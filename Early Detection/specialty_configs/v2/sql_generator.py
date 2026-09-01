"""
specialty_configs.sql_generator
--------------------------------
Turns the config loaded by loader.py into Snowflake SQL and runs it as a
pipeline of session TEMPORARY tables

Consequence: adding a brand-new Tier 1/2 signal, including a brand-new kind
of composite rule built from any/all/not/count_atoms_gate/count_buckets_gate,
means adding one entry to a features/*.json file. No Python change.

A Python change is only needed if a genuinely new *operator* is required
see OPS below, there are 5

Reads the SAME upstream evidence tables rddt_attr_sql.py already builds:
  ATTR_WIDE_NET_CANDIDATES, ATTR_EVID_CLAIM, ATTR_EVID_LAB_RESULT,
  ATTR_EVID_MEDICAL_HISTORY, ATTR_EVID_SURGICAL_HISTORY,
  ATTR_EVID_FAMILY_HISTORY, ATTR_EVID_CLINICAL_NOTES (optional)

Step 3 mirrors each source table, so the claim code columns are unpivoted here
into a single CODE_VALUE before per-atom matching.

Writes to a SEPARATE, distinctly-prefixed set of TEMPORARY tables
(ATTR_V2_*) so this can run side by side with the existing
rddt_specialty_sql.py output for comparison, without touching or risking
the proven pipeline.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from loader import Atom, Feature, SpecialtyConfig, load_config, load_shortlist_config

OPS = {"any", "all", "not", "count_atoms_gate", "count_buckets_gate"}

# Claim code columns, tagged by family so ICD predicates never run on CPT and vice versa.
CLAIM_DIAGNOSIS_COLUMNS = ("DIAGNOSIS_CODE", "OTHER_DIAGNOSIS_9", "OTHER_DIAGNOSIS_10")
CLAIM_PROCEDURE_COLUMNS = ("PROCEDURE_CODE",)
CLAIM_CODE_COLUMNS = (
    *[(c, "ICD") for c in CLAIM_DIAGNOSIS_COLUMNS],
    *[(c, "CPT_HCPCS") for c in CLAIM_PROCEDURE_COLUMNS],
)


def _esc(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace("'", "''")


def _sql(session, statement: str):
    return session.sql(statement).collect()


def _count(session, table: str) -> int:
    return int(session.sql(f"SELECT COUNT(*) AS N FROM {table}").collect()[0][0])


def _table_exists(session, name: str) -> bool:
    try:
        session.sql(f"SELECT 1 AS X FROM {name} LIMIT 1").collect()
        return True
    except Exception:
        return False


def _existing_cols(session, table: str, wanted: Sequence[str]) -> List[str]:
    try:
        desc = session.sql(f"DESCRIBE TABLE {table}").to_pandas()
        col0 = desc.columns[0]
        have = {str(x).upper() for x in desc[col0].tolist()}
        return [c for c in wanted if c.upper() in have]
    except Exception:
        return list(wanted)


# ---------------------------------------------------------------------------
# Column-routing: code patterns only ever touch code columns, keyword
# patterns only ever touch text columns. Never mixed.
# ---------------------------------------------------------------------------

def _icd_pred(col: str, prefixes: Sequence[str]) -> str:
    parts = []
    for p in prefixes:
        pu = p.upper()
        bare = pu.replace(".", "")
        parts.append(f"STARTSWITH(UPPER(REPLACE(COALESCE(TO_VARCHAR({col}), ''), '.', '')), '{_esc(bare)}')")
        parts.append(f"STARTSWITH(UPPER(COALESCE(TO_VARCHAR({col}), '')), '{_esc(pu)}')")
    return "(" + " OR ".join(parts) + ")" if parts else "FALSE"


def _cpt_pred(col: str, codes: Sequence[str]) -> str:
    if not codes:
        return "FALSE"
    inns = ", ".join(f"'{_esc(c.upper())}'" for c in codes)
    return f"UPPER(TRIM(COALESCE(TO_VARCHAR({col}), ''))) IN ({inns})"


def _snomed_norm_sql(col: str) -> str:
    """Keep digits only so 57406009, '57406009', and dotted forms compare equal."""
    return f"REGEXP_REPLACE(UPPER(TRIM(COALESCE(TO_VARCHAR({col}), ''))), '[^0-9]', '')"


def _snomed_pred(col: str, codes: Sequence[str]) -> str:
    digits = []
    seen = set()
    for c in codes:
        d = "".join(ch for ch in str(c) if ch.isdigit())
        if d and d not in seen:
            seen.add(d)
            digits.append(d)
    if not digits:
        return "FALSE"
    inns = ", ".join(f"'{_esc(d)}'" for d in digits)
    return f"{_snomed_norm_sql(col)} IN ({inns})"


def _snomed_row_pred(atom: Atom) -> str:
    """Match the unpivoted SNOMED_VALUE column (differential codes already excluded)."""
    return _snomed_pred("SNOMED_VALUE", atom.snomed_exact)


def _code_atom_pred(col: str, atom: Atom, code_system: Optional[str] = None) -> str:
    """Match one code column. If code_system is set, only that family is tested.

    ICD  -> ICD-10 prefixes and/or ICD-9 prefixes (diagnosis columns)
    CPT_HCPCS -> CPT exact and/or HCPCS exact (procedure columns)
    """
    bits = []
    if code_system is None or code_system == "ICD":
        if atom.icd10_prefixes:
            bits.append(_icd_pred(col, atom.icd10_prefixes))
        if atom.icd9_prefixes:
            bits.append(_icd_pred(col, atom.icd9_prefixes))
    if code_system is None or code_system == "CPT_HCPCS":
        if atom.cpt_exact:
            bits.append(_cpt_pred(col, atom.cpt_exact))
        if atom.hcpcs_exact:
            bits.append(_cpt_pred(col, atom.hcpcs_exact))
    return "(" + " OR ".join(bits) + ")" if bits else "FALSE"


def _claim_row_code_pred(atom: Atom) -> str:
    """System-aware claim match: ICD atoms only against ICD rows, CPT/HCPCS against procedure rows."""
    bits = []
    icd = _code_atom_pred("CODE_VALUE", atom, "ICD")
    if icd != "FALSE":
        bits.append(f"(CODE_SYSTEM = 'ICD' AND {icd})")
    proc = _code_atom_pred("CODE_VALUE", atom, "CPT_HCPCS")
    if proc != "FALSE":
        bits.append(f"(CODE_SYSTEM = 'CPT_HCPCS' AND {proc})")
    return "(" + " OR ".join(bits) + ")" if bits else "FALSE"


def _keyword_pred(txt_expr: str, keywords: Sequence[str]) -> str:
    if not keywords:
        return "FALSE"
    parts = [f"CONTAINS({txt_expr}, '{_esc(k.lower())}')" for k in keywords if str(k).strip()]
    return "(" + " OR ".join(parts) + ")" if parts else "FALSE"


def all_code_patterns_predicate(cfg: SpecialtyConfig, code_col: str) -> str:
    """Wide-net predicate: does this claim code row match ANY atom's claim code rule."""
    parts = [_claim_row_code_pred(a) for a in cfg.atoms.values() if a.has_code_rule()]
    return "(" + " OR ".join(p for p in parts if p != "FALSE") + ")" if parts else "FALSE"


def all_keyword_patterns_predicate(cfg: SpecialtyConfig, *text_cols: str) -> str:
    """Wide-net predicate: does any text column match ANY atom's keyword rule."""
    all_keywords: List[str] = []
    for a in cfg.atoms.values():
        all_keywords.extend(a.keywords)
    seen, uniq = set(), []
    for k in all_keywords:
        kl = k.lower()
        if kl not in seen:
            seen.add(kl)
            uniq.append(k)
    parts = []
    for col in text_cols:
        parts.append(_keyword_pred(f"LOWER(COALESCE({col}, ''))", uniq))
    return "(" + " OR ".join(parts) + ")" if parts else "FALSE"


# ---------------------------------------------------------------------------
# Stage 1: narrow the raw evidence tables to only rows that could match
# ---------------------------------------------------------------------------

def _claim_codes_unpivot_sql() -> str:
    """ATTR_EVID_CLAIM keeps codes in four columns; matching wants one CODE_VALUE."""
    parts = [
        f"""
        SELECT
          TRIM(TO_VARCHAR(PATIENT_ID)) AS PATIENT_ID,
          VISIT_ID,
          '{system}' AS CODE_SYSTEM,
          {col} AS CODE_VALUE,
          '{col}' AS CODE_SOURCE,
          FROM_DATE,
          TO_DATE
        FROM ATTR_EVID_CLAIM
        WHERE NULLIF(TRIM({col}), '') IS NOT NULL
        """
        for col, system in CLAIM_CODE_COLUMNS
    ]
    return "\nUNION ALL\n".join(parts)


def ensure_filtered_evidence(session, cfg: SpecialtyConfig) -> None:
    code_pred = all_code_patterns_predicate(cfg, "CODE_VALUE")
    lab_pred = all_keyword_patterns_predicate(cfg, "OBSERVATION_IDENTIFIER", "OBSERVATION_VALUE", "LAB_RESULT_NOTE")
    _sql(session, "CREATE OR REPLACE TEMPORARY TABLE ATTR_V2_EVID_CODES AS "
                  f"SELECT * FROM (\n{_claim_codes_unpivot_sql()}\n) C WHERE {code_pred}")
    _sql(session, "CREATE OR REPLACE TEMPORARY TABLE ATTR_V2_EVID_LAB AS "
                  f"SELECT l.* FROM ATTR_EVID_LAB_RESULT l WHERE {lab_pred}")
    print(f"TEMP ATTR_V2_EVID_CODES: {_count(session, 'ATTR_V2_EVID_CODES')}")
    print(f"TEMP ATTR_V2_EVID_LAB: {_count(session, 'ATTR_V2_EVID_LAB')}")


def _create_candidates(session) -> int:
    _sql(session, """
        CREATE OR REPLACE TEMPORARY TABLE ATTR_V2_CANDS AS
        SELECT DISTINCT TRIM(TO_VARCHAR(PATIENT_ID)) AS PATIENT_ID
        FROM ATTR_WIDE_NET_CANDIDATES
        WHERE PATIENT_ID IS NOT NULL
    """)
    n = _count(session, "ATTR_V2_CANDS")
    print(f"TEMP ATTR_V2_CANDS: {n}")
    return n


# ---------------------------------------------------------------------------
# Stage 2: one aggregate pass = every atom's CODE flag, per patient
# ---------------------------------------------------------------------------

def _create_code_atoms(session, cfg: SpecialtyConfig) -> None:
    selects = ["TRIM(TO_VARCHAR(PATIENT_ID)) AS PATIENT_ID"]
    for atom_id, atom in cfg.atoms.items():
        pred = _claim_row_code_pred(atom)
        selects.append(f"MAX(IFF({pred}, 1, 0)) AS {atom_id}_code")
    # bilateral CTS laterality-pair helper (G56.01 + G56.02 on different rows)
    selects.append(
        "MAX(IFF(STARTSWITH(UPPER(REPLACE(COALESCE(TO_VARCHAR(CODE_VALUE),''),'.','')), 'G5601') "
        "OR STARTSWITH(UPPER(COALESCE(TO_VARCHAR(CODE_VALUE),'')), 'G56.01'), 1, 0)) AS has_g5601"
    )
    selects.append(
        "MAX(IFF(STARTSWITH(UPPER(REPLACE(COALESCE(TO_VARCHAR(CODE_VALUE),''),'.','')), 'G5602') "
        "OR STARTSWITH(UPPER(COALESCE(TO_VARCHAR(CODE_VALUE),'')), 'G56.02'), 1, 0)) AS has_g5602"
    )
    sql = (
        "CREATE OR REPLACE TEMPORARY TABLE ATTR_V2_CODE_ATOMS AS\nSELECT\n  "
        + ",\n  ".join(selects)
        + "\nFROM ATTR_V2_EVID_CODES\nWHERE PATIENT_ID IS NOT NULL\nGROUP BY TRIM(TO_VARCHAR(PATIENT_ID))"
    )
    _sql(session, sql)
    print(f"TEMP ATTR_V2_CODE_ATOMS: {_count(session, 'ATTR_V2_CODE_ATOMS')}")


def _text_select(table: str, cols: Sequence[str]) -> str:
    concat = " || ' ' || ".join(f"COALESCE(TO_VARCHAR({c}), '')" for c in cols)
    return f"SELECT TRIM(TO_VARCHAR(PATIENT_ID)) AS PATIENT_ID, LOWER({concat}) AS TXT FROM {table} WHERE PATIENT_ID IS NOT NULL"


def _text_union_sql(session, include_visit_notes: bool) -> str:
    # Keyword columns only — never NoteType / FamilyMember / Status.
    sources = [
        ("ATTR_EVID_MEDICAL_HISTORY", ["VALUE", "SOURCE_CATEGORY"]),
        ("ATTR_EVID_SURGICAL_HISTORY", ["VALUE", "SOURCE_CATEGORY"]),
        ("ATTR_V2_EVID_LAB", ["OBSERVATION_IDENTIFIER", "OBSERVATION_VALUE", "LAB_RESULT_NOTE"]),
    ]
    if include_visit_notes:
        sources.append(("ATTR_EVID_CLINICAL_NOTES", ["NOTE_TEXT"]))
        sources.append(("ATTR_EVID_CLAIM", ["CLINICAL_NOTES"]))
    parts = []
    for table, cols in sources:
        if not _table_exists(session, table):
            continue
        use = _existing_cols(session, table, cols)
        if not use:
            continue
        parts.append(_text_select(table, use))
    if not parts:
        return "SELECT PATIENT_ID, '' AS TXT FROM ATTR_V2_CANDS WHERE 1 = 0"
    return "\nUNION ALL\n".join(parts)


def _family_text_union_sql(session) -> str:
    # Condition only — Status / FamilyMember are not clinical atom text.
    sources = [
        ("ATTR_EVID_FAMILY_HISTORY", ["CONDITION"]),
    ]
    parts = []
    for table, cols in sources:
        if not _table_exists(session, table):
            continue
        use = _existing_cols(session, table, cols)
        if not use:
            continue
        parts.append(_text_select(table, use))
    if not parts:
        return "SELECT PATIENT_ID, '' AS TXT FROM ATTR_V2_CANDS WHERE 1 = 0"
    return "\nUNION ALL\n".join(parts)


def _create_keyword_atoms(session, cfg: SpecialtyConfig, include_visit_notes: bool) -> None:
    patient_atoms = [a for a in cfg.atoms.values() if not a.family_tables_only]
    family_atoms = [a for a in cfg.atoms.values() if a.family_tables_only]

    sel = ["PATIENT_ID"]
    for atom in patient_atoms:
        pred = _keyword_pred("TXT", atom.keywords)
        sel.append(f"MAX(IFF({pred}, 1, 0)) AS {atom.atom_id}_kw")
    patient_sql = (
        "CREATE OR REPLACE TEMPORARY TABLE ATTR_V2_KW_PATIENT AS\nSELECT\n  "
        + ",\n  ".join(sel)
        + "\nFROM (\n" + _text_union_sql(session, include_visit_notes) + "\n) U\nGROUP BY PATIENT_ID"
    )
    _sql(session, patient_sql)
    print(f"TEMP ATTR_V2_KW_PATIENT: {_count(session, 'ATTR_V2_KW_PATIENT')}")

    if family_atoms:
        fsel = ["PATIENT_ID"]
        for atom in family_atoms:
            pred = _keyword_pred("TXT", atom.keywords)
            fsel.append(f"MAX(IFF({pred}, 1, 0)) AS {atom.atom_id}_kw")
        family_sql = (
            "CREATE OR REPLACE TEMPORARY TABLE ATTR_V2_KW_FAMILY AS\nSELECT\n  "
            + ",\n  ".join(fsel)
            + "\nFROM (\n" + _family_text_union_sql(session) + "\n) U\nGROUP BY PATIENT_ID"
        )
        _sql(session, family_sql)
        print(f"TEMP ATTR_V2_KW_FAMILY: {_count(session, 'ATTR_V2_KW_FAMILY')}")
    else:
        _sql(session, "CREATE OR REPLACE TEMPORARY TABLE ATTR_V2_KW_FAMILY AS SELECT PATIENT_ID FROM ATTR_V2_CANDS WHERE 1=0")


def _snomed_union_sql(session, tables: Sequence[str]) -> str:
    """Unpivot SNOMED + SECONDARY_SNOMED from history tables into one code column."""
    parts = []
    for table in tables:
        if not _table_exists(session, table):
            continue
        for col in _existing_cols(session, table, ["SNOMED", "SECONDARY_SNOMED"]):
            parts.append(
                f"SELECT TRIM(TO_VARCHAR(PATIENT_ID)) AS PATIENT_ID, {col} AS SNOMED_VALUE "
                f"FROM {table} "
                f"WHERE PATIENT_ID IS NOT NULL AND NULLIF(TRIM(TO_VARCHAR({col})), '') IS NOT NULL"
            )
    if not parts:
        return "SELECT PATIENT_ID, CAST(NULL AS VARCHAR) AS SNOMED_VALUE FROM ATTR_V2_CANDS WHERE 1 = 0"
    return "\nUNION ALL\n".join(parts)


def _create_snomed_atoms(session, cfg: SpecialtyConfig) -> None:
    """Fire an atom when a history SNOMED matches that atom's best/related SNOMED list."""
    patient_atoms = [a for a in cfg.atoms.values() if not a.family_tables_only]
    family_atoms = [a for a in cfg.atoms.values() if a.family_tables_only]

    sel = ["PATIENT_ID"]
    for atom in patient_atoms:
        pred = _snomed_row_pred(atom)
        sel.append(f"MAX(IFF({pred}, 1, 0)) AS {atom.atom_id}_snomed")
    patient_sql = (
        "CREATE OR REPLACE TEMPORARY TABLE ATTR_V2_SNOMED_PATIENT AS\nSELECT\n  "
        + ",\n  ".join(sel)
        + "\nFROM (\n"
        + _snomed_union_sql(session, ["ATTR_EVID_MEDICAL_HISTORY", "ATTR_EVID_SURGICAL_HISTORY"])
        + "\n) U\nGROUP BY PATIENT_ID"
    )
    _sql(session, patient_sql)
    print(f"TEMP ATTR_V2_SNOMED_PATIENT: {_count(session, 'ATTR_V2_SNOMED_PATIENT')}")

    if family_atoms:
        fsel = ["PATIENT_ID"]
        for atom in family_atoms:
            pred = _snomed_row_pred(atom)
            fsel.append(f"MAX(IFF({pred}, 1, 0)) AS {atom.atom_id}_snomed")
        family_sql = (
            "CREATE OR REPLACE TEMPORARY TABLE ATTR_V2_SNOMED_FAMILY AS\nSELECT\n  "
            + ",\n  ".join(fsel)
            + "\nFROM (\n"
            + _snomed_union_sql(session, ["ATTR_EVID_FAMILY_HISTORY"])
            + "\n) U\nGROUP BY PATIENT_ID"
        )
        _sql(session, family_sql)
        print(f"TEMP ATTR_V2_SNOMED_FAMILY: {_count(session, 'ATTR_V2_SNOMED_FAMILY')}")
    else:
        _sql(
            session,
            "CREATE OR REPLACE TEMPORARY TABLE ATTR_V2_SNOMED_FAMILY AS "
            "SELECT PATIENT_ID FROM ATTR_V2_CANDS WHERE 1=0",
        )


def _create_atoms_merged(session, cfg: SpecialtyConfig) -> None:
    cols = []
    for atom_id, atom in cfg.atoms.items():
        code_ref = f"COALESCE(C.{atom_id}_code, 0)"
        kw_ref = f"COALESCE({'F' if atom.family_tables_only else 'N'}.{atom_id}_kw, 0)"
        snomed_ref = f"COALESCE({'SF' if atom.family_tables_only else 'SP'}.{atom_id}_snomed, 0)"
        if atom_id == "cts_bilateral":
            expr = (
                f"IFF({code_ref} = 1 OR {kw_ref} = 1 OR {snomed_ref} = 1 "
                f"OR (COALESCE(C.has_g5601, 0) = 1 AND COALESCE(C.has_g5602, 0) = 1), 1, 0)"
            )
        else:
            expr = f"IFF({code_ref} = 1 OR {kw_ref} = 1 OR {snomed_ref} = 1, 1, 0)"
        cols.append(f"{expr} AS {atom_id}")

    inner = (
        "CREATE OR REPLACE TEMPORARY TABLE ATTR_V2_ATOMS AS\nWITH base AS (\n"
        "  SELECT\n    X.PATIENT_ID,\n    " + ",\n    ".join(cols) + "\n"
        "  FROM ATTR_V2_CANDS X\n"
        "  LEFT JOIN ATTR_V2_CODE_ATOMS C ON X.PATIENT_ID = C.PATIENT_ID\n"
        "  LEFT JOIN ATTR_V2_KW_PATIENT N ON X.PATIENT_ID = N.PATIENT_ID\n"
        "  LEFT JOIN ATTR_V2_KW_FAMILY F ON X.PATIENT_ID = F.PATIENT_ID\n"
        "  LEFT JOIN ATTR_V2_SNOMED_PATIENT SP ON X.PATIENT_ID = SP.PATIENT_ID\n"
        "  LEFT JOIN ATTR_V2_SNOMED_FAMILY SF ON X.PATIENT_ID = SF.PATIENT_ID\n"
        ")\nSELECT\n  PATIENT_ID,\n"
        + ",\n".join(
            ("  IFF(cts_any = 1 OR cts_bilateral = 1, 1, 0) AS cts_any" if a == "cts_any" else f"  {a}")
            for a in cfg.atoms.keys()
        )
        + "\nFROM base"
    )
    _sql(session, inner)
    print(f"TEMP ATTR_V2_ATOMS: {_count(session, 'ATTR_V2_ATOMS')}")


# ---------------------------------------------------------------------------
# The generic compiler: op-tree -> SQL boolean expression on ATTR_V2_ATOMS
# (alias A). This is the piece that replaces the hand-written composite_fn
# if/elif chain — any new any/all/not/count_* tree "just works" here.
# ---------------------------------------------------------------------------

def compile_logic(node: Dict[str, Any], cfg: SpecialtyConfig, alias: str = "A") -> str:
    op = node.get("op")
    if op not in OPS:
        raise ValueError(f"Unsupported logic op '{op}' — supported: {sorted(OPS)}")

    if op == "any":
        parts = [f"{alias}.{a} = 1" for a in (node.get("atoms") or [])]
        parts += [compile_logic(c, cfg, alias) for c in (node.get("children") or [])]
        if not parts:
            return "FALSE"
        return "(" + " OR ".join(parts) + ")"

    if op == "all":
        parts = [f"{alias}.{a} = 1" for a in (node.get("atoms") or [])]
        parts += [compile_logic(c, cfg, alias) for c in (node.get("children") or [])]
        if not parts:
            return "TRUE"
        return "(" + " AND ".join(parts) + ")"

    if op == "not":
        parts = [f"{alias}.{a} = 0" for a in (node.get("atoms") or [])]
        parts += [f"NOT {compile_logic(c, cfg, alias)}" for c in (node.get("children") or [])]
        if not parts:
            return "TRUE"
        return "(" + " AND ".join(parts) + ")"

    if op == "count_atoms_gate":
        atoms = node.get("atoms") or []
        threshold = int(node["threshold"])
        return "((" + " + ".join(f"{alias}.{a}" for a in atoms) + f") >= {threshold})"

    if op == "count_buckets_gate":
        bucket_set = cfg.buckets[node["bucket_set"]]
        threshold = int(node["threshold"])
        bucket_flags = [
            "IFF(" + " OR ".join(f"{alias}.{a} = 1" for a in atom_list) + ", 1, 0)"
            for atom_list in bucket_set.values()
        ]
        return "((" + " + ".join(bucket_flags) + f") >= {threshold})"

    raise AssertionError("unreachable")  # OPS check above guards this


def _create_feature_hits(session, cfg: SpecialtyConfig) -> None:
    unions: List[str] = []
    for feat in cfg.features:
        pred = compile_logic(feat.logic, cfg, alias="A")
        unions.append(f"""
            SELECT
              A.PATIENT_ID,
              '{_esc(feat.feature_id)}' AS feature_id,
              '{_esc(feat.specialty)}' AS specialty,
              {int(feat.tier)} AS tier,
              {"TRUE" if feat.shortlist_eligible else "FALSE"} AS shortlist_eligible,
              '{_esc(feat.short_name)}' AS short_name,
              'HIT' AS status
            FROM ATTR_V2_ATOMS A
            WHERE {pred}
        """)
    sql = "CREATE OR REPLACE TEMPORARY TABLE ATTR_V2_SPECIALTY_FEATURES AS\n" + "\nUNION ALL\n".join(unions)
    _sql(session, sql)
    print(f"TEMP ATTR_V2_SPECIALTY_FEATURES (HIT rows): {_count(session, 'ATTR_V2_SPECIALTY_FEATURES')}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_specialty_step4_v2(session, include_visit_notes: bool = True) -> Dict[str, str]:
    """
    Config-driven equivalent of rddt_specialty_sql.run_specialty_step4_sql.
    Writes ATTR_V2_* temporary tables (does not touch the existing ATTR_* ones).
    """
    print("=== specialty_configs Step 4 (config-driven, TEMPORARY only) ===")
    cfg = load_config()
    ensure_filtered_evidence(session, cfg)
    _create_candidates(session)
    print("SQL atom detect: codes ...")
    _create_code_atoms(session, cfg)
    print("SQL atom detect: keywords (groupby in warehouse) ...")
    _create_keyword_atoms(session, cfg, include_visit_notes=include_visit_notes)
    print("SQL atom detect: SNOMED (history tables) ...")
    _create_snomed_atoms(session, cfg)
    print("SQL merge atoms ...")
    _create_atoms_merged(session, cfg)
    print("SQL feature HITs (generic op-tree compiler) ...")
    _create_feature_hits(session, cfg)
    print("=== Done. All outputs are session TEMPORARY tables (ATTR_V2_*). ===")
    tables = {
        "atoms": "ATTR_V2_ATOMS",
        "feature_hits": "ATTR_V2_SPECIALTY_FEATURES",
    }
    for k, t in tables.items():
        print(f"  {k}: {t} ({_count(session, t)} rows)")
    return tables

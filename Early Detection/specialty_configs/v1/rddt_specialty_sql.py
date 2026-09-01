"""
RDDT v1.1 — SQL-first specialty Step 4 (Snowflake).

Does not query Census/Claim/Lab by client names. It only reads the canonical
session temps built by rddt_attr_sql.build_evidence:

  ATTR_WIDE_NET_CANDIDATES, ATTR_EVID_CLAIM, ATTR_EVID_LAB_RESULT,
  ATTR_EVID_MEDICAL_HISTORY, ATTR_EVID_SURGICAL_HISTORY,
  ATTR_EVID_FAMILY_HISTORY, ATTR_EVID_CLINICAL_NOTES

Social History is out of scope for this analysis (Excel: no need).

NLP uses VALUE / SOURCE_CATEGORY / lab notes / clinical note text.
SNOMED / SECONDARY_SNOMED on history tables match v2 atom best/related concept IDs.

Flow:
  ATTR_EVID_* → ATTR_ATOMS → ATTR_SPECIALTY_FEATURES → ATTR_SPECIALTY_TIERS
  → ATTR_KNOWN_ATTR / ATTR_SHORTLIST_LLM / ATTR_ARCH2_SUMMARY
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from rddt_specialty_config import (
    ATOMS,
    FEATURES,
    MSK_BUCKET_ATOMS,
    SHORTLIST_MIN_SPECIALTIES,
    SHORTLIST_N,
    SHORTLIST_SPECIALTIES,
    snowflake_lab_filter_sql,
)


def _esc(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace("'", "''")


def _sql(session, statement: str):
    return session.sql(statement).collect()


def _count(session, table: str) -> int:
    return int(session.sql(f"SELECT COUNT(*) AS N FROM {table}").collect()[0][0])


def _icd_pred(col: str, prefixes: Sequence[str]) -> str:
    parts = []
    for p in prefixes:
        pu = p.upper()
        bare = pu.replace(".", "")
        parts.append(
            f"STARTSWITH(UPPER(REPLACE(COALESCE(TO_VARCHAR({col}), ''), '.', '')), '{_esc(bare)}')"
        )
        parts.append(
            f"STARTSWITH(UPPER(COALESCE(TO_VARCHAR({col}), '')), '{_esc(pu)}')"
        )
    return "(" + " OR ".join(parts) + ")" if parts else "FALSE"


def _cpt_pred(col: str, codes: Sequence[str]) -> str:
    if not codes:
        return "FALSE"
    inns = ", ".join(f"'{_esc(c.upper())}'" for c in codes)
    return f"UPPER(TRIM(COALESCE(TO_VARCHAR({col}), ''))) IN ({inns})"


def _code_atom_pred(col: str, spec: Dict[str, Any], code_system: Optional[str] = None) -> str:
    bits = []
    prefs = tuple(spec.get("icd_prefixes") or ())
    cpts = tuple(spec.get("cpt_exact") or ())
    if code_system is None or code_system == "ICD":
        if prefs:
            bits.append(_icd_pred(col, prefs))
    if code_system is None or code_system == "CPT_HCPCS":
        if cpts:
            bits.append(_cpt_pred(col, cpts))
    return "(" + " OR ".join(bits) + ")" if bits else "FALSE"


def _claim_row_code_pred(spec: Dict[str, Any]) -> str:
    bits = []
    icd = _code_atom_pred("CODE_VALUE", spec, "ICD")
    if icd != "FALSE":
        bits.append(f"(CODE_SYSTEM = 'ICD' AND {icd})")
    proc = _code_atom_pred("CODE_VALUE", spec, "CPT_HCPCS")
    if proc != "FALSE":
        bits.append(f"(CODE_SYSTEM = 'CPT_HCPCS' AND {proc})")
    return "(" + " OR ".join(bits) + ")" if bits else "FALSE"


def _nlp_pred(txt_expr: str, patterns: Sequence[str]) -> str:
    if not patterns:
        return "FALSE"
    parts = [
        f"CONTAINS({txt_expr}, '{_esc(p.lower())}')" for p in patterns if str(p).strip()
    ]
    return "(" + " OR ".join(parts) + ")" if parts else "FALSE"


def _v2_snomed_by_atom() -> Dict[str, List[str]]:
    """Reuse v2 atom JSON SNOMED lists (v1 ATOMS have no snomed_exact field)."""
    v2_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "v2"))
    if v2_dir not in sys.path:
        sys.path.insert(0, v2_dir)
    from loader import load_config  # noqa: WPS433

    cfg = load_config()
    return {atom_id: list(atom.snomed_exact) for atom_id, atom in cfg.atoms.items()}


def _snomed_norm_sql(col: str) -> str:
    return f"REGEXP_REPLACE(UPPER(TRIM(COALESCE(TO_VARCHAR({col}), ''))), '[^0-9]', '')"


def _snomed_pred(col: str, codes: Sequence[str]) -> str:
    digits, seen = [], set()
    for c in codes:
        d = "".join(ch for ch in str(c) if ch.isdigit())
        if d and d not in seen:
            seen.add(d)
            digits.append(d)
    if not digits:
        return "FALSE"
    inns = ", ".join(f"'{_esc(d)}'" for d in digits)
    return f"{_snomed_norm_sql(col)} IN ({inns})"


# Code columns on ATTR_EVID_CLAIM, tagged by family so ICD never matches CPT rows.
CLAIM_DIAGNOSIS_COLUMNS = ("DIAGNOSIS_CODE", "OTHER_DIAGNOSIS_9", "OTHER_DIAGNOSIS_10")
CLAIM_PROCEDURE_COLUMNS = ("PROCEDURE_CODE",)
CLAIM_CODE_COLUMNS = (
    *[(c, "ICD") for c in CLAIM_DIAGNOSIS_COLUMNS],
    *[(c, "CPT_HCPCS") for c in CLAIM_PROCEDURE_COLUMNS],
)


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


def ensure_filtered_evidence(session) -> Tuple[int, int]:
    """Build TEMP filtered code/lab tables from Step 3 ATTR_EVID_*."""
    code_parts = [_claim_row_code_pred(spec) for _, spec in ATOMS.items()]
    code_pred = "(" + " OR ".join(p for p in code_parts if p != "FALSE") + ")" if code_parts else "FALSE"
    lab_pred = snowflake_lab_filter_sql(
        "OBSERVATION_IDENTIFIER", "OBSERVATION_VALUE", "LAB_RESULT_NOTE"
    )
    _sql(
        session,
        "CREATE OR REPLACE TEMPORARY TABLE ATTR_EVID_CODES_ARCH2 AS "
        f"SELECT * FROM (\n{_claim_codes_unpivot_sql()}\n) C WHERE {code_pred}",
    )
    _sql(
        session,
        "CREATE OR REPLACE TEMPORARY TABLE ATTR_EVID_LAB_ARCH2 AS "
        f"SELECT l.* FROM ATTR_EVID_LAB_RESULT l WHERE {lab_pred}",
    )
    n_codes = _count(session, "ATTR_EVID_CODES_ARCH2")
    n_lab = _count(session, "ATTR_EVID_LAB_ARCH2")
    print(f"TEMP ATTR_EVID_CODES_ARCH2: {n_codes}")
    print(f"TEMP ATTR_EVID_LAB_ARCH2: {n_lab}")
    return n_codes, n_lab


def _create_candidates(session) -> int:
    _sql(
        session,
        """
        CREATE OR REPLACE TEMPORARY TABLE ATTR_ARCH2_CANDS AS
        SELECT DISTINCT TRIM(TO_VARCHAR(PATIENT_ID)) AS PATIENT_ID
        FROM ATTR_WIDE_NET_CANDIDATES
        WHERE PATIENT_ID IS NOT NULL
        """,
    )
    n = _count(session, "ATTR_ARCH2_CANDS")
    print(f"TEMP ATTR_ARCH2_CANDS: {n}")
    return n


def _create_code_atoms(session) -> None:
    """Per-patient ICD/CPT atom flags + bilateral laterality pair."""
    selects = ["TRIM(TO_VARCHAR(PATIENT_ID)) AS PATIENT_ID"]
    for atom, spec in ATOMS.items():
        pred = _claim_row_code_pred(spec)
        selects.append(f"MAX(IFF({pred}, 1, 0)) AS {atom}_code")

    selects.append(
        "MAX(IFF("
        "STARTSWITH(UPPER(REPLACE(COALESCE(TO_VARCHAR(CODE_VALUE),''),'.','')), 'G5601') "
        "OR STARTSWITH(UPPER(COALESCE(TO_VARCHAR(CODE_VALUE),'')), 'G56.01'), 1, 0)) "
        "AS has_g5601"
    )
    selects.append(
        "MAX(IFF("
        "STARTSWITH(UPPER(REPLACE(COALESCE(TO_VARCHAR(CODE_VALUE),''),'.','')), 'G5602') "
        "OR STARTSWITH(UPPER(COALESCE(TO_VARCHAR(CODE_VALUE),'')), 'G56.02'), 1, 0)) "
        "AS has_g5602"
    )

    sql = (
        "CREATE OR REPLACE TEMPORARY TABLE ATTR_ARCH2_CODE_ATOMS AS\n"
        "SELECT\n  "
        + ",\n  ".join(selects)
        + "\nFROM ATTR_EVID_CODES_ARCH2\n"
        "WHERE PATIENT_ID IS NOT NULL\n"
        "GROUP BY TRIM(TO_VARCHAR(PATIENT_ID))"
    )
    _sql(session, sql)
    print(f"TEMP ATTR_ARCH2_CODE_ATOMS: {_count(session, 'ATTR_ARCH2_CODE_ATOMS')}")


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


def _text_select(table: str, cols: Sequence[str]) -> str:
    concat = " || ' ' || ".join(
        f"COALESCE(TO_VARCHAR({c}), '')" for c in cols
    )
    return f"""
        SELECT TRIM(TO_VARCHAR(PATIENT_ID)) AS PATIENT_ID,
               LOWER({concat}) AS TXT
        FROM {table}
        WHERE PATIENT_ID IS NOT NULL
        """


def _text_union_sql(session, include_visit_notes: bool) -> str:
    """Patient-level free text from the v1.1 evidence shape (not the old dictionary)."""
    sources = [
        ("ATTR_EVID_MEDICAL_HISTORY", ["VALUE", "SOURCE_CATEGORY"]),
        ("ATTR_EVID_SURGICAL_HISTORY", ["VALUE", "SOURCE_CATEGORY"]),
        (
            "ATTR_EVID_LAB_ARCH2",
            ["OBSERVATION_IDENTIFIER", "OBSERVATION_VALUE", "LAB_RESULT_NOTE"],
        ),
    ]
    if include_visit_notes:
        sources.append(("ATTR_EVID_CLINICAL_NOTES", ["NOTE_TEXT"]))
        sources.append(("ATTR_EVID_CLAIM", ["CLINICAL_NOTES"]))

    parts = []
    for table, cols in sources:
        if not _table_exists(session, table):
            print(f"  NLP skip (missing): {table}")
            continue
        use = _existing_cols(session, table, cols)
        if not use:
            print(f"  NLP skip (no text cols): {table}")
            continue
        parts.append(_text_select(table, use))
        print(f"  NLP source: {table} cols={use}")
    if not parts:
        return (
            "SELECT PATIENT_ID, '' AS TXT FROM ATTR_ARCH2_CANDS WHERE 1 = 0"
        )
    return "\nUNION ALL\n".join(parts)


def _family_text_union_sql(session) -> str:
    sources = [
        (
            "ATTR_EVID_FAMILY_HISTORY",
            ["CONDITION"],
        ),
    ]
    parts = []
    for table, cols in sources:
        if not _table_exists(session, table):
            print(f"  FHx NLP skip (missing): {table}")
            continue
        use = _existing_cols(session, table, cols)
        if not use:
            print(f"  FHx NLP skip (no text cols): {table}")
            continue
        parts.append(_text_select(table, use))
        print(f"  FHx NLP source: {table} cols={use}")
    if not parts:
        return (
            "SELECT PATIENT_ID, '' AS TXT FROM ATTR_ARCH2_CANDS WHERE 1 = 0"
        )
    return "\nUNION ALL\n".join(parts)


def _create_nlp_atoms(session, include_visit_notes: bool) -> None:
    patient_atoms = [
        (a, s) for a, s in ATOMS.items() if not s.get("family_tables_only")
    ]
    family_atoms = [
        (a, s) for a, s in ATOMS.items() if s.get("family_tables_only")
    ]

    # Patient / visit / lab NLP
    sel = ["PATIENT_ID"]
    for atom, spec in patient_atoms:
        nlp = tuple(spec.get("nlp") or ())
        pred = _nlp_pred("TXT", nlp)
        sel.append(f"MAX(IFF({pred}, 1, 0)) AS {atom}_nlp")

    patient_sql = (
        "CREATE OR REPLACE TEMPORARY TABLE ATTR_ARCH2_NLP_PATIENT AS\n"
        "SELECT\n  "
        + ",\n  ".join(sel)
        + "\nFROM (\n"
        + _text_union_sql(session, include_visit_notes)
        + "\n) U\nGROUP BY PATIENT_ID"
    )
    print(
        "Building TEMP ATTR_ARCH2_NLP_PATIENT "
        f"(include_visit_notes={include_visit_notes}) ..."
    )
    _sql(session, patient_sql)
    print(f"TEMP ATTR_ARCH2_NLP_PATIENT: {_count(session, 'ATTR_ARCH2_NLP_PATIENT')}")

    # Family-only NLP (e.g. fhx_sudden_death)
    if family_atoms:
        fsel = ["PATIENT_ID"]
        for atom, spec in family_atoms:
            nlp = tuple(spec.get("nlp") or ())
            pred = _nlp_pred("TXT", nlp)
            fsel.append(f"MAX(IFF({pred}, 1, 0)) AS {atom}_nlp")
        family_sql = (
            "CREATE OR REPLACE TEMPORARY TABLE ATTR_ARCH2_NLP_FAMILY AS\n"
            "SELECT\n  "
            + ",\n  ".join(fsel)
            + "\nFROM (\n"
            + _family_text_union_sql(session)
            + "\n) U\nGROUP BY PATIENT_ID"
        )
        _sql(session, family_sql)
        print(f"TEMP ATTR_ARCH2_NLP_FAMILY: {_count(session, 'ATTR_ARCH2_NLP_FAMILY')}")
    else:
        _sql(
            session,
            "CREATE OR REPLACE TEMPORARY TABLE ATTR_ARCH2_NLP_FAMILY AS "
            "SELECT PATIENT_ID FROM ATTR_ARCH2_CANDS WHERE 1=0",
        )


def _snomed_union_sql(session, tables: Sequence[str]) -> str:
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
        return (
            "SELECT PATIENT_ID, CAST(NULL AS VARCHAR) AS SNOMED_VALUE "
            "FROM ATTR_ARCH2_CANDS WHERE 1 = 0"
        )
    return "\nUNION ALL\n".join(parts)


def _create_snomed_atoms(session) -> None:
    snomed_by_atom = _v2_snomed_by_atom()
    patient_atoms = [
        (a, s) for a, s in ATOMS.items() if not s.get("family_tables_only")
    ]
    family_atoms = [
        (a, s) for a, s in ATOMS.items() if s.get("family_tables_only")
    ]

    sel = ["PATIENT_ID"]
    for atom, _spec in patient_atoms:
        pred = _snomed_pred("SNOMED_VALUE", snomed_by_atom.get(atom) or ())
        sel.append(f"MAX(IFF({pred}, 1, 0)) AS {atom}_snomed")
    _sql(
        session,
        "CREATE OR REPLACE TEMPORARY TABLE ATTR_ARCH2_SNOMED_PATIENT AS\nSELECT\n  "
        + ",\n  ".join(sel)
        + "\nFROM (\n"
        + _snomed_union_sql(session, ["ATTR_EVID_MEDICAL_HISTORY", "ATTR_EVID_SURGICAL_HISTORY"])
        + "\n) U\nGROUP BY PATIENT_ID",
    )
    print(f"TEMP ATTR_ARCH2_SNOMED_PATIENT: {_count(session, 'ATTR_ARCH2_SNOMED_PATIENT')}")

    if family_atoms:
        fsel = ["PATIENT_ID"]
        for atom, _spec in family_atoms:
            pred = _snomed_pred("SNOMED_VALUE", snomed_by_atom.get(atom) or ())
            fsel.append(f"MAX(IFF({pred}, 1, 0)) AS {atom}_snomed")
        _sql(
            session,
            "CREATE OR REPLACE TEMPORARY TABLE ATTR_ARCH2_SNOMED_FAMILY AS\nSELECT\n  "
            + ",\n  ".join(fsel)
            + "\nFROM (\n"
            + _snomed_union_sql(session, ["ATTR_EVID_FAMILY_HISTORY"])
            + "\n) U\nGROUP BY PATIENT_ID",
        )
        print(f"TEMP ATTR_ARCH2_SNOMED_FAMILY: {_count(session, 'ATTR_ARCH2_SNOMED_FAMILY')}")
    else:
        _sql(
            session,
            "CREATE OR REPLACE TEMPORARY TABLE ATTR_ARCH2_SNOMED_FAMILY AS "
            "SELECT PATIENT_ID FROM ATTR_ARCH2_CANDS WHERE 1=0",
        )


def _create_atoms_merged(session) -> None:
    """Merge code + NLP + bilateral rules into ATTR_ATOMS (0/1 flags)."""
    cols = []
    for atom, spec in ATOMS.items():
        family_only = bool(spec.get("family_tables_only"))
        code_ref = f"COALESCE(C.{atom}_code, 0)"
        if family_only:
            nlp_ref = f"COALESCE(F.{atom}_nlp, 0)"
            snomed_ref = f"COALESCE(SF.{atom}_snomed, 0)"
        else:
            nlp_ref = f"COALESCE(N.{atom}_nlp, 0)"
            snomed_ref = f"COALESCE(SP.{atom}_snomed, 0)"

        if atom == "cts_bilateral":
            expr = (
                f"IFF({code_ref} = 1 OR {nlp_ref} = 1 OR {snomed_ref} = 1 "
                f"OR (COALESCE(C.has_g5601, 0) = 1 AND COALESCE(C.has_g5602, 0) = 1), 1, 0)"
            )
        else:
            expr = f"IFF({code_ref} = 1 OR {nlp_ref} = 1 OR {snomed_ref} = 1, 1, 0)"
        cols.append(f"{expr} AS {atom}")

    # Placeholder; cts_any strengthened after in outer SELECT
    inner = (
        "CREATE OR REPLACE TEMPORARY TABLE ATTR_ATOMS AS\n"
        "WITH base AS (\n"
        "  SELECT\n"
        "    X.PATIENT_ID,\n    "
        + ",\n    ".join(cols)
        + "\n  FROM ATTR_ARCH2_CANDS X\n"
        "  LEFT JOIN ATTR_ARCH2_CODE_ATOMS C ON X.PATIENT_ID = C.PATIENT_ID\n"
        "  LEFT JOIN ATTR_ARCH2_NLP_PATIENT N ON X.PATIENT_ID = N.PATIENT_ID\n"
        "  LEFT JOIN ATTR_ARCH2_NLP_FAMILY F ON X.PATIENT_ID = F.PATIENT_ID\n"
        "  LEFT JOIN ATTR_ARCH2_SNOMED_PATIENT SP ON X.PATIENT_ID = SP.PATIENT_ID\n"
        "  LEFT JOIN ATTR_ARCH2_SNOMED_FAMILY SF ON X.PATIENT_ID = SF.PATIENT_ID\n"
        ")\n"
        "SELECT\n"
        "  PATIENT_ID,\n"
        + ",\n".join(
            (
                "  IFF(cts_any = 1 OR cts_bilateral = 1, 1, 0) AS cts_any"
                if a == "cts_any"
                else f"  {a}"
            )
            for a in ATOMS.keys()
        )
        + "\nFROM base"
    )
    _sql(session, inner)
    print(f"TEMP ATTR_ATOMS: {_count(session, 'ATTR_ATOMS')}")


def _feature_hit_sql(feat: Dict[str, Any]) -> Optional[str]:
    """Return SQL boolean on ATTR_ATOMS alias A for feature HIT, or None."""
    logic = feat.get("logic")
    if logic == "any_atom":
        atoms = feat.get("atoms") or ()
        if not atoms:
            return None
        return "(" + " OR ".join(f"A.{a} = 1" for a in atoms) + ")"
    if logic == "all_atoms":
        atoms = feat.get("atoms") or ()
        parts = []
        if atoms:
            parts.append("(" + " AND ".join(f"A.{a} = 1" for a in atoms) + ")")
        alt = feat.get("alt_all_atoms")
        if alt:
            parts.append("(" + " AND ".join(f"A.{a} = 1" for a in alt) + ")")
        return "(" + " OR ".join(parts) + ")" if parts else None
    if logic == "composite_fn":
        fn = feat.get("fn")
        if fn == "ortho_redflag_fhx_hf":
            return (
                "("
                "(A.cts_bilateral = 1 OR A.biceps_rupture = 1 "
                "OR (A.cts_any = 1 AND A.ctr_any = 1)) "
                "AND A.fhx_sudden_death = 1 AND A.hf_any = 1"
                ")"
            )
        if fn == "msk_regions_ge2":
            bucket_flags = []
            for _bucket, atom_names in MSK_BUCKET_ATOMS.items():
                bucket_flags.append(
                    "IFF(" + " OR ".join(f"A.{a} = 1" for a in atom_names) + ", 1, 0)"
                )
            return "(" + " + ".join(bucket_flags) + ") >= 2"
        if fn == "msk_manifest_ge3":
            keys = (
                "cts_any", "cts_bilateral", "ctr_any", "trigger_finger", "lumbar_stenosis",
                "biceps_rupture", "rotator_cuff", "arthroplasty", "dupuytren", "achilles",
                "congo_red",
            )
            return "(" + " + ".join(f"A.{k}" for k in keys) + ") >= 3"
        if fn == "reduced_gls_no_apical":
            return "(A.reduced_gls = 1 AND A.apical_sparing = 0)"
        if fn == "af_joint_hfpef":
            return (
                "("
                "A.af = 1 AND A.hfpef = 1 AND ("
                "A.arthroplasty = 1 OR A.cts_any = 1 OR A.lumbar_stenosis = 1 "
                "OR A.rotator_cuff = 1 OR A.trigger_finger = 1"
                "))"
            )
        return None
    return None


def _create_feature_hits(session) -> None:
    unions: List[str] = []
    for feat in FEATURES:
        pred = _feature_hit_sql(feat)
        if not pred:
            continue
        fid = _esc(feat["feature_id"])
        sp = _esc(feat["specialty"])
        tier = int(feat["tier"])
        shortlist = "TRUE" if feat.get("shortlist") else "FALSE"
        sname = _esc(feat.get("short_name") or "")
        unions.append(
            f"""
            SELECT
              A.PATIENT_ID,
              '{fid}' AS feature_id,
              '{sp}' AS specialty,
              {tier} AS tier,
              {shortlist} AS shortlist_eligible,
              '{sname}' AS short_name,
              'HIT' AS status
            FROM ATTR_ATOMS A
            WHERE {pred}
            """
        )
    if not unions:
        _sql(
            session,
            """
            CREATE OR REPLACE TEMPORARY TABLE ATTR_SPECIALTY_FEATURES AS
            SELECT
              CAST(NULL AS VARCHAR) AS PATIENT_ID,
              CAST(NULL AS VARCHAR) AS feature_id,
              CAST(NULL AS VARCHAR) AS specialty,
              CAST(NULL AS NUMBER) AS tier,
              CAST(NULL AS BOOLEAN) AS shortlist_eligible,
              CAST(NULL AS VARCHAR) AS short_name,
              CAST(NULL AS VARCHAR) AS status
            WHERE 1 = 0
            """,
        )
    else:
        sql = (
            "CREATE OR REPLACE TEMPORARY TABLE ATTR_SPECIALTY_FEATURES AS\n"
            + "\nUNION ALL\n".join(unions)
        )
        _sql(session, sql)
    print(f"TEMP ATTR_SPECIALTY_FEATURES (HIT rows): {_count(session, 'ATTR_SPECIALTY_FEATURES')}")


def _create_tiers(session) -> None:
    # Best tier per specialty, then feature list for that tier.
    _sql(
        session,
        """
        CREATE OR REPLACE TEMPORARY TABLE ATTR_ARCH2_BEST_TIER AS
        SELECT
          PATIENT_ID,
          specialty,
          MIN(tier) AS best_tier
        FROM ATTR_SPECIALTY_FEATURES
        WHERE shortlist_eligible AND tier IN (1, 2)
        GROUP BY PATIENT_ID, specialty
        """,
    )
    _sql(
        session,
        """
        CREATE OR REPLACE TEMPORARY TABLE ATTR_ARCH2_BEST_FEATS AS
        SELECT
          f.PATIENT_ID,
          f.specialty,
          b.best_tier,
          LISTAGG(DISTINCT f.feature_id, ',') WITHIN GROUP (ORDER BY f.feature_id)
            AS features
        FROM ATTR_SPECIALTY_FEATURES f
        JOIN ATTR_ARCH2_BEST_TIER b
          ON f.PATIENT_ID = b.PATIENT_ID
         AND f.specialty = b.specialty
         AND f.tier = b.best_tier
         AND f.shortlist_eligible
        GROUP BY f.PATIENT_ID, f.specialty, b.best_tier
        """,
    )

    pivot_tier = ",\n".join(
        f"MAX(IFF(specialty = '{sp}', best_tier, NULL)) AS {sp}_tier"
        for sp in SHORTLIST_SPECIALTIES
    )
    pivot_feat = ",\n".join(
        f"MAX(IFF(specialty = '{sp}', features, NULL)) AS {sp}_features"
        for sp in SHORTLIST_SPECIALTIES
    )
    select_sp = ",\n".join(
        f"p.{sp}_tier,\n            COALESCE(TO_VARCHAR(p.{sp}_features), '') AS {sp}_features"
        for sp in SHORTLIST_SPECIALTIES
    )
    # Qualify with a. — used in final SELECT from all_cands a
    n_expr = " + ".join(
        f"IFF(a.{sp}_tier IS NOT NULL, 1, 0)" for sp in SHORTLIST_SPECIALTIES
    )
    # RTRIM(..., ',') — avoid TRIM(BOTH ',' FROM ...) which Snowflake rejects
    specs_expr = (
        "RTRIM("
        + " || ".join(
            f"IFF(a.{sp}_tier IS NOT NULL, '{sp},', '')"
            for sp in SHORTLIST_SPECIALTIES
        )
        + ", ',')"
    )
    out_sp = ",\n".join(
        f"a.{sp}_tier,\n          a.{sp}_features" for sp in SHORTLIST_SPECIALTIES
    )

    _sql(
        session,
        f"""
        CREATE OR REPLACE TEMPORARY TABLE ATTR_SPECIALTY_TIERS AS
        WITH pivoted AS (
          SELECT
            PATIENT_ID,
            {pivot_tier},
            {pivot_feat}
          FROM ATTR_ARCH2_BEST_FEATS
          GROUP BY PATIENT_ID
        ),
        all_cands AS (
          SELECT
            c.PATIENT_ID,
            {select_sp}
          FROM ATTR_ARCH2_CANDS c
          LEFT JOIN pivoted p ON c.PATIENT_ID = p.PATIENT_ID
        ),
        t34 AS (
          SELECT
            PATIENT_ID,
            LISTAGG(DISTINCT feature_id, ',') WITHIN GROUP (ORDER BY feature_id)
              AS tier34_features
          FROM ATTR_SPECIALTY_FEATURES
          WHERE tier IN (3, 4)
          GROUP BY PATIENT_ID
        )
        SELECT
          a.PATIENT_ID,
          {out_sp},
          ({n_expr}) AS n_specialties_t12,
          {specs_expr} AS specialties_t12,
          IFF(({n_expr}) >= {int(SHORTLIST_MIN_SPECIALTIES)}, TRUE, FALSE)
            AS shortlist_pass,
          COALESCE(TO_VARCHAR(t.tier34_features), '') AS tier34_features
        FROM all_cands a
        LEFT JOIN t34 t ON a.PATIENT_ID = t.PATIENT_ID
        """,
    )
    print(f"TEMP ATTR_SPECIALTY_TIERS: {_count(session, 'ATTR_SPECIALTY_TIERS')}")


def _create_known_and_shortlist(session, shortlist_n: Optional[int]) -> None:
    _sql(
        session,
        """
        CREATE OR REPLACE TEMPORARY TABLE ATTR_KNOWN_ATTR AS
        SELECT
          PATIENT_ID,
          'KNOWN_ATTR_E85' AS list_name,
          'Already confirmed/labeled ATTR (E85.* / ATTR NLP)' AS list_meaning
        FROM ATTR_ATOMS
        WHERE confirmed_attr_e85 = 1
        """,
    )
    print(f"TEMP ATTR_KNOWN_ATTR: {_count(session, 'ATTR_KNOWN_ATTR')}")

    n_t1 = " + ".join(
        f"IFF(t.{sp}_tier = 1, 1, 0)" for sp in SHORTLIST_SPECIALTIES
    )
    why_bits = " || ".join(
        [
            f"IFF(t.{sp}_tier IS NOT NULL, '{sp}=T' || TO_VARCHAR(t.{sp}_tier) || '(' || COALESCE(t.{sp}_features,'') || ') | ', '')"
            for sp in SHORTLIST_SPECIALTIES
        ]
    )
    rank_filter = (
        f"WHERE rank <= {int(shortlist_n)}" if shortlist_n is not None else ""
    )
    _sql(
        session,
        f"""
        CREATE OR REPLACE TEMPORARY TABLE ATTR_SHORTLIST_LLM AS
        SELECT *
        FROM (
          SELECT
            t.*,
            ({n_t1}) AS n_t1,
            'SHORTLIST_LLM' AS list_name,
            'Tier1/Tier2 in >= {int(SHORTLIST_MIN_SPECIALTIES)} of Ortho/Cardio/Neuro (not a diagnosis)'
              AS list_meaning,
            'n_specialties_t12>={int(SHORTLIST_MIN_SPECIALTIES)}; exclude known E85' AS filter,
            RTRIM(TRIM({why_bits}), '| ') AS why_text,
            ROW_NUMBER() OVER (
              ORDER BY t.n_specialties_t12 DESC, ({n_t1}) DESC, t.PATIENT_ID
            ) AS rank
          FROM ATTR_SPECIALTY_TIERS t
          WHERE t.shortlist_pass
            AND NOT EXISTS (
              SELECT 1 FROM ATTR_KNOWN_ATTR k WHERE k.PATIENT_ID = t.PATIENT_ID
            )
        )
        {rank_filter}
        """,
    )
    print(f"TEMP ATTR_SHORTLIST_LLM: {_count(session, 'ATTR_SHORTLIST_LLM')}")


def _create_summary(session) -> pd.DataFrame:
    n_cand = _count(session, "ATTR_ARCH2_CANDS")
    n_known = _count(session, "ATTR_KNOWN_ATTR")
    n_pass = int(
        session.sql(
            "SELECT COUNT(*) AS N FROM ATTR_SPECIALTY_TIERS WHERE shortlist_pass"
        ).collect()[0][0]
    )
    n_keep = _count(session, "ATTR_SHORTLIST_LLM")
    summary = pd.DataFrame(
        [
            {
                "n_candidates": n_cand,
                "n_known_attr": n_known,
                "n_shortlist_pass": n_pass,
                "n_shortlist_kept": n_keep,
                "shortlist_rule": f">={SHORTLIST_MIN_SPECIALTIES} specialties with Tier1 or Tier2",
                "engine": "SQL-first (session TEMPORARY tables only)",
                "storage": "session TEMPORARY tables only (no permanent / no stage)",
            }
        ]
    )
    # write summary temp via values
    _sql(
        session,
        f"""
        CREATE OR REPLACE TEMPORARY TABLE ATTR_ARCH2_SUMMARY AS
        SELECT
          {n_cand} AS n_candidates,
          {n_known} AS n_known_attr,
          {n_pass} AS n_shortlist_pass,
          {n_keep} AS n_shortlist_kept,
          '{_esc(f">={SHORTLIST_MIN_SPECIALTIES} specialties with Tier1 or Tier2")}'
            AS shortlist_rule,
          'SQL-first (session TEMPORARY tables only)' AS engine,
          'session TEMPORARY tables only (no permanent / no stage)' AS storage
        """,
    )
    print("TEMP ATTR_ARCH2_SUMMARY written")
    print(summary)
    return summary


def run_specialty_step4_sql(
    session,
    shortlist_n: Optional[int] = SHORTLIST_N,
    include_visit_notes: bool = True,
    skip_filter: bool = False,
) -> Dict[str, Any]:
    """
    Run Architecture 2 Step 4 entirely in Snowflake TEMPORARY tables.

    Parameters
    ----------
    session : snowflake.snowpark.Session
    shortlist_n : max shortlist rows (None = keep all passers)
    include_visit_notes : if True, NLP-scan ATTR_EVID_CLINICAL_NOTES.NOTE_TEXT in SQL
    skip_filter : if True, assume ATTR_EVID_CODES_ARCH2 / LAB_ARCH2 already exist
    """
    print("=== Architecture 2 Step 4 SQL-first (TEMPORARY only) ===")
    if not skip_filter:
        ensure_filtered_evidence(session)
    else:
        print("skip_filter=True — using existing ATTR_EVID_CODES_ARCH2 / LAB_ARCH2")

    _create_candidates(session)
    print("SQL atom detect: codes ...")
    _create_code_atoms(session)
    print("SQL atom detect: NLP (groupby in warehouse) ...")
    _create_nlp_atoms(session, include_visit_notes=include_visit_notes)
    print("SQL atom detect: SNOMED (history tables) ...")
    _create_snomed_atoms(session)
    print("SQL merge atoms ...")
    _create_atoms_merged(session)
    print("SQL feature HITs ...")
    _create_feature_hits(session)
    print("SQL specialty tiers ...")
    _create_tiers(session)
    print("SQL known ATTR + shortlist ...")
    _create_known_and_shortlist(session, shortlist_n=shortlist_n)
    summary = _create_summary(session)

    tables = {
        "atoms": "ATTR_ATOMS",
        "feature_hits": "ATTR_SPECIALTY_FEATURES",
        "specialty_tiers": "ATTR_SPECIALTY_TIERS",
        "known_attr": "ATTR_KNOWN_ATTR",
        "shortlist": "ATTR_SHORTLIST_LLM",
        "summary": "ATTR_ARCH2_SUMMARY",
    }
    print("=== Done. All outputs are session TEMPORARY tables. ===")
    for k, t in tables.items():
        print(f"  {k}: {t} ({_count(session, t)} rows)")
    return {"tables": tables, "summary": summary}

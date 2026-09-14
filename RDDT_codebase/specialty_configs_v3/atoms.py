# -*- coding: utf-8 -*-
"""Atom extraction: evidence streams -> atom hits -> ATTR_V3_ATOMS wide table.

Reads atoms/*.json (v3 nested schema) and turns each atom's codes/keywords
into SQL predicates, then matches them against the ATTR_EVID_* evidence
tables built in Stage 1-3 (see rddt_attr_sql.py / pipeline.run_stages_1_to_3).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from common import (
    AA_BUCKETS,
    AL_BUCKETS,
    ATTRV_BUCKETS,
    WT01_GATE_BUCKETS,
    PHENOTYPE_OVERLAY_FILES,
    _esc,
    _sql,
    keyword_wildcard_variations,
    load_ortho_cluster,
    load_overlay_file,
)

# ---------------------------------------------------------------------------
# Atom extraction helpers (v3 nested schema)
# ---------------------------------------------------------------------------

def _code_list(atom: Dict[str, Any], family: str) -> List[str]:
    """Codes that should fire this atom. Skips mapping_role=DIFFERENTIAL_EXCLUDE
    (that role means "this code indicates a DIFFERENT condition, not this atom" -
    e.g. a tendon strain code on a rupture atom, or plain osteoarthritis on an
    arthroplasty atom - so it must never contribute to a positive match).

    Every other role (DIRECT_TARGET, PROXY_SUPPORT, or none) still fires the atom
    on its own for now - PROXY_SUPPORT's requires_corroboration / can_fire_atom_alone
    are not yet enforced. See KNOWN_GAPS.md."""
    codes = (((atom.get("extraction") or {}).get("codes") or {}).get(family)) or []
    out: List[str] = []
    seen: Set[str] = set()
    for c in codes:
        if c.get("mapping_role") == "DIFFERENTIAL_EXCLUDE":
            continue
        code = str(c.get("code") or "").strip()
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _keyword_list(atom: Dict[str, Any]) -> List[str]:
    ext = atom.get("extraction") or {}
    raw = ext.get("keywords") or ext.get("candidate_keywords") or []
    out: List[str] = []
    seen: Set[str] = set()
    for item in raw:
        if isinstance(item, str):
            val = item.strip()
        elif isinstance(item, dict):
            val = str(item.get("value") or item.get("term") or "").strip()
        else:
            continue
        if len(val) < 3:
            continue
        key = val.lower()
        if key not in seen:
            seen.add(key)
            out.append(val)
    return out


def _structured_rules(atom: Dict[str, Any]) -> List[Dict[str, Any]]:
    ext = atom.get("extraction") or {}
    return list(ext.get("structured_rules") or ext.get("candidate_structured_rules") or [])


def _atom_ids_for_buckets(
    config_root,
    buckets: Sequence[str],
    extra_atom_ids: Sequence[str] = (),
    overlay_filenames: Optional[Sequence[str]] = None,
) -> List[str]:
    """Union of atom_ids across the given overlay files (default: every
    PHENOTYPE_OVERLAY_FILES entry) whose bucket is in `buckets`, plus whatever's
    in `extra_atom_ids` (composite members, guardrail trigger atoms, etc).

    overlay_filenames MUST be passed explicitly by every caller that needs a
    fixed, phenotype-specific atom set (wt01_atom_ids, attrv_atom_ids) -
    PHENOTYPE_OVERLAY_FILES is a shared, growing dict, so scanning "every
    registered phenotype" silently changes an existing caller's atom set the
    moment a new phenotype is registered. That's the bug this parameter fixes.
    """
    root = config_root
    ids: List[str] = []
    seen: Set[str] = set()
    filenames = (
        list(overlay_filenames)
        if overlay_filenames is not None
        else list(PHENOTYPE_OVERLAY_FILES.values())
    )

    for fname in filenames:
        for o in load_overlay_file(root, fname):
            if o.get("is_composite") or o.get("composite_rule_id"):
                continue
            aid = o.get("atom_id")
            if not aid or aid in seen:
                continue
            if o.get("bucket") not in buckets:
                continue
            if o.get("tier") is None:
                continue
            seen.add(aid)
            ids.append(aid)

    for aid in extra_atom_ids:
        if aid not in seen:
            seen.add(aid)
            ids.append(aid)
    return ids


def wt01_atom_ids(
    config_root,
    cluster: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """All atoms referenced by WT01 bucket-tier SQL for ORTHO/CARDIO.

    Must be the union of ORTHO/CARDIO atoms across GENERAL_AMYLOID, ATTR_COMMON,
    and ATTRwt overlays (each phenotype has its own tier map), plus WT04 composite
    members and WT25/WT26 guardrail triggers. Otherwise create_bucket_tiers would
    reference ATTR_V3_ATOMS columns that were never extracted.
    """
    root = config_root
    cluster = cluster or load_ortho_cluster(root)

    composite_member_atoms: Set[str] = set()
    for sig in cluster.get("member_signals") or []:
        composite_member_atoms.update(sig.get("atom_ids") or [])

    extras = sorted(composite_member_atoms) + ["mgus", "renal_differential_assessment"]
    wt01_overlay_files = [
        PHENOTYPE_OVERLAY_FILES["GENERAL_AMYLOID"],
        PHENOTYPE_OVERLAY_FILES["ATTR_COMMON"],
        PHENOTYPE_OVERLAY_FILES["ATTRwt"],
    ]
    return _atom_ids_for_buckets(root, WT01_GATE_BUCKETS, extras, wt01_overlay_files)


# NEURO_PLUS_SYSTEMIC (V03)'s preferred anchor atoms - not guaranteed to already
# carry a bucket+tier in attrv.json (the composite can fall back to a generic
# NEURO tier<=2 check instead), so pulled in explicitly here to be safe.
ATTRV_COMPOSITE_ANCHOR_ATOMS = ("length_dependent", "emg_axonal")

# V38 guardrail (ALTERNATIVE_NEUROPATHY) trigger atoms - not tagged with a
# bucket/tier in any overlay file (guardrail-only, same shape as WT25/26's
# mgus/renal_differential_assessment), so pulled in explicitly here.
# diabetes (V37) IS tagged NEURO T3 MODIFIER in attrv.json and would already
# come through the bucket scan; listed here too so ATTRV_GUARDRAIL_ATOMS stays
# the complete set of ATTRv atom-triggered guardrail triggers (dedupe is fine).
ATTRV_GUARDRAIL_ATOMS = ("autoimmune_disease", "autoantibody_result", "diabetes")


def attrv_atom_ids(config_root) -> List[str]:
    """All atoms referenced by ATTRv bucket-tier SQL (NEURO/AUTONOMIC/HEREDITARY/
    OCULAR/CARDIO/ORTHO/RENAL), plus the NEURO_PLUS_SYSTEMIC composite's anchor
    atoms and the V37/V38 guardrails' trigger atoms. Independent of wt01_atom_ids -
    callers needing both phenotypes computed together should take the union of
    both functions' output.

    Also scans GENERAL_AMYLOID and ATTR_COMMON's own overlays (not just
    attrv.json) - V_RULE_01-06 funnel through ATTR_COMMON and V_RULE_07 funnels
    through GENERAL_AMYLOID, so those phenotypes' OWN bucket-tier rows (for the
    same HEREDITARY/RENAL/NEURO/... buckets) must be computed too, or the funnel
    tables (ATTR_V3_AC_PASS_IDS / ATTR_V3_GA_PASS_IDS) would stay empty for
    ATTRv-shaped patients. GENERAL_AMYLOID's other buckets (MUCOSAL_CUTANEOUS,
    GI_HEPATIC, HEME_CLONAL, INFLAMMATORY_DRIVER) are NOT covered here - not
    needed for V_RULE_07 specifically, since it also directly requires
    HEREDITARY+RENAL, which already satisfies GA01 through that same pair."""
    attrv_overlay_files = [
        PHENOTYPE_OVERLAY_FILES["GENERAL_AMYLOID"],
        PHENOTYPE_OVERLAY_FILES["ATTR_COMMON"],
        PHENOTYPE_OVERLAY_FILES["ATTRv"],
    ]
    extras = ATTRV_COMPOSITE_ANCHOR_ATOMS + ATTRV_GUARDRAIL_ATOMS
    return _atom_ids_for_buckets(config_root, ATTRV_BUCKETS, extras, attrv_overlay_files)


def al_atom_ids(config_root) -> List[str]:
    """All atoms referenced by AL bucket-tier SQL (HEME_CLONAL/RENAL/CARDIO/NEURO/
    GI_HEPATIC/MUCOSAL_CUTANEOUS). Independent of wt01_atom_ids/attrv_atom_ids -
    callers needing all phenotypes computed together should take the union of
    every relevant function's output.

    AL22/AL23 (guardrails) reuse ORTHO atoms already extracted by wt01_atom_ids
    (cts_*/ctr_any/lumbar_*/biceps_rupture), so no extra atom-id list is needed
    here for those - unlike V38, which needed atoms not extracted anywhere else.

    Scans GENERAL_AMYLOID's own overlay too (not just al.json) - all 7 AL_RULEs
    funnel through GENERAL_AMYLOID, so GA's OWN bucket-tier rows for these same
    buckets must be computed too, or ATTR_V3_GA_PASS_IDS would stay empty for
    AL-shaped patients."""
    al_overlay_files = [
        PHENOTYPE_OVERLAY_FILES["GENERAL_AMYLOID"],
        PHENOTYPE_OVERLAY_FILES["AL"],
    ]
    return _atom_ids_for_buckets(config_root, AL_BUCKETS, (), al_overlay_files)


# AA26/27/28 guardrail trigger atoms not tagged with a bucket/tier in aa.json
# (guardrail-only, same shape as WT25/26's mgus/renal_differential_assessment
# and V38's ATTRV_GUARDRAIL_ATOMS). mgus/plasma_cell_dyscrasia (AA28) are
# already extracted elsewhere (mgus via wt01_atom_ids' extras, plasma_cell_
# dyscrasia via al_atom_ids' HEME_CLONAL scan) whenever this phenotype runs
# alongside WT01/AL - listed here too so aa_atom_ids stays self-sufficient if
# ever called on its own (extras dedupe against the bucket scan automatically).
AA_GUARDRAIL_ATOMS = (
    "persistent_proteinuria", "urine_sediment_result", "mgus", "plasma_cell_dyscrasia",
)

# RENAL_DISPROPORTIONATE (AA21) composite's anchor atoms beyond what's already
# tagged RENAL in aa.json's own overlay (urine_protein_result, nephrotic_range_
# proteinuria, nephrotic_syndrome, microalbuminuria, creatinine_result, egfr_
# result, kidney_failure, hypoalbuminemia, peripheral_edema) - the composite's
# min_signal_atom_ids also lists two atoms that carry no bucket/tier of their
# own in aa.json (they're used as raw evidence for the composite, not as
# independently-tiered RENAL bucket members).
AA_COMPOSITE_ANCHOR_ATOMS = ("renal_dysfunction", "progressive_proteinuria")


def aa_atom_ids(config_root) -> List[str]:
    """All atoms referenced by AA bucket-tier SQL (INFLAMMATORY_DRIVER/
    INFLAMMATORY_ACTIVITY/RENAL/SUSCEPTIBILITY/GI_HEPATIC/SYSTEMIC_CONTEXT),
    plus the RENAL_DISPROPORTIONATE composite's extra anchor atoms and the
    AA26/27/28 guardrails' trigger atoms. Independent of wt01_atom_ids/
    attrv_atom_ids/al_atom_ids - callers needing all phenotypes computed
    together should take the union of every relevant function's output.

    Scans GENERAL_AMYLOID's own overlay too (not just aa.json) - both AA_RULE_01
    and AA_RULE_02 funnel through GENERAL_AMYLOID, and GA02 (GENERAL_AMYLOID's
    own ORG_PLUS_ETIOLOGY rule) lists INFLAMMATORY_DRIVER as an etiology option
    in its OWN overlay - those GENERAL_AMYLOID-tagged rows need the same atoms
    extracted, or ATTR_V3_GA_PASS_IDS would stay empty for AA-shaped patients."""
    aa_overlay_files = [
        PHENOTYPE_OVERLAY_FILES["GENERAL_AMYLOID"],
        PHENOTYPE_OVERLAY_FILES["AA"],
    ]
    extras = AA_COMPOSITE_ANCHOR_ATOMS + AA_GUARDRAIL_ATOMS
    return _atom_ids_for_buckets(config_root, AA_BUCKETS, extras, aa_overlay_files)


# ---------------------------------------------------------------------------
# SQL builders
# ---------------------------------------------------------------------------

CLAIM_DIAG_COLS = ("DIAGNOSIS_CODE", "OTHER_DIAGNOSIS_9", "OTHER_DIAGNOSIS_10")
CLAIM_PROC_COLS = ("PROCEDURE_CODE",)


def _icd_pred(col: str, codes: Sequence[str]) -> str:
    parts = []
    for p in codes:
        pu = p.upper()
        bare = pu.replace(".", "")
        parts.append(
            f"STARTSWITH(UPPER(REPLACE(COALESCE(TO_VARCHAR({col}), ''), '.', '')), '{_esc(bare)}')"
        )
        parts.append(f"STARTSWITH(UPPER(COALESCE(TO_VARCHAR({col}), '')), '{_esc(pu)}')")
    return "(" + " OR ".join(parts) + ")" if parts else "FALSE"


def _exact_pred(col: str, codes: Sequence[str]) -> str:
    if not codes:
        return "FALSE"
    inns = ", ".join(f"'{_esc(c.upper())}'" for c in codes)
    return f"UPPER(TRIM(COALESCE(TO_VARCHAR({col}), ''))) IN ({inns})"


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
    norm = f"REGEXP_REPLACE(UPPER(TRIM(COALESCE(TO_VARCHAR({col}), ''))), '[^0-9]', '')"
    return f"{norm} IN ({inns})"


def _kw_pred(col: str, keywords: Sequence[str], limit: int = 40) -> str:
    """Keyword match with wildcard / variation ILIKE patterns (same as inspection nets)."""
    parts: List[str] = []
    for kw in keywords[:limit]:
        for pat in keyword_wildcard_variations(kw):
            parts.append(
                f"UPPER(COALESCE(TO_VARCHAR({col}), '')) ILIKE '{_esc(pat.upper())}'"
            )
            if len(parts) >= 120:
                break
        if len(parts) >= 120:
            break
    return "(" + " OR ".join(parts) + ")" if parts else "FALSE"


def create_evidence_code_unpivot(session) -> str:
    """Long claim/history code stream for atom matching."""
    table = "ATTR_V3_WT01_CODE_STREAM"
    parts = []
    for col in CLAIM_DIAG_COLS:
        parts.append(
            f"""
            SELECT PATIENT_ID, TRY_TO_DATE(TO_VARCHAR(FROM_DATE)) AS EVENT_DATE,
                   UPPER(TRIM(TO_VARCHAR({col}))) AS CODE_VALUE, 'ICD' AS CODE_SYSTEM, 'CLAIM' AS SRC
            FROM ATTR_EVID_CLAIM
            WHERE {col} IS NOT NULL AND TRIM(TO_VARCHAR({col})) <> ''
            """
        )
    for col in CLAIM_PROC_COLS:
        parts.append(
            f"""
            SELECT PATIENT_ID, TRY_TO_DATE(TO_VARCHAR(FROM_DATE)) AS EVENT_DATE,
                   UPPER(TRIM(TO_VARCHAR({col}))) AS CODE_VALUE, 'CPT_HCPCS' AS CODE_SYSTEM, 'CLAIM' AS SRC
            FROM ATTR_EVID_CLAIM
            WHERE {col} IS NOT NULL AND TRIM(TO_VARCHAR({col})) <> ''
            """
        )
    for hist, date_col in (
        ("ATTR_EVID_SURGICAL_HISTORY", "EVENT_DATE"),
        ("ATTR_EVID_MEDICAL_HISTORY", "EVENT_DATE"),
    ):
        parts.append(
            f"""
            SELECT PATIENT_ID, TRY_TO_DATE(TO_VARCHAR({date_col})) AS EVENT_DATE,
                   REGEXP_REPLACE(UPPER(TRIM(COALESCE(TO_VARCHAR(SNOMED), ''))), '[^0-9]', '') AS CODE_VALUE,
                   'SNOMED' AS CODE_SYSTEM, '{hist}' AS SRC
            FROM {hist}
            WHERE SNOMED IS NOT NULL AND TRIM(TO_VARCHAR(SNOMED)) <> ''
            """
        )
        parts.append(
            f"""
            SELECT PATIENT_ID, TRY_TO_DATE(TO_VARCHAR({date_col})) AS EVENT_DATE,
                   REGEXP_REPLACE(UPPER(TRIM(COALESCE(TO_VARCHAR(SECONDARY_SNOMED), ''))), '[^0-9]', '') AS CODE_VALUE,
                   'SNOMED' AS CODE_SYSTEM, '{hist}' AS SRC
            FROM {hist}
            WHERE SECONDARY_SNOMED IS NOT NULL AND TRIM(TO_VARCHAR(SECONDARY_SNOMED)) <> ''
            """
        )
    # Family history: SNOMED only (no SECONDARY_SNOMED on ATTR_EVID_FAMILY_HISTORY)
    parts.append(
        """
        SELECT PATIENT_ID, TRY_TO_DATE(TO_VARCHAR(EVENT_DATE)) AS EVENT_DATE,
               REGEXP_REPLACE(UPPER(TRIM(COALESCE(TO_VARCHAR(SNOMED), ''))), '[^0-9]', '') AS CODE_VALUE,
               'SNOMED' AS CODE_SYSTEM, 'ATTR_EVID_FAMILY_HISTORY' AS SRC
        FROM ATTR_EVID_FAMILY_HISTORY
        WHERE SNOMED IS NOT NULL AND TRIM(TO_VARCHAR(SNOMED)) <> ''
        """
    )
    sql = f"CREATE OR REPLACE TEMPORARY TABLE {table} AS\n" + "\nUNION ALL\n".join(parts)
    _sql(session, sql)
    return table


def create_evidence_text_stream(session) -> str:
    table = "ATTR_V3_WT01_TEXT_STREAM"
    parts = [
        """
        SELECT PATIENT_ID, TRY_TO_DATE(TO_VARCHAR(FROM_DATE)) AS EVENT_DATE,
               TO_VARCHAR(CLINICAL_NOTES) AS TXT, 'CLAIM_NOTES' AS SRC
        FROM ATTR_EVID_CLAIM WHERE CLINICAL_NOTES IS NOT NULL
        """,
        """
        SELECT PATIENT_ID, TRY_TO_DATE(TO_VARCHAR(NOTE_DATE)) AS EVENT_DATE,
               TO_VARCHAR(NOTE_TEXT) AS TXT, 'CLINICAL_NOTE' AS SRC
        FROM ATTR_EVID_CLINICAL_NOTES WHERE NOTE_TEXT IS NOT NULL
        """,
        """
        SELECT PATIENT_ID, TRY_TO_DATE(TO_VARCHAR(EVENT_DATE)) AS EVENT_DATE,
               COALESCE(TO_VARCHAR(SOURCE_CATEGORY),'') || ' ' || COALESCE(TO_VARCHAR(VALUE),'') AS TXT,
               'SURGICAL_HISTORY' AS SRC
        FROM ATTR_EVID_SURGICAL_HISTORY
        WHERE VALUE IS NOT NULL OR SOURCE_CATEGORY IS NOT NULL
        """,
        """
        SELECT PATIENT_ID, TRY_TO_DATE(TO_VARCHAR(EVENT_DATE)) AS EVENT_DATE,
               COALESCE(TO_VARCHAR(SOURCE_CATEGORY),'') || ' ' || COALESCE(TO_VARCHAR(VALUE),'') AS TXT,
               'MEDICAL_HISTORY' AS SRC
        FROM ATTR_EVID_MEDICAL_HISTORY
        WHERE VALUE IS NOT NULL OR SOURCE_CATEGORY IS NOT NULL
        """,
        """
        SELECT PATIENT_ID, TRY_TO_DATE(TO_VARCHAR(EVENT_DATE)) AS EVENT_DATE,
               TO_VARCHAR(CONDITION) AS TXT, 'FAMILY_HISTORY' AS SRC
        FROM ATTR_EVID_FAMILY_HISTORY WHERE CONDITION IS NOT NULL
        """,
        """
        SELECT PATIENT_ID, TRY_TO_DATE(TO_VARCHAR(OBSERVATION_DATETIME)) AS EVENT_DATE,
               COALESCE(TO_VARCHAR(OBSERVATION_IDENTIFIER),'') || ' ' ||
               COALESCE(TO_VARCHAR(OBSERVATION_VALUE),'') || ' ' ||
               COALESCE(TO_VARCHAR(LAB_RESULT_NOTE),'') AS TXT,
               'LAB' AS SRC
        FROM ATTR_EVID_LAB_RESULT
        """,
    ]
    sql = f"CREATE OR REPLACE TEMPORARY TABLE {table} AS\n" + "\nUNION ALL\n".join(parts)
    _sql(session, sql)
    return table


def _atom_match_sql(atom: Dict[str, Any]) -> Tuple[str, str]:
    """Return (code_predicate on CODE_STREAM aliases, text_predicate on TEXT_STREAM)."""
    icd = _code_list(atom, "icd10") + _code_list(atom, "icd9")
    cpt = _code_list(atom, "cpt") + _code_list(atom, "hcpcs")
    snomed = _code_list(atom, "snomed")
    kws = _keyword_list(atom)

    code_bits = []
    if icd:
        code_bits.append(f"(CODE_SYSTEM = 'ICD' AND {_icd_pred('CODE_VALUE', icd)})")
    if cpt:
        code_bits.append(f"(CODE_SYSTEM = 'CPT_HCPCS' AND {_exact_pred('CODE_VALUE', cpt)})")
    if snomed:
        code_bits.append(f"(CODE_SYSTEM = 'SNOMED' AND {_snomed_pred('CODE_VALUE', snomed)})")
    code_pred = "(" + " OR ".join(code_bits) + ")" if code_bits else "FALSE"
    text_pred = _kw_pred("TXT", kws) if kws else "FALSE"
    return code_pred, text_pred


def _repeat_procedure_count_sql(
    atom_id: str, rule: Dict[str, Any], atoms: Dict[str, Dict[str, Any]]
) -> str:
    """Structured rule REPEAT_PROCEDURE_COUNT: fire an atom when a REFERENCED atom's own
    codes occur on >= min_distinct_dates distinct dates for the same patient - e.g. 2+
    separate carpal tunnel release procedures (ctr_any's codes) = recurrent CTS, without
    depending on a clinician ever writing the word "recurrent" in a note.

    FIRST_SEEN is the date of the Nth (e.g. 2nd) distinct occurrence - the date the
    repeat pattern actually became evident, not the date of the first procedure.
    """
    ref_id = rule.get("reference_atom_id")
    ref_atom = atoms.get(ref_id)
    if not ref_atom:
        raise KeyError(
            f"{atom_id}: structured_rule REPEAT_PROCEDURE_COUNT references atom "
            f"'{ref_id}', which is not in the extracted atom set."
        )
    min_dates = int(rule.get("min_distinct_dates", 2))
    ref_code_pred, _ref_text_pred = _atom_match_sql(ref_atom)
    return f"""
    SELECT PATIENT_ID, '{_esc(atom_id)}' AS ATOM_ID, EVENT_DATE AS FIRST_SEEN
    FROM (
        SELECT PATIENT_ID, EVENT_DATE,
               DENSE_RANK() OVER (PARTITION BY PATIENT_ID ORDER BY EVENT_DATE) AS DATE_RANK
        FROM (
            SELECT DISTINCT PATIENT_ID, EVENT_DATE
            FROM ATTR_V3_WT01_CODE_STREAM
            WHERE {ref_code_pred} AND EVENT_DATE IS NOT NULL
        )
    )
    WHERE DATE_RANK = {min_dates}
    """


def create_atom_hits(session, atoms: Dict[str, Dict[str, Any]]) -> str:
    """Long-form atom hits with first_seen date."""
    table = "ATTR_V3_WT01_ATOM_HITS"
    unions = []
    for aid, atom in atoms.items():
        code_pred, text_pred = _atom_match_sql(atom)
        unions.append(
            f"""
            SELECT PATIENT_ID, '{_esc(aid)}' AS ATOM_ID, MIN(EVENT_DATE) AS FIRST_SEEN
            FROM ATTR_V3_WT01_CODE_STREAM
            WHERE {code_pred} AND EVENT_DATE IS NOT NULL
            GROUP BY PATIENT_ID
            """
        )
        unions.append(
            f"""
            SELECT PATIENT_ID, '{_esc(aid)}' AS ATOM_ID, MIN(EVENT_DATE) AS FIRST_SEEN
            FROM ATTR_V3_WT01_TEXT_STREAM
            WHERE {text_pred} AND EVENT_DATE IS NOT NULL
            GROUP BY PATIENT_ID
            """
        )
        for rule in _structured_rules(atom):
            if rule.get("rule_type") == "REPEAT_PROCEDURE_COUNT":
                unions.append(_repeat_procedure_count_sql(aid, rule, atoms))
            else:
                print(f"NOTE: atom {aid} structured_rule type "
                      f"{rule.get('rule_type')!r} unsupported - skipped.")
    inner = "\nUNION ALL\n".join(unions)
    sql = f"""
    CREATE OR REPLACE TEMPORARY TABLE {table} AS
    SELECT PATIENT_ID, ATOM_ID, MIN(FIRST_SEEN) AS FIRST_SEEN
    FROM ({inner})
    GROUP BY PATIENT_ID, ATOM_ID
    """
    _sql(session, sql)
    return table


def create_atoms_wide(session, atom_ids: Sequence[str]) -> str:
    table = "ATTR_V3_ATOMS"
    flags = []
    dates = []
    for aid in atom_ids:
        col = aid.upper()
        flags.append(
            f"MAX(IFF(h.ATOM_ID = '{_esc(aid)}', 1, 0)) AS {col}"
        )
        dates.append(
            f"MIN(IFF(h.ATOM_ID = '{_esc(aid)}', h.FIRST_SEEN, NULL)) AS {col}_FIRST_SEEN"
        )
    sql = f"""
    CREATE OR REPLACE TEMPORARY TABLE {table} AS
    SELECT c.PATIENT_ID,
           {", ".join(flags)},
           {", ".join(dates)}
    FROM ATTR_WIDE_NET_CANDIDATES c
    LEFT JOIN ATTR_V3_WT01_ATOM_HITS h ON c.PATIENT_ID = h.PATIENT_ID
    GROUP BY c.PATIENT_ID
    """
    _sql(session, sql)
    return table

# -*- coding: utf-8 -*-
"""WT01 end-to-end SQL pipeline (ATTR v3) — orchestrator.

Signal WT01 = TEMPORAL_RULE RULE_ATTRWT_ORTHO_BEFORE_CARDIO (Excel T01).
Not an atom / not a bucket. Chronology upgrades the ORTHO+CARDIO combination.

Pipeline order (architecture checklist):
  SOURCE tables (SOURCE_CONFIG)
    -> ATTR_WIDE_NET_CANDIDATES + ATTR_EVID_*
    -> ATTR_V3_ATOMS            (atom triggers from atoms/*.json)
    -> ORTHO_CLUSTER (WT04)     (composite; feeds ORTHO tier)
    -> ATTR_V3_BUCKET_TIER      (ATTRwt / GENERAL_AMYLOID / ATTR_COMMON)
    -> ATTR_V3_TEMPORAL_HITS    (T01 / WT01 ORTHO_BEFORE_CARDIO)
    -> ATTR_V3_COMBINATION_HITS (GA01 -> AC01 -> WT_RULE_01/02)
    -> ATTR_V3_GUARDRAIL_HITS   (WT24/WT25/WT26; WT27/WT28/WT29/V37/V39 when AL/ATTRv/AA on)
    -> ATTR_V3_ROUTER_OUTPUT

Requires specialty_configs_v3/ only. Does NOT depend on RDDT_ATTR_Snowflake.ipynb.

This module is a thin orchestrator: each pipeline stage lives in its own
file (atoms / composites / buckets / temporal / combinations / guardrails /
router), all built on shared loaders in common.py. Every name previously
defined directly in this file (config loaders, SQL builders, run_* /
preview_* functions) is still importable as `pipeline.<name>` - callers just
need `import pipeline as wt01` (this module was renamed from wt01_pipeline.py
to pipeline.py; every `wt01.X(...)` call still works unchanged once the
import line itself is updated).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# Re-exported for backward compatibility (wt01.find_v3_config_root, wt01._sql, ...)
from common import (
    AA_BUCKETS as AA_BUCKETS,
    AL_BUCKETS as AL_BUCKETS,
    ATTRV_BUCKETS as ATTRV_BUCKETS,
    HERE as HERE,
    PHENOTYPE_OVERLAY_FILES as PHENOTYPE_OVERLAY_FILES,
    WT01_GATE_BUCKETS as WT01_GATE_BUCKETS,
    _count,
    _esc,
    _load_json,
    _sql,
    find_v3_config_root,
    keyword_wildcard_variations,
    load_atoms_by_id,
    load_attrwt_overlays,
    load_combination_file,
    load_guardrails,
    load_neuro_plus_systemic_composite,
    load_ortho_cluster,
    load_overlay_file,
    load_renal_disproportionate_composite,
    load_temporal_rule,
)

# Re-exported stage modules (wt01.create_atom_hits, wt01.wt01_atom_ids, ...)
from atoms import (
    CLAIM_DIAG_COLS,
    CLAIM_PROC_COLS,
    _atom_match_sql,
    _code_list,
    _exact_pred,
    _icd_pred,
    _keyword_list,
    _kw_pred,
    _snomed_pred,
    create_atom_hits,
    create_atoms_wide,
    create_evidence_code_unpivot,
    create_evidence_text_stream,
    aa_atom_ids,
    al_atom_ids,
    attrv_atom_ids,
    wt01_atom_ids,
)
from composites import create_ortho_cluster, create_neuro_plus_systemic, create_renal_disproportionate
from buckets import build_bucket_tier_map, create_bucket_tiers
from temporal import create_temporal_t01
from combinations import (
    _bucket_alias,
    _count_distinct_buckets_sql,
    _org_plus_etiology_sql,
    _pair_rule_sql,
    _priority_case_sql,
    _tier_cond,
    create_combinations,
)
from guardrails import create_guardrails
from router import (
    create_router_output,
    preview_bucket_tiers,
    preview_combinations,
    preview_composites,
    preview_router,
    preview_router_aa,
    preview_router_al,
    preview_router_attrv,
    preview_t01,
)


# ---------------------------------------------------------------------------
# Orchestrator — stage 4+ (atoms -> ... -> router), prerequisites: Stage 1-3
# ---------------------------------------------------------------------------

def run_attrwt_pipeline(
    session,
    config_root: Optional[Path] = None,
    source_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the full ATTRwt vertical slice (named by phenotype, not by WT01 - WT01
    was just the first signal built/verified end-to-end as a starting point; this
    function computes ALL of ATTRwt, not only the WT01 temporal check).
    Prerequisites: ATTR_WIDE_NET_CANDIDATES + ATTR_EVID_*.

    Fully config-driven: GENERAL_AMYLOID/ATTR_COMMON/ATTRwt each read their OWN
    phenotype_overlays/*.json (no tier-map reuse), combinations read directly from
    combinations/*.json (no hardcoded/approximated rule shape), guardrails read
    from guardrails/differential_routes.json.
    """
    root = config_root or find_v3_config_root()
    cfg = source_config or default_source_config()
    cluster = load_ortho_cluster(root)
    atom_ids = wt01_atom_ids(root, cluster)
    atoms = load_atoms_by_id(root, atom_ids)

    create_evidence_code_unpivot(session)
    create_evidence_text_stream(session)
    create_atom_hits(session, atoms)
    create_atoms_wide(session, atom_ids)
    create_ortho_cluster(session, cluster)
    wt01_phenotype_files = {
        "GENERAL_AMYLOID": PHENOTYPE_OVERLAY_FILES["GENERAL_AMYLOID"],
        "ATTR_COMMON": PHENOTYPE_OVERLAY_FILES["ATTR_COMMON"],
        "ATTRwt": PHENOTYPE_OVERLAY_FILES["ATTRwt"],
    }
    create_bucket_tiers(
        session, root, available_atom_ids=atom_ids, phenotype_files=wt01_phenotype_files
    )
    create_temporal_t01(session, root)
    create_combinations(session, root)
    create_guardrails(session, root, cfg)
    create_router_output(session)

    summary = {
        "config_root": str(root),
        "atom_count": len(atom_ids),
        "atom_hits": _count(session, "ATTR_V3_WT01_ATOM_HITS"),
        "atoms_wide": _count(session, "ATTR_V3_ATOMS"),
        "composites_fired": int(
            session.sql(
                "SELECT COUNT(*) AS N FROM ATTR_V3_COMPOSITE_HITS WHERE FIRED"
            ).collect()[0][0]
        ),
        "bucket_tiers": _count(session, "ATTR_V3_BUCKET_TIER"),
        "temporal_t01": _count(session, "ATTR_V3_TEMPORAL_HITS"),
        "combinations": _count(session, "ATTR_V3_COMBINATION_HITS"),
        "guardrails": _count(session, "ATTR_V3_GUARDRAIL_HITS"),
        "router_rows": _count(session, "ATTR_V3_ROUTER_OUTPUT"),
    }
    return summary


def run_full_pipeline(
    session,
    config_root: Optional[Path] = None,
    source_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Same as run_attrwt_pipeline, plus ATTRv (V_RULE_01-07 + NEURO_PLUS_SYSTEMIC
    composite + AC02-08 turned on so V_RULE's ATTR_COMMON funnel actually admits
    ATTRv-shaped patients), AL (AL_RULE_01-07 + AL22/23/30/31 guardrails; GA02
    - already on whenever phase3_wt01_only=False - now also gets real HEME_CLONAL
    etiology evidence for the first time), and AA (AA_RULE_01/02 + RENAL_
    DISPROPORTIONATE composite + AA25-30/WT29/V40 guardrails; GA02 now also gets
    real INFLAMMATORY_DRIVER etiology evidence for the first time). Kept as a
    SEPARATE function rather than a flag on run_attrwt_pipeline so the plain
    ATTRwt path's output can never silently change just because ATTRv/AL/AA code
    exists - see combinations.create_combinations's build_attrv/build_al/build_aa
    guards and router.create_router_output's include_attrv/include_al/include_aa
    guards, both of which this function is the only caller of with the widened
    behavior on.

    Named generically (run_full_pipeline, not per-phenotype) since it will keep
    growing to cover every phenotype as they get built - naming it after every
    phenotype it covers would need renaming again each time, exactly the
    naming-drift problem this whole rename exercise fixed for the module files,
    and it's the same reasoning that renamed this function to begin with (it
    used to be named after ATTRv, the phenotype ADDED when this function was
    created, rather than after everything it now runs).

    Composite call order matters here and differs from run_attrwt_pipeline: WT04
    (Shape A) and RENAL_DISPROPORTIONATE (Shape C) both read ATTR_V3_ATOMS
    directly and must run BEFORE bucket tiers (RENAL_DISPROPORTIONATE's result
    then FEEDS INTO the RENAL/AA bucket-tier row, same mechanism WT04 uses for
    ORTHO/ATTRwt); NEURO_PLUS_SYSTEMIC (Shape B) reads ATTR_V3_BUCKET_TIER
    (cross-bucket count) and must run AFTER. AL21/AL26/AL27 (AL's own
    composites) are NOT built here at all - AL21 is redundant with AL_RULE_07
    (same COUNT_DISTINCT_BUCKETS computation), AL26 is redundant with the union
    of AL_RULE_01-05 (same PAIR computations, same output_route), and AL27 is
    marked non-executable in its own config (needs a data field - a confirmed
    predates-suspicion timestamp - this pipeline doesn't have).
    """
    root = config_root or find_v3_config_root()
    cfg = source_config or default_source_config()
    cluster = load_ortho_cluster(root)
    atom_ids = sorted(
        set(wt01_atom_ids(root, cluster))
        | set(attrv_atom_ids(root))
        | set(al_atom_ids(root))
        | set(aa_atom_ids(root))
    )
    atoms = load_atoms_by_id(root, atom_ids)

    create_evidence_code_unpivot(session)
    create_evidence_text_stream(session)
    create_atom_hits(session, atoms)
    create_atoms_wide(session, atom_ids)
    create_ortho_cluster(session, cluster)

    renal_disproportionate = load_renal_disproportionate_composite(root)
    driver_bucket = renal_disproportionate["context_required"]["bucket"]
    driver_max_tier = int(renal_disproportionate["context_required"].get("max_tier", 2))
    aa_overlay = load_overlay_file(root, PHENOTYPE_OVERLAY_FILES["AA"])
    aa_driver_tiers = build_bucket_tier_map(aa_overlay).get(driver_bucket, {})
    driver_atom_ids = sorted(
        aid for aid, (tier, _gate) in aa_driver_tiers.items() if tier <= driver_max_tier
    )
    create_renal_disproportionate(session, renal_disproportionate, driver_atom_ids)

    combined_phenotype_files = {
        "GENERAL_AMYLOID": PHENOTYPE_OVERLAY_FILES["GENERAL_AMYLOID"],
        "ATTR_COMMON": PHENOTYPE_OVERLAY_FILES["ATTR_COMMON"],
        "ATTRwt": PHENOTYPE_OVERLAY_FILES["ATTRwt"],
        "ATTRv": PHENOTYPE_OVERLAY_FILES["ATTRv"],
        "AL": PHENOTYPE_OVERLAY_FILES["AL"],
        "AA": PHENOTYPE_OVERLAY_FILES["AA"],
    }
    combined_buckets = sorted(
        set(WT01_GATE_BUCKETS) | set(ATTRV_BUCKETS) | set(AL_BUCKETS) | set(AA_BUCKETS)
    )
    create_bucket_tiers(
        session,
        root,
        buckets_only=combined_buckets,
        available_atom_ids=atom_ids,
        phenotype_files=combined_phenotype_files,
    )

    v03 = load_neuro_plus_systemic_composite(root)
    create_neuro_plus_systemic(session, v03)

    create_temporal_t01(session, root)
    create_combinations(session, root, phase3_wt01_only=False, build_al=True, build_aa=True)
    create_guardrails(session, root, cfg, include_attrv=True, include_al=True, include_aa=True)
    create_router_output(session, include_attrv=True, include_al=True, include_aa=True)

    summary = {
        "config_root": str(root),
        "atom_count": len(atom_ids),
        "atom_hits": _count(session, "ATTR_V3_WT01_ATOM_HITS"),
        "atoms_wide": _count(session, "ATTR_V3_ATOMS"),
        "composites_fired": int(
            session.sql(
                "SELECT COUNT(*) AS N FROM ATTR_V3_COMPOSITE_HITS WHERE FIRED"
            ).collect()[0][0]
        ),
        "bucket_tiers": _count(session, "ATTR_V3_BUCKET_TIER"),
        "temporal_t01": _count(session, "ATTR_V3_TEMPORAL_HITS"),
        "combinations": _count(session, "ATTR_V3_COMBINATION_HITS"),
        "guardrails": _count(session, "ATTR_V3_GUARDRAIL_HITS"),
        "router_rows": _count(session, "ATTR_V3_ROUTER_OUTPUT"),
    }
    return summary


# ---------------------------------------------------------------------------
# Stages 1-3 — self-contained (no prior notebook required)
# Uses rddt_attr_sql.py living beside this module in specialty_configs_v3/
# ---------------------------------------------------------------------------

def default_source_config() -> Dict[str, Any]:
    """Physical table/column map (matches Early Detection / client data dictionary)."""
    return {
        "namespace": None,
        "tables": {
            "census": {
                "name": "CENSUS",
                "enabled": True,
                "required": True,
                "columns": {
                    "patient_id": "Member/PatientId",
                    "birth_date": "BirthDate",
                    "gender": "Gender",
                    "city": "City",
                    "state": "State",
                    "family_id": "FamilyId",
                },
                "required_columns": (
                    "patient_id", "birth_date", "gender", "city", "state", "family_id",
                ),
            },
            "encounter": {
                "name": "ENCOUNTER_VISIT",
                "enabled": True,
                "required": True,
                "columns": {
                    "encounter_id": "EncounterId/VisitId",
                    "patient_id": "Member/PatientId",
                    "encounter_date": "Encounter/Visit Date",
                },
                "required_columns": ("encounter_id", "patient_id", "encounter_date"),
            },
            "claim": {
                "name": "CLAIM",
                "enabled": True,
                "required": True,
                "columns": {
                    "patient_id": "Member/PatientId",
                    "encounter_id": "EncounterId/VisitId",
                    "diagnosis_code": "DiagnosisCode",
                    "other_diagnosis_9": "OtherDiagnosisCodes9",
                    "other_diagnosis_10": "OtherDiagnosisCodes10",
                    "procedure_code": "ProcedureCode",
                    "procedure_modifier_1": "ProcedureModifier1",
                    "procedure_modifier_2": "ProcedureModifier2",
                    "procedure_modifier_3": "ProcedureModifier3",
                    "diagnosis_type": "DiagnosisType",
                    "provider_type": "ProviderType",
                    "specialty_code": "SpecialtyCode",
                    "specialty_name": "SpecialtyName",
                    "drg_code": "DRGCode",
                    "clinical_notes": "ClinicalNotes",
                    "from_date": "FromDate",
                    "to_date": "ToDate",
                },
                "diagnosis_columns": ("diagnosis_code", "other_diagnosis_9", "other_diagnosis_10"),
                "procedure_columns": ("procedure_code",),
                "required_columns": (
                    "patient_id", "encounter_id",
                    "diagnosis_code", "other_diagnosis_9", "other_diagnosis_10",
                    "procedure_code", "procedure_modifier_1", "procedure_modifier_2", "procedure_modifier_3",
                    "diagnosis_type", "provider_type", "specialty_code", "specialty_name",
                    "drg_code", "clinical_notes", "from_date", "to_date",
                ),
            },
            "lab": {
                "name": "LAB",
                "enabled": True,
                "required": True,
                "columns": {
                    "patient_id": "Member/PatientId",
                    "encounter_id": "EncounterId/VisitId",
                    "lab_id": "LabId",
                    "lab_request_id": "LabRequestId",
                    "lab_result_id": "LabResultId",
                    "observation_identifier": "ObservationIdentifier",
                    "observation_value": "ObservationValue",
                    "result_status": "ObservationResultStatus",
                    "observation_datetime": "ObservationDateTime",
                    "lab_result_note": "LabResultNote",
                },
                "required_columns": (
                    "lab_id", "encounter_id", "patient_id",
                    "lab_request_id", "lab_result_id",
                    "observation_identifier", "observation_value", "result_status",
                    "observation_datetime", "lab_result_note",
                ),
            },
            "medical_history": {
                "name": "MEDICAL_HISTORY",
                "enabled": True,
                "required": True,
                "columns": {
                    "patient_id": "Member/PatientId",
                    "encounter_id": "EncounterId/VisitId",
                    "record_id": "MedicalHistoryId",
                    "source_category": "Source/Category",
                    "value": "Value",
                    "snomed": "SNOMED",
                    "secondary_snomed": "Secondary SNOMED",
                    "event_date": "Date",
                },
                "required_columns": (
                    "record_id", "encounter_id", "patient_id",
                    "source_category", "value", "snomed", "secondary_snomed", "event_date",
                ),
            },
            "surgical_history": {
                "name": "SURGICAL_HISTORY",
                "enabled": True,
                "required": True,
                "columns": {
                    "patient_id": "Member/PatientId",
                    "encounter_id": "EncounterId/VisitId",
                    "record_id": "SurgicalHistoryId",
                    "source_category": "Source/Category",
                    "value": "Value",
                    "snomed": "SNOMED",
                    "secondary_snomed": "Secondary SNOMED",
                    "event_date": "Date",
                },
                "required_columns": (
                    "record_id", "encounter_id", "patient_id",
                    "source_category", "value", "snomed", "secondary_snomed", "event_date",
                ),
            },
            "family_history": {
                "name": "FAMILY_HISTORY",
                "enabled": True,
                "required": True,
                "columns": {
                    "patient_id": "Member/PatientId",
                    "encounter_id": "EncounterId/VisitId",
                    "record_id": "FamilyHistoryId",
                    "condition": "Condition",
                    "status": "Status",
                    "family_member": "FamilyMember",
                    "snomed": "SNOMED",
                    "event_date": "Date",
                },
                "required_columns": (
                    "record_id", "encounter_id", "patient_id",
                    "snomed", "condition", "status", "family_member", "event_date",
                ),
            },
            "clinical_note": {
                "name": "CLINICAL_NOTE",
                "enabled": True,
                "required": True,
                "columns": {
                    "patient_id": "Member/PatientId",
                    "encounter_id": "EncounterId/VisitId",
                    "note_id": "NoteId",
                    "note_type": "NoteType",
                    "note_text": "Clinical Note Text",
                    "event_date": "Date",
                },
                "required_columns": (
                    "note_id", "encounter_id", "patient_id",
                    "note_type", "note_text", "event_date",
                ),
            },
            "social_history": {
                "name": "SOCIAL_HISTORY",
                "enabled": False,
                "required": False,
                "columns": {
                    "patient_id": "Member/PatientId",
                    "encounter_id": "EncounterId/VisitId",
                    "value": "Value",
                    "event_date": "Date",
                },
                "required_columns": (),
            },
            "medication": {
                "name": "MEDICATION",
                "enabled": False,
                "required": False,
                "columns": {
                    "patient_id": "Member/PatientId",
                    "encounter_id": "EncounterId/VisitId",
                    "medication_name": "Medication Name",
                    "status": "Medication Status",
                    "event_date": "Date",
                },
                "required_columns": (),
            },
        },
    }


# Free-text columns for keyword ILIKE (never run text strategies on code columns).
TEXT_COLUMNS = {
    "lab": ("observation_identifier", "observation_value", "lab_result_note"),
    "medical_history": ("value", "source_category"),
    "surgical_history": ("value", "source_category"),
    "family_history": ("condition",),
    "clinical_note": ("note_text",),
    "claim": ("clinical_notes",),
    "social_history": ("value",),
}

ICD_CODE_COLUMNS = {
    "claim": ("diagnosis_code", "other_diagnosis_9", "other_diagnosis_10"),
}
PROCEDURE_CODE_COLUMNS = {
    "claim": ("procedure_code",),
}
SNOMED_CODE_COLUMNS = {
    "medical_history": ("snomed", "secondary_snomed"),
    "surgical_history": ("snomed", "secondary_snomed"),
    "family_history": ("snomed",),
}


def _import_rsql():
    """Load rddt_attr_sql from the same specialty_configs_v3 folder."""
    import importlib
    import sys

    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import rddt_attr_sql as rsql

    return importlib.reload(rsql)


def _keyword_entries(atom: Dict[str, Any]) -> List[Dict[str, str]]:
    """Return keyword dicts with value/mode from atom extraction."""
    ext = atom.get("extraction") or {}
    raw = ext.get("keywords") or ext.get("candidate_keywords") or []
    out: List[Dict[str, str]] = []
    for item in raw:
        if isinstance(item, str):
            val = item.strip()
            if val:
                out.append({"value": val, "mode": "PHRASE"})
        elif isinstance(item, dict):
            val = str(item.get("value") or item.get("term") or "").strip()
            if val:
                out.append(
                    {
                        "value": val,
                        "mode": str(item.get("mode") or "PHRASE"),
                        "polarity_required": str(item.get("polarity_required") or ""),
                    }
                )
    return out


def build_wt01_vocab_frames(config_root: Optional[Path] = None) -> Dict[str, Any]:
    """Load WT01-relevant atoms and return display DataFrames + net lists.

    Returns dict with:
      codes_df, keywords_df, patterns_df, icd, cpt, snomed, keyword_patterns, atom_ids
    """
    import pandas as pd

    root = config_root or find_v3_config_root()
    cluster = load_ortho_cluster(root)
    atom_ids = wt01_atom_ids(root, cluster)
    atoms = load_atoms_by_id(root, atom_ids)

    # atom -> bucket/tier from ATTRwt overlay (display helper; GA/AC may differ)
    overlays = load_attrwt_overlays(root)
    meta: Dict[str, Dict[str, Any]] = {}
    for o in overlays:
        aid = o.get("atom_id")
        if aid:
            meta[aid] = {
                "bucket": o.get("bucket"),
                "tier": o.get("tier"),
                "gate_eligible": o.get("gate_eligible"),
                "source_sign_id": o.get("source_sign_id"),
            }

    code_rows = []
    kw_rows = []
    pattern_rows = []
    icd: List[str] = []
    cpt: List[str] = []
    snomed: List[str] = []
    keyword_patterns: List[str] = []
    seen_icd: Set[str] = set()
    seen_cpt: Set[str] = set()
    seen_sn: Set[str] = set()
    seen_pat: Set[str] = set()

    for aid, atom in atoms.items():
        m = meta.get(aid, {})
        for fam in ("icd10", "icd9", "cpt", "hcpcs", "snomed"):
            for c in (((atom.get("extraction") or {}).get("codes") or {}).get(fam)) or []:
                code = str(c.get("code") or "").strip()
                if not code:
                    continue
                code_rows.append(
                    {
                        "atom_id": aid,
                        "preferred_name": atom.get("preferred_name"),
                        "bucket": m.get("bucket"),
                        "tier": m.get("tier"),
                        "source_sign_id": m.get("source_sign_id"),
                        "code_family": fam.upper(),
                        "code": code,
                        "mapping_role": c.get("mapping_role"),
                        "can_fire_atom_alone": c.get("can_fire_atom_alone"),
                        "description": c.get("description"),
                    }
                )
                if fam in ("icd10", "icd9"):
                    u = code.upper()
                    if u not in seen_icd:
                        seen_icd.add(u)
                        icd.append(code)
                elif fam in ("cpt", "hcpcs"):
                    u = code.upper()
                    if u not in seen_cpt:
                        seen_cpt.add(u)
                        cpt.append(code)
                elif fam == "snomed":
                    d = "".join(ch for ch in code if ch.isdigit())
                    if d and d not in seen_sn:
                        seen_sn.add(d)
                        snomed.append(d)

        for kw in _keyword_entries(atom):
            kw_rows.append(
                {
                    "atom_id": aid,
                    "preferred_name": atom.get("preferred_name"),
                    "bucket": m.get("bucket"),
                    "tier": m.get("tier"),
                    "gate_eligible": m.get("gate_eligible"),
                    "source_sign_id": m.get("source_sign_id"),
                    "mode": kw.get("mode"),
                    "polarity_required": kw.get("polarity_required"),
                    "value": kw["value"],
                }
            )
            for pat in keyword_wildcard_variations(kw["value"], kw.get("mode") or "PHRASE"):
                pattern_rows.append(
                    {
                        "atom_id": aid,
                        "keyword_value": kw["value"],
                        "mode": kw.get("mode"),
                        "ilike_pattern": pat,
                    }
                )
                key = pat.lower()
                if key not in seen_pat:
                    seen_pat.add(key)
                    keyword_patterns.append(pat)

    return {
        "atom_ids": atom_ids,
        "codes_df": pd.DataFrame(code_rows),
        "keywords_df": pd.DataFrame(kw_rows),
        "patterns_df": pd.DataFrame(pattern_rows),
        "icd": icd,
        "cpt": cpt,
        "snomed": snomed,
        "keyword_patterns": keyword_patterns,
    }


def per_keyword_counts(
    session,
    source_config: Dict[str, Any],
    patterns: Sequence[str],
    logical_table: str,
    logical_columns: Sequence[str],
    verbose: bool = False,
):
    """Unique patients per ILIKE pattern on one source table (inspect occurrence)."""
    import pandas as pd

    rsql = _import_rsql()
    rows = []
    for pat in patterns:
        ids = rsql.text_net_patient_ids(
            session,
            source_config,
            logical_table,
            logical_columns,
            [pat],
            verbose=False,
        )
        n = len(ids)
        rows.append({"ilike_pattern": pat, "unique_patients": n})
        if verbose:
            print(f"{n:6,}  {pat}")
    return pd.DataFrame(rows).sort_values("unique_patients", ascending=False)


def per_keyword_counts_multi_source(
    session,
    source_config: Dict[str, Any],
    patterns: Sequence[str],
    sources: Optional[Sequence[Tuple[str, Sequence[str]]]] = None,
    max_patterns: int = 80,
):
    """Sum unique patients across configured text sources for each pattern.

    Note: counts are per-source then unioned approximately via max; for exact
    cross-source unique patients use the wide-net builder. This is for inspection.
    """
    import pandas as pd

    if sources is None:
        sources = [
            ("claim", ("clinical_notes",)),
            ("clinical_note", ("note_text",)),
            ("surgical_history", ("value",)),
            ("medical_history", ("value",)),
            ("lab", ("observation_identifier", "lab_result_note")),
        ]
    rsql = _import_rsql()
    use = list(patterns)[:max_patterns]
    rows = []
    for pat in use:
        all_ids: Set[str] = set()
        per_src = {}
        for logical, cols in sources:
            try:
                ids = rsql.text_net_patient_ids(
                    session, source_config, logical, cols, [pat], verbose=False
                )
            except Exception:
                ids = []
            per_src[logical] = len(ids)
            all_ids.update(ids)
        row = {"ilike_pattern": pat, "unique_patients_any_source": len(all_ids)}
        row.update({f"n_{k}": v for k, v in per_src.items()})
        rows.append(row)
        print(f"{len(all_ids):6,}  {pat}")
    return pd.DataFrame(rows).sort_values(
        "unique_patients_any_source", ascending=False
    )


def collect_wt01_net_vocab(config_root: Optional[Path] = None) -> Dict[str, List[str]]:
    """ICD / CPT / SNOMED / keyword ILIKE patterns for the WT01-relevant atom set."""
    frames = build_wt01_vocab_frames(config_root)
    return {
        "icd": frames["icd"],
        "cpt": frames["cpt"],
        "snomed": frames["snomed"],
        "keywords": frames["keyword_patterns"],
        "atom_ids": frames["atom_ids"],
    }


def run_stages_1_to_3(
    session,
    source_config: Optional[Dict[str, Any]] = None,
    config_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """QC -> WT01 vocab wide net -> ATTR_WIDE_NET_CANDIDATES -> ATTR_EVID_*.

    Fully self-contained; does not require RDDT_ATTR_Snowflake.ipynb.
    """
    rsql = _import_rsql()
    cfg = source_config or default_source_config()
    root = config_root or find_v3_config_root()
    vocab = collect_wt01_net_vocab(root)

    validation = rsql.validate_sources(session, cfg, raise_on_error=True)
    n_patients = rsql.patient_count(session, cfg)
    print(f"census patients: {n_patients:,}")

    ids: Set[str] = set()

    # Claim ICD/CPT net from v3 atom vocabulary
    # Trailing-dot ICD families (e.g. I50.) become LIKE prefixes I50.%
    exact_icd = []
    like_icd = []
    for code in vocab["icd"]:
        c = str(code).strip()
        if c.endswith("."):
            like_icd.append(c + "%")
            like_icd.append(c.replace(".", "") + "%")
        else:
            exact_icd.append(c)

    claim_ids = rsql.code_net_patient_ids(
        session,
        cfg,
        exact_icd=exact_icd,
        exact_cpt=vocab["cpt"],
        like_prefixes=like_icd,
    )
    ids.update(claim_ids)
    print(f"claim code net: {len(claim_ids):,}")

    # Text nets (TEXT_COLUMNS — never on code columns)
    for logical, cols in TEXT_COLUMNS.items():
        src = cfg["tables"].get(logical) or {}
        if not src.get("enabled", True):
            continue
        try:
            got = rsql.text_net_patient_ids(
                session, cfg, logical, cols, vocab["keywords"], verbose=True
            )
            ids.update(got)
        except Exception as exc:
            print(f"text net {logical}: skipped ({exc})")

    # SNOMED nets on history tables
    for logical, cols in SNOMED_CODE_COLUMNS.items():
        src = cfg["tables"].get(logical) or {}
        if not src.get("enabled", True):
            continue
        try:
            got = rsql.snomed_net_patient_ids(
                session, cfg, logical, vocab["snomed"], verbose=True
            )
            ids.update(got)
        except Exception as exc:
            print(f"snomed net {logical}: skipped ({exc})")

    print(f"wide-net unique patients: {len(ids):,}")
    rsql.create_candidates(session, ids)
    inventory = rsql.build_evidence(session, cfg)

    return {
        "census_patients": n_patients,
        "wide_net_patients": len(ids),
        "vocab_icd": len(vocab["icd"]),
        "vocab_cpt": len(vocab["cpt"]),
        "vocab_snomed": len(vocab["snomed"]),
        "vocab_keywords": len(vocab["keywords"]),
        "validation_ok": True,
        "evidence_inventory": inventory,
    }


def run_full_attrwt_pipeline(
    session,
    source_config: Optional[Dict[str, Any]] = None,
    config_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """End-to-end ATTRwt: wide net + evidence + atoms -> WT04 -> tiers -> T01 -> WT_RULE -> router."""
    root = config_root or find_v3_config_root()
    cfg = source_config or default_source_config()
    stage13 = run_stages_1_to_3(session, cfg, root)
    stage4 = run_attrwt_pipeline(session, root, cfg)
    return {"stages_1_3": stage13, "stages_4_plus": stage4}

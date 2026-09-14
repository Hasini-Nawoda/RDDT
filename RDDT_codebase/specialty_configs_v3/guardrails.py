# -*- coding: utf-8 -*-
"""Guardrails: guardrails/differential_routes.json -> ATTR_V3_GUARDRAIL_HITS.

WT01 scope: WT25/WT26 (atom-triggered) + WT24 (demographic). ATTRwt
INFERRED_TARGET_PHENOTYPE_PATTERN guardrails:
  WT27 (reuses AL_RULE_01/06)  when include_al=True
  WT28 (reuses V_RULE_01)      when include_attrv=True
  WT29 (reuses AA_RULE_01/02)  when include_aa=True
ATTRv: V37 (diabetes atom) when include_attrv=True; V39 (reuses
AL_RULE_01/06, twin of WT27) when include_al=True.
WT30 stays in do_not_use (never a screening trigger).

include_attrv=True (used by run_full_pipeline only) additionally
builds V37 (diabetes -> ANTI_ANCHORING_NOT_EXCLUSION), V38
(ALTERNATIVE_NEUROPATHY), V32 (LFLG-AS -> ATTRwt route), and V33
(isolated orthopedic prodrome -> ATTRwt route) - same atom-triggered shape as
WT25/26. V37/V38 are gated behind this flag out of necessity (their trigger
atoms - diabetes; autoimmune_disease/autoantibody_result - are only guaranteed
extracted when the ATTRv atom set is built - building them unconditionally
would reference ATTR_V3_ATOMS columns that don't exist in the plain WT01-only
pipeline and break it). V32 and V33 don't strictly need the gate - their
trigger atoms (as_valve/lflg_as; trigger_finger/trigger_release/rotator_cuff/
rotator_cuff_repair/shoulder_disorder/biceps_rupture) are already part of the
plain WT01 atom set too - but they're filed under ATTRv's signal catalog, so
kept behind the same flag for consistency rather than silently changing the
plain WT01-only pipeline's guardrail output.

Also builds V41 (isolated-cardiac-ATTRwt-phenotype -> still recommend genetic
testing) when include_attrv=True - a THIRD shape, different from the two above:
it fires off an already-computed RULE result (WT_RULE_01/WT_RULE_02 in
ATTR_V3_COMBINATION_HITS), not raw ATTR_V3_ATOMS flags. WT_RULE_01/02 are core
ATTRwt rules built in every pipeline run, so V41 doesn't strictly need the gate
either - kept behind it for the same consistency reason as V32. V40 (reuses
AA_RULE_01/02, same shape as V41) is built whenever include_aa=True. V39
(reuses AL_RULE_01/06 -> AL route; ATTRv twin of WT27) is built whenever
include_al=True.

include_al=True additionally builds AL22/AL23 (atom-triggered, reusing ORTHO
atoms already extracted by wt01_atom_ids - same non-strict-gate reasoning as
V32/V33), AL30/AL31 (rule-triggered: AL30 reuses WT_RULE_01/02, always
built; AL31 reuses V_RULE_01, so include_al only makes sense alongside
include_attrv=True in the same pipeline run - AL is not independent of ATTRv
here), WT27, and V39 (both reuse AL_RULE_01/06). AL25 (reuses AA_RULE_02) is
built only when include_al AND include_aa are both True - same "not independent
of the other phenotype" reasoning as AL31.

include_aa=True additionally builds AA26/AA27/AA28 (atom-triggered),
AA29 (rule-triggered, reuses AC01), AA30 (a fourth shape - ABSENCE-triggered:
fires when RENAL is gate-eligible but INFLAMMATORY_DRIVER is NOT, the mirror
image of a presence check), WT29/V40 (rule-triggered, reuse AA_RULE_01/02),
and AL25 (rule-triggered across TWO phenotypes at once - AL_RULE_02 is
phenotype=AL, AC01 is phenotype=ATTR_COMMON - see
_rule_triggered_guardrail_sql_multi, only used for this one guardrail so the
already-shipped single-phenotype _rule_triggered_guardrail_sql stays untouched).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from common import _esc, _sql, load_guardrails


def _atom_triggered_guardrail_sql(sign_id: str, g: Dict[str, Any]) -> str:
    """WT25/WT26/V38 shape: fires from ATTR_V3_ATOMS flags alone (VERIFIED_ATOM_TAG)."""
    trigger_atoms = g.get("trigger_atom_ids") or []
    cond = " OR ".join(f"COALESCE({a.upper()}, 0) = 1" for a in trigger_atoms)
    dates = ", ".join(f"IFF(COALESCE({a.upper()},0)=1,{a.upper()}_FIRST_SEEN,NULL)" for a in trigger_atoms)
    return f"""
    SELECT PATIENT_ID,
           '{sign_id}' AS SIGN_ID,
           '{_esc(g['source_phenotype'])}' AS SOURCE_PHENOTYPE,
           '{_esc(g['canonical_atom_or_rule_id'])}' AS CANONICAL_ATOM_OR_RULE_ID,
           '{_esc(g['reasoning_bucket'])}' AS REASONING_BUCKET,
           '{_esc(g['route_or_guardrail'])}' AS ROUTE_OR_GUARDRAIL,
           '{",".join(trigger_atoms)}' AS TRIGGERING_ATOM,
           LEAST({dates}) AS FIRST_SEEN_DATE
    FROM ATTR_V3_ATOMS
    WHERE {cond}
    """


def _rule_triggered_guardrail_sql(sign_id: str, g: Dict[str, Any], target_phenotype: str) -> str:
    """V41 shape: fires when the patient already passed one of `reuses_rule`'s
    rule IDs in ATTR_V3_COMBINATION_HITS (a phenotype/rule already computed
    elsewhere in the pipeline), rather than checking raw atom flags directly.
    No natural per-atom date to report here (ATTR_V3_COMBINATION_HITS doesn't
    carry one), so FIRST_SEEN_DATE is NULL - same as WT24's non-atom-based
    guardrail."""
    rule_ids = g.get("reuses_rule") or []
    rule_list = ", ".join(f"'{_esc(r)}'" for r in rule_ids)
    return f"""
    SELECT DISTINCT PATIENT_ID,
           '{sign_id}' AS SIGN_ID,
           '{_esc(g['source_phenotype'])}' AS SOURCE_PHENOTYPE,
           '{_esc(g['canonical_atom_or_rule_id'])}' AS CANONICAL_ATOM_OR_RULE_ID,
           '{_esc(g['reasoning_bucket'])}' AS REASONING_BUCKET,
           '{_esc(g['route_or_guardrail'])}' AS ROUTE_OR_GUARDRAIL,
           '{",".join(rule_ids)}' AS TRIGGERING_ATOM,
           NULL AS FIRST_SEEN_DATE
    FROM ATTR_V3_COMBINATION_HITS
    WHERE PHENOTYPE = '{_esc(target_phenotype)}' AND RULE_ID IN ({rule_list})
    """


def _rule_triggered_guardrail_sql_multi(
    sign_id: str, g: Dict[str, Any], target_phenotypes: Any
) -> str:
    """AA25 shape: same as _rule_triggered_guardrail_sql, but `reuses_rule` spans
    MORE THAN ONE phenotype at once (AL25 reuses AL_RULE_02 [phenotype=AL] AND
    AC01 [phenotype=ATTR_COMMON] together - the source note says "two possible
    targets (AL or ATTR) - both reuse-rules are listed; route resolution between
    them is not specified"). RULE_ID strings are unique across every phenotype in
    this codebase (GA01/AC01/WT_RULE_.../V_RULE_.../AL_RULE_.../AA_RULE_... never
    collide), so PHENOTYPE IN (...) here is a safety filter, not what actually
    disambiguates the match. Kept as a separate function (rather than generalizing
    _rule_triggered_guardrail_sql itself to take a list) so every already-shipped
    single-phenotype guardrail (V41/AL30/AL31/WT29/V40/AA29/AL25-as-AA) keeps its
    exact 'PHENOTYPE = <x>' SQL text unchanged."""
    rule_ids = g.get("reuses_rule") or []
    rule_list = ", ".join(f"'{_esc(r)}'" for r in rule_ids)
    phen_list = ", ".join(f"'{_esc(p)}'" for p in target_phenotypes)
    return f"""
    SELECT DISTINCT PATIENT_ID,
           '{sign_id}' AS SIGN_ID,
           '{_esc(g['source_phenotype'])}' AS SOURCE_PHENOTYPE,
           '{_esc(g['canonical_atom_or_rule_id'])}' AS CANONICAL_ATOM_OR_RULE_ID,
           '{_esc(g['reasoning_bucket'])}' AS REASONING_BUCKET,
           '{_esc(g['route_or_guardrail'])}' AS ROUTE_OR_GUARDRAIL,
           '{",".join(rule_ids)}' AS TRIGGERING_ATOM,
           NULL AS FIRST_SEEN_DATE
    FROM ATTR_V3_COMBINATION_HITS
    WHERE PHENOTYPE IN ({phen_list}) AND RULE_ID IN ({rule_list})
    """


def _aa30_absence_guardrail_sql(g: Dict[str, Any]) -> str:
    """AA30 shape: ABSENCE-triggered (the only one in this catalog) - fires when
    RENAL is gate-eligible for phenotype AA but INFLAMMATORY_DRIVER is NOT, i.e.
    a real kidney signal with no identified inflammatory/infectious driver despite
    the patient having AA bucket-tier rows computed at all (which requires them to
    have passed the wide net / have some AA-relevant evidence in the first place)."""
    return f"""
    SELECT DISTINCT r.PATIENT_ID,
           'AA30' AS SIGN_ID,
           '{_esc(g['source_phenotype'])}' AS SOURCE_PHENOTYPE,
           '{_esc(g['canonical_atom_or_rule_id'])}' AS CANONICAL_ATOM_OR_RULE_ID,
           '{_esc(g['reasoning_bucket'])}' AS REASONING_BUCKET,
           '{_esc(g['route_or_guardrail'])}' AS ROUTE_OR_GUARDRAIL,
           'RENAL gate-eligible, INFLAMMATORY_DRIVER not gate-eligible' AS TRIGGERING_ATOM,
           NULL AS FIRST_SEEN_DATE
    FROM ATTR_V3_BUCKET_TIER r
    WHERE r.PHENOTYPE = 'AA' AND r.BUCKET = 'RENAL' AND r.GATE_ELIGIBLE
      AND NOT EXISTS (
        SELECT 1 FROM ATTR_V3_BUCKET_TIER d
        WHERE d.PATIENT_ID = r.PATIENT_ID AND d.PHENOTYPE = 'AA'
          AND d.BUCKET = 'INFLAMMATORY_DRIVER' AND d.GATE_ELIGIBLE
      )
    """


def create_guardrails(
    session,
    config_root: Path,
    source_config: Dict[str, Any],
    include_attrv: bool = False,
    include_al: bool = False,
    include_aa: bool = False,
) -> str:
    """WT25/WT26 (atom-triggered) + WT24 (demographic from census).

    ATTRwt pattern-reuse guardrails (same shape as WT29):
      WT27 -> AL_RULE_01/06 when include_al=True
      WT28 -> V_RULE_01 when include_attrv=True
      WT29 -> AA_RULE_01/02 when include_aa=True
    ATTRv: V37 (diabetes atom) when include_attrv=True;
      V39 -> AL_RULE_01/06 when include_al=True (ATTRv twin of WT27).
    WT30 is DO_NOT_USE and is never written here.
    """
    table = "ATTR_V3_GUARDRAIL_HITS"
    by_sign = {g["sign_id"]: g for g in load_guardrails(config_root)}

    unions = []
    for sign_id in ("WT25", "WT26"):
        unions.append(_atom_triggered_guardrail_sql(sign_id, by_sign[sign_id]))

    if include_attrv:
        unions.append(_atom_triggered_guardrail_sql("V37", by_sign["V37"]))
        unions.append(_atom_triggered_guardrail_sql("V38", by_sign["V38"]))
        unions.append(_atom_triggered_guardrail_sql("V32", by_sign["V32"]))
        unions.append(_atom_triggered_guardrail_sql("V33", by_sign["V33"]))
        unions.append(_rule_triggered_guardrail_sql("V41", by_sign["V41"], target_phenotype="ATTRwt"))
        # WT28: ATTRwt patient pattern that looks like neuropathic/autonomic ATTRv
        unions.append(_rule_triggered_guardrail_sql("WT28", by_sign["WT28"], target_phenotype="ATTRv"))

    if include_al:
        unions.append(_atom_triggered_guardrail_sql("AL22", by_sign["AL22"]))
        unions.append(_atom_triggered_guardrail_sql("AL23", by_sign["AL23"]))
        unions.append(_rule_triggered_guardrail_sql("AL30", by_sign["AL30"], target_phenotype="ATTRwt"))
        unions.append(_rule_triggered_guardrail_sql("AL31", by_sign["AL31"], target_phenotype="ATTRv"))
        # WT27: ATTRwt patient pattern that looks AL-oriented multisystem
        unions.append(_rule_triggered_guardrail_sql("WT27", by_sign["WT27"], target_phenotype="AL"))
        # V39: ATTRv patient pattern that looks AL-oriented multisystem (same rules)
        unions.append(_rule_triggered_guardrail_sql("V39", by_sign["V39"], target_phenotype="AL"))

    if include_aa:
        unions.append(_atom_triggered_guardrail_sql("AA26", by_sign["AA26"]))
        unions.append(_atom_triggered_guardrail_sql("AA27", by_sign["AA27"]))
        unions.append(_atom_triggered_guardrail_sql("AA28", by_sign["AA28"]))
        unions.append(_rule_triggered_guardrail_sql("AA29", by_sign["AA29"], target_phenotype="ATTR_COMMON"))
        unions.append(_aa30_absence_guardrail_sql(by_sign["AA30"]))
        unions.append(_rule_triggered_guardrail_sql("WT29", by_sign["WT29"], target_phenotype="AA"))
        unions.append(_rule_triggered_guardrail_sql("V40", by_sign["V40"], target_phenotype="AA"))
        if include_al:
            unions.append(_rule_triggered_guardrail_sql("AL25", by_sign["AL25"], target_phenotype="AA"))
            unions.append(
                _rule_triggered_guardrail_sql_multi(
                    "AA25", by_sign["AA25"], target_phenotypes=["AL", "ATTR_COMMON"]
                )
            )

    g24 = by_sign["WT24"]
    census_cfg = source_config["tables"]["census"]
    census_table = census_cfg["name"]
    patient_col = census_cfg["columns"]["patient_id"]
    gender_col = census_cfg["columns"]["gender"]
    unions.append(f"""
    SELECT DISTINCT a.PATIENT_ID,
           'WT24' AS SIGN_ID,
           '{_esc(g24['source_phenotype'])}' AS SOURCE_PHENOTYPE,
           '{_esc(g24['canonical_atom_or_rule_id'])}' AS CANONICAL_ATOM_OR_RULE_ID,
           '{_esc(g24['reasoning_bucket'])}' AS REASONING_BUCKET,
           '{_esc(g24['route_or_guardrail'])}' AS ROUTE_OR_GUARDRAIL,
           'recorded_sex=F + ATTRwt CARDIO gate-eligible' AS TRIGGERING_ATOM,
           NULL AS FIRST_SEEN_DATE
    FROM ATTR_V3_ATOMS a
    JOIN {census_table} cen ON TRIM(TO_VARCHAR(cen."{patient_col}")) = a.PATIENT_ID
    JOIN ATTR_V3_BUCKET_TIER bt ON bt.PATIENT_ID = a.PATIENT_ID
      AND bt.PHENOTYPE = 'ATTRwt' AND bt.BUCKET = 'CARDIO' AND bt.GATE_ELIGIBLE
    WHERE UPPER(TRIM(TO_VARCHAR(cen."{gender_col}"))) IN ('F','FEMALE')
    """)

    skipped = []
    if not include_al:
        skipped.extend(["WT27", "V39"])
    if not include_attrv:
        skipped.append("WT28")
    if not include_aa:
        skipped.append("WT29")
    if skipped:
        print(
            "NOTE: "
            + "/".join(skipped)
            + " skipped in this run - they reuse AL/ATTRv/AA combination "
            "results that are not computed here. Not faked."
        )
    if include_al and not include_aa:
        print("NOTE: AL25 skipped - it reuses AA_RULE_02, and AA is not computed anywhere yet.")
    if include_aa and not include_al:
        print("NOTE: AL25/AA25 skipped - they reuse AL_RULE_02, and AL is not computed in this run.")

    _sql(session, f"CREATE OR REPLACE TEMPORARY TABLE {table} AS\n" + "\nUNION ALL\n".join(unions))
    return table

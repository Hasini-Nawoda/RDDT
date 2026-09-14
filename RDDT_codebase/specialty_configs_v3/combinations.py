# -*- coding: utf-8 -*-
"""Generic combination-rule engine — reads combinations/*.json directly,
no rule shape is hardcoded/approximated in SQL.

WT01 scope: builds the GENERAL_AMYLOID -> ATTR_COMMON -> ATTRwt funnel,
restricted by default to GA01, AC01, WT_RULE_01/02 (phase3_wt01_only=True).

Rule types implemented: PAIR / PAIR_TEMPORAL, COUNT_DISTINCT_BUCKETS,
ORG_PLUS_ETIOLOGY, PAIR_CLASS (fixed bucket + "any of a class" bucket set,
needed for AL_RULE_06), TRIPLE_WITH_MODIFIER (AA_RULE_01: two required
buckets + a third REQUIRED modifier bucket that strengthens priority without
counting as an independent bucket), and a modifier-aware PAIR variant (AA_RULE_02:
same two required buckets, but the modifier must be ABSENT instead of present -
see _pair_with_absent_modifier_sql).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from common import _esc, _sql, load_combination_file


def _bucket_alias(bucket: str) -> str:
    return "b_" + bucket.lower()


def _tier_cond(req: Dict[str, Any], alias: str) -> str:
    if "exact_tier" in req:
        return f"{alias}.BEST_TIER = {int(req['exact_tier'])}"
    if "max_tier" in req:
        return f"{alias}.BEST_TIER <= {int(req['max_tier'])}"
    return "TRUE"


def _priority_case_sql(rule: Dict[str, Any], bucket_alias: Dict[str, str]) -> str:
    """Build a SQL literal or CASE expression for a rule's priority from priority_when."""
    base_priority = rule.get("priority", "B")
    pw = rule.get("priority_when")
    if not pw:
        return f"'{_esc(base_priority)}'"

    if "branches" in pw:
        whens = []
        for branch in pw["branches"]:
            pr = branch["priority"]
            if "requires" in branch:
                cond = " AND ".join(_tier_cond(r, bucket_alias[r["bucket"]]) for r in branch["requires"])
            elif "requires_exactly_one_of" in branch:
                alts = [
                    "(" + " AND ".join(_tier_cond(r, bucket_alias[r["bucket"]]) for r in opt["requires"]) + ")"
                    for opt in branch["requires_exactly_one_of"]
                ]
                cond = "(" + " OR ".join(alts) + ")"
            else:
                cond = "TRUE"
            whens.append(f"WHEN {cond} THEN '{_esc(pr)}'")
        default = pw.get("default", base_priority)
        return "CASE " + " ".join(whens) + f" ELSE '{_esc(default)}' END"

    if "demote_if" in pw:
        # AA_RULE_02 shape: default priority, demoted to a weaker one when the
        # listed condition holds (opposite direction from if_any/if_all's
        # upgrade-on-match below).
        demote_to = pw.get("demote_to", base_priority)
        default = pw.get("default", base_priority)
        parts = [
            _tier_cond(req, bucket_alias[req["bucket"]])
            for req in pw["demote_if"]
            if "bucket" in req
        ]
        cond = "(" + " AND ".join(parts) + ")" if parts else "FALSE"
        return f"CASE WHEN {cond} THEN '{_esc(demote_to)}' ELSE '{_esc(default)}' END"

    default = pw.get("default", base_priority)
    upgrade = pw.get("upgrade_to", base_priority)
    for key, combiner in (("if_any", " OR "), ("if_all", " AND ")):
        if key in pw:
            parts = []
            for req in pw[key]:
                if "bucket" in req:
                    parts.append(_tier_cond(req, bucket_alias[req["bucket"]]))
                elif "role" in req and req["role"] in bucket_alias:
                    parts.append(f"{bucket_alias[req['role']]}.BEST_TIER <= {int(req.get('max_tier', 1))}")
            cond = "(" + combiner.join(parts) + ")" if parts else "FALSE"
            return f"CASE WHEN {cond} THEN '{_esc(upgrade)}' ELSE '{_esc(default)}' END"
    return f"'{_esc(base_priority)}'"


def _pair_rule_sql(phenotype: str, rule: Dict[str, Any], funnel_table: Optional[str]) -> str:
    """rule_type PAIR / PAIR_TEMPORAL: exactly two named buckets."""
    reqs = rule["requires"]
    b0, b1 = reqs[0]["bucket"], reqs[1]["bucket"]
    a0, a1 = _bucket_alias(b0), _bucket_alias(b1)
    bucket_alias = {b0: a0, b1: a1}
    where = [
        f"{a0}.PHENOTYPE = '{phenotype}' AND {a0}.BUCKET = '{b0}'",
        f"{a1}.PHENOTYPE = '{phenotype}' AND {a1}.BUCKET = '{b1}'",
        f"{a0}.BEST_TIER <= {int(reqs[0]['max_tier'])}",
        f"{a1}.BEST_TIER <= {int(reqs[1]['max_tier'])}",
    ]
    if rule.get("require_gate_eligible"):
        where += [f"{a0}.GATE_ELIGIBLE", f"{a1}.GATE_ELIGIBLE"]

    temporal_join = ""
    if rule.get("temporal_rule_id"):
        temporal_join = (
            f"JOIN ATTR_V3_TEMPORAL_HITS t ON t.PATIENT_ID = {a0}.PATIENT_ID "
            f"AND t.TEMPORAL_RULE_ID = '{_esc(rule['temporal_rule_id'])}'"
        )
        req = rule.get("temporal_requirement")
        if req == "SATISFIED_TRUE":
            where.append("t.SATISFIED = TRUE")
        elif req == "SATISFIED_NULL":
            where.append("t.SATISFIED IS NULL")
        elif req == "SATISFIED_FALSE":
            where.append("t.SATISFIED = FALSE")

    if funnel_table:
        where.append(f"{a0}.PATIENT_ID IN (SELECT PATIENT_ID FROM {funnel_table})")

    priority_sql = _priority_case_sql(rule, bucket_alias)
    return f"""
    SELECT {a0}.PATIENT_ID,
           '{phenotype}' AS PHENOTYPE,
           '{_esc(rule['rule_id'])}' AS RULE_ID,
           {priority_sql} AS PRIORITY,
           '{_esc(rule['output_route'])}' AS OUTPUT_ROUTE,
           '{b0},{b1}' AS CONTRIBUTING_BUCKETS
    FROM ATTR_V3_BUCKET_TIER {a0}
    JOIN ATTR_V3_BUCKET_TIER {a1} ON {a1}.PATIENT_ID = {a0}.PATIENT_ID
    {temporal_join}
    WHERE {" AND ".join(where)}
    """


def _pair_class_sql(phenotype: str, rule: Dict[str, Any], funnel_table: Optional[str]) -> str:
    """rule_type PAIR_CLASS: one fixed bucket + one "any of a class" bucket set
    (e.g. AL_RULE_06: MUCOSAL_CUTANEOUS + ANY_OF{RENAL,CARDIO,NEURO,AUTONOMIC,
    GI_HEPATIC}). No PAIR_CLASS rule in the current config uses priority_when,
    so only a literal priority is supported here - extend _priority_case_sql
    integration if a future rule needs it."""
    reqs = rule["requires"]
    fixed_req = next(r for r in reqs if "bucket" in r)
    class_req = next(r for r in reqs if "bucket_class" in r)
    fixed_bucket = fixed_req["bucket"]
    fixed_max = int(fixed_req["max_tier"])
    class_buckets_sql = ", ".join(f"'{_esc(b)}'" for b in class_req["allowed_buckets"])
    class_max = int(class_req["max_tier"])
    gate = "AND GATE_ELIGIBLE" if rule.get("require_gate_eligible") else ""

    funnel_clause = ""
    if funnel_table:
        funnel_clause = f"AND PATIENT_ID IN (SELECT PATIENT_ID FROM {funnel_table})"

    return f"""
    WITH fixed_side AS (
      SELECT PATIENT_ID
      FROM ATTR_V3_BUCKET_TIER
      WHERE PHENOTYPE = '{phenotype}' AND BUCKET = '{_esc(fixed_bucket)}'
        AND BEST_TIER <= {fixed_max} {gate}
        {funnel_clause}
    ),
    class_side AS (
      SELECT PATIENT_ID, LISTAGG(DISTINCT BUCKET, ',') WITHIN GROUP (ORDER BY BUCKET) AS CLASS_BUCKETS
      FROM ATTR_V3_BUCKET_TIER
      WHERE PHENOTYPE = '{phenotype}' AND BUCKET IN ({class_buckets_sql})
        AND BEST_TIER <= {class_max} {gate}
      GROUP BY PATIENT_ID
    )
    SELECT f.PATIENT_ID,
           '{phenotype}' AS PHENOTYPE,
           '{_esc(rule['rule_id'])}' AS RULE_ID,
           '{_esc(rule.get('priority', 'B'))}' AS PRIORITY,
           '{_esc(rule['output_route'])}' AS OUTPUT_ROUTE,
           '{_esc(fixed_bucket)}' || ',' || c.CLASS_BUCKETS AS CONTRIBUTING_BUCKETS
    FROM fixed_side f
    JOIN class_side c ON c.PATIENT_ID = f.PATIENT_ID
    """


def _modifier_presence_cond(phenotype: str, modifier: Dict[str, Any], patient_alias: str) -> str:
    """Plain bucket-tier existence check for a rule's `modifier` block (AA_RULE_01/02):
    does a ATTR_V3_BUCKET_TIER row exist for modifier['bucket'] at BEST_TIER <=
    modifier['max_tier'], for this same patient? Deliberately ignores GATE_ELIGIBLE -
    AA's INFLAMMATORY_ACTIVITY bucket is marked gate_eligible=false on every one of
    its own atoms (aa.json tags the whole bucket MODIFIER-only), so a gate-eligible
    requirement here would make AA_RULE_01's REQUIRED check impossible to satisfy,
    and (more subtly) would make AA_RULE_02's literal ABSENT_OR_NOT_GATE_ELIGIBLE
    wording always true regardless of whether activity evidence exists at all -
    which would let AA_RULE_01 and AA_RULE_02 both fire for the same patient,
    breaking their mutually_exclusive_with declaration. Using plain tier-presence
    for both sides (present vs. absent) keeps them true opposites. See KNOWN_GAPS.md."""
    bucket = modifier["bucket"]
    max_tier = int(modifier.get("max_tier", 2))
    return (
        f"EXISTS (SELECT 1 FROM ATTR_V3_BUCKET_TIER m WHERE m.PATIENT_ID = {patient_alias}.PATIENT_ID "
        f"AND m.PHENOTYPE = '{phenotype}' AND m.BUCKET = '{_esc(bucket)}' AND m.BEST_TIER <= {max_tier})"
    )


def _triple_with_modifier_sql(phenotype: str, rule: Dict[str, Any], funnel_table: Optional[str]) -> str:
    """rule_type TRIPLE_WITH_MODIFIER (AA_RULE_01): two required buckets (driver +
    renal), plus a REQUIRED modifier bucket that strengthens priority/urgency but,
    per the rule's own counts_as_independent_bucket: false, is NOT a third
    independently-counted bucket - it only gates whether this rule (vs. its
    mutually-exclusive PAIR sibling, AA_RULE_02) fires. See
    _modifier_presence_cond for why GATE_ELIGIBLE is deliberately not checked."""
    reqs = rule["requires"]
    b0, b1 = reqs[0]["bucket"], reqs[1]["bucket"]
    a0, a1 = _bucket_alias(b0), _bucket_alias(b1)
    bucket_alias = {b0: a0, b1: a1}
    where = [
        f"{a0}.PHENOTYPE = '{phenotype}' AND {a0}.BUCKET = '{b0}'",
        f"{a1}.PHENOTYPE = '{phenotype}' AND {a1}.BUCKET = '{b1}'",
        f"{a0}.BEST_TIER <= {int(reqs[0]['max_tier'])}",
        f"{a1}.BEST_TIER <= {int(reqs[1]['max_tier'])}",
    ]
    if rule.get("require_gate_eligible"):
        where += [f"{a0}.GATE_ELIGIBLE", f"{a1}.GATE_ELIGIBLE"]
    where.append(_modifier_presence_cond(phenotype, rule["modifier"], a0))
    if funnel_table:
        where.append(f"{a0}.PATIENT_ID IN (SELECT PATIENT_ID FROM {funnel_table})")

    priority_sql = _priority_case_sql(rule, bucket_alias)
    return f"""
    SELECT {a0}.PATIENT_ID,
           '{phenotype}' AS PHENOTYPE,
           '{_esc(rule['rule_id'])}' AS RULE_ID,
           {priority_sql} AS PRIORITY,
           '{_esc(rule['output_route'])}' AS OUTPUT_ROUTE,
           '{b0},{b1}' AS CONTRIBUTING_BUCKETS
    FROM ATTR_V3_BUCKET_TIER {a0}
    JOIN ATTR_V3_BUCKET_TIER {a1} ON {a1}.PATIENT_ID = {a0}.PATIENT_ID
    WHERE {" AND ".join(where)}
    """


def _pair_with_absent_modifier_sql(phenotype: str, rule: Dict[str, Any], funnel_table: Optional[str]) -> str:
    """rule_type PAIR + a `modifier` block requiring ABSENCE (AA_RULE_02): same two
    required buckets as _pair_rule_sql, plus a NOT EXISTS check that the modifier
    bucket's tier-qualifying evidence is absent - the mutually-exclusive complement
    of AA_RULE_01's REQUIRED modifier check (_modifier_presence_cond). Kept as a
    separate function rather than folded into _pair_rule_sql itself, since no other
    PAIR rule in any phenotype carries a `modifier` key - this keeps every other
    already-shipped PAIR rule's generated SQL untouched."""
    reqs = rule["requires"]
    b0, b1 = reqs[0]["bucket"], reqs[1]["bucket"]
    a0, a1 = _bucket_alias(b0), _bucket_alias(b1)
    bucket_alias = {b0: a0, b1: a1}
    where = [
        f"{a0}.PHENOTYPE = '{phenotype}' AND {a0}.BUCKET = '{b0}'",
        f"{a1}.PHENOTYPE = '{phenotype}' AND {a1}.BUCKET = '{b1}'",
        f"{a0}.BEST_TIER <= {int(reqs[0]['max_tier'])}",
        f"{a1}.BEST_TIER <= {int(reqs[1]['max_tier'])}",
    ]
    if rule.get("require_gate_eligible"):
        where += [f"{a0}.GATE_ELIGIBLE", f"{a1}.GATE_ELIGIBLE"]
    where.append("NOT " + _modifier_presence_cond(phenotype, rule["modifier"], a0))
    if funnel_table:
        where.append(f"{a0}.PATIENT_ID IN (SELECT PATIENT_ID FROM {funnel_table})")

    priority_sql = _priority_case_sql(rule, bucket_alias)
    return f"""
    SELECT {a0}.PATIENT_ID,
           '{phenotype}' AS PHENOTYPE,
           '{_esc(rule['rule_id'])}' AS RULE_ID,
           {priority_sql} AS PRIORITY,
           '{_esc(rule['output_route'])}' AS OUTPUT_ROUTE,
           '{b0},{b1}' AS CONTRIBUTING_BUCKETS
    FROM ATTR_V3_BUCKET_TIER {a0}
    JOIN ATTR_V3_BUCKET_TIER {a1} ON {a1}.PATIENT_ID = {a0}.PATIENT_ID
    WHERE {" AND ".join(where)}
    """


def _count_distinct_buckets_sql(
    phenotype: str, rule: Dict[str, Any], funnel_table: Optional[str] = None
) -> str:
    """funnel_table is optional since GA01 (the first gate, nothing funnels into
    it) uses this same builder with no funnel_table - only rules that declare
    their own funnel_source (e.g. AL_RULE_07) pass one."""
    buckets = ", ".join(f"'{_esc(b)}'" for b in rule["allowed_buckets"])
    max_tier = int(rule.get("max_tier_per_bucket", 2))
    min_count = int(rule.get("min_distinct_buckets", 2))
    gate = "AND GATE_ELIGIBLE" if rule.get("require_gate_eligible") else ""
    funnel_clause = (
        f"AND PATIENT_ID IN (SELECT PATIENT_ID FROM {funnel_table})" if funnel_table else ""
    )
    return f"""
    SELECT PATIENT_ID,
           '{phenotype}' AS PHENOTYPE,
           '{_esc(rule['rule_id'])}' AS RULE_ID,
           '{_esc(rule.get('priority','A'))}' AS PRIORITY,
           '{_esc(rule['output_route'])}' AS OUTPUT_ROUTE,
           LISTAGG(DISTINCT BUCKET, ',') AS CONTRIBUTING_BUCKETS
    FROM ATTR_V3_BUCKET_TIER
    WHERE PHENOTYPE = '{phenotype}' AND BUCKET IN ({buckets})
      AND BEST_TIER <= {max_tier} {gate}{funnel_clause}
    GROUP BY PATIENT_ID
    HAVING COUNT(DISTINCT BUCKET) >= {min_count}
    """


def _org_plus_etiology_sql(phenotype: str, rule: Dict[str, Any]) -> str:
    organ_req = next(r for r in rule["requires"] if r.get("role") == "ORGAN")
    etio_req = next(r for r in rule["requires"] if r.get("role") == "ETIOLOGY")
    organ_buckets = ", ".join(f"'{_esc(b)}'" for b in organ_req["allowed_buckets"])
    etio_buckets = ", ".join(f"'{_esc(b)}'" for b in etio_req["allowed_buckets"])
    organ_max = int(organ_req.get("max_tier", 2))
    etio_max = int(etio_req.get("max_tier", 2))
    gate = "AND GATE_ELIGIBLE" if rule.get("require_gate_eligible") else ""

    pw = rule.get("priority_when") or {}
    default_p = pw.get("default", rule.get("priority", "B"))
    upgrade_p = pw.get("upgrade_to", rule.get("priority", "A"))
    up_organ_tier, up_etio_tier = 1, 1
    for cond in pw.get("if_all", []):
        if cond.get("role") == "ORGAN":
            up_organ_tier = int(cond.get("max_tier", 1))
        elif cond.get("role") == "ETIOLOGY":
            up_etio_tier = int(cond.get("max_tier", 1))

    return f"""
    WITH organ AS (
      SELECT PATIENT_ID, MIN(BEST_TIER) AS BEST_ORGAN_TIER
      FROM ATTR_V3_BUCKET_TIER
      WHERE PHENOTYPE = '{phenotype}' AND BUCKET IN ({organ_buckets})
        AND BEST_TIER <= {organ_max} {gate}
      GROUP BY PATIENT_ID
    ),
    etiology AS (
      SELECT PATIENT_ID, MIN(BEST_TIER) AS BEST_ETIOLOGY_TIER
      FROM ATTR_V3_BUCKET_TIER
      WHERE PHENOTYPE = '{phenotype}' AND BUCKET IN ({etio_buckets})
        AND BEST_TIER <= {etio_max} {gate}
      GROUP BY PATIENT_ID
    )
    SELECT o.PATIENT_ID,
           '{phenotype}' AS PHENOTYPE,
           '{_esc(rule['rule_id'])}' AS RULE_ID,
           CASE WHEN o.BEST_ORGAN_TIER <= {up_organ_tier} AND e.BEST_ETIOLOGY_TIER <= {up_etio_tier}
                THEN '{_esc(upgrade_p)}' ELSE '{_esc(default_p)}' END AS PRIORITY,
           '{_esc(rule['output_route'])}' AS OUTPUT_ROUTE,
           'ORGAN+ETIOLOGY' AS CONTRIBUTING_BUCKETS
    FROM organ o
    JOIN etiology e ON o.PATIENT_ID = e.PATIENT_ID
    """


def create_combinations(
    session,
    config_root: Path,
    phase3_wt01_only: bool = True,
    build_al: bool = False,
    build_aa: bool = False,
) -> str:
    """Funnel: GENERAL_AMYLOID -> ATTR_COMMON -> ATTRwt.

    Default (phase3_wt01_only=True): GA01, AC01, WT_RULE_01/02 only — the WT01
    checklist slice. Set False later when expanding phenotypes.

    build_al=True additionally builds AL_RULE_01-07 (all funnel through
    GENERAL_AMYLOID, none through ATTR_COMMON) - independent of build_attrv,
    but only meaningful when phase3_wt01_only=False too (GA02 must also be
    running for AL's own HEME_CLONAL+organ pairs to pass the GA funnel; GA02
    already builds automatically whenever phase3_wt01_only=False).

    build_aa=True additionally builds AA_RULE_01 (TRIPLE_WITH_MODIFIER) and
    AA_RULE_02 (PAIR + an ABSENT modifier check) - both funnel through
    GENERAL_AMYLOID only (same as AL), and both need GA02's INFLAMMATORY_DRIVER
    etiology option actually extracting atoms (AA_BUCKETS in the caller's
    combined bucket set) for GENERAL_AMYLOID_PASS to admit AA-shaped patients.
    Independent of build_al/build_attrv.
    """
    table = "ATTR_V3_COMBINATION_HITS"
    ga_pass_table = "ATTR_V3_GA_PASS_IDS"
    ac_pass_table = "ATTR_V3_AC_PASS_IDS"

    # ATTRv is NEVER built when phase3_wt01_only=True, regardless of what's in
    # allow["ATTR_COMMON"] - keeps the default WT01-only pipeline's combination
    # output byte-identical to before ATTRv existed. Widening ATTR_COMMON to
    # AC02-08 only takes effect together with phase3_wt01_only=False, since
    # AC02-08 passing more patients into ATTR_V3_AC_PASS_IDS would otherwise
    # silently change WT_RULE_01/02's own funnel population.
    allow = {
        "GENERAL_AMYLOID": {"GA01"},
        "ATTR_COMMON": {"AC01"},
        "ATTRwt": {"WT_RULE_01", "WT_RULE_02"},
    } if phase3_wt01_only else None
    build_attrv = not phase3_wt01_only

    ga_rules = load_combination_file(config_root, "general_amyloid.json")
    ga_unions = []
    for rule in ga_rules:
        if allow and rule["rule_id"] not in allow["GENERAL_AMYLOID"]:
            continue
        if rule["rule_type"] == "COUNT_DISTINCT_BUCKETS":
            ga_unions.append(_count_distinct_buckets_sql("GENERAL_AMYLOID", rule))
        elif rule["rule_type"] == "ORG_PLUS_ETIOLOGY":
            ga_unions.append(_org_plus_etiology_sql("GENERAL_AMYLOID", rule))
        else:
            print(f"NOTE: GA rule {rule.get('rule_id')} unsupported type "
                  f"{rule.get('rule_type')!r} - skipped.")
    if not ga_unions:
        raise ValueError("No GENERAL_AMYLOID combination SQL generated (expected GA01).")
    _sql(session, f"CREATE OR REPLACE TEMPORARY TABLE {table} AS\n" + "\nUNION ALL\n".join(ga_unions))
    _sql(session, f"CREATE OR REPLACE TEMPORARY TABLE {ga_pass_table} AS "
                  f"SELECT DISTINCT PATIENT_ID FROM {table} WHERE PHENOTYPE = 'GENERAL_AMYLOID'")

    ac_rules = load_combination_file(config_root, "attr_common.json")
    ac_unions = []
    for rule in ac_rules:
        if allow and rule["rule_id"] not in allow["ATTR_COMMON"]:
            continue
        if rule["rule_type"] == "PAIR":
            ac_unions.append(_pair_rule_sql("ATTR_COMMON", rule, ga_pass_table))
    if ac_unions:
        _sql(session, f"INSERT INTO {table}\n" + "\nUNION ALL\n".join(ac_unions))
    _sql(session, f"CREATE OR REPLACE TEMPORARY TABLE {ac_pass_table} AS "
                  f"SELECT DISTINCT PATIENT_ID FROM {table} WHERE PHENOTYPE = 'ATTR_COMMON'")

    wt_rules = load_combination_file(config_root, "attrwt.json")
    wt_unions = []
    for rule in wt_rules:
        if allow and rule["rule_id"] not in allow["ATTRwt"]:
            continue
        funnel_table = ac_pass_table if rule.get("funnel_source") == "ATTR_COMMON" else ga_pass_table
        wt_unions.append(_pair_rule_sql("ATTRwt", rule, funnel_table))
    if wt_unions:
        _sql(session, f"INSERT INTO {table}\n" + "\nUNION ALL\n".join(wt_unions))

    if build_attrv:
        v_rules = load_combination_file(config_root, "attrv.json")
        v_unions = []
        for rule in v_rules:
            if rule["rule_type"] != "PAIR":
                print(f"NOTE: ATTRv rule {rule.get('rule_id')} unsupported type "
                      f"{rule.get('rule_type')!r} - skipped.")
                continue
            funnel_table = ac_pass_table if rule.get("funnel_source") == "ATTR_COMMON" else ga_pass_table
            v_unions.append(_pair_rule_sql("ATTRv", rule, funnel_table))
        if v_unions:
            _sql(session, f"INSERT INTO {table}\n" + "\nUNION ALL\n".join(v_unions))

    if build_al:
        al_rules = load_combination_file(config_root, "al.json")
        al_unions = []
        for rule in al_rules:
            # All AL rules funnel through GENERAL_AMYLOID (none through ATTR_COMMON).
            funnel_table = ga_pass_table
            if rule["rule_type"] == "PAIR":
                al_unions.append(_pair_rule_sql("AL", rule, funnel_table))
            elif rule["rule_type"] == "PAIR_CLASS":
                al_unions.append(_pair_class_sql("AL", rule, funnel_table))
            elif rule["rule_type"] == "COUNT_DISTINCT_BUCKETS":
                al_unions.append(_count_distinct_buckets_sql("AL", rule, funnel_table))
            else:
                print(f"NOTE: AL rule {rule.get('rule_id')} unsupported type "
                      f"{rule.get('rule_type')!r} - skipped.")
        if al_unions:
            _sql(session, f"INSERT INTO {table}\n" + "\nUNION ALL\n".join(al_unions))

    if build_aa:
        aa_rules = load_combination_file(config_root, "aa.json")
        aa_unions = []
        for rule in aa_rules:
            # Both AA rules funnel through GENERAL_AMYLOID (same as AL).
            funnel_table = ga_pass_table
            if rule["rule_type"] == "TRIPLE_WITH_MODIFIER":
                aa_unions.append(_triple_with_modifier_sql("AA", rule, funnel_table))
            elif rule["rule_type"] == "PAIR" and rule.get("modifier"):
                aa_unions.append(_pair_with_absent_modifier_sql("AA", rule, funnel_table))
            elif rule["rule_type"] == "PAIR":
                aa_unions.append(_pair_rule_sql("AA", rule, funnel_table))
            else:
                print(f"NOTE: AA rule {rule.get('rule_id')} unsupported type "
                      f"{rule.get('rule_type')!r} - skipped.")
        if aa_unions:
            _sql(session, f"INSERT INTO {table}\n" + "\nUNION ALL\n".join(aa_unions))

    return table

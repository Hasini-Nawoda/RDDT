# -*- coding: utf-8 -*-
"""Composite rules: multi-signal source rows derived without double-counting.

Three shapes implemented:
  - Shape A (WITHIN_BUCKET_COUNT): create_ortho_cluster - WT04, ATTRwt's
    ORTHO_CLUSTER. Reads ATTR_V3_ATOMS directly (pre-bucket-tier-rollup).
  - Shape B (CROSS_BUCKET_COUNT_AMONG_SET): create_neuro_plus_systemic - V03,
    ATTRv's NEURO_PLUS_SYSTEMIC. Reads ATTR_V3_BUCKET_TIER (post-rollup),
    since it counts across independent buckets, not within one.
  - Shape C (WITHIN_BUCKET_DERIVED_DISCRIMINATOR): create_renal_disproportionate
    - AA21, AA's RENAL_DISPROPORTIONATE. Reads ATTR_V3_ATOMS directly, like
    Shape A (pre-bucket-tier-rollup) - deliberately, so it can run BEFORE
    create_bucket_tiers and feed straight into it (same ordering as Shape A /
    ORTHO_CLUSTER), rather than needing a second bucket-tier pass.

composites/shape_b_c.json has other entries (V06/NEURO_CARDIO_MIXED,
AL21/AL26/AL27) not implemented here - those are AL/ATTRv shapes decided
redundant with rules already built via the combination-rule engine (see
KNOWN_GAPS.md / pipeline.run_full_pipeline's own docstring for why).
"""

from __future__ import annotations

from typing import Any, Dict, Sequence

from common import _esc, _sql


def create_ortho_cluster(session, cluster: Dict[str, Any]) -> str:
    """Shape A: distinct member signals >= min_count -> ORTHO_CLUSTER_FIRED + first_seen."""
    table = "ATTR_V3_COMPOSITE_HITS"
    signals = cluster.get("member_signals") or []
    min_count = int(cluster.get("min_count") or 2)
    signal_flags = []
    signal_dates = []
    for i, sig in enumerate(signals):
        aids = sig.get("atom_ids") or []
        if not aids:
            continue
        ors = " OR ".join(f"COALESCE({a.upper()}, 0) = 1" for a in aids)
        signal_flags.append(f"IFF({ors}, 1, 0)")
        date_coalesce = ", ".join(
            f"COALESCE({a.upper()}_FIRST_SEEN, DATE '9999-12-31')" for a in aids
        )
        signal_dates.append(
            f"IFF({ors}, NULLIF(LEAST({date_coalesce}), DATE '9999-12-31'), NULL)"
        )
    sum_expr = " + ".join(signal_flags) if signal_flags else "0"
    # signal_dates are IFF(... NULLIF(LEAST(...))) expressions; COALESCE so LEAST ignores missing signals
    coalesce_dates = (
        ", ".join(f"COALESCE(({d}), DATE '9999-12-31')" for d in signal_dates)
        if signal_dates
        else "DATE '9999-12-31'"
    )
    sql = f"""
    CREATE OR REPLACE TEMPORARY TABLE {table} AS
    SELECT PATIENT_ID,
           'ORTHO_CLUSTER' AS COMPOSITE_RULE_ID,
           'WT04' AS SOURCE_SIGN_ID,
           IFF(({sum_expr}) >= {min_count}, TRUE, FALSE) AS FIRED,
           ({sum_expr}) AS CONTRIBUTING_COUNT,
           CASE WHEN ({sum_expr}) >= {min_count}
                THEN NULLIF(LEAST({coalesce_dates}), DATE '9999-12-31')
                ELSE NULL END AS FIRST_SEEN_DATE
    FROM ATTR_V3_ATOMS
    """
    _sql(session, sql)
    return table


def create_neuro_plus_systemic(session, composite: Dict[str, Any]) -> str:
    """Shape B (CROSS_BUCKET_COUNT_AMONG_SET): V03/NEURO_PLUS_SYSTEMIC.

    Fires when BOTH:
      (a) anchor present - idiopathic axonal neuropathy, via preferred_atom_ids
          (checked on ATTR_V3_ATOMS) OR the bucket_fallback (NEURO tier <= max_tier,
          checked on ATTR_V3_BUCKET_TIER for phenotype=ATTRv) if neither preferred
          atom was extracted/fired;
      (b) at least min_count of count_from_buckets are ATTRv Tier <= max_tier_for_count.

    Cross-bucket, so it reads ATTR_V3_BUCKET_TIER (post-rollup) for the count,
    unlike Shape A which reads ATTR_V3_ATOMS directly (within one bucket, pre-rollup).
    Writes to the same ATTR_V3_COMPOSITE_HITS table as Shape A composites, one
    more row per patient with COMPOSITE_RULE_ID = the composite's own derived_rule_id.
    """
    table = "ATTR_V3_COMPOSITE_HITS"
    rule_id = composite["derived_rule_id"]
    sign_id = composite["source_sign_id"]
    phenotype = composite["phenotype"]

    anchor = composite.get("anchor") or {}
    preferred_atom_ids = anchor.get("preferred_atom_ids") or []
    fallback = anchor.get("bucket_fallback") or {}
    fallback_bucket = fallback.get("bucket")
    fallback_max_tier = int(fallback.get("max_tier", 2))

    count_buckets = composite.get("count_from_buckets") or []
    max_tier_for_count = int(composite.get("max_tier_for_count", 2))
    min_count = int(composite.get("min_count", 2))

    anchor_atom_cond = (
        " OR ".join(f"COALESCE(a.{aid.upper()}, 0) = 1" for aid in preferred_atom_ids)
        if preferred_atom_ids
        else "FALSE"
    )
    anchor_date_parts = [
        f"IFF(COALESCE(a.{aid.upper()}, 0) = 1, a.{aid.upper()}_FIRST_SEEN, DATE '9999-12-31')"
        for aid in preferred_atom_ids
    ]

    fallback_join = ""
    fallback_cond = "FALSE"
    fallback_date_sql = "DATE '9999-12-31'"
    if fallback_bucket:
        fallback_join = f"""
        LEFT JOIN ATTR_V3_BUCKET_TIER fb
          ON fb.PATIENT_ID = a.PATIENT_ID AND fb.PHENOTYPE = '{_esc(phenotype)}'
         AND fb.BUCKET = '{_esc(fallback_bucket)}'"""
        fallback_cond = f"(fb.BEST_TIER IS NOT NULL AND fb.BEST_TIER <= {fallback_max_tier})"
        fallback_date_sql = f"COALESCE(fb.FIRST_SEEN_DATE, DATE '9999-12-31')"

    anchor_present = f"({anchor_atom_cond}) OR {fallback_cond}"
    anchor_dates = ", ".join(anchor_date_parts + [fallback_date_sql]) or fallback_date_sql

    count_cte_parts = []
    for bucket in count_buckets:
        count_cte_parts.append(
            f"""
            SELECT PATIENT_ID, 1 AS HIT
            FROM ATTR_V3_BUCKET_TIER
            WHERE PHENOTYPE = '{_esc(phenotype)}' AND BUCKET = '{_esc(bucket)}'
              AND BEST_TIER <= {max_tier_for_count}
            """
        )
    count_union = "\nUNION ALL\n".join(count_cte_parts) if count_cte_parts else "SELECT NULL AS PATIENT_ID, 0 AS HIT WHERE FALSE"

    sql = f"""
    INSERT INTO {table}
    WITH systemic_counts AS (
        SELECT PATIENT_ID, COUNT(*) AS N_BUCKETS
        FROM (
            {count_union}
        )
        GROUP BY PATIENT_ID
    )
    SELECT a.PATIENT_ID,
           '{_esc(rule_id)}' AS COMPOSITE_RULE_ID,
           '{_esc(sign_id)}' AS SOURCE_SIGN_ID,
           IFF(({anchor_present}) AND COALESCE(sc.N_BUCKETS, 0) >= {min_count}, TRUE, FALSE) AS FIRED,
           COALESCE(sc.N_BUCKETS, 0) AS CONTRIBUTING_COUNT,
           CASE WHEN ({anchor_present}) AND COALESCE(sc.N_BUCKETS, 0) >= {min_count}
                THEN NULLIF(LEAST({anchor_dates}), DATE '9999-12-31')
                ELSE NULL END AS FIRST_SEEN_DATE
    FROM ATTR_V3_ATOMS a
    {fallback_join}
    LEFT JOIN systemic_counts sc ON sc.PATIENT_ID = a.PATIENT_ID
    """
    _sql(session, sql)
    return table


def create_renal_disproportionate(
    session,
    composite: Dict[str, Any],
    driver_atom_ids: Sequence[str],
) -> str:
    """Shape C (WITHIN_BUCKET_DERIVED_DISCRIMINATOR): AA21/RENAL_DISPROPORTIONATE.

    Fires when BOTH:
      (a) context_required - at least one AA INFLAMMATORY_DRIVER atom present
          (driver_atom_ids, passed in already tier-filtered by the caller); and
      (b) at least one of the composite's own min_signal_atom_ids (real kidney
          findings: urine_protein_result, nephrotic_range_proteinuria,
          nephrotic_syndrome, egfr_result, creatinine_result, renal_dysfunction,
          progressive_proteinuria) is present.

    When both fire, this feeds RENAL Tier 1 for phenotype AA in
    create_bucket_tiers (via KNOWN_COMPOSITE_RULE_IDS, same mechanism as
    ORTHO_CLUSTER feeding ORTHO for ATTRwt).

    KNOWN GAP (see KNOWN_GAPS.md): the composite's own confound_atom_ids
    (diabetes, hypertension) and its comparator
    ("RENAL_FINDING_PRESENT_AND_NOT_FULLY_EXPLAINED_BY_CONFOUND_ATOMS_ALONE")
    are NOT enforced here - this fires on renal-finding-presence +
    inflammatory-driver-context alone, without checking whether diabetes/
    hypertension already fully explain the renal picture. The source config
    itself says confounds must "down-weight confidence" but "not hard-exclude
    AA", so a real implementation needs a design decision on exactly how much
    to down-weight, not just an exclusion switch - deferred, not silently
    skipped.
    """
    table = "ATTR_V3_COMPOSITE_HITS"
    rule_id = composite["derived_rule_id"]
    sign_id = composite["source_sign_id"]
    anchor = composite.get("anchor") or {}
    renal_atom_ids = anchor.get("min_signal_atom_ids") or []

    driver_cond = (
        " OR ".join(f"COALESCE({a.upper()}, 0) = 1" for a in driver_atom_ids)
        if driver_atom_ids
        else "FALSE"
    )
    renal_cond = (
        " OR ".join(f"COALESCE({a.upper()}, 0) = 1" for a in renal_atom_ids)
        if renal_atom_ids
        else "FALSE"
    )
    renal_count = (
        " + ".join(f"IFF(COALESCE({a.upper()}, 0) = 1, 1, 0)" for a in renal_atom_ids)
        if renal_atom_ids
        else "0"
    )
    date_coalesce = (
        ", ".join(
            f"IFF(COALESCE({a.upper()}, 0) = 1, {a.upper()}_FIRST_SEEN, DATE '9999-12-31')"
            for a in renal_atom_ids
        )
        if renal_atom_ids
        else "DATE '9999-12-31'"
    )

    sql = f"""
    INSERT INTO {table}
    SELECT PATIENT_ID,
           '{_esc(rule_id)}' AS COMPOSITE_RULE_ID,
           '{_esc(sign_id)}' AS SOURCE_SIGN_ID,
           IFF(({driver_cond}) AND ({renal_cond}), TRUE, FALSE) AS FIRED,
           ({renal_count}) AS CONTRIBUTING_COUNT,
           CASE WHEN ({driver_cond}) AND ({renal_cond})
                THEN NULLIF(LEAST({date_coalesce}), DATE '9999-12-31')
                ELSE NULL END AS FIRST_SEEN_DATE
    FROM ATTR_V3_ATOMS
    """
    _sql(session, sql)
    return table

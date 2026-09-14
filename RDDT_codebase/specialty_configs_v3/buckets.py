# -*- coding: utf-8 -*-
"""Bucket-tier computation: phenotype_overlays/*.json -> ATTR_V3_BUCKET_TIER.

Each phenotype (GENERAL_AMYLOID / ATTR_COMMON / ATTRwt) reads its OWN overlay
file and gets a best-tier-per-bucket row via LEAST(); tiers are never added.
Restricted to WT01_GATE_BUCKETS (ORTHO/CARDIO) by default since that is all
the WT01 slice extracts atoms for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from common import (
    PHENOTYPE_OVERLAY_FILES,
    WT01_GATE_BUCKETS,
    _sql,
    load_overlay_file,
)

# composite_rule_id keys that phenotype_overlays/*.json entries can carry
# instead of an atom_id (build_bucket_tier_map's keys can be either kind).
# least_sql needs to know which of these to LEFT JOIN against
# ATTR_V3_COMPOSITE_HITS instead of looking for an ATTR_V3_ATOMS column.
# Update this tuple whenever a new composite gets wired into create_bucket_tiers.
KNOWN_COMPOSITE_RULE_IDS = ("ORTHO_CLUSTER", "RENAL_DISPROPORTIONATE")


def build_bucket_tier_map(
    overlays: Sequence[Dict[str, Any]]
) -> Dict[str, Dict[str, Tuple[int, bool]]]:
    """bucket -> {atom_id_or_composite_rule_id: (tier, gate_eligible)}, from ONE phenotype's
    own overlay file. Only rows carrying a numeric tier participate (guardrail/route rows
    never appear in phenotype_overlays/*.json, so nothing to filter out there)."""
    buckets: Dict[str, Dict[str, Tuple[int, bool]]] = {}
    for o in overlays:
        tier = o.get("tier")
        bucket = o.get("bucket")
        if tier is None or not bucket:
            continue
        gate = bool(o.get("gate_eligible"))
        if o.get("is_composite") or o.get("composite_rule_id"):
            key = o.get("composite_rule_id")
        else:
            key = o.get("atom_id")
        if not key:
            continue
        buckets.setdefault(bucket, {})[key] = (int(tier), gate)
    return buckets


def create_bucket_tiers(
    session,
    config_root: Path,
    buckets_only: Sequence[str] = WT01_GATE_BUCKETS,
    available_atom_ids: Optional[Sequence[str]] = None,
    phenotype_files: Optional[Dict[str, str]] = None,
) -> str:
    """GENERAL_AMYLOID + ATTR_COMMON + ATTRwt bucket tiers via LEAST(), each phenotype
    reading its OWN phenotype_overlays/*.json file (not a reused/approximated map).

    buckets_only restricts which buckets get built - defaults to ORTHO/CARDIO.
    available_atom_ids (if given) further filters overlay keys so SQL never references
    ATTR_V3_ATOMS columns that were not extracted.
    phenotype_files MUST be passed explicitly by every caller that needs a fixed
    phenotype set (defaults to the full, shared PHENOTYPE_OVERLAY_FILES, which grows
    over time as more phenotypes get registered) - a caller relying on the default
    would silently start computing rows for a newly-registered phenotype it never
    asked for. This is the same bug class as wt01_atom_ids' overlay_filenames param.

    FIRST_SEEN_DATE / GATE_ELIGIBLE follow architecture file 10:
      earliest date among evidence that produced BEST_TIER;
      gate true only if BEST_TIER is 1-2 and a winning contributor is gate_eligible.
    """
    table = "ATTR_V3_BUCKET_TIER"
    phenotypes = phenotype_files if phenotype_files is not None else PHENOTYPE_OVERLAY_FILES
    available = set(available_atom_ids) if available_atom_ids is not None else None

    def least_sql(phenotype: str, bucket: str, tier_map: Dict[str, Tuple[int, bool]]) -> str:
        # Keep only extracted atoms (+ composite keys - always usable, never
        # filtered by `available` since they're not atom ids to begin with).
        usable: Dict[str, Tuple[int, bool]] = {}
        for key, meta in tier_map.items():
            if key in KNOWN_COMPOSITE_RULE_IDS:
                usable[key] = meta
            elif available is None or key in available:
                usable[key] = meta
        if not usable:
            return ""

        # ORTHO_CLUSTER keeps its original bare "c" alias (byte-identical SQL
        # for every already-shipped ORTHO/CARDIO/ATTRv/AL bucket); any OTHER
        # composite key (e.g. RENAL_DISPROPORTIONATE) gets its own alias and
        # LEFT JOIN, added only when that bucket's own tier_map references it.
        def composite_alias(key: str) -> str:
            return "c" if key == "ORTHO_CLUSTER" else f"c_{key.lower()}"

        tier_parts = []
        for key, (tier, _gate) in usable.items():
            if key in KNOWN_COMPOSITE_RULE_IDS:
                alias = composite_alias(key)
                tier_parts.append(f"IFF({alias}.FIRED = TRUE, {tier}, 99)")
            else:
                tier_parts.append(f"IFF(COALESCE(a.{key.upper()}, 0) = 1, {tier}, 99)")
        least_tier = f"LEAST({', '.join(tier_parts)})"

        # Dates / gate only from contributors that produced BEST_TIER.
        date_parts = []
        gate_parts = []
        for key, (tier, gate) in usable.items():
            if key in KNOWN_COMPOSITE_RULE_IDS:
                alias = composite_alias(key)
                date_parts.append(
                    f"IFF({alias}.FIRED = TRUE AND {tier} = ({least_tier}), "
                    f"{alias}.FIRST_SEEN_DATE, DATE '9999-12-31')"
                )
                if gate and tier <= 2:
                    gate_parts.append(f"({alias}.FIRED = TRUE AND {tier} = ({least_tier}))")
            else:
                col = key.upper()
                date_parts.append(
                    f"IFF(COALESCE(a.{col}, 0) = 1 AND {tier} = ({least_tier}), "
                    f"a.{col}_FIRST_SEEN, DATE '9999-12-31')"
                )
                if gate and tier <= 2:
                    gate_parts.append(
                        f"(COALESCE(a.{col}, 0) = 1 AND {tier} = ({least_tier}))"
                    )

        least_date = f"NULLIF(LEAST({', '.join(date_parts)}), DATE '9999-12-31')"
        gate_any = " OR ".join(gate_parts) if gate_parts else "FALSE"

        # ORTHO_CLUSTER's join is always present (byte-identical to before -
        # harmless no-op when the bucket doesn't reference it). Any other
        # composite key referenced by THIS bucket gets an additional join.
        extra_joins = ""
        for key in usable:
            if key in KNOWN_COMPOSITE_RULE_IDS and key != "ORTHO_CLUSTER":
                alias = composite_alias(key)
                extra_joins += (
                    f"\n        LEFT JOIN ATTR_V3_COMPOSITE_HITS {alias}"
                    f"\n          ON a.PATIENT_ID = {alias}.PATIENT_ID AND {alias}.COMPOSITE_RULE_ID = '{key}'"
                )

        return f"""
        SELECT a.PATIENT_ID,
               '{phenotype}' AS PHENOTYPE,
               '{bucket}' AS BUCKET,
               {least_tier} AS BEST_TIER,
               IFF(({least_tier}) BETWEEN 1 AND 2 AND ({gate_any}), TRUE, FALSE) AS GATE_ELIGIBLE,
               {least_date} AS FIRST_SEEN_DATE
        FROM ATTR_V3_ATOMS a
        LEFT JOIN ATTR_V3_COMPOSITE_HITS c
          ON a.PATIENT_ID = c.PATIENT_ID AND c.COMPOSITE_RULE_ID = 'ORTHO_CLUSTER'{extra_joins}
        WHERE ({least_tier}) < 99
        """

    unions = []
    for phenotype, fname in phenotypes.items():
        overlays = load_overlay_file(config_root, fname)
        bucket_map = build_bucket_tier_map(overlays)
        for bucket, tmap in bucket_map.items():
            if not tmap or bucket not in buckets_only:
                continue
            sql_frag = least_sql(phenotype, bucket, tmap)
            if sql_frag:
                unions.append(sql_frag)

    if not unions:
        raise ValueError(
            "create_bucket_tiers produced no ORTHO/CARDIO SQL — check overlays vs extracted atoms."
        )
    sql = f"CREATE OR REPLACE TEMPORARY TABLE {table} AS\n" + "\nUNION ALL\n".join(unions)
    _sql(session, sql)
    return table

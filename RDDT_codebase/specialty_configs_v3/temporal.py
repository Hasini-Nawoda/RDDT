# -*- coding: utf-8 -*-
"""Temporal rules: temporal_rules/longitudinal_patterns.json -> ATTR_V3_TEMPORAL_HITS.

WT01 only needs T01 (ORTHO_BEFORE_CARDIO). T02-T07 belong to ATTRv/AA/AL and
are out of scope here.
"""

from __future__ import annotations

from pathlib import Path

from common import _esc, _sql, load_temporal_rule


def create_temporal_t01(session, config_root: Path) -> str:
    """Reads left_bucket/right_bucket/phenotype from temporal_rules/longitudinal_patterns.json's
    T01 entry instead of hardcoding them."""
    table = "ATTR_V3_TEMPORAL_HITS"
    rule = load_temporal_rule(config_root, "T01")
    phenotype = rule["phenotype"]
    left_bucket = rule["left_bucket"]
    right_bucket = rule["right_bucket"]
    sql = f"""
    CREATE OR REPLACE TEMPORARY TABLE {table} AS
    SELECT o.PATIENT_ID,
           'T01' AS TEMPORAL_RULE_ID,
           '{_esc(rule["source_sign_ids"][0])}' AS SOURCE_SIGN_ID,
           '{_esc(rule["pattern"])}' AS PATTERN,
           CASE
             WHEN o.FIRST_SEEN_DATE IS NULL OR c.FIRST_SEEN_DATE IS NULL THEN NULL
             WHEN o.FIRST_SEEN_DATE < c.FIRST_SEEN_DATE THEN TRUE
             ELSE FALSE
           END AS SATISFIED,
           CASE
             WHEN o.FIRST_SEEN_DATE IS NULL OR c.FIRST_SEEN_DATE IS NULL THEN NULL
             ELSE DATEDIFF('year', o.FIRST_SEEN_DATE, c.FIRST_SEEN_DATE)
           END AS YEARS_BETWEEN,
           o.FIRST_SEEN_DATE AS ORTHO_FIRST_SEEN,
           c.FIRST_SEEN_DATE AS CARDIO_FIRST_SEEN
    FROM ATTR_V3_BUCKET_TIER o
    JOIN ATTR_V3_BUCKET_TIER c
      ON o.PATIENT_ID = c.PATIENT_ID
     AND o.PHENOTYPE = '{phenotype}' AND o.BUCKET = '{left_bucket}'
     AND c.PHENOTYPE = '{phenotype}' AND c.BUCKET = '{right_bucket}'
    """
    _sql(session, sql)
    return table

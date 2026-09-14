# -*- coding: utf-8 -*-
"""Final router output: ATTR_V3_ROUTER_OUTPUT, one row per candidate patient
who passed GENERAL_AMYLOID, ATTR_COMMON, ATTRwt (WT_RULE_01/02), ATTRv
(V_RULE_*, when include_attrv=True), AL (AL_RULE_*, when include_al=True), AA
(AA_RULE_*, when include_aa=True), or a guardrail.

Plus the preview_* helpers used to inspect each stage from the notebook.
"""

from __future__ import annotations

from common import _esc, _sql


def create_router_output(
    session,
    include_attrv: bool = False,
    include_al: bool = False,
    include_aa: bool = False,
) -> str:
    """include_attrv=False (default) keeps ATTRV as the literal 'NOT_YET_IMPLEMENTED'
    - used by the plain WT01-only orchestrator, where ATTRv combinations were never
    computed, so ATTR_V3_COMBINATION_HITS has zero PHENOTYPE='ATTRv' rows and showing
    'INSUFFICIENT' would misleadingly imply we checked and found nothing, rather than
    never having checked at all. include_attrv=True computes a real ATTRV column the
    same way ATTRWT is computed (best-priority V_RULE hit, or INSUFFICIENT).

    include_al=True does the same for a real AL column (best-priority AL_RULE hit).
    Independent of include_attrv, but only meaningful together in practice since
    AL31 (a guardrail) depends on ATTRv also being computed.

    include_aa=True does the same for a real AA column (best-priority AA_RULE hit).
    Independent of include_attrv/include_al, but only meaningful together in
    practice since AL25/WT29/V40 (guardrails) depend on AA also being computed."""
    table = "ATTR_V3_ROUTER_OUTPUT"
    attrv_cte = ""
    attrv_join = ""
    attrv_select = "'NOT_YET_IMPLEMENTED' AS ATTRV,"
    attrv_route_for_all_routes = ""
    if include_attrv:
        attrv_cte = """
    v_ranked AS (
      SELECT PATIENT_ID, RULE_ID, PRIORITY, OUTPUT_ROUTE,
             ROW_NUMBER() OVER (PARTITION BY PATIENT_ID ORDER BY PRIORITY ASC) AS RN
      FROM ATTR_V3_COMBINATION_HITS
      WHERE PHENOTYPE = 'ATTRv'
    ),
    v AS (
      SELECT PATIENT_ID, RULE_ID, PRIORITY, OUTPUT_ROUTE FROM v_ranked WHERE RN = 1
    ),"""
        attrv_join = "LEFT JOIN v ON b.PATIENT_ID = v.PATIENT_ID"
        attrv_select = """CASE
             WHEN v.RULE_ID IS NULL THEN 'INSUFFICIENT'
             ELSE 'PRIORITY_' || v.PRIORITY
           END AS ATTRV,
           v.RULE_ID AS ATTRV_RULE_ID,
           v.OUTPUT_ROUTE AS ATTRV_ROUTE,"""
        attrv_route_for_all_routes = "ARRAY_CONSTRUCT_COMPACT(v.OUTPUT_ROUTE),"

    al_cte = ""
    al_join = ""
    al_select = "'NOT_YET_IMPLEMENTED' AS AL,"
    al_route_for_all_routes = ""
    if include_al:
        al_cte = """
    al_ranked AS (
      SELECT PATIENT_ID, RULE_ID, PRIORITY, OUTPUT_ROUTE,
             ROW_NUMBER() OVER (PARTITION BY PATIENT_ID ORDER BY PRIORITY ASC) AS RN
      FROM ATTR_V3_COMBINATION_HITS
      WHERE PHENOTYPE = 'AL'
    ),
    al_pick AS (
      SELECT PATIENT_ID, RULE_ID, PRIORITY, OUTPUT_ROUTE FROM al_ranked WHERE RN = 1
    ),"""
        al_join = "LEFT JOIN al_pick ON b.PATIENT_ID = al_pick.PATIENT_ID"
        al_select = """CASE
             WHEN al_pick.RULE_ID IS NULL THEN 'INSUFFICIENT'
             ELSE 'PRIORITY_' || al_pick.PRIORITY
           END AS AL,
           al_pick.RULE_ID AS AL_RULE_ID,
           al_pick.OUTPUT_ROUTE AS AL_ROUTE,"""
        al_route_for_all_routes = "ARRAY_CONSTRUCT_COMPACT(al_pick.OUTPUT_ROUTE),"

    aa_cte = ""
    aa_join = ""
    aa_select = "'NOT_YET_IMPLEMENTED' AS AA,"
    aa_route_for_all_routes = ""
    if include_aa:
        aa_cte = """
    aa_ranked AS (
      SELECT PATIENT_ID, RULE_ID, PRIORITY, OUTPUT_ROUTE,
             ROW_NUMBER() OVER (PARTITION BY PATIENT_ID ORDER BY PRIORITY ASC) AS RN
      FROM ATTR_V3_COMBINATION_HITS
      WHERE PHENOTYPE = 'AA'
    ),
    aa_pick AS (
      SELECT PATIENT_ID, RULE_ID, PRIORITY, OUTPUT_ROUTE FROM aa_ranked WHERE RN = 1
    ),"""
        aa_join = "LEFT JOIN aa_pick ON b.PATIENT_ID = aa_pick.PATIENT_ID"
        aa_select = """CASE
             WHEN aa_pick.RULE_ID IS NULL THEN 'INSUFFICIENT'
             ELSE 'PRIORITY_' || aa_pick.PRIORITY
           END AS AA,
           aa_pick.RULE_ID AS AA_RULE_ID,
           aa_pick.OUTPUT_ROUTE AS AA_ROUTE,"""
        aa_route_for_all_routes = "ARRAY_CONSTRUCT_COMPACT(aa_pick.OUTPUT_ROUTE),"

    sql = f"""
    CREATE OR REPLACE TEMPORARY TABLE {table} AS
    WITH base AS (
      SELECT PATIENT_ID FROM ATTR_WIDE_NET_CANDIDATES
    ),
    ga AS (
      SELECT DISTINCT PATIENT_ID, TRUE AS PASS FROM ATTR_V3_COMBINATION_HITS WHERE PHENOTYPE = 'GENERAL_AMYLOID'
    ),
    ac AS (
      SELECT DISTINCT PATIENT_ID, TRUE AS PASS FROM ATTR_V3_COMBINATION_HITS WHERE PHENOTYPE = 'ATTR_COMMON'
    ),
    wt_ranked AS (
      SELECT PATIENT_ID, RULE_ID, PRIORITY, OUTPUT_ROUTE,
             ROW_NUMBER() OVER (PARTITION BY PATIENT_ID ORDER BY PRIORITY ASC) AS RN
      FROM ATTR_V3_COMBINATION_HITS
      WHERE PHENOTYPE = 'ATTRwt'
    ),
    wt AS (
      SELECT PATIENT_ID, RULE_ID, PRIORITY, OUTPUT_ROUTE FROM wt_ranked WHERE RN = 1
    ),{attrv_cte}{al_cte}{aa_cte}
    t01 AS (
      SELECT PATIENT_ID, SATISFIED, YEARS_BETWEEN, ORTHO_FIRST_SEEN, CARDIO_FIRST_SEEN
      FROM ATTR_V3_TEMPORAL_HITS WHERE TEMPORAL_RULE_ID = 'T01'
    ),
    gr AS (
      SELECT PATIENT_ID, LISTAGG(DISTINCT ROUTE_OR_GUARDRAIL, ',') WITHIN GROUP (ORDER BY ROUTE_OR_GUARDRAIL) AS GUARDRAIL_ROUTES
      FROM ATTR_V3_GUARDRAIL_HITS
      GROUP BY PATIENT_ID
    )
    SELECT b.PATIENT_ID,
           IFF(ga.PASS, 'PASS', 'FAIL') AS GENERAL_AMYLOID,
           IFF(ac.PASS, 'PASS', 'FAIL') AS ATTR_COMMON,
           CASE
             WHEN wt.RULE_ID IS NULL THEN 'INSUFFICIENT'
             ELSE 'PRIORITY_' || wt.PRIORITY
           END AS ATTRWT,
           wt.RULE_ID AS ATTRWT_RULE_ID,
           wt.OUTPUT_ROUTE AS ATTRWT_ROUTE,
           t01.SATISFIED AS T01_SATISFIED,
           t01.YEARS_BETWEEN AS T01_YEARS_BETWEEN,
           t01.ORTHO_FIRST_SEEN,
           t01.CARDIO_FIRST_SEEN,
           {attrv_select}
           {al_select}
           {aa_select}
           ARRAY_CAT(
             ARRAY_CONSTRUCT_COMPACT(wt.OUTPUT_ROUTE),
             {attrv_route_for_all_routes}
             {al_route_for_all_routes}
             {aa_route_for_all_routes}
             COALESCE(SPLIT(gr.GUARDRAIL_ROUTES, ','), ARRAY_CONSTRUCT())
           ) AS ALL_ROUTES,
           gr.GUARDRAIL_ROUTES
    FROM base b
    LEFT JOIN ga ON b.PATIENT_ID = ga.PATIENT_ID
    LEFT JOIN ac ON b.PATIENT_ID = ac.PATIENT_ID
    LEFT JOIN wt ON b.PATIENT_ID = wt.PATIENT_ID
    {attrv_join}
    {al_join}
    {aa_join}
    LEFT JOIN t01 ON b.PATIENT_ID = t01.PATIENT_ID
    LEFT JOIN gr ON b.PATIENT_ID = gr.PATIENT_ID
    WHERE ga.PASS OR ac.PASS OR wt.RULE_ID IS NOT NULL
      {"OR v.RULE_ID IS NOT NULL" if include_attrv else ""}
      {"OR al_pick.RULE_ID IS NOT NULL" if include_al else ""}
      {"OR aa_pick.RULE_ID IS NOT NULL" if include_aa else ""}
      OR gr.GUARDRAIL_ROUTES IS NOT NULL
    """
    _sql(session, sql)
    return table


def preview_composites(session, limit: int = 50):
    """Inspect WT04 (ORTHO_CLUSTER) hits: which patients fired the >=2-distinct-signal
    composite, how many of the 6 member signals contributed, and the earliest
    contributing date. See composites.create_ortho_cluster for the build."""
    return session.sql(
        f"""
        SELECT PATIENT_ID, COMPOSITE_RULE_ID, SOURCE_SIGN_ID, FIRED,
               CONTRIBUTING_COUNT, FIRST_SEEN_DATE
        FROM ATTR_V3_COMPOSITE_HITS
        ORDER BY FIRED DESC, CONTRIBUTING_COUNT DESC, FIRST_SEEN_DATE
        LIMIT {int(limit)}
        """
    ).to_pandas()


def preview_t01(session, limit: int = 20):
    return session.sql(
        f"""
        SELECT PATIENT_ID, SOURCE_SIGN_ID, PATTERN, SATISFIED, YEARS_BETWEEN,
               ORTHO_FIRST_SEEN, CARDIO_FIRST_SEEN
        FROM ATTR_V3_TEMPORAL_HITS
        WHERE TEMPORAL_RULE_ID = 'T01'
        ORDER BY SATISFIED DESC NULLS LAST, YEARS_BETWEEN DESC NULLS LAST
        LIMIT {int(limit)}
        """
    ).to_pandas()


def preview_combinations(session, limit: int = 50):
    return session.sql(
        f"""
        SELECT PATIENT_ID, PHENOTYPE, RULE_ID, PRIORITY, OUTPUT_ROUTE, CONTRIBUTING_BUCKETS
        FROM ATTR_V3_COMBINATION_HITS
        ORDER BY PHENOTYPE, PRIORITY, RULE_ID
        LIMIT {int(limit)}
        """
    ).to_pandas()


def preview_bucket_tiers(session, phenotype: str = "ATTRwt", limit: int = 50):
    return session.sql(
        f"""
        SELECT PATIENT_ID, PHENOTYPE, BUCKET, BEST_TIER, GATE_ELIGIBLE, FIRST_SEEN_DATE
        FROM ATTR_V3_BUCKET_TIER
        WHERE PHENOTYPE = '{_esc(phenotype)}'
        ORDER BY PATIENT_ID, BUCKET
        LIMIT {int(limit)}
        """
    ).to_pandas()


def preview_router(session, limit: int = 50):
    """ATTRV/AL/AA columns always shown (present in every mode - either a real
    PRIORITY_X/INSUFFICIENT value, or the literal 'NOT_YET_IMPLEMENTED' when
    the plain WT01-only pipeline was run). ATTRV_RULE_ID/ATTRV_ROUTE,
    AL_RULE_ID/AL_ROUTE, and AA_RULE_ID/AA_ROUTE are NOT selected here since
    those columns only exist in ATTR_V3_ROUTER_OUTPUT when run_full_pipeline
    built the table with include_attrv=True / include_al=True / include_aa=True
    - use preview_router_attrv / preview_router_al / preview_router_aa for
    those after running that pipeline."""
    return session.sql(
        f"""
        SELECT PATIENT_ID, GENERAL_AMYLOID, ATTR_COMMON, ATTRWT, ATTRWT_RULE_ID, ATTRWT_ROUTE,
               ATTRV, AL, AA,
               T01_SATISFIED, T01_YEARS_BETWEEN, ORTHO_FIRST_SEEN, CARDIO_FIRST_SEEN,
               ALL_ROUTES, GUARDRAIL_ROUTES
        FROM ATTR_V3_ROUTER_OUTPUT
        ORDER BY ATTRWT, T01_YEARS_BETWEEN DESC NULLS LAST
        LIMIT {int(limit)}
        """
    ).to_pandas()


def preview_router_attrv(session, limit: int = 50):
    """Same as preview_router but with ATTRV_RULE_ID/ATTRV_ROUTE too - only
    valid after run_full_pipeline (include_attrv=True); those columns
    don't exist in ATTR_V3_ROUTER_OUTPUT when the plain ATTRwt-only pipeline was
    the last one run."""
    return session.sql(
        f"""
        SELECT PATIENT_ID, GENERAL_AMYLOID, ATTR_COMMON,
               ATTRWT, ATTRWT_RULE_ID, ATTRWT_ROUTE,
               ATTRV, ATTRV_RULE_ID, ATTRV_ROUTE,
               T01_SATISFIED, T01_YEARS_BETWEEN, ORTHO_FIRST_SEEN, CARDIO_FIRST_SEEN,
               ALL_ROUTES, GUARDRAIL_ROUTES
        FROM ATTR_V3_ROUTER_OUTPUT
        ORDER BY ATTRV, ATTRWT
        LIMIT {int(limit)}
        """
    ).to_pandas()


def preview_router_al(session, limit: int = 50):
    """Same as preview_router but with AL_RULE_ID/AL_ROUTE too - only valid
    after run_full_pipeline built the table with include_al=True;
    those columns don't exist otherwise."""
    return session.sql(
        f"""
        SELECT PATIENT_ID, GENERAL_AMYLOID, ATTR_COMMON,
               ATTRWT, ATTRWT_RULE_ID, ATTRWT_ROUTE,
               ATTRV, AL, AL_RULE_ID, AL_ROUTE,
               T01_SATISFIED, T01_YEARS_BETWEEN, ORTHO_FIRST_SEEN, CARDIO_FIRST_SEEN,
               ALL_ROUTES, GUARDRAIL_ROUTES
        FROM ATTR_V3_ROUTER_OUTPUT
        ORDER BY AL, ATTRWT
        LIMIT {int(limit)}
        """
    ).to_pandas()


def preview_router_aa(session, limit: int = 50):
    """Same as preview_router but with AA_RULE_ID/AA_ROUTE too - only valid
    after run_full_pipeline built the table with include_aa=True; those
    columns don't exist otherwise."""
    return session.sql(
        f"""
        SELECT PATIENT_ID, GENERAL_AMYLOID, ATTR_COMMON,
               ATTRWT, ATTRWT_RULE_ID, ATTRWT_ROUTE,
               ATTRV, AL, AA, AA_RULE_ID, AA_ROUTE,
               T01_SATISFIED, T01_YEARS_BETWEEN, ORTHO_FIRST_SEEN, CARDIO_FIRST_SEEN,
               ALL_ROUTES, GUARDRAIL_ROUTES
        FROM ATTR_V3_ROUTER_OUTPUT
        ORDER BY AA, ATTRWT
        LIMIT {int(limit)}
        """
    ).to_pandas()

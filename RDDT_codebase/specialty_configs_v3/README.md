# specialty_configs_v3 — ATTR architecture (WT01 first)

Self-contained. **Does not depend on** `RDDT_ATTR_Snowflake.ipynb`.

## WT01 end-to-end

`RDDT_ATTR_V3_Pipeline.ipynb` runs **signal WT01** end-to-end:

| Layer | Object | Meaning |
|---|---|---|
| Sources | `SOURCE_CONFIG` | Your CENSUS / CLAIM / LAB / histories / notes |
| Atoms | `ATTR_V3_ATOMS` | Codes + keyword wildcards from `atoms/*.json` |
| Composite | WT04 `ORTHO_CLUSTER` | ≥2 distinct ortho signals → ORTHO Tier 1 |
| Tiers | `ATTR_V3_BUCKET_TIER` | ATTRwt / GA / ATTR_COMMON ORTHO+CARDIO |
| Temporal | **T01 = WT01** | `ORTHO_BEFORE_CARDIO` (not a bucket) |
| Combinations | GA01 → AC01 → WT_RULE_01/02 | Funnel into ATTRwt |
| Guardrails | WT24 / WT25 / WT26 | Parallel routes (e.g. MGUS → AL_SAFETY) |
| Router | `ATTR_V3_ROUTER_OUTPUT` | Final phenotype row |

## How to run

1. Upload / mount this folder in Snowflake (or put it on `sys.path`).
2. Open `RDDT_ATTR_V3_Pipeline.ipynb`.
3. Run all cells — `run_full_attrwt_pipeline` builds every TEMP table in order.
4. Inspect section 4–5 for T01 / WT_RULE_01 hits.

Or in Python:

```python
import pipeline as wt01
result = wt01.run_full_attrwt_pipeline(session, wt01.default_source_config())
wt01.preview_router(session)
```

ATTRv (V32/V33/V38/V41 guardrails, `V_RULE_01-07`, the `NEURO_PLUS_SYSTEMIC`
composite) runs alongside WT01/ATTRwt via a separate entry point that does not
change the plain WT01-only output above:

```python
import pipeline as wt01
result = wt01.run_full_pipeline(session, wt01.default_source_config())
wt01.preview_router_attrv(session)
```

## Files

| Path | Role |
|---|---|
| `atoms/` … `guardrails/` | v3 JSON (Excel-backed) |
| `rddt_attr_sql.py` | QC / wide net / `ATTR_EVID_*` |
| `common.py` | shared config loaders + low-level SQL helpers |
| `atoms.py` | evidence streams, atom matching, atom-id extraction (WT01 + ATTRv) |
| `composites.py` | composite rules (WT04 `ORTHO_CLUSTER`, V03 `NEURO_PLUS_SYSTEMIC`) |
| `buckets.py` | bucket-tier computation (`ATTR_V3_BUCKET_TIER`) |
| `temporal.py` | temporal rules (T01) |
| `combinations.py` | generic combination-rule engine (GA/AC/ATTRwt/ATTRv) |
| `guardrails.py` | guardrails (WT24-26, V32/33/38/41) |
| `router.py` | final router output + `preview_*` helpers |
| `pipeline.py` | orchestrator (`run_attrwt_pipeline`, `run_full_pipeline`) |
| `RDDT_ATTR_V3_Pipeline.ipynb` | Start here |

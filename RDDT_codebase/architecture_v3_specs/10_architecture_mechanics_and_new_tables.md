# How the Design Actually Works — Layers, Firing, Tiers, Buckets, Rules, Funnel, New Tables

This is the mechanics document. Six layers, six new Snowflake tables, one continuous worked
example touching every one of them. No old-system comparison, no gap audit — just how it runs.

## The six layers, one sentence each

| # | Layer | One-sentence job | New table it produces |
|---|---|---|---|
| 1 | Atoms | Does this specific finding exist in the chart, and when? | `ATTR_V3_ATOMS` |
| 2 | Composite rules | Does a *pattern across several atoms* exist (a count, or a specific combo)? | `ATTR_V3_COMPOSITE_HITS` |
| 3 | Phenotype overlays + bucket-tier rollup | Given everything that fired, what's the *strongest tier* each reasoning bucket reaches, for *this* phenotype? | `ATTR_V3_BUCKET_TIER` |
| 4 | Temporal rules | Did the buckets involved happen in the required *order*, using the dates already on the atoms? | `ATTR_V3_TEMPORAL_HITS` |
| 5 | Combination rules | Do the bucket tiers (and temporal result) satisfy *this phenotype's* specific pattern? **This is the only layer that produces a decision.** | `ATTR_V3_COMBINATION_HITS` |
| 6 | Guardrails | Does this specific finding mean "also check a different phenotype," independent of whether a decision fired? | `ATTR_V3_GUARDRAIL_HITS` |

Everything downstream of layer 1 only ever reads the table the layer before it produced. No layer
reaches back into raw EHR columns except layer 1.

## Layer 1 — Atoms — `ATTR_V3_ATOMS`

One row per patient. One pair of columns per atom: a 0/1 flag, and the earliest date it was true.

| Column | Type | Meaning |
|---|---|---|
| `PATIENT_ID` | VARCHAR | From `CENSUS.Member/PatientId` |
| `<ATOM_ID>` | NUMBER(1) | 1 if any code/keyword rule for this atom matched anywhere in `ATTR_EVID_*` |
| `<ATOM_ID>_FIRST_SEEN` | DATE | Earliest date among the rows that made it fire |

**How a value gets in here:** for `cts_bilateral`, the generator looks at `atoms/ortho.json`,
pulls its `icd10`/`snomed` codes and its `keywords` list, and writes something structurally
identical to what `v1/rddt_specialty_config.py`'s `ATTR_CODES` already does by hand — except
generated from JSON instead of typed in Python:

```sql
MAX(IFF(<code or keyword match>, 1, 0))              AS CTS_BILATERAL,
MIN(IFF(<code or keyword match>, EVENT_DATE, NULL))  AS CTS_BILATERAL_FIRST_SEEN
```

**Fires how:** one row per patient, computed once, reused by every phenotype below it. An atom
does not know which phenotype is asking — it only knows "did this specific thing happen, and when."

## Layer 2 — Composite rules — `ATTR_V3_COMPOSITE_HITS`

Composite rules don't touch raw EHR data — they only read `ATTR_V3_ATOMS`. Two shapes exist,
matching the `any`/`count_atoms_gate` operators your own `v2/loader.py` already validates:

| Column | Meaning |
|---|---|
| `PATIENT_ID` | — |
| `COMPOSITE_RULE_ID` | e.g. `ORTHO_CLUSTER`, `NEURO_PLUS_SYSTEMIC` |
| `FIRED` | true/false |
| `CONTRIBUTING_ATOM_COUNT` | how many sibling atoms were true |
| `CONTRIBUTING_ATOMS` | array of atom IDs, for the evidence trail |

**Worked rule (`WT04` → `ORTHO_CLUSTER`):**

```sql
IFF(
  (CTS_BILATERAL + CTS_RECURRENT + LUMBAR_STENOSIS + BICEPS_RUPTURE
   + ARTHROPLASTY + TRIGGER_FINGER + ROTATOR_CUFF + SHOULDER_DISORDER) >= 2,
  1, 0
) AS ORTHO_CLUSTER_FIRED
```

This is `count_atoms_gate` from your existing `sql_generator.py` `compile_logic()`, unchanged —
just pointed at `ATTR_V3_ATOMS` columns instead of `ATTR_V2_ATOMS` columns.

## Layer 3 — Phenotype overlays + bucket-tier rollup — `ATTR_V3_BUCKET_TIER`

**This is where "tier" and "bucket" actually mean something.** One row per
`(patient, phenotype, bucket)` — not per atom, not per patient alone.

| Column | Meaning |
|---|---|
| `PATIENT_ID` | — |
| `PHENOTYPE` | `GENERAL_AMYLOID`, `ATTR_COMMON`, `ATTRwt`, `ATTRv`, `AL`, or `AA` |
| `BUCKET` | `ORTHO`, `CARDIO`, `NEURO`, `AUTONOMIC`, `RENAL`, `HEME_CLONAL`, `INFLAMMATORY_DRIVER`, `INFLAMMATORY_ACTIVITY`, `OCULAR`, `HEREDITARY`, `MUCOSAL_CUTANEOUS`, `GI_HEPATIC`, `SYSTEMIC_CONTEXT` |
| `BEST_TIER` | 1–4, the *lowest-numbered* (strongest) tier among every atom/composite that reached this bucket for this phenotype |
| `GATE_ELIGIBLE` | true only if `BEST_TIER` is 1 or 2 **and** the winning atom's overlay for this phenotype has `gate_eligible = true` |
| `FIRST_SEEN_DATE` | earliest date among whatever produced `BEST_TIER` |
| `CONTRIBUTING_ATOMS` | which atom(s)/composite(s) produced it |

**How "tier" works, precisely:** the phenotype-overlay data (documented in `02_phenotype_overlays.md`,
e.g. `WT04` → `ATTRwt` Tier 1, `WT04` → `GENERAL_AMYLOID` Tier 2) is a lookup table baked into the
SQL generator, not a runtime decision. For one `(patient, phenotype, bucket)` row, the generator
writes:

```sql
LEAST(
  IFF(CTS_BILATERAL = 1, 1, 99),           -- WT02, Tier 1 for ATTRwt
  IFF(ORTHO_CLUSTER_FIRED = 1, 1, 99),     -- WT04 composite, Tier 1 for ATTRwt
  IFF(LUMBAR_STENOSIS = 1, 2, 99),         -- WT05, Tier 2 for ATTRwt
  IFF(ARTHROPLASTY = 1, 3, 99),            -- WT06, Tier 3 for ATTRwt (not gate-eligible)
  ...
) AS ORTHO_BEST_TIER_ATTRWT
```

`LEAST()` is the entire mechanism — best tier wins, nothing is added, a Tier-3 hit sitting
alongside a Tier-1 hit changes nothing. **This is why the same atom can produce different tiers in
different rows:** the *same* `CTS_BILATERAL` atom feeds a `LEAST()` expression under `ATTRwt`
(where it's Tier 1) and a *different* `LEAST()` expression under `GENERAL_AMYLOID` (where it's
Tier 2) — two separate rows in this table, same patient, same atom, different phenotype column set.

**How "bucket" works, precisely:** a bucket is just the *grouping key* for one `LEAST()`
expression. `ORTHO` groups `{cts_bilateral, cts_recurrent, lumbar_stenosis, biceps_rupture,
arthroplasty, trigger_finger, rotator_cuff, shoulder_disorder, orthopedic-cluster-composite}`
because those are the atoms whose `reasoning_bucket` field says `ORTHO` — a static lookup, not
computed at runtime. The two documented exceptions (`gi_dysmotility`, `gastroparesis_early_satiety`)
just mean their bucket lookup has an `IF phenotype = 'AL' THEN GI_HEPATIC ELSE AUTONOMIC` branch
instead of one fixed value.

## Layer 4 — Temporal rules — `ATTR_V3_TEMPORAL_HITS`

Reads only `ATTR_V3_BUCKET_TIER`'s date columns — never touches raw EHR data again.

| Column | Meaning |
|---|---|
| `PATIENT_ID` | — |
| `TEMPORAL_RULE_ID` | e.g. `T01` (`ORTHO_BEFORE_CARDIO`) |
| `SATISFIED` | true / false / null (null = couldn't evaluate, dates missing) |
| `YEARS_BETWEEN` | stored for ranking/explanation, never gates anything by itself |

```sql
CASE
  WHEN ortho.FIRST_SEEN_DATE IS NULL OR cardio.FIRST_SEEN_DATE IS NULL THEN NULL
  WHEN ortho.FIRST_SEEN_DATE < cardio.FIRST_SEEN_DATE THEN TRUE
  ELSE FALSE
END AS T01_SATISFIED
```

## Layer 5 — Combination rules — `ATTR_V3_COMBINATION_HITS` — **the only decision layer**

One row per `(patient, phenotype, rule_id)` that actually fired.

| Column | Meaning |
|---|---|
| `PATIENT_ID` | — |
| `PHENOTYPE` | which of the six |
| `RULE_ID` | `WT_RULE_01`, `V_RULE_05`, `AL_RULE_07`, `AA_RULE_01`, `GA01`, `AC03`, ... |
| `PRIORITY` | `A`, `B`, `C`, or the special labels (`Possible AL`, `Carrier conversion`) |
| `OUTPUT_ROUTE` | `ATTRWT_REVIEW`, `AL_MONOCLONAL_SCREEN`, `ATTRV_CARRIER_REVIEW`, ... |
| `CONTRIBUTING_BUCKETS` | e.g. `['ORTHO', 'CARDIO']` |
| `CONTRIBUTING_ATOMS` | flattened from `ATTR_V3_BUCKET_TIER`, the actual sign IDs |

Every rule from `03_combinations.md` compiles to one `WHERE` clause against
`ATTR_V3_BUCKET_TIER` (pivoted so each bucket is a column), using the exact same `any`/`all`
operators your `sql_generator.py` `compile_logic()` already implements:

```sql
-- WT_RULE_01
WHERE ortho.BEST_TIER <= 2 AND ortho.GATE_ELIGIBLE
  AND cardio.BEST_TIER <= 2 AND cardio.GATE_ELIGIBLE
  AND (SELECT SATISFIED FROM ATTR_V3_TEMPORAL_HITS WHERE TEMPORAL_RULE_ID = 'T01' AND PATIENT_ID = ortho.PATIENT_ID) = TRUE

-- AL_RULE_07 (count_buckets_gate, no HEME_CLONAL required)
WHERE (IFF(cardio.GATE_ELIGIBLE,1,0) + IFF(renal.GATE_ELIGIBLE,1,0)
     + IFF(neuro.GATE_ELIGIBLE,1,0) + IFF(mucosal.GATE_ELIGIBLE,1,0)) >= 3
```

### This is also where the funnel lives — as literal WHERE filters between phenotypes

```sql
-- Stage A: everyone
CREATE TABLE ATTR_V3_COMBINATION_HITS AS
SELECT *, 'GENERAL_AMYLOID' AS PHENOTYPE FROM (...GA01/GA02 logic against ATTR_V3_BUCKET_TIER...)

-- Stage B: ATTR_COMMON, AL, AA — each filtered to GENERAL_AMYLOID passers, computed in parallel
INSERT INTO ATTR_V3_COMBINATION_HITS
SELECT *, 'ATTR_COMMON' FROM (...AC01-08 logic...)
WHERE PATIENT_ID IN (SELECT PATIENT_ID FROM ATTR_V3_COMBINATION_HITS WHERE PHENOTYPE='GENERAL_AMYLOID');

INSERT INTO ATTR_V3_COMBINATION_HITS
SELECT *, 'AL' FROM (...AL_RULE_01-07 logic...)
WHERE PATIENT_ID IN (SELECT PATIENT_ID FROM ATTR_V3_COMBINATION_HITS WHERE PHENOTYPE='GENERAL_AMYLOID');
-- AA identical pattern

-- Stage C: ATTRwt, ATTRv — filtered to ATTR_COMMON passers
INSERT INTO ATTR_V3_COMBINATION_HITS
SELECT *, 'ATTRwt' FROM (...WT_RULE_01/02 logic...)
WHERE PATIENT_ID IN (SELECT PATIENT_ID FROM ATTR_V3_COMBINATION_HITS WHERE PHENOTYPE='ATTR_COMMON');

-- Exception: V_RULE_07 (carrier route) filters off GENERAL_AMYLOID directly, not ATTR_COMMON
INSERT INTO ATTR_V3_COMBINATION_HITS
SELECT *, 'ATTRv' FROM (...V_RULE_07 logic, gated on known-carrier flag...)
WHERE PATIENT_ID IN (SELECT PATIENT_ID FROM ATTR_V3_COMBINATION_HITS WHERE PHENOTYPE='GENERAL_AMYLOID');
```

This nesting is provably safe (never drops a true positive) because every `ATTR_COMMON`,
`ATTRwt`, and `ATTRv` (except `V_RULE_07`) bucket pair is a subset of a `GA01`/`GA02`-qualifying
pair — that's a property of how the bucket lists were designed, not an assumption. `AL` and `AA`
are siblings of `ATTR_COMMON` under `GENERAL_AMYLOID`, never nested under it — an `AL`-shaped
patient with zero ortho/cardio/neuro findings would be wrongly dropped if `AL` were filtered
through `ATTR_COMMON` first.

## Layer 6 — Guardrails — `ATTR_V3_GUARDRAIL_HITS`

Reads `ATTR_V3_ATOMS` directly (guardrails mostly key off one atom or composite, not a bucket
pair), runs independently of Layer 5, and never gates or subtracts anything.

| Column | Meaning |
|---|---|
| `PATIENT_ID` | — |
| `SOURCE_PHENOTYPE` | which phenotype's sign this guardrail came from |
| `ROUTE` | `AL_SAFETY`, `ROUTE_TO_ATTRv`, `NO_EXCLUSION_FEMALE_WALL_THICKNESS`, ... |
| `TRIGGERING_ATOM` | e.g. `mgus` |

```sql
SELECT PATIENT_ID, 'ATTRwt' AS SOURCE_PHENOTYPE, 'AL_SAFETY' AS ROUTE, 'mgus' AS TRIGGERING_ATOM
FROM ATTR_V3_ATOMS WHERE MGUS = 1
```

## Final assembly — `ATTR_V3_ROUTER_OUTPUT`

One row per patient. Pivots `ATTR_V3_COMBINATION_HITS` (best priority per phenotype) and unions in
every `ATTR_V3_GUARDRAIL_HITS` row as an extra tag.

| Column | Meaning |
|---|---|
| `PATIENT_ID` | — |
| `GENERAL_AMYLOID_STATUS` | PASS / FAIL |
| `ATTR_COMMON_STATUS` | PASS / FAIL / N/A |
| `ATTRWT_STATUS` | best priority found, or `INSUFFICIENT` |
| `ATTRV_STATUS` | best priority found, or `INSUFFICIENT` |
| `AL_STATUS` | best priority found, or `INSUFFICIENT` |
| `AA_STATUS` | best priority found, or `INSUFFICIENT` |
| `PRIMARY_ROUTE` | single highest-ranked route (lexicographic key from `00_overview.md`) |
| `ALL_ROUTES` | array — every route + every guardrail tag, nothing dropped |
| `EVIDENCE_TRAIL` | array of sign IDs, traced back through every layer |

## One patient, through all seven tables

**Chart:** bilateral CTS (2015), distal biceps rupture (2016), hip arthroplasty (2017),
unexplained HFpEF (2023), known MGUS (2020).

| Table | Row(s) produced |
|---|---|
| `ATTR_V3_ATOMS` | `CTS_BILATERAL=1 (2015)`, `BICEPS_RUPTURE=1 (2016)`, `ARTHROPLASTY=1 (2017)`, `HFPEF=1 (2023)`, `MGUS=1 (2020)` |
| `ATTR_V3_COMPOSITE_HITS` | `ORTHO_CLUSTER_FIRED = true` (3 ortho atoms ≥ threshold 2) |
| `ATTR_V3_BUCKET_TIER` | `(ATTRwt, ORTHO, BEST_TIER=1, first_seen=2015)`; `(ATTRwt, CARDIO, BEST_TIER=2, first_seen=2023)`; `(ATTRwt, HEME_CLONAL, ...)` — not applicable, MGUS isn't an ATTRwt bucket, it's a guardrail atom |
| `ATTR_V3_TEMPORAL_HITS` | `T01: SATISFIED=true, YEARS_BETWEEN=8` |
| `ATTR_V3_COMBINATION_HITS` | `GENERAL_AMYLOID/GA01 fired`; `ATTR_COMMON/AC01 fired`; `ATTRwt/WT_RULE_01 fired, PRIORITY=A` |
| `ATTR_V3_GUARDRAIL_HITS` | `SOURCE_PHENOTYPE=ATTRwt, ROUTE=AL_SAFETY, TRIGGERING_ATOM=mgus` |
| `ATTR_V3_ROUTER_OUTPUT` | `ATTRWT_STATUS=PRIORITY_A`, `ALL_ROUTES=['ATTRWT_REVIEW','AL_SAFETY']`, `PRIMARY_ROUTE=ATTRWT_REVIEW`, `EVIDENCE_TRAIL=[WT02,WT03,WT06,WT09,WT25]` |

That last row is the entire point: one patient, one pass through six mechanical layers, ends as a
single readable record — ATTRwt Priority A, with a parallel AL-safety flag, and a full trail back
to the six original sign IDs that produced it.

## Review checklist for this file

- [ ] Confirm the `LEAST()`-per-bucket mechanism and the funnel-as-WHERE-filter mechanism match
      what you pictured when you asked "how does tier/bucket/rule work."
- [ ] Confirm `ATTR_V3_ROUTER_OUTPUT`'s column shape is the right final artifact, or if you want a
      long/tall table (one row per patient-phenotype) instead of this wide one.
- [ ] Flag anything in the seven-table list that doesn't match how you pictured the pipeline.

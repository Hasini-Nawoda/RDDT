# Step 6 — End-to-End Execution Pipeline

Maps the six-phenotype architecture onto the pipeline you already have running
(`rddt_attr_sql.py` + `specialty_configs/v2/sql_generator.py`). Every stage below either reuses an
existing table unchanged, or is a direct, same-shape descendant of one.

Depends on: all five prior spec files. This is where they become one flow.

## The five stages

```
Stage 1  QC                 unchanged — rddt_attr_sql.py Step 1
Stage 2  WIDE NET            unchanged in spirit — ATTR_WIDE_NET_CANDIDATES
Stage 3  EVIDENCE             unchanged — ATTR_EVID_* (already has dates)
Stage 4  ATOMS + BUCKETS      new atom catalog (01) → bucket-tier facts, WITH dates now used
Stage 5  PHENOTYPE DECISIONS  six independent rule engines (03) + guardrails (04) + temporal (05)
Stage 6  ROUTER OUTPUT        one row per patient, all six phenotype verdicts + routes
```

Stages 1–3 do not change structurally. Stage 4 changes what an "atom" carries. Stage 5 is the
genuinely new part — six decision engines instead of one shortlist gate.

## Stage 1 — QC (unchanged)

`validate_sources()` / `table_qc()` in `rddt_attr_sql.py`. No changes for v3.

## Stage 2 — Wide net (same purpose, refreshed pattern list)

`code_net_patient_ids()`, `text_net_patient_ids()`, `snomed_net_patient_ids()` →
`create_candidates()` → `ATTR_WIDE_NET_CANDIDATES`.

**Purpose stays identical:** a deliberately loose, high-recall filter. A patient becomes a
candidate if *any* code/keyword/SNOMED pattern loosely related to *any* of the 88 atoms across
all six phenotypes matches anywhere in their record. This is not a phenotype decision — it is
"is this patient worth the cost of full evidence extraction at all."

**What changes:** the pattern list itself is now sourced from the full corrected atom catalog in
`01_atoms_layer.md` (all 88 atoms across all 12 organ/etiology buckets) instead of the old
ortho/cardio/neuro-only atom set. Wider net, same mechanism.

## Stage 3 — Evidence (unchanged)

`build_evidence()` → `ATTR_EVID_PATIENT`, `ATTR_EVID_ENCOUNTER`, `ATTR_EVID_CLAIM`,
`ATTR_EVID_LAB_RESULT`, `ATTR_EVID_MEDICAL_HISTORY`, `ATTR_EVID_SURGICAL_HISTORY`,
`ATTR_EVID_FAMILY_HISTORY`, `ATTR_EVID_CLINICAL_NOTES` — scoped to wide-net candidates only, via
`_candidate_join`.

No changes needed. Every one of these tables already carries a date column
(`FROM_DATE`/`TO_DATE` on claims, `EVENT_DATE` on history, `OBSERVATION_DATETIME` on labs,
`NOTE_DATE` on notes) — Stage 4 just needs to stop discarding them.

## Stage 4 — Atoms and bucket-tier facts (the layer that changes shape)

Two sub-steps, mirroring `sql_generator.py`'s existing `_create_code_atoms` /
`_create_keyword_atoms` / `_create_snomed_atoms` / `_create_atoms_merged`, with one addition.

### 4a. Atom hits (per patient) — same mechanism as today, plus first-seen date

```
ATTR_V3_ATOMS
  PATIENT_ID
  <atom_id>            0/1   (code OR keyword OR SNOMED matched)
  <atom_id>_first_seen  MIN(date) across whichever evidence row matched      ← new
```

Every `<atom_id>` comes straight from `01_atoms_layer.md`'s 88-atom catalog — same three
detection paths v2 already has (`_claim_row_code_pred`, `_keyword_pred`, `_snomed_row_pred`),
same `MAX(IFF(...))` pattern for the flag. The only addition is a parallel
`MIN(IFF(<pred>, <date_col>, NULL))` for the first-occurrence date, using the date columns already
sitting in the Stage 3 evidence tables. No new evidence source needed — confirmed against
`rddt_attr_sql.py` above.

### 4b. Bucket-tier facts (per patient, per phenotype) — new step, not in v2 at all

```
ATTR_V3_BUCKET_TIER
  PATIENT_ID
  PHENOTYPE            e.g. 'ATTRwt', 'ATTRv', 'AL', 'AA', 'GENERAL_AMYLOID', 'ATTR_COMMON'
  BUCKET                e.g. 'ORTHO', 'CARDIO', 'NEURO', 'AUTONOMIC', ...
  BEST_TIER              1-4, the best (lowest-numbered) tier among atoms that fired in this
                         bucket, for this phenotype's overlay (from 02_phenotype_overlays.md)
  GATE_ELIGIBLE          true only if BEST_TIER is 1 or 2 AND at least one contributing atom's
                         overlay for this phenotype has gate_eligible = true
  FIRST_SEEN_DATE        MIN(first_seen) across the atoms that produced BEST_TIER
  CONTRIBUTING_ATOMS      array of atom_ids that fired in this bucket at BEST_TIER or better —
                         this is what lets the final output show WHICH sign IDs triggered it
```

This is the layer v2 does not have. It is the direct implementation of "best tier per bucket,
never summed" and it is computed **once per (patient, phenotype, bucket)** — this is also where
the two `bucket_override` exception atoms (`gi_dysmotility`, `gastroparesis_early_satiety`) get
resolved: same atom, different `BUCKET` value depending on which `PHENOTYPE` row is being computed.

`CONTRIBUTING_ATOMS` is the field that answers your traceability question from the atoms review —
every downstream phenotype decision can point back to the exact sign IDs that caused it.

## Stage 5 — Phenotype decisions (six independent engines, not one shared gate)

This is where `compile_logic()` from `sql_generator.py` gets reused almost unchanged — a `PAIR`
rule is just `all` over two bucket-tier booleans instead of two atom booleans; `COUNT_DISTINCT_BUCKETS`
is `count_buckets_gate` over `ATTR_V3_BUCKET_TIER` rows instead of over raw atom flags.

```
ATTR_V3_PHENOTYPE_HITS
  PATIENT_ID
  PHENOTYPE
  RULE_ID              e.g. 'WT_RULE_01', 'V_RULE_02', 'AL_RULE_07', 'AA_RULE_01'
  PRIORITY              'A' / 'B' / 'C' / etc, per 03_combinations.md
  TEMPORAL_SATISFIED     true / false / null (null = temporal not required for this rule)
  OUTPUT_ROUTE           'ATTRWT_REVIEW', 'ATTRV_CARRIER_REVIEW', 'AL_MONOCLONAL_SCREEN', ...
  CONTRIBUTING_BUCKETS   e.g. ['ORTHO', 'CARDIO']
  CONTRIBUTING_ATOMS     flattened from the bucket-tier rows above — the actual sign IDs
```

Run once per phenotype, independently, against `ATTR_V3_BUCKET_TIER` filtered to that phenotype's
rows. A patient can appear here multiple times for the same phenotype (different rules) and across
different phenotypes simultaneously (`ATTRwt` **and** `AL`) — there is no "pick one" step anywhere
in this stage. This directly implements the parallel-route requirement from `00_overview.md`.

Temporal rules (`05_temporal_rules.md`) plug in here as a filter/upgrade on `TEMPORAL_SATISFIED`,
comparing `FIRST_SEEN_DATE` between two bucket-tier rows for the same patient (e.g. `T01`: ORTHO's
`FIRST_SEEN_DATE` < CARDIO's `FIRST_SEEN_DATE`).

Guardrails (`04_guardrails.md`) run as their own pass over `ATTR_V3_ATOMS` (they mostly reference
individual atoms or composite patterns, not bucket gates) and write to:

```
ATTR_V3_GUARDRAIL_HITS
  PATIENT_ID
  SOURCE_PHENOTYPE
  ROUTE                 e.g. 'AL_SAFETY', 'ROUTE_TO_ATTRv', 'NO_EXCLUSION_FEMALE_WALL_THICKNESS'
  TRIGGERING_ATOM_OR_RULE
```

Guardrail hits never gate `ATTR_V3_PHENOTYPE_HITS` and are never subtracted from it — they are
unioned onto the final output as extra rows/tags.

## Stage 6 — Router output (one row per patient)

Final assembly, per the router diagram in `00_overview.md`:

```
ATTR_V3_ROUTER_OUTPUT
  PATIENT_ID
  GENERAL_AMYLOID_STATUS     PASS / FAIL
  ATTR_COMMON_STATUS         PASS / FAIL / N/A (N/A if GENERAL_AMYLOID failed)
  ATTRWT_STATUS               PRIORITY_A / PRIORITY_B / INSUFFICIENT
  ATTRV_STATUS                 PRIORITY_A / ... / CARRIER_REVIEW / INSUFFICIENT
  AL_STATUS                     SAFETY_PASS / MONOCLONAL_SCREEN / INSUFFICIENT
  AA_STATUS                     PRIORITY_A / PRIORITY_B / INSUFFICIENT
  PRIMARY_ROUTE                 the single highest-ranked route, by the lexicographic key
                               in 00_overview.md (never a weighted sum)
  ALL_ROUTES                    every route this patient qualifies for, including guardrail
                               ROUTE_TO_* tags, so nothing gets silently dropped
  EVIDENCE_TRAIL                 the CONTRIBUTING_ATOMS chain from Stage 5, for clinician review
```

`ATTR_UNSPECIFIED_REVIEW` (the "ATTR-shaped but wt/v not yet decided" case from `00_overview.md`)
is simply the row where `ATTR_COMMON_STATUS = PASS` but both `ATTRWT_STATUS` and `ATTRV_STATUS`
are `INSUFFICIENT` — no separate mechanism needed, it falls out of the table naturally.

## How we decide a patient — the direct answer

There isn't one gate. There are **three separate decisions**, at three different stages, and
mixing them up is the single easiest way to get this wrong:

1. **Stage 2 (wide net): "is this patient worth pulling into the pipeline at all?"** Loosest
   possible filter — any atom-related pattern anywhere. This is a cost-control filter, not a
   clinical decision. Nobody is "positive" for anything yet.

2. **Stage 4 (bucket-tier facts): "what does this patient's evidence look like, organized?"**
   This is not a decision either — it's pure fact derivation. No pass/fail happens here. A patient
   can have `ORTHO: Tier 1` and that alone means nothing until Stage 5 asks a specific question of
   it.

3. **Stage 5 (phenotype decisions): "does this patient's bucket-tier profile satisfy *this
   phenotype's* specific combination rule?"** This is the only stage where a real decision is
   made — and it's made **six separate times**, once per phenotype, each against its own rule set
   from `03_combinations.md`. This is the fundamental difference from your current v2 pipeline,
   where `shortlist_config.json` makes exactly *one* decision ("≥2 of ortho/cardio/neuro") for the
   whole system. v3 has no single shared gate — `ATTRwt` asks "ORTHO+CARDIO?", `ATTRv` asks any of
   seven different questions, `AL` asks a different six, `AA` asks two, completely independently,
   over the *same* underlying bucket-tier facts from Stage 4.

A patient is never globally "in" or "out." They are independently evaluated against six yes/no
(or graded-priority) questions, and the router in Stage 6 just reports all six answers plus which
one should be acted on first. That's the mechanism behind "a patient can be ATTRwt PRIORITY A and
AL SAFETY PASS at the same time" — there's no shared resource (like a single score or a single
gate) for those two verdicts to compete over.

## Review checklist for this file

- [ ] Confirm the three-decision framing above matches your mental model, or point out where it
      still doesn't.
- [ ] Confirm Stage 2's wide net should stay a single shared filter across all six phenotypes
      (cheapest, matches today's design) rather than six separate wide nets.
- [ ] Confirm `ATTR_V3_BUCKET_TIER` being computed per-phenotype (not once globally) is
      acceptable given it's needed for the two bucket-override atoms — this does mean Stage 4b
      runs up to 6x per patient instead of once, which is a real (but small) cost increase over v2.
- [ ] Confirm the Stage 6 output shape (one wide row per patient with all six statuses) is what
      you want to consume downstream, vs. a long/tall table of one row per `(patient, phenotype)`.

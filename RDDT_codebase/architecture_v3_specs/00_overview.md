# Amyloidosis Multi-Phenotype Router — Architecture Overview

Step 0 of 5. Read this first; each later file assumes these rules.

## Purpose

Convert the four pre-test phenotype tables (`Amiliodosis(Attrwt).csv`, `Amiliodosis(Attrv).csv`,
`Amiliodosis(AL).csv`, `Amiliodosis(AA).csv` — 133 rows total) into an implementation-ready,
**non-additive** reasoning config. No numeric disease scores. No `score - counter_evidence`
subtraction. Tiers and bucket combinations only.

This workbook already exists and is the verified source of truth for everything in these spec
files: `Amyloidosis_MultiPhenotype_Bucket_Config.xlsx`. These `.md` files restate its content as a
step-by-step, human-checkable build plan, and — for the atoms layer specifically — correct defects
found in the first build attempt (`Atoms creation/atoms/*.json`).

## The six phenotype configs

```
GENERAL_AMYLOID   — "is this chart worth an amyloidosis work-up at all?"
ATTR_COMMON       — "is this an ATTR-shaped patient, wt-or-v not yet decided?"
ATTRWT            — wild-type transthyretin amyloidosis
ATTRV             — hereditary/variant transthyretin amyloidosis
AL                — light-chain amyloidosis
AA                — inflammatory (serum amyloid A) amyloidosis
```

`ATTR_COMMON` exists so a clearly ATTR-shaped patient (e.g. CTS + cardiomyopathy + neuropathy) is
never lost just because the chart doesn't yet contain enough evidence to split wt vs v. Router
output in that case is `ATTR_COMMON: PASS`, `ATTRwt: insufficient subtype pattern`,
`ATTRv: insufficient subtype pattern` → route `ATTR_UNSPECIFIED_REVIEW`.

A patient can pass more than one phenotype at once — e.g. `ATTRwt = PRIORITY A` **and**
`AL = SAFETY PASS` simultaneously. Phenotypes are not mutually exclusive and never compete on a
single scalar.

## The five-folder architecture

```
specialty_configs/v3/
├── atoms/                  Step 1 — What happened in the EHR? (source of truth: atom_index.csv +
│                            atoms/*.json, corrected per 01_atoms_layer.md)
├── phenotype_overlays/     Step 2 — How important is that atom, for this specific phenotype?
├── combinations/           Step 3 — What collection of independent buckets makes a screening
│                            phenotype, for this specific phenotype?
├── temporal_rules/         Step 4 — Is the longitudinal order/persistence correct?
└── guardrails/             Step 5 — Does this evidence require a different or parallel funnel?
```

Each layer answers exactly one question. Do not let a later layer duplicate what an earlier layer
already decided (e.g. combinations never re-derive tiers; guardrails never subtract from a score
because there is no score to subtract from).

## The two concepts that must never collapse into one

| Concept | Meaning | Lives on |
|---|---|---|
| `source_specialty` | Where the evidence is actually documented clinically (Gastroenterology, Urology, Cardiology, Nephrology...) | the atom |
| `reasoning_bucket` | Which independent disease axis the combination engine counts it toward (ORTHO, CARDIO, NEURO, AUTONOMIC, RENAL, HEME_CLONAL, INFLAMMATORY_DRIVER, INFLAMMATORY_ACTIVITY, OCULAR, HEREDITARY, MUCOSAL_CUTANEOUS, GI_HEPATIC, SYSTEMIC_CONTEXT, TEMPORAL_COMPOSITE) | the atom |

Example: alternating diarrhea/constipation → `source_specialty = GASTROENTEROLOGY`,
`reasoning_bucket = AUTONOMIC` (in ATTRv it is autonomic-neuropathy evidence, not a second,
independent GI finding).

`source_specialty` is a fixed property of the atom — it never varies by phenotype, because it
describes a fact about the health system, not a disease theory.

`reasoning_bucket` has a **default value carried on the atom**, used by every phenotype unless a
phenotype overlay explicitly overrides it. An override is rare and only justified when the same
clinical finding plays a genuinely different mechanistic role in different diseases. The workbook
has exactly two such cases, both GI-dysmotility findings: in ATTRv the same finding is read as
`AUTONOMIC` evidence (neuropathy causing gut dysmotility); in AL the same finding is read as
`GI_HEPATIC` evidence (direct organ infiltration, no autonomic mechanism implied). See
`01_atoms_layer.md` and `02_phenotype_overlays.md` for exactly which atoms this applies to — it is
the exception, not the rule, and every other atom's bucket is identical across every phenotype
that uses it.

**Tier** always varies by phenotype and belongs only in `phenotype_overlays/`.

Counting the same underlying evidence in two different buckets (e.g. once as GI, once as
AUTONOMIC) is the single most dangerous failure mode in this design: it lets one biological
process manufacture a two-bucket combination on its own. See `01_atoms_layer.md` for the concrete
cases where the first build got this wrong and how they're fixed.

## Non-additive scoring — the hard rule

- Best tier is taken **within** a bucket. Multiple Tier-1 atoms in the same bucket do not raise
  that bucket above Tier 1.
- Tiers are **never summed** across buckets, and never turned into a 0–100 score.
- A phenotype "passes" only when an approved bucket **combination** (Combination Rules, step 3)
  is satisfied at the required tier level — not from a tally.
- Counter-evidence (guardrail rows) is **never** Tier 4 positive evidence and is **never**
  subtracted from anything. It emits a parallel `ROUTE_TO_X` signal alongside whatever the patient
  already passed.

## Router flow

```
Patient evidence
      │
      ▼
GENERAL_AMYLOID
      │
      ├── fail → no amyloid shortlist
      └── pass
           │
           ├─────────────────────────────┐
           ▼                             ▼
       ATTR_COMMON                    AL rules
           │                             │
      ┌────┴─────┐                       │
      ▼          ▼                       │
   ATTRwt      ATTRv                     │
      │          │                       │
      └────┬─────┘                       │
           └───────────────┬─────────────┘
                            ▼
                           AA
                            │
                            ▼
                        ROUTER OUTPUT
```

Guardrail rows fire independently of this pipeline and can attach a `ROUTE_TO_*` tag to the output
at any point without blocking or discounting a pass elsewhere.

## Ranking — also non-additive

When more than one route/priority is available, rank lexicographically, in this order, never by
weighted sum:

1. Route priority (e.g. `ATTRWT_REVIEW` before `ATTR_UNSPECIFIED_REVIEW`)
2. Canonical combination present? (yes beats no)
3. Temporal relationship present and confirmed? (yes beats unknown beats contradicted)
4. Number of gate-eligible independent buckets satisfied
5. Number of Tier-1 buckets among those
6. Number of Tier-2 buckets among those
7. First-signal-to-recognition lead time (longer, well-documented prodrome ranks higher)

Three buckets with two Tier-1s outranks two buckets with one Tier-1 — as a lexicographic
comparison, never as `3*5 + 2*3 = 21`.

## Build order for these spec files

| File | Covers | Status |
|---|---|---|
| `00_overview.md` | This file | Done |
| `01_atoms_layer.md` | Atom schema + corrections to the existing `Atoms creation/` build | Next |
| `02_phenotype_overlays.md` | Per-phenotype tier/role overlay schema | Pending |
| `03_combinations.md` | Full combination rule set, all 6 phenotypes | Pending |
| `04_guardrails.md` | Full guardrail/route rule set | Pending |
| `05_temporal_rules.md` | Temporal + composite (multi-atom, non-bucket-creating) rules | Pending |

Review each file in order. Nothing gets built into JSON until you approve the file it corresponds
to.

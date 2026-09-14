# GENERAL_AMYLOID — 2 rules

Question this phenotype answers: **"Regardless of which subtype, is there a real cross-system
amyloidosis pattern here at all?"** This is the front door — nothing reaches ATTRwt/ATTRv/AL/AA
evaluation unless it passes through here first, per the router diagram in `00_overview.md`.

## GA01 — Two independent organ buckets

**Plain question:** Does this patient have Tier 1–2 evidence in **any two different** organ
buckets, from the eight allowed?

**Requires:** `COUNT_DISTINCT_BUCKETS`, threshold 2, from the allowed set:
`CARDIO, RENAL, NEURO, AUTONOMIC, ORTHO, OCULAR, MUCOSAL_CUTANEOUS, GI_HEPATIC`

**Contributing sign IDs per bucket** (Tier 1–2, gate-eligible, GENERAL_AMYLOID overlay):

| Bucket | Sign IDs |
|---|---|
| CARDIO | `AL14:T1, WT13:T1, AL15:T1, WT15:T1, WT09:T1, V24:T1, WT10:T1, WT12:T1, AL20:T2, AL33:T2, AL16:T2, AL17:T2, WT16:T2, WT14:T2, WT11:T2, V23:T2, V25:T2` |
| RENAL | `AL03:T1, AL04:T1, AA17:T1, AA16:T1, AL06:T2, AL05:T2, AA18:T2, AA15:T2, V17:T2, AA19:T2, AA20:T2` |
| NEURO | `V04:T1, V02:T1, V21:T2, AL24:T2, V14:T2, V18:T2` |
| AUTONOMIC | `V05:T1, V11:T2, V19:T2, V09:T2, V10:T2` |
| ORTHO | `WT05:T2, V13:T2, WT03:T2, WT04:T2, WT02:T2` |
| OCULAR | `V15:T2` |
| MUCOSAL_CUTANEOUS | `AL08:T2, AL07:T2` |
| GI_HEPATIC | *(none reach Tier 1–2 gate-eligible for GENERAL_AMYLOID — see edge case below)* |

**Priority:** A. There's only one priority level for this rule — it either fires or it doesn't.

**Temporal:** None required.

**Output route:** `GENERAL_AMYLOID_REVIEW`

**Worked example:** A patient has `WT10` (unexplained LV wall thickening, CARDIO Tier 1) and
`AA16` (new persistent proteinuria, RENAL Tier 1). Two different buckets, both Tier 1 → `GA01`
fires. This patient now proceeds to `ATTR_COMMON`, `AL`, and `AA` evaluation — `GA01` itself makes
no claim about which subtype.

**Edge cases / tiny details:**
- Notice ORTHO is capped at Tier 2 here even for `WT02`/`WT03`/`WT04`, which are Tier 1 under
  ATTRwt. This is intentional and matches the workbook: an orthopedic finding alone is a weaker
  *general* amyloid signal than it is a *specific ATTRwt* signal — orthopedic disease is common and
  needs the ATTRwt-specific temporal/pairing logic to mean much on its own.
- `GI_HEPATIC` has no Tier 1–2 gate-eligible atom for GENERAL_AMYLOID in the current workbook —
  every AL/AA GI finding sits at Tier 3 or lower for this phenotype. That means, right now, no
  patient can satisfy `GA01` using GI_HEPATIC as one of their two buckets. Not a bug — just means
  GI findings alone are considered too nonspecific to help decide "is this amyloidosis at all,"
  only useful once a specific subtype is already suspected.
- Two Tier-1 hits in the *same* bucket (e.g. both `WT10` and `WT13`, both CARDIO) still only count
  as **one** bucket. `GA01` needs two *different* buckets, not two findings.

## GA02 — One organ bucket plus one etiologic-context bucket

**Plain question:** Does this patient have one organ finding (Tier 1–2) **plus** a plausible
underlying cause (Tier 1–2) — even if the organ evidence alone wasn't enough for `GA01`?

**Requires:** `ORG_PLUS_ETIOLOGY` — 1 organ/phenotype bucket Tier 1–2 (same eight buckets as
`GA01`) **+** 1 etiologic-context bucket Tier 1–2 from: `HEME_CLONAL, INFLAMMATORY_DRIVER, HEREDITARY`

**Contributing sign IDs for the etiology side:**

| Bucket | Sign IDs |
|---|---|
| HEME_CLONAL | `AL01:T2` |
| INFLAMMATORY_DRIVER | `AA07:T2, AA09:T2, AA08:T2, AA02:T2, AA06:T2` |
| HEREDITARY | `V01:T2, V08:T2, V07:T2` |

**Priority:** A/B — A when the organ side is Tier 1, B when it's Tier 2. (This distinction isn't
separately spelled out in the workbook as two rule IDs; treat organ-side Tier 1 as the stronger
outcome when ranking multiple `GA02` matches.)

**Temporal:** None required.

**Output route:** `GENERAL_AMYLOID_REVIEW`

**Worked example:** A patient has `AA02` (known FMF, INFLAMMATORY_DRIVER Tier 2) and `AA16` (new
proteinuria, RENAL Tier 1). RENAL alone wouldn't be a second *organ* bucket for `GA01` (there's
only one organ finding here), but `GA02` explicitly allows one organ + one cause → fires.

**Edge cases / tiny details:**
- The etiology bucket **can never pass alone**. A patient with only `AA02` (FMF) and nothing else
  does not pass `GA02` — a genetic/clonal/inflammatory background is context, not proof of organ
  involvement. This is the same principle used throughout: `ETIOLOGIC_CONTEXT`-role atoms are
  always paired, never standalone.
- If a patient has *both* two organ buckets (satisfying `GA01`) *and* an etiology bucket, they
  still just get one `GENERAL_AMYLOID_REVIEW` route — passing via two different rules doesn't
  create two records or a "double pass." `GA01` and `GA02` are two doors into the same room.

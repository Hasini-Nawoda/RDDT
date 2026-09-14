# Composite Rules — The Missing Layer Between Atoms and Phenotype Overlays

7 of the 133 source signs are not atoms and are not combination rules. They are **composite
rules**: a derived fact computed from *several* atoms (or bucket outcomes) before the
phenotype-overlay tier lookup ever runs. This file gives them the dedicated home they didn't have.

## Why this layer has to exist separately

| | Atom | Composite rule | Combination rule |
|---|---|---|---|
| Input | Raw EHR (codes/keywords) | Two or more atoms, or two bucket outcomes | Bucket **tiers** (already rolled up) |
| Output | A fact: true/false + date | A derived fact: true/false (+ contributing evidence) | A phenotype decision: priority + route |
| Has an `atom_id`? | Yes | **No** | No |
| Belongs to one bucket? | Yes, fixed | Sometimes (Shape A) — sometimes spans buckets (Shape B/C) | No — consumes multiple buckets by definition |

WT04 has no `atom_id` anywhere in `ortho.json`, and it never will — it isn't a thing you detect in
a chart, it's a pattern you compute across things you've already detected. `01_atoms_layer.md`
line 71 flagged this as a gap and said "add it as an atom," which was the wrong fix — that
instruction is superseded by this file.

## The 7 composite rules (confirmed against the Signal Catalog `Config_Object_Type` column, not the narrative text)

| Sign ID | Phenotype | Rule ID | Config_Object_Type | Definition | Effect | Double-counting guardrail |
|---|---|---|---|---|---|---|
| WT04 | ATTRwt | `ORTHO_CLUSTER` | `DERIVED_BUCKET_FEATURE` | ≥2 of: bilateral/recurrent CTS, LSS/decompression, biceps rupture, arthroplasty, trigger finger, shoulder disease, across different tissues/procedures | Derive ORTHO Tier 1 | Counts once as ORTHO; never as multiple specialties |
| V03 | ATTRv | `RULE_V03` (`NEURO_PLUS_SYSTEMIC`) | `COMPOSITE_RULE` | Idiopathic axonal PN + ≥2 of: family history, bilateral/recurrent CTS, dysautonomia, GI disease, cardiac disease, ocular signs, renal abnormalities | Upgrade ATTRv review priority | Do not add a synthetic extra bucket on top of the component buckets |
| V06 | ATTRv | `RULE_V06` (`NEURO_CARDIO_MIXED`) | `COMPOSITE_RULE` | Neurologic/autonomic phenotype + cardiac phenotype together | Upgrade mixed ATTRv combination | Equivalent to a combination rule, not a new independent bucket |
| AA21 | AA | `RULE_AA21` (`RENAL_DISPROPORTIONATE`) | `COMPOSITE_RULE` | Renal phenotype disproportionate to / not fully explained by known diabetes, hypertension, medications, or other kidney disease, in a persistent-inflammation context | May elevate RENAL to Tier 1 | Still counts once as RENAL |
| AL21 | AL | `RULE_AL21` (`MULTISYSTEM_ACCUMULATION`) | `COMPOSITE_RULE` | Evidence across ≥3 distinct organ-system buckets | Route to `AL_MONOCLONAL_SCREEN`; raise review priority | Do not count MULTISYSTEM as a fourth bucket |
| AL26 | AL | `RULE_AL26` (`CLONAL_PLUS_NEW_ORGAN`) | `COMPOSITE_RULE` | Known monoclonal/plasma-cell precursor state + new unexplained organ dysfunction | Direct AL safety escalation | Underlying HEME + ORGAN buckets are the actual counted evidence |
| AL27 | AL | `RULE_AL27` (`PREEXISTING_MONOCLONAL_PLUS_ORGAN`) | `COMPOSITE_RULE` | Pre-existing abnormal monoclonal studies from unrelated follow-up + new organ signal | Direct AL safety escalation | Only pre-test if monoclonal tests predated amyloid suspicion |

That's the complete set — nothing else in the 133 carries `DERIVED_BUCKET_FEATURE` or
`COMPOSITE_RULE`. (AA21 reads as "within-bucket" in its own description, but the catalog itself
tags it `COMPOSITE_RULE`, not `DERIVED_BUCKET_FEATURE` — verified directly against row 74 of the
Signal Catalog sheet, not assumed from the narrative text.)

## Three different shapes hiding under one label

Reading the "Definition" column closely, these 7 rules aren't one mechanism — they're three:

**Shape A — within-bucket count** (`WT04` only). N sibling atoms all live in the same bucket
(ORTHO); the rule fires on a minimum count among them. Output feeds directly into that bucket's
tier as if it were one more atom.

**Shape B — count-among-an-open-set across buckets** (`V03`, `AL21`). One anchor atom/bucket must
be true, *plus* a minimum count from a list of several other buckets (not one fixed second
bucket). This is different from a combination rule, which always names exactly two fixed buckets —
V03 and AL21 don't know in advance *which* second (or third) bucket will supply the evidence.

**Shape C — fixed cross-bucket pair that bypasses the normal tier pipeline** (`V06`, `AA21`,
`AL26`, `AL27`). These look like a combination rule (two named buckets), but instead of producing
a tier that later feeds a combination rule, they **directly** produce an upgrade or an escalation
route (`AL_SAFETY_REVIEW`). AL26/AL27 exist as their own rule instead of just being absorbed into
`AL_RULE_02`-style combination logic specifically because they must fire as an *immediate safety
escalation* — clonal-plus-organ evidence can't wait for the standard bucket-tier rollup before
triggering an urgent AL work-up.

## Where this sits in the pipeline (updates `10_architecture_mechanics_and_new_tables.md` Layer 2)

Composite rules read `ATTR_V3_ATOMS` (for Shape A/B, which need atom-level counts) or an
early pass of `ATTR_V3_BUCKET_TIER` (for Shape C, which needs bucket-level outcomes) — never raw
EHR data directly. Their own output table:

**`ATTR_V3_COMPOSITE_HITS`**

| Column | Meaning |
|---|---|
| `PATIENT_ID` | — |
| `COMPOSITE_RULE_ID` | `ORTHO_CLUSTER`, `NEURO_PLUS_SYSTEMIC`, `NEURO_CARDIO_MIXED`, `RENAL_DISPROPORTIONATE`, `MULTISYSTEM_ACCUMULATION`, `CLONAL_PLUS_NEW_ORGAN`, `PREEXISTING_MONOCLONAL_PLUS_ORGAN` |
| `SHAPE` | `WITHIN_BUCKET_COUNT` / `CROSS_BUCKET_COUNT` / `CROSS_BUCKET_PAIR_ESCALATION` |
| `FIRED` | true/false |
| `CONTRIBUTING_COUNT` | how many atoms (Shape A) or buckets (Shape B) were true |
| `CONTRIBUTING_ATOMS_OR_BUCKETS` | array, for the evidence trail |
| `DIRECT_EFFECT` | `FEEDS_BUCKET_TIER` (A/B) or `DIRECT_ESCALATION:<route>` (C) |

Worked SQL for each shape, using the exact thresholds from the table above (nothing invented):

```sql
-- Shape A: WT04
IFF((CTS_BILATERAL + CTS_RECURRENT + LUMBAR_STENOSIS + BICEPS_RUPTURE
   + ARTHROPLASTY + TRIGGER_FINGER + ROTATOR_CUFF + SHOULDER_DISORDER) >= 2, 1, 0)
  AS ORTHO_CLUSTER_FIRED   -- feeds the ORTHO LEAST() in ATTR_V3_BUCKET_TIER, same as an atom would

-- Shape B: AL21 ("evidence across >=3 distinct organ-system buckets")
IFF((IFF(renal.BEST_TIER<=2,1,0) + IFF(cardio.BEST_TIER<=2,1,0) + IFF(neuro.BEST_TIER<=2,1,0)
   + IFF(gi_hepatic.BEST_TIER<=2,1,0) + IFF(autonomic.BEST_TIER<=2,1,0)) >= 3, 1, 0)
  AS MULTISYSTEM_ACCUMULATION_FIRED   -- reads ATTR_V3_BUCKET_TIER, writes AL_MONOCLONAL_SCREEN route

-- Shape C: AL26 (direct escalation, bypasses normal combination-rule ranking)
IFF(heme_clonal.BEST_TIER<=2 AND
    (renal.BEST_TIER<=2 OR cardio.BEST_TIER<=2 OR neuro.BEST_TIER<=2 OR gi_hepatic.BEST_TIER<=2),
    1, 0) AS CLONAL_PLUS_NEW_ORGAN_FIRED   -- writes directly to AL_SAFETY_REVIEW, independent of AL_RULE_01-07
```

## Current build status

Nothing here is implemented. `atoms/*.json` has no representation for any of these 7 rules (WT04's
gap was previously misclassified as "missing atom content" rather than "missing composite-rule
layer"). No `ATTR_V3_COMPOSITE_HITS` table, no SQL for any of the three shapes, exists yet. This
file is the design only — same status as `03_combinations.md`, `04_guardrails.md`,
`05_temporal_rules.md` before any code gets written.

## Review checklist

- [ ] Confirm the three-shape split (within-bucket count / cross-bucket count-among-a-set /
      cross-bucket pair-escalation) matches how you want these to behave — in particular, whether
      AL26/AL27 should really *bypass* the standard AL combination rules (`AL_RULE_01`–`07`) rather
      than just being one more input into them.
- [ ] Confirm V06 (`NEURO_CARDIO_MIXED`) genuinely needs to exist as a composite rule at all, given
      it's functionally identical in shape to `AC04`/`V_RULE_04` (NEURO + CARDIO pair) in
      `03_combinations.md` — possible duplication worth resolving before this gets built.
- [ ] Confirm `ATTR_V3_COMPOSITE_HITS`'s column shape, or flag a different structure you'd prefer.

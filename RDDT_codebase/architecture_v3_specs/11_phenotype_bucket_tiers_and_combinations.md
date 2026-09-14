# Phenotype-Specific Bucket Tiers and Combination Logic

This file is the authoritative content for the `phenotype_overlays/` and `combinations/` layers,
per-phenotype, as specified directly. It **replaces** the looser "any pair from an approved list"
framing in `03_combinations.md` with explicit whitelists and per-bucket tier tables. Where this
narrows or conflicts with what's already in `02_phenotype_overlays.md` / `03_combinations.md`,
the conflict is called out at the end — not silently overridden.

Core rule restated: **no scores, no arithmetic.** Every phenotype box is a bucket-tier lookup
(`LEAST()` per bucket, same as `10_architecture_mechanics_and_new_tables.md`) feeding an explicit
combination whitelist. Reasoning buckets, not source specialties, are what combination rules count
— `alternating diarrhea/constipation` is `source_specialty: GASTROENTEROLOGY` but
`reasoning_bucket: AUTONOMIC`, so it can never manufacture an ATTRv NEURO+GI pair out of one
autonomic process.

---

## GENERAL_AMYLOID

**Question answered:** regardless of subtype, does this chart contain a cross-system amyloidosis pattern?

| Bucket | T1 | T2 | T3 | T4 |
|---|---|---|---|---|
| CARDIO | Unexplained LV thickening/restrictive phenotype; apical-sparing imaging phenotype; incidental cardiac tracer uptake | Unexplained HFpEF; conduction disease/pacemaker; voltage-mass discordance; persistent/disproportionate cardiac biomarkers | AF with other clues; AS with other clues | Isolated dyspnea/effusion |
| RENAL | Unexplained nephrotic-range proteinuria | New unexplained persistent proteinuria; proteinuria + falling eGFR | Microalbuminuria alone | — |
| NEURO | Unexplained progressive axonal neuropathy; strong small-fiber phenotype; refractory CIDP-type misdiagnosis | Autonomic neuropathy; progressive peripheral neuropathy | Nonspecific neuropathic pain | — |
| ORTHO | Multi-orthopedic ATTR-type cluster | Bilateral/recurrent CTS; biceps rupture; lumbar stenosis | Arthroplasty; trigger finger; rotator cuff | — |
| MUCOSAL_CUTANEOUS | Macroglossia; periorbital purpura | — | — | — |
| OCULAR | — | Characteristic vitreous phenotype | — | — |
| HEME_CLONAL / HEREDITARY / INFLAMMATORY_DRIVER | *(etiologic-context buckets — reuse each bucket's phenotype-specific T1/T2 definition from the AL/ATTRv/AA sections below; not redefined separately here)* | | | |

**Gate:**
```
T1/T2 in TWO independent organ buckets
   OR
ONE organ bucket T1/T2 + ONE etiologic-context bucket T1/T2 (HEME_CLONAL, HEREDITARY, or INFLAMMATORY_DRIVER)
```
An etiologic-context bucket alone never qualifies — it must pair with objective organ evidence.

---

## ATTR_COMMON

**Question answered:** is this an ATTR-shaped patient, even before wt/v can be resolved?

**Allowed pairs (whitelist, not `count(bucket) >= 2`):**

| Pair | Allowed? |
|---|---|
| ORTHO + CARDIO | YES |
| NEURO + AUTONOMIC | YES |
| NEURO + CARDIO | YES |
| NEURO + HEREDITARY | YES |
| CARDIO + HEREDITARY | YES |
| NEURO + OCULAR | YES |
| ORTHO + OCULAR | NO — falls back to `GENERAL_AMYLOID: possible` / `ATTR_COMMON: supportive`, not a pass |
| *(any pair not explicitly listed)* | NO |

This whitelist is **narrower** than the existing `AC01`–`AC08` rules in `03_combinations.md` — see
conflict note at the bottom.

**Fallback behavior (this is the reason `ATTR_COMMON` exists as its own phenotype):** a patient
with CTS + cardiomyopathy + neuropathy who doesn't yet have enough evidence to resolve wt vs v
still gets:
```
GENERAL_AMYLOID: PASS
ATTR_COMMON: PASS
ATTRwt: insufficient subtype pattern
ATTRv: insufficient subtype pattern
ROUTE → ATTR_UNSPECIFIED_REVIEW
```
Never dropped, never forced into a premature subtype.

---

## ATTRwt

| Bucket | T1 | T2 | T3 | T4 |
|---|---|---|---|---|
| ORTHO | WT02 bilateral/recurrent CTS; WT03 spontaneous distal biceps rupture; WT04 multiple orthopedic red flags (composite) | WT05 lumbar spinal stenosis/decompression | WT06 multiple/bilateral arthroplasty; WT07 multiple trigger fingers/releases | WT08 rotator-cuff/shoulder pathology |
| CARDIO | WT10 unexplained LV thickening/non-dilated LV; WT13 late unexplained HCM-like phenotype; WT20 incidental myocardial tracer uptake (non-amyloid indication) | WT09 unexplained HFpEF; WT11 AF + structural/orthopedic clues; WT12 conduction disease/pacemaker; WT14 AS + amyloid clues; WT15 apical sparing; WT16 voltage-mass discordance; WT18 unexpected BP fall/HF-drug intolerance | WT17 MCF-type supportive abnormality | WT19 experimental BNP/LV-mass comparator |
| NEURO | — (not gate-forming for ATTRwt) | — | WT21 hearing loss; WT22 mild sensory neuropathy | — |
| SYSTEMIC_CONTEXT | — | — | — | WT23 age+male sex (**never creates eligibility**) |

Important: apical sparing (WT15) is strong for `GENERAL_AMYLOID` cardiac suspicion but only T2 for
ATTRwt subtype discrimination — this is exactly why tiers are phenotype-specific, not atom-fixed.

**Guardrails (no tier, parallel route only):**

| Sign | Behavior |
|---|---|
| WT24 | `FALSE_NEGATIVE_GUARDRAIL` — female + <12mm wall thickness; not positive evidence |
| WT30 | `DO_NOT_USE_AS_SCREENING_FEATURE` |
| WT25 | → AL safety route |
| WT26 | → AL/renal interpretation guardrail |
| WT27 | → AL route |
| WT28 | → ATTRv route |
| WT29 | → AA route |

**WT01 is not a specialty tier — it's the canonical combination rule:**

```
RULE WT_CANONICAL_TEMPORAL
  ORTHO best_tier <= 2
  AND CARDIO best_tier <= 2
  AND ORTHO first_date < CARDIO first_date

ORTHO T1 + CARDIO T1 + correct sequence  → ATTRWT_PRIORITY_A
ORTHO T1 + CARDIO T2 + correct sequence  → ATTRWT_PRIORITY_B
ORTHO T2 + CARDIO T2 + correct sequence  → ATTRWT_PRIORITY_C
```
Zero point addition — rank `A > B > C` lexicographically. **ATTRwt requires ORTHO + CARDIO
specifically** — `ORTHO + NEURO` or `CARDIO + NEURO` may satisfy `ATTR_COMMON`, never ATTRwt alone
(this matches, not conflicts with, the existing `WT_RULE_01`/`WT_RULE_02` in `03_combinations.md`,
which are already ORTHO+CARDIO-only — no change needed there).

---

## ATTRv

| Bucket | T1 | T2 | T3 | T4 |
|---|---|---|---|---|
| NEURO | V02 progressive axonal sensorimotor PN; V04 painful small-fiber PN; V14 CIDP label + failed appropriate therapy | V18 rising NfL (where available); V21 compatible MR neurography; V28 unexplained bulbar phenotype | V20 CSP; V22 nerve ultrasound; V29 trophic foot changes; V37 diabetes-insufficient-to-explain-neuropathy context | very weak/specialized evidence only |
| AUTONOMIC | V05 early dysautonomia | V09 orthostasis; V10 GI dysmotility; V11 gastroparesis; V19 abnormal SUDOSCAN | V12 weight loss in autonomic phenotype; V26 ED; V27 neurogenic bladder; V31 falling BP/intolerance | weak isolated GI/systemic manifestations |
| HEREDITARY | V01 known pathogenic/likely-pathogenic TTR variant; V07 first-degree established ATTR family history | V08 unexplained familial progressive adult neuropathy | — | — |
| OCULAR | V15 characteristic vitreous involvement; V16 characteristic pupillary/iris phenotype | — | V35 nonspecific glaucoma/dry eye | — |
| CARDIO | — | V24 cardiomyopathy/HFpEF/LV thickening; V25 conduction disease/arrhythmia/pacemaker | V23 MIBG abnormality; V31 falling BP/intolerance | — |
| ORTHO | — | V13 bilateral/recurrent CTS | — | V30 lumbar stenosis alone (routes toward `ATTR_COMMON`, not ATTRv-specific) |

V03 (idiopathic axonal PN + ≥2 systemic red flags) is a **combination**, not a NEURO feature — see
`02b_composite_rules.md`. Don't count V10 (GI dysmotility) once as GI and again as AUTONOMIC — it
is AUTONOMIC only.

**Guardrails:** V32 → ATTRwt · V41 → ATTRwt · V39 → AL · V40 → AA · V33 → ATTRwt (isolated
orthopedic prodrome) · V38 → alternative inflammatory/demyelinating neuropathy · V36 → do not use
as trigger.

**Canonical combinations (no universal "2 of 3" rule — five explicit shapes):**

```
ATTRV_CANONICAL_1:  NEURO T1/T2 + AUTONOMIC T1/T2
ATTRV_CANONICAL_2:  NEURO T1/T2 + HEREDITARY T1/T2
ATTRV_CANONICAL_3:  NEURO T1/T2 + OCULAR T1/T2
ATTRV_CANONICAL_4:  NEURO T1/T2 + CARDIO T1/T2
ATTRV_CANONICAL_5:  HEREDITARY T1 + CARDIO T1/T2   (cardiac-predominant hereditary disease — neuropathy NOT mandatory)
```

---

## AL

| Bucket | T1 | T2 | T3 | T4 |
|---|---|---|---|---|
| HEME_CLONAL | AL01 known plasma-cell dyscrasia | AL02 MGUS under surveillance | — | — |
| RENAL | AL03 new/progressive persistent proteinuria; AL04 nephrotic proteinuria/nephrotic syndrome | AL05 hypoalbuminemia + edema/anasarca; AL06 declining renal function with proteinuric/clonal context | — | — |
| MUCOSAL_CUTANEOUS | AL07 macroglossia; AL08 periorbital/pinch purpura | — | — | — |
| CARDIO | — | AL14 unexplained HF/HFpEF; AL15 unexplained LV thickening/restrictive physiology; AL16 voltage-mass discordance/pseudoinfarction; AL17 disproportionate cardiac biomarkers | AL33 unexplained cardiomyopathy; AL28 unexplained serosal/pleural fluid | — |
| NEURO | — | AL24 symmetric sensorimotor neuropathy | AL13 autonomic dysfunction; AL29 hypotension/syncope in multisystem phenotype | — |
| GI_HEPATIC | — | — | AL10, AL11, AL18, AL09 | — |
| SYSTEMIC_CONTEXT | — | — | — | AL19 fatigue; AL20 dyspnea alone; AL34 nonspecific edema |

AL26/AL27 ("clonal state + organ involvement") move into the **combination engine**, not the tier
table — scoring them again as a bucket would double-count the same clonal+organ evidence already
counted by HEME_CLONAL and the organ bucket individually.

**Guardrails:** AL25 → AA · AL30 → ATTRwt · AL31 → ATTRv · AL22 → ATTRwt · AL23 → ATTRwt.

**Combinations:**

```
AL_HIGH_1:  HEME_CLONAL T1/T2 + RENAL T1/T2
AL_HIGH_2:  HEME_CLONAL T1/T2 + CARDIO T1/T2
AL_HIGH_3:  HEME_CLONAL T1/T2 + NEURO T1/T2
AL_HIGH_4:  MUCOSAL_CUTANEOUS T1 + any affected ORGAN T1/T2

AL_POSSIBLE (NOT "AL positive"):
  >= 3 independent organ buckets at T1/T2, no known clonal finding
  → routes to urgent monoclonal-screen funnel, never labeled AL
```

---

## AA

Three axes: INFLAMMATORY_DRIVER + INFLAMMATORY_ACTIVITY + RENAL.

| Bucket | T1 | T2 | T3 |
|---|---|---|---|
| INFLAMMATORY_DRIVER | AA02 FMF; AA06 other major autoinflammatory syndrome; AA08 significant chronic/active infection | AA01 chronic inflammatory arthritis; AA07 high-risk IBD phenotype; AA09 recurrent chronic infection/wounds; AA10 selected inflammatory neoplastic drivers | — |
| INFLAMMATORY_ACTIVITY | AA13 persistently high SAA (routinely followed) | AA05 inadequately controlled FMF; AA14 recurrent/uncontrolled inflammatory flares | AA12 repeated CRP/ESR elevation |
| RENAL | AA16 new/progressive persistent proteinuria; AA17 nephrotic-range proteinuria; AA21 disproportionate/unexplained renal phenotype (composite) | AA15 new low-grade albuminuria; AA20 declining eGFR | AA18 hypoalbuminemia from renal loss; AA19 edema/anasarca |
| SUSCEPTIBILITY (modifier only) | — | AA03 high-risk MEFV genotype; AA04 relevant family history — **never substitutes for driver or renal evidence** | — |

INFLAMMATORY_ACTIVITY never counts as a second independent disease system — it only strengthens
the driver's priority.

**Weak/context:** AA22 → GI T3 · AA23 → GI T4 · AA11 → T4 · AA24 → T4.
**Guardrails:** AA26 → alternate renal disease · AA27 → active sediment reduces specificity ·
AA28 → route to AL · AA29 → route to ATTR · AA30 → missing driver · AA25 → cardiac clue, investigate AL/ATTR instead.

**Combination — deliberately simple:**

```
AA_PASS:  INFLAMMATORY_DRIVER <= T2  AND  RENAL <= T2

PRIORITY A:  Driver T1 + Renal T1 + persistent inflammatory activity
PRIORITY B:  Driver T1 + Renal T1/T2
PRIORITY C:  Driver T2 + Renal T1/T2
```
FMF T1 + CRP T2 + SAA T1 with **no renal involvement** does not enter the AA shortlist — they're a
high-risk inflammatory patient, not yet an AA pre-test phenotype.

---

## Ranking — non-additive lexicographic key (applies across all phenotypes)

```
1. route priority
2. canonical combination present?
3. temporal relationship present?
4. number of gate-eligible independent buckets
5. number of T1 buckets
6. number of T2 buckets
7. first-signal-to-recognition lead time
```
3 buckets + 2 T1 outranks 2 buckets + 1 T1 by comparing this tuple top-to-bottom — never by
computing `3*5 + 2*3 = 21`.

---

## Final router shape

```
GENERAL_AMYLOID
   fail → no shortlist
   pass ─┬─────────────┬─────────────┐
         ▼             ▼             ▼
   ATTR_COMMON      AL rules       AA rules
         │
    ┌────┴────┐
    ▼         ▼
 ATTRwt     ATTRv
```
AL and AA read off `GENERAL_AMYLOID` in parallel with `ATTR_COMMON` — not nested under it. A
patient can legitimately emerge as `ATTR_COMMON: PASS, ATTRwt: PRIORITY_A` **and**
`AL: SAFETY_PASS` simultaneously — never `ATTRwt score − AL evidence`.

## Conflicts with existing files — flagged, not silently resolved

- **`03_combinations.md`'s `AC07` (ORTHO+NEURO) and `AC08` (AUTONOMIC+HEREDITARY)** are not in this
  file's `ATTR_COMMON` whitelist. Confirm whether those two should be dropped (this file wins) or
  whether the whitelist above should be widened to include them.
- **`02_phenotype_overlays.md`'s existing worked examples** (e.g. `ATOM_WT04` tier table) are
  consistent with this file's ATTRwt ORTHO table — no conflict there, just confirming the tables
  agree on WT04 = ATTRwt Tier 1.
- **GENERAL_AMYLOID's etiologic-context buckets** (HEME_CLONAL/HEREDITARY/INFLAMMATORY_DRIVER)
  reuse the phenotype-specific tier tables from AL/ATTRv/AA above rather than getting their own
  GENERAL-specific tier table — this is an assumption, not something explicitly stated; confirm.

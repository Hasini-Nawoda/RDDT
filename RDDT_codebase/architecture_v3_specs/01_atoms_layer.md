# Step 1 — Atoms Layer

Answers: **"What happened in the EHR?"** Nothing about disease, tier, or combination logic
belongs here.

## Schema (corrected)

```json
{
  "atom_id": "orthostatic_hypotension",
  "preferred_name": "Orthostatic hypotension / recurrent orthostatic intolerance",
  "source_specialty": "CARDIOLOGY_OR_NEUROLOGY_VITALS",
  "reasoning_bucket": "AUTONOMIC",
  "reasoning_bucket_overrides": {},
  "canonical_workbook_id": "AUTONOMIC_ORTHOSTASIS",
  "source_workbook_rows": ["V09", "AL13"],
  "stage": "PRETEST_SIGNAL",
  "experiencer_contract": "PATIENT",
  "family_tables_only": false,
  "extraction_executability": "NON_EXECUTABLE_MISSING_VOCABULARY",
  "extraction": {
    "codes": { "icd10": [], "icd9": [], "snomed": [], "cpt": [], "hcpcs": [], "loinc": [], "rxnorm": [] },
    "keywords": [],
    "structured_rules": []
  },
  "candidate_keywords": [],
  "candidate_structured_rules": [],
  "schema_version": "3.0"
}
```

Two changes from the schema currently in `Atoms creation/atoms/*.json`:

1. **`reasoning_bucket` is now an explicit field**, not something implied by which file the atom
   lives in. File/folder placement stays as an organizational convenience only. This is the single
   change that would have prevented every bucket-misplacement bug found in the first build — the
   bucket is asserted on the atom itself and can be checked by a linter regardless of which file it
   physically sits in.
2. **`reasoning_bucket_overrides`** is a small map, `{ "<phenotype>": "<bucket>" }`, empty for
   every atom except the two documented exceptions below. This replaces the incorrect assumption
   that bucket never varies by phenotype.

`source_specialty` must be the **true clinical origin** — where a clinician or coder would actually
find this in the chart — never a copy of the bucket name. `NEUROLOGY_AUTONOMIC` as a blanket value
for every atom in an "autonomic" bucket file is exactly the defect being corrected here.

## The two atoms where `reasoning_bucket` legitimately varies by phenotype

| `atom_id` | `canonical_workbook_id` | rows | default bucket | override |
|---|---|---|---|---|
| `gi_dysmotility` | `AUTONOMIC_GI_DYSMOTILITY` | V10, AL11 | `AUTONOMIC` (used for V10 / ATTRv) | `ATTRv → AUTONOMIC`, `AL → GI_HEPATIC` (AL11) |
| `gastroparesis_early_satiety` | `AUTONOMIC_GASTROPARESIS_EARLY_SATIETY` | V11, AL10 | `AUTONOMIC` (used for V11 / ATTRv) | `ATTRv → AUTONOMIC`, `AL → GI_HEPATIC` (AL10) |

Reasoning: in ATTRv the finding is autonomic-neuropathy evidence; in AL the same finding is direct
organ (GI) infiltration evidence with no autonomic mechanism implied. `source_specialty` is
`GASTROENTEROLOGY` either way — only the reasoning bucket differs. This is the **only** legitimate
exception found in the source workbook. Every other atom's bucket is identical across every
phenotype that references it — do not generalize this pattern beyond these two atoms without
new evidence review.

## Known defects in `Atoms creation/atoms/*.json` — fix list

These are verified against the bucket-config workbook (`Amyloidosis_MultiPhenotype_Bucket_Config.xlsx`,
Phenotype Overlays sheet), which is the source of truth.

### A. Missing atoms — highest severity

| Sign(s) | Canonical ID | Status | Fix |
|---|---|---|---|
| `WT02`, `V13` | `ORTHO_CTS_BILAT_RECURRENT` | Atoms exist (`cts_bilateral`, `cts_recurrent`, etc.) but every one has `source_workbook_rows: []` | Attach `WT02` and `V13` to one atom. This is bilateral/recurrent CTS — the single highest-priority ATTRwt discriminator and a Tier-2 ATTRv discriminator. Do not leave it unlinked. |
| `WT04` | `ATOM_WT04` | No atom anywhere | Add: "Multiple orthopedic red flags across different tissues/procedures" — Tier 1 ATTRwt composite-cluster feature. |
| `WT22` | `ATOM_WT22` | No atom anywhere | Add: "Mild-to-moderate length-dependent sensory polyneuropathy" — Tier 3 ATTRv/ATTRwt-compatibility feature. |

### B. Cross-bucket duplication (the double-counting failure mode) — highest severity

| Sign | Currently fires as | Problem | Fix |
|---|---|---|---|
| `V10` | `gi_dysmotility` in `autonomic.json` **and** `constipation`/`diarrhea` in `gi_hepatic.json` | Same evidence scores in two independent buckets simultaneously | One atom, `gi_dysmotility` (see table above). Bucket is `AUTONOMIC` for ATTRv's `V10`. Do not also emit `constipation`/`diarrhea` GI_HEPATIC atoms from this same sign. |
| `V11` | `gastroparesis` in `autonomic.json` **and** `delayed_gastric_emptying`/`early_satiety`/`nausea`/`vomiting` in `gi_hepatic.json` | Same as above | One atom, `gastroparesis_early_satiety`. Bucket `AUTONOMIC` for ATTRv's `V11`. |
| `AL10`, `AL11` | (same GI_HEPATIC atoms as above, correctly) | Not a bug for AL — GI_HEPATIC is the correct bucket here (see override table) | No change needed for these two rows specifically; just don't let `V10`/`V11` also feed them. |

### C. Mis-paired / fragmented atom (orthostatic hypotension) — high severity

| Problem | Detail |
|---|---|
| `AL13` fires in two different atoms | `dysautonomia` (`autonomic.json`, paired with `V05` — wrong) and `orthostatic` (`neuro.json`, paired with `V09` — right pairing, wrong file) |
| `V09` fires in two different atoms | `orthostatic_intolerance` (`autonomic.json`, alone) and `orthostatic` (`neuro.json`, with `AL13`) |
| `V05` should stand alone | Ground truth: `ATOM_V05` is its own canonical atom, never grouped with `AL13`. |

**Fix:** One atom, `orthostatic_hypotension`, canonical ID `AUTONOMIC_ORTHOSTASIS`,
`source_workbook_rows: ["V09", "AL13"]`, bucket `AUTONOMIC`. Delete `orthostatic_intolerance` and
the `dysautonomia`/`orthostatic` duplicate pairings. `V05` keeps its own separate atom
(`dysautonomia_general` or similar — do not reuse the bare name `dysautonomia` for both concepts).

### D. Bucket misplacement — atom correctly built, wrong bucket asserted

| Sign | Ground-truth bucket | Currently placed in | True `source_specialty` | Fix |
|---|---|---|---|---|
| `V23` (MIBG cardiac denervation) | `CARDIO` | `autonomic.json` | `NUCLEAR_CARDIOLOGY` | Move to cardio bucket. |
| `V31` (falling BP / med intolerance) | `AUTONOMIC` | `cardio.json` | `CARDIOLOGY` (documented there, but reasoned as autonomic evidence) | Move to autonomic bucket. Good example of `source_specialty ≠ reasoning_bucket`. |
| `V34` (GI weight loss labeled eating disorder) | `AUTONOMIC` | `shared.json` | `PSYCHIATRY_OR_GASTROENTEROLOGY` | Move to autonomic bucket. |
| `WT18` (BP fall / HF-med intolerance) | `SYSTEMIC_CONTEXT` | `cardio.json` | `CARDIOLOGY` | Move to systemic-context bucket. |
| `WT20` (incidental bone-scan uptake) | `SYSTEMIC_CONTEXT` | `cardio.json` | `NUCLEAR_MEDICINE` | Move to systemic-context bucket. |
| `V28` (bulbar symptoms) | `NEURO` | `gi_hepatic.json` | `NEUROLOGY` (ENT/speech involved in workup, not the reasoning axis) | Move to neuro bucket. |
| `AA03` (MEFV genotype) | `HEREDITARY` | `inflammatory.json` | `CLINICAL_GENETICS` | Move to hereditary bucket. |
| `AA04` (family history AA/ESRD) | `HEREDITARY` | `inflammatory.json` | `FAMILY_HISTORY` | Move to hereditary bucket. |
| `AL34` (nonspecific edema) | `SYSTEMIC_CONTEXT` | `renal.json` | `GENERAL_MEDICINE` | Move to systemic-context bucket. |
| `AL29` (hypotension/syncope/dizziness) | `CARDIO` | `shared.json` | `CARDIOLOGY` | Move to cardio bucket. |
| `AA11` (severe obesity) | `INFLAMMATORY_DRIVER` | `shared.json` | `GENERAL_MEDICINE_ENDOCRINOLOGY` | Move to inflammatory-driver bucket. |

### E. Structural gap — no dedicated file for `HEREDITARY`

`V01`, `V07`, `V08` (all `HEREDITARY`, all ATTRv-critical — they feed `V_RULE_02`, `V_RULE_05`,
`V_RULE_06`, and `AC03`/`AC05`/`AC08`) are currently sitting inside `shared.json` alongside
unrelated `SYSTEMIC_CONTEXT` atoms, distinguished only by which file they happen to be in — which
is exactly the fragile pattern causing defects B–D above. Once `reasoning_bucket` is an explicit
field (fix at the top of this document), this stops being load-bearing, but the recommendation
is still to give `HEREDITARY` its own file (`hereditary.json`) for readability, alongside
`AA03`/`AA04` once moved there per fix D.

### F. Non-bugs — do not "fix" these

- `V25` splitting into `af` / `arrhythmia` / `conduction_disease` / `pacemaker_implantation` /
  `pacemaker_presence`, all inside `cardio.json` — fine. Same bucket, finer-grained decomposition
  of one compound workbook row.
- Similar compound splits within a single bucket file (cardiac lab panels, GI symptom lists,
  inflammatory driver sub-types, renal lab results) — fine for the same reason. The danger is
  specifically when the same evidence lands in **two different buckets**, not when one workbook
  row becomes several fine-grained atoms inside **one** bucket.
- `V27` currently splits into `neurogenic_bladder` / `urinary_incontinence` / `urinary_retention`,
  all inside `autonomic.json` — not a correctness bug (same bucket throughout), just finer-grained
  than the workbook's single `ATOM_V27`. Optional to consolidate into one atom for fidelity;
  not required for correctness.

## Full corrected atom catalog (88 atoms, grouped by bucket)

Default `source_specialty` is stated once per bucket; only exceptions are listed per row. This
table is the complete population target for `atoms/*.json` — cross-check against
`Atoms creation/atom_index.csv` for existing human-readable names and reuse them where they are
already correct.

### ORTHO — default `source_specialty: ORTHOPEDIC_SURGERY_MSK`

| Canonical ID | Rows | Feature |
|---|---|---|
| `ORTHO_CTS_BILAT_RECURRENT` | WT02, V13 | Bilateral/recurrent carpal tunnel syndrome *(currently unlinked — Fix A)* |
| `ATOM_WT03` | WT03 | Spontaneous distal biceps tendon rupture |
| `ATOM_WT04` | WT04 | Multiple orthopedic red flags across tissues *(missing — Fix A)* |
| `ORTHO_LUMBAR_STENOSIS` | WT05, V30 | Lumbar spinal stenosis / decompression |
| `ATOM_WT06` | WT06 | Hip/knee arthroplasty |
| `ATOM_WT07` | WT07 | Trigger finger / digit release |
| `ATOM_WT08` | WT08 | Rotator cuff tear / shoulder pathology |

### CARDIO — default `source_specialty: CARDIOLOGY`

| Canonical ID | Rows | Feature | Specialty exception |
|---|---|---|---|
| `ATOM_WT11` | WT11 | AF/flutter | |
| `CARD_HFPEF_UNEXPLAINED` | WT09, AL14 | Unexplained HFpEF | |
| `CARD_CONDUCTION_PACEMAKER` | WT12, V25 | Conduction disease / pacemaker | |
| `CARD_LV_THICKENING_UNEXPLAINED` | WT10, AL15 | Unexplained LV wall thickening | |
| `ATOM_WT13` | WT13 | Late-onset HCM phenotype | |
| `ATOM_WT14` | WT14 | Severe AS | |
| `ATOM_WT15` | WT15 | Relative apical sparing | |
| `ATOM_WT16` | WT16 | Voltage/mass discordance, pseudoinfarction | |
| `ATOM_WT17` | WT17 | Reduced myocardial contraction fraction | |
| `ATOM_WT19` | WT19 | BNP/LVMI ratio (experimental) | |
| `ATOM_AL16` | AL16 | Low ECG voltage / pseudoinfarction | |
| `ATOM_AL17` | AL17 | Disproportionate NT-proBNP/troponin | |
| `ATOM_AL20` | AL20 | Dyspnea | |
| `ATOM_AL28` | AL28 | Pleural/serosal effusion | |
| `ATOM_AL29` | AL29 | Hypotension/syncope/dizziness *(move from shared.json — Fix D)* | |
| `ATOM_AL33` | AL33 | Unexplained cardiomyopathy/cardiomegaly | |
| `ATOM_V23` | V23 | Cardiac sympathetic denervation (MIBG) *(move from autonomic.json — Fix D)* | `NUCLEAR_CARDIOLOGY` |
| `ATOM_V24` | V24 | Cardiomyopathy/HFpEF/LV thickening (ATTRv) | |

### NEURO — default `source_specialty: NEUROLOGY`

| Canonical ID | Rows | Feature | Specialty exception |
|---|---|---|---|
| `ATOM_V02` | V02 | Progressive axonal sensorimotor PN | |
| `ATOM_V04` | V04 | Painful small-fiber neuropathy | |
| `ATOM_V14` | V14 | CIDP label, poor IVIG response | |
| `ATOM_V18` | V18 | Rising NfL | |
| `ATOM_V20` | V20 | Abnormal cutaneous silent period | |
| `ATOM_V21` | V21 | MR neurography abnormality | |
| `ATOM_V22` | V22 | Nerve ultrasound abnormality | |
| `ATOM_V28` | V28 | Bulbar symptoms *(move from gi_hepatic.json — Fix D)* | |
| `ATOM_V29` | V29 | Painless plantar ulcers / trophic change | |
| `ATOM_AL24` | AL24 | Symmetric sensorimotor PN | |
| `ATOM_WT21` | WT21 | Bilateral SNHL greater than age expectation | `AUDIOLOGY_ENT` |
| `ATOM_WT22` | WT22 | Mild sensory PN *(missing — Fix A)* | |

### AUTONOMIC — default `source_specialty: NEUROLOGY_AUTONOMIC_CLINIC`

| Canonical ID | Rows | Feature | Specialty exception |
|---|---|---|---|
| `ATOM_V05` | V05 | Early dysautonomia (general) | |
| `AUTONOMIC_ORTHOSTASIS` | V09, AL13 | Orthostatic hypotension *(fragmented — Fix C)* | `CARDIOLOGY_OR_NEUROLOGY_VITALS` |
| `AUTONOMIC_GI_DYSMOTILITY` | V10 (+ AL11 as GI_HEPATIC) | GI dysmotility *(cross-bucket dup — Fix B)* | `GASTROENTEROLOGY` |
| `AUTONOMIC_GASTROPARESIS_EARLY_SATIETY` | V11 (+ AL10 as GI_HEPATIC) | Gastroparesis / early satiety *(cross-bucket dup — Fix B)* | `GASTROENTEROLOGY` |
| `ATOM_V19` | V19 | Reduced SUDOSCAN ESC | |
| `ATOM_V26` | V26 | Erectile dysfunction | `UROLOGY` |
| `ATOM_V27` | V27 | Urinary retention/incontinence, neurogenic bladder | `UROLOGY` |
| `ATOM_V31` | V31 | Falling BP / antihypertensive intolerance *(move from cardio.json — Fix D)* | `CARDIOLOGY` |
| `ATOM_V34` | V34 | Severe GI weight loss labeled eating disorder *(move from shared.json — Fix D)* | `PSYCHIATRY_OR_GASTROENTEROLOGY` |

### RENAL — default `source_specialty: NEPHROLOGY`

| Canonical ID | Rows | Feature |
|---|---|---|
| `RENAL_PERSISTENT_PROTEINURIA` | AA16, AL03 | New/progressive proteinuria |
| `RENAL_NEPHROTIC_PROTEINURIA` | AA17, AL04 | Nephrotic-range proteinuria |
| `RENAL_HYPOALBUMINEMIA_PROTEIN_LOSS` | AA18, AL05 | Hypoalbuminemia with edema |
| `RENAL_EGFR_DECLINE` | AA20 | Rising creatinine / falling eGFR |
| `RENAL_EGFR_DECLINE_CONTEXTUAL` | AL06 | eGFR decline with proteinuric/clonal context |
| `ATOM_AA15` | AA15 | New microalbuminuria |
| `ATOM_AA19` | AA19 | Peripheral edema/anasarca |
| `ATOM_V17` | V17 | Persistent microalbuminuria in known TTR carrier |

### HEME_CLONAL — default `source_specialty: HEMATOLOGY_ONCOLOGY`

| Canonical ID | Rows | Feature |
|---|---|---|
| `ATOM_AL01` | AL01 | Known plasma-cell dyscrasia/myeloma |
| `HEME_MGUS` | AL02 | MGUS under surveillance |

### INFLAMMATORY_DRIVER — default varies per atom, no single specialty

| Canonical ID | Rows | Feature | `source_specialty` |
|---|---|---|---|
| `ATOM_AA01` | AA01 | Chronic inflammatory joint disease | `RHEUMATOLOGY` |
| `ATOM_AA02` | AA02 | FMF | `RHEUMATOLOGY_GENETICS` |
| `ATOM_AA06` | AA06 | Other autoinflammatory syndrome | `RHEUMATOLOGY_GENETICS` |
| `ATOM_AA07` | AA07 | Aggressive/fistulizing IBD | `GASTROENTEROLOGY` |
| `ATOM_AA08` | AA08 | Chronic/active infection (TB, bronchiectasis) | `INFECTIOUS_DISEASE_PULMONOLOGY` |
| `ATOM_AA09` | AA09 | Recurrent SSTI / chronic wounds | `INFECTIOUS_DISEASE_WOUND_CARE` |
| `ATOM_AA10` | AA10 | Castleman disease / RCC | `ONCOLOGY_HEMATOLOGY` |
| `ATOM_AA11` | AA11 | Severe obesity as idiopathic-AA context *(move from shared.json — Fix D)* | `GENERAL_MEDICINE_ENDOCRINOLOGY` |

### INFLAMMATORY_ACTIVITY — default `source_specialty: RHEUMATOLOGY_LAB_MEDICINE`

| Canonical ID | Rows | Feature |
|---|---|---|
| `ATOM_AA05` | AA05 | Colchicine nonadherence in FMF |
| `ATOM_AA12` | AA12 | Persistent CRP/ESR elevation |
| `ATOM_AA13` | AA13 | Persistently elevated SAA |
| `ATOM_AA14` | AA14 | Recurrent/uncontrolled flares |

### HEREDITARY — default `source_specialty: CLINICAL_GENETICS_OR_FAMILY_HISTORY` — needs own file (Fix E)

| Canonical ID | Rows | Feature | Specialty |
|---|---|---|---|
| `ATOM_V01` | V01 | Known pathogenic TTR variant | `CLINICAL_GENETICS` |
| `ATOM_V07` | V07 | First-degree family history of ATTR | `FAMILY_HISTORY` |
| `ATOM_V08` | V08 | Family history of unexplained progressive PN | `FAMILY_HISTORY` |
| `ATOM_AA03` | AA03 | High-risk MEFV genotype *(move from inflammatory.json — Fix D)* | `CLINICAL_GENETICS` |
| `ATOM_AA04` | AA04 | Family history of AA/ESRD *(move from inflammatory.json — Fix D)* | `FAMILY_HISTORY_NEPHROLOGY` |

### OCULAR — default `source_specialty: OPHTHALMOLOGY`

| Canonical ID | Rows | Feature |
|---|---|---|
| `ATOM_V15` | V15 | Vitreous opacities |
| `ATOM_V16` | V16 | Scalloped pupil / iris abnormality |
| `ATOM_V35` | V35 | Glaucoma / dry eye (nonspecific) |

### MUCOSAL_CUTANEOUS — default `source_specialty: DERMATOLOGY`

| Canonical ID | Rows | Feature | Specialty exception |
|---|---|---|---|
| `ATOM_AL07` | AL07 | Macroglossia | `GENERAL_EXAM_DENTAL_ENT` |
| `ATOM_AL08` | AL08 | Periorbital/pinch purpura | `DERMATOLOGY` |

### GI_HEPATIC — default `source_specialty: GASTROENTEROLOGY_HEPATOLOGY`

| Canonical ID | Rows | Feature |
|---|---|---|
| `ATOM_AA22` | AA22 | Intractable diarrhea |
| `ATOM_AA23` | AA23 | Melena / GI bleeding / ileus |
| `ATOM_AL18` | AL18 | Hepatomegaly / cholestatic ALP elevation |
| `AUTONOMIC_GI_DYSMOTILITY` (AL side) | AL11 | GI dysmotility, AL context only — see AUTONOMIC section |
| `AUTONOMIC_GASTROPARESIS_EARLY_SATIETY` (AL side) | AL10 | Gastroparesis/early satiety, AL context only — see AUTONOMIC section |

### SYSTEMIC_CONTEXT — default varies, no single specialty

| Canonical ID | Rows | Feature | `source_specialty` |
|---|---|---|---|
| `ATOM_WT18` | WT18 | BP fall / HF-med intolerance *(move from cardio.json — Fix D)* | `CARDIOLOGY` |
| `ATOM_WT20` | WT20 | Incidental bone-scan myocardial uptake *(move from cardio.json — Fix D)* | `NUCLEAR_MEDICINE` |
| `ATOM_WT23` | WT23 | Age + male sex | `DEMOGRAPHICS` |
| `SYSTEMIC_WEIGHT_LOSS` | V12, AL09 | Unintentional weight loss | `VITALS_NUTRITION` |
| `ATOM_AL19` | AL19 | Fatigue/malaise/weakness | `GENERAL_MEDICINE` |
| `ATOM_AL34` | AL34 | Nonspecific edema *(move from renal.json — Fix D)* | `GENERAL_MEDICINE` |
| `ATOM_AA24` | AA24 | Hypothyroidism/goiter | `ENDOCRINOLOGY` |

## Not atoms — do not add to `atoms/`

- `WT01`, `V03`, `V06`, `AA21`, `AL21`, `AL26`, `AL27` and all guardrail rows (`WT24`–`WT30`,
  `V32`–`V41`, `AA25`–`AA30`, `AL22`, `AL23`, `AL25`, `AL30`, `AL31`) are **rules**, not atoms.
  They are covered in `03_combinations.md`, `04_guardrails.md`, and `05_temporal_rules.md`. They
  correctly have no entry in `atoms/` today — confirmed absent, which is right.
- `WT30` (uric acid) and `V36` (declining prealbumin) exist as atoms **for provenance only** —
  tag them `DO_NOT_USE` and exclude from every combination/overlay. They already exist in the
  current build; keep them, just don't wire them into any rule.

## Review checklist for this file

- [ ] Confirm the `reasoning_bucket_overrides` mechanism is acceptable, or propose an alternative
      for the two GI-dysmotility exception atoms.
- [ ] Confirm the fix list in sections A–E before I touch any JSON.
- [ ] Confirm the "not atoms" list — nothing there should accidentally get created later.
- [ ] Flag any `source_specialty` value above you'd assign differently.

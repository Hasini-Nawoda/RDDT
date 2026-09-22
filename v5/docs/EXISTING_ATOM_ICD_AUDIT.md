# V5 existing-atom ICD-10 audit

Audit date: 2026-09-22

## Scope

This audit does not add or propose new atoms. It reviews the ICD-10-CM and
SNOMED mappings attached to the 192 existing shared atoms.

For each existing atom, the intended process is:

1. verify the meaning of every configured code;
2. retain only codes that can truthfully represent the atom;
3. search the 26,653 codes observed in the warehouse for better or missing
   codes;
4. search the official 2026 ICD-10-CM dictionary only when the warehouse does
   not contain a suitable code; and
5. keep the atom code-free when ICD-10-CM cannot represent the required
   measurement, trajectory, procedure, qualifier, or NLP assertion.

The 465-code and 895-code amyloidosis files are candidate indexes only. They
are not authoritative mappings and must never be bulk-added to the atoms.

## Inputs reviewed

- 26,653 distinct ICD codes observed in the warehouse, with usage counts and
  resolved meanings;
- 48 distinct SNOMED procedure codes observed in the warehouse;
- the official 2026 ICD-10-CM billable-code file containing 74,719 codes;
- the official 2026 and 2027 order files;
- the local/UMLS lookup script and caches;
- the supplied 465-code amyloidosis-related list;
- the supplied 895-code diagnostic-signal list; and
- all 17 shared-atom JSON files plus the confirmed-patient terminology.

The local `.env` file was not read or copied. The audit does not contain an
API key or patient identifiers.

## Meaning-extraction quality

The code-meaning extraction is suitable for this audit:

- 26,612 of 26,653 warehouse ICD codes have an exact local ICD-10-CM match;
- 37 codes use a documented parent-code fallback; and
- four nonstandard values remain unresolved.

Parent fallback is acceptable for describing a questionable source value, but
it must not make that value an executable exact code mapping. The
`EXACT_MATCH` field preserves this distinction.

The selection logic that produced the 465-code and 895-code files is not in
`search.py`, so those lists are not reproducible from the supplied program.
They are useful discovery inputs, not a basis for automatic configuration.

## Current configuration inventory

| Measure | Result |
|---|---:|
| Shared atoms | 192 |
| Atoms referenced by phenotype signal mappings | 167 |
| Configured ICD mapping rows | 662 |
| Distinct configured ICD values in shared atoms | 368 |
| Configured SNOMED mapping rows | 245 |
| Distinct configured SNOMED values in shared atoms | 207 |
| Prefix fallbacks | 4 |

Every one of the 662 ICD mappings is currently marked `DIRECT_TARGET` and
`can_fire_atom_alone=true`. The configuration therefore has no distinction
between an exact diagnosis, a broad proxy, a supporting code, an alternative
etiology, and a code that requires surrounding context. A wrong mapping can
directly create a clinical atom.

Among the 167 phenotype-referenced atoms:

- 97 have at least one configured ICD code observed in the warehouse;
- 21 have no configured warehouse ICD code but have one or more candidate
  codes requiring review; and
- 49 have no appropriate discovered claims code. Most of these are lab
  results, measurements, imaging patterns, trajectories, treatment response,
  or other concepts that should remain code-free.

## Main audit findings

### Existing mappings are the first problem to fix

The audit found 209 configured ICD mapping rows with no lexical alignment
between the resolved code meaning and the atom definition. Lexical alignment
is only a triage test, not clinical validation, but manual review confirmed
systematic copy/paste and semantic errors.

Fifty-one phenotype-referenced atoms contain at least one high-priority
mapping mismatch. In addition, 186 distinct system/code values are assigned to
multiple atoms; 183 of those reuses contain more than one direct mapping. Some
reuse is compatible, such as an AF code supporting both AF and a broad
arrhythmia atom. Other reuse creates contradictory findings.

Examples with direct warehouse impact:

| Current code | Actual meaning | Incorrect atom use |
|---|---|---|
| `I44.2` | Complete atrioventricular block | Atrial fibrillation |
| `K59.00` | Constipation | Diarrhea |
| `R19.7` | Diarrhea | Constipation |
| `Z98.890` | Other specified postprocedural state | Carpal-tunnel release, lumbar decompression, and trigger-finger release |
| `R13.10` | Dysphagia | Choking, dysarthria, and hoarseness |
| `R20.2` | Paresthesia | Small-fiber neuropathy and sensory loss |
| `I51.7` | Cardiomegaly | HFpEF and increased wall thickness |
| `I42.8` / `I42.9` | Other/unspecified cardiomyopathy | Increased wall thickness |
| `M65.331` | Trigger finger | Biceps rupture and rotator-cuff disorder |
| `M75.101` | Rotator-cuff tear | Trigger finger |
| `H04.123` | Bilateral dry-eye syndrome | Glaucoma |

These are not minor terminology differences. They can change a patient's
phenotype combination and verdict.

### Broad prefix matching creates additional false findings

The four current prefix fallbacks are:

| Prefix | Atom | Assessment |
|---|---|---|
| `I48.*` | Atrial fibrillation/flutter | Coherent for the warehouse codes reviewed |
| `I44.*` | Conduction disease | Coherent for the warehouse codes reviewed |
| `I45.*` | Conduction disease | Too broad: also captures pre-excitation and long-QT syndromes |
| `I42.*` | Increased ventricular wall thickness | Incorrect and high risk |

`I42.*` matches dilated, hypertrophic, restrictive, alcoholic, drug-induced,
other, and unspecified cardiomyopathies. Cardiomyopathy does not establish
increased ventricular wall thickness. This fallback must be removed from the
`thick_walls` atom. Codes in the I42 family may support the existing
`cardiomyopathy`, `hypertrophic_cardiomyopathy`, or
`restrictive_cardiomyopathy` atoms according to their exact meanings.

### Nonbillable parent codes do not cover their observed children

Fifteen configured parent codes are absent from the warehouse while billable
descendants are present. Exact matching will not bridge that gap.

Important examples:

- `G56.0` does not match `G56.01` or `G56.02`, leaving 1,383 right-sided and
  817 left-sided CTS patients without the intended side-specific atom.
- `I50.3` does not match `I50.30` or `I50.31`.
- `R53.8` does not match `R53.82` or `R53.83`.
- `Z51.1` does not match `Z51.12`.

Descendant expansion must still be semantic. For example, expanding `M66.8`
would include spontaneous tendon ruptures of the hand, ankle, and foot, which
does not make them distal-biceps rupture evidence.

### The supplied candidate lists contain useful codes and major false leads

The two supplied lists contain 895 unique warehouse codes. After including
the confirmed-patient terminology, 802 are not configured in an existing
atom.

That does not mean 802 codes should be added. The 895-code list includes:

- neonatal jaundice;
- pregnancy-induced hypertension and gestational proteinuria;
- diabetic and hypertensive kidney disease;
- alcoholic cirrhosis and viral hepatitis;
- tuberculosis screening and exposure;
- drug-induced constipation; and
- 319 inflammatory/AA-pathway codes.

Those codes may describe an alternative cause, a guardrail, an unrelated
condition, or an out-of-scope amyloid pathway. They are not direct ATTR
signals.

Even the supplied Tier 2 list mixes different roles. For example:

- `G56.01` and `G56.02` are appropriate side-specific CTS candidates;
- `D47.2` is an appropriate MGUS candidate for the existing AL differential;
- `Q38.2` is an appropriate macroglossia candidate;
- `O13.9` and `O12.10` are pregnancy-specific and should not promote ATTR;
- `R80.2` is orthostatic proteinuria, not amyloid renal involvement; and
- `M48.02` is cervical stenosis, not the lumbar-stenosis ATTR prodrome.

### SNOMED is not useful for the current delivered data

None of the 207 distinct configured SNOMED values occurs in the 48 delivered
warehouse SNOMED values. The observed values are mainly procedures such as
hysterectomy, cesarean section, mastectomy, colectomy, kidney transplant, and
plain chest X-ray.

SNOMED configuration can remain available for future sources, but it cannot
improve recall on the current data and should not delay the ICD audit.

## High-confidence corrections for existing atoms

The following are correction targets, not new atoms.

### Add exact warehouse codes to existing atoms

| Existing atom | Add/review | Warehouse patients | Reason |
|---|---|---:|---|
| `cts_right` | `G56.01` | 1,383 | Exact right-sided CTS |
| `cts_left` | `G56.02` | 817 | Exact left-sided CTS |
| `cts_any` | `G56.01`, `G56.02`, `G56.03` | 5,109 combined | Exact CTS descendants; keep `G56.00` for unspecified side |
| `dizziness` | `R42` | 19,708 | Exact dizziness/giddiness symptom code |
| `syncope` | `R55` | 8,388 | Exact syncope/collapse code |
| `polyneuropathy` | `G62.9`, `G62.89` | 4,045 combined | Generic/other polyneuropathy; do not infer axonal or progressive qualifiers |
| `mgus` | `D47.2` | 176 | Monoclonal gammopathy |
| `macroglossia` | `Q38.2` | 12 | Exact macroglossia code |
| `anhidrosis` | `L74.4` | 1 | Exact anhidrosis code |
| `conduction_disease` | `I49.5` | 392 | Sick-sinus syndrome is explicitly within the atom definition |
| `fmf` | `M04.1` | 58 | Periodic fever syndromes; use only if the atom's FMF wording accepts the broader category |
| `hypoalbuminemia` | `R77.0` | 38 | Abnormality of albumin; still less specific than a measured low value |
| `vitreous_opacity` | `H43.391`, `H43.392`, `H43.393`, `H43.399` | 375 combined | Exact other-vitreous-opacity family |

`R77.0`, `G62.9`, `G62.89`, and `M04.1` require evidence-role review because
their meanings are broader than the full atom wording. They should not inherit
unavailable qualifiers.

### Remove or narrow incorrect codes in existing atoms

- `af`: retain the I48 family; remove I44, I45, and `Z95.0` values.
- `thick_walls`: remove I42, I50, and `I51.7` diagnosis codes and delete the
  `I42.*` prefix fallback. Wall thickness is an imaging measurement, not a
  cardiomyopathy claim code.
- `hfpef`: remove `I42.9` and `I51.7`. Review I50.30-I50.33 as diastolic-HF
  proxies rather than exact HFpEF assertions.
- `restrictive_cardiomyopathy`: retain `I42.5`; remove generic `I42.8` and
  `I42.9` as direct evidence.
- `low_ecg_voltage` and `pseudo_infarct`: `R94.31` means abnormal ECG and does
  not establish either specific pattern.
- `hf_medication_intolerance` and `medication_dose_change`: `I95.9` establishes
  hypotension only, not medication intolerance or a dose change.
- `pacemaker_implantation`: `Z95.0` establishes pacemaker presence, not the
  implantation event. It is appropriate for `pacemaker_presence`.
- `constipation`: retain constipation-specific K59 values; remove diarrhea
  codes.
- `diarrhea`: retain `R19.7` and `K59.1`; remove constipation codes.
- `dysarthria`: retain `R47.1` only from the current set.
- `dysphagia`: retain the R13 family only from the current set.
- `hoarseness`: retain `R49.0` only from the current set.
- `early_satiety`: retain `R68.81`; do not infer it from nausea/vomiting.
- `nausea` and `vomiting`: use the appropriate R11 descendants; do not infer
  either from gastroparesis or early satiety.
- `dry_eye`: use H04.12x dry-eye codes; remove glaucoma codes.
- `glaucoma`: use the appropriate H40 family; remove dry-eye codes.
- `vitreous_opacity`: replace crystalline-deposit codes with H43.39x where the
  intended atom is general vitreous opacity.
- `charcot_arthropathy`: remove the L97 ulcer family. Retain reviewed M14
  neuropathic-arthropathy codes.
- `plantar_ulcer`: retain applicable L97 foot-ulcer codes; remove Charcot-joint
  codes.
- `sensory_loss`: retain anesthesia/hypoesthesia codes such as `R20.0` and
  `R20.1`; paresthesia `R20.2` does not establish sensory loss.
- `sfn`: no ICD-10-CM code in the supplied warehouse data specifically proves
  small-fiber neuropathy. `R20.2` must not fire it directly.
- `neurogenic_bladder`: retain N31 codes; urinary retention and incontinence
  alone do not establish neurogenic bladder.
- `urinary_retention`: retain R33 codes; do not treat incontinence as
  retention.
- `urinary_incontinence`: retain R32/applicable incontinence codes; do not
  treat retention as incontinence.
- `biceps_rupture`: retain reviewed M66.82x spontaneous upper-arm tendon codes
  as the closest ICD representation; remove trigger-finger, rotator-cuff, and
  traumatic-injury codes.
- `rotator_cuff`: retain applicable M75.10x-M75.12x nontraumatic tear codes;
  remove trigger-finger and biceps-rupture codes.
- `trigger_finger`: retain M65.3xx trigger-finger codes; remove biceps and
  rotator-cuff codes.
- `ctr_any`, `lumbar_decompression`, and `trigger_release`: remove `Z98.890`.
  It is a generic postprocedural-state code and cannot identify which procedure
  occurred.
- `lumbar_stenosis`: retain `M48.061` and `M48.062`. Do not add cervical
  stenosis `M48.02` or unspecified-site `M48.00`.
- `unintentional_weight_loss`: retain `R63.4` and review `R64`; remove anorexia
  nervosa codes and gastroparesis as direct weight-loss evidence.
- `fhx_established_attr`: generic family-history, susceptibility, and carrier
  codes do not establish a first-degree family history of ATTR. This atom
  should remain NLP/genetic-documentation based unless an ATTR-specific code
  exists.
- result/trajectory atoms such as eGFR, creatinine, BNP, NT-proBNP, troponin,
  urine protein, weight, ventricular measurements, and declining blood
  pressure should not fire from diagnosis codes that merely name a disease or
  symptom.

## Required evidence roles

Correct code text is not sufficient when the atom requires a qualifier that
ICD-10-CM does not encode. The existing atoms need four code roles:

1. `EXACT_DIRECT`: the code itself establishes the atom, such as `G56.01` for
   right CTS.
2. `PROXY_SUPPORT`: the code supports review but does not establish the full
   atom, such as a diastolic-HF code for an HFpEF-oriented atom.
3. `ALTERNATIVE_OR_GUARDRAIL`: the code represents a competing explanation and
   must not promote the positive phenotype.
4. `NO_VALID_ICD`: the atom requires measurement, chronology, procedure detail,
   result interpretation, or narrative context not represented by ICD-10-CM.

The current runtime collapses all four roles into direct atom firing. Correcting
the code lists without enforcing these roles would leave the core problem in
place.

## Correction workflow

1. Preserve the current config as the pre-audit checkpoint.
2. Create one V5 terminology-override registry keyed by existing `atom_id`,
   code system, and code. Do not create atoms.
3. For every current mapping, record `KEEP`, `REMOVE`, `MOVE_TO_EXISTING_ATOM`,
   or `RECLASSIFY_PROXY/GUARDRAIL`, with the resolved meaning and rationale.
4. Add codes only to an existing atom and only after searching the warehouse
   vocabulary first.
5. Use the official dictionary for valid codes absent from the warehouse, but
   label them `NOT_OBSERVED_IN_CURRENT_DATA` so they cannot be credited with
   current recall gains.
6. Generate the runtime mappings from the reviewed registry instead of copying
   code lists manually among JSON files.
7. Add tests that reject contradictory reuse, nonbillable exact parents,
   direct mappings with mismatched meanings, and broad prefix fallbacks.
8. Re-run the 20-patient linked cohort and compare which evidence and verdicts
   change. The expected first effect is fewer false specific findings, followed
   by recovered CTS, MGUS, syncope, dizziness, macroglossia, and polyneuropathy
   evidence where appropriate.

## Decision

Do not add new atoms. Do not bulk-import the 465/895 candidate lists. Clean the
existing direct mappings first, then add verified warehouse codes to the
existing atoms. Leave concepts code-free whenever ICD-10-CM cannot support the
full assertion.


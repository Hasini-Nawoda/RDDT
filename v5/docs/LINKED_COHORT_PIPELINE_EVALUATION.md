# V5 linked-cohort pipeline evaluation

Evaluation date: 2026-09-22

## Executive outcome

The warehouse extract is usable for a real V5 evaluation. All five files
contain the same 20 patients, so the pipeline can now be tested through
patient verdicts and profiles without fabricating joins.

The run confirms that encounter dates can recover dates for most claim rows,
and that claims-recall mode finds additional review candidates. It also
exposes four correctness problems that must be fixed before the output can be
treated as clinically reliable:

1. duplicated claim lines multiply evidence and make an unprepared run very
   slow;
2. provisional recall evidence can downgrade an otherwise strict pass;
3. localized and unspecified amyloidosis are mislabeled as known ATTR; and
4. several broad or ambiguous ICD-10 mappings are reported as if they proved
   a much more specific clinical finding.

The right V5 approach is therefore not to require unavailable context and
lose patients, or to pretend that broad codes prove facts they do not. V5
should keep high-recall candidates while explicitly distinguishing exact
evidence, proxy evidence, unavailable context, and contradictory/ambiguous
configuration.

## Linked data received

| Table | Rows | Distinct patients |
|---|---:|---:|
| CENSUS | 20 | 20 |
| CLAIMS | 16,020 | 20 |
| ENCOUNTERS | 4,359 | 20 |
| LABS | 36,398 | 20 |
| SURGICAL_HISTORY | 22 | 20 |

The all-five intersection and union are both 20 patients. There are no exact
duplicate full rows in any export.

Medication and social history were not used and are not part of V5.

## Join and source-quality findings

### Claims and encounter dates

- All 16,020 claim rows use ICD-10-CM.
- 13,602 rows are duplicates at patient + encounter + diagnosis-code grain,
  leaving 2,418 distinct claim evidence records.
- 14,415 raw claim rows (90.0%) match an encounter on patient + encounter and
  resolve to one encounter date.
- 1,605 claim rows do not have a matching encounter.
- No claim maps to conflicting encounter dates.
- ENCOUNTERS contains 4,064 distinct patient + visit keys. Although 294 keys
  repeat, every repeated key has a consistent date.

This means encounter dates are safe as a claim-date enrichment source after
the join is validated. An unmatched claim must remain visibly undated; its
code evidence should not be discarded solely because the date is absent.

### Labs

- 34,749 of 36,398 lab rows (95.5%) match ENCOUNTERS on patient + encounter.
- All lab observation dates are populated.
- The export contains 666 distinct local test names, not LOINC codes.
- It has no units, reference ranges, or abnormal flags.
- Notes are populated on 16,355 rows, but there are only 120 distinct notes,
  so much of the text is repeated or boilerplate rather than general-purpose
  clinical narrative.

Useful local-name families are present:

| Local-name family | Rows | Patients |
|---|---:|---:|
| BNP / NT-proBNP | 147 | 18 |
| Troponin | 101 | 17 |
| Free light chains | 22 | 6 |
| Electrophoresis / SPEP / UPEP | 80 | 8 |
| Urine protein | 62 | 14 |
| Creatinine / eGFR | 1,562 | 20 |
| Albumin | 787 | 19 |

These tests can be used only after a reviewed local-label mapping layer is
added. V5 must not label the local names as LOINC or infer abnormality without
units, ranges, and a validated result parser.

### Surgical history and census

- SURGICAL_HISTORY has 22 rows. Eighteen encounter IDs are `Unknown`, four
  are numeric, and four procedure dates are blank.
- The structured SNOMED field and available date are useful. `CATEGORY` is
  metadata and must not be treated as clinical narrative.
- CENSUS birth dates are year-only. They can support approximate age bands,
  but not precise age-at-event calculations.

## Pipeline runs

The evaluation used de-duplicated claims. The all-five run used ENCOUNTERS for
date enrichment, SURGICAL_HISTORY as structured SNOMED evidence, and CENSUS
and LABS to hydrate patient profiles. LABS was not allowed to fire clinical
atoms because the local-label mapping does not exist yet. NLP terminology was
disabled for this run because the required NLP runtime is not installed; this
also avoided the already-documented per-term pseudo-match explosion.

### Claims-only recall

| Measure | Count |
|---|---:|
| Patients evaluated | 20 |
| Candidate patients | 14 |
| Known amyloidosis rows routed by pre-screen | 4 |
| Known AL patients | 2 |
| Distinct source events | 1,597 |
| Qualified evidence rows | 1,468 |
| Signals | 1,022 |
| Combination rows | 308 |
| Patient verdicts | 20 |
| Suspicion profiles | 5 |

The verdict output contained four known-amyloidosis exclusions, five ATTR
claims-recall candidates, two confirmed AL patients, and nine patients held
without an ATTR or AL promotion.

The raw 16,020-row claims run did not finish within five minutes. The same run
on 2,418 distinct claim records completed in about 36 seconds. De-duplication
is therefore required before matching, not merely an optimization.

### All-five structured-evidence recall

| Measure | Count |
|---|---:|
| Patients evaluated | 20 |
| Candidate patients | 14 |
| Source events | 4,170 |
| Qualified evidence rows | 1,468 |
| Signals | 1,022 |
| Combination rows | 308 |
| Patient verdicts | 20 |
| Suspicion profiles | 5 |

The five suspicion profiles were hydrated from all five tables and each was
marked complete for the configured available sources. The result contained:

- one strict ATTR phenotype pass;
- four additional ATTR claims-recall candidates;
- four known-amyloidosis exclusions;
- two confirmed AL patients; and
- nine patients with no ATTR/AL promotion.

After known-patient exclusions, 1,368 claim events had an enriched date and
229 remained undated. ENCOUNTERS contributed 2,541 dated events.
SURGICAL_HISTORY contributed 24 dated and eight undated normalized events.

### Strict comparison

The all-five strict run produced three strict ATTR suspicion profiles, two
confirmed AL patients, four known-amyloidosis exclusions, and 11 patients
without a promotion.

This reveals a monotonicity defect: recall mode retained only one of the three
strict passes and converted the other two into recall-only candidates. Recall
mode must be a superset of strict mode. The likely cause is that provisional
support adds relaxations to an aggregate signal even when independent strict
support exists, making the downstream combination appear provisional.

## Patient-level review

Patient identifiers are replaced here by evaluation-only aliases. The alias
mapping is intentionally not stored in this report.

| Alias | Output | Main configured support | Important limitation |
|---|---|---|---|
| P03 | ATTRwt recall candidate | heart-failure code plus generic post-procedure status | date/ordering and exact procedure context unavailable |
| P04 | ATTRwt recall candidate | cardiomyopathy code plus generic post-procedure status | broad codes are presented as specific findings |
| P05 | ATTRwt recall candidate | cardiomyopathy plus post-procedure status | unexplained qualifier unavailable |
| P10 | strict ATTRv phenotype pass | `I42.8` plus `R20.2` | both codes are broader than the reported thick-wall/small-fiber findings |
| P14 | ATTRv and ATTRwt recall support | constipation, lumbar stenosis, cardiomyopathy, bilateral CTS codes | one constipation code is incorrectly labeled as diarrhea; several mappings are proxies |

The five profiles did prove that V5 can assemble a full cross-table patient
record. Their native row counts ranged from 505 to 3,319 rows. The clinical
wording, however, is currently too certain for the underlying codes.

## Configuration and interpretation defects

These findings do not justify silently rewriting the clinical atom or signal
files. They require a reviewed V5 evidence-policy overlay and, separately,
clinical approval for any terminology correction.

### Ambiguous or incorrect code reuse

- `Z98.890` is a generic postprocedural-status code but is configured under
  carpal-tunnel release, lumbar decompression/laminectomy, and trigger-finger
  release. One code can therefore create multiple specific findings.
- `K59.00` appears under both constipation and diarrhea. It represents
  constipation; reporting it as diarrhea is incorrect.
- `R20.2` represents paresthesia but is treated as direct evidence of
  small-fiber neuropathy and sensory loss.
- `I42.8` and `I42.9` are broad cardiomyopathy codes but are treated as direct
  evidence of thick walls, HFpEF, and restrictive cardiomyopathy.

The runtime currently trusts `can_fire_atom_alone` and does not enforce the
structured-code context guards. It then writes the configured atom name into
the profile as though it were an observed fact. This is the largest source of
potentially misleading patient-profile language in the linked run.

### Known-disease classification

The pre-screen sends every non-AL E85 code into a collection named
`known_attr_patients`. In this cohort that includes localized amyloidosis
(`E85.4`) and unspecified amyloidosis (`E85.9`). These patients should remain
known-amyloidosis exclusions unless there is actual evidence for ATTR; they
must not be described as known ATTR.

## V5 implementation plan

The plan preserves the clinical atoms, signals, and thresholds while changing
how the available evidence is prepared, qualified, combined, and explained.

1. **Canonicalize evidence before matching.** Normalize diagnosis codes and
   de-duplicate at patient + encounter + code grain. Preserve source-row
   lineage and duplicate counts for audit rather than matching every duplicate.
2. **Enrich dates without inventing them.** Join claims to a validated unique
   patient + encounter date index. Mark unmatched claims `DATE_UNAVAILABLE`
   and allow them to support non-temporal recall paths. Temporal rules may
   use only actual/enriched dates.
3. **Add source-aware evidence strength.** Classify configured mappings as
   exact, reviewed proxy, ambiguous reuse, or unavailable-context evidence.
   Broad proxy codes can generate a review candidate but cannot be narrated
   as the specific atom without corroboration.
4. **Make recall monotonic.** Compute strict support independently. If a
   strict combination passes, additional provisional evidence must not taint
   or downgrade it. Recall evaluation should only add candidates.
5. **Separate known amyloidosis from subtype claims.** Route known AL, known
   ATTR, localized amyloidosis, and unspecified/other amyloidosis into
   distinct transparent categories.
6. **Represent missing NLP once.** Store a bounded run/source capability gap
   instead of emitting one pseudo-match per NLP term per text event. Missing
   NLP context can prevent a strict assertion, but code-supported patients may
   remain review candidates.
7. **Add a reviewed local-lab dictionary.** Begin with BNP/NT-proBNP,
   troponin, free light chains, electrophoresis, urine protein, renal function,
   and albumin. Keep raw test name, value, note, observation date, mapping
   version, and uncertainty in the profile.
8. **Make profiles evidence-honest.** Show the observed source fact separately
   from the inferred atom, along with evidence strength, date provenance,
   missing qualifiers, relaxations, ambiguous mappings, and why the patient
   was promoted.
9. **Lock regression expectations.** On this 20-patient cohort, require:
   recall is a superset of strict; duplicate claim lines do not change a
   verdict; unmatched dates do not erase code support; broad codes never
   appear as unqualified specific findings; and known amyloidosis is not
   mislabeled as ATTR.

## Decision

The five-table data is sufficient to build and evaluate V5. It is not
necessary to request more tables before correcting the core pipeline.
Claims-only mode should intentionally favor recall, but its output must be a
transparent candidate verdict rather than an unsupported disease assertion.
The all-five mode can add encounter dates, surgical codes, profile context,
and later reviewed lab evidence without requiring a separate clinical ruleset.

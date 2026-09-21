# V5 data contract and architecture

## Decision

V5 must maximize screening recall without claiming that unavailable evidence
was observed. Missing dates, narrative, or surrounding context are source
limitations—not negative clinical findings. Explicit contradictions remain
clinically meaningful and may still block or reduce a signal according to the
unchanged clinical rules.

V4 remains the preserved baseline. V5 is implemented beside it and committed
in reviewable stages.

## Authoritative inputs

Only these tables are in scope: `CENSUS`, `CLAIMS`, `ENCOUNTERS`, `LABS`, and
`SURGICAL_HISTORY`. Medication and social history are excluded completely.
No V5 logic may query them, hydrate profiles from them, or infer their absence
as a patient-level clinical fact.

Two profiles enforce the product requirement:

| Profile | Detection inputs | Profile inputs | Date behavior |
|---|---|---|---|
| `claims_only_v1` | `CLAIMS` only | `CLAIMS` only | No claim date is invented; longitudinal requirements are source-unassessable |
| `all_available_v1` | `CLAIMS`, `ENCOUNTERS`, `LABS`, `SURGICAL_HISTORY` | All five tables | Native lab/surgical/encounter dates are used; claims may inherit an encounter date only from a validated unique patient-plus-encounter join |

## Verified sample findings

- `CLAIMS` has named patient, encounter, claim, status, diagnosis-type, and
  diagnosis-code fields. The placeholder columns that had been interpreted as
  dates, provider detail, secondary diagnoses, and notes were empty in all 50
  supplied rows. V5 therefore does not map them.
- Claims contain duplicate rows at patient, encounter, and diagnosis-code
  grain. Detection must deduplicate that grain before interpreting repeated
  rows as repeated clinical support.
- `ENCOUNTERS.VISITDATE` is populated in the sample. The supplied samples are
  independently drawn and contain no shared patients, so the full-data claim
  to encounter join remains unverified.
- `LABS` contains local free-text test identifiers, results, timestamps, and
  sparse notes. The identifier is not LOINC. Notes are largely boilerplate and
  are not a replacement for a general clinical-note corpus. Units, reference
  ranges, and abnormal flags are unavailable.
- `SURGICAL_HISTORY` includes dates and SNOMED fields. Encounter IDs were
  `Unknown` in all 50 sample rows, so V5 must not manufacture encounter links.
- `CENSUS.BIRTHDATE` was year-only/masked in the sample. V5 must not imply an
  exact date of birth or exact age when only a year is supplied.
- The five 50-row samples have no overlapping patients. That is expected for
  independent samples from very large tables and cannot be used as evidence
  that joins do or do not work in the full database.

## Clinical configuration versus operational feasibility

The clinical atom and signal files remain unchanged. They describe the
original intended evidence, including ICD-10, ICD-9, CPT/HCPCS, SNOMED, LOINC,
and narrative routes. V5 adds a capability overlay that records what each run
profile can actually observe:

- ICD-10 is directly available from claims.
- SNOMED is available only from surgical history in the five-table profile.
- ICD-9 and CPT/HCPCS are unavailable in the delivered fields.
- Local lab identifiers must not be passed through the LOINC route.
- Narrative/NLP is unavailable in claims-only and partial in five-table mode.
- Date-dependent logic is unassessable in claims-only unless a clinical rule
  can be satisfied without time. In five-table mode, dates remain specific to
  their native rows unless a join has been validated.

This separation makes it possible to explain both the original rule and the
evidence that the selected source profile could actually test.

## Evidence state model

Every patient/signal assessment should expose four separate states:

1. **Observed support** — qualifying code, structured value, or contextualized
   text actually present in the authorized inputs.
2. **Missing expected context** — the original signal expects corroboration,
   chronology, or context that was not present for this patient.
3. **Unavailable by source** — the selected run profile has no field/table
   capable of observing the expected item. This is not negative evidence.
4. **Explicit contradiction or blocker** — an observed competing explanation,
   negation, uncertainty, or guardrail. This remains clinically meaningful.

The recall-oriented screening verdict may promote code-supported candidates
when only states 2 or 3 prevent strict evaluation. The patient profile must
label that promotion and must never describe missing evidence as satisfied.

## Implementation stages

1. **Source contract and identity** — create the two V5 profiles, remove all
   out-of-scope tables, use V5 output names, and add capability reporting.
2. **Canonical event layer** — deduplicate claims, preserve null claim dates,
   normalize local lab labels separately from terminology codes, and validate
   any date-enrichment join before enabling it.
3. **Source-aware qualification** — distinguish failed, unassessable, and
   contradicted requirements. Add recall-oriented promotion for requirements
   that are unassessable solely because the active profile lacks dates or
   narrative.
4. **Transparent verdict/profile output** — produce a verdict for every
   patient and show observed support, unavailable/missing context, blockers,
   source coverage, and the reason for strict versus recall-oriented status.
5. **Validation** — compare strict and recall-oriented results, report the
   promotion delta, review high-impact promoted cohorts, and verify full-data
   joins before enabling derived claim dates.

## Safety rules

- Do not fabricate a date, unit, reference range, abnormal flag, narrative
  statement, or longitudinal trend.
- Do not interpret table/field absence as patient-level absence.
- Do not let repeated claim lines create false independent corroboration.
- Do not allow sparse boilerplate lab notes to stand in for clinical NLP.
- Keep confirmed ATTR/AL identification ahead of suspicion scoring, and keep
  ATTRv, ATTRwt, and AL outputs explicit rather than labeling the whole system
  as ATTRv-only.

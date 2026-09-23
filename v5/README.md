# RDDT V5

V5 is a source-aware refactor of the V4 amyloidosis screening pipeline. V4 is
preserved separately; V5 starts from the same clinical configuration but is
being adapted to the data that will actually be delivered.

## Source boundary

V5 recognizes exactly five physical tables:

1. `CENSUS`
2. `CLAIMS`
3. `ENCOUNTERS`
4. `LABS`
5. `SURGICAL_HISTORY`

Medication and social-history tables are not inputs to V5. They do not appear
in the V5 source contract, even as disabled compatibility entries.

## Run profiles

- `claims_only_v1` is the default and allows only `CLAIMS` to influence
  candidates, evidence, dates, verdicts, or patient-profile content.
- `all_available_v1` uses the five-table boundary. `CENSUS` hydrates profiles;
  the other four tables may provide screening evidence.
- `icd_dated_claims_v1` makes decisions from claim ICD-10 codes only. Encounter
  visit dates fill claim dates when the patient-plus-encounter join is unique.
  Census, encounters, labs, and surgical history are stored on the patient
  profile and do not fire atoms. Run that profile with evaluation mode
  `ICD_DATED_CLAIMS`. A direct-target code keeps the signal's configured tier.
  A proxy-support code, or a code that is missing note qualifiers such as
  progressive or length-dependent, still fires the signal one tier lower.
  The profile states what the signal expected and what the code showed.

Select the profile explicitly with `V5_SOURCE_SCHEMA_PROFILE` or the `profile`
argument to `load_source_config`.

The clinical atoms, signal definitions, and thresholds remain the V4-derived
configuration. V5 layers source capability and evidence transparency around
those definitions instead of silently rewriting the intended clinical logic.

See [V5_DATA_CONTRACT_AND_ARCHITECTURE.md](docs/V5_DATA_CONTRACT_AND_ARCHITECTURE.md)
for the verified data findings and implementation plan.

The first end-to-end sample run is documented in
[SAMPLE_PIPELINE_EVALUATION.md](docs/SAMPLE_PIPELINE_EVALUATION.md). Because
the random samples contain no linked patients, use
[extract_linked_evaluation_cohort.sql](sql/extract_linked_evaluation_cohort.sql)
to retrieve a real five-table test cohort from Snowflake.

The resulting 20-patient warehouse run, its strict-versus-recall comparison,
identified correctness defects, and the staged implementation plan are in
[LINKED_COHORT_PIPELINE_EVALUATION.md](docs/LINKED_COHORT_PIPELINE_EVALUATION.md).

The existing-atom ICD/SNOMED audit, including verified mapping defects and the
no-new-atoms correction workflow, is documented in
[EXISTING_ATOM_ICD_AUDIT.md](docs/EXISTING_ATOM_ICD_AUDIT.md).

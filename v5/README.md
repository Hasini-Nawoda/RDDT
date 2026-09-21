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

Select the profile explicitly with `V5_SOURCE_SCHEMA_PROFILE` or the `profile`
argument to `load_source_config`.

The clinical atoms, signal definitions, and thresholds remain the V4-derived
configuration. V5 layers source capability and evidence transparency around
those definitions instead of silently rewriting the intended clinical logic.

See [V5_DATA_CONTRACT_AND_ARCHITECTURE.md](docs/V5_DATA_CONTRACT_AND_ARCHITECTURE.md)
for the verified data findings and implementation plan.

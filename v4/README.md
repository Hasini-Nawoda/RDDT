# RDDT ATTR Phenotype V4

V4 contains a config-driven confirmed-patient extractor and the later ATTR
phenotype screening pipeline for a Snowflake workspace. The immediate first
run is confirmed-only: CLAIMS ICD-10 codes are matched against the exact
`ALL_AMYLOIDOSIS` allow-list, and no non-confirmed patient is scored. ATTRv,
ATTRwt, and AL remain available for the later full-pipeline run;
additional phenotype packages use the same runtime contract. The checked-in JSON files in
`config/` are the deployable clinical configuration. Corrected workbooks and
their compilers are build-time assets under `../v4_build_tools/`; Snowflake
does not read Excel or run the build tooling.

## Safety and data boundary

- Source warehouse tables are read only. The confirmed-only first-run notebook
  detects from the enabled CLAIMS source, then uses read-only `SELECT` queries
  to hydrate each confirmed patient's full EHR from all profile-enabled
  sources. It keeps the profile in notebook memory and creates no Snowflake
  table, view, or stage object.
- The confirmed-only run requires no event date, ICD-9, NLP, spaCy, or
  medSpaCy. Blank CLAIMS dates block only the later suspicion pipeline.
- Source-table selection is config-driven. The checked-in
  `config/source_schema.json` currently algorithm-enables only `claim`.
  `profile_enabled` independently controls whether a table contributes raw
  rows to final patient profiles.
- NLP terminology is applied with spaCy `PhraseMatcher` and medSpaCy clinical
  context. Regex, substring matching, and SQL text `LIKE`/`ILIKE` are not NLP
  fallbacks.
- Every PhraseMatcher occurrence is retained independently. Repeated mentions
  in one note can therefore carry different negation, uncertainty,
  experiencer, and temporal context instead of collapsing to one atom match.
- Narrative evidence keeps the warehouse row date as its availability date
  while resolving a separate mention-level clinical date for supported
  relative expressions such as `yesterday`, `three months ago`, and year-only
  history. Future/planned mentions remain `UNKNOWN`, not affirmative evidence.
- Candidate retrieval is not evidence. It only limits which source records are
  evaluated by the clinical pipeline.
- Before phenotype scoring, Step 03b separates patients with affirmed
  ATTR-specific documentation or the corroborated legacy E85/SNOMED known-
  amyloidosis pattern. A separate configurable known-AL route is also applied.
  Both confirmed-patient vocabularies are maintained together in
  `config/shared/confirmed_patients.json`; a missing or invalid AL route remains
  an explicit fail-safe gap.
- The workbook may contain missing structured codes. The runtime records gaps;
  it never invents or looks up a code.

## Run in Snowflake

Open `RDDT_ATTR_V4_Pipeline.ipynb` with Snowflake Warehouse Runtime and run the
cells in order. Do not install `requirements.txt` for this first pass. The
notebook reports total rows/distinct patients, reads the exact ICD-10 code and
type metadata from `config/shared/confirmed_patients.json`, and returns the
patient-level summary as the notebook-memory `confirmed_profiles_df`. It then
hydrates the full EHR only for confirmed patient IDs; profile-only tables do
not affect detection. The suspicion pipeline and non-confirmed patients are
not evaluated. See
`docs/SNOWFLAKE_RUNBOOK.md` for the exact sequence.

The operator-editable `config/source_schema.json` file is the source of truth
for the database/schema namespace, table toggles, and physical column mappings.
The active `sample_db_v1` profile points to
`UHTX_RDDT_CLINICAL_DEV.PUBLIC`, algorithm-enables only `CLAIMS`, and
profile-enables all six physical tables in the current warehouse; the preserved
`legacy_ehr_v1` profile can be selected with
`load_source_config(profile="legacy_ehr_v1")` or the
`V4_SOURCE_SCHEMA_PROFILE` environment variable. Under `columns`, the left
side is the stable pipeline field (`patient_id`, `diagnosis_code`, etc.) and
the right side is the current warehouse column name. When a warehouse schema
changes, update the profile rather than extraction code. Add a logical field
to `required_columns` only when the pipeline must reject a source table that
lacks it. See `docs/SNOWFLAKE_RUNBOOK.md` for the deployment and validation
sequence.

The run returns:

- stage-level counts and the pinned configuration hash;
- `run.router_output` for workspace-only result review and download;
- `run.known_attr_patients` and `run.known_al_patients` for confirmed patients
  removed before early-detection scoring;
- phenotype verdict slots including ATTRv, ATTRwt, and AL;
- one combined ATTR suspicion verdict and output tier, selected from the
  highest real phenotype pass across ATTRv and ATTRwt;
- a separate AL-detected output for every AL phenotype pass, including
  concurrent ATTR passes, plus a separate known-AL exclusion route;
- local-runtime JSONL and CSV exports for flagged patients. Both formats carry
  the ATTRv, ATTRwt, and AL verdicts plus the single combined ATTR tier.

When `profile_output_dir` is supplied, local outputs are organized as:

```text
profile_output_dir/
  confirmed/
    known_attr_patient_profiles.jsonl
    known_attr_patient_profiles.csv
  known_al/
    confirmed/
      known_al_patient_profiles.jsonl
      known_al_patient_profiles.csv
  detected/
    highest_suspicion/   # internal priority A
    high_suspicion/      # internal priority B
    moderate_suspicion/  # internal priority C
  al_detected/
    detected/
      al_detected_patient_profiles.jsonl
      al_detected_patient_profiles.csv
```

The default configurable profile threshold is `HIGHEST_SUSPICION` plus
`HIGH_SUSPICION`; the moderate files remain empty unless that level is enabled.

The workbook defines categorical review priority (`A`, `B`, or `C`) from
named signal combinations. Internal A/B/C classes are retained for config,
engine trace, and backward compatibility. Review-facing patient profiles and
downloads use only the consistent labels `HIGHEST_SUSPICION`,
`HIGH_SUSPICION`, and `MODERATE_SUSPICION`; session router rows include both
forms for internal auditability.
Flat bucket requirements and nested signal-group
rules are evaluated by the same combination engine. Each phenotype router
emits exactly one deterministic verdict per patient, and the ATTR aggregator
emits exactly one final suspicion tier per patient. Route-only
differential outcomes and cross-phenotype guardrails remain parallel routes:
they do not create a pass for the other phenotype and do not override its
independently evaluated verdict. The combined ATTR result uses only actual
ATTRv/ATTRwt phenotype passes. V4 does not invent a
numeric probability or risk score when the workbook does not define one.

JSONL/CSV exports exclude the duplicate `proprietary_pipeline_trace` payload by
default, while review-facing `algorithm_analysis` retains the exact stages and
rule identifiers needed to explain why the patient was flagged. Every profile
also contains raw EHR rows grouped by table under `ehr.records_by_table`.

## Build tooling

Workbook correction, audit, and compilation are offline build operations. See
`../v4_build_tools/README.md` and `../v4_build_tools/requirements-build.txt`.
They are not part of the Snowflake runtime.

A connected Snowflake run is required before deployment to validate
permissions, physical schema, data distributions, and reference/materialized
parity on warehouse data.

## Key modules

- `warehouse/source_schema.py` and `config/source_schema.json`: source-table
  toggles plus the physical-to-logical source schema mapping.
- `extraction/extraction_contract.py`: the single extraction routing, code-system,
  availability-date, and medSpaCy context-attribute policy file.
- `extraction/candidate_net.py`: structured candidate retrieval and broad text retrieval.
- `extraction/source_events.py`: normalized source evidence and lineage.
- `config/shared/confirmed_patients.json`: one editable contract containing the
  ATTR and AL confirmed-patient routes, terminology, and corroboration rules.
- `extraction/known_attr.py` / `extraction/known_al.py`: pre-screen vocabulary
  loading, structured-code corroboration, and exclusion records.
- `extraction/atom_matching.py` / `extraction/evidence_qualification.py`: workbook terminology,
  per-occurrence PhraseMatcher evidence, and clause-local medSpaCy context.
- `extraction/temporal_context.py`: token-based mention-level clinical-date
  resolution, separate from source availability dates.
- `reasoning/signal_engine.py` through `reasoning/router.py`: generic clinical reasoning stages.
- `output/patient_profile.py`: six-verdict medical profile, combined ATTR risk,
  and trace-safe exports.
- `pipeline.py`: end-to-end orchestration.
- `pipeline_steps/step_01_...step_11_...`: named runtime stages.

The ten difficult synthetic patients (one end-to-end profile plus nine
adversarial multi-row EHR cases), their runners, and the algorithm reachability
audit are build-time validation assets under `../v4_build_tools/validation/`;
they are deliberately outside this Snowflake deployment folder.

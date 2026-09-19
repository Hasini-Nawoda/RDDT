# RDDT ATTRv V4

V4 is a config-driven ATTRv screening pipeline for a Snowflake workspace. The
checked-in JSON files in `config/` are the deployable clinical
configuration. The corrected workbook and compiler are build-time assets under
`../v4_build_tools/`; Snowflake does not read Excel or run the build tooling.

## Safety and data boundary

- Source warehouse tables are read only.
- All V4 warehouse objects are session `TEMPORARY TABLE` objects named
  `AMY_V4_*`; no permanent or transient table is created.
- Social-history and medication tables are disabled.
- NLP terminology is applied with spaCy `PhraseMatcher` and medSpaCy clinical
  context. Regex, substring matching, and SQL text `LIKE`/`ILIKE` are not NLP
  fallbacks.
- Candidate retrieval is not evidence. It only limits which source records are
  evaluated by the clinical pipeline.
- The workbook may contain missing structured codes. The runtime records gaps;
  it never invents or looks up a code.

## Run in Snowflake

Open `RDDT_ATTRV_V4_Pipeline.ipynb` in the workspace, make this package and its
`config` directory available to the notebook, install the dependencies listed
in `requirements.txt`, and run the cells in order. The notebook obtains the
active Snowpark session, loads medSpaCy, validates the physical source schema,
then calls the current `run_attrv_v4_pipeline` compatibility wrapper. The
runtime itself is phenotype-generic: future loaded packages use
`run_phenotype_v4_pipeline(session, "PHENOTYPE", ...)` without changing the
numbered extraction or reasoning stages.

If the physical tables are in a database/schema namespace, set
`source_config["namespace"]` to `DATABASE.SCHEMA`. The table and column names
remain those in `source_schema.default_source_config()`.

The run returns:

- stage-level counts and the pinned configuration hash;
- `AMY_V4_ROUTER_OUTPUT` for result-grid review and download;
- six phenotype verdict slots per flagged profile, with only ATTRv evaluated
  until additional phenotype workbooks are loaded;
- local-runtime JSONL and CSV exports for flagged patients.

The workbook defines categorical review priority (`A`, `B`, or `C`) from
named signal combinations. Flat bucket requirements and nested signal-group
rules are evaluated by the same combination engine, and the router emits
exactly one deterministic ATTRv risk verdict per patient. V4 does not invent a
numeric probability or risk score when the workbook does not define one.

JSONL/CSV exports exclude proprietary algorithm trace and internal rule IDs by
default. The full in-memory profile stores the internal reasoning under the one
top-level key `proprietary_pipeline_trace`, which can be deleted without
removing the medical profile, clinical rationale, or verdicts.

## Build tooling

Workbook correction, audit, and compilation are offline build operations. See
`../v4_build_tools/README.md` and `../v4_build_tools/requirements-build.txt`.
They are not part of the Snowflake runtime.

A connected Snowflake run is required before deployment to validate
permissions, physical schema, data distributions, and reference/materialized
parity on warehouse data.

## Key modules

- `warehouse/source_schema.py`: allowed source tables and columns.
- `extraction/extraction_contract.py`: the single extraction routing, code-system,
  availability-date, and medSpaCy context-attribute policy file.
- `extraction/candidate_net.py`: structured candidate retrieval and broad text retrieval.
- `extraction/source_events.py`: normalized source evidence and lineage.
- `extraction/atom_matching.py` / `extraction/evidence_qualification.py`: workbook terminology,
  PhraseMatcher, and clinical context.
- `reasoning/signal_engine.py` through `reasoning/router.py`: generic clinical reasoning stages.
- `output/patient_profile.py`: six-verdict medical profile and trace-safe exports.
- `pipeline.py`: end-to-end orchestration.
- `pipeline_steps/step_01_...step_11_...`: named runtime stages.

The difficult synthetic-patient runner and algorithm reachability audit are
build-time validation assets under `../v4_build_tools/validation/`; they are
deliberately outside this Snowflake deployment folder.

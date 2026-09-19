# RDDT ATTR Phenotype V4

V4 is a config-driven ATTR phenotype screening pipeline for a Snowflake
workspace. ATTRv and ATTRwt are currently loaded; additional phenotype
packages use the same runtime contract. The checked-in JSON files in
`config/` are the deployable clinical configuration. Corrected workbooks and
their compilers are build-time assets under `../v4_build_tools/`; Snowflake
does not read Excel or run the build tooling.

## Safety and data boundary

- Source warehouse tables are read only.
- All V4 warehouse objects are session `TEMPORARY TABLE` objects named
  `AMY_V4_*`; no permanent or transient table is created.
- Social-history and medication tables are disabled.
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
  amyloidosis pattern. They are never evaluated by ATTRv or ATTRwt rules.
- The workbook may contain missing structured codes. The runtime records gaps;
  it never invents or looks up a code.

## Run in Snowflake

Open `RDDT_ATTR_V4_Pipeline.ipynb` in the workspace, make this package and its
`config` directory available to the notebook, install the dependencies listed
in `requirements.txt`, and run the cells in order. The notebook obtains the
active Snowpark session, loads medSpaCy, validates the physical source schema,
then calls `run_attr_v4_pipeline`. Every candidate is extracted once and then
evaluated by both the ATTRv and ATTRwt rule packages in the same run. There is
no phenotype selector in the notebook.

If the physical tables are in a database/schema namespace, set
`source_config["namespace"]` to `DATABASE.SCHEMA`. The table and column names
remain those in `source_schema.default_source_config()`.

The run returns:

- stage-level counts and the pinned configuration hash;
- `AMY_V4_ROUTER_OUTPUT` for result-grid review and download;
- `AMY_V4_KNOWN_ATTR` for patients removed before early-detection scoring;
- six phenotype verdict slots per flagged profile; ATTRv and ATTRwt are both
  evaluated, while the other four slots remain ready for future packages;
- one combined ATTR suspicion verdict and output tier, selected from the
  highest real phenotype pass across ATTRv and ATTRwt;
- local-runtime JSONL and CSV exports for flagged patients. Both formats carry
  the ATTRv and ATTRwt verdicts plus the single combined ATTR tier.

When `profile_output_dir` is supplied, local outputs are organized as:

```text
profile_output_dir/
  confirmed/
    known_attr_patient_profiles.jsonl
    known_attr_patient_profiles.csv
  detected/
    highest_suspicion/   # internal priority A
    high_suspicion/      # internal priority B
    moderate_suspicion/  # internal priority C
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
- `extraction/known_attr.py`: source-verbatim pre-screen known-ATTR vocabulary,
  structured-code corroboration, and exclusion records.
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

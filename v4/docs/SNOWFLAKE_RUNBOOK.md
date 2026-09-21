# V4 Snowflake runbook

This is the deployment and execution checklist for the V4 package. The first
run is deliberately CLAIMS-only and ICD-only for detection. Once a patient is
confirmed, the notebook hydrates that patient's full EHR from every available
table marked `profile_enabled`. All queries are read-only, fully qualified
SELECT statements, and the notebook keeps its result in notebook
memory; it creates no temporary, permanent, transient, shared, view, or stage
result object. The checked-in JSON configuration, not the analysis notebooks,
is the source of truth for a run.

## 0. Validate the provisional CLAIMS map

The supplied `new-sample-db/database_tables.csv` identifies the current
namespace as:

```text
database: UHTX_RDDT_CLINICAL_DEV
schema:   PUBLIC
tables:   CENSUS, CLAIMS, ENCOUNTERS, LABS, MEDICATIONS, SURGICAL_HISTORY
```

The supplied `database_columns.csv` identifies useful names for all of those
tables except `CLAIMS`, which exposes only `COLUMN0` through `COLUMN21`. V4 now
keeps two mappings together in `config/source_schema.json`:

- `sample_db_v1` is active and points to the current database. Only `CLAIMS`
  is algorithm-enabled. `CENSUS`, `CLAIMS`, `ENCOUNTERS`, `LABS`,
  `MEDICATIONS`, and `SURGICAL_HISTORY` are profile-enabled.
- `legacy_ehr_v1` preserves the previous table and column mapping and can be
  selected without reconstructing it.

The sample values strongly support `COLUMN0` as patient ID and
`COLUMN7`/`COLUMN8` as diagnosis type/code. The remaining `COLUMNn` meanings
follow the prior claim-column order and are explicitly provisional. In
particular, the date mappings (`COLUMN5`, `COLUMN6`, `COLUMN19`, `COLUMN20`)
must be checked against the full warehouse or its semantic dictionary before
the results are used clinically. Do not delete the legacy profile when the
current mapping is refined.

Before a production run, execute this read-only check in Snowflake and save
the result with the run record:

```sql
USE DATABASE UHTX_RDDT_CLINICAL_DEV;
USE SCHEMA PUBLIC;

SELECT CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA();
DESCRIBE TABLE UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS;
SELECT * FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS LIMIT 10;
```

Run this additional read-only preflight before editing the mapping. It gives
each opaque claim column its null rate, distinct count, one example, and a
generic date-parsing diagnostic. Snowflake can interpret numeric identifiers
as epoch-style dates, so `DATE_VALUES` must never be used by itself to identify
a date field. Confirm a date column from its meaning and formatted values.

```sql
WITH stats AS (
    SELECT 'COLUMN0' AS COLUMN_NAME, COUNT_IF(NULLIF(TRIM(COLUMN0), '') IS NULL) AS NULL_OR_BLANK, COUNT(DISTINCT COLUMN0) AS DISTINCT_VALUES, ANY_VALUE(COLUMN0) AS EXAMPLE_VALUE, COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN0), '')) IS NOT NULL) AS DATE_VALUES FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN1', COUNT_IF(NULLIF(TRIM(COLUMN1), '') IS NULL), COUNT(DISTINCT COLUMN1), ANY_VALUE(COLUMN1), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN1), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN2', COUNT_IF(NULLIF(TRIM(COLUMN2), '') IS NULL), COUNT(DISTINCT COLUMN2), ANY_VALUE(COLUMN2), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN2), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN3', COUNT_IF(NULLIF(TRIM(COLUMN3), '') IS NULL), COUNT(DISTINCT COLUMN3), ANY_VALUE(COLUMN3), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN3), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN4', COUNT_IF(NULLIF(TRIM(COLUMN4), '') IS NULL), COUNT(DISTINCT COLUMN4), ANY_VALUE(COLUMN4), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN4), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN5', COUNT_IF(NULLIF(TRIM(COLUMN5), '') IS NULL), COUNT(DISTINCT COLUMN5), ANY_VALUE(COLUMN5), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN5), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN6', COUNT_IF(NULLIF(TRIM(COLUMN6), '') IS NULL), COUNT(DISTINCT COLUMN6), ANY_VALUE(COLUMN6), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN6), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN7', COUNT_IF(NULLIF(TRIM(COLUMN7), '') IS NULL), COUNT(DISTINCT COLUMN7), ANY_VALUE(COLUMN7), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN7), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN8', COUNT_IF(NULLIF(TRIM(COLUMN8), '') IS NULL), COUNT(DISTINCT COLUMN8), ANY_VALUE(COLUMN8), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN8), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN9', COUNT_IF(NULLIF(TRIM(COLUMN9), '') IS NULL), COUNT(DISTINCT COLUMN9), ANY_VALUE(COLUMN9), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN9), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN10', COUNT_IF(NULLIF(TRIM(COLUMN10), '') IS NULL), COUNT(DISTINCT COLUMN10), ANY_VALUE(COLUMN10), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN10), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN11', COUNT_IF(NULLIF(TRIM(COLUMN11), '') IS NULL), COUNT(DISTINCT COLUMN11), ANY_VALUE(COLUMN11), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN11), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN12', COUNT_IF(NULLIF(TRIM(COLUMN12), '') IS NULL), COUNT(DISTINCT COLUMN12), ANY_VALUE(COLUMN12), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN12), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN13', COUNT_IF(NULLIF(TRIM(COLUMN13), '') IS NULL), COUNT(DISTINCT COLUMN13), ANY_VALUE(COLUMN13), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN13), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN14', COUNT_IF(NULLIF(TRIM(COLUMN14), '') IS NULL), COUNT(DISTINCT COLUMN14), ANY_VALUE(COLUMN14), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN14), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN15', COUNT_IF(NULLIF(TRIM(COLUMN15), '') IS NULL), COUNT(DISTINCT COLUMN15), ANY_VALUE(COLUMN15), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN15), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN16', COUNT_IF(NULLIF(TRIM(COLUMN16), '') IS NULL), COUNT(DISTINCT COLUMN16), ANY_VALUE(COLUMN16), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN16), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN17', COUNT_IF(NULLIF(TRIM(COLUMN17), '') IS NULL), COUNT(DISTINCT COLUMN17), ANY_VALUE(COLUMN17), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN17), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN18', COUNT_IF(NULLIF(TRIM(COLUMN18), '') IS NULL), COUNT(DISTINCT COLUMN18), ANY_VALUE(COLUMN18), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN18), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN19', COUNT_IF(NULLIF(TRIM(COLUMN19), '') IS NULL), COUNT(DISTINCT COLUMN19), ANY_VALUE(COLUMN19), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN19), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN20', COUNT_IF(NULLIF(TRIM(COLUMN20), '') IS NULL), COUNT(DISTINCT COLUMN20), ANY_VALUE(COLUMN20), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN20), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
    UNION ALL SELECT 'COLUMN21', COUNT_IF(NULLIF(TRIM(COLUMN21), '') IS NULL), COUNT(DISTINCT COLUMN21), ANY_VALUE(COLUMN21), COUNT_IF(TRY_TO_DATE(NULLIF(TRIM(COLUMN21), '')) IS NOT NULL) FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS
)
SELECT * FROM stats ORDER BY COLUMN_NAME;
```

Use this separate nonblank check for the four provisionally mapped date
positions. It does not mistake numeric encounter, claim, line, or NPI values
for dates:

```sql
SELECT
    COUNT(*) AS TOTAL_ROWS,
    COUNT_IF(NULLIF(TRIM(COLUMN5), '') IS NOT NULL) AS COLUMN5_POPULATED,
    COUNT_IF(NULLIF(TRIM(COLUMN6), '') IS NOT NULL) AS COLUMN6_POPULATED,
    COUNT_IF(NULLIF(TRIM(COLUMN19), '') IS NOT NULL) AS COLUMN19_POPULATED,
    COUNT_IF(NULLIF(TRIM(COLUMN20), '') IS NOT NULL) AS COLUMN20_POPULATED
FROM UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS;
```

The Snowflake results exported on 2026-09-21 show that `COLUMN5`, `COLUMN6`,
`COLUMN19`, and `COLUMN20` are blank in all 53,311,842 claim rows. This does
not block the confirmed-only first run below because confirmed recognition is
intentionally date-independent. It does block any later suspicion/non-
confirmed run: do not treat numeric identifiers as dates or substitute an
ingestion timestamp, notebook run time, or guessed column. V4's later
suspicion event/availability cutoff requires a real mapped source date.

The mapping is deployment-ready only when every logical field used by the
pipeline has an intentional physical column, the source validation cell
passes, and the provisional claim meanings have been confirmed. For the
current claim-only detection setting, the claim entry is enabled and required.
The six current physical tables are independently profile-enabled. If
additional source tables are algorithm-enabled later,
map and validate their logical fields before running.

## 1. Prepare the Snowflake role and namespace

Use an administrator or a deployment role to grant the run role access. Replace
`<V4_ROLE>` and `<V4_WAREHOUSE>`; do not paste credentials into the notebook.

```sql
GRANT USAGE ON WAREHOUSE <V4_WAREHOUSE> TO ROLE <V4_ROLE>;
GRANT USAGE ON DATABASE UHTX_RDDT_CLINICAL_DEV TO ROLE <V4_ROLE>;
GRANT USAGE ON SCHEMA UHTX_RDDT_CLINICAL_DEV.PUBLIC TO ROLE <V4_ROLE>;
GRANT SELECT ON TABLE UHTX_RDDT_CLINICAL_DEV.PUBLIC.CLAIMS TO ROLE <V4_ROLE>;
GRANT SELECT ON TABLE UHTX_RDDT_CLINICAL_DEV.PUBLIC.CENSUS TO ROLE <V4_ROLE>;
GRANT SELECT ON TABLE UHTX_RDDT_CLINICAL_DEV.PUBLIC.ENCOUNTERS TO ROLE <V4_ROLE>;
GRANT SELECT ON TABLE UHTX_RDDT_CLINICAL_DEV.PUBLIC.LABS TO ROLE <V4_ROLE>;
GRANT SELECT ON TABLE UHTX_RDDT_CLINICAL_DEV.PUBLIC.MEDICATIONS TO ROLE <V4_ROLE>;
GRANT SELECT ON TABLE UHTX_RDDT_CLINICAL_DEV.PUBLIC.SURGICAL_HISTORY TO ROLE <V4_ROLE>;
```

The confirmed-only notebook needs database/schema `USAGE`, warehouse `USAGE`,
and `SELECT` on all six current sources so it can build the complete EHR after
CLAIMS-only detection. It does not require `CREATE TABLE` or stage write
privileges.

Use a warehouse sized for the source volume. The metadata snapshot reports
approximately 53 million claim rows, 134 million lab rows, and 56 million
medication rows; start with a small validation run or a restrictive cutoff,
then scale up after query history and row counts are known.

## 2. Upload the V4 package

Use the current Snowflake Workspaces flow. In Snowsight, open **Projects →
Workspaces**, create or open the target Workspace, choose **Upload Folder**,
select the local `v4` folder, and confirm the upload includes the whole folder
tree. Preserve this relative layout:

```text
v4/
  __init__.py
  pipeline.py
  config_loader.py
  runtime_config.py
  requirements.txt
  config/                 # all checked-in JSON configuration
  extraction/
  reasoning/
  output/
  pipeline_steps/
  warehouse/
  RDDT_ATTR_V4_Pipeline.ipynb
  Data Analyze/          # analysis notebooks, read-only
```

Do not upload the local virtual environments or build-only Excel/compiler
assets as runtime dependencies. Keep `new-sample-db/` as reference metadata;
it is not a substitute for the production tables and is not read by the
pipeline.

In the Workspace, open `RDDT_ATTR_V4_Pipeline.ipynb` from the `v4` directory so
the notebook's package discovery resolves the sibling Python modules. If the
notebook is opened from its parent directory, the checked-in bootstrap also
supports that layout. Confirm that `v4/config` is visible before running.

## 3. Configure the notebook environment

Create/select a Snowflake **Warehouse Runtime** notebook session. Do not
select Container Runtime, configure a compute pool, install packages, or run
`pip` for this first run. In particular, do not import, install, or use spaCy
or medSpaCy. The first run reads the exact ICD-10 allow-list from
`config/shared/confirmed_patients.json` and requires only the
Snowflake-provided Snowpark session.

Run this Python preflight cell:

```python
from snowflake.snowpark.context import get_active_session

session = get_active_session()
print(session.sql("SELECT CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA()").collect())
print("Warehouse Runtime and Snowpark session: OK; NLP disabled for first run")
```

## 4. Set the active source mapping

In the pipeline notebook, load the checked-in source configuration. The
notebook now preserves the namespace declared by the active profile by
default; set its single `SOURCE_NAMESPACE_OVERRIDE` variable only for a
deliberate deployment-specific override. The active JSON contains the current
provisional physical names. Confirm or edit those names in this one file
before a production clinical run; do not edit extraction code for a warehouse
rename.

```python
from pathlib import Path
from v4.warehouse.source_schema import load_source_config

config_dir = Path.cwd() / "v4" / "config"  # adjust only if package_dir differs
source_config = load_source_config(config_dir / "source_schema.json")
SOURCE_NAMESPACE_OVERRIDE = None  # e.g. "UHTX_RDDT_CLINICAL_DEV.PUBLIC"
if SOURCE_NAMESPACE_OVERRIDE is not None:
    source_config["namespace"] = SOURCE_NAMESPACE_OVERRIDE
```

The source contract has four independent controls:

* `enabled`: whether the table participates in detection/scoring;
* `required`: whether a missing algorithm-enabled table is a hard failure;
* `profile_enabled`: whether the table is read for final patient EHR profiles;
* `profile_required`: whether a missing profile table is a hard failure.

For the current claim-only validation, set `claim.enabled=true` and
`claim.required=true`; set every other table's `enabled=false`. When a table
is enabled, its `required_columns` must match real physical columns. Mapping a
field to a non-existent or semantically wrong column will either fail source
validation or, worse, produce invalid clinical evidence.

Run the validation before the confirmed-only pass:

```python
from v4.warehouse.source_schema import validate_source_schema

report = validate_source_schema(session, source_config, raise_on_error=False)
print(report.as_dict())
if not report.ok:
    raise RuntimeError("Fix source_schema.json and rerun validation")
```

## 5. Run the confirmed-only first pass

Run the main notebook only after all Data Analyze notebooks have completed and
the total-row/distinct-patient summary is saved. The first pass is deliberately
not the suspicion pipeline:

* query `CLAIMS` only;
* accept only rows whose mapped diagnosis type is ICD-10/ICD-10-CM;
* match only the exact ICD-10 codes in
  `routes.ALL_AMYLOIDOSIS` inside `config/shared/confirmed_patients.json`;
* do not use ICD-9, NLP, clinical notes, event dates, screening cutoffs, or
  non-confirmed scoring;
* create no Snowflake table, view, or stage object.

The configured allow-list is `E85`, `E85.0`, `E85.1`, `E85.2`, `E85.3`,
`E85.4`, `E85.8`, `E85.81`, `E85.82`, `E85.89`, and `E85.9`. Dotted and
undotted representations compare by normalized exact equality; ICD-9 and
unconfigured E85-family values do not match. The read-only query aggregates
directly to one row per patient in `confirmed_profiles_df`. Each profile
includes all matched codes, configured type/subtype, `RISK_LABEL=CONFIRMED`,
`PRIORITY_LABEL=CONFIRMED`, and `DATE_REQUIRED=FALSE`. This is a confirmed-
recognition pass only; it does not assign suspicion tiers or evaluate
non-confirmed patients. A separate read-only hydration phase retrieves every
native row for those confirmed patient IDs from `CENSUS`, `CLAIMS`,
`ENCOUNTERS`, `LABS`, `MEDICATIONS`, and `SURGICAL_HISTORY`. These tables do
not affect confirmation. No Snowflake object is created.

## 6. Inspect and retain outputs

The compact index and complete JSON-ready profiles are available in notebook
memory:

```python
display(confirmed_profiles_df)
display(confirmed_patient_profiles[0])
```

No `AMY_V4_ROUTER_OUTPUT`, detected/suspicion output, or non-confirmed output is
created in this first pass.

The notebook writes three workspace-local review files:

```text
confirmed_amyloidosis_profiles.csv
confirmed/confirmed_amyloidosis_patient_profiles.csv
confirmed/confirmed_amyloidosis_patient_profiles.jsonl
```

`confirmed_amyloidosis_profiles.csv` is the compact one-row-per-patient
summary. The CSV inside `confirmed` is an index with the claim-row and
matching-evidence counts. The JSONL contains one complete JSON object per
patient. Each object includes every native row from every configured available
EHR table under `ehr.records_by_table` and the exact rows that caused
confirmation under
`clinical_rationale.matched_claim_evidence`. One JSONL line equals one patient
profile.

Download the workspace-local profile files before the notebook session is
discarded if a local review copy is needed. Do not upload them to a stage and
do not copy results into temporary, permanent, transient, shared, or view
objects as part of this run. The notebook creates no Snowflake result object.

## 7. Run the schema-analysis notebooks

Run all notebooks in `v4/Data Analyze/` before the confirmed pass, in separate
Warehouse Runtime notebook sessions as needed. In each notebook, execute all
cells in order and save the displayed `TOTAL_ROWS` and `DISTINCT_PATIENTS`
result. The main confirmed-only notebook reports only the currently enabled
CLAIMS source in its detection summary, then queries only `profile_enabled`
tables for the confirmed patients' EHR. It does not replace the separate
analysis notebooks.
The current-schema override cells point to
`UHTX_RDDT_CLINICAL_DEV.PUBLIC`; untouched legacy copies are retained under
`v4/Data Analyze/legacy_schema/`:

```text
census_data_analysis.ipynb
claim_data_analysis.ipynb
encounter_visit_data_analysis.ipynb
lab_data_analysis.ipynb
medication_data_analysis.ipynb
medical_history_data_analysis.ipynb
surgical_history_data_analysis.ipynb
family_history_data_analysis.ipynb
clinical_note_data_analysis.ipynb
social_history_data_analysis.ipynb
schema_counts_summary.ipynb
```

The supplied current database snapshot has no medical-history,
family-history, clinical-note, or social-history table. Those four active
notebooks return an explicit `SOURCE_AVAILABLE = FALSE` report and then query
an empty derived relation, so a run-all does not attempt to read a missing
table. The analysis notebooks are read-only and do not configure or run the
clinical pipeline.

At the end of each active analysis notebook, run the **Export all SQL results
to Excel** cell. It creates this workspace-local file and displays a download
link:

```text
v4/output/<notebook_name>_outputs.xlsx
```

Each workbook contains `Run Summary` plus one worksheet per SQL result cell.
The export cell reruns those read-only SQL cells so it can capture their full
tabular outputs; notebook UI grids cannot be recovered after the fact. Python
setup/configuration cells do not produce analysis tables and are not converted
into separate worksheets. A failed SQL result is recorded and export continues.
If a result exceeds Excel's per-sheet row limit, the workbook records that the
sheet was truncated.

These `.xlsx` files exist only in the Workspace/notebook file system. The
exporter does not create a Snowflake table, stage, view, or other database
object, and it uses only the Warehouse Runtime, Snowpark, and the Python
standard library to build the workbook. The final cell uses the Notebook's
built-in Streamlit download control, with an IPython file-link fallback; it
does not install anything. Download the workbooks before ending the session,
and handle them as PHI-bearing files.

## 8. Required post-run checks

Save the following with the confirmed-pass run ID, active mapping version, and
config hash:

1. Total rows and distinct patient counts from every Data Analyze notebook.
2. The confirmed profile table and row-level evidence table counts.
3. The exact active `source_schema.json` and confirmed-patient config hash.
4. The query history/warehouse used and the Warehouse Runtime notebook session.

Stop and correct the mapping if any analysis notebook cannot report its table,
if required columns are missing, or if the confirmed table is unexpectedly
empty. The blank date finding must be resolved before enabling the later
suspicion/non-confirmed pipeline, but is not a reason to block this confirmed-
only pass.

# Notebook-generated output files

The schema-analysis notebooks write their downloadable Excel workbooks into
this directory at run time:

```text
<notebook_name>_outputs.xlsx
```

Each workbook contains a `Run Summary` worksheet and one worksheet for every
SQL result cell in that notebook. The workbooks are local files in the
Snowflake Workspace/notebook file system. They are not Snowflake database
tables, stages, views, or shared objects.

The exporter assembles the ZIP-based XLSX package in a seekable temporary
stream before copying it into this directory. This avoids `OSError: [Errno 95]
Operation not supported` on Snowflake's mounted Workspace filesystem.

Download the workbook from the button displayed by the notebook's final cell
before deleting the Workspace or otherwise discarding its files. These files
can contain patient-level data and are intentionally ignored by Git through
the repository-wide `*.xlsx` rule.

The CLAIMS-only detection notebook writes three workspace-local files
under `rddt_v4_exports`:

```text
confirmed_amyloidosis_profiles.csv
confirmed/confirmed_amyloidosis_patient_profiles.csv
confirmed/confirmed_amyloidosis_patient_profiles.jsonl
```

The first CSV is the compact one-row-per-patient summary. The CSV inside
`confirmed` is an index that also reports claim-row and confirming-evidence
counts. The JSONL contains one complete JSON object per confirmed patient. It
preserves every native row from every current table marked `profile_enabled`
under `ehr.records_by_table`, while keeping the exact ICD-10 claim rows that
caused confirmation under `clinical_rationale.matched_claim_evidence`. These
are Workspace files only; the notebook does not create a Snowflake table,
view, or stage.

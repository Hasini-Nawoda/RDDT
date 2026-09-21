# V4 build tools

This directory contains the offline tooling used to correct, audit, validate,
and compile the clinical workbook into the deterministic JSON configuration
packages checked into `v4/config/`.

It is not part of the Snowflake deployment. The Snowflake runtime must not
read an Excel workbook or import these modules. The runtime consumes only the
compiled JSON files under `../v4/config/`. Atoms and terminology are emitted
once under `config/shared/`; signal construction and verdict logic are emitted
under `config/phenotypes/<phenotype>/`.

Contents:

- `source/ATTRv_Normalized_Clinical_Filtering_Config_v3.xlsx`: corrected
  workbook source of truth used during the build.
- `source/ATTRwt_Normalized_Clinical_Filtering_Config_FINAL.xlsx`: corrected
  ATTRwt workbook source of truth used by `compile_attrwt_from_normalized.py`.
- `compile_attrwt_from_normalized.py`: deterministic ATTRwt compiler that
  reuses the shared atom universe and emits only runtime clinical JSON.
- `terminology_normalization.py`: shared explicit code-matching and provenance
  policy used by both workbook compilers.
- `migrate_combined_terminology.py`: applies the combined ATTRv + ATTRwt
  terminology registry to `v4/config/shared/atoms/` and emits a migration
  report with safe-range and unresolved-range classifications.
- `validate_combined_terminology.py`: validates explicit `match_mode`, safe
  range expansions, LOINC exactness, provenance, and procedure mapping roles.

Workbook coordinates, hashes, cell formatting, and other authoring metadata are
kept only in build-time audit reports; they are not emitted into runtime atom
JSON.
- `config_compile.py` and `config_validation.py`: deterministic compiler and
  structural workbook validation.
- `tools/`: workbook correction, audit, compilation, and bundle validation
  commands.
- `validation/complex_patient_fixture.json`: the original hardened end-to-end
  patient, including long-clause experiencer/polarity and relative-date cases.
- `validation/adversarial_patient_suite.json`: nine additional multi-row EHR
  patients that stress repeated mentions, corrected assertions, family/patient
  switches, copied-forward history, structured/text conflict, future plans,
  and multiple dates in one note.
- `validation/run_complex_patient.py` and `validation/run_adversarial_suite.py`:
  local combined-pipeline validation runners; these are not Snowflake runtime
  dependencies.
- `workbook_audit_artifacts/`: preserved audit JSON, workbook copies, and
  rendered previews.

From the repository root, create/use the build virtual environment and run:

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\Activate.ps1
python -m pip install -r v4_build_tools\requirements-build.txt
python v4_build_tools\tools\audit_attrv_workbook.py v4_build_tools\source\ATTRv_Normalized_Clinical_Filtering_Config_v3.xlsx
python v4_build_tools\tools\compile_workbook.py
python v4_build_tools\migrate_runtime_layout.py
python v4_build_tools\migrate_combined_terminology.py
python v4_build_tools\validate_combined_terminology.py
```

The compiler writes a flat intermediate bundle to `v4_build_tools/compiled_flat`
(or the path supplied with `--output-dir`). The migration step writes the
categorized deployable JSON bundle to `v4/config/`. Before replacing that
checked-in runtime bundle, review the validation report before deployment.

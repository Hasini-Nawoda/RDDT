# V4 implementation notes

## Build-time source workbook (not deployed)

- Workbook: `../v4_build_tools/source/ATTRv_Normalized_Clinical_Filtering_Config_v3.xlsx`
- Workbook SHA-256: `1579093e7e15c64e3dd660c308a036893a6630d2019c8a227552d5953033560f`
- Signals: 39
- Atoms: 103
- Terminology rows: 1,260
- NLP terminology rows: 874
- Atoms with NLP terminology: 103 of 103

## Generated ATTRV runtime counts

- Signal metadata rows: 39
- Signal-rule rows: 39
- Signal-to-atom connector rows: 100
- Shared runtime atoms: 103

The old V03/V06 synthetic-signal rows were removed. Their unchanged clinical
logic now lives in V_RULE_V03/V_RULE_V06 as nested combinations, so all 15
routes produce a single patient-level verdict through one resolver.

The V3 correction normalized explicit structured code tokens already present in the supplied workbook, moved literal non-code phrases to NLP terminology, removed reviewer commentary/placeholders and exact duplicates, and added the missing `ROUTE_ONLY` controlled-vocabulary value. It did not add or externally look up codes.

## Clinical validation boundary

The workbook passes structural, cross-sheet, controlled-vocabulary, relationship, duplicate, and executable terminology-shape checks. This makes it ready for implementation and deterministic compilation. It does not replace terminology accuracy review, retrospective performance measurement, patient-level clinical review, or prospective validation before clinical deployment.

## Runtime dependencies

- Python 3.10 or newer
- `openpyxl` is build-only and is intentionally excluded from the runtime;
  see `../v4_build_tools/requirements-build.txt`.
- Snowpark Python in the Snowflake workspace
- spaCy for token-aware `PhraseMatcher`
- medSpaCy, or a tested medSpaCy-compatible clinical context processor, for negation, uncertainty, experiencer, and clinical-context attributes

The runtime does not substitute regex, SQL `LIKE`/`ILIKE`, or Python substring matching when NLP dependencies are absent.

## Output and download

Snowflake output objects are session temporary tables prefixed `AMY_V4_`. The notebook previews `AMY_V4_ROUTER_OUTPUT`, which Snowflake can download from the result grid. The Python profile exporter also writes a local-runtime JSONL profile file and trace-free CSV index. Proprietary traces are excluded from export by default.

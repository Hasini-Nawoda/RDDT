# V4 configuration layout

The phenotype registry at `config/phenotype_registry.json` identifies the
runtime phenotype packages. The generated runtime package is intentionally
minimal: workbook/compiler provenance stays in the build artifacts and is not
duplicated in deployable clinical JSON.

For ATTRV, the generated files are:

```text
config/phenotypes/ATTRV/
  signals.json         # all 39 real signal rows; source specialty is metadata
  signal_rules.json    # signal/guardrail ASTs
  signal_atoms.json    # 100 clean signal-to-atom connector rows
  combinations.json
  buckets.json
  priority_policies.json
  guardrails.json      # compact routes with rule_ref to signal_rules
```

Shared extraction atoms remain partitioned by specialty under
`config/shared/atoms/`. The ATTRV signal catalog is not specialty-partitioned.
Each catalog row preserves `source_specialty` as metadata; reasoning buckets
and independence are defined by the workbook fields and rule ASTs.

The 39 catalog rows classify as 31 direct signals, seven guardrails, and one
disabled do-not-use row (V36). `signals.json` contains
metadata only; `signal_rules.json` is the rule authority; and
`signal_atoms.json` contains only runtime connector fields. The shared atom
catalog contains 103 atoms. `combinations.json` contains all 15 patient-level
routes; V_RULE_V03 and V_RULE_V06 carry nested signal-group logic in that same
file and are resolved by the same matcher as the flat combinations.

Regenerate these files from the corrected workbook build artifacts. Do not
hand-edit generated JSON.

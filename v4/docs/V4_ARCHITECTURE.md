# RDDT V4 architecture

## Authority and deployment boundary

The corrected workbook is a build-time source maintained under
`../v4_build_tools/source/`. The runtime consumes only generated JSON under
`config/`; legacy folders and build tools are not runtime dependencies.

The deployable configuration is:

```text
config/
  phenotype_registry.json
  shared/
    atoms/*.json                 # specialty-partitioned shared atoms
  phenotypes/
    ATTRV/
      signals.json               # one 39-row phenotype-level catalog
      signal_rules.json          # structured rules and blockers
      signal_atoms.json          # 100 runtime signal-to-atom connectors
      combinations.json
      buckets.json
      priority_policies.json
      guardrails.json             # routes referencing signal_rules
```

The ATTRV signal catalog preserves source specialty only as metadata. It does
not derive reasoning buckets or independence from specialty. `signals.json`
uses `config_action` and `entity_type` to distinguish the 31 direct signals,
seven guardrails, and disabled V36 do-not-use row.

`signal_rules.json` is authoritative for signal and guardrail nested ASTs,
including blockers. V_RULE_V03 and V_RULE_V06 are nested entries inside
`combinations.json`, so cross-bucket logic has one execution authority.
`signal_atoms.json` is limited to signal ID, atom ID, mapping executability,
evidence mode, experiencer, stage, and required qualifiers. The shared atom
catalog contains 103 atoms referenced by the remaining connectors, active rule
ASTs, blockers, and guardrail rules.

## Runtime flow

```text
checked-in generated JSON bundle
  -> validate source tables and columns
  -> retrieve structured-code candidates and broad text-bearing records
  -> spaCy PhraseMatcher + medSpaCy clinical context
  -> long-form source events and atom matches
  -> qualified evidence with TRUE/FALSE/UNKNOWN and lineage
  -> normalized signal-rule trees and blockers from signal_rules.json
  -> bucket state
  -> one combination engine for flat and nested rules with lineage/dedup independence
  -> categorical priority and parallel guardrail routes
  -> exactly one ATTRv patient-level verdict and phenotype-generic router row
  -> flagged-patient profiles and local download payloads
```

Candidate retrieval is an efficiency stage, not positive evidence. Structured
codes use only workbook code values and configured exact/prefix/range
semantics. NLP never uses regex or simple substring matching. Missing NLP
components cause an auditable gap, not a fallback match.

## Evidence and lineage

The source-event layer retains patient, encounter, source table/field, source
record, event and availability dates, specialty metadata, code/text/result
values, and deterministic source-row identity. Atom matches and qualified
evidence carry source lineage. Source specialty remains metadata; it never
substitutes for a reasoning bucket.

Missing qualifiers remain `UNKNOWN`. Named combinations use backtracking so
alternative witnesses remain available until a valid independent assignment is
found. One source lineage or canonical dedup group cannot satisfy two
independent requirements.

## Phenotype extensibility

The router contract has six stable phenotype slots:

1. `GENERAL_AMYLOID`
2. `ATTR_COMMON`
3. `ATTRV`
4. `ATTRWT`
5. `AL`
6. `AA`

This delivery loads only the ATTRv workbook. Other phenotype rows are
`NOT_EVALUATED / CONFIG_NOT_LOADED`, never false or inferred from ATTRv
guardrails.

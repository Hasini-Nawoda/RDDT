# RDDT V4 architecture

## Authority and deployment boundary

The corrected workbook is a build-time source maintained under
`../v4_build_tools/source/`. The runtime consumes only generated JSON under
`config/`; legacy folders and build tools are not runtime dependencies.

The deployable configuration is:

```text
config/
  source_schema.json             # table toggles + logical-to-physical column mapping
  phenotype_registry.json
  shared/
    confirmed_patients.json      # all-amyloidosis ICD-10 + ATTR/AL contracts together
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
    ATTRWT/                       # same runtime contract, WT clinical rules
```

The ATTRV signal catalog preserves source specialty only as metadata. It does
not derive reasoning buckets or independence from specialty. `signals.json`
uses `config_action` and `entity_type` to distinguish the 31 direct signals
from guardrail and disabled/do-not-use catalog rows.

`signal_rules.json` is authoritative for signal and guardrail nested ASTs,
including blockers. V_RULE_V03 and V_RULE_V06 are nested entries inside
`combinations.json`, so cross-bucket logic has one execution authority.
`signal_atoms.json` is limited to signal ID, atom ID, mapping executability,
evidence mode, experiencer, stage, and required qualifiers. The shared atom
catalog contains 149 atoms referenced across the loaded ATTRv and ATTRwt
connectors, active rule ASTs, blockers, and guardrail rules.

## Runtime flow

The immediate first-run path is deliberately smaller than the full phenotype
flow below:

```text
CLAIMS COLUMN7/COLUMN8 (ICD-10 type/code only)
  -> exact normalized join to routes.ALL_AMYLOIDOSIS
  -> session TEMPORARY row-level evidence table
  -> session TEMPORARY deduplicated patient-profile table
  -> stop; do not run suspicion scoring
```

This path ignores dates and evaluates no non-confirmed patients. The complete
future suspicion flow remains:

```text
checked-in generated JSON bundle
  -> validate source tables and columns
  -> retrieve the union of ATTRv, ATTRwt, AL, and confirmed-patient candidates once
  -> create long-form source events once
  -> pre-screen known ATTR/amyloidosis and known AL recognition
       -> workspace-only confirmed/known ATTR collection and profile
       -> workspace-only confirmed AL collection and profile
       -> remove patient from early-detection scoring
  -> match shared atoms once with spaCy PhraseMatcher + medSpaCy context
  -> qualify shared evidence once with TRUE/FALSE/UNKNOWN and lineage
  -> evaluate ATTRv, ATTRwt, and AL rule trees for every remaining patient
       -> one ATTRv phenotype verdict
       -> one ATTRwt phenotype verdict
       -> one AL phenotype verdict
       -> cross-phenotype guardrails remain parallel routes only
  -> aggregate the two real phenotype verdicts using their highest suspicion
  -> one combined ATTR patient profile and suspicion-tiered output
  -> separate AL-detected profile and output for AL phenotype passes
  -> confirmed/ and suspicion-tiered detected/ profile downloads
```

Candidate retrieval is an efficiency stage, not positive evidence. Structured
codes use only workbook code values and configured exact/prefix/range
semantics. NLP never uses regex or simple substring matching. Missing NLP
components cause an auditable gap, not a fallback match.

Source tables remain read-only. When materialization is requested, V4 creates
only session-scoped `TEMPORARY` `AMY_V4_*` tables, which are invisible to other
sessions and disappear at session end. It never creates permanent, transient,
shared, view, or stage output objects.

## Evidence and lineage

The source-event layer retains patient, encounter, source table/field, source
record, event and availability dates, specialty metadata, code/text/result
values, and deterministic source-row identity. Atom matches and qualified
evidence carry source lineage. Source specialty remains metadata; it never
substitutes for a reasoning bucket.

Each configured PhraseMatcher span becomes its own evidence candidate, even
when the same atom is mentioned repeatedly in one source row. medSpaCy context
is evaluated in the target's assertion clause so family history, negation, and
uncertainty from an earlier clause do not leak into a later corrected
assessment. Comma-delimited finding lists remain intact; a comma becomes a
boundary only when the following tokens form a new predicated assertion.

For narrative matches, `available_date` remains the warehouse/source row date.
The evidence `event_date` is the mention-level clinical date when a supported
tokenized relative or year expression can be resolved. Temporal selection
prefers an anchor preceding the finding, cannot cross contrast/sentence
boundaries, and cannot reach backward from a later dated clause. Planned or
future findings are retained as `UNKNOWN` evidence.

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

This delivery loads ATTRv and ATTRwt. Other phenotype rows are `NOT_EVALUATED /
CONFIG_NOT_LOADED`, never false or inferred from a different phenotype's
guardrails. Both loaded phenotypes use the same extraction, known-patient
exclusion, signal, combination, router, priority-label, and profile engines.

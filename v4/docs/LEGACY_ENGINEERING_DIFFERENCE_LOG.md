# V4 legacy engineering difference log

This log records engineering mechanisms inspected while building the ATTRv V4 pipeline. The corrected normalized workbook is the only clinical source for V4.

## Source schema adapter

Legacy file/module: `specialty_configs_v3/pipeline.py::default_source_config`

Engineering mechanism inspected: physical Snowflake table and quoted column mappings for census, encounters, claims, labs, medical history, surgical history, family history, and clinical notes.

Old engineering limitation: the same module also enables legacy pipeline behavior and defines optional social-history and medication sources that are outside the current V4 scope.

V4 engineering decision: preserve only the physical source contract in an isolated schema module; keep social history and medication disabled; validate exact required table/column names before processing.

Clinical data copied from legacy: NONE

## Session-scoped warehouse objects

Legacy file/module: `specialty_configs_v3/rddt_attr_sql.py`

Engineering mechanism inspected: Snowpark execution, identifier quoting, source validation, and session `TEMPORARY TABLE` materialization.

Old engineering limitation: candidate retrieval and evidence mirrors are tied to legacy clinical vocabulary and legacy table shapes.

V4 engineering decision: retain only generic SQL/session mechanics. Generate candidate and evidence rows from the compiled workbook, and reject any non-temporary V4 table creation.

Clinical data copied from legacy: NONE

## Candidate retrieval

Legacy file/module: `specialty_configs_v3/atoms.py` and `specialty_configs_v3/rddt_attr_sql.py`

Engineering mechanism inspected: restricting expensive downstream work to a candidate patient set.

Old engineering limitation: the wide net is built from legacy atom JSON and free-text SQL matching, which would leak obsolete clinical content and bypass contextual NLP.

V4 engineering decision: compile structured codes and literal NLP terms only from the corrected workbook. Structured values route to exact/prefix/range planners. NLP values route to spaCy/medSpaCy phrase matching and context processing, never regex or SQL substring matching.

Clinical data copied from legacy: NONE

## Evidence representation

Legacy file/module: `specialty_configs_v3/atoms.py`, `specialty_configs_v3/buckets.py`, and `specialty_configs_v3/temporal.py`

Engineering mechanism inspected: staged evidence tables and later phenotype evaluation.

Old engineering limitation: early patient-level/bucket flattening can discard alternative witnesses, event dates, and component lineage needed for qualified rules and independence checks.

V4 engineering decision: preserve long-form source, atom-match, and qualified-evidence events with stable source lineage, support/context lineage, event/availability dates, experiencer, polarity, certainty, attributes, and workbook provenance.

Clinical data copied from legacy: NONE

## Three-valued predicates

Legacy file/module: `RDDT-codexversion/v3/reasoning.py`

Engineering mechanism inspected: generic `TRUE`/`FALSE`/`UNKNOWN` propagation and separation of support from context lineage.

Old engineering limitation: the legacy predicate model is bound to older schemas and clinical configuration.

V4 engineering decision: implement the same generic truth algebra against V4 workbook-compiled signal rule trees. Missing qualifiers remain `UNKNOWN`; absent records are not converted to clinical negatives.

Clinical data copied from legacy: NONE

## Combination witness allocation

Legacy file/module: `RDDT-codexversion/v3/match.py`

Engineering mechanism inspected: backtracking allocation with independent support lineage and canonical dedup groups.

Old engineering limitation: the requirement model does not directly represent every normalized workbook restriction, including workbook-specific allowed signals and requirement-scoped context permission.

V4 engineering decision: retain the generic backtracking approach while compiling candidates from `Combination_Requirements`, `Requirement_Buckets`, `Requirement_Tiers`, and `Requirement_Signals`. Enforce context permission per requirement and return a duplicate-lineage hold when only a relaxed assignment could pass.

Clinical data copied from legacy: NONE

## Router output

Legacy file/module: `specialty_configs_v3/router.py`

Engineering mechanism inspected: a stable patient-level integration surface.

Old engineering limitation: the legacy router is coupled to legacy phenotype outputs and may expose internal logic together with review-facing results.

V4 engineering decision: emit a phenotype-generic router row. Keep the patient medical profile and clinical rationale separate from a removable proprietary trace payload containing rule, bucket, and witness-assignment internals.

Clinical data copied from legacy: NONE

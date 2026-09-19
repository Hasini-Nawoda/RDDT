# V4 deployable pipeline stages

The Snowflake runtime is intentionally readable as a numbered sequence. The
generic entry point is `v4.pipeline.run_phenotype_v4_pipeline`; it loads one
named phenotype package and delegates every clinical/runtime boundary to the
corresponding `v4.pipeline_steps` module. The current notebook may continue to
call the `run_attrv_v4_pipeline` compatibility wrapper.

| Stage | Runtime module | Responsibility |
| --- | --- | --- |
| 01 | `step_01_source_validation.py` | Load compiled config and validate the declared warehouse source contract. |
| 02 | `step_02_candidate_retrieval.py` | Retrieve candidate patients from structured values and PhraseMatcher NLP spans. |
| 03 | `step_03_source_events.py` | Normalize source rows into lineage-preserving events. |
| 04 | `step_04_atom_matching.py` | Match configured atoms to source events. |
| 05 | `step_05_evidence_qualification.py` | Apply temporal, negation, experiencer, and contextual qualification. |
| 06 | `step_06_signal_evaluation.py` | Evaluate signal rule groups. |
| 07 | `step_07_bucket_evaluation.py` | Derive reasoning-bucket state from established signals. |
| 08 | `step_08_combination_matching.py` | Evaluate flat and nested combination rules in one engine. |
| 09 | `step_09_priority_guardrails.py` | Evaluate guardrails before routing. |
| 10 | `step_10_router.py` | Select exactly one deterministic patient-level verdict. |
| 11 | `step_11_patient_profiles.py` | Build flagged patient profiles and optional local exports. |

The modules are orchestration boundaries, not a second clinical source of
truth. Clinical atoms, terminology, signals, combinations, priorities, and
guardrails continue to come only from `v4/config`. The compiler and
workbook correction tools are outside this deployable runtime contract.

Runtime persistence is session-scoped only. Intermediate materialization uses
`CREATE OR REPLACE TEMPORARY TABLE`; no permanent or transient warehouse table
is created.

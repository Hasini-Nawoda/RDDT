# V4 deployable pipeline stages

The urgent first run does **not** execute the numbered suspicion stages below.
`RDDT_ATTR_V4_Pipeline.ipynb` performs only table/patient counts and exact
CLAIMS ICD-10 matching through `routes.ALL_AMYLOIDOSIS`, writes two
session-scoped temporary confirmed-patient tables, and stops. Dates, ICD-9,
NLP, and non-confirmed patients are out of scope for that run.

The Snowflake runtime is intentionally readable as a numbered sequence. The
production entry point is `v4.pipeline.run_attr_v4_pipeline`; it always loads
both ATTRv and ATTRwt. Candidate retrieval, source normalization, known-patient
exclusion, atom matching, and evidence qualification happen once. The shared
qualified evidence is then evaluated by both phenotype configurations before
one combined ATTR profile is produced.

| Stage | Runtime module | Responsibility |
| --- | --- | --- |
| 01 | `step_01_source_validation.py` | Load compiled config and validate the declared warehouse source contract. |
| 02 | `step_02_candidate_retrieval.py` | Retrieve the union of ATTRv, ATTRwt, and known-ATTR candidates from structured values and broad text-bearing rows. |
| 03 | `step_03_source_events.py` | Normalize source rows into lineage-preserving events. |
| 03b | `step_03b_known_attr_exclusion.py` | Export known patients separately and remove them before either phenotype is evaluated. |
| 04 | `step_04_atom_matching.py` | Match configured atoms to source events. |
| 05 | `step_05_evidence_qualification.py` | Apply temporal, negation, experiencer, and contextual qualification. |
| 06 | `step_06_signal_evaluation.py` | Evaluate ATTRv and ATTRwt signal rule groups from the same evidence. |
| 07 | `step_07_bucket_evaluation.py` | Derive each phenotype's reasoning-bucket state. |
| 08 | `step_08_combination_matching.py` | Evaluate each phenotype's flat and nested combination rules in one engine. |
| 09 | `step_09_priority_guardrails.py` | Evaluate phenotype guardrails and retain cross-phenotype references as parallel routes. |
| 10 | `step_10_router.py` | Select exactly one deterministic verdict for each phenotype. |
| 11 | `step_11_patient_profiles.py` | Combine both verdicts using their highest suspicion and build one ATTR profile/export. |

The modules are orchestration boundaries, not a second clinical source of
truth. Clinical atoms, terminology, signals, combinations, priorities, and
guardrails continue to come only from `v4/config`. The compiler and
workbook correction tools are outside this deployable runtime contract.

Snowflake source access is read-only. The runtime may materialize only
session-scoped `TEMPORARY` `AMY_V4_*` tables when
`persist_intermediates=True`; it does not create permanent, transient, shared,
view, or stage objects.

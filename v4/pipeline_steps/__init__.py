"""Numbered deployable runtime stages for the V4 ATTRv pipeline.

The numbered modules are the readable boundary of the Snowflake runtime.  The
lower-level engines in :mod:`v4` remain reusable implementation details; this
package makes the execution order explicit and auditable.
"""

STAGE_ORDER = (
    "step_01_source_validation",
    "step_02_candidate_retrieval",
    "step_03_source_events",
    "step_04_atom_matching",
    "step_05_evidence_qualification",
    "step_06_signal_evaluation",
    "step_07_bucket_evaluation",
    "step_08_combination_matching",
    "step_09_priority_guardrails",
    "step_10_router",
    "step_11_patient_profiles",
)

__all__ = ["STAGE_ORDER"]

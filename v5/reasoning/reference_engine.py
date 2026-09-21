"""Pure-Python deterministic reference evaluator for V4 parity validation.

This is an orchestration wrapper around the same config-driven stages used by
the production pipeline.  It contains no second clinical configuration.
"""
from __future__ import annotations

from typing import Any, Iterable

from .bucket_engine import build_bucket_state
from .guardrails import evaluate_guardrails
from .match_engine import match_combinations
from .router import route_results
from .signal_engine import evaluate_signals
from .reasoning_utils import configured_phenotype


def evaluate_reference(config: Any, evidence: Iterable[Any], *, patient_id: Any = None, phenotype: str | None = None, run_id: Any = None, config_hash: str | None = None, implementation_version: str = "v4-reference") -> dict[str, Any]:
    phenotype = configured_phenotype(config, phenotype)
    evidence_rows = list(evidence)
    signal_hits = evaluate_signals(config, evidence_rows, patient_id=patient_id, phenotype=phenotype)
    bucket_state = build_bucket_state(config, signal_hits, patient_id=patient_id, phenotype=phenotype)
    combination_hits = match_combinations(config, signal_hits, bucket_state=bucket_state, patient_id=patient_id, phenotype=phenotype)
    guardrail_hits = evaluate_guardrails(config, evidence_rows, patient_id=patient_id, phenotype=phenotype)
    results, router = route_results(config, combination_hits, guardrail_hits=guardrail_hits, patient_id=patient_id, phenotype=phenotype, run_id=run_id, config_hash=config_hash, implementation_version=implementation_version)
    return {
        "signal_hits": signal_hits,
        "bucket_state": bucket_state,
        "combination_hits": combination_hits,
        "guardrail_hits": guardrail_hits,
        "phenotype_results": results,
        "router_output": router,
    }


run_reference = evaluate_reference
run = evaluate_reference

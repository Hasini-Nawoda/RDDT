"""Step 09 — evaluate guardrails before single-verdict routing."""

from typing import Any, Iterable

from ..reasoning.guardrails import evaluate_guardrails


def evaluate_guardrails_stage(config: Any, evidence: Iterable[Any], *, patient_id: Any, phenotype: str) -> list[dict[str, Any]]:
    return list(evaluate_guardrails(config, list(evidence), patient_id=patient_id, phenotype=phenotype))


__all__ = ["evaluate_guardrails_stage"]

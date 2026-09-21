"""Step 06 — evaluate configured signal rule groups from qualified evidence."""

from typing import Any, Iterable

from ..reasoning.signal_engine import evaluate_signals


def evaluate_signals_stage(
    config: Any,
    evidence: Iterable[Any],
    *,
    patient_id: Any,
    phenotype: str,
    evaluation_mode: str = "STRICT",
) -> list[dict[str, Any]]:
    return list(evaluate_signals(
        config,
        list(evidence),
        patient_id=patient_id,
        phenotype=phenotype,
        evaluation_mode=evaluation_mode,
    ))


__all__ = ["evaluate_signals_stage"]

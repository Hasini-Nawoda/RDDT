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
    birth_date: Any = None,
) -> list[dict[str, Any]]:
    return list(evaluate_signals(
        config,
        list(evidence),
        patient_id=patient_id,
        phenotype=phenotype,
        evaluation_mode=evaluation_mode,
        birth_date=birth_date,
    ))


__all__ = ["evaluate_signals_stage"]

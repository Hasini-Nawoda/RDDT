"""Step 08 — evaluate all flat and nested combinations in one engine."""

from typing import Any, Iterable

from ..reasoning.match_engine import match_combinations


def match_combinations_stage(
    config: Any,
    signal_hits: Iterable[Any],
    bucket_state: Iterable[Any],
    *,
    patient_id: Any,
    phenotype: str,
    evaluation_mode: str = "STRICT",
) -> list[dict[str, Any]]:
    return list(match_combinations(
        config,
        list(signal_hits),
        bucket_state=list(bucket_state),
        patient_id=patient_id,
        phenotype=phenotype,
        evaluation_mode=evaluation_mode,
    ))


__all__ = ["match_combinations_stage"]

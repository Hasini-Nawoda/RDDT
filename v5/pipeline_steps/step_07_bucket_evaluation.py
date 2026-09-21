"""Step 07 — derive bucket state from established signal outputs."""

from typing import Any, Iterable

from ..reasoning.bucket_engine import build_bucket_state


def evaluate_buckets_stage(config: Any, signal_hits: Iterable[Any], *, patient_id: Any, phenotype: str) -> list[dict[str, Any]]:
    return list(build_bucket_state(config, list(signal_hits), patient_id=patient_id, phenotype=phenotype))


__all__ = ["evaluate_buckets_stage"]

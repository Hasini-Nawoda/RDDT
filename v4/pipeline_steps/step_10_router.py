"""Step 10 — choose exactly one deterministic patient-level phenotype verdict."""

from typing import Any, Iterable

from ..reasoning.router import route_results


def route_stage(config: Any, combination_hits: Iterable[Any], guardrail_hits: Iterable[Any], *, patient_id: Any, phenotype: str, run_id: Any, config_hash: str, implementation_version: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return route_results(config, list(combination_hits), guardrail_hits=list(guardrail_hits), patient_id=patient_id, phenotype=phenotype, run_id=run_id, config_hash=config_hash, implementation_version=implementation_version)


__all__ = ["route_stage"]

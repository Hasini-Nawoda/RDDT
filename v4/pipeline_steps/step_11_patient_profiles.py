"""Step 11 — build trace-separable patient profiles and local exports."""

from pathlib import Path
from typing import Any, Iterable, Mapping

from ..output.patient_profile import build_patient_profile, export_profiles, flagged_patient_ids


def build_profiles(router_output: Iterable[Any], *, config: Any, phenotype: str, source_events: Iterable[Any], evidence_events: Iterable[Any], signal_hits: Iterable[Any], bucket_state: Iterable[Any], combination_hits: Iterable[Any], guardrail_hits: Iterable[Any], demographics: Mapping[str, Mapping[str, Any]] | None, run_id: str, include_proprietary_trace: bool = True) -> list[dict[str, Any]]:
    router_rows = list(router_output)
    events = list(source_events)
    evidence = list(evidence_events)
    signals = list(signal_hits)
    buckets = list(bucket_state)
    combinations = list(combination_hits)
    guards = list(guardrail_hits)
    demographics = demographics or {}
    return [build_patient_profile(patient_id, config=config, screening_target=phenotype, router_rows=router_rows, source_events=events, evidence_events=evidence, signal_hits=signals, bucket_state=buckets, combination_hits=combinations, guardrail_hits=guards, demographics=demographics.get(patient_id), include_proprietary_trace=include_proprietary_trace, run_id=run_id) for patient_id in flagged_patient_ids(router_rows, phenotype=phenotype)]


def export_profile_files(profiles: Iterable[Mapping[str, Any]], output_dir: str | Path | None, *, phenotype: str) -> dict[str, str]:
    basename = f"{phenotype.lower()}_flagged_patient_profiles"
    return export_profiles(list(profiles), output_dir, basename=basename) if output_dir is not None else {}


__all__ = ["build_profiles", "export_profile_files"]

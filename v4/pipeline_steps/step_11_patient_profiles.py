"""Step 11 — build trace-separable patient profiles and local exports."""

from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..output.patient_profile import (
    build_known_al_profile,
    build_known_attr_profile,
    build_patient_profile,
    export_al_detected_profiles,
    export_known_al_profiles,
    export_known_attr_profiles,
    export_profiles,
    flagged_al_detected_patient_ids,
    flagged_attr_patient_ids,
    flagged_patient_ids,
)


def build_profiles(router_output: Iterable[Any], *, config: Any, phenotype: str, source_events: Iterable[Any], evidence_events: Iterable[Any], signal_hits: Iterable[Any], bucket_state: Iterable[Any], combination_hits: Iterable[Any], guardrail_hits: Iterable[Any], demographics: Mapping[str, Mapping[str, Any]] | None, run_id: str, include_proprietary_trace: bool = True, profile_priority_classes: Sequence[str] | None = None, profile_suspicion_levels: Sequence[str] | None = ("HIGHEST_SUSPICION", "HIGH_SUSPICION")) -> list[dict[str, Any]]:
    router_rows = list(router_output)
    events = list(source_events)
    evidence = list(evidence_events)
    signals = list(signal_hits)
    buckets = list(bucket_state)
    combinations = list(combination_hits)
    guards = list(guardrail_hits)
    demographics = demographics or {}
    return [build_patient_profile(patient_id, config=config, screening_target=phenotype, router_rows=router_rows, source_events=events, evidence_events=evidence, signal_hits=signals, bucket_state=buckets, combination_hits=combinations, guardrail_hits=guards, demographics=demographics.get(patient_id), include_proprietary_trace=include_proprietary_trace, run_id=run_id) for patient_id in flagged_patient_ids(router_rows, phenotype=phenotype, priority_classes=profile_priority_classes, suspicion_levels=profile_suspicion_levels)]


def build_attr_profiles(router_output: Iterable[Any], *, config: Any, source_events: Iterable[Any], evidence_events: Iterable[Any], signal_hits: Iterable[Any], bucket_state: Iterable[Any], combination_hits: Iterable[Any], guardrail_hits: Iterable[Any], demographics: Mapping[str, Mapping[str, Any]] | None, run_id: str, include_proprietary_trace: bool = True, profile_suspicion_levels: Sequence[str] | None = ("HIGHEST_SUSPICION", "HIGH_SUSPICION")) -> list[dict[str, Any]]:
    """Build one combined ATTR profile per patient after both phenotypes run."""
    router_rows = list(router_output)
    events = list(source_events)
    evidence = list(evidence_events)
    signals = list(signal_hits)
    buckets = list(bucket_state)
    combinations = list(combination_hits)
    guards = list(guardrail_hits)
    demographics = demographics or {}
    return [
        build_patient_profile(
            patient_id,
            config=config,
            screening_target="ATTR",
            router_rows=router_rows,
            source_events=events,
            evidence_events=evidence,
            signal_hits=signals,
            bucket_state=buckets,
            combination_hits=combinations,
            guardrail_hits=guards,
            demographics=demographics.get(patient_id),
            include_proprietary_trace=include_proprietary_trace,
            run_id=run_id,
        )
        for patient_id in flagged_attr_patient_ids(
            router_rows,
            suspicion_levels=profile_suspicion_levels,
        )
    ]


def build_al_detected_profiles(router_output: Iterable[Any], *, config: Any, source_events: Iterable[Any], evidence_events: Iterable[Any], signal_hits: Iterable[Any], bucket_state: Iterable[Any], combination_hits: Iterable[Any], guardrail_hits: Iterable[Any], demographics: Mapping[str, Mapping[str, Any]] | None, run_id: str, include_proprietary_trace: bool = True) -> list[dict[str, Any]]:
    """Build every AL pass, including concurrent ATTR passes."""
    router_rows = list(router_output)
    events = list(source_events)
    evidence = list(evidence_events)
    signals = list(signal_hits)
    buckets = list(bucket_state)
    combinations = list(combination_hits)
    guards = list(guardrail_hits)
    demographics = demographics or {}
    return [
        build_patient_profile(
            patient_id,
            config=config,
            screening_target="AL",
            router_rows=router_rows,
            source_events=events,
            evidence_events=evidence,
            signal_hits=signals,
            bucket_state=buckets,
            combination_hits=combinations,
            guardrail_hits=guards,
            demographics=demographics.get(patient_id),
            include_proprietary_trace=include_proprietary_trace,
            run_id=run_id,
        )
        for patient_id in flagged_al_detected_patient_ids(router_rows)
    ]


def build_known_profiles(known_patients: Iterable[Any], *, known_config: Any, source_events: Iterable[Any], evidence_events: Iterable[Any], demographics: Mapping[str, Mapping[str, Any]] | None, include_proprietary_trace: bool = True) -> list[dict[str, Any]]:
    events = list(source_events)
    evidence = list(evidence_events)
    demographics = demographics or {}
    return [
        build_known_attr_profile(
            patient,
            known_config=known_config,
            source_events=events,
            evidence_events=evidence,
            demographics=demographics.get(str(getattr(patient, "patient_id", ""))),
            include_proprietary_trace=include_proprietary_trace,
        )
        for patient in known_patients
    ]


def build_known_al_profiles(known_patients: Iterable[Any], *, known_config: Any, source_events: Iterable[Any], evidence_events: Iterable[Any], demographics: Mapping[str, Mapping[str, Any]] | None, include_proprietary_trace: bool = True) -> list[dict[str, Any]]:
    events = list(source_events)
    evidence = list(evidence_events)
    demographics = demographics or {}
    return [
        build_known_al_profile(
            patient,
            known_config=known_config,
            source_events=events,
            evidence_events=evidence,
            demographics=demographics.get(str(getattr(patient, "patient_id", ""))),
            include_proprietary_trace=include_proprietary_trace,
        )
        for patient in known_patients
    ]


def export_profile_files(profiles: Iterable[Mapping[str, Any]], output_dir: str | Path | None, *, phenotype: str) -> dict[str, str]:
    basename = f"{phenotype.lower()}_flagged_patient_profiles"
    return export_profiles(list(profiles), output_dir, basename=basename) if output_dir is not None else {}


def export_attr_profile_files(profiles: Iterable[Mapping[str, Any]], output_dir: str | Path | None) -> dict[str, str]:
    return export_profiles(list(profiles), output_dir, basename="attr_flagged_patient_profiles") if output_dir is not None else {}


def export_al_detected_profile_files(profiles: Iterable[Mapping[str, Any]], output_dir: str | Path | None) -> dict[str, str]:
    return export_al_detected_profiles(list(profiles), output_dir) if output_dir is not None else {}


def export_known_profile_files(profiles: Iterable[Mapping[str, Any]], output_dir: str | Path | None) -> dict[str, str]:
    return export_known_attr_profiles(list(profiles), output_dir) if output_dir is not None else {}


def export_known_al_profile_files(profiles: Iterable[Mapping[str, Any]], output_dir: str | Path | None) -> dict[str, str]:
    return export_known_al_profiles(list(profiles), output_dir) if output_dir is not None else {}


__all__ = [
    "build_profiles",
    "build_attr_profiles",
    "build_al_detected_profiles",
    "build_known_profiles",
    "build_known_al_profiles",
    "export_profile_files",
    "export_attr_profile_files",
    "export_al_detected_profile_files",
    "export_known_profile_files",
    "export_known_al_profile_files",
]

"""Operational evidence capabilities for the two V5 source profiles.

This module does not change clinical atoms, signals, or thresholds.  It states
which configured evidence routes can actually be observed in the authorized
warehouse inputs, so missing context is reported honestly instead of being
silently treated as negative clinical evidence.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .extraction.extraction_contract import normalize_system


AUTHORIZED_TABLE_KEYS = (
    "census",
    "claim",
    "encounter",
    "lab",
    "surgical_history",
)


@dataclass(frozen=True)
class EvidenceCapability:
    status: str
    sources: tuple[str, ...]
    explanation: str


PROFILE_CAPABILITIES: dict[str, dict[str, EvidenceCapability]] = {
    "claims_only_v1": {
        "ICD10": EvidenceCapability(
            "AVAILABLE",
            ("claim.diagnosis_code",),
            "ICD-10-CM diagnosis codes are directly available in CLAIMS.",
        ),
        "ICD9": EvidenceCapability(
            "UNAVAILABLE_BY_SOURCE",
            (),
            "The supplied claims identify diagnosis values as ICD-10-CM; no ICD-9 field is available.",
        ),
        "CPT_HCPCS": EvidenceCapability(
            "UNAVAILABLE_BY_SOURCE",
            (),
            "No populated procedure-code field is available in CLAIMS.",
        ),
        "SNOMED_CT": EvidenceCapability(
            "UNAVAILABLE_BY_SOURCE",
            (),
            "SNOMED evidence is outside the strict claims-only boundary.",
        ),
        "LOINC": EvidenceCapability(
            "UNAVAILABLE_BY_SOURCE",
            (),
            "LABS is outside the strict claims-only boundary.",
        ),
        "NLP": EvidenceCapability(
            "UNAVAILABLE_BY_SOURCE",
            (),
            "CLAIMS contains no usable clinical narrative field.",
        ),
        "EVENT_DATE": EvidenceCapability(
            "UNAVAILABLE_BY_SOURCE",
            (),
            "CLAIMS contains no verified usable date field.",
        ),
    },
    "all_available_v1": {
        "ICD10": EvidenceCapability(
            "AVAILABLE",
            ("claim.diagnosis_code",),
            "ICD-10-CM diagnosis codes are directly available in CLAIMS.",
        ),
        "ICD9": EvidenceCapability(
            "UNAVAILABLE_BY_SOURCE",
            (),
            "The supplied claims identify diagnosis values as ICD-10-CM; no ICD-9 field is available.",
        ),
        "CPT_HCPCS": EvidenceCapability(
            "UNAVAILABLE_BY_SOURCE",
            (),
            "No populated procedure-code field is available in CLAIMS.",
        ),
        "SNOMED_CT": EvidenceCapability(
            "AVAILABLE",
            ("surgical_history.snomed", "surgical_history.secondary_snomed"),
            "SNOMED codes are available only from SURGICAL_HISTORY.",
        ),
        "LOINC": EvidenceCapability(
            "UNAVAILABLE_BY_SOURCE",
            (),
            "LABS observation identifiers are local free text and must not be treated as LOINC.",
        ),
        "NLP": EvidenceCapability(
            "PARTIAL_CONTEXT",
            ("lab.lab_result_note", "surgical_history.value"),
            "Only sparse lab notes and surgical-history labels provide text; no general clinical-note corpus exists.",
        ),
        "LOCAL_LAB": EvidenceCapability(
            "PARTIAL_CONTEXT",
            ("lab.observation_identifier", "lab.observation_value"),
            "Local test names and values are available, but units, reference ranges, and abnormal flags are not.",
        ),
        "EVENT_DATE": EvidenceCapability(
            "PARTIAL_CONTEXT",
            ("encounter.encounter_date", "lab.observation_datetime", "surgical_history.event_date"),
            "Dates exist outside CLAIMS. A claim date may be enriched only after a validated, unique patient-plus-encounter join.",
        ),
    },
}


def capability_for(profile: str, evidence_type: str) -> EvidenceCapability:
    """Return the declared capability for one evidence type and profile."""
    try:
        capabilities = PROFILE_CAPABILITIES[str(profile)]
    except KeyError as exc:
        raise ValueError(f"unknown V5 source profile: {profile!r}") from exc
    raw_key = str(evidence_type).strip().upper().replace("-", "_").replace(" ", "_")
    key = raw_key if raw_key in capabilities else normalize_system(evidence_type)
    return capabilities.get(
        key,
        EvidenceCapability(
            "UNAVAILABLE_BY_SOURCE",
            (),
            f"{key or 'UNKNOWN'} has no route in the selected V5 source profile.",
        ),
    )


def audit_terminology_coverage(
    terminology_rows: Iterable[Mapping[str, Any]],
    *,
    profile: str,
) -> dict[str, Any]:
    """Summarize configured terminology without altering clinical config."""
    counts: Counter[str] = Counter()
    atoms: dict[str, set[str]] = defaultdict(set)
    for row in terminology_rows:
        system = normalize_system(row.get("terminology_system"))
        status = capability_for(profile, system).status
        counts[status] += 1
        atom_id = str(row.get("atom_id") or "").strip()
        if atom_id:
            atoms[status].add(atom_id)
    return {
        "profile": profile,
        "term_counts_by_status": dict(sorted(counts.items())),
        "atom_counts_by_status": {
            status: len(atom_ids) for status, atom_ids in sorted(atoms.items())
        },
        "clinical_config_modified": False,
    }


__all__ = [
    "AUTHORIZED_TABLE_KEYS",
    "EvidenceCapability",
    "PROFILE_CAPABILITIES",
    "audit_terminology_coverage",
    "capability_for",
]

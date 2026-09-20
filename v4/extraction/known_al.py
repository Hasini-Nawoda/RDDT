"""Configurable pre-screen recognition for known/confirmed AL.

AL recognition is intentionally fail-safe.  No diagnosis codes are embedded
here: when an approved known-AL vocabulary is unavailable, the route is an
explicit empty route and the pipeline reports the configuration gap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .known_attr import KnownAttrConfig, KnownAttrResult, identify_known_attr


DEFAULT_KNOWN_AL_CONFIG = Path(__file__).resolve().parents[1] / "config" / "shared" / "known_al.json"


class KnownALConfig(KnownAttrConfig):
    """Known-AL vocabulary with explicit availability/gap metadata."""

    def __init__(self, payload: Mapping[str, Any], *, path: str | Path | None = None, available: bool = True, config_gap: str | None = None):
        super().__init__(payload, path=path)
        self.available = bool(available)
        self.config_gap = config_gap


@dataclass
class KnownALPatient:
    run_id: str
    patient_id: str
    status: str
    confirmation_scope: str
    confirmation_rule_ids: list[str] = field(default_factory=list)
    matched_config_values: list[str] = field(default_factory=list)
    event_dates: list[str] = field(default_factory=list)
    support_lineage_ids: list[str] = field(default_factory=list)
    supporting_evidence_ids: list[str] = field(default_factory=list)
    known_al_config_hash: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "patient_id": self.patient_id,
            "status": self.status,
            "confirmation_scope": self.confirmation_scope,
            "confirmation_rule_ids": list(self.confirmation_rule_ids),
            "matched_config_values": list(self.matched_config_values),
            "event_dates": list(self.event_dates),
            "support_lineage_ids": list(self.support_lineage_ids),
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "known_al_config_hash": self.known_al_config_hash,
        }


@dataclass
class KnownALResult:
    patients: list[KnownALPatient]
    matches: list[Any]
    evidence: list[Any]
    config_gap: str | None = None

    @property
    def patient_ids(self) -> set[str]:
        return {row.patient_id for row in self.patients}


def _empty_config(*, gap: str) -> KnownALConfig:
    return KnownALConfig(
        {"atoms": [], "terminology": [], "confirmation_rules": []},
        path=None,
        available=False,
        config_gap=gap,
    )


def load_known_al_config(path: str | Path | None = None) -> KnownALConfig:
    source = Path(path or DEFAULT_KNOWN_AL_CONFIG).expanduser().resolve()
    if not source.is_file():
        return _empty_config(gap=f"KNOWN_AL_CONFIG_UNAVAILABLE:{source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _empty_config(gap=f"KNOWN_AL_CONFIG_INVALID:{source}:{exc}")
    if not isinstance(payload, Mapping):
        return _empty_config(gap=f"KNOWN_AL_CONFIG_INVALID:{source}:expected_object")
    # The shape mirrors known_attr.json, but unlike known ATTR no fallback
    # values are accepted or inferred.
    required = {"atoms", "terminology", "confirmation_rules"}
    missing = sorted(required - set(payload))
    if missing:
        return _empty_config(gap=f"KNOWN_AL_CONFIG_INVALID:{source}:missing={','.join(missing)}")
    try:
        return KnownALConfig(payload, path=source, available=True)
    except (TypeError, ValueError) as exc:
        return _empty_config(gap=f"KNOWN_AL_CONFIG_INVALID:{source}:{exc}")


def identify_known_al(
    events: Iterable[Any],
    *,
    run_id: str,
    screening_cutoff: Any,
    nlp: Any = None,
    context_processor: Any = None,
    config: KnownALConfig | None = None,
) -> KnownALResult:
    known_config = config or load_known_al_config()
    if not known_config.available:
        return KnownALResult(patients=[], matches=[], evidence=[], config_gap=known_config.config_gap)
    delegate: KnownAttrResult = identify_known_attr(
        events,
        run_id=run_id,
        screening_cutoff=screening_cutoff,
        nlp=nlp,
        context_processor=context_processor,
        config=known_config,
    )
    patients = [
        KnownALPatient(
            run_id=row.run_id,
            patient_id=row.patient_id,
            status="EXCLUDED_KNOWN_AL",
            confirmation_scope=row.confirmation_scope,
            confirmation_rule_ids=list(row.confirmation_rule_ids),
            matched_config_values=list(row.matched_config_values),
            event_dates=list(row.event_dates),
            support_lineage_ids=list(row.support_lineage_ids),
            supporting_evidence_ids=list(row.supporting_evidence_ids),
            known_al_config_hash=known_config.config_hash,
        )
        for row in delegate.patients
    ]
    return KnownALResult(
        patients=patients,
        matches=delegate.matches,
        evidence=delegate.evidence,
        config_gap=known_config.config_gap,
    )


__all__ = [
    "DEFAULT_KNOWN_AL_CONFIG",
    "KnownALConfig",
    "KnownALPatient",
    "KnownALResult",
    "load_known_al_config",
    "identify_known_al",
]

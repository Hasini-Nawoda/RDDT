"""Pre-screen recognition of patients with existing ATTR/amyloidosis evidence.

This stage is deliberately outside the phenotype signal registry.  It copies
the surviving V2/V3 ``confirmed_attr_e85`` vocabulary and applies the V3
corroboration restriction to structured codes.  Positive patients are removed
before ATTRv/ATTRwt scoring and retained for a separate confirmed output.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .atom_matching import AtomMatch, match_atom_events
from .evidence_qualification import QualifiedEvidence, qualify_atom_matches
from .source_events import SourceEvent


DEFAULT_KNOWN_CONFIRMATIONS_CONFIG = Path(__file__).resolve().parents[1] / "config" / "shared" / "confirmed_patients.json"
# Kept as a public compatibility alias for callers that used the old name.
DEFAULT_KNOWN_ATTR_CONFIG = DEFAULT_KNOWN_CONFIRMATIONS_CONFIG


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_date(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            parsed = datetime.combine(value, datetime.min.time())
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except (TypeError, ValueError):
        return None


class KnownAttrConfig:
    """Small config adapter used by the generic matching/qualification code."""

    def __init__(self, payload: Mapping[str, Any], *, path: str | Path | None = None):
        self.payload = dict(payload)
        self.path = None if path is None else str(path)
        self.config_hash = _canonical_hash(self.payload)

    def rows(self, table: str) -> list[dict[str, Any]]:
        value = self.payload.get(table, [])
        return [dict(row) for row in value] if isinstance(value, list) else []


class CandidateConfigUnion:
    """Candidate-only union of a phenotype package and known-ATTR vocabulary."""

    def __init__(self, phenotype_config: Any, known_attr_config: KnownAttrConfig, additional_configs: Iterable[Any] = ()):
        self.phenotype_config = phenotype_config
        self.known_attr_config = known_attr_config
        self.additional_configs = tuple(additional_configs or ())
        self.config_hash = _canonical_hash({
            "phenotype": getattr(phenotype_config, "config_hash", None),
            "known_attr": known_attr_config.config_hash,
            "additional": [getattr(config, "config_hash", None) for config in self.additional_configs],
        })

    def rows(self, table: str) -> list[dict[str, Any]]:
        base = list(self.phenotype_config.rows(table))
        if table in {"atoms", "terminology"}:
            base.extend(self.known_attr_config.rows(table))
            for config in self.additional_configs:
                base.extend(config.rows(table))
        return base


@dataclass
class KnownAttrPatient:
    run_id: str
    patient_id: str
    status: str
    confirmation_scope: str
    confirmation_rule_ids: list[str] = field(default_factory=list)
    matched_config_values: list[str] = field(default_factory=list)
    event_dates: list[str] = field(default_factory=list)
    support_lineage_ids: list[str] = field(default_factory=list)
    supporting_evidence_ids: list[str] = field(default_factory=list)
    known_attr_config_hash: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KnownAttrResult:
    patients: list[KnownAttrPatient]
    matches: list[AtomMatch]
    evidence: list[QualifiedEvidence]

    @property
    def patient_ids(self) -> set[str]:
        return {row.patient_id for row in self.patients}


def _route_payload(payload: Mapping[str, Any], route: str, source: Path) -> Mapping[str, Any]:
    """Select a route from the consolidated config, or accept the old flat shape."""
    routes = payload.get("routes")
    if routes is None:
        return payload
    if not isinstance(routes, Mapping):
        raise ValueError(f"Confirmed-patient routes must be an object: {source}")
    selected = routes.get(route)
    if not isinstance(selected, Mapping):
        raise ValueError(f"Confirmed-patient config is missing {route} route: {source}")
    return selected


def _validate_route_payload(payload: Mapping[str, Any], *, label: str, source: Path) -> Mapping[str, Any]:
    required = {"atoms", "terminology", "confirmation_rules"}
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"Known-{label} configuration is missing {missing}: {source}")
    terminology = payload.get("terminology", [])
    if not isinstance(terminology, list) or not all(isinstance(row, Mapping) for row in terminology):
        raise ValueError(f"Known-{label} terminology must be a list of objects: {source}")
    keys = [
        (
            str(row.get("atom_id", "")),
            str(row.get("terminology_system", "")).upper(),
            str(row.get("value", "")),
        )
        for row in terminology
    ]
    if len(keys) != len(set(keys)):
        raise ValueError(f"Known-{label} configuration contains duplicate terminology: {source}")
    configured_values = {str(row.get("value", "")) for row in terminology}
    rules = payload.get("confirmation_rules", [])
    if not isinstance(rules, list) or not all(isinstance(rule, Mapping) for rule in rules):
        raise ValueError(f"Known-{label} confirmation_rules must be a list of objects: {source}")
    unknown_rule_values = sorted({
        str(value)
        for rule in rules
        for value in (rule.get("values", []) or [])
        if str(value) not in configured_values
    })
    if unknown_rule_values:
        raise ValueError(
            f"Known-{label} confirmation rules reference unknown values {unknown_rule_values}: {source}"
        )
    return payload


def load_known_attr_config(path: str | Path | None = None) -> KnownAttrConfig:
    source = Path(path or DEFAULT_KNOWN_ATTR_CONFIG).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"Known-ATTR configuration must be an object: {source}")
    route = _validate_route_payload(_route_payload(payload, "ATTR", source), label="ATTR", source=source)
    return KnownAttrConfig(route, path=source)


def _available_before(match: AtomMatch, screening_cutoff: Any) -> bool:
    available = _parse_date(match.available_date)
    cutoff = _parse_date(screening_cutoff)
    return available is not None and cutoff is not None and available <= cutoff


def _value_assignment(matches_by_value: Mapping[str, Sequence[AtomMatch]], values: Sequence[str]) -> list[AtomMatch] | None:
    selected: list[AtomMatch] = []
    for value in values:
        candidates = list(matches_by_value.get(str(value), ()))
        if not candidates:
            return None
        selected.append(candidates[0])
    return selected


def identify_known_attr(
    events: Iterable[SourceEvent],
    *,
    run_id: str,
    screening_cutoff: Any,
    nlp: Any = None,
    context_processor: Any = None,
    config: KnownAttrConfig | None = None,
    terminology_mode: str = "ALL",
    terminology_systems: Any = None,
) -> KnownAttrResult:
    """Identify and aggregate confirmed/known patients before phenotype scoring."""
    known_config = config or load_known_attr_config()
    event_rows = list(events)
    matches = list(match_atom_events(
        event_rows,
        known_config,
        config_hash=known_config.config_hash,
        nlp=nlp,
        terminology_mode=terminology_mode,
        terminology_systems=terminology_systems,
    ))
    evidence = list(qualify_atom_matches(
        matches,
        known_config,
        context_processor=context_processor,
        screening_cutoff=screening_cutoff,
    ))
    term_scope = {
        str(row.get("value")): str(row.get("confirmation_scope") or "KNOWN_AMYLOIDOSIS")
        for row in known_config.rows("terminology")
    }
    affirmed_rules_by_value: dict[str, list[Mapping[str, Any]]] = {}
    for rule in known_config.rows("confirmation_rules"):
        if str(rule.get("operator", "")).upper() != "ANY_AFFIRMED_NLP_TERM":
            continue
        for value in rule.get("values", []) or []:
            affirmed_rules_by_value.setdefault(str(value), []).append(rule)
    evidence_by_patient: dict[str, list[QualifiedEvidence]] = {}
    for row in evidence:
        if row.status == "TRUE":
            evidence_by_patient.setdefault(str(row.patient_id), []).append(row)

    structured_by_patient: dict[str, dict[str, list[AtomMatch]]] = {}
    for match in matches:
        if match.match_method != "EXACT_NORMALIZED_CODE":
            continue
        if str(match.experiencer_hint or "PATIENT").upper() != "PATIENT":
            continue
        if not _available_before(match, screening_cutoff):
            continue
        structured_by_patient.setdefault(str(match.patient_id), {}).setdefault(
            str(match.matched_config_value), []
        ).append(match)

    patient_ids = set(evidence_by_patient) | set(structured_by_patient)
    patients: list[KnownAttrPatient] = []
    for patient_id in sorted(patient_ids):
        positive_evidence: list[QualifiedEvidence] = []
        selected_matches: list[AtomMatch] = []
        rule_ids: list[str] = []
        scopes: list[str] = []
        for row in evidence_by_patient.get(patient_id, []):
            matched_value = str(row.source_provenance.get("matched_config_value") or "")
            matching_rules = affirmed_rules_by_value.get(matched_value, [])
            if not matching_rules:
                continue
            positive_evidence.append(row)
            scopes.append(term_scope.get(matched_value, "KNOWN_AMYLOIDOSIS"))
            for rule in matching_rules:
                rule_ids.append(str(rule.get("rule_id")))
                if rule.get("confirmation_scope") not in (None, ""):
                    scopes.append(str(rule.get("confirmation_scope")))

        matches_by_value = structured_by_patient.get(patient_id, {})
        for rule in known_config.rows("confirmation_rules"):
            if str(rule.get("operator")) != "ALL_VALUES_PRESENT":
                continue
            assignment = _value_assignment(matches_by_value, [str(value) for value in rule.get("values", [])])
            if assignment is None:
                continue
            selected_matches.extend(assignment)
            rule_ids.append(str(rule.get("rule_id")))
            scopes.append(str(rule.get("confirmation_scope") or "KNOWN_AMYLOIDOSIS"))

        if not rule_ids:
            continue
        unique_matches = {
            (match.source_event_id, match.matched_config_value): match
            for match in selected_matches
        }
        if "ATTR_SPECIFIC" in scopes:
            scope = "ATTR_SPECIFIC"
        elif "AL_SPECIFIC" in scopes:
            scope = "AL_SPECIFIC"
        else:
            scope = "KNOWN_AMYLOIDOSIS"
        matched_values = {
            str(row.source_provenance.get("matched_config_value") or "")
            for row in positive_evidence
        }
        matched_values.update(str(match.matched_config_value) for match in unique_matches.values())
        lineages = {
            lineage
            for row in positive_evidence
            for lineage in row.support_lineage_ids
        }
        lineages.update(str(match.support_lineage_id) for match in unique_matches.values() if match.support_lineage_id)
        event_dates = {str(row.event_date) for row in positive_evidence if row.event_date not in (None, "")}
        event_dates.update(str(match.event_date) for match in unique_matches.values() if match.event_date not in (None, ""))
        patients.append(KnownAttrPatient(
            run_id=str(run_id),
            patient_id=patient_id,
            status="EXCLUDED_KNOWN_ATTR_OR_AMYLOIDOSIS",
            confirmation_scope=scope,
            confirmation_rule_ids=sorted(set(rule_ids)),
            matched_config_values=sorted(value for value in matched_values if value),
            event_dates=sorted(event_dates),
            support_lineage_ids=sorted(lineages),
            supporting_evidence_ids=sorted(row.evidence_id for row in positive_evidence),
            known_attr_config_hash=known_config.config_hash,
        ))
    return KnownAttrResult(patients=patients, matches=matches, evidence=evidence)


__all__ = [
    "DEFAULT_KNOWN_CONFIRMATIONS_CONFIG",
    "DEFAULT_KNOWN_ATTR_CONFIG",
    "KnownAttrConfig",
    "CandidateConfigUnion",
    "KnownAttrPatient",
    "KnownAttrResult",
    "load_known_attr_config",
    "identify_known_attr",
]

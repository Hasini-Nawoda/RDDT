"""Patient-profile assembly and local download exports for V4 screening runs.

The review-facing clinical rationale is intentionally separate from
``proprietary_pipeline_trace``.  Consumers can remove the latter with one
flag or one top-level field deletion without losing the medical profile,
phenotype verdicts, or clinical explanation.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..config_loader import PHENOTYPE_SLOTS

PHENOTYPE_ORDER = PHENOTYPE_SLOTS


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _patient(items: Iterable[Any], patient_id: str) -> list[Any]:
    wanted = str(patient_id)
    return [item for item in items if str(_value(item, "patient_id", "")) == wanted]


def _atom_names(config: Any) -> dict[str, str]:
    rows = config.rows("atoms") if hasattr(config, "rows") else _value(config, "atoms", [])
    if isinstance(rows, Mapping):
        rows = list(rows.values())
    names: dict[str, str] = {}
    for row in rows or []:
        atom_id = str(_value(row, "atom_id", _value(row, "Atom_ID", "")))
        preferred = _value(
            row,
            "preferred_clinical_name",
            _value(row, "preferred_name", _value(row, "Preferred_Clinical_Name", atom_id)),
        )
        if atom_id:
            names[atom_id] = str(preferred or atom_id)
    return names


def _source_event_index(source_events: Iterable[Any]) -> dict[str, Any]:
    index = {}
    for event in source_events:
        event_id = _value(event, "source_event_id")
        if event_id not in (None, ""):
            index[str(event_id)] = event
    return index


def _verdicts(router_rows: Sequence[Any]) -> list[dict[str, Any]]:
    by_phenotype = {str(_value(row, "phenotype", "")).upper(): row for row in router_rows}
    verdicts = []
    for phenotype in PHENOTYPE_ORDER:
        row = by_phenotype.get(phenotype)
        if row is None:
            verdicts.append({
                "phenotype": phenotype,
                "status": "NOT_EVALUATED",
                "result_route": None,
                "priority_class": None,
                "reason": "CONFIG_NOT_LOADED",
            })
            continue
        verdicts.append({
            "phenotype": phenotype,
            "status": _value(row, "status", "UNKNOWN"),
            "result_route": _value(row, "result_route"),
            "priority_class": _value(row, "priority_class"),
            "reason": _value(row, "explanation"),
            "parallel_routes": _plain(_value(row, "parallel_routes", [])),
        })
    return verdicts


def _supporting_evidence_ids(witnesses: Iterable[Any]) -> set[str]:
    """Collect evidence IDs recursively from selected combination witnesses."""
    found: set[str] = set()
    stack = list(witnesses)
    while stack:
        witness = stack.pop()
        for evidence_id in _value(witness, "supporting_evidence_ids", ()) or ():
            if evidence_id not in (None, ""):
                found.add(str(evidence_id))
        for key in ("supporting_hits", "selected_witnesses"):
            stack.extend(list(_value(witness, key, ()) or ()))
    return found


def _medical_timeline(
    patient_events: Sequence[Any],
    patient_evidence: Sequence[Any],
    atom_names: Mapping[str, str],
) -> list[dict[str, Any]]:
    event_index = _source_event_index(patient_events)
    atoms_by_event: dict[str, list[dict[str, Any]]] = {}
    for evidence in patient_evidence:
        provenance = _value(evidence, "source_provenance", {}) or {}
        source_event_id = _value(provenance, "source_event_id")
        if source_event_id in (None, ""):
            continue
        atom_id = str(_value(evidence, "atom_id", ""))
        meaning = {
            "atom_id": atom_id,
            "atom_name": atom_names.get(atom_id, atom_id),
            "evidence_status": _value(evidence, "status"),
            "reason": _value(evidence, "reason"),
        }
        existing = atoms_by_event.setdefault(str(source_event_id), [])
        key = (meaning["atom_id"], meaning["evidence_status"], meaning["reason"])
        if key not in {(item["atom_id"], item["evidence_status"], item["reason"]) for item in existing}:
            existing.append(meaning)

    timeline = []
    for event_id, event in event_index.items():
        timeline.append({
            "source_event_id": event_id,
            "event_date": _plain(_value(event, "event_date")),
            "available_date": _plain(_value(event, "available_date")),
            "encounter_id": _value(event, "encounter_id"),
            "source_table": _value(event, "source_table"),
            "source_record_id": _value(event, "source_record_id"),
            "source_specialty": _value(event, "source_specialty"),
            "source_field": _value(event, "source_field"),
            "code_system": _value(event, "code_system"),
            "code_value": _value(event, "code_value"),
            "text_value": _value(event, "text_value"),
            "result_value": _value(event, "result_value"),
            "result_status": _value(event, "result_status"),
            "clinical_meanings": atoms_by_event.get(event_id, []),
        })
    timeline.sort(key=lambda row: (str(row.get("event_date") or ""), str(row.get("source_event_id") or "")))
    return timeline


def build_patient_profile(
    patient_id: str,
    *,
    config: Any,
    screening_target: str,
    router_rows: Iterable[Any],
    source_events: Iterable[Any],
    evidence_events: Iterable[Any],
    signal_hits: Iterable[Any] = (),
    bucket_state: Iterable[Any] = (),
    combination_hits: Iterable[Any] = (),
    guardrail_hits: Iterable[Any] = (),
    demographics: Mapping[str, Any] | None = None,
    include_proprietary_trace: bool = True,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build one review profile with a single removable internal-trace field."""
    patient_router = _patient(router_rows, patient_id)
    patient_source = _patient(source_events, patient_id)
    patient_evidence = _patient(evidence_events, patient_id)
    patient_signals = _patient(signal_hits, patient_id)
    patient_buckets = _patient(bucket_state, patient_id)
    patient_combinations = _patient(combination_hits, patient_id)
    patient_guardrails = _patient(guardrail_hits, patient_id)
    names = _atom_names(config)
    verdicts = _verdicts(patient_router)
    target = str(screening_target).upper()
    if target not in PHENOTYPE_ORDER:
        raise ValueError(f"Unsupported screening target {target!r}; expected one of {PHENOTYPE_ORDER}")
    target_verdict = next(item for item in verdicts if item["phenotype"] == target)

    matched_combination_id = next(
        (
            _value(row, "matched_combination_id")
            for row in patient_router
            if str(_value(row, "phenotype", "")).upper() == target
        ),
        None,
    )
    matched_combination = next(
        (
            row for row in patient_combinations
            if _value(row, "combination_id") == matched_combination_id
            and str(_value(row, "status", "")).upper() == "TRUE"
        ),
        None,
    )
    rationale_evidence_ids = _supporting_evidence_ids(
        _value(matched_combination, "selected_witnesses", ()) or ()
    )

    clinical_reasons = []
    seen_reasons: set[tuple[str, str, str]] = set()
    for evidence in patient_evidence:
        if str(_value(evidence, "status", "")).upper() != "TRUE":
            continue
        if matched_combination is not None and str(_value(evidence, "evidence_id", "")) not in rationale_evidence_ids:
            continue
        atom_id = str(_value(evidence, "atom_id", ""))
        provenance = _value(evidence, "source_provenance", {}) or {}
        reason_key = (atom_id, str(_value(provenance, "source_event_id", "")), str(_value(evidence, "event_date", "")))
        if reason_key in seen_reasons:
            continue
        seen_reasons.add(reason_key)
        clinical_reasons.append({
            "clinical_finding": names.get(atom_id, atom_id),
            "atom_id": atom_id,
            "event_date": _plain(_value(evidence, "event_date")),
            "source_event_id": _value(provenance, "source_event_id"),
            "matched_value": _value(provenance, "matched_config_value"),
        })

    profile = {
        "run_id": run_id or next((str(_value(row, "run_id")) for row in patient_router if _value(row, "run_id") is not None), None),
        "patient_id": str(patient_id),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "demographics": _plain(dict(demographics or {})),
        "medical_profile": {
            "timeline": _medical_timeline(patient_source, patient_evidence, names),
            "event_count": len(patient_source),
        },
        "phenotype_verdicts": verdicts,
        "suspected_diagnosis": {
            "screening_target": target,
            "status": target_verdict["status"],
            "review_route": target_verdict["result_route"],
            "priority_class": target_verdict["priority_class"],
            "screening_only_not_diagnosis": True,
        },
        "clinical_rationale": {
            "summary": target_verdict.get("reason"),
            "findings": clinical_reasons,
            "parallel_routes": target_verdict.get("parallel_routes", []),
        },
    }
    if include_proprietary_trace:
        profile["proprietary_pipeline_trace"] = {
            "signal_hits": _plain(patient_signals),
            "bucket_state": _plain(patient_buckets),
            "combination_hits": _plain(patient_combinations),
            "guardrail_hits": _plain(patient_guardrails),
            "router_rows": _plain(patient_router),
        }
    return profile


def strip_proprietary_trace(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy safe for external review distribution.

    Atom names are clinical labels and remain beside code evidence. Internal
    rule identifiers are implementation details, so they are removed along
    with the top-level execution trace.
    """
    clean = _plain(profile)
    clean.pop("proprietary_pipeline_trace", None)

    internal_keys = {
        "atom_id",
        "signal_id",
        "bucket_id",
        "combination_id",
        "requirement_id",
        "guardrail_id",
        "rule_id",
        "group_id",
    }

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: scrub(item)
                for key, item in value.items()
                if str(key).lower() not in internal_keys
            }
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return scrub(clean)


def flagged_patient_ids(
    router_rows: Iterable[Any],
    *,
    phenotype: str,
    statuses: Sequence[str] = ("PHENOTYPE_PASS",),
) -> list[str]:
    accepted = {status.upper() for status in statuses}
    ids = {
        str(_value(row, "patient_id"))
        for row in router_rows
        if str(_value(row, "phenotype", "")).upper() == phenotype.upper()
        and str(_value(row, "status", "")).upper() in accepted
        and _value(row, "patient_id") not in (None, "")
    }
    return sorted(ids)


def profiles_jsonl_bytes(profiles: Iterable[Mapping[str, Any]], *, include_proprietary_trace: bool = False) -> bytes:
    rows = [(_plain(profile) if include_proprietary_trace else strip_proprietary_trace(profile)) for profile in profiles]
    return ("\n".join(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows) + ("\n" if rows else "")).encode("utf-8")


def profiles_csv_bytes(profiles: Iterable[Mapping[str, Any]]) -> bytes:
    """Return a compact, trace-free CSV index suitable for notebook download."""
    output = io.StringIO(newline="")
    fields = ["run_id", "patient_id", "screening_target", "screening_status", "review_route", "priority_class", "clinical_rationale"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for profile in profiles:
        clean = strip_proprietary_trace(profile)
        diagnosis = clean.get("suspected_diagnosis", {})
        rationale = clean.get("clinical_rationale", {})
        writer.writerow({
            "run_id": clean.get("run_id"),
            "patient_id": clean.get("patient_id"),
            "screening_target": diagnosis.get("screening_target"),
            "screening_status": diagnosis.get("status"),
            "review_route": diagnosis.get("review_route"),
            "priority_class": diagnosis.get("priority_class"),
            "clinical_rationale": rationale.get("summary"),
        })
    return output.getvalue().encode("utf-8-sig")


def export_profiles(
    profiles: Iterable[Mapping[str, Any]],
    output_dir: str | Path,
    *,
    basename: str = "amyloidosis_flagged_patient_profiles",
    include_proprietary_trace: bool = False,
) -> dict[str, str]:
    """Write local-runtime JSONL plus a trace-free CSV download index."""
    rows = list(profiles)
    target = Path(output_dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    jsonl = target / f"{basename}.jsonl"
    csv_path = target / f"{basename}.csv"
    jsonl.write_bytes(profiles_jsonl_bytes(rows, include_proprietary_trace=include_proprietary_trace))
    csv_path.write_bytes(profiles_csv_bytes(rows))
    return {"jsonl": str(jsonl), "csv": str(csv_path)}


__all__ = [
    "PHENOTYPE_ORDER",
    "build_patient_profile",
    "strip_proprietary_trace",
    "flagged_patient_ids",
    "profiles_jsonl_bytes",
    "profiles_csv_bytes",
    "export_profiles",
]

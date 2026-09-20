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
from ..reasoning.risk_labels import (
    SUSPICION_FOLDER,
    normalized_suspicion_levels,
    suspicion_level,
)

PHENOTYPE_ORDER = PHENOTYPE_SLOTS
ATTR_PHENOTYPES = ("ATTRV", "ATTRWT")
AL_PHENOTYPE = "AL"
_SUSPICION_RANK = {
    "HIGHEST_SUSPICION": 0,
    "HIGH_SUSPICION": 1,
    "MODERATE_SUSPICION": 2,
}


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
                "suspicion_level": None,
                "reason": "CONFIG_NOT_LOADED",
            })
            continue
        verdicts.append({
            "phenotype": phenotype,
            "status": _value(row, "status", "UNKNOWN"),
            "result_route": _value(row, "result_route"),
            "suspicion_level": _value(
                row,
                "suspicion_level",
                suspicion_level(_value(row, "priority_class")),
            ),
            "reason": _value(row, "explanation"),
            "parallel_routes": _plain(_value(row, "parallel_routes", [])),
        })
    return verdicts


def aggregate_attr_verdict(router_rows: Iterable[Any]) -> dict[str, Any]:
    """Build one ATTR verdict from actual ATTRv/ATTRwt phenotype verdicts.

    Guardrail and differential routes remain visible as parallel routes, but
    they never create a phenotype pass. The aggregate suspicion is therefore
    driven only by a real ``PHENOTYPE_PASS`` from ATTRv or ATTRwt.
    """
    rows = [
        row for row in router_rows
        if str(_value(row, "phenotype", "")).upper() in ATTR_PHENOTYPES
    ]
    passing = [
        row for row in rows
        if str(_value(row, "status", "")).upper() == "PHENOTYPE_PASS"
        and str(
            _value(
                row,
                "suspicion_level",
                suspicion_level(_value(row, "priority_class")),
            )
            or ""
        ).upper() in _SUSPICION_RANK
    ]
    passing.sort(key=lambda row: (
        _SUSPICION_RANK[str(
            _value(
                row,
                "suspicion_level",
                suspicion_level(_value(row, "priority_class")),
            )
        ).upper()],
        ATTR_PHENOTYPES.index(str(_value(row, "phenotype", "")).upper()),
    ))
    parallel_routes = list(dict.fromkeys(
        str(route)
        for row in rows
        for route in (_value(row, "parallel_routes", ()) or ())
        if route not in (None, "")
    ))
    if passing:
        best_level = str(
            _value(
                passing[0],
                "suspicion_level",
                suspicion_level(_value(passing[0], "priority_class")),
            )
        ).upper()
        passed_phenotypes = [
            str(_value(row, "phenotype", "")).upper() for row in passing
        ]
        highest_phenotypes = [
            str(_value(row, "phenotype", "")).upper()
            for row in passing
            if str(
                _value(
                    row,
                    "suspicion_level",
                    suspicion_level(_value(row, "priority_class")),
                )
            ).upper() == best_level
        ]
        return {
            "status": "ATTR_SUSPICION",
            "result_route": "ATTR_EARLY_DETECTION_REVIEW",
            "suspicion_level": best_level,
            "passed_phenotypes": passed_phenotypes,
            "highest_suspicion_phenotypes": highest_phenotypes,
            "parallel_routes": parallel_routes,
            "reason": (
                "ATTR early-detection criteria were met by "
                + " and ".join(passed_phenotypes)
                + "; the combined tier uses the highest phenotype suspicion."
            ),
        }
    statuses = {str(_value(row, "status", "")).upper() for row in rows}
    status = "HOLD" if "HOLD" in statuses else "UNKNOWN" if "UNKNOWN" in statuses else "NO_MATCH"
    return {
        "status": status,
        "result_route": "NO_MATCH",
        "suspicion_level": None,
        "passed_phenotypes": [],
        "highest_suspicion_phenotypes": [],
        "parallel_routes": parallel_routes,
        "reason": "Neither ATTRv nor ATTRwt produced a phenotype pass.",
    }


def _normalized_route(route: Any) -> str:
    """Normalize configured route labels for cross-phenotype annotations.

    Route labels are configuration-owned and may be emitted with a prefix or
    separator.  The runtime only recognizes the approved route identifiers;
    it never invents a diagnosis or a new route label.
    """
    text = "".join(ch for ch in str(route or "").upper() if ch.isalnum())
    if text.startswith("V39"):
        return "V39"
    for value in ("WT25", "WT26", "WT27"):
        if text.startswith(value):
            return value
    return text


def cross_phenotype_attr_al_annotation(router_rows: Iterable[Any]) -> dict[str, Any]:
    """Return the explicit ATTR/AL differential annotation for one patient.

    AL is independently evaluated and always remains visible.  Concurrent
    ATTR/AL evidence is labelled as concordant differential evidence when an
    ATTR-side parallel route carries one of the configured AL differential
    identifiers (V39 or WT25-WT27); neither result increases the certainty of
    the other, and the ATTR risk tier/verdict remains unchanged.
    """
    rows = list(router_rows)
    al_rows = [
        row for row in rows
        if str(_value(row, "phenotype", "")).upper() == AL_PHENOTYPE
    ]
    attr_rows = [
        row for row in rows
        if str(_value(row, "phenotype", "")).upper() in ATTR_PHENOTYPES
    ]
    al_pass = any(str(_value(row, "status", "")).upper() == "PHENOTYPE_PASS" for row in al_rows)
    attr_pass = any(str(_value(row, "status", "")).upper() == "PHENOTYPE_PASS" for row in attr_rows)
    routes = []
    source_guardrail_ids = []
    source_routes = []
    approved_routes = {
        "ALEVALUATIONORAMYLOIDTYPING": "V39",
        "ALEVALUATION": "WT25",
        "ALINTERPRETATIONREVIEW": "WT26",
        "URGENTALEVALUATION": "WT27",
    }
    approved_guardrails = {"V39", "WT25", "WT26", "WT27"}
    for row in attr_rows:
        for guardrail_id in (_value(row, "guardrail_ids", ()) or ()):
            normalized_guardrail = _normalized_route(guardrail_id)
            if normalized_guardrail in approved_guardrails:
                source_guardrail_ids.append(str(guardrail_id))
                routes.append(normalized_guardrail)
        for route in (_value(row, "parallel_routes", ()) or ()):
            source_route = str(route)
            normalized = approved_routes.get("".join(ch for ch in source_route.upper() if ch.isalnum()))
            if normalized:
                source_routes.append(source_route)
                routes.append(normalized)
    routes = list(dict.fromkeys(routes))
    source_guardrail_ids = list(dict.fromkeys(source_guardrail_ids))
    source_routes = list(dict.fromkeys(source_routes))
    concurrence = al_pass and attr_pass
    return {
        "annotation": "ATTR_AL_DIFFERENTIAL",
        "al_pass": al_pass,
        "attr_pass": attr_pass,
        "concurrent_pass": concurrence,
        "normalized_attr_al_routes": routes,
        "source_guardrail_ids": source_guardrail_ids,
        "source_routes": source_routes,
        "agreement_strength": (
            "CONCORDANT_DIFFERENTIAL_EVIDENCE" if concurrence and routes
            else "CROSS_PHENOTYPE_CONCURRENCE" if concurrence
            else "AL_PASS_ONLY" if al_pass
            else "NONE"
        ),
        "visible": al_pass,
    }


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
    differential = cross_phenotype_attr_al_annotation(patient_router)
    target = str(screening_target).upper()
    if target == "ATTR":
        target_verdict = aggregate_attr_verdict(patient_router)
        matched_combination_ids = {
            str(_value(row, "matched_combination_id"))
            for row in patient_router
            if str(_value(row, "phenotype", "")).upper() in ATTR_PHENOTYPES
            and str(_value(row, "status", "")).upper() == "PHENOTYPE_PASS"
            and _value(row, "matched_combination_id") not in (None, "")
        }
    else:
        if target not in PHENOTYPE_ORDER:
            raise ValueError(
                f"Unsupported screening target {target!r}; expected ATTR or one of {PHENOTYPE_ORDER}"
            )
        target_verdict = next(item for item in verdicts if item["phenotype"] == target)
        matched_combination_ids = {
            str(_value(row, "matched_combination_id"))
            for row in patient_router
            if str(_value(row, "phenotype", "")).upper() == target
            and _value(row, "matched_combination_id") not in (None, "")
        }

    matched_combinations = [
        row for row in patient_combinations
        if str(_value(row, "combination_id")) in matched_combination_ids
        and str(_value(row, "status", "")).upper() == "TRUE"
    ]
    rationale_evidence_ids: set[str] = set()
    for matched_combination in matched_combinations:
        rationale_evidence_ids.update(_supporting_evidence_ids(
            _value(matched_combination, "selected_witnesses", ()) or ()
        ))

    clinical_reasons = []
    seen_reasons: set[tuple[str, str, str]] = set()
    for evidence in patient_evidence:
        if str(_value(evidence, "status", "")).upper() != "TRUE":
            continue
        if matched_combinations and str(_value(evidence, "evidence_id", "")) not in rationale_evidence_ids:
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
            "suspicion_level": target_verdict["suspicion_level"],
            "passed_phenotypes": target_verdict.get("passed_phenotypes", [target]),
            "highest_suspicion_phenotypes": target_verdict.get(
                "highest_suspicion_phenotypes", [target]
            ),
            "screening_only_not_diagnosis": True,
        },
        "clinical_rationale": {
            "summary": target_verdict.get("reason"),
            "findings": clinical_reasons,
            "parallel_routes": target_verdict.get("parallel_routes", []),
            "cross_phenotype_annotations": [differential] if differential["visible"] else [],
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
    priority_classes: Sequence[str] | None = None,
    suspicion_levels: Sequence[str] | None = ("HIGHEST_SUSPICION", "HIGH_SUSPICION"),
) -> list[str]:
    accepted = {status.upper() for status in statuses}
    accepted_levels = normalized_suspicion_levels(
        priority_classes if priority_classes is not None else suspicion_levels
    )
    ids = {
        str(_value(row, "patient_id"))
        for row in router_rows
        if str(_value(row, "phenotype", "")).upper() == phenotype.upper()
        and str(_value(row, "status", "")).upper() in accepted
        and (
            accepted_levels is None
            or suspicion_level(_value(row, "priority_class")) in accepted_levels
        )
        and _value(row, "patient_id") not in (None, "")
    }
    return sorted(ids)


def flagged_attr_patient_ids(
    router_rows: Iterable[Any],
    *,
    suspicion_levels: Sequence[str] | None = ("HIGHEST_SUSPICION", "HIGH_SUSPICION"),
) -> list[str]:
    """Return patients whose combined ATTRv/ATTRwt verdict meets threshold."""
    rows = list(router_rows)
    accepted_levels = normalized_suspicion_levels(suspicion_levels)
    patient_ids = sorted({
        str(_value(row, "patient_id"))
        for row in rows
        if str(_value(row, "phenotype", "")).upper() in ATTR_PHENOTYPES
        and _value(row, "patient_id") not in (None, "")
    })
    output = []
    for patient_id in patient_ids:
        verdict = aggregate_attr_verdict(_patient(rows, patient_id))
        if verdict["status"] != "ATTR_SUSPICION":
            continue
        if accepted_levels is None or verdict["suspicion_level"] in accepted_levels:
            output.append(patient_id)
    return output


def flagged_al_detected_patient_ids(router_rows: Iterable[Any]) -> list[str]:
    """Return every patient with an AL phenotype pass at any tier."""
    rows = list(router_rows)
    patient_ids = sorted({
        str(_value(row, "patient_id"))
        for row in rows
        if _value(row, "patient_id") not in (None, "")
    })
    output: list[str] = []
    for patient_id in patient_ids:
        patient_rows = _patient(rows, patient_id)
        al_pass = any(
            str(_value(row, "phenotype", "")).upper() == AL_PHENOTYPE
            and str(_value(row, "status", "")).upper() == "PHENOTYPE_PASS"
            for row in patient_rows
        )
        if al_pass:
            output.append(patient_id)
    return output


def profiles_jsonl_bytes(profiles: Iterable[Mapping[str, Any]], *, include_proprietary_trace: bool = False) -> bytes:
    rows = [(_plain(profile) if include_proprietary_trace else strip_proprietary_trace(profile)) for profile in profiles]
    return ("\n".join(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows) + ("\n" if rows else "")).encode("utf-8")


def profiles_csv_bytes(profiles: Iterable[Mapping[str, Any]]) -> bytes:
    """Return a compact, trace-free CSV index suitable for notebook download."""
    output = io.StringIO(newline="")
    fields = [
        "run_id", "patient_id", "screening_target", "screening_status",
        "review_route", "suspicion_level",
        "attrv_status", "attrv_suspicion_level", "attrv_review_route",
        "attrwt_status", "attrwt_suspicion_level", "attrwt_review_route",
        "al_status", "al_suspicion_level", "al_review_route",
        "clinical_rationale",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for profile in profiles:
        clean = strip_proprietary_trace(profile)
        diagnosis = clean.get("suspected_diagnosis", {})
        rationale = clean.get("clinical_rationale", {})
        verdicts = {
            str(row.get("phenotype", "")).upper(): row
            for row in clean.get("phenotype_verdicts", [])
        }
        attrv = verdicts.get("ATTRV", {})
        attrwt = verdicts.get("ATTRWT", {})
        al = verdicts.get("AL", {})
        writer.writerow({
            "run_id": clean.get("run_id"),
            "patient_id": clean.get("patient_id"),
            "screening_target": diagnosis.get("screening_target"),
            "screening_status": diagnosis.get("status"),
            "review_route": diagnosis.get("review_route"),
            "suspicion_level": diagnosis.get("suspicion_level"),
            "attrv_status": attrv.get("status"),
            "attrv_suspicion_level": attrv.get("suspicion_level"),
            "attrv_review_route": attrv.get("result_route"),
            "attrwt_status": attrwt.get("status"),
            "attrwt_suspicion_level": attrwt.get("suspicion_level"),
            "attrwt_review_route": attrwt.get("result_route"),
            "al_status": al.get("status"),
            "al_suspicion_level": al.get("suspicion_level"),
            "al_review_route": al.get("result_route"),
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
    """Write combined and suspicion-tiered local patient-profile exports."""
    rows = list(profiles)
    target = Path(output_dir).expanduser().resolve()
    detected = target / "detected"
    detected.mkdir(parents=True, exist_ok=True)
    jsonl = detected / f"{basename}.jsonl"
    csv_path = detected / f"{basename}.csv"
    jsonl.write_bytes(profiles_jsonl_bytes(rows, include_proprietary_trace=include_proprietary_trace))
    csv_path.write_bytes(profiles_csv_bytes(rows))
    output = {"jsonl": str(jsonl), "csv": str(csv_path)}
    for level, folder_name in SUSPICION_FOLDER.items():
        tier_dir = detected / folder_name
        tier_dir.mkdir(parents=True, exist_ok=True)
        tier_rows = [
            profile for profile in rows
            if str(profile.get("suspected_diagnosis", {}).get("suspicion_level") or "").upper() == level
        ]
        tier_jsonl = tier_dir / f"{basename}.jsonl"
        tier_csv = tier_dir / f"{basename}.csv"
        tier_jsonl.write_bytes(profiles_jsonl_bytes(
            tier_rows,
            include_proprietary_trace=include_proprietary_trace,
        ))
        tier_csv.write_bytes(profiles_csv_bytes(tier_rows))
        key = folder_name.lower()
        output[f"{key}_jsonl"] = str(tier_jsonl)
        output[f"{key}_csv"] = str(tier_csv)
    return output


def export_al_detected_profiles(
    profiles: Iterable[Mapping[str, Any]],
    output_dir: str | Path,
    *,
    basename: str = "al_detected_patient_profiles",
    include_proprietary_trace: bool = False,
) -> dict[str, str]:
    """Write every AL-detected profile under a separate output root."""
    target = Path(output_dir).expanduser().resolve() / "al_detected"
    return export_profiles(
        list(profiles),
        target,
        basename=basename,
        include_proprietary_trace=include_proprietary_trace,
    )


def build_known_attr_profile(
    patient: Any,
    *,
    known_config: Any,
    source_events: Iterable[Any],
    evidence_events: Iterable[Any] = (),
    demographics: Mapping[str, Any] | None = None,
    include_proprietary_trace: bool = True,
) -> dict[str, Any]:
    """Build a separate profile for a patient excluded before screening."""
    patient_id = str(_value(patient, "patient_id", ""))
    patient_source = _patient(source_events, patient_id)
    patient_evidence = _patient(evidence_events, patient_id)
    names = _atom_names(known_config)
    matched_values = list(_value(patient, "matched_config_values", ()) or ())
    event_dates = list(_value(patient, "event_dates", ()) or ())
    profile = {
        "run_id": _value(patient, "run_id"),
        "patient_id": patient_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "demographics": _plain(dict(demographics or {})),
        "medical_profile": {
            "timeline": _medical_timeline(patient_source, patient_evidence, names),
            "event_count": len(patient_source),
        },
        "known_diagnosis": {
            "status": "KNOWN_ATTR_OR_AMYLOIDOSIS",
            "confirmation_scope": _value(patient, "confirmation_scope"),
            "excluded_from_early_detection": True,
            "source_recognition_not_new_diagnosis": True,
        },
        "clinical_rationale": {
            "summary": "Existing ATTR-specific or corroborated amyloidosis evidence was present before screening.",
            "matched_source_values": matched_values,
            "event_dates": event_dates,
        },
    }
    if include_proprietary_trace:
        profile["proprietary_pipeline_trace"] = {
            "known_attr_record": _plain(patient),
            "known_attr_evidence": _plain(patient_evidence),
        }
    return profile


def known_attr_profiles_csv_bytes(profiles: Iterable[Mapping[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    fields = [
        "run_id", "patient_id", "status", "confirmation_scope",
        "excluded_from_early_detection", "matched_source_values", "event_dates",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for profile in profiles:
        clean = strip_proprietary_trace(profile)
        diagnosis = clean.get("known_diagnosis", {})
        rationale = clean.get("clinical_rationale", {})
        writer.writerow({
            "run_id": clean.get("run_id"),
            "patient_id": clean.get("patient_id"),
            "status": diagnosis.get("status"),
            "confirmation_scope": diagnosis.get("confirmation_scope"),
            "excluded_from_early_detection": diagnosis.get("excluded_from_early_detection"),
            "matched_source_values": ";".join(str(value) for value in rationale.get("matched_source_values", [])),
            "event_dates": ";".join(str(value) for value in rationale.get("event_dates", [])),
        })
    return output.getvalue().encode("utf-8-sig")


def export_known_attr_profiles(
    profiles: Iterable[Mapping[str, Any]],
    output_dir: str | Path,
    *,
    basename: str = "known_attr_patient_profiles",
    include_proprietary_trace: bool = False,
) -> dict[str, str]:
    rows = list(profiles)
    target = Path(output_dir).expanduser().resolve() / "confirmed"
    target.mkdir(parents=True, exist_ok=True)
    jsonl = target / f"{basename}.jsonl"
    csv_path = target / f"{basename}.csv"
    jsonl.write_bytes(profiles_jsonl_bytes(rows, include_proprietary_trace=include_proprietary_trace))
    csv_path.write_bytes(known_attr_profiles_csv_bytes(rows))
    return {"jsonl": str(jsonl), "csv": str(csv_path)}


def build_known_al_profile(
    patient: Any,
    *,
    known_config: Any,
    source_events: Iterable[Any],
    evidence_events: Iterable[Any] = (),
    demographics: Mapping[str, Any] | None = None,
    include_proprietary_trace: bool = True,
) -> dict[str, Any]:
    """Build a separate profile for a known/confirmed AL recognition route."""
    patient_id = str(_value(patient, "patient_id", ""))
    patient_source = _patient(source_events, patient_id)
    patient_evidence = _patient(evidence_events, patient_id)
    names = _atom_names(known_config)
    matched_values = list(_value(patient, "matched_config_values", ()) or ())
    event_dates = list(_value(patient, "event_dates", ()) or ())
    profile = {
        "run_id": _value(patient, "run_id"),
        "patient_id": patient_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "demographics": _plain(dict(demographics or {})),
        "medical_profile": {
            "timeline": _medical_timeline(patient_source, patient_evidence, names),
            "event_count": len(patient_source),
        },
        "known_diagnosis": {
            "status": "KNOWN_AL",
            "confirmation_scope": _value(patient, "confirmation_scope"),
            "excluded_from_early_detection": True,
            "source_recognition_not_new_diagnosis": True,
        },
        "clinical_rationale": {
            "summary": "Existing AL-specific evidence was present before screening.",
            "matched_source_values": matched_values,
            "event_dates": event_dates,
        },
    }
    if include_proprietary_trace:
        profile["proprietary_pipeline_trace"] = {
            "known_al_record": _plain(patient),
            "known_al_evidence": _plain(patient_evidence),
        }
    return profile


def known_al_profiles_csv_bytes(profiles: Iterable[Mapping[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    fields = [
        "run_id", "patient_id", "status", "confirmation_scope",
        "excluded_from_early_detection", "matched_source_values", "event_dates",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for profile in profiles:
        clean = strip_proprietary_trace(profile)
        diagnosis = clean.get("known_diagnosis", {})
        rationale = clean.get("clinical_rationale", {})
        writer.writerow({
            "run_id": clean.get("run_id"),
            "patient_id": clean.get("patient_id"),
            "status": diagnosis.get("status"),
            "confirmation_scope": diagnosis.get("confirmation_scope"),
            "excluded_from_early_detection": diagnosis.get("excluded_from_early_detection"),
            "matched_source_values": ";".join(str(value) for value in rationale.get("matched_source_values", [])),
            "event_dates": ";".join(str(value) for value in rationale.get("event_dates", [])),
        })
    return output.getvalue().encode("utf-8-sig")


def export_known_al_profiles(
    profiles: Iterable[Mapping[str, Any]],
    output_dir: str | Path,
    *,
    basename: str = "known_al_patient_profiles",
    include_proprietary_trace: bool = False,
) -> dict[str, str]:
    rows = list(profiles)
    target = Path(output_dir).expanduser().resolve() / "known_al" / "confirmed"
    target.mkdir(parents=True, exist_ok=True)
    jsonl = target / f"{basename}.jsonl"
    csv_path = target / f"{basename}.csv"
    jsonl.write_bytes(profiles_jsonl_bytes(rows, include_proprietary_trace=include_proprietary_trace))
    csv_path.write_bytes(known_al_profiles_csv_bytes(rows))
    return {"jsonl": str(jsonl), "csv": str(csv_path)}


__all__ = [
    "PHENOTYPE_ORDER",
    "ATTR_PHENOTYPES",
    "AL_PHENOTYPE",
    "aggregate_attr_verdict",
    "cross_phenotype_attr_al_annotation",
    "build_patient_profile",
    "strip_proprietary_trace",
    "flagged_patient_ids",
    "flagged_attr_patient_ids",
    "flagged_al_detected_patient_ids",
    "profiles_jsonl_bytes",
    "profiles_csv_bytes",
    "export_profiles",
    "export_al_detected_profiles",
    "build_known_attr_profile",
    "known_attr_profiles_csv_bytes",
    "export_known_attr_profiles",
    "build_known_al_profile",
    "known_al_profiles_csv_bytes",
    "export_known_al_profiles",
]

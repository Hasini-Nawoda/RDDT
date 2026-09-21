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
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..config_loader import PHENOTYPE_SLOTS
from ..reasoning.risk_labels import (
    SUSPICION_FOLDER,
    normalized_suspicion_levels,
    suspicion_level,
)
from ..warehouse.source_schema import is_table_profile_enabled

PHENOTYPE_ORDER = PHENOTYPE_SLOTS
ATTR_PHENOTYPES = ("ATTRV", "ATTRWT")
AL_PHENOTYPE = "AL"
_SUSPICION_RANK = {
    "HIGHEST_SUSPICION": 0,
    "HIGH_SUSPICION": 1,
    "MODERATE_SUSPICION": 2,
}


def _case_value(item: Any, *names: str, default: Any = None) -> Any:
    """Read a value from a notebook/Snowpark-style row case-insensitively."""
    if hasattr(item, "as_dict"):
        try:
            item = item.as_dict()
        except Exception:
            pass
    if isinstance(item, Mapping):
        wanted = {
            str(name).strip('"').upper()
            for name in names
            if name not in (None, "")
        }
        for key, value in item.items():
            if str(key).strip('"').upper() in wanted:
                return value
    for name in names:
        if name in (None, ""):
            continue
        value = getattr(item, name, None)
        if value is not None:
            return value
    return default


def _row_dict(item: Any) -> dict[str, Any]:
    """Convert a pandas/Snowpark row or mapping to a JSON-friendly dict."""
    if hasattr(item, "as_dict"):
        try:
            item = item.as_dict()
        except Exception:
            pass
    if isinstance(item, Mapping):
        return {str(key): _plain(value) for key, value in item.items()}
    if hasattr(item, "__dict__"):
        return {
            str(key): _plain(value)
            for key, value in vars(item).items()
        }
    return _plain(item)


def _profile_values(value: Any) -> list[str]:
    """Split the comma/semicolon-delimited summary fields emitted by SQL."""
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(item) for item in value if item not in (None, "")]
    pieces = [str(value)]
    for delimiter in ("|", ";", ",", "\r\n", "\n", "\r"):
        pieces = [part for piece in pieces for part in piece.split(delimiter)]
    return [piece.strip() for piece in pieces if piece.strip()]


def _canonical_icd10(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "").replace(".", "")


def _claim_record(row: Any) -> dict[str, Any]:
    """Return the full source CLAIMS record from a detail row.

    The SQL notebook may wrap the record under SOURCE_CLAIM to keep the
    match annotations separate.  Raw rows are accepted as well, which keeps
    this helper usable in local tests and in a Snowpark ``to_local_iterator``.
    """
    wrapped = _case_value(row, "SOURCE_CLAIM", "RAW_RECORD", "CLAIM_ROW")
    if wrapped is not None:
        if isinstance(wrapped, str):
            try:
                parsed = json.loads(wrapped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, Mapping):
                wrapped = parsed
        return _row_dict(wrapped)
    raw = _row_dict(row)
    # SQL annotations are not source data and should not be duplicated in the
    # patient's complete claim record.
    for key in list(raw):
        if str(key).strip('"').upper() in {
            "MATCHED_CODE", "MATCHED_ICD10_CODE", "MATCHED_ICD10_CODES",
            "NORMALIZED_CODE", "DIAGNOSIS_SYSTEM", "MATCHED", "IS_MATCH",
            "AMYLOIDOSIS_TYPE", "SUBTYPE_LABEL", "AMYLOIDOSIS_SUBTYPE",
            "RISK_LABEL", "PRIORITY_LABEL", "CONFIRMATION_SCOPE",
        }:
            raw.pop(key, None)
    return raw


def _claim_code(row: Any, raw: Mapping[str, Any]) -> Any:
    source_value = _case_value(
        raw, "DIAGNOSIS_CODE", "DIAGNOSISCODE", "COLUMN8", "CODE_VALUE", "CODE"
    )
    if source_value not in (None, ""):
        return source_value
    return _case_value(row, "DIAGNOSIS_CODE", "CODE_VALUE", "CODE", "NORMALIZED_CODE")


def _claim_system(row: Any, raw: Mapping[str, Any]) -> Any:
    source_value = _case_value(raw, "DIAGNOSIS_TYPE", "DIAGNOSISTYPE", "COLUMN7", "CODE_SYSTEM")
    if source_value not in (None, ""):
        return source_value
    return _case_value(row, "DIAGNOSIS_SYSTEM", "DIAGNOSIS_TYPE", "CODE_SYSTEM")


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
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
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
            "evaluation_mode": _value(row, "evaluation_mode", "STRICT"),
            "provisional": bool(_value(row, "provisional", False)),
            "relaxations": _plain(_value(row, "relaxations", [])),
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
    strict_passing = [
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
    recall_passing = [
        row for row in rows
        if str(_value(row, "status", "")).upper() == "CLAIMS_RECALL_CANDIDATE"
        and str(
            _value(
                row,
                "suspicion_level",
                suspicion_level(_value(row, "priority_class")),
            )
            or ""
        ).upper() in _SUSPICION_RANK
    ]
    passing = strict_passing or recall_passing
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
            "status": "ATTR_SUSPICION" if strict_passing else "ATTR_CLAIMS_RECALL_CANDIDATE",
            "result_route": "ATTR_EARLY_DETECTION_REVIEW",
            "suspicion_level": best_level,
            "passed_phenotypes": passed_phenotypes,
            "highest_suspicion_phenotypes": highest_phenotypes,
            "parallel_routes": parallel_routes,
            "provisional": not bool(strict_passing),
            "relaxations": list(dict.fromkeys(
                str(reason)
                for row in passing
                for reason in (_value(row, "relaxations", ()) or ())
                if reason
            )),
            "reason": (
                "ATTR early-detection criteria were met by "
                + " and ".join(passed_phenotypes)
                + (
                    "; the combined tier uses the highest phenotype suspicion."
                    if strict_passing
                    else "; claims-only assumptions require clinical review before strict promotion."
                )
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


def _logical_source_value(
    row: Mapping[str, Any],
    table: Mapping[str, Any],
    logical_name: str,
) -> Any:
    physical_name = table.get("columns", {}).get(logical_name)
    return _case_value(row, logical_name, physical_name) if physical_name else _case_value(row, logical_name)


def _ehr_payload(
    patient_id: str,
    records_by_table: Mapping[str, Iterable[Any]] | None,
    source_config: Mapping[str, Any] | None,
    source_coverage: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Preserve every native EHR row for one patient, grouped by source table."""
    records_by_table = records_by_table or {}
    tables_config = (source_config or {}).get("tables", {})
    coverage = dict(source_coverage or {})
    ordered_keys = list(dict.fromkeys([*tables_config.keys(), *records_by_table.keys()]))
    table_payloads: dict[str, Any] = {}
    total_records = 0
    incomplete: list[str] = []
    for table_key in ordered_keys:
        table = tables_config.get(table_key, {})
        profile_enabled = is_table_profile_enabled(table)
        rows_present = table_key in records_by_table
        patient_column = table.get("columns", {}).get("patient_id")
        patient_rows: list[dict[str, Any]] = []
        if rows_present:
            for item in records_by_table.get(table_key, ()):
                raw = _claim_record(item) if _case_value(item, "SOURCE_CLAIM", "RAW_RECORD") is not None else _row_dict(item)
                row_patient = _case_value(raw, "patient_id", patient_column)
                if row_patient in (None, "") or str(row_patient) == str(patient_id):
                    patient_rows.append(raw)
        coverage_row = coverage.get(table_key)
        if isinstance(coverage_row, Mapping):
            status = str(coverage_row.get("status") or "UNKNOWN")
            coverage_detail = _plain(coverage_row)
        else:
            status = (
                "QUERIED" if rows_present
                else "NOT_REQUESTED" if not profile_enabled
                else "NOT_HYDRATED"
            )
            coverage_detail = {"status": status}
        if profile_enabled and status not in {"QUERIED", "QUERIED_NO_ROWS"}:
            incomplete.append(str(table_key))
        total_records += len(patient_rows)
        table_payloads[str(table_key)] = {
            "physical_table": table.get("name", table_key),
            "profile_enabled": profile_enabled,
            "column_map": _plain(table.get("columns", {})),
            "coverage": coverage_detail,
            "record_count": len(patient_rows),
            "records": patient_rows,
        }
    return {
        "completeness_status": (
            "COMPLETE_FOR_CONFIGURED_AVAILABLE_TABLES" if not incomplete
            else "INCOMPLETE_PROFILE_HYDRATION"
        ),
        "incomplete_tables": incomplete,
        "table_count": len(table_payloads),
        "total_record_count": total_records,
        "records_by_table": table_payloads,
    }


def _ehr_record_timeline(ehr: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Create a one-native-row-per-entry review timeline from the full EHR."""
    timeline: list[dict[str, Any]] = []
    for table_key, table_payload in ehr.get("records_by_table", {}).items():
        column_map = table_payload.get("column_map", {})
        reverse = {str(physical).upper(): logical for logical, physical in column_map.items()}
        for index, raw in enumerate(table_payload.get("records", [])):
            logical = {
                reverse.get(str(key).strip('"').upper(), str(key)): value
                for key, value in raw.items()
            }
            event_date = next((logical.get(name) for name in (
                "event_date", "observation_datetime", "encounter_date",
                "service_from_date", "from_date", "service_to_date", "to_date",
            ) if logical.get(name) not in (None, "")), None)
            code_value = next((logical.get(name) for name in (
                "diagnosis_code", "observation_identifier", "snomed",
                "procedure_code", "drg_code", "rev_code",
            ) if logical.get(name) not in (None, "")), None)
            text_value = next((logical.get(name) for name in (
                "clinical_notes", "note_text", "lab_result_note", "value",
                "condition", "medication_name",
            ) if logical.get(name) not in (None, "")), None)
            timeline.append({
                "source_table": table_key.upper(),
                "physical_table": table_payload.get("physical_table"),
                "source_record_index": index,
                "event_date": _plain(event_date),
                "encounter_id": logical.get("encounter_id"),
                "code_system": logical.get("diagnosis_type"),
                "code_value": _plain(code_value),
                "text_value": _plain(text_value),
                "result_value": _plain(logical.get("observation_value")),
                "result_status": _plain(logical.get("result_status") or logical.get("status")),
                "raw_record": raw,
                "clinical_meanings": [],
            })
    timeline.sort(key=lambda row: (
        str(row.get("event_date") or ""),
        str(row.get("source_table") or ""),
        int(row.get("source_record_index") or 0),
    ))
    return timeline


def _confirmation_profile_sections(
    summary: Mapping[str, Any],
    evidence_rows: Iterable[Any],
    *,
    source_table: str,
) -> dict[str, Any]:
    """Assemble confirmed-diagnosis and audit sections for the unified builder."""
    configured_codes = _profile_values(_case_value(summary, "MATCHED_ICD10_CODES", default=[]))
    configured_values = _profile_values(_case_value(
        summary, "MATCHED_SOURCE_VALUES", "matched_source_values", default=[]
    )) or configured_codes
    rule_ids = _profile_values(_case_value(
        summary, "CONFIRMATION_RULE_IDS", "confirmation_rule_ids", default=[]
    ))
    confirmation_kind = str(_case_value(
        summary,
        "CONFIRMATION_KIND",
        "confirmation_kind",
        default="EXACT_CONFIGURED_ICD10",
    ) or "EXACT_CONFIGURED_ICD10").upper()
    is_exact_icd10 = confirmation_kind == "EXACT_CONFIGURED_ICD10"
    evidence: list[dict[str, Any]] = []
    for row in evidence_rows:
        raw = _claim_record(row)
        matched_code = _case_value(row, "MATCHED_CODE", "MATCHED_ICD10_CODE")
        provenance = _case_value(row, "source_provenance", "SOURCE_PROVENANCE", default={}) or {}
        if matched_code in (None, ""):
            matched_code = _case_value(provenance, "matched_config_value", "MATCHED_CONFIG_VALUE")
        if matched_code in (None, ""):
            matched_code = _claim_code(row, raw)
        match_method = _case_value(row, "MATCH_METHOD", "match_method")
        if match_method in (None, ""):
            match_method = _case_value(provenance, "match_method", "MATCH_METHOD")
        evidence_item = {
            "matched_icd10_code": _plain(matched_code),
            "normalized_code": _canonical_icd10(matched_code),
            "diagnosis_system": _plain(_claim_system(row, raw)),
            "amyloidosis_type": _plain(_case_value(row, "AMYLOIDOSIS_TYPE")),
            "subtype_label": _plain(_case_value(row, "AMYLOIDOSIS_SUBTYPE", "SUBTYPE_LABEL")),
            "risk_label": _plain(_case_value(row, "RISK_LABEL", default="CONFIRMED")),
            "priority_label": _plain(_case_value(row, "PRIORITY_LABEL", default="CONFIRMED")),
            "confirmation_scope": _plain(_case_value(row, "CONFIRMATION_SCOPE")),
            "match_method": match_method or confirmation_kind,
            "source_table": source_table,
            "source_record": raw,
        }
        if is_exact_icd10:
            evidence_item["source_claim"] = raw
        evidence.append(evidence_item)
    matched_values = list(dict.fromkeys(
        str(item.get("matched_icd10_code")) for item in evidence
        if item.get("matched_icd10_code") not in (None, "")
    )) or configured_values
    matched_codes = matched_values if is_exact_icd10 else configured_codes
    types = _profile_values(_case_value(summary, "AMYLOIDOSIS_TYPES", "AMYLOIDOSIS_TYPE"))
    subtype_value = _case_value(summary, "AMYLOIDOSIS_SUBTYPES", "AMYLOIDOSIS_SUBTYPE")
    subtypes = (
        [str(item).strip() for item in subtype_value if str(item).strip()]
        if isinstance(subtype_value, (list, tuple, set, frozenset))
        else [item.strip() for item in str(subtype_value or "").split("|") if item.strip()]
    )
    scopes = _profile_values(_case_value(summary, "CONFIRMATION_SCOPES", "CONFIRMATION_SCOPE"))
    subtype_risks = []
    normalized_codes = {_canonical_icd10(code) for code in matched_codes}
    if "E8582" in normalized_codes:
        subtype_risks.append("ATTRWT")
    if "E8581" in normalized_codes:
        subtype_risks.append("AL")
    if "E853" in normalized_codes:
        subtype_risks.append("AA")
    risk_for = list(dict.fromkeys([*(types or ["AMYLOIDOSIS"]), *subtype_risks]))
    assessments = [{
        "risk_for": item,
        "status": "CONFIRMED",
        "risk_level": "CONFIRMED",
        "review_route": next((row.get("confirmation_scope") for row in evidence if row.get("amyloidosis_type") == item), None),
        "reason": (
            f"Exact configured ICD-10 amyloidosis evidence confirmed {item}."
            if is_exact_icd10
            else f"The configured pre-screen confirmation route confirmed {item}."
        ),
    } for item in risk_for]
    return {
        "known_diagnosis": {
            "status": "CONFIRMED_AMYLOIDOSIS",
            "confirmation_scope": scopes or ["KNOWN_AMYLOIDOSIS"],
            "amyloidosis_types": types,
            "amyloidosis_subtypes": subtypes,
            "matched_icd10_codes": matched_codes,
            "matched_source_values": matched_values,
            "risk_label": _case_value(summary, "RISK_LABEL", default="CONFIRMED"),
            "priority_label": _case_value(summary, "PRIORITY_LABEL", default="CONFIRMED"),
            "excluded_from_early_detection": True,
            "source_recognition_not_new_diagnosis": True,
        },
        "phenotype_risk_assessments": assessments,
        "clinical_rationale": {
            "summary": (
                "Confirmed by exact configured ICD-10 amyloidosis evidence before suspicion scoring."
                if is_exact_icd10
                else "Confirmed by the configured pre-screen recognition route before suspicion scoring."
            ),
            "rule": (
                "ALL_AMYLOIDOSIS_EXACT_ICD10_E85_ALLOW_LIST"
                if is_exact_icd10
                else confirmation_kind
            ),
            "confirmation_rule_ids": rule_ids,
            "confirmation_kind": confirmation_kind,
            "matched_icd10_codes": matched_codes,
            "matched_source_values": matched_values,
            "findings": [
                {
                    "clinical_finding": (
                        item.get("subtype_label")
                        or item.get("amyloidosis_type")
                        or "Configured confirmed-patient evidence"
                    ),
                    "matched_value": item.get("matched_icd10_code"),
                    "source_table": item.get("source_table"),
                    "match_method": item.get("match_method"),
                }
                for item in evidence
            ],
            "matched_claim_evidence": evidence,
            "evidence_count": len(evidence),
        },
        "algorithm_analysis": {
            "outcome_path": "CONFIRMED_PRE_SCREEN",
            "steps": [
                {
                    "step": (
                        "CONFIRMED_ICD10_LOOKUP"
                        if is_exact_icd10
                        else "CONFIGURED_CONFIRMATION_ROUTE"
                    ),
                    "status": "MATCHED",
                    "reason": (
                        "At least one exact configured ICD-10 amyloidosis code was found."
                        if is_exact_icd10
                        else "At least one configured confirmation rule was satisfied."
                    ),
                    "confirmation_kind": confirmation_kind,
                    "confirmation_rule_ids": rule_ids,
                    "evidence": evidence,
                },
                {
                    "step": "SUSPICION_PIPELINE",
                    "status": "NOT_RUN",
                    "reason": "Confirmed patients are removed before suspicion scoring.",
                },
            ],
        },
    }


def build_patient_profile(
    patient_id: str,
    *,
    config: Any = None,
    screening_target: str | None = None,
    router_rows: Iterable[Any] = (),
    source_events: Iterable[Any] = (),
    evidence_events: Iterable[Any] = (),
    signal_hits: Iterable[Any] = (),
    bucket_state: Iterable[Any] = (),
    combination_hits: Iterable[Any] = (),
    guardrail_hits: Iterable[Any] = (),
    demographics: Mapping[str, Any] | None = None,
    ehr_records_by_table: Mapping[str, Iterable[Any]] | None = None,
    source_config: Mapping[str, Any] | None = None,
    source_coverage: Mapping[str, Any] | None = None,
    confirmation_summary: Mapping[str, Any] | None = None,
    confirmation_evidence: Iterable[Any] = (),
    confirmation_source_table: str = "CLAIMS",
    include_proprietary_trace: bool = True,
    run_id: str | None = None,
    config_hash: str | None = None,
) -> dict[str, Any]:
    """Build one complete EHR profile for either confirmation or suspicion."""
    ehr = _ehr_payload(
        str(patient_id), ehr_records_by_table, source_config, source_coverage
    )
    if confirmation_summary is not None:
        sections = _confirmation_profile_sections(
            confirmation_summary,
            confirmation_evidence,
            source_table=confirmation_source_table,
        )
        profile = {
            "run_id": run_id or _case_value(confirmation_summary, "RUN_ID", "run_id"),
            "patient_id": str(patient_id),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "diagnosis_state": "CONFIRMED",
            "demographics": _plain(dict(demographics or {})),
            "ehr": ehr,
            "medical_profile": {
                "timeline": _ehr_record_timeline(ehr),
                "event_count": ehr["total_record_count"],
            },
            **sections,
        }
        if include_proprietary_trace:
            profile["proprietary_pipeline_trace"] = {
                "confirmed_config_hash": config_hash,
                "pipeline_scope": "CONFIRMED_PRE_SCREEN_WITH_FULL_EHR_HYDRATION",
            }
        return profile

    if screening_target is None:
        raise ValueError("screening_target is required for a suspicion-pipeline profile")
    patient_router = _patient(router_rows, patient_id)
    patient_source = _patient(source_events, patient_id)
    patient_evidence = _patient(evidence_events, patient_id)
    patient_signals = _patient(signal_hits, patient_id)
    patient_buckets = _patient(bucket_state, patient_id)
    patient_combinations = _patient(combination_hits, patient_id)
    patient_guardrails = _patient(guardrail_hits, patient_id)
    names = _atom_names(config) if config is not None else {}
    verdicts = _verdicts(patient_router)
    differential = cross_phenotype_attr_al_annotation(patient_router)
    target = str(screening_target).upper()
    if target == "ATTR":
        target_verdict = aggregate_attr_verdict(patient_router)
        matched_combination_ids = {
            str(_value(row, "matched_combination_id"))
            for row in patient_router
            if str(_value(row, "phenotype", "")).upper() in ATTR_PHENOTYPES
            and str(_value(row, "status", "")).upper() in {"PHENOTYPE_PASS", "CLAIMS_RECALL_CANDIDATE"}
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

    risk_assessments = [
        {
            "risk_for": verdict["phenotype"],
            "status": verdict["status"],
            "risk_level": verdict["suspicion_level"] or "NOT_FLAGGED",
            "review_route": verdict["result_route"],
            "reason": verdict["reason"],
        }
        for verdict in verdicts
    ]
    if target == "ATTR":
        risk_assessments.insert(0, {
            "risk_for": "ATTR",
            "status": target_verdict["status"],
            "risk_level": target_verdict["suspicion_level"] or "NOT_FLAGGED",
            "review_route": target_verdict["result_route"],
            "reason": target_verdict["reason"],
        })

    profile = {
        "run_id": run_id or next((str(_value(row, "run_id")) for row in patient_router if _value(row, "run_id") is not None), None),
        "patient_id": str(patient_id),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "diagnosis_state": (
            "CLAIMS_RECALL_CANDIDATE"
            if "CLAIMS_RECALL_CANDIDATE" in str(target_verdict.get("status", "")).upper()
            else "SUSPICION_FLAGGED"
        ),
        "demographics": _plain(dict(demographics or {})),
        "ehr": ehr,
        "medical_profile": {
            # This timeline contains every hydrated native EHR row, including
            # tables that do not participate in detection. The normalized
            # algorithm events remain available separately for audit.
            "timeline": _ehr_record_timeline(ehr),
            "event_count": ehr["total_record_count"],
            "algorithm_evidence_timeline": _medical_timeline(
                patient_source, patient_evidence, names
            ),
            "algorithm_event_count": len(patient_source),
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
            "provisional": bool(target_verdict.get("provisional", False)),
            "relaxations": _plain(target_verdict.get("relaxations", [])),
            "screening_only_not_diagnosis": True,
        },
        "clinical_rationale": {
            "summary": target_verdict.get("reason"),
            "findings": clinical_reasons,
            "parallel_routes": target_verdict.get("parallel_routes", []),
            "cross_phenotype_annotations": [differential] if differential["visible"] else [],
        },
        "phenotype_risk_assessments": risk_assessments,
        "algorithm_analysis": {
            "outcome_path": "SUSPICION_PIPELINE",
            "screening_target": target,
            "steps": [
                {"step": "EVIDENCE_QUALIFICATION", "records": _plain(patient_evidence)},
                {"step": "SIGNAL_EVALUATION", "records": _plain(patient_signals)},
                {"step": "BUCKET_EVALUATION", "records": _plain(patient_buckets)},
                {"step": "COMBINATION_MATCHING", "records": _plain(patient_combinations)},
                {"step": "GUARDRAIL_EVALUATION", "records": _plain(patient_guardrails)},
                {"step": "PHENOTYPE_ROUTING", "records": _plain(patient_router)},
            ],
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
    algorithm_analysis = clean.pop("algorithm_analysis", None)

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

    clean = scrub(clean)
    if algorithm_analysis is not None:
        # The review profile must retain the actual evidence -> signal ->
        # bucket -> combination -> guardrail -> router path. Only the separate
        # proprietary trace is removed from external exports.
        clean["algorithm_analysis"] = algorithm_analysis
    return clean


def flagged_patient_ids(
    router_rows: Iterable[Any],
    *,
    phenotype: str,
    statuses: Sequence[str] = ("PHENOTYPE_PASS", "CLAIMS_RECALL_CANDIDATE"),
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
        if verdict["status"] not in {"ATTR_SUSPICION", "ATTR_CLAIMS_RECALL_CANDIDATE"}:
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
            and str(_value(row, "status", "")).upper() in {"PHENOTYPE_PASS", "CLAIMS_RECALL_CANDIDATE"}
            for row in patient_rows
        )
        if al_pass:
            output.append(patient_id)
    return output


def profiles_jsonl_bytes(profiles: Iterable[Mapping[str, Any]], *, include_proprietary_trace: bool = False) -> bytes:
    rows = [(_plain(profile) if include_proprietary_trace else strip_proprietary_trace(profile)) for profile in profiles]
    # Snowpark can expose NUMBER/DECIMAL values as non-JSON-native objects;
    # stringifying those leaves the source value inspectable instead of
    # failing the whole patient export.
    return ("\n".join(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) for row in rows) + ("\n" if rows else "")).encode("utf-8")


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


def build_confirmed_icd10_patient_profile(
    summary: Mapping[str, Any],
    claim_rows: Iterable[Any],
    *,
    run_id: str | None = None,
    config_hash: str | None = None,
    source_table: str = "CLAIMS",
    include_proprietary_trace: bool = True,
) -> dict[str, Any]:
    """Compatibility adapter for the canonical ``build_patient_profile``.

    New code must call ``build_patient_profile`` directly with the complete
    EHR. This adapter remains only so earlier callers do not break abruptly.
    """
    rows = list(claim_rows)
    patient_id = str(_case_value(summary, "PATIENT_ID", "patient_id", default=""))
    configured_codes = _profile_values(_case_value(
        summary, "MATCHED_ICD10_CODES", "matched_icd10_codes", default=[]
    ))
    configured_keys = {_canonical_icd10(value) for value in configured_codes}
    evidence_rows = []
    raw_claims = []
    for row in rows:
        raw = _claim_record(row)
        raw_claims.append(raw)
        annotated_match = _case_value(
            row, "MATCHED_CODE", "MATCHED_ICD10_CODE", "MATCHED_CODE_VALUE"
        )
        raw_code = _claim_code(row, raw)
        raw_system = str(_claim_system(row, raw) or "").upper().replace("-", "").replace("_", "")
        exact_summary_match = (
            raw_system in {"ICD10", "ICD10CM"}
            and _canonical_icd10(raw_code) in configured_keys
        )
        if annotated_match not in (None, ""):
            evidence_rows.append(row)
        elif exact_summary_match:
            configured_match = next(
                value
                for value in configured_codes
                if _canonical_icd10(value) == _canonical_icd10(raw_code)
            )
            evidence_rows.append({
                "SOURCE_CLAIM": raw,
                "MATCHED_CODE": configured_match,
                "DIAGNOSIS_SYSTEM": _claim_system(row, raw),
                "NORMALIZED_CODE": _canonical_icd10(raw_code),
            })

    profile = build_patient_profile(
        patient_id,
        confirmation_summary=summary,
        confirmation_evidence=evidence_rows,
        ehr_records_by_table={"claim": raw_claims},
        confirmation_source_table=source_table,
        run_id=run_id,
        config_hash=config_hash,
        include_proprietary_trace=include_proprietary_trace,
    )
    # Temporary compatibility aliases for callers that consumed the original
    # confirmed-only exporter. New code reads the canonical ``ehr`` section.
    profile["source_data"] = {
        "tables_queried": [source_table],
        "claim_row_count": len(raw_claims),
        "claim_rows": raw_claims,
        "nlp_used": False,
        "icd9_used": False,
    }
    return profile

    # Pre-unification implementation retained below only until downstream
    # deployments have migrated to the canonical builder.
    patient_id = str(_case_value(summary, "PATIENT_ID", "patient_id", default=""))
    profile_run_id = run_id or _case_value(summary, "RUN_ID", "run_id")
    configured_codes = _profile_values(_case_value(
        summary, "MATCHED_ICD10_CODES", "matched_icd10_codes", default=[]
    ))
    configured_code_keys = {_canonical_icd10(code) for code in configured_codes}

    source_claims: list[dict[str, Any]] = []
    matched_evidence: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    for row in claim_rows:
        raw = _claim_record(row)
        code = _claim_code(row, raw)
        system = _claim_system(row, raw)
        normalized_code = _canonical_icd10(
            _case_value(row, "NORMALIZED_CODE", default=code)
        )
        matched_code = _case_value(
            row, "MATCHED_CODE", "MATCHED_ICD10_CODE", "MATCHED_CODE_VALUE"
        )
        # When SQL did not provide annotations, use the summary's exact
        # allow-list to identify evidence locally.  Removing the decimal is
        # only a representation normalization (E85.81 == E8581), not a
        # prefix/wildcard match.
        is_icd10 = str(system or "").upper().replace("-", "") in {
            "ICD10", "ICD10CM"
        }
        if matched_code in (None, "") and is_icd10 and normalized_code in configured_code_keys:
            matched_code = next(
                (value for value in configured_codes if _canonical_icd10(value) == normalized_code),
                code,
            )
        is_match = matched_code not in (None, "")
        source_claims.append(raw)

        event_date = _case_value(
            raw,
            "SERVICE_FROM_DATE", "FROM_DATE", "COLUMN5", "COLUMN19",
        )
        evidence_annotations = {
            "matched_icd10_code": _plain(matched_code),
            "normalized_code": normalized_code or None,
            "diagnosis_system": _plain(system),
            "amyloidosis_type": _plain(_case_value(
                row, "AMYLOIDOSIS_TYPE", "amyloidosis_type",
                default=_case_value(summary, "AMYLOIDOSIS_TYPE", "amyloidosis_type"),
            )),
            "subtype_label": _plain(_case_value(
                row, "SUBTYPE_LABEL", "AMYLOIDOSIS_SUBTYPE", "amyloidosis_subtype",
                default=_case_value(summary, "AMYLOIDOSIS_SUBTYPE", "amyloidosis_subtype"),
            )),
            "risk_label": _plain(_case_value(
                row, "RISK_LABEL", "risk_label",
                default=_case_value(summary, "RISK_LABEL", "risk_label", default="CONFIRMED"),
            )),
            "priority_label": _plain(_case_value(
                row, "PRIORITY_LABEL", "priority_label",
                default=_case_value(summary, "PRIORITY_LABEL", "priority_label", default="CONFIRMED"),
            )),
            "confirmation_scope": _plain(_case_value(
                row, "CONFIRMATION_SCOPE", "confirmation_scope",
                default=_case_value(summary, "CONFIRMATION_SCOPE", "confirmation_scope", default="KNOWN_AMYLOIDOSIS"),
            )),
            "match_method": "EXACT_CONFIGURED_ICD10_CODE",
            "source_table": source_table,
            "source_claim": raw,
        }
        timeline.append({
            "source_table": source_table,
            "event_date": _plain(event_date),
            "code_system": _plain(system),
            "code_value": _plain(code),
            "raw_record": raw,
            "clinical_meanings": [
                {
                    "meaning": "CONFIRMED_AMYLOIDOSIS_ICD10_MATCH",
                    "matched_icd10_code": _plain(matched_code),
                }
            ] if is_match else [],
        })
        if is_match:
            matched_evidence.append(evidence_annotations)

    matched_codes = list(dict.fromkeys(
        str(_case_value(item, "matched_icd10_code") or "")
        for item in matched_evidence
        if _case_value(item, "matched_icd10_code") not in (None, "")
    )) or configured_codes
    types = _profile_values(_case_value(summary, "AMYLOIDOSIS_TYPES", "amyloidosis_types", "AMYLOIDOSIS_TYPE"))
    subtype_value = _case_value(
        summary, "AMYLOIDOSIS_SUBTYPES", "amyloidosis_subtypes", "AMYLOIDOSIS_SUBTYPE"
    )
    if isinstance(subtype_value, (list, tuple, set, frozenset)):
        subtypes = [str(item).strip() for item in subtype_value if str(item).strip()]
    else:
        subtypes = [
            item.strip() for item in str(subtype_value or "").split("|") if item.strip()
        ]
    scopes = _profile_values(_case_value(summary, "CONFIRMATION_SCOPES", "confirmation_scopes", "CONFIRMATION_SCOPE"))
    risk = _case_value(summary, "RISK_LABEL", "risk_label", default="CONFIRMED")
    priority = _case_value(summary, "PRIORITY_LABEL", "priority_label", default="CONFIRMED")
    profile = {
        "run_id": _plain(profile_run_id),
        "patient_id": patient_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "demographics": {},
        "medical_profile": {
            "timeline": timeline,
            "event_count": len(source_claims),
            "source_scope": [source_table],
            "dates_required_for_confirmation": False,
        },
        "known_diagnosis": {
            "status": "CONFIRMED_AMYLOIDOSIS",
            "confirmation_scope": scopes or ["KNOWN_AMYLOIDOSIS"],
            "amyloidosis_types": types,
            "amyloidosis_subtypes": subtypes,
            "matched_icd10_codes": matched_codes,
            "risk_label": _plain(risk),
            "priority_label": _plain(priority),
            "excluded_from_early_detection": True,
            "source_recognition_not_new_diagnosis": True,
        },
        "clinical_rationale": {
            "summary": (
                "Confirmed because one or more CLAIMS rows contained an exact "
                "configured ICD-10 amyloidosis code. Matching used structured "
                "ICD-10 values only; NLP, ICD-9, and suspicion scoring were not used."
            ),
            "rule": "ALL_AMYLOIDOSIS_EXACT_ICD10_E85_ALLOW_LIST",
            "matched_icd10_codes": matched_codes,
            "matched_source_values": matched_codes,
            "findings": [
                {
                    "clinical_finding": (
                        item.get("subtype_label")
                        or item.get("amyloidosis_type")
                        or "Confirmed amyloidosis ICD-10 diagnosis"
                    ),
                    "matched_value": item.get("matched_icd10_code"),
                    "event_date": _case_value(
                        item.get("source_claim", {}),
                        "SERVICE_FROM_DATE", "FROM_DATE", "COLUMN5", "COLUMN19",
                    ),
                    "source_table": item.get("source_table"),
                }
                for item in matched_evidence
            ],
            "matched_claim_evidence": matched_evidence,
            "evidence_count": len(matched_evidence),
        },
        "source_data": {
            "tables_queried": [source_table],
            "claim_row_count": len(source_claims),
            "claim_rows": source_claims,
            "nlp_used": False,
            "icd9_used": False,
        },
    }
    if config_hash:
        profile["proprietary_pipeline_trace"] = {
            "confirmed_config_hash": str(config_hash),
            "pipeline_scope": "CLAIMS_ONLY_CONFIRMED_ICD10",
        }
    return profile


def confirmed_icd10_profiles_csv_bytes(profiles: Iterable[Mapping[str, Any]]) -> bytes:
    """Return a compact index beside the full per-patient JSONL objects."""
    output = io.StringIO(newline="")
    fields = [
        "run_id", "patient_id", "status", "matched_icd10_codes",
        "amyloidosis_types", "amyloidosis_subtypes", "confirmation_scope",
        "risk_label", "priority_label", "claim_row_count", "evidence_count",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for profile in profiles:
        clean = _plain(profile)
        diagnosis = clean.get("known_diagnosis", {})
        rationale = clean.get("clinical_rationale", {})
        source_data = clean.get("source_data", {})
        ehr_claims = clean.get("ehr", {}).get("records_by_table", {}).get("claim", {})
        join = lambda value: ";".join(str(item) for item in (value or []))
        writer.writerow({
            "run_id": clean.get("run_id"),
            "patient_id": clean.get("patient_id"),
            "status": diagnosis.get("status"),
            "matched_icd10_codes": join(diagnosis.get("matched_icd10_codes")),
            "amyloidosis_types": join(diagnosis.get("amyloidosis_types")),
            "amyloidosis_subtypes": join(diagnosis.get("amyloidosis_subtypes")),
            "confirmation_scope": join(diagnosis.get("confirmation_scope")),
            "risk_label": diagnosis.get("risk_label"),
            "priority_label": diagnosis.get("priority_label"),
            "claim_row_count": ehr_claims.get(
                "record_count", source_data.get("claim_row_count", 0)
            ),
            "evidence_count": rationale.get("evidence_count", 0),
        })
    return output.getvalue().encode("utf-8-sig")


def export_confirmed_icd10_profiles(
    profiles: Iterable[Mapping[str, Any]],
    output_dir: str | Path,
    *,
    basename: str = "confirmed_amyloidosis_patient_profiles",
    include_proprietary_trace: bool = False,
) -> dict[str, str]:
    """Write one complete JSON object per confirmed patient plus a CSV index."""
    rows = list(profiles)
    target = Path(output_dir).expanduser().resolve() / "confirmed"
    target.mkdir(parents=True, exist_ok=True)
    jsonl = target / f"{basename}.jsonl"
    csv_path = target / f"{basename}.csv"
    jsonl.write_bytes(profiles_jsonl_bytes(rows, include_proprietary_trace=include_proprietary_trace))
    csv_path.write_bytes(confirmed_icd10_profiles_csv_bytes(rows))
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
    "build_confirmed_icd10_patient_profile",
    "confirmed_icd10_profiles_csv_bytes",
    "export_confirmed_icd10_profiles",
]

"""Normalized, lineage-preserving source-event materialization."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Iterable, Mapping

from ..warehouse.source_schema import default_source_config
from .extraction_contract import (
    UNKNOWN_DIAGNOSIS_TYPE_POLICY,
    derive_available_date,
    diagnosis_system,
    normalize_system,
)


def _json_default(value: Any) -> str:
    return str(value)


def stable_row_hash(row: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(row), sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _value(row: Mapping[str, Any], physical: str | None, logical: str | None = None) -> Any:
    if logical and logical in row:
        return row[logical]
    if physical and physical in row:
        return row[physical]
    if physical:
        # Snowpark Row keys may arrive quoted or case-normalized.
        for key, value in row.items():
            if str(key).strip('"').upper() == str(physical).strip('"').upper():
                return value
    return None


def _physical(table_cfg: Mapping[str, Any], logical: str) -> str | None:
    return table_cfg.get("columns", {}).get(logical)


def _split_declared_values(value: Any) -> list[str]:
    """Flatten arrays and common multi-value delimiters.

    Warehouse exports represent repeated codes as lists, newline-delimited
    strings, or delimiter-separated strings.  This helper is used only for
    code-bearing fields, so comma is a safe legacy delimiter here.  Nested
    arrays are flattened recursively and empty values are discarded.
    """
    if value in (None, ""):
        return []
    if isinstance(value, Mapping):
        for key in ("values", "codes", "code", "value"):
            if key in value:
                return _split_declared_values(value[key])
        return []
    if isinstance(value, (list, tuple, set)):
        output: list[str] = []
        for item in value:
            output.extend(_split_declared_values(item))
        return output
    values = [str(value)]
    for delimiter in ("|", ";", ",", "~", "\r\n", "\n", "\r"):
        next_values: list[str] = []
        for item in values:
            next_values.extend(item.split(delimiter))
        values = next_values
    return [item.strip() for item in values if item.strip()]


def _value_identity(logical: str, index: int, value: Any) -> str:
    return hashlib.sha256(
        f"{logical}|{index}|{value}".encode("utf-8")
    ).hexdigest()[:16]


def _observation_system(row: Mapping[str, Any]) -> tuple[str | None, bool]:
    """Resolve an optional lab identifier-system declaration.

    The warehouse contract exposes ``ObservationIdentifier`` but does not
    itself declare that its values are LOINC.  A supplied system declaration
    is therefore required before a lab identifier can take the LOINC route;
    absent metadata remains untyped and cannot satisfy any structured term.
    """
    declared = _value(row, "ObservationIdentifierSystem", "observation_identifier_system")
    normalized = normalize_system(declared)
    if normalized:
        return normalized, False
    return None, False


def _text_event(base: SourceEvent, *, source_field: str, text: Any) -> SourceEvent:
    """Create a narrative event while retaining source/context provenance."""
    return replace(
        base,
        source_field=source_field,
        code_system=None,
        code_value=None,
        text_value=None if text in (None, "") else str(text),
        attributes={
            **dict(base.attributes or {}),
            "match_mode": "CODE_IN_TEXT",
            "code_in_text": True,
            "context_available": text not in (None, ""),
            "text_source_field": source_field,
        },
        value_identity=_value_identity(source_field, 0, text),
    )


@dataclass
class SourceEvent:
    run_id: str
    patient_id: str
    encounter_id: str | None
    source_table: str
    source_record_id: str
    event_date: Any
    available_date: Any
    source_specialty: str | None
    source_field: str | None
    code_system: str | None
    code_value: str | None
    text_value: str | None
    result_value: Any
    result_status: str | None
    experiencer_hint: str | None
    raw_row_hash: str
    config_hash: str
    attributes: dict[str, Any] = field(default_factory=dict)
    value_identity: str | None = None

    @property
    def support_lineage_id(self) -> str:
        """Stable identity of the native source row, shared by value events."""
        return f"{self.source_table}:{self.source_record_id}:{self.raw_row_hash}"

    @property
    def source_event_id(self) -> str:
        value_key = self.source_field or "row"
        if self.value_identity:
            value_key = f"{value_key}:{self.value_identity}"
        return f"{self.support_lineage_id}:{value_key}"

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["source_event_id"] = self.source_event_id
        out["support_lineage_id"] = self.support_lineage_id
        return out


def normalize_source_row(
    row: Mapping[str, Any],
    table_key: str,
    *,
    run_id: str,
    config_hash: str,
    source_config: Mapping[str, Any] | None = None,
) -> SourceEvent:
    """Convert one physical source row into one event.

    Multiple matching columns in a row share this event's identity.  The
    function therefore never emits one event per code/text column.
    """
    cfg = source_config or default_source_config()
    table = cfg.get("tables", {}).get(table_key)
    if table is None:
        raise KeyError(f"unknown source table key: {table_key}")
    col = table.get("columns", {})
    physical_name = str(table.get("name", table_key))
    patient = _value(row, _physical(table, "patient_id"), "patient_id")
    if patient in (None, ""):
        raise ValueError(f"{table_key} source row has no patient identifier")
    encounter = _value(row, _physical(table, "encounter_id"), "encounter_id")
    record_logical = "record_id"
    if table_key == "claim":
        # Claims do not have a declared native record ID in the source contract.
        record = None
    elif table_key == "lab":
        record = _value(row, _physical(table, "lab_result_id"), "lab_result_id") or _value(row, _physical(table, "lab_id"), "lab_id")
    elif table_key == "clinical_note":
        record = _value(row, _physical(table, "note_id"), "note_id")
    else:
        record = _value(row, _physical(table, record_logical), record_logical)
    raw_hash = stable_row_hash(row)
    source_record_id = str(record) if record not in (None, "") else raw_hash
    if table_key == "claim":
        event_date = _value(row, _physical(table, "from_date"), "from_date") or _value(row, _physical(table, "to_date"), "to_date")
        code_value = _value(row, _physical(table, "diagnosis_code"), "diagnosis_code") or _value(row, _physical(table, "procedure_code"), "procedure_code")
        text_value = _value(row, _physical(table, "clinical_notes"), "clinical_notes")
        source_field = "diagnosis_code" if _value(row, _physical(table, "diagnosis_code"), "diagnosis_code") not in (None, "") else "procedure_code"
        result_value = None
        result_status = None
        specialty = _value(row, _physical(table, "specialty_name"), "specialty_name")
    elif table_key == "lab":
        event_date = _value(row, _physical(table, "observation_datetime"), "observation_datetime")
        code_value = _value(row, _physical(table, "observation_identifier"), "observation_identifier")
        text_value = _value(row, _physical(table, "lab_result_note"), "lab_result_note")
        result_value = _value(row, _physical(table, "observation_value"), "observation_value")
        result_status = _value(row, _physical(table, "result_status"), "result_status")
        source_field = "lab"
        specialty = None
    elif table_key in {"medical_history", "surgical_history"}:
        event_date = _value(row, _physical(table, "event_date"), "event_date")
        code_value = _value(row, _physical(table, "snomed"), "snomed") or _value(row, _physical(table, "secondary_snomed"), "secondary_snomed")
        text_value = _value(row, _physical(table, "value"), "value")
        result_value = None
        result_status = None
        source_field = "history"
        specialty = _value(row, _physical(table, "source_category"), "source_category")
    elif table_key == "family_history":
        event_date = _value(row, _physical(table, "event_date"), "event_date")
        code_value = _value(row, _physical(table, "snomed"), "snomed")
        text_value = _value(row, _physical(table, "condition"), "condition")
        result_value = _value(row, _physical(table, "status"), "status")
        result_status = _value(row, _physical(table, "status"), "status")
        source_field = "family_history"
        specialty = None
    elif table_key == "clinical_note":
        event_date = _value(row, _physical(table, "event_date"), "event_date")
        code_value = None
        text_value = _value(row, _physical(table, "note_text"), "note_text")
        result_value = None
        result_status = None
        source_field = "clinical_note"
        specialty = _value(row, _physical(table, "note_type"), "note_type")
    elif table_key == "encounter":
        event_date = _value(row, _physical(table, "encounter_date"), "encounter_date")
        code_value = text_value = None
        result_value = result_status = None
        source_field = "encounter"
        specialty = None
    elif table_key == "census":
        event_date = None
        code_value = text_value = None
        result_value = result_status = None
        source_field = "census"
        specialty = None
    else:
        raise ValueError(f"unsupported source table: {table_key}")
    attrs = {"table_key": table_key, "physical_table": physical_name}
    if table_key == "claim":
        raw_type = _value(row, _physical(table, "diagnosis_type"), "diagnosis_type")
        diagnosis_kind, diagnosis_unknown = diagnosis_system(raw_type)
        attrs["diagnosis_type"] = raw_type
        attrs["diagnosis_type_normalized"] = diagnosis_kind
        attrs["diagnosis_type_unknown"] = diagnosis_unknown
        attrs["unknown_diagnosis_type_policy"] = UNKNOWN_DIAGNOSIS_TYPE_POLICY
        attrs["procedure_modifier_1"] = _value(row, _physical(table, "procedure_modifier_1"), "procedure_modifier_1")
        attrs["procedure_modifier_2"] = _value(row, _physical(table, "procedure_modifier_2"), "procedure_modifier_2")
        attrs["procedure_modifier_3"] = _value(row, _physical(table, "procedure_modifier_3"), "procedure_modifier_3")
    if table_key == "family_history":
        attrs["family_member"] = _value(row, _physical(table, "family_member"), "family_member")
        attrs["family_status"] = _value(row, _physical(table, "status"), "status")
    if table_key in {"medical_history", "surgical_history"}:
        attrs["source_category"] = _value(row, _physical(table, "source_category"), "source_category")
    if table_key == "lab":
        attrs["result_status"] = result_status
        observation_system, observation_assumed = _observation_system(row)
        attrs["observation_identifier_system"] = observation_system
        attrs["observation_identifier_system_declared"] = observation_system is not None
        attrs["observation_identifier_system_assumed"] = observation_assumed
    return SourceEvent(
        run_id=str(run_id), patient_id=str(patient), encounter_id=None if encounter in (None, "") else str(encounter),
        source_table=physical_name, source_record_id=source_record_id, event_date=event_date,
        available_date=derive_available_date(_value(row, "available_date", "available_date"), event_date),
        source_specialty=None if specialty in (None, "") else str(specialty), source_field=source_field,
        code_system=(
            diagnosis_system(_value(row, _physical(table, "diagnosis_type"), "diagnosis_type"))[0]
            if table_key == "claim" and source_field == "diagnosis_code"
            else "CPT_HCPCS" if table_key == "claim" and source_field == "procedure_code"
            else _observation_system(row)[0] if table_key == "lab" and source_field == "lab"
            else "SNOMED_CT" if table_key in {"medical_history", "surgical_history", "family_history"}
            else None
        ),
        code_value=None if code_value in (None, "") else str(code_value),
        text_value=None if text_value in (None, "") else str(text_value), result_value=result_value,
        result_status=None if result_status in (None, "") else str(result_status),
        experiencer_hint="FAMILY_MEMBER" if table_key == "family_history" else "PATIENT",
        raw_row_hash=raw_hash, config_hash=str(config_hash), attributes=attrs,
    )


def expand_source_row(
    row: Mapping[str, Any],
    table_key: str,
    *,
    run_id: str,
    config_hash: str,
    source_config: Mapping[str, Any] | None = None,
) -> list[SourceEvent]:
    """Emit one event per source value while sharing row-level lineage.

    A claim with diagnosis, secondary diagnosis, procedure and note values
    produces distinct value events, but every event carries the same
    ``support_lineage_id``.  Downstream independence therefore cannot treat
    repeated columns from one native row as independent clinical witnesses.
    """
    cfg = source_config or default_source_config()
    table = cfg.get("tables", {}).get(table_key)
    if table is None:
        raise KeyError(f"unknown source table key: {table_key}")
    base = normalize_source_row(row, table_key, run_id=run_id, config_hash=config_hash, source_config=cfg)
    col = table.get("columns", {})
    def raw(logical: str) -> Any:
        return _value(row, _physical(table, logical), logical)
    value_events: list[SourceEvent] = []
    if table_key == "claim":
        primary_system, diagnosis_type_unknown = diagnosis_system(raw("diagnosis_type"))
        base.attributes.update({
            "diagnosis_type_normalized": primary_system,
            "diagnosis_type_unknown": diagnosis_type_unknown,
            "unknown_diagnosis_type_policy": UNKNOWN_DIAGNOSIS_TYPE_POLICY,
        })
        for logical in ("diagnosis_code", "other_diagnosis_9", "other_diagnosis_10", "procedure_code"):
            system = {
                "diagnosis_code": primary_system,
                "other_diagnosis_9": "ICD9",
                "other_diagnosis_10": "ICD10",
                "procedure_code": "CPT_HCPCS",
            }[logical]
            for index, value in enumerate(_split_declared_values(raw(logical))):
                value_events.append(replace(base, source_field=logical, code_system=system, code_value=value, text_value=None,
                                            value_identity=_value_identity(logical, index, value)))
        if raw("clinical_notes") not in (None, ""):
            value_events.append(_text_event(base, source_field="clinical_notes", text=raw("clinical_notes")))
    elif table_key == "lab":
        observation_system, observation_assumed = _observation_system(row)
        base.attributes.update({
            "observation_identifier_system": observation_system,
            "observation_identifier_system_declared": observation_system is not None,
            "observation_identifier_system_assumed": observation_assumed,
        })
        identifiers = _split_declared_values(raw("observation_identifier"))
        if identifiers or raw("observation_value") not in (None, ""):
            for index, value in enumerate(identifiers or [None]):
                value_events.append(replace(
                    base,
                    source_field="observation_identifier",
                    code_system=observation_system,
                    code_value=value,
                    text_value=None,
                    result_value=raw("observation_value"),
                    value_identity=_value_identity("observation_identifier", index, value),
                ))
        if raw("lab_result_note") not in (None, ""):
            value_events.append(_text_event(base, source_field="lab_result_note", text=raw("lab_result_note")))
    elif table_key in {"medical_history", "surgical_history"}:
        for logical in ("snomed", "secondary_snomed"):
            for index, value in enumerate(_split_declared_values(raw(logical))):
                value_events.append(replace(base, source_field=logical, code_system="SNOMED_CT", code_value=value, text_value=None,
                                            value_identity=_value_identity(logical, index, value)))
        if raw("value") not in (None, ""):
            value_events.append(_text_event(base, source_field="value", text=raw("value")))
    elif table_key == "family_history":
        for index, value in enumerate(_split_declared_values(raw("snomed"))):
            value_events.append(replace(base, source_field="snomed", code_system="SNOMED_CT", code_value=value, text_value=None,
                                        value_identity=_value_identity("snomed", index, value)))
        if raw("condition") not in (None, ""):
            value_events.append(_text_event(base, source_field="condition", text=raw("condition")))
    elif table_key == "clinical_note":
        if raw("note_text") not in (None, ""):
            value_events.append(_text_event(base, source_field="note_text", text=raw("note_text")))
    if not value_events:
        value_events.append(base)
    return value_events


def iter_source_events(
    rows_by_table: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    run_id: str,
    config_hash: str,
    source_config: Mapping[str, Any] | None = None,
    candidate_patient_ids: set[str] | None = None,
) -> Iterable[SourceEvent]:
    for table_key, rows in rows_by_table.items():
        table_cfg = (source_config or default_source_config()).get("tables", {}).get(table_key, {})
        if not table_cfg.get("enabled", True):
            continue
        for row in rows:
            patient = _value(row, table_cfg.get("columns", {}).get("patient_id"), "patient_id")
            if candidate_patient_ids is not None and str(patient) not in candidate_patient_ids:
                continue
            yield from expand_source_row(row, table_key, run_id=run_id, config_hash=config_hash, source_config=source_config)


__all__ = ["SourceEvent", "stable_row_hash", "normalize_source_row", "expand_source_row", "iter_source_events"]

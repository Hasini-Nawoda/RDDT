"""Physical Snowflake source contract for V4.

This module intentionally contains no ATTRv vocabulary.  It describes only the
warehouse tables and columns supplied by the existing EHR data dictionary.
All created objects are expected to be temporary and run-scoped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


class SourceSchemaError(RuntimeError):
    """Raised when the physical source schema cannot satisfy the contract."""


@dataclass(frozen=True)
class SourceTable:
    key: str
    name: str
    columns: Mapping[str, str]
    required_columns: tuple[str, ...] = ()
    enabled: bool = True
    required: bool = True

    @property
    def physical_columns(self) -> tuple[str, ...]:
        return tuple(self.columns[key] for key in self.required_columns)


@dataclass
class SourceValidationReport:
    tables_checked: list[str] = field(default_factory=list)
    optional_disabled: list[str] = field(default_factory=list)
    missing_tables: list[str] = field(default_factory=list)
    missing_columns: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.missing_tables and not self.missing_columns

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tables_checked": list(self.tables_checked),
            "optional_disabled": list(self.optional_disabled),
            "missing_tables": list(self.missing_tables),
            "missing_columns": {k: list(v) for k, v in self.missing_columns.items()},
            "errors": list(self.errors),
        }


def default_source_config() -> dict[str, Any]:
    """Return the existing physical warehouse contract.

    Social history and medication remain explicitly disabled per the V4
    contract.  Logical keys are stable interfaces; values are physical names.
    """

    def table(key: str, name: str, columns: Mapping[str, str], required: Sequence[str], *, enabled: bool = True, is_required: bool = True) -> dict[str, Any]:
        return {
            "key": key,
            "name": name,
            "enabled": enabled,
            "required": is_required,
            "columns": dict(columns),
            "required_columns": tuple(required),
        }

    return {
        "namespace": None,
        "tables": {
            "census": table("census", "CENSUS", {
                "patient_id": "Member/PatientId", "birth_date": "BirthDate", "gender": "Gender",
                "city": "City", "state": "State", "family_id": "FamilyId",
            }, ("patient_id", "birth_date", "gender", "city", "state", "family_id")),
            "encounter": table("encounter", "ENCOUNTER_VISIT", {
                "encounter_id": "EncounterId/VisitId", "patient_id": "Member/PatientId",
                "encounter_date": "Encounter/Visit Date",
            }, ("encounter_id", "patient_id", "encounter_date")),
            "claim": table("claim", "CLAIM", {
                "patient_id": "Member/PatientId", "encounter_id": "EncounterId/VisitId",
                "diagnosis_code": "DiagnosisCode", "other_diagnosis_9": "OtherDiagnosisCodes9",
                "other_diagnosis_10": "OtherDiagnosisCodes10", "procedure_code": "ProcedureCode",
                "procedure_modifier_1": "ProcedureModifier1", "procedure_modifier_2": "ProcedureModifier2",
                "procedure_modifier_3": "ProcedureModifier3", "diagnosis_type": "DiagnosisType",
                "provider_type": "ProviderType", "specialty_code": "SpecialtyCode",
                "specialty_name": "SpecialtyName", "drg_code": "DRGCode", "clinical_notes": "ClinicalNotes",
                "from_date": "FromDate", "to_date": "ToDate",
            }, (
                "patient_id", "encounter_id", "diagnosis_code", "other_diagnosis_9", "other_diagnosis_10",
                "procedure_code", "procedure_modifier_1", "procedure_modifier_2", "procedure_modifier_3",
                "diagnosis_type", "provider_type", "specialty_code", "specialty_name", "drg_code",
                "clinical_notes", "from_date", "to_date",
            )),
            "lab": table("lab", "LAB", {
                "patient_id": "Member/PatientId", "encounter_id": "EncounterId/VisitId", "lab_id": "LabId",
                "lab_request_id": "LabRequestId", "lab_result_id": "LabResultId",
                "observation_identifier": "ObservationIdentifier", "observation_value": "ObservationValue",
                "result_status": "ObservationResultStatus", "observation_datetime": "ObservationDateTime",
                "lab_result_note": "LabResultNote",
            }, (
                "lab_id", "encounter_id", "patient_id", "lab_request_id", "lab_result_id",
                "observation_identifier", "observation_value", "result_status", "observation_datetime",
                "lab_result_note",
            )),
            "medical_history": table("medical_history", "MEDICAL_HISTORY", {
                "patient_id": "Member/PatientId", "encounter_id": "EncounterId/VisitId",
                "record_id": "MedicalHistoryId", "source_category": "Source/Category", "value": "Value",
                "snomed": "SNOMED", "secondary_snomed": "Secondary SNOMED", "event_date": "Date",
            }, ("record_id", "encounter_id", "patient_id", "source_category", "value", "snomed", "secondary_snomed", "event_date")),
            "surgical_history": table("surgical_history", "SURGICAL_HISTORY", {
                "patient_id": "Member/PatientId", "encounter_id": "EncounterId/VisitId",
                "record_id": "SurgicalHistoryId", "source_category": "Source/Category", "value": "Value",
                "snomed": "SNOMED", "secondary_snomed": "Secondary SNOMED", "event_date": "Date",
            }, ("record_id", "encounter_id", "patient_id", "source_category", "value", "snomed", "secondary_snomed", "event_date")),
            "family_history": table("family_history", "FAMILY_HISTORY", {
                "patient_id": "Member/PatientId", "encounter_id": "EncounterId/VisitId",
                "record_id": "FamilyHistoryId", "condition": "Condition", "status": "Status",
                "family_member": "FamilyMember", "snomed": "SNOMED", "event_date": "Date",
            }, ("record_id", "encounter_id", "patient_id", "snomed", "condition", "status", "family_member", "event_date")),
            "clinical_note": table("clinical_note", "CLINICAL_NOTE", {
                "patient_id": "Member/PatientId", "encounter_id": "EncounterId/VisitId", "note_id": "NoteId",
                "note_type": "NoteType", "note_text": "Clinical Note Text", "event_date": "Date",
            }, ("note_id", "encounter_id", "patient_id", "note_type", "note_text", "event_date")),
            "social_history": table("social_history", "SOCIAL_HISTORY", {
                "patient_id": "Member/PatientId", "encounter_id": "EncounterId/VisitId", "value": "Value", "event_date": "Date",
            }, (), enabled=False, is_required=False),
            "medication": table("medication", "MEDICATION", {
                "patient_id": "Member/PatientId", "encounter_id": "EncounterId/VisitId", "medication_name": "Medication Name",
                "status": "Medication Status", "event_date": "Date",
            }, (), enabled=False, is_required=False),
        },
    }


def _tables(config: Mapping[str, Any]) -> Mapping[str, Any]:
    return config.get("tables", config)


def quote_identifier(identifier: str) -> str:
    """Quote a Snowflake identifier, including names containing slash/space."""
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("identifier must be a non-empty string")
    return '"' + identifier.replace('"', '""') + '"'


def qualified_table_name(table: Mapping[str, Any], namespace: str | None = None) -> str:
    parts = []
    if namespace:
        parts.extend(quote_identifier(part) for part in namespace.split("."))
    parts.append(quote_identifier(str(table["name"])))
    return ".".join(parts)


def _table_columns_from_session(session: Any, table_name: str) -> set[str] | None:
    """Read columns from common Snowpark/test-double interfaces."""
    try:
        obj = session.table(table_name)
        cols = getattr(obj, "columns", None)
        if cols is not None:
            return {str(c).strip('"') for c in cols}
        schema = getattr(obj, "schema", None)
        names = getattr(schema, "names", None)
        if names is not None:
            return {str(c).strip('"') for c in names}
    except Exception:
        pass
    return None


def validate_source_schema(session: Any, source_config: Mapping[str, Any] | None = None, *, raise_on_error: bool = True) -> SourceValidationReport:
    """Validate required physical tables/columns without creating permanent objects."""
    config = source_config or default_source_config()
    report = SourceValidationReport()
    namespace = config.get("namespace")
    for key, raw in _tables(config).items():
        enabled = bool(raw.get("enabled", True))
        required = bool(raw.get("required", True))
        if not enabled:
            report.optional_disabled.append(key)
            continue
        name = str(raw.get("name", ""))
        report.tables_checked.append(name)
        try:
            resolved_name = qualified_table_name(raw, str(namespace)) if namespace else name
            table_obj = session.table(resolved_name)
            cols = _table_columns_from_session(session, resolved_name)
            if cols is None:
                # A real Snowpark table may expose schema only after collect().
                schema = getattr(table_obj, "schema", None)
                if callable(schema):
                    schema = schema()
                names = getattr(schema, "names", None)
                if names:
                    cols = {str(c).strip('"') for c in names}
            if cols is None:
                report.errors.append(f"{key}: unable to inspect columns for {name}")
                continue
            expected = {str(raw["columns"][logical]) for logical in raw.get("required_columns", ())}
            missing = sorted(expected - cols)
            if missing:
                report.missing_columns[key] = missing
        except Exception as exc:
            if required:
                report.missing_tables.append(name)
            else:
                report.errors.append(f"{key}: optional table inspection failed: {exc}")
    if raise_on_error and not report.ok:
        raise SourceSchemaError(f"source schema validation failed: {report.as_dict()}")
    return report


__all__ = [
    "SourceSchemaError", "SourceTable", "SourceValidationReport", "default_source_config",
    "quote_identifier", "qualified_table_name", "validate_source_schema",
]

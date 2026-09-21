"""Confirmed-only ICD-10 amyloidosis extraction for the CLAIMS-first run.

This is deliberately independent of the suspicion/phenotype engines. It uses
only typed ICD-10 diagnosis values from the enabled CLAIMS table, requires no
event date, and never invokes NLP, spaCy, medSpaCy, ICD-9, or text matching.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..warehouse.snowflake_io import create_run_table, insert_rows
from ..warehouse.source_schema import default_source_config, is_table_enabled
from .extraction_contract import normalize_system


DEFAULT_CONFIRMED_CONFIG = Path(__file__).resolve().parents[1] / "config" / "shared" / "confirmed_patients.json"


@dataclass(frozen=True)
class ConfirmedICD10Profile:
    run_id: str
    patient_id: str
    status: str = "CONFIRMED"
    matched_icd10_codes: tuple[str, ...] = ()
    amyloidosis_type: str = "AMYLOIDOSIS"
    amyloidosis_subtype: str = "configured E85 amyloidosis"
    risk_label: str = "CONFIRMED"
    priority_label: str = "CONFIRMED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "patient_id": self.patient_id,
            "status": self.status,
            "matched_icd10_codes": list(self.matched_icd10_codes),
            "amyloidosis_type": self.amyloidosis_type,
            "amyloidosis_subtype": self.amyloidosis_subtype,
            "risk_label": self.risk_label,
            "priority_label": self.priority_label,
        }


def _values(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_values(item))
        return out
    parts = [str(value)]
    for delimiter in ("|", ";", ",", "\r\n", "\n", "\r"):
        parts = [piece for item in parts for piece in item.split(delimiter)]
    return [item.strip() for item in parts if item.strip()]


def _row_value(row: Mapping[str, Any], physical: str | None) -> Any:
    if not physical:
        return None
    if physical in row:
        return row[physical]
    wanted = physical.strip('"').upper()
    for key, value in row.items():
        if str(key).strip('"').upper() == wanted:
            return value
    return None


def _canonical_code(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "")


def _configured_metadata(path: str | Path | None = None) -> dict[str, tuple[str, str, str, str]]:
    source = Path(path or DEFAULT_CONFIRMED_CONFIG)
    payload = json.loads(source.read_text(encoding="utf-8"))
    route = payload["routes"]["ALL_AMYLOIDOSIS"]
    metadata: dict[str, tuple[str, str, str, str]] = {}
    for term in route.get("terminology", []):
        if normalize_system(term.get("terminology_system")) != "ICD10":
            continue
        code = _canonical_code(term.get("value"))
        metadata[code] = (
            str(term.get("amyloidosis_type", "AMYLOIDOSIS")),
            str(term.get("subtype_label", "configured E85 amyloidosis")),
            str(term.get("risk_label", "CONFIRMED")),
            str(term.get("priority_label", "CONFIRMED")),
        )
    return metadata


def _classify(codes: Iterable[str], metadata: Mapping[str, tuple[str, str, str, str]]) -> tuple[str, str, str, str]:
    for code in sorted(codes, key=lambda value: (-len(value), value)):
        if code in metadata:
            return metadata[code]
    return ("AMYLOIDOSIS", "configured E85 amyloidosis", "CONFIRMED", "CONFIRMED")


def extract_confirmed_icd10(
    rows_by_table: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    source_config: Mapping[str, Any] | None = None,
    run_id: str = "confirmed-icd10",
    confirmed_config_path: str | Path | None = None,
) -> list[ConfirmedICD10Profile]:
    """Return one deduplicated confirmed profile per patient.

    A row qualifies only when its configured diagnosis type normalizes to
    ``ICD10`` and its configured diagnosis code is in the exact configured
    allow-list. Missing dates are intentionally irrelevant to this extractor.
    """
    config = source_config or default_source_config()
    table = config.get("tables", {}).get("claim", {})
    if not is_table_enabled(table):
        return []
    columns = table.get("columns", {})
    patient_col = columns.get("patient_id")
    system_col = columns.get("diagnosis_type")
    code_col = columns.get("diagnosis_code")
    if not patient_col or not system_col or not code_col:
        raise ValueError("enabled claim table needs patient_id, diagnosis_type, and diagnosis_code mappings")
    metadata = _configured_metadata(confirmed_config_path)
    undotted_metadata = {code.replace(".", ""): (code, details) for code, details in metadata.items()}
    by_patient: dict[str, set[str]] = {}
    for row in rows_by_table.get("claim", ()):
        if normalize_system(_row_value(row, system_col)) != "ICD10":
            continue
        patient = _row_value(row, patient_col)
        if patient in (None, ""):
            continue
        for raw_code in _values(_row_value(row, code_col)):
            code = _canonical_code(raw_code)
            configured = undotted_metadata.get(code.replace(".", ""))
            if configured:
                by_patient.setdefault(str(patient), set()).add(configured[0])
    profiles: list[ConfirmedICD10Profile] = []
    for patient_id in sorted(by_patient):
        codes = tuple(sorted(by_patient[patient_id]))
        amy_type, subtype, risk, priority = _classify(codes, metadata)
        profiles.append(
            ConfirmedICD10Profile(
                run_id=str(run_id),
                patient_id=patient_id,
                matched_icd10_codes=codes,
                amyloidosis_type=amy_type,
                amyloidosis_subtype=subtype,
                risk_label=risk,
                priority_label=priority,
            )
        )
    return profiles


def materialize_confirmed_icd10_profiles(
    session: Any,
    profiles: Iterable[ConfirmedICD10Profile],
    *,
    table_name: str = "AMY_V5_CONFIRMED_ICD10",
) -> int:
    """Materialize profiles in a session-scoped temporary table only."""
    rows = [profile.as_dict() for profile in profiles]
    columns = (
        "RUN_ID", "PATIENT_ID", "STATUS", "MATCHED_ICD10_CODES",
        "AMYLOIDOSIS_TYPE", "AMYLOIDOSIS_SUBTYPE", "RISK_LABEL", "PRIORITY_LABEL",
    )
    create_run_table(session, table_name, {column: "VARCHAR" for column in columns})
    values = [
        (
            row["run_id"], row["patient_id"], row["status"],
            ",".join(row["matched_icd10_codes"]), row["amyloidosis_type"],
            row["amyloidosis_subtype"], row["risk_label"], row["priority_label"],
        )
        for row in rows
    ]
    return insert_rows(session, table_name, columns, values)


__all__ = [
    "ConfirmedICD10Profile",
    "extract_confirmed_icd10",
    "materialize_confirmed_icd10_profiles",
]

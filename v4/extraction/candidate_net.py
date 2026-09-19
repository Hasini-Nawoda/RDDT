"""Workbook-driven candidate retrieval planning.

Candidate retrieval is an efficiency filter, never clinical evidence.  The
specific values in a plan must come from compiled ``Terminology`` rows.  NLP
rows deliberately retrieve broad text-bearing records; phrase/context matching
is performed later by :mod:`atom_matching` with a PhraseMatcher/clinical
context processor rather than SQL keyword or regex matching.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

from ..warehouse.source_schema import default_source_config, qualified_table_name, quote_identifier
from .extraction_contract import normalize_system, routes_for_system


def _rows(config: Any, key: str) -> list[Mapping[str, Any]]:
    if config is None:
        return []
    row_loader = getattr(config, "rows", None)
    if callable(row_loader):
        value = row_loader(key)
    else:
        value = None
    if value is None:
        tables = getattr(config, "tables", None)
        if isinstance(tables, Mapping):
            value = tables.get(key)
    if value is None:
        value = getattr(config, key, None)
    if value is None and isinstance(config, Mapping):
        value = config.get(key)
    if value is None and isinstance(config, Mapping) and key in {"terminology", "atoms"}:
        value = config.get(key.title())
    if isinstance(value, Mapping):
        value = list(value.values())
    return [r if isinstance(r, Mapping) else getattr(r, "__dict__", {}) for r in (value or [])]


def _get(row: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row:
            return row[name]
        # tolerate compiled-model snake_case/cell-header variants only
        for key in row:
            if str(key).replace(" ", "_").lower() == name.replace(" ", "_").lower():
                return row[key]
    return default


@dataclass(frozen=True)
class CandidateReason:
    atom_id: str
    terminology_system: str
    config_value: str
    can_fire_atom_alone: bool | None
    review_status: str | None
    config_hash: str
    retrieval_mode: str


@dataclass(frozen=True)
class CandidateQuery:
    table_key: str
    source_table: str
    source_field: str
    match_strategy: str
    sql: str
    params: tuple[Any, ...]
    reason: CandidateReason
    reasons: tuple[CandidateReason, ...] = ()


@dataclass(frozen=True)
class CandidatePatient:
    run_id: str
    patient_id: str
    reason: CandidateReason
    source_table: str | None = None
    source_record_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["reason"] = asdict(self.reason)
        return out


def _route_for_system(system: str) -> list[tuple[str, str, str]]:
    """Return logical source routes: (table key, logical field, strategy)."""
    return list(routes_for_system(system))


def _physical_column(source_config: Mapping[str, Any], table_key: str, logical_field: str) -> tuple[str, str] | None:
    table = source_config.get("tables", {}).get(table_key)
    if not table or not table.get("enabled", True):
        return None
    physical_table = str(table["name"])
    physical_field = table.get("columns", {}).get(logical_field)
    if not physical_field:
        return None
    return physical_table, str(physical_field)


def build_candidate_plan(config: Any, *, config_hash: str, source_config: Mapping[str, Any] | None = None) -> list[CandidateQuery]:
    """Build parameterized retrieval queries from compiled terminology only."""
    source_config = source_config or default_source_config()
    out: list[CandidateQuery] = []
    broad_groups: dict[tuple[str, str, str], list[CandidateReason]] = {}
    for term in _rows(config, "terminology"):
        atom_id = str(_get(term, "atom_id", "Atom_ID", default=""))
        system = normalize_system(_get(term, "terminology_system", "system", "Terminology_System", default=""))
        value = str(_get(term, "standard_code", "STANDARD_CODE", "nlp_term", "NLP_TERM", "value", "Value", default=""))
        if not atom_id or not value:
            continue
        can_fire = _get(term, "can_fire_atom_alone", "Can_Fire_Atom_Alone")
        can_fire_bool = None if can_fire in (None, "") else bool(can_fire) if isinstance(can_fire, bool) else str(can_fire).strip().upper() in {"TRUE", "YES", "1"}
        reason = CandidateReason(atom_id, system, value, can_fire_bool,
                                 _get(term, "review_status", "Review_Status"), config_hash,
                                 "")
        for table_key, logical_field, strategy in _route_for_system(system):
            physical = _physical_column(source_config, table_key, logical_field)
            if physical is None:
                continue
            table_name, column_name = physical
            table_sql = qualified_table_name(
                source_config["tables"][table_key],
                str(source_config.get("namespace")) if source_config.get("namespace") else None,
            )
            if strategy == "EXACT_CODE":
                raw = value.strip().upper()
                if raw.endswith("."):
                    strategy = "PREFIX_CODE"
                    sql = (
                        f"SELECT {quote_identifier(source_config['tables'][table_key]['columns'].get('patient_id', 'Member/PatientId'))} AS PATIENT_ID, "
                        f"{quote_identifier(column_name)} AS MATCHED_SOURCE_VALUE FROM {table_sql} "
                        f"WHERE UPPER(TRIM(CAST({quote_identifier(column_name)} AS VARCHAR))) LIKE UPPER(TRIM(?))"
                    )
                    params = (f"{value}%",)
                elif "-" in raw and raw.count("-") == 1:
                    start, end = (p.strip() for p in raw.split("-", 1))
                    if start and end and ("." in start or "." in end or (start.isdigit() and end.isdigit())):
                        strategy = "RANGE_CODE"
                        sql = (
                            f"SELECT {quote_identifier(source_config['tables'][table_key]['columns'].get('patient_id', 'Member/PatientId'))} AS PATIENT_ID, "
                            f"{quote_identifier(column_name)} AS MATCHED_SOURCE_VALUE FROM {table_sql} "
                            f"WHERE UPPER(TRIM(CAST({quote_identifier(column_name)} AS VARCHAR))) BETWEEN UPPER(TRIM(?)) AND UPPER(TRIM(?))"
                        )
                        params = (start, end)
                    else:
                        # Malformed range text is not executable; retain the
                        # literal as a deterministic exact lookup so the
                        # compiler/runtime can surface the mismatch.
                        strategy = "EXACT_CODE"
                        sql = (
                            f"SELECT {quote_identifier(source_config['tables'][table_key]['columns'].get('patient_id', 'Member/PatientId'))} AS PATIENT_ID, "
                            f"{quote_identifier(column_name)} AS MATCHED_SOURCE_VALUE FROM {table_sql} "
                            f"WHERE UPPER(TRIM(CAST({quote_identifier(column_name)} AS VARCHAR))) = UPPER(TRIM(?))"
                        )
                        params = (value,)
                else:
                    sql = (
                        f"SELECT {quote_identifier(source_config['tables'][table_key]['columns'].get('patient_id', 'Member/PatientId'))} AS PATIENT_ID, "
                        f"{quote_identifier(column_name)} AS MATCHED_SOURCE_VALUE FROM {table_sql} "
                        f"WHERE UPPER(TRIM(CAST({quote_identifier(column_name)} AS VARCHAR))) = UPPER(TRIM(?))"
                    )
                    params = (value,)
            else:
                broad_groups.setdefault((table_key, logical_field, strategy), []).append(
                    CandidateReason(reason.atom_id, reason.terminology_system, reason.config_value,
                                    reason.can_fire_atom_alone, reason.review_status, reason.config_hash, strategy)
                )
                continue
            updated_reason = CandidateReason(reason.atom_id, reason.terminology_system, reason.config_value,
                                             reason.can_fire_atom_alone, reason.review_status, reason.config_hash, strategy)
            out.append(CandidateQuery(table_key, table_name, column_name, strategy, sql, params, updated_reason, (updated_reason,)))
    # One broad source scan per text-bearing field. PhraseMatcher attaches the
    # actual configured atom after retrieval; this avoids thousands of full
    # table scans while retaining all configured reasons for audit.
    for (table_key, logical_field, strategy), reasons in broad_groups.items():
        physical = _physical_column(source_config, table_key, logical_field)
        if physical is None:
            continue
        table_name, column_name = physical
        table_sql = qualified_table_name(
            source_config["tables"][table_key],
            str(source_config.get("namespace")) if source_config.get("namespace") else None,
        )
        sql = (
            f"SELECT {quote_identifier(source_config['tables'][table_key]['columns'].get('patient_id', 'Member/PatientId'))} AS PATIENT_ID, "
            f"{quote_identifier(column_name)} AS MATCHED_SOURCE_VALUE FROM {table_sql} "
            f"WHERE {quote_identifier(column_name)} IS NOT NULL"
        )
        out.append(CandidateQuery(table_key, table_name, column_name, strategy, sql, (), reasons[0], tuple(reasons)))
    return out


def candidate_rows_from_query_results(run_id: str, query: CandidateQuery, rows: Iterable[Mapping[str, Any]]) -> list[CandidatePatient]:
    """Attach workbook provenance to candidate rows; no clinical decision is made."""
    out = []
    reasons = query.reasons or (query.reason,)
    for row in rows:
        patient = row.get("PATIENT_ID", row.get("patient_id"))
        if patient in (None, ""):
            continue
        record_id = row.get("SOURCE_RECORD_ID", row.get("source_record_id"))
        for reason in reasons:
            out.append(CandidatePatient(str(run_id), str(patient), reason, query.source_table, None if record_id is None else str(record_id)))
    return out


__all__ = ["CandidateReason", "CandidateQuery", "CandidatePatient", "build_candidate_plan", "candidate_rows_from_query_results", "normalize_system"]

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

from ..warehouse.source_schema import (
    default_source_config,
    is_table_enabled,
    qualified_table_name,
    quote_identifier,
)
from .code_semantics import (
    code_in_text_supported,
    expanded_values,
    executable_values,
    find_code_in_text,
    normalize_code_system,
    prefix_fallback_supported,
    term_match_mode,
)
from .extraction_contract import (
    NLP_SOURCE_ROUTES,
    normalize_system,
    normalize_terminology_mode,
    terminology_mode_for_systems,
    routes_for_system,
    terminology_allowed,
)


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
    match_mode: str | None = None
    expanded_values: tuple[str, ...] = ()
    match_in_text: bool = False
    mapping_role: str | None = None


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
    if not table or not is_table_enabled(table):
        return None
    physical_table = str(table["name"])
    physical_field = table.get("columns", {}).get(logical_field)
    if not physical_field:
        return None
    return physical_table, str(physical_field)


def _code_sql(column_name: str, term: Mapping[str, Any]) -> tuple[str, tuple[Any, ...], str] | None:
    """Build a code predicate using the same explicit semantics as matching."""
    system = normalize_code_system(_get(term, "terminology_system", "system", "Terminology_System", default=""))
    value = str(_get(term, "standard_code", "STANDARD_CODE", "value", "Value", default="") or "").strip()
    if not value:
        return None
    expression = f"UPPER(TRIM(CAST({quote_identifier(column_name)} AS VARCHAR)))"
    if system in {"ICD", "ICD9", "ICD10"}:
        expression = f"REPLACE({expression}, '.', '')"
    mode = term_match_mode(term)
    if mode in {"PREFIX", "PREFIX_FALLBACK", "RANGE"}:
        values = executable_values(term)
        if not values:
            return "1 = 0", (), f"{mode}_CODE"
        clauses: list[str] = []
        params: list[str] = []
        for member in values:
            member_text = str(member).strip().upper()
            if system in {"ICD", "ICD9", "ICD10"}:
                member_text = member_text.replace(".", "")
            clauses.append(f"{expression} = ?")
            params.append(member_text)
        return "(" + " OR ".join(clauses) + ")", tuple(params), f"{mode}_CODE"
    configured = value.upper()
    if system in {"ICD", "ICD9", "ICD10"}:
        configured = configured.replace(".", "")
    return f"{expression} = ?", (configured,), "EXACT_CODE"


def build_candidate_plan(
    config: Any,
    *,
    config_hash: str,
    source_config: Mapping[str, Any] | None = None,
    terminology_mode: str = "ALL",
    terminology_systems: Any = None,
) -> list[CandidateQuery]:
    """Build parameterized retrieval queries from compiled terminology only."""
    source_config = source_config or default_source_config()
    selected_mode = terminology_mode_for_systems(
        terminology_systems,
        default=terminology_mode,
    )
    out: list[CandidateQuery] = []
    broad_groups: dict[tuple[str, str, str], list[CandidateReason]] = {}
    code_text_groups: dict[tuple[str, str, str], list[CandidateReason]] = {}
    for term in _rows(config, "terminology"):
        if not terminology_allowed(
            _get(term, "terminology_system", "system", "Terminology_System", default=""),
            selected_mode,
        ):
            continue
        atom_id = str(_get(term, "atom_id", "Atom_ID", default=""))
        system = normalize_system(_get(term, "terminology_system", "system", "Terminology_System", default=""))
        canonical_system = normalize_code_system(system)
        value = str(_get(term, "standard_code", "STANDARD_CODE", "nlp_term", "NLP_TERM", "value", "Value", default=""))
        if not atom_id or not value:
            continue
        can_fire = _get(term, "can_fire_atom_alone", "Can_Fire_Atom_Alone")
        can_fire_bool = None if can_fire in (None, "") else bool(can_fire) if isinstance(can_fire, bool) else str(can_fire).strip().upper() in {"TRUE", "YES", "1"}
        reason = CandidateReason(atom_id, system, value, can_fire_bool,
                                 _get(term, "review_status", "Review_Status"), config_hash,
                                 "", match_mode=term_match_mode(term),
                                 expanded_values=expanded_values(term),
                                 match_in_text=code_in_text_supported(term) if canonical_system in {"ICD", "ICD9", "ICD10", "CPT_HCPCS", "SNOMED_CT", "LOINC"} else False,
                                 mapping_role=_get(term, "mapping_role", "Mapping_Role"))
        for table_key, logical_field, strategy in _route_for_system(canonical_system):
            physical = _physical_column(source_config, table_key, logical_field)
            if physical is None:
                continue
            table_name, column_name = physical
            table_sql = qualified_table_name(
                source_config["tables"][table_key],
                str(source_config.get("namespace")) if source_config.get("namespace") else None,
            )
            if strategy == "EXACT_CODE":
                # An authored ICD family may use the explicit second-stage
                # fallback when no reviewed exact member matches.  Retrieve
                # the typed column broadly and let atom_matching apply the
                # shared token/boundary semantics; never use SQL LIKE.
                if prefix_fallback_supported(term):
                    broad_groups.setdefault((table_key, logical_field, "PREFIX_FALLBACK_CODE"), []).append(
                        CandidateReason(reason.atom_id, reason.terminology_system, reason.config_value,
                                        reason.can_fire_atom_alone, reason.review_status, reason.config_hash,
                                        "PREFIX_FALLBACK_CODE", reason.match_mode, reason.expanded_values,
                                        reason.match_in_text, reason.mapping_role)
                    )
                    continue
                predicate = _code_sql(column_name, term)
                if predicate is None:
                    continue
                where, params, strategy = predicate
                sql = (
                    f"SELECT {quote_identifier(source_config['tables'][table_key]['columns'].get('patient_id', 'Member/PatientId'))} AS PATIENT_ID, "
                    f"{quote_identifier(column_name)} AS MATCHED_SOURCE_VALUE FROM {table_sql} WHERE {where}"
                )
            else:
                broad_groups.setdefault((table_key, logical_field, strategy), []).append(
                    CandidateReason(reason.atom_id, reason.terminology_system, reason.config_value,
                                    reason.can_fire_atom_alone, reason.review_status, reason.config_hash, strategy,
                                    reason.match_mode, reason.expanded_values, reason.match_in_text, reason.mapping_role)
                )
                continue
            updated_reason = CandidateReason(reason.atom_id, reason.terminology_system, reason.config_value,
                                             reason.can_fire_atom_alone, reason.review_status, reason.config_hash, strategy,
                                             reason.match_mode, reason.expanded_values, reason.match_in_text, reason.mapping_role)
            out.append(CandidateQuery(table_key, table_name, column_name, strategy, sql, params, updated_reason, (updated_reason,)))
        # Structured codes may appear in narrative text.  Retrieval remains a
        # broad, null-filtered source scan; the shared boundary matcher below
        # decides whether a configured code is actually present.
        if (canonical_system in {"ICD", "ICD9", "ICD10", "CPT_HCPCS", "SNOMED_CT", "LOINC"}
                and reason.match_in_text and code_in_text_supported(term)):
            code_reason = CandidateReason(
                reason.atom_id, reason.terminology_system, reason.config_value,
                reason.can_fire_atom_alone, reason.review_status, reason.config_hash,
                "CODE_IN_TEXT", reason.match_mode, reason.expanded_values, True, reason.mapping_role,
            )
            for text_table, text_field, _strategy in NLP_SOURCE_ROUTES:
                physical = _physical_column(source_config, text_table, text_field)
                if physical is not None:
                    code_text_groups.setdefault((text_table, text_field, "CODE_IN_TEXT"), []).append(code_reason)
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
    for (table_key, logical_field, strategy), reasons in code_text_groups.items():
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

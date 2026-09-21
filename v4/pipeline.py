"""End-to-end phenotype-generic V4 orchestration.

The orchestrator reads source tables and, when requested, materializes
intermediate results only as session-scoped Snowflake temporary tables.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import IMPLEMENTATION_VERSION
from .evaluation_policy import normalize_evaluation_mode
from .extraction.candidate_net import CandidatePatient, CandidateQuery, build_candidate_plan
from .extraction.evidence_qualification import ClinicalContextAdapter
from .extraction.known_attr import (
    CandidateConfigUnion,
    KnownAttrConfig,
    KnownAttrPatient,
    load_known_attr_config,
)
from .extraction.known_al import (
    KnownALConfig,
    KnownALPatient,
    load_known_al_config,
    identify_known_al,
)
from .extraction.confirmed_icd10 import extract_confirmed_icd10
from .warehouse.snowflake_io import create_run_table, execute, insert_rows
from .pipeline_steps.step_01_source_validation import load_config, validate_sources
from .pipeline_steps.step_02_candidate_retrieval import retrieve_candidates
from .pipeline_steps.step_03_source_events import build_source_events
from .pipeline_steps.step_03b_known_attr_exclusion import separate_known_attr
from .pipeline_steps.step_04_atom_matching import match_atoms
from .pipeline_steps.step_05_evidence_qualification import qualify_evidence
from .pipeline_steps.step_06_signal_evaluation import evaluate_signals_stage
from .pipeline_steps.step_07_bucket_evaluation import evaluate_buckets_stage
from .pipeline_steps.step_08_combination_matching import match_combinations_stage
from .pipeline_steps.step_09_priority_guardrails import evaluate_guardrails_stage
from .pipeline_steps.step_10_router import route_stage
from .pipeline_steps.step_11_patient_profiles import (
    build_attr_profiles,
    build_al_detected_profiles,
    build_known_al_profiles,
    build_known_profiles,
    build_profiles,
    export_attr_profile_files,
    export_al_detected_profile_files,
    export_known_al_profile_files,
    export_known_profile_files,
    export_profile_files,
)
from .output.patient_verdict import build_all_patient_verdicts
from .warehouse.source_schema import (
    default_source_config,
    is_table_enabled,
    is_table_profile_enabled,
    qualified_table_name,
    quote_identifier,
)
from .extraction.extraction_contract import (
    normalize_terminology_mode,
    terminology_mode_for_systems,
)


TEMP_TABLES = {
    "candidate_patients": "AMY_V4_CANDIDATE_PATIENT",
    "known_attr_patients": "AMY_V4_KNOWN_ATTR",
    "known_al_patients": "AMY_V4_KNOWN_AL",
    "source_events": "AMY_V4_SOURCE_EVENT",
    "atom_matches": "AMY_V4_ATOM_MATCH",
    "evidence_events": "AMY_V4_EVIDENCE_EVENT",
    "signal_hits": "AMY_V4_SIGNAL_HIT",
    "bucket_state": "AMY_V4_BUCKET_STATE",
    "combination_hits": "AMY_V4_COMBINATION_HIT",
    "guardrail_hits": "AMY_V4_GUARDRAIL_HIT",
    "phenotype_results": "AMY_V4_PHENOTYPE_RESULT",
    "router_output": "AMY_V4_ROUTER_OUTPUT",
    "patient_verdicts": "AMY_V4_PATIENT_VERDICT",
}

TEMP_TABLE_SCHEMAS = {
    "candidate_patients": (
        "RUN_ID", "PATIENT_ID", "CANDIDATE_REASON_TYPE", "CONFIG_ATOM_ID",
        "CONFIG_TERMINOLOGY_SYSTEM", "CONFIG_VALUE", "SOURCE_TABLE",
        "SOURCE_RECORD_ID", "CONFIG_HASH",
    ),
    "known_attr_patients": (
        "RUN_ID", "PATIENT_ID", "STATUS", "CONFIRMATION_SCOPE",
        "CONFIRMATION_RULE_IDS", "MATCHED_CONFIG_VALUES", "EVENT_DATES",
        "SUPPORT_LINEAGE_IDS", "SUPPORTING_EVIDENCE_IDS",
        "KNOWN_ATTR_CONFIG_HASH",
    ),
    "known_al_patients": (
        "RUN_ID", "PATIENT_ID", "STATUS", "CONFIRMATION_SCOPE",
        "CONFIRMATION_RULE_IDS", "MATCHED_CONFIG_VALUES", "EVENT_DATES",
        "SUPPORT_LINEAGE_IDS", "SUPPORTING_EVIDENCE_IDS",
        "KNOWN_AL_CONFIG_HASH",
    ),
    "source_events": (
        "RUN_ID", "PATIENT_ID", "SOURCE_EVENT_ID", "SUPPORT_LINEAGE_ID",
        "ENCOUNTER_ID", "SOURCE_TABLE", "SOURCE_RECORD_ID", "EVENT_DATE",
        "AVAILABLE_DATE", "SOURCE_SPECIALTY", "SOURCE_FIELD", "CODE_SYSTEM",
        "CODE_VALUE", "TEXT_VALUE", "RESULT_VALUE", "RESULT_STATUS",
        "EXPERIENCER_HINT", "RAW_ROW_HASH", "CONFIG_HASH", "ATTRIBUTES",
    ),
    "atom_matches": (
        "RUN_ID", "PATIENT_ID", "ATOM_ID", "SOURCE_EVENT_ID", "MATCH_METHOD",
        "MATCHED_CONFIG_VALUE", "MATCHED_SOURCE_VALUE", "MATCH_STATUS",
        "EVENT_DATE", "AVAILABLE_DATE", "SUPPORT_LINEAGE_ID", "ENCOUNTER_ID",
        "CONTEXT_LINEAGE_IDS", "CONFIG_RESTRICTION", "CONFIG_HASH",
    ),
    "evidence_events": (
        "RUN_ID", "PATIENT_ID", "EVIDENCE_ID", "ATOM_ID", "EVENT_DATE",
        "AVAILABLE_DATE", "STAGE", "POLARITY", "CERTAINTY", "EXPERIENCER",
        "STATUS", "SUPPORT_LINEAGE_IDS", "CONTEXT_LINEAGE_IDS", "ATTRIBUTES",
        "SOURCE_PROVENANCE", "CONFIG_RESTRICTION", "REASON", "CONFIG_HASH",
    ),
    "signal_hits": (
        "RUN_ID", "PATIENT_ID", "PHENOTYPE", "SIGNAL_ID", "STATUS",
        "REASONING_BUCKET", "TIER", "GATE_ROLE", "CANONICAL_DEDUP_GROUP",
        "SUPPORT_LINEAGE_IDS", "CONTEXT_LINEAGE_IDS", "EVENT_DATES",
        "SUPPORTING_EVIDENCE_IDS", "EXPLANATION", "CONFIG_HASH",
    ),
    "bucket_state": (
        "RUN_ID", "PATIENT_ID", "PHENOTYPE", "REASONING_BUCKET", "STATUS",
        "BEST_ELIGIBLE_TIER", "SUPPORT_LINEAGE_IDS", "SUPPORTING_SIGNAL_IDS",
    ),
    "combination_hits": (
        "RUN_ID", "PATIENT_ID", "PHENOTYPE", "COMBINATION_ID", "STATUS",
        "OUTCOME", "RESULT_ROUTE", "PRIORITY_POLICY_ID", "SELECTED_WITNESSES",
        "SUPPORT_LINEAGE_IDS", "HOLD_REASON", "CONFIG_HASH",
    ),
    "guardrail_hits": (
        "RUN_ID", "PATIENT_ID", "PHENOTYPE", "GUARDRAIL_ID", "STATUS",
        "ACTION", "ROUTE", "SUPPORT_LINEAGE_IDS", "CONFIG_HASH",
    ),
    "phenotype_results": (
        "RUN_ID", "PATIENT_ID", "PHENOTYPE", "STATUS", "RESULT_ROUTE",
        "PRIORITY_CLASS", "SUSPICION_LEVEL", "MATCHED_COMBINATION_ID",
        "SUPPORTING_SIGNAL_IDS", "SUPPORTING_BUCKETS", "SUPPORT_LINEAGE_IDS",
        "SUPPORTING_EVENT_DATES", "GUARDRAIL_IDS", "PARALLEL_ROUTES",
        "EXPLANATION", "CONFIG_HASH", "IMPLEMENTATION_VERSION",
    ),
    "router_output": (
        "RUN_ID", "PATIENT_ID", "PHENOTYPE", "STATUS", "RESULT_ROUTE",
        "PRIORITY_CLASS", "SUSPICION_LEVEL", "MATCHED_COMBINATION_ID",
        "SUPPORTING_SIGNAL_IDS", "SUPPORTING_BUCKETS", "SUPPORT_LINEAGE_IDS",
        "SUPPORTING_EVENT_DATES", "GUARDRAIL_IDS", "PARALLEL_ROUTES",
        "EXPLANATION", "CONFIG_HASH", "IMPLEMENTATION_VERSION",
        "ROUTER_SCHEMA_VERSION",
    ),
    "patient_verdicts": (
        "RUN_ID", "PATIENT_ID", "POPULATION_STATUS", "CONFIRMATION_STATUS",
        "CONFIRMATION_SCOPES", "ATTR_STATUS", "ATTR_SUSPICION_LEVEL",
        "ATTRV_STATUS", "ATTRWT_STATUS", "AL_STATUS", "AL_SUSPICION_LEVEL",
        "CANDIDATE_FOR_REVIEW", "EVALUATION_MODE", "VERDICT_SCOPE",
        "PROVISIONAL", "RELAXATIONS", "REASON",
    ),
}


WORKSPACE_RESULT_COLLECTIONS = (
    "candidate_patients",
    "known_attr_patients",
    "known_al_patients",
    "source_events",
    "atom_matches",
    "evidence_events",
    "signal_hits",
    "bucket_state",
    "combination_hits",
    "guardrail_hits",
    "phenotype_results",
    "router_output",
    "patient_verdicts",
    "patient_profiles",
)


class PipelineError(RuntimeError):
    """Raised when a run cannot safely continue."""


ATTR_PHENOTYPES = ("ATTRV", "ATTRWT")
SCREENED_PHENOTYPES = (*ATTR_PHENOTYPES, "AL")


class AttrExtractionConfig:
    """Shared atom/terminology view for one-pass ATTRv plus ATTRwt extraction."""

    def __init__(self, configs: Mapping[str, Any]):
        missing = [phenotype for phenotype in SCREENED_PHENOTYPES if phenotype not in configs]
        if missing:
            raise PipelineError(f"Combined ATTR run is missing phenotype configs: {missing}")
        baseline = configs[ATTR_PHENOTYPES[0]]
        self.tables = {
            "atoms": baseline.rows("atoms"),
            "terminology": baseline.rows("terminology"),
        }
        for phenotype in SCREENED_PHENOTYPES[1:]:
            current = configs[phenotype]
            for table in ("atoms", "terminology"):
                if current.rows(table) != self.tables[table]:
                    raise PipelineError(
                        f"{phenotype} does not share the same {table} registry; "
                        "one-pass extraction would be unsafe"
                    )
        hash_payload = json.dumps(
            {phenotype: configs[phenotype].config_hash for phenotype in SCREENED_PHENOTYPES},
            sort_keys=True,
            separators=(",", ":"),
        )
        self.config_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()
        self.phenotype = "ATTR"

    def rows(self, table: str) -> list[dict[str, Any]]:
        return list(self.tables.get(table, []))


@dataclass
class PipelineRun:
    run_id: str
    config_hash: str
    implementation_version: str
    evaluation_mode: str
    source_validation: dict[str, Any] | None
    stage_counts: dict[str, int]
    evaluated_phenotypes: list[str] = field(default_factory=list)
    config_gaps: list[dict[str, Any]] = field(default_factory=list)
    candidate_patients: list[Any] = field(default_factory=list)
    known_attr_patients: list[Any] = field(default_factory=list)
    known_al_patients: list[Any] = field(default_factory=list)
    known_attr_profiles: list[dict[str, Any]] = field(default_factory=list)
    known_al_profiles: list[dict[str, Any]] = field(default_factory=list)
    known_attr_exports: dict[str, str] = field(default_factory=dict)
    known_al_exports: dict[str, str] = field(default_factory=dict)
    source_events: list[Any] = field(default_factory=list)
    atom_matches: list[Any] = field(default_factory=list)
    evidence_events: list[Any] = field(default_factory=list)
    signal_hits: list[Any] = field(default_factory=list)
    bucket_state: list[Any] = field(default_factory=list)
    combination_hits: list[Any] = field(default_factory=list)
    guardrail_hits: list[Any] = field(default_factory=list)
    phenotype_results: list[Any] = field(default_factory=list)
    router_output: list[Any] = field(default_factory=list)
    patient_verdicts: list[dict[str, Any]] = field(default_factory=list)
    patient_profiles: list[dict[str, Any]] = field(default_factory=list)
    profile_exports: dict[str, str] = field(default_factory=dict)
    al_detected_profiles: list[dict[str, Any]] = field(default_factory=list)
    al_detected_exports: dict[str, str] = field(default_factory=dict)
    temporary_tables: dict[str, str] = field(default_factory=lambda: dict(TEMP_TABLES))
    warehouse_objects_created: tuple[str, ...] = ()

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "config_hash": self.config_hash,
            "implementation_version": self.implementation_version,
            "evaluation_mode": self.evaluation_mode,
            "evaluated_phenotypes": list(self.evaluated_phenotypes),
            "stage_counts": dict(self.stage_counts),
            "config_gaps": list(self.config_gaps),
            "temporary_tables": dict(self.temporary_tables),
            "warehouse_objects_created": list(self.warehouse_objects_created),
            "workspace_result_collections": list(WORKSPACE_RESULT_COLLECTIONS),
            "profile_exports": dict(self.profile_exports),
            "known_attr_exports": dict(self.known_attr_exports),
            "known_al_exports": dict(self.known_al_exports),
            "al_detected_exports": dict(self.al_detected_exports),
            "al_detected_profiles": len(self.al_detected_profiles),
        }


def _plain(value: Any) -> Any:
    if hasattr(value, "as_dict") and callable(value.as_dict):
        return _plain(value.as_dict())
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _row_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    if hasattr(row, "as_dict"):
        return dict(row.as_dict())
    if is_dataclass(row):
        return asdict(row)
    raise TypeError(f"Unsupported Snowflake row type: {type(row)!r}")


def _get(row: Mapping[str, Any], name: str, default: Any = None) -> Any:
    if name in row:
        return row[name]
    wanted = name.strip('"').upper()
    for key, value in row.items():
        if str(key).strip('"').upper() == wanted:
            return value
    return default


def _materialize_records(
    session: Any,
    table_name: str,
    records: Iterable[Any],
    *,
    required_columns: Sequence[str] = (),
    run_id: str | None = None,
) -> int:
    """Materialize one pipeline stage as a session-scoped temporary table."""
    rows = [_plain(record) for record in records]
    keys = [str(key).upper() for key in required_columns]
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError(f"Cannot materialize non-object row in {table_name}")
        normalized = {str(key).upper(): value for key, value in row.items()}
        if run_id is not None:
            normalized.setdefault("RUN_ID", run_id)
        for key in normalized:
            if key not in keys:
                keys.append(key)
        normalized_rows.append(normalized)
    if not keys:
        keys = ["RUN_ID", "EMPTY_REASON"]
    create_run_table(session, table_name, {key: "VARCHAR" for key in keys})
    values = []
    for row in normalized_rows:
        values.append(tuple(
            json.dumps(row.get(key), sort_keys=True, ensure_ascii=False)
            if isinstance(row.get(key), (dict, list, tuple, set))
            else row.get(key)
            for key in keys
        ))
    return insert_rows(session, table_name, keys, values)


def _materialize_pipeline_run(session: Any, result: PipelineRun) -> None:
    stages = {
        "candidate_patients": result.candidate_patients,
        "known_attr_patients": result.known_attr_patients,
        "known_al_patients": result.known_al_patients,
        "source_events": result.source_events,
        "atom_matches": result.atom_matches,
        "evidence_events": result.evidence_events,
        "signal_hits": result.signal_hits,
        "bucket_state": result.bucket_state,
        "combination_hits": result.combination_hits,
        "guardrail_hits": result.guardrail_hits,
        "phenotype_results": result.phenotype_results,
        "router_output": result.router_output,
        "patient_verdicts": result.patient_verdicts,
    }
    for key, records in stages.items():
        _materialize_records(
            session,
            TEMP_TABLES[key],
            records,
            required_columns=TEMP_TABLE_SCHEMAS[key],
            run_id=result.run_id,
        )
    result.warehouse_objects_created = tuple(TEMP_TABLES[key] for key in stages)


def _load_config(*, config_dir: str | Path | None, phenotype: str) -> Any:
    return load_config(
        config_dir=str(config_dir) if config_dir is not None else None,
        phenotype=phenotype,
    )


def _selected_phenotype(config: Any, phenotype: str | None = None) -> str:
    """Resolve one package phenotype and reject cross-package evaluation."""
    configured = str(getattr(config, "phenotype", "") or "").upper()
    selected = str(phenotype or configured).upper()
    if not selected:
        raise PipelineError("A phenotype is required and the loaded config does not declare one")
    if configured and selected != configured:
        raise PipelineError(
            f"Requested phenotype {selected!r} does not match loaded config {configured!r}"
        )
    return selected


def _exact_confirmed_pre_screen(
    rows_by_table: Mapping[str, Iterable[Mapping[str, Any]]],
    all_events: Sequence[Any],
    *,
    source_config: Mapping[str, Any],
    run_id: str,
    confirmed_config_path: str | Path | None,
    known_attr_config_hash: str,
    known_al_config_hash: str,
) -> tuple[list[KnownAttrPatient], list[KnownALPatient]]:
    """Adapt the date-independent exact E85 extractor to pipeline outputs."""
    profiles = extract_confirmed_icd10(
        rows_by_table,
        source_config=source_config,
        run_id=run_id,
        confirmed_config_path=confirmed_config_path,
    )
    by_patient: dict[str, list[Any]] = {}
    for event in all_events:
        by_patient.setdefault(str(event.patient_id), []).append(event)

    known_attr: list[KnownAttrPatient] = []
    known_al: list[KnownALPatient] = []
    for profile in profiles:
        patient_events = by_patient.get(str(profile.patient_id), [])
        matched_codes = {str(code).upper().replace(" ", "") for code in profile.matched_icd10_codes}
        supporting = [
            event for event in patient_events
            if str(getattr(event, "code_system", "") or "").upper() == "ICD10"
            and str(getattr(event, "code_value", "") or "").upper().replace(" ", "") in matched_codes
        ]
        lineages = sorted({str(event.support_lineage_id) for event in supporting})
        event_dates = sorted({
            str(event.event_date) for event in supporting
            if event.event_date not in (None, "")
        })
        amyloidosis_type = str(profile.amyloidosis_type or "AMYLOIDOSIS").upper()
        scope = (
            "AL_SPECIFIC" if amyloidosis_type == "AL"
            else "ATTR_SPECIFIC" if amyloidosis_type == "ATTR"
            else f"{amyloidosis_type}_AMYLOIDOSIS"
        )
        if amyloidosis_type == "AL":
            known_al.append(KnownALPatient(
                run_id=run_id,
                patient_id=profile.patient_id,
                status="EXCLUDED_KNOWN_AL",
                confirmation_scope=scope,
                confirmation_rule_ids=["KNOWN_AMYLOIDOSIS_ICD10_E85"],
                matched_config_values=list(profile.matched_icd10_codes),
                event_dates=event_dates,
                support_lineage_ids=lineages,
                supporting_evidence_ids=[],
                known_al_config_hash=known_al_config_hash,
            ))
        else:
            known_attr.append(KnownAttrPatient(
                run_id=run_id,
                patient_id=profile.patient_id,
                status="EXCLUDED_KNOWN_ATTR_OR_AMYLOIDOSIS",
                confirmation_scope=scope,
                confirmation_rule_ids=["KNOWN_AMYLOIDOSIS_ICD10_E85"],
                matched_config_values=list(profile.matched_icd10_codes),
                event_dates=event_dates,
                support_lineage_ids=lineages,
                supporting_evidence_ids=[],
                known_attr_config_hash=known_attr_config_hash,
            ))
    return known_attr, known_al


def _merge_patients(existing: Sequence[Any], additional: Sequence[Any]) -> list[Any]:
    """Merge pre-screen records deterministically, preferring the exact route."""
    by_patient = {str(row.patient_id): row for row in existing}
    by_patient.update({str(row.patient_id): row for row in additional})
    return [by_patient[patient_id] for patient_id in sorted(by_patient)]


def _execute_candidate_plan(
    session: Any,
    config: Any,
    *,
    run_id: str,
    source_config: Mapping[str, Any],
    nlp: Any,
    terminology_mode: str = "ALL",
) -> list[CandidatePatient]:
    return retrieve_candidates(
        session,
        config,
        run_id=run_id,
        source_config=source_config,
        nlp=nlp,
        terminology_mode=terminology_mode,
    )


def _fetch_candidate_source_rows(
    session: Any,
    source_config: Mapping[str, Any],
    *,
    candidate_plan: Sequence[CandidateQuery],
) -> dict[str, list[dict[str, Any]]]:
    """Read detection inputs and full EHR rows without a Snowflake work table.

    Candidate queries are combined into one read-only CTE. The CTE exists only
    for the duration of each SELECT statement and is not a catalog object.
    Broader NLP seed queries can return a superset; the in-memory event builder
    applies the exact candidate-id set before clinical evaluation.

    ``enabled`` controls algorithm participation. ``profile_enabled`` controls
    EHR hydration. A profile-only table is fetched here but is ignored by the
    event builder, so adding it to the patient record cannot change detection.
    """
    rows_by_table: dict[str, list[dict[str, Any]]] = {}
    if not candidate_plan:
        return {
            key: []
            for key, table in source_config.get("tables", {}).items()
            if is_table_enabled(table) or is_table_profile_enabled(table)
        }

    seed_queries: list[str] = []
    params: list[Any] = []
    for index, query in enumerate(candidate_plan):
        seed_queries.append(
            "SELECT CAST(PATIENT_ID AS VARCHAR) AS PATIENT_ID "
            f"FROM ({query.sql}) CANDIDATE_SEED_{index}"
        )
        params.extend(query.params)
    candidate_sql = (
        "SELECT DISTINCT PATIENT_ID FROM ("
        + " UNION ALL ".join(seed_queries)
        + ") CANDIDATE_UNION"
    )

    namespace = source_config.get("namespace")
    for table_key, table in source_config.get("tables", {}).items():
        if not (is_table_enabled(table) or is_table_profile_enabled(table)):
            continue
        patient_column = table.get("columns", {}).get("patient_id")
        if not patient_column:
            continue
        table_name = str(table["name"])
        physical = qualified_table_name(table, str(namespace) if namespace else None)
        sql = (
            f"WITH CANDIDATE_IDS AS ({candidate_sql}) "
            f"SELECT SRC.* FROM {physical} SRC "
            "JOIN CANDIDATE_IDS CAND "
            f"ON CAST(SRC.{quote_identifier(str(patient_column))} AS VARCHAR) = CAND.PATIENT_ID"
        )
        rows_by_table[table_key] = [
            _row_dict(row) for row in execute(session, sql, tuple(params))
        ]
    return rows_by_table


def _source_population_patient_ids(
    rows_by_table: Mapping[str, Iterable[Mapping[str, Any]]],
    source_config: Mapping[str, Any],
) -> set[str]:
    """Return the population represented by enabled algorithm source tables."""
    patient_ids: set[str] = set()
    for table_key, table in source_config.get("tables", {}).items():
        if not is_table_enabled(table):
            continue
        patient_column = table.get("columns", {}).get("patient_id")
        if not patient_column:
            continue
        for row in rows_by_table.get(table_key, ()):
            patient_id = _get(row, str(patient_column))
            if patient_id not in (None, ""):
                patient_ids.add(str(patient_id))
    return patient_ids


def _fetch_population_patient_ids(
    session: Any,
    source_config: Mapping[str, Any],
) -> set[str]:
    """Read only distinct patient identifiers from enabled algorithm tables."""
    namespace = source_config.get("namespace")
    queries: list[str] = []
    for table in source_config.get("tables", {}).values():
        if not is_table_enabled(table):
            continue
        patient_column = table.get("columns", {}).get("patient_id")
        if not patient_column:
            continue
        physical = qualified_table_name(table, str(namespace) if namespace else None)
        quoted_patient = quote_identifier(str(patient_column))
        queries.append(
            f"SELECT CAST({quoted_patient} AS VARCHAR) AS PATIENT_ID "
            f"FROM {physical} WHERE {quoted_patient} IS NOT NULL"
        )
    if not queries:
        return set()
    sql = "SELECT DISTINCT PATIENT_ID FROM (" + " UNION ALL ".join(queries) + ") SOURCE_POPULATION"
    return {
        str(_get(_row_dict(row), "PATIENT_ID"))
        for row in execute(session, sql)
        if _get(_row_dict(row), "PATIENT_ID") not in (None, "")
    }


def _demographics(rows_by_table: Mapping[str, Iterable[Mapping[str, Any]]], source_config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    table = source_config.get("tables", {}).get("census", {})
    columns = table.get("columns", {})
    result: dict[str, dict[str, Any]] = {}
    for row in rows_by_table.get("census", []):
        patient = _get(row, str(columns.get("patient_id", "Member/PatientId")))
        if patient in (None, ""):
            continue
        result[str(patient)] = {
            logical: _plain(_get(row, str(physical)))
            for logical, physical in columns.items()
            if logical != "patient_id"
        }
    return result


def _run_single_phenotype_reference_pipeline(
    rows_by_table: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    config: Any,
    phenotype: str | None = None,
    source_config: Mapping[str, Any] | None = None,
    run_id: str | None = None,
    candidate_patient_ids: set[str] | None = None,
    nlp: Any = None,
    terminology_mode: str = "ALL",
    terminology_systems: Sequence[str] | None = None,
    context_processor: Any = None,
    screening_cutoff: Any = None,
    include_profiles: bool = True,
    profile_output_dir: str | Path | None = None,
    profile_priority_classes: Sequence[str] | None = None,
    profile_suspicion_levels: Sequence[str] | None = ("HIGHEST_SUSPICION", "HIGH_SUSPICION"),
    known_attr_config: KnownAttrConfig | None = None,
    evaluation_mode: str = "STRICT",
) -> PipelineRun:
    """Run one loaded phenotype package on already supplied warehouse rows."""
    if screening_cutoff is None:
        raise PipelineError("screening_cutoff/as-of date is required for pre-test evidence eligibility")
    evaluation_mode = normalize_evaluation_mode(evaluation_mode)
    source_config = source_config or default_source_config()
    rows_by_table = {
        key: rows if isinstance(rows, list) else list(rows)
        for key, rows in rows_by_table.items()
    }
    terminology_mode = terminology_mode_for_systems(
        terminology_systems,
        default=terminology_mode,
    )
    run_id = run_id or str(uuid.uuid4())
    selected_phenotype = _selected_phenotype(config, phenotype)
    all_events = build_source_events(
        rows_by_table,
        run_id=run_id,
        config_hash=config.config_hash,
        source_config=source_config,
        candidate_patient_ids=candidate_patient_ids,
    )
    if context_processor is None and nlp is not None:
        context_processor = ClinicalContextAdapter(nlp)
    known_config = known_attr_config or load_known_attr_config()
    exact_attr, exact_al = _exact_confirmed_pre_screen(
        rows_by_table,
        all_events,
        source_config=source_config,
        run_id=run_id,
        confirmed_config_path=known_config.path,
        known_attr_config_hash=known_config.config_hash,
        known_al_config_hash=known_config.config_hash,
    )
    known_attr, events = separate_known_attr(
        all_events,
        run_id=run_id,
        screening_cutoff=screening_cutoff,
        known_attr_config=known_config,
        nlp=nlp,
        context_processor=context_processor,
        terminology_mode=terminology_mode,
        terminology_systems=terminology_systems,
    )
    known_attr.patients = _merge_patients(known_attr.patients, [*exact_attr, *exact_al])
    exact_ids = {str(row.patient_id) for row in (*exact_attr, *exact_al)}
    if exact_ids:
        events = [event for event in events if str(event.patient_id) not in exact_ids]
    known_ids = known_attr.patient_ids
    matches = match_atoms(
        events,
        config,
        nlp=nlp,
        terminology_mode=terminology_mode,
        terminology_systems=terminology_systems,
    )
    evidence = qualify_evidence(
        matches,
        config,
        context_processor=context_processor,
        screening_cutoff=screening_cutoff,
        evaluation_mode=evaluation_mode,
    )
    patient_universe = set(candidate_patient_ids or {event.patient_id for event in all_events})
    patients = sorted(patient_universe - known_ids)
    signal_hits: list[Any] = []
    bucket_state: list[Any] = []
    combination_hits: list[Any] = []
    guardrail_hits: list[Any] = []
    phenotype_results: list[Any] = []
    router_output: list[Any] = []
    for patient_id in patients:
        patient_evidence = [row for row in evidence if row.patient_id == patient_id]
        patient_signals = evaluate_signals_stage(
            config,
            patient_evidence,
            patient_id=patient_id,
            phenotype=selected_phenotype,
            evaluation_mode=evaluation_mode,
        )
        patient_buckets = evaluate_buckets_stage(config, patient_signals, patient_id=patient_id, phenotype=selected_phenotype)
        patient_combinations = match_combinations_stage(
            config,
            patient_signals,
            patient_buckets,
            patient_id=patient_id,
            phenotype=selected_phenotype,
            evaluation_mode=evaluation_mode,
        )
        patient_guards = evaluate_guardrails_stage(config, patient_evidence, patient_id=patient_id, phenotype=selected_phenotype)
        patient_results, patient_router = route_stage(
            config,
            patient_combinations,
            patient_guards,
            patient_id=patient_id,
            phenotype=selected_phenotype,
            run_id=run_id,
            config_hash=config.config_hash,
            implementation_version=IMPLEMENTATION_VERSION,
            evaluation_mode=evaluation_mode,
        )
        signal_hits.extend(patient_signals)
        bucket_state.extend(patient_buckets)
        combination_hits.extend(patient_combinations)
        guardrail_hits.extend(patient_guards)
        phenotype_results.extend(patient_results)
        router_output.extend(patient_router)

    gaps = []
    for row in evidence:
        if row.status == "UNKNOWN" and row.reason:
            gaps.append({"patient_id": row.patient_id, "atom_id": row.atom_id, "gap": row.reason})
    for row in signal_hits:
        explanation = str(row.get("explanation") or "")
        if explanation.startswith("CONFIG_GAP:"):
            gaps.append({"patient_id": row.get("patient_id"), "signal_id": row.get("signal_id"), "gap": explanation})

    demographics = _demographics(rows_by_table, source_config)
    effective_profile_levels = None if evaluation_mode == "CLAIMS_RECALL" else profile_suspicion_levels
    profiles = build_profiles(router_output, config=config, phenotype=selected_phenotype, source_events=events, evidence_events=evidence, signal_hits=signal_hits, bucket_state=bucket_state, combination_hits=combination_hits, guardrail_hits=guardrail_hits, demographics=demographics, run_id=run_id, ehr_records_by_table=rows_by_table, source_config=source_config, include_proprietary_trace=True, profile_priority_classes=profile_priority_classes, profile_suspicion_levels=effective_profile_levels) if include_profiles else []
    known_profiles = build_known_profiles(
        known_attr.patients,
        known_config=known_config,
        source_events=all_events,
        evidence_events=known_attr.evidence,
        demographics=demographics,
        ehr_records_by_table=rows_by_table,
        source_config=source_config,
        include_proprietary_trace=True,
    ) if include_profiles else []
    exports = export_profile_files(profiles, profile_output_dir, phenotype=selected_phenotype)
    known_exports = export_known_profile_files(known_profiles, profile_output_dir)
    stages = {
        "candidate_patients": len(patients),
        "candidate_patients_total_retrieved": len(patient_universe),
        "known_attr_patients": len(known_attr.patients),
        "source_events": len(events),
        "atom_matches": len(matches),
        "evidence_events": len(evidence),
        "signal_hits": len(signal_hits),
        "bucket_state": len(bucket_state),
        "combination_hits": len(combination_hits),
        "guardrail_hits": len(guardrail_hits),
        "phenotype_results": len(phenotype_results),
        "router_output": len(router_output),
        "patient_profiles": len(profiles),
        "known_attr_profiles": len(known_profiles),
    }
    return PipelineRun(
        run_id=run_id,
        config_hash=config.config_hash,
        implementation_version=IMPLEMENTATION_VERSION,
        evaluation_mode=evaluation_mode,
        source_validation=None,
        stage_counts=stages,
        evaluated_phenotypes=[selected_phenotype],
        config_gaps=gaps,
        known_attr_patients=known_attr.patients,
        known_attr_profiles=known_profiles,
        known_attr_exports=known_exports,
        source_events=events,
        atom_matches=matches,
        evidence_events=evidence,
        signal_hits=signal_hits,
        bucket_state=bucket_state,
        combination_hits=combination_hits,
        guardrail_hits=guardrail_hits,
        phenotype_results=phenotype_results,
        router_output=router_output,
        patient_profiles=profiles,
        profile_exports=exports,
    )


def run_attr_reference_pipeline(
    rows_by_table: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    configs: Mapping[str, Any] | None = None,
    config_dir: str | Path | None = None,
    source_config: Mapping[str, Any] | None = None,
    run_id: str | None = None,
    candidate_patient_ids: set[str] | None = None,
    population_patient_ids: set[str] | None = None,
    nlp: Any = None,
    terminology_mode: str = "ALL",
    terminology_systems: Sequence[str] | None = None,
    context_processor: Any = None,
    screening_cutoff: Any = None,
    include_profiles: bool = True,
    profile_output_dir: str | Path | None = None,
    profile_suspicion_levels: Sequence[str] | None = ("HIGHEST_SUSPICION", "HIGH_SUSPICION"),
    known_attr_config: KnownAttrConfig | None = None,
    known_al_config: KnownALConfig | None = None,
    evaluation_mode: str = "STRICT",
    include_all_patient_verdicts: bool = True,
) -> PipelineRun:
    """Run ATTRv, ATTRwt, and AL after one shared extraction pass."""
    if screening_cutoff is None:
        raise PipelineError("screening_cutoff/as-of date is required for pre-test evidence eligibility")
    evaluation_mode = normalize_evaluation_mode(evaluation_mode)
    loaded_configs = dict(configs or {
        phenotype: _load_config(config_dir=config_dir, phenotype=phenotype)
        for phenotype in SCREENED_PHENOTYPES
    })
    extraction_config = AttrExtractionConfig(loaded_configs)
    terminology_mode = terminology_mode_for_systems(
        terminology_systems,
        default=terminology_mode,
    )
    source_config = source_config or default_source_config()
    rows_by_table = {
        key: rows if isinstance(rows, list) else list(rows)
        for key, rows in rows_by_table.items()
    }
    if population_patient_ids is None:
        population_patient_ids = _source_population_patient_ids(rows_by_table, source_config)
    run_id = run_id or str(uuid.uuid4())
    all_events = build_source_events(
        rows_by_table,
        run_id=run_id,
        config_hash=extraction_config.config_hash,
        source_config=source_config,
        candidate_patient_ids=candidate_patient_ids,
    )
    if context_processor is None and nlp is not None:
        context_processor = ClinicalContextAdapter(nlp)
    known_config = known_attr_config or load_known_attr_config()
    known_al = known_al_config or load_known_al_config()
    exact_attr, exact_al = _exact_confirmed_pre_screen(
        rows_by_table,
        all_events,
        source_config=source_config,
        run_id=run_id,
        confirmed_config_path=known_config.path,
        known_attr_config_hash=known_config.config_hash,
        known_al_config_hash=known_al.config_hash,
    )
    known_attr, events = separate_known_attr(
        all_events,
        run_id=run_id,
        screening_cutoff=screening_cutoff,
        known_attr_config=known_config,
        nlp=nlp,
        context_processor=context_processor,
        terminology_mode=terminology_mode,
        terminology_systems=terminology_systems,
    )
    # Identify known AL on the full event set, then remove both known routes
    # before shared extraction/evidence qualification.  This keeps confirmed
    # patients out of all phenotype scoring and stage counts.
    known_al_result = identify_known_al(
        all_events,
        run_id=run_id,
        screening_cutoff=screening_cutoff,
        nlp=nlp,
        context_processor=context_processor,
        config=known_al,
        terminology_mode=terminology_mode,
        terminology_systems=terminology_systems,
    )
    known_attr.patients = _merge_patients(known_attr.patients, exact_attr)
    known_al_result.patients = _merge_patients(known_al_result.patients, exact_al)
    if known_al_result.patient_ids:
        events = [event for event in events if event.patient_id not in known_al_result.patient_ids]
    if known_attr.patient_ids:
        events = [event for event in events if event.patient_id not in known_attr.patient_ids]
    matches = match_atoms(
        events,
        extraction_config,
        nlp=nlp,
        terminology_mode=terminology_mode,
        terminology_systems=terminology_systems,
    )
    evidence = qualify_evidence(
        matches,
        extraction_config,
        context_processor=context_processor,
        screening_cutoff=screening_cutoff,
        evaluation_mode=evaluation_mode,
    )
    patient_universe = set(candidate_patient_ids or {event.patient_id for event in all_events})
    excluded_ids = known_attr.patient_ids | known_al_result.patient_ids
    patients = sorted(patient_universe - excluded_ids)

    signal_hits: list[Any] = []
    bucket_state: list[Any] = []
    combination_hits: list[Any] = []
    guardrail_hits: list[Any] = []
    phenotype_results: list[Any] = []
    router_output: list[Any] = []
    for patient_id in patients:
        patient_evidence = [row for row in evidence if row.patient_id == patient_id]
        for phenotype in SCREENED_PHENOTYPES:
            config = loaded_configs[phenotype]
            patient_signals = evaluate_signals_stage(
                config,
                patient_evidence,
                patient_id=patient_id,
                phenotype=phenotype,
                evaluation_mode=evaluation_mode,
            )
            patient_buckets = evaluate_buckets_stage(
                config,
                patient_signals,
                patient_id=patient_id,
                phenotype=phenotype,
            )
            patient_combinations = match_combinations_stage(
                config,
                patient_signals,
                patient_buckets,
                patient_id=patient_id,
                phenotype=phenotype,
                evaluation_mode=evaluation_mode,
            )
            patient_guards = evaluate_guardrails_stage(
                config,
                patient_evidence,
                patient_id=patient_id,
                phenotype=phenotype,
            )
            patient_results, patient_router = route_stage(
                config,
                patient_combinations,
                patient_guards,
                patient_id=patient_id,
                phenotype=phenotype,
                run_id=run_id,
                config_hash=config.config_hash,
                implementation_version=IMPLEMENTATION_VERSION,
                evaluation_mode=evaluation_mode,
            )
            signal_hits.extend(patient_signals)
            bucket_state.extend(patient_buckets)
            combination_hits.extend(patient_combinations)
            guardrail_hits.extend(patient_guards)
            phenotype_results.extend(patient_results)
            router_output.extend(patient_router)

    gaps = []
    for row in evidence:
        if row.status == "UNKNOWN" and row.reason:
            gaps.append({"patient_id": row.patient_id, "atom_id": row.atom_id, "gap": row.reason})
    for row in signal_hits:
        explanation = str(row.get("explanation") or "")
        if explanation.startswith("CONFIG_GAP:"):
            gaps.append({
                "patient_id": row.get("patient_id"),
                "phenotype": row.get("phenotype"),
                "signal_id": row.get("signal_id"),
                "gap": explanation,
            })

    patient_verdicts = build_all_patient_verdicts(
        population_patient_ids,
        router_output,
        known_attr_patients=known_attr.patients,
        known_al_patients=known_al_result.patients,
        evaluation_mode=evaluation_mode,
    ) if include_all_patient_verdicts else []

    demographics = _demographics(rows_by_table, source_config)
    effective_profile_levels = None if evaluation_mode == "CLAIMS_RECALL" else profile_suspicion_levels
    profiles = build_attr_profiles(
        router_output,
        config=extraction_config,
        source_events=events,
        evidence_events=evidence,
        signal_hits=signal_hits,
        bucket_state=bucket_state,
        combination_hits=combination_hits,
        guardrail_hits=guardrail_hits,
        demographics=demographics,
        run_id=run_id,
        ehr_records_by_table=rows_by_table,
        source_config=source_config,
        include_proprietary_trace=True,
        profile_suspicion_levels=effective_profile_levels,
    ) if include_profiles else []
    al_detected_profiles = build_al_detected_profiles(
        router_output,
        config=extraction_config,
        source_events=events,
        evidence_events=evidence,
        signal_hits=signal_hits,
        bucket_state=bucket_state,
        combination_hits=combination_hits,
        guardrail_hits=guardrail_hits,
        demographics=demographics,
        run_id=run_id,
        ehr_records_by_table=rows_by_table,
        source_config=source_config,
        include_proprietary_trace=True,
    ) if include_profiles else []
    known_profiles = build_known_profiles(
        known_attr.patients,
        known_config=known_config,
        source_events=all_events,
        evidence_events=known_attr.evidence,
        demographics=demographics,
        ehr_records_by_table=rows_by_table,
        source_config=source_config,
        include_proprietary_trace=True,
    ) if include_profiles else []
    known_al_profiles = build_known_al_profiles(
        known_al_result.patients,
        known_config=known_al,
        source_events=all_events,
        evidence_events=known_al_result.evidence,
        demographics=demographics,
        ehr_records_by_table=rows_by_table,
        source_config=source_config,
        include_proprietary_trace=True,
    ) if include_profiles else []
    exports = export_attr_profile_files(profiles, profile_output_dir)
    al_detected_exports = export_al_detected_profile_files(al_detected_profiles, profile_output_dir)
    known_exports = export_known_profile_files(known_profiles, profile_output_dir)
    known_al_exports = export_known_al_profile_files(known_al_profiles, profile_output_dir)
    if known_al_result.config_gap:
        gaps.append({"scope": "KNOWN_AL", "gap": known_al_result.config_gap})
    stages = {
        "candidate_patients": len(patients),
        "candidate_patients_total_retrieved": len(patient_universe),
        "known_attr_patients": len(known_attr.patients),
        "known_al_patients": len(known_al_result.patients),
        "source_events": len(events),
        "atom_matches": len(matches),
        "evidence_events": len(evidence),
        "signal_hits": len(signal_hits),
        "bucket_state": len(bucket_state),
        "combination_hits": len(combination_hits),
        "guardrail_hits": len(guardrail_hits),
        "phenotype_results": len(phenotype_results),
        "router_output": len(router_output),
        "patient_verdicts": len(patient_verdicts),
        "patient_profiles": len(profiles),
        "al_detected_profiles": len(al_detected_profiles),
        "al_detected_patients": len(al_detected_profiles),
        "known_attr_profiles": len(known_profiles),
        "known_al_profiles": len(known_al_profiles),
    }
    return PipelineRun(
        run_id=run_id,
        config_hash=extraction_config.config_hash,
        implementation_version=IMPLEMENTATION_VERSION,
        evaluation_mode=evaluation_mode,
        source_validation=None,
        stage_counts=stages,
        evaluated_phenotypes=list(SCREENED_PHENOTYPES),
        config_gaps=gaps,
        known_attr_patients=known_attr.patients,
        known_al_patients=known_al_result.patients,
        known_attr_profiles=known_profiles,
        known_al_profiles=known_al_profiles,
        known_attr_exports=known_exports,
        known_al_exports=known_al_exports,
        source_events=events,
        atom_matches=matches,
        evidence_events=evidence,
        signal_hits=signal_hits,
        bucket_state=bucket_state,
        combination_hits=combination_hits,
        guardrail_hits=guardrail_hits,
        phenotype_results=phenotype_results,
        router_output=router_output,
        patient_verdicts=patient_verdicts,
        patient_profiles=profiles,
        profile_exports=exports,
        al_detected_profiles=al_detected_profiles,
        al_detected_exports=al_detected_exports,
    )


def _run_single_phenotype_v4_pipeline(
    session: Any,
    phenotype: str,
    source_config: Mapping[str, Any] | None = None,
    run_id: str | None = None,
    persist_intermediates: bool = False,
    *,
    config_dir: str | Path | None = None,
    source_rows_by_table: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    nlp: Any = None,
    terminology_mode: str = "ALL",
    terminology_systems: Sequence[str] | None = None,
    context_processor: Any = None,
    screening_cutoff: Any = None,
    include_profiles: bool = True,
    profile_output_dir: str | Path | None = None,
    profile_priority_classes: Sequence[str] | None = None,
    profile_suspicion_levels: Sequence[str] | None = ("HIGHEST_SUSPICION", "HIGH_SUSPICION"),
    known_attr_config_path: str | Path | None = None,
    evaluation_mode: str = "STRICT",
) -> PipelineRun:
    """Run one configured phenotype pipeline against a Snowpark-like session."""
    terminology_mode = terminology_mode_for_systems(
        terminology_systems,
        default=terminology_mode,
    )
    if screening_cutoff is None:
        raise PipelineError("screening_cutoff/as-of date is required for pre-test evidence eligibility")
    selected_phenotype = str(phenotype).upper()
    config = _load_config(config_dir=config_dir, phenotype=selected_phenotype)
    known_config = load_known_attr_config(known_attr_config_path)
    selected_phenotype = _selected_phenotype(config, selected_phenotype)
    source_config = source_config or default_source_config()
    run_id = run_id or str(uuid.uuid4())
    validation = validate_sources(session, source_config)

    candidates: list[CandidatePatient] = []
    if source_rows_by_table is None:
        candidate_config = CandidateConfigUnion(config, known_config)
        candidates = retrieve_candidates(
            session,
            candidate_config,
            run_id=run_id,
            source_config=source_config,
            nlp=nlp,
            terminology_mode=terminology_mode,
            terminology_systems=terminology_systems,
        )
        source_rows_by_table = _fetch_candidate_source_rows(
            session,
            source_config,
            candidate_plan=build_candidate_plan(
                candidate_config,
                config_hash=candidate_config.config_hash,
                source_config=source_config,
                terminology_mode=terminology_mode,
                terminology_systems=terminology_systems,
            ),
        )
        candidate_ids = {candidate.patient_id for candidate in candidates}
    else:
        candidate_ids = None

    result = _run_single_phenotype_reference_pipeline(
        source_rows_by_table,
        config=config,
        phenotype=selected_phenotype,
        source_config=source_config,
        run_id=run_id,
        candidate_patient_ids=candidate_ids,
        nlp=nlp,
        terminology_mode=terminology_mode,
        terminology_systems=terminology_systems,
        context_processor=context_processor,
        screening_cutoff=screening_cutoff,
        include_profiles=include_profiles,
        profile_output_dir=profile_output_dir,
        profile_priority_classes=profile_priority_classes,
        profile_suspicion_levels=profile_suspicion_levels,
        known_attr_config=known_config,
        evaluation_mode=evaluation_mode,
    )
    result.candidate_patients = candidates
    known_ids = {str(row.patient_id) for row in result.known_attr_patients}
    retrieved_ids = set(candidate_ids or {event.patient_id for event in result.source_events}) | known_ids
    result.stage_counts["candidate_patients"] = len(retrieved_ids - known_ids)
    result.stage_counts["candidate_patients_total_retrieved"] = len(retrieved_ids)
    result.source_validation = _plain(validation)
    if persist_intermediates:
        _materialize_pipeline_run(session, result)

    return result


def run_attr_v4_pipeline(
    session: Any,
    source_config: Mapping[str, Any] | None = None,
    run_id: str | None = None,
    persist_intermediates: bool = False,
    *,
    config_dir: str | Path | None = None,
    source_rows_by_table: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    nlp: Any = None,
    terminology_mode: str = "ALL",
    terminology_systems: Sequence[str] | None = None,
    context_processor: Any = None,
    screening_cutoff: Any = None,
    include_profiles: bool = True,
    profile_output_dir: str | Path | None = None,
    profile_suspicion_levels: Sequence[str] | None = ("HIGHEST_SUSPICION", "HIGH_SUSPICION"),
    known_attr_config_path: str | Path | None = None,
    known_al_config_path: str | Path | None = None,
    evaluation_mode: str = "STRICT",
    include_all_patient_verdicts: bool = True,
) -> PipelineRun:
    """Run ATTRv, ATTRwt, and AL using read-only sources and temp outputs."""
    terminology_mode = terminology_mode_for_systems(
        terminology_systems,
        default=terminology_mode,
    )
    if screening_cutoff is None:
        raise PipelineError("screening_cutoff/as-of date is required for pre-test evidence eligibility")
    configs = {
        phenotype: _load_config(config_dir=config_dir, phenotype=phenotype)
        for phenotype in SCREENED_PHENOTYPES
    }
    extraction_config = AttrExtractionConfig(configs)
    known_config = load_known_attr_config(known_attr_config_path)
    known_al_config = load_known_al_config(known_al_config_path)
    source_config = source_config or default_source_config()
    run_id = run_id or str(uuid.uuid4())
    validation = validate_sources(session, source_config)

    candidates: list[CandidatePatient] = []
    population_patient_ids: set[str] | None = None
    if source_rows_by_table is None:
        if include_all_patient_verdicts:
            population_patient_ids = _fetch_population_patient_ids(session, source_config)
        candidate_config = CandidateConfigUnion(
            extraction_config,
            known_config,
            additional_configs=(known_al_config,),
        )
        candidates = retrieve_candidates(
            session,
            candidate_config,
            run_id=run_id,
            source_config=source_config,
            nlp=nlp,
            terminology_mode=terminology_mode,
            terminology_systems=terminology_systems,
        )
        source_rows_by_table = _fetch_candidate_source_rows(
            session,
            source_config,
            candidate_plan=build_candidate_plan(
                candidate_config,
                config_hash=candidate_config.config_hash,
                source_config=source_config,
                terminology_mode=terminology_mode,
                terminology_systems=terminology_systems,
            ),
        )
        candidate_ids = {candidate.patient_id for candidate in candidates}
    else:
        candidate_ids = None

    result = run_attr_reference_pipeline(
        source_rows_by_table,
        configs=configs,
        source_config=source_config,
        run_id=run_id,
        candidate_patient_ids=candidate_ids,
        population_patient_ids=population_patient_ids,
        nlp=nlp,
        terminology_mode=terminology_mode,
        terminology_systems=terminology_systems,
        context_processor=context_processor,
        screening_cutoff=screening_cutoff,
        include_profiles=include_profiles,
        profile_output_dir=profile_output_dir,
        profile_suspicion_levels=profile_suspicion_levels,
        known_attr_config=known_config,
        known_al_config=known_al_config,
        evaluation_mode=evaluation_mode,
        include_all_patient_verdicts=include_all_patient_verdicts,
    )
    result.candidate_patients = candidates
    known_ids = {str(row.patient_id) for row in result.known_attr_patients}
    known_ids |= {str(row.patient_id) for row in result.known_al_patients}
    retrieved_ids = set(candidate_ids or {event.patient_id for event in result.source_events}) | known_ids
    result.stage_counts["candidate_patients"] = len(retrieved_ids - known_ids)
    result.stage_counts["candidate_patients_total_retrieved"] = len(retrieved_ids)
    result.source_validation = _plain(validation)
    if persist_intermediates:
        _materialize_pipeline_run(session, result)

    return result


def run_attrv_reference_pipeline(
    rows_by_table: Mapping[str, Iterable[Mapping[str, Any]]],
    **kwargs: Any,
) -> PipelineRun:
    """Legacy name retained; production behavior now always runs both ATTR phenotypes."""
    requested = kwargs.pop("phenotype", "ATTRV")
    if str(requested).upper() != "ATTRV":
        raise PipelineError("run_attrv_reference_pipeline only accepts the ATTRV phenotype")
    legacy_config = kwargs.pop("config", None)
    if legacy_config is not None and "configs" not in kwargs:
        raise PipelineError(
            "The legacy single ATTRV config argument is no longer accepted; "
            "the production pipeline requires both ATTRV and ATTRWT configs"
        )
    return run_attr_reference_pipeline(rows_by_table, **kwargs)


def run_attrv_v4_pipeline(
    session: Any,
    source_config: Mapping[str, Any] | None = None,
    run_id: str | None = None,
    persist_intermediates: bool = False,
    **kwargs: Any,
) -> PipelineRun:
    """Legacy name retained; production behavior now always runs both ATTR phenotypes."""
    requested = kwargs.pop("phenotype", "ATTRV")
    if str(requested).upper() != "ATTRV":
        raise PipelineError("run_attrv_v4_pipeline only accepts the ATTRV phenotype")
    return run_attr_v4_pipeline(
        session,
        source_config=source_config,
        run_id=run_id,
        persist_intermediates=persist_intermediates,
        **kwargs,
    )


__all__ = [
    "WORKSPACE_RESULT_COLLECTIONS",
    "PipelineError",
    "PipelineRun",
    "ATTR_PHENOTYPES",
    "SCREENED_PHENOTYPES",
    "AttrExtractionConfig",
    "run_attr_reference_pipeline",
    "run_attr_v4_pipeline",
    "run_attrv_reference_pipeline",
    "run_attrv_v4_pipeline",
]

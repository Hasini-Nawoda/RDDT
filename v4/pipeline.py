"""End-to-end phenotype-generic V4 orchestration.

The orchestrator loads the compiled configuration, validates the
Snowflake source contract, creates only session temporary tables, preserves
long-form evidence, and delegates clinical reasoning to the generic reference
engine.  It contains no clinical terms, codes, thresholds, or fallback rules.
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
from .extraction.candidate_net import CandidatePatient
from .extraction.evidence_qualification import ClinicalContextAdapter
from .extraction.known_attr import (
    CandidateConfigUnion,
    KnownAttrConfig,
    load_known_attr_config,
)
from .warehouse.snowflake_io import create_run_table, execute, insert_rows
from .pipeline_steps.step_01_source_validation import load_config, validate_sources
from .pipeline_steps.step_02_candidate_retrieval import candidate_records, retrieve_candidates
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
    build_known_profiles,
    build_profiles,
    export_attr_profile_files,
    export_known_profile_files,
    export_profile_files,
)
from .warehouse.source_schema import default_source_config, qualified_table_name, quote_identifier


TEMP_TABLES = {
    "candidate_patients": "AMY_V4_CANDIDATE_PATIENT",
    "known_attr_patients": "AMY_V4_KNOWN_ATTR",
    "source_events": "AMY_V4_SOURCE_EVENT",
    "atom_matches": "AMY_V4_ATOM_MATCH",
    "evidence_events": "AMY_V4_EVIDENCE_EVENT",
    "signal_hits": "AMY_V4_SIGNAL_HIT",
    "bucket_state": "AMY_V4_BUCKET_STATE",
    "combination_hits": "AMY_V4_COMBINATION_HIT",
    "guardrail_hits": "AMY_V4_GUARDRAIL_HIT",
    "phenotype_results": "AMY_V4_PHENOTYPE_RESULT",
    "router_output": "AMY_V4_ROUTER_OUTPUT",
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
        "PRIORITY_CLASS", "SUSPICION_LEVEL", "MATCHED_COMBINATION_ID", "SUPPORTING_SIGNAL_IDS",
        "SUPPORTING_BUCKETS", "SUPPORT_LINEAGE_IDS", "SUPPORTING_EVENT_DATES",
        "GUARDRAIL_IDS", "PARALLEL_ROUTES", "EXPLANATION", "CONFIG_HASH",
        "IMPLEMENTATION_VERSION",
    ),
    "router_output": (
        "RUN_ID", "PATIENT_ID", "PHENOTYPE", "STATUS", "RESULT_ROUTE",
        "PRIORITY_CLASS", "SUSPICION_LEVEL", "MATCHED_COMBINATION_ID", "SUPPORTING_SIGNAL_IDS",
        "SUPPORTING_BUCKETS", "SUPPORT_LINEAGE_IDS", "SUPPORTING_EVENT_DATES",
        "GUARDRAIL_IDS", "PARALLEL_ROUTES", "EXPLANATION", "CONFIG_HASH",
        "IMPLEMENTATION_VERSION", "ROUTER_SCHEMA_VERSION",
    ),
}


class PipelineError(RuntimeError):
    """Raised when a run cannot safely continue."""


ATTR_PHENOTYPES = ("ATTRV", "ATTRWT")


class AttrExtractionConfig:
    """Shared atom/terminology view for one-pass ATTRv plus ATTRwt extraction."""

    def __init__(self, configs: Mapping[str, Any]):
        missing = [phenotype for phenotype in ATTR_PHENOTYPES if phenotype not in configs]
        if missing:
            raise PipelineError(f"Combined ATTR run is missing phenotype configs: {missing}")
        baseline = configs[ATTR_PHENOTYPES[0]]
        self.tables = {
            "atoms": baseline.rows("atoms"),
            "terminology": baseline.rows("terminology"),
        }
        for phenotype in ATTR_PHENOTYPES[1:]:
            current = configs[phenotype]
            for table in ("atoms", "terminology"):
                if current.rows(table) != self.tables[table]:
                    raise PipelineError(
                        f"{phenotype} does not share the same {table} registry; "
                        "one-pass extraction would be unsafe"
                    )
        hash_payload = json.dumps(
            {phenotype: configs[phenotype].config_hash for phenotype in ATTR_PHENOTYPES},
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
    source_validation: dict[str, Any] | None
    stage_counts: dict[str, int]
    evaluated_phenotypes: list[str] = field(default_factory=list)
    config_gaps: list[dict[str, Any]] = field(default_factory=list)
    candidate_patients: list[Any] = field(default_factory=list)
    known_attr_patients: list[Any] = field(default_factory=list)
    known_attr_profiles: list[dict[str, Any]] = field(default_factory=list)
    known_attr_exports: dict[str, str] = field(default_factory=dict)
    source_events: list[Any] = field(default_factory=list)
    atom_matches: list[Any] = field(default_factory=list)
    evidence_events: list[Any] = field(default_factory=list)
    signal_hits: list[Any] = field(default_factory=list)
    bucket_state: list[Any] = field(default_factory=list)
    combination_hits: list[Any] = field(default_factory=list)
    guardrail_hits: list[Any] = field(default_factory=list)
    phenotype_results: list[Any] = field(default_factory=list)
    router_output: list[Any] = field(default_factory=list)
    patient_profiles: list[dict[str, Any]] = field(default_factory=list)
    profile_exports: dict[str, str] = field(default_factory=dict)
    temporary_tables: dict[str, str] = field(default_factory=lambda: dict(TEMP_TABLES))

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "config_hash": self.config_hash,
            "implementation_version": self.implementation_version,
            "evaluated_phenotypes": list(self.evaluated_phenotypes),
            "stage_counts": dict(self.stage_counts),
            "config_gaps": list(self.config_gaps),
            "temporary_tables": dict(self.temporary_tables),
            "profile_exports": dict(self.profile_exports),
            "known_attr_exports": dict(self.known_attr_exports),
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


def _execute_candidate_plan(
    session: Any,
    config: Any,
    *,
    run_id: str,
    source_config: Mapping[str, Any],
    nlp: Any,
) -> list[CandidatePatient]:
    return retrieve_candidates(session, config, run_id=run_id, source_config=source_config, nlp=nlp)


def _candidate_records(candidates: Iterable[CandidatePatient]) -> list[dict[str, Any]]:
    return candidate_records(list(candidates))


def _materialize_records(
    session: Any,
    table_name: str,
    records: Iterable[Any],
    *,
    required_columns: Sequence[str] = (),
    run_id: str | None = None,
) -> int:
    rows = [_plain(record) for record in records]
    if not rows:
        empty_columns = list(required_columns) or ["RUN_ID", "EMPTY_REASON"]
        create_run_table(session, table_name, {key: "VARCHAR" for key in empty_columns})
        return 0
    keys: list[str] = list(required_columns)
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError(f"Cannot materialize non-object row in {table_name}")
        for key in row:
            upper = str(key).upper()
            if upper not in keys:
                keys.append(upper)
    create_run_table(session, table_name, {key: "VARCHAR" for key in keys})
    values = []
    for row in rows:
        normalized = {str(key).upper(): value for key, value in row.items()}
        if run_id is not None:
            normalized.setdefault("RUN_ID", run_id)
        values.append(tuple(
            json.dumps(normalized.get(key), sort_keys=True, ensure_ascii=False)
            if isinstance(normalized.get(key), (dict, list, tuple, set))
            else None if normalized.get(key) is None
            else str(normalized.get(key))
            for key in keys
        ))
    return insert_rows(session, table_name, keys, values)


def _fetch_candidate_source_rows(
    session: Any,
    source_config: Mapping[str, Any],
    *,
    candidate_table: str,
) -> dict[str, list[dict[str, Any]]]:
    rows_by_table: dict[str, list[dict[str, Any]]] = {}
    namespace = source_config.get("namespace")
    for table_key, table in source_config.get("tables", {}).items():
        if not table.get("enabled", True):
            continue
        patient_column = table.get("columns", {}).get("patient_id")
        if not patient_column:
            continue
        table_name = str(table["name"])
        physical = qualified_table_name(table, str(namespace) if namespace else None)
        sql = (
            f"SELECT SRC.* FROM {physical} SRC "
            f"JOIN (SELECT DISTINCT PATIENT_ID FROM {quote_identifier(candidate_table)}) CAND "
            f"ON CAST(SRC.{quote_identifier(str(patient_column))} AS VARCHAR) = CAND.PATIENT_ID"
        )
        rows_by_table[table_key] = [_row_dict(row) for row in execute(session, sql)]
    return rows_by_table


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
    context_processor: Any = None,
    screening_cutoff: Any = None,
    include_profiles: bool = True,
    profile_output_dir: str | Path | None = None,
    profile_priority_classes: Sequence[str] | None = None,
    profile_suspicion_levels: Sequence[str] | None = ("HIGHEST_SUSPICION", "HIGH_SUSPICION"),
    known_attr_config: KnownAttrConfig | None = None,
) -> PipelineRun:
    """Run one loaded phenotype package on already supplied warehouse rows."""
    if screening_cutoff is None:
        raise PipelineError("screening_cutoff/as-of date is required for pre-test evidence eligibility")
    source_config = source_config or default_source_config()
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
    known_attr, events = separate_known_attr(
        all_events,
        run_id=run_id,
        screening_cutoff=screening_cutoff,
        known_attr_config=known_config,
        nlp=nlp,
        context_processor=context_processor,
    )
    known_ids = known_attr.patient_ids
    matches = match_atoms(events, config, nlp=nlp)
    evidence = qualify_evidence(
        matches,
        config,
        context_processor=context_processor,
        screening_cutoff=screening_cutoff,
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
        patient_signals = evaluate_signals_stage(config, patient_evidence, patient_id=patient_id, phenotype=selected_phenotype)
        patient_buckets = evaluate_buckets_stage(config, patient_signals, patient_id=patient_id, phenotype=selected_phenotype)
        patient_combinations = match_combinations_stage(config, patient_signals, patient_buckets, patient_id=patient_id, phenotype=selected_phenotype)
        patient_guards = evaluate_guardrails_stage(config, patient_evidence, patient_id=patient_id, phenotype=selected_phenotype)
        patient_results, patient_router = route_stage(config, patient_combinations, patient_guards, patient_id=patient_id, phenotype=selected_phenotype, run_id=run_id, config_hash=config.config_hash, implementation_version=IMPLEMENTATION_VERSION)
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
    profiles = build_profiles(router_output, config=config, phenotype=selected_phenotype, source_events=events, evidence_events=evidence, signal_hits=signal_hits, bucket_state=bucket_state, combination_hits=combination_hits, guardrail_hits=guardrail_hits, demographics=demographics, run_id=run_id, include_proprietary_trace=True, profile_priority_classes=profile_priority_classes, profile_suspicion_levels=profile_suspicion_levels) if include_profiles else []
    known_profiles = build_known_profiles(
        known_attr.patients,
        known_config=known_config,
        source_events=all_events,
        evidence_events=known_attr.evidence,
        demographics=demographics,
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
    nlp: Any = None,
    context_processor: Any = None,
    screening_cutoff: Any = None,
    include_profiles: bool = True,
    profile_output_dir: str | Path | None = None,
    profile_suspicion_levels: Sequence[str] | None = ("HIGHEST_SUSPICION", "HIGH_SUSPICION"),
    known_attr_config: KnownAttrConfig | None = None,
) -> PipelineRun:
    """Run ATTRv and ATTRwt together after one shared extraction pass."""
    if screening_cutoff is None:
        raise PipelineError("screening_cutoff/as-of date is required for pre-test evidence eligibility")
    loaded_configs = dict(configs or {
        phenotype: _load_config(config_dir=config_dir, phenotype=phenotype)
        for phenotype in ATTR_PHENOTYPES
    })
    extraction_config = AttrExtractionConfig(loaded_configs)
    source_config = source_config or default_source_config()
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
    known_attr, events = separate_known_attr(
        all_events,
        run_id=run_id,
        screening_cutoff=screening_cutoff,
        known_attr_config=known_config,
        nlp=nlp,
        context_processor=context_processor,
    )
    matches = match_atoms(events, extraction_config, nlp=nlp)
    evidence = qualify_evidence(
        matches,
        extraction_config,
        context_processor=context_processor,
        screening_cutoff=screening_cutoff,
    )
    patient_universe = set(candidate_patient_ids or {event.patient_id for event in all_events})
    patients = sorted(patient_universe - known_attr.patient_ids)

    signal_hits: list[Any] = []
    bucket_state: list[Any] = []
    combination_hits: list[Any] = []
    guardrail_hits: list[Any] = []
    phenotype_results: list[Any] = []
    router_output: list[Any] = []
    for patient_id in patients:
        patient_evidence = [row for row in evidence if row.patient_id == patient_id]
        for phenotype in ATTR_PHENOTYPES:
            config = loaded_configs[phenotype]
            patient_signals = evaluate_signals_stage(
                config,
                patient_evidence,
                patient_id=patient_id,
                phenotype=phenotype,
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

    demographics = _demographics(rows_by_table, source_config)
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
        include_proprietary_trace=True,
        profile_suspicion_levels=profile_suspicion_levels,
    ) if include_profiles else []
    known_profiles = build_known_profiles(
        known_attr.patients,
        known_config=known_config,
        source_events=all_events,
        evidence_events=known_attr.evidence,
        demographics=demographics,
        include_proprietary_trace=True,
    ) if include_profiles else []
    exports = export_attr_profile_files(profiles, profile_output_dir)
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
        config_hash=extraction_config.config_hash,
        implementation_version=IMPLEMENTATION_VERSION,
        source_validation=None,
        stage_counts=stages,
        evaluated_phenotypes=list(ATTR_PHENOTYPES),
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


def _run_single_phenotype_v4_pipeline(
    session: Any,
    phenotype: str,
    source_config: Mapping[str, Any] | None = None,
    run_id: str | None = None,
    persist_intermediates: bool = True,
    *,
    config_dir: str | Path | None = None,
    source_rows_by_table: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    nlp: Any = None,
    context_processor: Any = None,
    screening_cutoff: Any = None,
    include_profiles: bool = True,
    profile_output_dir: str | Path | None = None,
    profile_priority_classes: Sequence[str] | None = None,
    profile_suspicion_levels: Sequence[str] | None = ("HIGHEST_SUSPICION", "HIGH_SUSPICION"),
    known_attr_config_path: str | Path | None = None,
) -> PipelineRun:
    """Run one configured phenotype pipeline against a Snowpark-like session.

    ``persist_intermediates`` controls session-table materialization only.
    No code path creates permanent or transient warehouse objects.
    """
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
        candidates = retrieve_candidates(
            session,
            CandidateConfigUnion(config, known_config),
            run_id=run_id,
            source_config=source_config,
            nlp=nlp,
        )
        candidate_rows = candidate_records(candidates)
        _materialize_records(
            session,
            TEMP_TABLES["candidate_patients"],
            candidate_rows,
            required_columns=TEMP_TABLE_SCHEMAS["candidate_patients"],
            run_id=run_id,
        )
        source_rows_by_table = _fetch_candidate_source_rows(
            session,
            source_config,
            candidate_table=TEMP_TABLES["candidate_patients"],
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
        context_processor=context_processor,
        screening_cutoff=screening_cutoff,
        include_profiles=include_profiles,
        profile_output_dir=profile_output_dir,
        profile_priority_classes=profile_priority_classes,
        profile_suspicion_levels=profile_suspicion_levels,
        known_attr_config=known_config,
    )
    result.candidate_patients = candidates
    known_ids = {str(row.patient_id) for row in result.known_attr_patients}
    retrieved_ids = set(candidate_ids or {event.patient_id for event in result.source_events}) | known_ids
    result.stage_counts["candidate_patients"] = len(retrieved_ids - known_ids)
    result.stage_counts["candidate_patients_total_retrieved"] = len(retrieved_ids)
    result.source_validation = _plain(validation)

    if persist_intermediates:
        if source_rows_by_table is not None and not candidates:
            synthetic = [
                {
                    "run_id": run_id,
                    "patient_id": patient_id,
                    "candidate_reason_type": "CALLER_SUPPLIED_CANDIDATE_ROWS",
                    "config_hash": config.config_hash,
                }
                for patient_id in sorted(
                    {event.patient_id for event in result.source_events}
                    | {str(row.patient_id) for row in result.known_attr_patients}
                )
            ]
            _materialize_records(
                session,
                TEMP_TABLES["candidate_patients"],
                synthetic,
                required_columns=TEMP_TABLE_SCHEMAS["candidate_patients"],
                run_id=run_id,
            )
        stage_rows = {
            "known_attr_patients": result.known_attr_patients,
            "source_events": result.source_events,
            "atom_matches": result.atom_matches,
            "evidence_events": result.evidence_events,
            "signal_hits": result.signal_hits,
            "bucket_state": result.bucket_state,
            "combination_hits": result.combination_hits,
            "guardrail_hits": result.guardrail_hits,
            "phenotype_results": result.phenotype_results,
            "router_output": result.router_output,
        }
        for stage, records in stage_rows.items():
            _materialize_records(
                session,
                TEMP_TABLES[stage],
                records,
                required_columns=TEMP_TABLE_SCHEMAS[stage],
                run_id=run_id,
            )
    return result


def run_attr_v4_pipeline(
    session: Any,
    source_config: Mapping[str, Any] | None = None,
    run_id: str | None = None,
    persist_intermediates: bool = True,
    *,
    config_dir: str | Path | None = None,
    source_rows_by_table: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    nlp: Any = None,
    context_processor: Any = None,
    screening_cutoff: Any = None,
    include_profiles: bool = True,
    profile_output_dir: str | Path | None = None,
    profile_suspicion_levels: Sequence[str] | None = ("HIGHEST_SUSPICION", "HIGH_SUSPICION"),
    known_attr_config_path: str | Path | None = None,
) -> PipelineRun:
    """Run ATTRv and ATTRwt for every candidate and emit one ATTR profile."""
    if screening_cutoff is None:
        raise PipelineError("screening_cutoff/as-of date is required for pre-test evidence eligibility")
    configs = {
        phenotype: _load_config(config_dir=config_dir, phenotype=phenotype)
        for phenotype in ATTR_PHENOTYPES
    }
    extraction_config = AttrExtractionConfig(configs)
    known_config = load_known_attr_config(known_attr_config_path)
    source_config = source_config or default_source_config()
    run_id = run_id or str(uuid.uuid4())
    validation = validate_sources(session, source_config)

    candidates: list[CandidatePatient] = []
    if source_rows_by_table is None:
        candidates = retrieve_candidates(
            session,
            CandidateConfigUnion(extraction_config, known_config),
            run_id=run_id,
            source_config=source_config,
            nlp=nlp,
        )
        _materialize_records(
            session,
            TEMP_TABLES["candidate_patients"],
            candidate_records(candidates),
            required_columns=TEMP_TABLE_SCHEMAS["candidate_patients"],
            run_id=run_id,
        )
        source_rows_by_table = _fetch_candidate_source_rows(
            session,
            source_config,
            candidate_table=TEMP_TABLES["candidate_patients"],
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
        nlp=nlp,
        context_processor=context_processor,
        screening_cutoff=screening_cutoff,
        include_profiles=include_profiles,
        profile_output_dir=profile_output_dir,
        profile_suspicion_levels=profile_suspicion_levels,
        known_attr_config=known_config,
    )
    result.candidate_patients = candidates
    known_ids = {str(row.patient_id) for row in result.known_attr_patients}
    retrieved_ids = set(candidate_ids or {event.patient_id for event in result.source_events}) | known_ids
    result.stage_counts["candidate_patients"] = len(retrieved_ids - known_ids)
    result.stage_counts["candidate_patients_total_retrieved"] = len(retrieved_ids)
    result.source_validation = _plain(validation)

    if persist_intermediates:
        if source_rows_by_table is not None and not candidates:
            synthetic_ids = (
                {event.patient_id for event in result.source_events}
                | {str(row.patient_id) for row in result.known_attr_patients}
            )
            _materialize_records(
                session,
                TEMP_TABLES["candidate_patients"],
                [
                    {
                        "run_id": run_id,
                        "patient_id": patient_id,
                        "candidate_reason_type": "CALLER_SUPPLIED_CANDIDATE_ROWS",
                        "config_hash": extraction_config.config_hash,
                    }
                    for patient_id in sorted(synthetic_ids)
                ],
                required_columns=TEMP_TABLE_SCHEMAS["candidate_patients"],
                run_id=run_id,
            )
        stage_rows = {
            "known_attr_patients": result.known_attr_patients,
            "source_events": result.source_events,
            "atom_matches": result.atom_matches,
            "evidence_events": result.evidence_events,
            "signal_hits": result.signal_hits,
            "bucket_state": result.bucket_state,
            "combination_hits": result.combination_hits,
            "guardrail_hits": result.guardrail_hits,
            "phenotype_results": result.phenotype_results,
            "router_output": result.router_output,
        }
        for stage, records in stage_rows.items():
            _materialize_records(
                session,
                TEMP_TABLES[stage],
                records,
                required_columns=TEMP_TABLE_SCHEMAS[stage],
                run_id=run_id,
            )
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
    persist_intermediates: bool = True,
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
    "TEMP_TABLES",
    "TEMP_TABLE_SCHEMAS",
    "PipelineError",
    "PipelineRun",
    "ATTR_PHENOTYPES",
    "AttrExtractionConfig",
    "run_attr_reference_pipeline",
    "run_attr_v4_pipeline",
    "run_attrv_reference_pipeline",
    "run_attrv_v4_pipeline",
]

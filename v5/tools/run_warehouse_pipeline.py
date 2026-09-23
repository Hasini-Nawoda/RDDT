"""Warehouse runner for the ICD-dated claims pipeline.

The heavy work stays in Snowflake. Claims are reduced to configured ICD-10
codes and encounter dates are resolved once. The notebook then scores patients
in batches of a few hundred and writes that batch's verdicts before the next
batch. Profiles are built from that same scoring pass. Chart tables are read
once per batch, only for patients who need a profile. A patient is not sent
through the engine a second time.

Re-running the notebook continues from those files. A new Snowflake session
rebuilds the temporary screen table, and it does not rescore patients whose
verdicts were already saved.

Every warehouse statement is checked before it runs. Allowed statements are
SELECT, WITH, SHOW, DESCRIBE, EXPLAIN, CREATE TEMPORARY TABLE, and INSERT
INTO an AMY_V5_ temporary table. UPDATE, DELETE, DROP, ALTER, TRUNCATE,
MERGE, and CREATE OR REPLACE are rejected. CREATE OR REPLACE is rejected
because replacing a table drops the previous one.
"""

from __future__ import annotations

# The continue cell checks this before scoring. The old file does not have it.
COUNTS_SAVE_SAFE = True
# Profiles are written with each checkpoint. A counts-only run is no longer possible.
CHECKPOINT_PROFILES = True

import csv
import gc
import io
import json
import re
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from v5.config_loader import load_phenotype_configs
from v5.extraction.code_semantics import (
    canonical_code,
    expanded_values,
    prefix_fallback_supported,
    term_values,
)
from v5.extraction.confirmed_icd10 import DEFAULT_CONFIRMED_CONFIG, extract_confirmed_icd10
from v5.extraction.extraction_contract import normalize_system
from v5.output.patient_profile import build_patient_profile, profiles_jsonl_bytes
from v5.pipeline import SCREENED_PHENOTYPES, AttrExtractionConfig, run_attr_reference_pipeline
from v5.pipeline_steps.step_11_patient_profiles import (
    build_aa_profiles,
    build_al_detected_profiles,
    build_attr_profiles,
)
from v5.reasoning.risk_labels import SUSPICION_FOLDER
from v5.warehouse.source_schema import (
    default_source_config,
    is_table_profile_enabled,
    quote_identifier,
)


CODE_TABLE = "AMY_V5_ICD_CODE"
SCREEN_TABLE = "TEMP_V5_SCREEN_CLAIM"
SCORE_PATIENT_TABLE = "AMY_V5_SCORE_PATIENT"
SCORE_CENSUS_TABLE = "TEMP_V5_CENSUS"
PROFILE_PATIENT_TABLE = "AMY_V5_PROFILE_PATIENT"
PROFILE_TABLES = {
    "census": "AMY_V5_PROFILE_CENSUS",
    "claim": "AMY_V5_PROFILE_CLAIM",
    "encounter": "AMY_V5_PROFILE_ENCOUNTER",
    "lab": "AMY_V5_PROFILE_LAB",
    "surgical_history": "AMY_V5_PROFILE_SURGICAL",
    "medication": "AMY_V5_PROFILE_MEDICATION",
}
# Already built in the warehouse. The runner only reads these. It does not create them.
PROFILE_SOURCE_TABLES = {
    "lab": "TEMP_V5_LAB",
    "encounter": "TEMP_V5_ENCOUNTER",
    "surgical_history": "TEMP_V5_SURGICAL",
    "medication": "TEMP_V5_MEDICATION",
}
PROFILE_LEVELS = (
    "HIGHEST_SUSPICION",
    "HIGH_SUSPICION",
)
SUSPICION_LEVELS = {
    "HIGHEST_SUSPICION",
    "HIGH_SUSPICION",
    "MODERATE_SUSPICION",
}
# 300,000 patients in a day needs a few hundred scored per warehouse round trip.
# Charts are fetched only for the patients who need a profile, in one query per
# table, and the scoring pass is not repeated for those patients.
MAX_SCORE_BATCH = 200
PROFILE_CHART_BATCH = 10
# Counted in Snowflake before any row is downloaded. A larger pull is what
# exhausts the notebook and kills the kernel before a checkpoint can be written.
MAX_CLAIM_ROWS = 8000
MAX_PROFILE_ROWS = 2000
MAX_PATIENT_ATTEMPTS = 3
_LEVEL_RANK = {
    "HIGHEST_SUSPICION": 0,
    "HIGH_SUSPICION": 1,
    "MODERATE_SUSPICION": 2,
}
_PROFILE_ORDER_FIELDS = {
    "lab": "observation_datetime",
    "encounter": "encounter_date",
    "surgical_history": "event_date",
}
VERDICT_FIELDS = (
    "patient_id",
    "population_status",
    "confirmation_status",
    "attr_status",
    "attr_suspicion_level",
    "attrv_status",
    "attrwt_status",
    "al_status",
    "al_suspicion_level",
    "aa_status",
    "aa_suspicion_level",
    "candidate_for_review",
    "evaluation_mode",
    "verdict_scope",
    "reason",
)


def collect_icd10_screening_codes(
    configs: Mapping[str, Any],
    confirmed: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Return the ICD codes the warehouse should retrieve.

    Exact codes are compared after dots are removed, matching the pipeline.
    Prefix rows are only the explicit family fallbacks already configured.
    """
    exact: set[str] = set()
    prefix: set[str] = set()
    terms: list[Mapping[str, Any]] = []
    for config in configs.values():
        terms.extend(config.rows("terminology"))
    _collect_terminology(confirmed, terms)
    for term in terms:
        system = normalize_system(
            term.get("terminology_system", term.get("system", ""))
        )
        if system not in {"ICD", "ICD10"}:
            continue
        if prefix_fallback_supported(term):
            raw = str(term.get("value") or "").strip().upper()
            if raw.endswith("."):
                prefix.add(canonical_code(raw[:-1], "ICD10"))
        for value in (*term_values(term), *expanded_values(term)):
            if str(value).strip().endswith("."):
                continue
            code = canonical_code(value, "ICD10")
            if code:
                exact.add(code)
    rows = [
        {"NORMALIZED_CODE": code, "MATCH_MODE": "EXACT"}
        for code in sorted(exact)
    ]
    rows.extend(
        {"NORMALIZED_CODE": code, "MATCH_MODE": "PREFIX"}
        for code in sorted(prefix)
        if code
    )
    return rows


def _say(message: Any) -> None:
    print(message, flush=True)


def _bounded_score_batch(score_batch_size: int) -> int:
    """Cap a batch so one fetch cannot exhaust the notebook."""
    if score_batch_size < 1:
        raise ValueError("batch sizes must be positive")
    return min(score_batch_size, MAX_SCORE_BATCH)


def _verdict_needs_profile(verdict: Mapping[str, Any]) -> bool:
    """Confirmed patients and highest or high suspicion get a profile. Moderate is counted only."""
    if str(verdict.get("population_status") or "").upper() == "SCORE_FAILED":
        return False
    if str(verdict.get("confirmation_status") or "").upper() == "CONFIRMED":
        return True
    return _export_verdict(verdict)


def _profile_sort_key(verdict: Mapping[str, Any]) -> tuple[int, int, str]:
    """Write the densest review profiles first so a stop still keeps them."""
    attr_rank = _LEVEL_RANK.get(str(verdict.get("attr_suspicion_level") or "").upper(), 9)
    al_rank = _LEVEL_RANK.get(str(verdict.get("al_suspicion_level") or "").upper(), 9)
    aa_rank = _LEVEL_RANK.get(str(verdict.get("aa_suspicion_level") or "").upper(), 9)
    confirmed_rank = 0 if str(verdict.get("confirmation_status") or "").upper() == "CONFIRMED" else 1
    return (min(attr_rank, al_rank, aa_rank), confirmed_rank, str(verdict.get("patient_id") or ""))


def _pending_profile_verdicts(
    verdicts: Mapping[str, Mapping[str, Any]],
    profiled_ids: set[str],
) -> list[Mapping[str, Any]]:
    pending = [
        verdict for patient_id, verdict in verdicts.items()
        if patient_id not in profiled_ids and _verdict_needs_profile(verdict)
    ]
    pending.sort(key=_profile_sort_key)
    return pending


def _unscored_patient_ids(
    ordered_ids: Sequence[str],
    scored_ids: set[str],
    patient_limit: int | None,
) -> list[str]:
    pending = [patient_id for patient_id in ordered_ids if patient_id not in scored_ids]
    if patient_limit is not None:
        return pending[:patient_limit]
    return pending


def _verdicts_by_patient(rows: Sequence[Mapping[str, str]]) -> dict[str, dict[str, str]]:
    """Later checkpoint files win. One row per patient, so counts are not doubled."""
    verdicts: dict[str, dict[str, str]] = {}
    for row in rows:
        patient_id = str(row.get("patient_id") or "")
        if patient_id:
            verdicts[patient_id] = dict(row)
    return verdicts


def _release_query_memory(session: Any) -> None:
    """Drop the connector's last result set so fetched claim rows are not retained."""
    connection = getattr(session, "_conn", None)
    cursor = getattr(connection, "_cursor", None) if connection is not None else None
    if cursor is not None:
        for name in ("_result", "_query_result_queue", "_result_set"):
            if hasattr(cursor, name):
                setattr(cursor, name, None)
    gc.collect()


def _empty_counts() -> dict[str, int]:
    return {
        "patients_scored": 0,
        "confirmed": 0,
        "suspicious_amyloidosis": 0,
        "high_attr": 0,
        "highest_attr": 0,
        "moderate_attr": 0,
        "high_al": 0,
        "highest_al": 0,
        "moderate_al": 0,
        "high_aa": 0,
        "highest_aa": 0,
        "moderate_aa": 0,
    }


def _tally_verdict(counts: dict[str, int], verdict: Mapping[str, Any], *, confirmed: bool = False) -> None:
    counts["patients_scored"] += 1
    attr_level = str(verdict.get("attr_suspicion_level") or "").upper()
    al_level = str(verdict.get("al_suspicion_level") or "").upper()
    aa_level = str(verdict.get("aa_suspicion_level") or "").upper()
    is_confirmed = confirmed or str(verdict.get("confirmation_status") or "").upper() == "CONFIRMED"
    if is_confirmed:
        counts["confirmed"] += 1
    if attr_level in SUSPICION_LEVELS or al_level in SUSPICION_LEVELS or aa_level in SUSPICION_LEVELS:
        counts["suspicious_amyloidosis"] += 1
    if attr_level == "HIGH_SUSPICION":
        counts["high_attr"] += 1
    elif attr_level == "HIGHEST_SUSPICION":
        counts["highest_attr"] += 1
    elif attr_level == "MODERATE_SUSPICION":
        counts["moderate_attr"] += 1
    if al_level == "HIGH_SUSPICION":
        counts["high_al"] += 1
    elif al_level == "HIGHEST_SUSPICION":
        counts["highest_al"] += 1
    elif al_level == "MODERATE_SUSPICION":
        counts["moderate_al"] += 1
    if aa_level == "HIGH_SUSPICION":
        counts["high_aa"] += 1
    elif aa_level == "HIGHEST_SUSPICION":
        counts["highest_aa"] += 1
    elif aa_level == "MODERATE_SUSPICION":
        counts["moderate_aa"] += 1


def run_icd_dated_claims_warehouse(
    session: Any,
    *,
    namespace: str,
    screening_cutoff: str,
    output_dir: str | Path,
    score_batch_size: int = MAX_SCORE_BATCH,
    profile_batch_size: int = 1,
    patient_limit: int | None = None,
    resume: bool = True,
    counts_only: bool = False,
    fresh_start: bool = False,
) -> dict[str, Any]:
    """Score every screened patient, save profiles, and continue after a stop.

    Checkpoints are files in ``output_dir``. Re-run the same call to continue.
    ``counts_only`` is ignored: counts and profiles are both saved.
    ``fresh_start=True`` deletes previous checkpoint files in that folder.
    """
    if profile_batch_size < 1:
        raise ValueError("batch sizes must be positive")
    if patient_limit is not None and patient_limit < 1:
        raise ValueError("patient_limit must be positive")
    requested_batch = score_batch_size
    score_batch_size = _bounded_score_batch(score_batch_size)
    if counts_only:
        _say({
            "counts_only": "ignored",
            "profiles": "written for confirmed and highest, high, or moderate suspicion",
        })
    if requested_batch != score_batch_size:
        _say({
            "score_batch_size": requested_batch,
            "using": score_batch_size,
            "reason": "larger batches exhaust the notebook CPU runtime",
        })
    _say({
        "phase": "scan",
        "status": "loading phenotype configs",
        "resume": True,
        "fresh_start": fresh_start,
        "profiles": "checkpointed with each batch",
    })
    source_config = default_source_config(profile="icd_dated_claims_v1")
    source_config["namespace"] = _namespace(namespace)
    configs = load_phenotype_configs(SCREENED_PHENOTYPES)
    confirmed = json.loads(DEFAULT_CONFIRMED_CONFIG.read_text(encoding="utf-8"))
    codes = collect_icd10_screening_codes(configs, confirmed)
    if not codes:
        raise RuntimeError("no ICD-10 screening codes were found in the v5 config")

    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    if fresh_start:
        _reset_outputs(output)
    if not resume:
        _say({"resume": "checkpoints are kept", "fresh_start": fresh_start})

    started = time.perf_counter()
    _say({
        "phase": "scan",
        "namespace": source_config["namespace"],
        "evaluation_mode": "ICD_DATED_CLAIMS",
        "profile": "icd_dated_claims_v1",
        "screening_codes": len(codes),
        "prefix_families": sum(row["MATCH_MODE"] == "PREFIX" for row in codes),
        "screening_cutoff": screening_cutoff,
        "patient_limit": patient_limit,
        "score_batch_size": score_batch_size,
        "profile_chart_batch": PROFILE_CHART_BATCH,
        "durable_tables": True,
    })
    _say(
        "If this notebook stops, run the same cell again. "
        "Saved verdicts and profiles are kept. Screening claims and census are read from "
        "the permanent TEMP_V5 tables and are not rebuilt."
    )

    namespace = str(source_config["namespace"])
    screen_table = _qualified_temp(namespace, SCREEN_TABLE)
    census_table = _qualified_temp(namespace, SCORE_CENSUS_TABLE)
    missing_tables = [
        name
        for name, table_name in (
            (SCREEN_TABLE, screen_table),
            (SCORE_CENSUS_TABLE, census_table),
        )
        if not _table_readable(session, table_name)
    ]
    if missing_tables:
        raise RuntimeError(
            "Missing permanent tables: "
            + ", ".join(missing_tables)
            + ". Run v5/sql/create_temp_v5_screen.sql once. This notebook does not create them."
        )
    code_seconds = 0.0
    screen_seconds = 0.0
    census_seconds = 0.0
    screen_count = _scalar(session, f"SELECT COUNT(*) FROM {screen_table}")
    patient_count = _scalar(
        session,
        f"SELECT COUNT(DISTINCT {_q(_patient_column(source_config, 'claim'))}) FROM {screen_table}",
    )
    print({
        "screen_claim_rows": screen_count,
        "screen_patients": patient_count,
        "screen_table": screen_table,
        "census_table": census_table,
        "census_rows": _scalar(session, f"SELECT COUNT(*) FROM {census_table}"),
        "rebuilt_this_session": False,
    })
    extraction = AttrExtractionConfig(configs)

    verdicts = _verdicts_by_patient(_read_verdicts(output / "patient_verdicts.csv"))
    profiled_ids, failed_profile_ids = _read_profile_outcomes(output)
    score_attempts = _read_attempt_counts(output, "score_errors")
    profile_attempts = _read_attempt_counts(output, "profile_errors")
    ordered_ids = _patient_ids(session, source_config, None)
    patient_ids = _unscored_patient_ids(ordered_ids, set(verdicts), patient_limit)
    counts = _empty_counts()
    for verdict in verdicts.values():
        _tally_verdict(counts, verdict)
    _say({
        "already_scored": len(verdicts),
        "patients_to_score": len(patient_ids),
        "profiles_already_saved": len(profiled_ids - failed_profile_ids),
        "profiles_still_needed": len(_pending_profile_verdicts(verdicts, profiled_ids)),
        "counts": counts,
    })

    chart_sources = _chart_sources(session, source_config)
    _say({
        "profile_tables": [str(source["table"]) for source in chart_sources],
        "profile_row_cap": None,
        "profile_tables_created_by_runner": False,
    })
    written = {"attr": 0, "al": 0, "aa": 0, "confirmed": 0, "failed": len(failed_profile_ids)}
    profile_started = time.perf_counter()
    _profile_pending(
            session,
        source_config=source_config,
        configs=configs,
        extraction=extraction,
        census_table=census_table,
        screening_cutoff=screening_cutoff,
        output=output,
        verdicts=verdicts,
        profiled_ids=profiled_ids,
        profile_attempts=profile_attempts,
        chart_sources=chart_sources,
        written=written,
        counts=counts,
        batch_size=score_batch_size,
    )
    profile_backfill_seconds = round(time.perf_counter() - profile_started, 1)

    timing_rows: list[dict[str, Any]] = []
    scored_this_run = 0
    score_elapsed = 0.0
    open_batch_sizes = _unfinished_batch_sizes(output, set(verdicts), "batch_open")
    queue: list[list[str]] = [list(batch) for batch in _chunks(patient_ids, score_batch_size)]
    batch_number = 0
    while queue:
        batch = [patient_id for patient_id in queue.pop(0) if patient_id not in verdicts]
        if not batch:
            continue
        batch, remainder, skip_patient = _next_batch_after_memory_stop(batch, open_batch_sizes)
        if remainder:
            queue.insert(0, remainder)
        if skip_patient:
            _skip_oversized_score(
                output,
                batch[0],
                0,
                verdicts,
                counts,
                batch_number,
                reason="notebook stopped while scoring this patient",
            )
            continue
        open_path = _note_open_batch(output, batch, open_batch_sizes, "batch_open")
        batch_number += 1
        try:
            fetch_seconds, score_seconds, profile_seconds = _score_and_checkpoint_batch(
                session,
                source_config=source_config,
                configs=configs,
                extraction=extraction,
                census_table=census_table,
                screening_cutoff=screening_cutoff,
                output=output,
                batch=batch,
                batch_number=batch_number,
                verdicts=verdicts,
                profiled_ids=profiled_ids,
                profile_attempts=profile_attempts,
                chart_sources=chart_sources,
                counts=counts,
                written=written,
                patients_to_score=len(patient_ids),
                scored_this_run=scored_this_run,
                score_attempts=score_attempts,
            )
        except Exception as exc:
            _release_query_memory(session)
            gc.collect()
            pending_ids = [patient_id for patient_id in batch if patient_id not in verdicts]
            if not pending_ids:
                _say({
                    "batch_checkpoint_kept": _short_error(exc),
                    "patients": len(batch),
                })
                fetch_seconds = 0.0
                score_seconds = 0.0
                profile_seconds = 0.0
            elif len(pending_ids) > 1:
                midpoint = max(len(pending_ids) // 2, 1)
                queue.insert(0, pending_ids[midpoint:])
                queue.insert(0, pending_ids[:midpoint])
                _say({
                    "batch_failed": _short_error(exc),
                    "splitting": len(pending_ids),
                    "status": "retrying in smaller batches",
                })
                continue
            else:
                _handle_score_failure(
                    output,
                    pending_ids[0],
                    exc,
                    verdicts=verdicts,
                    attempts=score_attempts,
                    counts=counts,
                )
                fetch_seconds = 0.0
                score_seconds = 0.0
                profile_seconds = 0.0
        if all(patient_id in verdicts for patient_id in batch):
            _close_open_batch(open_path, batch, open_batch_sizes)
        scored_this_run += sum(1 for patient_id in batch if patient_id in verdicts)
        score_elapsed += fetch_seconds + score_seconds + profile_seconds
        seconds_per_patient = score_elapsed / scored_this_run if scored_this_run else 0.0
        remaining = len(patient_ids) - scored_this_run
        timing_rows.append({
            "phase": "scan",
            "patient_id": batch[0] if len(batch) == 1 else "",
            "batch_index": batch_number,
            "batch_patients": len(batch),
            "claim_rows": "",
            "encounter_rows": "",
            "census_rows": "",
            "fetch_seconds": round(fetch_seconds / len(batch), 3),
            "score_seconds": round(score_seconds / len(batch), 3),
            "profile_seconds": round(profile_seconds / len(batch), 3),
        })
        _say({
            "phase": "scan",
            "batch": batch_number,
            "patients": len(batch),
            "fetch_seconds": round(fetch_seconds, 3),
            "score_seconds": round(score_seconds, 3),
            "seconds_per_patient": round(seconds_per_patient, 3),
            "remaining_patients": max(remaining, 0),
            "eta_hours": round(max(remaining, 0) * seconds_per_patient / 3600, 2),
            "suspicious_amyloidosis": counts["suspicious_amyloidosis"],
            "high_attr": counts["high_attr"],
            "highest_attr": counts["highest_attr"],
            "moderate_attr": counts["moderate_attr"],
            "high_al": counts["high_al"],
            "highest_al": counts["highest_al"],
            "moderate_al": counts["moderate_al"],
            "high_aa": counts["high_aa"],
            "highest_aa": counts["highest_aa"],
            "moderate_aa": counts["moderate_aa"],
            "confirmed": counts["confirmed"],
            "profiles_saved": written["attr"] + written["al"] + written["aa"] + written["confirmed"],
            "profiles_failed": written["failed"],
        })
        gc.collect()

    profiles_pending = len(_pending_profile_verdicts(verdicts, profiled_ids))
    confirmed_patients = sum(
        1 for verdict in verdicts.values()
        if str(verdict.get("confirmation_status") or "").upper() == "CONFIRMED"
    )
    profile_slice_seconds = round(time.perf_counter() - profile_started, 1)
    summary = _summary(
        phase="scan",
        namespace=source_config["namespace"],
        screening_cutoff=screening_cutoff,
        screening_codes=len(codes),
        screen_claim_rows=screen_count,
        screen_patients=patient_count,
        patients_scored=len(verdicts),
        verdict_rows=len(verdicts),
        confirmed_patients=confirmed_patients,
        profile_patients=len(profiled_ids),
        profiles_written=written,
        output_dir=output,
        elapsed_seconds=round(time.perf_counter() - started, 1),
        code_seconds=code_seconds,
        screen_seconds=screen_seconds,
        census_seconds=census_seconds,
        profile_slice_seconds=profile_slice_seconds,
        timing_rows=timing_rows,
        temporary_tables=[],
    )
    summary["counts"] = counts
    summary["counts_only"] = False
    summary["checkpoint"] = True
    summary["finished"] = patient_count == len(verdicts) and profiles_pending == 0
    summary["profiles_still_needed"] = profiles_pending
    summary["patients_scored_this_run"] = scored_this_run
    summary["profile_backfill_seconds"] = profile_backfill_seconds
    summary["stopped_after_pilot"] = False
    _say({"counts": counts, "profiles_written": written, "finished": summary["finished"]})
    summary_path = _unique_output_path(output / "checkpoints", "summary", ".json")
    zip_note = "folder"
    try:
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        if summary["finished"] and _directory_bytes(output) <= 64_000_000:
            zip_path = _zip_output(output)
            summary["download_zip"] = zip_path
            zip_note = zip_path
            _say({"download_this_file": zip_path})
        else:
            _say({
                "saved_folder": str(output),
                "reason": "profiles and checkpoints are in this folder; a single in-memory zip is skipped",
            })
    except Exception as exc:
        _say({"saved_files": "checkpoint_kept", "reason": _short_error(exc)})
    summary["download"] = zip_note
    _say(summary)
    if not summary["finished"]:
        print(
            "Scan paused with checkpoints on disk. Run this cell again to continue. "
            "Patients already scored are skipped, and missing profiles are written before new scoring."
        )
    return summary


def _score_and_checkpoint_batch(
    session: Any,
    *,
    source_config: Mapping[str, Any],
    configs: Mapping[str, Any],
    extraction: Any,
    census_table: str,
    screening_cutoff: str,
    output: Path,
    batch: Sequence[str],
    batch_number: int,
    verdicts: dict[str, dict[str, Any]],
    profiled_ids: set[str],
    profile_attempts: dict[str, int],
    chart_sources: Sequence[Mapping[str, Any]],
    counts: dict[str, int],
    written: dict[str, int],
    patients_to_score: int,
    scored_this_run: int,
    score_attempts: dict[str, int],
) -> tuple[float, float, float]:
    """Score one batch once, checkpoint verdicts, then write profiles from that pass."""
    _say({
        "phase": "scan",
        "batch": batch_number,
        "patients": len(batch),
        "status": "scoring",
        "scored_this_run": scored_this_run,
        "patients_to_score": patients_to_score,
    })
    claims: list[dict[str, Any]] | None = None
    encounters: list[dict[str, Any]] | None = None
    census: list[dict[str, Any]] | None = None
    result: Any = None
    fetch_started = time.perf_counter()
    try:
        claim_rows = _claim_row_total(session, source_config, batch)
        if claim_rows > MAX_CLAIM_ROWS and len(batch) > 1:
            raise RuntimeError(f"batch has {claim_rows} claim rows")
        if claim_rows > MAX_CLAIM_ROWS and _oversized_patient_already_failed(
            output, batch[0], score_attempts, f"{claim_rows} screening rows", "score_errors",
        ):
            _skip_oversized_score(output, batch[0], claim_rows, verdicts, counts, batch_number)
            return 0.0, 0.0, 0.0
        claims, encounters = _screen_batch(
            session,
            source_config,
            batch,
            per_patient_cap=MAX_CLAIM_ROWS if claim_rows > MAX_CLAIM_ROWS else None,
        )
        census = _fetch_where(
            session,
            census_table,
            _patient_column(source_config, "census"),
            batch,
        )
        fetch_seconds = time.perf_counter() - fetch_started
        score_started = time.perf_counter()
        slim_rows, result = _score_rows(
            claims,
            encounters,
            census,
            batch,
            configs=configs,
            source_config=source_config,
            screening_cutoff=screening_cutoff,
        )
        if claim_rows > MAX_CLAIM_ROWS:
            note = f"newest_{MAX_CLAIM_ROWS}_of_{claim_rows}_screening_rows"
            for row in slim_rows:
                row["reason"] = (str(row.get("reason") or "") + " " + note).strip()
        score_seconds = time.perf_counter() - score_started
        _write_verdict_batch(output, slim_rows)
        for row in slim_rows:
            patient_id = str(row.get("patient_id") or "")
            if not patient_id:
                continue
            verdicts[patient_id] = row
            _tally_verdict(counts, row)
        _write_running_counts(output, counts, scored_batches=batch_number)
        new_verdicts = {
            str(row.get("patient_id")): verdicts[str(row.get("patient_id"))]
            for row in slim_rows
            if row.get("patient_id")
        }
        profile_ids = {
            patient_id for patient_id, verdict in new_verdicts.items()
            if _verdict_needs_profile(verdict)
        }
        _release_score_traces(result)
        _keep_patient_traces(result, profile_ids)
        if profile_ids and claims is not None and encounters is not None and census is not None:
            claims = _rows_for_ids(claims, source_config, "claim", profile_ids)
            encounters = _rows_for_ids(encounters, source_config, "encounter", profile_ids)
            census = _rows_for_ids(census, source_config, "census", profile_ids)
        gc.collect()
        profile_seconds = _profiles_from_result(
            session,
            source_config=source_config,
            extraction=extraction,
            output=output,
            result=result,
            claims=claims,
            encounters=encounters,
            census=census,
            verdicts=new_verdicts,
            profiled_ids=profiled_ids,
            profile_attempts=profile_attempts,
            chart_sources=chart_sources,
            written=written,
        )
        return fetch_seconds, score_seconds, profile_seconds
    finally:
        del claims, encounters, census, result
        gc.collect()
        _release_query_memory(session)


def _score_rows(
    claims: Sequence[Mapping[str, Any]],
    encounters: Sequence[Mapping[str, Any]],
    census: Sequence[Mapping[str, Any]],
    batch: Sequence[str],
    *,
    configs: Mapping[str, Any],
    source_config: Mapping[str, Any],
    screening_cutoff: str,
) -> tuple[list[dict[str, Any]], Any]:
    result = run_attr_reference_pipeline(
        {
            "claim": claims,
            "encounter": encounters,
            "census": census,
            "lab": [],
            "surgical_history": [],
        },
        configs=configs,
        source_config=source_config,
        terminology_systems=("ICD10",),
        screening_cutoff=screening_cutoff,
        include_profiles=False,
        evaluation_mode="ICD_DATED_CLAIMS",
        profile_suspicion_levels=PROFILE_LEVELS,
        include_all_patient_verdicts=True,
        include_proprietary_trace=False,
        population_patient_ids=set(batch),
        candidate_patient_ids=set(batch),
    )
    confirmed = set(
        _object_ids(result.known_attr_patients) + _object_ids(result.known_al_patients)
    )
    by_id: dict[str, dict[str, Any]] = {}
    for verdict in result.patient_verdicts:
        row = {field: _cell(verdict.get(field)) for field in VERDICT_FIELDS}
        patient_id = str(row.get("patient_id") or "")
        if patient_id in confirmed:
            row["confirmation_status"] = "CONFIRMED"
        if patient_id:
            by_id[patient_id] = row
    missing = [patient_id for patient_id in batch if patient_id not in by_id]
    if missing:
        raise RuntimeError(f"no verdict for {missing[0]}")
    return [by_id[patient_id] for patient_id in batch], result


def _handle_score_failure(
    output: Path,
    patient_id: str,
    exc: BaseException,
    *,
    verdicts: dict[str, dict[str, Any]],
    attempts: dict[str, int],
    counts: dict[str, int],
) -> None:
    attempt = _record_attempt(output, "score_errors", patient_id, exc, attempts)
    if attempt < MAX_PATIENT_ATTEMPTS:
        _say({
            "score_will_retry_next_run": patient_id,
            "attempt": attempt,
            "error": _short_error(exc),
        })
        return
    row = _failed_verdict(patient_id, _short_error(exc))
    _write_verdict_batch(output, [row])
    verdicts[patient_id] = row
    _tally_verdict(counts, row)
    _write_running_counts(output, counts, scored_batches=0)
    _say({"score_failed_skipped": patient_id, "attempt": attempt, "error": row["reason"]})


def _failed_verdict(patient_id: str, reason: str) -> dict[str, Any]:
    row = {field: "" for field in VERDICT_FIELDS}
    row["patient_id"] = patient_id
    row["population_status"] = "SCORE_FAILED"
    row["confirmation_status"] = "NOT_CONFIRMED"
    row["reason"] = reason
    return row


def _census_slice_sql(source_config: Mapping[str, Any]) -> str:
    """Copy census rows for screened patients once, so later batches do not scan CENSUS."""
    namespace = str(source_config["namespace"])
    target = _qualified_temp(namespace, SCORE_CENSUS_TABLE)
    screen = _qualified_temp(namespace, SCREEN_TABLE)
    census = _physical(source_config, "census")
    screen_patient = _q(_patient_column(source_config, "claim"))
    census_patient = _q(_patient_column(source_config, "census"))
    return (
        f"CREATE TEMPORARY TABLE {target} AS "
        f"SELECT SRC.* FROM {census} SRC "
        f"JOIN (SELECT DISTINCT CAST({screen_patient} AS VARCHAR) AS PATIENT_ID FROM {screen}) IDS "
        f"ON CAST(SRC.{census_patient} AS VARCHAR) = IDS.PATIENT_ID"
    )


def _profile_lookup_sql(
    table_name: str,
    patient_column: str,
    patient_ids: Sequence[str],
) -> str:
    """Read every stored row for these patients. The TEMP_V5 tables are already built."""
    patient = _q(patient_column)
    return (
        f"SELECT SRC.* FROM {table_name} SRC "
        f"WHERE CAST(SRC.{patient} AS VARCHAR) IN ({_id_list(patient_ids)})"
    )


def _profile_pending(
    session: Any,
    *,
    source_config: Mapping[str, Any],
    configs: Mapping[str, Any],
    extraction: Any,
    census_table: str,
    screening_cutoff: str,
    output: Path,
    verdicts: Mapping[str, Mapping[str, Any]],
    profiled_ids: set[str],
    profile_attempts: dict[str, int],
    chart_sources: Sequence[Mapping[str, Any]],
    written: dict[str, int],
    counts: Mapping[str, int],
    batch_size: int,
) -> None:
    """Rebuild profiles for patients scored earlier. One engine pass per batch."""
    pending = _pending_profile_verdicts(verdicts, profiled_ids)
    if not pending:
        return
    _say({"profile_backfill_patients": len(pending), "batch_size": batch_size})
    verdict_by_id = {str(row.get("patient_id")): row for row in pending}
    open_batch_sizes = _unfinished_batch_sizes(output, set(profiled_ids), "profile_open")
    queue: list[list[str]] = [
        list(chunk)
        for chunk in _chunks([str(row.get("patient_id") or "") for row in pending], batch_size)
    ]
    while queue:
        patient_ids = [patient_id for patient_id in queue.pop(0) if patient_id and patient_id not in profiled_ids]
        if not patient_ids:
            continue
        patient_ids, remainder, skip_patient = _next_batch_after_memory_stop(patient_ids, open_batch_sizes)
        if remainder:
            queue.insert(0, remainder)
        if skip_patient:
            _mark_profile_failed(
                output,
                patient_ids[0],
                "notebook stopped while writing this profile",
                profiled_ids,
                written,
                verdict_by_id,
            )
            continue
        open_path = _note_open_batch(output, patient_ids, open_batch_sizes, "profile_open")
        claims = encounters = census = result = None
        try:
            claim_rows = _claim_row_total(session, source_config, patient_ids)
            if claim_rows > MAX_CLAIM_ROWS and len(patient_ids) > 1:
                raise RuntimeError(f"profile batch has {claim_rows} claim rows")
            if claim_rows > MAX_CLAIM_ROWS and _oversized_patient_already_failed(
                output, patient_ids[0], profile_attempts, f"{claim_rows} screening rows", "profile_errors",
            ):
                _mark_profile_failed(
                    output,
                    patient_ids[0],
                    f"{claim_rows} screening rows is too large for the notebook",
                    profiled_ids,
                    written,
                    verdict_by_id,
                )
                continue
            claims, encounters = _screen_batch(
                session,
                source_config,
                patient_ids,
                per_patient_cap=MAX_CLAIM_ROWS if claim_rows > MAX_CLAIM_ROWS else None,
            )
            census = _fetch_where(
                session,
                census_table,
                _patient_column(source_config, "census"),
                patient_ids,
            )
            _slim_rows, result = _score_rows(
                claims,
                encounters,
                census,
                patient_ids,
                configs=configs,
                source_config=source_config,
                screening_cutoff=screening_cutoff,
            )
            _release_score_traces(result)
            gc.collect()
            _profiles_from_result(
                session,
                source_config=source_config,
                extraction=extraction,
                output=output,
                result=result,
                claims=claims,
                encounters=encounters,
                census=census,
                verdicts={patient_id: verdict_by_id[patient_id] for patient_id in patient_ids},
                profiled_ids=profiled_ids,
                profile_attempts=profile_attempts,
                chart_sources=chart_sources,
                written=written,
            )
            _say({
                "profile_backfill_batch": len(patient_ids),
                "profiles_saved": written["attr"] + written["al"] + written["aa"] + written["confirmed"],
                "highest_attr": counts["highest_attr"],
            })
            if all(patient_id in profiled_ids for patient_id in patient_ids):
                _close_open_batch(open_path, patient_ids, open_batch_sizes)
        except Exception as exc:
            if len(patient_ids) > 1:
                midpoint = max(len(patient_ids) // 2, 1)
                queue.insert(0, patient_ids[midpoint:])
                queue.insert(0, patient_ids[:midpoint])
                _say({"profile_batch_failed": _short_error(exc), "splitting": len(patient_ids)})
            else:
                _record_profile_failures(
                    output,
                    patient_ids,
                    exc,
                    profile_attempts,
                    profiled_ids,
                    written,
                    verdict_by_id,
                )
        finally:
            del claims, encounters, census, result
            gc.collect()
            _release_query_memory(session)


def _profiles_from_result(
    session: Any,
    *,
    source_config: Mapping[str, Any],
    extraction: Any,
    output: Path,
    result: Any,
    claims: Sequence[Mapping[str, Any]],
    encounters: Sequence[Mapping[str, Any]],
    census: Sequence[Mapping[str, Any]],
    verdicts: Mapping[str, Mapping[str, Any]],
    profiled_ids: set[str],
    profile_attempts: dict[str, int],
    chart_sources: Sequence[Mapping[str, Any]],
    written: dict[str, int],
) -> float:
    """Write profiles from a finished scoring pass. The engine is not run again."""
    pending = _pending_profile_verdicts(verdicts, profiled_ids)
    if not pending:
        return 0.0
    started = time.perf_counter()
    for chunk in _chunks([str(row.get("patient_id") or "") for row in pending], PROFILE_CHART_BATCH):
        patient_ids = [patient_id for patient_id in chunk if patient_id]
        if not patient_ids:
            continue
        group = {patient_id: verdicts[patient_id] for patient_id in patient_ids}
        try:
            chart = _chart_for_profiles(
                session,
                source_config,
                patient_ids,
                claims,
                encounters,
                census,
                chart_sources,
            )
            _emit_profiles(
                output,
                source_config,
                extraction,
                result,
                chart,
                group,
                profiled_ids,
                profile_attempts,
                written,
            )
        except Exception as exc:
            _record_profile_failures(
                output,
                patient_ids,
                exc,
                profile_attempts,
                profiled_ids,
                written,
                group,
            )
            _say({
                "profile_chart_failed": _short_error(exc),
                "patients": len(patient_ids),
                "status": "verdicts kept",
            })
    elapsed = time.perf_counter() - started
    _say({
        "profile_patients_this_batch": len(pending),
        "profile_seconds": round(elapsed, 3),
    })
    return elapsed


def _chart_for_profiles(
    session: Any,
    source_config: Mapping[str, Any],
    patient_ids: Sequence[str],
    claims: Sequence[Mapping[str, Any]],
    encounters: Sequence[Mapping[str, Any]],
    census: Sequence[Mapping[str, Any]],
    sources: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Claims already scored, plus one read of each existing TEMP_V5 table for this group."""
    wanted = set(patient_ids)
    rows: dict[str, Any] = {
        "claim": _rows_for_ids(claims, source_config, "claim", wanted),
        "encounter": _rows_for_ids(encounters, source_config, "encounter", wanted),
        "census": _rows_for_ids(census, source_config, "census", wanted),
        "lab": [],
        "surgical_history": [],
    }
    truncated: dict[str, int] = {}
    for source in sources:
        key = str(source["key"])
        if key in {"claim", "census"}:
            continue
        fetched = _fetch_profile_rows(
            session,
            str(source["table"]),
            str(source["patient_column"]),
            patient_ids,
        )
        if key == "encounter":
            rows["encounter"] = _merge_encounters(fetched, rows["encounter"], source_config)
        else:
            rows[key] = fetched
    rows["_truncated_tables"] = truncated
    return rows


def _emit_profiles(
    output: Path,
    source_config: Mapping[str, Any],
    extraction: Any,
    result: Any,
    chart: Mapping[str, Any],
    verdicts: Mapping[str, Mapping[str, Any]],
    profiled_ids: set[str],
    profile_attempts: dict[str, int],
    written: dict[str, int],
) -> None:
    truncated = dict(chart.get("_truncated_tables") or {})
    ehr = {key: value for key, value in chart.items() if not str(key).startswith("_")}
    demographics = _demographics_by_patient(ehr.get("census", ()), source_config)
    wanted = {str(patient_id) for patient_id in verdicts}
    shared = dict(
        config=extraction,
        source_events=_traces_for(result.source_events, wanted),
        evidence_events=_traces_for(result.evidence_events, wanted),
        signal_hits=_traces_for(result.signal_hits, wanted),
        bucket_state=_traces_for(result.bucket_state, wanted),
        combination_hits=_traces_for(result.combination_hits, wanted),
        guardrail_hits=_traces_for(result.guardrail_hits, wanted),
        demographics=demographics,
        run_id=result.run_id,
        ehr_records_by_table=ehr,
        source_config=source_config,
        include_proprietary_trace=False,
    )
    attr_by = {
        str(profile.get("patient_id")): profile
        for profile in _stamp_profiles(build_attr_profiles(
            _traces_for(result.router_output, wanted),
            profile_suspicion_levels=PROFILE_LEVELS,
            **shared,
        ), truncated)
    }
    al_by = {
        str(profile.get("patient_id")): profile
        for profile in _stamp_profiles(build_al_detected_profiles(
            _traces_for(result.router_output, wanted),
            profile_suspicion_levels=PROFILE_LEVELS,
            **shared,
        ), truncated)
    }
    aa_by = {
        str(profile.get("patient_id")): profile
        for profile in _stamp_profiles(build_aa_profiles(
            _traces_for(result.router_output, wanted),
            profile_suspicion_levels=PROFILE_LEVELS,
            **shared,
        ), truncated)
    }
    confirmed_by = {
        str(profile.get("patient_id")): profile
        for profile in _stamp_profiles(
            _confirmed_patient_profiles(ehr, source_config),
            truncated,
        )
    }
    saved_attr: list[Mapping[str, Any]] = []
    saved_al: list[Mapping[str, Any]] = []
    saved_aa: list[Mapping[str, Any]] = []
    saved_confirmed: list[Mapping[str, Any]] = []
    checkpoint_rows: list[dict[str, Any]] = []
    failed: list[str] = []
    for patient_id, verdict in verdicts.items():
        attr_level = str(verdict.get("attr_suspicion_level") or "").upper()
        al_level = str(verdict.get("al_suspicion_level") or "").upper()
        aa_level = str(verdict.get("aa_suspicion_level") or "").upper()
        confirmed = str(verdict.get("confirmation_status") or "").upper() == "CONFIRMED"
        if not _verdict_needs_profile(verdict):
            continue
        expect_attr = attr_level in PROFILE_LEVELS
        expect_al = al_level in PROFILE_LEVELS
        expect_aa = aa_level in PROFILE_LEVELS
        attr_profile = attr_by.get(patient_id) if expect_attr else None
        al_profile = al_by.get(patient_id) if expect_al else None
        aa_profile = aa_by.get(patient_id) if expect_aa else None
        confirmed_profile = confirmed_by.get(patient_id) if confirmed else None
        if (
            (expect_attr and attr_profile is None)
            or (expect_al and al_profile is None)
            or (expect_aa and aa_profile is None)
            or (confirmed and confirmed_profile is None)
        ):
            failed.append(patient_id)
            continue
        if attr_profile is not None:
            saved_attr.append(attr_profile)
        if al_profile is not None:
            saved_al.append(al_profile)
        if aa_profile is not None:
            saved_aa.append(aa_profile)
        if confirmed_profile is not None:
            saved_confirmed.append(confirmed_profile)
        checkpoint_rows.append({
            "patient_id": patient_id,
            "status": "saved",
            "attr_suspicion_level": attr_level,
            "al_suspicion_level": al_level,
            "aa_suspicion_level": aa_level,
            "confirmation_status": verdict.get("confirmation_status") or "",
            "attr_profiles": 1 if attr_profile is not None else 0,
            "al_profiles": 1 if al_profile is not None else 0,
            "aa_profiles": 1 if aa_profile is not None else 0,
            "confirmed_profiles": 1 if confirmed_profile is not None else 0,
            "truncated_tables": ",".join(sorted(truncated)),
        })
    _append_detected(output, "detected", "attr_flagged_patient_profiles", saved_attr)
    _append_detected(output / "al_detected", "detected", "al_detected_patient_profiles", saved_al)
    _append_detected(output / "aa_detected", "detected", "aa_detected_patient_profiles", saved_aa)
    _append_jsonl(
        output / "confirmed" / "confirmed_amyloidosis_patient_profiles.jsonl",
        saved_confirmed,
    )
    if checkpoint_rows:
        _write_csv_once(
            _unique_output_path(output / "checkpoints", "profiled", ".csv"),
            checkpoint_rows,
            [
                "patient_id",
                "status",
                "attr_suspicion_level",
                "al_suspicion_level",
                "aa_suspicion_level",
                "confirmation_status",
                "attr_profiles",
                "al_profiles",
                "aa_profiles",
                "confirmed_profiles",
                "truncated_tables",
            ],
        )
        for row in checkpoint_rows:
            profiled_ids.add(str(row["patient_id"]))
    written["attr"] += len(saved_attr)
    written["al"] += len(saved_al)
    written["aa"] += len(saved_aa)
    written["confirmed"] += len(saved_confirmed)
    if failed:
        _record_profile_failures(
            output,
            failed,
            RuntimeError("profile was not built from the scoring pass"),
            profile_attempts,
            profiled_ids,
            written,
            verdicts,
        )


def _record_profile_failures(
    output: Path,
    patient_ids: Sequence[str],
    exc: BaseException,
    attempts: dict[str, int],
    profiled_ids: set[str],
    written: dict[str, int],
    verdicts: Mapping[str, Mapping[str, Any]],
) -> None:
    if not patient_ids:
        return
    error_rows = []
    failed_rows = []
    for patient_id in patient_ids:
        attempts[patient_id] = attempts.get(patient_id, 0) + 1
        error_rows.append({"patient_id": patient_id, "error": _short_error(exc)})
        if attempts[patient_id] < MAX_PATIENT_ATTEMPTS or patient_id in profiled_ids:
            continue
        verdict = verdicts.get(patient_id, {})
        failed_rows.append({
            "patient_id": patient_id,
            "status": "failed",
            "attr_suspicion_level": verdict.get("attr_suspicion_level") or "",
            "al_suspicion_level": verdict.get("al_suspicion_level") or "",
            "aa_suspicion_level": verdict.get("aa_suspicion_level") or "",
            "confirmation_status": verdict.get("confirmation_status") or "",
            "attr_profiles": 0,
            "al_profiles": 0,
            "aa_profiles": 0,
            "confirmed_profiles": 0,
            "truncated_tables": _short_error(exc),
        })
        profiled_ids.add(patient_id)
        written["failed"] += 1
    _write_csv_once(
        _unique_output_path(output / "checkpoints", "profile_errors", ".csv"),
        error_rows,
        ["patient_id", "error"],
    )
    if failed_rows:
        _write_csv_once(
            _unique_output_path(output / "checkpoints", "profiled", ".csv"),
            failed_rows,
            [
                "patient_id",
                "status",
                "attr_suspicion_level",
                "al_suspicion_level",
                "aa_suspicion_level",
                "confirmation_status",
                "attr_profiles",
                "al_profiles",
                "aa_profiles",
                "confirmed_profiles",
                "truncated_tables",
            ],
        )


def _rows_for_ids(
    rows: Sequence[Mapping[str, Any]],
    source_config: Mapping[str, Any],
    table_key: str,
    patient_ids: set[str],
) -> list[dict[str, Any]]:
    column = _patient_column(source_config, table_key)
    return [
        row for row in rows
        if str(_case_get(row, column) or "") in patient_ids
    ]


def _fetch_profile_rows(
    session: Any,
    table_name: str,
    patient_column: str,
    patient_ids: Sequence[str],
) -> list[dict[str, Any]]:
    if not patient_ids:
        return []
    return _fetch_sql(session, _profile_lookup_sql(table_name, patient_column, patient_ids))


def _demographics_by_patient(
    rows: Sequence[Mapping[str, Any]],
    source_config: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not rows or not source_config:
        return {}
    columns = source_config["tables"]["census"]["columns"]
    mapped: dict[str, dict[str, Any]] = {}
    for row in rows:
        patient_id = str(_case_get(row, columns["patient_id"]) or "")
        if not patient_id:
            continue
        mapped[patient_id] = {
            logical: _case_get(row, physical)
            for logical, physical in columns.items()
            if logical != "patient_id"
        }
    return mapped


def _chart_sources(session: Any, source_config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Read the existing TEMP_V5 profile tables. Claims stay on the screened ICD set.

    These tables are created outside this run. A missing table is skipped.
    The original LABS, ENCOUNTERS, SURGICAL_HISTORY, and MEDICATIONS tables are not queried.
    """
    namespace = str(source_config.get("namespace") or "")
    sources: list[dict[str, Any]] = []
    for key, table in source_config.get("tables", {}).items():
        ready_name = PROFILE_SOURCE_TABLES.get(key)
        if ready_name is None or not is_table_profile_enabled(table):
            continue
        physical = _qualified_temp(namespace, ready_name)
        if not _table_readable(session, physical):
            _say({"profile_table_missing": ready_name})
            continue
        sources.append({
            "key": key,
            "table": physical,
            "patient_column": _patient_column(source_config, key),
        })
    medication_name = PROFILE_SOURCE_TABLES["medication"]
    medication = _qualified_temp(namespace, medication_name)
    if _table_readable(session, medication):
        sources.append({
            "key": "medication",
            "table": medication,
            "patient_column": "PATIENTID",
        })
    else:
        _say({"profile_table_missing": medication_name})
    return sources


def _profile_order_column(source_config: Mapping[str, Any], table_key: str) -> str | None:
    logical = _PROFILE_ORDER_FIELDS.get(table_key)
    if not logical:
        return None
    return source_config["tables"][table_key]["columns"].get(logical)


def _merge_encounters(
    primary: Sequence[Mapping[str, Any]],
    extra: Sequence[Mapping[str, Any]],
    source_config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    columns = source_config["tables"]["encounter"]["columns"]
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in [*primary, *extra]:
        key = (
            str(_case_get(row, columns["patient_id"]) or ""),
            str(_case_get(row, columns["encounter_id"]) or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(row))
    return merged


def _stamp_profiles(
    profiles: Sequence[Mapping[str, Any]],
    truncated: Mapping[str, int],
) -> list[dict[str, Any]]:
    stamped: list[dict[str, Any]] = []
    for profile in profiles:
        item = dict(profile)
        item["chart_scope"] = {
            "claims": "Screened ICD-10 claim rows from the scoring pass.",
            "labs": "TEMP_V5_LAB",
            "encounters": "TEMP_V5_ENCOUNTER",
            "surgical_history": "TEMP_V5_SURGICAL",
            "medications": "TEMP_V5_MEDICATION",
            "row_cap_per_table": None,
            "truncated_tables": dict(truncated),
        }
        stamped.append(item)
    return stamped


def _read_profile_outcomes(output_dir: Path) -> tuple[set[str], set[str]]:
    done: set[str] = set()
    failed: set[str] = set()
    checkpoint_dir = output_dir / "checkpoints"
    if checkpoint_dir.exists():
        for path in sorted(checkpoint_dir.glob("profiled_*.csv")):
            for row in _read_csv_dicts(path):
                patient_id = str(row.get("patient_id") or "")
                if not patient_id:
                    continue
                done.add(patient_id)
                if str(row.get("status") or "").lower() == "failed":
                    failed.add(patient_id)
                else:
                    failed.discard(patient_id)
    return done, failed


def _read_attempt_counts(output_dir: Path, stem: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    checkpoint_dir = output_dir / "checkpoints"
    if not checkpoint_dir.exists():
        return counts
    for path in sorted(checkpoint_dir.glob(f"{stem}_*.csv")):
        for row in _read_csv_dicts(path):
            patient_id = str(row.get("patient_id") or "")
            if patient_id:
                counts[patient_id] = counts.get(patient_id, 0) + 1
    return counts


def _record_attempt(
    output_dir: Path,
    stem: str,
    patient_id: str,
    exc: BaseException,
    attempts: dict[str, int],
) -> int:
    attempts[patient_id] = attempts.get(patient_id, 0) + 1
    _write_csv_once(
        _unique_output_path(output_dir / "checkpoints", stem, ".csv"),
        [{"patient_id": patient_id, "error": _short_error(exc)}],
        ["patient_id", "error"],
    )
    return attempts[patient_id]


def _short_error(exc: BaseException) -> str:
    text = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    return " ".join(text.split())[:400]


def _unique_output_path(directory: Path, stem: str, suffix: str) -> Path:
    """One new file per write. The notebook filesystem cannot append or seek."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.time_ns()
    for _ in range(1000):
        path = directory / f"{stem}_{stamp}{suffix}"
        if not path.exists():
            return path
        stamp += 1
    raise RuntimeError(f"could not allocate a new file name in {directory}")


def _write_csv_once(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(fieldnames), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _directory_bytes(folder: Path) -> int:
    total = 0
    if not folder.exists():
        return 0
    for path in folder.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def _confirmed_patient_profiles(
    rows_by_table: Mapping[str, Sequence[Mapping[str, Any]]],
    source_config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Write the v4 confirmation record: one profile per E85 patient, including AA.

    ATTR, AL, AA, and the other configured E85 codes stay in this one list.
    They are not split into phenotype folders. Suspicion exports are separate.
    """
    found = extract_confirmed_icd10(rows_by_table, source_config=source_config)
    if not found:
        return []
    terms = _confirmation_terms()
    profiles: list[dict[str, Any]] = []
    for item in found:
        matched = [terms[code.replace(".", "")] for code in item.matched_icd10_codes if code.replace(".", "") in terms]
        summary = {
            "RUN_ID": item.run_id,
            "PATIENT_ID": item.patient_id,
            "STATUS": "CONFIRMED",
            "MATCHED_ICD10_CODES": [term["code"] for term in matched],
            "AMYLOIDOSIS_TYPES": sorted({term["type"] for term in matched}),
            "AMYLOIDOSIS_SUBTYPES": [term["subtype"] for term in matched],
            "CONFIRMATION_SCOPES": sorted({term["scope"] for term in matched}),
            "RISK_LABEL": "CONFIRMED",
            "PRIORITY_LABEL": "CONFIRMED",
            "CONFIRMATION_KIND": "EXACT_CONFIGURED_ICD10",
            "EXCLUDED_FROM_SUSPICION": True,
        }
        profiles.append(build_patient_profile(
            item.patient_id,
            confirmation_summary=summary,
            confirmation_evidence=_confirmation_evidence(rows_by_table, source_config, item.patient_id, terms),
            ehr_records_by_table=rows_by_table,
            source_config=source_config,
            demographics=_census_demographics(rows_by_table, source_config, item.patient_id),
            confirmation_source_table="CLAIMS",
            include_proprietary_trace=False,
            run_id=item.run_id,
        ))
    return profiles


def _confirmation_terms() -> dict[str, dict[str, str]]:
    payload = json.loads(DEFAULT_CONFIRMED_CONFIG.read_text(encoding="utf-8"))
    terms: dict[str, dict[str, str]] = {}
    for term in payload["routes"]["ALL_AMYLOIDOSIS"]["terminology"]:
        if normalize_system(term.get("terminology_system")) != "ICD10":
            continue
        code = str(term.get("value") or "").strip().upper()
        if not code:
            continue
        terms[code.replace(".", "")] = {
            "code": code,
            "type": str(term.get("amyloidosis_type") or "AMYLOIDOSIS"),
            "subtype": str(term.get("subtype_label") or ""),
            "scope": str(term.get("confirmation_scope") or "KNOWN_AMYLOIDOSIS"),
            "risk": str(term.get("risk_label") or "CONFIRMED"),
            "priority": str(term.get("priority_label") or "CONFIRMED"),
        }
    return terms


def _confirmation_evidence(
    rows_by_table: Mapping[str, Sequence[Mapping[str, Any]]],
    source_config: Mapping[str, Any],
    patient_id: str,
    terms: Mapping[str, Mapping[str, str]],
) -> list[dict[str, Any]]:
    columns = source_config["tables"]["claim"]["columns"]
    evidence: list[dict[str, Any]] = []
    for row in rows_by_table.get("claim", ()):
        if str(_case_get(row, columns["patient_id"]) or "") != str(patient_id):
            continue
        if normalize_system(_case_get(row, columns["diagnosis_type"])) != "ICD10":
            continue
        normalized = str(_case_get(row, columns["diagnosis_code"]) or "").strip().upper().replace(".", "")
        term = terms.get(normalized)
        if term is None:
            continue
        evidence.append({
            "SOURCE_CLAIM": dict(row),
            "MATCHED_CODE": term["code"],
            "AMYLOIDOSIS_TYPE": term["type"],
            "AMYLOIDOSIS_SUBTYPE": term["subtype"],
            "CONFIRMATION_SCOPE": term["scope"],
            "RISK_LABEL": term["risk"],
            "PRIORITY_LABEL": term["priority"],
            "DIAGNOSIS_SYSTEM": "ICD10",
        })
    return evidence


def _census_demographics(
    rows_by_table: Mapping[str, Sequence[Mapping[str, Any]]],
    source_config: Mapping[str, Any],
    patient_id: str,
) -> dict[str, Any]:
    columns = source_config["tables"]["census"]["columns"]
    for row in rows_by_table.get("census", ()):
        if str(_case_get(row, columns["patient_id"]) or "") != str(patient_id):
            continue
        return {
            logical: _case_get(row, physical)
            for logical, physical in columns.items()
            if logical != "patient_id"
        }
    return {}


def _screen_claim_sql(source_config: Mapping[str, Any], include_prefix: bool) -> str:
    claims = _physical(source_config, "claim")
    encounters = _physical(source_config, "encounter")
    claim_columns = source_config["tables"]["claim"]["columns"]
    encounter_columns = source_config["tables"]["encounter"]["columns"]
    patient = _q(claim_columns["patient_id"])
    encounter = _q(claim_columns["encounter_id"])
    code = _q(claim_columns["diagnosis_code"])
    diagnosis_type = _q(claim_columns["diagnosis_type"])
    projected = ", ".join(
        f"SRC.{_q(physical)} AS {_q(physical)}"
        for physical in dict.fromkeys(claim_columns.values())
    )
    encounter_patient = _q(encounter_columns["patient_id"])
    visit = _q(encounter_columns["encounter_id"])
    visit_date = _q(encounter_columns["encounter_date"])
    code_table = _qualified_temp(str(source_config["namespace"]), CODE_TABLE)
    screen_table = _qualified_temp(str(source_config["namespace"]), SCREEN_TABLE)
    normalized = f"UPPER(REPLACE(TRIM(SRC.{code}), '.', ''))"
    icd9 = _icd9_type_sql(f"SRC.{diagnosis_type}")
    date_join = (
        f"LEFT JOIN ENCOUNTER_DATE D "
        f"ON CAST(SRC.{patient} AS VARCHAR) = CAST(D.PATIENT_ID AS VARCHAR) "
        f"AND CAST(SRC.{encounter} AS VARCHAR) = CAST(D.VISIT_ID AS VARCHAR)"
    )
    exact = (
        f"SELECT {projected}, D.VISIT_DATE AS ENCOUNTER_VISIT_DATE "
        f"FROM {claims} SRC "
        f"JOIN {code_table} K ON K.MATCH_MODE = 'EXACT' AND {normalized} = K.NORMALIZED_CODE "
        f"{date_join} "
        f"WHERE SRC.{code} IS NOT NULL AND NOT ({icd9})"
    )
    branches = [exact]
    if include_prefix:
        branches.append(
            f"SELECT {projected}, D.VISIT_DATE AS ENCOUNTER_VISIT_DATE "
            f"FROM {claims} SRC "
            f"JOIN {code_table} K ON K.MATCH_MODE = 'PREFIX' "
            f"AND STARTSWITH({normalized}, K.NORMALIZED_CODE) "
            f"AND LENGTH({normalized}) > LENGTH(K.NORMALIZED_CODE) "
            f"{date_join} "
            f"WHERE SRC.{code} IS NOT NULL AND NOT ({icd9})"
        )
    union = "\nUNION ALL\n".join(branches)
    return (
        f"CREATE TEMPORARY TABLE {screen_table} AS "
        "WITH ENCOUNTER_DATE AS ("
        f"SELECT {encounter_patient} AS PATIENT_ID, {visit} AS VISIT_ID, "
        f"MIN({visit_date}) AS VISIT_DATE "
        f"FROM {encounters} "
        f"WHERE {encounter_patient} IS NOT NULL AND {visit} IS NOT NULL AND {visit_date} IS NOT NULL "
        f"GROUP BY {encounter_patient}, {visit} "
        f"HAVING COUNT(DISTINCT {visit_date}) = 1"
        ") "
        f"SELECT DISTINCT * FROM ({union}) SCREENED"
    )


def _profile_slice_sql(
    target: str,
    physical_table: str,
    patient_column: str,
    patient_table: str,
) -> str:
    patient = _q(patient_column)
    return (
        f"CREATE TEMPORARY TABLE {target} AS "
        f"SELECT SRC.* FROM {physical_table} SRC "
        f"JOIN {patient_table} B "
        f"ON CAST(SRC.{patient} AS VARCHAR) = B.PATIENT_ID"
    )


def _fetch_where(
    session: Any,
    table_name: str,
    patient_column: str,
    patient_ids: Sequence[str],
) -> list[dict[str, Any]]:
    if not patient_ids:
        return []
    patient = _q(patient_column)
    return _fetch_sql(
        session,
        f"SELECT SRC.* FROM {table_name} SRC "
        f"WHERE CAST(SRC.{patient} AS VARCHAR) IN ({_id_list(patient_ids)})",
    )


def _icd9_type_sql(column_sql: str) -> str:
    normalized = (
        "REGEXP_REPLACE(REPLACE(REPLACE(REPLACE(UPPER(TRIM(COALESCE("
        f"{column_sql}, ''))), '-', ' '), '/', ' '), '_', ' '), '[[:space:]]+', ' ')"
    )
    return f"{normalized} IN ('ICD9', 'ICD 9', 'ICD 9 CM', 'ICD9 CM', 'ICD9CM')"


def _claim_count_sql(source_config: Mapping[str, Any], patient_ids: Sequence[str]) -> str:
    patient = _q(_patient_column(source_config, "claim"))
    table = _qualified_temp(str(source_config["namespace"]), SCREEN_TABLE)
    return (
        f"SELECT COUNT(*) FROM {table} "
        f"WHERE CAST({patient} AS VARCHAR) IN ({_id_list(patient_ids)})"
    )


def _claim_row_total(session: Any, source_config: Mapping[str, Any], patient_ids: Sequence[str]) -> int:
    """Count screening rows in Snowflake before the notebook downloads them."""
    if not patient_ids:
        return 0
    return _scalar(session, _claim_count_sql(source_config, patient_ids))


def _screen_window_sql(
    source_config: Mapping[str, Any],
    patient_ids: Sequence[str],
    cap: int,
) -> str:
    """Newest screening rows only, at most ``cap`` per patient."""
    patient = _q(_patient_column(source_config, "claim"))
    table = _qualified_temp(str(source_config["namespace"]), SCREEN_TABLE)
    return (
        "SELECT * FROM ("
        f"SELECT SRC.*, ROW_NUMBER() OVER (PARTITION BY CAST(SRC.{patient} AS VARCHAR) "
        f"ORDER BY SRC.ENCOUNTER_VISIT_DATE DESC NULLS LAST) AS AMY_V5_RN "
        f"FROM {table} SRC WHERE CAST(SRC.{patient} AS VARCHAR) IN ({_id_list(patient_ids)})"
        f") RANKED WHERE AMY_V5_RN <= {int(cap)}"
    )


def _next_batch_after_memory_stop(
    batch: Sequence[str],
    open_sizes: Mapping[str, int],
) -> tuple[list[str], list[str], bool]:
    """Shrink a batch that already killed the notebook.

    The third value is true when this one patient already stopped a previous
    start, so the caller saves a failed row and does not load that patient again.
    """
    patients = [patient_id for patient_id in batch if patient_id]
    if not patients:
        return [], [], False
    recorded = open_sizes.get(patients[0])
    if recorded is None:
        return patients, [], False
    if recorded <= 1:
        return patients[:1], patients[1:], True
    if len(patients) >= recorded:
        width = max(int(recorded) // 2, 1)
        return patients[:width], patients[width:], False
    return patients, [], False


def _unfinished_batch_sizes(output: Path, done: set[str], stem: str) -> dict[str, int]:
    """Smallest batch size already attempted for patients who are still unfinished."""
    sizes: dict[str, int] = {}
    checkpoint_dir = output / "checkpoints"
    if not checkpoint_dir.exists():
        return sizes
    for path in sorted(checkpoint_dir.glob(f"{stem}_*.csv")):
        rows = _read_csv_dicts(path)
        if not rows:
            continue
        width = int(rows[0].get("batch_size") or len(rows))
        for row in rows:
            patient_id = str(row.get("patient_id") or "")
            if not patient_id or patient_id in done:
                continue
            previous = sizes.get(patient_id)
            sizes[patient_id] = width if previous is None else min(previous, width)
    return sizes


def _note_open_batch(
    output: Path,
    patient_ids: Sequence[str],
    sizes: dict[str, int],
    stem: str,
) -> Path:
    """Write the batch before the heavy work. A kernel kill leaves this file."""
    width = len(patient_ids)
    path = _unique_output_path(output / "checkpoints", stem, ".csv")
    _write_csv_once(
        path,
        [{"patient_id": patient_id, "batch_size": width} for patient_id in patient_ids],
        ["patient_id", "batch_size"],
    )
    for patient_id in patient_ids:
        previous = sizes.get(patient_id)
        sizes[patient_id] = width if previous is None else min(previous, width)
    return path


def _close_open_batch(path: Path, patient_ids: Sequence[str], sizes: dict[str, int]) -> None:
    for patient_id in patient_ids:
        sizes.pop(patient_id, None)
    try:
        path.unlink()
    except OSError:
        return


def _oversized_patient_already_failed(
    output: Path,
    patient_id: str,
    attempts: dict[str, int],
    reason: str,
    stem: str,
) -> bool:
    """Write the attempt before the download. A kernel kill still counts.

    The second start skips the download and saves a failed row, so one huge
    chart cannot stop the rest of the scan.
    """
    if attempts.get(patient_id, 0) < 1:
        _record_attempt(output, stem, patient_id, RuntimeError(reason), attempts)
        return False
    _record_attempt(output, stem, patient_id, RuntimeError(reason), attempts)
    return True


def _skip_oversized_score(
    output: Path,
    patient_id: str,
    claim_rows: int,
    verdicts: dict[str, dict[str, Any]],
    counts: dict[str, int],
    batch_number: int,
    reason: str | None = None,
) -> None:
    text = reason or f"{claim_rows} screening rows is too large for the notebook"
    row = _failed_verdict(patient_id, text)
    _write_verdict_batch(output, [row])
    verdicts[patient_id] = row
    _tally_verdict(counts, row)
    _write_running_counts(output, counts, scored_batches=batch_number)
    _say({"score_skipped": patient_id, "reason": text, "checkpoint": "kept"})


def _mark_profile_failed(
    output: Path,
    patient_id: str,
    reason: str,
    profiled_ids: set[str],
    written: dict[str, int],
    verdicts: Mapping[str, Mapping[str, Any]],
) -> None:
    if patient_id in profiled_ids:
        return
    verdict = verdicts.get(patient_id, {})
    _write_csv_once(
        _unique_output_path(output / "checkpoints", "profiled", ".csv"),
        [{
            "patient_id": patient_id,
            "status": "failed",
            "attr_suspicion_level": verdict.get("attr_suspicion_level") or "",
            "al_suspicion_level": verdict.get("al_suspicion_level") or "",
            "aa_suspicion_level": verdict.get("aa_suspicion_level") or "",
            "confirmation_status": verdict.get("confirmation_status") or "",
            "attr_profiles": 0,
            "al_profiles": 0,
            "aa_profiles": 0,
            "confirmed_profiles": 0,
            "truncated_tables": reason[:400],
        }],
        [
            "patient_id",
            "status",
            "attr_suspicion_level",
            "al_suspicion_level",
            "aa_suspicion_level",
            "confirmation_status",
            "attr_profiles",
            "al_profiles",
            "aa_profiles",
            "confirmed_profiles",
            "truncated_tables",
        ],
    )
    profiled_ids.add(patient_id)
    written["failed"] += 1
    _say({"profile_skipped_oversized": patient_id, "checkpoint": "kept"})


def _trace_patient_id(item: Any) -> str:
    if isinstance(item, Mapping):
        return str(item.get("patient_id") or "")
    return str(getattr(item, "patient_id", "") or "")


def _traces_for(items: Sequence[Any], patient_ids: set[str]) -> list[Any]:
    if not patient_ids:
        return []
    return [item for item in items if _trace_patient_id(item) in patient_ids]


def _keep_patient_traces(result: Any, patient_ids: set[str]) -> None:
    if result is None:
        return
    for name in (
        "source_events",
        "evidence_events",
        "signal_hits",
        "bucket_state",
        "combination_hits",
        "guardrail_hits",
        "router_output",
    ):
        value = getattr(result, name, None)
        if isinstance(value, list):
            setattr(result, name, _traces_for(value, patient_ids))


def _release_score_traces(result: Any) -> None:
    """Drop engine lists the profile writer does not read."""
    if result is None:
        return
    for name in (
        "atom_matches",
        "phenotype_results",
        "patient_verdicts",
        "patient_profiles",
        "al_detected_profiles",
        "aa_profiles",
        "config_gaps",
    ):
        value = getattr(result, name, None)
        if isinstance(value, list):
            value.clear()


def _screen_batch(
    session: Any,
    source_config: Mapping[str, Any],
    patient_ids: Sequence[str],
    per_patient_cap: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if per_patient_cap:
        rows = _fetch_sql(session, _screen_window_sql(source_config, patient_ids, per_patient_cap))
    else:
        rows = _fetch_where(
        session,
        _qualified_temp(str(source_config["namespace"]), SCREEN_TABLE),
        _patient_column(source_config, "claim"),
        patient_ids,
    )
    claims: list[dict[str, Any]] = []
    encounters: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    encounter_columns = source_config["tables"]["encounter"]["columns"]
    claim_columns = source_config["tables"]["claim"]["columns"]
    for row in rows:
        _pop_case(row, "AMY_V5_RN")
        visit_date = _pop_case(row, "ENCOUNTER_VISIT_DATE")
        claims.append(row)
        patient_id = _case_get(row, claim_columns["patient_id"])
        encounter_id = _case_get(row, claim_columns["encounter_id"])
        if patient_id in (None, "") or encounter_id in (None, "") or visit_date in (None, ""):
            continue
        key = (str(patient_id), str(encounter_id))
        if key in seen:
            continue
        seen.add(key)
        encounters.append({
            encounter_columns["patient_id"]: patient_id,
            encounter_columns["encounter_id"]: encounter_id,
            encounter_columns["encounter_date"]: visit_date,
        })
    return claims, encounters


def _table_readable(session: Any, physical_table: str) -> bool:
    try:
        _sql(session, f"SELECT * FROM {physical_table} WHERE 1 = 0")
    except Exception:
        return False
    return True


def _medication_table(source_config: Mapping[str, Any]) -> str | None:
    namespace = str(source_config.get("namespace") or "")
    if not namespace:
        return None
    parts = [_q(part) for part in namespace.split(".")]
    parts.append(_q("MEDICATIONS"))
    return ".".join(parts)


def _patient_ids(
    session: Any,
    source_config: Mapping[str, Any],
    max_patients: int | None,
) -> list[str]:
    patient = _q(_patient_column(source_config, "claim"))
    limit = f" LIMIT {int(max_patients)}" if max_patients else ""
    rows = _fetch_sql(
        session,
        f"SELECT DISTINCT CAST({patient} AS VARCHAR) AS PATIENT_ID "
        f"FROM {_qualified_temp(str(source_config['namespace']), SCREEN_TABLE)} WHERE {patient} IS NOT NULL "
        f"ORDER BY PATIENT_ID{limit}",
    )
    return [str(_case_get(row, "PATIENT_ID")) for row in rows if _case_get(row, "PATIENT_ID") not in (None, "")]


_FORBIDDEN_SQL = re.compile(
    r"\b(UPDATE|DELETE|DROP|ALTER|TRUNCATE|MERGE|UNDROP|GRANT|REVOKE|COPY|PUT|REMOVE)\b"
    r"|\bCREATE\s+OR\s+REPLACE\b"
    r"|\bCREATE\s+(?!TEMPORARY\s+TABLE\b)(?:OR\s+REPLACE\s+)?(?:TRANSIENT\s+|EXTERNAL\s+)?TABLE\b"
    r"|\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:VIEW|STAGE|FILE\s+FORMAT|STREAM|TASK|PIPE|SEQUENCE)\b",
    re.IGNORECASE,
)
_ALLOWED_SQL = re.compile(
    r"^\s*(SELECT|WITH|SHOW|DESCRIBE|DESC|EXPLAIN|CREATE|INSERT)\b",
    re.IGNORECASE,
)
_TEMP_NAME = r'(?:(?:"[^"]+"\.){2})?"?AMY_V5_[A-Z0-9_]+"?'
_CREATE_TEMPORARY = re.compile(
    rf"^\s*CREATE\s+TEMPORARY\s+TABLE\s+{_TEMP_NAME}(?=\s)",
    re.IGNORECASE,
)
_INSERT_TEMPORARY = re.compile(
    rf"^\s*INSERT\s+INTO\s+{_TEMP_NAME}(?=\s)",
    re.IGNORECASE,
)
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.{}:-]+$")


def _assert_warehouse_sql(sql: str) -> None:
    """Reject every statement except a read or a temporary-table create/insert."""
    text = str(sql or "").strip()
    if not text:
        raise RuntimeError("empty SQL is not allowed")
    if _FORBIDDEN_SQL.search(text) or not _ALLOWED_SQL.match(text):
        raise RuntimeError(
            "Blocked SQL. This run allows SELECT, WITH, SHOW, DESCRIBE, EXPLAIN, "
            "CREATE TEMPORARY TABLE AMY_V5_*, and INSERT INTO those temporary tables only."
        )
    if re.match(r"^\s*CREATE\b", text, re.IGNORECASE) and not _CREATE_TEMPORARY.match(text):
        raise RuntimeError("CREATE is allowed only for AMY_V5_ temporary tables")
    if re.match(r"^\s*INSERT\b", text, re.IGNORECASE) and not _INSERT_TEMPORARY.match(text):
        raise RuntimeError("INSERT is allowed only into AMY_V5_ temporary tables")


def _fetch_sql(session: Any, sql: str) -> list[dict[str, Any]]:
    _assert_warehouse_sql(sql)
    result = session.sql(sql)
    try:
        iterator = result.to_local_iterator() if hasattr(result, "to_local_iterator") else result.collect()
        return [_row_dict(row) for row in iterator]
    finally:
        del result
        _release_query_memory(session)


def _sql(session: Any, sql: str) -> None:
    _assert_warehouse_sql(sql)
    result = session.sql(sql)
    try:
        if hasattr(result, "collect"):
            result.collect()
    finally:
        del result
        _release_query_memory(session)


def _scalar(session: Any, sql: str) -> int:
    rows = _fetch_sql(session, sql)
    if not rows:
        return 0
    return int(next(iter(rows[0].values())))


def _temporary_table_status(session: Any, table_name: str) -> str:
    bare_name = _bare_temp_name(table_name)
    rows = _fetch_sql(
        session,
        f"SHOW TABLES LIKE '{bare_name}' IN SCHEMA {_schema_of(table_name)}",
    )
    kinds = []
    for row in rows:
        name = str(_case_get(row, "name") or "")
        if name.upper() != bare_name.upper():
            continue
        kinds.append(str(_case_get(row, "kind") or "").upper())
    if not kinds:
        return "MISSING"
    if any(kind != "TEMPORARY" for kind in kinds):
        raise RuntimeError(
            f"{table_name} already exists and is not a temporary table ({kinds}). "
            "This run will not modify it."
        )
    return "TEMPORARY"


def _create_temporary(session: Any, table_name: str, create_sql: str) -> None:
    if _temporary_table_status(session, table_name) == "TEMPORARY":
        raise RuntimeError(
            f"{table_name} already exists in this session. This run will not drop or replace it. "
            "Start a new Snowflake session."
        )
    _sql(session, create_sql)
    print({"temporary_table": table_name, "action": "created"})


def _reuse_or_create(session: Any, table_name: str, create_sql: str, *, allow_empty: bool = False) -> str:
    if _temporary_table_status(session, table_name) == "TEMPORARY":
        count = _scalar(session, f"SELECT COUNT(*) FROM {table_name}")
        if count <= 0 and not allow_empty:
            raise RuntimeError(
                f"{table_name} is an empty temporary table. This run will not drop it. "
                "Start a new Snowflake session."
            )
        print({"temporary_table": table_name, "action": "reused", "rows": count})
        return "reused"
    _sql(session, create_sql)
    print({"temporary_table": table_name, "action": "created"})
    return "created"


def _ensure_id_table(session: Any, table_name: str, patient_ids: Sequence[str]) -> str:
    if _temporary_table_status(session, table_name) == "TEMPORARY":
        existing = {
            str(_case_get(row, "PATIENT_ID") or next(iter(row.values())))
            for row in _fetch_sql(session, f"SELECT PATIENT_ID FROM {table_name}")
        }
        if existing != set(patient_ids):
            raise RuntimeError(
                f"{table_name} already holds a different patient list. "
                "This run will not drop it. Start a new Snowflake session."
            )
        print({"temporary_table": table_name, "action": "reused", "rows": len(existing)})
        return "reused"
    _create_id_table(session, table_name, patient_ids)
    return "created"


def _create_id_table(session: Any, table_name: str, patient_ids: Sequence[str]) -> None:
    _create_temporary(
        session,
        table_name,
        f"CREATE TEMPORARY TABLE {table_name} (PATIENT_ID VARCHAR)",
    )
    _insert_values(session, table_name, ("PATIENT_ID",), [(patient_id,) for patient_id in patient_ids])


def _insert_code_rows(session: Any, table_name: str, rows: Sequence[Mapping[str, str]]) -> None:
    _insert_values(
        session,
        table_name,
        ("NORMALIZED_CODE", "MATCH_MODE"),
        [(row["NORMALIZED_CODE"], row["MATCH_MODE"]) for row in rows],
    )


def _insert_values(
    session: Any,
    table_name: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[str]],
) -> None:
    if not rows:
        return
    column_sql = ", ".join(columns)
    for start in range(0, len(rows), 400):
        values = []
        for row in rows[start:start + 400]:
            if len(row) != len(columns):
                raise ValueError("insert row does not match the column list")
            values.append("(" + ", ".join(_sql_literal(value) for value in row) + ")")
        _sql(
            session,
            f"INSERT INTO {table_name} ({column_sql}) VALUES {', '.join(values)}",
        )


def _sql_literal(value: str) -> str:
    text = str(value)
    if not _SAFE_TOKEN.fullmatch(text):
        raise ValueError(f"refusing to interpolate an unsafe SQL value: {text!r}")
    return "'" + text + "'"


def _id_list(patient_ids: Sequence[str]) -> str:
    return ", ".join(_sql_literal(patient_id) for patient_id in patient_ids)


def _read_verdicts(path: Path) -> list[dict[str, str]]:
    """Read legacy verdict files first, then checkpoint files so the newest row wins.

    The notebook filesystem cannot seek, so each batch is a new file.
    """
    output_dir = path.parent
    files: list[Path] = []
    if path.exists():
        files.append(path)
    if output_dir.exists():
        files.extend(sorted(output_dir.glob("patient_verdicts_batch_*.csv")))
    checkpoint_dir = output_dir / "checkpoints"
    if checkpoint_dir.exists():
        files.extend(sorted(checkpoint_dir.glob("verdicts_*.csv")))
    rows: list[dict[str, str]] = []
    seen: set[Path] = set()
    for file_path in files:
        if file_path in seen:
            continue
        seen.add(file_path)
        try:
            rows.extend(_read_csv_dicts(file_path))
        except OSError as exc:
            _say({"verdict_file_skipped": str(file_path), "reason": str(exc)})
    return rows


def _read_csv_dicts(path: Path) -> list[dict[str, str]]:
    """Read one checkpoint. A damaged file is skipped so the others still resume."""
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception as exc:
        _say({"checkpoint_file_skipped": str(path), "reason": _short_error(exc)})
        return []


def _write_verdict_batch(output_dir: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write one new checkpoint file. A restart must not overwrite saved patients."""
    if not rows:
        return
    _write_csv_once(
        _unique_output_path(output_dir / "checkpoints", "verdicts", ".csv"),
        rows,
        VERDICT_FIELDS,
    )


def _write_running_counts(output_dir: Path, counts: Mapping[str, int], *, scored_batches: int) -> None:
    try:
        payload = json.dumps({"scored_batches": scored_batches, **counts}, indent=2)
        snapshot = _unique_output_path(output_dir / "checkpoints", "counts", ".json")
        snapshot.write_text(payload, encoding="utf-8")
        try:
            (output_dir / "running_counts.json").write_text(payload, encoding="utf-8")
        except OSError as exc:
            _say({"running_counts": str(snapshot), "reason": str(exc)})
    except Exception as exc:
        _say({"running_counts": "snapshot_failed", "reason": _short_error(exc)})


def _write_timing(path: Path, rows: Sequence[Mapping[str, Any]], resume: bool) -> None:
    if not rows:
        return
    target = path.with_name("patient_timing_continue.csv") if resume else path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _summary(
    *,
    phase: str,
    namespace: str,
    screening_cutoff: str,
    screening_codes: int,
    screen_claim_rows: int,
    screen_patients: int,
    patients_scored: int,
    verdict_rows: int,
    confirmed_patients: int,
    profile_patients: int,
    profiles_written: Mapping[str, int],
    output_dir: Path,
    elapsed_seconds: float,
    code_seconds: float,
    screen_seconds: float,
    census_seconds: float,
    profile_slice_seconds: float,
    timing_rows: Sequence[Mapping[str, Any]],
    temporary_tables: Sequence[str],
) -> dict[str, Any]:
    score_times = [float(row["score_seconds"]) for row in timing_rows]
    fetch_times = [float(row["fetch_seconds"]) for row in timing_rows]
    profile_times = [float(row["profile_seconds"] or 0) for row in timing_rows]
    remaining = max(int(screen_patients) - int(patients_scored), 0)
    median_score = _median(score_times)
    one_patient = all(int(row["batch_patients"]) == 1 for row in timing_rows) if timing_rows else True
    slowest = sorted(timing_rows, key=lambda row: float(row["score_seconds"]), reverse=True)[:5]
    return {
        "phase": phase,
        "stopped_after_pilot": phase == "pilot",
        "namespace": namespace,
        "evaluation_mode": "ICD_DATED_CLAIMS",
        "screening_cutoff": screening_cutoff,
        "screening_codes": screening_codes,
        "screen_claim_rows": screen_claim_rows,
        "screen_patients": screen_patients,
        "patients_scored": patients_scored,
        "remaining_patients": remaining,
        "verdict_rows": verdict_rows,
        "confirmed_patients": confirmed_patients,
        "profile_patients": profile_patients,
        "profiles_written": profiles_written,
        "timing_grain": "one patient" if one_patient else "batch time divided across the patients in that batch",
        "code_table_seconds": code_seconds,
        "warehouse_screen_seconds": screen_seconds,
        "census_slice_seconds": census_seconds,
        "profile_slice_seconds": profile_slice_seconds,
        "fetch_seconds_median": round(_median(fetch_times), 3),
        "score_seconds_min": round(min(score_times), 3) if score_times else 0,
        "score_seconds_median": round(median_score, 3),
        "score_seconds_mean": round(sum(score_times) / len(score_times), 3) if score_times else 0,
        "score_seconds_max": round(max(score_times), 3) if score_times else 0,
        "profile_seconds_mean": round(sum(profile_times) / len(profile_times), 3) if profile_times else 0,
        "estimated_remaining_score_hours": round(remaining * median_score / 3600, 2),
        "slowest_patients": [
            {
                "patient_id": row["patient_id"],
                "score_seconds": row["score_seconds"],
                "fetch_seconds": row["fetch_seconds"],
                "claim_rows": row["claim_rows"],
            }
            for row in slowest
        ],
        "elapsed_seconds": elapsed_seconds,
        "output_dir": str(output_dir),
        "durable_tables_created": False,
        "temporary_tables": list(temporary_tables),
        "statements_allowed": [
            "SELECT",
            "WITH",
            "SHOW",
            "DESCRIBE",
            "EXPLAIN",
            "CREATE TEMPORARY TABLE AMY_V5_*",
            "INSERT INTO AMY_V5_*",
        ],
        "statements_rejected": [
            "UPDATE",
            "DELETE",
            "DROP",
            "ALTER",
            "TRUNCATE",
            "MERGE",
            "CREATE OR REPLACE",
            "CREATE TABLE",
            "CREATE TRANSIENT TABLE",
            "INSERT into any source table",
        ],
    }


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return float(ordered[middle - 1] + ordered[middle]) / 2


def _append_detected(root: Path, folder: str, basename: str, profiles: Sequence[Mapping[str, Any]]) -> None:
    if not profiles:
        return
    detected = root / folder
    _append_jsonl(detected / f"{basename}.jsonl", profiles)
    for level, folder_name in SUSPICION_FOLDER.items():
        tier = [
            profile for profile in profiles
            if str((profile.get("suspected_diagnosis") or {}).get("suspicion_level") or "").upper() == level
        ]
        _append_jsonl(detected / folder_name / f"{basename}.jsonl", tier)


def _append_jsonl(path: Path, profiles: Sequence[Mapping[str, Any]]) -> None:
    """Write profiles to a new file. The notebook filesystem cannot append."""
    if not profiles:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = profiles_jsonl_bytes(profiles, include_proprietary_trace=False)
    target = path if not path.exists() else _unique_output_path(path.parent, path.stem, path.suffix)
    target.write_bytes(payload)


def _zip_output(output_dir: Path) -> str:
    """Pack the result folder into one zip beside it so Snowflake can download it once.

    The notebook filesystem cannot seek, and ZipFile seeks while it writes the
    directory. Build the archive in memory, then write the finished bytes once.
    """
    zip_path = output_dir.parent / f"{output_dir.name}.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output_dir.rglob("*")):
            if path.is_file() and path != zip_path:
                archive.write(path, path.relative_to(output_dir.parent).as_posix())
    zip_path.write_bytes(buffer.getvalue())
    return str(zip_path)


def _reset_outputs(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if path.is_file() and path.suffix in {".jsonl", ".csv", ".json"}:
            path.unlink()


def _export_verdict(verdict: Mapping[str, Any]) -> bool:
    levels = {
        str(verdict.get("attr_suspicion_level") or "").upper(),
        str(verdict.get("al_suspicion_level") or "").upper(),
        str(verdict.get("aa_suspicion_level") or "").upper(),
    }
    return bool(levels & set(PROFILE_LEVELS))


def _object_ids(items: Iterable[Any]) -> list[str]:
    patient_ids: list[str] = []
    for item in items:
        patient_id = item.get("patient_id") if isinstance(item, Mapping) else getattr(item, "patient_id", None)
        if patient_id not in (None, ""):
            patient_ids.append(str(patient_id))
    return patient_ids


def _collect_terminology(node: Any, terms: list[Mapping[str, Any]]) -> None:
    if isinstance(node, Mapping):
        terminology = node.get("terminology")
        if isinstance(terminology, list):
            terms.extend(item for item in terminology if isinstance(item, Mapping))
        for value in node.values():
            _collect_terminology(value, terms)
    elif isinstance(node, list):
        for item in node:
            _collect_terminology(item, terms)


def _physical(source_config: Mapping[str, Any], table_key: str) -> str:
    table = source_config["tables"][table_key]
    namespace = source_config.get("namespace")
    parts = [_q(part) for part in str(namespace).split(".")] if namespace else []
    parts.append(_q(str(table["name"])))
    return ".".join(parts)


def _patient_column(source_config: Mapping[str, Any], table_key: str) -> str:
    return str(source_config["tables"][table_key]["columns"]["patient_id"])


def _namespace(value: str) -> str:
    parts = [part.strip() for part in str(value or "").split(".") if part.strip()]
    if len(parts) != 2:
        raise ValueError("namespace must be DATABASE.SCHEMA")
    return ".".join(parts)


def _q(identifier: str) -> str:
    return quote_identifier(identifier)


def _qualified_temp(namespace: str, name: str) -> str:
    parts = [_q(part) for part in str(namespace).split(".") if part.strip()]
    if len(parts) != 2:
        raise ValueError("temporary tables need a DATABASE.SCHEMA namespace")
    return ".".join([*parts, _q(name)])


def _bare_temp_name(table_name: str) -> str:
    return table_name.split(".")[-1].strip().strip('"')


def _schema_of(table_name: str) -> str:
    parts = table_name.split(".")
    if len(parts) != 3:
        raise RuntimeError(f"{table_name} must be a database.schema.table name")
    return ".".join(parts[:-1])


def _chunks(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _cell(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return " | ".join(str(item) for item in value)
    return value


def _pop_case(row: dict[str, Any], name: str) -> Any:
    for key in list(row):
        if str(key).upper() == name.upper():
            return row.pop(key)
    return None


def _case_get(row: Mapping[str, Any], name: str) -> Any:
    for key, value in row.items():
        if str(key).upper() == str(name).upper():
            return value
    return None


def _row_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    if hasattr(row, "as_dict"):
        return dict(row.as_dict())
    if hasattr(row, "asDict"):
        return dict(row.asDict())
    return dict(row)

"""Run adversarial multi-row EHR patients through the combined ATTR pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import medspacy

from v4.pipeline import run_attr_reference_pipeline


SUITE_PATH = Path(__file__).with_name("adversarial_patient_suite.json")


def _quiet_third_party_logs() -> None:
    try:
        from loguru import logger

        logger.disable("PyRuSH")
    except Exception:
        pass


def _plain_date(value: Any) -> str:
    text = str(value)
    return text[:10] if len(text) >= 10 else text


def _evaluate_case(case: dict[str, Any], *, nlp: Any, cutoff: str) -> dict[str, Any]:
    run = run_attr_reference_pipeline(
        case["rows_by_table"],
        run_id=f"ADVERSARIAL:{case['case_id']}",
        candidate_patient_ids={case["patient_id"]},
        nlp=nlp,
        screening_cutoff=cutoff,
        include_profiles=True,
    )
    failures: list[str] = []
    expected = case.get("expectations", {})
    if expected.get("not_known_attr") and run.known_attr_patients:
        failures.append("patient was incorrectly excluded as known ATTR")
    if not run.known_attr_patients and len(run.router_output) != 2:
        failures.append(f"expected two phenotype router rows, got {len(run.router_output)}")
    if len(run.patient_profiles) > 1:
        failures.append(f"expected at most one combined profile, got {len(run.patient_profiles)}")
    if run.patient_profiles:
        verdicts = {
            row["phenotype"]: row
            for row in run.patient_profiles[0].get("phenotype_verdicts", [])
        }
        if "ATTRV" not in verdicts or "ATTRWT" not in verdicts:
            failures.append("combined profile does not contain both ATTRv and ATTRwt verdicts")

    evidence_summary: dict[str, dict[str, Any]] = {}
    for rule in expected.get("evidence", []):
        atom_id = str(rule["atom_id"])
        rows = [row for row in run.evidence_events if row.atom_id == atom_id]
        statuses = [str(row.status) for row in rows]
        dates = [_plain_date(row.event_date) for row in rows]
        phrase_count = sum(
            str(row.source_provenance.get("match_method")) == "PHRASEMATCHER"
            for row in rows
        )
        evidence_summary[atom_id] = {
            "statuses": statuses,
            "event_dates": dates,
            "phrase_matches": phrase_count,
        }
        for status in rule.get("statuses_include", []):
            if status not in statuses:
                failures.append(f"{atom_id}: missing expected status {status}; got {statuses}")
        forbidden = rule.get("forbid_status")
        if forbidden and forbidden in statuses:
            failures.append(f"{atom_id}: forbidden status {forbidden} was present")
        minimum = int(rule.get("minimum_phrase_matches", 0) or 0)
        if phrase_count < minimum:
            failures.append(
                f"{atom_id}: expected at least {minimum} phrase matches; got {phrase_count}"
            )
        for expected_date in rule.get("event_dates_include", []):
            if str(expected_date) not in dates:
                failures.append(
                    f"{atom_id}: missing expected clinical date {expected_date}; got {dates}"
                )

    router = {
        row["phenotype"]: {
            "status": row["status"],
            "suspicion_level": row.get("suspicion_level"),
            "parallel_routes": list(row.get("parallel_routes", ())),
        }
        for row in run.router_output
    }
    combined = (
        run.patient_profiles[0].get("suspected_diagnosis")
        if run.patient_profiles else None
    )
    return {
        "case_id": case["case_id"],
        "patient_id": case["patient_id"],
        "failures": failures,
        "evidence": evidence_summary,
        "router": router,
        "combined_profile": combined,
        "stage_counts": run.stage_counts,
    }


def validate(path: Path = SUITE_PATH, *, raise_on_failure: bool = True) -> dict[str, Any]:
    suite = json.loads(path.read_text(encoding="utf-8"))
    _quiet_third_party_logs()
    nlp = medspacy.load()
    results = [
        _evaluate_case(case, nlp=nlp, cutoff=str(suite["screening_cutoff"]))
        for case in suite["patients"]
    ]
    failures = [
        {"case_id": row["case_id"], "failures": row["failures"]}
        for row in results
        if row["failures"]
    ]
    report = {
        "suite_id": suite["suite_id"],
        "patient_count": len(results),
        "passed": len(results) - len(failures),
        "failed": len(failures),
        "failures": failures,
        "results": results,
    }
    if raise_on_failure and failures:
        raise AssertionError(json.dumps(report, indent=2, default=str))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, default=SUITE_PATH)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(
        validate(args.suite, raise_on_failure=not args.report_only),
        indent=2,
        ensure_ascii=False,
        default=str,
    ))


if __name__ == "__main__":
    main()

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


def _exported_patient_ids(exports: dict[str, Any]) -> list[str]:
    """Read the external JSONL artifact and return its patient membership."""
    path = exports.get("jsonl")
    if not path:
        return []
    artifact = Path(str(path))
    if not artifact.exists():
        return []
    return [
        str(row["patient_id"])
        for line in artifact.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for row in [json.loads(line)]
        if row.get("patient_id") is not None
    ]


def _evaluate_case(case: dict[str, Any], *, nlp: Any, cutoff: str, output_dir: Path | None = None, expected_router_statuses: dict[str, str] | None = None, expected_router_details: dict[str, dict[str, Any]] | None = None, expected_combined_attr: dict[str, Any] | None = None) -> dict[str, Any]:
    run = run_attr_reference_pipeline(
        case["rows_by_table"],
        run_id=f"ADVERSARIAL:{case['case_id']}",
        candidate_patient_ids={case["patient_id"]},
        nlp=nlp,
        screening_cutoff=cutoff,
        include_profiles=True,
        profile_output_dir=output_dir,
    )
    failures: list[str] = []
    expected = case.get("expectations", {})
    if expected.get("not_known_attr") and run.known_attr_patients:
        failures.append("patient was incorrectly excluded as known ATTR")
    if not run.known_attr_patients and len(run.router_output) != 3:
        failures.append(f"expected three phenotype router rows, got {len(run.router_output)}")
    if len(run.patient_profiles) > 1:
        failures.append(f"expected at most one combined profile, got {len(run.patient_profiles)}")
    if run.patient_profiles:
        verdicts = {
            row["phenotype"]: row
            for row in run.patient_profiles[0].get("phenotype_verdicts", [])
        }
        if not {"ATTRV", "ATTRWT", "AL"}.issubset(verdicts):
            failures.append("combined profile does not contain ATTRv, ATTRwt, and AL verdicts")

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
            "matched_combination_id": row.get("matched_combination_id"),
            "priority_class": row.get("priority_class"),
            "suspicion_level": row.get("suspicion_level"),
            "result_route": row.get("result_route"),
            "parallel_routes": list(row.get("parallel_routes", ())),
        }
        for row in run.router_output
    }
    if expected_router_statuses:
        expected_statuses = {
            phenotype: status
            for phenotype, status in expected_router_statuses.items()
            if phenotype in {"ATTRV", "ATTRWT", "AL"}
        }
        actual_statuses = {phenotype: item["status"] for phenotype, item in router.items()}
        if actual_statuses != expected_statuses:
            failures.append(f"router status matrix mismatch: expected {expected_statuses}, got {actual_statuses}")
        expected_main = bool(expected_router_statuses.get("main_attr", False))
        expected_al = bool(expected_router_statuses.get("al_detected", False))
        if bool(run.patient_profiles) != expected_main:
            failures.append(f"combined ATTR export mismatch: expected {expected_main}, got {bool(run.patient_profiles)}")
        if bool(run.al_detected_profiles) != expected_al:
            failures.append(f"AL-detected export mismatch: expected {expected_al}, got {bool(run.al_detected_profiles)}")
        if output_dir is not None:
            main_ids = _exported_patient_ids(run.profile_exports)
            al_ids = _exported_patient_ids(run.al_detected_exports)
            expected_ids = [str(case["patient_id"])]
            if (main_ids == expected_ids) != expected_main:
                failures.append(f"combined ATTR artifact membership mismatch: expected {expected_main}, got {main_ids}")
            if (al_ids == expected_ids) != expected_al:
                failures.append(f"AL-detected artifact membership mismatch: expected {expected_al}, got {al_ids}")
    if expected_router_details:
        for phenotype, expected_detail in expected_router_details.items():
            actual = router.get(phenotype)
            if actual is None:
                failures.append(f"missing router detail for {phenotype}")
                continue
            for field, expected_value in expected_detail.items():
                if actual.get(field) != expected_value:
                    failures.append(
                        f"{phenotype} {field} mismatch: expected {expected_value!r}, got {actual.get(field)!r}"
                    )
    if expected.get("expect_al_pass") and router.get("AL", {}).get("status") != "PHENOTYPE_PASS":
        failures.append(f"expected AL PHENOTYPE_PASS, got {router.get('AL')}")
    if expected.get("expect_al_detected_only"):
        if len(run.al_detected_profiles) != 1:
            failures.append(f"expected one AL-detected profile, got {len(run.al_detected_profiles)}")
        if run.patient_profiles:
            failures.append("AL-detected-only case incorrectly entered combined ATTR output")
        if not run.al_detected_profiles:
            failures.append("AL-detected-only case did not produce an AL profile")
        else:
            al_verdicts = {row["phenotype"] for row in run.al_detected_profiles[0].get("phenotype_verdicts", [])}
            if not {"ATTRV", "ATTRWT", "AL"}.issubset(al_verdicts):
                failures.append("AL-detected profile is missing one of ATTRV/ATTRWT/AL verdicts")
            from v4.output.patient_profile import strip_proprietary_trace
            if "proprietary_pipeline_trace" not in run.al_detected_profiles[0]:
                failures.append("AL-detected profile internal trace is missing")
            if "proprietary_pipeline_trace" in strip_proprietary_trace(run.al_detected_profiles[0]):
                failures.append("AL-detected trace stripping did not remove proprietary trace")
    from v4.output.patient_profile import strip_proprietary_trace
    for profile_kind, profiles in (("combined", run.patient_profiles), ("AL-detected", run.al_detected_profiles)):
        for profile in profiles:
            profile_verdicts = {row["phenotype"] for row in profile.get("phenotype_verdicts", [])}
            if not {"ATTRV", "ATTRWT", "AL"}.issubset(profile_verdicts):
                failures.append(f"{profile_kind} profile is missing one of ATTRV/ATTRWT/AL verdicts")
            if "proprietary_pipeline_trace" not in profile:
                failures.append(f"{profile_kind} profile internal trace is missing")
            if "proprietary_pipeline_trace" in strip_proprietary_trace(profile):
                failures.append(f"{profile_kind} trace stripping did not remove proprietary trace")
    if expected_combined_attr:
        expected_present = bool(expected_combined_attr.get("present"))
        if bool(run.patient_profiles) != expected_present:
            failures.append(f"combined ATTR profile presence mismatch: expected {expected_present}, got {bool(run.patient_profiles)}")
        if expected_present and run.patient_profiles:
            diagnosis = run.patient_profiles[0].get("suspected_diagnosis", {})
            for field in ("suspicion_level", "passed_phenotypes", "highest_suspicion_phenotypes"):
                if field in expected_combined_attr and diagnosis.get(field) != expected_combined_attr[field]:
                    failures.append(
                        f"combined ATTR {field} mismatch: expected {expected_combined_attr[field]!r}, got {diagnosis.get(field)!r}"
                    )
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
        "al_detected_profiles": len(run.al_detected_profiles),
        "profile_exports": run.profile_exports,
        "al_detected_exports": run.al_detected_exports,
        "known_attr_exports": run.known_attr_exports,
        "known_al_exports": run.known_al_exports,
        "stage_counts": run.stage_counts,
    }


def validate(path: Path = SUITE_PATH, *, raise_on_failure: bool = True, output_dir: Path | None = None) -> dict[str, Any]:
    suite = json.loads(path.read_text(encoding="utf-8"))
    _quiet_third_party_logs()
    nlp = medspacy.load()
    results = []
    for case in suite["patients"]:
        case_output = output_dir / str(case["case_id"]) if output_dir is not None else None
        results.append(_evaluate_case(
            case,
            nlp=nlp,
            cutoff=str(suite["screening_cutoff"]),
            output_dir=case_output,
            expected_router_statuses=suite.get("expected_router_statuses", {}).get(str(case["case_id"])),
            expected_router_details=suite.get("expected_router_details", {}).get(str(case["case_id"])),
            expected_combined_attr=suite.get("expected_combined_attr", {}).get(str(case["case_id"])),
        ))
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
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(
        validate(args.suite, raise_on_failure=not args.report_only, output_dir=args.output_dir),
        indent=2,
        ensure_ascii=False,
        default=str,
    ))


if __name__ == "__main__":
    main()

"""Run the focused difficult-patient validation without Snowflake.

This validates extraction and reasoning mechanics only.  It does not replace
the required connected Snowflake schema/integration run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import medspacy

from v4.config_loader import load_phenotype_configs
from v4.extraction.atom_matching import build_phrase_matcher
from v4.extraction.extraction_contract import is_nlp_system
from v4.output.patient_profile import strip_proprietary_trace
from v4.pipeline import AttrExtractionConfig, run_attr_reference_pipeline


FIXTURE_PATH = Path(__file__).with_name("complex_patient_fixture.json")


def _quiet_third_party_logs() -> None:
    try:
        from loguru import logger

        logger.disable("PyRuSH")
    except Exception:
        pass


def _load_fixture(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _evidence(run: Any, atom_id: str) -> list[Any]:
    return [row for row in run.evidence_events if row.atom_id == atom_id]


def _exported_patient_ids(exports: dict[str, Any]) -> list[str]:
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


def validate(path: Path = FIXTURE_PATH, output_dir: Path | None = None) -> dict[str, Any]:
    fixture = _load_fixture(path)
    configs = load_phenotype_configs(("ATTRV", "ATTRWT", "AL"))
    extraction_config = AttrExtractionConfig(configs)
    _quiet_third_party_logs()
    nlp = medspacy.load()

    nlp_terms = [row for row in extraction_config.rows("terminology") if is_nlp_system(row.get("terminology_system"))]
    _matcher, labels = build_phrase_matcher(nlp, nlp_terms)
    if len(labels) != len(nlp_terms):
        raise AssertionError(f"PhraseMatcher loaded {len(labels)} of {len(nlp_terms)} configured NLP rows")

    run = run_attr_reference_pipeline(
        fixture["rows_by_table"],
        configs=configs,
        run_id=fixture["fixture_id"],
        candidate_patient_ids={fixture["patient_id"]},
        nlp=nlp,
        screening_cutoff=fixture["screening_cutoff"],
        include_profiles=True,
        profile_output_dir=output_dir,
    )

    expected = fixture["expected"]
    routers = {row["phenotype"]: row for row in run.router_output}
    assert set(routers) == {"ATTRV", "ATTRWT", "AL"}, routers
    expected_router_statuses = expected["expected_router_statuses"]
    actual_router_statuses = {phenotype: row["status"] for phenotype, row in routers.items()}
    expected_statuses = {
        phenotype: status
        for phenotype, status in expected_router_statuses.items()
        if phenotype in {"ATTRV", "ATTRWT", "AL"}
    }
    assert actual_router_statuses == expected_statuses, (expected_statuses, actual_router_statuses)
    assert bool(run.patient_profiles) is bool(expected_router_statuses["main_attr"])
    assert bool(run.al_detected_profiles) is bool(expected_router_statuses["al_detected"])
    for phenotype, expected_detail in expected["expected_router_details"].items():
        for field, expected_value in expected_detail.items():
            assert routers[phenotype].get(field) == expected_value, (
                phenotype,
                field,
                expected_value,
                routers[phenotype].get(field),
            )
    router = routers["ATTRV"]
    if expected.get("expect_al_pass"):
        assert routers["AL"]["status"] == "PHENOTYPE_PASS", routers["AL"]
    true_signals = {
        row["signal_id"] for row in run.signal_hits
        if row["status"] == "TRUE" and row["phenotype"] == "ATTRV"
    }
    assert set(expected["true_signals"]).issubset(true_signals), (expected["true_signals"], sorted(true_signals))
    assert router["matched_combination_id"] == expected["matched_combination"], router
    assert router["status"] == expected["status"], router
    assert router["priority_class"] == expected["priority_class"], router

    # Current terminology includes a structured code for this atom.  When a
    # code and narrative evidence conflict, the generic matcher may report
    # either the term restriction or the explicit code-precedence hold.
    assert any(
        row.status == "UNKNOWN"
        and row.reason in {
            "CONFIG_RESTRICTION_TERM_CANNOT_FIRE_ALONE",
            "NLP_PRECEDENCE_CODE_SUPPRESSED",
        }
        for row in _evidence(run, "cts_bilateral")
    )
    assert any(row.status == "FALSE" and row.reason == "EXPERIENCER_MISMATCH" for row in _evidence(run, "cts_bilateral"))
    assert any(row.status == "TRUE" and row.source_provenance.get("match_method") == "PHRASEMATCHER" for row in _evidence(run, "cts_bilateral"))
    assert any(row.status == "TRUE" and str(row.event_date)[:10] == "2025-03-31" for row in _evidence(run, "burning_feet"))
    apical_evidence = _evidence(run, "apical_sparing")
    assert {row.status for row in apical_evidence} >= {"FALSE", "TRUE"}
    assert sum(
        row.source_provenance.get("match_method") == "PHRASEMATCHER"
        for row in apical_evidence
    ) >= 2
    assert any(row.status == "TRUE" and str(row.event_date)[:10] == "2025-11-03" for row in apical_evidence)
    assert any(row.status == "FALSE" and row.reason == "NEGATED" for row in _evidence(run, "diarrhea"))
    assert any(row.status == "UNKNOWN" and row.reason == "UNCERTAIN" for row in _evidence(run, "vitreous_opacity"))
    assert any(row.status == "FALSE" and row.reason == "EXPERIENCER_MISMATCH" for row in _evidence(run, "polyneuropathy"))
    assert any(row.status == "UNKNOWN" and row.reason == "AFTER_SCREENING_CUTOFF" for row in _evidence(run, "urine_protein_result"))
    assert not any(event.source_table in {"SOCIAL_HISTORY", "MEDICATION"} for event in run.source_events)

    profile = run.patient_profiles[0]
    assert len(profile["phenotype_verdicts"]) == 6
    verdicts = {row["phenotype"]: row for row in profile["phenotype_verdicts"]}
    assert verdicts["ATTRV"]["status"] == routers["ATTRV"]["status"]
    assert verdicts["ATTRWT"]["status"] == routers["ATTRWT"]["status"]
    assert verdicts["AL"]["status"] == routers["AL"]["status"]
    assert profile["suspected_diagnosis"]["screening_target"] == "ATTR"
    assert profile["suspected_diagnosis"]["suspicion_level"] == expected["expected_combined_attr_tier"]
    assert profile["suspected_diagnosis"]["passed_phenotypes"] == expected["expected_combined_passed_phenotypes"]
    assert profile["suspected_diagnosis"]["highest_suspicion_phenotypes"] == expected["expected_combined_highest_phenotypes"]
    assert "proprietary_pipeline_trace" in profile
    assert "proprietary_pipeline_trace" not in strip_proprietary_trace(profile)
    if expected.get("expect_concurrent"):
        assert len(run.patient_profiles) == 1
        assert len(run.al_detected_profiles) == 1
        assert any(
            item.get("agreement_strength") == "CONCORDANT_DIFFERENTIAL_EVIDENCE"
            for item in profile["clinical_rationale"].get("cross_phenotype_annotations", [])
        )
        al_profile = run.al_detected_profiles[0]
        assert {row["phenotype"] for row in al_profile["phenotype_verdicts"]} >= {"ATTRV", "ATTRWT", "AL"}
        assert "proprietary_pipeline_trace" in al_profile
        assert "proprietary_pipeline_trace" not in strip_proprietary_trace(al_profile)
        if output_dir is not None:
            assert run.profile_exports and run.al_detected_exports
            expected_ids = [str(fixture["patient_id"])]
            assert _exported_patient_ids(run.profile_exports) == expected_ids
            assert _exported_patient_ids(run.al_detected_exports) == expected_ids
    assert not run.known_al_patients
    assert not run.known_al_profiles
    assert not _exported_patient_ids(run.known_al_exports)
    assert any(item.get("scope") == "KNOWN_AL" and "UNAVAILABLE" in item.get("gap", "") for item in run.config_gaps)
    assert "al_detected_profiles" in run.stage_counts
    assert "known_al_exports" in run.summary()

    return {
        "fixture_id": fixture["fixture_id"],
        "patient_id": fixture["patient_id"],
        "configured_nlp_terms_loaded": len(labels),
        "stage_counts": run.stage_counts,
        "true_signals": sorted(true_signals),
        "matched_combination_id": router["matched_combination_id"],
        "status": router["status"],
        "priority_class": router["priority_class"],
        "phenotype_statuses": {
            phenotype: row["status"] for phenotype, row in routers.items()
        },
        "combined_attr_verdict": profile["suspected_diagnosis"],
        "parallel_routes": sorted({
            route
            for phenotype in ("ATTRV", "ATTRWT")
            for route in routers[phenotype].get("parallel_routes", ())
        }),
        "config_gaps": run.config_gaps,
        "profile_exports": run.profile_exports,
        "al_detected_exports": run.al_detected_exports,
        "known_attr_exports": run.known_attr_exports,
        "known_al_exports": run.known_al_exports,
        "trace_free_profile": strip_proprietary_trace(profile),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.fixture, args.output_dir), indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

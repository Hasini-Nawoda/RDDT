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


def validate(path: Path = FIXTURE_PATH, output_dir: Path | None = None) -> dict[str, Any]:
    fixture = _load_fixture(path)
    configs = load_phenotype_configs(("ATTRV", "ATTRWT"))
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
    assert set(routers) == {"ATTRV", "ATTRWT"}, routers
    router = routers["ATTRV"]
    true_signals = {
        row["signal_id"] for row in run.signal_hits
        if row["status"] == "TRUE" and row["phenotype"] == "ATTRV"
    }
    assert set(expected["true_signals"]).issubset(true_signals), (expected["true_signals"], sorted(true_signals))
    assert router["matched_combination_id"] == expected["matched_combination"], router
    assert router["status"] == expected["status"], router
    assert router["priority_class"] == expected["priority_class"], router

    assert any(row.status == "UNKNOWN" and row.reason == "CONFIG_RESTRICTION_TERM_CANNOT_FIRE_ALONE" for row in _evidence(run, "cts_bilateral"))
    assert any(row.status == "FALSE" and row.reason == "EXPERIENCER_MISMATCH" for row in _evidence(run, "cts_bilateral"))
    assert any(row.status == "TRUE" and row.source_provenance.get("match_method") == "PHRASEMATCHER" for row in _evidence(run, "cts_bilateral"))
    assert any(row.status == "TRUE" and str(row.event_date)[:10] == "2025-03-31" for row in _evidence(run, "burning_feet"))
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
    assert profile["suspected_diagnosis"]["screening_target"] == "ATTR"
    assert "proprietary_pipeline_trace" in profile
    assert "proprietary_pipeline_trace" not in strip_proprietary_trace(profile)

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
        "parallel_routes": list(router["parallel_routes"]),
        "config_gaps": run.config_gaps,
        "profile_exports": run.profile_exports,
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

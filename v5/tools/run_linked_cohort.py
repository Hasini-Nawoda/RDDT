"""Run the ICD-dated claims pipeline on the linked evaluation extract.

The extract lives in v5/sql/*_linked_eval.csv. Decisions use claim ICD-10
codes and encounter dates. The written profiles keep all five tables.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from v5.pipeline import run_attr_reference_pipeline
from v5.warehouse.source_schema import load_source_config


SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "not_for_snowflake" / "linked_eval_profiles"
FILES = {
    "census": "CENSUS_linked_eval.csv",
    "claim": "CLAIMS_linked_eval.csv",
    "encounter": "ENCOUNTERS_linked_eval.csv",
    "lab": "LABS_linked_eval.csv",
    "surgical_history": "SURGICAL_HISTORY_linked_eval.csv",
}


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _review_row(verdict: dict) -> dict:
    return {
        "patient_id": verdict.get("patient_id"),
        "population_status": verdict.get("population_status"),
        "confirmation_status": verdict.get("confirmation_status"),
        "confirmation_scopes": verdict.get("confirmation_scopes"),
        "attr_status": verdict.get("attr_status"),
        "attr_suspicion_level": verdict.get("attr_suspicion_level"),
        "attrv_status": verdict.get("attrv_status"),
        "attrwt_status": verdict.get("attrwt_status"),
        "al_status": verdict.get("al_status"),
        "al_suspicion_level": verdict.get("al_suspicion_level"),
        "aa_status": verdict.get("aa_status"),
        "aa_suspicion_level": verdict.get("aa_suspicion_level"),
        "candidate_for_review": verdict.get("candidate_for_review"),
        "reason": verdict.get("reason"),
    }


def main() -> int:
    rows = {
        key: _load_csv(SQL_DIR / filename)
        for key, filename in FILES.items()
    }
    source_config = load_source_config(profile="icd_dated_claims_v1")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result = run_attr_reference_pipeline(
        rows,
        source_config=source_config,
        screening_cutoff="2026-09-22",
        terminology_systems=("ICD10",),
        include_profiles=True,
        profile_output_dir=OUTPUT_DIR,
        profile_suspicion_levels=(
            "HIGHEST_SUSPICION",
            "HIGH_SUSPICION",
            "MODERATE_SUSPICION",
        ),
        evaluation_mode="ICD_DATED_CLAIMS",
    )
    summary = {
        "run_id": result.run_id,
        "profile": "icd_dated_claims_v1",
        "evaluation_mode": result.evaluation_mode,
        "stage_counts": result.stage_counts,
        "input_rows": {key: len(value) for key, value in rows.items()},
        "verdicts": [_review_row(row) for row in result.patient_verdicts],
        "profile_exports": {
            "attr": result.profile_exports,
            "al_detected": result.al_detected_exports,
            "known_attr": result.known_attr_exports,
            "known_al": result.known_al_exports,
        },
    }
    summary_path = OUTPUT_DIR / "review_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "summary": str(summary_path),
        "stage_counts": result.stage_counts,
        "verdicts": summary["verdicts"],
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

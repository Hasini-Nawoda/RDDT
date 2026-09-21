from __future__ import annotations

from types import SimpleNamespace

from v4.output.patient_profile import build_patient_profile
from v4.pipeline_steps.step_11_patient_profiles import build_known_profiles


def test_suspicion_profile_uses_same_builder_with_full_ehr_and_exact_stage_trace() -> None:
    patient_id = "p-suspect"
    source_config = {
        "tables": {
            "claim": {
                "name": "CLAIMS",
                "enabled": True,
                "profile_enabled": True,
                "columns": {
                    "patient_id": "COLUMN0",
                    "diagnosis_type": "COLUMN7",
                    "diagnosis_code": "COLUMN8",
                },
            },
            "lab": {
                "name": "LABS",
                "enabled": False,
                "profile_enabled": True,
                "columns": {
                    "patient_id": "COLUMN0",
                    "observation_identifier": "COLUMN4",
                    "observation_value": "COLUMN7",
                },
            },
        }
    }
    router_rows = [
        {
            "run_id": "run-1",
            "patient_id": patient_id,
            "phenotype": "ATTRV",
            "status": "PHENOTYPE_PASS",
            "result_route": "ATTRV_REVIEW",
            "suspicion_level": "HIGH_SUSPICION",
            "matched_combination_id": "ATTRV-C1",
            "explanation": "Configured ATTRv combination passed.",
        },
        {
            "run_id": "run-1",
            "patient_id": patient_id,
            "phenotype": "AL",
            "status": "NO_MATCH",
            "result_route": "NO_MATCH",
            "suspicion_level": None,
            "explanation": "AL criteria were not met.",
        },
    ]
    evidence = [{
        "patient_id": patient_id,
        "evidence_id": "EV-1",
        "atom_id": "ATOM-CARDIAC",
        "status": "TRUE",
        "event_date": "2026-01-02",
        "source_provenance": {
            "source_event_id": "SRC-1",
            "matched_config_value": "E85.2",
        },
    }]
    combination_hits = [{
        "patient_id": patient_id,
        "combination_id": "ATTRV-C1",
        "status": "TRUE",
        "selected_witnesses": [{"supporting_evidence_ids": ["EV-1"]}],
    }]
    profile = build_patient_profile(
        patient_id,
        screening_target="ATTR",
        router_rows=router_rows,
        evidence_events=evidence,
        signal_hits=[{"patient_id": patient_id, "signal_id": "SIG-1", "status": "TRUE"}],
        bucket_state=[{"patient_id": patient_id, "bucket_id": "BUCKET-1", "status": "TRUE"}],
        combination_hits=combination_hits,
        guardrail_hits=[{"patient_id": patient_id, "guardrail_id": "G-1", "status": "FALSE"}],
        source_config=source_config,
        ehr_records_by_table={
            "claim": [{"COLUMN0": patient_id, "COLUMN7": "ICD10", "COLUMN8": "E85.2"}],
            "lab": [{"COLUMN0": patient_id, "COLUMN4": "NT-proBNP", "COLUMN7": 900}],
        },
    )

    assert profile["diagnosis_state"] == "SUSPICION_FLAGGED"
    assert profile["ehr"]["completeness_status"] == "COMPLETE_FOR_CONFIGURED_AVAILABLE_TABLES"
    assert profile["ehr"]["records_by_table"]["lab"]["record_count"] == 1
    assert profile["medical_profile"]["event_count"] == 2
    assert len(profile["medical_profile"]["timeline"]) == 2
    risks = {row["risk_for"]: row for row in profile["phenotype_risk_assessments"]}
    assert risks["ATTR"]["risk_level"] == "HIGH_SUSPICION"
    assert risks["ATTRV"]["risk_level"] == "HIGH_SUSPICION"
    assert risks["AL"]["risk_level"] == "NOT_FLAGGED"
    assert [row["step"] for row in profile["algorithm_analysis"]["steps"]] == [
        "EVIDENCE_QUALIFICATION",
        "SIGNAL_EVALUATION",
        "BUCKET_EVALUATION",
        "COMBINATION_MATCHING",
        "GUARDRAIL_EVALUATION",
        "PHENOTYPE_ROUTING",
    ]


def test_known_attr_text_route_is_not_mislabeled_as_exact_icd10() -> None:
    patient = SimpleNamespace(
        run_id="run-known",
        patient_id="p-known",
        confirmation_scope="ATTR_SPECIFIC",
        confirmation_rule_ids=["KNOWN_ATTR_TEXT"],
        matched_config_values=["ATTR-CM"],
    )
    evidence = [SimpleNamespace(
        patient_id="p-known",
        source_provenance={"matched_config_value": "ATTR-CM"},
        match_method="NLP",
    )]
    profile = build_known_profiles(
        [patient],
        known_config=None,
        source_events=[],
        evidence_events=evidence,
        demographics={},
        source_config={
            "tables": {
                "claim": {
                    "name": "CLAIMS",
                    "enabled": True,
                    "profile_enabled": True,
                    "columns": {"patient_id": "COLUMN0"},
                }
            }
        },
        ehr_records_by_table={"claim": [{"COLUMN0": "p-known", "COLUMN21": "ATTR-CM"}]},
    )[0]

    assert profile["clinical_rationale"]["rule"] == "KNOWN_ATTR_TEXT"
    assert profile["clinical_rationale"]["confirmation_rule_ids"] == ["KNOWN_ATTR_TEXT"]
    assert profile["algorithm_analysis"]["steps"][0]["step"] == "CONFIGURED_CONFIRMATION_ROUTE"
    assert profile["algorithm_analysis"]["steps"][0]["confirmation_kind"] == "KNOWN_ATTR_TEXT"

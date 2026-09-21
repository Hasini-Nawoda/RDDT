from __future__ import annotations

import json
from decimal import Decimal

from v4.output.patient_profile import (
    build_patient_profile,
    build_confirmed_icd10_patient_profile,
    confirmed_icd10_profiles_csv_bytes,
    export_confirmed_icd10_profiles,
)


def test_confirmed_profile_keeps_all_claims_and_exact_match_evidence(tmp_path) -> None:
    summary = {
        "RUN_ID": "run-1",
        "PATIENT_ID": "p1",
        "STATUS": "CONFIRMED",
        "MATCHED_ICD10_CODES": "E85.81",
        "AMYLOIDOSIS_TYPES": "AL",
        "AMYLOIDOSIS_SUBTYPES": "light-chain (AL) amyloidosis",
        "CONFIRMATION_SCOPE": "AL_SPECIFIC",
        "RISK_LABEL": "CONFIRMED",
        "PRIORITY_LABEL": "CONFIRMED",
    }
    claims = [
        {"SOURCE_CLAIM": {"PATIENTID": "p1", "DIAGNOSISTYPE": "ICD10", "DIAGNOSISCODE": "E85.81", "COLUMN21": "note"}, "MATCHED_CODE": "E85.81", "AMYLOIDOSIS_TYPE": "AL"},
        {"PATIENTID": "p1", "DIAGNOSISTYPE": "ICD10", "DIAGNOSISCODE": "I10", "COLUMN21": "other"},
    ]

    profile = build_confirmed_icd10_patient_profile(summary, claims)

    assert profile["known_diagnosis"]["status"] == "CONFIRMED_AMYLOIDOSIS"
    assert profile["known_diagnosis"]["matched_icd10_codes"] == ["E85.81"]
    assert profile["source_data"]["claim_row_count"] == 2
    assert profile["source_data"]["claim_rows"][0]["COLUMN21"] == "note"
    assert profile["clinical_rationale"]["evidence_count"] == 1
    evidence = profile["clinical_rationale"]["matched_claim_evidence"][0]
    assert evidence["matched_icd10_code"] == "E85.81"
    assert evidence["source_claim"]["DIAGNOSISCODE"] == "E85.81"
    assert len(profile["medical_profile"]["timeline"]) == 2
    assert profile["medical_profile"]["timeline"][1]["raw_record"]["DIAGNOSISCODE"] == "I10"

    paths = export_confirmed_icd10_profiles([profile], tmp_path)
    exported = json.loads((tmp_path / "confirmed" / "confirmed_amyloidosis_patient_profiles.jsonl").read_text())
    assert exported["patient_id"] == "p1"
    assert len(exported["source_data"]["claim_rows"]) == 2
    assert paths["csv"].endswith("confirmed_amyloidosis_patient_profiles.csv")


def test_confirmed_profile_parses_snowflake_variant_json_and_preserves_subtype_commas() -> None:
    summary = {
        "PATIENT_ID": "p-json",
        "MATCHED_ICD10_CODES": "E85.9",
        "AMYLOIDOSIS_SUBTYPES": "amyloidosis, unspecified",
        "CONFIRMATION_SCOPES": "UNSPECIFIED_AMYLOIDOSIS",
    }
    claims = [{
        "SOURCE_CLAIM": json.dumps({
            "patient_id": "p-json",
            "diagnosis_type": "ICD10",
            "diagnosis_code": "E85.9",
            "paid_amount": 12.5,
        }),
        "MATCHED_CODE": "E85.9",
        "DIAGNOSIS_SYSTEM": "ICD10",
        "NORMALIZED_CODE": "E859",
        "AMYLOIDOSIS_SUBTYPE": "amyloidosis, unspecified",
        "CONFIRMATION_SCOPE": "UNSPECIFIED_AMYLOIDOSIS",
    }]

    profile = build_confirmed_icd10_patient_profile(summary, claims)

    assert profile["known_diagnosis"]["amyloidosis_subtypes"] == [
        "amyloidosis, unspecified"
    ]
    assert profile["known_diagnosis"]["confirmation_scope"] == [
        "UNSPECIFIED_AMYLOIDOSIS"
    ]
    assert profile["source_data"]["claim_rows"][0]["diagnosis_code"] == "E85.9"
    assert profile["clinical_rationale"]["matched_source_values"] == ["E85.9"]
    assert profile["clinical_rationale"]["findings"][0]["matched_value"] == "E85.9"


def test_confirmed_profile_serializes_snowflake_decimal_values() -> None:
    summary = {"PATIENT_ID": "p-decimal", "MATCHED_ICD10_CODES": "E85.81"}
    profile = build_confirmed_icd10_patient_profile(summary, [{
        "patient_id": "p-decimal",
        "diagnosis_type": "ICD10",
        "diagnosis_code": "E85.81",
        "paid_amount": Decimal("10.25"),
    }])

    payload = json.dumps(profile)
    assert '"paid_amount": 10.25' in payload


def test_confirmed_profile_matches_unpunctuated_exact_code_only() -> None:
    summary = {"PATIENT_ID": "p1", "MATCHED_ICD10_CODES": ["E85.9"]}
    claims = [
        {"patient_id": "p1", "diagnosis_type": "ICD-10-CM", "diagnosis_code": "E859"},
        {"patient_id": "p1", "diagnosis_type": "ICD-10-CM", "diagnosis_code": "E85.8"},
    ]
    profile = build_confirmed_icd10_patient_profile(summary, claims)
    assert profile["clinical_rationale"]["evidence_count"] == 1
    assert profile["clinical_rationale"]["matched_claim_evidence"][0]["matched_icd10_code"] == "E85.9"


def test_canonical_builder_preserves_complete_multitable_ehr_and_confirmation_trace() -> None:
    source_config = {
        "tables": {
            "census": {"name": "CENSUS", "enabled": False, "profile_enabled": True, "columns": {"patient_id": "COLUMN0"}},
            "claim": {"name": "CLAIMS", "enabled": True, "profile_enabled": True, "columns": {"patient_id": "PATIENTID", "diagnosis_type": "DIAGNOSISTYPE", "diagnosis_code": "DIAGNOSISCODE"}},
            "lab": {"name": "LABS", "enabled": False, "profile_enabled": True, "columns": {"patient_id": "COLUMN0", "observation_identifier": "COLUMN4", "observation_value": "COLUMN7"}},
            "medication": {"name": "MEDICATIONS", "enabled": False, "profile_enabled": True, "columns": {"patient_id": "COLUMN0", "medication_name": "COLUMN4"}},
        }
    }
    ehr = {
        "census": [{"COLUMN0": "p-full", "COLUMN2": "1980-01-01"}],
        "claim": [
            {"PATIENTID": "p-full", "DIAGNOSISTYPE": "ICD10", "DIAGNOSISCODE": "E85.81"},
            {"PATIENTID": "p-full", "DIAGNOSISTYPE": "ICD10", "DIAGNOSISCODE": "I10"},
        ],
        "lab": [{"COLUMN0": "p-full", "COLUMN4": "BNP", "COLUMN7": 500}],
        "medication": [{"COLUMN0": "p-full", "COLUMN4": "tafamidis"}],
    }
    profile = build_patient_profile(
        "p-full",
        source_config=source_config,
        ehr_records_by_table=ehr,
        confirmation_summary={
            "PATIENT_ID": "p-full",
            "MATCHED_ICD10_CODES": ["E85.81"],
            "AMYLOIDOSIS_TYPES": ["AL"],
            "AMYLOIDOSIS_SUBTYPES": ["light-chain (AL) amyloidosis"],
        },
        confirmation_evidence=[{
            "SOURCE_CLAIM": ehr["claim"][0],
            "MATCHED_CODE": "E85.81",
            "AMYLOIDOSIS_TYPE": "AL",
        }],
    )

    assert profile["ehr"]["completeness_status"] == "COMPLETE_FOR_CONFIGURED_AVAILABLE_TABLES"
    assert profile["ehr"]["total_record_count"] == 5
    assert profile["ehr"]["records_by_table"]["lab"]["records"][0]["COLUMN7"] == 500
    assert profile["ehr"]["records_by_table"]["medication"]["records"][0]["COLUMN4"] == "tafamidis"
    assert profile["clinical_rationale"]["evidence_count"] == 1
    assert profile["clinical_rationale"]["matched_claim_evidence"][0]["matched_icd10_code"] == "E85.81"
    assert profile["algorithm_analysis"]["steps"][0]["step"] == "CONFIRMED_ICD10_LOOKUP"
    assert profile["algorithm_analysis"]["steps"][1]["status"] == "NOT_RUN"
    assert {row["risk_for"] for row in profile["phenotype_risk_assessments"]} == {"AL"}
    csv_text = confirmed_icd10_profiles_csv_bytes([profile]).decode("utf-8-sig")
    assert ",2,1" in csv_text

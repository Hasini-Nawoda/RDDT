from __future__ import annotations

from v4.extraction.confirmed_icd10 import (
    extract_confirmed_icd10,
    materialize_confirmed_icd10_profiles,
)
from v4.warehouse.source_schema import default_source_config


def test_confirmed_extractor_is_date_free_icd10_only_and_deduplicated() -> None:
    rows = {
        "claim": [
            {"PATIENTID": "p-al", "DIAGNOSISTYPE": "ICD-10-CM", "DIAGNOSISCODE": "E85.81"},
            {"PATIENTID": "p-al", "DIAGNOSISTYPE": "ICD10", "DIAGNOSISCODE": "E85.81"},
            {"PATIENTID": "p-al", "DIAGNOSISTYPE": "ICD-9-CM", "DIAGNOSISCODE": "277.30"},
            {"PATIENTID": "p-text", "DIAGNOSISTYPE": "ICD-10-CM", "DIAGNOSISCODE": "E859", "COLUMN21": "AL amyloidosis"},
            {"PATIENTID": "p-other", "DIAGNOSISTYPE": "ICD-10-CM", "DIAGNOSISCODE": "I10"},
        ]
    }

    profiles = extract_confirmed_icd10(rows, source_config=default_source_config(), run_id="run")

    assert [profile.patient_id for profile in profiles] == ["p-al", "p-text"]
    assert profiles[0].matched_icd10_codes == ("E85.81",)
    assert profiles[0].amyloidosis_type == "AL"
    assert profiles[0].risk_label == "CONFIRMED"
    assert profiles[0].priority_label == "CONFIRMED"
    assert profiles[1].amyloidosis_subtype == "amyloidosis, unspecified"
    assert all(not hasattr(profile, "event_date") for profile in profiles)


class _Result:
    def collect(self):
        return []


class _Session:
    def __init__(self):
        self.calls = []

    def sql(self, sql, params=None):
        self.calls.append((sql, params))
        return _Result()


def test_confirmed_profiles_materialize_only_as_temporary_table() -> None:
    session = _Session()
    profiles = extract_confirmed_icd10(
        {"claim": [{"PATIENTID": "p1", "DIAGNOSISTYPE": "ICD10", "DIAGNOSISCODE": "E85.82"}]},
        source_config=default_source_config(),
    )

    assert materialize_confirmed_icd10_profiles(session, profiles) == 1
    assert "CREATE OR REPLACE TEMPORARY TABLE" in session.calls[0][0]
    assert "TRANSIENT" not in session.calls[0][0].upper()

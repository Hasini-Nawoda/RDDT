from __future__ import annotations

from v4.extraction.confirmed_icd10 import (
    extract_confirmed_icd10,
    materialize_confirmed_icd10_profiles,
)
from v4.warehouse.source_schema import default_source_config


def test_confirmed_extractor_is_date_free_icd10_only_and_deduplicated() -> None:
    rows = {
        "claim": [
            {"COLUMN0": "p-al", "COLUMN7": "ICD-10-CM", "COLUMN8": "E85.81"},
            {"COLUMN0": "p-al", "COLUMN7": "ICD10", "COLUMN8": "E85.81"},
            {"COLUMN0": "p-al", "COLUMN7": "ICD-9-CM", "COLUMN8": "277.30"},
            {"COLUMN0": "p-text", "COLUMN7": "ICD-10-CM", "COLUMN8": "E859", "COLUMN21": "AL amyloidosis"},
            {"COLUMN0": "p-other", "COLUMN7": "ICD-10-CM", "COLUMN8": "I10"},
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
        {"claim": [{"COLUMN0": "p1", "COLUMN7": "ICD10", "COLUMN8": "E85.82"}]},
        source_config=default_source_config(),
    )

    assert materialize_confirmed_icd10_profiles(session, profiles) == 1
    assert "CREATE OR REPLACE TEMPORARY TABLE" in session.calls[0][0]
    assert "TRANSIENT" not in session.calls[0][0].upper()

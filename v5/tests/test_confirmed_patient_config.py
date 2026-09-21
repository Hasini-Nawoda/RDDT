import json

import pytest

from v4.extraction.known_al import load_known_al_config
from v4.extraction.known_al import identify_known_al
from v4.extraction.known_attr import load_known_attr_config
from v4.extraction.source_events import expand_source_row
from v4.warehouse.source_schema import load_source_config


def test_consolidated_config_loads_both_routes():
    attr = load_known_attr_config()
    al = load_known_al_config()

    assert attr.path == al.path
    assert attr.path.endswith("confirmed_patients.json")
    assert {row["atom_id"] for row in attr.rows("atoms")} == {"confirmed_attr_e85"}
    assert {row["atom_id"] for row in al.rows("atoms")} == {"confirmed_al_e85_81"}
    assert "E85.81" in {row["value"] for row in al.rows("terminology")}
    assert al.available is True
    assert al.config_gap is None


def test_loaders_keep_flat_config_compatibility(tmp_path):
    payload = {
        "atoms": [{"atom_id": "a"}],
        "terminology": [{"atom_id": "a", "terminology_system": "NLP", "value": "term"}],
        "confirmation_rules": [{"rule_id": "r", "values": ["term"]}],
    }
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert load_known_attr_config(path).rows("atoms")[0]["atom_id"] == "a"


def test_consolidated_config_rejects_unknown_rule_value(tmp_path):
    payload = {
        "routes": {
            "AL": {
                "atoms": [{"atom_id": "a"}],
                "terminology": [{"atom_id": "a", "terminology_system": "NLP", "value": "term"}],
                "confirmation_rules": [{"rule_id": "r", "values": ["not-configured"]}],
            }
        }
    }
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = load_known_al_config(path)

    assert result.available is False
    assert result.config_gap and "unknown values" in result.config_gap


def test_claim_icd10_can_confirm_al_without_a_second_source_table():
    config = load_known_al_config()
    source_config = load_source_config(profile="legacy_ehr_v1")
    events = expand_source_row(
        {
            "Member/PatientId": "p-al-code",
            "DiagnosisCode": "E85.81",
            "DiagnosisType": "ICD10",
            "FromDate": "2026-01-02",
        },
        "claim",
        run_id="run",
        config_hash=config.config_hash,
        source_config=source_config,
    )

    result = identify_known_al(
        events,
        run_id="run",
        screening_cutoff="2026-01-31",
        config=config,
    )

    assert result.patient_ids == {"p-al-code"}
    assert result.patients[0].confirmation_scope == "AL_SPECIFIC"
    assert result.patients[0].confirmation_rule_ids == ["KNOWN_AL_ICD10"]


def test_al_text_uses_the_configured_al_rule_id():
    import spacy

    class AffirmedContext:
        @staticmethod
        def process(text, **kwargs):
            return {
                "context_processing_status": "OK",
                "negated": False,
                "uncertain": False,
                "experiencer": "PATIENT",
            }

    config = load_known_al_config()
    source_config = load_source_config(profile="legacy_ehr_v1")
    events = expand_source_row(
        {
            "Member/PatientId": "p-al-text",
            "ClinicalNotes": "Light chain (AL) amyloidosis is confirmed.",
            "FromDate": "2026-01-02",
        },
        "claim",
        run_id="run",
        config_hash=config.config_hash,
        source_config=source_config,
    )

    result = identify_known_al(
        events,
        run_id="run",
        screening_cutoff="2026-01-31",
        nlp=spacy.blank("en"),
        context_processor=AffirmedContext(),
        config=config,
    )

    assert result.patient_ids == {"p-al-text"}
    assert result.patients[0].confirmation_scope == "AL_SPECIFIC"
    assert result.patients[0].confirmation_rule_ids == ["KNOWN_AL_TEXT"]

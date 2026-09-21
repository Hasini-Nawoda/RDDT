from __future__ import annotations

from types import SimpleNamespace

import pytest

from v4.config_loader import ConfigLoadError, _adapt_signal_atom_mappings, _as_bool, _term_row
from v4.extraction.atom_matching import build_phrase_matcher, match_atom_events
from v4.extraction.candidate_net import build_candidate_plan
from v4.extraction.extraction_contract import (
    diagnosis_system,
    event_system_compatible,
    normalize_system,
    routes_for_system,
)
from v4.extraction.source_events import (
    _split_declared_values,
    expand_source_row,
    iter_source_events,
)
from v4.warehouse.source_schema import (
    default_source_config,
    is_table_profile_enabled,
    is_table_profile_required,
    load_source_config,
)


def test_default_source_config_is_claim_only_and_exposes_logical_mapping() -> None:
    config = default_source_config()
    enabled = [key for key, table in config["tables"].items() if table["enabled"]]
    assert enabled == ["claim"]
    claim = config["tables"]["claim"]
    assert claim["name"] == "CLAIMS"
    assert claim["columns"]["patient_id"] == "PATIENTID"
    assert claim["columns"]["diagnosis_code"] == "DIAGNOSISCODE"
    assert "diagnosis_code" in claim["required_columns"]


def test_source_schema_mapping_can_be_loaded_from_an_operator_file(tmp_path) -> None:
    path = tmp_path / "source_schema.json"
    path.write_text(
        '{"schema_version":"test", "namespace":"DB.SCHEMA", "tables": {'
        '"claim": {"name":"NEW_CLAIMS", "enabled":true, "required":true, '
        '"columns":{"patient_id":"MEMBER_ID", "diagnosis_code":"DX", '
        '"diagnosis_type":"DX_SYSTEM", "from_date":"SERVICE_DATE"}, '
        '"required_columns":["patient_id", "diagnosis_code"]}, '
        '"lab": {"name":"NEW_LABS", "enabled":"false", "required":false, '
        '"columns":{"patient_id":"MEMBER_ID"}, "required_columns":[]}'
        '}}',
        encoding="utf-8",
    )
    config = load_source_config(path)
    assert config["namespace"] == "DB.SCHEMA"
    assert config["tables"]["claim"]["columns"] == {
        "patient_id": "MEMBER_ID",
        "diagnosis_code": "DX",
        "diagnosis_type": "DX_SYSTEM",
        "from_date": "SERVICE_DATE",
    }
    assert config["tables"]["lab"]["enabled"] is False
    # Legacy/custom files without the new fields inherit the old algorithm
    # toggles, preserving compatibility for existing deployments.
    assert config["tables"]["claim"]["profile_enabled"] is True
    assert config["tables"]["claim"]["profile_required"] is True
    assert config["tables"]["lab"]["profile_enabled"] is False
    assert config["tables"]["lab"]["profile_required"] is False

    independent = {
        "key": "lab",
        "enabled": False,
        "required": False,
        "profile_enabled": "true",
        "profile_required": "false",
    }
    assert is_table_profile_enabled(independent) is True
    assert is_table_profile_required(independent) is False

    events = expand_source_row(
        {
            "MEMBER_ID": "p-new",
            "DX": "E85.81",
            "DX_SYSTEM": "ICD10",
            "SERVICE_DATE": "2026-01-02",
        },
        "claim",
        run_id="run",
        config_hash="hash",
        source_config=config,
    )
    assert [(event.patient_id, event.code_system, event.code_value) for event in events] == [
        ("p-new", "ICD10", "E85.81")
    ]


def test_claim_only_toggle_limits_broad_text_candidate_plan() -> None:
    config = SimpleNamespace(tables={
        "terminology": [{
            "atom_id": "a",
            "terminology_system": "NLP",
            "value": "amyloidosis",
            "can_fire_atom_alone": True,
        }]
    })

    plan = build_candidate_plan(
        config,
        config_hash="hash",
        source_config=load_source_config(profile="legacy_ehr_v1"),
    )

    assert plan
    assert {query.table_key for query in plan} == {"claim"}
    assert {query.source_field for query in plan} == {"ClinicalNotes"}


def test_disabled_source_tables_are_not_emitted_into_pipeline_events() -> None:
    rows = {
        "claim": [{"PATIENTID": "p1", "DIAGNOSISTYPE": "ICD10", "DIAGNOSISCODE": "I10"}],
        "lab": [{"PATIENTID": "p1", "OBSERVATIONIDENTIFIER": "14957-5"}],
    }
    events = list(
        iter_source_events(rows, run_id="r", config_hash="h", source_config=default_source_config())
    )
    assert events
    assert {event.attributes["table_key"] for event in events} == {"claim"}


def test_terminology_aliases_are_canonical_and_routes_are_typed() -> None:
    assert normalize_system("ICD-10-CM") == "ICD10"
    assert normalize_system("ICD-9-CM") == "ICD9"
    assert normalize_system("CPT/HCPCS") == "CPT_HCPCS"
    assert normalize_system("CPT / HCPCS") == "CPT_HCPCS"
    assert normalize_system("SNOMED CT") == "SNOMED_CT"
    assert routes_for_system("ICD10") == (
        ("claim", "diagnosis_code", "EXACT_CODE"),
        ("claim", "other_diagnosis_10", "EXACT_CODE"),
    )
    assert diagnosis_system("not-a-diagnosis-system") == ("ICD", True)
    assert event_system_compatible("CLAIM", "diagnosis_code", "ICD10", "ICD") is False
    assert event_system_compatible("CLAIM", "diagnosis_code", "ICD", "ICD10") is False
    assert event_system_compatible("CLAIM", "diagnosis_code", "ICD", "ICD") is True
    assert event_system_compatible("CLAIM", "diagnosis_code", "ICD9", "ICD10") is False
    assert event_system_compatible("CLAIM", "diagnosis_code", "ICD10", "ICD10") is True
    assert event_system_compatible("CLAIM", "other_diagnosis_9", "ICD", "ICD9") is False
    assert event_system_compatible("CLAIM", "other_diagnosis_9", "ICD9", "ICD9") is True
    assert routes_for_system("") == ()
    assert routes_for_system("UNSUPPORTED") == ()
    assert event_system_compatible("LAB", "observation_identifier", "LOINC", None) is False
    assert event_system_compatible("LAB", "observation_identifier", "LOINC", "LOCAL") is False
    assert event_system_compatible("LAB", "observation_identifier", "LOINC", "LOINC") is True
    assert event_system_compatible("CLAIM", "procedure_code", "CPT_HCPCS", "ICD10") is False
    assert event_system_compatible("MEDICAL_HISTORY", "snomed", "SNOMED_CT", "LOCAL") is False


def test_term_rows_parse_booleans_and_drop_workbook_metadata() -> None:
    row = _term_row(
        {"atom_id": "a"},
        {
            "value": "I10",
            "can_fire_atom_alone": "false",
            "match_mode": "EXACT_CODE",
            "mapping_role": "PROXY_SUPPORT",
            "provenance": {"sheet": "Atoms_by_Sign"},
        },
        "ICD-10-CM",
    )
    assert row["can_fire_atom_alone"] is False
    assert row["terminology_system"] == "ICD10"
    assert row["match_mode"] == "EXACT_CODE"
    assert row["mapping_role"] == "PROXY_SUPPORT"
    assert "provenance" not in row
    with pytest.raises(ConfigLoadError):
        _as_bool("perhaps", field="test")
    mapping = _adapt_signal_atom_mappings([{
        "signal_id": "s", "atom_id": "a", "can_fire_from_this_mapping": "false",
    }])[0]
    assert mapping["can_fire_from_this_mapping"] is False


def test_legacy_minimal_nlp_rows_need_no_structured_metadata() -> None:
    row = _term_row(
        {"atom_id": "legacy_nlp"},
        {"value": "legacy phrase", "can_fire_atom_alone": False},
        "NLP",
    )
    assert row == {
        "atom_id": "legacy_nlp",
        "terminology_system": "NLP",
        "value": "legacy phrase",
        "can_fire_atom_alone": False,
        "context_guard": None,
    }

    import spacy

    nlp = spacy.blank("en")
    matcher, labels = build_phrase_matcher(nlp, [row])
    matches = matcher(nlp("A legacy phrase is documented."))
    assert len(matches) == 1
    label = nlp.vocab.strings[matches[0][0]]
    assert labels[label]["value"] == "legacy phrase"


def test_structured_exact_lookup_ignores_evidence_role() -> None:
    legacy_source_config = load_source_config(profile="legacy_ehr_v1")
    events = expand_source_row(
        {
            "Member/PatientId": "p1",
            "DiagnosisCode": "I10",
            "DiagnosisType": "ICD10",
        },
        "claim",
        run_id="r",
        config_hash="h",
        source_config=legacy_source_config,
    )
    config = SimpleNamespace(
        tables={
            "atoms": [{"atom_id": "a"}],
            "terminology": [{
                "atom_id": "a",
                "terminology_system": "ICD10",
                "value": "I10",
                "match_mode": "EXACT",
                "mapping_role": "SUPPORTING",
                "can_fire_atom_alone": False,
            }],
        }
    )
    matches = match_atom_events(events, config, config_hash="h")
    assert len(matches) == 1
    assert matches[0].matched_config_value == "I10"


def test_multi_code_values_flatten_arrays_and_newlines() -> None:
    assert _split_declared_values(["I10\nI11", ["I12;I13"], None]) == [
        "I10", "I11", "I12", "I13"
    ]


def test_claim_expansion_is_strict_and_preserves_text_context() -> None:
    legacy_source_config = load_source_config(profile="legacy_ehr_v1")
    row = {
        "Member/PatientId": "p1",
        "ClaimId": "c1",
        "DiagnosisCode": ["I10", "I11.0\nI12"],
        "OtherDiagnosisCodes9": "250.00",
        "OtherDiagnosisCodes10": ["I13.0", "I14.0"],
        "ProcedureCode": "93000,93010",
        "DiagnosisType": "ICD-10-CM",
        "ClinicalNotes": "I10 documented",
    }
    events = expand_source_row(
        row, "claim", run_id="r", config_hash="h", source_config=legacy_source_config
    )
    code_events = [event for event in events if event.code_value]
    assert [(event.source_field, event.code_system, event.code_value) for event in code_events] == [
        ("diagnosis_code", "ICD10", "I10"),
        ("diagnosis_code", "ICD10", "I11.0"),
        ("diagnosis_code", "ICD10", "I12"),
        ("other_diagnosis_9", "ICD9", "250.00"),
        ("other_diagnosis_10", "ICD10", "I13.0"),
        ("other_diagnosis_10", "ICD10", "I14.0"),
        ("procedure_code", "CPT_HCPCS", "93000"),
        ("procedure_code", "CPT_HCPCS", "93010"),
    ]
    text_events = [event for event in events if event.text_value]
    assert len(text_events) == 1
    assert text_events[0].attributes["match_mode"] == "CODE_IN_TEXT"
    assert text_events[0].attributes["context_available"] is True


def test_lab_and_family_history_expand_code_arrays() -> None:
    legacy_source_config = load_source_config(profile="legacy_ehr_v1")
    lab = {
        "Member/PatientId": "p1",
        "LabId": "l1",
        "ObservationIdentifier": ["14957-5\n1848-9", "30003-8"],
        "ObservationIdentifierSystem": "LOINC",
        "ObservationValue": "2.1",
    }
    lab_events = expand_source_row(
        lab, "lab", run_id="r", config_hash="h", source_config=legacy_source_config
    )
    assert [event.code_value for event in lab_events if event.code_value] == [
        "14957-5", "1848-9", "30003-8"
    ]
    assert all(event.code_system == "LOINC" for event in lab_events if event.code_value)
    assert all(event.text_value is None for event in lab_events if event.code_value)
    family = {
        "Member/PatientId": "p1",
        "MedicalHistoryId": "f1",
        "SNOMED": ["1", "2\n3"],
        "Condition": "family history",
    }
    family_events = expand_source_row(
        family,
        "family_history",
        run_id="r",
        config_hash="h",
        source_config=legacy_source_config,
    )
    assert [event.code_value for event in family_events if event.code_value] == ["1", "2", "3"]
    assert all(event.text_value is None for event in family_events if event.code_value)
    assert all(event.experiencer_hint == "FAMILY_MEMBER" for event in family_events)


def test_undeclared_lab_identifier_is_not_assumed_to_be_loinc() -> None:
    legacy_source_config = load_source_config(profile="legacy_ehr_v1")
    events = expand_source_row(
        {
            "Member/PatientId": "p1",
            "LabId": "l1",
            "ObservationIdentifier": "14957-5",
            "ObservationValue": "2.1",
        },
        "lab",
        run_id="r",
        config_hash="h",
        source_config=legacy_source_config,
    )
    code_events = [event for event in events if event.code_value]
    assert len(code_events) == 1
    assert code_events[0].code_system is None
    assert code_events[0].attributes["observation_identifier_system_declared"] is False

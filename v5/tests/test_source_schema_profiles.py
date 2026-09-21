from __future__ import annotations

import json
from types import SimpleNamespace

from v5.pipeline import _fetch_candidate_source_rows
from v5.warehouse.source_schema import (
    DEFAULT_SOURCE_CONFIG_PATH,
    SOURCE_PROFILE_ENV,
    default_source_config,
    is_table_profile_enabled,
    is_table_profile_required,
    load_source_config,
)
from v5.extraction.source_events import expand_source_row
from v5.extraction.extraction_contract import event_system_compatible


def test_active_profile_is_strict_claims_only() -> None:
    config = default_source_config()

    assert config["profile"] == "claims_only_v1"
    assert config["available_profiles"] == ("claims_only_v1", "all_available_v1")
    assert set(config["tables"]) == {
        "census", "claim", "encounter", "lab", "surgical_history"
    }
    assert [key for key, table in config["tables"].items() if table["enabled"]] == ["claim"]

    profile_enabled = {
        key for key, table in config["tables"].items()
        if is_table_profile_enabled(table)
    }
    assert profile_enabled == {"claim"}
    assert {
        key for key, table in config["tables"].items()
        if is_table_profile_required(table)
    } == profile_enabled

    claim = config["tables"]["claim"]
    assert claim["name"] == "CLAIMS"
    assert claim["columns"]["patient_id"] == "PATIENTID"
    assert claim["columns"]["diagnosis_type"] == "DIAGNOSISTYPE"
    assert claim["columns"]["diagnosis_code"] == "DIAGNOSISCODE"
    assert claim["required_columns"] == ("patient_id", "diagnosis_type", "diagnosis_code")

    events = expand_source_row(
        {
            "PATIENTID": "member-1",
            "ENCOUNTERID": "visit-1",
            "DIAGNOSISTYPE": "ICD-10-CM",
            "DIAGNOSISCODE": "E85.81",
            "COLUMN19": "2026-01-02",
        },
        "claim",
        run_id="run",
        config_hash="hash",
        source_config=config,
    )
    diagnosis = [event for event in events if event.code_value == "E85.81"]
    assert len(diagnosis) == 1
    assert diagnosis[0].patient_id == "member-1"
    assert diagnosis[0].encounter_id == "visit-1"
    assert diagnosis[0].code_system == "ICD10"
    # Unmapped placeholder columns must not masquerade as claim dates.
    assert diagnosis[0].event_date is None
    assert diagnosis[0].source_table == "CLAIM"
    assert diagnosis[0].attributes["physical_table"] == "CLAIMS"
    assert event_system_compatible(
        diagnosis[0].source_table,
        diagnosis[0].source_field,
        "ICD10",
        diagnosis[0].code_system,
    )


def test_all_available_profile_uses_exactly_five_authorized_tables() -> None:
    config = load_source_config(profile="all_available_v1")

    assert config["profile"] == "all_available_v1"
    assert set(config["tables"]) == {
        "census", "claim", "encounter", "lab", "surgical_history"
    }
    assert {
        key for key, table in config["tables"].items() if table["enabled"]
    } == {"claim", "encounter", "lab", "surgical_history"}
    assert {
        key for key, table in config["tables"].items()
        if is_table_profile_enabled(table)
    } == set(config["tables"])
    assert "medication" not in config["tables"]
    assert "social_history" not in config["tables"]


def test_profile_can_be_selected_from_environment(monkeypatch) -> None:
    monkeypatch.setenv(SOURCE_PROFILE_ENV, "all_available_v1")

    assert default_source_config()["profile"] == "all_available_v1"


def test_profiled_file_contains_only_authorized_tables() -> None:
    payload = json.loads(
        DEFAULT_SOURCE_CONFIG_PATH.read_text(encoding="utf-8")
    )

    assert payload["active_profile"] == "claims_only_v1"
    assert set(payload["profiles"]) == {"claims_only_v1", "all_available_v1"}
    for profile in payload["profiles"].values():
        assert set(profile["tables"]) == {
            "census", "claim", "encounter", "lab", "surgical_history"
        }


def test_profile_toggle_helpers_parse_strict_values_and_remain_independent() -> None:
    table = {
        "key": "lab",
        "enabled": False,
        "required": False,
        "profile_enabled": "true",
        "profile_required": "false",
    }

    assert is_table_profile_enabled(table) is True
    assert is_table_profile_required(table) is False


def test_source_profile_environment_variable_is_v5_specific() -> None:
    assert SOURCE_PROFILE_ENV == "V5_SOURCE_SCHEMA_PROFILE"


def test_candidate_fetch_hydrates_profile_only_tables_without_enabling_detection() -> None:
    class Query:
        def __init__(self, rows):
            self.rows = rows

        def collect(self):
            return self.rows

    class Session:
        def __init__(self):
            self.sql_texts = []

        def sql(self, text, params=None):
            self.sql_texts.append(text)
            if '"CLAIMS"' in text:
                return Query([{"PATIENTID": "p1", "DIAGNOSISCODE": "E85.81"}])
            if '"LABS"' in text:
                return Query([{"COLUMN0": "p1", "COLUMN4": "BNP"}])
            return Query([])

    source_config = {
        "namespace": None,
        "tables": {
            "claim": {
                "key": "claim", "name": "CLAIMS", "enabled": True,
                "profile_enabled": True, "columns": {"patient_id": "PATIENTID", "diagnosis_code": "DIAGNOSISCODE"},
            },
            "lab": {
                "key": "lab", "name": "LABS", "enabled": False,
                "profile_enabled": True, "columns": {"patient_id": "COLUMN0"},
            },
        },
    }
    session = Session()
    rows = _fetch_candidate_source_rows(
        session,
        source_config,
        candidate_plan=[SimpleNamespace(sql="SELECT 'p1' AS PATIENT_ID", params=())],
    )

    assert rows["claim"][0]["DIAGNOSISCODE"] == "E85.81"
    assert rows["lab"][0]["COLUMN4"] == "BNP"
    assert any('"LABS"' in sql for sql in session.sql_texts)

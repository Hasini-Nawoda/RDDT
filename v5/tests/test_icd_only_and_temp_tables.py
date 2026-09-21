from __future__ import annotations

from types import SimpleNamespace

import pytest

from v4.extraction.atom_matching import match_atom_events
from v4.extraction.candidate_net import build_candidate_plan
from v4.extraction.extraction_contract import (
    event_system_compatible,
    normalize_terminology_mode,
)
from v4.extraction.source_events import expand_source_row
from v4.warehouse.snowflake_io import (
    SnowflakeIOError,
    assert_read_only_sql,
    create_run_table,
    insert_rows,
)
from v4.warehouse.source_schema import default_source_config


def test_icd_only_mode_matches_codes_without_an_nlp_runtime() -> None:
    config = SimpleNamespace(
        config_hash="hash",
        tables={
            "atoms": [{"atom_id": "a-icd"}, {"atom_id": "a-nlp"}],
            "terminology": [
                {
                    "atom_id": "a-icd",
                    "terminology_system": "ICD10",
                    "value": "E85.81",
                },
                {
                    "atom_id": "a-nlp",
                    "terminology_system": "NLP",
                    "value": "amyloidosis",
                },
            ],
        },
    )
    source_config = default_source_config()
    events = expand_source_row(
        {"PATIENTID": "member-1", "DIAGNOSISTYPE": "ICD-10-CM", "DIAGNOSISCODE": "E85.81"},
        "claim",
        run_id="run",
        config_hash="hash",
        source_config=source_config,
    )

    matches = match_atom_events(
        events,
        config,
        config_hash="hash",
        nlp=None,
        terminology_mode="ICD_ONLY",
    )

    assert [match.atom_id for match in matches] == ["a-icd"]
    assert event_system_compatible("CLAIM", "diagnosis_code", "ICD10", "ICD10")
    assert normalize_terminology_mode("icd-only") == "ICD_ONLY"


def test_icd_only_candidate_plan_excludes_nlp_terms() -> None:
    config = SimpleNamespace(
        config_hash="hash",
        tables={
            "terminology": [
                {"atom_id": "a-icd", "terminology_system": "ICD10", "value": "E85.81"},
                {"atom_id": "a-nlp", "terminology_system": "NLP", "value": "amyloidosis"},
            ]
        },
    )

    plan = build_candidate_plan(
        config,
        config_hash="hash",
        source_config=default_source_config(),
        terminology_mode="ICD_ONLY",
    )

    assert plan
    assert all(query.reason.terminology_system != "NLP" for query in plan)


class _Result:
    def collect(self):
        return []


class _Session:
    def __init__(self):
        self.calls = []

    def sql(self, sql, params=None):
        self.calls.append((sql, params))
        return _Result()


def test_pipeline_outputs_use_session_scoped_temporary_tables() -> None:
    session = _Session()

    create_run_table(session, "AMY_V4_SOURCE_EVENT", {"RUN_ID": "VARCHAR", "N": "NUMBER(10, 0)"})
    count = insert_rows(session, "AMY_V4_SOURCE_EVENT", ["RUN_ID", "N"], [("run", "1")])

    assert count == 1
    create_sql = session.calls[0][0]
    insert_sql = session.calls[1][0]
    assert "CREATE OR REPLACE TEMPORARY TABLE" in create_sql
    assert "TRANSIENT" not in create_sql.upper()
    assert "INSERT INTO" in insert_sql
    assert session.calls[1][1] == ("run", "1")


def test_read_only_query_guard_still_rejects_permanent_or_unapproved_writes() -> None:
    with pytest.raises(SnowflakeIOError):
        assert_read_only_sql("CREATE TABLE permanent_output (N NUMBER)")


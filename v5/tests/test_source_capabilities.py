from v5.source_capabilities import (
    AUTHORIZED_TABLE_KEYS,
    audit_terminology_coverage,
    capability_for,
)


def test_authoritative_table_boundary_has_exactly_five_tables() -> None:
    assert AUTHORIZED_TABLE_KEYS == (
        "census", "claim", "encounter", "lab", "surgical_history"
    )


def test_claims_only_treats_missing_context_as_unavailable_not_negative() -> None:
    assert capability_for("claims_only_v1", "ICD10").status == "AVAILABLE"
    assert capability_for("claims_only_v1", "NLP").status == "UNAVAILABLE_BY_SOURCE"
    assert capability_for("claims_only_v1", "EVENT_DATE").status == "UNAVAILABLE_BY_SOURCE"


def test_all_available_does_not_mislabel_local_labs_as_loinc() -> None:
    assert capability_for("all_available_v1", "LOINC").status == "UNAVAILABLE_BY_SOURCE"
    assert capability_for("all_available_v1", "LOCAL_LAB").status == "PARTIAL_CONTEXT"
    assert capability_for("all_available_v1", "SNOMED CT").status == "AVAILABLE"


def test_coverage_audit_is_an_overlay_not_a_config_rewrite() -> None:
    audit = audit_terminology_coverage(
        [
            {"atom_id": "a", "terminology_system": "ICD10"},
            {"atom_id": "a", "terminology_system": "NLP"},
            {"atom_id": "b", "terminology_system": "LOINC"},
        ],
        profile="claims_only_v1",
    )

    assert audit["term_counts_by_status"] == {
        "AVAILABLE": 1,
        "UNAVAILABLE_BY_SOURCE": 2,
    }
    assert audit["atom_counts_by_status"] == {
        "AVAILABLE": 1,
        "UNAVAILABLE_BY_SOURCE": 2,
    }
    assert audit["clinical_config_modified"] is False

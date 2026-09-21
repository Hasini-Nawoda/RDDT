from copy import deepcopy
from types import SimpleNamespace

from v4.config_loader import load_phenotype_configs
from v4.extraction.atom_matching import AtomMatch
from v4.extraction.evidence_qualification import qualify_atom_matches
from v4.pipeline import run_attr_reference_pipeline
from v4.pipeline_steps.step_03_source_events import build_source_events
from v4.reasoning.priority import resolve_priority
from v4.reasoning.signal_engine import evaluate_signals
from v4.warehouse.source_schema import load_source_config


def _claim_match(*, available_date=None):
    return AtomMatch(
        "run",
        "patient",
        "A",
        "claim-event",
        "EXACT_NORMALIZED_CODE",
        "G60.8",
        "G60.8",
        "TRUE",
        None,
        available_date,
        "claim:lineage",
        encounter_id="encounter-1",
        source_attributes={"table_key": "claim"},
    )


def test_claims_recall_relaxes_missing_date_but_strict_does_not():
    config = SimpleNamespace(tables={"atoms": [{"atom_id": "A", "stage": "PRETEST_SIGNAL"}]})

    strict = qualify_atom_matches(
        [_claim_match()],
        config,
        screening_cutoff="2026-09-21",
    )[0]
    recall = qualify_atom_matches(
        [_claim_match()],
        config,
        screening_cutoff="2026-09-21",
        evaluation_mode="CLAIMS_RECALL",
    )[0]

    assert strict.status == "UNKNOWN"
    assert strict.reason == "UNKNOWN_AVAILABILITY_DATE"
    assert recall.status == "TRUE"
    assert recall.provisional is True
    assert "MISSING_AVAILABILITY_DATE" in recall.relaxations
    assert "MISSING_REQUIRED_STAGE:PRETEST_SIGNAL" in recall.relaxations


def test_claims_recall_never_relaxes_an_after_cutoff_code():
    config = SimpleNamespace(tables={"atoms": [{"atom_id": "A"}]})
    evidence = qualify_atom_matches(
        [_claim_match(available_date="2026-10-01")],
        config,
        screening_cutoff="2026-09-21",
        evaluation_mode="CLAIMS_RECALL",
    )[0]

    assert evidence.status == "UNKNOWN"
    assert evidence.reason == "AFTER_SCREENING_CUTOFF"
    assert evidence.provisional is False
    assert evidence.relaxations == []


def test_nlp_precedence_still_suppresses_a_provisional_claim_code():
    config = SimpleNamespace(tables={"atoms": [{"atom_id": "A", "stage": "PRETEST_SIGNAL"}]})
    narrative = AtomMatch(
        "run", "patient", "A", "note-event", "PHRASEMATCHER",
        "neuropathy", "neuropathy", "TRUE", None, None,
        "note:lineage",
        source_attributes={"table_key": "clinical_note"},
    )

    evidence = qualify_atom_matches(
        [_claim_match(), narrative],
        config,
        screening_cutoff="2026-09-21",
        evaluation_mode="CLAIMS_RECALL",
    )
    code = next(row for row in evidence if row.source_provenance["match_method"] == "EXACT_NORMALIZED_CODE")

    assert code.status == "UNKNOWN"
    assert code.reason == "NLP_PRECEDENCE_CODE_SUPPRESSED"
    assert code.provisional is False
    assert code.relaxations == []


def _qualified_claim(*, persistent_marker):
    attributes = {
        "table_key": "claim",
        "match_method": "EXACT_NORMALIZED_CODE",
    }
    if persistent_marker is not None:
        attributes["persistent"] = persistent_marker
    return {
        "patient_id": "patient",
        "evidence_id": "evidence-A",
        "atom_id": "A",
        "status": "TRUE",
        "support_lineage_ids": ("claim:lineage",),
        "attributes": attributes,
        "source_provenance": {
            "match_method": "EXACT_NORMALIZED_CODE",
            "source_table": "claim",
        },
    }


def _qualified_signal_config():
    return SimpleNamespace(
        config_hash="cfg",
        tables={
            "signals": [{
                "signal_id": "S1",
                "enabled": True,
                "reasoning_bucket": "RENAL",
                "tier": 1,
                "runtime_executability": "EXECUTABLE",
            }],
            "signal_atoms": [{
                "signal_id": "S1",
                "atom_id": "A",
                "can_fire_from_mapping": True,
            }],
            "signal_rules": [{"signal_id": "S1", "root_group_id": "G1"}],
            "signal_rule_groups": [{
                "signal_id": "S1",
                "group_id": "G1",
                "operator": "ALL",
            }],
            "signal_rule_members": [{
                "signal_id": "S1",
                "group_id": "G1",
                "member_type": "ATOM",
                "member_id": "A",
                "required_attributes": "persistent=True",
            }],
            "signal_blockers": [],
        },
    )


def test_claims_recall_relaxes_missing_context_but_not_observed_false_context():
    config = _qualified_signal_config()
    missing = evaluate_signals(
        config,
        [_qualified_claim(persistent_marker=None)],
        patient_id="patient",
        phenotype="TEST",
        evaluation_mode="CLAIMS_RECALL",
    )[0]
    observed_false = evaluate_signals(
        config,
        [_qualified_claim(persistent_marker=False)],
        patient_id="patient",
        phenotype="TEST",
        evaluation_mode="CLAIMS_RECALL",
    )[0]

    assert missing["status"] == "TRUE"
    assert missing["provisional"] is True
    assert "MISSING_REQUIRED_QUALIFIER:persistent" in missing["relaxations"]
    assert observed_false["status"] == "FALSE"
    assert observed_false["provisional"] is False


def test_support_only_mapping_relaxation_is_limited_to_native_claim_codes():
    config = SimpleNamespace(
        config_hash="cfg",
        tables={
            "signals": [{
                "signal_id": "S1",
                "enabled": True,
                "reasoning_bucket": "RENAL",
                "tier": 1,
                "runtime_executability": "EXECUTABLE",
            }],
            "signal_atoms": [{
                "signal_id": "S1",
                "atom_id": "A",
                "can_fire_from_this_mapping": False,
            }],
            "signal_rules": [],
            "signal_rule_groups": [],
            "signal_rule_members": [],
            "signal_blockers": [],
        },
    )
    claim = _qualified_claim(persistent_marker=None)
    narrative = _qualified_claim(persistent_marker=None)
    narrative["attributes"] = {
        "table_key": "clinical_note",
        "match_method": "PHRASEMATCHER",
    }
    narrative["source_provenance"] = {
        "match_method": "PHRASEMATCHER",
        "source_table": "clinical_note",
    }

    claim_signal = evaluate_signals(
        config, [claim], patient_id="patient", phenotype="TEST",
        evaluation_mode="CLAIMS_RECALL",
    )[0]
    narrative_signal = evaluate_signals(
        config, [narrative], patient_id="patient", phenotype="TEST",
        evaluation_mode="CLAIMS_RECALL",
    )[0]

    assert claim_signal["status"] == "TRUE"
    assert claim_signal["provisional"] is True
    assert narrative_signal["status"] == "UNKNOWN"
    assert narrative_signal["provisional"] is False


def test_claims_only_attr_route_is_review_candidate_not_strict_pass():
    configs = load_phenotype_configs(
        ("ATTRV", "ATTRWT", "AL"),
        bundle_dir="v4/config",
    )
    source_config = load_source_config("v4/config/source_schema.json")
    rows = {
        "claim": [
            {"PATIENTID": "P1", "ENCOUNTERID": "E1", "DIAGNOSISTYPE": "ICD-10-CM", "DIAGNOSISCODE": "G60.8"},
            {"PATIENTID": "P1", "ENCOUNTERID": "E2", "DIAGNOSISTYPE": "ICD-10-CM", "DIAGNOSISCODE": "G90.8"},
        ]
    }

    strict = run_attr_reference_pipeline(
        rows,
        configs=configs,
        source_config=source_config,
        screening_cutoff="2026-09-21",
        include_profiles=False,
    )
    recall = run_attr_reference_pipeline(
        rows,
        configs=configs,
        source_config=source_config,
        screening_cutoff="2026-09-21",
        include_profiles=True,
        evaluation_mode="CLAIMS_RECALL",
    )

    strict_attrv = next(row for row in strict.router_output if row["phenotype"] == "ATTRV")
    recall_attrv = next(row for row in recall.router_output if row["phenotype"] == "ATTRV")
    assert strict_attrv["status"] != "PHENOTYPE_PASS"
    assert recall_attrv["status"] == "CLAIMS_RECALL_CANDIDATE"
    assert recall_attrv["provisional"] is True
    assert recall.patient_profiles[0]["diagnosis_state"] == "CLAIMS_RECALL_CANDIDATE"


def test_exact_amyloidosis_codes_remain_date_independent_before_recall_screening():
    configs = load_phenotype_configs(
        ("ATTRV", "ATTRWT", "AL"),
        bundle_dir="v4/config",
    )
    source_config = load_source_config("v4/config/source_schema.json")
    rows = {
        "claim": [
            {"PATIENTID": "ATTR", "ENCOUNTERID": "E1", "DIAGNOSISTYPE": "ICD-10-CM", "DIAGNOSISCODE": "E85.82"},
            {"PATIENTID": "AL", "ENCOUNTERID": "E2", "DIAGNOSISTYPE": "ICD-10-CM", "DIAGNOSISCODE": "E85.81"},
        ]
    }

    result = run_attr_reference_pipeline(
        rows,
        configs=configs,
        source_config=source_config,
        screening_cutoff="2026-09-21",
        include_profiles=False,
        evaluation_mode="CLAIMS_RECALL",
    )

    assert {row.patient_id for row in result.known_attr_patients} == {"ATTR"}
    assert {row.patient_id for row in result.known_al_patients} == {"AL"}
    assert result.router_output == []


def test_named_al_priority_policy_resolves_directly():
    config = SimpleNamespace(
        config_hash="cfg",
        tables={
            "priority_policies": [{
                "priority_policy_id": "AL_PRI_A",
                "kind": "NAMED_ROUTE",
                "class": "A",
            }]
        },
    )

    priority = resolve_priority(
        config,
        {"priority_policy_id": "AL_PRI_A"},
    )

    assert priority["status"] == "TRUE"
    assert priority["priority_class"] == "A"


def test_population_ledger_keeps_non_candidates_and_all_three_disease_verdicts():
    configs = load_phenotype_configs(
        ("ATTRV", "ATTRWT", "AL"),
        bundle_dir="v4/config",
    )
    source_config = load_source_config("v4/config/source_schema.json")
    rows = {
        "claim": [
            {"PATIENTID": "P1", "ENCOUNTERID": "E1", "DIAGNOSISTYPE": "ICD-10-CM", "DIAGNOSISCODE": "G60.8"},
            {"PATIENTID": "P1", "ENCOUNTERID": "E2", "DIAGNOSISTYPE": "ICD-10-CM", "DIAGNOSISCODE": "G90.8"},
        ]
    }

    result = run_attr_reference_pipeline(
        rows,
        configs=configs,
        source_config=source_config,
        candidate_patient_ids={"P1"},
        population_patient_ids={"P1", "P2"},
        screening_cutoff="2026-09-21",
        include_profiles=False,
        evaluation_mode="CLAIMS_RECALL",
    )

    ledger = {row["patient_id"]: row for row in result.patient_verdicts}
    assert set(ledger) == {"P1", "P2"}
    assert ledger["P1"]["attr_status"] == "ATTR_CLAIMS_RECALL_CANDIDATE"
    assert ledger["P1"]["attrv_status"] == "CLAIMS_RECALL_CANDIDATE"
    assert ledger["P1"]["al_status"] in {
        "CLAIMS_RECALL_CANDIDATE", "NO_MATCH", "HOLD", "UNKNOWN"
    }
    assert ledger["P2"]["population_status"] == "NO_CONFIGURED_CANDIDATE_EVIDENCE"
    assert ledger["P2"]["attr_status"] == "NO_CANDIDATE_EVIDENCE"
    assert ledger["P2"]["al_status"] == "NO_CANDIDATE_EVIDENCE"


def test_encounter_dates_enrich_claims_only_when_encounter_source_is_enabled():
    source_config = load_source_config("v4/config/source_schema.json")
    all_table_config = deepcopy(source_config)
    all_table_config["tables"]["encounter"]["enabled"] = True
    rows = {
        "claim": [{
            "PATIENTID": "P1", "ENCOUNTERID": "E1",
            "DIAGNOSISTYPE": "ICD-10-CM", "DIAGNOSISCODE": "G60.8",
        }],
        "encounter": [{
            "PATIENTID": "P1", "VISITID": "E1", "VISITDATE": "2025-01-02",
        }],
    }

    claims_only = build_source_events(
        rows,
        run_id="claims",
        config_hash="cfg",
        source_config=source_config,
    )
    all_tables = build_source_events(
        rows,
        run_id="all",
        config_hash="cfg",
        source_config=all_table_config,
    )

    claims_event = next(row for row in claims_only if row.source_table == "CLAIM")
    enriched_event = next(row for row in all_tables if row.source_table == "CLAIM")
    assert claims_event.available_date is None
    assert enriched_event.event_date == "2025-01-02"
    assert enriched_event.available_date == "2025-01-02"
    assert enriched_event.attributes["date_enrichment_source"] == "ENCOUNTER"


def test_all_table_encounter_dates_restore_strict_longitudinal_route():
    configs = load_phenotype_configs(
        ("ATTRV", "ATTRWT", "AL"),
        bundle_dir="v4/config",
    )
    source_config = deepcopy(load_source_config("v4/config/source_schema.json"))
    source_config["tables"]["encounter"]["enabled"] = True
    rows = {
        "claim": [
            {"PATIENTID": "P1", "ENCOUNTERID": "E1", "DIAGNOSISTYPE": "ICD-10-CM", "DIAGNOSISCODE": "G60.8"},
            {"PATIENTID": "P1", "ENCOUNTERID": "E2", "DIAGNOSISTYPE": "ICD-10-CM", "DIAGNOSISCODE": "G90.8"},
        ],
        "encounter": [
            {"PATIENTID": "P1", "VISITID": "E1", "VISITDATE": "2024-01-01"},
            {"PATIENTID": "P1", "VISITID": "E2", "VISITDATE": "2024-02-01"},
        ],
    }

    result = run_attr_reference_pipeline(
        rows,
        configs=configs,
        source_config=source_config,
        screening_cutoff="2026-09-21",
        include_profiles=False,
    )

    attrv = next(row for row in result.router_output if row["phenotype"] == "ATTRV")
    assert attrv["status"] == "PHENOTYPE_PASS"
    assert attrv["provisional"] is False
    assert result.patient_verdicts[0]["attr_status"] == "ATTR_SUSPICION"

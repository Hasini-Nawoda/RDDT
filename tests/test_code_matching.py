from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from v4.extraction.atom_matching import match_atom_events
from v4.extraction.candidate_net import build_candidate_plan
from v4.config_loader import load_phenotype_configs
from v4.extraction.code_semantics import expanded_values, find_code_in_text, match_code_value, term_match_mode
from v4.extraction.evidence_qualification import qualify_atom_matches
from v4.extraction.atom_matching import AtomMatch
from v4.extraction.source_events import SourceEvent
from v4_build_tools.terminology_normalization import expand_source_term, source_terminology


def _term(system: str, value: str, **extra):
    return {"atom_id": "A", "terminology_system": system, "value": value, **extra}


def _event(*, code=None, text=None, field="diagnosis_code", system="ICD10"):
    return SourceEvent(
        run_id="r", patient_id="p", encounter_id=None, source_table="CLAIM",
        source_record_id="row", event_date="2025-01-01", available_date="2025-01-01",
        source_specialty=None, source_field=field, code_system=system, code_value=code,
        text_value=text, result_value=None, result_status=None, experiencer_hint="PATIENT",
        raw_row_hash="hash", config_hash="cfg",
    )


def test_icd_dotted_dotless_equality_without_implicit_descendant():
    term = _term("ICD10", "I50.1")
    assert match_code_value("i501", term)[0]
    assert match_code_value("I50.1", term)[0]
    assert not match_code_value("I50.10", term)[0]
    assert match_code_value("I50", _term("ICD10", "I50"))[0]


def test_code_system_aliases_do_not_change_exact_code_semantics():
    assert find_code_in_text("I10", _term("ICD-10-CM", "I10", match_in_text=True))
    assert find_code_in_text("1234-5", _term("LOINC", "1234-5", match_in_text=True))
    assert not find_code_in_text("12345", _term("LOINC", "1234-5", match_in_text=True))


def test_prefix_authoring_requires_explicit_exact_members():
    prefix = _term("ICD10", "I50.", match_mode="PREFIX")
    assert not match_code_value("I50.9", prefix)[0]
    reviewed = _term("ICD10", "I50.", match_mode="PREFIX", expanded_values=["I50.9", "I50.1"])
    assert match_code_value("I50.9", reviewed)[0]
    assert match_code_value("I501", reviewed)[0]
    assert not match_code_value("I50.2", reviewed)[0]
    assert not match_code_value("I50.1", _term("ICD10", "I50"))[0]
    assert not match_code_value("I509", _term("ICD10", "I50", match_mode="PREFIX"))[0]


def test_explicit_icd_prefix_fallback_is_second_stage_only():
    legacy = _term("ICD10", "I42.", match_mode="PREFIX")
    assert not match_code_value("I42.7", legacy)[0]
    assert not find_code_in_text("I42.7", {**legacy, "match_in_text": True})

    fallback = _term(
        "ICD10", "I42.", match_mode="PREFIX_FALLBACK", match_in_text=True,
    )
    assert match_code_value("I42.7", fallback) == (True, "PREFIX_FALLBACK")
    assert match_code_value("I427", fallback) == (True, "PREFIX_FALLBACK")
    assert not match_code_value("I42.", fallback)[0]
    assert not match_code_value("I42", fallback)[0]
    assert find_code_in_text("documented I42.7", fallback)
    assert find_code_in_text("documented I427", fallback)
    assert not find_code_in_text("I42.", fallback)
    assert not find_code_in_text("XI42.7Y", fallback)
    assert not find_code_in_text("I42.7.0", fallback)
    assert not find_code_in_text("I42. (cardiomyopathy)", fallback)
    assert not find_code_in_text("I42.7-I42.8", fallback)

    reviewed = _term(
        "ICD10", "I42.", match_mode="PREFIX_FALLBACK", match_in_text=True,
        expanded_values=["I42.0"],
    )
    assert match_code_value("I42.0", reviewed) == (True, "EXACT")
    assert match_code_value("I42.7", reviewed) == (True, "PREFIX_FALLBACK")


def test_prefix_fallback_is_icd_only_and_candidate_retrieval_is_broad():
    for system in ("LOINC", "CPT_HCPCS", "SNOMED_CT"):
        term = _term(system, "I42.", match_mode="PREFIX_FALLBACK", match_in_text=True)
        assert not match_code_value("I42.7", term)[0]
        assert not find_code_in_text("I42.7", term)
    config = SimpleNamespace(
        config_hash="cfg",
        tables={"terminology": [_term("ICD10", "I42.", match_mode="PREFIX_FALLBACK", match_in_text=True)]},
    )
    plan = build_candidate_plan(config, config_hash="cfg")
    structured = [query for query in plan if query.match_strategy == "PREFIX_FALLBACK_CODE"]
    narrative = [query for query in plan if query.match_strategy == "CODE_IN_TEXT"]
    assert structured and all(query.params == () and "LIKE" not in query.sql.upper() for query in structured)
    assert narrative


def test_atom_matcher_emits_explicit_prefix_fallback_for_structured_and_text():
    config = SimpleNamespace(
        config_hash="cfg",
        tables={
            "atoms": [{"atom_id": "A"}],
            "terminology": [_term("ICD10", "I42.", match_mode="PREFIX_FALLBACK", match_in_text=True)],
        },
    )
    matches = match_atom_events(
        [_event(code="I42.7"), _event(code=None, text="Narrative documents I42.7", system=None)],
        config,
        config_hash="cfg",
    )
    assert any(match.match_method == "PREFIX_FALLBACK_CODE" for match in matches)
    assert any(match.match_method == "CODE_IN_TEXT" for match in matches)


def test_exact_member_wins_when_prefix_fallback_row_precedes_it():
    config = SimpleNamespace(
        config_hash="cfg",
        tables={
            "atoms": [{"atom_id": "A"}],
            "terminology": [
                _term("ICD10", "I42.", match_mode="PREFIX_FALLBACK"),
                _term("ICD10", "I42.7", match_mode="EXACT"),
            ],
        },
    )
    matches = match_atom_events([_event(code="I42.7")], config, config_hash="cfg")
    code_matches = [match for match in matches if match.atom_id == "A"]
    assert len(code_matches) == 1
    assert code_matches[0].match_method == "EXACT_NORMALIZED_CODE"
    assert code_matches[0].matched_config_value == "I42.7"


def test_exact_text_member_wins_when_prefix_fallback_row_precedes_it():
    config = SimpleNamespace(
        config_hash="cfg",
        tables={
            "atoms": [{"atom_id": "A"}],
            "terminology": [
                _term("ICD10", "I42.", match_mode="PREFIX_FALLBACK", match_in_text=True),
                _term("ICD10", "I42.7", match_mode="EXACT", match_in_text=True),
            ],
        },
    )
    matches = match_atom_events(
        [_event(code=None, text="Narrative documents I42.7", field="note_text", system=None)],
        config,
        config_hash="cfg",
    )
    code_matches = [match for match in matches if match.atom_id == "A"]
    assert len(code_matches) == 1
    assert code_matches[0].match_method == "CODE_IN_TEXT"
    assert code_matches[0].matched_config_value == "I42.7"


def test_icd_dotted_and_dotless_text_aliases_are_exact_only():
    dotted = _term("ICD10", "I50.1", match_in_text=True)
    dotless = _term("ICD10", "I501", match_in_text=True)
    assert find_code_in_text("coded I50.1", dotted)
    assert find_code_in_text("coded I501", dotted)
    assert find_code_in_text("coded I50.1", dotless)
    assert not find_code_in_text("coded I50.10", dotted)
    assert not find_code_in_text("coded I5010", dotted)


def test_non_icd_codes_are_exact_and_preserve_leading_zeroes():
    assert match_code_value("00123", _term("CPT_HCPCS", "00123"))[0]
    assert not match_code_value("123", _term("CPT_HCPCS", "00123"))[0]
    assert match_code_value("49436004", _term("SNOMED_CT", "49436004"))[0]
    assert not match_code_value("49436004.0", _term("SNOMED_CT", "49436004"))[0]
    assert match_code_value("1234-5", _term("LOINC", "1234-5"))[0]
    assert not match_code_value("12345", _term("LOINC", "1234-5"))[0]


def test_range_authoring_requires_explicit_exact_members():
    term = _term("CPT_HCPCS", "33206-33208")
    assert not match_code_value("33206", term)[0]
    reviewed = _term(
        "CPT_HCPCS", "33206-33208", match_mode="RANGE",
        expanded_values=["33206", "33207", "33208"],
    )
    assert match_code_value("33206", reviewed)[0]
    assert match_code_value("33207", reviewed)[0]
    assert match_code_value("33208", reviewed)[0]
    assert not match_code_value("33209", reviewed)[0]
    assert not match_code_value("33206-33208", _term("ICD10", "I44.1-I44.3"))[0]
    assert not match_code_value("I44.1-I44.3", _term("ICD10", "I44.1-I44.3", match_mode="EXACT"))[0]
    assert not match_code_value("33206-33208", _term("CPT_HCPCS", "33206-33208", match_mode="EXACT"))[0]


def test_migrated_runtime_expansions_are_exact_members_only():
    """The migrated runtime contains only discrete exact structured members."""
    for config in load_phenotype_configs(("ATTRV", "ATTRWT")).values():
        structured = [row for row in config.rows("terminology") if row.get("terminology_system") != "NLP"]
        assert structured
        exact_rows = [row for row in structured if term_match_mode(row) != "PREFIX_FALLBACK"]
        assert all(term_match_mode(row) == "EXACT" for row in exact_rows)
        assert all(not str(row.get("value", "")).endswith(".") for row in exact_rows)
        assert {
            (row.get("atom_id"), row.get("value"))
            for row in structured if term_match_mode(row) == "PREFIX_FALLBACK"
        } == {
            ("af", "I48."),
            ("conduction_disease", "I44."),
            ("conduction_disease", "I45."),
            ("thick_walls", "I42."),
        }
        # Hyphens are valid LOINC identifier/check-digit punctuation.  Other
        # hyphenated authored range literals must not survive migration as
        # runtime structured rows.
        assert all(
            "-" not in str(row.get("value", ""))
            or str(row.get("terminology_system", "")).upper() == "LOINC"
            for row in structured
        )


def test_migrated_runtime_expands_m65_and_confirmed_cpt_ranges():
    """Check the known ICD expansion and confirmed exact CPT members."""
    rows = {
        (row.get("atom_id"), row.get("value"))
        for config in load_phenotype_configs(("ATTRV", "ATTRWT")).values()
        for row in config.rows("terminology")
        if row.get("terminology_system") == "ICD10"
    }
    expected_m65 = {
        "M65.30", "M65.311", "M65.312", "M65.319", "M65.321", "M65.322", "M65.329",
        "M65.331", "M65.332", "M65.339", "M65.341", "M65.342", "M65.349", "M65.351",
        "M65.352", "M65.359",
    }
    assert {value for atom, value in rows if atom == "trigger_finger"} >= expected_m65
    cpt_values = {
        row.get("value")
        for config in load_phenotype_configs(("ATTRV", "ATTRWT")).values()
        for row in config.rows("terminology")
        if row.get("terminology_system") == "CPT_HCPCS"
    }
    assert {"81404", "81405", "96365", "96366", "96367", "96368", "72195", "72196", "72197"} <= cpt_values
    assert not {"81404-81405", "96365-96368", "72195-72197"} & cpt_values


def test_source_union_has_complete_materialized_runtime_coverage():
    """Every source/HEAD structured row is represented by an exact runtime row."""
    source_terms, exact_values = source_terminology()
    expected = set()
    for (atom_id, system, _), source_term in source_terms.items():
        if system == "NLP":
            continue
        expanded, _ = expand_source_term(source_term, exact_values=exact_values)
        assert expanded, (atom_id, system, source_term.get("Value"))
        expected.update((atom_id, system, str(row.get("Value", row.get("value", "")))) for row in expanded)
    runtime = {
        (str(row.get("atom_id")), str(row.get("terminology_system")), str(row.get("value")))
        for config in load_phenotype_configs(("ATTRV", "ATTRWT")).values()
        for row in config.rows("terminology")
        if row.get("terminology_system") != "NLP" and term_match_mode(row) != "PREFIX_FALLBACK"
    }
    assert runtime == expected


def test_runtime_preserves_only_the_four_operational_icd_prefix_fallbacks():
    expected = {
        ("af", "I48."),
        ("conduction_disease", "I44."),
        ("conduction_disease", "I45."),
        ("thick_walls", "I42."),
    }
    root = Path(__file__).resolve().parents[1]
    actual = set()
    for path in (root / "v4" / "config" / "shared" / "atoms").glob("*.json"):
        for atom in json.loads(path.read_text(encoding="utf-8"))["atoms"]:
            for fallback in atom.get("extraction", {}).get("code_prefix_fallbacks", []) or []:
                assert fallback["match_mode"] == "PREFIX_FALLBACK"
                assert fallback["terminology_system"] == "ICD10"
                actual.add((atom["atom_id"], fallback["prefix"]))
            for terms in atom.get("extraction", {}).get("codes", {}).values():
                assert all(term.get("match_mode") == "EXACT" for term in terms)
    assert actual == expected


def test_migrated_expanded_member_emits_once_per_atom_mention():
    """Exact and expanded rows for one reviewed member must not double-count."""
    for config in load_phenotype_configs(("ATTRV", "ATTRWT")).values():
        structured = match_atom_events(
            [_event(code="M65.30", system="ICD10")], config, config_hash=config.config_hash
        )
        narrative = match_atom_events(
            [_event(code=None, text="documented M65.30", field="note_text", system=None)],
            config,
            config_hash=config.config_hash,
        )
        for matches in (structured, narrative):
            code_matches = [
                match for match in matches
                if match.match_method in {
                    "EXACT_NORMALIZED_CODE", "PREFIX_NORMALIZED_CODE",
                    "RANGE_NORMALIZED_CODE", "CODE_IN_TEXT",
                }
            ]
            keys = {
                (
                    match.atom_id,
                    str(match.matched_source_value).upper(),
                    match.span_start,
                    match.span_end,
                    tuple(sorted((str(k), repr(v)) for k, v in match.config_restriction.items())),
                )
                for match in code_matches
            }
            assert len(keys) == len(code_matches)


def test_code_in_text_has_strong_numeric_and_icd_boundaries():
    term = _term("ICD10", "I50.1", match_in_text=True)
    assert [span.value for span in find_code_in_text("History: I50.1.", term)] == ["I50.1"]
    assert not find_code_in_text("identifier XI50.1Y", term)
    assert not find_code_in_text("I50.10", term)
    assert not find_code_in_text("I50.1", _term("ICD10", "I50", match_in_text=True))
    explicit_range = _term(
        "CPT_HCPCS", "33206-33208", match_in_text=True,
        expanded_values=["33206", "33207", "33208"],
    )
    assert find_code_in_text("Procedure 33207 documented", explicit_range)
    assert not find_code_in_text("measurement 33207.0", _term("CPT_HCPCS", "33207", match_in_text=True))


def test_code_in_text_rejects_prefix_descriptions_and_range_literals():
    prefix = _term("ICD10", "I50.", match_mode="PREFIX", match_in_text=True)
    reviewed_prefix = _term(
        "ICD10", "I50.", match_mode="PREFIX", match_in_text=True,
        expanded_values=["I50.1"],
    )
    authored_range = _term("ICD10", "I44.1-I44.3", match_in_text=True)
    unresolved_cpt_range = _term("CPT_HCPCS", "33206-33208", match_mode="RANGE", match_in_text=True)
    explicit_cpt_range = _term(
        "CPT_HCPCS", "33206-33208", match_mode="RANGE", match_in_text=True,
        expanded_values=["33206", "33207", "33208"],
    )
    assert not find_code_in_text("I50.1", prefix)
    assert find_code_in_text("I50.1", reviewed_prefix)
    assert not find_code_in_text("I50.10", reviewed_prefix)
    assert not find_code_in_text("I50. (heart failure family)", prefix)
    assert not find_code_in_text("I44.1-I44.3", authored_range)
    assert not find_code_in_text("range 33206-33208", unresolved_cpt_range)
    assert not find_code_in_text("range 33206-33208", explicit_cpt_range)
    assert not find_code_in_text("procedure 33207", unresolved_cpt_range)
    assert not find_code_in_text("heart failure", _term("ICD10", "heart failure", match_in_text=True))
    assert not find_code_in_text("joint pain", _term("SNOMED_CT", "joint pain", match_in_text=True))


def test_loinc_requires_complete_hyphenated_identifier():
    term = _term("LOINC", "1234-5", match_in_text=True, match_mode="RANGE")
    assert find_code_in_text("LOINC 1234-5", term)
    assert not find_code_in_text("LOINC 12345", term)
    assert not find_code_in_text("LOINC 1234-", term)
    assert not find_code_in_text("LOINC 1234-5.0", term)


def test_nlp_terms_never_enter_structured_code_text_matching():
    config = SimpleNamespace(
        config_hash="cfg",
        tables={"atoms": [{"atom_id": "A"}], "terminology": [
            _term("NLP", "I50.1", match_in_text=True, match_mode="PREFIX"),
        ]},
    )
    matches = match_atom_events(
        [_event(code=None, text="Narrative contains I50.1")], config, config_hash="cfg"
    )
    assert not [match for match in matches if match.match_method == "CODE_IN_TEXT"]


def test_atom_matcher_emits_code_in_text_and_structured_exact_matches():
    config = SimpleNamespace(
        config_hash="cfg",
        tables={
            "atoms": [{"atom_id": "A"}],
            "terminology": [_term("ICD10", "I50.1", match_in_text=True)],
        },
    )
    matches = match_atom_events(
        [_event(code="I501", text="Narrative also records I50.1.")],
        config,
        config_hash="cfg",
    )
    assert {row.match_method for row in matches} == {"EXACT_NORMALIZED_CODE", "CODE_IN_TEXT"}


def test_atom_matcher_labels_explicit_prefix_and_range_modes():
    config = SimpleNamespace(
        config_hash="cfg",
        tables={
            "atoms": [{"atom_id": "A"}],
            "terminology": [
                _term("ICD10", "I50.", match_mode="PREFIX", expanded_values=["I50.9"]),
                _term("CPT_HCPCS", "33206-33208", match_mode="RANGE", expanded_values=["33207"]),
            ],
        },
    )
    events = [
        _event(code="I509"),
        _event(code="33207", field="procedure_code", system="CPT_HCPCS"),
    ]
    matches = match_atom_events(events, config, config_hash="cfg")
    assert {row.match_method for row in matches} == {
        "PREFIX_NORMALIZED_CODE", "RANGE_NORMALIZED_CODE",
    }
    assert all(row.config_restriction["mapping_role"] is None for row in matches)


def test_atom_matcher_does_not_emit_prefix_or_authored_range_text_matches():
    config = SimpleNamespace(
        config_hash="cfg",
        tables={"atoms": [{"atom_id": "A"}], "terminology": [
            _term("ICD10", "I50.", match_mode="PREFIX", match_in_text=True),
            _term("ICD10", "I44.1-I44.3", match_in_text=True),
            _term("ICD10", "heart failure", match_in_text=True),
        ]},
    )
    event = _event(code=None, text="I50.1 is a descendant; I44.1-I44.3 is an authored range.")
    assert not [match for match in match_atom_events([event], config, config_hash="cfg")
                if match.match_method == "CODE_IN_TEXT"]


def test_candidate_reason_preserves_mapping_role():
    config = SimpleNamespace(
        config_hash="cfg",
        tables={"terminology": [_term("CPT_HCPCS", "00123", mapping_role="SUPPORTING")]},
    )
    plan = build_candidate_plan(config, config_hash="cfg")
    assert plan
    assert plan[0].reason.mapping_role == "SUPPORTING"


def test_candidate_plan_contains_code_in_text_scan_with_metadata():
    config = SimpleNamespace(
        config_hash="cfg",
        tables={"terminology": [_term("ICD10", "I50.1", match_in_text=True)]},
    )
    plan = build_candidate_plan(config, config_hash="cfg")
    code_text = [query for query in plan if query.match_strategy == "CODE_IN_TEXT"]
    assert code_text
    assert any(reason.config_value == "I50.1" for query in code_text for reason in query.reasons)
    assert all(query.params == () for query in code_text)


def test_candidate_plan_skips_non_exact_narrative_modes():
    config = SimpleNamespace(
        config_hash="cfg",
        tables={"terminology": [
            _term("ICD10", "I50.", match_mode="PREFIX", match_in_text=True),
            _term("ICD10", "I44.1-I44.3", match_in_text=True),
            _term("ICD10", "heart failure", match_in_text=True),
        ]},
    )
    plan = build_candidate_plan(config, config_hash="cfg")
    assert not [query for query in plan if query.match_strategy == "CODE_IN_TEXT"]


def test_candidate_structured_prefix_and_range_use_exact_member_sql():
    config = SimpleNamespace(
        config_hash="cfg",
        tables={"terminology": [
            _term("ICD10", "I50.", match_mode="PREFIX", expanded_values=["I50.9"]),
            _term("CPT_HCPCS", "33206-33208", match_mode="RANGE", expanded_values=["33207"]),
        ]},
    )
    plan = build_candidate_plan(config, config_hash="cfg")
    structured = [query for query in plan if query.match_strategy in {"PREFIX_CODE", "RANGE_CODE"}]
    assert {query.match_strategy for query in structured} == {"PREFIX_CODE", "RANGE_CODE"}
    assert all("LIKE" not in query.sql.upper() for query in structured)
    assert all(query.params for query in structured)
    assert all("33206-33208" not in str(query.params) for query in structured)


def test_code_in_text_uses_context_processor_for_negation():
    config = SimpleNamespace(tables={"atoms": [{"atom_id": "A"}]})
    match = AtomMatch(
        "r", "p", "A", "event", "CODE_IN_TEXT", "I50.1", "I50.1", "TRUE",
        "2025-01-01", "2025-01-01", "lineage", span_start=10, span_end=14,
    )
    seen = []

    def processor(text, *, target_span=None, target_label=None):
        seen.append((text, target_span, target_label))
        return {"is_negated": True, "context_processing_status": "OK"}

    evidence = qualify_atom_matches([match], config, context_processor=processor, screening_cutoff="2025-12-31")
    assert evidence[0].status == "FALSE"
    assert evidence[0].reason == "NEGATED"
    assert seen == [("I50.1", (10, 14), None)]


def test_code_in_text_context_uses_full_narrative_not_only_code_span():
    config = SimpleNamespace(tables={"atoms": [{"atom_id": "A"}]})
    match = AtomMatch(
        "r", "p", "A", "event", "CODE_IN_TEXT", "I50.1", "I50.1", "TRUE",
        "2025-01-01", "2025-01-01", "lineage", span_start=15, span_end=20,
        context_text="No evidence of I50.1 today.",
    )
    seen = []

    def processor(text, *, target_span=None, target_label=None):
        seen.append((text, target_span))
        return {"is_negated": True, "context_processing_status": "OK"}

    evidence = qualify_atom_matches([match], config, context_processor=processor, screening_cutoff="2025-12-31")
    assert seen == [("No evidence of I50.1 today.", (15, 20))]
    assert evidence[0].status == "FALSE"


def test_code_in_text_adapter_offsets_are_translated_to_tokens():
    config = SimpleNamespace(tables={"atoms": [{"atom_id": "A"}]})
    match = AtomMatch(
        "r", "p", "A", "event", "CODE_IN_TEXT", "I50.1", "I50.1", "TRUE",
        "2025-01-01", "2025-01-01", "lineage", span_start=8, span_end=12,
    )

    class Token:
        def __init__(self, idx, text):
            self.idx, self.text = idx, text

    class Nlp:
        def make_doc(self, _text):
            return [Token(0, "History"), Token(8, "I50.1"), Token(14, "noted")]

    class Processor:
        nlp = Nlp()

        def __init__(self):
            self.seen = []

        def process(self, text, *, target_span=None, target_label=None):
            self.seen.append(target_span)
            return {"is_uncertain": True, "context_processing_status": "OK"}

    processor = Processor()
    evidence = qualify_atom_matches([match], config, context_processor=processor, screening_cutoff="2025-12-31")
    assert processor.seen == [(1, 2)]
    assert evidence[0].status == "UNKNOWN"
    assert evidence[0].reason == "UNCERTAIN"


def _precedence_match(method, source_event_id, *, source_attributes=None, config_restriction=None):
    return AtomMatch(
        "r", "p", "A", source_event_id, method, "I50.1", "I50.1", "TRUE",
        "2025-01-01", "2025-01-01", f"lineage-{source_event_id}",
        source_attributes=dict(source_attributes or {}),
        config_restriction=dict(config_restriction or {}),
        context_text="No finding of I50.1 today.",
    )


@pytest.mark.parametrize(
    ("context_attrs", "expected_status", "expected_reason"),
    [
        ({}, "TRUE", None),
        ({"negated": True}, "FALSE", "NEGATED"),
        ({"uncertain": True}, "UNKNOWN", "UNCERTAIN"),
        ({"is_future": True}, "UNKNOWN", "FUTURE_OR_PLANNED_MENTION"),
    ],
)
def test_nlp_context_governs_code_fallback_for_same_atom(context_attrs, expected_status, expected_reason):
    config = SimpleNamespace(tables={"atoms": [{"atom_id": "A"}]})
    phrase = _precedence_match("PHRASEMATCHER", "phrase", source_attributes=context_attrs)
    code = _precedence_match("EXACT_NORMALIZED_CODE", "code")

    def processor(*_args, **_kwargs):
        return {"context_processing_status": "OK"}

    evidence = qualify_atom_matches(
        [phrase, code], config, context_processor=processor, screening_cutoff="2025-12-31"
    )
    phrase_evidence = next(item for item in evidence if item.source_provenance["match_method"] == "PHRASEMATCHER")
    code_evidence = next(item for item in evidence if item.source_provenance["match_method"] == "EXACT_NORMALIZED_CODE")
    assert phrase_evidence.status == expected_status
    assert phrase_evidence.reason == expected_reason
    assert code_evidence.status == "UNKNOWN"
    assert code_evidence.reason == "NLP_PRECEDENCE_CODE_SUPPRESSED"
    assert code_evidence.attributes["code_fallback_suppressed"] is True


def test_prefix_fallback_cannot_bypass_negated_nlp_evidence():
    """Explicit ICD prefix fallback follows the same NLP precedence policy."""
    config = SimpleNamespace(tables={"atoms": [{"atom_id": "A"}]})
    phrase = _precedence_match("PHRASEMATCHER", "phrase", source_attributes={"negated": True})
    code = _precedence_match("PREFIX_FALLBACK_CODE", "code")

    def processor(*_args, **_kwargs):
        return {"context_processing_status": "OK"}

    evidence = qualify_atom_matches(
        [phrase, code], config, context_processor=processor, screening_cutoff="2025-12-31"
    )
    phrase_evidence = next(item for item in evidence if item.source_provenance["match_method"] == "PHRASEMATCHER")
    code_evidence = next(item for item in evidence if item.source_provenance["match_method"] == "PREFIX_FALLBACK_CODE")
    assert phrase_evidence.status == "FALSE"
    assert phrase_evidence.reason == "NEGATED"
    assert code_evidence.status == "UNKNOWN"
    assert code_evidence.reason == "NLP_PRECEDENCE_CODE_SUPPRESSED"
    assert code_evidence.attributes["code_fallback_suppressed"] is True


def test_exact_code_can_fire_when_no_nlp_evidence_exists():
    config = SimpleNamespace(tables={"atoms": [{"atom_id": "A"}]})
    evidence = qualify_atom_matches(
        [_precedence_match("EXACT_NORMALIZED_CODE", "code")],
        config,
        screening_cutoff="2025-12-31",
    )
    assert evidence[0].status == "TRUE"


@pytest.mark.parametrize("mapping_role", ["SUPPORTING", "RESULT_REQUIRED"])
def test_non_standalone_code_mapping_cannot_fire_atom(mapping_role):
    config = SimpleNamespace(tables={"atoms": [{"atom_id": "A"}]})
    evidence = qualify_atom_matches(
        [_precedence_match(
            "EXACT_NORMALIZED_CODE", "code",
            config_restriction={"can_fire_atom_alone": True, "mapping_role": mapping_role},
        )],
        config,
        screening_cutoff="2025-12-31",
    )
    assert evidence[0].status == "UNKNOWN"
    assert evidence[0].reason == "CONFIG_RESTRICTION_MAPPING_ROLE_CANNOT_FIRE_ALONE"

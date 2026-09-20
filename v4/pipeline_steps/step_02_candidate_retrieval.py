"""Step 02 — retrieve candidate patients using structured codes and NLP spans."""

from __future__ import annotations

from typing import Any, Mapping

from ..extraction.atom_matching import build_phrase_matcher
from ..extraction.code_semantics import find_code_in_text
from ..extraction.candidate_net import CandidatePatient, CandidateReason, build_candidate_plan
from ..extraction.extraction_contract import is_nlp_system
from ..warehouse.snowflake_io import execute


def _row_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    if hasattr(row, "as_dict"):
        return dict(row.as_dict())
    raise TypeError(f"Unsupported Snowflake row type: {type(row)!r}")


def _get(row: Mapping[str, Any], name: str, default: Any = None) -> Any:
    wanted = name.strip('"').upper()
    for key, value in row.items():
        if str(key).strip('"').upper() == wanted:
            return value
    return default


def _reason(term: Mapping[str, Any], config_hash: str) -> CandidateReason:
    return CandidateReason(
        atom_id=str(term.get("atom_id", term.get("Atom_ID", ""))),
        terminology_system=str(term.get("terminology_system", term.get("Terminology_System", "NLP"))),
        config_value=str(term.get("value", term.get("Value", "")) or "").strip(),
        can_fire_atom_alone=term.get("can_fire_atom_alone", term.get("Can_Fire_Atom_Alone")),
        review_status=term.get("review_status", term.get("Review_Status")),
        config_hash=config_hash,
        retrieval_mode="BROAD_TEXT_FOR_PHRASEMATCHER",
        mapping_role=term.get("mapping_role", term.get("Mapping_Role")),
    )


def retrieve_candidates(session: Any, config: Any, *, run_id: str, source_config: Mapping[str, Any], nlp: Any = None) -> list[CandidatePatient]:
    """Execute the candidate plan; NLP candidates always come from PhraseMatcher spans."""
    plan = build_candidate_plan(config, config_hash=config.config_hash, source_config=source_config)
    terminology = config.rows("terminology")
    nlp_terms = [row for row in terminology if is_nlp_system(row.get("terminology_system", ""))]
    if nlp_terms and nlp is None:
        raise RuntimeError("spaCy/medSpaCy NLP pipeline is required because NLP terminology is configured")
    matcher = labels = None
    if nlp_terms:
        matcher, labels = build_phrase_matcher(nlp, nlp_terms)
    candidates: list[CandidatePatient] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for query in plan:
        rows = [_row_dict(row) for row in execute(session, query.sql, query.params)]
        if query.match_strategy != "BROAD_TEXT_FOR_PHRASEMATCHER":
            if query.match_strategy == "CODE_IN_TEXT":
                for row in rows:
                    patient_id = _get(row, "PATIENT_ID")
                    text_value = _get(row, "MATCHED_SOURCE_VALUE")
                    if patient_id in (None, "") or text_value in (None, ""):
                        continue
                    for reason in query.reasons or (query.reason,):
                        term = {
                            "atom_id": reason.atom_id,
                            "terminology_system": reason.terminology_system,
                            "value": reason.config_value,
                            "match_mode": reason.match_mode,
                            "expanded_values": list(reason.expanded_values),
                            "match_in_text": reason.match_in_text,
                        }
                        if not find_code_in_text(str(text_value), term):
                            continue
                        item = CandidatePatient(run_id, str(patient_id), reason, query.source_table, None)
                        key = (item.patient_id, reason.atom_id, reason.config_value, None)
                        if key not in seen:
                            seen.add(key)
                            candidates.append(item)
                continue
            for row in rows:
                patient_id = _get(row, "PATIENT_ID")
                if patient_id in (None, ""):
                    continue
                item = CandidatePatient(run_id, str(patient_id), query.reason, query.source_table, None)
                key = (item.patient_id, item.reason.atom_id, item.reason.config_value, item.source_record_id)
                if key not in seen:
                    seen.add(key)
                    candidates.append(item)
            continue
        if matcher is None or labels is None:
            continue
        for row in rows:
            patient_id = _get(row, "PATIENT_ID")
            text_value = _get(row, "MATCHED_SOURCE_VALUE")
            if patient_id in (None, "") or text_value in (None, ""):
                continue
            doc = nlp.make_doc(str(text_value))
            matched_labels = {doc.vocab.strings[match_id] for match_id, _, _ in matcher(doc)}
            for label in matched_labels:
                reason = _reason(labels[label], config.config_hash)
                item = CandidatePatient(run_id, str(patient_id), reason, query.source_table, None)
                key = (item.patient_id, reason.atom_id, reason.config_value, None)
                if key not in seen:
                    seen.add(key)
                    candidates.append(item)
    return candidates


def candidate_records(candidates: list[CandidatePatient]) -> list[dict[str, Any]]:
    return [{
        "run_id": item.run_id,
        "patient_id": item.patient_id,
        "candidate_reason_type": item.reason.retrieval_mode,
        "config_atom_id": item.reason.atom_id,
        "config_terminology_system": item.reason.terminology_system,
        "config_value": item.reason.config_value,
        "config_match_mode": item.reason.match_mode,
        "config_match_in_text": item.reason.match_in_text,
        "config_mapping_role": item.reason.mapping_role,
        "source_table": item.source_table,
        "source_record_id": item.source_record_id,
        "config_hash": item.reason.config_hash,
    } for item in candidates]


__all__ = ["retrieve_candidates", "candidate_records"]

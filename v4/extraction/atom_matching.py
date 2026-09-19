"""Workbook-driven structured and clinical-text atom matching.

Structured rows use exact normalized values.  NLP rows use spaCy's
``PhraseMatcher`` (or a caller-supplied medSpaCy-compatible matcher/context
processor); this module intentionally has no substring or regex fallback.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from .extraction_contract import event_system_compatible, is_nlp_system, normalize_system
from .source_events import SourceEvent
from .temporal_context import resolve_temporal_context


def _rows(config: Any, key: str) -> list[Mapping[str, Any]]:
    row_loader = getattr(config, "rows", None)
    if callable(row_loader):
        value = row_loader(key)
    else:
        value = None
    if value is None:
        tables = getattr(config, "tables", None)
        if isinstance(tables, Mapping):
            value = tables.get(key)
    if value is None:
        value = getattr(config, key, None)
    if value is None and isinstance(config, Mapping):
        value = config.get(key) or config.get(key.title())
    if isinstance(value, Mapping):
        value = list(value.values())
    return [r if isinstance(r, Mapping) else getattr(r, "__dict__", {}) for r in (value or [])]


def _get(row: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row:
            return row[name]
        target = name.replace(" ", "_").lower()
        for key in row:
            if str(key).replace(" ", "_").lower() == target:
                return row[key]
    return default


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _is_nlp(system: str) -> bool:
    return is_nlp_system(system)


def _term_value(row: Mapping[str, Any]) -> str:
    value = _get(row, "standard_code", "STANDARD_CODE", "nlp_term", "NLP_TERM", "value", "Value", default="")
    return str(value or "").strip()


@dataclass
class AtomMatch:
    run_id: str
    patient_id: str
    atom_id: str
    source_event_id: str
    match_method: str
    matched_config_value: str
    matched_source_value: str | None
    match_status: str
    event_date: Any
    available_date: Any
    support_lineage_id: str | None
    encounter_id: str | None = None
    source_attributes: dict[str, Any] = field(default_factory=dict)
    result_value: Any = None
    result_status: str | None = None
    context_lineage_ids: list[str] = field(default_factory=list)
    config_restriction: dict[str, Any] = field(default_factory=dict)
    config_hash: str = ""
    experiencer_hint: str | None = None
    stage_hint: str | None = None
    span_start: int | None = None
    span_end: int | None = None
    matcher_label: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["support_lineage_ids"] = [self.support_lineage_id] if self.support_lineage_id else []
        return out


def build_phrase_matcher(nlp: Any, terminology_rows: Sequence[Mapping[str, Any]]) -> tuple[Any, dict[str, Mapping[str, Any]]]:
    """Build a PhraseMatcher from workbook NLP terms only.

    A model/context pipeline is supplied by the caller so medSpaCy can be
    used where installed.  Terms are not lower-cased into substring checks;
    PhraseMatcher performs token-aware matching using the model vocabulary.
    """
    if nlp is None:
        raise ValueError("an NLP model is required for PhraseMatcher")
    try:
        from spacy.matcher import PhraseMatcher
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("spaCy is required for workbook NLP terminology") from exc
    matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
    labels: dict[str, Mapping[str, Any]] = {}
    for idx, row in enumerate(terminology_rows):
        system = normalize_system(_get(row, "terminology_system", "system", "Terminology_System", default=""))
        if not _is_nlp(system):
            continue
        phrase = _term_value(row)
        atom_id = str(_get(row, "atom_id", "Atom_ID", default=""))
        if not phrase or not atom_id:
            continue
        # Unique matcher labels preserve duplicate terms mapped to distinct
        # atoms without merging workbook rows.
        label = f"V4_TERM_{idx}"
        matcher.add(label, [nlp.make_doc(phrase)])
        labels[label] = row
    return matcher, labels


def _structured_match(event: SourceEvent, term: Mapping[str, Any]) -> bool:
    system = normalize_system(_get(term, "terminology_system", "system", "Terminology_System", default=""))
    if _is_nlp(system):
        return False
    raw = _term_value(term)
    source_code = _norm(event.code_value)
    if not source_code or not _event_system_compatible(event, system):
        return False
    normalized_raw = _norm(raw)
    if normalized_raw.endswith("."):
        return source_code.startswith(normalized_raw) and bool(source_code)
    if "-" in normalized_raw and normalized_raw.count("-") == 1:
        start, end = (part.strip() for part in normalized_raw.split("-", 1))
        # A range is deterministic when dotted code families or numeric
        # bounds are present.  Hyphens inside an opaque code remain exact.
        if start and end and ("." in start or "." in end or (start.isdigit() and end.isdigit())):
            return start <= source_code <= end
    configured = {normalized_raw}
    # v3 normalized sheets expose STANDARD_CODE; retain deterministic parsing
    # only when the parsed token is itself present in the workbook value.
    raw = _term_value(term)
    if ":" in raw:
        token = raw.split(":", 1)[0].strip()
        if token:
            configured.add(_norm(token))
    return source_code in configured


def _event_system_compatible(event: SourceEvent, system: str) -> bool:
    return event_system_compatible(event.source_table, event.source_field, system, event.code_system)


def match_atom_events(
    events: Sequence[SourceEvent],
    config: Any,
    *,
    config_hash: str,
    nlp: Any = None,
    max_unknown_nlp_matches: int = 10000,
) -> list[AtomMatch]:
    """Match source events against only workbook ``Terminology`` rows."""
    terms = _rows(config, "terminology")
    atoms = {str(_get(row, "atom_id", "Atom_ID", default="")): row for row in _rows(config, "atoms")}
    out: list[AtomMatch] = []
    matcher = labels = None
    nlp_gap = False
    if any(_is_nlp(normalize_system(_get(t, "terminology_system", "system", "Terminology_System", default=""))) for t in terms):
        if nlp is None:
            nlp_gap = True
        else:
            matcher, labels = build_phrase_matcher(nlp, terms)
    structured_terms = [t for t in terms if not _is_nlp(normalize_system(_get(t, "terminology_system", "system", "Terminology_System", default="")))]
    nlp_terms = [t for t in terms if _is_nlp(normalize_system(_get(t, "terminology_system", "system", "Terminology_System", default="")))]
    def restriction(term: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "can_fire_atom_alone": _get(term, "can_fire_atom_alone", "Can_Fire_Atom_Alone"),
            "review_status": _get(term, "review_status", "Review_Status"),
            "context_guard": _get(term, "context_guard", "Context_Guard"),
            "can_fire_from_mapping": _get(term, "can_fire_from_mapping", "Can_Fire_From_This_Mapping"),
        }
    def source_hints(event: SourceEvent) -> tuple[str, str | None]:
        experiencer = event.experiencer_hint or ("FAMILY_MEMBER" if event.source_table.upper() == "FAMILY_HISTORY" else "PATIENT")
        return experiencer, None
    for event in events:
        for term in structured_terms:
            atom_id = str(_get(term, "atom_id", "Atom_ID", default=""))
            if not atom_id:
                continue
            config_value = _term_value(term)
            if _structured_match(event, term):
                experiencer_hint, stage_hint = source_hints(event)
                out.append(AtomMatch(event.run_id, event.patient_id, atom_id, event.source_event_id,
                                     "EXACT_NORMALIZED_CODE", config_value, event.code_value, "TRUE",
                                     event.event_date, event.available_date, event.support_lineage_id,
                                     encounter_id=event.encounter_id,
                                     source_attributes=dict(event.attributes or {}), result_value=event.result_value,
                                     result_status=event.result_status,
                                     config_restriction=restriction(term), config_hash=config_hash,
                                     experiencer_hint=experiencer_hint, stage_hint=stage_hint))
        if not nlp_terms or event.text_value in (None, ""):
            continue
        if nlp_gap:
            unknown_count = 0
            for term in nlp_terms:
                if unknown_count >= max_unknown_nlp_matches:
                    break
                experiencer_hint, stage_hint = source_hints(event)
                out.append(AtomMatch(event.run_id, event.patient_id,
                                     str(_get(term, "atom_id", "Atom_ID", default="")), event.source_event_id,
                                     "NLP_CONFIG_GAP_NO_PHRASEMATCHER", _term_value(term), event.text_value,
                                     "UNKNOWN", event.event_date, event.available_date, event.support_lineage_id,
                                     encounter_id=event.encounter_id,
                                     source_attributes=dict(event.attributes or {}), result_value=event.result_value,
                                     result_status=event.result_status,
                                     config_restriction=restriction(term), config_hash=config_hash,
                                     experiencer_hint=experiencer_hint, stage_hint=stage_hint))
                unknown_count += 1
            continue
        # Process one document once per source event. Every configured span is
        # retained because repeated mentions may have different polarity,
        # certainty, experiencer, or clinical dates inside the same note.
        doc = nlp.make_doc(event.text_value)
        seen_spans: set[tuple[str, int, int]] = set()
        for match_id, start, end in matcher(doc):
            label = doc.vocab.strings[match_id]
            span_key = (label, int(start), int(end))
            if span_key in seen_spans:
                continue
            seen_spans.add(span_key)
            term = labels[label]
            experiencer_hint, stage_hint = source_hints(event)
            temporal = resolve_temporal_context(doc, int(start), int(end), event.event_date)
            source_attributes = dict(event.attributes or {})
            source_attributes.update(temporal.attributes(event.event_date))
            out.append(AtomMatch(event.run_id, event.patient_id,
                                 str(_get(term, "atom_id", "Atom_ID", default="")), event.source_event_id,
                                 "PHRASEMATCHER", _term_value(term), event.text_value, "TRUE",
                                 temporal.clinical_date or event.event_date,
                                 event.available_date, event.support_lineage_id,
                                 encounter_id=event.encounter_id,
                                 source_attributes=source_attributes, result_value=event.result_value,
                                 result_status=event.result_status,
                                 config_restriction=restriction(term), config_hash=config_hash,
                                 experiencer_hint=experiencer_hint, stage_hint=stage_hint,
                                 span_start=int(start), span_end=int(end), matcher_label=label))
    return out


__all__ = ["AtomMatch", "build_phrase_matcher", "match_atom_events"]

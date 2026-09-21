"""Evidence qualification with explicit TRUE/FALSE/UNKNOWN semantics."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..evaluation_policy import (
    is_claims_recall,
    is_native_claim_code,
    normalize_evaluation_mode,
)
from .atom_matching import AtomMatch
from .extraction_contract import MEDSPACY_CONTEXT_ATTRIBUTES


TRUE = "TRUE"
FALSE = "FALSE"
UNKNOWN = "UNKNOWN"

# These names are used only for evidence arbitration after matching.  They do
# not broaden structured-code or NLP matching behavior.
_CODE_MATCH_METHODS = {
    "EXACT_NORMALIZED_CODE",
    "PREFIX_NORMALIZED_CODE",
    "PREFIX_FALLBACK_CODE",
    "RANGE_NORMALIZED_CODE",
    "CODE_IN_TEXT",
}
_NLP_EVIDENCE_METHODS = {"PHRASEMATCHER"}
_NON_STANDALONE_MAPPING_ROLES = {"SUPPORTING", "RESULT_REQUIRED"}


class ClinicalContextAdapter:
    """Adapter for medSpaCy/spaCy context annotations.

    The adapter never performs lexical negation or experiencer heuristics.
    A medSpaCy pipeline (or an equivalent caller-supplied annotator) must set
    supported document/span extensions.  Missing context processing is
    reported as a config/runtime gap so NLP matches cannot become affirmative
    evidence by accident.
    """

    def __init__(self, nlp: Any, *, require_context_components: bool = True):
        self.nlp = nlp
        self.require_context_components = require_context_components

    def _target_window(
        self,
        text: str,
        target_start: int,
        target_end: int,
    ) -> tuple[str, int, int]:
        """Return a contrast/clause-local window while retaining medSpaCy.

        ConText modifiers should not leak across semicolons, sentence ends, or
        explicit contrast transitions in long EHR prose. This windowing uses
        spaCy token boundaries; it does not perform clinical keyword matching.
        """
        source = self.nlp.make_doc(text)
        tokens = list(source)
        boundaries = {
            ".", ";", "\n", "but", "however", "yet", "while", "whereas", "nevertheless",
        }

        # A comma is not always a context boundary (for example, ``no fever,
        # chills, or nausea``).  It is a boundary when the following tokens
        # start a new predicated clause, which covers the subject switches and
        # assessment corrections common in long clinical notes without
        # treating comma-delimited finding lists as separate assertions.
        subjects = {
            "he", "she", "they", "we", "i", "patient", "clinician", "physician",
            "examiner", "resident", "specialist", "assessment", "examination",
            "review", "history", "note", "chart", "report", "study", "result",
        }
        predicates = {
            "am", "are", "is", "was", "were", "be", "been", "being", "has", "had",
            "reports", "reported", "denies", "denied", "records", "recorded",
            "documents", "documented", "confirms", "confirmed", "states", "stated",
            "shows", "showed", "demonstrates", "demonstrated", "finds", "found",
            "notes", "noted", "describes", "described", "indicates", "indicated",
        }

        def comma_starts_clause(index: int) -> bool:
            segment: list[str] = []
            for token in tokens[index + 1:index + 22]:
                lowered = token.text.lower()
                if lowered in boundaries or lowered == ",":
                    break
                segment.append(lowered)
            while segment and segment[0] in {"and", "or", "then"}:
                segment.pop(0)
            if not segment:
                return False
            if segment[0] in predicates:
                return True
            return any(word in subjects for word in segment[:8]) and any(
                word in predicates for word in segment
            )

        def is_boundary(index: int) -> bool:
            lowered = tokens[index].text.lower()
            return lowered in boundaries or (lowered == "," and comma_starts_clause(index))

        left = 0
        for index in range(max(0, target_start - 1), -1, -1):
            if is_boundary(index):
                left = index + 1
                break
        right = len(tokens)
        for index in range(min(len(tokens), target_end), len(tokens)):
            if is_boundary(index):
                right = index
                break
        if left == 0 and right == len(tokens):
            return text, target_start, target_end
        if left >= right:
            return text, target_start, target_end
        start_char = tokens[left].idx
        last = tokens[right - 1]
        end_char = last.idx + len(last.text)
        return text[start_char:end_char], target_start - left, target_end - left

    def process(self, text: str, *, target_span: tuple[int | None, int | None] | None = None, target_label: str | None = None) -> dict[str, Any]:
        if self.nlp is None:
            return {"context_processing_status": "CONFIG_GAP_CONTEXT_ANNOTATOR_UNAVAILABLE"}
        # A purpose-built medSpaCy wrapper may accept the target directly and
        # run its context components against that span.  This is preferred to
        # re-running generic NLP without a target.
        if target_span and target_span[0] is not None and target_span[1] is not None and hasattr(self.nlp, "process_target"):
            result = self.nlp.process_target(text, int(target_span[0]), int(target_span[1]), target_label)
            if isinstance(result, Mapping):
                attrs = dict(result)
                attrs.setdefault("context_processing_status", "OK")
                return attrs
        target_start, target_end = target_span if target_span else (None, None)
        context_component_seen = False
        target_entity = None
        if target_start is not None and target_end is not None and hasattr(self.nlp, "make_doc"):
            # PhraseMatcher offsets are token offsets. Insert that exact target
            # immediately before the medSpaCy context component so context is
            # evaluated for the configured phrase, not an unrelated entity.
            window_text, target_start, target_end = self._target_window(
                text,
                int(target_start),
                int(target_end),
            )
            doc = self.nlp.make_doc(window_text)
            try:
                from spacy.tokens import Span
                target_entity = Span(doc, int(target_start), int(target_end), label=target_label or "V4_TARGET")
                for component_name, component in getattr(self.nlp, "pipeline", ()):
                    if "context" in str(component_name).lower():
                        retained = [
                            span for span in getattr(doc, "ents", ())
                            if span.end <= target_entity.start or span.start >= target_entity.end
                        ]
                        doc.ents = tuple(retained + [target_entity])
                        context_component_seen = True
                    doc = component(doc)
            except Exception:
                # Failed target insertion is an auditable context gap. It is
                # never replaced by lexical heuristics.
                doc = self.nlp(window_text)
                target_entity = None
        else:
            doc = self.nlp(text)
        attrs: dict[str, Any] = {}
        # medSpaCy and custom pipelines may expose these on doc._ or the
        # first target span.  We read annotations only; no terms are guessed.
        extensions = getattr(doc, "_", None)
        for name in MEDSPACY_CONTEXT_ATTRIBUTES:
            if extensions is not None and hasattr(extensions, name):
                try:
                    value = getattr(extensions, name)
                    if value not in (None, ""):
                        attrs[name] = value
                except Exception:
                    pass
        spans = list(getattr(doc, "ents", ()))
        if target_start is not None and target_end is not None:
            spans = [span for span in spans if span.start < target_end and span.end > target_start]
        for span in spans:
            span_ext = getattr(span, "_", None)
            if span_ext is None:
                continue
            for name in MEDSPACY_CONTEXT_ATTRIBUTES:
                if name not in attrs and hasattr(span_ext, name):
                    try:
                        value = getattr(span_ext, name)
                        if value not in (None, ""):
                            attrs[name] = value
                    except Exception:
                        pass
            if "experiencer" not in attrs and hasattr(span_ext, "is_family"):
                try:
                    if bool(span_ext.is_family):
                        attrs["experiencer"] = "FAMILY_MEMBER"
                except Exception:
                    pass
        if target_span and not context_component_seen and not hasattr(self.nlp, "process_target"):
            attrs["context_processing_status"] = "CONFIG_GAP_CONTEXT_TARGET_NOT_PROCESSED"
            return attrs
        if self.require_context_components and not any(
            key in attrs for key in MEDSPACY_CONTEXT_ATTRIBUTES if key != "context_lineage_ids"
        ):
            attrs["context_processing_status"] = "CONFIG_GAP_CONTEXT_ANNOTATOR_UNAVAILABLE"
        else:
            attrs["context_processing_status"] = "OK"
        return attrs


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


def _truth(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().upper()
    if text in {"TRUE", "YES", "Y", "1", "AFFIRMED", "PRESENT"}:
        return True
    if text in {"FALSE", "NO", "N", "0", "NEGATED", "ABSENT"}:
        return False
    return None


def _list_value(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value).replace("\n", ";").split(";") if part.strip()]


def _date_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value
    if value in (None, ""):
        return None
    return str(value)


def _on_or_before(value: Any, cutoff: Any) -> bool | None:
    if cutoff is None:
        return None
    if value in (None, ""):
        return None
    try:
        def normalized(raw: Any) -> datetime:
            if isinstance(raw, datetime):
                parsed = raw
            elif isinstance(raw, date):
                parsed = datetime.combine(raw, datetime.min.time())
            else:
                parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        left = normalized(value)
        right = normalized(cutoff)
        return left <= right
    except (TypeError, ValueError):
        # Date parsing is a config/data gap, never an affirmative eligibility.
        return None


def _stage_class(value: Any) -> str | None:
    if value in (None, ""):
        return None
    compact = str(value).strip().upper().replace("_", "").replace("-", "").replace(" ", "")
    if compact in {"PRETEST", "PRETESTSIGNAL"}:
        return "PRETEST_SIGNAL"
    return str(value).strip().upper()


@dataclass
class QualifiedEvidence:
    run_id: str
    patient_id: str
    evidence_id: str
    atom_id: str
    event_date: Any
    available_date: Any
    stage: str | None
    polarity: str | None
    certainty: str | None
    experiencer: str | None
    status: str
    support_lineage_ids: list[str] = field(default_factory=list)
    context_lineage_ids: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    source_provenance: dict[str, Any] = field(default_factory=dict)
    config_restriction: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    config_hash: str = ""
    evaluation_mode: str = "STRICT"
    provisional: bool = False
    relaxations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _processor_attributes(processor: Any, text: str | None, match: AtomMatch) -> dict[str, Any]:
    # Clinical context is meaningful only for a matched text span. Structured
    # codes are already exact evidence and must not be downgraded merely
    # because they have no NLP target span.
    if processor is None or not text or match.match_method not in {"PHRASEMATCHER", "CODE_IN_TEXT"}:
        return {}
    target_span = (match.span_start, match.span_end)
    # PhraseMatcher returns token offsets, while CODE_IN_TEXT is discovered by
    # a character-span regex.  ClinicalContextAdapter follows spaCy's token
    # span contract, so translate only when the adapter exposes its NLP model;
    # custom processors continue to receive the offsets they were given.
    if match.match_method == "CODE_IN_TEXT" and target_span[0] is not None and target_span[1] is not None:
        nlp = getattr(processor, "nlp", None)
        make_doc = getattr(nlp, "make_doc", None)
        if callable(make_doc):
            try:
                tokens = list(make_doc(text))
                start_char, end_char = int(target_span[0]), int(target_span[1])
                token_start = next(
                    (index for index, token in enumerate(tokens)
                     if token.idx + len(token.text) > start_char),
                    len(tokens),
                )
                token_end = next(
                    (index for index, token in enumerate(tokens)
                     if token.idx >= end_char),
                    len(tokens),
                )
                target_span = (token_start, token_end)
            except Exception:
                # The processor will report its normal context gap if a custom
                # tokenizer cannot represent the span.
                pass
    if hasattr(processor, "process"):
        try:
            result = processor.process(text, target_span=target_span, target_label=match.matcher_label)
        except TypeError:
            result = processor.process(text)
    elif callable(processor):
        try:
            result = processor(text, target_span=target_span, target_label=match.matcher_label)
        except TypeError:
            result = processor(text)
    else:
        return {}
    if isinstance(result, Mapping):
        return dict(result)
    return dict(getattr(result, "attributes", {}) or {})


def _mapping_role(attrs: Mapping[str, Any]) -> str:
    """Normalize the authoring role without changing matching behavior."""
    value = attrs.get("mapping_role", attrs.get("Mapping_Role", ""))
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def _evidence_method(evidence: QualifiedEvidence) -> str:
    return str(
        evidence.source_provenance.get("match_method", "")
        or evidence.attributes.get("match_method", "")
    ).strip().upper()


def _apply_atom_firing_precedence(evidence: Sequence[QualifiedEvidence]) -> list[QualifiedEvidence]:
    """Apply NLP-over-code precedence per run/patient/atom.

    A real PhraseMatcher span is authoritative for that atom, including when
    context qualifies it as negated, uncertain, future, or otherwise unknown.
    A code hit therefore cannot bypass that mention.  A model/configuration
    gap marker is not an NLP match; direct exact code evidence remains
    eligible in that case (subject to its normal restrictions).
    """
    groups: dict[tuple[str, str, str], list[QualifiedEvidence]] = {}
    for item in evidence:
        groups.setdefault((item.run_id, item.patient_id, item.atom_id), []).append(item)

    out: list[QualifiedEvidence] = []
    for group in groups.values():
        nlp_present = any(_evidence_method(item) in _NLP_EVIDENCE_METHODS for item in group)
        if not nlp_present:
            out.extend(group)
            continue
        for item in group:
            if _evidence_method(item) not in _CODE_MATCH_METHODS or item.status != TRUE:
                out.append(item)
                continue
            attrs = dict(item.attributes or {})
            attrs.update({
                "atom_firing_precedence": "NLP_OVER_CODE",
                "code_fallback_suppressed": True,
            })
            attrs.pop("recall_provisional", None)
            attrs.pop("recall_relaxations", None)
            out.append(replace(
                item,
                status=UNKNOWN,
                support_lineage_ids=[],
                attributes=attrs,
                reason="NLP_PRECEDENCE_CODE_SUPPRESSED",
                provisional=False,
                relaxations=[],
            ))
    return out


def _qualify_one(
    match: AtomMatch,
    atom: Mapping[str, Any],
    *,
    context_processor: Any = None,
    cutoff: Any = None,
    evaluation_mode: str = "STRICT",
) -> QualifiedEvidence:
    evaluation_mode = normalize_evaluation_mode(evaluation_mode)
    attrs = dict(match.source_attributes or {})
    attrs["evaluation_mode"] = evaluation_mode
    context_text = match.context_text or match.matched_source_value
    attrs.update(_processor_attributes(context_processor, context_text, match))
    if match.result_value not in (None, ""):
        attrs.setdefault("result_value", match.result_value)
    if match.result_status not in (None, ""):
        attrs.setdefault("result_status", match.result_status)
    attrs.update({k: v for k, v in (match.config_restriction or {}).items() if k not in attrs})
    if match.experiencer_hint and "experiencer" not in attrs:
        attrs["experiencer"] = match.experiencer_hint
    # Stage is an execution-time property for structured source evidence.
    # A dated row available on/before the screening cutoff is pre-test; no
    # lexical inference from a code/text value is performed.
    if "stage" not in attrs and match.stage_hint:
        attrs["stage"] = match.stage_hint
    if "stage" not in attrs and cutoff is not None and _on_or_before(match.available_date, cutoff) is True:
        attrs["stage"] = "PRETEST_SIGNAL"
    status = match.match_status if match.match_status in {TRUE, FALSE, UNKNOWN} else UNKNOWN
    reason = None
    relaxations: list[str] = []
    recall_eligible = is_claims_recall(evaluation_mode) and is_native_claim_code(match)

    def relax_or_downgrade(relaxation: str, strict_reason: str) -> None:
        nonlocal status, reason
        if recall_eligible:
            relaxations.append(relaxation)
        else:
            status, reason = UNKNOWN, strict_reason

    if status == TRUE and match.match_method in {"PHRASEMATCHER", "CODE_IN_TEXT"} and context_processor is None:
        status, reason = UNKNOWN, "CONFIG_GAP_CONTEXT_ANNOTATOR_UNAVAILABLE"
    if status == TRUE and str(attrs.get("context_processing_status", "")).startswith("CONFIG_GAP"):
        status, reason = UNKNOWN, str(attrs["context_processing_status"])
    can_fire_alone = _truth(attrs.get("can_fire_atom_alone"))
    if status == TRUE and can_fire_alone is False and match.match_method != "PHRASEMATCHER":
        # A structured code marked candidate-only can retrieve and label the
        # source event, but it cannot be silently promoted to affirmative atom
        # evidence without the contextual qualification available to NLP.
        relax_or_downgrade(
            "TERM_REQUIRES_CONTEXT_OR_CORROBORATION",
            "CONFIG_RESTRICTION_TERM_CANNOT_FIRE_ALONE",
        )
    mapping_role = _mapping_role(attrs)
    if status == TRUE and match.match_method in _CODE_MATCH_METHODS and mapping_role in _NON_STANDALONE_MAPPING_ROLES:
        # Supporting/result-required rows may retrieve or annotate an event,
        # but cannot establish an atom on their own.  This is qualification,
        # not code matching.
        relax_or_downgrade(
            f"NON_STANDALONE_MAPPING_ROLE:{mapping_role}",
            "CONFIG_RESTRICTION_MAPPING_ROLE_CANNOT_FIRE_ALONE",
        )
    if status == TRUE and not match.support_lineage_id:
        status, reason = UNKNOWN, "MISSING_SUPPORT_LINEAGE"
    available_ok = _on_or_before(match.available_date, cutoff)
    if status == TRUE and available_ok is not True:
        if available_ok is None:
            relax_or_downgrade(
                "MISSING_AVAILABILITY_DATE",
                "UNKNOWN_AVAILABILITY_DATE",
            )
        else:
            status, reason = UNKNOWN, "AFTER_SCREENING_CUTOFF"
    required_stage = _get(atom, "stage", "Stage", "evidence_stage", "Evidence_Stage")
    observed_stage = attrs.get("stage", attrs.get("evidence_stage"))
    if status == TRUE and required_stage not in (None, ""):
        if observed_stage in (None, ""):
            relax_or_downgrade(
                f"MISSING_REQUIRED_STAGE:{required_stage}",
                "MISSING_REQUIRED_STAGE",
            )
        elif _stage_class(observed_stage) != _stage_class(required_stage):
            status, reason = FALSE, "STAGE_MISMATCH"
    required_exp = _get(atom, "experiencer", "Experiencer")
    observed_exp = attrs.get("experiencer", attrs.get("experiencer_hint"))
    if status == TRUE and required_exp not in (None, ""):
        if observed_exp in (None, ""):
            status, reason = UNKNOWN, "MISSING_EXPERIENCER"
        elif str(observed_exp).strip().upper() != str(required_exp).strip().upper():
            status, reason = FALSE, "EXPERIENCER_MISMATCH"
    polarity = attrs.get("polarity")
    certainty = attrs.get("certainty")
    if status == TRUE and _truth(attrs.get("negated", attrs.get("is_negated"))) is True:
        status, reason, polarity = FALSE, "NEGATED", "NEGATED"
    if status == TRUE and _truth(attrs.get("uncertain", attrs.get("is_uncertain"))) is True:
        status, reason, certainty = UNKNOWN, "UNCERTAIN", "UNCERTAIN"
    if status == TRUE and _truth(attrs.get("is_future")) is True:
        status, reason = UNKNOWN, "FUTURE_OR_PLANNED_MENTION"
    # Historical mentions are preserved as affirmative/negative evidence with
    # explicit temporality. Whether recency is required belongs to the
    # workbook rule/qualifiers; history is not silently treated as current or
    # discarded. Cutoff eligibility is still governed by available_date.
    if _truth(attrs.get("is_historical")) is True:
        attrs.setdefault("temporality", "HISTORICAL")
    for qualifier in _list_value(_get(atom, "required_qualifiers", "Required_Qualifiers")):
        present = _truth(attrs.get(qualifier))
        if present is None:
            relax_or_downgrade(
                f"MISSING_REQUIRED_QUALIFIER:{qualifier}",
                f"MISSING_REQUIRED_QUALIFIER:{qualifier}",
            )
            break
        if present is False:
            status, reason = FALSE, f"FAILED_REQUIRED_QUALIFIER:{qualifier}"
            break
    relaxations = list(dict.fromkeys(relaxations))
    if status == TRUE and relaxations:
        reason = "CLAIMS_RECALL_PROVISIONAL"
        attrs["recall_provisional"] = True
        attrs["recall_relaxations"] = tuple(relaxations)
    elif status != TRUE:
        # A later observed contradiction or hard eligibility failure wins over
        # every earlier recall assumption.  Such evidence is never marked as
        # provisionally affirmative.
        relaxations = []
        attrs.pop("recall_provisional", None)
        attrs.pop("recall_relaxations", None)
    support = [match.support_lineage_id] if status == TRUE and match.support_lineage_id else []
    context = list(dict.fromkeys(match.context_lineage_ids or attrs.get("context_lineage_ids", []) or []))
    source_provenance = {"source_event_id": match.source_event_id, "support_lineage_id": match.support_lineage_id,
                         "encounter_id": match.encounter_id,
                         "match_method": match.match_method,
                         "source_table": attrs.get("table_key"),
                         "matched_config_value": match.matched_config_value,
                         "span_start": match.span_start,
                         "span_end": match.span_end,
                         "temporal_expression": attrs.get("temporal_expression"),
                         "source_recorded_event_date": attrs.get("source_recorded_event_date")}
    span_identity = (
        f":{match.matcher_label}:{match.span_start}:{match.span_end}"
        if match.match_method == "PHRASEMATCHER" else ""
    )
    return QualifiedEvidence(
        run_id=match.run_id, patient_id=match.patient_id,
        evidence_id=f"{match.source_event_id}:{match.atom_id}:{match.match_method}{span_identity}", atom_id=match.atom_id,
        event_date=_date_value(match.event_date), available_date=_date_value(match.available_date),
        stage=None if observed_stage in (None, "") else str(observed_stage), polarity=None if polarity in (None, "") else str(polarity),
        certainty=None if certainty in (None, "") else str(certainty), experiencer=None if observed_exp in (None, "") else str(observed_exp),
        status=status, support_lineage_ids=support, context_lineage_ids=context, attributes=attrs,
        source_provenance=source_provenance, config_restriction=dict(match.config_restriction or {}), reason=reason,
        config_hash=match.config_hash,
        evaluation_mode=evaluation_mode,
        provisional=bool(relaxations),
        relaxations=relaxations,
    )


def qualify_atom_matches(
    matches: Sequence[AtomMatch],
    config: Any,
    *,
    context_processor: Any = None,
    screening_cutoff: Any = None,
    evaluation_mode: str = "STRICT",
) -> list[QualifiedEvidence]:
    atoms = {str(_get(row, "atom_id", "Atom_ID", default="")): row for row in _rows(config, "atoms")}
    out = []
    for match in matches:
        atom = atoms.get(match.atom_id, {})
        out.append(_qualify_one(
            match,
            atom,
            context_processor=context_processor,
            cutoff=screening_cutoff,
            evaluation_mode=evaluation_mode,
        ))
    return _apply_atom_firing_precedence(out)


def eligible_evidence(evidence: QualifiedEvidence, *, required_stage: str | None = None, cutoff: Any = None, require_lineage: bool = True) -> bool | None:
    """Return TRUE/FALSE/UNKNOWN for use by later workbook-driven stages."""
    if evidence.status == FALSE:
        return False
    if evidence.status == UNKNOWN:
        return None
    if require_lineage and not evidence.support_lineage_ids:
        return None
    if required_stage and (evidence.stage or "").upper() != required_stage.upper():
        return False if evidence.stage else None
    date_ok = _on_or_before(evidence.available_date, cutoff)
    return True if date_ok is True else (False if date_ok is False else None)


__all__ = ["TRUE", "FALSE", "UNKNOWN", "ClinicalContextAdapter", "QualifiedEvidence", "qualify_atom_matches", "eligible_evidence"]

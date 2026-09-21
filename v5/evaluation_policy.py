"""Shared execution policy for strict and claims-only recall evaluation.

The clinical configuration remains single-source.  This module only controls
how the engine represents facts that a selected source profile cannot observe.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Iterable, Mapping


STRICT = "STRICT"
CLAIMS_RECALL = "CLAIMS_RECALL"
EVALUATION_MODES = frozenset({STRICT, CLAIMS_RECALL})

NATIVE_STRUCTURED_CODE_METHODS = frozenset({
    "EXACT_NORMALIZED_CODE",
    "PREFIX_NORMALIZED_CODE",
    "PREFIX_FALLBACK_CODE",
    "RANGE_NORMALIZED_CODE",
})


def normalize_evaluation_mode(value: Any = None) -> str:
    mode = str(value or STRICT).strip().upper().replace("-", "_")
    aliases = {
        "CLAIMS_ONLY": CLAIMS_RECALL,
        "CLAIM_ONLY": CLAIMS_RECALL,
        "HIGH_RECALL": CLAIMS_RECALL,
        "RECALL": CLAIMS_RECALL,
    }
    mode = aliases.get(mode, mode)
    if mode not in EVALUATION_MODES:
        raise ValueError(
            f"Unsupported evaluation_mode {value!r}; expected one of {sorted(EVALUATION_MODES)}"
        )
    return mode


def is_claims_recall(value: Any = None) -> bool:
    return normalize_evaluation_mode(value) == CLAIMS_RECALL


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _mapping(obj: Any, name: str) -> Mapping[str, Any]:
    value = _value(obj, name, {}) or {}
    return value if isinstance(value, Mapping) else {}


def is_native_claim_code(obj: Any) -> bool:
    """Return whether an evidence-like row is a native structured claim hit."""
    attributes = _mapping(obj, "attributes")
    if not attributes:
        attributes = _mapping(obj, "source_attributes")
    provenance = _mapping(obj, "source_provenance")
    restriction = _mapping(obj, "config_restriction")
    method = str(
        provenance.get("match_method")
        or attributes.get("match_method")
        or restriction.get("match_method")
        or _value(obj, "match_method", "")
    ).strip().upper()
    table = str(
        attributes.get("table_key")
        or attributes.get("source_table")
        or provenance.get("source_table")
        or _value(obj, "source_table", "")
    ).strip().upper()
    return table in {"CLAIM", "CLAIMS"} and method in NATIVE_STRUCTURED_CODE_METHODS


def recall_relaxations(obj: Any) -> tuple[str, ...]:
    direct = _value(obj, "relaxations", ()) or ()
    attributes = _mapping(obj, "attributes")
    nested = attributes.get("recall_relaxations", ()) or ()
    if isinstance(direct, str):
        direct = (direct,)
    if isinstance(nested, str):
        nested = (nested,)
    return tuple(dict.fromkeys(str(item) for item in (*direct, *nested) if item))


def is_provisional(obj: Any) -> bool:
    return bool(_value(obj, "provisional", False) or recall_relaxations(obj))


def collect_relaxations(items: Iterable[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        reason
        for item in items
        for reason in recall_relaxations(item)
        if reason
    ))


def provisional_copy(obj: Any, *reasons: str, status: str | None = None) -> dict[str, Any]:
    """Return an ordinary row with additive, auditable recall assumptions."""
    if isinstance(obj, Mapping):
        row = dict(obj)
    elif is_dataclass(obj):
        row = asdict(obj)
    elif hasattr(obj, "as_dict") and callable(obj.as_dict):
        row = dict(obj.as_dict())
    else:
        row = dict(vars(obj))
    existing = recall_relaxations(row)
    combined = tuple(dict.fromkeys((*existing, *(str(reason) for reason in reasons if reason))))
    attributes = dict(row.get("attributes") or {})
    attributes["evaluation_mode"] = CLAIMS_RECALL
    attributes["recall_provisional"] = True
    attributes["recall_relaxations"] = combined
    row["attributes"] = attributes
    row["evaluation_mode"] = CLAIMS_RECALL
    row["provisional"] = True
    row["relaxations"] = combined
    if status is not None:
        row["status"] = status
    return row


__all__ = [
    "STRICT",
    "CLAIMS_RECALL",
    "EVALUATION_MODES",
    "NATIVE_STRUCTURED_CODE_METHODS",
    "normalize_evaluation_mode",
    "is_claims_recall",
    "is_native_claim_code",
    "recall_relaxations",
    "is_provisional",
    "collect_relaxations",
    "provisional_copy",
]

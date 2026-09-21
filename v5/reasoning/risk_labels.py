"""Phenotype-independent review labels for categorical suspicion priority."""

from __future__ import annotations

from typing import Any, Iterable


PRIORITY_TO_SUSPICION = {
    "A": "HIGHEST_SUSPICION",
    "B": "HIGH_SUSPICION",
    "C": "MODERATE_SUSPICION",
}

SUSPICION_TO_PRIORITY = {label: priority for priority, label in PRIORITY_TO_SUSPICION.items()}

SUSPICION_FOLDER = {
    "HIGHEST_SUSPICION": "highest_suspicion",
    "HIGH_SUSPICION": "high_suspicion",
    "MODERATE_SUSPICION": "moderate_suspicion",
}


def suspicion_level(priority_class: Any) -> str | None:
    """Return the stable review label for an internal A/B/C priority class."""
    if priority_class in (None, ""):
        return None
    return PRIORITY_TO_SUSPICION.get(str(priority_class).strip().upper())


def normalized_suspicion_levels(values: Iterable[Any] | None) -> set[str] | None:
    """Accept either public suspicion labels or legacy A/B/C filter values."""
    if values is None:
        return None
    output: set[str] = set()
    for value in values:
        item = str(value).strip().upper()
        label = PRIORITY_TO_SUSPICION.get(item, item)
        if label not in SUSPICION_TO_PRIORITY:
            raise ValueError(
                f"Unknown suspicion level {value!r}; expected one of "
                f"{tuple(PRIORITY_TO_SUSPICION)} or {tuple(SUSPICION_TO_PRIORITY)}"
            )
        output.add(label)
    return output


__all__ = [
    "PRIORITY_TO_SUSPICION",
    "SUSPICION_TO_PRIORITY",
    "SUSPICION_FOLDER",
    "suspicion_level",
    "normalized_suspicion_levels",
]

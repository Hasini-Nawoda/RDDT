"""Step 04 — match configured atoms to structured and NLP source events."""

from typing import Any, Iterable

from ..extraction.atom_matching import match_atom_events


def match_atoms(
    events: Iterable[Any],
    config: Any,
    *,
    nlp: Any = None,
    terminology_mode: str = "ALL",
    terminology_systems: Any = None,
) -> list[Any]:
    return list(
        match_atom_events(
            events,
            config,
            config_hash=config.config_hash,
            nlp=nlp,
            terminology_mode=terminology_mode,
            terminology_systems=terminology_systems,
        )
    )


__all__ = ["match_atoms"]

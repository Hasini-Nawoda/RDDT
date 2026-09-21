"""Step 05 — apply temporal, negation, experiencer, and context qualification."""

from typing import Any, Iterable

from ..extraction.evidence_qualification import qualify_atom_matches


def qualify_evidence(
    matches: Iterable[Any],
    config: Any,
    *,
    context_processor: Any = None,
    screening_cutoff: Any,
    evaluation_mode: str = "STRICT",
) -> list[Any]:
    return list(qualify_atom_matches(
        matches,
        config,
        context_processor=context_processor,
        screening_cutoff=screening_cutoff,
        evaluation_mode=evaluation_mode,
    ))


__all__ = ["qualify_evidence"]

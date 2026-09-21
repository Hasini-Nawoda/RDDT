"""Step 03b — separate known/confirmed patients before phenotype scoring."""

from __future__ import annotations

from typing import Any, Iterable

from ..extraction.known_attr import KnownAttrConfig, KnownAttrResult, identify_known_attr


def separate_known_attr(
    events: Iterable[Any],
    *,
    run_id: str,
    screening_cutoff: Any,
    known_attr_config: KnownAttrConfig,
    nlp: Any = None,
    context_processor: Any = None,
    terminology_mode: str = "ALL",
    terminology_systems: Any = None,
) -> tuple[KnownAttrResult, list[Any]]:
    all_events = list(events)
    result = identify_known_attr(
        all_events,
        run_id=run_id,
        screening_cutoff=screening_cutoff,
        nlp=nlp,
        context_processor=context_processor,
        config=known_attr_config,
        terminology_mode=terminology_mode,
        terminology_systems=terminology_systems,
    )
    screened_events = [event for event in all_events if event.patient_id not in result.patient_ids]
    return result, screened_events


__all__ = ["separate_known_attr"]

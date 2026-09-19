"""Step 03 — normalize candidate source rows into lineage-preserving events."""

from typing import Any, Iterable, Mapping

from ..extraction.source_events import iter_source_events


def build_source_events(rows_by_table: Mapping[str, Iterable[Mapping[str, Any]]], *, run_id: str, config_hash: str, source_config: Mapping[str, Any], candidate_patient_ids: set[str] | None = None) -> list[Any]:
    return list(iter_source_events(rows_by_table, run_id=run_id, config_hash=config_hash, source_config=source_config, candidate_patient_ids=candidate_patient_ids))


__all__ = ["build_source_events"]

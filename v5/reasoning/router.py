"""Phenotype-generic V5 result and router output construction."""
from __future__ import annotations

from typing import Any, Iterable

from ..evaluation_policy import (
    CLAIMS_RECALL,
    collect_relaxations,
    is_provisional,
    normalize_evaluation_mode,
)
from .explain import build_explanation, build_trace
from .priority import resolve_priority
from .reasoning_utils import FALSE, TRUE, UNKNOWN, configured_phenotype, norm_status, value
from .risk_labels import suspicion_level


def route_results(
    config: Any,
    combination_hits: Iterable[Any],
    *,
    guardrail_hits: Iterable[Any] = (),
    patient_id: Any = None,
    phenotype: str | None = None,
    run_id: Any = None,
    config_hash: str | None = None,
    implementation_version: str = "v5",
    evaluation_mode: str = "STRICT",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evaluation_mode = normalize_evaluation_mode(evaluation_mode)
    phenotype = configured_phenotype(config, phenotype)
    combos = list(combination_hits)
    guards = list(guardrail_hits)
    true_combos = [
        c for c in combos
        if norm_status(value(c, "status", UNKNOWN)) == TRUE
        and str(value(c, "outcome", "") or "").upper() != "ROUTE_ONLY"
    ]
    route_only_combos = [
        c for c in combos
        if norm_status(value(c, "status", UNKNOWN)) == TRUE
        and str(value(c, "outcome", "") or "").upper() == "ROUTE_ONLY"
    ]
    priority_rank = {"A": 0, "B": 1, "C": 2}
    resolved = [
        (c, resolve_priority(config, c, list(value(c, "selected_witnesses", ()) or ())))
        for c in true_combos
    ]
    resolved.sort(key=lambda item: (
        1 if is_provisional(item[0]) else 0,
        priority_rank.get(str(item[1].get("priority_class") or "").upper(), 99),
        str(value(item[0], "combination_id", "")),
    ))
    true_combo = resolved[0][0] if resolved else None
    # Differential/route-only combinations are parallel clinical routes, not
    # phenotype passes.  They must never become the selected ATTR profile or
    # affect the main PASS/HOLD/UNKNOWN decision.
    evaluable_combos = [
        c for c in combos
        if str(value(c, "outcome", "") or "").upper() != "ROUTE_ONLY"
    ]
    hold_combo = next((c for c in evaluable_combos if value(c, "hold_reason", None)), None)
    if true_combo is not None:
        status = "CLAIMS_RECALL_CANDIDATE" if is_provisional(true_combo) else "PHENOTYPE_PASS"
        selected = list(value(true_combo, "selected_witnesses", ()) or ())
        priority = resolved[0][1]
        combo = true_combo
    elif hold_combo is not None:
        status = "HOLD"
        priority = {"priority_class": None}
        combo = hold_combo
    elif any(norm_status(value(c, "status", UNKNOWN)) == UNKNOWN for c in evaluable_combos):
        status = "UNKNOWN"
        priority = {"priority_class": None}
        combo = next((c for c in evaluable_combos if norm_status(value(c, "status", UNKNOWN)) == UNKNOWN), None)
    else:
        status = "NO_MATCH"
        priority = {"priority_class": None}
        combo = None
    active_guards = [g for g in guards if norm_status(value(g, "status", UNKNOWN)) == TRUE]
    guard_ids = tuple(str(value(g, "guardrail_id", "")) for g in active_guards)
    parallel_values = [
        str(value(g, "route", "")) for g in active_guards if value(g, "route", None)
    ]
    parallel_values.extend(
        str(value(c, "result_route", ""))
        for c in route_only_combos
        if value(c, "result_route", None)
    )
    parallel = tuple(dict.fromkeys(parallel_values))
    result = {
        "run_id": run_id,
        "patient_id": patient_id,
        "phenotype": phenotype,
        "status": status,
        "result_route": value(combo, "result_route", None) if combo is not None else "NO_MATCH",
        "priority_class": priority.get("priority_class"),
        "suspicion_level": suspicion_level(priority.get("priority_class")),
        "matched_combination_id": value(combo, "combination_id", None) if combo is not None and status in {"PHENOTYPE_PASS", "CLAIMS_RECALL_CANDIDATE"} else None,
        "supporting_signal_ids": tuple(value(combo, "supporting_signal_ids", ()) or ()) if combo is not None else (),
        "supporting_buckets": tuple(value(combo, "supporting_buckets", ()) or ()) if combo is not None else (),
        "support_lineage_ids": tuple(value(combo, "support_lineage_ids", ()) or ()) if combo is not None else (),
        "supporting_event_dates": tuple(value(combo, "supporting_event_dates", ()) or ()) if combo is not None else (),
        "guardrail_ids": guard_ids,
        "parallel_routes": parallel,
        "clinical_rationale": value(combo, "clinical_rationale", None) if combo is not None else None,
        "config_hash": config_hash or value(config, "config_hash", None),
        "implementation_version": implementation_version,
        "evaluation_mode": evaluation_mode,
        "verdict_scope": "CLAIMS_ONLY_RECALL" if evaluation_mode == CLAIMS_RECALL else "STRICT_CLINICAL_EVIDENCE",
        "provisional": bool(combo is not None and is_provisional(combo)),
        "relaxations": collect_relaxations([combo]) if combo is not None else (),
    }
    result["explanation"] = build_explanation(result)
    result["pipeline_trace"] = build_trace(result, implementation_version=implementation_version)
    router = dict(result)
    router["router_schema_version"] = "V5_PHENOTYPE_GENERIC"
    return [result], [router]


build_results = route_results
route = route_results

"""Workbook-defined guardrail and parallel-route evaluation."""
from __future__ import annotations

from typing import Any, Iterable

from .reasoning_utils import FALSE, TRUE, UNKNOWN, norm_status, rows, tri_all, tri_any, value
from .signal_engine import _evaluate_signal_rule


def _required(text: str) -> dict[str, str]:
    lower = text.lower()
    start = lower.find("[required:")
    if start < 0:
        return {}
    end = text.find("]", start)
    if end < 0:
        return {}
    out: dict[str, str] = {}
    for part in text[start + len("[required:"):end].split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _obs_status(atom_id: str, evidence: list[Any], required: dict[str, str]) -> tuple[str, list[Any]]:
    found: list[Any] = []
    unknown: list[Any] = []
    for ev in evidence:
        if str(value(ev, "atom_id", "")) != atom_id:
            continue
        status = norm_status(value(ev, "status", UNKNOWN))
        attrs = value(ev, "attributes", {}) or {}
        q = TRUE
        for key, wanted in required.items():
            got = value(ev, key, None)
            if got is None and isinstance(attrs, dict):
                got = attrs.get(key)
            if got is None:
                q = UNKNOWN
                break
            if str(got).strip().lower() != wanted.strip().lower():
                q = FALSE
                break
        if status == TRUE and q == TRUE:
            found.append(ev)
        elif status == UNKNOWN or q == UNKNOWN:
            unknown.append(ev)
    if found:
        return TRUE, found
    return (UNKNOWN if unknown else FALSE), unknown


def _condition(config: Any, text: Any, evidence: list[Any]) -> tuple[str, list[Any], str]:
    if isinstance(text, dict):
        op = str(text.get("operator", text.get("op", "ANY"))).upper()
        children = text.get("children", text.get("members", []))
        vals = [_condition(config, c, evidence) for c in children]
        statuses = [x[0] for x in vals]
        status = tri_all(statuses) if op in {"ALL", "ALL_OF"} else tri_any(statuses) if op in {"ANY", "ANY_OF"} else UNKNOWN
        return status, [e for _, evs, _ in vals for e in evs], f"workbook condition {op}"
    raw = str(text or "").strip()
    obs: list[tuple[int, int, str]] = []
    upper = raw.upper()
    cursor = 0
    while True:
        start = upper.find("OBSERVE(", cursor)
        if start < 0:
            break
        end = raw.find(")", start + len("OBSERVE("))
        if end < 0:
            return UNKNOWN, [], "CONFIG_GAP:unrepresentable guardrail condition"
        obs.append((start, end, raw[start + len("OBSERVE("):end].strip()))
        cursor = end + 1
    if not obs:
        return UNKNOWN, [], "CONFIG_GAP:unrepresentable guardrail condition"
    statuses: list[str] = []
    selected: list[Any] = []
    for start, end, atom_id in obs:
        # Include a trailing qualifier clause when present in this member.
        qualifier_end = raw.find("]", end)
        snippet = raw[start:qualifier_end + 1] if qualifier_end >= 0 else raw[start:end + 1]
        st, evs = _obs_status(atom_id, evidence, _required(snippet))
        statuses.append(st); selected.extend(evs)
    # The normalized workbook's prose uses explicit ANY OF/ALL OF markers.
    # For a single OBSERVE the direct status is exact.  For multiple markers,
    # evaluate the outermost declared operator; nested semantics are retained
    # as UNKNOWN rather than silently flattened to a positive.
    if len(obs) == 1:
        status = statuses[0]
    elif "ALL OF:" in upper and "ANY OF:" not in upper:
        status = tri_all(statuses)
    elif "ANY OF:" in upper and "ALL OF:" not in upper:
        status = tri_any(statuses)
    else:
        # Nested mixed expressions require the structured compiler form.  Do
        # not over-call a route when the text cannot be represented exactly.
        status = UNKNOWN
    return status, selected if status == TRUE else [], "workbook guardrail condition"


def _structured_condition(
    config: Any,
    rule_id: str,
    evidence: list[Any],
) -> tuple[str, list[Any], str] | None:
    """Evaluate a guardrail's normalized workbook rule AST when available."""
    rules = [r for r in rows(config, "signal_rules") if str(value(r, "signal_id", "")) == rule_id]
    groups = [g for g in rows(config, "signal_rule_groups") if str(value(g, "signal_id", "")) == rule_id]
    members = [m for m in rows(config, "signal_rule_members") if str(value(m, "signal_id", "")) == rule_id]
    if not rules or not groups:
        return None
    catalog = [
        row for row in rows(config, "signals_catalog")
        if str(value(row, "signal_id", "")) == rule_id
    ]
    if len(catalog) != 1:
        return UNKNOWN, [], f"CONFIG_GAP:guardrail signal catalog {rule_id} is not unique"
    signal = dict(catalog[0])
    enabled = value(signal, "enabled", True)
    if enabled is False or str(enabled).upper() == "FALSE":
        return UNKNOWN, [], f"CONFIG_GAP:guardrail {rule_id} disabled"
    runtime = str(value(signal, "runtime_executability", "EXECUTABLE") or "EXECUTABLE").upper()
    if runtime in {"NON_EXECUTABLE", "NON_FIRING", "BLOCKED"}:
        return UNKNOWN, [], f"CONFIG_GAP:guardrail {rule_id} {runtime}"
    signal["signal_id"] = rule_id
    signal.setdefault("config_action", "GUARDRAIL")
    status, support, unknown, reason, _witness_sets = _evaluate_signal_rule(config, signal, evidence)
    if status == TRUE:
        return status, support, "workbook guardrail rule"
    # Preserve unknown witnesses for an auditable route explanation, but do not
    # return them as positive supporting evidence.
    return status, unknown, reason


def evaluate_guardrails(config: Any, evidence: Iterable[Any], *, patient_id: Any = None, phenotype: str | None = None) -> list[dict[str, Any]]:
    ev = list(evidence)
    if patient_id is not None:
        ev = [e for e in ev if value(e, "patient_id", patient_id) == patient_id]
    out: list[dict[str, Any]] = []
    for guard in rows(config, "guardrails"):
        enabled = value(guard, "enabled", True)
        if enabled is False or str(enabled).upper() == "FALSE":
            continue
        guard_id = str(value(guard, "guardrail_id", value(guard, "rule_id", "")))
        rule_ref = str(value(guard, "rule_ref", value(guard, "condition_rule_ref", guard_id)) or guard_id)
        catalog = [
            row for row in rows(config, "signals_catalog")
            if str(value(row, "signal_id", "")) == rule_ref
        ]
        if len(catalog) != 1:
            status, supporting, reason = UNKNOWN, [], f"CONFIG_GAP:guardrail signal catalog {rule_ref} is not unique"
        else:
            catalog_row = catalog[0]
            catalog_enabled = value(catalog_row, "enabled", True)
            if catalog_enabled is False or str(catalog_enabled).upper() == "FALSE":
                continue
            runtime = str(value(catalog_row, "runtime_executability", "EXECUTABLE") or "EXECUTABLE").upper()
            if runtime in {"NON_EXECUTABLE", "NON_FIRING", "BLOCKED"}:
                status, supporting, reason = UNKNOWN, [], f"CONFIG_GAP:guardrail {rule_ref} {runtime}"
            else:
                structured = _structured_condition(config, rule_ref, ev)
                if structured is not None:
                    status, supporting, reason = structured
                else:
                    status, supporting, reason = _condition(config, value(guard, "clinical_condition", value(guard, "condition", None)), ev)
        out.append({
            "patient_id": patient_id,
            "phenotype": phenotype or value(guard, "phenotype", None),
            "guardrail_id": guard_id,
            "status": status,
            "guardrail_action": value(guard, "guardrail_action", value(guard, "action", None)),
            "route": value(guard, "route", value(guard, "route_to", None)),
            "does_not_negate_attrv": value(guard, "does_not_negate_attrv", value(guard, "does_not_negate", None)),
            "message": value(guard, "message", None),
            "support_lineage_ids": tuple(sorted({str(x) for e in supporting for x in (value(e, "support_lineage_ids", ()) or ())})),
            "supporting_evidence_ids": tuple(str(value(e, "evidence_id", "")) for e in supporting),
            "explanation": reason,
            "config_hash": getattr(config, "config_hash", None) if not isinstance(config, dict) else config.get("config_hash"),
        })
    return out


evaluate = evaluate_guardrails
run = evaluate_guardrails

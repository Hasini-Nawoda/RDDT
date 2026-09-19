"""Categorical priority lookup from workbook policy rows."""
from __future__ import annotations

from typing import Any, Iterable

from .reasoning_utils import rows, value


def _pattern(value_: Any) -> tuple[str, ...]:
    if isinstance(value_, (list, tuple)):
        return tuple(str(x).strip() for x in value_)
    text = str(value_ or "").strip()
    if not text:
        return ()
    # Preserve order.  A policy's pattern is categorical, not arithmetic.
    tokens: list[str] = []
    current: list[str] = []
    for char in text:
        if char in "+|/":
            token = "".join(current).strip()
            if token:
                tokens.append(token)
            current = []
        else:
            current.append(char)
    token = "".join(current).strip()
    if token:
        tokens.append(token)
    return tuple(tokens)


def resolve_priority(config: Any, combination: Any, selected_witnesses: Iterable[Any] = ()) -> dict[str, Any]:
    policy_id = value(combination, "priority_policy_id", None)
    tiers = tuple(str(value(w, "tier", "")) for w in selected_witnesses)
    # The workbook's requirement order is the canonical pattern order.  Do
    # not sort tiers or derive a score.
    policies = [p for p in rows(config, "priority_policies") if str(value(p, "priority_policy_id", "")) == str(policy_id)]
    fixed = [p for p in policies if str(value(p, "kind", value(p, "policy_kind", ""))).upper() == "FIXED"]
    if fixed:
        policy = fixed[0]
        return {
            "priority_class": value(policy, "priority_class", value(policy, "class", None)),
            "policy_id": policy_id,
            "tier_pattern": tiers,
            "status": "TRUE",
            "reason": "fixed workbook priority policy",
            "config_hash": value(config, "config_hash", None),
        }
    exact = [p for p in policies if _pattern(value(p, "tier_pattern", None)) == tiers]
    if not exact and policies:
        # Some callers provide a normalized pattern already on the match row.
        pattern = value(combination, "tier_pattern", None)
        exact = [p for p in policies if _pattern(value(p, "tier_pattern", None)) == _pattern(pattern)] if pattern else []
    if not exact:
        return {
            "priority_class": None,
            "policy_id": policy_id,
            "tier_pattern": tiers,
            "status": "UNKNOWN" if policy_id else "CONFIG_GAP",
            "reason": "no exact categorical priority policy match",
            "config_hash": value(config, "config_hash", None),
        }
    policy = exact[0]
    return {
        "priority_class": value(policy, "priority_class", value(policy, "class", None)),
        "policy_id": policy_id,
        "tier_pattern": tiers,
        "status": "TRUE",
        "reason": "exact workbook priority policy",
        "config_hash": value(config, "config_hash", None),
    }


resolve = resolve_priority
run = resolve_priority

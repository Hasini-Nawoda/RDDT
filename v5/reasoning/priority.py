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


def _witness_weakened(witness: Any) -> bool:
    return bool(value(witness, "context_gaps", None)) or "TIER_DROP" in str(value(witness, "tier_basis", "") or "")


def _one_class_down(priority_class: Any) -> Any:
    return {"A": "B", "B": "C"}.get(str(priority_class or "").upper(), priority_class)


def _lower_for_missing_claim_context(result: dict[str, Any], selected_witnesses: Iterable[Any]) -> dict[str, Any]:
    """Drop a fixed route one step when its main signal is the weak one.

    The first selected witness is the combination's main arm. A missing
    qualifier or a proxy code on that arm lowers highest to high, or high to
    moderate. A gap on a later supporting arm does not move the class.
    Pair patterns already use the weakened tier, so they are not lowered again.
    """
    witnesses = list(selected_witnesses)
    if not witnesses or not _witness_weakened(witnesses[0]):
        return result
    lowered = _one_class_down(result.get("priority_class"))
    if lowered == result.get("priority_class"):
        return result
    return {
        **result,
        "priority_class": lowered,
        "status": "TRUE",
        "reason": "the main signal lacked its full context, so suspicion is one step lower",
    }


def resolve_priority(config: Any, combination: Any, selected_witnesses: Iterable[Any] = ()) -> dict[str, Any]:
    policy_id = value(combination, "priority_policy_id", None)
    tiers = tuple(str(value(w, "tier", "")) for w in selected_witnesses)
    # The workbook's requirement order is the canonical pattern order.  Do
    # not sort tiers or derive a score.
    policies = [p for p in rows(config, "priority_policies") if str(value(p, "priority_policy_id", "")) == str(policy_id)]
    direct = [
        p for p in policies
        if str(value(p, "kind", value(p, "policy_kind", ""))).upper()
        in {"FIXED", "NAMED_ROUTE"}
    ]
    if direct:
        policy = direct[0]
        kind = str(value(policy, "kind", value(policy, "policy_kind", "FIXED"))).upper()
        return _lower_for_missing_claim_context({
            "priority_class": value(policy, "priority_class", value(policy, "class", None)),
            "policy_id": policy_id,
            "tier_pattern": tiers,
            "status": "TRUE",
            "reason": f"{kind.lower().replace('_', ' ')} workbook priority policy",
            "config_hash": value(config, "config_hash", None),
        }, selected_witnesses)
    exact = [p for p in policies if _pattern(value(p, "tier_pattern", None)) == tiers]
    if not exact and policies:
        # Some callers provide a normalized pattern already on the match row.
        pattern = value(combination, "tier_pattern", None)
        exact = [p for p in policies if _pattern(value(p, "tier_pattern", None)) == _pattern(pattern)] if pattern else []
    if not exact:
        weakened = any(
            value(witness, "context_gaps", None)
            or "TIER_DROP" in str(value(witness, "tier_basis", "") or "")
            for witness in selected_witnesses
        )
        if weakened:
            # The dropped tiers do not match a workbook pair. The pass stands
            # at moderate rather than disappearing.
            return {
                "priority_class": "C",
                "policy_id": policy_id,
                "tier_pattern": tiers,
                "status": "TRUE",
                "reason": "claim code lacked the signal's full context, so suspicion is moderate",
                "config_hash": value(config, "config_hash", None),
            }
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

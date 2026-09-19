"""Named-combination matcher with lineage-safe backtracking.

Only combinations and requirement restrictions supplied by the compiled
workbook are evaluated.  There is intentionally no fallback any-two-bucket
rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from itertools import combinations as witness_combinations
from typing import Any, Iterable

from .reasoning_utils import FALSE, TRUE, UNKNOWN, as_list, dedup_key, independent, norm_status, rows, union_lineage, value


@dataclass(frozen=True)
class Requirement:
    requirement_id: str
    combination_id: str
    order: int
    kind: str
    allowed_buckets: frozenset[str]
    allowed_tiers: frozenset[str]
    allowed_signal_ids: frozenset[str]
    context_witness_allowed: bool
    distinct_lineage_required: bool
    minimum_count: int | None = None
    notes: str | None = None


def _bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().upper() in {"TRUE", "1", "YES", "Y"}


def _tier_match(actual: Any, allowed: frozenset[str]) -> bool:
    if not allowed:
        return True
    a = str(actual)
    return a in allowed or a.upper() in {x.upper() for x in allowed}


def _requirements(config: Any, combination_id: str) -> list[Requirement]:
    raw = [r for r in rows(config, "combination_requirements") if str(value(r, "combination_id", "")) == combination_id]
    bmap: dict[str, set[str]] = {}
    tmap: dict[str, set[str]] = {}
    smap: dict[str, set[str]] = {}
    for r in rows(config, "requirement_buckets"):
        bmap.setdefault(str(value(r, "requirement_id", "")), set()).add(str(value(r, "reasoning_bucket", "")))
    for r in rows(config, "requirement_tiers"):
        tmap.setdefault(str(value(r, "requirement_id", "")), set()).add(str(value(r, "allowed_tier", "")))
    for r in rows(config, "requirement_signals"):
        smap.setdefault(str(value(r, "requirement_id", "")), set()).add(str(value(r, "allowed_signal_id", "")))
    out: list[Requirement] = []
    for r in raw:
        rid = str(value(r, "requirement_id", ""))
        # ``minimum_count`` is a workbook-level cardinality contract.  The
        # witness matcher operates on one arm per Requirement, so expand an
        # arm such as "at least two of these signals" into two equivalent
        # arms.  The normal lineage/conflict checks then require independent
        # evidence for each occurrence.  This keeps the behavior generic for
        # every phenotype rather than encoding ATTRwt-specific logic here.
        raw_minimum = value(r, "minimum_count", None)
        try:
            minimum_count = max(1, int(raw_minimum or 1))
        except (TypeError, ValueError):
            minimum_count = 1
        common = dict(
            combination_id=combination_id,
            order=int(value(r, "requirement_order", 0) or 0),
            kind=str(value(r, "requirement_kind", "BUCKET") or "BUCKET"),
            allowed_buckets=frozenset(x for x in bmap.get(rid, set()) if x),
            allowed_tiers=frozenset(x for x in tmap.get(rid, set()) if x),
            allowed_signal_ids=frozenset(x for x in smap.get(rid, set()) if x),
            context_witness_allowed=_bool(value(r, "context_witness_allowed", False)),
            distinct_lineage_required=_bool(value(r, "distinct_lineage_required", True), True),
            minimum_count=minimum_count,
            notes=value(r, "notes", None),
        )
        for occurrence in range(1, minimum_count + 1):
            expanded_id = rid if minimum_count == 1 else f"{rid}__{occurrence}"
            out.append(Requirement(requirement_id=expanded_id, **common))
    return sorted(out, key=lambda r: (r.order, r.requirement_id))


def _eligible_shape(hit: Any, requirement: Requirement, *, allow_unknown: bool = False) -> bool:
    status = norm_status(value(hit, "status", UNKNOWN))
    if status != TRUE and not (allow_unknown and status == UNKNOWN):
        return False
    bucket = str(value(hit, "reasoning_bucket", ""))
    if requirement.allowed_buckets and bucket not in requirement.allowed_buckets:
        return False
    if not _tier_match(value(hit, "tier", None), requirement.allowed_tiers):
        return False
    signal = str(value(hit, "signal_id", ""))
    if requirement.allowed_signal_ids and signal not in requirement.allowed_signal_ids:
        return False
    gate = str(value(hit, "gate_role", "") or "").upper()
    is_context = "CONTEXT" in gate or gate in {"T3", "CONTEXT_ONLY", "CONTEXT_EVIDENCE"}
    if is_context and not requirement.context_witness_allowed:
        return False
    # UNKNOWN witnesses may lack affirmative support lineage precisely because
    # qualification could not finish.  They can make a combination UNKNOWN,
    # but never TRUE.  Affirmative witnesses still require lineage.
    return status == UNKNOWN or bool(value(hit, "support_lineage_ids", None))


def eligible_hit(hit: Any, requirement: Requirement) -> bool:
    return _eligible_shape(hit, requirement, allow_unknown=False)


def _conflicts(candidate: Any, chosen: list[Any], req: Requirement, bucket_defs: dict[str, Any]) -> bool:
    for old in chosen:
        if req.distinct_lineage_required and not independent(candidate, old):
            return True
        # A bucket explicitly marked as non-independent cannot satisfy two
        # independent requirement arms.  We do not infer this from specialty.
        cb, ob = str(value(candidate, "reasoning_bucket", "")), str(value(old, "reasoning_bucket", ""))
        if cb and cb == ob and not bool(value(bucket_defs.get(cb), "counts_independently", True)):
            return True
    return False


def assign_witnesses(combination: Any, requirements: list[Requirement], candidate_hits: list[Any], bucket_defs: dict[str, Any] | None = None, *, allow_unknown: bool = False) -> tuple[list[Any] | None, list[tuple[str, tuple[str, ...]]]]:
    bucket_defs = bucket_defs or {}
    candidate_map = {
        r.requirement_id: [
            h for h in candidate_hits
            if _eligible_shape(h, r, allow_unknown=allow_unknown)
        ]
        for r in requirements
    }
    conflicts: list[tuple[str, tuple[str, ...]]] = []

    def rec(index: int, chosen: list[Any]) -> list[Any] | None:
        if index >= len(requirements):
            return list(chosen)
        req = requirements[index]
        for hit in candidate_map[req.requirement_id]:
            if _conflicts(hit, chosen, req, bucket_defs):
                conflicts.append((req.requirement_id, tuple(sorted(str(x) for x in (value(hit, "support_lineage_ids", ()) or ())))))
                continue
            result = rec(index + 1, chosen + [hit])
            if result is not None:
                return result
        return None

    return rec(0, []), conflicts


def _dedupe_witness_sets(witness_sets: list[list[Any]]) -> list[list[Any]]:
    seen: set[tuple[tuple[str, ...], ...]] = set()
    output: list[list[Any]] = []
    for witness_set in witness_sets:
        key = tuple(sorted(tuple(sorted(str(x) for x in (value(w, "support_lineage_ids", ()) or ()))) for w in witness_set))
        if key not in seen:
            seen.add(key)
            output.append(witness_set)
    return output


def _temporal_state(combination: Any, witnesses: list[Any]) -> str:
    """Evaluate the small, explicit temporal contract used by ATTRwt.

    Temporal order is a clinical rule, not an inferred score.  Missing or
    unparsable dates remain UNKNOWN so the paired null-chronology rule can
    route the patient without treating missing dates as a documented negative.
    """
    policy = str(value(combination, "temporal_policy", "") or "").upper()
    if not policy or policy in {"NO_FIXED_ORDER", "NONE"}:
        return TRUE

    def parsed(raw: Any) -> datetime | None:
        if raw in (None, ""):
            return None
        try:
            if isinstance(raw, datetime):
                result = raw
            elif isinstance(raw, date):
                result = datetime.combine(raw, datetime.min.time())
            else:
                result = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if result.tzinfo is not None:
                result = result.astimezone().replace(tzinfo=None)
            return result
        except (TypeError, ValueError):
            return None

    by_bucket: dict[str, list[datetime]] = {}
    missing_date = False
    for witness in witnesses:
        bucket = str(value(witness, "reasoning_bucket", "")).upper()
        raw_dates = value(witness, "event_dates", ()) or ()
        dates = [parsed(item) for item in raw_dates]
        dates = [item for item in dates if item is not None]
        if not bucket or not dates:
            # A selected witness with no reliable event date makes chronology
            # indeterminate, rather than silently satisfying a temporal gate.
            by_bucket.setdefault(bucket, [])
            missing_date = True
            continue
        by_bucket.setdefault(bucket, []).extend(dates)

    if policy in {"ORTHO_BEFORE_CARDIO", "PAIR_TEMPORAL", "ORTHOPEDIC_BEFORE_CARDIAC_WHEN_AVAILABLE"}:
        ortho = by_bucket.get("ORTHO", [])
        cardio = by_bucket.get("CARDIO", [])
        if not ortho or not cardio:
            return UNKNOWN
        return TRUE if min(ortho) < min(cardio) else FALSE
    if policy == "REQUIRE_UNKNOWN":
        # This branch is used only for a paired rule whose contract is the
        # unresolved chronology case (WT_RULE_02).
        if missing_date or not by_bucket.get("ORTHO") or not by_bucket.get("CARDIO"):
            return UNKNOWN
        return FALSE
    return UNKNOWN


def _hit_alternatives(hit: Any) -> list[Any]:
    raw = value(hit, "supporting_witnesses", None)
    if not raw:
        return [hit]
    output: list[Any] = []
    for witness_set in raw:
        clone = dict(hit) if isinstance(hit, dict) else hit
        if isinstance(clone, dict):
            clone = dict(clone)
            clone["support_lineage_ids"] = union_lineage(witness_set)
        output.append(clone)
    return output or [hit]


def _evaluate_rule_group(
    rule_id: str,
    group_id: str,
    hits: list[Any],
    groups: dict[str, Any],
) -> tuple[str, list[list[Any]], list[Any]]:
    group = groups.get(group_id)
    if group is None:
        return UNKNOWN, [], []
    children: list[tuple[list[list[Any]], list[Any]]] = []
    for member in value(group, "members", ()) or ():
        member_type = str(value(member, "type", value(member, "member_type", "SIGNAL"))).upper()
        member_id = str(value(member, "id", value(member, "member_id", "")))
        if member_type == "GROUP":
            _, alternatives, unknown = _evaluate_rule_group(rule_id, member_id, hits, groups)
        else:
            alternatives = [
                [alternative]
                for hit in hits
                if str(value(hit, "signal_id", "")) == member_id
                and norm_status(value(hit, "status", UNKNOWN)) == TRUE
                for alternative in _hit_alternatives(hit)
            ]
            unknown = [
                hit for hit in hits
                if str(value(hit, "signal_id", "")) == member_id
                and norm_status(value(hit, "status", UNKNOWN)) == UNKNOWN
            ]
        children.append((alternatives, unknown))

    operator = str(value(group, "operator", "ANY") or "ANY").upper()
    require_independent = _bool(value(group, "require_independent_lineage", False)) or operator == "INDEPENDENT_ALL"

    def valid(witnesses: list[Any]) -> bool:
        return not require_independent or all(
            independent(left, right) for left, right in witness_combinations(witnesses, 2)
        )

    unknown_rows = [row for _, unknown in children for row in unknown]
    if operator in {"ANY", "OR"}:
        alternatives = [choice for choices, _ in children for choice in choices]
        return (TRUE, _dedupe_witness_sets(alternatives), unknown_rows) if alternatives else (
            UNKNOWN if unknown_rows else FALSE, [], unknown_rows
        )
    if operator in {"ALL", "LINKED_ALL", "INDEPENDENT_ALL"}:
        if any(not choices for choices, _ in children):
            return (UNKNOWN if unknown_rows else FALSE), [], unknown_rows
        products: list[list[Any]] = [[]]
        for choices, _ in children:
            products = [prefix + suffix for prefix in products for suffix in choices]
        selected = [candidate for candidate in products if valid(candidate)]
        return (TRUE, _dedupe_witness_sets(selected), unknown_rows) if selected else (UNKNOWN, [], unknown_rows)
    if operator in {"AT_LEAST", "MINIMUM", "MIN_COUNT"}:
        minimum = int(value(group, "minimum_count", 1) or 1)
        selected: list[list[Any]] = []
        for count in range(minimum, len(children) + 1):
            for indices in witness_combinations(range(len(children)), count):
                if any(not children[index][0] for index in indices):
                    continue
                products: list[list[Any]] = [[]]
                for index in indices:
                    products = [prefix + suffix for prefix in products for suffix in children[index][0]]
                selected.extend(candidate for candidate in products if valid(candidate))
            if selected:
                break
        if selected:
            return TRUE, _dedupe_witness_sets(selected), unknown_rows
        partial_true = any(choices for choices, _ in children)
        return (UNKNOWN if unknown_rows or partial_true else FALSE), [], unknown_rows
    return UNKNOWN, [], unknown_rows


def _evaluate_nested_combination(rule_id: str, rule: Any, hits: list[Any]) -> tuple[str, list[Any], str | None]:
    if not isinstance(rule, dict) or not _bool(value(rule, "enabled", True), True):
        return UNKNOWN, [], "CONFIG_GAP:missing or disabled nested combination rule"
    group_rows = list(value(rule, "groups", ()) or ())
    groups = {str(value(group, "group_id", value(group, "id", ""))): group for group in group_rows}
    if not groups:
        return UNKNOWN, [], "CONFIG_GAP:nested combination has no groups"
    referenced = {
        str(value(member, "id", value(member, "member_id", "")))
        for group in group_rows
        for member in (value(group, "members", ()) or ())
        if str(value(member, "type", value(member, "member_type", ""))).upper() == "GROUP"
    }
    roots = [group for group_id, group in groups.items() if group_id not in referenced]
    roots.sort(key=lambda group: int(value(group, "evaluation_order", 0) or 0))
    evaluations = [
        _evaluate_rule_group(rule_id, str(value(group, "group_id", value(group, "id", ""))), hits, groups)
        for group in roots
    ]
    operator = str(value(rule, "operator", value(rule, "top_operator", "ALL")) or "ALL").upper()
    require_independent = operator == "INDEPENDENT_ALL" or any(
        _bool(value(group, "require_independent_lineage", False)) for group in group_rows
    )

    def valid(witnesses: list[Any]) -> bool:
        return not require_independent or all(
            independent(left, right) for left, right in witness_combinations(witnesses, 2)
        )

    unknown_present = any(unknown for _, _, unknown in evaluations)
    if operator in {"ALL", "LINKED_ALL", "INDEPENDENT_ALL"}:
        if any(not alternatives for _, alternatives, _ in evaluations):
            return (UNKNOWN if unknown_present else FALSE), [], (
                "INCOMPLETE_OR_UNKNOWN_EVIDENCE" if unknown_present else None
            )
        products: list[list[Any]] = [[]]
        for _, alternatives, _ in evaluations:
            products = [prefix + suffix for prefix in products for suffix in alternatives]
        selected_sets = [candidate for candidate in products if valid(candidate)]
    elif operator in {"ANY", "OR"}:
        selected_sets = [choice for _, alternatives, _ in evaluations for choice in alternatives]
    else:
        minimum = int(value(rule, "minimum_count", 1) or 1)
        selected_sets = []
        for count in range(minimum, len(evaluations) + 1):
            for indices in witness_combinations(range(len(evaluations)), count):
                if any(not evaluations[index][1] for index in indices):
                    continue
                products: list[list[Any]] = [[]]
                for index in indices:
                    products = [prefix + suffix for prefix in products for suffix in evaluations[index][1]]
                selected_sets.extend(candidate for candidate in products if valid(candidate))
            if selected_sets:
                break
    selected_sets = _dedupe_witness_sets(selected_sets)
    if selected_sets:
        selected_sets.sort(key=lambda items: (len(items), tuple(sorted(str(value(item, "signal_id", "")) for item in items))))
        return TRUE, selected_sets[0], None
    return (UNKNOWN if unknown_present else FALSE), [], (
        "HOLD_DUPLICATE_LINEAGE" if not unknown_present and any(alternatives for _, alternatives, _ in evaluations) else
        "INCOMPLETE_OR_UNKNOWN_EVIDENCE" if unknown_present else None
    )


def match_combinations(config: Any, signal_hits: Iterable[Any], *, bucket_state: Iterable[Any] = (), patient_id: Any = None, phenotype: str | None = None) -> list[dict[str, Any]]:
    hits = list(signal_hits)
    if patient_id is not None:
        hits = [h for h in hits if value(h, "patient_id", patient_id) == patient_id]
    bucket_defs = {str(value(b, "reasoning_bucket", "")): b for b in rows(config, "buckets")}
    out: list[dict[str, Any]] = []
    for combo in rows(config, "combinations"):
        enabled = value(combo, "enabled", True)
        if enabled is False or str(enabled).upper() == "FALSE":
            continue
        cid = str(value(combo, "combination_id", ""))
        nested_rule = value(combo, "rule", None)
        reqs = _requirements(config, cid)
        conflicts: list[tuple[str, tuple[str, ...]]] = []
        temporal_rejected = False
        temporal_state: str | None = None
        if nested_rule is not None:
            status, selected, hold = _evaluate_nested_combination(cid, nested_rule, hits)
            assignment = selected if status == TRUE else None
        elif not reqs:
            status, hold, assignment = UNKNOWN, "CONFIG_GAP:missing combination logic", None
        else:
            assignment, conflicts = assign_witnesses(combo, reqs, hits, bucket_defs)
            status, hold = (TRUE, None) if assignment is not None else (FALSE, None)
            if assignment is not None:
                temporal_state = _temporal_state(combo, assignment)
                temporal_policy = str(value(combo, "temporal_policy", "") or "").upper()
                temporal_requirement = str(value(combo, "temporal_requirement", "") or "").upper()
                if temporal_policy == "ORTHOPEDIC_BEFORE_CARDIAC_WHEN_AVAILABLE":
                    # Chronology is enforced whenever both sides have reliable
                    # dates.  Missing dates do not erase an otherwise valid
                    # multi-domain suspicion route because the workbook marks
                    # this policy explicitly as "when available".
                    if temporal_state == FALSE:
                        status, assignment, hold = FALSE, None, "TEMPORAL_ORDER_NOT_SATISFIED"
                        temporal_rejected = True
                elif temporal_requirement == "SATISFIED_TRUE":
                    if temporal_state == FALSE:
                        status, assignment, hold = FALSE, None, "TEMPORAL_ORDER_NOT_SATISFIED"
                        temporal_rejected = True
                    elif temporal_state == UNKNOWN:
                        status, assignment, hold = UNKNOWN, None, "INCOMPLETE_OR_UNKNOWN_EVIDENCE"
                        temporal_rejected = True
                elif temporal_requirement == "SATISFIED_NULL":
                    if temporal_state != UNKNOWN:
                        status, assignment, hold = FALSE, None, "TEMPORAL_CHRONOLOGY_RESOLVED"
                        temporal_rejected = True
        if nested_rule is None and reqs and assignment is None and not temporal_rejected:
            # A relaxed run is diagnostic only.  It can produce a hold, never
            # a pass, when the only route reuses lineage/dedup evidence.
            relaxed_reqs = [Requirement(**{**r.__dict__, "distinct_lineage_required": False}) for r in reqs]
            relaxed, _ = assign_witnesses(combo, relaxed_reqs, hits, bucket_defs)
            if relaxed is not None:
                status, hold = UNKNOWN, "HOLD_DUPLICATE_LINEAGE"
        if nested_rule is None and reqs and assignment is None and status == FALSE and not temporal_rejected:
            # Preserve three-valued logic at the combination boundary. If the
            # configured arms could be satisfied only by UNKNOWN signals, the
            # combination is UNKNOWN rather than an apparent negative.
            potential, _ = assign_witnesses(
                combo,
                reqs,
                hits,
                bucket_defs,
                allow_unknown=True,
            )
            if potential is not None:
                status, hold = UNKNOWN, "INCOMPLETE_OR_UNKNOWN_EVIDENCE"
        selected = assignment or []
        out.append({
            "patient_id": patient_id,
            "phenotype": phenotype or value(combo, "phenotype", None),
            "combination_id": cid,
            "status": status,
            "hold_reason": hold,
            "outcome": value(combo, "outcome", None),
            "result_route": value(combo, "result_route", None),
            "priority_policy_id": value(combo, "priority_policy_id", None),
            "selected_witnesses": tuple(selected),
            "supporting_signal_ids": tuple(sorted({str(value(x, "signal_id", "")) for x in selected if value(x, "signal_id", None) is not None})),
            "supporting_buckets": tuple(sorted({str(value(x, "reasoning_bucket", "")) for x in selected})),
            "support_lineage_ids": union_lineage(selected),
            "supporting_event_dates": tuple(sorted({str(d) for x in selected for d in (value(x, "event_dates", ()) or ())})),
            "temporal_state": temporal_state,
            "conflicts": tuple(conflicts),
            "clinical_rationale": value(combo, "clinical_rationale", None),
            "config_hash": value(config, "config_hash", None),
        })
    return out


match_named_combinations = match_combinations
run = match_combinations

"""Workbook-driven signal evaluation.

The evaluator is deliberately clinical-content agnostic.  All atom membership,
group operators, qualifiers and signal metadata are read from the compiled
bundle.  It emits one auditable row per configured signal; no score is built.
"""
from __future__ import annotations

from itertools import combinations
from typing import Any, Iterable, Mapping

from .reasoning_utils import (
    FALSE, TRUE, UNKNOWN, as_list, dedup_key, index_by, independent, lineage_set,
    norm_status, row_dict, rows, stable_id, tri_all, tri_any, tri_at_least, union_lineage,
    value,
)


def _qualifier_requirements(raw: Any) -> dict[str, str]:
    if raw is None or str(raw).strip().lower() in {"", "none", "none (default affirmed/confirmed)", "null"}:
        return {}
    if isinstance(raw, Mapping):
        return {str(k).strip(): str(v).strip() for k, v in raw.items()}
    out: dict[str, str] = {}
    text = str(raw).replace("[required:", "").replace("]", "")
    for part in text.replace("\n", ",").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _qualifies(evidence: Any, required: Any) -> str:
    req = _qualifier_requirements(required)
    if not req:
        return TRUE
    attrs = value(evidence, "attributes", {}) or {}
    statuses: list[str] = []
    for key, wanted in req.items():
        got = value(evidence, key, None)
        if got is None and isinstance(attrs, Mapping):
            got = attrs.get(key)
        if got is None:
            statuses.append(UNKNOWN)
        elif str(got).strip().lower() == str(wanted).strip().lower():
            statuses.append(TRUE)
        else:
            statuses.append(FALSE)
    return tri_all(statuses)


def _evidence_for_atom(evidence: Iterable[Any], atom_id: str, qualifier: Any = None) -> list[Any]:
    out: list[Any] = []
    for ev in evidence:
        if str(value(ev, "atom_id", value(ev, "ATOM_ID", ""))) != str(atom_id):
            continue
        status = norm_status(value(ev, "status", UNKNOWN))
        q = _qualifies(ev, qualifier)
        if status == TRUE and q == TRUE:
            out.append(ev)
        elif status == UNKNOWN or q == UNKNOWN:
            # A dataclass/object evidence row must also be converted to an
            # explicit UNKNOWN proxy. Returning the original TRUE object here
            # would silently bypass a missing required qualifier.
            unknown = row_dict(ev)
            unknown["status"] = UNKNOWN
            unknown["atom_id"] = atom_id
            out.append(unknown)
    return out


def _group_operator(group: Any) -> str:
    return str(value(group, "operator", value(group, "Operator", "ANY")) or "ANY").upper()


def _group_eval(statuses: list[str], group: Any) -> str:
    op = _group_operator(group)
    if op in {"ALL", "LINKED_ALL", "INDEPENDENT_ALL"}:
        return tri_all(statuses)
    if op in {"ANY", "OR"}:
        return tri_any(statuses)
    if op in {"AT_LEAST", "MINIMUM", "MIN_COUNT"}:
        minimum = value(group, "minimum_count", value(group, "Minimum_Count", 1)) or 1
        return tri_at_least(statuses, int(minimum))
    return UNKNOWN


def _mapping_for_signal(config: Any, signal_id: str) -> list[Any]:
    return [m for m in rows(config, "signal_atoms") if str(value(m, "signal_id", "")) == str(signal_id)]


def _mapping_is_executable(mapping: Any) -> bool:
    can_fire = value(
        mapping,
        "can_fire_from_this_mapping",
        value(mapping, "can_fire", value(mapping, "Can_Fire_From_This_Mapping", True)),
    )
    if can_fire is False or str(can_fire).strip().upper() in {"FALSE", "NO", "0"}:
        return False
    runtime = str(value(mapping, "runtime_executability", "EXECUTABLE") or "EXECUTABLE").upper()
    return runtime not in {"NON_EXECUTABLE", "NON_FIRING", "BLOCKED"}


def _atom_mapping_allowed(config: Any, signal_id: str, atom_id: str) -> bool:
    mappings = [
        mapping
        for mapping in _mapping_for_signal(config, signal_id)
        if str(value(mapping, "atom_id", "")) == str(atom_id)
    ]
    # Legacy nested packages did not emit signal_atoms.json. Preserve their
    # behavior while treating an emitted mapping catalog as authoritative.
    return not mappings or any(_mapping_is_executable(mapping) for mapping in mappings)


def _config_hash(config: Any) -> Any:
    if isinstance(config, Mapping):
        return config.get("config_hash")
    return getattr(config, "config_hash", None)


def _rule_rows(config: Any, signal_id: str) -> tuple[list[Any], list[Any], list[Any]]:
    groups = [g for g in rows(config, "signal_rule_groups") if str(value(g, "signal_id", "")) == str(signal_id)]
    members = [m for m in rows(config, "signal_rule_members") if str(value(m, "signal_id", "")) == str(signal_id)]
    rules = [r for r in rows(config, "signal_rules") if str(value(r, "signal_id", "")) == str(signal_id)]
    return groups, members, rules


def _episode_ids(event: Any) -> frozenset[str]:
    """Return explicit episode/encounter identifiers only.

    A linked rule cannot be inferred from dates or coincident patient scope.
    """
    ids: set[str] = set()
    for key in ("episode_id", "clinical_episode_id", "encounter_id", "visit_id"):
        got = value(event, key, None)
        if got not in (None, ""):
            ids.add(str(got))
    for container_key in ("attributes", "source_provenance", "provenance"):
        container = value(event, container_key, {}) or {}
        if isinstance(container, Mapping):
            for key in ("episode_id", "clinical_episode_id", "encounter_id", "visit_id"):
                got = container.get(key)
                if got not in (None, ""):
                    ids.add(str(got))
    return frozenset(ids)


def _dedupe_witness_sets(sets: list[list[Any]]) -> list[list[Any]]:
    seen: set[tuple[tuple[str, ...], ...]] = set()
    out: list[list[Any]] = []
    for witnesses in sets:
        key = tuple(sorted(tuple(sorted(str(x) for x in lineage_set(w))) for w in witnesses))
        if key not in seen:
            seen.add(key)
            out.append(witnesses)
    return out


def _combine_group(group: Any, children: list[tuple[str, list[list[Any]], list[Any]]]) -> tuple[str, list[list[Any]], list[Any]]:
    """Combine child alternatives without collapsing witness choices."""
    op = _group_operator(group)
    unknowns = [x for _, _, us in children for x in us]
    true_children = [(name, choices) for name, choices, _ in children if choices]
    child_unknown = any(us for _, _, us in children)
    require_independent = op == "INDEPENDENT_ALL" or str(value(group, "require_independent_lineage", False)).upper() in {"TRUE", "1", "YES"}
    linked = op == "LINKED_ALL" or str(value(group, "linkage_type", "")).upper() == "CLINICAL_EPISODE"

    def valid_combo(choice: list[Any]) -> bool:
        if require_independent:
            for left, right in combinations(choice, 2):
                if not independent(left, right):
                    return False
        if linked:
            shared: frozenset[str] | None = None
            for event in choice:
                episodes = _episode_ids(event)
                if not episodes:
                    return False
                shared = episodes if shared is None else shared.intersection(episodes)
                if not shared:
                    return False
        return True

    def product(index: int, selected: list[Any]) -> list[list[Any]]:
        if index >= len(true_children):
            return [selected] if valid_combo(selected) else []
        out: list[list[Any]] = []
        _, choices = true_children[index]
        for witness_set in choices:
            out.extend(product(index + 1, selected + witness_set))
        return out

    if op in {"ANY", "OR"}:
        choices = [choice for _, alternatives in true_children for choice in alternatives]
        if choices:
            return TRUE, _dedupe_witness_sets(choices), unknowns
        return (UNKNOWN if child_unknown else FALSE), [], unknowns

    if op in {"ALL", "LINKED_ALL", "INDEPENDENT_ALL"}:
        # A valid assignment needs one witness set from every child branch,
        # including child groups injected by Parent_Group_ID.
        if len(true_children) != len(children):
            return (UNKNOWN if child_unknown else FALSE), [], unknowns
        # Product over all child alternatives.  Each alternative is retained
        # until independence/linkage filtering has completed.
        all_choices: list[list[Any]] = [[]]
        for _, alternatives in true_children:
            all_choices = [prefix + suffix for prefix in all_choices for suffix in alternatives]
        valid = [choice for choice in all_choices if valid_combo(choice)]
        if valid:
            return TRUE, _dedupe_witness_sets(valid), unknowns
        # Missing explicit linkage is uncertainty, not a negative finding.
        return UNKNOWN, [], unknowns

    if op in {"AT_LEAST", "MINIMUM", "MIN_COUNT"}:
        minimum = int(value(group, "minimum_count", 1) or 1)
        if len(true_children) < minimum:
            return (UNKNOWN if child_unknown else FALSE), [], unknowns
        valid_sets: list[list[Any]] = []
        for branch_count in range(minimum, len(true_children) + 1):
            for branch_indices in combinations(range(len(true_children)), branch_count):
                selected_branches = [true_children[i][1] for i in branch_indices]
                choices: list[list[Any]] = [[]]
                for alternatives in selected_branches:
                    choices = [prefix + suffix for prefix in choices for suffix in alternatives]
                valid_sets.extend(choice for choice in choices if valid_combo(choice))
            if valid_sets:
                break
        if valid_sets:
            return TRUE, _dedupe_witness_sets(valid_sets), unknowns
        return UNKNOWN, [], unknowns
    return UNKNOWN, [], unknowns


def _evaluate_signal_rule(config: Any, signal: Any, evidence: list[Any], _stack: frozenset[str] = frozenset()) -> tuple[str, list[Any], list[Any], str, list[list[Any]]]:
    sid = str(value(signal, "signal_id", ""))
    groups, members, rules = _rule_rows(config, sid)
    mappings = _mapping_for_signal(config, sid)
    if not groups or not members:
        # A simple mapping is still fully workbook-defined.  A mapping marked
        # unable to fire contributes UNKNOWN rather than being upgraded.
        candidates: list[Any] = []
        blocked = False
        for mapping in mappings:
            if not _mapping_is_executable(mapping):
                blocked = True
                continue
            aid = value(mapping, "atom_id", "")
            candidates.extend(_evidence_for_atom(evidence, str(aid), value(mapping, "required_qualifiers", None)))
        status = tri_any(norm_status(value(c, "status", UNKNOWN)) for c in candidates)
        if not candidates and blocked:
            status = UNKNOWN
        selected = [c for c in candidates if norm_status(value(c, "status", UNKNOWN)) == TRUE]
        return status, selected, [c for c in candidates if norm_status(value(c, "status", UNKNOWN)) == UNKNOWN], "simple workbook mapping", [[c] for c in selected]

    if sid in _stack:
        return UNKNOWN, [], [], "CONFIG_GAP:cyclic signal reference", []
    group_by_id = {str(value(g, "group_id", "")): g for g in groups}
    mem_by_group: dict[str, list[Any]] = {}
    for m in members:
        mem_by_group.setdefault(str(value(m, "group_id", "")), []).append(m)
    child_groups: dict[str, list[Any]] = {}
    for child in groups:
        parent = value(child, "parent_group_id", None)
        if parent not in (None, ""):
            child_groups.setdefault(str(parent), []).append(child)
    root_id = value(rules[0], "root_group_id", None) if rules else None
    root = group_by_id.get(str(root_id)) if root_id not in (None, "") else None
    root = root or next((g for g in groups if value(g, "parent_group_id", None) in (None, "")), groups[0])
    signal_by_id = {str(value(row, "signal_id", "")): row for row in rows(config, "signals")}

    def eval_group(group_id: str) -> tuple[str, list[list[Any]], list[Any]]:
        group = group_by_id.get(group_id)
        if group is None:
            return UNKNOWN, [], []
        children: list[tuple[int, str, Any]] = []
        for member in mem_by_group.get(group_id, []):
            children.append((int(value(member, "evaluation_order", 0) or 0), "member", member))
        for child in child_groups.get(group_id, []):
            children.append((int(value(child, "evaluation_order", 0) or 0), "group", child))
        evaluated: list[tuple[str, list[list[Any]], list[Any]]] = []
        for _, child_kind, member in sorted(children, key=lambda x: x[0]):
            if child_kind == "group":
                ident = str(value(member, "group_id", ""))
                st, sets, us = eval_group(ident)
                evaluated.append((ident, sets, us))
                continue
            typ = str(value(member, "member_type", "ATOM")).upper()
            ident = value(member, "member_id", "")
            if typ in {"ATOM", "OBSERVE"}:
                # In a structured rule, Signal_Rule_Members is authoritative.
                # Can_Fire_From_This_Mapping controls simple direct mappings;
                # it must not suppress an atom explicitly used inside an AST.
                evs = _evidence_for_atom(evidence, str(ident), value(member, "required_attributes", None))
                ts = [e for e in evs if norm_status(value(e, "status", UNKNOWN)) == TRUE]
                us = [e for e in evs if norm_status(value(e, "status", UNKNOWN)) == UNKNOWN]
                sets = [[e] for e in ts]
            else:
                # A SIGNAL member recursively evaluates the referenced
                # workbook signal; it is not treated as a raw atom.
                evs = [e for e in evidence if str(value(e, "signal_id", "")) == str(ident)]
                if evs:
                    ts = [e for e in evs if norm_status(value(e, "status", UNKNOWN)) == TRUE]
                    us = [e for e in evs if norm_status(value(e, "status", UNKNOWN)) == UNKNOWN]
                    sets = [[e] for e in ts]
                elif str(ident) in signal_by_id:
                    child = signal_by_id[str(ident)]
                    st, support, us, _, child_sets = _evaluate_signal_rule(config, child, evidence, _stack | {sid})
                    child_exec = str(value(child, "runtime_executability", "EXECUTABLE") or "EXECUTABLE").upper()
                    child_action = str(value(child, "config_action", "POSITIVE_SIGNAL") or "POSITIVE_SIGNAL").upper()
                    child_enabled = value(child, "enabled", True)
                    if (
                        child_exec in {"NON_EXECUTABLE", "NON_FIRING", "BLOCKED"}
                        or child_action != "POSITIVE_SIGNAL"
                        or child_enabled is False
                        or str(child_enabled).upper() == "FALSE"
                    ):
                        st, support, us = UNKNOWN, [], us or [{}]
                    ts = support
                    sets = child_sets or [[e] for e in support]
                    if st == UNKNOWN and not us:
                        us = [{}]
                else:
                    ts, us, sets = [], [{}], []
            evaluated.append((str(ident), sets, us))
        return _combine_group(group, evaluated)

    status, witness_sets, unknown = eval_group(str(value(root, "group_id", "")))
    support = witness_sets[0] if witness_sets else []
    return status, support, unknown, "workbook signal rule", witness_sets


def evaluate_signals(config: Any, evidence: Iterable[Any], *, patient_id: Any = None, phenotype: str | None = None) -> list[dict[str, Any]]:
    """Evaluate all enabled configured signals for one patient.

    ``evidence`` is expected to be qualified evidence events.  The function is
    pure and returns ordinary dictionaries so it can be used by Snowpark or by
    the reference engine.
    """
    ev = list(evidence)
    if patient_id is not None:
        ev = [e for e in ev if value(e, "patient_id", patient_id) == patient_id]
    out: list[dict[str, Any]] = []
    for signal in rows(config, "signals"):
        enabled = value(signal, "enabled", True)
        if enabled is False or str(enabled).upper() == "FALSE":
            continue
        sid = str(value(signal, "signal_id", ""))
        status, support, unknown, reason, witness_sets = _evaluate_signal_rule(config, signal, ev)
        run_exec = str(value(signal, "runtime_executability", "EXECUTABLE") or "EXECUTABLE").upper()
        if run_exec in {"NON_EXECUTABLE", "NON_FIRING", "BLOCKED"}:
            status = UNKNOWN
            reason = f"CONFIG_GAP:{run_exec}"
            support = []
            witness_sets = []
        if status == TRUE:
            # A configured blocker is evaluated only when represented as a
            # qualified blocker evidence event.  No clinical fallback occurs.
            blockers = [b for b in rows(config, "signal_blockers") if str(value(b, "signal_id", "")) == sid]
            for blocker in blockers:
                bid = value(blocker, "atom_id", "")
                b_evs = _evidence_for_atom(ev, str(bid), value(blocker, "required_attributes", None))
                if any(norm_status(value(b, "status", UNKNOWN)) == TRUE for b in b_evs):
                    status, support, unknown = FALSE, [], b_evs
                    witness_sets = []
                    reason = f"blocked_by:{bid}"
                    break
        row = {
            "patient_id": patient_id if patient_id is not None else (value(support[0], "patient_id", None) if support else None),
            "phenotype": phenotype or value(signal, "phenotype", None),
            "signal_id": sid,
            "status": status,
            "reasoning_bucket": value(signal, "reasoning_bucket", None),
            "tier": value(signal, "tier", None),
            "gate_role": value(signal, "gate_role", None),
            "canonical_dedup_group": value(signal, "canonical_dedup_group", None),
            "support_lineage_ids": union_lineage(support),
            "context_lineage_ids": union_lineage(unknown, "context_lineage_ids"),
            "event_dates": tuple(sorted({str(value(x, "event_date", "")) for x in support if value(x, "event_date", None) is not None})),
            "supporting_evidence_ids": tuple(str(value(x, "evidence_id", stable_id(sid, i))) for i, x in enumerate(support)),
            "supporting_witnesses": tuple(tuple(wset) for wset in witness_sets),
            "supporting_witness_sets": tuple(tuple(str(value(x, "evidence_id", stable_id(sid, i))) for i, x in enumerate(wset)) for wset in witness_sets),
            "explanation": reason,
            "config_hash": _config_hash(config),
        }
        out.append(row)
    return out


# Compatibility aliases used by some orchestration styles.
evaluate_signal_hits = evaluate_signals
run = evaluate_signals

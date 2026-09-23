"""Workbook-driven signal evaluation.

The evaluator is deliberately clinical-content agnostic.  All atom membership,
group operators, qualifiers and signal metadata are read from the compiled
bundle.  It emits one auditable row per configured signal; no score is built.
"""
from __future__ import annotations

from datetime import date, datetime
from itertools import combinations
from typing import Any, Iterable, Mapping

from ..evaluation_policy import (
    ICD_DATED_CLAIMS,
    collect_relaxations,
    is_claims_recall,
    is_icd_dated_claims,
    is_native_claim_code,
    normalize_evaluation_mode,
    provisional_copy,
)
from .reasoning_utils import (
    FALSE, TRUE, UNKNOWN, as_list, dedup_key, index_by, independent, lineage_set,
    grouped_rows, norm_status, row_dict, rows, stable_id, tri_all, tri_any, tri_at_least, union_lineage,
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


def _qualifier_assessment(evidence: Any, required: Any) -> tuple[str, tuple[str, ...]]:
    req = _qualifier_requirements(required)
    if not req:
        return TRUE, ()
    attrs = value(evidence, "attributes", {}) or {}
    statuses: list[str] = []
    missing: list[str] = []
    for key, wanted in req.items():
        got = value(evidence, key, None)
        if got is None and isinstance(attrs, Mapping):
            got = attrs.get(key)
        if got is None:
            statuses.append(UNKNOWN)
            missing.append(key)
        elif str(got).strip().lower() == str(wanted).strip().lower():
            statuses.append(TRUE)
        else:
            statuses.append(FALSE)
    return tri_all(statuses), tuple(missing)


def _qualifies(evidence: Any, required: Any) -> str:
    return _qualifier_assessment(evidence, required)[0]


def _context_unknown_keys(evidence: Any) -> tuple[str, ...] | None:
    """Qualifiers a claim code left blank, when that is the only failure.

    Supporting and result-required mappings stay non-firing. An observed
    false qualifier is not represented by these reasons.
    """
    if _evidence_mapping_role(evidence) in {"SUPPORTING", "RESULT_REQUIRED"}:
        return None
    reason = str(value(evidence, "reason", "") or "")
    if reason == "CONFIG_RESTRICTION_TERM_CANNOT_FIRE_ALONE":
        return ("additional_clinical_context",)
    prefix = "MISSING_REQUIRED_QUALIFIER:"
    if reason.startswith(prefix):
        key = reason[len(prefix):].strip()
        return (key,) if key else ("note_context",)
    return None


# Note-context judgments. A claim date or an ICD title does not establish these.
_NOT_INFERABLE = {
    "additional_clinical_context",
    "note_context",
    "unexplained",
    "otherwise_unexplained",
    "no_convincing_sarcomeric_explanation",
    "no_matching_infarction_explanation",
    "amyloid_compatible",
    "clearly_established",
}

# How long the same atom must span, on encounter dates, before the qualifier counts.
# Progressive needs the finding to run across years of the chart, not a single visit.
_DURATION_DAYS = {
    "chronic": 90,
    "persistent": 90,
    "prior_longstanding": 365,
    "progressive": 365,
}
_REPEAT_KEYS = {"recurrent", "progressive_or_recurrent"}
_NAME_PHRASES = {
    "chronic": ("chronic",),
    "persistent": ("persistent",),
    "recurrent": ("recurrent",),
    "progressive": ("progressive",),
    "progressive_or_recurrent": ("progressive", "recurrent"),
    "length_dependent": ("length dependent",),
    "axonal": ("axonal",),
    "sensorimotor": ("sensorimotor", "sensory motor"),
    "multiple_or_bilateral": ("bilateral", "multiple"),
    "bilateral": ("bilateral",),
}
_DEGREE_PHRASES = (
    "first degree", "second degree", "mother", "father", "parent",
    "sibling", "brother", "sister", "son", "daughter",
)


def _compact_icd(code: str) -> str:
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def _z_prefix(code: str, start: int, end: int) -> bool:
    compact = _compact_icd(code)
    if len(compact) < 3 or not compact.startswith("Z"):
        return False
    try:
        prefix = int(compact[1:3])
    except ValueError:
        return False
    return start <= prefix <= end


def _claim_code_and_name(evidence: Any) -> tuple[str, str]:
    attrs = value(evidence, "attributes", {}) or {}
    restriction = value(evidence, "config_restriction", {}) or {}
    provenance = value(evidence, "source_provenance", {}) or {}
    if not isinstance(attrs, Mapping):
        attrs = {}
    if not isinstance(restriction, Mapping):
        restriction = {}
    if not isinstance(provenance, Mapping):
        provenance = {}
    code = str(
        provenance.get("matched_config_value")
        or attrs.get("matched_config_value")
        or restriction.get("matched_config_value")
        or value(evidence, "matched_config_value", "")
        or ""
    )
    name = str(attrs.get("display_name") or restriction.get("display_name") or "")
    return code, name


def _as_event_date(raw: Any) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _atom_event_dates(evidence: Any, rows: Iterable[Any]) -> list[date]:
    atom_id = str(value(evidence, "atom_id", ""))
    found: set[date] = set()
    for item in rows:
        if str(value(item, "atom_id", "")) != atom_id:
            continue
        parsed = _as_event_date(value(item, "event_date", None))
        if parsed is not None:
            found.add(parsed)
    return sorted(found)


def _age_years(evidence: Any, birth_date: Any) -> int | None:
    born = _as_event_date(birth_date)
    seen = _as_event_date(value(evidence, "event_date", None))
    if born is None or seen is None or seen < born:
        return None
    years = seen.year - born.year
    if (seen.month, seen.day) < (born.month, born.day):
        years -= 1
    return years


def _inference_source(evidence: Any, key: str, rows: Iterable[Any], birth_date: Any) -> str | None:
    """Say how a claim code or its encounter dates establish one qualifier.

    Returns None when the code and the dates do not speak to that qualifier.
    An absent inference is not a contradiction.
    """
    if key in _NOT_INFERABLE or key.startswith("adequately_explains") or key.startswith("clearly_established"):
        return None
    code, name = _claim_code_and_name(evidence)
    blob = name.lower().replace("-", " ").replace("_", " ")
    label = name or code or "the ICD-10 code"
    phrases = _NAME_PHRASES.get(key)
    if phrases and any(phrase in blob for phrase in phrases):
        return f"the ICD-10 description '{label}'"
    if key == "multiple_digits" and "multiple" in blob and any(word in blob for word in ("digit", "finger", "thumb")):
        return f"the ICD-10 description '{label}'"
    if key == "first_or_second_degree" and any(phrase in blob for phrase in _DEGREE_PHRASES):
        return f"the ICD-10 description '{label}'"
    if key in {"family_history", "family_member"} and (_z_prefix(code, 80, 84) or "family history" in blob):
        return f"ICD-10 family-history code {code or label}"
    if key in {"personal_history", "prior_history"} and (_z_prefix(code, 85, 87) or "personal history" in blob):
        return f"ICD-10 personal-history code {code or label}"
    if key == "adult_onset":
        # A family-history claim is dated when it was recorded, not when the
        # relative's disease began.
        if _z_prefix(code, 80, 84) or "family history" in blob:
            return None
        if birth_date in (None, ""):
            attrs = value(evidence, "attributes", {}) or {}
            birth_date = attrs.get("birth_date") if isinstance(attrs, Mapping) else None
        years = _age_years(evidence, birth_date)
        if years is not None and years >= 18:
            return f"age {years} on the encounter date, using the census birth date"
        return None
    dates = _atom_event_dates(evidence, rows)
    if key in _REPEAT_KEYS and len(dates) >= 2:
        return f"encounter dates {dates[0].isoformat()} and {dates[-1].isoformat()}"
    minimum = _DURATION_DAYS.get(key)
    if minimum is not None and len(dates) >= 2 and (dates[-1] - dates[0]).days >= minimum:
        if key == "progressive":
            return (
                f"the chart history, where encounter dates {dates[0].isoformat()} "
                f"through {dates[-1].isoformat()} are more than a year apart"
            )
        return f"encounter dates {dates[0].isoformat()} through {dates[-1].isoformat()}"
    return None


def _apply_claim_inferences(
    evidence: Any,
    required: Any,
    rows: Iterable[Any],
    birth_date: Any,
) -> Any:
    requirements = _qualifier_requirements(required)
    if not requirements:
        return evidence
    row = row_dict(evidence)
    attributes = dict(row.get("attributes") or {})
    inferred = [
        dict(item) for item in attributes.get("inferred_qualifiers") or row.get("inferred_qualifiers") or ()
        if isinstance(item, Mapping)
    ]
    seen = {str(item.get("qualifier")) for item in inferred}
    for key, wanted in requirements.items():
        if str(wanted).strip().lower() not in {"true", "1", "yes", "y"}:
            continue
        current = row.get(key)
        if current is None:
            current = attributes.get(key)
        if current is not None or key in seen:
            continue
        source = _inference_source(row, key, rows, birth_date)
        if not source:
            continue
        attributes[key] = True
        row[key] = True
        inferred.append({"qualifier": key, "source": source})
        seen.add(key)
    if not inferred:
        return evidence
    attributes["inferred_qualifiers"] = inferred
    row["attributes"] = attributes
    row["inferred_qualifiers"] = inferred
    return row


def _claim_support_lineage(evidence: Any) -> list[str]:
    existing = value(evidence, "support_lineage_ids", None) or []
    if existing:
        return [str(item) for item in existing if item]
    provenance = value(evidence, "source_provenance", {}) or {}
    lineage = provenance.get("support_lineage_id") if isinstance(provenance, Mapping) else None
    return [str(lineage)] if lineage else []


def _promote_missing_claim_context(
    evidence: Any,
    keys: tuple[str, ...],
    required: Any,
) -> dict[str, Any]:
    promoted = _with_context_gaps(evidence, keys, _qualifier_requirements(required))
    lineage = _claim_support_lineage(evidence)
    if lineage and not promoted.get("support_lineage_ids"):
        promoted["support_lineage_ids"] = lineage
    return promoted


def _qualifier_held(evidence: Any, key: str) -> bool:
    attrs = value(evidence, "attributes", {}) or {}
    got = value(evidence, key, None)
    if got is None and isinstance(attrs, Mapping):
        got = attrs.get(key)
    return str(got).strip().lower() in {"true", "1", "yes", "y"}


def _evidence_for_atom(
    evidence: Iterable[Any],
    atom_id: str,
    qualifier: Any = None,
    *,
    evaluation_mode: str = "STRICT",
    birth_date: Any = None,
) -> list[Any]:
    rows = list(evidence)
    out: list[Any] = []
    for ev in rows:
        if str(value(ev, "atom_id", value(ev, "ATOM_ID", ""))) != str(atom_id):
            continue
        if is_icd_dated_claims(evaluation_mode) and is_native_claim_code(ev):
            ev = _apply_claim_inferences(ev, qualifier, rows, birth_date)
        status = norm_status(value(ev, "status", UNKNOWN))
        q, missing = _qualifier_assessment(ev, qualifier)
        context_keys = _context_unknown_keys(ev) if status == UNKNOWN else None
        if status == TRUE and q == TRUE:
            out.append(ev)
        elif (
            status == TRUE
            and q == UNKNOWN
            and missing
            and is_claims_recall(evaluation_mode)
            and is_native_claim_code(ev)
        ):
            out.append(provisional_copy(
                ev,
                *(f"MISSING_REQUIRED_QUALIFIER:{key}" for key in missing),
                status=TRUE,
            ))
        elif (
            status == TRUE
            and q == UNKNOWN
            and missing
            and is_icd_dated_claims(evaluation_mode)
            and is_native_claim_code(ev)
        ):
            # The claim code is the support the signal asked for. Qualifiers
            # such as progressive or length-dependent are note context, so a
            # missing value lowers the tier later and does not block the signal.
            # An observed false qualifier does not take this path.
            out.append(_promote_missing_claim_context(ev, missing, qualifier))
        elif (
            context_keys is not None
            and q != FALSE
            and is_icd_dated_claims(evaluation_mode)
            and is_native_claim_code(ev)
        ):
            # Qualification left the code UNKNOWN because the note context is
            # absent. The code itself is still the signal's support.
            keys = tuple(
                key for key in dict.fromkeys((*context_keys, *missing))
                if not _qualifier_held(ev, key)
            )
            if not keys:
                restored = row_dict(ev)
                restored["status"] = TRUE
                lineage = _claim_support_lineage(ev)
                if lineage and not restored.get("support_lineage_ids"):
                    restored["support_lineage_ids"] = lineage
                out.append(restored)
            else:
                out.append(_promote_missing_claim_context(ev, keys, qualifier))
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
    return grouped_rows(config, "signal_atoms", "signal_id").get(str(signal_id), [])


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


def _evidence_mapping_role(item: Any) -> str:
    attrs = value(item, "attributes", {}) or {}
    restriction = value(item, "config_restriction", {}) or {}
    raw = ""
    if isinstance(attrs, Mapping):
        raw = attrs.get("mapping_role") or attrs.get("Mapping_Role") or ""
    if not raw and isinstance(restriction, Mapping):
        raw = restriction.get("mapping_role") or restriction.get("Mapping_Role") or ""
    return str(raw or "").strip().upper().replace("-", "_").replace(" ", "_")


def _drop_tier(tier: Any) -> Any:
    """Move a signal one step weaker without leaving the scored tier bands.

    Tier 1 becomes 2. Tier 2 becomes 3, which the context-tier policies still
    score. Tier 3 and above stay put: they are already context evidence, and
    a further step would fall outside every combination.
    """
    if isinstance(tier, bool) or tier in (None, ""):
        return tier
    try:
        number = int(tier)
    except (TypeError, ValueError):
        return tier
    if number >= 3:
        return number
    return number + 1


def _context_gaps_on(item: Any) -> list[dict[str, str]]:
    raw = value(item, "context_gaps", None)
    if not raw:
        attrs = value(item, "attributes", {}) or {}
        raw = attrs.get("context_gaps") if isinstance(attrs, Mapping) else None
    gaps: list[dict[str, str]] = []
    for gap in raw or ():
        if not isinstance(gap, Mapping):
            continue
        qualifier = str(gap.get("qualifier") or "").strip()
        if not qualifier:
            continue
        gaps.append({
            "qualifier": qualifier,
            "expected": str(gap.get("expected") or "True"),
            "observed": str(gap.get("observed") or "NOT_PRESENT"),
        })
    return gaps


def _with_context_gaps(evidence: Any, missing: tuple[str, ...] | list[str], required: Mapping[str, str]) -> dict[str, Any]:
    """Keep claim-code support while recording qualifiers the code cannot show.

    This is not a provisional recall hit. The signal still passes, and the
    tier drop is applied once for the whole signal.
    """
    row = row_dict(evidence)
    attributes = dict(row.get("attributes") or {})
    gaps = [
        dict(gap) for gap in attributes.get("context_gaps") or row.get("context_gaps") or ()
        if isinstance(gap, Mapping)
    ]
    seen = {str(gap.get("qualifier")) for gap in gaps}
    for key in missing:
        if key in seen:
            continue
        gaps.append({
            "qualifier": key,
            "expected": str(required.get(key) or "True"),
            "observed": "NOT_PRESENT",
        })
    attributes["context_gaps"] = gaps
    attributes["evaluation_mode"] = ICD_DATED_CLAIMS
    row["attributes"] = attributes
    row["context_gaps"] = gaps
    row["status"] = TRUE
    row["provisional"] = False
    row["relaxations"] = []
    row["evaluation_mode"] = ICD_DATED_CLAIMS
    return row


def _collected_inferences(witnesses: list[Any]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in witnesses:
        raw = value(item, "inferred_qualifiers", None)
        if not raw:
            attrs = value(item, "attributes", {}) or {}
            raw = attrs.get("inferred_qualifiers") if isinstance(attrs, Mapping) else None
        for inference in raw or ():
            if not isinstance(inference, Mapping):
                continue
            qualifier = str(inference.get("qualifier") or "").strip()
            source = str(inference.get("source") or "").strip()
            if not qualifier or (qualifier, source) in seen:
                continue
            seen.add((qualifier, source))
            found.append({"qualifier": qualifier, "source": source})
    return found


def _collected_context_gaps(witnesses: list[Any]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in witnesses:
        for gap in _context_gaps_on(item):
            key = (gap["qualifier"], gap["expected"])
            if key in seen:
                continue
            seen.add(key)
            gaps.append(gap)
    return gaps


def _tier_from_support(
    configured_tier: Any,
    witness_sets: list[list[Any]],
    support: list[Any],
) -> tuple[Any, str, list[dict[str, str]]]:
    """Drop one tier when support is proxy-only or missing note context.

    A direct code with every requested qualifier keeps the configured tier.
    Proxy support and missing qualifiers each weaken the signal, but they
    share one tier step so the signal stays inside the combination bands.
    """
    witnesses = [item for witness_set in witness_sets for item in witness_set] or list(support)
    roles = [_evidence_mapping_role(item) for item in witnesses]
    gaps = _collected_context_gaps(witnesses)
    proxy_only = bool(roles) and all(role == "PROXY_SUPPORT" for role in roles)
    if proxy_only and gaps:
        return _drop_tier(configured_tier), "PROXY_SUPPORT_AND_MISSING_CONTEXT_TIER_DROP", gaps
    if proxy_only:
        return _drop_tier(configured_tier), "PROXY_SUPPORT_TIER_DROP", gaps
    if gaps:
        return _drop_tier(configured_tier), "MISSING_CONTEXT_TIER_DROP", gaps
    if any(role == "DIRECT_TARGET" for role in roles):
        return configured_tier, "DIRECT_TARGET", gaps
    return configured_tier, "CONFIGURED_TIER", gaps


def _config_hash(config: Any) -> Any:
    if isinstance(config, Mapping):
        return config.get("config_hash")
    return getattr(config, "config_hash", None)


def _rule_rows(config: Any, signal_id: str) -> tuple[list[Any], list[Any], list[Any]]:
    key = str(signal_id)
    return (
        grouped_rows(config, "signal_rule_groups", "signal_id").get(key, []),
        grouped_rows(config, "signal_rule_members", "signal_id").get(key, []),
        grouped_rows(config, "signal_rules", "signal_id").get(key, []),
    )


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


def _witness_dates(witness: Any) -> list[datetime]:
    raw_dates = value(witness, "event_dates", None)
    if raw_dates in (None, ""):
        raw_dates = [value(witness, "event_date", None)]
    elif not isinstance(raw_dates, (list, tuple, set, frozenset)):
        raw_dates = [raw_dates]
    parsed: list[datetime] = []
    for raw in raw_dates:
        if raw in (None, ""):
            continue
        try:
            if isinstance(raw, datetime):
                item = raw
            elif isinstance(raw, date):
                item = datetime.combine(raw, datetime.min.time())
            else:
                item = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if item.tzinfo is not None:
                item = item.astimezone().replace(tzinfo=None)
            parsed.append(item)
        except (TypeError, ValueError):
            continue
    return sorted(parsed)


def _ordered_group_temporal_state(
    config: Any,
    policy: str,
    witnesses: list[Any],
    root_group_id: str,
    mem_by_group: Mapping[str, list[Any]],
    child_groups: Mapping[str, list[Any]],
) -> str:
    """Apply an explicit workbook temporal policy to one witness set."""
    ordered_children = sorted(
        child_groups.get(root_group_id, []),
        key=lambda group: int(value(group, "evaluation_order", 0) or 0),
    )
    if len(ordered_children) < 2:
        return UNKNOWN

    def expanded_signal_members(signal_id: str) -> set[tuple[str, str]]:
        # Use only the signal's direct atom mapping.  Recursively expanding a
        # cross-bucket composite would leak its supporting cardiac atoms into
        # an orthopedic temporal arm (and vice versa).
        found: set[tuple[str, str]] = {("SIGNAL", signal_id)}
        for mapping in grouped_rows(config, "signal_atoms", "signal_id").get(str(signal_id), []):
            found.add(("ATOM", str(value(mapping, "atom_id", ""))))
        return found

    def member_ids(group_id: str) -> set[tuple[str, str]]:
        found: set[tuple[str, str]] = set()
        for member in mem_by_group.get(group_id, []):
            member_type = str(value(member, "member_type", "ATOM") or "ATOM").upper()
            member_id = str(value(member, "member_id", ""))
            if member_type == "SIGNAL":
                found.update(expanded_signal_members(member_id))
            else:
                found.add(("ATOM", member_id))
        for child in child_groups.get(group_id, []):
            found.update(member_ids(str(value(child, "group_id", ""))))
        return found

    group_dates: list[list[datetime]] = []
    for child in ordered_children:
        allowed = member_ids(str(value(child, "group_id", "")))
        dates: list[datetime] = []
        for witness in witnesses:
            identifiers = {
                ("ATOM", str(value(witness, "atom_id", ""))),
                ("SIGNAL", str(value(witness, "signal_id", ""))),
            }
            if allowed.intersection(identifiers):
                dates.extend(_witness_dates(witness))
        if not dates:
            return UNKNOWN
        group_dates.append(sorted(dates))

    representatives = [dates[0] for dates in group_dates]
    strict = policy == "ORTHOPEDIC_BEFORE_CARDIAC_WHEN_AVAILABLE"
    ordered = all(
        left < right if strict else left <= right
        for left, right in zip(representatives, representatives[1:])
    )
    return TRUE if ordered else FALSE


def _combine_group(
    group: Any,
    children: list[tuple[str, list[list[Any]], list[Any]]],
    *,
    evaluation_mode: str = "STRICT",
) -> tuple[str, list[list[Any]], list[Any]]:
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
        if linked and is_claims_recall(evaluation_mode):
            # Claim encounters can show that the configured codes occurred,
            # but cannot always establish the rule's intended clinical-episode
            # relationship. Preserve the code-supported route provisionally.
            recall_choices = [
                [
                    provisional_copy(
                        witness,
                        "MISSING_REQUIRED_CLINICAL_EPISODE_LINKAGE",
                        status=TRUE,
                    )
                    for witness in choice
                ]
                for choice in all_choices
                if choice and all(is_native_claim_code(witness) for witness in choice)
            ]
            if recall_choices:
                return TRUE, _dedupe_witness_sets(recall_choices), unknowns
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


def _rows_for_atom(
    evidence: list[Any],
    atom_id: str,
    evidence_by_atom: Mapping[str, list[Any]] | None,
) -> list[Any]:
    if evidence_by_atom is None:
        return evidence
    return evidence_by_atom.get(str(atom_id), [])


def _evaluate_signal_rule(
    config: Any,
    signal: Any,
    evidence: list[Any],
    _stack: frozenset[str] = frozenset(),
    *,
    evaluation_mode: str = "STRICT",
    birth_date: Any = None,
    evidence_by_atom: Mapping[str, list[Any]] | None = None,
) -> tuple[str, list[Any], list[Any], str, list[list[Any]]]:
    evaluation_mode = normalize_evaluation_mode(evaluation_mode)
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
                runtime = str(value(mapping, "runtime_executability", "EXECUTABLE") or "EXECUTABLE").upper()
                allow_code = runtime not in {"NON_FIRING", "BLOCKED"} and (
                    is_claims_recall(evaluation_mode) or is_icd_dated_claims(evaluation_mode)
                )
                if not allow_code:
                    continue
            aid = value(mapping, "atom_id", "")
            mapped = _evidence_for_atom(
                _rows_for_atom(evidence, str(aid), evidence_by_atom),
                str(aid),
                value(mapping, "required_qualifiers", None),
                evaluation_mode=evaluation_mode,
                birth_date=birth_date,
            )
            if not _mapping_is_executable(mapping) and is_claims_recall(evaluation_mode):
                mapped = [
                    provisional_copy(
                        item,
                        "NON_EXECUTABLE_OR_SUPPORT_ONLY_SIGNAL_MAPPING",
                        status=TRUE,
                    )
                    for item in mapped
                    if is_native_claim_code(item)
                ]
            candidates.extend(mapped)
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
    signal_by_id = {
        signal_id_key: signal_rows[-1]
        for signal_id_key, signal_rows in grouped_rows(config, "signals", "signal_id").items()
        if signal_rows
    }

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
                evs = _evidence_for_atom(
                    _rows_for_atom(evidence, str(ident), evidence_by_atom),
                    str(ident),
                    value(member, "required_attributes", None),
                    evaluation_mode=evaluation_mode,
                    birth_date=birth_date,
                )
                if is_claims_recall(evaluation_mode):
                    member_mappings = [
                        mapping for mapping in mappings
                        if str(value(mapping, "atom_id", "")) == str(ident)
                    ]
                    if member_mappings and not any(_mapping_is_executable(mapping) for mapping in member_mappings):
                        evs = [
                            provisional_copy(
                                item,
                                "NON_EXECUTABLE_OR_SUPPORT_ONLY_SIGNAL_MAPPING",
                                status=TRUE,
                            ) if is_native_claim_code(item) and norm_status(value(item, "status", UNKNOWN)) == TRUE else item
                            for item in evs
                        ]
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
                    st, support, us, _, child_sets = _evaluate_signal_rule(
                        config,
                        child,
                        evidence,
                        _stack | {sid},
                        evaluation_mode=evaluation_mode,
                        birth_date=birth_date,
                        evidence_by_atom=evidence_by_atom,
                    )
                    child_exec = str(value(child, "runtime_executability", "EXECUTABLE") or "EXECUTABLE").upper()
                    child_action = str(value(child, "config_action", "POSITIVE_SIGNAL") or "POSITIVE_SIGNAL").upper()
                    child_enabled = value(child, "enabled", True)
                    if (
                        (
                            child_exec in {"NON_EXECUTABLE", "NON_FIRING", "BLOCKED"}
                            and not is_claims_recall(evaluation_mode)
                        )
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
        return _combine_group(group, evaluated, evaluation_mode=evaluation_mode)

    root_group_id = str(value(root, "group_id", ""))
    status, witness_sets, unknown = eval_group(root_group_id)
    reason = "workbook signal rule"
    temporal_policy = str(value(rules[0], "temporal_policy", "") or "").upper() if rules else ""
    if status == TRUE and temporal_policy:
        temporal_states = [
            _ordered_group_temporal_state(
                config,
                temporal_policy,
                witness_set,
                root_group_id,
                mem_by_group,
                child_groups,
            )
            for witness_set in witness_sets
        ]
        optional_when_missing = temporal_policy.endswith("_WHEN_AVAILABLE")
        accepted = [
            witness_set
            for witness_set, temporal_state in zip(witness_sets, temporal_states)
            if temporal_state == TRUE or (optional_when_missing and temporal_state == UNKNOWN)
        ]
        if accepted:
            if is_claims_recall(evaluation_mode):
                accepted = [
                    [
                        provisional_copy(
                            item,
                            "MISSING_REQUIRED_TEMPORAL_ORDER",
                            status=TRUE,
                        ) if temporal_state == UNKNOWN and is_native_claim_code(item) else item
                        for item in witness_set
                    ]
                    for witness_set, temporal_state in zip(witness_sets, temporal_states)
                    if temporal_state == TRUE or (optional_when_missing and temporal_state == UNKNOWN)
                ]
            witness_sets = accepted
            if any(state == UNKNOWN for state in temporal_states) and optional_when_missing:
                reason = "workbook signal rule; chronology unavailable but optional"
        elif any(state == UNKNOWN for state in temporal_states):
            recall_sets = [
                [
                    provisional_copy(
                        item,
                        "MISSING_REQUIRED_TEMPORAL_ORDER",
                        status=TRUE,
                    )
                    for item in witness_set
                ]
                for witness_set, temporal_state in zip(witness_sets, temporal_states)
                if temporal_state == UNKNOWN
                and witness_set
                and all(is_native_claim_code(item) for item in witness_set)
            ] if is_claims_recall(evaluation_mode) else []
            if recall_sets:
                witness_sets = recall_sets
                reason = "CLAIMS_RECALL_PROVISIONAL_TEMPORAL_EVIDENCE"
            else:
                status, witness_sets, unknown = UNKNOWN, [], [item for witness_set in witness_sets for item in witness_set]
                reason = "INCOMPLETE_OR_UNKNOWN_TEMPORAL_EVIDENCE"
        else:
            status, witness_sets = FALSE, []
            reason = "TEMPORAL_ORDER_NOT_SATISFIED"
    support = witness_sets[0] if witness_sets else []
    return status, support, unknown, reason, witness_sets


def evaluate_signals(
    config: Any,
    evidence: Iterable[Any],
    *,
    patient_id: Any = None,
    phenotype: str | None = None,
    evaluation_mode: str = "STRICT",
    birth_date: Any = None,
) -> list[dict[str, Any]]:
    """Evaluate all enabled configured signals for one patient.

    ``evidence`` is expected to be qualified evidence events.  The function is
    pure and returns ordinary dictionaries so it can be used by Snowpark or by
    the reference engine.
    """
    evaluation_mode = normalize_evaluation_mode(evaluation_mode)
    ev = list(evidence)
    if patient_id is not None:
        ev = [e for e in ev if value(e, "patient_id", patient_id) == patient_id]
    evidence_by_atom: dict[str, list[Any]] = {}
    for item in ev:
        evidence_by_atom.setdefault(
            str(value(item, "atom_id", value(item, "ATOM_ID", ""))),
            [],
        ).append(item)
    out: list[dict[str, Any]] = []
    for signal in rows(config, "signals"):
        enabled = value(signal, "enabled", True)
        if enabled is False or str(enabled).upper() == "FALSE":
            continue
        sid = str(value(signal, "signal_id", ""))
        status, support, unknown, reason, witness_sets = _evaluate_signal_rule(
            config,
            signal,
            ev,
            evaluation_mode=evaluation_mode,
            birth_date=birth_date,
            evidence_by_atom=evidence_by_atom,
        )
        run_exec = str(value(signal, "runtime_executability", "EXECUTABLE") or "EXECUTABLE").upper()
        if run_exec in {"NON_EXECUTABLE", "NON_FIRING", "BLOCKED"}:
            if (
                is_icd_dated_claims(evaluation_mode)
                and run_exec == "NON_EXECUTABLE"
                and status == TRUE
                and support
                and all(is_native_claim_code(item) for item in support)
            ):
                gap_key = ("note_context",)
                gap_required = {"note_context": "clinical detail beyond the ICD-10 code"}
                support = [
                    _with_context_gaps(item, gap_key, gap_required)
                    for item in support
                ]
                witness_sets = [
                    [
                        _with_context_gaps(item, gap_key, gap_required)
                        if is_native_claim_code(item) else item
                        for item in witness_set
                    ]
                    for witness_set in witness_sets
                ]
                reason = "ICD_DATED_CLAIMS_CODE_WITHOUT_NOTE_CONTEXT"
            elif (
                is_claims_recall(evaluation_mode)
                and status == TRUE
                and support
                and all(is_native_claim_code(item) for item in support)
            ):
                support = [
                    provisional_copy(
                        item,
                        f"SIGNAL_RUNTIME_RESTRICTION:{run_exec}",
                        status=TRUE,
                    )
                    for item in support
                ]
                witness_sets = [
                    [
                        provisional_copy(
                            item,
                            f"SIGNAL_RUNTIME_RESTRICTION:{run_exec}",
                            status=TRUE,
                        ) if is_native_claim_code(item) else item
                        for item in witness_set
                    ]
                    for witness_set in witness_sets
                ]
                reason = "CLAIMS_RECALL_PROVISIONAL_RUNTIME_RESTRICTION"
            else:
                status = UNKNOWN
                reason = f"CONFIG_GAP:{run_exec}"
                support = []
                witness_sets = []
        if status == TRUE:
            # A configured blocker is evaluated only when represented as a
            # qualified blocker evidence event.  No clinical fallback occurs.
            blockers = grouped_rows(config, "signal_blockers", "signal_id").get(sid, [])
            for blocker in blockers:
                bid = value(blocker, "atom_id", "")
                b_evs = _evidence_for_atom(
                    _rows_for_atom(ev, str(bid), evidence_by_atom),
                    str(bid),
                    value(blocker, "required_attributes", None),
                )
                if any(norm_status(value(b, "status", UNKNOWN)) == TRUE for b in b_evs):
                    status, support, unknown = FALSE, [], b_evs
                    witness_sets = []
                    reason = f"blocked_by:{bid}"
                    break
        configured_tier = value(signal, "tier", None)
        if status == TRUE:
            effective_tier, tier_basis, context_gaps = _tier_from_support(
                configured_tier, witness_sets, support
            )
        else:
            effective_tier, tier_basis, context_gaps = configured_tier, None, []
        row = {
            "patient_id": patient_id if patient_id is not None else (value(support[0], "patient_id", None) if support else None),
            "phenotype": phenotype or value(signal, "phenotype", None),
            "signal_id": sid,
            "clinical_feature": value(signal, "clinical_feature", None),
            "status": status,
            "reasoning_bucket": value(signal, "reasoning_bucket", None),
            "configured_tier": configured_tier,
            "tier": effective_tier,
            "tier_basis": tier_basis,
            "context_gaps": context_gaps,
            "inferred_qualifiers": _collected_inferences(support),
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
            "evaluation_mode": evaluation_mode,
            "provisional": bool(collect_relaxations(support)),
            "relaxations": collect_relaxations(support),
        }
        out.append(row)
    return out


# Compatibility aliases used by some orchestration styles.
evaluate_signal_hits = evaluate_signals
run = evaluate_signals

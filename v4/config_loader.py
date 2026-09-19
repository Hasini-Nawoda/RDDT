"""Load clean clinical JSON and adapt it to the existing reasoning engines.

The deployable package is deliberately not a materialized copy of workbook
tables. Atoms own their extraction vocabulary, and phenotype rules own their
nested members. This module performs the only normalization step, in memory.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .runtime_config import RuntimeConfig


class ConfigLoadError(RuntimeError):
    """Raised when a clinical configuration package is incomplete or invalid."""


DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent / "config"
DEFAULT_REGISTRY_FILE = DEFAULT_CONFIG_DIR / "phenotype_registry.json"
PHENOTYPE_SLOTS = (
    "GENERAL_AMYLOID",
    "ATTR_COMMON",
    "ATTRWT",
    "ATTRV",
    "AL",
    "AA",
)

_COLLECTION_KEYS = {
    "atoms": ("atoms",),
    "signals": ("signals", "entries", "overlays"),
    "signal_rules": ("signal_rules", "rules", "entries"),
    "signal_atoms": ("signal_atoms", "mappings", "entries"),
    "buckets": ("buckets",),
    "priority_policies": ("priority_policies", "policies"),
    "combinations": ("combinations", "rules"),
    "guardrails": ("guardrails", "rules"),
}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigLoadError(f"Missing clinical configuration file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigLoadError(f"Invalid JSON in clinical configuration file: {path}") from exc


def _rows_from_value(value: Any, keys: Sequence[str], path: Path) -> List[Dict[str, Any]]:
    rows = value
    if isinstance(value, Mapping):
        rows = next((value[key] for key in keys if isinstance(value.get(key), list)), None)
    if not isinstance(rows, list):
        raise ConfigLoadError(
            f"Clinical configuration {path} must be a list or contain one of {tuple(keys)}"
        )
    if not all(isinstance(row, Mapping) for row in rows):
        raise ConfigLoadError(f"Clinical configuration {path} contains a non-object row")
    return [dict(row) for row in rows]


def _read_collection_files(directory: Path, table: str) -> tuple[List[Dict[str, Any]], List[Path]]:
    if not directory.is_dir():
        raise ConfigLoadError(f"Missing {table} directory: {directory}")
    files = sorted(directory.rglob("*.json"), key=lambda item: item.as_posix())
    if not files:
        raise ConfigLoadError(f"No {table} files found under {directory}")
    rows: List[Dict[str, Any]] = []
    for path in files:
        rows.extend(_rows_from_value(_read_json(path), _COLLECTION_KEYS[table], path))
    return rows, files


def _first_existing(root: Path, candidates: Sequence[str]) -> Optional[Path]:
    for relative in candidates:
        path = root / relative
        if path.is_file():
            return path
    return None


def _read_named_collection(
    root: Path,
    table: str,
    candidates: Sequence[str],
    *,
    required: bool = True,
) -> tuple[List[Dict[str, Any]], List[Path]]:
    path = _first_existing(root, candidates)
    if path is None:
        if required:
            raise ConfigLoadError(f"Missing {table} clinical configuration under {root}")
        return [], []
    return _rows_from_value(_read_json(path), _COLLECTION_KEYS[table], path), [path]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _config_hash(paths: Iterable[Path], base: Path) -> str:
    payload = bytearray()
    for path in sorted(set(paths), key=lambda item: item.as_posix()):
        relative = path.relative_to(base).as_posix() if base in path.parents else path.name
        payload.extend(relative.encode("utf-8"))
        payload.extend(b"\0")
        payload.extend(_canonical_bytes(_read_json(path)))
        payload.extend(b"\0")
    return hashlib.sha256(bytes(payload)).hexdigest()


def _normal_system(value: Any) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "CPT": "CPT_HCPCS",
        "HCPCS": "CPT_HCPCS",
        "CPT/HCPCS": "CPT_HCPCS",
        "SNOMED": "SNOMED_CT",
        "SNOMEDCT": "SNOMED_CT",
        "KEYWORD": "NLP",
        "PHRASE": "NLP",
    }
    return aliases.get(text, text)


def _term_row(atom: Mapping[str, Any], item: Any, system: str) -> Dict[str, Any]:
    data = dict(item) if isinstance(item, Mapping) else {"value": item}
    value = data.get("value", data.get("code", data.get("term", data.get("text"))))
    if value in (None, ""):
        raise ConfigLoadError(f"Atom {atom.get('atom_id')!r} contains an empty extraction term")
    return {
        "atom_id": str(atom.get("atom_id", "")),
        "terminology_system": _normal_system(
            data.get("terminology_system", data.get("system", system))
        ),
        "value": str(value),
        "can_fire_atom_alone": bool(
            data.get(
                "can_fire_atom_alone",
                data.get("can_fire", atom.get("can_fire_atom_alone", False)),
            )
        ),
        # Guards belong to atoms in the clean files. The adapter supplies the
        # inherited value because the matcher consumes it at term level.
        "context_guard": data.get("context_guard", atom.get("context_guard")),
    }


def _adapt_atoms(rows: Iterable[Mapping[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    atoms: List[Dict[str, Any]] = []
    terminology: List[Dict[str, Any]] = []
    for raw in rows:
        atom = dict(raw)
        atom_id = str(atom.get("atom_id", "")).strip()
        if not atom_id:
            raise ConfigLoadError("Shared atom catalog contains an empty atom_id")
        extraction = atom.pop("extraction", {}) or {}
        if not isinstance(extraction, Mapping):
            raise ConfigLoadError(f"Atom {atom_id!r} extraction must be an object")

        for key in ("nlp_terms", "keywords", "terms"):
            for item in extraction.get(key, ()) or ():
                terminology.append(_term_row(atom, item, "NLP"))
        codes = extraction.get("codes", {}) or {}
        if isinstance(codes, Mapping):
            for system, items in codes.items():
                for item in items or ():
                    terminology.append(_term_row(atom, item, str(system)))
        elif isinstance(codes, list):
            for item in codes:
                if not isinstance(item, Mapping):
                    raise ConfigLoadError(f"Atom {atom_id!r} code entry must be an object")
                terminology.append(_term_row(atom, item, str(item.get("system", ""))))
        else:
            raise ConfigLoadError(f"Atom {atom_id!r} extraction.codes must be an object or list")
        atoms.append(atom)
    return atoms, terminology


def _member_identity(member: Mapping[str, Any]) -> tuple[str, str]:
    if member.get("atom_id") not in (None, ""):
        return "ATOM", str(member["atom_id"])
    if member.get("signal_id") not in (None, ""):
        return "SIGNAL", str(member["signal_id"])
    return (
        str(member.get("member_type", member.get("type", "ATOM"))).upper(),
        str(member.get("member_id", member.get("id", ""))),
    )


def _adapt_signal_rule(
    signal_id: str,
    rule: Mapping[str, Any],
) -> tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Normalize one nested rule AST into the engine's row representation.

    The clean contract permits either a root group directly, a ``root``/``rule``
    wrapper, or an explicit ``groups`` representation.  In particular, a
    nested group member may be encoded as ``{"type": "group", "rule": {...}}``;
    older code treated that wrapper as an ordinary member and lost the child
    group.  This adapter keeps the wrapper's id/order while representing the
    child through the existing parent-group edge.
    """
    groups: List[Dict[str, Any]] = []
    members: List[Dict[str, Any]] = []
    counter = 0

    def next_group_id() -> str:
        nonlocal counter
        counter += 1
        return f"{signal_id}_G{counter:03d}"

    def _group_payload(raw: Mapping[str, Any]) -> Mapping[str, Any]:
        nested = raw.get("rule")
        if isinstance(nested, Mapping) and not raw.get("members") and not raw.get("children"):
            return nested
        return raw

    def _members(raw: Mapping[str, Any]) -> list[Any]:
        value = raw.get("members", raw.get("children", ()))
        return list(value or ()) if isinstance(value, (list, tuple)) else []

    def _is_group_wrapper(raw: Mapping[str, Any]) -> bool:
        member_type = str(raw.get("member_type", raw.get("type", ""))).upper()
        nested = raw.get("rule")
        return member_type == "GROUP" and isinstance(nested, Mapping)

    def emit_group(
        raw_group: Mapping[str, Any],
        parent: Optional[str],
        order: int,
        forced_id: Optional[str] = None,
    ) -> str:
        group = _group_payload(raw_group)
        group_id = str(
            forced_id
            or raw_group.get("group_id")
            or raw_group.get("id")
            or group.get("group_id")
            or group.get("id")
            or next_group_id()
        )
        groups.append({
            "signal_id": signal_id,
            "group_id": group_id,
            "parent_group_id": parent,
            "evaluation_order": int(group.get("evaluation_order", order) or order),
            "operator": str(group.get("operator", group.get("op", "ANY"))).upper(),
            "minimum_count": group.get("minimum_count"),
            "require_independent_lineage": bool(group.get("require_independent_lineage", False)),
            "linkage_type": group.get("linkage_type"),
        })
        for member_order, raw_member in enumerate(_members(group), 1):
            if isinstance(raw_member, str):
                raw_member = {"member_type": "ATOM", "member_id": raw_member}
            if not isinstance(raw_member, Mapping):
                raise ConfigLoadError(f"Signal {signal_id!r} contains a non-object rule member")
            nested_rule = raw_member.get("rule")
            is_nested = _is_group_wrapper(raw_member) or (
                bool(_members(raw_member))
                and ("operator" in raw_member or "op" in raw_member)
            )
            if is_nested:
                child_id = raw_member.get("group_id") or raw_member.get("id")
                emit_group(
                    nested_rule if isinstance(nested_rule, Mapping) else raw_member,
                    group_id,
                    int(raw_member.get("evaluation_order", member_order) or member_order),
                    str(child_id) if child_id not in (None, "") else None,
                )
                continue
            member_type, member_id = _member_identity(raw_member)
            if not member_id:
                raise ConfigLoadError(f"Signal {signal_id!r} contains a rule member without an id")
            members.append({
                "signal_id": signal_id,
                "group_id": group_id,
                "evaluation_order": int(raw_member.get("evaluation_order", member_order) or member_order),
                "member_type": member_type,
                "member_id": member_id,
                "required_attributes": raw_member.get(
                    "required_attributes", raw_member.get("required_qualifiers", raw_member.get("qualifiers"))
                ),
                "member_role": raw_member.get("role", raw_member.get("member_role")),
                "experiencer": raw_member.get("experiencer"),
            })
        return group_id

    # A rule record may wrap the AST as ``root`` or ``rule``.  Keep rule-level
    # controls outside the root group while accepting the historical direct
    # group shape.
    root_rule: Mapping[str, Any] = rule
    if isinstance(rule.get("root"), Mapping):
        root_rule = rule["root"]
    elif isinstance(rule.get("rule"), Mapping):
        root_rule = rule["rule"]

    explicit_groups = root_rule.get("groups")
    if isinstance(explicit_groups, list) and explicit_groups:
        explicit_group_ids: set[str] = set()
        deferred_parent_edges: list[tuple[str, str, int]] = []
        for order, group in enumerate(explicit_groups, 1):
            if not isinstance(group, Mapping):
                raise ConfigLoadError(f"Signal {signal_id!r} contains a non-object rule group")
            group_id = str(group.get("group_id") or group.get("id") or next_group_id())
            explicit_group_ids.add(group_id)
            emit_group(group, group.get("parent_group_id"), order, group_id)
            for member_order, raw_member in enumerate(_members(group), 1):
                if isinstance(raw_member, Mapping):
                    member_type, member_id = _member_identity(raw_member)
                    if member_type == "GROUP" and member_id:
                        deferred_parent_edges.append((group_id, member_id, int(raw_member.get("evaluation_order", member_order) or member_order)))
        group_index = {str(group["group_id"]): group for group in groups}
        for parent_id, child_id, child_order in deferred_parent_edges:
            child = group_index.get(child_id)
            if child is None:
                raise ConfigLoadError(f"Signal {signal_id!r} references missing group {child_id!r}")
            child["parent_group_id"] = parent_id
            child["evaluation_order"] = child_order
        members = [member for member in members if member["member_type"] != "GROUP"]
        root_id = str(root_rule.get("root_group_id") or rule.get("root_group_id") or next(
            (group["group_id"] for group in groups if not group.get("parent_group_id")),
            groups[0]["group_id"],
        ))
    else:
        root_id = emit_group(root_rule, None, 1)

    rule_row = {
        "signal_id": signal_id,
        "root_group_id": root_id,
        "enabled": bool(rule.get("enabled", root_rule.get("enabled", True))),
        "blocker_policy": rule.get("blocker_policy", "APPLY_SIGNAL_BLOCKERS_AFTER_SUPPORT_RULE"),
        "missing_data_policy": rule.get("missing_data_policy"),
        "truth_model": rule.get("truth_model", rule.get("three_valued_logic")),
        "outcome": rule.get("outcome", rule.get("rule_outcome")),
    }
    return rule_row, groups, members


def _is_direct_signal(row: Mapping[str, Any]) -> bool:
    action = str(row.get("config_action", row.get("action", "POSITIVE_SIGNAL")) or "").upper()
    entity = str(row.get("entity_type", row.get("kind", "SIGNAL")) or "").upper()
    return action == "POSITIVE_SIGNAL" and entity in {"", "SIGNAL", "DIRECT_SIGNAL"}


def _adapt_signal_atom_mappings(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        signal_id = str(row.get("signal_id", row.get("Signal_ID", ""))).strip()
        atom_id = str(row.get("atom_id", row.get("Atom_ID", ""))).strip()
        if not signal_id or not atom_id:
            raise ConfigLoadError("Signal atom mapping requires signal_id and atom_id")
        row["signal_id"] = signal_id
        row["atom_id"] = atom_id
        if "required_qualifiers" not in row and "required_attributes" in row:
            row["required_qualifiers"] = row.get("required_attributes")
        if "can_fire_from_this_mapping" not in row:
            row["can_fire_from_this_mapping"] = row.get(
                "can_fire_from_mapping",
                row.get("can_fire", True),
            )
        output.append(row)
    return output


def _adapt_signal_rule_records(rows: Iterable[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    tables = {
        "signal_rules": [],
        "signal_rule_refs": [],
        "signal_rule_groups": [],
        "signal_rule_members": [],
        "signal_blockers": [],
    }
    seen: set[str] = set()
    for raw in rows:
        record = dict(raw)
        signal_id = str(
            record.get("signal_id", record.get("rule_id", record.get("source_signal_id", "")))
        ).strip()
        if not signal_id:
            raise ConfigLoadError("Signal rule configuration contains an empty signal_id/rule_id")
        rule_kind = str(record.get("rule_kind", record.get("kind", "")) or "").upper()
        rule_ref = str(record.get("rule_ref", "") or "").strip()
        if rule_ref:
            tables["signal_rule_refs"].append({
                "signal_id": signal_id,
                "rule_ref": rule_ref,
                "rule_kind": rule_kind,
            })
        has_ast = any(
            isinstance(record.get(key), Mapping)
            or isinstance(record.get(key), list)
            for key in ("rule", "root", "ast", "groups")
        ) or "operator" in record or "op" in record or "members" in record
        if not has_ast and record.get("rule_ref") not in (None, ""):
            continue
        if signal_id in seen:
            raise ConfigLoadError(f"Duplicate signal rule {signal_id!r}")
        seen.add(signal_id)
        ast = record.get("rule", record.get("root", record.get("ast")))
        if not isinstance(ast, Mapping):
            # A direct nested AST is also accepted.
            ast = record
        rule_record = dict(record)
        for key in ("rule", "root", "ast", "blockers"):
            rule_record.pop(key, None)
        rule_row, groups, members = _adapt_signal_rule(signal_id, {**rule_record, **dict(ast)})
        tables["signal_rules"].append(rule_row)
        tables["signal_rule_groups"].extend(groups)
        tables["signal_rule_members"].extend(members)
        blockers = record.get("blockers", ast.get("blockers", ())) if isinstance(ast, Mapping) else ()
        for order, raw_blocker in enumerate(blockers or (), 1):
            blocker = {"atom_id": raw_blocker} if isinstance(raw_blocker, str) else dict(raw_blocker)
            atom_id = str(blocker.get("atom_id", "")).strip()
            if not atom_id:
                raise ConfigLoadError(f"Signal rule {signal_id!r} contains an invalid blocker")
            tables["signal_blockers"].append({
                "blocker_id": str(blocker.get("blocker_id") or f"{signal_id}_B{order:02d}"),
                "signal_id": signal_id,
                "atom_id": atom_id,
                "required_attributes": blocker.get("required_attributes", blocker.get("qualifiers")),
                "block_action": blocker.get("block_action", blocker.get("action", "BLOCK_SIGNAL")),
                "evaluation_semantics": blocker.get("evaluation_semantics"),
            })
    return tables


def _adapt_signals(
    rows: Iterable[Mapping[str, Any]],
    *,
    rule_rows: Optional[Iterable[Mapping[str, Any]]] = None,
    mapping_rows: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    tables = {
        "signals": [],
        "signals_catalog": [],
        "signal_rule_refs": [],
        "signal_rules": [],
        "signal_rule_groups": [],
        "signal_rule_members": [],
        "signal_atoms": [],
        "signal_blockers": [],
    }
    embedded_rules: List[Dict[str, Any]] = []
    embedded_mappings: List[Dict[str, Any]] = []
    for raw in rows:
        signal = dict(raw)
        signal_id = str(signal.get("signal_id", "")).strip()
        if not signal_id:
            raise ConfigLoadError("Signal configuration contains an empty signal_id")
        signal["signal_id"] = signal_id
        tables["signals_catalog"].append(signal)
        if _is_direct_signal(signal):
            tables["signals"].append(signal)
        embedded_rule = signal.get("rule", signal.get("signal_rule"))
        if isinstance(embedded_rule, Mapping):
            embedded_rules.append({
                "signal_id": signal_id,
                "rule": embedded_rule,
                "blockers": signal.get("blockers", ()),
            })

    if rule_rows is not None:
        tables = _merge_tables(tables, _adapt_signal_rule_records(rule_rows))
    elif embedded_rules:
        tables = _merge_tables(tables, _adapt_signal_rule_records(embedded_rules))

    if mapping_rows is not None:
        tables["signal_atoms"].extend(_adapt_signal_atom_mappings(mapping_rows))
    else:
        # Backward-compatible fallback for old embedded packages.  This is
        # intentionally only a convenience relation; new packages must emit
        # signal_atoms.json so mapping-level executability is authoritative.
        seen_mapping_pairs: set[tuple[str, str]] = set()
        for member in tables["signal_rule_members"]:
            if member["member_type"] == "ATOM":
                pair = (str(member["signal_id"]), str(member["member_id"]))
                if pair in seen_mapping_pairs:
                    continue
                seen_mapping_pairs.add(pair)
                tables["signal_atoms"].append({
                    "signal_id": member["signal_id"],
                    "atom_id": member["member_id"],
                    "can_fire_from_this_mapping": True,
                    "required_qualifiers": member.get("required_attributes"),
                })
    return tables


def _as_list(value: Any) -> List[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _adapt_combinations(rows: Iterable[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    tables = {
        "combinations": [],
        "combination_requirements": [],
        "requirement_buckets": [],
        "requirement_tiers": [],
        "requirement_signals": [],
    }
    for raw in rows:
        combo = dict(raw)
        combination_id = str(combo.get("combination_id", combo.get("rule_id", ""))).strip()
        if not combination_id:
            raise ConfigLoadError("Combination configuration contains an empty combination_id")
        combo["combination_id"] = combination_id
        nested_rule = combo.get("rule")
        requirements = combo.pop("requirements", combo.pop("requires", combo.pop("all_of", ()))) or ()
        if nested_rule is not None and requirements:
            raise ConfigLoadError(
                f"Combination {combination_id!r} cannot define both flat requirements and a nested rule"
            )
        if nested_rule is None and (not isinstance(requirements, list) or not requirements):
            raise ConfigLoadError(f"Combination {combination_id!r} has no executable logic")
        if nested_rule is not None and not isinstance(nested_rule, Mapping):
            raise ConfigLoadError(f"Combination {combination_id!r} nested rule must be an object")
        tables["combinations"].append(combo)
        for order, raw_requirement in enumerate(requirements, 1):
            if not isinstance(raw_requirement, Mapping):
                raise ConfigLoadError(f"Combination {combination_id!r} has a non-object requirement")
            requirement = dict(raw_requirement)
            requirement_id = str(requirement.get("requirement_id") or f"{combination_id}_R{order}")
            buckets = _as_list(requirement.pop("allowed_buckets", requirement.pop("buckets", requirement.pop("bucket", []))))
            tiers = _as_list(requirement.pop("allowed_tiers", requirement.pop("tiers", [])))
            signals = _as_list(requirement.pop("allowed_signal_ids", requirement.pop("signal_ids", [])))
            tables["combination_requirements"].append({
                "requirement_id": requirement_id,
                "combination_id": combination_id,
                "requirement_order": int(requirement.get("requirement_order", order) or order),
                "requirement_kind": str(requirement.get("requirement_kind", requirement.get("kind", "BUCKET"))),
                "context_witness_allowed": bool(requirement.get("context_witness_allowed", False)),
                "distinct_lineage_required": bool(requirement.get("distinct_lineage_required", True)),
                "minimum_count": requirement.get("minimum_count"),
            })
            tables["requirement_buckets"].extend(
                {"requirement_id": requirement_id, "reasoning_bucket": str(bucket)} for bucket in buckets
            )
            tables["requirement_tiers"].extend(
                {"requirement_id": requirement_id, "allowed_tier": tier} for tier in tiers
            )
            tables["requirement_signals"].extend(
                {"requirement_id": requirement_id, "allowed_signal_id": str(signal_id)}
                for signal_id in signals
            )
    return tables


def _merge_tables(*groups: Mapping[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for group in groups:
        for name, rows in group.items():
            out.setdefault(name, []).extend(rows)
    return out


def _validate_tables(tables: Mapping[str, List[Dict[str, Any]]]) -> None:
    atom_ids = [str(row.get("atom_id", "")) for row in tables.get("atoms", [])]
    duplicates = sorted({atom_id for atom_id in atom_ids if atom_ids.count(atom_id) > 1})
    if duplicates:
        raise ConfigLoadError(f"Shared atom catalog contains duplicate atom IDs: {duplicates}")
    known_atoms = set(atom_ids)
    referenced_atoms = {
        str(row.get("member_id"))
        for row in tables.get("signal_rule_members", [])
        if str(row.get("member_type", "")).upper() == "ATOM"
    }
    referenced_atoms.update(str(row.get("atom_id")) for row in tables.get("signal_blockers", []))
    referenced_atoms.update(str(row.get("atom_id")) for row in tables.get("signal_atoms", []))
    missing = sorted(referenced_atoms - known_atoms)
    if missing:
        raise ConfigLoadError(f"Signal configuration references unknown shared atoms: {missing}")

    catalog_ids = [str(row.get("signal_id", "")) for row in tables.get("signals_catalog", tables.get("signals", []))]
    duplicate_catalog = sorted({signal_id for signal_id in catalog_ids if catalog_ids.count(signal_id) > 1})
    if duplicate_catalog:
        raise ConfigLoadError(f"Phenotype signal catalog contains duplicate signal IDs: {duplicate_catalog}")
    signal_ids = [str(row.get("signal_id", "")) for row in tables.get("signals", [])]
    duplicate_signals = sorted({signal_id for signal_id in signal_ids if signal_ids.count(signal_id) > 1})
    if duplicate_signals:
        raise ConfigLoadError(f"Phenotype package contains duplicate signal IDs: {duplicate_signals}")

    known_signals = set(catalog_ids)
    mapping_signal_ids = {
        str(row.get("signal_id")) for row in tables.get("signal_atoms", [])
    }
    mapping_signal_ids.update(str(row.get("signal_id")) for row in tables.get("signal_blockers", []))
    missing_mapping_signals = sorted(mapping_signal_ids - known_signals)
    if missing_mapping_signals:
        raise ConfigLoadError(f"Signal mappings reference unknown signals: {missing_mapping_signals}")
    mapping_pairs = [
        (str(row.get("signal_id")), str(row.get("atom_id")))
        for row in tables.get("signal_atoms", [])
    ]
    duplicate_pairs = sorted({pair for pair in mapping_pairs if mapping_pairs.count(pair) > 1})
    if duplicate_pairs:
        raise ConfigLoadError(f"Duplicate signal-to-atom mappings: {duplicate_pairs}")
    referenced_signals = {
        str(row.get("member_id"))
        for row in tables.get("signal_rule_members", [])
        if str(row.get("member_type", "")).upper() == "SIGNAL"
    }
    def nested_signal_ids(node: Any) -> set[str]:
        found: set[str] = set()
        if not isinstance(node, Mapping):
            return found
        if str(node.get("type", node.get("member_type", ""))).upper() == "SIGNAL":
            identifier = node.get("id", node.get("member_id"))
            if identifier not in (None, ""):
                found.add(str(identifier))
        for member in node.get("members", ()) or ():
            found.update(nested_signal_ids(member))
        for group in node.get("groups", ()) or ():
            found.update(nested_signal_ids(group))
        nested = node.get("rule")
        if nested is not None:
            found.update(nested_signal_ids(nested))
        return found

    for combination in tables.get("combinations", []):
        referenced_signals.update(nested_signal_ids(combination.get("rule")))
    missing_signals = sorted(referenced_signals - known_signals)
    if missing_signals:
        raise ConfigLoadError(f"Clinical rules reference unknown signals: {missing_signals}")

    rule_ids = [str(row.get("signal_id", "")) for row in tables.get("signal_rules", [])]
    duplicate_rules = sorted({rule_id for rule_id in rule_ids if rule_ids.count(rule_id) > 1})
    if duplicate_rules:
        raise ConfigLoadError(f"Duplicate signal rule IDs: {duplicate_rules}")
    rule_set = set(rule_ids)
    direct_ids = set(signal_ids)
    missing_direct_rules = sorted(direct_ids - rule_set)
    if missing_direct_rules:
        raise ConfigLoadError(f"Direct signals missing structured rules: {missing_direct_rules}")

    known_atoms_by_signal: Dict[str, set[str]] = {}
    for row in tables.get("signal_atoms", []):
        known_atoms_by_signal.setdefault(str(row.get("signal_id")), set()).add(str(row.get("atom_id")))
    for row in tables.get("signal_rule_members", []):
        if str(row.get("member_type", "")).upper() != "ATOM":
            continue
        sid, aid = str(row.get("signal_id")), str(row.get("member_id"))
        # A mapping catalog is authoritative when present.  Missing mappings
        # are invalid because they would silently bypass can_fire restrictions.
        if tables.get("signal_atoms") and aid not in known_atoms_by_signal.get(sid, set()):
            raise ConfigLoadError(f"Signal {sid!r} rule references atom {aid!r} without a signal_atoms mapping")

    for combination in tables.get("combinations", []):
        if combination.get("rule") is not None and not nested_signal_ids(combination.get("rule")):
            raise ConfigLoadError(
                f"Nested combination {combination.get('combination_id')!r} references no signals"
            )


def _resolve_roots(bundle_dir: Optional[str | Path], phenotype: str) -> tuple[Path, Path, Path, Dict[str, Any]]:
    requested = str(phenotype).upper()
    if requested not in PHENOTYPE_SLOTS:
        raise ConfigLoadError(f"Unsupported phenotype slot {requested!r}; expected one of {PHENOTYPE_SLOTS}")
    root = Path(bundle_dir or DEFAULT_CONFIG_DIR).expanduser().resolve()
    registry_path = root / "phenotype_registry.json"
    registry: Dict[str, Any] = {}
    registry_root = root
    if registry_path.is_file():
        value = _read_json(registry_path)
        if not isinstance(value, Mapping):
            raise ConfigLoadError("Phenotype registry must be a JSON object")
        registry = dict(value)
        packages = registry.get("packages", registry.get("phenotypes", {}))
        package = packages.get(requested) if isinstance(packages, Mapping) else None
        if isinstance(package, str):
            relative = package
        elif isinstance(package, Mapping):
            status = str(package.get("status", "LOADED")).upper()
            if status not in {"LOADED", "ACTIVE", "ENABLED"}:
                raise ConfigLoadError(f"Phenotype {requested!r} is registered but its configuration is not loaded")
            relative = package.get("path")
        else:
            relative = None
        if not relative:
            raise ConfigLoadError(f"Phenotype {requested!r} has no clinical package path")
        phenotype_root = (root / str(relative)).resolve()
        shared_entry = registry.get("shared", "shared")
        shared_relative = shared_entry.get("path", "shared") if isinstance(shared_entry, Mapping) else shared_entry
        shared_root = (root / str(shared_relative)).resolve()
    else:
        # Direct package loading is useful in a Snowflake workspace. The
        # expected package location is config/phenotypes/<PHENOTYPE>.
        phenotype_root = root
        registry_root = root.parent.parent if root.parent.name.lower() == "phenotypes" else root
        shared_root = registry_root / "shared"
    for path, label in ((phenotype_root, "phenotype"), (shared_root, "shared")):
        if not path.is_dir():
            raise ConfigLoadError(f"Missing {label} clinical configuration directory: {path}")
        if registry_root != path and registry_root not in path.parents:
            raise ConfigLoadError(f"{label.title()} configuration path escapes config root")
    return registry_root, shared_root, phenotype_root, registry


def load_compiled_config(
    bundle_dir: Optional[str | Path] = None,
    *,
    phenotype: str = "ATTRV",
    verify_hash: bool = True,
    require_valid_report: bool = True,
) -> RuntimeConfig:
    """Load one phenotype from the clean clinical configuration layout.

    The two legacy keyword arguments remain accepted so older notebook calls
    do not fail, but runtime loading no longer depends on a compiler manifest
    or validation report. ``config_hash`` is derived from the clean files.
    """
    del verify_hash, require_valid_report
    requested = str(phenotype).upper()
    registry_root, shared_root, phenotype_root, registry = _resolve_roots(bundle_dir, requested)

    atom_rows, atom_files = _read_collection_files(shared_root / "atoms", "atoms")
    atoms, terminology = _adapt_atoms(atom_rows)
    # Signals are one phenotype-level catalog because rules may reference
    # signals from other source specialties. Keep the directory form as a
    # compatibility fallback for older generated bundles.
    signal_path = _first_existing(phenotype_root, ("signals.json", "signals/signals.json"))
    if signal_path is not None:
        signal_rows, signal_files = _read_named_collection(
            phenotype_root,
            "signals",
            (signal_path.relative_to(phenotype_root).as_posix(),),
        )
    else:
        signal_rows, signal_files = _read_collection_files(phenotype_root / "signals", "signals")
    signal_rule_rows, signal_rule_files = _read_named_collection(
        phenotype_root,
        "signal_rules",
        ("signal_rules.json", "rules/signal_rules.json", "signals/signal_rules.json"),
        required=False,
    )
    signal_mapping_rows, signal_mapping_files = _read_named_collection(
        phenotype_root,
        "signal_atoms",
        ("signal_atoms.json", "relationships/signal_atoms.json", "signals/signal_atoms.json"),
        required=False,
    )
    if signal_path is not None and not signal_rule_rows:
        raise ConfigLoadError(
            f"Modern phenotype package requires signal_rules.json alongside {signal_path}"
        )
    if signal_path is not None and not signal_mapping_rows:
        raise ConfigLoadError(
            f"Modern phenotype package requires signal_atoms.json alongside {signal_path}"
        )
    signal_tables = _adapt_signals(
        signal_rows,
        rule_rows=signal_rule_rows or None,
        mapping_rows=signal_mapping_rows or None,
    )

    buckets, bucket_files = _read_named_collection(
        phenotype_root, "buckets", ("buckets.json", "algorithm/buckets.json")
    )
    priorities, priority_files = _read_named_collection(
        phenotype_root,
        "priority_policies",
        ("priority_policies.json", "algorithm/priority_policies.json"),
    )
    combinations, combination_files = _read_named_collection(
        phenotype_root, "combinations", ("combinations.json", "combinations/combinations.json")
    )
    guardrails, guardrail_files = _read_named_collection(
        phenotype_root,
        "guardrails",
        ("guardrails.json", "guardrails/guardrails.json"),
        required=False,
    )

    tables = _merge_tables(
        {"atoms": atoms, "terminology": terminology},
        signal_tables,
        {"buckets": buckets, "priority_policies": priorities, "guardrails": guardrails},
        _adapt_combinations(combinations),
    )
    _validate_tables(tables)
    loaded_files = (
        atom_files
        + signal_files
        + signal_rule_files
        + signal_mapping_files
        + bucket_files
        + priority_files
        + combination_files
        + guardrail_files
    )
    schema_version = str(registry.get("schema_version", registry.get("schema", "v4-clinical-config-v1")))
    return RuntimeConfig(
        phenotype_name=requested,
        tables=tables,
        config_hash=_config_hash(loaded_files, registry_root),
        schema_version=schema_version,
        root=str(phenotype_root),
    )


def load_phenotype_config(
    phenotype: str,
    bundle_dir: Optional[str | Path] = None,
    **kwargs: Any,
) -> RuntimeConfig:
    return load_compiled_config(bundle_dir, phenotype=phenotype, **kwargs)


def load_phenotype_configs(
    phenotypes: Optional[Iterable[str]] = None,
    bundle_dir: Optional[str | Path] = None,
    **kwargs: Any,
) -> Dict[str, RuntimeConfig]:
    selected = tuple(phenotypes or ("ATTRV",))
    return {
        str(phenotype).upper(): load_phenotype_config(str(phenotype), bundle_dir, **kwargs)
        for phenotype in selected
    }


def read_phenotype_registry(bundle_dir: Optional[str | Path] = None) -> Dict[str, Any]:
    root = Path(bundle_dir or DEFAULT_CONFIG_DIR).expanduser().resolve()
    registry = _read_json(root / "phenotype_registry.json")
    if not isinstance(registry, Mapping):
        raise ConfigLoadError("Phenotype registry must be a JSON object")
    return dict(registry)


def load_config(*args: Any, **kwargs: Any) -> RuntimeConfig:
    return load_compiled_config(*args, **kwargs)


def load_runtime_config(*args: Any, **kwargs: Any) -> RuntimeConfig:
    return load_compiled_config(*args, **kwargs)


# Historical function names remain import-compatible; they no longer imply a
# compiled workbook artifact.
load_compiled_bundle = load_compiled_config
DEFAULT_COMPILED_DIR = DEFAULT_CONFIG_DIR

__all__ = [
    "ConfigLoadError",
    "DEFAULT_CONFIG_DIR",
    "DEFAULT_REGISTRY_FILE",
    "PHENOTYPE_SLOTS",
    "load_compiled_config",
    "load_config",
    "load_runtime_config",
    "load_compiled_bundle",
    "load_phenotype_config",
    "load_phenotype_configs",
    "read_phenotype_registry",
]

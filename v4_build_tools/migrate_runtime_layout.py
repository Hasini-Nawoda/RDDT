"""Build compact deployable clinical config from the flat workbook export.

The flat export is build-time material. This script drops workbook coordinates,
hashes, review state, validation state, and denormalized joins. Runtime JSON
follows the V3 pattern: shared atoms own extraction vocabulary; phenotype
packages own signals and reasoning rules.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

try:
    from .terminology_normalization import normalize_atom_provenance, normalize_term, source_terminology
except ImportError:  # pragma: no cover - supports direct build-tool invocation
    from terminology_normalization import normalize_atom_provenance, normalize_term, source_terminology

ROOT = Path(__file__).resolve().parents[1]
PHENOTYPE_SLOTS = ("GENERAL_AMYLOID", "ATTR_COMMON", "ATTRWT", "ATTRV", "AL", "AA")


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def read_table(flat_dir: Path, name: str) -> List[Dict[str, Any]]:
    value = json.loads((flat_dir / f"{name}.json").read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"Expected list in {name}.json")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value))


def specialty(row: Dict[str, Any], fallback: str = "UNSPECIFIED") -> str:
    value = row.get("source_specialty") or row.get("specialty")
    return str(value).strip() if value is not None and str(value).strip() else fallback


def meaningful(value: Any) -> bool:
    return value not in (None, "", [], {}, "NONE (Active)")


def add_if(target: Dict[str, Any], key: str, value: Any) -> None:
    if meaningful(value):
        target[key] = value


def replace_generated_directory(path: Path, config_root: Path) -> None:
    resolved, root = path.resolve(), config_root.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"Refusing to replace path outside config root: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def build_shared_atoms(
    tables: Dict[str, List[Dict[str, Any]]],
    used_atom_ids: set[str] | None = None,
) -> Dict[str, List[Dict[str, Any]]]:
    _, exact_values = source_terminology()
    terminology: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in tables["terminology"]:
        terminology[str(row["atom_id"])].append(row)

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for source in sorted(tables["atoms"], key=lambda row: str(row.get("atom_id", ""))):
        atom_id = str(source["atom_id"])
        if used_atom_ids is not None and atom_id not in used_atom_ids:
            continue
        atom: Dict[str, Any] = {
            "atom_id": atom_id,
            "preferred_name": source["preferred_clinical_name"],
            "stage": source["stage"],
            "experiencer": source["experiencer"],
        }
        atom = normalize_atom_provenance(atom, source)
        if source.get("clinical_meaning") != source.get("preferred_clinical_name"):
            add_if(atom, "clinical_meaning", source.get("clinical_meaning"))
        add_if(atom, "context_guard", source.get("context_guard"))

        codes: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        nlp_terms: List[Dict[str, Any]] = []
        for term in sorted(
            terminology.get(atom_id, []),
            key=lambda row: (str(row.get("terminology_system", "")), str(row.get("value", ""))),
        ):
            item = normalize_term(
                term,
                atom_id=atom_id,
                exact_values=exact_values,
            )
            if str(term.get("value_class", "")).upper() == "NLP_TERM" or str(
                term.get("terminology_system", "")
            ).upper() == "NLP":
                nlp_terms.append(item)
            else:
                codes[str(term["terminology_system"])].append(item)

        atom["extraction"] = {
            "codes": {system: entries for system, entries in sorted(codes.items())},
            "nlp_terms": nlp_terms,
        }
        grouped[specialty(source)].append(atom)
    return grouped


def nested_signal_rule(
    signal_id: str,
    rule_row: Dict[str, Any],
    group_rows: List[Dict[str, Any]],
    member_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    groups = {str(row["group_id"]): row for row in group_rows if str(row.get("signal_id")) == signal_id}
    members: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in member_rows:
        if str(row.get("signal_id")) == signal_id:
            members[str(row["group_id"])].append(row)

    children: Dict[str, List[str]] = defaultdict(list)
    for group_id, row in groups.items():
        parent = row.get("parent_group_id")
        if meaningful(parent):
            children[str(parent)].append(group_id)

    def materialize(group_id: str) -> Dict[str, Any]:
        source = groups[group_id]
        group: Dict[str, Any] = {"operator": source["operator"]}
        add_if(group, "minimum_count", source.get("minimum_count"))
        if source.get("require_independent_lineage"):
            group["require_independent_lineage"] = True
        add_if(group, "linkage_type", source.get("linkage_type"))
        # Synthetic root notes are compiler scaffolding, not clinical runtime
        # semantics. Preserve only meaningful source rule notes.
        notes = source.get("notes")
        if str(notes or "").strip().lower() != "synthetic single-member root":
            add_if(group, "clinical_note", notes)

        ordered: List[tuple[int, str, Any]] = []
        for row in members.get(group_id, []):
            item: Dict[str, Any] = {
                "type": str(row["member_type"]).lower(),
                "id": row["member_id"],
            }
            add_if(item, "role", row.get("member_role"))
            add_if(item, "experiencer", row.get("experiencer"))
            add_if(item, "required_attributes", row.get("required_attributes"))
            ordered.append((int(row.get("evaluation_order") or 0), str(row.get("member_id", "")), item))
        for child_id in children.get(group_id, []):
            child = groups[child_id]
            ordered.append(
                (
                    int(child.get("evaluation_order") or 0),
                    child_id,
                    {"type": "group", "rule": materialize(child_id)},
                )
            )
        group["members"] = [item for _, _, item in sorted(ordered, key=lambda value: (value[0], value[1]))]
        return group

    rule = materialize(str(rule_row["root_group_id"]))
    rule["missing_data_policy"] = rule_row["missing_data_policy"]
    rule["truth_model"] = rule_row["three_valued_logic"]
    rule["outcome"] = rule_row["rule_outcome"]
    add_if(rule, "temporal_policy", rule_row.get("temporal_policy"))
    add_if(rule, "blocker_policy", rule_row.get("blocker_policy"))
    return rule


def signal_kind(source: Dict[str, Any]) -> str:
    """Return the stable catalog kind for a workbook Signals row."""
    action = str(source.get("config_action") or "").strip().upper()
    role = str(source.get("algorithm_role") or "").strip().upper()
    if action == "POSITIVE_SIGNAL":
        return "DIRECT"
    if action == "DO_NOT_TRIGGER" or role == "DO_NOT_USE":
        return "DO_NOT_USE"
    if role == "GUARDRAIL" or action.endswith("GUARDRAIL"):
        return "GUARDRAIL"
    return action or role or "UNSPECIFIED"


def build_signal_metadata(tables: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Build one phenotype-level metadata catalog for every Signals row.

    Clinical rule ASTs live in signal_rules.json. This file deliberately keeps
    only signal identity, routing metadata, and the workbook action/entity
    classification.
    """
    output: List[Dict[str, Any]] = []
    for source in sorted(tables["signals"], key=lambda row: str(row.get("signal_id", ""))):
        signal: Dict[str, Any] = {
            "signal_id": str(source["signal_id"]),
            "clinical_feature": source["clinical_feature"],
            "entity_type": source["entity_type"],
            "config_action": source["config_action"],
            "algorithm_role": source["algorithm_role"],
            "gate_role": source["gate_role"],
            "enabled": bool(source["enabled"]),
            "source_type": source["source_type"],
            "source_specialty": specialty(source),
            "source_subdomain": source.get("source_subdomain"),
            "reasoning_bucket": source.get("reasoning_bucket"),
            "bucket_class": source.get("bucket_class"),
            "tier": source.get("tier"),
            "canonical_dedup_group": source.get("canonical_dedup_group"),
            "evidence_stage": source.get("evidence_stage"),
            "runtime_executability": source.get("runtime_executability"),
            "evidence_mode": source.get("evidence_mode"),
        }
        if meaningful(source.get("guardrail_notes")):
            signal["clinical_note"] = source["guardrail_notes"]
        qualifiers = source.get("required_qualifiers")
        if meaningful(qualifiers) and str(qualifiers).strip().lower() != "none (default affirmed/confirmed)":
            signal["required_qualifiers"] = qualifiers
        output.append(signal)
    return output


def build_signal_rules(tables: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Build the single authoritative structured rule catalog.

    Every catalog signal has one normalized nested rule AST. Cross-bucket
    patient-level logic belongs to combinations, never to synthetic signals.
    """
    rule_by_signal = {str(row["signal_id"]): row for row in tables["signal_rules"]}
    blockers: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for source in tables["signal_blockers"]:
        blocker: Dict[str, Any] = {
            "blocker_id": source["blocker_id"],
            "atom_id": source["atom_id"],
            "action": source["block_action"],
        }
        add_if(blocker, "required_attributes", source.get("required_attributes"))
        add_if(blocker, "evaluation_semantics", source.get("evaluation_semantics"))
        blockers[str(source["signal_id"])].append(blocker)

    output: List[Dict[str, Any]] = []
    for source in sorted(tables["signals"], key=lambda row: str(row.get("signal_id", ""))):
        signal_id = str(source["signal_id"])
        rule_row = rule_by_signal[signal_id]
        signal: Dict[str, Any] = {
            "signal_id": signal_id,
            "enabled": bool(source["enabled"]),
            "blockers": sorted(
                blockers.get(signal_id, []), key=lambda row: str(row["blocker_id"])
            ),
        }
        signal["rule"] = nested_signal_rule(
            signal_id,
            rule_row,
            tables["signal_rule_groups"],
            tables["signal_rule_members"],
        )
        output.append(signal)
    return output


def build_signal_atoms(tables: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Build the clean runtime signal-to-atom connector table."""
    output: List[Dict[str, Any]] = []
    for source in sorted(
        tables["signal_atoms"],
        key=lambda row: (str(row.get("signal_id", "")), str(row.get("atom_id", ""))),
    ):
        qualifiers = source.get("required_qualifiers")
        if str(qualifiers or "").strip().lower() == "none (default affirmed/confirmed)":
            qualifiers = None
        output.append(
            {
                "signal_id": str(source["signal_id"]),
                "atom_id": str(source["atom_id"]),
                "can_fire_from_mapping": bool(source.get("can_fire_from_this_mapping", False)),
                "evidence_mode": source.get("evidence_mode"),
                "experiencer": source.get("experiencer"),
                "stage": source.get("stage"),
                "required_qualifiers": qualifiers,
            }
        )
    return output


def _collect_rule_atoms(rule: Any, output: set[str]) -> None:
    if not isinstance(rule, dict):
        return
    if str(rule.get("type", "")).lower() == "atom" and rule.get("id"):
        output.add(str(rule["id"]))
    nested = rule.get("rule")
    if nested is not None:
        _collect_rule_atoms(nested, output)
    for member in rule.get("members", []) or []:
        _collect_rule_atoms(member, output)


def runtime_atom_ids(tables: Dict[str, List[Dict[str, Any]]]) -> set[str]:
    """Return atoms referenced by the deployable executable graph.

    Nested combination rules reference established signals, so atom ownership
    remains entirely in the direct signal graph.
    """
    used = {row["atom_id"] for row in build_signal_atoms(tables)}
    for row in build_signal_rules(tables):
        if not row.get("enabled") or "rule" not in row:
            continue
        _collect_rule_atoms(row["rule"], used)
        for blocker in row.get("blockers", []) or []:
            if blocker.get("atom_id"):
                used.add(str(blocker["atom_id"]))
    return used


def build_combinations(tables: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[str]] = defaultdict(list)
    tiers: Dict[str, List[int]] = defaultdict(list)
    signals: Dict[str, List[str]] = defaultdict(list)
    for row in tables["requirement_buckets"]:
        buckets[str(row["requirement_id"])].append(str(row["reasoning_bucket"]))
    for row in tables["requirement_tiers"]:
        tiers[str(row["requirement_id"])].append(int(row["allowed_tier"]))
    for row in tables["requirement_signals"]:
        signals[str(row["requirement_id"])].append(str(row["allowed_signal_id"]))

    requirements: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for source in sorted(
        tables["combination_requirements"],
        key=lambda row: (str(row.get("combination_id", "")), int(row.get("requirement_order") or 0)),
    ):
        requirement_id = str(source["requirement_id"])
        requirement: Dict[str, Any] = {"kind": source["requirement_kind"]}
        add_if(requirement, "buckets", sorted(set(buckets.get(requirement_id, []))))
        add_if(requirement, "tiers", sorted(set(tiers.get(requirement_id, []))))
        add_if(requirement, "signal_ids", sorted(set(signals.get(requirement_id, []))))
        add_if(requirement, "minimum_count", source.get("minimum_count"))
        if source.get("context_witness_allowed"):
            requirement["context_witness_allowed"] = True
        if source.get("distinct_lineage_required"):
            requirement["distinct_lineage_required"] = True
        add_if(requirement, "clinical_note", source.get("notes"))
        requirements[str(source["combination_id"])].append(requirement)

    nested_rules = build_combination_rules(tables)
    output: List[Dict[str, Any]] = []
    for source in sorted(tables["combinations"], key=lambda row: str(row.get("combination_id", ""))):
        combination_id = str(source["combination_id"])
        combination: Dict[str, Any] = {
            "combination_id": combination_id,
            "enabled": bool(source["enabled"]),
            "outcome": source["outcome"],
            "result_route": source["result_route"],
            "priority_policy_id": source["priority_policy_id"],
            "temporal_policy": source["temporal_policy"],
            "clinical_rationale": source["clinical_rationale"],
        }
        if combination_id in nested_rules:
            combination["rule"] = nested_rules[combination_id]
        else:
            combination["requirements"] = requirements.get(combination_id, [])
        add_if(combination, "clinical_note", source.get("notes"))
        output.append(combination)
    return output


def build_combination_rules(tables: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    members: Dict[tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for source in tables["combination_rule_members"]:
        members[(str(source["combination_id"]), str(source["group_id"]))].append(
            {"type": str(source["member_type"]).lower(), "id": source["member_id"]}
        )
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for source in sorted(
        tables["combination_rule_groups"],
        key=lambda row: (
            str(row.get("combination_id", "")),
            int(row.get("evaluation_order") or 0),
            str(row.get("group_id", "")),
        ),
    ):
        rule_id, group_id = str(source["combination_id"]), str(source["group_id"])
        group: Dict[str, Any] = {
            "group_id": group_id,
            "operator": source["operator"],
            "minimum_count": source["minimum_count"],
            "members": sorted(members.get((rule_id, group_id), []), key=lambda row: (row["type"], str(row["id"]))),
        }
        if source.get("require_independent_lineage"):
            group["require_independent_lineage"] = True
        add_if(group, "clinical_note", source.get("notes"))
        groups[rule_id].append(group)

    output: Dict[str, Dict[str, Any]] = {}
    for source in sorted(tables["combination_rules"], key=lambda row: str(row.get("combination_id", ""))):
        rule_id = str(source["combination_id"])
        output[rule_id] = {
            "definition": source["definition"],
            "enabled": bool(source["enabled"]),
            "operator": source["top_operator"],
            "groups": groups.get(rule_id, []),
        }
    return output


def build_buckets(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "bucket": row["reasoning_bucket"],
            "class": row["bucket_class"],
            "counts_independently": bool(row["counts_independently"]),
            "definition": row["definition"],
        }
        for row in sorted(rows, key=lambda item: str(item.get("reasoning_bucket", "")))
    ]


def build_priorities(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output = []
    for source in sorted(rows, key=lambda row: str(row.get("priority_policy_id", ""))):
        policy: Dict[str, Any] = {
            "priority_policy_id": source["priority_policy_id"],
            "class": source["priority_class"],
            "kind": source["policy_kind"],
        }
        add_if(policy, "tier_pattern", source.get("tier_pattern"))
        add_if(policy, "clinical_note", source.get("notes"))
        output.append(policy)
    return output


def build_guardrails(
    rows: Iterable[Dict[str, Any]],
    signals: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    signal_enabled = {
        str(row.get("signal_id")): bool(row.get("enabled")) for row in signals
    }
    output = []
    for source in sorted(rows, key=lambda row: str(row.get("guardrail_id", ""))):
        guardrail_id = str(source["guardrail_id"])
        guardrail: Dict[str, Any] = {
            "guardrail_id": guardrail_id,
            # Signals.Enabled is authoritative when a guardrail also has a
            # Signals row (notably V36, which is DO_NOT_USE and disabled).
            "enabled": bool(source["enabled"]) and signal_enabled.get(guardrail_id, True),
            "rule_ref": guardrail_id,
            "action": source["guardrail_action"],
            "route": source["route"],
            "does_not_negate_attrv": bool(source["does_not_negate_at_t_r_v"]),
        }
        add_if(guardrail, "message", source.get("message"))
        output.append(guardrail)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flat-dir", type=Path, default=ROOT / "v4_build_tools" / "compiled_flat")
    parser.add_argument("--runtime-dir", type=Path, default=ROOT / "v4" / "config")
    args = parser.parse_args()
    flat_dir = args.flat_dir.expanduser().resolve()
    config_root = args.runtime_dir.expanduser().resolve()
    source_manifest = json.loads((flat_dir / "manifest.json").read_text(encoding="utf-8"))
    phenotype = str(source_manifest.get("phenotype", "ATTRV")).upper()
    if phenotype not in PHENOTYPE_SLOTS:
        raise ValueError(f"Unsupported phenotype {phenotype!r}")
    tables = {name: read_table(flat_dir, name) for name in source_manifest["tables"]}

    shared_root = config_root / "shared"
    phenotype_root = config_root / "phenotypes" / phenotype
    replace_generated_directory(shared_root, config_root)
    replace_generated_directory(phenotype_root, config_root)

    for source_specialty, atoms in sorted(
        build_shared_atoms(tables, runtime_atom_ids(tables)).items()
    ):
        write_json(
            shared_root / "atoms" / f"{source_specialty}.json",
            {"source_specialty": source_specialty, "atoms": atoms},
        )
    write_json(
        phenotype_root / "signals.json",
        {"phenotype": phenotype, "signals": build_signal_metadata(tables)},
    )
    write_json(
        phenotype_root / "signal_rules.json",
        {"phenotype": phenotype, "signal_rules": build_signal_rules(tables)},
    )
    write_json(
        phenotype_root / "signal_atoms.json",
        {"phenotype": phenotype, "signal_atoms": build_signal_atoms(tables)},
    )

    write_json(phenotype_root / "combinations.json", {"phenotype": phenotype, "combinations": build_combinations(tables)})
    write_json(phenotype_root / "buckets.json", {"phenotype": phenotype, "buckets": build_buckets(tables["buckets"])})
    write_json(
        phenotype_root / "priority_policies.json",
        {"phenotype": phenotype, "priority_policies": build_priorities(tables["priority_policies"])},
    )
    write_json(
        phenotype_root / "guardrails.json",
        {
            "phenotype": phenotype,
            "guardrails": build_guardrails(tables["guardrails"], tables["signals"]),
        },
    )
    write_json(
        config_root / "phenotype_registry.json",
        {"shared_atoms": "shared/atoms", "phenotypes": {phenotype: f"phenotypes/{phenotype}"}},
    )


if __name__ == "__main__":
    main()

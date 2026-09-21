"""Mechanical reachability audit for the deployable ATTRv runtime package."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Support both ``python -m v4_build_tools.validation.audit_runtime_algorithm``
# and direct execution from the repository root.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v4.config_loader import load_phenotype_config, load_phenotype_configs
from v4.output.patient_profile import aggregate_attr_verdict
from v4.reasoning.match_engine import match_combinations
from v4.reasoning.priority import resolve_priority
from v4.reasoning.router import route_results


def _allowed(config: Any, table: str, requirement_id: str, field: str) -> set[str]:
    return {
        str(row[field])
        for row in config.rows(table)
        if str(row.get("requirement_id")) == requirement_id
    }


def _candidate_for_requirement(config: Any, requirement: dict[str, Any], index: int) -> dict[str, Any]:
    rid = str(requirement["requirement_id"])
    buckets = _allowed(config, "requirement_buckets", rid, "reasoning_bucket")
    tiers = _allowed(config, "requirement_tiers", rid, "allowed_tier")
    signals = _allowed(config, "requirement_signals", rid, "allowed_signal_id")
    catalog = config.rows("signals_catalog")
    choices = []
    for row in catalog:
        sid = str(row.get("signal_id"))
        bucket = str(row.get("reasoning_bucket") or "")
        tier = str(row.get("tier") or "")
        if signals and sid not in signals:
            continue
        if buckets and bucket not in buckets:
            continue
        if tiers and tier not in tiers:
            continue
        choices.append(row)
    if not choices:
        raise AssertionError(f"No configured signal can satisfy {rid}")
    row = choices[0]
    return {
        "patient_id": "ALGORITHM_AUDIT",
        "phenotype": "ATTRV",
        "signal_id": row["signal_id"],
        "status": "TRUE",
        "reasoning_bucket": row.get("reasoning_bucket"),
        "tier": row.get("tier"),
        "gate_role": row.get("gate_role"),
        "canonical_dedup_group": row.get("canonical_dedup_group"),
        "support_lineage_ids": (f"AUDIT_LINEAGE_{index}",),
        "event_dates": (f"2025-01-{index + 1:02d}",),
    }


def _nested_signal_ids(node: Any) -> set[str]:
    if not isinstance(node, dict):
        return set()
    output: set[str] = set()
    if str(node.get("type", "")).upper() == "SIGNAL" and node.get("id"):
        output.add(str(node["id"]))
    for member in node.get("members", []) or []:
        output.update(_nested_signal_ids(member))
    for group in node.get("groups", []) or []:
        output.update(_nested_signal_ids(group))
    if isinstance(node.get("rule"), dict):
        output.update(_nested_signal_ids(node["rule"]))
    return output


def _candidate_for_signal(config: Any, signal_id: str, index: int) -> dict[str, Any]:
    row = next(row for row in config.rows("signals_catalog") if str(row.get("signal_id")) == signal_id)
    return {
        "patient_id": "ALGORITHM_AUDIT",
        "phenotype": "ATTRV",
        "signal_id": signal_id,
        "status": "TRUE",
        "reasoning_bucket": row.get("reasoning_bucket"),
        "tier": row.get("tier"),
        "gate_role": row.get("gate_role"),
        "canonical_dedup_group": row.get("canonical_dedup_group"),
        "support_lineage_ids": (f"AUDIT_NESTED_LINEAGE_{index}",),
        "event_dates": (f"2025-02-{index + 1:02d}",),
    }


def audit() -> dict[str, Any]:
    config = load_phenotype_config("ATTRV")
    registered = load_phenotype_configs(("ATTRV", "ATTRWT", "AL"))
    atoms = {row["atom_id"] for row in config.rows("atoms")}
    term_atoms = {row["atom_id"] for row in config.rows("terminology")}
    # The atom registry is shared across all loaded phenotypes.  An atom used
    # only by ATTRwt is not an orphan merely because this audit's reachability
    # scenarios below are ATTRv-specific.
    referenced_atoms: set[str] = set()
    per_phenotype_references: dict[str, set[str]] = {}
    for phenotype, phenotype_config in registered.items():
        phenotype_references: set[str] = set()
        phenotype_references.update(row["atom_id"] for row in phenotype_config.rows("signal_atoms"))
        phenotype_references.update(
            row["member_id"]
            for row in phenotype_config.rows("signal_rule_members")
            if row.get("member_type") == "ATOM"
        )
        phenotype_references.update(row["atom_id"] for row in phenotype_config.rows("signal_blockers"))
        unknown = phenotype_references - atoms
        assert not unknown, {"phenotype": phenotype, "unknown_atom_refs": sorted(unknown)}
        per_phenotype_references[phenotype] = phenotype_references
        referenced_atoms.update(phenotype_references)
    assert atoms == term_atoms, {"atoms_without_terms": sorted(atoms - term_atoms), "unknown_term_atoms": sorted(term_atoms - atoms)}
    assert atoms == referenced_atoms, {"orphan_atoms": sorted(atoms - referenced_atoms), "unknown_refs": sorted(referenced_atoms - atoms)}

    signal_catalog = config.rows("signals_catalog")
    assert len(signal_catalog) == 39
    assert len({row["signal_id"] for row in signal_catalog}) == 39
    assert len(config.rows("signals")) == 31
    assert len(config.rows("guardrails")) == 8
    assert not config.rows("composite_rules")

    reachable: dict[str, str] = {}
    for combination in config.rows("combinations"):
        cid = str(combination["combination_id"])
        requirements = sorted(
            [row for row in config.rows("combination_requirements") if row["combination_id"] == cid],
            key=lambda row: (row.get("requirement_order") or 0, row["requirement_id"]),
        )
        nested_rule = combination.get("rule")
        assert bool(requirements) != bool(nested_rule), f"{cid} must have exactly one logic representation"
        if nested_rule:
            hits = [
                _candidate_for_signal(config, signal_id, index)
                for index, signal_id in enumerate(sorted(_nested_signal_ids(nested_rule)))
            ]
        else:
            hits = [_candidate_for_requirement(config, requirement, index) for index, requirement in enumerate(requirements)]
        result = next(row for row in match_combinations(config, hits, patient_id="ALGORITHM_AUDIT", phenotype="ATTRV") if row["combination_id"] == cid)
        assert result["status"] == "TRUE", {cid: result}
        priority = resolve_priority(config, result, result["selected_witnesses"])
        assert priority["priority_class"] in {"A", "B", "C"}, {cid: priority}
        reachable[cid] = priority["priority_class"]

    # The same biological/source lineage cannot satisfy both arms of a pair.
    combo = next(row for row in config.rows("combinations") if row["combination_id"] == "V_COMBO01")
    requirements = sorted(
        [row for row in config.rows("combination_requirements") if row["combination_id"] == "V_COMBO01"],
        key=lambda row: row["requirement_order"],
    )
    duplicate_hits = [_candidate_for_requirement(config, requirement, index) for index, requirement in enumerate(requirements)]
    for hit in duplicate_hits:
        hit["support_lineage_ids"] = ("SAME_BIOLOGICAL_EVENT",)
    duplicate_result = next(row for row in match_combinations(config, duplicate_hits, patient_id="ALGORITHM_AUDIT", phenotype="ATTRV") if row["combination_id"] == combo["combination_id"])
    assert duplicate_result["status"] == "UNKNOWN"
    assert duplicate_result["hold_reason"] == "HOLD_DUPLICATE_LINEAGE"

    all_signal_hits = [
        _candidate_for_signal(config, str(row["signal_id"]), index)
        for index, row in enumerate(config.rows("signals_catalog"))
        if row.get("reasoning_bucket")
    ]
    all_matches = match_combinations(
        config,
        all_signal_hits,
        patient_id="ALGORITHM_AUDIT",
        phenotype="ATTRV",
    )
    results, router_rows = route_results(
        config,
        all_matches,
        patient_id="ALGORITHM_AUDIT",
        phenotype="ATTRV",
    )
    assert len(results) == 1 and len(router_rows) == 1
    assert router_rows[0]["matched_combination_id"]
    assert router_rows[0]["suspicion_level"] in {
        "HIGHEST_SUSPICION", "HIGH_SUSPICION", "MODERATE_SUSPICION",
    }

    aggregate = aggregate_attr_verdict([
        {
            "patient_id": "ALGORITHM_AUDIT",
            "phenotype": "ATTRV",
            "status": "PHENOTYPE_PASS",
            "priority_class": "B",
            "suspicion_level": "HIGH_SUSPICION",
            "parallel_routes": ("REVIEW_ATTRWT",),
        },
        {
            "patient_id": "ALGORITHM_AUDIT",
            "phenotype": "ATTRWT",
            "status": "PHENOTYPE_PASS",
            "priority_class": "A",
            "suspicion_level": "HIGHEST_SUSPICION",
            "parallel_routes": (),
        },
    ])
    assert aggregate["suspicion_level"] == "HIGHEST_SUSPICION"
    route_only = aggregate_attr_verdict([
        {
            "patient_id": "ROUTE_ONLY_AUDIT",
            "phenotype": "ATTRV",
            "status": "NO_MATCH",
            "parallel_routes": ("REVIEW_ATTRWT",),
        },
        {
            "patient_id": "ROUTE_ONLY_AUDIT",
            "phenotype": "ATTRWT",
            "status": "NO_MATCH",
            "parallel_routes": (),
        },
    ])
    assert route_only["status"] == "NO_MATCH"

    return {
        "config_hash": config.config_hash,
        "atoms": len(atoms),
        "terminology_rows": len(config.rows("terminology")),
        "signal_catalog_rows": len(signal_catalog),
        "direct_signals": len(config.rows("signals")),
        "nested_combinations": sum(bool(row.get("rule")) for row in config.rows("combinations")),
        "guardrails": len(config.rows("guardrails")),
        "named_combinations_reached": reachable,
        "duplicate_lineage_hold": duplicate_result["hold_reason"],
        "single_verdict_combination": router_rows[0]["matched_combination_id"],
        "single_verdict_suspicion_level": router_rows[0]["suspicion_level"],
        "combined_attr_suspicion_level": aggregate["suspicion_level"],
        "cross_phenotype_route_does_not_promote": route_only["status"],
        "shared_atom_reference_scope": sorted(registered),
        "per_phenotype_atom_reference_counts": {
            phenotype: len(references)
            for phenotype, references in sorted(per_phenotype_references.items())
        },
    }


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, sort_keys=True))

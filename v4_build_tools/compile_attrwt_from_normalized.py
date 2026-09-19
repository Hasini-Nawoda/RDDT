"""Compile the normalized ATTRwt workbook into the deployable V4 package.

The workbook is the clinical source of truth.  This build tool keeps its
inspection/provenance fields out of runtime logic, preserves source code tokens
exactly, reuses canonical ATTRv atoms, and writes only clean JSON under v4/.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "v4_build_tools" / "source" / "ATTRwt_Normalized_Clinical_Filtering_Config_FINAL.xlsx"
SHARED = ROOT / "v4" / "config" / "shared" / "atoms"
WT = ROOT / "v4" / "config" / "phenotypes" / "ATTRWT"


def rows(wb: Any, sheet: str) -> list[dict[str, Any]]:
    values = list(wb[sheet].values)
    header = [str(value).strip() if value is not None else "" for value in values[0]]
    return [
        dict(zip(header, row))
        for row in values[1:]
        if any(value is not None for value in row)
    ]


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().upper() in {"TRUE", "YES", "Y", "1"}


def as_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    return [part.strip() for part in str(value).replace("\n", ";").split(";") if part.strip()]


def base_atom_ids() -> set[str]:
    """Read the committed canonical universe without discarding working edits."""
    found: set[str] = set()
    for path in sorted(SHARED.glob("*.json")):
        rel = path.relative_to(ROOT).as_posix()
        try:
            payload = subprocess.check_output(["git", "show", f"HEAD:{rel}"], text=True)
            data = json.loads(payload)
        except Exception:
            data = {"atoms": []}
        found.update(str(row.get("atom_id")) for row in data.get("atoms", []))
    return found


def current_atoms() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    by_id: dict[str, dict[str, Any]] = {}
    locations: dict[str, str] = {}
    for path in sorted(SHARED.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("atoms", []):
            by_id[str(row["atom_id"])] = row
            locations[str(row["atom_id"])] = path.name
    return by_id, locations


def normalize_bucket(value: Any) -> str | None:
    aliases = {
        "ORTHOPEDIC": "ORTHO",
        "ORTHO": "ORTHO",
        "CARDIAC": "CARDIO",
        "CARDIO": "CARDIO",
        "NEURO": "NEURO",
        "OTHER": "SYSTEMIC_CONTEXT",
        "CONTEXT": "SYSTEMIC_CONTEXT",
        "RESEARCH_ONLY": "LAB_CONTEXT",
        "AL_DIFFERENTIAL": "LAB_CONTEXT",
        "AA_DIFFERENTIAL": "LAB_CONTEXT",
    }
    if value in (None, ""):
        return None
    return aliases.get(str(value).strip().upper(), str(value).strip().upper())


def specialty_file(specialty: Any) -> str:
    value = str(specialty or "MULTISPECIALTY").strip().upper().replace(" ", "_")
    return {
        "ORTHOPEDICS": "ORTHOPEDICS_MSK.json",
        "ORTHOPEDICS_MSK": "ORTHOPEDICS_MSK.json",
        "CARDIOLOGY": "CARDIOLOGY.json",
        "NEUROLOGY": "NEUROLOGY.json",
        "HEMATOLOGY": "HEMATOLOGY.json",
        "NEPHROLOGY": "NEPHROLOGY.json",
        "RHEUMATOLOGY": "RHEUM_INFLAMMATORY.json",
        "RHEUM_INFLAMMATORY": "RHEUM_INFLAMMATORY.json",
        "GENERAL_MEDICINE": "GENERAL_MEDICINE.json",
        "GENETICS": "GENETICS.json",
    }.get(value, "MULTISPECIALTY.json")


def build_atoms(wb: Any, signal_atoms: list[dict[str, Any]], signal_members: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> None:
    workbook_atoms = {str(row["Atom_ID"]): row for row in rows(wb, "Atoms")}
    terminology = rows(wb, "Terminology")
    terms_by_atom: dict[str, list[dict[str, Any]]] = {}
    for row in terminology:
        terms_by_atom.setdefault(str(row["Atom_ID"]), []).append(row)

    needed = {str(row["Atom_ID"]) for row in signal_atoms}
    needed.update(str(row["Member_ID"]) for row in signal_members if str(row["Member_Type"]).upper() == "ATOM")
    needed.update(str(row["Atom_ID"]) for row in blockers)

    existing, locations = current_atoms()
    base_ids = base_atom_ids()
    current_wt_ids = set(existing) - base_ids
    # Preserve any WT-looking rows that the ATTRv package currently uses, but
    # remove orphaned provisional rows from the earlier build.
    attrv_refs = set()
    attrv_root = ROOT / "v4" / "config" / "phenotypes" / "ATTRV"
    for name in ("signal_atoms.json", "signal_rules.json", "guardrails.json"):
        path = attrv_root / name
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for atom_id in existing:
                if f'"{atom_id}"' in text:
                    attrv_refs.add(atom_id)

    desired_wt = needed - base_ids
    keep_ids = base_ids | desired_wt | attrv_refs
    # Prefer exact workbook definitions for all non-canonical WT atoms.  A
    # blocker may not have an Atoms row, so preserve its current clinical row
    # and replace its terminology from the workbook.
    for atom_id in sorted(desired_wt):
        if atom_id in workbook_atoms:
            source = workbook_atoms[atom_id]
            entry = {
                "atom_id": atom_id,
                "preferred_name": source["Preferred_Clinical_Name"],
                "stage": source["Stage"] or "PRETEST_SIGNAL",
                "experiencer": source["Experiencer"] or "PATIENT",
                "clinical_meaning": source["Clinical_Meaning"],
                "source_specialty": source["Source_Specialty"],
                "source_subdomain": source["Source_Subdomain"],
                "context_guard": source["Context_Guard"],
                "extraction": {"codes": {}, "nlp_terms": []},
            }
            for term in terms_by_atom.get(atom_id, []):
                term_payload = {
                    "value": str(term["Value"]),
                    "can_fire_atom_alone": as_bool(term["Can_Fire_Atom_Alone"]),
                    "value_class": term["Value_Class"],
                    "review_status": term["Review_Status"],
                    "context_guard": term["Context_Guard"],
                }
                system = str(term["Terminology_System"])
                if system.upper() == "NLP":
                    entry["extraction"]["nlp_terms"].append(term_payload)
                else:
                    entry["extraction"]["codes"].setdefault(system, []).append(term_payload)
            existing[atom_id] = entry
            locations[atom_id] = specialty_file(source["Source_Specialty"])
        else:
            # Blocker-only atoms are not repeated in the workbook Atoms sheet,
            # but their exact source terminology is still authoritative.
            blocker_terms = terms_by_atom.get(atom_id, [])
            entry = dict(existing.get(atom_id, {
                "atom_id": atom_id,
                "preferred_name": atom_id.replace("_", " ").title(),
                "stage": "PRETEST_SIGNAL",
                "experiencer": "PATIENT",
                "clinical_meaning": atom_id.replace("_", " "),
                "source_specialty": "MULTISPECIALTY",
                "source_subdomain": "guardrail",
            }))
            entry["extraction"] = {"codes": {}, "nlp_terms": []}
            if blocker_terms:
                entry["context_guard"] = blocker_terms[0]["Context_Guard"]
            for term in blocker_terms:
                payload = {
                    "value": str(term["Value"]),
                    "can_fire_atom_alone": as_bool(term["Can_Fire_Atom_Alone"]),
                    "value_class": term["Value_Class"],
                    "review_status": term["Review_Status"],
                    "context_guard": term["Context_Guard"],
                }
                if str(term["Terminology_System"]).upper() == "NLP":
                    entry["extraction"]["nlp_terms"].append(payload)
                else:
                    entry["extraction"]["codes"].setdefault(str(term["Terminology_System"]), []).append(payload)
            existing[atom_id] = entry
            locations.setdefault(atom_id, "MULTISPECIALTY.json")

    for path in sorted(SHARED.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        output: list[dict[str, Any]] = []
        emitted: set[str] = set()
        for row in data.get("atoms", []):
            atom_id = str(row["atom_id"])
            if atom_id not in keep_ids or locations.get(atom_id) != path.name:
                continue
            replacement = existing.get(atom_id) if atom_id in desired_wt else row
            output.append(replacement)
            emitted.add(atom_id)
        for atom_id, row in existing.items():
            if atom_id in keep_ids and locations.get(atom_id) == path.name and atom_id not in emitted:
                output.append(row)
        data["atoms"] = sorted(output, key=lambda row: str(row["atom_id"]))
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_signals(wb: Any) -> list[dict[str, Any]]:
    output = []
    for row in rows(wb, "Signals"):
        entity = str(row["Entity_Type"])
        action = str(row["Config_Action"])
        direct_entity = "SIGNAL" if entity == "COMPOSITE_RULE" else entity
        direct_action = "POSITIVE_SIGNAL" if action == "CROSS_BUCKET_COMPOSITE_RULE" else action
        gate = str(row["Gate_Role"])
        if entity == "COMPOSITE_RULE":
            gate = "ELIGIBLE"
        output.append({
            "signal_id": str(row["Signal_ID"]),
            "clinical_feature": row["Clinical_Feature"],
            "entity_type": direct_entity,
            "source_entity_type": entity,
            "config_action": direct_action,
            "source_config_action": action,
            "algorithm_role": row["Algorithm_Role"],
            "gate_role": gate,
            "enabled": as_bool(row["Enabled"], True),
            "source_type": row["Source_Type"],
            "source_specialty": row["Source_Specialty"],
            "source_subdomain": row["Source_Subdomain"],
            "reasoning_bucket": normalize_bucket(row["Reasoning_Bucket"]),
            "bucket_class": row["Bucket_Class"],
            "tier": row["Tier"],
            "canonical_dedup_group": row["Canonical_Dedup_Group"],
            "evidence_stage": row["Evidence_Stage"],
            "runtime_executability": row["Runtime_Executability"],
            "execution_block_reason": row["Execution_Block_Reason"],
            "evidence_mode": row["Evidence_Mode"],
            "source_atom_ids": as_list(row["Atom_IDs"]),
            "clinical_logic": row["Clinical_Logic"],
            "required_qualifiers": row["Required_Qualifiers"],
            "guardrail_notes": row["Guardrail_Notes"],
            "combination_ids": as_list(row["Combination_IDs"]),
            "clinical_source_ids": as_list(row["Clinical_Source_IDs"]),
        })
    return output


def build_signal_atoms(wb: Any) -> list[dict[str, Any]]:
    output = []
    for row in rows(wb, "Signal_Atoms"):
        output.append({
            "signal_id": str(row["Signal_ID"]),
            "atom_id": str(row["Atom_ID"]),
            "experiencer": row["Experiencer"],
            "stage": row["Stage"],
            "required_qualifiers": row["Required_Qualifiers"],
            "runtime_executability": row["Runtime_Executability"],
            "execution_block_reason": row["Execution_Block_Reason"],
            "evidence_mode": row["Evidence_Mode"],
            "can_fire_from_this_mapping": as_bool(row["Can_Fire_From_This_Mapping"]),
        })
    return output


def build_signal_rules(wb: Any) -> list[dict[str, Any]]:
    group_rows = rows(wb, "Signal_Rule_Groups")
    member_rows = rows(wb, "Signal_Rule_Members")
    blockers = rows(wb, "Signal_Blockers")
    output = []
    for row in rows(wb, "Signal_Rules"):
        sid = str(row["Signal_ID"])
        groups = []
        for group in [x for x in group_rows if str(x["Signal_ID"]) == sid]:
            members = []
            for member in [x for x in member_rows if str(x["Signal_ID"]) == sid and str(x["Group_ID"]) == str(group["Group_ID"])]:
                members.append({
                    "type": str(member["Member_Type"]).lower(),
                    "id": str(member["Member_ID"]),
                    "evaluation_order": int(member["Evaluation_Order"] or 0),
                    "required_attributes": member["Required_Attributes"],
                    "experiencer": member["Experiencer"],
                    "role": member["Member_Role"],
                })
            groups.append({
                "group_id": str(group["Group_ID"]),
                "parent_group_id": group["Parent_Group_ID"],
                "evaluation_order": int(group["Evaluation_Order"] or 0),
                "operator": str(group["Operator"]),
                "minimum_count": group["Minimum_Count"],
                "linkage_type": group["Linkage_Type"],
                "require_independent_lineage": as_bool(group["Require_Independent_Lineage"]),
                "members": members,
            })
        output.append({
            "signal_id": sid,
            "enabled": as_bool(row["Enabled"], True),
            "runtime_executability": row["Runtime_Executability"],
            "blocker_policy": row["Blocker_Policy"],
            "missing_data_policy": row["Missing_Data_Policy"],
            "truth_model": row["Three_Valued_Logic"],
            "outcome": row["Rule_Outcome"],
            "temporal_policy": row.get("Temporal_Policy"),
            "rule": {"root_group_id": str(row["Root_Group_ID"]), "groups": groups},
            "blockers": [
                {
                    "blocker_id": str(blocker["Blocker_ID"]),
                    "atom_id": str(blocker["Atom_ID"]),
                    "action": blocker["Block_Action"],
                    "required_attributes": blocker["Required_Attributes"],
                    "evaluation_semantics": blocker["Evaluation_Semantics"],
                }
                for blocker in blockers if str(blocker["Signal_ID"]) == sid
            ],
        })
    return output


def build_combinations(wb: Any) -> list[dict[str, Any]]:
    combos = rows(wb, "Combinations")
    reqs = rows(wb, "Combination_Requirements")
    buckets = rows(wb, "Requirement_Buckets")
    tiers = rows(wb, "Requirement_Tiers")
    signals = rows(wb, "Requirement_Signals")
    out = []
    for combo in combos:
        cid = str(combo["Combination_ID"])
        requirements = []
        for req in [x for x in reqs if str(x["Combination_ID"]) == cid]:
            rid = str(req["Requirement_ID"])
            requirements.append({
                "requirement_id": rid,
                "requirement_order": int(req["Requirement_Order"] or 0),
                "kind": req["Requirement_Kind"],
                "minimum_count": int(req["Minimum_Count"]) if req["Minimum_Count"] not in (None, "") else None,
                "context_witness_allowed": as_bool(req["Context_Witness_Allowed"]),
                "distinct_lineage_required": as_bool(req["Distinct_Lineage_Required"], True),
                "buckets": [
                    normalize_bucket(x["Reasoning_Bucket"])
                    for x in buckets
                    if str(x["Requirement_ID"]) == rid
                ],
                "tiers": [x["Allowed_Tier"] for x in tiers if str(x["Requirement_ID"]) == rid],
                "signal_ids": [x["Allowed_Signal_ID"] for x in signals if str(x["Requirement_ID"]) == rid],
                "notes": req["Notes"],
            })
        out.append({
            "combination_id": cid,
            "enabled": as_bool(combo["Enabled"], True),
            "outcome": combo["Outcome"],
            "result_route": combo["Result_Route"],
            "priority_policy_id": combo["Priority_Policy_ID"],
            "clinical_rationale": combo["Clinical_Rationale"],
            "temporal_policy": combo["Temporal_Policy"],
            "notes": combo["Notes"],
            "requirements": requirements,
        })
    return out


def build_package() -> None:
    wb = load_workbook(WORKBOOK, data_only=True)
    signal_atoms = rows(wb, "Signal_Atoms")
    signal_members = rows(wb, "Signal_Rule_Members")
    blockers = rows(wb, "Signal_Blockers")
    build_atoms(wb, signal_atoms, signal_members, blockers)
    WT.mkdir(parents=True, exist_ok=True)

    signals = build_signals(wb)
    mappings = build_signal_atoms(wb)
    signal_rules = build_signal_rules(wb)
    combinations = build_combinations(wb)
    # Multiple source-purpose buckets intentionally normalize to the same
    # runtime bucket (for example AL/AA/research context -> LAB_CONTEXT).
    # Emit exactly one runtime row per normalized bucket so dictionary lookup
    # is deterministic while retaining each distinct clinical definition.
    bucket_by_id: dict[str, dict[str, Any]] = {}
    for row in rows(wb, "Buckets"):
        bucket_id = normalize_bucket(row["Reasoning_Bucket"])
        if not bucket_id:
            continue
        bucket_class = row["Bucket_Class"]
        counts_independently = as_bool(row["Counts_Independently"], True)
        definition = str(row["Definition"] or "").strip()
        existing = bucket_by_id.get(bucket_id)
        if existing is None:
            bucket_by_id[bucket_id] = {
                "reasoning_bucket": bucket_id,
                "bucket_class": bucket_class,
                "counts_independently": counts_independently,
                "definition": definition,
            }
            continue
        if (
            existing["bucket_class"] != bucket_class
            or existing["counts_independently"] != counts_independently
        ):
            raise ValueError(
                f"Normalized bucket {bucket_id!r} has conflicting runtime semantics"
            )
        definitions = [part.strip() for part in str(existing["definition"]).split(" | ") if part.strip()]
        if definition and definition not in definitions:
            definitions.append(definition)
        existing["definition"] = " | ".join(definitions)
    bucket_rows = list(bucket_by_id.values())
    priorities = [
        {
            "priority_policy_id": row["Priority_Policy_ID"],
            "kind": "FIXED",
            "class": row["Priority_Class"],
            "tier_pattern": row["Tier_Pattern"] or "ANY",
            "clinical_note": row["Notes"],
        }
        for row in rows(wb, "Priority_Policies")
    ]
    # Guardrail IDs are descriptive routes; their corresponding signal rules
    # retain the WT## evidence logic.
    guardrails = []
    for row in rows(wb, "Guardrails"):
        guard_id = str(row["Guardrail_ID"])
        rule_ref = guard_id.split("_", 1)[0]
        guardrails.append({
            "guardrail_id": guard_id,
            "enabled": as_bool(row["Enabled"], True),
            "rule_ref": rule_ref,
            "action": row["Guardrail_Action"],
            "route": row["Route"],
            "does_not_negate_attrv": as_bool(row["Does_Not_Negate_ATTRV"], True),
            "clinical_condition": row["Clinical_Condition"],
            "message": row["Message"],
        })
    payloads = {
        "signals.json": {"phenotype": "ATTRWT", "signals": signals},
        "signal_atoms.json": {"phenotype": "ATTRWT", "signal_atoms": mappings},
        "signal_rules.json": {"phenotype": "ATTRWT", "signal_rules": signal_rules},
        "buckets.json": {"phenotype": "ATTRWT", "buckets": bucket_rows},
        "priority_policies.json": {"phenotype": "ATTRWT", "priority_policies": priorities},
        "combinations.json": {"phenotype": "ATTRWT", "combinations": combinations},
        "guardrails.json": {"phenotype": "ATTRWT", "guardrails": guardrails},
    }
    for name, payload in payloads.items():
        (WT / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build_package()
    print("Compiled", WORKBOOK, "to", WT)

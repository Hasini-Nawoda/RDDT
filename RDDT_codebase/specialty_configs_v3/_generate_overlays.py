# Generate phenotype_overlays/*.json from architecture file 11 + atom source_workbook_rows.
import json
import os
import glob
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
ATOMS = os.path.join(ROOT, "atoms")
OUT = os.path.join(ROOT, "phenotype_overlays")


def load_sign_map():
    sign_to_atoms = defaultdict(list)
    for path in glob.glob(os.path.join(ATOMS, "*.json")):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for a in data.get("atoms", []):
            for r in a.get("source_workbook_rows") or []:
                sign_to_atoms[r].append(a["atom_id"])
    return sign_to_atoms


def row(atom_id, sign_id, bucket, tier, role="POSITIVE_EVIDENCE", gate=None, **extra):
    if gate is None:
        if role == "MODIFIER":
            gate = False
        elif role == "ETIOLOGIC_CONTEXT":
            gate = tier <= 2
        else:
            gate = tier <= 2
        if tier >= 3:
            gate = False
    o = {
        "atom_id": atom_id,
        "source_sign_id": sign_id,
        "bucket": bucket,
        "tier": tier,
        "role": role,
        "gate_eligible": gate,
    }
    o.update(extra)
    return o


def expand(sign_to_atoms, sign_id, bucket, tier, role="POSITIVE_EVIDENCE", **extra):
    atoms = sign_to_atoms.get(sign_id, [])
    if not atoms:
        return []
    return [row(a, sign_id, bucket, tier, role, **extra) for a in atoms]


def composite(rule_id, sign_id, bucket, tier, note=""):
    return {
        "composite_rule_id": rule_id,
        "is_composite": True,
        "source_sign_id": sign_id,
        "bucket": bucket,
        "tier": tier,
        "role": "POSITIVE_EVIDENCE",
        "gate_eligible": tier <= 2,
        "note": note or "Reads ATTR_V3_COMPOSITE_HITS. See composites/.",
    }


def dedupe(overlays):
    best = {}
    for item in overlays:
        key = (item.get("atom_id") or item.get("composite_rule_id"), item["bucket"])
        prev = best.get(key)
        if prev is None or item["tier"] < prev["tier"]:
            best[key] = item
    return list(best.values())


def write_phenotype(path, phenotype, overlays, notes=None):
    doc = {
        "phenotype": phenotype,
        "_source": "architecture_v3_specs/11_phenotype_bucket_tiers_and_combinations.md (authoritative) + specialty_configs_v3/atoms/*.json source_workbook_rows. Guardrails/DO_NOT_USE/temporal-only signs excluded.",
        "_decisions": {
            "authority": "File 11 wins over older Signal Catalog where they conflict (WT18, WT20).",
            "cts_policy": "Bilateral/recurrent atoms are gate-forming; unilateral/generic CTS atoms are weaker / non-gate.",
        },
        "overlays": overlays,
    }
    if notes:
        doc["_notes"] = notes
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("Wrote %s (%d overlays)" % (path, len(overlays)))


def build_attrwt(m):
    o = []
    wt02 = set(m.get("WT02", []))
    for a in ["cts_bilateral", "cts_recurrent"]:
        if a in wt02:
            o.append(row(a, "WT02", "ORTHO", 1))
    for a in ["cts_left", "cts_right", "cts_any", "ctr_any"]:
        if a in wt02:
            o.append(row(a, "WT02", "ORTHO", 3, gate=False))
    o += expand(m, "WT03", "ORTHO", 1)
    o.append(composite("ORTHO_CLUSTER", "WT04", "ORTHO", 1, "Shape A composite - see composites/shape_a.json"))
    o += expand(m, "WT05", "ORTHO", 2)
    o += expand(m, "WT06", "ORTHO", 3)
    o += expand(m, "WT07", "ORTHO", 3)
    o += expand(m, "WT08", "ORTHO", 4)
    # CARDIO - file 11: WT20 CARDIO T1, WT18 CARDIO T2
    o += expand(m, "WT10", "CARDIO", 1)
    o += expand(m, "WT13", "CARDIO", 1)
    o += expand(m, "WT20", "CARDIO", 1)
    o += expand(m, "WT09", "CARDIO", 2)
    o += expand(m, "WT11", "CARDIO", 2)
    o += expand(m, "WT12", "CARDIO", 2)
    o += expand(m, "WT14", "CARDIO", 2)
    o += expand(m, "WT15", "CARDIO", 2)
    o += expand(m, "WT16", "CARDIO", 2)
    o += expand(m, "WT18", "CARDIO", 2)
    o += expand(m, "WT17", "CARDIO", 3)
    o += expand(m, "WT19", "CARDIO", 4)
    o += expand(m, "WT21", "NEURO", 3)
    o += expand(m, "WT22", "NEURO", 3)
    o += expand(m, "WT23", "SYSTEMIC_CONTEXT", 4, role="MODIFIER")
    return o, [
        "CTS T1 gate only for cts_bilateral and cts_recurrent; unilateral/generic are Tier 3 non-gate.",
        "WT18 = CARDIO Tier 2 per file 11.",
        "WT20 = CARDIO Tier 1 gate-eligible per file 11.",
        "WT01 temporal, WT24-29 guardrails, WT30 DO_NOT_USE excluded; WT04 composite included.",
    ]


def build_attrv(m):
    o = []
    o += expand(m, "V02", "NEURO", 1)
    o += expand(m, "V04", "NEURO", 1)
    o += expand(m, "V14", "NEURO", 1)
    o += expand(m, "V18", "NEURO", 2)
    o += expand(m, "V21", "NEURO", 2)
    o += expand(m, "V28", "NEURO", 2)
    o += expand(m, "V20", "NEURO", 3)
    o += expand(m, "V22", "NEURO", 3)
    o += expand(m, "V29", "NEURO", 3)
    o += expand(m, "V37", "NEURO", 3, role="MODIFIER")
    o += expand(m, "V05", "AUTONOMIC", 1)
    o += expand(m, "V09", "AUTONOMIC", 2)
    o += expand(m, "V10", "AUTONOMIC", 2)
    o += expand(m, "V11", "AUTONOMIC", 2)
    o += expand(m, "V19", "AUTONOMIC", 2)
    o += expand(m, "V12", "AUTONOMIC", 3)
    o += expand(m, "V26", "AUTONOMIC", 3)
    o += expand(m, "V27", "AUTONOMIC", 3)
    o += expand(m, "V31", "AUTONOMIC", 3)
    o += expand(m, "V01", "HEREDITARY", 1, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "V07", "HEREDITARY", 1, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "V08", "HEREDITARY", 2, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "V15", "OCULAR", 1)
    o += expand(m, "V16", "OCULAR", 1)
    o += expand(m, "V35", "OCULAR", 3)
    o += expand(m, "V24", "CARDIO", 2)
    o += expand(m, "V25", "CARDIO", 2)
    o += expand(m, "V23", "CARDIO", 3)
    v13 = set(m.get("V13", []))
    for a in ["cts_bilateral", "cts_recurrent", "cts_persistent_after_release"]:
        if a in v13:
            o.append(row(a, "V13", "ORTHO", 2))
    for a in ["cts_left", "cts_right", "cts_any", "ctr_any"]:
        if a in v13:
            o.append(row(a, "V13", "ORTHO", 4, gate=False))
    o += expand(m, "V30", "ORTHO", 4)
    o.append(composite(
        "NEURO_PLUS_SYSTEMIC", "V03", "NEURO", 1,
        "Shape B composite - upgrades ATTRv priority; see composites/shape_b_c.json"
    ))
    return o, [
        "V03 composite pseudo-entry only; V06 dropped (use V_RULE_04).",
        "V10/V11 AUTONOMIC only (no GI double-count).",
        "V13 bilateral/recurrent Tier 2 gate; unilateral Tier 4 non-gate.",
    ]


def build_al(m):
    o = []
    o += expand(m, "AL01", "HEME_CLONAL", 1, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AL02", "HEME_CLONAL", 2, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AL03", "RENAL", 1)
    o += expand(m, "AL04", "RENAL", 1)
    o += expand(m, "AL05", "RENAL", 2)
    o += expand(m, "AL06", "RENAL", 2)
    o += expand(m, "AL07", "MUCOSAL_CUTANEOUS", 1)
    o += expand(m, "AL08", "MUCOSAL_CUTANEOUS", 1)
    o += expand(m, "AL14", "CARDIO", 2)
    o += expand(m, "AL15", "CARDIO", 2)
    o += expand(m, "AL16", "CARDIO", 2)
    o += expand(m, "AL17", "CARDIO", 2)
    o += expand(m, "AL33", "CARDIO", 3)
    o += expand(m, "AL28", "CARDIO", 3)
    o += expand(m, "AL24", "NEURO", 2)
    o += expand(m, "AL13", "NEURO", 3)
    o += expand(m, "AL29", "NEURO", 3)
    o += expand(m, "AL10", "GI_HEPATIC", 3)
    o += expand(m, "AL11", "GI_HEPATIC", 3)
    o += expand(m, "AL18", "GI_HEPATIC", 3)
    o += expand(m, "AL09", "GI_HEPATIC", 3)
    o += expand(m, "AL19", "SYSTEMIC_CONTEXT", 4, role="MODIFIER")
    o += expand(m, "AL20", "SYSTEMIC_CONTEXT", 4, role="MODIFIER")
    o += expand(m, "AL34", "SYSTEMIC_CONTEXT", 4, role="MODIFIER")
    return o, [
        "AL21/AL26/AL27 are composites/escalations - not positive tier rows here.",
        "Guardrails AL22/23/25/30/31 excluded.",
    ]


def build_aa(m):
    o = []
    o += expand(m, "AA02", "INFLAMMATORY_DRIVER", 1, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AA06", "INFLAMMATORY_DRIVER", 1, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AA08", "INFLAMMATORY_DRIVER", 1, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AA01", "INFLAMMATORY_DRIVER", 2, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AA07", "INFLAMMATORY_DRIVER", 2, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AA09", "INFLAMMATORY_DRIVER", 2, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AA10", "INFLAMMATORY_DRIVER", 2, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AA13", "INFLAMMATORY_ACTIVITY", 1, role="MODIFIER")
    o += expand(m, "AA05", "INFLAMMATORY_ACTIVITY", 2, role="MODIFIER")
    o += expand(m, "AA14", "INFLAMMATORY_ACTIVITY", 2, role="MODIFIER")
    o += expand(m, "AA12", "INFLAMMATORY_ACTIVITY", 3, role="MODIFIER")
    o += expand(m, "AA16", "RENAL", 1)
    o += expand(m, "AA17", "RENAL", 1)
    o.append(composite(
        "RENAL_DISPROPORTIONATE", "AA21", "RENAL", 1,
        "May elevate RENAL to Tier 1; see composites/shape_b_c.json"
    ))
    o += expand(m, "AA15", "RENAL", 2)
    o += expand(m, "AA20", "RENAL", 2)
    o += expand(m, "AA18", "RENAL", 3)
    o += expand(m, "AA19", "RENAL", 3)
    o += expand(m, "AA03", "SUSCEPTIBILITY", 2, role="MODIFIER")
    o += expand(m, "AA04", "SUSCEPTIBILITY", 2, role="MODIFIER")
    o += expand(m, "AA22", "GI_HEPATIC", 3)
    o += expand(m, "AA23", "GI_HEPATIC", 4)
    o += expand(m, "AA11", "SYSTEMIC_CONTEXT", 4, role="MODIFIER")
    o += expand(m, "AA24", "SYSTEMIC_CONTEXT", 4, role="MODIFIER")
    return o, [
        "INFLAMMATORY_ACTIVITY and SUSCEPTIBILITY are MODIFIER only.",
        "AA21 composite pseudo-entry included for RENAL Tier 1 elevation.",
        "Guardrails AA25-30 excluded.",
    ]


def build_general(m):
    o = []
    o += expand(m, "WT10", "CARDIO", 1, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AL15", "CARDIO", 1, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "WT15", "CARDIO", 1, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "WT20", "CARDIO", 1, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "WT09", "CARDIO", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AL14", "CARDIO", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "WT12", "CARDIO", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "V25", "CARDIO", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "WT16", "CARDIO", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AL16", "CARDIO", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AL17", "CARDIO", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "WT11", "CARDIO", 3, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "WT14", "CARDIO", 3, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AL20", "CARDIO", 4, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AL28", "CARDIO", 4, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AL04", "RENAL", 1, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AA17", "RENAL", 1, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AL03", "RENAL", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AA16", "RENAL", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AL06", "RENAL", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AA20", "RENAL", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AA15", "RENAL", 3, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "V17", "RENAL", 3, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "V02", "NEURO", 1, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "V04", "NEURO", 1, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "V14", "NEURO", 1, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AL24", "NEURO", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "V05", "AUTONOMIC", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "V09", "AUTONOMIC", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "V10", "AUTONOMIC", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "V11", "AUTONOMIC", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o.append(composite("ORTHO_CLUSTER", "WT04", "ORTHO", 1, "GA ORTHO T1 = multi-ortho cluster"))
    for a in ["cts_bilateral", "cts_recurrent"]:
        if a in m.get("WT02", []):
            o.append(row(a, "WT02", "ORTHO", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE"))
        if a in m.get("V13", []):
            o.append(row(a, "V13", "ORTHO", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE"))
    o += expand(m, "WT03", "ORTHO", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "WT05", "ORTHO", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "WT06", "ORTHO", 3, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "WT07", "ORTHO", 3, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "WT08", "ORTHO", 3, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AL07", "MUCOSAL_CUTANEOUS", 1, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AL08", "MUCOSAL_CUTANEOUS", 1, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "V15", "OCULAR", 2, role="ORGAN_OR_PHENOTYPE_EVIDENCE")
    o += expand(m, "AL01", "HEME_CLONAL", 1, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AL02", "HEME_CLONAL", 2, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "V01", "HEREDITARY", 1, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "V07", "HEREDITARY", 1, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "V08", "HEREDITARY", 2, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AA02", "INFLAMMATORY_DRIVER", 1, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AA06", "INFLAMMATORY_DRIVER", 1, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AA08", "INFLAMMATORY_DRIVER", 1, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AA01", "INFLAMMATORY_DRIVER", 2, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AA07", "INFLAMMATORY_DRIVER", 2, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AA09", "INFLAMMATORY_DRIVER", 2, role="ETIOLOGIC_CONTEXT")
    o += expand(m, "AA10", "INFLAMMATORY_DRIVER", 2, role="ETIOLOGIC_CONTEXT")
    return dedupe(o), [
        "Apical sparing (WT15) is GENERAL_AMYLOID CARDIO Tier 1 (stronger than ATTRwt T2).",
        "ORTHO: WT04 cluster = T1; bilateral CTS/biceps/LSS = T2 for general amyloid.",
        "Etiologic buckets reuse AL/ATTRv/AA T1-T2 for GA02 pairing.",
    ]


def build_attr_common(m):
    o = []
    o.append(composite("ORTHO_CLUSTER", "WT04", "ORTHO", 1, "ATTR_COMMON ORTHO T1 cluster"))
    for a in ["cts_bilateral", "cts_recurrent"]:
        if a in m.get("WT02", []):
            o.append(row(a, "WT02", "ORTHO", 1, role="ATTR_COMMON_EVIDENCE"))
        if a in m.get("V13", []):
            o.append(row(a, "V13", "ORTHO", 2, role="ATTR_COMMON_EVIDENCE"))
    o += expand(m, "WT03", "ORTHO", 1, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "WT05", "ORTHO", 2, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "WT10", "CARDIO", 1, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "WT13", "CARDIO", 1, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "WT16", "CARDIO", 2, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "WT15", "CARDIO", 2, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "V25", "CARDIO", 2, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "V24", "CARDIO", 2, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "WT12", "CARDIO", 2, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "WT09", "CARDIO", 2, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "WT14", "CARDIO", 2, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "WT11", "CARDIO", 2, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "V14", "NEURO", 1, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "V04", "NEURO", 1, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "V02", "NEURO", 1, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "V28", "NEURO", 2, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "V05", "AUTONOMIC", 1, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "V11", "AUTONOMIC", 2, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "V10", "AUTONOMIC", 2, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "V09", "AUTONOMIC", 2, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "V01", "HEREDITARY", 1, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "V07", "HEREDITARY", 1, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "V08", "HEREDITARY", 2, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "V16", "OCULAR", 1, role="ATTR_COMMON_EVIDENCE")
    o += expand(m, "V15", "OCULAR", 1, role="ATTR_COMMON_EVIDENCE")
    return dedupe(o), [
        "Role ATTR_COMMON_EVIDENCE; only whitelist pairs in combinations/attr_common.json can pass.",
        "CTS unilateral atoms not given ATTR_COMMON gate tiers - bilateral/recurrent only.",
    ]


def main():
    m = load_sign_map()
    builders = [
        ("attrwt.json", "ATTRwt", build_attrwt),
        ("attrv.json", "ATTRv", build_attrv),
        ("al.json", "AL", build_al),
        ("aa.json", "AA", build_aa),
        ("general_amyloid.json", "GENERAL_AMYLOID", build_general),
        ("attr_common.json", "ATTR_COMMON", build_attr_common),
    ]
    for fname, phenotype, fn in builders:
        overlays, notes = fn(m)
        write_phenotype(os.path.join(OUT, fname), phenotype, overlays, notes=notes)


if __name__ == "__main__":
    main()

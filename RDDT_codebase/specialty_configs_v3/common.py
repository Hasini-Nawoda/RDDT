# -*- coding: utf-8 -*-
"""Shared config-loading + low-level SQL helpers for the ATTR pipeline modules.

No Snowflake-table-creating logic lives here — just: find the config root,
load one JSON file/section, and tiny SQL-escaping helpers used by every
pipeline-stage module. Split out of pipeline.py so each pipeline stage
(atoms/composites/buckets/temporal/combinations/guardrails/router) can import
only what it needs without a circular dependency on the orchestrator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set

# ---------------------------------------------------------------------------
# Paths / config load
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent


def find_v3_config_root() -> Path:
    """Config root is this package folder (specialty_configs_v3)."""
    candidates = [
        HERE,  # common.py lives in specialty_configs_v3/
        Path.cwd(),
        Path.cwd() / "specialty_configs_v3",
        Path("/tmp/specialty_configs_v3"),
        Path("/tmp") / "specialty_configs_v3",
    ]
    for p in candidates:
        if (p / "atoms").is_dir() and (p / "phenotype_overlays" / "attrwt.json").exists():
            return p
    raise FileNotFoundError(
        "specialty_configs_v3 not found. Searched:\n  "
        + "\n  ".join(str(c) for c in candidates)
    )


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _esc(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace("'", "''")


def _sql(session, statement: str):
    return session.sql(statement).collect()


def _count(session, table: str) -> int:
    return int(session.sql(f"SELECT COUNT(*) AS N FROM {table}").collect()[0][0])


# ---------------------------------------------------------------------------
# JSON config loaders (atoms / overlays / composites / combinations /
# temporal rules / guardrails)
# ---------------------------------------------------------------------------

def load_atoms_by_id(config_root: Path, atom_ids: Any) -> Dict[str, Dict[str, Any]]:
    wanted = set(atom_ids)
    found: Dict[str, Dict[str, Any]] = {}
    for path in (config_root / "atoms").glob("*.json"):
        data = _load_json(path)
        for atom in data.get("atoms") or []:
            aid = atom.get("atom_id")
            if aid in wanted:
                found[aid] = atom
    missing = wanted - set(found)
    if missing:
        raise KeyError(f"Atoms not found in specialty_configs_v3/atoms: {sorted(missing)}")
    return found


def load_attrwt_overlays(config_root: Path) -> List[Dict[str, Any]]:
    data = _load_json(config_root / "phenotype_overlays" / "attrwt.json")
    return list(data.get("overlays") or [])


def load_ortho_cluster(config_root: Path) -> Dict[str, Any]:
    data = _load_json(config_root / "composites" / "shape_a.json")
    for c in data.get("composites") or []:
        if c.get("derived_rule_id") == "ORTHO_CLUSTER" or c.get("composite_rule_id") == "ORTHO_CLUSTER":
            return c
    raise KeyError("ORTHO_CLUSTER not found in composites/shape_a.json")


def load_neuro_plus_systemic_composite(config_root: Path) -> Dict[str, Any]:
    data = _load_json(config_root / "composites" / "shape_b_c.json")
    for c in data.get("composites") or []:
        if c.get("derived_rule_id") == "NEURO_PLUS_SYSTEMIC":
            return c
    raise KeyError("NEURO_PLUS_SYSTEMIC not found in composites/shape_b_c.json")


def load_renal_disproportionate_composite(config_root: Path) -> Dict[str, Any]:
    data = _load_json(config_root / "composites" / "shape_b_c.json")
    for c in data.get("composites") or []:
        if c.get("derived_rule_id") == "RENAL_DISPROPORTIONATE":
            return c
    raise KeyError("RENAL_DISPROPORTIONATE not found in composites/shape_b_c.json")


def load_overlay_file(config_root: Path, filename: str) -> List[Dict[str, Any]]:
    data = _load_json(config_root / "phenotype_overlays" / filename)
    return list(data.get("overlays") or [])


def load_combination_file(config_root: Path, filename: str) -> List[Dict[str, Any]]:
    data = _load_json(config_root / "combinations" / filename)
    return list(data.get("combinations") or [])


def load_temporal_rule(config_root: Path, temporal_rule_id: str) -> Dict[str, Any]:
    data = _load_json(config_root / "temporal_rules" / "longitudinal_patterns.json")
    for r in data.get("rules") or []:
        if r.get("temporal_rule_id") == temporal_rule_id:
            return r
    raise KeyError(f"{temporal_rule_id} not found in temporal_rules/longitudinal_patterns.json")


def load_guardrails(config_root: Path) -> List[Dict[str, Any]]:
    data = _load_json(config_root / "guardrails" / "differential_routes.json")
    return list(data.get("guardrails") or [])


# Phenotype -> its own overlay file. Each phenotype MUST read its own tiers -
# the same atom can (and does) carry a different tier per phenotype (e.g.
# apical_sparing is GENERAL_AMYLOID Tier 1 but ATTRwt Tier 2). Reusing one
# phenotype's tier map for another was the bug in the previous version of
# this function.
PHENOTYPE_OVERLAY_FILES = {
    "GENERAL_AMYLOID": "general_amyloid.json",
    "ATTR_COMMON": "attr_common.json",
    "ATTRwt": "attrwt.json",
    "ATTRv": "attrv.json",
    "AL": "al.json",
    "AA": "aa.json",
}

WT01_GATE_BUCKETS = ("ORTHO", "CARDIO")

# Buckets ATTRv's own overlays + combination rules (V_RULE_01-07) reference.
# ORTHO/CARDIO included since V13 (ORTHO) and V24/V25/V23 (CARDIO) atoms are
# ATTRv overlay rows too, and V_RULE_04/05 pair against CARDIO.
ATTRV_BUCKETS = ("NEURO", "AUTONOMIC", "HEREDITARY", "OCULAR", "CARDIO", "ORTHO", "RENAL")

# Buckets AL's own overlay + combination rules (AL_RULE_01-07) reference.
# HEME_CLONAL is AL's etiology bucket - extracting it also lets GA02
# (GENERAL_AMYLOID's own ORG_PLUS_ETIOLOGY rule, already running whenever
# phase3_wt01_only=False) use HEME_CLONAL as an etiology option for the first
# time - previously only HEREDITARY atoms (from ATTRv) were ever extracted for
# GA02's etiology side.
AL_BUCKETS = ("HEME_CLONAL", "RENAL", "CARDIO", "NEURO", "GI_HEPATIC", "MUCOSAL_CUTANEOUS")

# Buckets AA's own overlay + combination rules (AA_RULE_01/02) reference.
# INFLAMMATORY_DRIVER is AA's etiology bucket - extracting it also lets GA02
# use INFLAMMATORY_DRIVER as an etiology option for the first time (general_
# amyloid.json's own overlay already tags these same atoms INFLAMMATORY_DRIVER
# for phenotype=GENERAL_AMYLOID; they just were never extracted/rolled up
# because INFLAMMATORY_DRIVER was never in any buckets_only set before AA).
# INFLAMMATORY_ACTIVITY and SUSCEPTIBILITY are MODIFIER-only per aa.json's own
# _notes (never gate_eligible), but still need their bucket-tier rows built -
# AA_RULE_01/02's modifier check reads ATTR_V3_BUCKET_TIER for INFLAMMATORY_ACTIVITY.
AA_BUCKETS = (
    "INFLAMMATORY_DRIVER", "INFLAMMATORY_ACTIVITY", "RENAL",
    "SUSCEPTIBILITY", "GI_HEPATIC", "SYSTEMIC_CONTEXT",
)


# ---------------------------------------------------------------------------
# Keyword ILIKE pattern helper (used by atoms._kw_pred and by
# pipeline.build_wt01_vocab_frames for the display/inspection vocab)
# ---------------------------------------------------------------------------

def keyword_wildcard_variations(value: str, mode: str = "PHRASE") -> List[str]:
    """Build ILIKE patterns for one keyword value (wildcards + light variations).

    Examples for 'bilateral CTS':
      %bilateral CTS%
      %bilateral%CTS%          (flexible gap)
      %bilateral-CTS%          (hyphen variation)
    """
    v = " ".join(str(value).split())
    if not v:
        return []
    patterns: List[str] = []
    seen: Set[str] = set()

    def add(p: str) -> None:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            patterns.append(p)

    # core substring
    add(f"%{v}%")
    # hyphen <-> space
    if " " in v:
        add(f"%{v.replace(' ', '-')}%")
        add(f"%{v.replace(' ', '')}%")  # collapsed
        # allow other tokens between words: bilateral%CTS
        parts = v.split()
        if len(parts) >= 2:
            add("%" + "%".join(parts) + "%")
    if "-" in v:
        add(f"%{v.replace('-', ' ')}%")
        add(f"%{v.replace('-', '')}%")
    # slash variants (b/l CTS)
    if "/" in v:
        add(f"%{v.replace('/', '')}%")
        add(f"%{v.replace('/', ' ')}%")

    if mode.upper() == "TOKEN":
        # single-token style — already covered by %v%
        pass

    return patterns

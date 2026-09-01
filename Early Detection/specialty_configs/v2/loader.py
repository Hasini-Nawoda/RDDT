"""
specialty_configs.loader
------------------------
Reads the atoms/buckets/features JSON files in this folder and reconstructs
them as plain Python objects, with validation.

This is the ONLY place that touches the filesystem. Nothing else in
specialty_configs/ should open a JSON file directly - import from here.

Editing a signal (new keyword, new ICD prefix, new feature) means editing
one of the JSON files under atoms/ or features/. No Python change needed
for that. This loader only needs a Python change if a genuinely new kind
of logic operator is introduced (see sql_generator.py OPS).
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ATOMS_DIR = os.path.join(_HERE, "atoms")
_BUCKETS_DIR = os.path.join(_HERE, "buckets")
_FEATURES_DIR = os.path.join(_HERE, "features")

# any - at least one is true (OR)
# all - all must be true (AND)
# not - the opposite of the child (True when those atoms are not present - Used to exclude something)
# count_buckets_gate - at least this many buckets must be true
# count_atoms_gate - at least this many atoms must be true
VALID_OPS = {"any", "all", "not", "count_buckets_gate", "count_atoms_gate"}


CODE_SYSTEMS = ("icd10", "icd9", "snomed", "cpt", "hcpcs")

# best - the best match (the most specific match)
# related - a related match (a match that is not the best match)
# differential - a differential match (a match that is not the best or related match)
MATCH_ROLES = ("best", "related", "differential")


@dataclass
class CodeEntry:
    code: str
    description: str = ""
    match_role: str = "related"

    @property
    def is_active(self) -> bool:
        """Active = counts as positive evidence. 'differential' never does."""
        return self.match_role in ("best", "related")


@dataclass
class Atom:
    atom_id: str
    specialty: str
    family_tables_only: bool = False

    # EHR-facing fields (all optional)
    preferred_name: str = ""
    clinical_names: List[str] = field(default_factory=list)
    abbreviations: List[str] = field(default_factory=list)
    keywords_canonical: List[str] = field(default_factory=list)
    keywords_fuzzy: List[str] = field(default_factory=list)
    codes: Dict[str, List[CodeEntry]] = field(default_factory=lambda: {s: [] for s in CODE_SYSTEMS})
    notes: str = ""

    # --- computed views used by sql_generator.py -

    @property
    def icd10_prefixes(self) -> List[str]:
        return [c.code for c in self.codes.get("icd10", []) if c.is_active]

    @property
    def icd9_prefixes(self) -> List[str]:
        return [c.code for c in self.codes.get("icd9", []) if c.is_active]

    @property
    def cpt_exact(self) -> List[str]:
        return [c.code for c in self.codes.get("cpt", []) if c.is_active]

    @property
    def hcpcs_exact(self) -> List[str]:
        return [c.code for c in self.codes.get("hcpcs", []) if c.is_active]

    @property
    def snomed_exact(self) -> List[str]:
        """Active SNOMED concept IDs (best/related). Digits only, for exact match."""
        out, seen = [], set()
        for c in self.codes.get("snomed", []):
            if not c.is_active:
                continue
            digits = "".join(ch for ch in str(c.code) if ch.isdigit())
            if digits and digits not in seen:
                seen.add(digits)
                out.append(digits)
        return out

    @property
    def keywords(self) -> List[str]:
        # canonical + fuzzy, deduped, case-insensitive
        seen, out = set(), []
        for k in [*self.keywords_canonical, *self.keywords_fuzzy]:
            kl = k.lower()
            if kl not in seen:
                seen.add(kl)
                out.append(k)
        return out

    def has_code_rule(self) -> bool:
        """Claim-side structured codes (ICD-10 / ICD-9 / CPT / HCPCS)."""
        return bool(self.icd10_prefixes or self.icd9_prefixes or self.cpt_exact or self.hcpcs_exact)

    def has_snomed_rule(self) -> bool:
        return bool(self.snomed_exact)

    def has_keyword_rule(self) -> bool:
        return bool(self.keywords)


@dataclass
class Feature:
    feature_id: str
    specialty: str
    tier: int
    shortlist_eligible: bool
    short_name: str
    logic: Dict[str, Any]


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_code_entries(raw_list: Any, fname: str, atom_id: str, system: str) -> List[CodeEntry]:
    """Each entry is {code, description, match_role}; match_role defaults to 'related'."""
    out: List[CodeEntry] = []
    for item in raw_list or []:
        if not isinstance(item, dict):
            raise ValueError(f"Atom '{atom_id}' ({fname}): unrecognized code entry {item!r} in '{system}'")
        role = item.get("match_role", "related")
        if role not in MATCH_ROLES:
            raise ValueError(
                f"Atom '{atom_id}' ({fname}): code '{item.get('code')}' in '{system}' "
                f"has invalid match_role '{role}' (valid: {MATCH_ROLES})"
            )
        out.append(CodeEntry(code=item["code"], description=item.get("description", ""), match_role=role))
    return out


def _parse_keyword_bucket(raw_list: Any, fname: str, atom_id: str, bucket: str) -> List[str]:
    out: List[str] = []
    for item in raw_list or []:
        if isinstance(item, str):
            out.append(item)
        else:
            raise ValueError(
                f"Atom '{atom_id}' ({fname}): keyword entries in '{bucket}' must be plain strings, "
                f"got {item!r}"
            )
    return out


def _parse_keywords(raw: Any, fname: str, atom_id: str) -> Dict[str, List[str]]:
    """{"canonical": [...], "fuzzy_variants": [...]}; either bucket may be omitted."""
    if raw is None:
        return {"canonical": [], "fuzzy": []}
    if not isinstance(raw, dict):
        raise ValueError(f"Atom '{atom_id}' ({fname}): unrecognized 'keywords' shape {type(raw)}")
    return {
        "canonical": _parse_keyword_bucket(raw.get("canonical"), fname, atom_id, "canonical"),
        "fuzzy": _parse_keyword_bucket(raw.get("fuzzy_variants"), fname, atom_id, "fuzzy_variants"),
    }


def _parse_atom(a: Dict[str, Any], specialty: str, fname: str) -> "Atom":
    atom_id = a["atom_id"]
    kw = _parse_keywords(a.get("keywords"), fname, atom_id)
    codes_raw = a.get("codes") or {}
    codes = {s: _parse_code_entries(codes_raw.get(s), fname, atom_id, s) for s in CODE_SYSTEMS}
    return Atom(
        atom_id=atom_id,
        specialty=specialty,
        family_tables_only=bool(a.get("family_tables_only", False)),
        preferred_name=a.get("preferred_name", ""),
        clinical_names=list(a.get("clinical_names") or []),
        abbreviations=list(a.get("abbreviations") or []),
        keywords_canonical=kw["canonical"],
        keywords_fuzzy=kw["fuzzy"],
        codes=codes,
        notes=a.get("notes", ""),
    )


def _validate_logic_tree(node: Dict[str, Any], feature_id: str, known_atoms: set, known_buckets: Dict[str, Dict[str, List[str]]]) -> None:
    op = node.get("op")
    if op not in VALID_OPS:
        raise ValueError(f"Feature '{feature_id}': unknown logic op '{op}' (valid: {sorted(VALID_OPS)})")

    if op in ("any", "all", "not"):
        atoms = node.get("atoms") or []
        children = node.get("children") or []
        if not atoms and not children:
            raise ValueError(f"Feature '{feature_id}': op '{op}' has neither 'atoms' nor 'children'")
        for a in atoms:
            if a not in known_atoms:
                raise ValueError(f"Feature '{feature_id}': references unknown atom '{a}'")
        for c in children:
            _validate_logic_tree(c, feature_id, known_atoms, known_buckets)

    elif op == "count_atoms_gate":
        atoms = node.get("atoms") or []
        if not atoms:
            raise ValueError(f"Feature '{feature_id}': count_atoms_gate has no atoms")
        if "threshold" not in node:
            raise ValueError(f"Feature '{feature_id}': count_atoms_gate missing 'threshold'")
        for a in atoms:
            if a not in known_atoms:
                raise ValueError(f"Feature '{feature_id}': references unknown atom '{a}'")

    elif op == "count_buckets_gate":
        bucket_set = node.get("bucket_set")
        if bucket_set not in known_buckets:
            raise ValueError(f"Feature '{feature_id}': unknown bucket_set '{bucket_set}'")
        if "threshold" not in node:
            raise ValueError(f"Feature '{feature_id}': count_buckets_gate missing 'threshold'")
        for bucket_name, atom_list in known_buckets[bucket_set].items():
            for a in atom_list:
                if a not in known_atoms:
                    raise ValueError(
                        f"Bucket '{bucket_set}.{bucket_name}' (used by feature '{feature_id}') "
                        f"references unknown atom '{a}'"
                    )


class SpecialtyConfig:
    """Loaded + validated view of every atoms/buckets/features JSON file."""

    def __init__(self) -> None:
        self.atoms: Dict[str, Atom] = {}
        self.buckets: Dict[str, Dict[str, List[str]]] = {}
        self.features: List[Feature] = []
        self._load()

    def _load(self) -> None:
        # --- atoms ---
        for fname in sorted(os.listdir(_ATOMS_DIR)):
            if not fname.endswith(".json"):
                continue
            payload = _read_json(os.path.join(_ATOMS_DIR, fname))
            specialty = payload["specialty"]
            for a in payload["atoms"]:
                atom_id = a["atom_id"]
                if atom_id in self.atoms:
                    raise ValueError(f"Duplicate atom_id '{atom_id}' (in {fname}, already defined elsewhere)")
                self.atoms[atom_id] = _parse_atom(a, specialty, fname)

        # --- buckets ---
        if os.path.isdir(_BUCKETS_DIR):
            for fname in sorted(os.listdir(_BUCKETS_DIR)):
                if not fname.endswith(".json"):
                    continue
                payload = _read_json(os.path.join(_BUCKETS_DIR, fname))
                for bucket_set_name, bucket_map in payload.items():
                    if bucket_set_name in self.buckets:
                        raise ValueError(f"Duplicate bucket_set '{bucket_set_name}' (in {fname})")
                    self.buckets[bucket_set_name] = {k: list(v) for k, v in bucket_map.items()}

        # --- features (validated against atoms + buckets loaded above) ---
        known_atoms = set(self.atoms.keys())
        seen_ids = set()
        for fname in sorted(os.listdir(_FEATURES_DIR)):
            if not fname.endswith(".json"):
                continue
            payload = _read_json(os.path.join(_FEATURES_DIR, fname))
            for f in payload["features"]:
                fid = f["feature_id"]
                if fid in seen_ids:
                    raise ValueError(f"Duplicate feature_id '{fid}' (in {fname})")
                seen_ids.add(fid)
                _validate_logic_tree(f["logic"], fid, known_atoms, self.buckets)
                self.features.append(Feature(
                    feature_id=fid,
                    specialty=f["specialty"],
                    tier=int(f["tier"]),
                    shortlist_eligible=bool(f.get("shortlist_eligible", False)),
                    short_name=f.get("short_name", ""),
                    logic=f["logic"],
                ))

    def atoms_for_specialty(self, specialty: str) -> List[Atom]:
        return [a for a in self.atoms.values() if a.specialty == specialty]

    def features_for_specialty(self, specialty: str) -> List[Feature]:
        return [f for f in self.features if f.specialty == specialty]

    def all_active_snomed_codes(self) -> List[str]:
        """Deduped best/related SNOMED IDs across every atom (for Step 2 nets)."""
        seen, out = set(), []
        for atom in self.atoms.values():
            for code in atom.snomed_exact:
                if code not in seen:
                    seen.add(code)
                    out.append(code)
        return out


def load_shortlist_config() -> Dict[str, Any]:
    return _read_json(os.path.join(_HERE, "shortlist_config.json"))


def load_config() -> SpecialtyConfig:
    """Load + validate everything. Raises on the first inconsistency found."""
    return SpecialtyConfig()


if __name__ == "__main__":
    cfg = load_config()
    print(f"Loaded {len(cfg.atoms)} atoms, {len(cfg.features)} features, {len(cfg.buckets)} bucket sets.")
    for sp in ("ortho", "cardio", "neuro"):
        print(f"  {sp}: {len(cfg.atoms_for_specialty(sp))} atoms, {len(cfg.features_for_specialty(sp))} features")
    print("All atom references in all features/buckets are valid.")

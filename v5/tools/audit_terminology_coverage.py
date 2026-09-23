#!/usr/bin/env python3
"""Audit V5 ICD-10-CM and SNOMED mappings against supplied vocabularies.

This script is deliberately conservative. It produces review queues; it does
not modify clinical configuration or declare a code clinically valid from
text similarity alone.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Iterable


STOP_WORDS = {
    "a",
    "an",
    "and",
    "associated",
    "at",
    "by",
    "clinical",
    "condition",
    "disease",
    "disorder",
    "due",
    "elsewhere",
    "evidence",
    "finding",
    "for",
    "from",
    "history",
    "in",
    "including",
    "manifestation",
    "not",
    "of",
    "on",
    "or",
    "other",
    "patient",
    "presence",
    "related",
    "signal",
    "specified",
    "syndrome",
    "the",
    "to",
    "unspecified",
    "with",
    "without",
}

ALTERNATIVE_CAUSE_TERMS = {
    "alcoholic",
    "congenital",
    "diabetic",
    "drug induced",
    "hereditary motor",
    "hypertensive",
    "infectious",
    "neonatal",
    "obstetric",
    "pregnancy",
    "rheumatoid",
    "traumatic",
    "tuberculosis",
    "viral",
}


def clean_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_code(value: object) -> str:
    return clean_text(value).upper()


def compact_code(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", normalize_code(value))


def icd_category(value: object) -> str:
    compact = compact_code(value)
    return compact[:3] if len(compact) >= 3 else compact


def normalize_text(value: object) -> str:
    text = clean_text(value).lower().replace("/", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def stem_token(token: str) -> str:
    if len(token) > 7 and token.endswith("opathies"):
        return token[:-3]
    if len(token) > 6 and token.endswith("ies"):
        return token[:-3] + "y"
    for suffix in ("ations", "ation", "ments", "ment", "ing", "ed"):
        if len(token) > len(suffix) + 4 and token.endswith(suffix):
            return token[: -len(suffix)]
    if len(token) > 5 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def semantic_tokens(value: object) -> set[str]:
    return {
        stem_token(token)
        for token in normalize_text(value).split()
        if len(token) >= 3 and token not in STOP_WORDS
    }


def parse_int(value: object) -> int:
    try:
        return int(float(clean_text(value)))
    except ValueError:
        return 0


def parse_bool(value: object) -> bool | None:
    text = clean_text(value).lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def join_values(values: Iterable[object]) -> str:
    return " | ".join(sorted({clean_text(value) for value in values if clean_text(value)}))


@dataclass(frozen=True)
class VocabularyEntry:
    code: str
    meaning: str
    row_count: int = 0
    patient_count: int = 0
    source: str = ""
    matched_code: str = ""
    exact_match: bool | None = None


@dataclass
class AtomInfo:
    atom_id: str
    preferred_name: str
    clinical_meaning: str
    context_guard: str
    specialty: str
    source_file: str
    phenotypes: tuple[str, ...]
    nlp_terms: tuple[str, ...]

    @cached_property
    def semantic_text(self) -> str:
        return " ".join(
            [self.preferred_name, self.clinical_meaning, *self.nlp_terms]
        )

    @cached_property
    def tokens(self) -> set[str]:
        return semantic_tokens(self.semantic_text)

    @cached_property
    def phrases(self) -> tuple[str, ...]:
        phrases = []
        for phrase in (self.preferred_name, self.clinical_meaning, *self.nlp_terms):
            phrase_norm = normalize_text(phrase)
            if len(semantic_tokens(phrase_norm)) >= 2:
                phrases.append(phrase_norm)
        return tuple(sorted(set(phrases)))


def load_vocabulary(path: Path, code_column: str) -> dict[str, VocabularyEntry]:
    result: dict[str, VocabularyEntry] = {}
    for row in read_csv(path):
        code = normalize_code(row.get(code_column))
        if not code:
            continue
        result[code] = VocabularyEntry(
            code=code,
            meaning=clean_text(row.get("MEANING")),
            row_count=parse_int(row.get("ROW_COUNT")),
            patient_count=parse_int(row.get("PATIENT_COUNT")),
            source=clean_text(row.get("MEANING_SOURCE")),
            matched_code=normalize_code(row.get("MATCHED_CODE")),
            exact_match=parse_bool(row.get("EXACT_MATCH")),
        )
    return result


def phenotype_atom_usage(config_dir: Path) -> dict[str, set[str]]:
    usage: dict[str, set[str]] = defaultdict(set)
    for path in sorted((config_dir / "phenotypes").glob("*/signal_atoms.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        phenotype = clean_text(data.get("phenotype")) or path.parent.name
        for row in data.get("signal_atoms", []):
            atom_id = clean_text(row.get("atom_id"))
            if atom_id:
                usage[atom_id].add(phenotype)
    return usage


def load_atoms(config_dir: Path) -> tuple[dict[str, AtomInfo], list[dict[str, object]]]:
    usage = phenotype_atom_usage(config_dir)
    atoms: dict[str, AtomInfo] = {}
    mappings: list[dict[str, object]] = []

    for path in sorted((config_dir / "shared" / "atoms").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        file_specialty = clean_text(data.get("source_specialty")) or path.stem
        for atom in data.get("atoms", []):
            atom_id = clean_text(atom.get("atom_id"))
            terms = tuple(
                clean_text(term.get("value"))
                for term in atom.get("extraction", {}).get("nlp_terms", [])
                if clean_text(term.get("value"))
            )
            info = AtomInfo(
                atom_id=atom_id,
                preferred_name=clean_text(atom.get("preferred_name")),
                clinical_meaning=clean_text(atom.get("clinical_meaning")),
                context_guard=clean_text(atom.get("context_guard")),
                specialty=clean_text(atom.get("source_specialty")) or file_specialty,
                source_file=path.as_posix(),
                phenotypes=tuple(sorted(usage.get(atom_id, set()))),
                nlp_terms=terms,
            )
            atoms[atom_id] = info
            codes = atom.get("extraction", {}).get("codes", {})
            for system in ("ICD10", "SNOMED_CT"):
                for mapping in codes.get(system, []):
                    mappings.append(
                        {
                            "source_kind": "ATOM",
                            "source_file": path.as_posix(),
                            "specialty": info.specialty,
                            "phenotypes": join_values(info.phenotypes),
                            "atom_id": atom_id,
                            "atom_name": info.preferred_name,
                            "atom_semantic_text": info.semantic_text,
                            "context_guard": clean_text(mapping.get("context_guard"))
                            or info.context_guard,
                            "system": system,
                            "code": normalize_code(mapping.get("value")),
                            "mapping_role": clean_text(mapping.get("mapping_role")),
                            "can_fire_atom_alone": mapping.get("can_fire_atom_alone"),
                            "review_status": clean_text(mapping.get("review_status")),
                            "match_mode": clean_text(mapping.get("match_mode")),
                        }
                    )
    return atoms, mappings


def load_confirmed_mappings(config_dir: Path) -> list[dict[str, object]]:
    path = config_dir / "shared" / "confirmed_patients.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    mappings: list[dict[str, object]] = []
    for route_name, route in data.get("routes", {}).items():
        atom_names = {
            clean_text(atom.get("atom_id")): clean_text(atom.get("preferred_name"))
            for atom in route.get("atoms", [])
        }
        guards = {
            clean_text(atom.get("atom_id")): clean_text(atom.get("context_guard"))
            for atom in route.get("atoms", [])
        }
        for item in route.get("terminology", []):
            system = clean_text(item.get("terminology_system"))
            if system not in {"ICD10", "SNOMED_CT"}:
                continue
            atom_id = clean_text(item.get("atom_id"))
            mappings.append(
                {
                    "source_kind": f"CONFIRMED_{route_name}",
                    "source_file": path.as_posix(),
                    "specialty": "CONFIRMED_PRE_SCREEN",
                    "phenotypes": route_name,
                    "atom_id": atom_id,
                    "atom_name": atom_names.get(atom_id, ""),
                    "atom_semantic_text": " ".join(
                        [
                            atom_names.get(atom_id, ""),
                            clean_text(item.get("subtype_label")),
                            clean_text(item.get("amyloidosis_type")),
                        ]
                    ),
                    "context_guard": guards.get(atom_id, ""),
                    "system": system,
                    "code": normalize_code(item.get("value")),
                    "mapping_role": "CONFIRMED_PRE_SCREEN",
                    "can_fire_atom_alone": item.get("can_fire_atom_alone"),
                    "review_status": clean_text(item.get("review_status")),
                    "match_mode": "EXACT",
                }
            )
    return mappings


def load_prefix_fallbacks(
    config_dir: Path, atoms: dict[str, AtomInfo]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted((config_dir / "shared" / "atoms").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for atom in data.get("atoms", []):
            atom_id = clean_text(atom.get("atom_id"))
            info = atoms[atom_id]
            for fallback in atom.get("extraction", {}).get("code_prefix_fallbacks", []):
                rows.append(
                    {
                        "source_file": path.as_posix(),
                        "specialty": info.specialty,
                        "phenotypes": join_values(info.phenotypes),
                        "atom_id": atom_id,
                        "atom_name": info.preferred_name,
                        "atom_semantic_text": info.semantic_text,
                        "system": clean_text(fallback.get("terminology_system")),
                        "prefix": normalize_code(fallback.get("prefix")),
                        "mapping_role": clean_text(fallback.get("mapping_role")),
                        "can_fire_atom_alone": fallback.get("can_fire_atom_alone"),
                        "review_status": clean_text(fallback.get("review_status")),
                        "context_guard": clean_text(fallback.get("context_guard"))
                        or info.context_guard,
                    }
                )
    return rows


def prefix_fallback_audit(
    fallbacks: list[dict[str, object]], icd: dict[str, VocabularyEntry]
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for fallback in fallbacks:
        prefix = compact_code(fallback["prefix"])
        matches = [
            entry
            for code, entry in icd.items()
            if compact_code(code).startswith(prefix)
        ]
        zero: list[VocabularyEntry] = []
        low: list[VocabularyEntry] = []
        for entry in matches:
            score, _ = lexical_alignment(
                entry.meaning, clean_text(fallback["atom_semantic_text"])
            )
            if score == 0:
                zero.append(entry)
            if score < 0.20:
                low.append(entry)
        row = dict(fallback)
        row.update(
            warehouse_matched_code_count=len(matches),
            warehouse_matched_patient_count_sum=sum(
                entry.patient_count for entry in matches
            ),
            zero_alignment_code_count=len(zero),
            low_alignment_code_count=len(low),
            matched_code_examples=join_values(
                f"{entry.code}={entry.meaning}" for entry in matches[:25]
            ),
            zero_alignment_examples=join_values(
                f"{entry.code}={entry.meaning}" for entry in zero[:25]
            ),
            audit_flag=(
                "HIGH_RISK_BROAD_PREFIX"
                if fallback.get("can_fire_atom_alone") is True and low
                else "REVIEW_PREFIX"
            ),
        )
        result.append(row)
    return result


def vocabulary_for_system(
    system: str,
    icd: dict[str, VocabularyEntry],
    snomed: dict[str, VocabularyEntry],
) -> dict[str, VocabularyEntry]:
    return icd if system == "ICD10" else snomed


def lexical_alignment(meaning: str, semantic_text: str) -> tuple[float, str]:
    meaning_tokens = semantic_tokens(meaning)
    atom_tokens = semantic_tokens(semantic_text)
    overlap = meaning_tokens & atom_tokens
    denominator = min(max(len(meaning_tokens), 1), max(len(atom_tokens), 1))
    return len(overlap) / denominator, ", ".join(sorted(overlap))


def mapping_audit(
    mappings: list[dict[str, object]],
    icd: dict[str, VocabularyEntry],
    snomed: dict[str, VocabularyEntry],
) -> list[dict[str, object]]:
    reuse: Counter[tuple[str, str]] = Counter(
        (clean_text(row["system"]), normalize_code(row["code"]))
        for row in mappings
        if normalize_code(row["code"])
    )
    rows: list[dict[str, object]] = []
    for mapping in mappings:
        system = clean_text(mapping["system"])
        code = normalize_code(mapping["code"])
        vocab = vocabulary_for_system(system, icd, snomed)
        entry = vocab.get(code)
        score, overlap = lexical_alignment(
            entry.meaning if entry else "", clean_text(mapping["atom_semantic_text"])
        )
        flags: list[str] = []
        if not entry:
            flags.append("NOT_IN_WAREHOUSE_VOCABULARY")
        elif entry.exact_match is False:
            flags.append("WAREHOUSE_MEANING_FROM_PARENT_CODE")
        if reuse[(system, code)] > 1:
            flags.append("CODE_REUSED_IN_CONFIG")
        if entry and score == 0:
            flags.append("ZERO_LEXICAL_ALIGNMENT_REVIEW")
        elif entry and score < 0.20:
            flags.append("LOW_LEXICAL_ALIGNMENT_REVIEW")
        if mapping.get("can_fire_atom_alone") is True:
            flags.append("CAN_FIRE_ALONE")
        if clean_text(mapping.get("mapping_role")) == "DIRECT_TARGET":
            flags.append("DIRECT_TARGET")
        row = dict(mapping)
        row.update(
            warehouse_meaning=entry.meaning if entry else "",
            warehouse_row_count=entry.row_count if entry else 0,
            warehouse_patient_count=entry.patient_count if entry else 0,
            warehouse_meaning_source=entry.source if entry else "",
            warehouse_exact_meaning=entry.exact_match if entry else "",
            lexical_alignment=round(score, 3),
            lexical_overlap_tokens=overlap,
            config_reuse_count=reuse[(system, code)],
            audit_flags=" | ".join(flags),
        )
        rows.append(row)
    return rows


def reuse_audit(
    audited_mappings: list[dict[str, object]],
) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in audited_mappings:
        groups[(clean_text(row["system"]), normalize_code(row["code"]))].append(row)
    result: list[dict[str, object]] = []
    for (system, code), rows in groups.items():
        atom_ids = {clean_text(row["atom_id"]) for row in rows}
        if len(atom_ids) <= 1:
            continue
        direct_atoms = {
            clean_text(row["atom_id"])
            for row in rows
            if row.get("can_fire_atom_alone") is True
            or clean_text(row.get("mapping_role")) == "DIRECT_TARGET"
        }
        result.append(
            {
                "system": system,
                "code": code,
                "warehouse_meaning": clean_text(rows[0].get("warehouse_meaning")),
                "warehouse_row_count": rows[0].get("warehouse_row_count", 0),
                "warehouse_patient_count": rows[0].get("warehouse_patient_count", 0),
                "atom_count": len(atom_ids),
                "direct_atom_count": len(direct_atoms),
                "atom_ids": join_values(atom_ids),
                "atom_names": join_values(row.get("atom_name") for row in rows),
                "phenotypes": join_values(row.get("phenotypes") for row in rows),
                "mapping_roles": join_values(row.get("mapping_role") for row in rows),
                "audit_flag": (
                    "CONFLICTING_DIRECT_REUSE" if len(direct_atoms) > 1 else "REUSED_SUPPORT_CODE"
                ),
            }
        )
    return sorted(
        result,
        key=lambda row: (
            row["audit_flag"] != "CONFLICTING_DIRECT_REUSE",
            -int(row["warehouse_patient_count"] or 0),
            row["system"],
            row["code"],
        ),
    )


def atom_mapping_summary(
    audited_mappings: list[dict[str, object]],
) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in audited_mappings:
        if row["source_kind"] != "ATOM":
            continue
        groups[(clean_text(row["system"]), clean_text(row["atom_id"]))].append(row)

    result: list[dict[str, object]] = []
    for (system, atom_id), rows in groups.items():
        known = [row for row in rows if clean_text(row.get("warehouse_meaning"))]
        zero = [row for row in known if float(row.get("lexical_alignment") or 0) == 0]
        low = [row for row in known if float(row.get("lexical_alignment") or 0) < 0.20]
        absent = [row for row in rows if not clean_text(row.get("warehouse_meaning"))]
        reused = [row for row in rows if int(row.get("config_reuse_count") or 0) > 1]
        result.append(
            {
                "system": system,
                "specialty": clean_text(rows[0].get("specialty")),
                "phenotypes": clean_text(rows[0].get("phenotypes")),
                "atom_id": atom_id,
                "atom_name": clean_text(rows[0].get("atom_name")),
                "configured_mapping_rows": len(rows),
                "warehouse_present_rows": len(known),
                "warehouse_absent_rows": len(absent),
                "zero_alignment_rows": len(zero),
                "low_alignment_rows": len(low),
                "reused_code_rows": len(reused),
                "zero_alignment_codes": join_values(
                    f"{row['code']}={row['warehouse_meaning']}" for row in zero
                ),
                "low_alignment_codes": join_values(
                    f"{row['code']}={row['warehouse_meaning']}" for row in low
                ),
                "audit_priority": (
                    "HIGH"
                    if zero and clean_text(rows[0].get("phenotypes"))
                    else "MEDIUM"
                    if low or absent or reused
                    else "LOW"
                ),
            }
        )
    return sorted(
        result,
        key=lambda row: (
            {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[row["audit_priority"]],
            -int(row["zero_alignment_rows"] or 0),
            row["specialty"],
            row["atom_id"],
        ),
    )


def load_candidate_annotations(
    related_path: Path | None, diagnostic_path: Path | None
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = defaultdict(dict)
    if related_path and related_path.exists():
        for row in read_csv(related_path):
            result[normalize_code(row.get("DIAGNOSIS_CODE"))]["amyloid_tier"] = clean_text(
                row.get("AMYLOID_TIER")
            )
    if diagnostic_path and diagnostic_path.exists():
        for row in read_csv(diagnostic_path):
            result[normalize_code(row.get("DIAGNOSIS_CODE"))][
                "amyloid_signal_categories"
            ] = clean_text(row.get("AMYLOID_SIGNAL_CATEGORIES"))
    return result


def rank_candidate_bucket(meaning: str, tier: str, categories: str) -> tuple[str, list[str]]:
    text = normalize_text(meaning)
    flags: list[str] = []
    if any(term in text for term in ALTERNATIVE_CAUSE_TERMS):
        flags.append("EXPLICIT_ALTERNATIVE_ETIOLOGY")
    if "inflammatory aa pathway" in normalize_text(categories):
        flags.append("AA_PATHWAY_NOT_ATTR_POSITIVE_EVIDENCE")
    if "direct amyloidosis" in normalize_text(categories) or "tier 1" in normalize_text(tier):
        bucket = "KNOWN_AMYLOIDOSIS_REVIEW"
    elif "plasma cell" in normalize_text(categories):
        bucket = "AL_DIFFERENTIAL_REVIEW"
    elif "tier 2" in normalize_text(tier):
        bucket = "HIGH_PRIORITY_ATTR_REVIEW"
    elif flags:
        bucket = "ALTERNATIVE_OR_GUARDRAIL_REVIEW"
    else:
        bucket = "NONSPECIFIC_SUPPORT_REVIEW"
    return bucket, flags


def suggest_atoms(
    meaning: str,
    category: str,
    atoms: dict[str, AtomInfo],
    category_atoms: dict[str, set[str]],
    token_atoms: dict[str, set[str]],
    limit: int = 5,
) -> list[tuple[float, AtomInfo, str]]:
    meaning_norm = normalize_text(meaning)
    meaning_tokens = semantic_tokens(meaning)
    suggestions: list[tuple[float, AtomInfo, str]] = []
    candidate_atom_ids = set(category_atoms.get(category, set()))
    for token in meaning_tokens:
        candidate_atom_ids.update(token_atoms.get(token, set()))
    for atom_id in candidate_atom_ids:
        atom = atoms[atom_id]
        if not atom.phenotypes:
            continue
        overlap = meaning_tokens & atom.tokens
        phrase_hit = any(phrase in meaning_norm for phrase in atom.phrases)
        same_category = atom.atom_id in category_atoms.get(category, set())
        score = 0.0
        reasons: list[str] = []
        if phrase_hit:
            score += 5.0
            reasons.append("phrase")
        if same_category:
            score += 2.0
            reasons.append("same_icd_category")
        if overlap:
            score += min(3.0, float(len(overlap)))
            reasons.append("tokens=" + ",".join(sorted(overlap)))
        if score >= 3.0 or phrase_hit or (same_category and overlap):
            suggestions.append((score, atom, ";".join(reasons)))
    suggestions.sort(key=lambda item: (-item[0], item[1].atom_id))
    return suggestions[:limit]


def candidate_audit(
    vocabulary: dict[str, VocabularyEntry],
    atoms: dict[str, AtomInfo],
    mappings: list[dict[str, object]],
    annotations: dict[str, dict[str, str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    configured = {
        normalize_code(row["code"])
        for row in mappings
        if clean_text(row["system"]) == "ICD10"
    }
    category_atoms: dict[str, set[str]] = defaultdict(set)
    token_atoms: dict[str, set[str]] = defaultdict(set)
    for atom in atoms.values():
        if atom.phenotypes:
            for token in atom.tokens:
                token_atoms[token].add(atom.atom_id)
    for row in mappings:
        if clean_text(row["system"]) != "ICD10" or row["source_kind"] != "ATOM":
            continue
        atom = atoms.get(clean_text(row["atom_id"]))
        if atom and atom.phenotypes:
            category_atoms[icd_category(row["code"])].add(atom.atom_id)

    supplied_missing: list[dict[str, object]] = []
    discovered: list[dict[str, object]] = []
    for code, entry in vocabulary.items():
        if code in configured:
            continue
        annotation = annotations.get(code, {})
        category = icd_category(code)
        suggestions = suggest_atoms(
            entry.meaning, category, atoms, category_atoms, token_atoms
        )
        origins: list[str] = []
        if annotation.get("amyloid_tier"):
            origins.append("SUPPLIED_465_LIST")
        if annotation.get("amyloid_signal_categories"):
            origins.append("SUPPLIED_895_LIST")
        if category in category_atoms:
            origins.append("CONFIGURED_ICD_CATEGORY")
        if suggestions and any("phrase" in reason for _, _, reason in suggestions):
            origins.append("ATOM_PHRASE_MATCH")
        if not origins:
            continue

        tier = annotation.get("amyloid_tier", "")
        categories = annotation.get("amyloid_signal_categories", "")
        bucket, flags = rank_candidate_bucket(entry.meaning, tier, categories)
        if entry.exact_match is False:
            flags.append("MEANING_FROM_PARENT_CODE")
        row = {
            "code": code,
            "meaning": entry.meaning,
            "warehouse_row_count": entry.row_count,
            "warehouse_patient_count": entry.patient_count,
            "candidate_origins": " | ".join(origins),
            "amyloid_tier": tier,
            "amyloid_signal_categories": categories,
            "review_bucket": bucket,
            "suggested_atom_ids": join_values(item[1].atom_id for item in suggestions),
            "suggested_atom_names": join_values(item[1].preferred_name for item in suggestions),
            "suggestion_scores": " | ".join(
                f"{item[1].atom_id}:{item[0]:.1f}({item[2]})" for item in suggestions
            ),
            "audit_flags": " | ".join(flags),
        }
        if annotation:
            supplied_missing.append(row)
        elif suggestions:
            discovered.append(row)

    sort_key = lambda row: (
        {
            "KNOWN_AMYLOIDOSIS_REVIEW": 0,
            "HIGH_PRIORITY_ATTR_REVIEW": 1,
            "AL_DIFFERENTIAL_REVIEW": 2,
            "NONSPECIFIC_SUPPORT_REVIEW": 3,
            "ALTERNATIVE_OR_GUARDRAIL_REVIEW": 4,
        }.get(clean_text(row["review_bucket"]), 9),
        -int(row["warehouse_patient_count"] or 0),
        clean_text(row["code"]),
    )
    return sorted(supplied_missing, key=sort_key), sorted(discovered, key=sort_key)


def load_official_codes(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            code, meaning = parts
            result[normalize_code(code[:3] + ("." + code[3:] if len(code) > 3 else ""))] = clean_text(
                meaning
            )
    return result


def official_not_in_warehouse_candidates(
    official: dict[str, str],
    warehouse: dict[str, VocabularyEntry],
    atoms: dict[str, AtomInfo],
    mappings: list[dict[str, object]],
) -> list[dict[str, object]]:
    configured = {
        normalize_code(row["code"])
        for row in mappings
        if clean_text(row["system"]) == "ICD10"
    }
    category_atoms: dict[str, set[str]] = defaultdict(set)
    token_atoms: dict[str, set[str]] = defaultdict(set)
    for atom in atoms.values():
        if atom.phenotypes:
            for token in atom.tokens:
                token_atoms[token].add(atom.atom_id)
    for row in mappings:
        if clean_text(row["system"]) != "ICD10" or row["source_kind"] != "ATOM":
            continue
        atom = atoms.get(clean_text(row["atom_id"]))
        if atom and atom.phenotypes:
            category_atoms[icd_category(row["code"])].add(atom.atom_id)

    result: list[dict[str, object]] = []
    for code, meaning in official.items():
        if code in warehouse or code in configured:
            continue
        category = icd_category(code)
        suggestions = suggest_atoms(
            meaning, category, atoms, category_atoms, token_atoms
        )
        if not suggestions:
            continue
        result.append(
            {
                "code": code,
                "meaning": meaning,
                "candidate_origins": (
                    "CONFIGURED_ICD_CATEGORY"
                    if category in category_atoms
                    else "ATOM_PHRASE_MATCH"
                ),
                "suggested_atom_ids": join_values(item[1].atom_id for item in suggestions),
                "suggested_atom_names": join_values(item[1].preferred_name for item in suggestions),
                "suggestion_scores": " | ".join(
                    f"{item[1].atom_id}:{item[0]:.1f}({item[2]})" for item in suggestions
                ),
            }
        )
    return sorted(result, key=lambda row: (icd_category(row["code"]), row["code"]))


def active_atom_icd_coverage(
    atoms: dict[str, AtomInfo],
    mappings: list[dict[str, object]],
    icd: dict[str, VocabularyEntry],
    supplied_candidates: list[dict[str, object]],
    discovered_candidates: list[dict[str, object]],
) -> list[dict[str, object]]:
    configured: dict[str, set[str]] = defaultdict(set)
    for row in mappings:
        if row["source_kind"] == "ATOM" and row["system"] == "ICD10":
            configured[clean_text(row["atom_id"])].add(normalize_code(row["code"]))

    supplied: dict[str, set[str]] = defaultdict(set)
    discovered: dict[str, set[str]] = defaultdict(set)
    for output, rows in ((supplied, supplied_candidates), (discovered, discovered_candidates)):
        for row in rows:
            for atom_id in clean_text(row.get("suggested_atom_ids")).split(" | "):
                if atom_id:
                    output[atom_id].add(normalize_code(row["code"]))

    result: list[dict[str, object]] = []
    for atom in atoms.values():
        if not atom.phenotypes:
            continue
        codes = configured.get(atom.atom_id, set())
        present = {code for code in codes if code in icd}
        supplied_codes = supplied.get(atom.atom_id, set())
        discovered_codes = discovered.get(atom.atom_id, set())
        if present:
            status = "WAREHOUSE_EXECUTABLE_ICD"
        elif codes:
            status = "CONFIGURED_ICD_NOT_OBSERVED_IN_WAREHOUSE"
        elif supplied_codes or discovered_codes:
            status = "NO_CONFIGURED_ICD_WITH_REVIEW_CANDIDATES"
        else:
            status = "NO_CONFIGURED_ICD_OR_DISCOVERED_CANDIDATE"
        result.append(
            {
                "specialty": atom.specialty,
                "phenotypes": join_values(atom.phenotypes),
                "atom_id": atom.atom_id,
                "atom_name": atom.preferred_name,
                "configured_icd_count": len(codes),
                "warehouse_present_configured_icd_count": len(present),
                "configured_icd_codes": join_values(codes),
                "warehouse_present_configured_icd_codes": join_values(present),
                "supplied_list_candidate_count": len(supplied_codes),
                "supplied_list_candidate_codes": join_values(supplied_codes),
                "outside_list_candidate_count": len(discovered_codes),
                "outside_list_candidate_codes": join_values(discovered_codes),
                "claims_coverage_status": status,
            }
        )
    return sorted(
        result,
        key=lambda row: (
            {
                "NO_CONFIGURED_ICD_WITH_REVIEW_CANDIDATES": 0,
                "NO_CONFIGURED_ICD_OR_DISCOVERED_CANDIDATE": 1,
                "CONFIGURED_ICD_NOT_OBSERVED_IN_WAREHOUSE": 2,
                "WAREHOUSE_EXECUTABLE_ICD": 3,
            }[row["claims_coverage_status"]],
            row["phenotypes"],
            row["specialty"],
            row["atom_id"],
        ),
    )


def configured_parent_descendant_gaps(
    mappings: list[dict[str, object]], icd: dict[str, VocabularyEntry]
) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    configured_by_atom: dict[str, set[str]] = defaultdict(set)
    for row in mappings:
        if row["system"] != "ICD10" or row["source_kind"] != "ATOM":
            continue
        code = normalize_code(row["code"])
        groups[code].append(row)
        configured_by_atom[clean_text(row["atom_id"])].add(code)

    result: list[dict[str, object]] = []
    for parent_code, rows in groups.items():
        if parent_code in icd:
            continue
        parent_compact = compact_code(parent_code)
        descendants = [
            entry
            for code, entry in icd.items()
            if len(compact_code(code)) > len(parent_compact)
            and compact_code(code).startswith(parent_compact)
        ]
        if not descendants:
            continue
        atom_ids = {clean_text(row["atom_id"]) for row in rows}
        missing_for_atoms = [
            entry
            for entry in descendants
            if any(entry.code not in configured_by_atom[atom_id] for atom_id in atom_ids)
        ]
        result.append(
            {
                "configured_parent_code": parent_code,
                "atom_ids": join_values(atom_ids),
                "atom_names": join_values(row["atom_name"] for row in rows),
                "phenotypes": join_values(row["phenotypes"] for row in rows),
                "warehouse_descendant_count": len(descendants),
                "warehouse_descendant_patient_count_sum": sum(
                    entry.patient_count for entry in descendants
                ),
                "warehouse_descendants": join_values(
                    f"{entry.code}={entry.meaning} (patients={entry.patient_count})"
                    for entry in descendants
                ),
                "descendants_missing_from_one_or_more_atoms": join_values(
                    entry.code for entry in missing_for_atoms
                ),
                "audit_flag": "EXACT_PARENT_WILL_NOT_MATCH_BILLABLE_DESCENDANTS",
            }
        )
    return sorted(
        result,
        key=lambda row: (
            -int(row["warehouse_descendant_patient_count_sum"] or 0),
            row["configured_parent_code"],
        ),
    )


MAPPING_FIELDS = [
    "source_kind",
    "source_file",
    "specialty",
    "phenotypes",
    "atom_id",
    "atom_name",
    "system",
    "code",
    "warehouse_meaning",
    "warehouse_row_count",
    "warehouse_patient_count",
    "mapping_role",
    "can_fire_atom_alone",
    "review_status",
    "match_mode",
    "context_guard",
    "warehouse_meaning_source",
    "warehouse_exact_meaning",
    "lexical_alignment",
    "lexical_overlap_tokens",
    "config_reuse_count",
    "audit_flags",
]

REUSE_FIELDS = [
    "system",
    "code",
    "warehouse_meaning",
    "warehouse_row_count",
    "warehouse_patient_count",
    "atom_count",
    "direct_atom_count",
    "atom_ids",
    "atom_names",
    "phenotypes",
    "mapping_roles",
    "audit_flag",
]

CANDIDATE_FIELDS = [
    "code",
    "meaning",
    "warehouse_row_count",
    "warehouse_patient_count",
    "candidate_origins",
    "amyloid_tier",
    "amyloid_signal_categories",
    "review_bucket",
    "suggested_atom_ids",
    "suggested_atom_names",
    "suggestion_scores",
    "audit_flags",
]

OFFICIAL_FIELDS = [
    "code",
    "meaning",
    "candidate_origins",
    "suggested_atom_ids",
    "suggested_atom_names",
    "suggestion_scores",
]

ATOM_COVERAGE_FIELDS = [
    "specialty",
    "phenotypes",
    "atom_id",
    "atom_name",
    "configured_icd_count",
    "warehouse_present_configured_icd_count",
    "configured_icd_codes",
    "warehouse_present_configured_icd_codes",
    "supplied_list_candidate_count",
    "supplied_list_candidate_codes",
    "outside_list_candidate_count",
    "outside_list_candidate_codes",
    "claims_coverage_status",
]

ATOM_SUMMARY_FIELDS = [
    "system",
    "specialty",
    "phenotypes",
    "atom_id",
    "atom_name",
    "configured_mapping_rows",
    "warehouse_present_rows",
    "warehouse_absent_rows",
    "zero_alignment_rows",
    "low_alignment_rows",
    "reused_code_rows",
    "zero_alignment_codes",
    "low_alignment_codes",
    "audit_priority",
]

PREFIX_FIELDS = [
    "source_file",
    "specialty",
    "phenotypes",
    "atom_id",
    "atom_name",
    "system",
    "prefix",
    "mapping_role",
    "can_fire_atom_alone",
    "review_status",
    "context_guard",
    "warehouse_matched_code_count",
    "warehouse_matched_patient_count_sum",
    "zero_alignment_code_count",
    "low_alignment_code_count",
    "matched_code_examples",
    "zero_alignment_examples",
    "audit_flag",
]

PARENT_GAP_FIELDS = [
    "configured_parent_code",
    "atom_ids",
    "atom_names",
    "phenotypes",
    "warehouse_descendant_count",
    "warehouse_descendant_patient_count_sum",
    "warehouse_descendants",
    "descendants_missing_from_one_or_more_atoms",
    "audit_flag",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=Path("v5/config"))
    parser.add_argument(
        "--icd-vocabulary", type=Path, default=Path("not_for_snowflake/sql_codes/icd_codes_with_meaning.csv")
    )
    parser.add_argument(
        "--snomed-vocabulary",
        type=Path,
        default=Path("not_for_snowflake/sql_codes/snomed_codes_with_meaning.csv"),
    )
    parser.add_argument(
        "--related-list", type=Path, default=Path("not_for_snowflake/sql_codes/icd_amyloid_related.csv")
    )
    parser.add_argument(
        "--diagnostic-list",
        type=Path,
        default=Path("not_for_snowflake/sql_codes/icd_amyloid_diagnostic_signals.csv"),
    )
    parser.add_argument(
        "--official-icd", type=Path, default=Path("not_for_snowflake/sql_codes/icd10cm-codes-2026.txt")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("v5/audits/terminology/generated")
    )
    args = parser.parse_args()

    icd = load_vocabulary(args.icd_vocabulary, "DIAGNOSIS_CODE")
    snomed = load_vocabulary(args.snomed_vocabulary, "SNOMED_CODE")
    atoms, mappings = load_atoms(args.config_dir)
    mappings.extend(load_confirmed_mappings(args.config_dir))
    fallbacks = load_prefix_fallbacks(args.config_dir, atoms)

    audited = mapping_audit(mappings, icd, snomed)
    reused = reuse_audit(audited)
    atom_summary = atom_mapping_summary(audited)
    prefix_audit = prefix_fallback_audit(fallbacks, icd)
    parent_gaps = configured_parent_descendant_gaps(mappings, icd)
    annotations = load_candidate_annotations(args.related_list, args.diagnostic_list)
    supplied_missing, discovered = candidate_audit(icd, atoms, mappings, annotations)
    atom_coverage = active_atom_icd_coverage(
        atoms, mappings, icd, supplied_missing, discovered
    )
    official = load_official_codes(args.official_icd)
    official_candidates = official_not_in_warehouse_candidates(
        official, icd, atoms, mappings
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "configured_mapping_audit.csv", audited, MAPPING_FIELDS)
    write_csv(args.output_dir / "ambiguous_code_reuse.csv", reused, REUSE_FIELDS)
    write_csv(args.output_dir / "atom_mapping_summary.csv", atom_summary, ATOM_SUMMARY_FIELDS)
    write_csv(args.output_dir / "prefix_fallback_audit.csv", prefix_audit, PREFIX_FIELDS)
    write_csv(
        args.output_dir / "configured_parent_descendant_gaps.csv",
        parent_gaps,
        PARENT_GAP_FIELDS,
    )
    write_csv(
        args.output_dir / "supplied_lists_unconfigured.csv", supplied_missing, CANDIDATE_FIELDS
    )
    write_csv(
        args.output_dir / "discovered_outside_supplied_lists.csv", discovered, CANDIDATE_FIELDS
    )
    write_csv(
        args.output_dir / "official_codes_not_in_warehouse_candidates.csv",
        official_candidates,
        OFFICIAL_FIELDS,
    )
    write_csv(
        args.output_dir / "active_atom_icd_coverage.csv",
        atom_coverage,
        ATOM_COVERAGE_FIELDS,
    )

    distinct_config = {(row["system"], row["code"]) for row in mappings}
    summary = {
        "warehouse_icd_codes": len(icd),
        "warehouse_snomed_codes": len(snomed),
        "configured_mapping_rows": len(mappings),
        "configured_distinct_system_codes": len(distinct_config),
        "configured_icd_distinct": len(
            {row["code"] for row in mappings if row["system"] == "ICD10"}
        ),
        "configured_snomed_distinct": len(
            {row["code"] for row in mappings if row["system"] == "SNOMED_CT"}
        ),
        "configured_not_in_warehouse_vocabulary_rows": sum(
            "NOT_IN_WAREHOUSE_VOCABULARY" in clean_text(row["audit_flags"])
            for row in audited
        ),
        "zero_lexical_alignment_rows": sum(
            "ZERO_LEXICAL_ALIGNMENT_REVIEW" in clean_text(row["audit_flags"])
            for row in audited
        ),
        "ambiguous_reused_codes": len(reused),
        "conflicting_direct_reused_codes": sum(
            row["audit_flag"] == "CONFLICTING_DIRECT_REUSE" for row in reused
        ),
        "active_atoms_with_high_priority_mapping_review": sum(
            row["audit_priority"] == "HIGH" for row in atom_summary
        ),
        "configured_prefix_fallbacks": len(prefix_audit),
        "high_risk_prefix_fallbacks": sum(
            row["audit_flag"] == "HIGH_RISK_BROAD_PREFIX" for row in prefix_audit
        ),
        "configured_parent_codes_with_observed_descendants": len(parent_gaps),
        "supplied_list_unconfigured_codes": len(supplied_missing),
        "discovered_outside_supplied_lists": len(discovered),
        "official_candidate_codes_not_in_warehouse": len(official_candidates),
        "active_atom_claims_coverage_status": dict(
            Counter(row["claims_coverage_status"] for row in atom_coverage)
        ),
        "review_bucket_counts": dict(
            Counter(row["review_bucket"] for row in supplied_missing)
        ),
        "notes": [
            "All candidate suggestions require clinical/configuration review.",
            "Lexical alignment is a triage heuristic, not semantic validation.",
            "The source CSVs and API key are not copied into the audit output.",
        ],
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

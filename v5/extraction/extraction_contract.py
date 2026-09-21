"""Central extraction routing and clinical-context contract.

This is the single place to change extraction plumbing when a warehouse field,
terminology-system route, or supported medSpaCy context attribute changes.  It
contains no phenotype logic, clinical phrases, codes, scores, or thresholds.
Those remain entirely in the deployable JSON configuration.
"""

from __future__ import annotations

from typing import Any, Iterable


_SYSTEM_ALIASES = {
    "": "",
    "ICD": "ICD",
    "ICD9": "ICD9",
    "ICD 9": "ICD9",
    "ICD 9 CM": "ICD9",
    "ICD9 CM": "ICD9",
    "ICD9CM": "ICD9",
    "ICD10": "ICD10",
    "ICD 10": "ICD10",
    "ICD 10 CM": "ICD10",
    "ICD10 CM": "ICD10",
    "ICD10CM": "ICD10",
    "CPT": "CPT_HCPCS",
    "HCPCS": "CPT_HCPCS",
    "CPT HCPCS": "CPT_HCPCS",
    "CPT/HCPCS": "CPT_HCPCS",
    "CPT_HCPCS": "CPT_HCPCS",
    "SNOMED": "SNOMED_CT",
    "SNOMED CT": "SNOMED_CT",
    "SNOMEDCT": "SNOMED_CT",
    "SNOMED_CT": "SNOMED_CT",
    "LOINC": "LOINC",
    "KEYWORD": "NLP",
    "PHRASE": "NLP",
    "TEXT": "NLP",
    "CLINICAL TEXT": "NLP",
    "SNOMED TEXT": "NLP",
    "NLP": "NLP",
}


def normalize_system(value: Any) -> str:
    """Return one canonical terminology-system name.

    System names are configuration identifiers, not free text.  In
    particular, ICD-10-CM and ICD-9-CM are aliases for the diagnosis families
    used by the source contract; ICD-10-PCS is deliberately not collapsed into
    ICD-10 because it is a different code system and route.
    """
    text = str(value or "").strip().upper().replace("-", " ").replace("/", " ")
    text = " ".join(text.replace("_", " ").split())
    return _SYSTEM_ALIASES.get(text, text)


NLP_SYSTEMS = frozenset({"NLP"})
TERMINOLOGY_MODE_ALL = "ALL"
TERMINOLOGY_MODE_ICD_ONLY = "ICD_ONLY"


def normalize_terminology_mode(value: Any) -> str:
    """Normalize the explicit terminology subset used for a pipeline run."""
    normalized = str(value or TERMINOLOGY_MODE_ALL).strip().upper().replace("-", "_")
    aliases = {"ICD": TERMINOLOGY_MODE_ICD_ONLY, "ICD10": TERMINOLOGY_MODE_ICD_ONLY}
    normalized = aliases.get(normalized, normalized)
    if normalized not in {TERMINOLOGY_MODE_ALL, TERMINOLOGY_MODE_ICD_ONLY}:
        raise ValueError(
            f"unsupported terminology mode {value!r}; expected ALL or ICD_ONLY"
        )
    return normalized


def terminology_mode_for_systems(
    systems: Iterable[Any] | None,
    *,
    default: str = TERMINOLOGY_MODE_ALL,
) -> str:
    """Resolve an explicit system allow-list to the supported run mode.

    The initial warehouse run intentionally supports an ICD-family-only
    allow-list. Other terminology systems require their own extraction mode
    and are rejected rather than silently broadened.
    """
    if systems is None:
        return normalize_terminology_mode(default)
    selected = {normalize_system(value) for value in systems if str(value).strip()}
    if not selected or not selected.issubset({"ICD", "ICD9", "ICD10"}):
        raise ValueError("terminology_systems must contain one or more ICD-family systems")
    return TERMINOLOGY_MODE_ICD_ONLY


def terminology_allowed(value: Any, mode: str = TERMINOLOGY_MODE_ALL) -> bool:
    """Return whether one terminology system is active for ``mode``."""
    selected = normalize_terminology_mode(mode)
    if selected == TERMINOLOGY_MODE_ALL:
        return True
    return normalize_system(value) in {"ICD", "ICD9", "ICD10"}


def is_nlp_system(value: Any) -> bool:
    normalized = normalize_system(value)
    # An empty or unknown label is not permission to scan narrative fields.
    # Only an explicit NLP alias may take the broad text route.
    return normalized in NLP_SYSTEMS


# Logical table/field names are resolved to physical warehouse identifiers by
# warehouse.source_schema.  Strategies describe retrieval only; they never
# establish clinical evidence.
STRUCTURED_SOURCE_ROUTES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "ICD": (
        ("claim", "diagnosis_code", "EXACT_CODE"),
    ),
    "ICD9": (
        ("claim", "diagnosis_code", "EXACT_CODE"),
        ("claim", "other_diagnosis_9", "EXACT_CODE"),
    ),
    "ICD10": (
        ("claim", "diagnosis_code", "EXACT_CODE"),
        ("claim", "other_diagnosis_10", "EXACT_CODE"),
    ),
    "CPT_HCPCS": (("claim", "procedure_code", "EXACT_CODE"),),
    "SNOMED_CT": (
        ("medical_history", "snomed", "EXACT_CODE"),
        ("medical_history", "secondary_snomed", "EXACT_CODE"),
        ("surgical_history", "snomed", "EXACT_CODE"),
        ("surgical_history", "secondary_snomed", "EXACT_CODE"),
        ("family_history", "snomed", "EXACT_CODE"),
    ),
    "LOINC": (("lab", "observation_identifier", "EXACT_CODE"),),
}


NLP_SOURCE_ROUTES: tuple[tuple[str, str, str], ...] = (
    ("claim", "clinical_notes", "BROAD_TEXT_FOR_PHRASEMATCHER"),
    ("clinical_note", "note_text", "BROAD_TEXT_FOR_PHRASEMATCHER"),
    ("medical_history", "value", "BROAD_TEXT_FOR_PHRASEMATCHER"),
    ("surgical_history", "value", "BROAD_TEXT_FOR_PHRASEMATCHER"),
    ("family_history", "condition", "BROAD_TEXT_FOR_PHRASEMATCHER"),
    ("lab", "lab_result_note", "BROAD_TEXT_FOR_PHRASEMATCHER"),
)


def routes_for_system(value: Any) -> tuple[tuple[str, str, str], ...]:
    normalized = normalize_system(value)
    if is_nlp_system(normalized):
        return NLP_SOURCE_ROUTES
    return STRUCTURED_SOURCE_ROUTES.get(normalized, ())


EVENT_SYSTEM_COMPATIBILITY: dict[str, frozenset[tuple[str, str]]] = {
    "ICD": frozenset({
        ("CLAIM", "diagnosis_code"),
        ("CLAIM", "other_diagnosis_9"),
        ("CLAIM", "other_diagnosis_10"),
    }),
    "CPT_HCPCS": frozenset({("CLAIM", "procedure_code")}),
    "SNOMED_CT": frozenset({
        ("MEDICAL_HISTORY", "snomed"),
        ("MEDICAL_HISTORY", "secondary_snomed"),
        ("SURGICAL_HISTORY", "snomed"),
        ("SURGICAL_HISTORY", "secondary_snomed"),
        ("FAMILY_HISTORY", "snomed"),
    }),
    "LOINC": frozenset({("LAB", "observation_identifier")}),
}


# A missing or unrecognised DiagnosisType is retained as generic ICD evidence.
# It must not be guessed as ICD-9 or ICD-10, and therefore cannot satisfy a
# typed ICD9/ICD10 term until the source supplies an explicit type.
UNKNOWN_DIAGNOSIS_TYPE_POLICY = "GENERIC_ICD"


def diagnosis_system(value: Any) -> tuple[str, bool]:
    """Return (canonical system, is_unknown) for a claim DiagnosisType."""
    normalized = normalize_system(value)
    if normalized in {"ICD9", "ICD10"}:
        return normalized, False
    return "ICD", True


def event_system_compatible(
    source_table: Any,
    source_field: Any,
    terminology_system: Any,
    source_code_system: Any = None,
) -> bool:
    system = normalize_system(terminology_system)
    if system in {"ICD", "ICD9", "ICD10"}:
        family = "ICD"
    elif system == "CPT_HCPCS":
        family = "CPT_HCPCS"
    elif system == "SNOMED_CT":
        family = "SNOMED_CT"
    elif system == "LOINC":
        family = "LOINC"
    else:
        return False
    table_field = (str(source_table).upper(), str(source_field or "").lower())
    if table_field not in EVENT_SYSTEM_COMPATIBILITY[family]:
        return False
    observed = normalize_system(source_code_system)
    if family == "ICD":
        if table_field[1] == "other_diagnosis_9":
            return system == "ICD9"
        if table_field[1] == "other_diagnosis_10":
            return system == "ICD10"
        # The primary diagnosis field is only typed when DiagnosisType is
        # present and recognised.  Generic ICD terms are reserved for
        # unknown/blank types and must not widen a typed ICD9/ICD10 route.
        if observed == "ICD9":
            return system == "ICD9"
        if observed == "ICD10":
            return system == "ICD10"
        return system == "ICD"
    # Structured events carry their native system explicitly.  Do not let a
    # malformed/local event satisfy a term merely because its source column
    # happens to be in the right table.
    return observed == family


MEDSPACY_CONTEXT_ATTRIBUTES = (
    "is_negated",
    "is_uncertain",
    "experiencer",
    "stage",
    "pretest",
    "context_lineage_ids",
    "is_historical",
    "temporality",
)


def derive_available_date(explicit_available_date: Any, event_date: Any) -> Any:
    """Use the source availability timestamp when present, else event time.

    The supplied warehouse contract has no separate ingestion/availability
    column.  Falling back to the clinical event date is therefore explicit and
    auditable rather than hidden inside event construction.
    """
    return event_date if explicit_available_date in (None, "") else explicit_available_date


__all__ = [
    "NLP_SYSTEMS",
    "NLP_SOURCE_ROUTES",
    "STRUCTURED_SOURCE_ROUTES",
    "MEDSPACY_CONTEXT_ATTRIBUTES",
    "normalize_system",
    "diagnosis_system",
    "UNKNOWN_DIAGNOSIS_TYPE_POLICY",
    "is_nlp_system",
    "normalize_terminology_mode",
    "terminology_mode_for_systems",
    "terminology_allowed",
    "TERMINOLOGY_MODE_ALL",
    "TERMINOLOGY_MODE_ICD_ONLY",
    "routes_for_system",
    "event_system_compatible",
    "derive_available_date",
]

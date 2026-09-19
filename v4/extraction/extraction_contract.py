"""Central extraction routing and clinical-context contract.

This is the single place to change extraction plumbing when a warehouse field,
terminology-system route, or supported medSpaCy context attribute changes.  It
contains no phenotype logic, clinical phrases, codes, scores, or thresholds.
Those remain entirely in the deployable JSON configuration.
"""

from __future__ import annotations

from typing import Any


def normalize_system(value: Any) -> str:
    return " ".join(str(value or "").strip().upper().replace("_", " ").split())


NLP_SYSTEMS = frozenset({"NLP", "TEXT", "PHRASE", "CLINICAL TEXT", "SNOMED TEXT"})


def is_nlp_system(value: Any) -> bool:
    normalized = normalize_system(value)
    return not normalized or normalized in NLP_SYSTEMS


# Logical table/field names are resolved to physical warehouse identifiers by
# warehouse.source_schema.  Strategies describe retrieval only; they never
# establish clinical evidence.
STRUCTURED_SOURCE_ROUTES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "ICD": (
        ("claim", "diagnosis_code", "EXACT_CODE"),
        ("claim", "other_diagnosis_9", "EXACT_CODE"),
        ("claim", "other_diagnosis_10", "EXACT_CODE"),
    ),
    "ICD9": (
        ("claim", "diagnosis_code", "EXACT_CODE"),
        ("claim", "other_diagnosis_9", "EXACT_CODE"),
        ("claim", "other_diagnosis_10", "EXACT_CODE"),
    ),
    "ICD-9": (
        ("claim", "diagnosis_code", "EXACT_CODE"),
        ("claim", "other_diagnosis_9", "EXACT_CODE"),
        ("claim", "other_diagnosis_10", "EXACT_CODE"),
    ),
    "ICD10": (
        ("claim", "diagnosis_code", "EXACT_CODE"),
        ("claim", "other_diagnosis_9", "EXACT_CODE"),
        ("claim", "other_diagnosis_10", "EXACT_CODE"),
    ),
    "ICD-10": (
        ("claim", "diagnosis_code", "EXACT_CODE"),
        ("claim", "other_diagnosis_9", "EXACT_CODE"),
        ("claim", "other_diagnosis_10", "EXACT_CODE"),
    ),
    "CPT": (("claim", "procedure_code", "EXACT_CODE"),),
    "HCPCS": (("claim", "procedure_code", "EXACT_CODE"),),
    "CPT HCPCS": (("claim", "procedure_code", "EXACT_CODE"),),
    "CPT/HCPCS": (("claim", "procedure_code", "EXACT_CODE"),),
    "SNOMED": (
        ("medical_history", "snomed", "EXACT_CODE"),
        ("medical_history", "secondary_snomed", "EXACT_CODE"),
        ("surgical_history", "snomed", "EXACT_CODE"),
        ("surgical_history", "secondary_snomed", "EXACT_CODE"),
        ("family_history", "snomed", "EXACT_CODE"),
    ),
    "SNOMED CT": (
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


def event_system_compatible(
    source_table: Any,
    source_field: Any,
    terminology_system: Any,
    source_code_system: Any = None,
) -> bool:
    system = normalize_system(terminology_system)
    if system in {"ICD", "ICD9", "ICD-9", "ICD10", "ICD-10"}:
        family = "ICD"
    elif system in {"CPT", "HCPCS", "CPT HCPCS", "CPT/HCPCS"}:
        family = "CPT_HCPCS"
    elif system in {"SNOMED", "SNOMED CT"}:
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
            return system in {"ICD", "ICD9", "ICD-9"}
        if table_field[1] == "other_diagnosis_10":
            return system in {"ICD", "ICD10", "ICD-10"}
        if observed in {"ICD9", "ICD-9"}:
            return system in {"ICD", "ICD9", "ICD-9"}
        if observed in {"ICD10", "ICD-10"}:
            return system in {"ICD", "ICD10", "ICD-10"}
    return True


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
    "is_nlp_system",
    "routes_for_system",
    "event_system_compatible",
    "derive_available_date",
]

"""System-aware terminology matching helpers.

This module is intentionally independent of the clinical configuration loader.
Compiled terminology rows may contain either the modern explicit fields
(``match_mode``, ``expanded_values``, ``match_in_text``) or the legacy value
shape.  Both candidate retrieval and atom matching use these helpers so that
their semantics cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence


EXACT = "EXACT"
PREFIX = "PREFIX"
RANGE = "RANGE"
PREFIX_FALLBACK = "PREFIX_FALLBACK"
CODE_IN_TEXT = "CODE_IN_TEXT"


def _get(row: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row:
            return row[name]
        wanted = name.replace(" ", "_").lower()
        for key in row:
            if str(key).replace(" ", "_").lower() == wanted:
                return row[key]
    return default


def normalize_code_system(value: Any) -> str:
    """Normalize terminology system labels without changing code values."""
    text = str(value or "").strip().upper().replace("_", " ").replace("-", " ").replace("/", " ")
    text = " ".join(text.split())
    aliases = {
        "ICD": "ICD",
        "ICD 9": "ICD9",
        "ICD9": "ICD9",
        "ICD 9 CM": "ICD9",
        "ICD9 CM": "ICD9",
        "ICD9CM": "ICD9",
        "ICD 10": "ICD10",
        "ICD10": "ICD10",
        "ICD 10 CM": "ICD10",
        "ICD10 CM": "ICD10",
        "ICD10CM": "ICD10",
        "CPT": "CPT_HCPCS",
        "HCPCS": "CPT_HCPCS",
        "CPT HCPCS": "CPT_HCPCS",
        "CPT/HCPCS": "CPT_HCPCS",
        "SNOMED": "SNOMED_CT",
        "SNOMED CT": "SNOMED_CT",
        "SNOMEDCT": "SNOMED_CT",
        "LOINC": "LOINC",
    }
    return aliases.get(text, text)


def is_structured_system(value: Any) -> bool:
    return normalize_code_system(value) in {"ICD", "ICD9", "ICD10", "CPT_HCPCS", "SNOMED_CT", "LOINC"}


def _text(value: Any) -> str:
    return str(value or "").strip().upper()


def canonical_code(value: Any, system: Any) -> str:
    """Return an exact comparison key.

    ICD has a deliberate dotted/dotless alias policy.  Other systems retain
    punctuation and leading zeros; converting a warehouse number to a Python
    number would make ``00123`` indistinguishable from ``123``.
    """
    text = _text(value)
    if normalize_code_system(system) in {"ICD", "ICD9", "ICD10"}:
        return text.replace(".", "")
    return text


def code_forms(value: Any, system: Any) -> tuple[str, ...]:
    """Return comparison aliases in deterministic order."""
    raw = _text(value)
    canonical = canonical_code(raw, system)
    if normalize_code_system(system) in {"ICD", "ICD9", "ICD10"}:
        # ICD dotted/dotless equality is an identifier alias, not descendant
        # matching.  ICD-9-CM and ICD-10-CM both conventionally place the dot
        # after the first three characters when a dot is present.
        dotted = (
            canonical[:3] + "." + canonical[3:]
            if "." not in raw and len(canonical) > 3 else ""
        )
        aliases = [canonical, raw]
        if dotted:
            aliases.append(dotted)
        return tuple(dict.fromkeys(alias for alias in aliases if alias))
    return (canonical,)


def _truth(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().upper()
    if text in {"TRUE", "YES", "Y", "1", "ON"}:
        return True
    if text in {"FALSE", "NO", "N", "0", "OFF", ""}:
        return False
    return default


def term_match_mode(term: Mapping[str, Any]) -> str:
    system = normalize_code_system(_get(term, "terminology_system", "system", "Terminology_System", default=""))
    value = str(_get(term, "standard_code", "STANDARD_CODE", "value", "Value", default="") or "").strip()
    raw_mode = _get(term, "match_mode", "Match_Mode", "code_match_mode", "Code_Match_Mode")
    if raw_mode not in (None, ""):
        explicit_mode = str(raw_mode).strip().upper().replace("-", "_").replace(" ", "_")
        if explicit_mode == PREFIX_FALLBACK:
            return PREFIX_FALLBACK
    # LOINC's hyphen is part of the identifier/check digit.  It is never a
    # range delimiter, even if a stale mode field says otherwise.
    if system == "LOINC":
        return EXACT
    # Invalid range/family literals cannot be revived by a stale EXACT mode.
    # They remain metadata until explicit reviewed members are supplied.
    if system in {"ICD", "ICD9", "ICD10"} and value.endswith("."):
        return PREFIX
    if system in {"ICD", "ICD9", "ICD10", "CPT_HCPCS"} and value.count("-") == 1:
        return RANGE
    if raw_mode not in (None, ""):
        mode = str(raw_mode).strip().upper().replace("-", "_").replace(" ", "_")
        if mode in {"EXACT", "EXACT_CODE", "EQUALITY"}:
            return EXACT
        if mode in {"PREFIX", "PREFIX_CODE", "FAMILY"}:
            return PREFIX
        if mode in {"RANGE", "RANGE_CODE", "EXPANDED"}:
            return RANGE
    # Legacy trailing-dot family syntax is safe only for ICD.  Authored ICD
    # hyphenated values are ranges and therefore fail closed without members.
    # Authored ICD ranges are not executable without an explicit expansion;
    # classify them as RANGE so all consumers fail closed instead of matching
    # the literal ``left-right`` text.
    if _get(term, "expanded_values", "Expanded_Values", "range_values", "Range_Values") not in (None, "", [], ()):
        return RANGE
    return EXACT


def term_values(term: Mapping[str, Any]) -> tuple[str, ...]:
    value = _get(term, "standard_code", "STANDARD_CODE", "value", "Value", "code", "Code", default="")
    if value in (None, ""):
        return ()
    return (str(value).strip(),)


def expanded_values(term: Mapping[str, Any]) -> tuple[str, ...]:
    values = _get(term, "expanded_values", "Expanded_Values", "range_values", "Range_Values", default=())
    if isinstance(values, str):
        values = [part.strip() for part in values.replace(";", ",").split(",") if part.strip()]
    if not isinstance(values, (list, tuple, set)):
        return ()
    return tuple(str(value).strip() for value in values if str(value).strip())


def executable_values(term: Mapping[str, Any]) -> tuple[str, ...]:
    """Return only explicitly reviewed range/prefix members.

    Runtime matching must never manufacture identifiers by arithmetic
    expansion. The name is retained as a compatibility API for callers that
    already use it; its result is now strictly the authored member list.
    """
    return expanded_values(term)


def _icd_prefix_base(term: Mapping[str, Any]) -> tuple[str, str] | None:
    """Return a valid authored ICD family base for explicit fallback.

    Fallback is intentionally restricted to a trailing-dot family literal.
    A bare prefix-looking value, a numeric range, and every non-ICD system
    remain exact-member-only.  The syntax is operational configuration only;
    no workbook descriptions or metadata participate.
    """
    system = normalize_code_system(_get(term, "terminology_system", "system", "Terminology_System", default=""))
    if system not in {"ICD", "ICD9", "ICD10"}:
        return None
    value = term_values(term)[0] if term_values(term) else ""
    if not value.endswith("."):
        return None
    base = value[:-1].strip().upper()
    if system == "ICD9":
        valid = re.fullmatch(r"\d{3}", base) is not None
    elif system == "ICD10":
        valid = re.fullmatch(r"[A-Z]\d{2}", base) is not None
    else:
        valid = re.fullmatch(r"(?:[A-Z]\d{2}|\d{3})", base) is not None
    return (system, base) if valid else None


def prefix_fallback_supported(term: Mapping[str, Any]) -> bool:
    """Whether an authored ICD family may use the second-stage fallback."""
    # Legacy trailing-dot PREFIX rows deliberately remain fail-closed.  Only
    # an explicit operational PREFIX_FALLBACK row/field can activate this
    # second stage; workbook descriptions and inferred syntax do not count.
    raw_mode = _get(term, "match_mode", "Match_Mode", "code_match_mode", "Code_Match_Mode")
    explicit = str(raw_mode or "").strip().upper().replace("-", "_").replace(" ", "_")
    explicit = explicit == PREFIX_FALLBACK or _truth(
        _get(term, "prefix_fallback", "Prefix_Fallback", "allow_prefix_fallback", "Allow_Prefix_Fallback")
    )
    return explicit and _icd_prefix_base(term) is not None


def _prefix_fallback_match(source_value: Any, term: Mapping[str, Any]) -> bool:
    prefix = _icd_prefix_base(term)
    if prefix is None:
        return False
    system, base = prefix
    source = _text(source_value)
    if not _valid_code_token(source, system):
        return False
    canonical = canonical_code(source, system)
    canonical_base = base.replace(".", "")
    # The family literal itself (I42.) is not a code.  Dotted and dotless
    # representations of a child (I42.0 / I420) are equivalent aliases.
    return len(canonical) > len(canonical_base) and canonical.startswith(canonical_base)


def match_code_value(source_value: Any, term: Mapping[str, Any]) -> tuple[bool, str]:
    """Match a structured source value and return ``(matched, mode)``."""
    system = normalize_code_system(_get(term, "terminology_system", "system", "Terminology_System", default=""))
    if not is_structured_system(system):
        return False, EXACT
    source_forms = set(code_forms(source_value, system))
    if not source_forms or source_forms == {""}:
        return False, term_match_mode(term)
    mode = term_match_mode(term)
    configured = expanded_values(term) if mode in {PREFIX, PREFIX_FALLBACK, RANGE} else term_values(term)
    if mode in {PREFIX, PREFIX_FALLBACK, RANGE} and not configured and not prefix_fallback_supported(term):
        # A family/range authoring row is metadata until reviewed discrete
        # members are supplied; never compare its literal dynamically.
        return False, mode
    allowed = {form for value in configured for form in code_forms(value, system)}
    if source_forms & allowed:
        # A dedicated fallback row can carry reviewed exact members as its
        # first stage.  Surface those as EXACT so atom matching and audits can
        # distinguish the preferred member path from the dynamic fallback.
        return True, EXACT if mode == PREFIX_FALLBACK else mode
    if mode in {PREFIX, PREFIX_FALLBACK} and prefix_fallback_supported(term) and _prefix_fallback_match(source_value, term):
        return True, PREFIX_FALLBACK
    return False, mode


def code_in_text_enabled(term: Mapping[str, Any]) -> bool:
    raw = _get(term, "match_in_text", "Match_In_Text", "code_in_text", "Code_In_Text", "allow_code_in_text", "Allow_Code_In_Text")
    # Structured codes are text-searchable by default, but callers can turn
    # this off for numeric values whose narrative use is too ambiguous.
    return _truth(raw, default=True)


def _valid_code_token(value: Any, system: str) -> bool:
    """Return whether a value has the syntax of a discrete identifier."""
    token = _text(value)
    if not token:
        return False
    if system in {"ICD", "ICD9", "ICD10"}:
        return re.fullmatch(r"[A-Z0-9]+(?:\.[A-Z0-9]+)?", token) is not None
    if system == "CPT_HCPCS":
        return re.fullmatch(r"[A-Z0-9]+", token) is not None
    if system == "SNOMED_CT":
        return re.fullmatch(r"\d+", token) is not None
    if system == "LOINC":
        return re.fullmatch(r"\d+-\d+", token) is not None
    return False


def code_in_text_supported(term: Mapping[str, Any]) -> bool:
    """Whether a term can produce exact discrete-code narrative evidence."""
    if not code_in_text_enabled(term):
        return False
    system = normalize_code_system(_get(term, "terminology_system", "system", "Terminology_System", default=""))
    if not is_structured_system(system):
        return False
    mode = term_match_mode(term)
    if mode in {PREFIX, PREFIX_FALLBACK, RANGE}:
        # Prefix families may use the explicit second-stage ICD fallback;
        # ranges and all non-ICD prefix-like rows remain exact-member-only.
        values = expanded_values(term)
        if values and all(_valid_code_token(value, system) for value in values):
            return True
        return mode in {PREFIX, PREFIX_FALLBACK} and prefix_fallback_supported(term)
    return _valid_code_token(term_values(term)[0] if term_values(term) else "", system)


@dataclass(frozen=True)
class TextCodeSpan:
    start: int
    end: int
    value: str


def _code_pattern(value: str, system: str, mode: str) -> str | None:
    if not value:
        return None
    forms = code_forms(value, system)
    alternatives = [re.escape(form) for form in forms if form]
    if not alternatives:
        return None
    return "(?:" + "|".join(sorted(set(alternatives), key=len, reverse=True)) + ")"


def find_code_in_text(text: Any, term: Mapping[str, Any]) -> tuple[TextCodeSpan, ...]:
    """Find explicit code mentions with boundaries and numeric safeguards."""
    if not text or not code_in_text_supported(term):
        return ()
    system = normalize_code_system(_get(term, "terminology_system", "system", "Terminology_System", default=""))
    if not is_structured_system(system):
        return ()
    mode = term_match_mode(term)
    value = term_values(term)[0] if term_values(term) else ""
    # Narrative extraction is exact-code-only.  Prefix/family authoring may
    # contribute only its reviewed discrete members, never descendants.
    # A malformed/authored range must not become a literal narrative token.
    # Explicit expanded range members remain eligible as discrete exact codes.
    if mode != RANGE and system in {"ICD", "ICD9", "ICD10", "CPT_HCPCS"} and value.count("-") == 1:
        return ()
    if mode in {PREFIX, PREFIX_FALLBACK} and prefix_fallback_supported(term):
        values = expanded_values(term)
        patterns = [_code_pattern(member, system, EXACT) for member in values]
        patterns = [pattern for pattern in patterns if pattern]
        _, base = _icd_prefix_base(term)  # validated by prefix_fallback_supported
        # Match only a non-empty child token.  Both dotted and dotless ICD
        # aliases are accepted, but the literal family prefix is not.
        fallback = rf"{re.escape(base)}(?:\.[A-Z0-9]+|[A-Z0-9]+)"
        patterns.append(f"(?:{fallback})")
        pattern = "(?:" + "|".join(sorted(set(patterns), key=len, reverse=True)) + ")"
    elif mode in {PREFIX, PREFIX_FALLBACK, RANGE}:
        values = expanded_values(term)
        patterns = [_code_pattern(member, system, EXACT) for member in values]
        patterns = [pattern for pattern in patterns if pattern]
        pattern = "(?:" + "|".join(sorted(set(patterns), key=len, reverse=True)) + ")" if patterns else None
    else:
        pattern = _code_pattern(value, system, mode)
    if not pattern:
        return ()
    # Alphanumeric boundaries prevent 49436004 matching inside an identifier.
    # The decimal guard prevents an exact ICD root such as I50 from matching
    # the descendant I50.1 in narrative text.
    prefix = r"(?<![A-Z0-9])"
    suffix = r"(?![A-Z0-9])"
    if system in {"ICD", "ICD9", "ICD10", "LOINC"} and mode in {EXACT, RANGE, PREFIX, PREFIX_FALLBACK}:
        suffix = r"(?![A-Z0-9]|\.\d)"
    # Bare numeric codes are especially ambiguous in prose (for example a
    # dosage or measurement written as ``123.0``).  Treat a decimal-looking
    # continuation as one numeric token rather than a code mention.
    numeric_values = executable_values(term) if mode in {PREFIX, PREFIX_FALLBACK, RANGE} else (value,)
    if numeric_values and all(str(member).strip().isdigit() for member in numeric_values):
        prefix = r"(?<![A-Z0-9])(?<!\d\.)"
        suffix = r"(?![A-Z0-9]|\.\d)"
    regex = re.compile(rf"{prefix}{pattern}{suffix}", re.IGNORECASE)
    out: list[TextCodeSpan] = []
    narrative = str(text)
    for match in regex.finditer(str(text)):
        start, end = match.start(), match.end()
        # Do not extract a member embedded in an authored range literal such
        # as ``33206-33208``.  This guard is outside the regex so whitespace
        # around the hyphen is handled without weakening identifier boundaries.
        before = narrative[:start]
        after = narrative[end:]
        if re.search(r"[A-Z0-9]\s*-\s*$", before, re.IGNORECASE):
            continue
        if re.match(r"^\s*-\s*[A-Z0-9]", after, re.IGNORECASE):
            continue
        out.append(TextCodeSpan(start, end, match.group(0)))
    return tuple(out)


__all__ = [
    "EXACT", "PREFIX", "RANGE", "PREFIX_FALLBACK", "CODE_IN_TEXT", "TextCodeSpan",
    "normalize_code_system", "is_structured_system", "canonical_code",
    "code_forms", "term_match_mode", "expanded_values", "match_code_value", "prefix_fallback_supported",
    "executable_values",
    "code_in_text_enabled", "find_code_in_text",
    "code_in_text_supported",
]

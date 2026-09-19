"""Structural and cross-sheet validation for workbook-derived V4 config.

Validation is intentionally strict about references and categorical values.  It
never attempts to repair a missing clinical mapping from another source.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


class ConfigValidationError(ValueError):
    """Raised when a compiled clinical configuration is not executable."""

    def __init__(self, message: str, report: Optional["ValidationReport"] = None):
        super().__init__(message)
        self.report = report


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    sheet: Optional[str] = None
    row: Optional[int] = None
    field: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationReport:
    workbook_sha256: Optional[str] = None
    errors: List[ValidationIssue] = None
    warnings: List[ValidationIssue] = None

    def __post_init__(self) -> None:
        self.errors = list(self.errors or [])
        self.warnings = list(self.warnings or [])

    @property
    def valid(self) -> bool:
        return not self.errors

    def add_error(self, code: str, message: str, **where: Any) -> None:
        self.errors.append(ValidationIssue("ERROR", code, message, **where))

    def add_warning(self, code: str, message: str, **where: Any) -> None:
        self.warnings.append(ValidationIssue("WARNING", code, message, **where))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "workbook_sha256": self.workbook_sha256,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [x.to_dict() for x in self.errors],
            "warnings": [x.to_dict() for x in self.warnings],
        }


REQUIRED_SHEETS: Tuple[str, ...] = (
    "Signals", "Signal_Atoms", "Atoms", "Terminology", "Buckets",
    "Combinations", "Combination_Requirements", "Requirement_Buckets",
    "Requirement_Tiers", "Requirement_Signals", "Priority_Policies",
    "Combination_Rules", "Combination_Rule_Groups", "Combination_Rule_Members", "Guardrails",
    "Algorithm_Contract", "Controlled_Vocabulary", "Clinical_Sources",
)

OPTIONAL_SHEETS: Tuple[str, ...] = (
    "README", "Change_Log", "Signal_Rules", "Signal_Rule_Groups",
    "Signal_Rule_Members", "Signal_Blockers",
)

# The mapping is deliberately explicit.  It prevents a same-named field from
# being silently accepted when its controlled vocabulary is different.
CATEGORY_COLUMNS: Dict[str, str] = {
    "Phenotype": "Phenotype",
    "Entity_Type": "Entity_Type",
    "Source_Type": "Source_Type",
    "Bucket_Class": "Bucket_Class",
    "Gate_Role": "Gate_Role",
    "Config_Action": "Config_Action",
    "Runtime_Executability": "Runtime_Executability",
    "Experiencer": "Experiencer",
    "Stage": "Stage",
    "Evidence_Stage": "Stage",
    "Requirement_Kind": "Requirement_Kind",
    "Priority_Class": "Priority_Class",
    "Outcome": "Outcome",
    "Top_Operator": "Rule_Group_Operator",
    "Operator": "Rule_Group_Operator",
    "Rule_Outcome": "Rule_Outcome",
    "Block_Action": "Block_Action",
}


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _norm(value).upper() in {"TRUE", "YES", "Y", "1"}


def _ids(rows: Sequence[Mapping[str, Any]], field: str, report: ValidationReport, sheet: str,
        *, composite: Optional[Sequence[str]] = None) -> Set[str]:
    seen: Dict[str, int] = {}
    result: Set[str] = set()
    for index, row in enumerate(rows, start=2):
        if composite:
            key = "|".join(_norm(row.get(x)) for x in composite)
        else:
            key = _norm(row.get(field))
        if not key or key.replace("|", "") == "":
            report.add_error("MISSING_PRIMARY_ID", f"Missing primary key {field}", sheet=sheet, row=index, field=field)
            continue
        if key in seen:
            report.add_error("DUPLICATE_PRIMARY_ID", f"Duplicate primary key {key!r}; first row {seen[key]}",
                              sheet=sheet, row=index, field=field)
        else:
            seen[key] = index
            result.add(key)
    return result


def _foreign_keys(rows: Sequence[Mapping[str, Any]], field: str, known: Set[str], report: ValidationReport,
                  sheet: str, *, allow_empty: bool = True) -> None:
    for index, row in enumerate(rows, start=2):
        value = _norm(row.get(field))
        if not value and allow_empty:
            continue
        if value not in known:
            report.add_error("INVALID_FOREIGN_KEY", f"{field}={value!r} is not defined", sheet=sheet,
                              row=index, field=field)


def _validate_categories(tables: Mapping[str, Sequence[Mapping[str, Any]]], report: ValidationReport,
                        vocab: Mapping[str, Set[str]]) -> None:
    for sheet, rows in tables.items():
        for index, row in enumerate(rows, start=2):
            # Algorithm_Contract.Stage is an execution-pipeline stage (for
            # example INPUT_CONTRACT), not the clinical evidence-stage enum.
            if sheet in {"Algorithm_Contract", "algorithm_contract"}:
                continue
            for field, vocabulary in CATEGORY_COLUMNS.items():
                if field not in row or row.get(field) in (None, ""):
                    continue
                # Combination_Rule_Members.Member_Type is a structural union. GROUP
                # is not a clinical value and is therefore accepted only here.
                if sheet == "Combination_Rule_Members" and field == "Member_Type":
                    allowed = set(vocab.get("Rule_Member_Type", set())) | {"GROUP"}
                else:
                    allowed = vocab.get(vocabulary)
                if allowed is None:
                    continue
                value = _norm(row.get(field))
                if value not in allowed:
                    report.add_error("UNKNOWN_CONTROLLED_VALUE",
                                     f"{field}={value!r} is not allowed by Controlled_Vocabulary[{vocabulary!r}]",
                                     sheet=sheet, row=index, field=field)


def validate_tables(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    workbook_sha256: Optional[str] = None,
    sheets_present: Optional[Iterable[str]] = None,
) -> ValidationReport:
    """Validate normalized tables and all required cross-sheet references."""
    report = ValidationReport(workbook_sha256=workbook_sha256)
    present = set(sheets_present or tables.keys())
    for sheet in REQUIRED_SHEETS:
        if sheet not in present:
            report.add_error("MISSING_REQUIRED_SHEET", f"Required workbook sheet {sheet!r} is missing", sheet=sheet)

    vocab_rows = tables.get("controlled_vocabulary", tables.get("Controlled_Vocabulary", []))
    vocab: Dict[str, Set[str]] = {}
    for row in vocab_rows:
        key = _norm(row.get("Vocabulary"))
        value = _norm(row.get("Allowed_Value"))
        if key and value:
            vocab.setdefault(key, set()).add(value)
    _validate_categories(tables, report, vocab)

    signals = tables.get("signals", tables.get("Signals", []))
    signal_atoms = tables.get("signal_atoms", tables.get("Signal_Atoms", []))
    atoms = tables.get("atoms", tables.get("Atoms", []))
    terminology = tables.get("terminology", tables.get("Terminology", []))
    buckets = tables.get("buckets", tables.get("Buckets", []))
    combinations = tables.get("combinations", tables.get("Combinations", []))
    requirements = tables.get("combination_requirements", tables.get("Combination_Requirements", []))
    req_buckets = tables.get("requirement_buckets", tables.get("Requirement_Buckets", []))
    req_tiers = tables.get("requirement_tiers", tables.get("Requirement_Tiers", []))
    req_signals = tables.get("requirement_signals", tables.get("Requirement_Signals", []))
    policies = tables.get("priority_policies", tables.get("Priority_Policies", []))
    combination_rules = tables.get("combination_rules", tables.get("Combination_Rules", []))
    combination_rule_groups = tables.get("combination_rule_groups", tables.get("Combination_Rule_Groups", []))
    combination_rule_members = tables.get("combination_rule_members", tables.get("Combination_Rule_Members", []))
    guardrails = tables.get("guardrails", tables.get("Guardrails", []))
    clinical_sources = tables.get("clinical_sources", tables.get("Clinical_Sources", []))

    signal_ids = _ids(signals, "Signal_ID", report, "Signals")
    atom_ids = _ids(atoms, "Atom_ID", report, "Atoms")
    combination_ids = _ids(combinations, "Combination_ID", report, "Combinations")
    requirement_ids = _ids(requirements, "Requirement_ID", report, "Combination_Requirements")
    bucket_keys = _ids(buckets, "Reasoning_Bucket", report, "Buckets", composite=("Phenotype", "Reasoning_Bucket"))
    policy_keys = _ids(policies, "Priority_Policy_ID", report, "Priority_Policies",
                       composite=("Priority_Policy_ID", "Tier_Pattern"))
    rule_ids = _ids(combination_rules, "Combination_ID", report, "Combination_Rules")
    group_keys = _ids(combination_rule_groups, "Group_ID", report, "Combination_Rule_Groups",
                      composite=("Combination_ID", "Group_ID"))
    source_ids = _ids(clinical_sources, "Source_ID", report, "Clinical_Sources")
    _ids(guardrails, "Guardrail_ID", report, "Guardrails")

    for row in signal_atoms:
        _foreign_keys([row], "Signal_ID", signal_ids, report, "Signal_Atoms")
        _foreign_keys([row], "Atom_ID", atom_ids, report, "Signal_Atoms")
    mappings_by_signal: Dict[str, Set[str]] = {}
    for row in signal_atoms:
        mappings_by_signal.setdefault(_norm(row.get("Signal_ID")), set()).add(_norm(row.get("Atom_ID")))
    for row in signals:
        display = set(_split_ids(row.get("Atom_IDs")))
        authoritative = mappings_by_signal.get(_norm(row.get("Signal_ID")), set())
        if display and display != authoritative:
            report.add_error(
                "REDUNDANT_MAPPING_MISMATCH",
                f"Signals.Atom_IDs disagrees with Signal_Atoms for {_norm(row.get('Signal_ID'))!r}",
                sheet="Signals", field="Atom_IDs",
            )
    for row in terminology:
        _foreign_keys([row], "Atom_ID", atom_ids, report, "Terminology")
    for row in signals:
        bucket = _norm(row.get("Reasoning_Bucket"))
        if bucket and f"{_norm(row.get('Phenotype'))}|{bucket}" not in bucket_keys:
            report.add_error("INVALID_FOREIGN_KEY", f"Reasoning_Bucket={bucket!r} is not defined for phenotype",
                             sheet="Signals", field="Reasoning_Bucket")
        for source_id in _split_ids(row.get("Clinical_Source_IDs")):
            if source_id not in source_ids:
                report.add_error("INVALID_FOREIGN_KEY", f"Clinical source {source_id!r} is not defined",
                                 sheet="Signals", field="Clinical_Source_IDs")
    for row in combinations:
        policy = _norm(row.get("Priority_Policy_ID"))
        if policy and not any(key.startswith(policy + "|") for key in policy_keys):
            report.add_error("INVALID_FOREIGN_KEY", f"Priority policy {policy!r} is not defined",
                             sheet="Combinations", field="Priority_Policy_ID")
    for row in combination_rules:
        _foreign_keys([row], "Combination_ID", combination_ids, report, "Combination_Rules", allow_empty=False)
        policy = _norm(row.get("Priority_Policy_ID"))
        if policy and not any(key.startswith(policy + "|") for key in policy_keys):
            report.add_error("INVALID_FOREIGN_KEY", f"Priority policy {policy!r} is not defined",
                             sheet="Combination_Rules", field="Priority_Policy_ID")
    for row in requirements:
        _foreign_keys([row], "Combination_ID", combination_ids, report, "Combination_Requirements")
    for rows, field, sheet in ((req_buckets, "Requirement_ID", "Requirement_Buckets"),
                               (req_tiers, "Requirement_ID", "Requirement_Tiers"),
                               (req_signals, "Requirement_ID", "Requirement_Signals")):
        _foreign_keys(rows, field, requirement_ids, report, sheet)
    for row in req_buckets:
        bucket = _norm(row.get("Reasoning_Bucket"))
        # Requirement_Buckets has no phenotype column; a bucket name is
        # valid when present in any phenotype row, but not when absent entirely.
        if bucket and not any(key.endswith("|" + bucket) for key in bucket_keys):
            report.add_error("INVALID_FOREIGN_KEY", f"Reasoning bucket {bucket!r} is not defined",
                             sheet="Requirement_Buckets", field="Reasoning_Bucket")
    for row in req_signals:
        _foreign_keys([row], "Allowed_Signal_ID", signal_ids, report, "Requirement_Signals")
    for row in combination_rule_groups:
        if _norm(row.get("Combination_ID")) not in rule_ids:
            report.add_error("INVALID_FOREIGN_KEY", "Combination group references absent nested rule",
                             sheet="Combination_Rule_Groups", field="Combination_ID")
    for row in combination_rule_members:
        key = f"{_norm(row.get('Combination_ID'))}|{_norm(row.get('Group_ID'))}"
        if key not in group_keys:
            report.add_error("INVALID_FOREIGN_KEY", "Combination rule member references absent group",
                             sheet="Combination_Rule_Members", field="Group_ID")
        member_type = _norm(row.get("Member_Type"))
        member_id = _norm(row.get("Member_ID"))
        if member_type == "SIGNAL" and member_id not in signal_ids:
            report.add_error("INVALID_FOREIGN_KEY", f"Combination rule signal {member_id!r} is absent",
                             sheet="Combination_Rule_Members", field="Member_ID")
        if member_type == "GROUP" and f"{_norm(row.get('Combination_ID'))}|{member_id}" not in group_keys:
            report.add_error("INVALID_FOREIGN_KEY", f"Combination rule group {member_id!r} is absent",
                             sheet="Combination_Rule_Members", field="Member_ID")

    requirements_by_combo = {_norm(row.get("Combination_ID")) for row in requirements}
    nested_rule_ids = {_norm(row.get("Combination_ID")) for row in combination_rules}
    for combination_id in combination_ids:
        has_flat = combination_id in requirements_by_combo
        has_nested = combination_id in nested_rule_ids
        if has_flat == has_nested:
            report.add_error(
                "AMBIGUOUS_COMBINATION_LOGIC",
                f"Combination {combination_id!r} must define exactly one of flat requirements or a nested combination rule",
                sheet="Combinations",
                field="Combination_ID",
            )
    for row in guardrails:
        for source_id in _split_ids(row.get("Clinical_Source_IDs")):
            if source_id not in source_ids:
                report.add_error("INVALID_FOREIGN_KEY", f"Clinical source {source_id!r} is not defined",
                                 sheet="Guardrails", field="Clinical_Source_IDs")

    # v2 contains a normalized signal-rule representation.  Validate it when
    # present without making older normalized workbooks silently authoritative.
    signal_rules = tables.get("signal_rules", tables.get("Signal_Rules", []))
    signal_rule_groups = tables.get("signal_rule_groups", tables.get("Signal_Rule_Groups", []))
    signal_rule_members = tables.get("signal_rule_members", tables.get("Signal_Rule_Members", []))
    signal_blockers = tables.get("signal_blockers", tables.get("Signal_Blockers", []))
    if signal_rules:
        _ids(signal_rules, "Signal_ID", report, "Signal_Rules")
        for row in signal_rules:
            _foreign_keys([row], "Signal_ID", signal_ids, report, "Signal_Rules")
            for source_id in _split_ids(row.get("Clinical_Source_IDs")):
                if source_id not in source_ids:
                    report.add_error("INVALID_FOREIGN_KEY", f"Clinical source {source_id!r} is not defined",
                                     sheet="Signal_Rules", field="Clinical_Source_IDs")
    rule_group_keys: Set[str] = set()
    if signal_rule_groups:
        rule_group_keys = _ids(signal_rule_groups, "Group_ID", report, "Signal_Rule_Groups",
                               composite=("Signal_ID", "Group_ID"))
        for row in signal_rule_groups:
            _foreign_keys([row], "Signal_ID", signal_ids, report, "Signal_Rule_Groups")
            parent = _norm(row.get("Parent_Group_ID"))
            if parent and f"{_norm(row.get('Signal_ID'))}|{parent}" not in rule_group_keys:
                report.add_error("INVALID_FOREIGN_KEY", f"Parent group {parent!r} is absent",
                                 sheet="Signal_Rule_Groups", field="Parent_Group_ID")
    for row in signal_rule_members:
        key = f"{_norm(row.get('Signal_ID'))}|{_norm(row.get('Group_ID'))}"
        if rule_group_keys and key not in rule_group_keys:
            report.add_error("INVALID_FOREIGN_KEY", "Signal rule member references absent group",
                             sheet="Signal_Rule_Members", field="Group_ID")
        if _norm(row.get("Member_Type")) == "ATOM" and _norm(row.get("Member_ID")) not in atom_ids:
            report.add_error("INVALID_FOREIGN_KEY", "Signal rule member references absent atom",
                             sheet="Signal_Rule_Members", field="Member_ID")
        if _norm(row.get("Member_Type")) == "SIGNAL" and _norm(row.get("Member_ID")) not in signal_ids:
            report.add_error("INVALID_FOREIGN_KEY", "Signal rule member references absent signal",
                             sheet="Signal_Rule_Members", field="Member_ID")
    for row in signal_blockers:
        _foreign_keys([row], "Signal_ID", signal_ids, report, "Signal_Blockers")
        _foreign_keys([row], "Atom_ID", atom_ids, report, "Signal_Blockers")
        for source_id in _split_ids(row.get("Clinical_Source_IDs")):
            if source_id not in source_ids:
                report.add_error("INVALID_FOREIGN_KEY", f"Clinical source {source_id!r} is not defined",
                                 sheet="Signal_Blockers", field="Clinical_Source_IDs")

    return report


def _split_ids(value: Any) -> List[str]:
    if value is None:
        return []
    return [part.strip() for part in str(value).replace(",", ";").split(";") if part.strip()]


def validate_or_raise(report: ValidationReport) -> ValidationReport:
    if not report.valid:
        first = report.errors[0]
        raise ConfigValidationError(
            f"Workbook configuration validation failed ({len(report.errors)} error(s)); "
            f"first: {first.code}: {first.message}", report
        )
    return report


def validate_config(config_or_tables: Any, **kwargs: Any) -> ValidationReport:
    """Validate either raw tables or a loaded ``RuntimeConfig`` object."""
    tables = getattr(config_or_tables, "tables", config_or_tables)
    workbook_hash = kwargs.pop("workbook_sha256", getattr(config_or_tables, "workbook_hash", None))
    return validate_tables(tables, workbook_sha256=workbook_hash, **kwargs)

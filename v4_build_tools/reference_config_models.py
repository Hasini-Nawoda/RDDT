"""Typed, workbook-derived configuration models for RDDT V4.

The models deliberately contain no ATTRv defaults.  Every clinical value is
loaded into the runtime from compiled JSON emitted by the build compiler and retains its
source workbook hash and row number for auditability.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, Mapping, Optional


def _json_value(value: Any) -> Any:
    """Return a JSON-safe value while keeping workbook values lossless."""
    if hasattr(value, "isoformat") and not isinstance(value, (str, bytes)):
        try:
            return value.isoformat()
        except (AttributeError, TypeError, ValueError):
            pass
    if isinstance(value, Mapping):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(v) for v in value]
    return value


@dataclass
class WorkbookRow:
    """A row retained with its workbook provenance."""

    values: Dict[str, Any]
    sheet: str
    row_number: int
    workbook_hash: str

    def to_dict(self) -> Dict[str, Any]:
        data = dict(self.values)
        data["_source_sheet"] = self.sheet
        data["_source_row"] = self.row_number
        data["_workbook_hash"] = self.workbook_hash
        return _json_value(data)


@dataclass
class TerminologyConfig:
    atom_id: str
    terminology_system: str
    value: Any
    value_class: Optional[str] = None
    review_status: Optional[str] = None
    can_fire_atom_alone: Optional[bool] = None
    context_guard: Optional[str] = None
    source_sheet: str = "Terminology"
    source_row: Optional[int] = None
    workbook_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _json_value(asdict(self))


@dataclass
class AtomConfig:
    atom_id: str
    preferred_clinical_name: str
    source_type: Optional[str] = None
    source_specialty: Optional[str] = None
    source_subdomain: Optional[str] = None
    experiencer: Optional[str] = None
    stage: Optional[str] = None
    clinical_meaning: Optional[str] = None
    context_guard: Optional[str] = None
    contributing_signals: List[str] = field(default_factory=list)
    extraction_pattern: Optional[str] = None
    terminology: List[TerminologyConfig] = field(default_factory=list)
    source_sheet: str = "Atoms"
    source_row: Optional[int] = None
    workbook_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["terminology"] = [item.to_dict() for item in self.terminology]
        return _json_value(data)


@dataclass
class SignalAtomMapping:
    phenotype: str
    signal_id: str
    atom_id: str
    atom_preferred_name: Optional[str] = None
    experiencer: Optional[str] = None
    stage: Optional[str] = None
    required_qualifiers: Optional[str] = None
    signal_logic: Optional[str] = None
    runtime_executability: Optional[str] = None
    execution_block_reason: Optional[str] = None
    evidence_mode: Optional[str] = None
    can_fire_from_this_mapping: Optional[bool] = None
    source_row: Optional[int] = None
    workbook_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _json_value(asdict(self))


@dataclass
class SignalConfig:
    phenotype: str
    signal_id: str
    clinical_feature: str
    entity_type: Optional[str] = None
    source_type: Optional[str] = None
    source_specialty: Optional[str] = None
    source_subdomain: Optional[str] = None
    reasoning_bucket: Optional[str] = None
    bucket_class: Optional[str] = None
    tier: Optional[int] = None
    gate_role: Optional[str] = None
    config_action: Optional[str] = None
    canonical_dedup_group: Optional[str] = None
    algorithm_role: Optional[str] = None
    evidence_stage: Optional[str] = None
    runtime_executability: Optional[str] = None
    execution_block_reason: Optional[str] = None
    evidence_mode: Optional[str] = None
    atom_ids_display: List[str] = field(default_factory=list)
    clinical_logic: Optional[str] = None
    required_qualifiers: Optional[str] = None
    guardrail_notes: Optional[str] = None
    combination_ids_display: List[str] = field(default_factory=list)
    enabled: bool = True
    clinical_source_ids: List[str] = field(default_factory=list)
    mappings: List[SignalAtomMapping] = field(default_factory=list)
    source_row: Optional[int] = None
    workbook_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["mappings"] = [item.to_dict() for item in self.mappings]
        return _json_value(data)


@dataclass
class RequirementConfig:
    phenotype: str
    requirement_id: str
    combination_id: str
    requirement_order: int
    requirement_kind: str
    minimum_count: Optional[int] = None
    context_witness_allowed: bool = False
    distinct_lineage_required: bool = True
    notes: Optional[str] = None
    allowed_buckets: List[str] = field(default_factory=list)
    allowed_tiers: List[int] = field(default_factory=list)
    allowed_signal_ids: List[str] = field(default_factory=list)
    source_row: Optional[int] = None
    workbook_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _json_value(asdict(self))


@dataclass
class CombinationConfig:
    phenotype: str
    combination_id: str
    outcome: Optional[str] = None
    result_route: Optional[str] = None
    priority_policy_id: Optional[str] = None
    clinical_rationale: Optional[str] = None
    validation_class: Optional[str] = None
    enabled: bool = True
    origin: Optional[str] = None
    temporal_policy: Optional[str] = None
    notes: Optional[str] = None
    requirements: List[RequirementConfig] = field(default_factory=list)
    source_row: Optional[int] = None
    workbook_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["requirements"] = [item.to_dict() for item in self.requirements]
        return _json_value(data)


@dataclass
class CombinationRuleMemberConfig:
    combination_id: str
    group_id: str
    member_type: str
    member_id: str
    source_row: Optional[int] = None
    workbook_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _json_value(asdict(self))


@dataclass
class CombinationRuleGroupConfig:
    combination_id: str
    group_id: str
    evaluation_order: int
    operator: str
    minimum_count: Optional[int] = None
    require_independent_lineage: bool = False
    notes: Optional[str] = None
    members: List[CombinationRuleMemberConfig] = field(default_factory=list)
    source_row: Optional[int] = None
    workbook_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["members"] = [item.to_dict() for item in self.members]
        return _json_value(data)


@dataclass
class CombinationRuleConfig:
    phenotype: str
    combination_id: str
    top_operator: str
    definition: Optional[str] = None
    priority_policy_id: Optional[str] = None
    enabled: bool = True
    groups: List[CombinationRuleGroupConfig] = field(default_factory=list)
    source_row: Optional[int] = None
    workbook_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["groups"] = [item.to_dict() for item in self.groups]
        return _json_value(data)


@dataclass
class RuntimeConfig:
    """Loaded compiled configuration with convenient keyed lookups."""

    manifest: Dict[str, Any]
    tables: Dict[str, List[Dict[str, Any]]]
    root: Optional[str] = None

    @property
    def workbook_hash(self) -> str:
        return str(self.manifest.get("workbook_sha256", ""))

    @property
    def compiled_config_hash(self) -> str:
        return str(self.manifest.get("compiled_config_sha256", ""))

    @property
    def phenotype(self) -> str:
        return str(self.manifest.get("phenotype", "ATTRV"))

    def rows(self, table: str) -> List[Dict[str, Any]]:
        return list(self.tables.get(table, []))

    def keyed(self, table: str, key: str) -> Dict[str, Dict[str, Any]]:
        return {str(row[key]): row for row in self.rows(table) if row.get(key) is not None}

    @property
    def signals(self) -> Dict[str, Dict[str, Any]]:
        return self.keyed("signals", "signal_id")

    @property
    def atoms(self) -> Dict[str, Dict[str, Any]]:
        return self.keyed("atoms", "atom_id")

    @property
    def combinations(self) -> Dict[str, Dict[str, Any]]:
        return self.keyed("combinations", "combination_id")

    @property
    def buckets(self) -> Dict[str, Dict[str, Any]]:
        return {str(row.get("reasoning_bucket")): row for row in self.rows("buckets") if row.get("reasoning_bucket")}

    def get_signal(self, signal_id: str) -> Optional[Dict[str, Any]]:
        return self.signals.get(str(signal_id))

    def get_atom(self, atom_id: str) -> Optional[Dict[str, Any]]:
        return self.atoms.get(str(atom_id))

    def get_combination(self, combination_id: str) -> Optional[Dict[str, Any]]:
        return self.combinations.get(str(combination_id))

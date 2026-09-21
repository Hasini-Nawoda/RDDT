"""In-memory view of one clean V4 clinical configuration package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class RuntimeConfig:
    """Clinical configuration after the clean nested JSON has been adapted.

    The checked-in JSON is intentionally organized for clinicians and
    maintainers. ``tables`` is the normalized, in-memory adapter view used by
    the existing execution engines; it is never written back to the package.
    """

    phenotype_name: str
    tables: Dict[str, List[Dict[str, Any]]]
    config_hash: str
    schema_version: str = "v4-clinical-config-v1"
    root: Optional[str] = None

    @property
    def phenotype(self) -> str:
        return self.phenotype_name

    @property
    def package_schema(self) -> str:
        return self.schema_version

    @property
    def package_path(self) -> Optional[str]:
        return self.root

    def rows(self, table: str) -> List[Dict[str, Any]]:
        return list(self.tables.get(table, []))

    def keyed(self, table: str, key: str) -> Dict[str, Dict[str, Any]]:
        return {str(row[key]): row for row in self.rows(table) if row.get(key) is not None}

    @property
    def signals(self) -> Dict[str, Dict[str, Any]]:
        return self.keyed("signals", "signal_id")

    @property
    def signal_catalog(self) -> Dict[str, Dict[str, Any]]:
        """All configured signal rows, including route-only/guardrail rows.

        ``signals`` remains the executable direct-signal view consumed by the
        signal engine. The catalog remains separate so guardrail and
        DO_NOT_TRIGGER rows stay available for provenance and validation.
        """
        return self.keyed("signals_catalog", "signal_id")

    @property
    def catalog_signals(self) -> Dict[str, Dict[str, Any]]:
        return self.signal_catalog

    @property
    def atoms(self) -> Dict[str, Dict[str, Any]]:
        return self.keyed("atoms", "atom_id")

    @property
    def combinations(self) -> Dict[str, Dict[str, Any]]:
        return self.keyed("combinations", "combination_id")

    @property
    def buckets(self) -> Dict[str, Dict[str, Any]]:
        return {
            str(row["reasoning_bucket"]): row
            for row in self.rows("buckets")
            if row.get("reasoning_bucket") is not None
        }

    def get_signal(self, signal_id: str) -> Optional[Dict[str, Any]]:
        return self.signals.get(str(signal_id))

    def get_atom(self, atom_id: str) -> Optional[Dict[str, Any]]:
        return self.atoms.get(str(atom_id))

    def get_combination(self, combination_id: str) -> Optional[Dict[str, Any]]:
        return self.combinations.get(str(combination_id))


__all__ = ["RuntimeConfig"]

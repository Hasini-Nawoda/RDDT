"""Step 01 — load the compiled contract and validate warehouse sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..config_loader import DEFAULT_COMPILED_DIR, load_compiled_config
from ..warehouse.source_schema import default_source_config, validate_source_schema


def load_config(*, config_dir: str | None = None, phenotype: str) -> Any:
    """Load the checked-in JSON runtime config; Excel is never read here."""
    root = Path(config_dir).expanduser().resolve() if config_dir is not None else Path(DEFAULT_COMPILED_DIR)
    return load_compiled_config(root, phenotype=phenotype)


def validate_sources(session: Any, source_config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate the declared Snowflake source contract before querying patient data."""
    return validate_source_schema(session, source_config or default_source_config(), raise_on_error=True)


__all__ = ["load_config", "validate_sources"]

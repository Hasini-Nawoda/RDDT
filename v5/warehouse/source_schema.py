"""Physical Snowflake source contract for V4.

This module intentionally contains no ATTRv vocabulary.  It describes only the
warehouse tables and columns supplied by the existing EHR data dictionary.
All created objects are expected to be temporary and run-scoped.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


class SourceSchemaError(RuntimeError):
    """Raised when the physical source schema cannot satisfy the contract."""


@dataclass(frozen=True)
class SourceTable:
    key: str
    name: str
    columns: Mapping[str, str]
    required_columns: tuple[str, ...] = ()
    enabled: bool = True
    required: bool = True
    # Profile hydration is intentionally independent from algorithmic source
    # participation.  The screening engine may only need CLAIMS while a
    # patient profile still needs the patient's rows from every available EHR
    # table.  These defaults preserve the historical SourceTable behavior for
    # callers that construct the dataclass directly.
    profile_enabled: bool = True
    profile_required: bool = False

    @property
    def physical_columns(self) -> tuple[str, ...]:
        return tuple(self.columns[key] for key in self.required_columns)


@dataclass
class SourceValidationReport:
    tables_checked: list[str] = field(default_factory=list)
    optional_disabled: list[str] = field(default_factory=list)
    missing_tables: list[str] = field(default_factory=list)
    missing_columns: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.missing_tables and not self.missing_columns

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tables_checked": list(self.tables_checked),
            "optional_disabled": list(self.optional_disabled),
            "missing_tables": list(self.missing_tables),
            "missing_columns": {k: list(v) for k, v in self.missing_columns.items()},
            "errors": list(self.errors),
        }


# This file is intentionally separate from the clinical phenotype package. It
# is the one operator-editable contract for physical source tables. Each
# ``columns`` entry maps a stable logical pipeline field to its physical name.
DEFAULT_SOURCE_CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "source_schema.json"
)
SOURCE_PROFILE_ENV = "V4_SOURCE_SCHEMA_PROFILE"


def _config_bool(value: Any, *, default: bool, field_name: str) -> bool:
    """Parse JSON/config booleans without treating ``"false"`` as true."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "on", "1"}:
            return True
        if normalized in {"false", "no", "n", "off", "0"}:
            return False
    raise SourceSchemaError(
        f"{field_name} must be a boolean; received {value!r}"
    )


def _select_profile(
    raw: Mapping[str, Any],
    *,
    profile: str | None,
    path: Path,
) -> tuple[Mapping[str, Any], str | None, tuple[str, ...]]:
    """Select one operator-facing physical schema profile.

    A profile file keeps the active warehouse mapping and the previous
    mapping together.  This is intentionally resolved before normalization so
    every downstream consumer still receives the same ``tables`` contract.
    ``V4_SOURCE_SCHEMA_PROFILE`` is useful in Snowflake worksheets; callers
    can pass ``profile`` directly in tests or deployment code.
    """
    profiles = raw.get("profiles")
    if not isinstance(profiles, Mapping):
        return raw, None, ()
    available = tuple(str(key) for key in profiles)
    requested = profile or os.environ.get(SOURCE_PROFILE_ENV) or raw.get("active_profile")
    if not requested:
        raise SourceSchemaError(
            f"schema profile is required; choose one of {available!r}: {path}"
        )
    selected = profiles.get(str(requested))
    if not isinstance(selected, Mapping):
        raise SourceSchemaError(
            f"unknown source schema profile {requested!r}; choose one of {available!r}: {path}"
        )
    return selected, str(requested), available


def _normalize_source_config(
    raw: Mapping[str, Any],
    *,
    path: Path,
    profile: str | None = None,
) -> dict[str, Any]:
    """Normalize and validate the external source-schema contract.

    Logical keys (``patient_id``, ``diagnosis_code``, etc.) are the stable
    pipeline interface. Their values are the physical columns in the source
    table. Keeping this conversion here means downstream extraction code never
    needs to know which warehouse naming convention is currently in use.
    """
    if not isinstance(raw, Mapping):
        raise SourceSchemaError(f"source schema config must be an object: {path}")
    selected, selected_profile, available_profiles = _select_profile(
        raw, profile=profile, path=path
    )
    tables = selected.get("tables", selected)
    if not isinstance(tables, Mapping) or not tables:
        raise SourceSchemaError(f"source schema config has no tables: {path}")

    normalized_tables: dict[str, dict[str, Any]] = {}
    for key, value in tables.items():
        if not isinstance(value, Mapping):
            raise SourceSchemaError(f"source table {key!r} must be an object: {path}")
        table_key = str(key)
        name = str(value.get("name", "")).strip()
        columns = value.get("columns", {})
        if not name:
            raise SourceSchemaError(f"source table {table_key!r} has no physical name: {path}")
        enabled = _config_bool(
            value.get("enabled"), default=True, field_name=f"{table_key}.enabled"
        )
        if not isinstance(columns, Mapping) or (not columns and enabled):
            raise SourceSchemaError(f"source table {table_key!r} has no column mapping: {path}")
        required_columns = value.get("required_columns", ())
        if isinstance(required_columns, str) or not isinstance(required_columns, (list, tuple)):
            raise SourceSchemaError(
                f"source table {table_key!r}.required_columns must be a list: {path}"
            )
        missing_mappings = [logical for logical in required_columns if logical not in columns]
        if missing_mappings:
            raise SourceSchemaError(
                f"source table {table_key!r} has no mapping for required logical fields "
                f"{missing_mappings!r}: {path}"
            )
        normalized_tables[table_key] = {
            "key": str(value.get("key", table_key)),
            "name": name,
            "enabled": enabled,
            "required": _config_bool(
                value.get("required"), default=True, field_name=f"{table_key}.required"
            ),
            # Older schema profiles did not distinguish algorithm inputs from
            # profile hydration inputs.  Falling back to the corresponding
            # legacy flags keeps those profiles behavior-compatible while
            # allowing current profiles to opt into additional EHR tables.
            "profile_enabled": _config_bool(
                value.get("profile_enabled"),
                default=enabled,
                field_name=f"{table_key}.profile_enabled",
            ),
            "profile_required": _config_bool(
                value.get("profile_required"),
                default=_config_bool(
                    value.get("required"),
                    default=True,
                    field_name=f"{table_key}.required",
                ),
                field_name=f"{table_key}.profile_required",
            ),
            "columns": {str(logical): str(physical) for logical, physical in columns.items()},
            "required_columns": tuple(str(logical) for logical in required_columns),
        }
    return {
        "schema_version": str(
            selected.get("schema_version", raw.get("schema_version", "v4-source-schema-v1"))
        ),
        "namespace": selected.get("namespace", raw.get("namespace")),
        "profile": selected_profile,
        "available_profiles": available_profiles,
        "tables": normalized_tables,
    }


def load_source_config(
    path: str | Path | None = None,
    *,
    profile: str | None = None,
) -> dict[str, Any]:
    """Load the operator-editable physical source mapping.

    ``path`` is useful for a deployment-specific mapping or tests. With no
    path, the checked-in ``config/source_schema.json`` is used. The file is
    required so table selection and schema mapping always have one visible
    source of truth.
    """
    config_path = Path(path) if path is not None else DEFAULT_SOURCE_CONFIG_PATH
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SourceSchemaError(f"missing source schema config: {config_path}")
    except json.JSONDecodeError as exc:
        raise SourceSchemaError(f"invalid JSON in source schema config: {config_path}") from exc
    return _normalize_source_config(raw, path=config_path, profile=profile)


def default_source_config(*, profile: str | None = None) -> dict[str, Any]:
    """Return the checked-in, operator-editable source schema contract."""
    return load_source_config(profile=profile)


def is_table_enabled(table: Mapping[str, Any], *, default: bool = True) -> bool:
    """Return a source table's toggle using strict config boolean semantics."""
    return _config_bool(
        table.get("enabled"),
        default=default,
        field_name=f"{table.get('key', table.get('name', 'source_table'))}.enabled",
    )


def is_table_profile_enabled(
    table: Mapping[str, Any], *, default: bool | None = None
) -> bool:
    """Return whether a table should hydrate patient profiles.

    ``profile_enabled`` is deliberately separate from ``enabled``: a table
    can be excluded from phenotype extraction and still contribute complete
    patient-level EHR records.  For legacy mappings without the new flag, the
    algorithm toggle remains the compatibility fallback.
    """
    if default is None:
        default = is_table_enabled(table)
    return _config_bool(
        table.get("profile_enabled"),
        default=default,
        field_name=f"{table.get('key', table.get('name', 'source_table'))}.profile_enabled",
    )


def is_table_profile_required(
    table: Mapping[str, Any], *, default: bool | None = None
) -> bool:
    """Return whether a profile-enabled table is required for completeness.

    As with :func:`is_table_profile_enabled`, old mappings inherit the legacy
    ``required`` flag when ``profile_required`` is absent.
    """
    if default is None:
        default = _config_bool(
            table.get("required"),
            default=True,
            field_name=f"{table.get('key', table.get('name', 'source_table'))}.required",
        )
    return _config_bool(
        table.get("profile_required"),
        default=default,
        field_name=f"{table.get('key', table.get('name', 'source_table'))}.profile_required",
    )


def _tables(config: Mapping[str, Any]) -> Mapping[str, Any]:
    return config.get("tables", config)


def quote_identifier(identifier: str) -> str:
    """Quote a Snowflake identifier, including names containing slash/space."""
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("identifier must be a non-empty string")
    return '"' + identifier.replace('"', '""') + '"'


def qualified_table_name(table: Mapping[str, Any], namespace: str | None = None) -> str:
    parts = []
    if namespace:
        parts.extend(quote_identifier(part) for part in namespace.split("."))
    parts.append(quote_identifier(str(table["name"])))
    return ".".join(parts)


def _table_columns_from_session(session: Any, table_name: str) -> set[str] | None:
    """Read columns from common Snowpark/test-double interfaces."""
    try:
        obj = session.table(table_name)
        cols = getattr(obj, "columns", None)
        if cols is not None:
            return {str(c).strip('"') for c in cols}
        schema = getattr(obj, "schema", None)
        names = getattr(schema, "names", None)
        if names is not None:
            return {str(c).strip('"') for c in names}
    except Exception:
        pass
    return None


def validate_source_schema(session: Any, source_config: Mapping[str, Any] | None = None, *, raise_on_error: bool = True) -> SourceValidationReport:
    """Validate required physical tables/columns without creating permanent objects."""
    config = source_config or default_source_config()
    report = SourceValidationReport()
    namespace = config.get("namespace")
    for key, raw in _tables(config).items():
        enabled = is_table_enabled(raw)
        required = _config_bool(
            raw.get("required"),
            default=True,
            field_name=f"{key}.required",
        )
        if not enabled:
            report.optional_disabled.append(key)
            continue
        name = str(raw.get("name", ""))
        report.tables_checked.append(name)
        try:
            resolved_name = qualified_table_name(raw, str(namespace)) if namespace else name
            table_obj = session.table(resolved_name)
            cols = _table_columns_from_session(session, resolved_name)
            if cols is None:
                # A real Snowpark table may expose schema only after collect().
                schema = getattr(table_obj, "schema", None)
                if callable(schema):
                    schema = schema()
                names = getattr(schema, "names", None)
                if names:
                    cols = {str(c).strip('"') for c in names}
            if cols is None:
                report.errors.append(f"{key}: unable to inspect columns for {name}")
                continue
            expected = {str(raw["columns"][logical]) for logical in raw.get("required_columns", ())}
            missing = sorted(expected - cols)
            if missing:
                report.missing_columns[key] = missing
        except Exception as exc:
            if required:
                report.missing_tables.append(name)
            else:
                report.errors.append(f"{key}: optional table inspection failed: {exc}")
    if raise_on_error and not report.ok:
        raise SourceSchemaError(f"source schema validation failed: {report.as_dict()}")
    return report


__all__ = [
    "SourceSchemaError", "SourceTable", "SourceValidationReport", "default_source_config",
    "load_source_config", "is_table_enabled", "quote_identifier", "qualified_table_name",
    "is_table_profile_enabled", "is_table_profile_required",
    "SOURCE_PROFILE_ENV",
    "validate_source_schema",
]

"""Small, phenotype-agnostic helpers shared by the V4 reasoning stages.

This module intentionally contains no clinical identifiers.  It provides the
mechanical parts of the evaluator: three-valued logic, deterministic lineage
normalisation and tolerant access to compiled config records.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from hashlib import sha256
import json
import weakref
from typing import Any, Iterable, Mapping, Sequence


TRUE = "TRUE"
FALSE = "FALSE"
UNKNOWN = "UNKNOWN"


def value(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field from a dict/dataclass/object using common spellings."""
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        if name in obj:
            return obj[name]
        # The workbook compiler's generic header normalizer splits the
        # acronym ``ID`` as ``i_d``.  Treat both spellings as the same field
        # without changing the compiler's deterministic output.
        aliases = [name]
        if name.endswith("_id"):
            aliases.append(name[:-3] + "_i_d")
        elif name.endswith("_i_d"):
            aliases.append(name[:-4] + "_id")
        for alias in aliases[1:]:
            if alias in obj:
                return obj[alias]
        alt = name.lower() if name not in obj else name
        if alt in obj:
            return obj[alt]
        alt = name.upper()
        if alt in obj:
            return obj[alt]
        return default
    if hasattr(obj, name):
        return getattr(obj, name)
    for candidate in (name.lower(), name.upper()):
        if hasattr(obj, candidate):
            return getattr(obj, candidate)
    return default


def row_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, Mapping):
        return dict(obj)
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "model_dump"):
        return dict(obj.model_dump())
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    return {}


def rows(config: Any, name: str) -> list[Any]:
    """Read a config collection from a bundle or a model.

    Compilers in different integrations expose either plural attributes or a
    ``tables`` mapping.  Keeping that adapter here prevents clinical values
    from leaking into each engine module.
    """
    candidates = [name, name.lower(), name.upper()]
    if not name.endswith("s"):
        candidates += [name + "s", name.lower() + "s"]
    # Prefer the raw compiled tables when available.  RuntimeConfig also
    # exposes keyed convenience properties, but those assume unsplit ``*_id``
    # column names and can otherwise hide valid rows.
    raw_tables = getattr(config, "tables", None)
    if isinstance(raw_tables, Mapping):
        for candidate in candidates:
            if candidate in raw_tables:
                got = raw_tables[candidate]
                return list(got.values()) if isinstance(got, Mapping) else list(got)
    for candidate in candidates:
        got = value(config, candidate, None)
        if got is not None:
            if isinstance(got, Mapping):
                return list(got.values())
            return list(got)
    tables = value(config, "tables", {}) or {}
    if isinstance(tables, Mapping):
        for candidate in candidates:
            if candidate in tables:
                got = tables[candidate]
                return list(got.values()) if isinstance(got, Mapping) else list(got)
    return []


_GROUPED_ROWS: dict[int, tuple[weakref.ref, dict[tuple[str, str], dict[str, list[Any]]]]] = {}


def grouped_rows(config: Any, table: str, key_field: str) -> dict[str, list[Any]]:
    """Index one config table by a field, once per config object.

    Signal and combination lookup used to copy the whole table for every
    patient. The grouped lists keep workbook order. Config objects are not
    hashed: a phenotype package compares equal by value and cannot be a
    dictionary key.
    """
    cache_key = (table, key_field)
    per_config: dict[tuple[str, str], dict[str, list[Any]]] | None = None
    try:
        holder = weakref.ref(config)
    except TypeError:
        holder = None
    if holder is not None:
        slot = _GROUPED_ROWS.get(id(config))
        if slot is not None and slot[0]() is config:
            per_config = slot[1]
        else:
            per_config = {}
            _GROUPED_ROWS[id(config)] = (holder, per_config)
        grouped = per_config.get(cache_key)
        if grouped is not None:
            return grouped
    grouped = {}
    for row in rows(config, table):
        grouped.setdefault(str(value(row, key_field, "")), []).append(row)
    if per_config is not None:
        per_config[cache_key] = grouped
    return grouped


def configured_phenotype(config: Any, requested: str | None = None) -> str:
    """Resolve the selected phenotype from a package without a clinical default."""
    manifest = value(config, "manifest", {}) or {}
    declared = value(config, "phenotype", None) or value(manifest, "phenotype", None)
    selected = str(requested or declared or "").upper()
    if not selected:
        raise ValueError("Phenotype is required and the configuration does not declare one")
    if declared and selected != str(declared).upper():
        raise ValueError(
            f"Requested phenotype {selected!r} does not match configuration {str(declared).upper()!r}"
        )
    return selected


def index_by(items: Iterable[Any], field: str) -> dict[Any, Any]:
    out: dict[Any, Any] = {}
    for item in items:
        key = value(item, field)
        if key is not None:
            out[key] = item
    return out


def as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    if isinstance(v, (list, tuple, set, frozenset)):
        return list(v)
    if isinstance(v, str):
        s = v.strip()
        if not s or s.lower() in {"none", "null", "nan"}:
            return []
        if s.startswith("["):
            try:
                loaded = json.loads(s)
                return list(loaded) if isinstance(loaded, list) else [loaded]
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        return [x.strip() for x in s.replace(";", ",").split(",") if x.strip()]
    return [v]


def norm_status(v: Any) -> str:
    if isinstance(v, Enum):
        v = v.value
    s = str(v or UNKNOWN).upper().strip()
    return s if s in {TRUE, FALSE, UNKNOWN} else UNKNOWN


def tri_all(statuses: Iterable[Any]) -> str:
    vals = [norm_status(s) for s in statuses]
    if any(s == FALSE for s in vals):
        return FALSE
    if vals and all(s == TRUE for s in vals):
        return TRUE
    return UNKNOWN


def tri_any(statuses: Iterable[Any]) -> str:
    vals = [norm_status(s) for s in statuses]
    if any(s == TRUE for s in vals):
        return TRUE
    if vals and all(s == FALSE for s in vals):
        return FALSE
    return UNKNOWN


def tri_at_least(statuses: Iterable[Any], minimum: int) -> str:
    vals = [norm_status(s) for s in statuses]
    if sum(s == TRUE for s in vals) >= int(minimum):
        return TRUE
    if sum(s in {TRUE, UNKNOWN} for s in vals) < int(minimum):
        return FALSE
    return UNKNOWN


def lineage_set(obj: Any, field: str = "support_lineage_ids") -> frozenset[str]:
    vals = value(obj, field, None)
    if vals is None and field.startswith("support_"):
        vals = value(obj, "support_lineage", None)
    if isinstance(vals, str):
        vals = [x.strip() for x in vals.replace(";", ",").split(",") if x.strip()]
    return frozenset(str(x) for x in (vals or []) if x is not None and str(x) != "")


def union_lineage(items: Iterable[Any], field: str = "support_lineage_ids") -> tuple[str, ...]:
    out: set[str] = set()
    for item in items:
        out.update(lineage_set(item, field))
    return tuple(sorted(out))


def dedup_key(obj: Any) -> str | None:
    v = value(obj, "canonical_dedup_group", None)
    return None if v in (None, "", "NONE", "None") else str(v)


def independent(a: Any, b: Any, *, require_bucket: bool = False) -> bool:
    la = lineage_set(a)
    lb = lineage_set(b)
    if la and lb and la.intersection(lb):
        return False
    da, db = dedup_key(a), dedup_key(b)
    if da and db and da == db:
        return False
    if require_bucket:
        ba, bb = value(a, "reasoning_bucket"), value(b, "reasoning_bucket")
        if ba and bb and ba == bb:
            return False
    return True


def stable_id(*parts: Any) -> str:
    payload = "|".join("" if p is None else str(p) for p in parts)
    return sha256(payload.encode("utf-8")).hexdigest()[:24]


def explain(status: str, reason: str, **extra: Any) -> dict[str, Any]:
    out = {"status": norm_status(status), "reason": reason}
    out.update(extra)
    return out

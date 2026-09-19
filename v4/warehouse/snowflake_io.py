"""Small Snowpark/session adapter used by the V4 stages.

The adapter deliberately creates only ``TEMPORARY`` run-scoped tables.  It
does not contain clinical SQL or vocabulary; callers supply typed rows and
column definitions derived from the workbook/config contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .source_schema import quote_identifier


class SnowflakeIOError(RuntimeError):
    pass


@dataclass(frozen=True)
class TempTableSpec:
    name: str
    columns: tuple[tuple[str, str], ...]

    def ddl(self) -> str:
        if not self.columns:
            raise ValueError("temporary table requires at least one column")
        cols = ", ".join(f"{quote_identifier(name)} {sql_type}" for name, sql_type in self.columns)
        return f"CREATE OR REPLACE TEMPORARY TABLE {quote_identifier(self.name)} ({cols})"


def _collect(result: Any) -> list[Any]:
    if result is None:
        return []
    if hasattr(result, "collect"):
        return list(result.collect())
    if isinstance(result, list):
        return result
    return list(result) if isinstance(result, Iterable) and not isinstance(result, (str, bytes, Mapping)) else [result]


def execute(session: Any, sql: str, params: Sequence[Any] | None = None) -> list[Any]:
    """Execute SQL through a Snowpark-like session, returning collected rows."""
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql must be non-empty")
    try:
        query = session.sql(sql, params) if params is not None else session.sql(sql)
        return _collect(query)
    except TypeError:
        # Lightweight test doubles often accept only ``sql(text)``.
        query = session.sql(sql)
        return _collect(query)
    except Exception as exc:
        raise SnowflakeIOError(f"Snowflake statement failed: {exc}") from exc


def create_temp_table(session: Any, spec: TempTableSpec) -> None:
    execute(session, spec.ddl())


def drop_temp_table(session: Any, name: str) -> None:
    execute(session, f"DROP TABLE IF EXISTS {quote_identifier(name)}")


def create_run_table(session: Any, name: str, columns: Mapping[str, str]) -> TempTableSpec:
    """Create a temporary table from an ordered column mapping."""
    spec = TempTableSpec(name, tuple((str(k), str(v)) for k, v in columns.items()))
    create_temp_table(session, spec)
    return spec


def insert_rows(session: Any, table_name: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> int:
    """Insert rows using bound parameters where the session supports them."""
    if not columns:
        raise ValueError("columns must be non-empty")
    if not rows:
        return 0
    placeholders = ", ".join("?" for _ in columns)
    sql = f"INSERT INTO {quote_identifier(table_name)} ({', '.join(quote_identifier(c) for c in columns)}) VALUES ({placeholders})"
    count = 0
    for row in rows:
        if len(row) != len(columns):
            raise ValueError("row length does not match columns")
        execute(session, sql, tuple(row))
        count += 1
    return count


def fetch_rows(session: Any, table_name: str, columns: Sequence[str] | None = None) -> list[dict[str, Any]]:
    selected = "*" if not columns else ", ".join(quote_identifier(c) for c in columns)
    result = execute(session, f"SELECT {selected} FROM {quote_identifier(table_name)}")
    out: list[dict[str, Any]] = []
    for row in result:
        if isinstance(row, Mapping):
            out.append(dict(row))
        elif hasattr(row, "as_dict"):
            out.append(dict(row.as_dict()))
        else:
            names = list(columns or ())
            out.append(dict(zip(names, row)))
    return out


def session_temp_table_contract() -> dict[str, str]:
    """Object names are intentionally V4-scoped and temporary at runtime."""
    return {
        "candidate": "AMY_V4_CANDIDATE_PATIENT",
        "source_event": "AMY_V4_SOURCE_EVENT",
        "atom_match": "AMY_V4_ATOM_MATCH",
        "evidence": "AMY_V4_EVIDENCE_EVENT",
    }


__all__ = [
    "SnowflakeIOError", "TempTableSpec", "execute", "create_temp_table", "drop_temp_table",
    "create_run_table", "insert_rows", "fetch_rows", "session_temp_table_contract",
]

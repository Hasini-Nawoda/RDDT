"""Snowpark/session adapter used by the V4 runtime.

Source warehouse tables are read-only. Pipeline outputs are materialized as
session-scoped ``TEMPORARY`` tables, which disappear automatically when the
Snowflake session ends and never become permanent warehouse objects.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from .source_schema import quote_identifier


class SnowflakeIOError(RuntimeError):
    pass


_READ_ONLY_PREFIX = re.compile(
    r"^\s*(SELECT|WITH|SHOW|DESCRIBE|DESC|EXPLAIN)\b",
    re.IGNORECASE,
)
_FORBIDDEN_STATEMENT = re.compile(
    r"\b(CREATE|INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|TRUNCATE|COPY|PUT|REMOVE|CALL)\b",
    re.IGNORECASE,
)


def assert_read_only_sql(sql: str) -> None:
    """Reject any statement that is not an explicitly read-only query."""
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql must be non-empty")
    if not _READ_ONLY_PREFIX.match(sql) or _FORBIDDEN_STATEMENT.search(sql):
        raise SnowflakeIOError(
            "This source-query path is read-only. Use the dedicated V4 "
            "temporary-table helpers for approved session-scoped outputs; "
            "permanent/transient DDL, source DML, views, and stages are prohibited"
        )


def _collect(result: Any) -> list[Any]:
    if result is None:
        return []
    if hasattr(result, "collect"):
        return list(result.collect())
    if isinstance(result, list):
        return result
    return (
        list(result)
        if isinstance(result, Iterable) and not isinstance(result, (str, bytes, Mapping))
        else [result]
    )


def execute(
    session: Any,
    sql: str,
    params: Sequence[Any] | None = None,
) -> list[Any]:
    """Execute a read-only SQL query and return collected rows."""
    assert_read_only_sql(sql)
    try:
        query = session.sql(sql, params) if params is not None else session.sql(sql)
        return _collect(query)
    except TypeError:
        # Lightweight test doubles often accept only ``sql(text)``.
        query = session.sql(sql)
        return _collect(query)
    except Exception as exc:
        raise SnowflakeIOError(f"Snowflake read query failed: {exc}") from exc


def _execute_statement(
    session: Any,
    sql: str,
    params: Sequence[Any] | None = None,
) -> list[Any]:
    """Execute one explicitly authorized temporary-table statement."""
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql must be non-empty")
    try:
        result = session.sql(sql, params) if params is not None else session.sql(sql)
        return _collect(result)
    except TypeError:
        # Lightweight test doubles often accept only ``sql(text)``.
        result = session.sql(sql)
        return _collect(result)
    except Exception as exc:
        raise SnowflakeIOError(f"Snowflake statement failed: {exc}") from exc


def create_run_table(
    session: Any,
    table_name: str,
    columns: Mapping[str, str],
) -> None:
    """Create or replace a run-scoped Snowflake temporary table."""
    if not isinstance(columns, Mapping) or not columns:
        raise ValueError("columns must be a non-empty mapping")
    definitions: list[str] = []
    for name, data_type in columns.items():
        type_text = str(data_type).strip().upper()
        if not re.fullmatch(
            r"[A-Z][A-Z0-9_]*(?:\s*\(\s*\d+\s*(?:,\s*\d+\s*)?\))?",
            type_text,
        ):
            raise ValueError(f"unsupported temporary-table column type: {data_type!r}")
        definitions.append(f"{quote_identifier(str(name))} {type_text}")
    sql = (
        f"CREATE OR REPLACE TEMPORARY TABLE {quote_identifier(str(table_name))} "
        f"({', '.join(definitions)})"
    )
    _execute_statement(session, sql)


def insert_rows(
    session: Any,
    table_name: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
) -> int:
    """Insert rows into a previously-created session temporary table."""
    names = tuple(str(column) for column in columns)
    if not names:
        raise ValueError("columns must not be empty")
    values = [tuple(row) for row in rows]
    if not values:
        return 0
    if any(len(row) != len(names) for row in values):
        raise ValueError("each row must have the same number of values as columns")
    placeholders = ", ".join("?" for _ in names)
    sql = (
        f"INSERT INTO {quote_identifier(str(table_name))} "
        f"({', '.join(quote_identifier(name) for name in names)}) "
        f"VALUES ({placeholders})"
    )
    for row in values:
        _execute_statement(session, sql, row)
    return len(values)


def fetch_rows(
    session: Any,
    table_name: str,
    columns: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Read rows without creating or modifying a Snowflake object."""
    selected = "*" if not columns else ", ".join(
        '"' + str(column).replace('"', '""') + '"' for column in columns
    )
    result = execute(session, f"SELECT {selected} FROM {table_name}")
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


__all__ = [
    "SnowflakeIOError",
    "assert_read_only_sql",
    "execute",
    "fetch_rows",
    "create_run_table",
    "insert_rows",
]

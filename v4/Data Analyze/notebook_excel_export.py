"""Export Snowflake notebook SQL cells to a local XLSX workbook."""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape

EXCEL_MAX_ROWS = 1_048_576
DEFAULT_MAX_DATA_ROWS = EXCEL_MAX_ROWS - 3
SQL_START = re.compile(r"^\s*(SELECT|WITH|DESCRIBE|SHOW|EXPLAIN)\b", re.IGNORECASE | re.MULTILINE)
NOTEBOOK_MAGIC_LINE = re.compile(r"^\s*%+\S.*$")
INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")
EXPORT_MARKER = "NOTEBOOK_EXCEL_EXPORT_CELL"


@dataclass(frozen=True)
class SqlCell:
    cell_number: int
    label: str
    sql: str


@dataclass(frozen=True)
class SheetResult:
    cell_number: int
    label: str
    sheet_name: str
    query: str
    status: str
    row_count: int
    truncated: bool
    error: str
    headers: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]


@dataclass(frozen=True)
class ExportReport:
    output_path: Path
    sheets_written: tuple[str, ...]
    error_count: int
    truncated_sheet_count: int


def _cell_source(cell: dict[str, Any]) -> str:
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(source)
    return str(source)


def sanitize_sql(source: str) -> str:
    """Drop notebook cell magics such as ``%%sql -r dataframe_1`` before execution."""
    lines = []
    for line in source.splitlines():
        if NOTEBOOK_MAGIC_LINE.match(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _is_sql_cell(cell: dict[str, Any]) -> bool:
    if cell.get("cell_type") != "code":
        return False
    source = sanitize_sql(_cell_source(cell))
    if EXPORT_MARKER in source:
        return False
    metadata = cell.get("metadata") or {}
    language = str(metadata.get("language", "")).lower()
    if language == "python":
        return False
    if language == "sql":
        return bool(source)
    return bool(SQL_START.search(source))


def extract_sql_cells(notebook_path: str | Path) -> list[SqlCell]:
    path = Path(notebook_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    cells: list[SqlCell] = []
    for index, cell in enumerate(payload.get("cells", []), start=1):
        if not _is_sql_cell(cell):
            continue
        metadata = cell.get("metadata") or {}
        label = str(metadata.get("name") or f"Cell {index:03d}")
        cells.append(SqlCell(cell_number=index, label=label, sql=sanitize_sql(_cell_source(cell))))
    return cells


def resolve_placeholders(sql: str, variables: dict[str, Any]) -> tuple[str, list[Any]]:
    resolved = sql
    for key, value in variables.items():
        if value is None:
            continue
        resolved = resolved.replace(f"{{{{{key}}}}}", str(value))
    for key, value in variables.items():
        if value is None:
            continue
        resolved = resolved.replace(f"{{{key}}}", str(value))
    return resolved, []


def _resolve_notebook_path(notebook_path: str | Path) -> Path:
    path = Path(notebook_path)
    if path.exists():
        return path
    candidates = [
        Path.cwd() / path.name,
        Path.cwd() / "v4" / "notebooks and results" / path.name,
        Path(__file__).resolve().parents[1] / "notebooks and results" / path.name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Notebook not found: {notebook_path}")


def _default_output_dir(notebook_path: Path) -> Path:
    candidates = [
        notebook_path.parent.parent / "output",
        Path.cwd() / "v4" / "output",
        Path.cwd() / "output",
        Path(__file__).resolve().parents[1] / "output",
    ]
    for candidate in candidates:
        if candidate.exists() or candidate.parent.exists():
            return candidate
    return candidates[0]


def _sanitize_sheet_name(name: str, used: set[str]) -> str:
    cleaned = INVALID_SHEET_CHARS.sub("_", name.strip()) or "Sheet"
    cleaned = cleaned[:31]
    base = cleaned
    suffix = 1
    while cleaned in used:
        tail = f"_{suffix}"
        cleaned = f"{base[: 31 - len(tail)]}{tail}"
        suffix += 1
    used.add(cleaned)
    return cleaned


def _normalize_row(row: Any, headers: list[str]) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    if hasattr(row, "asDict"):
        return row.asDict()
    if hasattr(row, "_fields"):
        return dict(zip(row._fields, row))
    if headers and not isinstance(row, (str, bytes)):
        try:
            return dict(zip(headers, row))
        except TypeError:
            pass
    if isinstance(row, tuple):
        return {f"COL_{index + 1}": value for index, value in enumerate(row)}
    return {"VALUE": row}


def _execute_sql(session: Any, sql: str, max_rows: int) -> SheetResult:
    try:
        frame = session.sql(sql)
        headers: list[str] = []
        if hasattr(frame, "schema") and getattr(frame.schema, "fields", None):
            headers = [field.name for field in frame.schema.fields]
        rows: list[tuple[Any, ...]] = []
        truncated = False
        for index, row in enumerate(frame.to_local_iterator()):
            if index >= max_rows:
                truncated = True
                break
            normalized = _normalize_row(row, headers)
            if not headers:
                headers = list(normalized.keys())
            rows.append(tuple(normalized.get(header) for header in headers))
        return SheetResult(
            cell_number=0,
            label="",
            sheet_name="",
            query=sql,
            status="SUCCESS",
            row_count=len(rows),
            truncated=truncated,
            error="",
            headers=tuple(headers),
            rows=tuple(rows),
        )
    except Exception as exc:  # noqa: BLE001 - export should continue after query failures
        return SheetResult(
            cell_number=0,
            label="",
            sheet_name="",
            query=sql,
            status="ERROR",
            row_count=0,
            truncated=False,
            error=str(exc),
            headers=(),
            rows=(),
        )


def _column_letter(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _sheet_xml(rows: Iterable[tuple[str, ...]]) -> str:
    row_xml: list[str] = []
    for row_index, values in enumerate(rows, start=1):
        cells: list[str] = []
        for col_index, value in enumerate(values, start=1):
            ref = f"{_column_letter(col_index)}{row_index}"
            if value is None:
                cells.append(f'<c r="{ref}"/>')
                continue
            text = escape(str(value))
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>')
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        "</worksheet>"
    )


def _workbook_xml(sheet_names: list[str]) -> str:
    sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{index + 1}" r:id="rId{index + 1}"/>'
        for index, name in enumerate(sheet_names)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets>"
        "</workbook>"
    )


def _workbook_rels(count: int) -> str:
    relationships = [
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    ]
    for index in range(count):
        relationships.append(
            f'<Relationship Id="rId{index + 2}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index + 1}.xml"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{"".join(relationships)}'
        "</Relationships>"
    )


def _content_types(count: int) -> str:
    overrides = [
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    for index in range(count):
        overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{index + 1}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'{"".join(overrides)}'
        "</Types>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font/></fonts>'
        '<fills count="1"><fill/></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="1"><xf/></cellXfs>'
        "</styleSheet>"
    )


def _build_workbook(path: Path, sheet_tables: list[tuple[str, list[tuple[Any, ...]]]]) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            _content_types(len(sheet_tables)),
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        archive.writestr("xl/workbook.xml", _workbook_xml([name for name, _ in sheet_tables]))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(sheet_tables)))
        archive.writestr("xl/styles.xml", _styles_xml())
        for index, (_, rows) in enumerate(sheet_tables, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(rows))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.getvalue())


def _result_sheet_rows(result: SheetResult) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = [("Query", result.query), ("", "")]
    if result.status == "ERROR":
        rows.append(("Status", "ERROR"))
        rows.append(("Error", result.error))
        return rows
    rows.append(result.headers)
    rows.extend(result.rows)
    return rows


def export_notebook_results(
    notebook_path: str | Path,
    notebook_globals: dict[str, Any],
    *,
    session: Any,
    output_dir: str | Path | None = None,
    max_rows: int = DEFAULT_MAX_DATA_ROWS,
) -> Path:
    notebook = _resolve_notebook_path(notebook_path)
    target_dir = Path(output_dir) if output_dir is not None else _default_output_dir(notebook)
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / f"{notebook.stem}_outputs.xlsx"

    used_names: set[str] = {"Run Summary"}
    results: list[SheetResult] = []
    for cell in extract_sql_cells(notebook):
        resolved_sql, _ = resolve_placeholders(cell.sql, notebook_globals)
        executed = _execute_sql(session, resolved_sql, max_rows=max_rows)
        sheet_name = _sanitize_sheet_name(cell.label, used_names)
        results.append(
            SheetResult(
                cell_number=cell.cell_number,
                label=cell.label,
                sheet_name=sheet_name,
                query=resolved_sql,
                status=executed.status,
                row_count=executed.row_count,
                truncated=executed.truncated,
                error=executed.error,
                headers=executed.headers,
                rows=executed.rows,
            )
        )

    export_notebook_results._last_results = results  # type: ignore[attr-defined]

    summary_header = (
        "Cell Number",
        "Cell Name",
        "Sheet Name",
        "Query",
        "Status",
        "Row Count",
        "Truncated",
        "Error",
    )
    summary_rows: list[tuple[Any, ...]] = [summary_header]
    for result in results:
        summary_rows.append(
            (
                result.cell_number,
                result.label,
                result.sheet_name,
                result.query,
                result.status,
                result.row_count,
                result.truncated,
                result.error,
            )
        )

    sheet_tables: list[tuple[str, list[tuple[Any, ...]]]] = [("Run Summary", summary_rows)]
    for result in results:
        sheet_tables.append((result.sheet_name, _result_sheet_rows(result)))

    _build_workbook(output_path, sheet_tables)
    return output_path


def export_notebook_sql_outputs(
    session: Any,
    notebook_path: str | Path,
    notebook_globals: dict[str, Any],
    output_dir: str | Path | None = None,
    *,
    max_rows: int = DEFAULT_MAX_DATA_ROWS,
) -> ExportReport:
    output_path = export_notebook_results(
        notebook_path,
        notebook_globals,
        session=session,
        output_dir=output_dir,
        max_rows=max_rows,
    )
    results = getattr(export_notebook_results, "_last_results", [])
    sheets_written = ("Run Summary",) + tuple(result.sheet_name for result in results)
    return ExportReport(
        output_path=output_path,
        sheets_written=sheets_written,
        error_count=sum(1 for result in results if result.status == "ERROR"),
        truncated_sheet_count=sum(1 for result in results if result.truncated),
    )


def display_download_button(output_path: str | Path) -> None:
    path = Path(output_path)
    try:
        import streamlit as st

        st.download_button(
            label=f"Download {path.name}",
            data=path.read_bytes(),
            file_name=path.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        return
    except Exception:
        pass

    try:
        from IPython.display import FileLink, display

        display(FileLink(str(path)))
    except Exception:
        print(f"Download file: {path}")

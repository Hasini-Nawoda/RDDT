from __future__ import annotations

import json
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch


DATA_ANALYZE = Path(__file__).parents[1] / "Data Analyze"
if str(DATA_ANALYZE) not in sys.path:
    sys.path.insert(0, str(DATA_ANALYZE))

from notebook_excel_export import (  # noqa: E402
    export_notebook_sql_outputs,
    export_notebook_results,
    extract_sql_cells,
    resolve_placeholders,
    sanitize_sql,
)
import notebook_excel_export as exporter  # noqa: E402


class _Field:
    def __init__(self, name: str):
        self.name = name


class _Schema:
    def __init__(self, names):
        self.fields = [_Field(name) for name in names]


class _Frame:
    def __init__(self, rows, names=("VALUE",)):
        self.schema = _Schema(names)
        self._rows = rows

    def to_local_iterator(self):
        return iter(self._rows)


class _Session:
    def __init__(self):
        self.queries = []

    def sql(self, query):
        self.queries.append(query)
        if "MISSING_TABLE" in query:
            raise RuntimeError("table does not exist")
        return _Frame([(1,), (2,)], ("VALUE",))


def test_sanitize_sql_strips_notebook_cell_magics() -> None:
    assert sanitize_sql("%%sql -r dataframe_1\nSELECT 1;") == "SELECT 1;"
    assert sanitize_sql("%sql\nDESCRIBE TABLE T;") == "DESCRIBE TABLE T;"


def test_extracts_sql_in_order_and_resolves_both_placeholder_forms(tmp_path):
    path = tmp_path / "demo.ipynb"
    path.write_text(
        json.dumps(
            {
                "cells": [
                    {"cell_type": "code", "source": ["x = 1"]},
                    {
                        "cell_type": "code",
                        "metadata": {"language": "sql", "name": "Named query"},
                        "source": ["%%sql -r dataframe_1\n", "SELECT * FROM {{TABLE}} WHERE X = {VALUE};"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    cells = extract_sql_cells(path)
    assert [(cell.cell_number, cell.label) for cell in cells] == [(2, "Named query")]
    assert resolve_placeholders(cells[0].sql, {"TABLE": "T", "VALUE": 4}) == (
        "SELECT * FROM T WHERE X = 4;",
        [],
    )


def test_exports_summary_and_records_query_errors(tmp_path):
    path = tmp_path / "demo.ipynb"
    path.write_text(
        json.dumps(
            {
                "cells": [
                    {"cell_type": "code", "source": ["SELECT 1"]},
                    {"cell_type": "code", "source": ["SELECT * FROM MISSING_TABLE"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    session = _Session()
    report = export_notebook_sql_outputs(session, path, {}, tmp_path / "output")
    assert report.output_path.name == "demo_outputs.xlsx"
    assert report.sheets_written[0] == "Run Summary"
    assert len(report.sheets_written) == 3
    assert report.error_count == 1
    with zipfile.ZipFile(report.output_path) as workbook:
        assert "xl/workbook.xml" in workbook.namelist()
        assert "xl/styles.xml" in workbook.namelist()
        for member in workbook.namelist():
            if member.endswith(".xml"):
                ET.fromstring(workbook.read(member))


def test_max_rows_marks_truncation(tmp_path):
    path = tmp_path / "demo.ipynb"
    path.write_text(json.dumps({"cells": [{"cell_type": "code", "source": ["SELECT 1"]}]}), encoding="utf-8")
    report_path = export_notebook_results(
        path,
        {},
        session=_Session(),
        output_dir=tmp_path,
        max_rows=1,
    )
    assert report_path.exists()
    assert export_notebook_results._last_results[0].truncated  # type: ignore[attr-defined]


def test_zip_is_built_on_a_seekable_stream_before_workspace_write(tmp_path):
    """Regression test for Snowflake Workspace filesystems without seek()."""

    path = tmp_path / "demo.ipynb"
    path.write_text(
        json.dumps({"cells": [{"cell_type": "code", "source": ["SELECT 1"]}]}),
        encoding="utf-8",
    )
    original_zipfile = exporter.zipfile.ZipFile
    observed = []

    def checked_zipfile(file, *args, **kwargs):
        observed.append(file)
        assert not isinstance(file, (str, Path))
        assert file.seekable()
        return original_zipfile(file, *args, **kwargs)

    with patch.object(exporter.zipfile, "ZipFile", checked_zipfile):
        report = export_notebook_sql_outputs(_Session(), path, {}, tmp_path / "output")

    assert report.output_path.exists()
    assert observed

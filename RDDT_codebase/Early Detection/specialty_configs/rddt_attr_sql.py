"""SQL layer ATTR analysis.

The notebook owns the table/column configuration; this module owns the SQL.
Every physical identifier is resolved through the config dict passed in, and is
always quoted, so names containing spaces or "/" (Member/PatientId,
Clinical Note Text) work unchanged and a rename only touches the notebook.

Flow :
    Step 1  QC            null / total per configured table
    Step 2  wide net      claim codes + text nets -> ATTR_WIDE_NET_CANDIDATES
    Step 3  evidence      ATTR_EVID_* for candidates only
    Step 4  features      handled by rddt_specialty_sql.run_specialty_step4_sql

All objects created here are session TEMPORARY tables.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd

# ---------------------------------------------------------------------------
# Identifier / expression helpers
# ---------------------------------------------------------------------------

Pattern = Union[str, Sequence[str]]


def quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def quote_path(path: str) -> str:
    return ".".join(quote_identifier(part) for part in str(path).split("."))


def sql_literal(value: Any) -> str:
    """Escape a value for use inside single quotes."""
    return str(value).replace("\\", "\\\\").replace("'", "''")


def source_for(config: Mapping[str, Any], logical_table: str) -> Mapping[str, Any]:
    try:
        return config["tables"][logical_table]
    except KeyError as exc:
        raise KeyError(
            f"Unknown logical table '{logical_table}'. "
            f"Configured: {sorted(config.get('tables', {}))}"
        ) from exc


def table_ref(config: Mapping[str, Any], logical_table: str) -> str:
    source = source_for(config, logical_table)
    name = str(source["name"])
    namespace = config.get("namespace")
    if namespace and "." not in name:
        name = f"{namespace}.{name}"
    return quote_path(name)


def display_name(config: Mapping[str, Any], logical_table: str) -> str:
    return str(source_for(config, logical_table)["name"])


def is_enabled(config: Mapping[str, Any], logical_table: str) -> bool:
    return bool(source_for(config, logical_table).get("enabled", True))


def column(
    source: Mapping[str, Any],
    logical_name: str,
    alias: Optional[str] = None,
) -> Optional[str]:
    """Quoted column reference, or None when the column is not mapped."""
    physical = source.get("columns", {}).get(logical_name)
    if not physical:
        return None
    quoted = quote_identifier(str(physical))
    return f"{alias}.{quoted}" if alias else quoted


def column_or_null(
    source: Mapping[str, Any],
    logical_name: str,
    alias: Optional[str] = None,
) -> str:
    return column(source, logical_name, alias) or "NULL"


def mapped_columns(
    source: Mapping[str, Any],
    logical_names: Iterable[str],
    alias: Optional[str] = None,
) -> List[str]:
    """Quoted refs for the logical names that are actually mapped in config."""
    refs = []
    for logical_name in logical_names:
        ref = column(source, logical_name, alias)
        if ref:
            refs.append(ref)
    return refs


def text_expr(expr: str) -> str:
    return f"COALESCE(TO_VARCHAR({expr}), '')"


def patient_id_expr(source: Mapping[str, Any], alias: Optional[str] = None) -> str:
    ref = column(source, "patient_id", alias)
    if not ref:
        raise ValueError(
            f"Table '{source.get('name')}' has no 'patient_id' column mapping"
        )
    return f"TRIM(TO_VARCHAR({ref}))"


def _execute(session, statement: str) -> None:
    session.sql(statement).collect()


def _scalar(session, statement: str) -> Any:
    return session.sql(statement).collect()[0][0]


def count_rows(session, table: str) -> int:
    return int(_scalar(session, f"SELECT COUNT(*) FROM {table}"))


def _as_patterns(patterns: Pattern) -> List[str]:
    if isinstance(patterns, str):
        return [patterns]
    return list(patterns)


# ---------------------------------------------------------------------------
# Step 1 — schema validation and QC
# ---------------------------------------------------------------------------


def table_exists(session, config: Mapping[str, Any], logical_table: str) -> bool:
    try:
        session.sql(f"SELECT 1 FROM {table_ref(config, logical_table)} LIMIT 1").collect()
        return True
    except Exception:
        return False


def describe_columns(session, config: Mapping[str, Any], logical_table: str) -> List[str]:
    rows = session.sql(f"DESCRIBE TABLE {table_ref(config, logical_table)}").collect()
    return [str(row[0]) for row in rows]


def validate_sources(
    session,
    config: Mapping[str, Any],
    raise_on_error: bool = True,
) -> pd.DataFrame:
    """Check enabled tables against Excel analysis-need fields.
    required_columns = columns marked need in the dictionary.
    """
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []

    for logical_table, source in config["tables"].items():
        physical = str(source.get("name"))
        if not source.get("enabled", True):
            rows.append(
                {
                    "logical_table": logical_table,
                    "table": physical,
                    "status": "DISABLED",
                    "missing_columns": "",
                }
            )
            continue

        if not table_exists(session, config, logical_table):
            required = bool(source.get("required"))
            status = "MISSING_TABLE (required)" if required else "MISSING_TABLE (optional)"
            rows.append(
                {
                    "logical_table": logical_table,
                    "table": physical,
                    "status": status,
                    "missing_columns": "",
                }
            )
            if required:
                errors.append(f"{logical_table}: table {physical} not found")
            continue

        available = {name.upper() for name in describe_columns(session, config, logical_table)}
        wanted = source.get("required_columns") or ("patient_id",)
        missing = [
            logical
            for logical in wanted
            if str(source.get("columns", {}).get(logical, "")).upper() not in available
        ]
        rows.append(
            {
                "logical_table": logical_table,
                "table": physical,
                "status": "OK" if not missing else "MISSING_COLUMNS",
                "missing_columns": ", ".join(missing),
            }
        )
        if missing:
            mapped = [source.get("columns", {}).get(logical) for logical in missing]
            errors.append(f"{logical_table}: mapped columns not found -> {mapped}")

    report = pd.DataFrame(rows)
    if errors and raise_on_error:
        raise ValueError(
            "Source validation failed. Fix SOURCE_CONFIG in the notebook:\n- "
            + "\n- ".join(errors)
        )
    return report


def null_and_total(
    session,
    config: Mapping[str, Any],
    logical_table: str,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Null PATIENT_ID count + total rows, the v1.1 equivalent of the old QC."""
    source = source_for(config, logical_table)
    physical = str(source.get("name"))

    if not source.get("enabled", True):
        result = {"logical_table": logical_table, "table": physical, "status": "DISABLED",
                  "null_patient_id": None, "total_rows": None}
    elif not table_exists(session, config, logical_table):
        result = {"logical_table": logical_table, "table": physical, "status": "MISSING",
                  "null_patient_id": None, "total_rows": None}
    else:
        ref = table_ref(config, logical_table)
        pid = column(source, "patient_id")
        null_count = int(_scalar(session, f"SELECT COUNT(*) FROM {ref} WHERE {pid} IS NULL"))
        total = int(_scalar(session, f"SELECT COUNT(*) FROM {ref}"))
        result = {"logical_table": logical_table, "table": physical, "status": "OK",
                  "null_patient_id": null_count, "total_rows": total}

    if verbose:
        print(f"=== {physical} ({logical_table}) ===")
        if result["status"] == "OK":
            print(f"Records with Null patient id: {result['null_patient_id']:,}")
            print(f"Total Record Count: {result['total_rows']:,}")
        else:
            print(f"Status: {result['status']}")
        print()
    return result


def table_qc(
    session,
    config: Mapping[str, Any],
    logical_tables: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    tables = list(logical_tables or config["tables"].keys())
    return pd.DataFrame([null_and_total(session, config, t) for t in tables])


def patient_count(session, config: Mapping[str, Any]) -> int:
    source = source_for(config, "census")
    ref = table_ref(config, "census")
    pid = column(source, "patient_id")
    return int(_scalar(session, f"SELECT COUNT(DISTINCT TRIM(TO_VARCHAR({pid}))) FROM {ref}"))


# ---------------------------------------------------------------------------
# Step 2 — claim code net (ICD / CPT)
# ---------------------------------------------------------------------------


def _code_forms(code_ref: str) -> Tuple[str, str]:
    """(dotted, undotted) normalized SQL expressions for a code column."""
    raw = f"UPPER(TRIM({text_expr(code_ref)}))"
    bare = f"REPLACE({raw}, '.', '')"
    return raw, bare


def _exact_code_predicate(code_ref: str, codes: Sequence[str]) -> Optional[str]:
    codes = [c for c in codes if str(c).strip()]
    if not codes:
        return None
    raw, bare = _code_forms(code_ref)
    dotted = ", ".join(f"'{sql_literal(str(c).upper())}'" for c in codes)
    undotted = ", ".join(
        f"'{sql_literal(str(c).upper().replace('.', ''))}'" for c in codes
    )
    return f"({raw} IN ({dotted}) OR {bare} IN ({undotted}))"


def _like_code_predicate(code_ref: str, prefixes: Sequence[str]) -> Optional[str]:
    prefixes = [p for p in prefixes if str(p).strip()]
    if not prefixes:
        return None
    raw, bare = _code_forms(code_ref)
    parts = []
    for prefix in prefixes:
        dotted = sql_literal(str(prefix).upper())
        undotted = sql_literal(str(prefix).upper().replace(".", ""))
        parts.append(f"{raw} LIKE '{dotted}'")
        parts.append(f"{bare} LIKE '{undotted}'")
    return "(" + " OR ".join(parts) + ")"


def _claim_code_predicate(
    config: Mapping[str, Any],
    exact_icd: Sequence[str] = (),
    exact_cpt: Sequence[str] = (),
    like_prefixes: Sequence[str] = (),
    alias: Optional[str] = None,
) -> str:
    """Diagnosis columns get ICD + LIKE, procedure columns get CPT."""
    source = source_for(config, "claim")
    diagnosis_cols = mapped_columns(source, source.get("diagnosis_columns", ()), alias)
    procedure_cols = mapped_columns(source, source.get("procedure_columns", ()), alias)

    parts: List[str] = []
    for ref in diagnosis_cols:
        for predicate in (
            _exact_code_predicate(ref, exact_icd),
            _like_code_predicate(ref, like_prefixes),
        ):
            if predicate:
                parts.append(predicate)
    for ref in procedure_cols:
        predicate = _exact_code_predicate(ref, exact_cpt)
        if predicate:
            parts.append(predicate)

    return "(" + " OR ".join(parts) + ")" if parts else "FALSE"


def code_net_patient_ids(
    session,
    config: Mapping[str, Any],
    exact_icd: Sequence[str] = (),
    exact_cpt: Sequence[str] = (),
    like_prefixes: Sequence[str] = (),
) -> List[str]:
    """Distinct patients in the claim table matching any target code."""
    source = source_for(config, "claim")
    ref = table_ref(config, "claim")
    pid = patient_id_expr(source)
    predicate = _claim_code_predicate(config, exact_icd, exact_cpt, like_prefixes)

    frame = session.sql(
        f"""
        SELECT DISTINCT {pid} AS PATIENT_ID
        FROM {ref}
        WHERE {column(source, 'patient_id')} IS NOT NULL
          AND {predicate}
        """
    ).to_pandas()
    return [p.strip() for p in frame["PATIENT_ID"].tolist() if p]


def per_code_counts(
    session,
    config: Mapping[str, Any],
    codes: Sequence[str],
    code_kind: str = "icd",
    verbose: bool = True,
) -> pd.DataFrame:
    """Unique patients per individual code. Overlap between codes is expected."""
    source = source_for(config, "claim")
    ref = table_ref(config, "claim")
    pid = patient_id_expr(source)
    logical_cols = (
        source.get("diagnosis_columns", ())
        if code_kind.lower() == "icd"
        else source.get("procedure_columns", ())
    )
    col_refs = mapped_columns(source, logical_cols)

    rows = []
    for code in sorted(codes):
        predicates = [p for p in (_exact_code_predicate(r, [code]) for r in col_refs) if p]
        if not predicates:
            rows.append({"code": code, "unique_patients": 0})
            continue
        n = int(
            _scalar(
                session,
                f"""
                SELECT COUNT(DISTINCT {pid})
                FROM {ref}
                WHERE {column(source, 'patient_id')} IS NOT NULL
                  AND ({' OR '.join(predicates)})
                """,
            )
        )
        rows.append({"code": code, "unique_patients": n})
        if verbose:
            print(f"{code:12s}  {n:,}")

    frame = pd.DataFrame(rows).sort_values("unique_patients", ascending=False)
    if verbose and len(frame):
        print(f"\nCodes with >0 patients: {(frame['unique_patients'] > 0).sum()} / {len(frame)}")
    return frame


# ---------------------------------------------------------------------------
# Step 2 — text / keyword nets
# ---------------------------------------------------------------------------


def _text_predicate(
    source: Mapping[str, Any],
    logical_columns: Sequence[str],
    patterns: Sequence[str],
    alias: Optional[str] = None,
) -> str:
    col_refs = mapped_columns(source, logical_columns, alias)
    if not col_refs:
        return "FALSE"
    parts = []
    for pattern in patterns:
        literal = sql_literal(pattern)
        for ref in col_refs:
            parts.append(f"{ref} ILIKE '{literal}'")
    return "(" + " OR ".join(parts) + ")" if parts else "FALSE"


def text_net_patient_ids(
    session,
    config: Mapping[str, Any],
    logical_table: str,
    logical_columns: Sequence[str],
    patterns: Sequence[str],
    verbose: bool = True,
) -> List[str]:
    """Distinct patients whose configured text columns match any ILIKE pattern."""
    source = source_for(config, logical_table)
    physical = str(source.get("name"))

    if not source.get("enabled", True) or not table_exists(session, config, logical_table):
        if verbose:
            print(f"{physical}: skipped (disabled or missing)")
        return []

    ref = table_ref(config, logical_table)
    pid = patient_id_expr(source)
    predicate = _text_predicate(source, logical_columns, patterns)
    frame = session.sql(
        f"""
        SELECT DISTINCT {pid} AS PATIENT_ID
        FROM {ref}
        WHERE {column(source, 'patient_id')} IS NOT NULL
          AND {predicate}
        """
    ).to_pandas()
    ids = [p.strip() for p in frame["PATIENT_ID"].tolist() if p]
    if verbose:
        print(f"{physical} unique patients: {len(ids):,}")
    return ids


def _snomed_digits(code: Any) -> str:
    return "".join(ch for ch in str(code) if ch.isdigit())


def snomed_net_patient_ids(
    session,
    config: Mapping[str, Any],
    logical_table: str,
    codes: Sequence[str],
    verbose: bool = True,
) -> List[str]:
    """Distinct patients whose SNOMED / Secondary SNOMED matches any concept ID.

    Used so a history row with a code but no English text still enters Step 2.
    """
    source = source_for(config, logical_table)
    physical = str(source.get("name"))
    digits = []
    seen = set()
    for c in codes:
        d = _snomed_digits(c)
        if d and d not in seen:
            seen.add(d)
            digits.append(d)

    if not digits:
        if verbose:
            print(f"{physical} SNOMED net: skipped (no concept IDs)")
        return []

    if not source.get("enabled", True) or not table_exists(session, config, logical_table):
        if verbose:
            print(f"{physical} SNOMED net: skipped (disabled or missing)")
        return []

    col_refs = mapped_columns(source, ("snomed", "secondary_snomed"))
    if not col_refs:
        if verbose:
            print(f"{physical} SNOMED net: skipped (no SNOMED columns mapped)")
        return []

    inns = ", ".join(f"'{sql_literal(d)}'" for d in digits)
    parts = [
        f"REGEXP_REPLACE(UPPER(TRIM(COALESCE(TO_VARCHAR({ref}), ''))), '[^0-9]', '') IN ({inns})"
        for ref in col_refs
    ]
    ref = table_ref(config, logical_table)
    pid = patient_id_expr(source)
    frame = session.sql(
        f"""
        SELECT DISTINCT {pid} AS PATIENT_ID
        FROM {ref}
        WHERE {column(source, 'patient_id')} IS NOT NULL
          AND ({' OR '.join(parts)})
        """
    ).to_pandas()
    ids = [p.strip() for p in frame["PATIENT_ID"].tolist() if p]
    if verbose:
        print(f"{physical} SNOMED unique patients: {len(ids):,}")
    return ids


def term_counts(
    session,
    config: Mapping[str, Any],
    logical_table: str,
    logical_columns: Sequence[str],
    terms: Sequence[Tuple[str, Pattern]],
    verbose: bool = True,
    label_width: int = 42,
) -> pd.DataFrame:
    """Unique patients per keyword, the v1.1 equivalent of the old QC tables."""
    source = source_for(config, logical_table)
    physical = str(source.get("name"))

    if not source.get("enabled", True) or not table_exists(session, config, logical_table):
        if verbose:
            print(f"{physical}: skipped (disabled or missing)")
        return pd.DataFrame(columns=["term", "patterns", "unique_patients"])

    ref = table_ref(config, logical_table)
    pid = patient_id_expr(source)

    rows = []
    for label, raw_patterns in terms:
        patterns = _as_patterns(raw_patterns)
        predicate = _text_predicate(source, logical_columns, patterns)
        n = int(
            _scalar(
                session,
                f"""
                SELECT COUNT(DISTINCT {pid})
                FROM {ref}
                WHERE {column(source, 'patient_id')} IS NOT NULL
                  AND {predicate}
                """,
            )
        )
        rows.append({"term": label, "patterns": " | ".join(patterns), "unique_patients": n})
        if verbose:
            print(f"{label:{label_width}s}  {n:,}")

    frame = pd.DataFrame(rows).sort_values("unique_patients", ascending=False)
    if verbose and len(frame):
        print(f"\nTerms with >0: {(frame['unique_patients'] > 0).sum()} / {len(frame)}")
    return frame


# ---------------------------------------------------------------------------
# Step 2 — candidate table
# ---------------------------------------------------------------------------


def create_candidates(
    session,
    patient_ids: Iterable[str],
    table: str = "ATTR_WIDE_NET_CANDIDATES",
) -> int:
    """Materialize the wide net as a session TEMPORARY table."""
    unique = sorted({str(p).strip() for p in patient_ids if str(p).strip()})
    if not unique:
        raise ValueError("Wide net is empty — check Step 2 nets before continuing")

    frame = pd.DataFrame({"PATIENT_ID": unique})
    session.create_dataframe(frame).write.mode("overwrite").save_as_table(
        table, table_type="temporary"
    )
    n = count_rows(session, table)
    print(f"{table} rows: {n:,}")
    return n


# ---------------------------------------------------------------------------
# Step 3 — evidence tables for candidates only
# ---------------------------------------------------------------------------

_CANDIDATES = "ATTR_WIDE_NET_CANDIDATES"

_HISTORY_SHAPE = (
    ("RECORD_ID", "CAST(NULL AS VARCHAR)"),
    ("VISIT_ID", "CAST(NULL AS VARCHAR)"),
    ("PATIENT_ID", "CAST(NULL AS VARCHAR)"),
    ("SOURCE_CATEGORY", "CAST(NULL AS VARCHAR)"),
    ("VALUE", "CAST(NULL AS VARCHAR)"),
    ("SNOMED", "CAST(NULL AS VARCHAR)"),
    ("SECONDARY_SNOMED", "CAST(NULL AS VARCHAR)"),
    ("EVENT_DATE", "CAST(NULL AS TIMESTAMP)"),
)

_FAMILY_HISTORY_SHAPE = (
    ("RECORD_ID", "CAST(NULL AS VARCHAR)"),
    ("VISIT_ID", "CAST(NULL AS VARCHAR)"),
    ("PATIENT_ID", "CAST(NULL AS VARCHAR)"),
    ("SNOMED", "CAST(NULL AS VARCHAR)"),
    ("CONDITION", "CAST(NULL AS VARCHAR)"),
    ("STATUS", "CAST(NULL AS VARCHAR)"),
    ("FAMILY_MEMBER", "CAST(NULL AS VARCHAR)"),
    ("EVENT_DATE", "CAST(NULL AS TIMESTAMP)"),
)


def _create_empty(session, table: str, shape: Sequence[Tuple[str, str]]) -> None:
    columns = ",\n          ".join(f"{expr} AS {name}" for name, expr in shape)
    _execute(
        session,
        f"""
        CREATE OR REPLACE TEMPORARY TABLE {table} AS
        SELECT
          {columns}
        WHERE 1 = 0
        """,
    )


def _candidate_join(pid_expr: str) -> str:
    return f"INNER JOIN {_CANDIDATES} C ON {pid_expr} = TRIM(TO_VARCHAR(C.PATIENT_ID))"


def _build_history_evidence(
    session,
    config: Mapping[str, Any],
    logical_table: str,
    output_table: str,
) -> None:
    """Medical / surgical history: Source/Category + Value + SNOMED pair."""
    if not is_enabled(config, logical_table) or not table_exists(session, config, logical_table):
        _create_empty(session, output_table, _HISTORY_SHAPE)
        return

    source = source_for(config, logical_table)
    pid = patient_id_expr(source, "S")
    _execute(
        session,
        f"""
        CREATE OR REPLACE TEMPORARY TABLE {output_table} AS
        SELECT
          {text_expr(column_or_null(source, 'record_id', 'S'))} AS RECORD_ID,
          {text_expr(column_or_null(source, 'encounter_id', 'S'))} AS VISIT_ID,
          {pid} AS PATIENT_ID,
          {text_expr(column_or_null(source, 'source_category', 'S'))} AS SOURCE_CATEGORY,
          {text_expr(column_or_null(source, 'value', 'S'))} AS VALUE,
          {text_expr(column_or_null(source, 'snomed', 'S'))} AS SNOMED,
          {text_expr(column_or_null(source, 'secondary_snomed', 'S'))} AS SECONDARY_SNOMED,
          TRY_TO_TIMESTAMP({column_or_null(source, 'event_date', 'S')}) AS EVENT_DATE
        FROM {table_ref(config, logical_table)} S
        {_candidate_join(pid)}
        WHERE {column(source, 'patient_id', 'S')} IS NOT NULL
        """,
    )


def _build_family_history_evidence(session, config: Mapping[str, Any]) -> None:
    """Family history keeps Condition / Status / FamilyMember as their own columns."""
    if not is_enabled(config, "family_history") or not table_exists(session, config, "family_history"):
        _create_empty(session, "ATTR_EVID_FAMILY_HISTORY", _FAMILY_HISTORY_SHAPE)
        return

    source = source_for(config, "family_history")
    pid = patient_id_expr(source, "S")
    _execute(
        session,
        f"""
        CREATE OR REPLACE TEMPORARY TABLE ATTR_EVID_FAMILY_HISTORY AS
        SELECT
          {text_expr(column_or_null(source, 'record_id', 'S'))} AS RECORD_ID,
          {text_expr(column_or_null(source, 'encounter_id', 'S'))} AS VISIT_ID,
          {pid} AS PATIENT_ID,
          {text_expr(column_or_null(source, 'snomed', 'S'))} AS SNOMED,
          {text_expr(column_or_null(source, 'condition', 'S'))} AS CONDITION,
          {text_expr(column_or_null(source, 'status', 'S'))} AS STATUS,
          {text_expr(column_or_null(source, 'family_member', 'S'))} AS FAMILY_MEMBER,
          TRY_TO_TIMESTAMP({column_or_null(source, 'event_date', 'S')}) AS EVENT_DATE
        FROM {table_ref(config, 'family_history')} S
        {_candidate_join(pid)}
        WHERE {column(source, 'patient_id', 'S')} IS NOT NULL
        """,
    )


def _build_encounter_evidence(session, config: Mapping[str, Any]) -> None:
    if not is_enabled(config, "encounter") or not table_exists(session, config, "encounter"):
        _create_empty(
            session,
            "ATTR_EVID_ENCOUNTER",
            (
                ("VISIT_ID", "CAST(NULL AS VARCHAR)"),
                ("PATIENT_ID", "CAST(NULL AS VARCHAR)"),
                ("ENCOUNTER_DATE", "CAST(NULL AS TIMESTAMP)"),
            ),
        )
        return

    source = source_for(config, "encounter")
    pid = patient_id_expr(source, "S")
    _execute(
        session,
        f"""
        CREATE OR REPLACE TEMPORARY TABLE ATTR_EVID_ENCOUNTER AS
        SELECT
          {text_expr(column_or_null(source, 'encounter_id', 'S'))} AS VISIT_ID,
          {pid} AS PATIENT_ID,
          TRY_TO_TIMESTAMP({column_or_null(source, 'encounter_date', 'S')}) AS ENCOUNTER_DATE
        FROM {table_ref(config, 'encounter')} S
        {_candidate_join(pid)}
        WHERE {column(source, 'patient_id', 'S')} IS NOT NULL
        """,
    )


def _build_patient_evidence(session, config: Mapping[str, Any]) -> None:
    source = source_for(config, "census")
    pid = patient_id_expr(source, "S")
    _execute(
        session,
        f"""
        CREATE OR REPLACE TEMPORARY TABLE ATTR_EVID_PATIENT AS
        SELECT
          {pid} AS PATIENT_ID,
          {column_or_null(source, 'gender', 'S')} AS SEX,
          TRY_TO_DATE({column_or_null(source, 'birth_date', 'S')}) AS DATE_OF_BIRTH,
          DATEDIFF(
            'year',
            TRY_TO_DATE({column_or_null(source, 'birth_date', 'S')}),
            CURRENT_DATE()
          ) AS AGE_IN_YEARS,
          {text_expr(column_or_null(source, 'city', 'S'))} AS HOME_CITY,
          {text_expr(column_or_null(source, 'state', 'S'))} AS HOME_STATE,
          {text_expr(column_or_null(source, 'family_id', 'S'))} AS FAMILY_ID
        FROM {table_ref(config, 'census')} S
        {_candidate_join(pid)}
        WHERE {column(source, 'patient_id', 'S')} IS NOT NULL
        """,
    )


def _build_claim_evidence(session, config: Mapping[str, Any]) -> None:
    """Claim mirrored column for column. Step 4 unpivots the code columns itself."""
    source = source_for(config, "claim")
    pid = patient_id_expr(source, "S")
    _execute(
        session,
        f"""
        CREATE OR REPLACE TEMPORARY TABLE ATTR_EVID_CLAIM AS
        SELECT
          {pid} AS PATIENT_ID,
          {text_expr(column_or_null(source, 'encounter_id', 'S'))} AS VISIT_ID,
          UPPER(TRIM({text_expr(column_or_null(source, 'diagnosis_code', 'S'))})) AS DIAGNOSIS_CODE,
          UPPER(TRIM({text_expr(column_or_null(source, 'other_diagnosis_9', 'S'))})) AS OTHER_DIAGNOSIS_9,
          UPPER(TRIM({text_expr(column_or_null(source, 'other_diagnosis_10', 'S'))})) AS OTHER_DIAGNOSIS_10,
          UPPER(TRIM({text_expr(column_or_null(source, 'procedure_code', 'S'))})) AS PROCEDURE_CODE,
          {text_expr(column_or_null(source, 'procedure_modifier_1', 'S'))} AS PROCEDURE_MODIFIER_1,
          {text_expr(column_or_null(source, 'procedure_modifier_2', 'S'))} AS PROCEDURE_MODIFIER_2,
          {text_expr(column_or_null(source, 'procedure_modifier_3', 'S'))} AS PROCEDURE_MODIFIER_3,
          {text_expr(column_or_null(source, 'diagnosis_type', 'S'))} AS DIAGNOSIS_TYPE,
          {text_expr(column_or_null(source, 'provider_type', 'S'))} AS PROVIDER_TYPE,
          {text_expr(column_or_null(source, 'specialty_code', 'S'))} AS SPECIALTY_CODE,
          {text_expr(column_or_null(source, 'specialty_name', 'S'))} AS SPECIALTY_NAME,
          {text_expr(column_or_null(source, 'drg_code', 'S'))} AS DRG_CODE,
          {text_expr(column_or_null(source, 'clinical_notes', 'S'))} AS CLINICAL_NOTES,
          TRY_TO_DATE({column_or_null(source, 'from_date', 'S')}) AS FROM_DATE,
          TRY_TO_DATE({column_or_null(source, 'to_date', 'S')}) AS TO_DATE
        FROM {table_ref(config, 'claim')} S
        {_candidate_join(pid)}
        WHERE {column(source, 'patient_id', 'S')} IS NOT NULL
        """,
    )


def _build_lab_evidence(session, config: Mapping[str, Any]) -> None:
    if not is_enabled(config, "lab") or not table_exists(session, config, "lab"):
        _create_empty(
            session,
            "ATTR_EVID_LAB_RESULT",
            (
                ("LAB_ID", "CAST(NULL AS VARCHAR)"),
                ("VISIT_ID", "CAST(NULL AS VARCHAR)"),
                ("PATIENT_ID", "CAST(NULL AS VARCHAR)"),
                ("LAB_REQUEST_ID", "CAST(NULL AS VARCHAR)"),
                ("LAB_RESULT_ID", "CAST(NULL AS VARCHAR)"),
                ("OBSERVATION_IDENTIFIER", "CAST(NULL AS VARCHAR)"),
                ("OBSERVATION_VALUE", "CAST(NULL AS VARCHAR)"),
                ("RESULT_STATUS", "CAST(NULL AS VARCHAR)"),
                ("LAB_RESULT_NOTE", "CAST(NULL AS VARCHAR)"),
                ("OBSERVATION_DATETIME", "CAST(NULL AS TIMESTAMP)"),
            ),
        )
        return

    source = source_for(config, "lab")
    pid = patient_id_expr(source, "S")
    _execute(
        session,
        f"""
        CREATE OR REPLACE TEMPORARY TABLE ATTR_EVID_LAB_RESULT AS
        SELECT
          {text_expr(column_or_null(source, 'lab_id', 'S'))} AS LAB_ID,
          {text_expr(column_or_null(source, 'encounter_id', 'S'))} AS VISIT_ID,
          {pid} AS PATIENT_ID,
          {text_expr(column_or_null(source, 'lab_request_id', 'S'))} AS LAB_REQUEST_ID,
          {text_expr(column_or_null(source, 'lab_result_id', 'S'))} AS LAB_RESULT_ID,
          {text_expr(column_or_null(source, 'observation_identifier', 'S'))} AS OBSERVATION_IDENTIFIER,
          {text_expr(column_or_null(source, 'observation_value', 'S'))} AS OBSERVATION_VALUE,
          {text_expr(column_or_null(source, 'result_status', 'S'))} AS RESULT_STATUS,
          {text_expr(column_or_null(source, 'lab_result_note', 'S'))} AS LAB_RESULT_NOTE,
          TRY_TO_TIMESTAMP({column_or_null(source, 'observation_datetime', 'S')}) AS OBSERVATION_DATETIME
        FROM {table_ref(config, 'lab')} S
        {_candidate_join(pid)}
        WHERE {column(source, 'patient_id', 'S')} IS NOT NULL
        """,
    )


def _build_note_evidence(session, config: Mapping[str, Any]) -> None:
    """Clinical Note mirrored. Claim.ClinicalNotes stays on ATTR_EVID_CLAIM."""
    if not is_enabled(config, "clinical_note") or not table_exists(session, config, "clinical_note"):
        _create_empty(
            session,
            "ATTR_EVID_CLINICAL_NOTES",
            (
                ("NOTE_ID", "CAST(NULL AS VARCHAR)"),
                ("VISIT_ID", "CAST(NULL AS VARCHAR)"),
                ("PATIENT_ID", "CAST(NULL AS VARCHAR)"),
                ("NOTE_TYPE", "CAST(NULL AS VARCHAR)"),
                ("NOTE_TEXT", "CAST(NULL AS VARCHAR)"),
                ("NOTE_DATE", "CAST(NULL AS TIMESTAMP)"),
            ),
        )
        return

    source = source_for(config, "clinical_note")
    pid = patient_id_expr(source, "S")
    _execute(
        session,
        f"""
        CREATE OR REPLACE TEMPORARY TABLE ATTR_EVID_CLINICAL_NOTES AS
        SELECT
          {text_expr(column_or_null(source, 'note_id', 'S'))} AS NOTE_ID,
          {text_expr(column_or_null(source, 'encounter_id', 'S'))} AS VISIT_ID,
          {pid} AS PATIENT_ID,
          {text_expr(column_or_null(source, 'note_type', 'S'))} AS NOTE_TYPE,
          {text_expr(column_or_null(source, 'note_text', 'S'))} AS NOTE_TEXT,
          TRY_TO_TIMESTAMP({column_or_null(source, 'event_date', 'S')}) AS NOTE_DATE
        FROM {table_ref(config, 'clinical_note')} S
        {_candidate_join(pid)}
        WHERE {column(source, 'patient_id', 'S')} IS NOT NULL
        """,
    )


def build_evidence(session, config: Mapping[str, Any]) -> pd.DataFrame:
    """Create ATTR_EVID_* temporary tables for wide-net candidates only."""
    if count_rows(session, _CANDIDATES) == 0:
        raise ValueError(f"{_CANDIDATES} is empty — run Step 2 first")

    _build_patient_evidence(session, config)
    _build_encounter_evidence(session, config)
    _build_claim_evidence(session, config)
    _build_lab_evidence(session, config)
    _build_history_evidence(session, config, "medical_history", "ATTR_EVID_MEDICAL_HISTORY")
    _build_history_evidence(session, config, "surgical_history", "ATTR_EVID_SURGICAL_HISTORY")
    _build_family_history_evidence(session, config)
    _build_note_evidence(session, config)

    return evidence_inventory(session)


def evidence_inventory(session, tables: Optional[Sequence[str]] = None) -> pd.DataFrame:
    tables = list(
        tables
        or (
            _CANDIDATES,
            "ATTR_EVID_PATIENT",
            "ATTR_EVID_ENCOUNTER",
            "ATTR_EVID_CLAIM",
            "ATTR_EVID_LAB_RESULT",
            "ATTR_EVID_MEDICAL_HISTORY",
            "ATTR_EVID_SURGICAL_HISTORY",
            "ATTR_EVID_FAMILY_HISTORY",
            "ATTR_EVID_CLINICAL_NOTES",
        )
    )
    rows = []
    for table in tables:
        try:
            n = count_rows(session, table)
        except Exception:
            n = None
        rows.append({"table": table, "rows": n})
        print(f"{table:38s} {n if n is not None else 'MISSING'}")
    return pd.DataFrame(rows)

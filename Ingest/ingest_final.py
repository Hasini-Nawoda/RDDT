"""
Incremental ingestion: Database1 -> AI/ML staging.

CHANGE_LOG is an event log (log_id PK). Bookmark is (logged_at, log_id)
of the last event processed, not a time-only cutoff.

Each table: take the next 1M events ORDER BY logged_at, log_id (oldest
first), MERGE into staging, then move the bookmark to the last event in
that slice. Repeat until the window is empty. Join misses in a slice
block that slice's bookmark only.
"""

from snowflake.snowpark import Session

SOURCE_DB = "DATABASE1"
SOURCE_SCHEMA = "PUBLIC"          # change to actual schema name
CHANGE_LOG = f"{SOURCE_DB}.{SOURCE_SCHEMA}.CHANGE_LOG"

STAGING_DB = "MY_ANALYTICS_DB"    # change to your database
STAGING_SCHEMA = "STAGING"
WATERMARK = f"{STAGING_DB}.{STAGING_SCHEMA}.WATERMARK"
JOIN_FAILURES = f"{STAGING_DB}.{STAGING_SCHEMA}.JOIN_FAILURES"
ROWCOUNT_CHECK = f"{STAGING_DB}.{STAGING_SCHEMA}.ROWCOUNT_CHECK"
LOCK_TABLE = f"{STAGING_DB}.{STAGING_SCHEMA}.INGEST_LOCK" # someone try to run this script concurrently, this will prevent that
LOCK_NAME = "ingest_final_lock"
# Crash recovery only. Must be longer than any single 1M-event slice MERGE.
# 12 hours = crashed process
LOCK_STALE_MINUTES = 12 * 60 # crash → stuck locked → after 12 hours next run can steal and continuet

SAFETY_LAG_SECONDS = 60 # safety lag in seconds
SLICE_SIZE = 1_000_000     # CHANGE_LOG events per slice (then bookmark moves)
QUARANTINE_THRESHOLD = 3   # Patient X changed,” but Patient X is missing in the source table
                            # after 3 runs, move watermark, continue

# columns: source name == staging name 
TABLE_CONFIG = {
    "CENSUS": {
        "source_table": f"{SOURCE_DB}.{SOURCE_SCHEMA}.CENSUS",
        "staging_table": f"{STAGING_DB}.{STAGING_SCHEMA}.CENSUS_STG",
        "columns": ["PatientId", "BirthDate", "Gender", "City", "State", "FamilyId"],
        "merge_keys": ["PatientId"],
    },
    "ENCOUNTER_VISIT": {
        "source_table": f"{SOURCE_DB}.{SOURCE_SCHEMA}.ENCOUNTER_VISIT",
        "staging_table": f"{STAGING_DB}.{STAGING_SCHEMA}.ENCOUNTER_VISIT_STG",
        "columns": ["EncounterId", "PatientId", "EncounterDate"],
        "merge_keys": ["EncounterId"],
    },
    "LAB": {
        "source_table": f"{SOURCE_DB}.{SOURCE_SCHEMA}.LAB",
        "staging_table": f"{STAGING_DB}.{STAGING_SCHEMA}.LAB_STG",
        "columns": ["LabId", "EncounterId", "PatientId", "LabRequestId", "LabResultId",
                    "ObservationIdentifier", "ObservationValue", "ObservationResultStatus",
                    "ObservationDateTime", "LabResultNote"],
        "merge_keys": ["LabId"],
    },
    "SURGICAL_HISTORY": {
        "source_table": f"{SOURCE_DB}.{SOURCE_SCHEMA}.SURGICAL_HISTORY",
        "staging_table": f"{STAGING_DB}.{STAGING_SCHEMA}.SURGICAL_HISTORY_STG",
        "columns": ["SurgicalHistoryId", "EncounterId", "PatientId", "SourceCategory",
                    "Value", "SNOMED", "SecondarySNOMED", "Date"],
        "merge_keys": ["SurgicalHistoryId"],
    },
    "MEDICAL_HISTORY": {
        "source_table": f"{SOURCE_DB}.{SOURCE_SCHEMA}.MEDICAL_HISTORY",
        "staging_table": f"{STAGING_DB}.{STAGING_SCHEMA}.MEDICAL_HISTORY_STG",
        "columns": ["MedicalHistoryId", "EncounterId", "PatientId", "SourceCategory",
                    "Value", "SNOMED", "SecondarySNOMED", "Date"],
        "merge_keys": ["MedicalHistoryId"],
    },
    "FAMILY_HISTORY": {
        "source_table": f"{SOURCE_DB}.{SOURCE_SCHEMA}.FAMILY_HISTORY",
        "staging_table": f"{STAGING_DB}.{STAGING_SCHEMA}.FAMILY_HISTORY_STG",
        "columns": ["FamilyHistoryId", "EncounterId", "PatientId", "SNOMED",
                    "Condition", "Status", "FamilyMember", "Date"],
        "merge_keys": ["FamilyHistoryId"],
    },
    "CLINICAL_NOTE": {
        "source_table": f"{SOURCE_DB}.{SOURCE_SCHEMA}.CLINICAL_NOTE",
        "staging_table": f"{STAGING_DB}.{STAGING_SCHEMA}.CLINICAL_NOTE_STG",
        "columns": ["NoteId", "EncounterId", "PatientId", "NoteType",
                    "ClinicalNoteText", "Date"],
        "merge_keys": ["NoteId"],
    },
    "CLAIM": {
        "source_table": f"{SOURCE_DB}.{SOURCE_SCHEMA}.CLAIM",
        "staging_table": f"{STAGING_DB}.{STAGING_SCHEMA}.CLAIM_STG",
        "columns": ["ClaimNo", "ClaimLineNo", "PatientId", "EncounterId",
                    "ProcedureCode", "ProcedureModifier1", "ProcedureModifier2",
                    "ProcedureModifier3", "DiagnosisType", "DiagnosisCode",
                    "ProviderType", "SpecialtyCode", "SpecialtyName", "DRGCode",
                    "OtherDiagnosisCodes9", "OtherDiagnosisCodes10", "ClinicalNotes"],
        "merge_keys": ["ClaimNo", "ClaimLineNo"],  # never concatenated; DE format as-is
    },
}


def _src_stg(col):
    """Normalize a column entry to (source_name, staging_name)."""
    return col if isinstance(col, tuple) else (col, col)


# ---------------------------------------------------------------------------
# LOCK TABLE
# ---------------------------------------------------------------------------

def _dml_rows_affected(session: Session) -> int:
    """Rowcount of the previous DML statement. Snowpark collect() dict keys
    for UPDATE/MERGE are not stable; RESULT_SCAN(LAST_QUERY_ID()) is."""
    rows = session.sql("SELECT * FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))").collect()
    if not rows:
        return 0
    data = rows[0].as_dict()
    for key, val in data.items():
        if val is None:
            continue
        lowered = key.lower()
        if "updated" in lowered or "inserted" in lowered or "deleted" in lowered:
            return int(val)
    for val in data.values():
        if isinstance(val, (int, float)):
            return int(val)
    return 0


def acquire_lock(session: Session) -> bool:
    session.sql(
        f"""
        UPDATE {LOCK_TABLE}
        SET status = 'LOCKED', locked_at = CURRENT_TIMESTAMP()
        WHERE lock_name = ?
          AND (status = 'FREE'
               OR DATEDIFF('minute', locked_at, CURRENT_TIMESTAMP()) > {LOCK_STALE_MINUTES})
        """,
        params=[LOCK_NAME],
    ).collect()
    return _dml_rows_affected(session) == 1


def heartbeat(session: Session):
    session.sql(
        f"UPDATE {LOCK_TABLE} SET locked_at = CURRENT_TIMESTAMP() WHERE lock_name = ? AND status = 'LOCKED'",
        params=[LOCK_NAME],
    ).collect()


def release_lock(session: Session):
    session.sql(
        f"UPDATE {LOCK_TABLE} SET status = 'FREE' WHERE lock_name = ?", params=[LOCK_NAME]
    ).collect()


# ---------------------------------------------------------------------------
# WATERMARK
# ---------------------------------------------------------------------------

def get_watermark(session: Session, table_key: str):
    """Last processed CHANGE_LOG event. First run: 1900-01-01 + log_id 0."""
    row = session.sql(
        f"SELECT last_pulled_at, last_log_id FROM {WATERMARK} WHERE source_table = ?",
        params=[table_key],
    ).collect()
    if not row:
        return "1900-01-01 00:00:00", 0
    ts = row[0]["LAST_PULLED_AT"]
    lid = row[0]["LAST_LOG_ID"]
    if ts is None:
        ts = "1900-01-01 00:00:00"
    if lid is None:
        lid = 0
    return ts, int(lid)


def advance_watermark(session: Session, table_key: str, logged_at, log_id):
    session.sql(
        f"""
        MERGE INTO {WATERMARK} t
        USING (SELECT ? AS source_table, ? AS last_pulled_at, ? AS last_log_id) s
        ON t.source_table = s.source_table
        WHEN MATCHED THEN UPDATE SET
            last_pulled_at = s.last_pulled_at,
            last_log_id = s.last_log_id
        WHEN NOT MATCHED THEN INSERT (source_table, last_pulled_at, last_log_id)
             VALUES (s.source_table, s.last_pulled_at, s.last_log_id)
        """,
        params=[table_key, logged_at, log_id],
    ).collect()


def get_snowflake_cutoff(session: Session):
    row = session.sql(
        f"""
        SELECT DATEADD(second, -{SAFETY_LAG_SECONDS},
                        CONVERT_TIMEZONE('UTC', CURRENT_TIMESTAMP())::TIMESTAMP_NTZ) AS CUTOFF
        """
    ).collect()[0]
    return row["CUTOFF"]


# ---------------------------------------------------------------------------
# CORE
# ---------------------------------------------------------------------------

def _eq_null(left: str, right: str) -> str:
    """NULL-safe equality so ClaimLineNo (or any key) can be NULL and still match."""
    return f"EQUAL_NULL({left}, {right})"


def process_table(session: Session, table_key: str, cfg: dict, cutoff):
    keys = cfg["merge_keys"]
    pairs = [_src_stg(c) for c in cfg["columns"]]  # [(src, stg), ...]

    wm_ts, wm_id = get_watermark(session, table_key)

    if len(keys) == 1:
        join_on = _eq_null("sl.record_id", f"s.{keys[0]}")
        key_group = "sl.record_id"
    else:
        join_on = (
            f"{_eq_null('sl.record_id', f's.{keys[0]}')} AND "
            f"{_eq_null('sl.record_id_2', f's.{keys[1]}')}"
        )
        key_group = "sl.record_id, sl.record_id_2"

    col_select = ", ".join(f"s.{src} AS {stg}" for src, stg in pairs)
    stg_names = [stg for _, stg in pairs]
    update_clause = ", ".join(f"{n} = src.{n}" for n in stg_names if n not in keys)
    insert_cols = ", ".join(stg_names)
    insert_vals = ", ".join(f"src.{n}" for n in stg_names)
    merge_on = " AND ".join(_eq_null(f"tgt.{k}", f"src.{k}") for k in keys)

    temp_name = f"_ingest_tmp_{table_key.lower()}"
    slice_name = f"_ingest_sl_{table_key.lower()}"
    qtmp = f"_ingest_q_{table_key.lower()}"

    session.sql(
        f"""
        CREATE OR REPLACE TEMPORARY TABLE {qtmp} AS
        SELECT record_id, record_id_2
        FROM {JOIN_FAILURES}
        WHERE source_table = ?
        GROUP BY record_id, record_id_2
        HAVING COUNT(DISTINCT detected_at) >= {QUARANTINE_THRESHOLD}
        """,
        params=[table_key],
    ).collect()
    q_n = session.sql(f"SELECT COUNT(*) AS N FROM {qtmp}").collect()[0]["N"]
    if q_n:
        print(f"[{table_key}] {q_n} record(s) QUARANTINED (failed "
              f">= {QUARANTINE_THRESHOLD} runs). Slices still advance past them. "
              f"See {qtmp} / {JOIN_FAILURES}. Remove JOIN_FAILURES rows to retry.")

    not_quarantined = f"""
        AND NOT EXISTS (
            SELECT 1 FROM {qtmp} q
            WHERE {_eq_null("q.record_id", "sl.record_id")}
              AND {_eq_null("q.record_id_2", "sl.record_id_2")}
        )
    """

    slice_n = 0
    while True:
        session.sql(
            f"""
            CREATE OR REPLACE TEMPORARY TABLE {slice_name} AS
            SELECT cl.log_id, cl.logged_at, cl.record_id, cl.record_id_2
            FROM {CHANGE_LOG} cl
            WHERE cl.source_table = ?
              AND cl.logged_at <= ?
              AND (
                    cl.logged_at > ?
                    OR (cl.logged_at = ? AND cl.log_id > ?)
                  )
            QUALIFY ROW_NUMBER() OVER (ORDER BY cl.logged_at, cl.log_id) <= {SLICE_SIZE}
            """,
            params=[table_key, cutoff, wm_ts, wm_ts, wm_id],
        ).collect()
        heartbeat(session)

        event_n = session.sql(f"SELECT COUNT(*) AS N FROM {slice_name}").collect()[0]["N"]
        if event_n == 0:
            if slice_n == 0:
                print(f"[{table_key}] No new CHANGE_LOG events through {cutoff}.")
            break

        slice_n += 1

        session.sql(
            f"""
            CREATE OR REPLACE TEMPORARY TABLE {temp_name} AS
            SELECT {col_select}
            FROM (
                SELECT {key_group}, {col_select},
                       ROW_NUMBER() OVER (
                           PARTITION BY {key_group}
                           ORDER BY sl.logged_at DESC, sl.log_id DESC
                       ) AS rn
                FROM {slice_name} sl
                JOIN {cfg['source_table']} s ON {join_on}
                WHERE 1=1 {not_quarantined}
            )
            WHERE rn = 1
            """,
        ).collect()
        heartbeat(session)

        matched_n = session.sql(f"SELECT COUNT(*) AS N FROM {temp_name}").collect()[0]["N"]

        distinct_logged = session.sql(
            f"""
            SELECT COUNT(*) AS N FROM (
                SELECT {key_group} FROM {slice_name} sl
                WHERE 1=1 {not_quarantined}
                GROUP BY {key_group}
            )
            """,
        ).collect()[0]["N"]

        has_unresolved_failures = distinct_logged > matched_n

        if has_unresolved_failures:
            missing = distinct_logged - matched_n
            print(f"[{table_key}] slice {slice_n}: WARNING {missing} logged key(s) "
                  f"did not match source. Bookmark not moved; retry next run.")
            unmatched = f"NOT EXISTS (SELECT 1 FROM {cfg['source_table']} s WHERE {join_on})"
            session.sql(
                f"""
                INSERT INTO {JOIN_FAILURES} (source_table, record_id, record_id_2, logged_at)
                SELECT ?, sl.record_id, sl.record_id_2, sl.logged_at
                FROM {slice_name} sl
                WHERE {unmatched}
                  {not_quarantined}
                """,
                params=[table_key],
            ).collect()

        if matched_n > 0:
            session.sql(f"""
                MERGE INTO {cfg['staging_table']} tgt
                USING {temp_name} src
                ON {merge_on}
                WHEN MATCHED THEN UPDATE SET {update_clause}
                WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
            """).collect()
            heartbeat(session)

        if has_unresolved_failures:
            print(f"[{table_key}] slice {slice_n}: merged {matched_n} keys from "
                  f"{event_n} events. Watermark NOT advanced.")
            break

        last = session.sql(
            f"""
            SELECT logged_at, log_id
            FROM {slice_name}
            QUALIFY ROW_NUMBER() OVER (ORDER BY logged_at DESC, log_id DESC) = 1
            """
        ).collect()[0]
        wm_ts, wm_id = last["LOGGED_AT"], int(last["LOG_ID"])
        advance_watermark(session, table_key, wm_ts, wm_id)
        print(f"[{table_key}] slice {slice_n}: {event_n} events, merged {matched_n} keys. "
              f"Watermark -> logged_at={wm_ts} log_id={wm_id}")

    session.sql(f"DROP TABLE IF EXISTS {slice_name}").collect()
    session.sql(f"DROP TABLE IF EXISTS {temp_name}").collect()
    session.sql(f"DROP TABLE IF EXISTS {qtmp}").collect()


def validate_row_counts(session: Session):
    print("\n=== Row count check (INFORMATIONAL) ===")
    for table_key, cfg in TABLE_CONFIG.items():
        try:
            src_n = session.sql(f"SELECT COUNT(*) AS N FROM {cfg['source_table']}").collect()[0]["N"]
            stg_n = session.sql(f"SELECT COUNT(*) AS N FROM {cfg['staging_table']}").collect()[0]["N"]
            diff = int(src_n) - int(stg_n)
            status = "MATCH" if diff == 0 else "MISMATCH"
            session.sql(
                f"INSERT INTO {ROWCOUNT_CHECK} (source_table, source_count, staging_count, diff, status) "
                f"VALUES (?, ?, ?, ?, ?)",
                params=[table_key, int(src_n), int(stg_n), diff, status],
            ).collect()
            print(f"[{table_key}] source={src_n}  staging={stg_n}  diff={diff}  {status}")
        except Exception as e:
            print(f"[{table_key}] ERROR counting rows: {e}")


def run(session: Session):
    if not acquire_lock(session):
        print("Another ingestion run is in progress. Exiting.")
        return
    try:
        cutoff = get_snowflake_cutoff(session)
        for table_key, cfg in TABLE_CONFIG.items():
            try:
                process_table(session, table_key, cfg, cutoff)
            except Exception as e:
                print(f"[{table_key}] FAILED: {e}")
        validate_row_counts(session)
    finally:
        release_lock(session)


if __name__ == "__main__":
    session = Session.builder.configs({
        "account": "<your_account>",
        "user": "<your_user>",
        "role": "<your_role>",
        "warehouse": "<your_warehouse>",
        "database": STAGING_DB,
        "schema": STAGING_SCHEMA,
    }).create()

    run(session)
    session.close()

# ---------------------------------------------------------------------------
# STILL RECOMMENDED: run via a Snowflake Task (non-overlapping by default)
# rather than relying on the lock alone for concurrent manual runs.
#   CREATE OR REPLACE TASK ingest_final_task
#     WAREHOUSE = my_small_wh
#     SCHEDULE = 'USING CRON 0 6 * * * UTC'
#   AS
#     CALL run_ingest_final_procedure();
# ---------------------------------------------------------------------------
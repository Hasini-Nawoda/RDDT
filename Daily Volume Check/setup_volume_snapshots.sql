-- ============================================================================
-- ONE-TIME SETUP
-- Stores each daily volume run so the next run can diff against it.
-- Snapshots live in OUR AI/ML DB (not Data dump Database1).
-- Column names in snapshots are stable (patient_id, visit_count, ...) even if
-- the DE renames PatientId / EncounterId / VisitId in source.
-- ============================================================================

CREATE TABLE IF NOT EXISTS STAGING.VOLUME_CHECK_RUN (
    run_id         STRING PRIMARY KEY,
    checked_at     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    source_db      STRING,
    source_schema  STRING
);

CREATE TABLE IF NOT EXISTS STAGING.VOLUME_TABLE_SNAPSHOT (
    run_id                STRING,
    table_name            STRING,
    row_count             NUMBER,
    distinct_patients     NUMBER,
    distinct_encounters   NUMBER,
    distinct_record_ids   NUMBER,
    PRIMARY KEY (run_id, table_name)
);

CREATE TABLE IF NOT EXISTS STAGING.VOLUME_PATIENT_SNAPSHOT (
    run_id                    STRING,
    patient_id                STRING,
    visit_count               NUMBER,
    lab_count                 NUMBER,
    surgical_history_count    NUMBER,
    medical_history_count     NUMBER,
    family_history_count      NUMBER,
    note_count                NUMBER,
    claim_count               NUMBER,  -- unique ClaimNo + ClaimLineNo (composite key)
    PRIMARY KEY (run_id, patient_id)
);

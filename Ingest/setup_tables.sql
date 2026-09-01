-- ============================================================================
-- ONE-TIME SETUP (run in YOUR database/schema, e.g. MY_ANALYTICS_DB.STAGING)
-- ============================================================================

-- 1. WATERMARK: bookmark is the last CHANGE_LOG *event* processed, not a
--    clock cutoff. Pair is (last_pulled_at, last_log_id) = that event's
--    (logged_at, log_id)
CREATE TABLE IF NOT EXISTS STAGING.WATERMARK (
    source_table   STRING PRIMARY KEY,
    last_pulled_at TIMESTAMP_NTZ,
    last_log_id    NUMBER
);

-- If WATERMARK already existed without last_log_id:
ALTER TABLE STAGING.WATERMARK ADD COLUMN IF NOT EXISTS last_log_id NUMBER;

-- 2. JOIN_FAILURES: records CHANGE_LOG entries that could NOT be matched
--    back to the real source table (wrong key, NULL key, timing issue,
--    etc)
CREATE TABLE IF NOT EXISTS STAGING.JOIN_FAILURES (
    source_table  STRING,
    record_id     STRING,
    record_id_2   STRING,
    logged_at     TIMESTAMP_NTZ,
    detected_at   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- 3. ROWCOUNT_CHECK: completeness check log (source vs staging counts)
CREATE TABLE IF NOT EXISTS STAGING.ROWCOUNT_CHECK (
    checked_at    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    source_table  STRING,
    source_count  NUMBER,
    staging_count NUMBER,
    diff          NUMBER,
    status        STRING   -- MATCH or MISMATCH
);

-- 4. INGEST_LOCK
--    IMPORTANT: this requires exactly one seed row to exist already --
--    the script UPDATEs it, it never INSERTs. Run the seed INSERT below
--    exactly once
CREATE TABLE IF NOT EXISTS STAGING.INGEST_LOCK (
    lock_name  STRING PRIMARY KEY,
    status     STRING,   -- 'FREE' or 'LOCKED'
    locked_at  TIMESTAMP_NTZ
);

INSERT INTO STAGING.INGEST_LOCK (lock_name, status, locked_at)
SELECT 'ingest_final_lock', 'FREE', NULL
WHERE NOT EXISTS (
    SELECT 1 FROM STAGING.INGEST_LOCK WHERE lock_name = 'ingest_final_lock'
);

-- 5. Clean staging tables -- only needed columns.
--    Claim: kept as two real columns (ClaimNo, ClaimLineNo)
CREATE TABLE IF NOT EXISTS STAGING.CENSUS_STG (
    PatientId STRING PRIMARY KEY,
    BirthDate DATE, Gender STRING, City STRING, State STRING, FamilyId STRING
);

CREATE TABLE IF NOT EXISTS STAGING.ENCOUNTER_VISIT_STG (
    EncounterId STRING PRIMARY KEY,
    PatientId STRING, EncounterDate DATE
);

CREATE TABLE IF NOT EXISTS STAGING.LAB_STG (
    LabId STRING PRIMARY KEY,
    EncounterId STRING, PatientId STRING, LabRequestId STRING, LabResultId STRING,
    ObservationIdentifier STRING, ObservationValue STRING,
    ObservationResultStatus STRING, ObservationDateTime TIMESTAMP_NTZ,
    LabResultNote STRING
);

CREATE TABLE IF NOT EXISTS STAGING.SURGICAL_HISTORY_STG (
    SurgicalHistoryId STRING PRIMARY KEY,
    EncounterId STRING, PatientId STRING, SourceCategory STRING, Value STRING,
    SNOMED STRING, SecondarySNOMED STRING, Date DATE
);

CREATE TABLE IF NOT EXISTS STAGING.MEDICAL_HISTORY_STG (
    MedicalHistoryId STRING PRIMARY KEY,
    EncounterId STRING, PatientId STRING, SourceCategory STRING, Value STRING,
    SNOMED STRING, SecondarySNOMED STRING, Date DATE
);

CREATE TABLE IF NOT EXISTS STAGING.FAMILY_HISTORY_STG (
    FamilyHistoryId STRING PRIMARY KEY,
    EncounterId STRING, PatientId STRING, SNOMED STRING, Condition STRING,
    Status STRING, FamilyMember STRING, Date DATE
);

CREATE TABLE IF NOT EXISTS STAGING.CLINICAL_NOTE_STG (
    NoteId STRING PRIMARY KEY,
    EncounterId STRING, PatientId STRING, NoteType STRING,
    ClinicalNoteText STRING, Date DATE
);

CREATE TABLE IF NOT EXISTS STAGING.CLAIM_STG (
    ClaimNo STRING, ClaimLineNo STRING,
    PatientId STRING, EncounterId STRING,
    ProcedureCode STRING, ProcedureModifier1 STRING, ProcedureModifier2 STRING,
    ProcedureModifier3 STRING, DiagnosisType STRING, DiagnosisCode STRING,
    ProviderType STRING, SpecialtyCode STRING, SpecialtyName STRING,
    DRGCode STRING, OtherDiagnosisCodes9 STRING, OtherDiagnosisCodes10 STRING,
    ClinicalNotes STRING,
    PRIMARY KEY (ClaimNo, ClaimLineNo)
);

-- ============================================================================
-- REFERENCE ONLY -- hand this to your data engineer to create in Database1.
-- Do NOT run this yourself

-- ============================================================================
-- CREATE TABLE Database1.schema.CHANGE_LOG (
--     log_id             NUMBER AUTOINCREMENT START 1 INCREMENT 1,
--                         -- unique CHANGE_LOG *event* id (not PatientId).
--                         -- Must be numeric/increasing so we can ORDER BY
--                         -- logged_at, log_id and bookmark after each 1M slice.
--                         -- Do NOT use UUID here (UUID does not sort in insert order).
--     source_table       STRING,   -- 'CENSUS','ENCOUNTER_VISIT','LAB', etc.
--     record_id          STRING,   -- business key (Census: PatientId; Claim: ClaimNo)
--     record_id_2        STRING,   -- Claim only: ClaimLineNo; NULL for other tables
--     member_patient_id  STRING,   -- always populated, for cross-table tracing
--     logged_at          TIMESTAMP_NTZ DEFAULT CONVERT_TIMEZONE('UTC', CURRENT_TIMESTAMP())::TIMESTAMP_NTZ,
--     PRIMARY KEY (log_id)
-- );
--
-- NOTE: On standard Snowflake tables PRIMARY KEY is not enforced. Still:
--   - omit log_id on INSERT and let AUTOINCREMENT fill it
--   - never reuse log_id
--
-- IMPORTANT: logged_at DEFAULT is UTC. If INSERT sets logged_at explicitly,
-- use the same CONVERT_TIMEZONE('UTC', CURRENT_TIMESTAMP())::TIMESTAMP_NTZ.
-- logged_at = time this log *row* was written. rember this point at least DE forgot this point
--
-- ASK: clustering for large tables:
--   ALTER TABLE Database1.schema.CHANGE_LOG CLUSTER BY (source_table, logged_at, log_id);
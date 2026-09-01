-- ============================================================================
-- Daily volume check against the DE source (Database1).
--
-- Edit the CONFIG block only. Patient / encounter (visit) column names and
-- table names are used from there so a DE rename does not require hunting
-- through every query.
--
-- Run order:
--   1. setup_volume_snapshots.sql  (once)
--   2. This file, every day after a load
--
-- First run: snapshots only (no previous day to diff). Later runs show deltas.
-- ============================================================================

-- ========== CONFIG (edit these only) ==========
SET SOURCE_DB       = 'DATABASE1';
SET SOURCE_SCHEMA   = 'PUBLIC';
SET SNAPSHOT_DB     = 'MY_ANALYTICS_DB';
SET SNAPSHOT_SCHEMA = 'STAGING';

-- Dictionary names. Change if DE used MemberId / VisitId / PATIENT_ID / etc.
-- Claim uniqueness is ClaimNo + ClaimLineNo (composite), not ClaimNo alone.
SET PATIENT_COL     = 'PatientId';
SET ENCOUNTER_COL   = 'EncounterId';
SET CLAIM_NO_COL    = 'ClaimNo';
SET CLAIM_LINE_COL  = 'ClaimLineNo';
SET LAB_ID_COL      = 'LabId';
SET SURG_ID_COL     = 'SurgicalHistoryId';
SET MED_ID_COL      = 'MedicalHistoryId';
SET FAM_ID_COL      = 'FamilyHistoryId';
SET NOTE_ID_COL     = 'NoteId';

SET TBL_CENSUS      = 'CENSUS';
SET TBL_ENCOUNTER   = 'ENCOUNTER_VISIT';
SET TBL_LAB         = 'LAB';
SET TBL_SURG        = 'SURGICAL_HISTORY';
SET TBL_MED         = 'MEDICAL_HISTORY';
SET TBL_FAM         = 'FAMILY_HISTORY';
SET TBL_NOTE        = 'CLINICAL_NOTE';
SET TBL_CLAIM       = 'CLAIM';
-- ==============================================

SET RUN_ID = (SELECT UUID_STRING());

SET SNAP_RUN     = (SELECT $SNAPSHOT_DB || '.' || $SNAPSHOT_SCHEMA || '.VOLUME_CHECK_RUN');
SET SNAP_TABLE   = (SELECT $SNAPSHOT_DB || '.' || $SNAPSHOT_SCHEMA || '.VOLUME_TABLE_SNAPSHOT');
SET SNAP_PATIENT = (SELECT $SNAPSHOT_DB || '.' || $SNAPSHOT_SCHEMA || '.VOLUME_PATIENT_SNAPSHOT');


BEGIN
    LET source_db       STRING := (SELECT $SOURCE_DB);
    LET source_schema   STRING := (SELECT $SOURCE_SCHEMA);
    LET snapshot_db     STRING := (SELECT $SNAPSHOT_DB);
    LET snapshot_schema STRING := (SELECT $SNAPSHOT_SCHEMA);
    LET run_id          STRING := (SELECT $RUN_ID);

    LET q_pat  STRING := '"' || (SELECT $PATIENT_COL) || '"';
    LET q_enc  STRING := '"' || (SELECT $ENCOUNTER_COL) || '"';
    LET q_cno  STRING := '"' || (SELECT $CLAIM_NO_COL) || '"';
    LET q_cln  STRING := '"' || (SELECT $CLAIM_LINE_COL) || '"';
    LET q_lab  STRING := '"' || (SELECT $LAB_ID_COL) || '"';
    LET q_surg STRING := '"' || (SELECT $SURG_ID_COL) || '"';
    LET q_med  STRING := '"' || (SELECT $MED_ID_COL) || '"';
    LET q_fam  STRING := '"' || (SELECT $FAM_ID_COL) || '"';
    LET q_note STRING := '"' || (SELECT $NOTE_ID_COL) || '"';
    LET claim_key STRING := q_cno || ' || ''-'' || ' || q_cln;

    LET fqn STRING := source_db || '.' || source_schema;
    LET t_census STRING := fqn || '.' || (SELECT $TBL_CENSUS);
    LET t_enc    STRING := fqn || '.' || (SELECT $TBL_ENCOUNTER);
    LET t_lab    STRING := fqn || '.' || (SELECT $TBL_LAB);
    LET t_surg   STRING := fqn || '.' || (SELECT $TBL_SURG);
    LET t_med    STRING := fqn || '.' || (SELECT $TBL_MED);
    LET t_fam    STRING := fqn || '.' || (SELECT $TBL_FAM);
    LET t_note   STRING := fqn || '.' || (SELECT $TBL_NOTE);
    LET t_claim  STRING := fqn || '.' || (SELECT $TBL_CLAIM);

    LET snap_run     STRING := snapshot_db || '.' || snapshot_schema || '.VOLUME_CHECK_RUN';
    LET snap_table   STRING := snapshot_db || '.' || snapshot_schema || '.VOLUME_TABLE_SNAPSHOT';
    LET snap_patient STRING := snapshot_db || '.' || snapshot_schema || '.VOLUME_PATIENT_SNAPSHOT';

    EXECUTE IMMEDIATE
        'CREATE OR REPLACE TEMP TABLE tmp_table_sizes AS
         SELECT ''CENSUS'' AS table_name, COUNT(*) AS row_count,
                COUNT(DISTINCT ' || q_pat || ') AS distinct_patients,
                NULL::NUMBER AS distinct_encounters,
                COUNT(DISTINCT ' || q_pat || ') AS distinct_record_ids
         FROM ' || t_census || '
         UNION ALL
         SELECT ''ENCOUNTER_VISIT'', COUNT(*),
                COUNT(DISTINCT ' || q_pat || '),
                COUNT(DISTINCT ' || q_enc || '),
                COUNT(DISTINCT ' || q_enc || ')
         FROM ' || t_enc || '
         UNION ALL
         SELECT ''LAB'', COUNT(*),
                COUNT(DISTINCT ' || q_pat || '),
                COUNT(DISTINCT ' || q_enc || '),
                COUNT(DISTINCT ' || q_lab || ')
         FROM ' || t_lab || '
         UNION ALL
         SELECT ''SURGICAL_HISTORY'', COUNT(*),
                COUNT(DISTINCT ' || q_pat || '),
                COUNT(DISTINCT ' || q_enc || '),
                COUNT(DISTINCT ' || q_surg || ')
         FROM ' || t_surg || '
         UNION ALL
         SELECT ''MEDICAL_HISTORY'', COUNT(*),
                COUNT(DISTINCT ' || q_pat || '),
                COUNT(DISTINCT ' || q_enc || '),
                COUNT(DISTINCT ' || q_med || ')
         FROM ' || t_med || '
         UNION ALL
         SELECT ''FAMILY_HISTORY'', COUNT(*),
                COUNT(DISTINCT ' || q_pat || '),
                COUNT(DISTINCT ' || q_enc || '),
                COUNT(DISTINCT ' || q_fam || ')
         FROM ' || t_fam || '
         UNION ALL
         SELECT ''CLINICAL_NOTE'', COUNT(*),
                COUNT(DISTINCT ' || q_pat || '),
                COUNT(DISTINCT ' || q_enc || '),
                COUNT(DISTINCT ' || q_note || ')
         FROM ' || t_note || '
         UNION ALL
         SELECT ''CLAIM'', COUNT(*),
                COUNT(DISTINCT ' || q_pat || '),
                COUNT(DISTINCT ' || q_enc || '),
                COUNT(DISTINCT ' || claim_key || ')
         FROM ' || t_claim;

    EXECUTE IMMEDIATE
        'CREATE OR REPLACE TEMP TABLE tmp_patient_counts AS
         WITH census AS (
             SELECT ' || q_pat || ' AS patient_id FROM ' || t_census || '
         ),
         visits AS (
             SELECT ' || q_pat || ' AS patient_id,
                    COUNT(DISTINCT ' || q_enc || ') AS visit_count
             FROM ' || t_enc || ' GROUP BY 1
         ),
         labs AS (
             SELECT ' || q_pat || ' AS patient_id,
                    COUNT(DISTINCT ' || q_lab || ') AS lab_count
             FROM ' || t_lab || ' GROUP BY 1
         ),
         surg AS (
             SELECT ' || q_pat || ' AS patient_id,
                    COUNT(DISTINCT ' || q_surg || ') AS surgical_history_count
             FROM ' || t_surg || ' GROUP BY 1
         ),
         med AS (
             SELECT ' || q_pat || ' AS patient_id,
                    COUNT(DISTINCT ' || q_med || ') AS medical_history_count
             FROM ' || t_med || ' GROUP BY 1
         ),
         fam AS (
             SELECT ' || q_pat || ' AS patient_id,
                    COUNT(DISTINCT ' || q_fam || ') AS family_history_count
             FROM ' || t_fam || ' GROUP BY 1
         ),
         notes AS (
             SELECT ' || q_pat || ' AS patient_id,
                    COUNT(DISTINCT ' || q_note || ') AS note_count
             FROM ' || t_note || ' GROUP BY 1
         ),
         claims AS (
             SELECT ' || q_pat || ' AS patient_id,
                    COUNT(DISTINCT ' || claim_key || ') AS claim_count
             FROM ' || t_claim || ' GROUP BY 1
         )
         SELECT
             c.patient_id,
             COALESCE(v.visit_count, 0) AS visit_count,
             COALESCE(l.lab_count, 0) AS lab_count,
             COALESCE(s.surgical_history_count, 0) AS surgical_history_count,
             COALESCE(m.medical_history_count, 0) AS medical_history_count,
             COALESCE(f.family_history_count, 0) AS family_history_count,
             COALESCE(n.note_count, 0) AS note_count,
             COALESCE(cl.claim_count, 0) AS claim_count
         FROM census c
         LEFT JOIN visits v ON v.patient_id = c.patient_id
         LEFT JOIN labs l ON l.patient_id = c.patient_id
         LEFT JOIN surg s ON s.patient_id = c.patient_id
         LEFT JOIN med m ON m.patient_id = c.patient_id
         LEFT JOIN fam f ON f.patient_id = c.patient_id
         LEFT JOIN notes n ON n.patient_id = c.patient_id
         LEFT JOIN claims cl ON cl.patient_id = c.patient_id';

    EXECUTE IMMEDIATE
        'INSERT INTO ' || snap_run || ' (run_id, source_db, source_schema)
         SELECT ''' || run_id || ''', ''' || source_db || ''', ''' || source_schema || '''';

    EXECUTE IMMEDIATE
        'INSERT INTO ' || snap_table || '
         (run_id, table_name, row_count, distinct_patients, distinct_encounters, distinct_record_ids)
         SELECT ''' || run_id || ''', table_name, row_count, distinct_patients,
                distinct_encounters, distinct_record_ids
         FROM tmp_table_sizes';

    EXECUTE IMMEDIATE
        'INSERT INTO ' || snap_patient || '
         (run_id, patient_id, visit_count, lab_count, surgical_history_count,
          medical_history_count, family_history_count, note_count,
          claim_count)
         SELECT ''' || run_id || ''', patient_id, visit_count, lab_count,
                surgical_history_count, medical_history_count, family_history_count,
                note_count, claim_count
         FROM tmp_patient_counts';
END;


-- Today's table sizes
SELECT * FROM tmp_table_sizes ORDER BY table_name;

-- Today's per-patient counts
SELECT * FROM tmp_patient_counts ORDER BY visit_count DESC, patient_id;

-- Day-over-day table diff (this run vs previous run)
-- First run: prev_* is 0 and status is NEW DATA for every table.
WITH runs AS (
    SELECT run_id, checked_at,
           ROW_NUMBER() OVER (ORDER BY checked_at DESC) AS rn
    FROM IDENTIFIER($SNAP_RUN)
),
today AS (
    SELECT s.*
    FROM IDENTIFIER($SNAP_TABLE) s
    JOIN runs r ON r.run_id = s.run_id AND r.rn = 1
),
prev AS (
    SELECT s.*
    FROM IDENTIFIER($SNAP_TABLE) s
    JOIN runs r ON r.run_id = s.run_id AND r.rn = 2
)
SELECT
    t.table_name,
    t.row_count              AS today_rows,
    COALESCE(p.row_count, 0) AS prev_rows,
    t.row_count - COALESCE(p.row_count, 0) AS row_delta,
    t.distinct_patients      AS today_patients,
    COALESCE(p.distinct_patients, 0) AS prev_patients,
    t.distinct_patients - COALESCE(p.distinct_patients, 0) AS patient_delta,
    t.distinct_encounters    AS today_encounters,
    COALESCE(p.distinct_encounters, 0) AS prev_encounters,
    t.distinct_encounters - COALESCE(p.distinct_encounters, 0) AS encounter_delta,
    t.distinct_record_ids    AS today_ids,
    COALESCE(p.distinct_record_ids, 0) AS prev_ids,
    t.distinct_record_ids - COALESCE(p.distinct_record_ids, 0) AS id_delta,
    CASE WHEN t.row_count > COALESCE(p.row_count, 0) THEN 'NEW DATA'
         WHEN t.row_count < COALESCE(p.row_count, 0) THEN 'SHRANK'
         ELSE 'NO ROW CHANGE' END AS status
FROM today t
LEFT JOIN prev p ON p.table_name = t.table_name
ORDER BY table_name;

-- New patients vs previous snapshot
WITH runs AS (
    SELECT run_id, ROW_NUMBER() OVER (ORDER BY checked_at DESC) AS rn
    FROM IDENTIFIER($SNAP_RUN)
)
SELECT t.patient_id, t.visit_count, t.lab_count, t.claim_count
FROM IDENTIFIER($SNAP_PATIENT) t
JOIN runs r1 ON r1.run_id = t.run_id AND r1.rn = 1
WHERE NOT EXISTS (
    SELECT 1
    FROM IDENTIFIER($SNAP_PATIENT) p
    JOIN runs r2 ON r2.run_id = p.run_id AND r2.rn = 2
    WHERE p.patient_id = t.patient_id
)
ORDER BY t.patient_id;

-- Existing patients whose counts grew
WITH runs AS (
    SELECT run_id, ROW_NUMBER() OVER (ORDER BY checked_at DESC) AS rn
    FROM IDENTIFIER($SNAP_RUN)
),
today AS (
    SELECT s.* FROM IDENTIFIER($SNAP_PATIENT) s
    JOIN runs r ON r.run_id = s.run_id AND r.rn = 1
),
prev AS (
    SELECT s.* FROM IDENTIFIER($SNAP_PATIENT) s
    JOIN runs r ON r.run_id = s.run_id AND r.rn = 2
)
SELECT
    t.patient_id,
    t.visit_count - p.visit_count AS visit_delta,
    t.lab_count - p.lab_count AS lab_delta,
    t.surgical_history_count - p.surgical_history_count AS surgical_delta,
    t.medical_history_count - p.medical_history_count AS medical_delta,
    t.family_history_count - p.family_history_count AS family_delta,
    t.note_count - p.note_count AS note_delta,
    t.claim_count - p.claim_count AS claim_delta
FROM today t
JOIN prev p ON p.patient_id = t.patient_id
WHERE t.visit_count > p.visit_count
   OR t.lab_count > p.lab_count
   OR t.surgical_history_count > p.surgical_history_count
   OR t.medical_history_count > p.medical_history_count
   OR t.family_history_count > p.family_history_count
   OR t.note_count > p.note_count
   OR t.claim_count > p.claim_count
ORDER BY visit_delta DESC, lab_delta DESC, t.patient_id;

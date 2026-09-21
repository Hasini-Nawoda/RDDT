"""Generate comprehensive schema comparison and pipeline impact analysis workbooks.

Creates:
1. results/schema_and_data_impact_analysis.xlsx (Master unified workbook with dedicated tabs per table)
2. Individual workbooks per table in results/
   - results/claims_schema_and_data_analysis.xlsx
   - results/encounters_schema_and_data_analysis.xlsx
   - results/census_schema_and_data_analysis.xlsx
   - results/labs_schema_and_data_analysis.xlsx
   - results/surgical_history_schema_and_data_analysis.xlsx
   - results/missing_tables_impact_analysis.xlsx
"""

import os
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Color palette (Professional Healthcare / Tech Analytics)
HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")       # Dark Navy
HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
SUBHEADER_FILL = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")    # Soft Blue
SUBHEADER_FONT = Font(name="Calibri", size=11, bold=True, color="1F4E79")
SECTION_FILL = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")      # Medium Navy
SECTION_FONT = Font(name="Calibri", size=12, bold=True, color="FFFFFF")

ALERT_CRITICAL_FILL = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid") # Soft Red/Orange
ALERT_CRITICAL_FONT = Font(name="Calibri", size=10, bold=True, color="C00000")
ALERT_WARNING_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")  # Soft Yellow
ALERT_WARNING_FONT = Font(name="Calibri", size=10, bold=True, color="B25900")
ALERT_SUCCESS_FILL = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")  # Soft Green
ALERT_SUCCESS_FONT = Font(name="Calibri", size=10, bold=True, color="375623")

REGULAR_FONT = Font(name="Calibri", size=10)
BOLD_FONT = Font(name="Calibri", size=10, bold=True)
ITALIC_FONT = Font(name="Calibri", size=9, italic=True, color="595959")

THIN_BORDER = Border(
    left=Side(style='thin', color='D9D9D9'),
    right=Side(style='thin', color='D9D9D9'),
    top=Side(style='thin', color='D9D9D9'),
    bottom=Side(style='thin', color='D9D9D9')
)
DOUBLE_BOTTOM_BORDER = Border(
    left=Side(style='thin', color='D9D9D9'),
    right=Side(style='thin', color='D9D9D9'),
    top=Side(style='thin', color='D9D9D9'),
    bottom=Side(style='double', color='1F4E79')
)

def style_header_row(ws, row_idx, num_cols):
    for col in range(1, num_cols + 1):
        cell = ws.cell(row=row_idx, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
    ws.row_dimensions[row_idx].height = 28

def style_section_title(ws, row_idx, title, num_cols):
    ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=num_cols)
    cell = ws.cell(row=row_idx, column=1)
    cell.value = title
    cell.fill = SECTION_FILL
    cell.font = SECTION_FONT
    cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[row_idx].height = 26

def style_table_rows(ws, start_row, end_row, num_cols):
    for r in range(start_row, end_row + 1):
        ws.row_dimensions[r].height = 20
        for c in range(1, num_cols + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = REGULAR_FONT
            cell.border = THIN_BORDER
            if cell.value is not None:
                val_str = str(cell.value).strip()
                if val_str in ["FATAL BLOCKER", "CRITICAL", "HIGH", "100% NULL", "MISSING"]:
                    cell.fill = ALERT_CRITICAL_FILL
                    cell.font = ALERT_CRITICAL_FONT
                elif val_str in ["WARNING", "MEDIUM", "PARTIAL"]:
                    cell.fill = ALERT_WARNING_FILL
                    cell.font = ALERT_WARNING_FONT
                elif val_str in ["OK", "SUCCESS", "LOW", "100% POPULATED"]:
                    cell.fill = ALERT_SUCCESS_FILL
                    cell.font = ALERT_SUCCESS_FONT

def auto_fit_columns(ws, max_len_cap=60):
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            # Skip merged title rows
            if cell.coordinate in ws.merged_cells:
                continue
            if cell.value is not None:
                lines = str(cell.value).split('\n')
                for l in lines:
                    max_len = max(max_len, len(l))
        adjusted_width = min(max(max_len + 3, 12), max_len_cap)
        ws.column_dimensions[col_letter].width = adjusted_width

# Data definitions
SUMMARY_TABLES_DATA = [
    ["CENSUS", "CENSUS", "PRESENT (Active)", "2,794,815", "2,794,815", "FAMILYID removed in new schema; demographics largely blank; age clustered in 51-60 bracket.", "MEDIUM", "Proceed with demographics caveats; family pedigree cannot be established."],
    ["CLAIMS", "CLAIM", "PRESENT (Active)", "53,311,842", "929,356", "100% NULL dates (FROM_DATE, TO_DATE); 100% NULL procedure codes; 100% NULL notes; 22 generic COLUMN0-21 names.", "FATAL BLOCKER", "Confirmed extractor succeeds; Early Detection halts completely due to missing dates."],
    ["ENCOUNTERS", "ENCOUNTER_VISIT", "PRESENT (Active)", "17,429,113", "1,056,034", "Table renamed; 5 new columns added; 99.99999% date population; 38K future dates.", "LOW / OPPORTUNITY", "Serve as master date bridge to backfill CLAIMS dates via VISITID join."],
    ["LABS", "LAB", "PRESENT (Active)", "133,901,152", "695,413", "ObservationIdentifier contains text names ('Calcium'), NOT LOINC; no system declaration; empty notes.", "HIGH", "Biomarker elevation signals (Troponin, BNP) fail to match LOINC codes."],
    ["SURGICAL_HISTORY", "SURGICAL_HISTORY", "PRESENT (Active)", "10,000", "8,329", "7.53% NULL dates; 92.4% generic category text; 100% blank secondary SNOMED; 94% unknown encounters.", "MEDIUM", "SNOMED codes match, but 753 rows dropped due to null dates."],
    ["CLINICAL_NOTE", "CLINICAL_NOTE", "MISSING (Absent)", "0", "0", "Table completely absent in new database (SOURCE_AVAILABLE = FALSE).", "FATAL BLOCKER", "Entire NLP pipeline (spaCy / medSpaCy) cannot proceed; all note-derived findings lost."],
    ["MEDICAL_HISTORY", "MEDICAL_HISTORY", "MISSING (Absent)", "0", "0", "Table completely absent in new database (SOURCE_AVAILABLE = FALSE).", "FATAL BLOCKER", "All historical SNOMED conditions and past diagnoses cannot proceed."],
    ["FAMILY_HISTORY", "FAMILY_HISTORY", "MISSING (Absent)", "0", "0", "Table completely absent in new database (SOURCE_AVAILABLE = FALSE).", "FATAL BLOCKER", "All family history amyloidosis and neuropathy flags cannot proceed."],
    ["SOCIAL_HISTORY", "SOCIAL_HISTORY", "MISSING (Absent)", "0", "0", "Table absent; explicitly excluded from analysis per user instruction.", "N/A", "Excluded from scope per user request."],
    ["MEDICATIONS", "MEDICATIONS", "PRESENT (Inactive)", "55,652,835", "649,736", "Table present but disabled; explicitly excluded from analysis per user instruction.", "N/A", "Excluded from scope per user request."]
]

def build_summary_sheet(ws):
    ws.title = "Executive_Summary"
    ws.views.sheetView[0].showGridLines = True
    
    # Title
    ws.merge_cells("A1:H1")
    title_cell = ws.cell(row=1, column=1)
    title_cell.value = "ATTR AMYLOIDOSIS PIPELINE: SCHEMA & DATA IMPACT ANALYSIS"
    title_cell.fill = SECTION_FILL
    title_cell.font = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 36
    
    # Subtitle / Context
    ws.merge_cells("A2:H2")
    sub_cell = ws.cell(row=2, column=1)
    sub_cell.value = "Evaluation of Old Schema (legacy_ehr_v1) vs New Schema (sample_db_v1) and Data Quality Impacts on Algorithm Stages"
    sub_cell.font = ITALIC_FONT
    sub_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 20
    
    # Key Callout Box
    ws.merge_cells("A4:H5")
    callout = ws.cell(row=4, column=1)
    callout.value = (
        "CRITICAL ARCHITECTURAL FINDINGS:\n"
        "1. CLAIMS (53.3M rows): 100% of date columns are NULL. While Confirmed Amyloidosis ICD-10 extraction succeeds, the Early Detection Suspicion Pipeline completely halts because evidence qualification discards any row with UNKNOWN_AVAILABILITY_DATE.\n"
        "2. ENCOUNTERS (17.4M rows): 99.99999% date population with VISITID linking to CLAIMS.COLUMN1. This provides an immediate date backfill bridge.\n"
        "3. MISSING TABLES: CLINICAL_NOTE, MEDICAL_HISTORY, FAMILY_HISTORY, and SOCIAL_HISTORY are absent (SOURCE_AVAILABLE = FALSE). The pipeline CANNOT proceed with NLP narrative extraction, past medical history SNOMED conditions, or family history flags."
    )
    callout.fill = ALERT_WARNING_FILL
    callout.font = BOLD_FONT
    callout.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    
    # Section Header
    style_section_title(ws, 7, "1. TABLE STATUS & IMPACT MATRIX", 8)
    
    headers = [
        "Table Name", "Old Schema Name", "New Schema Status", 
        "Total Row Count", "Distinct Patients", "Primary Schema & Data Issues", 
        "Pipeline Severity", "Operational Impact & Feasibility"
    ]
    
    header_row = 8
    for c_idx, h in enumerate(headers, 1):
        ws.cell(row=header_row, column=c_idx, value=h)
    style_header_row(ws, header_row, len(headers))
    
    start_row = 9
    for r_idx, row_data in enumerate(SUMMARY_TABLES_DATA, start=start_row):
        for c_idx, val in enumerate(row_data, start=1):
            ws.cell(row=r_idx, column=c_idx, value=val)
    end_row = start_row + len(SUMMARY_TABLES_DATA) - 1
    style_table_rows(ws, start_row, end_row, len(headers))
    
    # Detailed algorithmic stages summary
    style_section_title(ws, end_row + 2, "2. ALGORITHM STAGE IMPACT SUMMARY", 8)
    stage_header_row = end_row + 3
    stage_headers = ["Stage ID", "Pipeline Stage Name", "Key Component", "Expected Input", "Actual Received Input", "Stage Status", "Failure Mechanism & Consequence", "Required Remediation"]
    for c_idx, h in enumerate(stage_headers, 1):
        ws.cell(row=stage_header_row, column=c_idx, value=h)
    style_header_row(ws, stage_header_row, len(stage_headers))
    
    stages_data = [
        ["Step 01", "Source Validation", "source_schema.py", "Declared physical tables & required columns", "4 tables missing; CLAIMS has COLUMN0-21; CENSUS lacks FAMILYID", "WARNING", "Fails if legacy_ehr_v1 profile is active; succeeds under sample_db_v1 only because missing tables are disabled.", "Keep missing tables disabled; maintain sample_db_v1 profile."],
        ["Step 02", "Candidate Retrieval", "candidate_net.py", "ICD-10, LOINC, SNOMED codes & NLP seed terms", "ICD-10 codes found in CLAIMS; SNOMED found in SURGICAL; LOINC missing; NLP text missing", "PARTIAL", "Retrieves 929K candidates from CLAIMS ICD-10 and 8.3K from SURGICAL SNOMED. Zero candidates from NLP or Labs.", "Proceed with claims candidates; accept reduced sensitivity."],
        ["Step 03", "Source Events Normalization", "source_events.py", "Normalized SourceEvents with dates, codes, text", "CLAIMS events have event_date=None, text=None; LABS has code_system=None", "PARTIAL", "Events materialized but lack dates and LOINC code systems.", "Join CLAIMS with ENCOUNTERS to assign event_date."],
        ["Step 03b", "Confirmed Amyloidosis Exclusion", "known_attr.py / known_al.py", "Exact ICD-10 codes (E85.82, E85.81, etc.)", "ICD-10 codes 100% available in CLAIMS.COLUMN8", "SUCCESS", "Succeeds completely! Confirmed extractor requires no dates, NLP, or procedures.", "No changes needed for confirmed-only pass."],
        ["Step 04", "Atom Matching", "atom_matching.py", "Structured codes & medSpaCy PhraseMatcher", "ICD-10 atoms match; SNOMED atoms match; CPT, LOINC, and NLP atoms fail", "PARTIAL", "Matches only claims ICD-10 and surgical SNOMED. Cannot match CPT or clinical narrative.", "Map text lab names to LOINC; translate CPT rules to ICD-10."],
        ["Step 05", "Evidence Qualification", "evidence_qualification.py", "Qualified evidence with valid availability_date <= cutoff", "CLAIMS availability_date is None (from null dates)", "FATAL BLOCKER", "All CLAIMS evidence marked UNKNOWN ('UNKNOWN_AVAILABILITY_DATE') and discarded!", "Backfill CLAIMS dates from ENCOUNTERS.VISITDATE."],
        ["Step 06", "Signal Evaluation", "signal_engine.py", "Qualified TRUE evidence grouped by clinical signal", "Only surgical SNOMED evidence (with valid dates) survives", "CRITICAL", "Almost all specialty signals (CTS, HF, Neuropathy) from claims fail to fire.", "Resolved once CLAIMS dates are backfilled."],
        ["Step 07", "Reasoning Buckets", "bucket_engine.py", "Buckets satisfied by qualified signals", "Insufficient signals survive evidence qualification", "CRITICAL", "Buckets cannot reach eligible thresholds.", "Resolved once CLAIMS dates are backfilled."],
        ["Step 08", "Combination Matching", "match_engine.py", "Multi-specialty rule combinations (A, B, C)", "No combinations match due to empty buckets", "CRITICAL", "Patients route to NO_MATCH or HOLD.", "Resolved once CLAIMS dates are backfilled."],
        ["Step 09-10", "Router & Verdicts", "router.py", "Phenotype verdicts (ATTRv, ATTRwt, AL)", "No phenotype passes generated for non-confirmed patients", "CRITICAL", "Early detection produces 0 flagged patients.", "Resolved once CLAIMS dates are backfilled."],
        ["Step 11", "Patient Profiles & Export", "patient_profile.py", "Rich medical profiles, timeline, demographics", "Timeline has empty dates; demographics lack family_id/city", "DEGRADED", "Profiles lack clinical depth and family linkages.", "Impute dates and display available demographics."]
    ]
    
    stage_start_row = stage_header_row + 1
    for r_idx, row_data in enumerate(stages_data, start=stage_start_row):
        for c_idx, val in enumerate(row_data, start=1):
            ws.cell(row=r_idx, column=c_idx, value=val)
    stage_end_row = stage_start_row + len(stages_data) - 1
    style_table_rows(ws, stage_start_row, stage_end_row, len(stage_headers))
    
    auto_fit_columns(ws)

def build_table_sheet(ws, table_key, table_display_name, old_table_name, new_table_name, columns_comparison, empirical_findings, schema_issues, data_issues, algorithm_impacts, required_changes):
    ws.title = f"Table_{table_key.upper()}"
    ws.views.sheetView[0].showGridLines = True
    
    # Title
    ws.merge_cells("A1:G1")
    title_cell = ws.cell(row=1, column=1)
    title_cell.value = f"TABLE ANALYSIS: {table_display_name} ({old_table_name} vs {new_table_name})"
    title_cell.fill = SECTION_FILL
    title_cell.font = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    title_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 32
    
    current_row = 3
    
    # Section 1: Empirical Data Overview
    style_section_title(ws, current_row, "1. EMPIRICAL DATA & RUNTIME OVERVIEW", 7)
    current_row += 1
    ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=7)
    ov_cell = ws.cell(row=current_row, column=1, value=empirical_findings)
    ov_cell.font = BOLD_FONT
    ov_cell.fill = SUBHEADER_FILL
    ov_cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[current_row].height = 42
    current_row += 2
    
    # Section 2: Schema Comparison Side-by-Side
    style_section_title(ws, current_row, "2. PREVIOUS SCHEMA VS CURRENT SCHEMA (SIDE-BY-SIDE)", 7)
    current_row += 1
    
    headers = [
        "Logical Field Name", "Previous Physical Column", "Current Physical Column", 
        "Previous Data Type", "Current Data Type", "Schema Change Status", "Pipeline Role & Expectation"
    ]
    for c_idx, h in enumerate(headers, 1):
        ws.cell(row=current_row, column=c_idx, value=h)
    style_header_row(ws, current_row, len(headers))
    current_row += 1
    
    start_table_row = current_row
    for r_idx, col_data in enumerate(columns_comparison, start=start_table_row):
        for c_idx, val in enumerate(col_data, start=1):
            ws.cell(row=r_idx, column=c_idx, value=val)
    end_table_row = start_table_row + len(columns_comparison) - 1
    style_table_rows(ws, start_table_row, end_table_row, len(headers))
    current_row = end_table_row + 2
    
    # Section 3: Issues with Current Schema
    style_section_title(ws, current_row, "3. ISSUES WITH CURRENT SCHEMA (AS PER ALGORITHM REQUIREMENTS)", 7)
    current_row += 1
    for item in schema_issues:
        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=7)
        cell = ws.cell(row=current_row, column=1, value=f"• {item}")
        cell.font = REGULAR_FONT
        cell.border = THIN_BORDER
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.row_dimensions[current_row].height = 24
        current_row += 1
    current_row += 1
    
    # Section 4: Issues with Current Data
    style_section_title(ws, current_row, "4. ISSUES WITH CURRENT DATA (EMPIRICAL FINDINGS)", 7)
    current_row += 1
    for item in data_issues:
        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=7)
        cell = ws.cell(row=current_row, column=1, value=f"• {item}")
        cell.font = REGULAR_FONT
        cell.border = THIN_BORDER
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.row_dimensions[current_row].height = 24
        current_row += 1
    current_row += 1
    
    # Section 5: How It Affects Our Algorithm
    style_section_title(ws, current_row, "5. HOW IT AFFECTS OUR CURRENT ALGORITHM & PIPELINE", 7)
    current_row += 1
    for item in algorithm_impacts:
        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=7)
        cell = ws.cell(row=current_row, column=1, value=f"• {item}")
        cell.font = REGULAR_FONT
        cell.border = THIN_BORDER
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.row_dimensions[current_row].height = 28
        current_row += 1
    current_row += 1
    
    # Section 6: What Changes We Need to Make to Our Algorithm
    style_section_title(ws, current_row, "6. WHAT CHANGES WE NEED TO MAKE TO OUR ALGORITHM / PIPELINE", 7)
    current_row += 1
    for item in required_changes:
        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=7)
        cell = ws.cell(row=current_row, column=1, value=f"• {item}")
        cell.font = BOLD_FONT
        cell.fill = ALERT_SUCCESS_FILL
        cell.border = THIN_BORDER
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.row_dimensions[current_row].height = 28
        current_row += 1
        
    auto_fit_columns(ws)

def build_missing_tables_sheet(ws):
    ws.title = "Missing_Tables"
    ws.views.sheetView[0].showGridLines = True
    
    ws.merge_cells("A1:G1")
    title_cell = ws.cell(row=1, column=1)
    title_cell.value = "ANALYSIS OF MISSING TABLES (SOURCE_AVAILABLE = FALSE)"
    title_cell.fill = SECTION_FILL
    title_cell.font = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    title_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 32
    
    current_row = 3
    style_section_title(ws, current_row, "1. STATUS OF EXPECTED VS RECEIVED TABLES", 7)
    current_row += 1
    
    headers = ["Expected Table Name", "Previous Role", "Current Status", "Row Count", "Key Clinical Features Lost", "Algorithm Impact", "Feasibility / Recommendation"]
    for c_idx, h in enumerate(headers, 1):
        ws.cell(row=current_row, column=c_idx, value=h)
    style_header_row(ws, current_row, len(headers))
    current_row += 1
    
    missing_data = [
        ["CLINICAL_NOTE", "Unstructured EHR narrative (physician notes, discharge summaries, cardiology consults)", "MISSING", "0 rows", "All medSpaCy / spaCy PhraseMatcher NLP text. Loss of bilateral CTS text, apical sparing, neuropathy, gastrointestinal symptoms, negation/uncertainty context.", "FATAL BLOCKER: Entire narrative pipeline cannot run. No NLP-derived clinical atoms can be qualified.", "CANNOT PROCEED with NLP features. Only structured claims/surgical history can be used."],
        ["MEDICAL_HISTORY", "Past medical history conditions, diagnoses, and procedures", "MISSING", "0 rows", "Historical SNOMED codes (heart failure, neuropathy, autonomic dysfunction, spinal stenosis) and free-text condition descriptions.", "FATAL BLOCKER: No historical SNOMED conditions can be loaded or matched.", "CANNOT PROCEED with medical history features. Pipeline must rely solely on CLAIMS billing diagnoses."],
        ["FAMILY_HISTORY", "Family medical history and pedigree relations", "MISSING", "0 rows", "SNOMED codes and condition terms for family members (hereditary amyloidosis, sudden cardiac death, neuropathy).", "FATAL BLOCKER: Family history amyloidosis screening route cannot fire.", "CANNOT PROCEED with family history rules. ATTRv must be scored on individual findings alone."],
        ["SOCIAL_HISTORY", "Social habits, smoking, alcohol, lifestyle", "MISSING", "0 rows", "Excluded from scope per user request.", "NO IMPACT: Excluded from analysis.", "No action needed (out of scope)."]
    ]
    
    start_table_row = current_row
    for r_idx, row_val in enumerate(missing_data, start=start_table_row):
        for c_idx, val in enumerate(row_val, start=1):
            ws.cell(row=r_idx, column=c_idx, value=val)
    end_table_row = start_table_row + len(missing_data) - 1
    style_table_rows(ws, start_table_row, end_table_row, len(headers))
    current_row = end_table_row + 2
    
    style_section_title(ws, current_row, "2. CORE CONCLUSION & ARCHITECTURAL DIRECTIVE", 7)
    current_row += 1
    
    conclusions = [
        "As confirmed by the data analysis workbooks in results/, CLINICAL_NOTE, MEDICAL_HISTORY, and FAMILY_HISTORY are completely absent from the current database snapshot (SOURCE_AVAILABLE = FALSE).",
        "The current V4 algorithm was originally designed expecting a complete EHR data lake where clinical text notes and past histories corroborate billing codes.",
        "BECAUSE THESE TABLES ARE MISSING, WE CANNOT PROCEED with any pipeline features, signals, or rules that depend on them.",
        "Specifically: (1) The spaCy/medSpaCy narrative extraction pipeline cannot be executed; (2) Historical SNOMED conditions cannot be retrieved; (3) Family pedigree risk rules cannot fire.",
        "Operational Directive: The algorithm must be adapted to run strictly on structured CLAIMS, ENCOUNTERS, LABS, and SURGICAL_HISTORY. All clinical atoms that rely exclusively on NLP or medical history must be disabled or flagged as unfulfillable gaps."
    ]
    
    for item in conclusions:
        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=7)
        cell = ws.cell(row=current_row, column=1, value=f"• {item}")
        cell.font = BOLD_FONT
        cell.fill = ALERT_CRITICAL_FILL if "CANNOT PROCEED" in item else SUBHEADER_FILL
        cell.border = THIN_BORDER
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.row_dimensions[current_row].height = 26
        current_row += 1
        
    auto_fit_columns(ws)

# Table Details
CLAIMS_COLS = [
    ["patient_id", "Member/PatientId", "COLUMN0", "TEXT", "TEXT", "Renamed (Positional)", "Primary patient identifier; 100% populated (929,356 distinct patients)."],
    ["encounter_id", "EncounterId/VisitId", "COLUMN1", "TEXT", "TEXT", "Renamed (Positional)", "Encounter link; 100% populated (8,153,451 distinct). Links directly to ENCOUNTERS.VISITID."],
    ["claim_no", "N/A", "COLUMN2", "N/A", "TEXT", "Added in New", "Claim number; 100% populated (11,103,649 distinct)."],
    ["claim_line_no", "N/A", "COLUMN3", "N/A", "TEXT", "Added in New", "Claim line number; 100% populated (53,311,842 unique lines)."],
    ["claim_status", "N/A", "COLUMN4", "N/A", "TEXT", "Added in New", "Claim status; 100% populated (93.16% 'Closed')."],
    ["date_incurred_from", "FromDate", "COLUMN5", "TEXT", "TEXT", "Renamed (Positional)", "Service start date; 100% NULL in current data (53,311,842 nulls)."],
    ["date_incurred_to", "ToDate", "COLUMN6", "TEXT", "TEXT", "Renamed (Positional)", "Service end date; 100% NULL in current data (53,311,842 nulls)."],
    ["diagnosis_type", "DiagnosisType", "COLUMN7", "TEXT", "TEXT", "Renamed (Positional)", "Diagnosis code system; 100% populated with 'ICD-10-CM'."],
    ["diagnosis_code", "DiagnosisCode", "COLUMN8", "TEXT", "TEXT", "Renamed (Positional)", "Primary diagnosis code; 100% populated with 26,653 distinct ICD-10 codes."],
    ["provider_npi", "N/A", "COLUMN9", "N/A", "TEXT", "Added in New", "Rendering NPI; 100% populated (5,511 distinct, 6.2M '*Unspecified')."],
    ["provider_name", "N/A", "COLUMN10", "N/A", "TEXT", "Added in New", "Provider name; 100% empty string."],
    ["provider_type", "ProviderType", "COLUMN11", "TEXT", "TEXT", "Renamed (Positional)", "Provider taxonomy/type; 100% empty string."],
    ["specialty_code", "SpecialtyCode", "COLUMN12", "TEXT", "TEXT", "Renamed (Positional)", "Specialty code; 100% empty string."],
    ["specialty_name", "SpecialtyName", "COLUMN13", "TEXT", "TEXT", "Renamed (Positional)", "Specialty name; 100% empty string."],
    ["provider_tax_id", "N/A", "COLUMN14", "N/A", "TEXT", "Added in New", "Tax ID; 100% empty string."],
    ["drg_code", "DRGCode", "COLUMN15", "TEXT", "TEXT", "Renamed (Positional)", "Inpatient DRG; 100% NULL / empty string."],
    ["rev_code", "N/A", "COLUMN16", "N/A", "TEXT", "Added in New", "Revenue code; 100% NULL / empty string."],
    ["other_diagnosis_9", "OtherDiagnosisCodes9", "COLUMN17", "TEXT", "TEXT", "Renamed (Positional)", "Secondary ICD-9 codes; 100% NULL."],
    ["other_diagnosis_10", "OtherDiagnosisCodes10", "COLUMN18", "TEXT", "TEXT", "Renamed (Positional)", "Secondary ICD-10 codes; 100% NULL."],
    ["from_date", "FromDate", "COLUMN19", "TEXT", "TEXT", "Renamed (Positional)", "Pipeline encounter window from_date; 100% NULL."],
    ["to_date", "ToDate", "COLUMN20", "TEXT", "TEXT", "Renamed (Positional)", "Pipeline encounter window to_date; 100% NULL."],
    ["clinical_notes", "ClinicalNotes", "COLUMN21", "TEXT", "TEXT", "Renamed (Positional)", "Free text clinical narrative on claim; 100% NULL / empty string."],
    ["procedure_code", "ProcedureCode", "UNMAPPED", "TEXT", "N/A", "REMOVED / UNMAPPED", "CPT/HCPCS procedure codes; completely absent/unmapped in new schema."],
    ["procedure_modifier_1", "ProcedureModifier1", "UNMAPPED", "TEXT", "N/A", "REMOVED / UNMAPPED", "Procedure modifier 1; completely unmapped / 100% null."],
    ["procedure_modifier_2", "ProcedureModifier2", "UNMAPPED", "TEXT", "N/A", "REMOVED / UNMAPPED", "Procedure modifier 2; completely unmapped / 100% null."],
    ["procedure_modifier_3", "ProcedureModifier3", "UNMAPPED", "TEXT", "N/A", "REMOVED / UNMAPPED", "Procedure modifier 3; completely unmapped / 100% null."]
]

CLAIMS_EMPIRICAL = "Total Rows: 53,311,842 | Unique Patients: 929,356 | Unique Claims: 11,103,649 | Distinct ICD-10 Codes: 26,653 | Dates Populated: 0% (53.3M NULLS) | Procedure Codes: 0% (53.3M NULLS) | Notes: 0% (53.3M BLANK)"
CLAIMS_SCHEMA_ISSUES = [
    "Generic positional column naming (COLUMN0..COLUMN21) replaces meaningful clinical column names, making queries highly brittle to upstream schema shifts.",
    "No procedure code (CPT/HCPCS) column is mapped or exposed in the new schema.",
    "Procedure modifiers (1, 2, 3) are completely unmapped.",
    "Both primary service dates (COLUMN5, COLUMN6) and encounter window dates (COLUMN19, COLUMN20) exist as columns but are entirely unpopulated."
]
CLAIMS_DATA_ISSUES = [
    "100% NULL Dates: Every single date field (COLUMN5, COLUMN6, COLUMN19, COLUMN20) is NULL across all 53,311,842 rows.",
    "100% NULL Procedure Codes: 0 procedure codes are present, preventing CPT-based surgical or diagnostic identification.",
    "100% NULL Clinical Notes: COLUMN21 is entirely blank, providing zero narrative text for NLP PhraseMatcher.",
    "100% Blank Provider Specialty: COLUMN12 and COLUMN13 are empty strings, preventing provider specialty routing (Cardiology vs Orthopedics vs Neurology).",
    "100% NULL Secondary Diagnoses: COLUMN17 (ICD-9) and COLUMN18 (ICD-10) are completely unpopulated."
]
CLAIMS_ALGORITHM_IMPACTS = [
    "Confirmed Amyloidosis Extractor (First-Run): SUCCEEDS. Matches exact ICD-10 codes (E85.82, E85.81, E85.4, etc.) in COLUMN8. It does not require dates, NLP, or CPT codes.",
    "Early Detection Suspicion Pipeline: COMPLETELY BLOCKS / FAILS. In source_events.py, event_date is None. In extraction_contract.py, available_date is None.",
    "In evidence_qualification.py (lines 465-467): _on_or_before(available_date, cutoff) evaluates to None. All evidence is assigned status UNKNOWN with reason 'UNKNOWN_AVAILABILITY_DATE'.",
    "Because evidence status is UNKNOWN, eligible_evidence() returns None. No clinical atom can ever fire from claims data.",
    "CPT Atoms Blocked: Atoms requiring procedure codes (e.g. Carpal Tunnel Release CPT 64721, Heart Biopsy CPT 93505) cannot match at all.",
    "Specialty Routing Blocked: The algorithm cannot verify whether a claim originated from a Cardiologist or Neurologist."
]
CLAIMS_CHANGES_NEEDED = [
    "DATE BACKFILL BRIDGE: Join CLAIMS with ENCOUNTERS on CLAIMS.COLUMN1 = ENCOUNTERS.VISITID and impute event_date and available_date from ENCOUNTERS.VISITDATE. (Verified: 100% of CLAIMS have COLUMN1, and ENCOUNTERS is 99.99999% populated with valid dates).",
    "RELAX REQUIRED COLUMNS: In v4/config/source_schema.json, remove from_date and to_date from required_columns for claims so that initial validation does not fail.",
    "DIAGNOSIS-BASED SPECIALTY INFERENCE: Infer clinical specialty from ICD-10 code chapters (e.g., I44/I50 -> Cardiology; M75/G56 -> Orthopedics; G60/G62 -> Neurology) rather than relying on empty specialty columns.",
    "CPT TO ICD-10 FALLBACK: For procedure atoms, allow equivalent ICD-10 diagnosis codes (e.g. bilateral CTS diagnosis G56.03 instead of CPT 64721) to satisfy the clinical signal."
]

ENCOUNTERS_COLS = [
    ["encounter_id", "EncounterId/VisitId", "VISITID", "TEXT", "TEXT", "Renamed", "Primary visit identifier; 100% populated (16,334,743 unique encounters)."],
    ["patient_id", "Member/PatientId", "PATIENTID", "TEXT", "TEXT", "Renamed", "Patient identifier; 100% populated (1,056,034 unique patients)."],
    ["encounter_date", "Encounter/Visit Date", "VISITDATE", "TEXT", "TEXT", "Renamed", "Clinical encounter date; 99.99999% populated (only 1 null out of 17.4M rows!)."],
    ["facility_id", "N/A", "FACILITYID", "N/A", "TEXT", "Added in New", "Facility identifier; 100% populated (690 distinct facilities)."],
    ["physician_id", "N/A", "PHYSICIANID", "N/A", "TEXT", "Added in New", "Physician identifier; 100% populated (3,753 distinct physicians)."],
    ["visit_type", "N/A", "TYPE", "N/A", "TEXT", "Added in New", "Visit setting/type (e.g. Inpatient, Outpatient, Emergency, Hemodialysis)."],
    ["financial_class", "N/A", "FINANCIALCLASS", "N/A", "TEXT", "Added in New", "Payer financial class (e.g. Medicaid Managed Care, Medicare)."],
    ["status", "N/A", "STATUS", "N/A", "TEXT", "Added in New", "Encounter status (73.32% 'Completed', 'Cancelled', etc.)."]
]
ENCOUNTERS_EMPIRICAL = "Total Rows: 17,429,113 | Unique Encounters: 16,334,743 | Unique Patients: 1,056,034 | Date Population: 99.99999% (1 NULL) | Date Span: 2004-06-11 to 2027-09-09 | Future Dates: 38,878 rows"
ENCOUNTERS_SCHEMA_ISSUES = [
    "Table renamed from ENCOUNTER_VISIT to ENCOUNTERS.",
    "Column names renamed from mixed-case slashes ('EncounterId/VisitId') to clean uppercase ('VISITID', 'VISITDATE').",
    "5 new columns added (FACILITYID, PHYSICIANID, TYPE, FINANCIALCLASS, STATUS) which provide valuable context but were not in the legacy schema."
]
ENCOUNTERS_DATA_ISSUES = [
    "38,878 future dates (dates after 2026-09-21, up to 2027-09-09) representing future scheduled visits.",
    "1,094,370 duplicate encounter IDs where multiple rows share the same VISITID across different service types or statuses."
]
ENCOUNTERS_ALGORITHM_IMPACTS = [
    "Table is currently disabled (enabled: false) in sample_db_v1 because V4 did not directly extract clinical atoms from encounters.",
    "Future dates, if ingested without filtering, would be flagged as is_future=True and marked 'FUTURE_OR_PLANNED_MENTION' (UNKNOWN) in evidence qualification.",
    "Encounter dates are the critical missing link for CLAIMS. Because CLAIMS.COLUMN1 connects to ENCOUNTERS.VISITID, keeping ENCOUNTERS disabled deprives CLAIMS of its only date source."
]
ENCOUNTERS_CHANGES_NEEDED = [
    "ENABLE TABLE: In v4/config/source_schema.json, set encounter.enabled = true.",
    "IMPLEMENT DATE BRIDGE JOIN: Use ENCOUNTERS as a date lookup table to populate CLAIMS event_date and available_date.",
    "FILTER FUTURE DATES: Add WHERE VISITDATE <= CURRENT_DATE() when querying ENCOUNTERS to exclude future scheduled appointments.",
    "DE-DUPLICATE GRAIN: Aggregate by VISITID taking MIN(VISITDATE) to ensure clean 1:1 encounter date mapping."
]

CENSUS_COLS = [
    ["patient_id", "Member/PatientId", "PATIENTID", "TEXT", "TEXT", "Renamed", "Unique patient identifier; 100% populated (2,794,815 distinct patients)."],
    ["birth_date", "BirthDate", "BIRTHDATE", "TEXT", "TEXT", "Renamed", "Patient birth date; 96.64% populated (94,045 missing). Clustered in 51-60 age group."],
    ["gender", "Gender", "GENDER", "TEXT", "TEXT", "Renamed", "Patient gender; 100% populated (51.29% F, 48.05% M, 0.66% U)."],
    ["city", "City", "CITY", "TEXT", "TEXT", "Renamed", "Patient city; 100% blank strings in data."],
    ["state", "State", "STATE", "TEXT", "TEXT", "Renamed", "Patient state; 100% blank strings in data."],
    ["family_id", "FamilyId", "UNMAPPED", "TEXT", "N/A", "REMOVED IN NEW", "Family/household identifier; COMPLETELY ABSENT in new schema."],
    ["firstname", "N/A", "FIRSTNAME", "N/A", "TEXT", "Added in New", "First name; 100% blank strings in data."],
    ["lastname", "N/A", "LASTNAME", "N/A", "TEXT", "Added in New", "Last name; 100% blank strings in data."],
    ["middleinitial", "N/A", "MIDDLEINITIAL", "N/A", "TEXT", "Added in New", "Middle initial; 100% blank strings in data."],
    ["address", "N/A", "ADDRESS", "N/A", "TEXT", "Added in New", "Street address; 100% blank strings in data."],
    ["county", "N/A", "COUNTY", "N/A", "TEXT", "Added in New", "County; 100% blank strings in data."],
    ["country", "N/A", "COUNTRY", "N/A", "TEXT", "Added in New", "Country; 100% blank strings in data."],
    ["zipcode", "N/A", "ZIPCODE", "N/A", "TEXT", "Added in New", "Zip code; 100% blank strings in data."],
    ["deathdate", "N/A", "DEATHDATE", "N/A", "TEXT", "Added in New", "Date of death; 100% blank strings in data."],
    ["ombethnicity", "N/A", "OMBETHNICITY", "N/A", "TEXT", "Added in New", "Ethnicity (Hispanic or Latino, Not Hispanic, Unknown)."],
    ["ombrace", "N/A", "OMBRACE", "N/A", "TEXT", "Added in New", "Race (White, Black, Asian, Unknown)."],
    ["begineffectivedate", "N/A", "BEGINEFFECTIVEDATE", "N/A", "TEXT", "Added in New", "Enrollment start date; mostly blank."],
    ["endeffectivedate", "N/A", "ENDEFFECTIVEDATE", "N/A", "TEXT", "Added in New", "Enrollment end date; mostly blank."]
]
CENSUS_EMPIRICAL = "Total Rows: 2,794,815 | Unique Patients: 2,794,815 (1:1 Grain) | Gender: 51.3% F, 48.1% M | Birth Date: 96.64% populated (94K null) | Family ID: 0% (Column Absent) | Demographics: 100% Blank Strings"
CENSUS_SCHEMA_ISSUES = [
    "FAMILYID column is completely removed from the new CENSUS schema.",
    "legacy_ehr_v1 profile had family_id in required_columns; running legacy config immediately fails schema validation.",
    "Numerous new demographic columns added (FIRSTNAME, LASTNAME, ADDRESS, etc.) but not populated with real data."
]
CENSUS_DATA_ISSUES = [
    "94,045 patients (3.36%) have missing birth dates.",
    "96.64% of patients fall into a single age band (51-60 years, clustered around 1970 birth dates) due to synthetic generation.",
    "All geographic columns (CITY, STATE, ZIPCODE, ADDRESS) are empty strings.",
    "Complete absence of family linkage across all 2.79M patients."
]
CENSUS_ALGORITHM_IMPACTS = [
    "Schema Validation: Handled in sample_db_v1 by removing family_id from required_columns.",
    "Hereditary ATTRv Pedigree Scoring: Cannot link index patients to relatives with amyloidosis or cardiomyopathy.",
    "Age-based Gates: The heavy 51-60 clustering means almost all patients satisfy the adult/elderly age gates for ATTRwt/ATTRv.",
    "Patient Profile Reports: Demographics section in viewer JSONL/CSV exports will show blank city, state, and family_id."
]
CENSUS_CHANGES_NEEDED = [
    "CONFIRM OPTIONAL DEMOGRAPHICS: Keep family_id, city, and state strictly optional in all pipeline schemas.",
    "ADJUST ATTRv HEREDITARY RULES: Evaluate ATTRv suspicion based purely on clinical symptom combinations (neuropathy + CTS + cardiomyopathy) rather than expecting family pedigree corroboration.",
    "SAFE AGE HANDLING: For the 94,045 patients with missing birth dates, treat age gates as non-blocking UNKNOWN rather than disqualifying."
]

LABS_COLS = [
    ["patient_id", "Member/PatientId", "PATIENTID", "TEXT", "TEXT", "Renamed", "Patient identifier; 100% populated (695,413 unique patients)."],
    ["encounter_id", "EncounterId/VisitId", "ENCOUNTERKEY", "TEXT", "TEXT", "Renamed", "Encounter key; 100% populated (3,856,970 unique encounters)."],
    ["lab_id", "LabId", "LABTESTKEY", "TEXT", "TEXT", "Renamed", "Lab test key; 100% populated (24,483,028 unique)."],
    ["lab_request_id", "LabRequestId", "LABREQUESTID", "TEXT", "TEXT", "Renamed", "Order request ID; 100% empty strings in data."],
    ["lab_result_id", "LabResultId", "LABRESULTID", "TEXT", "TEXT", "Renamed", "Result ID; 100% empty strings in data."],
    ["observation_identifier", "ObservationIdentifier", "OBSERVATIONIDENTIFIER", "TEXT", "TEXT", "Unchanged", "Test identifier; contains TEXT NAMES ('Calcium', 'Troponin'), NOT LOINC codes!"],
    ["observation_value", "ObservationValue", "OBSERVATIONVALUE", "TEXT", "TEXT", "Unchanged", "Test numeric/text result value; 100% populated."],
    ["result_status", "ObservationResultStatus", "OBSERVATIONRESULTSTATUS", "TEXT", "TEXT", "Renamed", "Result status; 99.73% 'Final result'."],
    ["observation_datetime", "ObservationDateTime", "OBSERVATIONDATETIME", "TEXT", "TEXT", "Renamed", "Observation timestamp; 100% populated (0 nulls). Range: 2018 to 2026."],
    ["lab_result_note", "LabResultNote", "LABRESULTNOTE", "TEXT", "TEXT", "Renamed", "Lab narrative note; 100% empty strings in data."],
    ["performed_datetime", "N/A", "PERFORMEDDATETIME", "N/A", "TEXT", "Added in New", "Test performed timestamp; 100% populated."],
    ["analysis_datetime", "N/A", "ANALYSISDATETIME", "N/A", "TEXT", "Added in New", "Test analysis timestamp; 57,545 nulls."],
    ["common_name", "N/A", "OBSERVATIONIDENTIFIERCOMMONNAME", "N/A", "TEXT", "Added in New", "Short abbreviation name (e.g. 'LYMPHS ABS AUTO')."]
]
LABS_EMPIRICAL = "Total Rows: 133,901,152 | Unique Patients: 695,413 | Unique Encounters: 3,856,970 | Dates Populated: 100% (0 NULLS) | Observation Values: 100% Populated | Identifier Format: Plain Text (7,668 names) | Notes: 100% Empty"
LABS_SCHEMA_ISSUES = [
    "No ObservationIdentifierSystem column exists to indicate whether the test is LOINC, local hospital code, or CPT.",
    "LABREQUESTID and LABRESULTID exist as columns but are 100% empty strings.",
    "LABRESULTNOTE exists as a column but is 100% empty strings."
]
LABS_DATA_ISSUES = [
    "OBSERVATIONIDENTIFIER contains free-text test names (e.g., 'Calcium', 'Glucose Accuchek POC', 'Troponin I') instead of standardized LOINC codes (e.g. 2160-0, 10839-9).",
    "100% Empty Notes: LABRESULTNOTE contains zero narrative text, preventing any NLP keyword or PhraseMatcher extraction.",
    "String Formatted Values: OBSERVATIONVALUE contains numeric strings, requiring explicit casting before threshold comparisons."
]
LABS_ALGORITHM_IMPACTS = [
    "LOINC Structured Matching Fails: In extraction_contract.py, LOINC routes expect exact code matches. In source_events.py, code_system is set to None because no system is declared. All LOINC atoms fail to match.",
    "Cardiac Biomarker Gates Fail: ATTRwt and AL biomarker criteria (elevated Troponin, elevated NT-proBNP) cannot fire through structured LOINC rules.",
    "Lab Narrative NLP Fails: The secondary route for clinical notes via lab_result_note produces zero matches because all note fields are empty strings."
]
LABS_CHANGES_NEEDED = [
    "TEXT-TO-LOINC MAPPING TABLE: Create a translation dictionary mapping top test names in OBSERVATIONIDENTIFIER to standard LOINC codes (e.g., 'Troponin I' -> 10839-9, 'NT-proBNP' -> 33762-6, 'Protein, Urine' -> 2888-6).",
    "OVERRIDE CODE SYSTEM: In source_events.py, set code_system = 'LOINC' whenever a recognized test name is mapped.",
    "SAFE NUMERIC CASTING: Apply TRY_TO_DOUBLE(OBSERVATIONVALUE) in Snowflake SQL queries to enable numeric biomarker thresholding.",
    "ENABLE LABS IN CONFIG: Once the mapping is in place, set lab.enabled = true in source_schema.json."
]

SURGICAL_COLS = [
    ["patient_id", "Member/PatientId", "PATIENTID", "TEXT", "TEXT", "Renamed", "Patient identifier; 100% populated (8,329 unique patients)."],
    ["encounter_id", "EncounterId/VisitId", "ENCOUNTERID", "TEXT", "TEXT", "Renamed", "Encounter link; 608 distinct, but ~94% are 'Unknown'."],
    ["record_id", "SurgicalHistoryId", "SURGICALHISTORYID", "TEXT", "TEXT", "Renamed", "Surgical record ID; 100% populated (8,732 unique)."],
    ["source_category", "Source/Category", "SOURCE", "TEXT", "TEXT", "Renamed", "Source category; 92.47% 'Surgical History Procedure'."],
    ["value", "Value", "CATEGORY", "TEXT", "TEXT", "Renamed", "Procedure text; 92.4% generic string 'SURGICAL HISTORY PROCEDURES'."],
    ["snomed", "SNOMED", "SNOMED", "TEXT", "TEXT", "Unchanged", "SNOMED CT procedure code; 100% populated (48 unique codes)."],
    ["secondary_snomed", "Secondary SNOMED", "SECONDARY_SNOMED", "TEXT", "TEXT", "Renamed", "Secondary SNOMED code; 100% empty strings."],
    ["event_date", "Date", "DATE", "TEXT", "TEXT", "Renamed", "Procedure date; 753 rows (7.53%) are NULL! Populated: 2020 to 2026."]
]
SURGICAL_EMPIRICAL = "Total Rows: 10,000 | Unique Patients: 8,329 | Unique Encounters: 608 (94% 'Unknown') | SNOMED Population: 100% (48 unique codes) | Date Population: 92.47% (753 NULLS) | Secondary SNOMED: 100% Empty"
SURGICAL_SCHEMA_ISSUES = [
    "Physical column names normalized to uppercase without slashes.",
    "value is mapped to CATEGORY in sample_db_v1, which only contains generic text ('SURGICAL HISTORY PROCEDURES').",
    "SECONDARY_SNOMED exists as a column but has 0 populated values."
]
SURGICAL_DATA_ISSUES = [
    "753 rows (7.53%) have NULL DATE, which causes them to be dropped by the pipeline.",
    "94% of encounter IDs are 'Unknown', preventing linkage to encounter metadata.",
    "Procedure descriptions in CATEGORY lack clinical specificity (92.4% generic text)."
]
SURGICAL_ALGORITHM_IMPACTS = [
    "SNOMED Code Matching SUCCEEDS: For the 9,247 rows with valid dates, the 48 SNOMED codes match configured orthopedic/cardiac procedure atoms.",
    "Null Date Drop: The 753 rows with NULL DATE fail evidence qualification with UNKNOWN_AVAILABILITY_DATE. 753 surgical procedures are lost.",
    "Secondary SNOMED and Narrative: Zero secondary SNOMED matches and zero NLP text matches from this table."
]
SURGICAL_CHANGES_NEEDED = [
    "DATE IMPUTATION FOR SURGICAL HISTORY: For the 753 rows with null dates, allow an imputation strategy (e.g. earliest encounter date or census effective date) or allow non-recency-gated atoms to fire without strict dates.",
    "ENABLE SURGICAL HISTORY IN CONFIG: Set surgical_history.enabled = true in source_schema.json so it participates in candidate retrieval and event normalization.",
    "MAP TO SNOMED DIRECTLY: Ensure SNOMED CT is the primary extraction route for surgical history rather than relying on the generic CATEGORY text."
]

def generate_all_workbooks():
    results_dir = r"c:\Users\PAMALI\Desktop\RDDT\results"
    os.makedirs(results_dir, exist_ok=True)
    
    # 1. Master unified workbook
    master_path = os.path.join(results_dir, "schema_and_data_impact_analysis.xlsx")
    wb_master = openpyxl.Workbook()
    
    # Summary
    ws_summary = wb_master.active
    build_summary_sheet(ws_summary)
    
    # Claims
    ws_claims = wb_master.create_sheet("Table_CLAIMS")
    build_table_sheet(ws_claims, "claims", "CLAIMS", "CLAIM", "CLAIMS", CLAIMS_COLS, CLAIMS_EMPIRICAL, CLAIMS_SCHEMA_ISSUES, CLAIMS_DATA_ISSUES, CLAIMS_ALGORITHM_IMPACTS, CLAIMS_CHANGES_NEEDED)
    
    # Encounters
    ws_enc = wb_master.create_sheet("Table_ENCOUNTERS")
    build_table_sheet(ws_enc, "encounters", "ENCOUNTERS", "ENCOUNTER_VISIT", "ENCOUNTERS", ENCOUNTERS_COLS, ENCOUNTERS_EMPIRICAL, ENCOUNTERS_SCHEMA_ISSUES, ENCOUNTERS_DATA_ISSUES, ENCOUNTERS_ALGORITHM_IMPACTS, ENCOUNTERS_CHANGES_NEEDED)
    
    # Census
    ws_cen = wb_master.create_sheet("Table_CENSUS")
    build_table_sheet(ws_cen, "census", "CENSUS", "CENSUS", "CENSUS", CENSUS_COLS, CENSUS_EMPIRICAL, CENSUS_SCHEMA_ISSUES, CENSUS_DATA_ISSUES, CENSUS_ALGORITHM_IMPACTS, CENSUS_CHANGES_NEEDED)
    
    # Labs
    ws_labs = wb_master.create_sheet("Table_LABS")
    build_table_sheet(ws_labs, "labs", "LABS", "LAB", "LABS", LABS_COLS, LABS_EMPIRICAL, LABS_SCHEMA_ISSUES, LABS_DATA_ISSUES, LABS_ALGORITHM_IMPACTS, LABS_CHANGES_NEEDED)
    
    # Surgical History
    ws_surg = wb_master.create_sheet("Table_SURGICAL_HISTORY")
    build_table_sheet(ws_surg, "surgical_history", "SURGICAL_HISTORY", "SURGICAL_HISTORY", "SURGICAL_HISTORY", SURGICAL_COLS, SURGICAL_EMPIRICAL, SURGICAL_SCHEMA_ISSUES, SURGICAL_DATA_ISSUES, SURGICAL_ALGORITHM_IMPACTS, SURGICAL_CHANGES_NEEDED)
    
    # Missing Tables
    ws_miss = wb_master.create_sheet("Missing_Tables")
    build_missing_tables_sheet(ws_miss)
    
    wb_master.save(master_path)
    print(f"Saved master workbook to: {master_path}")
    
    # 2. Individual workbooks per table
    tables_to_generate = [
        ("claims_schema_and_data_analysis.xlsx", "claims", "CLAIMS", "CLAIM", "CLAIMS", CLAIMS_COLS, CLAIMS_EMPIRICAL, CLAIMS_SCHEMA_ISSUES, CLAIMS_DATA_ISSUES, CLAIMS_ALGORITHM_IMPACTS, CLAIMS_CHANGES_NEEDED),
        ("encounters_schema_and_data_analysis.xlsx", "encounters", "ENCOUNTERS", "ENCOUNTER_VISIT", "ENCOUNTERS", ENCOUNTERS_COLS, ENCOUNTERS_EMPIRICAL, ENCOUNTERS_SCHEMA_ISSUES, ENCOUNTERS_DATA_ISSUES, ENCOUNTERS_ALGORITHM_IMPACTS, ENCOUNTERS_CHANGES_NEEDED),
        ("census_schema_and_data_analysis.xlsx", "census", "CENSUS", "CENSUS", "CENSUS", CENSUS_COLS, CENSUS_EMPIRICAL, CENSUS_SCHEMA_ISSUES, CENSUS_DATA_ISSUES, CENSUS_ALGORITHM_IMPACTS, CENSUS_CHANGES_NEEDED),
        ("labs_schema_and_data_analysis.xlsx", "labs", "LABS", "LAB", "LABS", LABS_COLS, LABS_EMPIRICAL, LABS_SCHEMA_ISSUES, LABS_DATA_ISSUES, LABS_ALGORITHM_IMPACTS, LABS_CHANGES_NEEDED),
        ("surgical_history_schema_and_data_analysis.xlsx", "surgical_history", "SURGICAL_HISTORY", "SURGICAL_HISTORY", "SURGICAL_HISTORY", SURGICAL_COLS, SURGICAL_EMPIRICAL, SURGICAL_SCHEMA_ISSUES, SURGICAL_DATA_ISSUES, SURGICAL_ALGORITHM_IMPACTS, SURGICAL_CHANGES_NEEDED)
    ]
    
    for filename, t_key, t_display, old_t, new_t, cols, emp, s_issues, d_issues, algo_imp, chg in tables_to_generate:
        p = os.path.join(results_dir, filename)
        wb = openpyxl.Workbook()
        ws = wb.active
        build_table_sheet(ws, t_key, t_display, old_t, new_t, cols, emp, s_issues, d_issues, algo_imp, chg)
        wb.save(p)
        print(f"Saved individual workbook to: {p}")
        
    # Missing tables individual workbook
    miss_path = os.path.join(results_dir, "missing_tables_impact_analysis.xlsx")
    wb_m = openpyxl.Workbook()
    ws_m = wb_m.active
    build_missing_tables_sheet(ws_m)
    wb_m.save(miss_path)
    print(f"Saved missing tables workbook to: {miss_path}")

if __name__ == "__main__":
    generate_all_workbooks()

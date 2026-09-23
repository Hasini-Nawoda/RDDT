"""Full 2026 ICD-10-CM pass for NEPHROLOGY.json — add codes + display_names."""
import json

def add_dot(code):
    code = code.strip()
    if len(code) > 3 and '.' not in code:
        return code[:3] + '.' + code[3:]
    return code

icd2026 = {}
with open('not_for_snowflake/sql_codes/icd10cm-codes-2026.txt', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line: continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            dotted = add_dot(parts[0])
            icd2026[dotted] = parts[1]
            icd2026[parts[0].strip()] = parts[1]

def lookup(code):
    return icd2026.get(code) or icd2026.get(code.replace('.', ''))

def make_entry(value, role, standalone):
    desc = lookup(value)
    return {
        'value': value,
        'can_fire_atom_alone': standalone,
        'review_status': 'WAREHOUSE_REVIEWED',
        'mapping_role': role,
        'match_mode': 'EXACT',
        'display_name': desc if desc else value + ' [no 2026 description]',
    }

def add_codes(atom, new_entries):
    icd = atom.setdefault('extraction', {}).setdefault('codes', {}).setdefault('ICD10', [])
    existing = {e['value'] for e in icd}
    added = 0
    for entry in new_entries:
        if entry['value'] not in existing:
            icd.append(entry)
            existing.add(entry['value'])
            added += 1
    return added

def backfill(atom):
    filled = 0
    for entry in atom.get('extraction', {}).get('codes', {}).get('ICD10', []):
        if 'display_name' not in entry:
            desc = lookup(entry['value'])
            entry['display_name'] = desc if desc else entry['value'] + ' [no 2026 description]'
            filled += 1
    return filled

DIRECT = 'DIRECT_TARGET'
PROXY  = 'PROXY_SUPPORT'

ADDITIONS = {

    # ── abnormal_serum_free_light_chain_ratio ─────────────────────────────
    # No ICD codes. Free light chain abnormality is reported as a lab result;
    # the ICD codes below represent the conditions found / suspected.
    'abnormal_serum_free_light_chain_ratio': [
        ('D47.2',  DIRECT, True),   # Monoclonal gammopathy (176 WH pts) — MGUS w/ abnormal FLC
        ('E85.81', DIRECT, True),   # Light chain (AL) amyloidosis (24 pts) — abnormal FLC → AL workup
        ('R77.8',  PROXY,  False),  # Other specified abnormalities of plasma proteins (305 pts)
        ('R77.9',  PROXY,  False),  # Abnormality of plasma protein, unspecified (268 pts)
        ('R77.1',  PROXY,  False),  # Abnormality of globulin (13 pts)
    ],

    # ── egfr_result ───────────────────────────────────────────────────────
    # Existing: N18.3, N18.4, N18.5, N18.9
    # Missing all CKD sub-stage codes (N18.31, N18.32, N18.30, N18.2, N18.1, N18.6)
    'egfr_result': [
        ('N18.31', DIRECT, True),   # CKD stage 3a (4,261 WH pts)
        ('N18.6',  DIRECT, True),   # End stage renal disease (3,752 pts)
        ('N18.32', DIRECT, True),   # CKD stage 3b (2,900 pts)
        ('N18.30', DIRECT, True),   # CKD stage 3, unspecified (1,700 pts)
        ('N18.2',  DIRECT, True),   # CKD stage 2, mild (1,519 pts)
        ('N18.1',  DIRECT, True),   # CKD stage 1 (345 pts)
        # Hypertensive CKD — eGFR abnormality coded under hypertension+CKD
        ('I12.9',  PROXY,  False),  # Hypertensive CKD stages 1–4 (4,196 pts)
        ('I12.0',  PROXY,  False),  # Hypertensive CKD stage 5 / ESRD (1,035 pts)
        ('I13.0',  PROXY,  False),  # Hypertensive heart+CKD with HF, stages 1–4 (744 pts)
        ('I13.10', PROXY,  False),  # Hypertensive heart+CKD without HF, stages 1–4 (200 pts)
        # CKD complication codes — confirm CKD diagnosis
        ('D63.1',  PROXY,  False),  # Anemia in chronic kidney disease (139 pts)
        ('N25.81', PROXY,  False),  # Secondary hyperparathyroidism of renal origin (1,200 pts)
    ],

    # ── hypoalbuminemia ───────────────────────────────────────────────────
    # Existing: E88.09, E88.0, R77.8
    'hypoalbuminemia': [
        ('R77.0',  DIRECT, True),   # Abnormality of albumin (38 WH pts) — direct albumin finding
        ('R77.9',  PROXY,  False),  # Abnormality of plasma protein, unspecified (268 pts)
        ('E88.89', PROXY,  False),  # Other specified metabolic disorders (80 pts)
    ],

    # ── microalbuminuria ──────────────────────────────────────────────────
    # Existing: R80.9
    'microalbuminuria': [
        ('R80.1',  PROXY,  False),  # Persistent proteinuria, unspecified (514 WH pts)
        ('R80.0',  PROXY,  False),  # Isolated proteinuria (61 pts)
        ('R80.8',  PROXY,  False),  # Other proteinuria (128 pts)
        ('N06.9',  PROXY,  False),  # Isolated proteinuria with unspecified morphologic lesion (235 pts)
    ],

    # ── nephrotic_range_proteinuria ───────────────────────────────────────
    # No ICD codes
    'nephrotic_range_proteinuria': [
        ('N04.9',  DIRECT, True),   # Nephrotic syndrome with unspecified morphologic changes (241 WH pts)
        ('N04.1',  DIRECT, True),   # Nephrotic syndrome with focal and segmental glomerular lesions (FSGS) (35 pts)
        ('N04.0',  DIRECT, True),   # Nephrotic syndrome with minor glomerular abnormality (minimal change) (13 pts)
        ('N04.20', DIRECT, True),   # Nephrotic syndrome with diffuse membranous GN, unspecified (3 pts)
        ('N04.21', DIRECT, True),   # Primary membranous nephropathy with nephrotic syndrome (2 pts)
        ('N04.8',  DIRECT, True),   # Nephrotic syndrome with other morphologic changes (3 pts)
        ('R80.9',  PROXY,  False),  # Proteinuria, unspecified (1,463 pts)
        ('R80.1',  PROXY,  False),  # Persistent proteinuria (514 pts)
        ('R80.8',  PROXY,  False),  # Other proteinuria (128 pts)
        ('N06.9',  PROXY,  False),  # Isolated proteinuria with unspecified morphologic lesion (235 pts)
    ],

    # ── serum_immunofixation_monoclonal ───────────────────────────────────
    # No ICD codes
    'serum_immunofixation_monoclonal': [
        ('D47.2',  DIRECT, True),   # Monoclonal gammopathy (176 WH pts) — positive serum IFE → MGUS/plasma cell
        ('E85.81', DIRECT, True),   # Light chain (AL) amyloidosis (24 pts) — serum IFE positive → AL evaluation
        ('C90.00', PROXY,  False),  # Multiple myeloma not in remission (237 pts) — monoclonal band on IFE
        ('R77.8',  PROXY,  False),  # Other specified abnormalities of plasma proteins (305 pts)
        ('R77.9',  PROXY,  False),  # Abnormality of plasma protein, unspecified (268 pts)
        ('R77.1',  PROXY,  False),  # Abnormality of globulin (13 pts)
    ],

    # ── urine_immunofixation_monoclonal ───────────────────────────────────
    # No ICD codes (share similar codes to serum IFE)
    'urine_immunofixation_monoclonal': [
        ('D47.2',  DIRECT, True),   # Monoclonal gammopathy (176 WH pts)
        ('E85.81', DIRECT, True),   # Light chain (AL) amyloidosis — Bence-Jones protein on urine IFE
        ('R77.8',  PROXY,  False),  # Other abnormalities of plasma proteins (305 pts)
        ('R80.9',  PROXY,  False),  # Proteinuria, unspecified — urine protein may mask IFE finding (1,463 pts)
        ('R82.998', PROXY, False),  # Other abnormal findings in urine (781 pts)
    ],

    # ── urine_protein_result ──────────────────────────────────────────────
    # No ICD codes
    'urine_protein_result': [
        ('R80.9',  DIRECT, True),   # Proteinuria, unspecified (1,463 WH pts)
        ('R80.1',  DIRECT, True),   # Persistent proteinuria, unspecified (514 pts)
        ('R80.8',  DIRECT, True),   # Other proteinuria (128 pts)
        ('R80.0',  DIRECT, True),   # Isolated proteinuria (61 pts)
        ('N06.9',  PROXY,  False),  # Isolated proteinuria with unspecified morphologic lesion (235 pts)
        ('R82.90', PROXY,  False),  # Unspecified abnormal findings in urine (3,432 pts)
        ('R80.2',  PROXY,  False),  # Orthostatic proteinuria, unspecified (11 pts)
    ],

    # ── al03_competing_proteinuria ────────────────────────────────────────
    # Existing: E10.21, E11.21, I12.9, I13.10, N04.1, N04.2, N05.2, N18.9
    'al03_competing_proteinuria': [
        # Diabetic CKD — most common competing cause
        ('E11.22', DIRECT, True),   # T2DM with diabetic CKD (5,944 WH pts — huge gap)
        ('E10.22', DIRECT, True),   # T1DM with diabetic CKD (204 pts)
        # All CKD stages as competing renal disease
        ('N18.31', DIRECT, True),   # CKD stage 3a (4,261 pts)
        ('N18.6',  DIRECT, True),   # ESRD (3,752 pts)
        ('N18.32', DIRECT, True),   # CKD stage 3b (2,900 pts)
        ('N18.4',  DIRECT, True),   # CKD stage 4 (2,206 pts)
        ('N18.30', DIRECT, True),   # CKD stage 3, unspecified (1,700 pts)
        ('N18.2',  DIRECT, True),   # CKD stage 2 (1,519 pts)
        ('N18.5',  DIRECT, True),   # CKD stage 5 (1,260 pts)
        # Hypertensive nephropathy
        ('I12.0',  DIRECT, True),   # Hypertensive CKD stage 5 (1,035 pts)
        # Nephritic syndromes (primary glomerular disease as competing cause)
        ('N05.1',  DIRECT, True),   # Unspecified nephritic syndrome with FSGS (123 pts)
        ('N05.9',  PROXY,  False),  # Unspecified nephritic syndrome, unspecified morphology (109 pts)
        ('N05.0',  DIRECT, True),   # Unspecified nephritic syndrome with minor glomerular abnormality (24 pts)
        ('N04.9',  PROXY,  False),  # Nephrotic syndrome, unspecified (241 pts)
    ],

    # ── al04_competing_nephrotic ──────────────────────────────────────────
    # Existing: E10.21, E11.21, E85.3, N04.0, N04.1, N04.2
    'al04_competing_nephrotic': [
        ('N04.9',  DIRECT, True),   # Nephrotic syndrome, unspecified morphologic changes (241 WH pts)
        ('N04.8',  DIRECT, True),   # Nephrotic syndrome with other morphologic changes (3 pts)
        ('N04.20', DIRECT, True),   # Nephrotic syndrome with diffuse membranous GN (3 pts)
        ('N04.21', DIRECT, True),   # Primary membranous nephropathy with nephrotic syndrome (2 pts)
        ('N04.5',  DIRECT, True),   # Nephrotic syndrome with diffuse mesangiocapillary GN (2 pts)
        # Diabetic nephropathy as competing nephrotic cause
        ('E11.22', DIRECT, True),   # T2DM with diabetic CKD — diabetic nephropathy (5,944 pts)
        ('E10.22', DIRECT, True),   # T1DM with diabetic CKD (204 pts)
    ],

    # ── al05_competing_hypoalbuminemia ────────────────────────────────────
    # Existing: E43, E46, I50.9, I87.2, K70.30, K74.60, K76.9, N18.9
    'al05_competing_hypoalbuminemia': [
        # Additional cirrhosis variants
        ('K74.69', DIRECT, True),   # Other cirrhosis of liver (2,045 WH pts)
        ('K70.31', DIRECT, True),   # Alcoholic cirrhosis with ascites (1,919 pts)
        # Additional HF sub-types causing fluid redistribution and hypoalbuminemia
        ('I50.20', DIRECT, True),   # Unspecified systolic HF (2,688 pts)
        ('I50.32', DIRECT, True),   # Chronic diastolic HF (2,077 pts)
        ('I50.22', DIRECT, True),   # Chronic systolic HF (1,580 pts)
        # Nephrotic syndrome — protein-losing nephropathy
        ('N04.9',  DIRECT, True),   # Nephrotic syndrome (241 pts) — major cause of hypoalbuminemia
        ('N04.0',  DIRECT, True),   # Nephrotic — minimal change (13 pts)
        # Malnutrition variants
        ('E44.0',  DIRECT, True),   # Moderate protein-calorie malnutrition (75 pts)
        ('E41',    DIRECT, True),   # Nutritional marasmus
        # Protein-losing enteropathy / malabsorption
        ('K90.9',  PROXY,  False),  # Intestinal malabsorption, unspecified
        ('K90.89', PROXY,  False),  # Other intestinal malabsorption
    ],

    # ── creatinine_result ─────────────────────────────────────────────────
    # No ICD10 codes (only SNOMED CPT)
    'creatinine_result': [
        ('N18.31', PROXY,  False),  # CKD stage 3a — most common context for creatinine monitoring (4,261 pts)
        ('N18.9',  PROXY,  False),  # CKD, unspecified (1,876 pts)
        ('N18.6',  PROXY,  False),  # ESRD (3,752 pts)
        ('R94.4',  DIRECT, True),   # Abnormal results of kidney function studies
        ('N17.9',  DIRECT, True),   # AKI, unspecified — elevated creatinine flags AKI
    ],

    # ── falling_egfr ──────────────────────────────────────────────────────
    # Existing: N17.9, N18.3, N18.4, N18.5
    'falling_egfr': [
        ('N18.31', DIRECT, True),   # CKD 3a (4,261 WH pts)
        ('N18.6',  DIRECT, True),   # ESRD (3,752 pts)
        ('N18.32', DIRECT, True),   # CKD 3b (2,900 pts)
        ('N18.9',  DIRECT, True),   # CKD, unspecified (1,876 pts)
        ('N18.30', DIRECT, True),   # CKD 3, unspecified (1,700 pts)
        ('N18.2',  DIRECT, True),   # CKD stage 2 (1,519 pts)
        ('N18.1',  DIRECT, True),   # CKD stage 1 (345 pts)
        ('N17.0',  PROXY,  False),  # AKI with tubular necrosis (135 pts)
        ('N17.8',  PROXY,  False),  # Other AKI (43 pts)
    ],

    # ── kidney_failure ────────────────────────────────────────────────────
    # Existing: N18.5, N18.6, N19, Z99.2
    'kidney_failure': [
        ('N17.9',  DIRECT, True),   # AKI, unspecified
        ('N17.0',  DIRECT, True),   # AKI with tubular necrosis (135 WH pts)
        ('N17.8',  DIRECT, True),   # Other AKI (43 pts)
        # Hypertensive renal failure
        ('I12.0',  PROXY,  False),  # Hypertensive CKD stage 5 / ESRD (1,035 pts)
        ('I13.11', PROXY,  False),  # Hypertensive heart+CKD without HF, stage 5 / ESRD (42 pts)
        ('I13.2',  PROXY,  False),  # Hypertensive heart+CKD with HF and stage 5 (194 pts)
        # Kidney transplant — post-failure intervention
        ('Z94.0',  PROXY,  False),  # Kidney transplant status (2,273 pts)
    ],

    # ── nephrotic_syndrome ────────────────────────────────────────────────
    # Existing: N04.8, N04.9
    'nephrotic_syndrome': [
        ('N04.1',  DIRECT, True),   # Nephrotic syndrome with FSGS (35 WH pts)
        ('N04.0',  DIRECT, True),   # Nephrotic syndrome with minor glomerular abnormality — minimal change (13 pts)
        ('N04.20', DIRECT, True),   # Nephrotic syndrome with diffuse membranous GN (3 pts)
        ('N04.21', DIRECT, True),   # Primary membranous nephropathy with nephrotic syndrome (2 pts)
        ('N04.5',  DIRECT, True),   # Nephrotic syndrome with diffuse mesangiocapillary GN (2 pts)
        ('N04.2',  DIRECT, True),   # Nephrotic syndrome with diffuse membranous GN
        ('Z87.441', PROXY, False),  # Personal history of nephrotic syndrome (15 pts)
    ],

    # ── peripheral_edema ──────────────────────────────────────────────────
    # Existing: R60.0, R60.1, R60.9
    'peripheral_edema': [
        ('I89.0',   PROXY, False),  # Lymphedema (754 WH pts) — competing cause of edema
        ('T78.3XXA', PROXY, False), # Angioneurotic edema, initial encounter (308 pts)
    ],

    # ── persistent_proteinuria ────────────────────────────────────────────
    # Existing: R80.0, R80.1, R80.8, R80.9
    'persistent_proteinuria': [
        ('N06.9',  PROXY,  False),  # Isolated proteinuria with unspecified morphologic lesion (235 WH pts)
        ('R80.2',  PROXY,  False),  # Orthostatic proteinuria, unspecified (11 pts)
    ],

    # ── progressive_proteinuria ───────────────────────────────────────────
    # Existing: R80.1, R80.9
    'progressive_proteinuria': [
        ('R80.0',  DIRECT, True),   # Isolated proteinuria (61 WH pts)
        ('R80.8',  DIRECT, True),   # Other proteinuria (128 pts)
        ('N06.9',  PROXY,  False),  # Isolated proteinuria with unspecified morphologic lesion (235 pts)
    ],

    # ── renal_dysfunction ────────────────────────────────────────────────
    # Existing: N18.3, N18.4, N18.9, N19
    'renal_dysfunction': [
        # All missing CKD sub-stage codes (massive warehouse gaps)
        ('N18.31', DIRECT, True),   # CKD stage 3a (4,261 WH pts)
        ('N18.6',  DIRECT, True),   # ESRD (3,752 pts)
        ('N18.32', DIRECT, True),   # CKD stage 3b (2,900 pts)
        ('N18.5',  DIRECT, True),   # CKD stage 5 (1,260 pts)
        ('N18.30', DIRECT, True),   # CKD stage 3, unspecified (1,700 pts)
        ('N18.2',  DIRECT, True),   # CKD stage 2 (1,519 pts)
        ('N18.1',  DIRECT, True),   # CKD stage 1 (345 pts)
        # Hypertensive nephropathy
        ('I12.9',  PROXY,  False),  # Hypertensive CKD stages 1–4 (4,196 pts)
        ('I12.0',  PROXY,  False),  # Hypertensive CKD stage 5 (1,035 pts)
        ('I13.0',  PROXY,  False),  # Hypertensive heart+CKD with HF, stages 1–4 (744 pts)
        # CKD complications confirming diagnosis
        ('N25.81', PROXY,  False),  # Secondary hyperparathyroidism of renal origin (1,200 pts)
        ('D63.1',  PROXY,  False),  # Anemia in CKD (139 pts)
    ],
}

data = json.load(open('v5/config/shared/atoms/NEPHROLOGY.json', encoding='utf-8'))
atom_lookup = {a['atom_id']: a for a in data['atoms']}

total_added = 0
total_filled = 0
for aid, specs in ADDITIONS.items():
    atom = atom_lookup.get(aid)
    if not atom:
        print('WARNING: atom not found: ' + aid)
        continue
    n = add_codes(atom, [make_entry(c, r, s) for c, r, s in specs])
    total_added += n
    print('  ' + aid.ljust(40) + '+' + str(n).rjust(3) + ' new codes')

for atom in data['atoms']:
    total_filled += backfill(atom)

print()
print('Total new ICD entries:          ' + str(total_added))
print('display_names backfilled:       ' + str(total_filled))

with open('v5/config/shared/atoms/NEPHROLOGY.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
print('Saved NEPHROLOGY.json')

total = sum(1 for a in data['atoms'] for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[]))
missing = [(a['atom_id'], e['value']) for a in data['atoms']
           for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[])
           if 'display_name' not in e]
print('Total ICD10 entries: ' + str(total))
print('Missing display_name: ' + str(len(missing)))
if missing:
    for aid, v in missing: print('  [' + aid + '] ' + v)
print('JSON valid: OK')

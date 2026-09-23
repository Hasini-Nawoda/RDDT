"""Full 2026 ICD-10-CM pass for GENERAL_MEDICINE.json — add codes + display_names."""
import json, csv

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
    e = {
        'value': value,
        'can_fire_atom_alone': standalone,
        'review_status': 'WAREHOUSE_REVIEWED',
        'mapping_role': role,
        'match_mode': 'EXACT',
        'display_name': desc if desc else value + ' [no 2026 description]',
    }
    return e

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

def backfill_display_names(atom):
    filled = 0
    for entry in atom.get('extraction', {}).get('codes', {}).get('ICD10', []):
        if 'display_name' not in entry:
            desc = lookup(entry['value'])
            entry['display_name'] = desc if desc else entry['value'] + ' [no 2026 description]'
            filled += 1
    return filled

DIRECT = 'DIRECT_TARGET'
PROXY  = 'PROXY_SUPPORT'
SUPP   = 'SUPPORTING'

ADDITIONS = {

    # ── declining_bmi ──────────────────────────────────────────────────────
    # Atom had NO ICD10 codes at all
    'declining_bmi': [
        ('R63.4',  DIRECT, True),   # Abnormal weight loss (3,558 WH pts)
        ('R63.6',  DIRECT, True),   # Underweight (806 pts)
        ('R64',    DIRECT, True),   # Cachexia (check description)
        ('R63.0',  PROXY,  False),  # Anorexia / loss of appetite (1,262 pts)
        ('R63.8',  PROXY,  False),  # Other symptoms re food/fluid intake (542 pts)
        ('E43',    PROXY,  False),  # Severe protein-calorie malnutrition (203 pts)
        ('E46',    PROXY,  False),  # Unspecified protein-calorie malnutrition (200 pts)
        ('E44.0',  PROXY,  False),  # Moderate protein-calorie malnutrition
        ('E41',    PROXY,  False),  # Nutritional marasmus
        # Low-BMI adult Z68 codes as proxy — point-in-time low BMI implies weight loss trajectory
        ('Z68.1',  PROXY,  False),  # BMI 19.9 or less, adult (underweight)
        ('Z68.20', PROXY,  False),  # BMI 20.0-20.9, adult
        ('Z68.21', PROXY,  False),  # BMI 21.0-21.9, adult
    ],

    # ── al34_competing_edema ────────────────────────────────────────────────
    'al34_competing_edema': [
        # Heart failure sub-types (beyond I50.9 already configured)
        ('I50.20', DIRECT, True),   # Unspecified systolic HF (2,688 pts)
        ('I50.32', DIRECT, True),   # Chronic diastolic HF (2,077 pts)
        ('I50.22', DIRECT, True),   # Chronic systolic HF (1,580 pts)
        ('I50.42', DIRECT, True),   # Chronic combined HF (1,426 pts)
        ('I50.23', DIRECT, True),   # Acute on chronic systolic HF (856 pts)
        ('I50.43', DIRECT, True),   # Acute on chronic combined HF (517 pts)
        ('I50.30', DIRECT, True),   # Unspecified diastolic HF (652 pts)
        ('I50.33', DIRECT, True),   # Acute on chronic diastolic HF (570 pts)
        ('I50.21', DIRECT, True),   # Acute systolic HF (516 pts)
        ('I50.41', DIRECT, True),   # Acute combined HF (165 pts)
        ('I11.0',  DIRECT, True),   # Hypertensive heart disease with HF (2,429 pts)
        ('I13.0',  DIRECT, True),   # Hypertensive heart+CKD with HF (744 pts)
        ('I13.2',  DIRECT, True),   # Hypertensive heart+CKD stage 5 with HF (194 pts)
        # CKD stages (beyond N18.9 already configured)
        ('N18.31', DIRECT, True),   # CKD stage 3a (4,261 pts)
        ('N18.6',  DIRECT, True),   # End stage renal disease (3,752 pts)
        ('N18.32', DIRECT, True),   # CKD stage 3b (2,900 pts)
        ('N18.4',  DIRECT, True),   # CKD stage 4 (2,206 pts)
        ('N18.30', DIRECT, True),   # CKD stage 3, unspecified (1,700 pts)
        ('N18.2',  DIRECT, True),   # CKD stage 2 (1,519 pts)
        ('N18.5',  DIRECT, True),   # CKD stage 5 (1,260 pts)
        ('N18.1',  DIRECT, True),   # CKD stage 1 (mild)
        # Nephrotic syndrome — major cause of edema
        ('N04.9',  DIRECT, True),   # Nephrotic syndrome, unspecified
        ('N04.0',  DIRECT, True),   # Nephrotic syndrome with minor glomerular abnormality
        # Cirrhosis variants (beyond K70.30 and K74.60 already configured)
        ('K74.69', DIRECT, True),   # Other cirrhosis of liver (2,045 pts)
        ('K70.31', DIRECT, True),   # Alcoholic cirrhosis with ascites (1,919 pts)
        ('K76.6',  DIRECT, True),   # Portal hypertension (606 pts)
        # Varicose veins (venous cause of edema)
        ('I83.813', DIRECT, True),  # Varicose veins bilateral lower extremities with pain
        ('I83.893', DIRECT, True),  # Varicose veins bilateral lower extremities with complications
        ('I83.812', DIRECT, True),  # Varicose veins left lower extremity with pain
        ('I83.811', DIRECT, True),  # Varicose veins right lower extremity with pain
        # Edema symptom codes
        ('R60.0',  PROXY,  False),  # Localized edema (5,150 pts)
        ('R60.9',  PROXY,  False),  # Edema, unspecified (1,359 pts)
        ('R60.1',  PROXY,  False),  # Generalized edema (anasarca)
        # Drug-induced edema
        ('T46.1X5A', SUPP, False),  # Adverse effect of calcium channel blockers (amlodipine)
        ('T46.1X5D', SUPP, False),  # Adverse effect of CCB, subsequent encounter
    ],

    # ── fatigue ────────────────────────────────────────────────────────────
    'fatigue': [
        ('R53.1',  PROXY,  False),  # Weakness (4,143 pts)
        ('R53.0',  PROXY,  False),  # Neoplastic (malignant) related fatigue (57 pts)
        ('G93.31', PROXY,  False),  # Postviral fatigue syndrome (119 pts)
        ('G93.32', DIRECT, True),   # Myalgic encephalomyelitis/chronic fatigue syndrome (107 pts)
        ('G93.39', PROXY,  False),  # Other post-infection and related fatigue syndromes
        ('R68.89', PROXY,  False),  # Other general symptoms and signs (7,172 pts)
    ],

    # ── malaise ────────────────────────────────────────────────────────────
    'malaise': [
        ('R53.83', PROXY,  False),  # Other fatigue (15,401 pts)
        ('R53.82', PROXY,  False),  # Chronic fatigue, unspecified (4,070 pts)
        ('R68.89', PROXY,  False),  # Other general symptoms and signs (7,172 pts)
        ('R68.83', PROXY,  False),  # Chills (without fever) — constitutional symptom
        ('R53.0',  PROXY,  False),  # Neoplastic fatigue (57 pts)
        ('G93.31', PROXY,  False),  # Postviral fatigue syndrome
        ('G93.32', PROXY,  False),  # ME/CFS
        ('G93.39', PROXY,  False),  # Other post-infection fatigue syndromes
    ],

    # ── other_serosal_effusion ─────────────────────────────────────────────
    'other_serosal_effusion': [
        ('R18.0',  DIRECT, True),   # Malignant ascites (248 pts)
        ('K70.31', DIRECT, True),   # Alcoholic cirrhosis with ascites (1,919 pts)
        ('K76.6',  PROXY,  False),  # Portal hypertension (causes ascites) (606 pts)
        ('K66.1',  DIRECT, True),   # Hemoperitoneum (113 pts)
        ('K65.2',  PROXY,  False),  # Spontaneous bacterial peritonitis (208 pts)
        ('K65.9',  PROXY,  False),  # Peritonitis, unspecified (136 pts)
        ('C78.6',  PROXY,  False),  # Secondary malignant neoplasm of peritoneum (122 pts)
        ('K65.4',  PROXY,  False),  # Sclerosing mesenteritis (72 pts)
        ('K76.1',  PROXY,  False),  # Chronic passive congestion of liver (36 pts)
        ('K65.0',  PROXY,  False),  # Generalized peritonitis
        ('K65.8',  PROXY,  False),  # Other peritonitis
    ],

    # ── subjective_weakness ────────────────────────────────────────────────
    'subjective_weakness': [
        ('M62.81', DIRECT, True),   # Muscle weakness (generalized) (897 pts)
        ('R53.83', PROXY,  False),  # Other fatigue (15,401 pts)
        ('R53.82', PROXY,  False),  # Chronic fatigue, unspecified (4,070 pts)
        ('R53.81', PROXY,  False),  # Other malaise (1,687 pts)
        ('R53.0',  PROXY,  False),  # Neoplastic fatigue (57 pts)
        ('R54',    PROXY,  False),  # Age-related physical debility (254 pts)
        ('G70.00', PROXY,  False),  # Myasthenia gravis without exacerbation (222 pts)
        ('G70.01', PROXY,  False),  # Myasthenia gravis with exacerbation (77 pts)
        ('G70.9',  PROXY,  False),  # Myoneural disorder, unspecified (48 pts)
        ('G72.9',  PROXY,  False),  # Myopathy, unspecified (152 pts)
        ('G72.81', PROXY,  False),  # Critical illness myopathy (73 pts)
        ('M62.9',  PROXY,  False),  # Disorder of muscle, unspecified (41 pts)
    ],
}

# ── Load, apply, save ───────────────────────────────────────────────────────
data = json.load(open('v5/config/shared/atoms/GENERAL_MEDICINE.json', encoding='utf-8'))
atom_lookup = {a['atom_id']: a for a in data['atoms']}

total_added = 0
total_filled = 0

for aid, entries_spec in ADDITIONS.items():
    atom = atom_lookup.get(aid)
    if not atom:
        print('WARNING: atom not found: ' + aid)
        continue
    entries = [make_entry(code, role, standalone) for (code, role, standalone) in entries_spec]
    n = add_codes(atom, entries)
    total_added += n
    print('  ' + aid.ljust(30) + '+' + str(n).rjust(3) + ' new codes')

for atom in data['atoms']:
    f = backfill_display_names(atom)
    total_filled += f

print()
print('Total new ICD entries added:    ' + str(total_added))
print('display_names backfilled:       ' + str(total_filled))

with open('v5/config/shared/atoms/GENERAL_MEDICINE.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
print('Saved GENERAL_MEDICINE.json')

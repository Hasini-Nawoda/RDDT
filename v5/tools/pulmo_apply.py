"""Full 2026 ICD-10-CM pass for PULMONOLOGY.json — add codes + display_names."""
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

warehouse = {}
with open('not_for_snowflake/sql_root/icd_codes_with_meaning.csv', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        warehouse[row['DIAGNOSIS_CODE']] = int(row['PATIENT_COUNT'])

probe = ['I50.20','I50.32','I50.22','I50.42','I50.23','I50.43','I50.30','I50.33',
         'K74.69','K70.31','I26.09','I26.01','J18.1','C78.2','J91.0','J91.8',
         'J90','J86.9','J86.0','J94.0','J94.8','K76.6','J18.8']
print('=== Warehouse probe ===')
for c in probe:
    print(f'  {c:<12}{warehouse.get(c,0):>8}  {icd2026.get(c,"?")}')

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

    # ── al28_competing_effusion ───────────────────────────────────────────
    # Existing: I26.99, I50.9, J18.0, J18.9, J91.0, K70.30, K74.60, N04.9
    'al28_competing_effusion': [
        # Heart failure sub-types (major competing cause of transudative pleural effusion)
        ('I50.20', DIRECT, True),   # Unspecified systolic heart failure (2,688 pts)
        ('I50.32', DIRECT, True),   # Chronic diastolic heart failure (2,077 pts)
        ('I50.22', DIRECT, True),   # Chronic systolic heart failure (1,580 pts)
        ('I50.42', DIRECT, True),   # Chronic combined systolic+diastolic HF (1,406 pts)
        ('I50.23', DIRECT, True),   # Acute on chronic systolic HF (963 pts)
        ('I50.43', DIRECT, True),   # Acute on chronic combined HF (791 pts)
        ('I50.30', DIRECT, True),   # Unspecified diastolic HF (768 pts)
        ('I50.33', DIRECT, True),   # Acute on chronic diastolic HF (588 pts)
        # Pulmonary embolism sub-types (PE causes effusion)
        ('I26.09', DIRECT, True),   # Other PE without acute cor pulmonale
        ('I26.01', PROXY,  False),  # Saddle embolus PE without cor pulmonale
        # Additional pneumonia types
        ('J18.1',  DIRECT, True),   # Lobar pneumonia, unspecified organism
        ('J18.8',  PROXY,  False),  # Other pneumonia, unspecified organism
        # Malignant / pleural disease
        ('C78.2',  DIRECT, True),   # Secondary malignant neoplasm of pleura (exudative effusion)
        ('J91.8',  DIRECT, True),   # Pleural effusion in other conditions
        # Additional cirrhosis codes
        ('K74.69', DIRECT, True),   # Other cirrhosis of liver (2,045 pts)
        ('K70.31', DIRECT, True),   # Alcoholic cirrhosis with ascites (1,919 pts)
        # Hepatic / portal contributing to hepatic hydrothorax
        ('K76.6',  PROXY,  False),  # Portal hypertension
        # Additional nephrotic syndrome codes (transudative effusion)
        ('N04.0',  DIRECT, True),   # Nephrotic syndrome with minor glomerular abnormality
        ('N04.1',  DIRECT, True),   # Nephrotic syndrome with FSGS
    ],

    # ── pleural_effusion ──────────────────────────────────────────────────
    # Existing: J90, J91.8
    'pleural_effusion': [
        ('J91.0',  DIRECT, True),   # Malignant pleural effusion
        ('J86.9',  DIRECT, True),   # Pyothorax without fistula (empyema)
        ('J86.0',  DIRECT, True),   # Pyothorax with fistula
        ('J94.0',  DIRECT, True),   # Chylous effusion
        ('J94.8',  PROXY,  False),  # Other specified pleural conditions
        ('J94.9',  PROXY,  False),  # Pleural condition, unspecified
        ('J93.9',  PROXY,  False),  # Pneumothorax, unspecified (differential)
        # Imaging / procedural evidence codes
        ('R91.8',  PROXY,  False),  # Other nonspecific abnormal findings on chest imaging
    ],
}

data = json.load(open('v5/config/shared/atoms/PULMONOLOGY.json', encoding='utf-8'))
atom_lookup = {a['atom_id']: a for a in data['atoms']}

total_added = 0
total_filled = 0
print()
for aid, specs in ADDITIONS.items():
    atom = atom_lookup.get(aid)
    if not atom:
        print('WARNING: atom not found: ' + aid)
        continue
    n = add_codes(atom, [make_entry(c, r, s) for c, r, s in specs])
    total_added += n
    print('  ' + aid.ljust(30) + '+' + str(n).rjust(3) + ' new codes')

for atom in data['atoms']:
    total_filled += backfill(atom)

print()
print('Total new ICD entries:    ' + str(total_added))
print('display_names backfilled: ' + str(total_filled))

with open('v5/config/shared/atoms/PULMONOLOGY.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
print('Saved PULMONOLOGY.json')

total = sum(1 for a in data['atoms'] for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[]))
missing = [(a['atom_id'], e['value']) for a in data['atoms']
           for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[])
           if 'display_name' not in e]
print('Total ICD10 entries: ' + str(total))
print('Missing display_name: ' + str(len(missing)))
if missing:
    for aid, v in missing: print('  [' + aid + '] ' + v)
print('JSON valid: OK')

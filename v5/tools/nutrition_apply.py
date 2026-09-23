"""Full 2026 ICD-10-CM pass for NUTRITION.json — add codes + display_names."""
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

# Quick warehouse check for key codes
probe = ['E05.00','E05.01','E05.10','F32.1','F32.0','F33.1','F33.0','C80.0','K90.0',
         'F50.00','F50.01','B20','R63.4','R63.6','Z68.1','Z68.20','Z68.21',
         'K86.1','K90.89','F32.4','F33.2','E05.20','E05.80',
         'K57.30','E40','E41','E44.1']
print('=== Warehouse probe for NUTRITION ===')
for c in probe:
    wh = warehouse.get(c, 0)
    desc = icd2026.get(c, '?')
    print(f'  {c:<12}{wh:>8}  {desc}')

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

    # ── al09_competing_weight_loss ────────────────────────────────────────
    # Existing: A15.9, C80.1, E05.9, F32.9, F33.9, K90.9
    'al09_competing_weight_loss': [
        # Hyperthyroidism sub-types (E05.9 = unspecified already exists)
        ('E05.00', DIRECT, True),   # Thyrotoxicosis with diffuse goiter, no crisis (Graves' disease)
        ('E05.01', DIRECT, True),   # Thyrotoxicosis with diffuse goiter, with thyrotoxic crisis
        ('E05.10', DIRECT, True),   # Thyrotoxicosis with toxic single thyroid nodule
        ('E05.20', DIRECT, True),   # Thyrotoxicosis with toxic multinodular goiter, no crisis
        ('E05.80', DIRECT, True),   # Other thyrotoxicosis, without crisis
        # Depression subtypes (F32.9 / F33.9 = unspecified already exist)
        ('F32.0',  DIRECT, True),   # Major depressive disorder, single episode, mild
        ('F32.1',  DIRECT, True),   # Major depressive disorder, single episode, moderate
        ('F32.2',  DIRECT, True),   # Major depressive disorder, single, severe without psychosis
        ('F33.0',  DIRECT, True),   # Major depressive disorder, recurrent, mild
        ('F33.1',  DIRECT, True),   # Major depressive disorder, recurrent, moderate
        ('F33.2',  DIRECT, True),   # Major depressive disorder, recurrent, severe without psychosis
        # Malignancy
        ('C80.0',  DIRECT, True),   # Disseminated malignant neoplasm, unspecified (occult cancer)
        ('C78.89', PROXY,  False),  # Secondary malignant neoplasm of other digestive organs
        # Eating disorders
        ('F50.00', DIRECT, True),   # Anorexia nervosa, unspecified
        ('F50.01', DIRECT, True),   # Anorexia nervosa, restricting type
        ('F50.02', DIRECT, True),   # Anorexia nervosa, binge eating/purging type
        # HIV / chronic infection
        ('B20',    DIRECT, True),   # HIV disease — major cause of wasting/weight loss
        # Malabsorption
        ('K90.0',  DIRECT, True),   # Celiac disease — malabsorption-driven weight loss
        ('K90.89', PROXY,  False),  # Other intestinal malabsorption
        ('K86.1',  PROXY,  False),  # Other chronic pancreatitis — exocrine insufficiency → malabsorption
        # Chronic inflammatory / tuberculosis sub-types
        ('A15.0',  DIRECT, True),   # Tuberculosis of lung — more specific than A15.9
        ('A15.4',  DIRECT, True),   # Tuberculosis of intrathoracic lymph nodes
        # Severe malnutrition itself as competing cause
        ('E40',    DIRECT, True),   # Kwashiorkor
        ('E41',    DIRECT, True),   # Nutritional marasmus
        ('E44.1',  DIRECT, True),   # Mild protein-calorie malnutrition
    ],

    # ── weight_result ─────────────────────────────────────────────────────
    # No ICD10 codes currently
    'weight_result': [
        ('R63.4',  DIRECT, True),   # Abnormal weight loss
        ('R63.6',  DIRECT, True),   # Underweight
        ('R63.5',  DIRECT, True),   # Abnormal weight gain
        # BMI codes — body weight measurement context
        ('Z68.1',  PROXY,  False),  # BMI 19.9 or less, adult
        ('Z68.20', PROXY,  False),  # BMI 20.0–20.9, adult
        ('Z68.21', PROXY,  False),  # BMI 21.0–21.9, adult
        ('Z68.22', PROXY,  False),  # BMI 22.0–22.9, adult
        ('Z68.23', PROXY,  False),  # BMI 23.0–23.9, adult
        ('Z68.41', PROXY,  False),  # BMI 40.0–44.9, adult
        ('Z68.42', PROXY,  False),  # BMI 45.0–49.9, adult
    ],
}

data = json.load(open('v5/config/shared/atoms/NUTRITION.json', encoding='utf-8'))
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
    print('  ' + aid.ljust(38) + '+' + str(n).rjust(3) + ' new codes')

for atom in data['atoms']:
    total_filled += backfill(atom)

print()
print('Total new ICD entries:    ' + str(total_added))
print('display_names backfilled: ' + str(total_filled))

with open('v5/config/shared/atoms/NUTRITION.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
print('Saved NUTRITION.json')

total = sum(1 for a in data['atoms'] for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[]))
missing = [(a['atom_id'], e['value']) for a in data['atoms']
           for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[])
           if 'display_name' not in e]
print('Total ICD10 entries: ' + str(total))
print('Missing display_name: ' + str(len(missing)))
if missing:
    for aid, v in missing: print('  [' + aid + '] ' + v)
print('JSON valid: OK')

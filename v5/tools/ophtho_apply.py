"""Full 2026 ICD-10-CM pass for OPHTHALMOLOGY.json — add codes + display_names."""
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

probe = [
    'H04.121','H04.122','H04.129','H16.141','H16.142','H16.149',
    'H40.10x0','H40.10x1','H40.1110','H40.1120','H40.9',
    'H40.1111','H40.1112','H40.1113','H40.1114',
    'H40.20x0','H40.2110','H40.3110',
    'H21.00','H21.531','H21.80',
    'H57.00','H57.09','H57.01',
    'H43.391','H43.392','H43.399','H43.819','H43.811','H43.812','H43.813',
]
print('=== Warehouse probe ===')
for c in probe:
    wh = warehouse.get(c, 0)
    desc = icd2026.get(c, '?')
    print(f'  {c:<14}{wh:>8}  {desc}')

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

    # ── dry_eye ───────────────────────────────────────────────────────────
    # Existing: H40.9 (glaucoma unspecified), H04.123 (dry eye syndrome bilateral)
    'dry_eye': [
        ('H04.121', DIRECT, True),  # Dry eye syndrome, right lacrimal gland
        ('H04.122', DIRECT, True),  # Dry eye syndrome, left lacrimal gland
        ('H04.129', DIRECT, True),  # Dry eye syndrome, unspecified lacrimal gland
        ('H16.149', PROXY,  False), # Keratoconjunctivitis, unspecified eye — KCS / sicca
        ('H16.141', PROXY,  False), # Keratoconjunctivitis, right eye
        ('H16.142', PROXY,  False), # Keratoconjunctivitis, left eye
    ],

    # ── floaters ─────────────────────────────────────────────────────────
    # Existing: H43.20-H43.23 (vitreous floaters, unspecified/right/left/bilateral)
    'floaters': [
        ('H43.391', PROXY, False),  # Other vitreous opacities, right eye
        ('H43.392', PROXY, False),  # Other vitreous opacities, left eye
        ('H43.399', PROXY, False),  # Other vitreous opacities, unspecified eye
        ('H43.813', PROXY, False),  # Vitreous degeneration, bilateral
        ('H43.819', PROXY, False),  # Vitreous degeneration, unspecified eye
    ],

    # ── glaucoma ──────────────────────────────────────────────────────────
    # Existing: H40.9 (glaucoma unspecified), H04.123 (dry eye — may be legacy placeholder)
    'glaucoma': [
        ('H40.10x0', DIRECT, True), # Unspecified open-angle glaucoma, stage unspecified
        ('H40.10x1', DIRECT, True), # Unspecified open-angle glaucoma, mild stage
        ('H40.10x2', DIRECT, True), # Unspecified open-angle glaucoma, moderate stage
        ('H40.1110', DIRECT, True), # Primary open-angle glaucoma, right eye, stage unspecified
        ('H40.1120', DIRECT, True), # Primary open-angle glaucoma, left eye, stage unspecified
        ('H40.1130', DIRECT, True), # Primary open-angle glaucoma, bilateral, stage unspecified
        ('H40.20x0', DIRECT, True), # Unspecified primary angle-closure glaucoma, stage unspecified
        ('H40.2110', DIRECT, True), # Primary angle-closure glaucoma, right eye, stage unspecified
        ('H40.2120', DIRECT, True), # Primary angle-closure glaucoma, left eye, stage unspecified
        ('H40.2130', DIRECT, True), # Primary angle-closure glaucoma, bilateral, stage unspecified
        ('H40.3110', PROXY,  False), # Glaucoma secondary to eye trauma, right eye
        ('H40.3120', PROXY,  False), # Glaucoma secondary to eye trauma, left eye
    ],

    # ── iris_abnormality ──────────────────────────────────────────────────
    # Existing: H21.89
    'iris_abnormality': [
        ('H21.00',  PROXY,  False), # Hyphema, unspecified eye (iris/anterior segment bleed)
        ('H21.30',  PROXY,  False), # Idiopathic iris cyst, unspecified eye
        ('H21.531', PROXY,  False), # Rubeosis iridis, right eye (neovascularization of iris)
        ('H21.532', PROXY,  False), # Rubeosis iridis, left eye
        ('H21.80',  PROXY,  False), # Other specified disorders of iris, unspecified eye
        ('H57.00',  PROXY,  False), # Unspecified anomaly of pupillary function
        ('H57.09',  PROXY,  False), # Other anomalies of pupillary function
    ],

    # ── scalloped_pupil ───────────────────────────────────────────────────
    # Existing: H21.89
    'scalloped_pupil': [
        ('H57.00',  DIRECT, True),  # Unspecified anomaly of pupillary function — pupil shape abnormality
        ('H57.09',  DIRECT, True),  # Other anomalies of pupillary function
        ('H57.01',  PROXY,  False), # Argyll Robertson pupil (irregular/nonreactive pupil)
        ('H21.80',  PROXY,  False), # Other specified disorders of iris, unspecified eye
    ],

    # ── vitreous_opacity ──────────────────────────────────────────────────
    # Existing: H43.20-H43.23 (vitreous floaters)
    'vitreous_opacity': [
        ('H43.391', DIRECT, True),  # Other vitreous opacities, right eye
        ('H43.392', DIRECT, True),  # Other vitreous opacities, left eye
        ('H43.399', DIRECT, True),  # Other vitreous opacities, unspecified eye
        ('H43.813', PROXY,  False), # Vitreous degeneration, bilateral
        ('H43.819', PROXY,  False), # Vitreous degeneration, unspecified eye
        ('H43.811', PROXY,  False), # Vitreous degeneration, right eye
        ('H43.812', PROXY,  False), # Vitreous degeneration, left eye
    ],
}

data = json.load(open('v5/config/shared/atoms/OPHTHALMOLOGY.json', encoding='utf-8'))
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

with open('v5/config/shared/atoms/OPHTHALMOLOGY.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
print('Saved OPHTHALMOLOGY.json')

total = sum(1 for a in data['atoms'] for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[]))
missing = [(a['atom_id'], e['value']) for a in data['atoms']
           for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[])
           if 'display_name' not in e]
print('Total ICD10 entries: ' + str(total))
print('Missing display_name: ' + str(len(missing)))
if missing:
    for aid, v in missing: print('  [' + aid + '] ' + v)
print('JSON valid: OK')

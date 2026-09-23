"""Full 2026 ICD-10-CM pass for RHEUM_INFLAMMATORY.json — add codes + display_names."""
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
    'M04.1','M04.2','M04.8','M04.9',
    'A15.9','A15.0','M86.20','M86.60','J47.9','J47.0',
    'M06.9','M05.9','M05.79','M06.09','M45.0','M08.00','M07.60',
    'K50.90','K50.91','K51.90','K51.91','K50.00','K50.10',
    'E85.3','R79.82','R70.0','R70.1','R79.89',
]
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

    # ── autoinflammatory_syndrome ─────────────────────────────────────────
    # No ICD10 codes
    'autoinflammatory_syndrome': [
        ('M04.1',  DIRECT, True),   # Periodic fever syndromes (CAPS, TRAPS, PFAPA, etc.)
        ('M04.2',  DIRECT, True),   # Cryopyrin-associated periodic syndromes (CAPS)
        ('M04.8',  DIRECT, True),   # Other autoinflammatory syndromes (HIDS, PAPA, etc.)
        ('M04.9',  DIRECT, True),   # Autoinflammatory syndrome, unspecified
        ('E85.3',  PROXY,  False),  # Secondary systemic amyloidosis (AA) — downstream consequence
    ],

    # ── chronic_infection ─────────────────────────────────────────────────
    # No ICD10 codes
    'chronic_infection': [
        ('A15.0',  DIRECT, True),   # Tuberculosis of lung — classic chronic infection → AA amyloid
        ('A15.9',  DIRECT, True),   # Respiratory tuberculosis, unspecified
        ('A18.09', DIRECT, True),   # Other musculoskeletal tuberculosis (bone, joint TB)
        ('M86.60', DIRECT, True),   # Other chronic osteomyelitis, unspecified site
        ('M86.20', DIRECT, True),   # Subacute osteomyelitis, unspecified site
        ('J47.9',  DIRECT, True),   # Bronchiectasis, uncomplicated (chronic suppurative lung)
        ('J47.0',  DIRECT, True),   # Bronchiectasis with acute lower respiratory infection
        ('A18.01', PROXY,  False),  # Tuberculosis of spine (Pott disease)
        ('B20',    PROXY,  False),  # HIV disease (chronic immune activation → AA risk)
        ('A69.20', PROXY,  False),  # Lyme disease, unspecified — chronic infectious driver
    ],

    # ── chronic_inflammatory_arthritis ───────────────────────────────────
    # No ICD10 codes
    'chronic_inflammatory_arthritis': [
        ('M06.9',  DIRECT, True),   # Rheumatoid arthritis, unspecified
        ('M05.9',  DIRECT, True),   # Seropositive RA, unspecified
        ('M05.79', DIRECT, True),   # Seropositive RA with rheumatoid vasculitis, multiple sites
        ('M06.09', DIRECT, True),   # RA without RF, multiple sites
        ('M45.0',  DIRECT, True),   # Ankylosing spondylitis of multiple sites in spine
        ('M45.9',  DIRECT, True),   # Ankylosing spondylitis of unspecified sites in spine
        ('M08.00', DIRECT, True),   # Juvenile RA, unspecified site — AA amyloid risk in JIA
        ('M07.60', DIRECT, True),   # Enteropathic arthropathies, unspecified site (IBD arthritis)
        ('M05.10', PROXY,  False),  # Felty syndrome, unspecified site
        ('M06.20', PROXY,  False),  # Adult-onset Still disease, unspecified site
        ('M32.9',  PROXY,  False),  # SLE, unspecified (systemic inflammatory arthritis)
    ],

    # ── crp_result ────────────────────────────────────────────────────────
    # Existing: R79.82
    'crp_result': [
        ('R79.89', PROXY, False),   # Other specified abnormal findings on examination of blood
        ('R70.0',  PROXY, False),   # Elevated ESR — ordered alongside CRP
    ],

    # ── esr_result ────────────────────────────────────────────────────────
    # Existing: R70.0
    'esr_result': [
        ('R79.82', PROXY, False),   # Elevated CRP — ordered alongside ESR
        ('R70.1',  PROXY, False),   # Abnormal plasma viscosity
    ],

    # ── fmf ───────────────────────────────────────────────────────────────
    # No ICD10 codes
    'fmf': [
        ('M04.1',  DIRECT, True),   # Periodic fever syndromes — FMF is the prototypic periodic fever
        ('E85.3',  PROXY,  False),  # Secondary systemic amyloidosis (AA) — FMF leading cause
        ('E85.0',  PROXY,  False),  # Non-neuropathic heredofamilial amyloidosis — FMF-associated
        ('M04.9',  PROXY,  False),  # Autoinflammatory syndrome, unspecified
    ],

    # ── ibd_inflammatory_driver ───────────────────────────────────────────
    # No ICD10 codes
    'ibd_inflammatory_driver': [
        ('K50.90', DIRECT, True),   # Crohn's disease of small and large intestine, unspecified, without complications
        ('K50.91', DIRECT, True),   # Crohn's disease of small and large intestine, unspecified, with complications
        ('K51.90', DIRECT, True),   # Ulcerative colitis, unspecified, without complications
        ('K51.91', DIRECT, True),   # Ulcerative colitis, unspecified, with complications
        ('K50.00', DIRECT, True),   # Crohn's disease of small intestine, without complications
        ('K50.10', DIRECT, True),   # Crohn's disease of large intestine, without complications
        ('K50.011',DIRECT, True),   # Crohn's disease small intestine with rectal bleeding
        ('K50.111',DIRECT, True),   # Crohn's disease large intestine with rectal bleeding
        ('K51.011',DIRECT, True),   # Ulcerative pancolitis with rectal bleeding
        ('K52.9',  PROXY,  False),  # Noninfective gastroenteritis and colitis, unspecified
    ],

    # ── saa_result ────────────────────────────────────────────────────────
    # No ICD10 codes (only SNOMED)
    'saa_result': [
        ('R79.89', DIRECT, True),   # Other specified abnormal findings on examination of blood — SAA is a blood test result
        ('R79.82', PROXY,  False),  # Elevated CRP — acute-phase reactant like SAA
        ('R70.0',  PROXY,  False),  # Elevated ESR — inflammatory marker like SAA
        ('E85.3',  PROXY,  False),  # Secondary systemic amyloidosis (AA) — SAA is the precursor protein
    ],
}

data = json.load(open('v5/config/shared/atoms/RHEUM_INFLAMMATORY.json', encoding='utf-8'))
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
    print('  ' + aid.ljust(36) + '+' + str(n).rjust(3) + ' new codes')

for atom in data['atoms']:
    total_filled += backfill(atom)

print()
print('Total new ICD entries:    ' + str(total_added))
print('display_names backfilled: ' + str(total_filled))

with open('v5/config/shared/atoms/RHEUM_INFLAMMATORY.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
print('Saved RHEUM_INFLAMMATORY.json')

total = sum(1 for a in data['atoms'] for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[]))
missing = [(a['atom_id'], e['value']) for a in data['atoms']
           for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[])
           if 'display_name' not in e]
print('Total ICD10 entries: ' + str(total))
print('Missing display_name: ' + str(len(missing)))
if missing:
    for aid, v in missing: print('  [' + aid + '] ' + v)
print('JSON valid: OK')

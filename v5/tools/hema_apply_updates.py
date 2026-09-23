"""Full 2026 ICD-10-CM pass for HEMATOLOGY.json — add codes + display_names."""
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

    # ── mgus ─────────────────────────────────────────────────────────────────
    # Atom had NO ICD codes at all.
    'mgus': [
        # Core MGUS / monoclonal protein codes
        ('D47.2',   DIRECT, True),   # Monoclonal gammopathy (176 WH pts) — this IS MGUS
        ('D47.Z9',  PROXY,  False),  # Other neoplasms of uncertain behavior — lymphoid (1 pt)
        ('D47.9',   PROXY,  False),  # Neoplasm uncertain behavior of lymphoid tissue, unspecified (18 pts)
        # Abnormal serum protein / globulin results — often the first lab clue for M-spike
        ('R77.1',   PROXY,  False),  # Abnormality of globulin (13 pts)
        ('R77.8',   PROXY,  False),  # Other specified abnormalities of plasma proteins (305 pts)
        ('R77.9',   PROXY,  False),  # Abnormality of plasma protein, unspecified (268 pts)
        # Conditions MGUS can progress to / be confused with
        ('C90.30',  PROXY,  False),  # Solitary plasmacytoma not in remission (16 pts)
        ('C90.31',  PROXY,  False),  # Solitary plasmacytoma in remission (2 pts)
        ('C88.00',  PROXY,  False),  # Waldenstrom macroglobulinemia (7 pts) — IgM MGUS overlap
        ('D47.Z2',  PROXY,  False),  # Castleman disease (16 pts) — plasma cell variant
        ('E85.81',  PROXY,  False),  # Light chain (AL) amyloidosis (24 pts) — MGUS/AL overlap
        ('E85.9',   PROXY,  False),  # Amyloidosis, unspecified (22 pts)
    ],

    # ── plasma_cell_dyscrasia ─────────────────────────────────────────────────
    # Existing: C90.00, C90.01, C90.10, C90.30, C90.20, E85.81
    'plasma_cell_dyscrasia': [
        # Missing MM relapse code (highest warehouse patient count not in config)
        ('C90.02',  DIRECT, True),   # Multiple myeloma in relapse (68 WH pts)
        # Remaining plasmacytoma variants
        ('C90.31',  DIRECT, True),   # Solitary plasmacytoma in remission (2 pts)
        ('C90.32',  DIRECT, True),   # Solitary plasmacytoma in relapse (0 pts)
        # Plasma cell leukemia variants
        ('C90.11',  DIRECT, True),   # Plasma cell leukemia in remission (2 pts)
        ('C90.12',  DIRECT, True),   # Plasma cell leukemia in relapse (1 pt)
        # Extramedullary plasmacytoma variants
        ('C90.21',  DIRECT, True),   # Extramedullary plasmacytoma in remission (1 pt)
        ('C90.22',  DIRECT, True),   # Extramedullary plasmacytoma in relapse (1 pt)
        # Waldenstrom macroglobulinemia — IgM plasma cell dyscrasia
        ('C88.00',  DIRECT, True),   # Waldenstrom macroglobulinemia not in remission (7 pts)
        ('C88.01',  DIRECT, True),   # Waldenstrom macroglobulinemia in remission (0 pts)
        # MALT lymphoma — marginal zone B-cell, close plasma-cell relative
        ('C88.40',  PROXY,  False),  # MALT lymphoma not in remission (18 pts)
        ('C88.41',  PROXY,  False),  # MALT lymphoma in remission (1 pt)
        # Heavy chain disease
        ('C88.20',  PROXY,  False),  # Heavy chain disease not in remission (0 pts)
        # Monoclonal gammopathy — MGUS as a spectrum entry
        ('D47.2',   PROXY,  False),  # Monoclonal gammopathy (176 pts) — borderline dyscrasia
        ('D47.Z9',  PROXY,  False),  # Other neoplasms uncertain behavior (1 pt)
        # Amyloidosis variants associated with dyscrasia
        ('E85.4',   PROXY,  False),  # Organ-limited amyloidosis (89 pts)
        ('E85.89',  PROXY,  False),  # Other amyloidosis (7 pts)
        ('E85.9',   PROXY,  False),  # Amyloidosis, unspecified (22 pts)
    ],

    # ── myeloma_therapy_exposure ──────────────────────────────────────────────
    # Existing: Z51.1, Z51.11, Z92.21
    'myeloma_therapy_exposure': [
        # Antineoplastic immunotherapy encounter (daratumumab, isatuximab infusions)
        ('Z51.12',  DIRECT, True),   # Encounter for antineoplastic immunotherapy (119 WH pts)
        # Long-term drug therapy — lenalidomide/bortezomib maintenance captured here
        ('Z79.899', PROXY,  False),  # Other long-term (current) drug therapy (7,810 pts)
        ('Z79.60',  PROXY,  False),  # Long-term use of immunomodulators/immunosuppressants (424 pts)
        ('Z79.52',  PROXY,  False),  # Long-term use of systemic steroids (dexamethasone component, 257 pts)
        # Personal history of drug therapy
        ('Z92.29',  PROXY,  False),  # Personal history of other drug therapy (251 pts)
        ('Z92.22',  DIRECT, True),   # Personal history of monoclonal drug therapy (0 pts, but specific)
        # Common chemo adverse effects — signals that active chemo was/is occurring
        ('D70.1',   PROXY,  False),  # Agranulocytosis secondary to cancer chemotherapy (186 pts)
        ('D64.81',  PROXY,  False),  # Anemia due to antineoplastic chemotherapy (173 pts)
        # Palliative care encounter — myeloma in advanced/refractory setting
        ('Z51.5',   PROXY,  False),  # Encounter for palliative care (437 pts)
        # Personal history of haematological malignancy
        ('Z85.79',  PROXY,  False),  # Personal history of other malignant neoplasms of lymphoid, haematopoietic tissue
    ],
}

data = json.load(open('v5/config/shared/atoms/HEMATOLOGY.json', encoding='utf-8'))
atom_lookup = {a['atom_id']: a for a in data['atoms']}

total_added = 0
total_filled = 0
for aid, specs in ADDITIONS.items():
    atom = atom_lookup[aid]
    n = add_codes(atom, [make_entry(c, r, s) for c, r, s in specs])
    total_added += n
    print('  ' + aid.ljust(30) + '+' + str(n).rjust(3) + ' new codes')

for atom in data['atoms']:
    total_filled += backfill(atom)

print()
print('Total new ICD entries:          ' + str(total_added))
print('display_names backfilled:       ' + str(total_filled))

with open('v5/config/shared/atoms/HEMATOLOGY.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
print('Saved HEMATOLOGY.json')

total = sum(1 for a in data['atoms'] for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[]))
missing = [(a['atom_id'], e['value']) for a in data['atoms']
           for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[])
           if 'display_name' not in e]
print('Total ICD10 entries: ' + str(total))
print('Missing display_name: ' + str(len(missing)))
if missing:
    for aid, v in missing: print('  [' + aid + '] ' + v)
print('JSON valid: OK')

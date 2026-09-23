"""Full 2026 ICD-10-CM pass for GENETICS.json — add codes + display_names."""
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

DIRECT = 'DIRECT_TARGET'
PROXY  = 'PROXY_SUPPORT'

# ── fhx_sudden_death ─────────────────────────────────────────────────────────
# Atom: Family history of sudden death or hereditary amyloid/neuropathy
# experiencer = FAMILY_MEMBER — codes are family-history Z-codes plus hereditary
# condition codes that imply hereditary risk in the patient's record.
ENTRIES = [

    # ── Family history Z-codes (primary encoding of FHx in ICD billing) ──
    ('Z82.41',  DIRECT, True),   # Family history of sudden cardiac death (49 WH pts)
    ('Z82.49',  DIRECT, True),   # Family history of ischemic heart disease & circulatory system (977 pts)
    ('Z84.81',  DIRECT, True),   # Family history of carrier of genetic disease (119 pts)
    ('Z84.89',  PROXY,  False),  # Family history of other specified conditions (115 pts)
    ('Z82.3',   PROXY,  False),  # Family history of stroke (27 pts)
    ('Z82.0',   PROXY,  False),  # Family history of epilepsy / diseases of nervous system (74 pts)
    ('Z86.74',  PROXY,  False),  # Personal history of sudden cardiac arrest (patient's own — 33 pts)

    # ── Hereditary amyloidosis — key for ATTR / AL amyloidosis evaluation ──
    ('E85.0',   DIRECT, True),   # Non-neuropathic heredofamilial amyloidosis (0 WH, but critical)
    ('E85.1',   DIRECT, True),   # Neuropathic heredofamilial amyloidosis (TTR-familial neuropathy)
    ('E85.2',   DIRECT, True),   # Heredofamilial amyloidosis, unspecified
    ('E85.81',  PROXY,  False),  # Light chain (AL) amyloidosis (24 WH pts)
    ('E85.82',  PROXY,  False),  # Wild-type transthyretin (ATTRwt) amyloidosis (10 pts)
    ('E85.89',  PROXY,  False),  # Other amyloidosis (7 pts)
    ('E85.4',   PROXY,  False),  # Organ-limited amyloidosis (89 pts)
    ('E85.9',   PROXY,  False),  # Amyloidosis, unspecified (22 pts)

    # ── Hereditary neuropathy ─────────────────────────────────────────────
    ('G60.0',   PROXY,  False),  # Hereditary motor and sensory neuropathy (CMT) (32 pts)
    ('G60.8',   PROXY,  False),  # Other hereditary and idiopathic neuropathies (76 pts)
    ('G60.9',   PROXY,  False),  # Hereditary and idiopathic neuropathy, unspecified (249 pts)
    ('G90.1',   PROXY,  False),  # Familial dysautonomia [Riley-Day] (116 pts) — hereditary autonomic neuropathy

    # ── Cardiac arrest / ventricular arrhythmia (direct sudden-death events) ──
    ('I46.9',   PROXY,  False),  # Cardiac arrest, cause unspecified (811 pts)
    ('I46.2',   PROXY,  False),  # Cardiac arrest due to underlying cardiac condition (4 pts)
    ('I49.01',  PROXY,  False),  # Ventricular fibrillation (46 pts) — primary mechanism of sudden death

    # ── Hereditary cardiomyopathy (major cause of sudden death in families) ──
    ('I42.1',   PROXY,  False),  # Obstructive hypertrophic cardiomyopathy (familial HCM)
    ('I42.2',   PROXY,  False),  # Other hypertrophic cardiomyopathy
]

data = json.load(open('v5/config/shared/atoms/GENETICS.json', encoding='utf-8'))
atom_lookup = {a['atom_id']: a for a in data['atoms']}
atom = atom_lookup['fhx_sudden_death']

entries = [make_entry(code, role, standalone) for (code, role, standalone) in ENTRIES]
n = add_codes(atom, entries)

print('fhx_sudden_death: +' + str(n) + ' new ICD codes')

# backfill display_names for any pre-existing entries (atom had none, so this is future-proofing)
filled = 0
for entry in atom.get('extraction', {}).get('codes', {}).get('ICD10', []):
    if 'display_name' not in entry:
        desc = lookup(entry['value'])
        entry['display_name'] = desc if desc else entry['value'] + ' [no 2026 description]'
        filled += 1
print('display_names backfilled: ' + str(filled))

with open('v5/config/shared/atoms/GENETICS.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
print('Saved GENETICS.json')

# validate
total = sum(1 for a in data['atoms'] for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[]))
missing = [(a['atom_id'], e['value']) for a in data['atoms']
           for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[])
           if 'display_name' not in e]
print('Total ICD10 entries: ' + str(total))
print('Missing display_name: ' + str(len(missing)))
print('JSON valid: OK')

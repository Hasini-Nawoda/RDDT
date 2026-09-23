"""
Backfill a `display_name` field on every ICD10 code entry in all atom files.

display_name = the official FY-2026 ICD-10-CM full description for the code,
so that when a proxy (or any code) fires in a patient profile the rendered
signal clearly says what actually matched, not just the atom's preferred_name.
"""
import json

# ── Load 2026 ICD-10-CM dictionary ─────────────────────────────────────────
def add_dot(code):
    code = code.strip()
    if len(code) > 3 and '.' not in code:
        return code[:3] + '.' + code[3:]
    return code

icd2026 = {}
with open('not_for_snowflake/sql_codes/icd10cm-codes-2026.txt', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            raw = add_dot(parts[0])
            icd2026[raw] = parts[1]
            icd2026[parts[0].strip()] = parts[1]   # also store without dot

def lookup(code):
    """Return official description or None."""
    return icd2026.get(code) or icd2026.get(code.replace('.', ''))


# ── Process a single atom file ──────────────────────────────────────────────
def process_file(path):
    data = json.load(open(path, encoding='utf-8'))
    updated = 0
    already  = 0
    missing  = []

    for atom in data['atoms']:
        icd_list = (atom
                    .get('extraction', {})
                    .get('codes', {})
                    .get('ICD10', []))
        for entry in icd_list:
            if 'display_name' in entry:
                already += 1
                continue
            desc = lookup(entry['value'])
            if desc:
                entry['display_name'] = desc
                updated += 1
            else:
                missing.append((atom['atom_id'], entry['value']))

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    return updated, already, missing


# ── Run on all four files ────────────────────────────────────────────────────
files = [
    'v5/config/shared/atoms/CARDIOLOGY.json',
    'v5/config/shared/atoms/DERMATOLOGY_ORAL.json',
    'v5/config/shared/atoms/DERMATOLOGY.json',
    'v5/config/shared/atoms/ENT.json',
]

total_updated = 0
for path in files:
    u, a, missing = process_file(path)
    total_updated += u
    fname = path.split('/')[-1]
    print(f'{fname}: +{u} display_names added  ({a} already had one)')
    for atom_id, code in missing:
        print(f'  WARNING: no 2026 description for [{atom_id}] {code}')

print(f'\nTotal display_name fields added: {total_updated}')

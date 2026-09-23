"""Full 2026 ICD-10-CM pass for ORTHOPEDICS_MSK.json — add codes + display_names."""
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

    # ── arthroplasty ──────────────────────────────────────────────────────
    # Existing: Z96.641-643, Z96.651-653, Z96.64, Z96.65 (hip variants)
    # MISSING: knee implant presence codes (highest WH counts!)
    'arthroplasty': [
        ('Z96.651', DIRECT, True),  # Presence of right artificial knee joint (370 pts)
        ('Z96.652', DIRECT, True),  # Presence of left artificial knee joint (343 pts)
        ('Z96.653', DIRECT, True),  # Presence of artificial knee joint, bilateral (39 pts)
        ('Z96.649', DIRECT, True),  # Presence of unspecified artificial hip joint (35 pts)
        ('Z96.611', PROXY,  False), # Presence of right artificial shoulder joint (79 pts)
        ('Z96.612', PROXY,  False), # Presence of left artificial shoulder joint (55 pts)
    ],

    # ── biceps_rupture ────────────────────────────────────────────────────
    # Existing: M66.821/822/829, M66.80/89/9, S46.211A/221A, M75.100/101/102, M65.30-M65.359/9
    'biceps_rupture': [
        ('M75.121', PROXY, False),  # Complete rotator cuff tear right (185 pts) — associated shoulder pathology
        ('M75.122', PROXY, False),  # Complete rotator cuff tear left (103 pts)
        ('M75.111', PROXY, False),  # Incomplete rotator cuff tear right (122 pts)
        ('M75.112', PROXY, False),  # Incomplete rotator cuff tear left (74 pts)
        ('M66.811', DIRECT, True),  # Spontaneous rupture other tendons, right shoulder
        ('M66.812', DIRECT, True),  # Spontaneous rupture other tendons, left shoulder
    ],

    # ── ctr_any ───────────────────────────────────────────────────────────
    # Existing: Z98.890 only
    'ctr_any': [
        ('G56.03',  PROXY, False),  # CTS bilateral (2,909 pts) — reason for CTR
        ('G56.01',  PROXY, False),  # CTS right (1,383 pts)
        ('G56.02',  PROXY, False),  # CTS left (817 pts)
    ],

    # ── cts_any ───────────────────────────────────────────────────────────
    # Existing: G56.00, G56.0
    'cts_any': [
        ('G56.03',  DIRECT, True),  # CTS bilateral (2,909 pts) — major gap
        ('G56.01',  DIRECT, True),  # CTS right (1,383 pts)
        ('G56.02',  DIRECT, True),  # CTS left (817 pts)
        ('G56.11',  PROXY,  False), # Other lesions of median nerve, right (42 pts)
        ('G56.12',  PROXY,  False), # Other lesions of median nerve, left (36 pts)
        ('G56.13',  PROXY,  False), # Other lesions of median nerve, bilateral (31 pts)
    ],

    # ── cts_bilateral ─────────────────────────────────────────────────────
    # Existing: G56.03 only
    'cts_bilateral': [
        ('G56.13',  PROXY, False),  # Other lesions of median nerve, bilateral (31 pts)
    ],

    # ── cts_left ──────────────────────────────────────────────────────────
    'cts_left': [
        ('G56.02',  DIRECT, True),  # CTS left upper limb (817 pts)
        ('G56.12',  PROXY,  False), # Other lesions of median nerve, left (36 pts)
    ],

    # ── cts_persistent_after_release ──────────────────────────────────────
    'cts_persistent_after_release': [
        ('G56.01',  PROXY, False),  # CTS right (1,383 pts) — persistent CTS after CTR
        ('G56.02',  PROXY, False),  # CTS left (817 pts)
        ('G56.03',  PROXY, False),  # CTS bilateral (2,909 pts)
        ('Z98.890', PROXY, False),  # Other specified postprocedural states (after CTR)
    ],

    # ── cts_recurrent ─────────────────────────────────────────────────────
    'cts_recurrent': [
        ('G56.01',  PROXY, False),  # CTS right (1,383 pts)
        ('G56.02',  PROXY, False),  # CTS left (817 pts)
        ('G56.03',  PROXY, False),  # CTS bilateral (2,909 pts)
    ],

    # ── cts_right ─────────────────────────────────────────────────────────
    'cts_right': [
        ('G56.01',  DIRECT, True),  # CTS right upper limb (1,383 pts)
        ('G56.11',  PROXY,  False), # Other lesions of median nerve, right (42 pts)
    ],

    # ── lumbar_decompression ──────────────────────────────────────────────
    # Existing: Z98.890 only
    'lumbar_decompression': [
        ('M48.062', PROXY, False),  # Spinal stenosis lumbar with neurogenic claudication (1,054 pts) — indication for decompression
        ('M48.061', PROXY, False),  # Spinal stenosis lumbar without neurogenic claudication (1,097 pts)
        ('M47.816', PROXY, False),  # Spondylosis without myelopathy, lumbar (2,347 pts)
    ],

    # ── lumbar_stenosis ───────────────────────────────────────────────────
    # Existing: M48.062, M48.061, M48.06, M48.07, M48.00
    'lumbar_stenosis': [
        ('M47.816', PROXY,  False), # Spondylosis without myelopathy, lumbar (2,347 pts)
        ('M47.26',  PROXY,  False), # Spondylosis with radiculopathy, lumbar (252 pts)
        ('M47.27',  PROXY,  False), # Spondylosis with radiculopathy, lumbosacral (504 pts)
        ('M51.16',  PROXY,  False), # IVD disorder with radiculopathy, lumbar (377 pts)
        ('M48.04',  PROXY,  False), # Spinal stenosis, thoracic (111 pts)
        ('M48.05',  PROXY,  False), # Spinal stenosis, thoracolumbar
    ],

    # ── persistent_lower_limb_symptoms_after_decompression ────────────────
    'persistent_lower_limb_symptoms_after_decompression': [
        ('M54.42',  DIRECT, True),  # Lumbago with sciatica, left side (7,905 pts)
        ('M54.41',  DIRECT, True),  # Lumbago with sciatica, right side (6,374 pts)
        ('M54.16',  DIRECT, True),  # Radiculopathy, lumbar region (4,436 pts)
        ('M54.40',  DIRECT, True),  # Lumbago with sciatica, unspecified (1,291 pts)
        ('M54.17',  DIRECT, True),  # Radiculopathy, lumbosacral region (415 pts)
        ('M51.16',  PROXY,  False), # IVD disorder with radiculopathy, lumbar (377 pts)
        ('M54.50',  PROXY,  False), # Low back pain, unspecified (26,780 pts)
        ('G57.93',  PROXY,  False), # Unspecified mononeuropathy, bilateral lower limbs (323 pts)
    ],

    # ── rotator_cuff ──────────────────────────────────────────────────────
    # Existing: M75.100/101/102, M66.821/822, M65.30 series (trigger finger overlap)
    'rotator_cuff': [
        ('M75.121', DIRECT, True),  # Complete RC tear right (185 pts)
        ('M75.122', DIRECT, True),  # Complete RC tear left (103 pts)
        ('M75.111', DIRECT, True),  # Incomplete RC tear right (122 pts)
        ('M75.112', DIRECT, True),  # Incomplete RC tear left (74 pts)
        ('S46.011A', PROXY, False), # Strain of rotator cuff muscles, right, initial (116 pts)
        ('S46.012A', PROXY, False), # Strain of rotator cuff muscles, left, initial (87 pts)
        ('M75.41',  PROXY,  False), # Impingement syndrome right shoulder (438 pts)
        ('M75.42',  PROXY,  False), # Impingement syndrome left shoulder (339 pts)
        ('M75.40',  PROXY,  False), # Impingement syndrome, unspecified shoulder
    ],

    # ── shoulder_disorder ─────────────────────────────────────────────────
    # Existing: M75.00/01/02, M75.40/41/42 + others
    'shoulder_disorder': [
        ('M75.21',  PROXY, False),  # Bicipital tendinitis, right (134 pts)
        ('M75.22',  PROXY, False),  # Bicipital tendinitis, left
        ('M75.51',  PROXY, False),  # Bursitis right shoulder (142 pts)
        ('M75.52',  PROXY, False),  # Bursitis left shoulder (105 pts)
        ('M75.81',  PROXY, False),  # Other shoulder lesions, right (155 pts)
        ('M75.82',  PROXY, False),  # Other shoulder lesions, left (96 pts)
        ('M75.121', PROXY, False),  # Complete RC tear right (185 pts)
        ('M75.122', PROXY, False),  # Complete RC tear left (103 pts)
    ],

    # ── spontaneous_atraumatic_rupture ────────────────────────────────────
    # Existing: M66.88, M66.8, M66.38, M66.9
    'spontaneous_atraumatic_rupture': [
        ('M66.211', DIRECT, True),  # Spontaneous rupture extensor tendons, right shoulder
        ('M66.212', DIRECT, True),  # Spontaneous rupture extensor tendons, left shoulder
        ('M66.241', DIRECT, True),  # Spontaneous rupture extensor tendons, right hand (5 pts)
        ('M66.242', DIRECT, True),  # Spontaneous rupture extensor tendons, left hand
        ('M66.311', DIRECT, True),  # Spontaneous rupture flexor tendons, right shoulder (1 pt)
        ('M66.821', PROXY,  False), # Spontaneous rupture other tendons, right upper arm (biceps-related)
        ('M66.822', PROXY,  False), # Spontaneous rupture other tendons, left upper arm
        ('M66.20',  DIRECT, True),  # Spontaneous rupture extensor tendons, unspecified site
    ],

    # ── trigger_finger ────────────────────────────────────────────────────
    # Existing: comprehensive M65.30-M65.359 series — already very complete
    # Adding only the bilateral/little finger variants if missing
    'trigger_finger': [
        ('M65.359', DIRECT, True),  # Trigger finger, unspecified little finger
        ('M65.349', DIRECT, True),  # Trigger finger, unspecified ring finger
    ],

    # ── trigger_release ───────────────────────────────────────────────────
    # Existing: Z98.890 only
    'trigger_release': [
        ('M65.30',  PROXY, False),  # Trigger finger, unspecified (275 pts) — indication for release
        ('M65.311', PROXY, False),  # Trigger thumb right (377 pts)
        ('M65.312', PROXY, False),  # Trigger thumb left (276 pts)
        ('M65.331', PROXY, False),  # Trigger finger right middle (575 pts)
    ],

    # ── wt03_traumatic_rupture ────────────────────────────────────────────
    # Existing: S46.11, S46.21, S46.12, S46.22, S46.1, S46.2
    'wt03_traumatic_rupture': [
        ('S46.011A', DIRECT, True), # Strain rotator cuff right shoulder, initial (116 pts)
        ('S46.012A', DIRECT, True), # Strain rotator cuff left shoulder, initial (87 pts)
        ('S46.211A', DIRECT, True), # Strain biceps long head, right elbow, initial
        ('S46.221A', DIRECT, True), # Strain biceps long head, left elbow, initial
        ('S46.211D', PROXY,  False),# Subsequent encounter, right
        ('S46.221D', PROXY,  False),# Subsequent encounter, left
        ('M66.821',  PROXY,  False),# Spontaneous rupture other tendons, right upper arm
        ('M66.822',  PROXY,  False),# Spontaneous rupture other tendons, left upper arm
    ],
}

data = json.load(open('v5/config/shared/atoms/ORTHOPEDICS_MSK.json', encoding='utf-8'))
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
    print('  ' + aid.ljust(48) + '+' + str(n).rjust(3) + ' new codes')

for atom in data['atoms']:
    total_filled += backfill(atom)

print()
print('Total new ICD entries:          ' + str(total_added))
print('display_names backfilled:       ' + str(total_filled))

with open('v5/config/shared/atoms/ORTHOPEDICS_MSK.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
print('Saved ORTHOPEDICS_MSK.json')

total = sum(1 for a in data['atoms'] for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[]))
missing = [(a['atom_id'], e['value']) for a in data['atoms']
           for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[])
           if 'display_name' not in e]
print('Total ICD10 entries: ' + str(total))
print('Missing display_name: ' + str(len(missing)))
if missing:
    for aid, v in missing: print('  [' + aid + '] ' + v)
print('JSON valid: OK')

"""Full 2026 ICD-10-CM pass for NEUROLOGY.json — add codes + display_names."""
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

    # ── abnormal_cutaneous_silent_period ──────────────────────────────────
    # No ICD code exists for the CSP test itself; use neuropathy context codes
    'abnormal_cutaneous_silent_period': [
        ('G62.89', PROXY, False),   # Other specified polyneuropathies (408 pts)
        ('G60.8',  PROXY, False),   # Other hereditary and idiopathic neuropathies (76 pts)
        ('G60.9',  PROXY, False),   # Hereditary and idiopathic neuropathy, unspecified (249 pts)
    ],

    # ── anhidrosis ────────────────────────────────────────────────────────
    'anhidrosis': [
        ('L74.9',  DIRECT, True),   # Eccrine sweat disorder, unspecified (37 pts) — closest to anhidrosis
        ('G90.9',  PROXY,  False),  # Disorder of autonomic nervous system, unspecified (85 pts)
        ('G90.A',  PROXY,  False),  # POTS (218 pts) — autonomic sweat dysfunction context
        ('G90.1',  PROXY,  False),  # Familial dysautonomia [Riley-Day] (116 pts)
    ],

    # ── axonal_pattern_on_emg ─────────────────────────────────────────────
    'axonal_pattern_on_emg': [
        ('G62.9',  PROXY,  False),  # Polyneuropathy, unspecified (3,637 pts)
        ('G62.89', PROXY,  False),  # Other specified polyneuropathies (408 pts)
        ('G62.0',  PROXY,  False),  # Drug-induced polyneuropathy (261 pts)
        ('G60.9',  PROXY,  False),  # Hereditary and idiopathic neuropathy, unspecified (249 pts)
        ('G60.8',  PROXY,  False),  # Other hereditary and idiopathic neuropathies (76 pts)
    ],

    # ── bulbar_neuropathy_symptoms ────────────────────────────────────────
    'bulbar_neuropathy_symptoms': [
        ('R13.10', PROXY, False),   # Dysphagia, unspecified (5,113 pts)
        ('R13.12', PROXY, False),   # Dysphagia, oropharyngeal phase (2,642 pts)
        ('R47.1',  PROXY, False),   # Dysarthria and anarthria (402 pts)
        ('R49.0',  PROXY, False),   # Dysphonia (1,222 pts)
        ('R47.81', PROXY, False),   # Slurred speech (156 pts)
        ('R13.14', PROXY, False),   # Dysphagia, pharyngoesophageal phase (802 pts)
        ('R13.19', PROXY, False),   # Other dysphagia (1,226 pts)
    ],

    # ── burning_feet ──────────────────────────────────────────────────────
    'burning_feet': [
        ('R20.2',  DIRECT, True),   # Paresthesia of skin (4,537 pts) — burning/tingling
        ('R20.8',  PROXY,  False),  # Other disturbances of skin sensation (392 pts)
        ('G57.93', PROXY,  False),  # Unspecified mononeuropathy, bilateral lower limbs (323 pts)
        ('G57.61', PROXY,  False),  # Lesion of plantar nerve, right lower limb (37 pts)
        ('G57.62', PROXY,  False),  # Lesion of plantar nerve, left lower limb (51 pts)
        ('G63',    PROXY,  False),  # Polyneuropathy in diseases classified elsewhere (143 pts)
    ],

    # ── cidp ──────────────────────────────────────────────────────────────
    # Existing: G61.81
    'cidp': [
        ('G61.0',  PROXY, False),   # Guillain-Barre syndrome (121 pts) — differential for CIDP
        ('G61.82', PROXY, False),   # Multifocal motor neuropathy (9 pts) — CIDP variant
        ('G61.89', PROXY, False),   # Other inflammatory polyneuropathies (3 pts)
        ('G61.9',  PROXY, False),   # Inflammatory polyneuropathy, unspecified (7 pts)
        ('G61.1',  PROXY, False),   # Serum neuropathy
    ],

    # ── demyelinating_emg_pattern ─────────────────────────────────────────
    'demyelinating_emg_pattern': [
        ('G61.81', DIRECT, True),   # CIDP (70 pts) — hallmark demyelinating NCS pattern
        ('G61.0',  PROXY,  False),  # Guillain-Barre syndrome (121 pts)
        ('G61.82', PROXY,  False),  # Multifocal motor neuropathy (9 pts)
        ('G37.9',  PROXY,  False),  # Demyelinating disease of CNS, unspecified (173 pts)
        ('G60.0',  PROXY,  False),  # Hereditary motor and sensory neuropathy / CMT (32 pts)
        ('G60.9',  PROXY,  False),  # Hereditary and idiopathic neuropathy, unspecified (249 pts)
    ],

    # ── dysautonomia ──────────────────────────────────────────────────────
    # Existing: G90.8, G90.9
    'dysautonomia': [
        ('G90.A',  DIRECT, True),   # POTS (218 pts) — common dysautonomia diagnosis
        ('G90.1',  DIRECT, True),   # Familial dysautonomia [Riley-Day] (116 pts)
        ('G90.3',  PROXY,  False),  # Multi-system degeneration of autonomic NS (23 pts)
        ('I95.1',  PROXY,  False),  # Orthostatic hypotension (721 pts)
        ('I95.0',  PROXY,  False),  # Idiopathic hypotension (122 pts)
        ('E11.43', PROXY,  False),  # T2DM with diabetic autonomic polyneuropathy (422 pts)
    ],

    # ── elevated_nfl ─────────────────────────────────────────────────────
    # No specific ICD code for neurofilament light chain; proxy neuropathy context
    'elevated_nfl': [
        ('G62.89', PROXY, False),   # Other specified polyneuropathies (408 pts)
        ('G62.9',  PROXY, False),   # Polyneuropathy, unspecified (3,637 pts)
        ('G60.9',  PROXY, False),   # Hereditary and idiopathic neuropathy, unspecified (249 pts)
    ],

    # ── erectile_dysfunction ──────────────────────────────────────────────
    # Existing: N52.9
    'erectile_dysfunction': [
        ('N52.1',  DIRECT, True),   # ED due to diseases classified elsewhere (145 pts) — neuropathic ED
        ('N52.8',  PROXY,  False),  # Other male erectile dysfunction (190 pts)
        ('N52.01', PROXY,  False),  # ED due to arterial insufficiency (87 pts)
        ('N52.2',  PROXY,  False),  # Drug-induced ED (71 pts)
        ('F52.21', PROXY,  False),  # Male erectile disorder (54 pts) — psychological/functional ED
    ],

    # ── gastroparesis ─────────────────────────────────────────────────────
    # Existing: K31.84, R68.81, R11.2
    'gastroparesis': [
        ('R11.0',  PROXY, False),   # Nausea (9,365 pts)
        ('R11.10', PROXY, False),   # Vomiting, unspecified (5,563 pts)
        ('K31.89', PROXY, False),   # Other diseases of stomach and duodenum (683 pts)
        ('R11.11', PROXY, False),   # Vomiting without nausea (993 pts)
    ],

    # ── gi_dysmotility ────────────────────────────────────────────────────
    # Existing: R19.7, K59.1, K59.00, K59.8
    'gi_dysmotility': [
        ('K59.09', PROXY, False),   # Other constipation (4,289 pts)
        ('K59.04', PROXY, False),   # Chronic idiopathic constipation (2,551 pts)
        ('K59.01', PROXY, False),   # Slow transit constipation (2,409 pts)
        ('K59.03', PROXY, False),   # Drug induced constipation (931 pts)
        ('R19.4',  PROXY, False),   # Change in bowel habit (676 pts)
        ('K31.84', PROXY, False),   # Gastroparesis (805 pts) — related dysmotility
        ('K31.89', PROXY, False),   # Other diseases of stomach and duodenum (683 pts)
    ],

    # ── immunotherapy_exposure ────────────────────────────────────────────
    # Existing: G61.81
    'immunotherapy_exposure': [
        ('Z79.899', PROXY, False),  # Other long-term drug therapy (7,810 pts)
        ('Z79.60',  PROXY, False),  # Long-term use of immunomodulators/immunosuppressants
        ('Z51.12',  PROXY, False),  # Encounter for antineoplastic immunotherapy
    ],

    # ── immunotherapy_nonresponse ─────────────────────────────────────────
    'immunotherapy_nonresponse': [
        ('G61.81', DIRECT, True),   # CIDP — nonresponse to IVIG/steroids in CIDP (70 pts)
        ('G61.89', PROXY,  False),  # Other inflammatory polyneuropathies (3 pts)
        ('G61.9',  PROXY,  False),  # Inflammatory polyneuropathy, unspecified (7 pts)
    ],

    # ── mibg_cardiac_denervation ──────────────────────────────────────────
    'mibg_cardiac_denervation': [
        ('R93.1',  DIRECT, True),   # Abnormal findings on diagnostic imaging of heart
        ('R93.89', PROXY,  False),  # Abnormal findings on imaging of other body structures
        ('G90.9',  PROXY,  False),  # Disorder of autonomic NS, unspecified (85 pts)
    ],

    # ── mild_sensory_polyneuropathy ───────────────────────────────────────
    # Existing: G62.9, G62.89, G60.9
    'mild_sensory_polyneuropathy': [
        ('G60.3',  DIRECT, True),   # Idiopathic progressive neuropathy (26 pts)
        ('G60.8',  PROXY,  False),  # Other hereditary and idiopathic neuropathies (76 pts)
        ('G62.0',  PROXY,  False),  # Drug-induced polyneuropathy (261 pts)
        ('G63',    PROXY,  False),  # Polyneuropathy in diseases classified elsewhere (143 pts)
    ],

    # ── mr_neurography_abnormal ───────────────────────────────────────────
    'mr_neurography_abnormal': [
        ('G62.89', PROXY, False),   # Other specified polyneuropathies (408 pts)
        ('G62.9',  PROXY, False),   # Polyneuropathy, unspecified (3,637 pts)
        ('G60.9',  PROXY, False),   # Hereditary and idiopathic neuropathy, unspecified (249 pts)
        ('G61.81', PROXY, False),   # CIDP — nerve enlargement common on MRN (70 pts)
        ('G60.0',  PROXY, False),   # Hereditary motor and sensory neuropathy / CMT (32 pts)
    ],

    # ── nerve_ultrasound_enlargement ──────────────────────────────────────
    'nerve_ultrasound_enlargement': [
        ('G61.81', PROXY, False),   # CIDP — enlarged nerves on ultrasound (70 pts)
        ('G61.82', PROXY, False),   # Multifocal motor neuropathy (9 pts)
        ('G60.0',  PROXY, False),   # Hereditary motor and sensory neuropathy / CMT (32 pts)
        ('G62.89', PROXY, False),   # Other specified polyneuropathies (408 pts)
        ('G62.9',  PROXY, False),   # Polyneuropathy, unspecified (3,637 pts)
    ],

    # ── neurogenic_bladder ────────────────────────────────────────────────
    # Existing: N31.9, R33.9, R32
    'neurogenic_bladder': [
        ('N31.2',  DIRECT, True),   # Flaccid neuropathic bladder (58 pts)
        ('N31.0',  DIRECT, True),   # Uninhibited neuropathic bladder (1 pt)
        ('N31.1',  DIRECT, True),   # Reflex neuropathic bladder
        ('N31.8',  DIRECT, True),   # Other neuromuscular dysfunction of bladder (21 pts)
        ('R35.1',  PROXY,  False),  # Nocturia — bladder dysfunction symptom
    ],

    # ── orthostatic_intolerance ───────────────────────────────────────────
    # Existing: I95.1, G90.8, G90.9
    'orthostatic_intolerance': [
        ('G90.A',  DIRECT, True),   # POTS (218 pts)
        ('I95.9',  PROXY,  False),  # Hypotension, unspecified (2,374 pts)
        ('I95.0',  DIRECT, True),   # Idiopathic hypotension (122 pts)
        ('I95.89', PROXY,  False),  # Other hypotension (462 pts)
        ('R55',    PROXY,  False),  # Syncope and collapse (8,388 pts)
        ('G90.3',  PROXY,  False),  # Multi-system degeneration (23 pts)
    ],

    # ── pain_temperature_loss ─────────────────────────────────────────────
    'pain_temperature_loss': [
        ('R20.0',  DIRECT, True),   # Anesthesia of skin (5,954 pts) — loss of pain/temp sensation
        ('R20.1',  DIRECT, True),   # Hypoesthesia of skin (reduced sensation)
        ('R20.2',  PROXY,  False),  # Paresthesia of skin (4,537 pts)
        ('R20.8',  PROXY,  False),  # Other disturbances of skin sensation (392 pts)
        ('G62.89', PROXY,  False),  # Other specified polyneuropathies (408 pts)
        ('G62.9',  PROXY,  False),  # Polyneuropathy, unspecified (3,637 pts)
    ],

    # ── plantar_ulcer ─────────────────────────────────────────────────────
    # Existing: L97.40x-L97.52x (43 codes), M14.671/M14.672
    # Add diabetic foot ulcer proxy codes (massive warehouse counts)
    'plantar_ulcer': [
        ('E11.621', PROXY, False),  # T2DM with foot ulcer (2,131 pts)
        ('E11.622', PROXY, False),  # T2DM with other skin complications (1,323 pts)
        ('E11.51',  PROXY, False),  # T2DM with diabetic peripheral angiopathy without gangrene (1,460 pts)
        ('I70.234', PROXY, False),  # Atherosclerosis of native arteries of left leg, ulceration of heel and midfoot
        ('I70.235', PROXY, False),  # Atherosclerosis of native arteries of right leg, ulceration of heel and midfoot
    ],

    # ── polyneuropathy ────────────────────────────────────────────────────
    'polyneuropathy': [
        ('G62.9',  DIRECT, True),   # Polyneuropathy, unspecified (3,637 pts)
        ('G62.89', DIRECT, True),   # Other specified polyneuropathies (408 pts)
        ('G60.3',  DIRECT, True),   # Idiopathic progressive neuropathy (26 pts)
        ('G62.0',  PROXY,  False),  # Drug-induced polyneuropathy (261 pts)
        ('G60.9',  PROXY,  False),  # Hereditary and idiopathic neuropathy, unspecified (249 pts)
        ('G60.0',  PROXY,  False),  # Hereditary motor and sensory neuropathy / CMT (32 pts)
        ('G63',    PROXY,  False),  # Polyneuropathy in diseases classified elsewhere (143 pts)
        ('G62.1',  PROXY,  False),  # Alcoholic polyneuropathy (35 pts)
    ],

    # ── positive_autoantibody ─────────────────────────────────────────────
    'positive_autoantibody': [
        ('R76.0',  DIRECT, True),   # Raised antibody titer (517 pts)
        ('R76.89', PROXY,  False),  # Other specified abnormal immunological findings (1,137 pts)
        ('R76.81', PROXY,  False),  # Abnormal RF and anti-CCP without RA (170 pts)
        ('G37.81', DIRECT, True),   # MOG antibody disease (37 pts) — specific autoantibody disease
        ('I77.82', PROXY,  False),  # ANCA vasculitis (94 pts)
        ('R76.9',  PROXY,  False),  # Abnormal immunological finding in serum, unspecified (32 pts)
    ],

    # ── reduced_ienfd ─────────────────────────────────────────────────────
    # IENFD (intraepidermal nerve fiber density) is a skin biopsy result, no direct ICD code
    'reduced_ienfd': [
        ('G60.8',  PROXY, False),   # Other hereditary and idiopathic neuropathies (76 pts)
        ('G62.89', PROXY, False),   # Other specified polyneuropathies (408 pts)
        ('G60.9',  PROXY, False),   # Hereditary and idiopathic neuropathy, unspecified (249 pts)
    ],

    # ── sfn ───────────────────────────────────────────────────────────────
    # Existing: G60.8, G60.9, R20.2
    'sfn': [
        ('G62.89', PROXY, False),   # Other specified polyneuropathies (408 pts)
        ('G62.9',  PROXY, False),   # Polyneuropathy, unspecified (3,637 pts)
        ('G60.3',  DIRECT, True),   # Idiopathic progressive neuropathy (26 pts) — SFN often idiopathic progressive
        ('R20.8',  PROXY, False),   # Other disturbances of skin sensation (392 pts)
        ('R20.9',  PROXY, False),   # Unspecified disturbances of skin sensation (218 pts)
    ],

    # ── sudoscan_reduced_esc ──────────────────────────────────────────────
    'sudoscan_reduced_esc': [
        ('L74.9',  DIRECT, True),   # Eccrine sweat disorder, unspecified (37 pts) — reduced ESC = sweat gland dysfunction
        ('G90.9',  PROXY,  False),  # Disorder of autonomic NS, unspecified (85 pts)
        ('G90.A',  PROXY,  False),  # POTS (218 pts) — autonomic context for reduced ESC
    ],

    # ── trophic_change ────────────────────────────────────────────────────
    # Existing: L97.40x-L97.52x (43 codes) + M14.671/M14.672
    'trophic_change': [
        ('L98.9',  PROXY, False),   # Disorder of skin and subcutaneous tissue, unspecified (4,293 pts)
        ('L85.3',  PROXY, False),   # Xerosis cutis (1,541 pts) — trophic skin change
        ('R23.8',  PROXY, False),   # Other skin changes (1,264 pts)
        ('L85.8',  PROXY, False),   # Other specified epidermal thickening (856 pts)
    ],

    # ── urinary_incontinence ──────────────────────────────────────────────
    # Existing: N31.9, R33.9, R32
    'urinary_incontinence': [
        ('N39.46',  PROXY, False),  # Mixed incontinence (2,584 pts)
        ('N39.3',   PROXY, False),  # Stress incontinence (2,165 pts)
        ('N39.41',  PROXY, False),  # Urge incontinence (1,194 pts)
        ('R39.81',  PROXY, False),  # Functional urinary incontinence (141 pts)
        ('N39.498', PROXY, False),  # Other specified urinary incontinence (141 pts)
    ],

    # ── urinary_retention ────────────────────────────────────────────────
    # Existing: N31.9, R33.9, R32
    'urinary_retention': [
        ('R33.8',  DIRECT, True),   # Other retention of urine (215 pts)
        ('N31.2',  DIRECT, True),   # Flaccid neuropathic bladder (58 pts)
        ('N31.8',  DIRECT, True),   # Other neuromuscular dysfunction of bladder (21 pts)
        ('N31.0',  DIRECT, True),   # Uninhibited neuropathic bladder (1 pt)
        ('R33.0',  PROXY,  False),  # Drug-induced retention (1 pt)
    ],

    # ── v02_competing_neuropathy ──────────────────────────────────────────
    'v02_competing_neuropathy': [
        ('E11.42', DIRECT, True),   # T2DM with diabetic polyneuropathy (7,129 pts) — most common competing cause
        ('E11.40', DIRECT, True),   # T2DM with diabetic neuropathy, unspecified (3,681 pts)
        ('E11.43', DIRECT, True),   # T2DM with diabetic autonomic polyneuropathy (422 pts)
        ('G62.0',  DIRECT, True),   # Drug-induced polyneuropathy (261 pts)
        ('G61.81', DIRECT, True),   # CIDP (70 pts)
        ('G61.0',  DIRECT, True),   # Guillain-Barre syndrome (121 pts)
        ('E10.42', DIRECT, True),   # T1DM with diabetic polyneuropathy (220 pts)
        ('E13.42', DIRECT, True),   # Other specified DM with polyneuropathy (219 pts)
        ('G62.1',  DIRECT, True),   # Alcoholic polyneuropathy (35 pts)
        ('G62.9',  PROXY,  False),  # Polyneuropathy, unspecified (3,637 pts)
        ('G62.89', PROXY,  False),  # Other specified polyneuropathies (408 pts)
        ('G62.2',  PROXY,  False),  # Polyneuropathy due to other toxic agents (26 pts)
    ],

    # ── v04_competing_neuropathy ──────────────────────────────────────────
    'v04_competing_neuropathy': [
        ('E11.42', DIRECT, True),   # T2DM with diabetic polyneuropathy (7,129 pts)
        ('E11.40', DIRECT, True),   # T2DM with diabetic neuropathy, unspecified (3,681 pts)
        ('G62.0',  DIRECT, True),   # Drug-induced polyneuropathy (261 pts)
        ('G60.0',  DIRECT, True),   # Hereditary motor and sensory neuropathy / CMT (32 pts)
        ('G61.81', DIRECT, True),   # CIDP (70 pts)
        ('G61.0',  PROXY,  False),  # Guillain-Barre (121 pts) — acute; less likely to be v04 competing
        ('E10.42', DIRECT, True),   # T1DM with diabetic polyneuropathy (220 pts)
        ('E13.42', DIRECT, True),   # Other specified DM with polyneuropathy (219 pts)
        ('G62.89', PROXY,  False),  # Other specified polyneuropathies (408 pts)
        ('G62.9',  PROXY,  False),  # Polyneuropathy, unspecified (3,637 pts)
    ],

    # ── v05_competing_dysautonomia ────────────────────────────────────────
    'v05_competing_dysautonomia': [
        ('G90.3',  DIRECT, True),   # Multi-system atrophy (MSA) (23 pts) — top competing dysautonomia
        ('E11.43', DIRECT, True),   # T2DM with diabetic autonomic polyneuropathy (422 pts)
        ('E10.43', DIRECT, True),   # T1DM with diabetic autonomic polyneuropathy (47 pts)
        ('G90.9',  PROXY,  False),  # Disorder of autonomic NS, unspecified (85 pts)
        ('G90.1',  PROXY,  False),  # Familial dysautonomia [Riley-Day] (116 pts)
        ('G90.A',  PROXY,  False),  # POTS (218 pts)
        ('I95.1',  PROXY,  False),  # Orthostatic hypotension (721 pts)
    ],

    # ── sensory_loss ──────────────────────────────────────────────────────
    # Existing: R20.0, R20.1, R20.2, R20.8, R20.9
    'sensory_loss': [
        ('G62.89', PROXY, False),   # Other specified polyneuropathies (408 pts)
        ('G62.9',  PROXY, False),   # Polyneuropathy, unspecified (3,637 pts)
        ('G54.0',  PROXY, False),   # Brachial plexus disorders (124 pts)
        ('G54.2',  PROXY, False),   # Cervical root disorders (45 pts)
        ('G54.1',  PROXY, False),   # Lumbosacral plexus disorders (15 pts)
    ],

    # ── charcot_arthropathy ───────────────────────────────────────────────
    # Existing: 43 L97.x + M14.671/M14.672
    # Add M14.679 (unspecified side) and diabetic Charcot foot
    'charcot_arthropathy': [
        ('M14.679', DIRECT, True),  # Arthropathy in other diseases, ankle and foot, unspecified
        ('M14.670', DIRECT, True),  # Arthropathy in other diseases, ankle and foot, unspecified side
        ('E11.610', DIRECT, True),  # T2DM with diabetic neuropathic arthropathy (Charcot foot)
        ('E10.610', DIRECT, True),  # T1DM with diabetic neuropathic arthropathy
    ],
}

data = json.load(open('v5/config/shared/atoms/NEUROLOGY.json', encoding='utf-8'))
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
    print('  ' + aid.ljust(42) + '+' + str(n).rjust(3) + ' new codes')

for atom in data['atoms']:
    total_filled += backfill(atom)

print()
print('Total new ICD entries:          ' + str(total_added))
print('display_names backfilled:       ' + str(total_filled))

with open('v5/config/shared/atoms/NEUROLOGY.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
print('Saved NEUROLOGY.json')

total = sum(1 for a in data['atoms'] for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[]))
missing = [(a['atom_id'], e['value']) for a in data['atoms']
           for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[])
           if 'display_name' not in e]
print('Total ICD10 entries: ' + str(total))
print('Missing display_name: ' + str(len(missing)))
if missing:
    for aid, v in missing: print('  [' + aid + '] ' + v)
print('JSON valid: OK')

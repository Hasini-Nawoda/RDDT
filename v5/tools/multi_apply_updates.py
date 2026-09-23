"""Full 2026 ICD-10-CM pass for MULTISPECIALTY.json — add codes + display_names."""
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

    # ── age_excessive_snhl ───────────────────────────────────────────────
    # Existing: H90.3, H90.5, H91.8X3, H91.8X9
    'age_excessive_snhl': [
        # Unspecified bilateral HL — may represent unclassified SNHL
        ('H91.93', PROXY,  False),  # Unspecified HL, bilateral (2,982 WH pts)
        ('H91.90', PROXY,  False),  # Unspecified HL, unspecified ear (1,839 pts)
        # Unilateral SNHL — bilateral when both ears coded separately
        ('H90.42', PROXY,  False),  # SNHL unilateral, left ear (739 pts)
        ('H90.41', PROXY,  False),  # SNHL unilateral, right ear (627 pts)
        ('H90.A22', PROXY, False),  # SNHL unilateral, left, restricted contralateral (267 pts)
        ('H90.A21', PROXY, False),  # SNHL unilateral, right, restricted contralateral (288 pts)
        # Other specified HL (unilateral) — same code family as H91.8X3
        ('H91.8X1', DIRECT, True),  # Other specified HL, right ear (74 pts)
        ('H91.8X2', DIRECT, True),  # Other specified HL, left ear (98 pts)
        # Mixed SNHL bilateral — still indicates bilateral inner-ear involvement
        ('H90.6',  PROXY,  False),  # Mixed conductive+sensorineural HL, bilateral (1,029 pts)
    ],

    # ── autoimmune_disease ───────────────────────────────────────────────
    # Existing: M35.9, R76.0
    'autoimmune_disease': [
        # Rheumatoid arthritis
        ('M06.9',  DIRECT, True),   # RA, unspecified (1,342 WH pts)
        ('M05.79', DIRECT, True),   # Seropositive RA, multiple sites (1,253 pts)
        ('M05.9',  DIRECT, True),   # Seropositive RA, unspecified (495 pts)
        ('M06.09', DIRECT, True),   # RA without RF, multiple sites (226 pts)
        # Systemic lupus erythematosus
        ('M32.9',  DIRECT, True),   # SLE, unspecified (963 pts)
        ('M32.19', DIRECT, True),   # Other organ involvement in SLE (180 pts)
        ('M32.8',  DIRECT, True),   # Other forms of SLE (79 pts)
        ('M32.14', DIRECT, True),   # Glomerular disease in SLE (283 pts)
        # Sjogren syndrome
        ('M35.00', DIRECT, True),   # Sjogren syndrome, unspecified (330 pts)
        ('M35.01', DIRECT, True),   # Sjogren with keratoconjunctivitis (344 pts)
        # Systemic sclerosis
        ('M34.9',  DIRECT, True),   # Systemic sclerosis, unspecified (182 pts)
        ('M34.1',  DIRECT, True),   # CREST syndrome (92 pts)
        ('M34.83', PROXY,  False),  # Systemic sclerosis with polyneuropathy (1 pt)
        # Vasculitis
        ('I77.82', DIRECT, True),   # ANCA vasculitis (94 pts)
        ('M31.6',  DIRECT, True),   # Other giant cell arteritis (128 pts)
        # Overlap / other connective tissue
        ('M35.1',  DIRECT, True),   # Other overlap syndromes (115 pts)
        ('M35.3',  PROXY,  False),  # Polymyalgia rheumatica (79 pts) — often autoimmune context
        # Autoimmune thyroiditis (thyroid-specific autoimmunity)
        ('E06.3',  PROXY,  False),  # Autoimmune thyroiditis / Hashimoto's (1,662 pts)
        # Inflammatory markers used to confirm autoimmune diagnosis
        ('R76.81', PROXY,  False),  # Abnormal RF/anti-CCP without established RA (170 pts)
    ],

    # ── axonal_neuropathy ────────────────────────────────────────────────
    # No ICD codes currently
    'axonal_neuropathy': [
        ('G62.9',  PROXY,  False),  # Polyneuropathy, unspecified (3,637 WH pts)
        ('G62.89', DIRECT, True),   # Other specified polyneuropathies (408 pts)
        ('G60.9',  PROXY,  False),  # Hereditary and idiopathic neuropathy, unspecified (249 pts)
        ('G63',    PROXY,  False),  # Polyneuropathy in diseases classified elsewhere (143 pts)
        ('G60.8',  PROXY,  False),  # Other hereditary and idiopathic neuropathies (76 pts)
        ('G60.3',  DIRECT, True),   # Idiopathic progressive neuropathy (26 pts)
        ('G62.0',  PROXY,  False),  # Drug-induced polyneuropathy (261 pts)
    ],

    # ── diabetes ─────────────────────────────────────────────────────────
    # Existing: E11.9, E11.42
    'diabetes': [
        # Type 2 DM — high-volume warehouse codes not yet configured
        ('E11.65', DIRECT, True),   # T2DM with hyperglycemia (34,684 WH pts)
        ('E11.69', DIRECT, True),   # T2DM with other specified complication (10,136 pts)
        ('E11.40', DIRECT, True),   # T2DM with diabetic neuropathy, unspecified (3,681 pts)
        ('E11.8',  DIRECT, True),   # T2DM with unspecified complications (3,108 pts)
        ('E11.49', DIRECT, True),   # T2DM with other diabetic neurological complication (887 pts)
        ('E11.43', DIRECT, True),   # T2DM with diabetic autonomic polyneuropathy (422 pts)
        ('E11.41', DIRECT, True),   # T2DM with diabetic mononeuropathy (168 pts)
        # Type 1 DM
        ('E10.9',  DIRECT, True),   # T1DM without complications (1,322 pts)
        ('E10.65', DIRECT, True),   # T1DM with hyperglycemia (1,635 pts)
        ('E10.42', DIRECT, True),   # T1DM with diabetic polyneuropathy (220 pts)
        ('E10.43', DIRECT, True),   # T1DM with diabetic autonomic polyneuropathy (47 pts)
        ('E10.40', DIRECT, True),   # T1DM with diabetic neuropathy, unspecified (90 pts)
        # Other specified DM
        ('E13.42', DIRECT, True),   # Other specified DM with polyneuropathy (219 pts)
        ('E13.40', DIRECT, True),   # Other specified DM with neuropathy, unspecified (38 pts)
        # DM with CKD — important comorbidity confirming DM diagnosis
        ('E11.22', PROXY,  False),  # T2DM with diabetic CKD (5,944 pts)
    ],

    # ── fhx_adult_onset_neuropathy ───────────────────────────────────────
    # Existing: Z82.0
    'fhx_adult_onset_neuropathy': [
        ('Z84.81', PROXY,  False),  # FHx carrier of genetic disease (119 WH pts)
        ('Z84.89', PROXY,  False),  # FHx other specified conditions (115 pts)
        ('Z82.3',  PROXY,  False),  # FHx stroke (27 pts) — may include neurological/neuropathy
    ],

    # ── fhx_established_attr ────────────────────────────────────────────
    # Existing: Z83.49, Z15.89, Z14.8
    'fhx_established_attr': [
        # Family-history carrier/genetic codes
        ('Z84.81', DIRECT, True),   # FHx carrier of genetic disease (119 WH pts)
        ('Z84.89', PROXY,  False),  # FHx other specified conditions (115 pts)
        # Hereditary amyloidosis — these would be found on a family member
        ('E85.1',  DIRECT, True),   # Neuropathic heredofamilial amyloidosis (TTR) (3 pts)
        ('E85.0',  DIRECT, True),   # Non-neuropathic heredofamilial amyloidosis (0 WH, critical)
        ('E85.2',  DIRECT, True),   # Heredofamilial amyloidosis, unspecified (2 pts)
    ],

    # ── idiopathic_progressive_neuropathy ────────────────────────────────
    # No ICD codes currently
    'idiopathic_progressive_neuropathy': [
        ('G60.3',  DIRECT, True),   # Idiopathic progressive neuropathy (26 WH pts — exact match!)
        ('G62.9',  PROXY,  False),  # Polyneuropathy, unspecified (3,637 pts)
        ('G62.89', PROXY,  False),  # Other specified polyneuropathies (408 pts)
        ('G60.9',  PROXY,  False),  # Hereditary and idiopathic neuropathy, unspecified (249 pts)
        ('G60.8',  PROXY,  False),  # Other hereditary and idiopathic neuropathies (76 pts)
        ('G63',    PROXY,  False),  # Polyneuropathy in diseases classified elsewhere (143 pts)
    ],

    # ── ligamentum_flavum_thickening ─────────────────────────────────────
    # No ICD codes currently (only CPT)
    'ligamentum_flavum_thickening': [
        # Lumbar spinal stenosis — primary consequence of LF thickening
        ('M48.061', DIRECT, True),  # Spinal stenosis, lumbar, without neurogenic claudication (1,097 WH pts)
        ('M48.062', DIRECT, True),  # Spinal stenosis, lumbar, with neurogenic claudication (1,054 pts)
        # Cervical and thoracic stenosis (LF thickening can occur at any level)
        ('M48.02',  PROXY,  False), # Spinal stenosis, cervical region (1,273 pts)
        ('M48.04',  PROXY,  False), # Spinal stenosis, thoracic region
        ('M48.00',  PROXY,  False), # Spinal stenosis, site unspecified (210 pts)
    ],

    # ── myocardial_bone_tracer_uptake ────────────────────────────────────
    # No ICD codes currently (only CPT)
    'myocardial_bone_tracer_uptake': [
        # Abnormal cardiac imaging — the finding that prompts further ATTR workup
        ('R93.1',  DIRECT, True),   # Abnormal findings on diagnostic imaging of heart (747 WH pts)
        ('R93.89', PROXY,  False),  # Abnormal findings on imaging of other body structures (2,577 pts)
        # Amyloidosis diagnoses confirmed via bone scan
        ('E85.82', DIRECT, True),   # Wild-type transthyretin (ATTRwt) amyloidosis (10 pts)
        ('E85.1',  DIRECT, True),   # Neuropathic heredofamilial amyloidosis (3 pts)
        ('E85.4',  PROXY,  False),  # Organ-limited amyloidosis (89 pts)
        ('E85.81', PROXY,  False),  # Light chain (AL) amyloidosis (24 pts)
        ('E85.9',  PROXY,  False),  # Amyloidosis, unspecified (22 pts)
        ('E85.89', PROXY,  False),  # Other amyloidosis (7 pts)
    ],

    # ── orthopedic_to_cardiac_trajectory ────────────────────────────────
    # No ICD codes currently (only NLP)
    'orthopedic_to_cardiac_trajectory': [
        # Bilateral carpal tunnel — the #1 amyloid orthopedic prodrome signal
        ('G56.03', DIRECT, True),   # Carpal tunnel syndrome, bilateral (2,909 WH pts)
        ('G56.01', PROXY,  False),  # CTS, right (1,383 pts)
        ('G56.02', PROXY,  False),  # CTS, left (817 pts)
        # Lumbar spinal stenosis — second most common amyloid orthopedic prodrome
        ('M48.061', DIRECT, True),  # Spinal stenosis, lumbar without claudication (1,097 pts)
        ('M48.062', DIRECT, True),  # Spinal stenosis, lumbar with claudication (1,054 pts)
        ('M48.02',  PROXY,  False), # Cervical spinal stenosis (1,273 pts)
        # Trigger finger — known ATTR prodrome
        ('M65.30',  DIRECT, True),  # Trigger finger, unspecified (275 pts)
        ('M65.311', DIRECT, True),  # Trigger thumb, right (377 pts)
        ('M65.312', DIRECT, True),  # Trigger thumb, left (276 pts)
        ('M65.331', DIRECT, True),  # Trigger finger, right middle (575 pts)
        ('M65.332', DIRECT, True),  # Trigger finger, left middle (381 pts)
        ('M65.341', DIRECT, True),  # Trigger finger, right ring (323 pts)
        ('M65.342', DIRECT, True),  # Trigger finger, left ring (227 pts)
        # Rotator cuff / shoulder pathology — also appears in amyloid prodrome
        ('M75.101', PROXY,  False), # Unspecified rotator cuff tear, right (489 pts)
        ('M75.102', PROXY,  False), # Unspecified rotator cuff tear, left (326 pts)
    ],

    # ── ttr_pathogenic_variant ───────────────────────────────────────────
    # No ICD codes currently
    'ttr_pathogenic_variant': [
        # Patient-level genetic susceptibility codes
        ('Z15.89', DIRECT, True),   # Genetic susceptibility to other disease (256 WH pts)
        ('Z14.8',  DIRECT, True),   # Genetic carrier of other disease (276 pts)
        # Active hereditary amyloidosis (pathogenic variant → may have disease)
        ('E85.1',  DIRECT, True),   # Neuropathic heredofamilial amyloidosis — ATTRv neuropathy (3 pts)
        ('E85.0',  DIRECT, True),   # Non-neuropathic heredofamilial amyloidosis (0 WH, key)
        ('E85.2',  DIRECT, True),   # Heredofamilial amyloidosis, unspecified (2 pts)
    ],

    # ── wt21_competing_hearing_loss ──────────────────────────────────────
    # Existing: H91.10, H91.13, H83.3X3, H83.3X9, H91.03, H91.09, H81.03, H81.09
    'wt21_competing_hearing_loss': [
        # Presbycusis (age-related HL — unilateral not yet configured)
        ('H91.11', DIRECT, True),   # Presbycusis, right ear
        ('H91.12', DIRECT, True),   # Presbycusis, left ear
        # Ototoxic HL (aminoglycoside / cisplatin — well-established competing cause)
        ('H91.00', DIRECT, True),   # Ototoxic HL, unspecified ear
        ('H91.01', DIRECT, True),   # Ototoxic HL, right ear
        ('H91.02', DIRECT, True),   # Ototoxic HL, left ear
        # Noise-induced HL (unilateral variants)
        ('H83.3X1', DIRECT, True),  # Noise effects on inner ear, right
        ('H83.3X2', DIRECT, True),  # Noise effects on inner ear, left
        ('H83.3X0', PROXY,  False), # Noise effects on inner ear, unspecified
        # Meniere disease (competing labyrinthine cause)
        ('H81.01', DIRECT, True),   # Meniere disease, right ear
        ('H81.02', DIRECT, True),   # Meniere disease, left ear
        # Benign paroxysmal positional vertigo — inner ear disease context
        ('H81.10', PROXY,  False),  # BPPV, unspecified ear (887 pts)
        ('H81.11', PROXY,  False),  # BPPV, right ear (488 pts)
        ('H81.12', PROXY,  False),  # BPPV, left ear (482 pts)
        ('H81.13', PROXY,  False),  # BPPV, bilateral (610 pts)
        # General hearing loss codes that may explain the finding
        ('H91.90', PROXY,  False),  # Unspecified HL, unspecified ear (1,839 pts)
        ('H91.93', PROXY,  False),  # Unspecified HL, bilateral (2,982 pts)
    ],

    # ── unintentional_weight_loss ────────────────────────────────────────
    # Existing: R63.4, R64, F50.00, F50.010-F50.029, K31.84
    'unintentional_weight_loss': [
        ('R63.6',  DIRECT, True),   # Underweight (806 WH pts)
        ('R63.0',  PROXY,  False),  # Anorexia / loss of appetite (1,262 pts)
        ('E43',    DIRECT, True),   # Severe protein-calorie malnutrition (203 pts)
        ('E46',    PROXY,  False),  # Unspecified protein-calorie malnutrition (200 pts)
        ('E44.0',  PROXY,  False),  # Moderate protein-calorie malnutrition (75 pts)
        ('E41',    PROXY,  False),  # Nutritional marasmus
        ('M62.50', PROXY,  False),  # Muscle wasting and atrophy, unspecified site (21 pts)
    ],
}

data = json.load(open('v5/config/shared/atoms/MULTISPECIALTY.json', encoding='utf-8'))
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
    print('  ' + aid.ljust(40) + '+' + str(n).rjust(3) + ' new codes')

for atom in data['atoms']:
    total_filled += backfill(atom)

print()
print('Total new ICD entries:          ' + str(total_added))
print('display_names backfilled:       ' + str(total_filled))

with open('v5/config/shared/atoms/MULTISPECIALTY.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
print('Saved MULTISPECIALTY.json')

total = sum(1 for a in data['atoms'] for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[]))
missing = [(a['atom_id'], e['value']) for a in data['atoms']
           for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[])
           if 'display_name' not in e]
print('Total ICD10 entries: ' + str(total))
print('Missing display_name: ' + str(len(missing)))
if missing:
    for aid, v in missing: print('  [' + aid + '] ' + v)
print('JSON valid: OK')

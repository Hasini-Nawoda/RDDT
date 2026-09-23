"""
Full 2026 ICD-10-CM pass for GASTROENTEROLOGY.json.
Adds new codes + display_name to all ICD10 entries.
"""
import json, csv

def add_dot(code):
    code = code.strip()
    if len(code) > 3 and '.' not in code:
        return code[:3] + '.' + code[3:]
    return code

# Load 2026 ICD dict
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

# Load warehouse
warehouse = {}
with open('not_for_snowflake/sql_root/icd_codes_with_meaning.csv', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        warehouse[row['DIAGNOSIS_CODE']] = int(row['PATIENT_COUNT'])

def lookup(code):
    return icd2026.get(code) or icd2026.get(code.replace('.', ''))

def make_entry(value, role, standalone):
    desc = lookup(value)
    e = {
        'value': value,
        'can_fire_atom_alone': standalone,
        'review_status': 'WAREHOUSE_REVIEWED',
        'mapping_role': role,
        'match_mode': 'EXACT',
    }
    if desc:
        e['display_name'] = desc
    else:
        e['display_name'] = value + ' [description not in 2026 official file]'
    return e

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

def backfill_display_names(atom):
    """Add display_name to any existing ICD10 entries that don't have one."""
    filled = 0
    for entry in atom.get('extraction', {}).get('codes', {}).get('ICD10', []):
        if 'display_name' not in entry:
            desc = lookup(entry['value'])
            entry['display_name'] = desc if desc else entry['value'] + ' [no 2026 description]'
            filled += 1
    return filled

DIRECT = 'DIRECT_TARGET'
PROXY  = 'PROXY_SUPPORT'
SUPP   = 'SUPPORTING'

# ── Per-atom additions ──────────────────────────────────────────────────────
ADDITIONS = {

    'alternating_bowel_habit': [
        # IBS mixed type is the canonical coded form of alternating bowel habit
        ('K58.2',  DIRECT, True),   # Mixed irritable bowel syndrome
        ('K58.9',  PROXY,  False),  # IBS without diarrhea (unspecified)
        ('K58.0',  PROXY,  False),  # IBS with diarrhea
        ('K58.1',  PROXY,  False),  # IBS with constipation
        ('R19.4',  DIRECT, True),   # Change in bowel habit
        ('K59.9',  PROXY,  False),  # Functional intestinal disorder, unspecified
    ],

    'choking': [
        # Aspiration and swallowing mechanism codes not yet in atom
        ('R13.0',  DIRECT, True),   # Aphagia (inability to swallow)
        ('R13.11', DIRECT, True),   # Dysphagia, oral phase
        ('R13.12', DIRECT, True),   # Dysphagia, oropharyngeal phase
        ('R13.13', DIRECT, True),   # Dysphagia, pharyngeal phase
        ('R13.14', DIRECT, True),   # Dysphagia, pharyngoesophageal phase
        ('J69.0',  PROXY,  False),  # Aspiration pneumonitis due to solids/liquids
        ('J69.1',  PROXY,  False),  # Pneumonitis due to oils/essences (aspiration)
        ('T17.990A', PROXY, False), # Food in other respiratory tract causing other injury
    ],

    'constipation': [
        # K59 subtypes were all missing
        ('K59.01', DIRECT, True),   # Slow transit constipation
        ('K59.02', DIRECT, True),   # Outlet dysfunction constipation
        ('K59.03', DIRECT, True),   # Drug-induced constipation
        ('K59.04', DIRECT, True),   # Chronic idiopathic constipation
        ('K59.09', DIRECT, True),   # Other constipation
        ('K56.41', PROXY,  False),  # Fecal impaction (severe constipation)
        ('R15.0',  PROXY,  False),  # Incomplete defecation
        ('R15.9',  PROXY,  False),  # Full incontinence of feces (autonomic dysmotility)
        ('K59.81', PROXY,  False),  # Ogilvie syndrome (colonic pseudo-obstruction)
    ],

    'delayed_gastric_emptying': [
        # Add the full gastroparesis and upper GI dysmotility family
        ('K31.89', PROXY,  False),  # Other specified diseases of stomach/duodenum
        ('K31.0',  PROXY,  False),  # Acute dilatation of stomach
        ('K31.1',  PROXY,  False),  # Adult hypertrophic pyloric stenosis
        ('K30',    PROXY,  False),  # Functional dyspepsia
        ('R14.0',  PROXY,  False),  # Abdominal distension (gaseous)
        ('R11.0',  PROXY,  False),  # Nausea alone (symptom context)
        ('R11.10', PROXY,  False),  # Vomiting, unspecified
    ],

    'diarrhea': [
        # Add specific functional and organic diarrhea subtypes
        ('K52.89', PROXY,  False),  # Other specified noninfective gastroenteritis and colitis
        ('K52.9',  PROXY,  False),  # Noninfective gastroenteritis and colitis, unspecified
        ('K52.21', PROXY,  False),  # Food protein-induced proctocolitis
        ('K59.1',  DIRECT, True),   # Functional diarrhea (ensure present)
        ('R19.7',  DIRECT, True),   # Diarrhea, unspecified (ensure present)
        ('A09',    PROXY,  False),  # Infectious gastroenteritis/colitis, unspecified
    ],

    'dysarthria': [
        # Add dysarthria-specific codes not yet in atom
        ('R47.0',  DIRECT, True),   # Dysphasia and aphasia
        ('R47.89', DIRECT, True),   # Other speech disturbances
        ('R47.9',  PROXY,  False),  # Unspecified speech disturbances
        ('R48.2',  PROXY,  False),  # Apraxia
        ('R41.3',  PROXY,  False),  # Other amnesia (cognitive context)
    ],

    'dysphagia': [
        # R13 subtype codes — the core dysphagia taxonomy
        ('R13.0',  DIRECT, True),   # Aphagia
        ('R13.11', DIRECT, True),   # Dysphagia, oral phase
        ('R13.12', DIRECT, True),   # Dysphagia, oropharyngeal phase
        ('R13.13', DIRECT, True),   # Dysphagia, pharyngeal phase
        ('R13.14', DIRECT, True),   # Dysphagia, pharyngoesophageal phase
        ('K22.4',  PROXY,  False),  # Dyskinesia of esophagus
        ('K22.2',  PROXY,  False),  # Esophageal obstruction
        ('K20.90', PROXY,  False),  # Esophagitis, unspecified, without bleeding
        ('J69.0',  PROXY,  False),  # Aspiration pneumonitis (consequence of dysphagia)
        ('K22.70', PROXY,  False),  # Barrett's esophagus without dysplasia
    ],

    'early_satiety': [
        # Abdominal fullness and bloating codes
        ('R14.0',  DIRECT, True),   # Abdominal distension (gaseous) / fullness
        ('R10.4',  PROXY,  False),  # Epigastric pain (postprandial context)
        ('K30',    PROXY,  False),  # Functional dyspepsia
        ('K31.89', PROXY,  False),  # Other specified stomach/duodenum disease
        ('R11.0',  PROXY,  False),  # Nausea alone
    ],

    'eating_disorder_label': [
        # Complete F50 eating disorder family — all were missing
        ('F50.00', DIRECT, True),   # Anorexia nervosa, unspecified
        ('F50.01', DIRECT, True),   # Anorexia nervosa, restricting type
        ('F50.02', DIRECT, True),   # Anorexia nervosa, binge eating/purging type
        ('F50.2',  DIRECT, True),   # Bulimia nervosa
        ('F50.82', DIRECT, True),   # Avoidant/restrictive food intake disorder (ARFID)
        ('F50.89', DIRECT, True),   # Other specified eating disorder
        ('F50.9',  DIRECT, True),   # Eating disorder, unspecified
        ('R63.0',  PROXY,  False),  # Anorexia (symptom — loss of appetite)
        ('R63.3',  PROXY,  False),  # Feeding difficulties
    ],

    'hoarseness': [
        # Add voice-specific codes not yet in atom
        ('R49.1',  DIRECT, True),   # Aphonia
        ('R49.8',  PROXY,  False),  # Other voice and resonance disorders
        ('R49.9',  PROXY,  False),  # Unspecified voice and resonance disorder
        ('J38.00', PROXY,  False),  # Paralysis of vocal cords and larynx, unspecified
        ('J38.01', PROXY,  False),  # Paralysis of vocal cords, unilateral
        ('J38.02', PROXY,  False),  # Paralysis of vocal cords, bilateral
        ('J38.3',  PROXY,  False),  # Other diseases of vocal cords
        ('J37.0',  PROXY,  False),  # Chronic laryngitis
    ],

    'nausea': [
        # R11.0 (nausea alone) is the key missing code
        ('R11.0',  DIRECT, True),   # Nausea alone
        ('R11.10', PROXY,  False),  # Vomiting, unspecified
        ('R11.11', PROXY,  False),  # Vomiting without nausea
        ('R11.14', PROXY,  False),  # Bilious vomiting
        ('G43.A0', PROXY,  False),  # Cyclical vomiting, not intractable
    ],

    'vomiting': [
        # R11 subtypes — all missing; only R11.2 (nausea+vomiting together) was there
        ('R11.10', DIRECT, True),   # Vomiting, unspecified
        ('R11.11', DIRECT, True),   # Vomiting without nausea
        ('R11.12', DIRECT, True),   # Projectile vomiting
        ('R11.13', DIRECT, True),   # Vomiting of fecal matter
        ('R11.14', DIRECT, True),   # Bilious vomiting
        ('R11.0',  PROXY,  False),  # Nausea alone (context)
        ('G43.A0', PROXY,  False),  # Cyclical vomiting, not intractable
        ('G43.A1', PROXY,  False),  # Cyclical vomiting, intractable
        ('K92.0',  PROXY,  False),  # Hematemesis (vomiting blood)
    ],

    'v10_competing_gi': [
        # IBS family
        ('K58.0',  DIRECT, True),   # IBS with diarrhea
        ('K58.1',  DIRECT, True),   # IBS with constipation
        ('K58.2',  DIRECT, True),   # Mixed IBS
        ('K58.9',  DIRECT, True),   # IBS without diarrhea
        # Crohn's disease family
        ('K50.00', DIRECT, True),   # Crohn's disease of small intestine without complications
        ('K50.10', DIRECT, True),   # Crohn's disease of large intestine without complications
        ('K50.80', DIRECT, True),   # Other Crohn's disease without complications
        ('K50.90', DIRECT, True),   # Crohn's disease of small and large intestine, unspecified
        # Ulcerative colitis
        ('K51.00', DIRECT, True),   # Ulcerative pancolitis without complications
        ('K51.20', DIRECT, True),   # Ulcerative proctitis without complications
        ('K51.90', DIRECT, True),   # Ulcerative colitis, unspecified, without complications
        # Celiac disease
        ('K90.0',  DIRECT, True),   # Celiac disease
        # Diabetic GI autonomic neuropathy
        ('E11.43', DIRECT, True),   # Type 2 DM with diabetic autonomic (poly)neuropathy
        ('E11.49', PROXY,  False),  # Type 2 DM with other diabetic neurological complication
        ('E10.43', DIRECT, True),   # Type 1 DM with diabetic autonomic neuropathy
        ('E10.49', PROXY,  False),  # Type 1 DM with other diabetic neurological complication
        # Microscopic colitis
        ('K52.832', PROXY, False),  # Collagenous colitis
        ('K52.839', PROXY, False),  # Microscopic colitis, unspecified
        # Whipple's disease
        ('K90.81', PROXY,  False),  # Whipple's disease
        # Small bowel dysmotility / pseudo-obstruction
        ('K59.81', PROXY,  False),  # Ogilvie syndrome
        ('K59.89', PROXY,  False),  # Other specified functional intestinal disorders
    ],

    'abdominal_pain': [
        # Full R10 abdominal pain taxonomy — most subtypes missing
        ('R10.0',  PROXY,  False),  # Acute abdomen
        ('R10.11', DIRECT, True),   # Right upper quadrant pain
        ('R10.12', DIRECT, True),   # Left upper quadrant pain
        ('R10.2',  PROXY,  False),  # Pelvic and perineal pain
        ('R10.30', DIRECT, True),   # Lower abdominal pain, unspecified
        ('R10.31', DIRECT, True),   # Right lower quadrant pain
        ('R10.32', DIRECT, True),   # Left lower quadrant pain
        ('R10.33', DIRECT, True),   # Periumbilical pain
        ('R10.4',  DIRECT, True),   # Other and unspecified abdominal pain (epigastric)
        ('R10.81', PROXY,  False),  # Abdominal tenderness, unspecified
        ('R10.819', PROXY, False),  # Abdominal tenderness
        ('R10.821', PROXY, False),  # Right upper quadrant rebound tenderness
        ('R14.0',  PROXY,  False),  # Abdominal distension
        ('R19.00', PROXY,  False),  # Intra-abdominal/pelvic swelling, unspecified
    ],
}

# ── Load and apply ──────────────────────────────────────────────────────────
data = json.load(open('v5/config/shared/atoms/GASTROENTEROLOGY.json', encoding='utf-8'))
atom_lookup = {a['atom_id']: a for a in data['atoms']}

total_added = 0
total_filled = 0

for aid, entries_spec in ADDITIONS.items():
    atom = atom_lookup.get(aid)
    if not atom:
        print('WARNING: atom not found: ' + aid)
        continue
    entries = [make_entry(code, role, standalone) for (code, role, standalone) in entries_spec]
    n = add_codes(atom, entries)
    total_added += n
    print('  ' + aid.ljust(35) + '+' + str(n).rjust(3) + ' new codes')

# Backfill display_names on all pre-existing entries that didn't get one
for atom in data['atoms']:
    f = backfill_display_names(atom)
    total_filled += f

print()
print('Total new ICD entries added:   ' + str(total_added))
print('Total display_names backfilled: ' + str(total_filled))

with open('v5/config/shared/atoms/GASTROENTEROLOGY.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
print('Saved GASTROENTEROLOGY.json')

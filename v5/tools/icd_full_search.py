"""Full 2026 ICD-10-CM semantic search for all CARDIOLOGY, DERMATOLOGY, and DERMATOLOGY_ORAL atoms."""
import json, csv, sys

def add_dot(code):
    code = code.strip()
    if len(code) > 3 and '.' not in code:
        return code[:3] + '.' + code[3:]
    return code

# Load 2026 official ICD codes
icd2026 = {}
with open('not_for_snowflake/sql_codes/icd10cm-codes-2026.txt', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            icd2026[add_dot(parts[0])] = parts[1]

# Load warehouse
warehouse = {}
with open('not_for_snowflake/sql_root/icd_codes_with_meaning.csv', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        warehouse[row['DIAGNOSIS_CODE']] = int(row['PATIENT_COUNT'])

# Load all atom configs
atoms_by_id = {}
for fname in [
    'v5/config/shared/atoms/CARDIOLOGY.json',
    'v5/config/shared/atoms/DERMATOLOGY_ORAL.json',
    'v5/config/shared/atoms/DERMATOLOGY.json',
]:
    d = json.load(open(fname, encoding='utf-8'))
    for a in d['atoms']:
        atoms_by_id[a['atom_id']] = {'file': fname.split('/')[-1], 'data': a}

# Collect configured ICD10 codes per atom (with roles)
configured = {}
for aid, av in atoms_by_id.items():
    entries = {}
    for c in av['data'].get('extraction', {}).get('codes', {}).get('ICD10', []):
        entries[c['value']] = c.get('mapping_role', '?')
    configured[aid] = entries


def search(prefixes, keywords, top=80):
    results = {}
    kws = [k.lower() for k in keywords]
    for code, desc in icd2026.items():
        match_prefix = any(code.startswith(p) for p in prefixes)
        desc_l = desc.lower()
        match_kw = any(k in desc_l for k in kws)
        if match_prefix or match_kw:
            results[code] = (desc, warehouse.get(code, 0))
    return sorted(results.items(), key=lambda x: (-x[1][1], x[0]))[:top]


# Per-atom search strategies: (prefixes, keywords, no_icd_note_or_None)
strategies = {
    # ── CARDIOLOGY ──────────────────────────────────────────────────────────
    'af': (
        ['I48'],
        ['atrial fibril', 'atrial flutter'],
        None,
    ),
    'arrhythmia': (
        ['I44', 'I45', 'I47', 'I48', 'I49'],
        ['arrhythmia', 'tachycardia', 'fibrillation', 'flutter', 'bradycardia',
         'sick sinus', 'paroxysmal supraventricular', 'ventricular tachycardia',
         'supraventricular', 'ectopic'],
        None,
    ),
    'as_valve': (
        ['I35'],
        ['aortic stenosis', 'nonrheumatic aortic'],
        None,
    ),
    'asymmetric_septal_hypertrophy': (
        ['I42'],
        ['septal hypertrophy', 'hypertrophic cardiomyopathy', 'obstructive hypertrophic',
         'asymmetric hypertrophy'],
        None,
    ),
    'cardiomegaly': (
        ['I51'],
        ['cardiomegaly', 'enlarged heart'],
        None,
    ),
    'cardiomyopathy': (
        ['I42'],
        ['cardiomyopathy'],
        None,
    ),
    'conduction_disease': (
        ['I44', 'I45', 'I49'],
        ['block', 'bundle', 'fascicular', 'conduction', 'sick sinus',
         'pre-excitation', 'long qt', 'sinus node', 'bradycardia', 'heart block'],
        None,
    ),
    'declining_blood_pressure': (
        ['I95', 'R03'],
        ['hypotension', 'low blood pressure'],
        'Trajectory — no ICD for decline itself; hypotension codes are proxy',
    ),
    'dizziness': (
        ['R42', 'H81', 'H82'],
        ['dizziness', 'giddiness', 'vertigo', 'labyrinth', 'vestibular'],
        None,
    ),
    'dyspnea': (
        ['R06'],
        ['dyspnea', 'shortness of breath', 'breathless', 'orthopnea', 'tachypnea'],
        None,
    ),
    'hf_any': (
        ['I50'],
        ['heart failure'],
        None,
    ),
    'hfpef': (
        ['I50'],
        ['diastolic', 'preserved ejection'],
        None,
    ),
    'hf_medication_intolerance': (
        ['I95', 'T46'],
        ['hypotension', 'adverse effect antihypertensive', 'adverse effect diuretic',
         'adverse effect cardiac drug'],
        'No single ICD encodes medication intolerance directly; T46 adverse-effect codes are proxies',
    ),
    'hypertension': (
        ['I10', 'I11', 'I12', 'I13', 'I15', 'I16'],
        ['hypertension', 'hypertensive'],
        None,
    ),
    'hypertrophic_cardiomyopathy': (
        ['I42'],
        ['hypertrophic cardiomyopathy', 'obstructive hypertrophic', 'asymmetric hypertrophy'],
        None,
    ),
    'lflg_as': (
        ['I35'],
        ['aortic stenosis'],
        None,
    ),
    'low_ecg_voltage': (
        ['R94'],
        ['electrocardiogram', 'ecg', 'ekg', 'abnormal ecg'],
        'R94.31 is best available; no specific low-voltage ICD-10-CM code exists',
    ),
    'medication_dose_change': (
        [], [],
        'No ICD-10-CM code represents a medication dose change',
    ),
    'pacemaker_implantation': (
        ['Z95', 'Z45'],
        ['pacemaker', 'cardiac resynchronization', 'defibrillator', 'device implant', 'generator'],
        None,
    ),
    'pacemaker_presence': (
        ['Z95'],
        ['pacemaker', 'cardiac device', 'defibrillator', 'crt', 'icd presence'],
        None,
    ),
    'pericardial_effusion': (
        ['I31', 'I30'],
        ['pericardial effusion', 'hemopericardium', 'pericarditis', 'pericardial'],
        None,
    ),
    'pseudo_infarct': (
        ['R94'],
        ['electrocardiogram', 'ecg', 'ekg'],
        'No ICD-10-CM code encodes pseudo-infarct Q-wave pattern; R94.31 is best available proxy',
    ),
    'restrictive_cardiomyopathy': (
        ['I42'],
        ['restrictive cardiomyopathy', 'endomyocardial', 'endocardial fibroel'],
        None,
    ),
    'restrictive_filling': (
        ['I42', 'I50'],
        ['restrictive', 'diastolic dysfunction', 'diastolic heart failure'],
        'Echo filling pattern — no direct ICD-10-CM code; diastolic HF codes are proxies',
    ),
    'syncope': (
        ['R55', 'G90'],
        ['syncope', 'collapse', 'vasovagal', 'presyncope'],
        None,
    ),
    'tavr': (
        ['Z95', 'Z45'],
        ['prosthetic heart valve', 'aortic valve replacement', 'heart valve status', 'valve implant'],
        None,
    ),
    'thick_walls': (
        ['I42', 'I11'],
        ['hypertrophic', 'wall thickness', 'lvh', 'ventricular hypertrophy',
         'left ventricular hypertrophy'],
        'Wall thickness is an echo measurement; cardiomyopathy codes are proxies',
    ),
    'troponin_elevated': (
        ['R79'],
        ['troponin', 'abnormal blood chemistry', 'cardiac enzyme'],
        'Lab value — no specific ICD-10-CM code for troponin elevation',
    ),
    'ntprobnp_elevated': (
        ['R79'],
        ['natriuretic', 'bnp', 'abnormal blood chemistry'],
        'Lab value — no specific ICD-10-CM code for NT-proBNP elevation',
    ),
    # Measurement/imaging atoms — no ICD applicable
    'apical_sparing':          ([], [], 'Echo pattern — no ICD applicable'),
    'bnp_result':              ([], [], 'Lab value — no ICD applicable'),
    'bnp_lvmi_ratio_result':   ([], [], 'Derived lab/echo ratio — no ICD applicable'),
    'ntprobnp_result':         ([], [], 'Lab value — no ICD applicable'),
    'lv_cavity_geometry':      ([], [], 'Echo measurement — no ICD applicable'),
    'lv_mass_index_result':    ([], [], 'Echo measurement — no ICD applicable'),
    'lv_relative_wall_thickness': ([], [], 'Echo measurement — no ICD applicable'),
    'lv_wall_measurement':     ([], [], 'Echo measurement — no ICD applicable'),
    'lvef_result':             ([], [], 'Echo measurement — no ICD applicable'),
    'small_lv_cavity':         ([], [], 'Echo finding — no ICD applicable'),
    'reduced_gls':             ([], [], 'Echo measurement — no ICD applicable'),
    'reduced_mcf':             ([], [], 'Echo measurement — no ICD applicable'),
    'voltage_mass_mismatch':   ([], [], 'Combined echo+ECG finding — no ICD applicable'),
    # Competing-cause atoms
    'v24_competing_lvh': (
        ['I11', 'I42'],
        ['hypertensive heart', 'ventricular hypertrophy', 'hypertrophic cardiomyopathy', 'lvh'],
        None,
    ),
    'wt09_competing_hf_cause': (
        ['I10', 'I11', 'I25', 'I34', 'I35', 'I21', 'I22', 'I26', 'I13', 'I36', 'I37'],
        ['hypertension', 'ischemic heart', 'coronary artery', 'aortic stenosis',
         'mitral', 'pulmonary embolism', 'heart failure cause'],
        None,
    ),
    'wt11_competing_af_cause': (
        ['I10', 'I11', 'E05', 'G47', 'F10', 'I34', 'I35', 'I26'],
        ['hypertension', 'hyperthyroid', 'sleep apnea', 'alcohol', 'mitral',
         'aortic stenosis', 'pulmonary embolism'],
        None,
    ),
    'wt12_competing_conduction_cause': (
        ['A69', 'D86', 'M05', 'M06', 'I25', 'B27', 'G35'],
        ['lyme', 'sarcoid', 'rheumatoid', 'coronary', 'ischemic', 'myocarditis',
         'infiltrative', 'neurosarcoid'],
        None,
    ),
    'wt13_sarcomeric_hcm': (
        ['I42', 'Z84', 'Z82'],
        ['hypertrophic cardiomyopathy', 'obstructive hypertrophic',
         'family history heart', 'sarcomeric'],
        None,
    ),
    'wt18_competing_hypotension': (
        ['I95', 'A41', 'E86', 'D50', 'D64', 'R55', 'G90'],
        ['sepsis', 'dehydration', 'anemia', 'orthostatic', 'vasovagal', 'autonomic'],
        None,
    ),
    'al17_competing_biomarker': (
        ['I21', 'I22', 'A41', 'I26', 'I30', 'I31', 'I40', 'I51'],
        ['myocardial infarction', 'sepsis', 'pulmonary embolism',
         'myocarditis', 'pericarditis', 'acute coronary'],
        None,
    ),
    'al20_competing_dyspnea': (
        ['J45', 'J44', 'J18', 'J06', 'I26', 'J81', 'D50', 'D64', 'R06'],
        ['asthma', 'copd', 'pneumonia', 'pulmonary embolism',
         'pulmonary edema', 'anemia', 'dyspnea'],
        None,
    ),
    'al29_competing_hypotension': (
        ['I95', 'A41', 'E86', 'D50', 'D64', 'R55', 'G90'],
        ['sepsis', 'dehydration', 'anemia', 'orthostatic', 'hypotension cause', 'vasovagal'],
        None,
    ),
    'al33_competing_cardiomyopathy': (
        ['I42', 'I11', 'I25', 'I13'],
        ['cardiomyopathy', 'hypertensive heart', 'ischemic cardiomyopathy'],
        None,
    ),
    # ── DERMATOLOGY_ORAL ────────────────────────────────────────────────────
    'macroglossia': (
        ['Q38', 'K14'],
        ['macroglossia', 'tongue enlarg', 'hypertrophy of tongue', 'disease of tongue'],
        None,
    ),
    'periorbital_purpura': (
        ['D69', 'R23', 'S00', 'H02'],
        ['purpura', 'ecchymosis', 'periorbital', 'bruising', 'pinch', 'eyelid edema'],
        None,
    ),
    # ── DERMATOLOGY ─────────────────────────────────────────────────────────
    'al08_competing_purpura': (
        ['D69', 'Z79', 'D68', 'E54', 'K29'],
        ['purpura', 'thrombocytopenia', 'anticoagulant', 'steroid', 'ascorbic',
         'scurvy', 'coagulation', 'platelet', 'bleeding disorder'],
        None,
    ),
    'ecchymosis': (
        ['D69', 'R23'],
        ['ecchymosis', 'bruising', 'purpura', 'spontaneous bruising'],
        None,
    ),
}

# ── Output ───────────────────────────────────────────────────────────────────
writer = csv.writer(sys.stdout)
writer.writerow([
    'atom_id', 'file', 'code', 'description',
    'warehouse_patients', 'currently_configured_role', 'status',
])

for aid in sorted(atoms_by_id.keys()):
    av = atoms_by_id[aid]
    fname = av['file']
    strat = strategies.get(aid)
    if not strat:
        writer.writerow([aid, fname, '', 'No strategy defined', 0, '', 'SKIP'])
        continue

    prefixes, keywords, note = strat
    conf = configured.get(aid, {})

    if not prefixes and not keywords:
        if note:
            writer.writerow([aid, fname, '', note, 0, '', 'NO_ICD_APPLICABLE'])
        continue

    candidates = search(prefixes, keywords, top=80)
    for code, (desc, wh_pts) in candidates:
        role = conf.get(code, '')
        if role:
            status = 'ALREADY_CONFIGURED'
        elif wh_pts > 0:
            status = 'WAREHOUSE_CANDIDATE'
        else:
            status = 'OFFICIAL_ONLY'
        writer.writerow([aid, fname, code, desc, wh_pts, role, status])

    # Also note if no_icd note exists
    if note and candidates:
        writer.writerow([aid, fname, '', f'NOTE: {note}', 0, '', 'NOTE'])

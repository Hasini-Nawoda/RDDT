"""Apply full 2026 ICD-10-CM additions to CARDIOLOGY, DERMATOLOGY_ORAL, DERMATOLOGY atoms."""
import json, copy

def load(path):
    return json.load(open(path, encoding='utf-8'))

def save(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    print(f'Saved {path}')


def make_entry(value, role, standalone, review='WAREHOUSE_REVIEWED', note=None):
    e = {
        'value': value,
        'can_fire_atom_alone': standalone,
        'review_status': review,
        'mapping_role': role,
        'match_mode': 'EXACT',
    }
    if note:
        e['context_guard'] = note
    return e


def add_codes(atom, new_entries):
    """Add ICD10 codes to an atom if not already present."""
    icd = atom.setdefault('extraction', {}).setdefault('codes', {}).setdefault('ICD10', [])
    existing = {e['value'] for e in icd}
    added = 0
    for entry in new_entries:
        if entry['value'] not in existing:
            icd.append(entry)
            existing.add(entry['value'])
            added += 1
    return added


# ── per-atom additions ────────────────────────────────────────────────────────
# Format: atom_id -> [(code, role, standalone, note_or_None)]
DIRECT = 'DIRECT_TARGET'
PROXY  = 'PROXY_SUPPORT'
SUPP   = 'SUPPORTING'

ADDITIONS = {

    # ── CARDIOLOGY ────────────────────────────────────────────────────────────
    'arrhythmia': [
        ('R00.0',  DIRECT, True,  None),  # Tachycardia, unspecified
        ('R00.1',  PROXY,  False, None),  # Bradycardia, unspecified
        ('I49.1',  DIRECT, True,  None),  # Atrial premature depolarization
        ('I49.3',  DIRECT, True,  None),  # Ventricular premature depolarization
        ('I49.8',  DIRECT, True,  None),  # Other specified cardiac arrhythmias
        ('I49.9',  DIRECT, True,  None),  # Cardiac arrhythmia, unspecified
        ('I47.10', DIRECT, True,  None),  # Supraventricular tachycardia, unspecified
        ('I47.11', DIRECT, True,  None),  # Inappropriate sinus tachycardia
        ('I47.19', DIRECT, True,  None),  # Other supraventricular tachycardia
        ('I47.20', DIRECT, True,  None),  # Ventricular tachycardia, unspecified
        ('I47.29', DIRECT, True,  None),  # Other ventricular tachycardia
        ('G90.A',  PROXY,  False, None),  # POTS
        ('I49.01', PROXY,  False, None),  # Ventricular fibrillation
        ('I49.02', PROXY,  False, None),  # Ventricular flutter
    ],

    'as_valve': [
        ('I35.1', PROXY, False, None),  # Nonrheumatic aortic valve insufficiency
        ('I35.2', PROXY, False, None),  # Nonrheumatic aortic stenosis with insufficiency
        ('I35.8', PROXY, False, None),  # Other nonrheumatic aortic valve disorders
        ('I35.9', PROXY, False, None),  # Nonrheumatic aortic valve disorder, unspecified
    ],

    'asymmetric_septal_hypertrophy': [
        ('I42.1', DIRECT, True, None),  # Obstructive hypertrophic cardiomyopathy
    ],

    'cardiomegaly': [
        ('I51.89', PROXY, False, None),  # Other ill-defined heart diseases
        ('I51.9',  PROXY, False, None),  # Heart disease, unspecified
    ],

    'cardiomyopathy': [
        ('I25.5',  DIRECT, True,  None),  # Ischemic cardiomyopathy
        ('O90.3',  DIRECT, True,  None),  # Peripartum cardiomyopathy
        ('I43',    PROXY,  False, None),  # Cardiomyopathy in diseases classified elsewhere
        ('B33.24', DIRECT, True,  None),  # Viral cardiomyopathy
    ],

    'conduction_disease': [
        ('R00.1', PROXY,  False, None),  # Bradycardia, unspecified
        ('I49.1', PROXY,  False, None),  # Atrial premature depolarization
        ('I49.3', PROXY,  False, None),  # Ventricular premature depolarization
        ('I49.8', PROXY,  False, None),  # Other specified cardiac arrhythmias
        ('I49.9', PROXY,  False, None),  # Cardiac arrhythmia, unspecified
        ('Q24.6', DIRECT, True,  None),  # Congenital heart block
    ],

    'declining_blood_pressure': [
        ('I95.1',  DIRECT, True,  None),  # Orthostatic hypotension
        ('I95.89', PROXY,  False, None),  # Other hypotension
        ('I95.2',  PROXY,  False, None),  # Hypotension due to drugs
        ('I95.0',  PROXY,  False, None),  # Idiopathic hypotension
        ('I95.81', PROXY,  False, None),  # Postprocedural hypotension
        ('I95.3',  PROXY,  False, None),  # Hypotension of hemodialysis
        ('R03.1',  PROXY,  False, None),  # Nonspecific low blood-pressure reading
        ('I95.9',  PROXY,  False, None),  # Hypotension, unspecified
    ],

    'dizziness': [
        ('H81.10',  PROXY, False, None),  # BPPV, unspecified ear
        ('H81.11',  PROXY, False, None),  # BPPV, right ear
        ('H81.12',  PROXY, False, None),  # BPPV, left ear
        ('H81.13',  PROXY, False, None),  # BPPV, bilateral
        ('H81.4',   PROXY, False, None),  # Vertigo of central origin
        ('H81.399', PROXY, False, None),  # Other peripheral vertigo, unspecified ear
        ('H81.391', PROXY, False, None),  # Other peripheral vertigo, right ear
        ('H81.392', PROXY, False, None),  # Other peripheral vertigo, left ear
        ('H81.393', PROXY, False, None),  # Other peripheral vertigo, bilateral
        ('H81.90',  PROXY, False, None),  # Unspecified vestibular disorder, unspecified
        ('H81.93',  PROXY, False, None),  # Unspecified vestibular disorder, bilateral
        ('H83.2X3', PROXY, False, None),  # Labyrinthine dysfunction, bilateral
        ('H83.2X9', PROXY, False, None),  # Labyrinthine dysfunction, unspecified
        ('H81.01',  PROXY, False, None),  # Meniere's disease, right ear
        ('H81.09',  PROXY, False, None),  # Meniere's disease, unspecified
    ],

    'dyspnea': [
        ('R06.00', DIRECT, True,  None),  # Dyspnea, unspecified
        ('R06.02', DIRECT, True,  None),  # Shortness of breath
        ('R06.09', DIRECT, True,  None),  # Other forms of dyspnea
        ('R06.2',  PROXY,  False, None),  # Wheezing
        ('R06.03', PROXY,  False, None),  # Acute respiratory distress
        ('R06.89', PROXY,  False, None),  # Other abnormalities of breathing
        ('R06.82', PROXY,  False, None),  # Tachypnea, not elsewhere classified
        ('R06.81', PROXY,  False, None),  # Apnea, not elsewhere classified
        ('R06.9',  PROXY,  False, None),  # Unspecified abnormalities of breathing
    ],

    'hf_any': [
        ('I11.0',   DIRECT, True,  None),  # Hypertensive heart disease with heart failure
        ('I13.0',   DIRECT, True,  None),  # Hypertensive heart + CKD 1-4 with heart failure
        ('I13.2',   DIRECT, True,  None),  # Hypertensive heart + CKD stage 5 with heart failure
        ('I97.130', DIRECT, True,  None),  # Postprocedural heart failure following cardiac surgery
        ('I97.131', DIRECT, True,  None),  # Postprocedural heart failure following other surgery
        ('I09.81',  DIRECT, True,  None),  # Rheumatic heart failure
        ('I11.9',   PROXY,  False, None),  # Hypertensive heart disease without heart failure
        ('I13.10',  PROXY,  False, None),  # Hypertensive heart + CKD 1-4 without heart failure
        ('I13.11',  PROXY,  False, None),  # Hypertensive heart + CKD stage 5 without heart failure
    ],

    'hf_medication_intolerance': [
        ('I95.1',   PROXY, False, None),  # Orthostatic hypotension
        ('I95.89',  PROXY, False, None),  # Other hypotension
        ('I95.2',   PROXY, False, None),  # Hypotension due to drugs
        ('T46.4X5A', SUPP, False, None),  # Adverse effect of ACE inhibitors
        ('T46.5X5A', SUPP, False, None),  # Adverse effect of other antihypertensive drugs
        ('T46.2X5A', SUPP, False, None),  # Adverse effect of antidysrhythmic drugs
    ],

    'hypertension': [
        ('R03.0', PROXY,  False, None),  # Elevated BP reading without hypertension diagnosis
        ('I12.9', DIRECT, True,  None),  # Hypertensive CKD stage 1-4
        ('I12.0', DIRECT, True,  None),  # Hypertensive CKD stage 5
        ('I16.0', DIRECT, True,  None),  # Hypertensive urgency
        ('I16.1', DIRECT, True,  None),  # Hypertensive emergency
        ('I15.9', DIRECT, True,  None),  # Secondary hypertension, unspecified
        ('I15.1', DIRECT, True,  None),  # Hypertension secondary to renal disorders
        ('I15.8', DIRECT, True,  None),  # Other secondary hypertension
        ('I1A.0', DIRECT, True,  None),  # Resistant hypertension
        ('I13.0', DIRECT, True,  None),  # Hypertensive heart + CKD with heart failure
        ('I13.10', DIRECT, True, None),  # Hypertensive heart + CKD without heart failure
        ('I13.2', DIRECT, True,  None),  # Hypertensive heart + CKD stage 5 with heart failure
        ('I27.20', PROXY, False, None),  # Pulmonary hypertension, unspecified
        ('I27.21', PROXY, False, None),  # Secondary pulmonary arterial hypertension
    ],

    'hypertrophic_cardiomyopathy': [
        ('I42.0', PROXY,  False, None),  # Dilated cardiomyopathy (alternate)
        ('I42.8', PROXY,  False, None),  # Other cardiomyopathies
        ('I42.9', PROXY,  False, None),  # Cardiomyopathy, unspecified
    ],

    'lflg_as': [
        ('I35.1', PROXY,  False, None),  # Nonrheumatic aortic valve insufficiency
        ('I35.2', DIRECT, True,  None),  # Nonrheumatic aortic stenosis with insufficiency
        ('I35.8', PROXY,  False, None),  # Other nonrheumatic aortic valve disorders
        ('I35.9', PROXY,  False, None),  # Nonrheumatic aortic valve disorder, unspecified
        ('I06.0', PROXY,  False, None),  # Rheumatic aortic stenosis
        ('I06.2', PROXY,  False, None),  # Rheumatic aortic stenosis with insufficiency
        ('Q24.4', PROXY,  False, None),  # Congenital subaortic stenosis
    ],

    'ntprobnp_elevated': [
        ('R79.89', PROXY, False, None),  # Other specified abnormal findings of blood chemistry
        ('R79.9',  PROXY, False, None),  # Abnormal finding of blood chemistry, unspecified
    ],

    'pacemaker_implantation': [
        ('Z95.810', SUPP,   False, None),  # Presence of AICD
        ('Z95.818', SUPP,   False, None),  # Presence of other cardiac implants
        ('Z45.018', DIRECT, True,  None),  # Encounter for management of pacemaker part
        ('Z45.010', SUPP,   False, None),  # Encounter for checking pacemaker battery
        ('Z45.02',  DIRECT, True,  None),  # Encounter for management of AICD
        ('Z45.09',  SUPP,   False, None),  # Encounter for management of other cardiac device
        ('Z95.9',   PROXY,  False, None),  # Presence of cardiac device, unspecified
    ],

    'pacemaker_presence': [
        ('Z95.810', DIRECT, True,  None),  # Presence of AICD
        ('Z95.818', PROXY,  False, None),  # Other cardiac implants and grafts
        ('Z45.018', SUPP,   False, None),  # Pacemaker management encounter
        ('Z45.010', SUPP,   False, None),  # Pacemaker battery check encounter
        ('Z45.02',  SUPP,   False, None),  # AICD management encounter
        ('Z95.9',   PROXY,  False, None),  # Cardiac device, unspecified
    ],

    'pericardial_effusion': [
        ('I31.31', DIRECT, True,  None),  # Malignant pericardial effusion
        ('I31.4',  DIRECT, True,  None),  # Cardiac tamponade (implies effusion)
        ('I31.2',  DIRECT, True,  None),  # Hemopericardium
        ('I31.9',  PROXY,  False, None),  # Disease of pericardium, unspecified
        ('I30.9',  PROXY,  False, None),  # Acute pericarditis, unspecified
        ('I30.0',  PROXY,  False, None),  # Acute nonspecific idiopathic pericarditis
        ('I30.1',  PROXY,  False, None),  # Infective pericarditis
        ('I30.8',  PROXY,  False, None),  # Other forms of acute pericarditis
        ('I31.1',  PROXY,  False, None),  # Chronic constrictive pericarditis
        ('M32.12', PROXY,  False, None),  # Pericarditis in SLE
        ('B33.23', PROXY,  False, None),  # Viral pericarditis
        ('I32',    PROXY,  False, None),  # Pericarditis in diseases classified elsewhere
    ],

    'restrictive_cardiomyopathy': [
        ('I43', PROXY, False, None),  # Cardiomyopathy in diseases classified elsewhere
    ],

    'restrictive_filling': [
        ('I50.30', PROXY, False, None),  # Unspecified diastolic HF
        ('I50.31', PROXY, False, None),  # Acute diastolic HF
        ('I50.32', PROXY, False, None),  # Chronic diastolic HF
        ('I50.33', PROXY, False, None),  # Acute on chronic diastolic HF
        ('I42.5',  PROXY, False, None),  # Other restrictive cardiomyopathy
        ('I42.9',  PROXY, False, None),  # Cardiomyopathy, unspecified
    ],

    'syncope': [
        ('G90.01',   DIRECT, True,  None),  # Carotid sinus syncope
        ('T67.1XXA', DIRECT, True,  None),  # Heat syncope, initial encounter
        ('R05.4',    DIRECT, True,  None),  # Cough syncope
        ('G90.A',    PROXY,  False, None),  # POTS
        ('G90.3',    PROXY,  False, None),  # Multi-system degeneration of autonomic nervous system
    ],

    'tavr': [
        ('Z95.2',  SUPP,  False, None),  # Presence of prosthetic heart valve
        ('Z95.3',  SUPP,  False, None),  # Presence of xenogenic heart valve
        ('Z95.4',  SUPP,  False, None),  # Presence of other heart-valve replacement
        ('Z95.818', SUPP, False, None),  # Other cardiac implants
        ('Z45.09',  SUPP, False, None),  # Encounter for cardiac device management
    ],

    'thick_walls': [
        ('I11.0', PROXY, False, None),  # Hypertensive heart disease with HF
        ('I11.9', PROXY, False, None),  # Hypertensive heart disease without HF
        ('I13.0', PROXY, False, None),  # Hypertensive heart + CKD with HF
    ],

    'troponin_elevated': [
        ('R79.89', PROXY, False, None),  # Other specified abnormal findings of blood chemistry
        ('R79.9',  PROXY, False, None),  # Abnormal finding of blood chemistry, unspecified
    ],

    'v24_competing_lvh': [
        ('I11.0',  DIRECT, True,  None),  # Hypertensive heart disease with HF
        ('I11.9',  DIRECT, True,  None),  # Hypertensive heart disease without HF
        ('I13.0',  DIRECT, True,  None),  # Hypertensive heart + CKD with HF
        ('I13.10', PROXY,  False, None),  # Hypertensive heart + CKD without HF
        ('I13.2',  DIRECT, True,  None),  # Hypertensive heart + CKD stage 5 with HF
        ('I42.1',  DIRECT, True,  None),  # Obstructive hypertrophic cardiomyopathy
        ('I42.2',  DIRECT, True,  None),  # Other hypertrophic cardiomyopathy
        ('I42.0',  PROXY,  False, None),  # Dilated cardiomyopathy
        ('I42.8',  PROXY,  False, None),  # Other cardiomyopathies
        ('I42.9',  PROXY,  False, None),  # Cardiomyopathy, unspecified
    ],

    # Competing-cause atoms
    'wt09_competing_hf_cause': [
        ('I25.10',  DIRECT, True,  None),  # Atherosclerotic heart disease (no angina)
        ('I25.118', DIRECT, True,  None),  # Atherosclerotic heart disease with angina
        ('I25.119', DIRECT, True,  None),  # Atherosclerotic heart disease with unspecified angina
        ('I25.5',   DIRECT, True,  None),  # Ischemic cardiomyopathy
        ('I25.2',   DIRECT, True,  None),  # Old myocardial infarction
        ('I25.9',   PROXY,  False, None),  # Chronic ischemic heart disease, unspecified
        ('I13.0',   DIRECT, True,  None),  # Hypertensive heart + CKD with HF
        ('I13.2',   DIRECT, True,  None),  # Hypertensive heart + CKD stage 5 with HF
        ('I11.0',   DIRECT, True,  None),  # Hypertensive heart disease with HF
    ],

    'wt11_competing_af_cause': [
        ('I25.10',  DIRECT, True,  None),  # Ischemic heart disease
        ('I25.118', DIRECT, True,  None),  # Ischemic heart disease with angina
        ('I13.0',   DIRECT, True,  None),  # Hypertensive heart + CKD with HF
        ('E05.00',  DIRECT, True,  None),  # Thyrotoxicosis without mention of thyroid storm
        ('E05.10',  DIRECT, True,  None),  # Thyrotoxicosis with toxic single thyroid nodule
        ('E05.90',  DIRECT, True,  None),  # Thyrotoxicosis, unspecified without storm
        ('G47.33',  DIRECT, True,  None),  # Obstructive sleep apnea (adult)(pediatric)
        ('G47.30',  PROXY,  False, None),  # Sleep apnea, unspecified
        ('F10.20',  PROXY,  False, None),  # Alcohol use disorder, uncomplicated
        ('K70.30',  PROXY,  False, None),  # Alcoholic cirrhosis without ascites
    ],

    'wt12_competing_conduction_cause': [
        ('A69.20', DIRECT, True,  None),  # Lyme disease, unspecified
        ('A69.21', DIRECT, True,  None),  # Meningitis due to Lyme disease
        ('A69.23', DIRECT, True,  None),  # Arthritis due to Lyme disease
        ('D86.0',  DIRECT, True,  None),  # Sarcoidosis of lung
        ('D86.85', DIRECT, True,  None),  # Sarcoidosis of myocardium
        ('D86.9',  PROXY,  False, None),  # Sarcoidosis, unspecified
        ('I25.10', PROXY,  False, None),  # Ischemic heart disease
        ('I25.5',  PROXY,  False, None),  # Ischemic cardiomyopathy
    ],

    'wt13_sarcomeric_hcm': [
        ('I42.1',  DIRECT, True,  None),  # Obstructive hypertrophic cardiomyopathy
        ('I42.2',  DIRECT, True,  None),  # Other hypertrophic cardiomyopathy
        ('I42.9',  PROXY,  False, None),  # Cardiomyopathy, unspecified
        ('Z84.81', PROXY,  False, None),  # Family history of carrier of genetic disease
        ('Z82.49', PROXY,  False, None),  # Family history of ischemic/circulatory disease
    ],

    'wt18_competing_hypotension': [
        ('D50.9',   DIRECT, True,  None),  # Iron deficiency anemia, unspecified
        ('D50.8',   DIRECT, True,  None),  # Other iron deficiency anemia
        ('D50.0',   DIRECT, True,  None),  # Iron deficiency anemia secondary to blood loss
        ('D62',     DIRECT, True,  None),  # Acute posthemorrhagic anemia
        ('D53.9',   DIRECT, True,  None),  # Nutritional anemia, unspecified
        ('D63.8',   PROXY,  False, None),  # Anemia in other chronic diseases
        ('D64.89',  PROXY,  False, None),  # Other specified anemias
        ('E86.1',   DIRECT, True,  None),  # Hypovolemia
        ('I95.1',   DIRECT, True,  None),  # Orthostatic hypotension
        ('I95.89',  PROXY,  False, None),  # Other hypotension
        ('G90.A',   PROXY,  False, None),  # POTS
        ('E11.43',  PROXY,  False, None),  # Type 2 DM with diabetic autonomic neuropathy
    ],

    'al17_competing_biomarker': [
        ('I21.4',  DIRECT, True,  None),  # NSTEMI
        ('I21.3',  DIRECT, True,  None),  # STEMI unspecified site
        ('I21.02', DIRECT, True,  None),  # STEMI LAD
        ('I21.11', DIRECT, True,  None),  # STEMI inferior wall right coronary
        ('I21.A1', DIRECT, True,  None),  # Myocardial infarction type 2
        ('I25.2',  DIRECT, True,  None),  # Old myocardial infarction
        ('I26.09', DIRECT, True,  None),  # Other PE with acute cor pulmonale
        ('I26.93', PROXY,  False, None),  # Single subsegmental PE without cor pulmonale
        ('I26.94', PROXY,  False, None),  # Multiple subsegmental PE without cor pulmonale
        ('I27.82', PROXY,  False, None),  # Chronic pulmonary embolism
        ('I31.39', DIRECT, True,  None),  # Other pericardial effusion (noninflammatory)
        ('I30.9',  PROXY,  False, None),  # Acute pericarditis, unspecified
        ('I51.7',  PROXY,  False, None),  # Cardiomegaly
        ('I51.89', PROXY,  False, None),  # Other ill-defined heart diseases
        ('Z86.711', PROXY, False, None),  # Personal history of pulmonary embolism
    ],

    'al20_competing_dyspnea': [
        ('R06.02', DIRECT, True,  None),  # Shortness of breath
        ('R06.00', DIRECT, True,  None),  # Dyspnea, unspecified
        ('R06.09', DIRECT, True,  None),  # Other forms of dyspnea
        ('J45.20', DIRECT, True,  None),  # Mild intermittent asthma, uncomplicated
        ('J45.21', DIRECT, True,  None),  # Mild intermittent asthma with exacerbation
        ('J45.30', DIRECT, True,  None),  # Mild persistent asthma, uncomplicated
        ('J45.31', DIRECT, True,  None),  # Mild persistent asthma with exacerbation
        ('J45.40', DIRECT, True,  None),  # Moderate persistent asthma, uncomplicated
        ('J45.41', DIRECT, True,  None),  # Moderate persistent asthma with exacerbation
        ('J45.901', DIRECT, True, None),  # Unspecified asthma with exacerbation
        ('J44.1',  DIRECT, True,  None),  # COPD with acute exacerbation
        ('J44.0',  DIRECT, True,  None),  # COPD with acute lower respiratory infection
        ('J18.9',  DIRECT, True,  None),  # Pneumonia, unspecified organism
        ('J06.9',  PROXY,  False, None),  # Acute upper respiratory infection, unspecified
        ('D50.9',  PROXY,  False, None),  # Iron deficiency anemia
        ('R06.2',  PROXY,  False, None),  # Wheezing
        ('R06.89', PROXY,  False, None),  # Other abnormalities of breathing
    ],

    'al29_competing_hypotension': [
        ('D50.9',  DIRECT, True,  None),  # Iron deficiency anemia, unspecified
        ('D50.8',  DIRECT, True,  None),  # Other iron deficiency anemia
        ('D50.0',  DIRECT, True,  None),  # Iron deficiency anemia secondary to blood loss
        ('D62',    DIRECT, True,  None),  # Acute posthemorrhagic anemia
        ('D53.9',  DIRECT, True,  None),  # Nutritional anemia, unspecified
        ('D63.8',  PROXY,  False, None),  # Anemia in chronic diseases
        ('D64.89', PROXY,  False, None),  # Other specified anemias
        ('E86.1',  DIRECT, True,  None),  # Hypovolemia
        ('I95.1',  DIRECT, True,  None),  # Orthostatic hypotension
        ('I95.89', PROXY,  False, None),  # Other hypotension
        ('G90.A',  PROXY,  False, None),  # POTS
    ],

    'al33_competing_cardiomyopathy': [
        ('I25.10',  DIRECT, True,  None),  # Atherosclerotic heart disease (no angina)
        ('I25.118', DIRECT, True,  None),  # Atherosclerotic heart disease with other angina
        ('I25.119', DIRECT, True,  None),  # Atherosclerotic heart disease with unspecified angina
        ('I25.5',   DIRECT, True,  None),  # Ischemic cardiomyopathy
        ('I25.2',   DIRECT, True,  None),  # Old myocardial infarction
        ('I25.9',   PROXY,  False, None),  # Chronic ischemic heart disease, unspecified
        ('I13.0',   PROXY,  False, None),  # Hypertensive heart + CKD with HF
        ('I25.110', DIRECT, True,  None),  # Atherosclerotic heart disease with unstable angina
    ],

    # ── DERMATOLOGY_ORAL ───────────────────────────────────────────────────────
    'periorbital_purpura': [
        ('D69.3',  PROXY, False, None),  # ITP — purpura context
        ('D69.0',  PROXY, False, None),  # Allergic purpura — purpura context
        ('H02.843', PROXY, False, None), # Edema of right eye, unspecified eyelid
        ('H02.846', PROXY, False, None), # Edema of left eye, unspecified eyelid
        ('H02.844', PROXY, False, None), # Edema of left upper eyelid
        ('H02.841', PROXY, False, None), # Edema of right upper eyelid
    ],

    'macroglossia': [
        ('K14.8', PROXY, False, None),  # Other diseases of tongue
        ('K14.3', PROXY, False, None),  # Hypertrophy of tongue papillae
        ('K14.9', PROXY, False, None),  # Disease of tongue, unspecified
    ],

    # ── DERMATOLOGY ────────────────────────────────────────────────────────────
    'al08_competing_purpura': [
        ('D69.0',   DIRECT, True,  None),  # Allergic purpura
        ('D69.3',   DIRECT, True,  None),  # Immune thrombocytopenic purpura (already? check)
        ('D68.61',  DIRECT, True,  None),  # Antiphospholipid syndrome
        ('D68.00',  DIRECT, True,  None),  # Von Willebrand disease, unspecified
        ('D68.51',  DIRECT, True,  None),  # Activated protein C resistance
        ('D68.2',   DIRECT, True,  None),  # Hereditary deficiency of clotting factors
        ('D68.59',  PROXY,  False, None),  # Other primary thrombophilia
        ('D68.9',   PROXY,  False, None),  # Coagulation defect, unspecified
        ('D68.69',  PROXY,  False, None),  # Other thrombophilia
        ('R79.1',   PROXY,  False, None),  # Abnormal coagulation profile
    ],

    'ecchymosis': [
        ('D69.6',  PROXY, False, None),  # Thrombocytopenia, unspecified
        ('D69.3',  PROXY, False, None),  # Immune thrombocytopenic purpura
        ('D69.9',  PROXY, False, None),  # Hemorrhagic condition, unspecified
        ('D69.0',  PROXY, False, None),  # Allergic purpura
        ('D69.1',  PROXY, False, None),  # Qualitative platelet defects
        ('D69.59', PROXY, False, None),  # Other secondary thrombocytopenia
        ('D69.41', PROXY, False, None),  # Evans syndrome
        ('R23.8',  PROXY, False, None),  # Other skin changes
    ],
}


# ── Apply to files ──────────────────────────────────────────────────────────
cardiology    = load('v5/config/shared/atoms/CARDIOLOGY.json')
derm_oral     = load('v5/config/shared/atoms/DERMATOLOGY_ORAL.json')
dermatology   = load('v5/config/shared/atoms/DERMATOLOGY.json')

file_map = {
    'CARDIOLOGY.json': cardiology,
    'DERMATOLOGY_ORAL.json': derm_oral,
    'DERMATOLOGY.json': dermatology,
}

# Build atom lookup per file
atom_lookup = {}
for fkey, fdata in file_map.items():
    for atom in fdata['atoms']:
        atom_lookup[atom['atom_id']] = (fkey, atom)

total_added = 0
for atom_id, entries in ADDITIONS.items():
    if atom_id not in atom_lookup:
        print(f'WARNING: atom {atom_id} not found in any loaded file')
        continue
    fkey, atom = atom_lookup[atom_id]
    new_items = [make_entry(code, role, standalone, note=note)
                 for (code, role, standalone, note) in entries]
    n = add_codes(atom, new_items)
    total_added += n
    print(f'  {atom_id:40s} +{n:3d} codes  ({fkey})')

print(f'\nTotal new ICD entries added: {total_added}')

# Save
save('v5/config/shared/atoms/CARDIOLOGY.json', cardiology)
save('v5/config/shared/atoms/DERMATOLOGY_ORAL.json', derm_oral)
save('v5/config/shared/atoms/DERMATOLOGY.json', dermatology)

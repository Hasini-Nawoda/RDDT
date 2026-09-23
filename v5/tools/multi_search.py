"""Search 2026 ICD codes for MULTISPECIALTY atoms."""
import csv

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
            icd2026[add_dot(parts[0])] = parts[1]

warehouse = {}
with open('not_for_snowflake/sql_root/icd_codes_with_meaning.csv', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        warehouse[row['DIAGNOSIS_CODE']] = int(row['PATIENT_COUNT'])

strats = {
    'age_excessive_snhl': {
        'prefixes': ['H90','H91'],
        'keywords': ['sensorineural hearing','sudden idiopathic hearing','bilateral hearing loss'],
        'cfg': {'H90.3','H90.5','H91.8X3','H91.8X9'},
    },
    'autoimmune_disease': {
        'prefixes': ['M32','M33','M34','M35','M05','M06','M30','M31'],
        'keywords': ['systemic lupus','sjogren','rheumatoid arthritis','autoimmune','vasculitis',
                     'systemic sclerosis','polymyositis','dermatomyositis','polyarteritis'],
        'cfg': {'M35.9','R76.0'},
    },
    'axonal_neuropathy': {
        'prefixes': ['G60','G62','G63'],
        'keywords': ['polyneuropathy','peripheral neuropathy','axonal','idiopathic neuropathy'],
        'cfg': set(),
    },
    'diabetes': {
        'prefixes': ['E10','E11','E13'],
        'keywords': ['diabetes mellitus','diabetic neuropathy','diabetic polyneuropathy'],
        'cfg': {'E11.9','E11.42'},
    },
    'fhx_adult_onset_neuropathy': {
        'prefixes': ['Z82','Z84'],
        'keywords': ['family history of.*nervous','family history.*neuropathy','hereditary neuropathy'],
        'cfg': {'Z82.0'},
    },
    'fhx_established_attr': {
        'prefixes': ['Z83','Z84','Z15','Z14','E85'],
        'keywords': ['family history.*amyloid','genetic susceptibility','carrier.*genetic',
                     'heredofamilial amyloid','transthyretin'],
        'cfg': {'Z83.49','Z15.89','Z14.8'},
    },
    'idiopathic_progressive_neuropathy': {
        'prefixes': ['G60','G62'],
        'keywords': ['idiopathic.*neuropathy','progressive neuropathy','cryptogenic neuropathy',
                     'hereditary and idiopathic neuropathy'],
        'cfg': set(),
    },
    'ligamentum_flavum_thickening': {
        'prefixes': ['M48','M47','G56'],
        'keywords': ['spinal stenosis','ligamentum','carpal tunnel','lumbar stenosis',
                     'cervical stenosis','spondylosis'],
        'cfg': set(),
    },
    'myocardial_bone_tracer_uptake': {
        'prefixes': ['R93','E85'],
        'keywords': ['incidental.*cardiac','myocardial.*uptake','bone scan','amyloidosis',
                     'abnormal.*imaging.*heart'],
        'cfg': set(),
    },
    'orthopedic_to_cardiac_trajectory': {
        'prefixes': ['G56','M48','M66','M65','M75'],
        'keywords': ['carpal tunnel','spinal stenosis','biceps rupture','trigger finger',
                     'rotator cuff','tendon rupture'],
        'cfg': set(),
    },
    'ttr_pathogenic_variant': {
        'prefixes': ['Z15','Z14','E85'],
        'keywords': ['genetic susceptibility','carrier','heredofamilial amyloid',
                     'transthyretin','pathogenic variant'],
        'cfg': set(),
    },
    'wt21_competing_hearing_loss': {
        'prefixes': ['H83','H90','H91','H81','H93'],
        'keywords': ['presbycusis','noise induced hearing','ototoxic','meniere','hearing loss'],
        'cfg': {'H91.10','H91.13','H83.3X3','H83.3X9','H91.03','H91.09','H81.03','H81.09'},
    },
    'unintentional_weight_loss': {
        'prefixes': ['R63','R64','E41','E43','E46'],
        'keywords': ['weight loss','cachexia','underweight','malnutrition','wasting','anorexia'],
        'cfg': {'R63.4','R64','F50.00','F50.010','F50.011','F50.012','F50.013','F50.014',
                'F50.019','F50.020','F50.021','F50.022','F50.023','F50.024','F50.029','K31.84'},
    },
}

for aid, strat in strats.items():
    cfg = strat['cfg']
    results = {}
    kws = [k.lower() for k in strat['keywords']]
    for code, desc in icd2026.items():
        if any(code.startswith(p) for p in strat['prefixes']) or any(k in desc.lower() for k in kws):
            results[code] = (desc, warehouse.get(code, 0))
    cands = sorted(results.items(), key=lambda x: (-x[1][1], x[0]))[:25]
    print('=== ' + aid + ' ===')
    for code, (desc, wh) in cands:
        tag = 'CFG' if code in cfg else ('WH' if wh > 0 else 'OFF')
        print('  ' + tag.ljust(5) + code.ljust(12) + str(wh).rjust(8) + '  ' + desc)
    print()

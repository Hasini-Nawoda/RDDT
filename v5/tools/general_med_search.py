"""Search 2026 ICD codes for all GENERAL_MEDICINE atoms."""
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

strategies = {
    'declining_bmi': {
        'prefixes': ['R63','R64','E40','E41','E42','E43','E44','E45','E46','Z68'],
        'keywords': ['weight loss','underweight','malnutrition','cachexia','bmi','wasting','marasmus'],
    },
    'al34_competing_edema': {
        'prefixes': ['I50','I83','I87','I89','K70','K74','K76','N04','N18','R60','T46'],
        'keywords': ['edema','oedema','heart failure','venous insufficiency','lymphedema',
                     'cirrhosis','nephrotic','varicose','hypoalbuminemia','anasarca','calcium channel'],
    },
    'fatigue': {
        'prefixes': ['R53','G93'],
        'keywords': ['fatigue','malaise','lethargy','asthenia','tiredness','exhaustion','postviral'],
    },
    'malaise': {
        'prefixes': ['R53','R68'],
        'keywords': ['malaise','fatigue','unwell','weakness','asthenia'],
    },
    'other_serosal_effusion': {
        'prefixes': ['R18','K65','K66','K76','C78'],
        'keywords': ['ascites','peritoneal effusion','serosal','paracentesis','peritonitis'],
    },
    'subjective_weakness': {
        'prefixes': ['R53','M62','G70','G72'],
        'keywords': ['weakness','muscle weakness','myopathy','asthenia','debility'],
    },
}

for aid, strat in strategies.items():
    configured = {
        'al34_competing_edema': {'I50.9','I87.2','I89.0','K70.30','K74.60','N18.9'},
        'fatigue': {'R53.81','R53.82','R53.83'},
        'malaise': {'R53.8','R53.81'},
        'other_serosal_effusion': {'K66.8','R18.8'},
        'subjective_weakness': {'R53.1'},
        'declining_bmi': set(),
    }.get(aid, set())

    results = {}
    kws = [k.lower() for k in strat['keywords']]
    for code, desc in icd2026.items():
        if any(code.startswith(p) for p in strat['prefixes']) or any(k in desc.lower() for k in kws):
            results[code] = (desc, warehouse.get(code, 0))

    cands = sorted(results.items(), key=lambda x: (-x[1][1], x[0]))[:30]
    print('=== ' + aid + ' ===')
    for code, (desc, wh) in cands:
        tag = 'CFG' if code in configured else ('WH' if wh > 0 else 'OFF')
        print('  ' + tag.ljust(5) + code.ljust(12) + str(wh).rjust(8) + '  ' + desc)
    print()

"""Search 2026 ICD codes for NEPHROLOGY atoms."""
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
    'abnormal_serum_free_light_chain_ratio': {
        'prefixes': ['D47','R77','R70'],
        'keywords': ['free light chain','monoclonal','gammopathy','paraprotein','immunofixation'],
        'cfg': set(),
    },
    'egfr_result': {
        'prefixes': ['N18'],
        'keywords': ['chronic kidney disease','ckd stage','glomerular filtration'],
        'cfg': {'N18.3','N18.4','N18.5','N18.9'},
    },
    'hypoalbuminemia': {
        'prefixes': ['E88','R77'],
        'keywords': ['hypoalbuminemia','low albumin','albumin deficiency'],
        'cfg': {'E88.09','E88.0','R77.8'},
    },
    'microalbuminuria': {
        'prefixes': ['R80','N39'],
        'keywords': ['albuminuria','microalbuminuria','proteinuria'],
        'cfg': {'R80.9'},
    },
    'nephrotic_range_proteinuria': {
        'prefixes': ['R80','N04','N05','N06'],
        'keywords': ['nephrotic','heavy proteinuria','proteinuria'],
        'cfg': set(),
    },
    'serum_immunofixation_monoclonal': {
        'prefixes': ['D47','R70','R77'],
        'keywords': ['monoclonal','immunofixation','m-protein','paraprotein','serum protein'],
        'cfg': set(),
    },
    'urine_protein_result': {
        'prefixes': ['R80','R82'],
        'keywords': ['proteinuria','urine protein','protein creatinine'],
        'cfg': set(),
    },
    'al03_competing_proteinuria': {
        'prefixes': ['N04','N05','N06','N07','N08','I12','I13','E10','E11'],
        'keywords': ['diabetic nephropathy','hypertensive nephropathy','glomerulonephritis',
                     'glomerular disease','iga nephropathy','fsgs','membranous'],
        'cfg': {'E10.21','E11.21','I12.9','I13.10','N04.1','N04.2','N05.2','N18.9'},
    },
    'al04_competing_nephrotic': {
        'prefixes': ['N04','N05','E85','N08'],
        'keywords': ['nephrotic syndrome','minimal change','membranous','fsgs',
                     'diabetic nephropathy','amyloid kidney'],
        'cfg': {'E10.21','E11.21','E85.3','N04.0','N04.1','N04.2'},
    },
    'al05_competing_hypoalbuminemia': {
        'prefixes': ['K70','K74','K76','N04','I50','I87','E43','E46'],
        'keywords': ['cirrhosis','heart failure','hypoalbuminemia','protein losing',
                     'malnutrition','venous insufficiency','lymphedema'],
        'cfg': {'E43','E46','I50.9','I87.2','K70.30','K74.60','K76.9','N18.9'},
    },
    'falling_egfr': {
        'prefixes': ['N17','N18'],
        'keywords': ['acute kidney injury','aki','chronic kidney disease','renal failure'],
        'cfg': {'N17.9','N18.3','N18.4','N18.5'},
    },
    'kidney_failure': {
        'prefixes': ['N17','N18','N19','Z99'],
        'keywords': ['kidney failure','renal failure','end stage renal','dialysis dependent','esrd'],
        'cfg': {'N18.5','N18.6','N19','Z99.2'},
    },
    'nephrotic_syndrome': {
        'prefixes': ['N04'],
        'keywords': ['nephrotic syndrome','nephrosis'],
        'cfg': {'N04.8','N04.9'},
    },
    'peripheral_edema': {
        'prefixes': ['R60'],
        'keywords': ['edema','oedema','anasarca','peripheral edema','swelling'],
        'cfg': {'R60.0','R60.1','R60.9'},
    },
    'persistent_proteinuria': {
        'prefixes': ['R80'],
        'keywords': ['proteinuria','albuminuria'],
        'cfg': {'R80.0','R80.1','R80.8','R80.9'},
    },
    'progressive_proteinuria': {
        'prefixes': ['R80'],
        'keywords': ['proteinuria','albuminuria'],
        'cfg': {'R80.1','R80.9'},
    },
    'renal_dysfunction': {
        'prefixes': ['N18','N25'],
        'keywords': ['chronic kidney disease','renal insufficiency','renal dysfunction'],
        'cfg': {'N18.3','N18.4','N18.9','N19'},
    },
}

for aid, strat in strats.items():
    cfg = strat['cfg']
    results = {}
    kws = [k.lower() for k in strat['keywords']]
    for code, desc in icd2026.items():
        if any(code.startswith(p) for p in strat['prefixes']) or any(k in desc.lower() for k in kws):
            results[code] = (desc, warehouse.get(code, 0))
    cands = sorted(results.items(), key=lambda x: (-x[1][1], x[0]))[:20]
    print('=== ' + aid + ' ===')
    for code, (desc, wh) in cands:
        tag = 'CFG' if code in cfg else ('WH' if wh > 0 else 'OFF')
        print('  ' + tag.ljust(5) + code.ljust(12) + str(wh).rjust(8) + '  ' + desc)
    print()

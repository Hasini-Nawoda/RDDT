"""Search 2026 ICD codes for HEPATOLOGY atoms."""
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
    'al18_congestive_hepatopathy': {
        'prefixes': ['K70','K71','K72','K73','K74','K75','K76','K77','C78','I50','I31'],
        'keywords': ['hepatopathy','liver disease','hepatic','cirrhosis','fatty liver','steatosis',
                     'congestion','hepatitis','cholestasis','fibrosis','nafld','nash','cholangitis',
                     'hepatomegaly','congestive hepat'],
    },
    'hepatic_alp_elevation': {
        'prefixes': ['R74','R94','K71','K74','K75','K80','K83','K86'],
        'keywords': ['alkaline phosphatase','alp elevated','transaminase','liver enzyme',
                     'cholestasis','cholestatic','biliary','bile duct','primary biliary',
                     'hepatocellular','abnormal liver','jaundice','bilirubin'],
    },
    'hepatomegaly': {
        'prefixes': ['R16','K76','Q44'],
        'keywords': ['hepatomegaly','hepatosplenomegaly','enlarged liver','liver enlargement',
                     'liver mass','liver lesion','hepatic mass'],
    },
}

configured = {
    'al18_congestive_hepatopathy': {'C78.7','K70.30','K74.3','K74.60','K75.81','K76.0','K76.1','K76.9'},
    'hepatic_alp_elevation': {'R74.0','R94.5'},
    'hepatomegaly': {'R16.0','R16.2'},
}

for aid, strat in strats.items():
    cfg = configured[aid]
    results = {}
    kws = [k.lower() for k in strat['keywords']]
    for code, desc in icd2026.items():
        if any(code.startswith(p) for p in strat['prefixes']) or any(k in desc.lower() for k in kws):
            results[code] = (desc, warehouse.get(code, 0))

    cands = sorted(results.items(), key=lambda x: (-x[1][1], x[0]))[:40]
    print('=== ' + aid + ' ===')
    for code, (desc, wh) in cands:
        tag = 'CFG' if code in cfg else ('WH' if wh > 0 else 'OFF')
        print('  ' + tag.ljust(5) + code.ljust(12) + str(wh).rjust(8) + '  ' + desc)
    print()

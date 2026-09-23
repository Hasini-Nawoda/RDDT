"""Search 2026 ICD codes for fhx_sudden_death atom in GENETICS.json."""
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

prefixes = ['Z82','Z83','Z84','E85','G60','I49']
keywords = [
    'family history','sudden death','sudden cardiac','hereditary','amyloid',
    'neuropathy','transthyretin','ttr','familial','heredofamilial',
    'cardiac arrest','ventricular fibrillation','unexplained death',
]

results = {}
for code, desc in icd2026.items():
    dl = desc.lower()
    if any(code.startswith(p) for p in prefixes) or any(k in dl for k in keywords):
        results[code] = (desc, warehouse.get(code, 0))

for code, (desc, wh) in sorted(results.items(), key=lambda x: (-x[1][1], x[0])):
    tag = 'WH' if wh > 0 else 'OFF'
    print(tag.ljust(5) + code.ljust(14) + str(wh).rjust(7) + '  ' + desc)

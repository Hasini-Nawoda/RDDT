"""Search 2026 ICD codes for HEMATOLOGY atoms."""
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
    'mgus': {
        'prefixes': ['D47','C88','R77'],
        'keywords': ['monoclonal','gammopathy','mgus','m-protein','m-spike','paraprotein',
                     'plasma cell','plasmacytoma','immunoproliferative'],
    },
    'plasma_cell_dyscrasia': {
        'prefixes': ['C90','C88','D47','E85'],
        'keywords': ['multiple myeloma','myeloma','plasma cell','plasmacytoma','amyloidosis',
                     'waldenstrom','immunoproliferative','smoldering'],
    },
    'myeloma_therapy_exposure': {
        'prefixes': ['Z51','Z79','Z92','Z85'],
        'keywords': ['antineoplastic','chemotherapy','immunotherapy','stem cell transplant',
                     'bone marrow transplant','transplant','melphalan','lenalidomide',
                     'bortezomib','daratumumab','carfilzomib','thalidomide'],
    },
}

configured = {
    'mgus': set(),
    'plasma_cell_dyscrasia': {'C90.00','C90.01','C90.10','C90.30','C90.20','E85.81'},
    'myeloma_therapy_exposure': {'Z51.1','Z51.11','Z92.21'},
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

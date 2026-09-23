"""Search 2026 ICD codes for ORTHOPEDICS_MSK atoms."""
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

groups = {
    'arthroplasty':  (['Z96.6'],   ['hip prosthesis','knee prosthesis','joint replacement implant']),
    'biceps':        (['M66.8','M75.1'],['biceps tendon rupture','biceps rupture']),
    'cts':           (['G56.0','G56.1'],['carpal tunnel','median nerve']),
    'lumbar_sten':   (['M48','M47.8','M47.2','M51.1'],['lumbar stenosis','spinal stenosis lumbar','spondylosis radiculopathy']),
    'persist_limb':  (['M54.4','M54.5','G57.9'],['lumbago sciatica','radiculopathy','lower limb symptoms','failed back']),
    'rotator_cuff':  (['M75.1','M66.2'],['rotator cuff','shoulder tear','supraspinatus']),
    'shoulder':      (['M75'],          ['shoulder disorder','frozen shoulder','adhesive capsulitis','shoulder impingement']),
    'spontaneous':   (['M66.2','M66.3','M66.8'],['spontaneous rupture tendon','atraumatic rupture']),
    'trigger_fin':   (['M65.3'],        ['trigger finger','trigger thumb','stenosing tenosynovitis']),
}

for gname, (prefixes, kws) in groups.items():
    results = {}
    lkws = [k.lower() for k in kws]
    for code, desc in icd2026.items():
        if any(code.startswith(p) for p in prefixes) or any(k in desc.lower() for k in lkws):
            results[code] = (desc, warehouse.get(code, 0))
    cands = sorted(results.items(), key=lambda x: (-x[1][1], x[0]))[:14]
    print('=== ' + gname + ' ===')
    for code, (desc, wh) in cands:
        print('  ' + code.ljust(12) + str(wh).rjust(8) + '  ' + desc)
    print()

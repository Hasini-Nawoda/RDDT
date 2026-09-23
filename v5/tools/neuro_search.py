"""Search 2026 ICD codes for NEUROLOGY atoms."""
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
    'anhidrosis':          (['L74','R61','G90'],  ['anhidrosis','hypohidrosis','absent sweat']),
    'axonal_pattern_emg':  (['R94','G62','G60'],  ['electromyogram','electromyography','nerve conduction','axonal neuropathy']),
    'bulbar_symptoms':     (['R13','R47','R49','G12'],  ['dysphagia','dysphonia','bulbar','slurred speech','dysarthria']),
    'burning_feet':        (['R20','G57','G63'],  ['burning','paraesthesia','neuropathic pain','sensory neuropathy']),
    'cidp':                (['G61'],              ['inflammatory polyneuropathy','cidp','demyelinating','chronic inflammatory']),
    'demyelinating_emg':   (['G61','G60','R94'],  ['demyelinating','inflammatory polyneuropathy','nerve conduction']),
    'dysautonomia':        (['G90','I95','R55'],  ['autonomic','dysautonomia','orthostatic','syncope','postural hypotension']),
    'erectile_dysfunction':(['N52','F52'],        ['erectile dysfunction','impotence']),
    'gastroparesis':       (['K31','R11'],        ['gastroparesis','gastric emptying','vomiting','nausea']),
    'gi_dysmotility':      (['K59','K31','R19'],  ['dysmotility','constipation','diarrhea','bowel','intestinal motility']),
    'immunotherapy':       (['G61','Z79','Z51'],  ['immunotherapy','plasmapheresis','ivig','intravenous immunoglobulin']),
    'mibg':                (['R93'],              ['cardiac imaging','nuclear medicine','heart scan','myocardial']),
    'mild_sensory_poly':   (['G62','G60','G63'],  ['polyneuropathy','sensory neuropathy','peripheral neuropathy']),
    'neurogenic_bladder':  (['N31','R33','R35'],  ['neurogenic bladder','neuropathic bladder','bladder dysfunction']),
    'orthostatic':         (['I95','G90','R55'],  ['orthostatic hypotension','postural hypotension','syncope','hypotension']),
    'pain_temp_loss':      (['R20','G54'],        ['anaesthesia','hypoaesthesia','sensory loss','temperature loss']),
    'polyneuropathy':      (['G62','G60','G63'],  ['polyneuropathy','peripheral neuropathy','neuropathy']),
    'positive_autoab':     (['R76'],              ['antibody','immunological','autoantibody','raised antibody']),
    'sfn':                 (['G60','G62','R20'],  ['small fiber','small-fiber neuropathy']),
    'trophic_change':      (['L98','L97','L85'],  ['trophic','skin change','neuropathic skin','xerosis','atrophy skin']),
    'urinary_incontinence':(['N39','R32'],        ['urinary incontinence','incontinence']),
    'urinary_retention':   (['N31','R33'],        ['urinary retention','retention of urine','neurogenic bladder']),
    'v02_competing':       (['E11','E10','G61','G62','B02'], ['diabetic neuropathy','drug neuropathy','cidp','competing neuropathy']),
    'v04_competing':       (['G60','G61','G62','E11'], ['hereditary neuropathy','cidp','drug neuropathy','diabetic neuropathy']),
    'v05_competing_dysauto':(['G90','E11'],       ['multiple system atrophy','autonomic neuropathy','dysautonomia','diabetic autonomic']),
    'sensory_loss':        (['R20','G62','G54'],  ['sensory loss','anaesthesia','hypoaesthesia','disturbances of skin sensation']),
}

for gname, (prefixes, kws) in groups.items():
    results = {}
    lkws = [k.lower() for k in kws]
    for code, desc in icd2026.items():
        if any(code.startswith(p) for p in prefixes) or any(k in desc.lower() for k in lkws):
            results[code] = (desc, warehouse.get(code, 0))
    cands = sorted(results.items(), key=lambda x: (-x[1][1], x[0]))[:15]
    print('=== ' + gname + ' ===')
    for code, (desc, wh) in cands:
        print('  ' + code.ljust(12) + str(wh).rjust(8) + '  ' + desc)
    print()

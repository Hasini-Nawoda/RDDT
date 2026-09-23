"""Full 2026 ICD-10-CM search for al07_competing_macroglossia (ENT.json)."""
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
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            icd2026[add_dot(parts[0])] = parts[1]

warehouse = {}
with open('not_for_snowflake/sql_root/icd_codes_with_meaning.csv', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        warehouse[row['DIAGNOSIS_CODE']] = int(row['PATIENT_COUNT'])

# Currently configured ICD10 codes
configured = {'E03.9', 'E22.0', 'Q90.9', 'T78.3XXA'}

# Prefixes covering all plausible competing causes of macroglossia
prefixes = [
    'E00', 'E01', 'E02', 'E03',  # thyroid / hypothyroidism
    'E04',                         # other thyroid disorders
    'E22',                         # acromegaly / pituitary
    'Q90',                         # Down syndrome
    'Q87',                         # congenital malformation syndromes (Beckwith-Wiedemann)
    'Q38',                         # macroglossia (tongue malformations)
    'T78',                         # angioedema / allergic reactions
    'T46',                         # drug adverse effects (ACE inhibitors)
    'D18',                         # hemangioma / lymphangioma
    'D84',                         # hereditary angioedema (C1-esterase inhibitor deficiency)
    'E74',                         # glycogen storage disease (Pompe)
    'E76',                         # mucopolysaccharidosis
    'J39',                         # upper airway / tongue disorders
    'K14',                         # tongue disorders
]

# Semantic keywords
keywords = [
    'macroglossia',
    'angioedema',
    'hypothyroid',
    'acromegaly',
    'down syndrome',
    'mucopolysaccharidosis',
    'glycogen storage',
    'lymphangioma',
    'hemangioma',
    'tongue enlarg',
    'beckwith',
    'myxedema',
    'cretinism',
    'pompe',
    'iodine deficiency',
    'gigantism',
    'c1 esterase',
    'hereditary angioedema',
    'hurler',
    'hunter syndrome',
]

results = {}
for code, desc in icd2026.items():
    match_prefix = any(code.startswith(p) for p in prefixes)
    desc_l = desc.lower()
    match_kw = any(k in desc_l for k in keywords)
    if match_prefix or match_kw:
        results[code] = (desc, warehouse.get(code, 0))

print('STATUS     CODE           WH_PTS  DESCRIPTION')
print('-' * 80)
for code, (desc, wh) in sorted(results.items(), key=lambda x: (-x[1][1], x[0])):
    if code in configured:
        tag = 'CONFIGURED'
    elif wh > 0:
        tag = 'WH_CAND'
    else:
        tag = 'OFFICIAL'
    print(tag.ljust(11) + code.ljust(14) + str(wh).rjust(7) + '  ' + desc)

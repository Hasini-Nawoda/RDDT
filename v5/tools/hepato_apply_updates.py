"""Full 2026 ICD-10-CM pass for HEPATOLOGY.json — add codes + display_names."""
import json

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
            dotted = add_dot(parts[0])
            icd2026[dotted] = parts[1]
            icd2026[parts[0].strip()] = parts[1]

def lookup(code):
    return icd2026.get(code) or icd2026.get(code.replace('.', ''))

def make_entry(value, role, standalone):
    desc = lookup(value)
    return {
        'value': value,
        'can_fire_atom_alone': standalone,
        'review_status': 'WAREHOUSE_REVIEWED',
        'mapping_role': role,
        'match_mode': 'EXACT',
        'display_name': desc if desc else value + ' [no 2026 description]',
    }

def add_codes(atom, new_entries):
    icd = atom.setdefault('extraction', {}).setdefault('codes', {}).setdefault('ICD10', [])
    existing = {e['value'] for e in icd}
    added = 0
    for entry in new_entries:
        if entry['value'] not in existing:
            icd.append(entry)
            existing.add(entry['value'])
            added += 1
    return added

def backfill(atom):
    filled = 0
    for entry in atom.get('extraction', {}).get('codes', {}).get('ICD10', []):
        if 'display_name' not in entry:
            desc = lookup(entry['value'])
            entry['display_name'] = desc if desc else entry['value'] + ' [no 2026 description]'
            filled += 1
    return filled

DIRECT = 'DIRECT_TARGET'
PROXY  = 'PROXY_SUPPORT'

ADDITIONS = {

    # ── al18_congestive_hepatopathy ───────────────────────────────────────
    # Existing: C78.7, K70.30, K74.3, K74.60, K75.81, K76.0, K76.1, K76.9
    'al18_congestive_hepatopathy': [
        # Cirrhosis variants (K74.60 present, K74.69 missing — huge WH gap)
        ('K74.69', DIRECT, True),   # Other cirrhosis of liver (2,045 WH pts)
        ('K74.00', DIRECT, True),   # Hepatic fibrosis, unspecified (719 pts)
        ('K74.02', DIRECT, True),   # Hepatic fibrosis, advanced fibrosis (251 pts)
        ('K74.01', DIRECT, True),   # Hepatic fibrosis, early fibrosis
        # Alcoholic liver disease variants
        ('K70.31', DIRECT, True),   # Alcoholic cirrhosis with ascites (1,919 pts)
        ('K70.10', DIRECT, True),   # Alcoholic hepatitis without ascites (131 pts)
        ('K70.11', DIRECT, True),   # Alcoholic hepatitis with ascites (119 pts)
        ('K70.40', DIRECT, True),   # Alcoholic hepatic failure without coma
        # Hepatic failure
        ('K72.90', DIRECT, True),   # Hepatic failure, unspecified without coma (1,813 pts)
        ('K72.10', DIRECT, True),   # Chronic hepatic failure without coma (710 pts)
        ('K72.00', DIRECT, True),   # Acute and subacute hepatic failure without coma (340 pts)
        ('K72.91', DIRECT, True),   # Hepatic failure, unspecified with coma (91 pts)
        # Portal hypertension
        ('K76.6',  DIRECT, True),   # Portal hypertension (606 pts)
        ('K76.82', DIRECT, True),   # Hepatic encephalopathy (1,073 pts)
        ('K76.89', DIRECT, True),   # Other specified diseases of liver (789 pts)
        # Viral hepatitis — major competing liver diseases
        ('B18.2',  DIRECT, True),   # Chronic viral hepatitis C (2,732 pts)
        ('B19.20', DIRECT, True),   # Unspecified viral hepatitis C without hepatic coma (911 pts)
        ('B18.1',  DIRECT, True),   # Chronic viral hepatitis B without delta-agent (391 pts)
        ('B18.0',  DIRECT, True),   # Chronic viral hepatitis B with delta-agent (14 pts)
        # Autoimmune hepatitis
        ('K75.4',  DIRECT, True),   # Autoimmune hepatitis (419 pts)
        ('K75.9',  PROXY,  False),  # Inflammatory liver disease, unspecified (145 pts)
        # Biliary / cholestatic liver disease
        ('K83.1',  DIRECT, True),   # Obstruction of bile duct (763 pts)
        ('K83.09', DIRECT, True),   # Other cholangitis (222 pts)
        ('K83.8',  PROXY,  False),  # Other specified diseases of biliary tract (1,251 pts)
        # Heart failure as direct cause of congestive hepatopathy
        ('I50.9',  DIRECT, True),   # Heart failure, unspecified (5,219 pts)
        ('I50.20', DIRECT, True),   # Unspecified systolic HF (2,688 pts)
        ('I50.32', DIRECT, True),   # Chronic diastolic HF (2,077 pts)
        ('I50.22', DIRECT, True),   # Chronic systolic HF (1,580 pts)
        ('I50.42', DIRECT, True),   # Chronic combined HF (1,426 pts)
        ('I50.23', DIRECT, True),   # Acute on chronic systolic HF (856 pts)
        ('I50.30', DIRECT, True),   # Unspecified diastolic HF (652 pts)
        ('I50.33', DIRECT, True),   # Acute on chronic diastolic HF (570 pts)
        # Imaging and hepatomegaly (supporting finding)
        ('R16.0',  PROXY,  False),  # Hepatomegaly, not elsewhere classified (1,530 pts)
        ('R93.2',  PROXY,  False),  # Abnormal findings on diagnostic imaging of liver/biliary tract (707 pts)
    ],

    # ── hepatic_alp_elevation ─────────────────────────────────────────────
    # Existing: R74.0, R94.5
    'hepatic_alp_elevation': [
        # Liver enzyme abnormalities
        ('R74.01', DIRECT, True),   # Elevation of liver transaminase levels (6,363 WH pts)
        ('R74.8',  PROXY,  False),  # Abnormal levels of other serum enzymes (10,531 pts)
        ('R74.09', PROXY,  False),  # Other abnormal serum enzyme levels
        # Jaundice — often accompanies cholestatic ALP elevation
        ('R17',    PROXY,  False),  # Unspecified jaundice (2,101 pts)
        # Primary causes of cholestatic / hepatic ALP elevation
        ('K74.3',  DIRECT, True),   # Primary biliary cirrhosis (425 pts)
        ('K75.4',  PROXY,  False),  # Autoimmune hepatitis (419 pts)
        ('K83.1',  DIRECT, True),   # Obstruction of bile duct (763 pts)
        ('K83.09', DIRECT, True),   # Other cholangitis (222 pts)
        ('K83.8',  PROXY,  False),  # Other specified diseases of biliary tract (1,251 pts)
        ('K80.50', PROXY,  False),  # Calculus of bile duct without cholangitis/cholecystitis (1,512 pts)
        ('K80.51', PROXY,  False),  # Calculus of bile duct without cholangitis, with obstruction (213 pts)
        # Liver infiltration and tumour — cause isolated ALP elevation
        ('C22.1',  PROXY,  False),  # Intrahepatic bile duct carcinoma / cholangiocarcinoma (229 pts)
        ('C78.7',  PROXY,  False),  # Secondary malignant neoplasm of liver (246 pts)
        # Hepatic imaging abnormalities (found in same workup)
        ('R93.2',  PROXY,  False),  # Abnormal findings on diagnostic imaging of liver/biliary tract (707 pts)
        # Pancreatic disease — pancreatic head can obstruct bile duct → ALP rise
        ('K86.89', PROXY,  False),  # Other specified diseases of pancreas (1,168 pts)
        ('K86.1',  PROXY,  False),  # Other chronic pancreatitis (1,103 pts)
        # Underlying liver disease (fibrosis/cirrhosis — ALP often elevated)
        ('K74.00', PROXY,  False),  # Hepatic fibrosis, unspecified (719 pts)
        ('K74.69', PROXY,  False),  # Other cirrhosis of liver (2,045 pts)
        ('K74.60', PROXY,  False),  # Unspecified cirrhosis of liver (5,609 pts)
    ],

    # ── hepatomegaly ──────────────────────────────────────────────────────
    # Existing: R16.0, R16.2
    'hepatomegaly': [
        # Splenomegaly — closely related finding, often co-occurring
        ('R16.1',  PROXY,  False),  # Splenomegaly, not elsewhere classified (225 WH pts)
        # Congestive hepatomegaly — direct liver congestion causes enlargement
        ('K76.1',  DIRECT, True),   # Chronic passive congestion of liver (36 pts)
        ('K76.5',  DIRECT, True),   # Hepatic veno-occlusive disease — Budd-Chiari type (5 pts)
        # Liver diseases causing hepatomegaly
        ('K76.82', PROXY,  False),  # Hepatic encephalopathy (1,073 pts)
        ('K76.89', PROXY,  False),  # Other specified diseases of liver (789 pts)
        ('K76.6',  PROXY,  False),  # Portal hypertension (606 pts)
        ('K76.7',  PROXY,  False),  # Hepatorenal syndrome (150 pts)
        ('K76.3',  PROXY,  False),  # Infarction of liver (2 pts)
        # Congenital liver disease causing hepatomegaly
        ('Q44.6',  PROXY,  False),  # Cystic disease of liver / polycystic liver (60 pts)
        ('Q44.71', PROXY,  False),  # Alagille syndrome — cholestatic liver disease (16 pts)
        # Hepatomegaly imaging abnormalities
        ('R93.2',  PROXY,  False),  # Abnormal findings on diagnostic imaging of liver/biliary tract (707 pts)
    ],
}

data = json.load(open('v5/config/shared/atoms/HEPATOLOGY.json', encoding='utf-8'))
atom_lookup = {a['atom_id']: a for a in data['atoms']}

total_added = 0
total_filled = 0
for aid, specs in ADDITIONS.items():
    atom = atom_lookup[aid]
    n = add_codes(atom, [make_entry(c, r, s) for c, r, s in specs])
    total_added += n
    print('  ' + aid.ljust(35) + '+' + str(n).rjust(3) + ' new codes')

for atom in data['atoms']:
    total_filled += backfill(atom)

print()
print('Total new ICD entries:          ' + str(total_added))
print('display_names backfilled:       ' + str(total_filled))

with open('v5/config/shared/atoms/HEPATOLOGY.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
print('Saved HEPATOLOGY.json')

total = sum(1 for a in data['atoms'] for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[]))
missing = [(a['atom_id'], e['value']) for a in data['atoms']
           for e in a.get('extraction',{}).get('codes',{}).get('ICD10',[])
           if 'display_name' not in e]
print('Total ICD10 entries: ' + str(total))
print('Missing display_name: ' + str(len(missing)))
if missing:
    for aid, v in missing: print('  [' + aid + '] ' + v)
print('JSON valid: OK')

"""Print new warehouse candidates per atom for clinical review."""
import csv
from collections import defaultdict

rows = list(csv.DictReader(open(
    'v5/audits/terminology/generated/icd_candidates_utf8.csv', encoding='utf-8'
)))

by_atom = defaultdict(list)
for r in rows:
    if r['status'] == 'WAREHOUSE_CANDIDATE':
        by_atom[r['atom_id']].append(r)

focus_atoms = [
    'af', 'arrhythmia', 'as_valve', 'asymmetric_septal_hypertrophy',
    'cardiomegaly', 'cardiomyopathy', 'conduction_disease',
    'declining_blood_pressure', 'dizziness', 'dyspnea',
    'hf_any', 'hfpef', 'hf_medication_intolerance', 'hypertension',
    'hypertrophic_cardiomyopathy', 'lflg_as', 'low_ecg_voltage',
    'macroglossia', 'pacemaker_implantation', 'pacemaker_presence',
    'pericardial_effusion', 'periorbital_purpura', 'pseudo_infarct',
    'restrictive_cardiomyopathy', 'restrictive_filling',
    'syncope', 'tavr', 'thick_walls', 'troponin_elevated',
    'ntprobnp_elevated', 'v24_competing_lvh',
    'al08_competing_purpura', 'ecchymosis',
]

for aid in focus_atoms:
    cands = sorted(by_atom.get(aid, []), key=lambda x: -int(x['warehouse_patients']))[:30]
    if not cands:
        continue
    print('=== ' + aid + ' ===')
    for r in cands:
        print('  ' + r['code'].ljust(12) + str(r['warehouse_patients']).rjust(7) + '  ' + r['description'])
    print()

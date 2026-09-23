"""Fix display_name for three non-billable parent codes that have no 2026 entry."""
import json

manual = {
    'I50.3': 'Diastolic (congestive) heart failure [non-billable parent; use I50.30-I50.33]',
    'E05.9': 'Thyrotoxicosis, unspecified [non-billable parent; use E05.90]',
    'I31.3': 'Pericardial effusion (noninflammatory) [non-billable parent; use I31.31/I31.39]',
}

files = [
    'v5/config/shared/atoms/CARDIOLOGY.json',
    'v5/config/shared/atoms/DERMATOLOGY_ORAL.json',
    'v5/config/shared/atoms/DERMATOLOGY.json',
    'v5/config/shared/atoms/ENT.json',
]

for path in files:
    data = json.load(open(path, encoding='utf-8'))
    changed = False
    for atom in data['atoms']:
        for entry in atom.get('extraction', {}).get('codes', {}).get('ICD10', []):
            val = entry['value']
            if val in manual and 'display_name' not in entry:
                entry['display_name'] = manual[val]
                changed = True
                print('Fixed ' + val + ' in ' + path.split('/')[-1])
    if changed:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

print('Done')

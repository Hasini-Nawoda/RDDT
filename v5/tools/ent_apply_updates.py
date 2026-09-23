"""Apply full 2026 ICD-10-CM additions to ENT.json (al07_competing_macroglossia)."""
import json

def load(path):
    return json.load(open(path, encoding='utf-8'))

def save(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    print(f'Saved {path}')

def make_entry(value, role, standalone):
    return {
        'value': value,
        'can_fire_atom_alone': standalone,
        'review_status': 'WAREHOUSE_REVIEWED',
        'mapping_role': role,
        'match_mode': 'EXACT',
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

DIRECT = 'DIRECT_TARGET'
PROXY  = 'PROXY_SUPPORT'
SUPP   = 'SUPPORTING'

# All additions for al07_competing_macroglossia
NEW_CODES = [
    # ── Hypothyroidism family ──────────────────────────────────────────────────
    # All E03.x subtypes cause myxedema → tongue swelling
    ('E03.0',  DIRECT, True),   # Congenital hypothyroidism with diffuse goiter
    ('E03.1',  DIRECT, True),   # Congenital hypothyroidism without goiter
    ('E03.2',  DIRECT, True),   # Hypothyroidism due to medicaments/exogenous substances
    ('E03.3',  DIRECT, True),   # Postinfectious hypothyroidism
    ('E03.4',  DIRECT, True),   # Atrophy of thyroid (acquired)
    ('E03.5',  DIRECT, True),   # Myxedema coma
    ('E03.8',  DIRECT, True),   # Other specified hypothyroidism (3,056 warehouse patients)
    ('E89.0',  DIRECT, True),   # Postprocedural hypothyroidism (2,178 pts) — post-thyroidectomy
    # Iodine-deficiency related (cause cretinism/myxedema with macroglossia)
    ('E02',    PROXY,  False),  # Subclinical iodine-deficiency hypothyroidism
    ('E01.0',  PROXY,  False),  # Iodine-deficiency related diffuse goiter
    ('E00.0',  DIRECT, True),   # Congenital iodine-deficiency syndrome, neurological type
    ('E00.9',  DIRECT, True),   # Congenital iodine-deficiency syndrome, unspecified

    # ── Down syndrome family ───────────────────────────────────────────────────
    ('Q90.0',  DIRECT, True),   # Trisomy 21, nonmosaicism
    ('Q90.1',  DIRECT, True),   # Trisomy 21, mosaicism
    ('Q90.2',  DIRECT, True),   # Trisomy 21, translocation

    # ── Angioedema family ──────────────────────────────────────────────────────
    # Subsequent-encounter and sequela variants of the already-configured initial code
    ('T78.3XXD', DIRECT, True),  # Angioneurotic edema, subsequent encounter
    ('T78.3XXS', DIRECT, True),  # Angioneurotic edema, sequela
    # ACE inhibitor-induced angioedema — classic drug cause of tongue swelling
    ('T46.4X5A', DIRECT, True),  # Adverse effect of ACE inhibitors, initial encounter
    ('T46.4X5D', DIRECT, True),  # Adverse effect of ACE inhibitors, subsequent encounter
    ('T46.4X1A', PROXY,  False), # Accidental poisoning by ACE inhibitors
    # Hereditary angioedema (C1-esterase inhibitor deficiency)
    ('D84.1',  DIRECT, True),   # Defects in the complement system (HAE)
    # Anaphylaxis/allergy — can present with angioedema and tongue swelling
    ('T78.2XXA', PROXY, False),  # Anaphylactic shock, unspecified, initial encounter
    ('T78.40XA', PROXY, False),  # Allergy, unspecified, initial encounter
    ('T78.49XA', PROXY, False),  # Other allergy, initial encounter

    # ── Vascular lesions of tongue ────────────────────────────────────────────
    ('D18.1',  DIRECT, True),   # Lymphangioma, any site — a cause of macroglossia
    ('D18.09', PROXY,  False),  # Hemangioma of other sites — may include tongue
    ('D18.00', PROXY,  False),  # Hemangioma, unspecified site

    # ── Glycogen storage diseases ─────────────────────────────────────────────
    ('E74.02', DIRECT, True),   # Pompe disease — glycogen storage, macroglossia is a feature
    ('E74.00', PROXY,  False),  # Glycogen storage disease, unspecified
    ('E74.09', PROXY,  False),  # Other glycogen storage disease
    ('E74.01', PROXY,  False),  # Von Gierke disease

    # ── Mucopolysaccharidoses ─────────────────────────────────────────────────
    # All MPS subtypes that affect tongue/facial features
    ('E76.01', DIRECT, True),   # Hurler's syndrome (MPS IH) — macroglossia is classic
    ('E76.1',  DIRECT, True),   # Mucopolysaccharidosis type II (Hunter syndrome)
    ('E76.22', DIRECT, True),   # Sanfilippo mucopolysaccharidoses (MPS III)
    ('E76.29', PROXY,  False),  # Other mucopolysaccharidoses
    ('E76.3',  PROXY,  False),  # Mucopolysaccharidosis, unspecified

    # ── Congenital overgrowth syndromes ───────────────────────────────────────
    # Beckwith-Wiedemann syndrome is the prime overgrowth cause of macroglossia
    ('Q87.3',  DIRECT, True),   # Congenital malformation syndromes involving early overgrowth
    ('Q38.3',  DIRECT, True),   # Other congenital malformations of tongue
    ('Q87.0',  PROXY,  False),  # Congenital malformation syndromes affecting facial appearance
    ('Q87.89', PROXY,  False),  # Other specified congenital malformation syndromes

    # ── Pituitary hyperfunction (acromegaly family) ───────────────────────────
    ('E22.8',  PROXY,  False),  # Other hyperfunction of pituitary gland
    ('E22.9',  PROXY,  False),  # Hyperfunction of pituitary gland, unspecified

    # ── Tongue disease context ────────────────────────────────────────────────
    ('K14.8',  PROXY,  False),  # Other diseases of tongue
    ('K14.9',  PROXY,  False),  # Disease of tongue, unspecified
]

ent = load('v5/config/shared/atoms/ENT.json')
atom_lookup = {a['atom_id']: a for a in ent['atoms']}
atom = atom_lookup['al07_competing_macroglossia']

entries = [make_entry(code, role, standalone) for (code, role, standalone) in NEW_CODES]
n = add_codes(atom, entries)
print(f'al07_competing_macroglossia: +{n} new ICD10 codes added')

save('v5/config/shared/atoms/ENT.json', ent)

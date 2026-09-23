"""Remove verified ICD mismatches. Keep R79.89 on troponin_elevated and G43.A0/A1."""
import json
from pathlib import Path

BASE = Path("v5/config/shared/atoms")

REMOVE = {
    "CARDIOLOGY.json": {
        "dizziness": {
            "H81.10", "H81.11", "H81.12", "H81.13", "H81.4",
            "H81.399", "H81.391", "H81.392", "H81.393",
            "H81.90", "H81.93", "H83.2X3", "H83.2X9", "H81.01", "H81.09",
        },
        "hf_any": {"I11.9", "I13.10", "I13.11"},
        "hypertrophic_cardiomyopathy": {"I42.0"},
        "al20_competing_dyspnea": {"J06.9"},
        "dyspnea": {"R06.81"},
        "ntprobnp_elevated": {"R79.89", "R79.9"},
        "troponin_elevated": {"R79.9"},
    },
    "ENT.json": {
        "al07_competing_macroglossia": {
            "E02", "E01.0", "T78.2XXA", "T78.40XA", "T78.49XA", "D18.00", "D18.09",
        },
    },
    "GASTROENTEROLOGY.json": {
        "constipation": {"R15.9"},
        "delayed_gastric_emptying": {"K31.1"},
        "diarrhea": {"K52.21", "A09"},
        "dysarthria": {"R48.2", "R41.3"},
        "dysphagia": {"K22.70"},
        "vomiting": {"K92.0"},
        "early_satiety": {"R10.4"},
    },
    "GENERAL_MEDICINE.json": {
        "declining_bmi": {"Z68.20", "Z68.21"},
        "malaise": {"R68.83"},
        "other_serosal_effusion": {"K65.0", "K65.2", "K65.4", "K65.8", "K65.9"},
    },
    "GENETICS.json": {
        "fhx_sudden_death": {"Z82.3", "Z82.0", "Z86.74"},
    },
    "MULTISPECIALTY.json": {
        "fhx_adult_onset_neuropathy": {"Z82.3"},
        "wt21_competing_hearing_loss": {"H81.10", "H81.11", "H81.12", "H81.13"},
        "ligamentum_flavum_thickening": {"M48.02", "M48.04"},
    },
    "HEMATOLOGY.json": {
        "plasma_cell_dyscrasia": {"C88.40", "C88.41"},
        "myeloma_therapy_exposure": {"Z51.5", "Z79.899"},
    },
    "HEPATOLOGY.json": {
        "hepatomegaly": {"R16.1", "K76.3", "Q44.71"},
    },
    "NEPHROLOGY.json": {
        "hypoalbuminemia": {"E88.89"},
        "urine_immunofixation_monoclonal": {"R80.9", "R82.998"},
        "urine_protein_result": {"R82.90"},
        "peripheral_edema": {"I89.0", "T78.3XXA"},
    },
    "NEUROLOGY.json": {
        "demyelinating_emg_pattern": {"G37.9"},
        "anhidrosis": {"G90.A"},
        "neurogenic_bladder": {"R35.1"},
        "trophic_change": {"L85.3", "L98.9", "L85.8"},
        "urinary_incontinence": {"N39.3"},
        "plantar_ulcer": {"I70.234", "I70.235"},
    },
    "OPHTHALMOLOGY.json": {
        "dry_eye": {"H16.141", "H16.142", "H16.149"},
        "iris_abnormality": {"H21.00", "H21.531", "H21.532"},
        "scalloped_pupil": {"H57.01"},
    },
    "ORTHOPEDICS_MSK.json": {
        "arthroplasty": {"Z96.611", "Z96.612"},
        "biceps_rupture": {"M75.111", "M75.112", "M75.121", "M75.122"},
        "lumbar_stenosis": {"M47.816", "M48.04", "M48.05"},
        "persistent_lower_limb_symptoms_after_decompression": {"M54.50"},
    },
    "PULMONOLOGY.json": {
        "pleural_effusion": {"J93.9"},
    },
    "RHEUM_INFLAMMATORY.json": {
        "chronic_inflammatory_arthritis": {"M06.20", "M05.10"},
        "crp_result": {"R79.89"},
        "esr_result": {"R70.1"},
        "ibd_inflammatory_driver": {"K52.9"},
        "saa_result": {"R79.89"},
    },
}

removed = []
missing = []
for fn, atoms in REMOVE.items():
    path = BASE / fn
    data = json.loads(path.read_text(encoding="utf-8"))
    by_id = {a["atom_id"]: a for a in data["atoms"]}
    for atom_id, codes in atoms.items():
        atom = by_id[atom_id]
        icd = atom["extraction"]["codes"].get("ICD10", [])
        present = {e["value"] for e in icd}
        for code in sorted(codes):
            if code not in present:
                missing.append(f"{fn}|{atom_id}|{code}")
        kept = [e for e in icd if e["value"] not in codes]
        gone = [e["value"] for e in icd if e["value"] in codes]
        removed.extend(f"{fn}|{atom_id}|{v}" for v in gone)
        atom["extraction"]["codes"]["ICD10"] = kept
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

print(f"removed {len(removed)}")
for line in removed:
    print(" -", line)
if missing:
    print(f"NOT FOUND {len(missing)}")
    for line in missing:
        print(" ?", line)

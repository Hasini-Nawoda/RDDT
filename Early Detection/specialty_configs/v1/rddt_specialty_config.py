"""
RDDT v1.1 - specialty Tier feature catalog (clinical rules only).

This file does not name client tables or columns. Source mapping lives in the
notebook SOURCE_CONFIG + rddt_attr_sql.py, which writes ATTR_EVID_* temps.
Step 4 (rddt_specialty_sql.py) reads those canonical temps.

Shortlist: Ortho / Cardio / Neuro Tier 1–2; ≥2 specialties.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Shortlist knobs
# ---------------------------------------------------------------------------
SHORTLIST_SPECIALTIES = ("ortho", "cardio", "neuro")
SHORTLIST_MIN_SPECIALTIES = 2  # need Tier1 or Tier2 in >= this many specialties
SHORTLIST_N = None  # None = keep ALL combo passers (no top-N cap)

# ---------------------------------------------------------------------------
# Atomic building blocks (detected from codes + NLP across all tables)
# ---------------------------------------------------------------------------
# icd_prefixes: code startswith any of these (after normalizing)
# cpt_exact: exact CPT match
# nlp: lowercase substring patterns (any match)

ATOMS: Dict[str, Dict[str, Any]] = {
    # --- Ortho ---
    "cts_any": {
        "icd_prefixes": ("G56.0", "G560"),
        "cpt_exact": (),
        "nlp": (
            "carpal tunnel", "carpel tunnel", "median neuropathy at wrist",
            "cts release", "ctr ", " ctr",
        ),
    },
    "cts_bilateral": {
        "icd_prefixes": ("G56.03", "G5603"),
        "cpt_exact": (),
        "nlp": (
            "bilateral carpal tunnel", "bilateral cts", "carpal tunnel both",
            "both wrists", "carpal tunnel surgery both", "cts both wrists",
            "bilateral carpel tunnel",
        ),
    },
    "cts_recurrent": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": (
            "recurrent carpal tunnel", "recurrent cts", "intractable carpal",
            "repeat carpal tunnel", "revision carpal tunnel",
            "contralateral carpal tunnel release",
        ),
    },
    "ctr_any": {
        "icd_prefixes": (),
        "cpt_exact": ("64721",),
        "nlp": (
            "carpal tunnel release", "carpel tunnel surgery", "carpal tunnel surgery",
            "cts release", "ctr surgery",
        ),
    },
    "biceps_rupture": {
        "icd_prefixes": ("M66.82", "M6682", "S46.2", "S462"),
        "cpt_exact": (),
        "nlp": (
            "biceps tendon rupture", "distal biceps", "popeye",
            "atraumatic biceps", "spontaneous biceps",
        ),
    },
    "trigger_finger": {
        "icd_prefixes": ("M65.3", "M653"),
        "cpt_exact": (),
        "nlp": (
            "trigger finger", "trigger digit", "stenosing tenosynovitis",
            "flexor tenosynovitis", "a1 pulley",
        ),
    },
    "lumbar_stenosis": {
        "icd_prefixes": ("M48.06", "M4806", "M48.07", "M4807"),
        "cpt_exact": (),
        "nlp": (
            "lumbar spinal stenosis", "lumbar stenosis", "spinal stenosis",
            "neurogenic claudication", "ligamentum flavum",
            "posterior lumbar decompression", "laminectomy",
        ),
    },
    "rotator_cuff": {
        "icd_prefixes": ("M75.1", "M751"),
        "cpt_exact": (),
        "nlp": ("rotator cuff", "shoulder repair",),
    },
    "arthroplasty": {
        "icd_prefixes": ("Z96.6", "Z966"),
        "cpt_exact": ("27447", "27130"),
        "nlp": (
            "knee replacement", "hip replacement", "total knee", "total hip",
            "arthroplasty", "tka", "tha", "joint replacement",
        ),
    },
    "congo_red": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": (
            "congo red", "apple-green", "apple green birefringence",
            "amyloid deposits", "thioflavin",
        ),
    },
    "dupuytren": {
        "icd_prefixes": ("M72.0", "M720"),
        "cpt_exact": (),
        "nlp": ("dupuytren", "palmar fibromatosis", "palmar cord"),
    },
    "achilles": {
        "icd_prefixes": ("M66.36", "M6636"),
        "cpt_exact": (),
        "nlp": ("achilles tendon rupture", "achilles tendinopathy", "atraumatic achilles"),
    },
    # --- Cardio ---
    "apical_sparing": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": (
            "apical sparing", "cherry-on-top", "cherry on top",
            "relative apical sparing", "bullseye pattern",
        ),
    },
    "cmr_ecv": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": ("expanded extracellular volume", "increased ecv", "ecv fraction", " elevated ecv"),
    },
    "cmr_native_t1": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": (
            "native t1", "elevated native t1", "t1 mapping",
            "non-contrast t1", "t1-ecv discordance",
        ),
    },
    "cmr_lge": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": (
            "diffuse lge", "subendocardial lge", "transmural lge",
            "circumferential lge", "late gadolinium",
        ),
    },
    "thick_walls": {
        "icd_prefixes": ("I51.7", "I517", "I42.", "I42"),
        "cpt_exact": (),
        "nlp": (
            "wall thickness", "increased wall thickness", "unexplained lvh",
            "left ventricular hypertrophy", "ivsd", "interventricular septal",
            "posterior wall thickness", "concentric hypertrophy",
            ">=12 mm", "≥12", ">12 mm", "lvh",
        ),
    },
    "voltage_mass_mismatch": {
        "icd_prefixes": ("R94.31", "R9431"),
        "cpt_exact": (),
        "nlp": (
            "voltage-mass mismatch", "voltage mass mismatch",
            "low voltage with lvh", "low qrs voltage", "limb lead low voltage",
            "discordant voltage",
        ),
    },
    "pyp_grade_2_3": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": (
            "perugini grade 2", "perugini grade 3", "grade 2 uptake", "grade 3 uptake",
            "pyp scan", "tc-99m pyrophosphate", "dpd scintigraphy", "hmdp scan",
            "heart-to-contralateral", "cardiac uptake grade",
        ),
    },
    "restrictive_filling": {
        "icd_prefixes": ("I42.5", "I425"),
        "cpt_exact": (),
        "nlp": (
            "restrictive filling", "grade iii diastolic", "grade 3 diastolic",
            "elevated e/e", "restrictive physiology", "restrictive cardiomyopathy",
        ),
    },
    "biatrial_enlargement": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": ("biatrial enlargement", "enlarged left atrium", "enlarged right atrium"),
    },
    "hfpef": {
        "icd_prefixes": ("I50.3", "I503"),
        "cpt_exact": (),
        "nlp": (
            "hfpef", "preserved ef", "diastolic heart failure",
            "heart failure with preserved", "diastolic hf",
        ),
    },
    "hf_any": {
        "icd_prefixes": ("I50.", "I50"),
        "cpt_exact": (),
        "nlp": ("heart failure", "congestive heart failure", "chf"),
    },
    "reduced_gls": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": ("reduced gls", "impaired longitudinal strain", "reduced global longitudinal"),
    },
    "as_valve": {
        "icd_prefixes": ("I35.0", "I35.2", "I350", "I352", "I35."),
        "cpt_exact": (),
        "nlp": ("aortic stenosis", "aortic valve stenosis"),
    },
    "lflg_as": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": (
            "low-flow low-gradient", "low flow low gradient", "lflg as",
            "paradoxical low-flow", "tavr evaluation", "pre-tavr", "pre-tavi", "tavi",
        ),
    },
    "tavr": {
        "icd_prefixes": (),
        "cpt_exact": ("33361", "33362", "33363", "33364", "33365", "33366"),
        "nlp": ("tavr", "tavi", "transcatheter aortic"),
    },
    "conduction_disease": {
        "icd_prefixes": ("I44.", "I44", "I45.", "I45"),
        "cpt_exact": (),
        "nlp": (
            "av block", "complete heart block", "rbbb", "lbbb",
            "bifascicular", "trifascicular", "sick sinus", "sinus node",
        ),
    },
    "pacemaker_icd": {
        "icd_prefixes": ("Z95.0", "Z950", "Z95.810", "Z95810"),
        "cpt_exact": ("33206", "33207", "33208", "33249"),
        "nlp": (
            "permanent pacemaker", "pacemaker", "icd implantation",
            "crt-p", "crt-d", "cardiac resynchronization",
        ),
    },
    "af": {
        "icd_prefixes": ("I48.", "I48"),
        "cpt_exact": (),
        "nlp": ("atrial fibrillation", "atrial flutter", "persistent af", "paroxysmal af"),
    },
    "low_svi": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": (
            "low stroke volume index", "reduced svi", "low cardiac output",
            "low stroke volume", "stroke volume index",
        ),
    },
    "difficulty_nulling": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": ("difficulty nulling myocardium", "abnormal myocardial nulling", "difficulty nulling"),
    },
    # Cardio T3/T4 atoms (extract only)
    "small_lv_cavity": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": ("small lv cavity", "reduced lv cavity", "nondilated lv", "small ventricular cavity"),
    },
    "troponin_elevated": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": ("troponin t", "troponin i", "hs-tnt", "hs-ctni", "chronic troponin"),
    },
    "ntprobnp_elevated": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": ("nt-probnp", "probnp", "b-type natriuretic", "elevated bnp", "natriuretic peptide"),
    },
    "pseudo_infarct": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": ("pseudo-infarction", "pseudo-mi", "poor r-wave progression"),
    },
    "pericardial_effusion": {
        "icd_prefixes": ("I31.3", "I313"),
        "cpt_exact": (),
        "nlp": ("pericardial effusion", "fluid in the pericardial"),
    },
    "thickened_ias": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": ("thickened ias", "interatrial septum thickened", "thickened interatrial"),
    },
    "rv_wall_thick": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": ("rv hypertrophy", "thickened rv", "right ventricular wall thickening"),
    },
    "valve_thickening": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": ("valve thickening", "mitral thickening", "tricuspid thickening", "aortic valve thickening"),
    },
    "granular_myocardium": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": (
            "granular sparkling", "speckled myocardium", "increased myocardial echogenicity",
            "sparkling appearance",
        ),
    },
    # --- Neuro ---
    "polyneuropathy": {
        "icd_prefixes": ("G62.", "G62", "G60.", "G60"),
        "cpt_exact": (),
        "nlp": (
            "polyneuropathy", "peripheral neuropathy", "sensorimotor neuropathy",
            "axonal polyneuropathy",
        ),
    },
    # Length-dependent axonal PN: keep ICD bridges (G62/G60) + Excel length-dep keywords
    "length_dependent": {
        "icd_prefixes": ("G62.", "G62", "G60.", "G60"),
        "cpt_exact": (),
        "nlp": (
            "length-dependent neuropathy", "length dependent neuropathy",
            "length-dependent polyneuropathy", "length dependent polyneuropathy",
            "stocking-glove", "stocking glove", "stocking-glove distribution",
            "symmetric sensorimotor polyneuropathy", "symmetric length-dependent",
            "distal symmetric polyneuropathy", "idiopathic axonal polyneuropathy",
            "distal axonal neuropathy",
        ),
    },
    "sfn": {
        # Excel bridge ICD G60.8 (+ related G60.9 / G62 used when SFN coded that way)
        "icd_prefixes": ("G60.8", "G608", "G60.9", "G609"),
        "cpt_exact": (),
        "nlp": (
            "small fiber neuropathy", "small-fiber neuropathy", "small fibre neuropathy",
            "small fiber dysfunction", "isolated small-fiber", "early sensory neuropathy",
            "sfn",
        ),
    },
    "ienfd": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": (
            "reduced ienfd", "low intraepidermal nerve fiber", "intraepidermal nerve fiber",
            "pgp 9.5", "pgp9.5", "skin biopsy nerve fiber",
            "decreased epidermal nerve fiber",
        ),
    },
    "emg_axonal": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": (
            "axonal neuropathy", "axonal pattern", "axonal sensorimotor",
            "non-excitable nerves", "severe axonal", "axonal loss predominant",
            "absent conduction block", "no conduction block",
        ),
    },
    "emg_mixed": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": ("mixed axonal-demyelinating", "atypical cidp", "secondary axonal loss"),
    },
    "cidp": {
        "icd_prefixes": ("G61.81", "G6181"),
        "cpt_exact": (),
        "nlp": ("cidp", "chronic inflammatory demyelinating"),
    },
    "cidp_failed": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": (
            "refractory to ivig", "failed immunotherapy", "steroid non-responsive",
            "treatment-refractory cidp", "no response to ivig", "failed ivig",
            "did not improve with", "nonresponder to ivig", "ivig refractory",
            "steroid refractory neuropathy", "no response to steroids",
        ),
    },
    "orthostatic": {
        "icd_prefixes": ("I95.1", "I951"),
        "cpt_exact": (),
        "nlp": (
            "orthostatic hypotension", "neurogenic orthostatic", "postural bp drop",
            "syncope on standing",
        ),
    },
    "progressive_neuropathy": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": (
            "progressive neuropathy", "worsening despite treatment",
            "relentlessly progressive", "treatment-refractory progression",
            "neuropathy progressing", "worsening weakness neuropathy",
        ),
    },
    "neuro_suspects_attr": {
        "icd_prefixes": (),
        "cpt_exact": (),
        "nlp": (
            "suspect amyloid neuropathy", "rule out attr", "consider hereditary amyloidosis",
            "recommend ttr genetic", "refer amyloid", "amyloid neuropathy",
            "possible attr neuropathy", "amyloid polyneuropathy suspected",
        ),
    },
    "neuropathic_pain": {
        "icd_prefixes": ("R20.8", "R208"),
        "cpt_exact": (),
        "nlp": ("burning feet", "dysesthesia", "allodynia", "neuropathic pain"),
    },
    "fhx_sudden_death": {
        "icd_prefixes": ("Z82.41", "Z8241"),
        "cpt_exact": (),
        "nlp": (
            "sudden cardiac death", "family history of amyloidosis",
            "hereditary neuropathy", "familial polyneuropathy", "ttr mutation",
        ),
        "family_tables_only": True,
    },
    "confirmed_attr_e85": {
        "icd_prefixes": ("E85.", "E85"),
        "cpt_exact": (),
        "nlp": (
            "attr-cm", "attr amyloidosis", "transthyretin amyloidosis",
            "wild-type attr", "hereditary attr",
        ),
    },
}

# Anatomical MSK buckets for Ortho composites
MSK_BUCKET_ATOMS: Dict[str, Tuple[str, ...]] = {
    "hand_cts": ("cts_any", "cts_bilateral", "ctr_any", "trigger_finger", "dupuytren"),
    "elbow_biceps": ("biceps_rupture",),
    "spine_lss": ("lumbar_stenosis",),
    "shoulder": ("rotator_cuff",),
    "joints": ("arthroplasty",),
    "achilles": ("achilles",),
}

# ---------------------------------------------------------------------------
# Specialty features (shortlist-eligible = image T1/T2 + confirmed Excel extras)
# logic: "any_atom" | "all_atoms" | "composite_fn"
# ---------------------------------------------------------------------------

FEATURES: List[Dict[str, Any]] = [
    # ===== ORTHO T1 (image) =====
    {
        "feature_id": "O_T1_RECURRENT_BCT",
        "specialty": "ortho",
        "tier": 1,
        "shortlist": True,
        "short_name": "Recurrent / hard-to-treat BCT",
        "logic": "all_atoms",
        "atoms": ("cts_bilateral", "cts_recurrent"),
        # also allow bilateral + CTR as recurrent proxy if recurrent NLP missing
        "alt_all_atoms": ("cts_bilateral", "ctr_any"),
    },
    {
        "feature_id": "O_T1_REDFLAG_FHX_HF",
        "specialty": "ortho",
        "tier": 1,
        "shortlist": True,
        "short_name": "Ortho red flag + FHx SCD + HF",
        "logic": "composite_fn",
        "fn": "ortho_redflag_fhx_hf",
    },
    {
        "feature_id": "O_T1_GE2_REGIONS",
        "specialty": "ortho",
        "tier": 1,
        "shortlist": True,
        "short_name": ">=2 anatomical MSK regions",
        "logic": "composite_fn",
        "fn": "msk_regions_ge2",
    },
    {
        "feature_id": "O_T1_GE3_MANIFEST",
        "specialty": "ortho",
        "tier": 1,
        "shortlist": True,
        "short_name": ">=3 ortho manifestations",
        "logic": "composite_fn",
        "fn": "msk_manifest_ge3",
    },
    {
        "feature_id": "O_T1_LSS_CTS",
        "specialty": "ortho",
        "tier": 1,
        "shortlist": True,
        "short_name": "LSS + CTS",
        "logic": "all_atoms",
        "atoms": ("lumbar_stenosis", "cts_any"),
    },
    # ===== ORTHO T2 (image) =====
    {
        "feature_id": "O_T2_BCT",
        "specialty": "ortho",
        "tier": 2,
        "shortlist": True,
        "short_name": "Bilateral CTS (BCT)",
        "logic": "any_atom",
        "atoms": ("cts_bilateral",),
    },
    {
        "feature_id": "O_T2_BICEPS",
        "specialty": "ortho",
        "tier": 2,
        "shortlist": True,
        "short_name": "Distal biceps rupture",
        "logic": "any_atom",
        "atoms": ("biceps_rupture",),
    },
    {
        "feature_id": "O_T2_TRIGGER_CTS",
        "specialty": "ortho",
        "tier": 2,
        "shortlist": True,
        "short_name": "Trigger finger + CTS",
        "logic": "all_atoms",
        "atoms": ("trigger_finger", "cts_any"),
    },
    {
        "feature_id": "O_T2_LSS",
        "specialty": "ortho",
        "tier": 2,
        "shortlist": True,
        "short_name": "Lumbar spinal stenosis",
        "logic": "any_atom",
        "atoms": ("lumbar_stenosis",),
    },
    # ===== ORTHO T3/T4 (Excel extract only) =====
    {
        "feature_id": "O_T3_ARTHROPLASTY",
        "specialty": "ortho",
        "tier": 3,
        "shortlist": False,
        "short_name": "Hip/knee arthroplasty history",
        "logic": "any_atom",
        "atoms": ("arthroplasty",),
    },
    {
        "feature_id": "O_T3_ACHILLES",
        "specialty": "ortho",
        "tier": 3,
        "shortlist": False,
        "short_name": "Achilles thickening/rupture",
        "logic": "any_atom",
        "atoms": ("achilles",),
    },
    {
        "feature_id": "O_T4_DUPUYTREN",
        "specialty": "ortho",
        "tier": 4,
        "shortlist": False,
        "short_name": "Dupuytren contracture",
        "logic": "any_atom",
        "atoms": ("dupuytren",),
    },
    # ===== CARDIO T1 (image + confirmed Excel #3,#6) =====
    {
        "feature_id": "C_T1_APICAL_SPARING",
        "specialty": "cardio",
        "tier": 1,
        "shortlist": True,
        "short_name": "Apical sparing / cherry-on-top",
        "logic": "any_atom",
        "atoms": ("apical_sparing",),
    },
    {
        "feature_id": "C_T1_CMR_ECV",
        "specialty": "cardio",
        "tier": 1,
        "shortlist": True,
        "short_name": "CMR expanded ECV",
        "logic": "any_atom",
        "atoms": ("cmr_ecv",),
    },
    {
        "feature_id": "C_T1_NATIVE_T1",
        "specialty": "cardio",
        "tier": 1,
        "shortlist": True,
        "short_name": "CMR elevated native T1 (Excel #3 confirmed)",
        "logic": "any_atom",
        "atoms": ("cmr_native_t1",),
    },
    {
        "feature_id": "C_T1_WALLS",
        "specialty": "cardio",
        "tier": 1,
        "shortlist": True,
        "short_name": "Unexplained LV wall thickness >12mm",
        "logic": "any_atom",
        "atoms": ("thick_walls",),
    },
    {
        "feature_id": "C_T1_DIFFUSE_LGE",
        "specialty": "cardio",
        "tier": 1,
        "shortlist": True,
        "short_name": "CMR diffuse LGE (Excel #6 confirmed)",
        "logic": "any_atom",
        "atoms": ("cmr_lge",),
    },
    {
        "feature_id": "C_T1_VOLTAGE_MISMATCH",
        "specialty": "cardio",
        "tier": 1,
        "shortlist": True,
        "short_name": "Voltage-mass mismatch",
        "logic": "any_atom",
        "atoms": ("voltage_mass_mismatch",),
    },
    {
        "feature_id": "C_T1_PYP_G23",
        "specialty": "cardio",
        "tier": 1,
        "shortlist": True,
        "short_name": "PYP/DPD/HMDP Perugini grade 2-3",
        "logic": "any_atom",
        "atoms": ("pyp_grade_2_3",),
    },
    {
        "feature_id": "C_T1_AF_JOINT_HFPEF",
        "specialty": "cardio",
        "tier": 1,
        "shortlist": True,
        "short_name": "AF + joint disorders + HFpEF",
        "logic": "composite_fn",
        "fn": "af_joint_hfpef",
    },
    # ===== CARDIO T2 (image + confirmed Excel #17 AF alone) =====
    {
        "feature_id": "C_T2_RESTRICTIVE",
        "specialty": "cardio",
        "tier": 2,
        "shortlist": True,
        "short_name": "Restrictive filling / Grade III DD",
        "logic": "any_atom",
        "atoms": ("restrictive_filling",),
    },
    {
        "feature_id": "C_T2_BIATRIAL",
        "specialty": "cardio",
        "tier": 2,
        "shortlist": True,
        "short_name": "Biatrial enlargement",
        "logic": "any_atom",
        "atoms": ("biatrial_enlargement",),
    },
    {
        "feature_id": "C_T2_HFPEF_LVH",
        "specialty": "cardio",
        "tier": 2,
        "shortlist": True,
        "short_name": "HFpEF + unexplained LVH",
        "logic": "all_atoms",
        "atoms": ("hfpef", "thick_walls"),
    },
    {
        "feature_id": "C_T2_REDUCED_GLS",
        "specialty": "cardio",
        "tier": 2,
        "shortlist": True,
        "short_name": "Reduced GLS without apical sparing",
        "logic": "composite_fn",
        "fn": "reduced_gls_no_apical",
    },
    {
        "feature_id": "C_T2_LFLG_AS",
        "specialty": "cardio",
        "tier": 2,
        "shortlist": True,
        "short_name": "Low-flow low-gradient AS / TAVR",
        "logic": "any_atom",
        "atoms": ("lflg_as", "tavr"),
    },
    {
        "feature_id": "C_T2_CONDUCTION",
        "specialty": "cardio",
        "tier": 2,
        "shortlist": True,
        "short_name": "Conduction disease",
        "logic": "any_atom",
        "atoms": ("conduction_disease",),
    },
    {
        "feature_id": "C_T2_PACEMAKER",
        "specialty": "cardio",
        "tier": 2,
        "shortlist": True,
        "short_name": "Pacemaker / ICD",
        "logic": "any_atom",
        "atoms": ("pacemaker_icd",),
    },
    {
        "feature_id": "C_T2_AF",
        "specialty": "cardio",
        "tier": 2,
        "shortlist": True,
        "short_name": "Atrial fibrillation/flutter",
        "logic": "any_atom",
        "atoms": ("af",),
    },
    {
        "feature_id": "C_T2_LOW_SVI",
        "specialty": "cardio",
        "tier": 2,
        "shortlist": True,
        "short_name": "Reduced SVI / low CO preserved EF",
        "logic": "any_atom",
        "atoms": ("low_svi",),
    },
    {
        "feature_id": "C_T2_NULLING",
        "specialty": "cardio",
        "tier": 2,
        "shortlist": True,
        "short_name": "Difficulty nulling myocardium",
        "logic": "any_atom",
        "atoms": ("difficulty_nulling",),
    },
    # Cardio T3/T4 extract
    {
        "feature_id": "C_T3_SMALL_LV",
        "specialty": "cardio",
        "tier": 3,
        "shortlist": False,
        "short_name": "Small LV cavity preserved EF",
        "logic": "any_atom",
        "atoms": ("small_lv_cavity",),
    },
    {
        "feature_id": "C_T3_TROPONIN",
        "specialty": "cardio",
        "tier": 3,
        "shortlist": False,
        "short_name": "Persistent troponin elevation",
        "logic": "any_atom",
        "atoms": ("troponin_elevated",),
    },
    {
        "feature_id": "C_T3_NTPROBNP",
        "specialty": "cardio",
        "tier": 3,
        "shortlist": False,
        "short_name": "Elevated NT-proBNP",
        "logic": "any_atom",
        "atoms": ("ntprobnp_elevated",),
    },
    {
        "feature_id": "C_T4_PSEUDO_MI",
        "specialty": "cardio",
        "tier": 4,
        "shortlist": False,
        "short_name": "Pseudo-infarction Q waves",
        "logic": "any_atom",
        "atoms": ("pseudo_infarct",),
    },
    {
        "feature_id": "C_T4_EFFUSION",
        "specialty": "cardio",
        "tier": 4,
        "shortlist": False,
        "short_name": "Small pericardial effusion",
        "logic": "any_atom",
        "atoms": ("pericardial_effusion",),
    },
    {
        "feature_id": "C_T4_IAS",
        "specialty": "cardio",
        "tier": 4,
        "shortlist": False,
        "short_name": "Thickened interatrial septum",
        "logic": "any_atom",
        "atoms": ("thickened_ias",),
    },
    {
        "feature_id": "C_T4_RV",
        "specialty": "cardio",
        "tier": 4,
        "shortlist": False,
        "short_name": "RV wall thickening",
        "logic": "any_atom",
        "atoms": ("rv_wall_thick",),
    },
    {
        "feature_id": "C_T4_VALVE_THICK",
        "specialty": "cardio",
        "tier": 4,
        "shortlist": False,
        "short_name": "Valve thickening",
        "logic": "any_atom",
        "atoms": ("valve_thickening",),
    },
    {
        "feature_id": "C_T4_GRANULAR",
        "specialty": "cardio",
        "tier": 4,
        "shortlist": False,
        "short_name": "Granular/speckled myocardium",
        "logic": "any_atom",
        "atoms": ("granular_myocardium",),
    },
    # ===== NEURO T1 (image) =====
    {
        "feature_id": "N_T1_CIDP_FAIL",
        "specialty": "neuro",
        "tier": 1,
        "shortlist": True,
        "short_name": "CIDP + failed IVIG/steroids",
        "logic": "all_atoms",
        "atoms": ("cidp", "cidp_failed"),
    },
    {
        "feature_id": "N_T1_PN_BCT",
        "specialty": "neuro",
        "tier": 1,
        "shortlist": True,
        "short_name": "Neuropathy + bilateral CTS",
        "logic": "all_atoms",
        "atoms": ("polyneuropathy", "cts_bilateral"),
    },
    {
        "feature_id": "N_T1_SUSPECT_ATTR",
        "specialty": "neuro",
        "tier": 1,
        "shortlist": True,
        "short_name": "Neurologist suspects amyloid/ATTR",
        "logic": "any_atom",
        "atoms": ("neuro_suspects_attr",),
    },
    # ===== NEURO T2 (image) =====
    {
        "feature_id": "N_T2_SFN",
        "specialty": "neuro",
        "tier": 2,
        "shortlist": True,
        "short_name": "Small-fiber neuropathy",
        "logic": "any_atom",
        "atoms": ("sfn",),
    },
    {
        "feature_id": "N_T2_OH",
        "specialty": "neuro",
        "tier": 2,
        "shortlist": True,
        "short_name": "Orthostatic hypotension",
        "logic": "any_atom",
        "atoms": ("orthostatic",),
    },
    {
        "feature_id": "N_T2_PN_CTS",
        "specialty": "neuro",
        "tier": 2,
        "shortlist": True,
        "short_name": "Neuropathy + CTS",
        "logic": "all_atoms",
        "atoms": ("polyneuropathy", "cts_any"),
    },
    {
        "feature_id": "N_T2_LENGTH_DEP",
        "specialty": "neuro",
        "tier": 2,
        "shortlist": True,
        "short_name": "Length-dependent axonal PN",
        # ICD G62/G60 kept on length_dependent atom + Excel length-dep keywords; EMG axonal also counts
        "logic": "any_atom",
        "atoms": ("length_dependent", "emg_axonal"),
    },
    {
        "feature_id": "N_T2_IENFD",
        "specialty": "neuro",
        "tier": 2,
        "shortlist": True,
        "short_name": "Reduced IENFD",
        "logic": "any_atom",
        "atoms": ("ienfd",),
    },
    {
        "feature_id": "N_T2_EMG_AXONAL",
        "specialty": "neuro",
        "tier": 2,
        "shortlist": True,
        "short_name": "Axonal pattern EMG/NCS",
        "logic": "any_atom",
        "atoms": ("emg_axonal",),
    },
    {
        "feature_id": "N_T2_EMG_MIXED",
        "specialty": "neuro",
        "tier": 2,
        "shortlist": True,
        "short_name": "Demyelinating + axonal loss",
        "logic": "any_atom",
        "atoms": ("emg_mixed",),
    },
    {
        "feature_id": "N_T2_PROGRESSIVE",
        "specialty": "neuro",
        "tier": 2,
        "shortlist": True,
        "short_name": "Progressive neuropathy serial visits",
        "logic": "any_atom",
        "atoms": ("progressive_neuropathy",),
    },
    # Neuro T3 extract
    {
        "feature_id": "N_T3_PAIN",
        "specialty": "neuro",
        "tier": 3,
        "shortlist": False,
        "short_name": "Neuropathic pain",
        "logic": "any_atom",
        "atoms": ("neuropathic_pain",),
    },
]

# Excel Cardio T1 NOT on image and NOT approved - kept here for reporting only
PENDING_CONFIRMATION: List[Dict[str, Any]] = [
    {
        "excel_sheet": "Agent2_Cardiology",
        "excel_n": 5,
        "tier": 1,
        "specialty": "cardio",
        "sig": "Explicit cardiologist suspicion of infiltrative cardiomyopathy / amyloidosis",
        "status": "REJECTED_BY_USER",
        "note": "User said No - do not add to shortlist Tier 1",
    },
    {
        "excel_sheet": "Agent2_Cardiology",
        "excel_n": 9,
        "tier": 2,
        "specialty": "cardio",
        "sig": "Progressive wall thickening on serial echocardiograms",
        "status": "HOLD_NOT_ON_IMAGE",
        "note": "Excel T2 not on Cardio sticky-note - report; wait for confirmation",
    },
    {
        "excel_sheet": "Agent2_Cardiology",
        "excel_n": 17,
        "tier": 2,
        "specialty": "cardio",
        "sig": "Atrial fibrillation/flutter (alone)",
        "status": "APPROVED_BY_USER",
        "note": "Added as Cardio Tier 2. AF+joints+HFpEF is Cardio Tier 1 (user correction).",
    },
    {
        "excel_sheet": "Agent1_Orthopedic",
        "excel_n": 3,
        "tier": 1,
        "specialty": "ortho",
        "sig": "Incidental Congo red / apple-green birefringence on unrelated ortho biopsy",
        "status": "HOLD_NOT_ON_IMAGE",
        "note": "Excel Ortho T1 not on Ortho sticky-note - report; wait for confirmation",
    },
]

# ---------------------------------------------------------------------------
# Snowflake filter helpers (session temps - shrink before to_pandas)
# ---------------------------------------------------------------------------

def all_icd_prefixes() -> Tuple[str, ...]:
    prefs = []
    for a in ATOMS.values():
        prefs.extend(a.get("icd_prefixes") or ())
    # unique preserve order
    seen = set()
    out = []
    for p in prefs:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return tuple(out)


def all_cpt_exact() -> Tuple[str, ...]:
    codes = []
    for a in ATOMS.values():
        codes.extend(a.get("cpt_exact") or ())
    return tuple(sorted(set(codes)))


def all_nlp_patterns() -> Tuple[str, ...]:
    pats = []
    for a in ATOMS.values():
        pats.extend(a.get("nlp") or ())
    # unique
    seen = set()
    out = []
    for p in pats:
        pl = p.lower()
        if pl not in seen:
            seen.add(pl)
            out.append(p)
    return tuple(out)


def snowflake_code_filter_sql(code_col: str = "CODE_VALUE") -> str:
    """SQL boolean expression: code matches any ICD prefix or CPT exact."""
    parts = []
    for p in all_icd_prefixes():
        pref = p.replace("'", "''")
        parts.append(f"STARTSWITH(UPPER(REPLACE({code_col},'.','')), '{pref.upper().replace('.','')}')")
        parts.append(f"STARTSWITH(UPPER({code_col}), '{pref.upper()}')")
    for c in all_cpt_exact():
        parts.append(f"UPPER({code_col}) = '{c}'")
    if not parts:
        return "FALSE"
    return "(" + " OR ".join(parts) + ")"


def snowflake_lab_filter_sql(*text_cols: str) -> str:
    cols = text_cols or ("OBSERVATION_IDENTIFIER", "OBSERVATION_VALUE", "LAB_RESULT_NOTE")
    pats = all_nlp_patterns()
    parts = []
    for col in cols:
        for p in pats:
            esc = p.lower().replace("'", "''")
            parts.append(f"CONTAINS(LOWER(COALESCE({col},'')), '{esc}')")
    if not parts:
        return "FALSE"
    return "(" + " OR ".join(parts) + ")"

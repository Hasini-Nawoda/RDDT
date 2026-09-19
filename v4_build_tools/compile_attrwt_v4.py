"""Build the clean ATTRwt V4 package from the audited disposition contract.

This is a build-time tool.  It is intentionally outside ``v4/``; the generated
JSON under ``v4/config`` is the only deployable artifact.  Existing shared
ATTRv atoms are referenced by ID and are never copied into a WT namespace.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "v4" / "config" / "shared" / "atoms"
WT = ROOT / "v4" / "config" / "phenotypes" / "ATTRWT"


def atom(atom_id: str, preferred_name: str, specialty: str, terms: list[str], *, meaning: str | None = None, guard: str | None = None) -> dict[str, Any]:
    return {
        "atom_id": atom_id,
        "preferred_name": preferred_name,
        "stage": "PRETEST_SIGNAL",
        "experiencer": "PATIENT",
        "clinical_meaning": meaning or preferred_name,
        "source_specialty": specialty,
        "context_guard": guard or "Use only when the configured clinical context and evidence qualification support the finding.",
        "extraction": {
            "codes": {},
            "nlp_terms": [{"value": term, "can_fire_atom_alone": False} for term in terms],
        },
    }


def build_shared_atoms() -> None:
    new: dict[str, list[dict[str, Any]]] = {
        "CARDIOLOGY.json": [
            atom("apical_sparing", "Relative apical sparing on global longitudinal strain", "CARDIOLOGY", ["relative apical sparing", "apical sparing", "cherry on top pattern"], guard="Subtype-neutral cardiac amyloidosis context; do not distinguish ATTRwt from AL or ATTRv."),
            atom("as_valve", "Severe aortic valve stenosis", "CARDIOLOGY", ["severe aortic stenosis", "severe AS", "aortic valve stenosis"], guard="Severe AS is contextual; only low-flow/low-gradient AS is the configured ATTR-enriched signal."),
            atom("asymmetric_septal_hypertrophy", "Asymmetric or basal septal hypertrophy", "CARDIOLOGY", ["asymmetric septal hypertrophy", "basal septal hypertrophy", "asymmetric LV hypertrophy"]),
            atom("bnp_result", "BNP or NT-proBNP result", "CARDIOLOGY", ["BNP", "NT-proBNP", "B-type natriuretic peptide"], guard="Research/comparative context only; never independently triggers ATTRwt."),
            atom("heart_failure", "Heart failure", "CARDIOLOGY", ["heart failure", "congestive heart failure", "cardiac failure"], guard="Generic heart failure requires the configured unexplained-HF rule and competing-cause blocker."),
            atom("hypertension", "Hypertension history", "CARDIOLOGY", ["hypertension", "high blood pressure", "hypertensive history"], guard="Context for longitudinal BP decline; hypertension alone is not ATTR evidence."),
            atom("hypertrophic_cardiomyopathy", "Hypertrophic cardiomyopathy phenotype", "CARDIOLOGY", ["hypertrophic cardiomyopathy", "HCM phenotype", "hypertrophic obstructive cardiomyopathy"], guard="Requires late-onset/no convincing sarcomeric explanation in WT13 logic."),
            atom("low_ecg_voltage", "Low ECG voltage", "CARDIOLOGY", ["low voltage ECG", "low QRS voltage", "low voltage on ECG"], guard="Normal voltage is not exclusionary; prior MI is a competing explanation for pseudoinfarction."),
            atom("lv_mass_index_result", "Left-ventricular mass index result", "CARDIOLOGY", ["LV mass index", "left ventricular mass index", "LVMI"], guard="Measurement/comparative context; never a standalone trigger."),
            atom("lv_relative_wall_thickness", "Increased relative LV wall thickness", "CARDIOLOGY", ["relative wall thickness", "increased relative wall thickness", "high relative wall thickness"]),
            atom("lv_wall_measurement", "Left-ventricular wall-thickness measurement", "CARDIOLOGY", ["LV wall thickness", "left ventricular wall thickness", "interventricular septal thickness"]),
            atom("lvef_result", "Left-ventricular ejection fraction result", "CARDIOLOGY", ["LVEF", "left ventricular ejection fraction", "ejection fraction"], guard="Measurement context for research-only MCF; never a standalone trigger."),
            atom("myocardial_bone_tracer_uptake", "Myocardial uptake on bone-avid scintigraphy", "CARDIOLOGY", ["myocardial tracer uptake", "cardiac uptake on bone scan", "bone scintigraphy myocardial uptake"], guard="Routing clue only; provenance and AL exclusion are mandatory."),
            atom("pacemaker_implantation", "Pacemaker implantation", "CARDIOLOGY", ["pacemaker implantation", "pacemaker inserted", "pacemaker placement"], guard="Deduplicate with pacemaker presence; device history is corroborating conduction evidence."),
            atom("pseudo_infarct", "Pseudoinfarction pattern", "CARDIOLOGY", ["pseudoinfarction pattern", "pseudo infarct pattern", "pathologic Q waves without infarction"]),
            atom("reduced_gls", "Reduced global longitudinal strain", "CARDIOLOGY", ["reduced GLS", "abnormal global longitudinal strain", "low global longitudinal strain"], guard="Subtype-neutral cardiac amyloidosis context."),
            atom("small_lv_cavity", "Small or non-dilated LV cavity", "CARDIOLOGY", ["small LV cavity", "small left ventricular cavity", "non-dilated LV"]),
            atom("voltage_mass_mismatch", "Voltage-to-mass discordance", "CARDIOLOGY", ["voltage mass discordance", "voltage-mass mismatch", "low voltage relative to LV mass"]),
            atom("aortic_valve_replacement", "Aortic valve replacement history", "CARDIOLOGY", ["aortic valve replacement", "AVR", "TAVR", "transcatheter aortic valve replacement"], guard="Procedure history is contextual and does not replace the configured AS finding."),
        ],
        "ORTHOPEDICS_MSK.json": [
            atom("arthroplasty", "Hip or knee arthroplasty history", "ORTHOPEDICS_MSK", ["hip arthroplasty", "knee arthroplasty", "joint replacement", "total hip replacement", "total knee replacement"]),
            atom("carpal_tunnel_release", "Carpal tunnel release procedure", "ORTHOPEDICS_MSK", ["carpal tunnel release", "carpal tunnel decompression", "median nerve release"], guard="Procedure-only evidence cannot independently establish WT02 without bilateral/recurrent/persistent CTS context."),
            atom("ligamentum_flavum_thickening", "Thickened ligamentum flavum", "ORTHOPEDICS_MSK", ["thickened ligamentum flavum", "ligamentum flavum hypertrophy", "ligamentum flavum thickening"], guard="Local ligament amyloid does not establish systemic ATTRwt; use only inside the WT05 composite."),
            atom("lumbar_decompression", "Lumbar decompression or laminectomy history", "ORTHOPEDICS_MSK", ["lumbar decompression", "lumbar laminectomy", "spinal decompression surgery"]),
            atom("shoulder_disorder", "Shoulder disorder", "ORTHOPEDICS_MSK", ["shoulder disorder", "shoulder pathology", "shoulder tendon disease"], guard="Context-only corroborating orthopedic evidence; never fires WT08 alone."),
            atom("wt03_traumatic_rupture", "Traumatic distal biceps rupture", "ORTHOPEDICS_MSK", ["traumatic biceps rupture", "traumatic distal biceps tear", "biceps rupture after trauma"], guard="Competing mechanism blocker; never positive ATTR support."),
            atom("wt06_osteoarthritis", "Osteoarthritis explaining arthroplasty", "ORTHOPEDICS_MSK", ["osteoarthritis", "degenerative joint disease", "advanced osteoarthritis"], guard="Competing explanation blocker for the WT06 arthroplasty composite."),
        ],
        "NEUROLOGY.json": [
            atom("mild_sensory_polyneuropathy", "Mild-to-moderate length-dependent sensory polyneuropathy", "NEUROLOGY", ["mild sensory polyneuropathy", "length-dependent sensory neuropathy", "mild distal sensory neuropathy"], guard="Compatibility/false-negative guardrail for ATTRwt; prominent painful/autonomic/hereditary patterns route toward ATTRv review."),
            atom("wt21_competing_hearing_loss", "Competing presbycusis, noise, or ototoxic hearing loss", "NEUROLOGY", ["presbycusis", "noise-induced hearing loss", "ototoxic hearing loss"], guard="Competing explanation blocker for the weak WT21 cluster enhancer."),
        ],
        "MULTISPECIALTY.json": [
            atom("age_excessive_snhl", "Bilateral sensorineural hearing loss disproportionate to age", "MULTISPECIALTY", ["bilateral sensorineural hearing loss", "age-excessive hearing loss", "hearing loss disproportionate to age"], guard="Weak cluster enhancer only; requires context and competing-cause review."),
            atom("egfr_result", "Estimated glomerular filtration rate result", "MULTISPECIALTY", ["eGFR", "estimated GFR", "glomerular filtration rate"], guard="Interpretive context for renal reference of free-light-chain results; not positive ATTR evidence."),
            atom("hypoalbuminemia", "Hypoalbuminemia", "MULTISPECIALTY", ["hypoalbuminemia", "low serum albumin", "low albumin"], guard="AL/renal differential context; never establishes ATTRwt."),
            atom("saa_result", "Serum amyloid A result", "MULTISPECIALTY", ["serum amyloid A", "SAA", "SAA result"], guard="AA differential context; requires the configured chronic inflammatory driver and proteinuric phenotype."),
            atom("crp_result", "C-reactive protein result", "MULTISPECIALTY", ["C-reactive protein", "CRP", "CRP result"], guard="AA differential context only."),
            atom("esr_result", "Erythrocyte sedimentation rate result", "MULTISPECIALTY", ["erythrocyte sedimentation rate", "ESR", "ESR result"], guard="AA differential context only."),
            atom("reduced_mcf", "Reduced myocardial contraction fraction", "MULTISPECIALTY", ["reduced myocardial contraction fraction", "reduced MCF", "myocardial contraction fraction"], guard="Research/corroborating feature only; never a clinical trigger."),
            atom("pyp_grade_2_3", "Grade 2 or 3 PYP/DPD/HMDP myocardial uptake", "MULTISPECIALTY", ["grade 2 PYP", "grade 3 PYP", "grade 2 bone scan uptake", "grade 3 bone scan uptake"], guard="Post-test/diagnostic evidence; not a pre-test trigger."),
            atom("elevated_uric_acid", "Elevated uric acid", "MULTISPECIALTY", ["elevated uric acid", "hyperuricemia", "high uric acid"], guard="WT30 do-not-trigger feature."),
            atom("wt09_competing_hf_cause", "Competing explanation for heart failure", "MULTISPECIALTY", ["ischemic heart failure", "hypertensive heart disease", "non-amyloid heart failure cause"], guard="Block WT09 only when clearly established and adequately explanatory."),
            atom("wt11_competing_af_cause", "Competing explanation for atrial fibrillation", "MULTISPECIALTY", ["AF due to valvular disease", "atrial fibrillation due to hyperthyroidism", "secondary atrial fibrillation"], guard="Block WT11 only when clearly established and adequately explanatory."),
            atom("wt12_competing_conduction_cause", "Competing explanation for conduction disease", "MULTISPECIALTY", ["conduction disease due to ischemia", "drug-induced AV block", "secondary conduction disease"], guard="Block WT12 only when clearly established and adequately explanatory."),
            atom("wt13_sarcomeric_hcm", "Convincing sarcomeric or hypertensive HCM explanation", "MULTISPECIALTY", ["sarcomeric HCM", "pathogenic sarcomere variant", "hypertensive remodeling explains hypertrophy"], guard="Block WT13 only when the alternate explanation is convincing."),
            atom("wt14_as_explains_lvh", "Aortic stenosis explaining LV hypertrophy", "MULTISPECIALTY", ["aortic stenosis explains LVH", "LVH due to aortic stenosis", "AS explains hypertrophy"], guard="Competing explanation check for WT14."),
            atom("wt16_prior_mi", "Prior myocardial infarction", "MULTISPECIALTY", ["prior myocardial infarction", "old MI", "history of myocardial infarction"], guard="Competing explanation for Q waves/pseudoinfarction; never positive support."),
            atom("wt18_competing_hypotension", "Competing explanation for falling blood pressure", "MULTISPECIALTY", ["dehydration causing hypotension", "weight loss causing low blood pressure", "frailty-related hypotension"], guard="Block WT18 only when clearly established and explanatory."),
        ],
        "HEMATOLOGY.json": [
            atom("plasma_cell_dyscrasia", "Plasma-cell dyscrasia", "HEMATOLOGY", ["plasma cell dyscrasia", "plasma-cell disorder", "multiple myeloma"], guard="AL differential routing; does not by itself label AL or negate ATTR."),
        ],
        "NEPHROLOGY.json": [],
        "RHEUM_INFLAMMATORY.json": [],
    }
    # Preserve all existing shared atoms and append only genuinely WT-specific rows.
    for filename, additions in new.items():
        path = SHARED / filename
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("atoms", [])
        existing = {row["atom_id"] for row in rows}
        for row in additions:
            if row["atom_id"] not in existing:
                rows.append(row)
        data["atoms"] = sorted(rows, key=lambda row: row["atom_id"])
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def a(atom_id: str, *, req: str | None = None, role: str = "SUPPORT", experiencer: str = "PATIENT") -> dict[str, Any]:
    item = {"type": "atom", "id": atom_id, "role": role, "experiencer": experiencer}
    if req:
        item["required_attributes"] = req
    return item


def s(signal_id: str, *, role: str = "SUPPORT") -> dict[str, Any]:
    return {"type": "signal", "id": signal_id, "role": role, "experiencer": "PATIENT"}


def g(operator: str, members: list[dict[str, Any]], *, minimum_count: int | None = None, independent: bool = False, linkage_type: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"operator": operator, "members": members}
    if minimum_count is not None:
        out["minimum_count"] = minimum_count
    if independent:
        out["require_independent_lineage"] = True
    if linkage_type:
        out["linkage_type"] = linkage_type
    return out


def rule(signal_id: str, root: dict[str, Any], *, blockers: list[dict[str, Any]] | None = None, runtime: str = "EXECUTABLE") -> dict[str, Any]:
    row: dict[str, Any] = {
        "signal_id": signal_id,
        "enabled": True,
        "runtime_executability": runtime,
        "missing_data_policy": "UNKNOWN_DOES_NOT_SATISFY_AND_DOES_NOT_NEGATE",
        "truth_model": "TRUE_FALSE_UNKNOWN",
        "outcome": "SIGNAL_ESTABLISHED",
        "blocker_policy": "APPLY_SIGNAL_BLOCKERS_AFTER_SUPPORT_RULE",
        "rule": root,
    }
    if blockers:
        row["blockers"] = blockers
    return row


def build_phenotype_package() -> None:
    WT.mkdir(parents=True, exist_ok=True)

    signals: list[dict[str, Any]] = []
    def sig(sid: str, feature: str, entity: str, action: str, algorithm: str, gate: str, specialty: str, subdomain: str, bucket: str, tier: int | None, dedup: str, runtime: str = "EXECUTABLE", note: str | None = None) -> None:
        signals.append({
            "signal_id": sid,
            "clinical_feature": feature,
            "entity_type": "SIGNAL" if entity == "COMPOSITE_RULE" else entity,
            "source_entity_type": entity,
            "config_action": action,
            "algorithm_role": algorithm,
            "gate_role": gate,
            "enabled": True,
            "source_type": "DERIVED" if entity in {"COMPOSITE_RULE", "GUARDRAIL", "DO_NOT_USE"} else "CLINICAL",
            "source_specialty": specialty,
            "source_subdomain": subdomain,
            "reasoning_bucket": bucket,
            "bucket_class": "INDEPENDENT" if bucket in {"ORTHO", "CARDIO"} else "CONTEXT",
            "tier": tier,
            "canonical_dedup_group": dedup,
            "evidence_stage": "PRETEST_SIGNAL",
            "runtime_executability": runtime,
            "evidence_mode": "DOCUMENTED_ASSERTION" if runtime == "EXECUTABLE" else None,
            "clinical_note": note,
        })

    sig("WT01", "Orthopedic/tenosynovial prodrome followed years later by otherwise unexplained cardiac disease", "COMPOSITE_RULE", "POSITIVE_SIGNAL", "COMPOSITE_RULE", "CONTEXT_ONLY", "MULTISPECIALTY", "TEMPORAL_TRAJECTORY", "SYSTEMIC_CONTEXT", 1, "WT01_TRAJECTORY", note="Cross-bucket temporal composite; orthopedic evidence must precede cardiac evidence and does not create a second independent bucket.")
    sig("WT02", "Bilateral and/or recurrent carpal tunnel syndrome", "SIGNAL", "POSITIVE_SIGNAL", "GATE_EVIDENCE", "ELIGIBLE", "ORTHOPEDICS", "TENOSYNOVIAL", "ORTHO", 1, "WT02_CTS")
    sig("WT03", "Spontaneous or trivial-trauma distal biceps tendon rupture / Popeye sign", "SIGNAL", "POSITIVE_SIGNAL", "GATE_EVIDENCE", "ELIGIBLE", "ORTHOPEDICS", "TENDON", "ORTHO", 1, "WT03_BICEPS")
    sig("WT04", "Multiple orthopedic red flags across different tissues/procedures", "COMPOSITE_RULE", "POSITIVE_SIGNAL", "COMPOSITE_RULE", "ELIGIBLE", "ORTHOPEDICS", "MULTI_TISSUE", "ORTHO", 1, "WT04_ORTHO_CLUSTER")
    sig("WT05", "Lumbar spinal stenosis/decompression with thickened ligamentum flavum and another ATTR clue", "COMPOSITE_RULE", "POSITIVE_SIGNAL", "COMPOSITE_RULE", "ELIGIBLE", "ORTHOPEDICS", "SPINE", "ORTHO", 2, "WT05_SPINE")
    sig("WT06", "Hip or knee arthroplasty years before cardiac disease, especially multiple/bilateral replacements", "COMPOSITE_RULE", "POSITIVE_SIGNAL", "COMPOSITE_RULE", "ELIGIBLE", "ORTHOPEDICS", "LARGE_JOINT", "ORTHO", 2, "WT06_ARTHROPLASTY")
    sig("WT07", "Trigger finger / digit-trigger release, especially multiple digits or combined with CTS", "COMPOSITE_RULE", "POSITIVE_SIGNAL", "COMPOSITE_RULE", "ELIGIBLE", "ORTHOPEDICS", "TENOSYNOVIAL", "ORTHO", 2, "WT07_TRIGGER")
    sig("WT08", "Rotator cuff tear/repair or shoulder pathology as part of an orthopedic cluster", "SIGNAL", "POSITIVE_SIGNAL", "CONTEXT_EVIDENCE", "CONTEXT_ONLY", "ORTHOPEDICS", "SHOULDER", "ORTHO", 3, "WT08_SHOULDER", note="Corroborating context only; never establishes WT08 alone.")
    sig("WT09", "Unexplained HFpEF / heart failure in an older adult", "SIGNAL", "POSITIVE_SIGNAL", "GATE_EVIDENCE", "ELIGIBLE", "CARDIOLOGY", "HEART_FAILURE", "CARDIO", 2, "WT09_HEART_FAILURE")
    sig("WT10", "Unexplained LV wall thickening / increased relative wall thickness / non-dilated LV", "SIGNAL", "POSITIVE_SIGNAL", "GATE_EVIDENCE", "ELIGIBLE", "CARDIOLOGY", "STRUCTURE", "CARDIO", 1, "WT10_WALL_GEOMETRY")
    sig("WT11", "Atrial fibrillation/flutter with LV thickening or orthopedic ATTR clues", "COMPOSITE_RULE", "POSITIVE_SIGNAL", "COMPOSITE_RULE", "ELIGIBLE", "CARDIOLOGY", "ARRHYTHMIA", "CARDIO", 2, "WT11_AF")
    sig("WT12", "Conduction disease and/or pacemaker implantation", "SIGNAL", "POSITIVE_SIGNAL", "GATE_EVIDENCE", "ELIGIBLE", "CARDIOLOGY", "CONDUCTION", "CARDIO", 2, "WT12_CONDUCTION")
    sig("WT13", "Late-onset HCM phenotype without a convincing sarcomeric explanation", "COMPOSITE_RULE", "POSITIVE_SIGNAL", "COMPOSITE_RULE", "ELIGIBLE", "CARDIOLOGY", "HCM_PHENOCOPY", "CARDIO", 2, "WT13_HCM")
    sig("WT14", "Severe aortic stenosis, particularly low-flow/low-gradient AS", "SIGNAL", "POSITIVE_SIGNAL", "GATE_EVIDENCE", "ELIGIBLE", "CARDIOLOGY", "AORTIC_STENOSIS", "CARDIO", 2, "WT14_AS")
    sig("WT15", "Relative apical sparing of longitudinal strain", "SIGNAL", "POSITIVE_SIGNAL", "CONTEXT_EVIDENCE", "CONTEXT_ONLY", "CARDIOLOGY", "STRAIN", "CARDIO", 3, "WT15_STRAIN", note="Subtype-neutral cardiac amyloidosis context.")
    sig("WT16", "Voltage-to-mass discordance and/or pseudoinfarction pattern", "SIGNAL", "POSITIVE_SIGNAL", "GATE_EVIDENCE", "ELIGIBLE", "CARDIOLOGY", "ECG", "CARDIO", 2, "WT16_ECG")
    sig("WT17", "Reduced myocardial contraction fraction despite preserved or mildly reduced LVEF", "DO_NOT_USE", "DO_NOT_TRIGGER", "RESEARCH_CONTEXT", "NO_TRIGGER", "CARDIOLOGY", "FUNCTION", "CARDIO", 3, "WT17_MCF", runtime="NON_FIRING")
    sig("WT18", "Long-standing hypertension becoming unexpectedly normal/low or new medication intolerance", "COMPOSITE_RULE", "POSITIVE_SIGNAL", "COMPOSITE_RULE", "ELIGIBLE", "CARDIOLOGY", "LONGITUDINAL_BP", "CARDIO", 2, "WT18_BP")
    sig("WT19", "Low BNP-to-LV mass index ratio relative to AL", "DO_NOT_USE", "DO_NOT_TRIGGER", "RESEARCH_CONTEXT", "NO_TRIGGER", "CARDIOLOGY", "BIOMARKER_RATIO", "CARDIO", 4, "WT19_BNP_LVMI", runtime="NON_FIRING")
    sig("WT20", "Incidental myocardial uptake on bone-avid scintigraphy for a non-amyloidosis indication", "GUARDRAIL", "DIFFERENTIAL_ROUTE_GUARDRAIL", "GUARDRAIL", "NO_TRIGGER", "NUCLEAR_MEDICINE", "BONE_SCINTIGRAPHY", "CARDIO", None, "WT20_TRACER", note="Routing clue only; provenance and AL exclusion are mandatory.")
    sig("WT21", "Bilateral sensorineural hearing loss greater than expected for age", "SIGNAL", "POSITIVE_SIGNAL", "CONTEXT_EVIDENCE", "CONTEXT_ONLY", "AUDIOLOGY", "HEARING", "SYSTEMIC_CONTEXT", 3, "WT21_HEARING", note="Weak cluster enhancer only; never establishes WT21 alone.")
    sig("WT22", "Mild-to-moderate length-dependent sensory polyneuropathy in an ATTRwt-like phenotype", "GUARDRAIL", "FALSE_NEGATIVE_GUARDRAIL", "GUARDRAIL", "NO_TRIGGER", "NEUROLOGY", "PERIPHERAL_NEUROPATHY", "NEURO", None, "WT22_MILD_NEUROPATHY")
    sig("WT23", "Age/male prior-probability context", "GUARDRAIL", "DO_NOT_TRIGGER", "INPUT_CONTEXT", "NO_TRIGGER", "GENERAL_MEDICINE", "DEMOGRAPHIC", "SYSTEMIC_CONTEXT", None, "WT23_DEMOGRAPHIC", runtime="NON_EXECUTABLE")
    sig("WT24", "Sex-aware low-wall-thickness false-negative guardrail", "GUARDRAIL", "FALSE_NEGATIVE_GUARDRAIL", "GUARDRAIL", "NO_TRIGGER", "CARDIOLOGY", "SEX_AWARE", "CARDIO", None, "WT24_SEX_WALL")
    sig("WT25", "Monoclonal/plasma-cell evidence routes toward AL evaluation", "GUARDRAIL", "DIFFERENTIAL_ROUTE_GUARDRAIL", "GUARDRAIL", "NO_TRIGGER", "HEMATOLOGY", "AL_DIFFERENTIAL", "LAB_CONTEXT", None, "WT25_AL")
    sig("WT26", "CKD-aware interpretation of free-light-chain and renal findings", "GUARDRAIL", "DIFFERENTIAL_ROUTE_GUARDRAIL", "GUARDRAIL", "NO_TRIGGER", "NEPHROLOGY", "RENAL_AL", "RENAL", None, "WT26_RENAL")
    sig("WT27", "AL counter-evidence with plasma-cell/renal phenotype", "GUARDRAIL", "DIFFERENTIAL_ROUTE_GUARDRAIL", "GUARDRAIL", "NO_TRIGGER", "HEMATOLOGY", "AL_DIFFERENTIAL", "LAB_CONTEXT", None, "WT27_AL_COUNTER")
    sig("WT28", "ATTRv counter-evidence / hereditary or neuropathic pattern", "GUARDRAIL", "DIFFERENTIAL_ROUTE_GUARDRAIL", "GUARDRAIL", "NO_TRIGGER", "GENETICS", "ATTRV_DIFFERENTIAL", "HEREDITARY", None, "WT28_ATTRV_COUNTER")
    sig("WT29", "AA counter-evidence with chronic inflammatory driver and proteinuric phenotype", "GUARDRAIL", "DIFFERENTIAL_ROUTE_GUARDRAIL", "GUARDRAIL", "NO_TRIGGER", "RHEUM_INFLAMMATORY", "AA_DIFFERENTIAL", "LAB_CONTEXT", None, "WT29_AA_COUNTER")
    sig("WT30", "Hyperuricemia research/competing feature", "DO_NOT_USE", "DO_NOT_TRIGGER", "RESEARCH_CONTEXT", "NO_TRIGGER", "GENERAL_MEDICINE", "LAB_CONTEXT", "LAB_CONTEXT", None, "WT30_URIC_ACID", runtime="NON_FIRING")

    rules: list[dict[str, Any]] = [
        rule("WT01", g("INDEPENDENT_ALL", [g("ANY", [s("WT02"), s("WT03"), s("WT04"), s("WT05"), s("WT06"), s("WT07"), s("WT08")]), g("ANY", [s("WT09"), s("WT10"), s("WT11"), s("WT12"), s("WT14"), s("WT16")])], independent=True)),
        rule("WT02", g("ANY", [a("cts_bilateral"), a("cts_recurrent"), a("cts_persistent_after_release")])),
        rule("WT03", g("ALL", [a("biceps_rupture", req="spontaneous_or_trivial_trauma=True")]), blockers=[{"blocker_id": "WT03_B01", "atom_id": "wt03_traumatic_rupture", "action": "BLOCK_SIGNAL", "required_attributes": "clearly_established=True"}]),
        rule("WT04", g("AT_LEAST", [s("WT02"), s("WT03"), s("WT05"), s("WT06"), s("WT07"), s("WT08")], minimum_count=2, independent=True)),
        rule("WT05", g("ALL", [g("ALL", [a("lumbar_stenosis"), a("lumbar_decompression"), a("ligamentum_flavum_thickening")], independent=True), g("ANY", [s("WT02"), s("WT03"), s("WT09"), s("WT10"), s("WT12"), s("WT14"), s("WT16")])], independent=True)),
        rule("WT06", g("ALL", [a("arthroplasty", req="multiple_or_bilateral=True"), g("ANY", [s("WT02"), s("WT03"), s("WT05"), s("WT09"), s("WT10"), s("WT12"), s("WT14")])], independent=True), blockers=[{"blocker_id": "WT06_B01", "atom_id": "wt06_osteoarthritis", "action": "BLOCK_SIGNAL", "required_attributes": "clearly_established=True, adequately_explains_arthroplasty=True"}]),
        rule("WT07", g("ANY", [a("trigger_finger", req="multiple_digits=True"), g("ALL", [a("trigger_finger"), s("WT02")], independent=True)])),
        rule("WT08", g("ANY", [a("rotator_cuff"), a("shoulder_disorder")])),
        rule("WT09", g("ANY", [a("hfpef"), a("heart_failure")]), blockers=[{"blocker_id": "WT09_B01", "atom_id": "wt09_competing_hf_cause", "action": "BLOCK_SIGNAL", "required_attributes": "clearly_established=True, adequately_explains_heart_failure=True"}]),
        rule("WT10", g("ANY", [a("thick_walls"), a("lv_relative_wall_thickness"), a("lv_wall_measurement", req="unexplained=True"), a("small_lv_cavity")]), blockers=[{"blocker_id": "WT10_B01", "atom_id": "v24_competing_lvh", "action": "BLOCK_SIGNAL", "required_attributes": "clearly_established=True, adequately_explains_lvh=True"}]),
        rule("WT11", g("ALL", [a("af"), g("ANY", [s("WT10"), s("WT02"), s("WT03"), s("WT05"), s("WT06"), s("WT07")], independent=True)], independent=True), blockers=[{"blocker_id": "WT11_B01", "atom_id": "wt11_competing_af_cause", "action": "BLOCK_SIGNAL", "required_attributes": "clearly_established=True, adequately_explains_af=True"}]),
        rule("WT12", g("ANY", [a("conduction_disease"), a("pacemaker_presence"), a("pacemaker_implantation")]), blockers=[{"blocker_id": "WT12_B01", "atom_id": "wt12_competing_conduction_cause", "action": "BLOCK_SIGNAL", "required_attributes": "clearly_established=True, adequately_explains_conduction_disease=True"}]),
        rule("WT13", g("ANY", [a("asymmetric_septal_hypertrophy", req="late_onset=True"), a("hypertrophic_cardiomyopathy", req="late_onset=True")]), blockers=[{"blocker_id": "WT13_B01", "atom_id": "wt13_sarcomeric_hcm", "action": "BLOCK_SIGNAL", "required_attributes": "clearly_established=True, adequately_explains_hypertrophy=True"}]),
        rule("WT14", g("ANY", [a("lflg_as")]), blockers=[{"blocker_id": "WT14_B01", "atom_id": "wt14_as_explains_lvh", "action": "BLOCK_SIGNAL", "required_attributes": "clearly_established=True, adequately_explains_lvh=True"}]),
        rule("WT15", g("ANY", [a("apical_sparing"), a("reduced_gls")])),
        rule("WT16", g("ANY", [a("pseudo_infarct"), a("voltage_mass_mismatch"), a("low_ecg_voltage")]), blockers=[{"blocker_id": "WT16_B01", "atom_id": "wt16_prior_mi", "action": "BLOCK_SIGNAL", "required_attributes": "clearly_established=True, adequately_explains_ecg_pattern=True"}]),
        rule("WT17", g("ALL", [a("reduced_mcf"), a("lvef_result")]), runtime="NON_FIRING"),
        rule("WT18", g("ALL", [g("ANY", [a("declining_blood_pressure"), a("hf_medication_intolerance"), a("medication_dose_change")]), a("hypertension")], independent=True), blockers=[{"blocker_id": "WT18_B01", "atom_id": "wt18_competing_hypotension", "action": "BLOCK_SIGNAL", "required_attributes": "clearly_established=True, adequately_explains_low_bp=True"}]),
        rule("WT19", g("ALL", [a("bnp_result"), a("lv_mass_index_result")]), runtime="NON_FIRING"),
        rule("WT20", g("ALL", [a("myocardial_bone_tracer_uptake", req="non_amyloid_indication=True")]), runtime="EXECUTABLE"),
        rule("WT21", g("ANY", [a("age_excessive_snhl")]), blockers=[{"blocker_id": "WT21_B01", "atom_id": "wt21_competing_hearing_loss", "action": "BLOCK_SIGNAL", "required_attributes": "clearly_established=True, adequately_explains_hearing_loss=True"}]),
        rule("WT22", g("ANY", [a("mild_sensory_polyneuropathy"), a("sfn"), a("dysautonomia")]), runtime="EXECUTABLE"),
        rule("WT23", g("ANY", []), runtime="NON_EXECUTABLE"),
        rule("WT24", g("ANY", [a("lv_wall_measurement"), a("lv_mass_index_result")]), runtime="EXECUTABLE"),
        rule("WT25", g("ANY", [a("plasma_cell_dyscrasia"), a("mgus"), a("serum_immunofixation_monoclonal"), a("urine_immunofixation_monoclonal")]), runtime="EXECUTABLE"),
        rule("WT26", g("ALL", [a("egfr_result"), g("ANY", [a("abnormal_serum_free_light_chain_ratio"), a("serum_immunofixation_monoclonal"), a("urine_immunofixation_monoclonal")])], independent=True), runtime="EXECUTABLE"),
        rule("WT27", g("ALL", [g("ANY", [a("plasma_cell_dyscrasia"), a("mgus"), a("hypoalbuminemia")]), g("ANY", [a("nephrotic_range_proteinuria"), a("periorbital_purpura"), a("macroglossia")])], independent=True), runtime="EXECUTABLE"),
        rule("WT28", g("ANY", [a("dysautonomia"), a("fhx_established_attr", experiencer="FAMILY_MEMBER"), a("gi_dysmotility"), a("sfn"), a("vitreous_opacity")]), runtime="EXECUTABLE"),
        rule("WT29", g("ALL", [g("ANY", [a("fmf"), a("chronic_inflammatory_arthritis"), a("ibd_inflammatory_driver"), a("chronic_infection"), a("autoinflammatory_syndrome")]), a("urine_protein_result"), g("ANY", [a("saa_result"), a("crp_result"), a("esr_result")])], independent=True), runtime="EXECUTABLE"),
        rule("WT30", g("ANY", [a("elevated_uric_acid")]), runtime="NON_FIRING"),
    ]

    # Structured signal-to-atom connector.  The AST is authoritative for
    # composite rules; mappings retain the audit trail and extraction status.
    mappings: list[dict[str, Any]] = []
    for rec in rules:
        sid = rec["signal_id"]
        def walk(node: Any) -> None:
            if not isinstance(node, dict): return
            if node.get("type") == "atom":
                mappings.append({"signal_id": sid, "atom_id": node["id"], "can_fire_from_this_mapping": rec.get("runtime_executability") not in {"NON_FIRING", "NON_EXECUTABLE"}, "required_qualifiers": node.get("required_attributes"), "evidence_mode": "DOCUMENTED_ASSERTION" if rec.get("runtime_executability") == "EXECUTABLE" else None, "stage": "PRETEST_SIGNAL"})
            for child in node.get("members", []): walk(child)
        walk(rec.get("rule"))
        for blocker in rec.get("blockers", []):
            mappings.append({"signal_id": sid, "atom_id": blocker["atom_id"], "can_fire_from_this_mapping": False, "required_qualifiers": blocker.get("required_attributes"), "evidence_mode": None, "stage": "PRETEST_SIGNAL", "mapping_role": "BLOCKER"})
    # Source audit retains procedure/device context atoms even when they are
    # deliberately non-firing.  Keep those connector rows so every retained
    # WT atom has an explicit signal relationship.
    mappings.extend([
        {"signal_id": "WT02", "atom_id": "carpal_tunnel_release", "can_fire_from_this_mapping": False, "mapping_role": "CONTEXT_ONLY", "evidence_mode": None, "stage": "PRETEST_SIGNAL"},
        {"signal_id": "WT14", "atom_id": "aortic_valve_replacement", "can_fire_from_this_mapping": False, "mapping_role": "CONTEXT_ONLY", "evidence_mode": None, "stage": "PRETEST_SIGNAL"},
    ])
    # Keep unique connector pairs while preserving a positive mapping if one exists.
    dedup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in mappings:
        key = (row["signal_id"], row["atom_id"])
        if key not in dedup or row.get("can_fire_from_this_mapping"):
            dedup[key] = row
    mappings = sorted(dedup.values(), key=lambda row: (row["signal_id"], row["atom_id"]))

    buckets = [
        {"reasoning_bucket": "CARDIO", "bucket_class": "INDEPENDENT", "counts_independently": True, "definition": "Cardiac ATTR-compatible evidence used in ATTRwt gate arms."},
        {"reasoning_bucket": "ORTHO", "bucket_class": "INDEPENDENT", "counts_independently": True, "definition": "Orthopedic/tenosynovial red-flag axis; derived composites retain independent lineage."},
        {"reasoning_bucket": "NEURO", "bucket_class": "INDEPENDENT", "counts_independently": True, "definition": "Peripheral neuropathy context used for subtype routing, not a positive WT gate."},
        {"reasoning_bucket": "RENAL", "bucket_class": "CONTEXT", "counts_independently": False, "definition": "Renal and light-chain context for AL/AA differential routing."},
        {"reasoning_bucket": "HEREDITARY", "bucket_class": "INDEPENDENT", "counts_independently": True, "definition": "Hereditary evidence routes toward ATTRv review; not WT-positive evidence."},
        {"reasoning_bucket": "LAB_CONTEXT", "bucket_class": "CONTEXT", "counts_independently": False, "definition": "Differential laboratory context; never an independent ATTRwt gate."},
        {"reasoning_bucket": "SYSTEMIC_CONTEXT", "bucket_class": "CONTEXT", "counts_independently": False, "definition": "Weak systemic context and demographic modifiers."},
    ]
    priorities = [
        {"priority_policy_id": "PAIR_TIER_MIX", "class": "A", "kind": "PAIR_TIER_MIX", "tier_pattern": "1+1", "clinical_note": "Highest review priority for two independent Tier 1 arms."},
        {"priority_policy_id": "PAIR_TIER_MIX", "class": "B", "kind": "PAIR_TIER_MIX", "tier_pattern": "1+2", "clinical_note": "High review priority for mixed Tier 1/Tier 2 arms."},
        {"priority_policy_id": "PAIR_TIER_MIX", "class": "B", "kind": "PAIR_TIER_MIX", "tier_pattern": "2+1", "clinical_note": "High review priority for mixed Tier 2/Tier 1 arms."},
        {"priority_policy_id": "PAIR_TIER_MIX", "class": "C", "kind": "PAIR_TIER_MIX", "tier_pattern": "2+2", "clinical_note": "Lower review priority; profiles are filtered by default."},
        {"priority_policy_id": "FIXED_B", "class": "B", "kind": "FIXED", "tier_pattern": "ANY", "clinical_note": "Temporal chronology unknown; retain as high-priority review route."},
    ]
    combinations = [
        {"combination_id": "WT_RULE_01", "enabled": True, "outcome": "PHENOTYPE_PASS", "result_route": "ATTRWT_REVIEW", "priority_policy_id": "PAIR_TIER_MIX", "temporal_policy": "ORTHO_BEFORE_CARDIO", "temporal_rule_id": "T01", "temporal_requirement": "SATISFIED_TRUE", "clinical_rationale": "Orthopedic ATTRwt red-flag evidence precedes independent cardiac ATTR-compatible evidence.", "requirements": [{"requirement_id": "WT_RULE_01_ORTHO", "kind": "BUCKET", "buckets": ["ORTHO"], "tiers": [1, 2], "distinct_lineage_required": True}, {"requirement_id": "WT_RULE_01_CARDIO", "kind": "BUCKET", "buckets": ["CARDIO"], "tiers": [1, 2], "distinct_lineage_required": True}]},
        {"combination_id": "WT_RULE_02", "enabled": True, "outcome": "PHENOTYPE_PASS", "result_route": "ATTRWT_REVIEW", "priority_policy_id": "FIXED_B", "temporal_policy": "REQUIRE_UNKNOWN", "temporal_rule_id": "T01", "temporal_requirement": "SATISFIED_NULL", "clinical_rationale": "Independent orthopedic and cardiac evidence with insufficient chronology for temporal ordering.", "requirements": [{"requirement_id": "WT_RULE_02_ORTHO", "kind": "BUCKET", "buckets": ["ORTHO"], "tiers": [1, 2], "distinct_lineage_required": True}, {"requirement_id": "WT_RULE_02_CARDIO", "kind": "BUCKET", "buckets": ["CARDIO"], "tiers": [1, 2], "distinct_lineage_required": True}]},
    ]
    guardrails = [
        {"guardrail_id": "WT20", "enabled": True, "rule_ref": "WT20", "action": "DIFFERENTIAL_ROUTE_GUARDRAIL", "route": "AMYLOID_EVALUATION_WITH_AL_EXCLUSION", "does_not_negate_attrv": True, "message": "Incidental myocardial tracer uptake routes to amyloid evaluation only when provenance is non-amyloid and AL exclusion is completed."},
        {"guardrail_id": "WT22", "enabled": True, "rule_ref": "WT22", "action": "FALSE_NEGATIVE_GUARDRAIL", "route": "RETAIN_ATTRWT_REVIEW_AND_ROUTE_PROMINENT_NEUROLOGY_TO_ATTRV", "does_not_negate_attrv": True},
        {"guardrail_id": "WT24", "enabled": True, "rule_ref": "WT24", "action": "FALSE_NEGATIVE_GUARDRAIL", "route": "REOPEN_ATTRWT_IF_DISPROPORTIONATE", "does_not_negate_attrv": True},
        {"guardrail_id": "WT25", "enabled": True, "rule_ref": "WT25", "action": "DIFFERENTIAL_ROUTE_GUARDRAIL", "route": "URGENT_AL_EVALUATION_OR_AMYLOID_TYPING", "does_not_negate_attrv": True},
        {"guardrail_id": "WT26", "enabled": True, "rule_ref": "WT26", "action": "DIFFERENTIAL_ROUTE_GUARDRAIL", "route": "CKD_AWARE_AL_REVIEW", "does_not_negate_attrv": True},
        {"guardrail_id": "WT27", "enabled": True, "rule_ref": "WT27", "action": "DIFFERENTIAL_ROUTE_GUARDRAIL", "route": "AL_EVALUATION_OR_AMYLOID_TYPING", "does_not_negate_attrv": True},
        {"guardrail_id": "WT28", "enabled": True, "rule_ref": "WT28", "action": "DIFFERENTIAL_ROUTE_GUARDRAIL", "route": "ATTRV_REVIEW_AND_TTR_GENOTYPING", "does_not_negate_attrv": True},
        {"guardrail_id": "WT29", "enabled": True, "rule_ref": "WT29", "action": "DIFFERENTIAL_ROUTE_GUARDRAIL", "route": "AA_DIFFERENTIAL_REVIEW", "does_not_negate_attrv": True},
    ]
    for name, payload in {"signals.json": {"phenotype": "ATTRWT", "signals": signals}, "signal_atoms.json": {"phenotype": "ATTRWT", "signal_atoms": mappings}, "signal_rules.json": {"phenotype": "ATTRWT", "signal_rules": rules}, "buckets.json": {"phenotype": "ATTRWT", "buckets": buckets}, "priority_policies.json": {"phenotype": "ATTRWT", "priority_policies": priorities}, "combinations.json": {"phenotype": "ATTRWT", "combinations": combinations}, "guardrails.json": {"phenotype": "ATTRWT", "guardrails": guardrails}}.items():
        (WT / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build_shared_atoms()
    build_phenotype_package()
    print("ATTRwt V4 package written to", WT)

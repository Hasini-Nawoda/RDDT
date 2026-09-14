# Implementation Checklist — Build Order for v3

Concrete, ordered checklist to go from specs to running Snowflake code. Each phase has a single
pass/fail success test — don't start the next phase until the current one's test passes on real
(or synthetic) patient data. Content referenced throughout comes from `11_phenotype_bucket_tiers_and_combinations.md`
(the phenotype-specific rules) plus `01`/`02b`/`04`/`05` (atoms/composites/guardrails/temporal).

## Phase 0 — Freeze the decisions (no code yet)

- [ ] **WT04 = composite, never an atom.** `02b_composite_rules.md` wins over the old note in
      `01_atoms_layer.md`.
- [ ] **Composites live only in `02b_composite_rules.md`.** Strip the duplicate "Composite rules
      schema" / "Full composite rule set" sections out of `05_temporal_rules.md` (lines 52–76) and
      replace with a one-line pointer to `02b`. `05` becomes temporal-only.
- [ ] **Drop V06 as a standalone composite.** It's functionally identical to `V_RULE_04`
      (NEURO+CARDIO, Priority B) already in `03_combinations.md`. Mark V06 "superseded by
      V_RULE_04" the same way WT04's old atom-note was marked superseded.
- [ ] **`bucket_override` lives on the phenotype overlay, not the atom.** Confirmed correct as
      already written in `02_phenotype_overlays.md` line 59 — `reasoning_bucket` varies *by
      phenotype* for the two exception atoms (`gi_dysmotility`, `gastroparesis_early_satiety`), so
      it's inherently a per-(atom, phenotype) fact. The atom carries one unconditional default
      `reasoning_bucket`; the overlay overrides it only for phenotypes that need to.
- [ ] **Resolve the `ATTR_COMMON` whitelist conflict.** Decide whether `AC07` (ORTHO+NEURO) and
      `AC08` (AUTONOMIC+HEREDITARY) from `03_combinations.md` stay in, or whether the narrower
      6-pair whitelist in `11_phenotype_bucket_tiers_and_combinations.md` wins.
- [ ] **Pipeline order locked:**
      `atoms → Shape A composites → bucket tiers → Shape B/C composites → temporal → combinations (funnel) → guardrails → router`
- [ ] Write the outcome of the five decisions above into this file's changelog (bottom) so nobody
      re-litigates them mid-build.

**Success test:** every reviewer has read and signed off on the five bullets above. No code.

---

## Phase 1 — Make atoms runnable

**Goal:** `ATTR_V3_ATOMS` produces correct 0/1 + date columns for at least the ATTRwt-relevant atoms.

- [ ] Write `v3_loader.py` that reads the actual nested schema in `atoms/*.json`
      (`extraction.codes.{icd10,icd9,cpt,hcpcs,loinc,rxnorm,snomed}`, `extraction.keywords`) — do
      not adapt the v2 loader's flat `keywords.canonical` shape to fit; write a new reader.
- [ ] Decide the `extraction_executability` fix: either (a) recompute it — mark
      `EXECUTABLE` if the atom has ≥1 `REVIEWED` code or ≥1 active keyword — or (b) ignore the flag
      entirely in the loader and gate executability on content presence directly. Pick one, apply
      it uniformly, don't leave some atoms flagged by the stale rule and others not.
- [ ] Add `"reasoning_bucket"` to every atom in `atoms/*.json` — confirmed present on **zero** of
      the 211 atoms today. This is the literal blocker for Phase 2 (nothing to `LEAST()`-group by
      without it). Pull the value from the Signal Catalog's `Reasoning_Bucket` column per atom's
      `source_workbook_rows`.
- [ ] Re-verify (don't re-fix blind) the previously-audited atom bugs — orthostatic consolidation,
      GI double-count, V10/V11 cross-bucket duplication, V28 bucket misplacement, AL34 bucket
      misplacement — against the *current* `atoms/*.json`, since most were already fixed earlier
      in this project. Only touch what's still actually broken.
- [ ] Scope Phase 1's atom set to what ATTRwt's walking skeleton needs: `cts_bilateral`,
      `biceps_rupture`, `arthroplasty`, `trigger_finger`, `rotator_cuff`, `shoulder_disorder`,
      `lumbar_stenosis` (ORTHO); `hfpef`, `af`, `conduction_disease`, `pacemaker_icd`, `pacemaker_implantation`,
      `pacemaker_presence`, `lv_wall_measurement`, `hypertrophic_cardiomyopathy`, `apical_sparing`,
      `myocardial_bone_tracer_uptake` (CARDIO); `mgus` (guardrail). Everything else can wait for Phase 4.
- [ ] Decide the test-patient source: a real de-identified Snowflake patient with `G56.03`
      (bilateral CTS) + a biceps-rupture code + an HFpEF code, or synthetic rows inserted into a
      scratch schema. Pick one before running the test below — don't discover this mid-Phase-1.

**Success test:** one patient with ICD-10 `G56.03` produces `CTS_BILATERAL = 1` with a non-null
`CTS_BILATERAL_FIRST_SEEN` date in `ATTR_V3_ATOMS`.

---

## Phase 2 — Overlays and bucket-tier rollup

**Goal:** `ATTR_V3_BUCKET_TIER` produces correct `BEST_TIER` per (patient, phenotype, bucket).

- [ ] Build `phenotype_overlays/attrwt.json` (and stub the other five) using this schema per atom:
      ```json
      {
        "atom_id": "cts_bilateral",
        "source_sign_ids": ["WT02", "V13"],
        "overlays": {
          "ATTRwt": {"tier": 1, "role": "POSITIVE_EVIDENCE", "gate_eligible": true, "source_sign_id": "WT02"},
          "GENERAL_AMYLOID": {"tier": 2, "role": "ORGAN_OR_PHENOTYPE_EVIDENCE", "gate_eligible": true, "source_sign_id": "WT02"}
        }
      }
      ```
      Note both levels: `source_sign_ids` (array, atom-level, every sign this atom serves) and
      `source_sign_id` (singular, per-overlay, which sign produced *this* phenotype's tier) — this
      resolves the earlier ambiguity about which sign a given tier row traces back to.
- [ ] Populate tiers from `11_phenotype_bucket_tiers_and_combinations.md`'s ATTRwt ORTHO/CARDIO
      tables exactly — no re-deriving thresholds.
- [ ] Enforce: Tier 3–4 → `gate_eligible: false`. `role: MODIFIER` → always `gate_eligible: false`,
      regardless of tier.
- [ ] Write the `LEAST()` SQL per bucket per phenotype (per-bucket tier = best tier among every
      atom/composite tagged to that bucket for that phenotype) — never `SUM()`.
- [ ] Wire in Shape-A composites (`WT04`/`ORTHO_CLUSTER`) as an extra input to the `LEAST()`
      expression, computed in the same pass as atoms (per the Phase 0 pipeline-order decision).

**Success test:** the same test patient from Phase 1 (CTS + biceps + HFpEF) produces
`ATTR_V3_BUCKET_TIER` rows: `(ATTRwt, ORTHO, BEST_TIER=1)` and `(ATTRwt, CARDIO, BEST_TIER=2)`.

---

## Phase 3 — Prove the funnel end-to-end on ATTRwt only

**Goal:** one full vertical slice through every layer type, before touching ATTRv/AL/AA.

- [ ] Composite: `WT04`/`ORTHO_CLUSTER` only (Shape A, `member_atom_ids` + `min_count: 2`).
- [ ] Temporal: `T01`/`WT_CANONICAL_TEMPORAL` only — implement the three-tier priority output
      (`ORTHO T1+CARDIO T1+sequence → A`, `ORTHO T1+CARDIO T2+sequence → B`,
      `ORTHO T2+CARDIO T2+sequence → C`), not just a boolean pass/fail.
- [ ] Combinations: `GA01`, `AC01` (ORTHO+CARDIO), `WT_RULE_01`/`WT_RULE_02` only.
- [ ] Guardrail: `WT25`/`mgus` → `AL_SAFETY` only.
- [ ] Router: wide output row, even if only ATTRwt/GENERAL_AMYLOID/ATTR_COMMON columns are
      populated and ATTRv/AL/AA are hardcoded `NOT_YET_IMPLEMENTED`.

**Success test:** a patient with CTS (2015) + biceps rupture (2016) + unexplained HFpEF (2023) +
known MGUS produces, in `ATTR_V3_ROUTER_OUTPUT`:
```
GENERAL_AMYLOID = PASS
ATTR_COMMON     = PASS
ATTRwt          = PRIORITY_A   (ORTHO T1 + CARDIO T2, correct temporal order → actually Priority B per the table above — verify against the exact tier mix in the test patient before asserting A vs B)
ALL_ROUTES      = ['ATTRWT_REVIEW', 'AL_SAFETY']
```
This test intentionally does **not** exercise a Shape B/C composite or `COUNT_DISTINCT_BUCKETS`/
`ORG_PLUS_ETIOLOGY` rule type — passing Phase 3 proves the pipeline shape works, not that every
rule shape works. Don't generalize that conclusion prematurely.

---

## Phase 4 — Expand phenotype by phenotype

- [ ] **ATTR_COMMON full whitelist** — all 6 (or 8, pending the Phase 0 AC07/AC08 decision) pairs.
- [ ] **ATTRv** — bring in NEURO/AUTONOMIC/HEREDITARY/OCULAR/CARDIO/ORTHO tier tables from
      `11_phenotype_bucket_tiers_and_combinations.md`; implement all 5 `ATTRV_CANONICAL_*` rules;
      confirm V06 stays dropped (Phase 0).
- [ ] **AL** — bring in HEME_CLONAL/RENAL/MUCOSAL_CUTANEOUS/CARDIO/NEURO/GI_HEPATIC tables; this is
      where Shape B/C composites (`AL21`, `AL26`, `AL27`) first get exercised, since they need
      bucket tiers to already exist; implement `AL_HIGH_1`–`4` and the `AL_POSSIBLE` fallback
      (≥3 organ buckets, no clonal finding → monoclonal-screen funnel, never labeled AL).
- [ ] **AA** — bring in INFLAMMATORY_DRIVER/INFLAMMATORY_ACTIVITY/RENAL/SUSCEPTIBILITY tables;
      this exercises the remaining Shape B/C composite (`AA21`); implement the two-line `AA_PASS`
      gate and Priority A/B/C ranking.
- [ ] **Remaining guardrails** — the ones not needed for Phase 3 (WT24/26/27/28/29, all V-series,
      all AL-series, all AA-series) plus remaining temporal rules `T02`–`T07`.
- [ ] **Ranking key** — implement the full 7-level lexicographic comparison across all six
      phenotypes (route priority → canonical combination present → temporal present → gate-eligible
      bucket count → T1 count → T2 count → lead time), replacing any per-phenotype ad hoc ranking
      built during Phase 3.
- [ ] Fill every remaining machine field (`member_atom_ids`, `trigger_atom_ids`, `min_tier`,
      `output_route`) as each rule gets implemented — never leave a rule in English-only form once
      its phase starts.

**Success test per phenotype:** same shape as Phase 3's test — one concrete patient, full router
output, before moving to the next phenotype.

---

## What not to do at any phase

- Don't build the full signal catalog file first — the workbook's `Signal Catalog` sheet is
  already the reference; nothing blocks on producing our own copy of it.
- Don't rewrite/verify all 133 signs' keywords before any SQL runs — Phase 1 only needs the
  ATTRwt-relevant atom subset.
- Don't implement all 28 combination rules on day one.
- Don't let WT04 become an atom again.
- Don't nest AL or AA under `ATTR_COMMON` — both read off `GENERAL_AMYLOID` directly, in parallel.

## Target directory layout (once Phase 1 starts producing real config files)

```
specialty_configs/
└── v3/
    ├── atoms/                    (ortho.json, cardio.json, neuro.json, renal.json, heme.json,
    │                              inflammatory.json, ocular.json, shared.json, ...)
    ├── phenotype_overlays/       (general_amyloid.json, attr_common.json, attrwt.json,
    │                              attrv.json, al.json, aa.json)
    ├── combinations/             (one file per phenotype, same six names)
    ├── composites/               (shape_a.json, shape_b_c.json — per 02b's three-shape split)
    ├── guardrails/
    │   └── differential_routes.json
    └── temporal_rules/
        └── longitudinal_patterns.json
```
This is the **runtime config** location (parallel to the existing `specialty_configs/v2/`) — distinct
from `architecture_v3_specs/`, which stays the design-doc folder and is never read by the pipeline.

## Changelog (Phase 0 decisions, once ratified)

- [ ] Date / initials: WT04 composite-not-atom — confirmed.
- [ ] Date / initials: 05/02b dedupe — done.
- [ ] Date / initials: V06 dropped in favor of V_RULE_04 — confirmed.
- [ ] Date / initials: bucket_override stays on overlay — confirmed.
- [ ] Date / initials: AC07/AC08 whitelist decision — confirmed which list wins.

# Known gaps — deferred on purpose, not forgotten

Things we found while reviewing signals one at a time, decided not to fix
immediately, and don't want to lose track of. Check this file before
declaring a signal "done" — the same gap likely applies to it too.

## 1. `mapping_role: PROXY_SUPPORT` + `requires_corroboration` not enforced

Found: 2026-09 (WT03 review, `biceps_rupture`).

Every code in `atoms/*.json` carries a `mapping_role`: `DIRECT_TARGET`,
`PROXY_SUPPORT`, or `DIFFERENTIAL_EXCLUDE`. `DIFFERENTIAL_EXCLUDE` is now
handled (`wt01_atoms._code_list` drops those codes — see fix below).

`PROXY_SUPPORT` is NOT yet handled. Its intent (per the `requires_corroboration`
list on each such code) is: this code is weak/nonspecific on its own and should
only count as a match if at least one of the listed corroborating codes is ALSO
present for the same patient. Example: `biceps_rupture`'s SNOMED `86128003`
("Rupture of tendon of biceps, long head") is PROXY_SUPPORT requiring
corroboration from `M66.821`, `M66.822`, `M66.829`, `428883008`, or `24342`.

Today, `_code_list` treats `PROXY_SUPPORT` exactly like `DIRECT_TARGET` — it
fires the atom alone, no corroboration check. This is a precision gap (over-
matching), not a directional bug like `DIFFERENTIAL_EXCLUDE` was, so it was
left as-is for now.

**When implementing:** decide the corroboration window (same atom's other
codes only, or across atoms? any date, or same encounter/date?) before writing
SQL — that's a clinical-design decision, not just an engineering one.

## 2. `can_fire_atom_alone` not enforced

Also sitting on every code (`true`/`false`), also unused by the pipeline right
now. Conceptually overlaps with `requires_corroboration` above (a `false` value
usually pairs with a `requires_corroboration` list) but is a separate field and
may need its own handling — e.g. for keyword-matched evidence that has no code
counterpart at all.

## 3. Audit needed: how many atoms currently in use are affected

At the time the `DIFFERENTIAL_EXCLUDE` fix went in, a repo-wide scan found 17
`DIFFERENTIAL_EXCLUDE` codes across 8 atoms: `achilles`, `arthroplasty`,
`biceps_rupture`, `cmr_lge`, `congo_red`, `length_dependent`,
`neuropathic_pain`, `pseudo_infarct`, `rv_wall_thick`.

Checked which of these are actually extracted by the current WT01 pipeline
(i.e. appear with a bucket+tier in `phenotype_overlays/{general_amyloid,
attr_common,attrwt}.json`) — only 3 are: `arthroplasty`, `biceps_rupture`,
`pseudo_infarct`. The rest (`achilles`, `cmr_lge`, `rv_wall_thick`,
`congo_red`, `length_dependent`, `neuropathic_pain`) exist as atom
definitions but aren't wired into any phenotype overlay yet, so they're not
extracted or matched at all right now — the `DIFFERENTIAL_EXCLUDE` fix is
inert for them today, but will apply automatically the moment they do get
wired in (it's generic, not per-atom).

Re-check `arthroplasty` and `biceps_rupture`'s `PROXY_SUPPORT` codes when the
corroboration logic above gets built — both have some today.

## 4. Lab-result atoms don't check the actual value, only that the test was mentioned

The 17 LOINC-backed atoms (`bnp_result`, `troponin_result`, `renal_differential_assessment`,
etc.) fire on keyword/name match alone, with no numeric threshold check against a
normal range — so a patient with a completely normal result still fires the atom
today. Needs clinician-supplied cutoffs before real value-based matching can be built.

## 5. `requires_corroboration: ['KEYWORD_EVIDENCE']` not enforced — code alone or
   keyword alone currently fires; should require both together

Found: ATTRv review (V02 / `polyneuropathy`). 36 atoms repo-wide have at least one
code tagged this way (`polyneuropathy`, `hf_any`, `bnp_result`, `troponin_result`,
`monoclonal_study_result`, `renal_dysfunction`, ... full list findable by grepping
atoms/*.json for `"KEYWORD_EVIDENCE"`). The source data is saying "this code alone
is too weak/nonspecific — only trust it if a keyword also matches" - today the atom
fires on the code OR the keyword independently (same generic code/keyword OR-merge
every atom uses), no AND requirement.

`polyneuropathy` is the highest-impact instance found so far: Tier 1, gate-eligible,
feeding ATTRv, GENERAL_AMYLOID, and ATTR_COMMON simultaneously. Its codes (`G60.`/
`G62.`) just mean "has nerve damage, any cause" - diabetes is the most common cause
by far. Checked its keyword list too - also generic ("peripheral neuropathy",
"sensorimotor neuropathy", etc), no amyloid-specific qualifiers ("idiopathic",
"unexplained", "progressive"). So even requiring code+keyword together (the direct
fix for this gap) would NOT be sufficient by itself for `polyneuropathy` specifically
- a diabetic patient's routine chart typically has both the code and the word.

Two-part fix, when this gets built:
  1. Generic: enforce code+keyword AND (not OR) wherever `requires_corroboration`
     includes `KEYWORD_EVIDENCE` - fixes the literal gap for all 36 atoms.
  2. `polyneuropathy`-specific, bigger: down-weight/exclude when a more common
     alternative cause (diabetes, alcohol use, B12 deficiency, chemotherapy) is the
     only documented explanation and no amyloid-suspicious framing exists. A
     `diabetes` atom already exists in the config, so this is buildable later -
     needs a design decision on exactly how "explained by X" should be detected.

Addendum, found via V03 (`NEURO_PLUS_SYSTEMIC` composite) review: its anchor atom
`length_dependent` already HAS a real diabetes exclusion (`E11.42` "diabetic
polyneuropathy" tagged `DIFFERENTIAL_EXCLUDE`) - the fix in gap #3 already makes
that active. But it only stops `E11.42` itself from counting; it does NOT stop the
atom's other codes (`G62.`/`G60.`, same nonspecific ones `polyneuropathy` uses) from
firing independently even when `E11.42` is ALSO present for that patient - so a
diabetic with both codes on their chart still fires it. Also, the composite's
`bucket_fallback` (used whenever `length_dependent`/`emg_axonal` don't fire) accepts
ANY NEURO Tier<=2 evidence, including plain `polyneuropathy` - which has no diabetes
protection at all - so the fallback path bypasses `length_dependent`'s partial
protection entirely. `emg_axonal` (the composite's other anchor atom) is a dead atom
- zero codes, zero keywords, same empty-shell pattern as `lumbar_decompression`/
`trigger_release`/`rotator_cuff_repair`/`pacemaker_implantation`/`pacemaker_presence`.

A real per-patient exclusion rule (not just "don't count this one code") is needed
to actually solve this - part of the design decision in point 2 above.

**Addendum, found via V37 - explained plainly for anyone reading this, not just
engineers:**

There is an atom called `diabetes` that checks whether the patient has a diabetes
diagnosis. It's one of the best-built atoms in the whole system - real diagnosis
codes, real symptom words, nothing wrong with it.

It's specifically labeled as a "MODIFIER" - meaning its job is supposed to be:
*"don't count this as its own evidence, use it to reduce trust in OTHER findings"* -
exactly the tool needed to fix the diabetes problem described above (a diabetic
patient's ordinary nerve damage getting mistaken for a sign of this disease).

**But that label currently does nothing.** We checked the entire codebase for
anywhere that reads this "MODIFIER" label and acts on it - nowhere does. Right now,
having diabetes on record is treated exactly the same as any other weak, low-priority
clue. It does not reduce trust in the neuropathy finding at all, even though it is
specifically tagged as if it should.

**Plain-language summary:** the tool needed to fix this problem already exists and
already correctly detects diabetes - it's just sitting there unused. Someone still
needs to write the logic that actually uses it the way it's labeled to be used.

## 6. `NEURO_PLUS_SYSTEMIC` composite (V03) computes but is never used - and
   `NEURO_CARDIO_MIXED` (V06) isn't even built

Found: ATTRv review (V03). The composite itself is built correctly and verified
against the source spec - fires `TRUE`/`FALSE` per patient into
`ATTR_V3_COMPOSITE_HITS`, visible via `preview_composites`. Its documented purpose
is "upgrade ATTRv review priority."

But nothing downstream reads it. Checked all 7 of `combinations/attrv.json`'s rules
(`V_RULE_01`-`07`) - none of them reference `NEURO_PLUS_SYSTEMIC` in `priority_when`
or anywhere else. So today, whether V03 fires or not has zero effect on a patient's
final `ATTRV` value, `ATTRV_RULE_ID`, or priority in `ATTR_V3_ROUTER_OUTPUT` - it's
computed and then never consumed.

Not just a missing SQL wire-up: the config itself (`combinations/attrv.json`) doesn't
say HOW the upgrade should work (which rule(s) it upgrades, from what priority to
what). That's a design decision needed before this can be implemented, not just an
engineering task.

**V06 addendum:** `NEURO_CARDIO_MIXED` (source_sign_id V06, in `composites/shape_b_c.json`)
is a third composite shape (`CROSS_BUCKET_PAIR` - NEURO or AUTONOMIC Tier<=2 + CARDIO
Tier<=2) that hasn't been built at all yet - only Shape A (`create_ortho_cluster`) and
V03's shape (`create_neuro_plus_systemic`) exist in `wt01_composites.py`. Its own note
says it overlaps `V_RULE_04` and should "upgrade" that rule's priority - same
"upgrade a rule" pattern as V03, and checked: `V_RULE_04` doesn't reference it either.
So even if built, V06 would hit the exact same dead end V03 did (computed, never
consumed) - same root cause, tracked together here rather than as a separate gap.

## 7. V17 (`microalbuminuria`) not usable by `V_RULE_07`, plus a separate
   confirmed-carrier-vs-family-history mixup in the same rule

Found: ATTRv review (V17 / `V_RULE_07`).

**Part A - tier too low.** `microalbuminuria`'s own spec says Tier 2, and it's meant
to be the RENAL half of `V_RULE_07` (the carrier-surveillance rule: HEREDITARY +
RENAL). But it's not in ATTRv's own overlay at all, and where it DOES exist (in
GENERAL_AMYLOID's overlay) it's set to Tier 3 - too weak to satisfy `V_RULE_07`'s
`RENAL max_tier: 2` requirement. So `V_RULE_07` can never get real RENAL evidence
today. Fix: add `microalbuminuria` to ATTRv's own overlay, RENAL Tier 2, non-gate
(matches its `Source_Gate_Eligible: No - modifier/context only` in the source spec).

**Part B - separate issue, found while checking Part A.** `V_RULE_07`'s own notes say
it "must not fire from family-history-only HEREDITARY without confirmed genetic/
carrier context." But the HEREDITARY bucket doesn't distinguish "confirmed carrier"
(`V01`/`ttr_pathogenic_variant` - real gene test) from "family history only"
(`V07`/`fhx_established_attr` - no test on this patient) - both sit at the same
Tier 1. So even after fixing Part A, `V_RULE_07` could still fire from family-history
-only HEREDITARY, which its own documentation says should never happen.

Two ways to fix Part B, discussed and NOT decided yet:
  - Lower `fhx_established_attr`'s tier globally (simple, but risks weakening OTHER
    rules that also require HEREDITARY Tier 1, e.g. `V_RULE_05`, which has no
    "confirmed-carrier-only" language attached - unclear if narrowing it is correct).
  - (Recommended) Make `V_RULE_07` specifically require the `ttr_pathogenic_variant`
    atom by name, not just "any HEREDITARY Tier 1 evidence" - more targeted, only
    touches this one rule, but needs the combination-rule engine to support
    "require this specific atom" conditions, which it can't do yet (today it can
    only ask for "some evidence in bucket X at tier Y").

## 8. `RENAL_DISPROPORTIONATE` (AA21) doesn't check its own confound atoms

Found: AA build (2026-09).

The composite's source config (`composites/shape_b_c.json`) lists
`confound_atom_ids: ["diabetes", "hypertension"]` and a comparator saying the
renal finding must be "present and not fully explained by confound atoms
alone." The current implementation (`composites.create_renal_disproportionate`)
does NOT check this - it fires whenever an AA `INFLAMMATORY_DRIVER` atom AND a
renal-finding atom are both present, full stop. Diabetes/hypertension are
extracted nowhere near this composite and never looked at.

**Plain-language version:** if a patient has diabetic kidney disease (very
common) AND also happens to have some inflammatory driver on their chart, this
composite currently treats their kidney findings as AA-suspicious - even though
diabetes alone is a completely ordinary explanation for those same kidney
findings.

Not fixed now because the source config itself only says confounds should
"down-weight confidence" (not hard-exclude) - exactly how much to down-weight,
and whether that means excluding patients where diabetes/hypertension is the
ONLY kidney explanation vs. something softer, is a clinical-design decision,
same category as gap #5's diabetes/neuropathy problem below.

## 9. `AA_RULE_01`/`AA_RULE_02`'s `modifier.presence` wording taken loosely,
   not literally, to keep the two rules mutually exclusive

Found: AA build (2026-09).

`combinations/aa.json` says `AA_RULE_01`'s modifier (`INFLAMMATORY_ACTIVITY`)
must be `"presence": "REQUIRED"`, and `AA_RULE_02`'s must be
`"presence": "ABSENT_OR_NOT_GATE_ELIGIBLE"`. Read completely literally, the
second one means "absent, OR present-but-not-gate-eligible." But
`INFLAMMATORY_ACTIVITY` is marked `gate_eligible: false` on every single one of
its own atoms in `aa.json` (it's a MODIFIER-only bucket by design, same as
`SUSCEPTIBILITY`) - so "not gate-eligible" is always true whenever ANY
`INFLAMMATORY_ACTIVITY` evidence exists at all. Implemented literally, that
would make `AA_RULE_02`'s modifier condition true 100% of the time, meaning
`AA_RULE_01` and `AA_RULE_02` could BOTH fire for the same driver+renal
patient whenever activity evidence is present - directly contradicting their
own `mutually_exclusive_with` declaration (each names the other).

**What we built instead:** both rules check plain presence/absence of an
`INFLAMMATORY_ACTIVITY` bucket-tier row (tier <= the modifier's `max_tier`),
ignoring `GATE_ELIGIBLE` entirely on both sides (`combinations._modifier_presence_cond`).
`AA_RULE_01` fires when that evidence is present; `AA_RULE_02` fires when it's
absent. This guarantees exactly one of the two ever fires for a given patient,
matching the rules' plain-English intent ("with activity modifier" vs.
"activity missing/weak") and their explicit mutual-exclusivity contract - but
it is a documented interpretation choice, not a literal implementation of the
JSON's exact wording. Revisit if a future data update ever makes
`INFLAMMATORY_ACTIVITY` gate-eligible for some atom - at that point the literal
wording and this looser interpretation would start to disagree in practice.

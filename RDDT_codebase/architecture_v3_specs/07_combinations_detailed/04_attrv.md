# ATTRv — 7 rules

Question: **"Is this specifically hereditary/variant transthyretin amyloidosis?"** ATTRv has more
rules than any other single subtype (7) because it genuinely presents more differently
patient-to-patient than ATTRwt does — neuropathy-dominant, autonomic-dominant, cardiac-dominant,
ocular-dominant, or purely-genetic-context-driven presentations are all real and all documented in
the source CSV.

**Contributing sign IDs** (Tier 1–2, gate-eligible, ATTRv overlay):

| Bucket | Sign IDs |
|---|---|
| NEURO | `V14:T1, V04:T1, V02:T1, V28:T2` |
| AUTONOMIC | `V05:T1, V11:T2, V10:T2, V09:T2` |
| HEREDITARY | `V01:T1, V07:T1, V08:T2` |
| OCULAR | `V16:T1, V15:T1` |
| CARDIO | `V25:T2, V24:T2` |
| ORTHO | `V13:T2` |

Note how thin `CARDIO` and `ORTHO` are here compared to `ATTRwt`'s lists — only two cardiac sign
IDs (`V24`, `V25`) and a single ortho sign ID (`V13`) are gate-eligible for ATTRv, versus eight and
four respectively for ATTRwt. This is the concrete reason cardiac/orthopedic findings pull much
harder toward `ATTRwt` than `ATTRv` in this system.

## V_RULE_01 — NEURO + AUTONOMIC (canonical)

**Plain question:** The single most classic ATTRv shape — progressive neuropathy plus dysautonomia.
**Requires:** `NEURO` Tier 1–2 + `AUTONOMIC` Tier 1–2. **Priority:** A. **Temporal:** none.
**Route:** `ATTRV_REVIEW`.
**Worked example:** `V02` (progressive axonal PN) + `V10` (GI dysmotility, reasoned as AUTONOMIC
for ATTRv per `01_atoms_layer.md`'s bucket-override rule) → fires.

## V_RULE_02 — NEURO + HEREDITARY

**Plain question:** Progressive neuropathy with a documented genetic/family background.
**Requires:** `NEURO` Tier 1–2 + `HEREDITARY` Tier 1–2. **Priority:** A. **Temporal:** none.
**Worked example:** `V04` (small-fiber neuropathy) + `V01` (known pathogenic TTR variant) → fires,
Priority A since both sides are Tier 1.

## V_RULE_03 — NEURO + OCULAR

**Plain question:** Neuropathy plus a hereditary-specific eye finding.
**Requires:** `NEURO` Tier 1–2 + `OCULAR` Tier 1–2. **Priority:** A/B (A when both Tier 1, e.g.
`V02`+`V15`; B when either side is only Tier 2).
**Edge case:** Ocular findings are rare (see `01_atoms_layer.md` — `V15`/`V16` are "high
discriminator, low sensitivity") so this rule fires infrequently but is very specific when it does.

## V_RULE_04 — NEURO + CARDIO

**Plain question:** Mixed neurologic-and-cardiac ATTRv presentation.
**Requires:** `NEURO` Tier 1–2 + `CARDIO` Tier 1–2. **Priority:** B.
**Worked example:** `V14` (CIDP-labeled, poor IVIG response) + `V24` (cardiomyopathy/HFpEF) →
fires. Only `V24`/`V25` can supply the CARDIO side — a generic ATTRwt-style cardiac finding like
`WT10` is not gate-eligible under the ATTRv overlay, so it cannot satisfy this rule's CARDIO side
on its own.

## V_RULE_05 — HEREDITARY + CARDIO (neuropathy not required)

**Plain question:** Does a cardiac-predominant hereditary presentation exist, with **no
neuropathy at all**?
**Requires:** `HEREDITARY` **Tier 1 specifically** (not Tier 2 — this is the one rule in the whole
28 that requires Tier 1 rather than Tier 1–2 on one side) + `CARDIO` Tier 1–2.
**Priority:** B. **Temporal:** none.
**Worked example:** `V01` (known pathogenic TTR variant, Tier 1) + `V24` (cardiomyopathy) → fires,
even though this patient has zero neuro/autonomic/ocular findings. `V08` (family history of
unexplained neuropathy, only Tier 2 HEREDITARY) would **not** satisfy this rule's HEREDITARY side —
only `V01` or `V07` (both Tier 1) can.
**Why this rule exists:** stated directly in your original plan — "we don't want to force every
plausible TTR patient into requiring neuropathy." Non-`p.Val50Met` carriers frequently present
cardiac-first (see the ATTRv CSV's `V06` and `V24` clinical notes).

## V_RULE_06 — HEREDITARY + AUTONOMIC

**Plain question:** Dysautonomia with a genetic/family backdrop, no neuropathy required.
**Requires:** `HEREDITARY` Tier 1–2 + `AUTONOMIC` Tier 1–2. **Priority:** B.
**Worked example:** `V07` (first-degree family history of ATTR) + `V09` (orthostatic hypotension)
→ fires.

## V_RULE_07 — HEREDITARY + RENAL (carrier conversion only — separate route)

**Plain question:** In a patient who is **already known** to carry a pathogenic TTR variant (or is
undergoing cascade/family testing), has a new renal change appeared that might signal conversion
from silent carrier to active disease?

**Requires:** `HEREDITARY` Tier 1 + `RENAL` Tier 1–2 — **but only evaluated at all in a known
carrier/cascade-testing context.**

**Priority label:** "Carrier conversion" — not A/B/C. This is deliberately not comparable to the
other six rules' priority scale.

**Output route:** `ATTRV_CARRIER_REVIEW` — **not** `ATTRV_REVIEW`. This is a hard separation:
finding a new renal sign in a known carrier is surveillance, not a diagnosis of active systemic
ATTRv, and it must never be presented with the same weight as `V_RULE_01`–`06`.

**Worked example:** A patient with a documented pathogenic TTR variant (`V01`, Tier 1) who has
never had any ATTRv symptoms develops new persistent microalbuminuria (`V17`). `V_RULE_07` fires
→ `ATTRV_CARRIER_REVIEW`, meaning "flag this known carrier for closer monitoring," not "this
patient has ATTRv."

**Edge case worth flagging directly:** under the *general* ATTRv overlay, `V17` (persistent
microalbuminuria in a known TTR carrier) is marked `gate_eligible: No — modifier/context only` —
it does **not** appear in the general RENAL gate-eligible list above (ATTRv has no general-purpose
gate-eligible RENAL atom at all). `V_RULE_07` only works because it applies a **narrower,
carrier-specific exception**: `V17` becomes gate-eligible *specifically* when the patient is
already a known carrier, which is exactly the "only in known carrier/cascade-testing context"
condition on this rule. Outside that context, RENAL evidence contributes nothing to ATTRv. When
this gets built into JSON, `V17`'s gate-eligibility needs to be conditional on carrier status, not
a blanket true/false — this is the one rule in the whole set where that's required.

## Why neuropathy is not mandatory for ATTRv, summarized

`V_RULE_05` (cardiac + hereditary) and `V_RULE_06` (autonomic + hereditary) both let a patient pass
without any NEURO-bucket evidence at all, as long as `HEREDITARY` is present. Only `V_RULE_01`
through `V_RULE_04` require NEURO. This is intentional, not an oversight — see the plain-question
text of `V_RULE_05` above.

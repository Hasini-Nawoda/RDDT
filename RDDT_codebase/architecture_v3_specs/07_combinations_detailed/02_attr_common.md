# ATTR_COMMON — 8 rules

Question: **"Does this patient look ATTR-shaped, even if we can't yet tell wild-type from
hereditary?"** Only reached after `GENERAL_AMYLOID` passes. This is the phenotype that exists so a
patient never gets silently dropped just because their chart doesn't yet distinguish ATTRwt from
ATTRv — see `00_overview.md`'s `ATTR_UNSPECIFIED_REVIEW` explanation.

**Contributing sign IDs for every bucket used below** (Tier 1–2, gate-eligible, ATTR_COMMON overlay):

| Bucket | Sign IDs |
|---|---|
| ORTHO | `WT03:T1, WT02:T1, WT04:T1, V13:T2, WT05:T2` |
| CARDIO | `WT10:T1, WT13:T1, WT16:T2, WT15:T2, V25:T2, V24:T2, WT12:T2, WT09:T2, WT14:T2, WT11:T2` |
| NEURO | `V14:T1, V04:T1, V02:T1, V28:T2` |
| AUTONOMIC | `V05:T1, V11:T2, V10:T2, V09:T2` |
| HEREDITARY | `V01:T1, V07:T1, V08:T2` |
| OCULAR | `V16:T1, V15:T1` |

All eight rules are type `PAIR` — exactly two buckets, each Tier 1–2, no temporal requirement,
output route `ATTR_REVIEW` for every one of them. What differs rule to rule is *which two buckets*.

## AC01 — ORTHO + CARDIO

**Plain question:** Classic wild-type-shaped pattern — orthopedic prodrome plus cardiac finding,
*without* requiring proof of which came first (that's what makes it `ATTR_COMMON` rather than the
stricter `ATTRwt` rule).
**Priority:** A.
**Worked example:** `WT04` (multi-ortho cluster) + `WT09` (unexplained HFpEF), no reliable dates →
`AC01` fires → `ATTR_COMMON: PRIORITY A`. Separately, `ATTRwt`'s own rules will check for the date
order; if dates can't be confirmed, `ATTRwt` lands on Priority B instead of A (see
`03_attrwt.md`) while `ATTR_COMMON` is already a clean A.

## AC02 — NEURO + AUTONOMIC

**Plain question:** Classic neuropathic/dysautonomic wild-type-v-shaped pattern.
**Priority:** A.
**Worked example:** `V02` (progressive axonal neuropathy) + `V09` (orthostatic hypotension) → fires.

## AC03 — NEURO + HEREDITARY

**Plain question:** Progressive neuropathy with a genetic/family-history backdrop.
**Priority:** A/B — A when both sides are Tier 1 (e.g. `V02`+`V01`), B when either side is only
Tier 2 (e.g. `V28`+`V08`).

## AC04 — NEURO + CARDIO

**Plain question:** Mixed neurologic-and-cardiac presentation, no hereditary or autonomic evidence
needed to justify it.
**Priority:** B.
**Worked example:** `V04` (small-fiber neuropathy) + `V24` (cardiomyopathy/HFpEF) → fires, even
with zero family history and zero autonomic findings.

## AC05 — CARDIO + HEREDITARY

**Plain question:** Allows a cardiac-predominant hereditary presentation through **without**
requiring neuropathy at all.
**Priority:** B.
**Edge case:** This is the ATTR_COMMON-level version of `V_RULE_05` in `04_attrv.md` — it exists
specifically so a patient with `V01` (known pathogenic TTR variant) + `V24` (cardiomyopathy) isn't
missed just because they have no neurologic symptoms yet.

## AC06 — NEURO + OCULAR

**Plain question:** Neurologic finding plus a characteristic hereditary-ATTR eye finding.
**Priority:** B.
**Worked example:** `V02` (axonal PN) + `V15` (vitreous opacities) → fires. Ocular findings are
rare but highly specific (see `01_atoms_layer.md`'s note on `OCULAR` being "high discriminator, low
sensitivity") — pairing them with any neuro finding is enough here, no autonomic or hereditary
evidence required in addition.

## AC07 — ORTHO + NEURO

**Plain question:** Orthopedic prodrome plus neuropathy — a pattern that's genuinely ambiguous
between wild-type and hereditary disease, which is exactly why it stops at `ATTR_COMMON` and
doesn't have a matching rule in either `03_attrwt.md` or `04_attrv.md`.
**Priority:** B/C.
**Worked example:** `WT02` (bilateral CTS) + `V02` (axonal PN, borrowed from the shared NEURO
bucket) → `AC07` fires, `ATTR_COMMON: PRIORITY B/C`. But check `03_attrwt.md`: ATTRwt's own rules
require ORTHO **+ CARDIO**, not ORTHO + NEURO — so this patient does *not* pass ATTRwt. And
`04_attrv.md`'s NEURO-based rules require NEURO plus AUTONOMIC/HEREDITARY/OCULAR/CARDIO — not
ORTHO — so this patient does *not* pass ATTRv either. Result: `ATTR_COMMON: PASS`, both subtypes
`insufficient subtype pattern` → routes to `ATTR_UNSPECIFIED_REVIEW`. This is the textbook case
your original plan (§3) was designed around.

## AC08 — AUTONOMIC + HEREDITARY

**Plain question:** Dysautonomia with a genetic/family backdrop, no neuropathy required yet.
**Priority:** B.
**Worked example:** `V09` (orthostatic hypotension) + `V07` (first-degree family history of ATTR)
→ fires.

## Which pairs are deliberately *not* rules

`ORTHO + OCULAR`, `ORTHO + HEREDITARY`, `ORTHO + AUTONOMIC`, `CARDIO + OCULAR`,
`AUTONOMIC + OCULAR`, and any pairing involving `RENAL` are **not** ATTR_COMMON rules. A patient
with only, say, `WT02` (ORTHO) + `V15` (OCULAR) does not pass `ATTR_COMMON` — that specific
combination isn't in the approved list, even though both buckets individually look ATTR-relevant.
This is the "not every pairwise combination is allowed" rule from `00_overview.md` made concrete —
if you think a missing pair should be added, flag it specifically; don't assume any two
ATTR-flavored buckets are automatically an approved combination.

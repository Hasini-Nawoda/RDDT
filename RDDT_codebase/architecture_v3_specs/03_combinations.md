# Step 3 — Combination Rules

Answers: **"What collection of independent buckets makes a screening phenotype, for this specific
phenotype?"** This is the only layer that can turn evidence into a route. No arithmetic anywhere
in this file — every rule is a bucket-tier requirement, a pair, or a count.

Depends on: `02_phenotype_overlays.md` (rules reference tiers/roles defined there).

This file lists 28 rules total across all six phenotypes: `GA01`-`GA02` (2), `AC01`-`AC08` (8),
`WT_RULE_01`-`02` (2), `V_RULE_01`-`07` (7), `AL_RULE_01`-`07` (7), `AA_RULE_01`-`02` (2). See
`07_combinations_detailed/` for every one of these worked through end-to-end with exact
contributing sign IDs and a worked example.

## Schema

```json
{
  "phenotype": "ATTRwt",
  "rule_id": "WT_RULE_01",
  "priority": "A",
  "rule_type": "PAIR_TEMPORAL",
  "requires": [
    { "bucket": "ORTHO", "min_tier": 2 },
    { "bucket": "CARDIO", "min_tier": 2 }
  ],
  "temporal_rule_id": "T01",
  "temporal_required": true,
  "output_route": "ATTRWT_REVIEW",
  "notes": "Canonical ATTRwt rule. Temporal sequence upgrades priority; it does not create another bucket."
}
```

`rule_type` values used below: `PAIR` (two buckets, each ≥ min tier), `PAIR_TEMPORAL` (a `PAIR`
plus a required temporal rule from `05_temporal_rules.md`), `PAIR_CLASS` (one specific bucket at a
tier, paired with *any one of* a named class of other buckets), `TRIPLE_WITH_MODIFIER` (two gating
buckets plus one non-gating modifier bucket that only affects priority), `COUNT_DISTINCT_BUCKETS`
(N or more buckets from an allowed set, no specific pair required), `ORG_PLUS_ETIOLOGY` (one organ
bucket paired with one etiologic-context bucket).

"min_tier: 2" means Tier 1 **or** Tier 2 satisfies it — best tier in the bucket, never summed.

## GENERAL_AMYLOID

| Rule ID | Priority | Type | Requires | Notes |
|---|---|---|---|---|
| `GA01` | A | `COUNT_DISTINCT_BUCKETS` | Any 2 independent organ/phenotype buckets, each Tier 1–2, from: `CARDIO, RENAL, NEURO, AUTONOMIC, ORTHO, OCULAR, MUCOSAL_CUTANEOUS, GI_HEPATIC` | Tier 3/4 never supplies the second bucket. Same biological process cannot be counted twice across source specialties. |
| `GA02` | A/B | `ORG_PLUS_ETIOLOGY` | 1 organ/phenotype bucket Tier 1–2 + 1 etiologic-context bucket Tier 1–2 from: `HEME_CLONAL, INFLAMMATORY_DRIVER, HEREDITARY` | Etiology context alone never passes; it must pair with objective organ/phenotype evidence. |

Output route: `GENERAL_AMYLOID_REVIEW`.

## ATTR_COMMON

| Rule ID | Priority | Requires | Notes |
|---|---|---|---|
| `AC01` | A | `ORTHO` Tier 1–2 + `CARDIO` Tier 1–2 | Classic ATTRwt-shaped pair |
| `AC02` | A | `NEURO` Tier 1–2 + `AUTONOMIC` Tier 1–2 | Classic neuropathic ATTRv-shaped pair |
| `AC03` | A/B | `NEURO` Tier 1–2 + `HEREDITARY` Tier 1–2 | Strong hereditary neuropathy pattern |
| `AC04` | B | `NEURO` Tier 1–2 + `CARDIO` Tier 1–2 | Mixed neurologic-cardiac ATTR pattern |
| `AC05` | B | `CARDIO` Tier 1–2 + `HEREDITARY` Tier 1–2 | Allows cardiac-predominant ATTRv |
| `AC06` | B | `NEURO` Tier 1–2 + `OCULAR` Tier 1–2 | Ocular + neurologic ATTRv pattern |
| `AC07` | B/C | `ORTHO` Tier 1–2 + `NEURO` Tier 1–2 | ATTR-common only; subtype requires wt/v-specific logic |
| `AC08` | B | `AUTONOMIC` Tier 1–2 + `HEREDITARY` Tier 1–2 | Hereditary autonomic pattern |

All rule type `PAIR`. **Not every pairwise combination of the six ATTR-common buckets is allowed**
— e.g. `ORTHO + OCULAR` is deliberately absent. An unlisted pair stays at `GENERAL_AMYLOID` only,
not `ATTR_COMMON`. Output route: `ATTR_REVIEW`.

## ATTRwt

| Rule ID | Priority | Type | Requires | Temporal | Notes |
|---|---|---|---|---|---|
| `WT_RULE_01` | A | `PAIR_TEMPORAL` | `ORTHO` Tier 1–2 + `CARDIO` Tier 1–2 | `T01`: ORTHO first evidence precedes CARDIO first evidence | Canonical ATTRwt rule |
| `WT_RULE_02` | B | `PAIR` | `ORTHO` Tier 1–2 + `CARDIO` Tier 1–2 | none required | Use when date quality is insufficient to prove sequence; ranks below `WT_RULE_01` |

Output route: `ATTRWT_REVIEW`. **`ORTHO + CARDIO` is the only pair recognized for ATTRwt** — there
is deliberately no `ORTHO + NEURO` or `CARDIO + NEURO` rule here (see `00_overview.md`, "ATTRwt =
ORTHO+CARDIO only, not any-2-of-3").

## ATTRv

| Rule ID | Priority | Requires | Notes |
|---|---|---|---|
| `V_RULE_01` | A | `NEURO` Tier 1–2 + `AUTONOMIC` Tier 1–2 | Canonical neuropathic/autonomic ATTRv |
| `V_RULE_02` | A | `NEURO` Tier 1–2 + `HEREDITARY` Tier 1–2 | Progressive neuropathy + hereditary context |
| `V_RULE_03` | A/B | `NEURO` Tier 1–2 + `OCULAR` Tier 1–2 | Neurologic + characteristic ocular phenotype |
| `V_RULE_04` | B | `NEURO` Tier 1–2 + `CARDIO` Tier 1–2 | Mixed phenotype |
| `V_RULE_05` | B | `HEREDITARY` Tier 1 + `CARDIO` Tier 1–2 | Allows cardiac-predominant hereditary disease without requiring neuropathy |
| `V_RULE_06` | B | `HEREDITARY` Tier 1–2 + `AUTONOMIC` Tier 1–2 | Hereditary + dysautonomia |
| `V_RULE_07` | Carrier conversion | `HEREDITARY` Tier 1 + `RENAL` Tier 1–2 — **only in known carrier/cascade-testing context** | Routes to `ATTRV_CARRIER_REVIEW`, not `ATTRV_REVIEW` — carrier surveillance is not equivalent to a systemic ATTRv diagnosis |

Rule type `PAIR` for all. Output route: `ATTRV_REVIEW` (except `V_RULE_07` → `ATTRV_CARRIER_REVIEW`).
Neuropathy is **not** mandatory for ATTRv — `V_RULE_05` explicitly allows cardiac-predominant
hereditary disease through.

## AL

| Rule ID | Priority | Type | Requires | Notes |
|---|---|---|---|---|
| `AL_RULE_01` | A | `PAIR` | `HEME_CLONAL` Tier 1–2 + `RENAL` Tier 1–2 | Highest-yield clonal + renal phenotype |
| `AL_RULE_02` | A/B | `PAIR` | `HEME_CLONAL` Tier 1–2 + `CARDIO` Tier 1–2 | Clonal + cardiac amyloid phenotype |
| `AL_RULE_03` | B | `PAIR` | `HEME_CLONAL` Tier 1–2 + `NEURO` Tier 1–2 | Clonal + neuropathy |
| `AL_RULE_04` | B | `PAIR` | `HEME_CLONAL` Tier 1–2 + `AUTONOMIC` Tier 1–2 | Clonal + autonomic organ involvement |
| `AL_RULE_05` | B | `PAIR` | `HEME_CLONAL` Tier 1–2 + `GI_HEPATIC` Tier 1–2 | Clonal + GI/hepatic organ involvement |
| `AL_RULE_06` | A | `PAIR_CLASS` | `MUCOSAL_CUTANEOUS` Tier 1 + any one of `RENAL, CARDIO, NEURO, AUTONOMIC, GI_HEPATIC` Tier 1–2 | Macroglossia/purpura are high-specificity, low-sensitivity |
| `AL_RULE_07` | "Possible AL" | `COUNT_DISTINCT_BUCKETS` | At least 3 organ buckets Tier 1–2, **no `HEME_CLONAL` required** | Output `AL_MONOCLONAL_SCREEN`, **not** `AL_SAFETY_REVIEW`. Do not label AL — this is a funnel into appropriate monoclonal evaluation. |

Output route for `AL_RULE_01`–`06`: `AL_SAFETY_REVIEW`. This is the safety net your plan called
for: an AL-shaped patient without a known clone gets routed to get the clone tested, never
silently labeled AL or silently dropped.

## AA

| Rule ID | Priority | Type | Requires | Notes |
|---|---|---|---|---|
| `AA_RULE_01` | A | `TRIPLE_WITH_MODIFIER` | `INFLAMMATORY_DRIVER` Tier 1–2 + `RENAL` Tier 1–2, **strengthened but not gated by** `INFLAMMATORY_ACTIVITY` Tier 1–2 | Driver + renal transition is the disease-shaped combination. Activity is never an independent bucket. |
| `AA_RULE_02` | B | `PAIR` | `INFLAMMATORY_DRIVER` Tier 1–2 + `RENAL` Tier 1–2 | Use when activity data are missing/weak. Family/genetic susceptibility (`HEREDITARY`) can modify priority but cannot replace driver or renal evidence — it is not a third gating bucket here. |

Output route: `AA_REVIEW`. This is the simplest phenotype in the system by design — one gate,
two priority levels, one optional modifier.

## Ranking within a phenotype

Priority letters (`A` > `B` > `C`) are resolved lexicographically per `00_overview.md`'s ranking
key, never combined into a score. A rule with `Priority A/B` means: `A` if the stronger tier/
temporal condition holds, `B` otherwise — both spellings are the same rule with two possible
outcomes, not two separate rules.

## Review checklist for this file

- [ ] Confirm `ATTRwt` should really have only the one `ORTHO+CARDIO` pair (no ortho+neuro
      fallback) — this is the biggest behavioral departure from a generic "any 2 of 3" system.
- [ ] Confirm `AL_RULE_07`'s ≥3-bucket-no-clone case should route to a screening funnel rather
      than ever being called "AL possible" in patient-facing output.
- [ ] Confirm `AC01`–`AC08` is the complete, correct list of allowed ATTR-common pairs — flag
      any pair you'd add or remove (e.g. should `RENAL + HEREDITARY` be allowed, given `V_RULE_07`
      exists at the ATTRv layer for carriers?).
- [ ] Confirm `V_RULE_07`'s carrier-only restriction and separate output route.

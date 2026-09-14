# Step 5 — Temporal & Composite Rules

Answers: **"Is the longitudinal order/persistence correct, and how are multi-signal workbook rows
derived without inventing an extra bucket?"** This is the last layer — everything here reads
atom-level dates or reads several atoms' outputs, but never creates a new independent bucket of
its own.

Depends on: `01_atoms_layer.md` (dates/trends live on atoms) and `03_combinations.md` (temporal
rules are referenced by `rule_type: PAIR_TEMPORAL` combination rules).

## Two different kinds of non-atom rule

1. **Temporal rules** — compare *when* things happened (date ordering, persistence over time,
   progression across visits).
2. **Composite rules** — a single workbook row that describes a *pattern across atoms* (e.g. "≥2
   systemic red flags," "evidence across ≥3 organ buckets"). These derive a within-bucket tier
   upgrade or trigger a specific downstream action — they never manufacture a bucket that isn't
   already one of the 13 reasoning buckets.

Both kinds share one hard rule: **the guardrail note is always the same** — "do not create an
extra independent bucket." If you ever find yourself wanting to add a 14th bucket called something
like `TEMPORAL` or `COMPOSITE` to the combination engine's organ-bucket list, that's the sign the
rule was implemented wrong.

## Temporal rules schema

```json
{
  "temporal_rule_id": "T01",
  "phenotype": "ATTRwt",
  "pattern": "ORTHO_BEFORE_CARDIO",
  "source_sign_ids": ["WT01"],
  "logic": "First qualifying ORTHO evidence precedes first qualifying CARDIO evidence",
  "threshold_status": "No hard minimum gap; store years_between for ranking/explanation",
  "effect": "Upgrades WT_RULE_01 to Priority A instead of WT_RULE_02's Priority B",
  "guardrail": "Do not create an extra bucket."
}
```

## Full temporal rule set (7 rules)

| ID | Source sign(s) | Phenotype | Pattern | Logic | Effect |
|---|---|---|---|---|---|
| `T01` | WT01 | ATTRwt | `ORTHO_BEFORE_CARDIO` | First qualifying ORTHO evidence precedes first qualifying CARDIO evidence | Upgrades to ATTRwt Priority A |
| `T02` | V02, V04, V14 | ATTRv | `PROGRESSIVE_NEUROPATHY` | Evidence of progression across visits/tests, not one lifetime code | Strengthens NEURO tier reliability |
| `T03` | V01, V17, V18 | ATTRv | `CARRIER_NEW_CHANGE` | Known carrier/family-risk context precedes a new objective neuro/autonomic/renal change | Triggers carrier-conversion review — never call active ATTRv from genotype alone |
| `T04` | AA05, AA12, AA13, AA14 | AA | `PERSISTENT_INFLAMMATORY_BURDEN` | Repeated/persistent activity over time, not one CRP/ESR/SAA value | Strengthens AA priority — inflammatory activity is a modifier, never the second independent bucket |
| `T05` | AA15, AA16, AA17, AA20 | AA | `RENAL_TRANSITION` | New/persistent/progressive renal abnormality after/with the inflammatory driver | Qualifies the RENAL bucket — a single transient abnormality should not trigger the gate |
| `T06` | AL03, AL04, AL06 | AL | `RENAL_PERSISTENCE` | Persistent/progressive proteinuric renal phenotype | Improves renal evidence confidence — avoid single-measurement overcalling |
| `T07` | AL21 | AL | `MULTISYSTEM_ACCUMULATION_OVER_TIME` | Distinct organ buckets accumulate longitudinally | Feeds `AL_RULE_07`'s monoclonal-screen funnel — count distinct buckets, not repeated codes |

## Composite rules schema

```json
{
  "source_sign_id": "V03",
  "phenotype": "ATTRv",
  "derived_rule_id": "NEURO_PLUS_SYSTEMIC",
  "scope": "Cross-bucket composite",
  "definition": "Idiopathic axonal neuropathy + at least 2 ATTRv systemic red flags",
  "effect": "Upgrades ATTRv review priority",
  "guardrail": "Do not add a synthetic extra bucket on top of the component buckets."
}
```

## Full composite rule set (7 rules)

| Source sign | Phenotype | Derived rule ID | Scope | Definition | Effect |
|---|---|---|---|---|---|
| `WT04` | ATTRwt | `ORTHO_CLUSTER` | Within-bucket | Multiple distinct orthopedic red flags across tissues/procedures | Derives ORTHO Tier 1 — counts once as ORTHO, never as multiple specialties |
| `V03` | ATTRv | `NEURO_PLUS_SYSTEMIC` | Cross-bucket | Idiopathic axonal neuropathy + ≥2 ATTRv systemic red flags | Upgrades ATTRv review priority |
| `V06` | ATTRv | `NEURO_CARDIO_MIXED` | Cross-bucket | Neurologic/autonomic phenotype + cardiac phenotype | Upgrades mixed ATTRv combination — equivalent to a combination rule, not a new bucket |
| `AA21` | AA | `RENAL_DISPROPORTIONATE` | Within-bucket | Renal phenotype disproportionate to diabetes/HTN/medication/other explanation, in inflammatory context | May elevate RENAL to Tier 1 — still counts once as RENAL |
| `AL21` | AL | `MULTISYSTEM_ACCUMULATION` | Cross-bucket | Evidence across ≥3 distinct organ-system buckets | Routes to `AL_MONOCLONAL_SCREEN` / raises review priority — MULTISYSTEM is not a 4th bucket |
| `AL26` | AL | `CLONAL_PLUS_NEW_ORGAN` | Cross-bucket | Known monoclonal/plasma-cell precursor + new unexplained organ dysfunction | Direct AL safety escalation — underlying HEME + ORGAN buckets are the actual counted evidence |
| `AL27` | AL | `PREEXISTING_MONOCLONAL_PLUS_ORGAN` | Cross-bucket | Pre-existing abnormal monoclonal studies from unrelated follow-up + new organ signal | Direct AL safety escalation — only pre-test if monoclonal tests predated amyloid suspicion |

## How `WT01` flows through this file specifically

Since you asked about it directly: `WT01` is `T01` here, consuming the ORTHO and CARDIO atoms from
step 1, feeding `WT_RULE_01`/`WT_RULE_02` in step 3. It has no separate composite-rule entry
because it's a pure two-bucket-plus-date-order comparison — no "≥N of a list" counting involved,
unlike `WT04`'s `ORTHO_CLUSTER` (which *is* a composite rule, because it counts how many distinct
orthopedic findings exist before deciding whether ORTHO itself reaches Tier 1).

## Review checklist for this file

- [ ] Confirm no hard time window (e.g. a forced "5–15 years") should be encoded for `T01` —
      current spec stores `years_between` for ranking/explanation but never gates on it.
- [ ] Confirm `T03`'s carrier-conversion output should route separately from active ATTRv
      (matches `V_RULE_07` in `03_combinations.md`) rather than ever being folded into the same
      review queue.
- [ ] Confirm `AL21`/`AL26`/`AL27`'s relationship: `AL21` counts distinct buckets;
      `AL26`/`AL27` require a specific clonal-plus-organ pattern. Confirm these three should stay
      as three separate composite rules rather than being merged.

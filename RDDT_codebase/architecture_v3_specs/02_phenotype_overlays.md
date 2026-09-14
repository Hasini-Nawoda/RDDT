# Step 2 — Phenotype Overlays

Answers: **"How important is this atom, for this specific phenotype?"** This is the layer where
the same atom gets a different tier depending which of the six phenotypes is asking.

Depends on: `01_atoms_layer.md` (every `atom_id` referenced here must exist there first).

## Why this layer exists separately from atoms

Apical sparing on strain echo is a strong signal that *some* cardiac amyloid is present
(`GENERAL_AMYLOID: Tier 1`), a moderate ATTRwt subtype discriminator (`Tier 2`), and only weakly
discriminates ATTRv (`Tier 3`, non-gate-eligible). One atom, three different weights. Baking any
one of those numbers into the atom itself would be wrong for the other two phenotypes.

## Schema

```json
{
  "atom_id": "orthostatic_hypotension",
  "overlays": {
    "ATTRv": {
      "tier": 2,
      "role": "POSITIVE_EVIDENCE",
      "gate_eligible": true,
      "bucket_override": null
    },
    "AL": {
      "tier": 3,
      "role": "POSITIVE_EVIDENCE",
      "gate_eligible": false,
      "bucket_override": null
    },
    "GENERAL_AMYLOID": {
      "tier": 2,
      "role": "ORGAN_OR_PHENOTYPE_EVIDENCE",
      "gate_eligible": true,
      "bucket_override": null
    },
    "ATTR_COMMON": {
      "tier": 2,
      "role": "ATTR_COMMON_EVIDENCE",
      "gate_eligible": true,
      "bucket_override": null
    }
  }
}
```

An atom only gets an entry for the phenotypes that actually use it. Nothing requires every atom to
appear in all six phenotype files.

## Field meanings

| Field | Meaning |
|---|---|
| `tier` | 1 (strongest) to 4 (weakest) for **this phenotype only**. Never summed with any other atom's tier. `"GUARDRAIL"`, `"COMPOSITE"`, `"TEMPORAL"`, or `"DO_NOT_USE"` in place of a number marks a non-tiered row — see `04_guardrails.md` / `05_temporal_rules.md`. |
| `role` | `POSITIVE_EVIDENCE` (phenotype-specific atom score), `ORGAN_OR_PHENOTYPE_EVIDENCE` (used by the `GENERAL_AMYLOID` gate), `ETIOLOGIC_CONTEXT` (etiology-only evidence — e.g. `HEREDITARY`, `HEME_CLONAL`, `INFLAMMATORY_DRIVER` — that can pair with one organ bucket but never passes `GENERAL_AMYLOID` alone), `MODIFIER` (raises/lowers confidence in a bucket that's already gate-eligible from something else — never gate-eligible on its own), `ATTR_COMMON_EVIDENCE` (used by `ATTR_COMMON` pair rules), `TEMPORAL_RULE` / `COMPOSITE_RULE` / `GUARDRAIL_OR_ROUTE` (non-tiered, see later steps). |
| `gate_eligible` | Whether Tier 1–2 evidence here can satisfy one side of a combination rule for this phenotype. Tier 3–4 and all `MODIFIER` rows are always `false` — context only, never gate-forming. |
| `bucket_override` | `null` unless this (atom, phenotype) pair is one of the two documented exceptions in `01_atoms_layer.md` (`gi_dysmotility`, `gastroparesis_early_satiety`), in which case it names the overriding bucket. |

## Worked example across all four applicable phenotypes: `ATOM_WT04` (multiple orthopedic red flags)

| Phenotype | Tier | Role | Gate-eligible |
|---|---|---|---|
| ATTRwt | 1 | `POSITIVE_EVIDENCE` | Yes |
| GENERAL_AMYLOID | 2 | `ORGAN_OR_PHENOTYPE_EVIDENCE` | Yes |
| ATTR_COMMON | 1 | `ATTR_COMMON_EVIDENCE` | Yes |
| ATTRv, AL, AA | — | not referenced | — |

Same atom, same extraction logic, three different weights, zero addition between them.

## Worked example of a `MODIFIER` (never gate-forming): `ATOM_AA13` (persistently elevated SAA)

| Phenotype | Tier | Role | Gate-eligible |
|---|---|---|---|
| AA | 1 | `POSITIVE_EVIDENCE` | **No — modifier/context only** |
| GENERAL_AMYLOID | 2 | `MODIFIER` | No |

Even at Tier 1, this never satisfies a bucket combination by itself. It can only strengthen the
*priority* of a combination that is already satisfied by `INFLAMMATORY_DRIVER` + `RENAL` (see
`AA_RULE_01` in `03_combinations.md`). This is the concrete mechanism behind your rule: *"repeated
flares/CRP/SAA strengthens priority but is NOT an independent bucket."*

## Worked example of `ETIOLOGIC_CONTEXT` (pairs with one organ, never alone): `ATOM_V01` (known pathogenic TTR variant)

| Phenotype | Tier | Role | Gate-eligible |
|---|---|---|---|
| ATTRv | 1 | `POSITIVE_EVIDENCE` | Yes |
| GENERAL_AMYLOID | 2 | `ETIOLOGIC_CONTEXT` | Yes (but only pairs with one organ/phenotype bucket — see `GA02` in `03_combinations.md`) |
| ATTR_COMMON | 1 | `ATTR_COMMON_EVIDENCE` | Yes |

`HEREDITARY`, `HEME_CLONAL`, and `INFLAMMATORY_DRIVER` atoms all follow this pattern for
`GENERAL_AMYLOID`: a genetic/clonal/inflammatory context alone never proves systemic amyloid —
it must pair with actual organ evidence.

## Build rule

The full overlay set (one entry per (atom, phenotype) pair the workbook defines — roughly 300
pairs across ~88 atoms and up to 6 phenotypes each) is transcribed directly from the **Phenotype
Overlays** sheet of `Amyloidosis_MultiPhenotype_Bucket_Config.xlsx`. That sheet has already been
checked against the workbook's own internal logic (unlike the atoms layer, no defects were found
in it) — the only edits going into JSON are:

1. Renaming `Canonical_Atom_or_Rule_ID` values to the corrected `atom_id`s from
   `01_atoms_layer.md` where they changed (e.g. the new `orthostatic_hypotension` replaces
   `AUTONOMIC_ORTHOSTASIS`/`orthostatic`/`orthostatic_intolerance`/`dysautonomia` confusion).
2. Adding `bucket_override` only for the two documented exception atoms.

No new tiers, roles, or gate-eligibility decisions are being made here — this file just restates
the schema so you can sanity-check the *rules*, not re-review all ~300 rows (those were already
extracted and shown to you correctly across the ATTRwt/ATTRv/AL/AA answers earlier in this
conversation).

## Review checklist for this file

- [ ] Confirm the six role types (`POSITIVE_EVIDENCE`, `ORGAN_OR_PHENOTYPE_EVIDENCE`,
      `ETIOLOGIC_CONTEXT`, `MODIFIER`, `ATTR_COMMON_EVIDENCE`, plus the non-tiered rule roles)
      cover every case you need, or if a phenotype needs a role this list is missing.
- [ ] Confirm `gate_eligible` should always be `false` for Tier 3/4 and all `MODIFIER` rows —
      i.e. no phenotype is allowed a "weak organ evidence still counts" exception.
- [ ] Confirm the build rule (transcribe from the workbook's Phenotype Overlays sheet, renaming
      only the corrected atom IDs) is the right approach, vs. wanting every row re-shown here
      first.

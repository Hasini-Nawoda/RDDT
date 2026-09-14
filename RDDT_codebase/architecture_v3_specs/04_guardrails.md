# Step 4 — Guardrails

Answers: **"Does this evidence require a different or parallel funnel?"** Nothing in this file
is ever positive evidence for the phenotype it appears under, and nothing here is ever subtracted
from anything. A guardrail fires a `ROUTE_TO_X` tag alongside whatever else the patient already
passed — it never blocks, never discounts, never becomes Tier 4.

Depends on: `01_atoms_layer.md` (some guardrails reference atom-level findings, e.g. MGUS) and
`03_combinations.md` (a guardrail's route target is one of the phenotypes defined there).

## Schema

```json
{
  "sign_id": "WT25",
  "source_phenotype": "ATTRwt",
  "canonical_id": "HEME_MGUS",
  "reasoning_bucket": "HEME_CLONAL",
  "route": "AL_SAFETY",
  "feature": "Monoclonal gammopathy / MGUS in an otherwise ATTRwt-like phenotype",
  "guardrail_context": "AL is urgent and must be actively excluded. Presence of monoclonal protein invalidates simple non-invasive ATTR attribution and usually requires definitive typing in the clinical pathway.",
  "implementation_rule": "Never convert to Tier 4 positive evidence; route/flag in parallel and allow simultaneous phenotype passes."
}
```

Every guardrail also emits a **mirrored route-target row** in the target phenotype's overlay file
— e.g. `WT27` (found under ATTRwt, routes to AL) also appears as a `ROUTE` row under the `AL`
phenotype pointing back at `WT27`'s canonical ID, marked `gate_eligible: false`,
`"do not double-count it as a new positive atom"`. This is how a single guardrail can surface in
two phenotypes' output without ever creating a second unit of evidence.

## Field meanings

| Field | Meaning |
|---|---|
| `route` | The alternative/parallel phenotype or interpretive instruction this evidence points toward. Never a tier. |
| `guardrail_context` | The clinical reason this must not become simple positive evidence — carried through so a reviewer or downstream UI can explain *why*. |
| `implementation_rule` | Always the same sentence for every guardrail: never Tier 4, always parallel, never subtractive. |

## Full guardrail set (24 rows)

| Sign(s) | Source phenotype | Bucket | Route | Feature |
|---|---|---|---|---|
| `WT24` | ATTRwt | CARDIO | `NO_EXCLUSION_FEMALE_WALL_THICKNESS` | Female ATTR-like phenotype despite septal wall thickness <12 mm |
| `WT25` | ATTRwt | HEME_CLONAL | `AL_SAFETY` | MGUS in an otherwise ATTRwt-like phenotype |
| `WT26` | ATTRwt | HEME_CLONAL | `AL_SAFETY_INTERPRET_FLC_WITH_CKD` | Abnormal FLC ratio in CKD — may reflect renal clearance, not monoclonality |
| `WT27` | ATTRwt | MULTISYSTEM_COMPOSITE | `AL` | Nephrotic proteinuria / macroglossia / periorbital purpura / plasma-cell context |
| `WT28` | ATTRwt | MULTISYSTEM_COMPOSITE | `ATTRv` | Painful PN + marked dysautonomia/GI ± family/ocular signs |
| `WT29` | ATTRwt | MULTISYSTEM_COMPOSITE | `AA` | Chronic inflammatory/infectious driver + persistent inflammatory burden + heavy proteinuria |
| `V32` | ATTRv | CARDIO | `ATTRwt` | Low-flow, low-gradient aortic stenosis |
| `V33` | ATTRv | ORTHO | `ATTRwt` | Isolated orthopedic prodrome (biceps/rotator cuff/trigger finger) without neuro/autonomic clues |
| `V37` | ATTRv | NEURO | `ANTI_ANCHORING_NOT_EXCLUSION` | Mild/well-controlled diabetes not explaining severe/rapid/ataxic neuropathy |
| `V38` | ATTRv | NEURO | `ALTERNATIVE_NEUROPATHY` | Active autoimmune disease with convincing inflammatory/demyelinating pattern |
| `V39` | ATTRv | MULTISYSTEM_COMPOSITE | `AL` | Nephrotic proteinuria / macroglossia / periorbital purpura / plasma-cell context |
| `V40` | ATTRv | MULTISYSTEM_COMPOSITE | `AA` | Chronic inflammatory/infectious driver + new proteinuria/nephrotic phenotype |
| `V41` | ATTRv | MULTISYSTEM_COMPOSITE | `ATTRwt` | Older patient, isolated cardiac phenotype, long orthopedic prodrome, little/no neuropathy |
| `AA25` | AA | CARDIO | `AL_OR_ATTR` | HF/conduction disease/cardiac imaging abnormality in a chronic inflammatory patient |
| `AA26` | AA | RENAL | `ALTERNATIVE_RENAL_PROCESS` | FMF + proteinuria with possible non-amyloid kidney disease |
| `AA27` | AA | RENAL | `ALTERNATIVE_RENAL_PROCESS` | Active urinary sediment / hematuria / leukocyturia in an AA-risk patient |
| `AA28` | AA | MULTISYSTEM_COMPOSITE | `AL` | Known monoclonal gammopathy/plasma-cell dyscrasia with proteinuria/multisystem features |
| `AA29` | AA | MULTISYSTEM_COMPOSITE | `ATTR` | Classic ATTR orthopedic prodrome (bilateral/recurrent CTS, LSS, biceps rupture) → cardiac disease |
| `AA30` | AA | SYSTEMIC_CONTEXT | `AA_UNCERTAIN_NO_DRIVER` | No identified chronic inflammatory/infectious driver despite adequate longitudinal history |
| `AL22` | AL | ORTHO | `ATTRwt` | Bilateral/recurrent CTS years before cardiac disease |
| `AL23` | AL | ORTHO | `ATTRwt` | Long orthopedic prodrome (LSS / biceps rupture / multiple tendon-hand procedures) |
| `AL25` | AL | MULTISYSTEM_COMPOSITE | `AA` | Credible chronic inflammatory/infectious history + new persistent proteinuria |
| `AL30` | AL | MULTISYSTEM_COMPOSITE | `ATTRwt` | Older, isolated cardiac phenotype + AF/CTS, little renal/GI/clonal evidence |
| `AL31` | AL | MULTISYSTEM_COMPOSITE | `ATTRv` | Painful small-fiber PN with early marked autonomic/GI dysfunction ± hereditary clues |

## `DO_NOT_USE` rows (not guardrails, but also never positive evidence)

| Sign | Phenotype | Feature | Rule |
|---|---|---|---|
| `WT30` | ATTRwt | Elevated serum uric acid | Retain for provenance/audit/research only — never a screening trigger |
| `V36` | ATTRv | Declining serum prealbumin | Retain for provenance/audit/research only — never a screening trigger |

## The mirrored-route mechanism, worked example

`WT27` lives under ATTRwt with `route: AL`. It also appears a second time, under the `AL`
phenotype's overlay file, as:

```json
{
  "canonical_id": "RULE_AL_ORIENTED_MULTISYSTEM",
  "phenotype": "AL",
  "role": "ROUTE",
  "route": "ROUTE_TO_AL",
  "gate_eligible": false,
  "note": "This source row points to the target phenotype; do not double-count it as a new positive atom."
}
```

The second entry is documentation, not a second unit of evidence — it lets a router or UI say "AL
is worth checking here" without letting `WT27`'s findings also silently satisfy an AL combination
rule from `03_combinations.md`. If a patient's actual AL-relevant atoms (e.g. `RENAL_NEPHROTIC_PROTEINURIA`,
`MUCOSAL_CUTANEOUS`) are present, they earn AL combination status on their own merits through the
normal path — the guardrail route is a *suggestion to look*, not a substitute for evidence.

## Review checklist for this file

- [ ] Confirm every route target above is correct — in particular `AA25 → AL_OR_ATTR` (a
      guardrail with two possible targets) and `AA29`/`WT29`/`V40` routing to the umbrella `AA`
      or `ATTR` rather than a specific subtype.
- [ ] Confirm `WT30` and `V36` should remain fully inert (no route, no tier, audit-only) rather
      than eventually feeding a research-only scoring layer.
- [ ] Confirm the mirrored-route mechanism (guardrail appears once under its source phenotype,
      once as a non-scoring `ROUTE` marker under its target phenotype) is how you want dual-phenotype
      output surfaced, vs. some other UI/output convention.

# Atom content audit — method

This is a different kind of check than everything in `01_atoms_layer.md`. That file checked
*structure* — is every sign_id linked to *an* atom, in the *right bucket*, under the *right
phenotype*. This audit checks *content* — for every sign_id, does `atom_index.csv` actually list
every EHR-detectable finding that sign describes, and does it avoid listing findings that don't
belong to any of these four sign rows at all?

## Where the checklist comes from

Every row in the four source CSVs already has an **"Example structured fields / NLP terms"**
column — the CSV authors already drafted candidate search terms per sign. That column, plus the
sign's own title and "Quantitative / comparative evidence" text, is the ground truth this audit
checks `atom_index.csv` against. Nothing here is invented — it's all re-derived from your four
CSVs.

## Three kinds of finding in this audit

1. **Correctly present** — the atom exists in `atom_index.csv`, tagged with the right sign_id(s).
2. **Present but mistagged** — the atom exists (e.g. `ligamentum_flavum_thickening`) but its
   `Excel sign IDs` column is blank or wrong, so nothing currently traces it back to the sign that
   actually mentions it.
3. **Orphan** — the atom exists in `atom_index.csv` but has **no connection to any sign in the
   four CSVs at all**. This is the "unrelated" half of your worry. It doesn't necessarily mean the
   atom is clinically wrong (some are real ATTR findings from the broader literature) — it means
   it isn't grounded in *this* source material, and needs an explicit decision: keep it as a
   deliberate addition, or drop it.

There's a fourth category worth naming separately: **helper atoms**. Some atoms (like
`cts_left`/`cts_right`) aren't meant to map to one sign directly — they're building blocks a
composite rule combines (e.g. "left CTS code + right CTS code on different dates" = bilateral).
These should still be tagged with the sign(s) they help construct, just flagged as helper role
rather than final/reportable role.

## ORTHO domain — full sign-by-sign result

| Sign(s) | What the CSV says to search for (its own NLP-terms column) | Current `atom_index.csv` status |
|---|---|---|
| `WT02`, `V13`, `AL22` (bilateral/recurrent CTS — shared canonical concept) | "bilateral carpal tunnel; right+left CTR; recurrent median neuropathy; repeat carpal tunnel release" (WT02); "bilateral CTS; recurrent CTS; carpal tunnel release; persistent numbness after release" (V13) | `cts_bilateral`, `cts_recurrent`, `ctr_any`, `cts_any`, `cts_left`, `cts_right`, `cts_persistent_after_release` all exist — **but every one has a blank `Excel sign IDs` column.** None are wrong content, they're just untraced. **Fix: tag all seven with `WT02, V13, AL22`.** |
| `WT03` (distal biceps rupture) | "distal biceps rupture; atraumatic biceps rupture; Popeye sign" | `biceps_rupture` exists, correctly tagged `WT03`. ✅ Correct. |
| `WT04` (composite — not a searchable atom, see `01_atoms_layer.md`) | n/a — this is a count rule over the other six ORTHO signs | Correctly has no atom of its own in `atom_index.csv`. ✅ Correct (confirmed absent). |
| `WT05`, `V30` (lumbar stenosis/decompression, ligamentum flavum) | "lumbar spinal stenosis; laminectomy; decompression; ligamentum flavum hypertrophy" (WT05) | `lumbar_stenosis` and `lumbar_decompression` are correctly tagged `V30, WT05`. ✅ Correct. `ligamentum_flavum_thickening` exists but has a **blank** sign ID — it's WT05's own explicit finding ("thickened ligamentum flavum"). **Fix: tag it `WT05`.** |
| `V30` specifically (its own extra qualifier: persistent symptoms *after* decompression) | Title: "...with persistent lower-limb symptoms" | `persistent_lower_limb_symptoms_after_decompression` exists but has a **blank** sign ID. **Fix: tag it `V30`.** |
| `WT06` (hip/knee arthroplasty) | "THA; TKA; total hip replacement; total knee replacement; bilateral arthroplasty" | `arthroplasty` exists, correctly tagged `WT06`. ✅ Correct. **Gap:** the CSV explicitly calls out *bilateral* arthroplasty as a stronger signal than unilateral — there's no separate `arthroplasty_bilateral` atom the way there is for CTS. Worth deciding whether that distinction matters enough to split out (see recommendation below). |
| `WT07` (trigger finger) | "trigger finger; stenosing tenosynovitis; trigger release" | `trigger_finger` and `trigger_release`, correctly tagged `WT07`. ✅ Correct. **Check needed (not visible from `atom_index.csv` alone):** does `trigger_finger`'s actual keyword list in `atoms/ortho.json` include the phrase "stenosing tenosynovitis," or only "trigger finger"? The CSV lists it as a synonym — if the keyword list is missing it, a chart that only says "stenosing tenosynovitis" would be missed. |
| `WT08` (rotator cuff / shoulder) | "rotator cuff tear; shoulder arthroplasty; rotator cuff repair" | `rotator_cuff`, `rotator_cuff_repair`, `shoulder_disorder`, all correctly tagged `WT08`. ✅ Correct. **Gap:** the CSV's own term list includes "shoulder arthroplasty" specifically — worth checking whether that's covered by `rotator_cuff_repair`'s codes or needs its own code entry (shoulder arthroplasty has different CPT codes than rotator cuff repair). |
| `V33` (guardrail: isolated ortho prodrome without neuro — biceps/rotator cuff/trigger finger) | "biceps rupture; rotator cuff tear; trigger finger; tenosynovitis" | No new atom needed — reuses `biceps_rupture`, `rotator_cuff`, `trigger_finger` exactly as already tagged. ✅ Correct that no separate atom exists; this is a guardrail composite, not a new finding. **Minor gap:** "tenosynovitis" as a standalone general term (not just trigger-finger-specific) isn't obviously covered — see `WT07` note above. |
| `AL23` (guardrail: long ortho prodrome — LSS/biceps/"multiple tendon-hand procedures") | "lumbar stenosis; biceps rupture; trigger finger; tendon surgery" | Reuses `lumbar_stenosis`, `biceps_rupture`, `trigger_finger`. The phrase "multiple tendon-hand procedures" is broader than any single existing atom — it's meant to be satisfied by *any combination* of the CTS/trigger-finger/Dupuytren-style procedures, which is a composite/count concept (like `WT04`), not a single atom. **No new atom needed, but this composite relationship isn't documented anywhere yet** — worth adding to `05_temporal_rules.md`'s composite rules table. |
| `AA29` (guardrail: classic ATTR ortho prodrome — CTS/LSS/biceps → cardiac) | "carpal tunnel release; bilateral CTS; lumbar stenosis; biceps rupture" | Reuses existing atoms exactly. ✅ Correct, no new atom needed. |

## Orphan atoms found — not grounded in any of the four CSVs

| Atom | Exists in `atom_index.csv` as | Found in any of the 4 CSVs? |
|---|---|---|
| `achilles` | "Achilles tendon thickening or spontaneous rupture" | **No.** I re-checked all 133 rows across ATTRwt/ATTRv/AL/AA — there is no Achilles-tendon sign anywhere in these four sheets. |
| `dupuytren` | "Dupuytren's contracture" | **No.** Same check, not present anywhere in the four CSVs. |
| `congo_red` | "Congo red / amyloid tissue confirmation" | **No** — and this one is a different *kind* of problem, not just "missing from these CSVs." Congo red staining is the definitive biopsy confirmation of amyloid, performed *after* amyloid is already suspected and biopsied. Using it as a pre-test screening atom would be circular — by the time Congo red is positive, the whole point of this pre-test model (finding patients *before* diagnosis) has already been achieved by something else. This matches the same logic your ATTRwt CSV already applies to `WT20` (incidental bone scan) — a confirmatory test is only usable pre-test if it was ordered for an unrelated reason, and Congo red staining is never ordered for an unrelated reason. |

**These three are real ATTR-literature findings (Achilles/Dupuytren tenosynovitis genuinely appear
in broader ATTR musculoskeletal reviews, and Congo red is the real gold-standard stain) — they
just aren't represented as sign rows in the four CSVs you gave me.** They likely carried over from
your earlier v2 build (`ortho_features.json` had `O_T3_ACHILLES` and `O_T4_DUPUYTREN` as real
Tier 3/4 features in the old system). The decision isn't "these are wrong" — it's **"do you want
this new system to include findings beyond the four CSVs, or be strictly limited to what's in
them?"** If you want them kept, they need their own tier/bucket/phenotype treatment the same as
every other atom (right now they have none — no tier, no bucket, no phenotype overlay reference
anywhere) and someone needs to write the equivalent of a 134th "sign row" for each, since they
don't exist in the four sheets I was given. If you want strict scope, they should be removed from
`atom_index.csv` and their entries in `atoms/ortho.json`.

## ORTHO summary

- **1 sign group** (bilateral/recurrent CTS) has **7 atoms that need their sign-ID tags fixed** —
  content is fine, traceability is broken.
- **2 individual atoms** (`ligamentum_flavum_thickening`, `persistent_lower_limb_symptoms_after_decompression`)
  need the same sign-ID fix.
- **2 small content gaps** worth checking at the keyword level (stenosing tenosynovitis phrasing,
  shoulder arthroplasty CPT codes) — can't be confirmed from `atom_index.csv` alone, need to look
  at the actual `atoms/ortho.json` keyword/code lists.
- **3 orphan atoms** (`achilles`, `dupuytren`, `congo_red`) not grounded in the four CSVs, needing
  an explicit in-or-out decision.
- **1 undocumented composite relationship** (`AL23`'s "multiple tendon-hand procedures") that
  should be added to the composite rules table.
- **Zero missing signs** — every ORTHO sign_id in the four CSVs (`WT02`–`WT08`, `V13`, `V30`,
  `V33`, `AL22`, `AL23`, `AA29`) does have *some* representation in `atom_index.csv`, which is
  better news than the tier/bucket audit found.

## Before I continue to the other eleven domains

This took checking every ORTHO sign's own NLP-terms column, cross-referencing every candidate
atom, and separately verifying the three suspicious atoms against all 133 rows (not just ORTHO) to
confirm they really don't appear anywhere. That's the level of care the remaining ~110 signs need
too, which will take a while across CARDIO, NEURO, AUTONOMIC, RENAL, HEME_CLONAL,
INFLAMMATORY_DRIVER, INFLAMMATORY_ACTIVITY, OCULAR, HEREDITARY, MUCOSAL_CUTANEOUS, GI_HEPATIC, and
SYSTEMIC_CONTEXT.

**Question before I proceed:** is this the right level of detail (sign-by-sign, with the
correctly-present / mistagged / orphan / undocumented-composite categories), or do you want
something adjusted — e.g. skip the "gaps I can't confirm without reading the actual JSON keyword
lists" callouts and I go read those files directly so every finding is fully confirmed rather than
flagged as "check needed"?

# V5 sample pipeline evaluation

Evaluation date: 2026-09-22

## Outcome

The supplied 50-row files cannot produce a real five-table patient profile.
The files contain no patient ID shared by any pair of tables, and therefore no
patient shared by all five tables. Joining one row from each file under a new
patient ID would fabricate a clinical record and was not done.

The samples still support a claims-only execution test and a source-plumbing
stress test. Both completed and exposed pipeline behavior that needs to be
corrected before judging clinical recall from warehouse data.

## Patient overlap

| Table | Rows | Distinct patients |
|---|---:|---:|
| CENSUS | 50 | 50 |
| CLAIMS | 50 | 4 |
| ENCOUNTERS | 50 | 50 |
| LABS | 50 | 50 |
| SURGICAL_HISTORY | 50 | 49 |

All ten pairwise patient intersections are zero. The all-five intersection is
also zero.

## Claims-only run

The V5 pipeline ran all 50 claim rows for the four claim patients in
`claims_only_v1` with recall evaluation enabled.

| Stage | Count |
|---|---:|
| Candidate patients | 4 |
| Source events | 50 |
| Atom matches | 18 |
| Qualified evidence rows | 18 |
| Signal rows | 292 |
| Combination rows | 88 |
| Router rows | 12 |
| All-patient verdict rows | 4 |
| Patient profiles | 0 |

No exact configured ATTR or AL confirmation code was present. All four
patients received ATTR=`HOLD` and AL=`HOLD`; none was marked as a review
candidate, so no suspicion profile was generated.

This is partly appropriate because the four random claim patients do not have
a strong configured multisystem pattern. However, the specific `HOLD` result
is misleading. The router promotes any combination with
`INCOMPLETE_OR_UNKNOWN_EVIDENCE` to HOLD, including combinations made unknown
only because unrelated configured signals are non-executable or absent. That
causes a universal HOLD tendency instead of distinguishing no match,
source-unassessable, and a genuine evidence hold.

## Five-table source-plumbing run

The five independent files were supplied together under the
`all_available_v1` contract without altering patient IDs. This does not create
full profiles; it tests whether each source can move through normalization and
reasoning without crashing.

| Stage | Count |
|---|---:|
| Evaluated patients | 153 |
| Source events | 270 |
| Atom matches | 90,937 |
| Qualified evidence rows | 90,937 |
| Signal rows | 11,169 |
| Router rows | 459 |
| Patient profiles | 0 |

The 153 patients are the union of patients in the enabled algorithm tables.
CENSUS is profile-only and shares no patients with those tables.

The 90,937 matches are not clinical matches. They consist of:

- 18 exact ICD-10 claim-code matches;
- 67,850 `NLP_CONFIG_GAP_NO_PHRASEMATCHER` rows generated from 50 repeated
  surgical category labels; and
- 23,069 `NLP_CONFIG_GAP_NO_PHRASEMATCHER` rows generated from 17 lab notes.

The current matcher emits one unknown row for every configured NLP term on
every text-bearing event when an NLP runtime is unavailable. This is an
operational gap representation, but it creates a large false workload and
obscures the 18 real structured matches. V5 should represent NLP availability
once at the source/run level and should not expand generic surgical metadata
as clinical narrative.

All 153 patients ended with ATTR=`HOLD` and AL=`HOLD`. No patient profile was
generated. This reproduces the router issue seen in the claims-only run.

## Required corrections before cohort evaluation

1. Treat `SURGICAL_HISTORY.CATEGORY` as metadata rather than clinical
   narrative. Keep its SNOMED codes and date as the evidence-bearing fields.
2. Replace per-term NLP-gap atom expansion with a bounded run/source
   capability record. Missing NLP infrastructure must remain transparent but
   must not create tens of thousands of pseudo-matches.
3. Route `INCOMPLETE_OR_UNKNOWN_EVIDENCE` separately from a genuine HOLD.
   `HOLD_DUPLICATE_LINEAGE` and explicit clinical blockers may remain holds;
   source-unassessable combinations should remain UNKNOWN unless recall rules
   promote observed code support to a review candidate.
4. Generate a transparent profile for review candidates and confirmed
   patients, showing observed support, unavailable context, missing expected
   context, and explicit blockers separately.
5. Re-run on a real linked cohort extracted with
   `sql/extract_linked_evaluation_cohort.sql` and compare strict versus recall
   results before changing clinical atoms or signal definitions.

## Data still needed

The linked-cohort SQL selects up to 20 real patients represented in all five
authorized tables, prioritizes exact E85 and high-yield suspicion-code paths,
and provides claim/encounter and lab/encounter join diagnostics. Its five
exports preserve the native columns required for an end-to-end V5 run.

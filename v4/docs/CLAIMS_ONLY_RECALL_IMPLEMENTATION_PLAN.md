# Claims-only high-recall implementation plan

## Goal

Run the same ATTR (ATTRv plus ATTRwt) and AL pipeline in two evidence modes:

- `STRICT`: preserve the current clinical-evidence behavior for the future all-table run.
- `CLAIMS_RECALL`: prefer sensitivity when only exact claim diagnosis codes and encounter identifiers are available.

The claims-only result is a screening/review candidate, not a diagnosis. A rule that passes only because unavailable evidence was relaxed must never be labelled as an ordinary strict phenotype pass.

## Audit findings

The claims table can provide patient identity, encounter identity, ICD-10-CM diagnosis type, and diagnosis code. It cannot provide event dates, narrative text, lab interpretation, measurement trends, or enough context to establish qualifiers such as progressive, persistent, recurrent, unexplained, or specialist-confirmed.

Configuration audit of the current v4 package found:

| Area | ATTRv | ATTRwt | AL |
|---|---:|---:|---:|
| ICD-10 atoms referenced by phenotype mappings | 50 | 46 | 57 |
| Claim-code mappings marked non-firing/support-only | 43 | 40 | 68 |
| Signals touched by those mapping restrictions | 23 | 17 | 25 |
| Normalized rule members with context/longitudinal requirements | 42 | 16 | 20 |
| Runtime non-executable signals that still map claim codes | 14 | 1 | 1 |

All 666 shared ICD-10 terminology rows currently allow the atom itself to fire. Therefore the principal claims-only attrition is not a blanket NLP requirement at terminology matching. It is caused by:

1. the global missing availability-date gate;
2. missing rule qualifiers and linked/temporal evidence;
3. signal/runtime restrictions for data sources that are absent from claims;
4. combination chronology requirements.

The NLP-over-code precedence rule suppresses a code only when an actual matching NLP span is present for the same atom. With a genuinely claims-only source there is no text span, so missing NLP by itself does not suppress an otherwise eligible exact code.

## Claims-recall policy

Only exact structured claim evidence is eligible for relaxation. A relaxation changes an unavailable fact into a provisional assumption; it does not manufacture a date, NLP assertion, lab value, or negative finding.

Relax in `CLAIMS_RECALL` when the fact is unobservable from claims:

- missing availability/event date or chronology;
- missing pre-test stage that depends only on the unavailable date;
- missing longitudinal qualifiers such as progressive, persistent, recurrent, chronic, rising/falling, new/worsening, comparable trend, or duration;
- missing narrative/context qualifiers such as unexplained, disproportionate, compatible, specialist-confirmed, or clinically significant;
- candidate/support-only mapping restrictions when an exact structured claim code matched;
- missing clinical-episode linkage when claim encounters do not establish the configured relationship;
- runtime non-executable status when the configured rule is otherwise supported by exact claim codes.

Do not relax:

- code-system compatibility or exact-code semantics;
- patient identity or source lineage;
- an observed FALSE qualifier, negation, explicit competing diagnosis blocker, or temporal contradiction;
- duplicate-lineage/independence requirements;
- confirmed ATTR or confirmed AL exclusion;
- a rule arm for which no configured code evidence exists.

## Output contract

Every relaxed evidence, signal, combination, and patient result carries:

- `evaluation_mode=CLAIMS_RECALL`;
- `provisional=true`;
- explicit `relaxations` explaining what could not be observed.

A combination supported without relaxation retains `PHENOTYPE_PASS`. A combination requiring one or more claims-only assumptions is routed as `CLAIMS_RECALL_CANDIDATE`, with a review-oriented suspicion label. `NO_MATCH` means no configured route matched within the claims-only scope; it must not be presented as a definitive absence of disease.

## Implementation sequence

1. Add one shared evaluation-policy module and keep `STRICT` as the default everywhere.
2. Teach evidence qualification to retain exact claim codes provisionally when only a claims-unobservable gate fails.
3. Teach signal evaluation to provisionally satisfy missing claim-unobservable qualifiers and chronology/linkage, while preserving explicit FALSE and blocker behavior.
4. Propagate provisional status and reasons through combinations and routing.
5. Expose `evaluation_mode` on both reference and warehouse entry points; no duplicate clinical configuration is introduced.
6. Add focused regression tests proving strict behavior is unchanged and claims-recall widens only exact structured claim evidence.
7. Emit a lightweight all-patient verdict ledger without running the expensive
   signal engine for patients who have no configured candidate evidence.
8. Enrich undated claims from the encounter table only when that table is an
   enabled algorithm source, using an exact patient-plus-encounter join. Keep
   conflicting dates unknown and preserve claims-only source isolation.

## Implemented safeguards and adjacent corrections

- Exact E85 ICD-10 confirmation now runs before suspicion scoring and does not
  require a date.
- Named AL priority policies resolve directly to their configured A/B/C class;
  they no longer fall through as an unknown tier.
- The population ledger distinguishes `NO_CANDIDATE_EVIDENCE` from an
  evaluated `NO_MATCH`, and includes ATTRv, ATTRwt, combined ATTR, and AL in
  every row.
- The all-table path can restore claim dates from a unique matching encounter;
  the claims-only profile never uses profile-hydration encounter rows.

# ATTRwt V4 clinical/configuration audit

Date: 2026-09-20  
Audited source: `v4_build_tools/source/ATTRwt_Normalized_Clinical_Filtering_Config_FINAL.xlsx`  
Audited deployable package: `v4/config` (shared atoms plus ATTRV and ATTRWT phenotype packages)

## Conclusion

The corrected ATTRwt configuration is internally coherent and clinically aligned for phenotype-based early detection and review routing. It produces one ATTRwt suspicion verdict from phenotype-pass combinations and preserves AL, hereditary ATTR, AA, and diagnostic-workup findings as separate parallel routes. It does not treat phenotype evidence as a definitive amyloid subtype diagnosis.

This is a logic/configuration audit, not prospective clinical validation, diagnostic-performance validation, or clinician sign-off.

## Disputed atom decisions

### `pyp_grade_2_3`

Removed from the pre-test atom and terminology catalog. Grade 2/3 bone-tracer uptake belongs to the diagnostic pathway and must not independently fire an early-detection phenotype. WT20 retains an explicit diagnostic-stage exclusion and its incidental-tracer route.

### `wt06_osteoarthritis`

Removed as an orphan atom, not converted into a blocker. Osteoarthritis can coexist with wild-type transthyretin deposition and therefore must not erase a qualified arthroplasty clue. WT06 still requires multiple/bilateral arthroplasty plus independent ATTR-compatible evidence.

### `wt30_competing_hyperuricemia`

Removed as an orphan atom. WT30 is explicitly non-firing research/prognostic context, so a competing-explanation atom attached to no executable rule or blocker has no valid runtime role.

## Other corrections made

- Removed WT14's aortic-stenosis whole-signal blocker because aortic stenosis can coexist with ATTR-CM.
- Removed WT16's prior-MI whole-signal blocker; prior infarction can explain Q waves but must not suppress an independent voltage-to-mass mismatch branch.
- Added `no_matching_infarction_explanation=True` specifically to WT16's pseudo-infarct branch.
- Added explicit signal temporal policies for WT01 and WT29 and implemented them in the phenotype-generic evaluator.
- Set WT14 and WT16 blocker policy to `NONE` after their blockers were removed.
- Added direct hereditary and AA source attribution to WT28 and WT29.
- Normalized combination requirement buckets with the same vocabulary as signal buckets; this repaired the previously unreachable `ORTHOPEDIC`/`ORTHO` arm of WT_COMBO02.
- Deduplicated normalized runtime bucket definitions while retaining all source definitions.
- Removed route-only WT_COMBO03-WT_COMBO05. Their AL, ATTRv, and AA functions remain in dedicated guardrails, preventing duplicate/dead parallel logic.
- Removed diagnostic-stage WT20 and the differential-only WT25/WT27/WT28/WT29 signals from phenotype-pass requirement lists.
- Changed WT_COMBO01 to consume the established WT01 composite rather than separately reimplementing its component and temporal logic.
- Added loader validation for duplicate terms/buckets/combinations/requirements, broken bucket/signal/priority references, and blocker-policy mismatches.

## Mechanical audit results

- Both `ATTRV` and `ATTRWT` packages load successfully through `v4.config_loader`.
- Shared atom universe: 149 atoms and 1,895 terminology rows.
- Every shared atom is referenced by at least one ATTRV or ATTRWT signal/rule/blocker; no orphan shared atoms remain.
- Every referenced atom and signal resolves.
- No duplicate atom IDs, atom/system/value terminology rows, signal IDs, signal-to-atom mappings, signal rules, normalized buckets, combinations, or requirements remain.
- Every atom has terminology.
- ATTRwt: 30 catalog signals, 19 positive/executable signal-view rows, 91 signal-to-atom mappings, 130 structured rule members, 9 clinically scoped blockers, 8 dedicated guardrails, and 2 phenotype-pass combinations.
- All 788 retained structured-code terminology rows are source-verbatim from the supplied ATTRv or ATTRwt workbooks; no code was invented.
- Workbook formula-error scan returned no matches.
- Runtime assertions passed for WT01 ordered/reversed/missing chronology, WT_COMBO02 reachability, WT16 pseudo-infarct qualification, WT29 ordered AA routing, and a single ATTRwt risk verdict with parallel differential routes.
- V4 contains no regex extraction implementation or fallback. NLP terminology remains configured for spaCy/medSpaCy matching.
- V4 warehouse writes are limited to session `TEMPORARY` tables; no permanent-table creation or warehouse write-back path was found.

## Clinical references used

- [2023 ACC Expert Consensus Decision Pathway on Cardiac Amyloidosis](https://www.acc.org/latest-in-cardiology/ten-points-to-remember/2023/01/19/14/49/2023-acc-consensus-on-cardiac-amyloidosis)
- [ACC Concise Clinical Guidance: Transthyretin Cardiac Amyloidosis Evaluation and Management](https://www.jacc.org/doi/10.1016/j.jacc.2025.09.004)
- [ASNC Practice Points: Tc-99m PYP Imaging for Transthyretin Cardiac Amyloidosis](https://www.asnc.org/wp-content/uploads/2024/05/19110-2021-ASNC-Amyloid-Practice-Points-PYP-MAY19-2022-1.pdf)
- [Yanagisawa et al.: wild-type TTR deposition in knee osteoarthritis tissue](https://pubmed.ncbi.nlm.nih.gov/23734638/)
- [GeneReviews: Hereditary Transthyretin Amyloidosis](https://www.ncbi.nlm.nih.gov/books/NBK1194/)
- [Mirioglu et al.: AA Amyloidosis—A Contemporary View](https://pubmed.ncbi.nlm.nih.gov/38568326/)

## Remaining validation boundary

Snowflake source access, real warehouse column compatibility, spaCy/medSpaCy model behavior on production notes, and clinical operating characteristics (sensitivity, specificity, PPV, calibration, subgroup performance) require execution and validation in the target Snowflake workspace. The current audit does not claim those external results.

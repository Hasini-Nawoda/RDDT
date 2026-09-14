# The Real End-to-End Flow — What Exists, What Runs, What's Missing

This file is grounded in three real artifacts I just read, not generic examples:
`Early Detection/RDDT_Data_Dictionary.xlsx`, `Early Detection/RDDT_ATTR_Snowflake.ipynb`, and the
`atoms/*.json` files we've been editing. Every table name, column name, and code below is real.

## Part 1 — What data actually exists in Snowflake

Ten physical tables, confirmed against both the data dictionary and the notebook's `SOURCE_CONFIG`
(`RDDT_ATTR_Snowflake.ipynb`, cell 6):

| Physical table | Logical name in code | Enabled? | What it holds |
|---|---|---|---|
| `CENSUS` | `census` | Yes | One row per patient: `Member/PatientId`, `BirthDate`, `Gender`, `City`, `State`, `FamilyId` |
| `ENCOUNTER_VISIT` | `encounter` | Yes | `EncounterId/VisitId`, `Member/PatientId`, `Encounter/Visit Date` |
| `CLAIM` | `claim` | Yes | `DiagnosisCode`, `OtherDiagnosisCodes9`, `OtherDiagnosisCodes10`, `ProcedureCode`, `ClinicalNotes`, `FromDate`, `ToDate`, plus provider/specialty fields |
| `LAB` | `lab` | Yes | `ObservationIdentifier`, `ObservationValue`, `LabResultNote`, `ObservationDateTime` |
| `MEDICAL_HISTORY` | `medical_history` | Yes | `Value`, `Source/Category`, `SNOMED`, `Secondary SNOMED`, `Date` |
| `SURGICAL_HISTORY` | `surgical_history` | Yes | Same shape as medical history — this is where CTS release, TAVR, laminectomy live |
| `FAMILY_HISTORY` | `family_history` | Yes | `Condition`, `FamilyMember`, `Status`, `SNOMED`, `Date` |
| `CLINICAL_NOTE` | `clinical_note` | Yes | `Clinical Note Text`, `NoteType`, `Date` — the only source for echo/CMR/EMG narrative |
| `SOCIAL_HISTORY` | `social_history` | **No** | Disabled — "no need" in the data dictionary |
| `MEDICATION` | `medication` | **No** | Disabled — delivered but not wired in yet |

**This is a fact, not a design choice you can revisit lightly:** nothing about the amyloid
phenotype model changes what tables exist. Every atom you build can only ever fire from these
eight enabled tables. If a sign in the four CSVs needs something not in this list (e.g. a discrete
vitals table for the "falling blood pressure over time" signs, `WT18`/`V31`), **it doesn't exist
in this delivery** — the notebook's own gap list (cell 18, `FUTURE_DATA_GAPS`) says so explicitly:
*"Vitals time series — in_v11_schema: False, workaround_today: None."*

## Part 2 — The pipeline that already runs today, stage by stage, with real table names

### Stage 1 — QC (`rddt_attr_sql.py`, notebook cells 8–12)

`rsql.validate_sources()` checks every "need" column from the data dictionary actually exists in
the delivered tables. `rsql.table_qc()` reports null-patient-id counts and row totals per table.
Nothing clinical happens here.

### Stage 2 — Wide net (notebook cells 15–36, produces `ATTR_WIDE_NET_CANDIDATES`)

This is the real mechanism, and it's simpler than it looks: **every candidate atom becomes either
an exact-code check or an `ILIKE '%phrase%'` check against one specific table/column pair,** and
the results across every table are unioned into one patient-ID list.

```
ATTR_CODES["orthopedic_msk"]["exact_icd"]["G56.03"]  →  matched against CLAIM.DiagnosisCode
                                                          (and OtherDiagnosisCodes9/10)
LAB_TERMS  → "%congo red%"                            →  matched against LAB.ObservationValue,
                                                          LAB.ObservationIdentifier, LAB.LabResultNote
SURGICAL_TERMS → "%carpal tunnel release%"            →  matched against SURGICAL_HISTORY.Value
MEDICAL_TERMS → "%unexplained LVH%"                   →  matched against MEDICAL_HISTORY.Value
FAMILY_TERMS → "%sudden death%"                       →  matched against FAMILY_HISTORY.Condition
NOTE_TERMS → "%apical sparing%"                       →  matched against CLINICAL_NOTE.NoteText
```

Five separate `rsql.text_net_patient_ids()` / `rsql.code_net_patient_ids()` calls, one per source
table, each returning a list of patient IDs. `rsql.create_candidates()` unions all five lists into
`ATTR_WIDE_NET_CANDIDATES`. **This step makes no clinical decision.** It exists purely so Stage 3
doesn't have to scan the entire warehouse — it's a cost filter, and it's deliberately loose (a bare
`%TTR%` or `%amyloid%` anywhere is enough to become a candidate).

### Stage 3 — Evidence (notebook cells 38–46, produces `ATTR_EVID_*`)

For every table, one `ATTR_EVID_<TABLE>` temporary table is created, joined down to just the
wide-net candidates, with columns renamed to a common shape (`PATIENT_ID`, `VALUE`, `CODE_VALUE`,
`NOTE_TEXT`, dates). This is where the raw column names from the data dictionary stop mattering —
everything downstream only ever reads `ATTR_EVID_*`.

### Stage 4a — Atom detection, **two competing engines exist side by side**

**v1 — hardcoded (`specialty_configs/v1/rddt_specialty_sql.py`, notebook cell 51):**
Python dictionaries of ICD/CPT/keyword rules, compiled directly to SQL. Produces `ATTR_ATOMS`
(one row per patient, one 0/1 column per atom), `ATTR_SPECIALTY_FEATURES` (which named features
fired), and — critically — **`ATTR_SPECIALTY_TIERS`**: one row per patient with three columns,
`ortho_tier`, `cardio_tier`, `neuro_tier`, each `1`, `2`, or `NULL`.

**v2 — config-driven (`specialty_configs/v2/`, notebook cell 54):** the `loader.py` +
`sql_generator.py` system we looked at earlier. Reads `atoms/*.json`, `buckets/*.json`,
`features/*.json`. Produces `ATTR_V2_ATOMS` and `ATTR_V2_SPECIALTY_FEATURES`.

**The important fact for you right now: v2 stops there.** It never built the equivalent of
`ATTR_SPECIALTY_TIERS` or a shortlist table. Go back and look at `sql_generator.py`'s
`run_specialty_step4_v2()` — the last thing it does is `_create_feature_hits()`. There is no
`_create_specialty_tiers()`, no shortlist step, nothing that rolls per-feature hits up into one
tier-per-specialty-per-patient summary. **v2 was left half-finished even in the old ATTR-only
system**, before we ever started the four-phenotype work. This is the honest starting point.

### Stage 4b — The final decision (v1 only, cells 57 and the `rddt_specialty_config.py` shortlist rule)

```sql
SELECT COUNT(*) FROM ATTR_SPECIALTY_TIERS
WHERE (IFF(ortho_tier=1,1,0) + IFF(cardio_tier=1,1,0) + IFF(neuro_tier=1,1,0)) >= 2
```

That single SQL expression, run against `ATTR_SPECIALTY_TIERS`, **is the entire priority/decision
logic of the currently-running system.** `ATTR_SHORTLIST_LLM` is just the patients who pass it.
There is no ATTR_COMMON, no ATTRwt-vs-ATTRv split, no AL safety route, no AA — v1 only ever
answered one binary question for one disease.

## Part 3 — Direct answers to your specific questions

### "How does it identify and fire logics, signals?"

An atom fires when its code list or keyword list matches a row in one specific `ATTR_EVID_*`
table — literally `IFF(<condition>, 1, 0)` per atom per patient, exactly like `ATTR_CODES` and
`LAB_TERMS` do today. Nothing more mysterious than that. A sign fires when **any** of its member
atoms fires (`WT12`'s `av_block OR bundle_branch_block OR pacemaker...`). A composite fires when a
**count** of sibling atoms crosses a threshold (`WT04`'s "≥2 of six ortho findings").

### "How does a patient get put in GENERAL_AMYLOID, then ATTR_COMMON, then ATTRwt/ATTRv/AA/AL?"

**This code doesn't exist yet.** `ATTR_SPECIALTY_TIERS` is the closest analog, and it only ever
computed three columns for one disease. To build the six-phenotype router, you need six new
per-patient summary tables (or one wide table with many columns) that don't exist in either engine
today — this is genuinely new SQL, not a config change. `06_execution_pipeline.md` sketched the
target shape (`ATTR_V3_BUCKET_TIER`, `ATTR_V3_PHENOTYPE_HITS`) — as of right now, **zero lines of
SQL implement it.**

### "How does priority come out?"

In the current system: it doesn't — there's only one pass/fail. In the target design: priority is
decided by which `Combination Rule` fires (`WT_RULE_01` = Priority A vs `WT_RULE_02` = Priority B),
computed by comparing `MIN(date)` values the same way `ATTR_EVID_CLAIM.FromDate` is already
available today — again, that comparison SQL hasn't been written.

### "How is timing handled?"

`ATTR_EVID_CLAIM` already carries `FROM_DATE`/`TO_DATE`; `ATTR_EVID_MEDICAL_HISTORY` /
`SURGICAL_HISTORY` carry `EVENT_DATE`; `ATTR_EVID_LAB_RESULT` carries `OBSERVATION_DATETIME`. The
raw dates are sitting there today, already pulled into evidence tables. What's missing is the step
that keeps the **earliest** matching date per atom instead of just a 0/1 flag — v1's
`_create_code_atoms()`-equivalent only ever does `MAX(IFF(...))`; nobody yet does the parallel
`MIN(IFF(...))`. Small, real, unwritten.

## Part 4 — The concrete reason "simple JSON doesn't work by itself," verified just now

I checked this directly rather than assuming. Every atom object carries a field:

```json
"extraction_executability": "NON_EXECUTABLE_MISSING_VOCABULARY"
```

**Every atom we added real keywords/codes to over the last several fix passes (ATTRwt, ATTRv, AL,
AA — roughly 150 atoms) still carries this exact flag, unchanged.** The handful of atoms that
worked from day one (`af`, `hf_any`, `conduction_disease`, `ctr_any`, `cts_any`) simply don't have
this field at all. That's the tell: its presence is a deliberate block, and nothing in any of our
fix passes ever removed it. If whatever code eventually reads `atoms/*.json` (there is no such
code yet — `loader.py` in `v2/` reads the *old* flat atom format, not this one) respects that flag
the way its name implies, **none of the content we built would be treated as ready.**

This is exactly the shape of your instinct: the JSON is syntactically valid (we've verified that
after every single edit), but a *status field inside it* contradicts the *content* inside it. A
schema being valid JSON and a schema being semantically self-consistent are different checks, and
we've only ever been doing the first one.

## Part 5 — What's actually built vs. not, no hedging

| Piece | Exists as real code today? |
|---|---|
| Stage 1 QC | ✅ Yes — `rddt_attr_sql.py`, unchanged, works |
| Stage 2 wide net | ✅ Yes — works, but its pattern lists are the *old* ATTR-only ones, not yet regenerated from the 88-atom four-phenotype catalog |
| Stage 3 evidence tables | ✅ Yes — works, dates already present |
| Stage 4a atom detection | ⚠️ **v1 exists and works** (old, hardcoded, ATTR-only). **v2 exists but only gets to raw feature hits**, and reads a *different* JSON shape than our `atoms/*.json` |
| Our new `atoms/*.json` (four-phenotype, 211 atoms) | ⚠️ Content is real and correct now, but **no loader/SQL-generator reads this exact file shape**, and every atom is still self-flagged non-executable |
| Bucket-tier rollup (Stage 4b) | ❌ Does not exist for the four-phenotype model. `ATTR_SPECIALTY_TIERS` is the nearest analog and only covers the old 3-specialty ATTR case |
| Phenotype overlays, combination rules, temporal rules, guardrails | ❌ Documented in `.md` files only. Zero JSON, zero SQL |
| Router / final output | ❌ Does not exist. `ATTR_SHORTLIST_LLM` is the nearest analog (one disease, one boolean) |

## Part 6 — How you'd actually test one patient through this, end to end, today

Given what's real right now, here's the only thing you could actually verify in Snowflake this
week, and how:

1. Pick a patient you already know has, say, bilateral CTS + HFpEF, from `ATTR_KNOWN_ATTR` or
   direct chart review.
2. `SELECT * FROM ATTR_WIDE_NET_CANDIDATES WHERE PATIENT_ID = '...'` — confirm they're in the net.
3. `SELECT * FROM ATTR_EVID_CLAIM WHERE PATIENT_ID = '...'` — confirm the CTS/HFpEF codes are
   actually present in the evidence slice, with dates.
4. `SELECT * FROM ATTR_SPECIALTY_TIERS WHERE PATIENT_ID = '...'` — confirm `ortho_tier` and
   `cardio_tier` came out `1` or `2` as expected. This is the v1 engine, today, real.
5. To test anything from our new four-phenotype `atoms/*.json` work, you currently **cannot** —
   there is no code that consumes that file. The only way to "test" it right now is manually:
   read a chart, read the atom's keyword/code list, and judge by eye whether it would match. That
   is a real limitation, not a documentation gap.

## What this means for what we build next

The honest next deliverable, if you want anything in this conversation to actually run against
Snowflake, is **not** more `.md` specs — it's a new Python module, structurally parallel to
`v1/rddt_specialty_sql.py` and `v2/sql_generator.py`, that:

1. Reads our actual `atoms/*.json` shape (`extraction.keywords`, `extraction.codes.*`,
   `source_workbook_rows`) — v2's `loader.py` cannot read this file as-is, it expects a different
   structure (flat `keywords.canonical`/`keywords.fuzzy_variants`, not the nested one we've been
   editing).
2. Ignores or explicitly clears `extraction_executability` for every atom that now has content —
   or better, makes that flag computed automatically (present with real keywords/codes ⇒
   executable) rather than a stale manual field.
3. Adds the `MIN(date)` companion to every existing `MAX(flag)` aggregation.
4. Builds one new SQL step per phenotype for the bucket-tier rollup, then one per phenotype for
   the combination rules — six small, mechanical passes, not one big one.

Nothing about the *design* in the earlier `.md` files was wrong. What was missing was ever
connecting it to code that runs. Want me to start on that module now, beginning with fixing the
loader/schema mismatch and the `extraction_executability` issue, since those block everything else?

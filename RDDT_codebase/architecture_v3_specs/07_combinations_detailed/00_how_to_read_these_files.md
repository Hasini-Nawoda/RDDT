# How to read the six rule-detail files

Each of the next six files covers **all the combination rules for one phenotype**, in full detail.
There are **28 rules total** across the six files:

| File | Phenotype | Rule count |
|---|---|---|
| `01_general_amyloid.md` | GENERAL_AMYLOID | 2 |
| `02_attr_common.md` | ATTR_COMMON | 8 |
| `03_attrwt.md` | ATTRwt | 2 |
| `04_attrv.md` | ATTRv | 7 |
| `05_al.md` | AL | 7 |
| `06_aa.md` | AA | 2 |
| | **Total** | **28** |

## What "contributing sign IDs" means in these files

For every bucket in every rule, I list the **exact sign IDs from your original four CSVs** that can
satisfy that bucket at Tier 1–2 **and** are gate-eligible for that specific phenotype — re-derived
directly from the bucket-config workbook, not from memory. Format: `SIGN_ID:T#` — e.g. `WT02:T1`
means sign `WT02` (bilateral/recurrent CTS) sits at Tier 1 for this phenotype's overlay.

**A bucket only needs the single best-tier atom among these to fire — not all of them, not
several of them added up.** If a patient has `WT02:T1` alone, their ORTHO bucket is already at
Tier 1 for ATTRwt; having `WT04` too doesn't push it to some higher level, because there is no
higher level than Tier 1.

## What each rule entry contains

- **Plain question** — what the rule is actually asking, in one sentence.
- **Requires** — the buckets, minimum tiers, and (from the table above) the actual sign IDs that
  can satisfy each side.
- **Priority** — what "A" vs "B" vs "C" means for *this specific rule*, not a generic definition.
- **Temporal** — whether a date-order or persistence check applies, and exactly what it checks.
- **Output route** — where a patient who fires this rule gets sent.
- **Worked example** — one concrete, invented patient, walked through step by step.
- **Edge cases / tiny details** — things that are easy to get wrong, including a couple of
  genuine gaps found while re-deriving this from the workbook (flagged where they occur).

## One thing to hold in your head across all 28 rules

None of these rules ever look at a raw sign directly. They only ever look at **bucket-tier
facts** — the output of Stage 4 in `06_execution_pipeline.md`. A rule doesn't know or care whether
`WT02` or `WT04` produced "ORTHO: Tier 1" — it only asks "is ORTHO at Tier 1 or 2?" The sign IDs
listed in each rule are there so you can trace *why* a bucket reached that tier, not because the
rule references them directly.

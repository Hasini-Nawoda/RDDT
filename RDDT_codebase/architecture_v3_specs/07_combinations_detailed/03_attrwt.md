# ATTRwt — 2 rules

Question: **"Is this specifically wild-type transthyretin amyloidosis?"** Only reached after
`ATTR_COMMON` passes (in practice: since `WT_RULE_01`/`02` require the same ORTHO+CARDIO evidence
as `AC01`, any patient who passes an ATTRwt rule has already passed `AC01`).

**Contributing sign IDs** (Tier 1–2, gate-eligible, ATTRwt overlay):

| Bucket | Sign IDs |
|---|---|
| ORTHO | `WT03:T1, WT02:T1, WT04:T1, WT05:T2` |
| CARDIO | `WT13:T1, WT10:T1, WT16:T2, WT14:T2, WT15:T2, WT09:T2, WT12:T2, WT11:T2` |

Notice: **only 4 ORTHO sign IDs and 8 CARDIO sign IDs, all `WT*`.** `V13` (ATTRv's version of
bilateral CTS) does **not** appear in ATTRwt's ORTHO list, even though it shares the same
canonical atom (`ORTHO_CTS_BILAT_RECURRENT`) as `WT02` — because `V13` is Tier 2 under the
*ATTRv* overlay specifically, and it isn't separately listed as gate-eligible under the *ATTRwt*
overlay in the workbook. In practice this rarely matters (a patient with bilateral CTS coded once
will have `WT02` fire regardless of which phenotype is asking), but it matters conceptually: the
same clinical fact is being asked two different questions by two different phenotypes, and each
phenotype only sees the sign IDs it was actually given tier/gate status for.

## WT_RULE_01 — ORTHO + CARDIO, with confirmed date order

**Plain question:** Does the patient have both ORTHO and CARDIO evidence at Tier 1–2, **and can we
prove from the dates that the orthopedic finding happened first?**

**Requires:** `ORTHO` Tier 1–2 + `CARDIO` Tier 1–2

**Temporal:** `T01` (`05_temporal_rules.md`) — `ORTHO.first_seen_date < CARDIO.first_seen_date`.
No minimum gap is enforced (not "must be ≥5 years apart") — any confirmed ordering counts, though
the years-between value is still stored for explanation/ranking.

**Priority:** A — the strongest possible ATTRwt signal in the entire system. This is `WT01` from
the original CSV, reframed as a rule (see `05_temporal_rules.md` for how `WT01` flows through).

**Output route:** `ATTRWT_REVIEW`

**Worked example:** Patient has `WT02` (bilateral CTS, first coded 2015) and `WT10` (unexplained LV
wall thickening, first coded 2023). ORTHO Tier 1 (from `WT02`), CARDIO Tier 1 (from `WT10`), and
2015 < 2023 is confirmed → `WT_RULE_01` fires → `ATTRwt: PRIORITY A`.

## WT_RULE_02 — ORTHO + CARDIO, date order unconfirmed

**Plain question:** Same two buckets, same tiers — but the dates are missing, ambiguous, or can't
be reliably compared (e.g. the ortho finding is documented only as "history of," with no discrete
date; or both findings first appear in the same visit/import batch).

**Requires:** Identical to `WT_RULE_01` — `ORTHO` Tier 1–2 + `CARDIO` Tier 1–2.

**Temporal:** None required (this rule is specifically *for* the case where `T01` can't be
evaluated).

**Priority:** B — same evidence, lower confidence, purely because timing couldn't be verified.

**Output route:** `ATTRWT_REVIEW` (same route as Rule 01 — the priority letter is what tells a
reviewer this one is less certain, not a different destination).

**Worked example:** Patient has `WT04` (multi-ortho cluster, no reliable onset date in the record)
and `WT13` (late-onset HCM phenotype, dated 2024). ORTHO Tier 1, CARDIO Tier 1, but no usable
ORTHO date to compare → `WT_RULE_01` cannot evaluate its temporal condition, so it doesn't fire;
`WT_RULE_02` fires instead → `ATTRwt: PRIORITY B`.

## Why there is no "ORTHO + NEURO" or "CARDIO + NEURO" rule here

This is the biggest deliberate restriction in the whole rule set, and it's worth stating plainly
since it's the opposite of how the old v2 pipeline worked (`shortlist_config.json`'s "any 2 of
ortho/cardio/neuro"). **ATTRwt recognizes exactly one shape of evidence: ORTHO + CARDIO.** A
patient with ORTHO + NEURO, or CARDIO + NEURO, does not pass either `WT_RULE_01` or `WT_RULE_02` —
no matter how strong those findings are. They may well pass `ATTR_COMMON` (via `AC04` or `AC07`)
and get routed to `ATTR_UNSPECIFIED_REVIEW`, but they are never labeled `ATTRwt` on neuro evidence
alone, because neuropathy is the hallmark that should raise ATTRv suspicion instead
(`04_attrv.md`), not dilute the ATTRwt-specific pattern.

## Edge cases / tiny details

- Both rules require the *same* tier thresholds — the only difference between them is the
  temporal check. If you ever see a patient satisfy `WT_RULE_02` but not `WT_RULE_01`, the fix is
  always "get better dates," never "lower the tier requirement."
- A patient can never fire both rules "at once" in a way that stacks — if the temporal condition
  holds, only `WT_RULE_01` (Priority A) is reported; `WT_RULE_02` is the fallback used only when
  `WT_RULE_01`'s condition can't be evaluated, not a second independent pass.
- Because ORTHO and CARDIO Tier 1–2 atoms are shared with `ATTR_COMMON`'s `AC01`, every ATTRwt
  pass is automatically also an `ATTR_COMMON` pass — there's no scenario where a patient is
  `ATTRwt: PRIORITY A` but `ATTR_COMMON: FAIL`.

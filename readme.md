# RDDT

ATTR (transthyretin amyloidosis) work on Snowflake: ingest client data, check daily volume, confirm known ATTR patients, and run early-detection specialty screening.

Most workstreams live on their own feature branch. Check out the branch you need, or merge into `main` when ready.

| Folder | Branch | Purpose |
|--------|--------|---------|
| [`Ingest/`](Ingest/) | `feat/ai/ingest` | Incremental load from source DB → AI/ML staging |
| [`Daily Volume Check/`](Daily%20Volume%20Check/) | `feat/ai/volume-check` | “Did new data land today?” snapshots and diffs |
| [`Confirmed Findings/`](Confirmed%20Findings/) | `feat/ai/confirm_patient_identification_01` | Find patients with confirmed ATTR wording/codes |
| [`Early Detection/`](Early%20Detection/) | `feat/ai/early-detection` | Specialty Tier 1–2 screening (ortho / cardio / neuro) |

---

## How the pieces fit

```
Source DB (Database1)
        │
        ▼
   Ingest/                CHANGE_LOG → staging MERGEs
        │
        ▼
Daily Volume Check/       row counts + patient diffs vs yesterday
        │
        ├──────────────────► Confirmed Findings/   (known ATTR labels)
        │
        └──────────────────► Early Detection/      (undiagnosed / shortlist)
```

Use **Confirmed Findings** when you want patients who already look ATTR-positive in notes/codes.  
Use **Early Detection** when you want specialty red-flag patterns (CTS, HF, neuropathy, …) for earlier review.

---

## 1. Ingest (`Ingest/`)

Incremental ingestion driven by `CHANGE_LOG` (event log), not a time-only watermark.

| File | Role |
|------|------|
| `ingest_final.py` | Slice CHANGE_LOG (1M events), MERGE into staging, advance bookmark |
| `setup_tables.sql` | Staging / watermark / lock / quarantine tables |
| `diagram.png` | Flow overview |

**Notes**

- Bookmark is `(logged_at, log_id)` of the last processed event.
- Concurrent runs are blocked via an ingest lock.
- Join misses can quarantine after repeated failures; see script comments.

Configure `SOURCE_DB`, `STAGING_DB`, and `TABLE_CONFIG` at the top of `ingest_final.py` before running.

---

## 2. Daily Volume Check (`Daily Volume Check/`)

Snowflake notebook to confirm the data engineer loaded new data.

| File | Role |
|------|------|
| `daily_volume_check.ipynb` | Config + table sizes + per-patient activity + snapshot diff |
| `daily_volume_check.sql` | Supporting SQL |
| `setup_volume_snapshots.sql` | One-time snapshot table setup |

**Each run**

1. Table sizes (census, claim, lab, histories, notes, …)
2. Per-patient visit / lab / history / claim activity
3. Save today’s snapshot
4. Diff vs previous snapshot (new patients, growth)

Edit only the `CONFIG` cell (source DB/schema, ID column names).

---

## 3. Confirmed Findings (`Confirmed Findings/`)

Identify patients with **confirmed ATTR** evidence (not the broad specialty shortlist).

| File | Role |
|------|------|
| `ATTR_Confirmed_Patients_Configurable.ipynb` | Preferred: config-driven columns, Step A explore → Step B confirm |
| `ATTR_Confirmed_Patients_Snowflake.ipynb` | Earlier hardcoded-column version |

**Configurable notebook flow**

1. **Config** - map logical tables/columns to this client’s names  
2. **Step A (BROAD)** - per-table, per-column amyloid vocabulary discovery  
3. **A.8** - add missed ATTR keywords to `ATTR_EXTRA_TERMS`  
4. **Step B (CONFIRMED)** - stricter ATTR terms + structured ICD/SNOMED where configured  
5. **Optional** - write session temporary outputs (`ATTR_CONFIRMED_*`)

`run_per_column_scan('MEDICAL_HISTORY', mode='BROAD')` scans **each search column** and stores results in `scan_store`.  
`.head(30)` on `discover_phrases(...)` is only a display preview; full detail is available via `scan_detail('BROAD', ...)`.

---

## 4. Early Detection (`Early Detection/`)

Specialty Tier agents for **early ATTR signals** (ortho / cardio / neuro), ending in a multi-specialty shortlist.

| Path | Role |
|------|------|
| `RDDT_ATTR_Snowflake.ipynb` | Main runbook (Steps 1–4) |
| `specialty_configs/rddt_attr_sql.py` | Steps 1–3: QC, wide net, `ATTR_EVID_*` mirrors |
| `specialty_configs/v1/` | Hardcoded Step 4 engine |
| `specialty_configs/v2/` | Config-driven Step 4: `atoms/`, `buckets/`, `features/`, `loader.py`, `sql_generator.py` |

**Pipeline**

| Step | Output | Meaning |
|------|--------|---------|
| 1 | QC | Validate configured tables/columns |
| 2 | `ATTR_WIDE_NET_CANDIDATES` | Union of patients from claim codes + text nets |
| 3 | `ATTR_EVID_*` | Candidate-only mirrors of census, claim, lab, histories, notes |
| 4 v1 / v2 | Feature hits + shortlist | Tier 1–2 rules; shortlist = ≥2 specialties |

**Client wiring:** edit `SOURCE_CONFIG` in the notebook (physical table/column names).  
**Clinical rules (v2):** edit JSON under `specialty_configs/v2/atoms|features|buckets` - no Python change for new keywords/codes/features that use existing operators.

Upload the whole `specialty_configs/` folder into Snowflake notebook Files (keep `v1/` and `v2/`).

All Step 3/4 objects are **session TEMPORARY** tables.

---

## Quick start (per workstream)

```text
# Volume check
git checkout feat/ai/volume-check
# Open Daily Volume Check/daily_volume_check.ipynb in Snowflake

# Confirmed ATTR patients
git checkout feat/ai/confirm_patient_identification_01
# Open Confirmed Findings/ATTR_Confirmed_Patients_Configurable.ipynb

# Ingest
git checkout feat/ai/ingest
# Configure Ingest/ingest_final.py, run setup_tables.sql, then the script

# Early detection
git checkout feat/ai/early-detection
# Upload Early Detection/specialty_configs/ + open RDDT_ATTR_Snowflake.ipynb
```

---

## Related docs

- Data dictionary / ATTR framework Excel files (when present on a branch) support column mapping and clinical signal definitions.
- Per-folder diagrams or SQL setup scripts document that workstream only; this README is the repo map.

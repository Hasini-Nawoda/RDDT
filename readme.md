# RDDT

ATTR (transthyretin amyloidosis) work on Snowflake: profile each source table, ingest client data, check daily volume, confirm known ATTR patients, and run early-detection specialty screening.

Most workstreams live on their own feature branch. Check out the branch you need, or merge into `main` when ready.

| Folder | Branch | Purpose |
|--------|--------|---------|
| [`Data Analyze/`](Data%20Analyze/) | `feat/ai/data-analyze` | Per-table read-only profiling / ERD-style exploration |
| [`Ingest/`](Ingest/) | `feat/ai/ingest` | Incremental load from source DB → AI/ML staging |
| [`Daily Volume Check/`](Daily%20Volume%20Check/) | `feat/ai/volume-check` | “Did new data land today?” snapshots and diffs |
| [`Confirmed Findings/`](Confirmed%20Findings/) | `feat/ai/confirm_patient_identification_01` | Find patients with confirmed ATTR wording/codes |
| [`Early Detection/`](Early%20Detection/) | `feat/ai/early-detection` | Specialty Tier 1–2 screening (ortho / cardio / neuro) |

---

## How the pieces fit

```
Source DB (Database1)
        │
        ├──────────────────► Data Analyze/         (one notebook per table)
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

Use **Data Analyze** first when you need to understand grain, nulls, and column names for a single table.  
Use **Confirmed Findings** when you want patients who already look ATTR-positive in notes/codes.  
Use **Early Detection** when you want specialty red-flag patterns (CTS, HF, neuropathy, …) for earlier review.

---

## 1. Data Analyze (`Data Analyze/`)

Read-only Snowflake notebooks — **one script/notebook per source table** — to explore schema, grain, and value patterns before wiring ingest or ATTR pipelines.

Branch: `feat/ai/data-analyze`

| Notebook | Table |
|----------|--------|
| `census_data_analysis.ipynb` | Census / patient demographics |
| `encounter_visit_data_analysis.ipynb` | Encounter / visit |
| `claim_data_analysis.ipynb` | Claim |
| `lab_data_analysis.ipynb` | Lab |
| `medical_history_data_analysis.ipynb` | Medical history |
| `surgical_history_data_analysis.ipynb` | Surgical history |
| `family_history_data_analysis.ipynb` | Family history |
| `clinical_note_data_analysis.ipynb` | Clinical notes |
| `social_history_data_analysis.ipynb` | Social history |
| `medication_data_analysis.ipynb` | Medication |

**How each notebook is set up**

- **Read-only:** `SELECT` / `DESCRIBE` only (no writes).
- **Config once:** database, schema, table, and physical column names in one Python cell; SQL cells use `{{T}}`, `{{C_PT}}`, etc.
- **SQL cells** so Snowflake shows Table / Chart / Pivot and the **download** button on results.

Edit only the config cell when the client renames a table or column.

---

## 2. Ingest (`Ingest/`)

Incremental ingestion driven by `CHANGE_LOG` (event log), not a time-only watermark.

| File | Role |
|------|------|
| `ingest_final.py` | Slice CHANGE_LOG (1M events), MERGE into staging, advance bookmark |
| `setup_tables.sql` | Staging / watermark / lock / quarantine tables |
| `diagram.png` | Ingest flow / ERD overview |

**Notes**

- Bookmark is `(logged_at, log_id)` of the last processed event.
- Concurrent runs are blocked via an ingest lock.
- Join misses can quarantine after repeated failures; see script comments.

Configure `SOURCE_DB`, `STAGING_DB`, and `TABLE_CONFIG` at the top of `ingest_final.py` before running.

---

## 3. Daily Volume Check (`Daily Volume Check/`)

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

## 4. Confirmed Findings (`Confirmed Findings/`)

Identify patients with **confirmed ATTR** evidence (not the broad specialty shortlist).

| File | Role |
|------|------|
| `ATTR_Confirmed_Patients_Configurable.ipynb` | Preferred: config-driven columns, Step A explore → Step B confirm |
| `ATTR_Confirmed_Patients_Snowflake.ipynb` | Earlier hardcoded-column version |

**Configurable notebook flow**

1. **Config** — map logical tables/columns to this client’s names  
2. **Step A (BROAD)** — per-table, per-column amyloid vocabulary discovery  
3. **A.8** — add missed ATTR keywords to `ATTR_EXTRA_TERMS`  
4. **Step B (CONFIRMED)** — stricter ATTR terms + structured ICD/SNOMED where configured  
5. **Optional** — write session temporary outputs (`ATTR_CONFIRMED_*`)

`run_per_column_scan('MEDICAL_HISTORY', mode='BROAD')` scans **each search column** and stores results in `scan_store`.  
`.head(30)` on `discover_phrases(...)` is only a display preview; full detail is available via `scan_detail('BROAD', ...)`.

---

## 5. Early Detection (`Early Detection/`)

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
**Clinical rules (v2):** edit JSON under `specialty_configs/v2/atoms|features|buckets` — no Python change for new keywords/codes/features that use existing operators.

Upload the whole `specialty_configs/` folder into Snowflake notebook Files (keep `v1/` and `v2/`).

All Step 3/4 objects are **session TEMPORARY** tables.

---

## Other / legacy folders

| Path | Notes |
|------|--------|
| `initial_qudrum/` | Early Architecture 2 prototype |
| `RDDT_Final_v1/` | Earlier packaged Step 4 snapshot |

Prefer **`Early Detection/`** for current screening work.

---

## Conventions

- **Snowflake notebooks** use `get_active_session()` — run inside Snowflake (or an environment with an active Snowpark session).
- **Do not commit** `.env`, `__pycache__/`, virtualenvs, or Excel lock files (`~$*`). See `.gitignore` when present on the branch.
- Spreadsheets such as data dictionaries / detection frameworks may live beside a workstream for reference; keep secrets out of the repo.

---

## Quick start (per workstream)

```text
# Per-table data analyze / ERD-style explore
git checkout feat/ai/data-analyze
# Open Data Analyze/<table>_data_analysis.ipynb (e.g. census_data_analysis.ipynb)

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

## Related docs on disk

- Data dictionary / ATTR framework Excel files (when present on a branch) support column mapping and clinical signal definitions.
- `Ingest/diagram.png` documents the ingest flow.
- Per-folder SQL setup scripts document that workstream only; this README is the repo map.

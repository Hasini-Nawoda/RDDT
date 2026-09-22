# Terminology audit artifacts

Run the audit from the repository root:

```powershell
python v5/tools/audit_terminology_coverage.py
```

The script reads the user-supplied vocabulary files in `v5/sql/codes` and the
V5 configuration. It never reads `.env`, calls an external API, or changes an
atom/config file.

Generated files:

- `configured_mapping_audit.csv`: one row per configured ICD/SNOMED mapping;
- `atom_mapping_summary.csv`: mapping-quality triage by existing atom;
- `ambiguous_code_reuse.csv`: codes assigned to more than one atom;
- `prefix_fallback_audit.csv`: warehouse effect of configured prefixes;
- `configured_parent_descendant_gaps.csv`: exact parent codes that do not
  match observed billable descendants;
- `active_atom_icd_coverage.csv`: ICD coverage for phenotype-referenced atoms;
- `supplied_lists_unconfigured.csv`: supplied candidate-list codes not mapped
  to an existing atom;
- `discovered_outside_supplied_lists.csv`: text/category candidates found in
  the warehouse vocabulary but not in the supplied candidate lists;
- `official_codes_not_in_warehouse_candidates.csv`: possible official codes
  not observed in the current warehouse export; and
- `summary.json`: reproducible counts.

Candidate and lexical-similarity outputs are review queues, not clinical
validation. They must not be loaded into the pipeline automatically. The audit
creates no new atoms.


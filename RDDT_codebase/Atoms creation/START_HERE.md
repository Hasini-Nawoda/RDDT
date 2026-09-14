# How to fill the amyloidosis terminology file

Fill **terminology_contribution.json**. It contains one entry per current clinical observation. The accompanying **atom_index.csv** translates each `atom_id` into its clinical name and Excel sign IDs. The `atoms/` folder is the cleaned reference configuration.

Do not edit only the generated reference atoms: regeneration can overwrite those changes. Returned contributions are merged into `Early Detection/specialty_configs/v3/terminology_review.json`, the durable input.

`[]` means an empty list: no entries have been supplied. Leave it empty when no appropriate code or term exists. Do not enter `N/A`, `unknown`, an empty string, or a guessed code. A sign need not have a code in every system.

## The fields you fill

| JSON field | Meaning | What to put there |
|---|---|---|
| `extraction.codes.icd10` | ICD-10 diagnosis codes | Relevant diagnosis codes; verify the local variant, such as ICD-10-CM. |
| `extraction.codes.icd9` | Older ICD-9 diagnosis codes | Relevant historical diagnosis codes, if used in the data. |
| `extraction.codes.snomed` | SNOMED CT clinical concepts | Relevant concept identifiers. |
| `extraction.codes.cpt` | CPT procedure/service codes | Procedures or services relevant to finding the observation. A procedure code does not automatically prove an abnormal result. |
| `extraction.codes.hcpcs` | HCPCS service/supply codes | Relevant codes if the source system uses them. |
| `extraction.codes.loinc` | LOINC test/observation identifiers | Identifiers for the relevant laboratory test or measurement. A test identifier alone does not establish an elevated/abnormal result. |
| `extraction.codes.rxnorm` | RxNorm medication concepts | Relevant medication identifiers where medication exposure is part of the observation. Medication alone may be only supporting evidence. |
| `extraction.keywords` | Terms to find in narrative text or text-valued columns | Clinical phrases, synonyms and abbreviations used to describe this observation. Each is an object as shown below. |
| `extraction.structured_rules` | Numeric conditions on structured data | Leave empty unless the actual source field, unit and reviewed comparison rule are known. This is usually completed with the data engineer. |

## Each code entry

Use an object, not just a code string. This example is a format illustration; replace the placeholder text before returning it:

```json
{
  "code": "REPLACE_WITH_VERIFIED_CODE",
  "description": "Official description of the code",
  "mapping_role": "PROXY_SUPPORT",
  "can_fire_atom_alone": false,
  "requires_corroboration": [],
  "review_status": "NEEDS_CLINICAL_REVIEW"
}
```

| Field | Meaning |
|---|---|
| `code` | The exact identifier, stored as text so formatting/leading zeros are preserved. |
| `description` | The human-readable code meaning. |
| `mapping_role` | `DIRECT_TARGET`: directly represents this observation. `PROXY_SUPPORT`: only a clue needing corroboration. `DIFFERENTIAL_EXCLUDE`: evidence relevant to an alternative explanation; it is not a blanket patient exclusion. `DO_NOT_USE`: retained but unsuitable for detection. |
| `can_fire_atom_alone` | Whether this code alone is sufficient to establish the atom. Start with `false`; promote only after review. This never bypasses later clinical qualifications. |
| `requires_corroboration` | A list of **existing atom IDs** that must also be supported. Leave `[]` if no such explicit requirement has been defined. Do not put prose or new invented IDs here. |
| `review_status` | Code-level status: `UNREVIEWED`, `NEEDS_CLINICAL_REVIEW`, or `REVIEWED`. This is an operational terminology control, not commentary about the assistant. |

## Each text-search entry

**The NLP search field is `extraction.keywords`.** Add one entry for each alternative clinical name, synonym, abbreviation or spelling variant. These entries are alternatives (OR): any matching term can identify a candidate for the same atom; all terms do not need to appear together. Negation, uncertainty, subject, timing and clinical qualifications still need to be checked before accepting the finding.

V2 separated search terms into `keywords.canonical` and `keywords.fuzzy_variants`. V3 represents both kinds in this single list. A listed spelling variant is an explicit search term, not a promise of automatic fuzzy matching. For example, `polyneuropathy` and `peripheral neuropathy` can be separate `PHRASE` entries for the same atom. Put proposals in `terminology_contribution.json` and keep its status `PENDING` until reviewed.

```json
{
  "value": "REPLACE_WITH_CLINICAL_PHRASE",
  "mode": "PHRASE",
  "polarity_required": "AFFIRMED"
}
```

| Field | Meaning |
|---|---|
| `value` | The term or phrase to search for. Add separate entries for synonyms. |
| `mode` | `PHRASE`: phrase match. `BOUNDARY`: match a term with word boundaries. `REGEX`: a regular-expression pattern; use only with engineering review. |
| `polarity_required` | `AFFIRMED`: present/positively documented. `NEGATED`: explicitly denied. `UNKNOWN`: unknown polarity. Use `AFFIRMED` for positive clinical signs. Mention detection still needs negation, uncertainty, patient/family and timing handling. |

The schema does not currently have dedicated lists called `synonyms`, `abbreviations` or `negative_terms`. Synonyms/abbreviations go in `keywords`; do not add unsupported JSON keys. Record source references or questions in a separate review document.

## Each structured numeric rule

| Field | Meaning |
|---|---|
| `rule_id` | A unique stable name for the extraction rule. |
| `field` | The actual data field/column to inspect, agreed with the data engineer. |
| `op` | `gte`: greater than or equal; `lte`: less than or equal; `eq`: equal; `between`: inclusive numeric range. |
| `value` | Numeric threshold, or lower bound for `between`. |
| `max_value` | Upper bound; required only when `op` is `between`. |
| `unit` | The measurement unit expected after appropriate normalization. |

Do not invent clinical thresholds. The existing schema supports these numeric comparisons; it does not by itself define serial trends, joins, terminology-system variants or a complete NLP extractor.

## Contribution status

Each atom entry has `review_status: "PENDING"`. Leave this unchanged while collecting codes and terms. Pending submissions are retained for review and do not automatically activate extraction. `APPROVED` is a later terminology approval step requiring `reviewer` (person/team name) and `reviewed_on` (`YYYY-MM-DD`). Atom-level `PENDING/APPROVED` is different from each code's review status.

## Reference fields you normally leave unchanged

| Field | Meaning |
|---|---|
| `atom_id` | Stable machine identifier used by the rest of the configuration. Use `atom_index.csv` to find its clinical meaning; do not rename it. |
| `preferred_name` | Human-readable clinical observation name. |
| `source_specialty` | Where the information is usually documented. It is separate from the disease reasoning bucket. |
| `source_workbook_rows` | Excel sign IDs supported by this observation. An empty list can mean a shared helper or historical observation, not a place to enter codes. |
| `stage` | Whether the observation belongs to pre-test evidence, later diagnostic work-up, confirmation or another configured stage. |
| `experiencer_contract` | Whether the observation describes the patient, a family member, or either with explicit context. |
| `family_tables_only` | Restricts family-history extraction to appropriate family-history sources when true. |
| `extraction_executability` | Whether reviewed extraction content is currently available. Do not manually switch it to executable. |
| `candidate_keywords` | Existing unapproved phrase suggestions. These are not active sufficient matches. Put your proposed terms in the contribution file's `keywords`, leaving the contribution pending. |
| `candidate_structured_rules` | Existing unapproved numeric-rule suggestions. They are not active sufficient rules. |
| `schema_version` | Configuration format version; leave unchanged. |

Clinical qualifications such as `persistent`, `distal_site`, `otherwise_unexplained` or `prior_known` are **not additional diagnosis codes**. They describe facts the later extractor must establish from the patient record. `clinical_qualifications.csv` lists these requirements by atom, with the expected value and the rule that requires it. Its readable labels expand the technical names; the linked workbook row and rule remain the authoritative context. Do not enter patient-specific true/false values into this terminology file, and do not assume a keyword match proves every qualifier.

Review prose (`semantic_review` and atom `notes`) has been moved out of the reference atom JSONs. Clinical qualifiers, provenance and extraction controls remain because they affect correct interpretation.

This handoff contains current extraction targets; the ongoing clinical row review is paused at 128/133. It is not a claim that all 133 rows have completed the final review or that the patient extraction pipeline is deployed.

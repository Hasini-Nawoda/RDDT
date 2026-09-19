import fs from "node:fs/promises";
import {
  FileBlob,
  SpreadsheetFile,
} from "file:///C:/Users/PAMALI/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const workbookPath = "C:/Users/PAMALI/Desktop/RDDT/v4_build_tools/source/ATTRv_Normalized_Clinical_Filtering_Config_v3.xlsx";
const auditDir = "C:/Users/PAMALI/Desktop/RDDT/v4_build_tools/workbook_audit_artifacts/final_clinical_audit";

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
await fs.mkdir(auditDir, { recursive: true });

async function render(name, range, suffix) {
  const image = await workbook.render({ sheetName: name, range, autoCrop: "all", scale: 1.25, format: "png" });
  await fs.writeFile(`${auditDir}/${name}_${suffix}.png`, new Uint8Array(await image.arrayBuffer()));
}

await render("Signals", "A1:Y42", "before");
await render("Signal_Atoms", "A1:L105", "before");
await render("Signal_Rule_Groups", "A1:J85", "before");
await render("Signal_Rule_Members", "A1:I190", "before");
await render("Atoms", "A1:K105", "before");
await render("Terminology", "A225:G325", "before");
await render("Terminology", "A695:G725", "before_orphan");
await render("Terminology", "A955:G985", "before_pacemaker");
await render("Algorithm_Contract", "A1:D15", "before_unified_verdict");
const initialSheetNames = new Set(workbook.worksheets.items.map((sheet) => sheet.name));
await render(initialSheetNames.has("Composite_Rules") ? "Composite_Rules" : "Combination_Rules", "A1:G3", "before_unified_verdict");
await render(initialSheetNames.has("Composite_Groups") ? "Composite_Groups" : "Combination_Rule_Groups", "A1:G12", "before_unified_verdict");
await render(initialSheetNames.has("Composite_Members") ? "Composite_Members" : "Combination_Rule_Members", "A1:D29", "before_unified_verdict");
await render("Combinations", "A1:M16", "before_unified_verdict");

function rowsAsObjects(matrix) {
  const headers = matrix[0];
  const rows = matrix.slice(1)
    .filter((row) => row.some((value) => value !== null && value !== ""))
    .map((row) => Object.fromEntries(headers.map((header, index) => [header, row[index] ?? null])));
  return { headers, rows };
}

function objectsAsMatrix(headers, rows) {
  return [headers, ...rows.map((row) => headers.map((header) => row[header] ?? null))];
}

function rewriteSheet(name, matrix) {
  const sheet = workbook.worksheets.getItem(name);
  const used = sheet.getUsedRange();
  if (used) used.clear({ applyTo: "contents" });
  sheet.getRangeByIndexes(0, 0, matrix.length, matrix[0].length).values = matrix;
}

const v03Logic = `INDEPENDENT ALL (separate source lineage required):
  • ESTABLISHED_SIGNAL(V02)
  • AT LEAST 2 OF:
    • ANY OF:
      • ESTABLISHED_SIGNAL(V07)
      • ESTABLISHED_SIGNAL(V08)
    • ESTABLISHED_SIGNAL(V13)
    • ANY OF:
      • ESTABLISHED_SIGNAL(V05)
      • ESTABLISHED_SIGNAL(V09)
      • ESTABLISHED_SIGNAL(V10)
      • ESTABLISHED_SIGNAL(V11)
      • ESTABLISHED_SIGNAL(V26)
      • ESTABLISHED_SIGNAL(V27)
    • ANY OF:
      • ESTABLISHED_SIGNAL(V24)
      • ESTABLISHED_SIGNAL(V25)
    • ANY OF:
      • ESTABLISHED_SIGNAL(V15)
      • ESTABLISHED_SIGNAL(V16)
    • ESTABLISHED_SIGNAL(V12)
    • ESTABLISHED_SIGNAL(V17)`;

const signalsData = rowsAsObjects(workbook.worksheets.getItem("Signals").getUsedRange().values);
for (const row of signalsData.rows) {
  if (row.Signal_ID === "V03") {
    row.Atom_IDs = null;
    row.Clinical_Logic = v03Logic;
  }
}
signalsData.rows = signalsData.rows.filter((row) => !["V03", "V06"].includes(row.Signal_ID));
rewriteSheet("Signals", objectsAsMatrix(signalsData.headers, signalsData.rows));

const signalAtomsData = rowsAsObjects(workbook.worksheets.getItem("Signal_Atoms").getUsedRange().values);
signalAtomsData.rows = signalAtomsData.rows.filter((row) => !["V03", "V06"].includes(row.Signal_ID));
rewriteSheet("Signal_Atoms", objectsAsMatrix(signalAtomsData.headers, signalAtomsData.rows));

const signalRulesData = rowsAsObjects(workbook.worksheets.getItem("Signal_Rules").getUsedRange().values);
signalRulesData.rows = signalRulesData.rows.filter((row) => !["V03", "V06"].includes(row.Signal_ID));
rewriteSheet("Signal_Rules", objectsAsMatrix(signalRulesData.headers, signalRulesData.rows));

const signalGroupsData = rowsAsObjects(workbook.worksheets.getItem("Signal_Rule_Groups").getUsedRange().values);
signalGroupsData.rows = signalGroupsData.rows.filter((row) => !["V03", "V06"].includes(row.Signal_ID));
rewriteSheet("Signal_Rule_Groups", objectsAsMatrix(signalGroupsData.headers, signalGroupsData.rows));

const signalMembersData = rowsAsObjects(workbook.worksheets.getItem("Signal_Rule_Members").getUsedRange().values);
signalMembersData.rows = signalMembersData.rows.filter((row) => !["V03", "V06"].includes(row.Signal_ID));
rewriteSheet("Signal_Rule_Members", objectsAsMatrix(signalMembersData.headers, signalMembersData.rows));

const combinationIdByLegacyRule = { V03: "V_RULE_V03", V06: "V_RULE_V06" };
const groupIdMap = {
  G1_NEURO_BASE: "V_RULE_V03_NEURO_BASE",
  G2_RED_FLAGS: "V_RULE_V03_RED_FLAGS",
  V03_HEREDITARY: "V_RULE_V03_HEREDITARY",
  V03_AUTONOMIC_GI: "V_RULE_V03_AUTONOMIC_GI",
  V03_CARDIO: "V_RULE_V03_CARDIO",
  V03_ORTHO: "V_RULE_V03_ORTHO",
  V03_OCULAR: "V_RULE_V03_OCULAR",
  V03_SYSTEMIC: "V_RULE_V03_SYSTEMIC",
  V03_RENAL: "V_RULE_V03_RENAL",
  V06_NEURO_AUTONOMIC: "V_RULE_V06_NEURO_AUTONOMIC",
  V06_CARDIAC: "V_RULE_V06_CARDIAC",
};

const combinationRulesSheet = workbook.worksheets.getItem(initialSheetNames.has("Composite_Rules") ? "Composite_Rules" : "Combination_Rules");
const combinationRulesSource = rowsAsObjects(combinationRulesSheet.getUsedRange().values);
const combinationRules = combinationRulesSource.rows.map((row) => ({
  Phenotype: row.Phenotype,
  Combination_ID: row.Combination_ID || row.Emits_Combination_ID || combinationIdByLegacyRule[row.Composite_Rule_ID],
  Top_Operator: row.Top_Operator,
  Definition: row.Definition,
  Priority_Policy_ID: row.Priority_Policy_ID,
  Enabled: row.Enabled,
}));
combinationRulesSheet.name = "Combination_Rules";
rewriteSheet("Combination_Rules", objectsAsMatrix(
  ["Phenotype", "Combination_ID", "Top_Operator", "Definition", "Priority_Policy_ID", "Enabled"],
  combinationRules,
));

const combinationGroupsSheet = workbook.worksheets.getItem(initialSheetNames.has("Composite_Groups") ? "Composite_Groups" : "Combination_Rule_Groups");
const combinationGroupsSource = rowsAsObjects(combinationGroupsSheet.getUsedRange().values);
const combinationGroups = combinationGroupsSource.rows.map((row) => ({
  Combination_ID: row.Combination_ID || combinationIdByLegacyRule[row.Composite_Rule_ID],
  Group_ID: groupIdMap[row.Group_ID] || row.Group_ID,
  Evaluation_Order: row.Evaluation_Order,
  Operator: row.Operator,
  Minimum_Count: row.Minimum_Count,
  Require_Independent_Lineage: row.Require_Independent_Lineage,
  Notes: String(row.Notes || "").replaceAll("V03", "V_RULE_V03").replaceAll("V06", "V_RULE_V06"),
}));
combinationGroupsSheet.name = "Combination_Rule_Groups";
rewriteSheet("Combination_Rule_Groups", objectsAsMatrix(
  ["Combination_ID", "Group_ID", "Evaluation_Order", "Operator", "Minimum_Count", "Require_Independent_Lineage", "Notes"],
  combinationGroups,
));

const combinationMembersSheet = workbook.worksheets.getItem(initialSheetNames.has("Composite_Members") ? "Composite_Members" : "Combination_Rule_Members");
const combinationMembersSource = rowsAsObjects(combinationMembersSheet.getUsedRange().values);
const combinationMembers = combinationMembersSource.rows.map((row) => ({
  Combination_ID: row.Combination_ID || combinationIdByLegacyRule[row.Composite_Rule_ID],
  Group_ID: groupIdMap[row.Group_ID] || row.Group_ID,
  Member_Type: row.Member_Type,
  Member_ID: row.Member_Type === "GROUP" ? (groupIdMap[row.Member_ID] || row.Member_ID) : row.Member_ID,
}));
combinationMembersSheet.name = "Combination_Rule_Members";
rewriteSheet("Combination_Rule_Members", objectsAsMatrix(
  ["Combination_ID", "Group_ID", "Member_Type", "Member_ID"],
  combinationMembers,
));

const combinationRequirementsData = rowsAsObjects(workbook.worksheets.getItem("Combination_Requirements").getUsedRange().values);
const retiredRequirementIds = new Set(
  combinationRequirementsData.rows
    .filter((row) => ["V_RULE_V03", "V_RULE_V06"].includes(row.Combination_ID))
    .map((row) => row.Requirement_ID),
);
combinationRequirementsData.rows = combinationRequirementsData.rows.filter(
  (row) => !["V_RULE_V03", "V_RULE_V06"].includes(row.Combination_ID),
);
rewriteSheet("Combination_Requirements", objectsAsMatrix(combinationRequirementsData.headers, combinationRequirementsData.rows));
for (const sheetName of ["Requirement_Buckets", "Requirement_Tiers", "Requirement_Signals"]) {
  const data = rowsAsObjects(workbook.worksheets.getItem(sheetName).getUsedRange().values);
  data.rows = data.rows.filter((row) => !retiredRequirementIds.has(row.Requirement_ID));
  rewriteSheet(sheetName, objectsAsMatrix(data.headers, data.rows));
}

const combinationsData = rowsAsObjects(workbook.worksheets.getItem("Combinations").getUsedRange().values);
for (const row of combinationsData.rows) {
  if (["V_RULE_V03", "V_RULE_V06"].includes(row.Combination_ID)) {
    row.Notes = "Nested signal-group rule evaluated directly by the single combination engine; produces one patient-level verdict through normal priority resolution.";
    row.Origin = "Main Workbook Nested Combination Rule";
    row.Clinical_Rationale = String(row.Clinical_Rationale || "")
      .replace("Direct Rule V03:", "Nested combination rule V_RULE_V03:")
      .replace("Direct Rule V06:", "Nested combination rule V_RULE_V06:");
  }
}
rewriteSheet("Combinations", objectsAsMatrix(combinationsData.headers, combinationsData.rows));

const priorityData = rowsAsObjects(workbook.worksheets.getItem("Priority_Policies").getUsedRange().values);
for (const row of priorityData.rows) {
  if (["FIXED_A", "FIXED_B"].includes(row.Priority_Policy_ID)) {
    row.Notes = "Named nested combination rule only.";
  }
}
rewriteSheet("Priority_Policies", objectsAsMatrix(priorityData.headers, priorityData.rows));

const contractData = rowsAsObjects(workbook.worksheets.getItem("Algorithm_Contract").getUsedRange().values);
contractData.rows = contractData.rows.filter((row) => row.Stage !== "COMPOSITE_RULES");
for (const row of contractData.rows) {
  if (row.Stage === "NAMED_COMBINATIONS") {
    row.Action = "Evaluate every configured combination in one engine, including nested signal-group rules V_RULE_V03 and V_RULE_V06.";
    row.Invariant = "Exactly one combination framework; no synthetic composite signal and no second verdict path.";
  }
  if (row.Stage === "OUTPUT") {
    row.Invariant = "Exactly one deterministic patient-level ATTRv risk verdict is emitted; other matched combinations remain removable proprietary trace.";
  }
}
contractData.rows.forEach((row, index) => { row.Step = index + 1; });
rewriteSheet("Algorithm_Contract", objectsAsMatrix(contractData.headers, contractData.rows));

const vocabularyData = rowsAsObjects(workbook.worksheets.getItem("Controlled_Vocabulary").getUsedRange().values);
vocabularyData.rows = vocabularyData.rows.filter((row) => !(
  (row.Vocabulary === "Entity_Type" && row.Allowed_Value === "COMPOSITE_RULE")
  || (row.Vocabulary === "Config_Action" && row.Allowed_Value === "CROSS_BUCKET_COMPOSITE_RULE")
));
rewriteSheet("Controlled_Vocabulary", objectsAsMatrix(vocabularyData.headers, vocabularyData.rows));

const atomsData = rowsAsObjects(workbook.worksheets.getItem("Atoms").getUsedRange().values);
atomsData.rows = atomsData.rows.filter((row) => row.Atom_ID !== "idiopathic_axonal_polyneuropathy");
rewriteSheet("Atoms", objectsAsMatrix(atomsData.headers, atomsData.rows));

const terminologyData = rowsAsObjects(workbook.worksheets.getItem("Terminology").getUsedRange().values);
const removeStructured = new Map([
  ["abnormal_cutaneous_silent_period", new Set([
    "NLP|electromyography", "NLP|nerve conduction study", "NLP|electromyography study",
    "NLP|neurophysiology report", "NLP|cutaneous silent period", "NLP|CSP", "NLP|CSP latency",
    "NLP|small-fiber electrophysiology",
  ])],
  ["anhidrosis", new Set([
    "NLP|other disorders of sweat glands", "NLP|abnormal sweating", "NLP|disorder of sweating",
    "NLP|sudomotor function test", "NLP|quantitative sudomotor axon reflex test",
  ])],
  ["arrhythmia", new Set(["NLP|arrhythmia", "NLP|cardiac arrhythmia"])],
  ["conduction_disease", new Set([
    "CPT_HCPCS|33206-33208", "CPT_HCPCS|93000", "ICD10|I48.0-I48.91", "ICD10|Z95.0",
    "ICD9|427.31", "ICD9|427.32", "ICD9|V45.01", "SNOMED_CT|233917008", "SNOMED_CT|49436004",
  ])],
  ["pacemaker_presence", new Set([
    "CPT_HCPCS|93000", "ICD10|I44.1-I44.3", "ICD10|I45.4", "ICD10|I48.0-I48.91",
    "ICD9|426.0-426.13", "ICD9|427.31", "ICD9|427.32", "SNOMED_CT|49436004",
  ])],
  ["cts_bilateral", new Set([
    "CPT_HCPCS|64721", "ICD10|G56.01", "ICD10|G56.02", "ICD10|G56.13", "ICD9|354.0",
    "SNOMED_CT|1303624004", "SNOMED_CT|293861000119102", "SNOMED_CT|293871000119108",
    "SNOMED_CT|397828008", "SNOMED_CT|57406009",
  ])],
  ["cts_recurrent", new Set([
    "CPT_HCPCS|64721", "ICD10|G56.01", "ICD10|G56.02", "ICD10|G56.03", "ICD9|354.0",
    "SNOMED_CT|57406009",
  ])],
  ["cts_persistent_after_release", new Set([
    "NLP|carpal tunnel release", "NLP|neuroplasty of median nerve", "NLP|revision carpal tunnel release",
  ])],
  ["elevated_nfl", new Set([
    "NLP|unlisted chemistry procedure", "NLP|neurofilament light chain",
    "NLP|neurofilament light chain serum", "NLP|neurofilament light chain plasma",
  ])],
  ["fhx_established_attr", new Set([
    "NLP|1354544003 — Hereditary transthyretin related amyloidosis / ATTRv",
    "NLP|715655000 — Transthyretin related familial amyloid cardiomyopathy",
    "NLP|715655000 — Transthyretin related familial amyloid cardiomyopathy: 1354544003 — Hereditary transthyretin related amyloidosis / ATTRv",
    "NLP|81479 (unlisted molecular pathology: 81479 (unlisted molecular pathology",
    "NLP|CPT 81404: CPT 81404",
    "NLP|TTR gene full mutation analysis in Blood or Tissue by Sequencing.",
    "NLP|Test only: rember we can filter out patient but current dictiobary not mention it come Loinc code",
    "NLP|commonly used for TTR sequencing): commonly used for TTR sequencing)",
  ])],
  ["iris_abnormality", new Set([
    "NLP|iris abnormality", "NLP|pupillary abnormality", "NLP|irregular pupil",
    "NLP|irregular pupil margin", "NLP|anisocoria", "NLP|sluggish pupil", "NLP|poorly reactive pupil",
  ])],
  ["lumbar_stenosis", new Set([
    "NLP|lumbar", "NLP|one interspace, lumbar", "NLP|ligamentum flavum hypertrophy",
  ])],
  ["medication_dose_change", new Set(["NLP|dose decreased because of hypotension"])],
  ["mibg_cardiac_denervation", new Set([
    "NLP|abnormal myocardial imaging", "NLP|myocardial imaging planar", "NLP|myocardial imaging SPECT",
    "NLP|myocardial imaging report", "NLP|nuclear medicine report", "NLP|radiopharmaceutical diagnostic imaging",
    "NLP|123I-MIBG", "NLP|MIBG", "NLP|H/M ratio", "NLP|heart-to-mediastinum ratio",
    "NLP|washout rate", "NLP|iobenguane", "NLP|metaiodobenzylguanidine",
  ])],
  ["mr_neurography_abnormal", new Set([
    "NLP|73718-73720  — no unique 'MR neurography' CPT code: MRI lower extremity", "NLP|DTI",
    "NLP|abnormal magnetic resonance imaging", "NLP|nerve enlargement",
    "NLP|magnetic resonance imaging pelvis", "NLP|magnetic resonance imaging upper extremity",
    "NLP|magnetic resonance imaging lower extremity", "NLP|MR neurography", "NLP|MR neurography report",
    "NLP|MRI report", "NLP|radiology report", "NLP|MRN",
  ])],
  ["nerve_ultrasound_enlargement", new Set([
    "NLP|abnormal ultrasound scan", "NLP|nerve enlargement", "NLP|increased nerve CSA",
    "NLP|increased nerve cross-sectional area", "NLP|brachial plexus enlargement", "NLP|enlarged brachial plexus",
    "NLP|neuromuscular ultrasound", "NLP|neuromuscular ultrasound report", "NLP|ultrasound extremity nonvascular",
    "NLP|ultrasound guidance", "NLP|ultrasound report",
  ])],
  ["reduced_ienfd", new Set([
    "NLP|abnormal skin biopsy", "NLP|intraepidermal nerve fiber density", "NLP|nerve fibre density",
    "NLP|punch biopsy of skin", "NLP|skin biopsy", "NLP|skin biopsy pathology report",
    "NLP|surgical pathology", "NLP|immunohistochemistry", "NLP|quantitative sensory testing",
  ])],
  ["sudoscan_reduced_esc", new Set([
    "NLP|95923 (autonomic function testing — commonly used for SUDOSCAN billing: 95923 (autonomic function testing — commonly used for SUDOSCAN billing",
    "NLP|not a SUDOSCAN-specific CPT code): not a SUDOSCAN-specific CPT code)", "NLP|ESC", "NLP|SUDOSCAN",
    "NLP|abnormal sudomotor function", "NLP|anhidrosis", "NLP|autonomic function test report",
    "NLP|electrochemical skin conductance", "NLP|hypohidrosis", "NLP|quantitative sudomotor axon reflex test",
    "NLP|sudomotor dysfunction", "NLP|sudomotor function", "NLP|sudomotor function test",
    "NLP|sudomotor test report", "NLP|testing of autonomic nervous system function sudomotor",
  ])],
  ["ttr_pathogenic_variant", new Set([
    "NLP|ATTRv", "NLP|ATTRv amyloidosis", "NLP|TTR-FAP", "NLP|familial amyloid polyneuropathy",
    "NLP|familial amyloidotic polyneuropathy", "NLP|hATTR", "NLP|hATTR amyloidosis",
    "NLP|hereditary ATTR", "NLP|hereditary ATTR amyloidosis", "NLP|hereditary TTR amyloidosis",
    "NLP|hereditary transthyretin amyloidosis", "NLP|variant TTR amyloidosis",
    "NLP|variant transthyretin amyloidosis", "NLP|TTR carrier", "NLP|hATTR carrier",
    "NLP|positive TTR genetic test",
  ])],
]);
terminologyData.rows = terminologyData.rows.filter((row) => {
  if (row.Atom_ID === "idiopathic_axonal_polyneuropathy") return false;
  const forbidden = removeStructured.get(row.Atom_ID);
  if (!forbidden) return true;
  return !forbidden.has(`${row.Terminology_System}|${row.Value}`);
});
rewriteSheet("Terminology", objectsAsMatrix(terminologyData.headers, terminologyData.rows));

const logData = rowsAsObjects(workbook.worksheets.getItem("Change_Log").getUsedRange().values);
for (const row of logData.rows) {
  if (row.Change_ID === "FIX-02") {
    row.Resolution = "Removed 26 atoms and their terminology rows because they were neither executable support members nor explicit blockers.";
  }
  if (row.Change_ID === "FIX-11") {
    row.Resolution = "Normalized structured terminology to executable code/prefix/range values, reclassified literal phrases to NLP, removed commentary/placeholders and duplicates, removed contradictory candidate code mappings, and removed NLP phrases that could not satisfy their atom's own context guard.";
  }
  if (row.Change_ID === "NORM-02") {
    row.Resolution = "Removed rules from Reasoning_Bucket; cross-bucket logic is represented only as named combinations, guardrails, or route rules.";
  }
  if (row.Change_ID === "FIX-03") {
    row.Resolution = "Normalized every direct or guardrail signal into Signal_Rules, Signal_Rule_Groups and Signal_Rule_Members; V03/V06 legacy composites are now named nested combination rules.";
  }
}
if (!logData.rows.some((row) => row.Change_ID === "FIX-13")) {
  logData.rows.push({
    Change_ID: "FIX-13",
    Change_Type: "STRUCTURAL",
    Area: "Single patient-level verdict",
    Resolution: "Removed V03/V06 as synthetic signals and moved their unchanged clinical group logic into V_RULE_V03/V_RULE_V06 under the combination framework.",
    Rationale: "All valid routes now compete in one priority resolver, so each patient receives exactly one deterministic ATTRv risk verdict while secondary matches remain removable audit trace.",
    Clinical_Source_IDs: null,
  });
}
rewriteSheet("Change_Log", objectsAsMatrix(logData.headers, logData.rows));

workbook.recalculate();

for (const [sheetName, range] of [
  ["Signals", "A1:Y40"],
  ["Signal_Rules", "A1:J40"],
  ["Signal_Atoms", "A1:L101"],
  ["Signal_Rule_Groups", "A1:J83"],
  ["Signal_Rule_Members", "A1:I186"],
  ["Atoms", "A1:K104"],
  ["Terminology", "A1:G1377"],
  ["Change_Log", "A1:F26"],
  ["Algorithm_Contract", "A1:D14"],
  ["Combination_Rules", "A1:F3"],
  ["Combination_Rule_Groups", "A1:G12"],
  ["Combination_Rule_Members", "A1:D29"],
  ["Combinations", "A1:M16"],
]) {
  const check = await workbook.inspect({
    kind: "table",
    range: `${sheetName}!${range}`,
    include: "values,formulas",
    tableMaxRows: sheetName === "Terminology" ? 5 : 120,
    tableMaxCols: 25,
  });
  await fs.writeFile(`${auditDir}/${sheetName}.inspect.ndjson`, check.ndjson, "utf8");
}

const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
await fs.writeFile(`${auditDir}/formula_errors.inspect.ndjson`, formulaErrors.ndjson, "utf8");

await render("Signals", "A1:Y40", "after");
await render("Signal_Atoms", "A1:L101", "after");
await render("Signal_Rule_Groups", "A1:J83", "after");
await render("Signal_Rule_Members", "A1:I186", "after");
await render("Atoms", "A1:K104", "after");
await render("Terminology", "A225:G315", "after");
await render("Terminology", "A930:G970", "after_pacemaker");
await render("Algorithm_Contract", "A1:D14", "after_unified_verdict");
await render("Combination_Rules", "A1:F3", "after_unified_verdict");
await render("Combination_Rule_Groups", "A1:G12", "after_unified_verdict");
await render("Combination_Rule_Members", "A1:D29", "after_unified_verdict");
await render("Combinations", "A1:M16", "after_unified_verdict");

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(workbookPath);

console.log(JSON.stringify({
  workbookPath,
  signals: signalsData.rows.length,
  signalAtoms: signalAtomsData.rows.length,
  signalRuleGroups: signalGroupsData.rows.length,
  signalRuleMembers: signalMembersData.rows.length,
  combinationRules: combinationRules.length,
  combinationRuleGroups: combinationGroups.length,
  combinationRuleMembers: combinationMembers.length,
  atoms: atomsData.rows.length,
  terminology: terminologyData.rows.length,
}, null, 2));

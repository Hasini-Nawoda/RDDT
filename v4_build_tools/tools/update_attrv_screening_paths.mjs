import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const sourcePath = "v4_build_tools/source/ATTRv_Normalized_Clinical_Filtering_Config_v3.xlsx";
const outputDir = "outputs/01a0b972-69e3-71f0-8de4-5346cb45e224";
const outputPath = `${outputDir}/ATTRv_Normalized_Clinical_Filtering_Config_v3.xlsx`;
const postRenderDir = "v4_build_tools/workbook_audit_artifacts/post_edit_render";

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(sourcePath));
const sheet = (name) => workbook.worksheets.getItem(name);
const valuesOf = (name) => sheet(name).getUsedRange().values;
const clone = (value) => JSON.parse(JSON.stringify(value));
const beforeTerminology = clone(valuesOf("Terminology"));
const beforeCombinations = clone(valuesOf("Combinations"));
const beforeRequirements = clone(valuesOf("Requirement_Buckets"));
const beforeRequirementSignals = clone(valuesOf("Requirement_Signals"));
const beforeBlockers = clone(valuesOf("Signal_Blockers"));

function setCell(sheetName, address, value) {
  sheet(sheetName).getRange(address).values = [[value]];
}

function rows(name) {
  return sheet(name).getUsedRange().values;
}

function findRow(name, predicate) {
  const data = rows(name);
  for (let i = 1; i < data.length; i++) {
    if (predicate(data[i])) return i + 1;
  }
  throw new Error(`Could not find row in ${name}`);
}

function signalRow(signalId) {
  return findRow("Signals", (r) => r[1] === signalId);
}

function atomRow(signalId, atomId) {
  return findRow("Signal_Atoms", (r) => r[1] === signalId && r[2] === atomId);
}

function ruleRow(signalId) {
  return findRow("Signal_Rules", (r) => r[1] === signalId);
}

function groupRow(signalId, groupId) {
  return findRow("Signal_Rule_Groups", (r) => r[1] === signalId && r[2] === groupId);
}

function memberRow(signalId, groupId, memberId) {
  return findRow("Signal_Rule_Members", (r) => r[1] === signalId && r[2] === groupId && r[5] === memberId);
}

const logic = {
  V01: "OBSERVE(ttr_pathogenic_variant) [curated NLP screening path; PATIENT, PRETEST_SIGNAL; negation/uncertainty/family context retained in terminology/context handling]",
  V02: [
    "ANY OF:",
    "  • ANY OF:",
    "    • OBSERVE(axonal_neuropathy) [screening path; no chart adjective flags required]",
    "    • OBSERVE(idiopathic_progressive_neuropathy) [screening path; no chart adjective flags required]",
    "    • OBSERVE(polyneuropathy) [required: progressive=True, length_dependent=True, axonal=True, sensorimotor=True]",
    "  • LINKED (CLINICAL_EPISODE):",
    "    • ANY OF:",
    "      • OBSERVE(axonal_neuropathy) [required: progressive=True, length_dependent=True, sensorimotor=True]",
    "      • OBSERVE(idiopathic_progressive_neuropathy) [required: progressive=True, length_dependent=True, sensorimotor=True]",
    "      • OBSERVE(polyneuropathy) [required: progressive=True, length_dependent=True, sensorimotor=True]",
    "    • OBSERVE(axonal_pattern_on_emg) [required: axonal=True]",
  ].join("\n"),
  V04: [
    "ANY OF:",
    "  • OBSERVE(sfn) [screening path; explicit SFN phrase]",
    "  • OBSERVE(sfn) [required: painful=True]",
    "  • OBSERVE(reduced_ienfd) [required: compatible_clinical_sfn=True]",
    "  • LINKED (CLINICAL_EPISODE):",
    "    • OBSERVE(burning_feet)",
    "    • OBSERVE(pain_temperature_loss)",
    "  • OBSERVE(pain_temperature_loss) [required: progressive=True, length_dependent=True]",
  ].join("\n"),
  V05: [
    "ANY OF:",
    "  • OBSERVE(dysautonomia) [screening path; explicit dysautonomia phrase]",
    "  • OBSERVE(dysautonomia) [required: objective_autonomic_evidence=True]",
    "  • LINKED (CLINICAL_EPISODE):",
    "    • AT LEAST 2 OF:",
    "      • OBSERVE(orthostatic_intolerance)",
    "      • OBSERVE(anhidrosis)",
    "      • ESTABLISHED_SIGNAL(V10)",
    "      • ESTABLISHED_SIGNAL(V11)",
  ].join("\n"),
  V07: "OBSERVE(fhx_established_attr) [curated established ATTR family-history NLP path; FAMILY_MEMBER experiencer retained]",
  V14: [
    "INDEPENDENT ALL (evidence may unfold across encounters; distinct source lineage required):",
    "  • ANY OF:",
    "    • OBSERVE(cidp)",
    "    • OBSERVE(demyelinating_emg_pattern) [required: convincing_demyelinating_pattern=True]",
    "  • OBSERVE(immunotherapy_exposure)",
    "  • OBSERVE(immunotherapy_nonresponse)",
  ].join("\n"),
  V24: [
    "ANY OF:",
    "  • OBSERVE(thick_walls) [screening path; explicit wall-thickness phrase]",
    "  • ALL OF:",
    "    • ANY OF:",
    "      • OBSERVE(hfpef) [required: unexplained=True]",
    "      • OBSERVE(cardiomyopathy) [required: unexplained=True]",
    "    • ANY OF:",
    "      • ESTABLISHED_SIGNAL(V02)",
    "      • ESTABLISHED_SIGNAL(V05)",
    "      • ESTABLISHED_SIGNAL(V07)",
    "      • ESTABLISHED_SIGNAL(V13)",
  ].join("\n"),
};

const signalChanges = {
  V01: { status: "PARTIAL", mode: "DOCUMENTED_ASSERTION" },
  V05: { status: "PARTIAL", mode: "DOCUMENTED_ASSERTION" },
  V07: { status: "PARTIAL", mode: "DOCUMENTED_ASSERTION" },
  V24: { status: "PARTIAL", mode: "DOCUMENTED_ASSERTION" },
};
for (const [sid, change] of Object.entries(signalChanges)) {
  const row = signalRow(sid);
  setCell("Signals", `P${row}`, change.status);
  setCell("Signals", `R${row}`, change.mode);
  setCell("Signals", `T${row}`, logic[sid]);
}
for (const sid of ["V02", "V04", "V05", "V14", "V24"]) {
  setCell("Signals", `T${signalRow(sid)}`, logic[sid]);
}
for (const sid of ["V01", "V07"]) {
  setCell("Signals", `T${signalRow(sid)}`, logic[sid]);
}

const connectorChanges = [
  ["V01", "ttr_pathogenic_variant", "None (default affirmed/confirmed)", true],
  ["V04", "sfn", "None (default affirmed/confirmed)", true],
  ["V05", "dysautonomia", "None (default affirmed/confirmed)", true],
  ["V07", "fhx_established_attr", "None (default affirmed/confirmed)", true],
  ["V14", "immunotherapy_exposure", "None (default affirmed/confirmed)", true],
  ["V14", "immunotherapy_nonresponse", "None (default affirmed/confirmed)", true],
  ["V24", "thick_walls", "None (default affirmed/confirmed)", true],
];
for (const [sid, aid, qualifiers, canFire] of connectorChanges) {
  const row = atomRow(sid, aid);
  setCell("Signal_Atoms", `G${row}`, qualifiers);
  setCell("Signal_Atoms", `H${row}`, logic[sid]);
  setCell("Signal_Atoms", `I${row}`, "EXECUTABLE");
  setCell("Signal_Atoms", `J${row}`, null);
  setCell("Signal_Atoms", `K${row}`, "DOCUMENTED_ASSERTION");
  setCell("Signal_Atoms", `L${row}`, canFire);
}

// Keep the mirrored atom-level logic documentation aligned with the signal rule
// for every affected atom, including non-connector atoms whose old text would
// otherwise retain the pre-change encounter/qualifier requirements.
for (const sid of ["V01", "V02", "V04", "V05", "V07", "V14", "V24"]) {
  const atomData = rows("Signal_Atoms");
  for (let i = 1; i < atomData.length; i++) {
    if (atomData[i][1] === sid) setCell("Signal_Atoms", `H${i + 1}`, logic[sid]);
  }
}

// V02: explicit axonal/idiopathic screening paths; generic polyneuropathy and linked EMG stay restricted.
for (const aid of ["axonal_neuropathy", "idiopathic_progressive_neuropathy"]) {
  const row = atomRow("V02", aid);
  setCell("Signal_Atoms", `G${row}`, "None (default affirmed/confirmed)");
  setCell("Signal_Atoms", `H${row}`, logic.V02);
}
for (const [gid, mid] of [["V02_G002", "axonal_neuropathy"], ["V02_G002", "idiopathic_progressive_neuropathy"]]) {
  setCell("Signal_Rule_Members", `G${memberRow("V02", gid, mid)}`, null);
}

// V04: explicit SFN screening path; painful/objective paths remain.
setCell("Signal_Rule_Members", `G${memberRow("V04", "V04_G001", "sfn")}`, null);

// V05: explicit dysautonomia screening path; objective alternative and the two-of-four path remain.
setCell("Signal_Rule_Members", `G${memberRow("V05", "V05_G001", "dysautonomia")}`, null);

// V01/V07: curated NLP phrases carry the specific clinical concept; retain patient/family context.
setCell("Signal_Rule_Members", `G${memberRow("V01", "V01_G001", "ttr_pathogenic_variant")}`, null);
setCell("Signal_Rule_Members", `G${memberRow("V07", "V07_G001", "fhx_established_attr")}`, null);

// V14: preserve all three facts but allow them to occur across encounters with independent lineage.
const v14Group = groupRow("V14", "V14_G001");
setCell("Signal_Rule_Groups", `F${v14Group}`, "INDEPENDENT_ALL");
setCell("Signal_Rule_Groups", `G${v14Group}`, null);
setCell("Signal_Rule_Groups", `H${v14Group}`, null);
setCell("Signal_Rule_Groups", `I${v14Group}`, true);
setCell("Signal_Rule_Groups", `J${v14Group}`, "Evidence may unfold across encounters; retain distinct source lineage for CIDP/EMG, treatment exposure, and nonresponse.");
setCell("Signal_Rule_Members", `G${memberRow("V14", "V14_G001", "immunotherapy_exposure")}`, null);
setCell("Signal_Rule_Members", `G${memberRow("V14", "V14_G001", "immunotherapy_nonresponse")}`, null);

// V24: explicit wall-thickness screening path only; HFpEF/cardiomyopathy stay guarded.
setCell("Signal_Rule_Members", `G${memberRow("V24", "V24_G001", "thick_walls")}`, null);

for (const sid of ["V01", "V05", "V07", "V24"]) {
  setCell("Signal_Rules", `H${ruleRow(sid)}`, "PARTIAL");
}
setCell("Signal_Rules", `H${ruleRow("V14")}`, "PARTIAL");

const changeLogTable = sheet("Change_Log").tables.items.find((t) => t.name === "ChangeLogTable") || sheet("Change_Log").tables.items[0];
if (!changeLogTable) throw new Error("Change_Log table not found");
if (!rows("Change_Log").some((r) => r[0] === "CLIN-07")) changeLogTable.rows.add(null, [[
  "CLIN-07",
  "CLINICAL",
  "Selective screening-path unblocking",
  "Enabled curated NLP screening paths for V01, V02, V04, V05, V07, V14 and V24; V14 now permits cross-encounter independent lineage. No structured codes or Can_Fire_Atom_Alone values changed; blockers and named combinations remain unchanged.",
  "Reduces extraction-driven UNKNOWN states for explicit curated phrases while retaining patient/family context, pre-test stage, core alternatives and combination safety gates.",
  "SRC_ATTRV_GENE_REVIEWS;SRC_ATTRV_US_PANEL;SRC_ATTRV_PN_CONSENSUS;SRC_ACC_CARDIAC;SRC_ACC_CARDIAC_2025",
]]);

workbook.recalculate();

// Preserve clinical source data and safety restrictions exactly.
if (JSON.stringify(beforeTerminology) !== JSON.stringify(valuesOf("Terminology"))) throw new Error("Terminology changed unexpectedly");
if (JSON.stringify(beforeCombinations) !== JSON.stringify(valuesOf("Combinations"))) throw new Error("Combinations changed unexpectedly");
if (JSON.stringify(beforeRequirements) !== JSON.stringify(valuesOf("Requirement_Buckets"))) throw new Error("Requirement_Buckets changed unexpectedly");
if (JSON.stringify(beforeRequirementSignals) !== JSON.stringify(valuesOf("Requirement_Signals"))) throw new Error("Requirement_Signals changed unexpectedly");
if (JSON.stringify(beforeBlockers) !== JSON.stringify(valuesOf("Signal_Blockers"))) throw new Error("Signal_Blockers changed unexpectedly");

const verification = await workbook.inspect({
  kind: "table",
  range: "Signals!A1:Y40",
  include: "values",
  tableMaxRows: 40,
  tableMaxCols: 25,
  maxChars: 20000,
});
console.log(verification.ndjson);

await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(postRenderDir, { recursive: true });
for (const sheetName of ["Signals", "Signal_Atoms", "Signal_Rules", "Signal_Rule_Groups", "Signal_Rule_Members", "Signal_Blockers", "Change_Log"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(`${postRenderDir}/${sheetName}.png`, new Uint8Array(await preview.arrayBuffer()));
}
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(sourcePath);
await output.save(outputPath);
console.log(JSON.stringify({ sourcePath, outputPath }));

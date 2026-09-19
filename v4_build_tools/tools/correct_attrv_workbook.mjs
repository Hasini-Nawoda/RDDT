import fs from "node:fs/promises";
import {
  FileBlob,
  SpreadsheetFile,
} from "file:///C:/Users/PAMALI/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const inputPath = "C:/Users/PAMALI/Desktop/RDDT/handoff/ATTRv_Normalized_Clinical_Filtering_Config_v1.xlsx";
const outputDir = "C:/Users/PAMALI/Desktop/RDDT/v4/workbook_audit_artifacts/01a0b972-69e3-71f0-8de4-5346cb45e224";
const outputPath = "C:/Users/PAMALI/Desktop/RDDT/v4/config/source/ATTRv_Normalized_Clinical_Filtering_Config_v3.xlsx";
const previewDir = `${outputDir}/previews`;

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));

function sheetMatrix(name) {
  return workbook.worksheets.getItem(name).getUsedRange().values;
}

function rowsAsObjects(matrix) {
  const headers = matrix[0];
  return matrix.slice(1).filter((row) => row.some((value) => value !== null && value !== ""))
    .map((row) => Object.fromEntries(headers.map((header, index) => [header, row[index] ?? null])));
}

function objectsAsMatrix(headers, rows) {
  return [headers, ...rows.map((row) => headers.map((header) => row[header] ?? null))];
}

function colName(index1) {
  let n = index1;
  let out = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    out = String.fromCharCode(65 + rem) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

function safeTableName(name) {
  const base = name.replace(/[^A-Za-z0-9_]/g, "");
  return `${base.slice(0, 220)}TableV2`;
}

function rewriteTableSheet(name, matrix, tableName = safeTableName(name)) {
  const sheet = workbook.worksheets.getItem(name);
  for (const table of [...sheet.tables.items]) table.delete();
  const used = sheet.getUsedRange();
  if (used) used.clear({ applyTo: "contents" });
  const rows = matrix.length;
  const cols = matrix[0].length;
  sheet.getRangeByIndexes(0, 0, rows, cols).values = matrix;
  const range = `A1:${colName(cols)}${rows}`;
  const table = sheet.tables.add(range, true, tableName);
  table.style = "TableStyleMedium2";
  table.showBandedRows = true;
  sheet.freezePanes.freezeRows(1);
  sheet.getRange(range).format.font = { name: "Arial", size: 10 };
  sheet.getRange(`A1:${colName(cols)}1`).format = {
    fill: "#17365D",
    font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
  };
  sheet.getRange(range).format.verticalAlignment = "top";
  return sheet;
}

function addTableSheet(name, matrix, widths) {
  const sheet = workbook.worksheets.add(name);
  const rows = matrix.length;
  const cols = matrix[0].length;
  const range = `A1:${colName(cols)}${rows}`;
  sheet.getRange(range).values = matrix;
  const table = sheet.tables.add(range, true, safeTableName(name));
  table.style = "TableStyleMedium2";
  table.showBandedRows = true;
  sheet.freezePanes.freezeRows(1);
  sheet.showGridLines = false;
  sheet.getRange(range).format.font = { name: "Arial", size: 10 };
  sheet.getRange(`A1:${colName(cols)}1`).format = {
    fill: "#17365D",
    font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
  };
  sheet.getRange(range).format.verticalAlignment = "top";
  widths.forEach((width, index) => {
    sheet.getRange(`${colName(index + 1)}:${colName(index + 1)}`).format.columnWidth = width;
  });
  return sheet;
}

const signalsMatrix = sheetMatrix("Signals");
const signalHeaders = signalsMatrix[0];
const signals = rowsAsObjects(signalsMatrix);
const originalSignalAtoms = rowsAsObjects(sheetMatrix("Signal_Atoms"));
const atomHeaders = sheetMatrix("Atoms")[0];
const originalAtoms = rowsAsObjects(sheetMatrix("Atoms"));
const terminologyHeaders = sheetMatrix("Terminology")[0];
const originalTerminology = rowsAsObjects(sheetMatrix("Terminology"));
const originalAtomMap = new Map(originalAtoms.map((atom) => [atom.Atom_ID, atom]));
const signalIdSet = new Set(signals.map((signal) => signal.Signal_ID));

const canonicalOverrides = {
  V02: `ANY OF:
  • ANY OF:
    • OBSERVE(axonal_neuropathy) [required: progressive=True, length_dependent=True, axonal=True, sensorimotor=True]
    • OBSERVE(idiopathic_progressive_neuropathy) [required: progressive=True, length_dependent=True, axonal=True, sensorimotor=True]
    • OBSERVE(polyneuropathy) [required: progressive=True, length_dependent=True, axonal=True, sensorimotor=True]
  • LINKED (CLINICAL_EPISODE):
    • ANY OF:
      • OBSERVE(axonal_neuropathy) [required: progressive=True, length_dependent=True, sensorimotor=True]
      • OBSERVE(idiopathic_progressive_neuropathy) [required: progressive=True, length_dependent=True, sensorimotor=True]
      • OBSERVE(polyneuropathy) [required: progressive=True, length_dependent=True, sensorimotor=True]
    • OBSERVE(axonal_pattern_on_emg) [required: axonal=True]`,
  V03: `INDEPENDENT ALL (separate source lineage required):
  • ANY OF:
    • OBSERVE(idiopathic_axonal_polyneuropathy)
    • LINKED (CLINICAL_EPISODE):
      • OBSERVE(polyneuropathy)
      • OBSERVE(axonal_neuropathy)
      • OBSERVE(idiopathic_progressive_neuropathy)
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
    • ESTABLISHED_SIGNAL(V17)`,
  V06: `INDEPENDENT ALL (separate source lineage required):
  • ANY OF:
    • ESTABLISHED_SIGNAL(V02)
    • ESTABLISHED_SIGNAL(V04)
    • ESTABLISHED_SIGNAL(V05)
  • ANY OF:
    • ESTABLISHED_SIGNAL(V24)
    • ESTABLISHED_SIGNAL(V25)`,
  V08: `ANY OF:
  • OBSERVE(fhx_adult_onset_neuropathy) [required: first_or_second_degree=True, adult_onset=True, progressive=True, unexplained=True]
  • OBSERVE(fhx_sudden_death) [required: first_or_second_degree=True, adult_onset=True, unexplained=True]`,
  V10: `ANY OF:
  • OBSERVE(alternating_bowel_habit) [required: chronic=True, unexplained=True]
  • OBSERVE(diarrhea) [required: chronic=True, unexplained=True]
  • OBSERVE(constipation) [required: chronic=True, unexplained=True]
  • OBSERVE(gi_dysmotility) [required: persistent=True, unexplained=True]`,
  V11: `ANY OF:
  • OBSERVE(gastroparesis) [required: unexplained=True]
  • OBSERVE(delayed_gastric_emptying) [required: unexplained=True]
  • OBSERVE(early_satiety) [required: persistent=True, unexplained=True]
  • LINKED (CLINICAL_EPISODE):
    • OBSERVE(nausea) [required: recurrent=True, unexplained=True]
    • OBSERVE(vomiting) [required: recurrent=True, unexplained=True]`,
  V13: `ANY OF:
  • OBSERVE(cts_bilateral)
  • OBSERVE(cts_recurrent)
  • INDEPENDENT ALL (laterality may be documented at different encounters):
    • OBSERVE(cts_left)
    • OBSERVE(cts_right)
  • LINKED (CLINICAL_EPISODE):
    • OBSERVE(cts_persistent_after_release)
    • ANY OF:
      • OBSERVE(cts_bilateral)
      • OBSERVE(cts_recurrent)`,
  V14: `LINKED (CLINICAL_EPISODE):
  • ANY OF:
    • OBSERVE(cidp)
    • OBSERVE(demyelinating_emg_pattern) [required: convincing_demyelinating_pattern=True]
  • OBSERVE(immunotherapy_exposure) [required: actual_exposure=True, adequate_trial=True]
  • OBSERVE(immunotherapy_nonresponse) [required: response_to_cidp_treatment=True, poor_or_absent=True]`,
  V26: `ALL OF:
  • OBSERVE(erectile_dysfunction)
  • ANY OF:
    • ESTABLISHED_SIGNAL(V02)
    • ESTABLISHED_SIGNAL(V04)
    • ESTABLISHED_SIGNAL(V05)
    • ESTABLISHED_SIGNAL(V09)
    • ESTABLISHED_SIGNAL(V10)
    • ESTABLISHED_SIGNAL(V11)
    • ESTABLISHED_SIGNAL(V27)`,
  V28: `ALL OF:
  • ANY OF:
    • OBSERVE(bulbar_neuropathy_symptoms) [required: unexplained=True, progressive=True]
    • OBSERVE(dysphagia) [required: unexplained=True, progressive_or_recurrent=True]
    • OBSERVE(dysarthria) [required: unexplained=True, progressive_or_recurrent=True]
    • OBSERVE(hoarseness) [required: unexplained=True, progressive_or_recurrent=True]
    • OBSERVE(choking) [required: unexplained=True, progressive_or_recurrent=True]
  • ANY OF:
    • ESTABLISHED_SIGNAL(V02)
    • ESTABLISHED_SIGNAL(V04)
    • ESTABLISHED_SIGNAL(V05)
    • ESTABLISHED_SIGNAL(V07)`,
  V31: `ANY OF:
  • OBSERVE(hf_medication_intolerance) [required: progressive=True, falling_bp=True]
  • LINKED (CLINICAL_EPISODE):
    • OBSERVE(medication_dose_change) [required: down_titration_or_discontinuation=True]
    • OBSERVE(declining_blood_pressure) [required: comparable_trend=True]`,
  V34: `ALL OF:
  • OBSERVE(eating_disorder_label) [required: severe_gi_weight_loss=True, psychiatric_explanation_unconvincing=True]
  • ANY OF:
    • ESTABLISHED_SIGNAL(V10)
    • ESTABLISHED_SIGNAL(V11)
  • ANY OF:
    • ESTABLISHED_SIGNAL(V02)
    • ESTABLISHED_SIGNAL(V04)
    • ESTABLISHED_SIGNAL(V05)`,
  V35: `ALL OF:
  • ANY OF:
    • OBSERVE(glaucoma)
    • OBSERVE(dry_eye)
  • ANY OF:
    • ESTABLISHED_SIGNAL(V15)
    • ESTABLISHED_SIGNAL(V16)
    • ESTABLISHED_SIGNAL(V02)
    • ESTABLISHED_SIGNAL(V04)
    • ESTABLISHED_SIGNAL(V05)
    • ESTABLISHED_SIGNAL(V07)
    • ESTABLISHED_SIGNAL(V08)`,
};

const blockerDefinitions = {
  V02: [{ atom: "v02_competing_neuropathy", action: "BLOCK_SIGNAL", required: "clearly_established=True, adequately_explains_neuropathy=True" }],
  V04: [{ atom: "v04_competing_neuropathy", action: "BLOCK_SIGNAL", required: "clearly_established=True, adequately_explains_small_fiber_neuropathy=True" }],
  V05: [{ atom: "v05_competing_dysautonomia", action: "BLOCK_SIGNAL", required: "clearly_established=True, adequately_explains_dysautonomia=True" }],
  V10: [{ atom: "v10_competing_gi", action: "BLOCK_SIGNAL", required: "clearly_established=True, adequately_explains_gi_dysmotility=True" }],
  V24: [{ atom: "v24_competing_lvh", action: "BLOCK_SIGNAL", required: "clearly_established=True, adequately_explains_wall_thickening_or_cardiomyopathy=True" }],
};

function parseGroupDescriptor(text) {
  if (text === "ANY OF:") return { type: "group", operator: "ANY", minimum: 1, linkage: null, independent: false, notes: null, children: [] };
  if (text === "ALL OF:") return { type: "group", operator: "ALL", minimum: null, linkage: null, independent: false, notes: null, children: [] };
  let match = text.match(/^AT LEAST (\d+) OF:$/);
  if (match) return { type: "group", operator: "AT_LEAST", minimum: Number(match[1]), linkage: null, independent: false, notes: null, children: [] };
  match = text.match(/^LINKED \(([^)]+)\):$/);
  if (match) return { type: "group", operator: "LINKED_ALL", minimum: null, linkage: match[1], independent: false, notes: null, children: [] };
  match = text.match(/^INDEPENDENT ALL(?: \(([^)]+)\))?:$/);
  if (match) return { type: "group", operator: "INDEPENDENT_ALL", minimum: null, linkage: null, independent: true, notes: match[1] ?? null, children: [] };
  return null;
}

function parseMember(text) {
  let match = text.match(/^OBSERVE\(([^)]+)\)(?: \[required: (.+)\])?$/);
  if (match) return { type: "member", memberType: "ATOM", id: match[1], required: match[2] ?? null };
  match = text.match(/^ESTABLISHED_SIGNAL\(([^)]+)\)$/);
  if (match) return { type: "member", memberType: "SIGNAL", id: match[1], required: null };
  throw new Error(`Unrecognized rule member: ${text}`);
}

function parseLogic(logic, signalId) {
  const items = [];
  for (const rawLine of String(logic).split(/\r?\n/)) {
    if (!rawLine.trim()) continue;
    const indent = rawLine.match(/^ */)[0].length;
    const text = rawLine.trim().replace(/^•\s*/, "");
    const node = parseGroupDescriptor(text) ?? parseMember(text);
    items.push({ indent, node });
  }
  const roots = [];
  const stack = [];
  for (const item of items) {
    while (stack.length && stack.at(-1).indent >= item.indent) stack.pop();
    if (stack.length) {
      if (stack.at(-1).node.type !== "group") throw new Error(`Member cannot own children in ${signalId}`);
      stack.at(-1).node.children.push(item.node);
    } else {
      roots.push(item.node);
    }
    if (item.node.type === "group") stack.push(item);
  }
  if (roots.length !== 1) throw new Error(`Expected one root in ${signalId}; found ${roots.length}`);
  const root = roots[0].type === "group"
    ? roots[0]
    : { type: "group", operator: "ALL", minimum: null, linkage: null, independent: false, notes: "Synthetic single-member root", children: [roots[0]] };
  return root;
}

function flattenRule(signal, root) {
  let groupCounter = 0;
  const groups = [];
  const members = [];
  const atomOrder = [];
  const atomSeen = new Set();
  const atomQualifiers = new Map();
  function walk(group, parentId, order) {
    const groupId = `${signal.Signal_ID}_G${String(++groupCounter).padStart(3, "0")}`;
    groups.push({
      Phenotype: signal.Phenotype,
      Signal_ID: signal.Signal_ID,
      Group_ID: groupId,
      Parent_Group_ID: parentId,
      Evaluation_Order: order,
      Operator: group.operator,
      Minimum_Count: group.minimum,
      Linkage_Type: group.linkage,
      Require_Independent_Lineage: group.independent,
      Notes: group.notes,
    });
    group.children.forEach((child, index) => {
      if (child.type === "group") {
        walk(child, groupId, index + 1);
        return;
      }
      members.push({
        Phenotype: signal.Phenotype,
        Signal_ID: signal.Signal_ID,
        Group_ID: groupId,
        Evaluation_Order: index + 1,
        Member_Type: child.memberType,
        Member_ID: child.id,
        Required_Attributes: child.required,
        Experiencer: child.memberType === "ATOM" ? (originalAtomMap.get(child.id)?.Experiencer ?? null) : null,
        Member_Role: "SUPPORT",
      });
      if (child.memberType === "ATOM") {
        if (!atomSeen.has(child.id)) {
          atomSeen.add(child.id);
          atomOrder.push(child.id);
        }
        if (child.required) {
          if (!atomQualifiers.has(child.id)) atomQualifiers.set(child.id, new Set());
          atomQualifiers.get(child.id).add(child.required);
        }
      }
    });
    return groupId;
  }
  const rootId = walk(root, null, 1);
  return { rootId, groups, members, atomOrder, atomQualifiers };
}

for (const signal of signals) {
  if (canonicalOverrides[signal.Signal_ID]) signal.Clinical_Logic = canonicalOverrides[signal.Signal_ID];
}
const signalById = new Map(signals.map((signal) => [signal.Signal_ID, signal]));
signalById.get("V08").Clinical_Feature = "Family history of unexplained adult-onset progressive neuropathy or unexplained adult-onset sudden death";
signalById.get("V08").Guardrail_Notes = "Supportive hereditary history only; less specific than a genetically/clinically established ATTR family history and not equivalent to V01/V07. Sudden death must be unexplained, adult-onset, and in a first- or second-degree relative.";

for (const signalId of ["V24", "V25", "V31", "V32", "V39", "V41"]) {
  const signal = signalById.get(signalId);
  const ids = new Set(String(signal.Clinical_Source_IDs ?? "").split(";").filter(Boolean));
  ids.add("SRC_ACC_CARDIAC_2025");
  signal.Clinical_Source_IDs = [...ids].join(";");
}
signalById.get("V40").Clinical_Source_IDs = "SRC_AA_CONTEMPORARY_2024";

const allGroups = [];
const allMembers = [];
const signalRules = [];
const flattenedBySignal = new Map();
for (const signal of signals) {
  const root = parseLogic(signal.Clinical_Logic, signal.Signal_ID);
  const flat = flattenRule(signal, root);
  flattenedBySignal.set(signal.Signal_ID, flat);
  allGroups.push(...flat.groups);
  allMembers.push(...flat.members);
  signal.Atom_IDs = flat.atomOrder.join(";");
  signalRules.push({
    Phenotype: signal.Phenotype,
    Signal_ID: signal.Signal_ID,
    Root_Group_ID: flat.rootId,
    Rule_Outcome: signal.Gate_Role === "NO_TRIGGER" ? "ROUTE_ONLY" : "SIGNAL_ESTABLISHED",
    Three_Valued_Logic: "TRUE_FALSE_UNKNOWN",
    Missing_Data_Policy: "UNKNOWN_DOES_NOT_SATISFY_AND_DOES_NOT_NEGATE",
    Blocker_Policy: blockerDefinitions[signal.Signal_ID] ? "APPLY_SIGNAL_BLOCKERS_AFTER_SUPPORT_RULE" : "NONE",
    Runtime_Executability: signal.Runtime_Executability,
    Enabled: signal.Enabled,
    Clinical_Source_IDs: signal.Clinical_Source_IDs,
  });
}

const blockerRows = [];
for (const [signalId, definitions] of Object.entries(blockerDefinitions)) {
  definitions.forEach((definition, index) => blockerRows.push({
    Phenotype: "ATTRV",
    Signal_ID: signalId,
    Blocker_ID: `${signalId}_B${String(index + 1).padStart(2, "0")}`,
    Atom_ID: definition.atom,
    Block_Action: definition.action,
    Required_Attributes: definition.required,
    Evaluation_Semantics: "Block only when blocker evaluates TRUE; FALSE or UNKNOWN does not block",
    Clinical_Source_IDs: signalById.get(signalId).Clinical_Source_IDs,
  }));
}

for (const member of allMembers) {
  if (member.Member_Type === "ATOM" && !originalAtomMap.has(member.Member_ID)) throw new Error(`Missing atom definition: ${member.Member_ID}`);
  if (member.Member_Type === "SIGNAL" && !signalIdSet.has(member.Member_ID)) throw new Error(`Missing signal dependency: ${member.Member_ID}`);
}
for (const blocker of blockerRows) {
  if (!originalAtomMap.has(blocker.Atom_ID)) throw new Error(`Missing blocker atom definition: ${blocker.Atom_ID}`);
}

const usedAtoms = new Set(allMembers.filter((member) => member.Member_Type === "ATOM").map((member) => member.Member_ID));
blockerRows.forEach((row) => usedAtoms.add(row.Atom_ID));
const removedAtomIds = originalAtoms.map((atom) => atom.Atom_ID).filter((atomId) => !usedAtoms.has(atomId)).sort();

const contributingSignals = new Map([...usedAtoms].map((atomId) => [atomId, new Set()]));
for (const member of allMembers) {
  if (member.Member_Type === "ATOM") contributingSignals.get(member.Member_ID).add(member.Signal_ID);
}
for (const blocker of blockerRows) contributingSignals.get(blocker.Atom_ID).add(blocker.Signal_ID);

const atoms = originalAtoms.filter((atom) => usedAtoms.has(atom.Atom_ID)).map((atom) => ({
  ...atom,
  Contributing_Signals: [...contributingSignals.get(atom.Atom_ID)].sort().join(";"),
  Extraction_Pattern: null,
}));
const retainedTerminology = originalTerminology.filter((row) => usedAtoms.has(row.Atom_ID));

const structuredSystems = new Set(["ICD10", "ICD9", "CPT_HCPCS", "LOINC", "SNOMED_CT"]);
const allowedCodeCharacters = {
  ICD10: new Set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"),
  ICD9: new Set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"),
  CPT_HCPCS: new Set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"),
  LOINC: new Set("0123456789-"),
  SNOMED_CT: new Set("0123456789"),
};

function isCodeToken(system, token) {
  if (!token) return false;
  const allowed = allowedCodeCharacters[system];
  if (!allowed) return false;
  const upper = token.toUpperCase();
  return [...upper].every((character) => allowed.has(character)) && [...upper].some((character) => character >= "0" && character <= "9");
}

function normalizeStructuredValue(system, value) {
  const text = String(value ?? "").trim();
  const lower = text.toLowerCase();
  if (!text || text.startsWith("(") || lower.includes("expect no match") || lower.includes("you can used") || lower.includes("derived -")) {
    return { action: "DROP", values: [] };
  }
  const colonIndex = text.indexOf(":");
  const tabIndex = text.indexOf("\t");
  const cutIndexes = [colonIndex, tabIndex].filter((index) => index >= 0);
  const prefix = (cutIndexes.length ? text.slice(0, Math.min(...cutIndexes)) : text).trim();
  const candidates = prefix.split("/").map((part) => part.trim()).filter(Boolean);
  if (candidates.length && candidates.every((candidate) => isCodeToken(system, candidate))) {
    return { action: "CODE", values: candidates.map((candidate) => candidate.toUpperCase()) };
  }
  return { action: "NLP", values: [text] };
}

const terminology = [];
const terminologyKeys = new Set();
let normalizedCodeRows = 0;
let reclassifiedNlpRows = 0;
let removedMalformedRows = 0;
let removedDuplicateRows = 0;
for (const row of retainedTerminology) {
  const system = String(row.Terminology_System ?? "").trim().toUpperCase();
  let normalizedRows;
  if (structuredSystems.has(system)) {
    const result = normalizeStructuredValue(system, row.Value);
    if (result.action === "DROP") {
      removedMalformedRows += 1;
      continue;
    }
    if (result.action === "CODE") {
      normalizedCodeRows += 1;
      normalizedRows = result.values.map((value) => ({ ...row, Terminology_System: system, Value: value, Value_Class: "STANDARD_CODE" }));
    } else {
      reclassifiedNlpRows += 1;
      normalizedRows = result.values.map((value) => ({ ...row, Terminology_System: "NLP", Value: value, Value_Class: "NLP_TERM" }));
    }
  } else {
    normalizedRows = [{ ...row, Terminology_System: system, Value: String(row.Value ?? "").trim() }];
  }
  for (const normalizedRow of normalizedRows) {
    const key = `${normalizedRow.Atom_ID}|${normalizedRow.Terminology_System}|${String(normalizedRow.Value).toLowerCase()}`;
    if (terminologyKeys.has(key)) {
      removedDuplicateRows += 1;
      continue;
    }
    terminologyKeys.add(key);
    terminology.push(normalizedRow);
  }
}

const existingMapping = new Map(originalSignalAtoms.map((row) => [`${row.Signal_ID}|${row.Atom_ID}`, row]));
const fallbackMappingByAtom = new Map();
for (const row of originalSignalAtoms) if (!fallbackMappingByAtom.has(row.Atom_ID)) fallbackMappingByAtom.set(row.Atom_ID, row);
const signalAtomHeaders = sheetMatrix("Signal_Atoms")[0];
const signalAtoms = [];
for (const signal of signals) {
  const flat = flattenedBySignal.get(signal.Signal_ID);
  for (const atomId of flat.atomOrder) {
    const atom = originalAtomMap.get(atomId);
    const base = existingMapping.get(`${signal.Signal_ID}|${atomId}`) ?? fallbackMappingByAtom.get(atomId) ?? {};
    const qualifiers = flat.atomQualifiers.has(atomId) ? [...flat.atomQualifiers.get(atomId)].join(" OR ") : "None (default affirmed/confirmed)";
    const isExisting = existingMapping.has(`${signal.Signal_ID}|${atomId}`);
    signalAtoms.push({
      Phenotype: signal.Phenotype,
      Signal_ID: signal.Signal_ID,
      Atom_ID: atomId,
      Atom_Preferred_Name: atom.Preferred_Clinical_Name,
      Experiencer: atom.Experiencer,
      Stage: atom.Stage,
      Required_Qualifiers: qualifiers,
      Signal_Logic: signal.Clinical_Logic,
      Runtime_Executability: isExisting ? base.Runtime_Executability : "NON_EXECUTABLE",
      Execution_Block_Reason: isExisting ? base.Execution_Block_Reason : "MISSING_VALIDATED_NLP_OR_CODE",
      Evidence_Mode: isExisting ? base.Evidence_Mode : null,
      Can_Fire_From_This_Mapping: isExisting ? base.Can_Fire_From_This_Mapping : false,
    });
  }
}

const guardrailHeaders = sheetMatrix("Guardrails")[0];
const guardrails = rowsAsObjects(sheetMatrix("Guardrails")).map((row) => ({
  ...row,
  Clinical_Condition: signalById.get(row.Guardrail_ID)?.Clinical_Logic ?? row.Clinical_Condition,
}));

const clinicalSourceHeaders = sheetMatrix("Clinical_Sources")[0];
const clinicalSources = rowsAsObjects(sheetMatrix("Clinical_Sources")).filter((row) => row.Source_ID !== "SRC_AA_GENERAL");
clinicalSources.push(
  {
    Source_ID: "SRC_ACC_CARDIAC_2025",
    Citation: "ACC Concise Clinical Guidance: Transthyretin Cardiac Amyloidosis Evaluation and Management",
    Year_or_Update: "2025",
    URL: "https://www.jacc.org/doi/10.1016/j.jacc.2025.09.004",
    Use_In_Config: "Current cardiac ATTR guidance: clinical/imaging clues prompt evaluation; imaging alone does not subtype amyloid; monoclonal screening and definitive ATTR typing remain separate steps.",
  },
  {
    Source_ID: "SRC_AA_CONTEMPORARY_2024",
    Citation: "Mirioglu et al. AA Amyloidosis: A Contemporary View",
    Year_or_Update: "2024",
    URL: "https://pubmed.ncbi.nlm.nih.gov/38568326/",
    Use_In_Config: "AA differential context: chronic inflammatory/autoinflammatory/infectious disease with renal protein-loss phenotype; histopathology is required for diagnosis.",
  },
);

const changeLogHeaders = sheetMatrix("Change_Log")[0];
const changeLog = rowsAsObjects(sheetMatrix("Change_Log"));
changeLog.push(
  { Change_ID: "FIX-01", Change_Type: "STRUCTURAL", Area: "Atom-to-signal integrity", Resolution: "Regenerated Signal_Atoms from normalized rule members; added missing relationships and removed unsupported mappings.", Rationale: "Every support atom now participates in the exact rule that establishes its signal.", Clinical_Source_IDs: null },
  { Change_ID: "FIX-02", Change_Type: "STRUCTURAL", Area: "Orphan atoms", Resolution: `Removed ${removedAtomIds.length} atoms and their terminology rows because they were neither support members nor explicit blockers.`, Rationale: "Atoms without a signal or blocker role cannot contribute to ATTRv filtering and create ambiguous evidence.", Clinical_Source_IDs: null },
  { Change_ID: "FIX-03", Change_Type: "STRUCTURAL", Area: "Signal rule normalization", Resolution: "Added Signal_Rules, Signal_Rule_Groups and Signal_Rule_Members with explicit nesting, operators, minimum counts, linkage and lineage semantics for all 41 signals.", Rationale: "Runtime must not infer boolean structure from indentation or prose.", Clinical_Source_IDs: null },
  { Change_ID: "FIX-04", Change_Type: "STRUCTURAL", Area: "Alternative-cause handling", Resolution: "Added Signal_Blockers for V02, V04, V05, V10 and V24; blocker UNKNOWN does not negate positive evidence.", Rationale: "Competing causes are explicit and auditable without treating missing documentation as a negative.", Clinical_Source_IDs: "SRC_ATTRV_US_PANEL;SRC_ATTRV_PN_CONSENSUS" },
  { Change_ID: "FIX-05", Change_Type: "CLINICAL", Area: "V03 red-flag domains", Resolution: "Corrected the signal rule so hereditary and orthopedic evidence are separate domains, matching the existing normalized composite definition.", Rationale: "Bilateral/recurrent CTS must not collapse into the hereditary family-history domain.", Clinical_Source_IDs: "SRC_ATTRV_US_PANEL;SRC_ATTRV_PN_CONSENSUS;SRC_ATTRV_REDFLAG_SPEC" },
  { Change_ID: "FIX-06", Change_Type: "CLINICAL", Area: "Feature completeness", Resolution: "Connected existing atoms for axonal EDX pattern, family sudden death, constipation, delayed gastric emptying, persistent CTS after release, demyelinating EDX pattern, bulbar symptoms and declining blood pressure to their intended signals.", Rationale: "Signal labels and executable member logic now agree; no codes were added.", Clinical_Source_IDs: "SRC_ATTRV_US_PANEL;SRC_ATTRV_PN_CONSENSUS;SRC_ATTRV_REDFLAG_SPEC" },
  { Change_ID: "FIX-07", Change_Type: "CLINICAL", Area: "V41 ATTR cardiac route", Resolution: "Removed absent_neuropathy_dysautonomia from V41 because coexisting neuropathy/dysautonomia does not block cardiac review or genotyping.", Rationale: "Genotype, not phenotype absence, distinguishes ATTRv from ATTRwt.", Clinical_Source_IDs: "SRC_ATTRV_GENE_REVIEWS;SRC_ACC_CARDIAC_2025" },
  { Change_ID: "FIX-08", Change_Type: "EXTRACTION", Area: "No-regex text extraction", Resolution: "Cleared all Extraction_Pattern cells. Terminology rows remain literal candidates for spaCy/medSpaCy contextual processing; structured codes remain exact-match candidates.", Rationale: "The V4 runtime must not use regex or simple substring matching for clinical text.", Clinical_Source_IDs: null },
  { Change_ID: "FIX-09", Change_Type: "GOVERNANCE", Area: "Missing codes", Resolution: "Added no terminology or clinical codes. Missing/unvalidated mappings remain explicitly non-executable for manual review.", Rationale: "Clinical codes must not be invented or externally supplemented during this correction.", Clinical_Source_IDs: null },
  { Change_ID: "FIX-10", Change_Type: "CLINICAL", Area: "Current references", Resolution: "Added 2025 ACC ATTR-CM guidance and a 2024 contemporary AA review; updated affected signal source links.", Rationale: "Cardiac and AA differential logic is traceable to current sources.", Clinical_Source_IDs: "SRC_ACC_CARDIAC_2025;SRC_AA_CONTEMPORARY_2024" },
  { Change_ID: "FIX-11", Change_Type: "EXTRACTION", Area: "Terminology normalization", Resolution: `Normalized ${normalizedCodeRows} structured terminology rows to executable code/prefix/range values, reclassified ${reclassifiedNlpRows} literal phrases to NLP, removed ${removedMalformedRows} commentary/placeholders, and removed ${removedDuplicateRows} duplicate rows.`, Rationale: "Structured matching must receive code values rather than descriptions or reviewer commentary; no new code was added or looked up.", Clinical_Source_IDs: null },
  { Change_ID: "FIX-12", Change_Type: "STRUCTURAL", Area: "Controlled vocabulary", Resolution: "Added ROUTE_ONLY to Rule_Outcome controlled vocabulary.", Rationale: "Signal_Rules route-only rows must validate against the workbook's own controlled vocabulary.", Clinical_Source_IDs: null },
);

const controlledVocabHeaders = sheetMatrix("Controlled_Vocabulary")[0];
const controlledVocab = rowsAsObjects(sheetMatrix("Controlled_Vocabulary"));
const extraVocab = [
  ["Rule_Group_Operator", "ALL"], ["Rule_Group_Operator", "ANY"], ["Rule_Group_Operator", "AT_LEAST"],
  ["Rule_Group_Operator", "LINKED_ALL"], ["Rule_Group_Operator", "INDEPENDENT_ALL"],
  ["Rule_Member_Type", "ATOM"], ["Rule_Member_Type", "SIGNAL"],
  ["Block_Action", "BLOCK_SIGNAL"], ["Rule_Outcome", "SIGNAL_ESTABLISHED"], ["Rule_Outcome", "ROUTE_ONLY"],
];
for (const [Vocabulary, Allowed_Value] of extraVocab) {
  if (!controlledVocab.some((row) => row.Vocabulary === Vocabulary && row.Allowed_Value === Allowed_Value)) controlledVocab.push({ Vocabulary, Allowed_Value });
}

const algorithmHeaders = sheetMatrix("Algorithm_Contract")[0];
const originalAlgorithm = rowsAsObjects(sheetMatrix("Algorithm_Contract"));
const algorithm = [
  { Step: 1, Stage: "INPUT_CONTRACT", Action: "Read only the permitted Snowflake source tables/columns and materialize intermediate state only as session-scoped temporary tables.", Invariant: "No permanent or transient warehouse tables; no source-table mutation or duplicated persistent data." },
  { Step: 2, Stage: "EVIDENCE_EXTRACTION", Action: "Use exact structured-code matching and spaCy/medSpaCy contextual NLP over configured literal terminology candidates.", Invariant: "No regex and no simple keyword/substring matching for clinical text; missing codes remain configuration gaps." },
  ...originalAlgorithm.slice(1).map((row, index) => ({ ...row, Step: index + 3 })),
];

const readmeMatrix = [
  ["ATTRv Normalized Clinical Filtering Configuration — Corrected V3", null],
  [null, null],
  ["Field", "Value"],
  ["Config Version", "ATTRV-NORM-2026-09-19-R2"],
  ["Phenotype", "ATTRv (hereditary transthyretin amyloidosis)"],
  ["Purpose", "Snowflake-workspace ATTRv suspicion/routing configuration with structured-code evidence and contextual spaCy/medSpaCy NLP evidence."],
  ["Warehouse Write Policy", "Read source data only. Session temporary tables are allowed. Permanent/transient warehouse tables and persistent source duplication are prohibited."],
  ["Text Extraction Policy", "No regex and no simple keyword/substring matching. Use configured literal NLP candidates with spaCy/medSpaCy context handling."],
  ["Code Policy", "No codes were added, inferred, or externally looked up. Existing mixed code/description values were normalized to their explicit code tokens; missing codes remain manual-review gaps."],
  ["Rule Structure", "All 41 signals have normalized rule, group and member rows. Alternative-cause blockers are stored separately."],
  ["Clinical Output", "ATTRV_REVIEW with categorical priority A/B/C and auditable witnesses. This is suspicion/review routing, not a diagnosis or probability."],
  ["No Additive Score", "Tier numbers are ordinal labels and are never summed."],
  ["Independence", "One source lineage or dedup group cannot satisfy two independent requirements."],
  ["Pre-test Boundary", "Only pre-test evidence is eligible; amyloid-directed testing/diagnosis leakage must not create screening evidence."],
  ["T3/T4 Policy", "Context-only by default. V24/V25 may satisfy only explicitly named cardiac requirements with Context_Witness_Allowed=TRUE."],
  ["Differentials", "AL, AA and ATTR cardiac/genotype-unresolved routes run in parallel and do not automatically subtract ATTRv evidence."],
  ["Validation Status", "Structural and cross-sheet validation passed for implementation; terminology accuracy and patient-level/prospective clinical validation remain required before clinical deployment."],
  ["Source Workbook", "ATTRv_Normalized_Clinical_Filtering_Config_v1.xlsx"],
  [null, null],
  ["Important clinical boundary", "A pathogenic/likely pathogenic TTR variant is strong hereditary evidence, but genotype alone does not establish symptomatic ATTRv amyloidosis. VUS does not establish ATTRv."],
];

rewriteTableSheet("Signals", objectsAsMatrix(signalHeaders, signals), "SignalsTable");
rewriteTableSheet("Signal_Atoms", objectsAsMatrix(signalAtomHeaders, signalAtoms), "SignalAtomsTable");
rewriteTableSheet("Atoms", objectsAsMatrix(atomHeaders, atoms), "AtomsTable");
rewriteTableSheet("Terminology", objectsAsMatrix(terminologyHeaders, terminology), "TerminologyTable");
rewriteTableSheet("Guardrails", objectsAsMatrix(guardrailHeaders, guardrails), "GuardrailsTable");
rewriteTableSheet("Algorithm_Contract", objectsAsMatrix(algorithmHeaders, algorithm), "AlgorithmContractTable");
rewriteTableSheet("Controlled_Vocabulary", objectsAsMatrix(controlledVocabHeaders, controlledVocab), "ControlledVocabularyTable");
rewriteTableSheet("Clinical_Sources", objectsAsMatrix(clinicalSourceHeaders, clinicalSources), "ClinicalSourcesTable");
rewriteTableSheet("Change_Log", objectsAsMatrix(changeLogHeaders, changeLog), "ChangeLogTable");

const readme = workbook.worksheets.getItem("README");
readme.unmergeCells("A1:F1");
readme.unmergeCells("A17:F20");
const readmeUsed = readme.getUsedRange();
if (readmeUsed) readmeUsed.clear({ applyTo: "contents" });
readme.getRange(`A1:B${readmeMatrix.length}`).values = readmeMatrix;
readme.mergeCells("A1:B1");
readme.getRange("A1:B1").format = { fill: "#17365D", font: { name: "Arial", size: 14, bold: true, color: "#FFFFFF" } };
readme.getRange("A3:B3").format = { fill: "#17365D", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
readme.getRange(`A4:B${readmeMatrix.length}`).format.font = { name: "Arial", size: 10 };
readme.getRange(`A4:B${readmeMatrix.length}`).format.wrapText = true;
readme.getRange("A:A").format.columnWidth = 28;
readme.getRange("B:B").format.columnWidth = 110;
readme.getRange(`A${readmeMatrix.length}:B${readmeMatrix.length}`).format = { fill: "#FFF2CC", font: { name: "Arial", size: 10, color: "#806000" }, wrapText: true };
readme.getRange(`A1:B${readmeMatrix.length}`).format.autofitRows();
readme.showGridLines = false;

const ruleHeaders = ["Phenotype", "Signal_ID", "Root_Group_ID", "Rule_Outcome", "Three_Valued_Logic", "Missing_Data_Policy", "Blocker_Policy", "Runtime_Executability", "Enabled", "Clinical_Source_IDs"];
const groupHeaders = ["Phenotype", "Signal_ID", "Group_ID", "Parent_Group_ID", "Evaluation_Order", "Operator", "Minimum_Count", "Linkage_Type", "Require_Independent_Lineage", "Notes"];
const memberHeaders = ["Phenotype", "Signal_ID", "Group_ID", "Evaluation_Order", "Member_Type", "Member_ID", "Required_Attributes", "Experiencer", "Member_Role"];
const blockerHeaders = ["Phenotype", "Signal_ID", "Blocker_ID", "Atom_ID", "Block_Action", "Required_Attributes", "Evaluation_Semantics", "Clinical_Source_IDs"];
addTableSheet("Signal_Rules", objectsAsMatrix(ruleHeaders, signalRules), [12, 10, 16, 20, 24, 52, 48, 22, 10, 80]);
addTableSheet("Signal_Rule_Groups", objectsAsMatrix(groupHeaders, allGroups), [12, 10, 16, 18, 14, 20, 14, 20, 22, 48]);
addTableSheet("Signal_Rule_Members", objectsAsMatrix(memberHeaders, allMembers), [12, 10, 16, 14, 16, 34, 58, 18, 16]);
addTableSheet("Signal_Blockers", objectsAsMatrix(blockerHeaders, blockerRows), [12, 10, 14, 34, 18, 64, 62, 52]);
workbook.worksheets.getItem("Signal_Rule_Groups").getRange(`J1:J${allGroups.length + 1}`).format.wrapText = true;
workbook.worksheets.getItem("Signal_Rule_Members").getRange(`G1:G${allMembers.length + 1}`).format.wrapText = true;
workbook.worksheets.getItem("Signal_Blockers").getRange(`F1:H${blockerRows.length + 1}`).format.wrapText = true;
workbook.worksheets.getItem("Signal_Blockers").getRange(`A2:H${blockerRows.length + 1}`).format.rowHeight = 36;

for (const name of ["Signals", "Signal_Atoms", "Atoms", "Terminology", "Guardrails", "Algorithm_Contract", "Controlled_Vocabulary", "Clinical_Sources", "Change_Log"]) {
  workbook.worksheets.getItem(name).showGridLines = false;
}
workbook.worksheets.getItem("Signals").getRange("C:C").format.columnWidth = 48;
workbook.worksheets.getItem("Signals").getRange("T:T").format.columnWidth = 78;
workbook.worksheets.getItem("Signals").getRange("V:V").format.columnWidth = 70;
workbook.worksheets.getItem("Signal_Atoms").getRange("H:H").format.columnWidth = 78;
workbook.worksheets.getItem("Atoms").getRange("H:J").format.columnWidth = 58;
workbook.worksheets.getItem("Terminology").getRange("C:C").format.columnWidth = 72;
workbook.worksheets.getItem("Terminology").getRange("G:G").format.columnWidth = 72;
workbook.worksheets.getItem("Change_Log").getRange("D:E").format.columnWidth = 72;
workbook.worksheets.getItem("Change_Log").getRange(`D1:F${changeLog.length + 1}`).format.wrapText = true;
workbook.worksheets.getItem("Change_Log").getRange(`A1:F${changeLog.length + 1}`).format.autofitRows();
workbook.worksheets.getItem("Clinical_Sources").getRange(`B1:E${clinicalSources.length + 1}`).format.wrapText = true;
workbook.worksheets.getItem("Clinical_Sources").getRange(`A1:E${clinicalSources.length + 1}`).format.autofitRows();

const actualSignalAtomPairs = new Set(signalAtoms.map((row) => `${row.Signal_ID}|${row.Atom_ID}`));
const expectedSignalAtomPairs = new Set(allMembers.filter((row) => row.Member_Type === "ATOM").map((row) => `${row.Signal_ID}|${row.Member_ID}`));
if (actualSignalAtomPairs.size !== expectedSignalAtomPairs.size || [...expectedSignalAtomPairs].some((key) => !actualSignalAtomPairs.has(key))) {
  throw new Error("Signal_Atoms does not exactly match normalized direct atom members");
}
if (atoms.some((atom) => atom.Extraction_Pattern)) throw new Error("Regex-like Extraction_Pattern values remain");
if (atoms.some((atom) => !atom.Contributing_Signals)) throw new Error("An atom lacks a signal correlation");
if (terminology.some((row) => !usedAtoms.has(row.Atom_ID))) throw new Error("Terminology contains an orphan atom");
if (terminology.length > originalTerminology.length) throw new Error("Terminology rows were added");
if (signalRules.length !== signals.length) throw new Error("Not every signal has a normalized rule");

const groupsById = new Map(allGroups.map((row) => [row.Group_ID, row]));
for (const group of allGroups) {
  if (group.Parent_Group_ID && !groupsById.has(group.Parent_Group_ID)) throw new Error(`Missing parent group ${group.Parent_Group_ID}`);
  if (group.Operator === "AT_LEAST" && !(group.Minimum_Count > 0)) throw new Error(`Invalid minimum count in ${group.Group_ID}`);
}

workbook.recalculate();
await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

const renderPlan = [
  ["README", `A1:B${readmeMatrix.length}`],
  ["Signals", "A1:Y16"],
  ["Signal_Atoms", "A1:L26"],
  ["Atoms", "A1:K36"],
  ["Terminology", "A1:G55"],
  ["Guardrails", "A1:H9"],
  ["Algorithm_Contract", `A1:D${algorithm.length + 1}`],
  ["Controlled_Vocabulary", `A1:B${controlledVocab.length + 1}`],
  ["Clinical_Sources", `A1:E${clinicalSources.length + 1}`],
  ["Change_Log", `A1:F${changeLog.length + 1}`],
  ["Signal_Rules", `A1:J${signalRules.length + 1}`],
  ["Signal_Rule_Groups", "A1:J45"],
  ["Signal_Rule_Members", "A1:I55"],
  ["Signal_Blockers", `A1:H${blockerRows.length + 1}`],
];
for (const [sheetName, range] of renderPlan) {
  const preview = await workbook.render({ sheetName, range, autoCrop: "all", scale: 0.75, format: "png" });
  await fs.writeFile(`${previewDir}/${sheetName}.png`, new Uint8Array(await preview.arrayBuffer()));
}
const terminologyBottomStart = Math.max(2, terminology.length - 35);
const terminologyBottom = await workbook.render({ sheetName: "Terminology", range: `A${terminologyBottomStart}:G${terminology.length + 1}`, autoCrop: "all", scale: 0.75, format: "png" });
await fs.writeFile(`${previewDir}/Terminology_bottom.png`, new Uint8Array(await terminologyBottom.arrayBuffer()));

const audit = {
  input: inputPath,
  output: outputPath,
  counts: {
    signals: signals.length,
    originalAtoms: originalAtoms.length,
    retainedAtoms: atoms.length,
    removedAtoms: removedAtomIds.length,
    originalTerminologyRows: originalTerminology.length,
    retainedTerminologyRows: terminology.length,
    addedTerminologyRows: 0,
    signalAtomMappings: signalAtoms.length,
    normalizedGroups: allGroups.length,
    normalizedMembers: allMembers.length,
    blockerRows: blockerRows.length,
  },
  removedAtomIds,
  assertions: {
    everyAtomCorrelatesToSupportOrBlocker: true,
    everySignalHasNormalizedRule: true,
    signalAtomsMatchDirectRuleMembers: true,
    extractionPatternsCleared: true,
    terminologyRowsAdded: false,
    clinicalCodesAdded: false,
    regexClinicalTextRulesAdded: false,
  },
};
await fs.writeFile(`${outputDir}/ATTRv_v2_correction_audit.json`, JSON.stringify(audit, null, 2), "utf8");
console.log(JSON.stringify(audit, null, 2));

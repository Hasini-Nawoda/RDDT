import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = path.resolve(
  "v4_build_tools/source/ATTRv_Normalized_Clinical_Filtering_Config_v3.xlsx",
);
const outputDir = path.resolve(
  "v4_build_tools/workbook_audit_artifacts/cursor_review_before",
);
await fs.mkdir(outputDir, { recursive: true });

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
const results = [];
for (const [label, options] of [
  ["overview", { kind: "workbook,sheet,table", maxChars: 12000, tableMaxRows: 4, tableMaxCols: 8 }],
  ["signals", { kind: "table", range: "Signals!A1:Y40", maxChars: 30000, tableMaxRows: 40, tableMaxCols: 25 }],
  ["signal_atoms", { kind: "table", range: "Signal_Atoms!A1:L101", maxChars: 30000, tableMaxRows: 101, tableMaxCols: 12 }],
  ["rule_groups", { kind: "table", range: "Signal_Rule_Groups!A1:J83", maxChars: 30000, tableMaxRows: 83, tableMaxCols: 10 }],
  ["rule_members", { kind: "table", range: "Signal_Rule_Members!A1:I186", maxChars: 50000, tableMaxRows: 186, tableMaxCols: 9 }],
]) {
  const result = await workbook.inspect(options);
  results.push(JSON.stringify({ label, ndjson: result.ndjson }));
}
await fs.writeFile(path.join(outputDir, "inspection.ndjson"), `${results.join("\n")}\n`, "utf8");

for (const [sheetName, range, fileName] of [
  ["Signals", "A1:Y40", "Signals.png"],
  ["Signal_Atoms", "A1:L101", "Signal_Atoms.png"],
  ["Signal_Rule_Groups", "A1:J83", "Signal_Rule_Groups.png"],
  ["Signal_Rule_Members", "A1:I186", "Signal_Rule_Members.png"],
]) {
  const image = await workbook.render({ sheetName, range, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(outputDir, fileName), new Uint8Array(await image.arrayBuffer()));
}

console.log(JSON.stringify({ workbookPath, outputDir, renderedSheets: 4 }));

import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "v4_build_tools/source/ATTRv_Normalized_Clinical_Filtering_Config_v3.xlsx";
const outDir = "v4_build_tools/workbook_audit_artifacts/pre_edit_render";
await fs.mkdir(outDir, { recursive: true });
const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const summary = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 8000,
  tableMaxRows: 4,
  tableMaxCols: 8,
  tableMaxCellChars: 120,
});
console.log(summary.ndjson);
for (const sheetName of ["Signals", "Signal_Atoms", "Signal_Rules", "Signal_Rule_Groups", "Signal_Rule_Members", "Signal_Blockers", "Change_Log"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(`${outDir}/${sheetName}.png`, new Uint8Array(await preview.arrayBuffer()));
}

import { columnHelp, type HelpTable } from "@/lib/columnHelp.js";
import { FieldInfo } from "./FieldInfo.js";

/** The "i" for a column heading, from the shared column help; nothing for a column without any. */
export function HeaderTip({ table, col }: { table: HelpTable; col: string }) {
  const lines = columnHelp(table, col);
  return lines ? <FieldInfo label={col} lines={lines} /> : null;
}

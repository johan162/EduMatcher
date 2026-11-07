import { useDraftStore } from "@/store/draftStore";
import {
  SYMBOL_FILE_COLUMNS,
  addImportedSymbols,
  readSymbolFile,
  writeSymbolFile,
} from "@/lib/symbolFile";
import { TableFileActions } from "@/components/ui/TableFileActions";

/** Import/export the symbol list, one row per symbol with the IPO dialog's fields. */
export function SymbolFileActions() {
  const empty = useDraftStore((s) => s.draft.symbolOrder.length === 0);
  return (
    <TableFileActions
      noun="symbols"
      columns={SYMBOL_FILE_COLUMNS}
      empty={empty}
      read={readSymbolFile}
      add={addImportedSymbols}
      write={writeSymbolFile}
    />
  );
}

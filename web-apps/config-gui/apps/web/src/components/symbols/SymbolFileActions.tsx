import { useRef, useState } from "react";
import { useDraftStore } from "@/store/draftStore";
import {
  SYMBOL_FILE_COLUMNS,
  addImportedSymbols,
  readSymbolFile,
  writeSymbolFile,
  type SymbolFileFormat,
} from "@/lib/symbolFile";
import { ConfirmDialog } from "@/components/ui/Dialog";

/** Most problems listed in a dialog; the rest are counted. */
const MAX_LISTED = 15;

function ProblemList({ intro, items }: { intro: string; items: string[] }) {
  return (
    <>
      <p>{intro}</p>
      <ul className="mt-2 max-h-64 list-disc overflow-y-auto pl-5">
        {items.slice(0, MAX_LISTED).map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      {items.length > MAX_LISTED && <p className="mt-1">…and {items.length - MAX_LISTED} more.</p>}
    </>
  );
}

const buttonClass = "rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50";

/**
 * Import and export the symbol list as CSV or JSON, one row per symbol with
 * the IPO dialog's fields. An import is all-or-nothing.
 */
export function SymbolFileActions() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const fileRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [importErrors, setImportErrors] = useState<string[] | null>(null);
  const [exportWarnings, setExportWarnings] = useState<string[] | null>(null);

  const onImportFile = async (file: File) => {
    setStatus(null);
    const format: SymbolFileFormat = file.name.toLowerCase().endsWith(".json") ? "json" : "csv";
    const { symbols, errors } = readSymbolFile(await file.text(), format, draft);
    if (errors.length > 0) {
      setImportErrors(errors);
      return;
    }
    update((d) => addImportedSymbols(d, symbols));
    setStatus(`Imported ${symbols.length} symbol${symbols.length === 1 ? "" : "s"}.`);
  };

  const onExport = (format: SymbolFileFormat) => {
    setStatus(null);
    const { text, warnings } = writeSymbolFile(draft, format);
    const blob = new Blob([text], { type: format === "json" ? "application/json" : "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `symbols.${format}`;
    a.click();
    // Revoking synchronously can cancel the download in some browsers.
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    if (warnings.length > 0) setExportWarnings(warnings);
  };

  const empty = draft.symbolOrder.length === 0;

  return (
    <>
      <input
        ref={fileRef}
        type="file"
        accept=".csv,.json"
        className="hidden"
        aria-label="Symbol file"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void onImportFile(file);
          e.target.value = "";
        }}
      />
      <button
        type="button"
        onClick={() => fileRef.current?.click()}
        className={buttonClass}
        title={`Add symbols from a CSV or JSON file with the columns: ${SYMBOL_FILE_COLUMNS.join(", ")}.`}
      >
        Import symbols…
      </button>
      <button type="button" disabled={empty} onClick={() => onExport("csv")} className={buttonClass}>
        Export CSV
      </button>
      <button type="button" disabled={empty} onClick={() => onExport("json")} className={buttonClass}>
        Export JSON
      </button>
      {status && <span className="text-sm text-success">{status}</span>}

      <ConfirmDialog
        open={importErrors !== null}
        onOpenChange={(o) => !o && setImportErrors(null)}
        title="Symbol import failed"
        description={
          importErrors && (
            <ProblemList intro="Nothing was imported. Fix these problems and try again:" items={importErrors} />
          )
        }
        confirmLabel="OK"
        cancelLabel="Close"
        onConfirm={() => setImportErrors(null)}
      />
      <ConfirmDialog
        open={exportWarnings !== null}
        onOpenChange={(o) => !o && setExportWarnings(null)}
        title="Some symbols were exported approximately"
        description={
          exportWarnings && (
            <ProblemList
              intro="The IPO fields cannot describe these symbols exactly (different last buy and sell prices, a hand-edited or extra market-maker quote, or no price). Re-importing the file would not reproduce them:"
              items={exportWarnings}
            />
          )
        }
        confirmLabel="OK"
        cancelLabel="Close"
        onConfirm={() => setExportWarnings(null)}
      />
    </>
  );
}

import { useRef, useState } from "react";
import type { EngineConfigDraft } from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import type { TableFileFormat } from "@/lib/tableFile";
import { ConfirmDialog } from "@/components/ui/Dialog";

/** Most problems listed in a dialog; the rest are counted. */
const MAX_LISTED = 15;

function ProblemList({ intro, items }: { intro: string; items: string[] }) {
  return (
    <>
      <p>{intro}</p>
      <ul className="mt-2 max-h-64 list-disc overflow-y-auto pl-5">
        {items.slice(0, MAX_LISTED).map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
      {items.length > MAX_LISTED && <p className="mt-1">…and {items.length - MAX_LISTED} more.</p>}
    </>
  );
}

const buttonClass = "rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50";

interface Props<T> {
  /** Plural name of the rows, e.g. "symbols"; also the download's base name. */
  noun: string;
  columns: readonly string[];
  /** Whether the draft holds no rows to export. */
  empty: boolean;
  read: (text: string, format: TableFileFormat, draft: EngineConfigDraft) => { items: T[]; errors: string[] };
  add: (d: EngineConfigDraft, items: T[]) => void;
  write: (draft: EngineConfigDraft, format: TableFileFormat) => { text: string; warnings: string[] };
}

/**
 * Import and export a draft list as CSV or JSON. An import is
 * all-or-nothing; an export names the rows it could not write exactly.
 */
export function TableFileActions<T>({ noun, columns, empty, read, add, write }: Props<T>) {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const fileRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [importErrors, setImportErrors] = useState<string[] | null>(null);
  const [exportWarnings, setExportWarnings] = useState<string[] | null>(null);

  const onImportFile = async (file: File) => {
    setStatus(null);
    const format: TableFileFormat = file.name.toLowerCase().endsWith(".json") ? "json" : "csv";
    const { items, errors } = read(await file.text(), format, draft);
    if (errors.length > 0) {
      setImportErrors(errors);
      return;
    }
    update((d) => add(d, items));
    setStatus(`Imported ${items.length} ${noun}.`);
  };

  const onExport = (format: TableFileFormat) => {
    setStatus(null);
    const { text, warnings } = write(draft, format);
    const blob = new Blob([text], { type: format === "json" ? "application/json" : "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${noun}.${format}`;
    a.click();
    // Revoking synchronously can cancel the download in some browsers.
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    if (warnings.length > 0) setExportWarnings(warnings);
  };

  return (
    <>
      <input
        ref={fileRef}
        type="file"
        accept=".csv,.json"
        className="hidden"
        aria-label={`${noun} file`}
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
        title={`Add ${noun} from a CSV or JSON file with the columns: ${columns.join(", ")}.`}
      >
        Import {noun}…
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
        title={`Import of ${noun} failed`}
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
        title={`Some ${noun} were exported approximately`}
        description={
          exportWarnings && (
            <ProblemList
              intro="The file's columns cannot describe these rows exactly, so re-importing the file would not reproduce them:"
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

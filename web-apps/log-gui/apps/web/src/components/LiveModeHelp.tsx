import { useEffect, useState } from "react";
import { HelpCircle } from "lucide-react";

/** "(?)" beside the Explorer's LIVE/history switch: what each mode shows. Esc closes it. */
export function LiveModeHelp({ bufferRows, historyRows }: { bufferRows: number; historyRows: number }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="What LIVE and history mean"
        aria-expanded={open}
        className="rounded p-1 text-fg-subtle hover:bg-bg-inset hover:text-fg"
      >
        <HelpCircle size={16} />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} aria-hidden="true" />
          <div
            role="dialog"
            aria-label="LIVE and history"
            className="absolute left-0 top-8 z-50 w-96 rounded border border-border bg-bg-subtle p-3 text-xs shadow-2xl"
          >
            <h3 className="mb-1 font-semibold text-fg">▶ LIVE</h3>
            <ul className="mb-3 list-disc space-y-1 pl-4 text-fg-subtle">
              <li>Streams new lines from pm-log-srv as they arrive, newest at the top.</li>
              <li>
                Shows only lines received since this page opened, kept in the browser: the newest{" "}
                {bufferRows.toLocaleString()}. The count is how many of those match the filters.
              </li>
              <li>Scrolling away from the top pauses the stream; the "new rows" bar resumes it.</li>
              <li>A marker row shows where lines were missed; switch to history to read them.</li>
            </ul>
            <h3 className="mb-1 font-semibold text-fg">history</h3>
            <ul className="list-disc space-y-1 pl-4 text-fg-subtle">
              <li>Searches the stored log database (log.db), including lines from before this page opened.</li>
              <li>
                Shows the newest {historyRows.toLocaleString()} matching lines; the count is every match in
                the database.
              </li>
              <li>Does not stream new lines as they arrive; changing a filter runs the search again.</li>
            </ul>
            <p className="mt-3 text-fg-subtle">The filters apply in both modes.</p>
          </div>
        </>
      )}
    </div>
  );
}

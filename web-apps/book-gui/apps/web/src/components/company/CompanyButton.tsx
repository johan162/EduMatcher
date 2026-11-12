/**
 * The top bar's "Company info" button and the right-edge drawer it opens for
 * the watched symbol: one tab, Company, as on trader-gui's symbol drawer.
 */

import { useEffect, useState } from "react";
import { Building2, X } from "lucide-react";
import { CompanyPanel } from "./CompanyPanel.js";
import { useBookStore } from "../../store/useBookStore.js";

export function CompanyButton() {
  const symbol = useBookStore((s) => s.watched);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={!symbol}
        aria-label="Company info"
        aria-expanded={open}
        title={symbol ? `Company info: ${symbol}` : "Company info — pick a symbol first"}
        className="rounded p-1.5 text-fg-subtle hover:bg-bg-inset hover:text-fg disabled:opacity-40 disabled:hover:bg-transparent"
      >
        <Building2 size={16} />
      </button>

      {open && symbol && (
        <aside
          role="dialog"
          aria-label={`${symbol} company`}
          className="fixed bottom-0 right-0 top-12 z-40 flex w-[640px] max-w-[90vw] flex-col border-l border-border bg-bg shadow-2xl"
        >
          <div className="flex items-start justify-between border-b border-border px-4 pb-2 pt-3">
            <h2 className="font-mono text-lg font-semibold text-fg">{symbol}</h2>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close company info"
              className="text-fg-subtle hover:text-fg"
            >
              <X size={18} />
            </button>
          </div>

          <div role="tablist" aria-label="Symbol detail views" className="flex border-b border-border px-2">
            <button
              role="tab"
              aria-selected
              type="button"
              className="relative px-3 py-2 text-xs font-medium text-fg"
            >
              Company
              <span className="absolute -bottom-px left-2 right-2 h-0.5 bg-accent" />
            </button>
          </div>

          <div className="flex-1 overflow-auto p-4">
            <CompanyPanel symbol={symbol} />
          </div>
        </aside>
      )}
    </>
  );
}

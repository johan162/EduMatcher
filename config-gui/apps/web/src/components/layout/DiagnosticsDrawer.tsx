import clsx from "clsx";
import { useNavigate } from "react-router-dom";
import type { Diagnostic } from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { tabById } from "@/lib/tabs";

const SEVERITY_STYLE: Record<Diagnostic["severity"], string> = {
  error: "border-l-error",
  warning: "border-l-warning",
  info: "border-l-linked",
};

const SEVERITY_ICON: Record<Diagnostic["severity"], string> = {
  error: "✗",
  warning: "!",
  info: "i",
};

export function DiagnosticsDrawer() {
  const diagnostics = useDraftStore((s) => s.diagnostics);
  const setHighlightedPaths = useDraftStore((s) => s.setHighlightedPaths);
  const navigate = useNavigate();

  const counts = {
    error: diagnostics.filter((d) => d.severity === "error").length,
    warning: diagnostics.filter((d) => d.severity === "warning").length,
    info: diagnostics.filter((d) => d.severity === "info").length,
  };

  const jump = (diagnostic: Diagnostic) => {
    const tab = tabById(diagnostic.tab);
    if (tab) navigate(tab.path);
    setHighlightedPaths(diagnostic.fieldPaths);
    window.setTimeout(() => setHighlightedPaths([]), 2500);
  };

  return (
    <aside className="flex h-full w-full flex-col border-l border-border bg-surface">
      <header className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Diagnostics</h2>
        <div className="mt-1 flex gap-3 text-xs">
          <span className="text-error">{counts.error} errors</span>
          <span className="text-warning">{counts.warning} warnings</span>
          <span className="text-fg-subtle">{counts.info} info</span>
        </div>
      </header>

      <div aria-live="polite" className="flex-1 space-y-2 overflow-y-auto p-3">
        {diagnostics.length === 0 && (
          <p className="px-1 text-sm text-fg-subtle">No issues. Configuration looks valid.</p>
        )}
        {diagnostics.map((diagnostic, i) => (
          <div
            key={`${diagnostic.id}-${i}`}
            className={clsx(
              "rounded-md border border-border border-l-2 bg-surface-raised p-2.5 text-xs",
              SEVERITY_STYLE[diagnostic.severity],
            )}
          >
            <div className="flex items-start gap-2">
              <span
                className={clsx(
                  "font-semibold",
                  diagnostic.severity === "error"
                    ? "text-error"
                    : diagnostic.severity === "warning"
                      ? "text-warning"
                      : "text-linked",
                )}
              >
                {SEVERITY_ICON[diagnostic.severity]}
              </span>
              <p className="flex-1 leading-snug">{diagnostic.message}</p>
            </div>
            <button
              type="button"
              onClick={() => jump(diagnostic)}
              className="mt-1 text-linked underline"
            >
              Jump →
            </button>
          </div>
        ))}
      </div>
    </aside>
  );
}

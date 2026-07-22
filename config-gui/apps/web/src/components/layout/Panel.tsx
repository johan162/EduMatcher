import { useDraftStore } from "@/store/draftStore";

interface Props {
  tabId: string;
  title: string;
  intro?: React.ReactNode;
  /** Right-aligned actions (e.g. add buttons). */
  actions?: React.ReactNode;
  children: React.ReactNode;
}

/** Standard tab panel with a section intro and a panel-level diagnostics banner. */
export function Panel({ tabId, title, intro, actions, children }: Props) {
  const diagnostics = useDraftStore((s) => s.diagnostics).filter((d) => d.tab === tabId);
  const errors = diagnostics.filter((d) => d.severity === "error");
  const warnings = diagnostics.filter((d) => d.severity === "warning");

  return (
    <div className="mx-auto max-w-3xl px-6 py-6">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{title}</h1>
          {intro && <p className="mt-1 max-w-2xl text-sm text-fg-subtle">{intro}</p>}
        </div>
        {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
      </div>

      {errors.length > 0 && (
        <div
          role="alert"
          className="mb-4 rounded-md border border-error/40 bg-error/10 px-3 py-2 text-sm text-error"
        >
          {errors.length} error{errors.length > 1 ? "s" : ""} on this tab must be resolved before export.
        </div>
      )}
      {warnings.length > 0 && (
        <div className="mb-4 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
          {warnings.length} warning{warnings.length > 1 ? "s" : ""} on this tab.
        </div>
      )}

      <div className="space-y-1">{children}</div>
    </div>
  );
}

interface SectionProps {
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
}

export function Section({ title, description, children }: SectionProps) {
  return (
    <section className="mt-6 rounded-lg border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-fg-subtle">{title}</h2>
      {description && <p className="mt-1 text-sm text-fg-subtle">{description}</p>}
      <div className="mt-3 space-y-1">{children}</div>
    </section>
  );
}

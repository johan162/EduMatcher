/**
 * Small presentational pieces shared by the screens: page and panel headings,
 * stat tiles, status badges (text first, colour second, so state is never
 * conveyed by colour alone), and the "more rows" note for bounded lists.
 */
import type { ReactNode } from "react";

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="mb-4 flex flex-col gap-1">
      <h1 className="text-lg font-semibold">{title}</h1>
      {children && <div className="text-xs text-fg-dim">{children}</div>}
    </header>
  );
}

export function Panel({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section aria-label={title} className="mb-5 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="flex min-w-[10rem] flex-col gap-0.5 rounded border border-line bg-panel px-3 py-2">
      <span data-stat-label className="text-[11px] uppercase tracking-wide text-fg-dim">
        {label}
      </span>
      <span className="num text-base">{value}</span>
      {sub && <span className="text-[11px] text-fg-faint">{sub}</span>}
    </div>
  );
}

export type Tone = "ok" | "warn" | "bad" | "neutral";

const TONE: Record<Tone, string> = {
  ok: "border-bid/50 text-bid",
  warn: "border-halt/50 text-halt",
  bad: "border-ask/50 text-ask",
  neutral: "border-line text-fg-dim",
};

export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`inline-block rounded border px-1.5 py-0.5 text-[11px] font-medium ${TONE[tone]}`}>{children}</span>;
}

/** The note under a bounded list that the server had more rows than it sent. */
export function MoreRows({ hasMore, count }: { hasMore: boolean; count: number }) {
  if (!hasMore) return null;
  return (
    <p className="text-xs text-halt">
      Showing the first {count} rows; more match. Narrow the filters (the date range, say) to see the rest.
    </p>
  );
}

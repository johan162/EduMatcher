import clsx from "clsx";
import type { ReactNode } from "react";

/**
 * A titled section. `stale` dims the whole panel when its data is no longer
 * live (design §15) — applied at the panel rather than per value, so a viewer
 * can tell at a glance which parts of the screen they can still trust.
 */
export function Panel({
  title,
  right,
  stale = false,
  children,
}: {
  title: string;
  right?: ReactNode;
  stale?: boolean;
  children: ReactNode;
}) {
  return (
    <section className={clsx("rounded border border-border bg-bg-subtle", stale && "stale")}>
      <header className="flex items-center justify-between border-b border-border px-3 py-2">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-fg-subtle">{title}</h2>
        {right}
      </header>
      <div className="p-3">{children}</div>
    </section>
  );
}

/** Shown in place of a table when there is genuinely nothing to report. */
export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-fg-faint">{children}</p>;
}

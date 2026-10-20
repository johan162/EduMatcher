/**
 * A dashboard row (design §12.1): a collapsible section with a title and a
 * count badge ("PROCESSES · 1 degraded"), remembered per browser.
 */

import clsx from "clsx";
import { useId, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useRowStore } from "../../store/useRowStore.js";

export interface RowProps {
  id: string;
  title: string;
  /** Beside the title: what needs attention, in words. */
  badge?: string;
  /** Tailwind text class for the badge. */
  badgeTone?: string;
  children: ReactNode;
}

export function Row({ id, title, badge, badgeTone = "text-fg-subtle", children }: RowProps) {
  const collapsed = useRowStore((s) => Boolean(s.collapsed[id]));
  const toggle = useRowStore((s) => s.toggle);
  const bodyId = useId();
  const Chevron = collapsed ? ChevronRight : ChevronDown;

  return (
    <section aria-labelledby={`${bodyId}-title`} data-widget="row" className="min-w-0 rounded border border-border bg-bg-subtle">
      <h2 className="m-0">
        <button
          id={`${bodyId}-title`}
          type="button"
          aria-expanded={!collapsed}
          aria-controls={bodyId}
          onClick={() => toggle(id)}
          className="flex w-full min-w-0 items-center gap-2 px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-fg"
        >
          <Chevron size={14} aria-hidden="true" className="shrink-0" />
          <span className="shrink-0">{title}</span>
          {badge && (
            <span className={clsx("min-w-0 truncate font-normal normal-case", badgeTone)} title={badge}>
              · {badge}
            </span>
          )}
        </button>
      </h2>
      {!collapsed && (
        <div id={bodyId} className="border-t border-border px-3 py-3">
          {children}
        </div>
      )}
    </section>
  );
}

/**
 * A detail drawer over the dashboard's right side (design §12.3, D4): the
 * dashboard stays live behind it. Not modal -- the rows can still be
 * clicked, which opens another drawer in its place. On opening, focus
 * moves to its title; Escape or the close button closes it.
 *
 * Positioned inside the shell's main area rather than fixed to the
 * viewport, so it sits under the top bar at every font size (CSS zoom, see
 * useFontSizeStore) and dims with the panels when the data is frozen.
 */

import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { useCloseDrawer } from "../../hooks/drawer.js";

export interface DrawerProps {
  /** What is shown: "Process", "Participant", "Order book". */
  kind: string;
  /** Its key, id or symbol. */
  title: string;
  /** Beside the title: the cross-app links. */
  actions?: ReactNode;
  children: ReactNode;
}

export function Drawer({ kind, title, actions, children }: DrawerProps) {
  const close = useCloseDrawer();
  const titleId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), [kind, title]);

  return (
    <aside
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      data-widget="drawer"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          close();
        }
      }}
      className="absolute inset-y-0 right-0 z-30 flex w-full max-w-[44rem] flex-col border-l border-border bg-bg shadow-2xl"
    >
      <header className="flex items-start gap-3 border-b border-border bg-bg-subtle px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="m-0 text-[11px] font-semibold uppercase tracking-wide text-fg-faint">{kind}</p>
          <h2 id={titleId} ref={heading} tabIndex={-1} title={title} className="m-0 truncate font-mono text-base font-semibold text-fg focus:outline-none">
            {title}
          </h2>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-3 pt-3 text-xs">{actions}</div>}
        <button type="button" aria-label="Close" onClick={close} className="shrink-0 rounded p-1 text-fg-subtle hover:bg-bg-inset hover:text-fg">
          <X size={16} aria-hidden="true" />
        </button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
    </aside>
  );
}

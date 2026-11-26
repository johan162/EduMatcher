/**
 * A detail drawer over the right side of the content area, as dash-gui's
 * (CG21, D3): the page stays live behind it. Not modal -- the page can still
 * be used, and opening another item replaces the drawer's content. On opening,
 * focus moves to its title; Escape or the close button closes it.
 *
 * It is drawn into the app shell's drawer layer (`DrawerHostContext`), which
 * sits beside the scrolling `main`: so it stays under the top bar at every
 * font size (CSS zoom) and does not scroll away with the page. Wide (90% of
 * the content area), because what it holds are full screens of tables.
 */
import { createContext, useContext, useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

/** The shell's drawer layer; null until it has mounted. */
export const DrawerHostContext = createContext<HTMLElement | null>(null);

export interface DrawerProps {
  /** What is shown: "Participant". */
  kind: string;
  /** Its id. */
  title: string;
  onClose: () => void;
  children: ReactNode;
}

export function Drawer(props: DrawerProps) {
  const host = useContext(DrawerHostContext);
  return host ? createPortal(<DrawerPanel {...props} />, host) : null;
}

function DrawerPanel({ kind, title, onClose, children }: DrawerProps) {
  const titleId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), [title]);

  return (
    <div
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
      className="absolute inset-y-0 right-0 z-30 flex w-[90%] max-w-[110rem] flex-col border-l border-line bg-app shadow-2xl"
    >
      <div className="flex items-start gap-3 border-b border-line bg-panel px-4 py-3">
        <h2 id={titleId} ref={heading} tabIndex={-1} className="min-w-0 flex-1 truncate focus:outline-none">
          <span className="block text-[11px] font-semibold uppercase tracking-wide text-fg-dim">{kind}</span>{" "}
          <span className="font-mono text-base font-semibold">{title}</span>
        </h2>
        <button type="button" aria-label="Close" onClick={onClose} className="shrink-0 rounded p-1 text-fg-dim hover:bg-raised hover:text-fg">
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
    </div>
  );
}

/** Footer (design §12.1): the bridge's view of pm-monitor. */

import clsx from "clsx";
import { useDashStore } from "../../store/useDashStore.js";

export function StatusStrip() {
  const monitor = useDashStore((s) => s.monitor);

  return (
    <footer className="flex h-7 shrink-0 items-center gap-4 border-t border-border bg-bg-subtle px-4 text-xs text-fg-subtle">
      <span data-testid="monitor-state" className={clsx(monitor !== "UP" && "font-semibold text-halt")}>
        pm-monitor {monitor ?? "unknown"}
      </span>
    </footer>
  );
}

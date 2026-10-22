/**
 * A chart's or gauge's visible title (design §12.3: every panel is named).
 * The panel already names itself to assistive technology by its
 * aria-label, so the title is hidden from it rather than read twice.
 */

import { widgetHelp } from "../../lib/help.js";
import { InfoTip } from "../shared/InfoTip.js";

export function PanelTitle({ children }: { children: string }) {
  const help = widgetHelp(children);
  return (
    <div className="mb-1 flex min-w-0 items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">
      <span aria-hidden="true" title={children} className="truncate">
        {children}
      </span>
      {help && <InfoTip label={children} help={help} />}
    </div>
  );
}

import type { ReactNode } from "react";
import { HelpPopover } from "./HelpPopover";

/**
 * Table column header with an optional "i" help popover, matching the
 * field-level help affordance used elsewhere. The popover is wrapped in a
 * `normal-case` span so the glyph is not upper-cased by table header styling.
 */
export function ColumnHead({ label, help }: { label: string; help?: ReactNode }) {
  return (
    <span className="inline-flex items-center">
      {label}
      {help && (
        <span className="normal-case">
          <HelpPopover>{help}</HelpPopover>
        </span>
      )}
    </span>
  );
}

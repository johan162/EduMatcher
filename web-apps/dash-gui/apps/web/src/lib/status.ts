/**
 * How a status looks: colour, glyph and text together, never colour alone
 * (design §12.5) -- for colour-blind operators and for screenshots pasted
 * into incident notes.
 */

import type { ExchangeStatusName } from "@edumatcher/dash-types";

export interface StatusLook {
  glyph: string;
  label: string;
  /** Tailwind text colour class. */
  text: string;
  /** Tailwind border colour class. */
  border: string;
}

export const EXCHANGE_STATUS: Record<ExchangeStatusName, StatusLook> = {
  OPERATIONAL: { glyph: "●", label: "OPERATIONAL", text: "text-ok", border: "border-ok" },
  DEGRADED: { glyph: "◐", label: "DEGRADED", text: "text-warning", border: "border-warning" },
  IMPAIRED: { glyph: "◆", label: "IMPAIRED", text: "text-error", border: "border-error" },
  DOWN: { glyph: "✕", label: "DOWN", text: "text-error", border: "border-error" },
};

/** No snapshot yet: nothing is known about the exchange. */
export const UNKNOWN_STATUS: StatusLook = {
  glyph: "○",
  label: "NO DATA",
  text: "text-stopped",
  border: "border-stopped",
};

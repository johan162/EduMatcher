/**
 * How a status looks: colour, glyph and text together, never colour alone
 * (design §12.5) -- for colour-blind operators and for screenshots pasted
 * into incident notes.
 */

import type { EventSeverity, ExchangeStatusName, ProcessState } from "@edumatcher/dash-types";
import type { Level } from "./thresholds.js";

export interface Tone {
  /** Tailwind classes, written out in full so Tailwind finds them. */
  text: string;
  border: string;
  bg: string;
  /** The colour as a CSS value, for SVG fills and strokes. */
  color: string;
}

export const TONE = {
  ok: { text: "text-ok", border: "border-ok", bg: "bg-ok", color: "var(--ok)" },
  warning: { text: "text-warning", border: "border-warning", bg: "bg-warning", color: "var(--warn)" },
  error: { text: "text-error", border: "border-error", bg: "bg-error", color: "var(--crit)" },
  hung: { text: "text-hung", border: "border-hung", bg: "bg-hung", color: "var(--hung)" },
  missing: { text: "text-missing", border: "border-missing", bg: "bg-missing", color: "var(--missing)" },
  stopped: { text: "text-stopped", border: "border-stopped", bg: "bg-stopped", color: "var(--stopped)" },
  info: { text: "text-info", border: "border-info", bg: "bg-info", color: "var(--info)" },
} satisfies Record<string, Tone>;

export interface StatusLook extends Tone {
  glyph: string;
  label: string;
}

function look(glyph: string, label: string, tone: Tone): StatusLook {
  return { glyph, label, ...tone };
}

export const EXCHANGE_STATUS: Record<ExchangeStatusName, StatusLook> = {
  OPERATIONAL: look("●", "OPERATIONAL", TONE.ok),
  DEGRADED: look("◐", "DEGRADED", TONE.warning),
  IMPAIRED: look("◆", "IMPAIRED", TONE.error),
  DOWN: look("✕", "DOWN", TONE.error),
};

/** No snapshot yet: nothing is known about the exchange. */
export const UNKNOWN_STATUS: StatusLook = look("○", "NO DATA", TONE.stopped);

/** §10's process states, with the mockup's glyphs (§12.3 row 2). */
export const PROCESS_STATE: Record<ProcessState, StatusLook> = {
  HEALTHY: look("●", "HEALTHY", TONE.ok),
  DEGRADED: look("◐", "DEGRADED", TONE.warning),
  HUNG: look("◆", "HUNG", TONE.hung),
  SILENT: look("✕", "SILENT", TONE.error),
  DEAD: look("✕", "DEAD", TONE.error),
  MISSING: look("✕", "MISSING", TONE.missing),
  STOPPED: look("○", "STOPPED", TONE.stopped),
};

/** A threshold level (lib/thresholds.ts). */
export const LEVEL: Record<Level, StatusLook> = {
  OK: look("●", "OK", TONE.ok),
  WARN: look("◐", "WARN", TONE.warning),
  CRIT: look("✕", "CRIT", TONE.error),
};

/** An event's severity (event log, chart annotations). */
export const SEVERITY: Record<EventSeverity, StatusLook> = {
  INFO: look("●", "INFO", TONE.info),
  WARN: look("◐", "WARN", TONE.warning),
  CRIT: look("✕", "CRIT", TONE.error),
};

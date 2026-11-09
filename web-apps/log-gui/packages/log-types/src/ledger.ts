/**
 * Log ledger (docs-design/EduMatcher-Log-Ledger.md §5): an explanation and
 * suggested actions per WARNING+ log call site, keyed by the row's `tpl`.
 * The bridge reads it from `pm-log-cli ledger export`, so Python and the GUI
 * share one copy of the text.
 */

import type { LogLevel } from "./log-row.js";

export interface LedgerEntry {
  logger: string;
  template: string;
  level: LogLevel;
  explanation: string;
  actions: string[];
}

/** `GET /api/ledger`. `available: false` means pm-log-cli could not be run. */
export interface LedgerResponse {
  available: boolean;
  reason?: string;
  entries: Record<string, LedgerEntry>;
}

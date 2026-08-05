/**
 * Bridge settings the frontend needs in order to behave as configured.
 *
 * These all used to be hard-coded in the browser while the bridge parsed an
 * environment variable nothing consumed — so setting the variable silently did
 * nothing. `GET /api/ui-config` is the one place that contract is now stated:
 * anything here is authoritative, and the frontend has no defaults of its own.
 */

import type { LogLevel } from "./log-row.js";

/** Named severity of the current error rate, derived from `ErrorRateBands`. */
export type ErrorRateBand = "normal" | "elevated" | "high" | "severe";

/**
 * Three thresholds, four bands. Each threshold is the rate at which the next
 * band begins, so they must be read as lower bounds:
 *
 * ```
 *   rate <  normalPerMin    -> "normal"
 *   rate <  elevatedPerMin  -> "elevated"
 *   rate <  severePerMin    -> "high"
 *   rate >= severePerMin    -> "severe"
 * ```
 */
export interface ErrorRateBands {
  normalPerMin: number;
  elevatedPerMin: number;
  severePerMin: number;
}

export interface UiConfig {
  /** Minimum issue level counted as "unacked" in the top bar and nav badge. */
  alertLevel: LogLevel;
  /** Minimum level that becomes an issue at all — seed and live ingest alike. */
  issuesMinLevel: LogLevel;
  /** Seconds of silence after which a connected process is flagged. */
  processSilenceSec: number;
  errorRate: ErrorRateBands;
}

/** Classifies an errors-per-minute rate. Shared so bridge and UI cannot drift. */
export function classifyErrorRate(perMin: number, bands: ErrorRateBands): ErrorRateBand {
  if (perMin >= bands.severePerMin) return "severe";
  if (perMin >= bands.elevatedPerMin) return "high";
  if (perMin >= bands.normalPerMin) return "elevated";
  return "normal";
}

/**
 * Threshold levels, judged exactly as pm-monitor judges them
 * (monitor/thresholds.py `Band`): above `warn` is WARN, above `crit` is
 * CRIT, both strictly; an inverted rule (disk free: low is bad) the other
 * way round. A tile therefore never disagrees with the THRESHOLD events.
 */

export type Level = "OK" | "WARN" | "CRIT";

export interface Thresholds {
  warn: number;
  /** Absent: the rule has no critical level. */
  crit?: number;
  /** Low is bad (disk free). */
  invert?: boolean;
}

export function levelOf(value: number, t: Thresholds): Level {
  if (t.invert) {
    if (t.crit !== undefined && value < t.crit) return "CRIT";
    return value < t.warn ? "WARN" : "OK";
  }
  if (t.crit !== undefined && value > t.crit) return "CRIT";
  return value > t.warn ? "WARN" : "OK";
}

/** What hovering a tile or gauge says (design §12.3): "WARN above 80%, CRIT above 95%". */
export function describeThresholds(t: Thresholds, show: (v: number) => string): string {
  const side = t.invert ? "below" : "above";
  const parts = [`WARN ${side} ${show(t.warn)}`];
  if (t.crit !== undefined) parts.push(`CRIT ${side} ${show(t.crit)}`);
  return parts.join(", ");
}

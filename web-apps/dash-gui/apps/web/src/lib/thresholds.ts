/**
 * Threshold levels, judged exactly as pm-monitor judges them
 * (monitor/thresholds.py `Band`): above `warn` is WARN, above `crit` is
 * CRIT, both strictly; an inverted rule (disk free: low is bad) the other
 * way round. A tile therefore never disagrees with the THRESHOLD events.
 *
 * The rules themselves come from the bridge (`/api/thresholds`, I113);
 * {@link fromRule} turns one into a widget's `thresholds` prop.
 */

import type { ThresholdRule } from "@edumatcher/dash-types";

export type Level = "OK" | "WARN" | "CRIT";

export interface Thresholds {
  warn: number;
  /** Absent: the rule has no critical level. */
  crit?: number;
  /** Low is bad (disk free). */
  invert?: boolean;
}

/** The level of `value`; null without a finite value (nothing to judge). */
export function levelOf(value: number | null, t: Thresholds): Level | null {
  if (value === null || !Number.isFinite(value)) return null;
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

/** A `/api/thresholds` rule as a widget's `thresholds`. */
export function fromRule(rule: ThresholdRule): Thresholds {
  return rule.crit === null ? { warn: rule.warn, invert: rule.invert } : { warn: rule.warn, crit: rule.crit, invert: rule.invert };
}

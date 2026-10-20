/**
 * The time picker's ranges and the refresh selector's intervals (design
 * §12.2, D1.3).
 *
 * The range is a query parameter, as in Grafana: `?from=now-1h`, so a URL
 * shared in an incident opens on the same window. The bridge accepts the
 * same names as `range=` (RANGE_NAMES, shared through dash-types).
 *
 * The refresh interval is how often the history panels ask the bridge
 * again; the live figures come at 1 Hz whatever it says. 10 s is the
 * default because 10 s is the finest history there is (metrics.db's raw
 * samples): asking more often returns the same points.
 */

import { RANGE_NAMES, type RangeName } from "@edumatcher/dash-types";

export { RANGE_NAMES, type RangeName };

export const DEFAULT_RANGE: RangeName = "1h";

export const RANGE_LABEL: Record<RangeName, string> = {
  "5m": "Last 5 minutes",
  "15m": "Last 15 minutes",
  "1h": "Last 1 hour",
  "6h": "Last 6 hours",
  "24h": "Last 24 hours",
  "7d": "Last 7 days",
};

/** `now-6h` -> `6h`; anything else is not a range we offer. */
export function rangeFromParam(param: string | null): RangeName | null {
  const name = param?.startsWith("now-") ? param.slice(4) : null;
  return name !== null && (RANGE_NAMES as readonly string[]).includes(name) ? (name as RangeName) : null;
}

export function rangeParam(range: RangeName): string {
  return `now-${range}`;
}

export const REFRESH_NAMES = ["off", "10s", "30s", "1m", "5m"] as const;
export type RefreshName = (typeof REFRESH_NAMES)[number];

export const DEFAULT_REFRESH: RefreshName = "10s";

export const REFRESH_MS: Record<RefreshName, number | null> = {
  off: null,
  "10s": 10_000,
  "30s": 30_000,
  "1m": 60_000,
  "5m": 300_000,
};

export const REFRESH_LABEL: Record<RefreshName, string> = {
  off: "Off",
  "10s": "10s",
  "30s": "30s",
  "1m": "1m",
  "5m": "5m",
};

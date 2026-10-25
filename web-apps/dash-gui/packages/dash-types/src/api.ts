/**
 * The bridge's REST responses (design §11.2). History comes from pm-monitor's
 * metrics.db, opened read-only.
 *
 * Every time in a request is epoch milliseconds or ISO-8601 with `Z` or an
 * offset (what metrics.db and the snapshot hold is UTC with `Z`); every
 * time in a response is epoch milliseconds, which is what a chart wants.
 * Buckets start on the session clock (`exchange.session_timezone`), so an
 * hourly bar is an hour of the exchange's day. Display is the web's job,
 * always in the session timezone (apps/web/src/lib/time.ts).
 */

import type { HealthEvent } from "./health.js";
import type { MonitorState } from "./ws.js";

/**
 * The time-picker ranges (design §11.2, the Grafana set): what `range=`
 * accepts and what the web's picker offers, in that order.
 */
export const RANGE_NAMES = ["5m", "15m", "1h", "6h", "24h", "7d"] as const;
export type RangeName = (typeof RANGE_NAMES)[number];

/** Each range's span in milliseconds. */
export const RANGE_MS: Record<RangeName, number> = {
  "5m": 5 * 60_000,
  "15m": 15 * 60_000,
  "1h": 3600_000,
  "6h": 6 * 3600_000,
  "24h": 24 * 3600_000,
  "7d": 7 * 24 * 3600_000,
};

/** `[epoch ms, value]`, oldest first. */
export type Point = [number, number];

/** Which table answered: every sample (10 s) or the one-minute roll-up. */
export type Resolution = "raw" | "1m";

/** `GET /api/series` */
export interface SeriesResponse {
  name: string;
  label: string;
  source: string;
  resolution: Resolution;
  /** Seconds each point stands for after server-side bucketing. */
  bucketSec: number;
  points: Point[];
}

/** `GET /api/series/multi` */
/**
 * `GET /api/series/multi`: several series -- one metric's labels
 * (`labels=`), one label across processes (`sources=`), or several metrics
 * of one process (`names=`) -- all at one resolution and on the same bucket
 * starts, so they line up in one chart. `name` is the metrics joined by ",".
 */
export interface MultiSeriesResponse {
  name: string;
  resolution: Resolution;
  bucketSec: number;
  series: { name: string; label: string; source: string; points: Point[] }[];
}

/**
 * `GET /api/rate`: counter increments per bucket, summed over sources, over
 * labels when none is given, and over every name of `names=` (then `name`
 * is them joined by ",").
 */
export interface RateResponse {
  name: string;
  label: string | null;
  bucket: "1m" | "1h";
  points: Point[];
}

/** `GET /api/rate/by-label`: one counter's increments per bucket, one series per label (orders/min by participant). */
export interface RateByLabelResponse {
  name: string;
  bucket: "1m" | "1h";
  series: { label: string; points: Point[] }[];
}

/** `GET /api/daily` */
export interface DailyResponse {
  name: string;
  label: string | null;
  days: { date: string; total: number }[];
}

/** `GET /api/events` */
export interface EventsResponse {
  events: HealthEvent[];
}

/**
 * One threshold rule as pm-monitor judges it (monitor/thresholds.py): WARN
 * strictly above `warn`, CRIT strictly above `crit` -- or below both when
 * `invert` (low is bad). `crit` null: the rule has no critical level.
 */
export interface ThresholdRule {
  warn: number;
  crit: number | null;
  invert: boolean;
  /** Set in `monitor.thresholds` (else fixed in pm-monitor's code). */
  configurable: boolean;
}

/**
 * `GET /api/thresholds`: every rule `ActiveBreach.rule` can name, keyed by
 * that name. From the deployed artifact's `monitor.thresholds` -- what
 * pm-monitor read when it started -- or pm-monitor's built-in defaults
 * when no artifact is deployed (as pm-monitor itself then runs).
 */
export interface ThresholdsResponse {
  source: "artifact" | "defaults";
  /** The artifact read, or looked for. */
  path: string;
  rules: Record<string, ThresholdRule>;
}

/** Body of every 4xx/5xx. */
export interface ApiError {
  error: string;
  message: string;
}

/** Base URLs of the sibling GUIs (`LOG_GUI_URL`, `BOOK_GUI_URL`); null: not configured, no link. */
export interface CrossAppLinks {
  logGui: string | null;
  bookGui: string | null;
}

/** `GET /api/bridge/status` */
export interface BridgeStatus {
  version: string;
  monitor: MonitorState;
  /** ISO-8601 UTC of the last monitor state change. */
  monitorSince: string;
  /** `host:port` of pm-monitor's PUB socket the bridge subscribes to. */
  source: string;
  /** Whether ZeroMQ holds a TCP connection to it (DOWN while true: pm-monitor is silent). */
  monitorConnected: boolean;
  snapshotsIn: number;
  eventsIn: number;
  /** Messages that were not two frames of topic + JSON object. */
  invalidIn: number;
  /** Messages that failed inside the bridge; each is logged (at most once a minute). */
  handlerErrors: number;
  /** `ts` of the latest snapshot while UP; null otherwise. */
  lastSnapshotTs: string | null;
  /** The session timezone in use: the latest snapshot's, else metrics.db's, else UTC. */
  sessionTz: string;
  metricsDb: { path: string; ok: boolean; detail: string };
  wsClients: number;
  /** Where the bridge's own log records go: `lalf`, `stdout`, … */
  logging: string;
  links: CrossAppLinks;
}

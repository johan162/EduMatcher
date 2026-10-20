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
 * `GET /api/series/multi`: several series of one metric -- its labels
 * (`labels=`), or one label across processes (`sources=`) -- all at one
 * resolution and on the same bucket starts, so they line up in one chart.
 */
export interface MultiSeriesResponse {
  name: string;
  resolution: Resolution;
  bucketSec: number;
  series: { label: string; source: string; points: Point[] }[];
}

/** `GET /api/rate`: counter increments per bucket, summed over sources (and labels when none is given). */
export interface RateResponse {
  name: string;
  label: string | null;
  bucket: "1m" | "1h";
  points: Point[];
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

/** Body of every 4xx/5xx. */
export interface ApiError {
  error: string;
  message: string;
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
}

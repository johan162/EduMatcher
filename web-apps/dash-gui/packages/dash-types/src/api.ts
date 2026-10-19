/**
 * The bridge's REST responses (design §11.2). History comes from pm-monitor's
 * metrics.db, opened read-only.
 *
 * Every time in a request is ISO-8601 UTC (what metrics.db and the snapshot
 * hold) or epoch milliseconds; every time in a response is epoch
 * milliseconds, which is what a chart wants.
 */

import type { HealthEvent } from "./health.js";
import type { MonitorState } from "./ws.js";

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
export interface MultiSeriesResponse {
  name: string;
  source: string;
  resolution: Resolution;
  bucketSec: number;
  series: { label: string; points: Point[] }[];
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
  snapshotsIn: number;
  eventsIn: number;
  /** `ts` of the latest snapshot; null before the first. */
  lastSnapshotTs: string | null;
  metricsDb: { path: string; ok: boolean; detail: string };
  wsClients: number;
  /** Where the bridge's own log records go: `lalf`, `stdout`, … */
  logging: string;
}

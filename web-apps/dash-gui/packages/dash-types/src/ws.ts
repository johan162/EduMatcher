/**
 * Bridge <-> browser WebSocket frame schema (design §11.1).
 *
 * One flat JSON object per frame, discriminated by `type`. Snapshot and
 * event payloads are pm-monitor's, passed through unchanged (see health.ts).
 * The browser sends nothing.
 */

import type { HealthEvent, HealthSnapshot } from "./health.js";

/** Whether the bridge is receiving pm-monitor's snapshots (none for 3 s = DOWN). */
export type MonitorState = "UP" | "DOWN";

/** First frame on every connection; the latest snapshot follows when UP. */
export interface HelloFrame {
  type: "hello";
  /** The bridge's own version, from its package.json. */
  version: string;
  monitor: MonitorState;
  /**
   * IANA session timezone the exchange buckets trading days in, from the
   * latest snapshot; "UTC" until one has arrived.
   */
  sessionTz: string;
}

export interface SnapshotFrame {
  type: "snapshot";
  data: HealthSnapshot;
}

export interface EventFrame {
  type: "event";
  data: HealthEvent;
}

/** Sent whenever the uplink state changes. */
export interface MonitorStateFrame {
  type: "monitor_state";
  monitor: MonitorState;
}

export type ServerFrame = HelloFrame | SnapshotFrame | EventFrame | MonitorStateFrame;

/**
 * Bridge <-> browser WebSocket frame schema (design §11.1).
 *
 * One flat JSON object per frame, discriminated by `type`. WP-C1 scaffold:
 * the frames the empty app needs. WP-C2 (C2.5) adds `snapshot` and `event`,
 * mirroring `spec/messages/health.yaml` — never re-deriving a figure.
 */

/** Whether the bridge is receiving pm-monitor's snapshots (none for 3 s = DOWN). */
export type MonitorState = "UP" | "DOWN";

/** First frame on every connection. */
export interface HelloFrame {
  type: "hello";
  /** The bridge's own version, from its package.json. */
  version: string;
  monitor: MonitorState;
  /** IANA session timezone the exchange buckets trading days in. */
  sessionTz: string;
}

/** Sent whenever the uplink state changes. */
export interface MonitorStateFrame {
  type: "monitor_state";
  monitor: MonitorState;
}

export type ServerFrame = HelloFrame | MonitorStateFrame;

/** `GET /api/bridge/status`. */
export interface BridgeStatus {
  version: string;
  monitor: MonitorState;
  /** `host:port` of pm-monitor's PUB socket the bridge subscribes to. */
  source: string;
  metricsDb: string;
  wsClients: number;
  /** Where the bridge's own log records go: `lalf`, `stdout`, … */
  logging: string;
}

/**
 * Bridge <-> browser WebSocket frame schema (design §16.3).
 *
 * The client cannot reach `pm-log-srv` at all — `set_filter`/`set_live` only
 * change what a tab receives from the bridge's single upstream subscription
 * (§6.5).
 */

import type { LogFilter, LogRow } from "./log-row.js";
import type { AckRecord, Issue } from "./issue.js";

export interface CounterWindow {
  eventsPerMin: number;
  errorsPerMin: number;
  perLevel: Record<string, number>;
  perProcess: Record<string, number>;
  windowSec: number;
  serverLastSeq: number;
}

export type ServerLiveState = "UP" | "DOWN";

export interface ServerState {
  server: string;
  state: ServerLiveState;
  proto: string;
  subscribers: number;
  activeBackfills: number;
  lastSeq: number;
  inboxDropped: number;
  defaultLeaseSec: number;
  timestamp: number;
}

export interface SourceHealth {
  ok: boolean;
  detail: string;
}

export type ServerFrame =
  | {
      t: "hello";
      subId: string;
      serverName: string | null;
      lastSeq: number;
    }
  | { t: "event"; row: LogRow }
  | { t: "events"; rows: LogRow[] }
  | { t: "counters"; window: CounterWindow }
  | { t: "issue"; issue: Issue }
  | { t: "ack"; fingerprint: string; ack: AckRecord | null }
  | { t: "server_state"; state: ServerState }
  | {
      t: "bridge_status";
      lalfPs: SourceHealth;
      logDb: SourceHealth;
      wsClients: number;
    };

export type ClientFrame =
  | { t: "set_filter"; filter: LogFilter }
  | { t: "set_live"; live: boolean }
  | { t: "ping" };

/** Log-server liveness as the browsers see it. */

import type { ServerState } from "@edumatcher/log-types";

/**
 * The `DOWN` state to broadcast when heartbeats stop. A killed or crashed
 * log server never publishes its own `DOWN`, so the bridge synthesises one
 * from the last state it saw.
 */
export function downFrom(last: ServerState | null, nowSec: number): ServerState {
  return {
    server: last?.server ?? "",
    state: "DOWN",
    proto: last?.proto ?? "",
    subscribers: 0,
    activeBackfills: 0,
    lastSeq: last?.lastSeq ?? 0,
    inboxDropped: last?.inboxDropped ?? 0,
    defaultLeaseSec: last?.defaultLeaseSec ?? 0,
    timestamp: nowSec,
  };
}

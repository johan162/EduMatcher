import { create } from "zustand";
import { classifyMonitorEnvelope, isTerminalStatus } from "@/lib/monitorEvents.js";
import type {
  AdminOrder,
  MonitorEvent,
  MonitorSnapshotData,
  WsEnvelope,
} from "@/types/index.js";

/** Bounded ring for the cross-gateway event log (§15.9). */
const MAX_EVENTS = 1000;

let _seq = 0;
const nextId = () => `mon-${Date.now()}-${++_seq}`;

interface MonitorStore {
  /** Cross-gateway orders, keyed by order_id (seeded by snapshot, live via order.*). */
  orders: Record<string, AdminOrder>;
  /** Newest-first log of cross-gateway activity. */
  events: MonitorEvent[];
  /** Per-gateway last stream_seq from the latest snapshot. */
  lastSeq: Record<string, number>;
  /** Unix ms of the last snapshot applied (the "reconciled at" marker). */
  snapshotAt: number | null;

  /** Route one admin-monitor frame (snapshot or live event) into the store. */
  ingest: (env: WsEnvelope<unknown>) => void;
  clear: () => void;
}

export const useMonitorStore = create<MonitorStore>((set, get) => ({
  orders: {},
  events: [],
  lastSeq: {},
  snapshotAt: null,

  ingest: (env) => {
    if (!env || typeof env.type !== "string") return;

    if (env.type === "monitor.snapshot") {
      const data = (env.data ?? {}) as Partial<MonitorSnapshotData>;
      const orders: Record<string, AdminOrder> = {};
      for (const o of data.orders ?? []) {
        if (o && typeof o.order_id === "string") orders[o.order_id] = o;
      }
      const hadEvents = get().events.length > 0;
      // A snapshot arriving after we already had events means a reconnect: the
      // window between disconnect and now cannot be replayed, so mark a visible
      // gap boundary rather than pretend continuity (§15.9).
      const gap: MonitorEvent[] = hadEvents
        ? [
            {
              id: nextId(),
              seq: null,
              ts: typeof env.ts === "string" ? env.ts : new Date().toISOString(),
              kind: "GAP",
              topic: "",
              gateway_id: null,
              symbol: null,
              order_id: null,
              detail: "Reconnected — events during the outage were not replayed.",
            },
          ]
        : [];
      set({
        orders,
        lastSeq: data.last_seq ?? {},
        snapshotAt: Date.now(),
        events: [...gap, ...get().events].slice(0, MAX_EVENTS),
      });
      return;
    }

    const cls = classifyMonitorEnvelope(env);
    if (!cls) return; // not a log-worthy frame

    set((s) => {
      let orders = s.orders;
      // Fold order lifecycle events into the cross-gateway orders map.
      if (cls.orderStatus && cls.order_id) {
        const prev = s.orders[cls.order_id] ?? {
          order_id: cls.order_id,
          gateway_id: cls.gateway_id ?? "",
          status: cls.orderStatus,
        };
        const merged: AdminOrder = {
          ...prev,
          ...(env.data as Record<string, unknown>),
          order_id: cls.order_id,
          gateway_id: cls.gateway_id ?? prev.gateway_id,
          status: cls.orderStatus,
        };
        orders = { ...s.orders, [cls.order_id]: merged };
      }

      const event: MonitorEvent = {
        id: nextId(),
        seq: typeof env.seq === "number" ? env.seq : null,
        ts: typeof env.ts === "string" ? env.ts : new Date().toISOString(),
        kind: cls.kind,
        topic: typeof env.topic === "string" ? env.topic : "",
        gateway_id: cls.gateway_id,
        symbol: cls.symbol,
        order_id: cls.order_id,
        detail: cls.detail,
      };
      return { orders, events: [event, ...s.events].slice(0, MAX_EVENTS) };
    });
  },

  clear: () => set({ orders: {}, events: [], lastSeq: {}, snapshotAt: null }),
}));

/** Count of non-terminal (working) cross-gateway orders — the dashboard KPI. */
export function selectActiveOrderCount(orders: Record<string, AdminOrder>): number {
  let n = 0;
  for (const o of Object.values(orders)) if (!isTerminalStatus(o.status)) n++;
  return n;
}

/** Non-terminal order counts grouped by symbol — the per-symbol dashboard table. */
export function selectOrderCountsBySymbol(
  orders: Record<string, AdminOrder>,
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const o of Object.values(orders)) {
    if (isTerminalStatus(o.status)) continue;
    const sym = typeof o.symbol === "string" ? o.symbol : null;
    if (sym) out[sym] = (out[sym] ?? 0) + 1;
  }
  return out;
}

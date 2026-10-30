import { create } from "zustand";
import {
  classifyMonitorEnvelope,
  isTerminalStatus,
  type MonitorClassification,
} from "@/lib/monitorEvents.js";
import type {
  AdminOrder,
  MonitorEvent,
  MonitorSnapshotData,
  WsEnvelope,
} from "@/types/index.js";

/** Bounded ring for the cross-gateway event log (§15.9). */
const MAX_EVENTS = 1000;

/**
 * Live frames are queued and applied in one store write per interval, so a busy
 * feed costs one React render and one `orders` copy per interval rather than
 * per frame (same idea as `useThrottledBooks`).
 */
export const FLUSH_MS = 250;

/**
 * Cap on the cross-gateway order map. Above it the oldest terminal orders are
 * dropped; working orders are never evicted. An evicted order's lifecycle is
 * still available from the audit trail (`AdminOrderDetailModal`).
 */
export const MAX_ORDERS = 5000;

interface QueuedFrame {
  env: WsEnvelope<unknown>;
  cls: MonitorClassification;
}
let queue: QueuedFrame[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;

function dropQueue(): void {
  queue = [];
  if (flushTimer !== null) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
}

/** Delete the oldest terminal orders (insertion order) until under MAX_ORDERS. In place. */
function evictTerminal(orders: Record<string, AdminOrder>): void {
  let excess = Object.keys(orders).length - MAX_ORDERS;
  for (const id in orders) {
    if (excess <= 0) return;
    if (isTerminalStatus(orders[id]!.status)) {
      delete orders[id];
      excess--;
    }
  }
}

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

  /** Route one admin-monitor frame into the store (live frames are batched; see FLUSH_MS). */
  ingest: (env: WsEnvelope<unknown>) => void;
  /** Apply all queued live frames now, in a single store write. */
  flush: () => void;
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
      get().flush(); // keep ordering: frames received before the snapshot go first
      const data = (env.data ?? {}) as Partial<MonitorSnapshotData>;
      const orders: Record<string, AdminOrder> = {};
      for (const o of data.orders ?? []) {
        if (o && typeof o.order_id === "string") orders[o.order_id] = o;
      }
      evictTerminal(orders);
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

    queue.push({ env, cls });
    if (flushTimer === null) flushTimer = setTimeout(() => get().flush(), FLUSH_MS);
  },

  flush: () => {
    const batch = queue;
    dropQueue();
    if (batch.length === 0) return;

    set((s) => {
      // Copied once per batch (not per frame); only when an order changes.
      let orders = s.orders;
      const fresh: MonitorEvent[] = [];
      for (const { env, cls } of batch) {
        // Fold order lifecycle events into the cross-gateway orders map.
        if (cls.orderStatus && cls.order_id) {
          if (orders === s.orders) orders = { ...s.orders };
          const prev = orders[cls.order_id] ?? {
            order_id: cls.order_id,
            gateway_id: cls.gateway_id ?? "",
            status: cls.orderStatus,
          };
          orders[cls.order_id] = {
            ...prev,
            ...(env.data as Record<string, unknown>),
            order_id: cls.order_id,
            gateway_id: cls.gateway_id ?? prev.gateway_id,
            status: cls.orderStatus,
          };
        }

        fresh.push({
          id: nextId(),
          seq: typeof env.seq === "number" ? env.seq : null,
          ts: typeof env.ts === "string" ? env.ts : new Date().toISOString(),
          kind: cls.kind,
          topic: typeof env.topic === "string" ? env.topic : "",
          gateway_id: cls.gateway_id,
          symbol: cls.symbol,
          order_id: cls.order_id,
          detail: cls.detail,
        });
      }
      if (orders !== s.orders) evictTerminal(orders);
      // Newest first: later frames of the batch go in front.
      return { orders, events: [...fresh.reverse(), ...s.events].slice(0, MAX_EVENTS) };
    });
  },

  clear: () => {
    dropQueue();
    set({ orders: {}, events: [], lastSeq: {}, snapshotAt: null });
  },
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

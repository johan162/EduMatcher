import { create } from "zustand";
import {
  classifyMonitorEnvelope,
  isTerminalStatus,
  type MonitorClassification,
} from "@/lib/monitorEvents.js";
import { getAdminOrders } from "@/api/endpoints.js";
import { SeqTracker } from "@/ws/seqTracker.js";
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

/**
 * Minimum spacing between working-order resyncs. The feed drops events only
 * when the gateway is overloaded, so a resync must not add much load: at most
 * one per interval, however many gaps arrive in it.
 */
export const RESYNC_MIN_MS = 10_000;

/** Non-terminal statuses in the gateway cache; one `GET /admin/orders` each. */
const WORKING_STATUSES = ["NEW", "PARTIAL", "AMENDED"] as const;

interface QueuedFrame {
  env: WsEnvelope<unknown>;
  cls: MonitorClassification;
}
let queue: QueuedFrame[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;

/**
 * Per-topic seq on this feed. A gap means the gateway dropped events for this
 * client (its queue was full); a dropped fill or cancel would otherwise leave
 * that order "working" here until the next reconnect.
 */
const seqTracker = new SeqTracker();
/** Events missed since the last flush, reported as one GAP row. */
let missed = 0;

let resyncTimer: ReturnType<typeof setTimeout> | null = null;
let lastResyncAt = -Infinity;
/** Order ids updated by live frames while a resync fetch is in flight. */
let touchedDuringResync: Set<string> | null = null;

function dropQueue(): void {
  queue = [];
  missed = 0;
  if (flushTimer !== null) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
}

function cancelResync(): void {
  if (resyncTimer !== null) {
    clearTimeout(resyncTimer);
    resyncTimer = null;
  }
  touchedDuringResync = null;
  lastResyncAt = -Infinity;
}

function scheduleFlush(): void {
  if (flushTimer === null)
    flushTimer = setTimeout(() => useMonitorStore.getState().flush(), FLUSH_MS);
}

function requestResync(): void {
  if (resyncTimer !== null) return;
  const wait = Math.max(0, lastResyncAt + RESYNC_MIN_MS - Date.now());
  resyncTimer = setTimeout(() => void runResync(), wait);
}

/**
 * Re-read the gateway's working orders and reconcile them into the map. Not a
 * full snapshot: that carries every cached terminal order too, which under a
 * burst is far larger than the working set and would land on a gateway that
 * is already behind.
 */
async function runResync(): Promise<void> {
  resyncTimer = null;
  lastResyncAt = Date.now();
  // Frames already queued predate the fetch; apply them now so they are not
  // mistaken for updates newer than the gateway's answer.
  useMonitorStore.getState().flush();
  const touched = new Set<string>();
  touchedDuringResync = touched;
  try {
    const pages = await Promise.all(WORKING_STATUSES.map((status) => getAdminOrders({ status })));
    // A clear() or snapshot while in flight supersedes this answer.
    if (touchedDuringResync !== touched) return;
    useMonitorStore.getState().reconcileWorking(
      pages.flatMap((p) => p.orders),
      touched,
    );
  } catch {
    // Best effort: the next gap asks again.
  } finally {
    if (touchedDuringResync === touched) touchedDuringResync = null;
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
  /**
   * Replace working-order state with the gateway's `working` set: a local
   * working order absent from it finished while its event was dropped, and
   * is removed. Orders in `touched` changed live during the fetch, so the
   * live state is newer and is kept.
   */
  reconcileWorking: (working: AdminOrder[], touched: ReadonlySet<string>) => void;
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
      // A new connection: seq baselines restart and the snapshot is complete,
      // so any resync still pending or in flight is moot.
      seqTracker.reset();
      cancelResync();
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

    // Every frame counts toward gap detection, log-worthy or not.
    const gap = seqTracker.observe(
      typeof env.topic === "string" ? env.topic : "",
      typeof env.seq === "number" ? env.seq : undefined,
    );
    if (gap) {
      missed += gap.missed;
      scheduleFlush();
      requestResync();
    }

    const cls = classifyMonitorEnvelope(env);
    if (!cls) return; // not a log-worthy frame

    queue.push({ env, cls });
    scheduleFlush();
  },

  flush: () => {
    const batch = queue;
    const lost = missed;
    dropQueue();
    if (batch.length === 0 && lost === 0) return;

    set((s) => {
      // Copied once per batch (not per frame); only when an order changes.
      let orders = s.orders;
      const fresh: MonitorEvent[] = [];
      for (const { env, cls } of batch) {
        // Fold order lifecycle events into the cross-gateway orders map.
        if (cls.orderStatus && cls.order_id) {
          touchedDuringResync?.add(cls.order_id);
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
      // The loss happened before the frame that revealed it, so the GAP row
      // sits behind this batch.
      const gapRow: MonitorEvent[] =
        lost > 0
          ? [
              {
                id: nextId(),
                seq: null,
                ts: new Date().toISOString(),
                kind: "GAP",
                topic: "",
                gateway_id: null,
                symbol: null,
                order_id: null,
                detail: `${lost} event${lost === 1 ? "" : "s"} dropped by the gateway (feed overloaded) — resyncing working orders.`,
              },
            ]
          : [];
      // Newest first: later frames of the batch go in front.
      return { orders, events: [...fresh.reverse(), ...gapRow, ...s.events].slice(0, MAX_EVENTS) };
    });
  },

  reconcileWorking: (working, touched) => {
    get().flush(); // apply live frames first, so `touched` is complete
    set((s) => {
      const orders = { ...s.orders };
      const live = new Map(working.map((o) => [o.order_id, o]));
      for (const id in orders) {
        if (!isTerminalStatus(orders[id]!.status) && !live.has(id) && !touched.has(id)) {
          delete orders[id];
        }
      }
      for (const [id, o] of live) if (!touched.has(id)) orders[id] = o;
      evictTerminal(orders);
      return { orders };
    });
  },

  clear: () => {
    dropQueue();
    seqTracker.reset();
    cancelResync();
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

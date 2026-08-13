import { create } from "zustand";
import { normalizeOrder } from "@/types/index.js";
import type {
  Order,
  OrderStatus,
  RawOrder,
  OrderAckData,
  Fill,
  OrderAmendedData,
  OrderTerminalData,
} from "@/types/index.js";

/**
 * Live order model for the Active Orders Blotter (§13.1) and the compact
 * Workspace blotter (§11.2).
 *
 * Single source of truth, keyed on `order_id`. It is seeded by the `/events`
 * `orders.snapshot` (sent on every connect, so no `GET /orders` round-trip is
 * needed) and kept current by folding live `order.*` events — mirroring the
 * gateway's own `SessionCaches.apply` status transitions so the client agrees
 * with the server without polling. `hydrate` merges a `GET /orders` reconcile
 * without resurrecting orders already terminal locally.
 *
 * Terminal orders (FILLED/CANCELLED/REJECTED/EXPIRED) are kept so their pill
 * shows briefly; a fresh snapshot on reconnect drops the ones the gateway has
 * since evicted.
 */

const TERMINAL: ReadonlySet<OrderStatus> = new Set<OrderStatus>([
  "FILLED",
  "CANCELLED",
  "REJECTED",
  "EXPIRED",
]);

export function isTerminal(status: OrderStatus): boolean {
  return TERMINAL.has(status);
}

interface OrderStore {
  orders: Record<string, Order>;
  /** Unix ms of the last snapshot/hydrate, for a "reconciled at" stamp. */
  syncedAt: number | null;
  /** Replace the working set from an `orders.snapshot` (authoritative baseline). */
  seed: (rows: RawOrder[]) => void;
  /** Merge a `GET /orders` reconcile: upsert rows, never resurrect terminals. */
  hydrate: (rows: RawOrder[]) => void;
  applyAck: (d: OrderAckData) => void;
  applyFill: (d: Fill) => void;
  applyAmended: (d: OrderAmendedData) => void;
  applyCancelled: (d: OrderTerminalData) => void;
  applyExpired: (d: OrderTerminalData) => void;
  clear: () => void;
}

const nowIso = () => new Date().toISOString();

/** A canonical Order with defaults, for upserting an event onto an unseen id. */
function blank(orderId: string): Order {
  return normalizeOrder({ order_id: orderId });
}

/** Optional order-detail fields an ack/fill may carry → a canonical patch. */
function detailPatch(d: OrderAckData | Fill): Partial<Order> {
  const p: Partial<Order> = {};
  if (d.symbol != null) p.symbol = d.symbol;
  if (d.side != null) p.side = d.side;
  if (d.order_type != null) p.order_type = d.order_type;
  if (d.tif != null) p.tif = d.tif;
  if (d.qty != null) p.quantity = d.qty;
  if (d.price != null) p.price = d.price;
  if (d.client_tag != null) p.client_order_id = d.client_tag;
  if (d.oco_group_id != null) p.oco_group_id = d.oco_group_id;
  if (d.combo_parent_id != null) p.combo_parent_id = d.combo_parent_id;
  return p;
}

export const useOrderStore = create<OrderStore>((set) => {
  /** Upsert one order by merging a patch over the existing (or a blank) row. */
  const upsert = (
    state: OrderStore,
    orderId: string,
    patch: Partial<Order>,
  ): Record<string, Order> => {
    const prev = state.orders[orderId] ?? blank(orderId);
    return {
      ...state.orders,
      [orderId]: { ...prev, ...patch, order_id: orderId, updated_at: nowIso() },
    };
  };

  return {
    orders: {},
    syncedAt: null,

    seed: (rows) =>
      set(() => {
        const orders: Record<string, Order> = {};
        for (const raw of rows) {
          const o = normalizeOrder(raw);
          if (o.order_id) orders[o.order_id] = o;
        }
        return { orders, syncedAt: Date.now() };
      }),

    hydrate: (rows) =>
      set((state) => {
        const orders = { ...state.orders };
        for (const raw of rows) {
          const o = normalizeOrder(raw);
          if (!o.order_id) continue;
          const existing = orders[o.order_id];
          // Don't let a stale REST row resurrect an order we already saw go
          // terminal via the live stream.
          if (existing && isTerminal(existing.status) && !isTerminal(o.status)) continue;
          orders[o.order_id] = o;
        }
        return { orders, syncedAt: Date.now() };
      }),

    applyAck: (d) =>
      set((state) => {
        if (!d.order_id) return state;
        const patch = detailPatch(d);
        patch.status = d.accepted ? "NEW" : "REJECTED";
        // An accepted new order rests with its full quantity remaining.
        if (d.accepted) {
          const prev = state.orders[d.order_id];
          patch.remaining_qty = patch.quantity ?? prev?.remaining_qty ?? prev?.quantity ?? 0;
        }
        return { orders: upsert(state, d.order_id, patch) };
      }),

    applyFill: (d) =>
      set((state) => {
        if (!d.order_id) return state;
        const patch = detailPatch(d);
        patch.remaining_qty = d.remaining_qty;
        patch.status = (d.status as OrderStatus) ?? "PARTIAL";
        // A fill's `qty` is the order's *original* total; if we already know a
        // quantity (e.g. an amend reduced it), the fill must not resurrect the
        // stale total — it only moves remaining/status.
        const prev = state.orders[d.order_id];
        if (prev && prev.quantity > 0) delete patch.quantity;
        return { orders: upsert(state, d.order_id, patch) };
      }),

    applyAmended: (d) =>
      set((state) => {
        if (!d.order_id) return state;
        // Amend carries no symbol/side — it only updates an existing row.
        const patch: Partial<Order> = {
          quantity: d.qty,
          remaining_qty: d.remaining_qty,
          price: d.price ?? null,
          status: d.remaining_qty < d.qty ? "PARTIAL" : "NEW",
        };
        return { orders: upsert(state, d.order_id, patch) };
      }),

    applyCancelled: (d) =>
      set((state) =>
        d.order_id ? { orders: upsert(state, d.order_id, { status: "CANCELLED" }) } : state,
      ),

    applyExpired: (d) =>
      set((state) =>
        d.order_id ? { orders: upsert(state, d.order_id, { status: "EXPIRED" }) } : state,
      ),

    clear: () => set({ orders: {}, syncedAt: null }),
  };
});

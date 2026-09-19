import { toast } from "sonner";
import { useWsEvent } from "@/hooks/useWsEvent.js";
import { useNotificationStore } from "@/store/useNotificationStore.js";
import { useOrderStore } from "@/store/useOrderStore.js";

/**
 * Bridge live private order lifecycle events (`/events`) into the Event Center
 * (§20) and Sonner toasts. Mounted once at the app root for TRADER/MARKET_MAKER.
 *
 * The synchronous accepted/rejected verdict for a NEW order is handled by the
 * ticket itself via `?wait=ack` (§12.9), so this bridge deliberately skips
 * the *first* `order.ack` for a new order to avoid duplicating that toast.
 * `?wait=ack` resolves on the first `order.ack` matching the order_id
 * (`_await_order_event`, gateway `routers/orders.py`) with no filter on
 * `accepted` — so for FOK/MARKET/IOC, whose book can reject or discard the
 * order in a *second* ack/cancel after the first accepted=true ack the
 * ticket already consumed, that terminal outcome reaches no one (M2). This
 * bridge is where it's surfaced: a request_tag-less reject ack for an order
 * the store already has resting (i.e. not the first ack) is that second,
 * authoritative FOK verdict, and a cancel that never had a fill is the
 * MARKET/IOC "book ran out" case, `cancel_reason: INSUFFICIENT_LIQUIDITY`
 * on the wire.
 *
 * A rejected cancel or amend has no synchronous surface either —
 * `DELETE /orders/{id}?wait=ack` only waits on `order.cancelled`, so it
 * times out rather than reporting the reject (C1) — so this bridge is also
 * the only place a trader learns their cancel/amend failed. Correlated by
 * `request_tag`, which every cancel/amend request already carries
 * (queries/index.ts `newOrderRequestTag`) and which is exactly the signal
 * `useOrderStore.applyAck` uses to tell a cancel/amend reject apart from a
 * new-order reject.
 */
export function useOrderEventNotifications(): void {
  const push = useNotificationStore((s) => s.push);

  useWsEvent("order.ack", (env) => {
    const d = env.data;
    if (d.accepted) return;
    if (d.request_tag != null) {
      const id8 = d.order_id.slice(0, 8);
      toast.error(`Order ${id8} not amended/cancelled: ${d.reason || "rejected"}`);
      push({
        ts: Date.now(),
        kind: "REJECT",
        title: `Order ${id8} — cancel/amend rejected`,
        detail: d.reason || "rejected",
        orderId: d.order_id,
      });
      return;
    }
    // request_tag == null: either the first ack of a rejected new order
    // (the ticket's own ?wait=ack already reported this — skip it here) or
    // FOK's second, authoritative kill ack for an order already resting
    // (M2 — the ticket's wait resolved on the *first* ack and never sees
    // this one). The store already has the order iff a prior accepted ack
    // applied, which is exactly the distinction between the two.
    if (!useOrderStore.getState().orders[d.order_id]) return;
    const id8 = d.order_id.slice(0, 8);
    toast.error(`Order ${id8} killed: ${d.reason || "rejected"}`);
    push({
      ts: Date.now(),
      kind: "REJECT",
      title: `Order ${id8} — killed`,
      detail: d.reason || "rejected",
      orderId: d.order_id,
    });
  });

  useWsEvent("order.fill", (env) => {
    const d = env.data;
    const label = `${d.side ?? ""} ${d.symbol ?? ""}`.trim();
    const detail = `${d.fill_qty} @ ${d.fill_price} · ${d.remaining_qty} left`;
    toast.success(`${label || "Order"} filled: ${detail}`);
    push({
      ts: Date.now(),
      kind: "FILL",
      title: `${label || "Order"} filled`,
      detail: `${detail} · ${d.status}`,
      orderId: d.order_id,
    });
  });

  useWsEvent("order.cancelled", (env) => {
    const d = env.data;
    const id8 = d.order_id.slice(0, 8);
    // M2: a cancel with zero fills is the engine's own terminal verdict on
    // an order it discarded rather than a trader-requested cancel (which
    // carries no cancel_reason) -- most commonly a MARKET/IOC remainder the
    // book couldn't fill. remaining_qty === quantity on the store's row
    // means no fill ever touched it; the row is read before pruneTerminal
    // replaces it below, so it still reflects the pre-cancel quantities.
    const order = useOrderStore.getState().orders[d.order_id];
    const isUnfilledKill = d.cancel_reason != null && order?.remaining_qty === order?.quantity;
    if (isUnfilledKill) {
      toast.error(`Order ${id8} killed: no fill (${d.cancel_reason})`);
    }
    push({
      ts: Date.now(),
      kind: "CANCEL",
      title: `Order ${id8} cancelled`,
      detail: `order ${id8}`,
      orderId: d.order_id,
    });
  });

  useWsEvent("order.expired", (env) => {
    const id8 = env.data.order_id.slice(0, 8);
    push({
      ts: Date.now(),
      kind: "CANCEL",
      title: `Order ${id8} expired`,
      detail: `order ${id8}`,
      orderId: env.data.order_id,
    });
  });

  // OCO / combo group lifecycle (§13.3, §17.2.2). The member orders update in
  // the blotter from their own order.* events; these entries record the group
  // outcome — most usefully the sibling auto-cancel when one OCO leg fills.
  useWsEvent("oco.ack", (env) => {
    const d = env.data;
    if (d.accepted) return; // an accepted OCO is unremarkable; only flag rejections
    toast.error(`OCO ${d.oco_id} rejected: ${d.reason || "rejected"}`);
    push({
      ts: Date.now(),
      kind: "REJECT",
      title: `OCO ${d.oco_id} rejected`,
      detail: d.reason || "rejected",
    });
  });

  useWsEvent("oco.cancelled", (env) => {
    const d = env.data;
    push({
      ts: Date.now(),
      kind: "CANCEL",
      title: `OCO ${d.oco_id} — leg cancelled`,
      detail: `order ${d.cancelled_order_id.slice(0, 8)}${d.reason ? ` · ${d.reason}` : ""}`,
      orderId: d.cancelled_order_id,
    });
  });

  useWsEvent("combo.ack", (env) => {
    const d = env.data;
    if (d.accepted) return;
    toast.error(`Combo ${d.combo_id} rejected: ${d.reason || "rejected"}`);
    push({
      ts: Date.now(),
      kind: "REJECT",
      title: `Combo ${d.combo_id} rejected`,
      detail: d.reason || "rejected",
    });
  });

  useWsEvent("combo.status", (env) => {
    const d = env.data;
    push({
      ts: Date.now(),
      kind: "SYSTEM",
      title: `Combo ${d.combo_id} · ${d.status}`,
      detail: d.reason || d.status,
    });
  });
}

import { toast } from "sonner";
import { useWsEvent } from "@/hooks/useWsEvent.js";
import { useNotificationStore } from "@/store/useNotificationStore.js";

/**
 * Bridge live private order lifecycle events (`/events`) into the Event Center
 * (§20) and Sonner toasts. Mounted once at the app root for TRADER/MARKET_MAKER.
 *
 * The synchronous accepted/rejected verdict for a NEW order is handled by the
 * ticket itself via `?wait=ack` (§12.9), so this bridge deliberately skips an
 * accepted `order.ack` to avoid duplicating it. A rejected cancel or amend has
 * no such synchronous surface — `DELETE /orders/{id}?wait=ack` only waits on
 * `order.cancelled`, so it times out rather than reporting the reject (C1) —
 * so this bridge is the only place a trader learns their cancel/amend failed.
 * Correlated by `request_tag`, which every cancel/amend request already
 * carries (queries/index.ts `newOrderRequestTag`) and which is exactly the
 * signal `useOrderStore.applyAck` uses to tell a cancel/amend reject apart
 * from a new-order reject.
 */
export function useOrderEventNotifications(): void {
  const push = useNotificationStore((s) => s.push);

  useWsEvent("order.ack", (env) => {
    const d = env.data;
    if (d.accepted || d.request_tag == null) return; // new-order rejects: handled by the ticket's own ?wait=ack
    const id8 = d.order_id.slice(0, 8);
    toast.error(`Order ${id8} not amended/cancelled: ${d.reason || "rejected"}`);
    push({
      ts: Date.now(),
      kind: "REJECT",
      title: `Order ${id8} — cancel/amend rejected`,
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
    const id8 = env.data.order_id.slice(0, 8);
    push({
      ts: Date.now(),
      kind: "CANCEL",
      title: `Order ${id8} cancelled`,
      detail: `order ${id8}`,
      orderId: env.data.order_id,
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

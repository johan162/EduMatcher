import { toast } from "sonner";
import { useWsEvent } from "@/hooks/useWsEvent.js";
import { useNotificationStore } from "@/store/useNotificationStore.js";

/**
 * Bridge live private order lifecycle events (`/events`) into the Event Center
 * (§20) and Sonner toasts. Mounted once at the app root for TRADER/MARKET_MAKER.
 *
 * The synchronous accepted/rejected verdict is handled by the ticket itself via
 * `?wait=ack` (§12.9), so this bridge deliberately covers only the *later*
 * outcomes — fills and terminals — to avoid duplicating the ACK the ticket
 * already surfaced. The blotter (phase 7) will additionally consume these.
 */
export function useOrderEventNotifications(): void {
  const push = useNotificationStore((s) => s.push);

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
}

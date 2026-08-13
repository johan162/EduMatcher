import { useEffect } from "react";
import { useWsEvent } from "@/hooks/useWsEvent.js";
import { useOrderStore } from "@/store/useOrderStore.js";
import { useAuthStore } from "@/store/useAuthStore.js";

/**
 * Feeds the live {@link useOrderStore} from the private `/events` stream: the
 * `orders.snapshot` seeds the working set on (re)connect, and each `order.*`
 * event is folded in. Mounted once at the app root for TRADER/MM (inert for
 * ADMIN, which receives no private order events). The blotter just reads the
 * store; it never has to call `GET /orders` to stay current (§13.1).
 */
export function useOrderStream(): void {
  useWsEvent("orders.snapshot", (env) => useOrderStore.getState().seed(env.data.orders));
  useWsEvent("order.ack", (env) => useOrderStore.getState().applyAck(env.data));
  useWsEvent("order.fill", (env) => useOrderStore.getState().applyFill(env.data));
  useWsEvent("order.amended", (env) => useOrderStore.getState().applyAmended(env.data));
  useWsEvent("order.cancelled", (env) => useOrderStore.getState().applyCancelled(env.data));
  useWsEvent("order.expired", (env) => useOrderStore.getState().applyExpired(env.data));

  // Drop the working set on logout so the next login starts clean.
  const apiKey = useAuthStore((s) => s.apiKey);
  useEffect(() => {
    if (!apiKey) useOrderStore.getState().clear();
  }, [apiKey]);
}

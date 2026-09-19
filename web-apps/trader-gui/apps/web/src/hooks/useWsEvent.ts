import { useEffect } from "react";
import { wsOn } from "@/ws/WebSocketManager.js";
import { useEventCallback } from "@/hooks/useEventCallback.js";
import type { WsEnvelope, WsDataByType, WsEventType } from "@/types/index.js";

/**
 * Subscribe to a typed WebSocket event type inside a React component.
 *
 * L6: the subscribe effect deliberately depends on `[type]` only, so it does
 * not resubscribe (and every caller passes a fresh inline arrow function each
 * render, which would otherwise mean resubscribing on every render). That
 * means the plain `handler` argument would get frozen as of mount -- a stale
 * closure for any handler that isn't already safe some other way (reading
 * stores via getState, stable setters, or remounting by key, as every
 * current caller happens to do). Routed through `useEventCallback` so the
 * function `wsOn` holds is stable while always running the latest closure.
 */
export function useWsEvent<T extends WsEventType>(
  type: T,
  handler: (env: WsEnvelope<WsDataByType[T]>) => void,
): void {
  const stableHandler = useEventCallback(handler);
  useEffect(() => {
    const off = wsOn(type, stableHandler as (env: WsEnvelope<unknown>) => void);
    return off;
  }, [type, stableHandler]);
}

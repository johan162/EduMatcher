import { useEffect } from "react";
import { wsOn } from "@/ws/WebSocketManager.js";
import type { WsEnvelope, WsDataByType, WsEventType } from "@/types/index.js";

/**
 * Subscribe to a typed WebSocket event type inside a React component.
 * The handler is stable-ref by convention — wrap in useCallback if needed.
 *
 * Example:
 *   useWsEvent("order.fill", (env) => { ... env.data ... });
 */
export function useWsEvent<T extends WsEventType>(
  type: T,
  handler: (env: WsEnvelope<WsDataByType[T]>) => void,
): void {
  useEffect(() => {
    const off = wsOn(type, handler as (env: WsEnvelope<unknown>) => void);
    return off;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type]);
}

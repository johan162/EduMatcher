import { useState, useEffect } from "react";
import {
  getConnectionHealth,
  onHealthChange,
  type ConnectionHealthSnapshot,
} from "@/ws/WebSocketManager.js";

export type ConnectionHealth = ConnectionHealthSnapshot;

/**
 * Reactive view over WebSocketManager's connection health (§17.5).
 * Re-renders when any socket changes state.
 */
export function useConnectionHealth(): ConnectionHealth {
  const [health, setHealth] = useState<ConnectionHealth>(getConnectionHealth);

  useEffect(() => {
    const off = onHealthChange(() => setHealth(getConnectionHealth()));
    // A status change between the initial render and this subscription would
    // otherwise be missed, leaving the dot stale until the next transition.
    setHealth(getConnectionHealth());
    return off;
  }, []);

  return health;
}

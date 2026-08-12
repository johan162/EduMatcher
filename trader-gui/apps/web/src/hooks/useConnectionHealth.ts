import { useState, useEffect } from "react";
import { getConnectionHealth, onHealthChange, type HealthStatus } from "@/ws/WebSocketManager.js";

export interface ConnectionHealth {
  events: HealthStatus;
  marketData: HealthStatus;
  adminMonitor: HealthStatus | null;
  overall: HealthStatus;
}

/**
 * Reactive view over WebSocketManager's connection health.
 * Re-renders when any socket changes state.
 */
export function useConnectionHealth(): ConnectionHealth {
  const [health, setHealth] = useState<ConnectionHealth>(getConnectionHealth);

  useEffect(() => {
    const off = onHealthChange(() => setHealth(getConnectionHealth()));
    return off;
  }, []);

  return health;
}

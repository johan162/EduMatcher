import { WifiOff, Activity } from "lucide-react";
import { useConnectionHealth } from "@/hooks/useConnectionHealth.js";

/**
 * A thin status banner under the top bar shown whenever the live connection is
 * not fully healthy (§23 phase 16 — "graceful degradation when the engine is
 * stopped"). It makes a stalled gateway/engine visible app-wide rather than
 * leaving screens silently stale; REST panels still show their own 503 notes.
 */
export function ConnectionBanner() {
  const health = useConnectionHealth();
  if (health.overall === "connected") return null;

  const reconnecting = health.overall === "reconnecting";
  const Icon = reconnecting ? Activity : WifiOff;

  return (
    <div
      role="status"
      className={`flex items-center justify-center gap-2 px-4 py-1 text-[11px] ${
        reconnecting ? "bg-amber-500/15 text-amber-300" : "bg-red-500/15 text-red-300"
      }`}
    >
      <Icon size={12} />
      {reconnecting ? (
        <span>Reconnecting to the exchange… live data is paused.</span>
      ) : (
        <span>
          Disconnected from the exchange — is pm-api-gwy / the engine running? Live prices and events
          are stale until the connection returns.
        </span>
      )}
    </div>
  );
}

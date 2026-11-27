/**
 * Whether the API gateway is answering, as the last request found it.
 *
 * `apiFetch` updates it on every request: `online` when any HTTP response
 * came back (an error status is still an answer), `offline` when the request
 * never reached the gateway. The top bar shows it, so an unreachable gateway
 * is visible even on a screen that is not refreshing.
 */
import { create } from "zustand";

export type ConnectionState = "unknown" | "online" | "offline";

interface ConnectionStore {
  state: ConnectionState;
  /** `Date.now()` of the last answered request. */
  lastOkAt: number | null;
}

export const useConnectionStore = create<ConnectionStore>(() => ({
  state: "unknown",
  lastOkAt: null,
}));

export function markOnline(): void {
  useConnectionStore.setState({ state: "online", lastOkAt: Date.now() });
}

export function markOffline(): void {
  useConnectionStore.setState({ state: "offline" });
}

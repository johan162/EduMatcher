/**
 * Hydrate the Zustand stores from a `GET /bootstrap/{role}` payload (§7.2).
 *
 * One round-trip replaces the symbols/session/positions/orders waterfall at
 * login, and — the part Phase 2 needs — it is where the session phase and the
 * venue calendar come from. Without it the top bar shows CLOSED with no
 * countdown until the first `session` event happens to fire, which for a
 * quiet venue can be the whole trading day.
 *
 * Optional fields arrive as `null` with their name listed in `incomplete`;
 * each is skipped individually rather than failing the login.
 */
import { useSessionStore } from "@/store/useSessionStore.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useHaltStore } from "@/store/useHaltStore.js";
import type { BootstrapAdmin, BootstrapTrader } from "@/types/index.js";

export function hydrateFromBootstrap(payload: BootstrapTrader | BootstrapAdmin): void {
  const reference = payload.reference;
  if (reference?.symbols) {
    useSymbolStore.getState().hydrateFromReference(reference.symbols);
  }
  if (reference?.schedule) {
    useSessionStore.getState().setSchedule(reference.schedule);
  }
  if (payload.session) {
    // No `prev_state` and no `next` on a polled status: the phase is known,
    // the countdown falls back to the configured schedule.
    useSessionStore.getState().setPhase(payload.session.state, null, null);
  }
  const halts = (payload as BootstrapAdmin).halts;
  if (halts?.halted) {
    useHaltStore.getState().setHalts(halts.halted);
  }
}

import { describe, it, expect, beforeEach } from "vitest";
import { hydrateFromBootstrap } from "@/lib/bootstrap";
import { useHaltStore } from "@/store/useHaltStore";
import { useSessionStore } from "@/store/useSessionStore";
import type { BootstrapTrader } from "@/types/index";

// WP-API04 (D6): bootstrap lists are no longer wrapped in their reply's envelope.
const PAYLOAD = {
  ts: "2026-08-29T13:30:05.412+00:00",
  incomplete: [],
  gateway_id: "TRADER01",
  gateway_role: "TRADER",
  session_timezone: "Europe/Stockholm",
  reference: { symbols: [], risk: { default_level: null, levels: [] }, indexes: [], schedule: null, config_version: "v1" },
  session: { state: "CONTINUOUS", sessions_enabled: true, session_timezone: "Europe/Stockholm", session_date: "2026-08-29" },
  positions: [],
  orders: [],
  recent_fills: [],
  halts: [{ symbol: "TSLA", level: "L1", halt_source: "CIRCUIT_BREAKER" }],
  capabilities: { sessions_enabled: true, stats_db_available: true, audit_db_available: false, index_available: false },
} as unknown as BootstrapTrader;

beforeEach(() => {
  useHaltStore.setState({ halts: {} });
});

describe("hydrateFromBootstrap", () => {
  it("loads the halts list as sent (no `halted` envelope)", () => {
    hydrateFromBootstrap(PAYLOAD);
    expect(Object.keys(useHaltStore.getState().halts)).toEqual(["TSLA"]);
    expect(useSessionStore.getState().phase).toBe("CONTINUOUS");
  });

  it("leaves the halts alone when the field timed out (null)", () => {
    hydrateFromBootstrap({ ...PAYLOAD, halts: null } as BootstrapTrader);
    expect(useHaltStore.getState().halts).toEqual({});
  });
});

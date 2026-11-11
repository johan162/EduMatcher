// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen } from "@testing-library/react";
import { POLL_CURRENT_MS, TRADE_PAGE_SIZE } from "@/api/queries";
import { useAuthStore, type Role } from "@/store/useAuthStore";
import { example, renderApp, signIn, stubApi } from "./helpers";

/**
 * CG9 request discipline, screen by screen: left open for a minute, a screen
 * may repeat only the small current-state reads, at no faster than the 5 s
 * clearing flush; history, trades, events, settlement and symbol settings are
 * read once; reconciliation never runs by itself; and no list is requested
 * without a bound.
 */
const C = "/api/v1/clearing";

/** The only routes a screen may request repeatedly. */
const POLLED = new Set([
  `${C}/positions`,
  `${C}/exposure`,
  `${C}/summary`,
  `${C}/participants`,
  `${C}/participants/TRADER01`,
  `${C}/health`,
]);

function api() {
  return stubApi({
    "/api/v1/symbols": example("/api/v1/symbols"),
    [`${C}/summary`]: example(`${C}/summary`),
    [`${C}/health`]: example(`${C}/health`),
    [`${C}/participants`]: example(`${C}/participants`),
    [`${C}/participants/TRADER01`]: example(`${C}/participants/{gateway_id}`),
    [`${C}/positions`]: example(`${C}/positions`),
    [`${C}/exposure`]: example(`${C}/exposure`),
    [`${C}/trades`]: example(`${C}/trades`),
    [`${C}/daily`]: example(`${C}/daily`),
    [`${C}/close-snapshots`]: example(`${C}/close-snapshots`),
    [`${C}/symbols`]: example(`${C}/symbols`),
    [`${C}/session-events`]: example(`${C}/session-events`),
    [`${C}/gateway-sessions`]: example(`${C}/gateway-sessions`),
    [`${C}/settlements`]: example(`${C}/settlements`),
    [`${C}/balances`]: example(`${C}/balances`),
    [`${C}/reconciliation`]: example(`${C}/reconciliation`),
  });
}

const SCREENS: [Role, string, string][] = [
  ["ADMIN", "/overview", "Clearing Overview"],
  ["ADMIN", "/participants", "Participants"],
  ["ADMIN", "/participants/TRADER01", "Participant TRADER01"],
  ["ADMIN", "/participants/TRADER01/trades", "Participant TRADER01"],
  ["ADMIN", "/participants/TRADER01/history", "Participant TRADER01"],
  ["ADMIN", "/participants/TRADER01/settlement", "Participant TRADER01"],
  ["ADMIN", "/symbols", "Symbol Activity"],
  ["ADMIN", "/events", "Events"],
  ["ADMIN", "/gateway-sessions", "Gateway Sessions"],
  ["ADMIN", "/reconciliation", "Reconciliation"],
  ["ADMIN", "/eod", "EOD Settlement"],
  ["TRADER", "/me/positions", "My Positions"],
  ["TRADER", "/me/trades", "My Trades"],
  ["TRADER", "/me/history", "Daily & Close History"],
  ["TRADER", "/me/settlement", "EOD Settlement"],
  ["TRADER", "/me/sessions", "Gateway Sessions"],
  ["MARKET_MAKER", "/me/obligations", "My Quote Obligations"],
];

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  useAuthStore.getState().logout();
});

describe.each(SCREENS)("%s %s", (role, path, heading) => {
  it("polls only bounded current state, and nothing faster than the flush", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    signIn(role, role === "ADMIN" ? "OPS01" : role === "MARKET_MAKER" ? "MM01" : "TRADER01");
    const stub = api();
    renderApp(path);
    await screen.findByRole("heading", { name: heading });
    const minute = 60_000;
    await vi.advanceTimersByTimeAsync(minute);

    const counts = new Map<string, number>();
    for (const request of stub.requests) {
      const url = new URL(request, "http://gui.test");
      counts.set(url.pathname, (counts.get(url.pathname) ?? 0) + 1);
      if (url.pathname === `${C}/trades`) {
        expect(Number(url.searchParams.get("limit"))).toBe(TRADE_PAGE_SIZE);
      }
    }
    expect(counts.get(`${C}/reconciliation`) ?? 0).toBe(0);
    for (const [route, n] of counts) {
      if (POLLED.has(route)) {
        // First load + one per POLL_CURRENT_MS at most.
        expect(n, route).toBeLessThanOrEqual(1 + minute / POLL_CURRENT_MS);
      } else {
        expect(n, `${route} was refetched on ${path}`).toBe(1);
      }
    }
  });
});

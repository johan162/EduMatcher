import { describe, it, expect } from "vitest";
import { actionCommandsForRole, filterByLabel } from "@/lib/commandItems";

describe("actionCommandsForRole (§21.1)", () => {
  it("gives TRADER the workspace/orders/positions nav and Flatten All", () => {
    const ids = actionCommandsForRole("TRADER").map((c) => c.id);
    expect(ids).toContain("nav-workspace");
    expect(ids).toContain("nav-orders");
    expect(ids).toContain("nav-positions");
    expect(ids).toContain("act-flatten-all");
    // No admin nav for a trader.
    expect(ids).not.toContain("nav-admin-dashboard");
  });

  it("gives MARKET_MAKER the quote nav + Flatten All, not trader-only screens", () => {
    const ids = actionCommandsForRole("MARKET_MAKER").map((c) => c.id);
    expect(ids).toContain("nav-quotes");
    expect(ids).toContain("act-flatten-all");
    expect(ids).not.toContain("nav-workspace");
  });

  it("gives ADMIN the admin nav and NOT Flatten All", () => {
    const ids = actionCommandsForRole("ADMIN").map((c) => c.id);
    expect(ids).toContain("nav-admin-session");
    expect(ids).toContain("nav-admin-monitor");
    expect(ids).not.toContain("act-flatten-all");
  });

  it("always includes the common actions and market/watchlist nav", () => {
    for (const role of ["TRADER", "MARKET_MAKER", "ADMIN"] as const) {
      const ids = actionCommandsForRole(role).map((c) => c.id);
      expect(ids).toContain("nav-market");
      expect(ids).toContain("nav-watchlist");
      expect(ids).toContain("act-event-center");
      expect(ids).toContain("act-help");
    }
  });
});

describe("filterByLabel", () => {
  const items = [{ label: "Positions" }, { label: "Trade History" }, { label: "Market Overview" }];
  it("returns all for an empty query", () => {
    expect(filterByLabel(items, "")).toHaveLength(3);
  });
  it("matches case-insensitive substrings", () => {
    expect(filterByLabel(items, "hist")).toEqual([{ label: "Trade History" }]);
    expect(filterByLabel(items, "MARKET")).toEqual([{ label: "Market Overview" }]);
  });
});

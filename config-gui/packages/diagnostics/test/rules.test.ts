import { describe, expect, it } from "vitest";
import { createBlankDraft, createGateway, type EngineConfigDraft } from "@edumatcher/schema";
import { evaluateDiagnostics, hasErrors } from "../src/index.js";

function base(): EngineConfigDraft {
  const draft = createBlankDraft();
  draft.symbols = { AAPL: { tickDecimals: 2 }, MSFT: { tickDecimals: 2 } };
  draft.symbolOrder = ["AAPL", "MSFT"];
  draft.gateways = [createGateway("TRADER01"), createGateway("OPS01", "ADMIN")];
  return draft;
}

function ids(draft: EngineConfigDraft): string[] {
  return evaluateDiagnostics(draft).map((d) => d.id);
}

describe("diagnostics rules", () => {
  it("flags an undefined risk level as an error", () => {
    const draft = base();
    draft.symbols.AAPL!.level = "GHOST";
    const diags = evaluateDiagnostics(draft);
    expect(diags.some((d) => d.id === "undefined-risk-level" && d.severity === "error")).toBe(true);
    expect(hasErrors(diags)).toBe(true);
  });

  it("accepts a symbol level that matches a defined level", () => {
    const draft = base();
    draft.riskControls.levels = { CORE: { staticBandPct: 0.18, dynamicBandPct: 0.02 } };
    draft.symbols.AAPL!.level = "CORE";
    expect(ids(draft)).not.toContain("undefined-risk-level");
  });

  it("warns when an MM gateway has no mid-range seeding", () => {
    const draft = base();
    draft.gateways.push(createGateway("MM01", "MARKET_MAKER"));
    expect(ids(draft)).toContain("mm-gateway-needs-quote-seeds");
  });

  it("errors when seed-from-mm is on but no range set", () => {
    const draft = base();
    draft.seeding.seedLastPricesFromMm = true;
    expect(ids(draft)).toContain("seed-last-prices-from-mm-without-range");
  });

  it("detects port collisions across enabled gateways", () => {
    const draft = base();
    draft.postTradeGateway.enabled = true;
    draft.marketDataGateway.enabled = true;
    draft.marketDataGateway.port = draft.postTradeGateway.port;
    expect(ids(draft)).toContain("port-collision");
  });

  it("errors on an out-of-order schedule", () => {
    const draft = base();
    draft.sessionsEnabled = true;
    draft.schedule.continuous = "08:00"; // before opening auction
    expect(ids(draft)).toContain("schedule-out-of-order");
  });

  it("errors on an index with unknown constituents and missing constituents", () => {
    const draft = base();
    draft.indices = [
      { id: "EDU", description: "", constituents: [], baseValue: 1000, publishIntervalSec: 1 },
      { id: "BAD", description: "", constituents: ["GHOST"], baseValue: 1000, publishIntervalSec: 1 },
    ];
    const found = ids(draft);
    expect(found).toContain("index-missing-constituents");
    expect(found).toContain("index-constituent-not-in-universe");
  });

  it("errors on duplicate and unknown combo legs", () => {
    const draft = base();
    draft.combos = [
      {
        comboId: "C1",
        comboType: "AON",
        tif: "DAY",
        legs: [
          { symbol: "AAPL", side: "BUY", orderType: "LIMIT", quantity: 1, smpAction: "NONE" },
          { symbol: "AAPL", side: "SELL", orderType: "LIMIT", quantity: 1, smpAction: "NONE" },
        ],
      },
    ];
    const found = ids(draft);
    expect(found).toContain("combo-duplicate-leg-symbol");
  });

  it("warns on a single gateway and no info noise on a healthy config", () => {
    const draft = base();
    draft.gateways = [createGateway("TRADER01")];
    expect(ids(draft)).toContain("single-gateway");
  });

  it("stays clean for a valid minimal config", () => {
    const draft = base();
    expect(hasErrors(evaluateDiagnostics(draft))).toBe(false);
  });
});

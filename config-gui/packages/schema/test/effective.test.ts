import { describe, expect, it } from "vitest";
import {
  createBlankDraft,
  createGateway,
  createIndex,
  resolveEffectiveSymbol,
  type EngineConfigDraft,
} from "../src/index.js";

function draftWith(symbol = "AAPL"): EngineConfigDraft {
  const d = createBlankDraft();
  d.symbols = { [symbol]: { tickDecimals: 2, lastBuyPrice: 100, lastSellPrice: 100 } };
  d.symbolOrder = [symbol];
  d.gateways = [createGateway("TRADER01")];
  return d;
}

describe("resolveEffectiveSymbol", () => {
  it("returns null for an unknown symbol", () => {
    expect(resolveEffectiveSymbol(draftWith(), "GHOST")).toBeNull();
  });

  it("reports no collar when neither a level nor a symbol collar applies", () => {
    const eff = resolveEffectiveSymbol(draftWith(), "AAPL")!;
    expect(eff.collar.applies).toBe(false);
  });

  it("resolves the global DEFAULT collar and marks the source", () => {
    const d = draftWith();
    d.riskControls.globalStaticBandPct = 0.2;
    d.riskControls.globalDynamicBandPct = 0.02;
    const eff = resolveEffectiveSymbol(d, "AAPL")!;
    expect(eff.level).toBe("DEFAULT");
    expect(eff.levelSource).toBe("default");
    expect(eff.collar.applies).toBe(true);
    expect(eff.collar.staticBandPct).toBeCloseTo(0.2, 6);
    expect(eff.collar.staticSource).toBe("level");
  });

  it("lets a symbol collar override the level and falls back to engine default for the missing side", () => {
    const d = draftWith();
    d.riskControls.levels = { CORE: { staticBandPct: 0.18, dynamicBandPct: 0.03 } };
    d.symbols.AAPL!.level = "CORE";
    d.symbols.AAPL!.collar = { staticBandPct: 0.1 }; // dynamic omitted -> inherit level
    const eff = resolveEffectiveSymbol(d, "AAPL")!;
    expect(eff.collar.staticBandPct).toBeCloseTo(0.1, 6);
    expect(eff.collar.staticSource).toBe("override");
    expect(eff.collar.dynamicBandPct).toBeCloseTo(0.03, 6);
    expect(eff.collar.dynamicSource).toBe("level");
  });

  it("merges per-symbol circuit-breaker overrides field-by-field over the ladder", () => {
    const d = draftWith();
    d.symbols.AAPL!.circuitBreaker = {
      referenceWindowNs: 600_000_000_000,
      levels: { L1: { priceShiftPct: 0.05, resumptionMode: "CONTINUOUS" }, L3: { haltDurationNs: null } },
    };
    const eff = resolveEffectiveSymbol(d, "AAPL")!;
    expect(eff.circuitBreaker.windowOverridden).toBe(true);
    expect(eff.circuitBreaker.referenceWindowNs).toBe(600_000_000_000);
    const l1 = eff.circuitBreaker.levels.find((l) => l.name === "L1")!;
    expect(l1.priceShiftPct).toBeCloseTo(0.05, 6);
    expect(l1.shiftOverridden).toBe(true);
    expect(l1.resumptionMode).toBe("CONTINUOUS");
    // L1 halt not overridden -> inherits the global ladder value.
    expect(l1.haltOverridden).toBe(false);
    const l3 = eff.circuitBreaker.levels.find((l) => l.name === "L3")!;
    expect(l3.haltOverridden).toBe(true);
    expect(l3.haltDurationNs).toBeNull();
  });

  it("resolves MM obligations and surfaces per-gateway overrides", () => {
    const d = draftWith();
    const mm = createGateway("MM01", "MARKET_MAKER");
    mm.mmObligations = { AAPL: { maxSpreadTicks: 6, minQty: 500 } };
    d.gateways.push(mm);
    d.mmObligationDefaults = { enforceMmObligation: true, mmMaxSpreadTicks: 12, mmMinQty: 200 };
    d.symbols.AAPL!.marketMaker = { mmMaxSpreadTicks: 8 };
    const eff = resolveEffectiveSymbol(d, "AAPL")!;
    expect(eff.marketMakerRelevant).toBe(true);
    expect(eff.mmObligation.maxSpreadTicks).toBe(8);
    expect(eff.mmObligation.maxSpreadOverridden).toBe(true);
    expect(eff.mmObligation.minQty).toBe(200); // inherited global
    expect(eff.mmObligation.minQtyOverridden).toBe(false);
    expect(eff.mmObligation.perGatewayOverrides).toEqual([
      { gatewayId: "MM01", maxSpreadTicks: 6, minQty: 500 },
    ]);
  });

  it("shows seeded MM quotes when a mid-range is set and stubs otherwise", () => {
    const d = draftWith();
    d.gateways.push(createGateway("MM01", "MARKET_MAKER"));
    let eff = resolveEffectiveSymbol(d, "AAPL")!;
    expect(eff.mmQuotes[0]!.origin).toBe("stub");
    expect(eff.mmQuotes[0]!.bidPrice).toBeNull();

    d.seeding.mmMidRange = { min: 100, max: 100 };
    eff = resolveEffectiveSymbol(d, "AAPL")!;
    expect(eff.mmQuotes[0]!.origin).toBe("seeded");
    expect(eff.mmQuotes[0]!.bidPrice).toBeCloseTo(99.99, 5);
    expect(eff.mmQuotes[0]!.askPrice).toBeCloseTo(100.01, 5);
  });

  it("prefers explicit quotes over seeding", () => {
    const d = draftWith();
    d.gateways.push(createGateway("MM01", "MARKET_MAKER"));
    d.seeding.mmMidRange = { min: 100, max: 100 };
    d.symbols.AAPL!.marketMakerQuotes = [
      { gatewayId: "MM01", bidPrice: 191.85, askPrice: 191.87, bidQty: 1000, askQty: 1000, tif: "DAY", seedOnce: true },
    ];
    const eff = resolveEffectiveSymbol(d, "AAPL")!;
    expect(eff.mmQuotes).toHaveLength(1);
    expect(eff.mmQuotes[0]!.origin).toBe("explicit");
    expect(eff.mmQuotes[0]!.bidPrice).toBe(191.85);
  });

  it("lists index and combo memberships", () => {
    const d = draftWith();
    d.symbols.MSFT = { tickDecimals: 2, lastBuyPrice: 400, lastSellPrice: 400, outstandingShares: 1 };
    d.symbolOrder.push("MSFT");
    d.symbols.AAPL!.outstandingShares = 1;
    const idx = createIndex("EDU");
    idx.constituents = ["AAPL", "MSFT"];
    d.indices = [idx];
    d.combos = [
      {
        comboId: "PAIR",
        comboType: "AON",
        tif: "DAY",
        legs: [
          { symbol: "AAPL", side: "BUY", orderType: "LIMIT", quantity: 1, smpAction: "NONE" },
          { symbol: "MSFT", side: "SELL", orderType: "LIMIT", quantity: 1, smpAction: "NONE" },
        ],
      },
    ];
    const eff = resolveEffectiveSymbol(d, "AAPL")!;
    expect(eff.indices).toEqual(["EDU"]);
    expect(eff.combos).toEqual(["PAIR"]);
  });
});

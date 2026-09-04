import { describe, expect, it } from "vitest";
import {
  bandPctAt,
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
      levels: { L1: { priceShiftPct: 0.05 }, L3: { haltDurationNs: null } },
    };
    const eff = resolveEffectiveSymbol(d, "AAPL")!;
    expect(eff.circuitBreaker.windowOverridden).toBe(true);
    expect(eff.circuitBreaker.referenceWindowNs).toBe(600_000_000_000);
    const l1 = eff.circuitBreaker.levels.find((l) => l.name === "L1")!;
    expect(l1.priceShiftPct).toBeCloseTo(0.05, 6);
    expect(l1.shiftOverridden).toBe(true);
    // L1 halt not overridden -> inherits the global ladder value.
    expect(l1.haltOverridden).toBe(false);
    const l3 = eff.circuitBreaker.levels.find((l) => l.name === "L3")!;
    expect(l3.haltOverridden).toBe(true);
    expect(l3.haltDurationNs).toBeNull();
  });

  it("resolves ACE per symbol, marking which fields are overridden", () => {
    const d = draftWith();
    d.symbols.AAPL!.circuitBreaker = {
      levels: {},
      reopening: { initialBandPct: 0.03 },
    };
    const eff = resolveEffectiveSymbol(d, "AAPL")!.circuitBreaker.reopening;

    expect(eff.initialBandPct).toBeCloseTo(0.03, 6);
    expect(eff.initialBandOverridden).toBe(true);
    // Untouched fields inherit, and say so.
    expect(eff.enabled).toBe(true);
    expect(eff.enabledOverridden).toBe(false);
    expect(eff.randomEndOverridden).toBe(false);
  });

  it("widens the corridor additively on the reference, not compounding", () => {
    // Nasdaq's published example: a $100 reference gives 90/110, 80/120,
    // 60/140. The GUI preview must agree with the engine or it shows a
    // corridor the exchange will not use.
    const d = draftWith();
    const ace = d.circuitBreakerDefaults.reopening;

    expect([0, 1, 2].map((n) => bandPctAt(ace, n))).toEqual([0.1, 0.2, 0.4]);
  });

  it("repeats the final rung so the corridor never stops widening", () => {
    const d = draftWith();
    const ace = d.circuitBreakerDefaults.reopening;

    // This is why there is no maximum-extensions setting.
    expect(bandPctAt(ace, 5)).toBeGreaterThan(bandPctAt(ace, 4));
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

describe("resolveEffectiveSymbol — order limits", () => {
  it("reports no limits when the symbol caps nothing", () => {
    const eff = resolveEffectiveSymbol(draftWith(), "AAPL")!;
    expect(eff.orderLimits.applies).toBe(false);
    expect(eff.orderLimits.maxOrderQty).toBeUndefined();
  });

  it("resolves the symbol's own caps", () => {
    const d = draftWith();
    d.symbols.AAPL!.orderLimits = { maxOrderQty: 5_000, maxOrderValue: 250_000 };
    const eff = resolveEffectiveSymbol(d, "AAPL")!;
    expect(eff.orderLimits.applies).toBe(true);
    expect(eff.orderLimits.maxOrderQty).toBe(5_000);
    expect(eff.orderLimits.maxOrderValue).toBe(250_000);
  });

  it("treats each cap independently", () => {
    const d = draftWith();
    d.symbols.AAPL!.orderLimits = { maxOrderValue: 250_000 };
    const eff = resolveEffectiveSymbol(d, "AAPL")!;
    expect(eff.orderLimits.applies).toBe(true);
    expect(eff.orderLimits.maxOrderQty).toBeUndefined();
  });

  it("does not inherit caps from the symbol's risk level", () => {
    // Levels carry collars and nothing else; a cap is per symbol or absent.
    const d = draftWith();
    d.riskControls.levels = { CORE: { staticBandPct: 0.18, dynamicBandPct: 0.03 } };
    d.symbols.AAPL!.level = "CORE";
    const eff = resolveEffectiveSymbol(d, "AAPL")!;
    expect(eff.collar.applies).toBe(true);
    expect(eff.orderLimits.applies).toBe(false);
  });
});

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import yaml from "js-yaml";
import {
  createBlankDraft,
  createGateway,
  type EngineConfigDraft,
} from "@edumatcher/schema";
import { buildConfigDocument, generateYaml, parseYamlToDraft } from "../src/index.js";

/** Minimal two-trader exchange (design ref: config-generator §10.2). */
function twoTraderExchange(): EngineConfigDraft {
  const draft = createBlankDraft();
  draft.symbols = { AAPL: { tickDecimals: 2 } };
  draft.symbolOrder = ["AAPL"];
  draft.gateways = [
    createGateway("TRADER01", "TRADER"),
    createGateway("TRADER02", "TRADER"),
  ];
  return draft;
}

describe("buildConfigDocument", () => {
  it("emits mandatory top-level keys in builder.py order", () => {
    const doc = buildConfigDocument(twoTraderExchange());
    const keys = Object.keys(doc);
    expect(keys.slice(0, 4)).toEqual([
      "sessions_enabled",
      "enforce_collars",
      "enforce_circuit_breakers",
      "snapshot_interval_sec",
    ]);
    expect(doc.symbols).toHaveProperty("AAPL");
    expect(doc.gateways).toEqual({
      alf: [
        { id: "TRADER01", role: "TRADER", disconnect_behaviour: "CANCEL_ALL" },
        { id: "TRADER02", role: "TRADER", disconnect_behaviour: "CANCEL_ALL" },
      ],
    });
  });

  it("adds quote_refresh_policy and quote stubs for MARKET_MAKER gateways", () => {
    const draft = twoTraderExchange();
    draft.gateways.push(createGateway("MM01", "MARKET_MAKER"));
    const doc = buildConfigDocument(draft) as any;
    const mm = doc.gateways.alf.find((g: any) => g.id === "MM01");
    expect(mm.quote_refresh_policy).toBe("INACTIVATE_ON_ANY_FILL");
    expect(doc.symbols.AAPL.market_maker_quotes[0]).toMatchObject({
      gateway_id: "MM01",
      bid_price: null,
      ask_price: null,
      bid_qty: 1000,
      seed_once: true,
    });
  });

  it("P1.2/P1.3: emits and round-trips per-gateway MM obligation overrides", () => {
    const draft = twoTraderExchange();
    const mm = createGateway("MM01", "MARKET_MAKER");
    mm.enforceMmObligation = true;
    mm.mmMaxSpreadTicks = 8;
    mm.mmMinQty = 300;
    mm.mmObligations = { AAPL: { enforceMmObligation: true, maxSpreadTicks: 6, minQty: 500 } };
    draft.gateways.push(mm);
    const doc = buildConfigDocument(draft) as any;
    const mmOut = doc.gateways.alf.find((g: any) => g.id === "MM01");
    expect(mmOut.enforce_mm_obligation).toBe(true);
    expect(mmOut.mm_max_spread_ticks).toBe(8);
    expect(mmOut.mm_min_qty).toBe(300);
    // Nested keys use max_spread_ticks / min_qty (no mm_ prefix).
    expect(mmOut.mm_obligations.AAPL).toEqual({
      enforce_mm_obligation: true,
      max_spread_ticks: 6,
      min_qty: 500,
    });
    // Non-overridden gateways carry none of these keys.
    const trader = doc.gateways.alf.find((g: any) => g.id === "TRADER01");
    expect(trader.enforce_mm_obligation).toBeUndefined();
    expect(trader.mm_obligations).toBeUndefined();

    const { draft: reparsed } = parseYamlToDraft(generateYaml(draft));
    const mmBack = reparsed.gateways.find((g) => g.id === "MM01")!;
    expect(mmBack.enforceMmObligation).toBe(true);
    expect(mmBack.mmMaxSpreadTicks).toBe(8);
    expect(mmBack.mmMinQty).toBe(300);
    expect(mmBack.mmObligations!.AAPL).toEqual({
      enforceMmObligation: true,
      maxSpreadTicks: 6,
      minQty: 500,
    });
  });

  it("P1.1: emits and round-trips a non-default quote_refresh_policy for MM gateways", () => {
    const draft = twoTraderExchange();
    const mm = createGateway("MM01", "MARKET_MAKER");
    mm.quoteRefreshPolicy = "NEVER_INACTIVATE";
    draft.gateways.push(mm);
    const doc = buildConfigDocument(draft) as any;
    const mmOut = doc.gateways.alf.find((g: any) => g.id === "MM01");
    expect(mmOut.quote_refresh_policy).toBe("NEVER_INACTIVATE");
    // Non-MM gateways never carry the field.
    const trader = doc.gateways.alf.find((g: any) => g.id === "TRADER01");
    expect(trader.quote_refresh_policy).toBeUndefined();

    const { draft: reparsed } = parseYamlToDraft(generateYaml(draft));
    expect(reparsed.gateways.find((g) => g.id === "MM01")!.quoteRefreshPolicy).toBe(
      "NEVER_INACTIVATE",
    );
  });

  it("seeds bid/ask around the mid-range when configured", () => {
    const draft = twoTraderExchange();
    draft.gateways.push(createGateway("MM01", "MARKET_MAKER"));
    draft.seeding.mmMidRange = { min: 100, max: 100 };
    draft.seeding.seedLastPricesFromMm = true;
    const doc = buildConfigDocument(draft) as any;
    const quote = doc.symbols.AAPL.market_maker_quotes[0];
    expect(quote.bid_price).toBeCloseTo(99.99, 5);
    expect(quote.ask_price).toBeCloseTo(100.01, 5);
    expect(doc.symbols.AAPL.last_buy_price).toBeCloseTo(100, 5);
  });

  it("emits explicit last prices in preference to global seeding", () => {
    const draft = twoTraderExchange();
    draft.symbols.AAPL = { tickDecimals: 2, lastBuyPrice: 191.86, lastSellPrice: 191.87 };
    draft.seeding.seedLastPrices = true; // would emit nulls if no explicit prices
    const doc = buildConfigDocument(draft) as any;
    expect(doc.symbols.AAPL.last_buy_price).toBe(191.86);
    expect(doc.symbols.AAPL.last_sell_price).toBe(191.87);
  });

  it("emits explicit multi-MM quotes in preference to auto-generated stubs", () => {
    const draft = twoTraderExchange();
    draft.gateways.push(createGateway("MM01", "MARKET_MAKER"));
    draft.gateways.push(createGateway("MM02", "MARKET_MAKER"));
    draft.symbols.AAPL = {
      tickDecimals: 2,
      lastBuyPrice: 191.86,
      lastSellPrice: 191.87,
      marketMakerQuotes: [
        { gatewayId: "MM01", bidPrice: 191.85, askPrice: 191.87, bidQty: 1000, askQty: 1000, tif: "DAY", seedOnce: true },
        { gatewayId: "MM02", bidPrice: 191.84, askPrice: 191.88, bidQty: 500, askQty: 500, tif: "DAY", seedOnce: false },
      ],
    };
    const doc = buildConfigDocument(draft) as any;
    const quotes = doc.symbols.AAPL.market_maker_quotes;
    expect(quotes).toHaveLength(2);
    expect(quotes[0]).toMatchObject({ gateway_id: "MM01", bid_price: 191.85, ask_price: 191.87 });
    expect(quotes[1]).toMatchObject({ gateway_id: "MM02", bid_qty: 500, seed_once: false });
  });

  it("round-trips explicit MM quotes through parse", () => {
    const draft = twoTraderExchange();
    draft.gateways.push(createGateway("MM01", "MARKET_MAKER"));
    draft.symbols.AAPL = {
      tickDecimals: 2,
      lastBuyPrice: 191.86,
      lastSellPrice: 191.87,
      marketMakerQuotes: [
        { gatewayId: "MM01", bidPrice: 191.85, askPrice: 191.87, bidQty: 1000, askQty: 1000, tif: "DAY", seedOnce: true },
      ],
    };
    const text = generateYaml(draft);
    const { draft: reparsed } = parseYamlToDraft(text);
    const quotes = reparsed.symbols.AAPL!.marketMakerQuotes;
    expect(quotes).toHaveLength(1);
    expect(quotes![0]).toMatchObject({ gatewayId: "MM01", bidPrice: 191.85, askPrice: 191.87, bidQty: 1000 });
  });

  it("P1.4: emits and round-trips a per-symbol circuit_breaker.reference_window_ns", () => {
    const draft = twoTraderExchange();
    draft.symbols.AAPL = {
      tickDecimals: 2,
      lastBuyPrice: 100,
      lastSellPrice: 100,
      circuitBreaker: { referenceWindowNs: 600_000_000_000, levels: {} },
    };
    const doc = buildConfigDocument(draft) as any;
    expect(doc.symbols.AAPL.circuit_breaker.reference_window_ns).toBe(600_000_000_000);
    // No levels emitted when only the window is overridden.
    expect(doc.symbols.AAPL.circuit_breaker.levels).toBeUndefined();

    const { draft: reparsed } = parseYamlToDraft(generateYaml(draft));
    expect(reparsed.symbols.AAPL!.circuitBreaker!.referenceWindowNs).toBe(600_000_000_000);
  });

  it("P1.4: window override coexists with per-level shift overrides", () => {
    const draft = twoTraderExchange();
    draft.symbols.AAPL = {
      tickDecimals: 2,
      lastBuyPrice: 100,
      lastSellPrice: 100,
      circuitBreaker: { referenceWindowNs: 120_000_000_000, levels: { L1: { priceShiftPct: 0.05 } } },
    };
    const doc = buildConfigDocument(draft) as any;
    expect(doc.symbols.AAPL.circuit_breaker.reference_window_ns).toBe(120_000_000_000);
    expect(doc.symbols.AAPL.circuit_breaker.levels.L1.price_shift_pct).toBe(0.05);
    const { draft: reparsed } = parseYamlToDraft(generateYaml(draft));
    expect(reparsed.symbols.AAPL!.circuitBreaker!.referenceWindowNs).toBe(120_000_000_000);
    expect(reparsed.symbols.AAPL!.circuitBreaker!.levels.L1!.priceShiftPct).toBe(0.05);
  });

  it("emits and round-trips per-symbol CB halt (cool-off) and resumption overrides", () => {
    const draft = twoTraderExchange();
    draft.symbols.AAPL = {
      tickDecimals: 2,
      lastBuyPrice: 100,
      lastSellPrice: 100,
      circuitBreaker: {
        levels: {
          L1: { haltDurationNs: 120_000_000_000, resumptionMode: "CONTINUOUS" },
          L3: { haltDurationNs: null }, // rest-of-day override
        },
      },
    };
    const doc = buildConfigDocument(draft) as any;
    expect(doc.symbols.AAPL.circuit_breaker.levels.L1).toEqual({
      halt_duration_ns: 120_000_000_000,
      resumption_mode: "CONTINUOUS",
    });
    expect(doc.symbols.AAPL.circuit_breaker.levels.L3).toEqual({ halt_duration_ns: null });

    const { draft: reparsed } = parseYamlToDraft(generateYaml(draft));
    const cb = reparsed.symbols.AAPL!.circuitBreaker!;
    expect(cb.levels.L1).toEqual({ haltDurationNs: 120_000_000_000, resumptionMode: "CONTINUOUS" });
    expect(cb.levels.L3!.haltDurationNs).toBeNull();
  });

  it("converts combo leg decimal prices to ticks using tick_decimals", () => {
    const draft = twoTraderExchange();
    draft.combos = [
      {
        comboId: "C1",
        comboType: "AON",
        tif: "DAY",
        legs: [
          { symbol: "AAPL", side: "BUY", orderType: "LIMIT", quantity: 100, price: 209.5, smpAction: "NONE" },
          { symbol: "AAPL", side: "SELL", orderType: "LIMIT", quantity: 50, price: 210.5, smpAction: "NONE" },
        ],
      },
    ];
    const doc = buildConfigDocument(draft) as any;
    expect(doc.market_maker_combos[0].legs[0].price).toBe(20950);
    expect(doc.market_maker_combos[0].legs[1].price).toBe(21050);
  });
});

describe("renderYaml", () => {
  it("produces a parseable header and quoted schedule times", () => {
    const draft = twoTraderExchange();
    draft.sessionsEnabled = true;
    const text = generateYaml(draft, { generatedDate: "2026-07-09" });
    expect(text).toContain("# Generated by pm-config-gen");
    expect(text).toContain("# -- Session control --");
    // Schedule times must round-trip as strings, not sexagesimal numbers.
    const parsed = yaml.load(text, { json: true }) as any;
    expect(parsed.schedule.pre_open).toBe("09:00");
    expect(parsed.schedule.closing_auction_end).toBe("16:05");
    expect(parsed.sessions_enabled).toBe(true);
  });

  it("includes the default-field comment block when requested", () => {
    const draft = twoTraderExchange();
    draft.output.commentDefaultFields = true;
    const text = generateYaml(draft);
    expect(text).toContain("Complete Recognized Configuration Shape");
    expect(text).toContain("Field Notes and Accepted Values");
  });
});

describe("parseYamlToDraft round trip", () => {
  it("re-imports a generated config without losing modelled fields", () => {
    const draft = twoTraderExchange();
    draft.sessionsEnabled = true;
    draft.riskControls.globalStaticBandPct = 0.2;
    draft.gateways.push(createGateway("OPS01", "ADMIN"));
    const text = generateYaml(draft);
    const { draft: reparsed } = parseYamlToDraft(text);
    expect(reparsed.symbolOrder).toEqual(["AAPL"]);
    expect(reparsed.gateways.map((g) => g.id)).toEqual(["TRADER01", "TRADER02", "OPS01"]);
    expect(reparsed.gateways[2]!.role).toBe("ADMIN");
    expect(reparsed.sessionsEnabled).toBe(true);
    expect(reparsed.riskControls.globalStaticBandPct).toBeCloseTo(0.2, 5);
  });

  it("P3.9: imports an omitted disconnect_behaviour as the engine default (CANCEL_QUOTES_ONLY)", () => {
    const text = [
      "sessions_enabled: false",
      "enforce_collars: true",
      "enforce_circuit_breakers: true",
      "snapshot_interval_sec: 0.5",
      "gateways:",
      "  alf:",
      "  - id: TRADER01", // TRADER, disconnect_behaviour intentionally omitted
      "    role: TRADER",
      "  - id: OPS01",
      "    role: ADMIN",
      "    disconnect_behaviour: LEAVE_ALL",
      "symbols:",
      "  AAPL:",
      "    tick_decimals: 2",
      "",
    ].join("\n");
    const { draft } = parseYamlToDraft(text);
    // Omitted -> engine default, not the role-derived CANCEL_ALL.
    expect(draft.gateways[0]!.disconnectBehaviour).toBe("CANCEL_QUOTES_ONLY");
    // Explicit value is preserved verbatim.
    expect(draft.gateways[1]!.disconnectBehaviour).toBe("LEAVE_ALL");
    // Re-export keeps the imported behaviour rather than silently changing it.
    const regenerated = generateYaml(draft);
    const parsed = yaml.load(regenerated, { json: true }) as any;
    expect(parsed.gateways.alf[0].disconnect_behaviour).toBe("CANCEL_QUOTES_ONLY");
  });

  it("newly created gateways still use role-derived disconnect defaults", () => {
    expect(createGateway("T1", "TRADER").disconnectBehaviour).toBe("CANCEL_ALL");
    expect(createGateway("OPS", "ADMIN").disconnectBehaviour).toBe("LEAVE_ALL");
  });

  it("imports explicit multi-MM quotes from the three-books-complex example (stub-review precondition)", () => {
    // The Market Maker tab's quote-stub review reports a symbol as satisfied when
    // it has an explicit quote with both prices set. This guards that the parser
    // surfaces exactly that for a real config with fully-specified quotes.
    const examplePath = fileURLToPath(
      new URL(
        "../../../../docs/examples/ref_data/three-books-complex-setup/engine_config.yaml",
        import.meta.url,
      ),
    );
    const { draft } = parseYamlToDraft(readFileSync(examplePath, "utf8"));
    const aapl = draft.symbols.AAPL;
    expect(aapl).toBeDefined();
    const quotes = aapl!.marketMakerQuotes ?? [];
    expect(quotes.length).toBeGreaterThanOrEqual(2);
    for (const q of quotes) {
      expect(q.bidPrice).not.toBeNull();
      expect(q.askPrice).not.toBeNull();
    }
    expect(quotes.map((q) => q.gatewayId)).toEqual(expect.arrayContaining(["MM01", "MM02"]));
  });

  it("preserves unmapped top-level sections", () => {
    const text = [
      "sessions_enabled: false",
      "enforce_collars: true",
      "enforce_circuit_breakers: true",
      "snapshot_interval_sec: 0.5",
      "gateways:",
      "  alf:",
      "  - id: TRADER01",
      "    role: TRADER",
      "    disconnect_behaviour: CANCEL_ALL",
      "symbols:",
      "  AAPL:",
      "    tick_decimals: 2",
      "future_feature:",
      "  some_key: 42",
      "",
    ].join("\n");
    const { draft, unmapped } = parseYamlToDraft(text);
    expect(unmapped).toContain("future_feature");
    expect(draft.unmappedYaml.future_feature).toEqual({ some_key: 42 });
    // And it survives re-export.
    const regenerated = generateYaml(draft);
    expect(regenerated).toContain("future_feature");
  });
});

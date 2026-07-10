import { describe, expect, it } from "vitest";
import {
  createBlankDraft,
  createGateway,
  createMmQuoteSeed,
  createSymbol,
  deriveIpoQuote,
  effectiveDefaultCollar,
  engineConfigDraftSchema,
  personaMeets,
} from "../src/index.js";

describe("schema", () => {
  it("blank draft satisfies the Zod schema", () => {
    const result = engineConfigDraftSchema.safeParse(createBlankDraft());
    expect(result.success).toBe(true);
  });

  it("derives an IPO quote straddling the reference price", () => {
    const q = deriveIpoQuote("MM01", 191.86, 2, 2, 1000);
    expect(q.bidPrice).toBeCloseTo(191.85, 5);
    expect(q.askPrice).toBeCloseTo(191.87, 5);
    expect(q.bidQty).toBe(1000);
    expect(q.askQty).toBe(1000);
    expect(q.gatewayId).toBe("MM01");
    // Reference lies within [bid, ask].
    expect(q.bidPrice! <= 191.86 && 191.86 <= q.askPrice!).toBe(true);
  });

  it("keeps the derived IPO quote on the tick grid for odd spreads", () => {
    const q = deriveIpoQuote("MM01", 100, 2, 1); // spread 1 tick
    expect(q.bidPrice).toBeCloseTo(100, 5); // floor(1/2)=0 below
    expect(q.askPrice).toBeCloseTo(100.01, 5); // 1 above
  });

  it("a populated draft satisfies the Zod schema", () => {
    const draft = createBlankDraft();
    draft.symbols = { AAPL: { tickDecimals: 2, level: "CORE" } };
    draft.symbolOrder = ["AAPL"];
    draft.gateways = [createGateway("TRADER01"), createGateway("MM01", "MARKET_MAKER")];
    draft.riskControls.levels = { CORE: { staticBandPct: 0.18, dynamicBandPct: 0.02 } };
    expect(engineConfigDraftSchema.safeParse(draft).success).toBe(true);
  });

  it("preserves per-symbol market_maker_quotes through Zod validation", () => {
    const draft = createBlankDraft();
    const quote = createMmQuoteSeed("MM01");
    quote.bidPrice = 100;
    quote.askPrice = 101;
    draft.symbols = {
      AAPL: { ...createSymbol(2, { lastBuyPrice: 100, lastSellPrice: 101 }), marketMakerQuotes: [quote] },
    };
    draft.symbolOrder = ["AAPL"];
    draft.gateways = [createGateway("MM01", "MARKET_MAKER")];
    const result = engineConfigDraftSchema.safeParse(draft);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.symbols.AAPL?.marketMakerQuotes).toHaveLength(1);
      expect(result.data.symbols.AAPL?.marketMakerQuotes?.[0]?.gatewayId).toBe("MM01");
    }
  });

  it("derives disconnect behaviour from role", () => {
    expect(createGateway("A", "MARKET_MAKER").disconnectBehaviour).toBe("CANCEL_QUOTES_ONLY");
    expect(createGateway("B", "ADMIN").disconnectBehaviour).toBe("LEAVE_ALL");
    expect(createGateway("C", "TRADER").disconnectBehaviour).toBe("CANCEL_ALL");
  });

  it("personaMeets respects tier ordering", () => {
    expect(personaMeets("BEGINNER", "B")).toBe(true);
    expect(personaMeets("BEGINNER", "I")).toBe(false);
    expect(personaMeets("EXPERT", "E")).toBe(true);
    expect(personaMeets("INTERMEDIATE", "E")).toBe(false);
  });

  it("effectiveDefaultCollar is undefined until a global band is set", () => {
    const draft = createBlankDraft();
    expect(effectiveDefaultCollar(draft)).toBeUndefined();
    draft.riskControls.globalStaticBandPct = 0.2;
    expect(effectiveDefaultCollar(draft)).toEqual({ staticBandPct: 0.2, dynamicBandPct: 0.02 });
  });
});

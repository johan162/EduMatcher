import { describe, expect, it } from "vitest";
import {
  createBlankDraft,
  createGateway,
  effectiveDefaultCollar,
  engineConfigDraftSchema,
  personaMeets,
} from "../src/index.js";

describe("schema", () => {
  it("blank draft satisfies the Zod schema", () => {
    const result = engineConfigDraftSchema.safeParse(createBlankDraft());
    expect(result.success).toBe(true);
  });

  it("a populated draft satisfies the Zod schema", () => {
    const draft = createBlankDraft();
    draft.symbols = { AAPL: { tickDecimals: 2, level: "CORE" } };
    draft.symbolOrder = ["AAPL"];
    draft.gateways = [createGateway("TRADER01"), createGateway("MM01", "MARKET_MAKER")];
    draft.riskControls.levels = { CORE: { staticBandPct: 0.18, dynamicBandPct: 0.02 } };
    expect(engineConfigDraftSchema.safeParse(draft).success).toBe(true);
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

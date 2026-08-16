import { describe, expect, it } from "vitest";
import {
  applyOverride,
  applyOverrideToMany,
  buildOverrideRow,
  clearOverrides,
  createBlankDraft,
  selectOverridePage,
  type EngineConfigDraft,
} from "../src/index.js";

function draftWith(count: number): EngineConfigDraft {
  const d = createBlankDraft();
  for (let i = 0; i < count; i += 1) {
    const symbol = `SYM${String(i).padStart(3, "0")}`;
    d.symbols[symbol] = { tickDecimals: 2, lastBuyPrice: 100, lastSellPrice: 100 };
    d.symbolOrder.push(symbol);
  }
  return d;
}

describe("override rows", () => {
  it("reports a value as inherited until the symbol sets it", () => {
    const d = draftWith(1);
    const before = buildOverrideRow(d, "SYM000");
    expect(before.aceInitialBandPct.overridden).toBe(false);
    expect(before.aceInitialBandPct.value).toBeCloseTo(
      d.circuitBreakerDefaults.reopening.initialBandPct,
      6,
    );
    expect(before.hasAnyOverride).toBe(false);

    applyOverride(d, "SYM000", "aceInitialBandPct", 0.03);
    const after = buildOverrideRow(d, "SYM000");
    expect(after.aceInitialBandPct.overridden).toBe(true);
    expect(after.aceInitialBandPct.value).toBeCloseTo(0.03, 6);
    expect(after.hasAnyOverride).toBe(true);
  });

  it("returns a symbol to inheriting when the override is cleared", () => {
    // Clearing must remove the key rather than write the default back, or the
    // symbol would silently stop tracking later changes to the exchange value.
    const d = draftWith(1);
    applyOverride(d, "SYM000", "aceInitialBandPct", 0.03);
    applyOverride(d, "SYM000", "aceInitialBandPct", undefined);

    expect(buildOverrideRow(d, "SYM000").aceInitialBandPct.overridden).toBe(false);
    expect(d.symbols.SYM000!.circuitBreaker).toBeUndefined();
  });

  it("does not leave an empty circuit_breaker container behind", () => {
    const d = draftWith(1);
    applyOverride(d, "SYM000", "aceEnabled", false);
    applyOverride(d, "SYM000", "aceEnabled", undefined);

    expect(d.symbols.SYM000!.circuitBreaker).toBeUndefined();
  });

  it("keeps a container that still holds a level override", () => {
    const d = draftWith(1);
    d.symbols.SYM000!.circuitBreaker = { levels: { L1: { priceShiftPct: 0.05 } } };
    applyOverride(d, "SYM000", "aceInitialBandPct", 0.03);
    applyOverride(d, "SYM000", "aceInitialBandPct", undefined);

    expect(d.symbols.SYM000!.circuitBreaker!.levels.L1).toEqual({ priceShiftPct: 0.05 });
  });
});

describe("paging", () => {
  it("pages a 250-symbol exchange", () => {
    const d = draftWith(250);
    const page = selectOverridePage(d, { page: 0, pageSize: 25 });

    expect(page.total).toBe(250);
    expect(page.pageCount).toBe(10);
    expect(page.rows).toHaveLength(25);
    expect(page.rows[0]!.symbol).toBe("SYM000");
  });

  it("clamps a page index stranded past the end by a filter", () => {
    const d = draftWith(250);
    const page = selectOverridePage(d, {
      search: "SYM001",
      page: 9,
      pageSize: 25,
    });

    expect(page.total).toBe(1);
    expect(page.page).toBe(0);
    expect(page.rows[0]!.symbol).toBe("SYM001");
  });

  it("filters case-insensitively on the symbol name", () => {
    const d = draftWith(20);
    expect(selectOverridePage(d, { search: "sym01", page: 0, pageSize: 100 }).total).toBe(
      10,
    );
  });

  it("can list only symbols that deviate from the defaults", () => {
    const d = draftWith(50);
    applyOverride(d, "SYM007", "aceInitialBandPct", 0.03);
    const page = selectOverridePage(d, {
      onlyOverridden: true,
      page: 0,
      pageSize: 25,
    });

    expect(page.total).toBe(1);
    expect(page.rows[0]!.symbol).toBe("SYM007");
  });
});

describe("bulk edits", () => {
  it("applies one field across a selection", () => {
    const d = draftWith(100);
    const selection = ["SYM001", "SYM002", "SYM003"];
    applyOverrideToMany(d, selection, "aceRandomEndMaxNs", 0);

    for (const s of selection) {
      expect(buildOverrideRow(d, s).aceRandomEndMaxNs.value).toBe(0);
    }
    expect(buildOverrideRow(d, "SYM004").aceRandomEndMaxNs.overridden).toBe(false);
  });

  it("clears every override on a selection at once", () => {
    const d = draftWith(10);
    applyOverrideToMany(d, ["SYM001"], "aceInitialBandPct", 0.03);
    applyOverrideToMany(d, ["SYM001"], "staticBandPct", 0.3);
    clearOverrides(d, ["SYM001"]);

    const row = buildOverrideRow(d, "SYM001");
    expect(row.hasAnyOverride).toBe(false);
    expect(d.symbols.SYM001!.collar).toBeUndefined();
  });

  it("ignores symbols that are not in the draft", () => {
    const d = draftWith(1);
    expect(() =>
      applyOverrideToMany(d, ["GHOST"], "aceInitialBandPct", 0.03),
    ).not.toThrow();
    expect(d.symbols.GHOST).toBeUndefined();
  });
});

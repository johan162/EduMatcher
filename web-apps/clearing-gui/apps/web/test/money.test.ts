import { describe, expect, it } from "vitest";
import {
  formatCurrency,
  formatMinor,
  formatTicks,
  ticksToDisplay,
  type Minor,
  type Ticks,
} from "@/lib/money";

/**
 * Clearing money is ticks of a symbol's precision; EOD money is minor units.
 * The two are different units and the helpers keep them apart: by type (the
 * branded `Ticks` / `Minor`) and at run time (a tick value without its
 * precision is refused rather than guessed).
 */
const t = (n: number) => n as Ticks;
const m = (n: number) => n as Minor;

describe("formatTicks", () => {
  it("converts with the row's own precision", () => {
    expect(formatTicks(t(18750), 2)).toBe("187.50");
    expect(formatTicks(t(10862), 4)).toBe("1.0862");
    expect(formatTicks(t(-6000), 4)).toBe("-0.6000");
    expect(formatTicks(t(2810000), 2)).toBe("28,100.00");
  });

  it("can show averages with extra decimals", () => {
    expect(formatTicks(t(18733.333333), 2, 2)).toBe("187.3333");
  });

  it("renders a missing value as a dash, not as zero", () => {
    expect(formatTicks(null, 2)).toBe("—");
  });

  it("refuses a value without a valid precision", () => {
    expect(() => formatTicks(t(100), undefined as unknown as number)).toThrow(RangeError);
    expect(() => formatTicks(t(100), 2.5)).toThrow(RangeError);
    expect(() => formatTicks(t(100), -1)).toThrow(RangeError);
    expect(() => formatTicks(t(100), 10)).toThrow(RangeError);
    expect(() => ticksToDisplay(t(100), Number.NaN)).toThrow(RangeError);
  });

  it("does not accept an EOD minor-unit amount (compile-time)", () => {
    // @ts-expect-error a Minor is not Ticks
    formatTicks(m(1234), 2);
    // @ts-expect-error a bare number has no declared unit
    formatTicks(1234, 2);
  });
});

describe("formatMinor", () => {
  it("is exact for 2-decimal minor units", () => {
    expect(formatMinor(m(1234))).toBe("12.34");
    expect(formatMinor(m(-2500))).toBe("-25.00");
    expect(formatMinor(m(1))).toBe("0.01");
    expect(formatMinor(m(-1))).toBe("-0.01");
    expect(formatMinor(m(0))).toBe("0.00");
    expect(formatMinor(m(1009879))).toBe("10,098.79");
  });

  it("refuses a non-integer", () => {
    expect(() => formatMinor(m(12.5))).toThrow(RangeError);
  });

  it("does not accept a clearing tick value (compile-time)", () => {
    // @ts-expect-error Ticks are not minor units
    formatMinor(t(1234));
  });
});

describe("formatCurrency", () => {
  it("shows a display-currency total with two decimals", () => {
    expect(formatCurrency(26.066666)).toBe("26.07");
    expect(formatCurrency(-1234.5)).toBe("-1,234.50");
    expect(formatCurrency(null)).toBe("—");
  });
});

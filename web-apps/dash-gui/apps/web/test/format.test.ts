/** lib/format.ts (design §13, D2.7). */

import { describe, expect, it } from "vitest";
import {
  formatBytes,
  formatCompact,
  formatCount,
  formatDuration,
  formatMicros,
  formatMillis,
  formatPercent,
  formatRate,
} from "../src/lib/format.js";

const T = " ";

describe("bytes, binary", () => {
  it.each([
    [0, "0 B"],
    [1023, "1023 B"],
    [1024, "1.00 KiB"],
    [1536, "1.50 KiB"],
    [1.5 * 1024 ** 3, "1.50 GiB"],
    [412e6, "393 MiB"],
    [1024 * 1024 - 1, "1.00 MiB"], // not "1024 KiB"
    [2 * 1024 ** 4, "2.00 TiB"],
  ])("%d -> %s", (n, text) => expect(formatBytes(n)).toBe(text));
});

describe("µs and ms", () => {
  it.each([
    [0, "0 µs"],
    [999, "999 µs"],
    [999.4, "999 µs"],
    [999.6, "1.00 ms"],
    [1000, "1.00 ms"],
    [640_400, "640 ms"],
    [1_500_000, "1.50 s"],
  ])("%d µs -> %s", (us, text) => expect(formatMicros(us)).toBe(text));

  it("milliseconds on the same scale", () => {
    expect(formatMillis(3)).toBe("3.00 ms");
    expect(formatMillis(14_200)).toBe("14.2 s");
  });
});

describe("counts, grouped with thin spaces", () => {
  it.each([
    [0, "0"],
    [999, "999"],
    [1000, `1${T}000`],
    [184_302, `184${T}302`],
    [-1_234_567, `-1${T}234${T}567`],
    [41_775.6, `41${T}776`],
  ])("%d -> %s", (n, text) => expect(formatCount(n)).toBe(text));

  it("compact past a million", () => {
    expect(formatCompact(999_999)).toBe(`999${T}999`);
    expect(formatCompact(1_210_000)).toBe("1.21 M");
    expect(formatCompact(3.4e9)).toBe("3.40 G");
  });
});

describe("rates, percent, durations", () => {
  it("rates", () => {
    expect(formatRate(212.4, "s")).toBe("212 /s");
    expect(formatRate(4.2, "min")).toBe("4.20 /min");
    expect(formatRate(3071, "min")).toBe(`3${T}071 /min`);
    expect(formatRate(0, "h")).toBe("0 /h");
  });

  it("percent: one decimal below 100", () => {
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(0.3)).toBe("0.3%");
    expect(formatPercent(14.25)).toBe("14.3%");
    expect(formatPercent(62)).toBe("62.0%");
    expect(formatPercent(99.97)).toBe("100%");
    expect(formatPercent(130)).toBe("130%");
  });

  it("durations as HH:MM, days in front", () => {
    expect(formatDuration(0)).toBe("00:00");
    expect(formatDuration(59)).toBe("00:00");
    expect(formatDuration(18_720)).toBe("05:12");
    expect(formatDuration(3 * 86_400 + 18_720)).toBe("3d 05:12");
    expect(formatDuration(-5)).toBe("00:00");
  });
});

describe("edge cases (review)", () => {
  it("rounds before choosing the decimals: never 4 significant figures at a boundary", () => {
    expect(formatRate(99.99, "s")).toBe("100 /s");
    expect(formatRate(9.999, "s")).toBe("10.0 /s");
    expect(formatRate(999.6, "min")).toBe(`1${T}000 /min`);
    expect(formatMicros(999_600)).toBe("1.00 s");
    expect(formatMicros(999_400)).toBe("999 ms");
    expect(formatBytes(1023.6 * 1024)).toBe("1.00 MiB");
    expect(formatBytes(1023.4)).toBe("1023 B");
    expect(formatBytes(1023.6)).toBe("1.00 KiB");
    expect(formatCompact(999_999.6)).toBe("1.00 M");
    expect(formatCompact(999_600_000)).toBe("1.00 G");
    expect(formatPercent(99.96)).toBe("100%");
    expect(formatPercent(99.94)).toBe("99.9%");
  });

  it("never a negative zero", () => {
    expect(formatCount(-0.3)).toBe("0");
    expect(formatPercent(-0.04)).toBe("0%");
    expect(formatRate(-0.0001, "s")).toBe("0 /s");
    expect(formatMicros(-0.4)).toBe("0 µs");
    expect(formatBytes(-0.2)).toBe("0 B");
    expect(formatPercent(-3.26)).toBe("-3.3%");
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])("%d is shown as a dash everywhere", (x) => {
    for (const f of [formatCount, formatCompact, formatBytes, formatMicros, formatMillis, formatPercent, formatDuration, (v: number) => formatRate(v, "s")]) {
      expect(f(x)).toBe("—");
    }
  });

  it("huge values stay readable", () => {
    expect(formatBytes(5 * 1024 ** 5)).toBe(`5${T}120 TiB`);
    expect(formatCount(1e15)).toBe(`1${T}000${T}000${T}000${T}000${T}000`);
  });
});

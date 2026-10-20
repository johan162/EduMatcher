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

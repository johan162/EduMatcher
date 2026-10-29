import { describe, expect, it } from "vitest";
import { ABSENT, clockInTimezone, compact, elapsed, price, qty, resumeAt } from "../src/lib/format.js";

describe("price", () => {
  it("formats to a fixed number of decimals", () => {
    expect(price(150.1)).toBe("150.10");
  });

  it("renders an absent price as a dash rather than zero", () => {
    // "no bid" and "a bid of zero" mean different things on a book.
    expect(price(undefined)).toBe(ABSENT);
  });

  it("renders a genuine zero as zero", () => {
    expect(price(0)).toBe("0.00");
  });

  it("does not print NaN into the UI", () => {
    expect(price(Number.NaN)).toBe(ABSENT);
  });
});

describe("qty", () => {
  it("groups thousands for scannability", () => {
    expect(qty(184300)).toBe("184,300");
  });

  it("distinguishes zero from absent", () => {
    expect(qty(0)).toBe("0");
    expect(qty(undefined)).toBe(ABSENT);
  });
});

describe("compact", () => {
  it("abbreviates a turnover to three significant digits", () => {
    expect(compact(27_644_220)).toBe("27.6M");
    expect(compact(1_420_000_000)).toBe("1.4B");
  });

  it("drops the decimal once the mantissa is three digits wide", () => {
    expect(compact(274_300_000)).toBe("274M");
  });

  it("leaves small figures alone", () => {
    expect(compact(842)).toBe("842");
  });

  it("distinguishes zero from absent", () => {
    expect(compact(0)).toBe("0");
    expect(compact(undefined)).toBe(ABSENT);
  });
});

describe("clockInTimezone", () => {
  it("shows the configured session wall-clock time", () => {
    expect(clockInTimezone("2026-07-30T11:02:17.000Z", "Europe/Stockholm")).toBe("13:02:17");
  });

  it("falls back to the absent marker for an invalid timezone", () => {
    expect(clockInTimezone("2026-07-30T11:02:17.000Z", "not-a-timezone")).toBe(ABSENT);
  });
});

describe("resumeAt", () => {
  const now = Date.parse("2026-07-30T11:02:17.000Z");

  it("shows the wall-clock time and a countdown", () => {
    expect(resumeAt("2026-07-30T11:07:17.000Z", "UTC", now)).toBe("11:07:17 (05:00)");
  });

  it("renders the wall-clock time in the given timezone", () => {
    expect(resumeAt("2026-07-30T11:07:17.000Z", "Europe/Stockholm", now)).toBe("13:07:17 (05:00)");
  });

  it("drops the countdown once the moment has passed", () => {
    // An auction resume often runs a little late; a negative countdown would
    // read as a fault rather than as normal.
    expect(resumeAt("2026-07-30T11:02:03.000Z", "UTC", now)).toBe("11:02:03");
  });

  it("renders a halt with no scheduled resume as absent", () => {
    expect(resumeAt(undefined, "UTC", now)).toBe(ABSENT);
  });
});

describe("elapsed", () => {
  const now = Date.parse("2026-07-30T11:05:00.000Z");

  it("reports seconds under a minute", () => {
    expect(elapsed("2026-07-30T11:04:47.000Z", now)).toBe("13s");
  });

  it("reports minutes and seconds beyond that", () => {
    expect(elapsed("2026-07-30T11:02:17.000Z", now)).toBe("2m 43s");
  });

  it("never reports negative time from a slightly-ahead clock", () => {
    expect(elapsed("2026-07-30T11:05:02.000Z", now)).toBe("0s");
  });
});

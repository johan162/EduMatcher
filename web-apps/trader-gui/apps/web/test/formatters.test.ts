import { describe, it, expect } from "vitest";
import {
  formatPrice,
  formatQty,
  formatChangePct,
  formatCountdown,
  shortId,
} from "@/lib/formatters";

describe("formatPrice", () => {
  it("formats with given decimals", () => {
    expect(formatPrice(150.25, 2)).toBe("150.25");
    expect(formatPrice(150.1, 3)).toBe("150.100");
  });

  it("returns — for null", () => {
    expect(formatPrice(null)).toBe("—");
  });
});

describe("formatQty", () => {
  it("formats integers with thousands separator", () => {
    expect(formatQty(1000)).toBe("1,000");
    expect(formatQty(500)).toBe("500");
  });

  it("returns — for null", () => {
    expect(formatQty(null)).toBe("—");
  });
});

describe("formatChangePct", () => {
  it("computes (last - open) / open * 100", () => {
    expect(formatChangePct(151.5, 150)).toBe("+1.00%");
    expect(formatChangePct(148.5, 150)).toBe("-1.00%");
  });

  it("returns — when either value is null or open is 0", () => {
    expect(formatChangePct(null, 150)).toBe("—");
    expect(formatChangePct(150, null)).toBe("—");
    expect(formatChangePct(150, 0)).toBe("—");
  });
});

describe("formatCountdown", () => {
  it("returns MM:SS for under an hour", () => {
    expect(formatCountdown(90_000)).toBe("01:30");
    expect(formatCountdown(0)).toBe("00:00");
  });

  it("returns HH:MM:SS for an hour or more", () => {
    expect(formatCountdown(3_661_000)).toBe("01:01:01");
  });
});

describe("shortId", () => {
  it("truncates to 8 chars", () => {
    expect(shortId("ORD-abcdef123456")).toBe("ORD-abcd");
  });
});

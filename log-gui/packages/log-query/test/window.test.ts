import { describe, expect, it } from "vitest";
import { isValidWindow, windowToIsoFrom } from "../src/window.js";

describe("windowToIsoFrom", () => {
  it("subtracts the correct number of seconds for each allow-listed window", () => {
    const now = new Date("2026-07-29T12:00:00.000Z");
    expect(windowToIsoFrom("1h", now)).toBe("2026-07-29T11:00:00Z");
    expect(windowToIsoFrom("24h", now)).toBe("2026-07-28T12:00:00Z");
  });

  it("falls back to 1h for an unknown window", () => {
    const now = new Date("2026-07-29T12:00:00.000Z");
    expect(windowToIsoFrom("bogus", now)).toBe(windowToIsoFrom("1h", now));
  });
});

describe("isValidWindow", () => {
  it("accepts the documented windows and rejects everything else", () => {
    expect(isValidWindow("1h")).toBe(true);
    expect(isValidWindow("24h")).toBe(true);
    expect(isValidWindow("3d")).toBe(false);
  });
});

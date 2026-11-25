import { describe, expect, it } from "vitest";
import { formatDay } from "../src/lib/formatTs.js";

describe("formatDay", () => {
  it("renders a session-timezone day with weekday and year", () => {
    expect(formatDay("2026-11-24")).toBe("Tue 24 Nov 2026");
  });

  it("is not shifted by the browser's zone (the string is a date, not an instant)", () => {
    expect(formatDay("2026-01-01")).toBe("Thu 01 Jan 2026");
  });
});

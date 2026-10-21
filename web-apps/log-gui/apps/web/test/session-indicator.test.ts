/** The session indicator's pure parts (WP-UI01); pm-dash and pm-book also render it under jsdom. */

import { describe, expect, it } from "vitest";
import {
  formatCountdown,
  phaseMeta,
} from "../src/components/SessionIndicator.js";

describe("formatCountdown", () => {
  it("is MM:SS below an hour and HH:MM:SS from one", () => {
    expect(formatCountdown(188_230)).toBe("03:08");
    expect(formatCountdown(3_862_000)).toBe("01:04:22");
  });

  it("never runs negative", () => {
    expect(formatCountdown(-5_000)).toBe("00:00");
  });
});

describe("phaseMeta", () => {
  it("uses pm-trader's labels and colours, and Unknown for anything else", () => {
    expect(phaseMeta("CONTINUOUS")).toEqual({
      label: "Continuous",
      badge: "bg-emerald-500 text-black",
    });
    expect(phaseMeta("UNKNOWN").label).toBe("Unknown");
    expect(phaseMeta(null).label).toBe("Unknown");
  });
});

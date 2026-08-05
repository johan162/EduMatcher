import { describe, expect, it } from "vitest";
import { ageSec, formatAge, isLate, liveTickLabel } from "../src/lib/data-age.js";

const NOW = Date.parse("2026-07-30T12:00:00Z");

describe("ageSec", () => {
  it("measures seconds since the source last delivered", () => {
    expect(ageSec(NOW - 4_000, NOW)).toBe(4);
    expect(ageSec(NOW - 125_000, NOW)).toBe(125);
  });

  it("distinguishes never-delivered from just-delivered", () => {
    // Opposite readings that must never render the same: one says the feed
    // is working, the other says nothing has ever arrived.
    expect(ageSec(null, NOW)).toBeNull();
    expect(ageSec(NOW, NOW)).toBe(0);
  });

  it("never reports a negative age from clock skew", () => {
    expect(ageSec(NOW + 5_000, NOW)).toBe(0);
  });
});

describe("formatAge", () => {
  it("coarsens as the age grows, because precision stops mattering", () => {
    expect(formatAge(4)).toBe("4s");
    expect(formatAge(59)).toBe("59s");
    expect(formatAge(60)).toBe("1m");
    expect(formatAge(3_599)).toBe("59m");
    expect(formatAge(3_600)).toBe("1h");
  });

  it("dashes rather than inventing a zero when nothing has arrived", () => {
    expect(formatAge(null)).toBe("—");
  });
});

describe("isLate", () => {
  it("allows one missed poll before flagging", () => {
    // Flagging ordinary jitter would train the reader to ignore the
    // indicator, which is worse than not having one.
    expect(isLate("daily", 10)).toBe(false);
    expect(isLate("daily", 20)).toBe(false);
    expect(isLate("daily", 21)).toBe(true);
  });

  it("holds the previous close to its own much slower cadence", () => {
    // Five-minute poll: a minute of silence is nothing.
    expect(isLate("prevClose", 60)).toBe(false);
    expect(isLate("prevClose", 601)).toBe(true);
  });

  it("never flags a source that has not delivered at all", () => {
    // That is a startup state, and the label already says so in words.
    expect(isLate("live", null)).toBe(false);
  });
});

describe("liveTickLabel", () => {
  it("says nothing has arrived rather than claiming a tick at time zero", () => {
    expect(liveTickLabel(null)).toBe("no ticks yet");
  });

  it("reads as an age once ticks are flowing", () => {
    expect(liveTickLabel(3)).toBe("last tick 3s ago");
    expect(liveTickLabel(240)).toBe("last tick 4m ago");
  });
});

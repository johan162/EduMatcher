import { describe, expect, it } from "vitest";
import { countdownLabel, countdownTo, formatCountdown } from "../src/lib/session-countdown.js";

const NOW = Date.parse("2026-07-30T15:00:00Z");
const at = (iso: string) => iso;

describe("countdownTo (T-M6)", () => {
  it("counts down to a scheduled transition", () => {
    const result = countdownTo("CLOSING_AUCTION", at("2026-07-30T15:04:22Z"), NOW);
    expect(result).toMatchObject({ seconds: 262, phase: "CLOSING_AUCTION", overdue: false });
  });

  it("returns nothing when the feed named no transition", () => {
    // A manually driven session, or none scheduled. This is a real state and
    // must render as silence — a 0:00 would assert a transition that is not
    // coming, which is the one thing the countdown exists to get right.
    expect(countdownTo(null, null, NOW)).toBeNull();
    expect(countdownTo(undefined, undefined, NOW)).toBeNull();
  });

  it("returns nothing for a half-pair", () => {
    // A phase with no time cannot be counted down to; a time with no phase
    // does not say what happens when it arrives.
    expect(countdownTo("CLOSED", null, NOW)).toBeNull();
    expect(countdownTo(null, at("2026-07-30T16:00:00Z"), NOW)).toBeNull();
  });

  it("returns nothing rather than a wrong number for an unreadable timestamp", () => {
    expect(countdownTo("CLOSED", "not-a-time", NOW)).toBeNull();
  });

  it("reports overdue instead of running a negative clock", () => {
    // A late, wedged, or absent scheduler all look like this, and a frozen
    // 0:00 would hide all three.
    const result = countdownTo("CLOSED", at("2026-07-30T14:59:00Z"), NOW);
    expect(result).toMatchObject({ seconds: 0, overdue: true });
  });

  it("flags the last minute as imminent", () => {
    expect(countdownTo("CLOSED", at("2026-07-30T15:00:30Z"), NOW)?.imminent).toBe(true);
    expect(countdownTo("CLOSED", at("2026-07-30T15:05:00Z"), NOW)?.imminent).toBe(false);
  });

  it("does not call an overdue transition imminent", () => {
    // They mean different things and are styled differently: one is "watch
    // this", the other is "something is wrong".
    const result = countdownTo("CLOSED", at("2026-07-30T14:59:30Z"), NOW);
    expect(result).toMatchObject({ overdue: true, imminent: false });
  });
});

describe("formatCountdown", () => {
  it("keeps seconds all the way down, unlike a data age", () => {
    // A countdown grows *more* interesting as it shrinks, which is the
    // opposite of an age — so this refines where formatAge coarsens.
    expect(formatCountdown(9)).toBe("9s");
    expect(formatCountdown(59)).toBe("59s");
    expect(formatCountdown(62)).toBe("1:02");
    expect(formatCountdown(600)).toBe("10:00");
  });

  it("grows an hours field for the start of a trading day", () => {
    expect(formatCountdown(3_862)).toBe("1:04:22");
  });

  it("floors at zero rather than rendering a negative", () => {
    expect(formatCountdown(-5)).toBe("0s");
  });
});

describe("countdownLabel", () => {
  it("names the phase, so the reader knows what is about to happen", () => {
    expect(countdownLabel(countdownTo("CLOSING_AUCTION", at("2026-07-30T15:04:22Z"), NOW))).toBe(
      "CLOSING_AUCTION in 4:22",
    );
  });

  it("says overdue rather than showing a stopped clock", () => {
    expect(countdownLabel(countdownTo("CLOSED", at("2026-07-30T14:00:00Z"), NOW))).toBe("CLOSED overdue");
  });

  it("has nothing to say when nothing is scheduled", () => {
    expect(countdownLabel(null)).toBeNull();
  });
});

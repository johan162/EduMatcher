import { describe, expect, it } from "vitest";
import { notExecutableLabel, notExecutableReason, notExecutableShortLabel } from "../src/lib/executable.js";

describe("notExecutableReason (T-M2)", () => {
  it("says a continuous, unhalted symbol is executable", () => {
    expect(notExecutableReason({ sessionPhase: "CONTINUOUS", halted: false })).toBeNull();
  });

  it("ranks a symbol's own halt above the session phase", () => {
    // Halted during CONTINUOUS is halted. Reporting "closed" would be false,
    // and the reader acts on the reason, not just the fact.
    expect(notExecutableReason({ sessionPhase: "CONTINUOUS", halted: true })).toBe("halted");
    expect(notExecutableReason({ sessionPhase: "CLOSED", halted: true })).toBe("halted");
  });

  it.each(["OPENING_AUCTION", "CLOSING_AUCTION"])("calls %s an auction, not a closure", (phase) => {
    // A call phase accepts orders but matches nothing until it uncrosses,
    // so a bid and an ask can sit crossed for minutes with no trade.
    expect(notExecutableReason({ sessionPhase: phase, halted: false })).toBe("auction");
  });

  // The engine's full vocabulary is PRE_OPEN, OPENING_AUCTION, CONTINUOUS,
  // CLOSING_AUCTION, CLOSED (models/session.py). Only CONTINUOUS matches,
  // which is exactly what is_matching_enabled() says there.
  it.each(["CLOSED", "PRE_OPEN"])("calls %s closed", (phase) => {
    expect(notExecutableReason({ sessionPhase: phase, halted: false })).toBe("closed");
  });

  it("treats an unknown phase as executable rather than marking the whole board", () => {
    // Before the first STATE frame the terminal has heard nothing. That is a
    // connection question, reported as one in the status strip — it is not a
    // licence to declare every quote on the screen untradable.
    expect(notExecutableReason({ sessionPhase: null, halted: false })).toBeNull();
    expect(notExecutableReason({ sessionPhase: undefined, halted: false })).toBeNull();
    expect(notExecutableReason({ sessionPhase: "", halted: false })).toBeNull();
  });

  it("still reports a halt before any session phase has arrived", () => {
    expect(notExecutableReason({ sessionPhase: null, halted: true })).toBe("halted");
  });
});

describe("labels", () => {
  it("gives every reason a full explanation and a short form", () => {
    for (const reason of ["halted", "auction", "closed"] as const) {
      expect(notExecutableLabel(reason).length).toBeGreaterThan(20);
      expect(notExecutableShortLabel(reason).length).toBeGreaterThan(0);
    }
  });

  it("says the figures are still accurate, not that they are wrong", () => {
    // The quote is not false under a halt or after the close — it is the
    // last real book. What changes is whether it can be acted on, and the
    // wording has to keep those apart.
    expect(notExecutableLabel("closed")).toMatch(/not executable/);
    expect(notExecutableLabel("auction")).toMatch(/indication/);
  });
});

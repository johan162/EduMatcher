import { describe, it, expect } from "vitest";
import {
  capSymbols,
  diffPairs,
  groupPairs,
  pairKey,
  planPairs,
  replayItems,
  WILDCARD,
} from "@/ws/subscriptions";

describe("capSymbols", () => {
  it("upper-cases, de-duplicates and preserves order", () => {
    expect(capSymbols([" aapl ", "MSFT", "aapl"], 10)).toEqual(["AAPL", "MSFT"]);
  });

  it("truncates to the cap, keeping the leading entries", () => {
    // The active symbol is passed first precisely so the cap cannot drop it.
    expect(capSymbols(["A", "B", "C", "D"], 2)).toEqual(["A", "B"]);
  });

  it("rejects the wildcard and blanks", () => {
    expect(capSymbols(["*", "", "  ", "AAPL"], 10)).toEqual(["AAPL"]);
  });
});

describe("planPairs", () => {
  it("keeps depth/auction off the wildcard", () => {
    const pairs = planPairs({ overview: true, focus: ["AAPL"] });
    expect(pairs.has(pairKey(WILDCARD, "book"))).toBe(true);
    expect(pairs.has(pairKey(WILDCARD, "trades"))).toBe(true);
    // §17.3.4: depth is a full snapshot with no delta form — never broadcast.
    expect(pairs.has(pairKey(WILDCARD, "depth"))).toBe(false);
    expect(pairs.has(pairKey(WILDCARD, "auction"))).toBe(false);
    expect(pairs.has(pairKey("AAPL", "depth"))).toBe(true);
    expect(pairs.has(pairKey("AAPL", "auction"))).toBe(true);
  });

  it("does not duplicate book/trades per focus symbol while the wildcard covers them", () => {
    // Re-requesting them per symbol makes every focus unsubscribe come back
    // as `wildcard_still_subscribed`.
    expect(planPairs({ overview: true, focus: ["AAPL"] }).has(pairKey("AAPL", "book"))).toBe(false);
  });

  it("widens the focus item to all four channels when the overview is off", () => {
    const pairs = planPairs({ overview: false, focus: ["AAPL"] });
    expect([...pairs].sort()).toEqual(
      ["AAPL|auction", "AAPL|book", "AAPL|depth", "AAPL|trades"].sort(),
    );
  });
});

describe("groupPairs", () => {
  it("groups symbols that share a channel set into one item", () => {
    const items = groupPairs([
      pairKey("AAPL", "depth"),
      pairKey("AAPL", "auction"),
      pairKey("MSFT", "depth"),
      pairKey("MSFT", "auction"),
      pairKey(WILDCARD, "book"),
    ]);
    expect(items).toHaveLength(2);
    const focus = items.find((i) => i.channels.join() === "auction,depth")!;
    expect(focus.symbols).toEqual(["AAPL", "MSFT"]);
    const broad = items.find((i) => i.channels.join() === "book")!;
    expect(broad.symbols).toEqual([WILDCARD]);
  });
});

describe("diffPairs", () => {
  it("emits only the delta when the focus symbol changes", () => {
    const before = planPairs({ overview: true, focus: ["AAPL"] });
    const after = planPairs({ overview: true, focus: ["MSFT"] });
    const { subscribe, unsubscribe } = diffPairs(before, after);

    expect(subscribe).toEqual([{ symbols: ["MSFT"], channels: ["auction", "depth"] }]);
    expect(unsubscribe).toEqual([{ symbols: ["AAPL"], channels: ["auction", "depth"] }]);
  });

  it("emits nothing when the plan is unchanged", () => {
    const pairs = planPairs({ overview: true, focus: ["AAPL", "MSFT"] });
    expect(diffPairs(pairs, planPairs({ overview: true, focus: ["AAPL", "MSFT"] }))).toEqual({
      subscribe: [],
      unsubscribe: [],
    });
  });

  it("adds the wildcard item without touching the focus item", () => {
    const off = planPairs({ overview: false, focus: [] });
    const on = planPairs({ overview: true, focus: [] });
    expect(diffPairs(off, on).subscribe).toEqual([
      { symbols: [WILDCARD], channels: ["book", "trades"] },
    ]);
  });
});

describe("replayItems", () => {
  it("annotates only the trades channel with a resume point", () => {
    const desired = planPairs({ overview: false, focus: ["AAPL"] });
    const items = replayItems(desired, (_sym, channel) => (channel === "trades" ? 4_412 : 99));
    expect(items).toHaveLength(1);
    // The snapshot channels are self-healing server-side, so a resume point
    // for them would be ignored — it is dropped rather than sent.
    expect(items[0]!.resume_from).toEqual({ trades: 4_412 });
  });

  it("omits resume_from when nothing has been seen yet", () => {
    const desired = planPairs({ overview: true, focus: [] });
    expect(replayItems(desired, () => undefined)[0]!.resume_from).toBeUndefined();
  });
});

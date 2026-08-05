import { describe, expect, it } from "vitest";
import { TopCache } from "../src/calf/top-cache.js";

describe("TopCache", () => {
  it("returns the first snapshot as-is", () => {
    const cache = new TopCache();
    expect(cache.merge("AAPL", { bid: 150.1, ask: 150.12 })).toEqual({ bid: 150.1, ask: 150.12 });
  });

  it("carries unchanged fields through a delta that omits them", () => {
    const cache = new TopCache();
    cache.merge("AAPL", { bid: 150.1, bidSz: 1400, ask: 150.12, askSz: 900 });

    // An MD that only moved the bid must not blank out the ask.
    expect(cache.merge("AAPL", { bid: 150.11, bidSz: 900 })).toEqual({
      bid: 150.11,
      bidSz: 900,
      ask: 150.12,
      askSz: 900,
    });
  });

  it("clears a withdrawn side instead of keeping the last price", () => {
    const cache = new TopCache();
    cache.merge("AAPL", { bid: 150.1, bidSz: 1400, ask: 150.12, askSz: 900 });

    const merged = cache.merge("AAPL", { bid: null, bidSz: 0 });

    expect("bid" in merged).toBe(false);
    expect(merged.bidSz).toBe(0);
    expect(merged.ask).toBe(150.12);
  });

  it("matches what a reconnecting client's fresh snapshot would show", () => {
    // The divergence this guards against: a merged delta stream and a SNAP
    // describing the same book differently, forever.
    const streamed = new TopCache();
    streamed.merge("AAPL", { bid: 150.1, bidSz: 1400, ask: 150.12, askSz: 900 });
    streamed.merge("AAPL", { bid: null, bidSz: 0 });

    const reconnected = new TopCache();
    reconnected.merge("AAPL", { bidSz: 0, ask: 150.12, askSz: 900 });

    expect(streamed.get("AAPL")).toEqual(reconnected.get("AAPL"));
  });

  it("re-admits a side that comes back after being withdrawn", () => {
    const cache = new TopCache();
    cache.merge("AAPL", { bid: 150.1, bidSz: 1400 });
    cache.merge("AAPL", { bid: null, bidSz: 0 });

    expect(cache.merge("AAPL", { bid: 149.9, bidSz: 50 }).bid).toBe(149.9);
  });

  it("applies a zero size rather than treating it as absent", () => {
    const cache = new TopCache();
    cache.merge("AAPL", { bid: 150.1, bidSz: 1400 });
    expect(cache.merge("AAPL", { bidSz: 0 }).bidSz).toBe(0);
  });

  it("leaves a never-traded symbol without a last price", () => {
    const cache = new TopCache();
    const merged = cache.merge("NEW", { bid: 10, ask: 11 });
    expect("last" in merged).toBe(false);
  });

  it("keeps symbols independent", () => {
    const cache = new TopCache();
    cache.merge("AAPL", { bid: 150.1 });
    cache.merge("MSFT", { bid: 421 });

    expect(cache.get("AAPL")).toEqual({ bid: 150.1 });
    expect(cache.get("MSFT")).toEqual({ bid: 421 });
  });

  it("reports nothing for a symbol it has never seen", () => {
    expect(new TopCache().get("NOPE")).toBeUndefined();
  });

  it("hands back a detached object, so a caller cannot corrupt the cache", () => {
    const cache = new TopCache();
    const merged = cache.merge("AAPL", { bid: 150.1 });
    merged.bid = 999;
    expect(cache.get("AAPL")?.bid).toBe(150.1);
  });
});

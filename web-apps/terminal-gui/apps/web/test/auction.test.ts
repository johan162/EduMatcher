import { describe, expect, it } from "vitest";
import type { AuctionIndicativeFrame } from "@edumatcher/terminal-types";
import {
  auctionSummary,
  imbalanceOf,
  indicativeVsLast,
  rankByImbalance,
  wouldCross,
} from "../src/lib/auction.js";

const indic = (over: Partial<AuctionIndicativeFrame> = {}): AuctionIndicativeFrame => ({
  type: "auction_indicative",
  sym: "AAPL",
  seq: 1,
  ts: "2026-07-30T09:29:00.000Z",
  indicQty: 1000,
  imbalanceQty: 0,
  phase: "OPENING_AUCTION",
  ...over,
});

describe("wouldCross (T-M1)", () => {
  it("distinguishes a crossing book from one that does not", () => {
    // "No cross" is a real state during a call phase — the bids and offers
    // collected so far do not overlap — and must never render as a price of
    // zero.
    expect(wouldCross(indic({ indicPrice: 150.25 }))).toBe(true);
    expect(wouldCross(indic())).toBe(false);
    expect(wouldCross(undefined)).toBe(false);
  });
});

describe("imbalanceOf", () => {
  it("reports the side and size of the surplus", () => {
    const result = imbalanceOf(
      indic({ indicPrice: 150, indicQty: 900, imbalanceQty: 100, imbalanceSide: "BUY" }),
    );
    expect(result).toMatchObject({ side: "BUY", qty: 100 });
  });

  it("scales the surplus against total interest, not in raw shares", () => {
    // 500 unmatched against 500 matched is a book in trouble; 500 against
    // 5,000,000 is noise. Only the ratio makes two symbols comparable.
    const heavy = imbalanceOf(
      indic({ indicPrice: 150, indicQty: 500, imbalanceQty: 500, imbalanceSide: "BUY" }),
    );
    const light = imbalanceOf(
      indic({ indicPrice: 150, indicQty: 5_000_000, imbalanceQty: 500, imbalanceSide: "BUY" }),
    );

    expect(heavy?.ratio).toBeCloseTo(0.5);
    expect(light?.ratio).toBeLessThan(0.001);
  });

  it("treats a balanced book as no imbalance, not a zero-sized one", () => {
    // Balanced is the state an auction is converging toward. It is good
    // news, and reads as the absence of a problem.
    expect(imbalanceOf(indic({ indicPrice: 150, imbalanceQty: 0 }))).toBeNull();
  });

  it("ignores a surplus with no side, which says nothing usable", () => {
    expect(imbalanceOf(indic({ indicPrice: 150, imbalanceQty: 100 }))).toBeNull();
  });

  it("has nothing to report before any frame arrives", () => {
    expect(imbalanceOf(undefined)).toBeNull();
  });
});

describe("indicativeVsLast", () => {
  it("measures where the auction is heading against the last print", () => {
    // The single most useful reading in a closing auction.
    expect(indicativeVsLast(indic({ indicPrice: 97 }), 100)).toBeCloseTo(-0.03);
  });

  it("is undefined rather than zero when either end is missing", () => {
    // Zero would read as "unchanged", which is a claim; undefined is the
    // absence of one.
    expect(indicativeVsLast(indic(), 100)).toBeUndefined();
    expect(indicativeVsLast(indic({ indicPrice: 97 }), undefined)).toBeUndefined();
    expect(indicativeVsLast(indic({ indicPrice: 97 }), 0)).toBeUndefined();
  });
});

describe("auctionSummary", () => {
  it("says no cross when the book would not trade", () => {
    expect(auctionSummary(indic())).toBe("no cross");
  });

  it("says balanced when it would trade cleanly", () => {
    expect(auctionSummary(indic({ indicPrice: 150 }))).toBe("balanced");
  });

  it("names the side and size of a surplus", () => {
    expect(
      auctionSummary(indic({ indicPrice: 150, indicQty: 900, imbalanceQty: 12_500, imbalanceSide: "SELL" })),
    ).toBe("SELL surplus 12,500");
  });

  it("has nothing to say with no frame, so the caller renders silence", () => {
    expect(auctionSummary(undefined)).toBeNull();
  });
});

describe("rankByImbalance", () => {
  it("ranks by ratio, not by raw share count", () => {
    // Otherwise the board becomes a ranking of which instruments happen to
    // trade in the largest size.
    const frames = {
      BIG: indic({
        sym: "BIG",
        indicPrice: 10,
        indicQty: 1_000_000,
        imbalanceQty: 10_000,
        imbalanceSide: "BUY",
      }),
      SMALL: indic({ sym: "SMALL", indicPrice: 10, indicQty: 100, imbalanceQty: 900, imbalanceSide: "SELL" }),
    };

    expect(rankByImbalance(frames).map((e) => e.sym)).toEqual(["SMALL", "BIG"]);
  });

  it("drops balanced symbols rather than ranking them at zero", () => {
    const frames = {
      AAPL: indic({ sym: "AAPL", indicPrice: 150, imbalanceQty: 0 }),
      MSFT: indic({ sym: "MSFT", indicPrice: 400, indicQty: 100, imbalanceQty: 50, imbalanceSide: "BUY" }),
    };

    expect(rankByImbalance(frames).map((e) => e.sym)).toEqual(["MSFT"]);
  });

  it("is empty when nothing is imbalanced", () => {
    expect(rankByImbalance({})).toEqual([]);
  });
});

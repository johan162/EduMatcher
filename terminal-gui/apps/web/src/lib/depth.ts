/**
 * Depth ladder shaping (design §14).
 *
 * The ladder as published is a list of independent price levels, but that is
 * not how it is read. What a viewer wants off a book is "how much is there
 * between here and four ticks away" — a running total from the touch outwards,
 * not a column of unrelated numbers to add up by eye. That running total is
 * also the honest thing to scale the bars against: per-level bars draw a book
 * with one fat level as deeper than one with five even ones, when the second
 * is the deeper book.
 *
 * Pure, and separate from the component, because the accumulation direction is
 * the one thing here that can be subtly wrong in a way a rendered table would
 * not make obvious.
 */

import type { DepthFrame, DepthLevel } from "@edumatcher/terminal-types";

export interface LadderRow {
  price: number;
  qty: number;
  /** Orders resting at this price — a count, never their identities (§14.2). */
  orders: number;
  /** This level plus every level nearer the touch. */
  cumulative: number;
  /**
   * Distance from this side's touch, as a fraction of the touch price.
   *
   * The ladder draws its levels evenly spaced whatever the prices are, so
   * bids at `100.00 / 99.99 / 99.98` render identically to bids at
   * `100.00 / 99.00 / 50.00` (T-L1). The cumulative column says how much
   * size is behind the touch; without this there is nothing saying how far
   * away it sits, and those are the two halves of the same question — a
   * hundred thousand shares two ticks down is a wall, and the same size ten
   * percent away is scenery.
   *
   * A fraction rather than ticks, so it is comparable between a 5.00
   * instrument and a 500.00 one. Zero at the touch itself. Absent when the
   * touch price is zero or missing, since a proportion of nothing says
   * nothing.
   */
  distance?: number;
}

export interface Ladder {
  bids: LadderRow[];
  asks: LadderRow[];
  bidTotal: number;
  askTotal: number;
  /**
   * The bid side's share of all resting size, 0..1. Above 0.5 is more size
   * bid than offered.
   *
   * Absent when the book is empty on both sides, which is a different state
   * from balanced — 0.5 there would report a symmetry that does not exist.
   */
  imbalance?: number;
  /** Largest cumulative on either side; the shared scale for both sets of bars. */
  peakCumulative: number;
  /** Rows to render — the deeper side's length, since sides need not match. */
  depth: number;
  /**
   * The widest distance on either side, as the shared scale for a gap
   * indicator. Zero when every level sits at the touch, or when there is
   * only one level a side.
   */
  peakDistance: number;
}

/**
 * Accumulate one side, in array order.
 *
 * The gateway publishes each side best-first, so array order *is* distance
 * from the touch and the running sum needs no sorting step. Re-sorting here
 * would only paper over a gateway that had stopped honouring that, and quietly
 * — better that such a book renders visibly wrong.
 */
function accumulate(levels: readonly DepthLevel[]): LadderRow[] {
  let running = 0;
  const touch = levels[0]?.[0];

  return levels.map(([price, qty, orders]) => {
    running += qty;
    const row: LadderRow = { price, qty, orders, cumulative: running };
    // Unsigned: which way it runs is already carried by which side of the
    // ladder it is on, and a reader comparing the two sides wants their
    // distances to be comparable rather than mirrored.
    if (touch !== undefined && touch > 0) row.distance = Math.abs(price - touch) / touch;
    return row;
  });
}

export function buildLadder(frame: DepthFrame | null): Ladder | null {
  if (!frame) return null;

  const bids = accumulate(frame.bids);
  const asks = accumulate(frame.asks);

  const bidTotal = bids.at(-1)?.cumulative ?? 0;
  const askTotal = asks.at(-1)?.cumulative ?? 0;
  const resting = bidTotal + askTotal;

  const ladder: Ladder = {
    bids,
    asks,
    bidTotal,
    askTotal,
    peakCumulative: Math.max(bidTotal, askTotal),
    depth: Math.max(bids.length, asks.length),
    peakDistance: Math.max(...[...bids, ...asks].map((row) => row.distance ?? 0), 0),
  };
  if (resting > 0) ladder.imbalance = bidTotal / resting;

  return ladder;
}

/**
 * Reading an auction while it is still running (design §12a, T-M1).
 *
 * For most of the day the interesting number is a traded price. During a
 * call phase there is no traded price — nothing matches until the uncross —
 * and the interesting numbers are instead *where the book would cross* and
 * *how far it is from balanced*. Those are what a participant needs in order
 * to supply the offsetting interest that resolves an imbalance, and they are
 * only useful while there is still time to act on them.
 *
 * The two moments a scheduled auction covers, the open and the close, are
 * where the largest volume of the day prints. Until this existed the
 * terminal could show a phase badge for them and nothing else.
 */

import type { AuctionIndicativeFrame } from "@edumatcher/terminal-types";

/** Which way the surplus runs, and by how much. */
export interface Imbalance {
  side: "BUY" | "SELL";
  qty: number;
  /**
   * Surplus as a fraction of total interest at the indicative price, 0..1.
   *
   * A raw quantity says nothing on its own: 500 shares unmatched against
   * 600 offered is a book in trouble, and against 6,000,000 it is noise.
   * The ratio is what makes two symbols comparable on one board.
   */
  ratio: number;
}

/**
 * The imbalance a frame describes, or `null` when the book is balanced.
 *
 * Balanced is a real, common and *good* state — it is what an auction is
 * converging toward — so it reads as the absence of an imbalance rather than
 * as a zero-sized one.
 */
export function imbalanceOf(frame: AuctionIndicativeFrame | undefined): Imbalance | null {
  if (frame === undefined) return null;
  if (frame.imbalanceQty <= 0) return null;
  if (frame.imbalanceSide !== "BUY" && frame.imbalanceSide !== "SELL") return null;

  const matched = frame.indicQty;
  const total = matched + frame.imbalanceQty;
  return {
    side: frame.imbalanceSide,
    qty: frame.imbalanceQty,
    ratio: total > 0 ? frame.imbalanceQty / total : 1,
  };
}

/**
 * Whether the book would cross at all.
 *
 * `false` is informative during a call phase and must not be rendered as a
 * price of zero: it means the bids and offers collected so far do not
 * overlap, so nothing would trade if the phase ended now.
 */
export function wouldCross(frame: AuctionIndicativeFrame | undefined): boolean {
  return frame?.indicPrice !== undefined;
}

/**
 * How the indicative compares with the last traded price, as a fraction.
 *
 * The single most useful reading during a closing auction: an indicative
 * three percent below the last print is the market telling you where the
 * close is heading. `undefined` when either end is missing, rather than a
 * zero that would read as "unchanged".
 */
export function indicativeVsLast(
  frame: AuctionIndicativeFrame | undefined,
  last: number | undefined,
): number | undefined {
  const indicative = frame?.indicPrice;
  if (indicative === undefined || last === undefined || last === 0) return undefined;
  return (indicative - last) / last;
}

/**
 * One line summarising an auction for a status strip or a row.
 *
 * Returns `null` when there is nothing to say, so a caller renders silence
 * rather than a row of dashes.
 */
export function auctionSummary(frame: AuctionIndicativeFrame | undefined): string | null {
  if (frame === undefined) return null;
  if (!wouldCross(frame)) return "no cross";

  const imbalance = imbalanceOf(frame);
  if (imbalance === null) return "balanced";
  return `${imbalance.side} surplus ${imbalance.qty.toLocaleString("en-US")}`;
}

/**
 * Symbols with the largest imbalance first, for a board that ranks them.
 *
 * By ratio rather than by raw quantity, for the reason given on
 * :attr:`Imbalance.ratio`: otherwise the board is a ranking of which
 * instruments happen to trade in the largest size.
 */
export function rankByImbalance(
  frames: Record<string, AuctionIndicativeFrame>,
  limit = 25,
): Array<{ sym: string; frame: AuctionIndicativeFrame; imbalance: Imbalance }> {
  return Object.entries(frames)
    .map(([sym, frame]) => ({ sym, frame, imbalance: imbalanceOf(frame) }))
    .filter(
      (entry): entry is { sym: string; frame: AuctionIndicativeFrame; imbalance: Imbalance } =>
        entry.imbalance !== null,
    )
    .sort((a, b) => b.imbalance.ratio - a.imbalance.ratio)
    .slice(0, limit);
}

/**
 * Level 2 depth ladder (design §14).
 *
 * Aggregated quantity per price level, never order-by-order — CALF
 * deliberately keeps per-order identity out of the public feed at every
 * version (§14.2), so the `#` column is a count of orders resting at that
 * price, not a list of them.
 *
 * Each `DEPTH` message carries a side's complete current ladder, so rendering
 * replaces wholesale and never patches a level in place (§14.4).
 *
 * Columns run outward from the price in both directions — `Cum | Qty | # |
 * Bid ‖ Ask | # | Qty | Cum` — so the two touch prices meet in the middle and
 * the cumulative totals, the figure read at a distance from the touch, sit at
 * the outer edges where the eye ends up.
 *
 * Rows are evenly spaced whatever the prices are, because a ladder that
 * spaced them by price would collapse to unreadable slivers the moment one
 * level sat far out. What that costs is any sense of *how far away* the size
 * is — `100.00 / 99.99 / 99.98` draws the same as `100.00 / 99.00 / 50.00`
 * — so the distance from the touch is stated as a figure instead, beside
 * each price, and a row whose gap is unusually wide is marked (T-L1).
 */

import clsx from "clsx";
import type { DepthFrame } from "@edumatcher/terminal-types";
import { buildLadder, type LadderRow } from "../lib/depth.js";
import { ABSENT, price, qty } from "../lib/format.js";

export function DepthLadder({
  frame,
  rowClass,
  decimals,
}: {
  frame: DepthFrame | null;
  rowClass: string;
  /** The ladder's symbol display precision, from CALF `REF=`. */
  decimals: number;
}) {
  const ladder = buildLadder(frame);

  if (!ladder) {
    return <p className="py-6 text-center text-sm text-fg-faint">Awaiting the first depth snapshot</p>;
  }

  // Rows beyond the gateway's configured LEVELS simply do not exist in the
  // feed — there is no "load more", since a client cannot request a deeper
  // ladder than the gateway publishes (§14.5).
  if (ladder.depth === 0) {
    return <p className="py-6 text-center text-sm text-fg-faint">No resting orders on either side</p>;
  }

  const { peakCumulative: peak } = ladder;

  return (
    <div>
      <table className="w-full text-left tabular">
        <thead>
          <tr className="border-b border-border text-[10px] uppercase tracking-widest text-fg-faint">
            <th className="py-1 text-right font-medium">Cum</th>
            <th className="py-1 text-right font-medium">Qty</th>
            <th className="py-1 text-right font-medium">#</th>
            <th className="py-1 text-right font-medium">Bid</th>
            <th className="py-1 text-right font-medium">%</th>
            <th className="w-1/4 py-1" />
            <th className="py-1 font-medium">%</th>
            <th className="py-1 font-medium">Ask</th>
            <th className="py-1 font-medium">#</th>
            <th className="py-1 font-medium">Qty</th>
            <th className="py-1 font-medium">Cum</th>
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: ladder.depth }, (_, i) => {
            const bid = ladder.bids[i];
            const ask = ladder.asks[i];
            return (
              <tr key={i} className={`border-b border-border-subtle ${rowClass}`}>
                <td className="text-right font-medium text-fg-subtle">
                  {bid ? qty(bid.cumulative) : ABSENT}
                </td>
                <td className="text-right">{bid ? qty(bid.qty) : ABSENT}</td>
                <td className="text-right text-fg-faint">{bid ? qty(bid.orders) : ABSENT}</td>
                <td className="text-right font-semibold text-up">
                  {bid ? price(bid.price, decimals) : ABSENT}
                </td>
                <Distance row={bid} peak={ladder.peakDistance} align="right" />
                {/*
                 * Bars are the cumulative staircase, not the per-level size:
                 * a book with one heavy level and a book with five even ones
                 * hold very different amounts, and only the running total
                 * draws them differently.
                 */}
                <td>
                  <div className="flex items-center gap-px">
                    <div className="flex flex-1 justify-end">
                      <Bar row={bid} peak={peak} tone="bg-up-bg" />
                    </div>
                    <div className="flex-1">
                      <Bar row={ask} peak={peak} tone="bg-down-bg" />
                    </div>
                  </div>
                </td>
                <Distance row={ask} peak={ladder.peakDistance} align="left" />
                <td className="font-semibold text-down">{ask ? price(ask.price, decimals) : ABSENT}</td>
                <td className="text-fg-faint">{ask ? qty(ask.orders) : ABSENT}</td>
                <td>{ask ? qty(ask.qty) : ABSENT}</td>
                <td className="font-medium text-fg-subtle">{ask ? qty(ask.cumulative) : ABSENT}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <Totals bidTotal={ladder.bidTotal} askTotal={ladder.askTotal} imbalance={ladder.imbalance} />
    </div>
  );
}

/**
 * How far this level sits from the touch, and whether that is a real gap.
 *
 * Shown as a percentage rather than in ticks so the figure means the same
 * on a 5.00 instrument and a 500.00 one. The touch itself reads `—` rather
 * than `0.00%`: it is the reference, not a measurement against it.
 *
 * A level more than halfway to the ladder's widest gap is marked, which is
 * the case the even spacing hides worst — a lone level far out beyond a
 * tight cluster looks like the next rung down.
 */
function Distance({
  row,
  peak,
  align,
}: {
  row: LadderRow | undefined;
  peak: number;
  align: "left" | "right";
}) {
  const distance = row?.distance;
  const far = distance !== undefined && peak > 0 && distance > peak / 2 && distance > 0;

  return (
    <td
      className={clsx(
        align === "right" ? "text-right" : "text-left",
        far ? "text-fg-subtle" : "text-fg-faint",
      )}
      title={far ? "Far from the touch — the rows above are not adjacent prices" : undefined}
    >
      {distance === undefined || distance === 0 ? ABSENT : `${(distance * 100).toFixed(2)}%`}
    </td>
  );
}

function Bar({ row, peak, tone }: { row: LadderRow | undefined; peak: number; tone: string }) {
  if (!row || peak <= 0) return null;
  return <span className={`block h-2 ${tone}`} style={{ width: `${(row.cumulative / peak) * 100}%` }} />;
}

/**
 * Resting size per side, and which way the book leans.
 *
 * Stated as a share of the whole rather than as a bid:ask ratio because the
 * ratio's useful range is unbounded in one direction and cramped in the other
 * — 0.2 and 5.0 are the same imbalance mirrored, and nobody reads them as
 * such. A percentage is symmetric around the middle, which is what the eye
 * wants from a lean.
 */
function Totals({
  bidTotal,
  askTotal,
  imbalance,
}: {
  bidTotal: number;
  askTotal: number;
  imbalance: number | undefined;
}) {
  const lean =
    imbalance === undefined
      ? ABSENT
      : `${Math.round(Math.max(imbalance, 1 - imbalance) * 100)}% ${imbalance >= 0.5 ? "bid" : "ask"}`;

  return (
    <div className="mt-2 flex items-baseline gap-4 border-t border-border pt-2 text-xs">
      <span className="text-up tabular">
        <span className="text-fg-faint">Bid depth </span>
        {qty(bidTotal)}
      </span>
      <span className="text-down tabular">
        <span className="text-fg-faint">Ask depth </span>
        {qty(askTotal)}
      </span>
      <span className="ml-auto tabular text-fg-subtle">
        <span className="text-fg-faint">Imbalance </span>
        {lean}
      </span>
    </div>
  );
}

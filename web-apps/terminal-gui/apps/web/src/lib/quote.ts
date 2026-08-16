/**
 * Figures derived from data the views already hold (design §8.4, §9.5).
 *
 * Nothing here needs a new subscription or a new endpoint: every input is a
 * field already on screen. They live in one place rather than in the two views
 * that want them, because "the spread" and "turnover" must mean exactly the
 * same thing on the Overview grid as they do on Symbol Detail — a grid that
 * ranked on a subtly different definition than the panel it links to would be
 * worse than not showing them at all.
 *
 * Every function returns `undefined` rather than `0` for an input it cannot
 * work from, matching `format.ts`: "no bid" and "a bid of zero" are different
 * claims, and that distinction has to survive all the way to the cell.
 */

/** Accepts the history rows' nullable columns as readily as the wire's optionals. */
type Maybe = number | null | undefined;

function value(input: Maybe): number | undefined {
  return input === null || input === undefined || !Number.isFinite(input) ? undefined : input;
}

/**
 * Absolute bid/ask spread.
 *
 * A crossed book yields a negative number and it is returned as-is. That state
 * is real — it is what a locked or crossed market looks like — and clamping it
 * to zero would hide the one case a viewer most needs to see.
 */
export function spread(bid: Maybe, ask: Maybe): number | undefined {
  const b = value(bid);
  const a = value(ask);
  return b === undefined || a === undefined ? undefined : a - b;
}

/**
 * Spread as basis points of the midpoint.
 *
 * The comparable form: 0.02 wide means something very different on a 5.00
 * stock than on a 500.00 one, so an absolute spread cannot be scanned down a
 * column of mixed price levels. Basis points can.
 */
export function spreadBps(bid: Maybe, ask: Maybe): number | undefined {
  const absolute = spread(bid, ask);
  const b = value(bid);
  const a = value(ask);
  if (absolute === undefined || b === undefined || a === undefined) return undefined;

  const mid = (b + a) / 2;
  return mid > 0 ? (absolute / mid) * 10_000 : undefined;
}

/**
 * Value traded this session — shares times the session VWAP.
 *
 * Ranking on share count alone flatters whatever is cheapest: a hundred
 * thousand shares of a 2.00 instrument is a smaller event than ten thousand of
 * a 200.00 one, and only the notional says so.
 *
 * **This is a reconstruction, not a reported figure** (T-L4). The exchange
 * publishes no turnover; `volume × vwap` recovers it because VWAP is by
 * definition the notional divided by the volume, so multiplying the two
 * cancels back. That identity is exact only while VWAP is unrounded, and
 * pm-stats rounds it to the symbol's tick precision before publishing — so
 * this figure will not tie exactly to a sum over the Trade Tape, and the
 * error grows with the number of prints behind it.
 *
 * Accurate enough for what it is used for: ranking symbols against each
 * other on the Movers board, and giving a sense of scale on the Overview.
 * Not accurate enough to reconcile against, and nothing on screen should
 * invite anyone to try.
 */
export function turnover(volume: Maybe, vwap: Maybe): number | undefined {
  const shares = value(volume);
  if (shares === undefined) return undefined;
  // Nothing traded is a known zero, not an unknown — and pm-stats leaves VWAP
  // null in exactly that case, so requiring it here would blank the column for
  // every quiet symbol.
  if (shares === 0) return 0;

  const average = value(vwap);
  return average === undefined ? undefined : shares * average;
}

/** Mean shares per print — the quick read on whether the flow is retail-sized or blocky. */
export function avgTradeSize(volume: Maybe, tradeCount: Maybe): number | undefined {
  const shares = value(volume);
  const trades = value(tradeCount);
  return shares === undefined || trades === undefined || trades <= 0 ? undefined : shares / trades;
}

/**
 * Where `last` sits in the session's range, as a 0..1 position for a marker.
 *
 * Clamped to the ends so a last price outside the recorded high/low — which a
 * live tick briefly is, before pm-stats recomputes the row — still renders on
 * the bar rather than escaping it. A zero-width range centres, since there is
 * no position to report.
 */
export function rangePosition(low: Maybe, high: Maybe, last: Maybe): number | undefined {
  const bottom = value(low);
  const top = value(high);
  const at = value(last);
  if (bottom === undefined || top === undefined || at === undefined) return undefined;
  if (top <= bottom) return 0.5;
  return Math.min(1, Math.max(0, (at - bottom) / (top - bottom)));
}

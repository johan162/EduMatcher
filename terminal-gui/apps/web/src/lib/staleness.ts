/**
 * How long ago a row last printed, and whether that is long enough to say so.
 *
 * A grid renders a price from three hours ago exactly like one from three
 * seconds ago — same digits, same colour, same conviction. On an exchange
 * where most symbols are quiet most of the time that is actively misleading:
 * a green +2.00% that has not moved since the morning reads as a live market.
 * Marking the row is the honest alternative to either hiding it or letting it
 * pass for fresh.
 */

import { useEffect, useState } from "react";

/**
 * Silence after which a row is shown as stale.
 *
 * Five minutes is long enough that an ordinarily thin book is not permanently
 * greyed out, and short enough that a symbol which has genuinely stopped
 * trading says so while the session is still running.
 */
export const STALE_AFTER_SEC = 300;

/**
 * True when the last print is old enough to flag.
 *
 * A symbol that has not printed at all this session is *not* stale — it is
 * untraded, which the empty price and change columns already say. Calling it
 * stale would imply it once had a fresh price that has since aged.
 */
export function isStale(lastTradeTs: string | undefined, now: number): boolean {
  if (lastTradeTs === undefined) return false;

  const printed = new Date(lastTradeTs).getTime();
  if (Number.isNaN(printed)) return false;

  return now - printed > STALE_AFTER_SEC * 1000;
}

/**
 * A clock that ticks on its own interval, for anything whose rendering depends
 * on the passage of time rather than on arriving data.
 *
 * Deliberately coarse: staleness is a five-minute judgement, and re-rendering
 * a full grid every second to maintain it would cost far more than it tells
 * anyone.
 */
export function useNow(intervalMs = 15_000): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);

  return now;
}

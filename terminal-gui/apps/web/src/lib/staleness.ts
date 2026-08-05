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
 * Default silence after which a row is shown as stale.
 *
 * A *default*, not a rule (T-L3). Five minutes suits an ordinarily liquid
 * book: long enough not to grey the board out, short enough that a symbol
 * which has genuinely stopped trading says so while the session runs. On a
 * thin classroom book it can be badly wrong in the direction that matters —
 * every row faded, permanently, at which point the mark carries no
 * information at all. The value in force is `usePrefsStore.staleAfterSec`,
 * and the grid states it on screen so it is never a mystery.
 */
export const STALE_AFTER_SEC = 300;

/**
 * True when the last print is old enough to flag.
 *
 * A symbol that has not printed at all this session is *not* stale — it is
 * untraded, which the empty price and change columns already say. Calling it
 * stale would imply it once had a fresh price that has since aged.
 */
export function isStale(
  lastTradeTs: string | undefined,
  now: number,
  afterSec: number = STALE_AFTER_SEC,
): boolean {
  if (lastTradeTs === undefined) return false;
  // Infinity turns the marking off entirely, for a session so quiet that no
  // threshold discriminates between symbols.
  if (!Number.isFinite(afterSec)) return false;

  const printed = new Date(lastTradeTs).getTime();
  if (Number.isNaN(printed)) return false;

  return now - printed > afterSec * 1000;
}

/**
 * A threshold as words, for a control or a footnote.
 *
 * Stated on screen because an arbitrary number that nobody can see is the
 * thing T-L3 objects to: a faded row is only readable if the reader knows
 * what "faded" means here.
 */
export function staleLabel(afterSec: number): string {
  if (!Number.isFinite(afterSec)) return "off";
  if (afterSec < 60) return `${afterSec}s`;
  if (afterSec < 3600) return `${Math.round(afterSec / 60)} min`;
  return `${Math.round(afterSec / 3600)} h`;
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

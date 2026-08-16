/**
 * How old the figures on screen actually are, per source.
 *
 * A row on the Overview looks like one reading taken at one instant. It is
 * not: `last`/`bid`/`ask` arrive on CALF sub-second, `open`/`volume`/
 * `turnover` come from a ten-second history poll, and the previous close
 * behind every percentage is on a five-minute poll of its own. Three clocks,
 * rendered in the same font, on the same line, with nothing to say so
 * (§ T-M4).
 *
 * The honest fix is not to hide the difference but to make each age
 * available, so a reader can tell "the market is quiet" from "this screen
 * stopped being told anything twenty minutes ago" — which look identical
 * today and mean opposite things.
 */

/** The three independent feeds behind one Overview row. */
export type DataSource = "live" | "daily" | "prevClose";

export const SOURCE_LABEL: Record<DataSource, string> = {
  live: "CALF live",
  daily: "session totals",
  prevClose: "previous close",
};

/**
 * What each source is expected to refresh at, in seconds.
 *
 * Used to judge whether an age is ordinary or worth flagging — an age is
 * only meaningful against the cadence it should have kept. The live feed has
 * no cadence of its own: a quiet book genuinely sends nothing, which is why
 * its threshold is a judgement about attention rather than about the poll.
 */
export const SOURCE_INTERVAL_SEC: Record<DataSource, number> = {
  live: 60,
  daily: 10,
  prevClose: 300,
};

/**
 * Seconds since a source last delivered, or `null` if it never has.
 *
 * Null is not zero: "nothing has arrived" and "something arrived just now"
 * are opposite readings and must not render the same.
 */
export function ageSec(at: number | null | undefined, now: number): number | null {
  if (at === null || at === undefined) return null;
  return Math.max(0, Math.round((now - at) / 1000));
}

/**
 * A compact age for a status strip: `4s`, `2m`, `1h`.
 *
 * Coarsens as it grows because precision stops mattering: the difference
 * between four and five seconds is worth reading, the difference between
 * sixty-one and sixty-two minutes is not.
 */
export function formatAge(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h`;
}

/**
 * Whether an age is long enough to be worth flagging for that source.
 *
 * Two intervals, not one: a single missed poll is ordinary jitter and
 * flagging it would train the reader to ignore the indicator, which is worse
 * than not having it.
 */
export function isLate(source: DataSource, seconds: number | null): boolean {
  if (seconds === null) return false;
  return seconds > SOURCE_INTERVAL_SEC[source] * 2;
}

/**
 * The status-strip reading for the live feed.
 *
 * Deliberately says "no ticks yet" rather than an age when nothing has
 * arrived — an age of zero would claim a tick that never happened, and on a
 * screen that has just connected that is the difference between "working"
 * and "connected to something silent".
 */
export function liveTickLabel(seconds: number | null): string {
  if (seconds === null) return "no ticks yet";
  return `last tick ${formatAge(seconds)} ago`;
}

/**
 * Display formatting.
 *
 * Everything here returns an em dash for absent values rather than "0" or
 * "null". On a market-data screen the difference between "no bid" and "a bid
 * of zero" is the difference between a halted book and a broken one, and the
 * type layer preserves that distinction all the way from the CALF wire
 * (`decodeTop` returns `undefined`, never `NaN`) — so the last step must not
 * throw it away.
 */

export const ABSENT = "—";

export function price(value: number | undefined | null, decimals = 2): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return ABSENT;
  return value.toFixed(decimals);
}

export function qty(value: number | undefined | null): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return ABSENT;
  return value.toLocaleString("en-US");
}

/**
 * A large figure abbreviated to three significant digits — `27.6M`, `1.4B`.
 *
 * For turnover, where the exact notional is never the point and the full digit
 * string would be the widest column on the grid. Share counts keep `qty()`'s
 * grouped digits: those are compared against each other and against print
 * sizes on the tape, where losing the last three digits would matter.
 */
export function compact(input: number | undefined | null): string {
  if (input === undefined || input === null || !Number.isFinite(input)) return ABSENT;

  const magnitude = Math.abs(input);
  for (const [limit, suffix] of [
    [1e12, "T"],
    [1e9, "B"],
    [1e6, "M"],
    [1e3, "K"],
  ] as const) {
    if (magnitude >= limit) {
      const scaled = input / limit;
      // Three significant digits either way: 27.6M, but 274M rather than 274.3M.
      return `${scaled.toFixed(Math.abs(scaled) >= 100 ? 0 : 1)}${suffix}`;
    }
  }
  return input.toFixed(0);
}

/** `HH:MM:SS` in UTC — the exchange's own clock, not the viewer's. */
export function clockUtc(iso: string | undefined | null): string {
  if (!iso) return ABSENT;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return ABSENT;
  return date.toISOString().slice(11, 19);
}

/**
 * A halt's `RESUMEAT` rendered as wall-clock plus a countdown.
 *
 * Returns just the clock time once the moment has passed: an auction-resume
 * halt often sits a little past its scheduled time while the uncross runs,
 * and showing "-00:00:14" would read as an error rather than as normal.
 */
export function resumeAt(iso: string | undefined, now = Date.now()): string {
  if (!iso) return ABSENT;
  const target = new Date(iso).getTime();
  if (Number.isNaN(target)) return ABSENT;

  const clock = clockUtc(iso);
  const remainingSec = Math.round((target - now) / 1000);
  if (remainingSec <= 0) return clock;

  const mm = String(Math.floor(remainingSec / 60)).padStart(2, "0");
  const ss = String(remainingSec % 60).padStart(2, "0");
  return `${clock} (${mm}:${ss})`;
}

/** How long a halt has been in effect, as `Xm Ys`. */
export function elapsed(iso: string | undefined | null, now = Date.now()): string {
  if (!iso) return ABSENT;
  const started = new Date(iso).getTime();
  if (Number.isNaN(started)) return ABSENT;

  const totalSec = Math.max(0, Math.round((now - started) / 1000));
  const minutes = Math.floor(totalSec / 60);
  return minutes > 0 ? `${minutes}m ${totalSec % 60}s` : `${totalSec}s`;
}

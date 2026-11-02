/**
 * Time-axis helpers for the Symbol Detail chart.
 *
 * Lightweight Charts treats numeric times as UTC and renders them as such, so
 * the bars stay true epoch seconds and the axis/crosshair labels are formatted
 * in the exchange's session timezone instead. A null timezone (before
 * bootstrap) falls back to the browser's.
 */
import { TickMarkType, type Time } from "lightweight-charts";

const dayFormat = new Map<string, Intl.DateTimeFormat>();

function formatter(timezone: string | null, opts: Intl.DateTimeFormatOptions) {
  const key = `${timezone ?? ""}|${JSON.stringify(opts)}`;
  let f = dayFormat.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat("en-GB", { ...opts, timeZone: timezone ?? undefined });
    dayFormat.set(key, f);
  }
  return f;
}

/** Calendar date `YYYY-MM-DD` of an epoch-seconds instant in `timezone`. */
export function sessionDay(epochSec: number, timezone: string | null): string {
  const parts = formatter(timezone, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(epochSec * 1000));
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** Crosshair and tick-mark label formatters for the chart's time scale. */
export function timeFormatters(timezone: string | null) {
  const at = (time: number, opts: Intl.DateTimeFormatOptions) =>
    formatter(timezone, { hourCycle: "h23", ...opts }).format(new Date(time * 1000));
  return {
    crosshair: (time: Time): string => {
      if (typeof time !== "number") return String(time);
      return `${at(time, { year: "numeric", month: "2-digit", day: "2-digit" })} ${at(time, {
        hour: "2-digit",
        minute: "2-digit",
      })}`;
    },
    tick: (time: Time, type: TickMarkType): string | null => {
      if (typeof time !== "number") return null;
      switch (type) {
        case TickMarkType.Year:
          return at(time, { year: "numeric" });
        case TickMarkType.Month:
          return at(time, { month: "short" });
        case TickMarkType.DayOfMonth:
          return at(time, { day: "numeric", month: "short" });
        case TickMarkType.Time:
          return at(time, { hour: "2-digit", minute: "2-digit" });
        default:
          return at(time, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      }
    },
  };
}

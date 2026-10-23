/**
 * Time-axis labels in the exchange's session timezone.
 *
 * Lightweight Charts renders every timestamp as UTC. These options re-label
 * the axis ticks and the crosshair in the session timezone instead. Daily bars
 * sit at midnight UTC and stand for a date, not an instant, so they keep their
 * UTC date rather than slide to the previous day in a western timezone.
 */

import { TickMarkType, type ChartOptions, type DeepPartial, type Time } from "lightweight-charts";

const isDaily = (seconds: number) => seconds % 86_400 === 0;

function fmt(seconds: number, timeZone: string, options: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat("en-GB", { timeZone, hourCycle: "h23", ...options }).format(seconds * 1000);
}

export function sessionTimeOptions(timeZone: string): {
  localization: DeepPartial<ChartOptions["localization"]>;
  tickMarkFormatter: (time: Time, type: TickMarkType) => string;
} {
  return {
    localization: {
      timeFormatter: (time: Time) => {
        const s = time as number;
        return isDaily(s)
          ? fmt(s, "UTC", { day: "2-digit", month: "short", year: "numeric" })
          : fmt(s, timeZone, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
      },
    },
    tickMarkFormatter: (time: Time, type: TickMarkType) => {
      const s = time as number;
      switch (type) {
        case TickMarkType.Year:
          return fmt(s, "UTC", { year: "numeric" });
        case TickMarkType.Month:
          return fmt(s, "UTC", { month: "short" });
        case TickMarkType.DayOfMonth:
          return fmt(s, isDaily(s) ? "UTC" : timeZone, { day: "numeric" });
        default:
          return fmt(s, timeZone, { hour: "2-digit", minute: "2-digit" });
      }
    },
  };
}

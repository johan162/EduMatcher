/**
 * `pm-api-gwy` `GET /api/v1/reference/schedule`, passed through unmodified by
 * the bridge: the venue's weekly session table and holiday calendar
 * (`ReferenceSchedule` / `WeeklySchedule` in `spec/messages/system.yaml`).
 */

/** One day's five wall-clock boundaries in the session timezone, `HH:MM[:SS]`. */
export interface SessionTimes {
  pre_open: string | null;
  opening_auction_start: string | null;
  continuous_start: string | null;
  closing_auction_start: string | null;
  closing_auction_end: string | null;
}

export interface Holiday {
  /** ISO-8601 calendar date in the session timezone. */
  date: string;
  name: string;
}

export type DayKey = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

/** Each day slot is null when the exchange is CLOSED that day. */
export type WeeklySchedule = Record<DayKey, SessionTimes | null> & {
  /** Applied instead of the weekday's entry on a bank holiday. */
  holidays: SessionTimes | null;
  /** Ascending, from the day the engine built the record through a year on. */
  upcoming_holidays: Holiday[];
};

export interface ReferenceSchedule {
  sessions_enabled: boolean;
  country: string | null;
  /** Null when no `schedule:` block is configured. */
  schedule: WeeklySchedule | null;
}

/**
 * The exchange session timezone on the bridge (design §11.2).
 *
 * Every time the bridge stores or sends is UTC (ISO-8601 or epoch ms); the
 * session timezone only decides where a bucket starts, so an hourly bar
 * covers 09:00–10:00 on the exchange's clock even where the zone is not a
 * whole number of hours from UTC (Asia/Kolkata, +05:30).
 */

/** Whether this Node's ICU knows the IANA name. */
export function knownTimeZone(tz: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

/** `tz`'s offset from UTC at `ms`, in seconds, east positive. */
export function utcOffsetSec(tz: string, ms: number): number {
  const name =
    new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "longOffset" })
      .formatToParts(ms)
      .find((p) => p.type === "timeZoneName")?.value ?? "GMT";
  const m = /^GMT([+-])(\d{2}):(\d{2})$/.exec(name);
  if (!m) return 0; // "GMT": UTC itself
  const sec = Number(m[2]) * 3600 + Number(m[3]) * 60;
  return m[1] === "-" ? -sec : sec;
}

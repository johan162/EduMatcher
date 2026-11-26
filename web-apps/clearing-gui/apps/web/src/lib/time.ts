/**
 * Timestamps, on the venue's clock.
 *
 * Every `*_ns` field is epoch nanoseconds. JSON numbers are doubles, so such a
 * value arrives rounded to a few hundred nanoseconds: fine for display, never
 * to be compared for equality.
 *
 * Times are shown in the venue's session timezone (`session_timezone` of
 * `GET /api/v1/session`, held by `useVenueTimeZoneStore`), as terminal-gui,
 * dash-gui and log-gui do, so they agree with the trading days (`trade_date`)
 * the server resolves in the same zone. Every time carries its date and its
 * zone. Until the zone is known -- or when the session request fails, or the
 * browser does not know the zone -- times are UTC and labelled so; a time is
 * never shown in an unnamed zone.
 */

const DASH = "—";

const FIELDS: Intl.DateTimeFormatOptions = {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
  timeZoneName: "short",
};

const formatters = new Map<string, Intl.DateTimeFormat[]>();

/**
 * en-GB and en-US formatters for `zone`, or none when the browser does not
 * know it. Each locale abbreviates different zones (en-GB: CET, en-US: EDT);
 * the other gives a "GMT+1" offset.
 */
function formattersFor(zone: string): Intl.DateTimeFormat[] {
  let found = formatters.get(zone);
  if (!found) {
    try {
      found = ["en-GB", "en-US"].map((locale) => new Intl.DateTimeFormat(locale, { ...FIELDS, timeZone: zone }));
    } catch {
      found = [];
    }
    formatters.set(zone, found);
  }
  return found;
}

function partsOf(formatter: Intl.DateTimeFormat, ms: number): Record<string, string> {
  return Object.fromEntries(formatter.formatToParts(ms).map((p) => [p.type, p.value]));
}

/** A zone abbreviation rather than a "GMT+1" offset (plain "GMT" is a name). */
function isAbbreviation(name: string): boolean {
  return !/^(GMT|UTC)[+-]/.test(name);
}

function formatMs(ms: number, zone: string | null): string {
  const [first, second] = zone ? formattersFor(zone) : [];
  if (!first || !second) {
    const iso = new Date(ms).toISOString();
    return `${iso.slice(0, 10)} ${iso.slice(11, 19)} UTC`;
  }
  const p = partsOf(first, ms);
  let name = p["timeZoneName"] ?? zone!;
  if (!isAbbreviation(name)) {
    const other = partsOf(second, ms)["timeZoneName"];
    if (other && isAbbreviation(other)) name = other;
  }
  return `${p["year"]}-${p["month"]}-${p["day"]} ${p["hour"]}:${p["minute"]}:${p["second"]} ${name}`;
}

/** `2026-11-03 10:00:01 CET` in `zone`, labelled UTC without one, or a dash for a missing time. */
export function formatNs(ns: number | null | undefined, zone: string | null): string {
  if (ns === null || ns === undefined) return DASH;
  return formatMs(Math.floor(ns / 1_000_000), zone);
}

/** An ISO-8601 instant (e.g. pm-eod's `finished_at`), formatted as `formatNs`. */
export function formatIso(iso: string, zone: string | null): string {
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? DASH : formatMs(ms, zone);
}

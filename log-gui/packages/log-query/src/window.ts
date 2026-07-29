/** Parses the small set of allow-listed window strings used across `/api/stats/*`. */

const WINDOW_SECONDS: Record<string, number> = {
  "5m": 5 * 60,
  "15m": 15 * 60,
  "1h": 60 * 60,
  "6h": 6 * 60 * 60,
  "24h": 24 * 60 * 60,
};

export function windowToIsoFrom(window: string, now: Date = new Date()): string {
  const seconds = WINDOW_SECONDS[window] ?? WINDOW_SECONDS["1h"];
  return new Date(now.getTime() - seconds * 1000).toISOString().replace(/\.\d+Z$/, "Z");
}

export function isValidWindow(window: string): boolean {
  return window in WINDOW_SECONDS;
}

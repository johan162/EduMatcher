/**
 * Epoch nanoseconds travel as decimal strings (design §3.2): beyond a
 * JavaScript number's exact range. Charts draw milliseconds (a float keeps
 * sub-millisecond detail there); the URL and the API keep the exact string.
 */
export function nsToMs(ns: string): number {
  const big = BigInt(ns);
  return Number(big / 1_000_000n) + Number(big % 1_000_000n) / 1e6;
}

export function msToNs(ms: number): string {
  const whole = Math.floor(ms);
  return (BigInt(whole) * 1_000_000n + BigInt(Math.round((ms - whole) * 1e6))).toString();
}

/** `07:00:56.001` (UTC), for axis labels and lists. */
export function clockText(ms: number): string {
  return new Date(ms).toISOString().slice(11, 23);
}

/** A price in ticks at the recorded scale: 9985, 2 -> "99.85"; no scale -> "9985 ticks". */
export function priceText(ticks: number, decimals: number | null): string {
  if (decimals === null) return `${ticks} ticks`;
  const sign = ticks < 0 ? "-" : "";
  const digits = String(Math.abs(ticks)).padStart(decimals + 1, "0");
  return decimals === 0 ? `${sign}${digits}` : `${sign}${digits.slice(0, -decimals)}.${digits.slice(-decimals)}`;
}

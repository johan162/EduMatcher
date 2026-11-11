/**
 * Money formatting with the units kept apart.
 *
 * The clearing API returns two kinds of money, and they must never meet:
 *
 * - **Ticks** (`*_ticks` fields): integers (or weighted averages) in ticks of
 *   one symbol's `tick_decimals`. One tick of a 4-decimal symbol is a
 *   hundredth of a tick of a 2-decimal one, so a tick value is meaningless
 *   without its row's precision and ticks of different rows cannot be added.
 * - **Minor units** (`*_minor` fields): EOD settlement amounts, integers in
 *   minor units of the display currency, always 2 decimals (1234 = 12.34).
 *
 * The schemas brand each field with its unit (`Ticks`, `Minor`), so passing a
 * minor-unit amount to `formatTicks` -- or a bare number -- is a type error.
 * Display-currency totals the API has already summed per row (participant
 * and venue P&L) are plain numbers and go through `formatCurrency`.
 */

export type Ticks = number & { readonly __unit: "ticks" };
export type Minor = number & { readonly __unit: "minor" };

const DASH = "—";

/** `tick_decimals` as the engine allows it: an integer 0..9. */
function checkPrecision(tickDecimals: number): void {
  if (!Number.isInteger(tickDecimals) || tickDecimals < 0 || tickDecimals > 9) {
    throw new RangeError(`tick_decimals must be an integer 0..9, got ${String(tickDecimals)}`);
  }
}

function fixed(value: number, decimals: number): string {
  // -0.0001 at 2 decimals rounds to zero: show "0.00", not "-0.00".
  const shown = Number(value.toFixed(decimals)) === 0 ? 0 : value;
  return shown.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** A tick value in display currency, per its own row's precision. */
export function ticksToDisplay(ticks: Ticks, tickDecimals: number): number {
  checkPrecision(tickDecimals);
  return ticks / 10 ** tickDecimals;
}

/**
 * A tick value as display text with the symbol's own number of decimals, plus
 * `extraDecimals` for averages (an average cost of 18733.33 ticks at 2 decimals
 * reads 187.3333 with 2 extra). `null` (no mark yet, say) is a dash, not 0.
 */
export function formatTicks(ticks: Ticks | null, tickDecimals: number, extraDecimals = 0): string {
  checkPrecision(tickDecimals);
  if (ticks === null) return DASH;
  return fixed(ticksToDisplay(ticks, tickDecimals), tickDecimals + extraDecimals);
}

/**
 * An EOD minor-unit amount, exactly: integer arithmetic, no floating division,
 * so 1 minor unit is "0.01" and never "0.010000000000000002".
 */
export function formatMinor(minor: Minor): string {
  if (!Number.isInteger(minor)) {
    throw new RangeError(`a minor-unit amount must be an integer, got ${String(minor)}`);
  }
  const sign = minor < 0 ? "-" : "";
  const abs = Math.abs(minor);
  const whole = Math.floor(abs / 100);
  const cents = String(abs % 100).padStart(2, "0");
  return `${sign}${whole.toLocaleString("en-US")}.${cents}`;
}

/** A display-currency amount the API already converted (cross-symbol totals). */
export function formatCurrency(value: number | null): string {
  return value === null ? DASH : fixed(value, 2);
}

/** A share quantity: signed, with thousands separators. */
export function formatQty(qty: number | null): string {
  return qty === null ? DASH : qty.toLocaleString("en-US");
}

/** Text colour for a signed amount: green up, red down, neutral at zero. */
export function signClass(value: number | null): string {
  if (value === null || value === 0) return "";
  return value > 0 ? "text-bid" : "text-ask";
}

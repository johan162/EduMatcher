/**
 * Per-symbol display precision, for the views that render prices.
 *
 * Every price on every screen used to be rendered at two decimals, because
 * that is `price()`'s default and no call site overrode it. `tick_decimals` is
 * per-symbol and configurable, so a symbol quoted to four decimals was
 * silently rounded — its last price, its spread, its basis-point spread, its
 * OHLC and its range bar all quietly wrong, on every view at once.
 *
 * The precision now arrives on CALF `REF=` (see `packages/calf-protocol`) and
 * reaches the browser on the bridge's `hello` frame.
 */

import { useCallback } from "react";
import { DEFAULT_TICK_DECIMALS } from "@edumatcher/terminal-types";
import { useLiveStore } from "../store/useLiveStore.js";

/**
 * Returns a lookup from symbol to decimal places.
 *
 * A function rather than the raw map because most call sites format several
 * prices for one symbol and the fallback should be applied in exactly one
 * place. Symbols the gateway did not describe — an older gateway with no
 * `REF=` at all, or an instrument first seen on the engine bus — resolve to
 * the same default the rest of the exchange assumes for them.
 */
export function useTickDecimals(): (sym: string) => number {
  const decimals = useLiveStore((s) => s.tickDecimals);
  return useCallback((sym: string) => decimals[sym] ?? DEFAULT_TICK_DECIMALS, [decimals]);
}

/** The precision for one symbol, where a component only ever renders that one. */
export function useSymbolDecimals(sym: string): number {
  return useLiveStore((s) => s.tickDecimals[sym] ?? DEFAULT_TICK_DECIMALS);
}

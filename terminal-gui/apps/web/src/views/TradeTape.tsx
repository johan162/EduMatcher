/**
 * Trade Tape / Time & Sales (design §11).
 *
 * Every print on the exchange, newest first. The bridge already holds a single
 * `SUB|CH=TRADE|SYM=*` wildcard subscription covering every symbol (§6.4), so
 * this view opens no subscription of its own and the symbol filter narrows
 * what is *shown* rather than what is received — switching filters is
 * instant and costs the gateway nothing.
 */

import { useMemo, useState } from "react";
import clsx from "clsx";
import type { GapFrame, TradeFrame } from "@edumatcher/terminal-types";
import { useLiveStore } from "../store/useLiveStore.js";
import { clockUtc, price, qty } from "../lib/format.js";
import { useTickDecimals } from "../lib/precision.js";

/** Rows rendered at once. The buffer holds more; the eye takes far less. */
const VISIBLE_ROWS = 200;

const ALL = "__all__";

export type TapeRow = TradeFrame | GapFrame;

export function filterTape(
  trades: readonly TradeFrame[],
  symbol: string,
  limit = VISIBLE_ROWS,
): TradeFrame[] {
  const rows = symbol === ALL ? trades : trades.filter((t) => t.sym === symbol);
  return rows.slice(0, limit);
}

/**
 * Interleave the tape's prints with the holes the bridge could not close.
 *
 * Both arrays are independently newest-first, but a gap and the trades either
 * side of it arrive as separate frames, so simple concatenation would put
 * every gap either before or after every print rather than where it actually
 * happened. Timestamp order is the only thing both series share (T-H4/T-H5) —
 * `seq` is not comparable between them, since a `GapFrame` has none of its
 * own. Ties go to the print, so a gap sorts just below the message that
 * revealed it, which is the side of it the hole is on.
 *
 * Merged rather than concatenated-and-sorted because both inputs already carry
 * the order wanted: the store holds up to `TRADE_BUFFER_MAX` prints and only
 * `limit` rows are ever shown, so this walks `limit` entries instead of
 * sorting five hundred to discard three hundred of them. Gaps are rare enough
 * that the empty case — the overwhelmingly common one — does no work at all.
 */
export function mergeTapeRows(
  trades: readonly TradeFrame[],
  gaps: readonly GapFrame[],
  symbol: string,
  limit = VISIBLE_ROWS,
): TapeRow[] {
  const printRows = filterTape(trades, symbol, limit);
  const gapRows = symbol === ALL ? gaps : gaps.filter((g) => g.sym === symbol);
  if (gapRows.length === 0) return printRows;

  const rows: TapeRow[] = [];
  let i = 0;
  let j = 0;
  while (rows.length < limit) {
    const print = printRows[i];
    const gap = gapRows[j];
    if (print !== undefined && (gap === undefined || print.ts >= gap.ts)) {
      rows.push(print);
      i += 1;
    } else if (gap !== undefined) {
      rows.push(gap);
      j += 1;
    } else {
      break;
    }
  }
  return rows;
}

export function TradeTapeView() {
  const trades = useLiveStore((s) => s.trades);
  const tradeGaps = useLiveStore((s) => s.tradeGaps);
  const symbols = useLiveStore((s) => s.symbols);
  const [symbol, setSymbol] = useState(ALL);
  const [paused, setPaused] = useState(false);
  // Snapshot taken at the moment of pausing. Live updates keep arriving into
  // the store — pausing freezes the reading, it does not drop data, so
  // resuming shows the current tape rather than a gap.
  const [frozen, setFrozen] = useState<{ trades: TradeFrame[]; gaps: GapFrame[] }>({
    trades: [],
    gaps: [],
  });
  // Per row, not per view: the unfiltered tape mixes every instrument on the
  // exchange, and they do not share a tick size.
  const tickDecimals = useTickDecimals();

  // Selected as two values rather than one `paused ? frozen : {trades, gaps}`
  // object: a literal is a fresh reference on every render, and this view
  // re-renders on every print, so the memo below would never once hit.
  const visibleTrades = paused ? frozen.trades : trades;
  const visibleGaps = paused ? frozen.gaps : tradeGaps;
  const rows = useMemo(
    () => mergeTapeRows(visibleTrades, visibleGaps, symbol),
    [visibleTrades, visibleGaps, symbol],
  );

  function togglePause(): void {
    if (paused) {
      setPaused(false);
      setFrozen({ trades: [], gaps: [] });
    } else {
      setFrozen({ trades, gaps: tradeGaps });
      setPaused(true);
    }
  }

  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Trade tape</h1>
        <label className="flex items-center gap-1.5 text-sm">
          <span className="text-fg-subtle">Symbol</span>
          <select
            aria-label="Filter tape by symbol"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="rounded border border-border bg-surface px-2 py-1"
          >
            <option value={ALL}>All</option>
            {symbols.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={togglePause}
          aria-pressed={paused}
          className={clsx(
            "rounded border px-3 py-1 text-sm",
            paused ? "border-halt bg-halt-bg text-warning" : "border-border hover:bg-muted",
          )}
        >
          {paused ? "Resume" : "Pause"}
        </button>
        <span className="ml-auto text-sm text-fg-subtle tabular">
          {rows.length} shown
          {paused && " · paused"}
        </span>
      </header>

      <div className="overflow-hidden rounded border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left text-xs uppercase text-fg-subtle">
            <tr>
              <th className="px-3 py-2">Time</th>
              <th className="px-3 py-2">Symbol</th>
              <th className="px-3 py-2 text-right">Price</th>
              <th className="px-3 py-2 text-right">Qty</th>
              <th className="px-3 py-2">Side</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) =>
              t.type === "gap" ? (
                // `bg-halt-bg`, not `bg-warning/10`: `warning` resolves to a
                // bare `var(--halt)`, and Tailwind cannot apply an alpha
                // modifier to one — the class compiles to nothing at all and
                // the row loses its tint silently (same failure as T-L2).
                // `halt-bg` is the token that already carries that colour at
                // that opacity.
                <tr key={`gap-${t.ch}-${t.sym}-${t.ts}`} className="border-t border-border bg-halt-bg">
                  <td className="px-3 py-1 tabular text-warning">{clockUtc(t.ts)}</td>
                  <td className="px-3 py-1 font-medium text-warning">{t.sym}</td>
                  <td colSpan={3} className="px-3 py-1 text-warning">
                    {/*
                     * A hole, not a print: the bridge missed one or more
                     * messages here and could not replay them, so nothing is
                     * claimed about what happened in this window rather than
                     * one side of it being silently omitted (T-H4/T-H5).
                     */}
                    gap in the tape — some prints for {t.sym} were missed
                  </td>
                </tr>
              ) : (
                <tr key={`${t.sym}-${t.seq}`} className="border-t border-border">
                  <td className="px-3 py-1 tabular text-fg-subtle">{clockUtc(t.ts)}</td>
                  <td className="px-3 py-1 font-medium">{t.sym}</td>
                  <td className="px-3 py-1 text-right tabular">{price(t.px, tickDecimals(t.sym))}</td>
                  <td className="px-3 py-1 text-right tabular">{qty(t.qty)}</td>
                  <td className={clsx("px-3 py-1", t.side === "BUY" ? "text-up" : "text-down")}>
                    {t.side === "BUY" ? "▲" : "▼"} {t.side}
                  </td>
                </tr>
              ),
            )}
            {rows.length === 0 && (
              <tr className="border-t border-border">
                <td colSpan={5} className="px-3 py-6 text-center text-fg-subtle">
                  {symbol === ALL ? "No prints yet." : `No prints for ${symbol} yet.`}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

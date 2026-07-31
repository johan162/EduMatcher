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
import type { TradeFrame } from "@edumatcher/terminal-types";
import { useLiveStore } from "../store/useLiveStore.js";
import { clockUtc, price, qty } from "../lib/format.js";
import { useTickDecimals } from "../lib/precision.js";

/** Rows rendered at once. The buffer holds more; the eye takes far less. */
const VISIBLE_ROWS = 200;

const ALL = "__all__";

export function filterTape(
  trades: readonly TradeFrame[],
  symbol: string,
  limit = VISIBLE_ROWS,
): TradeFrame[] {
  const rows = symbol === ALL ? trades : trades.filter((t) => t.sym === symbol);
  return rows.slice(0, limit);
}

export function TradeTapeView() {
  const trades = useLiveStore((s) => s.trades);
  const symbols = useLiveStore((s) => s.symbols);
  const [symbol, setSymbol] = useState(ALL);
  const [paused, setPaused] = useState(false);
  // Snapshot taken at the moment of pausing. Live updates keep arriving into
  // the store — pausing freezes the reading, it does not drop data, so
  // resuming shows the current tape rather than a gap.
  const [frozen, setFrozen] = useState<TradeFrame[]>([]);
  // Per row, not per view: the unfiltered tape mixes every instrument on the
  // exchange, and they do not share a tick size.
  const tickDecimals = useTickDecimals();

  const source = paused ? frozen : trades;
  const rows = useMemo(() => filterTape(source, symbol), [source, symbol]);

  function togglePause(): void {
    if (paused) {
      setPaused(false);
      setFrozen([]);
    } else {
      setFrozen(trades);
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
            paused ? "border-warning/50 bg-warning/10 text-warning" : "border-border hover:bg-muted",
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
            {rows.map((t) => (
              <tr key={`${t.sym}-${t.seq}`} className="border-t border-border">
                <td className="px-3 py-1 tabular text-fg-subtle">{clockUtc(t.ts)}</td>
                <td className="px-3 py-1 font-medium">{t.sym}</td>
                <td className="px-3 py-1 text-right tabular">{price(t.px, tickDecimals(t.sym))}</td>
                <td className="px-3 py-1 text-right tabular">{qty(t.qty)}</td>
                <td className={clsx("px-3 py-1", t.side === "BUY" ? "text-up" : "text-down")}>
                  {t.side === "BUY" ? "▲" : "▼"} {t.side}
                </td>
              </tr>
            ))}
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

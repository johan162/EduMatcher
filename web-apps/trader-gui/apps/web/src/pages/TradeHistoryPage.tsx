import { useMemo, useState } from "react";
import { useHistoryFillsQuery } from "@/queries/index.js";
import { useWsEvent } from "@/hooks/useWsEvent.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useBookStore } from "@/store/useBookStore.js";
import { useUiStore } from "@/store/useUiStore.js";
import {
  fillRowFromEvent,
  fillRowFromHistory,
  filterFillRowsBySide,
  mergeFillRows,
  type FillRow,
} from "@/lib/fills.js";
import { formatIsoTime, formatPrice, formatQty, shortId } from "@/lib/formatters.js";
import type { Side } from "@/types/index.js";

/** Local calendar date YYYY-MM-DD (matches the venue-day approximation elsewhere). */
function todayIso(now = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`;
}

/**
 * Trade History / Fills panel (§13.5). Durable FILL rows from
 * `GET /history/fills` (filtered by symbol/date server-side), with live
 * `order.fill` events prepended this session. Side is filtered client-side.
 * The Trade ID reads `trade_ids[0]` and badges "+N" for a swept VWAP fill;
 * clicking an Order ID opens the Order Detail drawer.
 */
export function TradeHistoryPage() {
  const symbols = useSymbolStore((s) => s.symbols);
  const [symbol, setSymbol] = useState("");
  const [side, setSide] = useState<Side | "ALL">("ALL");
  const [date, setDate] = useState(todayIso());
  const openOrderDetail = useUiStore((s) => s.openOrderDetail);
  const [liveRows, setLiveRows] = useState<FillRow[]>([]);

  const params: Record<string, string> = { limit: "200" };
  if (symbol) params.symbol = symbol;
  if (date) params.date = date;

  const fills = useHistoryFillsQuery(params);

  // Prepend live fills as they arrive; bounded so a busy session cannot grow
  // unbounded. Symbol/date filtering of the live tail is applied at render.
  useWsEvent("order.fill", (env) => {
    setLiveRows((prev) => [fillRowFromEvent(env.data), ...prev].slice(0, 500));
  });

  const historyRows = useMemo<FillRow[]>(
    () => (fills.data?.events ?? []).map(fillRowFromHistory),
    [fills.data],
  );

  const rows = useMemo<FillRow[]>(() => {
    // Live fills happen "now", so only surface them when the date filter is
    // today (or unset); constrain them to the symbol filter before merging.
    const showLive = !date || date === todayIso();
    const liveFiltered = showLive
      ? liveRows.filter((r) => !symbol || r.symbol === symbol)
      : [];
    const merged = mergeFillRows(liveFiltered, historyRows);
    return filterFillRowsBySide(merged, side);
  }, [liveRows, historyRows, symbol, side, date]);

  const tickFor = (sym: string) =>
    useBookStore.getState().books[sym]?.tickDecimals ??
    symbols.find((m) => m.symbol === sym)?.tick_decimals ??
    2;

  const inputCls =
    "bg-raised border border-line rounded px-2 py-1 text-xs focus:outline-none focus:border-[#3a3a60]";

  return (
    <div className="flex flex-col gap-3 p-4 h-full">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-fg">Trade History</h1>
        <span className="text-[11px] text-fg-faint">
          {rows.length} {rows.length === 1 ? "fill" : "fills"}
          {fills.isFetching ? " · loading…" : ""}
        </span>
      </div>

      {/* Filter bar (§13.5.3) */}
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-fg-faint">Symbol</span>
          <input
            list="fills-symbols"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            aria-label="Filter symbol"
            placeholder="All"
            className={`${inputCls} font-mono w-28`}
          />
          <datalist id="fills-symbols">
            {symbols.map((s) => (
              <option key={s.symbol} value={s.symbol} />
            ))}
          </datalist>
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-fg-faint">Side</span>
          <select
            value={side}
            onChange={(e) => setSide(e.target.value as Side | "ALL")}
            aria-label="Filter side"
            className={inputCls}
          >
            <option value="ALL">All</option>
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-fg-faint">Date</span>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            aria-label="Filter date"
            className={inputCls}
          />
        </label>
        {symbol && (
          <button
            type="button"
            onClick={() => setSymbol("")}
            className="rounded border border-line px-2 py-1 text-[11px] text-fg-dim hover:text-fg"
          >
            Clear symbol
          </button>
        )}
      </div>

      {fills.isError && (
        <p className="text-xs text-ask">Could not load fills — is the stats DB available?</p>
      )}

      {rows.length === 0 && !fills.isFetching ? (
        <div className="border border-line rounded p-8 text-center text-sm text-fg-dim">
          No fills for the selected filters.
        </div>
      ) : (
        <div className="overflow-auto border border-line rounded">
          <table className="w-full text-xs border-collapse">
            <thead className="sticky top-0 z-10 bg-panel text-fg-dim">
              <tr>
                <th scope="col" className="px-2 py-1.5 text-left font-medium">Time</th>
                <th scope="col" className="px-2 py-1.5 text-left font-medium">Symbol</th>
                <th scope="col" className="px-2 py-1.5 text-left font-medium">Side</th>
                <th scope="col" className="px-2 py-1.5 text-right font-medium">Fill Qty</th>
                <th scope="col" className="px-2 py-1.5 text-right font-medium">Fill Price</th>
                <th scope="col" className="px-2 py-1.5 text-right font-medium">Remaining</th>
                <th scope="col" className="px-2 py-1.5 text-left font-medium">Trade ID</th>
                <th scope="col" className="px-2 py-1.5 text-left font-medium">Order ID</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} className="border-b border-raised hover:bg-raised">
                  <td className="px-2 py-1 font-mono text-fg-dim whitespace-nowrap">
                    {r.ts ? formatIsoTime(r.ts) : "—"}
                    {r.live && <span className="ml-1 text-[9px] text-emerald-400">live</span>}
                  </td>
                  <td className="px-2 py-1 font-mono font-medium">{r.symbol || "—"}</td>
                  <td className={`px-2 py-1 ${r.side === "BUY" ? "text-bid" : r.side === "SELL" ? "text-ask" : "text-fg-faint"}`}>
                    {r.side ?? "—"}
                  </td>
                  <td className="px-2 py-1 text-right font-mono">{formatQty(r.fillQty)}</td>
                  <td className="px-2 py-1 text-right font-mono">
                    {r.fillPrice === null ? "—" : formatPrice(r.fillPrice, tickFor(r.symbol))}
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-fg-dim">
                    {formatQty(r.remaining)}
                  </td>
                  <td className="px-2 py-1 font-mono text-fg-dim" title={r.tradeId ?? undefined}>
                    {r.tradeId ? shortId(r.tradeId) : "—"}
                    {r.extraTradeCount > 0 && (
                      <span className="ml-1 rounded bg-elevated px-1 text-[9px] text-fg-dim">
                        +{r.extraTradeCount}
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-1">
                    <button
                      type="button"
                      onClick={() => openOrderDetail(r.orderId)}
                      className="font-mono text-sky-400 hover:underline"
                      title="Open order lifecycle"
                    >
                      {shortId(r.orderId)}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

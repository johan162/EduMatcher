import { useMemo, useState } from "react";
import { useHistoryFillsQuery } from "@/queries/index.js";
import { useWsEvent } from "@/hooks/useWsEvent.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useBookStore } from "@/store/useBookStore.js";
import { OrderDetailDrawer } from "@/components/orders/OrderDetailDrawer.js";
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
  const [detailId, setDetailId] = useState<string | null>(null);
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
    "bg-[#1a1a28] border border-[#2a2a45] rounded px-2 py-1 text-xs focus:outline-none focus:border-[#3a3a60]";

  return (
    <div className="flex flex-col gap-3 p-4 h-full">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-[#e8e8f0]">Trade History</h1>
        <span className="text-[11px] text-[#505070]">
          {rows.length} {rows.length === 1 ? "fill" : "fills"}
          {fills.isFetching ? " · loading…" : ""}
        </span>
      </div>

      {/* Filter bar (§13.5.3) */}
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">Symbol</span>
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
          <span className="text-[10px] text-[#505070]">Side</span>
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
          <span className="text-[10px] text-[#505070]">Date</span>
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
            className="rounded border border-[#2a2a45] px-2 py-1 text-[11px] text-[#9090b0] hover:text-[#e8e8f0]"
          >
            Clear symbol
          </button>
        )}
      </div>

      {fills.isError && (
        <p className="text-xs text-ask">Could not load fills — is the stats DB available?</p>
      )}

      {rows.length === 0 && !fills.isFetching ? (
        <div className="border border-[#2a2a45] rounded p-8 text-center text-sm text-[#9090b0]">
          No fills for the selected filters.
        </div>
      ) : (
        <div className="overflow-auto border border-[#2a2a45] rounded">
          <table className="w-full text-xs border-collapse">
            <thead className="sticky top-0 z-10 bg-[#12121a] text-[#9090b0]">
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
                <tr key={r.key} className="border-b border-[#1a1a28] hover:bg-[#1a1a28]">
                  <td className="px-2 py-1 font-mono text-[#9090b0] whitespace-nowrap">
                    {r.ts ? formatIsoTime(r.ts) : "—"}
                    {r.live && <span className="ml-1 text-[9px] text-emerald-400">live</span>}
                  </td>
                  <td className="px-2 py-1 font-mono font-medium">{r.symbol || "—"}</td>
                  <td className={`px-2 py-1 ${r.side === "BUY" ? "text-bid" : r.side === "SELL" ? "text-ask" : "text-[#505070]"}`}>
                    {r.side ?? "—"}
                  </td>
                  <td className="px-2 py-1 text-right font-mono">{formatQty(r.fillQty)}</td>
                  <td className="px-2 py-1 text-right font-mono">
                    {r.fillPrice === null ? "—" : formatPrice(r.fillPrice, tickFor(r.symbol))}
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-[#9090b0]">
                    {formatQty(r.remaining)}
                  </td>
                  <td className="px-2 py-1 font-mono text-[#9090b0]" title={r.tradeId ?? undefined}>
                    {r.tradeId ? shortId(r.tradeId) : "—"}
                    {r.extraTradeCount > 0 && (
                      <span className="ml-1 rounded bg-[#20203a] px-1 text-[9px] text-[#9090b0]">
                        +{r.extraTradeCount}
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-1">
                    <button
                      type="button"
                      onClick={() => setDetailId(r.orderId)}
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

      {detailId && (
        <OrderDetailDrawer key={detailId} orderId={detailId} onClose={() => setDetailId(null)} />
      )}
    </div>
  );
}

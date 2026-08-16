import { useHistoryDailyQuery, todayIso } from "@/queries/index.js";
import { useBookStore } from "@/store/useBookStore.js";
import { formatPrice, formatQty } from "@/lib/formatters.js";
import type { DailyStat } from "@/types/index.js";

interface StatCardProps {
  label: string;
  value: string;
}

function StatCard({ label, value }: StatCardProps) {
  return (
    <div className="rounded border border-[#2a2a45] bg-[#12121a] px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-[#505070]">{label}</div>
      <div className="text-sm font-mono text-[#e8e8f0]">{value}</div>
    </div>
  );
}

interface StatsPanelProps {
  symbol: string;
  tickDecimals: number;
}

/**
 * Daily OHLCV statistics (§16.5). The grid is sourced from today's
 * `/history/daily` row; last buy/sell come live from the book store. Renders
 * a friendly notice rather than an error when the stats database is absent
 * (a normal state before pm-stats has run) or before the first print.
 */
export function StatsPanel({ symbol, tickDecimals }: StatsPanelProps) {
  const dailyQuery = useHistoryDailyQuery(symbol, todayIso());
  const entry = useBookStore((s) => s.books[symbol]);

  const row: DailyStat | undefined = dailyQuery.data?.daily?.[0];
  const px = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : formatPrice(v, tickDecimals);

  const lastBuy = entry?.lastBuyPrice ?? row?.close_bid ?? null;
  const lastSell = entry?.lastSellPrice ?? row?.close_ask ?? null;

  return (
    <div className="flex flex-col gap-3">
      {dailyQuery.isLoading && <p className="text-xs text-[#9090b0]">Loading statistics…</p>}

      {!dailyQuery.isLoading && !row && (
        <p className="text-xs text-[#505070]">
          No daily statistics for {symbol} yet — they appear after the first trade of the session.
        </p>
      )}

      <div className="grid grid-cols-2 gap-2">
        <StatCard label="Open" value={px(row?.open_price)} />
        <StatCard label="High" value={px(row?.high_price)} />
        <StatCard label="Low" value={px(row?.low_price)} />
        <StatCard label="Close / Last" value={px(row?.close_price ?? entry?.lastPrice ?? null)} />
        <StatCard label="Volume" value={row ? formatQty(row.volume) : "—"} />
        <StatCard label="Trade Count" value={row ? formatQty(row.trade_count) : "—"} />
        <StatCard label="VWAP" value={px(row?.vwap)} />
        <StatCard
          label="Largest Trade"
          value={
            row?.largest_trade_qty && row?.largest_trade_price
              ? `${formatQty(row.largest_trade_qty)} @ ${formatPrice(row.largest_trade_price, tickDecimals)}`
              : "—"
          }
        />
        <StatCard label="Last Buy" value={px(lastBuy)} />
        <StatCard label="Last Sell" value={px(lastSell)} />
      </div>
    </div>
  );
}

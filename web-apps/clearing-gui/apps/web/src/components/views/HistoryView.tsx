/**
 * Daily activity and close-to-close history of one gateway.
 *
 * The only durable P&L history is one close snapshot per position per
 * session close, so the chart has one point per close and says so; there is
 * no intraday series to draw. Each close's total is the sum of its rows'
 * cumulative P&L, every row converted with its own precision first.
 *
 * Nothing here is polled: `useHistoryRevalidation` refetches only when
 * clearing commits a new position write.
 */
import { lazy, Suspense, useMemo, useState } from "react";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { FilterForm, filterDate, filterText, type FilterValues } from "@/components/shared/Filters";
import { QueryState } from "@/components/shared/QueryState";
import { MoreRows, Panel } from "@/components/shared/Ui";
import { Skeleton } from "@/components/shared/Skeleton";
import { useCloseSnapshots, useDaily, useHistoryRevalidation } from "@/api/queries";
import type { CloseSnapshotRowT, DailyRowT } from "@/api/schemas";
import { formatCurrency, signClass, ticksToDisplay, type Ticks } from "@/lib/money";
import { qtyColumn, textColumn, tickColumn } from "./columns";

const CloseChart = lazy(() => import("./CloseChart"));

const DAILY_COLUMNS: Column<DailyRowT>[] = [
  textColumn("date", "Date", (r) => r.trade_date),
  textColumn("symbol", "Symbol", (r) => r.symbol),
  qtyColumn("traded", "Traded qty", (r) => r.traded_qty),
  qtyColumn("bought", "Bought", (r) => r.buy_qty),
  qtyColumn("sold", "Sold", (r) => r.sell_qty),
  tickColumn("traded_value", "Traded value", (r) => r.traded_notional_ticks),
  tickColumn("net", "Net amount", (r) => r.net_amount_ticks, { signed: true, title: "Bought value − sold value" }),
  tickColumn("realized", "Realized P&L", (r) => r.realized_pnl_ticks, { signed: true, title: "Realized that day" }),
  qtyColumn("end_qty", "End qty", (r) => r.end_net_qty, "Position after the day's last trade"),
  tickColumn("end_cost", "End avg cost", (r) => r.end_avg_cost_ticks, { extra: 2 }),
  tickColumn("end_unrealized", "End unrealized", (r) => r.end_unrealized_pnl_ticks, { signed: true }),
];

const SNAPSHOT_COLUMNS: Column<CloseSnapshotRowT>[] = [
  textColumn("date", "Close", (r) => r.trade_date),
  textColumn("symbol", "Symbol", (r) => r.symbol),
  qtyColumn("qty", "Net qty", (r) => r.net_qty),
  tickColumn("mark", "Closing mark", (r) => r.mark_price_ticks),
  tickColumn("realized", "Cumulative realized", (r) => r.realized_pnl_ticks, { signed: true }),
  tickColumn("unrealized", "Unrealized at close", (r) => r.unrealized_pnl_ticks, { signed: true }),
];

export interface CloseTotal {
  date: string;
  positions: number;
  /** Cumulative realized + unrealized P&L, display currency. */
  pnl: number;
}

/** One total per close date, oldest first; every row converted before the sum. */
export function closeTotals(rows: CloseSnapshotRowT[]): CloseTotal[] {
  const byDate = new Map<string, CloseTotal>();
  for (const r of rows) {
    const total = byDate.get(r.trade_date) ?? { date: r.trade_date, positions: 0, pnl: 0 };
    const cumulative = (r.realized_pnl_ticks + r.unrealized_pnl_ticks) as Ticks;
    total.pnl += ticksToDisplay(cumulative, r.tick_decimals);
    total.positions += 1;
    byDate.set(r.trade_date, total);
  }
  return [...byDate.values()].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
}

const TOTAL_COLUMNS: Column<CloseTotal>[] = [
  textColumn("date", "Close", (r) => r.date),
  qtyColumn("positions", "Positions", (r) => r.positions),
  {
    id: "pnl",
    header: "Cumulative P&L",
    title: "Realized + unrealized at the closing marks, all symbols, display currency",
    align: "right",
    cell: (r) => <span className={signClass(r.pnl)}>{formatCurrency(r.pnl)}</span>,
    sortValue: (r) => r.pnl,
  },
];

const FIELDS = [
  { name: "symbol", label: "Symbol", placeholder: "e.g. AAPL" },
  { name: "from", label: "From", type: "date" as const },
  { name: "to", label: "To", type: "date" as const },
];

export function HistoryView({ gateway }: { gateway?: string }) {
  const [filters, setFilters] = useState<FilterValues>({});
  useHistoryRevalidation(gateway);
  const params = {
    gateway,
    symbol: filterText(filters["symbol"]),
    from: filterDate(filters["from"]),
    to: filterDate(filters["to"]),
  };
  const daily = useDaily(params);
  const closes = useCloseSnapshots(params);
  const totals = useMemo(() => (closes.data ? closeTotals(closes.data.snapshots) : []), [closes.data]);

  return (
    <>
      <FilterForm fields={FIELDS} onApply={setFilters} />
      <Panel title="Close-to-close cumulative P&L">
        <p className="text-xs text-fg-dim">
          One point per session close; there is no intraday history. Each point is the cumulative realized plus
          unrealized P&amp;L at that close&apos;s marks, every symbol converted with its own precision.
        </p>
        <QueryState
          query={closes}
          isEmpty={(d) => d.snapshots.length === 0}
          emptyTitle="No close snapshots"
          emptyHint="Clearing takes a snapshot at each session close."
        >
          {(d) => (
            <>
              <Suspense fallback={<Skeleton className="h-[220px] w-[720px]" />}>
                <CloseChart totals={totals} />
              </Suspense>
              <DataTable caption="Closes by day" columns={TOTAL_COLUMNS} rows={totals} rowKey={(r) => r.date} />
              <DataTable
                caption="Close snapshots"
                columns={SNAPSHOT_COLUMNS}
                rows={d.snapshots}
                rowKey={(r) => `${r.trade_date}/${r.gateway_id}/${r.symbol}`}
              />
              <MoreRows hasMore={d.has_more} count={d.count} />
            </>
          )}
        </QueryState>
      </Panel>
      <Panel title="Daily activity">
        <QueryState query={daily} isEmpty={(d) => d.daily.length === 0} emptyTitle="No daily rows">
          {(d) => (
            <>
              <DataTable
                caption="Daily activity"
                columns={DAILY_COLUMNS}
                rows={d.daily}
                rowKey={(r) => `${r.trade_date}/${r.gateway_id}/${r.symbol}`}
              />
              <MoreRows hasMore={d.has_more} count={d.count} />
            </>
          )}
        </QueryState>
      </Panel>
    </>
  );
}

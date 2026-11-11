/**
 * The retained-trade audit of one gateway, newest first, a page at a time.
 *
 * Exchange time (`ts_ns`) and clearing's ingest time are separate columns;
 * the retention window is stated above the table. A participant sees its own
 * side of each trade only: the server sends the counterparty as null.
 */
import { useState } from "react";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { FilterForm, filterDate, filterText, type FilterValues } from "@/components/shared/Filters";
import { QueryState } from "@/components/shared/QueryState";
import { useTrades } from "@/api/queries";
import type { TradeRowT } from "@/api/schemas";
import { qtyColumn, textColumn, tickColumn, timeColumn } from "./columns";

const COLUMNS: Column<TradeRowT>[] = [
  textColumn("trade_id", "Trade id", (r) => r.trade_id),
  timeColumn("ts", "Exchange time", (r) => r.ts_ns, "When the exchange printed the trade"),
  timeColumn("ingest", "Clearing ingest", (r) => r.ingest_ts_ns, "When clearing wrote it; not an exchange time"),
  textColumn("date", "Trade date", (r) => r.trade_date),
  textColumn("symbol", "Symbol", (r) => r.symbol),
  qtyColumn("qty", "Qty", (r) => r.quantity),
  tickColumn("price", "Price", (r) => r.price_ticks),
  textColumn("buyer", "Buyer", (r) => r.buy_gateway_id, "Null when the buyer is not you"),
  textColumn("seller", "Seller", (r) => r.sell_gateway_id, "Null when the seller is not you"),
  textColumn("aggressor", "Aggressor", (r) => r.aggressor_side, "As the engine sent it; not meaningful for auctions"),
  textColumn("match", "Match type", (r) => r.match_type),
  textColumn("msg", "Audit msg id", (r) => r.msg_id),
];

const FIELDS = [
  { name: "symbol", label: "Symbol", placeholder: "e.g. AAPL" },
  { name: "from", label: "From", type: "date" as const },
  { name: "to", label: "To", type: "date" as const },
];

export function TradesView({ gateway, label }: { gateway?: string; label: string }) {
  const [filters, setFilters] = useState<FilterValues>({});
  const trades = useTrades({
    gateway,
    symbol: filterText(filters["symbol"]),
    from: filterDate(filters["from"]),
    to: filterDate(filters["to"]),
  });
  const retained = trades.data?.pages[0]?.retained_from;
  return (
    <>
      <FilterForm fields={FIELDS} onApply={setFilters} />
      {trades.data && (
        <p className="mb-2 text-xs text-fg-dim">
          {retained
            ? `Raw trades are kept from ${retained}; older days are in Daily & Close History.`
            : "No raw trades are held; daily rows remain in Daily & Close History."}
        </p>
      )}
      <QueryState
        query={trades}
        isEmpty={(d) => d.pages.every((p) => p.trades.length === 0)}
        emptyTitle="No trades"
        emptyHint="No retained trade matches the filters."
      >
        {(d) => {
          const rows = d.pages.flatMap((p) => p.trades);
          return (
            <>
              <DataTable caption={`${label} retained trades`} columns={COLUMNS} rows={rows} rowKey={(r) => r.trade_id} />
              <div className="mt-2 flex items-center gap-3 text-xs text-fg-dim">
                <span>{rows.length} trades shown</span>
                {trades.hasNextPage && (
                  <button
                    type="button"
                    disabled={trades.isFetchingNextPage}
                    onClick={() => void trades.fetchNextPage()}
                    className="rounded bg-elevated px-3 py-1 font-semibold text-fg hover:brightness-110 disabled:opacity-50"
                  >
                    Load more
                  </button>
                )}
              </div>
            </>
          );
        }}
      </QueryState>
    </>
  );
}

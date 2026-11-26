/**
 * The retained-trade audit of one gateway, newest first, a page at a time.
 *
 * Exchange time (`ts_ns`) and clearing's ingest time are separate columns;
 * the retention window is stated above the table. A participant sees its own
 * side of each trade only: the server sends the counterparty as null.
 */
import { useState } from "react";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { FilterForm, filterDate, filterText, type FilterField, type FilterValues } from "@/components/shared/Filters";
import { QueryState } from "@/components/shared/QueryState";
import { useSymbolOptions, useTrades } from "@/api/queries";
import type { TradeRowT } from "@/api/schemas";
import { gatewayColumn, qtyColumn, textColumn, tickColumn, timeColumn } from "./columns";
import { subject, teachingHint } from "./teaching";

const COLUMNS: Column<TradeRowT>[] = [
  textColumn("trade_id", "Trade id", (r) => r.trade_id, "The engine's trade id: run number and sequence within the run"),
  timeColumn("ts", "Exchange time", (r) => r.ts_ns, "When the exchange printed the trade"),
  timeColumn("ingest", "Clearing ingest", (r) => r.ingest_ts_ns, "When clearing wrote it; not an exchange time"),
  textColumn("date", "Trade date", (r) => r.trade_date, "The trading day the trade belongs to, in the venue's session timezone"),
  textColumn("symbol", "Symbol", (r) => r.symbol, "The instrument traded"),
  qtyColumn("qty", "Qty", (r) => r.quantity, "Shares traded"),
  tickColumn("price", "Price", (r) => r.price_ticks, { title: "The execution price" }),
  gatewayColumn("buyer", "Buyer", (r) => r.buy_gateway_id, "The buying gateway; a dash when it is not you (a participant sees only its own side)"),
  gatewayColumn("seller", "Seller", (r) => r.sell_gateway_id, "The selling gateway; a dash when it is not you (a participant sees only its own side)"),
  textColumn("aggressor", "Aggressor", (r) => r.aggressor_side, "The side whose order took liquidity, as the engine sent it; not meaningful for auctions"),
  textColumn("match", "Match type", (r) => r.match_type, "How the trade matched: continuous trading, or an auction uncross"),
  textColumn("msg", "Audit msg id", (r) => r.msg_id, "The id of the trade message in the audit trail, for looking it up there"),
];

const DATE_FIELDS: FilterField[] = [
  { name: "from", label: "From", type: "date" },
  { name: "to", label: "To", type: "date" },
];

export function TradesView({ gateway, label }: { gateway?: string; label: string }) {
  const [filters, setFilters] = useState<FilterValues>({});
  const symbols = useSymbolOptions();
  const fields: FilterField[] = [{ name: "symbol", label: "Symbol", type: "combobox", suggestions: symbols }, ...DATE_FIELDS];
  const trades = useTrades({
    gateway,
    symbol: filterText(filters["symbol"]),
    from: filterDate(filters["from"]),
    to: filterDate(filters["to"]),
  });
  const retained = trades.data?.pages[0]?.retained_from;
  return (
    <>
      <FilterForm fields={fields} onApply={setFilters} />
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
        emptyHint={teachingHint(
          `No retained trade matches the filters: a trade appears here when one of ${subject(gateway).your} orders is filled.`,
          "Positions and P&L",
        )}
      >
        {(d) => {
          const rows = d.pages.flatMap((p) => p.trades);
          return (
            <>
              <p className="mb-1 text-xs text-fg-dim">
                Newest first, as the exchange printed them. The server sends the trades a page at a time, so the
                columns do not sort; filter by symbol or date to narrow them.
              </p>
              <DataTable
                caption={`${label} retained trades`}
                columns={COLUMNS}
                rows={rows}
                rowKey={(r) => r.trade_id}
                sortable={false}
                more={{
                  available: trades.hasNextPage,
                  loading: trades.isFetchingNextPage,
                  load: () => void trades.fetchNextPage(),
                }}
              />
            </>
          );
        }}
      </QueryState>
    </>
  );
}

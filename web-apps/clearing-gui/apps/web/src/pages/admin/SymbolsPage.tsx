/**
 * Symbol Activity (ADMIN): what traded per symbol over a date range, and the
 * aggregate signed position now. The aggregate is zero while every holder is
 * a gateway, so it is not open interest and is not titled as such.
 */
import { useState } from "react";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { FilterForm, filterDate, type FilterValues } from "@/components/shared/Filters";
import { QueryState } from "@/components/shared/QueryState";
import { MoreRows, PageHeader } from "@/components/shared/Ui";
import { qtyColumn, textColumn, tickColumn } from "@/components/views/columns";
import { useClearingSymbols } from "@/api/queries";
import type { ClearingSymbolRowT } from "@/api/schemas";

const COLUMNS: Column<ClearingSymbolRowT>[] = [
  textColumn("symbol", "Symbol", (r) => r.symbol),
  qtyColumn("traded", "Traded qty", (r) => r.traded_qty, "Counted once per side: a 100-share trade is 200"),
  tickColumn("value", "Traded value", (r) => r.traded_notional_ticks, { title: "Both sides" }),
  tickColumn("realized", "Realized P&L", (r) => r.realized_pnl_ticks, { signed: true }),
  qtyColumn("net", "Aggregate net qty", (r) => r.open_net_qty, "Sum of all current signed positions"),
  tickColumn("open_pnl", "Unrealized P&L", (r) => r.open_unrealized_pnl_ticks, { signed: true }),
];

const FIELDS = [
  { name: "from", label: "From", type: "date" as const },
  { name: "to", label: "To", type: "date" as const },
];

export function SymbolsPage() {
  const [filters, setFilters] = useState<FilterValues>({});
  const symbols = useClearingSymbols({ from: filterDate(filters["from"]), to: filterDate(filters["to"]) });
  return (
    <>
      <PageHeader title="Symbol Activity">
        Traded quantity, value and realized P&amp;L per symbol over the days chosen, and the aggregate signed
        position now. The aggregate is the sum of long and short positions, so it is zero while every holder
        is a gateway: it is not open interest.
      </PageHeader>
      <FilterForm fields={FIELDS} onApply={setFilters} />
      <QueryState query={symbols} isEmpty={(d) => d.symbols.length === 0} emptyTitle="Nothing traded in the range">
        {(d) => (
          <>
            <DataTable caption="Symbol activity" columns={COLUMNS} rows={d.symbols} rowKey={(r) => r.symbol} />
            <MoreRows hasMore={d.has_more} count={d.count} />
          </>
        )}
      </QueryState>
    </>
  );
}

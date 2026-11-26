/**
 * Reconciliation (ADMIN): raw trades against the daily rows, for an explicit
 * date range, on demand.
 *
 * The request scans every retained raw trade of the range, so it runs only
 * when Run is pressed and never refreshes by itself (useReconciliation).
 * What a result can prove is stated with it: only days that still have raw
 * trades are compared, and an empty list is "no discrepancy in the queried
 * retained data" -- never "verified".
 */
import { useState } from "react";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { FilterForm, filterText, type FilterField, type FilterValues } from "@/components/shared/Filters";
import { QueryState } from "@/components/shared/QueryState";
import { MoreRows, PageHeader } from "@/components/shared/Ui";
import { gatewayColumn, qtyColumn, textColumn, tickColumn } from "@/components/views/columns";
import { useGatewayOptions, useReconciliation, useSymbolOptions, type Params } from "@/api/queries";
import type { ReconciliationRowT } from "@/api/schemas";

const COLUMNS: Column<ReconciliationRowT>[] = [
  textColumn("date", "Date", (r) => r.trade_date, "The trading day compared"),
  textColumn("side", "Side", (r) => r.side, "BUY or SELL: each side is compared on its own"),
  gatewayColumn("gateway", "Gateway", (r) => r.gateway_id, "The participant gateway"),
  textColumn("symbol", "Symbol", (r) => r.symbol, "The instrument"),
  qtyColumn("raw_qty", "Raw qty", (r) => r.raw_qty, "Shares counted from the retained raw trades"),
  qtyColumn("summary_qty", "Daily-row qty", (r) => r.summary_qty, "Shares in clearing's daily row for the day"),
  qtyColumn("qty_diff", "Qty diff", (r) => r.qty_diff, "Raw qty − daily-row qty; anything but 0 is a discrepancy"),
  tickColumn("raw_value", "Raw value", (r) => r.raw_notional_ticks, { title: "Quantity × price summed from the retained raw trades" }),
  tickColumn("summary_value", "Daily-row value", (r) => r.summary_notional_ticks, { title: "The value in clearing's daily row for the day" }),
  tickColumn("value_diff", "Value diff", (r) => r.notional_diff_ticks, {
    signed: true,
    title: "Raw value − daily-row value; anything but 0 is a discrepancy",
  }),
];

export function ReconciliationPage() {
  const [params, setParams] = useState<Params | null>(null);
  const gateways = useGatewayOptions();
  const symbols = useSymbolOptions();
  const fields: FilterField[] = [
    { name: "from", label: "From", type: "date", required: true },
    { name: "to", label: "To", type: "date", required: true },
    { name: "gateway", label: "Gateway", type: "combobox", suggestions: gateways },
    { name: "symbol", label: "Symbol", type: "combobox", suggestions: symbols },
  ];
  const result = useReconciliation(params);

  function run(values: FilterValues) {
    const next: Params = {
      from: values["from"],
      to: values["to"],
      gateway: filterText(values["gateway"]),
      symbol: filterText(values["symbol"]),
    };
    // The same range again is a deliberate re-run: the cached result would
    // otherwise be shown and nothing compared.
    if (JSON.stringify(next) === JSON.stringify(params)) void result.refetch();
    else setParams(next);
  }

  return (
    <>
      <PageHeader title="Reconciliation">
        Compares the quantities and values counted from clearing&apos;s raw trades with its daily rows, per day,
        side, gateway and symbol. It reads every retained raw trade of the range, so it runs only when you ask.
      </PageHeader>
      <FilterForm fields={fields} onApply={run} submitLabel="Run" />
      {params !== null && (
        <QueryState query={result} skeletonColumns={10}>
          {(d) => (
            <>
              <p className="mb-2 text-xs text-fg-dim">
                {d.compared_from === null
                  ? `Nothing was compared: no day of the range has raw trades left (raw trades are kept from ${d.retained_from ?? "no day"}).`
                  : `Compared ${d.compared_from} to ${d.compared_to}; raw trades are kept from ${d.retained_from}, so earlier days cannot be checked.`}
              </p>
              {d.discrepancies.length === 0 ? (
                d.compared_from !== null && (
                  <p className="rounded border border-line p-3 text-sm">No discrepancy in the queried retained data.</p>
                )
              ) : (
                <>
                  <DataTable
                    caption="Discrepancies"
                    columns={COLUMNS}
                    rows={d.discrepancies}
                    rowKey={(r) => `${r.trade_date}/${r.side}/${r.gateway_id}/${r.symbol}`}
                  />
                  <MoreRows hasMore={d.has_more} count={d.count} />
                </>
              )}
            </>
          )}
        </QueryState>
      )}
    </>
  );
}

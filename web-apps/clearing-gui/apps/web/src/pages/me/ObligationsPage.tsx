/**
 * My Quote Obligations (MARKET_MAKER): the obligation settings the engine
 * resolved for this gateway, per symbol, from the requester-scoped
 * `GET /api/v1/symbols`. These are the inputs the engine enforces quotes
 * against; nothing records how the gateway actually quoted, so the screen
 * shows no presence, re-quote or compliance figure.
 */
import { DataTable, type Column } from "@/components/shared/DataTable";
import { QueryState } from "@/components/shared/QueryState";
import { PageHeader } from "@/components/shared/Ui";
import { textColumn } from "@/components/views/columns";
import { useSymbolSettings } from "@/api/queries";
import type { SymbolInfoT } from "@/api/schemas";
import { formatQty, formatTicks } from "@/lib/money";

function obligation(r: SymbolInfoT): string {
  if (r.enforce_mm_obligation === undefined || r.enforce_mm_obligation === null) return "Not configured";
  return r.enforce_mm_obligation ? "Enforced" : "Not enforced";
}

const COLUMNS: Column<SymbolInfoT>[] = [
  textColumn("symbol", "Symbol", (r) => r.symbol),
  textColumn("obligation", "Obligation", obligation, "Whether the engine enforces quote obligations for you on this symbol"),
  {
    id: "spread",
    header: "Max spread",
    title: "Widest quote that satisfies the obligation",
    align: "right",
    cell: (r) =>
      r.mm_max_spread_ticks === undefined || r.mm_max_spread_ticks === null
        ? "—"
        : `${r.mm_max_spread_ticks} ticks (${formatTicks(r.mm_max_spread_ticks, r.tick_decimals)})`,
    sortValue: (r) => r.mm_max_spread_ticks ?? null,
  },
  {
    id: "min_qty",
    header: "Min quantity",
    title: "Smallest quote that satisfies the obligation",
    align: "right",
    cell: (r) => formatQty(r.mm_min_qty ?? null),
    sortValue: (r) => r.mm_min_qty ?? null,
  },
];

export function ObligationsPage() {
  const symbols = useSymbolSettings();
  return (
    <>
      <PageHeader title="My Quote Obligations">
        The configured enforcement parameters for your quotes, per symbol: whether an obligation applies, the
        widest spread and the smallest size that satisfy it. This is configuration, not a measure of how you
        quoted.
      </PageHeader>
      <QueryState query={symbols} isEmpty={(d) => d.symbols.length === 0} emptyTitle="No symbols">
        {(d) => <DataTable caption="Quote obligation settings" columns={COLUMNS} rows={d.symbols} rowKey={(r) => r.symbol} />}
      </QueryState>
    </>
  );
}

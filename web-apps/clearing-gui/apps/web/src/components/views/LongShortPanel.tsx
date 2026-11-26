/**
 * Longs against shorts (CG27, D8, Explain mode): per symbol, the shares held
 * long and held short now, which are always equal while every holder is a
 * gateway: every share bought was sold by someone. The symbols with the
 * largest open positions are drawn; the table lists every open symbol.
 */
import { DataTable, type Column } from "@/components/shared/DataTable";
import { DivergingBars } from "@/components/shared/Bars";
import { useExplain } from "@/components/shared/Explain";
import { Panel } from "@/components/shared/Ui";
import type { ClearingSymbolRowT } from "@/api/schemas";
import { qtyColumn, textColumn } from "./columns";

const DRAWN = 20;

const COLUMNS: Column<ClearingSymbolRowT>[] = [
  textColumn("symbol", "Symbol", (r) => r.symbol, "The instrument"),
  qtyColumn("long", "Long qty", (r) => r.open_long_qty, "Shares held long now, by every gateway that is long"),
  qtyColumn("long_holders", "Long holders", (r) => r.long_holders, "Gateways long in the symbol now"),
  qtyColumn("short", "Short qty", (r) => r.open_short_qty, "Shares held short now, by every gateway that is short"),
  qtyColumn("short_holders", "Short holders", (r) => r.short_holders, "Gateways short in the symbol now"),
];

export function LongShortPanel({ rows }: { rows: ClearingSymbolRowT[] }) {
  const explain = useExplain();
  if (!explain) return null;
  const open = rows.filter((r) => r.open_long_qty > 0 || r.open_short_qty > 0);
  const drawn = [...open].sort((a, b) => b.open_long_qty - a.open_long_qty).slice(0, DRAWN);
  return (
    <Panel title="Longs against shorts">
      <p className="text-xs">
        Every share held long was sold by someone who is now short: the two sides are always equal, so each
        symbol&apos;s bars are the same length.
        {open.length > DRAWN && ` The ${DRAWN} symbols with the largest positions are drawn; the table lists all ${open.length}.`}
      </p>
      {open.length === 0 ? (
        <p className="text-xs text-fg-dim">No open position in these symbols now.</p>
      ) : (
        <>
          <DivergingBars
            leftLabel="short"
            rightLabel="long"
            rows={drawn.map((r) => ({ key: r.symbol, label: r.symbol, left: r.open_short_qty, right: r.open_long_qty }))}
          />
          <DataTable caption="Long and short positions" columns={COLUMNS} rows={open} rowKey={(r) => r.symbol} />
        </>
      )}
    </Panel>
  );
}

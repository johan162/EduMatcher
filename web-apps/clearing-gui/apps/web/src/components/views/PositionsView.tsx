/**
 * Current positions and marked exposure of one gateway: the caller's own
 * (no `gateway`, scoped by the server) or, on an ADMIN drill-down, the named
 * one. Both refresh at the current-state cadence (5 s).
 */
import { DataTable, type Column } from "@/components/shared/DataTable";
import { QueryState } from "@/components/shared/QueryState";
import { MoreRows, Panel } from "@/components/shared/Ui";
import { useExposure, usePositions, type Params } from "@/api/queries";
import type { ExposureRowT, PositionRowT } from "@/api/schemas";
import { formatClock } from "@/lib/time";
import { qtyColumn, textColumn, tickColumn, timeColumn } from "./columns";

const POSITION_COLUMNS: Column<PositionRowT>[] = [
  textColumn("symbol", "Symbol", (r) => r.symbol),
  qtyColumn("net_qty", "Net qty", (r) => r.net_qty, "Signed shares: negative is short"),
  tickColumn("avg_cost", "Avg cost", (r) => r.avg_cost_ticks, { extra: 2, title: "Volume-weighted entry price" }),
  tickColumn("mark", "Mark", (r) => r.mark_price_ticks, { title: "Last trade price, or the end-of-day mark" }),
  tickColumn("realized", "Realized P&L", (r) => r.realized_pnl_ticks, { signed: true }),
  tickColumn("unrealized", "Unrealized P&L", (r) => r.unrealized_pnl_ticks, { signed: true }),
  qtyColumn("buy_qty", "Bought", (r) => r.buy_qty),
  qtyColumn("sell_qty", "Sold", (r) => r.sell_qty),
  tickColumn("buy_notional", "Bought value", (r) => r.buy_notional_ticks),
  tickColumn("sell_notional", "Sold value", (r) => r.sell_notional_ticks),
  timeColumn("last_trade", "Last trade", (r) => r.last_trade_ts_ns, "Exchange time of the last trade"),
  timeColumn("updated", "Updated", (r) => r.updated_ts_ns, "When clearing last wrote the row"),
];

const EXPOSURE_COLUMNS: Column<ExposureRowT>[] = [
  textColumn("symbol", "Symbol", (r) => r.symbol),
  qtyColumn("net_qty", "Net qty", (r) => r.net_qty),
  tickColumn("mark", "Mark", (r) => r.mark_price_ticks),
  tickColumn("net_notional", "Net notional", (r) => r.net_notional_ticks, { signed: true, title: "Net qty × mark" }),
  tickColumn("gross_notional", "Gross notional", (r) => r.gross_notional_ticks, { title: "|Net qty × mark|" }),
  tickColumn("realized", "Realized P&L", (r) => r.realized_pnl_ticks, { signed: true }),
  tickColumn("unrealized", "Unrealized P&L", (r) => r.unrealized_pnl_ticks, { signed: true }),
  tickColumn("total", "Total P&L", (r) => r.total_pnl_ticks, { signed: true }),
];

/** The newest `updated_ts_ns` of a gateway's positions: when clearing last wrote. */
export function newestWrite(rows: PositionRowT[]): number | null {
  return rows.reduce<number | null>((max, r) => (max === null || r.updated_ts_ns > max ? r.updated_ts_ns : max), null);
}

export function FreshnessNote({ committedNs }: { committedNs: number | null }) {
  return (
    <p className="mb-3 text-xs text-fg-dim">
      {committedNs === null ? "Nothing committed by clearing yet" : `Committed by clearing at ${formatClock(committedNs)}`}
      {"; a fill can take up to 5 s (one clearing flush) to appear here."}
    </p>
  );
}

export function PositionsView({ gateway, label }: { gateway?: string; label: string }) {
  const params: Params = gateway ? { gateway } : {};
  const positions = usePositions(params);
  const exposure = useExposure(params);
  return (
    <>
      <FreshnessNote committedNs={positions.data ? newestWrite(positions.data.positions) : null} />
      <Panel title="Positions">
        <QueryState
          query={positions}
          isEmpty={(d) => d.positions.length === 0}
          emptyTitle="No positions"
          emptyHint="Clearing has no position rows for this gateway: it has not traded."
        >
          {(d) => (
            <>
              <DataTable
                caption={`${label} positions`}
                columns={POSITION_COLUMNS}
                rows={d.positions}
                rowKey={(r) => `${r.gateway_id}/${r.symbol}`}
              />
              <MoreRows hasMore={d.has_more} count={d.count} />
            </>
          )}
        </QueryState>
      </Panel>
      <Panel title="Exposure">
        <QueryState query={exposure} isEmpty={(d) => d.exposure.length === 0} emptyTitle="No exposure">
          {(d) => (
            <>
              <DataTable
                caption={`${label} exposure`}
                columns={EXPOSURE_COLUMNS}
                rows={d.exposure}
                rowKey={(r) => `${r.gateway_id}/${r.symbol}`}
              />
              <MoreRows hasMore={d.has_more} count={d.count} />
            </>
          )}
        </QueryState>
      </Panel>
    </>
  );
}

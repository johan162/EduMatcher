/**
 * Current positions of one gateway, at their marks: the caller's own (no
 * `gateway`, scoped by the server) or, on an ADMIN drill-down, the named one.
 * Refreshes at the current-state cadence (5 s).
 *
 * One table (CG20, D5). Net and gross notional and total P&L are derived
 * from the row itself, exactly as the API's exposure query derives them from
 * the same ledger row (net qty × mark, its absolute value, realized +
 * unrealized), in the row's own ticks -- so no second request, and no two
 * separately polled replies to line up.
 */
import { DataTable, type Column } from "@/components/shared/DataTable";
import { QueryState } from "@/components/shared/QueryState";
import { MoreRows, Panel } from "@/components/shared/Ui";
import { usePositions, type Params } from "@/api/queries";
import type { PositionRowT } from "@/api/schemas";
import { useFormatNs } from "@/components/shared/Time";
import type { Ticks } from "@/lib/money";
import { useExplain } from "@/components/shared/Explain";
import { positionColumn, qtyColumn, textColumn, tickColumn, timeColumn } from "./columns";
import { PositionExplain } from "./PositionExplain";
import { subject, teachingHint } from "./teaching";

/** Net qty × mark, in the row's ticks; none without a mark. */
export function netNotional(r: PositionRowT): Ticks | null {
  return r.mark_price_ticks === null ? null : ((r.net_qty * r.mark_price_ticks) as Ticks);
}

function grossNotional(r: PositionRowT): Ticks | null {
  const net = netNotional(r);
  return net === null ? null : (Math.abs(net) as Ticks);
}

const POSITION_COLUMNS: Column<PositionRowT>[] = [
  textColumn("symbol", "Symbol", (r) => r.symbol, "The instrument"),
  positionColumn("net_qty", "Net qty", (r) => r.net_qty, "Shares held now: bought minus sold. Negative is short."),
  tickColumn("avg_cost", "Avg cost", (r) => r.avg_cost_ticks, {
    extra: 2,
    title: "Volume-weighted price of the open position, in the symbol's currency",
  }),
  tickColumn("mark", "Mark", (r) => r.mark_price_ticks, {
    title: "The price the position is valued at: the last trade price, or the end-of-day mark after the close",
  }),
  tickColumn("net_notional", "Net notional", netNotional, {
    signed: true,
    title: "Net qty × mark: the position's value at the mark, negative when short",
  }),
  tickColumn("gross_notional", "Gross notional", grossNotional, {
    title: "|Net qty × mark|: the size of the position at the mark, long or short",
  }),
  tickColumn("realized", "Realized P&L", (r) => r.realized_pnl_ticks, {
    pnl: true,
    title: "Cumulative profit or loss locked in by trades that reduced or closed the position",
  }),
  tickColumn("unrealized", "Unrealized P&L", (r) => r.unrealized_pnl_ticks, {
    pnl: true,
    title: "Profit or loss of the open quantity if it were closed at the mark",
  }),
  tickColumn("total", "Total P&L", (r) => (r.realized_pnl_ticks + r.unrealized_pnl_ticks) as Ticks, {
    pnl: true,
    title: "Realized + unrealized P&L",
  }),
  qtyColumn("buy_qty", "Bought", (r) => r.buy_qty, "Cumulative shares bought in this symbol"),
  qtyColumn("sell_qty", "Sold", (r) => r.sell_qty, "Cumulative shares sold in this symbol"),
  tickColumn("buy_notional", "Bought value", (r) => r.buy_notional_ticks, {
    title: "Cumulative quantity × price of every buy",
  }),
  tickColumn("sell_notional", "Sold value", (r) => r.sell_notional_ticks, {
    title: "Cumulative quantity × price of every sell",
  }),
  timeColumn("last_trade", "Last trade", (r) => r.last_trade_ts_ns, "Exchange time of the last trade in this symbol"),
  timeColumn("updated", "Updated", (r) => r.updated_ts_ns, "When clearing last wrote the row (a flush, or a new mark)"),
];

/** The newest `updated_ts_ns` of a gateway's positions: when clearing last wrote. */
export function newestWrite(rows: PositionRowT[]): number | null {
  return rows.reduce<number | null>((max, r) => (max === null || r.updated_ts_ns > max ? r.updated_ts_ns : max), null);
}

export function FreshnessNote({ committedNs }: { committedNs: number | null }) {
  const formatNs = useFormatNs();
  return (
    <p className="mb-3 text-xs text-fg-dim">
      {committedNs === null ? "Nothing committed by clearing yet" : `Committed by clearing at ${formatNs(committedNs)}`}
      {"; a fill can take up to 5 s (one clearing flush) to appear here."}
    </p>
  );
}

export function PositionsView({ gateway, label }: { gateway?: string; label: string }) {
  const params: Params = gateway ? { gateway } : {};
  const positions = usePositions(params);
  const explain = useExplain();
  const who = subject(gateway);
  return (
    <>
      <FreshnessNote committedNs={positions.data ? newestWrite(positions.data.positions) : null} />
      <Panel title="Positions">
        <QueryState
          query={positions}
          isEmpty={(d) => d.positions.length === 0}
          emptyTitle="No positions"
          emptyHint={teachingHint(
            `Nothing traded yet: a position appears when one of ${who.your} orders trades.`,
            "Positions and P&L",
          )}
        >
          {(d) => (
            <>
              <DataTable
                caption={`${label} positions`}
                columns={POSITION_COLUMNS}
                rows={d.positions}
                rowKey={(r) => `${r.gateway_id}/${r.symbol}`}
                detail={
                  explain
                    ? { name: (r) => `Explain ${r.symbol}`, render: (r) => <PositionExplain row={r} /> }
                    : undefined
                }
              />
              <MoreRows hasMore={d.has_more} count={d.count} />
            </>
          )}
        </QueryState>
      </Panel>
    </>
  );
}

/**
 * The Overview's "Needs attention" panel (CG23): the participants with the
 * largest losses and the venue's largest open positions, side by side. Each
 * row opens that participant's drawer. Both are short exception lists; the
 * full lists are the Participants screen and each participant's drawer.
 */
import { useNavigate } from "react-router-dom";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { QueryState } from "@/components/shared/QueryState";
import { Panel } from "@/components/shared/Ui";
import { useLargestPositions, useParticipants } from "@/api/queries";
import type { ExposureRowT, ParticipantRowT } from "@/api/schemas";
import { formatPnlCurrency, signClass } from "@/lib/money";
import { largestLosses } from "@/pages/admin/overviewChecks";
import { positionColumn, textColumn, tickColumn } from "./columns";
import { participantPath } from "./GatewayId";

function money(id: string, header: string, value: (r: ParticipantRowT) => number, title: string): Column<ParticipantRowT> {
  return {
    id,
    header,
    title,
    align: "right",
    cell: (r) => <span className={signClass(value(r))}>{formatPnlCurrency(value(r))}</span>,
    sortValue: value,
  };
}

const LOSS_COLUMNS: Column<ParticipantRowT>[] = [
  textColumn("gateway", "Gateway", (r) => r.gateway_id, "The participant gateway; select the row to open it"),
  money("total", "Total P&L", (r) => r.total_pnl, "Realized + unrealized P&L, in display currency"),
  money("realized", "Realized", (r) => r.realized_pnl, "Realized P&L of all its positions"),
  money("unrealized", "Unrealized", (r) => r.unrealized_pnl, "Unrealized P&L of its open positions at their marks"),
];

const POSITION_COLUMNS: Column<ExposureRowT>[] = [
  textColumn("gateway", "Gateway", (r) => r.gateway_id, "The participant gateway; select the row to open it"),
  textColumn("symbol", "Symbol", (r) => r.symbol, "The instrument"),
  positionColumn("net_qty", "Net qty", (r) => r.net_qty, "Shares held now; negative is short"),
  tickColumn("gross", "Gross notional", (r) => r.gross_notional_ticks, {
    title: "|Net qty × mark|: the size of this one position at its mark (not a venue total)",
  }),
  tickColumn("unrealized", "Unrealized P&L", (r) => r.unrealized_pnl_ticks, {
    pnl: true,
    title: "Profit or loss of the open quantity at the mark",
  }),
];

export function NeedsAttention() {
  const navigate = useNavigate();
  const participants = useParticipants();
  const positions = useLargestPositions();
  return (
    <Panel title="Needs attention">
      <div className="grid gap-4 lg:grid-cols-2">
        <section aria-label="Largest losses" className="flex flex-col gap-1">
          <h3 className="text-xs font-semibold text-fg-dim">Largest losses</h3>
          <QueryState
            query={participants}
            isEmpty={(d) => largestLosses(d.participants).length === 0}
            emptyTitle="No participant is at a loss"
          >
            {(d) => (
              <DataTable
                caption="Largest losses"
                columns={LOSS_COLUMNS}
                rows={largestLosses(d.participants)}
                rowKey={(r) => r.gateway_id}
                sortable={false}
                onRowClick={(r) => navigate(participantPath(r.gateway_id))}
              />
            )}
          </QueryState>
        </section>
        <section aria-label="Largest positions" className="flex flex-col gap-1">
          <h3 className="text-xs font-semibold text-fg-dim">Largest positions</h3>
          <QueryState
            query={positions}
            isEmpty={(d) => d.exposure.every((r) => r.net_qty === 0)}
            emptyTitle="No open positions"
          >
            {(d) => (
              <DataTable
                caption="Largest positions"
                columns={POSITION_COLUMNS}
                rows={d.exposure.filter((r) => r.net_qty !== 0)}
                rowKey={(r) => `${r.gateway_id}/${r.symbol}`}
                sortable={false}
                onRowClick={(r) => navigate(participantPath(r.gateway_id))}
              />
            )}
          </QueryState>
        </section>
      </div>
    </Panel>
  );
}

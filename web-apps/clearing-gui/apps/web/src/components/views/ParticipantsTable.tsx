/**
 * Every participant gateway with its P&L totals. The totals are display
 * currency as the API computed them, each position converted with its own
 * precision before the sum; they are not tick values.
 */
import { Link } from "react-router-dom";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { QueryState } from "@/components/shared/QueryState";
import { MoreRows } from "@/components/shared/Ui";
import { useParticipants } from "@/api/queries";
import type { ParticipantRowT } from "@/api/schemas";
import { formatCurrency, signClass } from "@/lib/money";
import { qtyColumn, timeColumn } from "./columns";

function currencyColumn(id: string, header: string, value: (r: ParticipantRowT) => number): Column<ParticipantRowT> {
  return {
    id,
    header,
    align: "right",
    cell: (r) => <span className={signClass(value(r))}>{formatCurrency(value(r))}</span>,
    sortValue: value,
  };
}

const COLUMNS: Column<ParticipantRowT>[] = [
  {
    id: "gateway",
    header: "Gateway",
    cell: (r) => (
      <Link to={`/participants/${encodeURIComponent(r.gateway_id)}`} className="text-link hover:underline">
        {r.gateway_id}
      </Link>
    ),
    sortValue: (r) => r.gateway_id,
  },
  currencyColumn("realized", "Realized P&L", (r) => r.realized_pnl),
  currencyColumn("unrealized", "Unrealized P&L", (r) => r.unrealized_pnl),
  currencyColumn("total", "Total P&L", (r) => r.total_pnl),
  qtyColumn("positions", "Positions", (r) => r.position_count),
  qtyColumn("open", "Open", (r) => r.open_position_count, "Positions with a non-zero quantity"),
  timeColumn("updated", "Last update", (r) => r.last_update_ts_ns),
];

export function ParticipantsTable() {
  const participants = useParticipants();
  return (
    <QueryState
      query={participants}
      isEmpty={(d) => d.participants.length === 0}
      emptyTitle="No participant has a position"
      emptyHint="A gateway appears here once clearing has recorded a trade for it."
    >
      {(d) => (
        <>
          <DataTable
            caption="Participants"
            columns={COLUMNS}
            rows={d.participants}
            rowKey={(r) => r.gateway_id}
            initialSort={{ id: "gateway", dir: "asc" }}
          />
          <MoreRows hasMore={d.has_more} count={d.count} />
        </>
      )}
    </QueryState>
  );
}

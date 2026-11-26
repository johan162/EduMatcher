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

function currencyColumn(
  id: string,
  header: string,
  value: (r: ParticipantRowT) => number,
  title: string,
): Column<ParticipantRowT> {
  return {
    id,
    header,
    title,
    align: "right",
    cell: (r) => <span className={signClass(value(r))}>{formatCurrency(value(r))}</span>,
    sortValue: value,
  };
}

const COLUMNS: Column<ParticipantRowT>[] = [
  {
    id: "gateway",
    header: "Gateway",
    title: "The participant's gateway id; open it for positions, trades, history, settlement and sessions",
    cell: (r) => (
      <Link to={`/participants/${encodeURIComponent(r.gateway_id)}`} className="text-link hover:underline">
        {r.gateway_id}
      </Link>
    ),
    sortValue: (r) => r.gateway_id,
  },
  currencyColumn("realized", "Realized P&L", (r) => r.realized_pnl, "Realized P&L of all the gateway's positions, in display currency"),
  currencyColumn("unrealized", "Unrealized P&L", (r) => r.unrealized_pnl, "Unrealized P&L of all its open positions at their marks, in display currency"),
  currencyColumn("total", "Total P&L", (r) => r.total_pnl, "Realized + unrealized P&L, in display currency"),
  qtyColumn("positions", "Positions", (r) => r.position_count, "Symbols the gateway has a position row for: every symbol it has traded"),
  qtyColumn("open", "Open", (r) => r.open_position_count, "Positions with a non-zero quantity"),
  timeColumn("updated", "Last update", (r) => r.last_update_ts_ns, "When clearing last wrote any of the gateway's positions"),
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

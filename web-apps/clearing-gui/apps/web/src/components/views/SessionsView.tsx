/**
 * Gateway connect/disconnect history as clearing observed it. A participant
 * sees its own (no `gateway`); an ADMIN may filter by gateway, or a
 * drill-down fixes one.
 */
import { useState } from "react";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { FilterForm, filterDate, filterText, type FilterField, type FilterValues } from "@/components/shared/Filters";
import { QueryState } from "@/components/shared/QueryState";
import { MoreRows } from "@/components/shared/Ui";
import { useGatewaySessions } from "@/api/queries";
import type { GatewaySessionRowT } from "@/api/schemas";
import { textColumn, timeColumn } from "./columns";

const COLUMNS: Column<GatewaySessionRowT>[] = [
  textColumn("gateway", "Gateway", (r) => r.gateway_id),
  timeColumn("connected", "Connected", (r) => r.connected_at_ns),
  timeColumn("disconnected", "Disconnected", (r) => r.disconnected_at_ns, "Empty: still connected, or not seen"),
  textColumn("reason", "Reason", (r) => r.disconnect_reason),
];

const DATE_FIELDS: FilterField[] = [
  { name: "from", label: "From", type: "date" },
  { name: "to", label: "To", type: "date" },
  { name: "connected_only", label: "Connected only", type: "checkbox" },
];

interface SessionsViewProps {
  label: string;
  /** Fixed gateway (ADMIN drill-down). */
  gateway?: string;
  /** Offer a gateway filter (ADMIN venue screen). */
  gatewayFilter?: boolean;
}

export function SessionsView({ label, gateway, gatewayFilter = false }: SessionsViewProps) {
  const [filters, setFilters] = useState<FilterValues>({});
  const fields = gatewayFilter ? [{ name: "gateway", label: "Gateway" }, ...DATE_FIELDS] : DATE_FIELDS;
  const sessions = useGatewaySessions({
    gateway: gateway ?? filterText(filters["gateway"]),
    from: filterDate(filters["from"]),
    to: filterDate(filters["to"]),
    connected_only: filters["connected_only"] === "true",
  });
  return (
    <>
      <p className="mb-2 text-xs text-fg-dim">
        Times are when clearing observed the connect and disconnect, not engine times. A session without a
        disconnect is still connected, or its disconnect was not seen. Days are trading days.
      </p>
      <FilterForm fields={fields} onApply={setFilters} />
      <QueryState query={sessions} isEmpty={(d) => d.sessions.length === 0} emptyTitle="No gateway sessions">
        {(d) => (
          <>
            <DataTable
              caption={label}
              columns={COLUMNS}
              rows={d.sessions}
              rowKey={(r) => `${r.gateway_id}/${r.connected_at_ns}`}
            />
            <MoreRows hasMore={d.has_more} count={d.count} />
          </>
        )}
      </QueryState>
    </>
  );
}

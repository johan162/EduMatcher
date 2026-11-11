/**
 * Events (ADMIN): the PHASE, EOD and GAP events clearing recorded, newest
 * first, with each event's own payload in words.
 */
import { useState } from "react";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { FilterForm, filterDate, type FilterValues } from "@/components/shared/Filters";
import { QueryState } from "@/components/shared/QueryState";
import { MoreRows, PageHeader } from "@/components/shared/Ui";
import { textColumn, timeColumn } from "@/components/views/columns";
import { useSessionEvents } from "@/api/queries";
import type { SessionEventRowT } from "@/api/schemas";
import { eventDetail } from "@/components/views/eventDetail";

const COLUMNS: Column<SessionEventRowT>[] = [
  timeColumn("ts", "Observed", (r) => r.ts_ns, "When clearing observed it; for a GAP, the trade after the gap"),
  textColumn("date", "Trade date", (r) => r.trade_date),
  textColumn("type", "Type", (r) => r.event_type),
  textColumn("detail", "Detail", eventDetail),
];

const FIELDS = [
  {
    name: "type",
    label: "Type",
    type: "select" as const,
    options: [
      { value: "", label: "All" },
      { value: "PHASE", label: "PHASE" },
      { value: "EOD", label: "EOD" },
      { value: "GAP", label: "GAP" },
    ],
  },
  { name: "from", label: "From", type: "date" as const },
  { name: "to", label: "To", type: "date" as const },
];

export function EventsPage() {
  const [filters, setFilters] = useState<FilterValues>({});
  const events = useSessionEvents({
    type: filters["type"] || undefined,
    from: filterDate(filters["from"]),
    to: filterDate(filters["to"]),
  });
  return (
    <>
      <PageHeader title="Events">
        Session phases, the engine&apos;s end of day and feed gaps. Times are when clearing observed the event,
        not engine times. A GAP means clearing saw trade ids jump; no GAP does not prove the feed was complete.
      </PageHeader>
      <FilterForm fields={FIELDS} onApply={setFilters} />
      <QueryState query={events} isEmpty={(d) => d.events.length === 0} emptyTitle="No events match">
        {(d) => (
          <>
            <DataTable caption="Session events" columns={COLUMNS} rows={d.events} rowKey={(r) => String(r.id)} />
            <MoreRows hasMore={d.has_more} count={d.count} />
          </>
        )}
      </QueryState>
    </>
  );
}

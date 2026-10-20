/**
 * Row 7, EVENT LOG (design §12.3): every health event, newest first,
 * filterable by kind, on the session clock. The live stream fills it; on
 * each connect, /api/events adds what came before (useDashboardLoads).
 */

import { EventLog } from "../../components/widgets/EventLog.js";
import { Row } from "../../components/widgets/Row.js";
import { useDashStore } from "../../store/useDashStore.js";

export function EventsRow() {
  const events = useDashStore((s) => s.events);
  const tz = useDashStore((s) => s.sessionTz);
  return (
    <Row id="events" title="Event log" badge={`${events.length} events`}>
      <EventLog label="Events" events={events} tz={tz} height={300} />
    </Row>
  );
}

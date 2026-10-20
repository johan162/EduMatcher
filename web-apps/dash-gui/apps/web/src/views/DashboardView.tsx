/**
 * The dashboard (design §12.3): seven rows over the live snapshot and the
 * bridge's history. Each row subscribes to its own slice of the store, and
 * the charts redraw once per bucket of their resolution, so the 1 Hz
 * snapshot does not redraw the whole page every second.
 *
 * A drawer route (§12.4) renders in the outlet, over the rows' right side.
 */

import { Outlet } from "react-router-dom";
import { BooksRow } from "./rows/BooksRow.js";
import { EventsRow } from "./rows/EventsRow.js";
import { GatewaysRow } from "./rows/GatewaysRow.js";
import { OverviewRow } from "./rows/OverviewRow.js";
import { ParticipantsRow } from "./rows/ParticipantsRow.js";
import { ProcessesRow } from "./rows/ProcessesRow.js";
import { TradingRow } from "./rows/TradingRow.js";
import { useDashboardLoads } from "./rows/common.js";

export function DashboardView() {
  useDashboardLoads();
  return (
    <>
      <section aria-label="Dashboard" className="flex min-h-0 flex-col gap-4 overflow-y-auto pb-4">
        <OverviewRow />
        <ProcessesRow />
        <TradingRow />
        <ParticipantsRow />
        <BooksRow />
        <GatewaysRow />
        <EventsRow />
      </section>
      <Outlet />
    </>
  );
}

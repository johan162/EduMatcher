/**
 * Clearing Overview (ADMIN): the venue's clearing state, as an operations
 * view rather than a risk dashboard.
 *
 * - freshness: the latest committed clearing write and trade, with the
 *   flush qualifier;
 * - feed gaps: an alert when clearing saw trade ids jump on the latest
 *   session date, and the caveat that no gap is not proof of completeness;
 * - health: database and pm-clearing process, as two separate facts;
 * - participants, the last EOD run, recent session events.
 *
 * Summary and participants refresh at 5 s, health at 30 s; events are
 * fetched once. There is deliberately no venue equity, margin, open-interest
 * or cross-symbol notional figure: none is computed by the system.
 */
import { Link } from "react-router-dom";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { QueryState } from "@/components/shared/QueryState";
import { Badge, PageHeader, Panel, Stat } from "@/components/shared/Ui";
import { ParticipantsTable } from "@/components/views/ParticipantsTable";
import { textColumn, timeColumn } from "@/components/views/columns";
import { eventDetail } from "@/components/views/eventDetail";
import { useHealth, useSessionEvents, useSummary } from "@/api/queries";
import type { SessionEventRowT, SummaryT } from "@/api/schemas";
import { formatCurrency } from "@/lib/money";
import { formatClock, formatNs } from "@/lib/time";

const RECENT_EVENT_COLUMNS: Column<SessionEventRowT>[] = [
  timeColumn("ts", "Observed", (r) => r.ts_ns),
  textColumn("date", "Trade date", (r) => r.trade_date),
  textColumn("type", "Type", (r) => r.event_type),
  textColumn("detail", "Detail", eventDetail),
];

/** `1 trade`, `2 trades`. */
function plural(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

function FeedGaps({ summary }: { summary: SummaryT }) {
  const caveat =
    "A gap is a jump clearing saw in the trade ids it received. Seeing none does not prove the feed was complete.";
  const gap = summary.latest_gap;
  if (summary.gap_count > 0) {
    return (
      <div role="alert" aria-labelledby="gap-title" className="mb-4 rounded border-2 border-ask bg-ask/15 p-3">
        <h2 id="gap-title" className="text-sm font-bold text-ask">
          Feed gap on {summary.session_date}
        </h2>
        <p className="text-sm">
          {gap
            ? `${plural(summary.gap_count, "gap")} seen. Latest: ${gap.missing_trades === null ? "unknown number of trades" : plural(gap.missing_trades, "trade")} missing between ids ${gap.last_seq ?? "?"} and ${gap.next_seq ?? "?"} (run ${gap.run_seq ?? "?"}, ${formatNs(gap.ts_ns)}).`
            : `${plural(summary.gap_count, "gap")} seen; see Events for the detail.`}
        </p>
        <p className="text-xs text-fg-dim">
          {caveat} Positions and P&amp;L may miss those trades; reconcile, and check the audit trail.
        </p>
      </div>
    );
  }
  return (
    <div className="mb-4 rounded border border-line p-3 text-xs text-fg-dim">
      <p>{`No feed gap seen on ${summary.session_date ?? "the latest session"}.`}</p>
      {gap && <p>{`The latest gap ever was on ${gap.trade_date} (${gap.missing_trades ?? "?"} missing).`}</p>}
      <p>{caveat}</p>
    </div>
  );
}

function Health() {
  const health = useHealth();
  return (
    <Panel title="Health">
      <QueryState query={health} skeletonColumns={2}>
        {(h) => (
          <ul className="flex flex-col gap-1 text-xs">
            <li className="flex items-center gap-2">
              <Badge tone={h.database.available ? "ok" : "bad"}>{h.database.available ? "OK" : "FAIL"}</Badge>
              {`Database: ${h.database.detail}`}
              {h.database.available &&
                ` (journal ${h.database.wal_mode ?? "?"}, ${h.database.trade_events_rows ?? 0} raw trades held)`}
            </li>
            <li className="flex items-center gap-2">
              <Badge tone={h.process.alive ? "ok" : "bad"}>{h.process.alive ? "OK" : "FAIL"}</Badge>
              {`pm-clearing process: ${h.process.alive ? "alive" : "not answering"} (${h.process.detail})`}
            </li>
          </ul>
        )}
      </QueryState>
    </Panel>
  );
}

export function OverviewPage() {
  const summary = useSummary();
  const events = useSessionEvents({ limit: 10 });
  return (
    <>
      <PageHeader title="Clearing Overview">The venue&apos;s clearing ledger, as pm-clearing last committed it.</PageHeader>
      <QueryState query={summary} skeletonColumns={4}>
        {(s) => (
          <>
            <p className="mb-3 text-xs text-fg-dim">
              {`Last clearing write ${formatClock(s.last_flush_ts_ns)}; newest trade ${formatClock(s.last_trade_ts_ns)}. Committed data only: a fill can take up to 5 s (one clearing flush) to appear.`}
            </p>
            <FeedGaps summary={s} />
            <div className="mb-5 flex flex-wrap gap-3">
              <Stat label="Participants" value={s.participant_count} sub="gateways with a position row" />
              <Stat label="Open positions" value={s.open_position_count} />
              <Stat
                label="Venue realized P&L"
                value={formatCurrency(s.realized_pnl)}
                sub="all gateways, display currency"
              />
              <Stat label="Venue unrealized P&L" value={formatCurrency(s.unrealized_pnl)} sub="at current marks" />
              <div className="flex min-w-[10rem] flex-col gap-0.5 rounded border border-line bg-panel px-3 py-2 text-xs">
                <span data-stat-label className="text-[11px] uppercase tracking-wide text-fg-dim">
                  Last EOD run
                </span>
                {s.eod_db_available ? (
                  s.last_eod_run ? (
                    <span>
                      {`${s.last_eod_run.trade_date} · `}
                      <Badge tone={s.last_eod_run.status === "ok" ? "ok" : "bad"}>{s.last_eod_run.status}</Badge>
                    </span>
                  ) : (
                    <span>none recorded</span>
                  )
                ) : (
                  <span className="text-halt">EOD ledger unavailable</span>
                )}
              </div>
            </div>
          </>
        )}
      </QueryState>
      <Health />
      <Panel
        title="Participants"
        actions={
          <Link to="/reconciliation" className="text-xs text-link hover:underline">
            Reconcile raw trades against daily rows
          </Link>
        }
      >
        <ParticipantsTable />
      </Panel>
      <Panel title="Recent session events">
        <QueryState query={events} isEmpty={(d) => d.events.length === 0} emptyTitle="No session events">
          {(d) => (
            <DataTable
              caption="Recent session events"
              columns={RECENT_EVENT_COLUMNS}
              rows={d.events}
              rowKey={(r) => String(r.id)}
            />
          )}
        </QueryState>
      </Panel>
    </>
  );
}

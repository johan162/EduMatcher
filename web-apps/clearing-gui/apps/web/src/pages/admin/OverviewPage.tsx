/**
 * Clearing Overview (ADMIN): the venue's clearing state, as an operations
 * view rather than a risk dashboard.
 *
 * - freshness: the latest committed clearing write and trade, with the
 *   flush qualifier;
 * - feed gaps: an alert when clearing saw trade ids jump on the latest
 *   session date, and the caveat that no gap is not proof of completeness;
 * - health: database and pm-clearing process, as two separate facts;
 * - the session phase, with a warning when continuous trading has gone
 *   quiet in the ledger, and one when EOD failed or has not settled a closed
 *   day (overviewChecks.ts);
 * - needs attention: the largest losses and largest positions, each row
 *   opening the participant's drawer (CG23);
 * - the last EOD run, recent session events.
 *
 * Summary, participants and the largest positions refresh at 5 s, health
 * and the phase at 30 s; events are fetched once. There is deliberately no
 * venue equity, margin, open-interest or cross-symbol notional figure: none
 * is computed by the system. A position's own gross notional is not one.
 */
import { Link } from "react-router-dom";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { QueryState } from "@/components/shared/QueryState";
import { Badge, PageHeader, Panel, Stat } from "@/components/shared/Ui";
import { NeedsAttention } from "@/components/views/NeedsAttention";
import { FlowsPanel } from "@/components/views/FlowsPanel";
import { NettingPanel } from "@/components/views/NettingPanel";
import { textColumn, timeColumn } from "@/components/views/columns";
import { eventDetail } from "@/components/views/eventDetail";
import { useHealth, useSession, useSessionEvents, useSummary } from "@/api/queries";
import type { SessionEventRowT, SummaryT } from "@/api/schemas";
import { formatCurrency } from "@/lib/money";
import { Time, useFormatNs } from "@/components/shared/Time";
import { ExplainLine } from "@/components/shared/Explain";
import { STALE_WRITE_MS, eodProblem, staleWriteSeconds, useUnchangedForMs } from "./overviewChecks";

const RECENT_EVENT_COLUMNS: Column<SessionEventRowT>[] = [
  timeColumn("ts", "Observed", (r) => r.ts_ns, "When clearing observed it; for a GAP, the trade after the gap"),
  textColumn("date", "Trade date", (r) => r.trade_date, "The trading day the event belongs to"),
  textColumn("type", "Type", (r) => r.event_type, "PHASE: a session phase change; EOD: the engine's end of day; GAP: trade ids jumped"),
  textColumn("detail", "Detail", eventDetail, "The event's own payload, in words"),
];

const EOD_TILE_TITLE = "The trading day pm-eod last ran for, and how the run ended";

/** `1 trade`, `2 trades`. */
function plural(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

function FeedGaps({ summary }: { summary: SummaryT }) {
  const formatNs = useFormatNs();
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

/** A warning that is not an alarm: something to look at, worded with its possible causes. */
function Warning({ children }: { children: string }) {
  return (
    <p role="status" className="mb-3 rounded border border-halt/50 bg-halt/10 p-2 text-xs">
      {children}
    </p>
  );
}

export function OverviewPage() {
  const formatNs = useFormatNs();
  const summary = useSummary();
  const session = useSession();
  const events = useSessionEvents({ limit: 10 });
  const phase = session.data?.state ?? null;
  const unchangedMs = useUnchangedForMs(summary.data?.last_flush_ts_ns ?? null);
  return (
    <>
      <PageHeader title="Clearing Overview">
        The venue&apos;s clearing ledger, as pm-clearing last committed it.{" "}
        <Link to="/reconciliation" className="text-link hover:underline">
          Reconcile raw trades against daily rows
        </Link>
      </PageHeader>
      <QueryState query={summary} skeletonColumns={4}>
        {(s) => (
          <>
            <p className="mb-3 text-xs text-fg-dim">
              {`Last clearing write ${formatNs(s.last_flush_ts_ns)}; newest trade ${formatNs(s.last_trade_ts_ns)}. Committed data only: a fill can take up to 5 s (one clearing flush) to appear.`}
            </p>
            <FeedGaps summary={s} />
            <OverviewWarnings summary={s} phase={phase} unchangedMs={unchangedMs} />
            <div className="mb-5 flex flex-wrap gap-3">
              <Stat
                label="Session phase"
                value={session.data ? session.data.state : session.isError ? "unknown" : "…"}
                sub={
                  session.data && session.isError ? (
                    // A failed refresh keeps the last reply: say it is stale.
                    "last known — the engine did not answer the latest check"
                  ) : session.data ? (
                    <>
                      since <Time iso={session.data.state_since} />
                    </>
                  ) : session.isError ? (
                    "the engine did not answer"
                  ) : undefined
                }
                title="The engine's trading phase now (PRE_OPEN, auctions, CONTINUOUS, CLOSED), refreshed every 30 s"
              />
              <Stat
                label="Participants"
                value={s.participant_count}
                sub="gateways with a position row"
                title="Gateways clearing holds a position row for: every gateway that has traded"
              />
              <Stat
                label="Open positions"
                value={s.open_position_count}
                title="Gateway/symbol positions with a non-zero quantity, all gateways"
              />
              <Stat
                label="Venue realized P&L"
                value={formatCurrency(s.realized_pnl)}
                sub="all gateways, display currency"
                title="Realized P&L of every position of every gateway, each converted with its own precision"
              />
              <Stat
                label="Venue unrealized P&L"
                value={formatCurrency(s.unrealized_pnl)}
                sub="at current marks"
                title="Unrealized P&L of every open position at its mark, all gateways. Gateways trade with each other, so this is not a venue profit."
              />
              <div className="flex min-w-[10rem] flex-col gap-0.5 rounded border border-line bg-panel px-3 py-2 text-xs">
                <span
                  data-stat-label
                  data-has-tooltip=""
                  title={EOD_TILE_TITLE}
                  className="cursor-help self-start text-[11px] uppercase tracking-wide text-fg-dim underline decoration-dotted underline-offset-2"
                >
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
                <ExplainLine>{EOD_TILE_TITLE}</ExplainLine>
              </div>
            </div>
          </>
        )}
      </QueryState>
      <Health />
      <NeedsAttention />
      <NettingPanel venue />
      <FlowsPanel />
      <Panel
        title="Recent session events"
        actions={
          <Link to="/events" className="text-xs text-link hover:underline">
            All events →
          </Link>
        }
      >
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

/** The stale-write and EOD warnings; nothing when all is well. */
function OverviewWarnings({ summary, phase, unchangedMs }: { summary: SummaryT; phase: string | null; unchangedMs: number }) {
  const stale = staleWriteSeconds(phase, unchangedMs);
  const formatNs = useFormatNs();
  const eod = eodProblem(summary, phase);
  return (
    <>
      {stale !== null && (
        <Warning>
          {`No new clearing write for at least ${stale} s during continuous trading (last write ${formatNs(summary.last_flush_ts_ns)}; expected within ${STALE_WRITE_MS / 1000} s while trades arrive): no trade has arrived, or clearing is not writing. Check Health and the Events screen.`}
        </Warning>
      )}
      {eod !== null && <Warning>{eod}</Warning>}
    </>
  );
}

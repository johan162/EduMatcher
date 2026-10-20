/**
 * Row 6, GATEWAYS & INFRASTRUCTURE (design §12.3): clients per gateway
 * (against its limit where it has one), the API's WebSocket sessions and
 * dropped events, slow disconnects, the log server's intake, the feed gaps
 * pm-stats saw, the data files' sizes, and the engine's diagnostics.
 *
 * Dropped events, slow disconnects and feed gaps are judged by pm-monitor
 * on their increase over five minutes, which these since-start and today
 * figures cannot show; their colour is pm-monitor's own active breach.
 */

import type { GatewayStats } from "@edumatcher/dash-types";
import { BarGauge } from "../../components/widgets/BarGauge.js";
import { Row } from "../../components/widgets/Row.js";
import { StatTile } from "../../components/widgets/StatTile.js";
import { formatBytes, formatCount, formatRate } from "../../lib/format.js";
import { byLabel, METRIC, total } from "../../lib/metrics.js";
import { useDashStore } from "../../store/useDashStore.js";
import { shortKey, useBreachLevel } from "./common.js";

/** Gateways whose clients are shown as a tile, in this order. */
const CLIENT_KINDS = ["ALF", "BALF", "MD", "RALF", "DC"];

function clients(g: GatewayStats): (v: number) => string {
  return (v) => (g.clients_max === null ? formatCount(v) : `${formatCount(v)} / ${formatCount(g.clients_max)}`);
}

export function GatewaysRow() {
  const snapshot = useDashStore((s) => s.snapshot);
  const dropped = useBreachLevel("api_dropped_events");
  const gaps = useBreachLevel("stats_feed_gaps");
  const slowLevel = useBreachLevel("slow_client_disconnects");
  const gateways = snapshot?.gateways ?? [];
  const shown = gateways.filter((g) => CLIENT_KINDS.includes(g.kind)).sort((a, b) => CLIENT_KINDS.indexOf(a.kind) - CLIENT_KINDS.indexOf(b.kind) || a.key.localeCompare(b.key));
  const log = gateways.find((g) => g.kind === "LOG");
  const slow = gateways.reduce((sum, g) => sum + g.slow_disconnects_today, 0);
  const diagnostics = snapshot ? byLabel(snapshot, METRIC.engineDiagnostics).sort((a, b) => a.label.localeCompare(b.label)) : [];

  return (
    <Row id="gateways" title="Gateways & infrastructure">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        {shown.map((g) => (
          <StatTile key={g.key} label={`${g.kind} clients`} value={g.clients} format={clients(g)} sub={shortKey(g.key)} />
        ))}
        <StatTile label="API WS sessions" value={snapshot ? total(snapshot, METRIC.apiWsSessions) : null} format={formatCount} />
        <StatTile label="API dropped events" value={snapshot ? total(snapshot, METRIC.apiDroppedEvents) : null} format={formatCount} level={dropped} sub="since start; WARN: any in 5 min" />
        <StatTile label="Slow disconnects" value={snapshot ? slow : null} format={formatCount} level={slowLevel} sub="today; WARN: any in 5 min" />
        <StatTile label="Log ingest" value={log?.msgs_per_sec ?? null} format={(v) => formatRate(v, "s")} sub={log ? `${formatCount(log.clients)} sessions` : undefined} />
        <StatTile label="Feed gaps" value={snapshot ? total(snapshot, METRIC.statsFeedGaps) : null} format={formatCount} level={gaps} sub="since start; WARN: any in 5 min" />
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <BarGauge label="Data files" items={(snapshot?.host.files ?? []).map((f) => ({ label: f.name, value: f.size_bytes }))} format={formatBytes} />
        <section aria-label="Engine diagnostics">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">Engine diagnostics</h3>
          {diagnostics.length === 0 ? (
            <p className="text-xs text-fg-faint">No data</p>
          ) : (
            <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-3">
              {diagnostics.map((d) => (
                <div key={d.label} className="flex min-w-0 justify-between gap-2">
                  <dt className="truncate text-fg-subtle" title={d.label}>
                    {d.label}
                  </dt>
                  <dd className={`m-0 tabular ${d.value > 0 ? "font-semibold text-warning" : "text-fg"}`}>{formatCount(d.value)}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>
      </div>
    </Row>
  );
}

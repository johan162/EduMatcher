/**
 * Row 1, OVERVIEW (design §12.3): "is the exchange OK?" from across the
 * room -- processes and participants up, today's orders and trades, the
 * order rate and engine latency with their last minute, the host's CPU,
 * memory and disk, and the exchange's memory by process over the range.
 */

import { Gauge } from "../../components/widgets/Gauge.js";
import { Row } from "../../components/widgets/Row.js";
import { StatTile } from "../../components/widgets/StatTile.js";
import { formatBytes, formatCount, formatMicros, formatPercent, formatRate } from "../../lib/format.js";
import { VITAL } from "../../lib/metrics.js";
import type { ExchangeStatusName } from "@edumatcher/dash-types";
import type { Level } from "../../lib/thresholds.js";
import { useDashStore } from "../../store/useDashStore.js";
import { ProcessSeriesChart } from "./ProcessSeriesChart.js";
import { stateSummary, useBreachLevel, useRule } from "./common.js";

/** States that leave a process out of "up". */
const DOWN = new Set(["DEAD", "SILENT", "HUNG", "MISSING", "STOPPED"]);

/**
 * The processes tile's colour is pm-monitor's verdict on the exchange, not
 * a count of its own: without a profile roster a STOPPED process was
 * stopped on purpose and leaves the exchange OPERATIONAL (I118).
 */
const STATUS_LEVEL: Record<ExchangeStatusName, Level> = {
  OPERATIONAL: "OK",
  DEGRADED: "WARN",
  IMPAIRED: "CRIT",
  DOWN: "CRIT",
};

export function OverviewRow() {
  const snapshot = useDashStore((s) => s.snapshot);
  const recent = useDashStore((s) => s.recent);
  const cpuRule = useRule("host_cpu_pct");
  const memRule = useRule("host_mem_pct");
  const diskRule = useRule("disk_free_pct");
  const p99Rule = useRule("engine_handle_p99_us");

  const exchange = snapshot?.processes.filter((p) => p.group === "EXCHANGE") ?? [];
  const up = exchange.filter((p) => !DOWN.has(p.state)).length;
  const processLevel: Level | undefined = snapshot ? STATUS_LEVEL[snapshot.exchange.status] : undefined;
  const cpuLevel = useBreachLevel("host_cpu_pct", "host");
  const memLevel = useBreachLevel("host_mem_pct", "host");
  const diskLevel = useBreachLevel("disk_free_pct", "host");
  const p99Level = useBreachLevel("engine_handle_p99_us");
  const participants = snapshot?.participants ?? [];
  const connected = participants.filter((p) => p.connected).length;
  const trading = snapshot?.trading;
  const host = snapshot?.host;
  const memPct = host && host.mem_total_bytes > 0 ? (100 * host.mem_used_bytes) / host.mem_total_bytes : null;
  const diskFreePct = host && host.disk_total_bytes > 0 ? (100 * host.disk_free_bytes) / host.disk_total_bytes : null;

  return (
    <Row id="overview" title="Overview">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile
          label="Processes"
          value={snapshot ? up : null}
          format={(v) => `${v} / ${exchange.length}`}
          level={processLevel}
          sub={stateSummary(exchange) || "all healthy"}
        />
        <StatTile
          label="Participants"
          value={snapshot ? connected : null}
          format={(v) => `${v} / ${participants.length}`}
          sub="connected"
          spark={recent.map((r) => r.participantsConnected)}
        />
        <StatTile
          label="Orders today"
          value={trading?.orders.today ?? null}
          format={formatCount}
          sub={trading ? `~${formatRate(trading.orders.avg_per_min, "min")} last hour` : undefined}
        />
        <StatTile
          label="Trades today"
          value={trading?.trades.today ?? null}
          format={formatCount}
          sub={trading ? `~${formatRate(trading.trades.avg_per_min, "min")} last hour` : undefined}
        />
        <StatTile label="Orders / s" value={trading?.orders.per_sec_now ?? null} format={(v) => formatRate(v, "s")} spark={recent.map((r) => r.ordersPerSec)} />
        <StatTile label="Engine p99" value={trading?.handle_p99_us ?? null} format={formatMicros} thresholds={p99Rule} level={p99Level} spark={recent.map((r) => r.p99Us)} sub={trading ? `p50 ${formatMicros(trading.handle_p50_us)}` : undefined} />
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[auto_minmax(0,1fr)]">
        <div className="flex flex-wrap justify-center gap-4">
          <Gauge label="CPU" value={host?.cpu_pct ?? null} format={formatPercent} sub="host" thresholds={cpuRule} level={cpuLevel} />
          <Gauge label="Memory" value={memPct} format={formatPercent} sub={host ? formatBytes(host.mem_used_bytes) : undefined} thresholds={memRule} level={memLevel} />
          <Gauge label="Disk free" value={diskFreePct} format={formatPercent} sub={host ? formatBytes(host.disk_free_bytes) : undefined} thresholds={diskRule} level={diskLevel} />
        </div>
        <ProcessSeriesChart label="Exchange memory by process" name={VITAL.rss} live={(p) => p.rss_bytes} format={formatBytes} stacked />
      </div>
    </Row>
  );
}

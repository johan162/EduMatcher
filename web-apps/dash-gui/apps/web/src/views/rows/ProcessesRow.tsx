/**
 * Row 2, PROCESSES (design §12.3): every process with its state in glyph
 * and word, uptime, memory and CPU with their recent trend, loop age and
 * lag; the participant bots after the exchange's own; memory per process
 * and CPU per process over the range.
 */

import type { ActiveBreach, ProcessHealth } from "@edumatcher/dash-types";
import { BarGauge } from "../../components/widgets/BarGauge.js";
import { HealthTable, ProcessStateBadge, type Column } from "../../components/widgets/HealthTable.js";
import { Row } from "../../components/widgets/Row.js";
import { Sparkline } from "../../components/widgets/Sparkline.js";
import { formatBytes, formatDuration, formatMillis, formatPercent, NO_VALUE } from "../../lib/format.js";
import { VITAL } from "../../lib/metrics.js";
import { LEVEL, PROCESS_STATE } from "../../lib/status.js";
import { useOpenDrawer } from "../../hooks/drawer.js";
import { useDashStore } from "../../store/useDashStore.js";
import { ProcessSeriesChart } from "./ProcessSeriesChart.js";
import { beaconing, breachLevel, liveExchangeProcesses, shortKey, stateSummary } from "./common.js";

const NO_BREACHES: readonly ActiveBreach[] = [];

/** Worst first when sorted by state. */
const SEVERITY_ORDER = ["DEAD", "SILENT", "MISSING", "HUNG", "STOPPED", "DEGRADED", "HEALTHY"];

/** A figure that a process without a beacon (MISSING) does not have. */
function vital(p: ProcessHealth, show: () => string): string {
  return p.host === "" ? NO_VALUE : show();
}

/** `breaches`: the snapshot's active ones; loop age is coloured as pm-monitor judges it (I118). */
function columns(breaches: readonly ActiveBreach[]): Column<ProcessHealth>[] {
  return [
    { id: "state", header: "State", render: (p) => <ProcessStateBadge state={p.state} />, sortKey: (p) => SEVERITY_ORDER.indexOf(p.state) },
    {
      id: "key",
      header: "Process",
      render: (p) => (
        <span className="font-mono">
          {shortKey(p.key)}
          {p.restarted_recently && <span className={`ml-2 text-[10px] font-semibold ${PROCESS_STATE.STOPPED.text}`}>RESTARTED</span>}
        </span>
      ),
      sortKey: (p) => p.key,
    },
    { id: "uptime", header: "Up", render: (p) => vital(p, () => formatDuration(p.uptime_sec)), sortKey: (p) => (p.host ? p.uptime_sec : null), align: "right" },
    {
      id: "rss",
      header: "RSS",
      render: (p) => (
        <span className="inline-flex items-center justify-end gap-2">
          {vital(p, () => formatBytes(p.rss_bytes))}
          {p.spark.rss.length > 1 && <Sparkline values={p.spark.rss} width={48} />}
        </span>
      ),
      sortKey: (p) => (p.host ? p.rss_bytes : null),
      align: "right",
    },
    {
      id: "cpu",
      header: "CPU",
      render: (p) => (
        <span className="inline-flex items-center justify-end gap-2">
          {vital(p, () => formatPercent(p.cpu_pct))}
          {p.spark.cpu.length > 1 && <Sparkline values={p.spark.cpu} width={48} />}
        </span>
      ),
      sortKey: (p) => (p.host ? p.cpu_pct : null),
      align: "right",
    },
    {
      id: "loop",
      header: "Loop age",
      render: (p) => {
        const level = p.host ? breachLevel(breaches, "loop_age_ms", p.key) : null;
        return <span className={level && level !== "OK" ? LEVEL[level].text : undefined}>{vital(p, () => formatMillis(p.loop_age_ms))}</span>;
      },
      sortKey: (p) => (p.host ? p.loop_age_ms : null),
      align: "right",
    },
    { id: "lag", header: "Lag", render: (p) => vital(p, () => formatMillis(p.loop_lag_ms)), sortKey: (p) => (p.host ? p.loop_lag_ms : null), align: "right" },
  ];
}

export function ProcessesRow() {
  const processes = useDashStore((s) => s.snapshot?.processes ?? null);
  const breaches = useDashStore((s) => s.snapshot?.thresholds ?? NO_BREACHES);
  const open = useOpenDrawer();
  const summary = processes ? stateSummary(processes) : "";

  return (
    <Row id="processes" title="Processes" badge={summary || undefined} badgeTone="text-warning">
      <HealthTable
        label="Processes"
        columns={columns(breaches)}
        // Groups are shown in the order they first appear: the exchange's own first.
        rows={[...(processes ?? [])].sort((a, b) => Number(a.group === "BOT") - Number(b.group === "BOT"))}
        rowKey={(p) => p.key}
        group={(p) => (p.group === "BOT" ? "Participant bots" : "Exchange")}
        initialSort={{ id: "state", dir: "asc" }}
        onRowClick={(p) => open("process", p.key)}
      />
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <BarGauge
          label="Memory per process"
          // Current memory: a process whose beacons stopped has none (I118).
          items={liveExchangeProcesses(processes ?? [])
            .filter(beaconing)
            .map((p) => ({ label: shortKey(p.key), value: p.rss_bytes }))}
          format={formatBytes}
        />
        <ProcessSeriesChart label="CPU per process" name={VITAL.cpu} live={(p) => p.cpu_pct} format={formatPercent} />
      </div>
    </Row>
  );
}

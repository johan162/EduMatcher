/**
 * The process drawer (design §12.3): its state and figures, its vitals
 * over the picked range -- memory, CPU, threads, file descriptors, loop age
 * against its rule, loop lag -- its application metrics as last sent, its
 * events, and a link to its log records in log-gui.
 */

import { useParams } from "react-router-dom";
import type { HealthSnapshot, MetricSample, ProcessHealth } from "@edumatcher/dash-types";
import { Drawer } from "../../components/layout/Drawer.js";
import { HealthTable, ProcessStateBadge, type Column } from "../../components/widgets/HealthTable.js";
import { formatBytes, formatCount, formatDuration, formatMillis, formatPercent, NO_VALUE } from "../../lib/format.js";
import { logGuiUrl } from "../../lib/links.js";
import { VITAL } from "../../lib/metrics.js";
import { useDashStore } from "../../store/useDashStore.js";
import { SeriesChart } from "../charts.js";
import { beaconing, useRule } from "../rows/common.js";
import { CrossLink, Facts, Section, SubjectEvents, ToDashboard, Unavailable } from "./common.js";

const METRIC_COLUMNS: Column<MetricSample>[] = [
  { id: "name", header: "Metric", render: (m) => <span className="font-mono">{m.name}</span>, sortKey: (m) => m.name },
  { id: "label", header: "Label", render: (m) => <span className="font-mono">{m.label || NO_VALUE}</span>, sortKey: (m) => m.label },
  { id: "kind", header: "Kind", render: (m) => m.kind, sortKey: (m) => m.kind },
  { id: "value", header: "Value", render: (m) => formatCount(m.value), sortKey: (m) => m.value, align: "right" },
];

/** The same figure from a later snapshot, for a chart's live points; none while no beacons arrive (I118). */
const liveOf = (key: string, figure: (p: ProcessHealth) => number | null) => (snap: HealthSnapshot) => {
  const p = snap.processes.find((x) => x.key === key);
  return p && beaconing(p) ? figure(p) : null;
};

function Vitals({ p }: { p: ProcessHealth }) {
  const loopRule = useRule("loop_age_ms");
  const chart = { source: p.key, legend: p.key, height: 140 };
  return (
    <Section title="Vitals">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <SeriesChart label="Memory (RSS)" name={VITAL.rss} live={liveOf(p.key, (x) => x.rss_bytes)} format={formatBytes} {...chart} />
        <SeriesChart label="CPU" name={VITAL.cpu} live={liveOf(p.key, (x) => x.cpu_pct)} format={formatPercent} {...chart} />
        <SeriesChart label="Threads" name={VITAL.threads} live={liveOf(p.key, (x) => x.threads)} format={formatCount} integer {...chart} />
        <SeriesChart label="File descriptors" name={VITAL.fds} live={liveOf(p.key, (x) => x.fds)} format={formatCount} integer {...chart} />
        <SeriesChart label="Loop age" name={VITAL.loopAge} live={liveOf(p.key, (x) => x.loop_age_ms)} format={formatMillis} thresholds={loopRule} {...chart} />
        <SeriesChart label="Loop lag" name={VITAL.loopLag} live={liveOf(p.key, (x) => x.loop_lag_ms)} format={formatMillis} {...chart} />
      </div>
    </Section>
  );
}

export function ProcessDrawer() {
  const key = useParams()["*"] ?? "";
  const p = useDashStore((s) => s.snapshot?.processes.find((x) => x.key === key) ?? null);
  const logGui = useDashStore((s) => s.links?.logGui ?? null);
  if (key === "") return <ToDashboard />;
  if (!p) return <Unavailable kind="Process" title={key} what="process" />;

  const beaconing = p.host !== "";
  return (
    <Drawer kind="Process" title={p.key} actions={logGui && <CrossLink href={logGuiUrl(logGui, p.process)}>Logs in log-gui</CrossLink>}>
      <Facts
        label="Process figures"
        items={[
          ["State", <ProcessStateBadge key="state" state={p.state} />],
          ["Group", p.group === "BOT" ? "participant bot" : "exchange"],
          ["Instance", p.instance ?? NO_VALUE],
          ["Host", p.host || NO_VALUE],
          ["PID", beaconing ? String(p.pid) : NO_VALUE],
          ["Up", beaconing ? formatDuration(p.uptime_sec) : NO_VALUE],
          ["Last beacon", beaconing ? `${formatMillis(p.last_beacon_age_ms)} ago` : NO_VALUE],
          ["Restarted", p.restarted_recently ? "recently" : "no"],
          ["RSS", beaconing ? formatBytes(p.rss_bytes) : NO_VALUE],
        ]}
      />
      {beaconing ? (
        <>
          <Vitals p={p} />
          <Section title="Application metrics">
            {p.metrics.length === 0 ? (
              <p className="m-0 text-xs text-fg-faint">None sent</p>
            ) : (
              <HealthTable label="Application metrics" columns={METRIC_COLUMNS} rows={p.metrics} rowKey={(m) => `${m.name}|${m.label}`} initialSort={{ id: "name", dir: "asc" }} />
            )}
          </Section>
        </>
      ) : (
        <p className="mt-5 text-xs text-fg-subtle">No beacon from this process yet: it is expected by the profile but has not been seen.</p>
      )}
      <SubjectEvents subject={p.key} />
    </Drawer>
  );
}

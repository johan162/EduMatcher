/**
 * Every widget with synthetic data (WP-D2's "done when"): an unlinked page
 * at /widgets for checking them in both themes, and for building rows
 * against. Deterministic data, so two looks at it can be compared.
 */

import type { HealthEvent, Point } from "@edumatcher/dash-types";
import { BarGauge } from "../components/widgets/BarGauge.js";
import { EventLog } from "../components/widgets/EventLog.js";
import { Gauge } from "../components/widgets/Gauge.js";
import { HealthTable, ProcessStateBadge, type Column } from "../components/widgets/HealthTable.js";
import { RateBars } from "../components/widgets/RateBars.js";
import { Row } from "../components/widgets/Row.js";
import { Sparkline } from "../components/widgets/Sparkline.js";
import { StateTimeline } from "../components/widgets/StateTimeline.js";
import { StatTile } from "../components/widgets/StatTile.js";
import { TimeSeries } from "../components/widgets/TimeSeries.js";
import { formatBytes, formatCount, formatDuration, formatMicros, formatPercent, formatRate } from "../lib/format.js";
import { TONE } from "../lib/status.js";

const TZ = "Europe/Stockholm";
const END = Date.parse("2026-10-19T10:00:00Z");
const RANGE = { fromMs: END - 3600_000, toMs: END };
const MIN = 60_000;

/** A smooth, repeatable wave: no randomness, so the page looks the same each time. */
function wave(base: number, amp: number, phase: number, n = 60, step = MIN): Point[] {
  return Array.from({ length: n }, (_, i) => [RANGE.fromMs + i * step, base + amp * Math.sin(i / 6 + phase) + (amp / 3) * Math.sin(i / 1.7 + phase * 2)]);
}

const spark = (phase: number) => wave(50, 20, phase, 20).map(([, v]) => v);

const PARTICIPANTS = ["MM01", "MM02", "TRADER01", "TRADER02", "TRADER03", "TRADER04", "TRADER05", "TRADER06", "TRADER07", "TRADER08", "TRADER09"];

interface ProcessRow {
  key: string;
  state: "HEALTHY" | "DEGRADED" | "HUNG" | "MISSING" | "STOPPED";
  group: string;
  uptime: number;
  rss: number;
  cpu: number;
  spark: number[];
}

const PROCESSES: ProcessRow[] = [
  { key: "pm-engine@host", state: "HEALTHY", group: "Exchange", uptime: 18_720, rss: 412e6, cpu: 38, spark: spark(0) },
  { key: "pm-api-gwy/desk@host", state: "HEALTHY", group: "Exchange", uptime: 18_700, rss: 118e6, cpu: 6, spark: spark(1) },
  { key: "pm-stats@host", state: "DEGRADED", group: "Exchange", uptime: 18_690, rss: 96e6, cpu: 71, spark: spark(2) },
  { key: "pm-clearing@host", state: "HUNG", group: "Exchange", uptime: 18_680, rss: 88e6, cpu: 0, spark: spark(3) },
  { key: "pm-index", state: "MISSING", group: "Exchange", uptime: 0, rss: 0, cpu: 0, spark: [] },
  { key: "pm-mm-bot@host", state: "HEALTHY", group: "Participant bots", uptime: 9_000, rss: 61e6, cpu: 4, spark: spark(4) },
];

const COLUMNS: Column<ProcessRow>[] = [
  { id: "key", header: "Process", render: (r) => <span className="font-mono">{r.key}</span>, sortKey: (r) => r.key },
  { id: "state", header: "State", render: (r) => <ProcessStateBadge state={r.state} />, sortKey: (r) => r.state },
  { id: "uptime", header: "Up", render: (r) => formatDuration(r.uptime), sortKey: (r) => r.uptime, align: "right" },
  { id: "rss", header: "RSS", render: (r) => formatBytes(r.rss), sortKey: (r) => r.rss, align: "right" },
  {
    id: "cpu",
    header: "CPU",
    render: (r) => (
      <span className="inline-flex items-center gap-2">
        {formatPercent(r.cpu)} <Sparkline values={r.spark} width={48} />
      </span>
    ),
    sortKey: (r) => r.cpu,
    align: "right",
  },
];

const KINDS = [["CONNECT", "INFO"], ["DISCONNECT", "WARN"], ["PROCESS_STATUS", "CRIT"], ["THRESHOLD", "WARN"], ["SESSION", "INFO"]] as const;
const EVENTS: HealthEvent[] = Array.from({ length: 400 }, (_, i) => {
  const [kind, severity] = KINDS[i % KINDS.length]!;
  return {
    seq: i + 1,
    ts: new Date(RANGE.fromMs + i * 9_000).toISOString(),
    kind,
    severity,
    subject: kind === "PROCESS_STATUS" ? "pm-clearing@host" : PARTICIPANTS[i % PARTICIPANTS.length]!,
    detail: kind === "PROCESS_STATUS" ? "HEALTHY -> HUNG" : kind === "DISCONNECT" ? "heartbeat_timeout" : "",
  };
});

export function WidgetGallery() {
  return (
    <main className="flex h-full flex-col gap-4 overflow-y-auto bg-bg p-4 text-fg" aria-label="Widget gallery">
      <Row id="gallery-tiles" title="Stat tiles and gauges" badge="1 warning, 1 critical" badgeTone="text-warning">
        <div className="grid grid-cols-6 gap-3">
          <StatTile label="Processes" value={14} format={formatCount} sub="1 DEGRADED" />
          <StatTile label="Orders today" value={184_302} format={formatCount} sub={`~${formatRate(3071, "min")}`} spark={spark(0)} />
          <StatTile label="Engine p99" value={640} format={formatMicros} thresholds={{ warn: 500, crit: 2000 }} spark={spark(1)} />
          <StatTile label="Reject ratio" value={14.2} format={formatPercent} thresholds={{ warn: 5, crit: 10 }} colorMode="background" />
          <StatTile label="Disk free" value={12} format={formatPercent} thresholds={{ warn: 20, crit: 10, invert: true }} colorMode="background" />
          <StatTile label="Participants" value={null} format={formatCount} sub="no data" />
        </div>
        <div className="mt-4 flex gap-8">
          <Gauge label="CPU" value={62} format={(v) => formatPercent(v)} sub="host" thresholds={{ warn: 80, crit: 95 }} />
          <Gauge label="Memory" value={86} format={(v) => formatPercent(v)} sub="11.3 GiB" thresholds={{ warn: 80, crit: 95 }} />
          <Gauge label="Disk free" value={8} format={(v) => formatPercent(v)} sub="free" thresholds={{ warn: 20, crit: 10, invert: true }} mode="needle" />
          <Gauge label="Over range" value={130} format={(v) => formatPercent(v)} thresholds={{ warn: 80, crit: 95 }} />
        </div>
      </Row>

      <Row id="gallery-charts" title="Time series">
        <div className="grid grid-cols-2 gap-4">
          <TimeSeries
            label="CPU per process"
            series={[
              { label: "pm-engine", points: wave(38, 10, 0) },
              { label: "pm-stats", points: wave(70, 12, 1) },
              { label: "pm-api-gwy", points: wave(6, 3, 2) },
            ]}
            range={RANGE}
            tz={TZ}
            format={(v) => formatPercent(v)}
            thresholds={{ warn: 80, crit: 95 }}
          />
          <TimeSeries
            label="Exchange memory"
            stacked
            series={PROCESSES.slice(0, 4).map((p, i) => ({ label: p.key, points: wave(p.rss, p.rss / 20, i) }))}
            range={RANGE}
            tz={TZ}
            format={formatBytes}
          />
          <RateBars
            label="Orders per minute"
            series={PARTICIPANTS.map((id, i) => ({ label: id, points: wave(40 - i * 3, 10, i).map(([t, v]) => [t, Math.max(0, Math.round(v))] as Point) }))}
            range={RANGE}
            bucketMs={MIN}
            tz={TZ}
            format={formatCount}
          />
          <BarGauge
            label="Memory per process"
            items={PROCESSES.map((p) => ({ label: p.key.split("@")[0]!, value: p.rss }))}
            format={formatBytes}
            thresholds={{ warn: 300e6, crit: 400e6 }}
            limit={4}
          />
        </div>
      </Row>

      <Row id="gallery-tables" title="Timeline, tables and log">
        <StateTimeline
          label="Participant connections"
          lanes={PARTICIPANTS.slice(0, 5).map((id, i) => ({
            id,
            segments: [
              { from: RANGE.fromMs - 10 * MIN, to: RANGE.fromMs + (10 + i * 5) * MIN, state: "CONNECTED" },
              { from: RANGE.fromMs + (14 + i * 5) * MIN, to: RANGE.toMs + MIN, state: "CONNECTED" },
            ],
            marks: i % 2 ? [{ ts: RANGE.fromMs + (10 + i * 5) * MIN, kind: "HEARTBEAT_TIMEOUT" }] : [],
          }))}
          range={RANGE}
          states={{ CONNECTED: { label: "connected", color: TONE.ok.color } }}
          marks={{ HEARTBEAT_TIMEOUT: { label: "heartbeat timeout", color: TONE.error.color } }}
          tz={TZ}
        />
        <div className="mt-4">
          <HealthTable
            label="Processes"
            columns={COLUMNS}
            rows={PROCESSES}
            rowKey={(r) => r.key}
            group={(r) => r.group}
            initialSort={{ id: "rss", dir: "desc" }}
          />
        </div>
        <div className="mt-4">
          <EventLog label="Event log" events={EVENTS} tz={TZ} />
        </div>
      </Row>

      <EdgeCases />
    </main>
  );
}

const LONG = "pm-api-gwy/dashboards@a-rather-long-host-name.example.internal";

/**
 * What breaks widgets: long labels and values, no values, values that are
 * not numbers, negatives, empty data, many series, a narrow column. The
 * e2e suite checks in Chrome that nothing here overflows its widget.
 */
function EdgeCases() {
  const many = Array.from({ length: 12 }, (_, i) => ({ label: `pm-process-${i + 1}@host`, points: wave(10 + i * 5, 4, i) }));
  const late = [
    { label: "started late", points: wave(30, 5, 0).slice(25) },
    { label: "stopped early", points: wave(20, 5, 1).slice(0, 40) },
    { label: "all along", points: wave(10, 3, 2) },
  ];
  return (
    <Row id="gallery-edges" title="Edge cases" badge={`a badge long enough to need cutting: ${LONG} ${LONG}`}>
      <div className="grid grid-cols-[repeat(3,minmax(0,220px))_minmax(0,1fr)] gap-3">
        <StatTile label={`${LONG} label`} value={123_456_789_012} format={formatBytes} sub={LONG} spark={[1, Number.NaN, 3, 2]} thresholds={{ warn: 1, crit: 2 }} />
        <StatTile label="Not a number" value={Number.NaN} format={formatPercent} thresholds={{ warn: 5 }} colorMode="background" />
        <StatTile label="Negative" value={-0.04} format={formatPercent} spark={[5, 5, 5, 5]} sub="flat spark" />
        <div className="flex flex-wrap gap-2">
          <Gauge label={`Long ${LONG}`} value={1_234_567_890} max={2e9} format={formatBytes} sub={LONG} thresholds={{ warn: 1e9, crit: 1.5e9 }} size={140} />
          <Gauge label="No value" value={null} format={formatPercent} thresholds={{ warn: 80 }} size={140} />
          <Gauge label="Empty scale" value={5} min={10} max={10} format={formatPercent} size={140} />
        </div>
        <BarGauge
          label="Edge bars"
          items={[
            { label: LONG, value: 3e9 },
            { label: "negative", value: -5 },
            { label: "not a number", value: Number.NaN },
            { label: "zero", value: 0 },
          ]}
          format={formatBytes}
          thresholds={{ warn: 1e9 }}
        />
        <BarGauge label="No bars" items={[]} format={formatBytes} />
        <HealthTable label="Narrow table" columns={COLUMNS} rows={PROCESSES.slice(0, 3)} rowKey={(r) => r.key} />
        <EventLog
          label="Narrow log"
          height={110}
          events={EVENTS.slice(0, 3).map((e) => ({ ...e, subject: LONG, detail: `${LONG} ${LONG}` }))}
          tz={TZ}
        />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4">
        <TimeSeries label="Twelve series" series={many} range={RANGE} tz={TZ} format={(v) => formatPercent(v)} />
        <TimeSeries label="Gaps, stacked" stacked series={late} range={RANGE} tz={TZ} format={formatCount} integer />
        <TimeSeries label="No data" series={[]} range={RANGE} tz={TZ} format={formatCount} />
        <RateBars label="Quiet stretch" series={[{ label: "MM01", points: wave(20, 5, 0).filter((_p, i) => i < 15 || i > 40) }]} range={RANGE} bucketMs={MIN} tz={TZ} format={formatCount} />
        <StateTimeline
          label="Edge timeline"
          lanes={[
            { id: LONG, segments: [{ from: RANGE.fromMs + 30 * MIN, to: RANGE.fromMs + 30 * MIN + 500, state: "CONNECTED" }] },
            { id: "backwards", segments: [{ from: RANGE.toMs, to: RANGE.fromMs, state: "CONNECTED" }] },
          ]}
          range={RANGE}
          states={{ CONNECTED: { label: "connected", color: TONE.ok.color } }}
          tz={TZ}
        />
        <EventLog label="No events" events={[]} tz={TZ} height={60} />
      </div>
    </Row>
  );
}

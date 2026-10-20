import {
  DEFAULT_MONITOR,
  DEFAULT_MONITOR_THRESHOLDS,
  INVERTED_THRESHOLD_RULES,
  MONITOR_THRESHOLD_RULES,
  type MonitorConfigDraft,
  type MonitorThresholdRule,
} from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { usePersona } from "@/lib/usePersona";
import { Panel, Section } from "@/components/layout/Panel";
import { FieldRow, type FieldHelp } from "@/components/fields/FieldRow";
import { NumberInput, TextInput } from "@/components/fields/inputs";
import { Switch } from "@/components/ui/Switch";

const DOC =
  "../docs/books/operator-guide/part-6-observe-and-recover/060-health-monitor.md";

/** What each threshold rule watches, and its unit, for the table. */
const RULE_INFO: Record<
  MonitorThresholdRule,
  { label: string; unit: string; text: string }
> = {
  host_cpu_pct: {
    label: "Host CPU",
    unit: "%",
    text: "CPU use of the whole host.",
  },
  host_mem_pct: {
    label: "Host memory",
    unit: "%",
    text: "Memory use of the whole host.",
  },
  disk_free_pct: {
    label: "Disk free",
    unit: "%",
    text: "Free space on the data directory's file system.",
  },
  engine_handle_p99_us: {
    label: "Engine latency p99",
    unit: "µs",
    text: "99th-percentile time the engine takes to handle one request.",
  },
  reject_pct_5m: {
    label: "Reject rate (5 min)",
    unit: "%",
    text: "Share of inbound requests (orders, cancels, amends, quotes) the engine rejected over five minutes, judged from 20 requests.",
  },
  rss_growth_pct_1h: {
    label: "Memory growth (1 h)",
    unit: "%",
    text: "Growth of one process's resident memory over the last hour -- a leak. Judged once the process has been watched for 10 minutes.",
  },
  heap_garbage_pct: {
    label: "Book heap garbage",
    unit: "%",
    text: "Share of stale, lazily deleted entries in one symbol's order-book heaps, judged from 100 entries.",
  },
};

/**
 * The `monitor` block (design: EduMatcher-Config-GUI-Monitor-Extension.md §3).
 * Intermediate sees timing, retention and thresholds; Expert also the
 * network endpoints and the book-metrics interval.
 */
export function MonitorTab() {
  const m = useDraftStore((s) => s.draft.monitor);
  const update = useDraftStore((s) => s.update);
  const { canSee } = usePersona();
  const set = (fn: (mon: MonitorConfigDraft) => void) =>
    update((d) => fn(d.monitor));

  return (
    <Panel
      tabId="monitor"
      title="Health Monitoring"
      intro="Every pm-* process sends a small health beacon every few seconds; pm-monitor collects them, judges each process HEALTHY, DEGRADED, HUNG, SILENT or DEAD, keeps a metrics history, and raises alerts when a threshold is crossed. Shown by pm-monitor-cli and the operator dashboard."
    >
      <Section title="Monitoring">
        <FieldRow
          label="Write monitor section"
          path="monitor.include"
          help={{
            text: "Write the `monitor` block to the file. When off the block is left out and every process -- and pm-monitor -- runs on the defaults shown here: monitoring stays on. Use the switch below to turn it off.",
            cliFlag: "--monitor",
            docHref: DOC,
          }}
        >
          <Switch
            aria-label="Write monitor section"
            checked={m.include}
            onCheckedChange={(v) => set((mon) => (mon.include = v))}
          />
        </FieldRow>
        {m.include && (
          <FieldRow
            label="Monitoring enabled"
            path="monitor.enabled"
            help={{
              text: "When off no process sends beacons and pm-monitor, if started, idles. Nothing else changes.",
              cliFlag: "--monitor-disabled",
            }}
          >
            <Switch
              aria-label="Monitoring enabled"
              checked={m.enabled}
              onCheckedChange={(v) => set((mon) => (mon.enabled = v))}
            />
          </FieldRow>
        )}
      </Section>

      {m.include && (
        <>
          <Section
            title="Liveness"
            description="How often processes report, and how long a stall may last before pm-monitor calls a process HUNG (beacons arrive but its main loop has stopped) or SILENT / DEAD (no beacons at all; DEAD once its process is gone)."
          >
            <MonNum
              label="Beacon interval"
              unit="sec"
              path="monitor.beaconIntervalSec"
              value={m.beaconIntervalSec}
              def={DEFAULT_MONITOR.beaconIntervalSec}
              step={0.5}
              onChange={(v) => set((mon) => (mon.beaconIntervalSec = v))}
              help={{
                text: "Seconds between two beacons from each process. Shorter detects trouble faster and costs a little more traffic.",
                cliFlag: "--monitor-beacon-interval-sec",
              }}
            />
            <MonNum
              label="Hung after"
              unit="sec"
              path="monitor.hungAfterSec"
              value={m.hungAfterSec}
              def={DEFAULT_MONITOR.hungAfterSec}
              step={0.5}
              onChange={(v) => set((mon) => (mon.hungAfterSec = v))}
              help={{
                text: "A process whose main loop has not completed an iteration for this long is HUNG, even though its beacon thread still reports. A process still starting up gets 120 s. Must be longer than the beacon interval.",
                cliFlag: "--monitor-hung-after-sec",
              }}
            />
            <MonNum
              label="Silent after"
              unit="beacons"
              path="monitor.silentAfterBeacons"
              value={m.silentAfterBeacons}
              def={DEFAULT_MONITOR.silentAfterBeacons}
              step={1}
              onChange={(v) => set((mon) => (mon.silentAfterBeacons = v))}
              help={{
                text: "Beacon intervals without a beacon before a process is SILENT -- or DEAD, when its process no longer exists. One late beacon is normal, so keep this at 2 or more.",
                cliFlag: "--monitor-silent-after-beacons",
              }}
            />
            {canSee("E") && (
              <MonNum
                label="Book metrics interval"
                unit="sec"
                path="monitor.bookMetricsIntervalSec"
                value={m.bookMetricsIntervalSec}
                def={DEFAULT_MONITOR.bookMetricsIntervalSec}
                step={1}
                onChange={(v) => set((mon) => (mon.bookMetricsIntervalSec = v))}
                help={{
                  text: "How often the engine measures its order books (depth, heap garbage) for the beacon. These scans cost engine time, so this is slower than the beacon.",
                  cliFlag: "--monitor-book-metrics-interval-sec",
                }}
              />
            )}
          </Section>

          <Section
            title="History"
            description="pm-monitor keeps every sample for a short window, then one-minute averages for longer, in data/metrics.db."
          >
            <MonNum
              label="Raw samples kept"
              unit="hours"
              path="monitor.rawHours"
              value={m.rawHours}
              def={DEFAULT_MONITOR.rawHours}
              step={1}
              onChange={(v) => set((mon) => (mon.rawHours = v))}
              help={{
                text: "Hours of full-resolution samples kept.",
                cliFlag: "--monitor-raw-hours",
              }}
            />
            <MonNum
              label="Minute averages kept"
              unit="days"
              path="monitor.minuteDays"
              value={m.minuteDays}
              def={DEFAULT_MONITOR.minuteDays}
              step={1}
              onChange={(v) => set((mon) => (mon.minuteDays = v))}
              help={{
                text: "Days of one-minute averages kept.",
                cliFlag: "--monitor-minute-days",
              }}
            />
          </Section>

          <Section
            title="Alert thresholds"
            description="Crossing warn raises a warning event and makes its subject DEGRADED (a process, or the exchange status for host, reject and book rules); crossing crit raises a critical one. Warn must be below crit -- except for disk free, where lower is worse."
          >
            <ThresholdTable m={m} set={set} />
          </Section>

          {canSee("E") && (
            <Section
              title="Network"
              description="pm-monitor binds bind_address; every process sends its beacons to host. They differ when pm-monitor binds a wildcard (0.0.0.0) and processes reach it by name, or when it runs on another machine."
            >
              <MonText
                label="Bind address"
                path="monitor.bindAddress"
                value={m.bindAddress}
                def={DEFAULT_MONITOR.bindAddress}
                onChange={(v) => set((mon) => (mon.bindAddress = v))}
                help={{
                  text: "Interface pm-monitor listens on. 127.0.0.1 keeps it local; 0.0.0.0 accepts beacons from other hosts. EDUMATCHER_GATEWAY_BIND_HOST overrides it at run time.",
                  cliFlag: "--monitor-bind-address",
                }}
              />
              <MonText
                label="Host"
                path="monitor.host"
                value={m.host}
                def={DEFAULT_MONITOR.host}
                onChange={(v) => set((mon) => (mon.host = v))}
                help={{
                  text: "Address every process sends its beacons to, and pm-monitor-cli connects to. Must reach the bind address.",
                  cliFlag: "--monitor-host",
                }}
              />
              <MonNum
                label="Beacon (PULL) port"
                path="monitor.pullPort"
                value={m.pullPort}
                def={DEFAULT_MONITOR.pullPort}
                step={1}
                onChange={(v) => set((mon) => (mon.pullPort = v))}
                help={{
                  text: "ZeroMQ port pm-monitor receives beacons on.",
                  cliFlag: "--monitor-pull-port",
                }}
              />
              <MonNum
                label="Publish (PUB) port"
                path="monitor.pubPort"
                value={m.pubPort}
                def={DEFAULT_MONITOR.pubPort}
                step={1}
                onChange={(v) => set((mon) => (mon.pubPort = v))}
                help={{
                  text: "ZeroMQ port pm-monitor publishes health snapshots and events on (read by pm-monitor-cli and the dashboard). Must differ from the beacon port.",
                  cliFlag: "--monitor-pub-port",
                }}
              />
            </Section>
          )}
        </>
      )}
    </Panel>
  );
}

function ThresholdTable({
  m,
  set,
}: {
  m: MonitorConfigDraft;
  set: (fn: (mon: MonitorConfigDraft) => void) => void;
}) {
  return (
    <table className="w-full max-w-3xl text-sm">
      <thead>
        <tr className="border-b border-border text-left text-fg-subtle">
          <th className="py-1.5 pr-3 font-medium">Rule</th>
          <th className="py-1.5 pr-3 font-medium">Warn</th>
          <th className="py-1.5 pr-3 font-medium">Crit</th>
          <th className="py-1.5 font-medium" />
        </tr>
      </thead>
      <tbody>
        {MONITOR_THRESHOLD_RULES.map((rule) => {
          const info = RULE_INFO[rule];
          const band = m.thresholds[rule];
          const def = DEFAULT_MONITOR_THRESHOLDS[rule];
          const changed = band.warn !== def.warn || band.crit !== def.crit;
          return (
            <tr
              key={rule}
              className="border-b border-border/50 align-top"
              data-field-path={`monitor.thresholds.${rule}`}
            >
              <td className="py-2 pr-3">
                <div className="font-medium">{info.label}</div>
                <div className="font-mono text-xs text-fg-subtle">{rule}</div>
                <div className="mt-0.5 max-w-xs text-xs text-fg-subtle">
                  {info.text}
                  {INVERTED_THRESHOLD_RULES.has(rule) && " (lower is worse)"}
                </div>
              </td>
              <td className="py-2 pr-3">
                <div className="flex items-center gap-1">
                  <NumberInput
                    aria-label={`${info.label} warn`}
                    value={band.warn}
                    min={0}
                    onChange={(v) =>
                      set((mon) => (mon.thresholds[rule].warn = v ?? def.warn))
                    }
                  />
                  <span className="text-fg-subtle">{info.unit}</span>
                </div>
              </td>
              <td className="py-2 pr-3">
                <div className="flex items-center gap-1">
                  <NumberInput
                    aria-label={`${info.label} crit`}
                    value={band.crit}
                    min={0}
                    onChange={(v) =>
                      set((mon) => (mon.thresholds[rule].crit = v ?? def.crit))
                    }
                  />
                  <span className="text-fg-subtle">{info.unit}</span>
                </div>
              </td>
              <td className="py-2">
                {changed && (
                  <button
                    type="button"
                    className="text-xs text-accent hover:underline"
                    onClick={() =>
                      set(
                        (mon) =>
                          (mon.thresholds[rule] = {
                            warn: def.warn,
                            crit: def.crit,
                          }),
                      )
                    }
                  >
                    Reset ({def.warn} / {def.crit})
                  </button>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function MonNum({
  label,
  unit,
  path,
  value,
  def,
  step,
  onChange,
  help,
}: {
  label: string;
  unit?: string;
  path: string;
  value: number;
  def: number;
  step: number;
  onChange: (v: number) => void;
  help: FieldHelp;
}) {
  return (
    <FieldRow
      label={label}
      path={path}
      help={help}
      defaultHint={`Default: ${def}`}
      isSet={value !== def}
      onReset={() => onChange(def)}
    >
      <NumberInput
        aria-label={label}
        value={value}
        min={0}
        step={step}
        onChange={(v) => onChange(v ?? def)}
      />
      {unit && <span className="text-sm text-fg-subtle">{unit}</span>}
    </FieldRow>
  );
}

function MonText({
  label,
  path,
  value,
  def,
  onChange,
  help,
}: {
  label: string;
  path: string;
  value: string;
  def: string;
  onChange: (v: string) => void;
  help: FieldHelp;
}) {
  return (
    <FieldRow
      label={label}
      path={path}
      help={help}
      defaultHint={`Default: ${def}`}
      isSet={value !== def}
      onReset={() => onChange(def)}
    >
      <TextInput
        aria-label={label}
        value={value}
        onChange={onChange}
        className="w-64"
      />
    </FieldRow>
  );
}

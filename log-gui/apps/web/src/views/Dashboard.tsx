/** Dashboard (design §8): "is anything wrong right now?" from across a room. */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Link } from "react-router-dom";
import clsx from "clsx";
import { classifyErrorRate, type ErrorRateBand } from "@edumatcher/log-types";
import { api } from "../lib/api.js";
import { useUiConfig } from "../lib/useUiConfig.js";
import { useLiveStore } from "../store/useLiveStore.js";
import { Panel } from "../components/Panel.js";
import { SeverityBadge } from "../components/SeverityBadge.js";

/** Colour per band — the whole point of ERROR_RATE_*: a number you can glance at. */
const BAND_CLASS: Record<ErrorRateBand, string> = {
  normal: "text-fg",
  elevated: "text-level-warning",
  high: "text-level-error",
  severe: "text-level-critical",
};

const BAND_LABEL: Record<ErrorRateBand, string> = {
  normal: "normal",
  elevated: "elevated",
  high: "high",
  severe: "SEVERE",
};

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: "var(--level-debug)",
  INFO: "var(--level-info)",
  WARNING: "var(--level-warning)",
  ERROR: "var(--level-error)",
  CRITICAL: "var(--level-critical)",
};

function MeterTile({
  label,
  big,
  sub,
  bigClass,
}: {
  label: string;
  big: React.ReactNode;
  sub?: React.ReactNode;
  bigClass?: string;
}) {
  return (
    <div className="rounded border border-border bg-bg-subtle p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-fg-subtle">{label}</div>
      <div className={clsx("mt-1 text-2xl font-semibold tabular-nums", bigClass)}>{big}</div>
      {sub && <div className="mt-1 text-xs text-fg-subtle">{sub}</div>}
    </div>
  );
}

export function DashboardView() {
  const [window_] = useState("1h");
  const counters = useLiveStore((s) => s.counters);
  const serverState = useLiveStore((s) => s.serverState);
  const uiConfig = useUiConfig();
  const errorBand: ErrorRateBand | undefined =
    counters && uiConfig ? classifyErrorRate(counters.errorsPerMin, uiConfig.errorRate) : undefined;

  const { data: summary } = useQuery({
    queryKey: ["stats", "summary"],
    queryFn: api.statsSummary,
    refetchInterval: 30_000,
  });
  const { data: timeseries } = useQuery({
    queryKey: ["stats", "timeseries", window_],
    queryFn: () => api.timeseries(window_, "1m"),
    refetchInterval: 30_000,
  });
  const { data: unacked } = useQuery({
    queryKey: ["issues", { acked: false, minLevel: uiConfig?.alertLevel }],
    queryFn: () => api.issues({ acked: false, minLevel: uiConfig?.alertLevel }),
    enabled: uiConfig !== undefined,
    refetchInterval: 15_000,
  });
  const { data: byProcess } = useQuery({
    queryKey: ["stats", "by-process", window_, "ERROR"],
    queryFn: () => api.byProcess(window_, "ERROR"),
    refetchInterval: 30_000,
  });
  const { data: recentErrors } = useQuery({
    queryKey: ["logs", "recent-errors"],
    queryFn: () => api.logs({ minLevel: "ERROR" }, { limit: 5 }),
    refetchInterval: 15_000,
  });

  const unackedIssues = unacked?.issues ?? [];
  const worst = unackedIssues[0];

  const chartData = (timeseries?.buckets ?? []).map((b) => ({
    time: b.bucketStart.slice(11, 16),
    count: b.count ?? 0,
  }));

  return (
    <div className="flex flex-col gap-4 p-4">
      {unackedIssues.length > 0 && (
        <div
          className={clsx(
            "alert-pulse rounded border-2 border-level-error bg-level-error/10 p-3",
          )}
        >
          <div className="flex items-center justify-between">
            <span className="font-semibold text-level-error">
              ⚠ {unackedIssues.length} UNACKNOWLEDGED ISSUE{unackedIssues.length === 1 ? "" : "S"}
              {worst && ` — most recent from ${worst.process}`}
            </span>
            <Link to="/alerts" className="rounded bg-level-error px-3 py-1 text-sm font-semibold text-white">
              View alerts
            </Link>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <MeterTile label="Total events" big={summary?.server.total_log_events.toLocaleString() ?? "—"} />
        <MeterTile
          label="Error rate"
          big={counters ? `${counters.errorsPerMin.toFixed(1)}/min` : "—"}
          bigClass={errorBand ? BAND_CLASS[errorBand] : undefined}
          sub={errorBand ? BAND_LABEL[errorBand] : undefined}
        />
        <MeterTile label="Warnings" big={counters?.perLevel.WARNING ?? 0} sub="last 60s" />
        <MeterTile label="Processes" big={summary?.perProcess.length ?? "—"} />
        <MeterTile label="Log server" big={serverState?.state ?? "—"} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Events over time">
          <div style={{ width: "100%", height: 240 }}>
            <ResponsiveContainer>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="time" tick={{ fill: "var(--fg-subtle)", fontSize: 11 }} />
                <YAxis tick={{ fill: "var(--fg-subtle)", fontSize: 11 }} />
                <Tooltip contentStyle={{ background: "var(--bg-subtle)", border: "1px solid var(--border)" }} />
                <Bar dataKey="count" fill="var(--accent)" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Top processes by error count">
          <div style={{ width: "100%", height: 240 }}>
            <ResponsiveContainer>
              <BarChart layout="vertical" data={byProcess?.processes ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis type="number" tick={{ fill: "var(--fg-subtle)", fontSize: 11 }} />
                <YAxis
                  type="category"
                  dataKey="process"
                  width={100}
                  tick={{ fill: "var(--fg-subtle)", fontSize: 11 }}
                />
                <Tooltip contentStyle={{ background: "var(--bg-subtle)", border: "1px solid var(--border)" }} />
                <Bar dataKey="n" fill="var(--level-error)" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>

      <Panel title="Recent errors">
        <div className="flex flex-col gap-1">
          {(recentErrors?.rows ?? []).map((row) => (
            <div key={row.seq} className="flex items-center gap-2 font-mono text-xs">
              <span className="text-fg-subtle">{row.client_ts.slice(11, 19)}</span>
              <SeverityBadge level={row.level} />
              <span className="text-fg-subtle">{row.process}</span>
              <span className="truncate">{row.message}</span>
            </div>
          ))}
          {(recentErrors?.rows.length ?? 0) === 0 && <div className="text-sm text-fg-subtle">No recent errors.</div>}
        </div>
      </Panel>
    </div>
  );
}

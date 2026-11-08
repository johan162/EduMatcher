/**
 * Row 7, REST API: what the API gateways are asked to do. Per gateway
 * instance: requests per second now and over the last hour, the busiest
 * second since it started and the key behind it, the total since it
 * started, and what the rate limiter refused; then one line per API key, so
 * the key that loads the exchange (or is being throttled) stands out.
 *
 * Keys are named by their configured description, never by the key.
 * Throttling is judged by pm-monitor on its increase over five minutes
 * (`api_throttled`); the tile's colour is that breach.
 */

import clsx from "clsx";
import { useMemo } from "react";
import type { ApiKeyStats, ApiStats, RangeName, RateByLabelResponse } from "@edumatcher/dash-types";
import { HealthTable, type Column } from "../../components/widgets/HealthTable.js";
import { RateBars } from "../../components/widgets/RateBars.js";
import { Row } from "../../components/widgets/Row.js";
import { StatTile } from "../../components/widgets/StatTile.js";
import { useChartRange, useHistory } from "../../hooks/history.js";
import { getJson, query, rateBucket } from "../../lib/api.js";
import { formatCount, formatPercent, formatRate } from "../../lib/format.js";
import { COUNTER } from "../../lib/metrics.js";
import { useDashStore } from "../../store/useDashStore.js";
import { NO_SERIES } from "../charts.js";
import { shortKey, useBreachLevel } from "./common.js";

/** A key's table row: the key with the gateway's peak holder, to mark it. */
type KeyRow = ApiKeyStats & { holdsPeak: boolean };

const COLUMNS: Column<KeyRow>[] = [
  { id: "key", header: "API key", render: (k) => <span className="font-mono">{k.label}</span>, sortKey: (k) => k.label },
  { id: "total", header: "Requests", render: (k) => formatCount(k.requests_total), sortKey: (k) => k.requests_total, align: "right" },
  { id: "today", header: "Today", render: (k) => formatCount(k.requests_today), sortKey: (k) => k.requests_today, align: "right" },
  { id: "now", header: "/s now", render: (k) => formatRate(k.per_sec_now, "s"), sortKey: (k) => k.per_sec_now, align: "right" },
  { id: "hour", header: "/s last hour", render: (k) => formatRate(k.per_sec_hour, "s"), sortKey: (k) => k.per_sec_hour, align: "right" },
  { id: "share", header: "Share", render: (k) => formatPercent(k.share_pct), sortKey: (k) => k.share_pct, align: "right" },
  {
    id: "peak",
    header: "Peak /s",
    render: (k) => (
      <span className={clsx(k.holdsPeak && "font-semibold text-warning")}>
        {formatCount(k.peak_per_sec)}
        {k.holdsPeak && " ▲"}
      </span>
    ),
    sortKey: (k) => k.peak_per_sec,
    align: "right",
  },
  {
    id: "throttled",
    header: "Throttled",
    render: (k) => <span className={clsx(k.throttled_5m > 0 && "font-semibold text-warning")}>{formatCount(k.throttled_total)}</span>,
    sortKey: (k) => k.throttled_total,
    align: "right",
  },
  { id: "throttled5", header: "Throttled 5 min", render: (k) => formatCount(k.throttled_5m), sortKey: (k) => k.throttled_5m, align: "right" },
];

const formatPerSec = (v: number) => formatRate(v, "s");

/**
 * Requests per second by API key over the picked range, and the writes
 * throttled per bucket, from metrics.db's counter increments summed over
 * the API gateway instances. The series are stored as counts per bucket;
 * the first chart divides them into a rate.
 */
function ApiCharts() {
  const tz = useDashStore((s) => s.sessionTz);
  const { bucketMs } = rateBucket(useDashStore((s) => s.range));
  const range = useChartRange(bucketMs);
  const byKey = (name: string) => (r: RangeName, signal: AbortSignal) =>
    getJson<RateByLabelResponse>(`/api/rate/by-label?${query({ name, range: r, bucket: rateBucket(r).bucket })}`, signal);
  const requests = useHistory<RateByLabelResponse>("api-requests-by-key", byKey(COUNTER.apiKeyRequests));
  const throttled = useHistory<RateByLabelResponse>("api-throttled-by-key", byKey(COUNTER.apiKeyThrottled));
  // Once per fetch, not per snapshot: a new array each render would redraw the chart every second (I118).
  const perSec = useMemo(
    () => requests.data?.series.map((s) => ({ label: s.label, points: s.points.map(([ts, n]): [number, number] => [ts, n / (bucketMs / 1000)]) })) ?? NO_SERIES,
    [requests.data, bucketMs],
  );
  return (
    <div className="mb-5 grid grid-cols-1 gap-4 xl:grid-cols-2">
      <RateBars label="API requests / s by key" series={perSec} range={range} bucketMs={bucketMs} tz={tz} format={formatPerSec} allowDecimals />
      <RateBars label="API throttled by key" series={throttled.data?.series ?? NO_SERIES} range={range} bucketMs={bucketMs} tz={tz} format={formatCount} />
    </div>
  );
}

function Gateway({ api }: { api: ApiStats }) {
  // This instance's breach only: another instance being throttled is its own tile.
  const throttledLevel = useBreachLevel("api_throttled", api.key);
  const rows = useMemo(() => api.keys.map((k): KeyRow => ({ ...k, holdsPeak: k.label === api.peak_key })), [api.keys, api.peak_key]);
  return (
    <section aria-label={`REST API ${shortKey(api.key)}`} className="min-w-0">
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">{shortKey(api.key)}</h3>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <StatTile label="API requests / s" value={api.per_sec_now} format={(v) => formatRate(v, "s")} sub="last 60 s" />
        <StatTile label="API requests / s, last hour" value={api.per_sec_hour} format={(v) => formatRate(v, "s")} sub="average" />
        <StatTile
          label="API peak / s"
          value={api.peak_per_sec}
          format={formatCount}
          sub={api.peak_key ? `since start; ${api.peak_key}` : "since start"}
        />
        <StatTile label="API requests" value={api.requests_total} format={formatCount} sub={`since start; ${formatCount(api.requests_today)} today`} />
        <StatTile
          label="API throttled"
          value={api.throttled_total}
          format={formatCount}
          level={throttledLevel}
          sub={`since start; ${formatCount(api.throttled_5m)} in 5 min`}
        />
      </div>
      <div className="mt-3">
        <HealthTable label="API keys" columns={COLUMNS} rows={rows} rowKey={(k) => k.label} initialSort={{ id: "now", dir: "desc" }} />
      </div>
    </section>
  );
}

export function ApiRow() {
  const api = useDashStore((s) => s.snapshot?.api ?? null);
  const throttled = api?.reduce((sum, a) => sum + a.throttled_5m, 0) ?? 0;

  return (
    <Row id="api" title="REST API" badge={throttled > 0 ? `${formatCount(throttled)} throttled in 5 min` : undefined} badgeTone="text-warning">
      {api === null || api.length === 0 ? (
        <p className="text-xs text-fg-faint">No API gateway is reporting</p>
      ) : (
        <div>
          <ApiCharts />
          <div className="space-y-5">
            {api.map((a) => (
              <Gateway key={a.key} api={a} />
            ))}
          </div>
        </div>
      )}
    </Row>
  );
}

/**
 * Row 3, TRADING ACTIVITY (design §12.3): orders per minute by participant
 * (top 8 + other), trades and traded value per minute, today's averages,
 * and the reject ratio as pm-monitor judges it, with its threshold bands.
 *
 * Built from counter increments (/api/rate), refetched every refresh
 * interval: a rate bucket is complete only when its minute is, so these
 * panels are not extended point by point between fetches.
 *
 * As built: §12.3's "trades/min + traded value (dual axis)" is two charts
 * side by side, one axis each -- one scale per chart reads unambiguously.
 */

import type { RateByLabelResponse, RateResponse } from "@edumatcher/dash-types";
import { RateBars } from "../../components/widgets/RateBars.js";
import { Row } from "../../components/widgets/Row.js";
import { StatTile } from "../../components/widgets/StatTile.js";
import { TimeSeries } from "../../components/widgets/TimeSeries.js";
import { useChartRange, useHistory } from "../../hooks/history.js";
import { getJson, query, rateBucket } from "../../lib/api.js";
import { formatCompact, formatCount, formatPercent, formatRate } from "../../lib/format.js";
import { COUNTER, REQUEST_COUNTERS } from "../../lib/metrics.js";
import { useDashStore } from "../../store/useDashStore.js";
import { useMemo } from "react";
import { CounterBars, NO_SERIES } from "../charts.js";
import { rejectRatio, useAnnotations, useRule } from "./common.js";

function useBucket() {
  return rateBucket(useDashStore((s) => s.range));
}

function OrdersByParticipant() {
  const tz = useDashStore((s) => s.sessionTz);
  const { bucketMs } = useBucket();
  const history = useHistory<RateByLabelResponse>("orders-by-participant", (range, signal) =>
    getJson(`/api/rate/by-label?${query({ name: COUNTER.ordersIn, range, bucket: rateBucket(range).bucket })}`, signal),
  );
  const range = useChartRange(bucketMs);
  return <RateBars label="Orders per minute by participant" series={history.data?.series ?? NO_SERIES} range={range} bucketMs={bucketMs} tz={tz} format={formatCount} />;
}

function RejectRatio() {
  const tz = useDashStore((s) => s.sessionTz);
  const { bucketMs } = useBucket();
  const rule = useRule("reject_pct_5m");
  const annotations = useAnnotations();
  const history = useHistory<{ rejects: RateResponse; requests: RateResponse }>("reject-ratio", async (range, signal) => {
    const bucket = rateBucket(range).bucket;
    const [rejects, requests] = await Promise.all([
      getJson<RateResponse>(`/api/rate?${query({ name: COUNTER.rejects, range, bucket })}`, signal),
      getJson<RateResponse>(`/api/rate?${query({ names: REQUEST_COUNTERS.join(","), range, bucket })}`, signal),
    ]);
    return { rejects, requests };
  });
  const range = useChartRange(bucketMs);
  // Once per fetch, not per snapshot: a new series each render would redraw the chart every second (I118).
  const series = useMemo(() => {
    const points = history.data ? rejectRatio(history.data.rejects.points, history.data.requests.points, bucketMs) : [];
    return points.length > 0 ? [{ label: "reject ratio", points }] : NO_SERIES;
  }, [history.data, bucketMs]);
  return (
    <TimeSeries
      label={bucketMs === 60_000 ? "Reject ratio, 5-minute window" : "Reject ratio per hour"}
      series={series}
      range={range}
      tz={tz}
      format={formatPercent}
      thresholds={rule}
      annotations={annotations}
    />
  );
}

export function TradingRow() {
  const orders = useDashStore((s) => s.snapshot?.trading.orders ?? null);
  const traded = useDashStore((s) => s.snapshot?.trading.traded_value_today ?? null);
  return (
    <Row id="trading" title="Trading activity">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <OrdersByParticipant />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <CounterBars label="Trades per minute" name={COUNTER.trades} legend="trades" format={formatCount} />
          <CounterBars label="Traded value per minute" name={COUNTER.tradedValue} legend="traded value" format={formatCompact} />
        </div>
      </div>
      <div className="mt-4 grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Orders avg / min" value={orders?.avg_per_min ?? null} format={(v) => formatRate(v, "min")} />
          <StatTile label="Orders avg / hour" value={orders?.avg_per_hour ?? null} format={(v) => formatRate(v, "h")} />
          <StatTile label="Orders avg / day" value={orders?.avg_per_day ?? null} format={formatCompact} sub={orders && orders.avg_per_day === null ? "under a day of data" : "last 7 days"} />
          <StatTile label="Traded value today" value={traded} format={formatCompact} />
        </div>
        <RejectRatio />
      </div>
    </Row>
  );
}

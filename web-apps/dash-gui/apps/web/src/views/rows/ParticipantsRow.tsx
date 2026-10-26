/**
 * Row 4, PARTICIPANTS (design §12.3): how many participants were connected
 * over the range, with heartbeat timeouts marked, and the table: role,
 * connection and since when, orders today and their rates (avg/day "—"
 * before the first full day of data), reject %, resting orders, connects /
 * disconnects / heartbeat timeouts today, and the participant's own lane
 * over the range -- sorted by time disconnected, the unstable ones gather.
 * A lane per participant above the table pushed the table out of sight at
 * a few dozen participants; in the table it costs no height.
 *
 * The lanes come from CONNECT/DISCONNECT events -- those of the range from
 * /api/events, the live ones from the stream -- and the snapshot's present
 * connection state; the count is the lanes summed.
 */

import clsx from "clsx";
import { useCallback, useMemo } from "react";
import type { EventsResponse, HealthEvent, ParticipantStats, Point } from "@edumatcher/dash-types";
import { HealthTable, StateBadge, type Column } from "../../components/widgets/HealthTable.js";
import { Row } from "../../components/widgets/Row.js";
import { LaneBar, type Lane, type TimeRangeMs } from "../../components/widgets/StateTimeline.js";
import { TimeSeries } from "../../components/widgets/TimeSeries.js";
import { useOpenDrawer } from "../../hooks/drawer.js";
import { useChartRange, useHistory, useNow } from "../../hooks/history.js";
import { getJson, query } from "../../lib/api.js";
import { formatCount, formatDuration, formatPercent, formatRate, NO_VALUE } from "../../lib/format.js";
import { TONE } from "../../lib/status.js";
import { formatTime } from "../../lib/time.js";
import { useDashStore } from "../../store/useDashStore.js";
import { CONNECTED, connectedCount, connectionLanes, disconnectedMs, HEARTBEAT, heartbeatTimes } from "./common.js";

const CONN = { glyph: "●", label: "yes", ...TONE.ok };
const NOT_CONN = { glyph: "○", label: "no", ...TONE.stopped };

const STATES = { [CONNECTED]: { label: "connected", color: TONE.ok.color } };
const MARKS = { [HEARTBEAT]: { label: "heartbeat timeout", color: TONE.error.color } };

/** The count line is held to whole minutes; a change still shows at once. */
const COUNT_STEP_MS = 60_000;

const rate = (v: number | null, per: "min" | "h") => (v === null ? NO_VALUE : formatRate(v, per));

/** A table row: the participant with its lane over the range (in the row's data, so the row redraws when the lane does). */
type ParticipantRow = ParticipantStats & { lane: Lane; range: TimeRangeMs; downMs: number };

function columns(tz: string): Column<ParticipantRow>[] {
  return [
    { id: "id", header: "ID", render: (p) => <span className="font-mono">{p.id}</span>, sortKey: (p) => p.id },
    { id: "role", header: "Role", render: (p) => p.role, sortKey: (p) => p.role },
    { id: "conn", header: "Conn", render: (p) => <StateBadge look={p.connected ? CONN : NOT_CONN} />, sortKey: (p) => (p.connected ? 0 : 1) },
    { id: "since", header: "Since", render: (p) => (p.connected_since ? formatTime(p.connected_since, tz, false) : NO_VALUE), sortKey: (p) => p.connected_since },
    { id: "orders", header: "Orders today", render: (p) => formatCount(p.orders.today), sortKey: (p) => p.orders.today, align: "right" },
    { id: "now", header: "/min now", render: (p) => rate(p.orders.per_sec_now * 60, "min"), sortKey: (p) => p.orders.per_sec_now, align: "right" },
    { id: "avg-min", header: "avg/min", render: (p) => rate(p.orders.avg_per_min, "min"), sortKey: (p) => p.orders.avg_per_min, align: "right" },
    { id: "avg-h", header: "avg/h", render: (p) => rate(p.orders.avg_per_hour, "h"), sortKey: (p) => p.orders.avg_per_hour, align: "right" },
    { id: "avg-d", header: "avg/day", render: (p) => (p.orders.avg_per_day === null ? NO_VALUE : formatCount(p.orders.avg_per_day)), sortKey: (p) => p.orders.avg_per_day, align: "right" },
    { id: "rej", header: "Rej %", render: (p) => formatPercent(p.reject_pct), sortKey: (p) => p.reject_pct, align: "right" },
    { id: "rest", header: "Resting", render: (p) => formatCount(p.resting_orders), sortKey: (p) => p.resting_orders, align: "right" },
    {
      id: "cdh",
      header: "C/D/HB",
      render: (p) => `${p.connects_today}/${p.disconnects_today}/${p.heartbeat_timeouts_today}`,
      sortKey: (p) => p.heartbeat_timeouts_today,
      align: "right",
    },
    {
      id: "lane",
      header: "Connected in range",
      render: (p) => (
        <span title={p.downMs > 0 ? `not connected for ${formatDuration(p.downMs / 1000)} of the range` : undefined}>
          <LaneBar lane={p.lane} range={p.range} states={STATES} marks={MARKS} tz={tz} />
        </span>
      ),
      sortKey: (p) => p.downMs,
    },
  ];
}

const KINDS = new Set(["CONNECT", "DISCONNECT"]);

export function ParticipantsRow() {
  const tz = useDashStore((s) => s.sessionTz);
  const participants = useDashStore((s) => s.snapshot?.participants ?? null);
  const live = useDashStore((s) => s.events);
  const now = useNow();
  const open = useOpenDrawer();
  const cols = useMemo(() => columns(tz), [tz]);
  const onRowClick = useCallback((p: ParticipantRow) => open("participant", p.id), [open]);
  const range = useChartRange(COUNT_STEP_MS);
  const history = useHistory<EventsResponse>("connections", (r, signal) =>
    getJson(`/api/events?${query({ range: r, kind: "CONNECT,DISCONNECT", limit: 1000 })}`, signal),
  );
  const events = useMemo(() => {
    const bySeq = new Map<number, HealthEvent>();
    for (const e of history.data?.events ?? []) bySeq.set(e.seq, e);
    for (const e of live) if (KINDS.has(e.kind)) bySeq.set(e.seq, e);
    return [...bySeq.values()];
  }, [history.data, live]);
  const lanes = useMemo(() => connectionLanes(participants ?? [], events, range, now), [participants, events, range, now]);
  const rows = useMemo(() => {
    const byId = new Map(lanes.map((l) => [l.id, l]));
    return (participants ?? []).map((p): ParticipantRow => {
      const lane = byId.get(p.id)!;
      return { ...p, lane, range, downMs: disconnectedMs(lane, range, now) };
    });
  }, [participants, lanes, range, now]);
  // Kept the same objects until their values change: the lanes are new every snapshot (I118).
  const countKey = JSON.stringify(connectedCount(lanes, range, now, Math.floor(now / COUNT_STEP_MS) * COUNT_STEP_MS));
  const count = useMemo(() => [{ label: "connected", points: JSON.parse(countKey) as Point[] }], [countKey]);
  const marksKey = JSON.stringify(heartbeatTimes(lanes, range));
  const marks = useMemo(() => ({ ts: JSON.parse(marksKey) as number[], ...MARKS[HEARTBEAT] }), [marksKey]);
  const connected = participants?.filter((p) => p.connected).length ?? 0;

  return (
    <Row id="participants" title="Participants" badge={participants ? `${connected} / ${participants.length} connected` : undefined}>
      <TimeSeries label="Participants connected" series={count} range={range} tz={tz} format={formatCount} integer step marks={marks} height={120} />
      <div className="mt-4">
        <HealthTable label="Participants" columns={cols} rows={rows} rowKey={(p) => p.id} initialSort={{ id: "id", dir: "asc" }} onRowClick={onRowClick} />
        {/* Four windows side by side: say which is which. */}
        <p className="mb-0 mt-2 text-[11px] text-fg-faint">
          Orders: /min now over the last 60 s · avg/min over the last 60 min · avg/h today per hour open · avg/day over the last 7 trading days. Rej % and C/D/HB are today.
          Connected in range: <Swatch color={STATES[CONNECTED].color} /> connected, <Swatch color={MARKS[HEARTBEAT].color} narrow /> heartbeat timeout; sort it to put the most disconnected first.
        </p>
      </div>
    </Row>
  );
}

function Swatch({ color, narrow = false }: { color: string; narrow?: boolean }) {
  return <span aria-hidden="true" className={clsx("inline-block h-2 rounded-sm align-middle", narrow ? "w-0.5" : "w-3")} style={{ background: color }} />;
}

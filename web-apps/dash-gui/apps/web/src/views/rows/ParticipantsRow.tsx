/**
 * Row 4, PARTICIPANTS (design §12.3): a lane per participant, connected
 * stretches over the range with heartbeat timeouts marked, and the table:
 * role, connection and since when, orders today and their rates (avg/day
 * "—" before the first full day of data), reject %, resting orders, and
 * connects / disconnects / heartbeat timeouts today.
 *
 * The lanes come from CONNECT/DISCONNECT events -- those of the range from
 * /api/events, the live ones from the stream -- and the snapshot's present
 * connection state.
 */

import { useMemo } from "react";
import type { EventsResponse, HealthEvent, ParticipantStats } from "@edumatcher/dash-types";
import { HealthTable, StateBadge, type Column } from "../../components/widgets/HealthTable.js";
import { Row } from "../../components/widgets/Row.js";
import { StateTimeline } from "../../components/widgets/StateTimeline.js";
import { useChartRange, useHistory, useNow } from "../../hooks/history.js";
import { getJson, query } from "../../lib/api.js";
import { formatCount, formatPercent, formatRate, NO_VALUE } from "../../lib/format.js";
import { TONE } from "../../lib/status.js";
import { formatTime } from "../../lib/time.js";
import { useDashStore } from "../../store/useDashStore.js";
import { CONNECTED, connectionLanes, HEARTBEAT } from "./common.js";

const CONN = { glyph: "●", label: "yes", ...TONE.ok };
const NOT_CONN = { glyph: "○", label: "no", ...TONE.stopped };

const rate = (v: number | null, per: "min" | "h") => (v === null ? NO_VALUE : formatRate(v, per));

function columns(tz: string): Column<ParticipantStats>[] {
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
  ];
}

const KINDS = new Set(["CONNECT", "DISCONNECT"]);

export function ParticipantsRow() {
  const tz = useDashStore((s) => s.sessionTz);
  const participants = useDashStore((s) => s.snapshot?.participants ?? null);
  const live = useDashStore((s) => s.events);
  const now = useNow();
  const range = useChartRange(60_000);
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
  const connected = participants?.filter((p) => p.connected).length ?? 0;

  return (
    <Row id="participants" title="Participants" badge={participants ? `${connected} / ${participants.length} connected` : undefined}>
      <StateTimeline
        label="Participant connections"
        lanes={lanes}
        range={range}
        states={{ [CONNECTED]: { label: "connected", color: TONE.ok.color } }}
        marks={{ [HEARTBEAT]: { label: "heartbeat timeout", color: TONE.error.color } }}
        tz={tz}
      />
      <div className="mt-4">
        <HealthTable label="Participants" columns={columns(tz)} rows={participants ?? []} rowKey={(p) => p.id} initialSort={{ id: "id", dir: "asc" }} />
      </div>
    </Row>
  );
}

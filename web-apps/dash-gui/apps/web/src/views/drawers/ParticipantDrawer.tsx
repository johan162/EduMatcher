/**
 * The participant drawer (design §12.3): its connection and figures,
 * orders, rejects and fills per minute, its resting orders over the picked
 * range, and its events (connects, disconnects, auth rejects).
 */

import { useParams } from "react-router-dom";
import type { HealthSnapshot } from "@edumatcher/dash-types";
import { Drawer } from "../../components/layout/Drawer.js";
import { StateBadge } from "../../components/widgets/HealthTable.js";
import { formatCount, formatPercent, formatRate, NO_VALUE } from "../../lib/format.js";
import { COUNTER, GAUGE } from "../../lib/metrics.js";
import { TONE } from "../../lib/status.js";
import { formatTime } from "../../lib/time.js";
import { useDashStore } from "../../store/useDashStore.js";
import { CounterBars, SeriesChart } from "../charts.js";
import { Facts, Section, SubjectEvents, Unavailable } from "./common.js";

const CONNECTED = { glyph: "●", label: "connected", ...TONE.ok };
const DISCONNECTED = { glyph: "○", label: "not connected", ...TONE.stopped };

export function ParticipantDrawer() {
  const id = useParams()["id"] ?? "";
  const tz = useDashStore((s) => s.sessionTz);
  const p = useDashStore((s) => s.snapshot?.participants.find((x) => x.id === id) ?? null);
  if (!p) return <Unavailable kind="Participant" title={id} what="participant" />;

  const resting = (snap: HealthSnapshot) => snap.participants.find((x) => x.id === id)?.resting_orders ?? null;
  return (
    <Drawer kind="Participant" title={p.id}>
      <Facts
        label="Participant figures"
        items={[
          ["Connection", <StateBadge key="conn" look={p.connected ? CONNECTED : DISCONNECTED} />],
          ["Since", p.connected_since ? formatTime(p.connected_since, tz) : NO_VALUE],
          ["Role", p.role],
          ["Orders today", formatCount(p.orders.today)],
          ["Orders / min now", formatRate(p.orders.per_sec_now * 60, "min")],
          ["Avg / min", formatRate(p.orders.avg_per_min, "min")],
          ["Avg / hour", formatRate(p.orders.avg_per_hour, "h")],
          ["Avg / day (7 d)", p.orders.avg_per_day === null ? NO_VALUE : formatCount(p.orders.avg_per_day)],
          ["Reject %", formatPercent(p.reject_pct)],
          ["Fills today", formatCount(p.fills_today)],
          ["Resting orders", formatCount(p.resting_orders)],
          ["Conn / disc / HB today", `${p.connects_today} / ${p.disconnects_today} / ${p.heartbeat_timeouts_today}`],
        ]}
      />
      <Section title="Activity">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <CounterBars label="Orders per minute" name={COUNTER.ordersIn} seriesLabel={p.id} legend="orders" format={formatCount} />
          <CounterBars label="Rejects per minute" name={COUNTER.rejects} seriesLabel={p.id} legend="rejects" format={formatCount} />
          <CounterBars label="Fills per minute" name={COUNTER.fills} seriesLabel={p.id} legend="fills" format={formatCount} />
          <SeriesChart label="Resting orders" name={GAUGE.participantResting} seriesLabel={p.id} legend={p.id} live={resting} format={formatCount} integer height={140} />
        </div>
      </Section>
      <SubjectEvents subject={p.id} />
    </Drawer>
  );
}

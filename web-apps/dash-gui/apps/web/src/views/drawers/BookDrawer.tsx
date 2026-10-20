/**
 * The order-book drawer (design §12.3): its state and figures, trades and
 * traded value per minute, resting orders, estimated memory and heap
 * garbage against its rule over the picked range, its events (halts and
 * resumes), and a link to the book in book-gui.
 */

import { useParams } from "react-router-dom";
import type { BookStats, HealthSnapshot } from "@edumatcher/dash-types";
import { Drawer } from "../../components/layout/Drawer.js";
import { StateBadge } from "../../components/widgets/HealthTable.js";
import { formatBytes, formatCompact, formatCount, formatPercent } from "../../lib/format.js";
import { bookGuiUrl } from "../../lib/links.js";
import { COUNTER, GAUGE } from "../../lib/metrics.js";
import { TONE } from "../../lib/status.js";
import { useDashStore } from "../../store/useDashStore.js";
import { CounterBars, SeriesChart } from "../charts.js";
import { useRule } from "../rows/common.js";
import { CrossLink, Facts, Section, SubjectEvents, Unavailable } from "./common.js";

const HALTED = { glyph: "■", label: "HALTED", ...TONE.warning };
const TRADING = { glyph: "●", label: "trading", ...TONE.ok };

export function BookDrawer() {
  const symbol = useParams()["symbol"] ?? "";
  const b = useDashStore((s) => s.snapshot?.books.find((x) => x.symbol === symbol) ?? null);
  const bookGui = useDashStore((s) => s.links?.bookGui ?? null);
  const garbageRule = useRule("heap_garbage_pct");
  if (!b) return <Unavailable kind="Order book" title={symbol} what="order book" />;

  const live = (figure: (x: BookStats) => number) => (snap: HealthSnapshot) => {
    const x = snap.books.find((y) => y.symbol === symbol);
    return x ? figure(x) : null;
  };
  const chart = { seriesLabel: b.symbol, legend: b.symbol, height: 140 };
  return (
    <Drawer kind="Order book" title={b.symbol} actions={bookGui && <CrossLink href={bookGuiUrl(bookGui, b.symbol)}>Book in book-gui</CrossLink>}>
      <Facts
        label="Book figures"
        items={[
          ["State", <StateBadge key="state" look={b.halted ? HALTED : TRADING} />],
          ["Resting orders", formatCount(b.resting_orders)],
          ["Stop orders", formatCount(b.stop_orders)],
          ["Bid levels", formatCount(b.bid_levels)],
          ["Ask levels", formatCount(b.ask_levels)],
          ["Est. memory", formatBytes(b.est_bytes)],
          ["Heap garbage", formatPercent(b.heap_garbage_pct)],
          ["Trades today", formatCount(b.trades_today)],
        ]}
      />
      <Section title="Activity">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <CounterBars label="Trades per minute" name={COUNTER.trades} seriesLabel={b.symbol} legend="trades" format={formatCount} />
          <CounterBars label="Traded value per minute" name={COUNTER.tradedValue} seriesLabel={b.symbol} legend="traded value" format={formatCompact} />
          <SeriesChart label="Resting orders" name={GAUGE.bookResting} live={live((x) => x.resting_orders)} format={formatCount} integer {...chart} />
          <SeriesChart label="Estimated memory" name={GAUGE.bookEstBytes} live={live((x) => x.est_bytes)} format={formatBytes} {...chart} />
          <SeriesChart label="Heap garbage" name={GAUGE.bookHeapGarbage} live={live((x) => x.heap_garbage_pct)} format={formatPercent} thresholds={garbageRule} {...chart} />
        </div>
      </Section>
      <SubjectEvents subject={b.symbol} />
    </Drawer>
  );
}

/**
 * Row 5, ORDER BOOKS (design §12.3): how many books and their estimated
 * memory (and its share of the engine's), then one row per symbol: resting
 * and stop orders, price levels, memory, heap garbage against its
 * threshold, trades today, and whether it is halted -- in words.
 */

import type { ActiveBreach, BookStats } from "@edumatcher/dash-types";
import { HealthTable, StateBadge, type Column } from "../../components/widgets/HealthTable.js";
import { Row } from "../../components/widgets/Row.js";
import { StatTile } from "../../components/widgets/StatTile.js";
import { formatBytes, formatCount, formatPercent } from "../../lib/format.js";
import { LEVEL, TONE } from "../../lib/status.js";
import { useOpenDrawer } from "../../hooks/drawer.js";
import { useDashStore } from "../../store/useDashStore.js";
import { breachLevel } from "./common.js";

const NO_BREACHES: readonly ActiveBreach[] = [];

const HALTED = { glyph: "■", label: "HALTED", ...TONE.warning };
const TRADING = { glyph: "●", label: "trading", ...TONE.ok };

/**
 * `breaches`: the snapshot's active ones. Heap garbage is coloured as
 * pm-monitor judges it, which ignores a book with too few heap entries for
 * the share to mean anything (I118).
 */
function columns(breaches: readonly ActiveBreach[]): Column<BookStats>[] {
  return [
    { id: "symbol", header: "Symbol", render: (b) => <span className="font-mono">{b.symbol}</span>, sortKey: (b) => b.symbol },
    { id: "resting", header: "Resting", render: (b) => formatCount(b.resting_orders), sortKey: (b) => b.resting_orders, align: "right" },
    { id: "stops", header: "Stops", render: (b) => formatCount(b.stop_orders), sortKey: (b) => b.stop_orders, align: "right" },
    { id: "bid", header: "Bid lv", render: (b) => formatCount(b.bid_levels), sortKey: (b) => b.bid_levels, align: "right" },
    { id: "ask", header: "Ask lv", render: (b) => formatCount(b.ask_levels), sortKey: (b) => b.ask_levels, align: "right" },
    { id: "mem", header: "Est. mem", render: (b) => formatBytes(b.est_bytes), sortKey: (b) => b.est_bytes, align: "right" },
    {
      id: "garbage",
      header: "Heap garbage",
      render: (b) => {
        const level = breachLevel(breaches, "heap_garbage_pct", b.symbol);
        const alarm = level && level !== "OK" ? LEVEL[level] : null;
        return <span className={alarm?.text}>{formatPercent(b.heap_garbage_pct)}{alarm && ` ${alarm.glyph}`}</span>;
      },
      sortKey: (b) => b.heap_garbage_pct,
      align: "right",
    },
    { id: "trades", header: "Trades", render: (b) => formatCount(b.trades_today), sortKey: (b) => b.trades_today, align: "right" },
    { id: "state", header: "State", render: (b) => <StateBadge look={b.halted ? HALTED : TRADING} />, sortKey: (b) => (b.halted ? 0 : 1) },
  ];
}

export function BooksRow() {
  const books = useDashStore((s) => s.snapshot?.books ?? null);
  const engineRss = useDashStore((s) => s.snapshot?.processes.find((p) => p.process === "pm-engine" && p.host !== "")?.rss_bytes ?? null);
  const breaches = useDashStore((s) => s.snapshot?.thresholds ?? NO_BREACHES);
  const open = useOpenDrawer();
  const memory = books?.reduce((sum, b) => sum + b.est_bytes, 0) ?? null;
  const halted = books?.filter((b) => b.halted).length ?? 0;

  return (
    <Row id="books" title="Order books" badge={halted > 0 ? `${halted} halted` : undefined} badgeTone="text-warning">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[14rem_minmax(0,1fr)]">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-1 lg:content-start">
          <StatTile label="Books" value={books?.length ?? null} format={formatCount} />
          <StatTile
            label="Book memory (est.)"
            value={memory}
            format={formatBytes}
            sub={memory !== null && engineRss ? `${formatPercent((100 * memory) / engineRss)} of the engine` : undefined}
          />
        </div>
        <HealthTable label="Order books" columns={columns(breaches)} rows={books ?? []} rowKey={(b) => b.symbol} initialSort={{ id: "symbol", dir: "asc" }} onRowClick={(b) => open("book", b.symbol)} />
      </div>
    </Row>
  );
}

/**
 * Row 5, ORDER BOOKS (design §12.3): how many books and their estimated
 * memory (and its share of the engine's), then one row per symbol: long (GTC),
 * resting and stop orders, price levels, memory, heap bloat against its
 * threshold, trades today, and whether it is halted -- in words.
 */

import { useCallback, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ActiveBreach, BookStats } from "@edumatcher/dash-types";
import { HealthTable, StateBadge, type Column } from "../../components/widgets/HealthTable.js";
import { Row } from "../../components/widgets/Row.js";
import { StatTile } from "../../components/widgets/StatTile.js";
import { formatBytes, formatCount, formatPercent, formatRatio } from "../../lib/format.js";
import { LEVEL, TONE } from "../../lib/status.js";
import { useOpenDrawer } from "../../hooks/drawer.js";
import { useDashStore } from "../../store/useDashStore.js";
import { breachLevel, useBreaches } from "./common.js";

/** Rows per page; 0 is all of them. */
const PAGE_SIZES = [10, 30, 50, 100, 0];
const DEFAULT_PAGE_SIZE = 30;

const HALTED = { glyph: "■", label: "HALTED", ...TONE.warning };
const TRADING = { glyph: "●", label: "trading", ...TONE.ok };

/**
 * `breaches`: the snapshot's active ones. Heap bloat is coloured only where
 * pm-monitor has judged it (I118).
 */
function columns(breaches: readonly ActiveBreach[]): Column<BookStats>[] {
  return [
    { id: "symbol", header: "Symbol", render: (b) => <span className="font-mono">{b.symbol}</span>, sortKey: (b) => b.symbol },
    { id: "long", header: "Long", render: (b) => formatCount(b.gtc_orders), sortKey: (b) => b.gtc_orders, align: "right" },
    { id: "resting", header: "Resting", render: (b) => formatCount(b.resting_orders), sortKey: (b) => b.resting_orders, align: "right" },
    { id: "stops", header: "Stops", render: (b) => formatCount(b.stop_orders), sortKey: (b) => b.stop_orders, align: "right" },
    { id: "bid", header: "Bid lv", render: (b) => formatCount(b.bid_levels), sortKey: (b) => b.bid_levels, align: "right" },
    { id: "ask", header: "Ask lv", render: (b) => formatCount(b.ask_levels), sortKey: (b) => b.ask_levels, align: "right" },
    { id: "mem", header: "Est. mem", render: (b) => formatBytes(b.est_bytes), sortKey: (b) => b.est_bytes, align: "right" },
    {
      id: "bloat",
      header: "Heap bloat",
      render: (b) => {
        const level = breachLevel(breaches, "heap_bloat_ratio", b.symbol);
        const alarm = level && level !== "OK" ? LEVEL[level] : null;
        return <span className={alarm?.text}>{formatRatio(b.heap_bloat_ratio)}{alarm && ` ${alarm.glyph}`}</span>;
      },
      sortKey: (b) => b.heap_bloat_ratio,
      align: "right",
    },
    { id: "trades", header: "Trades", render: (b) => formatCount(b.trades_today), sortKey: (b) => b.trades_today, align: "right" },
    { id: "state", header: "State", render: (b) => <StateBadge look={b.halted ? HALTED : TRADING} />, sortKey: (b) => (b.halted ? 0 : 1) },
  ];
}

export function BooksRow() {
  const books = useDashStore((s) => s.snapshot?.books ?? null);
  const engineRss = useDashStore((s) => s.snapshot?.processes.find((p) => p.process === "pm-engine" && p.host !== "")?.rss_bytes ?? null);
  const breaches = useBreaches();
  const open = useOpenDrawer();
  const cols = useMemo(() => columns(breaches), [breaches]);
  const onRowClick = useCallback((b: BookStats) => open("book", b.symbol), [open]);
  const [search, setSearch] = useState("");
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [requestedPage, setRequestedPage] = useState(0);
  // The search covers every book, not just the page on show.
  const shown = useMemo(() => {
    const needle = search.trim().toUpperCase();
    return needle ? (books ?? []).filter((b) => b.symbol.toUpperCase().includes(needle)) : (books ?? []);
  }, [books, search]);
  const pageCount = pageSize ? Math.max(1, Math.ceil(shown.length / pageSize)) : 1;
  // Books come and go under a viewer: hold them at the last real page.
  const pageIndex = Math.min(requestedPage, pageCount - 1);
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
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-3 text-xs">
            <input
              type="search"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setRequestedPage(0);
              }}
              placeholder="Find symbol"
              aria-label="Find symbol"
              className="w-28 rounded border border-border bg-bg-inset px-2 py-0.5 text-xs placeholder:text-fg-faint"
            />
            <span className="tabular text-fg-subtle">
              {shown.length} symbol{shown.length === 1 ? "" : "s"}
              {shown.length !== (books?.length ?? 0) && ` of ${books?.length ?? 0}`}
            </span>
            <div className="ml-auto flex items-center gap-3">
              <span className="tabular text-fg-subtle">
                Page {pageIndex + 1}/{pageCount}
              </span>
              <button
                type="button"
                disabled={pageIndex === 0}
                onClick={() => setRequestedPage(pageIndex - 1)}
                aria-label="Previous page"
                className="rounded p-1 text-fg-subtle hover:bg-bg-inset hover:text-fg disabled:opacity-40"
              >
                <ChevronLeft size={14} />
              </button>
              <button
                type="button"
                disabled={pageIndex >= pageCount - 1}
                onClick={() => setRequestedPage(pageIndex + 1)}
                aria-label="Next page"
                className="rounded p-1 text-fg-subtle hover:bg-bg-inset hover:text-fg disabled:opacity-40"
              >
                <ChevronRight size={14} />
              </button>
              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setRequestedPage(0);
                }}
                aria-label="Rows per page"
                className="rounded border border-border bg-bg-inset px-1 py-0.5 text-xs text-fg-subtle"
              >
                {PAGE_SIZES.map((n) => (
                  <option key={n} value={n}>
                    {n ? `${n} rows` : "All rows"}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <HealthTable
            label="Order books"
            columns={cols}
            rows={shown}
            rowKey={(b) => b.symbol}
            initialSort={{ id: "symbol", dir: "asc" }}
            onRowClick={onRowClick}
            page={pageSize ? { index: pageIndex, size: pageSize } : undefined}
          />
        </div>
      </div>
    </Row>
  );
}

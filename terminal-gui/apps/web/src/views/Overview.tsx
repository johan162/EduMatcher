/**
 * Market Overview (design §8).
 *
 * Every tradable symbol, auto-paging so it can run unattended on a classroom
 * or lobby display, with a client-only watchlist for the case where a viewer
 * only cares about a handful.
 *
 * Rows on pages nobody is currently looking at stay just as live as the
 * visible ones: the bridge holds one wildcard subscription for the whole
 * market, so paging is a rendering concern and never a subscription one
 * (§8.3). Nothing in this view talks to CALF.
 */

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronLeft, ChevronRight, Pause, Play, Star } from "lucide-react";
import { useMemo } from "react";
import type { DailyBar } from "@edumatcher/terminal-types";
import { FlashCell } from "../components/FlashCell.js";
import { EmptyState, Panel } from "../components/Panel.js";
import { api } from "../lib/api.js";
import { ABSENT, clockUtc, compact, price, qty } from "../lib/format.js";
import { buildRows, columnsFor, type OverviewColumn, type OverviewRow } from "../lib/overview-rows.js";
import { pageSlice } from "../lib/paging.js";
import { useTickDecimals } from "../lib/precision.js";
import { STALE_AFTER_SEC, isStale, useNow } from "../lib/staleness.js";
import { useAutoPaging, useRowsPerPage } from "../lib/useAutoPaging.js";
import { usePrevCloses } from "../lib/usePrevCloses.js";
import { useLiveStore } from "../store/useLiveStore.js";
import {
  DENSITY_ROW_CLASS,
  PAGE_DELAY_CHOICES,
  effectivePageDelaySec,
  usePrefsStore,
} from "../store/usePrefsStore.js";

/** Approximate rendered row height per density, used to fit the page. */
const ROW_HEIGHT: Record<"lobby" | "standard" | "dense", number> = {
  lobby: 40,
  standard: 28,
  dense: 22,
};

const HEADING: Record<OverviewColumn, string> = {
  star: "",
  symbol: "Symbol",
  last: "Last",
  chg: "Chg",
  pctChg: "%Chg",
  bidSz: "Bid sz",
  bid: "Bid",
  ask: "Ask",
  askSz: "Ask sz",
  spread: "Spread",
  volume: "Volume",
  turnover: "Turnover",
  lastTrade: "Time",
};

const NUMERIC: ReadonlySet<OverviewColumn> = new Set<OverviewColumn>([
  "last",
  "chg",
  "pctChg",
  "bidSz",
  "bid",
  "ask",
  "askSz",
  "spread",
  "volume",
  "turnover",
  "lastTrade",
]);

/**
 * Marks a row whose change was measured from today's open because no previous
 * close is on record — a symbol listed today, or one dormant longer than the
 * lookback window. Two rows meaning different things by "%Chg" with nothing to
 * say so would be worse than either convention on its own.
 */
const OPEN_BASELINE_MARK = "*";

export function OverviewView() {
  const symbols = useLiveStore((s) => s.symbols);
  const top = useLiveStore((s) => s.top);
  const halted = useLiveStore((s) => s.halted);
  const lastTradeTs = useLiveStore((s) => s.lastTradeTs);

  const density = usePrefsStore((s) => s.density);
  const watchlist = usePrefsStore((s) => s.watchlist);
  const filter = usePrefsStore((s) => s.overviewFilter);
  const setFilter = usePrefsStore((s) => s.setOverviewFilter);
  const toggleWatchlist = usePrefsStore((s) => s.toggleWatchlist);
  const pageDelayPref = usePrefsStore((s) => s.pageDelaySec);
  const setPageDelaySec = usePrefsStore((s) => s.setPageDelaySec);

  // Open and volume are not on the CALF wire at all — pm-stats recomputes the
  // daily row on every trade, so a short re-poll keeps them current without
  // this tab hand-accumulating anything it happened to observe (§8.5).
  const { data, isError: dailyBarsError } = useQuery({
    queryKey: ["history", "daily"],
    queryFn: api.dailyBars,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });

  const daily = useMemo(() => {
    const bySymbol: Record<string, DailyBar> = {};
    for (const bar of data?.daily ?? []) bySymbol[bar.symbol] = bar;
    return bySymbol;
  }, [data]);

  const { closes: prevClose, unavailable: prevCloseGone } = usePrevCloses();

  const rows = useMemo(
    () => buildRows({ symbols, top, daily, prevClose, lastTradeTs, halted, watchlist, filter }),
    [symbols, top, daily, prevClose, lastTradeTs, halted, watchlist, filter],
  );

  // Staleness is a function of elapsed time, not of arriving data, so it needs
  // its own clock — a row goes stale precisely because nothing arrived.
  const now = useNow();
  const tickDecimals = useTickDecimals();

  const columns = columnsFor(density);
  const delaySec = effectivePageDelaySec(pageDelayPref, density);
  const { ref, rows: perPage } = useRowsPerPage(ROW_HEIGHT[density]);
  const paging = useAutoPaging(rows.length, perPage, delaySec);
  const visible = pageSlice(rows, paging.page, perPage);

  // Only footnote what is actually on this page — carrying the note while the
  // marked row sits three pages away would be noise.
  const anyOpenBaseline = visible.some((row) => row.baseline === "open");

  return (
    <div className="flex h-full flex-col">
      <Panel
        title="Market overview"
        right={
          <div className="flex items-center gap-3 text-xs">
            <div className="flex overflow-hidden rounded border border-border">
              {(["all", "watchlist"] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setFilter(option)}
                  className={clsx(
                    "px-2 py-0.5",
                    filter === option ? "bg-accent text-accent-fg" : "text-fg-subtle hover:bg-bg-inset",
                  )}
                >
                  {option === "all" ? "All" : `☆ ${watchlist.length}`}
                </button>
              ))}
            </div>

            <span className="tabular text-fg-subtle">
              Page {paging.page + 1}/{paging.pages}
            </span>

            <button
              type="button"
              onClick={() => paging.prev()}
              aria-label="Previous page"
              className="rounded p-1 text-fg-subtle hover:bg-bg-inset hover:text-fg"
            >
              <ChevronLeft size={14} />
            </button>
            <button
              type="button"
              onClick={paging.togglePaused}
              aria-label={paging.paused ? "Resume paging" : "Pause paging"}
              className="rounded p-1 text-fg-subtle hover:bg-bg-inset hover:text-fg"
            >
              {paging.paused ? <Play size={14} /> : <Pause size={14} />}
            </button>
            <button
              type="button"
              onClick={() => paging.next()}
              aria-label="Next page"
              className="rounded p-1 text-fg-subtle hover:bg-bg-inset hover:text-fg"
            >
              <ChevronRight size={14} />
            </button>

            <select
              value={pageDelayPref ?? "auto"}
              onChange={(event) =>
                setPageDelaySec(event.target.value === "auto" ? null : Number(event.target.value))
              }
              aria-label="Page delay"
              className="rounded border border-border bg-bg-inset px-1 py-0.5 text-xs text-fg-subtle"
            >
              <option value="auto">{delaySec}s (auto)</option>
              {PAGE_DELAY_CHOICES.map((seconds) => (
                <option key={seconds} value={seconds}>
                  {seconds}s
                </option>
              ))}
            </select>
          </div>
        }
      >
        {/*
         * Two failures, two meanings, so two notices (§ T-H1). The board does
         * not stop showing %Chg when previous closes go: it silently starts
         * measuring from the open instead, and "unavailable" over a full
         * column of numbers is a false statement about figures the reader can
         * see. Say what they now mean. The daily poll is the separate case
         * where a figure really is missing rather than re-based.
         */}
        {prevCloseGone && (
          <p className="mb-2 text-xs text-halt">
            %Chg is measured from today&rsquo;s open — previous closes are unavailable.
          </p>
        )}

        {dailyBarsError && (
          <p className="mb-2 text-xs text-halt">
            Open, volume and turnover unavailable — the history service is not reachable. Live prices are
            unaffected.
          </p>
        )}

        {rows.length === 0 ? (
          <EmptyState>
            {filter === "watchlist"
              ? "No symbols pinned yet — star a row in the All view"
              : "Awaiting the symbol list from the gateway"}
          </EmptyState>
        ) : (
          // Hovering pauses so a viewer can read a row without it sliding
          // away mid-glance (§8.3).
          <div
            ref={ref}
            onMouseEnter={() => paging.setPaused(true)}
            onMouseLeave={() => paging.setPaused(false)}
            className="min-h-[12rem] flex-1"
          >
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-border text-[10px] uppercase tracking-widest text-fg-faint">
                  {columns.map((column) => (
                    <th
                      key={column}
                      className={clsx("py-1 font-medium", NUMERIC.has(column) && "text-right")}
                    >
                      {HEADING[column]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <Row
                    key={row.sym}
                    row={row}
                    columns={columns}
                    rowClass={DENSITY_ROW_CLASS[density]}
                    stale={isStale(row.lastTradeTs, now)}
                    decimals={tickDecimals(row.sym)}
                    onTogglePin={() => toggleWatchlist(row.sym)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="mt-2 flex items-center gap-3 border-t border-border pt-2 text-[10px] text-fg-faint">
          <span>
            {rows.length} symbol{rows.length === 1 ? "" : "s"}
          </span>
          <span>
            {paging.advancing ? `advancing every ${delaySec}s` : paging.paused ? "paused" : "single page"}
          </span>
          <span>change vs previous close</span>
          {anyOpenBaseline && (
            <span>{OPEN_BASELINE_MARK} vs today&rsquo;s open — no previous close on record</span>
          )}
        </div>
      </Panel>
    </div>
  );
}

function Row({
  row,
  columns,
  rowClass,
  stale,
  decimals,
  onTogglePin,
}: {
  row: OverviewRow;
  columns: OverviewColumn[];
  rowClass: string;
  stale: boolean;
  /** This symbol's display precision, from CALF `REF=`. */
  decimals: number;
  onTogglePin: () => void;
}) {
  return (
    <tr
      className={clsx("border-b border-border/40", rowClass, stale && "opacity-50")}
      /*
       * Faded rather than recoloured. Dimming the whole row leaves the up/down
       * colours meaning exactly what they always mean — the row is simply
       * further away — where a grey repaint would collide with the one signal
       * the palette is reserved for.
       */
      title={stale ? `No print in over ${STALE_AFTER_SEC / 60} minutes` : undefined}
      data-stale={stale || undefined}
    >
      {columns.map((column) => {
        switch (column) {
          case "star":
            return (
              <td key={column} className="w-6">
                <button
                  type="button"
                  onClick={onTogglePin}
                  aria-label={row.pinned ? `Unpin ${row.sym}` : `Pin ${row.sym}`}
                  aria-pressed={row.pinned}
                  className={row.pinned ? "text-accent" : "text-fg-faint hover:text-fg-subtle"}
                >
                  <Star size={12} fill={row.pinned ? "currentColor" : "none"} />
                </button>
              </td>
            );

          case "symbol":
            return (
              <td key={column} className="font-semibold">
                <span className="flex items-center gap-1.5">
                  {row.sym}
                  {/*
                   * Only HALTED can appear here. Per-symbol STATE frames carry
                   * nothing else — the gateway's normalise_halt/resume emit
                   * HALTED or CONTINUOUS, and auction phases are exchange-wide
                   * under SYM=*, shown in the status strip instead.
                   */}
                  {row.halted && (
                    <span className="rounded bg-halt-bg px-1 py-px text-[9px] font-bold text-halt">HALT</span>
                  )}
                </span>
              </td>
            );

          case "last":
            return (
              <td key={column} className="text-right">
                <FlashCell value={row.last}>{price(row.last, decimals)}</FlashCell>
              </td>
            );

          case "chg":
            return (
              <td key={column} className={clsx("text-right tabular", toneOf(row.chg))}>
                {row.chg === undefined ? ABSENT : signed(row.chg, decimals)}
              </td>
            );

          case "pctChg":
            return (
              <td key={column} className={clsx("text-right tabular", toneOf(row.pctChg))}>
                {row.pctChg === undefined ? ABSENT : `${signed(row.pctChg)}%`}
                {row.baseline === "open" && (
                  <sup
                    title="Measured from today's open — no previous close on record for this symbol"
                    className="text-fg-faint"
                  >
                    {OPEN_BASELINE_MARK}
                  </sup>
                )}
              </td>
            );

          // Sizes are muted and prices are not: the pair of prices is what the
          // eye tracks down the column, and the sizes qualify them.
          case "bidSz":
            return (
              <td key={column} className="text-right tabular text-fg-subtle">
                {qty(row.bidSz)}
              </td>
            );

          case "bid":
            return (
              <td key={column} className="text-right">
                <FlashCell value={row.bid}>{price(row.bid, decimals)}</FlashCell>
              </td>
            );

          case "ask":
            return (
              <td key={column} className="text-right">
                <FlashCell value={row.ask}>{price(row.ask, decimals)}</FlashCell>
              </td>
            );

          case "askSz":
            return (
              <td key={column} className="text-right tabular text-fg-subtle">
                {qty(row.askSz)}
              </td>
            );

          case "spread":
            return (
              <td key={column} className="text-right tabular text-fg-subtle">
                {price(row.spread, decimals)}
              </td>
            );

          case "volume":
            return (
              <td key={column} className="text-right tabular text-fg-subtle">
                {qty(row.volume)}
              </td>
            );

          case "turnover":
            return (
              <td key={column} className="text-right tabular text-fg-subtle">
                {compact(row.turnover)}
              </td>
            );

          case "lastTrade":
            return (
              <td key={column} className="text-right tabular text-fg-faint">
                {clockUtc(row.lastTradeTs)}
              </td>
            );
        }
      })}
    </tr>
  );
}

/** Green above the reference close, red below, neutral exactly flat. */
function toneOf(value: number | undefined): string | undefined {
  if (value === undefined || value === 0) return undefined;
  return value > 0 ? "text-up" : "text-down";
}

/**
 * A signed figure at a given precision.
 *
 * `decimals` defaults to 2 for the percentage column, which is a percentage
 * rather than a price and so is unaffected by the instrument's tick size. The
 * change column passes the symbol's own precision, because it is a difference
 * between two prices and rounding it harder than them would make a row fail to
 * add up on screen.
 */
function signed(value: number, decimals = 2): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(decimals)}`;
}

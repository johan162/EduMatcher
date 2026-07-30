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
import { ABSENT, price, qty } from "../lib/format.js";
import { buildRows, columnsFor, type OverviewColumn, type OverviewRow } from "../lib/overview-rows.js";
import { pageSlice } from "../lib/paging.js";
import { useAutoPaging, useRowsPerPage } from "../lib/useAutoPaging.js";
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
  bid: "Bid",
  ask: "Ask",
  volume: "Volume",
};

const NUMERIC: ReadonlySet<OverviewColumn> = new Set<OverviewColumn>([
  "last",
  "chg",
  "pctChg",
  "bid",
  "ask",
  "volume",
]);

export function OverviewView() {
  const symbols = useLiveStore((s) => s.symbols);
  const top = useLiveStore((s) => s.top);
  const halted = useLiveStore((s) => s.halted);

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
  const { data, isError } = useQuery({
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

  const rows = useMemo(
    () => buildRows({ symbols, top, daily, halted, watchlist, filter }),
    [symbols, top, daily, halted, watchlist, filter],
  );

  const columns = columnsFor(density);
  const delaySec = effectivePageDelaySec(pageDelayPref, density);
  const { ref, rows: perPage } = useRowsPerPage(ROW_HEIGHT[density]);
  const paging = useAutoPaging(rows.length, perPage, delaySec);
  const visible = pageSlice(rows, paging.page, perPage);

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
        {isError && (
          <p className="mb-2 text-xs text-halt">
            Change and volume unavailable — the history service is not reachable. Live prices are unaffected.
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
        </div>
      </Panel>
    </div>
  );
}

function Row({
  row,
  columns,
  rowClass,
  onTogglePin,
}: {
  row: OverviewRow;
  columns: OverviewColumn[];
  rowClass: string;
  onTogglePin: () => void;
}) {
  return (
    <tr className={clsx("border-b border-border/40", rowClass)}>
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
                <FlashCell value={row.last}>{price(row.last)}</FlashCell>
              </td>
            );

          case "chg":
            return (
              <td key={column} className={clsx("text-right tabular", toneOf(row.chg))}>
                {row.chg === undefined ? ABSENT : signed(row.chg)}
              </td>
            );

          case "pctChg":
            return (
              <td key={column} className={clsx("text-right tabular", toneOf(row.pctChg))}>
                {row.pctChg === undefined ? ABSENT : `${signed(row.pctChg)}%`}
              </td>
            );

          case "bid":
            return (
              <td key={column} className="text-right">
                <FlashCell value={row.bid}>{price(row.bid)}</FlashCell>
              </td>
            );

          case "ask":
            return (
              <td key={column} className="text-right">
                <FlashCell value={row.ask}>{price(row.ask)}</FlashCell>
              </td>
            );

          case "volume":
            return (
              <td key={column} className="text-right tabular text-fg-subtle">
                {qty(row.volume)}
              </td>
            );
        }
      })}
    </tr>
  );
}

/** Green above the open, red below, neutral exactly flat. */
function toneOf(value: number | undefined): string | undefined {
  if (value === undefined || value === 0) return undefined;
  return value > 0 ? "text-up" : "text-down";
}

function signed(value: number): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

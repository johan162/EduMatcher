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
import { useMemo, useState } from "react";
import type { AuctionIndicativeFrame, DailyBar } from "@edumatcher/terminal-types";
import { FlashCell } from "../components/FlashCell.js";
import { EmptyState, Panel } from "../components/Panel.js";
import { api } from "../lib/api.js";
import { ABSENT, clockUtc, compact, price, qty } from "../lib/format.js";
import { imbalanceOf, wouldCross } from "../lib/auction.js";
import { buildRows, columnsFor, type OverviewColumn, type OverviewRow } from "../lib/overview-rows.js";
import { pageSlice } from "../lib/paging.js";
import { useTickDecimals } from "../lib/precision.js";
import { isStale, staleLabel, useNow } from "../lib/staleness.js";
import { ageSec, formatAge, isLate } from "../lib/data-age.js";
import {
  filterBySymbol,
  isAttended,
  nextSort,
  sortRows,
  type SortKey,
  type SortState,
} from "../lib/overview-sort.js";
import { useAutoPaging, useRowsPerPage } from "../lib/useAutoPaging.js";
import { usePrevCloses } from "../lib/usePrevCloses.js";
import { notExecutableLabel, notExecutableReason, type NotExecutableReason } from "../lib/executable.js";
import { useLiveStore } from "../store/useLiveStore.js";
import {
  DENSITY_ROW_CLASS,
  PAGE_DELAY_CHOICES,
  STALE_AFTER_CHOICES,
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
  indic: "Indic",
  indicQty: "Indic sz",
  imbalance: "Imbalance",
};

/**
 * Which sort key a column header offers, if any.
 *
 * `star` is excluded: pinning is a filter, not a magnitude, and the star
 * toggle already occupies that header's click target.
 */
const SORT_KEY: Partial<Record<OverviewColumn, SortKey>> = {
  symbol: "sym",
  last: "last",
  chg: "chg",
  pctChg: "pctChg",
  bidSz: "bidSz",
  bid: "bid",
  ask: "ask",
  askSz: "askSz",
  spread: "spread",
  volume: "volume",
  turnover: "turnover",
  lastTrade: "lastTradeTs",
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
  "indic",
  "indicQty",
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
  const sessionPhase = useLiveStore((s) => s.sessionPhase);
  const indicative = useLiveStore((s) => s.indicative);

  const density = usePrefsStore((s) => s.density);
  const watchlist = usePrefsStore((s) => s.watchlist);
  const filter = usePrefsStore((s) => s.overviewFilter);
  const setFilter = usePrefsStore((s) => s.setOverviewFilter);
  const toggleWatchlist = usePrefsStore((s) => s.toggleWatchlist);
  const pageDelayPref = usePrefsStore((s) => s.pageDelaySec);
  const setPageDelaySec = usePrefsStore((s) => s.setPageDelaySec);
  const staleAfterSec = usePrefsStore((s) => s.staleAfterSec);
  const setStaleAfterSec = usePrefsStore((s) => s.setStaleAfterSec);

  // Open and volume are not on the CALF wire at all — pm-stats recomputes the
  // daily row on every trade, so a short re-poll keeps them current without
  // this tab hand-accumulating anything it happened to observe (§8.5).
  const {
    data,
    isError: dailyBarsError,
    dataUpdatedAt: dailyUpdatedAt,
  } = useQuery({
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

  // Whether a quote can be acted on is a property of the session first and
  // the symbol second, so the board-wide part is resolved once here rather
  // than per row (§ T-M2).
  const boardNotExecutable = notExecutableReason({ sessionPhase, halted: false });

  // Session state, not a persisted preference: a wallboard left with a sort
  // applied would sit paused indefinitely with nobody there to notice, which
  // is a worse failure than a trader re-clicking a header after a reload
  // (§ T-M5).
  const [sort, setSort] = useState<SortState | null>(null);
  const [query, setQuery] = useState("");

  const rows = useMemo(
    () => buildRows({ symbols, top, daily, prevClose, lastTradeTs, halted, watchlist, filter }),
    [symbols, top, daily, prevClose, lastTradeTs, halted, watchlist, filter],
  );

  // Search narrows, then sort orders what is left. The other way round would
  // sort rows that are about to be discarded.
  const shown = useMemo(() => sortRows(filterBySymbol(rows, query), sort), [rows, query, sort]);

  // Staleness is a function of elapsed time, not of arriving data, so it needs
  // its own clock — a row goes stale precisely because nothing arrived.
  const now = useNow();
  const dailyAge = ageSec(dailyUpdatedAt || null, now);
  const tickDecimals = useTickDecimals();

  // The auction columns replace the quote columns during a call phase; see
  // `columnsFor`. A call phase is a different kind of market, not a display
  // preference, so the grid follows it rather than offering a toggle.
  const columns = columnsFor(density, sessionPhase);
  const delaySec = effectivePageDelaySec(pageDelayPref, density);
  const { ref, rows: perPage } = useRowsPerPage(ROW_HEIGHT[density]);
  // Somebody is sorting or searching, so somebody is reading: stop moving
  // the page under them. Expressed as a zero dwell rather than as a pause,
  // because the manual page buttons should keep working — this suppresses
  // the automatic advance, it does not take the view away from the reader.
  const attended = isAttended(sort, query);
  const paging = useAutoPaging(shown.length, perPage, attended ? 0 : delaySec);
  const visible = pageSlice(shown, paging.page, perPage);

  // Only footnote what is actually on this page — carrying the note while the
  // marked row sits three pages away would be noise.
  const anyOpenBaseline = visible.some((row) => row.baseline === "open");

  return (
    <div className="flex h-full flex-col">
      <Panel
        title="Market overview"
        right={
          <div className="flex items-center gap-3 text-xs">
            {/*
             * Type-ahead rather than a dropdown: on an exchange of any size
             * the list is longer than a menu is useful, and a trader
             * reaching for a symbol is already spelling it.
             */}
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Find symbol"
              aria-label="Find symbol"
              className="w-28 rounded border border-border bg-bg-inset px-2 py-0.5 text-xs placeholder:text-fg-faint"
            />

            {(sort !== null || query !== "") && (
              <button
                type="button"
                onClick={() => {
                  setSort(null);
                  setQuery("");
                }}
                title="Clear the sort and search, and resume automatic paging"
                className="text-fg-subtle hover:text-fg"
              >
                Reset
              </button>
            )}

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

            {/*
             * The right silence threshold is a property of the exchange, not
             * of the terminal: five minutes suits a liquid book and can fade
             * every row on a thin classroom one permanently, at which point
             * the mark carries no information (§ T-L3).
             */}
            <select
              value={String(staleAfterSec)}
              onChange={(event) => setStaleAfterSec(Number(event.target.value))}
              aria-label="Fade a row after"
              title="Fade a row after this much silence"
              className="rounded border border-border bg-bg-inset px-1 py-0.5 text-xs text-fg-subtle"
            >
              {STALE_AFTER_CHOICES.map((seconds) => (
                <option key={String(seconds)} value={String(seconds)}>
                  fade {staleLabel(seconds)}
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
        {/*
         * A board-level fact deserves a board-level statement. After the
         * close every row carries a full bid/ask that nobody can trade on,
         * and dimming alone is too quiet for something that applies to the
         * whole screen at once.
         */}
        {boardNotExecutable && (
          <p className="mb-2 text-xs text-halt">
            {notExecutableLabel(boardNotExecutable)}. Prices and volumes are the session&rsquo;s record and
            remain accurate.
          </p>
        )}

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

        {shown.length === 0 ? (
          <EmptyState>
            {query.trim() !== ""
              ? `No symbol matches "${query.trim()}"`
              : filter === "watchlist"
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
                  {columns.map((column) => {
                    const key = SORT_KEY[column];
                    const active = key !== undefined && sort?.key === key;
                    return (
                      <th
                        key={column}
                        aria-sort={
                          active ? (sort.direction === "asc" ? "ascending" : "descending") : undefined
                        }
                        className={clsx("py-1 font-medium", NUMERIC.has(column) && "text-right")}
                      >
                        {key === undefined ? (
                          HEADING[column]
                        ) : (
                          <button
                            type="button"
                            onClick={() => setSort((current) => nextSort(current, key))}
                            title={`Sort by ${HEADING[column] || column}`}
                            className={clsx("uppercase tracking-widest hover:text-fg", active && "text-fg")}
                          >
                            {HEADING[column]}
                            {/*
                             * A caret only on the active column. Reserving
                             * space on every header would cost a character
                             * of width per column on a grid that is already
                             * dense, to say nothing eleven times over.
                             */}
                            {active && <span aria-hidden>{sort.direction === "asc" ? " ▲" : " ▼"}</span>}
                          </button>
                        )}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <Row
                    key={row.sym}
                    row={row}
                    columns={columns}
                    rowClass={DENSITY_ROW_CLASS[density]}
                    stale={isStale(row.lastTradeTs, now, staleAfterSec)}
                    decimals={tickDecimals(row.sym)}
                    staleAfterSec={staleAfterSec}
                    notExecutable={notExecutableReason({ sessionPhase, halted: row.halted })}
                    indicative={indicative[row.sym]}
                    onTogglePin={() => toggleWatchlist(row.sym)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="mt-2 flex items-center gap-3 border-t border-border pt-2 text-[10px] text-fg-faint">
          <span>
            {shown.length} symbol{shown.length === 1 ? "" : "s"}
            {shown.length !== rows.length && ` of ${rows.length}`}
          </span>
          <span>
            {paging.advancing
              ? `advancing every ${delaySec}s`
              : attended
                ? "paging held while sorted or filtered"
                : paging.paused
                  ? "paused"
                  : "single page"}
          </span>
          <span>change vs previous close</span>
          <span>dimmed quote = not executable</span>
          {/*
           * Naming the threshold is half the fix: a faded row is only
           * readable if the reader knows what "faded" means here.
           */}
          {Number.isFinite(staleAfterSec) && <span>faded row = no print in {staleLabel(staleAfterSec)}</span>}
          {/*
           * A row looks like one reading taken at one instant and is not:
           * the quote is live, the session totals are a ten-second poll.
           * Naming the slower source is what stops the whole row passing
           * for as fresh as its fastest column (§ T-M4).
           */}
          <span
            className={clsx(isLate("daily", dailyAge) && "font-semibold text-halt")}
            title="Volume, turnover and open come from the history service, not the live feed"
          >
            session totals {formatAge(dailyAge)} old
          </span>
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
  staleAfterSec,
  notExecutable,
  indicative,
  onTogglePin,
}: {
  row: OverviewRow;
  columns: OverviewColumn[];
  rowClass: string;
  stale: boolean;
  /** This symbol's display precision, from CALF `REF=`. */
  decimals: number;
  /** The silence threshold in force, so the tooltip can state it. */
  staleAfterSec: number;
  /** Why this row's quote cannot be traded on, or null if it can (§ T-M2). */
  notExecutable: NotExecutableReason | null;
  /** This symbol's indicative uncross, during a call phase (§ T-M1). */
  indicative: AuctionIndicativeFrame | undefined;
  onTogglePin: () => void;
}) {
  /*
   * The quote group only. `last`, `chg`, `%chg`, `volume` and `turnover`
   * remain in the ordinary register because they are statements about what
   * *happened*, and those stay true after the close. Bid, ask, their sizes
   * and the spread are statements about what is *available*, and those do
   * not — which is the whole distinction T-M2 is about.
   */
  const quoteTone = notExecutable ? "text-fg-faint" : "text-fg-subtle";
  const quotePriceTone = notExecutable ? "text-fg-faint" : undefined;
  const quoteTitle = notExecutable ? notExecutableLabel(notExecutable) : undefined;
  return (
    <tr
      className={clsx("border-b border-border-subtle", rowClass, stale && "opacity-50")}
      /*
       * Faded rather than recoloured. Dimming the whole row leaves the up/down
       * colours meaning exactly what they always mean — the row is simply
       * further away — where a grey repaint would collide with the one signal
       * the palette is reserved for.
       */
      title={stale ? `No print in over ${staleLabel(staleAfterSec)}` : undefined}
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
              <td key={column} className={clsx("text-right tabular", quoteTone)} title={quoteTitle}>
                {qty(row.bidSz)}
              </td>
            );

          case "bid":
            return (
              <td key={column} className={clsx("text-right", quotePriceTone)} title={quoteTitle}>
                <FlashCell value={row.bid}>{price(row.bid, decimals)}</FlashCell>
              </td>
            );

          case "ask":
            return (
              <td key={column} className={clsx("text-right", quotePriceTone)} title={quoteTitle}>
                <FlashCell value={row.ask}>{price(row.ask, decimals)}</FlashCell>
              </td>
            );

          case "askSz":
            return (
              <td key={column} className={clsx("text-right tabular", quoteTone)} title={quoteTitle}>
                {qty(row.askSz)}
              </td>
            );

          case "spread":
            return (
              <td key={column} className={clsx("text-right tabular", quoteTone)} title={quoteTitle}>
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

          case "indic":
            return (
              <td key={column} className="text-right">
                {/*
                 * "No cross" is a real reading during a call phase: the bids
                 * and offers collected so far do not overlap, so nothing
                 * would trade if it ended now. Rendering that as a price
                 * would be a fabrication, so it renders as words.
                 */}
                {indicative === undefined ? (
                  ABSENT
                ) : wouldCross(indicative) ? (
                  <FlashCell value={indicative.indicPrice}>
                    {price(indicative.indicPrice, decimals)}
                  </FlashCell>
                ) : (
                  <span className="text-fg-faint" title="Bids and offers do not overlap yet">
                    no cross
                  </span>
                )}
              </td>
            );

          case "indicQty":
            return (
              <td key={column} className="text-right tabular text-fg-subtle">
                {indicative === undefined ? ABSENT : qty(indicative.indicQty)}
              </td>
            );

          case "imbalance": {
            const imbalance = imbalanceOf(indicative);
            return (
              <td key={column} className="text-right tabular">
                {/*
                 * Balanced is the state an auction converges toward, so it
                 * reads as good news rather than as a zero. The caret is the
                 * non-colour channel for the side (§ T-M3).
                 */}
                {indicative === undefined ? (
                  ABSENT
                ) : imbalance === null ? (
                  <span className="text-fg-faint">balanced</span>
                ) : (
                  <span className={imbalance.side === "BUY" ? "text-up" : "text-down"}>
                    <span aria-hidden>{imbalance.side === "BUY" ? "▲" : "▼"}</span> {qty(imbalance.qty)}
                  </span>
                )}
              </td>
            );
          }

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

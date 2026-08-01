/**
 * Symbol Detail (design §9).
 *
 * The deep-dive view for one instrument: chart, values table, and an optional
 * depth ladder. Large-screen only, as the design confirms — no mobile layout
 * is specified and none is attempted.
 *
 * Two CALF subscriptions are driven from here, and they have deliberately
 * different lifetimes (§6.4, §9.2):
 *
 *   - `CB` for as long as the view is open, because halt detail is relevant to
 *     the instrument generally, not just to its ladder.
 *   - `DEPTH` only while the toggle is on, because it is the heaviest channel
 *     on the wire and costs a real per-symbol subscription upstream.
 *
 * Both are reference-counted by the bridge, so several tabs on one symbol
 * share a single upstream subscription.
 */

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import type {
  AuctionReason,
  DailyBar,
  HaltContextFrame,
  TopOfBook,
  TradeRow,
} from "@edumatcher/terminal-types";
import { SessionBadge } from "../components/Badge.js";
import { DepthLadder } from "../components/DepthLadder.js";
import { EmptyState, Panel } from "../components/Panel.js";
import { PriceChart } from "../components/PriceChart.js";
import { api } from "../lib/api.js";
import { bucketTrades, dailyToBars, midOf, midpointSeries } from "../lib/bars.js";
import { ABSENT, clockUtc, compact, price, qty, resumeAt } from "../lib/format.js";
import { buildRows, type OverviewRow } from "../lib/overview-rows.js";
import { useSymbolDecimals } from "../lib/precision.js";
import { avgTradeSize, rangePosition, spreadBps } from "../lib/quote.js";
import { PRESETS, timeframeSpec, type Preset } from "../lib/timeframe.js";
import { sendControl } from "../lib/useTerminalStream.js";
import { usePrevCloses } from "../lib/usePrevCloses.js";
import { useLiveStore } from "../store/useLiveStore.js";
import { DENSITY_ROW_CLASS, usePrefsStore } from "../store/usePrefsStore.js";

/** How long an auction banner stays before dismissing itself (§9.3a). */
const AUCTION_BANNER_MS = 60_000;

/**
 * Which history endpoint filled the chart, tagged so the bucketing step knows
 * what it is holding. Declared rather than inferred: the two branches return
 * different row types and the query hook needs one named result.
 */
type ChartSeries = { kind: "trades"; rows: TradeRow[] } | { kind: "daily"; rows: DailyBar[] };

export function SymbolDetailView() {
  const { sym } = useParams<{ sym: string }>();
  const symbols = useLiveStore((s) => s.symbols);

  if (!sym) return <SymbolPicker symbols={symbols} />;
  // Keyed so switching symbols remounts: every subscription, query and banner
  // below is scoped to one instrument and none of it should carry over.
  return <SymbolDetail key={sym} sym={sym.toUpperCase()} />;
}

function SymbolPicker({ symbols }: { symbols: string[] }) {
  const navigate = useNavigate();

  return (
    <div className="mx-auto max-w-2xl">
      <Panel title="Choose a symbol">
        {symbols.length === 0 ? (
          <EmptyState>Awaiting the symbol list from the gateway</EmptyState>
        ) : (
          <div className="flex flex-wrap gap-2">
            {symbols.map((symbol) => (
              <button
                key={symbol}
                type="button"
                onClick={() => navigate(`/symbol/${symbol}`)}
                className="rounded border border-border px-3 py-1.5 text-sm font-semibold hover:border-accent hover:text-accent"
              >
                {symbol}
              </button>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

function SymbolDetail({ sym }: { sym: string }) {
  const [preset, setPreset] = useState<Preset>("1D");
  const [showCandles, setShowCandles] = useState(true);
  const [showMidpoint, setShowMidpoint] = useState(true);
  const [showDepth, setShowDepth] = useState(false);
  const [dismissedAuction, setDismissedAuction] = useState<number | null>(null);

  const top = useLiveStore((s) => s.top[sym]);
  const halted = useLiveStore((s) => s.halted[sym]);
  const haltEnded = useLiveStore((s) => s.haltEnded[sym]);
  const sessionPhase = useLiveStore((s) => s.sessionPhase);
  const depth = useLiveStore((s) => s.depth);
  const midTail = useLiveStore((s) => s.midTail[sym]);
  const auctions = useLiveStore((s) => s.auctions);
  const theme = usePrefsStore((s) => s.theme);
  const rowClass = DENSITY_ROW_CLASS[usePrefsStore((s) => s.density)];

  // Halt detail for the whole time this view is open (§6.4).
  useEffect(() => {
    sendControl({ t: "subscribe", ch: "CB", sym });
    return () => sendControl({ t: "unsubscribe", ch: "CB", sym });
  }, [sym]);

  // Depth only while asked for: unlike the always-on wildcard channels, this
  // opens a new upstream subscription (§9.2).
  useEffect(() => {
    if (!showDepth) return;
    sendControl({ t: "subscribe", ch: "DEPTH", sym });
    return () => sendControl({ t: "unsubscribe", ch: "DEPTH", sym });
  }, [showDepth, sym]);

  const spec = useMemo(() => timeframeSpec(preset), [preset]);

  const { data: dailyToday } = useQuery({
    queryKey: ["history", "daily", sym],
    queryFn: () => api.dailyForSymbol(sym),
    // High/low/VWAP/volume/trades are recalculated by pm-stats on every trade,
    // so a short re-poll keeps them live without this tab accumulating its own
    // running totals (§9.5).
    refetchInterval: 10_000,
  });
  const todayRow = dailyToday?.daily?.[0];

  const { data: history, isLoading: historyLoading } = useQuery<ChartSeries>({
    queryKey: ["history", "series", sym, preset],
    queryFn: async () =>
      spec.source === "trades"
        ? { kind: "trades", rows: (await api.trades(sym, spec.from)).trades }
        : { kind: "daily", rows: (await api.dailyRange(sym, spec.from)).daily },
    staleTime: 60_000,
  });

  const { data: snapshots } = useQuery({
    queryKey: ["history", "snapshots", sym, preset],
    queryFn: () => api.priceSnapshots(sym, spec.from),
    staleTime: 60_000,
    enabled: showMidpoint,
  });

  const { bars, volume } = useMemo(() => {
    if (!history) return { bars: [], volume: [] };
    return history.kind === "trades"
      ? bucketTrades(history.rows, spec.bucketSec ?? 60)
      : dailyToBars(history.rows);
  }, [history, spec.bucketSec]);

  const mid = useMemo(() => midpointSeries(snapshots?.snapshots ?? [], midTail ?? []), [snapshots, midTail]);

  // Only this symbol's uncrosses, newest first, and only while still fresh.
  const auction = auctions.find((a) => a.sym === sym);
  useEffect(() => setDismissedAuction(null), [auction?.seq]);
  useEffect(() => {
    if (!auction || dismissedAuction === auction.seq) return;
    const timer = setTimeout(() => setDismissedAuction(auction.seq), AUCTION_BANNER_MS);
    return () => clearTimeout(timer);
  }, [auction, dismissedAuction]);

  const last = top?.last;
  const phase = halted ? "HALTED" : sessionPhase;
  const { closes: prevCloses, unavailable: prevCloseGone } = usePrevCloses();
  const prevClose = prevCloses[sym];
  // One symbol for the whole view, so one lookup rather than one per figure.
  const decimals = useSymbolDecimals(sym);

  /*
   * The header's change figures come from the same `buildRows` the Overview
   * grid and the Movers board use, over a one-symbol universe.
   *
   * This view used to compute them itself, which is how it came to measure
   * from the session open while claiming the same "%Chg" label as everywhere
   * else. Two implementations of one definition will drift; one cannot.
   * `spread` and `turnover` below come along for free.
   */
  const row = useMemo(
    () =>
      buildRows({
        symbols: [sym],
        top: top ? { [sym]: top } : {},
        daily: todayRow ? { [sym]: todayRow } : {},
        prevClose: prevCloses,
        // This view shows the tape's own timestamps, not a row freshness mark.
        lastTradeTs: {},
        halted: halted ? { [sym]: halted } : {},
        watchlist: [],
        filter: "all",
      })[0],
    [sym, top, todayRow, prevCloses, halted],
  );

  return (
    <div className="flex h-full flex-col gap-3">
      <header className="flex items-baseline gap-4 px-1">
        <h1 className="text-2xl font-bold tracking-tight">{sym}</h1>
        <SessionBadge phase={phase} />
        <span className="tabular text-2xl">{price(last, decimals)}</span>
        <span
          className={clsx(
            "tabular text-sm",
            row?.chg === undefined || row.chg === 0
              ? "text-fg-subtle"
              : row.chg > 0
                ? "text-up"
                : "text-down",
          )}
        >
          {row?.chg === undefined ? ABSENT : `${row.chg > 0 ? "+" : ""}${row.chg.toFixed(decimals)}`}
          {row?.pctChg !== undefined && ` (${row.pctChg > 0 ? "+" : ""}${row.pctChg.toFixed(2)}%)`}
        </span>
        <span className="text-xs text-fg-faint">
          {row?.baseline === "open" ? "vs today’s open — no previous close" : "vs prev close"}
        </span>
        <span className="text-sm text-fg-subtle">Vol {qty(todayRow?.volume)}</span>
      </header>

      {prevCloseGone && (
        <p className="px-1 text-xs text-halt">
          Change is measured from today&rsquo;s open — the previous close is unavailable.
        </p>
      )}

      {halted?.context && <HaltDetail context={halted.context} decimals={decimals} />}

      {!halted && haltEnded?.reason === "CLOSING_BACKSTOP" && (
        <BackstopNotice context={haltEnded} decimals={decimals} />
      )}

      {auction && dismissedAuction !== auction.seq && (
        <div className="flex items-center gap-3 rounded border border-auction/40 bg-auction-bg px-3 py-2 text-sm">
          <span className="font-semibold text-auction">{auctionTitle(auction.reason)}</span>
          <span className="tabular">
            {auction.eqPrice === undefined ? "no cross" : price(auction.eqPrice, decimals)} ·{" "}
            {qty(auction.eqQty)} sh
            {auction.imbalanceSide && ` · imbalance ${auction.imbalanceSide} ${qty(auction.imbalanceQty)}`}
          </span>
          <span className="tabular text-fg-subtle">{clockUtc(auction.ts)}</span>
          <button
            type="button"
            onClick={() => setDismissedAuction(auction.seq)}
            aria-label="Dismiss auction result"
            className="ml-auto text-fg-subtle hover:text-fg"
          >
            ✕
          </button>
        </div>
      )}

      <Panel
        title="Chart"
        right={
          <div className="flex items-center gap-3 text-xs">
            <div className="flex gap-1">
              {PRESETS.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setPreset(option)}
                  className={clsx(
                    "rounded px-2 py-0.5",
                    preset === option ? "bg-accent text-accent-fg" : "text-fg-subtle hover:bg-bg-inset",
                  )}
                >
                  {option}
                </button>
              ))}
            </div>
            <Toggle checked={showCandles} onChange={setShowCandles} label="OHLC" />
            <Toggle checked={showMidpoint} onChange={setShowMidpoint} label="Midpoint" />
            <Toggle checked={showDepth} onChange={setShowDepth} label="Depth" />
          </div>
        }
      >
        <div className="h-[22rem]">
          {historyLoading ? (
            <EmptyState>Loading history…</EmptyState>
          ) : bars.length === 0 && mid.live.length === 0 && mid.historical.length === 0 ? (
            <EmptyState>No history recorded for {sym} in this window</EmptyState>
          ) : (
            <PriceChart
              bars={bars}
              volume={volume}
              midHistorical={mid.historical}
              midLive={mid.live}
              showCandles={showCandles}
              showMidpoint={showMidpoint}
              prevClose={prevClose}
              // Today's VWAP is a benchmark only within today's own session.
              // `spec.source === "trades"` is not the right test for that: 5D
              // is also trade-bucketed but spans five sessions, so a flat
              // line at today's VWAP would be a real benchmark for only the
              // last of those five days and a coincidence for the rest —
              // smaller-scale version of the same failure the `1M`/`3M`/
              // `YTD`/`All` daily-bar presets have. Gate on the preset
              // itself: `1D` and `Live` are the two windowed at today's open
              // and no earlier, which `timeframeSpec` guarantees (T-H2).
              vwap={preset === "1D" || preset === "Live" ? (todayRow?.vwap ?? undefined) : undefined}
              follow={spec.follow}
              theme={theme}
            />
          )}
        </div>
        {showMidpoint && mid.liveOnly && mid.live.length > 0 && (
          <p className="mt-1 text-[10px] text-fg-faint">
            Mid data begins here — no recorded snapshots for this window.
          </p>
        )}
      </Panel>

      <div className="grid grid-cols-2 gap-3">
        <Panel title="Values">
          <Values
            row={row}
            top={top}
            today={todayRow}
            prevClose={prevClose}
            phase={phase}
            rowClass={rowClass}
            decimals={decimals}
          />
        </Panel>

        {/*
         * Depth replaces the right-hand panel rather than sitting alongside
         * (§9.2). Off by default: it is the one panel that costs an upstream
         * subscription.
         */}
        <Panel title={showDepth ? `Depth — ${sym}` : "Depth"}>
          {showDepth ? (
            <DepthLadder frame={depth?.sym === sym ? depth : null} rowClass={rowClass} decimals={decimals} />
          ) : (
            <EmptyState>Enable the Depth toggle to subscribe to the order book</EmptyState>
          )}
        </Panel>
      </div>
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-1 text-fg-subtle hover:text-fg">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

/** Expanded circuit-breaker context for a halted symbol (§9.3a). */
/**
 * Name the uncross rather than calling all three "Auction uncrossed".
 *
 * A reopening auction after a circuit-breaker halt and the scheduled closing
 * auction produce the same fields, and until the gateway carried REASON there
 * was no way to tell a viewer which one they were looking at. An older
 * gateway sends no reason, so the generic wording remains the fallback.
 */
function auctionTitle(reason: AuctionReason | undefined): string {
  if (reason === "REOPEN") return "Reopening auction";
  if (reason === "RECOVERY") return "Startup uncross";
  return "Auction uncrossed";
}

/**
 * Where the indicative price sits relative to the corridor, as a 0..1
 * position for the marker. Clamped to the ends so a wildly outlying price
 * still renders on the bar rather than escaping it.
 */
function markerPosition(low: number, high: number, value: number): number {
  if (high <= low) return 0.5;
  return Math.min(1, Math.max(0, (value - low) / (high - low)));
}

/**
 * The corridor a halted symbol may reopen inside, with the last indicative
 * price marked against it.
 *
 * This is the whole explanation of why a halt is still running: the price is
 * outside the band, so the call phase was extended instead of printing. A
 * numeric readout alone makes the reader do that comparison in their head.
 */
function CorridorBar({ context, decimals }: { context: HaltContextFrame; decimals: number }) {
  const { corridorLow: low, corridorHigh: high, indicativePrice } = context;
  if (low === undefined || high === undefined) return null;

  const outside = indicativePrice !== undefined && (indicativePrice < low || indicativePrice > high);

  return (
    <div className="mt-2">
      <div className="flex items-baseline justify-between text-xs text-fg-subtle">
        <span className="tabular">{price(low, decimals)}</span>
        <span>may reopen inside</span>
        <span className="tabular">{price(high, decimals)}</span>
      </div>
      <div className="relative mt-1 h-2 rounded bg-halt/20">
        <div className="absolute inset-y-0 left-0 right-0 rounded border border-halt/50" />
        {indicativePrice !== undefined && (
          <div
            className={clsx("absolute top-1/2 h-3 w-0.5 -translate-y-1/2", outside ? "bg-error" : "bg-ok")}
            style={{ left: `${markerPosition(low, high, indicativePrice) * 100}%` }}
            aria-hidden
          />
        )}
      </div>
      {indicativePrice !== undefined && (
        <p className="mt-1 text-xs">
          <span className={outside ? "text-error" : "text-ok"}>
            Would reopen at {price(indicativePrice, decimals)}
          </span>
          {context.indicativeQty !== undefined && (
            <span className="text-fg-subtle"> for {qty(context.indicativeQty)}</span>
          )}
          {context.imbalanceSide && (
            <span className="text-fg-subtle"> · {context.imbalanceSide} imbalance</span>
          )}
          {outside && (
            <span className="text-fg-subtle"> — outside the corridor, so the auction was extended</span>
          )}
        </p>
      )}
    </div>
  );
}

function HaltDetail({ context, decimals }: { context: HaltContextFrame; decimals: number }) {
  const extended = (context.expansion ?? 0) > 0;
  return (
    <div className="rounded border border-halt/40 bg-halt-bg px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-4">
        <span className="font-semibold text-halt">Halted</span>
        {context.level && <span>Level {context.level}</span>}
        {extended && (
          <span
            className="rounded bg-halt/20 px-1.5 py-0.5 text-xs"
            title="The reopening auction has been extended because the price was outside the corridor"
          >
            extension {context.expansion}
          </span>
        )}
        {context.triggerPrice !== undefined && (
          <span className="tabular">Trigger {price(context.triggerPrice, decimals)}</span>
        )}
        {context.referencePrice !== undefined && (
          <span className="tabular">Reference {price(context.referencePrice, decimals)}</span>
        )}
        {context.haltSource && <span className="text-fg-subtle">{context.haltSource}</span>}
        <span className="tabular">
          {/*
            "Not before", not "Reopens at". Every call phase ends at a random
            point after its minimum duration so the uncross instant cannot be
            targeted, and the corridor may extend it further still. Naming an
            exact time would be a promise the exchange does not make.
          */}
          {context.resumeAt ? `Not before ${resumeAt(context.resumeAt)}` : "Reopens manually"}
        </span>
      </div>
      <CorridorBar context={context} decimals={decimals} />
    </div>
  );
}

/**
 * A resume the end of the trading day forced.
 *
 * Worth its own banner because the price was *imposed* at the corridor
 * boundary rather than discovered by the book. Presenting it as an ordinary
 * print would misrepresent the close.
 */
function BackstopNotice({ context, decimals }: { context: HaltContextFrame; decimals: number }) {
  if (context.reason !== "CLOSING_BACKSTOP") return null;
  return (
    <div className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
      <span className="font-semibold text-warning">Closing backstop</span>
      <span className="ml-3">The trading day ended before the auction could reopen inside its corridor.</span>
      {context.printPrice !== undefined && (
        <span className="ml-1 tabular">
          Printed at {price(context.printPrice, decimals)}
          {context.clamped && (
            <span className="text-fg-subtle"> — the corridor boundary, not a discovered price</span>
          )}
          .
        </span>
      )}
    </div>
  );
}

interface ValueRow {
  label: string;
  value: string;
  /** A qualifier shown muted beside the figure — a size, a bps form, a comparison. */
  note?: string;
  tone?: string;
}

/**
 * The instrument's numbers, in four reading groups.
 *
 * Previously one flat eleven-row list, which meant re-scanning all eleven to
 * find any one of them — Open sat above Last, and the quote sat between them.
 * Grouped, the eye goes to a block:
 *
 *   Quote      what can be traded against right now
 *   Session    where the price has been today
 *   Activity   how much has actually changed hands
 *   Status     what the exchange says the instrument is doing
 *
 * "Prev close" also used to be `close_price` from *today's* rollup row, which
 * is today's running close — the last price under a second name. The real
 * previous close comes from the day before (`lib/prev-close.ts`).
 */
function Values({
  row,
  top,
  today,
  prevClose,
  phase,
  rowClass,
  decimals,
}: {
  row: OverviewRow | undefined;
  top: TopOfBook | undefined;
  today: DailyBar | undefined;
  prevClose: number | undefined;
  phase: string | null;
  rowClass: string;
  decimals: number;
}) {
  const mid = midOf(top?.bid, top?.ask);
  const bps = spreadBps(top?.bid, top?.ask);
  const perTrade = avgTradeSize(today?.volume, today?.trade_count);

  const quote: ValueRow[] = [
    { label: "Bid", value: price(top?.bid, decimals), note: sizeNote(top?.bidSz), tone: "text-up" },
    { label: "Ask", value: price(top?.ask, decimals), note: sizeNote(top?.askSz), tone: "text-down" },
    {
      label: "Spread",
      value: price(row?.spread, decimals),
      // Basis points alongside the absolute figure: 0.02 wide is tight on a
      // 500.00 instrument and very wide on a 5.00 one, and only the relative
      // form says which this is.
      ...(bps === undefined ? {} : { note: `${bps.toFixed(0)} bps` }),
    },
    { label: "Mid (live)", value: price(mid, decimals) },
  ];

  const session: ValueRow[] = [
    { label: "Prev close", value: price(prevClose, decimals) },
    { label: "Open", value: price(today?.open_price, decimals) },
    { label: "High", value: price(today?.high_price, decimals) },
    { label: "Low", value: price(today?.low_price, decimals) },
    { label: "Last", value: price(top?.last, decimals) },
    {
      label: "VWAP",
      value: price(today?.vwap, decimals),
      // The benchmark every intraday execution is judged against, so where the
      // last print sits relative to it is the reading, not the level itself.
      ...vwapComparison(top?.last, today?.vwap),
    },
  ];

  const activity: ValueRow[] = [
    { label: "Volume", value: qty(today?.volume) },
    { label: "Turnover", value: compact(row?.turnover) },
    { label: "Trades", value: qty(today?.trade_count) },
    { label: "Avg trade", value: perTrade === undefined ? ABSENT : qty(Math.round(perTrade)) },
  ];

  return (
    <table className="w-full text-left">
      <Group title="Quote" rows={quote} rowClass={rowClass} />
      <Group title="Session" rows={session} rowClass={rowClass}>
        <DayRangeBar low={today?.low_price} high={today?.high_price} last={top?.last} decimals={decimals} />
      </Group>
      <Group title="Activity" rows={activity} rowClass={rowClass} />
      {/* "Phase", not "Session" — the group above already owns that word here. */}
      <Group title="Status" rows={[{ label: "Phase", value: phase ?? ABSENT }]} rowClass={rowClass} />
    </table>
  );
}

/** `× 1,200` beside a price — the size that quote is good for. */
function sizeNote(size: number | undefined): string | undefined {
  return size === undefined ? undefined : `× ${qty(size)}`;
}

function vwapComparison(last: number | undefined, vwap: number | null | undefined): Partial<ValueRow> {
  if (last === undefined || vwap === null || vwap === undefined || last === vwap) return {};
  return last > vwap ? { note: "last above", tone: "text-up" } : { note: "last below", tone: "text-down" };
}

function Group({
  title,
  rows,
  rowClass,
  children,
}: {
  title: string;
  rows: ValueRow[];
  rowClass: string;
  children?: ReactNode;
}) {
  return (
    <tbody>
      <tr>
        <th
          colSpan={2}
          className="pb-1 pt-3 text-left text-[10px] font-medium uppercase tracking-widest text-fg-faint"
        >
          {title}
        </th>
      </tr>
      {rows.map(({ label, value, note, tone }) => (
        <tr key={label} className={`border-b border-border/40 ${rowClass}`}>
          <td className="text-fg-subtle">{label}</td>
          <td className="text-right tabular">
            {note && <span className="mr-1.5 text-xs text-fg-faint">{note}</span>}
            <span className={tone} data-testid={`value-${label}`}>
              {value}
            </span>
          </td>
        </tr>
      ))}
      {children}
    </tbody>
  );
}

/**
 * Where the last price sits between the session's low and high.
 *
 * High, Low and Last as three separate numbers make the reader do the
 * subtraction; a marker on a bar is read at a glance. Same device as the
 * halt corridor above, for the same reason.
 */
function DayRangeBar({
  low,
  high,
  last,
  decimals,
}: {
  low: number | null | undefined;
  high: number | null | undefined;
  last: number | undefined;
  decimals: number;
}) {
  const position = rangePosition(low, high, last);
  if (position === undefined) return null;

  return (
    <tr>
      <td colSpan={2} className="pb-1 pt-2">
        <div className="flex items-baseline justify-between text-[10px] text-fg-faint">
          <span className="tabular">{price(low, decimals)}</span>
          <span>session range</span>
          <span className="tabular">{price(high, decimals)}</span>
        </div>
        <div className="relative mt-1 h-2 rounded bg-bg-inset">
          <div
            className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 bg-accent"
            style={{ left: `${position * 100}%` }}
            data-testid="range-marker"
            aria-hidden
          />
        </div>
      </td>
    </tr>
  );
}

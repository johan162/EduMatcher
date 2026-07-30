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
import { useEffect, useMemo, useState } from "react";
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
import { ABSENT, clockUtc, price, qty, resumeAt } from "../lib/format.js";
import { PRESETS, timeframeSpec, type Preset } from "../lib/timeframe.js";
import { sendControl } from "../lib/useTerminalStream.js";
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
  const open = todayRow?.open_price ?? undefined;
  const chg = last !== undefined && open !== undefined && open !== null ? last - open : undefined;
  const pctChg = chg !== undefined && open ? (chg / open) * 100 : undefined;
  const phase = halted ? "HALTED" : sessionPhase;

  return (
    <div className="flex h-full flex-col gap-3">
      <header className="flex items-baseline gap-4 px-1">
        <h1 className="text-2xl font-bold tracking-tight">{sym}</h1>
        <SessionBadge phase={phase} />
        <span className="tabular text-2xl">{price(last)}</span>
        <span
          className={clsx(
            "tabular text-sm",
            chg === undefined || chg === 0 ? "text-fg-subtle" : chg > 0 ? "text-up" : "text-down",
          )}
        >
          {chg === undefined ? ABSENT : `${chg > 0 ? "+" : ""}${chg.toFixed(2)}`}
          {pctChg !== undefined && ` (${pctChg > 0 ? "+" : ""}${pctChg.toFixed(2)}%)`}
        </span>
        <span className="text-sm text-fg-subtle">Vol {qty(todayRow?.volume)}</span>
      </header>

      {halted?.context && <HaltDetail context={halted.context} />}

      {auction && dismissedAuction !== auction.seq && (
        <div className="flex items-center gap-3 rounded border border-auction/40 bg-auction-bg px-3 py-2 text-sm">
          <span className="font-semibold text-auction">{auctionTitle(auction.reason)}</span>
          <span className="tabular">
            {auction.eqPrice === undefined ? "no cross" : price(auction.eqPrice)} · {qty(auction.eqQty)} sh
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
          <Values top={top} today={todayRow} phase={phase} rowClass={rowClass} />
        </Panel>

        {/*
         * Depth replaces the right-hand panel rather than sitting alongside
         * (§9.2). Off by default: it is the one panel that costs an upstream
         * subscription.
         */}
        <Panel title={showDepth ? `Depth — ${sym}` : "Depth"}>
          {showDepth ? (
            <DepthLadder frame={depth?.sym === sym ? depth : null} rowClass={rowClass} />
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

function HaltDetail({ context }: { context: HaltContextFrame }) {
  return (
    <div className="flex items-center gap-4 rounded border border-halt/40 bg-halt-bg px-3 py-2 text-sm">
      <span className="font-semibold text-halt">Halted</span>
      {context.level && <span>Level {context.level}</span>}
      {context.triggerPrice !== undefined && (
        <span className="tabular">Trigger {price(context.triggerPrice)}</span>
      )}
      {context.referencePrice !== undefined && (
        <span className="tabular">Reference {price(context.referencePrice)}</span>
      )}
      {context.haltSource && <span className="text-fg-subtle">{context.haltSource}</span>}
      <span className="tabular">
        {context.resumeAt ? `Reopens ${resumeAt(context.resumeAt)}` : "Reopens manually"}
      </span>
    </div>
  );
}

function Values({
  top,
  today,
  phase,
  rowClass,
}: {
  top: TopOfBook | undefined;
  today: DailyBar | undefined;
  phase: string | null;
  rowClass: string;
}) {
  const mid = midOf(top?.bid, top?.ask);

  const rows: Array<[string, string]> = [
    ["Open", price(today?.open_price)],
    ["High", price(today?.high_price)],
    ["Low", price(today?.low_price)],
    ["Last", price(top?.last)],
    ["Bid / Ask", `${price(top?.bid)} / ${price(top?.ask)}`],
    ["Mid (live)", price(mid)],
    ["VWAP", price(today?.vwap)],
    ["Prev close", price(today?.close_price)],
    ["Volume", qty(today?.volume)],
    ["Trades", qty(today?.trade_count)],
    ["Session", phase ?? ABSENT],
  ];

  return (
    <table className="w-full text-left">
      <tbody>
        {rows.map(([label, value]) => (
          <tr key={label} className={`border-b border-border/40 ${rowClass}`}>
            <td className="text-fg-subtle">{label}</td>
            <td className="text-right tabular" data-testid={`value-${label}`}>
              {value}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

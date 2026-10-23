/**
 * The order-book drawer of the Market overview: a symbol's state and figures,
 * and its trades and traded value per minute today. The same drawer as
 * dash-gui's, less what only an operator needs (heap garbage, memory, the
 * event log) and what only pm-monitor knows (resting and stop orders).
 */

import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Drawer } from "../components/layout/Drawer.js";
import { MinuteBars } from "../components/MinuteBars.js";
import { api } from "../lib/api.js";
import { ABSENT, compact, price, qty } from "../lib/format.js";
import { perMinute } from "../lib/minute-buckets.js";
import type { OverviewRow } from "../lib/overview-rows.js";
import { timeframeSpec } from "../lib/timeframe.js";
import { useLiveStore } from "../store/useLiveStore.js";
import { usePrefsStore } from "../store/usePrefsStore.js";

/** Label and value pairs, in a grid that wraps on narrow drawers. */
function Facts({ label, items }: { label: string; items: readonly (readonly [string, ReactNode])[] }) {
  return (
    <dl aria-label={label} className="m-0 grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
      {items.map(([name, value]) => (
        <div key={name} className="min-w-0">
          <dt className="truncate text-[11px] uppercase tracking-wide text-fg-faint">{name}</dt>
          <dd className="m-0 truncate tabular text-fg">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="mt-5">
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">{title}</h3>
      {children}
    </section>
  );
}

export interface BookDrawerProps {
  symbol: string;
  /** The symbol's row, absent when the gateway's symbol list does not hold it. */
  row: OverviewRow | undefined;
  tradeCount: number | null | undefined;
  /** The symbol's display precision. */
  decimals: number;
  onClose: () => void;
}

export function BookDrawer({ symbol, row, tradeCount, decimals, onClose }: BookDrawerProps) {
  const theme = usePrefsStore((s) => s.theme);
  const sessionPhase = useLiveStore((s) => s.sessionPhase);
  const { data } = useQuery({
    queryKey: ["history", "trades", symbol, "today"],
    queryFn: () => api.trades(symbol, timeframeSpec("1D").from),
    // pm-stats records every print, so a short re-poll keeps the bars live.
    refetchInterval: 10_000,
    enabled: row !== undefined,
  });
  const activity = perMinute(data?.trades ?? []);

  const link = (
    <Link to={`/symbol/${encodeURIComponent(symbol)}`} className="whitespace-nowrap text-accent hover:underline">
      Symbol detail
    </Link>
  );
  if (!row) {
    return (
      <Drawer kind="Order book" title={symbol} onClose={onClose}>
        <p role="status" className="m-0 text-sm text-fg-subtle">
          No order book “{symbol}” in the gateway&rsquo;s symbol list.
        </p>
      </Drawer>
    );
  }

  const state = row.halted ? "HALTED" : (sessionPhase?.replaceAll("_", " ").toLowerCase() ?? ABSENT);
  return (
    <Drawer kind="Order book" title={symbol} actions={link} onClose={onClose}>
      <Facts
        label="Book figures"
        items={[
          ["State", state],
          ["Last", price(row.last, decimals)],
          ["Bid", `${price(row.bid, decimals)} × ${qty(row.bidSz)}`],
          ["Ask", `${price(row.ask, decimals)} × ${qty(row.askSz)}`],
          ["Spread", price(row.spread, decimals)],
          ["Volume", qty(row.volume)],
          ["Turnover", compact(row.turnover)],
          ["Trades today", qty(tradeCount)],
        ]}
      />
      <Section title="Activity">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <MinuteBars label="Trades per minute" points={activity.trades} format={qty} theme={theme} />
          <MinuteBars label="Traded value per minute" points={activity.value} format={compact} theme={theme} />
        </div>
      </Section>
    </Drawer>
  );
}

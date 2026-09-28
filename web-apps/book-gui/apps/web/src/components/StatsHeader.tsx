/**
 * The two statistics rows (design §3.1, §9.3), field for field pm-viewer's
 * `_build_header`, with the clock and date pinned right in the exchange
 * session timezone.
 */

import clsx from "clsx";
import type { BookFrame, SessionStats } from "@edumatcher/book-types";
import { clock, hhmm, isoDate, pct, price, qty, signedPrice } from "../lib/format.js";
import { useNow } from "../lib/hooks.js";
import {
  ARROW,
  basis,
  change,
  changePct,
  range,
  reference,
  spread,
  trend,
  type Trend,
} from "../lib/stats.js";

const TREND_CLASS: Record<Trend, string> = { up: "text-up", down: "text-down", flat: "text-fg-subtle" };

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <span className="flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="text-[11px] font-semibold uppercase tracking-wider text-fg-faint">{label}</span>
      {children}
    </span>
  );
}

const Sep = () => <span className="h-4 w-px self-center bg-border" aria-hidden="true" />;

export function StatsHeader({
  book,
  stats,
  decimals,
}: {
  book: BookFrame | null;
  stats: SessionStats | null;
  decimals: number;
}) {
  const now = useNow(1000);
  const tz = stats?.timezone ?? "UTC";
  const ref = reference(stats);
  const last = book?.last;
  const lastTrend = trend(last, ref);
  const bid = book?.bids[0]?.price;
  const ask = book?.asks[0]?.price;
  const basisKind = basis(stats);

  return (
    <section aria-label="Statistics" className="shrink-0 font-mono tabular text-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <Field label="Last">
          <span className={clsx("text-lg font-bold", TREND_CLASS[lastTrend])} data-testid="last">
            {price(last, decimals)} {ARROW[lastTrend]}
          </span>
        </Field>
        <Field label="Chg">
          <span className={TREND_CLASS[lastTrend]} data-testid="chg">
            {signedPrice(change(last, ref), decimals)}
          </span>
          <span className={clsx("font-bold", TREND_CLASS[lastTrend])} data-testid="pct">
            {pct(changePct(last, ref))}
          </span>
        </Field>
        <Sep />
        <Field label="Size">
          <span className="text-fg" data-testid="size">
            {qty(book?.lastQty)}
          </span>
        </Field>
        <Sep />
        <Field label="Bid/Ask">
          <span className="text-up" data-testid="bid">
            {price(bid, decimals)}
          </span>
          <span className="text-fg-faint">×</span>
          <span className="text-down" data-testid="ask">
            {price(ask, decimals)}
          </span>
        </Field>
        <Sep />
        <Field label="Sprd">
          <span className="text-halt" data-testid="spread">
            {price(spread(bid, ask), decimals)}
          </span>
        </Field>
        <span className="ml-auto text-base font-bold text-accent" data-testid="clock" title={tz}>
          {clock(now, tz)}
        </span>
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
        <Field label="O">
          <span className="text-fg" data-testid="open">
            {price(stats?.open, decimals)}
          </span>
        </Field>
        <Field label="H">
          <span className="text-up" data-testid="high">
            {price(stats?.high, decimals)}
          </span>
        </Field>
        <Field label="L">
          <span className="text-down" data-testid="low">
            {price(stats?.low, decimals)}
          </span>
        </Field>
        <Field label="C">
          <span className="text-fg" data-testid="close">
            {price(stats?.close, decimals)}
          </span>
        </Field>
        <Sep />
        <Field label="Prev">
          <span className="text-fg" data-testid="prev">
            {stats?.prevClose === undefined ? "n/a" : price(stats.prevClose, decimals)}
          </span>
        </Field>
        <Sep />
        <Field label="Range">
          <span className="text-auction" data-testid="range">
            {price(range(stats), decimals)}
          </span>
        </Field>
        <Sep />
        <Field label="Vol">
          <span className="text-fg" data-testid="volume">
            {qty(stats?.volume)}
          </span>
        </Field>
        <span className="ml-auto flex items-center gap-4">
          <Field label="Basis">
            <span className={basisKind === "live-since" ? "text-halt" : "text-fg-subtle"} data-testid="basis">
              {basisKind === "live-since" ? `live since ${hhmm(stats?.since ?? now, tz)}` : basisKind}
            </span>
          </Field>
          <Sep />
          <span className="text-accent" data-testid="date">
            {isoDate(now, tz)}
          </span>
        </span>
      </div>

      <div
        data-testid="trend-line"
        data-trend={trend(stats?.close, ref)}
        className={clsx(
          "mt-2 h-0.5 rounded",
          { up: "bg-up", down: "bg-down", flat: "bg-border-strong" }[trend(stats?.close, ref)],
        )}
      />
    </section>
  );
}

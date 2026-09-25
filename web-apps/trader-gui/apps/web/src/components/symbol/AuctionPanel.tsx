import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useBookStore } from "@/store/useBookStore.js";
import { useSessionStore } from "@/store/useSessionStore.js";
import { isAuctionPhase } from "@/lib/marketRows.js";
import { formatPrice, formatQty } from "@/lib/formatters.js";
import type { BookEntry } from "@/store/useBookStore.js";
import { useThemeStore } from "@/store/useThemeStore.js";
import { CHART_COLORS } from "@/lib/chartTheme.js";

/**
 * Cumulative supply/demand curve from the resting book (§16.6): demand is the
 * bid quantity available at or above each price, supply the ask quantity at or
 * below it. The two cross near the equilibrium price — the visual the panel
 * exists to teach. Derived from the resting book, so it is a live educational
 * aid; the authoritative eq price is the engine's indicative/final value shown
 * above it.
 */
function buildCurve(entry: BookEntry | undefined) {
  if (!entry) return [];
  const prices = [
    ...entry.bids.map((l) => l.price),
    ...entry.asks.map((l) => l.price),
  ].sort((a, b) => a - b);
  const unique = [...new Set(prices)];
  return unique.map((price) => {
    const demand = entry.bids.filter((l) => l.price >= price).reduce((s, l) => s + l.qty, 0);
    const supply = entry.asks.filter((l) => l.price <= price).reduce((s, l) => s + l.qty, 0);
    return { price, demand, supply };
  });
}

interface AuctionPanelProps {
  symbol: string;
  tickDecimals: number;
}

/**
 * Auction / indicative-price panel (§16.6). During a call phase it shows the
 * engine's running indicative uncross; outside one it shows the most recent
 * completed auction result. `eq_price: null` is a real reading ("would not
 * cross"), not a missing value.
 */
export function AuctionPanel({ symbol, tickDecimals }: AuctionPanelProps) {
  const entry = useBookStore((s) => s.books[symbol]);
  const phase = useSessionStore((s) => s.phase);
  const auction = entry?.auction ?? null;
  const colors = CHART_COLORS[useThemeStore((s) => s.theme)];
  const inAuction = isAuctionPhase(phase);

  const curve = useMemo(() => buildCurve(entry), [entry]);

  const heading = auction
    ? auction.indicative
      ? "Indicative uncross (live)"
      : "Most recent auction result"
    : inAuction
      ? "Waiting for indicative…"
      : "No recent auction";

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium ${
            inAuction ? "bg-auction text-black" : "bg-elevated text-fg-dim"
          }`}
        >
          {inAuction ? `${phase.replace("_", " ")}` : "Continuous"}
        </span>
        <span className="text-xs text-fg-dim">{heading}</span>
      </div>

      {auction ? (
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded border border-line bg-panel px-3 py-2">
            <div className="text-[10px] uppercase tracking-wide text-fg-faint">Eq. price</div>
            <div className="text-sm font-mono text-fg">
              {auction.eqPrice === null ? "no cross" : formatPrice(auction.eqPrice, tickDecimals)}
            </div>
          </div>
          <div className="rounded border border-line bg-panel px-3 py-2">
            <div className="text-[10px] uppercase tracking-wide text-fg-faint">Matched qty</div>
            <div className="text-sm font-mono text-fg">{formatQty(auction.eqQty)}</div>
          </div>
          <div className="rounded border border-line bg-panel px-3 py-2">
            <div className="text-[10px] uppercase tracking-wide text-fg-faint">Imbalance side</div>
            <div
              className={`text-sm font-mono ${
                auction.imbalanceSide === "BUY"
                  ? "text-bid"
                  : auction.imbalanceSide === "SELL"
                    ? "text-ask"
                    : "text-fg-dim"
              }`}
            >
              {auction.imbalanceSide ?? "balanced"}
            </div>
          </div>
          <div className="rounded border border-line bg-panel px-3 py-2">
            <div className="text-[10px] uppercase tracking-wide text-fg-faint">Imbalance qty</div>
            <div className="text-sm font-mono text-fg">{formatQty(auction.imbalanceQty)}</div>
          </div>
        </div>
      ) : (
        <p className="text-xs text-fg-faint">
          {inAuction
            ? "The engine has not published an indicative uncross for this symbol yet."
            : "The auction panel populates during opening and closing auctions."}
        </p>
      )}

      {curve.length > 1 && (
        <div>
          <div className="text-[10px] uppercase tracking-wide text-fg-faint mb-1">
            Cumulative supply / demand
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={curve} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
              <CartesianGrid stroke={colors.grid} />
              <XAxis
                dataKey="price"
                tick={{ fill: colors.text, fontSize: 10 }}
                tickFormatter={(v: number) => formatPrice(v, tickDecimals)}
              />
              <YAxis tick={{ fill: colors.text, fontSize: 10 }} width={44} />
              <Tooltip
                contentStyle={{
                  background: colors.background,
                  border: `1px solid ${colors.border}`,
                  color: colors.text,
                  fontSize: 11,
                }}
                labelFormatter={(v: number) => `Price ${formatPrice(v, tickDecimals)}`}
              />
              <Line
                type="stepAfter"
                dataKey="demand"
                stroke={colors.up}
                dot={false}
                name="Demand"
              />
              <Line
                type="stepBefore"
                dataKey="supply"
                stroke={colors.down}
                dot={false}
                name="Supply"
              />
              {auction?.eqPrice != null && (
                <ReferenceLine x={auction.eqPrice} stroke={colors.marker} strokeDasharray="3 3" />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

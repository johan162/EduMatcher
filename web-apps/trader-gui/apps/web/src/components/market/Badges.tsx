import { Star } from "lucide-react";
import { formatPrice } from "@/lib/formatters.js";

/**
 * Circuit-breaker halt badge (§10.4).
 * `level` is a name string ("L2") and is null on an ADMIN halt, which is why
 * the label falls back to a bare HALT rather than printing "Level null".
 */
export function HaltBadge({ level }: { level: string | null }) {
  return (
    <span
      className="inline-flex items-center px-1.5 py-0.5 rounded bg-halt text-black text-[10px] font-medium"
      title={level ? `Circuit breaker level ${level}` : "Administrative halt"}
    >
      {level ? `HALT ${level}` : "HALT"}
    </span>
  );
}

/**
 * Auction badge with the indicative equilibrium price when the engine has
 * one. `eqPrice` is legitimately null while the book would not cross — an
 * informative reading (§6.10), not a missing value, so it renders as an
 * explicit "no cross" rather than being hidden.
 */
export function AuctionBadge({
  eqPrice,
  indicative,
  tickDecimals,
}: {
  eqPrice: number | null;
  indicative: boolean;
  tickDecimals: number;
}) {
  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-auction text-black text-[10px] font-medium"
      title={indicative ? "Indicative uncross — auction still in its call phase" : "Final uncross"}
    >
      AUCTION
      <span className="price-cell">
        {eqPrice === null ? "no cross" : formatPrice(eqPrice, tickDecimals)}
      </span>
      {indicative && <span className="opacity-70">~</span>}
    </span>
  );
}

/** Watchlist star toggle (§20.4). */
export function WatchStar({
  symbol,
  watched,
  onToggle,
}: {
  symbol: string;
  watched: boolean;
  onToggle: (symbol: string) => void;
}) {
  return (
    <button
      type="button"
      // The row itself selects the symbol; the star must not do both.
      onClick={(e) => {
        e.stopPropagation();
        onToggle(symbol);
      }}
      aria-pressed={watched}
      aria-label={watched ? `Remove ${symbol} from watchlist` : `Add ${symbol} to watchlist`}
      className={watched ? "text-amber-400" : "text-[#505070] hover:text-[#9090b0]"}
    >
      <Star size={12} fill={watched ? "currentColor" : "none"} />
    </button>
  );
}

/** Signed change-% cell, coloured by direction (§10.2 ChangeCell). */
export function ChangeCell({ pct }: { pct: number | null }) {
  if (pct === null) return <span className="price-cell text-[#505070]">—</span>;
  const cls = pct > 0 ? "text-up" : pct < 0 ? "text-down" : "text-[#9090b0]";
  return (
    <span className={`price-cell ${cls}`}>
      {pct > 0 ? "+" : ""}
      {pct.toFixed(2)}%
    </span>
  );
}

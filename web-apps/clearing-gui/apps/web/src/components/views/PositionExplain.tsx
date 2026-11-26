/**
 * "How this number is made" for one position (CG25), opened from its row in
 * Explain mode: the unrealized P&L written out as a sum with the row's own
 * values, a price scale with the average cost and the mark on it, the
 * total split into its realized and unrealized parts, and (CG29) how the
 * position was built on its latest trading day, fill by fill.
 *
 * Every number is the row's, formatted with its own precision; the result of
 * each sum is the ledger's value, not one computed here, so the card can
 * never disagree with the table above it. The written-out sum uses the
 * rounded average cost, so it can differ from the result in the last
 * decimal: the ledger keeps the full average.
 */
import type { PositionRowT } from "@/api/schemas";
import { useState } from "react";
import { formatAverage as formatAverageTicks, formatPnlTicks, formatQty, formatTicks, type Ticks } from "@/lib/money";
import { PositionReplayView } from "./PositionReplayView";

function formatAverage(r: PositionRowT): string {
  return formatAverageTicks(r.avg_cost_ticks, r.tick_decimals);
}

/** The unrealized P&L as a sum, or why there is none. */
export function unrealizedSentence(r: PositionRowT): string {
  const unrealized = formatPnlTicks(r.unrealized_pnl_ticks, r.tick_decimals);
  if (r.net_qty === 0) {
    const realized = formatPnlTicks(r.realized_pnl_ticks, r.tick_decimals);
    return r.realized_pnl_ticks === 0
      ? "Flat: no shares are held, so nothing is unrealized."
      : `Flat: no shares are held, so nothing is unrealized. The realized ${realized} stays: it was locked in by the trades that closed the position.`;
  }
  if (r.mark_price_ticks === null) return "No mark yet: unrealized P&L needs a price to value the position at.";
  const avg = formatAverage(r);
  const mark = formatTicks(r.mark_price_ticks, r.tick_decimals);
  const qty = formatQty(Math.abs(r.net_qty));
  return r.net_qty > 0
    ? `Long ${qty} at average ${avg}, mark ${mark}: (${mark} − ${avg}) × ${qty} = ${unrealized}. A long gains when the mark is above its average cost.`
    : `Short ${qty} at average ${avg}, mark ${mark}: (${avg} − ${mark}) × ${qty} = ${unrealized}. A short gains when the mark is below its average cost.`;
}

const SCALE_WIDTH = 320;
const SCALE_PAD = 24;

/** A horizontal price line with the average cost and the mark, the gap shaded gain or loss. */
function PriceScale({ r }: { r: PositionRowT & { mark_price_ticks: number } }) {
  const avg = r.avg_cost_ticks;
  const mark = r.mark_price_ticks;
  const spread = Math.abs(mark - avg) || 1;
  const lo = Math.min(avg, mark) - spread / 2;
  const hi = Math.max(avg, mark) + spread / 2;
  const x = (v: number) => SCALE_PAD + ((v - lo) / (hi - lo)) * (SCALE_WIDTH - 2 * SCALE_PAD);
  const gain = r.unrealized_pnl_ticks >= 0;
  const tone = gain ? "rgb(var(--bid))" : "rgb(var(--ask))";
  const perShare = formatTicks(Math.abs(mark - avg) as Ticks, r.tick_decimals, Number.isInteger(avg) ? 0 : 2);
  const label = `Price scale: average ${formatAverage(r)}, mark ${formatTicks(mark as Ticks, r.tick_decimals)}, a ${
    gain ? "gain" : "loss"
  } of ${perShare} per share`;
  return (
    <svg role="img" aria-label={label} width={SCALE_WIDTH} height={52} className="my-2 block">
      <line x1={SCALE_PAD / 2} x2={SCALE_WIDTH - SCALE_PAD / 2} y1={26} y2={26} stroke="rgb(var(--line))" strokeWidth={2} />
      <rect x={Math.min(x(avg), x(mark))} y={20} width={Math.abs(x(mark) - x(avg))} height={12} fill={tone} opacity={0.35} />
      <line x1={x(avg)} x2={x(avg)} y1={16} y2={36} stroke="rgb(var(--fg-dim))" strokeWidth={2} />
      <line x1={x(mark)} x2={x(mark)} y1={16} y2={36} stroke={tone} strokeWidth={2} />
      <text x={x(avg)} y={11} textAnchor="middle" fontSize={10} fill="rgb(var(--fg-dim))">
        {`avg ${formatAverage(r)}`}
      </text>
      <text x={x(mark)} y={49} textAnchor="middle" fontSize={10} fill={tone}>
        {`mark ${formatTicks(mark as Ticks, r.tick_decimals)}`}
      </text>
    </svg>
  );
}

/** Realized + unrealized = total, in words and as one bar of two parts. */
function PnlSplit({ r }: { r: PositionRowT }) {
  const total = (r.realized_pnl_ticks + r.unrealized_pnl_ticks) as Ticks;
  const parts = [
    { part: "realized", ticks: r.realized_pnl_ticks },
    { part: "unrealized", ticks: r.unrealized_pnl_ticks },
  ];
  const size = Math.abs(r.realized_pnl_ticks) + Math.abs(r.unrealized_pnl_ticks);
  return (
    <div className="mt-2">
      <p>
        {`Realized ${formatPnlTicks(r.realized_pnl_ticks, r.tick_decimals)} + unrealized ${formatPnlTicks(
          r.unrealized_pnl_ticks,
          r.tick_decimals,
        )} = total ${formatPnlTicks(total, r.tick_decimals)}. Realized P&L is locked in by trades that reduced the position; unrealized P&L moves with the mark until the position is closed.`}
      </p>
      <div aria-hidden="true" className="mt-1 flex h-2 w-80 overflow-hidden rounded bg-line/40">
        {parts.map(({ part, ticks }) => (
          <div
            key={part}
            data-pnl-part={part}
            style={{ width: size ? `${(Math.abs(ticks) / size) * 100}%` : 0 }}
            className={`${ticks >= 0 ? "bg-bid" : "bg-ask"} ${part === "unrealized" ? "opacity-60" : ""}`}
          />
        ))}
      </div>
      <p aria-hidden="true" className="mt-0.5 text-[10px] text-fg-faint">
        solid: realized · faded: unrealized
      </p>
    </div>
  );
}

export function PositionExplain({ row }: { row: PositionRowT }) {
  const mark = row.mark_price_ticks;
  const [built, setBuilt] = useState(false);
  return (
    <section aria-label={`How ${row.symbol}'s P&L is made`} data-explain className="text-xs">
      <p>{unrealizedSentence(row)}</p>
      {row.net_qty !== 0 && mark !== null && <PriceScale r={{ ...row, mark_price_ticks: mark }} />}
      <PnlSplit r={row} />
      <button
        type="button"
        aria-expanded={built}
        onClick={() => setBuilt((v) => !v)}
        className="mt-2 text-link hover:underline"
      >
        Show how this position was built
      </button>
      {built && <PositionReplayView gateway={row.gateway_id} symbol={row.symbol} />}
    </section>
  );
}

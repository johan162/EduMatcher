/**
 * How one position was built through one day (CG29), from
 * `GET /clearing/position-replay` (CG28): a step chart of the position and
 * of the fill prices against the average cost, a table of the fills, and the
 * selected fill written out as a sum.
 *
 * The server replays the fills with pm-clearing's own rules; nothing here
 * recomputes a position. The sums are written with the replay's own values
 * (the previous step's average cost, the fill's price and quantity) and end
 * on the server's result. When the replay does not end where the ledger
 * does, the screen says so with both values: that is a fault to report.
 */
import { useState } from "react";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { QueryState } from "@/components/shared/QueryState";
import { usePositionReplay } from "@/api/queries";
import type { PositionReplayT, ReplayStepT } from "@/api/schemas";
import { formatAverage, formatPnlTicks, formatPosition, formatQty, formatTicks, type Ticks } from "@/lib/money";
import { positionColumn, qtyColumn, textColumn, tickColumn, timeColumn } from "./columns";

/** The server's cap on the steps of one reply (CG28 `MAX_STEPS`). */
const REPLAY_MAX_STEPS = 5000;

type Start = PositionReplayT["start"];
/** The position before a step: the start, or the previous step. */
type Before = Pick<Start, "net_qty" | "avg_cost_ticks" | "tick_decimals">;
type Row = ReplayStepT & { n: number };

function side(qty: number): string {
  return qty > 0 ? "long" : "short";
}

/** A position held before the fill: "a 200 long". */
function held(qty: number): string {
  return `a ${formatQty(Math.abs(qty))} ${side(qty)}`;
}

/** What one fill did, written out with the replay's own values. */
export function stepSentence(s: ReplayStepT, before: Before): string {
  const td = s.tick_decimals;
  const verb = s.side === "BUY" ? "Bought" : "Sold";
  const qty = formatQty(s.quantity);
  const price = formatTicks(s.price_ticks, td);
  const avgBefore = formatAverage((before.avg_cost_ticks * 10 ** (td - before.tick_decimals)) as Ticks, td);
  const avgAfter = formatAverage(s.avg_cost_ticks, td);
  const realized = formatPnlTicks(s.realized_delta_ticks, td);
  const gain = before.net_qty > 0 ? `(${price} − ${avgBefore})` : `(${avgBefore} − ${price})`;
  switch (s.kind) {
    case "open":
      return `${verb} ${qty} at ${price}: opened a ${formatQty(Math.abs(s.net_qty))} ${side(s.net_qty)} at average ${avgAfter}.`;
    case "add":
      return `${verb} ${qty} at ${price} to ${held(before.net_qty)}: now ${formatPosition(s.net_qty)}, at average (${formatQty(Math.abs(before.net_qty))} × ${avgBefore} + ${qty} × ${price}) / ${formatQty(Math.abs(s.net_qty))} = ${avgAfter}.`;
    case "reduce":
      return `${verb} ${qty} of ${held(before.net_qty)} at ${price}: realized ${gain} × ${qty} = ${realized}; average cost unchanged, now ${formatPosition(s.net_qty)}.`;
    case "close":
      return `${verb} ${qty} of ${held(before.net_qty)} at ${price}: realized ${gain} × ${qty} = ${realized}; the position is now flat.`;
    case "flip":
      return `${verb} ${qty} against ${held(before.net_qty)} at ${price}: closed the ${side(before.net_qty)}, realizing ${gain} × ${formatQty(Math.abs(before.net_qty))} = ${realized}, and opened a ${formatQty(Math.abs(s.net_qty))} ${side(s.net_qty)} at ${avgAfter}.`;
  }
}

function positionAt(qty: number, avgTicks: Ticks, td: number): string {
  return qty === 0 ? "flat" : `${formatPosition(qty)} at average ${formatAverage(avgTicks, td)}`;
}

const COLUMNS: Column<Row>[] = [
  qtyColumn("n", "#", (r) => r.n, "The fill's place in the day, in the order clearing applied it"),
  timeColumn("ts", "Exchange time", (r) => r.ts_ns, "When the exchange printed the trade"),
  textColumn("side", "Side", (r) => r.side, "The gateway's side of the trade"),
  qtyColumn("qty", "Qty", (r) => r.quantity, "Shares in this fill"),
  tickColumn("price", "Price", (r) => r.price_ticks, { title: "The fill price" }),
  textColumn("kind", "What it did", (r) => r.kind, "open from flat, add to the same side, reduce part of it, close to flat, flip through flat to the other side"),
  positionColumn("position", "Position after", (r) => r.net_qty, "The position after this fill"),
  tickColumn("avg", "Avg cost after", (r) => r.avg_cost_ticks, { extra: 2, title: "The average cost after this fill" }),
  tickColumn("realized", "Realized", (r) => r.realized_delta_ticks, { pnl: true, title: "P&L this fill locked in" }),
  tickColumn("realized_day", "Realized today", (r) => r.realized_day_ticks, { pnl: true, title: "P&L locked in so far that day" }),
];

const W = 480;
const BAND = 56;
const PAD = 10;

/** Two bands over the fills: the position (top), and the fill prices with the average cost (bottom). */
function ReplayChart({ start, steps, selected, onSelect }: { start: Start; steps: ReplayStepT[]; selected: number | null; onSelect: (n: number) => void }) {
  const x = (i: number) => PAD + (i / Math.max(steps.length, 1)) * (W - 2 * PAD);
  // Each step in the display currency, so a precision change does not jump.
  const qtys = [start.net_qty, ...steps.map((s) => s.net_qty)];
  const qMax = Math.max(1, ...qtys.map(Math.abs));
  const yq = (q: number) => PAD + BAND / 2 - (q / qMax) * (BAND / 2 - 2);
  const prices = steps.flatMap((s) => (s.net_qty === 0 ? [s.price] : [s.price, s.avg_cost]));
  const lo = Math.min(...prices);
  const hi = Math.max(...prices);
  const span = hi - lo || 1;
  const top = PAD * 2 + BAND;
  const yp = (p: number) => top + BAND - 2 - ((p - lo) / span) * (BAND - 4);
  const path = qtys.map((q, i) => (i === 0 ? `M${x(0)},${yq(q)}` : `H${x(i)} V${yq(q)}`)).join(" ") + ` H${W - PAD}`;
  return (
    <svg aria-hidden="true" width={W} height={top + BAND + PAD} className="my-2 block">
      <text x={PAD} y={PAD - 1} fontSize={9} fill="rgb(var(--fg-dim))">position (0 at the dashed line)</text>
      <line x1={PAD} x2={W - PAD} y1={yq(0)} y2={yq(0)} stroke="rgb(var(--line))" strokeDasharray="3 3" />
      <path d={path} fill="none" stroke="rgb(var(--accent))" strokeWidth={2} />
      <text x={PAD} y={top - 3} fontSize={9} fill="rgb(var(--fg-dim))">fill price (dots) and average cost (line)</text>
      {steps.map((s, i) =>
        s.net_qty === 0 ? null : (
          <line key={`avg-${i}`} x1={x(i + 1)} x2={i + 1 < steps.length ? x(i + 2) : W - PAD} y1={yp(s.avg_cost)} y2={yp(s.avg_cost)} stroke="rgb(var(--fg-dim))" strokeWidth={2} />
        ),
      )}
      {selected !== null && <line x1={x(selected)} x2={x(selected)} y1={PAD} y2={top + BAND} stroke="rgb(var(--halt))" />}
      {steps.map((s, i) => (
        <circle
          key={`p-${i}`}
          data-replay-point
          cx={x(i + 1)}
          cy={yp(s.price)}
          r={selected === i + 1 ? 5 : 3.5}
          fill={s.side === "BUY" ? "rgb(var(--bid))" : "rgb(var(--ask))"}
          className="cursor-pointer"
          onClick={() => onSelect(i + 1)}
        />
      ))}
    </svg>
  );
}

function Replay({ r }: { r: PositionReplayT }) {
  const [selected, setSelected] = useState<number | null>(null);
  if (r.trade_date === null) return <p>{`Clearing has no trades of this gateway in ${r.symbol}.`}</p>;
  const startText = `At the start of ${r.trade_date}: ${positionAt(r.start.net_qty, r.start.avg_cost_ticks, r.start.tick_decimals)}.`;
  if (!r.trades_retained) {
    return <p>{`${startText} The raw trades of ${r.trade_date} are no longer kept, so the day cannot be replayed.`}</p>;
  }
  if (r.steps.length === 0) return <p>{`${startText} No fills on ${r.trade_date}.`}</p>;
  const rows: Row[] = r.steps.map((s, i) => ({ ...s, n: i + 1 }));
  const last = r.steps[r.steps.length - 1]!;
  const before = (n: number): Before => (n === 1 ? r.start : r.steps[n - 2]!);
  return (
    <>
      <p>{startText}</p>
      {r.has_more && (
        <p className="text-halt">{`Only the first ${formatQty(REPLAY_MAX_STEPS)} fills are shown, so the replay is not checked against the ledger.`}</p>
      )}
      {r.matches_daily_row === false && r.daily_row && (
        <p role="alert" className="rounded border border-ask/50 bg-ask/10 p-2">
          {`The replay ends at ${positionAt(last.net_qty, last.avg_cost_ticks, last.tick_decimals)}, but clearing's daily row holds ${positionAt(r.daily_row.end_net_qty, r.daily_row.end_avg_cost_ticks, r.daily_row.tick_decimals)}: report this.`}
        </p>
      )}
      {r.matches_position === false && (
        <p role="alert" className="rounded border border-ask/50 bg-ask/10 p-2">
          The replay does not end on clearing&apos;s stored position: report this.
        </p>
      )}
      <ReplayChart start={r.start} steps={r.steps} selected={selected} onSelect={setSelected} />
      <p role="status" aria-live="polite" className="my-1 rounded bg-raised/60 p-2">
        {selected === null
          ? "Select a fill in the table or the chart to see what it did."
          : stepSentence(r.steps[selected - 1]!, before(selected))}
      </p>
      <DataTable
        caption={`Fills of ${r.symbol} on ${r.trade_date}`}
        columns={COLUMNS}
        rows={rows}
        rowKey={(row) => String(row.n)}
        sortable={false}
        onRowClick={(row) => setSelected(row.n)}
        selectedKey={selected === null ? undefined : String(selected)}
      />
    </>
  );
}

/** The replay of `gateway`'s `symbol` on `date` (default: the latest day it traded). */
export function PositionReplayView({ gateway, symbol, date }: { gateway: string; symbol: string; date?: string }) {
  const replay = usePositionReplay({ gateway, symbol, date });
  return (
    <section aria-label={`How ${symbol} was built`} className="mt-2 border-t border-line pt-2 text-xs">
      <QueryState query={replay} skeletonColumns={5}>
        {(r) => <Replay r={r} />}
      </QueryState>
    </section>
  );
}

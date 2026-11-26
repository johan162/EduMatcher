/**
 * Follow one trade (CG31, Explain mode), opened from a trade row: what
 * happened to it, stage by stage, from the replies the GUI already has.
 *
 * 1. Matched by the engine (exchange time, the match type).
 * 2. Received by clearing (its ingest time, and how much later).
 * 3. Each visible side's position change: the trade's step in that side's
 *    replay of the day (CG28), written out as the replay writes it.
 * 4. The day's daily row for that side, from the same replay reply.
 * 5. pm-eod's settlement of the day for that side, or why there is none.
 *
 * An ADMIN sees both sides; a participant only its own (the server sends
 * the counterparty as null, and nothing here asks for it).
 */
import type { ReactNode } from "react";
import { usePositionReplay, useSettlements } from "@/api/queries";
import type { TradeRowT } from "@/api/schemas";
import { Time } from "@/components/shared/Time";
import { useAuthStore } from "@/store/useAuthStore";
import { formatMinor, formatPnlTicks, formatQty, formatTicks, type Minor } from "@/lib/money";
import { positionAt, stepSentence } from "./PositionReplayView";

function matchWords(matchType: string | null): string {
  if (matchType === null || matchType === "CONTINUOUS") return "in continuous trading";
  return `in the ${matchType.toLowerCase().replace(/_/g, " ")}`;
}

function delay(fromNs: number, toNs: number): string {
  const ms = (toNs - fromNs) / 1e6;
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(2)} s`;
}

function Stage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <li className="mb-1.5">
      <span className="font-semibold">{title}. </span>
      {children}
    </li>
  );
}

/** Stages 3-5 for one side of the trade. */
function Side({ trade, gateway, side, self }: { trade: TradeRowT; gateway: string; side: "BUY" | "SELL"; self: boolean }) {
  const who = self ? "you" : gateway;
  const replay = usePositionReplay({ gateway, symbol: trade.symbol, date: trade.trade_date });
  const settlements = useSettlements({ gateway, date: trade.trade_date });
  const r = replay.data;
  const index = r ? r.steps.findIndex((s) => s.trade_id === trade.trade_id && s.side === side) : -1;
  const step = r && index >= 0 ? r.steps[index]! : null;
  const before = r && index > 0 ? r.steps[index - 1]! : r?.start;

  let position = "…";
  if (replay.isError) position = "The replay of the day could not be read.";
  else if (r && step && before) position = stepSentence(step, before);
  else if (r) position = "This fill is beyond the replay's first 5,000 fills of the day.";

  let row = "…";
  if (r?.daily_row) {
    const d = r.daily_row;
    row = `At the end of ${trade.trade_date}, clearing's daily row for ${who} in ${trade.symbol} holds ${positionAt(d.end_net_qty, d.end_avg_cost_ticks, d.tick_decimals)}, with ${formatPnlTicks(d.realized_pnl_ticks, d.tick_decimals)} realized that day.`;
  } else if (r) row = `Clearing has no daily row for ${who} in ${trade.symbol} on ${trade.trade_date} yet.`;

  let settled = "…";
  const s = settlements.data;
  if (settlements.isError) settled = "pm-eod's settlements could not be read.";
  else if (s) {
    const mine = s.settlements.find((x) => x.account === gateway && x.trade_date === trade.trade_date);
    const run = s.runs.find((x) => x.trade_date === trade.trade_date);
    if (mine) {
      const amount = mine.amount_minor;
      const abs = formatMinor(Math.abs(amount) as Minor);
      settled =
        amount > 0
          ? `pm-eod settled ${trade.trade_date}: the exchange owes ${who} ${abs}.`
          : amount < 0
            ? `pm-eod settled ${trade.trade_date}: ${self ? "you owe" : `${gateway} owes`} the exchange ${abs}.`
            : `pm-eod settled ${trade.trade_date}: nothing moved for ${who}.`;
    } else if (run && run.status !== "ok") {
      settled = `pm-eod's run for ${trade.trade_date} ${run.status}: the day is not settled.`;
    } else if (run) {
      settled = `pm-eod settled ${trade.trade_date}, with nothing for ${who}.`;
    } else {
      settled = `Not settled yet: pm-eod settles ${trade.trade_date} after the close.`;
    }
  }

  return (
    <>
      <Stage title={`Position of ${who}`}>{position}</Stage>
      <Stage title={`Daily row of ${who}`}>{row}</Stage>
      <Stage title={`Settlement of ${who}`}>
        {settled}{" "}
        <span className="text-fg-dim">
          A settlement moves the day&apos;s change in P&amp;L of all its positions, not this trade&apos;s value.
        </span>
      </Stage>
    </>
  );
}

export function TradeTimeline({ trade }: { trade: TradeRowT }) {
  const admin = useAuthStore((s) => s.role === "ADMIN");
  const qty = formatQty(trade.quantity);
  const price = formatTicks(trade.price_ticks, trade.tick_decimals);
  const how = matchWords(trade.match_type);
  const buyer = trade.buy_gateway_id;
  const seller = trade.sell_gateway_id;
  const matched = admin
    ? `${buyer ?? "?"} bought ${qty} ${trade.symbol} from ${seller ?? "?"} at ${price} ${how}.`
    : buyer !== null
      ? `you bought ${qty} ${trade.symbol} at ${price} ${how}. The seller is not shown to you.`
      : `you sold ${qty} ${trade.symbol} at ${price} ${how}. The buyer is not shown to you.`;
  const sides: { gateway: string; side: "BUY" | "SELL" }[] = [];
  if (buyer !== null) sides.push({ gateway: buyer, side: "BUY" });
  if (seller !== null) sides.push({ gateway: seller, side: "SELL" });
  return (
    <section aria-label={`Trade ${trade.trade_id}, step by step`} data-explain className="text-xs">
      <ol className="list-decimal pl-5">
        <Stage title="Matched by the engine">
          <Time ns={trade.ts_ns} />: {matched}
        </Stage>
        <Stage title="Received by clearing">
          {`Received by clearing ${delay(trade.ts_ns, trade.ingest_ts_ns)} later`} (<Time ns={trade.ingest_ts_ns} />), and
          written to the ledger with its next flush, within 5 s.
        </Stage>
        {sides.map((s) => (
          <Side key={s.side} trade={trade} gateway={s.gateway} side={s.side} self={!admin} />
        ))}
      </ol>
    </section>
  );
}

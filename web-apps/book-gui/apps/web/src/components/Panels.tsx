/**
 * BIDS / ASKS / TRADES (design §9.4).
 *
 * The two ladders mirror each other about the centre divider, as pm-viewer's
 * do: bids read `Ord Qty Price Depth`, asks `Depth Price Qty Ord`, and each
 * depth bar grows outward from the centre. Rows are padded to the shared
 * capacity so the three panels always have equal height.
 */

import clsx from "clsx";
import type { Level, TapeTrade } from "@edumatcher/book-types";
import { price, qty, tradeTime } from "../lib/format.js";
import { barPct, maxQty, tapeRows } from "../lib/ladder.js";
import type { Trend } from "../lib/stats.js";

/** Every row is exactly this tall, so the fit-to-screen measurement is exact. */
export const ROW_PX = 22;

const TREND_CLASS: Record<Trend, string> = { up: "text-up", down: "text-down", flat: "text-fg-subtle" };

const rowClass = (i: number, zebra: boolean) =>
  clsx("grid items-center px-2", zebra && i % 2 === 1 && "bg-bg-subtle");

function Panel({
  title,
  titleClass,
  columns,
  header,
  children,
  bodyRef,
}: {
  title: string;
  titleClass: string;
  columns: string;
  /** Column labels; a leading `<` aligns that label left. */
  header: string[];
  children: React.ReactNode;
  bodyRef?: React.Ref<HTMLDivElement>;
}) {
  return (
    <section aria-label={title} className="flex min-h-0 flex-col rounded border border-border bg-bg-raised">
      <h2 className={clsx("py-1 text-center text-xs font-bold tracking-[0.2em]", titleClass)}>{title}</h2>
      <div
        className={clsx(
          "grid border-b border-border px-2 pb-1 text-[11px] font-semibold uppercase",
          titleClass,
        )}
        style={{ gridTemplateColumns: columns }}
      >
        {header.map((h) => (
          <span key={h} className={h.startsWith("<") ? "text-left" : "text-right"}>
            {h.replace("<", "")}
          </span>
        ))}
      </div>
      <div ref={bodyRef} className="min-h-0 flex-1 overflow-hidden font-mono tabular text-xs">
        {children}
      </div>
    </section>
  );
}

const BID_COLS = "1fr 1.5fr 1.5fr 5rem";
const ASK_COLS = "5rem 1.5fr 1.5fr 1fr";

export function SideLadder({
  side,
  levels,
  capacity,
  decimals,
  zebra,
  bodyRef,
}: {
  side: "bid" | "ask";
  levels: Level[];
  capacity: number;
  decimals: number;
  zebra: boolean;
  bodyRef?: React.Ref<HTMLDivElement>;
}) {
  const isBid = side === "bid";
  const shown = levels.slice(0, capacity);
  const max = maxQty(levels, capacity);
  const colour = isBid ? "text-up" : "text-down";

  const bar = (lvl: Level) => (
    <span className={clsx("flex h-3", isBid ? "justify-end" : "justify-start")}>
      <span
        data-testid="depth-bar"
        className={clsx("h-full rounded-sm", isBid ? "bg-up" : "bg-down")}
        style={{ width: `${barPct(lvl.qty, max)}%` }}
      />
    </span>
  );

  return (
    <Panel
      title={isBid ? "BIDS" : "ASKS"}
      titleClass={colour}
      columns={isBid ? BID_COLS : ASK_COLS}
      header={isBid ? ["Ord", "Qty", "Price", "Depth"] : ["<Depth", "<Price", "<Qty", "<Ord"]}
      bodyRef={bodyRef}
    >
      {Array.from({ length: capacity }, (_, i) => {
        const lvl = shown[i];
        const style = { gridTemplateColumns: isBid ? BID_COLS : ASK_COLS, height: ROW_PX };
        if (!lvl) return <div key={i} className={rowClass(i, zebra)} style={style} />;
        return (
          <div
            key={i}
            role="row"
            data-side={side}
            className={clsx(rowClass(i, zebra), "gap-2")}
            style={style}
          >
            {isBid ? (
              <>
                <span className="text-right text-fg">{lvl.count}</span>
                <span className="text-right text-fg">{qty(lvl.qty)}</span>
                <span className={clsx("text-right font-semibold", colour)}>{price(lvl.price, decimals)}</span>
                {bar(lvl)}
              </>
            ) : (
              <>
                {bar(lvl)}
                <span className={clsx("text-left font-semibold", colour)}>{price(lvl.price, decimals)}</span>
                <span className="text-left text-fg">{qty(lvl.qty)}</span>
                <span className="text-left text-fg">{lvl.count}</span>
              </>
            )}
          </div>
        );
      })}
    </Panel>
  );
}

const TRADE_COLS = "1.6fr 1fr 1fr";

export function TradesPanel({
  tape,
  capacity,
  decimals,
  timeZone,
  zebra,
}: {
  tape: TapeTrade[];
  capacity: number;
  decimals: number;
  timeZone: string;
  zebra: boolean;
}) {
  const rows = tapeRows(tape, capacity);
  return (
    <Panel title="TRADES" titleClass="text-accent" columns={TRADE_COLS} header={["<Time", "Price", "Qty"]}>
      {Array.from({ length: capacity }, (_, i) => {
        const row = rows[i];
        const style = { gridTemplateColumns: TRADE_COLS, height: ROW_PX };
        if (!row) return <div key={i} className={rowClass(i, zebra)} style={style} />;
        return (
          <div
            key={row.trade.id}
            role="row"
            data-trend={row.trend}
            className={rowClass(i, zebra)}
            style={style}
          >
            <span className="text-fg-subtle">{tradeTime(row.trade.tsMs, timeZone)}</span>
            <span className={clsx("text-right", TREND_CLASS[row.trend])}>
              {price(row.trade.px, decimals)}
            </span>
            <span className={clsx("text-right", TREND_CLASS[row.trend])}>{qty(row.trade.qty)}</span>
          </div>
        );
      })}
    </Panel>
  );
}

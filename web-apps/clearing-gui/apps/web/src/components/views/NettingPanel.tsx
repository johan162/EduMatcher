/**
 * Netting (CG27, Explain mode): the latest trading day's trades against the
 * one amount each gateway is left with, from `GET /clearing/netting`.
 *
 * Venue (ADMIN Overview): how many trades, worth how much, net to how few
 * amounts. One gateway (a participant's Settlement, an ADMIN's drawer): what
 * it bought and sold, and what it pays or receives. Every panel says that
 * this is cash netting, not pm-eod's settlement, which moves P&L: the two are
 * easy to confuse, and the settlement screen is where this panel stands.
 */
import { DataTable, type Column } from "@/components/shared/DataTable";
import { ValueBars } from "@/components/shared/Bars";
import { useExplain } from "@/components/shared/Explain";
import { QueryState } from "@/components/shared/QueryState";
import { Panel } from "@/components/shared/Ui";
import { useNetting } from "@/api/queries";
import type { NettingGatewayRowT, NettingT } from "@/api/schemas";
import { formatCurrency } from "@/lib/money";
import { qtyColumn, textColumn } from "./columns";

function plural(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

/** A net amount as what happens to it: "pay 27,015.00", "receive 1.00". */
export function netWords(net: number): string {
  const shown = Number(net.toFixed(2));
  if (shown > 0) return `pay ${formatCurrency(net)}`;
  if (shown < 0) return `receive ${formatCurrency(-net)}`;
  return formatCurrency(0);
}

function money(id: string, header: string, value: (r: NettingGatewayRowT) => number, title: string): Column<NettingGatewayRowT> {
  return { id, header, title, align: "right", cell: (r) => formatCurrency(value(r)), sortValue: value };
}

const COLUMNS: Column<NettingGatewayRowT>[] = [
  textColumn("gateway", "Gateway", (r) => r.gateway_id, "The participant gateway"),
  money("bought", "Bought", (r) => r.bought_value, "Value of the day's buys, every symbol, display currency"),
  money("sold", "Sold", (r) => r.sold_value, "Value of the day's sells, every symbol, display currency"),
  {
    id: "net",
    header: "Net",
    title: "Bought − sold: what the gateway pays for the day's trades, or receives",
    align: "right",
    cell: (r) => netWords(r.net_amount),
    sortValue: (r) => r.net_amount,
  },
  qtyColumn("trades", "Trades", (r) => r.trade_count, "The day's trades it was a side of; a dash once the raw trades are pruned"),
];

function venueSentence(n: NettingT): string {
  if (n.trade_date === null) return "No trading day yet.";
  if (n.gateways.length === 0) return `On ${n.trade_date} nothing traded.`;
  const trades = n.trade_count === null ? "the day's trades" : plural(n.trade_count, "trade");
  return `On ${n.trade_date}, ${trades} worth ${formatCurrency(n.gross_value)} net to ${plural(n.payment_count, "amount")}: the gateways that bought more than they sold pay ${formatCurrency(n.net_paid)} in all, and those that sold more receive ${formatCurrency(n.net_received)}.`;
}

function gatewaySentence(n: NettingT, self: boolean): string {
  const who = self ? "you" : "this gateway";
  if (n.trade_date === null) return "No trading day yet.";
  const row = n.gateways[0];
  if (!row) return `On ${n.trade_date} ${who} did not trade.`;
  const shown = Number(row.net_amount.toFixed(2));
  const left =
    shown > 0
      ? `${self ? "you pay" : "it pays"} ${formatCurrency(row.net_amount)}`
      : shown < 0
        ? `${self ? "you receive" : "it receives"} ${formatCurrency(-row.net_amount)}`
        : "the two balance, so nothing is left to pay";
  return `On ${n.trade_date} ${who} bought ${formatCurrency(row.bought_value)} and sold ${formatCurrency(row.sold_value)}: ${left}.`;
}

/** `gateway` undefined: the venue for ADMIN (`venue`), or the caller's own. */
export function NettingPanel({ gateway, venue = false }: { gateway?: string; venue?: boolean }) {
  const explain = useExplain();
  const netting = useNetting(gateway, explain);
  if (!explain) return null;
  const self = !venue && !gateway;
  return (
    <Panel title="Netting">
      <QueryState query={netting} skeletonColumns={4}>
        {(n) => {
          const row = n.gateways[0];
          return (
            <div className="flex flex-col gap-1 text-xs">
              <p>{venue ? venueSentence(n) : gatewaySentence(n, self)}</p>
              {!n.trades_retained && (
                <p className="text-fg-dim">Raw trades for this day are no longer kept, so they are not counted.</p>
              )}
              <p className="text-fg-dim">
                {venue
                  ? "This is the cash the day's trades net to: each gateway's buys are set against its sells, so thousands of trades leave one amount per gateway. It is not pm-eod's settlement, which moves each gateway's change in P&L."
                  : `This is the cash ${self ? "your" : "its"} trades net to: buys set against sells. It is not pm-eod's settlement below, which moves the day's change in P&L.`}
              </p>
              {venue ? (
                <ValueBars
                  rows={[
                    { key: "gross", label: "Traded value", value: n.gross_value, tone: "bg-accent/60" },
                    { key: "paid", label: "Left to pay, net", value: n.net_paid, tone: "bg-halt/70" },
                  ]}
                />
              ) : (
                row && (
                  <ValueBars
                    rows={[
                      { key: "bought", label: "Bought", value: row.bought_value, tone: "bg-accent/60" },
                      { key: "sold", label: "Sold", value: row.sold_value, tone: "bg-accent/60" },
                      { key: "net", label: "Left, net", value: row.net_amount, tone: "bg-halt/70" },
                    ]}
                  />
                )
              )}
              {n.gateways.length > 0 && (
                <DataTable caption="Netting by gateway" columns={COLUMNS} rows={n.gateways} rowKey={(r) => r.gateway_id} />
              )}
            </div>
          );
        }}
      </QueryState>
    </Panel>
  );
}

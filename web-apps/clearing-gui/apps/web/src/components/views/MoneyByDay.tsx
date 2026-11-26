/**
 * Money in and out by day (CG27, Explain mode): what a gateway bought (money
 * out) and sold (money in) each day, every symbol converted to display
 * currency, and the net it is left to pay or receive. Summed from the daily
 * rows the History screen already shows, so it follows their filters.
 */
import { DataTable, type Column } from "@/components/shared/DataTable";
import { DivergingBars } from "@/components/shared/Bars";
import { useExplain } from "@/components/shared/Explain";
import { Panel } from "@/components/shared/Ui";
import type { DailyRowT } from "@/api/schemas";
import { formatCurrency } from "@/lib/money";
import { textColumn } from "./columns";
import { netWords } from "./NettingPanel";

interface DayMoney {
  date: string;
  bought: number;
  sold: number;
  net: number;
}

/** One total per day, newest first; every row's display values, never ticks. */
export function moneyByDay(rows: DailyRowT[]): DayMoney[] {
  const byDate = new Map<string, DayMoney>();
  for (const r of rows) {
    const day = byDate.get(r.trade_date) ?? { date: r.trade_date, bought: 0, sold: 0, net: 0 };
    day.bought += r.buy_notional;
    day.sold += r.sell_notional;
    day.net += r.net_amount;
    byDate.set(r.trade_date, day);
  }
  return [...byDate.values()].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
}

function money(id: string, header: string, value: (r: DayMoney) => number, title: string): Column<DayMoney> {
  return { id, header, title, align: "right", cell: (r) => formatCurrency(value(r)), sortValue: value };
}

const COLUMNS: Column<DayMoney>[] = [
  textColumn("date", "Date", (r) => r.date, "The trading day"),
  money("bought", "Bought (money out)", (r) => r.bought, "Value of the day's buys, every symbol, display currency"),
  money("sold", "Sold (money in)", (r) => r.sold, "Value of the day's sells, every symbol, display currency"),
  {
    id: "net",
    header: "Net",
    title: "Bought − sold: what is left to pay, or to receive",
    align: "right",
    cell: (r) => netWords(r.net),
    sortValue: (r) => r.net,
  },
];

export function MoneyByDay({ rows }: { rows: DailyRowT[] }) {
  const explain = useExplain();
  if (!explain) return null;
  const days = moneyByDay(rows);
  return (
    <Panel title="Money in and out by day">
      <p className="text-xs">
        A buy is money out and a sell is money in; what is left after setting one against the other is the net
        to pay or receive. This is cash, not P&amp;L: buying shares spends money without making a loss.
      </p>
      <DivergingBars
        leftLabel="sold: money in"
        rightLabel="bought: money out"
        leftTone="bg-accent/60"
        rightTone="bg-fg-dim/60"
        rows={days.slice(0, 20).map((d) => ({ key: d.date, label: d.date, left: d.sold, right: d.bought }))}
      />
      <DataTable caption="Money by day" columns={COLUMNS} rows={days} rowKey={(r) => r.date} />
    </Panel>
  );
}

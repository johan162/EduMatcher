/**
 * The close-to-close line. Loaded lazily (HistoryView), so the chart library
 * reaches the browser only on a history screen. A fixed size keeps it
 * rendering where a container has no measurable width (tests, print).
 * The same numbers are in the "Closes by day" table, for screen readers.
 */
import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import { formatCurrency } from "@/lib/money";
import type { CloseTotal } from "./HistoryView";

export default function CloseChart({ totals }: { totals: CloseTotal[] }) {
  return (
    <figure aria-label="Close-to-close cumulative P&L chart" className="m-0">
      <LineChart width={720} height={220} data={totals} margin={{ top: 8, right: 16, bottom: 8, left: 16 }}>
        <CartesianGrid stroke="rgb(var(--line))" strokeDasharray="3 3" />
        <XAxis dataKey="date" stroke="rgb(var(--fg-dim))" fontSize={11} />
        <YAxis stroke="rgb(var(--fg-dim))" fontSize={11} tickFormatter={(v: number) => formatCurrency(v)} />
        <Tooltip formatter={(v: number) => formatCurrency(v)} />
        <Line type="linear" dataKey="pnl" name="Cumulative P&L" stroke="rgb(var(--accent))" dot isAnimationActive={false} />
      </LineChart>
    </figure>
  );
}

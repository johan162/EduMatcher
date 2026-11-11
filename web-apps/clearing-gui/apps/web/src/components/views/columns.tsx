/**
 * Column builders for the clearing tables.
 *
 * `tickColumn` is the only way a money cell is rendered from a row: it
 * formats the row's `*_ticks` value with that row's own `tick_decimals`, and
 * sorts by the display-currency value, so rows of symbols with different
 * precision order correctly. Cross-row sums never happen in a column.
 */
import type { Column } from "@/components/shared/DataTable";
import { formatQty, formatTicks, signClass, ticksToDisplay, type Ticks } from "@/lib/money";
import { formatNs } from "@/lib/time";

interface TickOptions {
  /** Extra decimals beyond the symbol's precision (averages). */
  extra?: number;
  /** Colour by sign (P&L). */
  signed?: boolean;
  title?: string;
}

export function tickColumn<R extends { tick_decimals: number }>(
  id: string,
  header: string,
  value: (row: R) => Ticks | null,
  { extra = 0, signed = false, title }: TickOptions = {},
): Column<R> {
  return {
    id,
    header,
    title,
    align: "right",
    cell: (row) => {
      const v = value(row);
      return <span className={signed ? signClass(v) : ""}>{formatTicks(v, row.tick_decimals, extra)}</span>;
    },
    sortValue: (row) => {
      const v = value(row);
      return v === null ? null : ticksToDisplay(v, row.tick_decimals);
    },
  };
}

export function qtyColumn<R>(id: string, header: string, value: (row: R) => number | null, title?: string): Column<R> {
  return {
    id,
    header,
    title,
    align: "right",
    cell: (row) => formatQty(value(row)),
    sortValue: value,
  };
}

export function textColumn<R>(id: string, header: string, value: (row: R) => string | null, title?: string): Column<R> {
  return {
    id,
    header,
    title,
    cell: (row) => value(row) ?? "—",
    sortValue: value,
  };
}

/** An epoch-nanosecond time, shown in UTC. */
export function timeColumn<R>(id: string, header: string, value: (row: R) => number | null, title?: string): Column<R> {
  return {
    id,
    header,
    title,
    cell: (row) => <span className="num">{formatNs(value(row))}</span>,
    sortValue: value,
  };
}

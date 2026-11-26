/**
 * Column builders for the clearing tables.
 *
 * `tickColumn` is the only way a money cell is rendered from a row: it
 * formats the row's `*_ticks` value with that row's own `tick_decimals`, and
 * sorts by the display-currency value, so rows of symbols with different
 * precision order correctly. Cross-row sums never happen in a column.
 */
import type { Column } from "@/components/shared/DataTable";
import { formatPnlTicks, formatPosition, formatQty, formatTicks, signClass, ticksToDisplay, type Ticks } from "@/lib/money";
import { Time } from "@/components/shared/Time";
import { GatewayId } from "./GatewayId";

interface TickOptions {
  /** Extra decimals beyond the symbol's precision (averages). */
  extra?: number;
  /** Colour by sign. */
  signed?: boolean;
  /** A P&L amount: coloured, and "gain" / "loss" beside it (CG25). */
  pnl?: boolean;
  /** The header's tooltip. */
  title: string;
}

export function tickColumn<R extends { tick_decimals: number }>(
  id: string,
  header: string,
  value: (row: R) => Ticks | null,
  { extra = 0, signed = false, pnl = false, title }: TickOptions,
): Column<R> {
  return {
    id,
    header,
    title,
    align: "right",
    cell: (row) => {
      const v = value(row);
      const text = pnl ? formatPnlTicks(v, row.tick_decimals) : formatTicks(v, row.tick_decimals, extra);
      return <span className={signed || pnl ? signClass(v) : ""}>{text}</span>;
    },
    sortValue: (row) => {
      const v = value(row);
      return v === null ? null : ticksToDisplay(v, row.tick_decimals);
    },
  };
}

export function qtyColumn<R>(id: string, header: string, value: (row: R) => number | null, title: string): Column<R> {
  return {
    id,
    header,
    title,
    align: "right",
    cell: (row) => formatQty(value(row)),
    sortValue: value,
  };
}

/** A signed position, with "long" / "short" / "flat" beside it (CG25). */
export function positionColumn<R>(id: string, header: string, value: (row: R) => number | null, title: string): Column<R> {
  return { ...qtyColumn(id, header, value, title), cell: (row) => formatPosition(value(row)) };
}

export function textColumn<R>(id: string, header: string, value: (row: R) => string | null, title: string): Column<R> {
  return {
    id,
    header,
    title,
    cell: (row) => value(row) ?? "—",
    sortValue: value,
  };
}

/** A gateway id; for ADMIN a link that opens that participant's drawer. */
export function gatewayColumn<R>(id: string, header: string, value: (row: R) => string | null, title: string): Column<R> {
  return {
    id,
    header,
    title,
    cell: (row) => <GatewayId id={value(row)} />,
    sortValue: value,
  };
}

/** An epoch-nanosecond time, shown on the venue's clock. */
export function timeColumn<R>(id: string, header: string, value: (row: R) => number | null, title: string): Column<R> {
  return {
    id,
    header,
    title,
    cell: (row) => <Time ns={value(row)} />,
    sortValue: value,
  };
}

import type { SessionEventRowT } from "@/api/schemas";

/** One line for an event's payload: the phase change, the gap, the EOD marks. */
export function eventDetail(row: SessionEventRowT): string {
  if (row.phase) return `${row.phase.prev_state ?? "—"} → ${row.phase.state}`;
  if (row.gap) {
    const g = row.gap;
    return `${g.missing_trades ?? "?"} missing (ids ${g.last_seq ?? "?"} → ${g.next_seq ?? "?"})`;
  }
  if (row.eod) return `${row.eod.symbols_count} symbol(s) marked`;
  return "";
}

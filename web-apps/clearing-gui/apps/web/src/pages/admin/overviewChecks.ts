/**
 * The Overview's "is anything wrong?" rules (CG23), as plain functions of
 * what the API reports, so each rule is stated and tested in one place.
 */
import type { ParticipantRowT, SummaryT } from "@/api/schemas";

/** How long continuous trading may go without a clearing write before the Overview says so. */
export const STALE_WRITE_MS = 30_000;

/** At most this many rows in each "needs attention" table. */
export const ATTENTION_ROWS = 5;

/**
 * Seconds since clearing last wrote, when that is worth a warning: only in
 * CONTINUOUS, the one phase in which fills arrive as they happen (pre-open
 * and auctions do not fill until the uncross; CLOSED does not fill at all).
 * `null` means no warning. A quiet market also writes nothing, so the
 * warning names both causes rather than claiming a fault.
 */
export function staleWriteSeconds(phase: string | null, lastFlushNs: number | null, nowMs: number): number | null {
  if (phase !== "CONTINUOUS" || lastFlushNs === null) return null;
  const ageMs = nowMs - lastFlushNs / 1_000_000;
  return ageMs > STALE_WRITE_MS ? Math.floor(ageMs / 1000) : null;
}

/**
 * What is wrong with end of day, in words, or `null`:
 * - pm-eod's last run did not end `ok`;
 * - the latest trading day is CLOSED and pm-eod has not run for it. While
 *   the market is open, today not being settled is normal.
 */
export function eodProblem(summary: SummaryT, phase: string | null): string | null {
  if (!summary.eod_db_available) return null; // the EOD tile already says the ledger is unavailable
  const run = summary.last_eod_run;
  if (run && run.status !== "ok") {
    return `The last EOD run, for ${run.trade_date}, ended ${run.status}: settlement for that day may be missing. See EOD Settlement.`;
  }
  const day = summary.session_date;
  if (phase === "CLOSED" && day && (!run || run.trade_date < day)) {
    return `Trading day ${day} is closed but not settled: pm-eod has not run for it yet.`;
  }
  return null;
}

/** The participants at a loss, worst first, at most `ATTENTION_ROWS`. */
export function largestLosses(rows: ParticipantRowT[]): ParticipantRowT[] {
  return rows
    .filter((r) => r.total_pnl < 0)
    .sort((a, b) => a.total_pnl - b.total_pnl)
    .slice(0, ATTENTION_ROWS);
}

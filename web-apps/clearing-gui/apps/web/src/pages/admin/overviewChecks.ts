/**
 * The Overview's "is anything wrong?" rules (CG23), as plain functions of
 * what the API reports, so each rule is stated and tested in one place --
 * plus `useUnchangedForMs`, the browser-side clock the stale-write rule needs.
 */
import { useEffect, useRef, useState } from "react";
import type { ParticipantRowT, SummaryT } from "@/api/schemas";

/** How long continuous trading may go without a clearing write before the Overview says so. */
export const STALE_WRITE_MS = 30_000;

/** At most this many rows in each "needs attention" table. */
export const ATTENTION_ROWS = 5;

/** How often the Overview re-checks staleness, though no data changed. */
export const STALE_TICK_MS = 5_000;

/**
 * Seconds the last clearing write has stood unchanged, when that is worth a
 * warning: only in CONTINUOUS, the one phase in which fills arrive as they
 * happen (pre-open and auctions do not fill until the uncross; CLOSED does
 * not fill at all). `null` means no warning. A quiet market also writes
 * nothing, so the warning names both causes rather than claiming a fault.
 *
 * `unchangedMs` is measured on the browser's own clock (useUnchangedForMs),
 * never by comparing the server's timestamp with the browser's clock: a
 * classroom laptop whose clock is off would otherwise warn always, or never.
 */
export function staleWriteSeconds(phase: string | null, unchangedMs: number): number | null {
  if (phase !== "CONTINUOUS") return null;
  return unchangedMs > STALE_WRITE_MS ? Math.floor(unchangedMs / 1000) : null;
}

/**
 * How long `value` has stood unchanged, on this browser's clock, re-checked
 * every `STALE_TICK_MS`. The tick matters: a poll that returns the same data
 * does not re-render the page, and "the same data" is exactly the stale case.
 * Counting starts when the page shows the value, so a ledger already stale
 * when the page opens is reported after `STALE_WRITE_MS` of watching.
 */
export function useUnchangedForMs(value: unknown): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), STALE_TICK_MS);
    return () => clearInterval(timer);
  }, []);
  const seen = useRef<{ value: unknown; since: number } | null>(null);
  if (seen.current === null || seen.current.value !== value) seen.current = { value, since: Date.now() };
  return Math.max(0, now - seen.current.since);
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

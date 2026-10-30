import { ApiError } from "@/api/apiFetch.js";

/**
 * M3: `mutation.mutate(...)` looped over a single `useMutation` only ever
 * fires the *latest* call's `onSuccess`/`onError` (TanStack v5's
 * `MutationObserver` keeps one `#mutateOptions`, overwritten on every
 * `mutate()`) -- so a bulk cancel or Flatten All silently dropped feedback
 * for all but the last item (`ActiveOrdersPage.tsx`, `PositionPanel.tsx`).
 * `mutateAsync`'s own returned promise does not share that limitation --
 * fire every call, let them all settle, and summarize into one toast.
 */
export interface BulkOutcome {
  ok: number;
  pending: number;
  failed: number;
}

/**
 * True when the command reached the engine but its outcome did not come back
 * in time: `ENGINE_TIMEOUT` is the only error that means that. Any other
 * error -- `503 ENGINE_UNAVAILABLE` and `SYMBOLS_NOT_READY` included -- means
 * the gateway refused before anything was sent, so it is a failure, not
 * "awaiting confirmation" (WP-API15). A write that waits with `?wait=ack` does
 * not error on a late ack at all: it answers `202` with `ack_timeout: true`.
 */
export function isUnconfirmed(err: unknown): boolean {
  return err instanceof ApiError && err.code === "ENGINE_TIMEOUT";
}

/** An unconfirmed rejection (`isUnconfirmed`) counts as pending, not failed
 * -- matches the single-item cancel/flatten's own onError. */
export function summarizeSettled(results: PromiseSettledResult<unknown>[]): BulkOutcome {
  let ok = 0;
  let pending = 0;
  let failed = 0;
  for (const r of results) {
    if (r.status === "fulfilled") {
      ok++;
    } else if (isUnconfirmed(r.reason)) {
      pending++;
    } else {
      failed++;
    }
  }
  return { ok, pending, failed };
}

/** One summary line, e.g. describeBulkOutcome("Cancelled", "order", {ok:2,pending:0,failed:1})
 * -> "Cancelled 2 orders, 1 failed". */
export function describeBulkOutcome(verb: string, noun: string, outcome: BulkOutcome): string {
  const { ok, pending, failed } = outcome;
  const parts = [`${verb} ${ok} ${noun}${ok === 1 ? "" : "s"}`];
  if (pending) parts.push(`${pending} awaiting confirmation`);
  if (failed) parts.push(`${failed} failed`);
  return parts.join(", ");
}

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

/** A 503/ENGINE_TIMEOUT rejection means "submitted, awaiting confirmation",
 * not a failure -- matches the single-item cancel/flatten's own onError. */
export function summarizeSettled(results: PromiseSettledResult<unknown>[]): BulkOutcome {
  let ok = 0;
  let pending = 0;
  let failed = 0;
  for (const r of results) {
    if (r.status === "fulfilled") {
      ok++;
    } else if (
      r.reason instanceof ApiError &&
      (r.reason.status === 503 || r.reason.code === "ENGINE_TIMEOUT")
    ) {
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

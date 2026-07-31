/**
 * The previous-close map, shared by every view that quotes a change figure.
 *
 * One query key for all of them, so the Overview, Movers and Symbol Detail
 * cannot end up measuring the same symbol's move from different reference
 * prices — react-query dedupes the request, and more importantly dedupes the
 * answer.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "./api.js";
import { previousCloses } from "./prev-close.js";

/**
 * Calendar days of daily rows fetched to find the day before.
 *
 * Wide enough to clear a long weekend plus a public holiday, narrow enough
 * that the response stays a few hundred rows for a market of this size — the
 * ranged endpoint pages oldest-first, so a window big enough to hit the row
 * limit would truncate the newest dates, which are the only ones this needs.
 */
const WINDOW_DAYS = 10;

const DAY_MS = 86_400_000;

/** Start of the lookback window, as the `YYYY-MM-DD` the endpoint validates. */
export function windowStart(now = Date.now()): string {
  return new Date(now - WINDOW_DAYS * DAY_MS).toISOString().slice(0, 10);
}

/**
 * Symbol to previous close. Empty until the first response, which is the same
 * shape as a symbol having no previous close at all — callers already have to
 * handle that case, so there is no separate loading state to thread through.
 */
export function usePrevCloses(): Record<string, number> {
  const { data } = useQuery({
    queryKey: ["history", "daily", "window"],
    queryFn: () => api.dailyWindow(windowStart()),
    // Unlike the daily rollup this does not move during a session — yesterday
    // is settled. The slow refetch exists only to pick up the rollover, not to
    // keep a live figure fresh.
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
  });

  return useMemo(() => previousCloses(data?.daily ?? []), [data]);
}

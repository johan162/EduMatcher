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

export interface PrevCloses {
  closes: Record<string, number>;
  /**
   * True when the whole board has silently re-based onto the session open.
   *
   * That is the fetch failing *and* nothing having been cached — not merely
   * `isError`. Previous closes do not move during a session, so a refetch that
   * fails after one success leaves a map that is still correct and rows that
   * still mean what the header says; warning about those would put a notice
   * over figures that are fine, and a notice that cries wolf is one people
   * stop reading.
   *
   * Empty-and-failing is indistinguishable from empty-and-loading at the row
   * level, which is exactly why this cannot be inferred from `closes` alone.
   */
  unavailable: boolean;
}

/**
 * Symbol to previous close, plus whether the board has lost that baseline.
 *
 * The map is empty until the first response, which is the same shape as a
 * symbol having no previous close at all — callers already have to handle
 * that case at the row level. `unavailable` is the separate, market-wide
 * signal: every row falling back to the open baseline at once means the window
 * fetch is down, not that every symbol just happened to lack history.
 */
export function usePrevCloses(): PrevCloses {
  // One value for both the key and the request, so the two cannot describe
  // different days. A key without the date outlives the day it was fetched
  // for: a tab left open across midnight — which the unattended display does
  // by design — would keep serving the previous session's window, and
  // `previousCloses` reads "today" off the newest date in the data, so every
  // baseline on the board would silently slip a session. The refetch normally
  // corrects that within five minutes; if it fails at the rollover, nothing
  // ever does, and `unavailable` stays quiet because the map is populated.
  const from = windowStart();
  const { data, isError } = useQuery({
    queryKey: ["history", "daily", "window", from],
    queryFn: () => api.dailyWindow(from),
    // Unlike the daily rollup this does not move during a session — yesterday
    // is settled. The slow refetch exists only to pick up the rollover, not to
    // keep a live figure fresh.
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
  });

  const closes = useMemo(() => previousCloses(data?.daily ?? []), [data]);
  return { closes, unavailable: isError && Object.keys(closes).length === 0 };
}

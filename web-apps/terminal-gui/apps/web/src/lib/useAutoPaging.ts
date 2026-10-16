/**
 * Auto-advancing pager for the Overview grid (design §8.3).
 *
 * The timer restarts whenever the page changes, including when a viewer steps
 * manually — otherwise a manual step could land on a page that immediately
 * advances because the previous page's dwell had nearly elapsed.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { clampPage, pageCount, shouldAutoPage, wrapPage } from "./paging.js";

export interface AutoPaging {
  page: number;
  pages: number;
  paused: boolean;
  /** True while the dwell timer is actually running. */
  advancing: boolean;
  next: () => void;
  prev: () => void;
  setPaused: (paused: boolean) => void;
  togglePaused: () => void;
}

export function useAutoPaging(total: number, perPage: number, delaySec: number): AutoPaging {
  const [page, setPage] = useState(0);
  const [paused, setPaused] = useState(false);
  const pages = pageCount(total, perPage);

  // Row count can shrink under a viewer — a watchlist filter, a resize. Hold
  // them on the last real page rather than snapping back to the first.
  const safePage = clampPage(page, total, perPage);
  useEffect(() => {
    if (safePage !== page) setPage(safePage);
  }, [safePage, page]);

  const next = useCallback(
    () => setPage((current) => wrapPage(current + 1, total, perPage)),
    [total, perPage],
  );
  const prev = useCallback(
    () => setPage((current) => wrapPage(current - 1, total, perPage)),
    [total, perPage],
  );

  const advancing = !paused && shouldAutoPage(total, perPage) && delaySec > 0;

  // Keep the callback out of the effect's dependencies so the timer is not
  // torn down and rebuilt on every render, which would stop it ever firing.
  const advance = useRef(next);
  advance.current = next;

  useEffect(() => {
    if (!advancing) return;
    const timer = setInterval(() => advance.current(), delaySec * 1000);
    return () => clearInterval(timer);
  }, [advancing, delaySec, safePage]);

  return {
    page: safePage,
    pages,
    paused,
    advancing,
    next,
    prev,
    setPaused,
    togglePaused: () => setPaused((value) => !value),
  };
}


import { useEffect, useRef, useState } from "react";

/** Current time, re-rendered every `intervalMs`. */
export function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

/**
 * Rows of `rowHeightPx` that fit the measured element, so the panels fill
 * the screen as pm-viewer's do. Copied from terminal-gui's `useRowsPerPage`:
 * falls back to `fallback` until measured, or where `ResizeObserver` is
 * unavailable.
 */
export function useRowsPerPage(rowHeightPx: number, fallback = 15) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [rows, setRows] = useState(fallback);

  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;

    const measure = () => {
      const fits = Math.floor(element.clientHeight / rowHeightPx);
      setRows(Math.max(1, fits || fallback));
    };
    measure();

    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [rowHeightPx, fallback]);

  return { ref, rows };
}

/** Log Explorer (design §9): historical query + live tail, filter in the URL. */

import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import clsx from "clsx";
import type { LogFilter, LogLevel, LogRow } from "@edumatcher/log-types";
import { LOG_LEVELS } from "@edumatcher/log-types";
import { api } from "../lib/api.js";
import { useLiveStore } from "../store/useLiveStore.js";
import { SeverityBadge } from "../components/SeverityBadge.js";

const MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-04-09T07:00:14.469Z" -> "09 Apr 07:00:14.469" (UTC, no year). */
function formatRowTs(clientTs: string): string {
  const month = MONTH_ABBR[Number(clientTs.slice(5, 7)) - 1];
  const day = clientTs.slice(8, 10);
  return `${day} ${month} ${clientTs.slice(11, 23)}`;
}

function filterFromParams(params: URLSearchParams): LogFilter {
  return {
    minLevel: (params.get("minLevel") as LogLevel) || undefined,
    processes: params.get("processes")?.split(",").filter(Boolean),
    contains: params.get("contains") || undefined,
    exceptionsOnly: params.get("exceptionsOnly") === "true",
  };
}

function paramsFromFilter(filter: LogFilter): URLSearchParams {
  const params = new URLSearchParams();
  if (filter.minLevel) params.set("minLevel", filter.minLevel);
  if (filter.processes?.length) params.set("processes", filter.processes.join(","));
  if (filter.contains) params.set("contains", filter.contains);
  if (filter.exceptionsOnly) params.set("exceptionsOnly", "true");
  return params;
}

export function ExplorerView() {
  const [searchParams, setSearchParams] = useSearchParams();
  const filter = useMemo(() => filterFromParams(searchParams), [searchParams]);
  const [live, setLive] = useState(true);
  const [selected, setSelected] = useState<LogRow | null>(null);

  const tail = useLiveStore((s) => s.tail);
  const tailPaused = useLiveStore((s) => s.tailPaused);
  const newRowsWhilePaused = useLiveStore((s) => s.newRowsWhilePaused);
  const setTailPaused = useLiveStore((s) => s.setTailPaused);

  const { data: historyData } = useQuery({
    queryKey: ["logs", filter],
    queryFn: () => api.logs(filter, { limit: 200, direction: "DESC" }),
  });
  const { data: countData } = useQuery({
    queryKey: ["logs-count", filter],
    queryFn: () => api.logsCount(filter),
  });

  const filteredTail = useMemo(
    () =>
      tail.filter((row) => {
        if (filter.minLevel && LOG_LEVELS.indexOf(row.level) < LOG_LEVELS.indexOf(filter.minLevel)) {
          return false;
        }
        if (filter.processes?.length && !filter.processes.includes(row.process)) return false;
        if (filter.exceptionsOnly && !row.has_exception) return false;
        if (filter.contains && !row.message.toLowerCase().includes(filter.contains.toLowerCase())) {
          return false;
        }
        return true;
      }),
    [tail, filter],
  );

  const rows = live ? filteredTail : historyData?.rows ?? [];

  // Tracks which seqs have already been rendered once, so a row only gets
  // the fade-in flash the first time it appears in live mode (design §14.3).
  const seenSeqs = useRef(new Set<number>());
  const [flashSeqs, setFlashSeqs] = useState<Set<number>>(new Set());
  useEffect(() => {
    if (!live) return;
    const freshlySeen = rows.filter((r) => !seenSeqs.current.has(r.seq));
    if (freshlySeen.length === 0) return;
    for (const r of freshlySeen) seenSeqs.current.add(r.seq);
    setFlashSeqs(new Set(freshlySeen.map((r) => r.seq)));
    const timer = setTimeout(() => setFlashSeqs(new Set()), 400);
    return () => clearTimeout(timer);
  }, [rows, live]);

  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 24,
    overscan: 20,
  });

  function updateFilter(patch: Partial<LogFilter>) {
    setSearchParams(paramsFromFilter({ ...filter, ...patch }));
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-bg-subtle p-2 text-sm">
        <input
          className="rounded border border-border bg-bg px-2 py-1"
          placeholder="message contains…"
          value={filter.contains ?? ""}
          onChange={(e) => updateFilter({ contains: e.target.value || undefined })}
        />
        <select
          className="rounded border border-border bg-bg px-2 py-1"
          value={filter.minLevel ?? ""}
          onChange={(e) => updateFilter({ minLevel: (e.target.value || undefined) as LogLevel | undefined })}
        >
          <option value="">all levels</option>
          {LOG_LEVELS.map((l) => (
            <option key={l} value={l}>
              {l}+
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={filter.exceptionsOnly ?? false}
            onChange={(e) => updateFilter({ exceptionsOnly: e.target.checked })}
          />
          exceptions only
        </label>
        <button
          type="button"
          onClick={() => setLive((v) => !v)}
          className={clsx(
            "rounded px-2 py-1 font-semibold",
            live ? "bg-accent text-white" : "border border-border",
          )}
        >
          {live ? "▶ LIVE" : "history"}
        </button>
        <span className="ml-auto text-fg-subtle">
          {live ? `${filteredTail.length} in buffer` : `${countData?.count ?? "…"} matches`}
        </span>
      </div>

      {live && tailPaused && newRowsWhilePaused > 0 && (
        <button
          type="button"
          onClick={() => setTailPaused(false)}
          className="border-b border-border bg-accent/10 py-1 text-center text-xs text-accent"
        >
          ⏸ {newRowsWhilePaused} new rows — jump to top
        </button>
      )}

      <div className="flex min-h-0 flex-1">
        <div
          ref={parentRef}
          className="min-w-0 flex-1 overflow-auto"
          onScroll={(e) => {
            if (live && e.currentTarget.scrollTop > 4) setTailPaused(true);
          }}
        >
          <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
            {virtualizer.getVirtualItems().map((item) => {
              const row = rows[item.index];
              if (!row) return null;
              return (
                <div
                  key={row.seq}
                  onClick={() => setSelected(row)}
                  className={clsx(
                    "absolute left-0 right-0 flex cursor-pointer items-center gap-2 border-l-2 px-2 font-mono text-xs hover:bg-bg-inset",
                    row.level === "ERROR" || row.level === "CRITICAL"
                      ? "border-level-error"
                      : row.level === "WARNING"
                        ? "border-level-warning"
                        : "border-transparent",
                    flashSeqs.has(row.seq) && "row-flash",
                  )}
                  style={{ transform: `translateY(${item.start}px)`, height: item.size }}
                >
                  <span className="w-40 shrink-0 text-fg-subtle">{formatRowTs(row.client_ts)}</span>
                  <SeverityBadge level={row.level} />
                  <span className="w-28 shrink-0 truncate text-fg-subtle">{row.process}</span>
                  <span className="truncate">{row.message}</span>
                  {row.has_exception && <span className="text-level-warning">⚠</span>}
                </div>
              );
            })}
          </div>
        </div>

        {selected && (
          <div className="w-96 shrink-0 overflow-auto border-l border-border bg-bg-subtle p-3 text-sm">
            <div className="mb-2 flex items-center justify-between">
              <span className="font-semibold">
                <SeverityBadge level={selected.level} /> {selected.process}
              </span>
              <button type="button" onClick={() => setSelected(null)} className="text-fg-subtle">
                ✕
              </button>
            </div>
            <div className="mb-2 text-xs text-fg-subtle">{selected.client_ts}</div>
            <dl className="mb-3 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-xs">
              <dt className="text-fg-subtle">logger</dt>
              <dd className="font-mono">{selected.logger}</dd>
              <dt className="text-fg-subtle">module</dt>
              <dd className="font-mono">
                {selected.module}
                {selected.line ? `:${selected.line}` : ""}
              </dd>
              <dt className="text-fg-subtle">pid / host</dt>
              <dd className="font-mono">
                {selected.pid} / {selected.host}
              </dd>
              <dt className="text-fg-subtle">session / seq</dt>
              <dd className="font-mono">
                {selected.session} / {selected.seq}
              </dd>
            </dl>
            <div className="rounded bg-bg-inset p-2 font-mono text-xs whitespace-pre-wrap">
              {selected.message}
            </div>
            <div className="mt-3 flex flex-col gap-1">
              <button
                type="button"
                className="rounded border border-border px-2 py-1 text-xs"
                onClick={() => navigator.clipboard.writeText(selected.message)}
              >
                Copy
              </button>
              <button
                type="button"
                className="rounded border border-border px-2 py-1 text-xs"
                onClick={() => updateFilter({ processes: [selected.process] })}
              >
                Filter to this process
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

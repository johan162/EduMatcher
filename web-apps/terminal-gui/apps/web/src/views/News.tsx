/**
 * News (WP-E5, WP-NR03): pm-market-sim's recorded headlines, newest first.
 *
 * CALF carries no news, so this polls the bridge's `/api/news` proxy every 20
 * seconds while the view is open. pm-api-gwy reads the headlines from the
 * sim's news history, so a restart loses none. Filtering and paging happen
 * there: a time window, a symbol or sector (a symbol also shows its sector's
 * and the market's news), status and sentiment. A rumour that was later
 * retracted is struck through, as is the retraction.
 *
 * Page 1 follows the news as it arrives. Leaving it pins the window's ends at
 * that moment, so later pages do not shift as headlines arrive; a chip counts
 * the newer ones and goes back to page 1.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { NewsEvent, NewsSnapshot } from "@edumatcher/terminal-types";
import { api, type NewsQuery } from "../lib/api.js";
import { clockInTimezone, dateInTimezone } from "../lib/format.js";
import { NEWS_WINDOW_LABEL, newsWindowStart, sectorIndex, type NewsWindow } from "../lib/news.js";
import { pageCount } from "../lib/paging.js";
import { useLiveStore } from "../store/useLiveStore.js";
import {
  ROWS_PER_PAGE_CHOICES,
  usePrefsStore,
  type NewsSentimentFilter,
  type NewsStatusFilter,
} from "../store/usePrefsStore.js";
import { newsHelp } from "../lib/help.js";
import { InfoTip } from "../components/shared/InfoTip.js";

export const NEWS_POLL_MS = 20_000;

/** The window's ends while off page 1. */
interface Pin {
  from?: string;
  to: string;
}

const SELECT_CLASS = "rounded border border-border bg-surface px-2 py-1 text-sm";

function StatusBadge({ item }: { item: NewsEvent }) {
  if (item.status === "RUMOUR") {
    const cred = item.credibility === undefined ? "" : ` ${Math.round(item.credibility * 100)}%`;
    return <span className="rounded bg-halt-bg px-1.5 py-0.5 text-xs text-warning">RUMOUR{cred}</span>;
  }
  if (item.status === "RETRACTED") {
    return <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-fg-subtle">RETRACTED</span>;
  }
  if (item.related_id) {
    return <span className="rounded bg-muted px-1.5 py-0.5 text-xs">CONFIRMED</span>;
  }
  return null;
}

/** The clock, with the date in front when it is not today's. */
function when(item: NewsEvent, timeZone: string, today: string): string {
  const iso = new Date(item.ts_ns / 1e6).toISOString();
  const day = dateInTimezone(iso, timeZone);
  const clock = clockInTimezone(iso, timeZone);
  return day === today ? clock : `${day} ${clock}`;
}

export function NewsView() {
  const sessionTimezone = useLiveStore((s) => s.sessionTimezone);
  const newsWindow = usePrefsStore((s) => s.newsWindow);
  const newsStatus = usePrefsStore((s) => s.newsStatus);
  const newsSentiment = usePrefsStore((s) => s.newsSentiment);
  const setNewsWindow = usePrefsStore((s) => s.setNewsWindow);
  const setNewsStatus = usePrefsStore((s) => s.setNewsStatus);
  const setNewsSentiment = usePrefsStore((s) => s.setNewsSentiment);
  const perPage = usePrefsStore((s) => s.newsRowsPerPage);
  const setNewsRowsPerPage = usePrefsStore((s) => s.setNewsRowsPerPage);
  const [snapshot, setSnapshot] = useState<NewsSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(0);
  const [pin, setPin] = useState<Pin | null>(null);
  const [newer, setNewer] = useState(0);
  /** The ends page 1 last asked for, to pin when leaving it. */
  const lastEnds = useRef<Pin>({ to: new Date().toISOString() });

  useEffect(() => {
    let live = true;
    const poll = () => {
      const now = Date.now();
      const from = pin ? pin.from : newsWindowStart(newsWindow, now);
      const query: NewsQuery = {
        limit: perPage,
        offset: page * perPage,
        from,
        to: pin?.to,
        filter: filter.trim() || undefined,
        status: newsStatus === "ALL" ? undefined : newsStatus,
        sentiment: newsSentiment === "all" ? undefined : newsSentiment,
      };
      if (!pin) lastEnds.current = { from, to: new Date(now).toISOString() };
      api
        .news(query)
        .then((s) => {
          if (!live) return;
          setSnapshot(s);
          setError(null);
        })
        .catch((e: unknown) => live && setError(String(e instanceof Error ? e.message : e)));
      if (pin) {
        const after = new Date(Date.parse(pin.to) + 1).toISOString();
        api
          .news({ ...query, limit: 1, offset: 0, from: after, to: undefined })
          .then((s) => live && setNewer(s.total))
          .catch(() => undefined);
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), NEWS_POLL_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [page, perPage, pin, filter, newsWindow, newsStatus, newsSentiment]);

  /** Any change of filter starts again from the newest headline. */
  const restart = () => {
    setPage(0);
    setPin(null);
    setNewer(0);
  };
  const goTo = (next: number) => {
    if (next === 0) return restart();
    if (!pin) setPin(lastEnds.current);
    setPage(next);
  };

  const rows = snapshot?.news ?? [];
  const total = snapshot?.total ?? 0;
  const pages = pageCount(total, perPage);
  const filtered =
    filter.trim() !== "" || newsWindow !== "all" || newsStatus !== "ALL" || newsSentiment !== "all";
  const today = dateInTimezone(new Date().toISOString(), sessionTimezone);
  const options = useMemo(() => {
    const sectorOf = sectorIndex(snapshot?.sectors ?? {});
    return [...new Set([...Object.values(sectorOf), ...Object.keys(sectorOf)])].sort();
  }, [snapshot]);

  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">News</h1>
        <input
          aria-label="Filter news by symbol or sector"
          placeholder="Symbol or sector"
          list="news-filter-options"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value);
            restart();
          }}
          className="rounded border border-border bg-surface px-2 py-1 text-sm"
        />
        <datalist id="news-filter-options">
          {options.map((o) => (
            <option key={o} value={o} />
          ))}
        </datalist>
        <select
          aria-label="News time window"
          value={newsWindow}
          onChange={(e) => {
            setNewsWindow(e.target.value as NewsWindow);
            restart();
          }}
          className={SELECT_CLASS}
        >
          {Object.entries(NEWS_WINDOW_LABEL).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <select
          aria-label="News status"
          value={newsStatus}
          onChange={(e) => {
            setNewsStatus(e.target.value as NewsStatusFilter);
            restart();
          }}
          className={SELECT_CLASS}
        >
          <option value="ALL">Any status</option>
          <option value="RUMOUR">Rumours</option>
          <option value="CONFIRMED">Confirmed</option>
          <option value="RETRACTED">Retracted</option>
        </select>
        <select
          aria-label="News sentiment"
          value={newsSentiment}
          onChange={(e) => {
            setNewsSentiment(e.target.value as NewsSentimentFilter);
            restart();
          }}
          className={SELECT_CLASS}
        >
          <option value="all">Any sentiment</option>
          <option value="positive">Positive</option>
          <option value="negative">Negative</option>
        </select>
        {pin && newer > 0 && (
          <button
            type="button"
            onClick={restart}
            className="rounded bg-muted px-2 py-0.5 text-xs text-fg hover:bg-bg-inset"
          >
            {newer} new
          </button>
        )}
        {error && <span className="text-sm text-warning">news unavailable: {error}</span>}
        <div className="ml-auto flex items-center gap-2 text-xs">
          <span className="tabular text-fg-subtle">
            {total} headline{total === 1 ? "" : "s"}
          </span>
          <span className="tabular text-fg-subtle">
            Page {Math.min(page, pages - 1) + 1}/{pages}
          </span>
          <button
            type="button"
            onClick={() => goTo(page - 1)}
            disabled={page === 0}
            aria-label="Previous page"
            className="rounded p-1 text-fg-subtle hover:bg-bg-inset hover:text-fg disabled:opacity-30"
          >
            <ChevronLeft size={14} />
          </button>
          <button
            type="button"
            onClick={() => goTo(page + 1)}
            disabled={page >= pages - 1}
            aria-label="Next page"
            className="rounded p-1 text-fg-subtle hover:bg-bg-inset hover:text-fg disabled:opacity-30"
          >
            <ChevronRight size={14} />
          </button>
          <select
            value={perPage}
            onChange={(e) => {
              setNewsRowsPerPage(Number(e.target.value));
              restart();
            }}
            aria-label="Rows per page"
            className="rounded border border-border bg-bg-inset px-1 py-0.5 text-xs text-fg-subtle"
          >
            {ROWS_PER_PAGE_CHOICES.map((count) => (
              <option key={count} value={count}>
                {count} rows
              </option>
            ))}
          </select>
        </div>
      </header>

      <div className="overflow-hidden rounded border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left text-xs uppercase text-fg-subtle">
            <tr>
              <th className="px-3 py-2">
                Time <InfoTip label="Time" help={newsHelp("Time")!} />
              </th>
              <th className="px-3 py-2">
                Status <InfoTip label="Status" help={newsHelp("Status")!} />
              </th>
              <th className="px-3 py-2">
                Scope <InfoTip label="Scope" help={newsHelp("Scope")!} />
              </th>
              <th className="px-3 py-2">
                Headline <InfoTip label="Headline" help={newsHelp("Headline")!} />
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((n) => (
              <tr
                key={`${n.id}-${n.ts_ns}`}
                data-testid="news-row"
                className="border-t border-border align-top"
              >
                <td className="whitespace-nowrap px-3 py-1 tabular text-fg-subtle">
                  {when(n, sessionTimezone, today)}
                </td>
                <td className="whitespace-nowrap px-3 py-1">
                  <StatusBadge item={n} />
                </td>
                <td className="whitespace-nowrap px-3 py-1 text-fg-subtle">
                  {n.scope === "MARKET" ? "MARKET" : n.targets.join(", ")}
                </td>
                <td
                  className={clsx(
                    "px-3 py-1",
                    n.sentiment > 0 && "text-up",
                    n.sentiment < 0 && "text-down",
                    (n.status === "RETRACTED" || n.resolution === "RETRACTED") && "line-through opacity-60",
                  )}
                >
                  {n.headline}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr className="border-t border-border">
                <td colSpan={4} className="px-3 py-6 text-center text-fg-faint">
                  {filtered ? "No headlines match." : "No news yet — is pm-market-sim running?"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

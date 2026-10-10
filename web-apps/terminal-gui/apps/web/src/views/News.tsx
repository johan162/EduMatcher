/**
 * News (WP-E5): pm-market-sim's headlines, newest first.
 *
 * CALF carries no news, so this polls the bridge's `/api/news` proxy once a
 * second while the view is open. The filter takes a symbol or a sector; a
 * symbol also shows its sector's and the market's news. A rumour that was
 * later retracted is struck through, as is the retraction.
 */

import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import type { NewsEvent, NewsSnapshot } from "@edumatcher/terminal-types";
import { api } from "../lib/api.js";
import { clockUtc } from "../lib/format.js";
import { newsMatches, resolutions, sectorIndex } from "../lib/news.js";

export const NEWS_POLL_MS = 1000;
const VISIBLE_ROWS = 100;

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

export function NewsView() {
  const [snapshot, setSnapshot] = useState<NewsSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    let live = true;
    const poll = () =>
      api
        .news()
        .then((s) => {
          if (!live) return;
          setSnapshot(s);
          setError(null);
        })
        .catch((e: unknown) => live && setError(String(e instanceof Error ? e.message : e)));
    void poll();
    const timer = setInterval(() => void poll(), NEWS_POLL_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  const items = useMemo(() => [...(snapshot?.news ?? [])].reverse(), [snapshot]);
  const sectorOf = useMemo(() => sectorIndex(snapshot?.sectors ?? {}), [snapshot]);
  const ended = useMemo(() => resolutions(items), [items]);
  const rows = useMemo(
    () => items.filter((n) => newsMatches(n, filter, sectorOf)).slice(0, VISIBLE_ROWS),
    [items, filter, sectorOf],
  );
  const options = useMemo(
    () => [...new Set([...Object.values(sectorOf), ...Object.keys(sectorOf)])].sort(),
    [sectorOf],
  );

  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">News</h1>
        <input
          aria-label="Filter news by symbol or sector"
          placeholder="Symbol or sector"
          list="news-filter-options"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="rounded border border-border bg-surface px-2 py-1 text-sm"
        />
        <datalist id="news-filter-options">
          {options.map((o) => (
            <option key={o} value={o} />
          ))}
        </datalist>
        {error && <span className="text-sm text-warning">news unavailable: {error}</span>}
      </header>

      <div className="overflow-hidden rounded border border-border">
        <table className="w-full text-sm">
          <tbody>
            {rows.map((n) => (
              <tr key={n.id} data-testid="news-row" className="border-t border-border align-top">
                <td className="whitespace-nowrap px-3 py-1 tabular text-fg-subtle">
                  {clockUtc(new Date(n.ts_ns / 1e6).toISOString())}
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
                    (n.status === "RETRACTED" || ended[n.id] === "RETRACTED") && "line-through opacity-60",
                  )}
                >
                  {n.headline}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr className="border-t border-border">
                <td className="px-3 py-6 text-center text-fg-faint">
                  {items.length === 0 ? "No news yet — is pm-market-sim running?" : "No headlines match."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

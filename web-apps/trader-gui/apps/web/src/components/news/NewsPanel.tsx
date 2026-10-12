import { useMemo, useState } from "react";
import { useNewsStore } from "@/store/useNewsStore.js";
import { newsMatches, resolutions } from "@/lib/news.js";
import { formatTime } from "@/lib/formatters.js";
import type { NewsEvent } from "@/types/index.js";

/** Rows shown; the store keeps more so a filter still finds older ones. */
const SHOWN = 50;

function StatusBadge({ item }: { item: NewsEvent }) {
  if (item.status === "RUMOUR") {
    const cred = item.credibility === undefined ? "" : ` ${Math.round(item.credibility * 100)}%`;
    return (
      <span
        className="px-1.5 py-0.5 rounded bg-halt text-black text-[10px] font-medium"
        title="Unconfirmed — the credibility is how believable it is"
      >
        RUMOUR{cred}
      </span>
    );
  }
  if (item.status === "RETRACTED") {
    return (
      <span className="px-1.5 py-0.5 rounded bg-raised text-fg-dim text-[10px]">RETRACTED</span>
    );
  }
  if (item.related_id) {
    return <span className="px-1.5 py-0.5 rounded bg-raised text-fg text-[10px]">CONFIRMED</span>;
  }
  return null;
}

/**
 * pm-market-sim's headlines (WP-E5), newest first. The filter takes a symbol
 * or a sector: a symbol also shows its sector's and the market's news.
 * A rumour that was later retracted is struck through, as is the retraction.
 */
export function NewsPanel() {
  const items = useNewsStore((s) => s.items);
  const sectorOf = useNewsStore((s) => s.sectorOf);
  const [filter, setFilter] = useState("");
  const ended = useMemo(() => resolutions(items), [items]);
  const shown = useMemo(
    () => items.filter((n) => newsMatches(n, filter, sectorOf)).slice(0, SHOWN),
    [items, filter, sectorOf],
  );
  const options = useMemo(
    () => [...new Set([...Object.values(sectorOf), ...Object.keys(sectorOf)])].sort(),
    [sectorOf],
  );

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <input
          aria-label="Filter news by symbol or sector"
          placeholder="Symbol or sector"
          list="news-filter-options"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="bg-raised border border-line rounded px-2 py-1 text-xs text-fg w-48"
        />
        <datalist id="news-filter-options">
          {options.map((o) => (
            <option key={o} value={o} />
          ))}
        </datalist>
      </div>
      {shown.length === 0 ? (
        <p className="text-xs text-fg-dim">
          {items.length === 0 ? "No news yet — is pm-market-sim running?" : "No headlines match."}
        </p>
      ) : (
        <table className="text-xs w-full">
          <tbody>
            {shown.map((n) => {
              const struck = n.status === "RETRACTED" || ended[n.id] === "RETRACTED";
              const tone = n.sentiment > 0 ? "text-up" : n.sentiment < 0 ? "text-down" : "text-fg";
              return (
                <tr key={n.id} data-testid="news-row" className="border-b border-line align-top">
                  <td className="py-1 pr-2 text-fg-faint whitespace-nowrap">
                    {formatTime(n.ts_ns / 1e9)}
                  </td>
                  <td className="py-1 pr-2 whitespace-nowrap">
                    <StatusBadge item={n} />
                  </td>
                  <td className="py-1 pr-2 text-fg-dim whitespace-nowrap">
                    {n.scope === "MARKET" ? "MARKET" : n.targets.join(", ")}
                  </td>
                  <td className={`py-1 ${tone} ${struck ? "line-through opacity-60" : ""}`}>
                    {n.headline}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

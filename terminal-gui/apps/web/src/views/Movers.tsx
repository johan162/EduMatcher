/**
 * Market Movers (design §12).
 *
 * A different ranking over the same live+REST dataset the Overview already
 * builds — §12.2 is explicit that this opens no new subscriptions. `Active`
 * ranks by session volume instead of percentage change.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import type { DailyBar } from "@edumatcher/terminal-types";
import { api } from "../lib/api.js";
import { useLiveStore } from "../store/useLiveStore.js";
import { usePrefsStore } from "../store/usePrefsStore.js";
import {
  buildRows,
  moverBarFraction,
  rankMovers,
  type MoversTab,
  type OverviewRow,
} from "../lib/overview-rows.js";
import { ABSENT, price, qty } from "../lib/format.js";

const TABS: { id: MoversTab; label: string }[] = [
  { id: "gainers", label: "Gainers" },
  { id: "losers", label: "Losers" },
  { id: "active", label: "Active" },
];

function pct(value: number | undefined): string {
  if (value === undefined || !Number.isFinite(value)) return ABSENT;
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function MoversView() {
  const symbols = useLiveStore((s) => s.symbols);
  const top = useLiveStore((s) => s.top);
  const halted = useLiveStore((s) => s.halted);
  const watchlist = usePrefsStore((s) => s.watchlist);
  const [tab, setTab] = useState<MoversTab>("gainers");

  // Open and volume are not on the CALF wire — same short re-poll the
  // Overview uses, and react-query dedupes the shared key so opening both
  // tabs costs one request rather than two.
  const { data } = useQuery({
    queryKey: ["history", "daily"],
    queryFn: api.dailyBars,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });

  const daily = useMemo(() => {
    const bySymbol: Record<string, DailyBar> = {};
    for (const bar of data?.daily ?? []) bySymbol[bar.symbol] = bar;
    return bySymbol;
  }, [data]);

  const rows = useMemo(
    () =>
      buildRows({ symbols, top, daily, halted, watchlist, filter: "all" }),
    [symbols, top, daily, halted, watchlist],
  );
  const ranked = useMemo(() => rankMovers(rows, tab), [rows, tab]);

  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Movers</h1>
        <div className="flex rounded border border-border" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={clsx(
                "px-3 py-1 text-sm first:rounded-l last:rounded-r",
                tab === t.id ? "bg-accent text-accent-fg" : "hover:bg-muted",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        <span className="ml-auto text-sm text-fg-subtle tabular">
          {ranked.length} of {rows.length}
        </span>
      </header>

      <div className="overflow-hidden rounded border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left text-xs uppercase text-fg-subtle">
            <tr>
              <th className="px-3 py-2">Symbol</th>
              <th className="px-3 py-2 text-right">Last</th>
              <th className="px-3 py-2 text-right">
                {tab === "active" ? "Volume" : "%Chg"}
              </th>
              <th className="px-3 py-2 w-1/2" />
            </tr>
          </thead>
          <tbody>
            {ranked.map((row: OverviewRow) => (
              <tr key={row.sym} className="border-t border-border">
                <td className="px-3 py-1 font-medium">
                  {row.sym}
                  {row.halted && (
                    <span className="ml-1.5 text-xs text-halt" title="halted">
                      ●
                    </span>
                  )}
                </td>
                <td className="px-3 py-1 text-right tabular">{price(row.last)}</td>
                <td
                  className={clsx(
                    "px-3 py-1 text-right tabular",
                    tab !== "active" &&
                      ((row.pctChg ?? 0) > 0 ? "text-up" : "text-down"),
                  )}
                >
                  {tab === "active" ? qty(row.volume) : pct(row.pctChg)}
                </td>
                <td className="px-3 py-1">
                  <div className="h-2 rounded bg-muted">
                    <div
                      className={clsx(
                        "h-2 rounded",
                        tab === "active"
                          ? "bg-accent"
                          : (row.pctChg ?? 0) > 0
                            ? "bg-up"
                            : "bg-down",
                      )}
                      style={{
                        width: `${moverBarFraction(row, ranked, tab) * 100}%`,
                      }}
                      aria-hidden
                    />
                  </div>
                </td>
              </tr>
            ))}
            {ranked.length === 0 && (
              <tr className="border-t border-border">
                <td colSpan={4} className="px-3 py-6 text-center text-fg-subtle">
                  {/*
                    Distinguish "nothing qualifies" from "no data". A symbol
                    that has not traded has no percentage change at all, and
                    ranking it as 0.00% would claim it was flat.
                  */}
                  {rows.length === 0
                    ? "Waiting for the instrument universe."
                    : tab === "active"
                      ? "Nothing has traded yet this session."
                      : `No ${tab} yet — no symbol has moved off its open.`}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/**
 * Index View (design §10).
 *
 * Headline level and session come from the live CALF `INDEX` channel; the
 * chart splices that live tail onto historical REST data. §10.2a is strict
 * about the split and this view follows it: any headline "level" figure comes
 * from the live `IDX` stream, never from a REST row for the current date,
 * because `/history/index-daily`'s `close_level` is only final once
 * `close_session_state == "CLOSED"`. Open/High/Low are safe to read from the
 * REST row even intraday — those are running-so-far values that only get more
 * correct as the day goes on.
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useLiveStore } from "../store/useLiveStore.js";
import { api } from "../lib/api.js";
import { ABSENT, price } from "../lib/format.js";
import {
  INDEX_TIMEFRAMES,
  dailySeries,
  indexRangeStart,
  recentChanges,
  snapshotSeries,
  usesSnapshots,
  withLiveTail,
  type IndexTimeframe,
} from "../lib/index-series.js";
import { IndexChart } from "../components/IndexChart.js";

export function IndexView() {
  const configured = useLiveStore((s) => s.indexes);
  const live = useLiveStore((s) => s.indexLive);
  const [selected, setSelected] = useState<string | null>(null);
  const [tf, setTf] = useState<IndexTimeframe>("1D");

  // Settle on the first configured index once SYMBOLS arrives, and drop a
  // selection that is no longer configured (a reconnect can change the set).
  useEffect(() => {
    if (configured.length === 0) {
      if (selected !== null) setSelected(null);
      return;
    }
    if (selected === null || !configured.includes(selected)) {
      setSelected(configured[0] ?? null);
    }
  }, [configured, selected]);

  const indexId = selected;
  const snapshot = indexId ? live[indexId] : undefined;

  // No subscribe/unsubscribe here, unlike DEPTH and CB. The bridge holds a
  // standing `SUB|CH=INDEX` for every configured index id from its own config
  // and broadcasts those frames to all tabs, so switching index costs nothing
  // upstream and the level for one already-open index keeps arriving.
  const from = useMemo(() => indexRangeStart(tf), [tf]);

  const intraday = usesSnapshots(tf);
  const { data: snapRows } = useQuery({
    queryKey: ["history", "index-snapshots", indexId, from],
    queryFn: () => api.indexSnapshots(indexId!, from),
    enabled: Boolean(indexId) && intraday,
    staleTime: 5_000,
  });
  const { data: dailyRows } = useQuery({
    queryKey: ["history", "index-daily", indexId, from],
    queryFn: () => api.indexDaily(indexId!, from),
    enabled: Boolean(indexId) && !intraday,
    staleTime: 30_000,
  });
  // Fetched once per view, not polled — these are rare, operator-driven
  // events, so a refresh or view re-open is enough (§10.2).
  const { data: eventRows } = useQuery({
    queryKey: ["history", "index-events", indexId],
    queryFn: () => api.indexEvents(indexId!),
    enabled: Boolean(indexId),
    staleTime: Infinity,
  });

  const series = useMemo(() => {
    const history = intraday
      ? snapshotSeries(snapRows?.snapshots ?? [])
      : dailySeries(dailyRows?.daily ?? []);
    return withLiveTail(history, snapshot?.level, Math.floor(Date.now() / 1000));
  }, [intraday, snapRows, dailyRows, snapshot?.level]);

  const changes = useMemo(() => recentChanges(eventRows?.events ?? []), [eventRows]);

  // Today's REST row, for Open/High/Low. Only consulted on daily presets;
  // intraday rows carry day_open/day_high/day_low of their own but the panel
  // reads one consistent source rather than mixing the two.
  const todayRow = dailyRows?.daily?.[dailyRows.daily.length - 1];

  if (configured.length === 0) {
    return (
      <section className="flex flex-col gap-3">
        <h1 className="text-lg font-semibold">Index</h1>
        <div className="rounded border border-border bg-surface px-4 py-8 text-center text-fg-subtle">
          This exchange has no index configured.
        </div>
      </section>
    );
  }

  const chg = snapshot?.chg;
  const pctChg = snapshot?.pctChg;
  const up = (chg ?? 0) >= 0;

  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-wrap items-baseline gap-3">
        {configured.length === 1 ? (
          <h1 className="text-lg font-semibold">{indexId} index</h1>
        ) : (
          <select
            aria-label="Index"
            value={indexId ?? ""}
            onChange={(e) => setSelected(e.target.value)}
            className="rounded border border-border bg-surface px-2 py-1 text-lg font-semibold"
          >
            {configured.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        )}
        <span className="text-2xl font-semibold tabular">{price(snapshot?.level)}</span>
        <span className={clsx("tabular", up ? "text-up" : "text-down")}>
          {chg === undefined ? ABSENT : `${up ? "+" : ""}${chg.toFixed(2)}`}
          {pctChg !== undefined && ` (${up ? "+" : ""}${pctChg.toFixed(2)}%)`}
        </span>
        {snapshot?.session && (
          <span
            className="ml-auto rounded bg-muted px-2 py-0.5 text-xs"
            title="Session reported by the live INDEX stream"
          >
            ● {snapshot.session}
          </span>
        )}
      </header>

      <div className="flex gap-1" role="tablist">
        {INDEX_TIMEFRAMES.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tf === t}
            onClick={() => setTf(t)}
            className={clsx(
              "rounded border px-2 py-0.5 text-sm",
              tf === t ? "border-accent bg-accent text-accent-fg" : "border-border hover:bg-muted",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      <IndexChart points={series} />

      <div className="grid gap-3 md:grid-cols-2">
        <dl className="rounded border border-border px-3 py-2 text-sm">
          <Row label="Open" value={price(todayRow?.open_level ?? undefined)} />
          <Row label="High" value={price(todayRow?.high_level ?? undefined)} />
          <Row label="Low" value={price(todayRow?.low_level ?? undefined)} />
          <Row
            label="Aggregate cap"
            value={snapshot?.aggCap === undefined ? ABSENT : `${(snapshot.aggCap / 1e12).toFixed(2)}T`}
          />
          <Row label="Session" value={snapshot?.session ?? ABSENT} />
        </dl>

        {changes.length > 0 && (
          <div className="rounded border border-border px-3 py-2 text-sm">
            <div className="mb-1 text-xs uppercase text-fg-subtle">Recent changes</div>
            <ul className="space-y-0.5">
              {changes.map((line) => (
                <li key={line} className="text-fg-subtle">
                  {line}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between py-0.5">
      <dt className="text-fg-subtle">{label}</dt>
      <dd className="tabular">{value}</dd>
    </div>
  );
}

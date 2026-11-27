/**
 * The Market workspace (design §9.4, Analyse mode of R0): one symbol × time
 * canvas, with a table equivalent for every mark and the order drawer.
 *
 * The URL is the state: `symbol`, the interval (`from`, `to`: epoch ns on
 * the receipt clock) and the drawer (`order`, `run`, `tab`). A brush or a
 * click pushes a history entry, so Back and Forward restore both. Interval
 * changes are debounced: one heatmap and one lifeline request per settled
 * interval (workplan AG6).
 */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { useHeatmap, useLifelines, useSnapshot, useTrades } from "@/api/queries";
import type { LifelineT, LifelinesT } from "@/api/schemas";
import { buildOption, maskText, pickLifeline, type CanvasInput } from "@/components/market/chartOption";
import { EChart } from "@/components/market/EChart";
import { OrderDrawer, type DrawerTab } from "@/components/market/OrderDrawer";
import { EmptyState } from "@/components/shared/EmptyState";
import { ExplainLine } from "@/components/shared/Explain";
import { ErrorPanel } from "@/components/shared/QueryState";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { END_MARKS, endText } from "@/lib/marks";
import { clockText, msToNs, nsToMs, priceText } from "@/lib/ns";
import { useSnapshotStore } from "@/store/useSnapshotStore";

const DEBOUNCE_MS = 150;
const TABS: DrawerTab[] = ["story", "checks", "raw"];

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

export function MarketPage() {
  const snapshotId = useSnapshotStore((s) => s.snapshotId);
  if (!snapshotId) {
    return (
      <div className="space-y-3">
        <h1 className="text-lg font-semibold">Market</h1>
        <EmptyState title="No snapshot pinned" hint="Choose an evidence collection in the top bar first." />
      </div>
    );
  }
  return <Market snapshotId={snapshotId} />;
}

function Market({ snapshotId }: { snapshotId: string }) {
  const snapshot = useSnapshot(snapshotId);
  const [params, setParams] = useSearchParams();
  const symbols = snapshot.data?.symbols ?? [];
  const symbol = params.get("symbol");

  /** Change URL parameters: one history entry (`replace` for defaults). */
  const update = useCallback(
    (changes: Record<string, string | null>, replace = false) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(changes)) {
            if (v === null) next.delete(k);
            else next.set(k, v);
          }
          return next;
        },
        { replace },
      ),
    [setParams],
  );

  useEffect(() => {
    if (!symbol && symbols[0]) update({ symbol: symbols[0].symbol }, true);
  }, [symbol, symbols, update]);

  return (
    <div className="flex h-full min-h-0 gap-3">
      <div className="flex min-w-0 flex-1 flex-col gap-2 overflow-auto">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-lg font-semibold">Market</h1>
          <label htmlFor="symbol" className="text-xs text-fg-dim">
            Symbol
          </label>
          <select
            id="symbol"
            value={symbol ?? ""}
            onChange={(e) => update({ symbol: e.target.value, from: null, to: null, order: null, run: null, tab: null })}
            className="rounded border border-line bg-raised px-1.5 py-0.5 font-mono text-xs"
          >
            {symbols.map((s) => (
              <option key={s.symbol} value={s.symbol}>
                {s.symbol}
              </option>
            ))}
          </select>
          {snapshot.isError && <ErrorPanel error={snapshot.error} />}
        </div>
        {symbol && <Canvas snapshotId={snapshotId} symbol={symbol} params={params} update={update} />}
      </div>
      {symbol && params.get("order") && (
        <OrderDrawer
          snapshotId={snapshotId}
          orderId={params.get("order")!}
          run={/^\d+$/.test(params.get("run") ?? "") ? Number(params.get("run")) : null}
          tab={(TABS as string[]).includes(params.get("tab") ?? "") ? (params.get("tab") as DrawerTab) : "story"}
          onTab={(tab) => update({ tab })}
          onClose={() => update({ order: null, run: null, tab: null })}
        />
      )}
    </div>
  );
}

const NO_LIFELINES: LifelinesT = {
  snapshot_id: "",
  symbol: "",
  clock: "receipt",
  tick_decimals: null,
  from_ns: "0",
  to_ns: "0",
  gateway: null,
  aggregated: false,
  segment_cap: 0,
  segments: 0,
  without_admission: 0,
  lifelines: [],
  levels: [],
};

interface CanvasProps {
  snapshotId: string;
  symbol: string;
  params: URLSearchParams;
  update: (changes: Record<string, string | null>, replace?: boolean) => void;
}

function Canvas({ snapshotId, symbol, params, update }: CanvasProps) {
  const window = useDebounced(`${params.get("from") ?? ""} ${params.get("to") ?? ""}`, DEBOUNCE_MS);
  const [from, to] = window.split(" ").map((v) => v || null) as [string | null, string | null];
  const heatmap = useHeatmap(snapshotId, symbol, from, to);
  const lifelines = useLifelines(snapshotId, symbol, from, to);
  const trades = useTrades(snapshotId, symbol);
  const selected = params.get("order");

  const open = useCallback(
    (life: LifelineT) => update({ order: life.order_id, run: String(life.run), tab: "story" }),
    [update],
  );

  const input: CanvasInput | null = useMemo(() => {
    if (!heatmap.data) return null;
    return {
      heatmap: heatmap.data,
      lifelines: lifelines.data ?? NO_LIFELINES,
      trades: trades.data?.trades ?? [],
      startMs: nsToMs(heatmap.data.from_ns),
      endMs: nsToMs(heatmap.data.to_ns),
      selected,
    };
  }, [heatmap.data, lifelines.data, trades.data, selected]);
  const option = useMemo(() => (input ? buildOption(input) : null), [input]);

  const decimals = heatmap.data?.tick_decimals ?? lifelines.data?.tick_decimals ?? null;
  const cadence = heatmap.data?.cadence;

  return (
    <>
      <div className="flex flex-wrap items-center gap-3 text-xs text-fg-dim">
        {heatmap.data && (
          <span>
            Window {clockText(nsToMs(heatmap.data.from_ns))} – {clockText(nsToMs(heatmap.data.to_ns))} UTC (receipt clock)
          </span>
        )}
        {(params.get("from") || params.get("to")) && (
          <button type="button" onClick={() => update({ from: null, to: null })} className="rounded bg-raised px-2 py-0.5 text-fg hover:bg-elevated">
            Whole session
          </button>
        )}
        {(heatmap.isPlaceholderData || lifelines.isPlaceholderData) && (
          <span role="status" className="text-halt">
            Updating…
          </span>
        )}
        {cadence && (
          <span>
            {cadence.observations} book observations
            {cadence.median_interval_ns !== null && `, median every ${(Number(cadence.median_interval_ns) / 1e9).toFixed(3)} s`}
            {heatmap.data && `; bins of ${(Number(heatmap.data.bin_ns) / 1e9).toFixed(3)} s`}
          </span>
        )}
      </div>
      <ExplainLine>
        Depth cells are recorded book observations only, each valid until the next one, a phase change, an uncross,
        lost records or the engine stopping; nothing is interpolated. Brush the chart to zoom; click a lifeline for its
        story.
      </ExplainLine>

      {heatmap.isError ? (
        <ErrorPanel error={heatmap.error} onRetry={() => void heatmap.refetch()} />
      ) : option && input ? (
        <EChart
          option={option}
          height={420}
          ariaLabel={`${symbol} depth heatmap, order lifelines and trades`}
          onPlotClick={(ms, price, tolMs, tolPrice) => {
            const life = pickLifeline(input, ms, price, tolMs, tolPrice);
            if (life) open(life);
          }}
          onBrush={(a, b) => update({ from: msToNs(a), to: msToNs(b) })}
        />
      ) : (
        <TableSkeleton rows={6} columns={4} />
      )}
      {trades.data?.truncated && (
        <p className="text-xs text-halt">Trades: only the first 5,000 of this symbol are drawn.</p>
      )}

      <Legend />
      {heatmap.data && (
        <ul aria-label="Evidence masks" className="text-xs">
          {heatmap.data.masks.length === 0 ? (
            <li className="text-fg-dim">No gap or halt in this window.</li>
          ) : (
            heatmap.data.masks.map((m, i) => <li key={i}>▨ {maskText(m)}</li>)
          )}
        </ul>
      )}

      {lifelines.isError ? (
        <ErrorPanel error={lifelines.error} onRetry={() => void lifelines.refetch()} />
      ) : lifelines.data ? (
        <Lifelines body={lifelines.data} decimals={lifelines.data.tick_decimals ?? decimals} selected={selected} onOpen={open} />
      ) : (
        <TableSkeleton rows={4} columns={3} />
      )}
    </>
  );
}

function Legend() {
  return (
    <ul aria-label="Legend" className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-dim">
      <li>
        <span className="mr-1 inline-block h-2 w-3 bg-[rgb(56_132_255)] align-middle" aria-hidden="true" />
        bid depth / buy order
      </li>
      <li>
        <span className="mr-1 inline-block h-2 w-3 bg-[rgb(245_158_11)] align-middle" aria-hidden="true" />
        ask depth / sell order
      </li>
      <li>▲ buyer-initiated trade</li>
      <li>▼ seller-initiated trade</li>
      <li>◆ auction print</li>
      <li>┄ stop held (not shown on the book)</li>
      {Object.values(END_MARKS).map((m) => (
        <li key={m.text}>{`${m.glyph} ${m.text}`}</li>
      ))}
      <li>▨ hatched: gap or halt</li>
    </ul>
  );
}

interface LifelinesProps {
  body: LifelinesT;
  decimals: number | null;
  selected: string | null;
  onOpen: (life: LifelineT) => void;
}

/** The lifelines as a keyboard-navigable list: the canvas's table equivalent. */
function Lifelines({ body, decimals, selected, onOpen }: LifelinesProps) {
  const [remembered, setActive] = useState(0);
  const refs = useRef<(HTMLLIElement | null)[]>([]);
  const lives = body.lifelines;
  // A zoom can shrink the list under the remembered row: keep one row tabbable.
  const active = Math.min(remembered, Math.max(lives.length - 1, 0));

  const move = (index: number) => {
    const next = Math.max(0, Math.min(index, lives.length - 1));
    setActive(next);
    refs.current[next]?.focus();
  };
  const onKeyDown = (e: KeyboardEvent<HTMLUListElement>) => {
    const keys: Record<string, () => void> = {
      ArrowDown: () => move(active + 1),
      ArrowUp: () => move(active - 1),
      Home: () => move(0),
      End: () => move(lives.length - 1),
      Enter: () => lives[active] && onOpen(lives[active]),
      " ": () => lives[active] && onOpen(lives[active]),
    };
    const action = keys[e.key];
    if (action) {
      e.preventDefault();
      action();
    }
  };

  return (
    <section className="space-y-1 text-xs">
      {body.aggregated && (
        <>
          <p className="text-halt">
            {body.segments.toLocaleString("en-US")} segments exceed the {body.segment_cap.toLocaleString("en-US")} shown:
            lifelines are summed per level. Brush a shorter interval to see each order.
          </p>
          <table className="w-full text-left">
            <caption className="sr-only">Lifelines per level</caption>
            <thead className="text-fg-dim">
              <tr>
                <th className="font-normal">Side</th>
                <th className="font-normal">Price</th>
                <th className="font-normal">State</th>
                <th className="font-normal">Orders</th>
                <th className="font-normal">Segments</th>
                <th className="font-normal">Ends</th>
              </tr>
            </thead>
            <tbody>
              {body.levels.map((l, i) => (
                <tr key={i} className="border-t border-line">
                  <td>{l.side}</td>
                  <td className="font-mono">{l.price_ticks === null ? "market" : priceText(l.price_ticks, decimals)}</td>
                  <td>{l.state}</td>
                  <td>{l.orders}</td>
                  <td>{l.segments}</td>
                  <td>
                    {Object.entries(l.ends)
                      .map(([end, n]) => `${n} ${END_MARKS[end as keyof typeof END_MARKS]?.text ?? end}`)
                      .join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {body.without_admission > 0 && (
        <p className="text-fg-dim">
          {body.without_admission} order(s) of this symbol have events but no admission in their run (restored by a
          restart, say): no lifeline is drawn for them.
        </p>
      )}
      <ul role="listbox" aria-label="Order lifelines" onKeyDown={onKeyDown} className="max-h-64 overflow-auto rounded border border-line">
        {lives.length === 0 && !body.aggregated && <li className="p-2 text-fg-dim">No order in this window.</li>}
        {lives.map((life, i) => {
          const first = life.segments[0];
          return (
            <li
              key={`${life.run}-${life.order_id}`}
              ref={(node) => {
                refs.current[i] = node;
              }}
              role="option"
              aria-selected={life.order_id === selected}
              tabIndex={i === active ? 0 : -1}
              onFocus={() => setActive(i)}
              onClick={() => onOpen(life)}
              className={`cursor-pointer px-2 py-1 font-mono focus:outline focus:outline-1 focus:outline-accent ${
                life.order_id === selected ? "bg-accent/20" : "hover:bg-raised"
              }`}
            >
              {`${END_MARKS[life.end].glyph} ${endText(life)}`} · {life.gateway ?? "?"} {life.side ?? ""}{" "}
              {first?.price_ticks !== null && first !== undefined ? priceText(first.price_ticks, decimals) : "market"} ·{" "}
              {life.order_id.slice(0, 8)}… · run {life.run} · filled {life.filled_qty}
              {life.start_censored && " · admitted before the window"}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

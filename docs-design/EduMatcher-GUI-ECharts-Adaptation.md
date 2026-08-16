# EduMatcher Trading GUI — Apache ECharts Chart Adaptation

> Design for replacing TradingView **Lightweight Charts v5** with **Apache ECharts** in the
> Symbol Detail chart ([§16.2 of `EduMatcher-Trading-GUI.md`](./EduMatcher-Trading-GUI.md#162-chart-tab-tradingview-lightweight-charts-v5)),
> driven by a licensing constraint: Lightweight Charts is Apache-2.0 licensed but carries a
> self-imposed attribution clause (on-chart logo + backlink to tradingview.com via the
> `attributionLogo` option, default `true`) that is inappropriate for an educational product.
> Apache ECharts carries no such clause. See the changelog at the end of this document for the
> decision trail.

---

## Table of contents

- [1. Goals and non-goals](#1-goals-and-non-goals)
- [2. Current state: what `SymbolChart.tsx` actually does](#2-current-state-what-symbolcharttsx-actually-does)
- [3. Functional inventory (the contract the replacement must honour)](#3-functional-inventory-the-contract-the-replacement-must-honour)
- [4. Library decision record](#4-library-decision-record)
- [5. Target architecture](#5-target-architecture)
  - [5.1 Adapter interface](#51-adapter-interface)
  - [5.2 ECharts adapter implementation notes](#52-echarts-adapter-implementation-notes)
  - [5.3 Live-tick update path](#53-live-tick-update-path)
  - [5.4 Zoom / pan](#54-zoom--pan)
  - [5.5 Theming](#55-theming)
  - [5.6 Data flow (unchanged)](#56-data-flow-unchanged)
- [6. Risk register](#6-risk-register)
- [7. Phased implementation plan](#7-phased-implementation-plan)
- [8. Testing strategy](#8-testing-strategy)
- [9. v2.0.0 candidate features (chart-adjacent)](#9-v200-candidate-features-chart-adjacent)
- [10. Effort estimate](#10-effort-estimate)
- [Changelog](#changelog)

---

## 1. Goals and non-goals

**Goals:**

1. Replace Lightweight Charts with Apache ECharts in `SymbolChart.tsx` with **no on-chart logo,
   backlink, or other attribution UI** — matching the Apache-2.0 license's actual requirements
   (source-level notice retention only, no on-screen element).
2. Preserve every user-facing behaviour listed in [§3](#3-functional-inventory-the-contract-the-replacement-must-honour)
   exactly — this is a substitution, not a redesign. A trader using the app should not notice the
   swap except for the missing logo.
3. Introduce a **chart adapter interface** so the concrete charting library is no longer imported
   directly by `SymbolChart.tsx` or any other component. This is what makes the swap itself safe
   (testable in isolation) and makes a *future* swap (or a second chart type, e.g. a depth-chart)
   cheap.
4. Identify, and either resolve or explicitly accept, the known ECharts candlestick/time-axis
   rough edges (`apache/echarts#18675`, `#18685`) before committing the full rollout.

**Non-goals:**

- No new chart features in this pass (indicators, overlays, volume panes — see [§9](#9-v200-candidate-features-chart-adjacent)
  for where those belong).
- No change to the candle-building library (`src/lib/candles.ts`) — it is already pure,
  library-agnostic, and unit-testable. It stays as-is.
- No change to the REST/WebSocket contracts this component consumes
  (`useHistoryTradesQuery`, `useHistoryDailyChartQuery`, `useWsEvent("trade", …)`).
- Not attempting a generic "pluggable, works with any of N backends" architecture. The adapter
  is shaped by having exactly one real implementation (ECharts); a second implementation is not
  planned, so the interface should be no more abstract than ECharts' own API already requires.

---

## 2. Current state: what `SymbolChart.tsx` actually does

Source: `web-apps/trader-gui/apps/web/src/components/symbol/SymbolChart.tsx` (250 lines).

The component has five moving parts, each already fairly well isolated:

1. **Chart lifecycle** (`useEffect`, mount/unmount): `createChart(el, { ...CHART_OPTIONS, width, height: 320 })`
   once per mount, torn down with `chart.remove()` on unmount. A `ResizeObserver` on the container
   keeps `width` current via `chart.applyOptions({ width })`.
2. **Series lifecycle** (`useEffect`, keyed on `chartType`): on candlestick/line toggle, the
   existing series is removed (`chart.removeSeries(...)`) and a new one created
   (`chart.addSeries(CandlestickSeries, {...})` or `chart.addSeries(LineSeries, {...})`), then
   seeded with the current candle set and `chart.timeScale().fitContent()` is called.
3. **Data replacement** (`useEffect`, keyed on `[candles, chartType]`): `series.setData(...)`
   whenever the upstream candle set changes (new timeframe selected, or a query refetch), followed
   by `fitContent()`.
4. **Live tick append** (`useWsEvent("trade", handler)`, bound once): on every WS `trade` event for
   the active symbol, folds the tick into the last bar via the library-agnostic `foldTick()` helper
   and calls `series.update(bar)` to patch just the last point — this is the highest-frequency,
   highest-visibility code path in the component.
5. **Chrome**: timeframe buttons (`1m`/`5m`/`1h`/`1D`/`All`), a candlestick/line toggle button,
   and loading/empty overlays. This is plain React/Tailwind and is untouched by the swap.

All chart-library types currently leak into the component's public surface via imports
(`IChartApi`, `ISeriesApi`, `SeriesType`, `UTCTimestamp`, `CandlestickSeries`, `LineSeries`,
`ColorType`, `CrosshairMode`). That leakage is exactly what the adapter interface in [§5](#5-target-architecture)
removes.

---

## 3. Functional inventory (the contract the replacement must honour)

This is the acceptance checklist for the swap — every row must hold true after the migration,
verified per [§8](#8-testing-strategy).

| # | Behaviour | Current implementation | Source |
|---|---|---|---|
| F1 | Candlestick and line chart types, toggled by one button | `CandlestickSeries` / `LineSeries` swap | §16.2, `SymbolChart.tsx:144-160` |
| F2 | Five timeframes: `1m`, `5m`, `1h`, `1D`, `All` | Button row, `TIMEFRAMES` const | §16.2.1 |
| F3 | Intraday candles built client-side from trade prints | `tradesToCandles()` in `candles.ts` | §16.2.1 |
| F4 | Daily/All candles from the daily rollup endpoint | `dailyToCandles()`, `useHistoryDailyChartQuery` | §16.2.1 |
| F5 | Scroll-to-zoom on the time axis | Lightweight Charts native behaviour | §16.2.2 |
| F6 | Click-drag pan | Lightweight Charts native behaviour | §16.2.2 |
| F7 | Crosshair with synced price/time readout on both axes | `CrosshairMode.Normal` | §16.2.2, `CHART_OPTIONS` |
| F8 | Double-click resets zoom to fit all loaded data | Lightweight Charts native behaviour + explicit `fitContent()` calls | §16.2.2 |
| F9 | Live tick append without a full re-render/refetch | `series.update(bar)` off `useWsEvent("trade", …)` | §16.2.3 |
| F10 | Live append only when: timeframe is intraday, tick's symbol matches active symbol | Guard clauses in the WS handler | `SymbolChart.tsx:178-180` |
| F11 | Chart resizes with its container (responsive layout, e.g. panel resize / window resize) | `ResizeObserver` → `applyOptions({ width })` | `SymbolChart.tsx:121-125` |
| F12 | Dark theme matching the app's existing palette (`#0a0a0f` background, `#9090b0` text, `#22c55e`/`#ef4444` up/down, `JetBrains Mono` font) | `CHART_OPTIONS` object | `SymbolChart.tsx:32-45` |
| F13 | Loading and empty-state overlays render over the chart container without disturbing chart layout | Plain absolutely-positioned `<p>` elements | `SymbolChart.tsx:236-246` |
| F14 | Chart tears down cleanly on unmount (no leaked observers/instances) | `observer.disconnect()`, `chart.remove()` in cleanup | `SymbolChart.tsx:127-132` |
| F15 | **No on-chart attribution logo or backlink** | N/A today (this is the defect being fixed) | — |

Two items are explicitly *not* preserved because they are pre-existing, documented gaps in the
current implementation, not swap regressions:

- Volume is tracked in every `Candle.volume` field but is **not rendered** today (no volume pane).
  This stays out of scope — see [§9](#9-v200-candidate-features-chart-adjacent).
- 1D/All show only the latest trading day (`/history/daily` is keyset-paginated one day per call);
  multi-day backfill is a tracked phase-4 limitation in the Trading GUI design, not something this
  swap should silently fix or silently carry forward as a new limitation. It is unaffected by the
  chart-library choice either way, since it is a data-fetching gap, not a rendering gap.

---

## 4. Library decision record

Apache ECharts was chosen over ApexCharts after a side-by-side review (full writeup in prior
conversation; summarized here for the record since this document is the durable artifact):

| Criterion | Apache ECharts | ApexCharts | Winner |
|---|---|---|---|
| License / attribution | Apache-2.0, no on-screen attribution clause (verified against `LICENSE`) | MIT, no on-screen attribution clause | Tie |
| Crosshair (F7) | Native `axisPointer: { type: 'cross' }` — synced crosshair + axis value labels on both axes, matching `CrosshairMode.Normal` | Tooltip-driven hover; a true dual-axis crosshair needs more custom configuration | **ECharts** |
| Live-tick update safety (F9) | `setOption()` patch of the last data point, or `appendData` for streaming; no reported candlestick-specific defect found | Open, unresolved GitHub issue (`apexcharts/apexcharts.js#1007`): candlestick OHLC tooltip values reported as unreliable after `updateSeries()` — exactly this component's live-update pattern | **ECharts** |
| Theming (F12) | Built-in `'dark'` theme + full custom theme-object registration (`echarts.registerTheme`) covering background/text/grid/axis | `theme.mode: 'dark'` + CSS custom-property tokens | Tie (both sufficient) |
| Maintenance signal | ~1.14M weekly npm downloads, Apache Software Foundation project | More frequent recent point releases (verified June 2026 releases) | ApexCharts (minor) |
| Known rough edges | `apache/echarts#18675` (candlestick + `xAxis type: 'time'` friction), `#18685` (data grouping on zoom) — **not yet verified against this app's actual timeframe set; see Risk R1** | — | — |

Given F7 and F9 map directly onto this component's two riskiest behaviours (the crosshair the
user stares at constantly, and the live-update path that runs continuously against a real
WebSocket feed), ECharts is the better fit despite the maintenance-cadence edge going the other
way. This document proceeds on that decision; R1 in [§6](#6-risk-register) is the one open item
from the decision record that this design explicitly carries forward and phases as a spike
(§7 Phase 0) rather than assuming away.

---

## 5. Target architecture

### 5.1 Adapter interface

A new module, `src/lib/chart/ChartAdapter.ts`, defines the interface `SymbolChart.tsx` programs
against. This is intentionally narrow — it is not a generic charting abstraction, it is exactly
the operations §2 identified `SymbolChart.tsx` as performing today:

```typescript
// src/lib/chart/ChartAdapter.ts
import type { Candle } from "@/lib/candles.js";

export type ChartSeriesType = "candlestick" | "line";

export interface ChartTheme {
  background: string;
  textColor: string;
  fontFamily: string;
  gridLineColor: string;
  axisBorderColor: string;
  upColor: string;
  downColor: string;
  lineColor: string;
}

/**
 * Thin wrapper around one chart-library instance bound to one DOM element.
 * `SymbolChart.tsx` (and any future chart consumer) programs only against
 * this interface — no chart-library types or imports outside `lib/chart/`.
 */
export interface ChartHandle {
  /** Swap candlestick <-> line. Recreates the series; re-seed with setData(). */
  setSeriesType(type: ChartSeriesType): void;
  /** Replace the full visible data set (new timeframe / refetch). */
  setData(candles: Candle[]): void;
  /** Patch just the last bar in place (F9) — the live-tick hot path. */
  updateLastBar(bar: Candle): void;
  /** Fit the visible time range to all loaded data (F8, called after setData). */
  fitContent(): void;
  /** Resize the chart to a new pixel width (F11, driven by ResizeObserver). */
  resize(width: number): void;
  /** Tear down the chart instance and release all resources (F14). */
  destroy(): void;
}

export interface CreateChartOptions {
  container: HTMLElement;
  width: number;
  height: number;
  theme: ChartTheme;
  seriesType: ChartSeriesType;
}

export type ChartFactory = (options: CreateChartOptions) => ChartHandle;
```

`SymbolChart.tsx` changes from importing `lightweight-charts` directly to importing
`createEChartsHandle` (or whichever factory is active) from `@/lib/chart/echartsAdapter.js`,
typed as `ChartFactory`. The five `useEffect` blocks in §2 are otherwise structurally unchanged —
they call `chartRef.current.setData(...)`, `.updateLastBar(...)`, etc. instead of touching
`lightweight-charts` APIs directly.

This interface is deliberately **not** exported with a registry or plugin-selection mechanism
(no `chartLibrary: "echarts" | "lightweight-charts"` config flag). Per the non-goals in §1, there
is exactly one production implementation; a second implementation, if ever needed, is a new file
behind the same interface, not a runtime switch.

### 5.2 ECharts adapter implementation notes

`src/lib/chart/echartsAdapter.ts` implements `ChartFactory` using `echarts.init()`. Key mapping
decisions:

- **Chart creation**: `echarts.init(container, undefined, { width, height, renderer: 'canvas' })`.
  `renderer: 'canvas'` (not `'svg'`) matches Lightweight Charts' canvas-based rendering and is the
  better choice for a chart that repaints on every live tick.
- **Series type**: candlestick uses ECharts' native `candlestick` series
  (`{ type: 'candlestick', data: [...] }`, data tuples `[open, close, low, high]` — note the
  order is **not** OHLC, it's O/C/L/H, a real conversion-bug risk flagged as R2); line uses a
  standard `line` series over `close`.
- **`setSeriesType`**: rather than removing/re-adding a series object (there is no ECharts
  equivalent of `chart.removeSeries()`), the adapter calls `chart.setOption({ series: [...] },
  { replaceMerge: ['series'] })` with the new series type — `replaceMerge` is required so the old
  series definition is actually replaced rather than merged, which ECharts would otherwise do by
  index.
- **`setData` / `updateLastBar`**: both go through `chart.setOption({ series: [{ data }] })`.
  For `updateLastBar`, the adapter keeps a local copy of the current data array (ECharts has no
  "patch last point" primitive analogous to Lightweight Charts' `series.update()`), mutates the
  last element, and calls `setOption` with `{ series: [{ data }] }` — **not** the whole option
  tree, so ECharts' internal diffing keeps this cheap. This is the one place this component's
  update model changes shape; see [§5.3](#53-live-tick-update-path).
- **`fitContent`**: `chart.dispatchAction({ type: 'dataZoom', start: 0, end: 100 })`, ECharts'
  equivalent of "reset zoom to show everything."
- **`resize`**: `chart.resize({ width })`.
- **`destroy`**: `chart.dispose()`.

### 5.3 Live-tick update path

This is the highest-risk behavioural change (F9/F10), so it gets its own subsection rather than
being buried in §5.2.

Current (`lightweight-charts`):

```typescript
series.update({ time, open, high, low, close } as never); // patches last bar, O(1)
```

ECharts has no direct equivalent — `setOption` always takes a full (or full-per-series) data
array. The adapter therefore keeps the current data array in a closure inside the `ChartHandle`
instance (not in React state — this must stay off the React render cycle exactly as it does
today, where `lastBarRef`/`candlesRef` are plain refs) and does:

```typescript
function updateLastBar(bar: Candle): void {
  const data = currentData; // closure-local, not React state
  if (data.length && sameBucket(data[data.length - 1], bar)) {
    data[data.length - 1] = toEChartsPoint(bar);
  } else {
    data.push(toEChartsPoint(bar));
  }
  chart.setOption({ series: [{ data }] }, { lazyUpdate: true });
}
```

`lazyUpdate: true` defers the actual repaint to the next animation frame, which matters at
tick-level update frequency on an active symbol — without it, ECharts would synchronously
re-diff and repaint on every single trade print. This needs to be verified under load (Phase 2
of §7, not assumed).

The `isNew` bar/new-bucket distinction already computed by `foldTick()` in `candles.ts` maps
directly onto the push-vs-replace branch above — **no change to `candles.ts` is needed**; the
adapter only needs `foldTick()`'s existing return shape.

### 5.4 Zoom / pan

ECharts requires an explicit `dataZoom` component; it is not automatic the way Lightweight
Charts' scroll/drag zoom is. The adapter's static option includes:

```typescript
dataZoom: [
  { type: 'inside', xAxisIndex: 0, zoomOnMouseWheel: true, moveOnMouseMove: true }, // F5, F6
  // No visible slider — matches current chrome, which has no on-chart zoom slider either.
]
```

`type: 'inside'` gives scroll-to-zoom and drag-to-pan directly on the plot area, matching F5/F6
without adding a new UI element (a slider `dataZoom` would be a visual change beyond what this
swap should introduce — see §9 for that as a possible v2.0.0 addition instead).

Double-click-to-reset (F8) is not a `dataZoom` built-in; the adapter binds a `dblclick` listener
on the chart's zrender instance that calls the same `fitContent()` path described in §5.2.

This is the area most exposed to R1 (the ECharts candlestick + time-axis GitHub issues) — see
§6 and the Phase 0 spike in §7.

### 5.5 Theming

`ChartTheme` (§5.1) is populated from the existing `CHART_OPTIONS` values verbatim — no colour
or font changes (F12):

```typescript
const DEFAULT_THEME: ChartTheme = {
  background: "#0a0a0f",
  textColor: "#9090b0",
  fontFamily: "JetBrains Mono, ui-monospace, monospace",
  gridLineColor: "#1a1a28",
  axisBorderColor: "#2a2a45",
  upColor: "#22c55e",
  downColor: "#ef4444",
  lineColor: "#6ea8fe",
};
```

The adapter maps this onto ECharts option fields directly (`backgroundColor`, `textStyle.color`,
`textStyle.fontFamily`, `splitLine.lineStyle.color` for grid, `axisLine.lineStyle.color` for
axis borders, `itemStyle.color`/`color0` for candlestick up/down) rather than using
`echarts.registerTheme()` with a separate theme JSON — a registered theme is the right tool when
supporting *multiple* named themes (e.g. a future light mode), which is not needed yet. If a
light theme is added later (plausible v2.0.0 candidate, §9), promoting `ChartTheme` values into a
registered theme object at that point is a small, additive change, not a rework.

### 5.6 Data flow (unchanged)

Nothing here changes: `useHistoryTradesQuery`, `useHistoryDailyChartQuery`,
`useHistoryDailyChartQuery`, `tradesToCandles`/`dailyToCandles`/`foldTick` in `candles.ts`, and
`useWsEvent("trade", …)` are all chart-library-agnostic already and are reused as-is. The only
code that changes is inside `SymbolChart.tsx`'s effects (talking to `ChartHandle` instead of
`IChartApi`/`ISeriesApi` directly) and the new `lib/chart/` adapter module.

---

## 6. Risk register

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | ECharts candlestick + `xAxis type: 'time'` friction (`apache/echarts#18675`) and data-grouping-on-zoom oddities (`#18685`) manifest against this app's actual timeframe set (1m/5m/1h/1D/All, with `time` values as both epoch-second numbers and `YYYY-MM-DD` strings on the same component) | Medium — reported against real ECharts usage, not hypothetical | High — would directly break F2/F5/F6 | **Phase 0 spike** (§7): build the candlestick + `dataZoom` + mixed time-format prototype *before* touching `SymbolChart.tsx`. If the friction reproduces, evaluate `xAxis type: 'category'` with a formatted-label workaround (the common fix cited against those issues) before abandoning ECharts. |
| R2 | ECharts candlestick data tuples are ordered `[open, close, low, high]`, not `[open, high, low, close]` — a silent transposition bug here renders a plausible-looking but wrong chart, not a crash | Medium — easy to get wrong once, easy to miss in casual visual review | High — silently wrong OHLC data is worse than a visible bug | Add an explicit, tested `toEChartsCandle(candle: Candle)` conversion function with a unit test asserting tuple order against a known-good bar; never inline the tuple construction. |
| R3 | `lazyUpdate` batching (§5.3) changes perceived update latency on the live-tick path vs. Lightweight Charts' synchronous `series.update()` | Low-medium — depends on tick frequency in practice | Medium — a visibly "laggy" live chart is a regression a trader would notice immediately | Load-test in Phase 2 against a symbol with realistic tick frequency (use the existing simulator); compare perceived latency; drop `lazyUpdate` if it's not actually needed at observed tick rates. |
| R4 | Adapter interface (§5.1) is designed against one implementation's needs (ECharts) but claims to be library-agnostic; if it accidentally leaks an ECharts-specific concept, the "swap is isolated" goal is undermined even though there's no second implementation to catch it | Low | Low-medium (design integrity, not runtime risk) | Code review checklist item in Phase 3 (§7): confirm `SymbolChart.tsx` has zero imports from `echarts` or `lightweight-charts` after the swap — only from `@/lib/chart/ChartAdapter.js`. |
| R5 | Bundle size: ECharts is a considerably larger dependency than Lightweight Charts (a known general trade-off of full-featured charting libraries vs. purpose-built ones) | Medium (near-certain some increase; magnitude unverified) | Low-medium — affects initial load, not runtime behaviour | Measure before/after with the existing Vite build's bundle analysis; use ECharts' modular imports (`echarts/core` + explicit `CandlestickChart`/`LineChart`/`GridComponent`/`DataZoomComponent` registration) rather than the full `echarts` barrel import, which is meaningfully smaller. |
| R6 | Removing `lightweight-charts` from `package.json` while other, currently-undiscovered code references its types | Low | Low (compile-time catch) | TypeScript build will fail loudly on any stray import; not a runtime risk. Grep confirmed today (§ Investigation) that `SymbolChart.tsx` is the only file importing `lightweight-charts` in `trader-gui`. |

---

## 7. Phased implementation plan

Each phase produces something independently verifiable — no phase depends on "trust me, the next
phase will make this work."

### Phase 0 — Spike: de-risk R1 (0.5 day)

Build a throwaway ECharts prototype (not integrated into the app) that renders: a candlestick
series, `dataZoom` scroll/drag zoom, and a time axis fed alternately with epoch-second numeric
`time` values (intraday) and `YYYY-MM-DD` string values (daily) — i.e., reproduce the exact
`Candle.time` duality `candles.ts` already produces. Confirm zoom/pan and tooltip behave
correctly across a timeframe switch. **Go/no-go gate**: if R1 reproduces badly enough that it's
not workaroundable within this phase's time-box, stop and re-open the library decision in §4
rather than pushing forward on a compromised foundation.

### Phase 1 — Adapter interface + ECharts implementation (0.5–1 day)

Write `src/lib/chart/ChartAdapter.ts` (interface, §5.1) and
`src/lib/chart/echartsAdapter.ts` (implementation, §5.2–§5.5), with unit tests against the
adapter in isolation (mounting into a detached DOM node via `jsdom` or similar, feeding it
synthetic `Candle[]` data, asserting on the resulting ECharts option object — not pixel output).
This phase does **not** touch `SymbolChart.tsx` yet.

### Phase 2 — Wire `SymbolChart.tsx` to the adapter (0.5–1 day)

Replace the direct `lightweight-charts` imports and calls in `SymbolChart.tsx` with the
`ChartHandle` interface, keeping the five `useEffect` blocks structurally the same (per §5.1).
Manually verify every row of the [§3 functional inventory](#3-functional-inventory-the-contract-the-replacement-must-honour)
against a running instance, including a live-tick load test against the simulator (R3).

### Phase 3 — Cleanup and removal (0.25 day)

Remove `lightweight-charts` from `package.json` and `package-lock.json`/`pnpm-lock.yaml`
(whichever this workspace uses); confirm no stray imports remain (R6, R4 checklist); run the
full `trader-gui` build and lint; measure bundle size delta (R5) and record it in this document's
changelog.

### Phase 4 — Documentation sync (0.25 day)

Update `EduMatcher-Trading-GUI.md` §16.2's heading and prose (currently
"Chart tab (TradingView Lightweight Charts v5)") and the tech-stack table row at §4 ("Charts |
TradingView Lightweight Charts v5 | …") to reflect ECharts, with a changelog entry there matching
this document's version. Cross-link back to this document.

**Total: 1.75–3 days**, consistent with the effort estimate in §10 and explicitly not the
unverifiable "~2 days" figure from the original ask — see the changelog on that point.

---

## 8. Testing strategy

- **Unit tests (new)**: the `ChartHandle` adapter's data-shaping functions —
  `toEChartsCandle()` (R2's guard), the `updateLastBar` push-vs-replace branch logic reusing
  `foldTick()`'s `isNew` flag, and the theme-mapping function — are pure and testable without a
  real DOM or ECharts instance, following the same pattern `candles.ts` already established
  (pure functions, no React, no chart library, unit-tested directly).
- **Adapter integration tests**: mount `echartsAdapter` against a detached DOM element (existing
  `trader-gui` test setup already supports component-level DOM tests) and assert the resulting
  ECharts option tree after `setData`/`setSeriesType`/`updateLastBar` calls — this catches R2
  and R4-style leakage without needing pixel comparison.
- **Manual verification pass**: the [§3 functional inventory](#3-functional-inventory-the-contract-the-replacement-must-honour)
  is the literal checklist — walk it top to bottom against a running build before calling Phase 2
  done. This includes the specific F15 check (inspect the rendered DOM for any ECharts-injected
  branding element — ECharts has none by default, but this should be a positive verification
  step, not an assumption).
- **Load verification (R3)**: drive live ticks against an active symbol via the existing
  simulator at a realistic or elevated rate and visually/programmatically confirm the chart
  keeps pace without visible lag or dropped updates.
- **No new backend/contract tests needed** — this swap touches only the GUI's chart-rendering
  layer; the REST/WebSocket contracts are unchanged (§5.6).

---

## 9. v2.0.0 candidate features (chart-adjacent)

These are **not** in scope for this swap (§1 non-goals) but are natural extensions once the
adapter boundary in §5.1 exists, since the adapter is exactly the seam where each of these would
be added without touching `SymbolChart.tsx`'s data-fetching or WebSocket logic. Listed here so
the swap's design doesn't foreclose them, and flagged for the trading-UI roadmap discussion
rather than committed to:

- **Volume pane.** `Candle.volume` is already computed by `candles.ts` and threaded through
  every code path today — it's simply never rendered. A second ECharts `bar` series in a stacked
  grid position (`gridIndex`) sharing the same time axis is the natural shape; the `ChartHandle`
  interface would need one addition (`setShowVolume(boolean)` or similar) rather than a rework.
- **Overlay indicators** (moving averages, VWAP line, Bollinger bands). ECharts supports
  multiple series sharing one axis natively, so an indicator is "one more series definition" in
  the adapter, computed from the same `Candle[]` already flowing through `setData`. This is a
  meaningfully easier lift on ECharts than it would have been on Lightweight Charts, which needs
  the separate paid "plugins" ecosystem for some indicator types.
- **Multi-day backfill for 1D/All** (already a tracked, pre-existing gap — §3). Chart-library-
  independent; this is a data-fetching change to `useHistoryDailyChartQuery` (paging backwards
  through the keyset-paginated `/history/daily` endpoint), not a charting change. Listed here only
  because it is likely to be requested alongside other chart improvements in a v2.0.0 pass, and
  is now unblocked from the "which library" question this document resolves.
- **Light theme / theme toggle.** §5.5 already designed the `ChartTheme` shape so a second
  registered theme is additive; a UI toggle would live in the existing chrome row.
- **Slider-style `dataZoom`** (a visible mini-map/brush under the chart, in addition to the
  inside-the-plot scroll/drag zoom kept for parity in §5.4). This is a genuine UX upgrade ECharts
  makes easy that Lightweight Charts does not offer at all — worth a product conversation, not an
  automatic yes, since it's new chrome rather than parity.
- **Depth-of-book visualization reusing the same adapter.** The Depth tab (§16.3 of the Trading
  GUI design) currently renders as a text/table ladder; an ECharts-based depth chart (cumulative
  bid/ask area chart) could reuse `lib/chart/`'s theming and lifecycle patterns, though it would
  need its own adapter surface, not the OHLC-shaped `ChartHandle` above.

---

## 10. Effort estimate

| Phase | Estimate |
|---|---|
| 0 — R1 spike | 0.5 day |
| 1 — Adapter + ECharts implementation | 0.5–1 day |
| 2 — Wire `SymbolChart.tsx`, functional + load verification | 0.5–1 day |
| 3 — Cleanup, dependency removal, bundle measurement | 0.25 day |
| 4 — Design-doc sync | 0.25 day |
| **Total** | **1.75–3 days** |

This is grounded in the concrete phase breakdown above, not a recollection of a prior estimate —
there is no record of a previously-given "~2 days" figure anywhere in this project's design docs
or memory (see changelog). The range's width mostly reflects R1 (Phase 0's go/no-go gate) and R3
(load-verification outcome) — both are things this plan tests early rather than assumes.

---

## Changelog

- **1.0.0 (2026-08-16)** — Initial design. Written after a comparative research pass (Apache
  ECharts vs. ApexCharts vs. react-financial-charts) confirmed: (1) Lightweight Charts' on-chart
  logo/backlink is a self-imposed Apache-2.0 attribution clause specific to that library, not a
  general Apache-2.0 requirement; (2) no record exists anywhere in this project's design docs or
  memory of a previously-quoted "~2 days" estimate for this swap — this document's §10 estimate
  is derived independently from the phase plan in §7, and happens to land in a similar range,
  which is a useful sanity check but not the basis for the number; (3) Apache ECharts was selected
  over ApexCharts primarily on crosshair fidelity (F7) and a live-update-safety signal (F9) — see
  §4 for the full decision record.

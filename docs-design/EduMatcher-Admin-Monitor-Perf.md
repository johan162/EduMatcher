# pm-trader admin Monitor Log / System Dashboard performance (WP-MP01)

## Problem

Logged in as ADMIN, opening *Monitor Log* took 15–25 s and the UI thread was
saturated by the live feed; the *System Dashboard* event list was also heavy.

## Root causes (found by reading, `apps/web` of `web-apps/trader-gui`)

1. `useMonitorStore.ingest` copied the whole cross-gateway `orders` map for every
   `order.*` frame, and terminal orders were never evicted — O(N) per event, N
   grows without bound.
2. One `set()` (and one React render of every subscriber) per WebSocket frame.
3. Monitor Log rendered all 1000 rows, unmemoized, on every event.
4. Dashboard re-rendered the whole page per event (subscribed to `events` + `orders`).

## Work items (all one WP)

- [x] M1 Batch ingestion: live frames queue and flush once per `FLUSH_MS` (250 ms); snapshot flushes first.
- [x] M2 Bounded order map: one copy per batch, oldest terminal orders evicted above `MAX_ORDERS`; evicted orders fall back to the audit trail (`AdminOrderDetailModal` already reads `/admin/orders/{id}` only).
- [x] M3 Monitor Log virtualized (`@tanstack/react-virtual`, spacer rows as in `MarketTable`) + memoized rows.
- [x] M4 Dashboard: `RecentEventsFeed` own component; page subscribes to derived counts only.
- [x] M5 Tests: batching, eviction, virtualized rendering, dashboard feed; existing tests updated for `flush()`.
- [x] M6 Gates: vitest, tsc, (no eslint configured; `npm run typecheck`). Verified 2026-10-30: 516 vitest pass, tsc clean. Not yet measured in a browser against a live sim..

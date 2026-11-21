# Index intraday resolution — workplan

Status: WP-IIR01 done 2026-11-21 (uncommitted).

## 1. Finding

The terminal-gui Index View shows the 1D and 5D presets as intraday charts,
built from `/history/index-snapshots` (one row per `index.update`). The web
client asks for `limit=5000`, oldest first, and never follows `next_cursor`.

pm-index publishes far more often than that. The sim on 2026-11-21 stored
22,755 EDU50 rows between 05:33 and 15:05 UTC. Row 5,000 is at 09:54 UTC, so
the 1D chart showed real data only for the first ~4.5 hours. `withLiveTail`
then drew a straight line from 09:54 to the live level at the close (990.12),
hiding the afternoon in which most of the −10 % move happened. 5D was worse:
5,000 rows from five days back covers part of the first day only.

A second bug, found while implementing: the web `IndexSnapshotRow` type
named the timestamp field `timestamp`, but pm-stats sends `ts`. So
`snapshotSeries` parsed every row as NaN and dropped it, and the 1D/5D charts
showed **only** the live tail. Fixed in the same WP (type renamed to `ts`,
regression test on a real pm-stats row).

## 2. What real exchanges do

Index providers calculate and disseminate index levels in real time during
the session (typically every 1–15 s), and publish an official
open/high/low/close per day. Charting front-ends never plot raw ticks: they
use ~1-minute bars for a 1-day view, 5–30-minute bars for a 5-day view, and
daily bars beyond that. The terminal's presets already follow this split;
only the intraday data path was broken.

## 3. Design

- `GET /api/v1/history/index-snapshots` gains an optional `interval` query
  parameter: `1m`, `5m`, `15m` or `1h`. Omitted means raw ticks, as before.
- With `interval`, the reply holds **one row per time bucket: the last
  snapshot in that bucket** (the bar's close — what a line chart plots).
  The row shape is unchanged, and `ts` is that snapshot's real timestamp,
  not the bucket start, so the response model and every consumer stay as
  they are.
- Buckets are aligned to multiples of the interval in Unix time (UTC). For
  every whole-hour session timezone this equals local alignment; a
  half-hour-offset timezone would get `1h` buckets at :30 local. Acceptable
  for a chart.
- Bucketing is done in SQL (`ROW_NUMBER() OVER (PARTITION BY bucket ...)`).
  Filters (`date`/`from`/`to`/`after`) apply before bucketing.
- Pagination is unchanged: the cursor is the `(ts, rowid)` of the page's
  last row, which is the last row of its bucket, so the next page starts in
  the next bucket. (A still-filling live bucket can appear again on a later
  page with a later `ts`; order stays ascending.)
- `pm-stats-cli index-snapshots --interval {1m,5m,15m,1h}` mirrors the
  endpoint, as the endpoint's docstring promises CLI parity.
- terminal-gui: 1D requests `interval=1m` (~570 rows for a sim session),
  5D requests `interval=5m` (~115 rows a day). Both are far below the 5,000
  page cap.

Considered and rejected: the client follows the cursor and buckets itself.
That is ~23k rows/day (~110k for 5D) re-downloaded every 5 s while the view
is open.

## 4. WP-IIR01 — server-side bucketing for intraday index levels

Tests first:

1. `query_index_snapshots(..., interval=...)` returns the last row per
   bucket, in order, isolates by index, honours the time window, and
   paginates without gaps or duplicates.
2. A day with more than 5,000 raw rows returns the whole session at `1m`
   (first and last bucket present) — the regression for §1.
3. Unknown interval → `ValueError` from the query.
4. API endpoint passes `interval` through; CLI `--interval` works.
5. terminal-gui: the 1D/5D presets map to `1m`/`5m`, and `api.indexSnapshots`
   sends the parameter.

Then: implement in `stats/query.py`, `api_gateway/routers/history.py`,
`stats/cli.py`, terminal-gui `index-series.ts` / `api.ts` / `IndexView.tsx`;
update the REST spec and the statistics chapter.

Done when: all of the above pass, the full Python suite + `make _check`
+ terminal-gui tests are clean, and a query against the 2026-11-21 sim DB
at `1m` covers 05:33–15:05.

### Result (2026-11-21)

- 2026-11-21 sim DB at `1m`: 393 rows, 05:33:04 → 15:05:00, last level
  990.1178; ~40 ms. `5m`: 81 rows. Raw ticks still available without
  `interval`.
- Full pytest suite: 15,237 passed after regenerating `spec/rest/openapi.json`
  (`make openapi`) and the shell completions (`make completion`);
  `make _check` clean. terminal-gui: typecheck, build and 760 vitest tests
  pass (prettier warnings in `help.ts`, `useAutoPaging.ts`, `chart-time.ts`
  predate this WP).
- `make test-e2e`: the exchange tests skipped, because the running sim held
  the ports. Not affected by this change.
- Deploy note: pm-api-gwy must be restarted together with the terminal
  bridge/web. An old gateway ignores the unknown `interval` and returns raw
  ticks, so 1D would again stop at the first 5,000 rows.

# Statistics and Reporting

!!! note "Learning objectives"
    After reading this page you will understand:

    - How EduMatcher defines a **trading date**, and why it is not the UTC date
    - How to record market and exchange index statistics continuously using `pm-stats`
    - How to query statistics data without writing SQL using `pm-stats-cli`
      - Common analyst workflows: end-of-day summaries, intraday price analysis, trade analysis, index level history, and order lifecycle investigation
    - How to export statistics for external analysis (spreadsheets, BI tools)
    - How the statistics system integrates with other tools like `pm-ticker`
    - How to troubleshoot and validate statistics data



## Overview — Statistics Architecture

EduMatcher has a two-part statistics system:

| Component | Role | Type | Purpose |
|-----------|------|------|---------|
| **pm-stats** | Subscriber | Long-running process | Listens to trades, book updates, index level updates, and private order lifecycle events; writes OHLCV, snapshots, trade log, index history, and `order_events` to `data/stats.db` |
| **pm-stats-cli** | Query tool | One-shot CLI | Reads from `data/stats.db` and prints human-friendly or machine-readable output without SQL |

This split keeps the recorder separate from the query interface, so you can:

- Start and stop `pm-stats-cli` at any time without affecting the live recorder
- Reload historical data after the engine restarts
- Build reports, dashboards, and automated analysis without needing live connections
- Keep the database read-only for auditing and compliance



## Dates and Timestamps — read this first

Every date question in `stats.db` has two possible answers, and mixing them up
is the easiest way to produce a report that is quietly wrong. The database
uses two distinct concepts:

| Concept | Where it appears | What it is |
|---------|------------------|------------|
| **Instant** | every `ts` column | An ISO-8601 UTC timestamp with an explicit `+00:00` offset, e.g. `2026-06-14T09:00:01.000+00:00` |
| **Trading date** | the `date` column of `daily_stats` and `index_daily_stats` | The calendar date **in the exchange's session timezone** that an instant belongs to, e.g. `2026-06-14` |

The trading date is deliberately *not* the UTC date. An exchange's daily
rollup has to align to the calendar day its participants actually traded. A
session that runs into the evening — or any session that straddles 00:00 UTC —
would otherwise be split across two `date` values, and the daily summary would
no longer describe a single trading session.

### Setting the session timezone

Set it once, on the recorder:

```bash
pm-stats --timezone Europe/Stockholm
```

`pm-stats` writes that value into the database's `stats_meta` table, and every
reader — `pm-stats-cli`, `pm-ticker`, the API Gateway — picks it up from there.
**Readers need no timezone configuration at all**, and cannot disagree with the
recorder about which trading day a `--date` refers to:

```bash
pm-stats-cli daily --date 2026-06-14   # resolves in Europe/Stockholm automatically
```

Two guardrails back this up:

- Restarting `pm-stats` against an existing database with a *different*
  `--timezone` is **refused**, because the `date` column would then mean two
  different things within one file. Use a different `--db` instead.
- Passing `--timezone` to a reader overrides the recorded value and prints a
  warning when the two disagree:

  ```console
  $ pm-stats-cli --timezone UTC daily --date 2026-06-14
  [WARN] --timezone UTC differs from the session timezone this database was
         recorded with (Europe/Stockholm); --date will resolve to a different
         trading day than pm-stats used
  ```

!!! note "`pm-clearing` still needs its own `--timezone`"
    `pm-clearing` keeps a separate database and takes the same flag with the
    same meaning for `trade_events.trade_date`. Give it the same value you
    gave `pm-stats`, or `daily_stats.volume` will not reconcile against
    `gateway_daily_summary.traded_qty` — that pairing spans two files and is
    not checked automatically.

    If your exchange runs in UTC, leave everything at the default and none of
    this applies.

### Inspecting what a database was recorded with

`stats_meta` is a plain key/value table:

```console
$ sqlite3 data/stats.db "SELECT key, value FROM stats_meta"
recorder|pm-stats
session_timezone|Europe/Stockholm
snapshot_interval_sec|900.0
```

The schema version is in `PRAGMA user_version`:

```console
$ sqlite3 data/stats.db "PRAGMA user_version"
3
```

The version is bumped both when the table definitions change and when the
*meaning* of stored values changes — version 2 introduced the distinct combo,
OCO and quote `event_type` values, which the DDL alone cannot express, and
version 3 added `feed_gaps` and widened `trade_log`'s primary key.

`pm-stats` refuses to open a database whose `user_version` does not match the
build, rather than writing new-format rows into an old-format file. If you hit
that, move or delete the file and let `pm-stats` create a fresh one.

### What `--date` means

`--date 2026-06-14` always means "the 2026-06-14 trading day". For
`daily_stats` and `index_daily_stats` that is a direct match on the `date`
column. For the timestamped tables (`trade_log`, `price_snapshots`,
`order_events`, `index_level_snapshots`) it is resolved to the UTC instant
range that trading day covers:

```text
--timezone Europe/Stockholm --date 2026-06-14
    →  ts >= 2026-06-13T22:00:00+00:00
   and  ts <  2026-06-14T22:00:00+00:00
```

Daylight-saving transitions are handled: a trading day may be 23 or 25 hours
long, and the range follows local midnight either side.

### What `--from` / `--to` accept

`--from` and `--to` are **instants**, and all of these are accepted:

| Form | Example | Interpreted as |
|------|---------|----------------|
| UTC with `Z` | `2026-06-14T09:00:00Z` | 09:00 UTC |
| Explicit offset | `2026-06-14T11:00:00+02:00` | 09:00 UTC |
| No offset | `2026-06-14T11:00:00` | 11:00 **session-local**, so 09:00 UTC in Stockholm |

Bounds are compared as instants, not as text, so the three rows above select
exactly the same trades. Both bounds are inclusive, and they are precise: a
`--to 2026-06-14T16:30:00` bound excludes a trade at `16:30:00.500`, because
that trade genuinely happened after the bound. Give the bound sub-second
precision if you want to include it.



## Data Folder Location

The location where `pm-stats` writes `data/stats.db` depends on how EduMatcher is installed:

| Running mode                                | Default location                     | Environment override  |
|---------------------------------------------|--------------------------------------|-----------------------|
| **Source checkout** (`poetry run pm-stats`) | `<repo>/src/data/stats.db`           | `EDUMATCHER_DATA_DIR` |
| **Installed** (`pm-stats` on PATH)          | `~/.local/share/edumatcher/stats.db` | `EDUMATCHER_DATA_DIR` |

**Set the data directory in your shell profile** (`~/.zshrc` or `~/.bashrc`) to override either default:

```bash
export EDUMATCHER_DATA_DIR="$HOME/.local/share/edumatcher"
```

Then every `pm-*` command — including `pm-stats` and `pm-stats-cli` — will use that location automatically:

```bash
# Uses $EDUMATCHER_DATA_DIR/stats.db
pm-stats
pm-stats-cli daily
```

**Common use cases:**

| Scenario                                       | Environment variable                  | Purpose                                    |
|------------------------------------------------|---------------------------------------|--------------------------------------------|
| **Installed user** (default for pipx)          | (unset) → `~/.local/share/edumatcher` | Persistent user data folder                |
| **Source checkout** (default for `poetry run`) | (unset) → `<repo>/src/data/`          | Development environment                    |
| **Isolated sessions**                          | `~/sessions/morning`                  | Per-session isolation for demos or testing |
| **Shared network**                             | `/mnt/shared/trading/`                | Shared data across machines                |

**Example: Per-session isolation**

```bash
# Session 1: Morning trading (uses custom data directory)
export EDUMATCHER_DATA_DIR="$HOME/sessions/morning"
poetry run pm-engine
poetry run pm-stats
poetry run pm-stats-cli daily

# Session 2: Afternoon trading (different database)
export EDUMATCHER_DATA_DIR="$HOME/sessions/afternoon"
poetry run pm-engine
poetry run pm-stats
```

Each session maintains its own `stats.db`, so historical data doesn't mix.

!!! tip "Finding your data"
    To see where `pm-stats` is writing data:
    ```bash
    echo $EDUMATCHER_DATA_DIR  # Shows override if set, otherwise empty
    poetry run python -c "from edumatcher.config import DATA_DIR; print(DATA_DIR)"  # Shows resolved path
    ls -la $EDUMATCHER_DATA_DIR/stats.db  # If env var is set
    ```

See [Processes — Environment variables](170-processes.md#environment-variables) for full details on `EDUMATCHER_DATA_DIR`.



## The Statistics Database Schema

All statistics are stored in `data/stats.db`, a SQLite 3 database with seven data
tables plus a metadata table.

### `stats_meta`

Key/value provenance for the file, written by `pm-stats` on every start.

| Key | Description |
|-----|-------------|
| `session_timezone` | The IANA timezone the `date` columns are expressed in. Readers resolve this automatically |
| `snapshot_interval_sec` | The `--snapshot-interval` in force, so a consumer can tell a sparse series from a coarse one |
| `recorder` | The process that wrote the file (`pm-stats`) |

The schema version lives in `PRAGMA user_version` rather than in this table, so
it can be checked before any query is attempted.

### `daily_stats`

Aggregated OHLCV (open, high, low, close, volume) and related metrics for each symbol per trading day.

**Primary key**: `(date, symbol)` — one row per symbol per trading day, upserted as trades arrive.

| Column                | Type    | Null? | Description                                                       |
|-----------------------|---------|-------|-------------------------------------------------------------------|
| `date`                | TEXT    | no    | **Trading date** `YYYY-MM-DD` in the session timezone             |
| `symbol`              | TEXT    | no    | Instrument ticker                                                 |
| `open_price`          | REAL    | yes   | First trade price of the day; null if the day had no trades       |
| `high_price`          | REAL    | yes   | Highest trade price; null if the day had no trades                |
| `low_price`           | REAL    | yes   | Lowest trade price; null if the day had no trades                 |
| `close_price`         | REAL    | yes   | Last trade price; null if the day had no trades                   |
| `volume`              | INTEGER | no    | Total traded quantity; `0` if the day had no trades               |
| `trade_count`         | INTEGER | no    | Number of trades; `0` if the day had no trades                    |
| `turnover`            | REAL    | no    | Traded notional, `sum(price × quantity)`; `0` if the day had no trades |
| `vwap`                | REAL    | yes   | Volume-weighted average price; null if the day had no trades      |
| `open_bid`            | REAL    | yes   | Best bid at first book update of the day                          |
| `open_ask`            | REAL    | yes   | Best ask at first book update of the day                          |
| `close_bid`           | REAL    | yes   | Best bid at engine shutdown                                       |
| `close_ask`           | REAL    | yes   | Best ask at engine shutdown                                       |
| `largest_trade_qty`   | INTEGER | yes   | Quantity of the single largest trade. Note this is `0`, not null, on a day with no trades |
| `largest_trade_price` | REAL    | yes   | Price of the single largest trade; null on a day with no trades   |

**Use case**: End-of-day summaries, daily trend analysis, multi-day performance tracking.

!!! note "Prices are unadjusted"
    `daily_stats` carries no corporate-action awareness. Prices are exactly
    what printed on the day, with no split or dividend adjustment and no
    marker indicating that an adjustment event occurred. A multi-day series
    that spans a corporate action is therefore discontinuous, and returns
    computed across it will be wrong. `pm-index` maintains the corporate-action
    audit record — see [Market Index](150-market-index.md).

### `price_snapshots`

Intraday mid-price, bid/ask, and percentage-change history, recorded at most once per interval per symbol (default: 15 minutes).

**Primary key**: `(ts, symbol)`.
**Index**: `(symbol, ts)`.

| Column       | Type | Null? | Description                                                                     |
|--------------|------|-------|---------------------------------------------------------------------------------|
| `ts`         | TEXT | no    | ISO-8601 UTC instant, **second** precision, e.g. `2026-06-14T09:00:00+00:00`     |
| `symbol`     | TEXT | no    | Instrument ticker                                                               |
| `mid_price`  | REAL | yes   | See the fallback chain below — **not always a true mid**                        |
| `best_bid`   | REAL | yes   | Best bid at snapshot time; null if the bid side was empty                       |
| `best_ask`   | REAL | yes   | Best ask at snapshot time; null if the ask side was empty                       |
| `pct_change` | REAL | yes   | Percentage change of `mid_price` from the previous snapshot (`1.25` means +1.25 %); null on the first snapshot |

`mid_price` is resolved in this order, and only the first case is a genuine mid-price:

| Book state | `mid_price` |
|------------|-------------|
| Both sides present | `(best_bid + best_ask) / 2` |
| Bid only | `best_bid` |
| Ask only | `best_ask` |
| Neither, but a last trade exists | `last_price` |
| Nothing available | null |

!!! warning "`mid_price` on a one-sided book"
    On a one-sided book `mid_price` is simply whichever side exists, so a
    series can silently mix true mid-prices with single-sided quotes. Because
    `pct_change` is computed from consecutive `mid_price` values, a book
    flipping between two-sided and one-sided produces a percentage move that
    reflects the change in *definition*, not a change in the market. Check
    `best_bid`/`best_ask` for null before treating `pct_change` as a return.

    Related: `pct_change` compares against the previous snapshot that had a
    usable `mid_price`. If an intervening snapshot had none, the percentage
    silently spans more than one interval.

### `trade_log`

Append-only record of every matched trade — no aggregation, one row per trade.

**Primary key**: `(trade_id, ts)`. Inserts are `OR IGNORE`, so a repeated delivery of the same trade — same id *and* same timestamp — is deduplicated.

!!! note "Why the key is composite"
    `trade_id` is a counter that **restarts at 1 on every engine run**, not a
    globally unique identifier. Keyed on `trade_id` alone, the first trade of
    a restarted engine would collide with the first trade of the previous run
    and be silently discarded, understating volume for the rest of the day.
    Including `ts` keeps a post-restart id reuse as a distinct row while still
    deduplicating a genuine duplicate delivery. `pm-clearing` records the same
    defect against its own archive as finding CL-C1.

| Column            | Type    | Null? | Description                                                          |
|-------------------|---------|-------|----------------------------------------------------------------------|
| `ts`              | TEXT    | no    | ISO-8601 UTC instant, **millisecond** precision. This is the **engine's** trade timestamp |
| `trade_id`        | TEXT    | no    | Engine trade counter, unique **within one engine run** only           |
| `symbol`          | TEXT    | no    | Instrument ticker                                                    |
| `price`           | REAL    | no    | Execution price                                                      |
| `quantity`        | INTEGER | no    | Matched quantity                                                     |
| `buy_gateway_id`  | TEXT    | yes   | Gateway that submitted the buy order                                 |
| `sell_gateway_id` | TEXT    | yes   | Gateway that submitted the sell order                                |
| `aggressor_side`  | TEXT    | yes   | `BUY` or `SELL` for a continuous match; `AUCTION` for an uncross print |

**Index**: `(symbol, ts)`.

`aggressor_side` is mirrored from the engine payload verbatim:

| Value | Meaning |
|-------|---------|
| `BUY` | An incoming buy order swept resting sell liquidity |
| `SELL` | An incoming sell order swept resting buy liquidity |
| `AUCTION` | An opening or closing uncross print — both sides were resting, so there is no true aggressor |

This is what makes trade classification and order-flow imbalance possible, and
it is also the only way to separate auction prints from continuous ones:

```bash
# Continuous-session buy-side pressure for one trading day
pm-stats-cli --format json trades --symbol AAPL --date 2026-06-14 --limit 100000 \
  | python3 -c "
import json, sys, collections
rows = json.load(sys.stdin)
by_side = collections.Counter()
for r in rows:
    by_side[r['aggressor_side']] += r['quantity']
print(dict(by_side))
"
```

**Use case**: Trade-by-trade analysis, order-flow imbalance, separating auction
from continuous volume, audit trails.

### `feed_gaps`

Trades the recorder can prove it never received.

**Primary key**: `seq` (`AUTOINCREMENT`).
**Index**: `(ts)`.

| Column          | Type    | Description                                                     |
|-----------------|---------|-----------------------------------------------------------------|
| `seq`           | INTEGER | Monotonic local sequence                                        |
| `ts`            | TEXT    | UTC instant of the trade that revealed the gap                  |
| `stream`        | TEXT    | Which feed the gap was detected on (currently `trade.executed`) |
| `expected_id`   | INTEGER | The trade id expected next                                      |
| `received_id`   | INTEGER | The trade id that actually arrived                              |
| `missing_count` | INTEGER | How many trades are unaccounted for between them                |

ZeroMQ PUB/SUB drops messages silently once a subscriber falls behind its
high-water mark, so without this table a session that lost trades is
indistinguishable from a quiet one. Because the engine numbers trades with a
monotonic counter, a jump in that counter is direct evidence of loss, and each
jump is written here inside the same transaction as the trade that revealed it.

**Use case**: answering "is this session's data complete?" before trusting a
volume, VWAP or turnover figure.

!!! warning "What gap detection does and does not cover"
    **Covers**: the `trade.executed` stream — the one where loss corrupts
    `volume`, `turnover` and `vwap`.

    **Does not cover**: `book.*`, `order.*`, `combo.*`, `oco.*`, `quote.*` and
    `index.update`. None of those carry a sequence number, so loss on them is
    still undetectable. A missed book update costs at most one snapshot; a
    missed order event leaves a hole in a lifecycle trail.

    An empty `feed_gaps` therefore means "no loss was *detected*", which is a
    weaker claim than "nothing was lost". Closing the remaining streams needs
    a publisher-side sequence number in the engine.

### `order_events`

Append-only order lifecycle history captured from private engine topics. This table is used by API Gateway history endpoints to reconstruct per-gateway order, fill, cancel, amend, combo, OCO, and quote events.

**Primary key**: `seq` (`AUTOINCREMENT`).
**Indexes**: `(order_id)`, `(gateway_id, ts)`, `(symbol, ts)`, `(event_type, ts)`.

!!! warning "`order_events.ts` is a different clock from `trade_log.ts`"
    `order_events.ts` is the wall-clock instant at which **`pm-stats` recorded**
    the event. `trade_log.ts` is the instant the **engine** stamped on the
    trade. The two therefore cannot be merged into one ordered timeline: a
    `FILL` row can carry a timestamp *earlier or later* than the `trade_log`
    row for the same execution, depending on delivery latency. Within
    `order_events` alone, order by `seq`, which is monotonic and reliable.

| Column            | Type    | Description                                                                                                          |
|-------------------|---------|----------------------------------------------------------------------------------------------------------------------|
| `seq`             | INTEGER | Monotonic local sequence assigned by SQLite for stable event ordering                                                |
| `ts`              | TEXT    | ISO-8601 timestamp (UTC, millisecond precision) when `pm-stats` recorded the event                                   |
| `event_type`      | TEXT    | Normalized event category — see the full value table below                                                            |
| `order_id`        | TEXT    | Order-like identifier; for combo/OCO/quote events this may be `combo_id`, `oco_id`, or `quote_id`                    |
| `gateway_id`      | TEXT    | Gateway identity that owns the private event                                                                         |
| `symbol`          | TEXT    | Instrument ticker when present in the event payload                                                                  |
| `side`            | TEXT    | `BUY` or `SELL` when applicable                                                                                      |
| `order_type`      | TEXT    | Order type from the original order or lifecycle event                                                                |
| `tif`             | TEXT    | Time-in-force value when present                                                                                     |
| `price`           | REAL    | Limit/order price when present                                                                                       |
| `quantity`        | INTEGER | Original or submitted quantity when present                                                                          |
| `remaining_qty`   | INTEGER | Quantity remaining after the event when provided by the engine                                                       |
| `status`          | TEXT    | Engine status value when present                                                                                     |
| `fill_price`      | REAL    | Execution price for fill events                                                                                      |
| `fill_qty`        | INTEGER | Executed quantity for fill events                                                                                    |
| `trade_id`        | TEXT    | Trade identifier linked to a fill event                                                                              |
| `reason`          | TEXT    | Rejection, cancel, expire, or status reason when provided                                                            |
| `client_order_id` | TEXT    | Client-supplied order identifier when present                                                                        |
| `combo_parent_id` | TEXT    | Parent combo identifier for combo child events                                                                       |
| `oco_group_id`    | TEXT    | OCO group identifier for linked order events                                                                         |
| `priority_reset`  | INTEGER | `1` when an amend reset queue priority, `0` when it did not, null when not applicable                                |

**Use case**: API Gateway order history, support investigations, per-gateway audit trails, fill-only history, and lifecycle reconstruction for a single order ID.

#### `event_type` values

Every value the recorder can write, and the engine topic it comes from:

| `event_type` | Source topic | Meaning |
|--------------|--------------|---------|
| `ACK` | `order.ack.*` with `accepted: true` | Order accepted |
| `REJECT` | `order.ack.*` with `accepted: false` | Order rejected |
| `FILL` | `order.fill.*` | Execution against the order |
| `AMEND` | `order.amended.*` | Order amended |
| `CANCEL` | `order.cancelled.*` | Order cancelled |
| `EXPIRE` | `order.expired.*` | Order expired |
| `COMBO_ACK` | `combo.ack.*` with `accepted: true` | Combo accepted |
| `COMBO_REJECT` | `combo.ack.*` with `accepted: false` | Combo rejected |
| `COMBO_STATUS` | `combo.status.*` | Combo status update |
| `OCO_ACK` | `oco.ack.*` with `accepted: true` | OCO pair accepted |
| `OCO_REJECT` | `oco.ack.*` with `accepted: false` | OCO pair rejected |
| `OCO_CANCEL` | `oco.cancelled.*` | One leg of an OCO pair cancelled |
| `QUOTE_ACK` | `quote.ack.*` with `accepted: true` | Quote accepted |
| `QUOTE_REJECT` | `quote.ack.*` with `accepted: false` | Quote rejected |
| `QUOTE_STATUS` | `quote.status.*` | Quote status update |
| `UNKNOWN` | any ack topic missing its `accepted` flag | See the note below |
| `EVENT` | any other subscribed private topic | Unclassified |

Combo, OCO and quote events each carry their own accept / reject / cancel /
status value rather than a single family name, so a rejected combo is
distinguishable from an accepted one and `oco.cancelled` is findable as a
cancellation. Filters are validated against this list — `pm-stats-cli` rejects
an unknown `--event-type` at parse time and the API returns `422`, rather than
silently returning an empty page.

!!! note "`UNKNOWN` means the engine did not say"
    Every ack-style payload carries an `accepted` flag, so its absence
    indicates a bug or a corrupted message. When that happens the recorder
    writes `UNKNOWN` and logs at `ERROR`, rather than defaulting to `REJECT` —
    recording a rejection the engine never asserted would put a fabricated
    fact into the audit trail. If you see `UNKNOWN` rows, check the `pm-stats`
    log for the topic that produced them.

### `index_daily_stats`

Aggregated daily OHLC (open, high, low, close) for each configured exchange index, one row per `(date, index_id)`, upserted on every `index.update` event `pm-stats` receives from `pm-index`.

**Primary key**: `(date, index_id)`.
**Index**: `(index_id, date)`.

| Column                 | Type    | Description                                          |
|------------------------|---------|-------------------------------------------------------|
| `date`                 | TEXT    | **Trading date** `YYYY-MM-DD` in the session timezone   |
| `index_id`             | TEXT    | Index identifier (e.g. `EDU100`)                        |
| `open_level`           | REAL    | Index level at the first update of the day              |
| `high_level`           | REAL    | Highest index level seen during the day                 |
| `low_level`            | REAL    | Lowest index level seen during the day                  |
| `close_level`          | REAL    | Index level at the *most recently received* update — see the finality note below |
| `close_session_state`  | TEXT    | Session state as of that most recent update (e.g. `CONTINUOUS`, `CLOSED`) — the key to knowing whether `close_level` is final |
| `open_aggregate_cap`   | REAL    | Aggregate constituent market cap at the first update     |
| `close_aggregate_cap`  | REAL    | Aggregate constituent market cap at the most recent update |
| `update_count`         | INTEGER | Number of `index.update` events folded into this day's row |

**Use case**: Daily index trend analysis, comparing index performance across trading dates, spotting days with unusually few updates (a thin `update_count` may indicate a quiet index or a connectivity gap), and — the most common ask — looking up an index's official end-of-day (EOD) closing level for a chosen date.

**Note**: an index has no independent trades or volume of its own — its level is computed from constituent prices — so this table has no `volume`/`trade_count`/`vwap` columns the way `daily_stats` does.

!!! warning "`close_level` is only final once `close_session_state` is `CLOSED`"
    `close_level` (and `close_session_state`) are updated on *every* `index.update` tick — they always reflect whatever was most recently received for that date, not necessarily the actual end-of-day print. For any **past** date this is a non-issue: no more updates can arrive for a date that has rolled over, so `close_level` is guaranteed final. But if you query **today's** date while the session is still open, `close_level` is a live "last level so far" that will keep changing intraday, and `close_session_state` will show whatever state the market is currently in (e.g. `CONTINUOUS`), not `CLOSED`.

    To reliably get the true EOD close for a given date:

    - **Simplest**: query a date that has already ended — `close_level` for a prior date is always final.
    - **To confirm today's row is final**: check that `close_session_state == "CLOSED"`. `pm-index` sets this via a forced publish when the session transitions to `CLOSED`, so once you see it, `close_level` for that date will not change again.

    See [Getting the EOD index level for a date](#getting-the-eod-index-level-for-a-date) below for a worked example.

### `index_level_snapshots`

Time series of every index level update received from `pm-index`, one row per `index.update` event (no additional throttling in `pm-stats` — `pm-index` already rate-limits its own publications via `publish_interval_sec` before it ever sends one).

**Primary key**: `(ts, index_id)`. Inserts are `OR IGNORE`, so two updates for one index landing in the same millisecond retain only the first.
**Index**: `(index_id, ts)`.

| Column          | Type | Description                                                          |
|-----------------|------|------------------------------------------------------------------------|
| `ts`            | TEXT | ISO-8601 UTC instant, millisecond precision                            |
| `index_id`      | TEXT | Index identifier                                                        |
| `level`         | REAL | Current index level at this update                                      |
| `aggregate_cap` | REAL | Aggregate constituent market cap at this update                         |
| `divisor`       | REAL | Index divisor in effect at this update                                  |
| `session_state` | TEXT | Index session state at this update — see the full set below            |
| `day_open`      | REAL | Day's opening level, when known at this update                         |
| `day_high`      | REAL | Day's high level so far, when known at this update                     |
| `day_low`       | REAL | Day's low level so far, when known at this update                      |

`session_state` (in both this table and `index_daily_stats.close_session_state`)
takes exactly one of the five values from the engine's session model:

| Value | Meaning |
|-------|---------|
| `PRE_OPEN` | Orders accepted, no matching |
| `OPENING_AUCTION` | Auction collection before the opening uncross |
| `CONTINUOUS` | Normal continuous matching |
| `CLOSING_AUCTION` | Auction collection before the closing uncross |
| `CLOSED` | Market closed — **the only value that makes `close_level` final** |

See [Session Scheduling and Auctions](080-session-scheduling.md#session-phases)
for the full phase model.

**Use case**: Intraday index charting, index-level history queries for `pm-terminal`-style viewers, reconstructing an index's level trajectory over any time window.

**Why this table exists**: `pm-index` also keeps its own append-only JSONL history file (`data/indexes/<id>_history.jsonl`) for corporate-action, delisting, and constituent-change audit records — that file remains the source of truth for those event types and is unaffected by this table. But that file is not indexed and every query against it is a full linear scan, which does not scale as a session runs longer. `index_level_snapshots` exists specifically to give the level time series (the data an index chart needs) a queryable, indexed home, the same way `price_snapshots` already does for instrument prices — it does not replace or duplicate the JSONL file's audit role.



## Running the Statistics Recorder

Start `pm-stats` as a background process after the engine starts:

```bash
# Terminal 1: Start the engine
pm-engine --verbose

# Terminal 2: Start statistics recorder (after engine is ready)
pm-stats
```

`pm-stats` will:

1. Connect as a subscriber to the engine's PUB socket (:5556)
2. Connect as a second, independent subscriber to `pm-index`'s own PUB socket (:5558 by default) for `index.update` events — `pm-index` binds a separate endpoint from the engine, so this is a distinct ZMQ connection, not an additional topic filter on the engine socket
3. Wait briefly for ZMQ subscriptions to propagate, then request the symbol list from the engine via PUSH (:5555); on receipt, request a current book snapshot per symbol so opening bid/ask and initial price rows are captured even before new trading activity
4. Begin recording trades to `daily_stats` as they execute
5. Write intraday snapshots every 15 minutes
6. Write trade-by-trade records to `trade_log` immediately
7. Write private order lifecycle events to `order_events`
8. Write every received index update to `index_level_snapshots` and upsert the day's rollup into `index_daily_stats` — no exchange indexes configured means no `index.update` traffic and these two tables simply stay empty, which is expected and not an error
9. At engine shutdown, record the final close bid/ask to `daily_stats`

**Startup options:**

| Flag                     | Default         | Description                                                                            |
|--------------------------|-----------------|----------------------------------------------------------------------------------------|
| `--db`                   | `data/stats.db` | Custom statistics database path                                                        |
| `--timezone`             | `UTC`           | Exchange session timezone defining the trading date written to the `date` columns (IANA name). Recorded into the database, so readers pick it up automatically. Restarting against an existing database with a different value is refused |
| `--snapshot-interval`    | `900` (15 min)  | Seconds between `price_snapshots` rows per symbol. Lower values give finer intraday resolution at the cost of more database writes. Values below 1 second are not useful — `price_snapshots` is keyed to second precision, so sub-second rows collide and are dropped |
| `--sql-trace`            | off             | Log executed SQLite statements from the stats writer connection — useful for debugging what `pm-stats` is actually writing |
| `--log-level`            | `WARNING`       | Explicit level: `CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG`                       |
| `-v`, `--verbose`        | off             | Increase verbosity (`-v` → `INFO`, `-vv` → `DEBUG`)                                   |
| `-q`, `--quiet`          | off             | Reduce output to warnings/errors                                                       |
| `--log-target`           | `server`        | Where this process's own operational log records go: `server` (auto-detected `pm-log-srv`), `stdout`, or `file` |
| `--log-file`             | —               | Operational log file path — required when `--log-target file`                          |
| `--log-failover-timeout` | `30`            | Grace window in seconds before falling back to a local log file once `pm-log-srv` becomes unreachable |

Use `--db` if you want to record into a different location:

```bash
pm-stats --db /tmp/session_stats.db
```

Use `--snapshot-interval` to change how often intraday price snapshots are recorded:

```bash
pm-stats --snapshot-interval 60    # one-minute snapshots
pm-stats --snapshot-interval 300   # five-minute snapshots
pm-stats --snapshot-interval 3600  # hourly snapshots
```

**Start order**: ZeroMQ `connect()` is asynchronous and retries indefinitely, so
starting `pm-stats` before the engine does not raise an error — but the startup
symbol request is sent once, shortly after launch, and is lost if nothing is
listening. The practical consequence of starting too early is that opening
bid/ask and the initial snapshot row are missing for the day, not that the
process fails. Start `pm-stats` after the engine is up.

### Exit codes

| Code | Meaning |
|------|---------|
| `0`  | Stopped cleanly via `Ctrl-C` / `SIGTERM` |
| `1`  | Startup failed, **or** the receive loop terminated unexpectedly and the process stopped recording |

A non-zero exit means data was not being recorded. Supervise `pm-stats` on its
exit code — a running process is not by itself evidence that recording is
happening, and the log will carry a `pm-stats stopped recording: …` line.

### Restarting mid-session

`pm-stats` can be restarted at any point during a trading day without losing
the day's figures. On the first event it sees for a given symbol it rebuilds
that symbol's running totals from `trade_log`, and the opening bid/ask from the
existing `daily_stats` row, before applying the new event. Open, high, low,
volume, trade count, VWAP and largest-trade all continue from where they were.

Two limits worth knowing:

- Anything the engine published **while `pm-stats` was down** was never
  received and cannot be recovered — ZeroMQ PUB/SUB has no replay. The rollup
  is consistent with what was recorded, not necessarily with what traded.
- For an index, `update_count` is rebuilt as the number of retained
  `index_level_snapshots` rows, which can be marginally lower than the number
  of updates originally received if any shared a millisecond.

### One recorder per database

Exactly one `pm-stats` process may write to a given `stats.db`, and this is
**enforced**. Two recorders against one file would each keep their own
in-memory rollup and overwrite each other's `daily_stats` rows, producing
figures that describe neither process — so a second one refuses to start:

```console
$ pm-stats --db data/stats.db
[ERROR] fatal startup error: another pm-stats process is already recording to
        data/stats.db (lock held on data/stats.db.lock). Two recorders on one
        database overwrite each other's daily rollups — use a different --db.
$ echo $?
1
```

The lock is an exclusive transaction on a sidecar `stats.db.lock` file, held
for the life of the process and released on shutdown. A few consequences worth
knowing:

- The `.lock` file appears alongside `stats.db`. It holds no data and can be
  deleted when no recorder is running.
- If `pm-stats` is killed with `SIGKILL`, the operating system releases the
  lock along with the process — there is no stale lock to clean up by hand.
- Readers are unaffected: `pm-stats-cli`, `pm-ticker` and the API Gateway never
  take this lock.
- Running two recorders deliberately is still fine, as long as each has its
  own `--db`.



## Querying with pm-stats-cli

Once `pm-stats` has recorded data, use `pm-stats-cli` to query without SQL.

### Basic Syntax

```bash
pm-stats-cli [--db data/stats.db] [--format table|json|csv] [--timezone TZ] COMMAND [options]
```

**Global options:**

| Flag          | Default         | Description                                                            |
|---------------|-----------------|------------------------------------------------------------------------|
| `--db`        | `data/stats.db` | Path to statistics database                                            |
| `--format`    | `table`         | Output format: `table` (human), `json` (structured), or `csv` (export) |
| `--no-header` | off             | Omit the header row from `table` and `csv` output                      |
| `--timezone`  | from the DB     | Override the session timezone that `--date` and offset-less `--from`/`--to` resolve in. Defaults to the value the database was recorded with; overriding warns on mismatch |

### Row limits and truncation

Every list command has a `--limit`. When more rows match than the limit allows,
the CLI prints a warning **to stderr** and gives you a cursor to continue from:

```console
$ pm-stats-cli trades --date 2026-06-14 --limit 200
... 200 rows ...
[WARN] Output truncated at --limit 200. More rows exist; re-run with
       --after eyJ0cyI6IjIwMjYtMDYtMTRUMTA6MDA6MDAuMDAwKzAwOjAwIiwicm93aWQiOjIwMH0= for the next page.
```

Because the warning goes to stderr it never corrupts a redirected CSV or JSON
payload — but it also means **you will not see it if you redirect both
streams**. When a count has to be exact, either raise `--limit` beyond the
expected row count or page through with `--after` until no warning appears.

`--after` takes the cursor verbatim and is available on `daily`, `snapshots`,
`trades`, `order-events`, `index-daily` and `index-snapshots`.

### Available Commands

#### `daily` — Daily OHLCV Summary

Show daily summary rows from `daily_stats`.

```bash
pm-stats-cli daily
pm-stats-cli daily --date 2026-06-14
pm-stats-cli daily --date 2026-06-14 --symbol AAPL
pm-stats-cli daily --wide  # include bid/ask and largest-trade columns
pm-stats-cli daily --limit 10

# Multi-day history for one symbol, oldest first
pm-stats-cli daily --symbol AAPL --from-date 2026-06-01 --to-date 2026-06-30
```

**Options:**

| Option        | Default          | Description                                              |
|---------------|------------------|----------------------------------------------------------|
| `--date`      | latest available | One trading date to query                                |
| `--from-date` | —                | Start of an inclusive multi-day range                    |
| `--to-date`   | —                | End of an inclusive multi-day range                      |
| `--symbol`    | all              | Limit to one symbol                                      |
| `--limit`     | 100              | Maximum rows to return                                   |
| `--after`     | —                | Continue from a previous run's truncation cursor         |
| `--wide`      | off              | Include open/close bid/ask and largest-trade fields      |

!!! important "`daily` returns a single date unless you ask for a range"
    With no date filter at all, `daily` returns rows for the **latest
    available date only** — `--limit` bounds how many *symbols* come back, not
    how many days. To get history across dates you must pass `--from-date`
    and/or `--to-date`; either bound may be omitted for an open-ended range.
    Range results are ordered oldest first, which is the order a chart plots
    them in. An explicit `--date` overrides a range if both are given.

**Example output (default `table` format):**

```
date       | symbol | open_price | high_price | low_price | close_price | volume | trade_count | vwap
-----------|--------|------------|------------|-----------|-------------|--------|-------------|-------
2026-06-14 | AAPL   | 150        | 153.25     | 149.5     | 152.75      | 5000   | 12          | 151.82
2026-06-14 | MSFT   | 414        | 418.5      | 413       | 417         | 3200   | 8           | 415.63
```

Null values render as an **empty cell** in `table` and `csv` output. Only
`--format json` writes an explicit `null`.

#### `snapshots` — Intraday Price History

Show periodic price snapshots from `price_snapshots` for one symbol over a time range. The recording interval is set by `pm-stats --snapshot-interval` (default: 15 minutes).

```bash
pm-stats-cli snapshots --symbol AAPL
pm-stats-cli snapshots --symbol AAPL --date 2026-06-14
pm-stats-cli snapshots --symbol MSFT --from 2026-06-14T09:00:00+00:00 --to 2026-06-14T16:30:00+00:00
pm-stats-cli snapshots --symbol AAPL --limit 50
```

**Options:**

| Option     | Required | Default   | Description                                      |
|------------|----------|-----------|--------------------------------------------------|
| `--symbol` | Yes      | —         | Symbol to query                                  |
| `--date`   | No       | all dates | Restrict to one trading date                     |
| `--from`   | No       | —         | Start timestamp (inclusive, ISO format)          |
| `--to`     | No       | —         | End timestamp (inclusive, ISO format)            |
| `--limit`  | No       | 500       | Maximum rows to return                           |
| `--after`  | No       | —         | Continue from a previous run's truncation cursor |

**Example output:**

```
ts                        | symbol | mid_price | best_bid | best_ask | pct_change
--------------------------|--------|-----------|----------|----------|-----------
2026-06-14T09:00:00+00:00 | AAPL   | 150.5     | 150      | 151      |
2026-06-14T09:15:00+00:00 | AAPL   | 151       | 150.5    | 151.5    | 0.33
2026-06-14T09:30:00+00:00 | AAPL   | 151.25    | 151      | 151.5    | 0.17
```

The first row's `pct_change` is empty because there is no previous snapshot to
compare against. Timestamps always carry the `+00:00` offset — copy them
verbatim into `--from`/`--to`.

#### `trades` — Trade-by-Trade History

Show individual trades from `trade_log` with optional filtering.

```bash
pm-stats-cli trades
pm-stats-cli trades --symbol AAPL
pm-stats-cli trades --symbol AAPL --date 2026-06-14
pm-stats-cli trades --symbol MSFT --from 2026-06-14T09:00:00+00:00 --to 2026-06-14T10:00:00+00:00
pm-stats-cli trades --limit 50
```

**Options:**

| Option     | Default   | Description                                      |
|------------|-----------|--------------------------------------------------|
| `--symbol` | all       | Limit to one symbol                              |
| `--date`   | all dates | Restrict to one trading date                     |
| `--from`   | —         | Start timestamp (inclusive)                      |
| `--to`     | —         | End timestamp (inclusive)                        |
| `--limit`  | 200       | Maximum rows to return                           |
| `--after`  | —         | Continue from a previous run's truncation cursor |

**Example output:**

```
ts                            | trade_id  | symbol | price | quantity | buy_gateway_id | sell_gateway_id
------------------------------|-----------|--------|-------|----------|----------------|----------------
2026-06-14T09:00:01.000+00:00 | T-AAPL-1  | AAPL   | 150   | 100      | TRADER01       | MM01
2026-06-14T09:00:05.123+00:00 | T-AAPL-2  | AAPL   | 150.5 | 50       | MM01           | TRADER02
2026-06-14T09:00:10.456+00:00 | T-AAPL-3  | AAPL   | 150.2 | 200      | TRADER02       | TRADER01
```

#### `order-events` — Private Order Lifecycle Events

Show order lifecycle events from `order_events` for one gateway. The gateway is
required because lifecycle history is private per participant.

```bash
pm-stats-cli order-events --gateway TRADER01
pm-stats-cli order-events --gateway TRADER01 --symbol AAPL
pm-stats-cli order-events --gateway TRADER01 --event-type FILL
pm-stats-cli order-events --gateway TRADER01 --date 2026-06-14 --limit 50
pm-stats-cli --format json order-events --gateway TRADER01 --from 2026-06-14T09:00:00+00:00
```

**Options:**

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--gateway` | Yes | - | Gateway ID that owns the private events |
| `--symbol` | No | all symbols | Restrict to one symbol |
| `--event-type` | No | all event types | Restrict to one normalized type — see [`event_type` values](#event_type-values). An unknown value is rejected at parse time |
| `--date` | No | all dates | Restrict to one trading date |
| `--from` | No | - | Start timestamp (inclusive) |
| `--to` | No | - | End timestamp (inclusive) |
| `--limit` | No | 500 | Maximum rows to return |
| `--after` | No | - | Continue from a previous run's truncation cursor |

**Example output:**

```
seq | ts                            | event_type | order_id | gateway_id | symbol | side | order_type | tif | price | quantity | remaining_qty | status
----|-------------------------------|------------|----------|------------|--------|------|------------|-----|-------|----------|---------------|---------
1   | 2026-06-14T09:00:00.100+00:00 | ACK        | O-AAPL-1 | TRADER01   | AAPL   | BUY  | LIMIT      | DAY | 150   | 100      | 100           | ACCEPTED
2   | 2026-06-14T09:00:01.000+00:00 | FILL       | O-AAPL-1 | TRADER01   | AAPL   | BUY  |            |     |       |          | 0             | FILLED
```

#### `order-lifecycle` — One Order's Event Trail

Show every lifecycle event for one order-like ID owned by a gateway. For combo,
OCO, and quote events, the ID may be a `combo_id`, `oco_id`, or `quote_id` stored
in the `order_id` column.

```bash
pm-stats-cli order-lifecycle --gateway TRADER01 --order-id O-AAPL-1
pm-stats-cli --format csv order-lifecycle --gateway TRADER01 --order-id O-AAPL-1
```

**Options:**

| Option       | Required | Default | Description                                           |
|--------------|----------|---------|-------------------------------------------------------|
| `--gateway`  | Yes      | -       | Gateway ID that owns the private event trail          |
| `--order-id` | Yes      | -       | Order, combo, OCO, or quote identifier to reconstruct |

#### `symbols` — Symbol Discovery

List all symbols with data in the statistics DB.

```bash
pm-stats-cli symbols
pm-stats-cli symbols --date 2026-06-14  # symbols with data on a specific date
```

#### `dates` — Trading Date Discovery

List all available trading dates recorded in `daily_stats`.

```bash
pm-stats-cli dates
pm-stats-cli dates --symbol AAPL  # dates with data for a specific symbol
```

**Example output:**

```
date
----------
2026-06-15
2026-06-14
2026-06-13
```

#### `index-daily` — Daily Index OHLC Summary

Show daily index summary rows from `index_daily_stats`.

```bash
pm-stats-cli index-daily
pm-stats-cli index-daily --date 2026-06-14
pm-stats-cli index-daily --date 2026-06-14 --index-id EDU100
pm-stats-cli index-daily --wide  # include open/close aggregate market cap
pm-stats-cli index-daily --limit 10
```

**Options:**

| Option        | Default          | Description                                      |
|---------------|------------------|--------------------------------------------------|
| `--date`      | latest available | One trading date to query                        |
| `--from-date` | —                | Start of an inclusive multi-day range            |
| `--to-date`   | —                | End of an inclusive multi-day range              |
| `--index-id`  | all indexes      | Limit to one index                               |
| `--limit`     | 100              | Maximum rows to return                           |
| `--after`     | —                | Continue from a previous run's truncation cursor |
| `--wide`      | off              | Include open/close aggregate market cap columns  |

As with `daily`, omitting every date filter returns the **latest date only**;
pass `--from-date`/`--to-date` for a series across days.

**Example output (default `table` format):**

```
date       | index_id | open_level | high_level | low_level | close_level | close_session_state | update_count
-----------|----------|------------|------------|-----------|-------------|----------------------|-------------
2026-06-14 | EDU100   | 1042.1     | 1056.3     | 1040.05   | 1048.73     | CLOSED               | 512
```

`close_session_state` is `CLOSED` above, so `close_level` (`1048.73`) is confirmed as the final EOD print for that date — see [Getting the EOD index level for a date](#getting-the-eod-index-level-for-a-date) below.

#### `index-snapshots` — Intraday Index Level History

Show every recorded index level update from `index_level_snapshots` for one index over a time range. Unlike `snapshots` for instruments, there is no configurable recording interval to tune — every `index.update` event `pm-stats` receives is recorded (`pm-index` has already rate-limited its own publications before `pm-stats` ever sees them).

```bash
pm-stats-cli index-snapshots --index-id EDU100
pm-stats-cli index-snapshots --index-id EDU100 --date 2026-06-14
pm-stats-cli index-snapshots --index-id EDU100 --from 2026-06-14T09:00:00+00:00 --to 2026-06-14T16:30:00+00:00
pm-stats-cli index-snapshots --index-id EDU100 --limit 50
```

**Options:**

| Option       | Required | Default   | Description                                      |
|--------------|----------|-----------|--------------------------------------------------|
| `--index-id` | Yes      | —         | Index to query                                   |
| `--date`     | No       | all dates | Restrict to one trading date                     |
| `--from`     | No       | —         | Start timestamp (inclusive, ISO format)          |
| `--to`       | No       | —         | End timestamp (inclusive, ISO format)            |
| `--limit`    | No       | 500       | Maximum rows to return                           |
| `--after`    | No       | —         | Continue from a previous run's truncation cursor |

**Example output:**

```
ts                            | index_id | level   | aggregate_cap | divisor | session_state
------------------------------|----------|---------|---------------|---------|----------------
2026-06-14T09:00:00.000+00:00 | EDU100   | 1042.10 | 7350000000000 | 1.25    | OPENING_AUCTION
2026-06-14T09:00:05.500+00:00 | EDU100   | 1043.85 | 7362000000000 | 1.25    | CONTINUOUS
```

#### `gaps` — Detected Feed Gaps

Show trades the recorder never received, from `feed_gaps`.

```bash
pm-stats-cli gaps
pm-stats-cli gaps --date 2026-06-14
pm-stats-cli gaps --from 2026-06-14T09:00:00Z --to 2026-06-14T12:00:00Z
```

**Options:**

| Option    | Default   | Description                  |
|-----------|-----------|------------------------------|
| `--date`  | all dates | Restrict to one trading date |
| `--from`  | —         | Start timestamp (inclusive)  |
| `--to`    | —         | End timestamp (inclusive)    |
| `--limit` | 500       | Maximum rows to return       |

**Example output:**

```
seq | ts                            | stream         | expected_id | received_id | missing_count
----+-------------------------------+----------------+-------------+-------------+--------------
1   | 2026-06-14T09:14:02.115+00:00 | trade.executed | 3           | 6           | 3
2   | 2026-06-14T11:41:55.008+00:00 | trade.executed | 8           | 20          | 12
```

`No rows found.` is the healthy result. See the
[`feed_gaps`](#feed_gaps) warning for what detection does and does not cover.

#### `index-ids` — Index Discovery

List all index IDs with data in the statistics DB.

```bash
pm-stats-cli index-ids
pm-stats-cli index-ids --date 2026-06-14  # indexes with data on a specific date
```

If no exchange indexes are configured, this returns no rows — that is expected, not an error.

### Order Lifecycle History Queries

`order_events` can be queried directly with `pm-stats-cli` or through the API
Gateway history endpoints. Use `pm-stats-cli` for local support, audit, and
offline analysis. Use API Gateway history when a client should see only the
private history for its authenticated trading credential.

Direct CLI examples:

```bash
pm-stats-cli order-events --gateway TRADER01 --symbol AAPL --event-type FILL --limit 50
pm-stats-cli order-lifecycle --gateway TRADER01 --order-id ORDER_ID
pm-stats-cli --format json order-events --gateway TRADER01 --date 2026-06-14
```

For API Gateway history queries, start the recorder, engine, stats database, and
API gateway with matching config:

```bash
pm-engine --verbose
pm-stats --db data/stats.db
pm-api-gwy --instance desk
```

Then query order lifecycle history through HTTP with a trading API key:

```bash
curl -H 'Authorization: Bearer key-trader-demo' \
   'http://127.0.0.1:8080/api/v1/history/orders?symbol=AAPL&event_type=FILL&limit=50'
```

API filters for `/api/v1/history/orders`:

| Query parameter | Required | Description |
|-----------------|----------|-------------|
| `symbol` | No | Restrict to one symbol |
| `event_type` | No | Restrict to one normalized type — see [`event_type` values](#event_type-values). An unknown value returns `422` |
| `date` | No | Restrict to one `YYYY-MM-DD` date based on `order_events.ts` |
| `from` | No | Inclusive ISO timestamp lower bound |
| `to` | No | Inclusive ISO timestamp upper bound |
| `limit` | No | Maximum rows to return, default `500`, maximum `5000` |
| `after` | No | Opaque keyset-pagination cursor from a previous response's `next_cursor`; fetches the next page |

`/history/orders` (and `/history/fills`) responses include `next_cursor` when
more rows are available. See
[API Gateway — Pagination](260-api-gateway.md#pagination) for the full
`count`/`has_more`/`next_cursor` contract, including which endpoints are
exceptions to it.

To reconstruct one order's lifecycle, use the order ID path:

```bash
curl -H 'Authorization: Bearer key-trader-demo' \
   'http://127.0.0.1:8080/api/v1/history/orders/ORDER_ID'
```

For fill-only history, use the shortcut endpoint:

```bash
curl -H 'Authorization: Bearer key-trader-demo' \
   'http://127.0.0.1:8080/api/v1/history/fills?symbol=AAPL&date=2026-06-14'
```

Responses include an `events` array, `count`, and for list-style queries a `has_more` flag. Each event row mirrors the `order_events` table columns, so JSON output can be loaded directly into audit notebooks or support tooling.

Read-only API keys with `gateway_id: null` cannot query private order lifecycle history. Use a trading credential whose `gateway_id` owns the orders being investigated.



## Output Formats

### Table Format (default)

Human-readable aligned columns, designed for terminal viewing.

```bash
pm-stats-cli daily --date 2026-06-14
```

Good for: interactive exploration, demos, quick spot-checks.

### JSON Format

Machine-readable structured output for automation and downstream tools.

```bash
pm-stats-cli --format json daily --date 2026-06-14 | jq '.[] | select(.symbol == "AAPL")'
```

Output:

```json
[
  {
    "date": "2026-06-14",
    "symbol": "AAPL",
    "open_price": 150.0,
    "high_price": 153.25,
    ...
  },
  ...
]
```

Good for: scripts, APIs, BI tools, data pipelines.

### CSV Format

Comma-separated values suitable for spreadsheets and data analysis tools.

```bash
pm-stats-cli --format csv trades --symbol AAPL --date 2026-06-14 > trades.csv
```

Output:

```
ts,trade_id,symbol,price,quantity,buy_gateway_id,sell_gateway_id
2026-06-14T09:00:01.000,T-AAPL-1,AAPL,150,100,TRADER01,MM01
2026-06-14T09:00:05.123,T-AAPL-2,AAPL,150.5,50,MM01,TRADER02
```

Good for: Excel, Google Sheets, R/Python data frames, general-purpose analysis.

Use `--no-header` to suppress the header row:

```bash
pm-stats-cli --format csv --no-header trades --symbol AAPL >> all_trades.csv
```



## Common Analyst Workflows

### End-of-Day Summary Report

Generate a quick summary of all symbols for a given trading date:

```bash
pm-stats-cli daily --date 2026-06-14 --wide
```

This shows open/close prices, bid/ask spreads, volume, trade count, and VWAP for every symbol.

**Follow-up questions:**
- Which symbol had the highest volume?
- What was the spread between open bid and close bid?
- Did any symbol experience a large single trade?

### Intraday Price Volatility Analysis

Check mid-price movement for one symbol throughout the day:

```bash
pm-stats-cli snapshots --symbol AAPL --date 2026-06-14 | head -20
```

Look at the `pct_change` column to spot:
- Periods of high volatility (large jumps)
- Periods of stagnation (flat pricing)
- Potential technical support/resistance levels
- Times when the book was empty (null bids/asks)

### Trade Flow Analysis

Examine all trades for a symbol to identify patterns:

```bash
pm-stats-cli --format csv trades --symbol AAPL --date 2026-06-14 > aapl_trades.csv
```

Then analyze in a spreadsheet or Python:

```python
import pandas as pd
trades = pd.read_csv('aapl_trades.csv', parse_dates=['ts'])
trades['hour'] = trades['ts'].dt.hour

# Trades per hour
print(trades.groupby('hour').size())

# Average trade size
print(trades.groupby('hour')['quantity'].mean())

# Who are the active participants?
print(trades['buy_gateway_id'].value_counts() + trades['sell_gateway_id'].value_counts())
```

### Participant Performance Analysis

Export trade logs and group by participant to see:

```bash
pm-stats-cli --format json trades --date 2026-06-14 | jq '.[] | {buyer: .buy_gateway_id, seller: .sell_gateway_id, price: .price, qty: .quantity}' > participant_flows.json
```

Then aggregate in your tool of choice:
- How many trades did each participant execute?
- What was their average trade size?
- Did they tend to be buyers or sellers?

### Multi-Day Price Trends

Compare the same symbol across multiple trading dates. A date **range** is
required — without one, `daily` returns only the latest date:

```bash
pm-stats-cli --format csv daily --symbol AAPL \
  --from-date 2026-01-01 --to-date 2026-06-30 --limit 1000 > aapl_history.csv
```

Either bound may be omitted for an open-ended range, so this exports everything
recorded for the symbol:

```bash
pm-stats-cli --format csv daily --symbol AAPL --from-date 1970-01-01 --limit 1000 \
  > aapl_history.csv
```

Rows come back oldest first. Check stderr for a truncation warning — if one
appears, raise `--limit` or page with `--after`.

This gives you historical OHLCV to track trends, seasonal patterns, or
support/resistance zones over time. Remember that prices are **unadjusted**:
a series spanning a corporate action is discontinuous and returns computed
across it will be wrong.

### Index Level History

Chart or export an exchange index's intraday level trajectory:

```bash
pm-stats-cli index-snapshots --index-id EDU100 --date 2026-06-14 | head -20
```

Look for the same signals `snapshots` gives for instruments — periods of rapid
level movement, gaps that may indicate a connectivity issue between
`pm-index` and `pm-stats`, and the `session_state` column shifting from
`OPENING_AUCTION`/`CONTINUOUS`/`CLOSED`.

Compare the index's daily performance across dates the same way you would
for a symbol — again, a date range is required for more than one day:

```bash
pm-stats-cli --format csv index-daily --index-id EDU100 \
  --from-date 2026-01-01 --to-date 2026-06-30 --limit 1000 > edu100_history.csv
```

### Getting the EOD index level for a date

To look up an index's official end-of-day closing level for a specific date,
query `index-daily` for that date and index:

```bash
pm-stats-cli index-daily --date 2026-06-14 --index-id EDU100
```

```
date       | index_id | open_level | high_level | low_level | close_level | close_session_state | update_count
-----------|----------|------------|------------|-----------|-------------|----------------------|-------------
2026-06-14 | EDU100   | 1042.1     | 1056.3     | 1040.05   | 1048.73     | CLOSED               | 512
```

`close_level` is the answer. For any date in the past this is always safe to
read directly — no more `index.update` events can arrive for a date once it
has rolled over, so `close_level` cannot change after the fact.

If you are querying **today's** date, confirm the row is actually final
before trusting it, since `close_level` is updated on every tick and is a
live "last level so far" until the session closes:

```bash
pm-stats-cli index-daily --index-id EDU100 --format json \
  | python3 -c "import json,sys; r=json.load(sys.stdin)[0]; print(r['close_level'], r['close_session_state'])"
```

If `close_session_state` prints `CLOSED`, `close_level` is the final EOD
print. Any other value (e.g. `CONTINUOUS`, `OPENING_AUCTION`) means the
session is still running and `close_level` will keep moving — re-query
after the close, or wait for `close_session_state` to flip to `CLOSED`.

For scripting, JSON output makes this a one-line check:

```bash
pm-stats-cli index-daily --date 2026-06-14 --index-id EDU100 --format json \
  | python3 -c "
import json, sys
row = json.load(sys.stdin)[0]
if row['close_session_state'] != 'CLOSED':
    sys.exit('not final yet: ' + row['close_session_state'])
print(f\"EOD close for {row['date']} {row['index_id']}: {row['close_level']}\")
"
```

### Validation — Did the Trade Complete Correctly?

After a trading session ends, verify key metrics:

0. **Check the recording is complete — do this first:**
   ```bash
   pm-stats-cli gaps --date 2026-06-14
   ```
   `No rows found.` means no loss was detected. Any row means the figures
   below are computed from an incomplete trade record, and `volume`,
   `turnover` and `vwap` for the affected symbols will be understated. There
   is no way to recover the missing trades after the fact — ZeroMQ PUB/SUB has
   no replay — so treat the day's numbers as approximate and investigate why
   `pm-stats` fell behind.

   `pm-stats` also logs a session total at `INFO` when it shuts down:

   ```text
   session totals: book_topics=10432, messages_received=12905, trades_persisted=2471
   ```

1. **Check daily summary recorded:**
   ```bash
   pm-stats-cli daily --date 2026-06-14
   ```
   Verify: all symbols present, volume > 0, open/close prices are reasonable.

2. **Check trade count:**
   ```bash
   # --limit must exceed the expected count, or the result is truncated.
   # Subtract 1 for the CSV header row.
   pm-stats-cli --format csv --no-header trades --date 2026-06-14 --limit 100000 | wc -l
   ```
   Verify: matches expected number from the trading floor. If a
   `[WARN] Output truncated` line appears on stderr, the count is **not**
   complete — raise `--limit` and re-run.

   The authoritative count without any limit concerns:

   ```bash
   pm-stats-cli --format json daily --date 2026-06-14 \
     | python3 -c "import json,sys; print(sum(r['trade_count'] for r in json.load(sys.stdin)))"
   ```

3. **Check for any empty books:**
   ```bash
   pm-stats-cli --format json snapshots --symbol AAPL --date 2026-06-14 \
     | python3 -c "
   import json, sys
   for row in json.load(sys.stdin):
       if row['best_bid'] is None or row['best_ask'] is None:
           print(row['ts'], row['best_bid'], row['best_ask'])
   "
   ```
   Empty books during active trading hours may indicate a problem. Use JSON
   here: `table` and `csv` render a null as an empty cell, so a text search for
   `null` finds nothing.

4. **Check largest trade vs. typical trade size:**
   ```bash
   pm-stats-cli daily --wide --date 2026-06-14 --symbol AAPL
   ```
   Look at `largest_trade_qty` vs. average (`volume / trade_count`). Outliers warrant investigation.

### Order Lifecycle Investigation

Use `order_events` when the question is about what happened to a submitted order rather than what trades printed to the market.

Examples:

```bash
# All recent events for a gateway
pm-stats-cli order-events --gateway TRADER01 --limit 100

# One order from ACK through fills, cancels, expiry, or rejection
pm-stats-cli order-lifecycle --gateway TRADER01 --order-id ORDER_ID

# Fill-only view for one symbol and date
pm-stats-cli order-events --gateway TRADER01 --symbol AAPL --event-type FILL --date 2026-06-14
```

Use this workflow to answer:

- Was the order accepted or rejected? (`ACK` / `REJECT`, and equally
  `COMBO_ACK` / `COMBO_REJECT`, `OCO_ACK` / `OCO_REJECT`,
  `QUOTE_ACK` / `QUOTE_REJECT`)
- Did an amend reset priority?
- Which fills belong to this order ID?
- Was the order cancelled or expired? (`CANCEL`, `EXPIRE`, and `OCO_CANCEL`
  for an OCO leg)
- Was it linked to a combo or OCO group? (`combo_parent_id`, `oco_group_id`)
- Does API Gateway history match the live private WebSocket events seen by the client?

```bash
# Every rejection across all event families for one gateway
for t in REJECT COMBO_REJECT OCO_REJECT QUOTE_REJECT; do
  pm-stats-cli order-events --gateway TRADER01 --event-type "$t"
done
```



## Integration with Other Tools

### Combining with pm-ticker

`pm-ticker` uses `data/stats.db` to display OHLCV and volume context in its live display.

To verify `pm-stats` is recording correctly while `pm-ticker` runs:

```bash
# Terminal 1: Start engine
pm-engine --verbose

# Terminal 2: Start stats
pm-stats

# Terminal 3: Start ticker (reads from stats DB)
pm-ticker

# Terminal 4: Live-check stats as trades occur
watch -n 5 'pm-stats-cli daily | tail -5'
```

### Exporting to BI Tools

Example: Export daily summaries to a cloud data warehouse:

```bash
# Export as CSV — pass a date range, or you get only the latest date
pm-stats-cli --format csv daily --from-date 2026-01-01 --limit 10000 > daily_stats.csv

# Upload to BigQuery, Redshift, Snowflake, etc.
bq load my_dataset.daily_stats daily_stats.csv

# Or load into local database
sqlite3 analysis.db <<EOF
.mode csv
.import --skip 1 daily_stats.csv daily_stats
EOF
```

!!! note "Carry the session timezone with the export"
    `stats.db` records the session timezone in `stats_meta`, but a CSV export
    does not — and `date` cannot be interpreted without it. Read it before
    exporting and keep it with the file:

    ```bash
    sqlite3 data/stats.db \
      "SELECT value FROM stats_meta WHERE key = 'session_timezone'"
    ```

    Currency, tick size and price precision are still not recorded anywhere in
    `stats.db`; carry those separately.

### Python / Pandas Integration

Query and analyze directly in Python:

```python
import subprocess
import json
import pandas as pd

# Get daily stats as JSON
result = subprocess.run(
    ['pm-stats-cli', '--format', 'json', 'daily', '--date', '2026-06-14'],
    capture_output=True,
    text=True
)

daily = pd.DataFrame(json.loads(result.stdout))

# Pivot to wide format for correlation analysis
daily_pivot = daily.set_index('symbol')
print(daily_pivot[['open_price', 'close_price', 'volume']])

# Calculate returns
daily['return_pct'] = (daily['close_price'] - daily['open_price']) / daily['open_price'] * 100
print(daily[['symbol', 'return_pct']])
```



## Troubleshooting

### No data recorded — where did the trades go?

1. **Verify `pm-stats` is running:**
   ```bash
   ps aux | grep pm-stats
   ```
   If not running, start it.

2. **Check that `pm-stats` connected to the engine:**
   ```bash
   pm-engine --verbose
   ```
   Look for log messages showing that `pm-stats` sent a `book.snapshot_request`.

3. **Verify the database file exists and has the right tables:**
   ```bash
   sqlite3 data/stats.db ".tables"
   ```
   You should see: `daily_stats`, `price_snapshots`, `trade_log`, `order_events`,
   `index_daily_stats`, `index_level_snapshots`, `feed_gaps`, and `stats_meta`.

4. **Check for recent trades:**
   ```bash
   pm-stats-cli trades --limit 5
   ```
   If empty, no trades have executed yet. Execute a test trade first.

5. **Check for order lifecycle history:**
   ```bash
   sqlite3 data/stats.db "SELECT ts,event_type,order_id,gateway_id,symbol FROM order_events ORDER BY seq DESC LIMIT 5;"
   ```
   If empty, no private order lifecycle topics have reached `pm-stats` yet. Submit, amend, cancel, or fill an order while `pm-stats` is running.

### No index data recorded — where did the index updates go?

1. **Confirm the exchange actually has an index configured.** If
   `engine_config.yaml` has no `indexes:` block, `pm-index` publishes
   nothing and `index_daily_stats`/`index_level_snapshots` staying empty is
   correct behavior, not a bug.

2. **Verify `pm-index` is running:**
   ```bash
   ps aux | grep pm-index
   ```
   `pm-stats` connects to `pm-index`'s own PUB socket (default port 5558),
   separate from the engine's PUB socket — if `pm-index` isn't running,
   there is nothing for `pm-stats` to receive.

3. **Check for recorded index updates:**
   ```bash
   pm-stats-cli index-ids
   pm-stats-cli index-snapshots --index-id EDU100 --limit 5
   ```
   If `index-ids` returns nothing, `pm-stats` has not received any
   `index.update` event yet — confirm `pm-index` is up and has finished its
   own startup index calculation.

4. **Check `pm-stats` logs at `-v`/`INFO` or higher** for
   `recorded index update index_id=...` lines, or run with `--sql-trace` to
   see the underlying `INSERT`/`UPDATE` statements against
   `index_level_snapshots`/`index_daily_stats`.

### Queries return "No rows found" but I know data should exist

1. **Check the date format:**
   ```bash
   pm-stats-cli dates  # What dates are actually in the DB?
   ```
   Use the exact date returned, e.g., `--date 2026-06-14`.

2. **Verify the symbol exists:**
   ```bash
   pm-stats-cli symbols
   ```
   `pm-stats-cli` upper-cases `--symbol`, `--gateway` and `--index-id` before
   querying, so `--symbol aapl` and `--symbol AAPL` behave identically. The
   values stored in the database are whatever the engine published — if those
   are not upper-case, the CLI cannot match them and you must query with
   `sqlite3` directly.

3. **Check the session timezone.** `--date` selects a *trading day* in the
   `--timezone` you pass. If `pm-stats-cli` uses a different `--timezone` than
   `pm-stats` recorded with, `--date` resolves to the wrong window and returns
   too few rows, too many, or none — with no error:
   ```bash
   pm-stats-cli --timezone Europe/Stockholm trades --date 2026-06-14
   ```

4. **Check the time window for snapshots/trades:**
   ```bash
   pm-stats-cli snapshots --symbol AAPL --date 2026-06-14
   ```
   If using `--from` / `--to`, both bounds are inclusive instants. A bound
   without an offset is read as session-local time; append `Z` or an explicit
   offset to be unambiguous.

### Database is locked or "unable to open"

1. **`stats.db` runs in WAL mode**, so one writer (`pm-stats`) and any number
   of readers (`pm-stats-cli`, `pm-ticker`, the API Gateway) proceed
   concurrently without blocking each other. Both the writer and readers also
   set a 5-second `busy_timeout` to absorb the brief exclusive lock taken
   during a WAL checkpoint.

2. **A second writer is still excluded.** Attempting to write directly with
   `sqlite3` while `pm-stats` is running can still produce a lock error, and
   running two `pm-stats` processes against one file corrupts the daily
   rollups (see "One recorder per database" above). Use `pm-stats-cli` for
   queries and keep a single recorder per file.

3. **If you need to copy the DB for backup**, do it online — do not `cp` the
   file. In WAL mode a plain `cp` can capture a torn database without the
   companion `-wal` file:
   ```bash
   # Safe while pm-stats is running; produces a consistent, compacted copy
   sqlite3 data/stats.db "VACUUM INTO 'data/stats_backup.db'"

   # Equivalent, and works on older sqlite3 builds
   sqlite3 data/stats.db ".backup 'data/stats_backup.db'"
   ```

!!! note "Growth and retention"
    `trade_log` and `order_events` are append-only and unbounded — `pm-stats`
    never prunes them. On a long-running deployment, plan for periodic
    archival (copy out with `VACUUM INTO`, then `DELETE` old rows and `VACUUM`)
    and monitor the file size. There is no built-in retention setting.

### Snapshot times seem wrong or are missing

- The **first** `book.*` message for a symbol always writes a snapshot. After that, a snapshot is written when a `book.*` message arrives **and** the configured interval has elapsed since the last one for that symbol.
- The default interval is **15 minutes** (`--snapshot-interval 900`). If you need finer resolution, start `pm-stats` with a smaller value, e.g. `--snapshot-interval 60` for one-minute snapshots.
- If trading is light and no book updates occur during the interval, no snapshot is recorded for that period. This is by design — snapshots only record when the market moves.

To verify:

```bash
pm-stats-cli snapshots --symbol AAPL --date 2026-06-14 | awk '{print $1}' | uniq -c
```

You should see roughly one entry every 15 minutes. Large gaps indicate periods with no trading.

### VWAP calculation looks wrong

VWAP is recalculated on every trade and stored at that moment. The final VWAP for the day is stored in `daily_stats` after the close.

To verify VWAP manually:

```bash
# --limit must exceed the day's trade count, or you will be comparing a
# partial recomputation against the full-day figure and they will not match.
pm-stats-cli --format csv trades --symbol AAPL --date 2026-06-14 --limit 100000 | \
  awk -F, 'NR>1 {qty_sum += $5; price_qty += $4*$5} END {print price_qty/qty_sum}'
```

This calculates $\sum(price \times qty) / \sum(qty)$ from the trade log. Compare it to the value in `daily_stats`:

```bash
pm-stats-cli daily --symbol AAPL --date 2026-06-14
```

They should agree to within floating-point rounding — prices and VWAP are
stored as SQLite `REAL` (IEEE-754 double), so expect agreement in the first
~15 significant digits, not an exact string match.

If they disagree materially, check in this order:

1. **Was the output truncated?** A `[WARN]` line on stderr means the awk sum
   covered only part of the day.
2. **Do `pm-stats` and `pm-stats-cli` use the same `--timezone`?** If not,
   `--date` selects a different set of trades than the one folded into the
   `daily_stats` row, and the two will never match.



## See Also

- [Processes — pm-stats and pm-stats-cli](170-processes.md#pm-stats-statistics-recorder) — full process documentation
- [Processes — pm-ticker](170-processes.md#pm-ticker-scrolling-market-ticker) — live ticker that uses statistics data
- [Audit Trail](190-audit.md) — `pm-audit-cli` for querying the full event log
- [Persistence](180-persistence.md) — where all data files are stored

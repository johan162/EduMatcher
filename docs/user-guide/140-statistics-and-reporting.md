# Statistics and Reporting

!!! note "Learning objectives"
    After reading this page you will understand:

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

See [Processes — Environment variables](170-processes.md#environment-variables) for full details on `EDUMATCHER_DATA_DIR` and `EDUMATCHER_CONFIG`.



## The Statistics Database Schema

All statistics are stored in `data/stats.db`, a SQLite 3 database with six tables:

### `daily_stats`

Aggregated OHLCV (open, high, low, close, volume) and related metrics for each symbol per day.

| Column                | Type    | Description                              |
|-----------------------|---------|------------------------------------------|
| `date`                | TEXT    | Calendar date `YYYY-MM-DD`               |
| `symbol`              | TEXT    | Instrument ticker                        |
| `open_price`          | REAL    | First trade price of the day             |
| `high_price`          | REAL    | Highest trade price                      |
| `low_price`           | REAL    | Lowest trade price                       |
| `close_price`         | REAL    | Last trade price                         |
| `volume`              | INTEGER | Total traded quantity                    |
| `trade_count`         | INTEGER | Number of trades                         |
| `vwap`                | REAL    | Volume-weighted average price            |
| `open_bid`            | REAL    | Best bid at first book update of the day |
| `open_ask`            | REAL    | Best ask at first book update of the day |
| `close_bid`           | REAL    | Best bid at engine shutdown              |
| `close_ask`           | REAL    | Best ask at engine shutdown              |
| `largest_trade_qty`   | INTEGER | Quantity of the single largest trade     |
| `largest_trade_price` | REAL    | Price of the single largest trade        |

**Use case**: End-of-day summaries, daily trend analysis, multi-day performance tracking.

### `price_snapshots`

Intraday mid-price, bid/ask, and percentage-change history captured every 15 minutes per symbol.

| Column       | Type | Description                                                                       |
|--------------|------|-----------------------------------------------------------------------------------|
| `ts`         | TEXT | ISO-8601 timestamp (UTC, second precision)                                        |
| `symbol`     | TEXT | Instrument ticker                                                                 |
| `mid_price`  | REAL | `(best_bid + best_ask) / 2`; falls back to last trade price if book is empty      |
| `best_bid`   | REAL | Best bid at snapshot time (null if empty)                                         |
| `best_ask`   | REAL | Best ask at snapshot time (null if empty)                                         |
| `pct_change` | REAL | Percentage change of mid-price from previous snapshot (e.g. `1.25` means +1.25 %) |

**Use case**: Intraday price trends, volatility analysis, spread history, detecting trading halts or gaps.

### `trade_log`

Append-only record of every matched trade — no aggregation, one row per trade.

| Column            | Type    | Description                                     |
|-------------------|---------|-------------------------------------------------|
| `ts`              | TEXT    | ISO-8601 timestamp (UTC, millisecond precision) |
| `trade_id`        | TEXT    | UUID from the engine (unique per trade)         |
| `symbol`          | TEXT    | Instrument ticker                               |
| `price`           | REAL    | Execution price                                 |
| `quantity`        | INTEGER | Matched quantity                                |
| `buy_gateway_id`  | TEXT    | Gateway that submitted the buy order            |
| `sell_gateway_id` | TEXT    | Gateway that submitted the sell order           |

**Use case**: Trade-by-trade analysis, flow analysis, detecting potential market manipulation, audit trails.

### `order_events`

Append-only order lifecycle history captured from private engine topics. This table is used by API Gateway history endpoints to reconstruct per-gateway order, fill, cancel, amend, combo, OCO, and quote events.

| Column            | Type    | Description                                                                                                          |
|-------------------|---------|----------------------------------------------------------------------------------------------------------------------|
| `seq`             | INTEGER | Monotonic local sequence assigned by SQLite for stable event ordering                                                |
| `ts`              | TEXT    | ISO-8601 timestamp (UTC, millisecond precision) when `pm-stats` recorded the event                                   |
| `event_type`      | TEXT    | Normalized event category: `ACK`, `REJECT`, `FILL`, `AMEND`, `CANCEL`, `EXPIRE`, `COMBO`, `OCO`, `QUOTE`, or `EVENT` |
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

### `index_daily_stats`

Aggregated daily OHLC (open, high, low, close) for each configured exchange index, one row per `(date, index_id)`, upserted on every `index.update` event `pm-stats` receives from `pm-index`.

| Column                 | Type    | Description                                          |
|------------------------|---------|-------------------------------------------------------|
| `date`                 | TEXT    | Calendar date `YYYY-MM-DD`                             |
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

| Column          | Type | Description                                                          |
|-----------------|------|------------------------------------------------------------------------|
| `ts`            | TEXT | ISO-8601 timestamp (UTC, millisecond precision)                        |
| `index_id`      | TEXT | Index identifier                                                        |
| `level`         | REAL | Current index level at this update                                      |
| `aggregate_cap` | REAL | Aggregate constituent market cap at this update                         |
| `divisor`       | REAL | Index divisor in effect at this update                                  |
| `session_state` | TEXT | Index session state at this update (e.g. `CONTINUOUS`, `CLOSED`)        |
| `day_open`      | REAL | Day's opening level, when known at this update                         |
| `day_high`      | REAL | Day's high level so far, when known at this update                     |
| `day_low`       | REAL | Day's low level so far, when known at this update                      |

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

| Flag                    | Default         | Description                                                                            |
|-------------------------|-----------------|----------------------------------------------------------------------------------------|
| `--db`                  | `data/stats.db` | Custom statistics database path                                                        |
| `--snapshot-interval`   | `900` (15 min)  | Seconds between `price_snapshots` rows per symbol. Lower values give finer intraday resolution at the cost of more database writes. |
| `--sql-trace`           | off             | Log executed SQLite statements from the stats writer connection — useful for debugging what `pm-stats` is actually writing |
| `--log-level`           | `WARNING`       | Explicit level: `CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG`                       |
| `-v`, `--verbose`       | off             | Increase verbosity (`-v` → `INFO`, `-vv` → `DEBUG`)                                   |
| `-q`, `--quiet`         | off             | Reduce output to warnings/errors                                                       |

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

**Important**: `pm-stats` must start **after** the engine binds its ZeroMQ sockets. If you start it before the engine, it will fail to connect.



## Querying with pm-stats-cli

Once `pm-stats` has recorded data, use `pm-stats-cli` to query without SQL.

### Basic Syntax

```bash
pm-stats-cli [--db data/stats.db] [--format table|json|csv] COMMAND [options]
```

**Global options:**

| Flag          | Default         | Description                                                            |
|---------------|-----------------|------------------------------------------------------------------------|
| `--db`        | `data/stats.db` | Path to statistics database                                            |
| `--format`    | `table`         | Output format: `table` (human), `json` (structured), or `csv` (export) |
| `--no-header` | off             | Omit header row (useful for CSV scripts)                               |

### Available Commands

#### `daily` — Daily OHLCV Summary

Show daily summary rows from `daily_stats`.

```bash
pm-stats-cli daily
pm-stats-cli daily --date 2026-06-14
pm-stats-cli daily --date 2026-06-14 --symbol AAPL
pm-stats-cli daily --wide  # include bid/ask and largest-trade columns
pm-stats-cli daily --limit 10
```

**Options:**

| Option     | Default          | Description                                         |
|------------|------------------|-----------------------------------------------------|
| `--date`   | latest available | Calendar date to query                              |
| `--symbol` | all              | Limit to one symbol                                 |
| `--limit`  | 100              | Maximum rows to return                              |
| `--wide`   | off              | Include open/close bid/ask and largest-trade fields |

**Example output (default `table` format):**

```
date       | symbol | open_price | high_price | low_price | close_price | volume | trade_count | vwap
-----------|--------|------------|------------|-----------|-------------|--------|-------------|-------
2026-06-14 | AAPL   | 150        | 153.25     | 149.5     | 152.75      | 5000   | 12          | 151.82
2026-06-14 | MSFT   | 414        | 418.5      | 413       | 417         | 3200   | 8           | 415.63
```

#### `snapshots` — Intraday Price History

Show periodic price snapshots from `price_snapshots` for one symbol over a time range. The recording interval is set by `pm-stats --snapshot-interval` (default: 15 minutes).

```bash
pm-stats-cli snapshots --symbol AAPL
pm-stats-cli snapshots --symbol AAPL --date 2026-06-14
pm-stats-cli snapshots --symbol MSFT --from 2026-06-14T09:00:00+00:00 --to 2026-06-14T16:30:00+00:00
pm-stats-cli snapshots --symbol AAPL --limit 50
```

**Options:**

| Option     | Required | Default   | Description                  |
|------------|----------|-----------|------------------------------|
| `--symbol` | Yes      | —         | Symbol to query              |
| `--date`   | No       | all dates | Restrict to one trading date |
| `--from`   | No       | —         | Start timestamp (ISO format) |
| `--to`     | No       | —         | End timestamp (ISO format)   |
| `--limit`  | No       | 500       | Maximum rows to return       |

**Example output:**

```
ts                    | symbol | mid_price | best_bid | best_ask | pct_change
----------------------|--------|-----------|----------|----------|----------
2026-06-14T09:00:00   | AAPL   | 150.5     | 150      | 151      | null
2026-06-14T09:15:00   | AAPL   | 151       | 150.5    | 151.5    | 0.33
2026-06-14T09:30:00   | AAPL   | 151.25    | 151      | 151.5    | 0.17
```

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

| Option     | Default   | Description                  |
|------------|-----------|------------------------------|
| `--symbol` | all       | Limit to one symbol          |
| `--date`   | all dates | Restrict to one trading date |
| `--from`   | —         | Start timestamp              |
| `--to`     | —         | End timestamp                |
| `--limit`  | 200       | Maximum rows to return       |

**Example output:**

```
ts                       | trade_id  | symbol | price | quantity | buy_gateway_id | sell_gateway_id
-------------------------|-----------|--------|-------|----------|----------------|----------------
2026-06-14T09:00:01.000  | T-AAPL-1  | AAPL   | 150   | 100      | TRADER01       | MM01
2026-06-14T09:00:05.123  | T-AAPL-2  | AAPL   | 150.5 | 50       | MM01           | TRADER02
2026-06-14T09:00:10.456  | T-AAPL-3  | AAPL   | 150.2 | 200      | TRADER02       | TRADER01
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
| `--event-type` | No | all event types | Restrict to one normalized type such as `ACK`, `REJECT`, `FILL`, `AMEND`, `CANCEL`, `EXPIRE`, `COMBO`, `OCO`, `QUOTE`, or `EVENT` |
| `--date` | No | all dates | Restrict to one trading date |
| `--from` | No | - | Start timestamp |
| `--to` | No | - | End timestamp |
| `--limit` | No | 500 | Maximum rows to return |

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

| Option       | Default          | Description                                    |
|--------------|------------------|--------------------------------------------------|
| `--date`     | latest available | Calendar date to query                            |
| `--index-id` | all indexes      | Limit to one index                                 |
| `--limit`    | 100              | Maximum rows to return                             |
| `--wide`     | off              | Include open/close aggregate market cap columns    |

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

| Option       | Required | Default   | Description                     |
|--------------|----------|-----------|------------------------------------|
| `--index-id` | Yes      | —         | Index to query                       |
| `--date`     | No       | all dates | Restrict to one trading date          |
| `--from`     | No       | —         | Start timestamp (ISO format)          |
| `--to`       | No       | —         | End timestamp (ISO format)            |
| `--limit`    | No       | 500       | Maximum rows to return                |

**Example output:**

```
ts                      | index_id | level   | aggregate_cap | divisor | session_state
-------------------------|----------|---------|----------------|---------|---------------
2026-06-14T09:00:00.000  | EDU100   | 1042.10 | 7350000000000  | 1.25    | OPENING_AUCTION
2026-06-14T09:00:05.500  | EDU100   | 1043.85 | 7362000000000  | 1.25    | CONTINUOUS
```

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
pm-engine --verbose --config engine_config.yaml
pm-stats --db data/stats.db
pm-api-gwy --config engine_config.yaml --instance desk
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
| `event_type` | No | Restrict to one normalized type such as `ACK`, `REJECT`, `FILL`, `AMEND`, `CANCEL`, `EXPIRE`, `COMBO`, `OCO`, `QUOTE`, or `EVENT` |
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

Compare the same symbol across multiple trading dates:

```bash
pm-stats-cli --format csv daily --symbol AAPL --limit 100 > aapl_history.csv
```

This gives you historical OHLCV to track trends, seasonal patterns, or support/resistance zones over time.

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
for a symbol:

```bash
pm-stats-cli --format csv index-daily --index-id EDU100 --limit 100 > edu100_history.csv
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

1. **Check daily summary recorded:**
   ```bash
   pm-stats-cli daily --date 2026-06-14
   ```
   Verify: all symbols present, volume > 0, open/close prices are reasonable.

2. **Check trade count:**
   ```bash
   pm-stats-cli --format csv trades --date 2026-06-14 | wc -l
   ```
   Verify: matches expected number from the trading floor.

3. **Check for any empty books:**
   ```bash
   pm-stats-cli snapshots --symbol AAPL --date 2026-06-14 | grep -E "(null|^-)"
   ```
   Empty books during active trading hours may indicate a problem.

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

- Was the order accepted or rejected?
- Did an amend reset priority?
- Which fills belong to this order ID?
- Was the order cancelled, expired, or linked to a combo/OCO group?
- Does API Gateway history match the live private WebSocket events seen by the client?



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
# Export as CSV
pm-stats-cli --format csv daily --limit 1000 > daily_stats.csv

# Upload to BigQuery, Redshift, Snowflake, etc.
bq load my_dataset.daily_stats daily_stats.csv

# Or load into local database
sqlite3 analysis.db < <<EOF
.mode csv
.import daily_stats.csv daily_stats
EOF
```

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
   `index_daily_stats`, and `index_level_snapshots`.

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

2. **Verify the symbol is correct (case-sensitive):**
   ```bash
   pm-stats-cli symbols
   ```
   Use exact symbol, e.g., `AAPL` not `aapl`.

3. **Check the time window for snapshots/trades:**
   ```bash
   pm-stats-cli snapshots --symbol AAPL --date 2026-06-14
   ```
   If using `--from` / `--to`, ensure they match the timestamp format (ISO 8601).

### Database is locked or "unable to open"

1. **`pm-stats` acquires short write locks during individual database transactions** (trade writes, snapshot writes, daily-stats flushes, order-event inserts). Between transactions no lock is held, so `pm-stats-cli` reads are never blocked. If you try to directly write to the database while `pm-stats` is running, you may get a transient lock error.

2. **Solution**: Use `pm-stats-cli` for queries, not direct `sqlite3` access while `pm-stats` is running.

3. **If you need to copy the DB for backup:**
   ```bash
   # Stop pm-stats first
   # Then copy the DB
   cp data/stats.db data/stats_backup.db
   # Then restart pm-stats
   ```

### Snapshot times seem wrong or are missing

- Snapshots are written when a `book.*` message arrives **and** the configured interval has elapsed since the last snapshot for that symbol.
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
pm-stats-cli --format csv trades --symbol AAPL --date 2026-06-14 | \
  awk -F, 'NR>1 {qty_sum += $5; price_qty += $4*$5} END {print price_qty/qty_sum}'
```

This calculates $\sum(price \times qty) / \sum(qty)$ from the trade log. Compare it to the value in `daily_stats` — they should match.



## See Also

- [Processes — pm-stats and pm-stats-cli](170-processes.md#pm-stats-statistics-recorder) — full process documentation
- [Processes — pm-ticker](170-processes.md#pm-ticker-scrolling-market-ticker) — live ticker that uses statistics data
- [Audit Trail](190-audit.md) — `pm-audit-cli` for querying the full event log
- [Persistence](180-persistence.md) — where all data files are stored

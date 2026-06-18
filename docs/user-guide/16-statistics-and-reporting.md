# Statistics and Reporting

!!! note "Learning objectives"
    After reading this page you will understand:

    - How to record market statistics continuously using `pm-stats`
    - How to query statistics data without writing SQL using `pm-stats-cli`
    - Common analyst workflows: end-of-day summaries, intraday price analysis, trade analysis
    - How to export statistics for external analysis (spreadsheets, BI tools)
    - How the statistics system integrates with other tools like `pm-ticker`
    - How to troubleshoot and validate statistics data



## Overview — Statistics Architecture

EduMatcher has a two-part statistics system:

| Component | Role | Type | Purpose |
|-----------|------|------|---------|
| **pm-stats** | Subscriber | Long-running process | Listens to all trades and book updates; writes OHLCV, snapshots, and trade log to `data/stats.db` |
| **pm-stats-cli** | Query tool | One-shot CLI | Reads from `data/stats.db` and prints human-friendly or machine-readable output without SQL |

This split keeps the recorder separate from the query interface, so you can:

- Start and stop `pm-stats-cli` at any time without affecting the live recorder
- Reload historical data after the engine restarts
- Build reports, dashboards, and automated analysis without needing live connections
- Keep the database read-only for auditing and compliance



## Data Folder Location

The location where `pm-stats` writes `data/stats.db` depends on how EduMatcher is installed:

| Running mode | Default location | Environment override |
|---|---|---|
| **Source checkout** (`poetry run pm-stats`) | `<repo>/src/data/stats.db` | `EDUMATCHER_DATA_DIR` |
| **Installed** (`pm-stats` on PATH) | `~/.local/share/edumatcher/stats.db` | `EDUMATCHER_DATA_DIR` |

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

| Scenario | Environment variable | Purpose |
|----------|----------------------|---------|
| **Installed user** (default for pipx) | (unset) → `~/.local/share/edumatcher` | Persistent user data folder |
| **Source checkout** (default for `poetry run`) | (unset) → `<repo>/src/data/` | Development environment |
| **Isolated sessions** | `~/sessions/morning` | Per-session isolation for demos or testing |
| **Shared network** | `/mnt/shared/trading/` | Shared data across machines |

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

See [Processes — Environment variables](10-processes.md#environment-variables) for full details on `EDUMATCHER_DATA_DIR` and `EDUMATCHER_CONFIG`.



## The Statistics Database Schema

All statistics are stored in `data/stats.db`, a SQLite 3 database with three tables:

### `daily_stats`

Aggregated OHLCV (open, high, low, close, volume) and related metrics for each symbol per day.

| Column | Type | Description |
|--------|------|-------------|
| `date` | TEXT | Calendar date `YYYY-MM-DD` |
| `symbol` | TEXT | Instrument ticker |
| `open_price` | REAL | First trade price of the day |
| `high_price` | REAL | Highest trade price |
| `low_price` | REAL | Lowest trade price |
| `close_price` | REAL | Last trade price |
| `volume` | INTEGER | Total traded quantity |
| `trade_count` | INTEGER | Number of trades |
| `vwap` | REAL | Volume-weighted average price |
| `open_bid` | REAL | Best bid at first book update of the day |
| `open_ask` | REAL | Best ask at first book update of the day |
| `close_bid` | REAL | Best bid at engine shutdown |
| `close_ask` | REAL | Best ask at engine shutdown |
| `largest_trade_qty` | INTEGER | Quantity of the single largest trade |
| `largest_trade_price` | REAL | Price of the single largest trade |

**Use case**: End-of-day summaries, daily trend analysis, multi-day performance tracking.

### `price_snapshots`

Intraday mid-price, bid/ask, and percentage-change history captured every 15 minutes per symbol.

| Column | Type | Description |
|--------|------|-------------|
| `ts` | TEXT | ISO-8601 timestamp (UTC, second precision) |
| `symbol` | TEXT | Instrument ticker |
| `mid_price` | REAL | `(best_bid + best_ask) / 2`; falls back to last trade price if book is empty |
| `best_bid` | REAL | Best bid at snapshot time (null if empty) |
| `best_ask` | REAL | Best ask at snapshot time (null if empty) |
| `pct_change` | REAL | Percentage change of mid-price from previous snapshot (e.g. `1.25` means +1.25 %) |

**Use case**: Intraday price trends, volatility analysis, spread history, detecting trading halts or gaps.

### `trade_log`

Append-only record of every matched trade — no aggregation, one row per trade.

| Column | Type | Description |
|--------|------|-------------|
| `ts` | TEXT | ISO-8601 timestamp (UTC, millisecond precision) |
| `trade_id` | TEXT | UUID from the engine (unique per trade) |
| `symbol` | TEXT | Instrument ticker |
| `price` | REAL | Execution price |
| `quantity` | INTEGER | Matched quantity |
| `buy_gateway_id` | TEXT | Gateway that submitted the buy order |
| `sell_gateway_id` | TEXT | Gateway that submitted the sell order |

**Use case**: Trade-by-trade analysis, flow analysis, detecting potential market manipulation, audit trails.



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
2. Request an initial book snapshot from the engine via PUSH (:5555)
3. Begin recording trades to `daily_stats` as they execute
4. Write intraday snapshots every 15 minutes
5. Write trade-by-trade records to `trade_log` immediately
6. At engine shutdown, record the final close bid/ask to `daily_stats`

**Startup options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | `data/stats.db` | Custom statistics database path |

Use `--db` if you want to record into a different location:

```bash
pm-stats --db /tmp/session_stats.db
```

**Important**: `pm-stats` must start **after** the engine binds its ZeroMQ sockets. If you start it before the engine, it will fail to connect.



## Querying with pm-stats-cli

Once `pm-stats` has recorded data, use `pm-stats-cli` to query without SQL.

### Basic Syntax

```bash
pm-stats-cli [--db data/stats.db] [--format table|json|csv] COMMAND [options]
```

**Global options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | `data/stats.db` | Path to statistics database |
| `--format` | `table` | Output format: `table` (human), `json` (structured), or `csv` (export) |
| `--no-header` | off | Omit header row (useful for CSV scripts) |

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

| Option | Default | Description |
|--------|---------|-------------|
| `--date` | latest available | Calendar date to query |
| `--symbol` | all | Limit to one symbol |
| `--limit` | 100 | Maximum rows to return |
| `--wide` | off | Include open/close bid/ask and largest-trade fields |

**Example output (default `table` format):**

```
date       | symbol | open_price | high_price | low_price | close_price | volume | trade_count | vwap
-----------|--------|------------|------------|-----------|-------------|--------|-------------|-------
2026-06-14 | AAPL   | 150        | 153.25     | 149.5     | 152.75      | 5000   | 12          | 151.82
2026-06-14 | MSFT   | 414        | 418.5      | 413       | 417         | 3200   | 8           | 415.63
```

#### `snapshots` — Intraday Price History

Show 15-minute snapshots from `price_snapshots` for one symbol over a time range.

```bash
pm-stats-cli snapshots --symbol AAPL
pm-stats-cli snapshots --symbol AAPL --date 2026-06-14
pm-stats-cli snapshots --symbol MSFT --from 2026-06-14T09:00:00+00:00 --to 2026-06-14T16:30:00+00:00
pm-stats-cli snapshots --symbol AAPL --limit 50
```

**Options:**

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--symbol` | Yes | — | Symbol to query |
| `--date` | No | all dates | Restrict to one trading date |
| `--from` | No | — | Start timestamp (ISO format) |
| `--to` | No | — | End timestamp (ISO format) |
| `--limit` | No | 500 | Maximum rows to return |

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

| Option | Default | Description |
|--------|---------|-------------|
| `--symbol` | all | Limit to one symbol |
| `--date` | all dates | Restrict to one trading date |
| `--from` | — | Start timestamp |
| `--to` | — | End timestamp |
| `--limit` | 200 | Maximum rows to return |

**Example output:**

```
ts                       | trade_id  | symbol | price | quantity | buy_gateway_id | sell_gateway_id
-------------------------|-----------|--------|-------|----------|----------------|----------------
2026-06-14T09:00:01.000  | T-AAPL-1  | AAPL   | 150   | 100      | TRADER01       | MM01
2026-06-14T09:00:05.123  | T-AAPL-2  | AAPL   | 150.5 | 50       | MM01           | TRADER02
2026-06-14T09:00:10.456  | T-AAPL-3  | AAPL   | 150.2 | 200      | TRADER02       | TRADER01
```

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
   You should see: `daily_stats`, `price_snapshots`, `trade_log`.

4. **Check for recent trades:**
   ```bash
   pm-stats-cli trades --limit 5
   ```
   If empty, no trades have executed yet. Execute a test trade first.

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

1. **`pm-stats` holds an exclusive write lock while running.** You can still read from `pm-stats-cli` concurrently, but if you try to directly write to the database, you'll get a lock error.

2. **Solution**: Use `pm-stats-cli` for queries, not direct `sqlite3` access while `pm-stats` is running.

3. **If you need to copy the DB for backup:**
   ```bash
   # Stop pm-stats first
   # Then copy the DB
   cp data/stats.db data/stats_backup.db
   # Then restart pm-stats
   ```

### Snapshot times seem wrong or are missing

- Snapshots are written every **15 minutes** when a `book.*` message arrives.
- If trading is light and no book updates occur for 15 minutes, no snapshot is recorded.
- This is by design — snapshots only record when the market moves.

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

- [Processes — pm-stats and pm-stats-cli](10-processes.md#pm-stats-statistics-recorder) — full process documentation
- [Processes — pm-ticker](10-processes.md#pm-ticker-scrolling-market-ticker) — live ticker that uses statistics data
- [Persistence](11-persistence.md) — where all data files are stored

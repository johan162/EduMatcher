# Statistics & Reporting

## Objective

Use the statistics service to record market data and query OHLCV, VWAP, and
trade history for analysis and reporting.

 


!!! abstract "Background reading"
    - [Statistics and Reporting](../operator-guide/part-4-run-a-market/060-statistics-and-reporting.md)

## Prerequisites

- Chapters 01–14 completed.
- `pm-stats` running and at least a few trades executed.

 

## Background

`pm-stats` subscribes to trade and book events and records them in a SQLite
database at `$EDUMATCHER_DATA_DIR/stats.db` (this resolves relative to
whatever data directory you configured in Chapter 00 — it is **not** a fixed
`data/stats.db` path in the current working directory). The `pm-stats-cli`
tool lets you query this data without writing SQL.

 

## Exercise 1: Start the Statistics Service

```bash
pm-stats
```

`pm-stats` logs at `WARNING` by default, so it starts silently. To see its
startup messages, run it with `-v`:

```bash
pm-stats -v
```

The startup lines include `opened stats DB connection path=...`, showing the
database path (which reflects your `EDUMATCHER_DATA_DIR`), and
`recording market statistics (Ctrl-C to stop)`; two more lines follow it
(`recorded tick metadata …`, `requested opening snapshots …`).

To confirm the active path with a stable command instead, run:

```bash
pm-stats --help
```

and check the default shown for `--db`, or simply verify the file exists
after the next exercise:

```bash
ls -la "$EDUMATCHER_DATA_DIR/stats.db"
```

:material-checkbox-blank-outline: **Checkpoint:** stats service running and `$EDUMATCHER_DATA_DIR/stats.db` exists.

 

## Exercise 2: Generate Some Trading Activity

Ensure `pm-mm-bot` (or AI traders) is quoting **both AAPL and MSFT** (the third
order below is a MSFT order; without a MSFT quote it is cancelled with
`INSUFFICIENT_LIQUIDITY`). A manual market-maker quote is pulled after its first
fill (Chapter 03), so the second and third orders would find no liquidity if you
rely on one. One bot per symbol, each with a start range, as in chapter 02:

```bash
pm-mm-bot --symbol AAPL --gap 0.10 --qty 500 --initial_min 149 --initial_max 151
pm-mm-bot --symbol MSFT --gap 0.16 --qty 300 --initial_min 419 --initial_max 421
```

(Both need their market-maker gateway, `MM_AAPL_01` and `MM_MSFT_01`, in the
configuration and no console connected as it. If you are still on the
`s150-nominal` example from chapter 14, use its `MM01` instead, as in that
chapter.) Execute a few manual trades:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
[TRADER01]> NEW|SYM=AAPL|SIDE=SELL|TYPE=MARKET|QTY=50
[TRADER01]> NEW|SYM=MSFT|SIDE=BUY|TYPE=MARKET|QTY=200
```

:material-checkbox-blank-outline: **Checkpoint:** trades executed and recorded by stats service.

 

## Exercise 3: Query the Daily OHLCV Summary

`pm-stats-cli` has no per-minute bar query — the closest built-in views are
`daily` (one OHLCV row per symbol per trading day) and `snapshots` (periodic
intraday price points, recorded at the interval set by
`pm-stats --snapshot-interval`, default 15 minutes). For today's daily
summary:

```bash
pm-stats-cli daily --symbol AAPL
```

Expected output (table or JSON):

```
date       | symbol | open_price | high_price | low_price | close_price | volume | trade_count | vwap
-----------|--------|------------|------------|-----------|-------------|--------|-------------|-------
2026-06-18 | AAPL   | 150        | 150.10     | 149.95    | 150.05      | 350    | 3           | 150.02
```

Note that `vwap` is already one of the columns in this row — see Exercise 4.

For an intraday price series instead of a single daily summary row, use
`snapshots`:

```bash
pm-stats-cli snapshots --symbol AAPL
```

:material-checkbox-blank-outline: **Checkpoint:** `daily` returns an OHLCV row for AAPL with today's date.

 

## Exercise 4: Read the VWAP Column

There is no standalone `vwap` command — the volume-weighted average price is
a column on the `daily` row you already queried in Exercise 3:

```bash
pm-stats-cli daily --symbol AAPL
```

Read the `vwap` column from the output. It reflects the volume-weighted
average price across all of today's trades for that symbol.

:material-checkbox-blank-outline: **Checkpoint:** you can locate the `vwap` value within `daily` output.

 

## Exercise 5: Query Trade Log

```bash
pm-stats-cli trades --symbol AAPL --limit 20
```

Shows up to 20 trades from `trade_log`, **oldest first** (it is a page, not a
"latest" list): `ts`, `trade_id`, `symbol`, `price`, `quantity`,
`aggressor_side`, `buy_gateway_id`, `sell_gateway_id`. When more rows exist
the command ends with a notice such as
`[WARN] Output truncated at --limit 20. More rows exist; re-run with --after <cursor>`;
copy that cursor to read the next page, or narrow the range with
`--from <ISO timestamp>` to start at the recent trades. `trade_id` is a
durable `run_seq-counter` string such as `000042-000000001`.
`aggressor_side` is `BUY` or `SELL` for a continuous match, and `AUCTION` for
an uncross print — so you can classify trades by which side crossed the
spread.

:material-checkbox-blank-outline: **Checkpoint:** trade log visible.

 

## Exercise 6: Multi-Symbol Summary

There is no dedicated `summary` verb. Omit `--symbol` on `daily` to get one
row per symbol instead of filtering to one:

```bash
pm-stats-cli daily
```

Each row shows, per symbol: `open_price`, `high_price`, `low_price`,
`close_price`, `volume`, `trade_count`, and `vwap` for the day. This does
**not** include current spread (best bid/ask) — for that, use `snapshots`
(most recent row per symbol) or query the live book directly with
`BOOK|SYM=<symbol>` in the operator console (`pm-admin`).

:material-checkbox-blank-outline: **Checkpoint:** `daily` with no `--symbol` filter returns one row per active symbol.

 

## Exercise 7: Export Data

```bash
pm-stats-cli --format csv trades --symbol AAPL > aapl_trades.csv
```

The CSV can be imported into Excel or a Jupyter notebook for further analysis.

:material-checkbox-blank-outline: **Checkpoint:** CSV export generated.

 

## What Gets Recorded

`pm-stats` writes to four tables (see
[Statistics and Reporting](../operator-guide/part-4-run-a-market/060-statistics-and-reporting.md)
for the full column reference):

| Table | Stored Fields |
|-------|--------------|
| `trade_log` | `ts`, `trade_id`, `symbol`, `price`, `quantity`, `buy_gateway_id`, `sell_gateway_id` — one row per trade, no aggregation |
| `price_snapshots` | `ts`, `symbol`, `mid_price`, `best_bid`, `best_ask`, `pct_change` — periodic intraday snapshots at `--snapshot-interval` (default 15 min) |
| `daily_stats` | `date`, `symbol`, `open/high/low/close_price`, `volume`, `trade_count`, `vwap`, plus open/close bid-ask and largest-trade fields — one row per symbol per day |
| `order_events` | Per-gateway private order lifecycle events (`ACK`, `FILL`, `AMEND`, `CANCEL`, etc.) — see `pm-stats-cli order-events` |

There is no separate table tracking session-phase transitions
(`PRE_OPEN`→`CONTINUOUS`, etc.) — `pm-stats` records market data and order
lifecycle events only.

 

## Summary

You can now:

- Configure and start the full exchange stack.
- Provide liquidity with manual MM quotes or `pm-mm-bot`.
- Trade using all order types and TIF values.
- Manage orders (amend, cancel, status).
- Run auctions and understand equilibrium pricing.
- Quote as a market maker with full lifecycle understanding.
- Use combo and OCO orders.
- Configure and trigger risk controls.
- Track P&L and positions.
- Subscribe to market data and drop-copy feeds.
- Generate realistic flow with AI traders.
- Record and query statistics.

## Reflection

Why does `pm-stats` need its own subscriber process and SQLite database
instead of the engine writing OHLCV/VWAP data directly? What would happen to
engine performance or reliability if it had to compute and serve statistics
queries itself, in-process, for every connected client?

## Further Reading

- [Statistics and Reporting](../operator-guide/part-4-run-a-market/060-statistics-and-reporting.md)
- [Processes, Environment and Ports](../reference-manual/part-1-command-line/010-processes-environment-and-ports.md)
- [Persistence](../operator-guide/part-6-observe-and-recover/010-persistence.md)
- [Market Data Feed](../protocols-and-clients/part-3-session-behaviour/030-calf-market-data-feed.md)

**Next:** [16 — Persistence & Recovery](160-persistence-recovery.md)

For a fuller hands-on tour of every viewer and observer process (including
`pm-stats` alongside `pm-viewer`, `pm-orders`, `pm-audit`, and `pm-board`),
see [18 — Exchange Observer Processes](180-exchange-observer-processes.md).

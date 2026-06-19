# Statistics & Reporting

## Objective

Use the statistics service to record market data and query OHLCV, VWAP, and
trade history for analysis and reporting.

---

## Prerequisites

- Chapters 01–14 completed.
- `pm-stats` running and at least a few trades executed.

---

## Background

`pm-stats` subscribes to trade and book events and records them in a SQLite
database (`data/stats.db`). The `pm-stats-cli` tool lets you query this data
without writing SQL.

---

## Exercise 1: Start the Statistics Service

```bash
pm-stats
```

Expected:

```
[INFO] Stats service connected — recording to data/stats.db
```

:material-checkbox-blank-outline: **Checkpoint:** stats service running and recording.

---

## Exercise 2: Generate Some Trading Activity

Ensure MMs and (optionally) AI traders are running. Execute a few manual trades:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
TRADER01> NEW|SYM=AAPL|SIDE=SELL|TYPE=MARKET|QTY=50
TRADER01> NEW|SYM=MSFT|SIDE=BUY|TYPE=MARKET|QTY=200
```

:material-checkbox-blank-outline: **Checkpoint:** trades executed and recorded by stats service.

---

## Exercise 3: Query OHLCV Data

```bash
pm-stats-cli ohlcv --symbol AAPL --interval 1m
```

Expected output (table or JSON):

```
timestamp           | open   | high   | low    | close  | volume
2026-06-18 09:30:00 | 150.05 | 150.10 | 149.95 | 150.05 | 350
```

:material-checkbox-blank-outline: **Checkpoint:** OHLCV data returned for AAPL.

---

## Exercise 4: Query VWAP

```bash
pm-stats-cli vwap --symbol AAPL
```

Shows the volume-weighted average price across all trades in the current session.

:material-checkbox-blank-outline: **Checkpoint:** VWAP value returned.

---

## Exercise 5: Query Trade Log

```bash
pm-stats-cli trades --symbol AAPL --limit 20
```

Shows the last 20 trades with timestamp, price, quantity, and aggressor side.

:material-checkbox-blank-outline: **Checkpoint:** trade log visible.

---

## Exercise 6: Multi-Symbol Summary

```bash
pm-stats-cli summary
```

Shows a per-symbol overview:

- Last price, day high, day low
- Total volume
- Number of trades
- Current spread

:material-checkbox-blank-outline: **Checkpoint:** summary covers all active symbols.

---

## Exercise 7: Export Data

```bash
pm-stats-cli trades --symbol AAPL --format csv > aapl_trades.csv
```

The CSV can be imported into Excel or a Jupyter notebook for further analysis.

:material-checkbox-blank-outline: **Checkpoint:** CSV export generated.

---

## What Gets Recorded

| Event | Stored Fields |
|-------|--------------|
| Trade | timestamp, symbol, price, qty, aggressor side, buyer/seller gateway |
| Book snapshot | timestamp, symbol, best bid, best ask, bid size, ask size |
| OHLCV bar | open, high, low, close, volume per configurable interval |
| Session event | timestamp, old state, new state |

---

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

## Further Reading

- [Statistics and Reporting](../user-guide/16-statistics-and-reporting.md)
- [Processes](../user-guide/10-processes.md)
- [Persistence](../user-guide/11-persistence.md)
- [Market Data Feed](../concepts/06-concepts-market-data-feed.md)

**Next:** [16 — Persistence & Recovery](16-persistence-recovery.md)

# Exchange Observer Processes

## Objective

Run the viewer and observer processes side by side so you can see the same
exchange activity from different operational viewpoints: book depth, cross-gateway
orders, ticker tape, market board, audit trail, statistics, and clearing/P&L.

 

## Prerequisites

- Chapters 01–03 completed, with `pm-engine`, `pm-scheduler`, and at least
  `TRADER01` connected.
- Market-maker liquidity from chapter 02, or another gateway placing opposite-side
  orders so trades and book updates are visible.
- Several terminals available. These observer processes are intentionally separate
  so you can start, stop, and compare them independently.

 

## Background

EduMatcher observers subscribe to the engine's market-data stream. They do not
own the order book and they do not submit orders. Their job is to make activity
visible from different angles.

| Process | Viewpoint | Best for |
|---------|-----------|----------|
| `pm-viewer` | One symbol's order book | Depth, spread, recent trades |
| `pm-board` | Multi-symbol dashboard | Large-screen market overview |
| `pm-ticker` | Scrolling market tape | Compact live price/trade context |
| `pm-orders` | Cross-gateway order monitor | Resting order state across gateways |
| `pm-audit` | Raw event log | Debugging and replay-style inspection |
| `pm-stats` | Statistics recorder | Persisting OHLCV, VWAP, trade log |
| `pm-stats-cli` | Statistics query CLI | Reading persisted stats |
| `pm-clearing` | Positions and P&L | Settlement and participant exposure |

 

## Exercise 1: Start the Baseline Exchange

Start the engine and scheduler if they are not already running:

```bash
pm-engine --config engine_config.yaml
pm-scheduler
```

Connect two trader gateways:

```bash
pm-alf-console --id TRADER01
pm-alf-console --id TRADER02
```

Create one resting order so observers have a visible book update:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=149.80|TIF=DAY
```

:material-checkbox-blank-outline: **Checkpoint:** `TRADER01` receives an acknowledgement and `ORDERS` shows the order.

 

## Exercise 2: Watch One Book with pm-viewer

In a new terminal, start the single-symbol book viewer:

```bash
pm-viewer --symbol AAPL --depth 10
```

From `TRADER01`, add or cancel another resting order:

```
TRADER01> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=50|PRICE=150.20|TIF=DAY
```

`pm-viewer` should update the bid/ask depth and recent trade area when market
data changes.

:material-checkbox-blank-outline: **Checkpoint:** you can identify best bid, best ask, spread, and recent trades in `pm-viewer`.

 

## Exercise 3: Monitor Orders Across Gateways with pm-orders

Start the cross-gateway order monitor:

```bash
pm-orders
```

For a narrower view, filter to one gateway:

```bash
pm-orders --gateway TRADER01
```

Place one order from each trader:

```
TRADER01> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=25|PRICE=419.00|TIF=DAY
TRADER02> NEW|SYM=TSLA|SIDE=SELL|TYPE=LIMIT|QTY=10|PRICE=252.00|TIF=DAY
```

Compare this process with the gateway-local `ORDERS` command. `ORDERS` is useful
inside one gateway; `pm-orders` is useful when you want an exchange-wide monitor.

:material-checkbox-blank-outline: **Checkpoint:** `pm-orders` shows orders from both gateways, while `ORDERS` shows only the current gateway's cache.

 

## Exercise 4: Record the Event Stream with pm-audit

Start the audit logger in terminal mode:

```bash
pm-audit --terminal
```

To also write the log to a known file:

```bash
pm-audit --terminal --log-file "$EDUMATCHER_DATA_DIR/audit.log"
```

Execute a trade:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=25
```

Watch the raw topics and payloads printed by `pm-audit`. This is the most direct
view of what the engine publishes.

:material-checkbox-blank-outline: **Checkpoint:** you can find the order acknowledgement, fill, trade, and book update events in the audit output.

 

## Exercise 5: Build Persistent Statistics with pm-stats

Start the statistics recorder:

```bash
pm-stats
```

Execute several trades, then query the database:

```bash
pm-stats-cli trades --symbol AAPL --limit 10
pm-stats-cli ohlcv --symbol AAPL --interval 1m
pm-stats-cli vwap --symbol AAPL
pm-stats-cli summary
```

`pm-stats` is a long-running subscriber. `pm-stats-cli` is a read-only query tool
for the SQLite database written by `pm-stats`.

:material-checkbox-blank-outline: **Checkpoint:** `pm-stats-cli` shows recent trades and at least one aggregate statistic after activity occurs.

 

## Exercise 6: Launch the Scrolling Ticker

Start the ticker with short intervals for training:

```bash
pm-ticker --interval 5 --db-interval 30
```

The ticker combines live book updates with statistics from `stats.db` when they
are available. If no symbols appear yet, create a book update or trade in a
gateway.

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=20|PRICE=149.70|TIF=DAY
```

:material-checkbox-blank-outline: **Checkpoint:** `pm-ticker` prints periodic lines with symbols, last price or best bid/ask, and statistics when available.

 

## Exercise 7: Launch the Multi-Symbol Board

Start the market board:

```bash
pm-board --rows 8 --interval 10
```

The board shows multiple symbols at once and updates as `book.*` and
`trade.executed` events arrive. Press Enter to advance pages manually if you have
more symbols than rows.

:material-checkbox-blank-outline: **Checkpoint:** `pm-board` shows AAPL, MSFT, and TSLA in a single market overview.

 

## Exercise 8: Track Positions and P&L with pm-clearing

Start clearing in a separate terminal:

```bash
pm-clearing
```

Create a trade between two gateways:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=150.00|TIF=DAY
TRADER02> NEW|SYM=AAPL|SIDE=SELL|TYPE=MARKET|QTY=50
```

`pm-clearing` consumes `trade.executed` events and maintains per-gateway position
and P&L. It also writes a clearing report CSV in the data directory.

:material-checkbox-blank-outline: **Checkpoint:** `pm-clearing` shows the changed position or records the trade in its report.

 

## Exercise 9: Compare the Views

For one trade, identify where each process shows it:

| Question | Process to use |
|----------|----------------|
| What is the current top of book? | `pm-viewer` or `pm-board` |
| Which gateways have live/resting orders? | `pm-orders` |
| What exact messages were published? | `pm-audit` |
| What trades and aggregates were persisted? | `pm-stats-cli` |
| What changed in participant positions/P&L? | `pm-clearing` |
| What is the compact live tape view? | `pm-ticker` |

:material-checkbox-blank-outline: **Checkpoint:** explain why no single observer replaces the others.

 

## Summary

You have now run the main exchange observer processes and seen how each one
answers a different operational question. In normal use, start only the observers
you need for the lesson or scenario you are running.

## Reflection

Why does EduMatcher split viewing responsibilities across several small
observer processes (`pm-viewer`, `pm-orders`, `pm-audit`, `pm-stats`,
`pm-board`) instead of one all-in-one dashboard? What would you lose in a
classroom setting if all of them were combined into a single process that
had to be restarted together?

## Further Reading

- [Processes](../user-guide/10-processes.md)
- [Messages](../user-guide/09-messages.md)
- [Market Data & Drop Copy](13-market-data-drop-copy.md)
- [Statistics & Reporting](15-statistics-reporting.md)
- [Market Data Feed](../concepts/06-concepts-market-data-feed.md)

**Next:** [19 - Advanced Admin Operations](19-advanced-admin-operations.md)

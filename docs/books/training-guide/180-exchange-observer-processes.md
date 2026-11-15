# Exchange Observer Processes

## Objective

Run the viewer and observer processes side by side so you can see the same
exchange activity from different operational viewpoints: book depth, cross-gateway
orders, ticker tape, market board, audit trail, statistics, and clearing/P&L.

 


!!! abstract "Background reading"
    - [Processes, Environment and Ports](../reference-manual/part-1-command-line/010-processes-environment-and-ports.md)

## Prerequisites

- Chapter 17 completed, with its exchange still running: `pm-engine`,
  `pm-stats`, `pm-clearing`, `pm-audit --terminal` and `pm-viewer`, the market
  reopened after its Exercise 9, `TRADER01` and `TRADER02` connected, and the
  three market makers quoting.
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

 

Three of the processes in the table have had a chapter each and are already
running from the capstone: `pm-audit` (chapter 13), `pm-stats` and
`pm-stats-cli` (chapter 15) and `pm-clearing` (chapter 12). Do not start
second copies — two `pm-clearing` processes would record every trade twice.
This chapter adds the four live screens, then compares all of them.

## Exercise 1: Watch One Book with pm-viewer

The capstone already started `pm-viewer --symbol AAPL`. Leave it running, or
restart it with an explicit depth:

```bash
pm-viewer --symbol AAPL --depth 10
```

From `TRADER01`, add or cancel a resting order:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=50|PRICE=150.20|TIF=DAY
```

`pm-viewer` should update the bid/ask depth and recent trade area when market
data changes.

:material-checkbox-blank-outline: **Checkpoint:** you can identify best bid, best ask, spread, and recent trades in `pm-viewer`.

 

## Exercise 2: Monitor Orders Across Gateways with pm-orders

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
[TRADER01]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=25|PRICE=419.00|TIF=DAY
[TRADER02]> NEW|SYM=TSLA|SIDE=SELL|TYPE=LIMIT|QTY=10|PRICE=252.00|TIF=DAY
```

Compare this process with the gateway-local `ORDERS` command. `ORDERS` is useful
inside one gateway; `pm-orders` is useful when you want an exchange-wide monitor.
`pm-orders` only shows events it saw arrive, so start it before the orders.
A rejected order shows `?` in most columns: the rejection carries the order
ID, not the order.

:material-checkbox-blank-outline: **Checkpoint:** `pm-orders` shows orders from both gateways, while `ORDERS` shows only the current gateway's cache.

 

## Exercise 3: Launch the Scrolling Ticker

Start the ticker. The book updates it receives are pushed live by the engine;
`--db-interval` controls only how often it re-reads the daily aggregates from
`stats.db`, so a short value makes those refresh quickly during a lesson:

```bash
pm-ticker --db-interval 30
```

The ticker combines live book updates with the day's high, low, volume and
change from `stats.db`, which the capstone's `pm-stats` has been writing. If no symbols appear yet, create a book update or trade in a
gateway.

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=20|PRICE=149.70|TIF=DAY
```

:material-checkbox-blank-outline: **Checkpoint:** `pm-ticker` prints periodic lines with symbols, last price or best bid/ask, and statistics when available.

 

## Exercise 4: Launch the Multi-Symbol Board

Start the market board:

```bash
pm-board --rows 8 --interval 10
```

The board shows multiple symbols at once and updates as `book.*` and
`trade.executed` events arrive. Press Enter to advance pages manually if you have
more symbols than rows.

:material-checkbox-blank-outline: **Checkpoint:** `pm-board` shows AAPL, MSFT, and TSLA in a single market overview.

 

## Exercise 5: Compare the Views

Make one more trade, so every observer has something new to show:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=150.00|TIF=DAY
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=MARKET|QTY=50
```

For one trade, identify where each process shows it:

| Question | Process to use |
|----------|----------------|
| What is the current top of book? | `pm-viewer` or `pm-board` |
| Which gateways have live/resting orders? | `pm-orders` |
| What exact messages were published? | `pm-audit` |
| What trades and aggregates were persisted? | `pm-stats-cli` |
| What changed in participant positions/P&L? | `pm-clearing-cli positions` |
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

- [Processes, Environment and Ports](../reference-manual/part-1-command-line/010-processes-environment-and-ports.md)
- [Messages](../protocols-and-clients/part-5-message-reference/010-message-reference.md)
- [Market Data & Drop Copy](130-market-data-drop-copy.md)
- [Statistics & Reporting](150-statistics-reporting.md)
- [Market Data Feed](../protocols-and-clients/part-3-session-behaviour/030-calf-market-data-feed.md)

**Next:** [19 - Advanced Admin Operations](190-advanced-admin-operations.md)

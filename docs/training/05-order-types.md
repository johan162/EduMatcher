# 05 — Order Types Deep Dive

## Objective

Explore every order type beyond basic LIMIT and MARKET — STOP, STOP_LIMIT, FOK,
IOC, ICEBERG, and TRAILING_STOP — through practical exercises.

---

## Exercise 1: Stop Order

A stop order becomes a market order when the trigger price is reached.

Place a stop-sell (protect a long position if price drops):

```
TRADER01> NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP|QTY=100|STOP_PRICE=149.50|TIF=DAY
```

The order is dormant until AAPL trades at or below 149.50. Once triggered, it
executes as a market order.

To test: from TRADER02, sell aggressively to push the price down past the stop.

:material-checkbox-blank-outline: **Checkpoint:** stop order triggered and filled after price drop.

---

## Exercise 2: Stop-Limit Order

Like a stop, but becomes a limit order (not market) when triggered:

```
TRADER01> NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP_LIMIT|QTY=100|STOP_PRICE=149.50|PRICE=149.40|TIF=DAY
```

When the stop triggers at 149.50, a limit sell at 149.40 is placed. If the
market gaps below 149.40, the order may not fill (unlike a plain stop).

:material-checkbox-blank-outline: **Checkpoint:** stop-limit triggers and rests as a limit order.

---

## Exercise 3: Fill-or-Kill (FOK)

FOK demands the entire quantity in a single fill or cancels:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=FOK|QTY=1000|PRICE=150.10
```

If the ask side doesn't have 1000 shares at or below 150.10, the order is
immediately cancelled.

Try with a smaller qty that the MM can fill:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=FOK|QTY=100|PRICE=150.10
```

:material-checkbox-blank-outline: **Checkpoint:** large FOK cancelled; small FOK filled.

---

## Exercise 4: Immediate-or-Cancel (IOC)

IOC fills as much as possible immediately, then cancels the rest:

```
TRADER01> NEW|SYM=MSFT|SIDE=BUY|TYPE=IOC|QTY=1000|PRICE=420.20
```

If only 300 are available at the ask, you get 300 filled and 700 cancelled.

:material-checkbox-blank-outline: **Checkpoint:** partial fill + cancellation of remainder.

---

## Exercise 5: Iceberg Order

An iceberg shows only a visible "peak" quantity while hiding the reserve:

```
TRADER01> NEW|SYM=TSLA|SIDE=BUY|TYPE=ICEBERG|QTY=1000|PRICE=249.75|PEAK_QTY=100|TIF=DAY
```

The book shows only 100 visible. When those 100 fill, another 100 automatically
appears until the full 1000 is done.

Check the book:

```
TRADER01> BOOK|SYM=TSLA
```

You should see a 100-lot bid, not 1000.

:material-checkbox-blank-outline: **Checkpoint:** only peak quantity visible in the book.

---

## Exercise 6: Trailing Stop

A trailing stop follows the market by a fixed offset:

```
TRADER01> NEW|SYM=AAPL|SIDE=SELL|TYPE=TRAILING_STOP|QTY=100|TRAIL_OFFSET=0.20|TIF=DAY
```

If AAPL rises to 150.50, the stop moves to 150.30 (150.50 − 0.20).
If AAPL then falls to 150.30, the stop triggers and sells at market.

The stop only moves **up** (for a sell) or **down** (for a buy) — never against
you.

:material-checkbox-blank-outline: **Checkpoint:** trailing stop triggers after price reversal.

---

## Order Type Summary

| Type | Execution | Rests? | Key Parameter |
|------|-----------|--------|---------------|
| MARKET | Immediate, best price | No | — |
| LIMIT | At price or better | Yes | `PRICE` |
| STOP | Dormant → market on trigger | Until triggered | `STOP_PRICE` |
| STOP_LIMIT | Dormant → limit on trigger | Until triggered, then yes | `STOP_PRICE`, `PRICE` |
| FOK | All-or-nothing, immediate | No | `QTY`, `PRICE` |
| IOC | Fill what you can, cancel rest | No | `QTY`, `PRICE` |
| ICEBERG | Hidden reserve, visible peak | Yes | `PEAK_QTY` |
| TRAILING_STOP | Dynamic stop follows market | Until triggered | `TRAIL_OFFSET` |

---

**Next:** [06 — Time-in-Force & Sessions](06-time-in-force-sessions.md)

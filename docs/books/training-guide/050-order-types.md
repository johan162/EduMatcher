# Order Types Deep Dive

## Objective

Explore every order type beyond basic LIMIT and MARKET — STOP, STOP_LIMIT, FOK,
IOC, ICEBERG, and TRAILING_STOP — through practical exercises.

 


!!! abstract "Background reading"
    - [Order Types](../participant-guide/part-2-orders/020-order-types.md)

## Prerequisites

- Chapters 01–04 completed.
- At least one trader gateway connected with active MM liquidity.

 

## Deterministic Trigger Setup

Stop and stop-limit orders only trigger when the market actually **trades**
through their trigger price — quotes alone never trigger them. To make the
exercises below behave exactly as described, build the AAPL book yourself
before each one, with the market maker's console placing ordinary limit
orders:

1. Clear AAPL from the operator console (this cancels every order and quote
   on it), and stop any `pm-mm-bot` quoting AAPL:

    ```
    [GW_ADMIN|ADMIN]> CANCEL_SYM|SYM=AAPL
    ```

2. Give the book two bids, one above and one below the trigger level you
   will use (149.50):

    ```
    [MM_AAPL_01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=149.60|TIF=DAY
    [MM_AAPL_01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=200|PRICE=149.30|TIF=DAY
    ```

3. Make a trade **above** the trigger, so the last traded price is 149.60 and
   a sell stop at 149.50 is not triggered the moment you place it:

    ```
    [TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=149.60|TIF=DAY
    ```

Now only the 200-share bid at 149.30 is left in the book.

 

## Exercise 1: Stop Order

A stop order becomes a market order when the trigger price is reached.

After the setup above, place a stop-sell — the order a trader holding AAPL
would use to limit the loss if the price falls:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP|QTY=100|STOP=149.50|TIF=DAY
```

The order is acknowledged and then lies dormant: it is not in the visible
book. Now let the market fall through 149.50 — `TRADER02` sells into the
149.30 bid:

```
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=149.30|TIF=DAY
```

That trade at 149.30 is at or below the stop, so the stop triggers and becomes
a market sell, which fills against the remaining 100 bid at 149.30:

```
[<time>] FILL      <order_id>  qty=100 @149.3  remaining=0  [FILLED]
```

Interpretation: 149.50 was the **trigger**, not the execution price. A stop
guarantees that you get out, not at what price — in a falling market the fill
can be well below the stop.

:material-checkbox-blank-outline: **Checkpoint:** the stop triggered on a trade below 149.50 and filled at 149.30.

 

## Exercise 2: Stop-Limit Order

Like a stop, but becomes a limit order (not a market order) when triggered.
Repeat the setup, but with the lower bid at **149.00** instead of 149.30, so
that the market will *gap* through your limit:

```
[GW_ADMIN|ADMIN]> CANCEL_SYM|SYM=AAPL
[MM_AAPL_01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=149.60|TIF=DAY
[MM_AAPL_01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=200|PRICE=149.00|TIF=DAY
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=149.60|TIF=DAY
```

Place the stop-limit:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP_LIMIT|QTY=100|STOP=149.50|PRICE=149.40|TIF=DAY
```

`STOP=149.50` controls **when** the order is activated; `PRICE=149.40` is the
**worst price** you will accept once it is. Now trade through both levels:

```
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=149.00|TIF=DAY
```

The trade at 149.00 triggers the stop, and a limit sell at 149.40 is placed —
but the only bid left is at 149.00, below your limit, so nothing fills. The
order now **rests** on the ask side at 149.40 (check with `BOOK|SYM=AAPL` and
`ORDERS`). A plain stop would have sold at 149.00; the stop-limit protected
the price and gave up the certainty of getting out.

:material-checkbox-blank-outline: **Checkpoint:** the stop-limit triggered and rests as a limit sell at 149.40.

Before the next exercise, cancel the resting stop-limit and let the market
maker quote AAPL again:

```
[TRADER01]> CANCEL|ID=<stop-limit order id>
[MM_AAPL_01]> QUOTE|SYM=AAPL|BID=149.95|ASK=150.05|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=AAPL-MM-005
```

 

## Exercise 3: Fill-or-Kill (FOK)

FOK demands the entire quantity in a single all-or-nothing execution (which may sweep several resting orders) or cancels:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=FOK|QTY=1000|PRICE=150.10
```

The market maker offers only 500, so the ask side doesn't have 1000 shares at
or below 150.10, and the order is rejected at once with
`code=INSUFFICIENT_LIQUIDITY` — nothing trades.

Try with a smaller qty that the MM can fill:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=FOK|QTY=100|PRICE=150.10
```

:material-checkbox-blank-outline: **Checkpoint:** large FOK rejected; small FOK filled.

 

## Exercise 4: Immediate-or-Cancel (IOC)

IOC fills as much as possible immediately, then cancels the rest:

```
[TRADER01]> NEW|SYM=MSFT|SIDE=BUY|TYPE=IOC|QTY=1000|PRICE=420.20
```

If only 300 are available at the ask, you get 300 filled and 700 cancelled.

:material-checkbox-blank-outline: **Checkpoint:** partial fill + cancellation of remainder.

 

## Exercise 5: Iceberg Order

An iceberg shows only a visible "peak" quantity while hiding the reserve:

```
[TRADER01]> NEW|SYM=TSLA|SIDE=BUY|TYPE=ICEBERG|QTY=1000|PRICE=249.70|VISIBLE=100|TIF=DAY
```

The book shows only 100 visible. When those 100 fill, another 100 automatically
appears until the full 1000 is done.

Check the book:

```
[GW_ADMIN|ADMIN]> BOOK|SYM=TSLA
```

You should see a 100-lot bid at 249.70, not 1000. (The price is one tick
below the market maker's 249.75 bid on purpose: `BOOK` adds up all orders at
one price, so at 249.75 you would see the market maker's 200 plus your 100.)

:material-checkbox-blank-outline: **Checkpoint:** only peak quantity visible in the book.

 

## Exercise 6: Trailing Stop

A trailing stop follows the market by a fixed offset:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=SELL|TYPE=TRAILING_STOP|QTY=100|TRAIL=0.20|TIF=DAY
```

No `STOP=` is given here, so the engine derives the initial trigger from the
last traded price minus `TRAIL` (this works because AAPL has already traded
in earlier exercises). If AAPL has no trade history yet, `TRAILING_STOP`
without an explicit `STOP=` is **rejected** — pass `STOP=<price>` explicitly
to set the initial trigger yourself, e.g. `STOP=149.50`.

If AAPL rises to 150.50, the stop moves to 150.30 (150.50 − 0.20).
If AAPL then falls to 150.30, the stop triggers and sells at market.

The stop only moves **up** (for a sell) or **down** (for a buy) — never against
you.

:material-checkbox-blank-outline: **Checkpoint:** trailing stop triggers after price reversal.

 

## Order Type Summary

| Type | Execution | Rests? | Key Parameter |
|------|-----------|--------|---------------|
| MARKET | Immediate, best price | No | — |
| LIMIT | At price or better | Yes | `PRICE` |
| STOP | Dormant → market on trigger | Until triggered | `STOP` |
| STOP_LIMIT | Dormant → limit on trigger | Until triggered, then yes | `STOP`, `PRICE` |
| FOK | All-or-nothing, immediate | No | `QTY`, `PRICE` |
| IOC | Fill what you can, cancel rest | No | `QTY`, `PRICE` |
| ICEBERG | Hidden reserve, visible peak | Yes | `VISIBLE` |
| TRAILING_STOP | Dynamic stop follows market | Until triggered | `TRAIL` |

 

## Reflection

Why does STOP_LIMIT exist at all, given that a plain STOP order guarantees
execution once triggered? What real trading scenario would make a trader
prefer a STOP_LIMIT's "might not fill" risk over a STOP's "might fill at a
bad price" risk?

## Further Reading

- [Order Types](../participant-guide/part-2-orders/020-order-types.md)
- [ALF Protocol — Single-leg Orders](../protocols-and-clients/part-2-specifications/010-alf.md)

 

**Next:** [06 — Time-in-Force & Sessions](060-time-in-force-sessions.md)

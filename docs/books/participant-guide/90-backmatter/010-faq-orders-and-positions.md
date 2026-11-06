# FAQ: Orders, Sessions and Positions

Questions that come up once you trade beyond the first day: why an order type
was rejected or did not trigger, how average cost and saved orders behave, and
what self-match prevention does. The first-day questions are in the Quick Start
Guide's [FAQ & Common Mistakes](../../quick-start/90-backmatter/010-faq.md);
how the exchange is installed, configured and operated is in the Operator's
Guide's [FAQ: Setup and Operation](../../operator-guide/90-backmatter/010-faq-setup-and-operation.md).

## Order types

### Why was my IOC order rejected?

IOC (Immediate-Or-Cancel) orders **cannot rest on the book**, so they are
rejected during any non-matching phase (PRE_OPEN, OPENING_AUCTION,
CLOSING_AUCTION, CLOSED). IOC is only valid during `CONTINUOUS` trading.

```text
[09:20:11.403] REJECTED  6f5471b08c2d3eb970dc8c864bf270cb code=SESSION_NOT_PERMITTED  IOC orders not accepted during PRE_OPEN
```

The same applies to `MARKET` and `FOK` orders.

**Fix:** Type `SESSION` in the trader console to see the current phase, then
wait for `CONTINUOUS`, or use a `LIMIT` order with `TIF=DAY` if you are
willing to have the order rest.


### Why didn't my STOP order trigger?

STOP orders only trigger from **last trade price** events. If no trades have
occurred since you submitted the STOP, the trigger is never evaluated —
regardless of the current bid/ask quotes.

```
# This SELL STOP at 148 won't fire if no trades have happened yet
NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP|QTY=100|STOP=148.00
```

**Fix:** Check whether any trades have printed in the engine output (`--verbose`
mode) or in the audit log. A stop only becomes relevant once the market is
actively trading through its trigger level.

Also check the trigger direction. A **SELL STOP** triggers when `last_trade_price <= stop_price`.
If the market is above your stop, it won't fire until price falls *to* or *through* it.

See [Stop Trigger Logic](../part-2-orders/020-order-types.md#stop-trigger-logic) for full details.


### Why did my STOP_LIMIT order trigger but not fill?

This is expected behavior. When a STOP_LIMIT triggers, it converts to a
**LIMIT order at your specified `PRICE=`**. If the market has moved past that
limit price before the converted order can match, it sits on the book unfilled.

**Example:** SELL STOP_LIMIT with `STOP=148.00` and `PRICE=147.50`.
If the market gaps down to $146.00 before the converted limit can fill,
your order rests at $147.50 — but nobody is bidding that high. You are
protected from filling at $146.00, but you may not fill at all.

**Tradeoff:** STOP gives fill certainty. STOP_LIMIT gives price certainty.
Neither gives both.


### My FOK order was rejected even though there was liquidity. Why?

FOK checks whether the **entire quantity** can be filled at the limit price
*before* executing. It does not execute at all unless the full size is
available.

```
# Book has only 80 shares at 150.00, but you want 100
NEW|SYM=AAPL|SIDE=BUY|TYPE=FOK|QTY=100|PRICE=150.00
# → REJECTED because 80 < 100
```

**Fix:** Reduce `QTY` to match available liquidity, or use a `LIMIT` order
and accept a partial fill.


---

## Positions and P&L

### Why does my average cost change when I buy more shares?

When you add to an existing position, your **VWAP average cost** updates to
reflect the new shares at the new price. This is standard practice for
tracking the true cost basis of a position built over multiple trades.

**Example:**
```
Buy 100 shares @ 150.00  →  avg_cost = 150.00
Buy 100 shares @ 152.00  →  avg_cost = (150 × 100 + 152 × 100) / 200 = 151.00
```

See [P&L & Clearing — VWAP Average Cost](../part-5-positions-and-results/010-positions-and-pnl.md#vwap-average-cost).


---

## Saved orders

### My GTC orders didn't reload after restart. Why?

GTC orders are written to `data/gtc_orders.json` **on engine shutdown** (when
you press Ctrl-C or the scheduler sends a CLOSED transition). If the engine was
killed forcefully (`kill -9` or a crash), the file was not written.

**Fix:** Check whether `data/gtc_orders.json` exists and has recent content.
If the engine was killed mid-session, the file may be stale or missing.


---

## Self-match prevention

### What is SMP and why did my order get cancelled?

**Self Match Prevention (SMP)** stops you from accidentally trading against
your own resting orders. If you submit a buy that would match a sell you
already have on the same book, SMP kicks in.

```
# Submit a buy that would cross with your own resting sell
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=151.00|SMP=CANCEL_AGGRESSOR
```

With `SMP=CANCEL_AGGRESSOR`, the incoming buy is cancelled instead of
filling against your own sell. Options:

| Value | Behaviour |
|-------|-----------|
| `NONE` | No SMP — you can trade against yourself |
| `CANCEL_AGGRESSOR` | The incoming order is cancelled |
| `CANCEL_RESTING` | The resting order is cancelled |
| `CANCEL_BOTH` | Both orders are cancelled |


---

## Prices

### Why does the engine use integer ticks instead of float prices?

Float arithmetic can introduce tiny representation errors in comparisons and
aggregation. Using integer ticks makes price-time matching and level math exact.


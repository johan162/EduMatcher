# FAQ & Common Mistakes

Common questions and gotchas when learning EduMatcher.

---

## Orders & Execution

### Why was my IOC order rejected?

IOC (Immediate-Or-Cancel) orders **cannot rest on the book**, so they are
rejected during any non-matching phase (PRE_OPEN, OPENING_AUCTION,
CLOSING_AUCTION, CLOSED). IOC is only valid during `CONTINUOUS` trading.

```
[GW01] order.ack: accepted=false reason="IOC rejected outside CONTINUOUS phase"
```

**Fix:** Check the current session phase with `SESSION` at the gateway prompt,
then wait for CONTINUOUS or switch to a `LIMIT` order with `TIF=DAY` if you're
willing to have the order rest.

---

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

See [Stop Trigger Logic](order-types.md#9-stop-trigger-logic) for full details.

---

### Why did my STOP_LIMIT order trigger but not fill?

This is expected behaviour. When a STOP_LIMIT triggers, it converts to a
**LIMIT order at your specified `PRICE=`**. If the market has moved past that
limit price before the converted order can match, it sits on the book unfilled.

**Example:** SELL STOP_LIMIT with `STOP=148.00` and `PRICE=147.50`.
If the market gaps down to $146.00 before the converted limit can fill,
your order rests at $147.50 — but nobody is bidding that high. You are
protected from filling at $146.00, but you may not fill at all.

**Tradeoff:** STOP gives fill certainty. STOP_LIMIT gives price certainty.
Neither gives both.

---

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

### Why is my LIMIT order filling at a different price than I specified?

Your limit price is the **worst** price you'll accept — not necessarily the
price you'll get. If better prices are available, you fill at those better
prices.

**Example:** You submit `BUY LIMIT QTY=100 PRICE=151.00` but the book has asks
at 149.90 and 150.20. You fill at 149.90 and 150.20 (both better than your
limit of 151.00), not at 151.00.

This is called **price improvement** — you get a better deal than the worst
price you were willing to accept.

---

### I submitted a MARKET order but it only partially filled. Where did the rest go?

A MARKET order sweeps the book until it runs out of liquidity. If the book
does not have enough resting orders to fill the entire quantity, the
unfilled remainder is **discarded** (not rested). You will receive one or
more partial fill events, then a cancellation for the remaining quantity.

**Fix:** If you need guaranteed full execution at whatever price, use FOK
and ensure liquidity is available. If you're comfortable with partial fills,
MARKET is correct — just understand the remainder is discarded, not queued.

---

## P&L & Position

### Why is my unrealized P&L different from my realized P&L?

They measure different things:

- **Unrealized P&L**: paper gain/loss on shares you still hold, calculated as
  `(current_price - avg_cost) × position`. This changes every time a trade
  prints and updates the last trade price.
- **Realized P&L**: profit/loss locked in when you *closed* part of your
  position (sold shares you were long, or bought back a short). This never
  changes after the trade.

Until you close your position, your gains are "on paper" — the market can
take them back. Once realized, they are yours regardless of subsequent
price moves.

---

### Why does my average cost change when I buy more shares?

When you add to an existing position, your **VWAP average cost** updates to
reflect the new shares at the new price. This is standard practice for
tracking the true cost basis of a position built over multiple trades.

**Example:**
```
Buy 100 shares @ 150.00  →  avg_cost = 150.00
Buy 100 shares @ 152.00  →  avg_cost = (150 × 100 + 152 × 100) / 200 = 151.00
```

See [P&L & Clearing — VWAP Average Cost](pnl.md#vwap-average-cost).

---

### Why do I have a negative position?

A negative position means you are **short** — you have sold shares you did not
own. This can happen if you submit a SELL order without first having bought any
shares. In a real brokerage this requires a margin account and stock borrowing;
EduMatcher does not enforce these constraints, so short positions are allowed
freely.

---

## Sessions & Orders

### What happens to my open orders when the market closes?

It depends on their time-in-force:

| TIF | At market close |
|-----|----------------|
| `DAY` | Expired and removed. You receive `order.expired` events. |
| `GTC` | Saved to `data/gtc_orders.json` and reloaded on next engine start. |
| `ATO` | Expired when OPENING_AUCTION phase ends. |
| `ATC` | Expired when CLOSING_AUCTION phase ends. |

---

### My GTC orders didn't reload after restart. Why?

GTC orders are written to `data/gtc_orders.json` **on engine shutdown** (when
you press Ctrl-C or the scheduler sends a CLOSED transition). If the engine was
killed forcefully (`kill -9` or a crash), the file was not written.

**Fix:** Check whether `data/gtc_orders.json` exists and has recent content.
If the engine was killed mid-session, the file may be stale or missing.

---

### Why is my order rejected with "Gateway not authenticated"?

Your gateway ID is not in the engine's allowlist. Gateway IDs must be
pre-configured in `engine_config.yaml` under `gateways.fix`:

```yaml
gateways:
    fix:
        - id: GW01
          description: My first trader
```

Restart the engine after editing the config.

---

## Self-Match Prevention

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

## Architecture & Setup

### The engine started but gateways can't connect. What's wrong?

Check that:
1. The engine is running *before* the gateways try to connect.
2. ZMQ ports 5555 and 5556 are not blocked by a firewall or in use by another
   process: `lsof -i :5555 -i :5556`
3. The gateway ID exists in `engine_config.yaml`.

---

### Why do I need five terminal windows?

Each process is an independent OS process communicating over ZeroMQ. They
cannot run inside a single terminal because each blocks on its own event loop.
For convenience, use the provided `./launch_all.sh` script which starts
everything in the background.

---

### How do I see what messages are flowing between processes?

Run `pm-audit --terminal` in a separate window. It subscribes to **all**
ZeroMQ messages and prints them to stdout, giving a full real-time trace of
every event in the system.

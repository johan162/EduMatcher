# Your First Trade

!!! note "Learning objectives"
    After completing this walkthrough you will have:

    - Started EduMatcher and verified all processes are connected
    - Submitted a limit order and watched it rest on the book
    - Executed a trade between two gateways
    - Read your fill confirmation and P&L update
    - Cancelled a resting order

This is a step-by-step guided walkthrough. You need about 10 minutes and five
terminal windows. No prior trading knowledge is assumed — every term is
explained as it appears.

---

## Prerequisites

Install EduMatcher if you haven't yet:

```bash
cd EduMatcher
poetry install
```

---

## Step 1 — Start the system

Open five terminal windows. Run one command per window, **in this order**
(the engine must start before the gateways):

```bash
# Window 1 — Matching engine
poetry run pm-engine --verbose
```

```bash
# Window 2 — Order book viewer (watch AAPL)
poetry run pm-viewer --symbol AAPL
```

```bash
# Window 3 — Clearing / P&L tracker
poetry run pm-clearing
```

```bash
# Window 4 — First trader
poetry run pm-gateway --id GW01
```

```bash
# Window 5 — Second trader
poetry run pm-gateway --id GW02
```

When the gateways start, you should see:

```
[GW01] Connected and authenticated.
[GW01] Session: CONTINUOUS
GW01>
```

The `GW01>` prompt means you are ready to enter orders.

---

## Step 2 — Check what symbols are available

At the `GW01>` prompt, type:

```
SYMBOLS
```

You should see the list of configured symbols (e.g. `AAPL`, `MSFT`). All
examples in this walkthrough use `AAPL`.

---

## Step 3 — Submit a passive LIMIT BUY (make liquidity)

A **LIMIT BUY** order says: *"I want to buy X shares, but only at this price
or lower."* If no one is selling at that price right now, the order will
**rest on the book** — it waits until someone is willing to sell at your price.

At the `GW01>` prompt:

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00
```

**What each field means:**

| Field | Value | Meaning |
|-------|-------|---------|
| `SYM` | `AAPL` | The symbol (instrument) you want to trade |
| `SIDE` | `BUY` | You want to buy |
| `TYPE` | `LIMIT` | Price-limited order — won't fill above $150.00 |
| `QTY` | `100` | 100 shares |
| `PRICE` | `150.00` | Maximum price you'll pay |

You should see the acknowledgement:

```
[GW01] order.ack: order_id=abc123 accepted=true
```

Now look at the **book viewer** (Window 2). You should see:

```
AAPL  CONTINUOUS
BID                ASK
─────────────────────
100 @ 150.00
```

Your buy order is sitting on the bid side, waiting for a seller.

---

## Step 4 — Submit a matching LIMIT SELL (take liquidity)

Now switch to the `GW02>` prompt in Window 5 and submit a sell order at the
same price:

```
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.00
```

Because GW01 has a resting bid at $150.00 and GW02 is now willing to sell at
$150.00, the prices **cross** — a trade happens immediately.

---

## Step 5 — Read the fill confirmation

Both gateways receive fill events. In Window 4 (GW01):

```
[GW01] order.fill: order_id=abc123 qty=100 price=150.00 status=FILLED
```

In Window 5 (GW02):

```
[GW02] order.fill: order_id=xyz456 qty=100 price=150.00 status=FILLED
```

In Window 2 (book viewer), the order book is now empty at that level — both
orders were consumed by the trade.

In Window 1 (engine `--verbose`), you'll see the trade logged:

```
TRADE AAPL buyer=GW01 seller=GW02 qty=100 price=150.00
```

---

## Step 6 — Check P&L in the clearing window

In Window 3 (clearing), you'll see a P&L update for both traders:

```
[CLEARING] GW01 AAPL: position=+100 avg_cost=150.00 realized=0.00 unrealized=0.00
[CLEARING] GW02 AAPL: position=-100 avg_cost=150.00 realized=0.00 unrealized=0.00
```

**Reading the P&L:**

- **GW01** bought 100 shares at $150.00. They now have a **long position** of
  +100 shares. Their unrealized P&L is $0 because the market price is still
  $150.00 (no profit or loss yet).
- **GW02** sold 100 shares they presumably don't own — they are now **short**
  100 shares. Their P&L is also $0 at the moment of the trade.

---

## Step 7 — Submit a resting sell and watch unrealized P&L move

From `GW01>`, post another order to close the long position at a profit:

```
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=152.00|TIF=GTC
```

The `TIF=GTC` (Good-Till-Cancelled) means this order will survive if the
trading session ends. It rests on the ask side of the book waiting for a buyer
at $152.00.

From `GW02>`, imagine GW02 wants to buy back their short position. If GW02
submits a buy at $152.00:

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=152.00
```

Another trade executes. Now in the clearing window:

```
[CLEARING] GW01 AAPL: position=0 avg_cost=0.00 realized=+200.00 unrealized=0.00
[CLEARING] GW02 AAPL: position=0 avg_cost=0.00 realized=-200.00 unrealized=0.00
```

GW01 bought at $150, sold at $152 — **$2 × 100 shares = $200 realized profit**.
GW02 sold at $150, bought back at $152 — **$200 realized loss**. Both are now
flat (position = 0).

---

## Step 8 — Submit and cancel a resting order

Submit a new bid that won't fill immediately:

```
# From GW01>
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=148.00
```

You'll get an order ID in the acknowledgement (e.g. `order_id=def789`). To
cancel it:

```
CANCEL|ID=def789
```

The engine confirms:

```
[GW01] order.cancelled: order_id=def789
```

The order disappears from the book viewer.

---

## Step 9 — Amend an existing order

Sometimes you want to change your mind without withdrawing completely — maybe
you'd take a slightly higher price, or you only want to buy 30 shares instead
of 50. The `AMEND` command updates a **resting** LIMIT order in-place, without
cancelling it and losing your queue position.

From `GW01>`, post a new resting bid:

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=148.00
```

Note the order ID from the acknowledgement (e.g. `order_id=def789`). Now
change the price to $149.00 and reduce the quantity to 30 shares:

```
AMEND|ID=def789|PRICE=149.00|QTY=30
```

The engine confirms the change:

```
[GW01] order.amended: order_id=def789 price=149.00 qty=30
```

In the book viewer the old level at $148.00 disappears and a new line appears
at $149.00 for 30 shares — the order was updated atomically. You can amend
the price, the quantity, or both in a single command. You cannot amend a
fully filled or cancelled order.

!!! warning "Queue priority"
    Amending an order can cost you your **time priority** in the queue,
    mirroring the behaviour of real exchanges:

    - **Price change** — always loses priority. The order moves to the back
      of the new price level's queue, because you are effectively competing
      for a different set of contra orders.
    - **Quantity increase** — loses priority. A larger order consumes more
      liquidity, so the engine treats it as a new aggressor and re-timestamps
      it.
    - **Quantity decrease** — priority is **preserved**. Reducing your size
      is a concession to the market; exchanges reward this by keeping your
      place in the queue.

    In the example above, both the price change ($148 → $149) *and* the
    quantity reduction (50 → 30) happen in one command. The price change
    dominates — the order goes to the back of the $149.00 queue.

---

## Step 10 — Try a MARKET order

A MARKET order doesn't specify a price — it just says "buy/sell at whatever
is available right now." First, make sure there's something to trade against.

From `GW02>`, post a resting sell:

```
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=151.00
```

Now from `GW01>`, sweep it with a market buy:

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
```

The market order fills immediately at $151.00 — it takes whatever price the
resting sell requires. You didn't choose the price; you prioritised speed.

---

## Summary

You have completed a full basic trading session:

| Step | What you did | Concept learned |
|------|-------------|-----------------|
| 1 | Started all processes | System topology |
| 2 | Queried symbols | System state |
| 3 | Posted a LIMIT BUY | Passive / maker order, resting on book |
| 4 | Posted a matching LIMIT SELL | Aggressive / taker order, price crossing |
| 5 | Read fill confirmation | Order lifecycle |
| 6 | Checked P&L | Long position, unrealized P&L |
| 7 | Closed position for profit | Realized P&L |
| 8 | Cancelled a resting order | Order cancellation |
| 9 | Amended a resting order | In-place price/qty update, queue priority |
| 10 | Submitted a MARKET order | Immediacy vs. price certainty |

---

## What next?

- [Order Types](order-types.md) — all ten order types with detailed mechanics
- [A Full Trading Day](concepts-trading-day.md) — auctions, session phases, and daily lifecycle
- [P&L & Clearing](pnl.md) — full explanation of VWAP cost basis and realized vs. unrealized

---

[← The Order Book](concepts-order-book.md) | [Next: A Full Trading Day →](concepts-trading-day.md)

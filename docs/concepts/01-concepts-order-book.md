# The Order Book

!!! note "Learning objectives"
    After reading this page you will understand:

    - What an order book is and how it is structured
    - The difference between a bid and an ask
    - What the spread is and why it matters
    - How price-time priority determines who gets filled first
    - What happens step-by-step when two orders match

---

## What is an order book?

When you buy a share of stock, someone else must sell it to you. But they may
not be available at exactly the moment you want to trade, and you may not agree
on price. The **order book** is the mechanism that bridges this gap.

An order book is a sorted, live list of all orders that have been submitted to
the exchange but have not yet traded. Every tradable instrument has its own
book. Orders are separated into two sides:

| Side | Also called | What it represents |
|------|-------------|-------------------|
| **Bids** | Buy side | Traders who want to buy, sorted highest price first |
| **Asks** | Offer / sell side | Traders who want to sell, sorted lowest price first |

The matching engine continuously checks whether the best bid and the best ask
overlap in price. When they do, a **trade** is produced.

---

## A concrete order book

Imagine AAPL is trading around $150. The live book might look like this:

```
    BID (buy orders)          ASK (sell orders)
    ─────────────────         ──────────────────
    Qty    Price              Price    Qty
    ───    ─────              ─────    ───
    200    149.90             150.10    100
    500    149.80             150.20    300
    150    149.70             150.30    500
    300    149.60             150.50    200
```

- The **best bid** (highest buy price) is **149.90** for 200 shares.
- The **best ask** (lowest sell price) is **150.10** for 100 shares.
- These prices do not overlap — no trade happens yet.

---

## The bid-ask spread

The **spread** is the gap between the best bid and best ask:

$$\text{spread} = \text{best ask} - \text{best bid} = 150.10 - 149.90 = 0.20$$

The spread represents the cost of an immediate round-trip (buy then sell). A
trader who buys at the ask ($150.10) and immediately sells at the bid ($149.90)
loses $0.20 per share.

**Narrow spread** (e.g. $0.01) — a **liquid** market. Many participants are
competing to trade, so prices are tight. Cheap to trade in and out.

**Wide spread** (e.g. $2.00) — an **illiquid** market. Few participants, or
high uncertainty. Expensive to trade in and out.

The **mid-price** is the midpoint between bid and ask:

$$\text{mid} = \frac{149.90 + 150.10}{2} = 150.00$$

---

## Book depth

**Depth** refers to how much volume (quantity of shares) is available at or
near the top of each side. A deep book absorbs large orders without moving
the price much. A thin book has little resting quantity and even a moderate
order can push the price significantly.

Looking at our example book above, if a trader submits a market sell order for
600 shares, it would:
1. Fill 100 shares at the best bid of **149.90**
2. Fill 500 shares at the next level, **149.80**

The average fill price would be:

$$\frac{(100 \times 149.90) + (500 \times 149.80)}{600} = \frac{14990 + 74900}{600} = \frac{89890}{600} \approx 149.82$$

The trader wanted to sell at ~149.90 but the large size caused the actual
average to be 149.82. This difference is called **slippage**.

---

## Price-time priority

When multiple orders rest at the same price, the matching engine must decide
which one fills first. EduMatcher uses **price-time priority** (also called
FIFO priority):

1. **Price first** — the order with the best price for the counterparty fills
   first. For bids: the highest price wins. For asks: the lowest price wins.
2. **Time second** — among orders at the same price, the one that arrived
   earliest fills first.

### Worked example — three bids at the same price

Suppose three traders each submitted a LIMIT BUY at exactly $149.90:

| Order | Trader | Time submitted | Qty |
|-------|--------|---------------|-----|
| A     | GW01   | 09:30:01.100  | 100 |
| B     | GW02   | 09:30:01.250  | 200 |
| C     | GW03   | 09:30:03.900  | 150 |

Now a LIMIT SELL at $149.90 for 250 shares arrives. The engine processes bids
in time order (A before B before C):

1. **Order A** (GW01, 100 shares) fills first — submitted earliest.
2. **Order B** (GW02, 200 shares) — only 150 more needed, so 150 of the 200
   fills, leaving 50 shares of Order B resting.
3. **Order C** (GW03) — gets nothing this time; it was last in queue.

The result:

| Order | Fill | Remaining |
|-------|------|-----------|
| A     | 100  | 0 (fully filled) |
| B     | 150  | 50 (partially filled, still resting) |
| C     | 0    | 150 (still resting, now at the front of the remaining queue) |

This is why being early matters: all else being equal, the first order in
queue has an advantage. This creates an incentive for market participants to
submit orders quickly — one driver of the speed race in modern markets.

---

## Step-by-step: what happens when orders match

Here is the full lifecycle of a trade between a resting limit order and an
incoming aggressive order.

**State: AAPL book has a resting BID from GW01**

```
Resting bid: GW01 BUY 100 @ 150.00 (LIMIT, arrived at 09:31:00)
```

**Action: GW02 submits a SELL LIMIT at 150.00 for 100 shares**

```
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.00
```

**Engine processing:**

1. Incoming order hits the matching engine via ZeroMQ PUSH socket.
2. Engine checks: is there a resting bid at or above $150.00? Yes — GW01 at $150.00.
3. Trade price is the **resting order's price** ($150.00) because it was first.
4. Engine generates a `trade.executed` event:
   - buyer: GW01, qty: 100, price: 150.00
   - seller: GW02, qty: 100, price: 150.00
5. Both orders are fully filled and removed from the book.
6. Engine publishes `order.fill.GW01` and `order.fill.GW02` to both gateways.
7. Engine publishes a `book.AAPL` snapshot — that bid level is now gone.
8. Clearing process receives `trade.executed` and updates both traders' P&L.

**Result:**

```
GW01: bought 100 AAPL @ 150.00 — position +100, avg cost 150.00
GW02: sold   100 AAPL @ 150.00 — position -100 (or flat if they were long)
```

---

## Passive vs. aggressive orders

An order that **rests** on the book, waiting for a counterparty, is called
**passive** (or a **maker** order, because it "makes" liquidity for others to
trade against).

An order that **crosses** the spread and immediately matches against resting
orders is called **aggressive** (or a **taker** order, because it "takes"
available liquidity).

| Role | Also called | What it does |
|------|-------------|-------------|
| Passive | Maker / resting | Posts to the book, waits |
| Aggressive | Taker / crossing | Matches immediately against the book |

In real exchanges, makers often pay lower fees than takers as a reward for
providing liquidity. EduMatcher does not model fees, but the distinction
is important for understanding order strategy.

---

## Key terms summary

| Term | Definition |
|------|-----------|
| **Order book** | The live, sorted collection of all resting buy and sell orders for one instrument |
| **Bid** | A resting buy order; bids are sorted highest price first |
| **Ask / offer** | A resting sell order; asks are sorted lowest price first |
| **Spread** | Gap between best bid and best ask |
| **Mid-price** | Average of best bid and best ask |
| **Depth** | Total resting volume near the top of the book |
| **Slippage** | Difference between expected and actual average fill price on a large order |
| **Price-time priority** | Fill ordering rule: best price first, then earliest arrival |
| **Passive / maker** | An order resting on the book |
| **Aggressive / taker** | An order that crosses the spread and matches immediately |

---

[Back to top](#the-order-book) | [Next: A Full Trading Day →](05-concepts-trading-day.md)

## Implementation Note: Tick Prices

EduMatcher stores prices internally as integer ticks (not floating-point decimals).
That means priority, comparisons, and level aggregation are exact in engine code.
Displayed bid/ask values are converted back to decimals for user-facing views.

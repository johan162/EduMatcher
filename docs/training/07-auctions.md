# Auctions

## Objective

Run opening and closing auctions, understand equilibrium price calculation, and
observe how auction orders are collected and matched in a single uncrossing event.

 

## Prerequisites

- Chapters 01–06 completed.
- Scheduler control available so you can observe auction phases.

 

## Background

Auctions concentrate liquidity at a single price. All orders are collected
during the auction phase, then matched at the **equilibrium price** — the price
that maximises the quantity traded.

Key properties:

- No partial information leakage (indicative prices may be shown).
- All fills happen at the same price.
- Prevents manipulation via timing advantages.

 

## Exercise 1: Set Up for an Opening Auction

Stop the scheduler and restart with manual phase control (or use a config that
pauses in PRE_OPEN). You want to stay in PRE_OPEN long enough to enter orders.

From two gateways, enter orders while in PRE_OPEN/OPENING_AUCTION:

**TRADER01:**
```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=300|PRICE=150.50|TIF=ATO
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=200|PRICE=150.20|TIF=ATO
```

**TRADER02:**
```
TRADER02> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=400|PRICE=149.80|TIF=ATO
TRADER02> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.30|TIF=ATO
```

:material-checkbox-blank-outline: **Checkpoint:** orders accepted, resting in auction book.

 

## Exercise 2: Trigger the Auction Uncrossing

When the scheduler transitions from OPENING_AUCTION → CONTINUOUS, all crossing
orders match at the equilibrium price.

For the exact orders entered in Exercise 1, here is the full calculation
(verified against `engine/auction.py`):

| Candidate price | Cumulative buy qty (bids ≥ price) | Cumulative sell qty (asks ≤ price) | Matched qty | Surplus |
|---|---|---|---|---|
| 149.80 | 500 (300+200) | 400 | **400** | 100 |
| 150.20 | 500 | 400 | 400 | 100 |
| 150.30 | 300 | 500 | 300 | 200 |
| 150.50 | 300 | 500 | 300 | 200 |

Maximum matched quantity is 400, tied between 149.80 and 150.20 with equal
surplus (100). The engine scans candidate prices from lowest to highest and
only replaces the current best on a **strict** improvement, so the **first**
price reached with the best (qty, surplus) pair wins. That means the
equilibrium price here is **149.80** — the lower of the two tied prices —
not a value in between.

Expected: all fills print execution price `149.80`, for a total matched
quantity of 400 shares.

What to observe: identify the one common execution price printed across all
fill events, and confirm it equals `149.80` and the total filled quantity
equals `400` (300 from TRADER01's first order + 100 remaining from the
second, against TRADER02's 400-share sell).

:material-checkbox-blank-outline: **Checkpoint:** all fills report execution price `149.80` and matched quantity `400`.

 

## Exercise 3: Unfilled Auction Orders

If an ATO order does not cross (e.g. a buy at 148.00 with no matching sell),
it is cancelled when CONTINUOUS begins.

Place:

```
TRADER01> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=400.00|TIF=ATO
```

After auction uncrossing, this should be cancelled (no sell at 400.00).

:material-checkbox-blank-outline: **Checkpoint:** out-of-range ATO order cancelled.

 

## Exercise 4: Closing Auction

When the session reaches CLOSING_AUCTION:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.80|TIF=ATC
TRADER02> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.60|TIF=ATC
```

On transition to CLOSED, the auction uncrosses and fills are generated.

:material-checkbox-blank-outline: **Checkpoint:** closing auction produces fills.

 

## Exercise 5: GTC Orders in Auctions

GTC orders participate in auctions alongside ATO/ATC orders:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=150.00|TIF=GTC
```

This order participates in both opening and closing auctions, and rests during
CONTINUOUS trading.

:material-checkbox-blank-outline: **Checkpoint:** GTC order fills in auction or continues resting.

 

## Equilibrium Price Rules

The auction algorithm scans candidate prices from lowest to highest and
selects the price that:

1. **Maximises traded volume** — most shares can match.
2. **Minimises surplus** — least shares left unexecuted at that price.
3. **Ties resolved by scan order** — if multiple prices tie on both volume
   and surplus, the engine keeps the first (lowest) one it found, since it
   only replaces the current best on a strict improvement. There is no
   separate "nearest to last trade" tie-break — the tie always resolves to
   the lower of the tied candidate prices.

 

## Reflection

Why does an auction match all crossing orders at a single equilibrium price,
instead of walking the book and filling each order at its own limit price
(as CONTINUOUS trading does)? What problem would arise at the open if every
order filled at its own price instead?

## Further Reading

- [Auctions & Scheduling](../user-guide/080-auctions-scheduling.md)
- [Auction Equilibrium Concepts](../concepts/05-concepts-trading-day.md)
- [Order Types](../user-guide/060-order-types.md)

 

**Next:** [08 — Cancelling & Managing Orders](08-cancelling-orders.md)

# 07 — Auctions

## Objective

Run opening and closing auctions, understand equilibrium price calculation, and
observe how auction orders are collected and matched in a single uncrossing event.

---

## Prerequisites

- Chapters 01–06 completed.
- Scheduler control available so you can observe auction phases.

---

## Background

Auctions concentrate liquidity at a single price. All orders are collected
during the auction phase, then matched at the **equilibrium price** — the price
that maximises the quantity traded.

Key properties:

- No partial information leakage (indicative prices may be shown).
- All fills happen at the same price.
- Prevents manipulation via timing advantages.

---

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

---

## Exercise 2: Trigger the Auction Uncrossing

When the scheduler transitions from OPENING_AUCTION → CONTINUOUS, all crossing
orders match at the equilibrium price.

Expected: fills at a single price that maximises traded volume. In this example
the equilibrium price should be around 150.20–150.30 (the exact price depends on
the algorithm; max-volume, then min-surplus rules apply).

:material-checkbox-blank-outline: **Checkpoint:** all fills report the same execution price.

---

## Exercise 3: Unfilled Auction Orders

If an ATO order does not cross (e.g. a buy at 148.00 with no matching sell),
it is cancelled when CONTINUOUS begins.

Place:

```
TRADER01> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=400.00|TIF=ATO
```

After auction uncrossing, this should be cancelled (no sell at 400.00).

:material-checkbox-blank-outline: **Checkpoint:** out-of-range ATO order cancelled.

---

## Exercise 4: Closing Auction

When the session reaches CLOSING_AUCTION:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.80|TIF=ATC
TRADER02> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.60|TIF=ATC
```

On transition to CLOSED, the auction uncrosses and fills are generated.

:material-checkbox-blank-outline: **Checkpoint:** closing auction produces fills.

---

## Exercise 5: GTC Orders in Auctions

GTC orders participate in auctions alongside ATO/ATC orders:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=150.00|TIF=GTC
```

This order participates in both opening and closing auctions, and rests during
CONTINUOUS trading.

:material-checkbox-blank-outline: **Checkpoint:** GTC order fills in auction or continues resting.

---

## Equilibrium Price Rules

The auction algorithm selects the price that:

1. **Maximises traded volume** — most shares can match.
2. **Minimises surplus** — least shares left unexecuted at that price.
3. **Nearest to reference** — if tied, closest to last traded price.

---

## Further Reading

- [Auctions & Scheduling](../user-guide/06-auctions-scheduling.md)
- [Order Types](../user-guide/04-order-types.md)
- [A Full Trading Day](../concepts/05-concepts-trading-day.md)

---

**Next:** [08 — Cancelling & Managing Orders](08-cancelling-orders.md)

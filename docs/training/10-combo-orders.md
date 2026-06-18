# 10 — Combo Orders

## Objective

Create multi-leg orders that execute atomically and understand OCO (One-Cancels-
Other) linked orders.

---

## Background

A **combo order** bundles two or more legs (different symbols or sides) into a
single atomic unit. Either all legs fill or none do. This eliminates "leg risk" —
the danger of only one side of a spread filling.

---

## Exercise 1: Simple Two-Leg Combo

Buy AAPL and sell MSFT atomically:

```
TRADER01> NEW|TYPE=COMBO|TIF=DAY|LEGS=BUY:AAPL:100:150.10,SELL:MSFT:50:420.50
```

The engine tries to match both legs simultaneously. If both sides have
sufficient liquidity, you get fills on both. Otherwise the combo rests.

:material-checkbox-blank-outline: **Checkpoint:** combo acknowledged; fills or rests as a unit.

---

## Exercise 2: Verify Atomic Behaviour

Check that you cannot get a partial combo (one leg filled, other not):

1. Set up a book where only AAPL has liquidity but MSFT does not have a bid
   at 420.50.
2. Submit the combo — it should rest (not fill AAPL alone).

:material-checkbox-blank-outline: **Checkpoint:** combo does not partially fill.

---

## Exercise 3: Cancel a Resting Combo

```
TRADER01> CANCEL|ORDER_ID=<combo_order_id>
```

All legs are cancelled together.

:material-checkbox-blank-outline: **Checkpoint:** full combo cancellation confirmed.

---

## Exercise 4: OCO — One-Cancels-Other

Link two independent orders so that when one fills or is cancelled, the other
is automatically cancelled:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=149.50|TIF=DAY|OCO_GROUP=oco1
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=148.00|TIF=DAY|OCO_GROUP=oco1
```

When the first order fills (price drops to 149.50), the second order at 148.00
is automatically cancelled.

:material-checkbox-blank-outline: **Checkpoint:** filling one OCO leg cancels the other.

---

## Exercise 5: OCO with Different Sides

A common pattern — bracket order (take-profit + stop-loss):

```
TRADER01> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=151.00|TIF=DAY|OCO_GROUP=bracket1
TRADER01> NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP|QTY=100|STOP_PRICE=149.00|TIF=DAY|OCO_GROUP=bracket1
```

If price rises to 151.00 (take-profit fills), the stop is cancelled.
If price drops to 149.00 (stop triggers and fills), the limit sell is cancelled.

:material-checkbox-blank-outline: **Checkpoint:** bracket order behaves as expected.

---

## When to Use Combos vs OCO

| Use Case | Mechanism |
|----------|-----------|
| Spread / pairs trade (buy A + sell B) | Combo |
| Hedging (must have both sides or neither) | Combo |
| Take-profit + stop-loss (only want one to execute) | OCO |
| Multiple entries at different prices (only want one) | OCO |

---

**Next:** [11 — Risk Controls](11-risk-controls.md)

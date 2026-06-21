# Combo Orders

## Objective

Create multi-leg orders that execute atomically and understand OCO (One-Cancels-
Other) linked orders.

---

## Prerequisites

- Chapters 01–09 completed.
- Two trader gateways connected so you can stage opposing liquidity.

---

## Background

A **combo order** bundles two or more legs (different symbols or sides) into a
single atomic unit. Either all legs fill or none do. This eliminates "leg risk" —
the danger of only one side of a spread filling.

---

## Exercise 1: Simple Two-Leg Combo

Buy AAPL and sell MSFT atomically:

```
TRADER01> NEW|TYPE=COMBO|COMBO_ID=PAIR-001|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.10|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=50|LEG1.PRICE=420.50
```

The engine tries to match both legs simultaneously. If both sides have
sufficient liquidity, you get fills on both. Otherwise the combo rests.

:material-checkbox-blank-outline: **Checkpoint:** combo acknowledged; fills or rests as a unit.

Observation: atomic behavior is what removes leg risk. You should never see one
leg fill without the other in a valid combo execution.

---

## Exercise 2: Verify Atomic Behaviour

Check that you cannot get a partial combo (one leg filled, other not):

1. Set up a book where only AAPL has liquidity but MSFT does not have a bid
   at 420.50.
2. Submit the combo — it should rest (not fill AAPL alone).

:material-checkbox-blank-outline: **Checkpoint:** combo does not partially fill.

Operational rationale: without atomicity, you could end up with accidental
directional inventory from only one leg filling.

---

## Exercise 3: Cancel a Resting Combo

```
TRADER01> CANCEL|COMBO_ID=PAIR-001
```

All legs are cancelled together.

:material-checkbox-blank-outline: **Checkpoint:** full combo cancellation confirmed.

---

## Exercise 4: OCO — One-Cancels-Other

Link two independent orders so that when one fills or is cancelled, the other
is automatically cancelled:

```
TRADER01> NEW|TYPE=OCO|OCO_ID=OCO-AAPL-ENTRY|SYM=AAPL|QTY=100|TIF=DAY|LEG1_SIDE=BUY|LEG1_TYPE=LIMIT|LEG1_PRICE=149.50|LEG2_SIDE=BUY|LEG2_TYPE=LIMIT|LEG2_PRICE=148.00
```

When the first order fills (price drops to 149.50), the second order at 148.00
is automatically cancelled.

:material-checkbox-blank-outline: **Checkpoint:** filling one OCO leg cancels the other.

---

## Exercise 5: OCO with Different Sides

A common pattern — bracket order (take-profit + stop-loss):

```
TRADER01> NEW|TYPE=OCO|OCO_ID=BRACKET-AAPL-001|SYM=AAPL|QTY=100|TIF=DAY|LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|LEG1_PRICE=151.00|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=149.00
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

## Further Reading

- [Combo Orders](../user-guide/05-combos.md)
- [ALF Protocol — OCO and Combo Orders](../user-guide/90-app-alf-protocol.md)

---

**Next:** [11 — Risk Controls](11-risk-controls.md)

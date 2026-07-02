# Combo Orders

## Objective

Create multi-leg orders that execute atomically and understand OCO (One-Cancels-
Other) linked orders.

 

## Prerequisites

- Chapters 01–09 completed.
- Two trader gateways connected so you can stage opposing liquidity.

 

## Background

A **combo order** bundles two or more legs (different symbols or sides) into a
single atomic unit. Either all legs fill or none do. This eliminates "leg risk" —
the danger of only one side of a spread filling.

 

## Exercise 1: Simple Two-Leg Combo

To see the combo **fill atomically**, first guarantee liquidity on both legs
with explicit counter-orders (don't rely on ambient MM quotes, which may not
be at the exact combo prices):

```
TRADER02> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.10|TIF=DAY
TRADER02> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=420.50|TIF=DAY
```

Now submit the combo — buy AAPL and sell MSFT atomically:

```
TRADER01> NEW|TYPE=COMBO|COMBO_ID=PAIR-001|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.10|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=50|LEG1.PRICE=420.50
```

Because both counter-orders above match the combo's leg prices exactly, the
engine can fill both legs simultaneously.

:material-checkbox-blank-outline: **Checkpoint:** combo acknowledged; both legs fill in the same event (check `BOOK|SYM=AAPL` and `BOOK|SYM=MSFT` for matching fill reports).

Observation: atomic behavior is what removes leg risk. You should never see one
leg fill without the other in a valid combo execution.

 

## Exercise 2: Verify Atomic Behaviour (Resting Case)

Now check that you cannot get a partial combo (one leg filled, other not) when
liquidity is missing on **one** leg:

1. Confirm AAPL has a resting sell at 150.10 (from Exercise 1, or place a new
   one: `TRADER02> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.10|TIF=DAY`).
2. Do **not** place any MSFT buy at 420.50 — cancel or avoid resting MSFT
   liquidity at that price so the second leg has nothing to match against.
3. Submit a new combo with a fresh ID:

   ```
   TRADER01> NEW|TYPE=COMBO|COMBO_ID=PAIR-002|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.10|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=50|LEG1.PRICE=420.50
   ```

4. It should rest in full — check `BOOK|SYM=AAPL` and confirm the AAPL sell at
   150.10 is **still resting, unfilled**, proving the combo did not execute
   the AAPL leg alone even though a matching counter-order existed for it.

:material-checkbox-blank-outline: **Checkpoint:** combo does not partially fill; AAPL counter-order remains untouched.

Operational rationale: without atomicity, you could end up with accidental
directional inventory from only one leg filling.

 

## Exercise 3: Cancel a Resting Combo

```
TRADER01> CANCEL|COMBO_ID=PAIR-002
```

All legs are cancelled together.

:material-checkbox-blank-outline: **Checkpoint:** full combo cancellation confirmed.

 

## Exercise 4: OCO — One-Cancels-Other

Link two independent orders so that when one fills or is cancelled, the other
is automatically cancelled:

```
TRADER01> NEW|TYPE=OCO|OCO_ID=OCO-AAPL-ENTRY|SYM=AAPL|QTY=100|TIF=DAY|LEG1_SIDE=BUY|LEG1_TYPE=LIMIT|LEG1_PRICE=149.50|LEG2_SIDE=BUY|LEG2_TYPE=LIMIT|LEG2_PRICE=148.00
```

When the first order fills (price drops to 149.50), the second order at 148.00
is automatically cancelled.

:material-checkbox-blank-outline: **Checkpoint:** filling one OCO leg cancels the other.

 

## Exercise 5: OCO with Different Sides

A common pattern — bracket order (take-profit + stop-loss):

```
TRADER01> NEW|TYPE=OCO|OCO_ID=BRACKET-AAPL-001|SYM=AAPL|QTY=100|TIF=DAY|LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|LEG1_PRICE=151.00|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=149.00
```

If price rises to 151.00 (take-profit fills), the stop is cancelled.
If price drops to 149.00 (stop triggers and fills), the limit sell is cancelled.

:material-checkbox-blank-outline: **Checkpoint:** bracket order behaves as expected.

 

## When to Use Combos vs OCO

| Use Case | Mechanism |
|----------|-----------|
| Spread / pairs trade (buy A + sell B) | Combo |
| Hedging (must have both sides or neither) | Combo |
| Take-profit + stop-loss (only want one to execute) | OCO |
| Multiple entries at different prices (only want one) | OCO |

 

## Reflection

Why is a Combo's atomicity a *guarantee* while an OCO's "one cancels other"
is a *reaction* to the first fill? Could an OCO ever leave you exposed for a
brief moment that a Combo would not — and why does that difference matter for
a pairs trade versus a take-profit/stop-loss pair?

## Further Reading

- [Combo Orders](../user-guide/05-combos.md)
- [ALF Protocol — OCO and Combo Orders](../user-guide/90-app-alf-protocol.md)

 

**Next:** [11 — Risk Controls](11-risk-controls.md)

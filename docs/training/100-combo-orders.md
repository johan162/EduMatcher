# Combo Orders

## Objective

Create multi-leg orders, understand exactly how far the all-or-none guarantee
reaches, and use OCO (One-Cancels-Other) linked orders.

 


!!! abstract "Pre-reading in the User Guide"
    - [Combo Orders](../user-guide/070-combo-orders.md)
    - [OCO](../user-guide/060-order-types.md#oco-one-cancels-other)

## Prerequisites

- Chapters 01–09 completed.
- Two trader gateways connected so you can stage opposing liquidity.

 

## Background

A **combo order** bundles two or more legs (different symbols or sides) and
submits them as one message with a shared `COMBO_ID`.

`COMBO_TYPE=AON` (all-or-none) gives you an atomicity guarantee — but it is
narrower than it first sounds, and the exact shape of it is the main thing this
chapter teaches:

!!! important "AON is atomic **at entry**, not for the combo's lifetime"
    When you submit an AON combo the engine checks, at that instant, whether
    *every* leg can fill completely. Two outcomes, and only two:

    - **All legs can fill** → all legs execute together. No partial.
    - **Any leg is short** → **no leg matches at all**. Every leg is posted to
      its book as an ordinary resting order.

    That second outcome is where the nuance lives. Those resting legs are now
    normal orders. Nothing stops another participant from hitting one of them
    later, and when that happens the combo moves to `PARTIALLY_MATCHED` — one
    leg filled, the others still resting. **You have leg risk again.**

So the accurate statement is: an AON combo will never *execute itself* into a
half-filled position at submission. It can still *end up* half-filled while it
rests. Exercises 2 and 3 show both halves of that.

The combo's lifecycle states are `PENDING`, `PARTIALLY_MATCHED`, `MATCHED`,
`FAILED` (a leg was cancelled or expired, so the siblings cascade-cancel),
`CANCELLED` and `REJECTED`.

 

## Exercise 1: Simple Two-Leg Combo

To see the combo **fill atomically**, first guarantee liquidity on both legs
with explicit counter-orders (don't rely on ambient MM quotes, which may not
be at the exact combo prices):

```
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.10|TIF=DAY
[TRADER02]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=420.50|TIF=DAY
```

Now submit the combo — buy AAPL and sell MSFT atomically:

```
[TRADER01]> NEW|TYPE=COMBO|COMBO_ID=PAIR-001|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.10|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=50|LEG1.PRICE=420.50
```

Because both counter-orders above match the combo's leg prices exactly, the
engine can fill both legs simultaneously.

:material-checkbox-blank-outline: **Checkpoint:** combo acknowledged; both legs fill in the same event (check `BOOK|SYM=AAPL` and `BOOK|SYM=MSFT` in the operator console for matching fill reports).

Observation: when the pre-check passes, both legs execute in the same pass —
this is the case the AON guarantee is designed for.

 

## Exercise 2: Atomicity at Entry — One Short Leg Blocks Every Leg

Now check the pre-check: when liquidity is missing on **one** leg, *no* leg
matches, even the one that could have:

1. Confirm AAPL has a resting sell at 150.10 (from Exercise 1, or place a new
   one: `TRADER02> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.10|TIF=DAY`).
2. Do **not** place any MSFT buy at 420.50 — cancel or avoid resting MSFT
   liquidity at that price so the second leg has nothing to match against.
3. Submit a new combo with a fresh ID:

   ```
   [TRADER01]> NEW|TYPE=COMBO|COMBO_ID=PAIR-002|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.10|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=50|LEG1.PRICE=420.50
   ```

4. It should rest in full — check `BOOK|SYM=AAPL` in the operator console and confirm the AAPL sell at
   150.10 is **still resting, unfilled**, proving the combo did not execute
   the AAPL leg alone even though a matching counter-order existed for it.

:material-checkbox-blank-outline: **Checkpoint:** the combo did not execute the
AAPL leg even though a matching counter-order was sitting there. Both combo
legs are now resting, and the combo is `PENDING`.

Operational rationale: without the entry pre-check you would pick up accidental
directional inventory the moment you submitted an unbalanced combo.

 

## Exercise 3: Leg Risk Returns Once the Combo Rests

Exercise 2 left `PAIR-002` resting with both legs in their books. This is the
case people are surprised by, so cause it deliberately.

**1.** Confirm the combo is resting and `PENDING`:

```
[TRADER01]> ORDERS
```

You should see both child legs — the AAPL buy at 150.10 and the MSFT sell at
420.50 — with status `NEW`.

**2.** From `TRADER02`, hit **only the MSFT leg**:

```
[TRADER02]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=420.50|TIF=DAY
```

**3.** Look at what happened to the combo:

```
[TRADER01]> ORDERS
```

The MSFT leg is `FILLED`. The AAPL leg is still `NEW`, resting. The combo has
moved to `PARTIALLY_MATCHED`.

`TRADER01` is now short 50 MSFT with no offsetting AAPL position — precisely
the leg risk the combo was supposed to prevent. The AON guarantee was never
violated: it applied at submission, and at submission nothing executed.

:material-checkbox-blank-outline: **Checkpoint:** the combo is
`PARTIALLY_MATCHED` with one leg filled and one resting, and you can explain
why this does not contradict "all-or-none".

!!! tip "What a real desk does about this"
    Because a resting AON combo can be picked apart, desks do not leave them
    resting. They either submit only when both sides are already fillable, or
    they cancel the whole combo the moment it fails to execute at entry:

    ```
    [TRADER01]> CANCEL|COMBO_ID=PAIR-002
    ```

    That cancels every remaining leg. Fills that already happened are **not**
    reversed — cancel the combo before someone hits a leg, not after.

Clean up before continuing:

```
[TRADER01]> CANCEL|COMBO_ID=PAIR-002
```

 

## Exercise 4: Cancel a Resting Combo

```
[TRADER01]> CANCEL|COMBO_ID=PAIR-002
```

All legs are cancelled together.

:material-checkbox-blank-outline: **Checkpoint:** full combo cancellation confirmed.

 

## Exercise 5: OCO — One-Cancels-Other

Link two independent orders so that when one fills or is cancelled, the other
is automatically cancelled:

```
[TRADER01]> NEW|TYPE=OCO|OCO_ID=OCO-AAPL-ENTRY|SYM=AAPL|QTY=100|TIF=DAY|LEG1_SIDE=BUY|LEG1_TYPE=LIMIT|LEG1_PRICE=149.50|LEG2_SIDE=BUY|LEG2_TYPE=LIMIT|LEG2_PRICE=148.00
```

When the first order fills (price drops to 149.50), the second order at 148.00
is automatically cancelled.

:material-checkbox-blank-outline: **Checkpoint:** filling one OCO leg cancels the other.

 

## Exercise 6: OCO with Different Sides

A common pattern — bracket order (take-profit + stop-loss):

```
[TRADER01]> NEW|TYPE=OCO|OCO_ID=BRACKET-AAPL-001|SYM=AAPL|QTY=100|TIF=DAY|LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|LEG1_PRICE=151.00|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=149.00
```

If price rises to 151.00 (take-profit fills), the stop is cancelled.
If price drops to 149.00 (stop triggers and fills), the limit sell is cancelled.

:material-checkbox-blank-outline: **Checkpoint:** bracket order behaves as expected.

 

## When to Use Combos vs OCO

| Use Case | Mechanism |
|----------|-----------|
| Spread / pairs trade (buy A + sell B) | Combo |
| Hedging (must have both sides or neither) | Combo — but see the caveat below |
| Take-profit + stop-loss (only want one to execute) | OCO |
| Multiple entries at different prices (only want one) | OCO |

!!! warning "\"Both sides or neither\" holds at entry, not while resting"
    An AON combo will not execute half of itself when you submit it. It *can*
    end up half-filled if it rests and someone hits one leg, as Exercise 3
    showed. If you genuinely need "both or neither", either submit only when
    both sides are already fillable, or cancel the combo as soon as it fails
    to execute at entry rather than leaving it working.

 

## Reflection

An AON combo is described as "all-or-none", yet a combo can reach a state where
one leg is filled and another is still resting. Explain how both statements are
true at once, and name the moment at which the guarantee applies.

Why is a Combo's entry atomicity a *guarantee* while an OCO's "one cancels other"
is a *reaction* to the first fill? Could an OCO ever leave you exposed for a
brief moment that a Combo would not — and why does that difference matter for
a pairs trade versus a take-profit/stop-loss pair?

## Further Reading

- [Combo Orders](../user-guide/070-combo-orders.md)
- [ALF Protocol — OCO and Combo Orders](../user-guide/900-app-alf-protocol.md)

 

**Next:** [11 — Risk Controls](110-risk-controls.md)

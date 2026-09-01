# Amending Orders

## Objective

Learn to modify resting orders — change price, quantity, or both — and
understand how amendments affect queue priority.

 


!!! abstract "Pre-reading in the User Guide"
    - [Order Amendment (AMEND)](../user-guide/060-order-types.md#order-amendment-amend)
    - [ALF Console](../user-guide/055-alf-console.md)

## Prerequisites

- Exchange running with two-sided liquidity from previous chapters
    (manual MM gateways or `pm-mm-bot`).
- `TRADER01` connected with at least one resting limit order.

 

## Exercise 1: Place a Resting Order to Amend

```
[TRADER01]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=300|PRICE=419.50|TIF=DAY|TAG=AMD-ORDER-001
```

Note the `order_id` returned.

`TAG` identifies the order and is echoed on later lifecycle events. `RTAG` is
different: it identifies one amend request against that order.

`AMEND` accepts an optional `RTAG=<request-tag>`. The tag identifies this one
amend request and is echoed on the `AMENDED` response or rejected ACK, which is
useful when several changes are outstanding for the same order.

:material-checkbox-blank-outline: **Checkpoint:** order resting; `ORDERS` confirms qty=300, price=419.50.

 

## Exercise 2: Amend Quantity Down

Reduce the order to 200 shares:

```
[TRADER01]> AMEND|ID=<order_id>|QTY=200|RTAG=AMD-DOWN-001
```

Expected: amendment accepted; new qty=200.

!!! note "Priority preserved"
    Reducing quantity does **not** lose time priority — your order keeps its
    place in the queue.

    Why: you are not jumping ahead of anyone; you are only reducing your own
    claim at the same price level.

:material-checkbox-blank-outline: **Checkpoint:** `ORDERS` shows qty=200, same price.

 

## Exercise 3: Amend Price

Move the order to a more aggressive price:

```
[TRADER01]> AMEND|ID=<order_id>|PRICE=419.70|RTAG=AMD-PRICE-001
```

Expected: amendment accepted; new price=419.70.

!!! warning "Priority lost"
    A price change **always** loses time priority — the order moves to the back
    of the queue at the new price level.

    Why: a new price is treated as a new offer, so queue fairness requires
    re-entering at the back.

:material-checkbox-blank-outline: **Checkpoint:** `ORDERS` shows price=419.70.

 

## Exercise 4: Amend Both Price and Quantity

```
[TRADER01]> AMEND|ID=<order_id>|PRICE=419.60|QTY=150|RTAG=AMD-BOTH-001
```

:material-checkbox-blank-outline: **Checkpoint:** both fields updated in one command.

 

## Exercise 5: Attempt an Invalid Amendment

Try setting quantity to zero:

```
[TRADER01]> AMEND|ID=<order_id>|QTY=0|RTAG=AMD-BAD-001
```

Expected: rejection — quantity must be positive. The rejected ACK includes a
stable `REJECT_CODE` as well as the text reason.

Try amending a non-existent order:

```
[TRADER01]> AMEND|ID=INVALID123|PRICE=100.00|RTAG=AMD-MISSING-001
```

Expected: rejection — order not found, with `REJECT_CODE=ORDER_NOT_FOUND`.

:material-checkbox-blank-outline: **Checkpoint:** both invalid amendments rejected with clear errors.

 

## Exercise 6: Amend After Partial Fill

1. Place a large buy:
   ```
   [TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=500|PRICE=150.10|TIF=DAY
   ```
   (This may immediately fill partially against the MM ask.)

2. If partially filled, amend the remaining quantity:
   ```
    [TRADER01]> AMEND|ID=<order_id>|QTY=200|RTAG=AMD-PARTIAL-001
   ```

!!! note
    The new qty must be **strictly greater than** the already-filled quantity. Setting it equal to the filled quantity is rejected — use `CANCEL` if you want the remainder gone. You cannot amend below
    what has already been executed.

:material-checkbox-blank-outline: **Checkpoint:** amendment accepted on partially filled order.

 

## Exercise 7: See Queue Priority Change

The rules below are easy to state and easy to disbelieve. This exercise makes
them visible, using two traders queued at the same price.

**Step 1 — build a queue.** From `TRADER01`, then `TRADER02`, place the same
buy at the same price. `TRADER01` is now *ahead* in the queue because it
arrived first:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=149.50|TIF=DAY
[TRADER02]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=149.50|TIF=DAY
```

Confirm both are resting at 149.50 in the operator console:

```
[GW_ADMIN|ADMIN]> BOOK|SYM=AAPL
```

**Step 2 — reduce quantity and prove priority survives.** From `TRADER01`,
amend *down* to 50:

```
[TRADER01]> AMEND|ID=<TRADER01 order id>|QTY=50|RTAG=AMD-KEEP-001
```

Now have a third party sell 50 into the bid. Because `TRADER01` kept its
place, `TRADER01` is filled and `TRADER02` is untouched:

```
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=50|PRICE=149.50|TIF=DAY
```

Check who filled with `STATUS` on each trader console.

**Step 3 — increase quantity and prove priority is lost.** Rebuild the queue
as in step 1, then amend `TRADER01` *up*:

```
[TRADER01]> AMEND|ID=<TRADER01 order id>|QTY=200|RTAG=AMD-LOSE-001
```

Sell 100 into the bid again. This time `TRADER02` fills first, because
`TRADER01`'s increase sent it to the back of the queue at that price.

:material-checkbox-blank-outline: **Checkpoint:** in step 2 `TRADER01` filled;
in step 3 `TRADER02` filled. You have now *observed* the rule in the table
below rather than taking it on trust.

!!! tip "Use the full order ID"
    `ORDERS` truncates the order ID for display. `AMEND` and `CANCEL` need the
    **complete** ID — copy it from the acknowledgement you received when the
    order was placed, not from the truncated column.

!!! tip "Use one RTAG per request"
    `RTAG` is not the order ID. It is a request label, so use a fresh value for
    each amend you want to correlate in logs, terminal output, or tests.

 

## Key Rules

| Change | Priority Impact | Why |
|--------|----------------|-----|
| Quantity down | Priority preserved | You are asking for less; nobody behind you is disadvantaged |
| Quantity up | Priority lost | The extra quantity never queued — keeping your slot would jump it ahead of orders that arrived earlier |
| Price change (any direction) | Priority lost | A different price is a different queue |
| Both price and qty | Priority lost | As above |

 

## Reflection

Why does reducing quantity preserve time priority, but increasing it does
not? What unfair advantage would a trader gain if increasing quantity kept
their original priority in a busy book?

## Further Reading

- [ALF Console (pm-alf-console)](../user-guide/055-alf-console.md)
- [ALF Protocol — AMEND](../user-guide/900-app-alf-protocol.md)

 

**Next:** [05 — Order Types Deep Dive](05-order-types.md)

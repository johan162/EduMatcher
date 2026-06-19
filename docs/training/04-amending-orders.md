# Amending Orders

## Objective

Learn to modify resting orders — change price, quantity, or both — and
understand how amendments affect queue priority.

---

## Prerequisites

- Exchange running with two-sided liquidity from previous chapters
    (manual MM gateways or `pm-mm-bot`).
- `TRADER01` connected with at least one resting limit order.

---

## Exercise 1: Place a Resting Order to Amend

```
TRADER01> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=300|PRICE=419.50|TIF=DAY
```

Note the `order_id` returned.

:material-checkbox-blank-outline: **Checkpoint:** order resting; `ORDERS` confirms qty=300, price=419.50.

---

## Exercise 2: Amend Quantity Down

Reduce the order to 200 shares:

```
TRADER01> AMEND|ID=<order_id>|QTY=200
```

Expected: amendment accepted; new qty=200.

!!! note "Priority preserved"
    Reducing quantity does **not** lose time priority — your order keeps its
    place in the queue.

    Why: you are not jumping ahead of anyone; you are only reducing your own
    claim at the same price level.

:material-checkbox-blank-outline: **Checkpoint:** `ORDERS` shows qty=200, same price.

---

## Exercise 3: Amend Price

Move the order to a more aggressive price:

```
TRADER01> AMEND|ID=<order_id>|PRICE=419.70
```

Expected: amendment accepted; new price=419.70.

!!! warning "Priority lost"
    A price change **always** loses time priority — the order moves to the back
    of the queue at the new price level.

    Why: a new price is treated as a new offer, so queue fairness requires
    re-entering at the back.

:material-checkbox-blank-outline: **Checkpoint:** `ORDERS` shows price=419.70.

---

## Exercise 4: Amend Both Price and Quantity

```
TRADER01> AMEND|ID=<order_id>|PRICE=419.60|QTY=150
```

:material-checkbox-blank-outline: **Checkpoint:** both fields updated in one command.

---

## Exercise 5: Attempt an Invalid Amendment

Try setting quantity to zero:

```
TRADER01> AMEND|ID=<order_id>|QTY=0
```

Expected: rejection — quantity must be positive.

Try amending a non-existent order:

```
TRADER01> AMEND|ID=INVALID123|PRICE=100.00
```

Expected: rejection — order not found.

:material-checkbox-blank-outline: **Checkpoint:** both invalid amendments rejected with clear errors.

---

## Exercise 6: Amend After Partial Fill

1. Place a large buy:
   ```
   TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=500|PRICE=150.10|TIF=DAY
   ```
   (This may immediately fill partially against the MM ask.)

2. If partially filled, amend the remaining quantity:
   ```
    TRADER01> AMEND|ID=<order_id>|QTY=200
   ```

!!! note
    The new qty must be ≥ already-filled quantity. You cannot amend below
    what has already been executed.

:material-checkbox-blank-outline: **Checkpoint:** amendment accepted on partially filled order.

---

## Key Rules

| Change | Priority Impact |
|--------|----------------|
| Quantity down | Priority preserved |
| Quantity up | Priority lost |
| Price change (any direction) | Priority lost |
| Both price and qty | Priority lost |

---

## Further Reading

- [Gateway Commands](../user-guide/08-gateway.md)
- [ALF Protocol — AMEND](../user-guide/20-app-alf-protocol.md)

---

**Next:** [05 — Order Types Deep Dive](05-order-types.md)

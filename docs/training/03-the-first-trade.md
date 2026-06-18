# 03 — The First Trade

## Objective

Execute your first buy and sell trades against the market-maker quotes and
understand fill messages, order IDs, and the order book lifecycle.

---

## Prerequisites

- Engine, scheduler, and MM bots running from chapters 01–02.
- `TRADER01` gateway connected.

---

## Exercise 1: Buy at Market — Lift the Ask

From `TRADER01`, send a market buy order for AAPL:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
```

Expected output:

```
[FILL] order_id=... AAPL BUY 100@150.05 status=FILLED
```

The order matched against the MM's ask at 150.05.

:material-checkbox-blank-outline: **Checkpoint:** you received a fill confirmation.

---

## Exercise 2: Sell at Market — Hit the Bid

```
TRADER01> NEW|SYM=AAPL|SIDE=SELL|TYPE=MARKET|QTY=100
```

Expected output:

```
[FILL] order_id=... AAPL SELL 100@149.95 status=FILLED
```

:material-checkbox-blank-outline: **Checkpoint:** sell fill at the bid price.

---

## Exercise 3: Place a Limit Buy Order

Place a buy order below the current bid — it should rest on the book:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=200|PRICE=149.80|TIF=DAY
```

Expected: order acknowledged, status=NEW (resting).

Verify with:

```
TRADER01> BOOK|SYM=AAPL
```

You should see your 200-lot bid at 149.80 below the MM's bid.

:material-checkbox-blank-outline: **Checkpoint:** limit order visible in the book.

---

## Exercise 4: Place a Limit Sell and Get a Fill

Now from `TRADER02` (open a second gateway if not already):

```bash
pm-gateway --id TRADER02
```

```
TRADER02> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=50|PRICE=149.80|TIF=DAY
```

This sell crosses TRADER01's resting bid at 149.80 → immediate fill.

Both gateways receive fill notifications:

- TRADER01: partial fill (200→150 remaining)
- TRADER02: full fill (50 filled)

:material-checkbox-blank-outline: **Checkpoint:** cross-gateway fill confirmed on both sides.

---

## Exercise 5: Check Order Status

From TRADER01, check the status of the partially filled order:

```
TRADER01> STATUS|ORDER_ID=<order_id_from_exercise_3>
```

Expected: `qty=200, filled=50, remaining=150, status=PARTIAL`

:material-checkbox-blank-outline: **Checkpoint:** STATUS shows partial fill correctly.

---

## Exercise 6: Observe the MM Bot Re-quoting

After your market order in Exercise 1 lifted the MM's ask, the MM bot
automatically re-quoted. Run BOOK again:

```
TRADER01> BOOK|SYM=AAPL
```

The MM should have a fresh two-sided quote (possibly at a slightly different
mid if the trade moved the reference price).

:material-checkbox-blank-outline: **Checkpoint:** MM has re-quoted after being filled.

---

## Key Concepts Learned

- **Market orders** execute immediately against the best available price.
- **Limit orders** rest on the book until a matching counterparty arrives.
- **Fills** generate fill messages to both buyer and seller.
- **Partial fills** leave the remainder resting.
- **Order IDs** are used for STATUS, AMEND, and CANCEL operations.

---

**Next:** [04 — Amending Orders](04-amending-orders.md)

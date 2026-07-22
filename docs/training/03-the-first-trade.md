# The First Trade

## Objective

Execute your first buy and sell trades against the market-maker quotes and
understand fill messages, clearing records, order IDs, and the order book
lifecycle.

 

## Prerequisites

- Engine and scheduler running from chapters 01–02.
- MM liquidity running from chapter 02 (manual MM gateways or `pm-mm-bot`).
- `TRADER01` gateway connected.
- One spare terminal for the clearing process.

 

## Exercise 1: Start Clearing

In a new terminal, start the clearing process before you trade:

```bash
pm-clearing
```

`pm-clearing` subscribes to executed trades, updates per-gateway positions and
P&L, and writes batched results to `clearing.db` (SQLite) in the data
directory — not a CSV file. Use `pm-clearing-cli --format csv ...` afterward
if you want a CSV export. Leave `pm-clearing` running while you work through
this chapter.

:material-checkbox-blank-outline: **Checkpoint:** clearing is running and waiting for trades.

 

## Exercise 2: Buy at Market — Lift the Ask

From `TRADER01`, send a market buy order for AAPL:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
```

Expected output:

```
[FILL] order_id=... AAPL BUY 100@150.05 status=FILLED
```

The order matched against the MM's ask at 150.05.

Now switch to the `pm-clearing` terminal. You should see the trade reflected in
the clearing output: `TRADER01` has bought AAPL, the market-maker gateway has
sold AAPL, and positions/P&L are updated from the execution price.

:material-checkbox-blank-outline: **Checkpoint:** you received a fill confirmation and can see the trade in `pm-clearing`.

 

## Exercise 3: Sell at Market — Hit the Bid

```
TRADER01> NEW|SYM=AAPL|SIDE=SELL|TYPE=MARKET|QTY=100
```

Expected output:

```
[FILL] order_id=... AAPL SELL 100@149.95 status=FILLED
```

:material-checkbox-blank-outline: **Checkpoint:** sell fill at the bid price.

 

## Exercise 4: Place a Limit Buy Order

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

 

## Exercise 5: Place a Limit Sell and Get a Fill

Now from `TRADER02` (open a second gateway if not already):

```bash
pm-alf-console --id TRADER02
```

```
TRADER02> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=50|PRICE=149.80|TIF=DAY
```

This sell crosses TRADER01's resting bid at 149.80 → immediate fill.

Both gateways receive fill notifications:

- TRADER01: partial fill (200→150 remaining)
- TRADER02: full fill (50 filled)

:material-checkbox-blank-outline: **Checkpoint:** cross-gateway fill confirmed on both sides.

 

## Exercise 6: Check Order State

From TRADER01, inspect the partially filled order:

```
TRADER01> ORDERS
```

Expected: the order from Exercise 4 appears with filled and remaining quantity
showing the partial fill.

:material-checkbox-blank-outline: **Checkpoint:** ORDERS shows partial fill state correctly.

 

**Optional:** If you have `pm-viewer` running on AAPL, you should see the bid size drop from 200 to 150 after the fill.


## Exercise 7 (Optional): Observe Automatic Re-Quoting with pm-mm-bot

If you are running `pm-mm-bot` for AAPL (instead of manual quoting), your
market order in Exercise 2 should trigger automatic re-quoting. Run BOOK again:

```
TRADER01> BOOK|SYM=AAPL
```

The MM should have a fresh two-sided quote (possibly at a slightly different
mid if the trade moved the reference price).

:material-checkbox-blank-outline: **Checkpoint:** MM has re-quoted after being filled.

 

## Key Concepts Learned

- **Market orders** execute immediately against the best available price.
- **Limit orders** rest on the book until a matching counterparty arrives.
- **Fills** generate fill messages to both buyer and seller.
- **Clearing** consumes executed trades and turns them into positions and P&L.
- **Partial fills** leave the remainder resting.
- **Order IDs** are used for AMEND and CANCEL operations.

## Reflection

Why does a MARKET order carry no `PRICE` field at all, while a LIMIT order
requires one? What risk would a MARKET order expose you to in a thin book
that a LIMIT order would protect you from?

## Further Reading

- [Your First Trade](../concepts/04-concepts-first-trade.md)
- [The Order Book](../concepts/01-concepts-order-book.md)
- [Gateway Commands](../user-guide/050-gateway.md)

 

**Next:** [04 — Amending Orders](04-amending-orders.md)

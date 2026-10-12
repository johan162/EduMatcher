# The First Trade

## Objective

Execute your first buy and sell trades against the market-maker quotes and
understand fill messages, clearing records, order IDs, and the order book
lifecycle.

 


!!! abstract "Background reading"
    - [ALF Console](../participant-guide/part-2-orders/010-the-trader-console.md)
    - [Order Types](../participant-guide/part-2-orders/020-order-types.md)

## Prerequisites

- Engine running from chapters 01–02, with the market open in `CONTINUOUS`.
- The manual AAPL quote from chapter 02 active: `MM_AAPL_01` bidding 149.95
  and asking 150.05, 500 shares each side, and its console still open. (With
  `pm-mm-bot` quoting instead, the prices and sizes below will differ.)
- `TRADER01` gateway connected, and the operator console open.
- One spare terminal for the clearing process.

 

## Exercise 1: Start Clearing

In a new terminal, start the clearing process before you trade:

```bash
pm-clearing --print-every 1
```

`pm-clearing` subscribes to executed trades, updates per-gateway positions and
P&L, and writes batched results to `clearing.db` (SQLite) in the data
directory — not a CSV file. Use `pm-clearing-cli --format csv ...` afterward
if you want a CSV export. `--print-every 1` makes it print its P&L summary
after every trade; by default it prints only every 100 trades. Leave
`pm-clearing` running while you work through this chapter.

!!! note "Start recorders before the trading"
    `pm-clearing` only sees trades that happen while it is running. Started
    after a trade, it never learns about it, and its positions will be wrong
    from then on.

:material-checkbox-blank-outline: **Checkpoint:** clearing is running and waiting for trades.

 

## Exercise 2: Buy at Market — Lift the Ask

From `TRADER01`, send a market buy order for AAPL:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
```

Expected output (the console's fill line reports the order ID, quantity,
price and remaining/status — not the symbol or side, since you already know
those from the order you just sent):

```
[<time>] FILL      <order_id>  qty=100 @150.05  remaining=0  [FILLED]
```

The order matched against the MM's ask at 150.05.

Now switch to the `pm-clearing` terminal. Within a few seconds it prints a P&L
summary: `TRADER01` is long 100 AAPL at 150.05, and `MM_AAPL_01` is short 100
at the same price.

Look at the market maker's console too:

```
[<time>] FILL      <ask leg id>  qty=100 @150.05  remaining=400  [PARTIAL]
[<time>] CANCELLED <bid leg id>
[<time>] QUOTE INACTIVE_ASK_FILLED  AAPL-MM-001
```

Chapter 02 configured `MM_AAPL_01` with `quote_refresh_policy:
INACTIVATE_ON_ANY_FILL`: the moment either side of its quote is hit, the
engine **pulls the other side** and marks the quote inactive, while the
remaining 400 on the hit side keep resting. This protects a market maker from
being hit again before it has had time to reprice — and it means AAPL now has
no bid at all.

:material-checkbox-blank-outline: **Checkpoint:** you received a fill confirmation and can see the trade in `pm-clearing`.

 

## Exercise 3: Sell at Market — Hit the Bid

With no bid in the book, a market sell would have nothing to trade against —
try it and the order is accepted and immediately `CANCELLED`. So let the
market maker re-quote first, as a real one would after a fill:

```
[MM_AAPL_01]> QUOTE|SYM=AAPL|BID=149.95|ASK=150.05|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=AAPL-MM-002
```

The new quote replaces the old one (its 400-share remainder is cancelled).
Now sell:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=SELL|TYPE=MARKET|QTY=100
```

Expected output, in the same format as Exercise 2:

```
[<time>] FILL      <order_id>  qty=100 @149.95  remaining=0  [FILLED]
```

This time the market maker's **ask** is pulled, and 400 shares remain bid at
149.95.

:material-checkbox-blank-outline: **Checkpoint:** sell fill at the bid price, and you can explain why the market maker had to re-quote first.

 

## Exercise 4: Place a Limit Buy Order

Place a buy order below the current bid — it should rest on the book:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=200|PRICE=149.80|TIF=DAY
```

Expected: order acknowledged, status=NEW (resting).

Verify in the **operator console** — a trader cannot see the whole book:

```
[GW_ADMIN|ADMIN]> BOOK|SYM=AAPL
```

You should see two bids: the market maker's 400 at 149.95 on top, and your
200 at 149.80 below it — the book is sorted best price first.

:material-checkbox-blank-outline: **Checkpoint:** limit order visible in the book.

 

## Exercise 5: Place a Limit Sell and Get a Fill

Now from `TRADER02` (open a second gateway if not already):

```bash
pm-alf-console --id TRADER02
```

```
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=450|PRICE=149.80|TIF=DAY
```

TRADER02 will sell 450 shares at 149.80 *or better*. The engine fills it
against the best bids first — **price priority**:

- 400 shares at **149.95** against the market maker, a better price than
  TRADER02 asked for (this is *price improvement*);
- the last 50 shares at **149.80** against TRADER01.

TRADER01 receives a partial fill (200 → 150 remaining). TRADER02's console
reports the whole order filled at the average price,
`qty=450 @149.9333…` — (400 × 149.95 + 50 × 149.80) / 450.

:material-checkbox-blank-outline: **Checkpoint:** cross-gateway fill confirmed on both sides.

 

## Exercise 6: Check Order State

From TRADER01, inspect the partially filled order:

```
[TRADER01]> ORDERS
```

Expected: the order from Exercise 4 appears with filled and remaining quantity
showing the partial fill.

:material-checkbox-blank-outline: **Checkpoint:** ORDERS shows partial fill state correctly.

 

**Optional:** If you have `pm-viewer` running on AAPL, you should see the bid size drop from 200 to 150 after the fill.


## Exercise 7 (Optional): Observe Automatic Re-Quoting with pm-mm-bot

If you are running `pm-mm-bot` for AAPL (instead of manual quoting), your
market order in Exercise 2 should trigger automatic re-quoting. Run `BOOK`
again in the operator console:

```
[GW_ADMIN|ADMIN]> BOOK|SYM=AAPL
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

- [Your First Trade](../quick-start/part-1-see-it-run/030-your-first-trade.md)
- [The Order Book](../participant-guide/part-1-trading-basics/020-the-order-book.md)
- [ALF Console (pm-alf-console)](../participant-guide/part-2-orders/010-the-trader-console.md)

 

**Next:** [04 — Amending Orders](040-amending-orders.md)

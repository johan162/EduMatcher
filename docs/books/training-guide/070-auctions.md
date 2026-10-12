# Auctions

## Objective

Run opening and closing auctions, understand equilibrium price calculation, and
observe how auction orders are collected and matched in a single uncrossing event.

 


!!! abstract "Background reading"
    - [Equilibrium price](../operator-guide/part-4-run-a-market/030-sessions-and-scheduling.md#equilibrium-price)
    - [What are auctions?](../operator-guide/part-4-run-a-market/030-sessions-and-scheduling.md#what-are-auctions)

## Prerequisites

- Chapters 01–06 completed.
- Scheduler control available so you can observe auction phases.

 

## Background

Auctions concentrate liquidity at a single price. All orders are collected
during the auction phase, then matched at the **equilibrium price** — the price
that maximises the quantity traded.

Key properties:

- No partial information leakage (indicative prices may be shown).
- All fills happen at the same price.
- Prevents manipulation via timing advantages.

 

## Exercise 1: Set Up for an Opening Auction

Stop the scheduler and use manual phase control instead (see
[06 — Freeze/Advance Procedure](060-time-in-force-sessions.md#freezeadvance-procedure-deterministic-session-control)).
You want to be sitting in `OPENING_AUCTION` — **not** `PRE_OPEN` — before
sending the `TIF=ATO` orders below: the engine only accepts `ATO` orders
while the session state is exactly `OPENING_AUCTION` and rejects them during
`PRE_OPEN` even though `PRE_OPEN` accepts orders generally. With no
scheduler running, a freshly started engine sits in `CLOSED`, and `CLOSED`'s
only legal move is to `PRE_OPEN` — so get there first, then go on to
`OPENING_AUCTION`:

```
[GW_ADMIN|ADMIN]> SESSION|STATE=PRE_OPEN
```

Before the auction starts, empty the AAPL book. The market-maker quotes from
chapter 02 would otherwise take part in the auction too, and the calculation
in Exercise 2 assumes only the four orders below. Stop any `pm-mm-bot` and AI
traders, then cancel everything resting on AAPL — orders and quotes — and
check the book is empty:

```
[GW_ADMIN|ADMIN]> CANCEL_SYM|SYM=AAPL
[GW_ADMIN|ADMIN]> BOOK|SYM=AAPL
[GW_ADMIN|ADMIN]> SESSION|STATE=OPENING_AUCTION
```

From two gateways, enter orders while in `OPENING_AUCTION`:

**TRADER01:**
```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=300|PRICE=150.50|TIF=ATO
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=200|PRICE=150.20|TIF=ATO
```

**TRADER02:**
```
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=400|PRICE=149.80|TIF=ATO
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.30|TIF=ATO
```

:material-checkbox-blank-outline: **Checkpoint:** orders accepted, resting in auction book.

 

## Exercise 2: Trigger the Auction Uncrossing

When the scheduler transitions from OPENING_AUCTION → CONTINUOUS, all crossing
orders match at the equilibrium price.

For the exact orders entered in Exercise 1, here is the full calculation
(verified against `engine/auction.py`):

| Candidate price | Cumulative buy qty (bids ≥ price) | Cumulative sell qty (asks ≤ price) | Matched qty | Surplus |
|---|---|---|---|---|
| 149.80 | 500 (300+200) | 400 | **400** | 100 |
| 150.20 | 500 | 400 | 400 | 100 |
| 150.30 | 300 | 500 | 300 | 200 |
| 150.50 | 300 | 500 | 300 | 200 |

Maximum matched quantity is 400, tied between 149.80 and 150.20 with equal
surplus (100). The engine scans candidate prices from lowest to highest and
only replaces the current best on a **strict** improvement, so the **first**
price reached with the best (qty, surplus) pair wins. That means the
equilibrium price here is **149.80** — the lower of the two tied prices —
not a value in between.

Expected: all fills print execution price `149.80`, for a total matched
quantity of 400 shares. TRADER01's second order fills 100 of its 200 shares
and reports `[PARTIAL]`; its unfilled 100, and TRADER02's sell at 150.30, then
expire, because an `ATO` order only lives for the opening auction.

What to observe: identify the one common execution price printed across all
fill events, and confirm it equals `149.80` and the total filled quantity
equals `400` (300 from TRADER01's first order + 100 remaining from the
second, against TRADER02's 400-share sell).

:material-checkbox-blank-outline: **Checkpoint:** all fills report execution price `149.80` and matched quantity `400`.

 

## Exercise 3: Unfilled Auction Orders

If an ATO order does not cross (e.g. a buy at 148.00 with no matching sell),
it expires when CONTINUOUS begins.

Place:

```
[TRADER01]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=400.00|TIF=ATO
```

After the auction uncrosses this order is not filled — the MSFT market maker
from chapter 02 asks about 420, far above 400 — and the console reports it
`EXPIRED`. (The console's explanation reads *DAY order — trading day ended*;
for an `ATO` order, read it as *the opening auction ended*.)

:material-checkbox-blank-outline: **Checkpoint:** the unmatched ATO order expired at the start of CONTINUOUS.

 

## Exercise 4: Closing Auction

Move the session to the closing auction:

```
[GW_ADMIN|ADMIN]> SESSION|STATE=CLOSING_AUCTION
```

Then enter:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.80|TIF=ATC
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.60|TIF=ATC
```

Close the day; on the transition to CLOSED the auction uncrosses and fills
are generated:

```
[GW_ADMIN|ADMIN]> SESSION|STATE=CLOSED
```

Remember to reopen the market (`PRE_OPEN`, then `CONTINUOUS`) before the next
chapter.

:material-checkbox-blank-outline: **Checkpoint:** closing auction produces fills.

 

## Exercise 5: GTC Orders in Auctions

GTC orders participate in auctions alongside ATO/ATC orders:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=150.00|TIF=GTC
```

This order participates in both opening and closing auctions, and rests during
CONTINUOUS trading.

:material-checkbox-blank-outline: **Checkpoint:** GTC order fills in auction or continues resting.

 

## Equilibrium Price Rules

The auction algorithm scans candidate prices from lowest to highest and
selects the price that:

1. **Maximises traded volume** — most shares can match.
2. **Minimises surplus** — least shares left unexecuted at that price.
3. **Ties resolved by scan order** — if multiple prices tie on both volume
   and surplus, the engine keeps the first (lowest) one it found, since it
   only replaces the current best on a strict improvement. There is no
   separate "nearest to last trade" tie-break — the tie always resolves to
   the lower of the tied candidate prices.

!!! note "How real exchanges break the tie"
    Most real exchanges use more steps after rules 1 and 2. If the surplus is
    on the buy side at every tied price, they pick the *highest* tied price
    (buyers are pressing, so the price moves up); if it is on the sell side,
    the lowest; and only if there is no clear pressure do they fall back to
    the price closest to a reference price, such as the last trade. In this
    chapter's example the surplus is on the buy side, so a typical exchange
    would uncross at 150.20, not 149.80. EduMatcher keeps the simpler rule so
    the result is easy to compute by hand — a good discussion point for the
    Reflection below.

 

## Reflection

Why does an auction match all crossing orders at a single equilibrium price,
instead of walking the book and filling each order at its own limit price
(as CONTINUOUS trading does)? What problem would arise at the open if every
order filled at its own price instead?

## Further Reading

- [Auctions & Scheduling](../operator-guide/part-4-run-a-market/030-sessions-and-scheduling.md)
- [Auction Equilibrium Concepts](../participant-guide/part-1-trading-basics/030-the-trading-day-and-auctions.md)
- [Order Types](../participant-guide/part-2-orders/020-order-types.md)

 

**Next:** [08 — Cancelling & Managing Orders](080-cancelling-orders.md)

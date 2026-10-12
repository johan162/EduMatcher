# Known Limitations & Bugs

!!! note "Learning objectives"
    After reading this page you will understand:

    - A real historical bug in how the engine reported fills for orders that
      sweep **multiple price levels** in a single execution
    - Why the bug affected only the **average cost** (and therefore unrealized
      P&L) of the aggressing order, never the **quantity** of any position
    - A worked numeric example that makes the size of the (former) error
      concrete, and what the engine reports today for the same scenario
    - How the fix actually works, as a short case study in fixing a reporting
      bug on a hot code path without changing the number of messages a
      gateway receives

    **Prerequisite**: Read [Positions and P&L](../../participant-guide/part-5-positions-and-results/010-positions-and-pnl.md) first — this page
    builds directly on the VWAP average-cost formula described there.

## What this page covers

EduMatcher is a teaching exchange, and part of teaching is being honest about
the places where the implementation used to take a shortcut — and what it
took to fix it properly. This chapter is a case study of one such bug: when a
single aggressive order traded against several resting orders at *different*
prices in one shot (a "sweep"), the engine used to collapse those fills into
**one** fill notification that carried the **last** trade price rather than
the true volume-weighted average.

The bug was subtle: nobody lost or gained shares, the public trade record was
always correct, and a single-price fill was always reported perfectly. The
error only ever showed up in the **average cost** that a trader's gateway
derived from the fill notification, and only for an order that walked through
more than one price level.

!!! success "Status: fixed"
    This was a genuine bug in early versions of EduMatcher. It was fixed in
    the matching engine (internally tagged **H6**, alongside the related
    duplicate-fill guard **H5**) before release 0.16.1. This page keeps the
    worked example and the diagrams as a case study — the mechanics below are
    exactly what shipped.

---

## Background: how a fill used to be reported

When an order arrives, the engine's `_handle_new_order` handler hands it to
the order book's `process()` method. Matching happens inside `_apply_fill`,
which is called **once per resting order that the aggressor trades against**.
Each call:

1. Creates a `Trade` record at that resting order's price.
2. Decrements the aggressor's `remaining_qty`.
3. Appends the **aggressor `Order` object** to the `events` list.

The crucial detail is in step 3: the engine appends the **same Python object**
each time. After the sweep finishes, that one object only holds its **final**
state — the total quantity filled and a `remaining_qty` of zero. The
per-level breakdown (how much filled at each price) is not visible on the
aggressor object afterwards; it only ever existed in the separate list of
`Trade` records.

After matching, the publish loop walks `events` and emits an `order.fill`
message for each fill. Because the aggressor object was appended N times (once
per price level it consumed), a guard called `_published_fill_ids` ensures the
engine still sends **exactly one** `order.fill` message for the aggressor
instead of N duplicates — that part of the design was correct from the start
and is unchanged today. What *that* single message reported was the bug:

```python
# The bug: every fill message used the price of the LAST trade in the
# sweep, no matter how many price levels the order actually walked through.
fill_price = from_ticks(book.last_trade_price, order.symbol)
```

`book.last_trade_price` is the price of the **last** fill in the sweep — the
deepest, least favourable level the order reached. That single price was then
reported for the **entire** filled quantity, at every site in the engine that
published a fill (the main order path, seeded quotes, combo legs, OCO legs,
and auction fills all shared the same mistake).

!!! note "The resting (passive) side was always correct"
    Every resting order the aggressor hits is a **distinct** object and is
    filled exactly once at its own price, so each passive participant has
    always received a correct per-price `order.fill`. The inaccuracy was
    limited to the **one** aggregated message sent to the **aggressing**
    order's gateway.

---

## How the gateway turns a fill into a position

A trading gateway tracks positions with VWAP average-cost accounting (see
[Positions and P&L](../../participant-guide/part-5-positions-and-results/010-positions-and-pnl.md)). On every `order.fill` it calls
`_update_position(symbol, side, fill_qty, fill_price)`, which folds the fill
into the running average:

$$
\text{avg\_cost}_\text{new} = \frac{\text{avg\_cost}_\text{old} \times \lvert q_\text{old} \rvert + \text{fill\_price} \times \text{fill\_qty}}{\lvert q_\text{new} \rvert}
$$

The gateway trusts `fill_price` as the price for the whole `fill_qty`. Before
the fix, when the engine sent one aggregated fill at the last sweep price, the
gateway booked the **entire** quantity at that single, least-favourable price
— overstating cost basis for a buy sweep and understating proceeds for a sell
sweep.

---

## Worked example

Suppose the ask side of the book holds three resting sell orders:

| Resting order | Price   | Quantity |
|---------------|---------|----------|
| A             | \$10.00 | 100      |
| B             | \$10.01 | 100      |
| C             | \$10.02 | 100      |

A trader sends an aggressive **BUY 300 (MARKET)** order. It sweeps all three
levels and three trades print:

| Trade | Price   | Quantity |
|-------|---------|----------|
| 1     | \$10.00 | 100      |
| 2     | \$10.01 | 100      |
| 3     | \$10.02 | 100      |

The **true** volume-weighted average price the buyer paid is:

$$
\text{VWAP} = \frac{100 \times 10.00 + 100 \times 10.01 + 100 \times 10.02}{300}
       = \frac{3003}{300} = \mathbf{10.01}
$$

**Before the fix**, the engine emitted a single aggregated fill using the last
trade's price:

```text
order.fill  →  fill_qty = 300   fill_price = 10.02 ✗   remaining_qty = 0
```

giving a reported average cost of \$10.02 — a \$0.01/share, \$3.00 total,
overstatement of the true \$10.01 cost basis.

**Today**, the engine still sends exactly **one** `order.fill` message for the
sweep (the message count did not change — see [How it was
fixed](#how-it-was-fixed) below), but the price on that message is the
order's own VWAP across every level it touched:

```text
order.fill  →  fill_qty = 300   fill_price = 10.01 ✓   remaining_qty = 0
```

which folds into the gateway's running average as exactly \$10.01 — matching
the true cost basis.

The three sellers (A, B, C) each receive, as they always did, a correct fill
at their own price, and the `trade.executed` market-data / drop-copy feed
carries all three trades at the right prices.

### Direction of the (former) error

The last level reached in a sweep is always the **worst** price for the
aggressor, so the old bug had a predictable sign:

| Aggressor side | Last level is… | Effect on the aggressor's books (before the fix)       |
|----------------|----------------|----------------------------------------------------------|
| **BUY**        | Highest price  | Cost basis **overstated** → unrealized P&L understated |
| **SELL**       | Lowest price   | Proceeds **understated** → unrealized P&L understated  |

In both directions the old, buggy report was **pessimistic**: it made a sweep
look like a slightly worse trade than it actually was. The magnitude equalled
the spread between the sweep's average price and its last price, multiplied
by the swept quantity.

!!! note "Position quantity was never wrong"
    The dedup guard (`_published_fill_ids`, H5) always guaranteed the quantity
    was counted **once**, so the net position size was always exact, even
    before the price fix. Only the **price** attached to that quantity was
    ever approximate.

---

## Visualising the fix

The diagram below contrasts the **three real trades** generated inside the
book with the **single fill** delivered to the aggressor's gateway, as it
works today.

```mermaid
sequenceDiagram
    autonumber
    participant GW as Aggressor Gateway
    participant ENG as Engine (order book)
    participant FEED as trade.executed feed

    GW->>ENG: BUY 300 @ MARKET
    Note over ENG: Sweep walks 3 price levels
    ENG->>FEED: Trade 1  100 @ 10.00
    ENG->>FEED: Trade 2  100 @ 10.01
    ENG->>FEED: Trade 3  100 @ 10.02
    Note over ENG: aggressor object appended 3x,<br/>holds only FINAL state (qty 300) —<br/>but _order_fill_prices() derives the<br/>VWAP (10.01) from the 3 Trade records
    ENG-->>GW: order.fill  qty=300  price=10.01  (ONE message)
    Note over GW: books 300 @ 10.01<br/>avg_cost = 10.01 ✓
```

The same idea as plain ASCII:

```text
   Book side (asks)                Trades printed            Fill sent to buyer
   ----------------                --------------            ------------------
   100 @ 10.00  ◄── swept ──►  Trade 1: 100 @ 10.00
   100 @ 10.01  ◄── swept ──►  Trade 2: 100 @ 10.01   ===►  order.fill
   100 @ 10.02  ◄── swept ──►  Trade 3: 100 @ 10.02            qty   = 300
                                                               price = 10.01  ✓
                               true VWAP = 10.01               (per-order VWAP)

   Correct quantity (300) ✓     Correct trade prints ✓     Correct average price ✓
```

Before the fix, the last line of the gateway note read `price = 10.02 ✗ (last
level only)` — the trade prints and the per-level book walk were identical;
only the number handed to the gateway was wrong.

---

## How it was fixed

The aggregation lives in the engine's hottest code path (`_handle_new_order`
and its siblings for seeded quotes, combo legs, OCO legs, and auctions), so a
fix that is correct but still cheap on that path mattered. The engine does
**not** split the aggregated message into one-per-level (which would double
or triple outbound message volume for every sweep); instead it keeps sending
exactly one `order.fill` per order per `process()` call, and computes that
message's price from the `Trade` records the book already produced:

```python
@staticmethod
def _order_fill_prices(trades: list[Any]) -> dict[str, float]:
    """Per-order volume-weighted execution price (display) from *trades*.

    H6: a fill message must report the price the order ACTUALLY executed
    at, not ``book.last_trade_price`` (the last level of the whole sweep).
    For an order that fills across multiple levels this is its VWAP; for a
    passive order filled at a single level it is exactly that level's price.
    """
    agg: dict[str, tuple[int, float]] = {}  # order_id -> (qty, notional)
    for t in trades:
        px = from_ticks(t.price, t.symbol)
        for oid in (t.buy_order_id, t.sell_order_id):
            qty, notional = agg.get(oid, (0, 0.0))
            agg[oid] = (qty + t.quantity, notional + px * t.quantity)
    return {oid: (n / q if q else 0.0) for oid, (q, n) in agg.items()}
```

Every fill-publishing site calls this once per `process()` result and looks up
each order's own VWAP by its id, falling back to `last_trade_price` only for
the (normally impossible) case of an order with no matching trade record:

```python
fill_price=_order_fill_px.get(evt.id, _fill_px)
```

This is cheaper than it looks: `trades` for a single dispatch is small (one
entry per price level swept, rarely more than a handful), so building the
per-order VWAP map costs one extra pass over data the book already produced —
no additional allocation on the matching path itself, and **no change** to
how many messages a gateway receives per order. The dedup guard (H5) that
ensures exactly one `order.fill` per order is unchanged; only the *price* it
carries is now correct.

Because no test asserted the specific (wrong) last-trade-price value, fixing
this required no changes to the existing test suite — only new tests asserting
that a multi-level sweep's fill price equals the true VWAP.

---

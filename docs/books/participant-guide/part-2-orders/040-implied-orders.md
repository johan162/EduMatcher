# Implied Orders (Synthetic Orders)

This section explains an advanced but very important exchange concept:
**implied orders** (also called **synthetic orders**).

!!! note "Not supported"

    This concept is not yet supported by EduMatcher
    Current EduMatcher combo handling is parent/child leg tracking over outright books. It does not yet implement a native synthetic instrument book with implied quote generation. This section describes the exchange-grade mechanism typically added in a later architectural step.


## The key idea in one paragraph

Some exchanges maintain a **spread book** — a separate order book whose
"instrument" is not a single stock but a *price difference* between two (or
more) stocks. For example, a spread book for "MSFT minus AAPL" lets traders
buy or sell the numerical difference between MSFT and AAPL prices as if it
were its own tradeable product. Concretely, "buying the spread at 205" means
you end up long MSFT and short AAPL at a net cost of 205 per share — regardless
of whether MSFT is at 415 and AAPL at 210, or MSFT at 420 and AAPL at 215.
You are trading the *gap*, not the individual prices.

Now imagine that spread book is empty — nobody has directly placed an order in
it. Yet on the **outright** MSFT book (the ordinary, single-symbol order book
where people trade just MSFT) there is a resting bid at 415.00 (meaning someone
is willing to buy MSFT at that price), and on the outright AAPL book there is a
resting ask at 210.10 (someone is willing to sell AAPL at that price).

Here is the key insight: any trader who wants to **sell** the spread (= sell
MSFT and buy AAPL) could execute against those two existing orders right now —
sell MSFT at 415.00 (hitting that bid) and buy AAPL at 210.10 (hitting that
ask) — netting 415.00 − 210.10 = 204.90. The exchange recognizes this and
automatically publishes a **synthetic bid of 204.90** in the spread book. That
synthetic quote is an **implied order** — executable liquidity that exists but
was never typed by any human.

Major derivatives exchanges (CME Globex, Eurex T7, ICE) rely heavily on implied
order engines to connect fragmented books and improve fill rates.

If you are new to markets, read this as:

- A **direct order** is something a trader explicitly entered.
- An **implied/synthetic order** is extra liquidity the exchange computes from
  other available orders.

## First: beginner terminology

- **Liquidity**: how much you can trade without waiting. More resting orders
  means more liquidity.
- **Bid**: highest price someone is willing to buy at.
- **Ask**: lowest price someone is willing to sell at.
- **Bid-ask spread**: the gap between the best ask and best bid in a single
  book (for example, if MSFT best bid is 415.00 and best ask is 415.20, the
  bid-ask spread is 0.20).
- **Spread instrument**: a synthetic product defined as the price difference
  between two or more symbols (for example, "MSFT minus AAPL"). Not the same
  as bid-ask spread — this is a tradeable product in its own right.
- **Resting order**: an order that has been posted to the book but not yet
  matched. It sits there passively, waiting for someone to trade against it.
- **Hitting**: executing against a resting order. "Hit the bid" means you
  sell to the person whose buy order is resting at the bid price. "Hit the
  ask" (also called "lifting the offer") means you buy from the person whose
  sell order is resting at the ask price.
- **Leg**: one component of a combo. A 2-leg combo has two child orders.
- **Outright**: a normal single-symbol market (for example, just MSFT).
- **Synthetic instrument**: a derived instrument built from other instruments
  (for example, spread = MSFT - AAPL).
- **Implied order**: a quoted buy/sell order in one book that is inferred from
  prices resting in related books.
- **Atomic execution**: all required legs execute together as one transaction,
  or none execute.

## Why combo markets are hard without implied orders

Combo markets have structural problems:

1. Fragmented liquidity:
  Liquidity exists in many places (outright books, other combo books), so one
  combo book can look empty even when executable prices exist elsewhere.

2. Leg risk:
  If a strategy is filled leg-by-leg manually, one leg can fill while others
  do not. The trader is left with unwanted directional exposure.

3. Wide displayed spreads:
  Without implied quotes, visible combo bid/ask can be sparse and wide,
  discouraging participation.

4. Price inconsistency:
  The same economic position can be priced differently across related markets,
  creating temporary dislocations.

## What problem implied orders solve

Implied orders solve a visibility and matching problem:

- They expose executable combo liquidity that already exists indirectly in
  related books.
- They tighten quoted spreads in combo books.
- They increase fill probability for strategy traders.
- They align related market prices more quickly.

Important: implied orders do not create "free money". They reveal and route
existing executable relationships between books.

## How implied orders accomplish this

At a high level, the exchange continuously does this:

1. Watch all relevant books (outrights and related combos).
2. Build candidate synthetic prices using valid price relationships.
3. Compute the maximum executable synthetic quantity from limiting legs.
4. Publish implied bid/ask levels in the target book.
5. Recompute immediately whenever any source book changes.

When a trader hits an implied quote, the exchange does not simply report a
theoretical price — it actually **executes** the underlying leg trades. For
example, if a trader sells the MSFT-AAPL spread at the implied bid of 204.90,
the exchange simultaneously:

1. Sells MSFT at 415.00 against the resting bid in the MSFT book.
2. Buys AAPL at 210.10 against the resting ask in the AAPL book.
3. Reports all fills to the respective parties.

This happens atomically — either both legs execute, or neither does. The
original resting orders in the outright books are consumed (partially or
fully), just as if someone had traded against them directly.

## Detailed calculation model (2-leg spread)

Assume a spread instrument:

$$
S = A - B
$$

where:

- $A$ is leg 1 (for example MSFT)
- $B$ is leg 2 (for example AAPL)
- $S$ is the synthetic spread market

Let:

- $A_{bid}$ = best bid price in A
- $A_{ask}$ = best ask price in A
- $B_{bid}$ = best bid price in B
- $B_{ask}$ = best ask price in B

### Implied bid for spread $S$

The implied bid represents resting synthetic buy interest — the price a spread
**seller** can receive by executing against existing outright liquidity.

To sell $S = A - B$, the seller:

- sells $A$ (hits the resting bid → receives $A_{bid}$), and
- buys $B$ (hits the resting ask → pays $B_{ask}$)

Net price received (= implied bid):

$$
S_{bid}^{impl} = A_{bid} - B_{ask}
$$

### Implied ask for spread $S$

The implied ask represents resting synthetic sell interest — the price a spread
**buyer** must pay to execute against existing outright liquidity.

To buy $S = A - B$, the buyer:

- buys $A$ (hits the resting ask → pays $A_{ask}$), and
- sells $B$ (hits the resting bid → receives $B_{bid}$)

Net price paid (= implied ask):

$$
S_{ask}^{impl} = A_{ask} - B_{bid}
$$

### Implied quantity

Implied size is constrained by the smallest executable leg quantity after ratio
normalization.

For 1:1 ratio spreads:

$$
Q_{impl} = \min(Q_A, Q_B)
$$

For general ratios $r_A : r_B$:

$$
Q_{impl} = \min\left(\left\lfloor\frac{Q_A}{r_A}\right\rfloor,
\left\lfloor\frac{Q_B}{r_B}\right\rfloor\right)
$$

## Generalized weighted synthetic pricing

For a multi-leg synthetic:

$$
P_{synthetic} = \sum_{i=1}^{n} w_i P_i
$$

where:

- $w_i$ are signed leg weights (positive for bought legs, negative for sold legs)
- $P_i$ are the price used for leg $i$, selected according to the
  side-selection rule below

**Side-selection rule:** the key question is "which price (bid or ask) do I
use for each leg?" The answer depends on *who is executing* and *which
direction they trade each leg*:

| Computing... | For legs you BUY | For legs you SELL |
|---|---|---|
| Synthetic **bid** (what a seller receives) | Use the **ask** (seller must buy this leg, hitting the ask) | Use the **bid** (seller sells this leg, hitting the bid) |
| Synthetic **ask** (what a buyer pays) | Use the **ask** (buyer buys this leg, hitting the ask) | Use the **bid** (buyer sells this leg, hitting the bid) |

Simplified: always use the price that the *taker* would actually receive or
pay — the bid when selling into it, the ask when buying into it. This ensures
the synthetic price reflects real executable costs, not theoretical mid-prices.

## Worked Example 1 (2-leg, equal ratios)

Goal: build implied quotes for spread $S = MSFT - AAPL$ (1:1).

Assume current books:

- MSFT best bid = 415.00 (qty 120)
- MSFT best ask = 415.20 (qty 80)
- AAPL best bid = 210.00 (qty 90)
- AAPL best ask = 210.10 (qty 200)

Implied spread bid:

$$
S_{bid}^{impl} = 415.00 - 210.10 = 204.90
$$

Implied spread ask:

$$
S_{ask}^{impl} = 415.20 - 210.00 = 205.20
$$

Implied bid quantity (1:1, using MSFT bid qty and AAPL ask qty):

$$
Q_{bid}^{impl} = \min(120, 200) = 120
$$

Implied ask quantity (1:1, using MSFT ask qty and AAPL bid qty):

$$
Q_{ask}^{impl} = \min(80, 90) = 80
$$

So the spread book can display synthetic liquidity:

- Bid 204.90 x 120
- Ask 205.20 x 80

Even if no trader directly entered spread orders.

## Worked Example 2 (3-leg with ratios)

Synthetic instrument:

$$
X = 2 \cdot A - 1 \cdot B - 3 \cdot C
$$

Interpretation per 1 unit of $X$:

- Buy 2 of A
- Sell 1 of B
- Sell 3 of C

Assume top-of-book:

- A bid/ask: 100.00 / 100.20, qty at ask = 250, qty at bid = 180
- B bid/ask: 40.10 / 40.30, qty at bid = 140, qty at ask = 300
- C bid/ask: 10.00 / 10.05, qty at bid = 500, qty at ask = 220

### Synthetic bid for X

The implied bid is what a **seller** of X receives. Selling X means reversing
the definition: sell A, buy B, buy C.

- sell A at $A_{bid}$ = 100.00 (qty available: 180)
- buy B at $B_{ask}$ = 40.30 (qty available: 300)
- buy C at $C_{ask}$ = 10.05 (qty available: 220)

Price:

$$
X_{bid}^{impl} = 2(100.00) - 1(40.30) - 3(10.05)
$$

$$
= 200.00 - 40.30 - 30.15 = 129.55
$$

Quantity limits by ratio:

- A supports $\lfloor 180/2 \rfloor = 90$ synthetic units
- B supports $\lfloor 300/1 \rfloor = 300$ synthetic units
- C supports $\lfloor 220/3 \rfloor = 73$ synthetic units

So:

$$
Q_{bid}^{impl} = \min(90, 300, 73) = 73
$$

### Synthetic ask for X

The implied ask is what a **buyer** of X pays. Buying X means executing the
definition directly: buy A, sell B, sell C.

- buy A at $A_{ask}$ = 100.20 (qty available: 250)
- sell B at $B_{bid}$ = 40.10 (qty available: 140)
- sell C at $C_{bid}$ = 10.00 (qty available: 500)

Price:

$$
X_{ask}^{impl} = 2(100.20) - 1(40.10) - 3(10.00)
$$

$$
= 200.40 - 40.10 - 30.00 = 130.30
$$

Quantity limits:

- A supports $\lfloor 250/2 \rfloor = 125$
- B supports $\lfloor 140/1 \rfloor = 140$
- C supports $\lfloor 500/3 \rfloor = 166$

So:

$$
Q_{ask}^{impl} = \min(125, 140, 166) = 125
$$

This yields implied quotes for X:

- Bid 129.55 x 73
- Ask 130.30 x 125

The implied spread is 0.75, representing normal market conditions. With different
input prices, implied markets can **cross** (bid ≥ ask), indicating an arbitrage
that production engines immediately consume via matching.

## Directions of implication

The examples above demonstrate **implied-in**: outright book liquidity is
combined to generate synthetic quotes in a combo/spread book. Production
exchanges support additional implication directions:

| Direction | Source → Target | Example |
|-----------|----------------|---------|
| Implied-in | Outrights → Spread | MSFT bid + AAPL ask → MSFT-AAPL spread bid |
| Implied-out | Spread → Outrights | A resting spread order implies an outright quote in one leg, given liquidity in the other |
| Implied-through | Spread → Spread | Liquidity in spread AB and outright B together imply a quote in spread AC |

**Implied-out example:** A trader posts "sell MSFT-AAPL spread at 205.00." If
AAPL has a resting bid at 210.00, the exchange can derive an implied offer in
MSFT at 415.00 (= 205.00 + 210.00). This publishes synthetic sell liquidity in
the outright MSFT book that did not previously exist.

**Implied-through** chains multiple relationships: spread AB liquidity combined
with outright B liquidity generates implied quotes in spread AC. The
combinatorial explosion of paths is the primary reason implied engines are
computationally expensive.

Most exchange implied engines support implied-in and implied-out. Only the most
sophisticated (CME Globex, Eurex T7) additionally support implied-through, often
limited to a configurable hop depth to bound computation.

## Practical implementation challenges

Building implied orders correctly in a matching engine is hard. Common issues:

1. Atomic routing:
  Implied fills must map to real leg executions in one atomic transaction.

2. Double counting:
  The same leg liquidity can be reachable through multiple synthetic paths.
  Engines must prevent over-committing that liquidity.

3. Priority policy:
  Venues define whether direct orders outrank implied orders at same price/time.

4. Performance:
  Every book update can trigger recomputation across many related instruments.

5. Consistency under concurrency:
  Between quote calculation and execution, source books can change. Matching
  must lock/sequence state safely.

6. Explainability:
  Traders and surveillance systems need audit trails showing which source
  liquidity created each implied fill.

## How this relates to EduMatcher today

Current EduMatcher combo handling is parent/child leg tracking over outright
books. It does not yet implement a native synthetic instrument book with implied
quote generation. This section describes the exchange-grade mechanism typically
added in a later architectural step.

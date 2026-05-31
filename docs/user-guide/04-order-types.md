# Order Types

!!! note "Learning objectives"
    After reading this page you will understand:

    - What each of the ten order types does and when to use it
    - The difference between aggressive (market/IOC/FOK) and passive (limit/iceberg) orders
    - How stop-family orders trigger and what happens after trigger
    - How time-in-force controls order lifetime across session phases
    - How combo and OCO orders manage multi-leg strategy risk

    **Prerequisite**: [The Order Book](../concepts/01-concepts-order-book.md) — you should understand
    price-time priority before diving into order type mechanics.

EduMatcher supports **ten order types**, from the simplest market order to
multi-leg combo/OCO orders used to execute strategies across multiple symbols
atomically.

## Contents

- [1. MARKET](#1-market)
- [2. LIMIT](#2-limit)
- [3. STOP (Stop-Market)](#3-stop-stop-market)
- [4. STOP_LIMIT](#4-stop_limit)
- [5. FOK (Fill-or-Kill)](#5-fok-fill-or-kill)
- [6. ICEBERG](#6-iceberg)
- [7. COMBO](#7-combo)
- [8. Time-in-Force (TIF)](#8-time-in-force-tif)
- [9. Stop Trigger Logic](#9-stop-trigger-logic)
- [10. IOC (Immediate-Or-Cancel)](#10-ioc-immediate-or-cancel)
- [11. TRAILING_STOP](#11-trailing_stop)
- [12. Order Amendment (AMEND)](#12-order-amendment-amend)
- [13. OCO (One-Cancels-Other)](#13-oco-one-cancels-other)

---

## 1. MARKET

[Back to Contents](#contents)

Executes immediately at the best available price.

### Background

Market orders are the oldest order instruction in listed markets. Before
electronic books, brokers executed "at market" instructions on exchange
floors by taking the best immediately available quote.

In modern matching engines, MARKET remains the purest urgency-driven order:
it prioritizes immediacy over price certainty.

### Motivation

Use MARKET when:

- Execution speed is more important than exact price.
- You are entering/exiting quickly in a liquid symbol.
- You are reducing directional risk and need certainty of fill.

- Sweeps the opposite side of the book (consumes resting orders from best
  price outward) as far as needed
- Partial fills are accepted — the unfilled remainder is **discarded** (not rested)
- No price specified

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
```

**Educational note**: Market orders **guarantee execution but not price**. In a
thin book (few resting orders, so liquidity is low), a large market order can
move the price significantly — this is called **slippage** (the difference
between expected execution price and actual average fill price).

---

## 2. LIMIT

[Back to Contents](#contents)

Executes at the specified price or better; any unfilled portion **rests on the
book** (remains posted as a passive order, waiting for a future counterparty
to trade against it).

### Background

LIMIT orders are the foundation of central limit order books (CLOBs). They
define displayed liquidity and form the visible bid/ask ladder used by all
other participants to price risk and route flow.

### Motivation

Use LIMIT when:

- Price control is more important than immediate execution.
- You want to provide liquidity and potentially earn spread capture.
- You are comfortable waiting in queue under price-time priority.

- Buy LIMIT: fills at `price` or lower
- Sell LIMIT: fills at `price` or higher
- Becomes a resting order if not immediately matchable

### Gateway Syntax

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.50
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.50|TIF=GTC
```

**Educational note**: Limit orders **guarantee price but not execution**. In a
thin book (few resting orders, so liquidity is low), a large limit order may
not fill immediately or at all, especially if the limit price is far from the
current market price.

---

## 3. STOP (Stop-Market)

[Back to Contents](#contents)

A dormant order that **activates** when the market touches the stop price, then executes as a MARKET order.

### Background

STOP orders became common as risk-management tools for both discretionary
traders and portfolio overlays. They were designed to automate exits without
requiring constant manual monitoring.

### Motivation

Use STOP when:

- You need a hard, automated risk cutoff (stop-loss).
- You want to enter on momentum confirmation (breakout stop-entry).
- Guaranteed execution after trigger matters more than trigger-to-fill price precision.

- `STOP` price is the trigger, not the execution price
- Buy STOP: triggers when last trade price ≥ stop price (used to enter long on breakout)
- Sell STOP: triggers when last trade price ≤ stop price (used to limit downside loss)

### Gateway Syntax

```
NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP|QTY=100|STOP=148.00
```

**Educational note**: Once triggered, a STOP becomes a MARKET order — execution price
is not guaranteed, especially in fast markets.

---

## 4. STOP_LIMIT

[Back to Contents](#contents)

Like STOP, but once triggered converts to a **LIMIT order** at a specified limit price.

### Background

STOP_LIMIT was introduced to address a classic STOP weakness: in fast or thin
markets, trigger-to-fill slippage can be large. By adding a limit cap, traders
can constrain worst-case execution price after trigger.

### Motivation

Use STOP_LIMIT when:

- You need trigger automation but still require explicit price protection.
- You can tolerate non-fill risk after trigger.
- You want to avoid executing through temporary price spikes/gaps.

- Provides price protection after trigger, but may not fill if the market moves past the limit
- Requires both `STOP=` (trigger) and `PRICE=` (limit after trigger)


### Gateway Syntax

```
NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP_LIMIT|QTY=100|STOP=148.00|PRICE=147.50
```

**Educational note**: The gap between stop price and limit price is the "insurance premium"
against market impact. If the market falls through 147.50 before the order fills, it remains
unexecuted as a resting limit.

---

## 5. FOK (Fill-or-Kill)

[Back to Contents](#contents)

Must be **entirely filled immediately** or the whole order is cancelled.

### Background

FOK comes from block-trading workflows where partial execution can break a
strategy's economics. It is common in institutional routing logic and
cross-venue execution algos that need all-or-nothing completion.

### Motivation

Use FOK when:

- Partial fills are unacceptable.
- You need immediate certainty of complete size.
- The order is one leg of a tightly coupled strategy and partial execution introduces exposure.

- Checks total available quantity at the given price before executing
- If `available_qty < order_qty` → rejected entirely (no partial fills ever)
- If sufficient → executes in full immediately


### Gateway Syntax

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=FOK|QTY=100|PRICE=150.00
```

**Educational note**: FOK is used when partial fills are unacceptable — e.g. algorithmic
strategies needing an exact block to execute a multi-leg trade atomically.

---

## 6. ICEBERG

[Back to Contents](#contents)

A large LIMIT order that hides most of its size, showing only a `visible_qty` "peak"
at any one time.

### Background

ICEBERG orders were designed for institutional execution where displaying full
size can move the market against the trader. The displayed "tip" reveals only
a small slice while preserving the same total parent quantity.

### Motivation

Use ICEBERG when:

- You need to execute large notional size with reduced information leakage.
- You want to rest passively without broadcasting your full intent.
- You accept slower completion in exchange for lower signaling risk.

- Only `VISIBLE=` quantity is published to the order book
- Once the visible peak is fully consumed, a **new peak** is replenished from the hidden quantity
- Each new peak gets a **new timestamp** → goes to the back of the queue at
  that price level (because the book uses price-time priority: among orders at
  the same price, the oldest order gets filled first — a fresh timestamp means
  this peak waits behind all other orders already resting at that price)
- The total hidden size is **never visible** to other market participants


### Gateway Syntax

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=ICEBERG|QTY=1000|PRICE=150.00|VISIBLE=100
```

**Educational note**: This is how large institutional orders are worked into the market
without telegraphing their full size. Watch the book viewer as the iceberg refills — the
qty at that price level resets to 100 after each 100-lot fill, but the order ID changes
(new timestamp = new queue position).

---

## 7. COMBO

[Back to Contents](#contents)

A **multi-leg order** that bundles two or more child orders across different
symbols into a single atomic instruction. The child orders are linked: they
are submitted, tracked, and cancelled as a group.

### Background

COMBO orders are the exchange-native answer to legging risk in spread,
pairs, and relative-value strategies. Instead of managing legs manually,
the matching system keeps lifecycle and cancellation coupling explicit.

### Motivation

Use COMBO when:

- Strategy PnL depends on a relationship between instruments, not one symbol.
- You want coordinated child lifecycle and automatic cascade-cancel.
- You need operational safety against partial strategy completion.

- Each leg is a standard LIMIT order posted to its respective symbol book
- All legs are tracked together under a parent combo ID
- If any leg is cancelled or expires, all remaining legs are automatically
  **cascade-cancelled** (unfilled quantities only — fills already executed
  are not reversed)
- The combo is considered MATCHED only when **all** legs are fully filled


**Educational note**: COMBO is not a synthetic construct built on top of regular orders — it is a first-class order type with native engine support for multi-leg lifecycle management and cascade cancellation.

### Gateway Syntax

```
NEW|TYPE=COMBO|COMBO_ID=PAIR-001|COMBO_TYPE=AON|TIF=GTC|LEG_COUNT=2|LEG0.SYM=MSFT|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=415.00|LEG1.SYM=AAPL|LEG1.SIDE=SELL|LEG1.QTY=100|LEG1.PRICE=210.00
```

| Field | Meaning |
|-------|---------|
| `TYPE=COMBO` | Identifies this as a multi-leg order |
| `COMBO_ID` | Your human-readable tracking label |
| `COMBO_TYPE=AON` | All-or-none: combo succeeds only when every leg fills completely |
| `LEG_COUNT` | Number of legs (2–10) |
| `LEG<i>.SYM` | Symbol for leg *i* |
| `LEG<i>.SIDE` | BUY or SELL for leg *i* |
| `LEG<i>.QTY` | Quantity for leg *i* |
| `LEG<i>.PRICE` | Limit price for leg *i* |

**Educational note**: The `COMBO_TYPE` field is reserved for future expansion. Currently only `AON` (All-Or-Nothing) is supported, meaning the combo is successful only if every leg fills in full. In the future, we may add `ANY` (combo succeeds if at least one leg fills) or `MIN` (combo succeeds if a minimum number of legs fill).

### Combo lifecycle

```
PENDING ──────► PARTIALLY_MATCHED ──────► MATCHED
                      │
                      ▼
                    FAILED  (cascade-cancel triggered)
```

### Cancelling a combo

```
CANCEL|COMBO_ID=PAIR-001
```

Cancels all unfilled legs. Fills already executed are irrevocable.

**Educational note**: Combos enable relative-value strategies (pairs trades,
hedged entries, statistical arbitrage) where the profit depends on the
*relationship* between instruments, not on any single instrument's direction.
Without combos, submitting legs separately exposes you to **leg risk** — one
side fills while the other does not, leaving you with unintended directional
exposure. See the [Combo Orders](05-combos.md) page for full details, examples,
and the implied orders mechanism.

---

## 8. Time-in-Force (TIF)

[Back to Contents](#contents)

**TIF** (Time-in-Force) is not an order type; it is a set of instructions that specify how long an order remains active before it is executed or expires.

Time-in-force controls how long an order remains active before the engine
automatically expires or cancels it.

### Background

TIF instructions standardize order lifetime semantics across venues. They let
participants express not only *how* to trade (order type) but *for how long*
that instruction is valid under changing session states.

### Motivation

Use TIF to align execution intent with horizon:

- `DAY` for session-local participation.
- `GTC` for persistence across restarts/sessions.
- `ATO`/`ATC` for auction-specific participation windows.
- `FOK` when immediacy and completeness must be coupled.

| Value | Meaning |
|-------|----------|
| `DAY` (default) | Valid for the current trading session only. Cancelled/expired at engine shutdown or when the session transitions to CLOSED. |
| `GTC` | Good-Till-Cancelled. Persisted to `data/gtc_orders.json` at shutdown and reloaded next session. Survives across trading days. |
| `ATO` | At-The-Open. Only accepted during the `OPENING_AUCTION` phase. Automatically expired when the opening auction ends (transition to CONTINUOUS). |
| `ATC` | At-The-Close. Only accepted during the `CLOSING_AUCTION` phase. Automatically expired when the closing auction ends (transition to CLOSED). |
| `FOK` | Fill-Or-Kill (also an order type). Must fill entirely and immediately, or is rejected. |

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00|TIF=GTC
```

---

## 9. Stop Trigger Logic

[Back to Contents](#contents)

Stop-family orders (`STOP`, `STOP_LIMIT`, and `TRAILING_STOP`) are
**event-driven**: they do not trigger from top-of-book quotes, midpoint,
or best bid/ask changes. They trigger from the symbol's **last executed
trade price**.

### Why last trade price?

Using last trade price aligns trigger events with actual executions, which
reduces false triggers that can occur from ephemeral quote flickers. It also
makes replay and audit deterministic: every trigger can be traced to a trade
event in the execution stream.

### Trigger Conditions

Stops are evaluated after every trade event:

| Order Side | Trigger Condition |
|------------|------------------|
| BUY STOP   | `last_trade_price >= stop_price` |
| SELL STOP  | `last_trade_price <= stop_price` |

**Why does a BUY STOP trigger at a price *higher* than the stop?**

It seems backwards — normally you want to buy *low*. The key is that a BUY
STOP is not a value-buying tool; it is a *momentum confirmation* tool. The
stop price acts as a breakout threshold: the trader is saying "I don't want
to buy unless the market proves it can trade at or above this level."

Common use cases:

- **Breakout entry**: A stock has been consolidating below $150 (resistance).
  A trader places a BUY STOP at $150.01. If the price breaks through and
  prints at or above that level, it signals that sellers are exhausted and
  momentum is upward — the trader enters only after that confirmation.
- **Short-squeeze protection**: A trader is short and places a BUY STOP above
  the current price as an automated exit. If the market rises against their
  position past the stop, the buy triggers to close (cover) the short before
  losses grow larger.
- **Trend-following systems**: Algorithms that "buy strength" deliberately
  wait for a new high to be set before entering, treating the breakout level
  as the entry signal rather than a price they'd prefer to avoid.

The counterpart, SELL STOP (`last_trade_price <= stop_price`), is the more
intuitive stop-loss: trigger a sell when the market falls to or through a
floor price. BUY STOP is simply the mirror image applied to the upside.

### Lifecycle After Trigger

1. The stop leaves its dormant container (`_buy_stops`, `_sell_stops`, or
   `_trailing_stops`).
2. The engine converts it:
   - `STOP` -> `MARKET`
   - `STOP_LIMIT` -> `LIMIT` (retains the original `PRICE=`)
   - `TRAILING_STOP` -> `MARKET` (using current ratcheted `stop_price` for trigger only)
3. The converted order is re-processed through normal matching logic.
4. It receives a fresh queue timestamp at conversion time.

This means a triggered stop behaves exactly like a newly submitted active
order of its converted type.

### Session-Phase Interaction

- In non-matching phases, stops can be accepted and stored.
- Trigger checks are tied to trade events, so without trades there are no
  triggers.
- On phase transitions that produce uncross trades, stop evaluations run after
  those trade events and can create cascades.

### Trigger Cascades

A single aggressive trade can trigger multiple dormant stops:

1. Trade updates `last_trade_price`.
2. One or more stops become trigger-eligible.
3. Converted orders are injected and may execute immediately.
4. Those executions update `last_trade_price` again.
5. Additional stops may now trigger.

This cascade is expected behavior in volatile moves and is why stop-heavy
books can accelerate directional momentum.


### Worked Scenarios

#### Scenario A — SELL STOP trigger and slippage

Gateway message:

```
NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP|QTY=100|STOP=148.00
```

- Dormant order: `SELL STOP qty=100 stop=148`
- Last trade before event: `149.50`
- Next execution prints at `147.20`.

Trigger check: `147.20 <= 148` -> true, so order converts to MARKET SELL.
Fill can occur below 148 depending on available bids (slippage).

#### Scenario B — STOP_LIMIT trigger without fill

Gateway message:

```
NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP_LIMIT|QTY=100|STOP=148.00|PRICE=147.50
```

- Dormant order: `SELL STOP_LIMIT qty=100 stop=148 limit=147.50`
- Trade prints at `147.80` (triggered)
- Best bid drops to `146.90` before order can match.

Order converts to LIMIT SELL at 147.50 and rests unfilled until a buyer
meets that price.

#### Scenario C — Multiple stops fire on one print

Gateway messages (three separate dormant orders):

```
NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP|QTY=100|STOP=149.00
NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP|QTY=100|STOP=148.00
NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP|QTY=100|STOP=147.00
```

Dormant sell stops: 149, 148, 147.

If a trade prints at 147.00, all three satisfy `last_trade_price <= stop_price`.
All convert in sequence and are processed as active orders.

### Practical Notes

- Trigger is binary; `stop_price` is not an execution guarantee.
- STOP prioritizes fill certainty over price certainty.
- STOP_LIMIT prioritizes price control over fill certainty.
- TRAILING_STOP adds adaptive trigger movement but still converts to MARKET on trigger.

---

## 10. IOC (Immediate-Or-Cancel)

[Back to Contents](#contents)

### Background

Immediate-Or-Cancel (IOC) is a time-in-force discipline that has been a
fixture of electronic trading since the early days of ECNs (Electronic
Communication Networks) in the 1990s. It was developed to give traders a
way to "take what is available right now" without inadvertently posting
a resting order that could fill much later at a stale price.

The Chicago Mercantile Exchange (CME), NYSE, and most modern exchanges
support IOC natively. It is especially important for algorithmic and
high-frequency traders who cannot afford the risk of an old order sitting
on the book after a quote has moved.

### Motivation

Use IOC when:

- You need to sweep available liquidity at or better than your limit price,
  but you are not willing to wait for the market to come to you.
- You want to avoid being "on the hook" for shares if the price moves
  away between submission and fill.
- You are executing a leg of a larger strategy and a partial fill is
  acceptable, but a resting order is not.

**IOC vs LIMIT**: A `LIMIT` order rests on the book if it does not fill
immediately. An `IOC` order never rests — the unfilled portion is
cancelled before control returns to the caller.

**IOC vs FOK**: `FOK` (Fill-Or-Kill) requires the *entire* quantity to fill
immediately or it is rejected. `IOC` accepts partial fills, cancelling only
what could not be filled.

### How It Works

1. The engine receives the `IOC` order.
2. If the session is in a non-matching phase (auction), the order is
   **rejected** immediately — IOC cannot rest on the book.
3. During continuous trading, the engine sweeps the opposite side of the
   book, filling against resting orders at progressively worse prices up to
   the IOC limit price.
4. After the sweep completes (or if no liquidity was available), any
   remaining quantity is **cancelled** and a `CANCELLED` event is published.
5. The IOC order is never added to the resting order book.

**Educational note**: IOC is a pure liquidity-taking instruction. It is designed to consume whatever is available at or better than the limit price, but it does not wait for liquidity to appear. If the book is empty or all orders are above (for BUY) or below (for SELL) the limit, the IOC will simply cancel itself without any fills.

### Examples

#### Example 1 — Full fill

Gateway message:

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=IOC|QTY=10|PRICE=100.00
```

Book state (asks):

```
Ask  100.00  qty=10
Ask  101.00  qty=10
```

Result:
- Trade: 10 × 100.00
- IOC order: FILLED
- No resting order added to the book

#### Example 2 — Partial fill, remainder cancelled

Gateway message:

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=IOC|QTY=10|PRICE=100.00
```

Book state (asks):

```
Ask  100.00  qty=5   ← only 5 available at limit price
Ask  101.00  qty=10  ← above IOC limit, not swept
```

Result:
- Trade: 5 × 100.00
- IOC order: remaining 5 units **CANCELLED**
- 5 asks at 101.00 remain on the book

#### Example 3 — No fill, entire order cancelled

Gateway message:

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=IOC|QTY=10|PRICE=100.00
```

Book state (asks): empty (or all asks above limit)

Result:
- No trade
- IOC order: all 10 units **CANCELLED** immediately

#### Example 4 — Multi-level sweep

Gateway message:

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=IOC|QTY=9|PRICE=101.00
```

Book state (asks):

```
Ask   99.00  qty=3
Ask  100.00  qty=3
Ask  101.00  qty=3
Ask  102.00  qty=3
```

Result:
- Trade: 3 × 99.00, 3 × 100.00, 3 × 101.00
- IOC order: FILLED
- 3 asks at 102.00 remain untouched

### Gateway Syntax

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=IOC|QTY=100|PRICE=150.00
```

`IOC` ignores the `TIF=` field — it is always immediate-or-cancel by
definition. The engine will reject an IOC during auction phases.

### Edge Cases and Gotchas

| Scenario | Behaviour |
|----------|-----------|
| Submitted during opening/closing auction | **REJECTED** — IOC cannot rest |
| Self-match (same gateway on both sides) | SMP rule applies to the IOC fill attempt |
| Price limit not specified | Not supported — IOC requires a `PRICE=` |
| IOC against FOK resting order | Normal interaction; FOK would already have been rejected if it had no fill |

---

## 11. TRAILING_STOP

[Back to Contents](#contents)

### Background

A trailing stop is a stop order whose trigger price automatically moves
in the trader's favour as the market moves favourably — but *never*
moves against the trader. It was popularised by retail brokerages in
the 1990s and 2000s as a way to "let profits run while cutting losses".

Modern exchange systems (CME, NASDAQ, CBOE) all support native trailing
stops. They are especially useful for momentum strategies and position
management when a trader wants to stay long/short for as long as the
trend continues, but exit automatically once a reversal of a given
magnitude occurs.

### Motivation

Use a trailing stop when:

- You want to protect a profit without capping the upside. A regular stop
  is static — once set at, say, $98, it stays at $98 even if the stock
  rallies to $130. A trailing stop at $2 behind would move up to $128
  automatically.
- You are managing a position and cannot monitor it continuously.
- You want a systematic, emotion-free exit strategy.

**Trailing stop vs regular STOP**: A regular stop has a fixed trigger
price. A trailing stop has a *dynamic* trigger price that ratchets in one
direction (up for SELL, down for BUY) with the market.

### Gateway Syntax

```
NEW|SYM=AAPL|SIDE=SELL|TYPE=TRAILING_STOP|QTY=100|TRAIL=2.00|STOP=98.00
```


### How It Works

The trailing stop maintains two values:

- **`trail_offset`** (`TRAIL=`): a fixed price distance from the market.
- **`stop_price`**: the current trigger level, updated after each trade.

#### SELL trailing stop (protecting a long position)

- Goal: trigger only if the price *falls* by `trail_offset` from its peak.
- After each trade at price *P*:
  - New candidate stop: $P - \text{trail\_offset}$
  - **stop\_price is updated only if the candidate is higher** (ratchet upward)
  - Trigger condition: $P \leq \text{stop\_price}$

#### BUY trailing stop (protecting a short position)

- Goal: trigger only if the price *rises* by `trail_offset` from its trough.
- After each trade at price *P*:
  - New candidate stop: $P + \text{trail\_offset}$
  - **stop\_price is updated only if the candidate is lower** (ratchet downward)
  - Trigger condition: $P \geq \text{stop\_price}$

#### On trigger

The trailing stop is removed from the pending list and converted to a
**MARKET** order, which is then processed immediately in the same trade cycle.

#### Initial stop price

If `STOP=` is supplied, that is the initial `stop_price`. If omitted, the
engine computes the initial stop from `last_trade_price ± trail_offset`.
If there is no last trade and no explicit `STOP=`, the order is **rejected**.

### Examples

#### Example 1 — SELL trailing stop: price rallies then drops

Gateway message:

```
NEW|SYM=AAPL|SIDE=SELL|TYPE=TRAILING_STOP|QTY=100|TRAIL=2.00|STOP=98.00
```

Setup: last trade price = 100. SELL trailing stop: `trail=2`, `stop=98`.

```
Trade at 105  →  stop ratchets up  →  stop = max(98, 105−2) = 103
Trade at 110  →  stop ratchets up  →  stop = max(103, 110−2) = 108
Trade at 102  →  102 ≤ 108?  YES  →  TRIGGERED → MARKET SELL
```


The trailing stop locked in a floor of 108 as the stock rallied to 110.
When the stock dropped back to 102, the stop fired.

#### Example 2 — SELL trailing stop: stop never moves down

Gateway message:

```
NEW|SYM=AAPL|SIDE=SELL|TYPE=TRAILING_STOP|QTY=100|TRAIL=2.00|STOP=98.00
```

```
stop = 98, trail = 2, last_trade = 100

Trade at 106  →  stop = max(98, 104) = 104
Trade at 95   →  95 ≤ 104?  YES  →  TRIGGERED
```

Note that the trade at 95 did *not* move the stop down to 93 first.
The trigger check happens in the same sweep as the ratchet update,
but the trigger condition is evaluated against the *already-updated* stop.
In practice a stop at 104 triggered by a trade at 95 means the order
fires well below its stop — this is called **slippage on the stop trigger**.

#### Example 3 — BUY trailing stop: price falls then rises

Gateway message:

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=TRAILING_STOP|QTY=100|TRAIL=3.00|STOP=53.00
```

Setup: last trade = 50. BUY trailing stop: `trail=3`, `stop=53`.

```
Trade at 45   →  stop ratchets down  →  stop = min(53, 45+3) = 48
Trade at 40   →  stop ratchets down  →  stop = min(48, 40+3) = 43
Trade at 44   →  44 ≥ 43?  YES  →  TRIGGERED → MARKET BUY
```

The stop followed the price down from 53 to 43. When the price started
recovering and crossed 43, the buy was triggered.

#### Example 4 — Cancelling a trailing stop before trigger

```
CANCEL|ID=<order_id>
```

A trailing stop can be cancelled at any time before trigger using its
`order_id`. The engine marks the order CANCELLED, publishes an
`order.cancelled` event, and removes it from the pending trailing stop
list on the next trade cycle (lazy deletion).

### Gateway Syntax

```
# With explicit initial stop
NEW|SYM=AAPL|SIDE=SELL|TYPE=TRAILING_STOP|QTY=100|TRAIL=2.00|STOP=148.00

# Without explicit stop — engine computes from last trade price
NEW|SYM=AAPL|SIDE=SELL|TYPE=TRAILING_STOP|QTY=100|TRAIL=2.00
```

### Edge Cases and Gotchas

| Scenario | Behaviour |
|----------|-----------|
| No `TRAIL=` supplied | **REJECTED** |
| No `STOP=` and no prior trade | **REJECTED** (engine cannot compute initial stop) |
| Submitted during auction phase | **Accepted** — rests until the auction uncroses, then evaluated on next trade |
| Large `trail_offset` relative to price | Stop may never trigger if the market doesn't move that far |
| Triggered during uncross | The resulting MARKET order participates in the uncross matching round |
| Multiple trailing stops on the same symbol | All are evaluated after every trade in O(t) time (t = number of trailing stops) |

---

## 12. Order Amendment (AMEND)

[Back to Contents](#contents)

### Background

Order amendment (also called **modify** or **cancel/replace** in FIX protocol
terminology) allows a trader to change the price or quantity of a resting
order without explicitly cancelling and re-submitting it. This is a
fundamental operation on every real exchange — CME, NYSE, Eurex, LSE, and
NASDAQ all support in-place amendment.

In FIX Protocol, this is `MsgType=G` (Order Cancel/Replace Request). The key
semantic distinction from a plain cancel+new is that an amendment **preserves
the order ID** and, under certain conditions, **preserves time priority**.

### Priority Rules

EduMatcher implements the same priority rules used by most lit exchanges:

| Amendment Type | Priority |
|----------------|----------|
| Quantity decrease only (price unchanged) | **Preserved** — order keeps its original timestamp |
| Price change (any direction) | **Lost** — order moves to the back of the queue at the new price |
| Quantity increase (price unchanged) | **Lost** — order moves to the back of the queue |
| Price change + quantity change | **Lost** |

**Rationale**: A quantity decrease cannot disadvantage other participants at
the same price level (there is less competition for incoming aggressor flow).
Any other change either alters the priority ranking (price change) or grants
the order more opportunity to fill without having competed for that position
(quantity increase).

### AMEND vs. Cancel+New

| Aspect | AMEND | Cancel + New |
|--------|-------|--------------|
| Order ID | Preserved | New ID assigned |
| Message count | 1 inbound + 1 response | 2 inbound + 2 responses |
| Priority on qty decrease | Preserved | **Lost** (new order gets current timestamp) |
| Atomicity | Guaranteed — no gap where the order is absent from the book | Non-atomic — brief window with no resting order |
| Fill risk during gap | None | Another order could fill the opposite side during the gap |
| Filled quantity tracking | Continuous — partial fills before amendment are preserved | Resets to zero on the new order |
| Gateway state | Single cache entry updated | Old entry cancelled + new entry created |

**When to use Cancel+New instead**: If you need to change the order's side,
symbol, order type, or TIF, you must cancel and resubmit — amendment only
modifies price and/or quantity of an existing resting order.

### Supported Order Types

Only **LIMIT** and **ICEBERG** orders can be amended. Other order types either
cannot rest on the book (MARKET, IOC, FOK) or have trigger semantics that
make in-place amendment ambiguous (STOP, STOP_LIMIT, TRAILING_STOP).

### Gateway Syntax

```
# Change price only (priority lost)
AMEND|ID=<order-id>|PRICE=151.00

# Decrease quantity only (priority preserved)
AMEND|ID=<order-id>|QTY=50

# Change both price and quantity (priority lost)
AMEND|ID=<order-id>|PRICE=151.00|QTY=200
```

### Examples

```bash
# 1. Place a resting buy limit
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00
# → ACK: order_id = abc123...

# 2. Market moves — improve price (priority lost, back of queue at 151)
AMEND|ID=abc123...|PRICE=151.00
# → AMENDED: price=151.0 qty=100 remaining=100 (priority reset)

# 3. Reduce size to manage risk (priority preserved at 151)
AMEND|ID=abc123...|QTY=80
# → AMENDED: price=151.0 qty=80 remaining=80

# 4. After a partial fill of 30, reduce remaining exposure
#    (original qty was 80, filled 30, so remaining = 50)
AMEND|ID=abc123...|QTY=60
# → AMENDED: price=151.0 qty=60 remaining=30
#    Note: new_qty (60) - filled (30) = 30 remaining
```

### Amendment Events

| Topic | Fired When |
|-------|------------|
| `order.amended.{GW}` | Amendment accepted; contains new `price`, `qty`, `remaining_qty`, `priority_reset` |
| `order.ack.{GW}` (`accepted=false`) | Amendment rejected; contains `reason` |

### Edge Cases and Gotchas

| Scenario | Behaviour |
|----------|-----------|
| Order not found (wrong ID) | **REJECTED** — "Order not found" |
| Order already filled | **REJECTED** — "Cannot amend FILLED order" |
| Order already cancelled | **REJECTED** — "Cannot amend CANCELLED order" |
| MARKET / STOP / FOK order | **REJECTED** — "Cannot amend MARKET orders" |
| New QTY ≤ already filled qty | **REJECTED** — "New quantity must exceed already-filled quantity" |
| New QTY = 0 or negative | **REJECTED** — "Quantity must be positive" |
| New PRICE ≤ 0 | **REJECTED** — "Price must be positive" |
| Neither PRICE nor QTY supplied | **REJECTED** — "Amend requires at least PRICE or QTY" |
| Iceberg order amended | Supported — displayed_qty is recalculated from `visible_qty` |
| Combo child order amended | Allowed — the child is a normal resting order |
| OCO leg amended | Allowed — does not affect the OCO linkage |
| Amend during auction phase | Allowed — the resting order's price/qty is updated in the book |

---

## 13. OCO (One-Cancels-Other)

[Back to Contents](#contents)

### Background

One-Cancels-Other (OCO) is a paired order construct in which two orders
are linked such that when one reaches a terminal state (filled, cancelled,
or rejected), the other is automatically cancelled. OCO is a core primitive
in institutional trading and has been standardised by the FIX Protocol
(tag 1OC) and supported by virtually every major exchange and brokerage
since the early 2000s.

The classic use case is a **bracket order**: a trader enters a long position
and simultaneously places a take-profit limit above the entry price and a
stop-loss below. Once one of them fills, the other is automatically cancelled,
preventing the trader from accidentally doubling their position.

### Motivation

Use OCO when:

- You want to protect a position with *either* a profit target *or* a
  stop-loss — whichever happens first — without needing to manually cancel
  the other leg.
- You want to implement a "bracket" strategy: entry fills, then
  simultaneously a take-profit limit and a stop-loss stop are live.
- You need the guarantee that you cannot be filled on *both* legs.

**OCO vs two independent orders**: Without OCO, if your take-profit fills
first and you forget to cancel the stop, the stop might trigger later and
re-open an unintended position. OCO prevents this by coupling the two orders
at the engine level.

**OCO vs COMBO**: A COMBO (All-Or-Nothing) executes multiple legs
simultaneously on a single triggering event. An OCO has two legs that
compete — only one can survive.

**Educational note**: OCO is a powerful risk management tool that automates the lifecycle coupling of two related orders. It is essential for any strategy that relies on mutually exclusive outcomes, such as profit-taking vs stop-loss scenarios.


### How It Works

1. The gateway sends an OCO request with two **leg definitions** (side,
   type, price/stop) plus a shared quantity and `oco_id`.
2. The engine validates both legs (gateway auth, symbol config, price
   fields), then creates two independent `Order` objects, each tagged
   with `oco_group_id`.
3. Both orders are posted to the relevant order book and given `NEW` status.
4. The engine publishes an `oco.ack.{GW}` message containing both
   `order_id_1` and `order_id_2`.
5. When either order transitions to a terminal state (FILLED, CANCELLED,
   REJECTED), the engine calls `_check_oco_after_event()`:
   - Looks up the sibling order ID.
   - Sends a cancel request to the book for the sibling.
   - Publishes `oco.cancelled.{GW}` with `cancelled_order_id` (the sibling)
     and `reason` explaining why.
   - Removes the OCO group from the engine's tracking dict.
6. The OCO group can also be cancelled explicitly via `CANCEL|OCO_ID=<id>`,
   which cancels both legs immediately.

### Examples

#### Example 1 — Classic take-profit + stop-loss bracket (SELL side)

You are long 100 AAPL at $150. You want to:
- Sell at $160 (take profit) if the stock rallies, **or**
- Sell at $140 (stop-loss) if the stock drops.

```
NEW|TYPE=OCO|OCO_ID=BRACKET1|SYM=AAPL|QTY=100|TIF=GTC|
    LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|LEG1_PRICE=160|
    LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=140
```

**Scenario A**: Stock rallies to $162. A buyer crosses the LIMIT leg at $160.

```
Order book receives BUY at 162
LIMIT SELL at 160 → FILLED
Engine: OCO group BRACKET1 — sibling stop cancelled
oco.cancelled.TRADER01 published (cancelled_order_id = stop order)
```

**Scenario B**: Stock drops to $138. A seller triggers the STOP.

```
Trade at 138 → STOP SELL trigger → converts to MARKET SELL → FILLED
Engine: OCO group BRACKET1 — sibling limit cancelled
oco.cancelled.TRADER01 published (cancelled_order_id = limit order)
```

#### Example 2 — Two limit orders (buy-side bracket)

You are short 100 AAPL at $150. Cover at $140 (profit) or at $160 (stop).

```
NEW|TYPE=OCO|OCO_ID=SHORT_BRACKET|SYM=AAPL|QTY=100|TIF=GTC|
    LEG1_SIDE=BUY|LEG1_TYPE=LIMIT|LEG1_PRICE=140|
    LEG2_SIDE=BUY|LEG2_TYPE=LIMIT|LEG2_PRICE=160
```

Whichever price is touched first fills; the other is auto-cancelled.

#### Example 3 — Explicit cancellation of the entire OCO pair

Before either leg fills:

```
CANCEL|OCO_ID=BRACKET1
```

Both legs are cancelled atomically. The engine publishes `order.cancelled`
for each leg and removes the OCO group.

#### Example 4 — One leg rejects, the other is cancelled

Gateway message (leg 1 has an invalid price):

```
NEW|TYPE=OCO|OCO_ID=BAD1|SYM=AAPL|QTY=50|TIF=GTC|LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|LEG1_PRICE=INVALID|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=145
```

If leg 1 is rejected (e.g., invalid price format caught at engine level),
the engine also cancels leg 2 and publishes `oco.cancelled.{GW}` to
notify the gateway.

### Gateway Syntax

```
# Full OCO request syntax
NEW|TYPE=OCO|OCO_ID=<label>|SYM=<symbol>|QTY=<qty>|TIF=<tif>
   |LEG1_SIDE=<BUY|SELL>|LEG1_TYPE=<order_type>|LEG1_PRICE=<price>
   |LEG2_SIDE=<BUY|SELL>|LEG2_TYPE=<order_type>|LEG2_STOP=<stop_price>

# LIMIT + STOP (take-profit + stop-loss)
NEW|TYPE=OCO|OCO_ID=TPS|SYM=AAPL|QTY=50|TIF=GTC|LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|LEG1_PRICE=155|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=145

# Two LIMITs (buy bracket)
NEW|TYPE=OCO|OCO_ID=BB|SYM=AAPL|QTY=50|TIF=GTC|LEG1_SIDE=BUY|LEG1_TYPE=LIMIT|LEG1_PRICE=140|LEG2_SIDE=BUY|LEG2_TYPE=LIMIT|LEG2_PRICE=160

# Cancel the entire OCO pair
CANCEL|OCO_ID=TPS
```

### OCO Events

| Topic | Fired When |
|-------|------------|
| `oco.ack.{GW}` | OCO pair accepted; contains `order_id_1`, `order_id_2` |
| `oco.ack.{GW}` (`accepted=false`) | OCO pair rejected; contains `reason` |
| `oco.cancelled.{GW}` | Sibling auto-cancelled after the other leg settled |
| `order.fill.{GW}` | Each leg is an independent order; fill events are per-leg |
| `order.cancelled.{GW}` | Published for each leg on explicit CANCEL|OCO_ID= |

### Edge Cases and Gotchas

| Scenario | Behaviour |
|----------|-----------|
| OCO_ID already in use | **REJECTED** (not implemented as replacement) |
| Unknown symbol or gateway | **REJECTED** with `oco.ack accepted=false` |
| LIMIT leg missing `LEG_PRICE=` | **REJECTED** |
| STOP leg missing `LEG_STOP=` | **REJECTED** |
| Partial fill of one leg | Does NOT cancel the sibling — only a terminal state (FILLED, CANCELLED, REJECTED) does |
| Both legs fill simultaneously | First fill to be processed cancels the second; race resolved by event order |
| GTC OCO across sessions | Both legs persist with their TIF; if GTC they survive session reset |

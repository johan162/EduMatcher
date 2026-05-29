# EduMatcher — Migration Plan v4: Integer Nanosecond Timestamps and Tick-Based Prices

> v4 is a **strict superset** of v1 and v3.
> It preserves all detailed content from v1 and includes a verbatim v3 addendum at the end.

> **Audience:** A developer who knows Python well but may be new to financial
> systems. This document explains every trading term before using it. If you
> already know exchange mechanics, skip to Section 3.
>
> **No backward compatibility.** This plan assumes all persisted data files
> (`gtc_orders.json`, `book_stats.json`, `gtc_combos.json`) are deleted before
> the migrated engine starts. The old float-based JSON format is gone. Every
> `from_dict()` method assumes the new format exclusively.
>
> **Reading order:** Read the *Finance Concepts Primer* and the two *Why* sections
> first. The motivation for each change makes the implementation details much easier
> to follow.

---

## Finance Concepts Primer

This section defines every trading and financial term used in this document. Read it
before the technical sections — many of the design decisions only make sense once
you understand what the system is modelling.

### What is a price tick?

In financial markets, instruments (stocks, currencies, futures contracts) cannot
trade at arbitrary prices. They move in minimum steps called **ticks**. For US
equities, the minimum price increment is $0.01 — a stock priced at $150.30 can
next trade at $150.29 or $150.31, but not at $150.295.

The size of this step is the **tick size**. Different markets have different tick
sizes:
- US equities: $0.01 per tick
- E-mini S&P 500 futures: $0.25 per tick
- EUR/USD currency pair: $0.00001 per tick (five decimal places)

EduMatcher uses `tick_decimals` to encode tick size: `tick_decimals = 2` means
1 tick = $0.01; `tick_decimals = 4` means 1 tick = $0.0001.

### What is price-time priority?

When two buyers both want to buy at the same price, the exchange must decide which
one gets filled first. The rule used by almost all exchanges is
**price-time priority**:

1. **Price first:** better prices execute before worse prices. A buyer offering
   $151 gets filled before a buyer offering $150.
2. **Time second:** at the same price, the order that arrived first gets filled
   first — like a queue at a shop counter.

In EduMatcher, each resting order's position in this priority system is encoded as
a tuple: `(-price_ticks, timestamp_ns)`. The negative price means highest price
sorts first (buy side), and the nanosecond timestamp ensures earlier orders sort
before later ones at the same price.

### What is a resting order vs an aggressive order?

A **resting order** (also called a passive order) is one that has been placed in the
order book and is waiting for a counterparty. It does not execute immediately.

An **aggressive order** (also called a taker order) is one that comes in and
immediately matches against resting orders. When you send a buy order at a price
above the cheapest existing sell offer, your order is aggressive — it sweeps into
the resting orders and causes trades to happen.

### What is a stop order and a trailing stop?

A **stop order** is a conditional order: it only becomes active (and enters the
book) when the market price reaches a specified **stop price**. Until then, it sits
dormant.

- A **sell stop** at $145 triggers when the market price falls to $145. It is used
  to automatically cut losses on a long position ("stop-loss").
- A **buy stop** at $155 triggers when the market price rises to $155. It is used
  to enter a position on upward momentum.

A **trailing stop** is a stop order whose stop price moves automatically as the
market moves in a favourable direction. A sell trailing stop with a $2 offset starts
at `current_price - $2`. If the price rises from $150 to $160, the stop rises from
$148 to $158. If the price then falls, the stop holds at $158 and eventually fires.

The **trail offset** is the fixed distance between the market price and the stop.
The **ratchet** is the mechanism that moves the stop upward (for a sell) or
downward (for a buy) as price moves in your favour — but never in the other
direction.

### What is an auction and an equilibrium price?

At the start and end of the trading day, exchanges run a **call auction** (also
called a fixing or uncross). Rather than matching orders one at a time as they
arrive, the auction collects all orders during a period and then executes them all
at a single **equilibrium price** — the price that allows the maximum number of
shares to trade.

The **surplus** is the leftover quantity after the uncross: if 10,000 shares of
buy orders and 8,000 shares of sell orders can trade at the equilibrium price, the
surplus is 2,000 buy shares that could not find a match.

The **imbalance side** identifies which side has the surplus (in the example above,
"BUY").

### What is an OCO order and a combo order?

**OCO (One-Cancels-Other):** Two linked orders where filling one automatically
cancels the other. For example: "Buy at $148 (limit order) OR buy at $150 if the
price breaks upward (stop order), but not both." The first order to fill cancels
its sibling.

**Combo order:** A multi-leg order that ties together orders in different
instruments. For example: "Buy 100 shares of AAPL and simultaneously sell 50 shares
of MSFT as a single transaction." Each component is a **leg**. EduMatcher implements
combo orders with All-Or-None (AON) semantics: all legs must fill or the combo
fails.

### What is a market maker?

A **market maker** is a participant who continuously quotes both a buy price and a
sell price, providing liquidity for other traders. Rather than submitting normal
orders, market makers send **two-sided quotes** — a bid price (they will buy at
this) and an ask price (they will sell at this). The spread between bid and ask is
their profit margin.

**Seed orders** (also called market-maker orders in `engine_config.yaml`) are
initial orders the engine places when it starts up, to ensure the book is not empty
when the first real participants connect.

### What is clearing?

**Clearing** is the process of settling completed trades: confirming that the buyer
receives the shares and the seller receives the money. EduMatcher's clearing process
tracks each participant's **position** (how many shares they currently hold, positive
for long, negative for short) and their **P&L** (profit and loss).

**VWAP (Volume-Weighted Average Price)** is the average price paid for a position,
weighted by the quantity bought at each price. If you buy 100 shares at $150 and
then 50 more at $160, your VWAP is (100×150 + 50×160) / 150 = $153.33.

### What is a GTC order and why does it need special persistence?

**GTC (Good-Till-Cancelled)** orders do not expire at the end of the trading day —
they stay in the book until explicitly cancelled or filled. This means they must
survive engine restarts. EduMatcher saves them to `data/gtc_orders.json` on
shutdown and reloads them on the next startup.

`data/book_stats.json` stores the last traded prices per symbol — needed to
initialise stop-order logic correctly after a restart. `data/gtc_combos.json`
stores multi-leg combo orders that span sessions.

### What is a book snapshot?

A **book snapshot** is a complete picture of the order book at a point in time:
all the resting buy orders grouped by price, all the resting sell orders grouped by
price, and recent trade information. The engine publishes snapshots at most every
500ms per symbol to display processes (viewer, board, ticker) so participants can
see the current market.

### What is the FIX protocol?

**FIX (Financial Information eXchange)** is the industry-standard message protocol
for order submission, used by almost every real exchange and broker. EduMatcher uses
a simplified FIX-inspired text format for its gateway commands:
```
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.50|TIF=GTC
```
The engine also uses this format internally for seeding market-maker orders from
`engine_config.yaml`.

### What is ZMQ and why does it matter here?

**ZeroMQ (ZMQ)** is a messaging library that allows processes to communicate over
sockets. EduMatcher uses it so that the matching engine, gateways, clearing process,
and display tools can all run as separate programs and communicate without tight
coupling. **Subscribers** are processes that receive published messages from the
engine. The engine publishes (broadcasts) on one socket; any number of subscribers
connect to receive the messages they care about.

---

## Table of Contents

0. [Finance Concepts Primer](#finance-concepts-primer)
1. [Why Nanosecond Timestamps?](#1-why-nanosecond-timestamps)
2. [Why Integer Tick Prices?](#2-why-integer-tick-prices)
3. [New Shared Infrastructure — `models/price.py` and `models/clock.py`](#3-new-shared-infrastructure--modelspricepy-and-modelsclockpy)
4. [The Conversion Boundary Rule](#4-the-conversion-boundary-rule)
5. [Design Constraints and Rules](#5-design-constraints-and-rules)
6. [Before You Start — Delete Persisted Data](#6-before-you-start--delete-persisted-data)
7. [Phase Order](#7-phase-order)
8. [Phase 1 — `models/order.py`](#8-phase-1--modelsorderpy)
9. [Phase 2 — `models/trade.py`](#9-phase-2--modelstradepy)
10. [Phase 3 — `models/combo.py`](#10-phase-3--modelscombopy)
11. [Phase 4 — `engine/order_book.py`](#11-phase-4--engineorder_bookpy)
12. [Phase 5 — `engine/auction.py`](#12-phase-5--engineauctionpy)
13. [Phase 6 — `engine/config_loader.py` and `engine_config.yaml`](#13-phase-6--engineconfig_loaderpy-and-engine_configyaml)
14. [Phase 7 — `engine/persistence.py`](#14-phase-7--enginepersistencepy)
15. [Phase 8 — `engine/main.py`](#15-phase-8--enginemainpy)
16. [Phase 9 — `models/message.py`](#16-phase-9--modelsmessagepy)
17. [Phase 10 — `gateway/main.py`](#17-phase-10--gatewaymainpy)
18. [Phase 11 — `clearing/main.py`](#18-phase-11--clearingmainpy)
19. [Phase 12 — `stats/main.py`](#19-phase-12--statsmainpy)
20. [Phase 13 — `viewer/main.py` and `board/main.py`](#20-phase-13--viewermainpy-and-boardmainpy)
21. [Phase 14 — `ticker/main.py`](#21-phase-14--tickermainpy)
22. [Phase 15 — `ai_trader/main.py` and `ai_trader/personality.py`](#22-phase-15--ai_tradermainpy-and-ai_traderpersonalitypy)
23. [Tests](#23-tests)
24. [Complete Change Summary](#24-complete-change-summary)
25. [Implementation Checklist](#25-implementation-checklist)

---

## 1. Why Nanosecond Timestamps?

### Background: what is a Unix timestamp?

Every event in EduMatcher is tagged with a **timestamp** — a number recording when
the event happened. Computers express time as seconds elapsed since the **Unix
epoch**: midnight, 1 January 1970, UTC. A timestamp of `1748000000` means roughly
May 2025. Fractional seconds are used for sub-second precision: `1748000000.123456`
means that same moment plus 123,456 microseconds.

### The Current Problem

EduMatcher uses `time.time()` which returns a Python `float` of seconds since the
Unix epoch:

```python
# models/order.py — current
timestamp: float    # e.g. 1748000000.123456789
```

Python floats use the **IEEE 754** standard (the way most programming languages
store decimal numbers in binary). A 64-bit IEEE 754 float has 52 bits of storage
for the significant digits — giving about 15–16 meaningful decimal digits total.

The problem: at the current Unix epoch (roughly 1.748 × 10⁹ seconds), the integer
part alone uses 10 of those 15 digits. That leaves only 5–6 digits for the
fractional (sub-second) part. Five decimal places in seconds is **10 microseconds**
of precision at best — far less than the one nanosecond we need.

In practical terms, two orders submitted in rapid succession can receive
**identical timestamps** because the float cannot tell them apart:

```python
>>> t1 = time.time()
>>> t2 = time.time()
>>> t1 == t2    # can be True at high submission rates
True
```

When two orders at the same price share a timestamp, the engine cannot determine
which arrived first. Their position in the priority queue becomes arbitrary —
whichever the heap happens to put first from the insertion order, not the true
arrival order. **This violates price-time priority** (the rule that at the same
price, earlier orders execute before later ones — explained in the Finance Concepts
Primer above).

### The Solution

`time.time_ns()` returns an `int` of nanoseconds since epoch:

```python
>>> time.time_ns()
1748000000123456789    # integer, exact, no precision loss
```

An `int` in Python has unlimited precision. Two consecutive calls to
`time.time_ns()` always return distinct values because the integer increments
each nanosecond. At 57,000 orders/second, consecutive orders are roughly 17,500
nanoseconds apart — well above the one-nanosecond resolution of `time.time_ns()`.

**Additional benefit:** comparing two Python integers is ~5–10% faster than
comparing two floats, which directly improves the heap key comparison
`(±price_ticks, timestamp_ns)` that runs on every single match.

> **Important — read Section 5.3 before implementing.** `time.time_ns()` solves the
> precision problem, but it is still not safe to call directly. The system wall clock
> can step *backward* due to NTP adjustments or hypervisor pauses, which would give
> a later order a *smaller* timestamp than an earlier one — silently breaking
> price-time priority. Section 5.3 introduces `monotonic_ns()`, a thin wrapper that
> guarantees strictly increasing values. **Use `monotonic_ns()` everywhere, not
> `time.time_ns()` directly.** Section 1 explains the motivation; Section 5.3 is
> where the actual function to use is defined.

---

## 2. Why Integer Tick Prices?

### The Current Problem

Prices are stored as Python `float`:

```python
price: Optional[float] = None    # e.g. 150.30
```

Because of IEEE 754 binary representation (the same issue as timestamps, but for
prices), most decimal fractions cannot be stored exactly:

```python
>>> 100.1 + 0.2
100.30000000000001    # not 100.30 — a tiny error crept in

>>> 150.30 == 150.10 + 0.20
False                 # should be True
```

This creates three distinct bugs in EduMatcher:

**1. Price comparison errors (matching fails silently)**

The matching engine compares prices to decide whether a resting order and an
incoming order cross (i.e., whether a trade should happen). If a resting sell order
at `$150.30` and an incoming buy order also at `$150.30` produce slightly different
float values due to how they were computed, the comparison `buy.price >= sell.price`
may evaluate to `False` even though mathematically they are equal. The trade never
happens — a silent, incorrect failure.

**2. Dict key collisions (depth is double-counted)**

The order book maintains `_bid_qty: dict[float, int]`, mapping price levels to
total resting quantity. If two orders at "the same" price produce slightly different
floats, they create two separate dictionary entries at nearly-equal keys. The book
now shows two price levels instead of one, silently double-counting the depth. The
viewer displays wrong information; FOK (Fill-Or-Kill) availability checks get wrong
answers.

**3. Trailing stop drift (ratchet accumulates error)**

A trailing stop's trigger price is updated by repeated arithmetic:
`stop_price = last_price - trail_offset`. Each subtraction of floats introduces a
small error. After many price moves (the "ratchet" described in the Finance Concepts
Primer), these errors accumulate. The stop triggers at a slightly wrong price, or
fails to trigger at all.

### The Solution: Tick-Based Integer Prices

Store prices as integer **tick counts** — the number of minimum price increments
from zero. For a symbol with `tick_decimals = 2` (meaning 1 tick = $0.01):

```python
$150.30  →  15030 ticks    # exact integer — no representation error
$150.31  →  15031 ticks
$150.30 + $0.01  →  15030 + 1  =  15031    # exact integer addition
15030 == 15030             # always True, regardless of how 15030 was computed
```

All arithmetic inside the engine uses these integers. Conversion between float
prices (what users type) and integer ticks happens only at the boundaries:
- **Input boundary** (e.g. gateway parsing `PRICE=150.30`): `to_ticks(150.30, "AAPL")` → `15030`
- **Output boundary** (e.g. publishing a fill message): `from_ticks(15030, "AAPL")` → `150.30`

### The Float → Ticks → Float Pipeline

Here is what happens to a price as it travels through the system:

```
User types:   PRICE=150.30
                  │
                  │  Gateway receives float from terminal
                  ▼
Gateway:      payload["price"] = 150.30        (Python float: may be 150.29999999999...)
                  │
                  │  Sent over ZMQ as JSON
                  ▼
Engine input: raw_price = 150.30               (float from JSON)
              ticks = to_ticks(150.30, "AAPL") = 15030    ← round() fixes float error
                  │
                  │  All internal processing uses 15030
                  ▼
OrderBook:    order.price = 15030              (int — exact)
              heap key = (-15030, timestamp_ns) (int — exact comparison)
              _bid_qty[15030] += 100            (int key — no collision)
                  │
                  │  Engine publishes fill event
                  ▼
Engine output: from_ticks(15030, "AAPL") = 150.30    (float for display)
                  │
                  │  Sent over ZMQ as JSON
                  ▼
Gateway displays: "filled at $150.30"
```

The key insight: `round()` at the input boundary absorbs float error exactly once,
at the earliest possible moment. After that, the integer `15030` travels through the
entire engine without any possibility of drift.

### Why the Gateway Cannot Validate Tick Alignment

The gateway sends float prices typed by the user. It does not validate tick
alignment. **Tick alignment is the engine's responsibility**, because:

1. The tick size per symbol lives in `engine_config.yaml`, which the gateway does
   not read.
2. The gateway is a user-facing terminal — its job is to accept and forward commands
   faithfully, not to interpret instrument-specific rules.
3. Adding tick validation to the gateway would require the gateway to maintain its
   own copy of the tick registry — a second source of truth that could diverge.

**Rule:** the gateway sends floats. The engine validates alignment.

### Tick Size Per Symbol

Different instruments have different minimum price increments. `tick_decimals`
encodes this as the number of decimal places in one tick:

| `tick_decimals` | Tick size | Example instrument | Example price | As ticks |
|---|---|---|---|---|
| 0 | $1.00 | Some options (whole-dollar strikes) | $150 | 150 |
| 2 | $0.01 | US equities (default) | $150.30 | 15030 |
| 3 | $0.001 | Some ETFs | $150.305 | 150305 |
| 4 | $0.0001 | Some FX pairs | $1.2345 | 12345 |
| 5 | $0.00001 | EUR/USD retail FX | $1.23456 | 123456 |

EduMatcher uses `tick_decimals = 2` as the default. Any symbol not registered
explicitly falls back to this default.

### Valid vs Invalid Prices: Concrete Examples

For AAPL with `tick_decimals = 2` (tick size = $0.01):

| Submitted price | Valid? | Reason | Ticks |
|---|---|---|---|
| `150.30` | ✅ Valid | Exact multiple of $0.01 | 15030 |
| `150.00` | ✅ Valid | Exact multiple | 15000 |
| `0.01` | ✅ Valid | Minimum valid price | 1 |
| `150.305` | ❌ **Reject** | Not a multiple of $0.01 — midway between 15030 and 15031 | — |
| `150.999` | ❌ **Reject** | Not a multiple of $0.01 | — |
| `0.00` | ❌ **Reject** | Zero price is forbidden | — |
| `-1.00` | ❌ **Reject** | Negative price is forbidden | — |

**The rule for v6:** if the submitted price is not an exact multiple of the tick
size, **reject the order**. Do not round silently. The user must re-submit with a
correctly aligned price.

The check after `to_ticks()`:

```python
ticks = to_ticks(raw_price, symbol)
reconstructed = from_ticks(ticks, symbol)
tick_size_float = 10.0 ** -get_tick_decimals(symbol)

if abs(reconstructed - raw_price) > tick_size_float * 0.01:
    # Difference exceeds 1% of a tick — price is not aligned.
    # (The 1% tolerance absorbs IEEE 754 representation error for
    #  values that ARE exact multiples, like 150.30.)
    self.pub_sock.send_multipart(
        make_ack_msg(order.gateway_id, order.id, False,
                     f"Price {raw_price} is not a valid tick multiple for "
                     f"{symbol} (tick size = {tick_size_float}). "
                     f"Nearest valid prices: "
                     f"{from_ticks(ticks, symbol):.{get_tick_decimals(symbol)}f} or "
                     f"{from_ticks(ticks + 1, symbol):.{get_tick_decimals(symbol)}f}")
    )
    return
```

The tolerance of 1% of a tick (not 50%) is intentional: it accepts the tiny
IEEE 754 error in a legitimately aligned price like `150.30` (which may be stored
as `150.29999999999998`) while still rejecting a genuinely misaligned price like
`150.305` (which differs by 50% of a tick).

The conversion formulas:

```python
# float → int ticks (at input boundary only)
ticks       = round(float_price * 10**tick_decimals)

# int ticks → float (at output/display boundary only)
float_price = ticks / 10**tick_decimals
```

`round()` is essential — it absorbs the small IEEE 754 representation error so that
`to_ticks(150.30, "AAPL")` gives exactly `15030`. Never use `int()` or truncation.

---

## 3. New Shared Infrastructure — `models/price.py` and `models/clock.py`

Create these two files first. Everything else in the plan imports from one or both of them.

**File 1 of 2:** `src/edumatcher/models/price.py` (tick conversion utilities) — full code below.

**File 2 of 2:** `src/edumatcher/models/clock.py` (monotonic timestamps) — full code in
Section 5.3, where the motivation for it is explained. Create it at the same time as
`price.py`, since `models/order.py` (Phase 1) imports `monotonic_ns` from it.

**New file:** `src/edumatcher/models/price.py`

```python
"""
models/price.py — Integer tick-based price representation.

Prices are stored internally as integers (tick counts). Conversion between
float prices and integer ticks happens only at I/O boundaries:

  Input boundary  (gateway parsing, config loading):
      float price  →  to_ticks(price, symbol)  →  int ticks

  Output boundary (ZMQ publish, display, CSV):
      int ticks  →  from_ticks(ticks, symbol)  →  float price

Everything between these boundaries is integer arithmetic — exact, fast,
and free of floating-point representation error.

Tick registry
-------------
Each symbol has a tick_decimals value loaded from engine_config.yaml.
The registry is populated once at engine startup via register_tick_decimals().
Subscriber processes receive tick_decimals in book snapshot messages and
maintain their own local copy via the same register_tick_decimals() call.

Why int and not Decimal?
------------------------
Python's decimal.Decimal is exact but each operation costs several
microseconds. Integer arithmetic costs ~30ns. Since matching-engine
arithmetic is addition, subtraction, and comparison (no division needed
until display), integers give exactness without the performance cost.
"""

from __future__ import annotations
from typing import Optional

# ---------------------------------------------------------------------------
# Default tick precision
# ---------------------------------------------------------------------------

DEFAULT_TICK_DECIMALS: int = 2    # 1 tick = $0.01

# ---------------------------------------------------------------------------
# Per-symbol registry — populated once at engine startup, never mutated.
# ---------------------------------------------------------------------------

_tick_decimals: dict[str, int] = {}


def register_tick_decimals(symbol: str, tick_decimals: int) -> None:
    """Register tick precision for a symbol. Called once at startup.

    Raises ValueError if tick_decimals is out of range (0–8).
    Raises RuntimeError if called a second time for the same symbol with a
    different value — changing tick size mid-session is forbidden (see Section 5.1).
    """
    if not (0 <= tick_decimals <= 8):
        raise ValueError(
            f"tick_decimals must be 0–8, got {tick_decimals} for {symbol}"
        )
    if symbol in _tick_decimals and _tick_decimals[symbol] != tick_decimals:
        raise RuntimeError(
            f"Attempted to change tick_decimals for '{symbol}' from "
            f"{_tick_decimals[symbol]} to {tick_decimals} mid-session. "
            f"Restart the engine with clean persisted data to change tick size."
        )
    _tick_decimals[symbol] = tick_decimals


def get_tick_decimals(symbol: str) -> int:
    """Return tick_decimals for a symbol, falling back to the default."""
    return _tick_decimals.get(symbol, DEFAULT_TICK_DECIMALS)


# ---------------------------------------------------------------------------
# Conversion — call only at I/O boundaries
# ---------------------------------------------------------------------------

def to_ticks(price_float: float, symbol: str) -> int:
    """
    Convert a human-readable float price to integer ticks.

    round() absorbs the floating-point representation error that makes
    float literals like 150.30 slightly off in IEEE 754. For example:

        to_ticks(150.30, "AAPL")       →  15030  (not 15029 or 15031)
        to_ticks(100.1 + 0.2, "AAPL") →  10030  (not 10030.000000001)

    Always use this function at input boundaries. Never use int() or
    truncation — they give wrong results for prices like $150.30.
    """
    return round(price_float * (10 ** get_tick_decimals(symbol)))


def from_ticks(ticks: int, symbol: str) -> float:
    """
    Convert integer ticks to a human-readable float price.

    For display and JSON output only. The result is a float and must
    not be used for internal arithmetic or price comparisons.
    """
    return ticks / (10 ** get_tick_decimals(symbol))


def format_price(ticks: int, symbol: str) -> str:
    """Format ticks as a price string with correct decimal places."""
    decimals = get_tick_decimals(symbol)
    return f"{ticks / (10 ** decimals):.{decimals}f}"
```

**Note:** compared to the backward-compatible version, `to_ticks_or_none()` and
`from_ticks_or_none()` are gone. Without compat guards, callers handle `None`
themselves with a simple `if price is not None` check where needed.

> **Coming in Section 5.2:** `check_tick_aligned()` also belongs in `models/price.py`
> and must be added when you implement Section 5.2. It validates that a submitted
> float price is an exact tick multiple and returns a descriptive error message if
> not. The Phase 0 checklist item for it will remind you. Do not consider
> `models/price.py` complete until that function is added.

---

## 4. The Conversion Boundary Rule

Before reading any phase, internalise this rule — it governs every decision.

An **I/O boundary** is anywhere data enters or leaves the engine process. When a
user types `PRICE=150.30` in the gateway, that is an input boundary. When the engine
publishes a fill message over ZMQ (the messaging system, see Finance Concepts
Primer), that is an output boundary. Everything between those boundaries stays as
integers.

```
 User terminal          Gateway process        Engine process         Subscriber process
 ─────────────          ───────────────        ──────────────         ──────────────────

 "PRICE=150.30"  ──►   float 150.30    ──►   to_ticks()    ──►   float prices
                        (no conversion)        15030 (int)           (from_ticks)
                                                   │
                        ◄─────────────────────── │ ──────────────────────────────────
                         INPUT BOUNDARY           │ OUTPUT BOUNDARY
                         float→int               │ int→float
                                                   │
                                         ┌─────── │ ──────────────────────────────┐
                                         │  ALL INTERNAL ENGINE CODE              │
                                         │                                        │
                                         │  order.price = 15030      (int)        │
                                         │  _bid_qty[15030] += 100   (int key)    │
                                         │  heap key = (-15030, ns)  (int tuple)  │
                                         │  15030 > 14999            (int cmp)    │
                                         │  15030 - 50 = 14980       (int arith)  │
                                         │                                        │
                                         │  NO FLOATS INSIDE THIS BOX             │
                                         └────────────────────────────────────────┘
```

### Allowed and Forbidden Operations

| Location | Allowed | Forbidden |
|---|---|---|
| Gateway | Parse `float` from user input; send float in JSON payload | Call `to_ticks()`; store int ticks |
| Engine `_handle_new_order()` (input boundary) | Call `to_ticks()` once per price field; validate result | Store raw float; pass float to OrderBook |
| Engine `OrderBook` (internal) | Integer arithmetic; integer key lookups; integer comparison | Accept float prices; call `from_ticks()` |
| Engine `_handle_new_order()` (output boundary) | Call `from_ticks()` before publishing to ZMQ | Publish raw int ticks directly |
| Subscriber processes | Display float prices received from ZMQ | Call `to_ticks()` on received prices; do arithmetic on float prices |

### What Happens If You Violate the Boundary

**Violation 1: storing float prices in the order book.**
```python
# WRONG — float price in the book:
order.price = 150.30   # float
_bid_qty[150.30] += 100   # float key

# Two orders both at "$150.30" but computed differently:
order_a.price = 150.30        # from user input: may be 150.29999...
order_b.price = 150.10 + 0.20 # computed: 150.30000000001

# Result: two separate dict entries — depth is double-counted
assert len(_bid_qty) == 2   # BUG: should be 1
```

**Violation 2: converting from_ticks() inside the engine.**
```python
# WRONG — converting back to float inside a handler then comparing:
display_price = from_ticks(order.price, symbol)  # 150.30 (float)
if display_price >= 150.30:  # float comparison — may be False!
    match()   # BUG: trade never happens
```

**Violation 3: subscriber doing arithmetic on received float prices.**
```python
# WRONG — subscriber computing a spread using received floats:
bid = snapshot["bids"][0]["price"]   # 150.30 (float)
ask = snapshot["asks"][0]["price"]   # 150.35 (float)
spread = ask - bid                    # 0.04999999... — float drift
if spread > 0.05:  # may be wrong!
    alert()

# CORRECT — subscriber displays only, no arithmetic:
bid_str = f"{bid:.2f}"   # "150.30" — display only
ask_str = f"{ask:.2f}"   # "150.35" — display only
```

**Why subscribers must not do arithmetic:** subscribers receive prices that have
already been through one float round-trip (`to_ticks()` then `from_ticks()`). A
second round of float arithmetic compounds the error. Subscribers are display
processes — their job is to show prices, not compute with them.

### Why the Gateway Sends Floats but the Engine Uses Ints

This asymmetry is deliberate:

- **The gateway** is a user-facing terminal. Users type decimal prices. The gateway's
  job is to accept and forward commands faithfully as floats.
- **The engine** is the authority on tick size. It is the only process that reads
  `engine_config.yaml` and knows that AAPL has `tick_decimals=2`. It is therefore
  the only process that can correctly convert prices to ticks.
- **Subscribers** receive prices that the engine has already converted back to floats
  for display — they need no knowledge of tick size.

The conversion happens exactly once in each direction: float→int at the engine input
boundary, int→float at the engine output boundary.

---

## 5. Design Constraints and Rules

This section answers nine questions that the implementation plan deliberately leaves
open unless explicitly resolved. Every decision here is a **rule** — implement it
exactly as stated. Where the rule has consequences for specific files, those
consequences are called out in the relevant phase sections.

---

### 5.1 Tick size is constant for the lifetime of the engine process

`tick_decimals` for a symbol is registered once at startup via
`register_tick_decimals()` and **never changes** while the engine is running.

**Why this must be constant:** Every resting order in the book stores its price as
an integer tick count. If tick size changed mid-session, those stored counts would
be misinterpreted — a price stored as `15030` ticks at $0.01/tick would become
$1503.00 if the tick size changed to $0.10/tick. The entire order book would be
silently corrupted.

**What this means in practice:**

- `register_tick_decimals()` may only be called before the engine begins accepting
  orders. The correct place is inside `_load_config()`, which runs at startup. Never
  call it inside any order handler.
- If you need to change `tick_decimals` for a symbol between restarts (e.g. because
  you made a configuration error), you must also delete all three persisted data
  files and restart clean.
- The engine does not detect whether `tick_decimals` changed between restarts. It is
  the operator's responsibility to delete persisted data when changing tick size.

**Explicit prohibition:** calling `register_tick_decimals()` a second time for the
same symbol with a *different* value during a single engine run is forbidden and
raises `RuntimeError`. (Calling it again with the *same* value is harmless and
allowed — this is what lets subscribers re-register idempotently on every snapshot,
see Section 5.8.) The `register_tick_decimals()` implementation in `models/price.py`
enforces this:

```python
def register_tick_decimals(symbol: str, tick_decimals: int) -> None:
    """Register tick precision for a symbol. Called once at startup."""
    if not (0 <= tick_decimals <= 8):
        raise ValueError(
            f"tick_decimals must be 0–8, got {tick_decimals} for {symbol}"
        )
    if symbol in _tick_decimals and _tick_decimals[symbol] != tick_decimals:
        raise RuntimeError(
            f"Attempted to change tick_decimals for '{symbol}' from "
            f"{_tick_decimals[symbol]} to {tick_decimals} mid-session. "
            f"Restart the engine with clean persisted data to change tick size."
        )
    _tick_decimals[symbol] = tick_decimals
```

---

### 5.2 Price alignment: reject prices that are not exact tick multiples

**v6 policy: reject misaligned prices. Do not round silently.**

When the engine receives a float price from the gateway, it calls `to_ticks()`
which uses `round()`. After conversion, the engine checks whether the result
faithfully represents the submitted price. If not — if the user submitted a price
that is not a valid tick multiple — the order is **rejected** with a clear error
message telling the user the nearest valid prices.

**Why reject rather than round?** Silent rounding is deceptive. A user who submits
`$150.305` intends to buy or sell at exactly that price. If the engine rounds to
`$150.31` without telling them, the user may trade at a price they did not intend.
Rejection forces the user to be explicit about which tick boundary they mean.

**Why `to_ticks()` still uses `round()` internally:** IEEE 754 means that even a
legitimately aligned price like `$150.30` may be stored as `150.29999999999998` in
floating-point. `round()` corrects this tiny error silently, giving `15030`. The
alignment check then verifies whether the reconstruction from those ticks is close
enough to the submitted price — and for `150.30` it is, within the 1% tolerance. A
genuinely misaligned price like `150.305` rounds to `15030` (banker's rounding of
`15030.5`), whose reconstruction `150.30` differs from the submitted `150.305` by
half a tick — far exceeding the tolerance. So `150.305` is correctly rejected while
`150.30` is correctly accepted.

Note also the example in the table below uses a `0.0001` threshold: that is 1% of
the `$0.01` tick size for a 2-decimal symbol (`0.01 × 0.01 = 0.0001`).

```
Submitted   to_ticks()  from_ticks()  Difference  Threshold   Result
─────────── ─────────── ─────────────  ──────────  ─────────   ──────
150.30      15030       150.30         0.000       0.0001      ✅ Accept
150.305     15030       150.30         0.005       0.0001      ❌ Reject
150.999     15100       151.00         0.001       0.0001      ❌ Reject
0.00        0           —              —           —           ❌ Reject (zero)
-1.00       -100        —              —           —           ❌ Reject (negative)
```

Note on `150.305`: `150.305 × 100 = 15030.5`, and Python's `round()` uses
banker's rounding (round-half-to-even), so `round(15030.5) = 15030`. The
reconstruction `from_ticks(15030)` is `150.30`, which differs from the submitted
`150.305` by `0.005` — half a tick, far exceeding the `0.0001` threshold. The order
is rejected. (The exact tick the price rounds to does not matter for the decision;
what matters is that the reconstruction differs from the submission by more than
the tolerance.)

**The validation function** (add to `models/price.py`):

```python
import math

def check_tick_aligned(raw_price: float, symbol: str) -> tuple[int, str]:
    """
    Convert a float price to ticks and validate alignment.

    Returns (ticks, error_message).
    If error_message is non-empty, the price is invalid — reject the order.
    If error_message is empty, the price is valid — use ticks.

    The 1% tolerance absorbs IEEE 754 representation error for prices
    that ARE exact tick multiples (e.g. 150.30 stored as 150.29999...).
    """
    ticks = to_ticks(raw_price, symbol)
    if ticks <= 0:
        return ticks, f"Price must be positive (got {raw_price})"

    reconstructed = from_ticks(ticks, symbol)
    td        = get_tick_decimals(symbol)
    tick_sz   = 10.0 ** -td
    tolerance = tick_sz * 0.01   # 1% of one tick

    if abs(reconstructed - raw_price) > tolerance:
        # Compute the two valid tick prices that bracket the submitted value,
        # so the error message guides the user to a correct price.
        scaled = raw_price * (10 ** td)
        lower  = from_ticks(math.floor(scaled), symbol)
        upper  = from_ticks(math.ceil(scaled),  symbol)
        return ticks, (
            f"Price {raw_price:.{td+3}f} is not a valid tick multiple for "
            f"{symbol} (tick size = {tick_sz:.{td}f}). "
            f"Nearest valid prices: {lower:.{td}f} or {upper:.{td}f}"
        )
    return ticks, ""
```

Use it at every engine input boundary:

```python
# In _handle_new_order(), after the Order object has been built:
raw_price = payload.get("price")
if raw_price is not None:
    price_ticks, err = check_tick_aligned(float(raw_price), symbol)
    if err:
        self.pub_sock.send_multipart(
            make_ack_msg(order.gateway_id, order.id, False, err)
        )
        return
```

Apply the same check for `stop_price` and `trail_offset`.

**The gateway's role** remains unchanged: send floats, no validation. The engine
rejects invalid prices with a message that includes the nearest valid alternatives,
so the user knows exactly how to fix their submission.

---

### 5.3 Timestamp monotonicity: enforce with a wrapper function

#### What is a monotonic clock?

A **monotonic clock** is one that never goes backwards — each reading is guaranteed
to be greater than or equal to the previous reading. Python's `time.monotonic()`
is monotonic (used for measuring elapsed time), but `time.time_ns()` is NOT
guaranteed to be strictly monotonic because it reflects the system wall clock, which
can be adjusted:

- **NTP (Network Time Protocol)** adjustments step the clock forward or backward
  to keep it synchronised with a time server. A backward step makes `time.time_ns()`
  return a value smaller than the previous call.
- **Virtual machine hypervisor** pauses and resumes can cause similar jumps.

#### Why does non-monotonicity break the order book?

The heap key for a resting order is `(-price_ticks, timestamp_ns)`. The timestamp
breaks ties between orders at the same price — earlier timestamps should sort first,
implementing FIFO (first-in, first-out) within each price level.

If two orders get the same timestamp (or an out-of-order timestamp), FIFO is
violated:

```
What should happen (FIFO at price 15030):

Order A arrives at ns=1000: heap key = (-15030, 1000)   ← first in
Order B arrives at ns=1001: heap key = (-15030, 1001)   ← second in

Heap peek returns A ✅  (1000 < 1001, so A sorts first)

─────────────────────────────────────────────────────────────

What happens if clock goes backwards (FIFO violated):

Order A arrives at ns=1000: heap key = (-15030, 1000)   ← first in
Clock steps back by 2ns
Order B arrives at ns=999:  heap key = (-15030, 999)    ← second in, but smaller ts

Heap peek returns B ❌  (999 < 1000, so B sorts first — wrong!)
```

The participant who submitted Order A first gets filled second. Their price-time
priority was stolen by a clock adjustment they had no control over.

#### The fix: enforce monotonicity with a wrapper

Create a module-level function that guarantees strictly increasing timestamps.

We place it in `models/` rather than `engine/` because both the models layer
(`Order.create()`, `Trade.create()`) and the engine layer need it. Putting it in
`models/` keeps the dependency direction clean: models never import from engine.

**New file:** `src/edumatcher/models/clock.py`

```python
"""
models/clock.py — Strictly monotonic nanosecond timestamps.

time.time_ns() reflects the system wall clock and can go backwards on NTP
adjustments or VM hypervisor pauses. This module provides monotonic_ns(),
which always returns a value strictly greater than the previous call.

Usage:
    from edumatcher.models.clock import monotonic_ns
    now = monotonic_ns()    # replaces time.time_ns() everywhere in the engine

Thread safety:
    The engine is single-threaded, so no locking is needed. If threads are
    ever introduced, add threading.Lock() around the comparison and assignment.
"""

import time

_last_ns: int = 0


def monotonic_ns() -> int:
    """
    Return a strictly increasing nanosecond timestamp.

    If time.time_ns() returns the same or smaller value as the previous call
    (due to clock adjustment), returns previous + 1 instead. This guarantees
    that every call returns a unique value greater than all previous calls.

    The returned value is anchored to real wall-clock time as long as the
    system clock is not adjusted. After a backward adjustment, values may be
    slightly ahead of wall clock time (by at most the size of the adjustment),
    but they are always monotonically increasing.
    """
    global _last_ns
    ts = time.time_ns()
    if ts <= _last_ns:
        ts = _last_ns + 1
    _last_ns = ts
    return ts
```

Replace **every** call to `time.time_ns()` in the engine with `monotonic_ns()`:

```python
# In engine/main.py:
from edumatcher.models.clock import monotonic_ns

# Replace:
now = time.time_ns()
# With:
now = monotonic_ns()
```

Also update `Order.create()` in `models/order.py` to use `monotonic_ns()` as its
fallback when `now` is not supplied (note: this requires adding a `now` parameter
to `Order.create()` if it does not already have one — see Section 8.2):

```python
from edumatcher.models.clock import monotonic_ns

@classmethod
def create(cls, ..., now: int | None = None) -> "Order":
    ...
    timestamp=now if now is not None else monotonic_ns(),
```

And `Trade.create()` in `models/trade.py`:
```python
timestamp=now if now is not None else monotonic_ns(),
```

Add the monotonicity comment near the heap insertion in `_rest()`:

```python
# INVARIANT: timestamp_ns is strictly monotonically increasing thanks to
# monotonic_ns() in models/clock.py. No two orders can share a timestamp,
# so price-time priority is always deterministic.
key = (-order.price, order.timestamp)
heapq.heappush(heap, entry)
```

---

### 5.4 Integer bounds: explicit minimum and maximum values

**Tick prices:**

| Constraint | Rule | Reason |
|---|---|---|
| Negative price | **Reject** — prices must be `> 0` | No instrument trades at or below zero |
| Zero price | **Reject** — prices must be `> 0` | Zero price has no meaning for a limit order |
| Maximum price | No explicit limit enforced | Python integers are arbitrary precision; `10**15` ticks (= $10 trillion at $0.01/tick) exceeds any real price |
| `trail_offset` | Must be `> 0` | A zero or negative trailing distance makes no mathematical sense |
| `stop_price` | Must be `> 0` | Same as price |

The positive-price check is already built into `check_tick_aligned()` (Section 5.2),
which returns an error message when `ticks <= 0`. If you prefer an explicit standalone
check at the call-site in `_handle_new_order()`, it looks like this:

```python
if ticks <= 0:
    # reject the order
    self.pub_sock.send_multipart(
        make_ack_msg(order.gateway_id, order.id, False,
                     f"Price must be positive, got {raw_price}")
    )
    return
```

Apply the same check for `stop_price` and `trail_offset`.

**Timestamps:**

| Constraint | Rule |
|---|---|
| Negative timestamp | Cannot occur with `monotonic_ns()` — no enforcement needed |
| Maximum timestamp | No explicit limit — Python integers are arbitrary precision |

---

### 5.5 Combo leg price validation: per-leg, using each leg's symbol

#### What is a combo order?

A combo order is an instruction to execute orders in multiple instruments
simultaneously. Each instrument is called a **leg**. For example:
"Buy 100 shares of AAPL at $150.30 AND sell 50 shares of MSFT at $415.50."

Each leg may have a different instrument, side, quantity, and price — and
critically, each instrument may have a different tick size.

#### Concrete example: a 2-leg combo

```
Combo order received as JSON:
{
  "combo_id": "PAIR001",
  "gateway_id": "GW01",
  "legs": [
    {
      "symbol":     "AAPL",
      "side":       "BUY",
      "quantity":   100,
      "price":      150.30,      ← float from gateway
      "stop_price": null
    },
    {
      "symbol":     "MSFT",
      "side":       "SELL",
      "quantity":   50,
      "price":      415.50,      ← float from gateway
      "stop_price": null
    }
  ]
}
```

Per-leg tick conversion:

```
Leg 0 — AAPL (tick_decimals=2, tick_size=$0.01):
  raw_price = 150.30
  ticks     = to_ticks(150.30, "AAPL") = 15030     ← uses AAPL's tick_decimals
  check     : from_ticks(15030, "AAPL") = 150.30   ← aligned ✅

Leg 1 — MSFT (tick_decimals=2, tick_size=$0.01):
  raw_price = 415.50
  ticks     = to_ticks(415.50, "MSFT") = 41550     ← uses MSFT's tick_decimals
  check     : from_ticks(41550, "MSFT") = 415.50   ← aligned ✅

Both legs valid → create child orders:
  child_0.price = 15030   (int ticks, AAPL)
  child_1.price = 41550   (int ticks, MSFT)
```

**The critical rule:** the tick lookup in `check_tick_aligned()` uses
`leg.symbol`, not the combo's symbol (combos have no single symbol). If you
accidentally pass the wrong symbol, the wrong tick size is used and an aligned
price can appear misaligned, or vice versa.

#### What if two legs have different tick sizes?

This is completely normal. A combo spanning a US equity ($0.01 ticks) and an FX
pair ($0.0001 ticks) would have:

```
Leg 0 — AAPL (tick_decimals=2): price 150.30 → 15030 ticks
Leg 1 — EURUSD (tick_decimals=4): price 1.2345 → 12345 ticks
```

The two tick counts (15030 and 12345) are in different units and must never be
compared or added to each other. They are stored separately on each child order.

#### Validation checklist for combo legs

Process each leg sequentially. If any leg fails, reject the entire combo.

```python
for i, leg in enumerate(combo.legs):
    # 1. Symbol must be known
    if self._allowed_symbols and leg.symbol not in self._allowed_symbols:
        _reject_combo(combo, f"Leg {i}: unknown symbol {leg.symbol!r}")
        return False

    # 2. Validate price alignment using that leg's symbol
    if leg.price is not None:
        _, err = check_tick_aligned(
            from_ticks(leg.price, leg.symbol),  # leg.price is already int ticks
            leg.symbol                           # MUST use leg.symbol, not combo symbol
        )
        if err:
            _reject_combo(combo, f"Leg {i} ({leg.symbol}) price: {err}")
            return False

    # 3. Validate stop price alignment (if present)
    if leg.stop_price is not None:
        _, err = check_tick_aligned(
            from_ticks(leg.stop_price, leg.symbol),
            leg.symbol
        )
        if err:
            _reject_combo(combo, f"Leg {i} ({leg.symbol}) stop_price: {err}")
            return False

    # 4. Validate positive prices (redundant with check_tick_aligned but explicit)
    if leg.price is not None and leg.price <= 0:
        _reject_combo(combo, f"Leg {i} ({leg.symbol}): price must be positive")
        return False
```

---

### 5.6 Persistence format versioning: use format_version=2

#### What is schema evolution and why does it matter?

A **schema** is the structure of a data file — what fields it contains, what their
types are, what values are valid. Over time, schemas evolve: new fields are added,
old fields are removed, types change.

Without a version field, there is no reliable way to detect that a file was written
by an older version of the code. The engine might load it without error and silently
produce wrong results — for example, reading an old float timestamp as a nanosecond
timestamp, getting a value 10⁹ times too large.

A `format_version` field makes the schema version explicit:
- The writer stamps the version it used.
- The reader checks the version. If it does not match what it expects, it refuses
  to load and prints a clear error.

This turns a silent bug (wrong values) into a loud failure (crash with explanation).

#### Why format_version=2?

v5 of this plan introduced `format_version=1`. v6 changes the rejection policy for
misaligned prices: prices that were silently rounded and accepted under v5's
"round and warn" policy are now rejected outright. This means a `gtc_orders.json`
written by a v5 engine could contain orders whose prices would fail v6 validation
if they were re-submitted today. To prevent a v6 engine from loading those
potentially-invalid orders, v6 bumps the persisted format to `format_version=2`.

**Rule: a v6 engine must reject any file whose `format_version` is not exactly `2`.**

#### Before and after JSON examples

**Before (pre-migration, plain list — no version field):**
```json
[
  {
    "id": "abc-123",
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "tif": "GTC",
    "quantity": 100,
    "remaining_qty": 100,
    "gateway_id": "GW01",
    "timestamp": 1748000000.123456,
    "price": 150.30,
    "status": "NEW",
    "smp_action": "NONE"
  }
]
```
Problems with this format: plain list (no versioning), float timestamp (seconds,
not nanoseconds), no `format_version` — cannot detect if loaded by wrong engine.

**After (v6 format, format_version=2):**
```json
{
  "format_version": 2,
  "orders": [
    {
      "id": "abc-123",
      "symbol": "AAPL",
      "side": "BUY",
      "order_type": "LIMIT",
      "tif": "GTC",
      "quantity": 100,
      "remaining_qty": 100,
      "gateway_id": "GW01",
      "timestamp": 1748000000123456789,
      "price": 150.30,
      "status": "NEW",
      "smp_action": "NONE"
    }
  ]
}
```
Changes: wrapped in a dict, `format_version: 2` key present, `timestamp` is now an
integer nanosecond value.

**The rule:** add `"format_version": 2` as the first key in every JSON file the
engine writes. On load, check for this field. If it is absent or has any value
other than `2`, refuse to load the file.

```python
def save_gtc_orders(orders: list[Order], path: Path) -> None:
    gtc = [
        o.to_dict()
        for o in orders
        if o.tif == TIF.GTC and o.status in (OrderStatus.NEW, OrderStatus.PARTIAL)
    ]
    output = {"format_version": 2, "orders": gtc}   # ← version 2
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2))


def load_gtc_orders(path: Path) -> list[Order]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    # Detect old pre-migration format (plain list)
    if isinstance(raw, list):
        raise RuntimeError(
            f"{path} is in the pre-migration format (a plain list, no version). "
            f"Delete this file and restart the engine."
        )
    version = raw.get("format_version")
    if version != 2:
        raise RuntimeError(
            f"Expected format_version=2 in {path}, got {version!r}. "
            f"This file was written by a different version of EduMatcher. "
            f"Delete this file and restart the engine."
        )
    return [Order.from_dict(d) for d in raw.get("orders", [])]
```

Apply the same versioning to `save_gtc_combos()` / `load_gtc_combos()`.

`book_stats.json` does not need versioning — it is always fully overwritten on
clean shutdown, so an old file cannot survive.

---

### 5.7 Replay log format: float prices, intentional, never migrate

`clearing_report.csv` and `data/stats.db` store human-readable float prices. This
is **intentional and permanent**. These files are for human operators, external
reporting tools, and spreadsheet analysis — they must contain prices that a person
can read without knowing the tick size.

**The rules:**

- Do not convert prices in these files to integer ticks, now or in future migrations.
- Future tools that read these files should treat all price columns as `float`.
- If a new reporting tool is built that needs tick-precision internal arithmetic,
  it should read the float prices and call `to_ticks()` itself — after confirming
  the symbol's tick size from the engine config.
- Do not add a `tick_decimals` column to these files. The float values are already
  correctly rounded to tick precision by the engine before they are written.

No code changes are needed for these files.

---

### 5.8 Cross-process tick registry: explicit synchronisation rules

The engine adds `"tick_decimals": <int>` to every book snapshot message (see Phase 8,
Section 15.9). Subscriber processes that display or process prices must call
`register_tick_decimals()` to keep their local registries in sync.

**Explicit rules:**

| Rule | Detail |
|---|---|
| Field name | `"tick_decimals"` — a plain Python `int` in the snapshot JSON |
| When to register | On every snapshot received, not just the first. It is idempotent since tick size never changes mid-session |
| Subscriber startup before first snapshot | Use `DEFAULT_TICK_DECIMALS = 2` as fallback — already the behaviour of `get_tick_decimals()` |
| Subscriber code pattern | See below |

```python
# In any subscriber that receives book snapshots:
def _handle_book_snapshot(self, payload: dict[str, Any]) -> None:
    symbol = payload["symbol"]

    # Synchronise tick registry from the snapshot.
    # This is idempotent — calling it on every snapshot is correct.
    tick_decimals = payload.get("tick_decimals")
    if tick_decimals is not None:
        from edumatcher.models.price import register_tick_decimals
        register_tick_decimals(symbol, int(tick_decimals))

    # Now safe to call from_ticks() on prices from this snapshot
    ...
```

Add this pattern to the subscriber loop in:
- `clearing/main.py` — if it ever needs to display or log tick-precise prices
- `stats/main.py` — if it stores prices in tick-based formats in future
- `viewer/main.py`, `board/main.py` — optional, since snapshot prices arrive already
  as floats, but good practice

**The rule on tick size changing mid-session:** it cannot (see Section 5.1).
Therefore if a subscriber calls `register_tick_decimals()` on every snapshot, it
will always register the same value — no conflict, no side-effect.

---

## 6. Before You Start — Delete Persisted Data

No backward compatibility means the old persisted files (written in float-price
format) cannot be read by the migrated engine. Delete them before starting:

```bash
rm -f data/gtc_orders.json
rm -f data/book_stats.json
rm -f data/gtc_combos.json
```

**What each file stores and why it must be deleted:**

- **`gtc_orders.json`** — resting limit orders with TIF=GTC (Good-Till-Cancelled,
  meaning they survive overnight). Files written before this migration are in the
  old format: a plain JSON list with float timestamps and no `format_version` field.
  A v6 engine rejects them on load (see Section 5.6). Delete the file to start clean.
- **`book_stats.json`** — the last traded buy and sell price for each symbol, used
  to seed stop-order logic and display after a restart. Pre-migration files store
  these as floats in a format the v6 loader does not expect. Delete to start clean.
- **`gtc_combos.json`** — multi-leg GTC combo orders (see Finance Concepts Primer).
  Same situation as `gtc_orders.json`: old-format files are rejected on load, so
  delete before starting.

These files are recreated automatically on the next clean engine shutdown. Two other
files do **not** need to be deleted:
- **`clearing_report.csv`** — a trade history log; append-only; never read back by
  the engine.
- **`data/stats.db`** — SQLite database of OHLCV (Open, High, Low, Close, Volume)
  market statistics; append-only; never read back by the engine.

---

## 7. Phase Order

Implement phases strictly in this sequence. Later phases depend on earlier ones.

> **Navigation note:** The document sections are numbered from 1 onwards (for the
> Table of Contents), but the phases themselves are numbered starting at 0. The
> mapping is: **document section N contains Phase N − 7**. For example, Phase 1
> (`models/order.py`) is in document section 8. The table below is the definitive
> reference — use it to find the right section for each phase.

| Phase | File | Document Section | Dependency |
|-------|------|-----------------|------------|
| **0** | `models/price.py` + `models/clock.py` | Section 3 | None — create both first |
| **1** | `models/order.py` | Section 8 | Needs `price.py` |
| **2** | `models/trade.py` | Section 9 | Needs `price.py` |
| **3** | `models/combo.py` | Section 10 | Needs `order.py` |
| **4** | `engine/order_book.py` | Section 11 | Needs `order.py`, `trade.py` |
| **5** | `engine/auction.py` | Section 12 | Needs `order_book.py` |
| **6** | `engine/config_loader.py` + `engine_config.yaml` | Section 13 | Needs `price.py` |
| **7** | `engine/persistence.py` | Section 14 | Needs `order.py`, `price.py` |
| **8** | `engine/main.py` | Section 15 | Needs everything above |
| **9** | `models/message.py` | Section 16 | Needs `price.py` |
| **10** | `gateway/main.py` | Section 17 | Needs `message.py` |
| **11** | `clearing/main.py` | Section 18 | Needs `trade.py` |
| **12** | `stats/main.py` | Section 19 | Needs `trade.py` |
| **13** | `viewer/main.py`, `board/main.py` | Section 20 | Needs snapshot format |
| **14** | `ticker/main.py` | Section 21 | Needs snapshot format |
| **15** | `ai_trader/main.py`, `personality.py` | Section 22 | Needs snapshot format |

Run the full test suite after each phase before moving to the next. After Phase 4
(`order_book.py`) in particular, run tests before continuing — this is the most
likely phase to introduce a subtle regression.

---

## 8. Phase 1 — `models/order.py`

This is the most fundamental change. Every downstream phase follows from it.

### 8.1 Change field types

**Current:**
```python
timestamp:   float
price:       Optional[float] = None
stop_price:  Optional[float] = None
trail_offset: Optional[float] = None
```

**New:**
```python
timestamp:   int               # nanoseconds since Unix epoch
price:       Optional[int] = None   # ticks
stop_price:  Optional[int] = None   # ticks — the price level that activates this stop
trail_offset: Optional[int] = None  # ticks — how far the stop follows the market
```

`trail_offset` in ticks deserves a moment of explanation. For a sell trailing stop
with `trail_offset = 50` (= $0.50 for a 2-decimal symbol):
- If the market is at $150.00, the stop trigger is at $150.00 − $0.50 = $149.50
- If the market rises to $155.00, the stop ratchets up to $155.00 − $0.50 = $154.50
- The ratchet arithmetic is: `new_stop = last_price_ticks - trail_offset_ticks`

Using integer ticks makes every ratchet step exact. With floats, 100 steps of
`$150.00 - $0.50 → $149.50` accumulate ~10⁻¹² of error; with ints, the result is
always exactly the right integer.

### 8.2 Update `Order.create()`

Change parameter types, add an optional `now` parameter, and use `monotonic_ns()`
for the timestamp. The `now` parameter lets the engine pass a single timestamp
captured once per incoming message, so that all orders and trades produced while
handling one message share a consistent time (and avoids calling the clock more
than necessary). When `now` is not supplied, `Order.create()` falls back to
`monotonic_ns()` (see Section 5.3 for why this wrapper is used instead of
`time.time_ns()`):

```python
from edumatcher.models.clock import monotonic_ns

@classmethod
def create(
    cls,
    symbol:       str,
    side:         Side,
    order_type:   OrderType,
    quantity:     int,
    gateway_id:   str,
    tif:          TIF = TIF.DAY,
    price:        Optional[int] = None,        # ticks
    stop_price:   Optional[int] = None,        # ticks
    visible_qty:  Optional[int] = None,
    smp_action:   SmpAction = SmpAction.NONE,
    trail_offset: Optional[int] = None,        # ticks
    oco_group_id: Optional[str] = None,
    now:          Optional[int] = None,        # int nanoseconds; defaults to monotonic_ns()
) -> "Order":
    displayed = visible_qty if order_type == OrderType.ICEBERG else None
    return cls(
        id=str(uuid.uuid4()),
        symbol=symbol,
        side=side,
        order_type=order_type,
        tif=tif,
        quantity=quantity,
        remaining_qty=quantity,
        gateway_id=gateway_id,
        timestamp=now if now is not None else monotonic_ns(),   # ← int nanoseconds
        status=OrderStatus.NEW,
        price=price,
        stop_price=stop_price,
        visible_qty=visible_qty,
        displayed_qty=displayed,
        smp_action=smp_action,
        trail_offset=trail_offset,
        oco_group_id=oco_group_id,
    )
```

### 8.3 Update `to_dict()`

Prices are published as **float** in ZMQ messages so subscribers can display them
without needing the tick registry. Timestamps stay as **int** nanoseconds.

```python
def to_dict(self) -> dict[str, Any]:
    from edumatcher.models.price import from_ticks
    return {
        "id":           self.id,
        "symbol":       self.symbol,
        "side":         self.side.value,
        "order_type":   self.order_type.value,
        "tif":          self.tif.value,
        "quantity":     self.quantity,
        "remaining_qty": self.remaining_qty,
        "gateway_id":   self.gateway_id,
        "trail_offset": (
            from_ticks(self.trail_offset, self.symbol)
            if self.trail_offset is not None else None
        ),
        "oco_group_id":    self.oco_group_id,
        "timestamp":       self.timestamp,      # int nanoseconds — kept as int
        "status":          self.status.value,
        "price": (
            from_ticks(self.price, self.symbol)
            if self.price is not None else None
        ),
        "stop_price": (
            from_ticks(self.stop_price, self.symbol)
            if self.stop_price is not None else None
        ),
        "visible_qty":     self.visible_qty,
        "displayed_qty":   self.displayed_qty,
        "smp_action":      self.smp_action.value,
        "combo_parent_id": self.combo_parent_id,
        "leg_index":       self.leg_index,
    }
```

### 8.4 Update `from_dict()`

No compat guards. The JSON always carries float prices and int timestamps:

```python
@classmethod
def from_dict(cls, d: dict[str, Any]) -> "Order":
    from edumatcher.models.price import to_ticks
    o = object.__new__(cls)
    o.id          = d["id"]
    o.symbol      = d["symbol"]
    o.side        = _SIDE_MAP[d["side"]]
    o.order_type  = _TYPE_MAP[d["order_type"]]
    o.tif         = _TIF_MAP[d["tif"]]
    o.quantity    = d["quantity"]
    o.remaining_qty = d["remaining_qty"]
    o.gateway_id  = d["gateway_id"]
    o.timestamp   = d["timestamp"]     # int nanoseconds — no conversion
    o.status      = _STATUS_MAP[d["status"]]

    # Float prices from JSON → int ticks
    _p  = d.get("price")
    _sp = d.get("stop_price")
    _to = d.get("trail_offset")
    o.price        = to_ticks(_p,  o.symbol) if _p  is not None else None
    o.stop_price   = to_ticks(_sp, o.symbol) if _sp is not None else None
    o.trail_offset = to_ticks(_to, o.symbol) if _to is not None else None

    o.visible_qty    = d.get("visible_qty")
    o.displayed_qty  = d.get("displayed_qty")
    o.smp_action     = _SMP_MAP.get(d.get("smp_action", "NONE"), SmpAction.NONE)
    o.oco_group_id   = d.get("oco_group_id")
    o.combo_parent_id = d.get("combo_parent_id")
    o.leg_index      = d.get("leg_index")
    return o
```

Clean, flat, no branching.

Two performance patterns are preserved from the original code and should not be
removed:

- **`object.__new__(cls)` bypass** — bypasses the normal `__init__` method. The
  dataclass-generated `__init__` with many keyword arguments is slow due to Python's
  argument-dispatch overhead. Writing slot values directly via `__new__` and then
  assigning attributes is faster. Do not replace this with a normal constructor call.
- **Pre-built enum lookup dicts** (`_SIDE_MAP`, `_TYPE_MAP`, etc.) — these are
  dictionaries built once when the module loads, mapping string values like `"BUY"`
  directly to their `Side.BUY` enum member. Using `_SIDE_MAP["BUY"]` is much faster
  than `Side("BUY")` because Python's `Enum()` constructor iterates all members.

---

## 9. Phase 2 — `models/trade.py`

### 9.1 Change field types

**Current:**
```python
price:     float
timestamp: float
```

**New:**
```python
price:     int    # ticks
timestamp: int    # nanoseconds
```

### 9.2 Update `Trade.create()`

```python
from edumatcher.models.clock import monotonic_ns

@classmethod
def create(
    cls,
    symbol:          str,
    buy_order_id:    str,
    sell_order_id:   str,
    buy_gateway_id:  str,
    sell_gateway_id: str,
    price:           int,           # ticks — no conversion needed, caller passes ticks
    quantity:        int,
    now:             int | None = None,   # nanoseconds
) -> "Trade":
    return cls(
        id=str(next(_trade_counter)),
        symbol=symbol,
        buy_order_id=buy_order_id,
        sell_order_id=sell_order_id,
        buy_gateway_id=buy_gateway_id,
        sell_gateway_id=sell_gateway_id,
        price=price,
        quantity=quantity,
        timestamp=now if now is not None else monotonic_ns(),
    )
```

### 9.3 Update `to_dict()`

```python
def to_dict(self) -> dict[str, Any]:
    from edumatcher.models.price import from_ticks
    return {
        "id":              self.id,
        "symbol":          self.symbol,
        "buy_order_id":    self.buy_order_id,
        "sell_order_id":   self.sell_order_id,
        "buy_gateway_id":  self.buy_gateway_id,
        "sell_gateway_id": self.sell_gateway_id,
        "price":           from_ticks(self.price, self.symbol),  # float for display
        "quantity":        self.quantity,
        "timestamp":       self.timestamp,    # int nanoseconds
    }
```

### 9.4 Update `from_dict()`

```python
@classmethod
def from_dict(cls, d: dict[str, Any]) -> "Trade":
    from edumatcher.models.price import to_ticks
    symbol = d["symbol"]
    return cls(
        id=d["id"],
        symbol=symbol,
        buy_order_id=d["buy_order_id"],
        sell_order_id=d["sell_order_id"],
        buy_gateway_id=d["buy_gateway_id"],
        sell_gateway_id=d["sell_gateway_id"],
        price=to_ticks(d["price"], symbol),   # float from JSON → int ticks
        quantity=d["quantity"],
        timestamp=d["timestamp"],             # int nanoseconds — no conversion
    )
```

---

## 10. Phase 3 — `models/combo.py`

### 10.1 Update `ComboLeg` field types

**Current:**
```python
price:      Optional[float] = None
stop_price: Optional[float] = None
```

**New:**
```python
price:      Optional[int] = None   # ticks
stop_price: Optional[int] = None   # ticks
```

### 10.2 Update `ComboLeg.to_dict()` and `from_dict()`

```python
def to_dict(self) -> dict[str, Any]:
    from edumatcher.models.price import from_ticks
    return {
        "symbol":     self.symbol,
        "side":       self.side.value,
        "order_type": self.order_type.value,
        "quantity":   self.quantity,
        "price": (
            from_ticks(self.price, self.symbol)
            if self.price is not None else None
        ),
        "stop_price": (
            from_ticks(self.stop_price, self.symbol)
            if self.stop_price is not None else None
        ),
        "smp_action": self.smp_action.value,
    }

@classmethod
def from_dict(cls, d: dict[str, Any]) -> "ComboLeg":
    from edumatcher.models.price import to_ticks
    symbol = d["symbol"]
    _p  = d.get("price")
    _sp = d.get("stop_price")
    return cls(
        symbol=symbol,
        side=Side(d["side"]),
        order_type=OrderType(d["order_type"]),
        quantity=d["quantity"],
        price=      to_ticks(_p,  symbol) if _p  is not None else None,
        stop_price= to_ticks(_sp, symbol) if _sp is not None else None,
        smp_action=SmpAction(d.get("smp_action", SmpAction.NONE.value)),
    )
```

### 10.3 Update `ComboOrder.timestamp`

**Current:**
```python
timestamp: float
...
timestamp=time.time(),
```

**New:**
```python
from edumatcher.models.clock import monotonic_ns

timestamp: int    # nanoseconds
...
timestamp=monotonic_ns(),
```

Update `to_dict()` to keep `timestamp` as int and `from_dict()` to read it
directly without conversion:

```python
# to_dict():
"timestamp": self.timestamp,   # int nanoseconds — no conversion

# from_dict():
combo.timestamp = d["timestamp"]   # int nanoseconds — no conversion
```

---

## 11. Phase 4 — `engine/order_book.py`

This file has the most internal changes — every price-related type annotation,
heap key, and dictionary changes from float to int. The matching logic itself
requires almost no structural change because integer arithmetic and comparison
work identically to float for addition, subtraction, and `>`, `<`, `==`.

### Order Book Invariants

Before making any changes, understand the invariants the order book must maintain.
These are properties that must be true at all times. If any invariant is violated,
matching will produce wrong results.

| Invariant | Description | What breaks if violated |
|---|---|---|
| **All prices are positive int ticks** | Every price, stop_price, and trail_offset must be an `int > 0` | Matching compares wrong values; heap ordering breaks |
| **All timestamps are positive int ns** | Every order timestamp must be an `int > 0` | FIFO ordering breaks; timestamps become meaningless |
| **Heap keys are pure int tuples** | `_bids` keys: `(-int, int)`. `_asks` keys: `(int, int)` | Heap comparison mixes int and float — Python will raise `TypeError` |
| **`_bid_qty` and `_ask_qty` use int keys** | Every price level key must be `int` | Two orders at "the same" float price create separate levels |
| **`_bid_qty` tracks visible qty only** | For iceberg orders, only `displayed_qty` is counted — not the hidden reserve | FOK checks undercount available liquidity; see Section 11.9 |
| **`_bid_qty` deletes empty levels** | When `qty_index[price]` reaches 0, the key must be deleted | FOK sees phantom liquidity; depth snapshots show empty levels |
| **`_order_index` maps to Order with int price** | The Order stored in the index must have int prices | Cancel operations find wrong values |
| **`last_trade_price` is int or None** | Never a float | Stop order checks trigger at wrong prices |
| **Monotonically increasing timestamps** | Each new order gets a timestamp > all previous orders | FIFO within price level breaks silently |

### Heap Structure: Before and After

The bid and ask heaps use tuples as sort keys. Here is what entries look like
before and after the migration:

**Before migration (float prices, float timestamps):**
```
_bids (max-heap via negation):
  [0] heap key = (-210.00, 1748000000.100)   ← best bid: $210.00, arrived first
  [1] heap key = (-210.00, 1748000000.101)   ← same price, arrived later
  [2] heap key = (-209.50, 1748000000.095)

Problems:
  • Float negation: -210.00 == -209.99999... in some cases → wrong sort
  • Float timestamps: two orders may have identical timestamps
  • dict key: _bid_qty[210.00] vs _bid_qty[209.99999...] — two entries!
```

**After migration (int ticks, int nanoseconds):**
```
_bids (max-heap via negation):
  [0] heap key = (-21000, 1748000000100000000)  ← $210.00=21000t, arrived first
  [1] heap key = (-21000, 1748000000101000000)  ← same price, strictly later ns
  [2] heap key = (-20950, 1748000000095000000)  ← $209.50=20950t

Benefits:
  • Integer negation: -21000 == -21000, always
  • Int timestamps from monotonic_ns(): always strictly distinct
  • dict key: _bid_qty[21000] — exactly one entry, no collisions
```

The corresponding bid-side depth lookup is now exact:
```python
# Before: may find 0 or 2 entries for "the same" price
total = _bid_qty.get(210.00, 0)   # BUG: key may not match

# After: always exactly one entry
total = _bid_qty.get(21000, 0)    # always correct
```

### 11.1 Update module docstring comments

```python
#  _bids  max-heap: list of (-price_ticks, timestamp_ns, order)
#  _asks  min-heap: list of ( price_ticks, timestamp_ns, order)
#  _buy_stops  min-heap of (stop_price_ticks, timestamp_ns, order)
#  _sell_stops max-heap of (-stop_price_ticks, timestamp_ns, order)
#  _bid_qty / _ask_qty : dict[price_ticks, int]
#
# INVARIANT: All prices are int > 0. All timestamps are int ns from monotonic_ns().
# Heap keys are pure (int, int) tuples — no floats anywhere inside this class.
```

### 11.2 Update `__init__` type annotations

```python
self._bid_qty:  dict[int, int] = {}   # price_ticks → total visible resting qty
self._ask_qty:  dict[int, int] = {}   # (visible only — iceberg hidden reserve excluded)

# Three distinct "last price" fields — each serves a different purpose:
self.last_trade_price: Optional[int] = None   # ticks — updated on every fill;
                                               # used by _check_stops() to detect triggers
self.last_trade_qty:   Optional[int] = None
self.last_buy_price:   Optional[int] = None   # ticks — updated when aggressor was BUY
                                               # (a buyer swept into resting asks)
                                               # used by statistics and circuit breakers
self.last_sell_price:  Optional[int] = None   # ticks — updated when aggressor was SELL
                                               # (a seller swept into resting bids)
                                               # used by statistics and circuit breakers
```

The three reference price fields look similar but carry different information:
`last_trade_price` changes on every fill regardless of which side was aggressive.
`last_buy_price` only updates when a buy order aggressively sweeps into asks, recording
the direction of the last aggressive buying. `last_sell_price` only updates when a sell
order sweeps into bids. Together they let statistics and display tools show whether the
market has recently been driven by buyers or sellers — a useful short-term momentum signal.

### 11.3 Update `process()` signature

```python
def process(
    self, order: Order, *, match: bool = True, now: int | None = None
) -> tuple[list[Trade], list[Order]]:
    ...
    if now is None:
        now = monotonic_ns()    # int nanoseconds — see Section 5.3
```

The `OrderBook` should import the clock at the top of `engine/order_book.py`:
```python
from edumatcher.models.clock import monotonic_ns
```

### 11.4 Update `cancel_order()`

No changes to the method body — it operates on order IDs and boolean flags.
The call to `_deduct_qty_index` takes `order.price` which is now `int`, but
`_deduct_qty_index` itself uses the value as a dict key, which works identically
for int and float.

### 11.5 Update `amend_order()` signature

```python
def amend_order(
    self,
    order_id:  str,
    new_price: Optional[int] = None,   # ticks
    new_qty:   Optional[int] = None,
    now:       Optional[int] = None,   # nanoseconds
) -> tuple[Optional[Order], bool, str]:
    ...
    if now is None:
        now = monotonic_ns()

    ...
    if price <= 0:    # int comparison — exact
        return None, False, "Price must be positive"
```

The rest of `amend_order` operates on `order.price` (now `int`) and dict keys
(now `int`). No other body changes are needed.

### 11.6 Update `restore_stats()`

```python
def restore_stats(
    self,
    last_buy_price:  Optional[int],   # ticks
    last_sell_price: Optional[int],   # ticks
) -> None:
    self.last_buy_price  = last_buy_price
    self.last_sell_price = last_sell_price
```

### 11.7 Update `snapshot()`

`snapshot()` publishes to ZMQ subscribers. All prices must be converted to float
here — this is the **output boundary**:

```python
def snapshot(self) -> dict[str, Any]:
    from edumatcher.models.price import from_ticks
    bids: dict[int, dict[str, Any]] = {}
    asks: dict[int, dict[str, Any]] = {}

    for entry in self._bids:
        if not entry.valid:
            continue
        o = entry.order
        if o.status in (FILLED, CANCELLED, REJECTED, EXPIRED):
            continue
        price_ticks = o.price
        qty = (
            o.displayed_qty          # iceberg: show only the visible peak
            if o.order_type == OrderType.ICEBERG
            else o.remaining_qty
        )
        lvl = bids.setdefault(price_ticks, {"price": price_ticks, "qty": 0, "count": 0})
        lvl["qty"]   += qty
        lvl["count"] += 1

    # ... identical loop for asks ...

    return {
        "symbol": self.symbol,
        "bids": [
            {
                "price": from_ticks(lvl["price"], self.symbol),   # float for display
                "qty":   lvl["qty"],
                "count": lvl["count"],
            }
            for lvl in sorted(bids.values(), key=lambda x: -x["price"])
        ],
        "asks": [
            {
                "price": from_ticks(lvl["price"], self.symbol),   # float for display
                "qty":   lvl["qty"],
                "count": lvl["count"],
            }
            for lvl in sorted(asks.values(), key=lambda x: x["price"])
        ],
        "last_price": (
            from_ticks(self.last_trade_price, self.symbol)
            if self.last_trade_price is not None else None
        ),
        "last_qty":       self.last_trade_qty,
        "last_buy_price": (
            from_ticks(self.last_buy_price, self.symbol)
            if self.last_buy_price is not None else None
        ),
        "last_sell_price": (
            from_ticks(self.last_sell_price, self.symbol)
            if self.last_sell_price is not None else None
        ),
        # recent_trades: include the last 5 trades (not all 20 in the deque).
        # The deque holds 20 to serve reconnecting subscribers that need a longer
        # tail of history when they first connect. The live snapshot only needs 5
        # to keep the message size small. Trade.to_dict() calls from_ticks() on
        # the price field — this is the output boundary for trade prices.
        "recent_trades": [t.to_dict() for t in list(self.recent_trades)[-5:]],
        "tick_decimals": get_tick_decimals(self.symbol),  # so subscribers can sync
    }
```

**Three things to note about this snapshot:**

1. **Iceberg visible-only**: depth levels include only `displayed_qty` for icebergs,
   not the hidden reserve — the same count as `_bid_qty`. A subscriber sees 300
   shares at a level where an iceberg has 3,000 hidden. This is intentional.

2. **Spread and mid are not stored — they are derived by subscribers**: `OrderBook`
   has no `spread` or `mid_price` field. Subscribers compute them from the published
   float bid/ask prices: `spread = best_ask_price - best_bid_price`. If either side
   of the book is empty (`bids` or `asks` is an empty list), there is no spread and
   no mid. Subscribers must check for this and not divide by zero.

3. **Trade prices in `recent_trades`**: `Trade.to_dict()` must call `from_ticks()`
   on `trade.price` before serialising. This is the output boundary for trade prices.
   If `to_dict()` were to emit raw int ticks, subscribers would receive integers in
   a field they expect to be a float — a silent type mismatch.

### 11.8 Update `_sweep()` and `_sweep_iceberg()`

The `price_limit` and `now` parameters change type. The comparison logic is
structurally identical:

```python
def _sweep(
    self,
    aggressor:      Order,
    opposite_heap:  list[_HeapEntry],
    price_limit:    Optional[int],    # was Optional[float]
    trades:         list[Trade],
    events:         list[Order],
    now:            int,              # was float
) -> None:
    ...
    # Price comparisons — unchanged in structure, now exact integer arithmetic
    if _side == Side.BUY  and best.price > price_limit: break
    if _side == Side.SELL and best.price < price_limit: break
```

Same change for `_sweep_iceberg()` — `now: int`, price comparisons unchanged.

### 11.9 Update `_available_qty()`

```python
def _available_qty(
    self,
    heap:        list[_HeapEntry],
    price_limit: Optional[int],   # was Optional[float]
    side:        Side,
) -> int:
    qty_index = self._ask_qty if side == Side.BUY else self._bid_qty
    total = 0
    for price, qty in qty_index.items():
        if price_limit is not None:
            if side == Side.BUY  and price > price_limit: continue
            if side == Side.SELL and price < price_limit: continue
        total += qty
    return total
```

**Important limitation — iceberg orders:** `_bid_qty` and `_ask_qty` track only the
**visible** quantity of iceberg orders (the `displayed_qty` peak), not their full
`remaining_qty`. This means `_available_qty()` will undercount liquidity when
icebergs are present.

**Example:** A FOK BUY order for 2,500 shares arrives. At the best ask price there
is one regular limit order for 800 shares and one iceberg with 300 visible and 2,700
hidden. `_ask_qty[price]` = 1,100 (800 + 300 visible only). `_available_qty()`
returns 1,100 — less than 2,500 — so the FOK is rejected. But the iceberg actually
has enough to fill the order.

This is a deliberate simplification. Correct iceberg-aware FOK checking would
require scanning heap entries (O(n)) instead of the qty index (O(P)). For an
educational system, the visible-only approximation is acceptable. Note it in your
code comments so future readers understand the trade-off.

### 11.10 Update `_apply_fill()`

```python
def _apply_fill(
    self,
    aggressor:  Order,
    passive:    Order,
    fill_qty:   int,
    fill_price: int,      # was float — now int ticks
    trades:     list[Trade],
    events:     list[Order],
    now:        int,      # was float — now int nanoseconds
) -> None:
    ...
    # Decrement the price-level quantity index.
    # When the last order at a price level is consumed, delete the key entirely.
    # This keeps _bid_qty/_ask_qty compact so FOK checks and depth snapshots
    # only see price levels that actually have live orders.
    qty_index = self._bid_qty if passive.side == Side.BUY else self._ask_qty
    qty_index[fill_price] -= fill_qty
    if qty_index[fill_price] <= 0:
        del qty_index[fill_price]   # price level is now empty — remove it

    trade = Trade.create(
        symbol=self.symbol,
        buy_order_id=buy_order.id,
        sell_order_id=sell_order.id,
        buy_gateway_id=buy_order.gateway_id,
        sell_gateway_id=sell_order.gateway_id,
        price=fill_price,    # int ticks — passed straight through
        quantity=fill_qty,
        now=now,             # int nanoseconds — passed straight through
    )
    ...
    self.last_trade_price = fill_price    # int ticks

    # last_buy_price  = price of the most recent fill where a BUY order was aggressive
    #                   (a buyer swept into resting asks).
    #                   Used by statistics and circuit breakers to track upward pressure.
    # last_sell_price = price of the most recent fill where a SELL order was aggressive
    #                   (a seller swept into resting bids).
    #                   Used similarly to track downward pressure.
    # Note: last_trade_price is updated on every fill and is what _check_stops() uses.
    # last_buy_price and last_sell_price are directional and updated only on the
    # relevant aggressor side.
    if aggressor.side == Side.BUY:
        self.last_buy_price  = fill_price
    else:
        self.last_sell_price = fill_price
```

### 11.11 Update `_rest()` and `_reinsert_iceberg()`

The heap key becomes `(-int_price, int_timestamp)` — structurally identical, now
using integer types throughout:

```python
def _rest(self, order: Order) -> None:
    assert order.price is not None
    # INVARIANT: order.timestamp is strictly monotonically increasing thanks to
    # monotonic_ns() (models/clock.py). No two orders share a timestamp, so
    # price-time priority within a price level is always deterministic. See Section 5.3.
    qty = (
        order.displayed_qty
        if order.order_type == OrderType.ICEBERG
        else order.remaining_qty
    )
    if order.side == Side.BUY:
        key  = (-order.price, order.timestamp)   # int negation, int timestamp
        heap = self._bids
        self._bid_qty[order.price] = self._bid_qty.get(order.price, 0) + qty
    else:
        key  = (order.price, order.timestamp)
        heap = self._asks
        self._ask_qty[order.price] = self._ask_qty.get(order.price, 0) + qty
    entry = _HeapEntry(key=key, order=order)
    heapq.heappush(heap, entry)
    self._order_index[order.id] = order
    self._entry_index[order.id] = entry
```

The critical improvement: both elements of the heap key are now `int`. Heap
comparisons `(-price, timestamp) < (-price2, timestamp2)` use pure integer
arithmetic — exact, no floating-point edge cases, and ~5–10% faster per comparison.

### 11.12 Update `_check_stops()`

```python
def _check_stops(self, now: int) -> list[Order]:   # now: int nanoseconds
    if self.last_trade_price is None:
        return []
    ...
    # BUY STOPS — min-heap by stop_price. A buy stop fires when price rises to
    # or above the stop price. We break when the top entry has NOT triggered,
    # because if the lowest stop hasn't fired, none deeper in the heap have either.
    while self._buy_stops:
        entry = self._buy_stops[0]
        stop_price, _ = entry.key
        if self.last_trade_price < stop_price:   # int < int — exact
            break   # price hasn't reached this stop yet; none higher will have fired
        ...
        stop_order.timestamp = now    # int nanoseconds

    # SELL STOPS — max-heap by -stop_price. A sell stop fires when price falls to
    # or below the stop price. We break when the top entry (highest stop_price)
    # has NOT triggered, because if the highest stop hasn't fired, none lower will.
    while self._sell_stops:
        entry = self._sell_stops[0]
        neg_stop_price, _ = entry.key
        stop_price = -neg_stop_price              # undo the negation
        if self.last_trade_price > stop_price:   # int > int — exact
            break   # price hasn't fallen to this stop yet; none lower will have fired
        ...
```

**Why the break directions are opposite:**

- **Buy stops (min-heap, lowest trigger at top):** as the market price *rises*, the
  first stop to trigger is the one with the lowest trigger price (e.g., $152 is
  crossed before $158 as price moves up). The min-heap puts the lowest at `heap[0]`.
  We break when `last_trade_price < stop_price` — the current price hasn't yet
  reached even the lowest pending stop, so nothing has triggered.

- **Sell stops (max-heap, highest trigger at top):** as the market price *falls*, the
  first stop to trigger is the one with the *highest* trigger price (e.g., $148 is
  crossed before $142 as price moves down). The max-heap (via negation) puts the
  highest trigger at `heap[0]`. We break when `last_trade_price > stop_price` —
  the current price hasn't yet fallen to even the highest pending stop.

Both heaps follow the same principle: "the entry closest to the current price is
always at `heap[0]`, so a single peek and a single comparison tells us whether
anything has triggered." This is the key design insight that makes stop checking
O(1) in the common case.

### 11.13 Update `_check_trailing_stops()`

This is where integer arithmetic provides the clearest correctness win. Every
arithmetic operation is now exact integer subtraction and addition:

```python
def _check_trailing_stops(self, now: int) -> list[Order]:   # now: int ns
    if self.last_trade_price is None:
        return []
    trade_price = self.last_trade_price   # int ticks
    ...
    for order in self._trailing_stops:
        offset = order.trail_offset       # int ticks — guaranteed non-None

        if order.side == Side.SELL:
            candidate = trade_price - offset       # int - int = int, exact
            if candidate > order.stop_price:       # int > int, exact
                order.stop_price = candidate
            if trade_price <= order.stop_price:    # int <= int, exact
                order.order_type   = OrderType.MARKET
                order.trail_offset = None
                order.timestamp    = now           # int nanoseconds
                triggered.append(order)
                continue
        else:  # BUY trailing stop
            candidate = trade_price + offset       # int + int = int, exact
            if candidate < order.stop_price:
                order.stop_price = candidate
            if trade_price >= order.stop_price:
                order.order_type   = OrderType.MARKET
                order.trail_offset = None
                order.timestamp    = now
                triggered.append(order)
                continue

        still_active.append(order)
    self._trailing_stops = still_active
    return triggered
```

With 100 ratchet steps, old float code accumulates ~10⁻¹² error per step — small
but real. Integer code has zero accumulated error regardless of step count.

---

## 12. Phase 5 — `engine/auction.py`

### 12.1 Update `AuctionResult`

`AuctionResult` holds the outcome of an auction uncross calculation. Its fields:

- **`eq_price`** — the equilibrium price (int ticks) at which the maximum volume
  can trade; `None` if no buy and sell orders overlap at all.
- **`eq_qty`** — the total number of shares that will trade at the equilibrium price.
- **`surplus`** — how many shares are left over after the uncross. If 10,000 shares
  of buy orders and 8,000 shares of sell orders can all trade, the surplus is 2,000
  (the extra buy orders that found no match).
- **`imbalance_side`** — which side has the surplus (`"BUY"`, `"SELL"`, or `""`
  for a perfectly balanced auction).

```python
@dataclass
class AuctionResult:
    eq_price:       int | None   # ticks, or None when no crossable interest
    eq_qty:         int
    surplus:        int
    imbalance_side: str
```

### 12.2 Update `compute_equilibrium()`

All price variables become `int`. Replace the `float("inf")` sentinel with a
large integer. A **sentinel** is a special value used to mean "not yet set" or
"worst possible". `float("inf")` is positive infinity — any real number is less
than it, making it a useful initial value for "find the minimum". Since we are
switching to integer arithmetic, we use `10**18` instead, which is larger than any
realistic quantity of shares:

```python
def compute_equilibrium(book: "OrderBook") -> AuctionResult:
    bid_prices = sorted(book._bid_qty.keys(), reverse=True)   # list[int]
    ask_prices = sorted(book._ask_qty.keys())                  # list[int]

    if not bid_prices or not ask_prices:
        return AuctionResult(eq_price=None, eq_qty=0, surplus=0, imbalance_side="")

    cum_buy:  dict[int, int] = {}
    cum_sell: dict[int, int] = {}
    running = 0
    for p in bid_prices:
        running += book._bid_qty[p]
        cum_buy[p] = running
    running = 0
    for p in ask_prices:
        running += book._ask_qty[p]
        cum_sell[p] = running

    all_prices = sorted(set(bid_prices) | set(ask_prices))   # list[int]

    best_price:   int | None = None
    best_qty:     int = 0
    best_surplus: int = 10**18   # large int sentinel replaces float("inf")

    for price in all_prices:   # price: int ticks
        buy_qty = 0
        for bp in bid_prices:
            if bp >= price:
                buy_qty = cum_buy[bp]
            else:
                break
        sell_qty = 0
        for ap in ask_prices:
            if ap <= price:
                sell_qty = cum_sell[ap]
            else:
                break
        exec_qty = min(buy_qty, sell_qty)
        surplus  = abs(buy_qty - sell_qty)
        if exec_qty > best_qty or (exec_qty == best_qty and surplus < best_surplus):
            best_price   = price
            best_qty     = exec_qty
            best_surplus = surplus

    if best_price is None or best_qty == 0:
        return AuctionResult(eq_price=None, eq_qty=0, surplus=0, imbalance_side="")

    # Determine imbalance side at equilibrium
    buy_at_eq  = 0
    sell_at_eq = 0
    for bp in bid_prices:
        if bp >= best_price:
            buy_at_eq = cum_buy[bp]
        else:
            break
    for ap in ask_prices:
        if ap <= best_price:
            sell_at_eq = cum_sell[ap]
        else:
            break

    imbalance_side = (
        "BUY"  if buy_at_eq > sell_at_eq else
        "SELL" if sell_at_eq > buy_at_eq else
        ""
    )
    return AuctionResult(
        eq_price=best_price,    # int ticks
        eq_qty=best_qty,
        surplus=best_surplus,
        imbalance_side=imbalance_side,
    )
```

### 12.3 Update `execute_uncross()`

```python
def execute_uncross(
    book:     "OrderBook",
    eq_price: int,            # ticks
) -> tuple[list[Trade], list[Order]]:
    from edumatcher.models.clock import monotonic_ns
    trades: list[Trade] = []
    events: list[Order] = []
    now = monotonic_ns()      # int nanoseconds — see Section 5.3

    while True:
        best_bid = book._peek(book._bids)
        best_ask = book._peek(book._asks)
        if best_bid is None or best_ask is None:
            break
        if best_bid.price < eq_price: break   # int comparison — exact
        if best_ask.price > eq_price: break
        fill_qty = min(best_bid.remaining_qty, best_ask.remaining_qty)
        book._apply_fill(best_bid, best_ask, fill_qty, eq_price, trades, events, now)

    if trades:
        book.last_trade_price = eq_price   # int ticks
        book.last_trade_qty   = trades[-1].quantity

    return trades, events
```

---

## 13. Phase 6 — `engine/config_loader.py` and `engine_config.yaml`

### 13.1 Add `tick_decimals` to `SymbolConfig`

```python
@dataclass
class SymbolConfig:
    name:                str
    tick_decimals:       int = 2             # 1 tick = $0.01 by default
    last_buy_price:      Optional[float] = None   # float in YAML; converted to ticks in engine
    last_sell_price:     Optional[float] = None
    market_maker_orders: list[str] = field(default_factory=list)
```

**What are `last_buy_price` and `last_sell_price`?** These are the most recent
prices at which trades occurred on the buy and sell sides, from the previous trading
session. They seed the engine's reference prices on startup so that stop orders and
display tools have a reasonable starting point before any new trades happen. They
are stored as float in the YAML file (human-readable) and converted to int ticks
when the engine loads them.

**What are `market_maker_orders`?** These are the seed orders — see the Finance
Concepts Primer section on market makers. They are FIX-format strings that the
engine submits to itself at startup to ensure the book has initial liquidity.

### 13.2 Parse `tick_decimals` in `load_engine_config()`

```python
# In the symbol loading loop:
td = cfg.get("tick_decimals", 2)
if not isinstance(td, int) or not (0 <= td <= 8):
    raise ValueError(
        f"Symbol '{sym}': tick_decimals must be an integer 0–8, got {td!r}"
    )
sym_config = SymbolConfig(
    name=sym,
    tick_decimals=td,
    last_buy_price=lbp,    # float from YAML — engine converts to ticks
    last_sell_price=lsp,
    market_maker_orders=mm_orders,
)
```

### 13.3 Add `tick_decimals` to `engine_config.yaml`

All existing symbols use `tick_decimals: 2` (= $0.01 per tick). Add the field
to each symbol:

```yaml
symbols:
  MSFT:
    tick_decimals: 2
    last_buy_price:  415.00
    last_sell_price: 415.50
    market_maker_orders:
      - "NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=1000|PRICE=414.00|TIF=GTC"
      - "NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=500|PRICE=413.00|TIF=GTC"
      - "NEW|SYM=MSFT|SIDE=SELL|TYPE=LIMIT|QTY=1000|PRICE=416.00|TIF=GTC"
      - "NEW|SYM=MSFT|SIDE=SELL|TYPE=LIMIT|QTY=500|PRICE=417.00|TIF=GTC"

  AAPL:
    tick_decimals: 2
    last_buy_price:  209.50
    last_sell_price: 210.50
    market_maker_orders:
      - "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=2000|PRICE=209.00|TIF=GTC"
      - "NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=2000|PRICE=211.00|TIF=GTC"

  TSLA:
    tick_decimals: 2
    last_buy_price:  248.00
    last_sell_price: 249.00
    market_maker_orders:
      - "NEW|SYM=TSLA|SIDE=BUY|TYPE=LIMIT|QTY=500|PRICE=247.00|TIF=GTC"
      - "NEW|SYM=TSLA|SIDE=SELL|TYPE=LIMIT|QTY=500|PRICE=250.00|TIF=GTC"
```

---

## 14. Phase 7 — `engine/persistence.py`

GTC (Good-Till-Cancelled) orders survive engine restarts: the engine saves them on
shutdown and reloads them on the next startup. After this migration, the save/load
cycle works like this:

1. **Save** (`Order.to_dict()`): the order's internal `int` tick price is converted
   to `float` for JSON (e.g. `15030` → `150.30`).
2. **Load** (`Order.from_dict()`): the float price in JSON is converted back to
   `int` ticks (e.g. `150.30` → `15030`).

This round-trip is lossless as long as the price was a valid tick multiple to begin
with (which all accepted orders are, because the engine validates them on entry). A
price like `$150.30` with `tick_decimals=2` becomes exactly `15030` ticks, and back
to exactly `150.30` in display — no information is lost.

### 14.1 Update `save_book_stats()`

`last_buy_price` and `last_sell_price` are now `int` ticks in the book. Convert
to float for JSON:

```python
def save_book_stats(books: dict[str, Any], path: Path) -> None:
    from edumatcher.models.price import from_ticks
    stats: dict[str, dict[str, Any]] = {}
    for symbol, book in books.items():
        stats[symbol] = {
            "last_buy_price": (
                from_ticks(book.last_buy_price, symbol)
                if book.last_buy_price is not None else None
            ),
            "last_sell_price": (
                from_ticks(book.last_sell_price, symbol)
                if book.last_sell_price is not None else None
            ),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, indent=2))
```

No change to `load_book_stats()` — it returns the raw dict with float values, and
the caller in `engine/main.py` converts to ticks (see Phase 8, Section 15.2).

### 14.2 Add format versioning to GTC files (required by Section 5.6)

Update `save_gtc_orders()` to wrap the order list in a versioned envelope dict:

```python
def save_gtc_orders(orders: list[Order], path: Path) -> None:
    gtc = [
        o.to_dict()
        for o in orders
        if o.tif == TIF.GTC and o.status in (OrderStatus.NEW, OrderStatus.PARTIAL)
    ]
    output = {"format_version": 2, "orders": gtc}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2))
```

Update `load_gtc_orders()` to check the version before parsing. The `isinstance`
check handles the case where an old (pre-migration) file is accidentally loaded:

```python
def load_gtc_orders(path: Path) -> list[Order]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    # Old format was a plain list — detect and refuse
    if isinstance(raw, list):
        raise RuntimeError(
            f"{path} is in the pre-migration format (a plain list). "
            f"Delete this file and restart the engine."
        )
    version = raw.get("format_version")
    if version != 2:
        raise RuntimeError(
            f"Unrecognised format_version {version!r} in {path}. "
            f"Delete this file and restart the engine."
        )
    return [Order.from_dict(d) for d in raw.get("orders", [])]
```

Apply the same versioning pattern to `save_gtc_combos()` / `load_gtc_combos()`.

`book_stats.json` does not need versioning — it is always fully overwritten on
clean shutdown, so an old-format file can only exist if the engine never shut down
cleanly. In that case, the absence of the file is handled gracefully by the existing
code (it falls back to YAML config values).

---

## 15. Phase 8 — `engine/main.py`

This file has the most places to update — a **call-site** is any line of code that
calls a function. For example, when the meaning of `Trade.create()`'s `price`
parameter changes from a float price to an integer tick count, every place in this
file that calls `Trade.create()` is a call-site that must be checked to ensure it
now passes ticks rather than a float. Work through the sections below in the order
shown; each section depends on the previous one being in place.

### 15.1 Register tick decimals at startup

The very first thing `_load_config()` must do for each symbol is register its tick
precision with `price.py`. This must happen before any order parsing:

```python
from edumatcher.models.price import register_tick_decimals, to_ticks

def _load_config(self) -> None:
    ...
    for sym, sym_cfg in self._engine_config.symbols.items():
        register_tick_decimals(sym, sym_cfg.tick_decimals)   # ← first
        self._allowed_symbols.add(sym)
        ...
```

### 15.2 Convert seeded last prices to ticks

Book stats are stored as float in JSON and YAML. Convert on load:

```python
from edumatcher.models.price import to_ticks

# After registering tick_decimals for the symbol:
lbp = persisted.get("last_buy_price") or sym_cfg.last_buy_price
lsp = persisted.get("last_sell_price") or sym_cfg.last_sell_price

book.restore_stats(
    last_buy_price  = to_ticks(float(lbp),  sym) if lbp  is not None else None,
    last_sell_price = to_ticks(float(lsp), sym) if lsp is not None else None,
)
```

### 15.3 Update the market-maker order parser

The engine parses FIX-like strings for seed orders. Convert float prices to ticks
immediately after parsing:

```python
from edumatcher.models.price import to_ticks

# In the MM order parsing section:
raw_price = float(kv["PRICE"]) if "PRICE" in kv else None
raw_stop  = float(kv["STOP"])  if "STOP"  in kv else None

price      = to_ticks(raw_price, sym) if raw_price is not None else None
stop_price = to_ticks(raw_stop,  sym) if raw_stop  is not None else None

order = Order.create(
    symbol=sym,
    ...
    price=price,        # int ticks
    stop_price=stop_price,
)
```

### 15.4 Update `_handle_new_order()`

The gateway sends float prices in JSON. Convert at the engine input boundary:

```python
def _handle_new_order(self, payload: dict[str, Any]) -> None:
    from edumatcher.models.price import to_ticks
    ...
    symbol = str(payload.get("symbol", "")).upper()
    ...
    raw_price = payload.get("price")
    raw_stop  = payload.get("stop_price")
    raw_trail = payload.get("trail_offset")

    order = Order.create(
        symbol=symbol,
        side=Side(payload["side"]),
        order_type=OrderType(payload["order_type"]),
        quantity=int(payload["quantity"]),
        gateway_id=payload["gateway_id"],
        tif=TIF(payload.get("tif", TIF.DAY.value)),
        price=      to_ticks(raw_price, symbol) if raw_price is not None else None,
        stop_price= to_ticks(raw_stop,  symbol) if raw_stop  is not None else None,
        trail_offset=to_ticks(raw_trail, symbol) if raw_trail is not None else None,
        visible_qty=int(payload["visible_qty"]) if payload.get("visible_qty") else None,
        smp_action=SmpAction(payload.get("smp_action", SmpAction.NONE.value)),
        oco_group_id=payload.get("oco_group_id"),
    )

    # Validate every supplied price per the v6 rules (Sections 5.2 and 5.4):
    # check_tick_aligned() REJECTS misaligned prices and zero/negative prices,
    # returning a non-empty error message. (trail_offset is a distance, not a
    # price level, so it is checked only for positivity, not tick alignment.)
    for field_name, raw_val in (
        ("price", raw_price),
        ("stop_price", raw_stop),
    ):
        if raw_val is not None:
            _, err = check_tick_aligned(float(raw_val), symbol)
            if err:
                self.pub_sock.send_multipart(
                    make_ack_msg(order.gateway_id, order.id, False,
                                 f"{field_name}: {err}")
                )
                return

    if raw_trail is not None and order.trail_offset is not None and order.trail_offset <= 0:
        self.pub_sock.send_multipart(
            make_ack_msg(order.gateway_id, order.id, False,
                         f"trail_offset must be positive, got {raw_trail}")
        )
        return
    ...
    # TRAILING_STOP: if the gateway did not supply an explicit stop_price,
    # calculate it from the last trade price in the book.
    # A trailing stop must know where the market currently is to set its initial
    # trigger level. If no trades have happened yet (book.last_trade_price is None),
    # we cannot place the stop — reject it with an error message.
    if order.order_type == OrderType.TRAILING_STOP and order.stop_price is None:
        if book.last_trade_price is None:
            # No trades yet in this session — cannot initialise trailing stop
            order.status = OrderStatus.REJECTED
            self.pub_sock.send_multipart(
                make_ack_msg(order.gateway_id, order.id, False,
                             "No last trade price available for trailing stop initialisation")
            )
            return
        else:
            if order.side == Side.SELL:
                # Sell trailing stop: start below the current market price
                order.stop_price = book.last_trade_price - order.trail_offset
            else:
                # Buy trailing stop: start above the current market price
                order.stop_price = book.last_trade_price + order.trail_offset
            # Both operands are int ticks — exact integer arithmetic, no drift

    now = monotonic_ns()    # int nanoseconds — see Section 5.3
    trades, events = book.process(order, match=do_match, now=now)
    ...
```

`check_tick_aligned()` and `make_ack_msg` must be imported at the top of
`engine/main.py`:
```python
from edumatcher.models.price import to_ticks, from_ticks, check_tick_aligned
```

### 15.5 Update fill event publication

When a trade executes, the engine sends **fill events** to the gateways involved —
notifications telling each participant how much of their order was filled, at what
price, and how much remains. `book.last_trade_price` is now `int` ticks; convert to
float before publishing so subscribers receive human-readable prices:

```python
from edumatcher.models.price import from_ticks

# In the fill events loop:
_dumps({
    "order_id":      evt.id,
    "fill_qty":      evt.quantity - evt.remaining_qty,
    "fill_price":    (
        from_ticks(book.last_trade_price, evt.symbol)
        if book.last_trade_price is not None else None
    ),
    "remaining_qty": evt.remaining_qty,
    "status":        evt.status.value,
    "symbol":        evt.symbol,
    "side":          evt.side.value,
    "order_type":    evt.order_type.value,
    "qty":           evt.quantity,
    "price": (
        from_ticks(evt.price, evt.symbol)
        if evt.price is not None else None
    ),
})
```

### 15.6 Update `time.time()` calls

Search for `time.time()` in `engine/main.py` — there are exactly two occurrences,
both in order-handling functions. Change each one to `monotonic_ns()` (not
`time.time_ns()` — see Section 5.3 for why the monotonic wrapper is required):

```python
# At the top of engine/main.py:
from edumatcher.models.clock import monotonic_ns

# In _handle_new_order():
now = time.time()     →     now = monotonic_ns()

# In _handle_amend_order():
now = time.time()     →     now = monotonic_ns()
```

To find them quickly: `grep -n "time\.time()" src/edumatcher/engine/main.py`

The `time.monotonic()` call in `_flush_snapshots()` is for throttle timing (elapsed
wall-clock seconds between snapshot flushes), not an epoch timestamp — leave it
as `float`. It controls how often snapshots are sent, not when events happened.
Note that `time.monotonic()` (elapsed seconds, a float) and `monotonic_ns()` (our
strictly-increasing nanosecond timestamp wrapper) are different functions for
different purposes — do not confuse them.

### 15.7 Update `_handle_amend_order()`

**Amending** an order means changing its price or quantity after it has been placed
in the book. Some exchanges call this a "modify" or "replace" operation. The engine
receives an amend request with the order ID and the new values.

The amend payload carries a float price from the gateway (because the gateway works
in the human-readable float world). Convert to ticks before passing to the order
book. Then convert back to float when publishing the amended price in the response
message so the gateway can display it correctly:

```python
def _handle_amend_order(self, payload: dict[str, Any]) -> None:
    from edumatcher.models.price import to_ticks, from_ticks
    ...
    raw_price = payload.get("price")   # float from gateway, or None
    new_price_ticks = (
        to_ticks(float(raw_price), symbol)
        if raw_price is not None else None
    )
    ok, priority_reset, err = book.amend_order(
        order_id=order_id,
        new_price=new_price_ticks,   # int ticks — or None if not amending price
        new_qty=new_qty,
        now=monotonic_ns(),          # int nanoseconds — see Section 5.3
    )
    ...
    # When publishing the amended order's price back to the gateway:
    # Convert ticks back to float so the gateway can display it
    amended_price_float = (
        from_ticks(amended.price, amended.symbol)
        if amended.price is not None else None
    )
```

### 15.8 Update auction call-sites

`AuctionResult.eq_price` is now `int` ticks. Convert to float for publication:

```python
from edumatcher.models.price import from_ticks

if result.eq_price is not None and result.eq_qty > 0:
    trades, events = execute_uncross(book, result.eq_price)  # eq_price: int ticks
    ...
    # In fill event publication:
    "fill_price": from_ticks(result.eq_price, symbol),   # float for subscribers
    ...
    # In auction result message:
    "eq_price": from_ticks(result.eq_price, symbol),     # float for display
```

### 15.9 Add `tick_decimals` to book snapshot messages

Subscribers that receive book snapshots need the tick precision to correctly
re-convert if needed. Add it to the snapshot dict in `_flush_snapshots()`:

```python
from edumatcher.models.price import get_tick_decimals

snapshot = book.snapshot()
snapshot["tick_decimals"] = get_tick_decimals(symbol)
self.pub_sock.send_multipart(make_book_msg(symbol, snapshot))
```

### 15.10 Combo and OCO leg prices

**Combo orders** (see Finance Concepts Primer) decompose into individual child
orders — one per instrument leg. Leg prices are already stored as int ticks in
`ComboLeg.price` (updated in Phase 3), so they pass directly to `Order.create()`
with no conversion:

```python
child = Order.create(
    symbol=leg.symbol,
    side=leg.side,
    order_type=leg.order_type,
    quantity=leg.quantity,
    gateway_id=combo.gateway_id,
    tif=combo.tif,
    price=leg.price,           # int ticks — already converted in Phase 3
    stop_price=leg.stop_price, # int ticks — already converted in Phase 3
)
```

**OCO (One-Cancels-Other) orders** are submitted by the gateway as JSON with float
prices. Convert at the engine input boundary as you read each leg:

```python
from edumatcher.models.price import to_ticks

for raw_leg in [raw.get("leg1"), raw.get("leg2")]:
    _p  = raw_leg.get("price")
    _sp = raw_leg.get("stop_price")
    leg = ComboLeg(
        ...
        price=      to_ticks(_p,  symbol) if _p  is not None else None,
        stop_price= to_ticks(_sp, symbol) if _sp is not None else None,
    )
```

---

## 16. Phase 9 — `models/message.py`

`message.py` provides factory functions that build ZMQ messages — the packets the
engine sends to subscribers. When the engine records a fill internally, prices are
int ticks. But the fill message that goes over the network to the gateway needs
float prices so the terminal can display `"filled at $150.30"` rather than
`"filled at 15030"`.

The message functions therefore accept int ticks as input and call `from_ticks()`
before encoding the JSON payload. This conversion happens at the output boundary.

### 16.1 Update `make_fill_msg()`

```python
def make_fill_msg(
    gateway_id: str,
    order_id:   str,
    fill_qty:   int,
    fill_price: int,           # was float — now int ticks
    remaining:  int,
    status:     str,
    symbol:     str,
    side:       str,
    order_type: str,
    qty:        int,
    price:      Optional[int], # was Optional[float] — now int ticks
) -> list[bytes]:
    from edumatcher.models.price import from_ticks
    topic = f"order.fill.{gateway_id}"
    return encode(topic, {
        "order_id":      order_id,
        "fill_qty":      fill_qty,
        "fill_price":    from_ticks(fill_price, symbol) if fill_price is not None else None,
        "remaining_qty": remaining,
        "status":        status,
        "symbol":        symbol,
        "side":          side,
        "order_type":    order_type,
        "qty":           qty,
        "price":         from_ticks(price, symbol) if price is not None else None,
    })
```

### 16.2 Update `make_auction_result_msg()`

```python
def make_auction_result_msg(
    symbol:       str,
    eq_price:     int | None,   # was float | None — now int ticks
    eq_qty:       int,
    surplus:      int,
    imbalance_side: str,
    trades_count: int,
) -> list[bytes]:
    from edumatcher.models.price import from_ticks
    return encode("auction.result", {
        "symbol":          symbol,
        "eq_price":        from_ticks(eq_price, symbol) if eq_price is not None else None,
        "eq_qty":          eq_qty,
        "surplus":         surplus,
        "imbalance_side":  imbalance_side,
        "trades_count":    trades_count,
    })
```

### 16.3 Update `make_ack_msg()` where it includes order prices

If `make_ack_msg()` encodes `order.price` or `order.stop_price`, convert to float:

```python
if order is not None:
    from edumatcher.models.price import from_ticks
    payload["price"] = (
        from_ticks(order.price, order.symbol)
        if order.price is not None else None
    )
```

---

## 17. Phase 10 — `gateway/main.py`

The gateway is the user-facing input boundary. It parses float prices typed by
the user and sends them as floats in the JSON payload. The engine converts to ticks
on receipt. **The gateway never calls `to_ticks()`.**

### 17.1 Order command parser — no change to price parsing

```python
# These stay as float — the engine is responsible for conversion:
price        = float(kv["PRICE"]) if "PRICE" in kv else None
stop_price   = float(kv["STOP"])  if "STOP"  in kv else None
trail_offset = float(kv["TRAIL"]) if "TRAIL" in kv else None

payload = {
    "price":        price,        # float — engine converts to ticks
    "stop_price":   stop_price,
    "trail_offset": trail_offset,
    ...
}
```

### 17.2 Update timestamp display

The gateway receives `timestamp` fields in order status messages. They are now `int`
nanoseconds. Add a module-level helper and use it wherever timestamps are formatted:

```python
# Add near the top of gateway/main.py:
def _fmt_timestamp(ts_ns: int) -> str:
    """Format a nanosecond int timestamp as HH:MM:SS.

    All timestamps in the migrated system are int nanoseconds, so we divide
    by 1_000_000_000 to convert to the float seconds that datetime expects.
    """
    from datetime import datetime
    return datetime.fromtimestamp(ts_ns / 1_000_000_000).strftime("%H:%M:%S")

# Replace:
ts = datetime.fromtimestamp(od["timestamp"]).strftime("%H:%M:%S")
# With:
ts = _fmt_timestamp(od["timestamp"])
```

### 17.3 Fill and amend display — no change needed

Fill messages from the engine already carry float prices (converted before
publishing). The gateway displays them with the existing `:.4f` format strings.

---

## 18. Phase 11 — `clearing/main.py`

The clearing process (see Finance Concepts Primer) subscribes to `trade.executed`
messages from the engine. It tracks each participant's position (shares held) and
P&L (profit and loss), and writes a record to `clearing_report.csv`.

After Phase 8, fill messages from the engine carry **float prices** (the engine
calls `from_ticks()` before publishing via `Trade.to_dict()`). The `PositionRecord`
class computes P&L using standard float arithmetic, which is fine at display
precision — no tick conversion is needed here.

### 18.1 Update timestamp formatting

The only required code change is timestamp formatting:

```python
# Add near the top of clearing/main.py:
def _fmt_ts(ts_ns: int) -> datetime:
    """Convert nanosecond timestamp to UTC datetime."""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts_ns / 1_000_000_000, timezone.utc)

# Replace every occurrence of:
datetime.fromtimestamp(trade.timestamp, timezone.utc).isoformat()
datetime.fromtimestamp(trade.timestamp, timezone.utc).strftime(...)
# With:
_fmt_ts(trade.timestamp).isoformat()
_fmt_ts(trade.timestamp).strftime(...)
```

There are two occurrences in `clearing/main.py`:
1. In `_record_trade()` — the CSV timestamp column
2. In `_receive()` — the console print

### 18.2 Add tick registry synchronisation (from Section 5.8)

If clearing ever needs to call `from_ticks()` or `to_ticks()` directly (for
example in a future feature that logs tick-precise prices internally), it must first
register the symbol's tick size. Add this to the book snapshot handler:

```python
def _handle_book_snapshot(self, payload: dict[str, Any]) -> None:
    """Called whenever the engine publishes a book.{symbol} snapshot."""
    symbol = payload.get("symbol", "")
    tick_decimals = payload.get("tick_decimals")
    if tick_decimals is not None:
        from edumatcher.models.price import register_tick_decimals
        register_tick_decimals(symbol, int(tick_decimals))
    # ... rest of handler
```

If clearing does not currently subscribe to book snapshots, this step can be deferred
until it does. The fallback `DEFAULT_TICK_DECIMALS = 2` will be used in the meantime.

---

## 19. Phase 12 — `stats/main.py`

The stats process records market data history in a SQLite database. For each symbol
and trading day it stores **OHLCV**: Open (first trade price), High (highest trade
price), Low (lowest), Close (last trade price), and Volume (total shares traded).
It also stores a mid-price snapshot every 15 minutes.

SQLite stores prices as `REAL` — its floating-point type. Since the stats process
receives already-converted float prices from ZMQ messages (the engine converts
before publishing), the SQLite schema requires no change. Only timestamp handling
changes here.

```python
# Add near the top of stats/main.py:
def _ns_to_dt(ts: int) -> datetime:
    """Convert nanosecond int timestamp to UTC datetime."""
    return datetime.fromtimestamp(ts / 1_000_000_000, timezone.utc)

# Replace every occurrence of:
datetime.fromtimestamp(payload_ts, timezone.utc).isoformat(...)
# With:
_ns_to_dt(payload_ts).isoformat(...)
```

There are two occurrences in `stats/main.py`:
1. In `_upsert_daily_stats()` — reading `trade["timestamp"]`
2. In the snapshot interval check — reading book snapshot timestamps if stored

---

## 20. Phase 13 — `viewer/main.py` and `board/main.py`

The viewer and board are display processes that show the live order book to users.
They receive **book snapshots** — periodic JSON messages from the engine containing
the current state of all resting orders, grouped by price level, plus recent trade
history. The engine's `snapshot()` method (updated in Phase 4) already converts all
prices to float before publishing, so these processes receive float values and
display them directly with no tick conversion needed.

The only required change is timestamp formatting for recent trades in the snapshot:

**`viewer/main.py`:**

```python
# Add helper:
def _ns_to_time_str(ts: int) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(ts / 1_000_000_000).strftime("%H:%M:%S.%f")[:-3]

# Replace:
ts = datetime.fromtimestamp(tr["timestamp"]).strftime("%H:%M:%S.%f")[:-3]
# With:
ts = _ns_to_time_str(tr["timestamp"])
```

**`board/main.py`:**

```python
# Add the same helper at the top of board/main.py:
def _ns_to_time_str(ts: int) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(ts / 1_000_000_000).strftime("%H:%M:%S.%f")[:-3]

# Apply wherever tr["timestamp"] or similar trade timestamps are formatted.
# Search the file for datetime.fromtimestamp( to find all occurrences.
```

---

## 21. Phase 14 — `ticker/main.py`

The ticker reads prices from SQLite (`REAL` columns — already float) and from
book snapshot messages (already float). No price changes needed.

If the ticker reads `timestamp` fields from ZMQ message payloads, apply the same
nanosecond-to-seconds conversion:

```python
def _ns_to_time_str(ts: int) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(ts / 1_000_000_000).strftime("%H:%M:%S")
```

The ticker's `time.monotonic()` calls for display refresh intervals are unaffected.

---

## 22. Phase 15 — `ai_trader/main.py` and `ai_trader/personality.py`

The AI trader is a simulated market participant that reads book snapshots and submits
orders through the gateway — it lives entirely in the float world, just like a real
human user would.

**`personality.py` — no changes.** The `tick_size: float = 0.01` field is used when
computing prices for orders before submission (e.g. `price = mid_price - 2 * tick_size`).
This float arithmetic is fine here because the result goes through the gateway as a
float, which the engine then converts to ticks via `to_ticks()`. The tick size field
is a display-world concept.

**`ai_trader/main.py` — timestamp handling only.** The existing `_as_float()` helper
converts price values from book snapshots to Python floats for arithmetic. Since book
snapshots already carry float prices (the engine converts before publishing), this
helper continues to work without any change. Do not apply `_as_float()` to timestamp
fields — timestamps from messages are integer nanoseconds and need the
`_ns_to_time_str()` pattern from Phase 13 if you want to display them.

The timing fields (`reject_window_sec`, `stale_data_sec`, etc.) use `time.monotonic()`
to measure how many seconds have elapsed since a reference point — for example,
"ignore order acks older than 5 seconds". `time.monotonic()` returns a float of
elapsed seconds, which is correct for duration measurement. It does not return an
epoch timestamp and does not need to change.

---

## 23. Tests

Run the full existing test suite after Phase 4 to catch any regressions in the
matching engine before touching subscriber processes.

### Test Matrix

The following table maps every design rule from Section 5 to a specific test.
Write the test before implementing the feature — this forces you to understand
exactly what success looks like before writing code.

| Test file | Test name | What it verifies | Expected result |
|---|---|---|---|
| `test_price.py` | `test_to_ticks_simple` | Basic conversion | `to_ticks(150.30, "AAPL") == 15030` |
| `test_price.py` | `test_to_ticks_absorbs_float_error` | `round()` fixes IEEE 754 | `to_ticks(100.1+0.2, "AAPL") == 10030` |
| `test_price.py` | `test_round_trip` | Float→ticks→float is lossless | `from_ticks(to_ticks(p, s), s) ≈ p` for valid prices |
| `test_price.py` | `test_tick_size_immutable` | `register_tick_decimals` rule | Second call with different value → `RuntimeError` |
| `test_tick_alignment.py` | `test_aligned_price_accepted` | Valid price passes check | `check_tick_aligned(150.30, "AAPL")` → no error |
| `test_tick_alignment.py` | `test_float_representation_error_is_tolerated` | 1% tolerance absorbs IEEE 754 | `100.1 + 0.2` accepted as 10030 — tiny float error is within tolerance |
| `test_tick_alignment.py` | `test_misaligned_price_rejected` | v6 rejection policy | `check_tick_aligned(150.305, "AAPL")` → error message with nearest valid prices |
| `test_tick_alignment.py` | `test_zero_price_rejected` | Positive price rule | `check_tick_aligned(0.0, "AAPL")` → error message |
| `test_tick_alignment.py` | `test_negative_price_rejected` | Positive price rule | `check_tick_aligned(-1.0, "AAPL")` → error message |
| `test_tick_alignment.py` | `test_whole_dollar_symbol_accepts_whole_dollar` | Tick size=1 works correctly | `check_tick_aligned(150.0, "FUT")` → no error |
| `test_tick_alignment.py` | `test_whole_dollar_symbol_rejects_cents` | Misalignment for tick_decimals=0 | `check_tick_aligned(150.50, "FUT")` → error message |
| `test_clock.py` | `test_strictly_increasing` | `monotonic_ns()` guarantee | 10,000 consecutive calls → all strictly ascending |
| `test_clock.py` | `test_all_distinct` | No duplicate timestamps | 1,000 calls → all values unique |
| `test_clock.py` | `test_handles_clock_regression` | Clock-backward protection | If `time.time_ns` returns a smaller value → `monotonic_ns` still increments |
| `test_clock.py` | `test_handles_same_value` | Clock-stall protection | If `time.time_ns` returns the same value twice → two distinct results |
| `test_order_timestamps.py` | `test_timestamp_is_int` | Timestamp type | `isinstance(order.timestamp, int)` |
| `test_order_timestamps.py` | `test_consecutive_timestamps_distinct` | No timestamp collisions | Consecutive `Order.create()` → distinct timestamps |
| `test_order_timestamps.py` | `test_price_is_int_ticks` | Price type | `isinstance(order.price, int)` |
| `test_order_timestamps.py` | `test_serialization_round_trip` | Dict round-trip | `Order.from_dict(order.to_dict()).price == order.price` |
| `test_matching_integer_prices.py` | `test_same_price_always_matches` | No float equality bug | Orders at same float price → 1 trade |
| `test_matching_integer_prices.py` | `test_price_level_index_no_duplicate_keys` | No dict key collision | Two orders at same price → 1 key in `_bid_qty` |
| `test_trailing_stop_integer_ratchet.py` | `test_ratchet_exact_after_many_steps` | No trailing stop drift | 100 ratchet steps → exact final stop price |
| `test_trailing_stop_integer_ratchet.py` | `test_ratchet_does_not_move_down` | Stop only ratchets up | Price falls after ratchet → stop price unchanged |
| `test_persistence.py` | `test_format_version_missing_rejected` | Versioning rule | File with no `format_version` → `RuntimeError` |
| `test_persistence.py` | `test_format_version_wrong_rejected` | Versioning rule | File with `format_version=1` → `RuntimeError` |
| `test_persistence.py` | `test_format_version_2_accepted` | Happy path | File with `format_version=2` → loaded successfully |
| `test_persistence.py` | `test_plain_list_rejected` | Pre-migration format | Plain JSON list → `RuntimeError` |
| `test_combo.py` | `test_combo_leg_uses_own_symbol_tick` | Per-leg validation | AAPL leg uses `tick_decimals("AAPL")`, MSFT leg uses `tick_decimals("MSFT")` |
| `test_combo.py` | `test_combo_misaligned_leg_rejected` | Combo validation | One misaligned leg → entire combo rejected |
| `test_snapshot.py` | `test_snapshot_prices_are_float` | Output boundary | All prices in `snapshot()` are `float`, not `int` |
| `test_snapshot.py` | `test_snapshot_includes_tick_decimals` | Cross-process sync | `snapshot["tick_decimals"]` is present and correct |

Worked, copy-ready examples for the first six files (`test_price.py`,
`test_tick_alignment.py`, `test_clock.py`, `test_order_timestamps.py`,
`test_trailing_stop_integer_ratchet.py`, and `test_matching_integer_prices.py`)
appear below. The remaining three files in the matrix — `test_persistence.py`,
`test_combo.py`, and `test_snapshot.py` — are specified here as targets but left
for you to write, following the same patterns; the rules they test are fully
described in Sections 5.5, 5.6, and 11.7 respectively.

### Order Book Invariant Checklist

Assert these properties in any test that creates an `OrderBook` and processes orders.
If any assertion fails, the tick migration was not applied correctly.

```python
def assert_book_invariants(book: OrderBook, symbol: str) -> None:
    """
    Call this after every operation in tests that use OrderBook directly.
    If any assertion fails, the tick migration has a bug.
    """
    # 1. All prices in heap entries are positive integers
    for entry in book._bids:
        if entry.valid:
            o = entry.order
            assert isinstance(o.price, int), f"bid price is {type(o.price)}, not int"
            assert o.price > 0,              f"bid price is {o.price}, not positive"

    for entry in book._asks:
        if entry.valid:
            o = entry.order
            assert isinstance(o.price, int), f"ask price is {type(o.price)}, not int"
            assert o.price > 0,              f"ask price is {o.price}, not positive"

    # 2. All _bid_qty / _ask_qty keys are integers
    for key in book._bid_qty:
        assert isinstance(key, int), f"_bid_qty key is {type(key)}, not int"
    for key in book._ask_qty:
        assert isinstance(key, int), f"_ask_qty key is {type(key)}, not int"

    # 3. last_trade_price is int or None
    if book.last_trade_price is not None:
        assert isinstance(book.last_trade_price, int), (
            f"last_trade_price is {type(book.last_trade_price)}, not int"
        )
        assert book.last_trade_price > 0, (
            f"last_trade_price is {book.last_trade_price}, not positive"
        )

    # 4. All order timestamps in the book are positive integers
    for entry in book._bids:
        if entry.valid:
            assert isinstance(entry.order.timestamp, int), "bid timestamp not int"
            assert entry.order.timestamp > 0,              "bid timestamp not positive"
    for entry in book._asks:
        if entry.valid:
            assert isinstance(entry.order.timestamp, int), "ask timestamp not int"
            assert entry.order.timestamp > 0,              "ask timestamp not positive"

    # 5. No float keys in the heap tuples
    for entry in book._bids:
        key = entry.key
        assert all(isinstance(k, int) for k in key), f"bid heap key contains float: {key}"
    for entry in book._asks:
        key = entry.key
        assert all(isinstance(k, int) for k in key), f"ask heap key contains float: {key}"
```

### New test file: `tests/test_tick_alignment.py`

```python
"""
Tests for the tick alignment validation rule introduced in v6.

v6 policy: misaligned prices are REJECTED, not rounded.
"""
import pytest
from edumatcher.models.price import (
    register_tick_decimals, check_tick_aligned, from_ticks
)


def setup_function():
    register_tick_decimals("AAPL", 2)   # tick size = $0.01
    register_tick_decimals("FUT",  0)   # tick size = $1.00


def test_aligned_price_accepted():
    ticks, err = check_tick_aligned(150.30, "AAPL")
    assert err == "", f"Expected no error, got: {err}"
    assert ticks == 15030


def test_float_representation_error_is_tolerated():
    # 100.1 + 0.2 = 100.30000000000001 in IEEE 754
    # This IS an aligned price (100.30 is a multiple of 0.01)
    # The tiny error is within the 1% tolerance
    ticks, err = check_tick_aligned(100.1 + 0.2, "AAPL")
    assert err == "", f"Should accept representable float error: {err}"
    assert ticks == 10030


def test_misaligned_price_rejected():
    """150.305 is NOT a multiple of 0.01 — halfway between 150.30 and 150.31."""
    ticks, err = check_tick_aligned(150.305, "AAPL")
    assert err != "", "Expected rejection of misaligned price"
    assert "150.30" in err or "150.31" in err, (
        "Error message should show nearest valid prices"
    )


def test_zero_price_rejected():
    ticks, err = check_tick_aligned(0.0, "AAPL")
    assert err != "", "Expected rejection of zero price"
    assert "positive" in err.lower()


def test_negative_price_rejected():
    ticks, err = check_tick_aligned(-1.00, "AAPL")
    assert err != "", "Expected rejection of negative price"


def test_whole_dollar_symbol_accepts_whole_dollar():
    """FUT has tick_decimals=0, so only whole dollar prices are valid."""
    ticks, err = check_tick_aligned(150.0, "FUT")
    assert err == ""
    assert ticks == 150


def test_whole_dollar_symbol_rejects_cents():
    """FUT does not trade at fractional dollar prices."""
    ticks, err = check_tick_aligned(150.50, "FUT")
    assert err != "", "Expected rejection of $150.50 for whole-dollar symbol"
```

### New test file: `tests/test_clock.py`

```python
"""
Tests for the monotonic nanosecond clock in models/clock.py.
"""
from edumatcher.models.clock import monotonic_ns
from unittest.mock import patch


def test_strictly_increasing():
    """10,000 consecutive calls must all return strictly increasing values."""
    values = [monotonic_ns() for _ in range(10_000)]
    for i in range(1, len(values)):
        assert values[i] > values[i - 1], (
            f"Timestamp regressed at position {i}: "
            f"{values[i-1]} → {values[i]}"
        )


def test_all_distinct():
    """All timestamps must be unique."""
    values = [monotonic_ns() for _ in range(1_000)]
    assert len(set(values)) == len(values), "Duplicate timestamps found"


def test_handles_clock_regression():
    """
    Simulate a clock going backward (NTP adjustment).
    monotonic_ns() must still return an increasing value.
    """
    import edumatcher.models.clock as clk
    # Force a known last value
    clk._last_ns = 1_000_000
    # Simulate time.time_ns() returning a value BEFORE _last_ns
    with patch("time.time_ns", return_value=999_999):
        result = monotonic_ns()
    # Result must be _last_ns + 1, not the regressed clock value
    assert result == 1_000_001, (
        f"Expected 1_000_001 after regression, got {result}"
    )


def test_handles_same_value():
    """
    Simulate time.time_ns() returning the same value twice (clock stall).
    Both calls must return different values.
    """
    import edumatcher.models.clock as clk
    clk._last_ns = 0
    with patch("time.time_ns", return_value=5_000_000):
        v1 = monotonic_ns()
        v2 = monotonic_ns()
    assert v1 < v2, f"Expected v1 < v2, got {v1} and {v2}"
```

### A note on test isolation

The `_tick_decimals` registry in `models/price.py` is a **module-level singleton**
— a plain Python dict that persists for the entire test session. If two test files
both call `register_tick_decimals("AAPL", 2)` that is fine — same value, no
conflict (the function allows idempotent re-registration). But if one test
registers `"AAPL"` with `tick_decimals=2` and another registers `"AAPL"` with
`tick_decimals=4`, the second call raises `RuntimeError` (see Section 5.1). Tests
that deliberately use a different precision for the same symbol name must reset the
registry first — clear `models.price._tick_decimals` in `setup_function()` or use a
distinct symbol name per test.

The `setup_function()` calls in each test file run before each test function in
that module. They register symbols before each test so the registry is always
populated correctly.

Similarly, `_last_ns` in `models/clock.py` is a module-level variable. Tests that
simulate clock regressions must reset it to a known value before the test and restore
it after (or use `importlib.reload()` to get a fresh module state).

### `tests/test_price.py`

```python
"""Tests for the price tick conversion utilities."""
from edumatcher.models.price import (
    register_tick_decimals, to_ticks, from_ticks, format_price,
    get_tick_decimals,
)


def setup_function():
    register_tick_decimals("AAPL",  2)
    register_tick_decimals("MSFT",  2)
    register_tick_decimals("EURUSD", 4)


def test_to_ticks_simple():
    assert to_ticks(150.30, "AAPL") == 15030
    assert to_ticks(150.31, "AAPL") == 15031
    assert to_ticks(0.01,   "AAPL") == 1
    assert to_ticks(0.00,   "AAPL") == 0


def test_to_ticks_absorbs_float_error():
    # 100.1 + 0.2 = 100.30000000000001 in IEEE 754 — round() fixes it
    assert to_ticks(100.1 + 0.2, "AAPL") == 10030


def test_from_ticks():
    assert from_ticks(15030, "AAPL") == 150.30
    assert from_ticks(1,     "AAPL") == 0.01
    assert from_ticks(0,     "AAPL") == 0.0


def test_round_trip():
    for price in [150.30, 209.00, 414.00, 0.01, 999.99, 1.00]:
        ticks     = to_ticks(price, "AAPL")
        recovered = from_ticks(ticks, "AAPL")
        assert abs(recovered - price) < 1e-10, f"Round-trip failed for {price}"


def test_four_decimal_symbol():
    assert to_ticks(1.2345, "EURUSD") == 12345
    assert from_ticks(12345, "EURUSD") == 1.2345


def test_format_price():
    assert format_price(15030, "AAPL") == "150.30"
    assert format_price(100,   "AAPL") == "1.00"
    assert format_price(1,     "AAPL") == "0.01"


def test_default_fallback():
    # Symbol not registered — falls back to DEFAULT_TICK_DECIMALS=2
    assert to_ticks(1.23, "UNKNOWN") == 123


def test_tick_size_immutable():
    # Re-registering the same value is allowed (idempotent).
    register_tick_decimals("AAPL", 2)   # no error — same value
    # Re-registering a DIFFERENT value is forbidden (Section 5.1).
    import pytest
    with pytest.raises(RuntimeError):
        register_tick_decimals("AAPL", 4)
```

### `tests/test_order_timestamps.py`

```python
"""Tests for nanosecond timestamps on Order and Trade."""
import time
from edumatcher.models.order import Order, Side, OrderType, TIF
from edumatcher.models.price import register_tick_decimals, to_ticks


def setup_function():
    register_tick_decimals("AAPL", 2)


def test_timestamp_is_int():
    o = Order.create("AAPL", Side.BUY, OrderType.LIMIT, 100, "GW01",
                     price=to_ticks(150.30, "AAPL"))
    assert isinstance(o.timestamp, int)
    # Plausible nanosecond epoch value (> year 2020)
    assert o.timestamp > 1_577_836_800 * 10**9


def test_consecutive_timestamps_distinct():
    o1 = Order.create("AAPL", Side.BUY, OrderType.LIMIT, 100, "GW01",
                      price=to_ticks(150.30, "AAPL"))
    o2 = Order.create("AAPL", Side.BUY, OrderType.LIMIT, 100, "GW01",
                      price=to_ticks(150.30, "AAPL"))
    assert o1.timestamp != o2.timestamp


def test_price_is_int_ticks():
    o = Order.create("AAPL", Side.BUY, OrderType.LIMIT, 100, "GW01",
                     price=to_ticks(150.30, "AAPL"))
    assert isinstance(o.price, int)
    assert o.price == 15030


def test_serialization_round_trip():
    o = Order.create("AAPL", Side.BUY, OrderType.LIMIT, 100, "GW01",
                     price=to_ticks(150.30, "AAPL"),
                     stop_price=to_ticks(148.00, "AAPL"))
    d  = o.to_dict()
    o2 = Order.from_dict(d)

    assert isinstance(d["price"], float)          # JSON carries float
    assert isinstance(d["timestamp"], int)         # JSON carries int ns
    assert o2.price == 15030                       # round-trip exact
    assert o2.stop_price == 14800
    assert o2.timestamp == o.timestamp             # preserved exactly
```

### `tests/test_trailing_stop_integer_ratchet.py`

This test verifies that the trailing stop ratchet mechanism accumulates no error
across many steps. The ratchet moves the stop price upward each time the market
rises, by subtracting `trail_offset` from `last_trade_price`. With floats, 100
such subtractions of $0.50 accumulate roughly 10⁻¹² of error per step — small but
real, and it can compound. With integers, each step is exact and the final result
is provably correct.

```python
"""Integer ratchet arithmetic must not accumulate error over many steps."""
from edumatcher.engine.order_book import OrderBook
from edumatcher.models.clock import monotonic_ns
from edumatcher.models.order import Order, Side, OrderType
from edumatcher.models.price import register_tick_decimals, to_ticks


def setup_function():
    register_tick_decimals("AAPL", 2)


def test_ratchet_exact_after_many_steps():
    book = OrderBook("AAPL")
    book.last_trade_price = to_ticks(150.00, "AAPL")   # 15000 ticks

    # Sell trailing stop: trail $0.50 = 50 ticks
    stop = Order.create("AAPL", Side.SELL, OrderType.TRAILING_STOP, 100, "GW01",
                        stop_price=to_ticks(149.50, "AAPL"),   # 14950
                        trail_offset=to_ticks(0.50,  "AAPL"))  # 50 ticks
    book._add_trailing_stop(stop, [])

    # 100 upward ticks: $150.00 → $151.00 (1 tick = $0.01)
    for i in range(1, 101):
        book.last_trade_price = 15000 + i
        book._check_trailing_stops(monotonic_ns())

    # Stop should be exactly 15050 (=$150.50 = $151.00 - $0.50)
    # With floats this accumulates ~1e-12 error per step; with ints: zero error
    assert stop.stop_price == 15050, (
        f"Expected 15050 ticks but got {stop.stop_price} — "
        "arithmetic error if this fails"
    )


def test_ratchet_does_not_move_down():
    book = OrderBook("AAPL")
    book.last_trade_price = to_ticks(150.00, "AAPL")

    stop = Order.create("AAPL", Side.SELL, OrderType.TRAILING_STOP, 100, "GW01",
                        stop_price=to_ticks(149.50, "AAPL"),
                        trail_offset=to_ticks(0.50, "AAPL"))
    book._add_trailing_stop(stop, [])

    # Price rises to $151.00 — stop ratchets to $150.50 = 15050
    book.last_trade_price = 15100
    book._check_trailing_stops(monotonic_ns())
    assert stop.stop_price == 15050

    # Price drops to $150.70 — stop must NOT move down
    book.last_trade_price = 15070
    book._check_trailing_stops(monotonic_ns())
    assert stop.stop_price == 15050   # unchanged
```

### `tests/test_matching_integer_prices.py`

These two tests verify the two most important correctness properties of integer tick
prices:

1. **Orders at the same price always match** — even when the buy price was computed
   via floating-point arithmetic that would produce a slightly different bit pattern
   from the sell price. `to_ticks()` absorbs both into the same integer.
2. **No duplicate price levels** — two orders at "the same" float price must produce
   exactly one entry in `_bid_qty`, not two separate entries with nearly-equal float
   keys.

```python
"""Orders at the same price must always match — no float equality bugs."""
from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import Order, Side, OrderType, TIF
from edumatcher.models.price import register_tick_decimals, to_ticks


def setup_function():
    register_tick_decimals("AAPL", 2)


def test_same_price_always_matches():
    book = OrderBook("AAPL")

    # Post a resting ask at $150.30
    ask = Order.create("AAPL", Side.SELL, OrderType.LIMIT, 100, "GW01",
                       price=to_ticks(150.30, "AAPL"))
    book.process(ask)

    # Aggressive buy — price computed via float arithmetic that would fail in old code:
    # 100.1 + 0.2 + 50.0 = 150.30000000000001 in IEEE 754
    # to_ticks() absorbs this → 15030 ← exactly matches the ask
    computed_price = 100.1 + 0.2 + 50.0
    buy = Order.create("AAPL", Side.BUY, OrderType.LIMIT, 100, "GW02",
                       price=to_ticks(computed_price, "AAPL"))

    trades, _ = book.process(buy)
    assert len(trades) == 1, "Must match — float equality bug would give 0 trades"
    assert trades[0].price == 15030


def test_price_level_index_no_duplicate_keys():
    """Float dict keys can create two entries for the same price — ints cannot."""
    book = OrderBook("AAPL")

    # Two orders at the same price, computed different ways
    o1 = Order.create("AAPL", Side.BUY, OrderType.LIMIT, 100, "GW01",
                      price=to_ticks(150.30, "AAPL"))
    o2 = Order.create("AAPL", Side.BUY, OrderType.LIMIT, 200, "GW02",
                      price=to_ticks(100.1 + 0.2 + 50.0, "AAPL"))

    book.process(o1)
    book.process(o2)

    # Must see exactly one price level, not two
    assert len(book._bid_qty) == 1, "Float keys would create 2 entries; int keys create 1"
    assert book._bid_qty[15030] == 300   # 100 + 200
```

---

## 24. Complete Change Summary

### Files requiring changes

| File | Changes |
|------|---------|
| `models/price.py` | **NEW** — `register_tick_decimals` (raises `RuntimeError` on conflicting re-registration), `get_tick_decimals`, `to_ticks`, `from_ticks`, `format_price`, `check_tick_aligned` (rejects misaligned/non-positive prices) |
| `models/clock.py` | **NEW** — `monotonic_ns()`: strictly increasing nanosecond timestamps that survive wall-clock regressions (Section 5.3) |
| `models/order.py` | `timestamp/price/stop_price/trail_offset`: float→int; `create()`: add `now` param, fallback to `monotonic_ns()`; `to_dict()`: `from_ticks` on prices; `from_dict()`: `to_ticks` on prices, direct int timestamp |
| `models/trade.py` | `price/timestamp`: float→int; `create()`: `monotonic_ns()` fallback; `to_dict()`: `from_ticks`; `from_dict()`: `to_ticks`, direct int timestamp |
| `models/combo.py` | `ComboLeg.price/stop_price`: float→int; `ComboOrder.timestamp`: float→int, `monotonic_ns()`; `to_dict`/`from_dict`: same pattern |
| `models/message.py` | `make_fill_msg`, `make_auction_result_msg`, `make_ack_msg`: accept int ticks, convert to float before encode |
| `engine/order_book.py` | `_bid_qty/_ask_qty`: dict[float]→dict[int]; `last_trade/buy/sell_price`: float→int; `process/amend`: `now` float→int, `monotonic_ns()` fallback; `_sweep/_apply_fill`: `price_limit/now/fill_price` float→int; `_rest/_reinsert`: heap keys now int; `_check_stops/_check_trailing_stops`: `now` int; `snapshot()`: `from_ticks` on output; `restore_stats`: params float→int |
| `engine/auction.py` | `AuctionResult.eq_price`: float→int; `compute_equilibrium`: dict types int, `float("inf")`→large int; `execute_uncross`: `eq_price` int, `monotonic_ns()` |
| `engine/config_loader.py` | `SymbolConfig`: add `tick_decimals: int = 2`; `load_engine_config()`: parse and validate `tick_decimals` |
| `engine_config.yaml` | Add `tick_decimals: 2` to each symbol |
| `engine/persistence.py` | `save_book_stats()`: `from_ticks` before JSON; `save_gtc_orders/save_gtc_combos`: wrap output in `{"format_version": 2, ...}`; `load_gtc_orders/load_gtc_combos`: reject any file whose `format_version` is not 2, and reject old plain-list format |
| `engine/main.py` | `_load_config()`: `register_tick_decimals`, `to_ticks` for seed prices; MM order parser: `to_ticks`; `_handle_new_order()`: `to_ticks` on all prices, then `check_tick_aligned` to **reject** misaligned/non-positive prices; `_handle_amend_order()`: `to_ticks`; fill publication: `from_ticks`; auction: `from_ticks`; 2× `time.time()` → `monotonic_ns()`; snapshot: add `tick_decimals` |
| `gateway/main.py` | Add `_fmt_timestamp()` helper; apply wherever `od["timestamp"]` is formatted |
| `clearing/main.py` | Add `_fmt_ts()` helper; replace 2× `datetime.fromtimestamp(trade.timestamp, ...)`; optionally sync tick registry from snapshots (Section 5.8) |
| `stats/main.py` | Add `_ns_to_dt()` helper; replace all `datetime.fromtimestamp(payload_ts, ...)` |
| `viewer/main.py` | Add `_ns_to_time_str()` helper; replace `datetime.fromtimestamp(tr["timestamp"])` |
| `board/main.py` | Same timestamp helper; apply to trade timestamp display |
| `ticker/main.py` | Apply timestamp helper if reading message timestamps |
| `ai_trader/main.py` | Apply timestamp helper if reading message timestamps |

### Files requiring no changes

| File | Reason |
|------|--------|
| `messaging/bus.py` | No prices or timestamps |
| `scheduler/main.py` | Uses `time.monotonic()` for scheduling; no price or epoch timestamps |
| `audit/main.py` | Logs raw JSON; prices already float in payloads; timestamps opaque |
| `orders/main.py` | Displays JSON dict fields; prices already float |
| `models/session.py` | No prices or timestamps |
| `ai_trader/personality.py` | `tick_size: float` is display-world; no changes needed |

### Conversion functions used per zone

| Zone | Function | Direction |
|------|----------|-----------|
| Engine input (gateway payload, config, FIX strings) | `to_ticks(float, symbol)` | float → int |
| Engine internal | none — everything is int | — |
| Engine output (ZMQ publish, `to_dict()`, CSV) | `from_ticks(int, symbol)` | int → float |
| Display (viewer, board, ticker, gateway, clearing) | `from_ticks()` or receive already-converted float | int → float or already float |

**"Already float" explained:** Subscriber processes (viewer, board, clearing, stats)
receive prices via ZMQ messages. Those messages carry float prices because the engine
calls `from_ticks()` before publishing. So by the time a price arrives in a subscriber,
it is already a Python `float` — the subscriber does not need to call `from_ticks()`
itself. The only time a subscriber would call `from_ticks()` is if it were doing its
own internal tick arithmetic, which none of the current subscribers do.

---

## 25. Implementation Checklist

Use this to track progress. Tick each item only after the corresponding test passes.

### Section 5 — Design Constraints (verify before starting any phase)
- [ ] `register_tick_decimals()` raises `RuntimeError` if called a second time with a different value for the same symbol (Section 5.1)
- [ ] `check_tick_aligned()` added to `models/price.py` — **rejects** misaligned prices (Section 5.2, v6 policy change from v5)
- [ ] `check_tick_aligned()` uses 1% tolerance (not 50%) to distinguish IEEE 754 float error from genuine misalignment (Section 5.2)
- [ ] `check_tick_aligned()` error message shows the two nearest valid tick prices (Section 5.2)
- [ ] `models/clock.py` created with `monotonic_ns()` function (Section 5.3)
- [ ] `monotonic_ns()` is used instead of `time.time_ns()` everywhere in the engine and in `Order.create()` / `Trade.create()` / `ComboOrder` (Section 5.3)
- [ ] `Order.create()` uses `monotonic_ns()` as its timestamp fallback (Section 5.3)
- [ ] `Trade.create()` uses `monotonic_ns()` as its timestamp fallback (Section 5.3)
- [ ] Invariant comment added in `_rest()` in `order_book.py` (Section 5.3)
- [ ] Zero and negative prices rejected in `_handle_new_order()` (Section 5.4)
- [ ] Combo leg validation uses each leg's own symbol for `check_tick_aligned()` (Section 5.5)
- [ ] `save_gtc_orders()` writes `"format_version": 2` (Section 5.6, v6 — bumped from v5's 1)
- [ ] `load_gtc_orders()` rejects files with `format_version != 2` (Section 5.6)
- [ ] `load_gtc_orders()` detects and rejects old plain-list format (Section 5.6)
- [ ] Same versioning applied to `save_gtc_combos()` / `load_gtc_combos()` (Section 5.6)
- [ ] Clearing and viewer/board snapshot handlers call `register_tick_decimals()` when `tick_decimals` is in snapshot (Section 5.8)

### Phase 0 — `models/price.py` and `models/clock.py` (new files)
- [ ] `register_tick_decimals()` raises `RuntimeError` on mid-session tick size change
- [ ] `to_ticks()` uses `round()` — not `int()` or truncation
- [ ] `from_ticks()` and `format_price()` implemented
- [ ] `check_tick_aligned()` implemented with 1% tolerance, positive-price check, helpful error message
- [ ] `DEFAULT_TICK_DECIMALS = 2` module-level constant present
- [ ] `models/clock.py` created with `monotonic_ns()` — handles same-value and backward-regression cases
- [ ] `tests/test_price.py` passes (all 8 test functions)
- [ ] `tests/test_tick_alignment.py` passes (all 7 test functions including misaligned rejection)
- [ ] `tests/test_clock.py` passes (all 4 test functions including simulated regression)

### Phase 1 — `models/order.py`
- [ ] `timestamp: int`, `price: Optional[int]`, `stop_price: Optional[int]`, `trail_offset: Optional[int]`
- [ ] `Order.create()` adds a `now` parameter and uses `monotonic_ns()` as its fallback
- [ ] `to_dict()` calls `from_ticks()` on price fields; keeps timestamp as int
- [ ] `from_dict()` calls `to_ticks()` on price fields; reads timestamp as int directly
- [ ] No `isinstance` compat guards anywhere in `from_dict()`
- [ ] `tests/test_order_timestamps.py` passes

### Phase 2 — `models/trade.py`
- [ ] `price: int`, `timestamp: int`
- [ ] `Trade.create()` calls `monotonic_ns()` as fallback
- [ ] `to_dict()` calls `from_ticks()` on price
- [ ] `from_dict()` calls `to_ticks()` on price; reads timestamp as int

### Phase 3 — `models/combo.py`
- [ ] `ComboLeg.price: Optional[int]`, `ComboLeg.stop_price: Optional[int]`
- [ ] `ComboOrder.timestamp: int`; `create()` calls `monotonic_ns()`
- [ ] Both `to_dict()` and `from_dict()` updated for all price fields

### Phase 4 — `engine/order_book.py`
- [ ] `_bid_qty: dict[int, int]`, `_ask_qty: dict[int, int]`
- [ ] `last_trade_price`, `last_buy_price`, `last_sell_price`: `Optional[int]`
- [ ] `process()` and all sub-methods: `now: int`
- [ ] `amend_order()`: `new_price: Optional[int]`, `now: Optional[int]`
- [ ] `restore_stats()`: both params `Optional[int]`
- [ ] `snapshot()` calls `from_ticks()` on all price fields in output dict
- [ ] `_sweep()`, `_sweep_iceberg()`: `price_limit: Optional[int]`, `now: int`
- [ ] `_apply_fill()`: `fill_price: int`, `now: int`
- [ ] `_check_stops()`, `_check_trailing_stops()`: `now: int`
- [ ] **Run full test suite here before continuing**
- [ ] `tests/test_trailing_stop_integer_ratchet.py` passes
- [ ] `tests/test_matching_integer_prices.py` passes

### Phase 5 — `engine/auction.py`
- [ ] `AuctionResult.eq_price: int | None`
- [ ] `compute_equilibrium()`: all dict types `dict[int, int]`; `float("inf")` → `10**18`
- [ ] `execute_uncross()`: `eq_price: int`, `monotonic_ns()`

### Phase 6 — `engine/config_loader.py` and `engine_config.yaml`
- [ ] `SymbolConfig.tick_decimals: int = 2` added
- [ ] `load_engine_config()` parses and validates `tick_decimals` (0–8)
- [ ] `engine_config.yaml`: `tick_decimals: 2` added to every symbol

### Phase 7 — `engine/persistence.py`
- [ ] `save_book_stats()` calls `from_ticks()` before writing JSON
- [ ] `save_gtc_orders()` wraps output in `{"format_version": 2, "orders": [...]}`
- [ ] `load_gtc_orders()` validates `format_version == 2`, raises `RuntimeError` on mismatch
- [ ] Same versioning applied to `save_gtc_combos()` / `load_gtc_combos()`

### Phase 8 — `engine/main.py`
- [ ] `_load_config()` calls `register_tick_decimals()` first for every symbol
- [ ] Seed prices converted with `to_ticks()` before `book.restore_stats()`
- [ ] MM order parser converts with `to_ticks()` immediately after parsing
- [ ] `_handle_new_order()` converts all prices with `to_ticks()` then validates with `check_tick_aligned()` — **rejects** misaligned prices (v6 policy)
- [ ] `_handle_new_order()` rejects zero and negative ticks for price, stop_price, trail_offset
- [ ] `_handle_amend_order()` converts price with `to_ticks()`; publishes with `from_ticks()`
- [ ] Fill publication converts `last_trade_price` and `evt.price` with `from_ticks()`
- [ ] Auction call-sites convert `eq_price` with `from_ticks()` before publishing
- [ ] Both `time.time()` calls changed to `monotonic_ns()`
- [ ] `time.monotonic()` in `_flush_snapshots()` left as float (intentional)
- [ ] `tick_decimals` added to book snapshot dict
- [ ] Combo and OCO leg prices handled correctly (ticks passed through / converted at JSON boundary)
- [ ] Combo leg validation: each leg's price checked for `> 0` using that leg's symbol's tick_decimals

### Phase 9 — `models/message.py`
- [ ] `make_fill_msg()`: `fill_price: int`, `price: Optional[int]`; both converted with `from_ticks()` before encode
- [ ] `make_auction_result_msg()`: `eq_price: int | None`; converted with `from_ticks()`
- [ ] `make_ack_msg()`: order price fields converted with `from_ticks()`

### Phase 10 — `gateway/main.py`
- [ ] Price parsing unchanged (gateway sends floats)
- [ ] `_fmt_timestamp()` helper added
- [ ] All `datetime.fromtimestamp(od["timestamp"])` replaced with `_fmt_timestamp()`

### Phase 11 — `clearing/main.py`
- [ ] `_fmt_ts()` helper added
- [ ] Both timestamp occurrences (CSV column, console print) replaced
- [ ] Book snapshot handler calls `register_tick_decimals()` when `tick_decimals` field is present

### Phase 12 — `stats/main.py`
- [ ] `_ns_to_dt()` helper added
- [ ] Both timestamp occurrences replaced

### Phase 13 — `viewer/main.py` and `board/main.py`
- [ ] `_ns_to_time_str()` helper added to each file
- [ ] All timestamp formatting calls replaced in both files

### Phase 14 — `ticker/main.py`
- [ ] `_ns_to_time_str()` helper added if reading message timestamps
- [ ] `time.monotonic()` calls left as float (correct — they measure durations)

### Phase 15 — `ai_trader/`
- [ ] No price changes needed (`_as_float()` still works on already-float prices)
- [ ] Timestamp formatting updated if reading message timestamps
- [ ] `time.monotonic()` calls left as float

### Final
- [ ] `pytest` runs clean with no warnings across all test files
- [ ] Persisted data files deleted: `gtc_orders.json`, `book_stats.json`, `gtc_combos.json`
- [ ] Engine starts, seeds market-maker orders, and processes a test order end-to-end

---

*EduMatcher Tick Migration Plan v7 — Publication Edition, May 2026.*
*Delete `data/gtc_orders.json`, `data/book_stats.json`, and `data/gtc_combos.json`*
*before starting the migrated engine. Implement phases in order.*
*v7 additions from deep-dive review: last-price field explanations, iceberg FOK*
*undercount documented, zero-removal from qty index made explicit, stop heap*
*direction logic explained, snapshot derived-value notes.*


---

## v3 Addendum (Merged into v4)

The section below is included verbatim from `design/EduMatcher Tick Migration Plan v3.md` so v4 is a strict superset of v1 + v3.

# EduMatcher Tick Migration Plan v2

This v2 replaces v1 as the implementation baseline.

Goal: migrate all internal prices to fixed ticks and all internal timestamps to integer nanoseconds with minimal regression risk.

Scope assumptions:
- No backward compatibility is required.
- Existing persisted files may be deleted before first v2 startup.
- Internal representation changes are allowed across engine and downstream processes.

## 1. Critical review of v1

v1 has strong coverage of core modules, but these regression risks were under-specified:

1. Clock monotonicity risk
- Replacing float seconds with time.time_ns() alone can still produce non-monotonic values if wall clock steps backward.
- Price-time priority must rely on strictly increasing timestamps, not raw wall time.

2. Mixed-unit trailing stop risk
- Current logic computes candidate stop as trade_price +/- trail_offset.
- If trade_price becomes ticks and trail_offset stays float price, ratchet logic silently mixes units.

3. Conversion boundary leakage
- Current code creates/parses prices in many entry points (gateway, MM FIX parser, combo parser, amend flow, config loader).
- If any path bypasses conversion, types diverge and failures appear late.

4. Message and timestamp display risk
- Multiple consumers call datetime.fromtimestamp() on current float seconds.
- After ns migration they must divide by 1e9 exactly once.

5. Stats/clearing schema semantic drift
- stats uses REAL columns and arithmetic assuming display prices.
- clearing and gateway PnL use float positions/costs while quantity is integral.
- Missing explicit policy for where integer ticks are mandatory versus where float display values are allowed.

6. Test gap risk
- Existing tests focus on round prices and do not stress tick-grid alignment, unit conversion, or ns timestamp roundtrips.

## 2. Design rules (must hold globally)

1. Internal canonical types
- price_ticks: int for all order/trade/book/core math.
- ts_ns: int for all event timestamps and priority ordering.

2. Boundary-only conversion
- Convert float/string price to ticks only at ingestion boundaries.
- Convert ticks to formatted decimal only at presentation/output boundaries.
- No internal business rule compares or aggregates float prices.

3. Clock policy
- Introduce one clock API used everywhere in engine/model factories:
  - now_ns(): strictly increasing integer nanoseconds.
- Do not call time.time() or time.time_ns() directly in matching paths.

4. Trailing stop policy
- trail_offset is stored and processed in ticks.
- stop_price and candidate stop are always ticks.
- No float arithmetic in ratchet logic.

5. Single rounding policy
- Inbound price conversion rounds to nearest tick using configured tick size.
- Never truncate inbound prices.
- Outbound display formatting uses symbol tick_decimals.

6. No mixed schemas
- Once v2 lands, persisted files and message payloads use only v2 fields/types.

## 3. Canonical representation contract

Use these field contracts after migration:

- Order
  - timestamp_ns: int
  - price_ticks: int | None
  - stop_price_ticks: int | None
  - trail_offset_ticks: int | None

- Trade
  - timestamp_ns: int
  - price_ticks: int

- ComboLeg
  - price_ticks: int | None
  - stop_price_ticks: int | None

- OrderBook internals
  - _bid_qty/_ask_qty keys: int ticks
  - heap sort keys include ticks + timestamp_ns

- Auction
  - eq_price_ticks: int | None

Display payloads may still expose decimal prices where needed, but conversion must be explicit and centralized.

## 4. Migration sequence (minimal-risk order)

## Phase 0: Safety net first

1. Add failing-forward tests before behavior changes
- Tick-grid alignment tests for new, amend, stop, trailing stop, AI trader quoting.
- Timestamp monotonicity tests for order/trade creation.
- Roundtrip persistence tests for order/trade/combo with ticks and ns.
- Cross-process timestamp display tests (gateway/viewer/clearing/stats).

2. Add shared conversion and clock utilities
- models/price.py: to_ticks, from_ticks, format_price, symbol tick registry.
- models/clock.py: now_ns() with strict monotonic guarantee.

Exit criteria:
- New safety tests exist and pass on current branch (where applicable).
- No production code path uses ad hoc conversion helpers.

## Phase 1: Core models

1. Update models/order.py
- Replace float price/stop/trail fields with tick integer fields.
- Replace timestamp with timestamp_ns.
- Update create/to_dict/from_dict to v2 schema.

2. Update models/trade.py
- price_ticks + timestamp_ns.

3. Update models/combo.py
- Leg pricing fields to ticks.
- Parent timestamp to ns.

Exit criteria:
- Model serialization tests pass.
- All model factories use now_ns().

## Phase 2: Matching and auction core

1. Update engine/order_book.py
- Qty indexes keyed by int ticks.
- Heap keys use ticks and timestamp_ns.
- All price comparisons on int ticks only.
- Trailing stop ratchet uses trail_offset_ticks only.

2. Update engine/auction.py
- Equilibrium on int tick price levels.
- Auction result carries eq_price_ticks internally.

Exit criteria:
- Price-time priority tests pass at same-price high-rate submissions.
- Stop and trailing stop tests pass with fractional decimal inputs converted to ticks.

## Phase 3: Ingestion boundaries

1. Update engine/main.py parsers
- MM FIX parsing converts PRICE/STOP/TRAIL to ticks immediately.
- Amend/new handlers enforce tick-domain validation.

2. Update gateway/main.py input parsing
- Keep user input decimal-friendly.
- Convert once before sending (or send decimal and convert immediately in engine, choose one policy and apply uniformly).
- OCO/combo leg inputs follow same rule.

3. Update engine/config_loader.py and engine_config.yaml contract
- Support tick_decimals per symbol.
- Seed prices converted to ticks on load.

Exit criteria:
- No engine path receives float prices after boundary conversion point.
- Config loading tests include multiple tick_decimals symbols.

## Phase 4: Persistence and messaging

1. Update engine/persistence.py
- Persist v2-only schema.
- Loaders expect ticks and ns fields only.

2. Update models/message.py and payload builders
- Define canonical field names for internal payloads.
- If external payloads retain decimal prices, conversion happens in one message-layer location.

Exit criteria:
- Restart roundtrip tests preserve exact tick values and ns timestamps.
- No float drift across save/load.

## Phase 5: Downstream consumers

1. Update clearing/main.py
- Core position math can continue in decimal display units, but trade ingest must convert from ticks explicitly.
- If using float output, conversion only at report/display boundaries.
- Replace datetime conversion with timestamp_ns aware logic.

2. Update stats/main.py
- Decide one of:
  - store ticks as INTEGER in DB and compute derived display values, or
  - store display decimals but convert from ticks exactly once on ingest.
- Make the chosen policy explicit and test it.

3. Update viewer/main.py, board/main.py, ticker/main.py
- Format prices from ticks via shared formatter.
- Format timestamps from ns consistently.

4. Update ai_trader/main.py and personality assumptions
- Quote generation must stay on tick grid for every symbol tick_decimals.

Exit criteria:
- UI and reports show correct decimal prices.
- All timestamp displays match expected wall time.

## Phase 6: Cleanup and hardening

1. Remove legacy float-based field names/usages.
2. Remove direct time.time() hot-path calls.
3. Add static checks (grep-based CI or lint rule) forbidding raw price float math in engine core.

Exit criteria:
- Full test suite green.
- No remaining float price fields in core engine/models.

## 5. Test strategy (regression-first)

Mandatory additions:

1. Price conversion and validation
- to_ticks/from_ticks roundtrip for multiple tick_decimals.
- Invalid off-grid inputs rejected or normalized per policy.

2. Matching invariants
- Same price different timestamps always FIFO.
- Better price always precedes worse price.
- FOK/IOC behavior unchanged under tick representation.

3. Stop/trailing behavior
- Trigger boundaries exact at tick edges.
- Ratchet only tightens, never loosens.
- trail_offset unit mismatch prevented by type/validation.

4. Auction correctness
- Equilibrium and imbalance deterministic on dense multi-level books.

5. Persistence
- Order/trade/combo roundtrip exact equality on ticks and ns.
- Engine restart preserves queue priority ordering semantics.

6. Process integration
- Gateway submit/amend/cancel paths with prices and timestamps.
- Viewer/board/ticker/clearing/stats consume v2 payloads without crashes.

7. AI trader
- All submitted prices lie on configured tick grid.

## 6. Cutover plan

1. Pre-cutover
- Stop all processes.
- Delete data/gtc_orders.json, data/book_stats.json, data/gtc_combos.json.

2. Deploy order
- Deploy engine and models first.
- Then gateway and downstream consumers.

3. Smoke checks
- Submit LIMIT/STOP/STOP_LIMIT/TRAILING_STOP/IOC/FOK/ICEBERG.
- Run one opening/continuous/closing session flow.
- Verify persistence reload and book order priority.

4. Go/no-go gates
- No failing tests in matching, persistence, or process integration groups.
- Manual smoke checks pass without type conversion errors.

## 7. Explicit non-goals

- Backward-compatible payload/schema support.
- Dual float+tick execution modes.
- Opportunistic refactors unrelated to tick/ns migration.

## 8. Execution checklist

- [ ] Shared price and clock modules added.
- [ ] Model fields migrated to ticks/ns.
- [ ] Order book and auction migrated to pure int math.
- [ ] All ingestion boundaries convert once.
- [ ] Persistence and message schema switched to v2.
- [ ] Downstream consumers updated for ticks/ns formatting.
- [ ] Regression tests added and passing.
- [ ] Legacy float/time paths removed.

## 9. Concrete task list (implementation order)

Use this as the day-to-day execution checklist.

1. Create shared tick/clock primitives
- Files:
  - src/edumatcher/models/price.py (new)
  - src/edumatcher/models/clock.py (new)
- Tasks:
  - Implement symbol tick registry and converters (to_ticks, from_ticks, format_price).
  - Implement now_ns() with strictly increasing behavior.
  - Add unit tests for conversion and monotonicity.
- Tests:
  - Add/extend tests/test_messages.py (conversion behavior used in payloads)
  - Add new tests/test_price_and_clock.py

2. Migrate canonical model fields to ticks/ns
- Files:
  - src/edumatcher/models/order.py
  - src/edumatcher/models/trade.py
  - src/edumatcher/models/combo.py
- Tasks:
  - Replace float price/timestamp fields with tick/ns fields.
  - Update create(), to_dict(), from_dict() to v2 schema names/types.
  - Ensure all factory paths source time from now_ns().
- Tests:
  - tests/test_messages.py
  - tests/test_combo.py
  - tests/test_order_flow.py
  - tests/test_new_order_types.py

3. Migrate matching core to pure integer arithmetic
- Files:
  - src/edumatcher/engine/order_book.py
  - src/edumatcher/engine/auction.py
- Tasks:
  - Convert heap keys, qty indexes, and comparisons to tick ints.
  - Migrate stop/trailing logic to stop_price_ticks and trail_offset_ticks.
  - Remove remaining float price arithmetic from matching paths.
- Tests:
  - tests/test_order_book_coverage.py
  - tests/test_order_flow.py
  - tests/test_auction.py
  - tests/test_new_order_types.py

4. Convert ingestion boundaries and config
- Files:
  - src/edumatcher/engine/main.py
  - src/edumatcher/gateway/main.py
  - src/edumatcher/engine/config_loader.py
  - engine_config.yaml
- Tasks:
  - Convert NEW/AMEND/OCO/COMBO/MM FIX price fields to ticks exactly once.
  - Add tick_decimals support per symbol in config loader.
  - Enforce off-grid input behavior (reject or normalize) consistently.
- Tests:
  - tests/test_gateway_and_scheduler.py
  - tests/test_config_loader.py
  - tests/test_combo_gateway_integration.py

5. Migrate persistence and message contracts
- Files:
  - src/edumatcher/engine/persistence.py
  - src/edumatcher/models/message.py
- Tasks:
  - Persist only v2 tick/ns schema fields.
  - Ensure outbound message payload conversions are centralized and deterministic.
  - Ensure timestamp serialization/deserialization preserves ns precision.
- Tests:
  - tests/test_messages.py
  - tests/test_engine_integration.py
  - add new tests/test_persistence_tick_ns.py

6. Update downstream consumers and displays
- Files:
  - src/edumatcher/clearing/main.py
  - src/edumatcher/stats/main.py
  - src/edumatcher/viewer/main.py
  - src/edumatcher/board/main.py
  - src/edumatcher/ticker/main.py
  - src/edumatcher/ai_trader/main.py
  - src/edumatcher/ai_trader/personality.py
- Tasks:
  - Convert inbound trade/book payloads from ticks/ns using shared helpers.
  - Update datetime conversions to ns-aware formatting.
  - Ensure AI trader always submits on-grid prices for symbol tick_decimals.
- Tests:
  - tests/test_clearing_ticker_gateway.py
  - tests/test_stats_and_orders.py
  - tests/test_ai_trader_personality.py
  - tests/test_ai_trader_runtime.py

7. Add targeted regression tests for known risk areas
- Files:
  - tests/test_order_book_coverage.py
  - tests/test_auction.py
  - tests/test_new_order_types.py
  - tests/test_process_helpers.py
  - tests/test_gateway_and_scheduler.py
- Tasks:
  - Add FIFO tie-break tests for same-price, close-arrival orders.
  - Add trailing-stop ratchet tests that verify tick-grid invariants.
  - Add persistence roundtrip tests asserting exact tick/ns equality.
  - Add integration tests validating viewer/board/ticker timestamp formatting from ns.

8. Clean up legacy paths and add guardrails
- Files:
  - src/edumatcher/** (all touched modules)
  - Makefile (optional guard target)
- Tasks:
  - Remove obsolete float price fields/usages and direct time.time() from hot paths.
  - Add a lightweight CI grep check to fail on prohibited patterns in engine core.
  - Re-run full suite and confirm no mixed-unit code remains.

9. Update relevant documentation in docs/
- Files to update:
  - docs/architecture.md
  - docs/configuration.md
  - docs/messages.md
  - docs/gateway.md
  - docs/concepts-order-book.md
  - docs/auction.md
  - docs/persistence.md
  - docs/pnl.md
  - docs/faq.md
  - docs/glossary.md
  - docs/ai-bot.md
- Tasks:
  - Document canonical tick/ns internal model and conversion boundary rule.
  - Update message examples to match v2 field names/types.
  - Document tick_decimals configuration and TRAIL offset semantics in ticks.
  - Update operational notes for deleting legacy persistence files before cutover.
  - Update glossary terms (tick, timestamp_ns, trail_offset_ticks, equilibrium price in ticks).

10. Final validation and cutover
- Commands:
  - poetry run pytest tests/ -n auto --cov=src/edumatcher --cov-report=term-missing --cov-report=html --cov-report=xml --cov-fail-under=85
  - poetry run black --check src tests
  - poetry run flake8 src tests
  - poetry run mypy src tests
- Tasks:
  - Run smoke scenario across NEW/AMEND/CANCEL/STOP/STOP_LIMIT/FOK/IOC/ICEBERG/TRAILING_STOP.
  - Restart engine and verify GTC/book stats/combo persistence under v2 schema.
  - Record go/no-go based on test + smoke evidence.

# EduMatcher OrderBook — Deep Dive for Python Programmers (v4)

## What You Will Learn

- **What an order book is** — the fundamental data structure at the heart of every
  financial exchange, and what problem it solves
- **The heap data structure** — what it is, how Python's `heapq` module works, and
  why a heap is the right tool for a matching engine's price queue
- **Lazy deletion** — why we never remove entries from the middle of a heap, and how
  to mark entries as invalid instead
- **The dual-index pattern** — why a matching engine maintains two parallel data
  structures (the heap and a flat dictionary) and what each one is responsible for
- **Price-time priority** — how we encode "best price first, then earliest time" into
  a heap key using a simple tuple trick
- **The `__slots__` optimisation** — what Python object memory looks like by default,
  and how `__slots__` trades flexibility for speed and lower memory
- **Stop and trailing stop order mechanics** — how two separate heaps replace a linear
  scan for triggered stops, and why each heap uses a different sort direction
- **The three "last price" fields** — why `last_trade_price`, `last_buy_price`, and
  `last_sell_price` are three distinct fields serving three distinct purposes
- **The iceberg FOK undercount** — a concrete limitation of the visible-only quantity
  index and what it means for Fill-Or-Kill availability checks
- **Spread and mid price as derived values** — why the order book stores neither, and
  what happens when one side of the book is empty
- **The synchronisation invariant** — the four data structures that must always be
  updated together, and what breaks if any one is missed
- **Self-match prevention** — why an exchange needs to detect when a participant would
  trade against themselves, and how the three cancellation strategies work
- **No-matching mode** — how the same order book collects interest during an auction
  without executing any trades

---

## Financial Glossary

Read this before anything else. Every term below appears in this document. If you
already work in finance, skip ahead — these definitions are deliberately simplified
for software developers.

**Instrument / Symbol** — the thing being traded. Could be a share of Apple stock
(symbol: `AAPL`), a currency pair (symbol: `EURUSD`), or a futures contract. An
order book exists per symbol.

**Order** — an instruction to buy or sell a quantity of an instrument at a specified
price or better.

**Bid** — a buyer's offer. A bid of $150.30 means: "I am willing to buy at $150.30
or cheaper." The collection of all active bids forms the buy side of the book.

**Ask** (also called an **offer**) — a seller's offer. An ask of $150.35 means: "I
am willing to sell at $150.35 or higher." The collection of all active asks forms
the sell side of the book.

**Spread** — the difference between the best (lowest) ask and the best (highest) bid.
If the best bid is $150.30 and the best ask is $150.35, the spread is $0.05. A
tighter spread means more liquid, cheaper-to-trade market.

**Resting order** (also called a **passive order**) — an order that has been accepted
by the exchange and is sitting in the book waiting for a counterparty. It does not
execute immediately.

**Aggressive order** (also called a **taker**) — an incoming order that immediately
trades against resting orders. It "sweeps" the book.

**Price level** — all the resting orders at the same price. If three buyers have all
placed bids at $150.30, they are all at the same price level. Their combined quantity
is the depth at that level.

**Depth** — how much quantity is resting at a given price level (or within a price
range). Deep books have large quantities at each price, making it hard to move the
price by trading. Shallow books are easier to move.

**Market data** — the continuous stream of information about what is happening in the
book: what prices orders are resting at, how much quantity, and what trades have
happened. Display tools (viewer, board, ticker) consume market data.

**Trade** (also called a **fill** or **execution**) — the event that occurs when a
buyer and seller agree on a price and quantity. A trade record contains: the
instrument, the price, the quantity, and which orders were involved.

**Limit order** — an order with a price constraint. A buy limit order at $150.30
will only execute at $150.30 or lower — the buyer is setting the maximum price they
will pay. A sell limit order at $150.35 will only execute at $150.35 or higher.
Limit orders that cannot immediately match rest in the book.

**Market order** — an order with no price constraint. "Buy 100 shares at whatever
price is available right now." Market orders execute immediately against the best
available resting orders. Because they have no price limit, they cannot rest in the
book — there is no price to put them at.

**IOC (Immediate-Or-Cancel)** — an order that must execute immediately. Any portion
that cannot be immediately filled is cancelled on the spot. Unlike a market order,
an IOC can have a price limit ("fill what you can at $150.35 or better, cancel the
rest").

**FOK (Fill-Or-Kill)** — an order that must be entirely filled immediately, or not
at all. If the book does not have enough quantity to fill the full order, the entire
order is cancelled without any partial fill.

**GTC (Good-Till-Cancelled)** — a Time-In-Force (TIF) instruction on an order.
A GTC order stays in the book indefinitely until it fills or the participant
explicitly cancels it. It survives engine restarts.

**DAY** — another TIF instruction. A DAY order expires at the end of the trading
session if not filled.

**Stop order** — a conditional order that is dormant until the market price reaches
a specified trigger level (the stop price), at which point it converts to a market
or limit order and enters the book. Used to automatically exit a position if the
price moves against you.

**Trailing stop** — a stop order whose trigger price moves automatically as the
market moves in a favourable direction. See the dedicated section below.

**Iceberg order** — an order that shows only a small visible portion (the "peak")
to the market while hiding a large reserve behind it. When the visible portion is
consumed by a fill, the order automatically replenishes from the reserve. Used by
large traders who do not want to reveal the full size of their position, which would
move the market against them.

**Lot** — a unit of quantity. For equities, one lot typically means one share. For
futures, one lot is one contract. In this document, "100 lots" means a quantity of
100.

**Firm** — a trading company or financial institution. In SMP (Self-Match
Prevention) context, a "firm" is a single participant whose orders all share the
same `gateway_id`.

**Auction** — a trading session mode used at market open and close. During an
auction, orders are collected but not immediately matched. At the end of the auction
period, all eligible orders execute simultaneously at a single equilibrium price.

---

## What Is an Order Book?

Before looking at any code, build the conceptual model.

An exchange is a marketplace where buyers and sellers meet. The order book is the
exchange's record of every unmet offer — all the buyers who want to buy but haven't
found a seller yet, and all the sellers who want to sell but haven't found a buyer.

```
                  THE ORDER BOOK FOR AAPL
  ┌─────────────────────────────────────────────────────┐
  │  BUY SIDE (BIDS)            SELL SIDE (ASKS)        │
  │                                                     │
  │  $150.28 × 200 shares       $150.31 × 500 shares   │
  │  $150.27 × 100 shares       $150.33 × 200 shares   │
  │  $150.25 × 400 shares       $150.35 × 300 shares   │
  │           ↑                          ↑              │
  │      Best bid                   Best ask            │
  │      (highest buyer)            (lowest seller)     │
  │                                                     │
  │            SPREAD = $150.31 - $150.28 = $0.03       │
  └─────────────────────────────────────────────────────┘
```

When a new buy order arrives at $150.31 or higher, it crosses the spread and
matches against the best ask. A trade happens. Both orders are updated. The engine
checks for more matches.

When a new buy order arrives at $150.27, it cannot match (the cheapest seller wants
$150.31). The order rests on the bid side, joining the queue.

The `OrderBook` class in `engine/order_book.py` implements all of this.

---

## Background: The Heap Data Structure

Before reading any code, you need a solid mental model of what a heap is. Everything
else in this file builds on it.

### What a Heap Is

A heap is a list that maintains one guarantee: **the smallest element is always at
index 0.** That is the entire contract. The rest of the list is not sorted — it is
just arranged so that the minimum can be found in O(1) and added or removed in
O(log n).

```
Unsorted list:  [5, 2, 8, 1, 4, 9, 3]
After heapify:  [1, 2, 3, 5, 4, 9, 8]
                 ^
                 Always the minimum — instantly accessible
```

Python's `heapq` module gives you three operations:

```python
import heapq

heap = []

heapq.heappush(heap, 4)   # insert 4 — O(log n)
heapq.heappush(heap, 1)   # insert 1 — O(log n)
heapq.heappush(heap, 7)   # insert 7 — O(log n)

heap[0]                   # peek at minimum — O(1), does NOT remove
heapq.heappop(heap)       # remove and return minimum — O(log n)
```

**What "amortised O(1)" means:** Some operations are listed as "O(1) amortised"
in the complexity table at the end. This means the operation is not always O(1), but
the *average* cost across many calls is O(1). Lazy deletion is a good example: most
calls to `_peek()` are O(1) (one valid entry at the top), but occasionally a call
must discard several stale entries, each costing O(log n). Spread across all calls,
the average is O(1) per `_peek()` call.

### Why a Heap For an Order Book?

A matching engine needs to answer one question repeatedly and very fast:

> "What is the best resting order right now?"

For bids, "best" means the **highest price** — the most a buyer is willing to pay.
For asks, "best" means the **lowest price** — the least a seller will accept.

A heap gives us O(1) access to the best element. Inserting a new order is O(log n).
This is the right tradeoff for a matching engine where `peek at best` and `insert new
order` are the dominant operations.

### The Min-Heap / Max-Heap Trick

Python's `heapq` is a **min-heap** — it always puts the smallest element first.
This is perfect for asks (we want the lowest ask first) but backwards for bids
(we want the highest bid first).

The standard solution: **negate the price for bids.**

> **Note:** Since the tick migration, all prices in EduMatcher are stored as
> integer tick counts (e.g. `$100.02` is `10002` for a symbol with
> `tick_decimals=2`). The heap key arithmetic works identically — negation of
> an `int` is still an `int`. The examples below use readable decimal prices for
> clarity, but the actual values in the code are integers.

```python
# Ask heap — natural min-heap, lowest ask first
heapq.heappush(asks, (10002, timestamp, order))  # $100.02 = 10002 ticks
heapq.heappush(asks, (10005, timestamp, order))  # $100.05 = 10005 ticks  ← will be second
heapq.heappush(asks, (10008, timestamp, order))  # $100.08 = 10008 ticks

asks[0]  # → (10002, ...)  ✓ lowest ask is first

# Bid heap — negate price so highest bid sorts first
heapq.heappush(bids, (-9998, timestamp, order))   # $99.98 = 9998 ticks
heapq.heappush(bids, (-10000, timestamp, order))  # $100.00 = 10000 ticks ← will be first
heapq.heappush(bids, (-9995, timestamp, order))   # $99.95 = 9995 ticks

bids[0]  # → (-10000, ...)  ✓ negated, so highest bid is first
```

Negating bids is a standard Python pattern. You will see it throughout this codebase.

### Price-Time Priority as a Tuple Key

A matching engine sorts orders by price first, then by arrival time as a tiebreaker.
This is called **price-time priority**. We encode both into a single tuple:

```python
key = (price, timestamp)
```

Python compares tuples element by element. If two orders have the same price, the
one with the smaller timestamp (earlier arrival) wins. This naturally implements
price-time priority in a single heap with no special logic:

```python
# Two asks at the same price — earlier one sorts first
# Timestamps are int nanoseconds from monotonic_ns()
key_a = (10002, 1_748_000_000_000_000_000)   # arrived first
key_b = (10002, 1_748_000_000_000_005_000)   # arrived 5 microseconds later

key_a < key_b  # True — key_a is "better" and will be at top of heap
```

For bids we negate the price:

```python
key = (-price_ticks, timestamp_ns)
```

This gives us highest price first, then earliest timestamp among equal prices. Both
in one heap, no special cases. Because both elements are integers, comparisons are
exact — no floating-point representation edge cases.

**Why price-time priority?** It is the fairest rule: better prices should win, and
among equal prices, whoever arrived first should win. It prevents a participant from
"cutting the queue" by submitting an order at the same price as someone who was
already waiting.

---

## The `_HeapEntry` Wrapper

```python
class _HeapEntry:
    __slots__ = ("key", "order", "valid")

    def __init__(self, key, order, valid=True):
        self.key = key
        self.order = order
        self.valid = valid

    def __lt__(self, other):
        return self.key < other.key
```

### Why Not Put Orders Directly on the Heap?

Python's `heapq` compares elements when sorting. If you put `Order` objects directly
on the heap, Python would try to compare them with `<`. But `Order` objects are
dataclasses with many fields — there is no natural ordering between two orders
(should a BUY order be "less than" a SELL order?). Python would raise a `TypeError`.

`_HeapEntry` solves this by:

1. Storing the sort key separately (`self.key = (price, timestamp)`)
2. Implementing `__lt__` to compare only keys — `heapq` uses `__lt__` internally
3. Carrying the `Order` as a passenger — never compared, just stored

### The `valid` Flag — Lazy Deletion

This is the most important field in `_HeapEntry`. Understand it deeply.

The `valid` flag is `True` when the entry should be considered, `False` when it
should be ignored. When an order is cancelled or filled, **we do not remove its
entry from the heap.** We just set `entry.valid = False`.

Why? Because Python's `heapq` has no `remove()` operation. Removing an arbitrary
element from the middle of a heap requires finding it first (O(n) scan) and then
re-heapifying (O(log n)). Together that is O(n) — too slow for a hot path.

Instead we use **lazy deletion**: mark as invalid, leave in the heap, and skip
invalid entries the next time `_peek()` is called.

```python
# Cancelling an order — O(1)
entry.valid = False          # mark invalid
order.status = CANCELLED     # update the order

# The entry is still physically in the heap, but _peek() will skip it
```

This is a well-known pattern in competitive programming and high-performance systems.
The heap may contain "garbage" entries, but they cost nothing until they surface at
the top, at which point they are discarded in O(log n).

### `__slots__` on `_HeapEntry`

```python
class _HeapEntry:
    __slots__ = ("key", "order", "valid")
```

By default, every Python object stores its attributes in a dictionary (`__dict__`).
Accessing `entry.valid` involves a hash table lookup inside that dict.

`__slots__` replaces the dict with a fixed C array. Attribute access becomes a
direct memory offset — like accessing `struct.field` in C. This is approximately
30% faster per access and uses significantly less memory per instance.

`_HeapEntry` is instantiated once per resting order. In a book with thousands of
resting orders, this saving compounds meaningfully.

---

## The `OrderBook` Class

```python
class OrderBook:
    __slots__ = (
        "symbol", "_bids", "_asks", "_buy_stops", "_sell_stops",
        "_trailing_stops", "_bid_qty", "_ask_qty", "_order_index",
        "_entry_index", "last_trade_price", "last_trade_qty",
        "last_buy_price", "last_sell_price", "recent_trades",
    )
```

`__slots__` on `OrderBook` itself gives the same benefit — faster attribute access
on every `self.xxx` reference inside the matching loop.

### The Data Structures

The `OrderBook` maintains ten distinct data structures. Each answers a different
question. They are all updated in sync — if you update one, you must update the
others. This is the key discipline of the order book implementation.

---

#### 1. `_bids` and `_asks` — The Price-Time Queues

```python
self._bids: list[_HeapEntry] = []   # max-heap via negated price
self._asks: list[_HeapEntry] = []   # min-heap
```

These are the two sides of the order book. Every resting limit order lives in one
of these heaps as a `_HeapEntry`.

**`_bids`** is a max-heap (via negated price). `_bids[0]` always gives the highest
bid — the most a buyer is currently willing to pay.

**`_asks`** is a min-heap. `_asks[0]` always gives the lowest ask — the least a
seller will accept.

When the matching engine needs to fill an incoming buy order, it looks at `_asks[0]`.
When filling an incoming sell order, it looks at `_bids[0]`. Both are O(1) lookups.

---

#### 2. `_order_index` — Fast Lookup by Order ID

```python
self._order_index: dict[str, Order] = {}
```

A flat dictionary mapping every resting order's ID to the `Order` object itself.

This answers: **"Given an order ID, give me the Order."**

Used for cancels, amends, and any operation that arrives with an order ID and needs
to find the order quickly. Without this, you would have to scan the entire heap —
O(n). With this dictionary, it is O(1).

```python
# Cancel arrives with just an order_id
order = self._order_index.get(order_id)   # O(1) — no heap scan needed
```

---

#### 3. `_entry_index` — Fast Lookup by Entry

```python
self._entry_index: dict[str, _HeapEntry] = {}
```

A flat dictionary mapping every order ID to its `_HeapEntry` in the heap.

This answers: **"Given an order ID, give me its heap entry so I can invalidate it."**

This is the second half of the lazy deletion pattern. When you cancel an order, you
need both the `Order` (to update its status) and the `_HeapEntry` (to set
`entry.valid = False`). The `_order_index` gives you the first, `_entry_index` gives
you the second.

```python
# Cancel path — two O(1) lookups, no heap scan
order = self._order_index.get(order_id)   # get the Order
entry = self._entry_index.get(order_id)   # get the HeapEntry
entry.valid = False                        # lazy deletion
order.status = OrderStatus.CANCELLED       # update status
```

Why two separate dicts instead of one? Because `Order` and `_HeapEntry` serve
different purposes and have different lifetimes. Stop orders, for example, are in
`_order_index` but not in `_entry_index` (they use different heaps with different
management). Keeping them separate avoids conflation.

---

#### 4. `_bid_qty` and `_ask_qty` — The Price-Level Quantity Index

```python
self._bid_qty: dict[int, int] = {}   # price_ticks → total resting qty at that price
self._ask_qty: dict[int, int] = {}
```

These dictionaries map each price level to the total quantity resting there. They
are maintained in parallel with the heaps and kept exactly in sync.

They answer: **"How much total quantity is available at price X?"**

Used for two things:

**FOK pre-check** — a Fill-Or-Kill order must be fully fillable before any fills
execute. The check scans this index to add up all available quantity at or better
than the FOK's limit price. Without this index, checking availability requires
scanning the entire heap. With this index, it is O(P) where P is the number of
distinct price levels — much faster.

```python
def _available_qty(self, heap, price_limit, side) -> int:
    qty_index = self._ask_qty if side == Side.BUY else self._bid_qty
    total = 0
    for price, qty in qty_index.items():
        if side == Side.BUY  and price <= price_limit: total += qty
        if side == Side.SELL and price >= price_limit: total += qty
    return total
```

`qty_index` is chosen based on which side is being checked: a BUY order needs to
know how much sell-side liquidity is available, so it reads `_ask_qty`. The price
filter then checks whether each level is within the order's limit price.

**Depth snapshots** — computing the available depth at a range of prices iterates
this index rather than the heap, avoiding the O(n) cost of scanning all heap entries.

### Iceberg Orders and the FOK Undercount

There is an important limitation: `_bid_qty` and `_ask_qty` track only the
**visible** quantity of iceberg orders, not their hidden reserve.

When an iceberg order is placed via `_rest()`, the code adds only `displayed_qty`
(the visible peak) to the quantity index:

```python
qty = (
    order.displayed_qty    # iceberg: only the visible peak is counted here
    if order.order_type == OrderType.ICEBERG
    else order.remaining_qty
)
self._bid_qty[order.price] = self._bid_qty.get(order.price, 0) + qty
```

This means `_available_qty()` — which the FOK check calls — will **undercount**
available liquidity whenever icebergs are present at price levels within the FOK's
range.

**Concrete example:** Suppose a FOK BUY order for 2,500 shares arrives at $150.30.
At that price level there are:
- One regular LIMIT order for 800 shares
- One ICEBERG order with 300 visible and 2,700 hidden (3,000 total)

`_bid_qty[150.30]` = 800 + 300 = 1,100 (only visible counted)

`_available_qty()` returns 1,100 — less than the 2,500 needed — so the FOK is
rejected. But the iceberg could actually fill 3,000 shares; if regular orders were
also present at better prices the aggregate might reach 2,500 easily.

This is a known, intentional design simplification in EduMatcher. Correct iceberg-
aware FOK checking would require scanning the heap entries at each relevant price
level (to sum visible + hidden), which trades O(P) for O(n) on the FOK path. For
an educational system, the visible-only approximation is acceptable.

### The Synchronisation Invariant

Every operation that adds or removes a resting order must update **all four
structures** together, or the book becomes inconsistent:

| Operation | heap | `_order_index` | `_entry_index` | qty index |
|---|---|---|---|---|
| `_rest()` — new order | `heappush` | add | add | `+= qty` |
| cancel / `_apply_fill` (full fill) | `entry.valid = False` | `pop` | `pop` | `-= qty`, delete if 0 |
| `amend_order` (price/qty change) | invalidate old, `heappush` new | no change | update to new entry | `±= qty_delta` |
| iceberg replenish | invalidate old, `heappush` new | no change | update to new entry | `+= new_peak` |

Missing any one of these in any code path causes a silent bug that may not manifest
immediately. For example, leaving a stale entry in `_bid_qty` would cause the FOK
check to see phantom liquidity that has already been cancelled. Leaving an entry in
`_order_index` after a fill would cause a cancel request on that order ID to find
a filled order and send a confusing response.

---

#### 5. `_buy_stops` and `_sell_stops` — The Stop Heaps

```python
self._buy_stops: list[_HeapEntry] = []    # min-heap by stop_price
self._sell_stops: list[_HeapEntry] = []   # max-heap by -stop_price
```

Stop orders (defined in the glossary above) are not resting in the bid/ask book.
They wait in their own heaps and convert to market or limit orders when triggered.

**`_buy_stops`** — min-heap by stop price. A buy stop fires when the market price
rises to or above the stop price. The min-heap means the stop with the lowest
trigger price surfaces first — the next one to fire as price rises.

**Why is this correct?** As the market price rises from, say, $100 to $110, the
first buy stop to trigger is the one with the lowest stop price (say $102), because
$100 → $102 is crossed before $100 → $108. The min-heap puts the lowest price at
the top, so the first entry to check is the right one. A break out of the while
loop fires because `self.last_trade_price < stop_price` — if even the lowest stop
hasn't triggered, none of the others have either.

**`_sell_stops`** — max-heap by negated stop price. A sell stop fires when the
market price falls to or below the stop price. The max-heap (via negation) means
the stop with the highest trigger price surfaces first — the next one to fire as
price falls.

**Why is this correct?** As the market price falls from $100 to $90, the first sell
stop to trigger is the one with the highest stop price (say $98), because $100 →
$98 is crossed before $100 → $92. The max-heap puts the highest price at the top.
A break fires because `self.last_trade_price > stop_price` — if even the highest
stop hasn't triggered, none of the others have either.

The pattern is: for each stop heap, "the entry closest to the current price" is also
"the entry most likely to have just triggered" — and that is always at `heap[0]`.

Two separate heaps mean triggering is O(k log k) where k is the number of stops
that actually fire — typically zero or one. Without the split, you would need to
check both heaps for every trade.

---

#### 6. `_trailing_stops` — The Trailing Stop List

```python
self._trailing_stops: list[Order] = []
```

A plain list of all active trailing stop orders. Unlike regular stops, the trigger
price of a trailing stop changes every time the market price moves, so a heap is
not useful here — we must scan all of them on every trade to update their trigger
prices. In practice, trailing stop lists are short.

---

#### 7. `recent_trades` — The Rolling Trade Window

```python
self.recent_trades: deque[Trade] = deque(maxlen=20)
```

A bounded deque that holds the last 20 trades for this symbol. When the deque
is full, the oldest trade is automatically evicted when a new one is appended —
no manual housekeeping needed.

Used by `snapshot()` to include recent trade history in book snapshots.

**Why this matters for display processes.** A viewer or board process that starts
up mid-session — say, at 11:47am when trading has been running since 9:30am —
receives book snapshots and trade events going forward from the moment it connects.
But it needs to show the user *some* recent history immediately on startup, not just
the very first trade that happens to occur after it connects.

`recent_trades` solves this: the very first book snapshot the process receives
includes up to 20 recent trades, giving the display an immediate picture of recent
activity without querying the stats database.

**Why maxlen=20?** The bound is a deliberate network efficiency choice. Every book
snapshot message includes this list serialised as JSON. At 20 trades per snapshot,
and snapshots publishing every 500ms per symbol, the overhead is modest. Too few
trades (say, 5) and the initial display looks sparse; too many (say, 200) and the
snapshot message grows significantly. 20 is sufficient for a "recent tape" display
without inflating message sizes.

**`recent_trades` is the only trade source for reconnecting processes.** There is no
"replay last N trades" API in EduMatcher. If a display process restarts and needs
trade history, `recent_trades` in the next snapshot is all it gets from the engine.
The stats database (`data/stats.db`) has the full OHLCV history, but display
processes do not query it directly.

---

## Walking Through `process()` — The Main Entry Point

```python
def process(self, order, *, match=True, now=None):
```

Every incoming order enters through this single method. Let us walk through what
happens for the most common case: an incoming limit order.

### Step 1: Compute the Timestamp Once

```python
if now is None:
    now = monotonic_ns()   # from models/clock.py
```

`monotonic_ns()` is a thin wrapper around `time.time_ns()` that guarantees a
strictly increasing integer nanosecond timestamp even if the system clock steps
backward (due to NTP or a virtual machine hypervisor). It is a system call, and
system calls are expensive (~300-500 nanoseconds each).

A single aggressive order that triggers stop orders can go through `process()`
recursively several times. Computing `now` once at the top and passing it through
avoids repeated calls.

This is a micro-optimisation but it is the right instinct: **identify the expensive
operation, call it once, pass the result everywhere.**

### Step 2: No-Matching Mode Check

```python
if not match:
    if order.order_type in (OrderType.MARKET, OrderType.FOK, OrderType.IOC):
        order.status = OrderStatus.REJECTED
        events.append(order)
        return trades, events
    self._rest(order)
    return trades, events
```

When `match=False`, the engine is in **auction mode** — the phase at the start and
end of the trading day when orders are collected but not yet executed. During an
auction, orders queue up so there is plenty of interest to trade when the auction
ends and a single equilibrium price is computed.

Market, FOK, and IOC orders are rejected during an auction because they require
immediate execution, which is not possible when no matching is happening. Limit and
iceberg orders are accepted and placed directly onto the heap with no sweep attempt.

### Step 3: Dispatch to the Right Handler

```python
if order.order_type == OrderType.MARKET:
    self._match_market(order, trades, events, now)
elif order.order_type == OrderType.LIMIT:
    self._match_limit(order, trades, events, now)
# ... etc
```

Each order type has its own handler. They all ultimately call `_sweep()` or a
variant of it, but differ in what happens to any quantity that cannot immediately
fill:

- **MARKET** — discard the unfilled remainder. A market order has no price limit,
  so there is no sensible price to rest it at. If the book runs out of resting
  orders, the remainder is cancelled.
- **LIMIT** — rest the unfilled remainder on the book at the specified price. This
  is the most common case.
- **IOC** — cancel the unfilled remainder immediately. Same as MARKET for the
  remainder, but with a price limit on what can fill.
- **FOK** — pre-check that the full quantity is available in the book before
  sweeping at all. If not enough quantity exists, cancel the entire order without
  doing any fills.

### Step 4: Check Stops After Every Trade

```python
if trades:
    triggered = self._check_stops(now)
    triggered += self._check_trailing_stops(now)
    for t_order in triggered:
        sub_trades, sub_events = self.process(t_order, now=now)
        trades.extend(sub_trades)
        events.extend(sub_events)
```

After any fills occur, we check whether any stop orders should now trigger. This
check only runs if `trades` is non-empty — no trades means prices did not move,
so no stops can trigger.

Note the **recursive call** to `self.process()`. A triggered stop becomes a new
market or limit order and goes back through the full matching logic. The `now`
timestamp is passed through to avoid more calls inside the recursive call.

This recursion is bounded in practice — triggered orders rarely trigger further
stops — but it is worth being aware of for deep stop cascades.

---

## The Sweep Loop — `_sweep()`

This is the innermost loop of the matching engine. It runs for every aggressive
order (one that immediately tries to fill against resting orders on the opposite
side of the book).

```python
def _sweep(self, aggressor, opposite_heap, price_limit, trades, events, now):
    _side = aggressor.side
    _smp_action = aggressor.smp_action
    _gw_id = aggressor.gateway_id
    _peek = self._peek
    _apply_fill = self._apply_fill
```

### Caching Attributes as Locals

The first thing `_sweep` does is copy several attributes and method references into
local variables. Why?

In Python, accessing `self.something` is an attribute lookup — Python looks up
`something` in the object's slot (or dict). This costs roughly 50-70 nanoseconds.
Accessing a local variable costs roughly 30 nanoseconds.

In a loop that may iterate dozens of times for a single aggressive order, accessing
`aggressor.side` on every iteration costs more than accessing the local `_side`.
By copying to locals before the loop, each loop iteration saves ~20-40 nanoseconds.

This is a genuine optimisation in CPython (the standard Python interpreter). It is
standard practice in performance-sensitive Python loops.

```python
# Without caching — attribute lookup every iteration
while ...:
    if aggressor.side == Side.BUY and best.price > aggressor.price:
        break

# With caching — local variable access every iteration
_side = aggressor.side
while ...:
    if _side == Side.BUY and best.price > price_limit:
        break
```

### The Main Loop

```python
while aggressor.remaining_qty > 0 and opposite_heap:
    best = _peek(opposite_heap)
    if best is None:
        break

    # Price check
    if price_limit is not None:
        if _side == Side.BUY and best.price > price_limit:
            break
        if _side == Side.SELL and best.price < price_limit:
            break

    # Self-match check
    if _smp_action != SmpAction.NONE and _gw_id == best.gateway_id:
        # ... handle SMP
        pass

    fill_qty = min(aggressor.remaining_qty, best.remaining_qty)
    fill_price = best.price
    _apply_fill(aggressor, best, fill_qty, fill_price, trades, events, now)
```

Each iteration:

1. **Peek at the best resting order** — O(1), but `_peek` does lazy deletion
   (see below)
2. **Price check** — stop sweeping if the best available price is worse than
   our limit. A buy order stops when asks are too expensive; a sell order stops
   when bids are too low.
3. **Self-match check** — if the aggressor and the resting order came from the
   same gateway (i.e., the same firm), apply the SMP action before filling.
4. **Fill** — take the smaller of what the aggressor needs and what the resting
   order has. The fill price is always the resting order's price (the passive side
   sets the price; the aggressive side takes it).

---

## `_apply_fill()` — What Happens When Two Orders Trade

`_apply_fill()` is called for every partial or full fill between an aggressive order
and a resting order. It is the moment a trade is born.

```python
def _apply_fill(self, aggressor, passive, fill_qty, fill_price,
                trades, events, now):
    # Reduce quantities on both orders
    aggressor.remaining_qty -= fill_qty
    passive.remaining_qty   -= fill_qty

    # Update price-level quantity index
    qty_index = self._bid_qty if passive.side == Side.BUY else self._ask_qty
    qty_index[fill_price] -= fill_qty
    if qty_index[fill_price] <= 0:
        del qty_index[fill_price]   # price level is now empty

    # If passive is fully consumed, mark it and remove from indexes
    if passive.remaining_qty <= 0:
        passive.status = OrderStatus.FILLED
        self._order_index.pop(passive.id, None)
        self._entry_index.pop(passive.id, None)
        # The heap entry is already invalid from _peek() cleanup

    # If aggressor is fully filled
    if aggressor.remaining_qty <= 0:
        aggressor.status = OrderStatus.FILLED

    # Create the trade record
    trade = Trade.create(
        symbol=self.symbol,
        buy_order_id=...,
        sell_order_id=...,
        price=fill_price,      # int ticks — the resting order's price
        quantity=fill_qty,
        now=now,
    )
    trades.append(trade)
    self.recent_trades.append(trade)

    # Update last trade reference prices (used by stop trigger checks)
    self.last_trade_price = fill_price
    if passive.side == Side.BUY:
        self.last_buy_price  = fill_price
    else:
        self.last_sell_price = fill_price

    # Notify both sides
    events.append(aggressor)
    events.append(passive)
```

Key points:

- **The resting order sets the price.** The passive (resting) side determines the
  fill price. This is why limit orders guarantee a price: if you rest a sell order
  at $150.35, any fill on that order happens at $150.35 or better.
- **Both sides are partially or fully consumed.** `remaining_qty` is decremented on
  both the aggressor and passive.
- **The price-level index is decremented immediately.** If the last order at a price
  level is filled, the entry is deleted entirely.
- **A `Trade` record is created** — this is what gets published to the clearing
  process and stats database.
- **Three reference prices are updated** — explained in detail below.

### The Three "Last Price" Fields

`_apply_fill` updates three separate price fields on the `OrderBook`. They look
similar but serve completely different purposes:

```python
self.last_trade_price = fill_price
if passive.side == Side.BUY:
    self.last_buy_price  = fill_price
else:
    self.last_sell_price = fill_price
```

**`last_trade_price`** — updated on every single fill, regardless of which side was
aggressive. This is the field that stop-trigger checks use. After each fill,
`_check_stops()` compares `last_trade_price` against the stop prices of all waiting
stop orders to decide whether any should fire. It answers: "what price did the most
recent trade happen at?"

**`last_buy_price`** — updated only when the passive (resting) order was on the BUY
side. This means the fill was initiated by an aggressive SELL order hitting a resting
bid. It records: "the most recent price at which a sell aggressor hit a standing
bid." Used by market statistics and circuit breakers.

**`last_sell_price`** — updated only when the passive order was on the SELL side,
meaning an aggressive BUY order hit a resting ask. Records: "the most recent price
at which a buy aggressor hit a standing offer."

**Why have both `last_buy_price` and `last_sell_price`?** The direction of the last
aggression — whether a buyer swept into sellers or a seller swept into buyers — is a
meaningful signal in market microstructure. A sequence of aggressive buys hitting
asks (rising `last_sell_price`) suggests upward pressure; a sequence of aggressive
sells hitting bids (rising `last_buy_price`) suggests downward pressure. These
separate fields let statistics and display tools show this directionality without
needing to examine the full trade history.

---

## `_peek()` — Lazy Deletion in Practice

```python
def _peek(self, heap):
    while heap:
        entry = heap[0]
        if not entry.valid:
            heapq.heappop(heap)
            continue
        o = entry.order
        if o.status in (FILLED, CANCELLED, REJECTED, EXPIRED):
            heapq.heappop(heap)
            entry.valid = False
            continue
        return o
    return None
```

This is where lazy deletion pays off. `_peek` does not just return `heap[0].order`.
It loops, discarding invalid or terminal entries, until it finds a valid resting order
or exhausts the heap.

The statuses it discards:
- **FILLED** — fully consumed by a previous match
- **CANCELLED** — explicitly cancelled by the participant or the engine
- **REJECTED** — rejected at submission (should not be in the heap, but defensive)
- **EXPIRED** — a DAY order that was not filled by end of session

The key insight: entries accumulate in the heap over time as orders fill, cancel, or
expire. Rather than removing them at the moment they become invalid (expensive), we
leave them in place and clean them up lazily here. Each invalid entry costs one
`heappop` — O(log n) — but that cost is paid only once, when the entry finally
surfaces at the top.

In a busy book where orders fill and cancel frequently, this avoids O(n) removal
operations and replaces them with O(log n) cleanup spread across many calls to
`_peek`.

---

## `_rest()` — Placing a Resting Order

```python
def _rest(self, order):
    assert order.price is not None
    # INVARIANT: order.timestamp is strictly monotonically increasing thanks to
    # monotonic_ns() (models/clock.py). No two orders share a timestamp, so
    # price-time priority within a price level is always deterministic.
    qty = (
        order.displayed_qty
        if order.order_type == OrderType.ICEBERG
        else order.remaining_qty
    )
    if order.side == Side.BUY:
        key = (-order.price, order.timestamp)
        heap = self._bids
        self._bid_qty[order.price] = self._bid_qty.get(order.price, 0) + qty
    else:
        key = (order.price, order.timestamp)
        heap = self._asks
        self._ask_qty[order.price] = self._ask_qty.get(order.price, 0) + qty

    entry = _HeapEntry(key=key, order=order)
    heapq.heappush(heap, entry)
    self._order_index[order.id] = order
    self._entry_index[order.id] = entry
```

When an order rests on the book, five things happen in the same function call:

1. A `_HeapEntry` is created with the correct sort key
2. The entry is pushed onto the appropriate heap
3. The order is registered in `_order_index` (for cancel/amend lookup)
4. The entry is registered in `_entry_index` (for lazy deletion on cancel)
5. The quantity is added to `_bid_qty` or `_ask_qty` (for FOK and depth checks)

All five data structures are updated within the same function call to stay in sync.
This is the discipline that keeps the book consistent — every operation that touches
the book must update all relevant structures.

Note the iceberg special case: an iceberg order rests its `displayed_qty` (the
visible peak) rather than its full `remaining_qty`. The hidden reserve is invisible
to other participants.

---

## `amend_order()` — Modifying a Resting Order

Amending a resting order's price or quantity is more complex than it appears
because of queue priority rules. EduMatcher implements the same rules used by
real exchanges:

- **Quantity decrease only, same price** → priority is **preserved**. The order
  stays at its position in the queue. Reducing size is not aggressive and should
  not be penalised. The participant is giving up some of their position — they
  should not lose their place in line as a result.
- **Price change, or quantity increase** → priority is **lost**. The order gets a
  new timestamp and goes to the back of the queue at the new price level. Changing
  the price is a meaningful change to the order's competitiveness; increasing the
  quantity means the participant wants to trade more at the same price, which is
  treated as a new competitive act.

```python
def amend_order(self, order_id, new_price=None, new_qty=None, now=None):
    order = self._order_index.get(order_id)
    ...
    price_changed = price != old_price
    qty_increased = qty > old_qty
    priority_reset = price_changed or qty_increased

    if priority_reset:
        order.timestamp = now        # new timestamp → back of queue
        entry.valid = False          # lazy-delete the old heap entry
        # Re-insert with new key (new price and/or new timestamp)
        new_entry = _HeapEntry(key=new_key, order=order)
        heapq.heappush(heap, new_entry)
        self._entry_index[order.id] = new_entry
    # If not priority_reset, just update the qty index — no heap change needed
```

The `priority_reset` branch is why `_entry_index` exists. Without it, we would
have no way to invalidate the old heap entry when the order is re-inserted at a
new key.

---

## Iceberg Orders — Replenishment

An iceberg order (defined in the glossary) has a fixed visible peak (e.g. 100 lots)
backed by a hidden reserve (e.g. 900 lots). When the visible slice is fully consumed
in a fill, it replenishes from the hidden reserve and goes to the **back of the queue**
at its price level.

**Why do iceberg orders lose queue priority on replenishment?** Fairness. Other
participants who were waiting in line at the same price should not be indefinitely
displaced by a large iceberg that keeps recycling to the front. Once a slice is
consumed, the iceberg must take its turn again.

```python
# In _apply_fill, after filling a passive iceberg:
if passive.remaining_qty > 0 and passive.displayed_qty == 0:
    new_peak = min(passive.visible_qty, passive.remaining_qty)
    passive.displayed_qty = new_peak
    passive.timestamp = now   # ← back of queue
    self._reinsert_iceberg(passive)
```

The timestamp update is the key mechanism. By setting `passive.timestamp = now`,
the replenished iceberg gets a new, later timestamp. When `_rest()` is called again,
its heap key becomes `(price, now)` — sorting behind any other resting orders at
the same price that arrived earlier. This correctly implements the exchange rule that
iceberg replenishment loses queue priority.

`_reinsert_iceberg` invalidates the old heap entry (lazy deletion) and pushes a new
one with the updated timestamp and quantity.

---

## Self-Match Prevention

**Why self-matching matters:** Exchanges prohibit a participant from trading with
themselves because it creates a false impression of market activity (the participant
is generating artificial volume) and could be used to manipulate prices. In
EduMatcher, a "participant" corresponds to a `gateway_id`.

When a firm's own orders might trade against each other, the exchange can apply one
of three strategies:

```python
class SmpAction(str, Enum):
    NONE             = "NONE"             # no SMP — let the trade happen
    CANCEL_AGGRESSOR = "CANCEL_AGGRESSOR" # cancel the incoming order
    CANCEL_RESTING   = "CANCEL_RESTING"  # cancel the resting order, try next
    CANCEL_BOTH      = "CANCEL_BOTH"     # cancel both orders
```

Detection is simple — compare `gateway_id` of the aggressor and the resting order:

```python
if _smp_action != SmpAction.NONE and _gw_id == best.gateway_id:
    if _smp_action == SmpAction.CANCEL_AGGRESSOR:
        aggressor.status = OrderStatus.CANCELLED
        events.append(aggressor)
        return                    # stop sweeping entirely

    elif _smp_action == SmpAction.CANCEL_RESTING:
        self._smp_cancel_resting(best, events)
        continue                  # skip this resting order, try next

    elif _smp_action == SmpAction.CANCEL_BOTH:
        self._smp_cancel_resting(best, events)
        aggressor.status = OrderStatus.CANCELLED
        events.append(aggressor)
        return                    # stop sweeping entirely
```

`CANCEL_RESTING` is the most interesting case — it removes the conflicting resting
order and **continues** the sweep loop with `continue`, looking for the next resting
order which may belong to a different participant and can fill legitimately.

`_smp_cancel_resting()` sets the resting order's status to CANCELLED, removes it
from both indexes (`_order_index`, `_entry_index`), decrements the qty index, and
appends the cancelled order to `events` so the gateway is notified.

---

## Stop Orders — Two Heaps

After every trade, `_check_stops` runs:

```python
def _check_stops(self, now):
    if self.last_trade_price is None:
        return []

    triggered = []

    # BUY stops: fire when price rises to/above stop_price
    while self._buy_stops:
        entry = self._buy_stops[0]
        stop_price, _ = entry.key
        if self.last_trade_price < stop_price:
            break            # ← min-heap: if top hasn't triggered, none will
        heapq.heappop(self._buy_stops)
        # convert to MARKET or LIMIT and add to triggered list
        ...

    # SELL stops: fire when price falls to/below stop_price
    while self._sell_stops:
        entry = self._sell_stops[0]
        neg_stop_price, _ = entry.key
        stop_price = -neg_stop_price
        if self.last_trade_price > stop_price:
            break            # ← max-heap: if top hasn't triggered, none will
        ...
```

The `break` statement is the crucial insight. Because the heap is sorted:

- **Buy stops min-heap**: if the stop at the top has a higher trigger price than
  the last trade, all remaining stops also have higher trigger prices. None will
  fire. We can stop immediately.
- **Sell stops max-heap**: same logic inverted.

This makes stop checking O(1) in the common case (no stops triggered) and O(k log k)
when k stops fire. A naive linear scan over all pending stops would be O(s) on every
trade, where s is the total number of pending stops.

---

## Trailing Stops — The Ratchet

**A concrete scenario:** You bought 100 shares of AAPL at $150.00. You want to
protect your profit but also let the position run if the stock keeps rising. You set
a sell trailing stop with a trail offset of $2.00.

- Market at $150.00 → stop trigger at $148.00 (= $150.00 - $2.00)
- Market rises to $155.00 → stop ratchets up to $153.00 (= $155.00 - $2.00)
- Market rises to $160.00 → stop ratchets up to $158.00 (= $160.00 - $2.00)
- Market then falls to $158.00 → stop FIRES, position is sold

The key rule: the stop only ever tightens (moves to protect more profit), never
loosens. If the market falls from $160 to $159, the stop stays at $158.

```python
for order in self._trailing_stops:
    if order.side == Side.SELL:
        # Ratchet up: if price rises, tighten the stop
        candidate = trade_price - order.trail_offset
        if candidate > order.stop_price:
            order.stop_price = candidate   # stop rises, never falls

        # Trigger if price has fallen to the stop
        if trade_price <= order.stop_price:
            # convert to MARKET and add to triggered
            ...
```

The ratchet rule: **the stop only tightens, never loosens.** For a sell trailing
stop, if the market rises the stop rises with it (protecting more profit). But if
the market falls, the stop stays where it is and may trigger.

Trailing stops are kept in a simple list rather than a heap because their trigger
price changes on every trade — maintaining heap order would require re-heapifying
on every price update, which is expensive. The list is iterated in full on every
trade, but trailing stop lists are typically short.

In EduMatcher, both `trade_price` and `order.trail_offset` are integer tick counts,
so the subtraction `candidate = trade_price - order.trail_offset` is exact integer
arithmetic with no floating-point drift.

---

## The `snapshot()` Method

`snapshot()` builds the view of the order book that gets published as market data to
display processes (viewer, board, ticker). It produces the aggregated picture a
market participant would see on their screen — total quantities at each price level,
not individual orders.

### Spread and Mid Price Are Derived Values

The `OrderBook` stores no `spread` or `mid_price` field. These are always computed
fresh from the heap:

```python
def snapshot(self):
    best_bid = self._peek(self._bids)   # O(1) — top of bid heap
    best_ask = self._peek(self._asks)   # O(1) — top of ask heap

    spread   = None
    mid      = None
    if best_bid is not None and best_ask is not None:
        spread = best_ask.price - best_bid.price      # e.g. 21 - 20 = 1 tick
        mid    = (best_ask.price + best_bid.price) / 2
```

**Why derive rather than store?** The best bid and best ask change every time an
order is added, cancelled, or filled. Keeping a `spread` field in sync would require
updating it in `_rest()`, `cancel_order()`, and `_apply_fill()` — three places that
already have enough to update. Deriving it in `snapshot()` is both correct and
free: `_peek()` is O(1) and `snapshot()` is already doing those peeks to build
the price level lists.

**What if one side is empty?** If there are no resting asks (all sellers have left),
`best_ask is None`, so there is no spread and no mid price. The snapshot is
published with `spread: null` and `mid: null`. Display tools must handle this case
and not divide by zero or assume a mid exists.

```python
    bids = {}
    asks = {}

    for entry in self._bids:
        if not entry.valid:
            continue
        o = entry.order
        if o.status in (FILLED, CANCELLED, ...):
            continue
        # For iceberg: show only the visible peak, not the hidden reserve
        qty = o.displayed_qty if o.order_type == ICEBERG else o.remaining_qty
        # Aggregate into price levels
        lvl = bids.setdefault(o.price, {"price": o.price, "qty": 0, "count": 0})
        lvl["qty"] += qty
        lvl["count"] += 1
    ...
```

`snapshot()` iterates the entire heap — O(n) — to build the aggregated price
levels needed for market data publication. This is correct but expensive if called
on every trade.

Note that `snapshot()` shows only `displayed_qty` for icebergs — the same visible
portion that `_bid_qty` tracks. A market participant viewing the snapshot sees 300
shares at a price level where an iceberg has 3,000 hidden shares. This is
intentional: icebergs are supposed to be hidden. But it means the public depth view
has the same undercount as the FOK check.

For high-frequency market data publishing, use the `_bid_qty` / `_ask_qty` price-
level index instead — it gives total visible quantity per price level in O(P) without
iterating individual orders. Reserve `snapshot()` for full depth snapshots needed
less frequently, such as when a client connects and needs the full current book
state.

---

## Data Structure Summary

| Structure | Type | Key | Value | Purpose |
|---|---|---|---|---|
| `_bids` | Heap | `(-price_ticks, timestamp_ns)` | `_HeapEntry` | Best bid, price-time order |
| `_asks` | Heap | `(price_ticks, timestamp_ns)` | `_HeapEntry` | Best ask, price-time order |
| `_buy_stops` | Heap | `(stop_price_ticks, ts_ns)` | `_HeapEntry` | Buy stop triggers |
| `_sell_stops` | Heap | `(-stop_price_ticks, ts_ns)` | `_HeapEntry` | Sell stop triggers |
| `_trailing_stops` | List | — | `Order` | Trailing stop ratchet updates |
| `_order_index` | Dict | `order_id` | `Order` | O(1) order lookup by ID |
| `_entry_index` | Dict | `order_id` | `_HeapEntry` | O(1) lazy deletion |
| `_bid_qty` | Dict | `price_ticks` | `int` | O(P) depth / FOK check |
| `_ask_qty` | Dict | `price_ticks` | `int` | O(P) depth / FOK check |
| `recent_trades` | Deque | — | `Trade` | Rolling last-20-trades window |

---

## Complexity Summary

| Operation | Complexity | Notes |
|---|---|---|
| Insert resting order | O(log n) | heappush + 2 index dict entries + 1 qty dict update |
| Peek best order | O(1) amortised | lazy deletion in `_peek`; stale entries cleaned on the way |
| Cancel order | O(1) | two dict lookups + `valid=False` |
| Amend order (price change or qty increase) | O(log n) | invalidate old entry + re-insert |
| Amend order (qty decrease, same price) | O(1) | preserve priority, update qty index only |
| FOK availability check | O(P) | iterate `_bid_qty` / `_ask_qty` |
| Full book snapshot | O(n) | iterate all heap entries |
| Depth metrics | O(P) | iterate qty index only |
| Stop trigger check | O(1) amortised | heap peek + early break when top hasn't triggered |
| Stop trigger (k fired) | O(k log k) | k heappops + recursive `process()` call |

Where n = total resting orders, P = distinct price levels (typically P << n).

---

*Part of the EduMatcher documentation series. v4 — May 2026.*

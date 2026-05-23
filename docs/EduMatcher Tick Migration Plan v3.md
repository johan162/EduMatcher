# EduMatcher — Migration Plan v3: Integer Nanosecond Timestamps and Tick-Based Prices

> **No backward compatibility.** This plan assumes all persisted data files
> (`gtc_orders.json`, `book_stats.json`, `gtc_combos.json`) are deleted before
> the migrated engine starts. The old float-based JSON format is gone. Every
> `from_dict()` method assumes the new format exclusively.
> 
> **Reading order:** Read the *Why* sections first. The motivation for each
> change makes the implementation details easier to follow.

-----

## Table of Contents

1. [Why Nanosecond Timestamps?](#1-why-nanosecond-timestamps)
1. [Why Integer Tick Prices?](#2-why-integer-tick-prices)
1. [New Shared Infrastructure — `models/price.py`](#3-new-shared-infrastructure--modelspricepy)
1. [The Conversion Boundary Rule](#4-the-conversion-boundary-rule)
1. [Before You Start — Delete Persisted Data](#5-before-you-start--delete-persisted-data)
1. [Phase Order](#6-phase-order)
1. [Phase 1 — `models/order.py`](#7-phase-1--modelsorderpy)
1. [Phase 2 — `models/trade.py`](#8-phase-2--modelstradepy)
1. [Phase 3 — `models/combo.py`](#9-phase-3--modelscombopy)
1. [Phase 4 — `engine/order_book.py`](#10-phase-4--engineorder_bookpy)
1. [Phase 5 — `engine/auction.py`](#11-phase-5--engineauctionpy)
1. [Phase 6 — `engine/config_loader.py` and `engine_config.yaml`](#12-phase-6--engineconfig_loaderpy-and-engine_configyaml)
1. [Phase 7 — `engine/persistence.py`](#13-phase-7--enginepersistencepy)
1. [Phase 8 — `engine/main.py`](#14-phase-8--enginemainpy)
1. [Phase 9 — `models/message.py`](#15-phase-9--modelsmessagepy)
1. [Phase 10 — `gateway/main.py`](#16-phase-10--gatewaymainpy)
1. [Phase 11 — `clearing/main.py`](#17-phase-11--clearingmainpy)
1. [Phase 12 — `stats/main.py`](#18-phase-12--statsmainpy)
1. [Phase 13 — `viewer/main.py` and `board/main.py`](#19-phase-13--viewermainpy-and-boardmainpy)
1. [Phase 14 — `ticker/main.py`](#20-phase-14--tickermainpy)
1. [Phase 15 — `ai_trader/main.py` and `ai_trader/personality.py`](#21-phase-15--ai_tradermainpy-and-ai_traderpersonalitypy)
1. [Tests](#22-tests)
1. [Complete Change Summary](#23-complete-change-summary)
1. [Implementation Checklist](#24-implementation-checklist)

-----

## 1. Why Nanosecond Timestamps?

### The Current Problem

EduMatcher uses `time.time()` which returns a Python `float` of seconds since the
Unix epoch:

```python
# models/order.py — current
timestamp: float    # e.g. 1748000000.123456789
```

A 64-bit IEEE 754 float has 52 bits of mantissa — about 15–16 significant decimal
digits. At the current epoch (roughly 1.748 × 10⁹ seconds), the integer part
consumes 10 digits, leaving only 5–6 for the fractional part. This gives
**microsecond precision at best** in practice — not nanosecond.

More critically, two orders submitted in rapid succession can receive **identical
timestamps** if they arrive within the same float-representable increment:

```python
>>> t1 = time.time()
>>> t2 = time.time()
>>> t1 == t2    # can be True at high submission rates
True
```

When two orders share a timestamp at the same price, their queue ordering inside
the heap is non-deterministic — whichever entry happens to sit higher from
insertion, not the true arrival order. This violates price-time priority.

### The Solution

`time.time_ns()` returns an `int` of nanoseconds since epoch:

```python
>>> time.time_ns()
1748000000123456789    # integer, exact, no precision loss
```

Integer comparison is simpler, faster, and exact. Two consecutive calls to
`time.time_ns()` always return distinct values because the integer increments
each nanosecond. At 57,000 orders/second, consecutive orders are roughly 17,500
nanoseconds apart — well above the resolution of `time.time_ns()`.

**Additional benefit:** integer comparisons are ~5–10% faster than float in CPython,
directly improving the heap key comparison `(±price, timestamp_ns)` that runs on
every match.

-----

## 2. Why Integer Tick Prices?

### The Current Problem

Prices are stored as Python `float`:

```python
price: Optional[float] = None    # e.g. 150.30
```

IEEE 754 cannot exactly represent most decimal fractions:

```python
>>> 100.1 + 0.2
100.30000000000001    # not 100.30

>>> 150.30 == 150.10 + 0.20
False                 # should be True
```

This creates real bugs in the matching engine:

**Price comparison errors** — a resting order at `$150.30` and an aggressive order
also at `$150.30` may compare as unequal if they were computed via different
arithmetic paths.

**Dict key collisions** — `_bid_qty: dict[float, int]` uses float prices as keys.
Two mathematically-equal floats with different bit representations produce separate
entries, silently double-counting depth.

**Trailing stop drift** — `stop_price = last_price - trail_offset` accumulates
rounding error across many ratchet steps.

### The Solution: Tick-Based Integer Prices

Store prices as integer **tick counts** — the number of minimum price increments
from zero:

```python
# tick_decimals=2 means 1 tick = $0.01
$150.30  →  15030 ticks    # exact integer
$150.31  →  15031 ticks
15030 == 15030             # always True, no representation error
```

All internal arithmetic uses integers. Conversion to/from human-readable float
happens only at the I/O boundary: when parsing user input and when displaying.

### Tick Size Per Symbol

Different instruments have different minimum price increments. `tick_decimals`
encodes this as a power of ten:

```python
tick_decimals = 2    # 1 tick = $0.01  — US equities (default)
tick_decimals = 4    # 1 tick = $0.0001 — some FX pairs
```

Converting between float and ticks:

```python
ticks      = round(float_price * 10**tick_decimals)   # float → int (input boundary)
float_price = ticks / 10**tick_decimals                # int → float (display boundary)
```

Using `round()` on input absorbs the float representation error in the last digit,
giving the correct integer for any valid price.

-----

## 3. New Shared Infrastructure — `models/price.py`

Create this file first. Everything else in the plan imports from it.

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
    """Register tick precision for a symbol. Called once at startup."""
    if not (0 <= tick_decimals <= 8):
        raise ValueError(
            f"tick_decimals must be 0–8, got {tick_decimals} for {symbol}"
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

-----

## 4. The Conversion Boundary Rule

Before reading any phase, internalise this rule — it governs every decision:

```
┌──────────────────────────────────────────────────────────────┐
│                      OUTSIDE THE ENGINE                       │
│  float prices (user types "150.30")                          │
│  float timestamps are gone — everything uses int ns now      │
│                                                              │
│  INPUT BOUNDARY        ──────────────────────────────────►   │
│  to_ticks()            float price → int ticks               │
│  time.time_ns()        (no input conversion for timestamps)  │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│                      INSIDE THE ENGINE                        │
│  int ticks for all prices                                    │
│  int nanoseconds for all timestamps                          │
│  All arithmetic is integer — exact, no drift                 │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  OUTPUT BOUNDARY       ◄──────────────────────────────────   │
│  from_ticks()          int ticks → float price               │
│  ns / 1e9              int ns → float seconds (display only) │
│                                                              │
│  float prices (display, CSV, ZMQ JSON messages)              │
└──────────────────────────────────────────────────────────────┘
```

**ZMQ messages carry float prices.** The engine converts ticks to float before
publishing. Subscribers receive float and display directly. This keeps subscriber
processes simple — they do not need access to the tick registry.

**The gateway is an input boundary.** It receives `PRICE=150.30` from the user,
parses it as `float`, and sends that float in the JSON payload to the engine. The
engine converts to ticks on receipt. The gateway never calls `to_ticks()`.

-----

## 5. Before You Start — Delete Persisted Data

No backward compatibility means old persisted files will be parsed incorrectly.
Delete them before starting the migrated engine:

```bash
rm -f data/gtc_orders.json
rm -f data/book_stats.json
rm -f data/gtc_combos.json
```

These files are recreated automatically on the next clean engine shutdown. The
`clearing_report.csv` and `data/stats.db` do not need to be deleted — they are
append-only logs that are not read back by the engine.

-----

## 6. Phase Order

Implement phases strictly in this sequence. Later phases depend on earlier ones.

> **Navigation note:** The document sections are numbered from 1 onwards (for the
> Table of Contents), but the phases themselves are numbered starting at 0. The
> mapping is: **document section N contains Phase N − 6**. For example, Phase 1
> (`models/order.py`) is in document section 7. The table below is the definitive
> reference — use it to find the right section for each phase.

|Phase |File                                            |Document Section|Dependency                  |
|------|------------------------------------------------|----------------|----------------------------|
|**0** |`models/price.py`                               |Section 3       |None — create this first    |
|**1** |`models/order.py`                               |Section 7       |Needs `price.py`            |
|**2** |`models/trade.py`                               |Section 8       |Needs `price.py`            |
|**3** |`models/combo.py`                               |Section 9       |Needs `order.py`            |
|**4** |`engine/order_book.py`                          |Section 10      |Needs `order.py`, `trade.py`|
|**5** |`engine/auction.py`                             |Section 11      |Needs `order_book.py`       |
|**6** |`engine/config_loader.py` + `engine_config.yaml`|Section 12      |Needs `price.py`            |
|**7** |`engine/persistence.py`                         |Section 13      |Needs `order.py`, `price.py`|
|**8** |`engine/main.py`                                |Section 14      |Needs everything above      |
|**9** |`models/message.py`                             |Section 15      |Needs `price.py`            |
|**10**|`gateway/main.py`                               |Section 16      |Needs `message.py`          |
|**11**|`clearing/main.py`                              |Section 17      |Needs `trade.py`            |
|**12**|`stats/main.py`                                 |Section 18      |Needs `trade.py`            |
|**13**|`viewer/main.py`, `board/main.py`               |Section 19      |Needs snapshot format       |
|**14**|`ticker/main.py`                                |Section 20      |Needs snapshot format       |
|**15**|`ai_trader/main.py`, `personality.py`           |Section 21      |Needs snapshot format       |

Run the full test suite after each phase before moving to the next. After Phase 4
(`order_book.py`) in particular, run tests before continuing — this is the most
likely phase to introduce a subtle regression.

-----

## 7. Phase 1 — `models/order.py`

This is the most fundamental change. Every downstream phase follows from it.

### 7.1 Change field types

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
stop_price:  Optional[int] = None   # ticks
trail_offset: Optional[int] = None  # ticks — trail distance in tick units
```

`trail_offset` in ticks means the ratchet arithmetic `stop_price = last_price - trail_offset` is exact integer subtraction, eliminating drift across many steps.

### 7.2 Update `Order.create()`

Change parameter types and the timestamp call:

```python
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
        timestamp=time.time_ns(),     # ← int nanoseconds
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

### 7.3 Update `to_dict()`

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

### 7.4 Update `from_dict()`

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

Clean, flat, no branching. The `__new__` bypass and pre-built enum maps are
preserved from the original for performance.

-----

## 8. Phase 2 — `models/trade.py`

### 8.1 Change field types

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

### 8.2 Update `Trade.create()`

```python
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
        timestamp=now if now is not None else time.time_ns(),
    )
```

### 8.3 Update `to_dict()`

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

### 8.4 Update `from_dict()`

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

-----

## 9. Phase 3 — `models/combo.py`

### 9.1 Update `ComboLeg` field types

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

### 9.2 Update `ComboLeg.to_dict()` and `from_dict()`

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

### 9.3 Update `ComboOrder.timestamp`

**Current:**

```python
timestamp: float
...
timestamp=time.time(),
```

**New:**

```python
timestamp: int    # nanoseconds
...
timestamp=time.time_ns(),
```

Update `to_dict()` to keep `timestamp` as int and `from_dict()` to read it
directly without conversion:

```python
# to_dict():
"timestamp": self.timestamp,   # int nanoseconds — no conversion

# from_dict():
combo.timestamp = d["timestamp"]   # int nanoseconds — no conversion
```

-----

## 10. Phase 4 — `engine/order_book.py`

This file has the most internal changes — every price-related type annotation,
heap key, and dictionary changes from float to int. The matching logic itself
requires almost no structural change because integer arithmetic and comparison
work identically to float for addition, subtraction, and `>`, `<`, `==`.

### 10.1 Update module docstring comments

```python
#  _bids  max-heap: list of (-price_ticks, timestamp_ns, order)
#  _asks  min-heap: list of ( price_ticks, timestamp_ns, order)
#  _buy_stops  min-heap of (stop_price_ticks, timestamp_ns, order)
#  _sell_stops max-heap of (-stop_price_ticks, timestamp_ns, order)
#  _bid_qty / _ask_qty : dict[price_ticks, int]
```

### 10.2 Update `__init__` type annotations

```python
self._bid_qty:  dict[int, int] = {}   # price_ticks → total resting qty
self._ask_qty:  dict[int, int] = {}

self.last_trade_price: Optional[int] = None   # ticks
self.last_trade_qty:   Optional[int] = None
self.last_buy_price:   Optional[int] = None   # ticks
self.last_sell_price:  Optional[int] = None   # ticks
```

### 10.3 Update `process()` signature

```python
def process(
    self, order: Order, *, match: bool = True, now: int | None = None
) -> tuple[list[Trade], list[Order]]:
    ...
    if now is None:
        now = time.time_ns()    # int nanoseconds
```

### 10.4 Update `cancel_order()`

No changes to the method body — it operates on order IDs and boolean flags.
The call to `_deduct_qty_index` takes `order.price` which is now `int`, but
`_deduct_qty_index` itself uses the value as a dict key, which works identically
for int and float.

### 10.5 Update `amend_order()` signature

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
        now = time.time_ns()

    ...
    if price <= 0:    # int comparison — exact
        return None, False, "Price must be positive"
```

The rest of `amend_order` operates on `order.price` (now `int`) and dict keys
(now `int`). No other body changes are needed.

### 10.6 Update `restore_stats()`

```python
def restore_stats(
    self,
    last_buy_price:  Optional[int],   # ticks
    last_sell_price: Optional[int],   # ticks
) -> None:
    self.last_buy_price  = last_buy_price
    self.last_sell_price = last_sell_price
```

### 10.7 Update `snapshot()`

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
            o.displayed_qty
            if o.order_type == OrderType.ICEBERG
            else o.remaining_qty
        )
        lvl = bids.setdefault(price_ticks, {"price": price_ticks, "qty": 0, "count": 0})
        lvl["qty"]   += qty
        lvl["count"] += 1

    for entry in self._asks:
        if not entry.valid:
            continue
        o = entry.order
        if o.status in (FILLED, CANCELLED, REJECTED, EXPIRED):
            continue
        price_ticks = o.price
        qty = (
            o.displayed_qty
            if o.order_type == OrderType.ICEBERG
            else o.remaining_qty
        )
        lvl = asks.setdefault(price_ticks, {"price": price_ticks, "qty": 0, "count": 0})
        lvl["qty"]   += qty
        lvl["count"] += 1

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
        "recent_trades": [t.to_dict() for t in list(self.recent_trades)[-5:]],
    }
```

### 10.8 Update `_sweep()` and `_sweep_iceberg()`

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

### 10.9 Update `_available_qty()`

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

### 10.10 Update `_apply_fill()`

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
    if aggressor.side == Side.BUY:
        self.last_buy_price  = fill_price
    else:
        self.last_sell_price = fill_price
```

### 10.11 Update `_rest()` and `_reinsert_iceberg()`

The heap key becomes `(-int_price, int_timestamp)` — structurally identical, now
using integer types throughout:

```python
def _rest(self, order: Order) -> None:
    assert order.price is not None
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

### 10.12 Update `_check_stops()`

```python
def _check_stops(self, now: int) -> list[Order]:   # now: int nanoseconds
    if self.last_trade_price is None:
        return []
    ...
    while self._buy_stops:
        entry = self._buy_stops[0]
        stop_price, _ = entry.key
        if self.last_trade_price < stop_price:   # int < int — exact
            break
        ...
        stop_order.timestamp = now    # int nanoseconds
    ...
```

### 10.13 Update `_check_trailing_stops()`

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

-----

## 11. Phase 5 — `engine/auction.py`

### 11.1 Update `AuctionResult`

```python
@dataclass
class AuctionResult:
    eq_price:       int | None   # ticks, or None when no crossable interest
    eq_qty:         int
    surplus:        int
    imbalance_side: str
```

### 11.2 Update `compute_equilibrium()`

All price variables become `int`. Replace the `float("inf")` sentinel with a
large integer:

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

### 11.3 Update `execute_uncross()`

```python
def execute_uncross(
    book:     "OrderBook",
    eq_price: int,            # ticks
) -> tuple[list[Trade], list[Order]]:
    trades: list[Trade] = []
    events: list[Order] = []
    now = time.time_ns()      # int nanoseconds

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

-----

## 12. Phase 6 — `engine/config_loader.py` and `engine_config.yaml`

### 12.1 Add `tick_decimals` to `SymbolConfig`

```python
@dataclass
class SymbolConfig:
    name:                str
    tick_decimals:       int = 2             # 1 tick = $0.01 by default
    last_buy_price:      Optional[float] = None   # float in YAML; converted to ticks in engine
    last_sell_price:     Optional[float] = None
    market_maker_orders: list[str] = field(default_factory=list)
```

### 12.2 Parse `tick_decimals` in `load_engine_config()`

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

### 12.3 Add `tick_decimals` to `engine_config.yaml`

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

-----

## 13. Phase 7 — `engine/persistence.py`

GTC orders are saved via `Order.to_dict()` (which now emits float prices and int
timestamps) and reloaded via `Order.from_dict()` (which converts float prices to
ticks). The round-trip is lossless for any price with at most `tick_decimals`
decimal places — which is always true for valid orders.

### 13.1 Update `save_book_stats()`

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
the caller in `engine/main.py` converts to ticks (see Phase 8, Section 14.2).

No change to `save_gtc_orders()`, `load_gtc_orders()`, `save_gtc_combos()`, or
`load_gtc_combos()` — these delegate to `to_dict()` / `from_dict()` which already
handle the conversion.

-----

## 14. Phase 8 — `engine/main.py`

This file has the most call-sites to update. Work through them in the order shown.

### 14.1 Register tick decimals at startup

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

### 14.2 Convert seeded last prices to ticks

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

### 14.3 Update the market-maker order parser

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

### 14.4 Update `_handle_new_order()`

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
    ...
    # TRAILING_STOP: initialise stop_price from last trade if not supplied
    if order.order_type == OrderType.TRAILING_STOP and order.stop_price is None:
        if book.last_trade_price is None:
            # reject — no reference price available
            ...
        else:
            if order.side == Side.SELL:
                order.stop_price = book.last_trade_price - order.trail_offset
            else:
                order.stop_price = book.last_trade_price + order.trail_offset
            # Both operands are int ticks — exact integer arithmetic

    now = time.time_ns()    # int nanoseconds
    trades, events = book.process(order, match=do_match, now=now)
    ...
```

### 14.5 Update fill event publication

`book.last_trade_price` is now `int` ticks. Convert to float before publishing:

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

### 14.6 Update `time.time()` calls

Search for `time.time()` in `engine/main.py` — there are exactly two occurrences,
both in order-handling functions. Change each one:

```python
# In _handle_new_order():
now = time.time()     →     now = time.time_ns()

# In _handle_amend_order():
now = time.time()     →     now = time.time_ns()
```

To find them quickly: `grep -n "time\.time()" src/edumatcher/engine/main.py`

The `time.monotonic()` call in `_flush_snapshots()` is for throttle timing (elapsed
wall-clock seconds between snapshot flushes), not an epoch timestamp — leave it
as `float`. It controls how often snapshots are sent, not when events happened.

### 14.7 Update `_handle_amend_order()`

The amend payload carries a float price from the gateway. Convert to ticks before
passing to the order book. Then convert back to float when publishing the amended
price in the response message:

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
        now=time.time_ns(),          # int nanoseconds
    )
    ...
    # When publishing the amended order's price back to the gateway:
    # Convert ticks back to float so the gateway can display it
    amended_price_float = (
        from_ticks(amended.price, amended.symbol)
        if amended.price is not None else None
    )
```

### 14.8 Update auction call-sites

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

### 14.9 Add `tick_decimals` to book snapshot messages

Subscribers that receive book snapshots need the tick precision to correctly
re-convert if needed. Add it to the snapshot dict in `_flush_snapshots()`:

```python
from edumatcher.models.price import get_tick_decimals

snapshot = book.snapshot()
snapshot["tick_decimals"] = get_tick_decimals(symbol)
self.pub_sock.send_multipart(make_book_msg(symbol, snapshot))
```

### 14.10 Combo and OCO leg prices

In `_accept_combo()`, leg prices come from `ComboLeg.price` (now `int` ticks).
Pass directly to `Order.create()` — no conversion:

```python
child = Order.create(
    symbol=leg.symbol,
    side=leg.side,
    order_type=leg.order_type,
    quantity=leg.quantity,
    gateway_id=combo.gateway_id,
    tif=combo.tif,
    price=leg.price,           # int ticks — no conversion
    stop_price=leg.stop_price, # int ticks — no conversion
)
```

In `_handle_oco_order()`, prices arrive in JSON as floats. Convert at entry:

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

-----

## 15. Phase 9 — `models/message.py`

`message.py` provides helper functions that wrap ZMQ messages. Where these
functions accept price arguments, the callers now pass `int` ticks. The message
functions must convert to float before encoding.

### 15.1 Update `make_fill_msg()`

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

### 15.2 Update `make_auction_result_msg()`

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

### 15.3 Update `make_ack_msg()` where it includes order prices

If `make_ack_msg()` encodes `order.price` or `order.stop_price`, convert to float:

```python
if order is not None:
    from edumatcher.models.price import from_ticks
    payload["price"] = (
        from_ticks(order.price, order.symbol)
        if order.price is not None else None
    )
```

-----

## 16. Phase 10 — `gateway/main.py`

The gateway is the user-facing input boundary. It parses float prices typed by
the user and sends them as floats in the JSON payload. The engine converts to ticks
on receipt. **The gateway never calls `to_ticks()`.**

### 16.1 Order command parser — no change to price parsing

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

### 16.2 Update timestamp display

The gateway receives `timestamp` fields in order status messages. They are now `int`
nanoseconds. Add a module-level helper and use it wherever timestamps are formatted:

```python
# Add near the top of gateway/main.py:
def _fmt_timestamp(ts: int | float) -> str:
    """Format a nanosecond int timestamp as HH:MM:SS."""
    from datetime import datetime
    seconds = ts / 1_000_000_000 if isinstance(ts, int) and ts > 10**12 else float(ts)
    return datetime.fromtimestamp(seconds).strftime("%H:%M:%S")

# Replace:
ts = datetime.fromtimestamp(od["timestamp"]).strftime("%H:%M:%S")
# With:
ts = _fmt_timestamp(od["timestamp"])
```

### 16.3 Fill and amend display — no change needed

Fill messages from the engine already carry float prices (converted before
publishing). The gateway displays them with the existing `:.4f` format strings.

-----

## 17. Phase 11 — `clearing/main.py`

The clearing process subscribes to `trade.executed` messages. After Phase 8, these
carry **float prices** (converted by the engine before publishing via
`Trade.to_dict()`). The `PositionRecord` works with float internally and requires
no type changes.

The only required change is timestamp formatting:

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
1. In `_receive()` — the console print

-----

## 18. Phase 12 — `stats/main.py`

The stats process receives trade events and book snapshots carrying float prices.
No price type changes are needed. Only timestamp handling changes:

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
1. In the snapshot interval check — reading book snapshot timestamps if stored

SQLite stores prices as `REAL` (float). Since the stats process already receives
float prices from message payloads, the SQLite schema requires no change.

-----

## 19. Phase 13 — `viewer/main.py` and `board/main.py`

Both viewer and board receive book snapshots that carry float prices (from the
engine’s `snapshot()` output boundary). All `lvl["price"]` values are already float.
The `:.4f` format strings work without change.

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

-----

## 20. Phase 14 — `ticker/main.py`

The ticker reads prices from SQLite (`REAL` columns — already float) and from
book snapshot messages (already float). No price changes needed.

If the ticker reads `timestamp` fields from ZMQ message payloads, apply the same
nanosecond-to-seconds conversion:

```python
def _ns_to_time_str(ts: int) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(ts / 1_000_000_000).strftime("%H:%M:%S")
```

The ticker’s `time.monotonic()` calls for display refresh intervals are unaffected.

-----

## 21. Phase 15 — `ai_trader/main.py` and `ai_trader/personality.py`

The AI trader operates entirely in the float world as a client of the exchange.
It reads book snapshots (float prices), computes float limit prices, and submits
them through the gateway (which sends floats to the engine).

**`personality.py` — no changes.** The `tick_size: float = 0.01` field is used for
display-world price computation before order submission. It remains float.

**`ai_trader/main.py` — timestamp handling only.** If the AI trader reads
`timestamp` fields from message payloads for timing logic, apply the nanosecond
conversion. The existing `_as_float()` helper in `ai_trader/main.py` converts
price values safely from book snapshot messages — since those prices are already
float (the engine converts before publishing), `_as_float()` continues to work
without change. Do not apply `_as_float()` to timestamps — use the
`_ns_to_time_str()` pattern from Phase 13 instead.

The time-based fields (`reject_window_sec`, `stale_data_sec`, etc.) use
`time.monotonic()` for duration measurement — these are not timestamps and require
no change.

-----

## 22. Tests

Run the full existing test suite after Phase 4 to catch any regressions in the
matching engine before touching subscriber processes.

### A note on test isolation

The `_tick_decimals` registry in `models/price.py` is a **module-level singleton**
— a plain Python dict that persists for the entire test session. If two test files
both call `register_tick_decimals("AAPL", 2)` that is fine — same value, no
conflict. But if one test registers `"AAPL"` with `tick_decimals=2` and another
registers `"AAPL"` with `tick_decimals=4`, one will overwrite the other silently.

The `setup_function()` calls in the test files below use `pytest`’s convention for
running code before each test function in the module. They register symbols before
each test so the registry is always populated correctly for that test.

If you write tests that use unusual `tick_decimals` values, register them in your
`setup_function()` and document the choice.

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

```python
"""Integer ratchet arithmetic must not accumulate error over many steps."""
import time
from edumatcher.engine.order_book import OrderBook
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
        book._check_trailing_stops(time.time_ns())

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
    book._check_trailing_stops(time.time_ns())
    assert stop.stop_price == 15050

    # Price drops to $150.70 — stop must NOT move down
    book.last_trade_price = 15070
    book._check_trailing_stops(time.time_ns())
    assert stop.stop_price == 15050   # unchanged
```

### `tests/test_matching_integer_prices.py`

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

-----

## 23. Complete Change Summary

### Files requiring changes

|File                     |Changes                                                                                                                                                                                                                                                                                                                                           |
|-------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|`models/price.py`        |**NEW** — `register_tick_decimals`, `to_ticks`, `from_ticks`, `format_price`                                                                                                                                                                                                                                                                      |
|`models/order.py`        |`timestamp/price/stop_price/trail_offset`: float→int; `create()`: `time.time_ns()`; `to_dict()`: `from_ticks` on prices; `from_dict()`: `to_ticks` on prices, direct int timestamp                                                                                                                                                                |
|`models/trade.py`        |`price/timestamp`: float→int; `create()`: `time.time_ns()`; `to_dict()`: `from_ticks`; `from_dict()`: `to_ticks`, direct int timestamp                                                                                                                                                                                                            |
|`models/combo.py`        |`ComboLeg.price/stop_price`: float→int; `ComboOrder.timestamp`: float→int; `to_dict`/`from_dict`: same pattern                                                                                                                                                                                                                                    |
|`models/message.py`      |`make_fill_msg`, `make_auction_result_msg`, `make_ack_msg`: accept int ticks, convert to float before encode                                                                                                                                                                                                                                      |
|`engine/order_book.py`   |`_bid_qty/_ask_qty`: dict[float]→dict[int]; `last_trade/buy/sell_price`: float→int; `process/amend`: `now` float→int; `_sweep/_apply_fill`: `price_limit/now/fill_price` float→int; `_rest/_reinsert`: heap keys now int; `_check_stops/_check_trailing_stops`: `now` int; `snapshot()`: `from_ticks` on output; `restore_stats`: params float→int|
|`engine/auction.py`      |`AuctionResult.eq_price`: float→int; `compute_equilibrium`: dict types int, `float("inf")`→large int; `execute_uncross`: `eq_price` int, `time.time_ns()`                                                                                                                                                                                         |
|`engine/config_loader.py`|`SymbolConfig`: add `tick_decimals: int = 2`; `load_engine_config()`: parse and validate `tick_decimals`                                                                                                                                                                                                                                          |
|`engine_config.yaml`     |Add `tick_decimals: 2` to each symbol                                                                                                                                                                                                                                                                                                             |
|`engine/persistence.py`  |`save_book_stats()`: `from_ticks` before JSON; no other changes                                                                                                                                                                                                                                                                                   |
|`engine/main.py`         |`_load_config()`: `register_tick_decimals`, `to_ticks` for seed prices; MM order parser: `to_ticks`; `_handle_new_order()`: `to_ticks` on all prices; `_handle_amend_order()`: `to_ticks`; fill publication: `from_ticks`; auction: `from_ticks`; 2× `time.time()` → `time.time_ns()`; snapshot: add `tick_decimals`                              |
|`gateway/main.py`        |Add `_fmt_timestamp()` helper; apply wherever `od["timestamp"]` is formatted                                                                                                                                                                                                                                                                      |
|`clearing/main.py`       |Add `_fmt_ts()` helper; replace 2× `datetime.fromtimestamp(trade.timestamp, ...)`                                                                                                                                                                                                                                                                 |
|`stats/main.py`          |Add `_ns_to_dt()` helper; replace all `datetime.fromtimestamp(payload_ts, ...)`                                                                                                                                                                                                                                                                   |
|`viewer/main.py`         |Add `_ns_to_time_str()` helper; replace `datetime.fromtimestamp(tr["timestamp"])`                                                                                                                                                                                                                                                                 |
|`board/main.py`          |Same timestamp helper; apply to trade timestamp display                                                                                                                                                                                                                                                                                           |
|`ticker/main.py`         |Apply timestamp helper if reading message timestamps                                                                                                                                                                                                                                                                                              |
|`ai_trader/main.py`      |Apply timestamp helper if reading message timestamps                                                                                                                                                                                                                                                                                              |

### Files requiring no changes

|File                      |Reason                                                              |
|--------------------------|--------------------------------------------------------------------|
|`messaging/bus.py`        |No prices or timestamps                                             |
|`scheduler/main.py`       |Uses `time.monotonic()` for scheduling; no price or epoch timestamps|
|`audit/main.py`           |Logs raw JSON; prices already float in payloads; timestamps opaque  |
|`orders/main.py`          |Displays JSON dict fields; prices already float                     |
|`models/session.py`       |No prices or timestamps                                             |
|`ai_trader/personality.py`|`tick_size: float` is display-world; no changes needed              |

### Conversion functions used per zone

|Zone                                               |Function                                         |Direction                   |
|---------------------------------------------------|-------------------------------------------------|----------------------------|
|Engine input (gateway payload, config, FIX strings)|`to_ticks(float, symbol)`                        |float → int                 |
|Engine internal                                    |none — everything is int                         |—                           |
|Engine output (ZMQ publish, `to_dict()`, CSV)      |`from_ticks(int, symbol)`                        |int → float                 |
|Display (viewer, board, ticker, gateway, clearing) |`from_ticks()` or receive already-converted float|int → float or already float|

**“Already float” explained:** Subscriber processes (viewer, board, clearing, stats)
receive prices via ZMQ messages. Those messages carry float prices because the engine
calls `from_ticks()` before publishing. So by the time a price arrives in a subscriber,
it is already a Python `float` — the subscriber does not need to call `from_ticks()`
itself. The only time a subscriber would call `from_ticks()` is if it were doing its
own internal tick arithmetic, which none of the current subscribers do.

-----

## 24. Implementation Checklist

Use this to track progress. Tick each item only after the corresponding test passes.

### Phase 0 — `models/price.py` (new file)

- [ ] `register_tick_decimals()`, `get_tick_decimals()` implemented
- [ ] `to_ticks()` uses `round()` — not `int()` or truncation
- [ ] `from_ticks()` and `format_price()` implemented
- [ ] `DEFAULT_TICK_DECIMALS = 2` module-level constant present
- [ ] `tests/test_price.py` passes (all 7 test functions)

### Phase 1 — `models/order.py`

- [ ] `timestamp: int`, `price: Optional[int]`, `stop_price: Optional[int]`, `trail_offset: Optional[int]`
- [ ] `Order.create()` calls `time.time_ns()`
- [ ] `to_dict()` calls `from_ticks()` on price fields; keeps timestamp as int
- [ ] `from_dict()` calls `to_ticks()` on price fields; reads timestamp as int directly
- [ ] No `isinstance` compat guards anywhere in `from_dict()`
- [ ] `tests/test_order_timestamps.py` passes

### Phase 2 — `models/trade.py`

- [ ] `price: int`, `timestamp: int`
- [ ] `Trade.create()` calls `time.time_ns()` as fallback
- [ ] `to_dict()` calls `from_ticks()` on price
- [ ] `from_dict()` calls `to_ticks()` on price; reads timestamp as int

### Phase 3 — `models/combo.py`

- [ ] `ComboLeg.price: Optional[int]`, `ComboLeg.stop_price: Optional[int]`
- [ ] `ComboOrder.timestamp: int`; `create()` calls `time.time_ns()`
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
- [ ] `execute_uncross()`: `eq_price: int`, `time.time_ns()`

### Phase 6 — `engine/config_loader.py` and `engine_config.yaml`

- [ ] `SymbolConfig.tick_decimals: int = 2` added
- [ ] `load_engine_config()` parses and validates `tick_decimals` (0–8)
- [ ] `engine_config.yaml`: `tick_decimals: 2` added to every symbol

### Phase 7 — `engine/persistence.py`

- [ ] `save_book_stats()` calls `from_ticks()` before writing JSON
- [ ] No other changes needed (GTC order round-trip works via `to_dict`/`from_dict`)

### Phase 8 — `engine/main.py`

- [ ] `_load_config()` calls `register_tick_decimals()` first for every symbol
- [ ] Seed prices converted with `to_ticks()` before `book.restore_stats()`
- [ ] MM order parser converts with `to_ticks()` immediately after parsing
- [ ] `_handle_new_order()` converts all prices with `to_ticks()`
- [ ] `_handle_amend_order()` converts price with `to_ticks()`; publishes with `from_ticks()`
- [ ] Fill publication converts `last_trade_price` and `evt.price` with `from_ticks()`
- [ ] Auction call-sites convert `eq_price` with `from_ticks()` before publishing
- [ ] Both `time.time()` calls changed to `time.time_ns()`
- [ ] `time.monotonic()` in `_flush_snapshots()` left as float (intentional)
- [ ] `tick_decimals` added to book snapshot dict
- [ ] Combo and OCO leg prices handled correctly (ticks passed through / converted at JSON boundary)

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

-----

*EduMatcher Tick Migration Plan v3 — May 2026.*
*Delete `data/gtc_orders.json`, `data/book_stats.json`, and `data/gtc_combos.json`*
*before starting the migrated engine. Implement phases in order.*
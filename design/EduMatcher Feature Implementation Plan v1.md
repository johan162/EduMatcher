# EduMatcher — Feature Implementation Plan 

> **Audience:** A developer new to the codebase. Read this document top-to-bottom
> before writing a single line of code. Each phase depends on the previous one.
>
> **No backward compatibility.** Delete persisted data files before starting:
> ```bash
> rm -f data/gtc_orders.json data/book_stats.json data/gtc_combos.json
> ```
>
> **Tick migration assumed complete.** Integer ticks for all prices, integer
> nanoseconds for all timestamps. See `EduMatcher_Tick_Migration_Plan_v6.md`.
>
> **Clock:** Use `monotonic_ns()` from `models/clock.py` everywhere a timestamp
> is needed — never call `time.time_ns()` directly. `monotonic_ns()` wraps it
> with a strictly-increasing guarantee even when the system clock steps backward.

---
## High-Level Roadmap

| Phase | Feature | Files Touched |
|-------|---------|---------------|
| **1** | Instrument halt state | `engine/main.py`, `models/instrument.py` *(new)* |
| **2** | Kill switch | `gateway/main.py`, `engine/main.py`, `models/message.py` |
| **3** | Price collar bands | `engine/collar.py` *(new)*, `engine/main.py` |
| **4** | Circuit breaker | `engine/circuit_breaker.py` *(new)*, `engine/main.py` |
| **5** | Depth metrics and market data | `engine/order_book.py`, `models/message.py` |
| **6** | Drop copy publisher | `engine/drop_copy.py` *(new)*, `engine/main.py` |
| **7** | Config extensions | `engine/config_loader.py`, `engine_config.yaml` |
| **8** | Tests | `tests/` |

---

---

## Phase 1 — Instrument Halt State

**New file:** `models/instrument.py`

### Why this needs its own model

The circuit breaker (Phase 10) needs to mark a symbol as "halted" so that new
orders cannot match against resting orders at artificial prices. Without this,
a circuit breaker halt would stop publishing trades but aggressive orders would
still execute.

The halt also needs to be checked by quote acceptance (Phase 6, already wired in),
and it needs to be cleared when the circuit breaker resumes.

### 1.1 Create `models/instrument.py`

```python
"""
models/instrument.py — Per-symbol trading state enum.

Used by the engine to track whether a symbol is in normal ACTIVE matching
or HALTED (circuit breaker fired, no matching allowed).
"""
from __future__ import annotations
from enum import Enum


class InstrumentState(str, Enum):
    ACTIVE = "ACTIVE"    # normal continuous matching
    HALTED = "HALTED"    # circuit breaker fired; no matching; quotes rejected
```

### 1.2 Add `_halted_symbols` to `Engine.__init__()`

```python
# In __init__:
self._halted_symbols: dict[str, bool] = {}
# True means halted. Missing key or False means active.
# Using a plain dict rather than a set so we can easily set/clear per symbol.
```

### 1.3 Add halt check to `_handle_new_order()`

Add this block immediately after the symbol allowlist check and before the timestamp
and book access lines (`now = monotonic_ns()`, `book = self._book(symbol)`):

```python
if self._halted_symbols.get(symbol):
    # Symbol is halted. Different handling per order type:
    if order.order_type in (OrderType.MARKET, OrderType.FOK, OrderType.IOC):
        # These types REQUIRE immediate execution. Reject them entirely.
        order.status = OrderStatus.REJECTED
        self.pub_sock.send_multipart(
            make_ack_msg(
                order.gateway_id, order.id, False,
                f"{symbol} is halted — market/FOK/IOC orders rejected"
            )
        )
        return

    # LIMIT and ICEBERG orders are accepted but NOT matched.
    # match=False tells the order book to accept them as resting interest
    # without attempting to sweep the opposite side. This collects liquidity
    # during the halt so the resumption auction has interest to uncross.
    from edumatcher.models.clock import monotonic_ns
    now  = monotonic_ns()
    book = self._book(symbol)
    trades, events = book.process(order, match=False, now=now)
    self._publish_events(events, book)
    self._mark_dirty(symbol)
    return   # do not fall through to normal processing
```

---

## Phase 2 — Kill Switch

A kill switch is a risk management and regulatory tool that immediately cancels
every resting order and quote for a participant. It can be triggered by the
participant themselves (e.g. their system is about to shut down unexpectedly), by
the exchange (e.g. the participant is submitting orders at a rate that is endangering
the market), or by a broker. Most exchange regulations require this capability.

After a kill switch, the session is marked `connected=False`, which blocks any
further order submissions until the participant reconnects and re-authenticates.

This phase is already covered in Phase 5 (gateway command) and Phase 4 (message
types). The engine handler is:

```python
def _handle_kill_switch(self, payload: dict[str, Any]) -> None:
    gateway_id = str(payload.get("gateway_id", "")).upper()
    operator   = payload.get("operator", "SELF")

    # Cancel all quotes for this gateway
    entries = self._quote_index.cancel_all_for_gateway(gateway_id)
    for entry in entries:
        book = self.books.get(entry.symbol)
        if book:
            for oid in (entry.bid_order_id, entry.ask_order_id):
                book.cancel_order(oid)
                self._order_symbol.pop(oid, None)
        self._mark_dirty(entry.symbol)

    # Cancel all resting orders for this gateway
    cancelled_orders = 0
    for symbol, book in self.books.items():
        for order in list(book.resting_orders()):
            if order.gateway_id == gateway_id:
                book.cancel_order(order.id)
                self._order_symbol.pop(order.id, None)
                # Notify the gateway that each order was cancelled.
                # make_order_cancelled_msg() is an EXISTING helper in message.py
                # (it was there before this plan). Search for it in message.py —
                # it encodes an order.cancelled.{gateway_id} message.
                self.pub_sock.send_multipart(
                    make_order_cancelled_msg(gateway_id, order.id)
                )
                cancelled_orders += 1
        self._mark_dirty(symbol)

    # Mark session as not connected — blocks all future submissions
    # from this gateway until it reconnects and re-authenticates
    session = self._sessions.get(gateway_id)
    if session:
        session.connected = False

    # Acknowledge the kill switch execution
    self.pub_sock.send_multipart(make_kill_switch_ack_msg(
        gateway_id=gateway_id,
        cancelled_orders=cancelled_orders,
        cancelled_quotes=len(entries),
    ))

    print(
        f"[ENGINE] KILL SWITCH {gateway_id} by {operator}: "
        f"{cancelled_orders} orders, {len(entries)} quotes cancelled"
    )
```

**Note on exchange-triggered kill switch:** The engine can also trigger a kill switch
internally — for example if it detects runaway order submission from a gateway. To do
this, the engine sends itself a `risk.kill_switch` message by calling
`_handle_kill_switch()` directly, passing `operator="EXCHANGE"`.

---

## Phase 3 — Price Collar Bands

**New file:** `engine/collar.py`

### Why integer arithmetic, not `Decimal`

With prices as integer ticks, collar boundaries are computed as:
```python
static_upper = int(ref * (1 + collar.static_band_pct))
```

`int()` truncates toward zero. For a positive upper bound, truncating gives a value
slightly below the mathematically exact boundary — meaning the allowed range is
slightly tighter than specified. For a lower bound:
```python
static_lower = int(ref * (1 - collar.static_band_pct))
```

`int()` truncates toward zero again, so the lower bound is slightly above the
mathematically exact boundary — again, slightly tighter. Both bounds err toward
being more restrictive, which is the safe direction for a price protection mechanism.
No `Decimal` or floating-point rounding is needed.

```python
"""
engine/collar.py — Price collar band validation.

Collar bands prevent any single order from moving price too far in one step:

Static band:  ±static_band_pct from the reference price (prior close).
              Catches fat-finger errors: "sell 1000 shares at $1.00" when
              the stock trades at $150 is caught here.

Dynamic band: ±dynamic_band_pct from the last trade price.
              Prevents step-by-step manipulation: submitting 50 orders
              each moving price 1.9% to avoid any single 2% trigger.

Both bands must pass. An order rejected by either band receives an ack
with reason STATIC_COLLAR_BREACH or DYNAMIC_COLLAR_BREACH.

All prices are int ticks. Band limits are int ticks (int() truncation toward
zero gives a conservative — slightly tighter — boundary, which is correct).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class CollarConfig:
    symbol:           str
    reference_price:  int            # ticks — set from last close or seed price
    static_band_pct:  float = 0.20  # ±20% from reference
    dynamic_band_pct: float = 0.02  # ±2% from last trade


@dataclass
class CollarResult:
    rejected: bool
    reason:   str = ""


def validate_collar(
    price:            int,
    collar:           CollarConfig,
    last_trade_price: Optional[int],  # ticks; None if no trades yet today
) -> CollarResult:
    """
    Check price against both collar bands. Returns rejected=True if either fails.

    Parameters
    ----------
    price            : The order price in int ticks.
    collar           : Configuration for this symbol.
    last_trade_price : The most recent fill price, or None if no trades yet.
                       When None, only the static band is checked.
    """
    ref = collar.reference_price

    # Static band check (always applied)
    static_upper = int(ref * (1 + collar.static_band_pct))
    static_lower = int(ref * (1 - collar.static_band_pct))
    if not (static_lower <= price <= static_upper):
        return CollarResult(
            rejected=True,
            reason=(
                f"STATIC_COLLAR_BREACH: price {price} ticks is outside "
                f"[{static_lower}, {static_upper}] ticks "
                f"(±{collar.static_band_pct*100:.0f}% from reference {ref})"
            ),
        )

    # Dynamic band check (only when we have a last trade price)
    if last_trade_price is not None:
        dyn_upper = int(last_trade_price * (1 + collar.dynamic_band_pct))
        dyn_lower = int(last_trade_price * (1 - collar.dynamic_band_pct))
        if not (dyn_lower <= price <= dyn_upper):
            return CollarResult(
                rejected=True,
                reason=(
                    f"DYNAMIC_COLLAR_BREACH: price {price} ticks is outside "
                    f"[{dyn_lower}, {dyn_upper}] ticks "
                    f"(±{collar.dynamic_band_pct*100:.0f}% from last trade {last_trade_price})"
                ),
            )

    return CollarResult(rejected=False)
```

**Integrate into the engine** — in `Engine.__init__()`:
```python
from edumatcher.engine.collar import CollarConfig, validate_collar
self._collars: dict[str, CollarConfig] = {}   # symbol → CollarConfig
```

In `_handle_new_order()`, after the halt check and before order creation:
```python
if order.price is not None:
    collar = self._collars.get(symbol)
    if collar:
        result = validate_collar(order.price, collar, book.last_trade_price)
        if result.rejected:
            self.pub_sock.send_multipart(
                make_ack_msg(order.gateway_id, order.id, False, result.reason)
            )
            return
```

---

## Phase 4 — Circuit Breaker

**New file:** `engine/circuit_breaker.py`

A circuit breaker is a market safety mechanism. When prices move too fast — beyond
a defined percentage in a short rolling window — the exchange temporarily halts
trading for that symbol. This prevents automated systems from driving prices to
extremes in milliseconds, protecting all participants.

During a halt:
- All resting quotes are cancelled (market makers cannot reprice them, so stale quotes must go)
- Resting limit orders stay in the book as auction interest
- No new matching occurs
- After `halt_duration_ns` nanoseconds, trading resumes

`resumption_mode = "AUCTION"` means trading resumes with an auction uncross: all
resting orders execute at the equilibrium price, then normal continuous matching
begins. This is the safest resumption method because it prevents one large resting
order from immediately moving the price at the moment the halt lifts.

```python
"""
engine/circuit_breaker.py — Per-symbol circuit breaker.

Monitors fill prices against a rolling window average. When a fill price
moves more than dynamic_band_pct from the reference price:

  1. The symbol is HALTED (_halted_symbols[symbol] = True in the engine)
  2. All resting quotes for that symbol are cancelled
  3. Resting limit orders are NOT cancelled — they are frozen as auction interest
  4. A circuit_breaker.halt.{symbol} message is broadcast to all subscribers
  5. After halt_duration_ns nanoseconds, a resume message is broadcast and
     _halted_symbols[symbol] is set to False

The record_trade() method is called synchronously in _publish_trades() after
every fill. It must be fast. It is O(1) amortised: append to deque, trim
entries older than the window, compute integer average, compare.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CircuitBreakerConfig:
    symbol:              str
    dynamic_band_pct:    float = 0.05           # halt if price moves ±5%
    reference_window_ns: int   = 300_000_000_000 # 5-minute window (nanoseconds)
    halt_duration_ns:    int   = 60_000_000_000  # 60-second halt (nanoseconds)
    resumption_mode:     str   = "AUCTION"       # "AUCTION" or "CONTINUOUS"


@dataclass
class CircuitBreakerState:
    symbol:          str
    config:          CircuitBreakerConfig
    trade_history:   deque = field(default_factory=deque)  # (timestamp_ns, price_ticks)
    halted:          bool  = False
    halted_at_ns:    Optional[int] = None   # nanoseconds
    resume_at_ns:    Optional[int] = None   # nanoseconds
    trigger_price:   Optional[int] = None   # ticks — the price that fired the breaker
    reference_price: Optional[int] = None   # ticks — average over the window

    def record_trade(self, price: int, now: int) -> bool:
        """
        Record a new trade price and check if the breaker should fire.

        Returns True  → circuit breaker should fire.
        Returns False → price within bounds, or already halted.
        """
        if self.halted:
            return False   # already halted, don't double-trigger

        self.trade_history.append((now, price))

        # Trim entries older than the reference window
        cutoff = now - self.config.reference_window_ns
        while self.trade_history and self.trade_history[0][0] < cutoff:
            self.trade_history.popleft()

        if not self.trade_history:
            return False

        # Integer average: sum of prices // count
        # Fast and exact — no float arithmetic needed
        prices = [p for _, p in self.trade_history]
        ref    = sum(prices) // len(prices)
        self.reference_price = ref

        upper = int(ref * (1 + self.config.dynamic_band_pct))
        lower = int(ref * (1 - self.config.dynamic_band_pct))

        if price > upper or price < lower:
            self.trigger_price = price
            return True
        return False

    def activate(self, now: int) -> None:
        """Call this when record_trade() returns True."""
        self.halted       = True
        self.halted_at_ns = now
        self.resume_at_ns = now + self.config.halt_duration_ns

    def should_resume(self, now: int) -> bool:
        """Returns True when enough time has passed since the halt."""
        return (
            self.halted
            and self.resume_at_ns is not None
            and now >= self.resume_at_ns
        )

    def deactivate(self) -> None:
        """Call this when should_resume() returns True."""
        self.halted         = False
        self.halted_at_ns   = None
        self.resume_at_ns   = None
        self.trigger_price  = None
```

**Integrate into the engine:**

```python
# In __init__:
from edumatcher.engine.circuit_breaker import CircuitBreakerConfig, CircuitBreakerState
self._circuit_breakers: dict[str, CircuitBreakerState] = {}
```

```python
def _check_circuit_breaker(self, symbol: str, trade_price: int, now: int) -> None:
    """Called from _publish_trades() after every fill."""
    from edumatcher.models.price import from_ticks
    cb = self._circuit_breakers.get(symbol)
    if cb is None:
        return   # no circuit breaker configured for this symbol

    if not cb.record_trade(trade_price, now):
        return   # price within bounds

    # Circuit breaker fires:
    cb.activate(now)
    self._halted_symbols[symbol] = True

    # Cancel all quotes for this symbol
    for entry in self._quote_index.cancel_all_for_symbol(symbol):
        book = self.books.get(symbol)
        if book:
            for oid in (entry.bid_order_id, entry.ask_order_id):
                book.cancel_order(oid)
                self._order_symbol.pop(oid, None)

    # Broadcast halt notification
    self.pub_sock.send_multipart(encode(
        f"circuit_breaker.halt.{symbol}",
        {
            "symbol":          symbol,
            "trigger_price":   from_ticks(cb.trigger_price, symbol),
            "reference_price": from_ticks(cb.reference_price, symbol),
            "resume_at_ns":    cb.resume_at_ns,
            "resumption_mode": cb.config.resumption_mode,
        },
    ))
    self._mark_dirty(symbol)
    print(
        f"[ENGINE] CIRCUIT BREAKER HALT {symbol}: "
        f"trigger={cb.trigger_price}, ref={cb.reference_price} ticks"
    )
```

```python
def _flush_circuit_breakers(self) -> None:
    """
    Check whether any halted symbols are ready to resume.
    Called from the MAIN POLL LOOP on every iteration — not from _flush_snapshots().

    Why not _flush_snapshots()? Because snapshots are throttled to at most once
    every 500ms per symbol. If a halt is 60 seconds, we check resumption every
    200ms (the poll timeout). Putting this in _flush_snapshots() would delay
    resumption by up to 500ms unnecessarily.
    """
    from edumatcher.models.clock import monotonic_ns
    now = monotonic_ns()
    for symbol, cb in self._circuit_breakers.items():
        if cb.should_resume(now):
            cb.deactivate()
            self._halted_symbols[symbol] = False
            self.pub_sock.send_multipart(encode(
                f"circuit_breaker.resume.{symbol}",
                {"symbol": symbol, "mode": cb.config.resumption_mode},
            ))
            self._mark_dirty(symbol)
            print(f"[ENGINE] CIRCUIT BREAKER RESUME {symbol}")
```

**How to add it to the main loop** — find the `while self._running:` loop. It looks
roughly like:

```python
while self._running:
    socks = dict(poller.poll(timeout=200))
    if self.pull_sock in socks:
        frames = self.pull_sock.recv_multipart()
        topic, payload = decode(frames)
        if topic == "order.new":
            self._handle_new_order(payload)
        elif topic == ...:
            ...
    # After processing one message (or after the 200ms timeout with no message):
    self._flush_snapshots()
    self._flush_circuit_breakers()   # ← add this line here
```

The `_flush_circuit_breakers()` call goes at the same level as `_flush_snapshots()`,
outside the `if self.pull_sock in socks:` block. It runs on every poll cycle
regardless of whether a message arrived.

---


## Phase 5 — Depth Metrics

**File:** `engine/order_book.py`

**What depth means:** Order book depth is the total quantity of resting orders at
each price level. A "deep" book has large quantities near the best price, meaning
you can trade a large size without moving the price much. Depth metrics publish a
summary of how much volume is resting within a certain distance of the mid price.

**Why depth matters:** Trading desks and algorithmic systems consume depth data to
estimate market impact — "if I buy 10,000 shares, how far will the price move?"

```python
def depth_snapshot(self, tolerance_ticks: int) -> dict:
    """
    Compute depth metrics within tolerance_ticks of the mid price.

    Uses the _bid_qty / _ask_qty price-level index for O(P) performance
    where P = number of distinct price levels. Much cheaper than iterating
    all heap entries as snapshot() does.

    Parameters
    ----------
    tolerance_ticks : How many ticks either side of mid to include.
                      Example: if mid is 15000 ticks and tolerance is 100,
                      include bids in [14900, 15000] and asks in [15000, 15100].

    Returns a dict suitable for direct JSON publication via make_depth_msg().
    Prices are int ticks — subscribers convert to float for display.
    """
    if self.last_trade_price is None:
        return {}   # no trades yet; no meaningful mid price

    mid   = self.last_trade_price
    lower = mid - tolerance_ticks
    upper = mid + tolerance_ticks

    bid_depth = sum(qty for px, qty in self._bid_qty.items() if lower <= px <= mid)
    ask_depth = sum(qty for px, qty in self._ask_qty.items() if mid <= px <= upper)
    total     = bid_depth + ask_depth

    return {
        "symbol":          self.symbol,
        "mid_price_ticks": mid,          # int ticks — subscriber calls from_ticks()
        "tolerance_ticks": tolerance_ticks,
        "bid_depth":       bid_depth,
        "ask_depth":       ask_depth,
        "imbalance":       (bid_depth - ask_depth) / total if total > 0 else 0.0,
        "cost_to_move":    bid_depth,    # quantity of sell orders needed to push price DOWN by
                                         # tolerance_ticks (i.e. must exhaust all bids in the range)
    }
```

Add to `message.py`:
```python
def make_depth_msg(symbol: str, depth: dict[str, Any]) -> list[bytes]:
    """Engine → all subscribers: depth snapshot for a symbol."""
    return encode(f"depth.{symbol}", depth)
```

In `_flush_snapshots()`, after publishing the book snapshot:
```python
if book.last_trade_price:
    depth = book.depth_snapshot(tolerance_ticks=100)  # configurable per symbol later
    # For a symbol with tick_decimals=2, 100 ticks = $1.00.
    # So this publishes depth within ±$1.00 of the mid price.
    self.pub_sock.send_multipart(make_depth_msg(symbol, depth))
```

---

## Phase 6 — Drop Copy Publisher

**New file:** `engine/drop_copy.py`

**What a drop copy is:** A drop copy is a real-time feed of all order lifecycle
events for a participant — every submission, fill, cancel, and reject — delivered
to a separate recipient such as their clearing broker, their risk management system,
or a regulator. It is called a "drop copy" because the exchange "drops a copy" of
each event to the recipient as it happens, rather than the recipient having to poll
for updates.

The drop copy runs on a separate ZMQ PUB socket (port 5557) so recipients do not
need to be part of the main market data feed (port 5556). Each message carries a
monotonically increasing sequence number so a recipient that reconnects can request
a replay of any missed messages.

### What `**payload` means

In `drop_copy.py` you will see dict unpacking syntax:
```python
_dumps({
    "seq":        seq,
    "timestamp":  now,
    "event_type": event_type,
    **payload,          # ← unpack all key-value pairs from payload into this dict
})
```

`**payload` is Python dict unpacking. If `payload = {"order_id": "abc", "fill_qty": 100}`,
then `{"seq": 1, **payload}` produces `{"seq": 1, "order_id": "abc", "fill_qty": 100}`.
It is equivalent to building the dict and calling `.update(payload)`.

```python
"""
engine/drop_copy.py — Sequenced drop copy on a separate ZMQ socket.

The drop copy publishes every order lifecycle event on port 5557, separate
from the main market data feed on port 5556. This allows clearing brokers,
risk systems, and regulators to subscribe independently.

Every message carries a monotonically increasing sequence number. A recipient
that reconnects can send a replay request with from_seq=N to recover missed
messages from the in-memory buffer.

Timestamps are int nanoseconds throughout.
"""
from __future__ import annotations
import itertools
# Note: `time` is NOT imported here. Timestamps use monotonic_ns() from
# models/clock.py (imported locally inside publish() for clarity).
from collections import deque
from dataclasses import dataclass
from typing import Any

import zmq

from edumatcher.models.message import _dumps

_seq_counter          = itertools.count(1)
DROP_COPY_PUB_ADDR    = "tcp://127.0.0.1:5557"
DROP_COPY_PULL_ADDR   = "tcp://127.0.0.1:5558"   # for replay requests
DROP_COPY_BUFFER_SIZE = 10_000                    # messages retained in memory


@dataclass
class DropCopyMessage:
    seq:        int    # monotonically increasing
    timestamp:  int    # nanoseconds
    gateway_id: str
    topic:      str    # e.g. "order.fill", "quote.fill", "order.cancel"
    payload:    dict[str, Any]


class DropCopyPublisher:
    """
    Instantiated once by the Engine. Publishes all order events on a
    separate ZMQ PUB socket.
    """

    def __init__(self, context: zmq.Context) -> None:
        self._pub = context.socket(zmq.PUB)
        self._pub.bind(DROP_COPY_PUB_ADDR)
        # Bounded deque: when full, oldest messages are automatically dropped
        self._log: deque[DropCopyMessage] = deque(maxlen=DROP_COPY_BUFFER_SIZE)

    def publish(
        self, gateway_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        """
        Publish one event. Called by the engine for every fill, cancel, reject,
        and quote fill. `payload` should contain the fields relevant to this
        event type.
        """
        seq = next(_seq_counter)
        from edumatcher.models.clock import monotonic_ns
        now = monotonic_ns()  # strictly increasing nanosecond timestamp
        msg = DropCopyMessage(
            seq=seq, timestamp=now, gateway_id=gateway_id,
            topic=event_type, payload=payload,
        )
        self._log.append(msg)

        # Topic is gateway-scoped so recipients can filter per gateway
        topic_bytes = f"drop_copy.event.{gateway_id}".encode()
        self._pub.send_multipart([
            topic_bytes,
            _dumps({
                "seq":        seq,
                "timestamp":  now,
                "gateway_id": gateway_id,
                "event_type": event_type,
                **payload,   # spread all payload fields into the top-level dict
            }),
        ])

    def replay(self, recipient_id: str, from_seq: int) -> int:
        """
        Re-send all buffered messages with seq >= from_seq to a reconnecting
        recipient. Returns the number of messages replayed.
        """
        topic_bytes = f"drop_copy.replay.{recipient_id}".encode()
        replayed = 0
        for msg in self._log:
            if msg.seq >= from_seq:
                self._pub.send_multipart([
                    topic_bytes,
                    _dumps({
                        "seq":        msg.seq,
                        "timestamp":  msg.timestamp,
                        "gateway_id": msg.gateway_id,
                        "event_type": msg.topic,
                        **msg.payload,
                    }),
                ])
                replayed += 1
        return replayed

    def close(self) -> None:
        """Call from Engine._shutdown() to cleanly close the socket."""
        self._pub.close()
```

**Integrate into the engine:**

```python
# In __init__:
from edumatcher.engine.drop_copy import DropCopyPublisher
self._drop_copy = DropCopyPublisher(zmq.Context.instance())

# In _publish_events(), add this inside the `if evt.status in _FILL_STATUSES:` branch,
# AFTER the existing pub_sock.send_multipart() call and combo/OCO cascade checks.
# Note: `from_ticks` is already imported at the top of _publish_events().
self._drop_copy.publish(
    gateway_id=evt.gateway_id,
    event_type="order.fill",
    payload={
        "order_id":      evt.id,
        "fill_qty":      evt.quantity - evt.remaining_qty,
        "fill_price":    (
            from_ticks(book.last_trade_price, evt.symbol)
            if book.last_trade_price is not None else 0.0
        ),
        "remaining_qty": evt.remaining_qty,
        "symbol":        evt.symbol,
        # liquidity_flag: "MAKER_QUOTE" if the resting order was a market maker
        # quote leg; "MAKER" for a regular resting limit order. Note: this
        # implementation does not distinguish the aggressive (TAKER) side from the
        # passive (MAKER) side in the drop copy — a future enhancement would pass
        # aggressor_side information to label taker fills correctly.
        "liquidity_flag": "MAKER_QUOTE" if evt.origin == OrderOrigin.QUOTE else "MAKER",
    },
)

# In _shutdown():
self._drop_copy.close()
```

---

---

## Phase 7 — Config Extensions

**File:** `engine/config_loader.py` and `engine_config.yaml`

Extend `SymbolConfig`:
```python
@dataclass
class SymbolConfig:
    name:                str
    tick_decimals:       int   = 2       # from tick migration plan
    last_buy_price:      Optional[float] = None
    last_sell_price:     Optional[float] = None
    market_maker_orders: list[str] = field(default_factory=list)
    collar:              Optional["CollarConfig"]         = None
    circuit_breaker:     Optional["CircuitBreakerConfig"] = None
```

Extend `FixGatewayConfig`:
```python
@dataclass
class FixGatewayConfig:
    id:                   str
    description:          str                 = ""
    role:                 ParticipantRole     = ParticipantRole.TRADER
    disconnect_behaviour: DisconnectBehaviour = DisconnectBehaviour.CANCEL_QUOTES_ONLY
    mm_obligations:       dict[str, "MarketMakerObligation"] = field(default_factory=dict)
    quote_refresh_policy: QuoteRefreshPolicy = QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL
```

In `Engine._load_config()`, after loading the config, populate all engine
structures. This should be one of the first things that runs in `_load_config()`
so that tick decimals are registered before any order is processed:

```python
from edumatcher.models.price import register_tick_decimals, to_ticks
from edumatcher.engine.collar import CollarConfig
from edumatcher.engine.circuit_breaker import CircuitBreakerState

for sym, sym_cfg in self._engine_config.symbols.items():
    # 1. Register tick precision — must be first
    register_tick_decimals(sym, sym_cfg.tick_decimals)

    # 2. Collar
    if sym_cfg.collar:
        ref_float = sym_cfg.last_buy_price or sym_cfg.last_sell_price
        if ref_float is not None:
            sym_cfg.collar.symbol          = sym
            sym_cfg.collar.reference_price = to_ticks(float(ref_float), sym)
            self._collars[sym] = sym_cfg.collar

    # 3. Circuit breaker
    if sym_cfg.circuit_breaker:
        sym_cfg.circuit_breaker.symbol = sym
        self._circuit_breakers[sym] = CircuitBreakerState(
            symbol=sym, config=sym_cfg.circuit_breaker
        )

for gw_id, gw_cfg in self._engine_config.fix_gateways.items():
    # 4. Quote refresh policy
    self._quote_refresh_policy[gw_id] = gw_cfg.quote_refresh_policy

    # 5. MM obligations
    for sym, obl in gw_cfg.mm_obligations.items():
        self._mm_obligations[(gw_id, sym)] = obl
```

Complete `engine_config.yaml` example:
```yaml
symbols:
  AAPL:
    tick_decimals: 2            # 1 tick = $0.01
    last_buy_price:  209.50
    last_sell_price: 210.50
    collar:
      static_band_pct:  0.20   # ±20% from reference price
      dynamic_band_pct: 0.02   # ±2% from last trade
    circuit_breaker:
      dynamic_band_pct:    0.05
      reference_window_ns: 300000000000   # 300 seconds = 5 minutes
      halt_duration_ns:    60000000000    # 60 seconds
      resumption_mode:     AUCTION
    market_maker_orders:
      - "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=2000|PRICE=209.00|TIF=GTC"
      - "NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=2000|PRICE=211.00|TIF=GTC"

fix_gateways:
  GW01:
    description: "Trader terminal 1"
    role: TRADER
    disconnect_behaviour: CANCEL_ALL

  MM01:
    description: "Market maker 1"
    role: MARKET_MAKER
    disconnect_behaviour: CANCEL_QUOTES_ONLY
    quote_refresh_policy: INACTIVATE_ON_ANY_FILL
    mm_obligations:
      AAPL:
        max_spread_ticks:     10      # 10 ticks = $0.10
        min_qty:              100
        min_presence_pct:     0.85
        max_requote_delay_ns: 500000000   # 500ms
        mmp_fill_count:       5
        mmp_window_ns:        1000000000  # 1 second
```

---

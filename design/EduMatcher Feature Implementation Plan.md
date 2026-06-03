Version: 0.1.0

Date: 2026-04-09

Status: Design and Research Proposal

# EduMatcher — Feature Implementation Plan v2

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
> **Clock:** Use `now_ns()` from `models/clock.py` everywhere a timestamp is
> needed — never call `time.time_ns()` directly. `now_ns()` wraps it with a
> strictly-increasing guarantee even when the system clock steps backward.
>
> ⚠️ **v1 → v2 changes summary:**
> - `monotonic_ns()` renamed to `now_ns()` throughout (actual function name in codebase)
> - `make_order_cancelled_msg()` → `make_cancelled_msg()` (actual function name)
> - `_publish_trades()` → `_publish_trade()` (actual method name, called per trade)
> - Phase 2 (Kill Switch): already implemented; section rewritten to document actual behaviour and remaining gap
> - Phase 5 (Depth Metrics): `make_depth_msg()` already exists in `models/message.py`; `make_dropcopy_fill_msg()` already exists too
> - Phase 6 (Drop Copy): integration point corrected (`_publish_events()` doesn't exist; must integrate inline)
> - Phase 7 (Config): `SymbolConfig.market_maker_orders` replaced by `market_maker_quotes`; `FixGatewayConfig.mm_obligations` dict reconciled against existing flat fields; `models/mm_obligation.py` already exists
> - Circuit breaker resume with `AUCTION` mode must call existing `_run_uncross()`

---

## High-Level Roadmap

| Phase | Feature | Files Touched | Status |
|-------|---------|---------------|--------|
| **1** | Instrument halt state | `engine/main.py`, `models/instrument.py` *(new)* | Not started |
| **2** | Kill switch | already implemented — see notes | Implemented (gap: no per-symbol scope in plan) |
| **3** | Price collar bands | `engine/collar.py` *(new)*, `engine/main.py` | Not started |
| **4** | Circuit breaker | `engine/circuit_breaker.py` *(new)*, `engine/main.py` | Not started |
| **5** | Depth metrics and market data | `engine/order_book.py`, `engine/main.py` | Not started |
| **6** | Drop copy publisher | `engine/drop_copy.py` *(new)*, `engine/main.py` | Not started |
| **7** | Config extensions | `engine/config_loader.py`, `engine_config.yaml` | Partially done |

---

## Phase 1 — Instrument Halt State

**New file:** `models/instrument.py`

### Why this needs its own model

The circuit breaker (Phase 4) needs to mark a symbol as "halted" so that new
orders cannot match against resting orders at artificial prices. Without this,
a circuit breaker halt would stop publishing trades but aggressive orders would
still execute.

The halt also needs to be checked by quote acceptance (`_handle_quote_new`),
and it must be cleared when the circuit breaker resumes.

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
# In __init__, alongside the other tracking dicts:
self._halted_symbols: dict[str, bool] = {}
# True means halted. Missing key or False means active.
```

### 1.3 Add halt check to `_handle_new_order()`

Add this block **after** the session state / ATC / ATO checks and **before** the
`book = self._book(order.symbol)` / `do_match = is_matching_enabled(...)` lines.
The existing session-state MARKET/FOK/IOC rejection check also handles those types
during halts — but the halt check must be explicit and separate to allow LIMIT/ICEBERG
through (as resting-only interest for the resumption auction):

```python
if self._halted_symbols.get(symbol):
    if order.order_type in (OrderType.MARKET, OrderType.FOK, OrderType.IOC):
        order.status = OrderStatus.REJECTED
        self.pub_sock.send_multipart(
            make_ack_msg(
                order.gateway_id, order.id, accepted=False,
                reason=f"{symbol} is halted — {order.order_type.value} orders rejected"
            )
        )
        return

    # LIMIT / ICEBERG: accept but force match=False so they collect as
    # auction interest during the halt without sweeping the opposite side.
    now = now_ns()
    book = self._book(symbol)
    trades, events = book.process(order, match=False, now=now)
    self._publish_ack(order, payload)        # see note below
    for evt in events:
        self._publish_fill_or_cancel(evt, book)
    self._mark_dirty(symbol)
    return
```

> **Note on `_publish_ack` / `_publish_fill_or_cancel`:** The engine currently
> inlines event publishing in `_handle_new_order` (for performance). To avoid
> duplicating that inline block, extract it into private helpers first, or simply
> inline the ACK and event loop here as the existing code does. Do not call the
> inline code twice — add the halt early-return so the flow is:
> halt-path → `return`, normal-path → existing code continues.

### 1.4 Add halt check to `_handle_quote_new()`

Add after the `session.role != ParticipantRole.MARKET_MAKER` check:

```python
if self._halted_symbols.get(symbol):
    self.pub_sock.send_multipart(
        make_quote_ack_msg(gateway_id, quote_id, False, f"{symbol} is halted")
    )
    return
```

---

## Phase 2 — Kill Switch

**Status: already implemented.** `_handle_kill_switch()` in `engine/main.py`
and `risk.kill_switch` topic handling in the main loop are complete.

### What the current implementation does

```
risk.kill_switch  payload: { gateway_id, symbol? }
```

- Validates gateway is configured and connected (rejects with ack if not)
- Optional `symbol` field scopes cancellation to a single symbol
- Cancels all active quote legs for that gateway (or just the scoped symbol)
- Cancels all non-quote resting orders for that gateway (or just the scoped symbol)
- Does **not** mark the session as disconnected — the gateway remains connected
  and can continue submitting new orders after the kill switch
- Publishes `risk.kill_switch_ack.<GW_ID>` with `cancelled_orders` and
  `cancelled_quotes` counts

### What v1 plan described vs what was built

The v1 plan showed `session.connected = False` after kill switch. This was not
implemented and should not be implemented without explicit product requirement:
marking a session disconnected after kill switch would prevent a gateway from
re-quoting after a risk event, which is the opposite of what most market-making
firms need. The current design keeps the session active.

The v1 plan also showed no `symbol_filter` — the implemented version supports
per-symbol scope, which is strictly more capable.

### Remaining gap

The only thing to verify: when Phase 1 adds `_halted_symbols`, the kill switch
should be extended to also set halt state if the operator is `EXCHANGE`:

```python
# At the end of _handle_kill_switch, before the ack send:
if payload.get("operator") == "EXCHANGE" and symbol_filter:
    self._halted_symbols[symbol_filter] = True
```

This is optional and can be deferred to Phase 4 when circuit breakers are wired in.

---

## Phase 3 — Price Collar Bands

**New file:** `engine/collar.py`

### Why integer arithmetic, not `Decimal`

With prices as integer ticks, collar boundaries are computed as:
```python
static_upper = int(ref * (1 + collar.static_band_pct))
```

`int()` truncates toward zero. For a positive upper bound, truncating gives a
value slightly below the mathematically exact boundary — meaning the allowed
range is slightly tighter than specified. For a lower bound:
```python
static_lower = int(ref * (1 - collar.static_band_pct))
```

Both bounds err toward being more restrictive, which is the safe direction for
a price protection mechanism. No `Decimal` or floating-point rounding is needed.

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

### Integrate into the engine

In `Engine.__init__()`:

```python
from edumatcher.engine.collar import CollarConfig, validate_collar
self._collars: dict[str, CollarConfig] = {}   # symbol → CollarConfig
```

In `_handle_new_order()`, after the halt check (Phase 1) and before the
`book = self._book(order.symbol)` line:

```python
if order.price is not None:
    collar = self._collars.get(order.symbol)
    if collar:
        book = self._book(order.symbol)
        result = validate_collar(order.price, collar, book.last_trade_price)
        if result.rejected:
            self.pub_sock.send_multipart(
                make_ack_msg(order.gateway_id, order.id, False, result.reason)
            )
            return
```

> **Note:** `book` is accessed here only to read `last_trade_price`. The same
> variable is re-assigned a few lines later in the normal flow — that is fine
> because `self._book(symbol)` is idempotent (returns the existing book).

---

## Phase 4 — Circuit Breaker

**New file:** `engine/circuit_breaker.py`

A circuit breaker is a market safety mechanism. When prices move too fast —
beyond a defined percentage in a short rolling window — the exchange temporarily
halts trading for that symbol. This prevents automated systems from driving
prices to extremes in milliseconds, protecting all participants.

During a halt:
- All resting quotes are cancelled (market makers cannot reprice them, so stale quotes must go)
- Resting limit orders stay in the book as auction interest
- No new matching occurs (enforced by Phase 1 halt state)
- After `halt_duration_ns` nanoseconds, trading resumes

`resumption_mode = "AUCTION"` means trading resumes with an auction uncross: all
resting orders execute at the equilibrium price, then normal continuous matching
begins. The engine already has `_run_uncross()` for this — call it directly.
`resumption_mode = "CONTINUOUS"` skips the uncross and resumes matching directly.

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

record_trade() is called from _publish_trade() after every fill. It must be
fast — O(1) amortised: append to deque, trim old entries, compute integer
average, compare.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CircuitBreakerConfig:
    symbol:              str
    dynamic_band_pct:    float = 0.05           # halt if price moves ±5%
    reference_window_ns: int   = 300_000_000_000 # 5-minute rolling window
    halt_duration_ns:    int   = 60_000_000_000  # 60-second halt
    resumption_mode:     str   = "AUCTION"       # "AUCTION" or "CONTINUOUS"


@dataclass
class CircuitBreakerState:
    symbol:          str
    config:          CircuitBreakerConfig
    trade_history:   deque = field(default_factory=deque)  # (timestamp_ns, price_ticks)
    halted:          bool  = False
    halted_at_ns:    Optional[int] = None
    resume_at_ns:    Optional[int] = None
    trigger_price:   Optional[int] = None   # ticks — the price that fired the breaker
    reference_price: Optional[int] = None   # ticks — window average at fire time

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

        # Integer average: sum of prices // count — fast and exact
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

### Integrate into the engine

In `Engine.__init__()`:

```python
from edumatcher.engine.circuit_breaker import CircuitBreakerConfig, CircuitBreakerState
self._circuit_breakers: dict[str, CircuitBreakerState] = {}
```

Add `_check_circuit_breaker()` — call it from `_publish_trade()` at the end,
after the `pub_sock.send_multipart()` call:

```python
def _check_circuit_breaker(self, symbol: str, trade_price: int, now: int) -> None:
    """Called from _publish_trade() after every fill."""
    cb = self._circuit_breakers.get(symbol)
    if cb is None:
        return

    if not cb.record_trade(trade_price, now):
        return

    # Circuit breaker fires:
    cb.activate(now)
    self._halted_symbols[symbol] = True

    # Cancel all quotes for this symbol (stale quotes must not rest during halt)
    for entry in self._quote_index.cancel_all_for_symbol(symbol):
        self._cancel_quote_entry(entry, reason="Circuit breaker halt")

    # Broadcast halt notification to all subscribers
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

In `_publish_trade()`, add at the end:

```python
def _publish_trade(self, trade: Any) -> None:
    # ... existing send_multipart code unchanged ...
    self.pub_sock.send_multipart([_TRADE_TOPIC, _dumps({...})])
    # Circuit breaker check — uses int ticks (trade.price), not float
    self._check_circuit_breaker(trade.symbol, trade.price, trade.timestamp)
```

Add `_flush_circuit_breakers()`:

```python
def _flush_circuit_breakers(self) -> None:
    """
    Check whether any halted symbols are ready to resume.
    Called from the main poll loop on every iteration — not from _flush_snapshots().

    Why not _flush_snapshots()? Snapshots are throttled to 500ms max per symbol.
    Halt duration is 60 seconds. Checking here (every 200ms poll timeout) is
    sufficient and avoids any unnecessary delay at halt lift.
    """
    now = now_ns()
    for symbol, cb in self._circuit_breakers.items():
        if not cb.should_resume(now):
            continue
        cb.deactivate()
        self._halted_symbols[symbol] = False

        if cb.config.resumption_mode == "AUCTION":
            # Run equilibrium-price uncross exactly as the session transition does
            self._run_uncross(from_state=self._session_state)

        self.pub_sock.send_multipart(encode(
            f"circuit_breaker.resume.{symbol}",
            {"symbol": symbol, "mode": cb.config.resumption_mode},
        ))
        self._mark_dirty(symbol)
        print(f"[ENGINE] CIRCUIT BREAKER RESUME {symbol}")
```

> **Note on `_run_uncross`:** The existing method signature is
> `_run_uncross(self, from_state: SessionState)`. It iterates all books.
> For the circuit breaker resumption you only want to uncross the halted symbol.
> Either pass a `symbol_filter` param (requires a small signature change) or
> call `_run_uncross` and accept that it uncrosses all books — safe but slightly
> wasteful. A cleaner option: extract `_uncross_symbol(symbol)` as a helper and
> call it from both `_run_uncross` and `_flush_circuit_breakers`.

Wire `_flush_circuit_breakers()` into the main loop. Find the end of the
`while self._running:` body — it currently ends with:

```python
            self._flush_snapshots()
```

Add immediately after:

```python
            self._flush_snapshots()
            self._flush_circuit_breakers()   # ← add here
```

This runs on every poll cycle (200ms) regardless of whether a message arrived.

---

## Phase 5 — Depth Metrics

**File:** `engine/order_book.py` and `engine/main.py`

> **Note:** `make_depth_msg()` already exists in `models/message.py` (topic:
> `book.depth.{symbol}`). Do **not** add it again.

**What depth means:** Order book depth is the total quantity of resting orders at
each price level. A "deep" book has large quantities near the best price, meaning
you can trade a large size without moving the price much.

**Why depth matters:** Algorithmic systems consume depth data to estimate market
impact — "if I buy 10,000 shares, how far will the price move?"

### 5.1 Add `depth_snapshot()` to `OrderBook`

`OrderBook` already has `_bid_qty: dict[int, int]` and `_ask_qty: dict[int, int]`
(price-level quantity indexes). Use them for O(P) depth computation.

```python
def depth_snapshot(self, tolerance_ticks: int) -> dict:
    """
    Compute depth metrics within tolerance_ticks of the last trade price.

    Uses the _bid_qty / _ask_qty price-level index for O(P) performance
    where P = number of distinct price levels. Much cheaper than iterating
    all heap entries as snapshot() does.

    Parameters
    ----------
    tolerance_ticks : How many ticks either side of the last trade to include.
                      Example: last trade=15000 ticks, tolerance=100 →
                      include bids in [14900, 15000] and asks in [15000, 15100].

    Returns a dict suitable for make_depth_msg(). Prices are int ticks;
    subscribers convert to float for display.

    Returns {} if no trades have occurred yet (no meaningful mid price).
    """
    if self.last_trade_price is None:
        return {}

    mid   = self.last_trade_price
    lower = mid - tolerance_ticks
    upper = mid + tolerance_ticks

    bid_depth = sum(qty for px, qty in self._bid_qty.items() if lower <= px <= mid)
    ask_depth = sum(qty for px, qty in self._ask_qty.items() if mid  <= px <= upper)
    total     = bid_depth + ask_depth

    return {
        "symbol":          self.symbol,
        "mid_price_ticks": mid,
        "tolerance_ticks": tolerance_ticks,
        "bid_depth":       bid_depth,
        "ask_depth":       ask_depth,
        "imbalance":       (bid_depth - ask_depth) / total if total > 0 else 0.0,
        "cost_to_move":    bid_depth,
    }
```

### 5.2 Publish depth from `_flush_snapshots()`

In `Engine._flush_snapshots()`, after the existing `make_book_msg` publish:

```python
if book.last_trade_price:
    depth = book.depth_snapshot(tolerance_ticks=100)
    if depth:
        self.pub_sock.send_multipart(make_depth_msg(symbol, depth))
```

Add `make_depth_msg` to the imports at the top of `engine/main.py`:

```python
from edumatcher.models.message import (
    ...
    make_depth_msg,    # ← add
    ...
)
```

> `tolerance_ticks=100` means ±100 ticks. For a symbol with `tick_decimals=2`
> that is ±$1.00. Make this configurable per symbol in Phase 7.

---

## Phase 6 — Drop Copy Publisher

**New file:** `engine/drop_copy.py`

**What a drop copy is:** A drop copy is a real-time feed of all order lifecycle
events for a participant — every fill, cancel, and reject — delivered to a
separate recipient such as their clearing broker or risk management system.
It runs on a separate ZMQ PUB socket (port 5557) so recipients do not
need to be part of the main market data feed (port 5556).

> **Note:** `make_dropcopy_fill_msg()` already exists in `models/message.py`
> (topic: `dropcopy.fill.{gateway_id}`). The `DropCopyPublisher` below uses
> its own sequenced format on a separate socket — the two are not connected.
> `make_dropcopy_fill_msg` was added early as a placeholder; `DropCopyPublisher`
> supersedes it for the engine-side implementation.

### What `**payload` means

```python
_dumps({"seq": seq, "timestamp": now, "event_type": event_type, **payload})
```

`**payload` is Python dict unpacking — all key-value pairs from `payload` are
merged into the outer dict. Equivalent to `.update(payload)` but in a literal.

```python
"""
engine/drop_copy.py — Sequenced drop copy on a separate ZMQ socket.

Publishes every order lifecycle event on port 5557, separate from the
main market data feed on port 5556. Allows clearing brokers, risk systems,
and regulators to subscribe independently.

Every message carries a monotonically increasing sequence number. A recipient
that reconnects can send a replay request with from_seq=N to recover missed
messages from the in-memory buffer.

Timestamps are int nanoseconds (now_ns() from models/clock.py).
"""
from __future__ import annotations
import itertools
from collections import deque
from dataclasses import dataclass
from typing import Any

import zmq

from edumatcher.models.message import _dumps

_seq_counter          = itertools.count(1)
DROP_COPY_PUB_ADDR    = "tcp://127.0.0.1:5557"
DROP_COPY_BUFFER_SIZE = 10_000   # messages retained in memory for replay


@dataclass
class DropCopyMessage:
    seq:        int    # monotonically increasing
    timestamp:  int    # nanoseconds (now_ns())
    gateway_id: str
    topic:      str    # e.g. "order.fill", "order.cancel"
    payload:    dict[str, Any]


class DropCopyPublisher:
    """Instantiated once by the Engine. Publishes all order events on a
    separate ZMQ PUB socket."""

    def __init__(self, context: zmq.Context) -> None:
        self._pub = context.socket(zmq.PUB)
        self._pub.bind(DROP_COPY_PUB_ADDR)
        # Bounded deque: when full, oldest messages are automatically dropped
        self._log: deque[DropCopyMessage] = deque(maxlen=DROP_COPY_BUFFER_SIZE)

    def publish(
        self, gateway_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        """
        Publish one event. Called by the engine for every fill and cancel.
        `payload` should contain the fields relevant to this event type.
        """
        seq = next(_seq_counter)
        from edumatcher.models.clock import now_ns
        now = now_ns()
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
                **payload,
            }),
        ])

    def replay(self, recipient_id: str, from_seq: int) -> int:
        """
        Re-send all buffered messages with seq >= from_seq.
        Returns the number of messages replayed.
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

### Integrate into the engine

In `Engine.__init__()`:

```python
from edumatcher.engine.drop_copy import DropCopyPublisher
self._drop_copy = DropCopyPublisher(zmq.Context.instance())
```

**Integration point for fills:** The engine does not have a `_publish_events()`
helper — events are published inline in `_handle_new_order`, `_handle_quote_new`,
`_accept_combo`, and `_handle_oco_order`. In each of those methods, find the
block that handles `evt.status in _FILL_STATUSES` and add a drop copy call after
the existing `pub_sock.send_multipart()`:

```python
# Inside the fill event block, AFTER the existing pub_sock.send_multipart:
self._drop_copy.publish(
    gateway_id=evt.gateway_id,
    event_type="order.fill",
    payload={
        "order_id":       evt.id,
        "symbol":         evt.symbol,
        "fill_qty":       evt.quantity - evt.remaining_qty,
        "fill_price":     (
            from_ticks(book.last_trade_price, evt.symbol)
            if book.last_trade_price is not None else 0.0
        ),
        "remaining_qty":  evt.remaining_qty,
        "liquidity_flag": "MAKER_QUOTE" if evt.origin == OrderOrigin.QUOTE else "MAKER",
    },
)
```

> `_handle_new_order` uses an inlined fast-path for fills (bypasses `make_fill_msg`
> for perf). The drop copy call goes after that fast-path block — not inside it.

In `Engine._shutdown()`:

```python
self._drop_copy.close()
```

Add `DROP_COPY_PUB_ADDR` to `config.py` so it is not hardcoded:

```python
DROP_COPY_PUB_ADDR = "tcp://127.0.0.1:5557"
```

And import it in `drop_copy.py` from `edumatcher.config` instead of hardcoding.

---

## Phase 7 — Config Extensions

**Files:** `engine/config_loader.py` and `engine_config.yaml`

> **Current state:** `SymbolConfig` already has `tick_decimals`, `last_buy_price`,
> `last_sell_price`, `market_maker_quotes` (list of `MMQuoteSeed`).
> `FixGatewayConfig` already has `enforce_mm_obligation`, `mm_max_spread_ticks`,
> `mm_min_qty`. `models/mm_obligation.py` already exists with full
> `MarketMakerObligation` and `MMPState` dataclasses.

### 7.1 Extend `SymbolConfig`

Add `collar` and `circuit_breaker` optional fields:

```python
from edumatcher.engine.collar import CollarConfig
from edumatcher.engine.circuit_breaker import CircuitBreakerConfig

@dataclass
class SymbolConfig:
    name:                 str
    tick_decimals:        int                          = 2
    last_buy_price:       Optional[float]              = None
    last_sell_price:      Optional[float]              = None
    market_maker_quotes:  list["MMQuoteSeed"]          = field(default_factory=list)
    collar:               Optional[CollarConfig]       = None   # ← new
    circuit_breaker:      Optional[CircuitBreakerConfig] = None # ← new
```

> **Watch for circular imports:** `CollarConfig` and `CircuitBreakerConfig` are
> defined in `engine/collar.py` and `engine/circuit_breaker.py`. Both are under
> `engine/`, same package as `config_loader.py`. No circular dependency.

### 7.2 Extend the YAML parser in `load_engine_config()`

After parsing `market_maker_quotes`, parse the optional `collar` and
`circuit_breaker` sub-mappings:

```python
collar_raw = cfg.get("collar")
collar_cfg = None
if collar_raw is not None:
    if not isinstance(collar_raw, dict):
        raise ValueError(f"Symbol '{sym}': collar must be a mapping")
    collar_cfg = CollarConfig(
        symbol=sym,
        reference_price=0,  # populated in _load_config() from actual prices
        static_band_pct=float(collar_raw.get("static_band_pct", 0.20)),
        dynamic_band_pct=float(collar_raw.get("dynamic_band_pct", 0.02)),
    )

cb_raw = cfg.get("circuit_breaker")
cb_cfg = None
if cb_raw is not None:
    if not isinstance(cb_raw, dict):
        raise ValueError(f"Symbol '{sym}': circuit_breaker must be a mapping")
    cb_cfg = CircuitBreakerConfig(
        symbol=sym,
        dynamic_band_pct=float(cb_raw.get("dynamic_band_pct", 0.05)),
        reference_window_ns=int(cb_raw.get("reference_window_ns", 300_000_000_000)),
        halt_duration_ns=int(cb_raw.get("halt_duration_ns", 60_000_000_000)),
        resumption_mode=str(cb_raw.get("resumption_mode", "AUCTION")).upper(),
    )

symbols[sym] = SymbolConfig(
    name=sym,
    tick_decimals=tick_decimals,
    last_buy_price=lbp,
    last_sell_price=lsp,
    market_maker_quotes=mm_quotes,
    collar=collar_cfg,       # ← new
    circuit_breaker=cb_cfg,  # ← new
)
```

### 7.3 Extend `FixGatewayConfig` with full MM obligations

`models/mm_obligation.py` already defines `MarketMakerObligation`. The current
`FixGatewayConfig` has simple flat fields (`enforce_mm_obligation`, `mm_max_spread_ticks`,
`mm_min_qty`). These cover the basic spread/size checks but not the advanced MMP
(market-maker protection) fields in `MarketMakerObligation`.

Add an optional `mm_obligations` dict to `FixGatewayConfig` for per-symbol
obligations that supersede the flat fields:

```python
from edumatcher.models.mm_obligation import MarketMakerObligation

@dataclass
class FixGatewayConfig:
    id:                   str
    description:          str                 = ""
    role:                 ParticipantRole     = ParticipantRole.TRADER
    disconnect_behaviour: DisconnectBehaviour = DisconnectBehaviour.CANCEL_QUOTES_ONLY
    quote_refresh_policy: QuoteRefreshPolicy  = QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL
    enforce_mm_obligation: bool               = False
    mm_max_spread_ticks:  int                 = 10
    mm_min_qty:           int                 = 100
    mm_obligations:       dict[str, MarketMakerObligation] = field(default_factory=dict)
```

Parse `mm_obligations` in `load_engine_config()`:

```python
mm_obls_raw = gw_raw.get("mm_obligations") or {}
mm_obligations: dict[str, MarketMakerObligation] = {}
for sym, obl_raw in mm_obls_raw.items():
    if not isinstance(obl_raw, dict):
        continue
    mm_obligations[sym.upper()] = MarketMakerObligation(
        gateway_id=gw_id,
        symbol=sym.upper(),
        max_spread_ticks=int(obl_raw.get("max_spread_ticks", 10)),
        min_qty=int(obl_raw.get("min_qty", 100)),
        min_presence_pct=float(obl_raw.get("min_presence_pct", 0.85)),
        max_requote_delay_ns=int(obl_raw.get("max_requote_delay_ns", 500_000_000)),
        mmp_fill_count=int(obl_raw.get("mmp_fill_count", 5)),
        mmp_window_ns=int(obl_raw.get("mmp_window_ns", 1_000_000_000)),
    )
```

### 7.4 Wire collar and circuit breaker in `Engine._load_config()`

The existing `_load_config()` already calls `register_tick_decimals` for each
symbol. Extend it to populate `_collars` and `_circuit_breakers`:

```python
from edumatcher.models.price import register_tick_decimals, to_ticks

for sym, sym_cfg in self._engine_config.symbols.items():
    # 1. Register tick precision — already present, keep as-is
    register_tick_decimals(sym, sym_cfg.tick_decimals)

    # 2. Collar — new
    if sym_cfg.collar:
        ref_float = sym_cfg.last_buy_price or sym_cfg.last_sell_price
        if ref_float is not None:
            sym_cfg.collar.symbol = sym
            sym_cfg.collar.reference_price = to_ticks(float(ref_float), sym)
            self._collars[sym] = sym_cfg.collar

    # 3. Circuit breaker — new
    if sym_cfg.circuit_breaker:
        sym_cfg.circuit_breaker.symbol = sym
        self._circuit_breakers[sym] = CircuitBreakerState(
            symbol=sym, config=sym_cfg.circuit_breaker
        )
```

> `_collars` and `_circuit_breakers` are populated here (after tick decimals
> are registered) so that `to_ticks()` works correctly for reference price
> conversion.

### 7.5 Complete `engine_config.yaml` example

```yaml
gateways:
  fix:
    - id: TRADER01
      description: "Trader terminal 1"
      role: TRADER
      disconnect_behaviour: CANCEL_ALL

    - id: MM01
      description: "Market maker 1"
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_ANY_FILL
      enforce_mm_obligation: true
      mm_max_spread_ticks: 10
      mm_min_qty: 100
      mm_obligations:
        AAPL:
          max_spread_ticks:     10
          min_qty:              100
          min_presence_pct:     0.85
          max_requote_delay_ns: 500000000   # 500ms
          mmp_fill_count:       5
          mmp_window_ns:        1000000000  # 1 second

symbols:
  AAPL:
    tick_decimals: 2            # 1 tick = $0.01
    last_buy_price:  209.50
    last_sell_price: 210.50
    market_maker_quotes:
      - gateway_id: MM01
        quote_id: MM-AAPL-1
        bid_price: 209.00
        ask_price: 211.00
        bid_qty: 2000
        ask_qty: 2000
        tif: DAY
    collar:
      static_band_pct:  0.20   # ±20% from reference price
      dynamic_band_pct: 0.02   # ±2% from last trade
    circuit_breaker:
      dynamic_band_pct:    0.05
      reference_window_ns: 300000000000   # 5 minutes
      halt_duration_ns:    60000000000    # 60 seconds
      resumption_mode:     AUCTION
```

---

## Appendix — Codebase Reference

The following names appear in the plan and differ from v1 or may be unfamiliar.
All are in the current codebase.

| Plan reference | Actual name/location | Notes |
|---|---|---|
| `now_ns()` | `models/clock.py` → `now_ns()` | v1 wrongly said `monotonic_ns()` |
| `make_cancelled_msg()` | `models/message.py` | v1 said `make_order_cancelled_msg()` |
| `_publish_trade(trade)` | `engine/main.py` | v1 said `_publish_trades()` (plural) |
| `make_depth_msg()` | `models/message.py` | Already exists — do not add again |
| `make_dropcopy_fill_msg()` | `models/message.py` | Placeholder; superseded by `DropCopyPublisher` |
| `encode(topic, payload)` | `models/message.py` | Returns `list[bytes]` |
| `QuoteIndex.cancel_all_for_symbol(sym)` | `models/quote.py` | Exists — safe to call |
| `_run_uncross(from_state)` | `engine/main.py` | Used by CB resumption; uncrosses all books |
| `MarketMakerObligation` | `models/mm_obligation.py` | Already exists — do not redefine |
| `MMPState` | `models/mm_obligation.py` | Already exists |
| `SymbolConfig.market_maker_quotes` | `engine/config_loader.py` | v1 still showed `market_maker_orders` |
| `_flush_snapshots()` | `engine/main.py` | Throttled snapshot loop; called every 200ms |

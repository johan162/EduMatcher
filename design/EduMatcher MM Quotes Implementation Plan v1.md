# EduMatcher — Quotes Implementation Plan

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

## Financial Concepts Primer

Make sure you have read the *Exchange Concepts Introduction* (latest version) 
before starting this work. Especially the following concepts must be understood:

- **Market maker (MM)** — a firm that continuously provides both a buy price and a
sell price for an instrument, ensuring there is always someone willing to trade.
Market makers profit from the spread (the gap between their buy and sell prices) in
exchange for taking on the risk of holding inventory. Without market makers, buyers
and sellers might wait a long time to find a counterparty.

- **Two-sided quote** — the simultaneous submission of a bid price (the market maker
will buy at this price) and an ask price (the market maker will sell at this price).
A quote is different from a regular order: it is a commitment to both sides at once.

- **Bid** — the price a buyer (in our case, the market maker acting as buyer) is
willing to pay. The best bid is the highest price any buyer is currently offering.

- **Ask** (also called the offer) — the price a seller is willing to accept. The best
ask is the lowest price any seller is currently offering.

- **Spread** — the difference between the best ask and the best bid. A spread of
$0.05 means you can immediately buy at $150.05 or immediately sell at $150.00.
Market makers earn the spread when a buyer hits their ask and a seller hits their
bid. Market maker obligations (Phase 11) enforce that the spread stays tight.

- **Adverse selection / informed flow** — market makers are exposed to being filled
by traders who have better information about where prices are going. A market maker
who posts a bid at $150 may be hit by someone who knows the price is about to fall
to $140 — the market maker just bought shares that are about to lose value. This
is "adverse selection." "Informed flow" refers to orders from participants with an
informational advantage. MMP (Market Maker Protection, Phase 11) defends against
this by pulling quotes when fills arrive suspiciously fast.

- **Depth** — the quantity of resting orders at each price level. "Deep" books have
large quantities near the best prices; "shallow" books can be moved significantly
with a small trade. Depth metrics (Phase 12) give subscribers a summary of how much
volume is resting near the current mid price.

- **Liquidity flag** — a label attached to a fill indicating whether the filled order
was providing liquidity (the resting, passive side — a "MAKER") or consuming
liquidity (the aggressive side — a "TAKER"). Market makers typically receive a fee
rebate for providing liquidity. A "MAKER_QUOTE" flag means the resting order was
specifically a quote leg, not a regular limit order.

---

## High-Level Roadmap

| Phase | Feature | Files Touched |
|-------|---------|---------------|
| **1** | Extend `Order` and `Trade` models | `models/order.py`, `models/trade.py` |
| **2** | Participant session model | `models/participant.py` *(new)* |
| **3** | Quote model and quote index | `models/quote.py` *(new)* |
| **4** | Quote message types | `models/message.py` |
| **5** | Gateway: quote commands and display | `gateway/main.py` |
| **6** | Engine: quote handling, fill side-effects, disconnect | `engine/main.py` |
| **7** | Tests | `tests/` |

---

## Before You Start — Understand the Codebase

Before touching a single file, spend 30 minutes reading these files in order:

1. `models/order.py` — the `Order` dataclass. This is the atom of the system.
2. `models/message.py` — how ZMQ messages are built. Notice the `encode()` function
   at the top; every `make_*` function is a thin wrapper around it.
3. `engine/order_book.py` — the matching engine core. Focus on `process()` and
   `_apply_fill()`.
4. `engine/main.py` — the engine orchestrator. Find the main `while self._running:`
   loop and read how it dispatches messages to handlers like `_handle_new_order()`.

### Three helper methods you will see everywhere

You will see these called repeatedly in `engine/main.py`. They are not obvious from
their names:

**`self._book(symbol)`** — returns the `OrderBook` for a symbol, creating it if
it does not exist yet:
```python
def _book(self, symbol: str) -> OrderBook:
    if symbol not in self.books:
        self.books[symbol] = OrderBook(symbol)
    return self.books[symbol]
```

**`self._mark_dirty(symbol)`** — tells the snapshot throttle that this symbol's
book has changed and needs to be published on the next flush. Without this, the
viewer never sees the updated book state:
```python
def _mark_dirty(self, symbol: str) -> None:
    self._dirty_symbols.add(symbol)
```

**`self._gateway_status(gateway_id)`** — returns `(True, "")` if the gateway is
connected and known, or `(False, "reason string")` if not. Every handler calls
this as its first check. After Phase 2 it uses `_sessions`:
```python
def _gateway_status(self, gateway_id: str) -> tuple[bool, str]:
    session = self._sessions.get(gateway_id)
    if not session or not session.connected:
        return False, f"Gateway {gateway_id} not connected"
    return True, ""
```

### Two existing attributes you need to understand

**`self._sessions_enabled`** — a bool that is `True` when the engine is running
with session state management (opening/closing auctions etc.). It is `False` in
simple "always continuous" mode used for testing. Checking it before validating
session state lets tests skip auction-state restrictions.

**`self._session_state`** — the current `SessionState` enum value:
`PRE_OPEN`, `OPENING_AUCTION`, `CONTINUOUS`, `CLOSING_AUCTION`, or `CLOSED`. Set
by `_handle_session_transition()` when the scheduler sends a transition message.

**`self._order_symbol`** — a `dict[str, str]` mapping `order_id → symbol`. It
exists because some cancel and amend messages arrive with only an order ID — no
symbol — so the engine needs a fast way to find which book owns that order:
```python
self._order_symbol: dict[str, str] = {}
# Populated when an order is inserted into any book:
self._order_symbol[order.id] = symbol
# Cleaned up when the order is cancelled or filled:
self._order_symbol.pop(order.id, None)
```
Every new order you create (including quote legs) must be registered here, and
removed on cancellation. You will see this pattern throughout Phase 6.

### The pre-built enum lookup dict pattern

The plan mentions this in several places. Here is what it means and why it matters.

Python's `Enum("VALUE")` constructor is slow (~600ns) because it iterates all
members. For `from_dict()` methods called on every incoming message, this adds up.

The solution: build a plain dict once at module load time and use it instead:

```python
# Slow — called on every from_dict():
side = Side(d["side"])   # iterates all Side members each time

# Fast — O(1) dict lookup:
_SIDE_MAP: dict[str, Side] = {v.value: v for v in Side}
side = _SIDE_MAP[d["side"]]
```

You must add a `_ORIGIN_MAP` for the new `OrderOrigin` enum in Phase 1. Follow
the same pattern as the existing `_SIDE_MAP`, `_TYPE_MAP`, etc. in `order.py`.

### Architecture reminder

```
gateway (stdin) ──PUSH :5555──► engine ──PUB :5556──► all subscribers
                 ◄──PUB :5556──          (gateway, board, stats, ticker, clearing)

drop copy (new, Phase 13):
engine ──PUB :5557──► clearing broker / risk system / regulator
```

The engine's run loop receives one message at a time on its PULL socket, processes
it completely, then picks up the next message. This is why there are no locks — only
one thing runs at a time. **Never introduce threads or async into the engine.**

**Performance rules — maintain throughout:**
- `__slots__` on every new dataclass instantiated at high frequency
- Pre-built enum lookup dicts for all `from_dict()` methods
- `monotonic_ns()` from `models/clock.py` everywhere — never call `time.time_ns()` or `time.time()` directly
- Integer ticks for all prices — convert to float only at ZMQ publish boundaries
- Inline `_dumps({...})` on hot paths rather than calling helper functions

---

## Phase 1 — Extend `Order` and `Trade` Models

**Files:** `models/order.py`, `models/trade.py`

### 1.1 Add `OrderOrigin` enum to `order.py`

Add this enum near the top of the file, alongside `Side`, `OrderType`, `TIF`, etc.:

```python
class OrderOrigin(str, Enum):
    """
    Records how this resting order was created.

    ORDER   — submitted directly by a participant via an OrderNew message.
               This is the default for all existing orders.
    QUOTE   — generated from one leg of a QuoteNew message. The fill handler
               uses this to know it must inactivate the counterpart leg.
    IMPLIED — reserved for implied/synthetic order generation. Not yet implemented.
    """
    ORDER   = "ORDER"
    QUOTE   = "QUOTE"
    IMPLIED = "IMPLIED"
```

Immediately after the existing `_SMP_MAP` dict, add the fast lookup dict:

```python
_ORIGIN_MAP: dict[str, OrderOrigin] = {v.value: v for v in OrderOrigin}
```

### 1.2 Add `origin` and `quote_id` fields to `Order`

The `Order` dataclass uses `@dataclass(slots=True)`. With slots, **fields with
default values must come after fields without defaults**. Since all existing
optional fields are at the bottom, add the new fields after `leg_index`:

```python
# Add these two lines after leg_index:
origin:   OrderOrigin = OrderOrigin.ORDER
quote_id: Optional[str] = None
```

Why `OrderOrigin.ORDER` as default? Every existing call to `Order.create()` in the
codebase does not pass `origin` — they all create regular orders. The default means
no existing code breaks. Only quote handling in Phase 6 sets it to `QUOTE`.

### 1.3 Update `to_dict()` and `from_dict()`

In `to_dict()`, add these two lines alongside the other fields:
```python
"origin":   self.origin.value,
"quote_id": self.quote_id,
```

In `from_dict()`, add after the existing slot assignments:
```python
o.origin   = _ORIGIN_MAP.get(d.get("origin", "ORDER"), OrderOrigin.ORDER)
o.quote_id = d.get("quote_id")
```

The `.get("origin", "ORDER")` default handles JSON that does not contain an
`origin` field (e.g. new orders from gateways that do not set it). The second
argument to `_ORIGIN_MAP.get()` is a safety fallback in case the value is
unrecognised.

### 1.4 Add `aggressor_side` to `Trade`

A trade record does not currently show whether the buyer or seller was the
aggressor (the one who sent the order that triggered the match). This matters for
the time-and-sales feed: a trade at $150 where the seller was the aggressor means
someone hit the bid, which is bearish. The same price with a buyer aggressor is
bullish. Clearing and stats subscribers need this information.

**In `models/trade.py`,** add to the `Trade` dataclass after `quantity`:
```python
aggressor_side: str   # "BUY" or "SELL" — the side of the incoming aggressive order
```

Update `Trade.create()` — add `aggressor_side: str` as a required parameter
(before `now`, which has a default):
```python
@classmethod
def create(
    cls,
    symbol:          str,
    buy_order_id:    str,
    sell_order_id:   str,
    buy_gateway_id:  str,
    sell_gateway_id: str,
    price:           int,             # int ticks
    quantity:        int,
    aggressor_side:  str,             # ← new required parameter
    now:             int | None = None,  # int nanoseconds
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
        aggressor_side=aggressor_side,   # ← pass through
        timestamp=now if now is not None else monotonic_ns(),  # from models/clock.py
    )
```

Add `"aggressor_side": self.aggressor_side` to `to_dict()` and
`aggressor_side=d["aggressor_side"]` to `from_dict()`.

**In `engine/order_book.py`,** update the `Trade.create()` call in `_apply_fill()`.
The aggressor side is already known — it is `aggressor.side.value`:

```python
trade = Trade.create(
    symbol=self.symbol,
    buy_order_id=buy_order.id,
    sell_order_id=sell_order.id,
    buy_gateway_id=buy_order.gateway_id,
    sell_gateway_id=sell_order.gateway_id,
    price=fill_price,
    quantity=fill_qty,
    aggressor_side=aggressor.side.value,   # ← new — "BUY" or "SELL"
    now=now,
)
```

**In `engine/main.py`,** find the inlined trade dict near `_TRADE_TOPIC` (search
for the string `_TRADE_TOPIC`). Add `"aggressor_side": trade.aggressor_side` to
that dict so subscribers receive it.

---

## Phase 2 — Participant Session Model

**New file:** `models/participant.py`

### Why this phase exists

The engine currently tracks connected gateways in a plain set:
```python
self._connected_fix_gateways: set[str] = set()
```

This is a binary "connected or not" signal. It cannot express:
- Whether a gateway is a market maker or a regular trader
- What should happen to its orders and quotes when it disconnects
- Whether it is in KILLED state and should be blocked from future submissions

This phase replaces the set with a richer structure. Every subsequent phase
depends on it.

### 2.1 Create `models/participant.py`

```python
"""
models/participant.py — Participant session model.

In EduMatcher, gateway_id serves as both the firm identifier and the
session identifier. In a production system these would be distinct:
a firm has one identity but can have many simultaneous sessions. For
educational purposes they are the same.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class ParticipantRole(str, Enum):
    """
    Roles control which message types a session may submit.

    TRADER       — may submit OrderNew, combo orders, OCO orders.
                   May NOT submit QuoteNew. This is the default.
    MARKET_MAKER — all TRADER permissions, plus QuoteNew.
    ADMIN        — kill switch and risk management access (future use).
    """
    TRADER       = "TRADER"
    MARKET_MAKER = "MARKET_MAKER"
    ADMIN        = "ADMIN"


class DisconnectBehaviour(str, Enum):
    """
    Controls what happens to a session's resting state when it disconnects.

    CANCEL_QUOTES_ONLY — pull all quotes, leave regular limit orders resting.
                         The standard for market makers. A disconnected MM
                         cannot react to market moves, so their quotes must
                         come off immediately. But their GTC limit orders are
                         intentional standing interest and can stay.
    CANCEL_ALL         — cancel everything: quotes and orders. Used for
                         algorithmic traders whose orders are only valid while
                         their system is running.
    LEAVE_ALL          — do nothing on disconnect. Dangerous. Only for
                         testing scenarios where you want to inspect state
                         after a gateway exits.
    """
    CANCEL_QUOTES_ONLY = "CANCEL_QUOTES_ONLY"
    CANCEL_ALL         = "CANCEL_ALL"
    LEAVE_ALL          = "LEAVE_ALL"


@dataclass
class ParticipantSession:
    """
    Represents one authenticated gateway connection.

    `connected` is True while the gateway is live. Set to False on disconnect
    or kill switch. When False, _gateway_status() rejects new submissions.
    """
    gateway_id:           str
    role:                 ParticipantRole     = ParticipantRole.TRADER
    disconnect_behaviour: DisconnectBehaviour = DisconnectBehaviour.CANCEL_QUOTES_ONLY
    connected:            bool                = False
```

### 2.2 Replace `_connected_fix_gateways` with `_sessions`

This is a **replacement**, not an addition. Find every reference to
`_connected_fix_gateways` in `engine/main.py` — there will be roughly 5–8 — and
update each one.

**In `__init__`, replace:**
```python
# Remove this line:
self._connected_fix_gateways: set[str] = set()
# Add this line:
self._sessions: dict[str, ParticipantSession] = {}
```

**Everywhere the old set was checked**, change the pattern:
```python
# Old pattern:
if gateway_id in self._connected_fix_gateways:
    ...
if gateway_id not in self._connected_fix_gateways:
    ...

# New pattern:
session = self._sessions.get(gateway_id)
if session and session.connected:
    ...
if not session or not session.connected:
    ...
```

**Update `_gateway_status()`:**
```python
def _gateway_status(self, gateway_id: str) -> tuple[bool, str]:
    session = self._sessions.get(gateway_id)
    if not session or not session.connected:
        return False, f"Gateway {gateway_id} not connected"
    return True, ""
```

**Update `_handle_gateway_connect()`:**
```python
from edumatcher.models.participant import (
    ParticipantSession, ParticipantRole, DisconnectBehaviour
)

def _handle_gateway_connect(self, payload: dict[str, Any]) -> None:
    gateway_id = str(payload.get("gateway_id", "")).upper()
    # Look up config for this gateway — may not exist for unknown gateways
    cfg = (
        self._engine_config.fix_gateways.get(gateway_id)
        if self._engine_config else None
    )
    self._sessions[gateway_id] = ParticipantSession(
        gateway_id=gateway_id,
        role=cfg.role if cfg else ParticipantRole.TRADER,
        disconnect_behaviour=(
            cfg.disconnect_behaviour if cfg
            else DisconnectBehaviour.CANCEL_QUOTES_ONLY
        ),
        connected=True,
    )
    # ... rest of existing handler (send auth ack, etc.)
```

### 2.3 Extend `FixGatewayConfig` in `config_loader.py`

```python
from edumatcher.models.participant import ParticipantRole, DisconnectBehaviour

@dataclass
class FixGatewayConfig:
    id:                   str
    description:          str                 = ""
    role:                 ParticipantRole     = ParticipantRole.TRADER
    disconnect_behaviour: DisconnectBehaviour = DisconnectBehaviour.CANCEL_QUOTES_ONLY
```

In the `load_engine_config()` function, in the gateway-parsing loop, parse the new
fields. The `.upper()` call makes the YAML values case-insensitive:

```python
role_str = gw_data.get("role", "TRADER").upper()
disc_str = gw_data.get("disconnect_behaviour", "CANCEL_QUOTES_ONLY").upper()
cfg = FixGatewayConfig(
    id=gw_id,
    description=gw_data.get("description", ""),
    role=ParticipantRole(role_str),
    disconnect_behaviour=DisconnectBehaviour(disc_str),
)
```

### 2.4 Update `engine_config.yaml`

```yaml
fix_gateways:
  GW01:
    description: "Trader terminal 1"
    role: TRADER
    disconnect_behaviour: CANCEL_ALL
  MM01:
    description: "Market maker 1"
    role: MARKET_MAKER
    disconnect_behaviour: CANCEL_QUOTES_ONLY
```

---

## Phase 3 — Quote Model and Quote Index

**New file:** `models/quote.py`

### Why there is no separate quote order book

A common misunderstanding: you might expect a `QuoteOrderBook` class alongside the
regular `OrderBook`. There isn't one. When a quote arrives, it becomes two regular
`Order` objects — one BUY, one SELL — tagged with `origin=QUOTE` and inserted into
the same `OrderBook` as all other orders. The matching engine never distinguishes
between quote-origin and order-origin orders during matching. The `origin` field is
only checked in post-fill handling.

The `QuoteIndex` is purely a lookup table: given `(gateway_id, symbol)`, find the
two `order_id` values that belong to the current live quote. It is not a second
order book.

### 3.1 Create `models/quote.py`

```python
"""
models/quote.py — Quote model and quote index.

Design: NO separate quote order book.
A QuoteNew becomes two regular Order objects (BUY + SELL) tagged with
origin=QUOTE and quote_id, inserted into the single per-symbol OrderBook.

The QuoteIndex is a lightweight cross-reference that answers one question:
  "Given (gateway_id, symbol), which two order_ids are the live quote legs?"

This enables:
  O(1) — quote replacement: look up old IDs, cancel them, insert new
  O(1) — post-fill inactivation: look up counterpart ID, cancel it
  O(N) — mass cancel on disconnect: iterate all keys for a gateway_id

The matching engine never reads the QuoteIndex. It sees only the OrderBook
and branches on order.origin in the post-fill handler.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# monotonic_ns() provides a strictly-increasing nanosecond timestamp
# even when the system clock steps backward. See models/clock.py.
from edumatcher.models.clock import monotonic_ns


class QuoteState(str, Enum):
    """The lifecycle state of a quote tracked in the QuoteIndex."""
    ACTIVE              = "ACTIVE"
    # Bid was hit by an incoming sell order; ask pulled; MM must re-quote:
    INACTIVE_BID_FILLED = "INACTIVE_BID_FILLED"
    # Ask was lifted by an incoming buy order; bid pulled; MM must re-quote:
    INACTIVE_ASK_FILLED = "INACTIVE_ASK_FILLED"
    CANCELLED           = "CANCELLED"


class QuoteRefreshPolicy(str, Enum):
    """
    Determines when the counterpart leg is cancelled after a fill.

    Example: MM posts bid 500@99.00 and ask 500@101.00.
    Someone buys 100 from the ask. Bid still has 500. Ask has 400 remaining.

    INACTIVATE_ON_ANY_FILL:  pull the bid immediately. MM re-quotes fresh.
                              Conservative — protects MM from stale exposure.
                              Eurex-style behaviour. (Eurex is the German
                              derivatives exchange; this is their default policy.)
    INACTIVATE_ON_FULL_FILL: pull the bid only when the ask is fully consumed.
                              MM accumulates partial fills before re-quoting.
    NEVER_INACTIVATE:        leave both sides live always. Most liquidity,
                              most risk. MM must manage their own exposure.
    """
    INACTIVATE_ON_ANY_FILL  = "INACTIVATE_ON_ANY_FILL"
    INACTIVATE_ON_FULL_FILL = "INACTIVATE_ON_FULL_FILL"
    NEVER_INACTIVATE        = "NEVER_INACTIVATE"


@dataclass
class QuoteEntry:
    """
    Tracks the two order IDs that represent one live two-sided quote.

    Only order IDs are stored here. All prices, quantities, and statuses
    live on the Order objects inside the OrderBook. The QuoteEntry is just
    the index record — a tiny object that lets us find those orders in O(1).
    """
    quote_id:     str
    gateway_id:   str
    symbol:       str
    bid_order_id: str    # the order ID of the BUY leg in the OrderBook
    ask_order_id: str    # the order ID of the SELL leg in the OrderBook
    state:        QuoteState = QuoteState.ACTIVE
    timestamp:    int = field(default_factory=monotonic_ns)  # int nanoseconds; monotonic_ns from models/clock.py

    def counterpart_order_id(self, filled_side: str) -> str:
        """
        Given the side that was just filled, return the OTHER leg's order ID.

        If the BUY leg was filled (someone sold into our bid), the counterpart
        is the ASK leg (which we should now pull). And vice versa.
        """
        return self.ask_order_id if filled_side == "BUY" else self.bid_order_id


class QuoteIndex:
    """
    Auxiliary index: (gateway_id, symbol) → QuoteEntry.

    Enforces the rule: at most one active quote per (gateway_id, symbol) pair.
    A market maker with two symbols AAPL and MSFT can have one quote per symbol,
    giving two entries in the index keyed by ("MM01", "AAPL") and ("MM01", "MSFT").
    """

    def __init__(self) -> None:
        # The dict key is a tuple: (gateway_id, symbol)
        self._index: dict[tuple[str, str], QuoteEntry] = {}

    def get(self, gateway_id: str, symbol: str) -> Optional[QuoteEntry]:
        """Look up the current quote entry. Returns None if no quote exists."""
        return self._index.get((gateway_id, symbol))

    def put(self, entry: QuoteEntry) -> Optional[QuoteEntry]:
        """
        Register a new QuoteEntry, replacing any existing entry for the same key.
        Returns the old entry if one existed — the CALLER is responsible for
        cancelling its order IDs from the OrderBook before calling put().
        """
        key = (entry.gateway_id, entry.symbol)
        old = self._index.get(key)
        self._index[key] = entry
        return old

    def remove(self, gateway_id: str, symbol: str) -> Optional[QuoteEntry]:
        """Remove and return the entry, or None if not present."""
        return self._index.pop((gateway_id, symbol), None)

    def cancel_all_for_gateway(self, gateway_id: str) -> list[QuoteEntry]:
        """
        Remove and return ALL entries for a gateway.
        Used on disconnect and kill switch.
        The caller is responsible for cancelling the order IDs from the book.
        """
        # Collect all keys first, then pop — never mutate a dict while iterating it
        keys = [k for k in self._index if k[0] == gateway_id]
        return [self._index.pop(k) for k in keys]

    def cancel_all_for_symbol(self, symbol: str) -> list[QuoteEntry]:
        """
        Remove and return ALL entries for a symbol.
        Used on auction transition and circuit breaker halt.
        """
        keys = [k for k in self._index if k[1] == symbol]
        return [self._index.pop(k) for k in keys]

    def active_count(self) -> int:
        """Total number of active quotes across all gateways and symbols."""
        return len(self._index)
```

---

## Phase 4 — Quote Message Types

**File:** `models/message.py`

Open `message.py` and read the existing `make_*` functions to understand the
pattern before adding new ones. Each function calls `encode(topic, payload_dict)`
where `topic` is a string ZMQ topic prefix. The convention for private messages
(sent to one specific gateway) is `topic.{GATEWAY_ID}`.

Add to the module docstring the new topics:
```
quote.new             — gateway → engine: submit a two-sided quote
quote.cancel          — gateway → engine: cancel one symbol's quote or all quotes
quote.ack.{GW}        — engine → gateway: quote accepted or rejected
quote.fill.{GW}       — engine → gateway: one leg was filled (counterpart inactivated)
quote.status.{GW}     — engine → gateway: quote state changed
system.gateway_disconnect — gateway → engine: clean shutdown notification
```

Add these functions following the existing style exactly. Note that `make_quote_new_msg`
is deliberately thin — the payload is assembled by the gateway and passed through
without modification. This keeps the gateway in control of the payload structure,
which is appropriate since the gateway generates the `quote_id`:

```python
def make_quote_new_msg(payload: dict[str, Any]) -> list[bytes]:
    """Gateway → engine: submit a two-sided quote."""
    return encode("quote.new", payload)


def make_quote_cancel_msg(gateway_id: str, symbol: str | None = None) -> list[bytes]:
    """
    Gateway → engine: cancel a quote.
    If symbol is None, cancel ALL quotes for this gateway (mass cancel).
    If symbol is given, cancel only that symbol's quote.
    """
    payload: dict[str, Any] = {"gateway_id": gateway_id}
    if symbol is not None:
        payload["symbol"] = symbol
    return encode("quote.cancel", payload)


def make_quote_ack_msg(
    gateway_id: str, quote_id: str, accepted: bool, reason: str = ""
) -> list[bytes]:
    """Engine → gateway: quote accepted or rejected."""
    return encode(f"quote.ack.{gateway_id}", {
        "quote_id": quote_id,
        "accepted": accepted,
        "reason":   reason,
    })


def make_quote_fill_msg(
    gateway_id:    str,
    quote_id:      str,
    symbol:        str,
    filled_side:   str,   # "BUY" or "SELL" — which leg was hit
    fill_price:    float, # float for display (already converted from ticks by caller)
    fill_qty:      int,
    remaining_qty: int,   # remaining on the filled leg (0 if fully consumed)
) -> list[bytes]:
    """
    Engine → gateway: one quote leg was filled.
    This is separate from the regular order.fill message because the MM
    also needs to know the counterpart leg was inactivated — the quote.status
    message that follows this one carries that information.
    """
    return encode(f"quote.fill.{gateway_id}", {
        "quote_id":     quote_id,
        "symbol":       symbol,
        "filled_side":  filled_side,
        "fill_price":   fill_price,
        "fill_qty":     fill_qty,
        "remaining_qty": remaining_qty,
    })


def make_quote_status_msg(
    gateway_id:    str,
    quote_id:      str,
    symbol:        str,
    status:        str,    # QuoteState.value — "CANCELLED", "INACTIVE_BID_FILLED", etc.
    bid_remaining: int,    # 0 if inactivated or cancelled
    ask_remaining: int,    # 0 if inactivated or cancelled
) -> list[bytes]:
    """
    Engine → gateway: quote state changed.
    This is the MM's signal to re-quote. When status is INACTIVE_*_FILLED,
    the MM should submit a fresh QuoteNew with updated prices.
    """
    return encode(f"quote.status.{gateway_id}", {
        "quote_id":      quote_id,
        "symbol":        symbol,
        "status":        status,
        "bid_remaining": bid_remaining,
        "ask_remaining": ask_remaining,
    })


def make_gateway_disconnect_msg(gateway_id: str) -> list[bytes]:
    """Gateway → engine: clean shutdown. Engine cancels quotes/orders per policy."""
    return encode("system.gateway_disconnect", {"gateway_id": gateway_id})


def make_kill_switch_msg(gateway_id: str, operator: str = "SELF") -> list[bytes]:
    """
    Anyone → engine: immediately cancel all orders and quotes for a session.
    operator: "SELF" (gateway triggered), "EXCHANGE", or "BROKER".
    """
    return encode("risk.kill_switch", {
        "gateway_id": gateway_id,
        "operator":   operator,
    })


def make_kill_switch_ack_msg(
    gateway_id: str, cancelled_orders: int, cancelled_quotes: int
) -> list[bytes]:
    """Engine → gateway: kill switch executed, this many things were cancelled."""
    return encode(f"risk.kill_switch_ack.{gateway_id}", {
        "gateway_id":       gateway_id,
        "cancelled_orders": cancelled_orders,
        "cancelled_quotes": cancelled_quotes,
    })
```

---

## Phase 5 — Gateway: Quote Commands and Display

**File:** `gateway/main.py`

### 5.1 Where to add the command handler

The gateway parses commands in a function like `_parse_command()` or `_handle_input()`
— search for `elif cmd == "NEW":` to find the dispatch section. Add `QUOTE` handling
alongside `NEW`, `CANCEL`, `AMEND`, etc.

New command syntax:
```
QUOTE|SYM=AAPL|BID=149.98|BIDQTY=500|ASK=150.02|ASKQTY=500
QUOTE|SYM=AAPL|CANCEL      ← cancel only AAPL's quote
QUOTE|CANCEL               ← cancel ALL quotes for this gateway
```

```python
elif cmd == "QUOTE":
    symbol = kv.get("SYM", "").upper()
    cancel = "CANCEL" in kv  # True if CANCEL appears anywhere in the key-value pairs

    if cancel:
        # symbol may be empty string if no SYM= was given — treat as None (mass cancel)
        self.push_sock.send_multipart(
            make_quote_cancel_msg(self.gateway_id, symbol if symbol else None)
        )
        return

    # Validate that all required fields are present and parseable
    try:
        bid_price = float(kv["BID"])
        ask_price = float(kv["ASK"])
        bid_qty   = int(kv["BIDQTY"])
        ask_qty   = int(kv["ASKQTY"])
    except (KeyError, ValueError) as e:
        self._print_error(f"QUOTE parse error: {e}")
        return

    # Basic sanity checks — caught early before sending to the engine
    if bid_price >= ask_price:
        self._print_error("QUOTE rejected locally: bid price must be strictly less than ask price")
        return
    if bid_qty <= 0 or ask_qty <= 0:
        self._print_error("QUOTE rejected locally: quantities must be positive integers")
        return
    if not symbol:
        self._print_error("QUOTE rejected locally: SYM= is required")
        return

    import uuid   # move this import to the top of gateway/main.py if not already there
    payload = {
        "quote_id":   str(uuid.uuid4()),   # unique ID assigned by the gateway
        "gateway_id": self.gateway_id,
        "symbol":     symbol,
        "bid_price":  bid_price,           # float — the engine converts to int ticks
        "bid_qty":    bid_qty,
        "ask_price":  ask_price,
        "ask_qty":    ask_qty,
    }
    self.push_sock.send_multipart(make_quote_new_msg(payload))
```

Note: the gateway sends float prices. The engine is responsible for converting them
to integer ticks using `to_ticks()`. The gateway does not know or care about tick
size — that is the engine's concern.

### 5.2 Subscribe to quote response topics

The gateway has a subscriber thread that receives messages from the engine's PUB
socket. Find the section where `sub_sock.setsockopt_string(zmq.SUBSCRIBE, ...)` is
called for existing topics, and add:

```python
sub_sock.setsockopt_string(zmq.SUBSCRIBE, f"quote.ack.{self.gateway_id}")
sub_sock.setsockopt_string(zmq.SUBSCRIBE, f"quote.fill.{self.gateway_id}")
sub_sock.setsockopt_string(zmq.SUBSCRIBE, f"quote.status.{self.gateway_id}")
sub_sock.setsockopt_string(zmq.SUBSCRIBE, f"risk.kill_switch_ack.{self.gateway_id}")
```

### 5.3 Display incoming quote messages

In the subscriber thread's dispatch section (find the `elif topic == ...` chain),
add:

```python
elif topic == f"quote.ack.{self.gateway_id}":
    qid = payload.get("quote_id", "")[:8]   # show first 8 chars of UUID
    if payload.get("accepted"):
        self._console.print(f"[green]QUOTE ACK[/green]    {qid}")
    else:
        self._console.print(
            f"[red]QUOTE REJECTED[/red] {qid}: {payload.get('reason', '')}"
        )

elif topic == f"quote.fill.{self.gateway_id}":
    qid  = payload.get("quote_id", "")[:8]
    sym  = payload.get("symbol", "")
    side = payload.get("filled_side", "")
    qty  = payload.get("fill_qty", 0)
    px   = payload.get("fill_price", 0)
    self._console.print(
        f"[cyan]QUOTE FILL[/cyan]   {qid} {sym} {side} qty={qty} @{px}"
    )

elif topic == f"quote.status.{self.gateway_id}":
    qid    = payload.get("quote_id", "")[:8]
    sym    = payload.get("symbol", "")
    status = payload.get("status", "")
    self._console.print(f"[yellow]QUOTE STATUS[/yellow] {qid} {sym} → {status}")

elif topic == f"risk.kill_switch_ack.{self.gateway_id}":
    orders = payload.get("cancelled_orders", 0)
    quotes = payload.get("cancelled_quotes", 0)
    self._console.print(
        f"[bold red]KILL SWITCH[/bold red] executed — "
        f"{orders} orders and {quotes} quotes cancelled"
    )
```

### 5.4 Add the KILL command

```python
elif cmd == "KILL":
    self.push_sock.send_multipart(
        make_kill_switch_msg(self.gateway_id, operator="SELF")
    )
    self._console.print("[bold red]KILL SWITCH[/bold red] sent — awaiting confirmation")
```

### 5.5 Send disconnect notification on clean exit

Find the gateway's shutdown path — look for a `try/finally` block or a `cleanup()`
method, wherever the gateway tears down its sockets. Add the disconnect message
**before** closing the sockets:

```python
# BEFORE closing sockets:
try:
    self.push_sock.send_multipart(
        make_gateway_disconnect_msg(self.gateway_id),
        flags=zmq.NOBLOCK,   # non-blocking — don't hang if engine is gone
    )
except zmq.ZMQError:
    pass   # socket may already be in error state; ignore
```

The `zmq.NOBLOCK` flag is important. Without it, if the engine has already shut
down, `send_multipart()` could block indefinitely. `NOBLOCK` makes it raise a
`zmq.ZMQError` instead, which we catch and ignore.

---

## Phase 6 — Engine: Quote Handling

**File:** `engine/main.py`

This is the largest phase. Read every section before writing any code.

> **Dependency warning for phases implemented in order:**
> Phase 6's code references items from later phases. Use these stubs when
> implementing Phase 6, then replace them once the later phase is complete:
>
> - `self._halted_symbols` (Phase 7) — add `self._halted_symbols: dict[str, bool] = {}`
>   to `__init__` now so Guard 5 in `_handle_quote_new()` works.
> - `validate_collar()` (Phase 9) — Guard the call: `if hasattr(self, '_collars') and self._collars.get(symbol):` until Phase 9 is done.
> - `self._mm_obligations` (Phase 11) — add `self._mm_obligations: dict = {}` to `__init__` now.
> - `self._drop_copy` (Phase 13) — guard the call: `if hasattr(self, '_drop_copy'): self._drop_copy.publish(...)` until Phase 13 is done.
>
> These guards let you run the test suite after each phase without AttributeErrors.

### 6.1 Add imports and new state to `Engine.__init__()`

Add imports at the top of the file:
```python
from edumatcher.models.quote import (
    QuoteIndex, QuoteEntry, QuoteState, QuoteRefreshPolicy
)
from edumatcher.models.order import OrderOrigin
from edumatcher.models.participant import ParticipantRole, DisconnectBehaviour
from edumatcher.models.message import (
    make_quote_ack_msg, make_quote_fill_msg, make_quote_status_msg,
    make_gateway_disconnect_msg,
)
```

Add to `__init__()`:
```python
self._quote_index:          QuoteIndex = QuoteIndex()
# Per-gateway quote refresh policy. Populated from config in _load_config().
self._quote_refresh_policy: dict[str, QuoteRefreshPolicy] = {}
```

**Pre-cache ZMQ topic bytes.** The engine pre-caches frequently used topic byte
strings to avoid re-encoding them on every message. Find the section in `__init__`
that builds `self._topic_cache` and add quote topics. The cache is keyed by the
human-readable topic string:

```python
# After the engine config is loaded, iterate known gateways:
if self._engine_config:
    for gw_id in self._engine_config.fix_gateways:
        _tc = self._topic_cache
        _tc[f"quote.ack.{gw_id}"]    = f"quote.ack.{gw_id}".encode()
        _tc[f"quote.fill.{gw_id}"]   = f"quote.fill.{gw_id}".encode()
        _tc[f"quote.status.{gw_id}"] = f"quote.status.{gw_id}".encode()
```

Note: if the topic cache is built in `__init__` before the config is loaded,
move the topic population into `_load_config()` instead — right after iterating
the gateway configs.

### 6.2 Extract `_publish_events()` and `_publish_trades()`

**Do this step first, before writing any quote code.** It is the most important
refactor in this phase.

Currently, `_handle_new_order()`, `_accept_combo()`, and `_handle_oco_order()` all
contain nearly identical for-loops that iterate order events and publish fill/cancel
messages. With quote handling added, this code will need to run in one more place.
Duplicating it a fourth time makes the code unmaintainable.

The extraction process:
1. Find the events loop in `_handle_new_order()` — it looks like
   `for evt in events: if evt.status in _FILL_STATUSES: ...`
2. Move it into a new method `_publish_events(self, events, book)`
3. Replace the original loops in `_handle_new_order()`, `_accept_combo()`, and
   `_handle_oco_order()` with calls to the new method
4. Verify the tests still pass before continuing

Here is the complete `_publish_events()` method:

```python
def _publish_events(self, events: list[Order], book: "OrderBook") -> None:
    """
    Publish fill, cancel, and reject messages for a list of order events.
    Also triggers combo/OCO cascade checks and quote fill handling.

    Called after every book.process() call and after auction uncrossing.
    """
    from edumatcher.models.price import from_ticks
    _tc = self._topic_cache

    for evt in events:
        if evt.status in _FILL_STATUSES:
            # Publish the fill message to the order's gateway
            self.pub_sock.send_multipart([
                _tc.get(f"fill.{evt.gateway_id}")
                    or f"order.fill.{evt.gateway_id}".encode(),
                _dumps({
                    "order_id":      evt.id,
                    "fill_qty":      evt.quantity - evt.remaining_qty,
                    "fill_price":    from_ticks(book.last_trade_price, evt.symbol)
                                     if book.last_trade_price is not None else None,
                    "remaining_qty": evt.remaining_qty,
                    "status":        evt.status.value,
                    "symbol":        evt.symbol,
                    "side":          evt.side.value,
                    "order_type":    evt.order_type.value,
                    "qty":           evt.quantity,
                    "price":         from_ticks(evt.price, evt.symbol)
                                     if evt.price is not None else None,
                }),
            ])

            # Check if this fill completes or fails a combo
            if evt.combo_parent_id:
                self._check_combo_after_child_event(evt)

            # Check if this fill should cancel an OCO sibling
            if evt.status == OrderStatus.FILLED and evt.oco_group_id:
                self._check_oco_after_event(evt)

            # If this is a quote leg, handle the inactivation side-effect
            if evt.origin == OrderOrigin.QUOTE:
                self._on_quote_leg_filled(evt, book)

        elif evt.status == OrderStatus.CANCELLED:
            self.pub_sock.send_multipart([
                _tc.get(f"cancel.{evt.gateway_id}")
                    or f"order.cancelled.{evt.gateway_id}".encode(),
                _dumps({"order_id": evt.id}),
            ])
            if evt.combo_parent_id:
                self._check_combo_after_child_event(evt)
            if evt.oco_group_id:
                self._check_oco_after_event(evt)

        elif evt.status == OrderStatus.REJECTED:
            self.pub_sock.send_multipart(
                make_ack_msg(evt.gateway_id, evt.id, False, "Insufficient liquidity")
            )
```

And `_publish_trades()`:

```python
def _publish_trades(self, trades: list["Trade"]) -> None:
    """
    Publish trade.executed messages to all subscribers and check circuit breakers.

    The circuit breaker check happens here because it needs to see every trade
    immediately after it is produced, before the next message is processed.
    """
    from edumatcher.models.price import from_ticks
    from edumatcher.models.clock import monotonic_ns
    now = monotonic_ns()
    for trade in trades:
        self.pub_sock.send_multipart([
            _TRADE_TOPIC,
            _dumps({
                "id":              trade.id,
                "symbol":          trade.symbol,
                "buy_order_id":    trade.buy_order_id,
                "sell_order_id":   trade.sell_order_id,
                "buy_gateway_id":  trade.buy_gateway_id,
                "sell_gateway_id": trade.sell_gateway_id,
                "price":           from_ticks(trade.price, trade.symbol),
                "quantity":        trade.quantity,
                "aggressor_side":  trade.aggressor_side,
                "timestamp":       trade.timestamp,
            }),
        ])
        # Circuit breaker check — uses int ticks (trade.price), not float
        self._check_circuit_breaker(trade.symbol, trade.price, now)
```

### 6.3 Add `_handle_quote_new()`

A note on the `_reject()` helper inside this function. You might be tempted to write:

```python
def _reject(reason: str) -> None:
    self.pub_sock.send_multipart(
        make_quote_ack_msg(gateway_id, quote_id, False, reason)
    )
    return   # ← this return only exits _reject(), NOT _handle_quote_new()
```

And then call it as:

```python
if not ok:
    _reject(reason)   # ← this does NOT stop _handle_quote_new() from continuing!
```

This is a common Python mistake. The `return` inside `_reject` only returns from
`_reject`. The outer function keeps running. The correct pattern is:

```python
if not ok:
    _reject(reason)
    return    # ← explicit return in the OUTER function
```

Or more concisely, since `_reject()` returns `None`, you can use the Python
idiom `return _reject(reason)` which evaluates `_reject(reason)`, then returns
whatever `_reject` returned (which is `None`) from the outer function:

```python
if not ok:
    return _reject(reason)   # _reject runs, then outer function returns None
```

This idiom is used throughout the code below. It is a style choice that makes the
guard-clause pattern concise. Both forms are correct. The code in `_handle_quote_new()`
uses `return _reject(reason)` — read each guard clause as "if this check fails,
send a rejection and stop processing immediately."

```python
def _handle_quote_new(self, payload: dict[str, Any]) -> None:
    from edumatcher.models.price import to_ticks
    from edumatcher.engine.collar import validate_collar

    gateway_id = str(payload.get("gateway_id", "")).upper()
    quote_id   = str(payload.get("quote_id", ""))
    symbol     = str(payload.get("symbol", "")).upper()

    # Helper: send a rejection ack and return None
    def _reject(reason: str) -> None:
        self.pub_sock.send_multipart(
            make_quote_ack_msg(gateway_id, quote_id, False, reason)
        )

    # Guard 1: gateway must be connected
    ok, reason = self._gateway_status(gateway_id)
    if not ok:
        return _reject(reason)

    # Guard 2: must be a MARKET_MAKER session
    session = self._sessions.get(gateway_id)
    if not session or session.role != ParticipantRole.MARKET_MAKER:
        return _reject(f"{gateway_id} is not configured as a market maker")

    # Guard 3: quotes only during CONTINUOUS trading session
    if self._sessions_enabled and self._session_state != SessionState.CONTINUOUS:
        return _reject(
            f"Quotes only accepted in CONTINUOUS state. "
            f"Current: {self._session_state.value}. "
            f"Use limit orders for auction participation."
        )

    # Guard 4: symbol must be known
    if self._allowed_symbols and symbol not in self._allowed_symbols:
        return _reject(f"Unknown symbol: {symbol}")

    # Guard 5: symbol must not be halted (Phase 7)
    if self._halted_symbols.get(symbol):
        return _reject(f"{symbol} is currently halted")

    # Parse and validate prices and quantities
    raw_bid = payload.get("bid_price")
    raw_ask = payload.get("ask_price")
    bid_qty = int(payload.get("bid_qty", 0))
    ask_qty = int(payload.get("ask_qty", 0))

    if raw_bid is None or raw_ask is None:
        return _reject("Missing bid_price or ask_price")
    if float(raw_bid) >= float(raw_ask):
        return _reject(f"Crossed quote: bid {raw_bid} must be < ask {raw_ask}")
    if bid_qty <= 0 or ask_qty <= 0:
        return _reject("Quantities must be positive")

    # Convert float prices from gateway to int ticks
    bid_price = to_ticks(float(raw_bid), symbol)
    ask_price = to_ticks(float(raw_ask), symbol)

    # MMP spread check (Phase 11) — obligation may require a maximum spread
    obligation = self._mm_obligations.get((gateway_id, symbol))
    if obligation:
        spread = ask_price - bid_price
        if spread > obligation.max_spread_ticks:
            return _reject(
                f"Spread {spread} ticks exceeds maximum {obligation.max_spread_ticks} ticks"
            )
        if bid_qty < obligation.min_qty or ask_qty < obligation.min_qty:
            return _reject(
                f"Quote size {min(bid_qty, ask_qty)} below minimum {obligation.min_qty}"
            )

    # Collar check — both legs must be within price bands
    collar = self._collars.get(symbol)
    if collar:
        book = self.books.get(symbol)
        last_px = book.last_trade_price if book else None
        for px, label in ((bid_price, "bid"), (ask_price, "ask")):
            result = validate_collar(px, collar, last_px)
            if result.rejected:
                return _reject(f"{label} price: {result.reason}")

    # All validation passed — now build the orders
    from edumatcher.models.clock import monotonic_ns
    now  = monotonic_ns()
    book = self._book(symbol)

    # --- Atomically replace an existing quote ---
    # If this gateway already has a live quote for this symbol, cancel its
    # legs before inserting the new ones. This is a replace, not an addition.
    old_entry = self._quote_index.get(gateway_id, symbol)
    if old_entry:
        for oid in (old_entry.bid_order_id, old_entry.ask_order_id):
            book.cancel_order(oid)
            self._order_symbol.pop(oid, None)
        # No cancel notification sent — the new quote ACK is sufficient

    # --- Build two resting orders ---
    # TIF.GTC so the legs persist until explicitly cancelled or replaced.
    bid_order = Order.create(
        symbol=symbol, side=Side.BUY, order_type=OrderType.LIMIT,
        quantity=bid_qty, gateway_id=gateway_id, tif=TIF.GTC, price=bid_price,
    )
    # Set quote-specific fields AFTER create() — they are not parameters of create()
    bid_order.origin   = OrderOrigin.QUOTE
    bid_order.quote_id = quote_id

    ask_order = Order.create(
        symbol=symbol, side=Side.SELL, order_type=OrderType.LIMIT,
        quantity=ask_qty, gateway_id=gateway_id, tif=TIF.GTC, price=ask_price,
    )
    ask_order.origin   = OrderOrigin.QUOTE
    ask_order.quote_id = quote_id

    # --- Insert into the order book ---
    # process() may produce immediate fills if prices cross existing orders.
    # This is unusual but valid (MM posting inside the spread).
    bid_trades, bid_events = book.process(bid_order, match=True, now=now)
    ask_trades, ask_events = book.process(ask_order, match=True, now=now)

    # --- Register in index and symbol map ---
    # Must happen AFTER process() so that if process() immediately fills the
    # order, _on_quote_leg_filled() can find the entry via the index.
    entry = QuoteEntry(
        quote_id=quote_id, gateway_id=gateway_id, symbol=symbol,
        bid_order_id=bid_order.id, ask_order_id=ask_order.id,
    )
    self._quote_index.put(entry)
    # Register in _order_symbol so cancel-by-ID can find the book
    self._order_symbol[bid_order.id] = symbol
    self._order_symbol[ask_order.id] = symbol

    # --- Reset MMP state if a previous MMP was active ---
    mmp = self._mmp_state.get((gateway_id, symbol))
    if mmp and mmp.mmp_active:
        mmp.reset_mmp()

    # --- Publish fills (if any) from immediate crossing ---
    for trades, events in ((bid_trades, bid_events), (ask_trades, ask_events)):
        self._publish_events(events, book)
        self._publish_trades(trades)

    # --- Send the ACK last ---
    # The ACK comes AFTER publishing fill events. This ensures that if a
    # gateway receives fills and then an ACK, the ordering makes sense:
    # "your quote was accepted AND here are some immediate fills on it."
    # If ACK came first and then fills, the MM would be confused.
    self.pub_sock.send_multipart(make_quote_ack_msg(gateway_id, quote_id, True))
    self._mark_dirty(symbol)
```

### 6.4 Add `_handle_quote_cancel()`

```python
def _handle_quote_cancel(self, payload: dict[str, Any]) -> None:
    """
    Cancel one symbol's quote or all quotes for a gateway.

    Called from:
    - The run loop (QUOTE|CANCEL from a gateway)
    - _handle_gateway_disconnect() (implicit cancel on disconnect)
    - _handle_kill_switch() (implicit cancel on kill switch)
    - _on_quote_leg_filled() (MMP triggered cancel)
    - _handle_session_transition() (auction started, all quotes must go)
    """
    gateway_id = str(payload.get("gateway_id", "")).upper()
    raw_symbol = payload.get("symbol")
    symbol     = str(raw_symbol).upper() if raw_symbol else None

    if symbol:
        # Cancel only one symbol's quote
        entry = self._quote_index.remove(gateway_id, symbol)
        entries = [entry] if entry else []
    else:
        # Mass cancel — all symbols for this gateway
        entries = self._quote_index.cancel_all_for_gateway(gateway_id)

    for entry in entries:
        book = self.books.get(entry.symbol)
        if book:
            for oid in (entry.bid_order_id, entry.ask_order_id):
                book.cancel_order(oid)
                self._order_symbol.pop(oid, None)
        entry.state = QuoteState.CANCELLED
        # Notify the gateway their quote was cancelled
        self.pub_sock.send_multipart(make_quote_status_msg(
            gateway_id=gateway_id,
            quote_id=entry.quote_id,
            symbol=entry.symbol,
            status=QuoteState.CANCELLED.value,
            bid_remaining=0,
            ask_remaining=0,
        ))
        self._mark_dirty(entry.symbol)
```

### 6.5 Add `_on_quote_leg_filled()`

This is called from `_publish_events()` when `evt.origin == OrderOrigin.QUOTE`.
It handles the quote-specific side-effects after a fill: inactivating the counterpart
leg, notifying the market maker, and checking MMP.

```python
def _on_quote_leg_filled(self, order: Order, book: "OrderBook") -> None:
    """
    Called after a quote leg (BUY or SELL) receives a fill.

    This method runs inside _publish_events(), which runs inside the engine's
    single-threaded event loop. It is safe to mutate engine state here.

    Parameters
    ----------
    order : The quote-origin Order that was just filled (partially or fully).
    book  : The OrderBook containing this order.
    """
    from edumatcher.models.price import from_ticks
    if not order.quote_id:
        return  # safety check — should not happen for QUOTE-origin orders

    gateway_id = order.gateway_id
    symbol     = order.symbol
    entry      = self._quote_index.get(gateway_id, symbol)
    if not entry:
        return  # quote was already cancelled or inactivated by a previous fill

    # Determine whether to pull the counterpart leg based on the refresh policy
    policy = self._quote_refresh_policy.get(
        gateway_id, QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL  # conservative default
    )
    should_inactivate = (
        policy == QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL
        or (
            policy == QuoteRefreshPolicy.INACTIVATE_ON_FULL_FILL
            and order.remaining_qty == 0   # only inactivate when fully consumed
        )
    )

    if should_inactivate:
        # Cancel the counterpart leg
        counterpart_id = entry.counterpart_order_id(order.side.value)
        book.cancel_order(counterpart_id)
        self._order_symbol.pop(counterpart_id, None)

        # Update the entry state before removing from index
        entry.state = (
            QuoteState.INACTIVE_BID_FILLED
            if order.side == Side.BUY   # bid was hit → record bid was filled
            else QuoteState.INACTIVE_ASK_FILLED
        )
        # Remove from index — MM must submit a fresh QuoteNew to re-activate
        self._quote_index.remove(gateway_id, symbol)

        bid_remaining = order.remaining_qty if order.side == Side.BUY  else 0
        ask_remaining = order.remaining_qty if order.side == Side.SELL else 0
    else:
        # NEVER_INACTIVATE — leave counterpart live, read its current qty
        bid_ord = book._order_index.get(entry.bid_order_id)
        ask_ord = book._order_index.get(entry.ask_order_id)
        bid_remaining = bid_ord.remaining_qty if bid_ord else 0
        ask_remaining = ask_ord.remaining_qty if ask_ord else 0

    # Compute fill details for the notification messages
    fill_qty   = order.quantity - order.remaining_qty
    fill_price = (
        from_ticks(book.last_trade_price, symbol)
        if book.last_trade_price is not None else 0.0
    )

    # Send the quote fill report to the gateway
    self.pub_sock.send_multipart(make_quote_fill_msg(
        gateway_id=gateway_id,
        quote_id=order.quote_id,
        symbol=symbol,
        filled_side=order.side.value,
        fill_price=fill_price,
        fill_qty=fill_qty,
        remaining_qty=order.remaining_qty,
    ))

    # Send the quote status message (tells MM to re-quote if inactivated)
    if should_inactivate:
        self.pub_sock.send_multipart(make_quote_status_msg(
            gateway_id=gateway_id,
            quote_id=order.quote_id,
            symbol=symbol,
            status=entry.state.value,
            bid_remaining=bid_remaining,
            ask_remaining=ask_remaining,
        ))

    # --- MMP check ---
    # "Adverse selection" means the MM's quote was hit by a trader with better
    # information — e.g., someone who knows the price is about to move against the
    # MM. If fills arrive too fast (more than mmp_fill_count in mmp_window_ns),
    # MMP triggers and pulls all quotes to protect the MM from further informed flow.
    #
    # Capture now once — we call monotonic_ns() once and use it for both
    # record_fill() and activate_mmp() to ensure consistent timestamps.
    from edumatcher.models.clock import monotonic_ns
    mmp_now = monotonic_ns()
    key = (gateway_id, symbol)
    obligation = self._mm_obligations.get(key)
    if obligation:
        mmp = self._mmp_state.setdefault(
            key, MMPState(gateway_id=gateway_id, symbol=symbol)
        )
        # record_fill() returns True if the threshold was reached
        if mmp.record_fill(obligation, mmp_now) and not mmp.mmp_active:
            mmp.activate_mmp(obligation, mmp_now)
            # Cancel all quotes for this gateway+symbol
            self._handle_quote_cancel({"gateway_id": gateway_id, "symbol": symbol})

    # --- Drop copy ---
    self._drop_copy.publish(gateway_id, "quote.fill", {
        "quote_id":     order.quote_id,
        "symbol":       symbol,
        "filled_side":  order.side.value,
        "fill_price":   fill_price,
        "fill_qty":     fill_qty,
        "remaining_qty": order.remaining_qty,
    })
```

### 6.6 Add `_handle_gateway_disconnect()`

```python
def _handle_gateway_disconnect(self, payload: dict[str, Any]) -> None:
    gateway_id = str(payload.get("gateway_id", "")).upper()
    session    = self._sessions.get(gateway_id)
    if not session:
        return

    session.connected = False
    behaviour = session.disconnect_behaviour

    # Both CANCEL_QUOTES_ONLY and CANCEL_ALL cancel quotes
    if behaviour in (DisconnectBehaviour.CANCEL_QUOTES_ONLY,
                     DisconnectBehaviour.CANCEL_ALL):
        # Reuse _handle_quote_cancel with a synthetic payload
        self._handle_quote_cancel({"gateway_id": gateway_id})

    # CANCEL_ALL also cancels regular resting orders
    if behaviour == DisconnectBehaviour.CANCEL_ALL:
        for symbol, book in self.books.items():
            # list() prevents "dict changed size during iteration" error
            for order in list(book.resting_orders()):
                if order.gateway_id == gateway_id:
                    book.cancel_order(order.id)
                    self._order_symbol.pop(order.id, None)
                    self.pub_sock.send_multipart(
                        make_order_cancelled_msg(gateway_id, order.id)
                    )
            self._mark_dirty(symbol)
```

### 6.7 Cancel all quotes on auction transition

Find `_handle_session_transition()` and add this block at the very beginning,
before any existing transition logic:

```python
def _handle_session_transition(self, payload: dict[str, Any]) -> None:
    new_state = SessionState(payload.get("state", ""))

    # Quotes are only valid during CONTINUOUS trading.
    # Cancel all quotes before transitioning into any auction state.
    if new_state in (SessionState.OPENING_AUCTION, SessionState.CLOSING_AUCTION):
        for symbol in list(self.books.keys()):
            for entry in self._quote_index.cancel_all_for_symbol(symbol):
                book = self.books.get(symbol)
                if book:
                    for oid in (entry.bid_order_id, entry.ask_order_id):
                        book.cancel_order(oid)
                        self._order_symbol.pop(oid, None)
                self.pub_sock.send_multipart(make_quote_status_msg(
                    gateway_id=entry.gateway_id,
                    quote_id=entry.quote_id,
                    symbol=symbol,
                    status=QuoteState.CANCELLED.value,
                    bid_remaining=0,
                    ask_remaining=0,
                ))
                self._mark_dirty(symbol)
        if self.verbose:
            print(f"[ENGINE] All quotes cancelled for transition to {new_state.value}")

    # ... rest of existing transition handling ...
```

### 6.8 Register new handlers in the run loop

Find the main `while self._running:` loop and its message dispatch chain (the
`if topic == "order.new": ... elif topic == ...` section). Add:

```python
elif topic == "quote.new":
    self._handle_quote_new(payload)
elif topic == "quote.cancel":
    self._handle_quote_cancel(payload)
elif topic == "system.gateway_disconnect":
    self._handle_gateway_disconnect(payload)
elif topic == "risk.kill_switch":
    self._handle_kill_switch(payload)
```


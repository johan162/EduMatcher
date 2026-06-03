Version: 1.1.0

Date: 2026-05-09

Status: Design and Research Proposal

# EduMatcher — System Requirements Document

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [Messaging Protocol](#3-messaging-protocol)
4. [Domain Model](#4-domain-model)
5. [Functional Requirements — Matching Engine](#5-functional-requirements--matching-engine)
6. [Functional Requirements — Gateway](#6-functional-requirements--gateway)
7. [Functional Requirements — Order Book Viewer](#7-functional-requirements--order-book-viewer)
8. [Functional Requirements — Order Status Monitor](#8-functional-requirements--order-status-monitor)
9. [Functional Requirements — Audit Process](#9-functional-requirements--audit-process)
10. [Functional Requirements — Clearing Process](#10-functional-requirements--clearing-process)
11. [Functional Requirements — Statistics Process](#11-functional-requirements--statistics-process)
12. [Functional Requirements — Ticker Process](#12-functional-requirements--ticker-process)
12.5. [Functional Requirements — Session Scheduler](#125-functional-requirements--session-scheduler)
13. [Configuration](#13-configuration)
14. [Persistence](#14-persistence)
15. [Non-Functional Requirements](#15-non-functional-requirements)
16. [Implementation Plan](#16-implementation-plan)
17. [Test Specification](#17-test-specification)
18. [Post-v2 Requirements Addendum](#18-post-v2-requirements-addendum)

---

## 1. System Overview

EduMatcher is an educational multi-process trading system that simulates an electronic exchange. It consists of 9 independently running processes communicating over ZeroMQ (ZMQ) messaging. The system demonstrates:

- **Order matching** with price-time priority
- **7 order types**: Market, Limit, Stop, Stop-Limit, Fill-or-Kill (FOK), Iceberg, Combo
- **10 order types**: Market, Limit, Stop, Stop-Limit, Fill-or-Kill (FOK), Iceberg, Combo, IOC, Trailing Stop, OCO
- **Auction mechanisms**: opening and closing call auctions with equilibrium price discovery
- **Session scheduling**: automated phase transitions (PRE_OPEN → OPENING_AUCTION → CONTINUOUS → CLOSING_AUCTION → CLOSED)
- **Multi-leg combo orders** with cascade-cancel semantics
- **Gateway authentication** against a configured allowlist
- **Self Match Prevention** (SMP)
- **GTC order persistence** across sessions
- **Real-time market data** distribution
- **Trade settlement** with P&L tracking
- **Market statistics** with OHLCV data
- **Audit logging** of all system events

The system is designed for a single machine with all processes running as separate OS processes, communicating via TCP loopback.

### Key Terminology

This document assumes limited financial domain knowledge. All financial terms are defined in [Appendix E: Financial Glossary](#appendix-e-financial-glossary) at first use. Key concepts:

- **Order book**: a sorted collection of resting buy and sell orders for a single instrument
- **Matching**: the process of pairing a buy order with a sell order at a compatible price to produce a trade
- **Auction**: a phase where orders accumulate without matching, then execute simultaneously at a single computed price
- **Combo order**: a bundle of 2–10 child orders across different instruments, managed as a unit
- **Session phase**: the current operating mode of the exchange (e.g., accepting orders, matching, closed)

---

## 2. Architecture

### 2.1 Process Topology

```
┌───────────┐          ┌───────────────────────┐
│  Gateway  │──PUSH───▶│                       │──PUB──▶ All subscribers
│ (TRADER01)│          │                       │
└───────────┘          │    Matching Engine     │
                       │                       │
┌───────────┐          │  PULL :5555 (inbound) │
│  Gateway  │──PUSH───▶│  PUB  :5556 (outbound)│
│ (TRADER02)│          │                       │
└───────────┘          └───────────────────────┘
                                │ PUB
           ┌────────────────────┼────────────────────────────────┐
           ▼                    ▼                    ▼            ▼
    ┌─────────────┐  ┌──────────────┐  ┌─────────┐  ┌──────────┐
    │   Viewer    │  │ Order Monitor│  │  Audit  │  │ Clearing │
    │(per symbol) │  │              │  │         │  │          │
    └─────────────┘  └──────────────┘  └─────────┘  └──────────┘
           ▼                                             ▼
    ┌─────────────┐                              ┌──────────────┐
    │    Stats    │                              │    Ticker    │
    │             │                              │              │
    └─────────────┘                              └──────────────┘
```

### 2.2 Socket Configuration

| Socket | Type | Address | Role |
|--------|------|---------|------|
| Engine Inbound | PULL (bind) | `tcp://127.0.0.1:5555` | Receives all client commands |
| Engine Outbound | PUB (bind) | `tcp://127.0.0.1:5556` | Broadcasts all events |
| Gateway Outbound | PUSH (connect) | `tcp://127.0.0.1:5555` | Sends orders to engine |
| Gateway Inbound | SUB (connect) | `tcp://127.0.0.1:5556` | Receives gateway-specific events |
| Scheduler Outbound | PUSH (connect) | `tcp://127.0.0.1:5555` | Sends session transitions to engine |
| Viewer/Monitor/Audit/etc. | SUB (connect) | `tcp://127.0.0.1:5556` | Receives broadcast events |

### 2.3 ZMQ Pattern Summary

- **PUSH/PULL** (many-to-one): Gateways push commands to the engine. Messages are load-balanced if multiple PULLers exist (but in this system only one engine runs).
- **PUB/SUB** (one-to-many): Engine publishes events; subscribers filter by topic prefix.

### 2.4 Process Startup Order

1. **Engine** — must start first (binds sockets)
2. **Scheduler** — sends session transitions; can start before or after gateways
3. **Gateways** — connect to engine, authenticate, then enter command loop
4. **Viewer, Orders, Audit, Clearing, Stats, Ticker** — subscribers; can start in any order after engine

---

## 3. Messaging Protocol

### 3.1 Frame Format

All ZMQ messages are two-frame multipart messages:

| Frame | Content | Encoding |
|-------|---------|----------|
| 0 | Topic string | UTF-8 bytes |
| 1 | JSON payload | UTF-8 bytes |

### 3.2 Topic Conventions

| Topic | Direction | Description |
|-------|-----------|-------------|
| `order.new` | Gateway → Engine | Submit new order |
| `order.cancel` | Gateway → Engine | Cancel resting order |
| `order.combo` | Gateway → Engine | Submit multi-leg combo order |
| `order.combo_cancel` | Gateway → Engine | Cancel a combo and all its legs |
| `order.ack.{GW_ID}` | Engine → Gateway | Accept/reject acknowledgement |
| `order.fill.{GW_ID}` | Engine → Gateway | Partial or full fill notification |
| `order.cancelled.{GW_ID}` | Engine → Gateway | Cancel confirmation |
| `order.expired.{GW_ID}` | Engine → Gateway | DAY/ATO/ATC order expired |
| `order.orders_request` | Gateway → Engine | Request all resting orders for a gateway |
| `order.orders.{GW_ID}` | Engine → Gateway | Response: list of resting orders |
| `combo.ack.{GW_ID}` | Engine → Gateway | Combo accepted or rejected |
| `combo.status.{GW_ID}` | Engine → Gateway | Combo lifecycle status change |
| `trade.executed` | Engine → All | Trade execution broadcast |
| `book.{SYMBOL}` | Engine → All | Order book snapshot |
| `book.snapshot_request` | Any → Engine | Request immediate book snapshot |
| `session.transition` | Scheduler → Engine | Request session phase change |
| `session.state` | Engine → All | Confirm session phase change |
| `auction.result.{SYMBOL}` | Engine → All | Auction uncross result |
| `system.gateway_connect` | Gateway → Engine | Gateway authentication request |
| `system.gateway_auth.{GW_ID}` | Engine → Gateway | Authentication response |
| `system.symbols_request` | Any → Engine | Request list of active symbols |
| `system.symbols.{GW_ID}` | Engine → Requestor | Response: list of symbols |
| `system.eod` | Engine → All | End-of-day broadcast (shutdown) |

### 3.3 Message Payloads

#### 3.3.1 `order.new` — New Order Submission

```json
{
  "id": "uuid-string",
  "symbol": "AAPL",
  "side": "BUY",
  "order_type": "LIMIT",
  "tif": "DAY",
  "quantity": 100,
  "remaining_qty": 100,
  "gateway_id": "TRADER01",
  "timestamp": 1714400000.123,
  "status": "NEW",
  "price": 150.50,
  "stop_price": null,
  "visible_qty": null,
  "displayed_qty": null,
  "smp_action": "NONE"
}
```

All fields of the Order model are serialized.

#### 3.3.2 `order.cancel` — Cancel Request

```json
{
  "order_id": "uuid-string",
  "gateway_id": "TRADER01"
}
```

#### 3.3.3 `order.ack.{GW_ID}` — Acknowledgement

```json
{
  "order_id": "uuid-string",
  "accepted": true,
  "reason": "",
  "symbol": "AAPL",
  "side": "BUY",
  "order_type": "LIMIT",
  "tif": "DAY",
  "qty": 100,
  "price": 150.50
}
```

When `accepted` is `false`, `reason` contains an error description (e.g., "Symbol not configured: XYZ", "Insufficient liquidity", "Order not found").

#### 3.3.4 `order.fill.{GW_ID}` — Fill Notification

```json
{
  "order_id": "uuid-string",
  "fill_qty": 50,
  "fill_price": 150.25,
  "remaining_qty": 50,
  "status": "PARTIAL",
  "symbol": "AAPL",
  "side": "BUY",
  "order_type": "LIMIT",
  "tif": "DAY",
  "qty": 100,
  "price": 150.50
}
```

`status` is either `"PARTIAL"` or `"FILLED"`.

#### 3.3.5 `order.cancelled.{GW_ID}` — Cancel Confirmation

```json
{
  "order_id": "uuid-string"
}
```

#### 3.3.6 `order.expired.{GW_ID}` — DAY Order Expired

```json
{
  "order_id": "uuid-string"
}
```

#### 3.3.7 `trade.executed` — Trade Broadcast

```json
{
  "id": "trade-uuid",
  "symbol": "AAPL",
  "buy_order_id": "uuid-buyer",
  "sell_order_id": "uuid-seller",
  "buy_gateway_id": "TRADER01",
  "sell_gateway_id": "TRADER02",
  "price": 150.25,
  "quantity": 50,
  "timestamp": 1714400001.456
}
```

#### 3.3.8 `book.{SYMBOL}` — Book Snapshot

```json
{
  "symbol": "AAPL",
  "bids": [
    {"price": 150.00, "qty": 200, "count": 3},
    {"price": 149.50, "qty": 100, "count": 1}
  ],
  "asks": [
    {"price": 150.50, "qty": 150, "count": 2},
    {"price": 151.00, "qty": 500, "count": 1}
  ],
  "last_price": 150.25,
  "last_qty": 50,
  "last_buy_price": 150.25,
  "last_sell_price": 150.00,
  "recent_trades": [
    {
      "id": "trade-uuid",
      "symbol": "AAPL",
      "buy_order_id": "...",
      "sell_order_id": "...",
      "buy_gateway_id": "TRADER01",
      "sell_gateway_id": "TRADER02",
      "price": 150.25,
      "quantity": 50,
      "timestamp": 1714400001.456
    }
  ]
}
```

- `bids`: sorted descending by price (best bid first)
- `asks`: sorted ascending by price (best ask first)
- `recent_trades`: up to 5 most recent trades (most recent last)
- `last_buy_price`: price of the last trade where the buyer was the aggressor
- `last_sell_price`: price of the last trade where the seller was the aggressor

#### 3.3.9 `book.snapshot_request`

```json
{
  "symbol": "AAPL"
}
```

#### 3.3.10 `system.symbols_request`

```json
{
  "gateway_id": "TRADER01"
}
```

#### 3.3.11 `system.symbols.{GW_ID}`

```json
{
  "symbols": ["AAPL", "MSFT", "TSLA"]
}
```

#### 3.3.12 `order.orders_request`

```json
{
  "gateway_id": "TRADER01"
}
```

#### 3.3.13 `order.orders.{GW_ID}`

```json
{
  "orders": [
    { /* full Order.to_dict() */ },
    { /* ... */ }
  ]
}
```

#### 3.3.14 `system.eod` — End of Day

```json
{
  "books": [
    { /* book snapshot for symbol 1 */ },
    { /* book snapshot for symbol 2 */ }
  ]
}
```

#### 3.3.15 `system.gateway_connect` — Gateway Authentication Request

```json
{
  "gateway_id": "GW01"
}
```

Sent by the gateway immediately on startup, before entering the command loop.

#### 3.3.16 `system.gateway_auth.{GW_ID}` — Authentication Response

```json
{
  "gateway_id": "GW01",
  "accepted": true,
  "reason": "",
  "description": "Primary trading desk"
}
```

When `accepted` is `false`, `reason` contains the rejection cause (e.g., "Gateway not configured: GW01"). The gateway should exit on rejection.

#### 3.3.17 `order.combo` — Combo Order Submission

```json
{
  "id": "uuid-string",
  "combo_id": "MY-PAIR-01",
  "gateway_id": "GW01",
  "combo_type": "AON",
  "tif": "DAY",
  "legs": [
    {
      "symbol": "AAPL",
      "side": "BUY",
      "order_type": "LIMIT",
      "quantity": 100,
      "price": 150.50,
      "stop_price": null,
      "smp_action": "NONE"
    },
    {
      "symbol": "MSFT",
      "side": "SELL",
      "order_type": "LIMIT",
      "quantity": 50,
      "price": 415.00,
      "stop_price": null,
      "smp_action": "NONE"
    }
  ],
  "timestamp": 1714400000.123,
  "status": "PENDING"
}
```

A **combo order** bundles 2–10 child orders across different symbols into a single unit. All legs are posted to their respective order books simultaneously. If any leg is cancelled or expires, all remaining legs are cascade-cancelled.

#### 3.3.18 `order.combo_cancel` — Combo Cancel Request

```json
{
  "combo_id": "MY-PAIR-01",
  "gateway_id": "GW01"
}
```

#### 3.3.19 `combo.ack.{GW_ID}` — Combo Acknowledgement

```json
{
  "combo_id": "MY-PAIR-01",
  "accepted": true,
  "reason": "",
  "combo": {
    "id": "uuid-string",
    "combo_id": "MY-PAIR-01",
    "gateway_id": "GW01",
    "child_order_ids": [],
    "status": "PENDING"
  }
}
```

When `accepted` is `false`, `reason` contains the validation error (e.g., "Combo requires at least 2 legs", "Duplicate symbols in combo legs", "Symbol not configured: XYZ") and `combo` is omitted.

For accepted combos, the ACK is emitted immediately after validation and before child-order creation, so `combo.child_order_ids` is expected to be empty in this message.

#### 3.3.20 `combo.status.{GW_ID}` — Combo Status Change

```json
{
  "combo_id": "MY-PAIR-01",
  "status": "MATCHED",
  "details": {
    "reason": ""
  }
}
```

Possible `status` values: `PARTIALLY_MATCHED`, `MATCHED`, `FAILED`, `CANCELLED`. A `FAILED` status includes `details.reason` indicating which leg triggered the cascade (e.g., "Leg 0 (AAPL) CANCELLED").

#### 3.3.21 `session.transition` — Session Phase Change Request

```json
{
  "to_state": "CONTINUOUS"
}
```

Sent by the scheduler process. Valid `to_state` values: `PRE_OPEN`, `OPENING_AUCTION`, `CONTINUOUS`, `CLOSING_AUCTION`, `CLOSED`.

#### 3.3.22 `session.state` — Session Phase Confirmation

```json
{
  "state": "CONTINUOUS",
  "prev_state": "OPENING_AUCTION"
}
```

Published by the engine to all subscribers after a valid session transition.

#### 3.3.23 `auction.result.{SYMBOL}` — Auction Uncross Result

```json
{
  "symbol": "AAPL",
  "eq_price": 150.50,
  "eq_qty": 5000,
  "trades_count": 12,
  "imbalance_side": "BUY",
  "imbalance_qty": 500
}
```

Published for each symbol when exiting an auction phase. `eq_price` is `null` and `eq_qty` is `0` if no orders crossed. `imbalance_side` is `"BUY"`, `"SELL"`, or `""` (balanced). The **equilibrium price** is the single price that maximizes executable quantity (see FR-ENG-031).

## 4. Domain Model

### 4.1 Order

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID string | Unique identifier, generated at creation |
| `symbol` | string | Instrument symbol (e.g., "AAPL") |
| `side` | enum: BUY, SELL | Order direction |
| `order_type` | enum: MARKET, LIMIT, STOP, STOP_LIMIT, FOK, ICEBERG, COMBO, IOC, TRAILING_STOP | |
| `tif` | enum: DAY, GTC, ATO, ATC | Time-in-force |
| `quantity` | integer > 0 | Original total quantity |
| `remaining_qty` | integer ≥ 0 | Quantity still to be filled |
| `gateway_id` | string | Identifier of the submitting gateway |
| `timestamp` | float (Unix epoch, sub-second) | Creation or last-updated time |
| `status` | enum: NEW, PARTIAL, FILLED, CANCELLED, REJECTED, EXPIRED | |
| `price` | float or null | Limit price (required for LIMIT, FOK, ICEBERG, STOP_LIMIT) |
| `stop_price` | float or null | Trigger price (required for STOP, STOP_LIMIT) |
| `visible_qty` | integer or null | ICEBERG: fixed peak size per slice |
| `displayed_qty` | integer or null | ICEBERG: current visible quantity on the book |
| `smp_action` | enum: NONE, CANCEL_AGGRESSOR, CANCEL_RESTING, CANCEL_BOTH | Self Match Prevention |

### 4.2 Trade

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID string | Unique trade identifier |
| `symbol` | string | Traded instrument |
| `buy_order_id` | UUID string | ID of the buy-side order |
| `sell_order_id` | UUID string | ID of the sell-side order |
| `buy_gateway_id` | string | Gateway of the buyer |
| `sell_gateway_id` | string | Gateway of the seller |
| `price` | float | Execution price |
| `quantity` | integer > 0 | Executed quantity |
| `timestamp` | float (Unix epoch) | Execution time |

### 4.3 Enumerations

#### Side
- `BUY`
- `SELL`

#### OrderType
- `MARKET` — Execute immediately at best available price; unfilled remainder is discarded
- `LIMIT` — Execute at specified price or better; unfilled remainder rests on the book
- `STOP` — Dormant until trigger; converts to MARKET when last trade price reaches stop_price
- `STOP_LIMIT` — Dormant until trigger; converts to LIMIT when last trade price reaches stop_price
- `FOK` (Fill or Kill) — Execute entirely at specified price or better, or reject completely
- `ICEBERG` — Like LIMIT but only shows `visible_qty` at a time; hidden quantity replenishes
- `COMBO` — Bundles 2–10 child LIMIT orders across different symbols, managed as a unit with cascade-cancel
- `IOC` (Immediate-Or-Cancel) — Like LIMIT but the unfilled remainder is cancelled instead of resting; rejected during auction phases
- `TRAILING_STOP` — Like STOP but the trigger price ratchets with the market (upward for SELL, downward for BUY); requires `trail_offset`

#### TIF (Time in Force)
- `DAY` — Resting portion expires when the engine shuts down (end of session)
- `GTC` (Good 'Til Cancelled) — Persists across engine restarts
- `ATO` (At-The-Open) — Only accepted during `OPENING_AUCTION` phase; expired when the phase exits
- `ATC` (At-The-Close) — Only accepted during `CLOSING_AUCTION` phase; expired when the phase exits

#### OrderStatus
- `NEW` — Accepted and resting (or a new stop order)
- `PARTIAL` — Partially filled, remainder still resting
- `FILLED` — Completely filled
- `CANCELLED` — Cancelled by user or by SMP
- `REJECTED` — Never entered the book (e.g., FOK with insufficient liquidity)
- `EXPIRED` — DAY/ATO/ATC order removed at phase transition or engine shutdown

#### SmpAction (Self Match Prevention)
- `NONE` — Disabled; self-trades are allowed (default)
- `CANCEL_AGGRESSOR` — Cancel the incoming (aggressor) order; resting order stays
- `CANCEL_RESTING` — Cancel the resting order; continue matching with next level
- `CANCEL_BOTH` — Cancel both the aggressor and the resting order

#### SessionState

The trading session progresses through a sequence of phases. During auction phases, orders accumulate without matching; on exit, all crossable interest executes at a single equilibrium price.

- `PRE_OPEN` — Orders accepted (LIMIT, STOP, STOP_LIMIT, ICEBERG), no matching occurs
- `OPENING_AUCTION` — Orders accepted (same as PRE_OPEN + ATO), no matching; uncross on exit
- `CONTINUOUS` — Normal continuous matching; all order types accepted
- `CLOSING_AUCTION` — Orders accepted (same as PRE_OPEN + ATC), no matching; uncross on exit
- `CLOSED` — No new orders accepted

**Valid transitions:**
```
PRE_OPEN         → OPENING_AUCTION, CONTINUOUS
OPENING_AUCTION  → CONTINUOUS
CONTINUOUS       → CLOSING_AUCTION, CLOSED
CLOSING_AUCTION  → CLOSED
CLOSED           → PRE_OPEN (next day)
```

**State predicates** (used by the engine to evaluate every incoming event):

| Predicate | True when | Used for |
|-----------|-----------|----------|
| `is_matching_enabled(state)` | `state == CONTINUOUS` only | Decides whether `_sweep()` runs after order placement |
| `is_auction_phase(state)` | `state in (OPENING_AUCTION, CLOSING_AUCTION)` | Controls uncross trigger and ATO/ATC expiry on phase exit |
| `accepts_orders(state)` | `state != CLOSED` | Guards all `order.new` and `order.combo` handlers before validation |

All three predicates are pure functions of the current `session_state` — they take no other inputs.

#### ComboType
- `AON` (All or None) — All legs are posted simultaneously; failure of any leg cascades to all

#### ComboStatus
- `PENDING` — Child orders posted, waiting for fills
- `PARTIALLY_MATCHED` — One or more legs filled, others still resting
- `MATCHED` — All legs fully filled
- `FAILED` — A leg was cancelled or expired; all remaining siblings cascade-cancelled
- `CANCELLED` — User cancelled the combo
- `REJECTED` — Combo failed validation at entry

### 4.4 Combo Order Model

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID string | Internal unique identifier |
| `combo_id` | string | User-provided tracking label |
| `gateway_id` | string | Originating gateway |
| `combo_type` | enum: AON | Combo execution semantics |
| `tif` | enum: DAY, GTC, ATO, ATC | Applied to all child legs |
| `legs` | array of ComboLeg | 2–10 legs (see below) |
| `timestamp` | float (Unix epoch) | Creation time |
| `status` | ComboStatus enum | Current lifecycle state |
| `child_order_ids` | array of UUID strings | Engine-generated IDs for each child order |
| `leg_fill_qty` | dict[int, int] | Leg index → quantity filled so far |
| `leg_statuses` | dict[int, string] | Leg index → current OrderStatus of that child |

### 4.5 Combo Leg Model

| Field | Type | Description |
|-------|------|-------------|
| `symbol` | string | Instrument for this leg |
| `side` | enum: BUY, SELL | Direction |
| `order_type` | enum: LIMIT (others allowed but LIMIT is typical) | |
| `quantity` | integer > 0 | Quantity for this leg |
| `price` | float or null | Required for LIMIT, FOK, ICEBERG, STOP_LIMIT |
| `stop_price` | float or null | Required for STOP, STOP_LIMIT |
| `smp_action` | SmpAction enum | Per-leg SMP setting |

### 4.6 Child Order Backlinks to Parent Combo

Each child Order created from a ComboOrder leg carries forward references:

| Field | Type | Description |
|-------|------|-------------|
| `combo_parent_id` | UUID string or null | ID of parent ComboOrder (null for non-combo orders) |
| `leg_index` | integer or null | 0-based position in parent's legs array |

**Purpose**: Enable fast parent lookup and cascade-cancel operations:
- When a child order transitions to terminal status (CANCELLED, REJECTED, EXPIRED), the engine uses `combo_parent_id` to look up the parent
- The parent uses `_order_to_combo[child_id]` to verify the relationship and trigger cascade-cancel of siblings
- On GTC restore, child orders are re-linked to parent combos via these backlinks

### 4.7 Combo Lifecycle State Machine

ComboOrder progresses through states as legs fill and fail:

```
PENDING
  ├─→ PARTIALLY_MATCHED  (first leg fills)
  │    ├─→ MATCHED (all legs fill)
  │    └─→ FAILED (any leg cancelled/expires before full fill)
  └─→ REJECTED (validation failure at entry)
  └─→ FAILED (any leg cancelled/expires before any fills)
  └─→ CANCELLED (user cancels via order.combo_cancel)
```

**Terminal states** (combo cannot transition further): MATCHED, FAILED, CANCELLED, REJECTED
**Non-terminal states** (can still be cancelled by user): PENDING, PARTIALLY_MATCHED

**State-specific behavior**:
- **PENDING → PARTIALLY_MATCHED**: Triggered when `leg_fill_qty[any_leg] > 0` (first fill event from any leg)
- **PARTIALLY_MATCHED → MATCHED**: Triggered when all legs reach status FILLED (`is_fully_filled` property true)
- **PENDING/PARTIALLY_MATCHED → FAILED**: Triggered when any child transitions to CANCELLED or EXPIRED before combo is fully filled
- **Any non-terminal → CANCELLED**: Triggered by user sending `order.combo_cancel` request
- **Rejected combos never enter non-terminal states**: REJECTED is final, no children posted

### 4.8 Combo Cascade-Cancel Algorithm

When a child order `C` of combo `P` transitions to CANCELLED or EXPIRED:

1. **Lookup parent**: `parent_id = _order_to_combo[C.id]`; fetch `parent = _combos[parent_id]`
2. **Check if already terminal**: If `parent.status` is already MATCHED, FAILED, CANCELLED, or REJECTED: skip (no action needed)
3. **Update parent status**: Set `parent.status = FAILED` with reason "Leg {leg_index} ({symbol}) {event_type}"
4. **Cancel non-terminal siblings**: For each leg `i` with `leg_statuses[i]` NOT in (FILLED, CANCELLED, EXPIRED, REJECTED):
   - Find the corresponding child order by `child_order_ids[i]`
   - Call `book.cancel_order(child_id)` for each sibling's symbol
   - Publish `order.cancelled.{GW_ID}` for each cancelled sibling
5. **Publish combo status**: Send `combo.status.{GW_ID}` with status FAILED
6. **Preserve filled trades**: Legs that are already FILLED are NOT reversed; trades remain settled

**Key invariant**: Once a combo enters FAILED state, no further fills are expected. Subsequent child fills are isolated to their individual fills (no combo status update).

### 4.9 Engine Combo Data Structures for Tracking

The Engine maintains:

**Combo registry** (`_combos`): dict[combo_internal_id → ComboOrder]
- All active (non-terminal and terminal) combos for the session
- Used for lifecycle status updates, cascade-cancel lookups, and user cancel requests
- Subset of non-terminal combos are persisted to `data/gtc_combos.json` on shutdown (GTC only)

**Child-to-parent mapping** (`_order_to_combo`): dict[child_order_id → combo_internal_id]
- Enables O(1) parent lookup when a child order event occurs
- Populated when child orders are created (during `_accept_combo`)
- Enables cascade-cancel to find all siblings of a failed leg
- Entries are cleared when parent combo reaches terminal status (optional optimization; can also persist the stale mapping)

**Per-leg fill tracking** on ComboOrder (`leg_fill_qty`, `leg_statuses`):
- `leg_fill_qty[leg_index]` = cumulative fill quantity for that leg (updated on each fill event)
- `leg_statuses[leg_index]` = current OrderStatus of that child (updated on each status event)
- Used to compute `is_fully_filled` property and determine state transitions

---

## 5. Functional Requirements — Matching Engine

### FR-ENG-001: Socket Binding

The engine SHALL bind a PULL socket on `tcp://127.0.0.1:5555` and a PUB socket on `tcp://127.0.0.1:5556`. These addresses are configurable via constants.

### FR-ENG-002: Message Dispatch

The engine SHALL poll the PULL socket with a 200 ms timeout and dispatch based on the topic string in frame[0]:
- `order.new` → new order handler
- `order.cancel` → cancel handler
- `order.combo` → combo order handler
- `order.combo_cancel` → combo cancel handler
- `session.transition` → session state handler
- `system.gateway_connect` → gateway authentication handler
- `system.symbols_request` → symbols request handler
- `book.snapshot_request` → book snapshot handler
- `order.orders_request` → orders request handler

### FR-ENG-002A: Engine Class Architecture

The Engine maintains the following core data structures:

**Per-Symbol Order Books**:
- `books`: dict[symbol → OrderBook] — lazy-created OrderBook instances, one per active symbol
- Books are created on-demand when the first order for a symbol arrives
- All matching, book snapshots, and trade history are managed by the OrderBook instances

**Global Order Routing** (enables O(1) cancel routing):
- `_order_symbol`: dict[order_id → symbol] — fast symbol lookup for incoming cancel requests
- Allows cancel handler to route directly to the correct book in O(1) time without symbol lookup
- Populated on every order acceptance; cleared on order terminal status (FILLED, CANCELLED, REJECTED, EXPIRED)

**Combo Order Tracking** (enables cascade-cancel on leg failure):
- `_combos`: dict[combo_internal_id → ComboOrder] — tracks all active combo orders
- `_order_to_combo`: dict[child_order_id → combo_internal_id] — maps child order to parent combo
- When a combo leg fails (REJECTED or CANCELLED), all sibling legs cascade-cancel via `_order_to_combo` lookup
- Resting combos are persisted to `data/gtc_combos.json`; restored on engine restart

**Snapshot Publishing** (enables throttled snapshot broadcasts at 0.5s intervals per symbol):
- `_dirty_symbols`: set[symbol] — symbols whose books changed since last snapshot publish
- `_last_snapshot`: dict[symbol → timestamp] — per-symbol throttle tracking
- On each poll tick (200ms), iterate dirty symbols and publish snapshots only if SNAPSHOT_INTERVAL (0.5s) has elapsed
- This prevents excessive PUB socket traffic while maintaining near-real-time viewer updates

**Gateway Connection Tracking** (for authentication):
- `_connected_fix_gateways`: set[gateway_id] — authenticated gateways
- `_allowed_fix_gateways`: frozenset[gateway_id] — configured allowlist (None if no restrictions)
- Used to reject orders/combos from unauthenticated gateways

**Session State**:
- `_session_state`: SessionState (PRE_OPEN, OPENING_AUCTION, CONTINUOUS, CLOSING_AUCTION, or CLOSED)
- Controls which order types are accepted and whether matching is enabled
- Default: CONTINUOUS (for backward compatibility when no scheduler is running)

### FR-ENG-002B: Matching Pipeline (Order Processing Flow)

For each incoming `order.new` message, the engine executes:

1. **Authentication**: Validate gateway_id is connected (if gateway restrictions enabled)
2. **Symbol Validation**: Check symbol is in allowlist (if configured)
3. **Session Phase Check**: Verify order_type is allowed in current phase (FR-ENG-030)
4. **Book Routing**: Get or create OrderBook for the order's symbol via `_book(symbol)` helper
5. **Symbol Index**: Add mapping `_order_symbol[order.id] = symbol` for fast cancel routing
6. **Process**: Call `book.process(order)` which returns (trades: list[Trade], events: list[Order])
   - Execution happens synchronously; trades and fill events are generated
7. **Publish ACK**: Send `order.ack.{GW_ID}` immediately (accepted=true or false with reason)
8. **Publish Fills**: For each event with status in (PARTIAL, FILLED), send `order.fill.{GW_ID}`
9. **Publish Trades**: For each trade, send `trade.executed`
10. **Mark Dirty**: Add symbol to `_dirty_symbols` for snapshot throttling
11. **Cascade Processing** (for triggered stops and combo failures):
    - If trades occurred, check for triggered STOP/STOP_LIMIT orders via `_check_stops()` (recursive cascade)
    - Each triggered stop is re-processed as MARKET or LIMIT, potentially generating further trades
    - If order is combo child, check parent combo status via `_order_to_combo[order.id]` → cascade-cancel siblings if leg failed
12. **Return**: Engine loop continues; snapshot flushing happens on next poll tick if throttle window elapsed

For incoming `order.cancel` messages:

1. **Symbol Lookup**: Use `_order_symbol[order_id]` to get symbol in O(1) time
2. **Book Routing**: Fetch `books[symbol]`
3. **Cancel**: Call `book.cancel_order(order_id)` which invalidates heap entry (lazy deletion)
4. **Publish**: Send `order.cancelled.{GW_ID}` message
5. **Combo Check**: If cancelled order is combo child, cascade-cancel all siblings via `_order_to_combo` mapping

### FR-ENG-003: Price-Time Priority

Orders are matched using **strict price-time priority**:
- For the **buy side**: the order with the highest price has priority. Among orders at the same price, the oldest (lowest timestamp) has priority.
- For the **sell side**: the order with the lowest price has priority. Among orders at the same price, the oldest (lowest timestamp) has priority.

### FR-ENG-004: Market Order Matching

- A MARKET order SHALL be swept against the opposite side of the book with no price limit.
- If the opposite side is exhausted before the order is fully filled, the remaining quantity is **discarded** (status set to CANCELLED silently — no cancel event published).
- MARKET orders never rest on the book.

### FR-ENG-005: Limit Order Matching

- A LIMIT BUY order SHALL match against resting asks at prices ≤ the limit price.
- A LIMIT SELL order SHALL match against resting bids at prices ≥ the limit price.
- Execution price is always the **resting order's price** (passive price improvement).
- If the LIMIT order is not fully filled, the remainder rests on the book at the limit price.

### FR-ENG-006: Stop Order Handling

- A STOP order is not placed on the active book. It is stored in a separate stop-order structure.
- A **BUY STOP** fires when `last_trade_price >= stop_price`. Upon triggering, it converts to a MARKET order (price set to null, order_type set to MARKET) and is re-processed.
- A **SELL STOP** fires when `last_trade_price <= stop_price`. Same conversion.
- Stop orders are checked after every trade execution.

### FR-ENG-007: Stop-Limit Order Handling

- Same trigger conditions as STOP orders.
- Upon triggering, a STOP_LIMIT converts to a LIMIT order (order_type set to LIMIT, retains its limit price) and is re-processed.
- The timestamp is updated to the trigger time: `timestamp = time.time()`. This causes the order to move to the **back of the queue** at its price level (loses original time priority). Other orders at the same price that were posted earlier will execute first.

### FR-ENG-008: Fill-or-Kill (FOK) Matching

- Before executing any fills, the engine SHALL pre-check that the total available quantity at or better than the limit price is ≥ the order quantity.
- The available quantity check uses a price-level quantity index for efficiency.
- If insufficient liquidity: the order is REJECTED (not partially filled).
- If sufficient: the order is swept normally; it MUST be completely filled.
- FOK orders never rest on the book.

### FR-ENG-009: Iceberg Order Matching

- An ICEBERG order has a total `quantity`, a fixed `visible_qty` (peak size), and a `displayed_qty` (current visible slice).
- `displayed_qty` is initially set to `visible_qty`.
- Matching occurs only against the `displayed_qty`, not the full hidden quantity.
- When `displayed_qty` is exhausted (reaches 0) and `remaining_qty > 0`:
  - A new peak is replenished using the formula: `displayed_qty = min(visible_qty, remaining_qty)`
  - The order's timestamp is updated to current time (goes to back of queue at same price)
- Iceberg orders rest on the book like LIMIT orders.
- In the book snapshot, only `displayed_qty` is visible — the hidden quantity is never exposed.

### FR-ENG-010: Self Match Prevention (SMP)

When an incoming (aggressor) order would match against a resting order **from the same gateway_id**, and the aggressor's `smp_action` is not NONE:

- **CANCEL_AGGRESSOR**: The aggressor order is cancelled (status=CANCELLED, event published). The resting order remains untouched. Matching stops.
- **CANCEL_RESTING**: The resting order is cancelled (status=CANCELLED, event published). Matching continues with the next best resting order.
- **CANCEL_BOTH**: Both orders are cancelled. Matching stops.

SMP is checked inside both the regular sweep and the iceberg sweep. When an iceberg resting order is SMP-cancelled, **all remaining hidden quantity is removed** — the order does not replenish.

### FR-ENG-011: Order Acknowledgement

Upon receiving an `order.new` message, the engine SHALL immediately publish an `order.ack.{GW_ID}` with `accepted: true` before processing. The ack includes order metadata (symbol, side, order_type, tif, qty, price).

If the order is rejected for any reason (symbol not configured), the engine publishes an ack with `accepted: false` and a `reason` string.

### FR-ENG-012: Fill Notification

For each order whose status transitions to PARTIAL or FILLED during matching, the engine SHALL publish an `order.fill.{GW_ID}` message. This is published for **both** the aggressor and the passive (resting) order involved in each fill.

The fill message includes:
- `fill_qty`: quantity filled in this event = `order.quantity - order.remaining_qty` (cumulative total filled at the moment the fill event is published)
- `fill_price`: the last trade price
- `remaining_qty`: remaining after the fill
- `status`: PARTIAL or FILLED
- Order metadata (symbol, side, order_type, tif, qty, price)

### FR-ENG-013: Cancel Handling

- The engine maintains a global `order_id → symbol` map for O(1) routing of cancel requests.
- The engine looks up the order in the correct book and sets `status = CANCELLED`.
- The heap entry for the order is invalidated (lazy deletion).
- The price-level quantity index is decremented.
- A `order.cancelled.{GW_ID}` message is published.
- If the order is not found or already terminal: an `order.ack` with `accepted: false` and reason "Order not found" is published.

### FR-ENG-014: Trade Publication

For each trade produced by matching, the engine SHALL publish a `trade.executed` message containing the full Trade object.

### FR-ENG-015: Book Snapshot Publication

- After processing any order that produces trades or changes book state, the affected symbol is marked "dirty".
- Snapshots are published at most once per 0.5 seconds per symbol (**throttled**).
- The snapshot is flushed on every poll loop tick (every 200 ms), but only if ≥ 0.5 s have elapsed since the last publish for that symbol.
- Snapshots are published immediately (bypassing throttle) after GTC order restore and market-maker order injection at startup.

### FR-ENG-016: Book Snapshot Format

The snapshot contains:
- `bids`: aggregated by price level, sorted descending by price. Each level: `{price, qty, count}`.
- `asks`: aggregated by price level, sorted ascending by price. Each level: `{price, qty, count}`.
- For iceberg orders, only `displayed_qty` contributes to the visible `qty`.
- `last_price`, `last_qty`: most recent trade price and quantity.
- `last_buy_price`: price of last trade where buyer was aggressor.
- `last_sell_price`: price of last trade where seller was aggressor.
- `recent_trades`: up to 5 most recent trades (serialized Trade objects).

### FR-ENG-017: Symbol Allowlist

- If an engine configuration file exists and defines symbols, only those symbols are accepted.
- Orders for unlisted symbols are rejected with reason "Symbol not configured: {SYMBOL}".
- If no configuration file is present, all symbols are accepted (backward-compatible mode).

### FR-ENG-018: Market-Maker Order Injection

At startup (after GTC restore), the engine processes market-maker orders defined in the configuration file:
- Orders are parsed from FIX-like strings (same format as gateway commands).
- All MM orders use gateway_id = "MM".
- After injection, book snapshots for all affected symbols are published immediately.

### FR-ENG-019: Symbols Request

When receiving `system.symbols_request`, the engine responds with `system.symbols.{GW_ID}` containing a sorted list of all symbols that have an active order book. A symbol has an "active" order book if it contains at least one resting order, including market-maker orders injected at startup.

### FR-ENG-020: Book Snapshot Request

When receiving `book.snapshot_request`, the engine immediately publishes the current snapshot for the requested symbol (if the book exists). No throttle is applied to on-demand requests.

### FR-ENG-021: Orders Request

When receiving `order.orders_request`, the engine scans all books for resting orders belonging to the specified `gateway_id` and responds with `order.orders.{GW_ID}`.

### FR-ENG-022: Graceful Shutdown

On SIGINT or SIGTERM:
1. All resting DAY orders are expired: status set to EXPIRED, `order.expired.{GW_ID}` published for each.
2. All resting GTC orders are saved to `data/gtc_orders.json`.
3. Book statistics (last_buy_price, last_sell_price per symbol) are saved to `data/book_stats.json`.
4. A `system.eod` message is published with book snapshots for all symbols.
5. Sockets are closed.

### FR-ENG-023: GTC Order Restore

On startup, the engine loads `data/gtc_orders.json`:
- Each order is re-inserted into the appropriate book via the normal `process()` path.
- Original timestamps are preserved (maintaining time priority).
- Orders (both single-leg and combo child orders) for symbols no longer in the allowlist are skipped (with a verbose warning).
- GTC combo orders are also restored from `data/gtc_combos.json`, with their child orders re-linked to their parent combos.
- Book snapshots are published immediately for all restored books.

### FR-ENG-023A: GTC Combo Persistence and Restore

**Persistence format** (`data/gtc_combos.json`):
- File contains an array of ComboOrder objects serialized to JSON
- Only combos with `tif == GTC` and `status` in (PENDING, PARTIALLY_MATCHED) are saved (terminal-status combos are not persisted)
- Each combo includes:
  - Parent fields: `id`, `combo_id`, `gateway_id`, `combo_type`, `tif`, `timestamp`, `status`
  - Legs array: full ComboLeg definitions (symbol, side, order_type, quantity, prices, etc.)
  - Child tracking: `child_order_ids` (list of engine-generated child Order IDs)
  - Fill tracking: `leg_fill_qty` (dict[leg_index → qty_filled]), `leg_statuses` (dict[leg_index → OrderStatus])

**Restore sequence** (on startup, after GTC single-leg orders):
1. Load `data/gtc_combos.json` (returns empty array if file missing/corrupt)
2. For each combo:
   - Restore ComboOrder object with all parent and leg state
   - Register in `_combos[combo.id]` dict
   - For each `child_order_id`, add mapping `_order_to_combo[child_id] = combo.id`
3. When single-leg orders are restored (step 1 of FR-ENG-023):
   - Check if order has `combo_parent_id` set (backlink to parent)
   - If yes, verify parent combo exists in `_combos` (should exist from step 2)
   - Update parent's `leg_statuses[leg_index]` and `leg_fill_qty[leg_index]` to match the restored child's state

**Important**: GTC combo restoration happens AFTER single-leg order restoration, allowing combos to be rebuilt with their children already on the books.

### FR-ENG-024: Book Statistics Restore

On startup, `data/book_stats.json` is loaded and each book's `last_buy_price` / `last_sell_price` are restored. Persisted values take precedence over config-seeded values.

### FR-ENG-025: Heap Data Structure

The order book uses **binary heaps** (min-heap) for efficient O(log n) insertion and O(1) best-price lookup:
- Bids: max-heap simulated by negating price keys: `(-price, timestamp)`
- Asks: min-heap: `(price, timestamp)`
- Buy stops: min-heap by `(stop_price, timestamp)` — fires when price rises to stop
- Sell stops: max-heap by `(-stop_price, timestamp)` — fires when price drops to stop

Lazy deletion is used: cancelled/filled orders have their heap entry marked `valid=false` and are skipped during peek.

### FR-ENG-026: Price-Level Quantity Index

For FOK pre-checks, the engine maintains a `dict[price, total_qty]` for both bid and ask sides. This is updated on every rest, fill, and cancel.

### FR-ENG-026A: OrderBook Data Structures

The OrderBook (per-symbol) maintains the following complete data structure layout:

**Primary Matching Heaps** (price-time priority):
- `_bids`: max-heap of (−price, timestamp, Order) — BUY orders, highest price first
- `_asks`: min-heap of (price, timestamp, Order) — SELL orders, lowest price first

**Stop Order Heaps** (trigger-based):
- `_buy_stops`: min-heap of (stop_price, timestamp, Order) — fires when trade_price ≥ stop_price
- `_sell_stops`: max-heap of (−stop_price, timestamp, Order) — fires when trade_price ≤ stop_price

**Index Structures** (for O(1) lookups and state management):
- `_order_index`: dict[order_id → Order] — fast lookup for cancellations and state queries
- `_entry_index`: dict[order_id → _HeapEntry] — fast access to heap entries for lazy deletion during cancels
- `_bid_qty`: dict[price → total_qty] — bid-side price-level quantity for FOK pre-checks
- `_ask_qty`: dict[price → total_qty] — ask-side price-level quantity for FOK pre-checks

**Trade History**:
- `recent_trades`: deque[Trade] with maxlen=20 — FIFO buffer of the 20 most recent trades; persisted only the 5 most recent in snapshots

**Last-Trade State** (for trigger and statistics):
- `last_trade_price`: Optional[float] — most recent trade price on this symbol (used for STOP trigger conditions)
- `last_trade_qty`: Optional[int] — most recent trade quantity
- `last_buy_price`: Optional[float] — most recent trade price where buyer was aggressor (persisted across restarts)
- `last_sell_price`: Optional[float] — most recent trade price where seller was aggressor (persisted across restarts)

**Heap Entry Wrapper** (`_HeapEntry`):
Each heap element is a wrapper object containing:
- `key`: tuple of (±price, timestamp) — used for heap ordering
- `order`: Order — the order object itself
- `valid`: bool — set to False on lazy deletion (cancel/fill) without removing from heap; skipped during `peek()`

This design ensures O(log n) insertions, O(1) best-price lookups, and O(1) lazy cancellations without full heap reconstruction.

### FR-ENG-027: Stop Order Trigger Cascade

After any trade, all stop orders whose trigger conditions are met are collected, then each is re-processed (converted to MARKET or LIMIT). Triggered stops may produce additional trades, which may trigger further stops (recursive cascade).

### FR-ENG-028: Gateway Authentication

On receiving `system.gateway_connect`:

1. If no configuration file is loaded (backward-compatible mode): accept all gateways unconditionally.
2. If a configuration defines a `gateways.fix` allowlist:
   - If the `gateway_id` is in the allowlist: accept, add to `_connected_fix_gateways` set, reply with `system.gateway_auth.{GW_ID}` containing `accepted: true` and the configured `description`.
   - If the `gateway_id` is NOT in the allowlist: reject with reason "Gateway not configured: {GW_ID}".
3. All subsequent `order.new`, `order.cancel`, and `order.combo` messages are rejected if the `gateway_id` is not in the connected set.

### FR-ENG-029: Session State Management

The engine maintains a `session_state` variable (default: `CONTINUOUS` for backward compatibility when no scheduler is running).

On receiving `session.transition`:
1. Validate the requested transition against the allowed transitions map (see Section 4.3, SessionState).
2. If valid: update internal state, publish `session.state` to all subscribers.
3. If invalid: silently reject (log a warning). No response is sent.

### FR-ENG-030: Order Acceptance by Session Phase

Before processing any incoming `order.new`, check the current session phase:

| Phase | Accepts | Rejects (with reason) |
|-------|---------|----------------------|
| `PRE_OPEN` | LIMIT, STOP, STOP_LIMIT, ICEBERG, TRAILING_STOP (DAY/GTC only) | MARKET, FOK, IOC, ATO, ATC |
| `OPENING_AUCTION` | LIMIT, STOP, STOP_LIMIT, ICEBERG, TRAILING_STOP (DAY/GTC/ATO) | MARKET, FOK, IOC, ATC |
| `CONTINUOUS` | All order types (DAY/GTC only) | ATO, ATC |
| `CLOSING_AUCTION` | LIMIT, STOP, STOP_LIMIT, ICEBERG, TRAILING_STOP (DAY/GTC/ATC) | MARKET, FOK, IOC, ATO |
| `CLOSED` | Nothing | All orders rejected |

During non-matching phases (PRE_OPEN, OPENING_AUCTION, CLOSING_AUCTION), accepted orders rest on the book but do NOT trigger matching. Stop orders are stored but do not fire.

### FR-ENG-031: Auction Uncross (Equilibrium Price Algorithm)

When the session transitions OUT of an auction phase (OPENING_AUCTION → CONTINUOUS, or CLOSING_AUCTION → CLOSED), the engine runs the **uncross algorithm** on every symbol's order book:

1. **Candidate prices**: All distinct bid and ask prices currently resting on the book.
2. For each candidate price **P**:
   - `buy_qty` = sum of resting bid quantities where bid_price ≥ P
   - `sell_qty` = sum of resting ask quantities where ask_price ≤ P
   - `exec_qty` = min(buy_qty, sell_qty)
   - `surplus` = |buy_qty − sell_qty|
3. **Selection**: Choose the price P that maximizes `exec_qty`. Break ties by:
   - First: minimize `surplus` (the quantity that would remain unexecuted)
   - Second: if still tied, choose the lowest price
4. **Execution**: Execute all crossable interest at the single equilibrium price, respecting price-time priority for allocation. When the surplus side has more quantity than can be executed:
   - Example: 200 BUY orders resting at $100, 100 SELL orders resting at $100 → eq_price = $100, eq_qty = 100 (fully crosses seller side), surplus = 100 (buy side).
   - Allocation: Among the 200 buy orders at $100, only the first 100 (by time priority) execute. The remaining 100 stay resting on the book.
5. **Publication**: Publish `trade.executed` and `order.fill` messages for each fill, then `auction.result.{SYMBOL}` with the result summary.

If no prices cross (no bids ≥ any ask), `eq_price` is null and `eq_qty` is 0.

### FR-ENG-032: ATO/ATC Order Expiry

- On exiting `OPENING_AUCTION`: expire all resting ATO orders (publish `order.expired.{GW_ID}` for each).
- On exiting `CLOSING_AUCTION`: expire all resting ATC orders.
- Expiry occurs AFTER the uncross execution (ATO/ATC orders participate in the auction).

### FR-ENG-033: Combo Order Validation

On receiving `order.combo`, validate before accepting:

1. **Leg count**: 2 ≤ leg_count ≤ 10. Reject: "Combo requires at least 2 legs" or "Combo supports at most 10 legs".
2. **Symbol uniqueness**: No duplicate symbols across legs. Reject: "Duplicate symbols in combo legs".
3. **Symbol allowlist**: Each leg's symbol must be configured. Reject: "Symbol not configured: {SYM}".
4. **Quantity**: Each leg's quantity must be > 0. Reject: "Leg {i}: invalid quantity {QTY}".
5. **Price requirements**: Same rules as single orders (LIMIT requires price, STOP requires stop_price, etc.).

On success: publish `combo.ack.{GW_ID}` with `accepted: true` and a `combo` object containing the parent combo's pre-child-creation state (`child_order_ids` empty at ACK time).
On failure: publish `combo.ack.{GW_ID}` with `accepted: false` and `reason`.

### FR-ENG-034: Combo Child Order Creation

On valid combo acceptance:
1. Create one child order per leg, each tagged with the parent `combo_id` for reverse lookup.
2. Post each child to its respective symbol's order book via the normal order processing path.
3. During CONTINUOUS phase, children match immediately if crossable (like normal orders).
4. During auction phases, children rest without matching (like normal orders).

### FR-ENG-035: Combo Fill Tracking

On every child order fill event:
1. Update `leg_fill_qty[leg_index]` with the new fill quantity.
2. If ALL legs are fully filled: set combo status to `MATCHED`, publish `combo.status.{GW_ID}`.
3. If this is the first fill of any leg (combo was previously `PENDING`): set status to `PARTIALLY_MATCHED`, publish `combo.status.{GW_ID}`.

### FR-ENG-036: Combo Cascade Cancel

If any child order transitions to `CANCELLED` or `EXPIRED` (by user cancel, SMP, or phase-change expiry):
1. Set combo status to `FAILED` with reason indicating which leg triggered it (e.g., "Leg 0 (AAPL) CANCELLED").
2. Cancel all remaining unfilled child orders (publish `order.cancelled.{GW_ID}` for each).
3. Publish `combo.status.{GW_ID}` with status `FAILED`.
4. **Fills already executed are NOT reversed.** Completed trades remain settled.

### FR-ENG-037: Combo Cancel by User

On receiving `order.combo_cancel`:
1. Look up the combo by `combo_id` and `gateway_id`.
2. Cancel all unfilled child orders.
3. Set combo status to `CANCELLED`.
4. Publish `combo.status.{GW_ID}` with status `CANCELLED`.
5. If the combo is already in a terminal state (MATCHED, FAILED, CANCELLED, REJECTED): reject with "Combo already {STATUS}".

### FR-ENG-038: Market-Maker Combo Injection

At startup, the engine processes combos defined in the `market_maker_combos` configuration section, in this order:
1. Restore GTC orders from `data/gtc_orders.json` and `data/gtc_combos.json`
2. Inject single-leg market-maker orders from `market_maker_orders` config
3. Inject market-maker combos from `market_maker_combos` config (this step)

For each MM combo:
- Each entry follows the same validation rules as user-submitted combos.
- All MM combos use `gateway_id = "MM"`.
- Child orders are posted to books and participate in matching normally.

---

## 6. Functional Requirements — Gateway
### FR-ENG-039: Immediate-Or-Cancel (IOC) Matching

- An `IOC` order is a LIMIT-like order that must fill immediately; any unfilled remainder is cancelled.
- The engine SHALL reject an `IOC` order submitted during any non-matching session phase (PRE_OPEN, OPENING_AUCTION, CLOSING_AUCTION).
- During continuous trading, the engine sweeps the opposite side using the same price-priority logic as a LIMIT order, up to the IOC's limit price.
- After the sweep, any remaining quantity is set to CANCELLED and an `order.cancelled.{GW_ID}` event is published.
- An `IOC` order is never added to the resting order book.
- SMP rules apply during the IOC sweep exactly as they do for LIMIT orders.
- `PRICE=` is required; IOC without a price limit is rejected.

### FR-ENG-040: Trailing Stop Order Handling

- A `TRAILING_STOP` order has a `trail_offset` (required) and an optional explicit `stop_price`.
- If `stop_price` is omitted and a last trade price exists for the symbol, the engine computes:
  - SELL trailing stop: `stop_price = last_trade_price − trail_offset`
  - BUY trailing stop: `stop_price = last_trade_price + trail_offset`
- If `stop_price` is omitted and no last trade price exists, the order is **rejected**.
- After each trade on the symbol, the engine iterates all resting trailing stops and:
  - **SELL**: updates `stop_price = max(stop_price, trade_price − trail_offset)` (ratchet upward only).
    Triggers if `trade_price ≤ stop_price`.
  - **BUY**: updates `stop_price = min(stop_price, trade_price + trail_offset)` (ratchet downward only).
    Triggers if `trade_price ≥ stop_price`.
- On trigger, the trailing stop is converted to a MARKET order and processed immediately in the same trade cycle.
- Trailing stops are stored in a separate `_trailing_stops` list (not in the price heap).
- Cancelled trailing stops are pruned lazily on the next trade cycle.
- `TRAIL=` (trail_offset) is required; the order is rejected without it.

### FR-ENG-041: OCO (One-Cancels-Other) Order Pair

- An OCO request creates two linked orders from a single `order.oco` message.
- Both legs share the same `symbol`, `quantity`, and `tif`; each leg has its own `side`, `order_type`, and price fields.
- Validation rules:
  - `gateway_id` must be an authenticated gateway.
  - `symbol` must be in the engine's symbol allowlist.
  - LIMIT legs require a `price` field; STOP legs require a `stop_price` field.
  - `oco_id` must not already be registered.
- On validation success, the engine:
  1. Creates both `Order` objects, each tagged with `oco_group_id = oco_id`.
  2. Registers the group in `_oco_groups` and `_order_to_oco`.
  3. Posts both orders to the order book.
  4. Publishes `oco.ack.{GW_ID}` with `accepted: true` and `order_id_1`, `order_id_2`.
- On validation failure, the engine publishes `oco.ack.{GW_ID}` with `accepted: false` and a `reason`.
- Whenever an OCO leg transitions to a terminal state (FILLED, CANCELLED, REJECTED):
  1. The engine looks up the sibling order via `_order_to_oco` + `_oco_groups`.
  2. Issues a cancel for the sibling order.
  3. Publishes `oco.cancelled.{GW_ID}` with the sibling's order ID and reason.
  4. Removes the OCO group from tracking.
- An OCO pair can be cancelled explicitly via an `order.oco_cancel` message (`CANCEL|OCO_ID=`):
  - Both legs are cancelled.
  - `order.cancelled.{GW_ID}` is published for each leg.
  - The OCO group is removed.

---

## 6. Functional Requirements — Gateway

### FR-GW-001: Command Interface

The gateway provides an interactive terminal prompt accepting pipe-delimited FIX-like commands:

```
NEW|SYM=<symbol>|SIDE=<BUY|SELL>|TYPE=<type>|QTY=<n>[|PRICE=<p>][|STOP=<p>][|TIF=<DAY|GTC|ATO|ATC>][|VISIBLE=<n>][|SMP=<action>]
NEW|TYPE=COMBO|COMBO_ID=<label>|COMBO_TYPE=AON|TIF=<DAY|GTC|ATO|ATC>[|LEG_COUNT=<n>]|LEG0.SYM=<sym>|LEG0.SIDE=<BUY|SELL>|LEG0.QTY=<n>|LEG0.PRICE=<p>[|LEG0.TYPE=LIMIT]|LEG1.SYM=...
CANCEL|ID=<order-id>
CANCEL|COMBO_ID=<label>
ORDERS
SYMBOLS
HELP
EXIT / QUIT
```

### FR-GW-002: Field Parsing

- Fields are separated by `|`, key-value pairs by `=`.
- All field names and values are case-insensitive (converted to uppercase internally).
- The first segment is the command verb (NEW, CANCEL, etc.).

### FR-GW-003: Input Validation

Before sending to the engine, the gateway validates:
- LIMIT, FOK, ICEBERG require `PRICE=`
- STOP, STOP_LIMIT require `STOP=`
- STOP_LIMIT requires both `STOP=` and `PRICE=`
- ICEBERG requires `VISIBLE=`
- ICEBERG: `VISIBLE` must be less than `QTY`

Invalid commands display an error locally without sending to the engine.

### FR-GW-004: Order ID Generation

The gateway creates the Order object locally (generating UUID) and sends the full serialized order to the engine. This means the gateway knows the order ID immediately.

### FR-GW-005: Order Cache

The gateway maintains a local `order_cache` (keyed by order_id) tracking all orders and their current status. The cache is populated:
- Immediately upon sending NEW (status = "PENDING")
- Updated on ACK, FILL, CANCEL, EXPIRE events from the engine
- Restored from the engine on startup via `order.orders_request`

### FR-GW-006: Event Display

Background events from the engine are printed to the terminal in real-time with timestamps:
- ACK: `[HH:MM:SS.mmm] ACK       <id8>  order accepted`
- REJECTED: `[HH:MM:SS.mmm] REJECTED  <id8>  <reason>`
- FILL: `[HH:MM:SS.mmm] FILL      <id8>  qty=<n> @<price>  remaining=<n>  [<status>]`
- CANCELLED: `[HH:MM:SS.mmm] CANCELLED <id8>`
- EXPIRED: `[HH:MM:SS.mmm] EXPIRED   <id8>  (DAY order — trading day ended)`

### FR-GW-007: ORDERS Command

Displays a formatted table of all cached orders with columns: ID (first 8 chars), Symbol, Side, Type, TIF, Qty, Remaining, Price, Status (colour-coded), Time. Sorted by time descending.

### FR-GW-008: SYMBOLS Command

Sends a `system.symbols_request` to the engine. Upon receiving the response, displays a table of active instruments.

### FR-GW-009: Tab Completion

The gateway provides context-aware tab completion:
- First segment: top-level commands (NEW, CANCEL, ORDERS, SYMBOLS, HELP, EXIT, QUIT)
- After `NEW|`: single-leg field names (SYM=, SIDE=, TYPE=, etc.), filtered by order type if TYPE= is already entered
- After a `KEY=`: value suggestions (e.g., SIDE= suggests BUY/SELL; TYPE= suggests all types; SMP= suggests actions)
- `SYM=` suggests known symbols (populated from SYMBOLS response)

Current behavior note: the completer is optimized for single-leg commands. It does not provide dedicated dynamic suggestions for COMBO leg fields (`LEG0.SYM=`, `LEG1.QTY=`, etc.) and, for `CANCEL|`, it suggests `ID=` (even though `COMBO_ID=` is accepted by the parser).

### FR-GW-010: Command History

The gateway supports up/down arrow key history navigation (in-memory, session-scoped).

### FR-GW-011: Background Listener

A daemon thread polls the SUB socket and processes events asynchronously while the user types commands. Output is interleaved cleanly using stdout patching.

### FR-GW-012: Reconnection Support

On startup, the gateway:
1. Subscribes to: `order.ack.{GW_ID}`, `order.fill.{GW_ID}`, `order.cancelled.{GW_ID}`, `order.expired.{GW_ID}`, `order.orders.{GW_ID}`, `system.symbols.{GW_ID}`, `combo.ack.{GW_ID}`, `combo.status.{GW_ID}`, `system.gateway_auth.{GW_ID}`
2. Waits 100 ms for socket connection
3. Sends `system.gateway_connect` to authenticate
4. Waits for `system.gateway_auth.{GW_ID}` response; exits if rejected
5. Sends `order.orders_request` to restore outstanding orders into the cache

### FR-GW-013: Graceful Exit

On EXIT/QUIT command, EOFError, or KeyboardInterrupt:
- Set `_running = False`
- Close PUSH and SUB sockets
- Print disconnection message

### FR-GW-014: Gateway Authentication

On startup (before entering the command loop):
1. Gateway sends `system.gateway_connect` with its own `gateway_id`.
2. Subscribes to `system.gateway_auth.{GW_ID}` and waits for the response.
3. If `accepted: true`: prints description and proceeds to the command loop.
4. If `accepted: false`: prints the rejection reason and exits immediately.
5. If no response within 3 seconds (engine not running): prints warning and exits. The gateway will not proceed in degraded mode — the engine must be running and responsive.

### FR-GW-015: Combo Command Handling

When the user enters a COMBO command:
1. Parse `COMBO_ID`, `COMBO_TYPE` (default: AON), `TIF` (default: DAY), and `LEG_COUNT`.
2. For each leg index `i` (0 to LEG_COUNT-1), parse `LEG{i}.SYM`, `LEG{i}.SIDE`, `LEG{i}.QTY`, `LEG{i}.PRICE`, and optionally `LEG{i}.TYPE` (default: LIMIT).
3. Validate locally: LEG_COUNT ≥ 2, all required fields present.
4. Build and send `order.combo` message to engine.
5. On `combo.ack`: display acceptance or rejection.
6. On `combo.status`: display lifecycle transitions.

---

## 7. Functional Requirements — Order Book Viewer

### FR-VIEW-001: Single-Symbol Display

The viewer displays a live-updating terminal view for a single symbol (specified via `--symbol` CLI argument).

### FR-VIEW-002: Display Layout

A bordered panel containing three tables side-by-side:
1. **Bids table**: Price (green, right-aligned), Qty, #Orders — sorted best (highest) first
2. **Asks table**: Price (red, right-aligned), Qty, #Orders — sorted best (lowest) first
3. **Recent Trades table**: Time (HH:MM:SS.mmm), Price, Qty — most recent at top. Displays up to 5 most recent trades (engine stores up to 20 internally).

Header line shows: `{SYMBOL}   Last: {price} (qty {n})   Last Buy: {price}   Last Sell: {price}   Updated: HH:MM:SS`

### FR-VIEW-003: Depth Configuration

The `--depth` CLI argument controls how many price levels are displayed (default: 10).

### FR-VIEW-004: Refresh Rate

The display refreshes at 2 Hz (configurable constant `_REFRESH_HZ`).

### FR-VIEW-005: Snapshot Request on Startup

On startup, the viewer sends a `book.snapshot_request` to the engine (after a 150 ms delay to allow SUB subscription to propagate). This ensures the viewer shows data immediately on connect/reconnect rather than waiting for the next order event.

### FR-VIEW-006: Data Source

The viewer subscribes to `book.{SYMBOL}` and stores the latest received snapshot. The display is rebuilt from this snapshot on every refresh cycle regardless of whether new data arrived.

---

## 8. Functional Requirements — Order Status Monitor

### FR-ORD-001: All-Orders Display

The order monitor shows a live-updating table of all order events across all gateways (or filtered to a single gateway via `--gateway`).

### FR-ORD-002: Topic Subscription

Subscribes to the prefix `order.` — receiving all order-related events (acks, fills, cancels, expires).

### FR-ORD-003: State Accumulation

Maintains a dictionary keyed by `order_id`. Each event updates the order's state:
- `order.ack` with `accepted=true` → status "NEW"
- `order.ack` with `accepted=false` → status "REJECTED"
- `order.fill` → updates `remaining` and `status`
- `order.cancelled` → status "CANCELLED"
- `order.expired` → status "EXPIRED"

Gateway ID is extracted from the topic string (e.g., `order.ack.TRADER01` → gateway_id = "TRADER01").

### FR-ORD-004: Display Table

Columns: ID (8 chars), Gateway, Symbol, Side, Type, TIF, Qty, Remaining, Price, Status (colour-coded), Updated (HH:MM:SS). Sorted by updated time descending.

### FR-ORD-005: Refresh Rate

Display refreshes at 2 Hz using a live terminal table.

---

## 9. Functional Requirements — Audit Process

### FR-AUD-001: Universal Subscription

Subscribes to all topics (empty string subscription filter → receives everything published on the PUB socket).

### FR-AUD-002: Log Format

Each event is written as a single line:
```
[2026-04-29T14:32:01.123] [topic.name] {"json": "payload"}
```

Timestamps are UTC ISO-8601 with millisecond precision.

### FR-AUD-003: Log Rotation

Uses a rotating file handler:
- Max file size: 10 MB
- Backup count: 5 (keeps up to 5 rotated files)
- Encoding: UTF-8

### FR-AUD-004: Default Log Path

`data/audit.log` (configurable via `--log-file` CLI argument).

### FR-AUD-005: Terminal Output

Optional `--terminal` flag also prints each audit entry to stdout.

### FR-AUD-006: Error Resilience

A single malformed message SHALL NOT crash the receive loop. Decode errors are logged as warnings and the message is skipped.

---

## 10. Functional Requirements — Clearing Process

### FR-CLR-001: Trade Subscription

Subscribes to `trade.executed` topic.

### FR-CLR-002: CSV Recording

Every trade is appended to `data/clearing_report.csv` with columns:
- trade_id, symbol, buy_order_id, sell_order_id, buy_gateway, sell_gateway, price, quantity, timestamp (ISO UTC)

The CSV header is written only if the file is new or empty.

### FR-CLR-003: Position Tracking

Maintains per-gateway, per-symbol position records:
- `position`: net quantity (positive = long, negative = short)
- `avg_cost`: Volume-Weighted Average Price of the current position
- `realized_pnl`: profit/loss from closed positions
- `unrealized_pnl`: `position × (last_price - avg_cost)`

### FR-CLR-004: Position Update Logic

For each trade, both the buyer and seller are updated:

**Adding to position** (same direction as existing):
- `avg_cost = (old_avg_cost × |old_position| + fill_price × fill_qty) / |new_position|`

**Reducing/reversing position** (opposite direction):
- `realized_pnl += (fill_price - avg_cost) × reduce_qty` (for longs)
- `realized_pnl += (avg_cost - fill_price) × reduce_qty` (for shorts)
- If fully closed: `avg_cost = 0`
- If reversed: `avg_cost = fill_price` for the new direction

### FR-CLR-005: P&L Table

A formatted P&L summary table is printed:
- Every N trades (configurable, default 10)
- On graceful shutdown (Ctrl-C)

Columns: Gateway, Symbol, Position, Avg Cost, Last Price, Realized, Unrealized, Total P&L (colour-coded green/red).

### FR-CLR-006: Trade Counter Display

Each trade is printed to the console with: timestamp, trade ID (8 chars), symbol, qty, price, buyer gateway, seller gateway.

---

## 11. Functional Requirements — Statistics Process

### FR-STAT-001: Subscriptions

Subscribes to: `trade.*`, `book.*`, `system.eod`, `system.symbols.STATS`

### FR-STAT-002: SQLite Database

Maintains a SQLite database (default `data/stats.db`) with three tables:

**daily_stats** (primary key: date + symbol):
- date, symbol, open_price, high_price, low_price, close_price
- open_bid, open_ask, close_bid, close_ask
- volume, trade_count, vwap, largest_trade_qty, largest_trade_price

**price_snapshots** (primary key: ts + symbol):
- ts (ISO UTC), symbol, mid_price, best_bid, best_ask, pct_change

**trade_log** (primary key: trade_id):
- ts, trade_id, symbol, price, quantity, buy_gateway_id, sell_gateway_id

### FR-STAT-003: Daily Statistics

On each trade:
- If first trade of the day for that symbol: `open_price = trade.price`
- Update `high_price = max(high_price, price)`, `low_price = min(low_price, price)`
- `close_price = price` (always the latest)
- `volume += quantity`, `trade_count += 1`
- VWAP = `Σ(price × qty) / Σ(qty)`
- Track `largest_trade_qty` and `largest_trade_price`
- Upsert row in daily_stats immediately

### FR-STAT-004: Opening Bid/Ask

From the first book snapshot of the day for each symbol, record `open_bid` and `open_ask`.

### FR-STAT-005: Price Snapshots

Every 15 minutes per symbol (based on monotonic clock since last snapshot), record:
- `mid_price = (best_bid + best_ask) / 2` (or whichever is available)
- `pct_change` vs previous snapshot's mid_price
- Best bid and best ask

### FR-STAT-006: Trade Log

Every trade is inserted into `trade_log` with ISO UTC timestamp.

### FR-STAT-007: End-of-Day Handling

On `system.eod`:
- For each symbol's book in the EOD payload, record `close_bid` and `close_ask`.
- Flush the daily_stats row.

### FR-STAT-008: Startup Symbol Discovery

On startup (after 300 ms socket connection delay):
1. Send `system.symbols_request` with gateway_id "STATS"
2. On receiving the response, send `book.snapshot_request` for each symbol
3. This ensures opening prices are captured even if no new orders arrive

---

## 12. Functional Requirements — Ticker Process

### FR-TICK-001: Scrolling Display

The ticker prints one line of market data every N seconds (default 30, configurable via `--interval`). Lines scroll naturally in the terminal.

### FR-TICK-002: Line Format

```
HH:MM:SS  ◆  SYMBOL  PRICE  ±%  H:high  L:low  Vol:n (nT)  bid/ask  ◆  SYMBOL2 ...
```

Fields:
- Price: last trade price (from live book data or daily close)
- %: change from today's open_price
- H/L: today's high/low
- Vol: today's volume
- nT: trade count
- bid/ask: current best bid / best ask

### FR-TICK-003: Data Sources

- **Live data**: subscribes to `book.*` for real-time last_price, best_bid, best_ask
- **Daily data**: queries the `daily_stats` SQLite table every `--db-interval` seconds (default 900 = 15 minutes) for OHLCV

### FR-TICK-004: Symbol Discovery

Symbols are discovered from both live book updates and the database. The symbol list is maintained in sorted order.

---

## 12.5. Functional Requirements — Session Scheduler

The scheduler is a lightweight process that drives the engine through its session phases by sending `session.transition` messages at configured times.

### FR-SCHED-001: Transition Messages

The scheduler connects a PUSH socket to the engine's PULL address and sends `session.transition` messages with a `to_state` field containing the target SessionState value.

### FR-SCHED-002: Wall-Clock Mode (Default)

In default mode, the scheduler reads the `schedule` section from the configuration file and sleeps until each configured wall-clock time, then sends the corresponding transition. Times that are already past (scheduler started late) are skipped.

Sleep is performed in 1-second increments to allow SIGINT interruption.

### FR-SCHED-003: Immediate Mode (`--now`)

When launched with `--now`, the scheduler sends all transitions in rapid succession with a configurable delay after each (default: 3.0 seconds via `--delay`). The sequence is:

```
PRE_OPEN → OPENING_AUCTION → CONTINUOUS → CLOSING_AUCTION → CLOSED
```

The delay is applied **after every transition, including the last one (CLOSED)**. The process sleeps `--delay` seconds after sending CLOSED before exiting cleanly. This ensures the engine has processed the final transition before any downstream processes act on it.

This mode is intended for testing and demonstrations.

### FR-SCHED-004: Default Schedule

If no configuration file is loaded or the `schedule` section is absent, defaults are used:

| Time | Transition |
|------|-----------|
| 09:00 | PRE_OPEN |
| 09:25 | OPENING_AUCTION |
| 09:30 | CONTINUOUS |
| 16:00 | CLOSING_AUCTION |
| 16:05 | CLOSED |

All times are HH:MM in the local timezone of the machine.

### FR-SCHED-005: Graceful Shutdown

On SIGINT/SIGTERM, the scheduler sets an internal `running` flag to false. The active 1-second sleep increment completes, then the outer per-transition loop exits cleanly without sending any further transitions — including the one that was being waited for when the signal arrived. The PUSH socket is closed before process exit.

### FR-SCHED-006: Socket Connection Warm-Up Delay

After creating the PUSH socket and before sending the first transition, the scheduler waits **100 milliseconds** (`time.sleep(0.1)`). This gives the ZMQ TCP connection time to complete the handshake with the engine's PULL socket so that the first message is not silently dropped.

This delay is applied in both wall-clock mode and `--now` mode.

### FR-SCHED-007: Canonical Schedule Ordering

Regardless of the order in which keys appear in the `schedule` YAML section, transitions are always evaluated and sent in the following canonical session sequence:

1. PRE_OPEN
2. OPENING_AUCTION
3. CONTINUOUS
4. CLOSING_AUCTION
5. CLOSED

YAML key order has no effect. A Rust implementation MUST sort (or iterate) loaded schedule entries in this canonical order before dispatching.

---

## 13. Configuration

### 13.1 Engine Configuration File

**File**: `engine_config.yaml` (path configurable via `--config` CLI argument)

**Format**:
```yaml
symbols:
  <SYMBOL>:
    last_buy_price:  <float>     # optional
    last_sell_price: <float>     # optional
    market_maker_orders:         # optional
      - "NEW|SYM=...|SIDE=...|TYPE=...|QTY=...|PRICE=...|TIF=..."

gateways:                        # required when config file is provided
  fix:
    - id: "GW01"
      description: "Primary trading desk"
    - id: "GW02"
      description: "Automated strategy"

schedule:                        # optional — omit for defaults
  pre_open:              "09:00"
  opening_auction_start: "09:25"
  continuous_start:      "09:30"
  closing_auction_start: "16:00"
  closing_auction_end:   "16:05"

market_maker_combos:             # optional
  - combo_id: "MM_PAIR_1"
    combo_type: "AON"
    tif: "GTC"
    legs:
      - symbol: "AAPL"
        side: "BUY"
        order_type: "LIMIT"
        quantity: 100
        price: 150.0
        smp_action: "NONE"
      - symbol: "MSFT"
        side: "SELL"
        order_type: "LIMIT"
        quantity: 50
        price: 300.0
```

**Rules**:
- Only symbols listed under `symbols:` are tradeable. All others are rejected.
- `last_buy_price` / `last_sell_price` seed initial values only when no persisted `book_stats.json` values exist.
- `market_maker_orders` are FIX-like strings injected at startup with gateway_id "MM".
- Market-maker order format is identical to gateway NEW commands.

### 13.2 Gateway Allowlist (`gateways.fix`)

- If an engine config file is provided, `gateways.fix` MUST be present and non-empty.
- Backward-compatible mode (all gateway IDs auto-accepted) occurs only when no config file is loaded at all.
- `gateways.fix` must be a list of mappings, each with a required `id` field and an optional `description`.
- Gateway IDs are case-insensitive (compared uppercase).
- Duplicate IDs in the config raise a validation error at load time.
- At least one entry is required.

### 13.3 Session Schedule (`schedule`)

- If the `schedule` section is **absent**: the scheduler uses built-in defaults (see FR-SCHED-004).
- All time values are in `HH:MM` format (24-hour local time).
- The mapping from config keys to session states:
  - `pre_open` → PRE_OPEN
  - `opening_auction_start` → OPENING_AUCTION
  - `continuous_start` → CONTINUOUS
  - `closing_auction_start` → CLOSING_AUCTION
  - `closing_auction_end` → CLOSED
- **Missing individual keys are omitted entirely** — if a key is absent from the YAML `schedule` block, that transition is simply never sent that day. There is no fallback to the built-in default for individual keys; defaults only apply when the entire `schedule` section is absent.
- YAML key ordering does not matter; transitions are always applied in canonical session order: PRE_OPEN → OPENING_AUCTION → CONTINUOUS → CLOSING_AUCTION → CLOSED (see FR-SCHED-007).

### 13.4 Market-Maker Combos (`market_maker_combos`)

- Optional list of combo order definitions injected at engine startup.
- Each entry requires: `combo_id` (non-empty string), `combo_type`, `tif`, `legs` (list of 2–10 leg mappings).
- Each leg requires: `symbol`, `side`, `order_type`, `quantity`, `price`.
- Symbols referenced in legs must exist in the `symbols` section.
- No duplicate symbols within a single combo.
- Injected with `gateway_id = "MM"` after single-leg MM orders.

### 13.5 Global Constants

| Constant | Default | Description |
|----------|---------|-------------|
| ENGINE_PULL_ADDR | tcp://127.0.0.1:5555 | Engine inbound socket |
| ENGINE_PUB_ADDR | tcp://127.0.0.1:5556 | Engine outbound socket |
| ORDERBOOK_DEPTH | 10 | Default viewer depth |
| CLEARING_PRINT_EVERY | 10 | Trades between P&L table prints |
| SNAPSHOT_INTERVAL | 0.5 s | Min time between book snapshot publishes |

---

## 14. Persistence

### 14.1 GTC Orders (`data/gtc_orders.json`)

- **Written**: on engine shutdown (SIGINT/SIGTERM)
- **Read**: on engine startup
- **Format**: JSON array of serialized Order objects (full `to_dict()` output)
- **Filter**: only orders with `tif=GTC` and `status` in {NEW, PARTIAL}
- **Behavior**: original timestamps are preserved so time priority carries over between sessions

### 14.2 Book Statistics (`data/book_stats.json`)

- **Written**: on engine shutdown
- **Read**: on engine startup
- **Format**: JSON object keyed by symbol:
  ```json
  {
    "AAPL": {"last_buy_price": 150.25, "last_sell_price": 149.80},
    "MSFT": {"last_buy_price": null, "last_sell_price": 415.50}
  }
  ```
- **Behavior**: persisted values override config-seeded values on restore

### 14.3 Audit Log (`data/audit.log`)

- Rotating file (10 MB, 5 backups)
- Written continuously by the audit process
- One JSON-line entry per event

### 14.4 Clearing Report (`data/clearing_report.csv`)

- Append-only CSV
- Written continuously by the clearing process
- Header written only on first creation

### 14.5 Statistics Database (`data/stats.db`)

- SQLite database
- Written continuously by the stats process
- Three tables: daily_stats, price_snapshots, trade_log

### 14.6 Data Directory

All persistence files reside in a `data/` directory relative to the project root. The directory is created automatically if it does not exist.

---

## 15. Non-Functional Requirements

### NFR-001: Language Independence

The messaging protocol uses JSON over ZMQ, enabling interoperability between processes written in different languages.

### NFR-002: Single Machine Deployment

All processes run on a single machine, communicating via TCP loopback (127.0.0.1). No network-level security is required for the educational scope.

### NFR-003: Process Independence

Each process is a standalone OS process with its own event loop. Processes can be started and stopped independently (respecting startup order for the engine).

### NFR-004: Graceful Degradation

- If the engine is not running, subscriber processes connect and wait; the gateway exits after authentication timeout (3 seconds).
- If a subscriber crashes and restarts, it reconnects and can request current state (book snapshot, orders).
- ZMQ's PUSH/PULL pattern provides automatic buffering if the engine is temporarily busy.

### NFR-005: Performance Characteristics

- Matching: O(log n) insertion, O(1) peek, O(k log k) for k fills
- FOK pre-check: O(p) where p = number of price levels
- Stop trigger: O(k log k) where k = triggered stops
- Cancel: O(1) lookup + O(1) invalidation (lazy heap deletion)
- Snapshot: O(n) where n = total resting orders (full heap scan for aggregation)

### NFR-006: Memory Model

- Each order book uses binary heaps with lazy deletion (stale entries consume memory until the book is compacted via natural pops).
- The engine maintains a global order_id → symbol map for O(1) cancel routing.
- Recent trades are bounded (deque with maxlen=20 per book).

### NFR-007: Clock Usage

- Order timestamps use `time.time()` (Unix epoch with sub-second precision).
- Throttle timers use `time.monotonic()` (not affected by clock adjustments).

### NFR-008: Shutdown Guarantees

- Engine persists all GTC orders before exit.
- All DAY orders are expired with notifications before exit.
- All subscribers receive EOD notification before the PUB socket closes.

### NFR-009: Terminal Display

- Use ANSI colour codes for terminal output (via a rich-text library or equivalent).
- Live-updating displays refresh at 2 Hz.
- Ticker scrolls at configurable intervals.

### NFR-010: Error Handling

- Malformed messages do not crash any process; they are logged and skipped.
- Individual handler errors in the engine are caught and logged; the engine continues.
- File I/O errors during persistence return empty defaults (graceful fallback).

### NFR-011: Scalability Boundaries

This is an educational system. Expected scale:
- 1-10 symbols
- 1-5 gateways
- 100s to low 1000s of orders per session
- No horizontal scaling; single-engine architecture

### NFR-012: UUID Generation

All IDs (order_id, trade_id) are UUID v4 strings, ensuring global uniqueness without coordination.

---

## 16. Implementation Plan

### Phase 1: Foundation (Messaging + Domain Model)

**Goal**: Establish the communication infrastructure and core data types.

1. **Define domain enums**: Side, OrderType, TIF, OrderStatus, SmpAction
2. **Define Order model**: all fields, factory method `create()`, serialization `to_dict()`/`from_dict()`
3. **Define Trade model**: all fields, factory, serialization
4. **Implement ZMQ bus**: context management, socket factories (make_puller, make_publisher, make_pusher, make_subscriber)
5. **Implement message helpers**: encode/decode, all `make_*_msg()` functions
6. **Define configuration constants**: addresses, file paths, defaults

**Deliverables**: Importable modules for models, messaging, config. Unit tests for serialization round-trips.

### Phase 2: Matching Engine Core

**Goal**: A working engine that can receive orders and match them.

1. **Implement OrderBook**: heap data structures, `_rest()`, `_peek()`, lazy deletion
2. **Implement LIMIT matching**: `_sweep()` with price-time priority, `_apply_fill()`
3. **Implement MARKET matching**: sweep with no price limit, discard remainder
4. **Implement price-level quantity index**: maintain on rest/fill/cancel
5. **Implement FOK**: `_available_qty()` pre-check + sweep
6. **Implement STOP/STOP_LIMIT**: separate heaps, trigger on trade, convert and re-process
7. **Implement ICEBERG**: displayed_qty tracking, peak replenishment, timestamp refresh
8. **Implement SMP**: gateway_id check in `_sweep()` and `_sweep_iceberg()`
9. **Implement cancel**: O(1) lookup, invalidation, qty index update
10. **Implement `snapshot()`**: aggregate by price level, honour iceberg privacy

**Deliverables**: Fully testable OrderBook class. Extensive unit tests.

### Phase 3: Engine Process

**Goal**: The engine runs as a standalone process.

1. **Implement Engine class**: socket binding, poll loop, message dispatch
2. **Implement handlers**: new order, cancel, symbols request, book snapshot request, orders request
3. **Implement snapshot throttling**: dirty set + per-symbol timestamp
4. **Implement shutdown**: SIGINT/SIGTERM handlers, DAY expiry, GTC persistence, EOD broadcast
5. **Implement GTC restore**: load from JSON, re-insert into books
6. **Implement config loader**: YAML parsing, validation, EngineConfig dataclass
7. **Implement startup sequence**: restore GTC → load config → seed stats → inject MM orders → publish snapshots
8. **Implement book stats persistence**: save/load last_buy_price, last_sell_price per symbol

**Deliverables**: Running engine process. Integration tests with mock gateways.

### Phase 4: Gateway

**Goal**: User-facing terminal for order entry.

1. **Implement command parser**: FIX-like string parsing, field extraction
2. **Implement input validation**: per-order-type field requirements
3. **Implement SUB listener thread**: event reception and display
4. **Implement order cache**: local state tracking, restore from engine on connect
5. **Implement ORDERS table display**
6. **Implement tab completion**: context-aware, type-dependent field suggestions
7. **Implement prompt with history**: interactive line editing
8. **Implement stdout patching**: clean interleaving of prompt and background output

**Deliverables**: Working interactive gateway. Manual testing with engine.

### Phase 5: Viewer + Order Monitor

**Goal**: Real-time market data display.

1. **Implement viewer**: subscribe, snapshot request, build display, live refresh
2. **Implement order monitor**: subscribe to `order.*`, accumulate state, live table

**Deliverables**: Visual verification of matching behavior.

### Phase 6: Back-Office Processes

**Goal**: Audit, clearing, statistics, ticker.

1. **Implement audit logger**: universal subscription, rotating file, error resilience
2. **Implement clearing process**: trade subscription, CSV append, P&L tracking, position logic
3. **Implement statistics process**: SQLite schema, daily_stats upsert, 15-min snapshots, trade_log, EOD handling
4. **Implement ticker process**: scrolling line output, DB queries, live book data

**Deliverables**: Full system operational.

### Phase 7: Session Management + Auctions

**Goal**: Trading session phases with auction mechanisms.

1. **Implement SessionState enum and transition map**
2. **Implement session.transition handler**: validate, update state, publish session.state
3. **Implement order acceptance by phase**: reject MARKET/FOK during auctions, enforce ATO/ATC rules
4. **Implement equilibrium price algorithm**: candidate prices, cumulative curves, tie-breaking
5. **Implement uncross execution**: execute at equilibrium price on phase exit
6. **Implement ATO/ATC expiry**: expire phase-specific orders after uncross
7. **Implement no-matching mode**: orders rest without triggering matching in auction phases

**Deliverables**: Session state machine, auction algorithm, phase-specific order handling. Unit tests for equilibrium price and phase transitions.

### Phase 8: Combo Orders

**Goal**: Multi-leg order management with cascade semantics.

1. **Implement ComboOrder and ComboLeg models**: serialization, validation
2. **Implement combo validation**: leg count, symbol uniqueness, field requirements
3. **Implement combo child order creation**: tag children with parent combo_id
4. **Implement fill tracking**: monitor child fills, detect MATCHED status
5. **Implement cascade cancel**: on child cancel/expire, cancel all siblings
6. **Implement combo cancel by user**: cancel all unfilled children
7. **Implement market_maker_combos config**: parse and inject at startup

**Deliverables**: Working combo lifecycle. Unit tests for validation, fill tracking, cascade.

### Phase 9: Gateway Authentication + Scheduler

**Goal**: Access control and automated session scheduling.

1. **Implement gateway allowlist in config**: parse gateways.fix section
2. **Implement gateway_connect handler**: accept/reject based on allowlist
3. **Implement connected-gateway check**: reject orders from unconnected gateways
4. **Implement scheduler process**: wall-clock mode, --now mode, config schedule loading
5. **Gateway auth flow**: send connect on startup, handle response, exit on rejection

**Deliverables**: End-to-end auth flow, scheduler driving session transitions.

### Phase 10: Orchestration + Polish

**Goal**: Easy launch and documentation.

1. **Create launch script**: opens all processes with proper timing
2. **Verify graceful shutdown**: all processes handle Ctrl-C cleanly
3. **End-to-end testing**: full system with multiple gateways, order types, SMP, combos, auctions

---

## 17. Test Specification

### 17.1 Unit Tests — Order Model

| ID | Test | Expected Result |
|----|------|-----------------|
| T-OM-001 | Create LIMIT BUY order | All fields set correctly, status=NEW, remaining=quantity |
| T-OM-002 | Create ICEBERG order | `displayed_qty = visible_qty`, `visible_qty` stored |
| T-OM-003 | to_dict() / from_dict() round-trip | All fields preserved including smp_action |
| T-OM-004 | SmpAction round-trip | `SmpAction.CANCEL_BOTH` survives serialization |
| T-OM-005 | Default values | `tif=DAY`, `smp_action=NONE`, nullable fields are None |

### 17.2 Unit Tests — Trade Model

| ID | Test | Expected Result |
|----|------|-----------------|
| T-TR-001 | Trade.create() | UUID generated, timestamp set, all fields correct |
| T-TR-002 | to_dict() / from_dict() round-trip | All 9 fields preserved |

### 17.3 Unit Tests — Message Encoding

| ID | Test | Expected Result |
|----|------|-----------------|
| T-MSG-001 | encode("topic", {"key": "val"}) | Returns [b"topic", b'{"key": "val"}'] |
| T-MSG-002 | decode round-trip | encode then decode returns original topic+payload |
| T-MSG-003 | make_ack_msg accepted | Topic = "order.ack.GW01", accepted=true in payload |
| T-MSG-004 | make_ack_msg rejected | Topic = "order.ack.GW01", accepted=false, reason present |
| T-MSG-005 | make_fill_msg | Correct topic, all fill fields present |
| T-MSG-006 | make_book_msg | Topic = "book.AAPL", snapshot dict in payload |
| T-MSG-007 | make_orders_request_msg | Topic = "order.orders_request" |
| T-MSG-008 | make_orders_msg | Topic = "order.orders.GW01", orders list in payload |

### 17.3A Unit Tests — OrderBook Data Structures

| ID | Test | Expected Result |
|----|------|-----------------|
| T-DS-001 | OrderBook creation | `_bids`, `_asks`, `_buy_stops`, `_sell_stops`, `_order_index`, `_entry_index`, `_bid_qty`, `_ask_qty`, `recent_trades` all initialized empty |
| T-DS-002 | Rest order → index updated | `_order_index[order_id]` → Order, `_entry_index[order_id]` → _HeapEntry |
| T-DS-003 | Rest order → qty index updated | `_bid_qty[price]` or `_ask_qty[price]` incremented by qty |
| T-DS-004 | Peek best bid | `_peek(_bids)` returns highest-priced entry without removing |
| T-DS-005 | Peek best ask | `_peek(_asks)` returns lowest-priced entry without removing |
| T-DS-006 | Cancel order → entry invalidated | Entry `valid=false` set; still in heap (lazy deletion) |
| T-DS-007 | Cancel order → indices cleaned | `_order_index` and `_entry_index` entries removed or marked |
| T-DS-008 | Cancel order → qty index updated | `_bid_qty[price]` or `_ask_qty[price]` decremented by qty |
| T-DS-009 | Fill order → remaining_qty decremented | Order state reflects executed qty; still in index until status=FILLED |
| T-DS-010 | Recent trades buffer | `recent_trades` deque stores trade objects, max 20 items |
| T-DS-011 | Add stop order → heap inserted | Stop entry added to `_buy_stops` or `_sell_stops` heap |
| T-DS-012 | Lazy deletion efficiency | Peak/pop skips invalid entries; O(1) cancellation (no heap rebuild) |
| T-DS-013 | FOK pre-check | `_available_qty(heap, price, side)` uses `_bid_qty` / `_ask_qty` index correctly |

### 17.4 Unit Tests — OrderBook LIMIT Matching

| ID | Test | Expected Result |
|----|------|-----------------|
| T-LIM-001 | Buy limit crosses existing ask | Trade at ask price, buyer status=FILLED or PARTIAL |
| T-LIM-002 | Sell limit crosses existing bid | Trade at bid price |
| T-LIM-003 | Buy limit below best ask | Order rests, no trade |
| T-LIM-004 | Partial fill | Aggressor remaining_qty decremented, status=PARTIAL |
| T-LIM-005 | Full fill of passive | Passive status=FILLED, entry invalidated |
| T-LIM-006 | Multiple fills in one sweep | 3 resting orders at improving prices, all filled in order |
| T-LIM-007 | Price-time priority | Two asks at same price — older one fills first |
| T-LIM-008 | Price improvement | Buy limit at 102, ask at 100 → trade at 100 (passive price) |

### 17.5 Unit Tests — OrderBook MARKET Matching

| ID | Test | Expected Result |
|----|------|-----------------|
| T-MKT-001 | Market buy fills entire ask side | All asks consumed, trades at each level's price |
| T-MKT-002 | Market buy with insufficient asks | Remainder discarded, status=CANCELLED (silent) |
| T-MKT-003 | Market sell | Fills against bids |
| T-MKT-004 | Market order never rests | After processing, order is not on any heap |

### 17.6 Unit Tests — OrderBook FOK

| ID | Test | Expected Result |
|----|------|-----------------|
| T-FOK-001 | FOK with sufficient liquidity | Fully filled |
| T-FOK-002 | FOK with insufficient liquidity | Status=REJECTED, no trades, no fills |
| T-FOK-003 | FOK exactly matching available | Fills completely |
| T-FOK-004 | FOK at better price | Fills at resting prices (price improvement) |

### 17.7 Unit Tests — OrderBook STOP / STOP_LIMIT

| ID | Test | Expected Result |
|----|------|-----------------|
| T-STP-001 | Buy stop placed, no trigger | Order in stop heap, not on book |
| T-STP-002 | Buy stop triggers on trade | Converts to MARKET, fills at available price |
| T-STP-003 | Sell stop triggers on trade | Converts to MARKET when price drops to stop |
| T-STP-004 | Stop-limit triggers | Converts to LIMIT with original limit price |
| T-STP-005 | Stop-limit trigger, no match | Rests on book as limit order |
| T-STP-006 | Cascade: trade triggers stop, stop triggers another stop | Both stops fire |
| T-STP-007 | Stop below current price (not triggered) | Remains dormant |
| T-STP-008 | Stop-Limit trigger preserves time order | Timestamp updated to trigger time, order goes to back of queue at price |  

### 17.8 Unit Tests — OrderBook ICEBERG

| ID | Test | Expected Result |
|----|------|-----------------|
| T-ICE-001 | Iceberg rests with displayed_qty only | Snapshot shows visible_qty, not full |
| T-ICE-002 | Partial fill of displayed slice | displayed_qty decremented |
| T-ICE-003 | Full displayed slice consumed | displayed_qty replenished to min(visible_qty, remaining) |
| T-ICE-004 | Timestamp refresh on replenishment | Order goes to back of queue at same price |
| T-ICE-005 | Final fill | When remaining=0, status=FILLED, no replenishment |
| T-ICE-006 | Aggressor iceberg | Fills against opposite side, replenishes and continues |
| T-ICE-007 | Iceberg visible_qty in snapshot | Only displayed_qty visible per level |

### 17.9 Unit Tests — Self Match Prevention

| ID | Test | Expected Result |
|----|------|-----------------|
| T-SMP-001 | NONE: same gateway trades allowed | Trade executes normally |
| T-SMP-002 | CANCEL_AGGRESSOR: same gateway | Aggressor cancelled, resting untouched, no trade |
| T-SMP-003 | CANCEL_RESTING: same gateway | Resting cancelled, matching continues with next level |
| T-SMP-004 | CANCEL_BOTH: same gateway | Both cancelled, no trade |
| T-SMP-005 | Different gateway_ids | SMP not triggered, trade executes |
| T-SMP-006 | SMP on iceberg sweep | Same behavior as regular sweep |
| T-SMP-007 | CANCEL_RESTING skips one, fills next | First resting cancelled, second resting fills |

### 17.10 Unit Tests — Cancel

| ID | Test | Expected Result |
|----|------|-----------------|
| T-CAN-001 | Cancel resting limit | Status=CANCELLED, entry invalidated, qty index updated |
| T-CAN-002 | Cancel stop order | Status=CANCELLED |
| T-CAN-003 | Cancel already-filled order | Returns None (not cancellable) |
| T-CAN-004 | Cancel non-existent ID | Returns None |
| T-CAN-005 | Cancel iceberg | Full remaining hidden qty removed |

### 17.11 Unit Tests — Persistence

| ID | Test | Expected Result |
|----|------|-----------------|
| T-PER-001 | save_gtc_orders filters by TIF/status | Only GTC + NEW/PARTIAL saved |
| T-PER-002 | load_gtc_orders round-trip | Orders restored with original timestamps |
| T-PER-003 | load_gtc_orders missing file | Returns empty list |
| T-PER-004 | load_gtc_orders corrupt file | Returns empty list |
| T-PER-005 | save_book_stats | All symbols with buy/sell prices written |
| T-PER-006 | load_book_stats round-trip | Prices restored |
| T-PER-007 | load_book_stats missing file | Returns empty dict |
| T-PER-008 | save_gtc_combos filters by TIF/status | Only GTC + PENDING/PARTIALLY_MATCHED combos saved; MATCHED/FAILED/CANCELLED/REJECTED excluded |
| T-PER-009 | save_gtc_combos structure | All combo fields persisted: id, combo_id, legs, child_order_ids, leg_fill_qty, leg_statuses |
| T-PER-010 | load_gtc_combos round-trip | Combos restored with status and fill tracking intact |
| T-PER-011 | load_gtc_combos missing file | Returns empty list |
| T-PER-012 | load_gtc_combos corrupt file | Returns empty list |
| T-PER-013 | GTC combo + child order restore sequence | Single-leg orders restored first; then combos; child orders re-linked via _order_to_combo |
| T-PER-014 | GTC combo child backlinks | Restored child orders have `combo_parent_id` and `leg_index` set correctly |
| T-PER-015 | Combo parent lookup after restore | `_combos[combo.id]` and `_order_to_combo[child_id]` both populated correctly |

### 17.12 Unit Tests — Config Loader

| ID | Test | Expected Result |
|----|------|-----------------|
| T-CFG-001 | Valid config parses | EngineConfig with correct symbols, prices, MM orders |
| T-CFG-002 | Missing file | FileNotFoundError raised |
| T-CFG-003 | Invalid YAML structure | ValueError raised |
| T-CFG-004 | Invalid market_maker_orders entry | ValueError raised |
| T-CFG-005 | allowed_symbols property | Returns frozenset of symbol names |
| T-CFG-006 | Symbol names uppercased | "aapl" → "AAPL" |

### 17.12A Unit Tests — Engine Class Architecture

| ID | Test | Expected Result |
|----|------|-----------------|
| T-ENG-DS-001 | Engine startup | `books={}`, `_order_symbol={}`, `_combos={}`, all tracking structures initialized |
| T-ENG-DS-002 | Book creation on demand | First order for symbol creates OrderBook lazily; subsequent orders use same instance |
| T-ENG-DS-003 | Order symbol index | `_order_symbol[order_id] = symbol` populated on acceptance |
| T-ENG-DS-004 | Cancel routing | Cancel request uses `_order_symbol[order_id]` for O(1) symbol lookup |
| T-ENG-DS-005 | Combo order creation | `_combos[combo.id]` created; child orders added to `_order_to_combo` |
| T-ENG-DS-006 | Combo child cascade | Parent lookup via `_order_to_combo[child_id]` enables fast sibling access |
| T-ENG-DS-007 | Dirty symbols tracking | Book changes add symbol to `_dirty_symbols` |
| T-ENG-DS-008 | Snapshot throttle | `_last_snapshot[symbol]` used to enforce SNAPSHOT_INTERVAL |
| T-ENG-DS-009 | Gateway auth tracking | `_connected_fix_gateways` updated on successful `system.gateway_connect` |
| T-ENG-DS-010 | Symbol allowlist | `_allowed_symbols=None` disables restrictions; non-None frozenset enforces |
| T-ENG-DS-011 | Session state storage | `_session_state` updated on valid transitions |
| T-ENG-DS-012 | Order symbol cleanup | Entry removed from `_order_symbol` when order reaches terminal status |

### 17.12B Unit Tests — Engine Matching Pipeline

| ID | Test | Expected Result |
|----|------|-----------------|
| T-PIPE-001 | New order validation → book routing → process | ACK published immediately; fills/trades after processing |
| T-PIPE-002 | Cancel order → symbol lookup → cancel → publish | Uses `_order_symbol` for O(1) routing |
| T-PIPE-003 | Stop cascade → check stops after trade | Triggered stops re-processed; may generate additional trades |
| T-PIPE-004 | Combo child → parent tracking → cascade | Failed leg looks up parent via `_order_to_combo` and cancels siblings |
| T-PIPE-005 | Multiple trades in one order | All trades published in same order submission batch |
| T-PIPE-006 | Combo leg fills → parent status update | Parent status transitions (PENDING → PARTIALLY_MATCHED → MATCHED) |
| T-PIPE-007 | Combo leg cancel → cascade-cancel siblings | All non-terminal siblings cancelled and published |
| T-PIPE-008 | Dirty symbol accumulation | Multiple changes mark symbol dirty once; snapshot publishes when throttle elapses |
| T-PIPE-009 | Session phase enforcement | PRE_OPEN rejects MARKET/FOK; OPENING_AUCTION rejects MARKET; CONTINUOUS allows all |
| T-PIPE-010 | Throttle snapshot window | Symbol dirty; no snapshot until SNAPSHOT_INTERVAL (0.5s) elapsed since last publish |
| T-PIPE-011 | Message ordering | ACK before FILL before TRADE within same order submission |
| T-PIPE-012 | Auth rejection | Unauthenticated gateway order rejected before symbol validation |

### 17.13 Integration Tests — Engine + Gateway

| ID | Test | Expected Result |
|----|------|-----------------|
| T-INT-001 | Submit LIMIT, receive ACK | Gateway receives ack within 500 ms |
| T-INT-002 | Submit crossing orders, receive fills | Both gateways receive fill notifications |
| T-INT-003 | Cancel resting order | Gateway receives cancelled confirmation |
| T-INT-004 | Reject for unknown symbol | Gateway receives rejection with reason |
| T-INT-005 | GTC persist + restore | Shutdown engine, restart, order still on book |
| T-INT-006 | SYMBOLS command | Returns list of active symbols |
| T-INT-007 | ORDERS command on reconnect | Resting orders populated from engine |
| T-INT-008 | Book snapshot on viewer connect | Viewer receives snapshot within 500 ms |
| T-INT-009 | SMP across same gateway | Appropriate cancel events received |
| T-INT-010 | Market-maker orders in book | Viewer shows MM orders after engine startup |

### 17.14 Integration Tests — Full System

| ID | Test | Expected Result |
|----|------|-----------------|
| T-SYS-001 | Full trade lifecycle | Order → ACK → Fill → Trade → Book update → Clearing CSV → Audit log |
| T-SYS-002 | Stop trigger cascade | Place stop, trigger it via limit cross, verify conversions |
| T-SYS-003 | Iceberg fills across multiple participants | Multiple traders fill slices, iceberg replenishes |
| T-SYS-004 | Engine shutdown EOD | All DAY orders expired, GTC saved, EOD published |
| T-SYS-005 | Stats captures OHLCV | After trades, verify daily_stats table has correct values |
| T-SYS-006 | Clearing P&L accuracy | Two opposing fills → verify realized_pnl calculation |
| T-SYS-007 | Audit completeness | Every engine-published event appears in audit.log |
| T-SYS-008 | Concurrent gateway orders | Two gateways submit simultaneously, matching is correct |
| T-SYS-009 | FOK rejection | Submit FOK without liquidity, verify REJECTED, no fills |
| T-SYS-010 | Config change: remove symbol | Restart engine, old GTC for removed symbol skipped |

### 17.15 Stress / Edge Case Tests

| ID | Test | Expected Result |
|----|------|-----------------|
| T-EDGE-001 | Order with qty=1 | Fills correctly |
| T-EDGE-002 | Price of 0.0001 (very small) | Handles floating-point correctly |
| T-EDGE-003 | Large quantity (1,000,000) | No overflow |
| T-EDGE-004 | Same price, 100 orders | Time priority maintained for all 100 |
| T-EDGE-005 | Cancel during sweep | Cancelled resting order skipped by peek |
| T-EDGE-006 | Multiple FOK at same time | Each evaluated independently |
| T-EDGE-007 | Iceberg visible_qty = 1 | Replenishes 1 at a time |
| T-EDGE-008 | Empty book + market order | No trade, order discarded |
| T-EDGE-009 | GTC restore with 0 remaining | Not loaded (status would be FILLED) |
| T-EDGE-010 | Malformed JSON on PULL socket | Engine logs error, continues |

### 17.16 Unit Tests — Combo Orders

| ID | Test | Expected Result |
|----|------|-----------------|
| T-CMB-001 | Valid 2-leg combo accepted | combo.ack accepted=true, child orders on books |
| T-CMB-002 | Combo with 1 leg rejected | Reason: "Combo requires at least 2 legs" |
| T-CMB-003 | Combo with 11 legs rejected | Reason: "Combo supports at most 10 legs" |
| T-CMB-004 | Duplicate symbols in legs rejected | Reason: "Duplicate symbols in combo legs" |
| T-CMB-005 | Unknown symbol in leg rejected | Reason: "Symbol not configured: XYZ" |
| T-CMB-006 | All legs fill → MATCHED | combo.status with status=MATCHED |
| T-CMB-007 | One leg cancelled → cascade cancel | All other legs cancelled, status=FAILED |
| T-CMB-008 | User cancel combo | All children cancelled, status=CANCELLED |
| T-CMB-009 | Partial fill → PARTIALLY_MATCHED | Status transition on first leg fill |
| T-CMB-010 | Fills not reversed on cascade | Already-executed fills remain settled |
| T-CMB-011 | Cancel already-terminal combo | Rejection: "Combo already {STATUS}" |
| T-CMB-012 | Combo during auction phase | Children rest without matching, uncross normally |
| T-CMB-013 | Combo with mixed order types | Legs with LIMIT, MARKET, ICEBERG all process correctly; MARKET fills immediately if liquidity exists |
| T-CMB-014 | combo.ack accepted payload shape | `accepted=true` includes `combo` object with `child_order_ids=[]` at ACK time; no top-level `child_order_ids` field |
| T-CMB-015 | combo.status FAILED payload shape | `status=FAILED` includes `details.reason` (not top-level `reason`) |

### 17.16A Unit Tests — Combo Order Data Structures and Lifecycle

| ID | Test | Expected Result |
|----|------|-----------------|
| T-CMB-DS-001 | ComboOrder creation | `id` (UUID), `combo_id` (user label), `gateway_id`, `status=PENDING`, `child_order_ids=[]`, `leg_fill_qty={}`, `leg_statuses={}` all initialized |
| T-CMB-DS-002 | Child order backlinks | Each child has `combo_parent_id=parent.id` and `leg_index` set correctly |
| T-CMB-DS-003 | Engine._order_to_combo | `_order_to_combo[child_id] = parent.id` populated for all legs |
| T-CMB-DS-004 | Engine._combos registry | `_combos[parent.id] = parent` tracks all active combos |
| T-CMB-DS-005 | is_fully_filled property | Returns true only when all legs have status FILLED |
| T-CMB-DS-006 | leg_fill_qty tracking | `leg_fill_qty[i]` incremented on each fill event; reflects cumulative qty |
| T-CMB-DS-007 | leg_statuses tracking | `leg_statuses[i]` updated to match child Order.status after each event |
| T-CMB-DS-008 | State: PENDING → PARTIALLY_MATCHED | Transition when `leg_fill_qty[any_leg] > 0` after first fill |
| T-CMB-DS-009 | State: PARTIALLY_MATCHED → MATCHED | Transition when `is_fully_filled` property true |
| T-CMB-DS-010 | State: any non-terminal → FAILED | Transition when any child transitions to CANCELLED/EXPIRED before combo fills |
| T-CMB-DS-011 | State: non-terminal → CANCELLED | Transition when user sends `order.combo_cancel` |
| T-CMB-DS-012 | State: REJECTED is terminal | No transitions from REJECTED; combo never posted to books |
| T-CMB-DS-013 | Cascade-cancel sibling lookup | Failed leg looks up parent via `_order_to_combo[leg.id]`, finds all siblings |
| T-CMB-DS-014 | Cascade-cancel filtering | Only siblings with `leg_statuses[i]` NOT in (FILLED, CANCELLED, EXPIRED, REJECTED) are cancelled |
| T-CMB-DS-015 | Cascade-cancel preserves fills | Already-FILLED legs are not cancelled; trades remain settled |
| T-CMB-DS-016 | Terminal state invariant | Once in MATCHED/FAILED/CANCELLED/REJECTED, no further state transitions |
| T-CMB-DS-017 | Child order serial numbering | `leg_index` reflects position in `combo.legs` array (0-based) |

### 17.17 Unit Tests — Auctions / Session State

| ID | Test | Expected Result |
|----|------|-----------------|
| T-AUC-001 | Equilibrium price maximizes quantity | Correct price selected from candidates |
| T-AUC-002 | Tie-breaking: minimum surplus | Among equal exec_qty, lower surplus wins |
| T-AUC-003 | Tie-breaking: lowest price | Among equal surplus, lowest price wins |
| T-AUC-004 | No crossable interest → no uncross | eq_price=null, eq_qty=0 |
| T-AUC-005 | ATO accepted during OPENING_AUCTION | Order rests on book |
| T-AUC-006 | ATO rejected during CONTINUOUS | Rejection with reason |
| T-AUC-007 | ATO expired on auction exit | order.expired published after uncross |
| T-AUC-008 | ATC accepted during CLOSING_AUCTION | Order rests on book |
| T-AUC-009 | ATC rejected during OPENING_AUCTION | Rejection with reason |
| T-AUC-010 | MARKET rejected during auction phase | Rejection: order type not allowed |
| T-AUC-011 | FOK rejected during auction phase | Rejection: order type not allowed |
| T-AUC-012 | All orders rejected during CLOSED | Rejection: session closed |
| T-AUC-013 | Valid transition CONTINUOUS→CLOSING_AUCTION | session.state published |
| T-AUC-014 | Invalid transition PRE_OPEN→CLOSED | Silently rejected, state unchanged |
| T-AUC-015 | Uncross executes at equilibrium price | All fills at single price |
| T-AUC-016 | Orders rest without matching during auction | No trades until uncross |
| T-AUC-017 | Uncross allocation on surplus side | 200 BUY @$100 vs 100 SELL @$100 → only first 100 BUYs (by time) execute, rest stay resting |

### 17.18 Unit Tests — Gateway Authentication

| ID | Test | Expected Result |
|----|------|-----------------|
| T-AUTH-001 | Valid gateway ID (in allowlist) | accepted=true, description returned |
| T-AUTH-002 | Invalid gateway ID (not in allowlist) | accepted=false, reason="Gateway not configured" |
| T-AUTH-003 | Order from unconnected gateway | Rejected with reason |
| T-AUTH-004 | No engine config file (backward compat) | All gateways auto-accepted |
| T-AUTH-005 | Duplicate gateway IDs in config | Validation error at load time |

### 17.19 Integration Tests — Combo + Auction + Auth

| ID | Test | Expected Result |
|----|------|-----------------|
| T-INT-020 | Combo submitted, all legs fill | combo.status MATCHED, fills for both legs |
| T-INT-021 | Scheduler drives full session lifecycle | PRE_OPEN→...→CLOSED, auction results published |
| T-INT-022 | Gateway rejected by auth | Gateway exits, no orders processed |
| T-INT-023 | Combo during auction → uncross fills legs | Combo transitions to MATCHED after uncross |
| T-INT-024 | MM combo injected at startup | Child orders visible in book snapshots |
| T-INT-025 | Iceberg cascade cancel via SMP | Iceberg resting order SMP-cancelled → all hidden qty removed, not replenished |
| T-INT-026 | Stop-Limit trigger during auction | Stop fires, converts to LIMIT with new timestamp, rests; uncross may fill it later |
| T-INT-027 | GTC combo restored across restart | Combo with child orders restored from disk, child-parent links re-established, children re-posted to books |

### 17.20 Unit Tests — Session Scheduler

| ID | Test | Expected Result |
|----|------|-----------------|
| T-SCHED-001 | Wall-clock mode: past time skipped | Transition with already-elapsed HH:MM is not sent; log prints "already past, skipping" |
| T-SCHED-002 | Wall-clock mode: future time sends | Waits until target time, then sends `session.transition` with correct `to_state` |
| T-SCHED-003 | Wall-clock mode: SIGINT during wait | `running` flag cleared; current pending transition NOT sent; loop exits cleanly |
| T-SCHED-004 | `--now` mode: all 5 transitions sent | Sends PRE_OPEN, OPENING_AUCTION, CONTINUOUS, CLOSING_AUCTION, CLOSED in order |
| T-SCHED-005 | `--now` mode: delay after every transition | `time.sleep(delay)` called after each of the 5 transitions, including after CLOSED |
| T-SCHED-006 | `--now` mode: `--delay` overrides default | Passing `--delay 1.0` results in 1.0s sleeps between transitions |
| T-SCHED-007 | Schedule loaded from YAML | Custom times from `schedule:` block used instead of defaults |
| T-SCHED-008 | Schedule loaded: missing key omitted | YAML with no `closing_auction_start` → CLOSING_AUCTION transition never sent (no fallback to default) |
| T-SCHED-009 | Schedule loaded: absent section → defaults | No `schedule:` block in YAML → full default schedule used |
| T-SCHED-010 | Schedule loaded: YAML key order irrelevant | Keys in any order still produce transitions in canonical sequence (PRE_OPEN first, CLOSED last) |
| T-SCHED-011 | Socket warm-up delay applied | 100ms sleep after socket creation, before first `send_multipart` call |
| T-SCHED-012 | Default schedule values | Default times match: 09:00 PRE_OPEN, 09:25 OPENING_AUCTION, 09:30 CONTINUOUS, 16:00 CLOSING_AUCTION, 16:05 CLOSED |
| T-SCHED-013 | Corrupt YAML → fallback to defaults | Malformed config file logs a warning and uses built-in default schedule |

### 17.21 Unit Tests — SessionState Predicates

| ID | Test | Expected Result |
|----|------|-----------------|
| T-SESS-001 | `is_matching_enabled(CONTINUOUS)` | Returns true |
| T-SESS-002 | `is_matching_enabled` for non-CONTINUOUS | Returns false for PRE_OPEN, OPENING_AUCTION, CLOSING_AUCTION, CLOSED |
| T-SESS-003 | `is_auction_phase(OPENING_AUCTION)` | Returns true |
| T-SESS-004 | `is_auction_phase(CLOSING_AUCTION)` | Returns true |
| T-SESS-005 | `is_auction_phase` for non-auction | Returns false for PRE_OPEN, CONTINUOUS, CLOSED |
| T-SESS-006 | `accepts_orders(CLOSED)` | Returns false |
| T-SESS-007 | `accepts_orders` for all non-CLOSED | Returns true for PRE_OPEN, OPENING_AUCTION, CONTINUOUS, CLOSING_AUCTION |
| T-SESS-008 | VALID_TRANSITIONS completeness | All 5 states have entries; no state is unreachable in the forward direction |
| T-SESS-009 | Invalid transition PRE_OPEN→CLOSED | Not in VALID_TRANSITIONS; engine silently rejects, logs warning |
| T-SESS-010 | CLOSED→PRE_OPEN valid (next day) | Is in VALID_TRANSITIONS; engine accepts and publishes `session.state` |

---

## 18. Post-v2 Requirements Addendum

This section captures major functionality implemented after version 2.0.
Where this section conflicts with earlier text, this section takes precedence.

### 18.1 Messaging Extensions

The following topics are implemented and form part of the protocol:

- `quote.new` (Gateway -> Engine): submit or replace a two-sided MM quote.
- `quote.cancel` (Gateway -> Engine): cancel active quote for one symbol.
- `quote.ack.{GW_ID}` (Engine -> Gateway): quote accept/reject response.
- `quote.status.{GW_ID}` (Engine -> Gateway): quote lifecycle status.
- `risk.kill_switch` (Gateway -> Engine): emergency cancel by gateway, optional symbol scope.
- `risk.kill_switch_ack.{GW_ID}` (Engine -> Gateway): kill-switch result summary with cancellation counts.
- `circuit_breaker.halt.{SYMBOL}` (Engine -> All): symbol halt event with trigger/reference details and level.
- `circuit_breaker.resume.{SYMBOL}` (Engine -> All): symbol resume event.
- `depth.{SYMBOL}` (Engine -> All): tolerance-window depth metrics published with snapshot flushes.
- `drop_copy.event.{GW_ID}` (Engine -> Drop-copy subscribers): sequenced per-gateway event stream on dedicated drop-copy PUB socket.
- `drop_copy.replay.{RECIPIENT_ID}` (Engine -> Drop-copy subscribers): replay stream from buffered sequence.

### 18.2 Tick/Nanosecond Canonical Model

FR-CORE-001: Internal canonical price representation

- The engine SHALL use integer ticks for all matching-critical prices (`order.price`, `order.stop_price`, `trade.price`, book indices, collar/circuit-breaker checks).
- Decimal display prices SHALL be converted to ticks at ingress boundaries and converted back to decimal at egress boundaries.

FR-CORE-002: Per-symbol tick precision

- `tick_decimals` SHALL be configurable per symbol.
- Supported range is 0..8.
- Default is 2 when not configured.

FR-CORE-003: Canonical timestamp representation

- The engine SHALL use integer nanosecond timestamps for ordering-critical state.
- `now_ns()` SHALL be strictly monotonic within process lifetime (if wall-clock regresses or ties, increment by 1 ns).

FR-CORE-004: External timestamp compatibility

- External JSON payloads may expose seconds as decimal for backward compatibility (for example in selected publication paths), but internal state and comparisons SHALL remain integer nanoseconds.

### 18.3 Risk Controls: Collar + Circuit Breaker

#### FR-RISK-001: Collar checks

- A collar SHALL reject limit-priced orders outside static and dynamic bands.
- Static band is anchored to symbol reference price.
- Dynamic band is anchored to last trade price when available.
- MARKET/FOK/IOC SHALL bypass collar checks.

#### FR-RISK-002: Collar level profiles

- `risk_controls.levels` SHALL define reusable collar profiles.
- `risk_controls.default_level` SHALL apply when symbol `level` is absent.
- Resolution precedence for collars SHALL be:
  1. `symbols.<SYM>.collar`
  2. `symbols.<SYM>.level` profile
  3. `risk_controls.default_level` profile
  4. built-in collar defaults

#### FR-RISK-003: Circuit breaker ladder model

- Circuit breakers SHALL be configured as threshold ladders (`levels`) keyed by level name.
- Each level SHALL define:
  - `price_shift_pct` in (0,1)
  - `halt_duration_ns` (positive integer or null for rest-of-day)
  - `resumption_mode` in {AUCTION, CONTINUOUS}
- Trigger selection SHALL use the highest crossed threshold based on absolute shift from rolling reference.

#### FR-RISK-004: Circuit breaker defaults and overrides

- Global defaults SHALL be configured under top-level `circuit_breaker_defaults`.
- Per-symbol overrides SHALL be configured under `symbols.<SYM>.circuit_breaker`.
- Resolution precedence SHALL be:
  1. symbol circuit-breaker override
  2. global `circuit_breaker_defaults`
  3. built-in defaults
- Built-in defaults are:
  - L1: 7% shift, 5 minutes
  - L2: 13% shift, 15 minutes
  - L3: 20% shift, rest-of-day

#### FR-RISK-005: Deprecated placement rejection

- `risk_controls.levels.<LEVEL>.circuit_breaker` SHALL be rejected at config load with a clear error directing operators to top-level `circuit_breaker_defaults`.

#### FR-RISK-006: Halt behavior

- On breaker halt, the engine SHALL:
  1. mark symbol halted,
  2. cancel all active MM quote entries for that symbol,
  3. publish `circuit_breaker.halt.{SYMBOL}` with trigger/reference/level data.
- While halted:
  - MARKET/FOK/IOC SHALL be rejected.
  - LIMIT/ICEBERG MAY rest but SHALL NOT match.
  - `quote.new` SHALL be rejected.

#### FR-RISK-007: Resume behavior

- Timed levels SHALL auto-resume when `halt_duration_ns` elapses.
- For `resumption_mode = AUCTION`, symbol-level uncross SHALL run before resume publish.
- For null duration levels (rest-of-day), auto-resume SHALL NOT occur.
- On session transition to CLOSED, any still-halted symbols SHALL be force-reset to non-halted.

### 18.4 Market-Maker Quotes

#### FR-MMQ-001: Quote submission model

- A quote SHALL be represented by two linked limit orders (bid/ask) with shared `quote_id`.
- `quote.new` for the same `(gateway_id, symbol)` SHALL replace prior active quote by cancelling prior quote legs.

#### FR-MMQ-002: Access control

- Only gateways with role `MARKET_MAKER` SHALL be allowed to submit quotes.

#### FR-MMQ-003: Validation

- `bid_qty` and `ask_qty` SHALL be positive.
- `bid_price` SHALL be strictly less than `ask_price`.
- Symbol allowlist and gateway connectivity/auth rules SHALL apply.

#### FR-MMQ-004: Quote lifecycle publication

- Engine SHALL publish `quote.ack.{GW_ID}` for accept/reject.
- Engine SHALL publish `quote.status.{GW_ID}` transitions (`ACTIVE`, `CANCELLED`, inactive-on-fill states).

#### FR-MMQ-005: Quote refresh policy

- `quote_refresh_policy` SHALL support:
  - `INACTIVATE_ON_ANY_FILL`
  - `INACTIVATE_ON_FULL_FILL`
  - `NEVER_INACTIVATE`
- When policy requires inactivation, sibling quote leg SHALL be cancelled and quote removed from active index.

#### FR-MMQ-006: Disconnect behavior

- Participant disconnect handling SHALL support:
  - `LEAVE_ALL`: no automatic cancellations.
  - `CANCEL_QUOTES_ONLY`: cancel active quotes only.
  - `CANCEL_ALL`: cancel active quotes and all resting non-quote orders for participant.

### 18.5 MM Obligation and MMP-Related Policy

#### FR-MMO-001: Enforced quote obligation checks

- When MM obligation enforcement is active for a participant/symbol, quote acceptance SHALL enforce:
  - maximum spread in ticks,
  - minimum bid/ask quantity.

#### FR-MMO-002: Configuration fields

- Global defaults: `mm_obligation_defaults` with `enforce_mm_obligation`, `mm_max_spread_ticks`, `mm_min_qty`, and optional per-symbol overrides under `mm_obligation_defaults.symbols`.
- Gateway defaults: `gateways.fix[].enforce_mm_obligation`, `mm_max_spread_ticks`, `mm_min_qty`.
- Gateway symbol overrides: `gateways.fix[].mm_obligations.<SYM>` with `enforce_mm_obligation`, `max_spread_ticks`, `min_qty`.

#### FR-MMO-003: Specificity precedence

- Effective MM obligation policy SHALL resolve as:
  1. gateway+symbol override
  2. global symbol override
  3. gateway-level defaults
  4. global defaults

#### FR-MMO-004: MMP model availability

- Data models SHALL include MMP state primitives (`mmp_fill_count`, `mmp_window_ns`, `max_requote_delay_ns`, activation/reset state), enabling future engine-side MMP trigger workflow.

### 18.6 Kill Switch

#### FR-KILL-001: Kill-switch action

- `risk.kill_switch` SHALL cancel open risk-bearing exposure for the requesting gateway.
- With symbol specified, scope SHALL be single symbol.
- Without symbol, scope SHALL be all symbols.

#### FR-KILL-002: Cancel scope

- Kill switch SHALL cancel:
  - active MM quote entries and their legs,
  - resting non-quote orders belonging to the gateway.

#### FR-KILL-003: Acknowledgement

- Engine SHALL publish `risk.kill_switch_ack.{GW_ID}` containing:
  - `accepted`
  - `reason`
  - `cancelled_orders`
  - `cancelled_quotes`

### 18.7 Additional Market Data and Backoffice Streams

#### FR-MD-001: Depth metrics stream

- Engine SHALL compute and publish `depth.{SYMBOL}` metrics alongside throttled book snapshot flushes.
- Metrics SHALL be anchored to last trade and include:
  - `mid_price_ticks`
  - `tolerance_ticks`
  - `bid_depth`
  - `ask_depth`
  - `imbalance`
  - `cost_to_move`
- If no last trade exists, no depth payload SHALL be published for the symbol.

#### FR-OPS-001: Drop-copy socket

- Engine SHALL bind a dedicated drop-copy PUB socket (default `tcp://127.0.0.1:5557`).
- Drop-copy publishes SHALL include sequence and nanosecond timestamp.
- Engine SHALL maintain a bounded replay buffer (default 10,000 events) and support replay by sequence lower bound.

#### FR-OPS-002: Drop-copy payloads

- For fill drop-copy events, payload SHALL include at least: order identifier, symbol, fill quantity, fill price, remaining quantity, and liquidity flag.

### 18.8 Configuration Additions and Rules

#### FR-CFG-018-001: Symbol config additions

- `tick_decimals` per symbol.
- `level` per symbol for collar profile selection.
- `collar` per-symbol overrides.
- `circuit_breaker` per-symbol ladder overrides.
- `market_maker_quotes` seed entries.

#### FR-CFG-018-002: Top-level additions

- `risk_controls` (collar levels only)
- `circuit_breaker_defaults`
- `mm_obligation_defaults`
- `sessions_enabled`

#### FR-CFG-018-003: MM gateway validation rule

- If any MARKET_MAKER gateway is configured, each configured symbol SHALL include at least one `market_maker_quotes` entry.

### 18.9 Persistence Additions

#### FR-PER-018-001: Tick/ns persistence model

- Persisted order/trade/book-stat values SHALL preserve integer tick and integer nanosecond semantics in core files and runtime state.

#### FR-PER-018-002: Drop-copy replay buffer

- Drop-copy replay storage is in-memory bounded buffer; it is not durable across engine restarts.

### 18.10 Non-Functional Additions

#### NFR-013: Deterministic arithmetic

- Matching-critical price math SHALL avoid floating-point drift by using integer ticks.

#### NFR-014: Time ordering robustness

- Event ordering SHALL be resilient to wall-clock ties/regressions via strictly monotonic nanosecond clock helper.

#### NFR-015: Segregated operational feed

- Drop-copy SHALL be isolated from market data transport to reduce subscriber coupling and support participant-specific operational monitoring.

### 18.11 Test Addendum

The implementation includes dedicated coverage for these new areas. A conforming reimplementation SHALL include equivalent tests for:

- Circuit-breaker ladder trigger selection, timed and rest-of-day halts, and activation/resume transitions.
- Halted-symbol behavior for order acceptance/matching suppression and quote rejection.
- Collar static/dynamic rejection behavior.
- MM quote workflow: role gating, replace/cancel flow, disconnect behavior, and refresh-policy transitions.
- MM obligation enforcement toggles and specificity precedence resolution.
- Kill-switch scoped/global cancellation and acknowledgement counts.
- Depth metrics payload shape and windowed depth math.
- Drop-copy publish sequencing and replay semantics.

---

## Appendix A: FIX-Like Command Syntax

### Single-Leg Orders

```
NEW|SYM=<SYMBOL>|SIDE=<BUY|SELL>|TYPE=<MARKET|LIMIT|STOP|STOP_LIMIT|FOK|ICEBERG>|QTY=<integer>[|PRICE=<float>][|STOP=<float>][|TIF=<DAY|GTC|ATO|ATC>][|VISIBLE=<integer>][|SMP=<NONE|CANCEL_AGGRESSOR|CANCEL_RESTING|CANCEL_BOTH>]

CANCEL|ID=<uuid-string>
```

Field defaults:
- TIF: DAY
- SMP: NONE

### Combo Orders

```
NEW|TYPE=COMBO|COMBO_ID=<label>|COMBO_TYPE=AON[|TIF=<DAY|GTC>][|LEG_COUNT=<n>]|LEG0.SYM=<SYMBOL>|LEG0.SIDE=<BUY|SELL>|LEG0.QTY=<integer>|LEG0.PRICE=<float>[|LEG0.TYPE=LIMIT]|LEG1.SYM=...|LEG1.SIDE=...|LEG1.QTY=...|LEG1.PRICE=...

CANCEL|COMBO_ID=<label>
```

Field defaults:
- COMBO_TYPE: AON
- TIF: DAY
- LEG{i}.TYPE: LIMIT

## Appendix B: CLI Arguments Summary

| Process | Command | Arguments |
|---------|---------|-----------|
| Engine | `pm-engine` | `--verbose/-v`, `--config/-c <path>` |
| Gateway | `pm-gateway` | `--id <GW_ID>` (required) |
| Scheduler | `pm-scheduler` | `--config/-c <path>`, `--now`, `--delay <sec>` |
| Viewer | `pm-viewer` | `--symbol/-s <SYM>` (required), `--depth/-d <n>` |
| Orders | `pm-orders` | `--gateway/-g <GW_ID>` |
| Audit | `pm-audit` | `--log-file <path>`, `--terminal/-t` |
| Clearing | `pm-clearing` | (none) |
| Stats | `pm-stats` | `--db <path>` |
| Ticker | `pm-ticker` | `--db <path>`, `--interval <sec>`, `--db-interval <sec>` |

## Appendix C: Data File Paths

| File | Default Path | Created By |
|------|-------------|------------|
| GTC Orders | `data/gtc_orders.json` | Engine (shutdown) |
| Book Stats | `data/book_stats.json` | Engine (shutdown) |
| Audit Log | `data/audit.log` | Audit process |
| Clearing Report | `data/clearing_report.csv` | Clearing process |
| Statistics DB | `data/stats.db` | Stats process |
| Engine Config | `engine_config.yaml` | User (manual) |

## Appendix D: Dependencies

| Library | Purpose |
|---------|---------|
| ZeroMQ (pyzmq) | Inter-process messaging |
| Rich | Terminal UI (tables, colours, live display) |
| prompt_toolkit | Interactive line editing with completion |
| PyYAML | Configuration file parsing |
| SQLite (stdlib) | Statistics persistence |

---

## Appendix E: Financial Glossary

This glossary defines all financial and trading terms used in this document. It is intended for readers with no prior domain knowledge of electronic trading or financial markets.

---

### Aggressor (Taker)

The party who initiates a trade by submitting an order that immediately matches against an existing resting order. For example, if a sell order is sitting on the book at $100 and you submit a buy order at $100, you are the aggressor — your order "took" the existing liquidity. The opposite party (whose order was already resting) is called the **passive** or **maker**. The distinction matters for price determination: trades always execute at the passive order's price, giving the aggressor potential price improvement.

---

### Ask (Offer)

The price at which a seller is willing to sell. In an order book, the **ask side** contains all resting sell orders. The **best ask** is the lowest-priced sell order currently available — it represents the cheapest price at which you can immediately buy. Asks are sometimes displayed in red. See also: **Bid**.

---

### Auction / Continuous Trading

This system implements **both** continuous trading and call auctions:

- **Continuous trading** (also called continuous matching): orders are matched immediately as they arrive, one at a time, whenever prices cross. This is the primary mode during the `CONTINUOUS` session phase.
- **Call auction**: orders accumulate without matching during a defined period (the `OPENING_AUCTION` or `CLOSING_AUCTION` phase). When the phase ends, all accumulated orders are matched simultaneously at a single **equilibrium price** — the price that maximizes the total executed quantity. Call auctions are used at market open and close to establish fair reference prices.

The session transitions between these modes automatically based on the schedule (see Section 12.5).

---

### Avg Cost (Average Cost / Cost Basis)

The volume-weighted average price at which a position was built. If you buy 100 shares at $50 and then 100 more at $52, your avg cost is $(50×100 + 52×100) / 200 = $51. Avg cost is used to calculate unrealized P&L: how much you would gain or lose if you closed the position at the current market price.

---

### Best Bid / Best Ask (Top of Book, BBO)

The **best bid** is the highest price any buyer is currently willing to pay (the most competitive buy order). The **best ask** is the lowest price any seller is currently willing to sell at. Together they form the **BBO** (Best Bid and Offer) and define the current quoted market. The difference between them is the **spread**.

---

### Bid

The price at which a buyer is willing to buy. In an order book, the **bid side** contains all resting buy orders. The **best bid** is the highest-priced buy order currently available — it represents the most you can immediately receive when selling. Bids are sometimes displayed in green. See also: **Ask**.

---

### Book (Order Book, Limit Order Book, LOB)

A data structure maintained by the matching engine that holds all resting (unfilled) buy and sell orders for a single instrument, organized by price and time. The buy side is sorted best (highest) price first; the sell side is sorted best (lowest) price first. The book is the central mechanism that determines whether incoming orders can be matched.

---

### Cascade Cancel

A mechanism specific to **combo orders**. When one leg of a combo is cancelled or expires (for any reason — user cancel, SMP, phase-change expiry), all remaining unfilled legs of the same combo are automatically cancelled. This ensures the combo maintains its "all-or-none" semantics at the combo level. Fills that have already executed are NOT reversed — only unfilled portions are cancelled.

---

### Clearing

The post-trade process of determining obligations: who owes what to whom after a trade executes. In this system, the clearing process tracks each participant's net position, average cost, and realized/unrealized profit. In real markets, clearing also involves settlement (actual transfer of securities and cash), netting, and counterparty risk management.

---

### Close Price

The last traded price before the market closes (or, in this system, before the engine shuts down). Used as a reference point for next-day calculations such as opening price change percentage.

---

### Combo Order (Multi-Leg Order)

An order that bundles 2–10 individual orders (called **legs**) across different instruments into a single managed unit. All legs are submitted and posted simultaneously. The combo's lifecycle is tracked as a whole: if all legs fill, the combo is `MATCHED`; if any leg fails, all remaining legs are **cascade-cancelled**. In this system, combos use AON (All-or-None) semantics — meaning the intent is for all legs to execute, though individual leg fills are not atomic (they happen as matching opportunities arise). Common use: pairs trading, hedging, spread strategies.

---

### Cost Basis

See **Avg Cost**.

---

### Crossing (Crossed Orders)

When an incoming order's price is equal to or better than the best price on the opposite side, the orders **cross** and a trade occurs. For example: if the best ask is $100 and a buy order arrives at $100 or higher, they cross. Orders that do not cross rest on the book.

---

### DAY (Time in Force)

An order validity period. A DAY order remains active only for the current trading session. When the engine shuts down (end of day), all unfilled DAY orders are automatically expired (cancelled). The next session starts with a clean slate for DAY orders.

---

### Depth

The number of price levels visible in the order book. "Depth of 10" means the viewer shows the 10 best bid price levels and 10 best ask price levels. A "deep" book has many price levels with substantial quantity.

---

### Displayed Quantity (Visible Slice)

For **iceberg orders**, the portion of the total order size that is currently visible on the order book. Other market participants can only see this slice; the remaining (hidden) quantity is not revealed until the displayed portion is filled.

---

### End of Day (EOD)

The moment when the trading session concludes. In this system, EOD is triggered by the engine's graceful shutdown. At EOD: DAY orders expire, GTC orders are persisted, closing prices are recorded, and an EOD broadcast is sent to all subscribers.

---

### Exchange

An organized marketplace where buyers and sellers come together to trade financial instruments. This system simulates a simplified exchange with a single matching engine acting as the central counterparty for all trades.

---

### Equilibrium Price (Auction Price, Clearing Price)

The single price at which a call auction executes. It is computed by evaluating all candidate prices (every distinct bid and ask price on the book) and selecting the one that **maximizes the total quantity** that can be traded. If multiple prices achieve the same quantity, tie-breaking selects the one with minimum surplus (leftover unexecuted quantity), then lowest price. All auction trades execute at this single price — there is no price-time sweeping through multiple levels as in continuous trading.

---

### Execution (Fill)

The event of an order being matched and a trade occurring. A **full fill** means the entire order quantity was executed. A **partial fill** means only some of the quantity was executed, with the remainder still resting or (for market orders) discarded.

---

### Fill or Kill (FOK)

An order type that must be **completely** filled immediately or not at all. There is no partial execution — if the full quantity cannot be satisfied at the specified price or better, the entire order is rejected. FOK orders never rest on the book.

---

### GTC (Good 'Til Cancelled)

An order validity period. A GTC order remains active indefinitely — it survives the end of the trading session and is automatically restored when the engine restarts. It stays on the book until explicitly cancelled by the user or until it is fully filled. Contrast with **DAY** orders.

---

### Hidden Quantity

The portion of an **iceberg order** that is not visible to other market participants. It will be revealed (become displayed) in slices as the visible portion is consumed by fills.

---

### Iceberg Order

An order type designed to hide the full size of a large order. Only a small portion (the **visible quantity** or **peak**) is shown on the order book at any time. When that visible slice is fully consumed by trades, a new slice is automatically replenished from the hidden quantity. This continues until the entire order is filled. Each replenishment gives the order a new timestamp (it goes to the back of the queue at its price level). Purpose: to avoid signalling to the market that a very large order exists, which could move prices adversely.

---

### Instrument (Symbol, Ticker)

A tradeable asset identified by a short code. In this system, instruments are equities (stocks) identified by their ticker symbol: AAPL (Apple), MSFT (Microsoft), TSLA (Tesla). Each instrument has its own independent order book.

---

### Last Price (Last Trade Price)

The price at which the most recent trade executed for a given instrument. This is the primary real-time indicator of an instrument's current value.

---

### Latency

The time delay between sending an order and receiving a response (acknowledgement, fill, etc.). In this educational system, latency is dominated by ZMQ messaging overhead (sub-millisecond on localhost).

---

### Limit Order

An order to buy or sell at a **specific price or better**. A limit buy at $100 means "buy at $100 or lower"; a limit sell at $100 means "sell at $100 or higher". If the order cannot be immediately executed (no crossing opportunity), it rests on the book, waiting for a future matching order. Limit orders provide price certainty but not execution certainty.

---

### Limit Price

The maximum price a buyer is willing to pay (for a buy limit order) or the minimum price a seller is willing to accept (for a sell limit order).

---

### Liquidity

The ease with which an instrument can be traded without significantly affecting its price. A **liquid** book has many resting orders at tight price levels (narrow spread, high depth). An **illiquid** book has few orders and wide spreads. Limit orders that rest on the book **provide** liquidity (makers); market orders and aggressive limit orders **consume** liquidity (takers).

---

### Long (Long Position)

Holding a positive quantity of an instrument. If you have bought 100 shares of AAPL and not sold any, you are "long 100 AAPL". A long position profits when the price rises and loses when the price falls. Unrealized P&L for a long position = position × (current_price − avg_cost).

---

### Maker (Passive, Liquidity Provider)

A market participant whose resting order provides liquidity to the book. When another participant's incoming order matches against it, the maker's order was already sitting on the book waiting. The maker "made" the market by posting a price. Contrast with **Aggressor/Taker**.

---

### Market Maker (MM)

A participant who continuously posts both buy and sell orders to provide liquidity and earn the spread. In this system, the engine can inject market-maker orders from configuration at startup (with gateway_id "MM"). Real market makers profit from the bid-ask spread while taking on inventory risk.

---

### Market Order

An order to buy or sell immediately at the best available price, regardless of what that price is. Market orders guarantee execution (if there is any liquidity) but not price. They sweep through the order book from the best price outward. If the book is exhausted before the order is fully filled, the unfilled remainder is discarded — market orders never rest.

---

### Matching Engine

The core software component that receives incoming orders, determines whether they can trade against resting orders (based on price-time priority rules), and produces trades. It is the "brain" of the exchange. All order books are maintained inside the matching engine.

---

### Mid Price

The arithmetic average of the best bid and best ask: `(best_bid + best_ask) / 2`. Used as a reference price when no trade has occurred recently, and for calculating percentage changes in the statistics process.

---

### OHLCV

A standard set of statistics for a trading period:
- **O**pen: first trade price of the period
- **H**igh: highest trade price during the period
- **L**ow: lowest trade price during the period
- **C**lose: last trade price of the period
- **V**olume: total quantity traded during the period

These are the fundamental data points used in financial charting and analysis.

---

### Order

An instruction from a market participant to buy or sell a specified quantity of an instrument under specified conditions (price, time validity, type). Orders are the primary input to the matching engine.

---

### Order Book

See **Book**.

---

### Order Type

The execution logic applied to an order. This system supports 7 types:
- **Market**: execute immediately at best available price
- **Limit**: execute at specified price or better; rest if not immediately fillable
- **Stop**: dormant until triggered by price movement, then becomes Market
- **Stop-Limit**: dormant until triggered, then becomes Limit
- **FOK (Fill or Kill)**: fill entirely or reject entirely
- **Iceberg**: like Limit but hides total size, revealing it in slices
- **Combo**: bundles 2–10 child orders across different symbols into a single unit with cascade-cancel semantics

---

### P&L (Profit and Loss)

The financial result of trading activity.

- **Realized P&L**: profit or loss from positions that have been closed (bought then sold, or sold short then bought back). This is actual, locked-in profit/loss.
- **Unrealized P&L** (paper P&L): profit or loss on positions still open, calculated as if you closed them at the current market price. It changes with every price movement.
- **Total P&L** = Realized + Unrealized.

Example: You buy 100 shares at $50 (avg cost = $50). The current price is $52. Your unrealized P&L = 100 × ($52 − $50) = +$200. If you sell 50 shares at $52, your realized P&L = 50 × ($52 − $50) = +$100, and you still have an unrealized P&L of 50 × ($52 − $50) = +$100 on the remaining position.

---

### Partial Fill

When only a portion of an order's quantity is executed. For example, you submit a buy order for 500 shares but only 200 are available at your price — you receive a partial fill of 200, and the remaining 300 stays on the book (for limit orders) or is discarded (for market orders). The order's status transitions from NEW to PARTIAL.

---

### Passive Order

See **Maker**.

---

### Peak (Iceberg Peak)

The fixed size of each visible slice of an iceberg order. For example, an iceberg order of total 10,000 shares with a peak of 500 will show 500 shares on the book at a time, replenishing as each 500-share slice is consumed.

---

### Position

The net quantity of an instrument held by a participant. Positive = **long** (owns shares), negative = **short** (owes shares). Zero = flat (no exposure). Position is tracked per-gateway per-symbol in the clearing process.

---

### Price Improvement

When an order executes at a better price than requested. For example: you submit a buy limit at $101, but the best ask is $100 — you get filled at $100, saving $1 per share. This happens because trades execute at the **resting** order's price (passive price), not the aggressor's limit.

---

### Price Level

All orders at a single price on one side of the book, viewed as an aggregate. For example, "3 orders totalling 500 shares at $100.00" is one price level. The order book snapshot reports data aggregated by price level.

---

### Price-Time Priority

The fundamental matching rule: orders are filled in order of **price** first (best price has priority), then **time** (oldest order at the same price has priority). This ensures fairness — you cannot jump the queue by submitting later at the same price, and you can jump the queue by offering a better price.

---

### Quote

In the context of this system, the current best bid and best ask together represent the "quote" for an instrument. A market maker who posts both a bid and an ask is said to be "quoting" the instrument. The quote tells you the price at which you can immediately buy (the ask) or sell (the bid).

---

### Realized P&L

See **P&L**.

---

### Resting Order

An order that has been accepted into the order book and is waiting to be matched by a future incoming order. Only limit orders, stop orders, and iceberg orders can rest. Market and FOK orders never rest — they either execute immediately or are removed.

---

### Self Match Prevention (SMP)

A protection mechanism that prevents a single participant from accidentally trading against their own resting orders. This can happen when automated trading strategies submit both buy and sell orders for the same instrument. SMP detects when an incoming order would match a resting order from the same gateway and takes a configured action (cancel one or both) instead of creating a self-trade.

---

### Settlement

The final transfer of ownership after a trade. In real markets, equities typically settle T+1 (one business day after the trade). In this educational system, settlement is abstracted — the clearing process simply tracks positions and P&L without modelling actual cash/security transfers.

---

### Session Phase (Trading Phase)

The current operating mode of the exchange, which determines what order types are accepted and whether matching occurs. The five phases in this system are: **PRE_OPEN** (orders accepted, no matching), **OPENING_AUCTION** (same + ATO allowed, uncross on exit), **CONTINUOUS** (all types, immediate matching), **CLOSING_AUCTION** (same as auction + ATC allowed, uncross on exit), **CLOSED** (no orders). Transitions between phases are driven by the scheduler process.

---

### Short (Short Position)

Holding a negative quantity of an instrument — effectively owing shares. A short position is created by selling shares you don't own (selling first, intending to buy back later). Short positions profit when the price falls and lose when the price rises. Unrealized P&L for a short position = |position| × (avg_cost − current_price).

---

### Spread (Bid-Ask Spread)

The difference between the best ask and the best bid: `spread = best_ask − best_bid`. A narrow spread (e.g., $0.01) indicates a liquid market. A wide spread indicates an illiquid market or uncertainty. The spread represents the cost of immediately round-tripping (buying then selling, or vice versa).

---

### Stop Loss Order (Stop Order)

An order that is dormant (not on the active book) until a specified price level is reached (the **stop price** or **trigger price**). When the last trade price hits the trigger:
- A **BUY STOP** triggers when the price **rises** to or above the stop price. Used to limit losses on a short position or to enter a long position on a breakout.
- A **SELL STOP** triggers when the price **falls** to or below the stop price. Used to limit losses on a long position ("stop loss").

Upon triggering, the order converts to a market order (or a limit order for stop-limit) and is processed normally.

---

### Stop-Limit Order

A combination of stop and limit: dormant until the stop price is reached (like a stop order), then converts to a limit order (not a market order). This gives the trader control over the worst execution price after triggering, but with the risk that the limit order may not fill if the market moves too quickly past the limit price.

---

### Stop Price (Trigger Price)

The price at which a stop or stop-limit order activates. It is NOT the execution price — it is the condition that causes the order to "wake up" and enter the active matching process.

---

### Symbol

See **Instrument**.

---

### Ticker

A short, uppercase alphabetic code identifying a traded instrument (e.g., AAPL, MSFT, TSLA). Also refers to the scrolling display of price data ("ticker tape"), which in this system is the Ticker process showing periodic one-line market snapshots.

---

### Time in Force (TIF)

A parameter that specifies how long an order remains active if not filled:
- **DAY**: expires at end of session (engine shutdown)
- **GTC** (Good 'Til Cancelled): persists indefinitely across sessions until filled or manually cancelled
- **ATO** (At-The-Open): only valid during the `OPENING_AUCTION` phase; participates in the opening uncross then expires
- **ATC** (At-The-Close): only valid during the `CLOSING_AUCTION` phase; participates in the closing uncross then expires

---

### Trade (Execution, Transaction)

The event that occurs when a buy order and a sell order are matched by the engine at an agreed price and quantity. A trade always involves exactly two parties (buyer and seller) and produces a trade record with a unique ID, price, quantity, and timestamp.

---

### Trading Session (Trading Day)

The period during which the matching engine is running and accepting orders. Corresponds to one run of the engine process from startup to shutdown. DAY orders are scoped to a single session; GTC orders span multiple sessions.

---

### Unrealized P&L (Paper P&L, Mark-to-Market)

See **P&L**.

---

### Uncross

The process of executing all accumulated orders at the end of a call auction phase. During the auction, orders rest without matching. When the phase transitions out (e.g., OPENING_AUCTION → CONTINUOUS), the engine computes the **equilibrium price** and executes all crossable interest at that single price. This is called "uncrossing" because all orders whose prices "cross" (overlap) at the equilibrium price are matched simultaneously.

---

### Volume

The total quantity of shares traded for an instrument during a given period. "Daily volume of 50,000" means 50,000 shares changed hands today across all trades. High volume generally indicates strong market interest.

---

### VWAP (Volume-Weighted Average Price)

The average trade price weighted by the quantity of each trade:

$$\text{VWAP} = \frac{\sum (\text{price}_i \times \text{quantity}_i)}{\sum \text{quantity}_i}$$

VWAP represents the "fair" average price at which trading occurred. It is used as a benchmark — if you bought below VWAP, you got a better-than-average price. Institutional traders often measure execution quality against VWAP.

Example: Two trades — 100 shares at $50 and 200 shares at $51.
VWAP = (100×50 + 200×51) / (100+200) = 15,200 / 300 = $50.67.

---

*End of Requirements Document*

# Message Reference

!!! note "Learning objectives"
    After reading this page you will understand:

    - What a message is in the context of a distributed bus system and how it
      differs from a function call or shared data structure
    - How messages are defined in real systems (schema registries, IDL, plain JSON)
      and the pragmatic trade-offs EduMatcher makes
    - What ZeroMQ requires of a message — frames, encoding, topic filters
    - Why ZeroMQ has no broker, and what that means for reliability and operational
      complexity compared with broker-based systems (Kafka, RabbitMQ, NATS)
    - The full catalogue of messages used in EduMatcher, their fields, and which
      processes produce and consume each one

---

## Background — Messages in a Bus System

### What is a message?

A function call passes data synchronously inside a process: the caller blocks
until the callee returns.  A **message** is an asynchronous unit of data sent
between processes.  The sender does not wait for a response; it hands the
message to the transport layer and moves on.

Messages carry three things:

1. **Identity** — what kind of event this is (the topic or message type)
2. **Payload** — the data describing the event
3. **Routing metadata** — information the transport needs to deliver it
   (addresses, topic filters, sequence numbers)

### How message formats are defined in real systems

In production systems there are three common approaches to defining what a
message looks like:

**Schema registries (Avro, Protobuf, Thrift)**
: Messages are defined in an Interface Definition Language (IDL) file.
  A code generator produces serialisers and deserialisers for every target
  language.  The registry enforces compatibility: a new field may be added
  but existing fields cannot be removed or re-typed without a version bump.
  Kafka and gRPC use this model.

**Canonical JSON/XML schemas (JSON Schema, OpenAPI, AsyncAPI)**
: Message shapes are described in a human-readable document (like AsyncAPI
  for event-driven systems).  Any process that speaks JSON can produce or
  consume a message without a code generator.  The schema document is the
  contract; violations surface only at runtime unless you add a validation
  library.

**Hardcoded structures**
: The simplest approach — message shape is implicit in the code that creates
  and reads it.  No IDL, no registry, no generator.  Fast to build, but
  schema drift is invisible until something breaks at runtime.

EduMatcher uses the **hardcoded approach**.  Each message type is created
by a helper function in `pythonmatcher/models/message.py` (e.g.
`make_order_new_msg`, `make_gateway_connect_msg`) and decoded by `decode()`.
Every field documented on this page is exactly what those functions produce.
This is ideal for a learning system — you can read the code and immediately
see the message — but a real exchange would use Protobuf or Avro to enforce
schema contracts across teams and languages.

### What ZeroMQ requires of a message

ZeroMQ does not impose a message format.  It sees messages as one or more
opaque **frames** — byte arrays that are sent and received atomically as a
group.  It is up to the application to define what those bytes mean.

EduMatcher uses exactly **two frames** for every message:

```
frame[0]  →  topic string, UTF-8 encoded
             e.g.  b"order.ack.GW01"

frame[1]  →  JSON payload, UTF-8 encoded
             e.g.  b'{"order_id": "3f2a...", "accepted": true}'
```

`frame[0]` doubles as the **PUB/SUB filter key**.  A subscriber that
registers for prefix `"order.ack.GW01"` will receive only messages whose
first frame starts with that string — all other messages are dropped by the
ZeroMQ layer before the application even sees them.  This prefix-match filter
is evaluated in the kernel's socket buffer, not in Python, so it adds almost
no CPU overhead regardless of how many message types are on the bus.

### ZeroMQ without a broker

Most messaging systems interpose a **broker** between producers and consumers:

```
Producer ──▶  Broker  ──▶  Consumer
```

The broker buffers messages, persists them to disk, routes them to the right
queues, and handles consumer acknowledgements.  Examples: RabbitMQ, Apache
Kafka, NATS JetStream, AWS SQS.

ZeroMQ is **brokerless**.  Producers connect directly to consumers (or to the
engine in PUSH/PULL):

```
Gateway ──PUSH──▶  Engine ──PUB──▶  Subscriber A
                                ├──▶  Subscriber B
                                └──▶  Subscriber C
```

There is no third process in the middle.  The advantages and disadvantages
flow directly from that choice:

**Advantages of no broker**

| Advantage | Detail |
|-----------|--------|
| **Lower latency** | No extra network hop; messages go directly from sender to receiver |
| **Fewer moving parts** | No broker process to install, configure, monitor, or restart |
| **No single point of failure** | The engine is the bus; if the engine is up, the bus is up |
| **Simpler deployment** | `pip install pyzmq` is the entire installation |

**Disadvantages of no broker**

| Disadvantage | Detail |
|--------------|--------|
| **No persistence** | If a subscriber is down when a message is published, the message is gone forever |
| **No guaranteed delivery** | PUB/SUB drops messages to slow subscribers without warning |
| **No replay** | You cannot re-consume old messages; there is no commit log |
| **Tight coupling on addresses** | Producers must know the address of the engine; adding a new engine address requires reconfiguring all clients |
| **No backpressure** | A fast publisher can overwhelm a slow subscriber; the subscriber's receive buffer fills and messages are silently discarded |

For EduMatcher these trade-offs are acceptable: the system runs on
localhost, sessions last hours not days, and correctness over time is handled
by the GTC persistence layer rather than the message bus.  For a real exchange,
the audit trail would be written by a Kafka consumer (guaranteed delivery,
infinite replay), and the matching engine would use a persisted queue for order
intake.

---

## Message structure

Every inter-process communication in EduMatcher is a two-frame ZeroMQ
multipart message.  ZeroMQ (ZMQ) is a high-performance messaging library;
a "multipart message" is simply an ordered list of byte-array frames sent
and received atomically:

| Frame | Content |
|---|---|
| `frame[0]` | Topic string (UTF-8) — used for PUB/SUB prefix filtering |
| `frame[1]` | JSON payload (UTF-8) |

## Transport channels

| Channel | ZMQ pattern | Address | Direction |
|---|---|---|---|
| Order submission | PUSH → PULL | `tcp://127.0.0.1:5555` | Gateway → Engine |
| Event broadcast | PUB → SUB | `tcp://127.0.0.1:5556` | Engine → all subscribers |

---

## Order messages (gateway → engine)

### `system.gateway_connect`

Sent by a FIX gateway at startup to authenticate its gateway ID against
`engine_config.yaml`.

| Field | Type | Description |
|---|---|---|
| `gateway_id` | string | Gateway identifier being requested (e.g. `TRADER01`) |

**Reply:** `system.gateway_auth.{GW_ID}`

| Field | Type | Description |
|---|---|---|
| `gateway_id` | string | Gateway identifier |
| `accepted` | boolean | `true` if ID is configured in `gateways.fix` |
| `reason` | string | Rejection reason when `accepted=false` |
| `description` | string | Optional configured description for the gateway |

When `accepted=false`, the gateway must terminate and MUST NOT submit orders.

---

### `order.new`

Sent by a gateway to submit a new order for matching.

| Field | Type | Description |
|---|---|---|
| `id` | string (UUID) | Unique order identifier |
| `symbol` | string | Instrument ticker, e.g. `MSFT` |
| `side` | `"BUY"` \| `"SELL"` | Order side |
| `order_type` | string | `MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT`, `FOK`, `ICEBERG` |
| `tif` | `"DAY"` \| `"GTC"` \| `"ATO"` \| `"ATC"` \| `"FOK"` | Time-in-force |
| `quantity` | integer | Total order quantity |
| `remaining_qty` | integer | Unfilled quantity (equals `quantity` on submission) |
| `gateway_id` | string | Originating gateway identifier, e.g. `TRADER01` |
| `timestamp` | float | Unix epoch (seconds) |
| `status` | string | Initial status, always `"NEW"` |
| `price` | float \| null | Limit price (LIMIT, STOP_LIMIT, FOK, ICEBERG) |
| `stop_price` | float \| null | Trigger price (STOP, STOP_LIMIT) |
| `visible_qty` | integer \| null | Peak size for ICEBERG orders |
| `displayed_qty` | integer \| null | Current visible slice (ICEBERG) |
| `smp_action` | string | Self-match prevention: `NONE`, `CANCEL_AGGRESSOR`, `CANCEL_RESTING`, `CANCEL_BOTH` |

---

### `order.cancel`

Sent by a gateway to cancel a resting order.

| Field | Type | Description |
|---|---|---|
| `order_id` | string (UUID) | ID of the order to cancel |
| `gateway_id` | string | Gateway that owns the order |

---

### `order.amend`

Sent by a gateway to amend the price and/or quantity of a resting order.

| Field | Type | Description |
|---|---|---|
| `order_id` | string (UUID) | ID of the order to amend |
| `gateway_id` | string | Gateway that owns the order |
| `price` | float \| absent | New limit price (omit to keep current) |
| `qty` | integer \| absent | New total quantity (omit to keep current) |

At least one of `price` or `qty` must be present.

**Priority rules:**

- Quantity decrease only → priority **preserved** (timestamp unchanged)
- Price change or quantity increase → priority **lost** (new timestamp assigned)

**Reply:** `order.amended.{GW_ID}` on success, or `order.ack.{GW_ID}` with `accepted=false` on rejection.

---

### `order.combo`

Sent by a gateway to submit a combo (multi-leg) order.

| Field | Type | Description |
|---|---|---|
| `id` | string (UUID) | Internal combo identifier |
| `combo_id` | string | User-provided tracking label |
| `gateway_id` | string | Originating gateway identifier |
| `combo_type` | `"AON"` | Combo semantics (all-or-none) |
| `tif` | `"DAY"` \| `"GTC"` | Time-in-force for all legs |
| `legs` | array of leg objects | Each leg: `{symbol, side, order_type, quantity, price}` |
| `timestamp` | float | Unix epoch (seconds) |
| `status` | string | Initial status (`"PENDING"`) |

---

### `order.combo_cancel`

Sent by a gateway to cancel a combo and all its child legs.

| Field | Type | Description |
|---|---|---|
| `combo_id` | string | User-provided combo label to cancel |
| `gateway_id` | string | Gateway that owns the combo |

---

## Order events (engine → subscribers)

All topics in this section are published on the PUB socket and filtered by the gateway-specific suffix where applicable.

### `order.ack.{GW_ID}`

Acknowledgement of an `order.new` submission.  
Subscribed to by the originating gateway and the order monitor.

| Field | Type | Description |
|---|---|---|
| `order_id` | string (UUID) | Order being acknowledged |
| `accepted` | boolean | `true` = accepted; `false` = rejected |
| `reason` | string | Rejection reason (empty string when accepted) |
| `symbol` | string | Instrument ticker *(present when accepted)* |
| `side` | string | Order side *(present when accepted)* |
| `order_type` | string | Order type *(present when accepted)* |
| `tif` | string | Time-in-force *(present when accepted)* |
| `qty` | integer | Original quantity *(present when accepted)* |
| `price` | float \| null | Limit price *(present when accepted)* |

!!! note "Rejection reasons"
    Common rejection reasons: `"Symbol not configured: XYZ"`, `"Insufficient liquidity"` (FOK), `"Order not found"` (cancel), `"Gateway not configured: TRADER99"`, `"Gateway not connected: TRADER01"`.

---

### `order.fill.{GW_ID}`

Notifies a gateway (and the order monitor) of a partial or full fill.  
Both the aggressor and the resting counterparty receive their own `order.fill` message.

| Field | Type | Description |
|---|---|---|
| `order_id` | string (UUID) | Filled order |
| `fill_qty` | integer | Quantity matched in this fill event |
| `fill_price` | float | Price at which the fill occurred |
| `remaining_qty` | integer | Unfilled quantity remaining after this fill |
| `status` | `"PARTIAL"` \| `"FILLED"` | Order status after the fill |
| `symbol` | string | Instrument ticker |
| `side` | string | Order side |
| `order_type` | string | Order type |
| `tif` | string | Time-in-force |
| `qty` | integer | Original quantity |
| `price` | float \| null | Limit price |

---

### `order.cancelled.{GW_ID}`

Confirms a cancel request or a Self-Match Prevention (SMP) forced cancellation.

| Field | Type | Description |
|---|---|---|
| `order_id` | string (UUID) | Cancelled order |

---

### `order.amended.{GW_ID}`

Confirms a successful order amendment.

| Field | Type | Description |
|---|---|---|
| `order_id` | string (UUID) | Amended order ID (unchanged from original) |
| `price` | float | New price after amendment |
| `qty` | integer | New total quantity after amendment |
| `remaining_qty` | integer | Remaining unfilled quantity |
| `priority_reset` | boolean | `true` if the order lost time priority |

---

### `order.expired.{GW_ID}`

Published during engine shutdown for every resting `DAY` order that did not fill.

| Field | Type | Description |
|---|---|---|
| `order_id` | string (UUID) | Expired order |

---

### `order.orders.{GW_ID}`

Response to an `order.orders_request` from a gateway; delivers the full current order list.

| Field | Type | Description |
|---|---|---|
| `orders` | array of order dicts | Each element has the same shape as `order.new` plus a current `status` and `remaining_qty` |

---

## Combo events (engine → subscribers)

### `combo.ack.{GW_ID}`

Acknowledgement of a combo order submission.

| Field | Type | Description |
|---|---|---|
| `combo_id` | string | User-provided combo label |
| `accepted` | boolean | `true` = combo accepted; `false` = rejected |
| `reason` | string | Rejection reason (empty when accepted) |
| `combo` | object \| null | Full combo payload when accepted |

!!! note "Rejection reasons"
    Common rejection reasons: `"Combo requires at least 2 legs"`, `"Duplicate symbols in combo legs"`, `"Symbol not configured: XYZ"`, `"Leg 0: invalid quantity 0"`, `"Leg 0: LIMIT requires a price"`.

---

### `combo.status.{GW_ID}`

Published when a combo transitions between lifecycle states.

| Field | Type | Description |
|---|---|---|
| `combo_id` | string | User-provided combo label |
| `status` | string | New combo status (see below) |
| `details` | object \| null | Optional details, e.g. `{"reason": "Leg 0 (AAPL) CANCELLED"}` |

**Combo statuses:**

| Status | Meaning |
|--------|---------|
| `PENDING` | Combo accepted, children resting, no fills yet |
| `PARTIALLY_MATCHED` | At least one leg has a fill, but not all legs are fully filled |
| `MATCHED` | All legs fully filled — combo complete |
| `FAILED` | A child leg was cancelled or expired — cascade-cancel triggered |
| `CANCELLED` | User cancelled via `CANCEL\|COMBO_ID=` — all children cancelled |

---

## Trade events (engine → all subscribers)

### `trade.executed`

Published once per matched trade pair. Consumed by clearing, audit, and statistics processes.

| Field | Type | Description |
|---|---|---|
| `id` | string (UUID) | Unique trade identifier |
| `symbol` | string | Instrument ticker |
| `buy_order_id` | string (UUID) | Buyer's order |
| `sell_order_id` | string (UUID) | Seller's order |
| `buy_gateway_id` | string | Gateway that submitted the buy order |
| `sell_gateway_id` | string | Gateway that submitted the sell order |
| `price` | float | Execution price |
| `quantity` | integer | Matched quantity |
| `timestamp` | float | Unix epoch (seconds) |

---

## Book events (engine → all subscribers)

### `book.{SYMBOL}`

Full order-book snapshot published after every state change for the named symbol.  
Consumed by order-book viewers and the statistics process.

| Field | Type | Description |
|---|---|---|
| `symbol` | string | Instrument ticker |
| `bids` | array of level dicts | Sorted best-to-worst; each level: `{"price", "qty", "count"}` |
| `asks` | array of level dicts | Sorted best-to-worst; each level: `{"price", "qty", "count"}` |
| `last_price` | float \| null | Price of the most recent trade |
| `last_qty` | integer \| null | Quantity of the most recent trade |
| `last_buy_price` | float \| null | Last price where the buyer was aggressor |
| `last_sell_price` | float \| null | Last price where the seller was aggressor |
| `recent_trades` | array | Up to 5 most recent `trade.executed` payloads |

---

## Request / response (gateway → engine, point-to-point)

These messages travel over the PUSH/PULL channel (port 5555) and the reply is published on the PUB socket filtered by `{GW_ID}`.

### `book.snapshot_request`

Requests the current book snapshot for a symbol (used by viewers on startup to avoid waiting for the next update).

| Field | Type | Description |
|---|---|---|
| `symbol` | string | Symbol to request |

**Reply:** `book.{SYMBOL}` — same shape as above.

---

### `system.symbols_request`

Requests the list of configured symbols from the engine.
Used by gateways on connect and by the statistics process at startup to discover
which symbols to pull opening book snapshots for.

| Field | Type | Description |
|---|---|---|
| `gateway_id` | string | Requesting process identifier. Gateways use their own ID; the statistics process uses the fixed ID `"STATS"` |

**Reply:** `system.symbols.{GW_ID}`

| Field | Type | Description |
|---|---|---|
| `symbols` | array of strings | All symbols configured in `engine_config.yaml` |

---

### `order.orders_request`

Requests the current order list for a specific gateway.

| Field | Type | Description |
|---|---|---|
| `gateway_id` | string | Gateway whose orders are requested |

**Reply:** `order.orders.{GW_ID}` — see above.

---

## System messages (engine → all subscribers)

### `session.state`

Broadcast whenever the engine transitions between session phases (e.g.
from OPENING_AUCTION to CONTINUOUS).  Consumed by gateways, monitors,
and the statistics process to know what trading mode is currently active.

| Field | Type | Description |
|---|---|---|
| `state` | string | New session state: `"PRE_OPEN"`, `"OPENING_AUCTION"`, `"CONTINUOUS"`, `"CLOSING_AUCTION"`, `"CLOSED"` |
| `prev_state` | string | Previous session state (empty string on first transition) |

---

### `auction.result.{SYMBOL}`

Broadcast once per symbol after an auction uncross completes (i.e. when
transitioning out of OPENING_AUCTION or CLOSING_AUCTION).  Reports the
equilibrium price, quantity matched, and any imbalance.

| Field | Type | Description |
|---|---|---|
| `symbol` | string | Instrument ticker |
| `eq_price` | float \| null | Equilibrium (uncross) price; `null` if no crossable interest |
| `eq_qty` | integer | Total quantity matched at the equilibrium price |
| `trades_count` | integer | Number of individual trade pairs generated |
| `imbalance_side` | string | `"BUY"`, `"SELL"`, or `""` (balanced) |
| `imbalance_qty` | integer | Surplus quantity that could not be matched |

---

### `system.eod`

Broadcast by the engine at shutdown before sockets are closed.  
Consumed by the statistics process to record end-of-day closing bid/ask prices.

| Field | Type | Description |
|---|---|---|
| `books` | array of book snapshots | One entry per active symbol; each element has the same shape as a `book.{SYMBOL}` payload |

---

## Session messages (scheduler → engine)

### `session.transition`

Sent by the `pm-scheduler` process to request a session-phase transition.
Travels over the PUSH/PULL channel (port 5555), same as order messages.

| Field | Type | Description |
|---|---|---|
| `to_state` | string | Target state: `"PRE_OPEN"`, `"OPENING_AUCTION"`, `"CONTINUOUS"`, `"CLOSING_AUCTION"`, `"CLOSED"` |

The engine validates the transition (see [Auctions & Scheduling](auction.md)
for valid state transitions).  Invalid transitions are silently rejected
and logged to stderr.  On success, the engine publishes a `session.state`
event confirming the new phase.

---

## Subscription filter summary

| Subscriber | Topics subscribed |
|---|---|
| Gateway | `system.gateway_auth.{own GW_ID}`, `order.ack.{own GW_ID}`, `order.fill.{own GW_ID}`, `order.amended.{own GW_ID}`, `order.cancelled.{own GW_ID}`, `order.expired.{own GW_ID}`, `order.orders.{own GW_ID}`, `combo.ack.{own GW_ID}`, `combo.status.{own GW_ID}`, `system.symbols.{own GW_ID}`, `session.state` |
| Order-book viewer | `book.{SYMBOL}`, `session.state` |
| Order monitor | `order.` (prefix — all order events), `combo.`, `session.state` |
| Clearing | `trade.executed` |
| Audit | *(empty filter — receives everything)* |
| Statistics | `trade.`, `book.`, `system.eod`, `system.symbols.STATS`, `session.state`, `auction.result.` |

---

## Price And Timestamp Semantics (v2)

- Internal engine/model state uses integer ticks for price and integer
  nanoseconds for ordering-critical timestamps.
- External process payloads keep human-readable decimal prices and seconds-based
  timestamps where appropriate.
- Message producers convert from internal ticks/ns at publish boundaries.

Practical rule:

- Do not perform business logic on decimal payload values in core matching code.
- Do conversion at process edges only.

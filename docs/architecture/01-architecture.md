# Architecture

!!! note "Learning objectives"
    After reading this page you will understand:

    - Why a multi-process message-passing architecture was chosen over a monolith or
      a shared-memory design, and how this mirrors real trading systems
    - The fundamental messaging concepts: topics, publish/subscribe, point-to-point,
      broadcast, and subscription filters
    - How the ZeroMQ brokerless topology connects all processes in EduMatcher
    - The internal data structures of an order book — heaps, lazy deletion, price-level
      indexes — and how to read a visual order book depth diagram
    - The time complexity of every core operation: insert, match, cancel, stop trigger
    - The principal data flows, the single-host/remote deployment boundary, and the trust model
    - How state persists and is recovered across a restart, and what is *not* durable
    - The runtime failure modes — ZeroMQ back-pressure and silent PUB drop to slow consumers
    - Which configuration choices materially change throughput, latency, and memory

!!! info "This page vs. the Detailed Walkthrough"
    This page is the **architecture reference**: decisions, data flows, persistence,
    failure modes, and performance. For a first-principles, code-level tour that
    builds the same system up from a single limit order, read the
    [Detailed Walkthrough](02-architecture-guide.md). Where the two overlap, this
    page is the concise reference and the Walkthrough is the narrative.



## Why This Architecture?

### Three ways to build a trading system

Before looking at what EduMatcher does, it helps to understand the alternatives
and why they fall short for this use case.

**Option 1 — Monolith**
: One process, one program.  The user types an order, matching runs, results print.
  Simple to build, simple to debug.  Falls apart as soon as two users need to trade
  simultaneously, or when you want to add an audit log without touching the matching code.

**Option 2 — Shared memory / threads**
: Multiple threads share an in-process order book protected by a lock.
  Common in C++ HFT cores.  Fast, but extremely hard to reason about:
  lock contention, priority inversion, and data races all wait to bite you.
  Also single-machine — you can't run the viewer on a separate screen
  without redesigning everything.

**Option 3 — Multi-process message passing**
: Each process owns its own state and communicates by sending messages.
  No shared memory, no locks.  Processes can run on different machines.
  Adding a new observer (an audit logger, a new data feed) means writing a
  new subscriber — the engine doesn't change.

EduMatcher uses Option 3.  It is also how most real exchange systems are
actually built: a matching engine core that publishes every event on an internal
bus, with a fleet of downstream consumers (clearing, risk, market data
distribution, surveillance) that subscribe to the topics they care about.

### Core messaging concepts

Before reading the topology diagram, it is worth having clear definitions:

**Topic**
: A string label attached to every message that identifies what kind of event it
  carries.  Examples: `trade.executed`, `order.fill.GW01`, `book.AAPL`.
  Think of it like the subject line of an email — the sender sets it, the
  receiver uses it to decide whether to read the body.

**Publish / Subscribe (PUB/SUB)**
: One sender, many potential receivers.  The sender *publishes* to a topic; every
  process that has *subscribed* to that topic receives a copy.  Processes that have
  not subscribed never see the message.  This is how the engine broadcasts book
  updates: one `book.AAPL` message is published; the viewer, the stats recorder,
  and the board all receive it independently.

**Subscription filter**
: A subscriber declares which topics it wants to receive.  In ZeroMQ, the filter is
  a simple prefix match: a subscription for `"order.fill.GW01"` receives only
  messages whose topic starts with that string.  A subscription for `"book."` receives
  book updates for all symbols.  An empty-string subscription receives everything.

**Broadcast**
: A message sent to all subscribers simultaneously with no specific address.
  The engine broadcasts `session.state` when the trading phase changes — every
  process (gateways, viewers, stats, board) reacts according to its own logic.

**Point-to-point (PUSH/PULL)**
: One sender, exactly one receiver.  EduMatcher uses PUSH/PULL for order
  submission: a gateway *pushes* an order message and the engine *pulls* it.
  No other process sees that message; no routing table is needed because the
  engine is the only process that ever binds the PULL socket.

**Message routing**
: In a broker-based system, the broker reads the topic and decides which queue
  to put the message in.  In EduMatcher, routing is done by the ZeroMQ
  layer using the subscription filter — no broker, no routing table, no extra
  process.

**Private reply over PUB/SUB**
: The subscription prefix enables a lightweight request/reply pattern without a
  dedicated REQ/REP socket.  When a gateway pushes a `system.symbols_request`
  command, the engine publishes the answer on `system.symbols.GW01` — a topic
  only that gateway's SUB filter will match; every other subscriber silently
  discards it at the ZMQ layer.  This pattern covers every personalised engine
  response: `order.ack.{GW}`, `system.symbols.{GW}`, `system.quote_bootstrap.{GW}`,
  and more.  It requires every connected process to register a unique gateway ID.



## Overview

EduMatcher uses a **broker-less ZeroMQ** topology.  
The matching engine is the only process that *binds* sockets — all other processes *connect* to it.  
No ZMQ broker daemon, no message queue server, no external dependencies beyond ZMQ itself.



## ZMQ Topology

```mermaid
graph TD
    ALF["pm-alf-console\nALF"]
    APIGW["pm-api-gwy"]
    MMBOT["pm-mm-bot"]
    SCH["pm-scheduler"]

    subgraph Engine["Matching Engine — sole binder"]
        PULL["PULL :5555\norder commands"]
        PUB56["PUB :5556\nmarket events"]
        PUB57["PUB :5557\ndrop-copy"]
    end

    GW_R["pm-alf-console\nprivate events"]
    APIR["pm-api-gwy\nWebSocket bridge"]
    OPS["pm-stats · pm-clearing · pm-audit"]
    UI["pm-viewer · pm-board · pm-ticker · pm-orders"]
    IDX["pm-index"]
    MD["pm-md-gwy\nCALF TCP bridge"]
    PT["pm-ralf-gwy\nRALF TCP bridge"]
    DCC["Risk / compliance consumers"]

    subgraph IndexBus["Index bus  (pm-index binds)"]
        IPUB["PUB :5558\nindex events"]
        IPULL["PULL :5559\nindex commands"]
    end

    ExtMD["External market-data clients"]
    ExtPT["External post-trade clients"]

    ALF & APIGW & MMBOT & SCH -->|PUSH| PULL
    PUB56 -->|SUB| GW_R & APIR & OPS & UI & IDX & MD & PT
    PUB57 -->|SUB| DCC
    IDX -->|binds| IPUB & IPULL
    ALF & APIGW -.->|"SUB / PUSH"| IndexBus
    MD -->|"CALF / TCP"| ExtMD
    PT -->|"RALF / TCP"| ExtPT
```



## Message Topics

All messages are two-frame ZMQ multipart:

- **frame[0]** — topic string (used for SUB filtering)
- **frame[1]** — JSON payload

### Commands — GW / operator → Engine (PUSH :5555)

| Topic | Description |
|-------|-------------|
| `order.new` | Submit a new order |
| `order.cancel` | Cancel a resting order |
| `order.amend` | Amend the price and/or quantity of a resting order |
| `order.combo` | Submit a multi-leg combo order |
| `order.combo_cancel` | Cancel a combo and all its child legs |
| `order.oco` | Link two resting orders into an OCO pair |
| `order.oco_cancel` | Cancel both legs of an OCO pair |
| `quote.new` | Submit or replace a two-sided market-maker quote |
| `quote.cancel` | Cancel the active quote for a symbol |
| `risk.kill_switch` | Cancel all resting orders and quotes for a gateway |
| `risk.symbol_halt` | Operator halt of a single symbol |
| `risk.symbol_resume` | Resume a previously halted symbol |
| `risk.cancel_symbol` | Cancel all resting orders across all gateways on one symbol |
| `risk.circuit_breaker_halt_all` | Administrative global halt |
| `risk.circuit_breaker_resume_all` | Administrative global resume |
| `system.gateway_connect` | Authenticate a gateway ID on startup |
| `system.gateway_disconnect` | Graceful disconnect notice from a gateway |
| `system.symbols_request` | Request the list of configured symbols |
| `book.snapshot_request` | Request an immediate book snapshot for a symbol |
| `order.orders_request` | Request the current resting order list for a gateway |
| `system.quote_bootstrap_request` | Request active quote state for a gateway |
| `system.quote_legs_request` | Request quote leg snapshot (QLEGS) |
| `system.session_state_request` | Request current session state |
| `system.gateways_request` | Request the list of configured gateways and connection status |
| `system.volume_request` | Request cumulative traded volume for all symbols |
| `system.halt_status_request` | Request a snapshot of all currently halted symbols |
| `system.position_request` | Request per-symbol position snapshot for a gateway |
| `session.transition` | Request a session-phase change (sent by pm-scheduler) |

### Private replies — Engine → GW (PUB :5556, personalised prefix)

| Topic | Description |
|-------|-------------|
| `order.ack.{GW_ID}` | Order accepted or rejected |
| `order.fill.{GW_ID}` | Partial or full fill notification |
| `order.cancelled.{GW_ID}` | Cancel confirmed or SMP-forced cancellation |
| `order.amended.{GW_ID}` | Amendment confirmed |
| `order.expired.{GW_ID}` | DAY / ATO / ATC order expired at phase change or shutdown |
| `order.orders.{GW_ID}` | Response to `order.orders_request`: full resting order list |
| `combo.ack.{GW_ID}` | Combo order accepted or rejected |
| `combo.status.{GW_ID}` | Combo lifecycle state change |
| `oco.ack.{GW_ID}` | OCO link accepted |
| `oco.cancelled.{GW_ID}` | Sibling leg cancelled after other leg filled or was cancelled |
| `quote.ack.{GW_ID}` | Quote accepted or rejected |
| `quote.status.{GW_ID}` | Quote lifecycle state change |
| `risk.kill_switch_ack.{GW_ID}` | Kill-switch execution confirmed |
| `system.gateway_auth.{GW_ID}` | Authentication accepted or rejected |
| `system.symbols.{GW_ID}` | Response to `system.symbols_request` |
| `system.quote_bootstrap.{GW_ID}` | Active quote bootstrap state |
| `system.quote_legs.{GW_ID}` | Quote leg snapshot response |
| `system.session_status.{GW_ID}` | Current session state and enforcement flag |
| `system.gateways.{GW_ID}` | Configured gateways and connection status |
| `system.volume.{GW_ID}` | Cumulative traded volume per symbol |
| `system.halt_status.{GW_ID}` | Currently halted symbols snapshot |
| `system.position.{GW_ID}` | Per-symbol position snapshot (net qty, avg cost) |

### Broadcasts — Engine → all subscribers (PUB :5556)

| Topic | Description |
|-------|-------------|
| `session.state` | Session phase changed; every subscriber reacts accordingly |
| `auction.result.{SYMBOL}` | Auction uncross result: equilibrium price, quantity, imbalance |
| `trade.executed` | A trade was matched; consumed by clearing, stats, RALF, viewers |
| `book.{SYMBOL}` | Full order-book snapshot. **Throttled**, not per-event: after a state change the snapshot is published on the next engine poll tick, and at most once per `snapshot_interval_sec` (default 0.5 s) per symbol. On-demand `book.snapshot_request` replies are immediate. See [Configuration choices that impact performance](#configuration-choices-that-impact-performance). |
| `depth.{SYMBOL}` | Depth-of-market statistics (bid/ask imbalance, cost-to-move) published on the **same throttled tick** as `book.{SYMBOL}`. |
| `circuit_breaker.halt.{SYMBOL}` | Symbol halted by the circuit breaker |
| `circuit_breaker.resume.{SYMBOL}` | Symbol resumed after a circuit-breaker halt |
| `system.eod` | End-of-day shutdown broadcast; signals all subscribers to flush and stop |

### Drop-copy feed — Engine → compliance consumers (PUB :5557)

| Topic | Description |
|-------|-------------|
| `drop_copy.event.{GW_ID}` | Sequenced fill event with nanosecond timestamp, one per filled order leg |
| `drop_copy.replay.{CLIENT_ID}` | Replayed historical fill events in response to a replay request |

### Index bus — pm-index ↔ clients (PUB :5558 / PULL :5559)

`pm-index` is its own process with its own dedicated sockets at ports :5558 and :5559.
It subscribes to the engine PUB at :5556 and publishes index events independently.

| Topic | Direction | Description |
|-------|-----------|-------------|
| `index.update` | pm-index → all | Current index level, OHLC, and session state |
| `index.history_request` | GW → pm-index | Query index history by time range |
| `index.history.{GW_ID}` | pm-index → GW | History query response |
| `index.corp_action` | GW → pm-index | Apply a corporate action to an index constituent |
| `index.corp_action_ack.{GW_ID}` | pm-index → GW | Corporate action acknowledgement |
| `index.constituent_change` | GW → pm-index | Add or remove an index constituent |
| `index.constituent_change_ack.{GW_ID}` | pm-index → GW | Constituent-change acknowledgement |



## Process Roles

| Process | ZMQ Sockets | Binds/Connects | Role |
|---------|------------|----------------|------|
| pm-engine | PULL :5555, PUB :5556, PUB :5557 | **Binds** all three | Matching, session state, combo/OCO/quote tracking, drop-copy |
| pm-alf-console (ALF) | PUSH→:5555, SUB→:5556, SUB→:5558, PUSH→:5559 | Connects | Interactive order entry; ALF line protocol; index data display |
| pm-api-gwy | PUSH→:5555, SUB→:5556, SUB→:5558, PUSH→:5559 | Connects | REST and WebSocket order gateway for programmatic clients |
| pm-mm-bot | PUSH→:5555, SUB→:5556 | Connects | Automated market-maker; manages two-sided quotes |
| pm-scheduler | PUSH→:5555 | Connects | Drives session phase transitions on a time schedule |
| pm-viewer | SUB→:5556 | Connects | Real-time order book display for one symbol |
| pm-orders | SUB→:5556 | Connects | Order status monitor across all gateways |
| pm-audit | SUB→:5556 | Connects | Universal event log (subscribes to all topics) |
| pm-clearing | SUB→:5556 | Connects | P&L tracking and trade settlement |
| pm-stats | SUB→:5556 | Connects | OHLCV statistics and SQLite persistence |
| pm-ticker | SUB→:5556 | Connects | Scrolling market data display |
| pm-board | SUB→:5556 | Connects | Multi-symbol paged market display |
| pm-index | PULL :5559, PUB :5558, SUB→:5556 | **Binds** :5558 and :5559; connects→:5556 | Index calculation, OHLC, corporate actions |
| pm-md-gwy (CALF) | SUB→:5556, SUB→:5558 | Connects | Translates engine events to CALF TCP for external market-data subscribers |
| pm-ralf-gwy (RALF) | SUB→:5556 | Connects | Translates trade events to RALF TCP for external post-trade / clearing parties |



## Data Flows

Four principal flows move through the system. All of them converge on the
single-writer engine and fan back out over PUB topics.

**1. Order entry (request/response).** A gateway PUSHes a command on `:5555`; the
engine processes it run-to-completion and publishes personalised results on the
gateway's private `order.*` / `quote.*` / `system.*` prefixes on `:5556`.

```mermaid
sequenceDiagram
    autonumber
    participant GW as Gateway (ALF/API/MM-bot)
    participant ENG as Engine (single thread)
    participant SUB as Consumers (stats, clearing, audit, viewers, bridges)
    GW->>ENG: PUSH order.new  :5555
    Note over ENG: validate → collar/halt gate → match (sweep) → build events
    ENG-->>GW: PUB order.ack.{GW} / order.fill.{GW}  :5556
    ENG-->>SUB: PUB trade.executed  :5556
    ENG-->>SUB: PUB book.{SYM} / depth.{SYM}  (throttled, next tick)
    ENG-->>SUB: PUB drop_copy.event.{GW}  :5557
```

**2. Market data (broadcast, throttled).** After matching, `trade.executed` is
published immediately, but `book.{SYM}` / `depth.{SYM}` snapshots are coalesced and
emitted on the poll tick, at most once per `snapshot_interval_sec` per symbol (see
[Configuration choices that impact performance](#configuration-choices-that-impact-performance)).
Protocol bridges (`pm-md-gwy`/CALF) re-publish these to external TCP subscribers.

**3. Post-trade & drop-copy.** `trade.executed` feeds `pm-clearing` (P&L),
`pm-stats` (OHLCV), and `pm-audit` (full log) on `:5556`; the sequenced per-fill
drop-copy feed on `:5557` feeds compliance consumers and `pm-ralf-gwy` (RALF).

**4. Index sub-bus.** `pm-index` is a *second-tier publisher*: it subscribes to the
engine's `:5556`, recomputes index levels, and publishes `index.update` on its own
bus (`:5558`), accepting commands on `:5559`. It is the one process besides the
engine that binds sockets.

Where each of these ends up on disk is covered in
[Persistence & crash recovery](#persistence-crash-recovery); how they behave when a
consumer can't keep up is covered in
[Failure modes & fault tolerance](#failure-modes-fault-tolerance).



## Key Design Decisions

### The Engine as the Sole Binder

The engine is the only process that binds sockets (:5555, :5556, :5557).  Every
other process connects to the engine.  This has three practical consequences:

- **Start the engine first.** A gateway that connects before the engine is started
  will block on send until the engine comes up (ZMQ queues outgoing messages).
- **Adding a new subscriber requires no engine change.** Any process can connect
  to :5556 and subscribe to the topics it needs.  The engine has no knowledge of
  who is listening.
- **Restart isolation.** Any subscriber can crash and restart without disturbing
  the engine or other subscribers.  It simply reconnects and resumes.

`pm-index` is the one exception: it binds its own pair of sockets (:5558, :5559)
because it is a second-tier publisher, not a consumer of the engine.

### Two Tiers of Gateways

EduMatcher has two distinct gateway roles:

**Order-entry gateways** (`pm-alf-console`, `pm-api-gwy`, `pm-mm-bot`) connect
directly to the engine over ZMQ PUSH/PULL.  They authenticate via
`system.gateway_connect` and receive personalised events on their subscribed
`order.*`, `quote.*`, and `system.*` topics.  These processes are internal to the
exchange operator.

**Protocol bridges** (`pm-md-gwy`, `pm-ralf-gwy`) subscribe to the engine PUB
socket and translate engine events into an external TCP line protocol for
third-party consumers:

- `pm-md-gwy` (CALF) — real-time order book and trade data for market-data
  subscribers, with session management, subscription filtering, and gap-recovery
  replay
- `pm-ralf-gwy` (RALF) — post-trade execution events for external clearing,
  drop-copy, and audit parties over authenticated TCP sessions

### Bus Segmentation by Function

Separating traffic onto distinct ports serves both operational and compliance needs:

| Port | Socket | Purpose |
|------|--------|---------|
| :5555 | PULL | Order commands — only the engine reads these |
| :5556 | PUB | Market events — all internal subscribers |
| :5557 | PUB | Drop-copy — sequenced fill feed for compliance consumers |
| :5558 | PUB | Index events — separate bus owned by `pm-index` |
| :5559 | PULL | Index commands — received only by `pm-index` |

The drop-copy feed on :5557 deliberately isolates the compliance feed from the full
market event stream.  Each fill event carries a monotonic sequence number and a
nanosecond timestamp so consumers can detect gaps.

### Single-Threaded Engine as a Correctness Guarantee

The engine's main loop processes one message at a time in a single thread.  There
are no locks, no shared mutable state, and no concurrent modifications.  Combo
status transitions, cascade-cancels, and session phase changes are all fully
serialised.  The price is that a long auction uncross blocks all other message
processing until it finishes — acceptable for an educational system, but a
production engine would decompose the critical path or use non-blocking event
dispatch.

### Deployment Topology & Trust Boundaries

EduMatcher is **partially multi-host by design**. The core is single-host; remote
reach is provided only through the external protocol gateways.

- **The engine is never partitioned.** There is exactly one authoritative matching
  engine. It cannot be sharded or run active/active — a second engine would be a
  second, divergent order book.
- **The internal ZMQ bus is loopback by default.** The engine binds
  `tcp://127.0.0.1` for `:5555/:5556/:5557` (and `pm-index` for `:5558/:5559`).
  These are **unauthenticated**: the PUSH socket accepts any `gateway_id` in the
  payload, and `ADMIN` is a payload-level role check, not transport authentication.
  The bus therefore MUST stay on a trusted host. The internal consumers (`pm-stats`,
  `pm-clearing`, `pm-audit`, viewers, `pm-index`, and the protocol-gateway
  processes) are expected to be **co-located** with the engine.
- **Remote participants connect at the gateways, not the bus.** The protocol
  gateways bind `0.0.0.0` and are the intended network edge:
  order entry over **ALF** (`pm-alf-gwy`, :5565) and **BALF** (`pm-balf-gwy`, :5560),
  which authenticate sessions against the `gateways.alf` allowlist; market data over
  **CALF** (`pm-md-gwy`, :5570) and post-trade over **RALF** (`pm-ralf-gwy`, :5580).
  A remote trading client or data consumer speaks TCP to one of these — it never
  touches the ZMQ bus.

```mermaid
flowchart LR
    subgraph Trusted["Trusted host (loopback ZMQ bus)"]
        ENG["pm-engine\n:5555/:5556/:5557"]
        OPS["pm-stats · pm-clearing · pm-audit · pm-index"]
        GWP["Gateway processes\npm-alf-gwy · pm-balf-gwy\npm-md-gwy · pm-ralf-gwy"]
        ENG <-->|ZMQ localhost| OPS
        ENG <-->|ZMQ localhost| GWP
    end
    RC["Remote order-entry clients"] -->|"ALF/BALF TCP :5565/:5560\n(authenticated)"| GWP
    RM["Remote data / post-trade consumers"] -->|"CALF/RALF TCP :5570/:5580"| GWP
```

The ZMQ bind host is overridable (`EDUMATCHER_ENGINE_HOST`,
`EDUMATCHER_INDEX_BIND_HOST`), which *can* place ZMQ consumers on another machine —
but doing so exposes the **unauthenticated** bus over the network and SHOULD only be
done on a private, trusted segment. The supported remote path is the gateways.



## Order Book Data Structures

### Visual: order depth at each price level

Before looking at the heap internals, here is what an order book actually looks like
from a market participant's perspective.  Each price level accumulates all the resting
orders placed at that price.  Time priority determines which order fills first within
a level.

```
        BID SIDE                            ASK SIDE
  (buyers waiting to buy)            (sellers waiting to sell)

  Price    Qty   Orders               Price    Qty   Orders
  ──────  ─────  ──────               ──────  ─────  ──────
  150.00   800     3    ◄── best bid  150.25   500     1    ◄── best ask
  149.75   650     2                  150.50   300     2
  149.50   200     1                  150.75   450     3
  149.25   500     2                  151.00   200     1
  149.00   300     1                  151.25   350     2

                    ▲                  ▲
                    └── SPREAD ────────┘
                       (150.25 - 150.00 = 0.25)
```

Reading this table:

- The **best bid** (150.00) and **best ask** (150.25) define the current spread.
- A MARKET BUY would consume the ask side top-down (best ask first): 500 @ 150.25,
  then 300 @ 150.50, etc., until its quantity is filled.
- A MARKET SELL would consume the bid side top-down: 800 @ 150.00, then 650 @ 149.75, etc.
- A LIMIT BUY at 150.10 would *not* cross the spread (best ask is 150.25 > 150.10),
  so it would rest on the bid side at a new level between 150.00 and 150.25.
- Within the 150.00 bid level, 3 separate orders are resting.  The order with the
  earliest timestamp fills first when a sell aggressor arrives.

The "Qty" column shows **total visible quantity** at that level.  Iceberg orders
only contribute their `visible_qty` (the current peak); the hidden reserve is
not shown.

### Internal representation

```
OrderBook (per symbol)
├── _bids        max-heap  [(-price, timestamp, order), ...]
├── _asks        min-heap  [( price, timestamp, order), ...]
├── _buy_stops   min-heap  [( stop_price, timestamp, order), ...]
├── _sell_stops   max-heap  [(-stop_price, timestamp, order), ...]
├── _order_index  dict[order_id → Order]   (all resting orders)
└── _entry_index  dict[order_id → HeapEntry] (bid/ask heap entries)
```

**Price-time priority**: within the same price level, earlier-submitted orders are filled first.
Lazy deletion is used — heap entries are marked invalid on cancel/fill and skipped on next access.



## Thread Model

Each process is **single-process, single-thread** for the main logic, with one optional background
thread for ZMQ receiving in interactive processes (gateway, viewer, orders, clearing).

The engine runs a single-threaded event loop using `zmq.Poller` with a 200 ms timeout,
making it safe from concurrent modification without locks.



## Core Matching Algorithm — In Depth

This section describes the exact data structures, algorithms, and time complexities
used by the matching engine.



### Order Book Organization

Each symbol gets its own `OrderBook` instance.  Internally it maintains **six primary data structures** organized for fast price-time-priority matching:

```
OrderBook("AAPL")
│
├── _bids          max-heap  [HeapEntry(-price, timestamp, order), ...]
├── _asks          min-heap  [HeapEntry( price, timestamp, order), ...]
│
├── _buy_stops     min-heap  [(stop_price, timestamp, order), ...]
├── _sell_stops    max-heap  [(-stop_price, timestamp, order), ...]
│
├── _bid_qty       dict[int, int]      price_ticks → total visible resting qty
├── _ask_qty       dict[int, int]      price_ticks → total visible resting qty
│
├── _order_index   dict[order_id, Order]       all resting orders (fast cancel lookup)
└── _entry_index   dict[order_id, HeapEntry]   heap entry pointers (lazy delete)
```

**Why heaps?**  Python's `heapq` gives us O(log n) insertion and O(1) peek at best price.
Since we always match against the best available price, a heap is the natural choice.

**Bids use negated prices** so that `heapq` (a min-heap) pops the *highest* bid first:

```python
# Bid key:  (-price, timestamp)  →  highest price wins, ties broken by earliest time
# Ask key:  ( price, timestamp)  →  lowest  price wins, ties broken by earliest time
```

**Price-level quantity indexes** (`_bid_qty`, `_ask_qty`) are auxiliary `dict[price, int]`
maps that track the aggregate visible quantity at each price level.  They enable O(p)
FOK pre-checks (where p = number of distinct price levels) instead of walking every
heap entry.



### Heap Entry and Lazy Deletion

Each heap entry is a wrapper object:

```python
@dataclass
class HeapEntry:
    key:   tuple       # (-price, ts) for bids; (price, ts) for asks
    order: Order
    valid: bool = True # set False on cancel/fill → "tombstone"
```

When an order is cancelled or filled, we do **not** remove it from the heap immediately
(which would require O(n) search + O(log n) sift).  Instead we mark `entry.valid = False`
(O(1)).  Stale entries are garbage-collected lazily when they bubble to the top during
`_peek()`:

```
┌────────────────────────────────────────────────────────┐
│               _asks min-heap                           │
│                                                        │
│   top → [100.0, t=1, VALID]  ← best ask                │
│          [100.0, t=3, INVALID]  ← tombstone, skipped   │
│          [101.5, t=2, VALID]                           │
│          [102.0, t=4, VALID]                           │
└────────────────────────────────────────────────────────┘

_peek() pops invalid entries until a valid one is at the top.
Amortized O(1) access to the best price.
```



### Matching Algorithm: The Sweep

The core of the matching engine is the `_sweep()` function.  It is called by
MARKET, LIMIT, FOK, and ICEBERG order types.

#### Pseudocode

```
function SWEEP(aggressor, opposite_heap, price_limit):
    while aggressor.remaining_qty > 0:
        best ← PEEK(opposite_heap)        // O(1) amortized (lazy GC)
        if best is None:
            break                          // no more resting orders
        if price_limit exists:
            if BUY  and best.price > price_limit: break
            if SELL and best.price < price_limit: break

        // Self-match prevention (SMP)
        if aggressor.gateway_id == best.gateway_id and SMP enabled:
            handle SMP action (cancel aggressor / resting / both)
            continue or return

        fill_qty   ← min(aggressor.remaining_qty, best.remaining_qty)
        fill_price ← best.price             // passive price wins (maker gets their price)

        APPLY_FILL(aggressor, best, fill_qty, fill_price)
```

#### Visual Flow

```
                 Incoming BUY LIMIT @ 101.0, qty=25
                              │
                              ▼
          ┌─────── ASKS HEAP (min-heap) ──────────┐
          │                                       │
          │  [100.0, t=1, qty=10]  ← best ask     │ ← fills 10 @ 100.0
          │  [100.5, t=2, qty=8 ]  ← next best    │ ← fills 8  @ 100.5
          │  [101.0, t=3, qty=20]  ← crosses      │ ← fills 7  @ 101.0
          │  [102.0, t=4, qty=5 ]  ← above limit  │ ← STOP: price > 101.0
          │                                       │
          └───────────────────────────────────────┘
                              │
                              ▼
          Result: 3 trades (10+8+7 = 25 filled), aggressor FILLED
```

#### Order-Type Dispatch

```
incoming order
      │
      ├─ MARKET  ──→ SWEEP(no price_limit) → discard unfilled remainder
      │
      ├─ LIMIT   ──→ SWEEP(price=order.price) → REST unfilled portion on own side
      │
      ├─ FOK     ──→ PRE-CHECK available qty via _bid_qty/_ask_qty
      │                 if insufficient → REJECT immediately
      │                 else → SWEEP(price=order.price)
      │
      ├─ ICEBERG ──→ SWEEP visible slice → replenish peak from hidden qty → REST
      │
      └─ STOP / STOP_LIMIT ──→ add to stop heap → no immediate match
                                 triggers later when last_trade_price crosses stop_price
```



### Apply Fill

When a match is found, `_apply_fill` performs these updates atomically:

```
function APPLY_FILL(aggressor, passive, fill_qty, fill_price):
    1. Create Trade object (symbol, buyer/seller, price, qty, timestamp)
    2. Update last_trade_price, last_buy/sell_price
    3. aggressor.remaining_qty -= fill_qty
       → status = FILLED if 0 else PARTIAL
    4. passive.remaining_qty   -= fill_qty
       → status = FILLED if 0 else PARTIAL
       → if FILLED: mark HeapEntry.valid = False (tombstone)
    5. Deduct fill_qty from price-level qty index (_bid_qty / _ask_qty)
    6. If passive is ICEBERG and displayed_qty exhausted:
       → replenish displayed_qty from hidden remainder
       → update timestamp (loses time priority — back of queue)
       → re-insert into heap with fresh key
```



### Stop Order Trigger Mechanism

Stop orders live in **separate heaps**, sorted by trigger price:

```
_buy_stops:  min-heap by ( stop_price, timestamp) — triggers when price RISES to/above
_sell_stops: max-heap by (-stop_price, timestamp) — triggers when price FALLS to/below
```

After every trade, `_check_stops()` peeks at both heaps:

```
function CHECK_STOPS(last_trade_price):
    triggered = []

    // BUY stops: sorted cheapest first; fire all where last_price >= stop
    while _buy_stops not empty:
        if top.stop_price > last_trade_price: break
        pop entry
        convert STOP → MARKET (or STOP_LIMIT → LIMIT)
        triggered.append(order)

    // SELL stops: sorted most expensive first; fire all where last_price <= stop
    while _sell_stops not empty:
        if top.stop_price < last_trade_price: break
        pop entry
        convert STOP → MARKET (or STOP_LIMIT → LIMIT)
        triggered.append(order)

    // Re-process each triggered order through the book
    for order in triggered:
        process(order)  → may produce additional trades → may trigger more stops (recursion)
```



### Resting an Order

When a LIMIT order does not fully cross the spread, its remainder is placed on the book:

```
function REST(order):
    if BUY:
        key = (-order.price, order.timestamp)   # negated → max-heap behavior
        heappush(_bids, HeapEntry(key, order))
        _bid_qty[order.price] += order.remaining_qty
    else:
        key = (order.price, order.timestamp)
        heappush(_asks, HeapEntry(key, order))
        _ask_qty[order.price] += order.remaining_qty

    _order_index[order.id] = order
    _entry_index[order.id] = entry
```



### Cancellation

```
function CANCEL(order_id):
    order = _order_index[order_id]          // O(1) lookup
    entry = _entry_index[order_id]          // O(1) lookup
    entry.valid = False                     // tombstone — O(1)
    deduct remaining qty from _bid_qty or _ask_qty
    order.status = CANCELLED
    return order
```

No heap restructuring needed — lazy deletion handles cleanup on next `_peek()`.



### Time Complexity Summary

| Operation | Complexity | Notes |
|-----------|-----------|-------|
| Insert (rest on book) | O(log n) | `heapq.heappush` |
| Best-price access | O(1) amortized | `_peek()` with lazy GC of tombstones |
| Match one level | O(log n) | Pop from heap |
| Full sweep (k fills) | O(k log n) | k = number of resting orders matched |
| Cancel | O(1) | Tombstone + dict lookup |
| FOK pre-check | O(p) | p = distinct price levels (via qty index) |
| Stop trigger check | O(k log s) | k triggered stops out of s total |
| Snapshot (book image) | O(n) | Walk all valid entries |
| Order lookup by ID | O(1) | `_order_index` dict |

Where **n** = total resting orders on one side of one book.



### Combo Orders — Data Structures and Tracking

Combo orders are **parent containers** that decompose into normal child orders.
The engine uses two dictionaries to track the parent-child relationship:

```
Engine
├── _combos           dict[combo_internal_id → ComboOrder]
└── _order_to_combo   dict[child_order_id → combo_internal_id]
```

A `ComboOrder` holds per-leg state:

```
ComboOrder
├── id                 str (internal UUID)
├── combo_id           str (user label)
├── gateway_id         str
├── combo_type         AON
├── tif                DAY | GTC
├── legs               list[ComboLeg]        (2–10 entries)
├── status             PENDING | PARTIALLY_MATCHED | MATCHED | FAILED | CANCELLED
├── child_order_ids    list[str]             (parallel to legs by index)
├── leg_fill_qty       dict[leg_index → int] (filled qty per leg)
└── leg_statuses       dict[leg_index → str] (OrderStatus.value per leg)
```

#### Combo Lifecycle State Machine

```mermaid
stateDiagram-v2
    [*] --> PENDING
    PENDING --> PARTIALLY_MATCHED : first leg fills
    PENDING --> CANCELLED : user cancel → cascade-cancel all legs
    PARTIALLY_MATCHED --> MATCHED : all legs filled
    PARTIALLY_MATCHED --> FAILED : any leg cancelled/expired → cascade-cancel siblings
    MATCHED --> [*]
    CANCELLED --> [*]
    FAILED --> [*]
```

#### Combo Entry Algorithm

```
function HANDLE_COMBO_ORDER(payload):
    combo = ComboOrder.from_dict(payload)

    // === Validation phase ===
    validate gateway auth                            O(1)
    validate 2 ≤ legs ≤ 10                          O(1)
    validate no duplicate symbols                    O(L) where L=leg count
    validate all symbols in allowlist                O(L)
    validate each leg (qty > 0, price if needed)    O(L)

    ACK combo to gateway

    // === Child order creation phase ===
    for i, leg in enumerate(combo.legs):             O(L)
        child = Order.create(from leg fields)
        child.combo_parent_id = combo.id
        child.leg_index = i

        combo.child_order_ids.append(child.id)       O(1)
        _order_to_combo[child.id] = combo.id         O(1)
        _order_symbol[child.id]   = leg.symbol       O(1)

        trades, events = book.process(child)         O(k log n) per leg

        // Publish fills/rejects for immediate matches
        for event in events:
            publish fill/reject messages

        combo.leg_statuses[i] = child.status.value
        combo.leg_fill_qty[i] = filled amount

    _combos[combo.id] = combo                        O(1)
    UPDATE_COMBO_STATUS(combo)                       O(L)
```

#### Combo Status Update (after any child event)

```
function CHECK_COMBO_AFTER_CHILD_EVENT(child_order):
    combo_id = _order_to_combo[child_order.id]       O(1)
    combo    = _combos[combo_id]                     O(1)

    idx = child_order.leg_index
    combo.leg_statuses[idx] = child_order.status
    combo.leg_fill_qty[idx] = filled amount

    if child_order.status in (CANCELLED, EXPIRED):
        CASCADE_CANCEL(combo, FAILED)                O(L)
        return

    UPDATE_COMBO_STATUS(combo)                       O(L)

function UPDATE_COMBO_STATUS(combo):
    if all leg_statuses == FILLED:                   O(L)
        combo.status = MATCHED
        publish combo.status MATCHED
    elif any leg has PARTIAL or FILLED fill:
        combo.status = PARTIALLY_MATCHED
        publish combo.status PARTIALLY_MATCHED
```

#### Cascade Cancel

```
function CASCADE_CANCEL(combo, terminal_status):
    combo.status = terminal_status

    for child_id in combo.child_order_ids:           O(L)
        symbol = _order_symbol[child_id]             O(1)
        book   = books[symbol]                       O(1)
        book.cancel_order(child_id)                  O(1) — tombstone
        publish order.cancelled
        remove from _order_symbol, _order_to_combo   O(1)

    publish combo.status
```

#### Combo Event Propagation Flow

```
  ┌─────────────────────────────────────────────────────────────────────┐
  │                       MATCHING ENGINE                               │
  │                                                                     │
  │   incoming order ──► OrderBook.process()                            │
  │         │                    │                                      │
  │         │              fills/trades                                 │
  │         │                    │                                      │
  │         ▼                    ▼                                      │
  │   publish fill       was this a combo child?                        │
  │   publish trade       │                                             │
  │                       ├── NO  → done                                │
  │                       └── YES → _check_combo_after_child_event()    │
  │                                      │                              │
  │                         ┌────────────┴────────────┐                 │
  │                         │                         │                 │
  │                    child FILLED?            child CANCELLED?        │
  │                         │                         │                 │
  │                         ▼                         ▼                 │
  │                  update leg_fill_qty       CASCADE_CANCEL           │
  │                  update leg_statuses         │                      │
  │                         │                    ├── cancel siblings    │
  │                         ▼                    └── publish FAILED     │
  │                  all legs FILLED?                                   │
  │                    │          │                                     │
  │                   YES         NO                                    │
  │                    │          │                                     │
  │                    ▼          ▼                                     │
  │              publish      publish                                   │
  │              MATCHED    PARTIALLY_MATCHED                           │
  │                                                                     │
  └─────────────────────────────────────────────────────────────────────┘
```

#### Combo Time Complexity Summary

| Operation | Complexity | Notes |
|-----------|-----------|-------|
| Validate combo | O(L) | L = leg count (2–10, bounded constant) |
| Create & post all children | O(L × k log n) | k matches per leg |
| Lookup child→combo parent | O(1) | `_order_to_combo` dict |
| Update combo status | O(L) | Iterate leg_statuses |
| Cascade-cancel | O(L) | One tombstone per child |
| Combo cancel by user | O(L) | Lookup by combo_id is O(C) worst-case* |

\* User-facing cancel searches `_combos` by `combo_id` string (not internal UUID).
With C active combos, worst-case is O(C).  In practice C is small and could be
indexed if needed.

Since L is bounded at 10, all combo-specific operations are effectively **O(1)** in
big-O terms relative to book size n.



### Session State Machine

The engine manages a session state that controls which order types are accepted and
whether matching occurs.  The scheduler process drives transitions by sending
`session.transition` messages.

#### States and Transitions

```mermaid
stateDiagram-v2
    [*] --> PRE_OPEN
    PRE_OPEN --> OPENING_AUCTION : session.transition
    PRE_OPEN --> CONTINUOUS : session.transition (shortcut)
    OPENING_AUCTION --> CONTINUOUS : uncross all books + expire ATO orders
    CONTINUOUS --> CLOSING_AUCTION : session.transition
    CONTINUOUS --> CLOSED : session.transition (shortcut)
    CLOSING_AUCTION --> CLOSED : uncross all books + expire ATC orders
    CLOSED --> [*]
```

#### Phase Behavior

| Phase | Matching? | Accepts | Rejects |
|-------|-----------|---------|---------|
| PRE_OPEN | No | LIMIT, STOP, STOP_LIMIT, ICEBERG | MARKET, FOK, IOC, ATO, ATC |
| OPENING_AUCTION | No | Same as PRE_OPEN + ATO | MARKET, FOK, IOC, ATC |
| CONTINUOUS | Yes | All types | ATO, ATC |
| CLOSING_AUCTION | No | Same as PRE_OPEN + ATC | MARKET, FOK, IOC, ATO |
| CLOSED | — | Nothing | All |

During no-matching phases, accepted orders rest on the book but the sweep is never called.
Stop orders are stored but do not fire (no trades occur to trigger them).

#### Handling a Transition

```
function HANDLE_SESSION_TRANSITION(to_state):
    if transition not in VALID_TRANSITIONS[current_state]:
        log warning, ignore
        return

    prev_state = current_state
    current_state = to_state

    // If exiting an auction phase → uncross all books
    if prev_state in (OPENING_AUCTION, CLOSING_AUCTION):
        for each symbol book:
            UNCROSS(book)

    // Expire phase-specific orders
    if prev_state == OPENING_AUCTION:
        expire all ATO orders → publish order.expired
    if prev_state == CLOSING_AUCTION:
        expire all ATC orders → publish order.expired

    publish session.state { state, prev_state }
```



### Auction Uncross Algorithm — Equilibrium Price

When exiting an auction phase, accumulated orders execute at a **single equilibrium price**.
This is the price that maximizes total traded quantity.

#### Algorithm

```
function UNCROSS(book):
    // 1. Collect all candidate prices (every distinct bid and ask price)
    candidates = sorted(unique(bid_prices ∪ ask_prices))

    best_price    = None
    best_exec_qty = 0
    best_surplus  = ∞

    // 2. Evaluate each candidate
    for P in candidates:
        buy_qty  = Σ resting bid qty where bid_price ≥ P
        sell_qty = Σ resting ask qty where ask_price ≤ P
        exec_qty = min(buy_qty, sell_qty)
        surplus  = |buy_qty − sell_qty|

        // 3. Selection: maximize exec_qty, then minimize surplus, then lowest price
        if exec_qty > best_exec_qty:
            best_price, best_exec_qty, best_surplus = P, exec_qty, surplus
        elif exec_qty == best_exec_qty and surplus < best_surplus:
            best_price, best_exec_qty, best_surplus = P, exec_qty, surplus
        elif exec_qty == best_exec_qty and surplus == best_surplus and P < best_price:
            best_price = P

    if best_exec_qty == 0:
        publish auction.result { eq_price: null, eq_qty: 0 }
        return

    // 4. Execute: fill orders at equilibrium price using price-time priority
    remaining = best_exec_qty
    while remaining > 0:
        // match best bid against best ask, fill_price = best_price
        best_bid = PEEK(bids)
        best_ask = PEEK(asks)
        fill_qty = min(best_bid.remaining, best_ask.remaining, remaining)
        APPLY_FILL(best_bid, best_ask, fill_qty, best_price)
        remaining -= fill_qty

    publish auction.result { eq_price, eq_qty, trades_count, imbalance_side, imbalance_qty }
```

**Key difference from continuous matching**: In continuous mode, each fill happens at the
**resting** order's price (price improvement for the aggressor).  In auction uncross, ALL
fills happen at the same computed equilibrium price — neither the bid's limit nor the ask's
limit is used directly.

#### Complexity

| Operation | Complexity | Notes |
|-----------|-----------|-------|
| Collect candidates | O(n) | Scan all resting orders |
| Evaluate all candidates | O(p × n) | p prices × n cumulative sums (optimizable to O(n) with prefix sums) |
| Execute fills | O(k log n) | k fills at equilibrium price |

Where p = distinct price levels, n = total resting orders, k = orders matched.



### Gateway Authentication

Before a gateway can submit orders, it must authenticate with the engine.
If the engine has a `gateways.alf` section in its config, only listed gateway IDs are accepted.

```mermaid
sequenceDiagram
    participant G as Gateway
    participant E as Engine

    G->>E: system.gateway_connect {gateway_id: "GW01"}
    Note over G,E: PUSH -> PULL
    Note over E: check config allowlist
    E-->>G: system.gateway_auth.GW01 {accepted: true, description: "..."}
    Note over E,G: PUB -> SUB
    G->>E: order.new (now allowed)
```

If `accepted: false`, the gateway prints the rejection reason and exits.
If no `gateways.alf` section exists in config, all gateway IDs are auto-accepted
(backward-compatible mode).

Orders from gateways that have not completed the auth handshake are rejected with
reason "Gateway not connected: {GW_ID}".



### Engine Event Loop

The engine processes messages sequentially in a single thread:

```
function RUN():
    restore_gtc()          // reload GTC orders + combos from disk
    load_config()          // seed stats, inject MM orders

    loop:
        poll PULL socket (200 ms timeout)

        if message available:
            topic, payload = decode(message)
            dispatch:
                "order.new"              → _handle_new_order(payload)
                "order.cancel"           → _handle_cancel(payload)
                "order.combo"            → _handle_combo_order(payload)
                "order.combo_cancel"     → _handle_combo_cancel(payload)
                "session.transition"     → _handle_session_transition(payload)
                "system.gateway_connect" → _handle_gateway_connect(payload)
                "system.symbols_request" → _handle_symbols_request(payload)
                "book.snapshot_request"  → _handle_snapshot_request(payload)
                "order.orders_request"   → _handle_orders_request(payload)

        flush_snapshots()  // publish throttled book images for dirty symbols

        if shutdown requested:
            _shutdown()    // save GTC, expire DAY, save combos, publish EOD
            break
```

No locks, no shared memory, no race conditions.  The sequential dispatch guarantees
that combo status transitions and cascade-cancels are atomic from the system's
perspective.



## Persistence & Crash Recovery

The engine holds the authoritative order book **in memory**. Durability is provided
by two independent tiers: engine **state files** written at shutdown and reloaded at
startup, and subscriber **data stores** written continuously during the session.

| File / store | Written by | Cadence | Survives restart? | Purpose |
|---|---|---|---|---|
| `gtc_orders.json` | engine | clean shutdown | reloaded at startup | resting GTC orders (price-time priority preserved) |
| `gtc_combos.json` | engine | clean shutdown | reloaded at startup | resting GTC combo parents + child links |
| `book_stats.json` | engine | clean shutdown | reloaded at startup | last buy/sell price per symbol; reseeds collar & circuit-breaker references at the next open |
| `stats.db` (SQLite) | pm-stats | per trade · snapshot every 15 min · EOD | accumulates | OHLCV, intraday snapshots, trade log |
| `clearing.db` (SQLite) | pm-clearing | per trade · connect/disconnect · EOD | accumulates | positions, VWAP, realised/unrealised P&L |
| `audit.log` | pm-audit | continuous (rotating) | accumulates | full chronological event trail |
| `indexes/<ID>_{history.jsonl,state.json}` | pm-index | throttled + EOD / on update | accumulates | index history and restart state |

(Full field-level detail is in the user guide's
[Persistence chapter](../user-guide/180-persistence.md#data-files-at-a-glance).)

**Shutdown is an ordered sequence**, not a hard stop — this is what makes GTC
recovery and clean consumer flush possible:

```mermaid
sequenceDiagram
    autonumber
    participant OP as Operator (Ctrl-C / SIGINT)
    participant ENG as Engine
    participant DISK as State files
    participant SUB as Subscribers
    OP->>ENG: SIGINT
    ENG->>DISK: serialise resting GTC orders + combos
    ENG->>DISK: write book_stats.json (last prices, seed flags)
    ENG-->>SUB: PUB order.expired for all DAY/ATO/ATC orders
    ENG-->>SUB: PUB system.eod (flush-and-stop signal)
    ENG->>ENG: close sockets
    Note over SUB: stats/clearing/audit flush their stores and exit
```

At startup the engine reloads `gtc_orders.json` / `gtc_combos.json`, restoring each
order **with its original timestamp** so queue priority is unchanged, and reseeds
each symbol's collar and circuit-breaker reference from `book_stats.json`.

**Idempotency and gap detection** guard the accumulating stores: trade events are
inserted with `INSERT OR IGNORE` on trade id, so a replayed or duplicated event is
harmless; the drop-copy feed carries a monotonic sequence number and CALF carries a
per-`(channel,symbol)` sequence so consumers can detect and replay gaps.

**What is *not* durable.** Messages in flight in ZMQ queues are lost on a hard kill
(only a clean SIGINT runs the sequence above). DAY orders are intentionally dropped
at shutdown. Trade IDs are a per-session monotonic counter that **resets to 1** on
restart (`models/trade.py`), so trade-id uniqueness is *within a session only* —
merging logs across sessions requires a session prefix. A `SIGKILL` skips GTC
serialisation entirely, losing the resting book.



## Failure Modes & Fault Tolerance

The system's resilience is dominated by two facts: there is **one** engine (a single
point of failure by design), and the internal bus uses **ZeroMQ default flow
control**, which behaves very differently for the two socket patterns.

### Back-pressure: PUSH blocks, PUB drops

```mermaid
flowchart TD
    A[Producer wants to send] --> B{Socket type}
    B -->|PUSH → PULL :5555| C{Receiver queue full\nat high-water mark?}
    C -->|no| C2[send immediately]
    C -->|yes| D[PUSH blocks the sender\n→ natural back-pressure]
    B -->|PUB → SUB :5556/:5557/:5558| E{Subscriber queue full\nat high-water mark?}
    E -->|no| E2[deliver a copy]
    E -->|yes| F[PUB DROPS the message\nfor that slow subscriber — silently]
```

- **Order entry (PUSH/PULL, :5555):** if the engine falls behind, a gateway's PUSH
  **blocks** until space frees up. This is benign back-pressure — order submitters
  slow down; nothing is lost.
- **Event fan-out (PUB/SUB, :5556/:5557/:5558):** if any subscriber can't drain fast
  enough, ZeroMQ **discards** messages for *that* subscriber once its high-water mark
  is reached. The loss is **silent** — there is no error, no gap signal from ZMQ
  itself.

`messaging/bus.py` creates sockets with **default** options — no explicit
`SNDHWM`/`RCVHWM`, `LINGER`, or `CONFLATE` are set. So the effective HWM is ZeroMQ's
default (~1000 messages per socket).

!!! warning "Silent loss to internal stateful consumers — recommended change"
    This default-drop behaviour was **inherited, not deliberately chosen**. It is
    acceptable for viewers (which only ever need the *latest* book) but is a real
    correctness risk for the **stateful internal consumers that have no replay path**
    — `pm-clearing` (P&L), `pm-stats` (OHLCV), and `pm-audit` (the compliance log).
    Under sustained back-pressure these can miss `trade.executed` events and silently
    diverge, with no gap to detect.

    Recommended, in order:

    1. **Make it explicit and observable.** Set generous `RCVHWM` on the internal SUB
       consumers and monitor ZeroMQ's drop counters; a silent gap should become a
       visible alarm.
    2. **Protect the stateful consumers.** For `pm-clearing`/`pm-audit`, prefer a
       larger queue plus a slow-consumer alarm, or consume via the sequenced feeds
       (drop-copy / RALF) that support replay, rather than the best-effort `:5556`
       broadcast.
    3. **Conflate the viewers.** `pm-viewer`/`pm-board` only need current state —
       `zmq.CONFLATE` (keep only the newest message) removes them as a back-pressure
       source entirely.

    Reliable, replay-backed delivery already exists on the **external** edges (CALF
    `replay_window_sec`, RALF `replay_retention_sec`, drop-copy's 10k in-memory
    buffer); the gap is on the internal broadcast bus.

### Other failure modes

| Trigger | Effect | Mitigation / current behaviour |
|---------|--------|--------------------------------|
| Slow / stalled subscriber | PUB drops its messages at HWM (silent) | see recommendation above; external feeds replay |
| Engine crash (hard) | whole exchange down; in-flight + DAY orders + resting book lost (no GTC flush) | single-writer SPOF by design; no HA. Clean SIGINT preserves GTC |
| Engine restart (clean) | DAY orders expire; GTC/combos restored; trade-id counter resets to 1; subscribers reconnect automatically | ordered shutdown + startup reload |
| Subscriber crash | isolated — engine and other consumers unaffected | reconnects and resumes; may have a gap (replay if supported) |
| Gateway disconnect | per-gateway `disconnect_behaviour` (`CANCEL_QUOTES_ONLY` default / `CANCEL_ALL` / `LEAVE_ALL`) | configured per gateway |
| Wall-clock regression | none — priority tie-break stays strictly increasing | `now_ns()` monotonic guarantee |
| Drop-copy port (:5557) in use | engine logs a warning and runs **without** the drop-copy feed | deliberate: a port conflict must not stop matching |
| Long auction uncross | blocks all message processing until it finishes | acceptable for teaching; single-thread trade-off |



## Performance Optimizations

A sequence of pure-Python changes (no C extensions, no Cython, no multiprocessing)
raised single-thread throughput by roughly **2.8×**. This section explains each
technique and *why* it works.

!!! warning "Throughput is strongly CPU-architecture dependent"
    The headline "after" figure of **~160,000 orders/second** is measured on
    **ARM (Apple Silicon)**. The identical code on a typical **Intel x86** desktop
    reaches roughly **~80,000 orders/second** — about half. The "before" baseline
    (~57,000/s) and the latency table below are ARM figures. Treat all absolute
    numbers as *illustrative of the relative gains*, not as a portable benchmark;
    see [Why ARM and Intel differ so much](#why-arm-and-intel-differ-so-much).


### How to read the numbers

Every number below was measured with the engine running in a single thread,
processing orders through the full hot path (deserialize → validate → match →
build messages → publish).  "µs" means microseconds (one millionth of a second).



###  `__slots__` on hot-path classes

**What it does:**  By default, Python objects store their attributes in a hidden
dictionary (`__dict__`).  When you add `__slots__ = ('x', 'y')` to a class,
Python stores attributes in a fixed-size C array instead.

**Why it's faster:**

- Attribute access goes from a hash-table lookup (~60–80 ns) to a direct offset
  lookup (~30 ns) — roughly 2× faster per access.
- Each instance uses ~40% less memory (no per-object dict allocation), which
  means less work for the garbage collector.

**Where we applied it:**

- `Order` (the most common object — one per incoming request)
- `Trade` (one per fill)
- `_HeapEntry` (internal wrapper — thousands live on the book at once)
- `OrderBook` (only a few instances, but accessed on every single order)

**Before/after for a dataclass:**

```python
# Before
@dataclass
class Order:
    id: str
    symbol: str
    ...

# After — just add slots=True
@dataclass(slots=True)
class Order:
    id: str
    symbol: str
    ...
```

For classes that aren't dataclasses (like `_HeapEntry`), you define it manually:

```python
class _HeapEntry:
    __slots__ = ('key', 'order', 'valid')

    def __init__(self, key, order, valid=True):
        self.key   = key
        self.order = order
        self.valid = valid
```

**Drawbacks:**  You can no longer add arbitrary attributes at runtime (e.g.
`order.debug_tag = "test"` will raise `AttributeError`).  Multiple inheritance
becomes tricky — all parent classes must also declare `__slots__` or you lose
the benefit.  Adding a new field requires updating the `__slots__` tuple, which
is easy to forget.



###  Fast enum lookup dictionaries

**What it does:**  Replaces `Side("BUY")` with a pre-built dictionary lookup
`_SIDE_MAP["BUY"]`.

**Why it's faster:**  Python's `Enum(value)` constructor iterates through *all*
members comparing each string (~600–800 ns).  A dictionary lookup is ~50 ns.
With 5 enums per order, this saves ~3 µs per deserialization call.

```python
# Build once at module load time
_SIDE_MAP = {v.value: v for v in Side}      # {"BUY": Side.BUY, "SELL": Side.SELL}
_TYPE_MAP = {v.value: v for v in OrderType}

# Then in from_dict():
side = _SIDE_MAP[d["side"]]   # ~50 ns instead of Side("BUY") at ~700 ns
```

**Drawbacks:**  If you add a new enum member, you must remember that the lookup
dict was built at import time — it won't automatically include the new member
unless you rebuild it.  Also, an invalid value like `_SIDE_MAP["INVALID"]` raises
a `KeyError` instead of the more descriptive `ValueError` that `Side("INVALID")`
would give, making debugging slightly harder.



###  Single timestamp call per order (cached nanosecond clock)

**What it does:**  Reads the clock once at the top of the hot path and passes the
result (`now`, an integer nanosecond value) down to every function that needs a
timestamp.

**Why it's faster:**  reading the clock is a system call — it crosses from Python
into the OS kernel and back (~300–500 ns). A single aggressive order that triggers
stops could read it 4–6 times. Caching it means we pay the cost exactly once.

The ordering-critical timestamp is `now_ns()` (`models/clock.py`) — a wrapper over
`time.time_ns()` that guarantees a **strictly increasing** integer nanosecond value
(it never returns a duplicate or a value that went backwards, even if the wall
clock does). `now_ns()` takes a lock to enforce that guarantee across threads; on
the engine's single-threaded order loop the hot path calls `time.time_ns()`
**directly**, bypassing the lock, because ties are already impossible within one
run-to-completion order.

```python
def _handle_new_order(self, payload):
    now = now_ns()                       # one clock read, int nanoseconds
    ...
    trades, events = book.process(order, now=now)  # passed through

# Inside the order book:
def _apply_fill(self, aggressor, passive, qty, price, trades, events, now):
    trade = Trade.create(..., now=now)   # reuses cached timestamp
```

**Drawbacks:**  All fills and stop triggers within the same order share the exact
same timestamp, even if matching takes a few microseconds — you lose sub-microsecond
sequencing *within* a single order (across orders, monotonicity still holds). It
also pollutes function signatures — every internal method carries an extra `now`
parameter, making the code slightly harder to read and test.



###  Monotonic integer trade IDs (replacing `uuid4()`)

**What it does:**  Generates trade IDs as sequential integers (`1`, `2`, `3`, ...)
instead of random UUIDs.

**Why it's faster:**  `uuid.uuid4()` reads from `/dev/urandom` (a kernel call) and
then formats 128 random bits into a hyphenated string — total cost ~1.5 µs.
`next(counter)` is a pure-Python operation costing ~30 ns.

```python
import itertools

_trade_counter = itertools.count(1)

@classmethod
def create(cls, ...):
    return cls(id=str(next(_trade_counter)), ...)
```

> Trade IDs only need to be unique within a single engine session, not globally,
> so a monotonic counter is safe here.

**Drawbacks:**  IDs are no longer globally unique — if you restart the engine,
counter resets to 1 and old trade IDs may collide with new ones.  This makes it
unsafe to merge trade logs from multiple sessions without adding a session prefix.
Also, sequential IDs leak information (e.g. competitors can estimate your trade
volume by observing the ID gap between two of their fills).



###  `orjson` instead of stdlib `json`

**What it does:**  Replaces `json.dumps(payload).encode()` with `orjson.dumps(payload)`.

**Why it's faster:**  `orjson` is a C-extension JSON serializer that:

- Encodes directly to `bytes` (no intermediate `str` → `.encode()` step)
- Uses SIMD instructions for string escaping
- Is ~9× faster than stdlib json for typical 10-key dictionaries

| Serializer | Cost per call |
|------------|--------------|
| `json.dumps().encode()` | ~2,100 ns |
| `orjson.dumps()` | ~230 ns |

With 2–4 messages published per order, this alone saved ~4–7 µs on aggressive
orders.

```python
try:
    import orjson
    def _dumps(obj): return orjson.dumps(obj)
except ImportError:
    import json
    def _dumps(obj): return json.dumps(obj).encode()
```

The fallback ensures the code works in environments where `orjson` isn't
installed — it just runs slower.

**Drawbacks:**  Adds a third-party dependency (`orjson`) that must be installed
and kept updated.  `orjson` is stricter than stdlib `json` — it rejects `NaN`,
`Infinity`, and non-string dict keys that stdlib silently accepts.  If your
payloads ever contain these edge cases, you'll get a `TypeError` at runtime.
The library is also platform-specific (compiled C/Rust), so it may not be
available on all architectures (e.g. some Alpine Docker images).



###  Eliminate redundant serialization (`to_dict()` removal)

**What it does:**  Instead of calling `order.to_dict()` to build a full 18-key
dictionary and then passing it to a message function, we build only the keys the
message actually needs, directly from object attributes.

**Why it's faster:**  `to_dict()` unconditionally copies all 18 fields and calls
`.value` on every enum — cost ~3–4 µs.  The ack message only needs 6 of those
fields.  Building a minimal dict inline costs ~250 ns.

```python
# Before — wasteful
self.pub_sock.send_multipart(
    make_fill_msg(evt.gateway_id, evt.id, ..., order=evt.to_dict())
)

# After — only the fields the consumer needs
self.pub_sock.send_multipart([
    fill_topic_bytes,
    _dumps({
        "order_id": evt.id,
        "fill_qty": evt.quantity - evt.remaining_qty,
        "status":   evt.status.value,
        ...
    }),
])
```

**Drawbacks:**  The message schema is now implicitly defined at each call site
instead of in one canonical `to_dict()` method.  If a downstream consumer adds a
field requirement, you need to find and update every inline dict that builds that
message type.  Forgetting one is a subtle bug.  It also makes writing integration
tests harder — you can't just mock `to_dict()` and check its output.



###  Inlined message construction

**What it does:**  Bypasses helper functions like `make_ack_msg()` and builds the
two-frame ZMQ message (`[topic_bytes, payload_bytes]`) directly at the call site.

**Why it's faster:**  Each helper function allocates a dict, conditionally merges
fields via `.update()`, then calls `encode()` which does *another* function call.
That's 3 function calls + 2 dict allocations.  Inlining collapses all of that
into a single dict literal + one `orjson.dumps()`:

| Approach | Cost |
|----------|------|
| `make_ack_msg(...)` | ~950 ns |
| Inlined with `_dumps()` | ~450 ns |

**Drawbacks:**  Code duplication — the message format is now repeated at each
call site instead of living in one helper.  If the message protocol changes
(e.g. adding a `"version"` field to all messages), you must update every inline
construction point.  The engine code also becomes longer and denser, making
code reviews harder.  For low-frequency messages (rejects, cancels), the savings
are negligible and the readability cost isn't justified.



###  Pre-cached topic bytes

**What it does:**  ZMQ topic strings like `"order.ack.GW01"` are the same for every
message sent to a given gateway.  We encode them once and store the `bytes` in a
dictionary, avoiding repeated `f"order.ack.{gw}".encode()` calls.

**Why it's faster:**  `f-string + .encode()` costs ~100 ns per call.  With 3–4
messages per order, that's ~300–400 ns wasted on creating the same bytes.  A dict
lookup is ~50 ns total.

```python
# Populate on first use
self._topic_cache[gw] = f"order.ack.{gw}".encode()

# Hot path
topic = self._topic_cache[gw]  # ~50 ns instead of ~100 ns
```

**Drawbacks:**  The cache grows unboundedly — if gateways connect and disconnect
frequently with unique IDs, the dict accumulates stale entries (a minor memory
leak).  In practice this is a non-issue since gateway IDs are static, but in a
general-purpose system you'd want eviction logic.  It also adds a layer of
indirection that can confuse readers unfamiliar with the pattern.



###  Local variable caching in tight loops

**What it does:**  Before entering the matching loop, we copy frequently-accessed
object attributes into local variables.

**Why it's faster:**  In CPython, local variable access (`LOAD_FAST` bytecode) is a
direct array-index operation (~30 ns).  Attribute access (`LOAD_ATTR`) involves a
descriptor lookup even with `__slots__` (~50–70 ns).  In a loop that runs 5–50
iterations, this adds up.

```python
def _sweep(self, aggressor, opposite_heap, ...):
    # Cache once before the loop
    _side       = aggressor.side         # LOAD_FAST inside loop
    _smp_action = aggressor.smp_action
    _peek       = self._peek             # avoid self.__dict__ lookup per iteration

    while aggressor.remaining_qty > 0 and opposite_heap:
        best = _peek(opposite_heap)      # local call, not self._peek(...)
        if _side == Side.BUY and best.price > price_limit:
            break
        ...
```

**Drawbacks:**  Makes the code less obvious — a reader seeing `_peek(heap)` has
to scroll up to understand it's actually `self._peek`.  If the cached attribute
is mutable and gets reassigned on `self` during the loop (unlikely here, but
possible in other contexts), the local copy becomes stale and introduces bugs.
Debugging is also harder because inspecting `self._peek` in a debugger won't
show the value actually used inside the loop.



###  `__new__` for fast deserialization

**What it does:**  Uses `object.__new__(cls)` + direct slot writes instead of
calling the dataclass-generated `__init__` with 19 keyword arguments.

**Why it's faster:**  CPython's function-call machinery needs to parse and bind
each keyword argument — with 19 kwargs this alone costs ~400 ns.  `__new__`
creates a bare instance in ~80 ns, and then each `o.field = value` is a simple
`STORE_ATTR` (~30 ns with slots).

```python
@classmethod
def from_dict(cls, d: dict) -> "Order":
    o = object.__new__(cls)
    o.id         = d["id"]
    o.symbol     = d["symbol"]
    o.side       = _SIDE_MAP[d["side"]]
    ...
    return o
```

**Drawbacks:**  Completely bypasses `__init__`, so any validation, default value
assignment, or `__post_init__` logic in the dataclass is skipped.  If you later
add a new field with a default value to the dataclass, `from_dict` won't
automatically pick it up — you'll get an `AttributeError` on first access.
This pattern also breaks the implicit contract that dataclass instances are
always fully initialized, which can confuse static analysis tools like mypy.



### Summary

| # | Technique | Savings per order | Applies to |
|---|-----------|-------------------|------------|
| 1 | `__slots__` | ~1.5–2 µs | All hot-path objects |
| 2 | Enum lookup dicts | ~3 µs | `Order.from_dict()` |
| 3 | Cached timestamp | ~1–2 µs | Fills + stop triggers |
| 4 | Monotonic trade IDs | ~1.5 µs | Every fill |
| 5 | `orjson` | ~4–7 µs | Every published message |
| 6 | No redundant `to_dict()` | ~3 µs | Ack + fill messages |
| 7 | Inlined messages | ~500 ns | Ack + fill + trade |
| 8 | Pre-cached topic bytes | ~300 ns | All messages |
| 9 | Local var caching | ~200–800 ns | Sweep loop |
| 10 | `__new__` deserialization | ~400 ns | `Order.from_dict()` |

**Result:**

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Throughput | 57,000 TPS | 160,000 TPS | **+180%** |
| Median latency | 23.5 µs | 8.5 µs | **−64%** |
| P90 latency | 25.7 µs | 10.0 µs | **−61%** |

All of these improvements are **pure Python** — no C extensions, no multi-threading,
no unsafe hacks.  The key insight is that in a tight loop, small costs (100 ns here,
200 ns there) compound rapidly.  At ~160,000 orders/second (ARM), each order has a
budget of only **6.25 µs** — every nanosecond matters. On Intel x86 the budget is
roughly double (~12.5 µs at ~80,000/s), because the per-order work is the same but
each interpreter step is slower (below).

### Why ARM and Intel differ so much

The **same code** runs ~2× faster on Apple Silicon (ARM) than on a typical Intel
x86 desktop. This is a property of the *workload* — a CPython bytecode interpreter
doing pointer-chasing and small-object allocation — meeting two very different
microarchitectures. The dominant hypotheses (in rough order of expected impact;
confirming the split requires profiling, e.g. `perf stat` on each host):

| Factor | Why it favours Apple Silicon |
|--------|------------------------------|
| **Interpreter dispatch** | CPython's eval loop is a giant computed-goto over bytecodes — a torrent of hard-to-predict indirect branches. Apple's very wide decode and large branch-prediction resources swallow this better than mainstream x86 desktop parts. |
| **Memory latency & cache** | Refcounting and dict/attribute lookups are latency-bound pointer chases. Apple Silicon's on-package unified memory and large L1/L2 (and huge SLC) cut the average miss cost that this workload pays constantly. |
| **Single-thread IPC / clocks** | The engine is single-threaded, so only 1-core performance matters. High-IPC M-series cores at competitive clocks beat many Intel desktop cores on this specific scalar, branchy, allocation-heavy code. |
| **Refcount write traffic** | Every `INCREF`/`DECREF` is a small write; Apple's store buffering and cache bandwidth absorb the churn with less stall. |
| **Native library codegen** | `orjson` (Rust) and the Python build itself may be compiled with better-tuned codegen / SIMD paths on `arm64` than the x86 wheels in use. |

Two caveats. First, "Intel" and "ARM" are not monolithic: a recent high-clock
Xeon/Core will close much of the gap versus an older desktop part, and the numbers
here compare the specific machines used. Second, the *relative* speedups of the ten
techniques above are stable across both architectures — only the absolute TPS moves.
If you publish throughput figures, always state the CPU.

## Configuration Choices That Impact Performance

Several config values are not just feature toggles — they directly set the system's
work rate, memory footprint, and back-pressure thresholds. The most important is the
market-data throttle.

| Setting | Where | Default | Performance effect |
|---------|-------|---------|--------------------|
| `snapshot_interval_sec` | engine config | `0.5` | **Dominant market-data lever.** Caps how often `book.{SYM}` / `depth.{SYM}` are published per symbol. Lower = fresher books but more messages, more serialisation, and more downstream CPU across every subscriber and bridge. The floor is the engine poll tick. |
| Engine poll timeout | `engine/main.py` const | `200 ms` | Upper bound on idle→snapshot latency and on how often circuit-breaker resume timers are checked. Also the effective minimum snapshot cadence. |
| `market_data_gateway.depth_levels` | CALF | `10` | Bytes per `DEPTH`/`SNAP` line. Combined with a `SYM=*` wildcard subscription, multiplies per-client bandwidth by the symbol count. |
| `*.max_client_queue` | all gateways | `10000` | Per-client outbound backlog before `SLOW_CLIENT`/drop; also the per-client memory ceiling. |
| `market_data_gateway.replay_window_sec` · `post_trade_gateway.replay_retention_sec` | CALF / RALF | `30` · `86400` | Replay reach vs replay-buffer memory. |
| `*.heartbeat_interval_sec` · `*.idle_timeout_sec` | all gateways | varies | Idle-traffic volume vs dead-peer detection latency. |
| `*.max_commands_per_second` · `*.max_messages_per_second` · `api rate_limit` | ALF / BALF / API | `100` · `100` · `10` | Ingress throttles that protect the single-threaded engine from a runaway client. |
| ZeroMQ high-water marks | `messaging/bus.py` | **unset (ZMQ default ≈1000)** | Governs when PUB silently drops to slow subscribers and when PUSH blocks — see [Failure modes](#failure-modes-fault-tolerance). Not currently tunable via config. |

Rule of thumb: to reduce load, **raise `snapshot_interval_sec`** first (it scales
across every consumer at once); to reduce latency for a specific external consumer,
tune that gateway's own knobs rather than the global throttle.

## Tick And Time Representation

- Internal prices are stored as integer ticks in core engine/model logic.
- Internal timestamps are stored as integer nanoseconds (`time_ns`).
- Conversion happens at boundaries only:
    - Inbound user/config prices (decimal) -> ticks.
    - Outbound UI/messages/reporting values -> decimal prices.
    - Outbound display timestamps use seconds derived from ns (`ns / 1e9`).
- Matching, queue priority, auction price selection, and stop logic all operate
    on integer values to avoid float drift.

**Monotonic ordering guarantee.** Ordering-critical timestamps come from
`now_ns()` (`models/clock.py`), which wraps `time.time_ns()` and enforces a
**strictly increasing** sequence: if the raw clock returns a value less than or
equal to the last one (a duplicate, or a backwards wall-clock step), `now_ns()`
returns `last + 1` instead. This matters because the timestamp is the **tie-breaker
in price-time priority** — two orders at the same price must never compare equal,
or heap ordering (and therefore queue fairness) becomes undefined. The guarantee is
lock-protected for multi-threaded callers; the engine's single-threaded order loop
deliberately calls `time.time_ns()` directly on the hot path (ties are impossible
within one run-to-completion order — see [Performance Optimizations](#single-timestamp-call-per-order-cached-nanosecond-clock)).

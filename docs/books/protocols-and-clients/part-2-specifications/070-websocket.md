# WebSocket API Reference

> **Status: Normative.** This chapter is the contract for the four WebSocket
> streams of `pm-api-gwy` (`api_gateway/routers/ws.py`). It is versioned with
> the REST API under `/api/v1` and follows the same
> [compatibility policy](060-rest-and-websocket.md#compatibility-and-deprecation-policy).
> For a tutorial with worked client code see
> [API Gateway (REST/WebSocket)](../../operator-guide/part-5-gateways/050-api-gateway.md#websocket-endpoints).
> The key words MUST, MUST NOT, SHOULD and MAY are used per RFC 2119.
> `tests/test_ws_spec_matches_code.py` holds the catalogues below to the code.

## Streams

Every socket lives under `/api/v1/ws/`, so a reverse proxy can route upgrades
by that one prefix.

| Path | Access | Purpose | Queue |
|---|---|---|---|
| `/api/v1/ws/private` | Trading key | The caller gateway's order, quote and risk events | `256` |
| `/api/v1/ws/market-data` | Any key | Public book, depth, trades, auctions, session, halts and news, by subscription | `512` |
| `/api/v1/ws/admin/monitor` | ADMIN | Every engine event across all gateways, plus `admin.action` | `512` |
| `/api/v1/ws/admin/sim` | ADMIN | `pm-market-sim` state and the model's true values | `64` |

**Queue** is the number of events the gateway holds for one socket that has
not yet read them. See [Flow control](#flow-control).

## Connecting

1. The client opens the socket. The server accepts the upgrade.
2. The client MUST send, as its first frame and within **5 seconds**, a JSON
   object `{"api_key": "<key>"}`.
3. On success the server sends `{"type": "authenticated", ...}` and then the
   socket's opening snapshot, if it has one, before any live event.

The checks, in order, and what a failure looks like:

| Check | Sockets | On failure |
|---|---|---|
| A first frame arrives within 5 s and is JSON | all | close `1008` |
| `api_key` is a configured key | all | close `1008` |
| The key is a trading key (has a `gateway_id`) | `private`, `admin/monitor`, `admin/sim` | `error` frame (admin sockets), then close `1008` |
| The engine accepts the gateway's identity | `private`, `admin/monitor` | `error` frame with the engine's reason, then close `1008` |
| The gateway holds the ADMIN role | `admin/monitor`, `admin/sim` | `error` frame `"ADMIN role required"`, then close `1008` |

### Close codes

The gateway itself closes a socket with exactly one code:

| Code | Meaning |
|---|---|
| `1008` | Policy violation: authentication or authorisation failed (see above). The client MUST NOT reconnect with the same key without fixing the cause |

Any other closure (a normal close, the server shutting down, or a dropped
connection with no close frame) is not a verdict on the client: it SHOULD
reconnect with backoff and recover as described for each socket.

## The event envelope

Every engine event on every socket arrives in one envelope:

```json
{
  "type": "order.fill",
  "topic": "order.fill.TRADER01",
  "seq": 4127,
  "stream_seq": 88,
  "ts": "2026-06-24T10:15:03.221Z",
  "gateway_id": "TRADER01",
  "data": { "order_id": "ORD-...", "fill_qty": 50, "fill_price": 150.5 }
}
```

| Field | Present | Meaning |
|---|---|---|
| `type` | always | The stable event name; see [Event types](#event-types) |
| `topic` | always | The engine topic the event came from |
| `seq` | engine events | Per-`topic` counter, assigned once per event by this gateway process |
| `stream_seq` | `private` only | Per-gateway counter across the whole private stream |
| `ts` | always | When this gateway sent the event, UTC, millisecond ISO-8601 |
| `gateway_id` | gateway-scoped events | The gateway the event belongs to |
| `data` | always | The engine message body; its schema is the linked message reference |

Server frames that are not engine events (`authenticated`, snapshots, the
market-data control replies, `error`) carry `type` and `data` and only the other
fields their row below names.

### Sequencing

- `seq` counts per `topic`, within one gateway process. A client checking for
  gaps MUST key on `topic`, not `type`: one type (`depth`) spans many topics
  (`depth.AAPL`, `depth.MSFT`), each numbered independently.
- `stream_seq` counts every event on one gateway's private stream, so on
  `/ws/private` it is contiguous: a gap of any size means events were lost.
- An event is numbered before it is queued, so an event dropped for a slow
  socket still consumes its number. A gap is therefore always detectable.
- Counters restart when the gateway process restarts. A client SHOULD treat a
  `seq` lower than the last one seen on a topic as a restart, not a gap.

### Event types

`type` is derived from `topic`: the first two dot-separated segments
(`order.fill.TRADER01` gives `order.fill`), with these exceptions:

| Topic | `type` |
|---|---|
| `trade.executed` | `trade` |
| `book.{symbol}` | `book` |
| `depth.{symbol}` | `depth` |
| `session.state` | `session` |
| `circuit_breaker.*` | `circuit_breaker` |
| `auction.result.{symbol}` | `auction` |
| `auction.indicative.{symbol}` | `auction.indicative` |
| `risk.kill_switch_ack.{gateway_id}` | `mass_cancel.ack` |
| `admin.action.{gateway_id}` | `admin.action` |

A client MUST ignore an event whose `type` it does not recognise. New types
may be added within v1.

## Flow control

Each socket has a bounded queue (see [Streams](#streams)). The gateway never
blocks the engine feed for a slow client: when a socket's queue is full, the
event is **dropped for that socket** and the socket stays open.

- Every drop is counted per stream (`private`, `market_data`, `admin`) in
  `GET /api/v1/healthz` as `dropped_events` and in the gateway's metrics as
  `api.dropped_events`.
- The client detects a drop from a `seq` or `stream_seq` gap and recovers as
  its socket describes below.
- `/ws/admin/sim` and `news` events are not numbered. Each `sim` frame
  supersedes the previous one, so a dropped one needs no recovery.

## `/api/v1/ws/private`

The caller gateway's own events, unfiltered.

### Opening frames

| `type` | Fields | Meaning |
|---|---|---|
| `authenticated` | `gateway_id`, `stream_seq` | Authenticated; `stream_seq` is the stream position now |
| `orders.snapshot` | `gateway_id`, `stream_seq`, `ts`, `data: {orders, positions, quote_legs}` | The gateway's view of the caller's orders, positions and quote legs, accurate as of `stream_seq` |

The event sink is registered before the snapshot is taken: the worst case is
an event both in the snapshot and delivered live, never one in neither. Order
state is idempotent, so a client MAY apply such a duplicate twice.

### Private event catalogue

| `type` | Engine topic | Payload |
|---|---|---|
| `order.ack` | `order.ack.{gateway_id}` | [order.ack](../part-5-message-reference/010-message-reference.md#orderackgateway_id) |
| `order.fill` | `order.fill.{gateway_id}` | [order.fill](../part-5-message-reference/010-message-reference.md#orderfillgateway_id) |
| `order.amended` | `order.amended.{gateway_id}` | [order.amended](../part-5-message-reference/010-message-reference.md#orderamendedgateway_id) |
| `order.cancelled` | `order.cancelled.{gateway_id}` | [order.cancelled](../part-5-message-reference/010-message-reference.md#ordercancelledgateway_id) |
| `order.expired` | `order.expired.{gateway_id}` | [order.expired](../part-5-message-reference/010-message-reference.md#orderexpiredgateway_id) |
| `order.triggered` | `order.triggered.{gateway_id}` | [order.triggered](../part-5-message-reference/010-message-reference.md#ordertriggeredgateway_id) |
| `order.orders` | `order.orders.{gateway_id}` | [order.orders](../part-5-message-reference/010-message-reference.md#orderordersgateway_id) |
| `combo.ack` | `combo.ack.{gateway_id}` | [combo.ack](../part-5-message-reference/010-message-reference.md#comboackgateway_id) |
| `combo.status` | `combo.status.{gateway_id}` | [combo.status](../part-5-message-reference/010-message-reference.md#combostatusgateway_id) |
| `oco.ack` | `oco.ack.{gateway_id}` | [oco.ack](../part-5-message-reference/010-message-reference.md#ocoackgateway_id) |
| `oco.cancelled` | `oco.cancelled.{gateway_id}` | [oco.cancelled](../part-5-message-reference/010-message-reference.md#ococancelledgateway_id) |
| `quote.ack` | `quote.ack.{gateway_id}` | [quote.ack](../part-5-message-reference/010-message-reference.md#quoteackgateway_id) |
| `quote.status` | `quote.status.{gateway_id}` | [quote.status](../part-5-message-reference/010-message-reference.md#quotestatusgateway_id) |
| `mass_cancel.ack` | `risk.kill_switch_ack.{gateway_id}` | [risk.kill_switch_ack](../part-5-message-reference/010-message-reference.md#riskkill_switch_ackgateway_id) |
| `system.gateway_auth` | `system.gateway_auth.{gateway_id}` | [system.gateway_auth](../part-5-message-reference/010-message-reference.md#systemgateway_authgateway_id) |
| `system.symbols` | `system.symbols.{gateway_id}` | [system.symbols](../part-5-message-reference/010-message-reference.md#systemsymbolsgateway_id) |
| `system.quote_bootstrap` | `system.quote_bootstrap.{gateway_id}` | [system.quote_bootstrap](../part-5-message-reference/010-message-reference.md#systemquote_bootstrapgateway_id) |
| `system.quote_legs` | `system.quote_legs.{gateway_id}` | [system.quote_legs](../part-5-message-reference/010-message-reference.md#systemquote_legsgateway_id) |
| `system.session_status` | `system.session_status.{gateway_id}` | [system.session_status](../part-5-message-reference/010-message-reference.md#systemsession_statusgateway_id) |

The `order.*` events carry the order's `client_tag`, and cancels and amends
their `request_tag` (see the REST spec's
[order correlation](060-rest-and-websocket.md#order-correlation-with-client_tag)).

### Recovery

On reconnect the server sends a fresh `orders.snapshot`. A client MUST rebuild
its order state from it, then apply live events with a higher `stream_seq`.
There is no replay of missed private events: the snapshot is the recovery. For
history, use `GET /api/v1/history/orders` and `GET /api/v1/history/fills`.

## `/api/v1/ws/market-data`

Public events, filtered by the socket's subscription. Any configured key may
connect, including a read-only one.

### Channels

A client subscribes to `(symbol, channel)` pairs. Three channels are always
on: their events reach every market-data socket without a subscription,
because a halt or a phase change alters the meaning of every other channel.

| Channel | Subscribable | Event `type`s | Engine topics |
|---|---|---|---|
| `book` | yes | `book` | [`book.{symbol}`](../part-5-message-reference/010-message-reference.md#booksymbol) |
| `depth` | yes | `depth` | [`depth.{symbol}`](../part-5-message-reference/010-message-reference.md#depthsymbol) |
| `trades` | yes | `trade` | [`trade.executed`](../part-5-message-reference/010-message-reference.md#tradeexecuted) |
| `auction` | yes | `auction`, `auction.indicative` | [`auction.result.{symbol}`](../part-5-message-reference/010-message-reference.md#auctionresultsymbol), [`auction.indicative.{symbol}`](../part-5-message-reference/010-message-reference.md#auctionindicativesymbol) |
| `session` | always on | `session` | [`session.state`](../part-5-message-reference/010-message-reference.md#sessionstate) |
| `circuit_breaker` | always on | `circuit_breaker` | [`circuit_breaker.halt.{symbol}`](../part-5-message-reference/010-message-reference.md#circuit_breakerhaltsymbol), `.extend.{symbol}`, `.resume.{symbol}` |
| `news` | always on | `news` | [`news.event`](../part-5-message-reference/010-message-reference.md#newsevent) (from `pm-market-sim`; not numbered) |

### Control frames

The client sends control frames as JSON objects at any time after
`authenticated`.

| `action` | Fields | Effect | Reply |
|---|---|---|---|
| `subscribe` | `symbols`, `channels` (flat form) and/or `items` | Add the pairs; then send the current snapshot of each | `subscription`, then snapshot events |
| `unsubscribe` | as `subscribe` | Remove the pairs | `subscription` |
| `snapshot` | as `subscribe` | Re-send the current snapshot, subscription unchanged | snapshot events |
| `resume` | `topic`, `from_seq`, optional `symbols` | Replay one topic after `from_seq` | replayed events, or `resume.rejected` |

- **Flat form:** `{"action": "subscribe", "symbols": ["AAPL"], "channels": ["book", "trades"]}`
  is the cross product of its two lists.
- **Items form:** `"items": [{"symbols": ["*"], "channels": ["book"]}, {"symbols": ["AAPL"], "channels": ["depth"]}]`
  is a list of independent rules: book for every symbol, depth for AAPL only.
- An empty `symbols` list, or `["*"]`, means every symbol.
- An item may carry `resume_from: {"trades": <seq>}`; on `subscribe` and
  `snapshot` the `trades` channel then replays buffered prints after that
  `seq` instead of sending the whole tail.
- A malformed frame, or one that fails validation (an unknown `action` or
  channel, an unknown field), is answered with an `error` frame and otherwise
  ignored; the socket stays open.

### Server control frames

| `type` | `data` | Sent |
|---|---|---|
| `authenticated` | none | After authentication |
| `subscription` | `items` (effective rules, one per symbol), `always` (the always-on channels), `rejected` | After every `subscribe`/`unsubscribe` |
| `resume.rejected` | `topic`, `from_seq`, `reason` | A `resume` (or `resume_from`) that cannot be served |
| `trades.reset` | `symbol` | Before a fresh trade tail, when a symbol's trades could not be replayed |
| `error` | `message` | A control frame could not be parsed or validated |

`subscription.data.rejected` lists the items that contributed nothing:

| `reason` | Meaning |
|---|---|
| `no_channels` | The item named no channel |
| `wildcard_still_subscribed` | An `unsubscribe` of a named symbol that a `*` rule still covers |

`resume.rejected.data.reason`:

| `reason` | Meaning |
|---|---|
| `unknown_topic` | The topic is not a market-data topic, or there is nothing cached for it |
| `too_old` | `from_seq` is older than the replay window; a fresh tail follows |

### Recovery

- **Snapshot channels** (`book`, `depth`, `auction`) are self-healing: the
  current snapshot replaces whatever was missed. After a gap or a reconnect,
  send `snapshot` (or `subscribe`) for the pairs concerned.
- **Trades** are replayable for the gateway's replay window
  (`market_data_cache_sec`, 60 seconds by default): `resume` with `topic: "trade.executed"`, the last
  processed `seq` and the symbol. Past the window the server sends
  `trades.reset` and `resume.rejected` (`too_old`), then the current tail. A
  client SHOULD de-duplicate trades by their `id` across a replay.
- `session` and `circuit_breaker` state after a reconnect is available from
  `GET /api/v1/session` and `GET /api/v1/halts`.

## `/api/v1/ws/admin/monitor`

Every engine event this gateway receives, across all gateways, in the
standard envelope, plus `admin.action`. ADMIN only.

### Opening frames

| `type` | Fields | Meaning |
|---|---|---|
| `authenticated` | none | Authenticated |
| `monitor.snapshot` | `ts`, `data: {orders, halts, gateways, last_seq, incomplete}` | Current state: the gateway's cross-gateway order view, the engine's halts and gateway roster, each active gateway's `stream_seq`; names of any part that timed out in `incomplete` |

### Events

All private and market-data event types above, for every gateway, and:

| `type` | Engine topic | Payload |
|---|---|---|
| `admin.action` | `admin.action.{gateway_id}` | [admin.action](../part-5-message-reference/010-message-reference.md#adminactiongateway_id): one admin-gated command, who ran it and what it did |

Other engine topics (system replies addressed to any gateway, index and
reference events) also arrive here, with `type` derived as in
[Event types](#event-types). A monitor MUST ignore types it does not render.

### Recovery

None by replay: on reconnect the snapshot is current state. History is the
audit trail (`GET /api/v1/admin/orders/{order_id}/audit`, `pm-audit-cli`).

## `/api/v1/ws/admin/sim`

`pm-market-sim`'s state and the model's true (hidden) fair values. ADMIN only.
Frames carry `type` and `data` only, and are not numbered.

| `type` | `data` | Sent |
|---|---|---|
| `authenticated` | none | After authentication |
| `sim.snapshot` | `{available, state, values}`, as `GET /api/v1/admin/sim` | Opening state |
| `sim.state` | [sim.state](../part-5-message-reference/010-message-reference.md#simstate) | Each simulator heartbeat |
| `sim.value` | [sim.value](../part-5-message-reference/010-message-reference.md#simvalue) | Each step's true values |

Each frame supersedes the previous one; a slow viewer simply misses steps.

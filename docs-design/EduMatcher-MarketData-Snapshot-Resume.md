Version: 1.0.0

Date: 2026-08-12

Status: Design and Implementation Proposal

# EduMatcher — Market-Data Snapshot / Resume for `pm-api-gwy`

> Implements item 2 of the suggested order in
> [EduMatcher-Trading-GUI.md §26.5](./EduMatcher-Trading-GUI.md#265-suggested-implementation-order):
> *"Add snapshot/resume for market data."* Scope is the four subscribable
> market-data channels — `book`, `trades`, `depth`, `auction` — delivered over
> `WS /api/v1/market-data`. Private-event resume/replay on `/api/v1/events` was
> evaluated and deliberately deferred (§26.3.5 of that document) and is **not**
> in scope here.

## Table of Contents

- [1. Motivation](#1-motivation)
- [2. What exists today](#2-what-exists-today)
- [3. The snapshot-not-delta nuance](#3-the-snapshot-not-delta-nuance)
- [4. Goals and Non-Goals](#4-goals-and-non-goals)
- [5. Design](#5-design)
  - [5.1 The stream cache](#51-the-stream-cache)
  - [5.2 Where the cache lives and how it is fed](#52-where-the-cache-lives-and-how-it-is-fed)
  - [5.3 Snapshot on subscribe](#53-snapshot-on-subscribe)
  - [5.4 Explicit snapshot](#54-explicit-snapshot)
  - [5.5 Resume](#55-resume)
  - [5.6 Reset](#56-reset)
- [6. Wire Protocol](#6-wire-protocol)
  - [6.1 Control frames](#61-control-frames)
  - [6.2 Server responses](#62-server-responses)
- [7. Configuration](#7-configuration)
- [8. Testing Plan](#8-testing-plan)
- [9. Backwards Compatibility](#9-backwards-compatibility)
- [10. Deferred / Out of Scope](#10-deferred--out-of-scope)

## 1. Motivation

A market-data client (`pm-trading-ui`, or any CALF-style consumer over the
JSON WebSocket) has two moments where it needs *current* state rather than the
*next* update:

1. **On (re)subscribe.** When it subscribes to a symbol it receives nothing
   until the next event on that topic. For `book`/`depth` that is up to the
   engine's per-symbol snapshot interval (~0.5 s); for `auction` it is only
   during a call phase; for `trades` it is only on the next print. A
   reconnecting terminal therefore renders a blank ladder until the market
   happens to move.
2. **After a detected gap.** The per-topic `seq` shipped earlier
   ([§26.5 item 1](./EduMatcher-Trading-GUI.md#265-suggested-implementation-order))
   lets a client *detect* a dropped event, but it has no way to *repair* one
   except to tear the socket down and re-subscribe, which triggers a full
   REST/bootstrap refetch storm (§17.3.4).

This proposal adds the missing half: an authoritative snapshot on demand, and
a bounded resume, delivered by a small in-gateway stream cache — the
component sketched in
[§26.4.1 API gateway stream cache](./EduMatcher-Trading-GUI.md#2641-api-gateway-stream-cache).

## 2. What exists today

`WS /api/v1/market-data` (`api_gateway/routers/ws.py`) authenticates, sends
`{"type": "authenticated"}`, registers a fan-out sink on the shared
`EngineClient`, and runs a sender/receiver pair. The `Subscription` object
holds independent `(symbol, channel)` pairs, so per-symbol channels already
work. Every event carries a per-topic `seq` assigned in
`EngineClient._next_seq(topic)` and rendered by `events.envelope(...)`.

What is missing:

- Nothing retains the *latest* value of any topic, so a snapshot cannot be
  served on demand.
- There is no `snapshot`, `resume`, or `reset` verb in the control protocol.

## 3. The snapshot-not-delta nuance

This shapes the entire design and is worth stating before the mechanics.

Per [§17.3.4](./EduMatcher-Trading-GUI.md#1734-bandwidth-and-the-100-symbol-overview),
`book`, `depth`, `auction`, and `auction.indicative` are **full snapshots**,
republished on a timer. There is no incremental depth channel. Only `trade`
is a genuine append-only delta stream.

The consequence: for the three snapshot channels a sequence gap is
**self-healing** — the next message is already complete state — so "resume"
for them means nothing more than "hand me the current snapshot." Only `trades`
has history worth replaying, and only `trades` can suffer a gap that a later
message does not implicitly repair. The cache is therefore asymmetric by
design: it keeps the *latest* value per snapshot topic, and a *time-bounded
tail* of `trade` prints.

## 4. Goals and Non-Goals

**Goals**

- Serve an authoritative snapshot for `book`/`depth`/`auction` and a recent
  tail for `trades`, both on subscribe and on an explicit `snapshot` request.
- Answer a `resume` for `trades` by replaying buffered prints after a client's
  last-seen `seq`, or telling the client to re-snapshot when it has fallen
  outside the retained window.
- Keep every addition additive: a client that never sends the new verbs, and
  never sets the new fields, behaves exactly as before.

**Non-Goals**

- No replay for `book`/`depth`/`auction` beyond re-sending the current
  snapshot (they are self-healing; a delta log would be dead weight).
- No private-event (`/api/v1/events`) resume — deferred in §26.3.5.
- No durable/on-disk retention. The cache is in-memory and bounded, matching
  the classroom/local scale the gateway targets.

## 5. Design

### 5.1 The stream cache

A new `api_gateway/market_cache.py` defines `MarketDataCache`:

- `_snapshots: dict[str, dict]` — keyed by **engine topic** (`book.AAPL`,
  `depth.AAPL`, `auction.result.AAPL`, `auction.indicative.AAPL`), holding the
  last envelope seen for that topic. Keying by topic (not by
  `(symbol, channel)`) keeps the two auction tenses — `result` and
  `indicative` — as distinct entries that both surface under the client's one
  `auction` channel, exactly as the live feed treats them.
- `_trades: dict[str, deque[_Buffered]]` — per symbol, a time-bounded ring of
  recent `trade` envelopes, evicted by age. This mirrors the existing
  CALF-layer `md_gateway/replay_buffer.py` (`ReplayBuffer` /
  `ReplayMissError`), reusing its shape rather than inventing a second idiom.
- `_symbols_by_channel: dict[str, set[str]]` — an index so a wildcard (`*`)
  subscribe can enumerate exactly the symbols the cache has actually seen.

Public surface:

```python
class MarketDataCache:
    def __init__(self, window_sec: int = 60) -> None: ...
    def record(self, event: dict[str, Any]) -> None: ...
    def snapshot(self, symbol: str, channel: str) -> list[dict[str, Any]]: ...
    def snapshot_channel(self, channel: str) -> list[dict[str, Any]]: ...
    def resume_trades(self, symbol: str, from_seq: int) -> list[dict[str, Any]]: ...
```

`resume_trades` raises `ReplayMiss` (a local subclass of `RuntimeError`,
naming kept parallel to `md_gateway`'s `ReplayMissError`) when `from_seq`
precedes the oldest retained print, so the caller can fall back to a reset.

### 5.2 Where the cache lives and how it is fed

The cache is owned by `EngineClient` and updated inside `_handle_event`, in the
market-data branch (`gateway_id is None`), immediately after the envelope is
built and sequenced. That is the one point where every market-data event, with
its final `seq`, passes through exactly once, so the cache and the live feed
can never disagree about what the current snapshot or the latest `seq` is.

`EngineClient.__init__` gains an optional `market_cache_sec: int = 60`; the
FastAPI lifespan passes `config.market_data_cache_sec`. Because the SUB reader
hands events into the event loop via `call_soon_threadsafe`, the cache is only
ever touched on the loop thread — the same single-threaded discipline the sinks
already rely on, so no lock is needed.

### 5.3 Snapshot on subscribe

After a `subscribe` control is applied, the gateway immediately emits the
cached snapshot for each newly-matched `(symbol, channel)` pair — the current
`book`/`depth`/`auction` envelope, or the buffered `trades` tail. A `*`
(wildcard) symbol expands over the symbols the cache has seen on that channel.
This is what removes the blank-ladder-on-reconnect gap. When nothing is cached
yet (cold gateway), the burst is simply empty and the client waits for the
first live tick as it does today.

### 5.4 Explicit snapshot

`{"action": "snapshot", "items": [...]}` re-emits the current snapshot for the
requested symbols/channels without changing the subscription. This lets a
client that already detected a gap on a snapshot channel refresh that one topic
without a re-subscribe.

### 5.5 Resume

A `resume` names one topic and the last `seq` the client processed:
`{"action": "resume", "topic": "trade.executed", "symbol": "AAPL",
"from_seq": 128400}`. For `trades`, the gateway replays buffered prints with
`seq > from_seq`. If `from_seq` is older than the retained window it answers
`resume.rejected` with `reason: "too_old"` and follows with a fresh trades
snapshot. For a snapshot channel, resume is answered by re-sending the current
snapshot (self-healing); for a topic the cache has never seen,
`resume.rejected` with `reason: "unknown_topic"`.

### 5.6 Reset

When the gateway cannot honour a resume it emits a `*.reset` envelope for the
affected topic instructing the client to discard its cached state and take a
fresh snapshot, then sends that snapshot. This is the browser equivalent of a
CALF `RESET`.

## 6. Wire Protocol

### 6.1 Control frames

`MarketDataControl` (`schemas.py`) gains two actions and two fields; the
existing `subscribe`/`unsubscribe` forms are unchanged.

```jsonc
// snapshot on subscribe is automatic; resume_from is an optional per-item hint
{ "action": "subscribe",
  "items": [ { "symbols": ["AAPL"], "channels": ["book","trades","depth","auction"],
               "resume_from": { "trades": 128400 } } ] }

// re-snapshot without changing the subscription
{ "action": "snapshot", "items": [ { "symbols": ["AAPL"], "channels": ["book","depth"] } ] }

// resume one dropped stream explicitly
{ "action": "resume", "topic": "trade.executed", "symbol": "AAPL", "from_seq": 128400 }
```

`resume_from` maps a channel to the last `seq` the client saw on that channel's
topic for the item's symbol(s); it is honoured for `trades` and ignored (a
plain snapshot is sent) for the self-healing channels.

### 6.2 Server responses

- Snapshot delivery reuses the existing envelope `type`s (`book`, `depth`,
  `auction`, `auction.indicative`, `trade`) — each is already complete state,
  so the client applies them through its normal routing.
- `{"type": "<channel>.reset", "topic": "...", "data": {"symbol": "..."}}` —
  discard cached state for the topic and expect a fresh snapshot next.
- `{"type": "resume.rejected", "data": {"topic": "...", "from_seq": N,
  "reason": "too_old" | "unknown_topic" | "snapshot_required"}}`.

## 7. Configuration

`ApiGatewayConfig` gains `market_data_cache_sec: int = 60`, loaded by
`_load_api_gateway_section` with the same rules as the existing
`order_retention_sec` (`>= 0`, `0` disables retention entirely). Default 60 s
matches the recommended market-data retention in
[§26.4.1](./EduMatcher-Trading-GUI.md#2641-api-gateway-stream-cache) ("retain
the last 30–60 seconds per symbol/channel, plus current snapshots"). The latest
snapshot per topic is retained regardless of the window — only the `trades`
tail is aged out — so a snapshot is always available even for a symbol that has
been quiet longer than the window.

## 8. Testing Plan

New `tests/test_api_gateway_market_snapshot.py`, plus additions to the existing
`tests/test_api_gateway_ws_sequencing.py`, both reusing the mocked-`EngineClient`
fixture (drive `client._handle_event(topic, payload)`, drain a sink queue):

- `record` then `snapshot` returns the latest `book`/`depth`/`auction` envelope.
- Both auction tenses (`auction.result`, `auction.indicative`) are retained and
  both returned for the `auction` channel.
- `snapshot("AAPL", "trades")` returns the buffered tail in order.
- `snapshot_channel` expands a wildcard over every cached symbol on the channel.
- `resume_trades` returns only prints with `seq > from_seq`.
- `resume_trades` beyond the retained window raises `ReplayMiss`.
- Aged trades are evicted once older than `window_sec`; the latest snapshot is
  **not** evicted.
- `window_sec == 0` disables the trade buffer but still serves snapshots.
- Control-frame parsing: `snapshot`/`resume` actions validate; `resume_from`
  round-trips; unknown fields are still rejected by the `StrictModel`.
- End-to-end WS behaviour is additive: a client that never sends the new verbs
  sees the unchanged event stream.

Target: ≥ 86 % line coverage on the new module, within the project's 85 %
global gate; `black`, `flake8`, `mypy`, and `pyright --level error` green.

## 9. Backwards Compatibility

Every change is additive. `MarketDataControl` keeps its existing fields and
forms; the two new actions and two new optional fields default to absent. A
client that only ever sends `subscribe`/`unsubscribe` receives exactly the
stream it does today, plus — and only if the cache is warm — an initial
snapshot burst on subscribe, which is itself just ordinary `book`/`depth`/
`auction`/`trade` envelopes it already knows how to route. No engine change and
no change to `/api/v1/events`.

## 10. Deferred / Out of Scope

- **Private-event resume** on `/api/v1/events` — deferred in
  [§26.3.5](./EduMatcher-Trading-GUI.md#2635-private-event-recovery);
  `stream_seq` + `orders.snapshot` + `/history/*` already cover it.
- **A unified envelope** across market data, private events, and admin monitor
  (§26.3.1) — a larger cross-cutting change, tracked separately.
- **Admin-monitor event backfill** (§26.3.6) — its own item.
- **Incremental depth deltas** (§26.3.4) — the engine publishes full depth
  snapshots; a delta channel is a separate engine-side change.

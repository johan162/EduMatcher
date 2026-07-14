# CALF Market Data Gateway Code Review

**Scope:** `src/edumatcher/md_gateway/` — `gateway.py`, `client_session.py`, `config.py`, `main.py`, `protocol.py`, `fanout.py`, `sequencer.py`, `replay_buffer.py`, `normaliser.py`. Also its dependencies `messaging/bus.py` and `models/message.py`.

**Date:** 2026-07-13

**Subject:** `pm-md-gwy` — public-facing CALF market data gateway that accepts the CALF text protocol over TCP/IP and fans engine PUB topics out to subscribed clients.

---

## Overall assessment

Like the ALF gateway, this uses a **single-threaded reactor** (`accept → read → poll engine → heartbeat → flush → drop-idle → sleep`), which avoids in-process data races on client state. Two structural facts make its risk profile different from the ALF gateway:

- **It is subscribe-only toward the engine.** It holds two `zmq.SUB` sockets and never PUSHes. All engine reads go through non-blocking `poll(timeout=0)` + `recv_multipart`. So the ALF gateway's critical "blocking `send_multipart` freezes the loop" issue **does not apply**, and there are no gateway→engine write race conditions to worry about. This is a genuine strength worth stating explicitly.
- It is heavily and thoughtfully documented (design rationale, references to `EduMatcher-CALF-Extensions.md`), and normalization is cleanly separated from socket flow. Maintainability is generally good — better commented than the ALF gateway.

That said, the gateway has one **critical, trivially-triggered crash** (no connection limit) and two **high-severity robustness bugs** (slow-client handling is effectively broken, and the hot engine-event path can crash the whole process). The correctness of sequencing/replay is largely sound.

No true engine-interaction race conditions were found: the reactor serializes everything, `_known_symbols` and the normaliser caches are read/written on the one thread, and there are no writes back to the engine.

---

## Critical

### MD-C1. No maximum-connections limit → trivially crashable on a public port

`_accept_new_clients` accepts unconditionally and only catches `BlockingIOError`:

```python
while True:
    try:
        conn, addr = self._server.accept()
    except BlockingIOError:
        break
    conn.setblocking(False)
    self._clients[conn.fileno()] = ClientSession(sock=conn, addr=addr)
```

There is no `max_connections` in `MarketDataGatewayConfig` and no cap here. Two independent crash paths follow, both trivially reachable by opening many sockets to a public port:

1. **fd exhaustion:** once the process file-descriptor limit is reached (often 256 by default on macOS), `accept()` raises `OSError(EMFILE)`, which is *not* `BlockingIOError` and is uncaught → propagates out of the run loop → gateway dies.
2. **`select` FD_SETSIZE:** `_read_client_data` calls `select.select(readable, [], [], 0)`. Once any socket fd is `>= FD_SETSIZE` (1024), CPython's `select.select` raises `ValueError`, which is *not* `OSError` (only `OSError` is caught there) → propagates → gateway dies.

For a public-facing service, an unauthenticated peer can take the whole gateway down by opening a modest number of connections.

**Fix:** add a `max_connections` config bound and close excess connections on accept; catch `OSError` around `accept()`; and move off `select.select` (or guard its fd count) — `selectors`/`poll` avoids the FD_SETSIZE ceiling.

---

## High

### MD-H1. Slow-client disconnect is ineffective and leaks memory unboundedly **fixed**

The overflow handling in `_flush_client_writes`:

```python
if len(session.out_queue) > self.config.max_client_queue:
    self._queue_line(session, "ERR", {"CODE": "SLOW_CLIENT", "MSG": "outbound queue overflow"})
    self._close_after_flush(session)   # sets session.closing = True

if session.closing and not session.out_queue:
    self._disconnect(session)
```

`_close_after_flush` only sets `closing = True`; the actual `_disconnect` fires **only when `out_queue` is empty**. A slow client, by definition, never drains its queue — so it is never disconnected. Worse, `_emit_stream_event` keeps fanning out to any `authenticated` session regardless of `closing`, so it continues appending market data to the already-overflowing queue. The result: the queue grows without bound, the SLOW_CLIENT branch re-fires every iteration (queuing yet more ERR lines), and the connection is never dropped.

There is also no per-append bound: `_queue_raw` appends unconditionally, and the only overflow check is *after the fact* in `_flush_client_writes`. During a single `_poll_engine_events` burst, an arbitrary number of events can be appended before any check runs.

(For contrast, the ALF gateway clears the queue on overflow before queuing its single ERR, so its close-after-flush actually completes.)

**Fix:** on overflow, hard-disconnect immediately (don't wait for an empty queue), and stop fanning out to sessions flagged `closing`.

### MD-H2. Engine-event hot path is only partially guarded → one bad event crashes the gateway **fixed**

`_poll_engine_events` wraps only `decode` in try/except:

```python
while self._sub_sock.poll(timeout=0):
    try:
        topic, payload = decode(self._sub_sock.recv_multipart())
    except Exception:
        continue
    now_seconds = _extract_ts(payload)
    if topic.startswith("book."):
        ... self._normaliser.normalise_book(...) ...
        ... self._emit_stream_event(...) ...
```

Normalisation, sequence allocation, replay append, `build_line`, and fanout all run **outside** the try/except. The normalisers are mostly defensive today, but any unhandled edge (e.g. `build_line` raising `CalfProtocolError` if a normalised field ever contains `|`, or an unexpected payload shape) propagates out of the loop → `finally: self.close()` → the entire gateway (all clients) goes down over a single event.

**Fix:** wrap the whole per-message handler body in try/except (log-and-continue), not just `decode`.

---

## Medium

### MD-M1. Idle timeout is effectively defeated for authenticated clients **fixed**

`last_activity` is refreshed both on `recv` (`_read_client_data`) **and on every successful `send`** (`_flush_client_writes`: `session.last_activity = time.monotonic()`). Since heartbeats are flushed every `heartbeat_interval_sec` (default 1s) and `idle_timeout_sec` defaults to 5s, an authenticated client's `last_activity` is continuously refreshed by the gateway's own outbound writes — so `_drop_idle_clients` never fires for it, even if the client never reads or sends anything. Idle detection only kicks in once sends stop succeeding, at which point the (broken, see MD-H1) slow-client path is supposed to take over. Net effect: the idle timeout does not do its stated job for authenticated clients.

**Fix:** base idle detection on inbound activity (and/or unacked outbound backlog), not on successful sends.

### MD-M2. No command rate limiting; SUB/UNSUB toggling amplifies snapshots **fixed**

Unlike the ALF gateway (token bucket), there is no per-client command rate limit. `_handle_sub` sends a fresh SNAP for each newly-added pair, and for `CH=TOP, SYM=*` it emits one SNAP per known symbol. Because `new_pairs = requested_pairs - session.subscriptions`, a client can repeatedly `UNSUB` then `SUB` a wildcard TOP stream to force the gateway to regenerate a per-symbol snapshot storm on demand — CPU/bandwidth amplification from a single connection.

**Fix:** add a lightweight per-client command rate limit (and/or a cooldown on snapshot regeneration).

### MD-M3. `_poll_engine_events` drains the entire SUB backlog per iteration **fixed**

`while self._sub_sock.poll(timeout=0):` (and the index socket likewise) processes *all* currently-available engine messages before returning to `_flush_client_writes`. On a market-data hot path this means a burst is fully appended to every subscriber's `out_queue` before any flush occurs — latency and memory spikes, and it interacts badly with MD-H1. Consider bounding messages processed per iteration and interleaving flushes.

---

## Low / informational

- **MD-L1. Pre-auth slowloris (minor).** There *is* a handshake timeout (`_HELLO_TIMEOUT_SEC = 5`, good — the ALF gateway lacked this), but because `last_activity` resets on any inbound byte, a client dribbling bytes every <5s can hold an unauthenticated slot. Bounded to 5s windows; combined with MD-C1 (no connection cap) it is more relevant.
- **MD-L2. Dead code in SUB validation.** In `_handle_sub`, `if any(ch == "INDEX" ...) and not sym:` can never be true — `_parse_csv_upper` already strips empty tokens, so `sym` is never falsy.
- **MD-L3. Two sources of truth for subscriptions.** `session.subscriptions` and `SubscriptionRegistry._by_client[fd]` are kept in sync manually (every mutation must call `set_for_client`). This is fragile duplication; consider a single owner.
- **MD-L4. `ClientSession.__del__` closes the socket.** Relying on `__del__` for cleanup is risky (non-deterministic, runs during interpreter shutdown); it is wrapped defensively but explicit close paths should remain the norm.
- **MD-L5. `fileno`-as-dict-key reuse.** `_clients` and the subscription registry are keyed by `sock.fileno()`. Correct today because `_disconnect` reads the fd before `close()` and removes both entries, but the invariant deserves a comment since a stale/reused fd would misroute fanout.
- **MD-L6. Cross-restart sequence continuity.** `SequenceAllocator` and `ReplayBuffer` are in-memory and reset on restart. A client `RESUME`-ing after a gateway restart gets an empty (non-miss) replay and then sees sequence numbers restart low, which can confuse client-side gap detection. Likely acceptable, but worth documenting.
- **MD-L7. Replay stream map never shrinks.** `ReplayBuffer._events` is a `defaultdict` that retains a `StreamKey` entry (empty deque) forever once a stream is seen. Bounded by channels × symbols, but never reclaimed.
- **MD-L8. Broad `except Exception: continue` around `decode`** silently swallows all engine-message decode errors, which can mask real bus/serialization problems. Consider narrowing or counting/logging.
- **MD-L9. Open market data by design.** HELLO requires only a non-empty `CLIENT` (≤32 chars) and `PROTO=CALF1`; there is no real authentication. Presumably intended for public market data, but note that anyone can subscribe to everything.

---

## Coherence / maintainability

Strengths: clear module decomposition (protocol / fanout / sequencer / replay / normaliser / session), strong docstrings and rationale comments, all-or-nothing SUB validation, defensive normalisers (`_extract_levels`, `_as_int_text`, `_as_decimal` all tolerate bad input), and a real handshake timeout.

Suggestions:
- State the concurrency contract in the module docstring ("single-threaded reactor; no blocking calls in the loop") as done conceptually already, and note that engine interaction is read-only (no write races).
- Collapse the dual subscription bookkeeping (MD-L3) to one source of truth.
- Add a `max_connections` bound (MD-C1) and document the fanout/fd invariants (MD-L5).
- Wrap the engine-event handler body defensively (MD-H2) and make slow-client eviction a hard close (MD-H1).

---

## Priority to fix

1. **MD-C1** (no connection limit → trivial crash) — highest priority for a public-facing service.
2. **MD-H1** (slow-client leak / never disconnects) and **MD-H2** (unguarded engine path crashes the process).
3. **MD-M1 / MD-M2** (idle timeout defeated; snapshot amplification).

---

## Findings summary

| ID | Severity | Area | Summary |
|----|----------|------|---------|
| MD-C1 | Critical | Accept / IO | No `max_connections` cap; `accept()` EMFILE and `select` FD_SETSIZE both crash the gateway; trivially triggered by opening many sockets. |
| MD-H1 | High | Backpressure | SLOW_CLIENT sets `closing` but disconnect waits for an empty queue that a slow client never reaches, while fanout keeps appending → unbounded memory, never dropped. |
| MD-H2 | High | Engine path | Only `decode` is guarded in `_poll_engine_events`; an unhandled exception in normalise/emit/`build_line` tears down the whole gateway. |
| MD-M1 | Medium | Idle timeout | `last_activity` refreshed on successful sends (incl. heartbeats), so the idle timeout never fires for actively-fed authenticated clients. |
| MD-M2 | Medium | Rate limiting | No command rate limit; UNSUB/SUB toggling of wildcard TOP forces repeated per-symbol snapshot storms (amplification). |
| MD-M3 | Medium | Engine path | Poll loop drains the entire SUB backlog before flushing, causing latency/memory spikes on bursts. |
| MD-L1 | Low | Pre-auth | Handshake timeout exists but byte-dribbling resets it within the 5s window. |
| MD-L2 | Low | Validation | Dead `and not sym` INDEX check (empty tokens already stripped). |
| MD-L3 | Low | Maintainability | Subscriptions duplicated between `ClientSession` and `SubscriptionRegistry`. |
| MD-L4 | Low | Lifecycle | `ClientSession.__del__` closes the socket (fragile cleanup pattern). |
| MD-L5 | Low | Fanout | `fileno`-as-key reuse is safe today but undocumented/fragile. |
| MD-L6 | Low | Replay | In-memory sequence/replay reset on restart breaks RESUME continuity. |
| MD-L7 | Low | Replay | `ReplayBuffer._events` never reclaims quiet streams. |
| MD-L8 | Low | Robustness | Broad `except Exception` around decode silently swallows bus errors. |
| MD-L9 | Info | Auth | Market data is effectively unauthenticated (likely by design). |

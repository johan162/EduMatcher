Version: 1.0.0

Date: 2026-08-04

Status: Pre-Beta Code Review

# pm-engine — Pre-Beta Review

Scope: `src/edumatcher/engine/` (8 209 lines) plus the gateway send paths that
feed it. Focus per request: correctness, race conditions, expected behaviour,
edge cases, lost orders.

Severity key:

- **E-CRIT** — data loss, or an unauthenticated participant can stop the venue.
- **E-HIGH** — protocol contract broken, or an order's fate is indeterminate.
- **E-MED** — inconsistent behaviour, operational risk.
- **E-LOW** — hardening, clarity.

Findings marked *(verified)* were reproduced by executing the code.

---

## Summary

| ID | Severity | Finding |
|----|----------|---------|
| E1 | **E-CRIT** — *FIXED* | A malformed frame from any client crashes the engine, and the crash path skips the *only* code that persists GTC orders |
| E2 | **E-CRIT** — *FIXED* | GTC orders, combos and `book_stats` are persisted **only** at clean shutdown — no checkpoint |
| E3 | **E-HIGH** — *FIXED* | A handler exception leaves the order with no ACK and no REJECT — the client's order is in limbo |
| E4 | **E-MED** — *FIXED* | `api_gateway` does not guard the PUSH send that `alf_gwy` does guard; behaviour under backpressure differs by gateway |
| E5 | **E-LOW** — *FIXED* | `_flush_*` maintenance calls sit outside the loop's exception handling |

The engine is **not** in the state the statistics module was. Ownership checks,
duplicate-ID rejection, input validation, self-match handling and combo/OCO
cascades are all present and carefully commented, several carrying prior review
tags (`A4`, `M7`, `H1`, `L9`). §7 lists what I checked and found sound, because
that matters as much as the defects for a beta decision.

The findings below are concentrated in one place: **the boundary between the
socket and the dispatcher**, which is the one part of the loop that has not had
the same hardening as the handlers behind it.

---

## E1 — A malformed frame crashes the engine and destroys the resting book *(verified — FIXED)*

**Severity: E-CRIT.** Unauthenticated denial of service *plus* data loss.

`Engine.run()`:

```python
while self._running:
    try:
        socks = dict(poller.poll(timeout=200))
    except zmq.ZMQError:
        break
    if self.pull_sock in socks:
        frames = self.pull_sock.recv_multipart()     # ← unguarded
        topic, payload = decode(frames)              # ← unguarded
        self._dbg_count("pull_messages")
        self._dbg_count(f"topic_{topic}")
        self._dispatch_pull_message(topic, payload)  # (internally guarded)
    self._flush_snapshots()                          # ← unguarded
    self._flush_circuit_breakers()                   # ← unguarded
    ...
```

The `try` covers `poller.poll()` and nothing else. `_dispatch_pull_message` is
correctly guarded internally — that was clearly deliberate, and its docstring
explains the three failure modes it distinguishes. But `decode()` runs *before*
it, outside any handler.

`decode()` raises on input a client fully controls (verified):

| Frames sent | Result |
|---|---|
| `[b"order.new"]` — single frame | `IndexError` |
| `[b"order.new", b"{not json"]` | `JSONDecodeError` |
| `[b"order.new", b""]` | `JSONDecodeError` |
| `[b"\xff\xfe", b"{}"]` | `UnicodeDecodeError` |

The PULL socket is bound on `:5555` and accepts from any peer that connects.
No authentication precedes `decode()` — gateway identity is validated inside
the handlers, which is *after* the crash point.

**The consequence is not just a crash.** The exception propagates out of
`run()`, so the loop never exits normally and `self._shutdown()` is never
reached. `_shutdown()` is the only place that calls:

```python
save_gtc_orders(all_resting, GTC_ORDERS_FILE)      # main.py:4142
save_gtc_combos(list(self._combos.values()), ...)  # main.py:4146
save_book_stats(self.books, BOOK_STATS_FILE)       # main.py:4156
```

So one four-byte malformed message from any connected participant destroys
every resting GTC order in the venue, every GTC combo, and `book_stats` —
which carries `prev_close`, the seed for collar and circuit-breaker references
on the next start.

**Fix.** Wrap the receive-and-decode in the loop's existing failure taxonomy:

```python
if self.pull_sock in socks:
    try:
        frames = self.pull_sock.recv_multipart()
        topic, payload = decode(frames)
    except Exception as exc:
        self._dbg_count("undecodable_messages")
        log.warning("discarding undecodable PULL message: %s", exc)
    else:
        self._dbg_count("pull_messages")
        self._dbg_count(f"topic_{topic}")
        self._dispatch_pull_message(topic, payload)
```

A message that cannot be decoded cannot be attributed to a gateway, so no
reject can be sent — discarding and counting is the only honest option, and it
must be counted so the condition is observable rather than invisible.

**Fixed.** Receive and decode now sit inside a guard that counts
`_undecodable_count` (a plain integer, not the DEBUG-gated `_dbg_count`, so it
is present in a normal run) and logs at WARNING. A message with no decodable
topic has no gateway to reject to, so discarding it is the only honest option
— but it is now counted rather than fatal. `tests/test_engine_durability.py`
covers all four frame shapes, plus a test pinning that `decode()` still raises
on them so the guard's justification cannot silently outlive its cause.

---

## E2 — The resting book is persisted only at clean shutdown *(FIXED)*

**Severity: E-CRIT.** Data loss on any abnormal termination.

E1 is one route to this, but not the only one. There is no periodic
checkpoint: `save_gtc_orders` appears exactly once in `engine/main.py`, inside
`_shutdown()`. Therefore the entire resting GTC book is lost on:

- an unhandled exception anywhere outside `_dispatch_pull_message` (E1, E5)
- `SIGKILL` — container eviction, OOM killer, `kill -9`
- host power loss
- any crash in the ZMQ layer

For a venue whose participants leave GTC orders resting across sessions, "we
lose the entire book if the process does not exit politely" is a materially
different durability promise from the one the persistence module's existence
implies.

**Fix.** Checkpoint on a timer in the existing 200 ms tick — the loop already
runs `_flush_snapshots()` and `_flush_circuit_breakers()` on the same cadence,
so a `_flush_persistence()` throttled to, say, 5 s fits the established shape.
Write to a temporary file and `os.replace()` so a crash mid-write cannot
truncate the previous good copy.

An alternative worth considering for beta+1 is an append-only journal of
accepted orders replayed at startup, which is what removes the window
entirely rather than shrinking it. That is a larger change and should not gate
beta.

**Fixed.** `_flush_persistence()` runs on the existing poll tick, throttled to
`_PERSIST_INTERVAL_SEC = 5.0`, bounding loss to five seconds. Unlike
`_shutdown()` it never mutates state — no DAY expiry, no publishing — so it is
safe mid-session, and a failed checkpoint logs at ERROR and continues rather
than ending the session.

This required a second fix first. `save_gtc_orders` used
`Path.write_text`, which truncates before writing, and `load_gtc_orders`
treats an unparseable file as an *empty book* — so an interrupted write
silently discarded every resting order. Checkpointing periodically multiplies
the number of write windows, so it is only safe once each replacement is
atomic. All three save functions now write to a temporary file in the same
directory, `fsync`, and `os.replace()`. Verified: a write that fails part-way
leaves the previous checkpoint byte-identical and loadable.

---

## E3 — A handler exception leaves the order with neither ACK nor REJECT *(verified — FIXED)*

**Severity: E-HIGH.** The order's fate is indeterminate from the client's side.

`_dispatch_pull_message`'s handler is:

```python
except Exception as exc:
    self._dbg_count("handler_errors")
    self._error_count += 1
    log.error("Error processing %s (#%d): %s", topic, self._error_count, exc)
```

It logs and counts. It sends nothing.

Every other path through `_handle_new_order` terminates in either
`make_ack_msg(accepted=True)` or `make_ack_msg(accepted=False, reason=…)`. If
the handler raises part-way — after validation but before the ACK, or during
matching — the submitting gateway receives **no message at all**.

What the participant experiences depends on the gateway:

- **API Gateway** — `await_event` waits for `order.ack.{GW}` and eventually
  raises `TimeoutError`. The client sees a timeout, indistinguishable from a
  slow engine.
- **ALF/BALF** — the client is left waiting on an ack that will never arrive.

Worse, the order may have *partially executed* before the exception: trades can
have printed and been published while the ACK never was. The participant then
holds an unacknowledged position.

**Fix.** Send a reject from the except block when the topic and payload carry
enough identity to address one:

```python
except Exception as exc:
    ...
    gateway_id = str(payload.get("gateway_id", "")).upper()
    order_id = payload.get("order_id") or payload.get("id")
    if gateway_id and order_id and topic in _ORDER_TOPICS:
        self.pub_sock.send_multipart(
            make_ack_msg(gateway_id, order_id, accepted=False,
                         reason="Internal error processing order")
        )
```

This is a contract fix, not a masking one: the exception is still logged and
counted, but the protocol invariant "every order terminates in an ack or a
reject" is restored.

**Caveat to design carefully.** If the exception occurred *after* fills
printed, a bare reject is itself misleading. The reject reason should be
distinguishable (`"Internal error after partial execution"`), and the drop-copy
record of the fills remains authoritative. This deserves explicit thought
rather than a blanket reject.

**Fixed.** `_reject_after_error(topic, payload, fills_before)` is called from
the except block. Three decisions differ from the sketch above and are worth
recording:

*Which topics.* `_ORDER_TOPICS` covers the seven order-entry and
order-cancellation topics only. Query topics (`*_request`) and the risk and
session control topics are excluded deliberately — nothing rests on them, and
an order-reject addressed to an id that is not an order is worse than silence.

*The partial-execution caveat, resolved by measurement rather than guesswork.*
`self._fills_published` is a plain counter (again not `_dbg_count`, which is
DEBUG-gated) incremented at all eight sites that publish a fill. The dispatcher
snapshots it before calling the handler, so the except path can tell whether
anything printed and pick between:

- `"Internal error processing order"` — nothing executed, a clean reject.
- `"Internal error after execution — fills already printed, reconcile against
  the drop copy"`.

The counter is engine-wide rather than per-order, so a fill belonging to a
resting *counterparty* also moves the reject to the second wording. That is
conservative on purpose: over-warning costs a participant one reconciliation,
under-warning tells them an order that executed never traded.

*Not `.upper()` on the gateway id.* The sketch above uppercased it. Acks are
addressed by topic (`order.ack.{gateway_id}`), and every other reject path in
the engine passes the id through verbatim — uppercasing here would have
published to a topic no lowercase-id gateway is subscribed to, reintroducing
the silence this finding is about, for exactly the participants whose orders
already failed.

The send is itself wrapped: raising inside the except block would escape
`run()` and take the venue down over a message that already failed once.
`tests/test_engine_durability.py` covers all five paths; four of the six new
tests fail against the unfixed code.

---

## E4 — Backpressure behaviour differs between gateways *(FIXED)*

**Severity: E-MED.**

`make_pusher` configures fail-fast semantics:

```python
_PUSH_SEND_TIMEOUT_MS = 0    # SNDTIMEO — never block
_PUSH_SEND_HWM = 1000
_PUSH_IMMEDIATE = 1          # fail if no peer connected
```

So `send_multipart` raises `zmq.Again` when the engine is down, not yet
connected, or slower than the sender. That is a sound choice for a
single-threaded reactor — but the two gateways respond differently.

`alf_gwy/gateway.py:1510` handles it properly:

```python
try:
    self._push.send_multipart(frames)
except zmq.Again:
    ...
    raise ValidationError("ENGINE_UNAVAILABLE",
                          "Engine unavailable: command not forwarded; retry shortly")
```

`api_gateway/engine_client.py:371` does not:

```python
def send_new_order(self, order: Order) -> None:
    self._push.send_multipart(make_order_new_msg(order.to_dict()))
```

`zmq.Again` propagates into the FastAPI route, producing a bare 500 rather than
the documented `{"error": {"code": …}}` envelope, and giving the client no way
to distinguish "engine busy, retry" from "server bug". `send_cancel`,
`send_amend` and the other senders in the same class share the shape.

**Fix.** Mirror the ALF treatment: catch `zmq.Again` and return a 503 with
`ENGINE_UNAVAILABLE`. Retryable congestion and a server defect are different
things and clients act on them differently.

**Fixed.** All 24 send sites in `EngineClient` now route through one
`_send(frames, *, require_engine=True)`, which raises
`HTTPException(503, ENGINE_UNAVAILABLE)` — the same envelope the routers
already use for its sibling condition `ENGINE_TIMEOUT`. `zmq.Again` *and*
`ZMQError` carrying `EAGAIN` are both caught, because the former is a subclass
of the latter but not every EAGAIN arrives as one; ALF guards both. Any other
`ZMQError` still propagates: "engine busy, retry" and "something is broken"
must not collapse into one answer.

Three things the fix had to get right beyond the sketch:

- **`require_engine=False`** for the shutdown disconnect in `main.py`. That
  call sits in a `finally` block *above* the two `stop_listener()` calls — a
  503 raised there would have skipped them and leaked both reader threads, and
  "the engine is already gone" is the ordinary case at shutdown.
- **A closed socket returns quietly.** Shutdown ordering can close `_push`
  first.
- **`authenticate()` cleaned up its waiter.** It registers a future *before*
  sending (the SUB reader is a separate thread and could otherwise resolve the
  reply before we were listening). A send that now raises would have orphaned
  that waiter, so clients retrying against a down engine would accumulate
  them without bound. The cleanup already written inline in `await_event` was
  extracted to `_drop_pending` and reused. The symbols request *after* a
  successful handshake is deliberately best-effort: the engine accepted the
  handshake, so the gateway is authenticated, and failing the whole
  authentication over a cache-seeding convenience would be wrong.

Six of the seven tests in `tests/test_api_gateway_backpressure.py` fail
against the unfixed code; the seventh is the negative assertion that a real
`ZMQError` is still not masked.

---

## E5 — Maintenance flushes sit outside the loop's exception handling *(FIXED)*

**Severity: E-LOW** on its own; it is a second route into E1/E2.

`_flush_snapshots()`, `_flush_circuit_breakers()`, `_flush_auction_indicative()`
and `_flush_debug_summary()` all run unguarded on every tick. Each publishes on
`pub_sock`; a `zmq.ZMQError` there — or any defect in the auction-indicative
calculation, which is the newest of the four — terminates the loop and takes
the resting book with it (E2).

**Fix.** Once E1's guard exists, extend the same treatment to the flush block.
A failure to publish a snapshot should degrade market data, not end the
session.

**Fixed.** The five flushes moved into `Engine._run_maintenance()`, guarded
**per call rather than as a block**: a failure to publish market data must not
skip the circuit-breaker timers behind it, since those resume halted symbols
and are a safety function, not a convenience. Failures increment
`_flush_error_count` and log at ERROR.

Extracting a method rather than wrapping the loop body in place was deliberate.
The first version of the test mirrored `run()`'s body — the same shape as the
E1 test — which meant it exercised a copy of the logic and would have passed
against unfixed source. A named method the test can call directly removes that
blind spot, and both E5 tests were confirmed to fail once `_run_maintenance`
is reduced to bare calls.

The error path logs `getattr(flush, "__name__", "?")`, not `flush.__name__`.
That is not defensive noise: the first test run raised `AttributeError` *inside
the except block*, which would defeat the guard entirely — the precise failure
mode this finding is about.

---

## 6. Race conditions

**There are none of the classic kind, by construction.** `grep` for
`threading`, `Thread(`, `Lock()` and `asyncio` across `engine/` returns
nothing: the engine is a single-threaded poll loop, and every handler runs to
completion before the next message is read. Order-book mutation, publishing and
persistence cannot interleave.

The signal handlers are correctly written for this model, and the reasoning is
recorded in the code:

```python
# Signal handlers only set the stop flag.  Calling _shutdown() directly
# from a signal handler is unsafe: the handler can interrupt mid-message
# (e.g. inside _handle_new_order) and close pub_sock while the handler
# still holds references, causing unhandled ZMQErrors in _flush_snapshots.
```

That is exactly right, and it is the one genuine reentrancy hazard in a
single-threaded design.

The residual ordering hazards are logical rather than concurrent:

- **Publish-then-persist.** Fills are published before `_shutdown()` persists.
  A crash between them leaves subscribers holding trades the restarted engine
  has no record of. This is inherent to publishing before durability and is
  the same class as E2.
- **Cross-process.** The engine's ordering guarantees stop at its PUB socket;
  ZeroMQ drops silently past the high-water mark. The statistics work added
  per-topic sequence numbers so subscribers can *detect* that, which is the
  right mitigation short of a replayable journal.

---

## 7. What I checked and found sound

Recorded deliberately: a beta decision needs to know where the engine is
strong, not only where it is weak.

| Area | Finding |
|---|---|
| **Duplicate order IDs** | Rejected before reaching the book — `"Duplicate order id"`, tagged `A4`, with a comment explaining that a retry would otherwise double liquidity |
| **Cancel ownership** | A gateway may only cancel its own orders; verified explicitly, with a clear reject reason |
| **Input validation** | Positive quantity, positive price where the type requires one, iceberg `visible_qty` bounds — tagged `M7`, all *before* the positive ACK so malformed orders never rest |
| **Queue priority** | `_HeapEntry` carries an engine-assigned arrival sequence, explicitly so a client cannot back-date `timestamp` to jump the queue (`H1`) |
| **Auction aggressor** | Uncross prints carry a neutral `AUCTION` marker rather than a misleading aggressor (`L9`) |
| **Turnover accumulation** | Accumulated in integer ticks and converted once at the boundary, explicitly to avoid float drift (`M11`) |
| **Combo / OCO cascades** | Cancel and expiry both cascade to siblings and parents, on the shutdown path too |
| **Dispatcher taxonomy** | Unknown topics counted separately from handler errors, so a routing gap is distinguishable from a runtime fault |

---

## 8. Coverage and limits of this review

Stated plainly so the sign-off is not over-read.

**Reviewed closely:** the run loop and dispatch boundary; persistence and its
call sites; the gateway PUSH paths; order validation and the cancel path;
threading and signal model; the constants governing backpressure.

**Sampled, not exhaustively verified:** the matching algorithm itself
(`order_book.py`, 1 469 lines) — heap invariants, iceberg replenishment,
trailing-stop recalculation, FOK/IOC edge semantics; the auction uncross
(`auction.py`); collar and circuit-breaker arithmetic; `config_loader.py`
(1 315 lines).

**Not reviewed:** drop-copy replay semantics; the gateway protocols
themselves; performance under load.

The matching algorithm is the largest unreviewed surface and the one where a
defect is most costly. It carries prior review tags and a substantial test
suite, which is reassuring but is not the same as having been read for this
review. If beta is gating on one more piece of work, that is where I would
spend it.

---

## 9. Recommendation

**E1, E2 and E3 should be fixed before beta.** All three are small, localised
changes in the run loop and dispatcher — collectively perhaps 40 lines — and
each addresses either silent data loss or a broken protocol contract. E1 in
particular is reachable by any participant who can connect to `:5555`, without
authenticating, and its blast radius is the entire resting book.

E4 and E5 are worth doing in the same change since they touch the same code
and the same failure taxonomy.

Nothing found requires architectural change. The engine's structure — single
threaded, validate-before-ACK, explicit ownership checks — is sound, and the
defects are all at the one seam that the hardening applied to the handlers has
not yet reached.

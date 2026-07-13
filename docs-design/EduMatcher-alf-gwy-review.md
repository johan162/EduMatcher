# ALF Gateway Code Review

**Scope:** `src/edumatcher/alf_gwy/` (`gateway.py`, `protocol.py`, `config.py`, `main.py`), plus its dependencies `messaging/bus.py`, `models/price.py`, and `models/message.py`.

**Date:** 2026-07-13

**Subject:** `pm-alf-gwy` — public-facing ALF gateway that accepts the ALF text protocol over a TCP/IP connection and bridges traffic to/from the engine ZMQ bus.

---

## Overall assessment

The design is fundamentally sound for a public-facing gateway. It uses a **single-threaded reactor** (`accept → read → poll engine → heartbeat → flush → drop-idle → sleep`), which is a good choice because it sidesteps almost all in-process data races: all client state and engine I/O happen on one thread, so there are no locks to get wrong. Parsing is defensive (bounded line length, NaN/Inf rejection, integer range clamping, UTF-8 guarding, error-window disconnect, slow-client queue cap).

The flip side of that single-threaded design is the biggest risk: **any blocking call in the loop freezes the entire gateway**, and there is one such call that can block. The other significant issues cluster around the **pre-authentication phase**, which is under-defended for something exposed to untrusted TCP peers.

No true in-process race conditions were found in the client-handling code — the reactor prevents them, and the iterations that mutate `self._clients` correctly snapshot with `list(...)`. The "race" risks are instead **state desyncs between the gateway and the engine** across the asynchronous auth handshake.

---

## Critical

### C1. Blocking send to the engine can hang the whole gateway

`make_pusher` (`bus.py`) creates a `zmq.PUSH` socket with default options (no `SNDTIMEO`, no `SNDHWM` override), and `_send_to_engine` calls `send_multipart` in blocking mode:

```python
def _send_to_engine(self, frames, *, count_as_command=True):
    try:
        self._push.send_multipart(frames)   # blocking
    except zmq.ZMQError:
        ...
```

ZMQ `PUSH` blocks when the message cannot be queued — i.e. when **no peer is connected** (engine down at startup, or it restarts/disconnects) or when the peer's high-water mark is reached (engine slow/stalled). Because everything runs on one thread, a single blocked `send_multipart` freezes accept, reads, heartbeats, flushes, and idle-eviction for *every* connected client, and stops new connections. The `except zmq.ZMQError` never fires for a blocking stall — it only helps on `EINTR`.

For a public-facing gateway this is the highest-impact bug: engine unavailability or backpressure turns into a full gateway outage rather than graceful degradation.

**Fix:** set `SNDTIMEO` (and likely a bounded `SNDHWM`) on the push socket, or send with `zmq.DONTWAIT`, and handle `EAGAIN` by rejecting the command (e.g. `ENGINE_UNAVAILABLE`) instead of blocking.

---

## High

### H2. Pre-auth HELLO amplification / unbounded resource growth

Before authentication, `_handle_client_line` routes every line to `_handle_hello` as long as the command is `HELLO`, and the per-command rate limiter (`_allow_command_now`) is only applied *after* auth. Each HELLO with a fresh `ID`:

- sends `make_gateway_connect_msg` to the engine (`count_as_command=False`, so it is not even counted),
- calls `_subscribe_topic("system.gateway_auth.<ID>")` and appends to `session.subscriptions`,

with no cap. A single unauthenticated TCP peer can loop HELLOs with distinct IDs to flood the engine with connect messages and grow `session.subscriptions` / `_topic_refcounts` without bound (they are only released on disconnect). This is an amplification and memory-exhaustion vector from an unauthenticated client.

**Fix:** rate-limit (and count) pre-auth lines too; reject a second HELLO on an already-HELLO'd session instead of re-processing it.

### H3. Gateway↔engine state desync when a session dies mid-handshake

`_handle_hello` emits `gateway_connect` to the engine, but `_disconnect` only emits `gateway_disconnect` when `session.authenticated` is true:

```python
if gateway_id and session.authenticated:
    self._send_to_engine(make_gateway_disconnect_msg(gateway_id, reason=reason), ...)
```

If the client disconnects (or idle-times-out) while `auth_pending` — after `gateway_connect` was sent but before/around the auth reply — the engine gets a connect with no matching disconnect. Symmetrically, if the auth reply arrives after the session is gone, `_handle_gateway_auth` finds no pending session and returns, but the engine already considers the gateway authenticated. Either way the engine can leak a "connected" gateway, which can also block the *next* legitimate connection for that ID. This is the closest thing to a race in the engine interaction.

**Fix:** send `gateway_disconnect` whenever `gateway_id` is set and a connect was emitted (track a `_connect_sent` flag), regardless of `authenticated`.

### H4. No pre-authentication / handshake timeout (slowloris)

`last_activity` is refreshed on *any* inbound bytes (`_read_client_data`), and the only eviction is `idle_timeout_sec` against `last_activity`. A client that dribbles one byte every `< idle_timeout` seconds (default 30s) — never sending a full HELLO — holds a connection slot indefinitely. With `max_connections` default 64, ~64 such peers exhaust the pool and deny service to legitimate clients.

**Fix:** enforce a short, separate handshake deadline (time from connect to successful auth), independent of the idle timer.

---

## Medium

### M5. Symbol validation window / shared global registry

`_validate_symbol` only rejects unknown symbols once `_known_symbols` is non-empty, which is populated asynchronously by the first `SYMBOLS` response. Orders sent between auth and that response bypass symbol validation. Also `_known_symbols` and the `price.py` tick registry are process-global/shared across gateways and mutated from engine responses — fine functionally, but worth a comment since it is shared mutable state.

### M6. `_poll_engine_events` drains the whole SUB queue per iteration and can crash the loop

`while self._sub.poll(timeout=0):` processes all pending engine messages before returning to client I/O, so an engine burst can starve clients for that iteration. Additionally, a non-`EINTR` `zmq.ZMQError` is re-raised and propagates out of `run()`'s loop, tearing down the gateway.

**Fix:** bound messages-per-iteration and handle unexpected ZMQErrors without process teardown.

### M7. Self-inflicted disconnect on duplicate HELLO for the same ID

While `auth_pending`, a second HELLO for the *same* gateway hits `_gateway_in_use(...) == True` and returns `GATEWAY_ALREADY_CONNECTED` with `close_connection=True`, closing the client's own in-flight session. A retrying client gets disconnected rather than a benign "already authenticating" response.

---

## Low

- **L8. Busy-poll with fixed `time.sleep(0.01)`** instead of a `select`/`poll` timeout adds up to ~10ms latency per step and constant wakeups. `select.select` also caps at `FD_SETSIZE` (~1024) — fine at `max_connections=64`, but a latent ceiling if raised. Consider a timeout-driven `select` covering both readable and pending-write sockets.
- **L9. Global uppercasing of all field values** in `parse_alf_line` (`value.strip().upper()`) also uppercases the `CLIENT` name and any free-text — cosmetic surprise, and means client identifiers cannot preserve case.
- **L10. Post-`closing` lines are still processed.** After `EXIT`/auth-failure sets `closing=True`, `_drain_lines` keeps parsing the rest of the buffer and queuing responses/errors that will not be usefully consumed. Minor wasted work.
- **L11. `_send_to_engine` re-raises ZMQError** except during shutdown — related to C1; once C1 is fixed with a timeout, ensure the `EAGAIN`/error path degrades gracefully rather than raising into the loop.
- **L12. Redundant 4096-byte checks** in both `_read_client_data` and `_drain_lines` (harmless, slightly confusing).

---

## Coherence / maintainability

Strengths worth keeping: the single-threaded reactor (call this out explicitly in a module docstring as the concurrency contract — "no blocking calls allowed in the loop"), the refcounted subscription helpers, the token-bucket limiter, and the clean protocol/validation split in `protocol.py`.

Suggestions:

- Document the **auth state machine** (`auth_pending` vs `authenticated`, and what `gateway_connect`/`gateway_disconnect` must bracket). This is the subtlest part of the code and currently has no explaining comment; H3 is a direct consequence.
- Document the **`fileno`-as-dict-key** assumption. It is currently correct because `_disconnect` reads `fileno()` before `close()` and removes the entry, but the invariant (no closed-socket fileno reuse while still keyed) deserves a comment since it is fragile.
- `_dispatch_authenticated` and especially `_route_gateway_scoped_event` are long if/elif ladders. A dispatch table (`{prefix: (msg_type, field_mapper)}`) would make the topic→message mapping easier to audit and extend.
- Add a comment on `_known_symbols` / tick registry being process-global shared state.

---

## Priority to fix

1. **C1** (engine send can hang the gateway) — do this first; it is the difference between graceful degradation and a full outage.
2. **H4** and **H2** (pre-auth slowloris + HELLO amplification) — the main untrusted-input exposure.
3. **H3** (connect/disconnect bracketing) — the engine-state correctness issue.

---

## Findings summary

| ID | Severity | Area | Summary |
|----|----------|------|---------|
| C1 | Critical | Engine I/O | Blocking `send_multipart` on PUSH can freeze the whole single-threaded gateway when the engine is down/slow/backpressured. |
| H2 | High | Pre-auth | Repeated HELLO (not rate-limited pre-auth) amplifies `gateway_connect` to engine and grows subscriptions unbounded. |
| H3 | High | Handshake | Session dying while `auth_pending` sends `gateway_connect` but never `gateway_disconnect` → engine state leak/desync. |
| H4 | High | Pre-auth | No handshake timeout; byte-dribbling holds connection slots (slowloris), exhausting `max_connections`. |
| M5 | Medium | Validation | Symbol validation bypassed until first `SYMBOLS` response; `_known_symbols`/tick registry are shared global state. |
| M6 | Medium | Engine I/O | `_poll_engine_events` drains all messages per pass (client starvation) and re-raises unexpected ZMQError, crashing the loop. |
| M7 | Medium | Handshake | Duplicate HELLO for same ID while pending closes the client's own connection. |
| L8 | Low | Loop | Fixed 10ms busy-poll adds latency; `select` FD_SETSIZE ceiling. |
| L9 | Low | Protocol | All field values force-uppercased, including `CLIENT` name. |
| L10 | Low | Read path | Buffered lines still processed after `closing` is set. |
| L11 | Low | Engine I/O | `_send_to_engine` re-raises ZMQError outside shutdown. |
| L12 | Low | Read path | Redundant 4096-byte line-length checks. |

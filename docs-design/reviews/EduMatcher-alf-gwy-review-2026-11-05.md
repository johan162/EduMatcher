# ALF Gateway Review — 2026-11-05

**Scope:** `src/edumatcher/alf_gwy/` (`gateway.py`, `protocol.py`, `config.py`, `main.py`) at `6505def0`, plus the parts of `messaging/bus.py`, `messaging/reject_report.py`, `models/message.py` and `models/price.py` it depends on.

**Focus:** correctness, performance, corner cases, and above all **information loss** (events a client should have received but did not, or received corrupted).

**Previous review:** `EduMatcher-alf-gwy-review.md` (2026-07-13). Its C1, H2–H4, M5–M7 fixes are in place: PUSH is `SNDTIMEO=0/IMMEDIATE`, pre-auth is rate-limited, `connect_emitted` brackets connect/disconnect, there is a handshake deadline, and the SUB drain is bounded. **L10 is not fixed** (see L4 below).

**Method:** read every line; reproduced each finding marked *(repro)* with a scratch script that drives `AlfGateway` with fake ZMQ sockets and real `socketpair()`s.

---

## Summary

| ID | Sev | Area | Finding |
|----|-----|------|---------|
| H1 | High | Engine I/O | A single malformed engine event raises out of `_poll_engine_events` and takes the whole gateway down *(repro)* |
| H2 | High | Info loss | Engine events can be silently dropped at the SUB high-water mark, and the gateway ignores the per-topic sequence numbers that would detect it |
| H3 | High | Info loss / slots | A closing session whose peer stops reading is never disconnected; its gateway ID stays locked out *(repro)* |
| M1 | Med | Info loss | SLOW_CLIENT overflow discards a half-sent line and glues the ERR onto it, so the client gets a corrupt frame *(repro)* |
| M2 | Med | Info loss | SLOW_CLIENT drops private events (FILL/ACK) along with public broadcasts that caused the overflow |
| M3 | Med | Info loss | Shutdown closes sockets without flushing `out_queue` or draining the SUB socket |
| M4 | Med | Robustness | `accept()` errors other than `EAGAIN` (`EMFILE`, `ENFILE`, `ECONNABORTED`, ...) crash the loop |
| M5 | Med | Perf | Every gateway's private events are JSON-decoded before routing finds there is no session for them |
| L1 | Low | Correctness | A second `POS` overwrites the pending one; the first reply is silently dropped *(repro)* |
| L2 | Low | Correctness | HELLO `ID` charset is not validated; an ID containing `.` is routed by its suffix, which can leak to another session *(repro)* |
| L3 | Low | Robustness | Absurd prices (`PRICE=1e300`) give `INTERNAL_ERROR` plus a full traceback in the log, per message *(repro)* |
| L4 | Low | Correctness | Lines after `EXIT`, or after an auth failure, are still processed and forwarded *(repro)* |
| L5 | Low | Parsing | After an over-long line is discarded, its tail is parsed as a fresh command |
| L6 | Low | Design | Rate-limit refusals count towards `MAX_ERRORS`, so a bursty client is disconnected |
| L7 | Low | Parsing | `safe_int`/`safe_float` accept `1_000` and non-ASCII digits (`１００`) |
| L8 | Low | Info loss | `DC|ON` has no replay or resume-from-seq; fills during the gap are lost from the DC channel |
| L9 | Low | Engine I/O | Engine heartbeats/disconnects dropped at PUSH HWM are silent, and `last_engine_heartbeat` advances anyway |
| P1–P3 | Low | Perf | Minor per-message/per-tick overheads |

---

## High

### H1. One bad engine event kills the gateway *(repro)* **fixed**

`_poll_engine_events` wraps only `decode()` in `try`. Every handler after it (`_route_gateway_scoped_event`, `_handle_symbols_response`, `_handle_session_probe`, `_broadcast`, ...) runs unprotected, and `run()` has only `try/finally`. Any exception therefore leaves the loop, `main()` logs "fatal runtime error" and re-raises, and **every connected session is dropped with its queued output** (see M3).

Payloads that do this today:

| Event | Payload | Exception |
|---|---|---|
| `order.triggered.<GW>` | no `stop_price_ticks` | `KeyError` (`int(payload["stop_price_ticks"])`, gateway.py:1872) |
| `order.fill.<GW>` | `"trade_ids": null` | `TypeError` (gateway.py:1835) |
| any routed event | a `reason`/`symbol`/... containing `|` | `AlfProtocolError` from `build_line` |
| `system.symbols.<GW>` | `"symbols": null` | `TypeError` (gateway.py:1557) |
| `system.gateways.ALF-PROBE-n` | `"gateways": null` | `TypeError` (gateway.py:2019) |

None of these is produced by today's engine as far as I can see, so this is a robustness bug rather than a live crash. But the blast radius (all clients, all queued fills) is out of all proportion to the trigger (one schema drift, one free-text reason containing `|`), and the same loop already treats undecodable frames as "log and continue".

**Fix:** wrap the per-event dispatch (everything after `decode`) in `try/except Exception: log.exception(...); continue`, same as the drop-copy loop needs. In `build_line`, replace `|` in *values* with a placeholder rather than raising. Raising is right for keys we write ourselves, wrong for engine text being relayed. Add one regression test per row of the table.

### H2. Silent loss of private events at the SUB high-water mark

The fix for the subscribe-race (gateway.py:296–302) subscribes to **every gateway-scoped prefix for every gateway**: `order.ack.`, `order.fill.`, `order.cancelled.`, ... So this SUB socket carries the private order stream of the *whole exchange* (REST, BALF, mm-bot, AI traders), not just ALF's sessions. On top of that come `trade.executed` and the rest.

Neither side raises the high-water mark (`make_subscriber(...)` without `rcvhwm`, and the engine PUB has no `SNDHWM` set), so both stay at ZMQ's default of 1000 messages. When the gateway loop falls behind (a logon burst, a large `_broadcast` fan-out, GC), the engine's PUB **silently drops** messages for this subscriber. A dropped `order.fill.<GW>` is a fill the client never learns about. Nothing tells the client; it has no fill replay over ALF (`ORDERS` shows remaining quantity, not the fills or their prices).

The publisher already stamps a per-topic sequence in frame 2 (`SequencedPublisher`, `decode_sequence`). The topics are per gateway (`order.fill.T1`), so gaps for one session can be detected exactly, and the gateway currently throws that frame away.

**Fix (in order of value):**
1. Set `rcvhwm` on `self._sub` (pm-audit uses 200 000) so bursts are absorbed rather than dropped.
2. Track `decode_sequence()` per topic for topics that route to a live session. On a gap, send the session a line such as `ERR|CODE=EVENTS_LOST|REJECT_CODE=...|DETAIL=<topic> missed N` (or a dedicated `GAP|...` line), so the client knows to reconcile with `ORDERS`. A decrease is an engine restart, not a gap (see the class docstring).
3. Count gaps in `_global_stats` so the operator dashboard shows them.

### H3. A closing session whose peer does not read is never reaped *(repro)* **fixed**

A session is removed only by `_flush_client_writes` once `out_queue` is empty, or by a send/recv error. Nothing enforces a deadline on `closing`. If the peer stops reading while its socket is still open (a hung or `SIGSTOP`ped agent, a client blocked on something else while the public feed fills its window), the kernel send buffer stays full, the socket stays write-blocked, and:

- `_drop_idle_clients` queues another `ERR|CODE=IDLE_TIMEOUT` **every 100 ms housekeeping tick**. For a never-authenticated socket it is `AUTH_TIMEOUT` instead, also every tick.
- `_send_heartbeats_if_due` queues an `HB` **every tick**, because `last_outbound` never advances.
- Every overflow clears the queue (SLOW_CLIENT) and the cycle restarts. In the repro there were 5 SLOW_CLIENT cycles in 300 ticks, and the session was still connected.
- `_active_gateway_sessions` still holds the ID, so the **same participant reconnecting gets `GATEWAY_ALREADY_CONNECTED`** until the old process dies.
- Engine heartbeats stop (closing sessions are skipped), so the engine expires the ID. The probe then calls `_drop_lost_session`, which only queues more lines.

The half-open (dead peer) case is mostly safe: with free space in the kernel buffer the final ERR is accepted, the queue empties and the session closes. The leak needs a full buffer, which is the slow-reader case.

**Fix:** record `closing_since` in `_close_after_flush` and `_queue_raw`'s overflow branch. In housekeeping, hard-`_disconnect` any session with `closing` set for more than a few seconds (2–5 s). Skip closing sessions in `_drop_idle_clients` and `_send_heartbeats_if_due`, and stop `_queue_raw` from appending to a closing session (see M1).

---

## Medium

### M1. SLOW_CLIENT overflow corrupts the frame on the wire *(repro)* **fixed**

`_queue_raw`'s overflow branch does `out_queue.clear(); out_offset = 0` even when the head line is partly sent. The client then receives the first half of that line followed directly by the ERR:

```
FILL|ORDER_ID=abERR|CODE=SLOW_CLIENT|DETAIL=Outbound queue full - disconnecting\n
```

The client parses this as a `FILL` with a wrong `ORDER_ID` and no quantity, and **never sees the SLOW_CLIENT error**. Had the cut fallen right after a `|`, it would parse as a well-formed `FILL` carrying `CODE=`/`DETAIL=` fields. Separately, after the overflow `_queue_raw` keeps appending to the closing session, so the "disconnecting" line can be followed by more events.

**Fix:** keep the remaining bytes of the head when `out_offset > 0`, i.e. replace it with `payload[out_offset:]` and set `out_offset=0`, then append the ERR. Make `_queue_raw` a no-op once `session.closing` is set (the ERR/close paths that legitimately queue after setting `closing` must queue first).

### M2. SLOW_CLIENT discards fills together with the noise

An overflow is almost always caused by the public feed (`TRADE` per print, `HALT`, `SESSION`) on a `FEED=ALL` session. The overflow clears *everything*, including the `FILL`/`ACK`/`CANCELLED` lines that matter, and the client has no way to recover the fills (see H2).

**Fix (pick one):** when trimming, drop public broadcast lines first and keep private lines (mark them when queuing, e.g. a second deque or a flag tuple); or give public broadcasts their own, smaller cap, so a slow feed reader loses trades, not fills. Either way, the ERR should say how many private events were lost.

### M3. Shutdown throws away queued output

`close()` calls `_disconnect` on every session straight away. Lines still in `out_queue`, and events still sitting in the SUB socket, are discarded. On a planned restart, every fill the engine published in the last moments is lost to its client.

**Fix:** in `run()`'s exit path, before `close()`: drain `_sub`/`_dc_sub` once (bounded), queue a final `ERR|CODE=GATEWAY_SHUTDOWN` (or similar), then loop `_flush_client_writes` with a short deadline (e.g. 1–2 s) before disconnecting. Also `main()` calls `gateway.close()` a second time after `run()`'s own `finally`; harmless today, but it should be idempotent by intent, not by accident.

### M4. `accept()` errors crash the gateway **fixed**

`_accept_new_clients` catches only `BlockingIOError`. `ConnectionAbortedError`, `EMFILE`/`ENFILE` (fd exhaustion — `_FD_HEADROOM` covers our own use, not the system table), `ENOBUFS`, `EPERM` all propagate out of `run()`. `conn.setsockopt(TCP_NODELAY)` on an already-reset socket can raise too.

**Fix:** catch `OSError` around `accept()`. Log it and `break` (on `EMFILE`/`ENFILE` the listener stays readable, so breaking prevents a hot loop; the next tick retries). Wrap the per-connection setup in `try/except OSError: conn.close(); continue`.

### M5. Decode cost for events nobody here wants

Because of the all-gateways subscription (H2), most messages on `self._sub` are for gateways with no session on this ALF instance. Each is still fully decoded (`decode()` → orjson) before `_route_gateway_scoped_event` looks up the session and discards it. Under a busy simulation that is the bulk of the gateway's engine-side CPU, and it directly feeds H2: a slower loop means more HWM drops.

**Fix:** peek at `frames[0]` first. For gateway-scoped prefixes, take the suffix and `continue` without decoding when `_active_gateway_sessions` has no entry and there is no pending auth (`system.gateway_auth.*`), symbols (`system.symbols.*`, which also refreshes the shared cache) or POS reply (`system.position_snapshot.*`) to wait for. A per-topic routing cache (`dict[bytes, handler]`) would also remove the `startswith` ladder.

---

## Low

- **L1. POS overwrite** *(repro)*. `pending_position_query` holds one target; `POS|GW=A` then `POS|GW=B` returns only B, and A's reply is dropped silently. Use a small set/counter per target, or reject the second with `POS_ALREADY_PENDING`. Note also, as already documented, that any ALF session can read any gateway's positions. That is a deliberate choice, but for a public-facing gateway it deserves a role check.
- **L2. Gateway ID charset** *(repro)*. `validate_hello_fields` accepts any characters. Routing takes `topic.rsplit(".", 1)[-1]`, so an ID `A.B` gets its events routed to session `B` (the repro delivers `A.B`'s fill to `B`). `config_gen` enforces `^[A-Z][A-Z0-9_]{0,31}$`, but `engine/config_loader.py` only checks non-empty, so a hand-written config can contain such an ID. Apply the same regex at HELLO (it also subsumes the 32-char check) and ideally in the engine loader.
- **L3. Huge prices** *(repro)*. `to_ticks_exact` returns an unbounded int; orjson then raises "Integer exceeds 64-bit range" inside the generic handler. The client gets `INTERNAL_ERROR` instead of `INVALID_VALUE`, and **each such line writes a full traceback** via `log.exception`, so a client can flood pm-log-srv at the command rate. Bound `abs(ticks)` in `_ticks` (the spec's int range) and raise `INVALID_VALUE`.
- **L4. Lines processed after close** *(repro)*. `_drain_lines` keeps dispatching after `EXIT`, after `AUTH_REQUIRED`/`AUTH_FAILED`, and after `MAX_ERRORS`; `EXIT\nNEW|...` forwards the order. Check `session.closing` at the top of the loop and discard the rest of the buffer. (The previous review's L10 is marked fixed but is not.)
- **L5. Over-long line tail.** `_read_client_data` clears a newline-less buffer over 4096 bytes, but the rest of that line, when it arrives, is parsed as a new command. Keep a `discarding` flag until the next `\n`.
- **L6. Rate-limit refusals feed `MAX_ERRORS`.** At the defaults (100/s, 50 errors per 60 s), one burst of 150 commands disconnects the client; fills that arrive after the disconnect are lost to it. Consider not counting `RATE_LIMITED` towards the error window, or a separate, higher threshold.
- **L7. Lenient numbers.** Python's `int()`/`float()` accept `1_000` and Unicode digits (`QTY=１００` → 100). Not dangerous, but not ALF either; a `str.isascii()` check plus a regex in `safe_int`/`safe_float` closes it.
- **L8. Drop copy has no resume.** `DC|ON` subscribes live only; the `DC_ACK` is sent before the async ZMQ subscription takes effect, and fills during any reconnect are never replayed although they carry `SEQ`. Document the gap or expose a `DC|ON|FROM_SEQ=` replay.
- **L9. Silent engine-side drops.** `_send_to_engine(..., require_engine=False)` swallows `EAGAIN` for heartbeats, disconnects and probes. All sessions' heartbeats fire in the same tick after a logon burst (up to `max_connections` messages against a PUSH HWM of 1000). If that coincides with backpressure, heartbeats are dropped while `last_engine_heartbeat` still advances; a few lost rounds expire sessions and the probe then drops them. Count these drops in `_global_stats`; spread heartbeats by jittering the initial `last_engine_heartbeat`.

## Performance (minor)

- **P1.** `self._sub.poll(timeout=0)` plus `recv_multipart()` per message; `recv_multipart(zmq.NOBLOCK)` with `except zmq.Again: break` is one call instead of two. Same for `_dc_sub`.
- **P2.** `_broadcast` scans all clients per trade print. Keep a set of authenticated `FEED=ALL` filenos.
- **P3.** `_find_pending_auth_session` and `_gateway_in_use` are O(N) per HELLO/auth reply, which makes a logon burst O(N²). A `dict[gateway_id, fileno]` for pending sessions makes both O(1). `_has_pending_writes` builds a set difference every loop iteration; `len(self._dirty) > len(self._write_blocked)` is equivalent because `_write_blocked ⊆ _dirty`.

---

## Verified as correct

- Auth state machine: connect/disconnect bracketing via `connect_emitted`, reject clears it, late auth replies after a reconnect resolve consistently (same ID, ordered PUSH).
- fileno-as-key handling: `_disconnect` reads `fileno()` before `close()`; `ready` and `writable` are re-validated against `_clients`.
- Edge-triggered ZMQ FD handling: `zmq.EVENTS` is checked before each `select`, so a capped drain is never stranded.
- Tick-grid enforcement on NEW/OCO/COMBO/QUOTE, and on AMEND in the engine (`_handle_amend` uses `to_ticks_exact`).
- `RejectReporter.report` never raises.
- Probe logic (`authenticated_at < sent_at`) cannot drop a session whose connect the engine has not yet processed.

## Suggested fix order

1. **H1** (crash containment) and **M4**: cheap, and they remove the "one bad input kills every session" class.
2. **H3** + **M1**: same code path (`closing` handling); fix together.
3. **H2**: RCVHWM first (one line), then sequence-gap detection.
4. **M2**, **M3**: information-loss hardening.
5. **M5** and the Low items.

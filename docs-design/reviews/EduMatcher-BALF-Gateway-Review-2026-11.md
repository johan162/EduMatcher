# pm-balf-gwy Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/balf_gwy/` at `75d64363` (v0.79.0): `gateway.py`
(1 722 lines, the TCP loop, sessions, logon, request and event handlers),
`codec.py` (498, frame layouts and builders), `translate.py` (218, BALF ↔
engine dicts), `protocol.py` (192, field validation and the reject
classifier), `config.py` (208) and `main.py` (206, the CLI). The generated
BALF serialisers (`models/generated/order.py`:
`serialise_execution_report_balf`, `serialise_stop_triggered_balf`), the
engine payloads the gateway reads (`spec/messages/order.yaml`:
`order.ack`, `order.fill`, `order.cancelled`, `order.amended`), the engine's
symbol and amend handlers (`engine/main.py:2488`, `engine/main.py:7048`) and
`messaging/bus.py` were read where they decide this gateway's behaviour, not
reviewed as code of their own.

**Focus:** correctness, edge-case handling, performance, and whether the
comments, help texts, the operator guide chapter
(`docs/books/operator-guide/part-5-gateways/020-balf-gateway.md`) and the
protocol specification
(`docs/books/protocols-and-clients/part-2-specifications/020-balf.md`) say
what the code does.

**Previous work:** the key-component fixes K11 (symbol-metadata gate before
`LOGON_ACK`, engine-restart reconciliation), K12 (per-request `request_tag`
correlation, `EVICT_OLD` covers pending sessions), K16 (engine drain budget,
unused subscriptions dropped) and K17 (strict config coercion), in
`docs-design/EduMatcher-Key-Component-Fixes-Workplan.md`; the reject
classifier fix `94e016f8`; R3 (symbols request failure). Their fixes are in
place and are not repeated here. The ALF gateway review
(`EduMatcher-alf-gwy-review-2026-11-05.md`) fixed in pm-alf-gwy several
defects this review finds again in pm-balf-gwy (its H2, H3, M1, M2/M3); they
were never ported.

**Method:** every line of the files above was read. Findings marked *(repro)*
were reproduced with scratch scripts against the tree at `75d64363`. Most
drive a real `BalfGateway` wired to a real `Engine`
(`tests/engine_harness.make_engine`, with the engine's `_load_config()` so
books exist): client frames go through `BalfGateway._drain_frames` exactly as
read off TCP, and every payload the gateway sees is one the engine published.
The ZMQ findings use the real bus factories (`make_publisher`,
`make_subscriber`, `make_pusher`) over TCP on localhost. *(measured)* means
timed on this host with the real gateway thread, real TCP and a fake engine
thread that answers each `order.new` at once. The other findings are by
inspection, with line numbers given.

Status: **Done, uncommitted** (2026-11-15). Decisions Q1–Q5 taken as
recommended. Last full suite 14 435 passed, 1 skipped; `make _check` and
`mkdocs build` clean. Beyond the plan: the order map is kept across engine
restarts (WP-BALF01), LOGOUT bypasses the rate limit (WP-BALF05), the engine
is told on LOGOUT rather than after the flush (WP-BALF04), two stale guide
passages (WP-BALF09); new wire codes 0x0D, 0x0E and `cancel_reason` 1–8/254.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (frames the client receives, messages the engine
   receives, the session table, the health metrics).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_balf_gwy_*.py`,
   `tests/test_msgen_balf_roundtrip.py` and
   `tests/test_examples_balf_alf_current.py` with `-n logical`, then
   black/flake8/mypy/pyright. Do not start the next WP with a known failing
   test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Session-level tests should drive a real engine: `make_engine(...)` plus
`engine._load_config()`, a `BalfGateway` whose `make_pusher` and
`make_subscriber` are monkeypatched to in-memory doubles, and a pump that
hands each pushed frame to `engine._dispatch_pull_message` and each published
frame to `gateway._dispatch_engine_event` (the review's scratch `bridge.py`
is about 100 lines and can become `tests/balf_harness.py`). Hand-made engine
payloads hid C1: `tests/test_balf_gwy_unit.py:1034` feeds a fill with a
`timestamp` key the engine stopped sending. Transport tests (loop, ZMQ,
latency) use the `running_gateway` fixture of
`tests/test_balf_gwy_integration.py:272`.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-BALF01 | A resting order stays the client's after a reconnect | H1 | Q1 | 1 d | ☑ | 2026-11-14 |
| 2 | WP-BALF02 | A logon is never lost to the subscription race | C3, C9, C14 | — | 0.5 d | ☑ | 2026-11-14 |
| 3 | WP-BALF03 | Engine events are not dropped silently, nor at shutdown | C5, C6 | Q5 | 0.75 d | ☑ | 2026-11-15 |
| 4 | WP-BALF04 | A closing session always ends | C4, C15 | — | 0.5 d | ☑ | 2026-11-15 |
| 5 | WP-BALF05 | Every request gets an answer | C2, C11 | Q2 | 0.5 d | ☑ | 2026-11-15 |
| 6 | WP-BALF06 | Timestamps, reject codes and cancel reasons the client can use | C1, C7, C8, C13 | Q3 | 1 d | ☑ | 2026-11-15 |
| 7 | WP-BALF07 | The loop waits for work instead of sleeping | P1, C12 | — | 0.75 d | ☑ | 2026-11-15 |
| 8 | WP-BALF08 | Inbound sequence numbers are checked as the spec says | C10 | Q4 | 0.25 d | ☑ | 2026-11-15 |
| 9 | WP-BALF09 | Comments, docstrings, help texts, guides | D1–D10 | WP-BALF01–08 | 0.5 d | ☑ | 2026-11-15 |

Suggested order: **WP-BALF01 → WP-BALF02 → WP-BALF03 → WP-BALF04 →
WP-BALF05 → WP-BALF06 → WP-BALF07 → WP-BALF08 → WP-BALF09**. WP-BALF01 is
the only finding where fills happen and the client is never told. WP-BALF02
to WP-BALF04 close the paths where messages or sessions are lost (the logon
race fails close to half the logons in the repro). WP-BALF05 and WP-BALF06
change wire semantics and need Q2/Q3. WP-BALF07 rewrites the loop and goes
after the behavioural fixes so their tests guard it. WP-BALF08 can break
careless clients and comes late. WP-BALF09 goes last so every text describes
the code as it ends up.

Estimated sequential effort: about 5.75 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The **framing** is sound: bad magic, bad version and unknown `msg_type` close
the connection before a byte of body is read, partial frames wait for more
data, and every body is a fixed size, so a client cannot make the gateway
buffer more than one frame (`gateway.py:486-543`). **Pricing** is safe since
K11: no order is priced before the engine's symbol metadata arrives, an
unknown symbol is refused, and a price off the tick grid is refused, not
rounded (`translate.py:85-100`). **Correlation** of cancels and amends by
`request_tag` works against the real engine (K12; client cancel → `CANCEL_ACK`
accepted with the cancel's own `client_order_id`, *(repro)*). Fill price,
quantity, remaining quantity, side and status map correctly from the engine's
`order.fill` *(repro)*. Engine restarts close every session with a reason.

The defects are in five places:

- **Orders that outlive their session (H1).** BALF order ids and the
  engine-to-BALF map live in the TCP session. The default
  `disconnect_behaviour` (`CANCEL_QUOTES_ONLY`) leaves ordinary orders on the
  book, so after a reconnect a resting order fills and the client receives
  nothing, and it cannot cancel the order either. BALF has no order query.
- **Lost logons and lost events (C3, C5, C6).** The auth topic is subscribed
  per session immediately before `gateway_connect`; ZMQ applies the
  subscription asynchronously and the reply is lost in 137 of 300 logons in
  the repro (10 s of silence, then a close with no `LOGON_ACK`). The SUB
  socket keeps ZMQ's 1 000-message default with no gap check, and a stop
  drops every queued frame. pm-alf-gwy fixed all three in November.
- **Sessions that never end, requests that get no answer (C4, C2).** A
  session that is closing while its peer does not read is skipped by every
  timeout and keeps its gateway ID forever. A rate-limited `NEW_ORDER`,
  `CANCEL_ORDER` or `AMEND_ORDER` is dropped with no frame at all (6 of 10 in
  the repro), although the spec promises an `ORDER_ACK` for every
  `NEW_ORDER`.
- **Figures the client cannot use (C1, C7, C8, C13).** Every
  `EXECUTION_REPORT` carries `timestamp_ns = 0`: the gateway reads a key the
  engine no longer sends. Rejects are classified from the engine's prose, so
  an invalid price becomes `RC_OTHER` with a 25-byte stump of a reason;
  every exchange-initiated cancel is the same `255`; the forwarded-frame
  metric counts every order twice.
- **Latency (P1).** The loop sleeps a fixed 5 ms per pass: a
  `NEW_ORDER` → `ORDER_ACK` round trip takes 10.6 ms median against an engine
  that answers at once, for the protocol the guide recommends for
  "latency-sensitive algos".

Severity key: **High**: a fill or an order state change happens and the
client is not told, with no warning. **Med**: a lost or wrong message or
figure; a session, logon or gateway ID that is stuck or fails without a
reason. **Low**: hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| H1 | High | Sessions | After a reconnect, fills of the earlier session's resting orders are dropped and the orders cannot be cancelled *(repro)* | BALF01 |
| C1 | Med | Fills | `EXECUTION_REPORT.timestamp_ns` is always 0; `ORDER_ACK.timestamp_ns` is the gateway's clock at ack receipt *(repro)* | BALF06 |
| C2 | Med | Requests | A rate-limited request gets no answer and is not counted as an error: 10 orders, 4 `ORDER_ACK`s *(repro)* | BALF05 |
| C3 | Med | Logon | Per-session SUBSCRIBE races the auth reply: 137/300 replies lost, logon times out without `LOGON_ACK` *(repro)* | BALF02 |
| C4 | Med | Sessions | A closing session whose peer does not read is never reaped; its gateway ID stays locked *(repro)* | BALF04 |
| C5 | Med | Events | SUB socket at ZMQ's default HWM, no sequence check: 10 500 of 20 000 fill-sized events lost silently *(repro)* | BALF03 |
| C6 | Med | Shutdown | A stop disconnects every session at once: queued frames and unread engine events are dropped, no `LOGOUT` | BALF03 |
| C7 | Low | Rejects | Rejects are classified from engine prose, not `order.ack.reject_code`: invalid price → `RC_OTHER` *(repro)* | BALF06 |
| C8 | Low | Cancels | Every exchange-initiated cancel is `cancel_reason = 255`; the engine's `cancel_reason` is ignored *(repro)* | BALF06 |
| C9 | Low | Logon | A second `LOGON` while the `LOGON_ACK` waits for symbols is refused as "already connected" against itself | BALF02 |
| C10 | Low | Protocol | Inbound `seq_no` is never checked, although the spec makes a gap a protocol error | BALF08 |
| C11 | Low | Amend | An amend with one invalid field (price 0 or quantity 0 with its bit set) silently drops that field | BALF05 |
| C12 | Low | Loop | `select.select` raises `ValueError` (uncaught) once a descriptor passes 1023 | BALF07 |
| C13 | Low | Metrics | `frames_forwarded_total` counts each order, cancel and amend twice; field rejects are not counted *(repro)* | BALF06 |
| C14 | Low | Logon | A gateway ID containing `.` is never answered: the reply topic is parsed to the wrong ID | BALF02 |
| C15 | Low | Slow client | `SLOW_CLIENT` clears the queue mid-frame: the client reads a truncated frame, then later frames | BALF04 |
| P1 | Med | Latency | Fixed 5 ms sleep per loop pass: `NEW_ORDER` → `ORDER_ACK` median 10.6 ms *(measured)* | BALF07 |
| D1–D10 | — | Texts | See §5 | BALF09 |

---

## 3. Correctness findings

### H1. Orders of an earlier session are orphaned *(repro)* — High

`gateway.py:233-247` keeps the order map per TCP session:
`engine_to_balf`, `balf_to_engine` and the BALF order id counter
(`_balf_id_seq`) are fields of `ClientSession`. An engine event is routed to
the session that now holds the gateway ID (`gateway.py:1081-1084`) and
dropped when that session's map has no entry for the order
(`gateway.py:1334-1336` for fills, `1429-1431` triggers, `1444-1446`
expiries).

Whether an order survives its session is the participant's
`disconnect_behaviour`, and the default is `CANCEL_QUOTES_ONLY`
(`engine/config_loader.py:327`): ordinary orders stay on the book. Repro,
real engine, GW01 and GW02 with default participants:

| Step | GW01 client receives | Engine publishes |
|---|---|---|
| GW01 session 1: SELL 100 AAPL @ 100.00 | `ORDER_ACK` (order_id 1) | `order.ack.GW01` |
| GW01 `LOGOUT`, session closed | — | (order stays: `CANCEL_QUOTES_ONLY`) |
| GW01 session 2 logs on | `LOGON_ACK` accepted | — |
| GW02: BUY 100 AAPL @ 100.00 | **nothing** | `order.fill.GW02`, `order.fill.GW01` |
| GW01 session 2: `CANCEL_ORDER` order_id 1 | `CANCEL_ACK` accepted=0 | — |

GW01 sold 100 shares and was never told. The cancel fails because order id 1
belongs to session 1, and BALF 1.0.0 has no order list to find the order
again. The same happens after `EVICT_OLD`, after a heartbeat timeout or
network blip, and after a pm-balf-gwy restart. The only ways to learn about
the fill are other protocols (drop-copy, REST, clearing).

**Fix.** See Q1: keep the order map per gateway ID for the life of the
process, so a reconnecting client keeps receiving its orders' events under
their original BALF ids and can cancel them; document what a gateway restart
still loses.

### C1. Execution reports carry no time *(repro)* — Med

`translate.py:143`:

```python
ts = payload.get("timestamp") or payload.get("fill_timestamp") or 0
```

The engine's `order.fill` carries `ts_ns` (`spec/messages/order.yaml`,
`order_fill.ts_ns`: "identical to trade.executed.ts_ns"); neither key read
here exists. Repro against the real engine:

```text
engine order.fill ts_ns: 1794686805863134119
GW01 EXECUTION_REPORT FILLED 100 100.0 timestamp_ns = 0
GW02 EXECUTION_REPORT FILLED 100 100.0 timestamp_ns = 0
```

Every fill ever sent by pm-balf-gwy says 1970-01-01. The unit tests did not
notice because they feed hand-made payloads with the old keys
(`tests/test_balf_gwy_unit.py:1034`, `:1055`).

`ORDER_ACK.timestamp_ns` is `now_ns()` taken when the gateway processes the
ack (`gateway.py:1318`). The spec calls it "engine receive time"
(`020-balf.md:341`). The engine's `order.ack` carries the order's `ts_ns`,
which BALF itself stamped at ingress (`translate.py:113`); neither is the
engine's receive time, and the gateway's ack-time is the least useful of the
three.

**Fix.** Read `ts_ns` for fills. Fill `ORDER_ACK.timestamp_ns` from the ack's
`ts_ns` and correct the spec's wording (see D8).

### C2. A rate-limited request gets no answer *(repro)* — Med

`gateway.py:629-633`: when the token bucket is empty the frame is counted in
`frames_rejected_total`, reported to the audit trail and dropped. No
`ORDER_ACK`, `CANCEL_ACK` or `AMEND_ACK` is sent and `_register_error` is not
called. Repro with `max_messages_per_second: 5`, ten `NEW_ORDER`s in one
burst:

```text
NEW_ORDER sent: 10   ORDER_ACK received: 4  clids: [1, 2, 3, 4]
frames_rejected_total: 6 session.errors: 0
```

The spec says `ORDER_ACK` is "sent for every NEW_ORDER" (`020-balf.md:333`);
the module docstring says "Rate-limit exceeded → reject + error counter"
(`gateway.py:21`). A client waiting for the ack of order 5 waits forever and
cannot tell a dropped order from a slow one. A dropped `HEARTBEAT` is
harmless; a dropped `CANCEL_ORDER` leaves an order live that the client
believes is being cancelled. `tests/test_balf_gwy_integration.py:1144`
encodes the silent drop as intended.

**Fix.** Answer every rate-limited request with its own ack type,
`accepted = 0`; see Q2 for the code and whether it counts as an error.

### C3. The auth reply races the subscription *(repro)* — Med

`gateway.py:728-737` subscribes `system.gateway_auth.<GW>` and sends
`system.gateway_connect` in the same breath. The comment above it says the
subscription "is in place well before the reply". It is not: SUBSCRIBE
travels on the SUB socket's TCP connection and is applied by the engine's PUB
I/O thread asynchronously, while the connect travels on the PUSH connection.
When the engine answers before the subscription lands, the PUB filters the
reply out. Repro with the real bus factories and an engine thread that
answers each connect at once:

```text
auth replies lost to the subscribe race: 137/300
```

The session then sits in `auth_pending` until `auth_timeout_sec` (10 s,
counted from TCP connect, `gateway.py:1524`) and is hard-closed with no
`LOGON_ACK` (`gateway.py:1528`): the client sees silence and a reset. The
engine did accept the connect, and only the disconnect sent on that close
frees the ID again. pm-alf-gwy hit the same race and now subscribes every
gateway-scoped family once by prefix at start-up
(`alf_gwy/gateway.py:350-368`). The integration fixture hides it with a
`time.sleep(0.1)` before publishing the auth reply
(`tests/test_balf_gwy_integration.py:241-242`).

**Fix.** Subscribe the gateway-scoped prefixes (`system.gateway_auth.`,
`system.symbols.`, the six `order.*.` families) once in `__init__`, as
pm-alf-gwy does, and drop the per-session refcounting; route by the exact
gateway ID as today.

### C4. A closing session can live forever *(repro)* — Med

`_close_after_flush` (`gateway.py:1598`) only sets `closing`; the session is
removed when its queue drains (`gateway.py:562-563`). Every timeout skips
closing sessions (`gateway.py:1497-1498`), a send error is swallowed
(`gateway.py:552-553`), and the engine heartbeat stops for them
(`gateway.py:1482`). After a `LOGOUT` the session is still `authenticated`
and still in `_active_gateway_sessions`. Repro: a client with unread output
sends `LOGOUT` and stops reading (a hung process, or a link that drops
without FIN):

```text
after 1 s (5 × heartbeat_timeout): session alive: True  queued: 2990  GW01 held: True
new LOGON GW01 -> LOGON_ACK accepted=0 reject_code=0x2 (ALREADY_CONNECTED)
```

Under the default `REJECT_NEW`, the participant cannot log on through
pm-balf-gwy until the TCP connection dies, which for a peer that keeps
acknowledging with a zero window is never. The engine meanwhile frees the ID
after 180 s without heartbeats, so pm-alf-gwy can take it while pm-balf-gwy
still refuses it. Triggers: `LOGOUT` (`gateway.py:758-760`), engine restart
(`gateway.py:1249`), auth refusal (`gateway.py:1126`), `SLOW_CLIENT`
(`gateway.py:1594`). This is pm-alf-gwy's old H3.

**Fix.** Give a closing session a deadline (a few seconds, as pm-alf-gwy's
close grace), release its gateway ID when it starts closing, and treat a
permanent send error as a disconnect.

### C5. Engine events are dropped without a trace *(repro)* — Med

`gateway.py:339-342` builds the SUB socket with `make_subscriber` and no
`rcvhwm`, so ZMQ's default 1 000-message high-water mark applies, and
`_poll_engine_events` (`gateway.py:1046-1061`) ignores the per-topic sequence
frame the engine stamps on every event. Repro with the real bus factories:
the publisher sends a burst of fill-sized events (≈600 bytes) for one
gateway while the subscriber does not read, as when the loop stalls:

| Burst | Received | Lost | Gaps visible to a sequence check |
|---|---|---|---|
| 5 000 | 5 000 | 0 | 0 |
| 20 000 | 9 500 | 10 500 | (all lost at the tail; the next event shows the gap) |
| 50 000 | 9 500 | 40 500 | 1 |

The loop drains at most 256 events per 5 ms pass (about 50 000/s), so loss
needs a burst or a stall, not normal load. When it happens, fills and acks
vanish and nothing is logged, counted or told to the client. pm-alf-gwy
raised its HWM to 200 000 and checks the sequence (its H2,
`alf_gwy/gateway.py:164`, `:1508-1546`).

**Fix.** `rcvhwm=200_000`; check `decode_sequence` per private topic, count
`events_lost`, log a WARNING, and tell the session as Q5 decides.

### C6. A stop drops what is already queued — Med

`run()`'s `finally` calls `close()` (`gateway.py:394-395`), which calls
`_disconnect` on every session (`gateway.py:411-412`). `_disconnect` closes
the socket at once: frames already in `out_queue` (fills among them) are
never sent, events waiting on the SUB socket are never read, and the client
gets no `LOGOUT`, only a reset. With H1 those fills are then lost to the
client for good. pm-alf-gwy drains the SUB socket once, sends each session a
closing line and flushes for a bounded time before closing
(`alf_gwy/gateway.py:507-533`, its M2/M3).

**Fix.** The same: on a requested stop, one drain of the SUB socket, a
`LOGOUT` to each authenticated session, a bounded flush, then close. Not
after a crash.

### C7. Rejects are classified from prose *(repro)* — Low

`classify_engine_reason` (`protocol.py:65-98`) matches eleven engine
sentences. The engine's `order.ack` has carried a machine-readable
`reject_code` enum (33 values, "stable across every order-entry transport")
for some time, and the classifier's own comment (`protocol.py:82-87`) says
classifying on it is the better design. Any sentence not in the list becomes
`RC_OTHER`, and the reason is cut to 25 bytes (`gateway.py:1314`). Repro:

```text
LIMIT price -100.00 -> reject_code 0xFF, reason 'LIMIT order requires a po'
```

The engine said `INVALID_VALUE`, which BALF has a code for (`0x0C`). The same
fate meets `LOT_VIOLATION`, `PRICE_OUT_OF_RANGE`, `QTY_OUT_OF_RANGE`,
`MAX_ORDER_QTY`, `MAX_ORDER_VALUE`, `POSITION_LIMIT`, `KILL_SWITCH_ACTIVE`,
`ROLE_DENIED` and any reworded sentence.

**Fix.** Classify on `payload["reject_code"]`, keeping the prose only where
BALF splits one engine code in two (ATO versus ATC). Whether risk refusals
get new BALF codes is Q3.

### C8. Every exchange cancel looks the same *(repro)* — Low

`_handle_cancelled_event` sends `cancel_reason = 255` for every cancel the
client did not request (`gateway.py:1389`); expiries too (`gateway.py:1458`).
The engine's `order.cancelled` says why (`SELF_MATCH_PREVENTED`,
`INSUFFICIENT_LIQUIDITY`, `KILL_SWITCH`, `CIRCUIT_BREAKER_HALT`,
`GATEWAY_DISCONNECT`, `ADMIN_CANCEL_SYMBOL`, …). Repro, SMP
`CANCEL_RESTING`: the engine publishes `cancel_reason: SELF_MATCH_PREVENTED`,
the client gets `CANCEL_ACK(accepted=1, cancel_reason=255)`. An algo cannot
tell its own self-match from a kill switch without another protocol.
`translate.cancel_reason_from_engine` (`translate.py:203-208`) is unused and
always returns 0.

**Fix.** Map the engine's `cancel_reason` to distinct codes (Q3).

### C9. A repeated LOGON during the symbols wait closes the session — Low

Since K11 the `LOGON_ACK` waits for symbol metadata, up to
`auth_timeout_sec`. The repeated-`LOGON` guard covers `auth_pending` only
(`gateway.py:578`). A `LOGON` sent again while `symbols_pending` reaches
`_handle_logon`, where `_gateway_in_use` (`gateway.py:700`, `1686-1689`)
counts the session itself: under `REJECT_NEW` it is answered
`ALREADY_CONNECTED` and closed, which sends `gateway_disconnect` and tears
down the engine session it was about to complete; under `EVICT_OLD` it sends
a second `gateway_connect` for an ID the engine already holds. A client with
a short logon timeout that retries on the same socket does exactly this.

**Fix.** Treat `logon_in_progress` like `auth_pending` at
`gateway.py:578`.

### C10. Inbound sequence numbers are ignored — Low

`gateway.py:530` reads `seq_no` and never uses it. The spec says "A gap in
the inbound sequence number is a protocol error" (`020-balf.md:157`,
`:537`, `:614`). A client that numbers wrongly is never told. The spec also
says reserved body fields "should be validated as zero" (`020-balf.md:107`)
and lists "silent tolerance" of non-zero reserved fields as a defect
(`:588`), while the gateway tolerates a non-zero `flags` byte on purpose
(`gateway.py:537-541`, operator guide "forward-compatible"). See Q4.

### C11. A partly invalid amend is applied in part — Low

`gateway.py:969-975`: with bit 0 set and `new_price = 0`, or bit 1 set and
`new_quantity = 0`, that field is treated as absent. If the other field is
valid, the amend goes ahead without the field the client asked to change, and
the `AMEND_ACK` says accepted. Only when both are unusable is it refused.
A negative `new_price` is passed through to the engine, which refuses it
correctly (`engine/main.py:7063-7065`).

**Fix.** Refuse the amend (`AMEND_ACK accepted=0`, counted as a field error)
when a flagged field is zero.

### C12. More than 1 023 descriptors stop the gateway — Low

`_read_client_data` uses `select.select` (`gateway.py:463-467`), which raises
`ValueError` for a descriptor ≥ `FD_SETSIZE`; only `OSError` is caught, so the
exception ends `run()`. `max_connections` has no upper bound
(`config.py:125-127`). Reached only with a large `max_connections` or a
process with many other descriptors; pm-alf-gwy's selector loop does not have
the limit. Fixed by WP-BALF07's loop.

### C13. Forwarded frames are counted twice *(repro)* — Low

`_send_to_engine` increments `frames_forwarded_total` when `count_as_command`
is true (`gateway.py:1657-1658`), and the order, cancel and amend handlers
increment it again after a successful send (`gateway.py:839`, `908`,
`1024`):

```text
1 NEW_ORDER -> frames_forwarded_total + 2
1 CANCEL    -> frames_forwarded_total + 2
off-tick NEW_ORDER -> ORDER_ACK reject 0x0C 'price off tick grid', frames_rejected_total + 0
```

The dashboard shows twice the real order rate. Field rejects
(`gateway.py:800-813`, `924-935`, `976-990`) are not counted in
`frames_rejected_total`, while unknown-symbol and rate-limit rejects are.

### C14. A gateway ID with a dot is never answered — Low

`_dispatch_engine_event` takes the gateway ID as the text after the last
`.` of the topic (`gateway.py:1069`, `1074`). A `LOGON` for `GW.01` (any
bytes are accepted, `gateway.py:686`) gets its reply on
`system.gateway_auth.GW.01`, which is looked up as `01`; the session waits
for the auth timeout and is closed with no `LOGON_ACK`. pm-alf-gwy refuses
such IDs at `HELLO` with a pattern (`_GATEWAY_ID_RE`, its L2).

**Fix.** Refuse an ID that does not match the participants ID pattern with
`LOGON_ACK(accepted=0, reject_code=0xFF, msg="gateway_id invalid")`.

### C15. `SLOW_CLIENT` truncates a frame — Low

`_queue_frame` (`gateway.py:1586-1595`) clears the queue and resets
`out_offset` when the queue is full. If the first frame was partly sent, the
client has received its first bytes; frames queued after the clear (in the
same loop pass) are sent behind them before the close, so the client parses
a frame whose tail is the next frame's header. No reason is given before the
close. pm-alf-gwy's M1.

**Fix.** Keep the partly sent frame, drop the rest, and close after it.

---

## 4. Performance findings

### P1. A fixed 5 ms sleep per loop pass *(measured)* — Med

`run()` (`gateway.py:383-393`) does one pass and then `time.sleep(0.005)`,
whatever is pending. A request is read in one pass; the engine's reply
arrives a few hundred microseconds later, after that pass's
`_poll_engine_events`, and is delivered in the next pass. Measured with the
real gateway thread, real TCP, `TCP_NODELAY` on both sides and a fake engine
that answers each `order.new` at once, 500 sequential orders:

| | median | p90 | p99 | min |
|---|---|---|---|---|
| `NEW_ORDER` → `ORDER_ACK` | 10.60 ms | 10.67 ms | 10.85 ms | 10.48 ms |

Two full sleeps per round trip, every time. Idle CPU is 1.1–1.4 % of a core.
The cost does not grow with history or with the day; it is a floor. The drain
budget of 256 events per pass also caps throughput at about 50 000 engine
events per second. pm-alf-gwy, the text protocol, waits on an epoll selector
with the ZMQ notification fd registered and has no such floor
(`alf_gwy/gateway.py:438-506`).

**Fix.** The same selector loop: register the listener, the client sockets
and the SUB socket's `zmq.FD`, wait with a timeout of the next housekeeping
deadline (0 when ZMQ reports `POLLIN` or a write is pending), and run
heartbeats and timeouts on a schedule rather than every pass. Target: median
round trip below 1 ms on this host (a guess, to be confirmed by the
measurement in WP-BALF07).

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `gateway.py:6-24` | Module docstring: "Single-threaded select() loop" (it sleeps 5 ms per pass); "Rate-limit exceeded → reject + error counter" (dropped silently, C2); "Outbound queue full → SLOW_CLIENT close" (no `SLOW_CLIENT` reason reaches the client); "Inbound idle / heartbeat timeout" (`idle_timeout_sec` is unused). |
| D2 | `gateway.py:724-727` | "subscribed here … so the subscription is in place well before the reply": false (C3). |
| D3 | `translate.py:203-208` | `cancel_reason_from_engine` is unused, always returns 0, and its comment says system cancels "come via order.ack with accepted=False": they come as `order.cancelled` (C8). |
| D4 | `codec.py:425-431` | `build_amend_ack`: `reject_reason` is accepted and ignored, and the docstring says "the caller should send ORDER_ACK for rejects"; the gateway sends `AMEND_ACK(accepted=0)`. |
| D5 | `gateway.py:528`, `666`, `1716-1722` | `import struct as _struct` inside the per-frame loop; a `struct_error` module global defined after the class through a `try/except ImportError` that cannot fail; `parse_logon` only raises `ValueError` anyway. |
| D6 | Operator guide, "Server → client messages" | The table omits `STOP_TRIGGERED` (0x21) and the `LOGOUT` the gateway sends on an engine restart. |
| D7 | Operator guide, "Common problems" | "Unknown `msg_type` → connection closed — Client sent a server-direction frame": after logon a server-direction frame is ignored (`gateway.py:622-627`); before logon any non-`LOGON` frame closes. |
| D8 | Spec `020-balf.md:341`, `:107`, `:588`, `:566-567`, `:466-467` | `ORDER_ACK.timestamp_ns` "engine receive time" (C1); reserved fields "should be validated as zero" and the flags tolerance (C10); config table types `heartbeat_*` as Integer (floats are accepted, `config.py:113-118`); "The recipient must respond with HEARTBEAT_ACK" (the gateway counts any traffic and never checks for the ack). |
| D9 | Operator guide config table, `auth_timeout_sec` | "Hard-close if `LOGON` is not answered within this window": the window runs from TCP connect (`gateway.py:1524`) and also bounds the symbols wait (`gateway.py:1503-1506`), which closes with `SYMBOLS_UNAVAILABLE`, not a hard close. |
| D10 | Spec `020-balf.md` identifier rules; operator guide | Nothing says that `order_id` dies with the session and that orders left by `disconnect_behaviour` are invisible afterwards (H1). To be rewritten after Q1. |

---

## 6. Verified as correct

- **Framing.** Bad magic, bad version, unknown type: hard close before the
  body is read. Partial frames wait. A frame body is never longer than its
  fixed size, so `in_buffer` is bounded by one frame plus one `recv`.
- **Pre-logon.** Any frame but `LOGON` before authentication closes the
  connection and is reported to the audit trail (`gateway.py:604-615`).
- **Pricing.** No `LOGON_ACK` before the engine's symbol list (K11); an
  unlisted symbol is refused with `RC_SYMBOL_NOT_CONFIGURED`; an off-grid
  price is refused with `RC_INVALID_FIELD`, `"price off tick grid"`
  *(repro)*. Amend prices are checked by the engine with `to_ticks_exact`
  (`engine/main.py:7063-7065`).
- **Cancel and amend correlation.** Tagged per request (K12); a client
  cancel returns `CANCEL_ACK(accepted=1, cancel_reason=0)` with the cancel's
  own `client_order_id` *(repro)*.
- **Fills.** Price, quantity, remaining quantity, side and status (`PARTIAL`
  / `FILLED`, the engine's enum since the status unification) map correctly
  *(repro)*; only the time is wrong (C1).
- **Engine restart.** Every authenticated or logging-on session is closed
  with `LOGOUT` or `LOGON_ACK(ENGINE_RESTARTED)`, symbol metadata is
  re-requested, and no `gateway_disconnect` is sent for sessions the new
  engine never had (K11).
- **Engine liveness.** One `system.gateway_heartbeat` per authenticated
  session every 60 s, so the engine frees an ID whose gateway died.
- **Config.** Integers and positive floats are coerced strictly (K17);
  participant ID prefixes are refused.
- **Outbound sequence wrap.** `next_seq` does not wrap at `UINT32_MAX` as
  the spec says; reaching it needs 4.3 × 10⁹ frames in one session (497 days
  at 100 frames/s). Not worth code.

---

## 7. Decisions

All five taken as recommended on 2026-11-14, when the WPs were asked for in one go.
The resulting wire changes (ORDER_ACK codes 0x0D and 0x0E, `cancel_reason` 1–8 and 254, `LOGOUT` sent by the gateway, inbound sequence enforcement) were confirmed by the project owner on 2026-11-15.

| # | Question | Recommendation |
|---|---|---|
| Q1 | H1: how should a reconnecting client keep its orders? (a) keep `engine_to_balf`, `balf_to_engine`, the order symbols and the BALF id counter per gateway ID in the gateway process, so a new session of the same ID keeps receiving events under the original BALF ids and can cancel and amend them; (b) as (a), and on logon also adopt the engine's live orders via `order.orders_request`, so a gateway restart is covered too (needs `client_order_id` sent as `client_tag` to restore it); (c) only document it and recommend `disconnect_behaviour: CANCEL_ALL` for BALF participants. | **(a)**: it covers reconnects, evictions and timeouts, the common cases, with no wire change. (b) adds a request/response and a new adoption state to a logon that K11 already made longer; worth a For-Later entry. (c) leaves the default configuration losing fills. With (a), the guide must say that a pm-balf-gwy restart still loses the map. |
| Q2 | C2: what does a rate-limited request get? (a) its own ack type with `accepted = 0`; for `ORDER_ACK` a new reject code `0x0D RC_RATE_LIMITED`, reason `"RATE_LIMITED"`; not counted towards `max_errors_before_disconnect`; (b) as (a) but counted; (c) `RC_OTHER` with reason `"RATE_LIMITED"`, no new code. | **(a)**. The engine's `reject_code` already has `RATE_LIMITED`, so a code costs nothing to explain. Counting it (b) would disconnect a client after ten throttled orders in a minute, which punishes a burst the bucket already absorbed. (c) makes the client parse prose, which C7 is trying to remove. |
| Q3 | C7/C8: new codes? (a) map the engine's `reject_code` onto the existing BALF codes, add `0x0D RC_RATE_LIMITED` (Q2) and `0x0E RC_RISK_LIMIT` (`MAX_ORDER_QTY`, `MAX_ORDER_VALUE`, `POSITION_LIMIT`, `KILL_SWITCH_ACTIVE`), and give `CANCEL_ACK.cancel_reason` one code per engine `cancel_reason` (1 = `SELF_MATCH_PREVENTED` … 8 = `QUOTE_LEG_FILLED`, 254 = expiry, 255 = unclassified); (b) map onto existing codes only, keep 255 for every system cancel. | **(a)**. BALF 1.0.0 is not released; the `cancel_reason` byte already has room, and the codes are additive for any client that treats unknown values as "other". (b) keeps the information loss C8 describes. |
| Q4 | C10: (a) enforce inbound sequence: a gap or repeat is a protocol error, logged, counted and hard-closed; keep tolerating non-zero `flags` and reserved bytes, and change the spec to say so; (b) do not check, and change the spec to say the gateway does not check. | **(a)**. A client that misnumbers will also misread the gateway's numbers, and the spec already tells implementers a gap is fatal. The examples are checked by `tests/test_examples_balf_alf_current.py`. Tolerating `flags` stays, since the operator guide promises it. |
| Q5 | C5: what does a session get when its engine events were lost? (a) a `LOGOUT` and a close, after a WARNING log and the `events_lost` metric: the spec's own rule for an out-of-sync session; (b) only the log and the metric. | **(a)**. BALF has no error frame to say "reconcile", and a session that has silently lost a fill is wrong in a way the client cannot see; with Q1 (a) its orders are still reachable after it logs on again. (b) leaves the client trading on a wrong position. |

---

## 8. Work packages

### WP-BALF01 — A resting order stays the client's after a reconnect (H1; after Q1)

**Tests first** (`tests/test_balf_gwy_sessions.py`, real-engine harness):

1. GW01 rests SELL 100 @ 100.00, logs out, logs on again; GW02 buys 100 @
   100.00 → GW01's new session receives `EXECUTION_REPORT` with the original
   `order_id` and `client_order_id`, status `FILLED`. (Fails today.)
2. Same, but GW01's new session sends `CANCEL_ORDER` for the original
   `order_id` before GW02 trades → `CANCEL_ACK(accepted=1)` and the engine
   book no longer holds the order. (Fails today.)
3. `EVICT_OLD`: the evicting session receives the evicted session's fills.
   (Fails today.)
4. BALF order ids are not reused across sessions of one gateway ID: the
   second session's first order gets id 2, not 1. (Fails today.)
5. A gateway ID's map is dropped on engine restart (the engine's orders are
   the restarted engine's business). Unchanged in effect, new test.

**Change.** Move the order maps and the id counter from `ClientSession` to a
per-gateway-ID object owned by `BalfGateway`, created at first logon and kept
until engine restart; clean entries on terminal events as today.

**Exit criteria.** Tests 1–5 pass; `tests/test_balf_gwy_*.py` green; the guide
and spec say what a gateway restart loses (with WP-BALF09).

**Outcome (2026-11-14).** The order maps, the in-flight cancel/amend maps
and the BALF id counter moved from `ClientSession` to a new
`_GatewayOrders`, one per gateway ID in `BalfGateway._gateway_orders`, bound
to the session in `_complete_logon`; a `forget()` helper replaces three
copies of the three-map cleanup. In-flight cancels and amends moved with
them, so a result that arrives on the next session of the same ID still
finds its request (it also removes the K12 fall-through where a tagged
refusal unknown to the session could be read as a new-order rejection).
**Deviation from test 5:** the plan said to drop the map on engine restart.
The engine restores GTC orders under their original engine ids
(`load_gtc_orders`), so dropping it would orphan exactly those orders; the
map is kept, and test 5 asserts that a cancel of the old BALF id after a
restart is forwarded with the original engine id. Entries for orders a
restarted engine forgot stay until the process ends (a cancel of one is
refused by the engine). New `tests/balf_harness.py` (real engine ↔ real
gateway) and `tests/test_balf_gwy_sessions.py`; tests 1–4 failed first on
the missing report / refused cancel / id 1, test 5 on the locally refused
cancel. `tests/test_balf_gwy_k11_k12.py` reads `session.orders.engine_to_balf`.
Full suite: 14 368 passed, 1 skipped.

### WP-BALF02 — A logon is never lost to the subscription race (C3, C9, C14)

**Tests first** (`tests/test_balf_gwy_integration.py`):

1. Remove the `time.sleep(0.1)` from `_balf_authenticate`; 50 sequential
   logons with distinct IDs, the fake engine answering at once → 50
   `LOGON_ACK(accepted=1)`. (Fails today.)
2. A second `LOGON` while the `LOGON_ACK` waits for symbols →
   `LOGON_ACK(accepted=0, msg="LOGON_ALREADY_PENDING")`, the session stays,
   and the engine receives no `gateway_disconnect`. (Fails today.)
3. `LOGON` for `GW.01` → `LOGON_ACK(accepted=0, msg="gateway_id invalid")`
   at once, no `gateway_connect` sent. (Fails today.)

**Change.** Subscribe the gateway-scoped prefixes once in `__init__`
(K16's "drop unused subscriptions" stays true: they are all used); remove
`_subscribe_topic`/`_unsubscribe_topic` and `session.subscriptions`. Extend
the pending-logon guard to `logon_in_progress`. Validate the ID with the
participants pattern.

**Exit criteria.** Tests 1–3 pass; suites green; test 1 passes 20 runs in a
row.

**Outcome (2026-11-14).** `BalfGateway.__init__` subscribes
`system.gateway_auth.`, `system.symbols.`, the six `order.*.` families and
the restart notice once; `_subscribe_topic`, `_unsubscribe_topic`,
`_topic_refcounts`, `_gateway_topics` and `ClientSession.subscriptions` are
gone. Because the socket now carries every gateway's order events,
`_poll_engine_events` skips the ones for a gateway with no session here
before decoding them (`_for_absent_gateway`, as pm-alf-gwy). The repeated-
`LOGON` guard covers `logon_in_progress`; the ID must match
`[A-Z][A-Z0-9_]{0,15}` (pm-alf-gwy's pattern, at the LOGON field's 16 bytes).
**Test 1 as planned did not fail:** 50 real-ZMQ logons with no sleep all
succeeded before the fix, because the test thread answers slower than an
engine. It was kept as a 20-logon real-ZMQ smoke test, and the race is
proved by a deterministic model instead
(`test_auth_reply_published_at_once_still_completes_the_logon`: a fake SUB
whose runtime SUBSCRIBEs take effect one poll later, a fake engine that
answers inside `send_multipart`), which failed first with no `LOGON_ACK`.
Tests 2 and 3 failed first on `GW01 already connected` and on no answer.
The race-hiding `time.sleep(0.1)` calls before the auth reply were removed
from `_balf_authenticate` and the robustness `_do_auth` and inline copies.
`tests/test_gateway_k16_k17.py::test_b5_…` pinned the old subscription list
(only the restart notice); its rule (nothing subscribed that dispatch
ignores) still holds and it now checks the new set. Full suite: 14 372
passed, 1 skipped.

### WP-BALF03 — Engine events are not dropped silently, nor at shutdown (C5, C6; after Q5)

**Tests first** (`tests/test_balf_gwy_robustness.py`):

1. The SUB socket is created with `rcvhwm=200_000` (assert on the
   `make_subscriber` call). (Fails today.)
2. An `order.fill.GW01` event with sequence 5 after one with sequence 3 →
   `events_lost` metric +1, a WARNING naming the topic, and (Q5 a) the
   session receives `LOGOUT` and is closed. (Fails today.)
3. A lower sequence (engine restart) or the first sight of a topic is not a
   gap. Unchanged in effect, new test.
4. `stop()` with frames queued and one event waiting on the SUB socket → the
   client receives the queued frames, the event, and a `LOGOUT` before the
   socket closes. (Fails today.)

**Change.** Port pm-alf-gwy's `_check_sequence` (without its absent-gateway
fast path, which BALF's narrower subscription does not need) and
`_flush_for_shutdown`.

**Exit criteria.** Tests 1–4 pass; suites green.

**Outcome (2026-11-15).** `_SUB_RCVHWM = 200_000` on the SUB socket;
`_check_sequence` counts gaps per private topic for every gateway (before
the absent-gateway skip, so a later logon is not told of a false gap) into
the new `gwy.events_lost` metric with a WARNING; `_end_out_of_sync_session`
sends the session `LOGOUT` and closes it **after** the event that revealed
the gap has been delivered (Q5). `_flush_for_shutdown` (one SUB drain,
`LOGOUT` to authenticated sessions, flush bounded by 2 s) runs when `run()`'s
loop ends normally, not after a crash. The absent-gateway fast path the plan
called unnecessary is in, since WP-BALF02 widened the subscription. Two new
log-ledger entries in `log_ledger/entries/balf_gwy.yaml` (the ledger test
requires one per WARNING call site; the first full run failed on that).
Test doubles of `make_subscriber` in `test_balf_gwy_k11_k12.py` and
`test_gateway_k16_k17.py` now accept `**_kw`. `tests/balf_harness.py`
gained `peer_of` and `read_wire` (bytes that really crossed the socket).
All four tests failed first on the missing `rcvhwm`, the missing
`events_lost` key and the missing `_flush_for_shutdown`. Full suite: 14 376
passed, 1 skipped.

### WP-BALF04 — A closing session always ends (C4, C15)

**Tests first** (`tests/test_balf_gwy_robustness.py`):

1. Client with unread output sends `LOGOUT` and stops reading → the session
   is gone within the close grace, and a new `LOGON` for the same ID under
   `REJECT_NEW` is accepted. (Fails today.)
2. `send()` raising `BrokenPipeError` on a closing session → disconnected on
   that pass. (Fails today.)
3. Queue overflow with the head frame half sent → the bytes the client
   receives end on a frame boundary. (Fails today.)

**Change.** A `close_deadline` set by `_close_after_flush`; release the
gateway ID from `_active_gateway_sessions` when closing starts; classify
permanent send/recv errors as disconnects; keep the head frame on overflow.

**Exit criteria.** Tests 1–3 pass; suites green.

**Outcome (2026-11-15).** `_close_after_flush(session, reason)` now sets
`close_deadline` (`_CLOSE_GRACE_SEC = 5.0`, enforced in
`_drop_stale_clients` with reason `close_timeout`) and calls the new
`_release_gateway_id`, which frees the ID **and sends
`gateway_disconnect` at once**: releasing the ID without telling the engine
would let a new session's `gateway_connect` reach an engine still holding
the old one (found while designing the change; `_disconnect` shares the
helper). `_sessions_holding` ignores closing sessions. `_queue_frame` drops
frames for a closing session, and on overflow keeps a partly sent head
frame. Send errors other than `BlockingIOError`/`InterruptedError`
disconnect (`send_error`), as do such recv errors (`recv_error`). Closes
carry their reason to the engine (`client_logout`, `slow_client`,
`events_lost`, `gateway_shutdown`) where they all said `session_closed`
before. Test 3 as first written had an unbounded precondition loop; it was
rewritten to set the half-sent state directly (40 of 92 bytes sent), and
then failed with 120 bytes on the wire (40 + 5 × 16), test 1 on
`LOGON_ACK refused`, test 2 on the session still present. Full suite:
14 379 passed, 1 skipped.

### WP-BALF05 — Every request gets an answer (C2, C11; after Q2)

**Tests first** (`tests/test_balf_gwy_integration.py`, rewriting
`test_rate_limiting_enforced`):

1. Ten `NEW_ORDER`s against a bucket of 5 → ten `ORDER_ACK`s, six with
   `reject_code 0x0D`, reason `RATE_LIMITED`; the session stays open and
   `session.errors` is 0. (Fails today.)
2. Rate-limited `CANCEL_ORDER` → `CANCEL_ACK(accepted=0)`; rate-limited
   `AMEND_ORDER` → `AMEND_ACK(accepted=0)`; rate-limited `HEARTBEAT` → no
   frame. (Fails today, except the heartbeat.)
3. Amend with bit 0 set, `new_price = 0`, bit 1 set, `new_quantity = 50` →
   `AMEND_ACK(accepted=0)`, nothing sent to the engine. (Fails today.)

**Change.** Parse the request id before the rate check and answer with the
type's reject; add `RC_RATE_LIMITED` to `protocol.py` and the spec; refuse
zero flagged amend fields.

**Exit criteria.** Tests 1–3 pass; suites green; spec reject table updated.

**Outcome (2026-11-15).** `RC_RATE_LIMITED = 0x0D` in `protocol.py`;
`_refuse_rate_limited` answers a refused `NEW_ORDER` (`ORDER_ACK`, 0x0D,
`RATE_LIMITED`), `CANCEL_ORDER` (`CANCEL_ACK accepted=0`, order id echoed)
or `AMEND_ORDER` (`AMEND_ACK accepted=0`); heartbeats get nothing; none of it
counts as a session error (Q2). **Beyond the plan:** `LOGOUT` bypasses the
bucket, since a rate-limited LOGOUT was also dropped and left the session
open. An amend whose flagged field is zero is refused whole (`flagged amend
field is zero`, counted as a field error). The reject tables in the spec,
the operator guide and `docs/examples/balf/balf_parser.py`
(`ORDER_REJECT_NAMES`, checked by `test_examples_balf_alf_current.py`, which
failed on the first full run) name 0x0D. Two tests encoded the old
behaviour: `test_rate_limiting_enforced` (silent drop; now asserts the
0x0D acks) and `test_balf_gwy_rejects.py::test_a_rate_limited_message_is_reported`
(drove `_process_frame` with an empty body, which no wire frame can have;
now a whole body). New tests failed first: 4 acks for 10 orders, no ack for
cancel/amend, LOGOUT ignored, the half-applied amend accepted. Full suite:
14 383 passed, 1 skipped.

### WP-BALF06 — Timestamps, reject codes and cancel reasons the client can use (C1, C7, C8, C13; after Q3)

**Tests first** (real-engine harness, `tests/test_balf_gwy_sessions.py`):

1. A cross between GW01 and GW02 → both `EXECUTION_REPORT`s carry the
   engine's `order.fill.ts_ns`. (Fails today.)
2. `ORDER_ACK.timestamp_ns` equals the engine ack's `ts_ns`. (Fails today.)
3. LIMIT with a negative price → `reject_code 0x0C`. Order over
   `max_order_qty` → `0x0E`. ATO outside the opening auction → `0x05`
   (unchanged). (First two fail today.)
4. SMP `CANCEL_RESTING` → `CANCEL_ACK.cancel_reason = 1`; a DAY order
   expiring → 254; a client cancel → 0 (unchanged). (First two fail today.)
5. One `NEW_ORDER` → `frames_forwarded_total` +1; an off-grid price →
   `frames_rejected_total` +1. (Fails today.)
6. Replace the hand-made payloads of `tests/test_balf_gwy_unit.py:1025-1062`
   with the generated builders' output.

**Change.** Read `ts_ns`; a table from engine `reject_code` to BALF code with
the ATO/ATC prose split; a table from engine `cancel_reason`; delete
`cancel_reason_from_engine`; count once in `_send_to_engine`; count field
rejects.

**Exit criteria.** Tests 1–6 pass; suites green; `classify_engine_reason`'s
prose list reduced to the ATO/ATC split.

**Outcome (2026-11-15).** Fills read `ts_ns`; `ORDER_ACK.timestamp_ns` is the
engine ack's `ts_ns` (the order's entry time; now when absent).
`classify_engine_reason(reason)` became `classify_engine_reject(reject_code,
reason)`: a table from the engine's `reject_code` (verified at its raise
sites in `engine/main.py`) to the BALF codes, prose read only to split
`SESSION_NOT_PERMITTED` into ATO / ATC / phase and to keep
`RC_TRAILING_STOP_NO_PRICE` apart from other `MISSING_FIELD`s; new
`RC_RISK_LIMIT = 0x0E` for `MAX_ORDER_QTY`, `MAX_ORDER_VALUE`,
`POSITION_LIMIT`, `KILL_SWITCH_ACTIVE`. `cancel_reason_from_engine` was not
deleted but made true: it maps the engine's `cancel_reason` to new codec
constants 1–8, 255 when the engine gives none; expiries send 254
(`CANCEL_REASON_EXPIRED`). `frames_forwarded_total` is counted once (in
`_send_to_engine`); field rejects on new orders and amends count in
`frames_rejected_total`. A test assumption was wrong and corrected: a
negative LIMIT price is `PRICE_OUT_OF_RANGE` at the engine, not
`INVALID_VALUE` (both map to 0x0C). Tests changed by design:
`test_classify_engine_reason` (now a code table), the two fill translation
tests (`ts_ns`), `test_cancel_reason_is_client`, `test_expired_event_delivered`
(254). The examples follow: `balf_parser.py` names 0x0E and every
`cancel_reason` (`CANCEL_REASON_NAMES`, `by_exchange` is now `!= 0`, which
`== 255` would have got wrong for 1–254), `balf_parser.c` the same test and
prints the code; a new example test checks every codec `CANCEL_REASON_*`
is named. All seven new tests failed first (timestamp 0, gateway clock,
255 for SMP and expiry, 0xFF for the risk limit, +2 forwarded, +0
rejected). Full suite: 14 402 passed, 1 skipped (run before a one-line
test-import fix mypy asked for; the WP-BALF07 run covers it).

### WP-BALF07 — The loop waits for work instead of sleeping (P1, C12)

**Tests first** (`tests/test_balf_gwy_integration.py`):

1. 200 sequential `NEW_ORDER` → `ORDER_ACK` round trips against an engine
   thread that answers at once → median below 2 ms (CI margin over the
   1 ms target). (Fails today: 10.6 ms.)
2. Heartbeats, heartbeat timeout, auth timeout and the close grace of
   WP-BALF04 still fire with the loop otherwise idle. Unchanged, existing
   tests.
3. A flood of engine events still lets a heartbeat and a timeout through
   (K16's test). Unchanged.

**Change.** A `selectors.DefaultSelector` loop as in pm-alf-gwy: the
listener, client sockets (read; write only when blocked) and the SUB
socket's `zmq.FD`; wait 0 when `zmq.EVENTS` has `POLLIN` or a write is
pending, else until the next housekeeping deadline.

**Exit criteria.** Tests 1–3 pass; suites green; the median round trip
measured with the review's `bench_rtt.py` recorded in the outcome (target
< 1 ms, a guess).

**Outcome (2026-11-15).** `run()` waits on a `selectors.DefaultSelector`
over the listener, each client socket (registered in `_accept_new_clients`,
unregistered in `_disconnect`) and the SUB socket's `zmq.FD`; it does not
block while `zmq.EVENTS` reports input or a session has output not waiting
on its peer (`_has_pending_writes`). Housekeeping (client and engine
heartbeats, timeouts) runs every `_LOOP_WAIT_SEC = 0.1` s instead of every
pass. A send that would block sets `ClientSession.write_blocked` and
registers write interest (`_set_write_interest`); the session is retried
only when the selector reports it writable. `_read_client_data` reads the
sessions the selector reported, so `select.select` and its 1 024-descriptor
limit (C12) are gone. Measured with `bench_rtt.py` (500 round trips, fake
engine answering at once): median **0.43 ms** (0.99 ms on a first, noisier
run), p99 0.51 ms, against 10.6 ms before; idle CPU 0.2 % of a core against
1.1–1.4 %. The new test failed first at 11.0 ms. Full suite: 14 414 passed,
1 skipped. `make _check`'s pyright step fails in
`tests/test_monitor_snapshot.py`, part of a monitor review in progress in a
parallel session (not this WP); pyright on every file this review touches
is clean.

### WP-BALF08 — Inbound sequence numbers are checked as the spec says (C10; after Q4)

**Tests first** (`tests/test_balf_gwy_robustness.py`):

1. `NEW_ORDER` seq 1, then `HEARTBEAT` seq 3 → hard close,
   `protocol_errors_total` +1, WARNING naming expected and received.
   (Fails today.)
2. Seq 1, 2, 3 → accepted; `LOGON` with seq 0 → accepted. Unchanged.
3. The example clients in `docs/examples` keep passing
   `tests/test_examples_balf_alf_current.py`.

**Change.** `ClientSession.inbound_seq`; check in `_drain_frames` after
logon; wrap at `UINT32_MAX` to 1 as the spec says.

**Exit criteria.** Tests 1–3 pass; suites green; spec's reserved-field
sentences changed to "tolerated".

**Outcome (2026-11-15).** `ClientSession.inbound_seq`; `_process_frame`
checks every frame of a logged-on client except `LOGON` (seq 0, not
numbered): expected is the last + 1, wrapping from `UINT32_MAX` to 1; a gap
or a repeat is logged (`expected N, got M`), counted in
`protocol_errors_total` and hard-closed. The check sits before the rate
limit, so a refused frame still uses its number. New log-ledger entry for
the WARNING. No BALF client in the repository sends frames (the
`docs/examples/balf` files only parse), and the operator guide's minimal
client numbers correctly. `BalfBridge.send` now numbers frames like a client
library (`raw=True` sends them as built) and `logout()` lost its `seq_no`.
Ten existing integration/robustness tests sent numbers the spec forbids
(the first frame after LOGON as 2, a heartbeat as 99 or 5, a client-sent
`ORDER_ACK` as 99) and were renumbered 1, 2, 3; each failed only on
"connection closed by gateway". The spec now says the gateway tolerates
non-zero `flags`/reserved bytes and closes on a sequence error. The gap and
repeat tests failed first (session still open); the consecutive and wrap
tests passed before, as unchanged behaviour. Full suite: 14 418 passed,
1 skipped.

### WP-BALF09 — Comments, docstrings, help texts, guides (D1–D10)

**Tests first:** none beyond `make _check` and `mkdocs build`; the text must
describe the code after WP-BALF01–08. Re-walk the operator guide's session
lifecycle, troubleshooting table and minimal client against the final code
(lessons-learned §B1).

**Change.** D1–D10; the reject and `cancel_reason` tables in both books
(Q2/Q3); a "Reconnecting" section (Q1); the server-message table.

**Exit criteria.** `make _check`, `poetry run mkdocs build` clean; every D
item resolved.

**Outcome (2026-11-15).** D1 `gateway.py` module docstring rewritten (loop,
order map, subscriptions, every defensive rule as the code now has it); D2
went with WP-BALF02's comment; D3 with WP-BALF06 (`cancel_reason_from_engine`
made true rather than deleted); D4 `build_amend_ack` lost its unused
`reject_reason` parameter (no caller passed it) and its wrong docstring; D5
`struct` imported once at the top, the in-loop import and the
`struct_error` try/except removed (`parse_logon` checks the length before
unpacking, so only `ValueError` can come out). Spec
(`020-balf.md`): order ids belong to the gateway ID (identifier rules, order
ID encoding with what a gateway restart loses, field tables, parsing notes),
`ORDER_ACK.timestamp_ns` wording, the `cancel_reason` table, `0x0E`,
`LOGOUT` bidirectional and what the gateway does with it, heartbeat
liveness as implemented, `heartbeat_*` typed Number. Operator guide
(`020-balf-gateway.md`): `auth_timeout_sec` (D9), sequence checking, LOGOUT
behaviour, a new "Reconnecting" section (D10), `STOP_TRIGGERED` and `LOGOUT`
in the server-message table (D6), `0x0E`, `timestamp_ns` in the execution
report table, the `cancel_reason` table, disconnect triggers, `EVICT_OLD`
keeps order ids, troubleshooting rows (D7 rewritten; sequence error, lost
events, rate limit added). Beyond the D list, re-walking the books (§B1)
found two more passages the WPs had made false, fixed here: the risk-controls
chapter said an SMP cancel cannot be told apart over BALF, and
`docs/examples/balf/balf_parser.py`'s docstring said order ids start over
after a LOGOUT; the known-limitations table now names the gateway-restart
limit. The minimal client in the guide numbers its frames correctly.
`make _check` and `mkdocs build` clean. Full suite: 14 435 passed,
1 skipped (with `-o faulthandler_timeout=60`). **A first full run hung** in
one xdist worker (main thread in `poll`, two ZMQ listeners, no gateway
thread) until the outer timeout killed it; it did not recur in the rerun or
in 33 runs of all BALF and gateway test files. In those runs one test failed
once: `test_balf_gwy_robustness.py::TestFrameStreaming::test_pipelined_heartbeats_both_acked`
with `Address already in use` binding a port `free_ports()` had just
returned (a pre-existing race in the shared helper, not this review's code).

---

## 9. Out of scope, noted

- **`enabled` read with `bool()`** in `balf_gwy/config.py:106`,
  `alf_gwy/config.py:82` and `api_gateway/config.py:238`: `enabled: "false"`
  is true. pm-cverifier refuses a non-bool, so a file deployed with
  `pm-config-deploy` is safe; this is the class of
  `EduMatcher-For-Later-ToDo.md` L024, and the three gateway fields are added
  to it.
- **Engine reason for a negative trailing offset.** A TRAILING_STOP with
  `trail_offset = -1.00` and no prior trade is refused with "Trailing stop
  requires STOP= or a prior trade price", so the client is told about a
  missing price rather than an invalid offset *(repro)*. Engine validation
  order, not BALF: **L026**.
- **Gateway restart and resting orders** (Q1 option b): even after
  WP-BALF01 a pm-balf-gwy restart loses the order map; adopting the engine's
  live orders at logon needs a BALF protocol addition: **L027**.

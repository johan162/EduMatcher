# pm-dc-gwy Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/dc_gateway/` at `03d31bb1` (v0.80.0): `gateway.py`
(584 lines, the TCP loop, sessions, HELLO handling, the refcounted topic
subscriptions and the `DC_FILL` relay), `main.py` (193, the CLI), `config.py`
(111), `protocol.py` (74, line parsing and building) and `__init__.py` (6). The
publisher it relays (`engine/drop_copy.py` `DropCopyPublisher.publish_fill`,
fed from `engine/main.py:3503-3519`), the payload contract
(`spec/messages/drop_copy.yaml` `drop_copy_event`) and `messaging/bus.py`
`make_subscriber` were read where they decide this gateway's behaviour, not
reviewed as code of their own. pm-ralf-gwy (reviewed the same day,
`EduMatcher-RALF-Gateway-Review-2026-11.md`) and pm-md-gwy were read for
comparison: the three share the loop and close model.

**Focus:** correctness, edge-case handling, performance, and whether the
comments, help texts, the operator guide chapter
(`docs/books/operator-guide/part-5-gateways/060-drop-copy-gateway.md`) and the
drop-copy chapter
(`docs/books/protocols-and-clients/part-3-session-behaviour/060-drop-copy.md`)
say what the code does.

**Previous work:** the Line-Gateway Alignment workplan
(`docs-design/EduMatcher-Line-Gateway-Alignment-Workplan.md`, W1–W6,
committed): `ValueError` from `select` caught and `max_connections` (F1), the
4096-byte line cap including the terminated line (F4), nothing answered after
the line that ends a session (F5), the 5 s HELLO deadline (F11), the 5 s close
grace and `_drop_backlog`, `ERR` key `DETAIL` and `AUTH_REQUIRED` for a bad
`HELLO` (D1, D2), heartbeat/idle doc fixes and the phantom `IDLE_TIMEOUT` code
removed (F13). Earlier: K16/K17 (event-loop fairness, strict config coercion);
the M033 verifier check (idle timeout more than twice the heartbeat). The
pm-ralf-gwy review recorded two items about this gateway in the For-Later list
(L035, L036); this review takes them over and corrects L035 (see §9). Their
fixes are in place and are not repeated here.

**Method:** every line of the files above was read. Findings marked *(repro)*
were reproduced with scratch scripts against the tree at `03d31bb1`: a real
`DcGateway` thread on real TCP, fed by the engine's real `DropCopyPublisher`
bound on a free port, so every message is exactly what the engine sends;
clients are plain sockets speaking DC1. The gateway module's `decode` was
wrapped with a counter to see what the gateway receives. *(measured)* means
timed on this host with the same setup. The other findings are by
inspection, with line numbers given.

Status: **Done, uncommitted.** WP-DCG01–05 completed 2026-11-15 in order,
each test-first with a full-suite run. Decisions Q1–Q5 were taken as
recommended (the user asked for all WPs in one go); see §7.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (lines the client receives and their `SEQ`s, the
   gateway's health samples and log records, config refusals).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_dc_gwy_*.py`,
   `tests/test_dc_examples.py` and `tests/test_dc_spy.py` with `-n logical`,
   then black/flake8/mypy/pyright. Do not start the next WP with a known
   failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Session tests should be fed by the engine's real `DropCopyPublisher`
(`DropCopyPublisher(zmq.Context.instance(), addr=...)` and `publish_fill`),
not hand-built frames, so the payload keys and the topic are the engine's.
The review's scratch `harness.py` (about 70 lines) does that and can become
the fixture in `tests/test_dc_gwy_gateway.py`.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-DCG01 | Other participants' traffic never costs a watched participant's fills, and a loss is counted | H1, P1 | Q1 | 0.5 d | ☑ | 2026-11-15 |
| 2 | WP-DCG02 | Every `DC_FILL` says when it happened and which trade it was | C1 | Q2 | 0.5 d | ☑ | 2026-11-15 |
| 3 | WP-DCG03 | The loop serves every descriptor and a stop says goodbye | C3, C4, C5 | Q4, Q5 | 0.5 d | ☑ | 2026-11-15 |
| 4 | WP-DCG04 | The config refuses a name the gateway cannot send | C6 | — | 0.25 d | ☑ | 2026-11-15 |
| 5 | WP-DCG05 | Comments, help texts and guides say what the code does | C2, D1–D8 | Q3, WP-DCG01–04 | 0.5 d | ☑ | 2026-11-15 |

Suggested order: **WP-DCG01 → WP-DCG02 → WP-DCG03 → WP-DCG04 → WP-DCG05**.
WP-DCG01 is the only path where fills are lost. WP-DCG02 changes the wire
(additive fields) and needs Q2. WP-DCG03 should land together with
WP-RALF04 so the line gateways stay alike. WP-DCG05 goes last so every text
describes the code as it ends up.

Estimated sequential effort: about 2.25 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The **session edges** are sound since the alignment work: a 4096-byte line
cap, a 5 s HELLO deadline, nothing answered after the line that ends a
session, a final line on every gateway-initiated close and a bounded drain.
The **relay** reads the keys the engine actually sends: `SEQ`, `ORDER_ID`,
`SYMBOL`, `FILL_QTY`, `FILL_PRICE` and `LIQUIDITY` are the publisher's values
*(repro)*. Unlike pm-ralf-gwy, `SEQ` is the engine's own per-participant
counter, passed through, so a client can see a loss as a gap.

The defects are in three places:

- **Fills lost because of somebody else's traffic (H1).** The engine
  subscriber is created with no topic, which in `make_subscriber` means
  *every* topic, so the refcounted per-ID subscriptions add nothing: the
  gateway receives and decodes every participant's fills whether anyone
  watches them or not, through ZeroMQ's default 1000-message buffer. A burst
  for unwatched participants cost a watched one 857 of 2 001 fills. The
  operator is told nothing, and the client learns of it only from the `SEQ`
  of its *next* fill, if there is one; DC1 has no replay.
- **Fills without time or trade (C1).** `DC_FILL` drops the payload's
  `timestamp` and `trade_ids`. A clearing or risk consumer cannot tell when a
  fill happened, cannot match it to the public trade, and cannot tell an
  engine restart (`SEQ` back to 1) from anything else.
- **Loop and shutdown hardening (C3–C5).** The same as pm-ralf-gwy:
  descriptors above 1023 stop every client being read, a stop sends no
  `EXIT`, a half-closed reader is dropped.

Severity key: **High**: a fill is not delivered to a client watching that
participant, and nothing tells the operator. **Med**: a lost or misleading
field or figure; a session that cannot do its job. **Low**: hardening,
clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| H1 | High | Engine feed | Subscribed to every participant with the default RCVHWM: a burst for unwatched IDs cost a watched ID 857 of 2 001 fills; no log, no metric *(repro)* | DCG01 |
| C1 | Med | Fields | `DC_FILL` carries no time, no trade id and no run identity; the payload has `timestamp` and `trade_ids` *(repro)* | DCG02 |
| C2 | Low | HELLO | Any `ID` is welcomed, including one no participant has: a typo looks exactly like "no fills yet" *(repro)* | DCG05 |
| C3 | Low | Loop | Once a descriptor reaches 1024, `select` fails every pass: no client is read again, WARNING about 100 times a second *(repro)* | DCG03 |
| C4 | Low | Shutdown | A stop closes every session without a line: no `EXIT`, queued lines dropped *(repro)* | DCG03 |
| C5 | Low | Sessions | A client that half-closes after its `HELLO` is disconnected as `peer_closed` before any fill *(repro)* | DCG03 |
| C6 | Low | Config | A `name` containing `\|` deploys and kills the gateway at the first `HELLO` | DCG04 |
| P1 | Low | Latency | Fixed 10 ms sleep per pass: publish → `DC_FILL` median 7.3 ms; at most 1000 events per pass *(measured)* | DCG01 |
| D1–D8 | — | Texts | See §5 | DCG05 |

---

## 3. Correctness findings

### H1. Other participants' traffic drops a watched participant's fills *(repro)* — High

`gateway.py:121` creates the subscriber with no topic:

```python
self._sub: zmq.Socket[bytes] = make_subscriber(config.drop_copy_pub_addr)
```

`make_subscriber` subscribes to everything when given no topics
(`messaging/bus.py:383-384`). The per-ID `SUBSCRIBE`/`UNSUBSCRIBE` with
refcounts (`gateway.py:419-441`) is therefore a no-op: the `""` subscription
is never removed, and `_poll_dc_events` (`gateway.py:443-468`) receives and
decodes every participant's fills, then discards those nobody watches. No
`rcvhwm` is passed, so ZeroMQ's default of 1000 messages applies, and a SUB
socket drops silently past it (`bus.py:373-376`). pm-md-gwy, pm-alf-gwy,
pm-balf-gwy, pm-clearing, pm-stats and pm-audit all pass `rcvhwm=100_000`.

Repro, with the engine's `DropCopyPublisher`:

| Step | Result |
|---|---|
| No client connected; 1000 fills for `TRADER07` | 1000 decoded by pm-dc-gwy |
| One client watching `TRADER01`; 40 000 fills for `TRADER10`–`TRADER29` with 2 000 `TRADER01` fills interleaved, then one more `TRADER01` fill after the burst | client receives **1 144 of 2 001**; `SEQ` 1–1143, then 2001 |
| Gateway log, health beacon | nothing |

The client's first sign of the loss is the jump to 2001, which came only
because the script sent one more fill after the burst. A participant that
does not trade again that day leaves its watcher believing it has every fill.
DC1 has no replay (operator guide lines 59-66), so even a client that sees the
gap cannot recover over this protocol. The operator, who could, has no
figure: `metric_samples` (`gateway.py:166-177`) has no loss counter.

The fixed 10 ms sleep per pass (P1) makes the buffer fill sooner.

**Fix.** See Q1: subscribe per ID only, a 100 000-message RCVHWM, and a
per-ID payload-`seq` check that counts gaps in the beacon and logs a
latched WARNING.

### C1. `DC_FILL` has no time, no trade id and no run identity *(repro)* — Med

`_poll_dc_events` builds the line from six keys (`gateway.py:470-480`):

```text
DC_FILL|SEQ=1|ORDER_ID=O1003|SYMBOL=AAPL|FILL_QTY=100|FILL_PRICE=100.25|LIQUIDITY=TAKER
```

The payload (`drop_copy.yaml` `drop_copy_event`, filled at
`engine/drop_copy.py:155-183`) also carries `timestamp` (epoch ns, when the
engine published) and `trade_ids` (the public `trade.executed` id(s)). Both
are dropped. As a result:

- A consumer has only its own receive time, which is wrong by the queueing
  delay and after midnight lands on the wrong date.
- A fill cannot be matched to the public trade (`trade.executed.id`, RALF
  `EXEC_ID`, clearing's trade rows), which is what a reconciliation needs.
- `SEQ` restarts at 1 when the engine restarts (drop-copy chapter line 108).
  A client that was connected across the restart sees `SEQ` go backwards; one
  that reconnects after the new run has passed its last `SEQ` sees a
  plausible continuation or a false gap. The trade id's prefix is the
  engine-run sequence (`models/trade.py:102`), which would make the restart
  explicit.

The guide says "`DC_FILL` fields map directly from the drop-copy payload"
(lines 288-292), which suggests nothing is missing.

**Fix.** See Q2: add `TS` (from `timestamp`) and `TRADE_ID` (the
`trade_ids`, comma-joined) to `DC_FILL`.

### C2. A mistyped ID is welcomed and then silent *(repro)* — Low

`_handle_hello` (`gateway.py:377-413`) accepts any non-empty `ID`:
`HELLO|…|ID=NOSUCHGW` gets `WELCOME|…|ID=NOSUCHGW` and then only
heartbeats. That is consistent with the documented "no authentication"
stance (guide lines 232-237), but the guide's troubleshooting row for
"`WELCOME` arrives but no `DC_FILL` ever does" (line 414) lists only "no fills
yet" and a failed engine bind, not a wrong `ID`, which is the likelier cause.

**Fix.** See Q3.

### C3. A descriptor at 1024 or above stops every client being read *(repro)* — Low

`_read_client_data` (`gateway.py:229-238`) passes every session to
`select.select`, which raises `ValueError` for a descriptor of 1024 or more.
Alignment F1 caught it, so the loop survives, but each pass then returns
without reading any client. Repro with 1100 descriptors open: a new client's
`HELLO` is never answered, and `WARNING read select failed: filedescriptor out
of range in select()` is logged 98 times in one second. Every other client
stops being read too (`PING`, `EXIT`), but none is disconnected. The same code
is in pm-md-gwy and pm-ralf-gwy (RALF review C5).

**Fix.** `select.poll`, as WP-RALF04.

### C4. A stop closes every session without a word *(repro)* — Low

`close()` (`gateway.py:179-195`) closes each client socket; queued lines are
dropped and no `EXIT` is sent. A connected client reads only EOF and cannot
tell a planned stop from a crash. Every other gateway-initiated close sends a
final line. Same as RALF review C7.

**Fix.** See Q4.

### C5. A client that half-closes is disconnected *(repro)* — Low

`recv` returning `b""` disconnects at once (`gateway.py:254-256`). A reader
that half-closes its write side after `HELLO` (`printf 'HELLO|…\n' | nc host
5590`) receives `WELCOME` and is then dropped before any fill. DC1 clients
send nothing after `HELLO` except `PING`/`EXIT`, so this is a natural way to
script one. The guide's own `printf … | nc` example (line 403) sends `EXIT`
as well, so it does not show the difference.

**Fix.** See Q5.

### C6. A `name` with `|` kills the gateway at the first `HELLO` — Low

`config.py:41` takes `name` as any string; `WELCOME` carries `GW=<name>`
(`gateway.py:397-407`), and `build_line` raises `DcProtocolError` for `|`
(`protocol.py:71-72`). The exception propagates out of `_handle_hello`
through the run loop, and the process ends with a traceback. This is the
code path reproduced for pm-ralf-gwy (RALF review C6), where
`pm-config-deploy --check` accepted the same name. `build_line` does not check
`\n`/`\r`, so a name containing a newline splits `WELCOME` in two.

**Fix.** Refuse an empty `name` or one containing `|`, `\n` or `\r` in the
loader; `build_line` refuses `\n`/`\r` in a value.

---

## 4. Performance findings

Only P1 matters, and only through H1.

### P1. A fixed 10 ms sleep per pass *(measured)* — Low

`run()` (`gateway.py:145-154`) sleeps 10 ms after every pass, and
`_poll_dc_events` handles at most 1000 events per pass (`gateway.py:58`).

| Measure | Value |
|---|---|
| `publish_fill` → client `DC_FILL`, median / p99 | 7.3 ms / 7.5 ms |
| Ceiling, by construction | 1000 events per pass of at least 10 ms: under 100 000/s, minus handling |

The latency is fine for a drop-copy feed. The ceiling matters because the
gateway today handles every participant's events (H1).

**Fix.** Do not sleep after a pass that exhausted the budget. With H1's
per-ID subscriptions the gateway sees only watched traffic.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | guide lines 37, 198, 245-247, 257-259; `gateway.py:118-119` | The internal SUB is described as "refcounted per gateway_id", subscribing and unsubscribing per ID; it receives every ID today (H1). True once WP-DCG01 is done; re-check the wording then. |
| D2 | `main.py:40-43`; guide line 144 | `--engine-dc-pub` "default: value from config, then tcp://127.0.0.1:5557": no config key exists (`config.py:70-73`); the default is `DROP_COPY_PUB_ADDR`, `tcp://$EDUMATCHER_ENGINE_HOST:5557`. |
| D3 | `main.py:61`; guide line 147 | `-q` "Reduce log output to warnings/errors": WARNING is already the default (L034 pattern). |
| D4 | `config.py:55-56` | A second `port <= 0` check after `config.py:44-45` already refused it: dead code. |
| D5 | guide lines 288-292 | "`DC_FILL` fields map directly from the drop-copy payload": three payload fields are dropped (C1). |
| D6 | drop-copy chapter lines 186-188 | "Detect gaps … should request a replay": no replay is reachable over DC1 or any other external protocol (same chapter, lines 214-219). Say what a DC1 consumer can do on a gap (reconcile from clearing or REST). |
| D7 | guide line 414 | The "no `DC_FILL` ever arrives" row omits a wrong `ID` (C2). |
| D8 | `protocol.py:3-8` | "the wire grammar is just HELLO/WELCOME plus unsolicited DC_FILL/HB lines": there are also `PING`/`PONG`, `EXIT` and `ERR`. |

---

## 6. Verified as correct

- **Payload keys.** Every key `_poll_dc_events` reads exists in
  `drop_copy_event` and is filled by `publish_fill`; `FILL_PRICE` is the
  display float (`100.25` in the repro).
- **`SEQ` is the engine's.** It is passed through, not renumbered, so loss
  between the engine and the client shows as a gap in the client's stream.
- **ID case.** The engine upper-cases gateway ids at config load
  (`engine/config_loader.py:772`, `1303`); the gateway upper-cases the `HELLO`
  `ID` and the topic suffix (`gateway.py:380`, `465`), so they match.
- **Several watchers per ID.** Each gets every line; disconnecting one keeps
  the others' delivery (the fd sets in `_sessions_by_gateway`).
- **Idle versus heartbeat.** An idle timeout at or below twice the heartbeat
  cannot be deployed (M033 is an ERROR, and `pm-config-deploy` refuses
  blocking findings).
- **Order ids** are engine-minted (`models/ids.new_order_id`), so a `|` in
  `ORDER_ID` cannot reach `build_line`.

---

## 7. Decisions

| # | Question | Recommendation |
|---|---|---|
| Q1 | How is engine-side loss prevented and shown (H1)? (a) Subscribe per watched ID only (no `""` subscription), RCVHWM 100 000, and track each watched ID's payload `seq`: a jump is counted in the beacon (`gwy.feed_gaps`) and logged as a latched WARNING; `seq` going back to 1 is an engine restart, logged at INFO. (b) (a) plus an in-band line to affected clients. | **(a)**. The client already sees the gap in `SEQ`; what is missing is that the operator sees it, and that unwatched traffic cannot cause it. (b) adds a message type for information the client has. |
| Q2 | Which payload fields does `DC_FILL` gain (C1)? (a) `TS` (ISO-8601 UTC with milliseconds, from `timestamp`, as every other line protocol here) and `TRADE_ID` (`trade_ids` comma-joined). (b) (a) plus `GW` (the participant). (c) None; document what is missing. | **(a)**. Both are additive; the bundled Python and C parsers keep unknown fields. (b) repeats the session's own `ID`. (c) leaves reconciliation impossible. |
| Q3 | A `HELLO` for an ID no participant has (C2)? (a) Keep accepting it; name the wrong-ID case in the guide's troubleshooting. (b) Refuse with `ERR|CODE=UNKNOWN_ID` against the compiled config's gateways. | **(a)**. The "no authentication" stance makes (b) a convenience only, and it would refuse IDs added by a redeploy until pm-dc-gwy restarts. |
| Q4 | Should a stop say goodbye (C4)? (a) `EXIT|REASON=shutdown|TS=…` to every session and a flush bounded at 1 s. (b) Leave as is. | **(a)**, the same as RALF Q7, so the line gateways stay alike (pm-md-gwy via L036). |
| Q5 | Half-closed clients (C5)? (a) Document that a half-close ends the session. (b) Keep the session until a send fails or it idles out. | **(a)**, as RALF Q8, for alignment; (b) also needs send errors to disconnect (`gateway.py:313-315`). |

**Taken (2026-11-15):** Q1 (a), Q2 (a), Q3 (a), Q4 (a), Q5 (a): the
recommendations, as the user asked for all WPs to be completed in one go.

---

## 8. Work packages

### WP-DCG01 — Other participants' traffic never costs a watched participant's fills, and a loss is counted (H1, P1; after Q1)

**Tests first** (`tests/test_dc_gwy_gateway.py`):

1. With no client connected, 1000 fills for an unwatched ID are not
   received by the gateway's subscriber (the counted `decode` stays at 0).
   (Fails today.)
2. The H1 repro (one watcher of `TRADER01`, 40 000 unwatched fills with
   2 000 watched ones interleaved, one more after): the client receives all
   2 001 with no `SEQ` gap. (Fails today.)
3. An ID that is a prefix of another (`TRADER1` versus `TRADER10`): the
   `TRADER1` watcher receives only `TRADER1` fills. Unchanged (it passes today
   only because of the exact match in `_poll_dc_events`; it guards the
   per-ID subscription).
4. A `seq` jump of 5 for a watched ID: the beacon reports `gwy.feed_gaps` = 5
   and one WARNING is logged; a second jump within the latch window adds to
   the counter without another WARNING. (Fails today.)
5. `seq` back to 1 for a watched ID (engine restart) is not counted as a gap.
   (Fails today: there is no check; the test asserts the INFO record.)
6. A pass that exhausted the 1000-event budget does not sleep. (Fails today.)
7. The last watcher of an ID disconnects: the subscription is removed (a
   later fill for that ID is not received). (Fails today.)

**Change.** A SUB socket with `rcvhwm=100_000` and no initial subscription
(a small `make_subscriber` call with an explicit empty topic list is not
available; create it with the bus context and the same option order, or add
the option to `make_subscriber` on this component's path only); per-ID last
`seq` tracking in `_poll_dc_events`; a `gwy.feed_gaps` counter in
`metric_samples`; skip the sleep when the budget ran out.

**Exit criteria.** Tests 1–7 pass; `tests/test_dc_gwy_*.py` and the monitor
tests that read `gwy.*` samples green.

**Outcome (2026-11-15).** The drop-copy SUB is still made by
`make_subscriber` (now with `rcvhwm=100_000`), and its catch-all `""`
subscription is removed straight after (`UNSUBSCRIBE b""`), so only the
per-ID topics of `_dc_subscribe` remain. Keeping `make_subscriber` keeps the
shared stub in `tests/test_gateway_metrics.py` working, which a direct
`get_context().socket(zmq.SUB)` broke (23 errors in the first full run).
`_check_feed_seq` tracks the last payload `seq` per watched ID: a jump adds
the missed count to `gwy.feed_gaps` (a new counter in `metric_samples`) and
logs one WARNING (`drop-copy feed lost %d event(s) for %s: seq %d..%d …`),
latched for 60 s with a running "lost since the last warning" figure, as
pm-md-gwy's `md.bus_gaps`. `seq` at or below the last one is logged at INFO
as an engine restart and not counted. An ID's last `seq` is forgotten when
its last watcher leaves, so fills nobody watched are not a gap for the next
watcher (a regression found on the way; test added).
`_poll_dc_events` returns whether the 1000-event budget ran out, and `run()`
skips the 10 ms sleep after such a pass (P1). Idle latency is unchanged by
design (the sleep stays when there is no backlog).

Beyond the WP text: pm-monitor watches the counter (`WATCHED_INCREASES`
`gwy.feed_gaps` → rule `dc_feed_gaps`, any increase in 5 min), mirrored in
dash-gui's `FIXED_RULES` (`thresholds.ts`) and the health-monitor chapter's
rule table; the new WARNING has a log-ledger entry. Without a rule the
counter would only be visible in raw metrics, which is the H1 complaint.

Measured on this host after the change: a fill published 0, 1, 5 or 20 ms
after `WELCOME` was delivered 20/20 times each. The per-ID SUBSCRIBE is sent
in the HELLO pass, before `WELCOME` is queued, so dropping the catch-all
subscription opened no visible startup window on a local engine.

Tests (`tests/test_dc_gwy_gateway.py`): 1 unwatched fills never decoded
(failed first: 1000 decoded); 2 the H1 repro, all 2 001 with `SEQ` 1–2001
(failed first: index 786, `SEQ` 1330 for 787); 3 prefix ID (unchanged,
passed); 4 gap counted 5 then 7 with one WARNING naming `2..6` (failed
first: 0 == 5); 5 restart at INFO, no gap (failed first: no INFO record);
7 last watcher leaving removes the subscription (failed first: 6 decoded vs
1); 6 no sleep after a full pass, first sleep at 2 500 decoded (failed
first: at 1 000); plus the regression test "fills while unwatched are not a
gap" and `test_health_contract.py`'s owner list (failed first, then passed).
Full suite: 14 556 passed, 1 skipped.

### WP-DCG02 — Every `DC_FILL` says when it happened and which trade it was (C1; after Q2)

**Tests first** (`tests/test_dc_gwy_gateway.py`, `tests/test_dc_examples.py`):

1. A fill published with `trade_ids=["000003-000000017"]` arrives as
   `DC_FILL|…|TS=<ISO of timestamp>|TRADE_ID=000003-000000017`. (Fails today.)
2. Two `trade_ids` are comma-joined. (Fails today.)
3. The Python and C example parsers and subscribers accept the new fields,
   and the example subscriber prints the trade id. (Fails today for the
   print.)
4. The existing six fields keep their values and order. Unchanged.

**Change.** Two fields in `_poll_dc_events`; the protocol table, the wire
example and D5 in the guide; the examples.

**Exit criteria.** Tests 1–4 pass; `tests/test_dc_*.py` green.

**Outcome (2026-11-15).** `DC_FILL` gains `TS` (`iso_utc(timestamp / 1e9)`,
the same format as `HB`/`PONG`) and `TRADE_ID` (`trade_ids` comma-joined),
after the six existing fields. The Python and C example subscribers print
`trade=<TRADE_ID> … at <TS>` in their fill line; their parsers needed no
change (the C parser holds 64 fields). Docs: the operator guide's `DC_FILL`
row, the sequence diagram, the wire example, and a field-by-field mapping
table that replaces "map directly from the drop-copy payload" (D5); the
example-libraries chapter's parse example. Tests: two in
`tests/test_dc_gwy_gateway.py` (field order and values, and two trade ids;
both failed first: no `TS`/`TRADE_ID`), the Python example test asserting the
new fields and a new print test, and the C example test's expected line (all
failed first). Full suite: 14 559 passed, 1 skipped.

### WP-DCG03 — The loop serves every descriptor and a stop says goodbye (C3, C4, C5; after Q4, Q5)

**Tests first** (`tests/test_dc_gwy_gateway.py`):

1. With 1100 descriptors open, a new client's `HELLO` gets `WELCOME` and no
   `read select failed` WARNING is logged. (Fails today.)
2. On `stop()`, a connected client reads `EXIT|REASON=shutdown|TS=…` before
   EOF. (Fails today.)
3. A client that stopped reading does not hold the stop for more than 1 s.
   (Fails today: the test pins the bound.)
4. A half-closed reader is disconnected as `peer_closed`, unchanged; the
   behaviour is now documented.

**Change.** `select.poll` in `_read_client_data`; `close()` queues
`EXIT|REASON=shutdown` and flushes for at most 1 s. Implement together with
WP-RALF04 so the two gateways' code stays the same.

**Exit criteria.** Tests 1–4 pass; `tests/test_dc_gwy_*.py` green.

**Outcome (2026-11-15).** `_read_client_data` builds a `select.poll` over the
client descriptors each pass and treats any event as "call `recv`", so EOF
and errors are settled where they were before; the WARNING is now `read poll
failed: %s` (log-ledger entry renamed). On a normal stop, `run()` calls the
new `_flush_for_shutdown()`: one more relay pass, `EXIT|REASON=shutdown|TS=…`
to every session not already closing, then flushes for at most
`SHUTDOWN_FLUSH_SEC` = 1 s; sessions that drain are disconnected as
`shutdown`. `close()` now disconnects the rest through `_disconnect` (so they
are counted and unsubscribed), with reason `shutdown`, or the reason a
session was already closing with. Not run after a crash, as in pm-balf-gwy.
Docs: the guide's Step 4 (half-close ends the session, Q5; the stop's
`EXIT`), an `EXIT` row in the gateway→client table, the error-codes note, the
`printf … | nc` troubleshooting example, and the reference manual's
"Messages published" table.

Tests: 1 descriptor above 1023 (failed first: timeout, `read select failed`
logged ~100/s); 2 `EXIT|REASON=shutdown` before EOF (failed first: nothing
before EOF); 3 non-reading client holds the stop under 1.5 s. Test 3's timing
part passed before the change too (close() was immediate); it failed first
only on the `shutdown` disconnect count, and it pins the new 1 s bound.
4 half-close is `peer_closed` (unchanged, passed). Full suite: 14 563 passed,
1 skipped.

WP-RALF04 is not done yet, so pm-ralf-gwy still has the `select` loop and the
silent stop; when it is, `_read_client_data` and `_flush_for_shutdown` here
are the code to copy.

### WP-DCG04 — The config refuses a name the gateway cannot send (C6)

**Tests first** (`tests/test_dc_gwy_config.py`, `tests/test_dc_gwy_protocol.py`):

1. `name: "dc|01"`, `name: "a\nb"`, `name: ""` → `ValueError` naming
   `dc_gateway.name`. (Fails today.)
2. `build_line("X", {"K": "a\nb"})` raises `DcProtocolError`. (Fails today.)
3. Defaults and every bundled example config still load. Unchanged.

**Change.** Checks in `_load_dc_gateway_config_from_raw`; `\n`/`\r` in
`build_line`; D4 in the same edit.

**Exit criteria.** Tests 1–3 pass; `tests/test_dc_gwy_config.py` and the
verifier/deploy tests green.

**Outcome (2026-11-15).** `_load_dc_gateway_config_from_raw` refuses an empty
`name` or one containing `|`, CR or LF (`dc_gateway.name must be non-empty,
without '|' or line breaks`); `build_line` refuses CR/LF in a key or value.
The dead second `port <= 0` check is removed (D4). pm-cverifier runs the same
loader, so `pm-config-deploy` refuses the name too: a `dc_gateway.name=dc|01`
case was added to `tests/test_cverifier_deploy_agreement.py` (failed without
the loader change: "the case must be one the loaders refuse"). Docs: the
guide's `name` row and the formal specification's constraint. Tests: 4
refused names and one kept name in `tests/test_dc_gwy_config.py`, 2 line
breaks in `tests/test_dc_gwy_protocol.py` (all refusals failed first with
DID NOT RAISE). Full suite: 14 571 passed, 1 skipped.

### WP-DCG05 — Comments, help texts and guides say what the code does (C2, D1–D8; after Q3 and WP-DCG01–04)

**Tests first:**

1. `pm-dc-gwy --help` shows the corrected `--engine-dc-pub` and `-q` texts
   (`tests/test_dc_gwy_main.py`). (Fails today.)

**Change.** D1–D8 as listed in §5; the wrong-ID row (Q3); `make completion`
for the help change; re-walk every guide passage touched by WP-DCG01–03
(lessons-learned §B1).

**Exit criteria.** Test 1 passes; `make _check` and `mkdocs build` clean; the
full suite green.

**Outcome (2026-11-15).** D2: `--engine-dc-pub` help now names the real
default (`tcp://$EDUMATCHER_ENGINE_HOST:5557`, 127.0.0.1 when unset), in
`--help`, the guide, the reference manual and pm-help's option default. D3:
`-q` reads "Explicit WARNING log level (the default)", as pm-mm-bot's
(L034), in the same three places. D8: the protocol module docstring lists
`PING`/`PONG`, `EXIT` and `ERR`. D1: re-checked after WP-DCG01, the
"refcounted per gateway_id" wording is now true; Step 2 adds that only
watched IDs reach the gateway and that ZeroMQ's prefix match brings in
`TRADER10` for `TRADER1` (dropped by the exact match). D4, D5 were done in
WP-DCG04/02. D6: the drop-copy chapter's gap advice now says no replay is
reachable externally and names the reconciliation sources
(`GET /api/v1/history/fills`, `pm-clearing-cli trades --gateway`); the
de-duplicate point says duplicates come only from an in-process replay.
C2/D7 (Q3 a): the troubleshooting row names a wrong `ID`; two rows added for
a `SEQ` jump (pointing at `drop-copy feed lost` / `dc_feed_gaps`) and for
`EXIT|REASON=shutdown`. `make completion` regenerated the zsh completion.
Re-walked: the guide's quick-connect, lifecycle, protocol reference, error
codes and troubleshooting; the drop-copy chapter's sequence and pm-dc-gwy
sections; the example README and the example-libraries chapter; training
chapters 13 and 20 (only references, nothing to change).

Tests: two in `tests/test_dc_gwy_main.py` (both failed first on the old
texts). `make _check` and `mkdocs build` clean; the new anchors
(`#step-4-disconnect`, `#quick-connect-test`, `#sequence-numbers`,
`#get-apiv1historyfills`) exist in the built site. Full suite: 14 573
passed, 1 skipped.

---

## 9. Out of scope, noted

- **L035 is taken over by WP-DCG01 and corrected.** It said DC1 `SEQ` "stays
  dense" after a loss; it does not, because `SEQ` is the engine's counter
  passed through (§6). The row now points here.
- **L036 now concerns pm-md-gwy only** for its `select` loop and silent stop;
  pm-dc-gwy's share is WP-DCG03.
- **The engine's drop-copy publisher** keeps ZeroMQ's default send
  high-water mark (`engine/drop_copy.py:112-113`), so a slow subscriber can
  also lose messages at the publisher. After WP-DCG01 the gateway drains
  quickly enough that this is not reached in the repro; not changed here.
- **`liquidity_flag` for uncross prints.** The engine compares each side with
  `aggressor_side` (`engine/main.py:3510-3517`); for an uncross print that is
  `AUCTION`, so both events are `MAKER`, while `drop_copy.yaml` says "Exactly
  one of the two events a trade produces is TAKER". Engine behaviour, not this
  gateway's; recorded as **L037**.
- **`-q` in other entry points** is L034; this review rewords only
  pm-dc-gwy's (D3).
- **pm-alf-gwy's `DC|STATE=ON` relay** builds its own `DC_FILL` with the six
  original fields; WP-DCG02 changed only pm-dc-gwy's line. That relay goes to
  the participant's own session, whose `FILL` already carries the trade ids
  (`TRADE_IDS`, `alf_gwy/gateway.py:2020`), so it is noted here, not filed.
- **`tests/test_dc_examples.py::test_python_example_reports_backwards_seq_but_not_gaps`**
  has a docstring saying `SEQ` is engine-wide and gaps are routine; `SEQ` is
  per gateway ID and the example reports gaps. The test's assertions are
  right; only the docstring is stale. Not changed (not in this review's
  scope).

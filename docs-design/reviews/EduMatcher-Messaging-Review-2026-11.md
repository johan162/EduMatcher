# Messaging layer Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/messaging/` at `b91a1b7c` (v0.79.0): `bus.py`
(370 lines, the socket factories and the three wire wrappers
`SequencedPublisher`, `CausalPublisher`, `CausalPusher`) and
`reject_report.py` (90, `RejectReporter`, the gateway-refusal records). The
package is shared by every process on the bus: `make_pusher` is called from
15 packages, `make_subscriber` from 18, `make_publisher` by pm-engine,
pm-index and pm-market-sim, `RejectReporter` by pm-alf-gwy, pm-balf-gwy and
pm-api-gwy. The wire readers in `models/message.py` (`decode`,
`decode_sequence`, `decode_publisher_sequence`, `decode_envelope`), the
envelope in `models/envelope.py`, the engine's receive loop and command echo
(`engine/main.py:7495-7560`, `:8080-8160`) and the gateways' reporter wiring
were read where they decide this layer's behaviour. They were not reviewed as
code of their own.

**Focus:** correctness, edge-case handling, performance, and whether the
comments, docstrings and the wire-format passages of the architecture,
protocols and operator books say what the code does.

**Previous work:** no earlier review of the package itself. The features it
carries came in with the causal envelope (`b1a14eef`), `eseq` on every
message (`4dadc7b4`), gateway-local refusals as `system.gateway_reject`
(`c131c6f0`, folded per peer host in `1f8997cd`), and the fail-fast PUSH
options and `PushSocket` protocol from the gateway and scheduler reviews.
They are in place and are not repeated here.

**Method:** every line of the files above was read. Findings marked *(repro)*
were reproduced with a scratch script against the tree at `b91a1b7c`, using
the real `RejectReporter`, `make_publisher`/`make_subscriber` over TCP
loopback, and a real `Engine` started as `audit/replay/rerun.py:fresh_engine`
starts one (the `s1-basic` example) with the real publisher stack on an
`inproc` PUB socket. *(measured)* means timed on this host (36 cores, Python
3.14, pyzmq 27.3.0, libzmq 4.3.5) with `timeit`, best of 7, pinned with
`taskset` to one core because the host carried a load average of about 20
from a running simulation; unpinned runs read up to 2× higher. The other
findings are by inspection, with line numbers given.

Status: **Open.** Decision Q1 is needed before WP-MSG02. WP-MSG01 and
WP-MSG03 can start now.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (the frames a publisher sends, what the decode helpers
   read back, the `count` in the `system.gateway_reject` records a gateway
   sends).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_envelope_causation.py`,
   `tests/test_engine_command_echo.py`, `tests/test_gateway_reject_reporter.py`,
   `tests/test_api_gateway_rejects.py`, `tests/test_sim_forensics_*.py` and
   `tests/test_audit_*.py` with `-n logical`, then black/flake8/mypy/pyright.
   Do not start the next WP with a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

The wrapper tests should use a recording socket (any object with
`send_multipart`, as `SendsMultipart` allows) and the decode helpers, not a
real ZMQ socket; cost tests count calls and frames rather than wall time, in
the style of `tests/test_k18_hot_path_cost.py`. Reporter tests drive
`RejectReporter` with a fake clock and a `send` that raises `zmq.Again`, as
`tests/test_gateway_reject_reporter.py` does today.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-MSG01 | Stamping an envelope costs a third of what it does now, wire unchanged | P1 (ULID, envelope object) | — | 0.5 d | ☐ | |
| 2 | WP-MSG02 | A published message carries its sequences and envelope in one frame | P1 (frames), D3 | Q1, WP-MSG01 | 1 d | ☐ | |
| 3 | WP-MSG03 | A refusal record's `count` never drops refusals the gateway saw | C1, C2 | — | 0.5 d | ☐ | |
| 4 | WP-MSG04 | Docstrings and the books describe the wire as it is | D1, D2, D4–D9 | WP-MSG02 | 0.5 d | ☐ | |

Suggested order: **WP-MSG01 → WP-MSG03 → WP-MSG02 → WP-MSG04**. WP-MSG01 is
the larger half of the latency win and changes nothing anyone reads.
WP-MSG03 is independent and small. WP-MSG02 waits for Q1 because it changes
the internal wire format. The text WP goes last so the wire tables describe
the final layout.

Estimated sequential effort: about 2.5 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The layer does what its design says. The per-topic sequence makes every
subscriber's view contiguous regardless of its prefix filters, and a
subscriber that falls behind sees the hole (§6). A raised `rcvhwm` is set
before `connect()` and holds a 100 000-message burst with no loss. The
fail-fast PUSH options never block a reactor and do not hang process exit.
The causal attribution is correct on every path the engine uses: the cause
is set per inbound message and cleared in a `finally`, units run only from
the maintenance tick, and nothing in the engine, pm-index or pm-market-sim
publishes from a second thread. The command echo keeps the sender's
`msg_id`. Every PUSH to the engine goes through `make_pusher`.

The defects are in two places:

- **Cost on the engine's hot path (P1).** The publisher stack turns a
  2.2 µs PUB send into 11.7 µs. With trades on, an order the engine handles in
  58 µs takes 105 µs. 44 % of the engine's order-handling time is spent
  stamping three publishes. Half of the cost is minting the ULID and the
  envelope object in Python. The other half is the three extra frames. Both
  can be cut without losing any of what the frames carry.
- **Refusal counts that silently lose refusals (C1, C2).** `RejectReporter`
  documents one loss (the count of a burst nobody follows up). It has two
  more: clearing its table at 4096 peers drops every count it was folding,
  and a failed send drops the record *and* the refusals folded since.

Severity key: **High**: an order, fill or audit record lost or misattributed
without a warning. **Med**: a wrong, lost or misleading figure, or a cost
that moves the engine's latency materially. **Low**: hardening, clarity,
hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| P1 | Med | Publish path | The publisher stack costs 11.7 µs per message against 2.2 µs raw. An engine order goes from 58 to 105 µs median (+46 µs, 3 publishes) *(measured)* | MSG01, MSG02 |
| C1 | Low | Refusal records | Reaching 4096 tracked peers clears the table, so every folded count is dropped: 4147 refusals reported as 4098 *(repro)* | MSG03 |
| C2 | Low | Refusal records | A send that fails (engine away) resets the peer's state before sending: 1001 refusals reported as 100. On REST the failure is not even logged *(repro)* | MSG03 |
| D1–D9 | — | Comments, books | See §5 | MSG02, MSG04 |

---

## 3. Correctness findings

### C1. A full table drops every count it was folding *(repro)* — Low

`reject_report.py:438-439`.

```python
if len(self._state) >= _MAX_TRACKED:
    self._state.clear()
```

The table maps `(peer host, code)` to `(time of last record, refusals folded
since)`. Clearing it throws away the folded counts of every entry, including
peers still inside their interval. Nothing is logged.

Repro: host `10.0.0.1` is refused 50 times within one second (one record,
49 folded). Then 4096 other hosts are refused once each, and `10.0.0.1` once
more five seconds later:

| | refusals made | sum of `count` in the records sent |
|---|---|---|
| observed | 4147 | 4098 |

The 49 refusals folded for `10.0.0.1` are gone. The audit trail then
understates the burst that a dispute is about.

In practice this happens only on pm-api-gwy, which is reachable from many
hosts, during a scan or a misconfigured fleet (4096 distinct hosts × reported
codes). ALF and BALF see few hosts.

**Fix.** Evict instead of clearing. An entry whose interval has passed and
that folded nothing carries no information and can go. One that folded
something is sent as its own record (`count = folded`) before it goes.

### C2. A failed send loses the record and the refusals folded since *(repro)* — Low

`reject_report.py:440-454`.

The state is reset to `(now, 0)` *before* `self._send` is tried. When the
send raises (the engine's PULL is away: `make_pusher` sets `IMMEDIATE=1` and
`SNDTIMEO=0`, so the send raises `zmq.Again`), the record is lost. Every
refusal folded into that entry for the next interval is then counted toward
a record that was never sent.

Repro: a peer is refused 100 times a second for 10 s while the engine is
away, then once more after it is back:

| | refusals made | sum of `count` in the records sent |
|---|---|---|
| observed | 1001 | 100 |

On ALF and BALF the failure logs one WARNING per peer and code per second. On
REST it is not visible at all. `EngineClient.report` sends with
`require_engine=False`, and `EngineClient._send`
(`api_gateway/engine_client.py:229-243`) swallows `zmq.Again` and every
`EAGAIN`, so the reporter believes the record went out.

The engine being away also means the trail records nothing else in that
window, so the loss is in the *count* of the first record after it returns,
not in whether the peer appears at all. The operator guide
(`020-audit-trail.md:412-417`) promises that `count` is "the number it
folded in", and that is what is wrong.

**Fix.** Update the state only after the send succeeds. On failure, add this
refusal to the folded count and keep the old timestamp, so the next attempt
(at the next refusal) carries everything. Make REST's `send` raise on
`zmq.Again` the way ALF's and BALF's `push.send_multipart` does. That is a
one-line change at the reporter's call site in `api_gateway/main.py:158`; the
REST path does not need `EngineClient.report`'s 503 handling.

---

## 4. Performance findings

This matters at today's sizes. The engine is single-threaded, and every
message it publishes pays the cost on the order path.

### P1. The publisher stack quadruples the cost of a publish *(measured)* — Med

`bus.py:111-135` (`SequencedPublisher.send_multipart`), `:216-220`
(`CausalPublisher.send_multipart`), `:285-288` (`CausalPusher`);
`models/envelope.py:67-99` (`_encode_b32`, `new_ulid`), `:124-156`
(`Envelope`).

Per message, pinned to one core:

| What | µs |
|---|---|
| raw PUB `send_multipart`, 2 frames (topic, payload) | 2.2 |
| raw PUB `send_multipart`, 5 frames (as the stack sends) | 6.6 |
| `new_ulid()` | 2.7 |
| `Envelope.root().to_frame()` | 3.6 |
| `make_publisher` stack (`CausalPublisher(SequencedPublisher(PUB))`) | 11.7 |
| raw PUSH + PULL recv, 2 frames | 4.4 |
| `CausalPusher` + PULL recv | 11.6 |

Where the 9.5 µs go:

- **Three extra frames: about 4.4 µs.** ZMQ charges per frame: 2 → 5 frames
  costs 2.2 → 6.6 µs. `seq`, `eseq` and the envelope each ride in their own
  frame (`bus.py:126-132`).
- **The ULID: 2.7 µs.** `_encode_b32` (`envelope.py:67-72`) builds 26
  characters one at a time in a Python loop, twice per id (time and
  randomness). It re-encodes the 10-character time prefix on every call,
  though the prefix changes once a millisecond.
- **The envelope object: about 1 µs.** `current_envelope()` builds a frozen
  slotted dataclass (`Envelope.caused()`, 0.56 µs per construction) only to
  join it back into bytes in `to_frame()`.
- **List rebuilding** in two wrappers and two `str(int).encode()` calls make up
  the rest.

In the engine, with the real stack against a recording PUB socket (the
`s1-basic` example, 4000 crossing pairs: a resting sell, then a buy that
trades it; 3 publishes per order, median of 7600 handled orders after
warm-up):

| Publisher | median `order.new` handling |
|---|---|
| raw PUB (no wrappers) | 58 µs |
| `make_publisher` stack | 105 µs |

That is +46 µs per order, 44 % of the order path. The command echo
(`engine/main.py:7546`) adds one more 5-frame send per command on top, outside
the measured dispatch. A gateway pays the `CausalPusher` part (+7 µs) once per
request.

Prototypes of the two fixes (same machine, same pinning):

| Variant | µs per publish |
|---|---|
| current stack | 11.7 |
| (a) cached time prefix + 10-bit table encode of the randomness (0.9 µs per ULID), envelope built as bytes; wire unchanged | 8.2 |
| (b) (a), plus `seq`, `eseq` and the envelope packed into one `|`-separated frame | 5.5 |

Neither depends on history or on the day: the cost is per message and
constant.

**Fix.** (a) in WP-MSG01. Keep `new_ulid`'s lock, its monotonicity rule and
its clock-backwards rule. Cache the 10-character time prefix per millisecond,
and encode the 80 random bits with a 1024-entry two-character table (8
lookups). Let `CausalPublisher` and `CausalPusher` build the envelope frame
directly from strings instead of through `Envelope`. `Envelope` stays the
reader's type. (b) in WP-MSG02, after Q1.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `bus.py:1-6` | "Thin ZeroMQ socket factory functions." The module is the bus's wire contract: three wrappers that stamp sequences and envelopes, and the fail-fast PUSH policy. The docstring mentions none of it. |
| D2 | `bus.py:90-93` | "adding it costs one dict lookup and one int-to-bytes per send": there are two counters (`seq`, `eseq`) and two extra frames, about 3 µs measured (P1). |
| D3 | `bus.py:103-106` | "The envelope is found by its shape, so it may move one frame back." On PUB the envelope is at index 4, behind `seq` (2) and `eseq` (3). On PUSH it is at index 2. "One frame back" names neither. Superseded by WP-MSG02's layout. |
| D4 | `bus.py:153-156` | `SequencedPublisher.__getattr__` says "Everything else (close, closed, setsockopt, ...) passes through". Those three are declared right above it (`:143-151`) and no longer go through `__getattr__`. |
| D5 | `bus.py:274` | "each of the thirteen processes that call it": `make_pusher` is called from 15 packages (ai_trader, alf_console, alf_gwy, api_gateway, balf_gwy, board, commands, index, market_sim, md_gateway, mm_bot, scheduler, stats, ticker, viewer). Say "every process" instead of a count that drifts. |
| D6 | `bus.py:313-319` | `make_publisher`: "a socket that stamps a per-topic sequence *and* a causal envelope" leaves out `eseq`, the socket-wide order pm-audit relies on. |
| D7 | `models/message.py:93-96` | `decode`: "Publishers append a third frame carrying a per-topic sequence number". A PUB message carries three trailing frames (`seq`, `eseq`, envelope); a PUSH message carries one (the envelope). |
| D8 | `protocols-and-clients/part-5-message-reference/000-preamble.md:163-168`, `010-message-reference.md:174-179`, `architecture-and-development/part-1-architecture/010-architecture-overview.md` (frame table above `:179`), `020-guided-tour.md:1810-1816` and the `decode_envelope` excerpt "(index 3)" at `:1866`, `part-2-inside-the-engine/020-order-flow-end-to-end.md:874` | Every wire table puts the envelope at PUB `frame[3]`. `frame[3]` is `eseq`, and the envelope is `frame[4]`. None of them mentions `eseq`, which `pm-audit-replay anomalies` reports as `ESEQ_GAP` (`035-answering-a-dispute.md:28`). |
| D9 | `000-preamble.md:172-174`, `010-message-reference.md:183-186`, `020-guided-tour.md:1880-1883` | "this extension cost nothing on the hot path" and "the cost of the causal envelope is confined to the publish side: minting a ULID and formatting one short ASCII frame". `decode()` is indeed unaffected, but the publish side is the engine's hot path, and the stamping is 44 % of its order handling (P1). State the measured cost after WP-MSG01/02. |

---

## 6. Verified as correct

- **Per-topic sequence and gap detection.** A subscriber that read nothing
  during a 100 000-message burst, with the default high-water mark, received
  17 500 messages, and `decode_sequence` showed exactly one gap. With
  `rcvhwm=200000` it received all 100 000 with no gap. Setting the option
  before `connect()` (`bus.py:362-364`) is what makes it apply; the PUB side's
  default SNDHWM does not limit a subscriber whose own pipe has room.
- **Fail-fast PUSH and process exit.** With 1000 messages queued at a peer
  that never reads, and `LINGER` at its default of −1, `close()` and exit took
  1.0 s. pyzmq does not terminate the shared context at exit, so the
  unbounded linger never blocks.
- **One cause at a time.** `set_cause` is set per inbound message and cleared
  in a `finally` (`engine/main.py:8136-8147`). `begin_unit` is called only from
  `_flush_circuit_breakers` and `_expire_silent_gateways`, both run only from
  the maintenance list (`:7954`, `:7961`), outside any command, with
  `end_unit` in a `finally`. No thread exists in pm-engine, pm-index or
  pm-market-sim, so `CausalPublisher`'s single-threaded assumption
  (`bus.py:176-180`) holds.
- **Command echo.** Fewer than three frames is counted as "carried no
  envelope" and not echoed (`engine/main.py:7537-7543`). A third frame that is
  not an envelope is echoed verbatim and reads back as no envelope, because
  `Envelope.from_frame` is strict (26-character ULID, three fields), so a
  bare `seq` or `eseq` integer cannot be taken for one.
- **All engine-bound PUSH sockets carry an envelope.** Every PUSH to
  `ENGINE_PULL_ADDR` is made by `make_pusher`. The raw PUSH sockets
  (`market_sim/news_cli.py:63`, `market_sim/main.py:579`) go to pm-market-sim,
  not to the engine.
- **Peer host folding.** All three reporter callers pass `host:port`
  (`alf_gwy/gateway.py:2546`, `balf_gwy/gateway.py:1928`,
  `api_gateway/sessions.py:85`), so `rpartition(":")` gives the host also for
  IPv6 (`::1:5000` → `::1`).
- **REST reporter on one thread.** Every REST caller of `report_refusal` is an
  `async def` dependency or endpoint, so `RejectReporter`'s dict and the PUSH
  socket are only touched from the event-loop thread.
- **Module-level context and fork.** `get_context` caches
  `zmq.Context.instance()` (`bus.py:57-61`), which would defeat pyzmq's
  post-fork check, but the only multiprocessing user on the bus starts with
  `spawn` (`ai_trader/swarm.py:239`).

---

## 7. Decisions

| # | Question | Recommendation |
|---|---|---|
| Q1 | After WP-MSG01, pack `seq`, `eseq` and the envelope into one frame on PUB (`[topic, payload, "seq\|eseq\|msg\|cause\|chain"]`)? (a) Yes, in WP-MSG02. (b) No, keep five frames. | **(a).** It saves a further 2.7 µs per publish (8.2 → 5.5 µs), about 8 µs per order. The bus is internal, and only the engine reads a trailing frame by index (`engine/main.py:7546`, the PUSH envelope, which keeps its shape). Every other reader goes through the three `decode_*` helpers, which change in one place. pm-audit's log lines and `tools/replay_to_engine.py` use the helpers or `decode()` only. The wire tables have to be rewritten anyway (D8). (b) leaves a third of the remaining cost in place for no reader's benefit. |

---

## 8. Work packages

### WP-MSG01 — Stamping an envelope costs a third of what it does now, wire unchanged (P1)

**Tests first** (`tests/test_messaging_bus.py`, new; `tests/test_envelope_causation.py`):

1. 10 000 `new_ulid()` calls with the clock held in one millisecond call
   `os.urandom` once and encode the time prefix once (counted by patching
   `envelope.os.urandom` and the prefix encoder). (Fails today: the prefix is
   encoded on every call.)
2. `new_ulid()` output is byte-identical to the current encoder for a fixed
   `(ms, rand)` table including 0, 2⁸⁰−1 and 2⁴⁸−1 ms, and round-trips through
   `ulid_millis`, unchanged.
3. Ids stay strictly increasing within a millisecond and across a clock
   step backwards, unchanged.
4. `CausalPublisher.send_multipart` with a cause set, and `CausalPusher`, do
   not construct an `Envelope` (counted by patching `Envelope.__init__`).
   (Fails today.)
5. The frames a `make_publisher`-shaped stack sends to a recorder are
   unchanged: `decode_sequence`, `decode_publisher_sequence` and
   `decode_envelope` read the same seq, eseq, cause and chain as before,
   including in a unit and with `send_with_envelope`. Unchanged.

**Change.** In `models/envelope.py`, cache the time prefix per millisecond
and encode the randomness with a two-character table. Keep the lock and both
monotonicity rules. In `bus.py`, build the envelope frame from the cause's
strings: keep the cause as `(msg_id, correlation_id)` bytes or strings
internally, while `set_cause` still takes an `Envelope`.

**Exit criteria.** Tests 1–5 pass; the suites named in the delivery rule are
green. Target from the prototype, pinned to one core: `make_publisher` stack
≤ 8.5 µs per publish (11.7 today), and engine `order.new` median in the
§4 harness ≤ 95 µs (105 today). The engine figure is an estimate from 3 ×
3.4 µs.

### WP-MSG02 — A published message carries its sequences and envelope in one frame (P1, D3; after Q1, WP-MSG01)

**Tests first** (`tests/test_messaging_bus.py`, `tests/test_engine_command_echo.py`):

1. A message from the `make_publisher` stack has exactly three frames.
   (Fails today: five.)
2. `decode_sequence`, `decode_publisher_sequence` and `decode_envelope` read
   seq, eseq and the envelope from that frame, and return `None` on a
   two-frame message and on garbage. Partly fails today.
3. A PUSH message from `make_pusher` is unchanged: `[topic, payload,
   envelope]`, and `decode_envelope` reads it. Unchanged.
4. The engine's echo of a gateway command keeps the gateway's `msg_id`, and
   `seq`/`eseq` are read correctly from the echoed frame. Fails today on the
   frame count only.
5. pm-audit writes the same `[seq=… msg=… cause=… chain=…]` annotation as
   before for a published message and an echoed command (an existing audit
   test, run against the new layout), unchanged.

**Change.** Merge the stamping of `SequencedPublisher` and `CausalPublisher`
into one trailing frame `seq|eseq|msg_id|causation_id|correlation_id`.
`send_with_envelope` puts the received envelope's three fields behind the two
counters. Teach the three decode helpers the new layout, with PUSH keeping
its three-field frame. Drop the "found by shape" scan where the layout makes
the position fixed.

**Exit criteria.** Tests 1–5 pass; the suites named in the delivery rule, and
`tests/test_md_*`, `tests/test_audit_*` and `tests/test_sim_forensics_*`, are
green. Target from the prototype: stack ≤ 6 µs per publish, pinned.

### WP-MSG03 — A refusal record's `count` never drops refusals the gateway saw (C1, C2)

**Tests first** (`tests/test_gateway_reject_reporter.py`, `tests/test_api_gateway_rejects.py`):

1. The §3 C1 scenario (50 refusals from one host, 4096 other hosts, the first
   host again after the interval): the records' `count` values sum to 4147.
   (Fails today: 4098.)
2. The §3 C2 scenario (`send` raising `zmq.Again` for 10 s, then succeeding):
   the records' counts sum to 1001. (Fails today: 100.)
3. The table never exceeds 4096 entries under 100 000 distinct hosts.
   Unchanged (today's test at `:104`).
4. A record is still at most one per host and code per interval while sends
   succeed, unchanged.
5. pm-api-gwy: with the engine's PULL away, a refused request leaves the
   reporter's folded count for that peer intact. (Fails today: `EngineClient`
   swallows the failure.)

**Change.** In `RejectReporter.report`, write the new state only after a
successful send; on failure keep the old timestamp and add to the fold. On a
full table, drop entries that are past their interval and folded nothing;
send entries that folded something as their own record before dropping them.
In `api_gateway/main.py:158`, give the reporter a `send` that raises on
`zmq.Again`. This is the only line outside `messaging/`.

**Exit criteria.** Tests 1–5 pass; the reporter, ALF, BALF and REST gateway
suites are green. The operator guide's sentence at `020-audit-trail.md:416`
("The count of the last burst is lost if the peer then goes quiet") stays
true and is the only remaining loss.

### WP-MSG04 — Docstrings and the books describe the wire as it is (D1, D2, D4–D9; after WP-MSG02)

**Tests first.** Text only: none. Check with `poetry run mkdocs build` and
`make _check`.

**Change.** Rewrite D1, D2, D4, D5, D6 and D7 in place. Replace the five wire
tables of D8 with the final layout (after WP-MSG02: PUB `[topic, payload,
seq|eseq|envelope]`, PUSH `[topic, payload, envelope]`), naming `eseq` and
what reads it. Replace the "cost nothing" claims of D9 with the measured
per-publish cost after WP-MSG01/02. Regenerate the built books.

**Exit criteria.** Every passage in D1–D9 matches the code; `mkdocs build` is
clean; `grep -rn "frame\[3\]" docs/books` finds only the new tables.

---

## 9. Out of scope, noted

- **An unknown gateway id costs the engine memory for good.** Any client can
  send an ALF `HELLO` with a made-up gateway id. pm-alf-gwy forwards it
  (`alf_gwy/gateway.py:997-1004`), and `_handle_gateway_connect` creates a
  `ParticipantSession` (`engine/main.py:2786`, `_session_for_gateway` at
  `:1064-1071`) and a metrics label *before* the allowlist refuses it
  (`:2813`), then publishes on the new topic `system.gateway_auth.<id>`.
  Measured: 50 000 refused ids leave 50 000 sessions and 50 007 publisher
  topics, 337 B per refused id (16.8 MB). 136 B of each is
  `SequencedPublisher._seq`, and subscribers that keep per-topic sequence
  state grow the same way. The bus cannot drop a topic's counter without
  breaking gap detection, so the fix belongs at the source: the engine checks
  the allowlist before creating a session. `L031` in
  `EduMatcher-For-Later-ToDo.md`.
- **Log-server guide.** `operator-guide/part-6-observe-and-recover/040-log-server.md:276-279`
  says log-server messages are "the same two-frame envelope used everywhere
  else on the bus" and that ZeroMQ's prefix filter routes "in the kernel".
  The engine's bus carries three trailing frames, and ZMQ filters in libzmq
  (on the publisher side for TCP), not in the kernel. pm-log-srv builds its
  own sockets (`log_srv/pubsub.py:497-510`) and is not on this bus. A text fix
  for a log-server pass. Not a defect, so no `Lnnn`.
- **Raw sockets outside the factories.** pm-log-srv, `health/reporter.py`,
  `monitor/cli.py`, `ai_trader/worker.py:137`, pm-market-sim's own PUB/PULL
  and the commands client's SUB build sockets directly from the shared
  context. None of them pushes to the engine, so none loses an envelope.
  Listed so that a later "everything goes through `messaging/`" pass knows
  where they are.

# pm-ralf-gwy Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/ralf_gateway/` at `b8f1e5b4` (v0.79.0): `gateway.py`
(788 lines, the TCP loop, sessions, HELLO/SUB handling, the replay journal and
the engine-event mapping), `main.py` (190, the CLI), `config.py` (120),
`protocol.py` (66, line parsing and building) and `__init__.py` (6). The engine
payloads the gateway reads (`spec/messages/trade.yaml` `trade.executed`,
`spec/messages/system.yaml` `system.eod`), the engine's shutdown sequence that
publishes `system.eod` (`engine/main.py:7506-7517`), the trade id factory
(`models/trade.py:96-102`), `messaging/bus.py` `make_subscriber`, the
deployment path (`config_deploy.compile_config`) and the verifier checks that
name this gateway (`cverifier/layer3_semantic.py` M016, M033) were read where
they decide this gateway's behaviour, not reviewed as code of their own.
pm-md-gwy and pm-dc-gwy were read for comparison only: they share the loop
and close model (Line-Gateway Alignment, 2026-11-05).

**Focus:** correctness, edge-case handling, performance, and whether the
comments, help texts, the operator guide chapter
(`docs/books/operator-guide/part-5-gateways/040-ralf-gateway.md`) and the
protocol specification
(`docs/books/protocols-and-clients/part-2-specifications/040-ralf.md`) say
what the code does.

**Previous work:** the Line-Gateway Alignment workplan
(`docs-design/EduMatcher-Line-Gateway-Alignment-Workplan.md`, W1–W6, committed
`c271f626..26d983c5`): `ValueError` from `select` caught and `max_connections`
(F1), `REPLAY_MISS` when `LASTSEQ` is ahead of the stream or the journal aged
out (F3), the 4096-byte inbound line cap (F4), nothing answered after the line
that closed a session (F5), the 5 s HELLO deadline (F11), `TCP_NODELAY`, the
1000-event engine poll budget, the login log line and `UNSUB` validation
(F12), heartbeat/idle doc fixes (F13). Earlier: K16/K17 (event-loop fairness,
strict config coercion), the M033 verifier check (idle timeout more than twice
the heartbeat), CRITICAL for fatal messages. Their fixes are in place and are
not repeated here.

**Method:** every line of the files above was read. Findings marked *(repro)*
were reproduced with scratch scripts against the tree at `b8f1e5b4`: a real
`RalfGateway` thread on real TCP, fed by a real engine-side publisher
(`messaging.bus.make_publisher`, so every message carries the bus sequence
trailer the engine sends) with `trade.executed` payloads in the shape of
`spec/messages/trade.yaml`; clients are plain sockets speaking RALF lines.
*(measured)* means timed on this host with the same setup, or by calling the
gateway's handlers directly on a synthetic day of 10⁵ trades. The other
findings are by inspection, with line numbers given.

Status: **Done, uncommitted.** WP-RALF01–06 completed 2026-11-15 in order,
each test-first with a full-suite run. Decisions Q1–Q8 were taken as
recommended (the user asked for all WPs in one go); see §7.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (lines the client receives and their `SEQ`s, the
   gateway's health samples, its log records, exit status, config refusals).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_ralf_*.py` (gateway, unit,
   config, main, protocol, spy, examples) and the verifier tests with
   `-n logical`, then black/flake8/mypy/pyright. Do not start the next WP
   with a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Session tests use the `running_gateway` fixture of
`tests/test_ralf_gateway.py:134` (real gateway thread, real TCP, a PUB socket
the test binds). Two changes make it fit for these WPs: the PUB must be
`make_publisher` (sequenced, as the engine's is) so bus-gap tests see real
trailers, and payloads must follow `trade.yaml` (`id` as
`NNNNNN-NNNNNNNNN`, `run_seq`, `ts_ns`). The review's scratch `harness.py`
(about 80 lines: gateway restart on the same port, a line client with
`lines(quiet)`) can be folded into the fixture.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-RALF01 | A checkpoint from another gateway run is never replayed as this run's | H1 | Q1 | 0.75 d | ☑ | 2026-11-15 |
| 2 | WP-RALF02 | Engine bursts are not lost, and a loss is counted | H2, P1 | Q4 | 0.5 d | ☑ | 2026-11-15 |
| 3 | WP-RALF03 | A resuming client receives every event from its checkpoint to live | C1, C2 | Q2, Q3 | 1 d | ☑ | 2026-11-15 |
| 4 | WP-RALF04 | The loop serves every descriptor and a stop says goodbye | C5, C7, C8 | Q7, Q8 | 0.5 d | ☑ | 2026-11-15 |
| 5 | WP-RALF05 | The config refuses what the gateway cannot serve | C6 | — | 0.25 d | ☑ | 2026-11-15 |
| 6 | WP-RALF06 | Comments, help texts, guide and spec say what the code does | C3, C4, P2, D1–D14 | Q5, Q6, WP-RALF01–05 | 0.75 d | ☑ | 2026-11-15 |

Suggested order: **WP-RALF01 → WP-RALF02 → WP-RALF03 → WP-RALF04 →
WP-RALF05 → WP-RALF06**. WP-RALF01 and WP-RALF02 close the two paths where a
clearing consumer silently misses trades and cannot tell. WP-RALF03 changes
when replay happens; it goes after WP-RALF01 because both rewrite
`_handle_hello`/`_replay_from` and the EPOCH check must guard the moved
replay. WP-RALF04 and WP-RALF05 are hardening. WP-RALF06 goes last so every
text describes the code as it ends up.

Estimated sequential effort: about 3.75 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The **framing and session edges** are sound since the alignment work: a
4096-byte line cap, a 5 s HELLO deadline, nothing answered after the line
that ends a session, and every gateway-initiated close sends a final line
and drains for at most 5 s. **Entitlements** follow the spec's matrix on
`SUB` and on replay. The **EXEC projection** reads the keys the engine
actually sends (`id`, `buy_gateway_id`, `ts_ns`, …), unlike pm-balf-gwy
before its review: `TS` is the match time, not receipt time *(repro)*.
`REPLAY_MISS` is sent when `LASTSEQ` is ahead of the stream or older than the
journal.

The defects are in four places:

- **Replay that serves the wrong events (H1, C1).** Sequences restart at 1
  when the gateway restarts, and nothing on the wire names the run. Once the
  new run passes the client's `LASTSEQ`, a reconnect replays only the events
  above it: 50 of the new run's 80 trades are never sent, with no error. And
  replay runs at `HELLO`, before any subscription: a client that waits for
  `WELCOME` before it sends `SUB` (as the guide's own example does) loses
  every trade in between, and the `SNAP` that follows covers the hole.
- **Engine messages lost and hidden (H2).** The engine subscriber keeps
  ZeroMQ's default 1000-message high-water mark and no bus-sequence check.
  A 20 000-trade burst with ten AUDIT clients lost 14 000 trades. The
  gateway numbers lines after the loss, so every channel's `SEQ` stays
  dense: no client can see it, and nothing is logged or counted.
- **Recovery that cannot finish (C2).** A replay queues the whole backlog at
  once, and the slow-client check counts it as backlog: a client more than
  about 10 000 lines plus its socket buffers behind is disconnected with
  `SLOW_CLIENT`, and an identical reconnect fails identically for ever.
- **Numbers whose meaning is not what the texts say (C3, C4).** `EOD` is sent
  when the *engine stops* (mid-session included), and `TRADE_COUNT` counts
  what this gateway process saw since it started or since the last stop. The
  guide's gap check reports false gaps on every symbol-filtered
  subscription, because `SEQ` is per channel.

Severity key: **High**: an executed trade is not delivered to a subscribed
client and neither the client nor the operator is told. **Med**: a lost,
wrong or misleading line or figure; a recovery or session that cannot
succeed. **Low**: hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| H1 | High | Replay | After a gateway restart, a `LASTSEQ` from the old run replays the new run's events above it as the continuation: 50 of 80 trades never sent, no `REPLAY_MISS` *(repro)* | RALF01 |
| H2 | High | Engine feed | Default RCVHWM, no bus-sequence check: 14 000 of a 20 000-trade burst lost; RALF `SEQ` stays dense, nothing counted or logged *(repro)* | RALF02 |
| C1 | Med | Replay | Replay runs at `HELLO`; trades between `WELCOME` and `SUB` are never sent, and the `SNAP` covers the gap *(repro)* | RALF03 |
| C2 | Med | Replay | A replay larger than `max_client_queue` plus the socket buffers ends in `SLOW_CLIENT`, and every retry fails the same way *(repro)* | RALF03 |
| C3 | Med | EOD | `EOD` is sent at engine stop, not end of day; `TRADE_COUNT` counts what this gateway process saw; `TS` is receipt time | RALF06 |
| C4 | Low | Sequencing | With a `SYM` filter, `SEQ` jumps on every other symbol's trade: the guide's gap check reports 2 gaps for 0 lost lines *(repro)* | RALF06 |
| C5 | Low | Loop | Once a descriptor reaches 1024, `select` fails every pass: no client is read again, WARNING about 100 times a second *(repro)* | RALF04 |
| C6 | Low | Config | `name: "ralf\|01"` deploys cleanly and kills the gateway at the first `HELLO`; `allowed_roles` accepts roles with no channel *(repro)* | RALF05 |
| C7 | Low | Shutdown | A stop closes every session without a line: no `EXIT`, queued lines dropped *(repro)* | RALF04 |
| C8 | Low | Sessions | A client that half-closes after its `SUB` (`printf … \| nc`) is disconnected as `peer_closed` before any event *(repro)* | RALF04 |
| P1 | Low | Latency | Fixed 10 ms sleep per pass: publish → `EXEC` median 7.4 ms; with the 1000-event budget the loop caps throughput below the burst rate of H2 *(measured)* | RALF02 |
| P2 | Low | Memory | The journal costs 129 MB per 10⁵ trades and grows all day; a 10-line replay scans it all (18.6 ms on 300 000 lines) *(measured)* | RALF06 |
| D1–D14 | — | Texts | See §5 | RALF06 |

---

## 3. Correctness findings

### H1. A checkpoint from another gateway run replays the wrong events *(repro)* — High

`gateway.py:105` starts every channel's sequence at 1 when the process
starts; the journal (`gateway.py:106`) lives in memory. `WELCOME`
(`gateway.py:424-434`) names the gateway (`GW=`) but not the run, and `HELLO`
carries only `LASTSEQ`. `_replay_from` (`gateway.py:530-533`) refuses
`LASTSEQ` only when it is *ahead* of the channel or older than the journal:

```python
def missed(ch: str) -> bool:
    latest = self._next_seq_by_channel.get(ch, 1) - 1
    oldest = oldest_by_channel.get(ch, latest + 1)
    return last_seq > latest or last_seq < oldest - 1
```

Once the restarted gateway has passed the client's checkpoint, the old
run's `LASTSEQ` looks like a position in the new run. Repro (one CLEARING
client, real gateway restarted on the same port):

| Step | Gateway | Client |
|---|---|---|
| Run 1: 50 trades | CLEARING SEQ 1–50 | checkpoint `LASTSEQ=50` |
| pm-ralf-gwy restarts, 80 trades (other symbol) | CLEARING SEQ 1–80 | — |
| `HELLO … LASTSEQ=50`, `SUB` | `WELCOME`, then `EXEC` SEQ 51–80 | 30 `EXEC`, no `ERR` |

The client receives SEQ 51–80 as the continuation of what it had and never
sees the new run's trades 1–50. Its `SEQ` stream is dense, so its gap check
is silent. The spec (§8) and the guide promise `REPLAY_MISS` "after a gateway
restart", which holds only while the new run is still *behind* the
checkpoint. pm-md-gwy had the same defect and fixed it with a run identity
(`md_gateway/gateway.py:153-158`: `WELCOME|EPOCH=`, `RESUME` requires
`EPOCH`).

**Fix.** See Q1: an `EPOCH` in `WELCOME`, required beside a non-zero
`LASTSEQ` in `HELLO`; a different epoch is `REPLAY_MISS` plus `SNAP`.

### H2. Engine messages are dropped at the subscriber and nobody can tell *(repro)* — High

`gateway.py:116-120` creates the engine subscriber without `rcvhwm`, so it
has ZeroMQ's default of 1000 messages; past it a SUB socket drops silently
(`messaging/bus.py:373-376`). pm-md-gwy, pm-alf-gwy, pm-balf-gwy,
pm-clearing, pm-stats and pm-audit all pass `rcvhwm=100_000`.
`_poll_engine_events` (`gateway.py:563-581`) decodes with `decode()` and
never looks at the bus sequence trailer, so a drop is not counted either.

Repro: ten AUDIT clients subscribed to all three channels, the engine side
publishing pre-encoded `trade.executed` messages as fast as it can:

| Burst | Rate | EXEC emitted per channel | Lost | Logged / counted |
|---|---|---|---|---|
| 5 000 trades | 12 900/s | 5 000 | 0 | — |
| 20 000 trades | 31 600/s | 6 000 | **14 000** | nothing |

The gateway assigns `SEQ` *after* the loss (`_emit_event`,
`gateway.py:647-649`), so every channel stays dense: a client's gap check
passes, `TRADE_COUNT` at the next `EOD` agrees with the lines it received,
and the health beacon (`gateway.py:167-178`) has no figure for it. For a
feed whose purpose is clearing and audit this is the worst failure: trades
are missing and every check the client can make says nothing is.

The loop's own pace makes the overflow easier (P1): a pass handles at most
1000 events and then sleeps 10 ms.

**Fix.** See Q4: the md-gwy model, a 100 000-message RCVHWM and a
per-topic bus-sequence check that counts missed messages in the health
beacon and logs a latched WARNING.

### C1. Trades between `WELCOME` and `SUB` are lost on a resume *(repro)* — Med

`_handle_hello` replays at once (`gateway.py:443-444`). Live events go only to
sessions whose subscriptions want them (`_emit_event`, `gateway.py:663-667`),
and a session has none until its `SUB`. The `SNAP` after the `SUB` carries the
channel's latest `SEQ` (`gateway.py:486-495`). A client that sends `HELLO`,
reads `WELCOME` and only then sends `SUB` (the guide's annotated subscriber,
guide lines 533-544, does exactly that) misses every event emitted in
between. Repro, CLEARING client, `LASTSEQ=6` with SEQ 1–11 in the journal:

```text
WELCOME|PROTO=RALF1|GW=ralf-test|ROLE=CLEARING|REPLAY=86400|HBINT=60
EXEC … SEQ=7 … SEQ=11          (replay)
   3 trades happen here          (SEQ 12–14)
SNAP|CH=CLEARING|SYM=*|SEQ=14
EXEC … SEQ=15, SEQ=16           (live)
EXEC SEQs received: [7, 8, 9, 10, 11, 15, 16]
```

The spec tells the client the `SNAP` is its baseline, so a client that
follows it silently loses SEQ 12–14. The window is as long as the client's
round trip plus its processing of the replay; a replay of thousands of lines
makes it seconds.

A second effect of the same ordering is the spec's "known deviation"
(§8): replay is not subscription-filtered, so a DROP_COPY client
subscribed to one symbol is replayed every symbol, and an AUDIT client is
replayed all three channels.

**Fix.** See Q2: replay on `SUB`, for the pairs that `SUB` adds, followed by
its `SNAP`, in the same pass.

### C2. A long replay always ends in `SLOW_CLIENT` *(repro)* — Med

`_replay_from` queues every journal line above `LASTSEQ` in one call
(`gateway.py:553-557`). The next `_flush_client_writes` sends what the
socket takes and then applies the slow-client check to what is left
(`gateway.py:322-334`): more than `max_client_queue` (default 10 000) lines →
backlog dropped, `ERR|CODE=SLOW_CLIENT`, disconnect.

Repro: 30 000 trades in the journal, a CLEARING client resuming from
`LASTSEQ=1`. On loopback with the host's large autotuned buffers the replay
fits (30 000 and 100 000 lines both delivered). A client with a 256 KiB
receive buffer that takes 50 ms to start reading (a WAN link, a client
busy with the `WELCOME`):

| Attempt | EXEC received | Last line |
|---|---|---|
| 1 | 13 370 / 30 000 | `ERR\|CODE=SLOW_CLIENT\|DETAIL=queue overflow` |
| 2 (same `LASTSEQ`) | 13 370 / 30 000 | `ERR\|CODE=SLOW_CLIENT\|DETAIL=queue overflow` |

The second attempt is the first one again: the client cannot make progress,
because its checkpoint did not move past lines it never processed. The
guide's advice for `SLOW_CLIENT` is "Reconnect and process faster", which
cannot help. An AUDIT client is replayed three lines per trade, so it hits
the limit at a third of the backlog. At sim scale (10⁵ trades a day) a
clearing client that was down for an hour or two cannot recover over RALF.

**Fix.** See Q3: replayed lines do not count towards the slow-client limit.

### C3. `EOD` is the engine's stop, counted by this gateway process — Med

`_handle_eod` (`gateway.py:614-637`) emits one `EOD` per symbol in
`system.eod.books` with `TRADE_COUNT = EXEC_COUNT = self._trade_counts[symbol]`
and clears the counts. Three things differ from what the texts say ("end-of-day
per-symbol summary", "trades executed for the symbol since the previous
`EOD`", spec lines 150-158):

- The engine publishes `system.eod` in its shutdown sequence
  (`engine/main.py:7506-7517`), "whenever it stops, mid-session included"
  (operator guide, market index chapter, line 298). An engine restart at
  noon produces an `EOD` at noon, and the evening `EOD` counts only the
  afternoon. A killed engine sends none, so the next `EOD` counts two days.
- `_trade_counts` (`gateway.py:122`) is process memory. After a pm-ralf-gwy
  restart the count starts at zero: the evening `EOD` says 3 for a symbol
  that traded 8 times. Trades lost as in H2 are not counted either.
- `TS` is the gateway's clock when the message arrived (`gateway.py:630`);
  the payload carries no time. Every `EOD` of one stop has a slightly
  different `TS`.

A reconciliation that compares `TRADE_COUNT` with the day's trades will see
breaks that are not breaks, and will not see the losses of H2 (the count is
of the same lines the client received).

**Fix.** See Q5.

### C4. Gap detection fails on symbol-filtered subscriptions *(repro)* — Low

`SEQ` is one counter per channel across every symbol (`gateway.py:647-649`;
spec §8). A client subscribed to one symbol sees a jump whenever another
symbol trades. The guide's gap rule ("gap detected when received_seq !=
last_seq + 1", lines 375-383) and the example subscriber
(`docs/examples/ralf/ralf_subscriber.py:86-128`) apply it per channel.
Repro: DROP_COPY client with `SYM=AAPL`, trades AAPL, MSFT, AAPL, MSFT,
AAPL:

```text
AAPL-only DROP_COPY SEQs: [202, 204, 206] -> guide's check reports 2 gaps for 0 lost lines
```

The guide's own DROP_COPY example uses `SYM=AAPL`. Gap detection is only
meaningful with `SYM=*`, which the texts do not say.

**Fix.** See Q6.

### C5. A descriptor at 1024 or above stops every client being read *(repro)* — Low

`_read_client_data` (`gateway.py:232-237`) passes every session to
`select.select`, which raises `ValueError` for a descriptor of 1024 or more.
Alignment F1 caught the exception so the loop survives, but the pass then
returns without reading any client, every pass. Repro with 1100 descriptors
already open in the process: a new client's `HELLO` is never answered, and
the log shows `WARNING read select failed: filedescriptor out of range in
select()` 98 times in one second. Every other client stops being read too
(their `PING`, `SUB`, `EXIT`), and none is disconnected. With the default
`max_connections: 64` this needs a host process with many other descriptors
open; a raised `max_connections` reaches it directly.

**Fix.** `select.poll` (or `selectors`), which has no descriptor limit.

### C6. The config accepts values the gateway cannot serve *(repro)* — Low

`config.py:41` takes `name` as any string; `protocol.build_line` refuses `|`
in a value (`protocol.py:63-64`) and `WELCOME` carries `GW=<name>`
(`gateway.py:424-434`). `pm-config-deploy --check` accepts `name:
"ralf|01"`; the gateway then starts, and the first `HELLO` raises
`RalfProtocolError` out of `_handle_hello` through the run loop: the process
ends with a traceback and the port is closed (repro). `build_line` does not
check `\n` at all, so a name containing a newline (`"a\nb"` in YAML) splits
`WELCOME` into two lines on the wire.

`allowed_roles` (`config.py:56-59`) accepts any string. A role outside
`CLEARING`, `DROP_COPY`, `AUDIT` authenticates and then gets
`ENTITLEMENT_DENIED` on every `SUB`, because `_entitled_channels`
(`gateway.py:669-674`) knows only the three; an empty list makes every
`HELLO` fail.

**Fix.** Refuse in the loader (and so at deploy): a `name` that is empty or
contains `|`, `\n` or `\r`; `allowed_roles` values outside the three
channels, or an empty list. `build_line` also refuses `\n`/`\r` in a value.

### C7. A stop closes every session without a word *(repro)* — Low

`close()` (`gateway.py:180-194`) closes each client socket. Lines still
queued are dropped and no `EXIT` is sent, although the spec lists `EXIT` as
the gateway's termination signal (§6) and every other gateway-initiated
close sends one. Repro: a subscribed client reads nothing at all when the
gateway stops; it sees only EOF and cannot tell a planned stop from a crash
or network failure. pm-md-gwy and pm-dc-gwy behave the same (§9).

**Fix.** See Q7.

### C8. A client that half-closes is disconnected *(repro)* — Low

`recv` returning `b""` disconnects at once as `peer_closed`
(`gateway.py:253-255`). A read-only client that half-closes its write side
after its last line, which is what `printf 'HELLO…\nSUB…\n' | nc host 5580`
does, receives `WELCOME` and `SNAP` and is then dropped before any event
(repro). RALF is a read-only protocol, so this is a natural way to script it;
the spec says nothing either way. pm-md-gwy and pm-dc-gwy do the same.

**Fix.** See Q8.

---

## 4. Performance findings

At today's sizes only P1 matters, and only through H2: per-trade cost is not
the bottleneck, the loop's pacing is.

### P1. A fixed 10 ms sleep per pass *(measured)* — Low

`run()` (`gateway.py:145-155`) sleeps 10 ms after every pass, whatever
happened, and `_poll_engine_events` handles at most 1000 events per pass
(`gateway.py:36`).

| Measure | Value |
|---|---|
| Engine publish → client `EXEC`, median / p99 | 7.4 ms / 7.7 ms |
| `_handle_trade`, 0 / 1 / 10 / 64 AUDIT sessions | 20.8 / 18.4 / 25.2 / 63.1 µs per trade |
| Sustained cap with 10 AUDIT sessions (1000 × 25 µs + 10 ms per pass) | about 28 000 trades/s (derived) |

The latency is acceptable for a post-trade feed. The cap is what lets a
burst fill the subscriber (H2): the loop sleeps even when the budget ran out
with events still queued.

**Fix.** Do not sleep after a pass that exhausted the engine budget (with
H2's larger RCVHWM, a burst is then drained at the handlers' own speed).

### P2. The journal grows all day and every replay scans it *(measured)* — Low

Every line is journalled (`gateway.py:661`) and pruned only by age
(`gateway.py:726-729`, default 86 400 s). Synthetic day of 10⁵ trades:

| Measure | Value |
|---|---|
| Journal after 10⁵ trades | 300 000 lines, 129 MB (tracemalloc) |
| `_replay_from`, CLEARING, 10-line replay | 18.6 ms |
| `_replay_from`, CLEARING, full replay | 34.4 ms |

The memory grows with the day and resets only as lines age out. The replay
cost is a scan of the whole journal twice (`gateway.py:520-525`,
`553-557`), whatever the size of the replay, and it blocks the loop for that
long. Both are tolerable at sim scale. The guide says "Tune
`replay_retention_sec` for your memory budget" (line 637-638) without a
figure.

**Fix.** No code change: put the measured cost (about 1.3 KB per trade) in
the guide's operational notes. Revisit if WP-RALF03's per-`SUB` replay
makes the scan frequent.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | spec line 82; guide lines 355, 435, 681 | `HB` is described as sent "when the stream is quiet/idle"; it is sent every interval to every authenticated client (`gateway.py:694-702`), as spec §9 (line 221) already says. |
| D2 | guide line 308 | "`CLIENT` is a free-text identifier (max 32 chars)": the gateway applies no limit (`gateway.py:383-387`). |
| D3 | guide lines 258-262 | The channel summary lists `DROP_COPY` as `EXEC` only; `EOD` is emitted on all three channels (`gateway.py:624`), as spec line 160 says. |
| D4 | spec line 143 | `SIDE` "aggressor side (`BUY`/`SELL`)": an uncross print carries `AUCTION` (`trade.yaml` `aggressor_side`), passed through unchanged (`gateway.py:606`). |
| D5 | spec lines 150-158; guide lines 199, 434 | `EOD` "at end of day", "trades executed since the previous `EOD`": see C3 for what it is. |
| D6 | guide lines 85-86 | "By default it reads `engine_config.yaml`": it reads the deployed compiled configuration (`config.py:106-120`, `main.py:128`). |
| D7 | `main.py:40`; guide line 130; `pm_help/registry.py` | `--engine-pub` "default: value from config, then tcp://127.0.0.1:5556": no config key exists (`config.py:78-80`); the default is `ENGINE_PUB_ADDR`, `tcp://$EDUMATCHER_ENGINE_HOST:5556` (`config.py:90`). |
| D8 | `main.py:58` | `-q` "Reduce log output to warnings/errors": WARNING is already the default (the L034 pattern; pm-mm-bot's was reworded in WP-MMB08). |
| D9 | `config.py:61-62` | A second `port <= 0` check after `config.py:44-45` has already refused it: dead code. |
| D10 | guide lines 375-383, 546-562 | The gap rule and the annotated subscriber apply per-channel gap detection to symbol-filtered subscriptions (C4). |
| D11 | guide lines 403-405 | "making intraday reconnects lossless in normal operation" is false today (H1, H2, C1, C2); reword after the fixes to what then holds. |
| D12 | spec lines 24-26 | "tracked in the project's suspected-bugs report": no such report exists. |
| D13 | spec and guide wire examples | Examples put `SEQ` after `SYM`; the gateway appends it last (`gateway.py:651-653`). Spec §4 should say field order is not significant. |
| D14 | `cverifier/layer3_semantic.py:930-949` (M016); operator guide `020-config-verifier.md:547` | Warns that without an ADMIN gateway "RALF admin commands (replay, etc.) will be unavailable". pm-ralf-gwy has no admin commands and uses no gateway id. |

---

## 6. Verified as correct

- **EXEC projection.** Every key read in `_handle_trade`
  (`gateway.py:583-612`) exists in `trade.yaml` `trade_executed`; `TS` is the
  match time from `ts_ns`, not the gateway's clock; `PX` is the display
  float formatted by `str()`, which round-trips the engine's
  `price_ticks / 10**tick_decimals` value exactly.
- **Entitlements.** `SUB` checks every requested channel before adding any
  pair (`gateway.py:463-480`); replay sends only entitled channels
  (`gateway.py:516-518`, `553-555`).
- **Replay boundaries.** `LASTSEQ` equal to the latest replays nothing with
  no error; ahead of the stream or older than the journal gives
  `REPLAY_MISS` + `SNAP` (alignment W5), including an empty journal.
- **Idle versus heartbeat.** An `idle_timeout_sec` at or below the heartbeat
  interval drops reading clients (repro: idle 1 s, HB 3 s → `EXIT|REASON=idle_timeout`),
  but such a config cannot be deployed: M033 (`layer3_semantic.py:1355-1408`)
  is an ERROR, and `pm-config-deploy` refuses blocking findings
  (`config_deploy.py:191`).
- **Close model.** Every gateway-initiated close queues its final line and
  disconnects after the flush or `CLOSE_GRACE_SEC`; `_drop_backlog` keeps a
  partly-sent line, so the wire never carries a torn line before
  `SLOW_CLIENT` (`gateway.py:780-788`).
- **Per-trade cost** is not a limit at sim scale (P1 table).
- **Prefix subscriptions.** `trade.executed` and `system.eod` match no other
  engine topic.

---

## 7. Decisions

| # | Question | Recommendation |
|---|---|---|
| Q1 | How does a client name the run its `LASTSEQ` came from (H1)? (a) `WELCOME` carries `EPOCH=<random hex per run>`; `HELLO` with `LASTSEQ>0` must carry `EPOCH`, else `BAD_MESSAGE`; a different epoch is `REPLAY_MISS` + `SNAP`. (b) `EPOCH` optional; without it, today's behaviour. (c) Persist the journal and counters across restarts. | **(a)**, the rule pm-md-gwy already has for `RESUME`, so the line gateways agree. (b) keeps the silent wrong replay for every client that does not upgrade. (c) is a durable store for a 1.x feature; it still needs an identity after a data reset. pm-ralf-spy `--lastseq` gains `--epoch`, and the Python and C examples store and send it. |
| Q2 | When does replay happen (C1)? (a) On `SUB`: `HELLO` records `LASTSEQ`; each `SUB` replays the journal lines above it that the new pairs want and the old pairs did not, then sends its `SNAP`, in one pass. (b) Keep replay at `HELLO` and give the session every entitled live event until its first `SUB`. (c) Keep replay at `HELLO`; on `SUB`, fill from the journal between the replay's end and now. | **(a)**. It closes the gap and removes the spec's "known deviation" (replay becomes subscription-filtered). (b) sends unsubscribed channels and symbols to clients that never asked. (c) fixes the gap but keeps the unfiltered replay and adds a second replay path. A `HELLO` with `LASTSEQ` and no `SUB` then receives nothing beyond `WELCOME`, which is consistent: nothing was subscribed. `REPLAY_MISS` moves to the `SUB` reply. |
| Q3 | How is a long replay delivered (C2)? (a) Replayed lines do not count against `max_client_queue`: the limit applies to what is queued beyond the replay. (b) Paced replay: a per-session journal cursor, refilled as the queue drains, live lines held until it catches up. (c) Cap replay size, `REPLAY_MISS` beyond. | **(a)**. Queued lines are references to the journal's bytes, so a full-day AUDIT replay costs about 2.4 MB of references per session, not a copy; a client that stops reading is still dropped by the idle timeout. (b) is the better design for very large journals but is a rewrite of the queue. (c) turns a recoverable outage into data loss. |
| Q4 | What happens when engine messages are lost (H2)? (a) RCVHWM 100 000 and the md-gwy bus-sequence check: missed messages counted per topic family in the beacon (`gwy.bus_gaps`), a latched WARNING, engine restarts recognised. (b) (a) plus a wire signal to clients (for example `ERR|CODE=FEED_GAP` on each channel). | **(a)**. With the larger mark the repro's burst is absorbed, and any remaining loss is visible to the operator. (b) is a protocol addition clients would have to handle; record it as For-Later if wanted. |
| Q5 | What does `EOD` mean (C3)? (a) Document it as it is: sent when the engine stops; `TRADE_COUNT` is the number of trades this gateway run disseminated for the symbol since it started or since the previous `EOD`; `TS` is when the gateway received it. (b) (a) plus a `SINCE=<TS>` field giving the start of the counting window. (c) Drop `TRADE_COUNT`/`EXEC_COUNT`. | **(a)**. It makes the figure honest without a wire change. (b) helps a consumer see a partial window and can follow if a consumer needs it. (c) breaks clients that read the fields. |
| Q6 | Gap detection with symbol filters (C4)? (a) Document that `SEQ` gaps are meaningful only for `SYM=*` subscriptions; fix the guide and the example to check gaps only then. (b) Add a per-(channel, symbol) sequence. | **(a)**. (b) is a protocol change for one use case; a filtered consumer can resume by `LASTSEQ` on the channel sequence as today. |
| Q7 | Should a stop say goodbye (C7)? (a) On stop, queue `EXIT|REASON=shutdown|TS=…` to every session and flush for at most a short bound (1 s) before closing. (b) Leave as is. | **(a)**, matching the close model used for every other gateway-initiated close. pm-md-gwy and pm-dc-gwy get the same in a For-Later item (L036) so the three stay alike. |
| Q8 | Half-closed clients (C8)? (a) Document that a half-close ends the session (as in pm-md-gwy and pm-dc-gwy). (b) Keep a half-closed session open until a send fails or it idles out. | **(a)**, for alignment with the other line gateways; (b) also needs send errors to disconnect, which they do not today (`gateway.py:313-314`). |

**Taken (2026-11-15):** Q1–Q8 all (a), the recommendations, as the user asked
for all WPs to be completed in one go.

---

## 8. Work packages

### WP-RALF01 — A checkpoint from another gateway run is never replayed as this run's (H1; after Q1)

**Tests first** (`tests/test_ralf_gateway.py`, `tests/test_ralf_spy.py`):

1. `WELCOME` carries `EPOCH=<hex>`, the same for every session of one run
   and different after a restart. (Fails today.)
2. Restart scenario of H1 (old run to SEQ 50, new run to 80, `HELLO
   LASTSEQ=50 EPOCH=<old>`): `ERR|CODE=REPLAY_MISS` then `SNAP` at the new
   run's latest, no `EXEC` from the journal. (Fails today.)
3. `HELLO … LASTSEQ=50` without `EPOCH` → `ERR|CODE=BAD_MESSAGE` and close.
   (Fails today.)
4. Same epoch, `LASTSEQ` inside the journal: replay as today, unchanged.
5. `LASTSEQ=0` or absent needs no `EPOCH`, unchanged.
6. pm-ralf-spy `--lastseq N --epoch E` sends both; `--lastseq` without
   `--epoch` is a usage error. (Fails today.)

**Change.** `self._epoch = secrets.token_hex(4)` in `__init__`, `EPOCH` in
`WELCOME`, the epoch rule in `_handle_hello` before `_replay_from`. pm-ralf-spy
option, `docs/examples/ralf` (Python and C) store and send the epoch. Spec
§6/§8/§10 and guide "Gap detection and replay" in this WP, since the wire
changes.

**Exit criteria.** Tests 1–6 pass; `tests/test_ralf_*.py` and
`tests/test_ralf_examples.py` green.

**Outcome (2026-11-15).** `RalfGateway._epoch = secrets.token_hex(4)`, sent
as `WELCOME|EPOCH=` (after `GW`). `_handle_hello` refuses `LASTSEQ` above 0
without `EPOCH` (`ERR|CODE=BAD_MESSAGE|DETAIL=LASTSEQ requires EPOCH`, then
close, as for a non-integer `LASTSEQ`); a different epoch is a replay miss
(`ERR|CODE=REPLAY_MISS` + `SNAP`) whatever the `LASTSEQ`. pm-ralf-spy gains
`--epoch` (a non-zero `--lastseq` without it is a usage error, exit 2) and
`RalfSpyOptions.epoch`, sent beside `LASTSEQ`. The Python example gains
`--epoch` and a `hello_fields()` helper; the C example never resumes (it
always sends `LASTSEQ=0`), so it needed no change. Docs: spec §6 (`HELLO`
`EPOCH`, `WELCOME` `EPOCH`), §8 (a checkpoint is the pair), §10; the guide's
sequence diagram, Step 1, "Gap detection and replay", the examples, both
error tables and the runbook; the spy chapter's options; pm-help;
`make completion`.

Tests: `tests/test_ralf_gateway.py` gained the review harness (the engine's
`make_publisher`, `trade.yaml`-shaped payloads, a gateway restartable on one
port, a threaded line client); 1 one epoch per run, new after a restart
(failed first: `KeyError: 'EPOCH'`); 2 the H1 restart scenario (failed
first: same); 3 `LASTSEQ` without `EPOCH` (failed first: no EOF, the session
stayed open); 5 `LASTSEQ` absent or 0 (unchanged, passed). 4 is the existing
`test_replay_from_lastseq`, which now sends the `EPOCH` of its first
session. 6 in `tests/test_ralf_spy.py` (parser, usage error, and the HELLO
fields; the usage-error test failed first with exit 1 from a refused
connect) and `tests/test_ralf_examples.py` (`hello_fields`). Full suite:
14 581 passed, 1 skipped.

### WP-RALF02 — Engine bursts are not lost, and a loss is counted (H2, P1; after Q4)

**Tests first** (`tests/test_ralf_gateway.py`, `tests/test_ralf_gateway_unit.py`):

1. Burst of 20 000 sequenced `trade.executed` with ten AUDIT sessions (the H2
   repro): 20 000 `EXEC` per channel. (Fails today.)
2. A bus-sequence jump of 5 on `trade.executed` (feed frames with trailers
   `1|…`, `2|…`, `8|…`): the beacon reports `gwy.bus_gaps{trade}` = 5 and one
   WARNING is logged; a second jump within the latch window adds to the
   counter without another WARNING. (Fails today.)
3. A sequence that starts again at 1 (engine restart) is not a gap.
   (Fails today: no check exists, the test asserts the restart log line.)
4. A pass that exhausted the 1000-event budget does not sleep: with 3000
   queued events, the third batch is handled within one pass interval of
   the first. (Fails today.)

**Change.** `make_subscriber(..., rcvhwm=_SUB_RCVHWM)` with 100 000; port
md-gwy's bus-sequence tracking (`md_gateway/gateway.py:940-1012`) using
`decode_sequence`, and its `counter("…bus_gaps", …)` samples in
`metric_samples`; skip the sleep when the budget ran out.

**Exit criteria.** Tests 1–4 pass; `tests/test_ralf_*.py` and the monitor
tests that read `gwy.*` samples green.

**Outcome (2026-11-15).** The engine SUB is made with `rcvhwm=_SUB_RCVHWM`
(100 000). `_check_bus_sequence` is pm-md-gwy's, per engine topic (there are
only two, `trade.executed` and `system.eod`, so the topic is the label, not a
family): a jump adds to `gwy.bus_gaps{<topic>}` and logs one WARNING per
topic per 60 s with a running "lost since the last warning" figure; a
sequence at or below the last is an engine restart, logged at INFO and not
counted. `_poll_engine_events` returns whether the 1000-event budget ran
out, and `run()` skips the 10 ms sleep after such a pass (P1). A failed
`recv` still ends the pass; a decode error still skips one message.

Beyond the WP text, as for pm-dc-gwy's `gwy.feed_gaps`: pm-monitor watches
the counter (`WATCHED_INCREASES` `gwy.bus_gaps` → rule `ralf_bus_gaps`, any
increase in 5 min), mirrored in dash-gui's `FIXED_RULES` and the
health-monitor chapter's rule table; the WARNING has a log-ledger entry;
`tests/test_health_contract.py` lists the counter's owner.

Tests (`tests/test_ralf_gateway.py`, on the engine's sequenced publisher):
1 the H2 burst, 20 000 trades with ten AUDIT sessions (failed first: 17 499
per channel); 2 a jump of 5 then 2 counts 5 then 7 with one WARNING (failed
first: `{}`); 3 a sequence back to 1 is an INFO restart, no gap (failed
first: no INFO record); 4 with 2 500 events queued, the first sleep comes
after all 2 500 (failed first: after 1 000). Full suite: 14 585 passed,
1 skipped.

### WP-RALF03 — A resuming client receives every event from its checkpoint to live (C1, C2; after Q2, Q3)

**Tests first** (`tests/test_ralf_gateway.py`):

1. C1 repro: `HELLO LASTSEQ=6`, read `WELCOME`, 3 trades, `SUB`: the client
   receives SEQ 7–14 before the `SNAP` (SEQ 14), then 15–16. (Fails today.)
2. Replay is subscription-filtered: DROP_COPY `SYM=AAPL` resuming over a
   journal of AAPL and MSFT trades receives only AAPL lines. (Fails today.)
3. AUDIT client: `SUB CH=CLEARING` then `SUB CH=AUDIT` replays each
   channel once, with no duplicate lines for pairs already subscribed.
   (Fails today.)
4. `REPLAY_MISS` + `SNAP` is now the `SUB` reply for an aged-out or
   foreign-epoch checkpoint. (Fails today.)
5. C2 repro: 30 000 journalled trades, a client with a 256 KiB receive
   buffer that starts reading after 50 ms receives all 30 000 lines with no
   `SLOW_CLIENT`. (Fails today.)
6. A client that stops reading during a replay is still disconnected by
   the idle timeout, and live overflow past `max_client_queue` after the
   replay is still `SLOW_CLIENT`. Unchanged.
7. A fresh session without `LASTSEQ`: `SUB` → `SNAP` → live, unchanged.

**Change.** `HELLO` stores `last_seq` and the epoch result; `_handle_sub`
replays the newly wanted pairs above it (`_session_wants` before and after
the update), then queues the `SNAP`. A per-session replay allowance (lines
queued by the replay) is added to `max_client_queue` in the slow-client check
and released as the queue drains below the limit. Spec §8 loses its "known
deviation"; spec and guide describe the new order.

**Exit criteria.** Tests 1–7 pass; `tests/test_ralf_*.py` green; the full
replay of test 5 completes in under 2 s on this host (a guess, to be
measured).

**Outcome (2026-11-15).** `HELLO` now only records the checkpoint
(`ClientSession.last_seq_seen`, and `same_run` = its `EPOCH` is this run's);
`_handle_sub` notes the pairs it held before, adds the new ones, and, when the
session has a checkpoint, calls `_replay_for_sub` before queueing its `SNAP`,
all in one pass. `_replay_for_sub` (replacing `_replay_from`) checks the miss
conditions for the `SUB`'s channels only (foreign epoch, `LASTSEQ` ahead of a
channel or older than its journal) and answers `ERR|CODE=REPLAY_MISS`, the
`SNAP` following as the baseline; otherwise it queues, in journal order, the
lines after `LASTSEQ` that the new pairs want and the old did not, so replay
is subscription-filtered and each channel/symbol is replayed once. The
spec's "known deviation" and the unused `_entitled_channels` are gone;
matching moved to a module-level `_wants()`. A `SUB` after an `UNSUB` of the
same pair replays it again from `LASTSEQ` (duplicates, never a loss; a client
de-duplicates by `SEQ`).

C2: `ClientSession.replay_allowance` counts the replayed lines; the
slow-client check allows `max_client_queue + replay_allowance`, and after
every flush the allowance shrinks to the queue length, so it is released as
the replay drains and live overflow beyond it is still `SLOW_CLIENT`;
`_drop_backlog` resets it. A client that stops reading during a replay is
still dropped by the idle timeout (that path did not change).

Docs: spec §6 `SUB`, §8 (replay order, miss on `SUB`, allowance), §9, §12;
the guide's Step 3, recovery options and runbook; training exercise 6 (which
said replay arrives before `SUB`, and now needs `EPOCH`); the spy chapter,
`--lastseq` help, the spy client docstring and pm-help.

Tests (`tests/test_ralf_gateway.py`): 1 the C1 repro, SEQ 7–14 then
`SNAP` 14 then 15–16 (failed first: the `SNAP` came after 13 lines short); 2
DROP_COPY `SYM=AAPL` resumes only AAPL (failed first: MSFT lines too); 3
AUDIT `SUB CLEARING`, `SUB CLEARING,AUDIT`, `SUB CLEARING SYM=AAPL`: each
channel once, no DROP_COPY (failed first: DROP_COPY replayed at HELLO); 5 the
C2 repro, 30 000 lines to a 256 KiB reader 50 ms late, no `ERR` (failed
first: `SLOW_CLIENT`). In `tests/test_ralf_gateway_unit.py` the replay
tests that called `_replay_from` now go through `HELLO`+`SUB` (4: a miss is
the `SUB` reply, nothing after `HELLO`; failed first: `ERR`,`SNAP` came
after `HELLO`), plus 6 the allowance (20 replayed lines then 5 live is fine
with `max_client_queue=5`, the 6th live line is `SLOW_CLIENT`). 7 is the
existing fresh-session tests, unchanged. The existing
`test_replay_from_lastseq` now sends its `SUB`. Measured: the 30 000-line
replay completes in 0.36–0.49 s standalone (under 2 s); the first
`-n logical` run took 2.006 s because the test client re-parsed every line
on each poll, fixed in the harness. Full suite: 14 590 passed, 1 skipped.

### WP-RALF04 — The loop serves every descriptor and a stop says goodbye (C5, C7, C8; after Q7, Q8)

**Tests first** (`tests/test_ralf_gateway.py`, `tests/test_ralf_gateway_unit.py`):

1. With 1100 descriptors open in the test process, a new client's `HELLO`
   is answered with `WELCOME` and no `read select failed` WARNING is
   logged. (Fails today.)
2. On `stop()`, a subscribed client reads `EXIT|REASON=shutdown|TS=…` before
   EOF, and lines queued before the stop arrive ahead of it. (Fails today.)
3. A client that stopped reading does not hold the stop for more than the
   bound (1 s). (Fails today: there is no flush at all; the test pins the
   bound.)
4. Half-close (Q8 (a)): `printf`-style client gets `WELCOME`, `SNAP` and the
   disconnect reason `peer_closed`, unchanged; the behaviour is now
   documented.

**Change.** `select.poll` registration per session in `_read_client_data`;
`close()` queues `EXIT|REASON=shutdown` and flushes for at most 1 s before
closing; text for C8 in spec §3.

**Exit criteria.** Tests 1–4 pass; `tests/test_ralf_*.py` green; stop of a
gateway with 64 non-reading clients completes within 1.5 s (measured in
test 3).

**Outcome (2026-11-15).** pm-dc-gwy's WP-DCG03 code, ported:
`_read_client_data` builds a `select.poll` over the client descriptors each
pass and lets `recv` settle every event; the WARNING is now `read poll
failed: %s` (log-ledger entry renamed). On a normal stop `run()` calls
`_flush_for_shutdown()`: one more engine pass, `EXIT|REASON=shutdown|TS=…`
to every session not already closing, then a flush bounded by
`SHUTDOWN_FLUSH_SEC` = 1 s; sessions that drain are disconnected as
`shutdown`. `close()` disconnects the rest through `_disconnect` (counted,
reason `shutdown` or the reason a session was already closing with). Not
run after a crash. Half-close (Q8 a) is unchanged and now documented: spec
§3, the guide's Step 6. Docs also: spec §6 `EXIT` reasons, the guide's Step
6 (the stop's `EXIT`), the reference manual's "Messages published" row.

Tests (`tests/test_ralf_gateway.py`): 1 a client on a descriptor above 1023
gets `WELCOME` and `PONG`, no read WARNING (failed first: timeout, `read
select failed` logged every pass); 2 three queued `EXEC` then
`EXIT|REASON=shutdown` before EOF, `shutdown` counted (failed first: no
`EXIT`); 3 one AUDIT client with a 4 KiB receive buffer that reads nothing,
20 000 trades queued, stop under 1.5 s (failed first on the `shutdown`
count; the timing passed before too, close() was immediate); 4 half-close
is `peer_closed` after `WELCOME`, `SNAP` (unchanged, passed). The exit
criterion's "64 non-reading clients" was tested with one: the bound is one
deadline shared by all sessions, not per session. Full suite: 14 594
passed, 1 skipped.

pm-ralf-gwy and pm-dc-gwy now share this code; pm-md-gwy still has the
`select` loop and the silent stop (L036).

### WP-RALF05 — The config refuses what the gateway cannot serve (C6)

**Tests first** (`tests/test_ralf_config.py`, `tests/test_ralf_protocol.py`):

1. `name: "ralf|01"`, `name: "a\nb"`, `name: ""` → `ValueError` naming
   `post_trade_gateway.name`. (Fails today.)
2. `allowed_roles: [RISK]` and `allowed_roles: []` → `ValueError`.
   (Fails today.)
3. `build_line("X", {"K": "a\nb"})` raises `RalfProtocolError`. (Fails
   today.)
4. `pm-config-deploy --check` on a config with `name: "ralf|01"` exits
   non-zero. (Fails today.)
5. The defaults and every bundled example config still load, unchanged.

**Change.** Checks in `_load_ralf_gateway_config_from_raw`; `\n`/`\r` in
`build_line`. D9 (the dead second port check) goes in the same edit.

**Exit criteria.** Tests 1–5 pass; `tests/test_ralf_config.py`,
`tests/test_cverifier*.py`, `tests/test_config_deploy*.py` green.

**Outcome (2026-11-15).** `_load_ralf_gateway_config_from_raw` refuses an
empty `name` or one containing `|`, CR or LF
(`post_trade_gateway.name must be non-empty, without '|' or line breaks`, as
pm-dc-gwy's), and an `allowed_roles` list that is empty or names anything
but `CLEARING`, `DROP_COPY`, `AUDIT` (after upper-casing). `build_line`
refuses CR/LF in a key or value. The dead second `port <= 0` check is gone
(D9). pm-cverifier runs the same loader, so `pm-config-deploy` refuses both:
`tests/test_cverifier_deploy_agreement.py` gained a `post_trade_gateway`
block in its base config and two cases (`name: ralf|01`,
`allowed_roles: [RISK]`), which failed without the loader change ("the case
must be one the loaders refuse"); that test stands for WP test 4. Docs: the
formal specification's §6.4 constraints and the protocol spec's §11 table.

Tests: 4 refused names, 3 refused role lists, an ordinary name kept and
roles upper-cased in `tests/test_ralf_config.py`; 2 line breaks in
`tests/test_ralf_protocol.py` (every refusal failed first with DID NOT
RAISE). Test 5 (defaults and bundled configs load) is the existing suite.
Full suite: 14 607 passed, 1 skipped.

### WP-RALF06 — Comments, help texts, guide and spec say what the code does (C3, C4, P2, D1–D14; after Q5, Q6 and WP-RALF01–05)

**Tests first:**

1. `pm-ralf-gwy --help` shows the corrected `--engine-pub` and `-q` texts
   (`tests/test_ralf_main.py`). (Fails today.)
2. `pm-cverifier` on a config with `post_trade_gateway` and no ADMIN gateway
   reports no M016 (`tests/test_cverifier*.py`). (Fails today.)
3. The example subscriber reports no gap for the C4 repro sequence on a
   `SYM=AAPL` subscription and still reports one for a `SYM=*` gap
   (`tests/test_ralf_examples.py`). (Fails today.)

**Change.** D1–D14 as listed in §5; C3 and C4 texts as decided in Q5/Q6
(spec §6 `EOD`, §8; guide "What data is available", "Gap detection and
replay", the annotated subscriber); P2's memory figure in the guide's
operational notes; `make completion` for the help change; remove M016 and
its row in the verifier chapter. Re-walk every guide passage touched by
WP-RALF01–04 (lessons-learned §B1).

**Exit criteria.** Tests 1–3 pass; `make _check` and `mkdocs build` clean;
the full suite green.

**Outcome (2026-11-15).** D7/D8: `--engine-pub` help names the real default
(`tcp://$EDUMATCHER_ENGINE_HOST:5556`, 127.0.0.1 when unset, no config key)
and `-q` reads "Explicit WARNING log level (the default)", in `--help`, the
guide, the reference manual and pm-help; `make completion`. D14: M016 and
its check `_check_post_trade_admin` are removed, and its row in the verifier
chapter. C4/Q6 (a): the Python example's `ChannelSequenceTracker` takes the
`--symbols` value and checks gaps only for `*` (the C example always
subscribes `SYM=*`); spec §8, the guide's gap rule and annotated subscriber
say so. C3/Q5 (a): spec §6 `EOD` and a new guide section "What `EOD` means"
(sent when the engine stops; `TRADE_COUNT` counts this gateway run's lines;
`TS` is receipt time; reconcile from pm-clearing or REST). D1 (`HB` every
interval) in spec §5 and three guide places; D2 (no `CLIENT` limit); D3
(`DROP_COPY` carries `EOD`); D4 (`SIDE` may be `AUCTION`); D5 with C3; D6
(the deployed compiled config); D10 with C4; D11 (the "lossless" note now
says when replay is complete and when it is not); D12 (the
suspected-bugs sentence removed, as the spec has no deviations left); D13
(field order not significant, spec §4). P2: the measured journal cost
(about 1.3 KB per trade, 20–35 ms per replay scan at 10⁵ trades) and the
`gwy.bus_gaps` signal in the guide's operational notes. D9 was done in
WP-RALF05.

Re-walk (lessons-learned §B1): the guide's quick start, Steps 1–6, gap
detection and replay, quick-connect, annotated subscriber, bundled
examples, error tables and runbook; the spec end to end; the spy chapter;
training chapter 22 (`220-ralf.md`); the reference manual section; the
verifier and health-monitor chapters. **Follow-up found on the way:**
training exercise 4 said `UNSUB|CH=CLEARING|SYM=AAPL` after
`SUB|CH=CLEARING|SYM=*` stops AAPL; `_handle_unsub` removes exactly the
named pairs, so it does not. The code is consistent (UNSUB is the inverse of
SUB); the texts were wrong. A unit test pins the behaviour (passed as
written); the exercise now subscribes `AAPL,MSFT`, and the spec §6 and the
guide's Step 4 state the rule. Training's `EXIT` note gained `shutdown`.
L036 now names pm-ralf-gwy's code as the one to copy.

Tests: two in `tests/test_ralf_main.py` (both failed first on the old
texts); `tests/test_cverifier.py`'s M016 test inverted (failed first:
M016 present) and the bad-shape test no longer expects M016; one example
test (failed first: `ChannelSequenceTracker` took no argument).
`make _check` and `mkdocs build` clean; the new anchor `#what-eod-means`
exists in the built site. Full suite: 14 611 passed, 1 skipped.

---

## 9. Out of scope, noted

- **pm-dc-gwy has the engine-feed defect of H2.** Its subscriber
  (`dc_gateway/gateway.py:121`) uses the default RCVHWM and does no
  bus-sequence check. Recorded as **L035**.
- **pm-md-gwy and pm-dc-gwy share C5 and C7.** Both run the same
  `select.select` read loop with the same `ValueError` handling
  (`md_gateway/gateway.py:364-369`, `dc_gateway/gateway.py:233-238`) and the
  same `close()` without `EXIT`. Recorded as **L036**, so the three line
  gateways can be aligned again after WP-RALF04. pm-dc-gwy's share moved to
  WP-DCG03 of the DC gateway review, which also took over L035.
- **`-q` in other entry points** is L034; this review rewords only
  pm-ralf-gwy's (D8).
- **`trade.yaml` header** (lines 5-8) says the RALF projection's `encoding`
  block arrives "with the ralf_gateway adoption". The gateway still builds
  its lines by hand; adopting msgen is a 1.x refactor, not a defect.
- **pm-ralf-spy** was read only for the options WP-RALF01 must add; it was
  not reviewed.

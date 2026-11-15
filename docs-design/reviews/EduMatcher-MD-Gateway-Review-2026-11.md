# pm-md-gwy Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/md_gateway/` at `7d4a63d2` (v0.79.0):
`gateway.py` (1242 lines, the reactor, protocol handling and fan-out),
`normaliser.py` (758, engine payload → CALF fields and the SNAP caches),
`main.py` (247, the `pm-md-gwy` CLI), `config.py` (166), `replay_buffer.py`
(111), `protocol.py` (90), `client_session.py` (62), `sequencer.py` (50),
`fanout.py` (32). The engine's book publishing (`engine/main.py`
`_flush_snapshots`, `_handle_book_snapshot_request`,
`_handle_halt_status_request`), the bus sequence frame
(`messaging/bus.py` `SequencedPublisher`, `models/message.py`
`decode_sequence`) and `calf_client/recovery.py`'s `SequenceTracker` were
read where they decide this gateway's behaviour. They were not reviewed as
code of their own.

**Focus:** correctness, edge-case handling, performance, and whether the
comments, help texts, the CALF protocol reference
(`docs/books/protocols-and-clients/part-2-specifications/030-calf.md`), the
operator guide chapter (`part-5-gateways/030-calf-gateway.md`) and training
chapter 230 say what the code does.

**Previous work:** `EduMatcher-md-gwy-review.md` (2026-07, MD-C1 … MD-L9) and
`EduMatcher-Line-Gateway-Alignment-Workplan.md` (W1–W6, 2026-11-05). Their
fixes are in place and are not repeated here: connection cap, slow-client
close with grace, guarded engine handler, idle timer on sends, command rate
limit, engine-poll budget, HELLO deadline, 4096-byte line cap, `peer_reset`,
`REPLAY_MISS` when `LASTSEQ` is ahead or aged out, duplicate-trade sequence
hole (F14). The open alignment option (`select.poll` instead of
`select.select`) is in §9.

**Method:** every line of the files above was read. Findings marked
*(repro)* were reproduced with a scratch script against the tree at
`7d4a63d2`: a real `MarketDataGateway.run()` in a thread, a real
`SequencedPublisher` PUB standing in for the engine (fed with the real
`make_book_msg` / `make_trade_msg` / `make_circuit_breaker_halt` /
`make_session_status_msg` encoders), a PULL socket recording what the
gateway asks the engine, and real TCP clients. For C4 the publisher ran in
a separate process. *(measured)* means timed on this host (36 logical
CPUs) by calling `_emit_stream_event` 20 000 times with 1–64 sessions of 30–600
subscription pairs over 300 symbols. The other findings are by inspection,
with line numbers given.

Status: **Done, uncommitted.** Q1–Q3 decided as recommended (2026-11-14); WP-MDG01–07 done 2026-11-14.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (CALF lines a TCP client receives, requests on the
   engine PULL socket, metric samples, log records).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_md_*.py`,
   `tests/test_calf_*.py` and `tests/test_msgen_calf_*.py` with
   `-n logical`, then black/flake8/mypy/pyright. Do not start the next WP
   with a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Unit tests use the `unit_gateway` fixture and `_FakeSubscriber` from
`tests/test_md_gateway_runtime_paths.py` (socketpair sessions, a fake SUB
fed with `decode`-shaped tuples). Tests about bus sequence frames need the
raw frames, so give `_FakeSubscriber` real `make_*` frames plus a sequence
frame and keep the real `decode`. End-to-end tests drive `run()` in a
thread against a bound PUB/PULL pair, as `tests/test_md_gateway_main.py`
already does.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-MDG01 | Lost engine messages are counted, logged and less likely | C4 | Q2 | 0.5 d | ☑ | 2026-11-14 |
| 2 | WP-MDG02 | SNAP baselines match the engine after a gateway start or engine restart | C1, C2, D6, D10 | WP-MDG01 | 1 d | ☑ | 2026-11-14 |
| 3 | WP-MDG03 | A gateway restart is never replayed as a continuation | C3, D3 | Q1 | 1 d | ☑ | 2026-11-14 |
| 4 | WP-MDG04 | Fan-out cost depends on who wants an event, not on every subscription held | P1 | — | 0.5 d | ☑ | 2026-11-14 |
| 5 | WP-MDG05 | Subscription rules hold on every path | C5, C6 | Q3 | 0.25 d | ☑ | 2026-11-14 |
| 6 | WP-MDG06 | Config and metric say what happened | C7, C8 | — | 0.25 d | ☑ | 2026-11-14 |
| 7 | WP-MDG07 | Texts say what the code does | D1, D2, D4, D5, D7, D8, D9, D11, D12 | all | 0.5 d | ☑ | 2026-11-14 |

Suggested order: **WP-MDG01 → 02 → 03 → 04 → 05 → 06 → 07**. WP-MDG01 adds
the bus sequence tracking that WP-MDG02 uses to notice an engine restart.
WP-MDG03 changes the wire (Q1) and every CALF client in the repo, so it
should land before 1.0. WP-MDG04 is independent and could go first if the
sim's client count makes the lag visible sooner. The text-only WP is last
so the texts describe the final code.

Estimated sequential effort: about 4 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The protocol core is sound. Parsing, framing, the line cap, the handshake,
per-stream sequencing, the replay buffer's miss detection, the slow-client
and idle close paths, the `TOP`/`DEPTH` diffing (`top_cache` vs `top_sent`),
the session/halt state machine in the normaliser and the `SYM=*` rules all
do what the spec says, and the 2026-07 review and the alignment work left
no regressions that this review could find. The reactor is single-threaded,
so there are no races on session state.

The defects are in four places:

- **The gateway's caches are only as good as the events it happened to
  see (C1, C2).** The engine publishes a book only when it changes and a
  halt only when it happens. The gateway never asks for either, so after it
  starts a quiet symbol's `SNAP` says the book is empty, and after an engine
  restart a symbol stays `HALTED` on CALF indefinitely. The engine has request
  messages built for exactly this and the gateway does not use them.
- **Restarts and losses are invisible to clients (C3, C4).** CALF sequence
  numbers are the gateway's own and restart at 1 with it, and nothing on the
  wire says which run they belong to; a `RESUME` across a restart can return
  the new run's events as if nothing was missed. Messages the engine bus
  drops are renumbered contiguously, with no log line or metric.
- **Fan-out cost grows with every subscription held (P1):** 1.3 ms per event
  at 64 clients × 600 pairs, which makes C4's drops more likely.
- **Small rule leaks (C5, C6)** and **texts** that describe an earlier
  gateway (D1–D12).

Severity key: **High**: market data that is wrong or missing with no way for
any client to notice, permanently. **Med**: a wrong, missing or misleading
figure a client cannot detect, or one that persists until a restart; lag
that grows with load. **Low**: hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| C1 | Med | Snapshots | After the gateway starts, `SNAP|CH=TOP/DEPTH` for a quiet symbol carries no bid, ask or levels although the engine's book has orders; the gateway sends the engine no book request *(repro)* | MDG02 |
| C2 | Med | Halts | After an engine restart a halted symbol stays `HALTED` on `STATE` and `CB` for the gateway's lifetime; a gateway started after a halt reports the symbol active *(repro)* | MDG02 |
| C3 | Med | Recovery | Across a gateway restart, `RESUME` returns the new run's events as a continuation; `calf_client` reports no gap and 3 prints are lost *(repro)* | MDG03 |
| C4 | Med | Engine bus | Messages dropped at the SUB high-water mark vanish: 5 500 of 20 000 trades lost, CALF `SEQ` contiguous, no log, no metric *(repro)* | MDG01 |
| C5 | Low | SUB rules | `INDEX` in a `SUB` exempts every channel in it from the symbol check (`SUB|CH=INDEX,TOP|SYM=BOGUS` accepted); an `INDEX` `SNAP` with no level lacks the required `LEVEL`/`SESSION` *(repro)* | MDG05 |
| C6 | Low | SUB rules | `RESUME` adds subscriptions without the `max_symbols_per_client` check: 300 held against a limit of 200 *(repro)* | MDG05 |
| C7 | Low | Config | `enabled: "false"` (a string) enables the gateway; the port range is checked twice | MDG06 |
| C8 | Low | Metrics | `md.msgs_out` counts lines queued, including those `_drop_backlog` discards unsent | MDG06 |
| P1 | Med | Fan-out | `session_wants` scans each client's whole subscription set per event: 10 µs → 1 314 µs per event from 1 to 64 clients × 600 pairs *(measured)* | MDG04 |
| D1–D12 | — | Texts | See §5 | MDG02, 03, 07 |

---

## 3. Correctness findings

### C1. A `SNAP` taken after the gateway starts reports an empty book *(repro)* — Med

`gateway.py:827-848` `_send_snapshot_for_stream`; `normaliser.py:364-367`,
`:396-404`; engine `engine/main.py:1144-1169` `_flush_snapshots`.

The `TOP` and `DEPTH` caches are filled only by `book.{SYM}` messages. The
engine publishes one only for a symbol marked dirty, that is, when its book
changed (`_mark_dirty`, `engine/main.py:1140`). A gateway started while the
market is quiet (the exchange is `CLOSED` overnight, a symbol nobody is
trading, a gateway restarted mid-day) has empty caches, and a `SUB` gets a
baseline that says there is no bid and no ask. The engine answers
`book.snapshot_request` on its PULL socket (`engine/main.py:2850-2857`) and
pm-board, pm-market-sim and pm-ai-trader all send it at start-up. The
gateway's only request to the engine is the session query
(`gateway.py:1078-1089`).

Repro (gateway started, no book has changed since):

```text
requests the gateway sent the engine in its first 2.5 s:
   ['system.session_state_request']
SUB|CH=TOP,DEPTH|SYM=AAPL ->
   SNAP|CH=DEPTH|SYM=AAPL|SEQ=1|TS=…|LEVELS=10
   SNAP|CH=TOP|SYM=AAPL|SEQ=1|TS=…
-- the first book change arrives 0.5 s later:
   MD|CH=TOP|SYM=AAPL|SEQ=2|…|BID=100.0|BIDSZ=100|ASK=100.5|ASKSZ=50
```

A client shows an empty book, and a bot that quotes off it sees no market,
until someone changes that symbol's book. `INDEX` has the same shape
(pm-index publishes on change, so an index `SNAP` before the first update
is empty), but there is no request to fix it with; see C5 and Q3.

**Fix.** Ask the engine for every known symbol's book, and for its halts
(C2), when the engine is first heard from and whenever it restarts. The
restart signal is the bus sequence going backwards on the session-status
topic (WP-MDG01 tracks it).

### C2. Halt state is never reconciled with the engine *(repro)* — Med

`normaliser.py:333-346` `apply_session_to_symbols`, `normalise_halt`;
`:650-653` `cb_snapshot_fields`; engine `engine/main.py:2639-2657`.

The gateway learns of a halt only from the `circuit_breaker.halt.*` event
and of its end only from `circuit_breaker.resume.*`. Two consequences:

1. **Engine restart.** The engine keeps halts in memory only (§9, L021), so
   a restart clears them and publishes no resume. The gateway keeps the
   symbol `HALTED`: `apply_session_to_symbols` deliberately skips halted
   symbols (`normaliser.py:334`), and nothing else ever clears it.
   Repro: halt AAPL, then the restarted engine answers the session query
   unchanged; a new subscriber then gets

   ```text
   SNAP|CH=CB|SYM=AAPL|SEQ=1|…|STATUS=HALTED|LEVEL=L1|TRIGGERPX=95.0|REFPX=100.0|SRC=CB
   SNAP|CH=STATE|SYM=AAPL|SEQ=1|…|SESSION=HALTED
   ```

   while the engine is matching AAPL. This lasts until the gateway restarts.
2. **Gateway started after a halt.** The symbol's `STATE` `SNAP` reports the
   session phase and `CB` reports `STATUS=ACTIVE`, although the engine has
   it halted. Training chapter 230 (line 288) tells students to expect
   `STATUS=HALTED` "if already halted".

The engine answers `system.halt_status_request` with every halted symbol,
its level, source and resume time (`engine/main.py:2639-2657`); the spec
names it "for a caller that has just started and missed it". The gateway
does not use it.

**Fix.** Same trigger as C1: request halt status, apply the answer
(halt symbols it lists that the gateway thinks active, resume symbols it
omits that the gateway thinks halted), and publish the resulting `STATE`
and `CB` events like live ones. The halt-status reply carries no trigger or
reference price, so a `CB` rebuilt from it omits `TRIGGERPX`/`REFPX`; that
is acceptable and should be said in the spec.

### C3. `RESUME` across a gateway restart replays another run's events *(repro)* — Med

`gateway.py:693-722` `_handle_resume`; `replay_buffer.py:216-251`;
`calf_client/recovery.py:144-200`.

CALF sequence numbers live in the gateway's memory and restart at 1 with
it; `WELCOME` carries nothing that identifies the run. Alignment W5 made
`RESUME` answer `REPLAY_MISS` when `LASTSEQ` is *ahead* of the new run's
stream, but once the new run's stream has passed the client's `LASTSEQ`,
the replay succeeds with the new run's events. `calf_client` detects a
restart only by a sequence going backwards on a new connection
(`recovery.py:166`), so it sees nothing either.

Repro: run A prints three AAPL trades (client at `SEQ=3`); the gateway
restarts; run B sees five more prints; the client reconnects and resumes.

```text
A: TRADE|…|SEQ=1|…|TRADE_ID=000007-000000001 …
A: TRADE|…|SEQ=3|…|TRADE_ID=000007-000000003 …
B: TRADE|…|SEQ=4|…|TRADE_ID=000007-000000104 … | client gap: None
B: TRADE|…|SEQ=5|…|TRADE_ID=000007-000000105 … | client gap: None
client believes position 5 with no gap; prints 000007-000000101..103 never reached it
```

The same applies to `TOP` (deltas from run B merged onto a baseline from
run A, which is harmless only because the new run's first `MD` carries every
field) and to every quiet stream (`STATE`, `CB`, `AUCTION`, `INDEX`), whose
sequences are small and are overtaken quickly. The operator guide's
"Recovery option 3" and the spec's reconnect rules promise `REPLAY_MISS`
after a restart (D3).

**Fix.** Give each gateway run an identity on the wire (Q1).

### C4. Engine messages lost on the bus are invisible *(repro)* — Med

`gateway.py:892-901`, `:1034-1042`; `messaging/bus.py:76-107`,
`:348-370`.

The gateway's SUB sockets use ZeroMQ's default receive high-water mark of
1000 messages; past it ZeroMQ drops silently. The engine stamps a per-topic
sequence frame on every message precisely so a subscriber can see such a
hole (`bus.py:79-83`), and pm-alf-gwy, pm-stats and pm-audit read it with
`decode_sequence`. pm-md-gwy calls `decode`, which ignores the frame, and
then numbers whatever arrived contiguously, so no CALF client can see the
loss either.

Repro (publisher in its own process, 20 000 trades over 300 symbols in
0.19 s, gateway with 64 sessions × 600 pairs):

| Matching | Trades emitted | Lost | Log / metric |
|---|---|---|---|
| today (`session_wants` scan) | 14 500 | 5 500 | none |
| O(1) lookup prototype (P1 fix) | 16 781 | 3 219 | none |

The burst is faster than the Python engine would publish (it was built
from pre-encoded frames), so the numbers show the mechanism, not a sim
measurement. P1 narrows the window but does not close it; only detection
makes the loss visible. A lost `trade.executed` is a print that no CALF
client will ever see, on a feed that tells it nothing is missing.

**Fix.** Track the per-topic bus sequence on both SUB sockets, count gaps in
a metric, log the first one per topic at WARNING and later ones latched, and
raise the receive high-water mark. How (or whether) to tell CALF clients is
Q2.

### C5. The `INDEX` exemption leaks to other channels; an empty `INDEX` `SNAP` *(repro)* — Low

`gateway.py:745-757` `_handle_sub`; `normaliser.py:470-472`.

The spec exempts `INDEX` from the known-symbol check because index ids are
a separate namespace. The code skips the check for *every* channel of a
`SUB` that includes `INDEX`:

```python
if sym != "*" and self._known_symbols and sym not in self._known_symbols:
    if not any(ch == "INDEX" for ch in channels):
```

So `SUB|CH=INDEX,TOP|SYM=BOGUS` subscribes `(TOP, BOGUS)` and answers with
an empty `SNAP|CH=TOP|SYM=BOGUS`, contradicting "if any requested pair is
invalid, the gateway rejects the `SUB`". The `and not sym` test at `:755`
can never be true (`_parse_csv_upper` drops empty tokens), as MD-L2 noted.

An `INDEX` subscription for an id the gateway has not seen an update for (an
unknown id, or any index before pm-index's first update after the gateway
started, which outside trading hours is all night) answers
`SNAP|CH=INDEX|SYM=…|SEQ=1|TS=…` with no `LEVEL` and no `SESSION`, both
"required" in the spec's `IDX` table, which the `SNAP` section says it
shares. The gateway cannot validate index ids: the index configuration is
not in the compiled artifact. See Q3.

**Fix.** Apply the exemption per pair. Decide what an `INDEX` `SNAP` without
a level means (Q3).

### C6. `RESUME` bypasses `max_symbols_per_client` *(repro)* — Low

`gateway.py:689-691`.

`RESUME` adds `(CH, SYM)` to the session's subscriptions without the
`SUB_LIMIT` check `_handle_sub` applies (`:763-766`), and does not validate
the symbol (documented). Repro: 300 `RESUME`s for distinct symbols, paced
under the rate limit, leave 300 subscriptions held; the next
`SUB|CH=TRADE|SYM=AAPL` answers `ERR|CODE=SUB_LIMIT`. The limit is the
gateway's bound on per-client fan-out work (P1), so one client can make
every event cost more for everyone.

**Fix.** Count the pair `RESUME` would add against the limit and answer
`ERR|CODE=SUB_LIMIT` (session stays open), before any replay.

### C7. `enabled` is coerced with `bool()`; a duplicate port check — Low

`config.py:61` `enabled = bool(md_raw.get("enabled", True))`: a quoted
`"false"` (or `"no"`) is a non-empty string, so the gateway starts. The
cverifier's layer 2 runs this same loader, so it does not catch it either.
`config.py:97-98` repeats the `port <= 0` test already made at `:65-66`;
it can never fire.

**Fix.** Refuse a non-boolean `enabled` (`ValueError`, which the verifier
then reports); drop the dead check.

### C8. `md.msgs_out` counts lines that were never sent — Low

`gateway.py:1147-1148` counts a line when it is queued. A slow client's
backlog is then discarded by `_drop_backlog` (`:1199-1209`), and lines
queued to a session that disconnects are never sent, but all of them stay
in `md.msgs_out`, which the dashboard plots as messages out. Under a slow
client the figure is inflated by up to `max_client_queue` (10 000) per
disconnect.

**Fix.** Count on a completed send (`_flush_client_writes`, where
`out_queue.popleft()` happens).

---

## 4. Performance findings

At classroom sizes (a handful of clients with a few symbols each) none of
this matters: 10–90 µs per event. It matters at sim scale, where dozens of
bots and GUIs each follow hundreds of pairs.

### P1. Every event scans every client's whole subscription set *(measured)* — Med

`gateway.py:882-886` `_emit_stream_event`; `fanout.py:25-32`
`session_wants`.

For each event, the gateway loops over all sessions and, for each,
iterates its entire subscription set looking for `(ch, sym)` or `(ch, "*")`.
Cost is O(clients × pairs per client) per event, whether or not anyone
wants the event.

| Clients × pairs each | Today | Set lookup (prototype) |
|---|---|---|
| 1 × 30 | 10.0 µs/event | 7.9 µs |
| 16 × 150 | 93.4 µs | 16.7 µs |
| 64 × 150 | 434.8 µs | 27.9 µs |
| 64 × 600 (limit: 200 symbols × 3 channels) | 1 313.6 µs (761 events/s) | 35.4 µs (28 280/s) |
| 64 × 3 wildcard pairs | 36.3 µs | 34.9 µs |

Each book change is up to two events (`MD` and `DEPTH`), each trade one. At
64 × 600 a 5 000-trade burst reached clients 8.3 s late (1.6 s with the
prototype). The cost grows with subscriptions held, not with history or
the day; C6 lets one client raise it without bound.

**Fix.** Index subscriptions by `(ch, sym)` and by channel for wildcards in
`SubscriptionRegistry`, so an event visits only the sessions that want it.
That also retires MD-L3's duplicated bookkeeping if `ClientSession` stops
holding its own copy.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `030-calf.md` §`IDX` | "`IDX` has no baseline `SNAP` variant in CALF 1.0.0. Delivery starts from events that occur after the subscription becomes active." The same page's `SNAP` section, the operator guide and the code (`gateway.py:799-800`) send an `INDEX` `SNAP`. |
| D2 | `030-calf.md` §`ERR` | The example `ERR|CODE=REPLAY_MISS|DETAIL=Requested sequence outside replay buffer|…` carries a `DETAIL`; the gateway sends none (`gateway.py:705-709`). |
| D3 | operator guide "Recovery option 3"; `030-calf.md` reconnect rules | Say a restarted gateway answers `REPLAY_MISS`; true only while `LASTSEQ` is ahead of the new run (C3). Rewritten in WP-MDG03. |
| D4 | operator guide "What this process is", flowchart | Shows `index.*` arriving from pm-engine on `:5556`; it comes from pm-index on `:5558` (`gateway.py:144`). |
| D5 | operator guide warning "If `engine_config.yaml` fails to load" | Says the gateway "silently" falls back to an empty symbol set; `main.py:162-168` logs a WARNING, and the source is the compiled configuration, not `engine_config.yaml`. |
| D6 | operator guide "What this process is" | "This is the gateway's only traffic towards the engine": changes with C1/C2. Rewritten in WP-MDG02. |
| D7 | `gateway.py:1216-1229` `_extract_ts` | Implies every topic carries `ts_ns` and calls the fallback "believed dead". `session.state`, `system.session_status`, `circuit_breaker.*` and `auction.*` carry no time at all, so their `TS` is the gateway's receive clock; the docstring should say so (the spec's "Transition timestamp" too). |
| D8 | `pm_help/registry.py:668-676` | Summary and description name only `TOP`, `TRADE` and `STATE`; the gateway serves seven channels. |
| D9 | `main.py:38-47`; `registry.py:681-689` | `--engine-pub` "overrides config" and `--index-pub` "(overrides config)": the YAML loader reads neither address (`config.py:121-122` always uses the constants), and `--index-pub`'s non-`None` default makes `cfg.index_pub_addr` at `main.py:146` unreachable. |
| D10 | training ch. 230, line 288 | "`STATUS=HALTED` plus detail if already halted": only if the gateway saw the halt (C2). Rewritten in WP-MDG02. |
| D11 | `normaliser.py:372-377`; `030-calf.md` message catalogue | `normalise_depth` "Return incremental `DEPTH` fields" and the catalogue's "Incremental multi-level order book update": `DEPTH` is a full-ladder replace, as the `DEPTH` section says. |
| D12 | `client_session.py:42` | `last_activity` "used for both auth-timeout and idle-timeout checks": the auth deadline uses `connected_at` (`gateway.py:1108`). |

---

## 6. Verified as correct

- **Framing and the line cap.** Partial, single and multiple lines per
  `recv`; the unterminated-tail and complete-line checks agree at exactly
  4096 bytes; nothing after a closing line is dispatched
  (`gateway.py:347-380`).
- **Close paths.** Slow client, idle, auth timeout, refused `HELLO` and
  client `EXIT` all go through `_close_after_flush` with the 5 s grace; a
  closing session gets no further lines; a partly sent line is kept ahead
  of the final `ERR` (`:395-452`, `:1136-1209`).
- **Sequencing and replay.** A repeated `TRADE_ID` is dropped before a
  sequence is taken (`:863-869`); `replay_since` distinguishes up-to-date,
  aged-out and ahead (`replay_buffer.py:216-251`); a `SNAP` on a never-emitted
  stream starts at 1 and the next event is 2, as the spec says.
- **`TOP` diffing.** `top_cache` (what a `SNAP` reports) and `top_sent`
  (what `MD` diffs against) are kept apart, so `LAST` after a trade reaches
  continuously connected clients; a withdrawn side is sent as `BID=`/`ASK=`
  (`normaliser.py:136-236`).
- **Session and halt state.** Per-symbol `STATE` is repeated on each exchange
  transition except for halted symbols; a resume goes to the current phase,
  not to `CONTINUOUS`; `NEXTPHASE`/`NEXTAT` are both-or-neither and
  replaced wholesale (`normaliser.py:238-362`).
- **Engine handler isolation.** A failing normaliser for one topic logs and
  skips; `STATE` and `CB` for one halt are separate emits.
- **Heartbeat vs idle.** The cverifier's M033 already warns when
  `idle_timeout_sec ≤ 2 × heartbeat_interval_sec` for this section.
- **Rate limiting** applies before authentication, so a pre-auth flood is
  bounded too.

---

## 7. Decisions

| # | Question | Recommendation |
|---|---|---|
| Q1 | How does a client learn that sequences belong to a new gateway run (C3)? (a) `WELCOME|EPOCH=<id>` only, and clients reset their positions when it changes; (b) (a) plus a required `EPOCH` on `RESUME`, and the gateway answers `REPLAY_MISS` (plus `SNAP` where one exists) when it is not the current run's; (c) start every stream's sequence at a value derived from the start time, so a new run is always ahead of any old position. | **(b)**: the gateway decides in one place, so a client that forgets to compare epochs still cannot be fed another run's events; `calf_client`, the examples and the spies send it. (a) leaves correctness to each client. (c) needs no field but breaks the spec's "start value is 1", makes sequences unreadable in class, and a wall-clock step backwards would recreate the bug. No backwards compatibility: `RESUME` without `EPOCH` becomes `BAD_MESSAGE`. |
| Q2 | What happens on an engine-bus gap (C4)? (a) log + metric `md.bus_gaps` only; (b) (a) plus a larger receive high-water mark; (c) (b) plus telling clients, e.g. an `ERR|CODE=DATA_LOSS|CH=TRADE` to every `TRADE` subscriber (the lost trade's symbol is unknown). | **(b)**: an operator sees the loss, and a deeper buffer (as pm-audit and pm-stats use) rides out bursts. (c) is a protocol addition whose client-side meaning ("some print somewhere is missing") is weak; put it in the For-Later list if wanted. |
| Q3 | What does an `INDEX` `SNAP` mean before the gateway has a level (C5)? (a) keep sending it without `LEVEL`/`SESSION` and document that as "no level published since the gateway started; wait for the first `IDX`"; (b) send no `SNAP` until a level is cached; (c) ask pm-index for current levels at start-up (no such request exists today). | **(a)**: honest, no new message, and clients already key on field presence (`INDICPX`, `SYMBOLS`). (b) leaves a client with no baseline sequence; (c) needs a new pm-index request, which is out of scope. |

---

## 8. Work packages

### WP-MDG01 — Lost engine messages are counted, logged and less likely (C4; after Q2)

**Tests first** (`tests/test_md_gateway_runtime_paths.py`):

1. Feed `trade.executed` frames with bus sequences 1, 2, 5 → metric
   `md.bus_gaps` (counter, labelled by topic) is 2 and one WARNING names the
   topic and the missing range. (Fails today.)
2. A second gap on the same topic increments the metric without another
   WARNING inside the latch window. (Fails today.)
3. A sequence going backwards (1, 2, 1) is a restart, not a gap: no count,
   one INFO line, and the tracker exposes "restarted" for that topic (used
   by WP-MDG02). (Fails today.)
4. Frames without a sequence frame are processed as today, unchanged.
5. The engine and index SUB sockets are created with the receive
   high-water mark chosen in Q2 (assert `getsockopt(zmq.RCVHWM)`).
   (Fails today.)

**Change.** Read `decode_sequence(frames)` in `_poll_engine_events` for both
sockets; keep last-seen per topic; count, log (latched), and report through
`metric_samples`. Pass `rcvhwm=` to `make_subscriber`. Add the metric to the
health sample list and to the monitor/dashboard only if the monitor already
renders per-gateway counters by name (check `client_gateway_samples`).

**Exit criteria.** Tests 1–5 pass; `tests/test_md_*.py` and the monitor tests
green; the scratch repro reports the lost count in the metric.

**Outcome (2026-11-14).** `_check_bus_sequence` reads `decode_sequence` on
both SUB sockets before `decode`; a jump adds the missed count to
`md.bus_gaps` (counter, labelled by topic family: `book`,
`circuit_breaker.halt`, …, or the topic itself, so 300 books are one label)
and logs one WARNING per family per `_BUS_GAP_LOG_INTERVAL_SEC` (60 s), with
the count since the last one; a sequence going back logs one INFO per family
and returns `True` (used by WP-MDG02). Both SUBs get `_SUB_RCVHWM = 100_000`
(pm-stats' value). `md.bus_gaps` joined pm-monitor's `WATCHED_INCREASES`
(rule `md_bus_gaps`, any increase in 5 min), dash-gui's `FIXED_RULES`, the
health-contract test's owner list, the operator guide's threshold table and
the log ledger. Tests 1–3 and 5 failed first (no metric, no
`_check_bus_sequence`, no `_SUB_RCVHWM`); test 4 passed before and after; an
index-socket case and a monitor-rule case were added. The first full run
caught the two contract tests (ledger entry, watched-counter owner).
Scratch repro (separate-process publisher, 64 × 600 pairs, today's fan-out):
40 000 trades in 0.33 s, **0 lost** with the new buffer; forced back to 1 000,
20 000 lost and `md.bus_gaps = 20000` exactly. Limit, inherent in sequence
detection: a loss at the very end of a burst is counted only when that
topic's next message arrives. Full suite: 14 334 passed, 1 skipped.

### WP-MDG02 — SNAP baselines match the engine after a gateway start or engine restart (C1, C2, D6, D10; after WP-MDG01)

**Tests first** (`tests/test_md_gateway_runtime_paths.py`,
`tests/test_md_normaliser.py`):

1. On the first `system.session_status` answer the gateway pushes one
   `book.snapshot_request` per known symbol and one
   `system.halt_status_request` to the engine PULL (capture the push
   socket). (Fails today.)
2. When WP-MDG01's tracker reports that the session-status topic restarted,
   the same requests go out again; an unchanged repeated answer sends
   nothing. (Fails today.)
3. A `system.halt_status.{GW}` answer listing AAPL halted (gateway thought
   it active) emits `STATE|SYM=AAPL|SESSION=HALTED` and
   `CB|SYM=AAPL|STATUS=HALTED|LEVEL=…|SRC=…`; a later `SNAP|CH=CB` carries
   them. (Fails today.)
4. An answer omitting a symbol the gateway holds `HALTED` emits a resume
   (`STATE` to the current phase, `CB|STATUS=ACTIVE`). (Fails today.)
5. The C2 repro end to end: halt, simulated engine restart (bus sequence
   back to 1, empty halt list) → a new subscriber's `SNAP`s say active.
   (Fails today.)
6. A live `circuit_breaker.halt` still produces the full `CB` fields
   (trigger and reference price), unchanged.

**Change.** Subscribe to `system.halt_status.{name}`; a `_resync_engine_state()`
that pushes the requests, called on the first status answer and on a
detected engine restart; `EngineNormaliser.apply_halt_status(halted)`
returning the `STATE`/`CB` changes. Operator guide (D6) and training ch. 230
(D10) updated; spec `CB` section says a halt learned this way has no
`TRIGGERPX`/`REFPX`.

**Exit criteria.** Tests 1–6 pass; `tests/test_md_*.py`,
`tests/test_calf_*.py` green; the C1 and C2 repros show populated `SNAP`s.

**Outcome (2026-11-14).** The gateway subscribes to
`system.halt_status.{GW}`. `_resync_engine_state` pushes one
`system.halt_status_request` and then one `book.snapshot_request` per known
symbol; it runs on the first session-status answer and whenever that topic's
bus sequence goes back (an engine restart, detected within one 2 s query).
If the halt request cannot be sent it retries on the next answer; if the
PUSH fills part-way through the books, the rest arrive with their next
change (logged at INFO). `EngineNormaliser.apply_halt_status` halts listed
symbols the gateway thought active and resumes held-`HALTED` symbols the list
omits, through the existing `normalise_halt`/`normalise_cb_halt`/
`normalise_resume`/`normalise_cb_resume`, so live and reconciled events share
one shape; the gateway emits them as `STATE` and `CB` events. Tests 1–5 and
three normaliser tests failed first for the right reasons; test 6 is the
existing `test_poll_engine_events_halt_emits_state_and_cb`, unchanged.
Docs: operator guide "What this process is" (D6), training ch. 230 exercise
(D10), spec `CB` section ("Halts learnt from the engine's halt list").
Scratch repro against a real gateway and an engine stub answering the PULL
requests: C1 `SNAP|CH=TOP|…|BID=100.0|BIDSZ=100|ASK=100.5|ASKSZ=50` and a
populated `DEPTH`; C2 `STATUS=ACTIVE`/`SESSION=CONTINUOUS` after the restart;
a gateway started after a halt reports `STATUS=HALTED|LEVEL=L2|SRC=CB` and
`SESSION=HALTED`. Limit: the engine does not answer a book request for a
symbol it holds no book for (`engine/main.py:2850-2856`), so after an engine
restart that restored no orders for a symbol, its old `TOP`/`DEPTH` stay
until its first order: For-Later **L028**. Full suite: 14 342 passed,
1 skipped.

### WP-MDG03 — A gateway restart is never replayed as a continuation (C3, D3; after Q1)

**Tests first** (`tests/test_md_gateway_unit.py`, `tests/test_calf_client.py`):

1. `WELCOME` carries `EPOCH`, different for two gateway instances. (Fails
   today.)
2. `RESUME` with the current `EPOCH` and a retained `LASTSEQ` replays as
   today, now with the required field. (Fails today only because `WELCOME`
   has no `EPOCH` to send back.)
3. `RESUME` with another `EPOCH` → `ERR|CODE=REPLAY_MISS` and, on `TOP`, a
   `SNAP`; on `TRADE`, no `SNAP`. (Fails today.)
4. `RESUME` without `EPOCH` → `ERR|CODE=BAD_MESSAGE`, session open. (Fails
   today.)
5. The C3 scenario through `calf_client`: positions from run A, reconnect to
   run B → the client's `on_gap` reports the `TRADE` loss. (Fails today.)

**Change.** A per-run id generated in `MarketDataGateway.__init__`; `WELCOME`
field; `_handle_resume` check; `calf_client` stores the epoch from
`WELCOME` and sends it; `docs/examples/calf/*`, `calf_spy` and the
terminal-gui bridge updated; spec, operator guide (D3) and training chapter
rewritten for the new rule.

**Exit criteria.** Tests 1–5 pass; `tests/test_calf_*.py`,
`tests/test_md_*.py`, the examples' tests and `make test-e2e` (when the sim
is stopped) green.

**Outcome (2026-11-14).** The gateway draws `_epoch = secrets.token_hex(4)`
per instance and sends it as `WELCOME|EPOCH=`. `RESUME` without `EPOCH` is
`BAD_MESSAGE` (session open, nothing subscribed); with another run's epoch it
takes the existing `REPLAY_MISS` path (the pair stays subscribed; `SNAP` only
on snapshot channels). Clients: `calf_client`'s `SequenceTracker` records the
epoch of each stream position (`new_connection(epoch)`, now called after
`WELCOME` rather than at connect) and a `Gap` carries the epoch of the
position *before* the hole, so a resume after reconnecting to a restarted
gateway names the old run; `CalfClient.resume()` takes `epoch`.
`pm-calf-spy --resume` is now `CH:SYM:LASTSEQ:EPOCH` (pm-help, completion
regenerated). The terminal-gui bridge does the same as `calf_client`
(`StreamPosition.epoch`, `buildResume(…, epoch)`, `WelcomeInfo.epoch`; the
fake gateway answers another run's epoch with `REPLAY_MISS`). The Python and
C examples (which do not reconnect) send the `WELCOME`'s epoch;
`calf_recovery_build_resume` takes it. Tests 1–4 failed first (`KeyError:
'EPOCH'`, no `REPLAY_MISS`, no `BAD_MESSAGE`); test 5 failed on the old
client with "timed out waiting for a RESUME naming run A". Added: a tracker
test, a spy parse test, an examples test, a C self-test line, two TS
protocol tests and a bridge restart test. The existing `RESUME` unit tests
were given the current epoch. The test stub's `close()` now shuts the socket
down, without which a reconnect test never saw EOF. Docs: spec (`WELCOME`,
`RESUME`, error table, reconnect rules, diagrams), operator guide (command
table, recovery options 1 and 3 = D3, examples), training ch. 230
exercise 6, protocols-and-clients ch. 3 and spy chapter, reference manual,
examples README. Exit check through the real `calf_client` against two
gateway runs on one port, run B printing while the client was away: before,
no gap and three prints lost silently; now `on_gap` reports
`Gap(TRADE, AAPL, …)`. `make test-e2e` was not run (the sim may be running
on this host). C self-test: all checks passed; terminal-gui: 753 tests and
typecheck green. Full suite: 14 350 passed, 1 skipped.

### WP-MDG04 — Fan-out cost depends on who wants an event (P1)

**Tests first** (`tests/test_md_gateway_emit.py`):

1. Wildcard and exact subscriptions on the same channel deliver an event
   once, unchanged.
2. `UNSUB` and disconnect remove a session from the index (no delivery
   afterwards), unchanged.
3. With 64 sessions × 600 pairs, `_emit_stream_event` visits only sessions
   that want the event (count `session_wants`/lookup calls, not time).
   (Fails today.)

**Change.** `SubscriptionRegistry` keeps `(ch, sym) → fds` and
`ch → fds` (wildcards); `_emit_stream_event` iterates the union.

**Exit criteria.** Tests pass; the bench in §4 at 64 × 600 is ≤ 50 µs per
event (prototype: 35.4 µs; the target is a guess with that margin).

**Outcome (2026-11-14).** `SubscriptionRegistry` keeps `_by_stream`
(`(ch, sym)` → fds, with `SYM=*` as its own key) beside `_by_client`;
`set_for_client` and `remove_client` maintain both, `wanting(ch, sym)` returns
the union of the exact and wildcard sets, and `session_wants` became two set
lookups. `_emit_stream_event` iterates `wanting` and skips sessions that are
gone, unauthenticated or closing. Test 3 failed first (64 sessions visited
for 35 that wanted the event); test 1 passed before and after; test 2's
delivery part was unchanged and it now also asserts the index is emptied by
`UNSUB` and disconnect. `ClientSession.subscriptions` still holds its own copy
(MD-L3); merging the two was not needed for P1 and was left alone. Bench
(§4 method, this host):

| Clients × pairs each | Before | After |
|---|---|---|
| 1 × 30 | 10.0 µs/event | 7.3 µs |
| 16 × 150 | 93.4 µs | 7.5 µs |
| 64 × 150 | 434.8 µs | 9.7 µs |
| 64 × 600 | 1 313.6 µs | 16.8 µs |
| 64 × 3 wildcard pairs | 36.3 µs | 21.7 µs |

The C4 repro forced back to the old 1 000-message buffer now loses 3 467 of
20 000 (5 500 before; all counted in `md.bus_gaps`). Full suite: 14 353
passed, 1 skipped.

### WP-MDG05 — Subscription rules hold on every path (C5, C6; after Q3)

**Tests first** (`tests/test_md_gateway_unit.py`):

1. `SUB|CH=INDEX,TOP|SYM=BOGUS` → `ERR|CODE=INVALID_SYMBOL|SYM=BOGUS`,
   subscriptions unchanged. (Fails today.)
2. `SUB|CH=INDEX|SYM=EDU50` with no cached level still sends the `SNAP`
   without `LEVEL`, as decided in Q3 (unchanged behaviour, now specified).
3. A `RESUME` that would take a client past `max_symbols_per_client` →
   `ERR|CODE=SUB_LIMIT`, no replay, session open. (Fails today.)
4. A `RESUME` for a stream already covered by a wildcard adds nothing and
   is not counted, unchanged.

**Change.** Per-pair exemption in `_handle_sub` (drop the dead `not sym`
branch); limit check in `_handle_resume`; spec text for Q3.

**Exit criteria.** Tests 1–4 pass; `tests/test_md_*.py`, `tests/test_calf_*.py`
green.

**Outcome (2026-11-14).** `_handle_sub` rejects an unknown non-wildcard
symbol unless every channel in the `SUB` is `INDEX`; the dead `not sym`
branch is gone. `_handle_resume` answers `ERR|CODE=SUB_LIMIT` (session open,
nothing added or replayed) when the stream is not already held, its symbol is
new, and the session already holds `max_symbols_per_client` symbols; the check
sits after the `EPOCH` check and before the subscription is added. Tests 1
and 3 failed first (a `SNAP` for `BOGUS`; a replay instead of `SUB_LIMIT`);
2 and 4 passed before and after. Spec: subscription rules (per-pair
exemption, limit on `RESUME`), `RESUME` validation, config notes, the `SNAP`
`INDEX` paragraph for Q3, and the `IDX` paragraph (D1, done here since it is
the same text); operator guide `max_symbols_per_client` row. Full suite:
14 357 passed, 1 skipped.

### WP-MDG06 — Config and metric say what happened (C7, C8)

**Tests first** (`tests/test_md_gateway_config.py`,
`tests/test_md_gateway_runtime_paths.py`):

1. `enabled: "false"` → `ValueError` naming `market_data_gateway.enabled`.
   (Fails today.)
2. `enabled: false` / `true` load as today, unchanged.
3. A slow client whose 10 000-line backlog is dropped adds only the lines
   actually sent to `md.msgs_out`. (Fails today.)

**Change.** Boolean check in the loader (reuse a `config_coerce` helper if
one exists); remove the duplicate port test; count in
`_flush_client_writes`.

**Exit criteria.** Tests pass; cverifier tests green.

**Outcome (2026-11-14).** The loader refuses a non-boolean `enabled` with
`ValueError("market_data_gateway.enabled must be true or false, got …")`
(no bool helper exists in `config_coerce`, so the check is inline); the dead
second `port <= 0` test is removed. `md.msgs_out` is incremented in
`_flush_client_writes` when a line has been sent whole, no longer in
`_queue_raw`. Tests 1 and 3 failed first (no `ValueError` for `"false"`,
`"no"`, `1`; 10 001 counted against 93 sent); test 2 passed before and after.
The full suite then caught `test_gateway_metrics.py`'s
`test_md_counts_messages_out_and_a_slow_client`, which asserted the old
count-on-queue meaning; it now asserts 0 queued, 3 after the flush. Checked
by hand: `pm-cverifier` on a config with `enabled: "false"` reports
`[S083] … market_data_gateway.enabled must be true or false, got 'false'`.
Full suite: 14 363 passed, 1 skipped.

### WP-MDG07 — Texts say what the code does (D1, D2, D4, D5, D7, D8, D9, D11, D12)

**Tests first.** None of these change behaviour; `tests/test_pm_help*.py`
and `test_shell_completion` must stay green (`make completion` if `--help`
text changes).

**Change.** Each item in §5 as described; re-walk the operator guide's
"Quick connect test" and "Gap detection" sections and training chapter 230
against the code after WP-MDG02/03.

**Exit criteria.** `make _check` and the full suite green; every §5 row
fixed or marked done in a WP outcome.

**Outcome (2026-11-14).** D1 was done in WP-MDG05, D3 in WP-MDG03, D6 and D10
in WP-MDG02. Here: D2 the spec's `REPLAY_MISS` example lost its `DETAIL`;
D4 the operator guide says `index.*` comes from pm-index on `:5558` (text and
flowchart, which also gained `auction.indicative.*`); D5 the warning now
describes what happens (WARNING and an empty symbol set when no compiled
configuration is deployed; refusal to start when the deployed one is
unreadable); D7 `_extract_ts` names which topics carry `ts_ns` and which get
the gateway's receive time (checked against the generated message classes);
D8 pm-help names all seven channels; D9 `--engine-pub`/`--index-pub` help
(argparse, pm-help, operator guide table) says the configuration file does not
set them (completion regenerated); D11 `normalise_depth`'s docstring and the
spec catalogue say `DEPTH` replaces the ladder; D12 the `last_activity`
comment. Re-walked the operator guide's "Quick connect test", "Connecting and
subscribing" (Step 1 now says to keep `EPOCH`) and "Gap detection" sections
and training ch. 230 against the final code; nothing else was stale.
`mkdocs build --strict` clean; full suite: 14 363 passed, 1 skipped.

**Not changed (noted).** `--index-pub` still has a non-`None` argparse
default, so `cfg.index_pub_addr` in `_resolve_config` is never used; both are
the same constant, so this is dead code rather than a defect, and the WP was
text-only.

---

## 9. Out of scope, noted

- **Engine restart clears every halt.** `_halted_symbols` is not persisted,
  so an operator's halt silently ends with an engine restart, and no resume
  is published. WP-MDG02 makes pm-md-gwy follow whatever the engine holds,
  but the engine behaviour itself is a question for the engine. For-Later
  **L021**.
- **`select.select` fd ceiling.** Alignment W3 caught the `ValueError` at an
  fd ≥ 1024, but a `max_connections` near that value makes every read pass
  skip; `select.poll` would remove the ceiling. Noted in the alignment
  workplan as an option; not a defect at the default of 64.
- **`-q/--quiet`** sets the level that is already the default (`main.py:106-109`);
  the same pattern is shared by other `pm-*` CLIs.
- **Prices on `TRADE`** are formatted with `str(float(…))` in the generated
  projection (`models/generated/trade.py:460`), so a price below 1e-4 would
  print in exponent form; no configured `tick_decimals` reaches that today.

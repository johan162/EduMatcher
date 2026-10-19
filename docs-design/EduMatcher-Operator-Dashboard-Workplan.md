# EduMatcher — Operator Dashboard: Workplan and Progress

Tracks the implementation of
[`EduMatcher-Operator-Dashboard.md`](EduMatcher-Operator-Dashboard.md) (v0.3.0),
§18. One work package (WP) at a time; each WP ends with a holistic test run
(`make _check` + the full test suite, or `npm run typecheck && npm test` for
web apps), a holistic review for new insights, and a proposed commit message. The
maintainer commits.

Started: 2026-10-18

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit)

Execution order follows the dependencies in §18.2 (A2 needs A3, so A3 runs
before A2).

| # | WP | Content | Depends on | Status | Done on |
|---|---|---|---|---|---|
| 1 | A1 | Message spec `health.yaml`, transports, publishers, generated code | — | ☑ | 2026-10-18 |
| 2 | A3 | `monitor` config section end to end (SCHEMA_VERSION 5, cverifier S124+/M029+, config-show, ports) | — | ☑ | 2026-10-18 |
| 3 | A2 | `edumatcher.health.HealthReporter`, `psutil` | A1, A3 | ☑ | 2026-10-19 |
| 4 | A4 | Engine metrics, reject funnel, book memory estimate, reporter, perf gate | A2 | ☑ | 2026-10-19 |
| 5 | A5 | Gateway metrics and reporters (ALF, BALF, MD, RALF, DC, API) | A2 | ☑ | 2026-10-19 |
| 6 | A6 | Service metrics and reporters (log-srv, stats, audit, clearing, scheduler, index, market-sim) | A2 | ☑ | 2026-10-19 |
| 7 | B1 | `pm-monitor` skeleton, process state, 1 Hz snapshot | A1–A3 | ☑ | 2026-10-19 |
| 8 | B2 | Health model and expected roster | B1 | ☑ | 2026-10-19 |
| 9 | B3 | Rates, engine-bus events, thresholds, host sampler | B1 | ☐ | |
| 10 | B4 | `metrics.db` store, downsampling, retention | B3 | ☐ | |
| 11 | B5 | Start-up integration: `emo` profiles, container `EXPOSE`, participant-bot beacons (B5.4, I38) | B1 | ☐ | |
| 12 | C1 | Scaffold `web-apps/dash-gui` | — | ☐ | |
| 13 | C2 | Bridge: monitor uplink, `/ws`, history REST | B1, B4, C1 | ☐ | |
| 14 | D1 | App shell, top bar, time picker, theme, settings | C1 | ☐ | |
| 15 | D2 | Widget library | D1 | ☐ | |
| 16 | D3 | Dashboard rows 1–7 | C2, D2 | ☐ | |
| 17 | D4 | Drawers and deep links | D3 | ☐ | |
| 18 | E1 | Compose (docker + curl), GHCR workflow, `mkbld.sh`, Makefiles, READMEs | C1, B5 | ☐ | |
| 19 | E2 | Operator-guide chapter and reference docs | D4, A3 | ☐ | |
| 20 | E3 | End-to-end scenarios | all | ☐ | |

## Per-WP checklist

1. Re-read the WP in §18 and the design sections it cites; check the named
   files/functions still exist.
2. Implement the tasks, each with its verifying test.
3. Holistic test: `make _check`, the full `pytest` suite (excluding perf
   unless the WP has a perf gate), plus app tests for TypeScript WPs.
4. Review: what did implementation reveal? Fix code, and update the design
   doc and later WPs where an assumption turned out wrong. Log it below.
5. Mark the WP ☑ here, propose a commit message, stop.

## Insights log

Findings made during implementation that changed code, the design or a later
WP. Numbered I1, I2, … so they can be referenced from commits.

| # | WP | Insight | Action |
|---|---|---|---|
| I1 | A1 | The generator handles everything §11.1 needs (records in records, lists of records, lists of `float`/`int`), so the snapshot is fully generated and validated. | No `json_payload` fallback. Design §11.1 now names `spec/messages/health.yaml` as the wire shape. |
| I2 | A1 | §11.1's TS sketch had a map (`files`), a positional tuple (`load`) and two undefined records (`GatewayStats`, `ActiveBreach`), and repeated the rate fields three times. | Spec uses `FileSize[]`, `load1/5/15`, defines both records and one `RateStats`. Wire is snake_case; C2.5 mirrors it. Differences listed in design §11.1. |
| I3 | A1 | A beacon `host` ≤ 64 (§7.4) would fail validation for a long FQDN, and validation happens in the sampler thread, so the process would go SILENT for good. | `host` ≤ 128 (as `LogRow.host`); design §7.4 updated; A2 truncates `gethostname()` to 128. |
| I4 | A1 | Generated `make_*` constructors validate, so any bad sample (label > 32, empty name) raises in the A2 sampler thread. | A2 watch-out: catch per beacon, count, keep the thread alive. A4 watch-out: label bound vs clamp. |
| I5 | A1 | The UI needs to know which processes are bots (Q2) and needs to read raw metrics not summarised elsewhere (row 6, D3.1). | Added `ProcessHealth.group` (EXCHANGE/BOT) and `ProcessHealth.metrics`; also `TradingStats.busy_pct`, `ExchangeStatus.session_timezone`, `health.event.severity`. |
| I6 | A1 | Measured a realistic snapshot: ≈ 65 KB, 0.8 ms to build and validate. | Validation cost dismissed; size noted in §11.1 and B1 (trim `ProcessHealth.metrics` for the engine first if needed). |
| I7 | A1 | `unit` vocabulary had no bytes/seconds/ms/µs; existing specs fudge these as `dimensionless`. | Added `bytes`, `duration_seconds`, `duration_millis`, `duration_micros` to `msgen/spec.py:UNITS`. Retro-fitting `log.yaml`'s `*_sec`/`*_ms` fields is a possible follow-up (doc-only change to its reference). |
| I8 | A1 | `pm-msgen lint` dies with a raw PyYAML traceback on a YAML syntax error (e.g. a `>` block scalar inside a flow mapping) instead of a `SpecError` naming the file. | Follow-up, out of scope for this plan. |
| I9 | A1 | The holistic run caught that `"monitor.snapshot"` already exists as the frame type of the API gateway's `/admin/monitor` WebSocket (trader-gui), an unrelated protocol; `pm-msgen grep-literals` flagged it. | Johan chose to rename the bus family to `health` (`health.beacon/snapshot/event`, `spec/messages/health.yaml`); transports, publisher, config section and process name keep `monitor`. Design doc updated throughout. |
| I10 | A1 | Adding a spec family trips four cross-cutting gates: the pinned family list and message count, the audit-replay lexicon (every top-level enum value needs a gloss), and the builder-adoption gate (every message needs a `make_*` producer in `src/`). | Lexicon glosses for `health.event` `kind`/`severity`; count 121 → 124; a self-expiring `PENDING_ADOPTION` set in `test_msgen_adoption.py` that A2 (beacon) and B1/B3 (snapshot/event) must empty, enforced by a guard test. |
| I11 | A3 | M018 and the config-show port panel only looked at sections *present* in the YAML. pm-monitor binds 5610/5611 with no `monitor:` block at all, so `alf_gateway.port: 5610` would have passed verification and failed at start-up. | `gateway_ports.MONITOR_PORTS` + `monitor_section()`: counted unless `enabled: false`. Tested in both consumers. `log_server` has the same latent gap (pm-log-srv binds 5600–5602 on defaults when the block is absent); follow-up, not fixed here. |
| I12 | A3 | `LogServerConfig.bind_address` resolves `EDUMATCHER_GATEWAY_BIND_HOST` at **compile** time, so the env of the compiling shell is baked into the artifact. | `MonitorConfig.bind_address` stores the authored value; B1.2 must call `resolve_gateway_bind_host()` when binding (design B1.2 annotated). The log_server behaviour is a possible follow-up. |
| I13 | A3 | A dedicated "pull == pub" M-code would duplicate M018, which already has both ports in its inventory (log_server avoids the duplicate only because its S102 is layer 2 and L3 never runs after an L2 error). | No M031; M018 reports it (tested). Design §14/A3.4 updated. |
| I14 | A3 | A new top-level section trips more gates than the WP listed: config-gen's `--comment-default-config-fields` shape+notes (pinned by test), `KNOWN_TOP_LEVEL`, the S121 key pin, and the operator guide's verifier code tables. | All updated; added a test that the documented `monitor:` example resolves exactly to `MonitorConfig()`. |
| I15 | A3 | Would deferring config-gui support (§19.3) lose a `monitor:` block on save? | No: config-gui's yaml-codec keeps unknown sections in `unmappedYaml` and re-emits them. Deferral is safe. |
| I16 | A3 | `log_server`'s loader uses `bool(...)` on `enabled`, so a quoted `"false"` reads as True (only S096 at verify time stops it). | `monitor` loader is strict (`must be true or false`). log_server left alone (out of scope). |
| I17 | A3 | CHANGELOG has no Unreleased section; entries are written at release. | Breaking change (SCHEMA_VERSION 5 → redeploy) stated in the A3 commit message; CHANGELOG entry in E2.4. Verified a v4 artifact is refused with "redeploy with pm-config-deploy". |
| I18 | A2 | `psutil` was not installed at all; the design's "already a transitive dev dependency" (§3) was stale. `poetry.lock` is git-ignored in this repo, so only `pyproject.toml` records the change. | `psutil ^7.2.2` (runtime) and `types-psutil` (dev) added. Container installs the wheel via pip, which resolves psutil from PyPI; E3 confirms. |
| I19 | A2 | With no deployed artifact the monitor section resolves to *enabled* defaults, so once A4–A6 wire reporters, every test running a real process loop would beacon into a developer's live pm-monitor on 5610 (the `pm-log-srv` trap again). | Autouse `_no_health_beacons` in `tests/conftest.py` + `real_health_reporter` marker (registered in `pyproject.toml`); guard pinned by `tests/test_health_guard.py`. Noted in design A4. |
| I20 | A2 | LINGER 0 (design §7.5) would discard the final beacon, making every clean stop look DEAD. Without `ZMQ_IMMEDIATE`, up to 10 beacons queue for an absent monitor and arrive as a stale burst when it binds. | `stop()` closes with a 500 ms linger (still returns < 1 s with no peer, tested). B1 watch-out added: drain fully, judge by highest `seq` per `boot_id`. |
| I21 | A2 | Per-sample validation needs its own counter, distinct from dropped beacons. | `health.samples_rejected` added (design §8.6). |
| I22 | A2 | `tick()` measured at ≈ 160 ns; the engine pays it once per message. | Recorded in design A4 for the ≤ 2 % perf gate; test bound 10 µs (holds under coverage tracing). |
| I23 | A2 | `started_at_ns` taken from `psutil.Process().create_time()` (process start), not from the reporter's construction, so uptime is right even when a process wires its reporter late. | — |
| I24 | A4 | `book.*` metric names clash with the parameterised topic `book.{symbol}` (`pm-msgen grep-literals` flagged them; `"book.halted"` *is* the book topic of a symbol named HALTED). | Renamed `engine.book_*` (design §8.3 updated). Checked the A5/A6 names against every parameterised topic prefix: no clash; nearest miss `log.events_in` vs `log.event.`. |
| I25 | A4 | `_handle_new_order` does not clamp the gateway id (it takes `Order.from_dict`), and an unknown id is counted before it is rejected. Keying counters by it would let any PUSH peer grow engine memory and the beacon. | `EngineMetrics.label()`: configured ids by name, anything else `(unknown)`; ≤ 64 dynamic labels without config; ids > 32 chars or non-str are unknown. Tested with 500 invented ids. |
| I26 | A4 | Reject funnel: all 37 order-flow ack builder calls (`make_ack_msg`, combo, OCO, quote) route through four `Engine._*_ack` wrappers; admin/auth acks deliberately do not. | AST test forbids direct builder calls in `engine/main.py`. Suite-wide autouse invariant (`conftest._engine_reject_count_invariant`) tallies published `accepted=False` order-flow acks per engine and compares with `metrics.rejects`; it held across all 9.7k tests. Mock publishers and perf tests are exempt (explained in code). |
| I27 | A4 | The design's book-memory formula ignored that a not-yet-compacted heap entry still holds its Order alive. | Garbage entries cost an Order + an entry. Constants measured: Order 425 B, entry 160 B, trade 330 B (stable 2k–40k orders); tracemalloc guard test at ±15 %. |
| I28 | A4 | **Perf budget is at the limit.** `test_max_tps`: −1.93 % and −2.33 % in two sessions (≈ 0.75 % of it from imports alone, visible on the unchanged base). Unmeasured by that test: ≈ 0.38 µs/message for `tick()` + dispatch timing (≈ 1 %). Cheaper variants of tick/timing saved only ≈ 50 ns: the cost is two Python method calls per message. | **Decided (Johan): sample latency 1-in-N** → I31. |
| I29 | A4 | My own suite-wide reject proxy cost 20 % in the benchmark before perf tests were exempted -- a reminder to measure with the harness out of the loop. Also: `test_max_tps` publishes acks via a pre-encoded fast path, so accepted acks never reach `_order_ack`. | Perf-marked tests skip the tally. |
| I30 | A4 | The A4.9 run-loop test initially had a dead loop (set_run_seq raised in the thread) and the beacon duly reported `loop_age_ms` ≈ 5000 -- the HUNG/DEAD signal working as designed, caught by its own test. The harness time shim also needed `perf_counter*`. | Test fixed; harness shim extended. |
| I31 | A4 | Implementing 1-in-16 latency sampling: a counter synced only on sampled messages would read short after a burst until the next sampled message -- possibly never on a quiet engine. Percentiles of a quiet window would be zeros. | `msgs_in` synced from the loop's local count on sampled messages *and* sampled maintenance passes (which run when idle); first message of every window always timed (`sample_next`). Busy % estimated per window from sampled means. Real-loop test: 100-message burst → `msgs_in` 100, 7 samples. Final: loop ≈ 230 ns/msg, `test_max_tps` −1.67 %. |
| I32 | A5 | Eleven processes (A5 + A6) need the same wiring. | `HealthReporter.start_from_compiled_config()` (for `main()`) and `tick_and_publish(samples_fn)` (one call per loop iteration). `main()` attaches only when a reporter exists, so tests that swap in dummy gateway classes are unaffected. |
| I33 | A5 | **Pre-existing bug:** `pm-ralf-gwy` and `pm-dc-gwy` never drop a client that stops reading. Slow-client and idle-timeout both only mark it close-after-flush, which needs an empty queue; the idle path also re-queues an `EXIT` line every loop pass, so the session's queue grows without bound. The design said RALF disconnects slow clients -- it does not. | Instrumented: `gwy.slow_clients` (once per session) and gauge `gwy.closing_clients`. **Fixed afterwards at Johan's request (I44).** |
| I34 | A5 | Counting HTTP and WebSocket sessions per router would touch every handler and miss future routes. | One ASGI middleware (`api_gateway/metrics.py`): requests, 5xx (incl. unhandled exceptions), open WebSockets by path→channel (closed set + `other`). Sessions count from the connection attempt, before auth. |
| I35 | A5 | Starlette's `TestClient` is unusable (needs `httpx`, not a dependency); with `from __future__ import annotations`, a FastAPI `ws: WebSocket` parameter whose type is imported inside a function is silently treated as a query param and the socket is refused. | Tests drive the ASGI app directly (as `test_tick_validation.py` does); `WebSocket` imported at module level. |
| I36 | A5 | `loop_lag_ms` is the longest gap between ticks, so it includes each loop's designed wait: engine ≤ 200 ms when idle (poll timeout), API ≈ 250 ms (health task sleep), socket gateways 5–10 ms. | Documented for B2; the DEGRADED rule (`loop_lag_ms > 1000`) tolerates all of them. A blocked API event loop (1 s) is detected (test). |
| I37 | A5 | Metric naming across gateways is uneven by design: ALF/BALF export `_global_stats` keys (`gwy.connected_clients`, `gwy.slow_client_disconnects`), RALF/DC use `gwy.clients`/`gwy.slow_clients`, MD uses `md.*`. | B3 must map to `GatewayStats` by **process name**, not by metric prefix. Noted here for B3. |
| I38 | A6 | No WP assigned the participant bots (`pm-mm-bot`, `pm-ai-swarm`) a reporter, though §7.3 and Q2 say they beacon in their own group. | Added as design task B5.4. |
| I39 | A6 | The scheduler has no loop object, but every wait already calls an `is_running()` closure on each wake-up. | Ticks there (no signature changes); `LIVENESS_CHUNK_SEC` = 1 s passed by the two callers; `WALLCLOCK_RECHECK_SEC` stays 30 s (pinned by an existing test). `sched.next_transition_in_s` = remaining wait while sleeping, 0 otherwise. |
| I40 | A6 | Scheduler engine round-trips (2 s send + 2 s confirm) can go ≈ 4 s without a tick -- under `hung_after_sec` = 5, but M030 only requires `hung_after_sec > beacon_interval_sec`. | Noted for B2 in the design; no change now. |
| I41 | A6 | Two failure counters were missing that an operator would want: stats events that failed to persist, audit frames that could not be decoded. | `stats.records_dropped`, `audit.decode_errors` (design §8.5 updated). |
| I42 | A6 | Design said pm-stats creates its reporter in `run()`. | All services attach from `main()` (as in A5): same effect, one pattern, and tests construct and run processes without reporters. |
| I43 | A6 | `log.events_in` counts frames accepted for persistence (the enqueue), not rows committed; `log.writer_queue` is the gap between them. pm-index and pm-market-sim beacon vitals only, so they call `tick()` and never publish samples. | Documented in code. |
| I44 | A5 fix | Fix for I33 in `pm-ralf-gwy` and `pm-dc-gwy`, as `pm-md-gwy` drops a slow client: slow/idle detection fires once per session; a closing session takes no further lines and is disconnected when its final line drains or after `CLOSE_GRACE_SEC` = 5 s regardless, with the cause as reason (`slow_client`, `idle_timeout`). The slow-client backlog is dropped before the `ERR` (RALF too, now; clients recover via `LASTSEQ`), keeping a half-sent line so the wire is never torn. | Unit tests with a never-reading peer for both gateways; real-loop test that a silent client gets `EXIT` then EOF; operator-guide RALF/DC sections updated. |
| I45 | review | Reporters start in `main()`, before each loop exists, so start-up work (engine GTC restore + config load, clearing retention prune, index initialise) showed as a growing `loop_age_ms`: a slow but healthy start would read HUNG, indistinguishable from a stuck one. | `health.beacon.starting` (true until the first `tick()`, derived in the sampler thread at zero hot-path cost); B2 must apply a start-up grace while `starting`. Tests added. |
| I46 | review | Reporter docstring showed the pre-A5 wiring; `start()` after `stop()` exited at once (stop event never cleared); engine-metrics comments predated 1-in-16 sampling. | Fixed (commit `5e1a2dc3`), restart covered by a test. Rest of Phase A re-checked (reject funnel, counters vs. threads, RALF/DC close logic, API middleware, service tick placement, names vs. emo commands, every `monitor` field has a consumer): no further defects. Daily trade counters are not restored on restart, so their COUNTER semantics hold for B3. |
| I47 | B1 | `ProcessHealth` has no `starting` field, so the dashboard cannot tell a process that is still starting (start-up grace) from a healthy one, although the beacon carries it. | B2.5 added: B2 decides, with the grace rule, whether `ProcessHealth` gains `starting` (spec change, cheap before C2). Resolved in B2: added. |
| I48 | B1 | Two live processes with the same `(process, instance, host)` would alternate `boot_id` and look like a restart every beacon. | A beacon from an incarnation with a lower `started_at_ns` than the current one is stale: the newer one is shown and `monitor.beacons_stale` rises. Tested. |
| I49 | B1 | The snapshot-size question (§11.1) is best answered on a live exchange, not once. A bare `pm-engine` with no deployed config gives ≈ 3.9 KB (two processes). | pm-monitor's own beacon carries `monitor.snapshot_bytes` and `monitor.snapshot_build_ms`; revisit the 5 s/delta option only if they say so (E3). |
| I50 | B1 | A new `pm-*` entry point trips the shell-completion gate (`tests/test_shell_completion.py`): the committed bash/zsh files are generated from every parser. | Regenerated with `tools/gen_completion.py`. The `pm-help` entry stays in E2.3. |
| I51 | B1 | Nothing relates `monitor.host` to `monitor.bind_address`: binding a specific non-loopback address while `host` stays `127.0.0.1` silently drops every beacon, pm-monitor's own included. | Noted for E2 (operator guide) as a possible verifier warning; no change now, the default (both loopback) is coherent. |
| I52 | B2 | The §10 exchange rule said nothing of a STOPPED engine or no engine at all (both read OPERATIONAL), nor of STOPPED processes. | DOWN when no engine runs (STOPPED or never heard of); a STOPPED process impairs only when the active profile expects it. Spec doc (`ExchangeStatus.status`) and §10 updated; table-driven test. |
| I53 | B2 | Judging MISSING from pm-monitor's first second would announce every process of a running exchange MISSING and then back; a MISSING process that starts beaconing gets a new key (it gains a host), so its recovery would not be an event. | MISSING waits one silence period after start; first sight HEALTHY is not an event; a new key looks up the hostless MISSING key for its previous state (`MISSING -> HEALTHY`). |
| I54 | B2 | `psutil.pid_exists` is not enough for DEAD: a reused PID reads SILENT, and an unreaped zombie still exists. | `process_alive` compares the process start time with `started_at_ns` (±1 s) and treats a zombie as dead. Tested with real children. |
| I55 | B2 | A roster built from every profile command would expect programs that never beacon (bots until B5.4, a console) and show them MISSING forever. | Only `BEACONING_PROCESSES` are expected; a guard test pins every built-in profile program to that set or a named exception. B5.4 must move the bots in (design B5.4 updated). |
| I56 | B2 | Sources were never forgotten: a process killed by hand stayed DEAD, and in one of the 256 slots, for the life of pm-monitor. | Sources the roster does not expect are dropped after `FORGET_AFTER_SEC` = 1 h without a beacon (`monitor.sources_forgotten`). |
| I57 | B2 | Ageing `loop_age_ms` by the time since the beacon arrived would make the scheduler's ≈ 4 s engine round-trip (I40) read HUNG at the 5 s default. | HUNG judges the value as sent (at most one interval old while beacons arrive). Start-up grace is a constant 120 s, not a config field. |
| I58 | B2 | `PROCESS_STATUS` events are B2's (B2.4), so `health.event` was adopted in B2, not B3, with a per-start `seq` until `metrics.db` exists. | `PENDING_ADOPTION` is now empty (kept as a mechanism); B4 makes the event `seq` the stored `events.seq` (design B4 note). |

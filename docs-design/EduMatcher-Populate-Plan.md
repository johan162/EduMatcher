Version: 1.0.0

Date: 2026-10-01

Status: Implementation plan for `docs-design/EduMatcher-Populate.md` v0.4.

# pm-populate — Implementation Plan

## How to use this plan

- Each work package (WP) is sized so that one developer can finish it in
  about 0.5–2 days. Each one ends in a state where the full test suite
  passes.
- **Done** lists what must exist. **Correct** lists the evidence that it
  works. A WP is closed only when both are met.
- Section numbers (§) refer to the design doc. Facts F1–F39 are in design §3.
- The project rules apply to every WP: minimal and surgical changes, no
  backwards compatibility, and no commits. Propose a commit message instead.

### Definition of Done (applies to every WP)

1. `black --check src tests`, `flake8`, `mypy src tests` and
   `pyright src tests` are clean, with no new errors.
2. `pytest -n 8` is green. The device-VM environmental failures listed in
   the project notes are the only allowed failures.
3. New code has unit tests. Each bug-class risk the WP addresses (design §17)
   has a test that fails without the change.
4. Docs touched by the behaviour are updated in the same WP: user guide,
   `pm-help` and the message reference via msgen.
5. A commit message is proposed in the WP's hand-off note.

### Dependency overview

```
WP-00 ─┐
WP-01 ─┼─ WP-02 ─ WP-03a/b/c ─ WP-04 ─┐
       │                              ├─ WP-06 ─ WP-07 ─┬─ WP-17 ─┐
WP-05 ─┴──────────────────────────────┘                 │         │
WP-08, WP-09, WP-10, WP-11 (independent; after WP-01)   │         │
WP-12 ─ WP-13 ─ WP-14 ─ WP-15                           │         │
WP-16 (after WP-01) ────────────────────────────────────┤         │
                                                        ▼         ▼
WP-18 ─ WP-19 ─ WP-20 ─ WP-21 ─ WP-22 ─ WP-23 ─ WP-24 ─ (M3: end-to-end noise flow)
WP-25 ─ WP-26 ─ WP-27 ;  WP-28 ;  WP-29 ─ WP-30 ─ WP-31 ;  WP-32 ;  WP-33
WP-34 ─ WP-35 ─ WP-36
```

### Milestones

| Milestone | Contents | What it proves |
|---|---|---|
| M1 Clock | WP-00…07 | The stack runs in sim mode with correct business dates, end to end |
| M2 Engine day + role | WP-08…16 | Day boundaries are correct; SIM gateways exist and are gated |
| M3 Driver | WP-17…24 | pm-populate drives N days of simple flow, deterministically, and always stops the stack |
| M4 Realism | WP-25…33 | Market model, news, personalities and reports |
| M5 Acceptance | WP-34…36 | Determinism, calibration on s150, docs |

---

## M1 — Sim clock foundation

### WP-00 Latency and volume probe (spike)

- **Goal**: replace the estimates in design §16 with measurements.
- **Files**: `scripts/populate_probe.py` (new; not shipped as a CLI).
- **Steps**:
  1. Start the `micro` profile plus `pm-alf-gwy` and `pm-audit`, real mode,
     on a clean data dir, with config `s10-nominal-setup`.
  2. Over one ALF session, sequentially send 10 000 alternating crossing
     LIMIT orders, each waiting for its ACK. Record per-order round-trip
     time.
  3. Over a PUSH/SUB pair, send 10 000 `book.snapshot_request` and wait for
     each `book.{SYM}` reply. This is a stand-in for the clock round trip.
  4. Measure audit log bytes and `stats.db` growth per order.
- **Done**: script committed; results table pasted into design §16 (the
  "Measured" column); O1 decided ("needed / not needed").
- **Correct**: three runs agree within 20 % on p50. Raw numbers are attached
  in the PR description.

### WP-01 Clock module

- **Files**: `src/edumatcher/models/clock.py`,
  `tests/test_clock_sim.py`.
- **Steps**: implement design §5.2 exactly: `is_sim`, `now_ns`, `now_s`,
  `now_dt`, `today`, `cadence_s`, `apply_tick`, `ClockError`, `EDU_CLOCK`
  parsing at import, and `reset_clock_for_tests(mode=…, start_ns=…)` for
  tests.
- **Done**: API present and documented in the module docstring.
- **Correct** (tests):
  - Real mode: `now_ns` is strictly increasing and within 1 s of
    `time.time_ns()`. `today()` equals `date.today()`.
  - `EDU_CLOCK=sim:1700000000000000000`: `now_ns()` ≥ start; two calls
    differ by ≥ 1; no advance across `time.sleep(0.05)`.
  - `apply_tick(t)` with `t > now` sets `now_ns() ≥ t`. `t == now` is
    accepted. `t < now` raises `ClockError`.
  - `cadence_s()` equals sim seconds in sim mode and moves with
    `time.monotonic()` in real mode.
  - `EDU_CLOCK=bogus` raises at import (run in a subprocess).
  - Thread test: 8 threads × 10 000 `now_ns()` calls during concurrent
    `apply_tick` give no duplicates.

### WP-02 Wall-clock lint guard

- **Files**: `tests/test_no_wall_clock.py`.
- **Steps**: an AST scan of `src/edumatcher/**/*.py` for calls to
  `time.time`, `time.time_ns`, `datetime.now`, `datetime.today`,
  `date.today`, `datetime.utcnow`, `time.localtime`, `time.gmtime`,
  `time.strftime`, and SQL string literals containing `'now'`. An explicit
  allowlist of `(module, function)` pairs = the O and Client rows of design
  Appendix A, each with a one-line reason.
- **Done**: the test exists. Initially it is marked `xfail(strict=True)`
  listing exactly the B/C sites still to migrate. WP-03 removes entries as
  it goes, and WP-04 removes the xfail.
- **Correct**: adding a `time.time()` call to a non-allowlisted function
  makes the test fail (demonstrated in the test via a fixture source
  string).

### WP-03a Migrate business time: engine, models, envelope

- **Files**: `engine/main.py` (`_weekly_schedule_wire`, `_restore_gtc`),
  `models/message.py` (5 index factories), `models/envelope.py::new_ulid`,
  `balf_gwy/codec.py::now_ns`.
- **Done**: these sites call `clock.*`; their allowlist and xfail entries
  are removed.
- **Correct**:
  - With `reset_clock_for_tests(sim, 2026-03-02 08:00 local)`,
    `_weekly_schedule_wire()["today"]` resolves Monday 2026-03-02.
  - `ulid_millis(new_ulid())` equals the sim ms.
  - `_restore_gtc` discards a DAY order dated the sim day before and keeps
    a GTC order.

### WP-03b Migrate business time: stats and clearing

- **Files**: `stats/main.py` (8 B sites), `clearing/store.py` (2 SQL sites
  get a `cutoff_date` param, design §6.3), `clearing/cli.py`,
  `clearing/main.py` callers.
- **Correct**:
  - Sim clock at 2026-03-02: `_on_eod` writes into the 2026-03-02
    accumulator, and an order event row has `ts` on 2026-03-02.
  - `prune_old_events(conn, cutoff_date="2026-01-01")` deletes only rows
    with `trade_date < 2026-01-01`.
  - The reconciliation guard uses the same cutoff.
  - No `'now'` remains in clearing SQL.

### WP-03c Migrate business time: index, audit, api-gwy, gateways

- **Files**: `index/main.py` (7), `audit/main.py` receipt ts,
  `api_gateway/routers/bootstrap.py`, `routers/history.py`, `events.py`,
  `ralf_gateway` trade fallback, `md_gateway::_event_ts` fallbacks.
- **Correct**: one sim-clock unit test per module asserting the produced
  timestamp equals the sim time. The full suite is green.

### WP-04 Business cadences on `cadence_s()`

- **Files**: `engine/main.py::_flush_snapshots` and
  `_flush_auction_indicative` throttles, `stats/main.py` price-snapshot
  interval, `index/main.py` publish throttle.
- **Done**: all four use `clock.cadence_s()`; the WP-02 xfail is removed (the
  test now passes strictly).
- **Correct**:
  - Sim test for stats: three trades at sim t, t+14 min and t+16 min
    produce exactly two price-snapshot rows.
  - Engine test: with no tick between, a dirty symbol is not re-published,
    whatever real time passes (patch `time.monotonic`).
  - Real mode is unchanged (existing tests pass).

### WP-05 Message specs

- **Files**: `spec/messages/system.yaml` (clock.set/tick/sync/synced), new
  `spec/messages/news.yaml` (news.publish, news.{symbol}), generated
  bindings, `docs/user-guide/270-message-reference.md`.
- **Done**: `pm-msgen check` passes, and the generated `TOPIC_CLOCK_*` /
  `TOPIC_NEWS_*` constants and `make_*` factories exist.
- **Correct**: round-trip tests (factory → decode → `from_dict`) for all six
  messages. The msgen docs test passes.

### WP-06 Engine sim mode

- **Files**: `engine/main.py`.
- **Steps**:
  1. Add the `clock.set` handler (design §5.4, steps 1–6), with rejections
     via `system.diagnostic`.
  2. Add the `clock.sync` → `clock.synced` relay and the `news.publish`
     relay (design §6.5).
  3. In sim mode, maintenance skips the snapshot, CB and indicative flushes.
  4. Re-stamp orders on new/OCO/combo in sim mode (D29).
  5. Log the startup banner.
- **Correct** (unit tests with captured `pub_sock` frames):
  - Real mode: `clock.set` produces a diagnostic and no tick, and the clock
    is unchanged.
  - Sim mode: `clock.set(t)` with one dirty symbol publishes `book.SYM`
    **before** `clock.tick` (frame order asserted).
  - Backward `clock.set` is rejected.
  - A halted symbol with `resume_at = t` resumes during `clock.set(t)`, and
    the resume event precedes the tick.
  - An order whose payload `ts_ns` is older than the sim time gets the
    engine's sim `now_ns()`.
  - `clock.sync` is relayed unchanged.
  - Invalid news (unknown kind, headline > 200 chars) is rejected with a
    diagnostic.

### WP-07 Processes follow `clock.tick`

- **Files**: `models/clock.py::follow`, plus subscription and dispatch in
  stats, clearing, audit, index, alf-gwy, balf-gwy, md-gwy, ralf-gwy, dc-gwy
  and api-gwy (design §5.3 table).
- **Correct**:
  - A unit test per process: feeding `clock.tick` advances
    `clock.now_ns()`.
  - **Integration test** (`tests/test_sim_clock_e2e.py`, marked `heavy` (the existing marker, deselected by default; run with `-m heavy`)):
    start engine, alf-gwy, stats and clearing as subprocesses with
    `EDU_CLOCK=sim:<2026-03-02 08:59>`. Send `clock.set` + PRE_OPEN →
    CONTINUOUS. Send two crossing orders over ALF, then CLOSED. Assert:
    - the trade `ts_ns` falls on 2026-03-02;
    - the stats daily row is dated 2026-03-02;
    - the clearing `trade_events.trade_date` is 2026-03-02;
    - the audit receipt timestamps are on 2026-03-02.

**M1 exit**: WP-07's integration test is green.

---

## M2 — Engine day semantics, SIMULATOR role, opctl

### WP-08 EOD at CLOSED

- **Files**: `engine/main.py` (`_handle_session_transition`, `_shutdown`),
  `spec/messages/system.yaml::eod` doc text, CHANGELOG.
- **Correct**:
  - Two simulated days in one engine process give exactly two `system.eod`
    frames, each after `session.state=CLOSED`, plus none at shutdown.
  - A shutdown mid-day (no CLOSED) gives one EOD at shutdown.
  - `sessions_enabled=false` gives one EOD at shutdown.
  - Existing clearing, stats, index and ralf EOD tests pass. A new
    clearing test feeds two EODs on consecutive sim dates and gets two EOD
    rows with the right `trade_date`.

### WP-09 Collar re-reference at PRE_OPEN

- **Files**: `engine/main.py`, `docs/user-guide/120-risk-controls.md`.
- **Correct**:
  - Reference 100.00 with a last trade at 130.00 on day 1. On day 2, after
    PRE_OPEN, a LIMIT at 150.00 is accepted (inside 130 ± 20 %); before the
    change it was rejected.
  - With no trade that day the reference stays at last-buy/last-sell.
  - The INFO log lists the change.

### WP-10 Clearing prune by clock date

This is WP-03b's SQL change seen from the operator's side.

- **Files**: `clearing/main.py`, docs (the clearing chapter's retention
  paragraph).
- **Correct**: in sim mode, at sim date D with retention 90, rows with
  `trade_date < D−90` are pruned at EOD and newer rows are kept.

### WP-11 Audit rotation 100 MB × 5

- **Files**: `audit/main.py` (named constant), docs (the audit chapter
  states the 600 MB worst case).
- **Correct**: a unit test asserts the handler's `maxBytes == 100 MiB` and
  `backupCount == 5`.

### WP-12 SIMULATOR role: model, verifier, config-gen

- **Files**: `models/participant.py`, `cverifier/layer2_schema.py`,
  `cverifier/layer3_semantic.py`, `config_gen/gateway_spec.py`,
  `config_gen/cli_parser.py`, `config_gen/builder.py` (append SIM gateways,
  skip API keys, `smp_action`), `config_gen/warnings.py` if needed.
- **Correct**:
  - `pm-config-gen … --sim-traders auto` with 150 symbols emits SIM01–SIM50,
    all with `LEAVE_ALL` and `CANCEL_RESTING`, and none in `credentials`.
  - 10 symbols gives 20 SIM gateways. `--sim-traders 0` gives none.
  - An explicit `--gateways SIM01:TRADER` collision is an error.
  - cverifier errors on a SIM gateway with `CANCEL_ALL`, with an API key, or
    in `market_maker_quotes`, and warns when the count exceeds
    `max_connections`.
  - The compiled config round-trips through `pm-config-deploy`.

### WP-13 SIMULATOR connect gate and gateway role handling

- **Files**: `engine/main.py::_handle_gateway_connect`, `alf_gwy`,
  `balf_gwy`.
- **Correct**:
  - Real mode: HELLO as SIM01 gets an auth failure with the D18 reason, and
    the engine logs a WARNING.
  - Sim mode: it is accepted.
  - QUOTE from SIM01 gets `ROLE_DENIED`. NEW from SIM01 is accepted.

### WP-14 Frontends know the role

- **Files**: `web-apps/config-gui/packages/schema/src/types.ts`,
  `defaults.ts`, the diagnostics package, and
  `web-apps/trader-gui/apps/web/src/types/index.ts`.
- **Correct**: config-gui `npm run typecheck` and vitest are green. A new
  roundtrip fixture with a SIMULATOR gateway loads and saves unchanged. The
  diagnostics rule fires on SIM + CANCEL_ALL. trader-gui typecheck is green.

### WP-15 Regenerate example configs and docs

- **Files**: everything under `docs/examples/ref_data/*-setup/`, the
  configuration chapter (roles table), `pm-help`.
- **Correct**: `pm-cverifier` passes on every example. Each example's
  gateway count matches the `auto` formula. `scripts/checkdocs.py` reports
  no new failures.

### WP-16 opctl sim support

- **Files**: `emo/cli.py`: a `processes_override` parameter on
  `start_profile`; `sim_profile(processes)` (drops `pm-scheduler`, strips
  `--verbose`, `-v` and `-vv`); `list` shows `EDU_CLOCK` when set in a
  running process's environ (read `/proc/<pid>/environ` on Linux, `ps eww`
  on macOS; best-effort); add `DATA_DIR / "populate"` to
  `NON_STATE_PATHS`.
- **Correct**:
  - Unit tests of `sim_profile` on the `default` and `mm-demo` profiles:
    the scheduler is gone, no `--verbose` remains, and `pm-mm-bot` args are
    kept.
  - `clear --all` removes `populate/`.
  - The override path starts exactly the given list (subprocess spawning
    mocked).

### WP-17 pm-mm-bot sim mode

- **Files**: `mm_bot/bot.py`, `mm_bot/pricer.py` (only the time source).
- **Steps**: implement design §8, rules 1–5.
- **Correct** (fake bus harness, as in `tests/test_mm_bot*.py`):
  - In sim mode, no quote is sent between ticks unless triggered by a
    received book, session or CB message.
  - After `clock.tick(t)` the bot sends its due requotes, then exactly one
    `clock.sync(t)`, in that order on PUSH.
  - The reissue delay is measured in sim seconds: a fill at t, with
    `reissue_delay` 5 s, requotes on the first tick ≥ t+5 s and not before.
  - A registration sync is sent once after bootstrap.
  - Real-mode tests are unchanged and green (all 414+).

**M2 exit**: everything above is green. A manual run of
`EDU_CLOCK=sim:… pm-opctl-cli start mm-demo`, followed by a few hand-sent
`clock.set` messages through a tiny script, shows `clock.synced` from MM01.

---

## M3 — pm-populate driver (noise flow only)

### WP-18 Package, CLI, entry point

- **Files**: `src/edumatcher/populate/{__init__,main,cli}.py`,
  `pyproject.toml` script, `pm_help/registry.py`.
- **Correct**: parser tests cover every validation rule in design §9.2 (exit
  code 2 and the message names the flag). `pm-populate --help` lists every
  option. The default seed is printed.

### WP-19 Calendar

- **Files**: `populate/calendar.py`.
- **Correct**:
  - `--days 5` ending on a Monday with a holiday on Friday skips Sat, Sun
    and the holiday unless `holidays:` has a schedule, in which case the
    holiday is included.
  - A weekend `sat:` schedule is included.
  - Across a DST change (use `TZ=Europe/Stockholm`, last Sunday of March),
    the 09:00 local PRE_OPEN maps to the correct UTC instant on both sides.
  - The results match the scheduler's `_seconds_until_local` math for the
    same inputs.

### WP-20 Preflight

- **Files**: `populate/preflight.py`.
- **Correct**: one test per check in design §9.3 (both failure and pass),
  using a temp data dir and fixture configs. Each failure prints its
  remedy. Warnings are emitted for an unset `reopening_random_seed`, a
  missing MM reference, retention vs span, the UTC date-split (R8) and low
  disk (R15).

### WP-21 Bus client

- **Files**: `populate/bus.py`.
- **Correct**: against an in-process fake engine (ZMQ PULL/PUB on ephemeral
  ports):
  - `clock_set` + `wait_tick` returns once the matching tick arrives.
  - Books and fills that arrive before the tick are applied to the tracker
    before `wait_tick` returns.
  - `wait_synced(K=2)` waits for both gateways.
  - A transition that gets no `session.state` times out with a
    `FatalRunError` naming both states (R20).
  - A `clock.tick` with a ts other than the one awaited is a fatal protocol
    error.

### WP-22 ALF session pool

- **Files**: `populate/alf.py`.
- **Correct**: against a fake ALF TCP server:
  - Auth success and failure are handled.
  - NEW/ACK is correlated by TAG, AMEND/AMENDED and CANCEL/CANCELLED by
    RTAG, and ERR by TAG/RTAG.
  - Stray FILL lines don't satisfy a wait.
  - A PING is sent after 10 s idle (patched clock), and a missing PONG
    aborts.
  - `RATE_LIMITED` is retried up to 3 times, then fatal.

### WP-23 Sequencer and day driver with uniform noise flow

- **Files**: `populate/sequencer.py`, `populate/intents.py` (uniform
  placeholder planner), `populate/pricing.py` (minimal cross/touch/passive
  with collar clamping).
- **Correct** (`heavy` integration test on the `micro` + alf-gwy + stats +
  clearing profile, config `s10-nominal-setup` regenerated with SIM
  gateways): `pm-populate --days 2 --avg-orders 200 --seed 1`:
  - finishes with exit 0;
  - the stats daily table has 2 days × traded symbols, dated correctly;
  - every day has a session-state sequence PRE_OPEN→…→CLOSED in clearing
    `session_events`;
  - there are 2 EOD rows;
  - zero `COLLAR_BREACH` and zero `SESSION_NOT_PERMITTED` rejects;
  - the stack is stopped afterwards (no `pm-*` processes).

### WP-24 Orchestration and cleanup

- **Files**: `populate/main.py`, `populate/stack.py`.
- **Correct**:
  - SIGINT mid-run gives exit 1, the stack stopped, and the "data is
    partial" message.
  - An injected exception in the pricer gives the same.
  - Preflight failure leaves the stack untouched and starts nothing.

**M3 exit**: running WP-23's test twice with the same seed gives identical
trade tuples. This is the early form of WP-34, before the model exists.

---

## M4 — Realism

### WP-25 Market model

- **Files**: `populate/model/market.py`.
- **Correct** (pure unit tests, seed fixed):
  - Over 10 000 simulated days, the realised annualised σ of each symbol is
    within ±10 % of the configured value.
  - The correlation of two β=1 symbols is within ±0.1 of the theoretical
    value.
  - The regime occupancy matches 25:5 within ±15 %.
  - Changing `--avg-orders` does not change any fair-value value.
  - The floor holds.
  - `fair_value.csv` in `close` mode has rows = days × symbols.

### WP-26 News: generation, scripted events, relay

- **Files**: `populate/model/news.py`, `news_templates.yaml`, use of the
  engine relay (WP-06).
- **Correct**:
  - Over 1 000 days the event rate is within its CI.
  - A rumour always resolves, and only after its event.
  - A scripted event appears at its exact time with its exact jump.
  - Adding a scripted event leaves all other events identical.
  - `news.yaml` is complete.
  - The bus payload never contains the true jump (asserted on captured
    frames).

### WP-27 News storage and API

- **Files**: `stats/main.py` (subscribe to `news.`, table `news_events`,
  migration on startup), `api_gateway/routers/history.py`
  (`GET /api/v1/history/news`).
- **Correct**: stats test: two news frames give two rows with the right
  fields. API test: filters by symbol and time range, `limit` is honoured,
  the response schema is documented in OpenAPI.

### WP-28 Volume model

- **Files**: `populate/model/volume.py`.
- **Correct**:
  - Over 500 days, the mean of `N_d` is within 2 % of `avg_orders`.
  - Timestamps are strictly increasing and all inside their windows.
  - The auction shares hold, and every active symbol has ≥ 1 buy and ≥ 1
    sell in each auction.
  - The U-shape: the ratio of first-30-min to midday-30-min counts is in
    [2.0, 3.0].
  - Bursts after news raise the symbol's next-20-min count by ≥ 2×.

### WP-29 Personalities

- **Files**: `populate/traders.py`, scenario overrides.
- **Correct**:
  - Archetype counts match the weights by largest remainder.
  - Pinned traders keep their archetype.
  - Parameters are inside archetype ranges.
  - Assignment is identical for the same seed and changes for a different
    seed.

### WP-30 Intents and pricing

- **Files**: `populate/intents.py` (replaces the placeholder),
  `populate/pricing.py`.
- **Correct**:
  - **Property test** (hypothesis is not a dependency, so use a seeded
    10 000-case loop): every resolved command passes `validate_collar()`
    and the order-limit check for the tracked state, has a price on the tick
    grid, has a valid iceberg `VISIBLE < QTY`, and is never
    MARKET/IOC/FOK outside CONTINUOUS or when halted.
  - Risk limits are never exceeded.
  - The fallback table in design §11.1 holds for every combination of
    `--order-types` and `--tifs`.

### WP-31 Cancel/amend and GTC hygiene

- **Files**: `populate/intents.py`, `populate/pricing.py`.
- **Correct**: a 20-day integration run on s10 gives end-of-run resting
  orders per symbol with median < 40 and max < 200. Cancel and amend counts
  are within ±10 % of planned.

### WP-32 Scenario YAML

- **Files**: `populate/scenario.py`.
- **Correct**: one test per validation error in design Appendix C. A valid
  full example loads.

### WP-33 Report and artefacts

- **Files**: `populate/report.py`.
- **Correct**: after WP-23's run, all files in design §14 exist. The
  report's accepted + rejected + skipped equals planned. The latency
  percentiles are non-empty. `run.yaml` reproduces the run when fed back
  as arguments.

---

## M5 — Acceptance

### WP-34 Determinism test

- **Files**: `tests/test_populate_determinism.py` (`heavy`).
- **Correct**: s10 with `reopening_random_seed` set, 1 MM bot, `--days 3
  --avg-orders 300`, seed 7, run twice on clean data dirs. Identical:
  - trade tuples (symbol, price, qty, buy gw, sell gw, ts);
  - final clearing positions;
  - final `gtc_orders.json` by (symbol, side, price, qty, gw);
  - `news.yaml`.

### WP-35 Calibration and stress acceptance (s150, default arguments)

- **Steps**: `pm-opctl-cli clear --all`; regenerate s150-nominal with SIM
  gateways; `pm-populate` with defaults (120 days, 5 000/day); with and
  without the `mm-demo` bot. Tune the archetype defaults only if the
  criteria fail.
- **Correct** (record all numbers in the design doc §16 and in a project
  note):
  1. Exit 0. The run time is recorded.
  2. Reject rate < 2 % of sent, with zero COLLAR_BREACH and zero
     SESSION_NOT_PERMITTED (pricing bugs).
  3. Every symbol with any continuous trade on a day has an opening print
     and a closing print.
  4. Close tracking error |ln(close/fair)|: median < 3 %, 90th percentile
     < 8 %.
  5. Resting orders at the end: median < 40 and max < 200 per symbol.
  6. A class-day start afterwards (`pm-opctl-cli start default`, real
     clock):
     - the engine restores the GTC orders;
     - SIM gateways can't connect;
     - trader-gui shows the price history;
     - `GET /api/v1/history/news` returns the news (the GUI pane is out of
       plan);
     - a student order can fill against a SIM GTC order and is booked in
       clearing.

### WP-36 Documentation

- **Files**: new user-guide chapter `docs/user-guide/0xx-preparing-a-class.md`
  (the instructor workflow: regenerate config → clear --all → pm-populate →
  start; troubleshooting R9, R12, R13), configuration chapter (SIMULATOR
  role, `--sim-traders`), `pm-help` entries, CHANGELOG (D25 behaviour
  change), and the design doc status set to "Implemented".
- **Correct**: `scripts/checkdocs.py` reports no new failures. Every CLI
  flag documented in the chapter exists in `--help` (scripted check).

---

## Out of plan

- The news pane in trader-gui and terminal-gui needs a separate design
  (O3).
- O1 batching is built only if WP-00 says so.

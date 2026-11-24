Version: 1.2.0

Date: 2026-11-17

Status: Design and Research Proposal

# EduMatcher — For Later ToDo

Global findings that fall outside the work package that uncovered them. They
are recorded here so they are not forgotten; each one is picked up later as
its own piece of work.

The open findings (status table below) are grouped into work packages
WP-FL01 … WP-FL21. The WP status table follows; the decisions and the WP
details are in the [Work plan](#work-plan) at the end. When a WP is done, its
findings' rows in the finding table get `Fixed (WP-FLnn)`.

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (a reply or reject on the bus, a row in a database, a
   line on a socket, a CLI's output and exit status, a rendered GUI text).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then the suites of every component the WP
   touches with `-n logical`, then black/flake8/mypy/pyright (and the web
   app's own test and type-check scripts for a GUI WP). Do not start the next
   WP with a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Engine tests use a real `Engine` (the wired-engine pattern of
`tests/test_engine_quote_entry_fill.py` and `tests/test_mm_bot_engine_wired.py`);
restart tests the pattern of `tests/test_engine_restart_contract.py`. A WP
that changes a message in `spec/` regenerates the bindings first and adds a
test on the generated model before the engine test that uses it. A
documentation-only change is "tested" by a pinned behaviour test where the
text states engine behaviour (WP-FL20), and by `mkdocs build` and the grep
checks listed in the WP.

## Work-package status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

Priority is that of the findings (highest wins); risk is the chance the
change breaks something that works today (wire, persistence or every-client
paths are High).

| # | WP | Content | Findings | Prio | Risk | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|---|---|
| 1 | WP-FL01 | The engine refuses a quote or order priced at the wrong tick scale | L032 | Med | High | Q1 | 1 d | ☑ | 2026-11-16 |
| 2 | WP-FL02 | Every gateway session can expire, and a refused gateway id costs the engine nothing | L029, L031 | Med | High | — | 1 d | ☑ | 2026-11-16 |
| 3 | WP-FL03 | An engine restart keeps ADMIN halts and announces every halt it drops | L021 | Med | High | Q2 | 1 d | ☑ | 2026-11-16 |
| 4 | WP-FL04 | A subscriber can tell whether it received the whole of an engine run | L022 | Med | High | Q3 | 1.5 d | ☑ | 2026-11-16 |
| 5 | WP-FL05 | `clearing.db` can be rebuilt from the audit trail and compared with the live ledger | L023 | Med | Med | Q4 | 1.5 d | ☑ | 2026-11-16 |
| 6 | WP-FL06 | Admin position/order queries and book requests always get a truthful answer | L030, L028 | Med | Med | Q5 | 1 d | ☑ | 2026-11-16 |
| 7 | WP-FL07 | A participant's resting orders stay reachable over BALF after a gateway restart (BALF 1.1) | L027 | Med | High | Q6, WP-FL06 | 1.5 d | ☑ | 2026-11-16 |
| 8 | WP-FL08 | pm-admin and pm-admin-cli print the engine's answer to a session transition, not TIMEOUT | L009 | Med | Low | — | 0.5 d | ☑ | 2026-11-16 |
| 9 | WP-FL09 | Every configuration loader refuses the values it cannot hold | L024 | Low | Med | — | 1 d | ☑ | 2026-11-17 |
| 10 | WP-FL10 | Engine rejection texts name the real problem; an uncross print has a defined liquidity flag | L012, L026, L037 | Low | Med | Q7 | 0.5 d | ☑ | 2026-11-17 |
| 11 | WP-FL11 | Line gateways serve past 1024 descriptors, stop with `EXIT`, and answer a half-closed client | L036, L011 | Low | Med | Q8 | 1 d | ☑ | 2026-11-17 |
| 12 | WP-FL12 | pm-api-gwy's index and sim listeners fail loudly | L033 | Low | Low | — | 0.5 d | ☑ | 2026-11-17 |
| 13 | WP-FL13 | The log-GUI live view re-subscribes after a server restart and marks lost rows | L038 | Low | Med | Q9 | 1 d | ☑ | 2026-11-17 |
| 14 | WP-FL14 | Close snapshots in `clearing.db` are pruned, the last settled date never | L019 | Low | Med | — | 0.5 d | ☑ | 2026-11-17 |
| 15 | WP-FL15 | Every topic pm-sim-forensics matches on is a declared topic | L001 | Low | Low | — | 0.5 d | ☑ | 2026-11-17 |
| 16 | WP-FL16 | CLIs behave in pipes and scripts: no `BrokenPipeError`, `health -q` exits 1, `-q` means one thing | L013, L017, L034 | Low | Low | Q10 | 1 d | ☑ | 2026-11-17 |
| 17 | WP-FL17 | pm-admin, ALF `QBOOT` and pm-orders print prices and states readably | L006, L008, L015 | Low | Low | — | 0.5 d | ☑ | 2026-11-17 |
| 18 | WP-FL18 | trader-gui: no "-0.00%", and the order-audit modal shows the index's reach | L002, L018 | Low | Low | — | 0.5 d | ☑ | 2026-11-17 |
| 19 | WP-FL19 | pm-mm-bot with `--anchor-sim` starts from the market model when the book gives no reference | L014 | Low | Low | — | 0.5 d | ☑ | 2026-11-17 |
| 20 | WP-FL20 | The books describe what the code does | L003, L007, L016, L025, L020 (interim) | Med | Low | Q11, all above | 1 d | ☑ | 2026-11-17 |
| 21 | WP-FL21 | Exchange-side corporate actions (1.x, design first) | L020 | Med | Very high | WP-FL20 | design 1 d | ☐ | |

Suggested order: **WP-FL01 → WP-FL02 → WP-FL03 → WP-FL04 → WP-FL05 →
WP-FL06 → WP-FL07 → WP-FL08 → WP-FL09 → WP-FL10 → WP-FL11 → WP-FL12 →
WP-FL13 → WP-FL14 → WP-FL15 → WP-FL16 → WP-FL17 → WP-FL18 → WP-FL19 →
WP-FL20**, then WP-FL21 for 1.x.

The Medium findings come first, the riskiest of them earliest, so they get
the longest soak in simulation runs before 1.0. WP-FL01 is first because it
is the only finding that silently puts a price on the book 100× away from
the intended one. WP-FL02 touches the connect and expiry path every client
goes through. WP-FL03 and WP-FL04 change what the engine persists or
publishes at a restart or a close. WP-FL05 adds a tool and does not touch the
live ledger, so it is safer than its priority suggests, but it repairs what
WP-FL04 detects. WP-FL06 changes the order query that WP-FL07 depends on.
WP-FL08 is Medium but small and safe. The Low WPs follow in falling risk:
WP-FL09 can refuse a configuration that loads today, WP-FL10 changes a spec
enum, WP-FL11 and WP-FL13 change I/O loops. The texts go last (WP-FL20) so
they describe the final code; its L016 part (combo guarantees, Medium) does
not depend on any other WP and may be pulled forward. WP-FL21 is a 1.x
feature: its design comes first, and 1.0 ships WP-FL20's documented
contract instead.

Estimated sequential effort for 1.0: about 17.5 days (WP-FL01 … WP-FL20),
excluding review time, simulation soak runs and findings discovered on the
way.

## Status

| ID | Date | Area | Finding | Priority | Status |
|----|------|------|---------|----------|--------|
| L001 | 2026-11-11 | sim_forensics / msgen | pm-sim-forensics hard-codes 185 topic literals and is exempt from the literal gate | Low | Fixed (WP-FL15) |
| L002 | 2026-11-11 | trader-gui | `formatChangePct` shows "-0.00%" (and "+0.00%" for zero) for a change that rounds to zero | Low | Fixed (WP-FL18) |
| L003 | 2026-11-13 | docs (operator guide, quick start, participant guide) | Container install has seven web applications (Clearing GUI on 8096), the books say six / 8090–8095 | Low | Fixed (WP-FL20) |
| L004 | 2026-11-13 | pm-config-gen | `[HINT] Validate with: poetry run python -c … Path("engine_config.yaml")` is wrong for installed users and names the wrong file | Low | Fixed (Config-Tools review WP-CFG04) |
| L005 | 2026-11-13 | pm-cverifier | Header counts `Semantic: 2 warnings` while the verdict says `1 WARNING` (the INFO M004 is counted as a warning) | Low | Fixed (Config-Tools review WP-CFG07) |
| L006 | 2026-11-13 | consoles / pm-mm-bot | Prices printed as raw floats: `149.8`, `@149.93333333333334`, `book mid=150.51999999999998` | Low | Fixed (WP-FL17) |
| L007 | 2026-11-13 | docs (operator guide, persistence) | Two diagrams say DAY combo parents are not persisted; the engine persists and restores them on a same-day restart | Low | Fixed (WP-FL20) |
| L008 | 2026-11-13 | pm-admin / pm-admin-cli | `BOOK` prints `Last trade: 150.0 × None` after an engine restart (restored price, unknown quantity) | Low | Fixed (WP-FL17) |
| L009 | 2026-11-13 | ExchangeCommandClient / pm-admin / pm-admin-cli | An illegal session transition prints `TIMEOUT`, although the engine answers on `session.transition_ack` (REST shows `409` with the reason) | Medium | Fixed (WP-FL08) |
| L010 | 2026-11-13 | pm-api-gwy | Once hung at shutdown on "Waiting for background tasks to complete"; second Ctrl-C needed (not reproduced) | Low | Fixed (API Gateway review WP-AGW01) |
| L011 | 2026-11-13 | pm-alf-gwy | A client that half-closes (`printf … \| nc`) loses the replies still on their way from the engine | Low | Fixed (WP-FL11) |
| L012 | 2026-11-13 | engine (combo/OCO validation) | `TRAILING_STOP is not supported on a combo leg: it needs trail_offset` is shown even when `LEG0.TRAIL=` was given | Low | Fixed (WP-FL10) |
| L013 | 2026-11-13 | pm-stats-cli (CLIs) | `pm-stats-cli daily \| head` ends with a `BrokenPipeError` traceback | Low | Fixed (WP-FL16) |
| L014 | 2026-11-13 | pm-mm-bot | With `--anchor-sim` the bot still needs a two-sided book or a range to start; it could start from the market model's value | Low | Fixed (WP-FL19) |
| L015 | 2026-11-13 | pm-alf-gwy / pm-orders | ALF `QBOOT` lines carry an empty `STATUS=`; `pm-orders` shows `?` in every column of a rejected order | Low | Fixed (WP-FL17) |
| L016 | 2026-11-13 | docs (participant combo guide) | Introduction promises atomic all-or-none execution for combos, although AON is an entry guard and later legs can fill independently | Medium | Fixed (WP-FL20) |
| L017 | 2026-11-13 | CLIs (`health -q`) | `health -q` exits `-1` (status 255) while the non-quiet path exits 1, in four CLIs | Low | Fixed (WP-FL16) |
| L018 | 2026-11-13 | trader-gui (admin order detail) | A 404 from the order-audit endpoint shows "No audited events for this order." without the index's reach (`indexed_through`), so an order newer than the last index build looks unknown | Low | Fixed (WP-FL18) |
| L019 | 2026-11-14 | pm-clearing (close snapshots) | `position_close_snapshot` is never pruned and keeps every flat position: one full position table per day in `clearing.db` and in every nightly backup | Low | Fixed (WP-FL14) |
| L020 | 2026-11-14 | engine / market sim / bots (corporate actions) | A split or dividend is applied to the index only; nothing adjusts the market's price, so the next trade moves the index by the split factor | Medium | Open (interim contract documented, WP-FL20; WP-FL21 for 1.x) |
| L021 | 2026-11-14 | pm-engine (halts) | Halts are not persisted: an engine restart silently clears every circuit-breaker and operator halt, so a symbol an operator halted trades again after a restart, with no resume published | Medium | Fixed (WP-FL03) |
| L022 | 2026-11-14 | pm-engine / subscribers (end of a run) | Trades lost just before an engine stop are undetectable downstream: the next run starts a new id sequence, and `system.eod` does not say which id the run ended at | Medium | Fixed (WP-FL04) |
| L023 | 2026-11-14 | pm-clearing (repair) | No way to repair `clearing.db` once a feed gap is known: nothing rebuilds the ledger from the audit trail | Medium | Fixed (WP-FL05) |
| L024 | 2026-11-14 | engine / log-server loaders | Loaders accept values they mean to refuse: `tick_decimals: true`, `outstanding_shares: true`, `max_order_qty: 1.5` (truncated to 1), `schedule: 'x'`, `log_server.enabled: 'x'`, `.nan` where `> 0` is required | Low | Fixed (WP-FL09) |
| L025 | 2026-11-14 | docs (training guide ch. 17) | Says the static collar "only takes effect from the first trades on"; the engine registers a collar only at start-up when a reference price is known | Low | Fixed (WP-FL20) |
| L026 | 2026-11-14 | pm-engine (order validation) | A TRAILING_STOP with a negative `trail_offset` and no prior trade is refused as "Trailing stop requires STOP= or a prior trade price", not as an invalid offset | Low | Fixed (WP-FL10) |
| L027 | 2026-11-14 | pm-balf-gwy (restart) | After a pm-balf-gwy restart a participant's resting orders are unreachable over BALF: no order ids, no fills, no cancel, and BALF has no order query | Medium | Fixed (WP-FL07) |
| L028 | 2026-11-14 | pm-engine (book requests) | `book.snapshot_request` for a symbol the engine holds no book for gets no answer, so a subscriber that cached the book before an engine restart cannot learn it is now empty | Low | Not a defect (WP-FL06: every configured symbol has a book from start-up) |
| L029 | 2026-11-15 | pm-engine (heartbeats) | A session that never sent a heartbeat is never expired, so a client that connects and dies (or is answered after it gave up) holds its gateway id until an admin disconnect or an engine restart | Medium | Fixed (WP-FL02) |
| L030 | 2026-11-15 | pm-engine (admin queries) | Position and order queries about a disconnected gateway answer empty lists, so `GET /admin/gateways/{id}/positions` and `/orders` show a logged-off trader with resting orders as flat with none | Medium | Fixed (WP-FL06) |
| L031 | 2026-11-15 | pm-engine (gateway connect) | A refused `gateway_connect` for an unknown id still creates a session, a metrics label and a published topic that are never freed: 337 B per refused id, reachable by any client through ALF `HELLO` | Low | Partly fixed (WP-FL02): publisher counter remains |
| L032 | 2026-11-15 | pm-engine (quotes) | `quote.new` carries `tick_decimals` but the engine ignores it, so a client with a wrong tick registry rests its quote at 1/100 or 100× the intended price without a reject | Medium | Fixed (WP-FL01) |
| L033 | 2026-11-15 | pm-api-gwy (index and sim listeners) | The `IndexClient` and `SimClient` receive threads end on a ZeroMQ error while the process keeps serving: index history and the sim/news streams then go quiet with no ERROR and no exit | Low | Fixed (WP-FL12) |
| L034 | 2026-11-15 | CLIs (`-q`) | `-q`/`--quiet` is documented as "Reduce output to warnings/errors" but sets WARNING, the default, so it changes nothing (5 entry points and pm-help's common log options) | Low | Fixed (WP-FL16) |
| L035 | 2026-11-15 | pm-dc-gwy (engine feed) | The drop-copy subscriber keeps ZeroMQ's default 1000-message RCVHWM and subscribes to every participant, so a burst for unwatched IDs drops watched fills with no log or metric | Medium | Moved to DC review WP-DCG01 (done 2026-11-15) |
| L036 | 2026-11-15 | pm-md-gwy (loop, shutdown) | Once a descriptor reaches 1024 `select` fails every pass and no client is read again (WARNING ~100/s); a stop closes every session with no `EXIT` and drops queued lines | Low | Fixed (WP-FL11) |
| L037 | 2026-11-15 | pm-engine (drop copy) | For an uncross print (`aggressor_side` AUCTION) both drop-copy events carry `liquidity_flag` MAKER, while `drop_copy.yaml` says exactly one of the two is TAKER | Low | Fixed (WP-FL10) |
| L038 | 2026-11-16 | log-gui (bridge LALF-PS uplink) | After a pm-log-srv crash and restart inside the 15 s heartbeat budget the uplink stays ACTIVE and only re-subscribes on the next renew's `UNKNOWN_SUB` (up to 15 s), and it ignores `dropped`: rows of that window are missing from the live view with no gap marker | Low | Fixed (WP-FL13) |
| L039 | 2026-11-16 | pm-engine (position/orders queries) | `system.position_request` and `order.orders_request` carry no requester: any client that can reach the engine's PUSH socket reads any participant's orders and positions | Low | Open |
| L040 | 2026-11-16 | tests (`test_monitor_e2e.py`) | Two e2e tests expect a process event's detail to end in the bare state (`-> DEAD`, `HEALTHY -> SILENT`); since `4bc205db` the detail carries a reason, so both fail | Low | Fixed |
| L041 | 2026-11-17 | pm-engine (collars) | A symbol that starts without a reference price gets no static collar until the next engine start, however long it trades (decided in WP-FL20 / Q11 for 1.x) | Low | Open |
| L042 | 2026-11-18 | pm-engine / pm-scheduler (sessions) | The engine does not report when it entered its session state, so a scheduler started after an outage that spanned a close takes yesterday's `CONTINUOUS` as today's and the day boundary never happens (Scheduler review 2026-11 §9) | Low | Fixed 2026-11-19 (`state_since` on `system.session_status`) |
| L043 | 2026-11-22 | pm-engine / msgen (inbound coercion) | The price-level orders filter rounds an off-grid price to the nearest tick, an amend's `qty` is truncated with `int()` (10.7 → 10), and the generated `from_dict` truncates float ticks (`int(10000.5)` → 10000) instead of refusing them (Models review 2026-11 §9) | Low | Open |
| L044 | 2026-11-23 | pm-engine (target-only commands) | `risk.kill_switch`, `quote.cancel` and `system.gateway_disconnect` name only the gateway they act on, so any PUSH client can cancel or disconnect any participant, and pm-admin's `KICK` reaches the audit trail as the target's own logout, unattributed and without an ack (Admin commands review 2026-11 §9) | Low | Fixed 2026-11-24 (ADMIN `risk.gateway_kick` with ack and `admin.action`; the self-service messages stay, see entry) |
| L045 | 2026-11-23 | deployment (container stop) | `stop_grace_period` is 30 s (60 s for ai-sim) while `pm-opctl-cli stop` may wait up to four 15 s waves; a slow engine stop is SIGKILLed by Docker before the recorders' wave (pm-opctl review 2026-11 §9) | Low | Open |

## L001 — Topic literals in pm-sim-forensics

**Found:** 2026-11-11, when `test_msgen_literals.py` failed (12 tests) after
commit `dad29aba` moved `sim_forensics` from `tools/` into
`src/edumatcher/sim_forensics/`.

**Finding.** The literal gate (`pm-msgen grep-literals`, enforced by
`tests/test_msgen_literals.py`) scans `src/` for topic names written as string
literals instead of the generated `TOPIC_*` constants. Once `sim_forensics`
moved under `src/`, the gate found 185 literals across 10 modules in
`sim_forensics/checks/` (`breakers`, `coverage`, `cumulative`, `derived`,
`differential`, `immediate`, `matching`, `persistence`, `quotes`,
`refusals`). Families affected: order (67), risk (28), quote (23), system
(21), book (10), circuit_breaker (10), structure (10), auction (6), trade (6),
session (4).

**Interim fix (done).** `sim_forensics` was added to `_EXEMPT_PARTS` in
`src/edumatcher/msgen/literals.py`, and to the separate path filter in
`test_trade_executed_appears_nowhere_as_a_literal`. That restores the state
before the move: under `tools/`, it was never scanned.

**Remaining risk.** The gate exists because a publisher-side topic rename is
silent for a consumer. That applies to forensics too: if `trade.executed` is
renamed, forensics checks find no matching lines and report SKIPPED or pass
on empty data, without failing.

**Options.**

1. *Migrate.* Replace the literals with the generated `TOPIC_*` constants and
   remove the exemption. Many uses are prefix matches (`"order.ack."`,
   `"circuit_breaker.halt."`) or `startswith` tuples, which have no
   ready-made constant. They need either a prefix helper in the generated
   bindings or a derived prefix (for example `TOPIC_ORDER_ACK.split("{")[0]`).
   Check that this does not conflict with the "independent of the component
   it checks" principle in `sim_forensics/__init__.py`. The constants come
   from the spec, not the producer's code, so it probably does not.
2. *Guard without migrating.* Keep the literals, and add a test asserting that
   every topic or prefix that `sim_forensics` matches on is a declared topic
   (or a prefix of one) in `spec/`. A rename then fails that test instead of
   silently emptying a check.
3. *Accept.* Leave the exemption, and rely on the forensics coverage check
   noticing missing traffic.

**Recommendation.** Option 2: it closes the silent-rename hole with one test
and leaves the 185 lines alone.

## L002 — trader-gui "-0.00%" change

**Found:** 2026-11-11, while doing clearing-GUI follow-up CG16 (no "-0.00" in
`formatPrice` / `formatSignedPrice`).

**Finding.** `trader-gui/apps/web/src/lib/formatters.ts` `formatChangePct`
signs on the unrounded value and formats with `toFixed(2)`: a change of
-0.001 % renders "-0.00%", and a flat symbol "+0.00%". Same defect class as
F20/CG16, but CG16 named only the two price formatters, so it was left alone.

**Fix.** Sign on the rounded text, as `formatSignedPrice` now does (the
private `fixed` helper in the same file), test-first:
`formatChangePct(149.9999, 150)` gives `"0.00%"`.

## L003 — "Six web applications" in the other books

**Found:** 2026-11-13, training-guide review (container route).

**Finding.** `./edumatcher.sh start` brings up seven web applications; the
seventh is the Clearing GUI (`pm-clearing-ui`) on port 8096
(`CLEARING_GUI_PORT`). The training guide is fixed. Still saying six, or
8090–8095: `operator-guide/part-1-install-and-deploy/010-installation.md`
(lines ~29, 33, 81), `operator-guide/part-3-run/010-running-the-exchange.md`
(~54), `quick-start/90-backmatter/020-when-something-does-not-work.md` (~32),
`participant-guide/part-6-front-ends/010-trading-info-terminal.md` (~163) and
`030-order-book-gui.md` (~211).

## L004 — pm-config-gen validation hint

**Found:** 2026-11-13, training guide chapter 01.

**Finding.** After writing its output, `pm-config-gen` prints
`[HINT] Validate with: poetry run python -c 'from pathlib import Path; from
edumatcher.engine.config_loader import load_engine_config; print(load_engine_config(Path("engine_config.yaml")))'`.
The command needs a Poetry checkout, and it names `engine_config.yaml` even when
`--output generated.yaml` was given. `pm-cverifier <output file>` is the
command the documentation teaches.

## L005 — pm-cverifier semantic count

**Found:** 2026-11-13, training guide chapter 01.

**Finding.** For the chapter 01 configuration the summary block says
`⚠ Semantic: 2 warnings` while the verdict says `1 WARNING, 4 ADVISORIES`; the
second "warning" is the INFO-level `M004`. The two counts should agree.

## L006 — Float formatting of prices

**Found:** 2026-11-13, training guide chapters 02–05.

**Finding.** `pm-alf-console` prints fills as `@149.8` and averages as
`@149.93333333333334`; `pm-admin BOOK` shows `149.8`; `pm-mm-bot --verbose`
logs `book mid=150.51999999999998`. Prices should be printed with the
symbol's `tick_decimals` (an average could keep more digits, but rounded).

**Update (2026-11-15).** pm-mm-bot's log lines are fixed (MM bot review
WP-MMB08: prices at `tick_decimals`, mids with one more digit); the consoles
and `pm-admin` remain.

**Update (2026-11-16).** pm-alf-console's part (fill/amend lines and the
`POS`, `POS|GW=`, `QLEGS`, `QBOOT` tables, which use `.2f` and so also
truncate 3-decimal symbols) is taken over by the ALF console review C9 /
WP-ACN06 (`docs-design/reviews/EduMatcher-ALF-Console-Review-2026-11.md`);
`pm-admin` remains.

**Update (2026-11-16, later).** WP-ACN06 done: pm-alf-console prints every
price at the symbol's `tick_decimals` (fill, amend, drop-copy and
`TRIGGERED` lines, `ORDERS`, `QLEGS`, `QBOOT`) and average costs with one
more digit (`POS`, `POS|GW=`). Only `pm-admin` remains.

## L007 — DAY combo parents in the persistence diagrams

**Found:** 2026-11-13, training guide chapter 10.

**Finding.** `operator-guide/part-6-observe-and-recover/010-persistence.md`
says in two mermaid nodes (around lines 248 and 590) that DAY combo parents
are not persisted. `Engine` saves every live combo in `gtc_combos.json`
(`engine/main.py`, the comment above `_save_combos`) and discards a DAY combo
only when its business day has passed. A same-day restart restores the
parent, and `CANCEL|COMBO_ID=` works on it (verified live).

## L008 — "Last trade: X × None"

**Found:** 2026-11-13, training guide chapters 09–10.

**Finding.** After an engine restart, `BOOK|SYM=AAPL` in `pm-admin` prints
`Last trade: 150.0 × None`: the last price is restored from
`book_stats.json`, its quantity is not. Print the price alone, or `—`.

## L009 — Console TIMEOUT for an illegal session transition

**Found:** 2026-11-13, training guide chapter 25 (first noted as Q14 in the
2026-11-06 review).

**Finding.** `SESSION|STATE=CONTINUOUS` while already `CONTINUOUS` makes
`pm-admin` (and `pm-admin-cli session`) wait three seconds and print
`TIMEOUT  No ack with prefix 'session.state'`. The engine does answer:
`POST /api/v1/admin/session/transition` gets `409 TRANSITION_REJECTED`,
`Invalid transition CONTINUOUS → CONTINUOUS (allowed: CLOSED,
CLOSING_AUCTION)`. `ExchangeCommandClient.session_advance` sends the
transition without `command_id`/`gateway_id` and waits only for the public
`session.state` broadcast; it should request the
`session.transition_ack.<gateway_id>` reply as the API gateway does, and the
console and CLI should print the engine's reason. The training guide
(chapters 01, 06) documents the current `TIMEOUT`.

## L010 — pm-api-gwy shutdown hang

**Found:** 2026-11-13, training guide chapter 25.

**Finding.** After a session with REST calls, two WebSocket clients and
several refused admin calls (`ENGINE_AUTH`), `Ctrl-C` on `pm-api-gwy`
stopped at uvicorn's "Waiting for background tasks to complete" for over a
minute; a second `Ctrl-C` ended it with a `CancelledError` traceback from a
`receive_queue.get()`. Three later attempts shut down cleanly. While it hung,
the IDs it held stayed connected in the engine. A
`timeout_graceful_shutdown` on `uvicorn.run` would bound it.

**Fixed** (2026-11-15, API Gateway review H2, WP-AGW01). Reproduced: a
`/ws/private` or admin socket the client had closed kept its handler waiting
for the next event, and uvicorn's graceful shutdown waited for that handler.
The handlers now end when the client closes, and `uvicorn.run` gets
`timeout_graceful_shutdown=5` as a backstop.

## L011 — ALF replies lost on half-close

**Found:** 2026-11-13, training guide chapter 27.

**Finding.** `printf 'HELLO…\nSYMBOLS\nEXIT\n' | nc 127.0.0.1 5565` (ncat)
prints nothing: `nc` half-closes the socket at the end of its input, the
gateway treats that as a disconnect and drops whatever is still queued or
on its way from the engine. Since 2026-11-13 lines sent behind `HELLO` are
held until the logon completes, so the remaining gap is the half-close. The
guide now tells scripts to wait (`sleep 1`) before `EXIT`.

## L012 — Misleading combo/OCO leg rejection text

**Found:** 2026-11-13, training guide chapter 10.

**Finding.** `LEG0.TYPE=TRAILING_STOP|LEG0.TRAIL=1.00` answers
`COMBO REJ … Leg 0: TRAILING_STOP is not supported on a combo leg: it needs
trail_offset`; `ICEBERG` says `… it needs visible_qty`. The leg type is
refused outright, so "it needs …" reads as if adding the field would help.
Say only that the type is not supported on a combo (or OCO) leg.

## L013 — BrokenPipeError from CLIs in a pipe

**Found:** 2026-11-13, training guide chapter 15.

**Finding.** `pm-stats-cli daily | head -6` prints the rows and then a
`BrokenPipeError: [Errno 32] Broken pipe` traceback from `_render_table`.
Other table-printing CLIs probably share it. Handle `BrokenPipeError` in the
entry points (or reset `SIGPIPE` to the default).

## L014 — pm-mm-bot start-up reference with --anchor-sim

**Found:** 2026-11-13, training guide chapter 14.

**Finding.** Since 2026-11-13 the bot asks for each symbol's book at
start-up, so a restarted `MM01 --all-symbols` found a reference for 148 of
150 symbols (it found 9 before). The other two had an empty or one-sided
book. With `--anchor-sim` the bot already receives the market model's value
for every symbol; it could use that value as the start-up reference when
the book gives none.

## L015 — Cosmetic gaps in QBOOT and pm-orders

**Found:** 2026-11-13, training guide chapters 18 and 27.

**Finding.** Over ALF, `QBOOT` lists an active quote as
`QUOTE|QUOTE_ID=…|…|ASK_QTY=500|STATUS=` — the status is empty (the
console's `QBOOT` table shows `ACTIVE`). `pm-orders` shows a row with `?` in
every column for an order the engine rejected (the rejection carries only the
order ID); it could show `REJECTED` with the reason instead.

## L016 — Combo guide overstates atomic execution

**Found:** 2026-11-13, WP-ENG09 flow review.

**Finding.** The opening of `docs/books/participant-guide/part-2-orders/030-combo-and-oco-orders.md`
claims that if all legs cannot fill, none fill, and presents simultaneous
atomic execution as a combo guarantee. The engine's AON preflight only guards
entry; legs that rest can subsequently fill independently, while non-AON
combos can fill partially. Review the guide's examples and guarantees against
the actual combo contract so participants are not misled about leg risk.


## L017 — `health -q` exits -1

**Found:** 2026-11-13, pm-audit / pm-audit-cli review
(`docs-design/reviews/EduMatcher-Audit-Review-2026-11.md` §9).

**Finding.** `health -q` raises `SystemExit(0 if healthy else -1)`, which the
shell sees as status 255, while the same command without `-q` exits 1 when
unhealthy. The help text says "exit 0 when healthy or -1 otherwise". The
pattern is in `audit/cli.py:1042`, `clearing/cli.py:945`, `index/cli.py:825`
and `stats/cli.py:743`. A script that tests `$? -eq 1` behaves differently
with and without `-q`.

**Recommendation.** Exit 1 in both modes and fix the four help texts; check
the operator guide's health chapter and any container healthcheck that
compares the status.

## L018 — trader-gui hides how far the audit index reaches

**Found:** 2026-11-13, WP-AUD05 of the pm-audit review
(`docs-design/reviews/EduMatcher-Audit-Review-2026-11.md`).

**Finding.** `GET /admin/orders/{order_id}/audit` now returns
`indexed_through` and names it in the 404 message, because the audit index
is built by hand and an order newer than the build is not in it yet.
`web-apps/trader-gui/apps/web/src/components/admin/AdminOrderDetailModal.tsx`
prints its own text on a 404 ("No audited events for this order.") and
ignores the field on a 200, so an operator cannot tell "not indexed yet"
from "no such order".

**Recommendation.** Show the 404's message (or `indexed_through`) in the
modal, and add `indexed_through` to the type in `src/types/index.ts`.

## L019 — Close snapshots grow without bound

**Found:** 2026-11-14, pm-eod review
(`docs-design/reviews/EduMatcher-EOD-Review-2026-11.md` §9, P2).

**Finding.** `write_close_snapshot` copies every row of
`gateway_symbol_positions`, flat positions included, under each closed
date, and nothing ever deletes old dates. In the simulation that is about
10 000 rows a day (3.6 M a year), all of it in `clearing.db` and therefore
in every nightly `pm-eod` backup. pm-eod needs only the snapshot of the last
settled date (today it re-reads it as the next baseline).

**Recommendation.** After the pm-eod review's WP-EOD01 stores the settled
equity in `eod.db`, give pm-clearing a snapshot retention (for example the
same `--retention-days` as `trade_events`, but never the latest settled
date) and document it next to the other retention rules.

## L020 — Corporate actions exist only in pm-index

**Found:** 2026-11-14, pm-index review
(`docs-design/reviews/EduMatcher-Index-Review-2026-11.md`, C3 and Q1).

**Finding.** `pm-index-admin-cli split`/`dividend` adjust pm-index's view of
a constituent (shares and price for a split, price for a dividend) and keep
the index level through the divisor. The engine, pm-market-sim and pm-mm-bot
have no corporate actions, so the constituent keeps trading at the old
price and the next print replaces the adjusted one: a 2:1 split moved a
two-name index from 1000 to 1500 on the next trade, a 10.00 dividend to
1052.6.

**Interim.** The review recommends (Q1) documenting the contract for 1.0:
the action models the index side of an ex-date, and the operator makes the
constituent trade at the adjusted price.

**Recommendation for 1.x.** An exchange-side corporate action: one command
that adjusts the instrument's reference prices, resting order prices and
quantities (or cancels them, as many venues do on an ex-date), the bots'
anchors, and pm-index, at a session boundary.

## L021 — An engine restart clears every halt

**Found:** 2026-11-14, pm-md-gwy review
(`docs-design/reviews/EduMatcher-MD-Gateway-Review-2026-11.md`, C2).

**Finding.** `_halted_symbols` and the breakers' halted state live only in
the engine's memory (`engine/main.py:3743`, `:4990`, `:5150` set them;
`engine/persistence.py` has no halt state). After a restart every symbol is
tradable again, including one an operator halted on purpose (an ADMIN halt
is meant to outlast the close, `engine/main.py:2654`), and no
`circuit_breaker.resume` is published, so subscribers that cached the halt
(pm-md-gwy until its WP-MDG02, the GUIs) keep showing it.

**Recommendation.** Decide whether an ADMIN halt should survive a restart.
If yes, persist it with the books and restore it at start-up; if no, say so
in the operator guide's restart section and publish a resume for each halt
the restart dropped, so every cache clears.

## L022 — Nobody can tell that the end of an engine run was lost

**Found:** 2026-11-14, pm-clearing review
(`docs-design/reviews/EduMatcher-Clearing-Review-2026-11.md`, H2 and §9).

**Finding.** Trade ids are `{run_seq}-{seq}` and `seq` restarts at 1 every
run, so a subscriber detects a lost trade only when a later trade of the
*same* run arrives (`clearing/main.py:625-674`). Trades lost just before an
engine stop (a slow subscriber, a full high-water mark, a subscriber down at
the time) are followed by the next run's first trade and look like a clean
run boundary. `system.eod` (`engine/main.py:7463-7468`) carries the closing
books, not the run's last trade id.

**Recommendation.** Put the run's last trade id (or trade count) on
`system.eod` and on the engine's session-status reply, so pm-clearing,
pm-stats and pm-audit can check a run is complete at its end and after
their own restarts.

## L023 — No repair once a clearing gap is known

**Found:** 2026-11-14, pm-clearing review
(`docs-design/reviews/EduMatcher-Clearing-Review-2026-11.md`, Q1 (b)).

**Finding.** After the review's WP-CLR02, a trade pm-clearing never received
is reported as a `GAP`, but positions and P&L stay without it. Applying the
missing trades late is not equivalent: average cost and realised P&L depend
on order. pm-audit holds every `trade.executed`, with its `msg_id`.

**Recommendation.** A `pm-clearing-cli rebuild --from-audit` (or a
`pm-audit-replay` target) that replays the retained `trade.executed` stream
in order into a fresh `clearing.db`, keeping the close snapshots pm-eod
already settled from, and reports the difference against the live ledger.

## L024 — Loaders accept values they mean to refuse

**Found:** 2026-11-14, pm-cverifier / pm-config-gen review
(`docs-design/reviews/EduMatcher-Config-Tools-Review-2026-11.md`, §9).

**Finding.** A differential harness (one YAML leaf replaced at a time,
verifier versus the loaders `compile_config` runs) found values the loaders
accept although the field cannot hold them:

- `engine/config_loader.py`: `tick_decimals: true` and
  `outstanding_shares: true` (a bool is read as 1);
  `order_limits.max_order_qty: 1.5` is truncated to 1; `schedule: 'x'` or
  `schedule: 0` is treated as absent; `snapshot_interval_sec: .nan` passes
  the `<= 0` check, and the engine then never publishes a book snapshot
  (`engine/main.py:1154`).
- `log_srv/config.py`: `enabled: 'x'`, `pubsub_enabled: 'x'`, and a number
  for `name`, `bind_address` or `db_path`.
- `balf_gwy/config.py:106`, `alf_gwy/config.py:82`,
  `api_gateway/config.py:238`: `enabled` is read with `bool()`, so
  `enabled: "false"` is true (added 2026-11-14 by the pm-balf-gwy review,
  `docs-design/reviews/EduMatcher-BALF-Gateway-Review-2026-11.md`, §9).

pm-cverifier refuses all of these, so a file that goes through
`pm-config-deploy` is safe; any other caller of the loaders is not.

**Recommendation.** Make the loaders refuse bools for integer fields,
non-integral floats for counts, non-mapping `schedule`, non-bool flags and
non-finite numbers (`math.isfinite`), with a test per field.

## L025 — When a collar without a reference price takes effect

**Found:** 2026-11-14, pm-cverifier / pm-config-gen review, WP-CFG09
(`docs-design/reviews/EduMatcher-Config-Tools-Review-2026-11.md`).

**Finding.** `training-guide/170-capstone-scenario.md` (Exercise 2) says the
books have no price until the market makers quote, "so the static collar only
takes effect from the first trades on". The engine registers a symbol's collar
only while it starts (`engine/main.py:1402-1416`, the only writer of
`self._collars`), and only when the book then has a last price, from the
config or from a previous run's persisted book stats. A collar without a
reference price therefore applies from the next engine start after the first
trades, not from the first trades.

**Recommendation.** Either reword the chapter, or (a design decision) let the
engine arm a symbol's collar when its first reference price becomes known.

## L026 — A negative trailing offset is reported as a missing price

**Found:** 2026-11-14, pm-balf-gwy review
(`docs-design/reviews/EduMatcher-BALF-Gateway-Review-2026-11.md`, §9).

**Finding.** A TRAILING_STOP with `trail_offset = -1.00` on a symbol with no
trade yet, sent through pm-balf-gwy to a real engine, is refused with
"Trailing stop requires STOP= or a prior trade price". The engine checks for
a reference price before it checks the offset's sign, so the client is told
to add a price when the offset is what is wrong.

**Recommendation.** Validate the offset (`> 0`) before the reference-price
rule, with `reject_code` `INVALID_VALUE`.

## L027 — Resting orders are unreachable over BALF after a gateway restart

**Found:** 2026-11-14, pm-balf-gwy review
(`docs-design/reviews/EduMatcher-BALF-Gateway-Review-2026-11.md`, H1 and Q1).

**Finding.** BALF order ids and the map from engine order ids live in the
pm-balf-gwy process. WP-BALF01 keeps them across reconnects of one gateway
ID, but a gateway restart loses them: a participant whose
`disconnect_behaviour` leaves orders on the book receives no
`EXECUTION_REPORT` for them afterwards and cannot cancel them over BALF,
which has no order query.

**Recommendation.** At logon, adopt the gateway ID's live orders with
`order.orders_request` and give them fresh BALF ids; send the client's
`client_order_id` as `client_tag` on `order.new` so it can be restored. The
client also needs a way to learn the adopted ids (a new server message, or an
`EXECUTION_REPORT`-like status frame): a protocol change for BALF 1.1.

## L028 — No answer to a book request for a symbol without a book

**Found:** 2026-11-14, pm-md-gwy review WP-MDG02
(`docs-design/reviews/EduMatcher-MD-Gateway-Review-2026-11.md`).

**Finding.** `_handle_book_snapshot_request` (`engine/main.py:2850-2856`)
answers only when `symbol in self.books`, and books are created on a
symbol's first order (`_book`, `:1077`). After an engine restart that
restored no orders for a symbol, pm-md-gwy's request for its book gets no
answer, so the gateway keeps the `TOP`/`DEPTH` it cached before the restart
until the symbol's first order. pm-board, pm-market-sim and pm-ai-trader send
the same request and have the same blind spot.

**Recommendation.** Answer with an empty book for a configured symbol that
has no book yet.

## L029 — A session that never heartbeated never expires

**Found:** 2026-11-15, pm-api-gwy review H3
(`docs-design/reviews/EduMatcher-API-Gateway-Review-2026-11.md`).

**Finding.** `_expire_silent_gateways` skips every session with
`heartbeat_interval_sec <= 0` (`engine/main.py:4550`), and the interval is
set only by the first `system.gateway_heartbeat`. A client that is accepted
and then dies, or stops listening, before its first beat keeps its gateway
id connected for good: every later `gateway_connect` for that id is refused
"Gateway already connected" until an ADMIN disconnects it or the engine
restarts. The review reproduced it through pm-api-gwy (an accept that
arrived after its 3 s auth timeout): refused for over 240 s with no end in
sight. WP-AGW02 removes that REST path; ALF, BALF and the bots can still
reach the state.

**Recommendation.** Start the silence clock at connect, with the default
`GATEWAY_HEARTBEAT_INTERVAL_SEC` as the interval until the first beat says
otherwise.

## L030 — Admin queries about a disconnected gateway answer "nothing"

**Found:** 2026-11-15, pm-api-gwy review §9
(`docs-design/reviews/EduMatcher-API-Gateway-Review-2026-11.md`).

**Finding.** `_handle_position_request` (`engine/main.py:2622-2625`) and
`_handle_orders_request` (`:2861-2864`) answer an empty list when the gateway
named in the request is not connected. That id is both "who asks" and "about
whom", so an ADMIN asking about a logged-off participant gets `[]`.
`GET /admin/gateways/{id}/positions` and `GET /admin/gateways/{id}/orders`
then show a trader with GTC orders and a position as flat with no orders, in
a `200`.

**Recommendation.** Give the admin queries a requester field separate from
the target, as `risk.kill_switch_gateway` already has, and answer an ADMIN
about any configured gateway, connected or not.

**Update (2026-11-16).** pm-alf-console's `POS|GW=<id>` shows the same
answer to anyone: an offline market maker, or a mistyped id (one that no
participant has), prints `<id>: flat (no open positions).`
(`_handle_position_request`, `engine/main.py:2649-2651`). Found in the ALF
console review §9. The reply should tell "unknown id" and "not connected"
apart from "flat".

## L031 — An unknown gateway id costs the engine memory for good

**Found:** 2026-11-15, messaging layer review §9
(`docs-design/reviews/EduMatcher-Messaging-Review-2026-11.md`).

**Finding.** Any client can send an ALF `HELLO` with a made-up gateway id;
pm-alf-gwy forwards it as `system.gateway_connect`
(`alf_gwy/gateway.py:997-1004`). `_handle_gateway_connect`
(`engine/main.py:2786`) calls `_session_for_gateway`, which creates and keeps
a `ParticipantSession`, and counts a per-gateway metric, *before* the
allowlist check at `:2813` refuses the id. The refusal is published on the
new topic `system.gateway_auth.<id>`, so `SequencedPublisher._seq` and every
subscriber's per-topic sequence state gain an entry too. Measured with the
real engine: 50 000 refused ids leave 50 000 sessions and 50 007 publisher
topics, 337 B per refused id (16.8 MB); 136 B of each is the publisher's
counter.

**Recommendation.** Check the allowlist before `_session_for_gateway` and
before counting the per-gateway metric. The publisher's per-topic counter
cannot be dropped without breaking gap detection, so the remaining growth
(one counter per refused id) is best removed by having the gateways refuse
ids that are not configured participants before forwarding.

**Update (2026-11-16, WP-FL02).** The engine now refuses an unknown id before
it creates a session, and a `gateway_disconnect` for one creates nothing. What
remains per refused id is the publisher's sequence counter for
`system.gateway_auth.<id>` (136 B); removing it needs the gateways to refuse
ids that are not configured participants before forwarding.

## L032 — The engine ignores a quote's `tick_decimals`

**Found:** 2026-11-15, pm-mm-bot review §9
(`docs-design/reviews/EduMatcher-MM-Bot-Review-2026-11.md`).

**Finding.** `_handle_quote_new` reads `bid_price_ticks`/`ask_price_ticks`
as integers (`engine/main.py:4121-4141`) and never compares the payload's
`tick_decimals` with the symbol's configured value. A client that converted
with the wrong scale (pm-mm-bot does when its symbols reply times out and the
tick registry falls back to 2 decimals, review C5) rests a quote at 1/100 or
100× the intended price, and nothing refuses it. The order paths that carry
`tick_decimals` may share the gap.

**Recommendation.** Reject a `quote.new` (and any order) whose
`tick_decimals` differs from the symbol's, with a reason naming both values.

## L033 — pm-api-gwy's index and sim listeners die silently

**Found:** 2026-11-15, API gateway review WP-AGW06
(`docs-design/reviews/EduMatcher-API-Gateway-Review-2026-11.md`, C5).

**Finding.** WP-AGW06 made a dead engine receive thread log at ERROR and
stop pm-api-gwy with exit status 1. `IndexClient._receive_loop`
(`api_gateway/index_client.py`) and `SimClient._receive_loop`
(`api_gateway/sim_client.py`) have the same shape as the old engine loop: a
non-EINTR `ZMQError` ends the thread and the process keeps serving.
`/history/index-events` then answers only with timeouts, and the admin sim
and news streams go silent, with nothing in the log.

**Recommendation.** Give both the engine listener's handling: log the
failure at ERROR and report it through the same `on_listener_failure` path,
or at least count it in the health beacon.

## L034 — `-q` is the default

**Found:** 2026-11-15, pm-mm-bot review D3
(`docs-design/reviews/EduMatcher-MM-Bot-Review-2026-11.md`).

**Finding.** Most `pm-*` processes configure logging with
`elif quiet: level = logging.WARNING` followed by `else: level =
logging.WARNING`, so `-q` selects the level that is already the default,
while the help text says "Reduce output to warnings/errors". Five entry points and pm-help's common log options
still carry that text (`ai_trader/main.py`, `alf_console/main.py`, `api_gateway/main.py`, `audit/main.py`, `market_sim/main.py`, `pm_help/registry.py`);
pm-mm-bot's was reworded to "Explicit WARNING log level (the default)" in
WP-MMB08, matching the reference manual's wording for another tool ("Explicit
`WARNING` (same as the default)").

**Recommendation.** Decide once for every process: either `-q` means ERROR,
or the help says it is the default. Change all entry points together so the
flag means the same everywhere.

## L035 — pm-dc-gwy drops engine bursts silently

**Found:** 2026-11-15, pm-ralf-gwy review H2
(`docs-design/reviews/EduMatcher-RALF-Gateway-Review-2026-11.md`).

**Finding.** `dc_gateway/gateway.py:121` creates its drop-copy subscriber
with `make_subscriber(config.drop_copy_pub_addr)`: no `rcvhwm`, so ZeroMQ's
default of 1000 messages applies, and past it a SUB socket drops without a
trace; nothing counts or logs a drop.

**Correction and status (2026-11-15).** The first version of this entry said
DC1 `SEQ` stays dense after a loss. It does not: `SEQ` is the engine's
per-participant counter, passed through, so the client sees the gap (at its
next fill). The pm-dc-gwy review found the subscriber is also subscribed to
every participant, so unwatched traffic causes the loss (857 of 2 001 watched
fills lost in its repro). Taken over by
`docs-design/reviews/EduMatcher-DC-Gateway-Review-2026-11.md` H1 /
WP-DCG01.

**Recommendation.** The same fix as WP-RALF02: `rcvhwm=100_000` and the
pm-md-gwy bus-sequence check with a `gwy.bus_gaps` counter and a latched
WARNING.

## L036 — pm-md-gwy: select limit and silent stop

**Found:** 2026-11-15, pm-ralf-gwy review C5 and C7
(`docs-design/reviews/EduMatcher-RALF-Gateway-Review-2026-11.md`).

**Finding.** Both gateways read clients with `select.select` and catch the
`ValueError` it raises for a descriptor of 1024 or more
(`md_gateway/gateway.py:364-369`, `dc_gateway/gateway.py:233-238`). The pass
then returns without reading anyone, every pass: no client is served and the
WARNING repeats about 100 times a second (reproduced in pm-ralf-gwy, which has
the same code). Their `close()` closes every session without a final line,
so a planned stop looks like a crash to clients and queued lines are lost.

**Recommendation.** Port WP-RALF04 (`select.poll`, `EXIT|REASON=shutdown`
with a bounded flush) so the three line gateways stay alike. pm-dc-gwy's share
is now WP-DCG03 of the DC gateway review (2026-11-15), and pm-ralf-gwy's is
WP-RALF04 (done 2026-11-15); this entry remains for pm-md-gwy. The code to
copy is `_read_client_data` and `_flush_for_shutdown` in either.

## L037 — Uncross prints have no TAKER in drop copy

**Found:** 2026-11-15, pm-dc-gwy review §9
(`docs-design/reviews/EduMatcher-DC-Gateway-Review-2026-11.md`).

**Finding.** `engine/main.py:3510-3517` sets each side's drop-copy
`liquidity_flag` to TAKER when that side equals `trade.aggressor_side`. An
uncross print has `aggressor_side` AUCTION, so both events are MAKER.
`spec/messages/drop_copy.yaml` (`liquidity_flag`) says "Exactly one of the two
events a trade produces is TAKER". A fee or rebate computed from the flag
treats both auction counterparties as liquidity providers.

**Recommendation.** Decide what an auction fill is (a third value such as
AUCTION, or MAKER for both, documented) and make the spec and the engine
agree.

## L038 — log-GUI live view gaps after a server restart

**Found:** 2026-11-16, pm-log-srv/logclient review §9
(`docs-design/reviews/EduMatcher-Log-Server-Review-2026-11.md`).

**Finding.** `web-apps/log-gui/apps/bridge/src/lalf-ps-uplink.ts:247-253`
re-sends `log.subscribe` on `log.server_state` `UP` only when the uplink is
not ACTIVE. A clean server stop publishes `DOWN` first, so that case works.
After a crash (no `DOWN`) and a restart within the uplink's 15-second
heartbeat budget, the uplink stays ACTIVE; the new server has no
subscription, so nothing arrives until the next `log.renew` gets
`UNKNOWN_SUB` (up to `renew_before_sec`, 15 s by default). The rows of that
window never reach the live view. The uplink also ignores `dropped` in
`log.event`, so neither this gap nor a slow-subscriber loss is shown.

**Recommendation.** Give `log.server_state` an identity that changes on
every server start (a start time or random instance id; `last_seq` does not
change, because `seq` continues across restarts), re-subscribe when it
changes, and show a gap
marker in the live view when `dropped` (or the per-subscription message
counter planned in the review's Q5) says rows were lost; the view can then
offer a re-read from `log.db`.

## L039 — Position and order queries carry no requester

**Found:** 2026-11-16, WP-FL06.

**Finding.** `system.position_request` and `order.orders_request` name only
the gateway asked about, which is also the reply topic. The engine checks
nothing about who sent the request, so any client that can reach the engine's
PUSH socket (port 5555) reads any participant's resting orders and positions.
pm-alf-gwy and pm-api-gwy only ask about their own session's gateway for
orders; positions are open to everyone by design (`POS|GW=`).

**Recommendation.** Decide whether orders of another participant are
confidential. If they are, add a requester field (as `risk.kill_switch_gateway`
has) and answer another gateway's orders only to an ADMIN requester; the PUSH
socket's reach (internal network) is the other half of the answer.

## L040 — Monitor e2e tests expect the old event wording

**Found:** 2026-11-16, `make test-e2e` after WP-FL01…08 (not caused by them).

**Finding.** `4bc205db` (pm-monitor: explain and calibrate DEGRADED) appends a
reason to a process event's detail, e.g. `HEALTHY -> SILENT: no beacon for
7.0 s, process runs`. `tests/test_monitor_e2e.py::test_a_stopped_process_goes_silent_and_comes_back`
compares the detail with `HEALTHY -> SILENT`, and
`test_a_killed_engine_is_dead_the_exchange_down_and_a_restart_shows` waits for
a detail that `endswith("-> DEAD")`, so both fail (the second after its 20 s
wait). The e2e suite is not part of the normal run, which is why the commit
passed.

**Recommendation.** Match the transition part (`detail.split(":")[0]`) in both
tests, and keep asserting that a reason is present.

**Fixed 2026-11-17.** Both tests compare the transition part
(`detail.split(":")[0]`) and assert the reason: `, process runs` on the SILENT
event, `, process gone` on the DEAD one, none on `SILENT -> HEALTHY`.
`tests/test_monitor_e2e.py`: 14 passed.

## L041 — Arm a collar when the first reference price is known

**Found:** 2026-11-17, WP-FL20 (Q11, from L025).

**Finding.** The engine registers a symbol's static collar only at start-up,
and only when the book then has a last price (from the configuration or the
previous run's `book_stats.json`, `engine/main.py`, the only writer of
`self._collars`). A symbol configured without a reference price trades
without a collar for the whole run, and gets one at the next engine start.
For 1.0 the training guide (ch. 17) now says so (Q11 (a)).

**Recommendation (1.x).** Register the collar when the symbol's first
reference price becomes known (its first trade, or an opening auction
print), with the static band around that price; a test on a wired engine
that the second order after the first trade is collared.


## L042 — Report the trading date of the engine's session state

**Found:** 2026-11-18, pm-scheduler review (`reviews/EduMatcher-Scheduler-Review-2026-11.md` §9).

**Finding.** `system.session_status` carries the engine's current session
state but not when it was entered. pm-scheduler's start-up catch-up
(`scheduler/main.py` `_plan_catch_up`) accepts any state on today's path as
today's. An engine left in `CONTINUOUS` (or `CLOSING_AUCTION`) by a day that
never closed, found by a scheduler started during the next day's trading
hours, is therefore left there: the previous day's `DAY` orders keep
resting, no archive runs, the daily counters are not reset and no opening
auction happens. A `--daily` scheduler that stays up routes such an engine
to `CLOSED` at midnight, so only a scheduler outage across the close
exposes it.

**Recommendation (1.x).** Add the session-local trading date of the last
applied transition to `system.session_status`; pm-scheduler treats a state
entered on an earlier date as off-path and routes it through `CLOSED`. Test
on a wired engine: state set "yesterday", scheduler started at 10:00 →
`CLOSED`, `PRE_OPEN`, `OPENING_AUCTION`, `CONTINUOUS`.

**Fixed (2026-11-19).** `system.session_status` carries `state_since`, the
UTC instant the engine entered its state (its start for the boot state); a
wall instant rather than a trading date, so a compressed-clock scheduler can
compare it with its own day. At start-up pm-scheduler treats a non-`CLOSED`
state entered before its day began as left over (`_left_over`) and
`_plan_catch_up` closes it by the shortest legal route before planning the
day from `CLOSED`. Tests: `test_scheduler_reconcile.py` (planner, boundary)
and `test_scheduler_closed_loop.py` (wired engine, the scenario above).

---

## L043 — Refuse, do not round, off-grid admin filters, fractional amend quantities and float ticks

**Found:** 2026-11-22, shared models review (`reviews/EduMatcher-Models-Review-2026-11.md` §9).

**Finding.** Three inbound paths turn a wrong value into a different valid
one instead of refusing it:

- `Engine._handle_price_level_orders_request` converts the optional `price`
  filter with nearest-tick `to_ticks` (`engine/main.py:3130-3132`), so an
  off-grid `100.005` silently shows the 100.00 or 100.01 level.
- `Engine._handle_amend` coerces `qty` with `int()` (`engine/main.py:7349-7353`),
  so `10.7` amends to 10 and is acknowledged.
- The generated `from_dict` of every tick-carrying message coerces with
  `int()` (`models/generated/order.py:97`), so a producer that computes
  `10000.5` ticks publishes 10000 without an error. In-house producers
  compute integers today, so this is latent.

**Recommendation.** The filter uses `to_ticks_exact` and answers a
`TickViolation` with `rejected=True`; the amend refuses a non-integer `qty`
with `INVALID_VALUE`; the msgen coercion for `int` fields refuses a float
with a fractional part (`MessageValidationError`). Tests: one per path,
sending the off-grid or fractional value and expecting a refusal.


## L044 — Target-only commands carry no requester; KICK is unattributed

**Found:** 2026-11-23, pm-admin/pm-admin-cli review
(`reviews/EduMatcher-Admin-Commands-Review-2026-11.md` §9).

**Finding.** `risk.kill_switch`, `quote.cancel` and
`system.gateway_disconnect` carry one id: the gateway they act on, which is
also the reply topic. The engine cannot tell the participant from any other
client on the PUSH socket (port 5555), so anyone who reaches it can cancel
another participant's orders and quotes or end its session. pm-admin's `KICK`
uses `system.gateway_disconnect` with the target's id
(`commands/client.py:604-612`): the audit trail records the target logging
out with the operator's free-text reason, the operator's id appears nowhere,
no `admin.action` is published, and nothing is acknowledged (an unknown id is
silently ignored, `engine/main.py:4703-4710`). pm-api-gwy's
`POST /admin/gateways/{id}/disconnect` sends the same message.

**Recommendation.** An ADMIN `risk.gateway_kick` message with a requester,
a `command_id`, an ack (`Gateway not configured` / `not connected` refusals)
and an `admin.action` record, used by pm-admin and pm-api-gwy; the
self-service messages stay for their own gateway, and the PUSH socket's reach
(internal network) is the other half of the answer, as for L039.

**Fixed (2026-11-24).** Decisions: the REST endpoint awaits the ack; an
ADMIN's own id is refused; the bye names the ADMIN. `risk.gateway_kick`
(`gateway_id` = the ADMIN caller, `target_gateway_id`, `note`, `command_id`)
and `risk.gateway_kick_ack.{gateway_id}` are in `spec/messages/risk.yaml`;
`admin.action` gained the action `gateway.kick`. `Engine._handle_gateway_kick`
refuses a caller that is not connected or not ADMIN, a missing target, the
caller's own id, `Gateway not configured: X` and `Gateway not connected: X`
(each with an ack and an `admin.action`, nothing disconnected); otherwise it
runs the ordinary disconnect path with the bye reason `kicked by <ADMIN>[:
<note>]` (which clearing keeps as the session's `disconnect_reason`), so the
target's `disconnect_behaviour` applies, and acknowledges after the
disconnect's effects. `ExchangeCommandClient.gateway_kick` returns the ack;
pm-admin `KICK` / pm-admin-cli `kick` report it (`KICK OK  X` or `REJECTED
…`, exit 1) and no longer pre-check with `gateway_list()`. `POST
/admin/gateways/{id}/disconnect` answers `200` with the ack or `409
DISCONNECT_REJECTED` (was `202 PENDING_DISCONNECT` for any id); the
trader-gui type follows. Sim forensics C13 judges a kick: an accepted one
needs an ADMIN caller and ends exactly its target's session, a refused one
ends none. `risk.kill_switch` and `quote.cancel` remain the participant's own
messages and are still not authenticated: closing that needs the engine to
know who sent a PUSH message, the network half above. Tests:
`test_engine_admin_gateway_kick.py` (wired engine), `test_commands.py`,
`test_commands_console.py`, `test_api_gateway_admin.py`,
`test_api_gateway_admin_parity.py`, `test_sim_forensics_sweeps.py`, the
trader-gui `adminGateways.test.tsx`. Books: operator guide (admin console),
reference manual, REST reference, training ch. 19, architecture overview,
generated message reference.


## L045 — The container's stop grace is shorter than pm-opctl's stop budget

**Found:** 2026-11-23, pm-opctl-cli review (`reviews/EduMatcher-Opctl-Review-2026-11.md` §9).

**Finding.** `deployment/docker/compose.yaml` and `compose.ai-sim.yaml` give
the container 30 s and 60 s (`stop_grace_period`) between SIGTERM and SIGKILL.
The entrypoint's `shutdown` runs `pm-opctl-cli stop`, which signals in four
waves and waits up to 15 s for each (`emo/cli.py:183-189`, `:1089-1098`). When
the gateways or the engine take long to exit (a large GTC book to persist in
ai-sim), Docker SIGKILLs the stack before the recorders' wave, so pm-clearing,
pm-stats and pm-audit miss the engine's last messages and pm-log-srv its
farewells.

**Recommendation.** Measure `stop` on the ai-sim profile at a busy close and
set `stop_grace_period` above the measured time plus margin (or 4 × 15 s +
10 s), and/or let `pm-opctl-cli stop` take a total budget so it can share the
grace period between waves.
---

## Work plan

### Decisions

Each one is to be confirmed before its WP starts; the WP is written for the
recommendation.

| # | WP | Question | Recommendation |
|---|---|---|---|
| Q1 | WP-FL01 | Which messages does the engine check `tick_decimals` on? (a) every message that carries it (`quote.new`, `order.new`, OCO and combo legs, amends); (b) `quote.new` only | **(a)**: every path that carries the field can carry a wrong one; checking only quotes leaves the same 100× error on orders. |
| Q2 | WP-FL03 | Which halts survive an engine restart? (a) ADMIN halts are persisted and restored; circuit-breaker halts are not, and the engine publishes `circuit_breaker.resume` for each one it dropped; (b) none, resume published for all; (c) all | **(a)**: an ADMIN halt is an operator decision meant to outlast the close (`engine/main.py:2654`); a breaker halt is timed and its timer is meaningless after a restart. Publishing the resume clears every subscriber's cache. |
| Q3 | WP-FL04 | What does `system.eod` carry? (a) the run's last trade id (`{run_seq}-{seq}`, or none for a run without trades), also on the `system.session_status.{gateway_id}` reply as "last so far"; (b) a trade count | **(a)**: subscribers already parse and compare trade ids; a count must be matched against what each subscriber counted, which a restarted subscriber does not know. |
| Q4 | WP-FL05 | Where does the rebuild live? (a) `pm-clearing-cli rebuild --from-audit <audit dir> --output <new clearing.db>`, which never writes the live database and prints the difference; (b) a `pm-audit-replay` target | **(a)**: the ledger logic and its `apply` path belong to pm-clearing; replacing the live file stays an explicit operator step. |
| Q5 | WP-FL06 | How does an admin query name its target? (a) a requester field separate from the target (as `risk.kill_switch_gateway`), and a reply `status` of `OK`, `NOT_CONNECTED` (with the stored orders/positions) or `UNKNOWN_GATEWAY`; (b) keep one field, answer about disconnected gateways only when the requester is ADMIN | **(a)**: (b) cannot tell "unknown id" from "flat", which is the pm-alf-console half of L030. |
| Q6 | WP-FL07 | How does a BALF client learn adopted orders? (a) a new server message `ORDER_STATUS` (BALF 1.1) per adopted order at logon, with the new BALF id, the `client_order_id` restored from `client_tag`, and the order's state; (b) an `EXECUTION_REPORT` with a restatement status; (c) leave it for 1.x and document that a gateway restart orphans resting orders | **(a)**: `EXECUTION_REPORT` means "something happened to the order"; a restatement overloads it for every client. If 1.0 cannot take a protocol change, (c) and move WP-FL07 behind WP-FL20. |
| Q7 | WP-FL10 | What is an auction fill's `liquidity_flag`? (a) a third value `AUCTION` on both events; (b) `MAKER` on both, documented | **(a)**: neither side took liquidity; a fee rule that sees MAKER pays a rebate to both. The enum change reaches pm-dc-gwy, the drop-copy consumers and the spec. |
| Q8 | WP-FL11 | What does pm-alf-gwy do on a half-close (EOF on read)? (a) stop reading, keep sending until the replies to commands already sent have arrived or a bound (2 s) passes, then close; (b) close at once (today) | **(a)**: `printf … \| nc` is the documented scripting route, and TCP allows sending after the peer's FIN. |
| Q9 | WP-FL13 | How does a subscriber recognise a new server? (a) a random `instance_id` on `log.server_state`, new at every start; (b) the start time | **(a)**: a start time can repeat after a clock step; an id cannot. pm-clearing already uses an `instance_id` the same way. |
| Q10 | WP-FL16 | What does `-q` mean? (a) WARNING, the default, with the help saying so ("Explicit WARNING log level (the default)", as pm-mm-bot's WP-MMB08); (b) ERROR everywhere | **(a)**: it is the wording already chosen for pm-mm-bot and the reference manual, and changes no process's output. |
| Q11 | WP-FL20 | L025: (a) reword training-guide ch. 17 to what the engine does (a collar without a reference price applies from the next engine start); (b) arm the collar when the first reference price becomes known | **(a)** for 1.0: (b) changes a risk control's timing in the engine and belongs with the 1.x work; record it as a new For-Later entry. |

### WP-FL01 — The engine refuses a quote or order priced at the wrong tick scale (L032; after Q1)

**Tests first** (`tests/test_engine_tick_scale.py`, new; wired engine, one
symbol at 2 decimals and one at 3):

1. `quote.new` for the 2-decimal symbol with `tick_decimals: 4` is rejected
   with a reason naming both scales ("tick_decimals 4 does not match AAPL's
   2"); no quote rests and the book is unchanged. (Fails today: the quote
   rests at 1/100 of the price.)
2. The same with `tick_decimals: 0` (the 100× case). (Fails today.)
3. `order.new` (LIMIT), an OCO and a combo whose `tick_decimals` (or a leg's)
   differs from the symbol's are rejected with `reject_code` `INVALID_VALUE`.
   A path that already refuses keeps its test as a regression test.
   (Expected to fail on at least the paths that read only `*_ticks`.)
4. An amend that carries a wrong scale is rejected and the order keeps its
   price.
5. Matching scales are accepted on every path, unchanged.
6. pm-mm-bot with its symbols reply timed out on the 3-decimal symbol
   (review C5's fallback to 2 decimals): its quote is refused and the bot
   logs the reject, instead of resting at the wrong price
   (`tests/test_mm_bot_engine_wired.py`). (Fails today.)

**Change.** One check before price conversion in `_handle_quote_new` and the
order, OCO, combo and amend entry paths, against `get_tick_decimals(symbol)`.
The spec's `tick_decimals` docs say the engine refuses a mismatch.

**Risk check.** Run the integration suites of every in-repo sender (api-gwy,
alf-gwy, balf-gwy, mm-bot, market-sim, ai-trader) and one short simulation:
a sender that relied on the field being ignored now gets rejects. Each such
sender bug gets its own regression test before its fix.

**Exit criteria.** Tests 1–6 pass; sender suites green; a 30-minute sim run
shows no `tick_decimals` rejects.

**Outcome (2026-11-16).** Q1 (a) taken. `Engine._tick_scale_mismatch`
compares a message's `tick_decimals` with the symbol's *configured* value
(not the process-wide tick registry, which `run()` fills and a test harness
does not) and returns "tick_decimals 4 does not match AAPL's 2". Used by:
`_validate_new_order` (`INVALID_VALUE`, only when the order carries a tick
price: a MARKET order has nothing the scale could misplace), `quote.new`
(`tick_decimals` is now read as the required field the spec says it is; a
quote without it is an "Invalid quote payload"), `order.oco` (absent reads as
the spec's default 0, so it is refused on any symbol not at 0 decimals) and
`order.combo` (each priced leg, "Leg i: …"). Plan test 4 does not apply:
`order.amend` carries display money and no `tick_decimals`; the engine
converts it with the resting order's symbol. Plan test 6 is already covered:
since WP-MMB05 pm-mm-bot ends its start-up when the symbol list does not
arrive (`test_no_symbol_list_ends_start_up`), so the 2-decimal fallback of
review C5 no longer quotes. The spec texts of the four `tick_decimals` fields
say the engine refuses a mismatch (bindings and message reference
regenerated).

Sender bug found: pm-alf-console's OCO omitted `tick_decimals`, which the
generated builder filled with 0; every console OCO would have been refused.
Fixed with a failing assertion first (`tests/test_alf_console_ticks.py`).
Every other in-repo sender (api-gwy, alf-gwy, pm-mm-bot, the consoles' quote
and combo) already sent the symbol's scale. 45 existing engine tests (six
files) failed because they built raw OCO, combo-leg or quote payloads without
`tick_decimals`; the payloads now carry `"tick_decimals": 2` as the gateways'
do. One more quote test in `test_engine_structure_error_contract.py` expected
a refusal and would have passed for the wrong reason; it got the field too.

Tests: `tests/test_engine_tick_scale.py` (10; 5 failed first on
`accepted True`). Full suite: 14794 passed, 1 skipped; `make _check` clean.
Live check pending: a sim run shows no `tick_decimals` rejects.

### WP-FL02 — Every gateway session can expire, and a refused gateway id costs nothing (L029, L031)

**Tests first** (`tests/test_engine_gateway_sessions.py`, new; wired engine
with a short heartbeat interval and an injectable clock):

1. An accepted `gateway_connect` with no heartbeat ever: after the default
   interval × the miss budget the session is expired, the disconnect is
   published, `disconnect_behaviour` applies to its orders, and a new
   `gateway_connect` for the id is accepted. (Fails today: refused for good.)
2. A first heartbeat announcing a longer interval replaces the default; a
   session beating at that interval is not expired at the default deadline.
3. A session that beats normally is unchanged; an ADMIN disconnect is
   unchanged.
4. 1000 `gateway_connect` for ids that are not configured participants: the
   engine's session table and the per-gateway metric labels do not grow, and
   each id still gets its refusal on `system.gateway_auth.<id>`. (Fails
   today: 1000 sessions, 1000 labels.)
5. A configured id refused as "already connected" keeps today's behaviour.
6. pm-mm-bot `--all-symbols` start-up (the slowest first beat in the repo)
   sends its first heartbeat within the default interval and is not expired
   (`tests/test_mm_bot_engine_wired.py`).

**Change.** Start the silence clock at connect with
`GATEWAY_HEARTBEAT_INTERVAL_SEC` until the first beat says otherwise
(`_expire_silent_gateways`, `engine/main.py:4584`). In
`_handle_gateway_connect`, check the allowlist before `_session_for_gateway`
and before counting the metric. The publisher's per-topic counter for the
refusal topic stays (gap detection needs it); L031's entry is updated to say
so.

**Exit criteria.** Tests 1–6 pass; engine, gateway and bot suites green; a
sim run with every bot and GUI shows no unexpected expiries.

**Outcome (2026-11-16).** `_handle_gateway_connect` refuses an id that is no
configured participant *before* `_session_for_gateway` (L031); the refusal,
its text and the `auth_rejects` count (already a bounded label: unknown ids
count under the shared unknown label) are unchanged. On an accepted connect
the session gets `heartbeat_interval_sec = GATEWAY_HEARTBEAT_INTERVAL_SEC`
(60) and `last_heartbeat = now`, so `_expire_silent_gateways` times out a
session that never beats after 180 s (L029); the first beat replaces the
interval as before. A refused duplicate connect does not reset the live
session's clock. Found on the way and fixed with a failing test first:
`_handle_gateway_disconnect` also created a session for any unknown id (and
published a `gateway_bye` for it); it now ignores ids that are not configured
participants. All other `_session_for_gateway` callers check
`_gateway_status` first (verified).

Risk check: every process that connects was checked for a heartbeat. pm-admin
(`AdminConsole`) never sent one, so an idle console would now have been
logged out after three minutes: it now runs a heartbeat thread with its own
PUSH socket (as pm-alf-console), started after logon and joined before the
disconnect. `pm-admin-cli` connects for one command and disconnects, so it
needs none. `tools/replay_to_engine.py` sends one beat at 3600 s after logon.
pm-mm-bot, pm-alf-console, pm-alf-gwy, pm-balf-gwy and pm-api-gwy already
beat; pm-mm-bot's first beat is sent at logon, before its symbols request
(new wired test). The spec motivation of `system.gateway_heartbeat`, the
message-reference preamble ("Liveness is opt-in" removed; pm-admin added to
the senders) and the `ParticipantSession` comment describe the new rule.

Tests: `tests/test_engine_gateway_sessions.py` (8; 5 failed first: never
expired, re-logon refused, orders not cancelled, 1000 sessions, 100
sessions), `tests/test_commands_console.py` (3 heartbeat tests, failed on
the missing heartbeat), `tests/test_mm_bot_engine_wired.py` (1). Full suite:
14806 passed, 1 skipped; `make _check` clean. Live check pending: a sim run
with every bot and GUI shows no unexpected `heartbeat_timeout`.

### WP-FL03 — An engine restart keeps ADMIN halts and announces every halt it drops (L021; after Q2)

**Tests first** (`tests/test_engine_restart_contract.py`):

1. ADMIN halt on AAPL, clean stop, restart: AAPL is still halted, an
   `order.new` is refused as halted, and the halt is published at start-up
   so a fresh subscriber learns it. (Fails today: AAPL trades.)
2. The halt is persisted when it is set, not only at stop: halt, stop
   without the clean save, restart → still halted. (Fails today.)
3. ADMIN halt, resume, restart: AAPL trades.
4. A circuit-breaker halt active at stop: after the restart AAPL trades and
   one `circuit_breaker.resume` for it is published. (Fails today: no
   resume.)
5. A persisted halt for a symbol no longer configured is dropped with a
   WARNING.
6. pm-md-gwy clears a cached halt on that resume
   (`tests/test_md_gateway_unit.py`, regression).

**Change.** ADMIN halts are saved with the books' persisted state
(`engine/persistence.py`) at halt and resume time and restored at start-up;
breaker halts that were active are announced as resumed. The operator
guide's restart section is updated in WP-FL20.

**Exit criteria.** Tests 1–6 pass; engine and persistence suites green; one
live restart with an ADMIN halt checked in pm-admin and the GUIs.

**Outcome (2026-11-16).** Q2 (a) taken, made precise with the rule the
engine already had: an *operator halt* is one whose level is in
`_OPERATOR_HALT_LEVELS` (`ADMIN_SYMBOL`, `ADMIN_ALL`: no timer, untouched by
the closing backstop), or any halt of a symbol without a breaker. Those are
restored. Every other halt (a breaker trip, rest-of-day levels included, and
an operator halt started *at* a breaker level, which is timed) ends at the
restart with a `circuit_breaker.resume` carrying its `halt_source`.

`book_stats.json` carries the state: each halted symbol's entry gets
`halt: {level, source}` (`save_book_stats(..., halts)`), and a halted symbol
without a book gets an entry of its own. `load_book_stats` validates it like
`cb_window`: a bad `halt` is dropped with a CRITICAL, counted, the file kept,
and the symbol starts tradable. No new file, so the audit re-run's patched
paths, pm-new-symbol's guards and the EOD archive need no change.
`_flush_persistence` compares `_halt_records()` with what it last wrote and
checkpoints at once when they differ, so a halt is on disk within one
maintenance slice, not only at the next interval or at stop. `_load_config`
sets restored halts before the market-maker seed quotes are injected (seeds
then rest unmatched, as any limit order entered during a halt), and sets the
breaker's state as the halt handlers do; `_startup` then publishes
`circuit_breaker.halt` (`resume_at_ns` null, `halt_source` ADMIN, the saved
level) for each restored halt and `circuit_breaker.resume` for each ended
one. A checkpointed halt for a symbol no longer configured is dropped with a
WARNING. Each start-up decision is logged at WARNING; the four new messages
have log-ledger entries.

Defect found and fixed with a failing test first: an operator halt at a
breaker level (`halt-sym --level L1`) published the level's name but left
`cb.triggered_level` at its previous value, so `system.halt_status` reported
no level (or a stale one), and the checkpoint could not tell it from an
operator halt without a level. Limits: a symbol without a breaker halted by
`halt` (halt-all) is restored as `ADMIN_SYMBOL`, since the engine records no
level for it; it behaves the same. The `circuit_breaker.halt`/`.resume` spec
notes name the restart as a producer.

Tests: `tests/test_engine_restart_contract.py` (8 new; 6 failed first: not
halted after restart, no resume published, no WARNING, seed quote traded),
`tests/test_engine_corrupt_startup_state.py` (7 new: corrupt halt dropped and
counted, a good one kept, a bookless halt saved). Plan test 6 is the existing
`test_poll_engine_events_resume_emits_state_and_cb` (pm-md-gwy). Full suite:
14821 passed, 1 skipped; `make _check` clean. Live check pending: an ADMIN
halt across a real restart, seen in pm-admin and the GUIs. The operator
guide's restart section is WP-FL20's.

### WP-FL04 — A subscriber can tell whether it received the whole of an engine run (L022; after Q3)

**Tests first:**

1. Generated model: `system.eod` and `system.session_status.{gateway_id}`
   have the last-trade-id field (none allowed for a run without trades).
   (Fails today: field absent.)
2. Wired engine: after three trades, `system.eod` carries the third trade's
   id; a run without trades carries none; the session-status reply carries
   the id of the last trade so far. (Fails today.)
3. pm-clearing (`tests/test_clearing_main.py`): trades `R-1 … R-5` received,
   `system.eod` says `R-7` → a `GAP` for `R-6 … R-7`, reported the same way
   as WP-CLR02's in-run gaps. All received → no gap. (Fails today.)
4. pm-clearing restarted after the engine run ended: it asks for the session
   status, compares with the last stored trade of that run, and reports the
   gap. (Fails today.)
5. pm-stats and pm-audit: the same end-of-run check, each through its
   existing gap reporting (one test each). (Fails today.)

**Change.** Spec field on both messages, regenerate; the engine tracks the
run's last trade id; the three subscribers compare at `system.eod` and after
their own start.

**Exit criteria.** Tests 1–5 pass; engine, clearing, stats and audit suites
green; a sim day with a subscriber killed just before the close shows the
gap.

**Outcome (2026-11-16).** Q3 (a) taken. `models/trade.py` keeps the id of the
newest trade minted (`last_trade_id()`, one assignment per trade).
`system.eod` and `system.session_status.{gateway_id}` gained `last_trade_id`
(nullable; null for a run without trades), filled by the engine; the REST
session-status example, the OpenAPI contract and the api-gwy layout test's
engine double carry it too (those three fixed by Johan during the WP).

- pm-clearing: `_handle_eod` compares the run's last id with the last one
  received (`_check_run_end`) and records a `GAP` with reason `end_of_run`
  (`last_seq` 0 when none of the run's trades arrived). The GAP write is
  shared with the in-run check (`_record_gap`). Its `_last_seq` was already
  seeded from `trade_events` at start (H2), so the check also holds after a
  pm-clearing restart.
- pm-stats: `_on_eod` does the same, as a `feed_gaps` row with the new
  `source` `run_end` (`expected_id` the first missing, `received_id` one past
  the run's last). `_last_trade_id` is now seeded from `trade_log` at start,
  as pm-clearing's is, so the check (and the in-run check at the next trade)
  holds after a pm-stats restart; no schema change, so `SCHEMA_VERSION` stays
  12.
- pm-audit: no change needed. `system.eod` is on the engine's publisher-wide
  sequence (`eseq`), so trades lost before it already count in
  `audit.missed_messages`; a test now pins that.

Deviation from the plan: plan test 4 (pm-clearing asks the engine for the
session status after its own restart) was not built. pm-clearing has no
channel to the engine, and the case is already covered: its seeded last id is
compared with the run's next trade (H2) and with `system.eod`. What stays
undetectable is an engine run that ends while the subscriber is down (it
never sees that `system.eod`); the clearing-GUI chapter says so.

Texts: the operator guide's clearing-GUI chapter (reasons `feed`, `restart`,
`end_of_run`) and statistics chapter (`source` values), the `feed_gaps` DDL
comment and the regenerated schema reference, the clearing ledger entry; the
new pm-stats ERROR has a ledger entry (written by Johan).

Tests: `tests/test_engine_run_end.py` (5; failed first on the missing API),
`tests/test_clearing_restart_gap.py` (4 new; 3 failed first),
`tests/test_stats_bounds_and_gaps.py` (3 new; 2 failed first),
`tests/test_audit_main_runtime.py` (1, pins existing behaviour). Full suite:
14833 passed, 1 skipped; `make _check` clean. Live check pending: a sim day
with a subscriber slowed just before the close shows the gap.

### WP-FL05 — `clearing.db` can be rebuilt from the audit trail (L023; after Q4)

**Tests first** (`tests/test_clearing_rebuild.py`, new):

1. An audit directory holding N `trade.executed` events and a live
   `clearing.db` that missed trade k: `pm-clearing-cli rebuild --from-audit
   … --output new.db` produces positions, average costs and realised P&L
   equal to a ledger fed all N in order through the live apply path. (Fails
   today: no command.)
2. The report lists every (gateway, symbol) that differs between the live
   and the rebuilt ledger, and the exit status says whether there were
   differences (the CLI's convention).
3. Close snapshots that pm-eod settled from are carried over unchanged.
4. Refused: `--output` naming the live database; an audit trail whose
   retention does not reach the first trade of the oldest open position (the
   error names the reach).
5. An event present twice in the audit trail (same `msg_id`) is applied
   once.

**Change.** A `rebuild` subcommand reading pm-audit's retained files
in trade-id order into a fresh database through the existing apply code, and
a diff against the live database. The operator guide's clearing chapter gets
the repair procedure (WP-FL20).

**Exit criteria.** Tests 1–5 pass; clearing and audit suites green; a
rebuild of a real sim day's `clearing.db` reports no differences.

**Outcome (2026-11-16).** Q4 (a) taken: `pm-clearing-cli [--datapath LIVE]
rebuild --from-audit DATA_DIR --output NEW` (`clearing/rebuild.py`). It
streams pm-audit's `trade.executed` lines (`audit.rawlines`: the daily
archives, then the live trail) through a fresh `ClearingProcess` on the new
file, flushing every 10 000 trades, so positions, average cost and realised
P&L come from pm-clearing's own code and its id-based dedup. It then copies
the live `position_close_snapshot` rows unchanged (the live file is attached
read-only) and lists every gateway/symbol whose `net_qty`, `avg_cost` or
`realized_pnl` differ (or that only one side has). Exit 0: no difference; 3:
differences listed; 1: refused. Gaps in the audit's own trade ids are
recorded as GAPs in the new file and named in the summary line.

Design note: the plan's "reach" rule became concrete once the schema was
read. A close snapshot has no average cost, so the ledger cannot restart from
one; the rebuild starts flat and therefore needs every trade since the live
ledger's first. `gateway_daily_summary` is never pruned, so its earliest
`trade_date` is that day; an audit trail whose first trade is later is
refused with both dates. Also refused: `--output` naming the live file, an
existing `--output`, an audit trail with no trade. Not carried over:
`trade_events.msg_id` (the raw-line reader does not expose `msg=`), and the
EOD marks (`mark_price` comes from the replayed trades; marks are not
compared). `ClearingProcess` gained a small public surface for this
(`replay`, `gap_count`, `close_db`) instead of the rebuild using its
internals. pm-help's registry and the shell completions list the verb; the
operator-guide repair procedure is WP-FL20's.

Tests: `tests/test_clearing_rebuild.py` (14; the first 12 failed first on the
missing module, two CLI ones after it on the missing verb). The batch-flush
and audit-hole tests were added after the streaming rewrite, as regression
tests. Full suite: 14848 passed, 1 skipped; `make _check` clean. Live check
pending: a rebuild of a real sim day's `clearing.db` reports no difference.

### WP-FL06 — Admin queries and book requests always get a truthful answer (L030, L028; after Q5)

**Tests first:**

1. Generated model: the position and orders requests have a requester and a
   target, the replies a `status`. (Fails today.)
2. Wired engine: an ADMIN asks for the orders and positions of a logged-off
   gateway that has GTC orders and a position → status `NOT_CONNECTED` with
   both. (Fails today: empty lists.)
3. An id no participant has → `UNKNOWN_GATEWAY`; a connected flat
   participant → `OK` with empty lists. (Fails today: all three look alike.)
4. A non-admin asking about another gateway is refused as today (security
   regression).
5. `GET /admin/gateways/{id}/positions` and `/orders`: 200 with the data for
   a logged-off gateway, 404 for an unknown id
   (`tests/test_api_gateway_*`). pm-alf-console `POS|GW=XYZ` prints that the
   id is unknown. (Fail today.)
6. `book.snapshot_request` for a configured symbol with no book yet → an
   empty snapshot; for an unconfigured symbol → no book is created. pm-md-gwy
   clears its cached `TOP`/`DEPTH` on that empty snapshot. (Fails today: no
   answer.)

**Change.** Spec, regenerate; `_handle_position_request`,
`_handle_orders_request` and `_handle_book_snapshot_request`; the api-gwy
and pm-alf-console callers.

**Exit criteria.** Tests 1–6 pass; engine, api-gwy, alf-console and md-gwy
suites green.

**Outcome (2026-11-16).** Q5 was decided on a premise the code does not
hold: it assumed a gateway can ask only about itself, so that a requester
field would separate "who asks" from "about whom". Neither request carries
any requester identity, and `POS|GW=<id>` (pm-alf-console, pm-alf-gwy) is
documented as working for any gateway; nothing to authorise changes with a
requester field. Built instead, the part of Q5 (a) that fixes L030: both
replies answer about any *configured* participant, connected or not, with a
new `status` (`OK`, `NOT_CONNECTED` with the data, `UNKNOWN_GATEWAY` with an
empty list; `Engine._query_status`). This discloses nothing new (a refused
logon already names an unknown id; the spec note that said otherwise is
rewritten). The missing requester identity is recorded as L039.

Callers: `GET /admin/gateways/{id}/positions` and `/orders` answer a logged-off
participant with its data and an unknown id with the new 404
`UNKNOWN_GATEWAY` (error registry, REST spec tables, OpenAPI); the orders
reply's REST shape is generated from the message, so it carries `status`.
pm-alf-gwy's `POSITION` line gained `STATUS=`; pm-alf-console prints "no
participant has this id" or "(not connected)". pm-admin's `POS`/`ORDERS`
(`commands/client.py`) still return the list alone. The audit-replay lexicon
glosses the three values.

L028 is not a defect: `_load_config` creates a book for every configured
symbol at start-up (since the initial commit), so a book request for one
without orders is answered with an empty book; only an unconfigured symbol
goes unanswered. A pinning test was added and the handler's comment, which
said books appear with a symbol's first order, corrected.

Tests: `tests/test_engine_admin_queries.py` (5; 4 failed first on the missing
`status`), `tests/test_api_gateway_admin.py` (3; the 404 ones failed first),
`tests/test_alf_gwy_gateway_unit.py` (3), `tests/test_alf_console_position_query.py`
(6), two existing assertions updated for the new argument and field. Full
suite: 14868 passed, 1 skipped; `make _check` clean.

### WP-FL07 — Resting orders stay reachable over BALF after a gateway restart (L027; after Q6, WP-FL06)

**Tests first** (`tests/test_balf_gwy_integration.py`, real engine):

1. Codec: `ORDER_STATUS` encodes and decodes with the fields of Q6, and the
   protocol version is 1.1 (`tests/test_balf_gwy_unit.py`). (Fails today.)
2. `NEW_ORDER` sends the client's `client_order_id` as `client_tag` on
   `order.new`. (Fails today.)
3. A participant whose `disconnect_behaviour` keeps orders places a GTC
   order; pm-balf-gwy is restarted; at the next logon the client receives an
   `ORDER_STATUS` with a new BALF id and the original `client_order_id`; a
   later fill arrives as an `EXECUTION_REPORT` for that id, and a cancel by
   that id works. (Fails today: nothing arrives, the cancel is unknown.)
4. Another participant's orders are not adopted; a participant whose orders
   were cancelled at disconnect receives no `ORDER_STATUS`.
5. A reconnect without a gateway restart (WP-BALF01's path) is unchanged.

**Change.** At logon pm-balf-gwy asks `order.orders_request` (WP-FL06's
target form) for its gateway id, registers each live order under a fresh
BALF id and sends `ORDER_STATUS`. `020-balf.md` documents BALF 1.1.

**Exit criteria.** Tests 1–5 pass; BALF suites green; the BALF example
client handles the new message.

**Outcome (2026-11-16).** Q6 (a) taken: BALF `1.1.0` adds `ORDER_STATUS`
(0x22, server to client, 64 bytes: `client_order_id`, new `order_id`,
`price`, `stop_price`, `quantity`, `remaining_qty`, `symbol`, `side`,
`order_type`, `tif` in `NEW_ORDER`'s codes). `NEW_ORDER` now sends the
client's `client_order_id` to the engine as `client_tag`. When a gateway ID
logs on and this pm-balf-gwy process has no order map for it yet (a fresh
process), the gateway sends `order.orders_request` after `LOGON_ACK`; the
reply (`order.orders.<ID>`, now subscribed) is adopted once
(`_GatewayOrders.adopt_pending`, `BalfGateway._adopt_orders`): each order not
already mapped gets the next BALF id, the maps are filled, and one
`ORDER_STATUS` goes to the client. `client_order_id` is 0 for an order whose
tag is not a BALF number (entered over REST or ALF). A second session of the
same ID in the same process asks nothing (WP-BALF01's path, unchanged). If
the request cannot be sent, a WARNING (ledger entry added) says the orders
are out of reach this run.

No version negotiation (no backwards-compatibility code): the header
`version` byte stays 1, and the spec now says a client MUST skip a
`msg_type` it does not know. Known limit, documented: an event for a not yet
adopted order that arrives between `LOGON_ACK` and the engine's answer is
not delivered. Plan test 4 ("another participant's orders are not adopted";
"a participant whose orders were cancelled gets no ORDER_STATUS") follows
from the reply being gateway-scoped and holding only resting orders; it is
covered by the adoption tests with the reply's content, not separately.

Texts: the BALF reference (status `1.1.0`, summary row, the message, the
order-id paragraph, the unknown-type rule), the operator guide's BALF
chapter, the `_GatewayOrders` docstring; the Python example parser decodes
`ORDER_STATUS` and the C one knows its size.

Tests: `tests/test_balf_gwy_integration.py` (4: client_tag, adoption with a
fill and a cancel under the new id, untagged orders, no second request),
`tests/test_balf_gwy_unit.py` (codec round trip),
`tests/test_examples_balf_alf_current.py` (example parser); all failed first
on the missing frame, tag or request. `tests/test_gateway_k16_k17.py`'s
subscription list gained `order.orders.`. Full suite: 14874 passed, 1
skipped; `make _check` clean. Live check pending: restart pm-balf-gwy under a
BALF client with a resting GTC order and see it handed back.

### WP-FL08 — Console and CLI print the engine's answer to a session transition (L009)

**Tests first** (`tests/test_commands.py`, `tests/test_commands_console.py`,
`tests/test_commands_cli.py`, wired engine):

1. `session_advance(CONTINUOUS)` while `CONTINUOUS` returns the rejection
   with the engine's reason within one second. (Fails today: three-second
   `TIMEOUT`.)
2. A legal transition returns the new state, unchanged.
3. `pm-admin-cli session` prints the reason and exits non-zero; pm-admin's
   `SESSION|STATE=` prints it. (Fail today.)

**Change.** `ExchangeCommandClient.session_advance` sends `command_id` and
`gateway_id` and waits on `session.transition_ack.<gateway_id>`, as the API
gateway does; both front ends print its reason. Training guide ch. 01 and 06
lose their `TIMEOUT` text in this WP.

**Exit criteria.** Tests 1–3 pass; commands suites green.

**Outcome (2026-11-16).** `ExchangeCommandClient.session_advance` sends the
transition with `reply_to` (a fresh `command_id` and its own gateway id), as
pm-api-gwy does, and returns the engine's `session.transition_ack`
(`accepted`, `to_state`, `reason`); the client subscribes to that prefix
instead of `session.state`. pm-admin's `SESSION|STATE=` and `pm-admin-cli
session` print `SESSION  now <STATE>` or `SESSION  REJECTED  <reason>`, and a
refusal is a failed command (exit 1 for the CLI). The previous
`prev → state` line came from the `session.state` broadcast, which the
command no longer waits for. Texts updated: the operator guide (admin
commands, sessions chapter), the quick start, training guide ch. 01 and 06.

Tests: `tests/test_commands.py` — two unit tests rewritten for the new
request and reply, and `TestSessionAgainstTheEngine` (3, a real `Engine`
behind the client's sockets): an illegal transition answers with the
engine's reason in well under a second, a legal one with the new state,
pm-admin prints `REJECTED` and the reason and reports failure. All failed
first (`session.state` timeout, missing `accepted`). Full suite: 14877
passed, 1 skipped; `make _check` clean.

### WP-FL09 — Every configuration loader refuses the values it cannot hold (L024)

**Tests first** (parametrised, one case per field):

1. `tests/test_config_loader.py`: `tick_decimals: true`,
   `outstanding_shares: true`, `order_limits.max_order_qty: 1.5`,
   `schedule: 'x'` and `schedule: 0`, `.nan` for every `> 0` field (at least
   `snapshot_interval_sec`) are refused with an error naming the field.
   (Fail today.)
2. log_srv, balf_gwy, alf_gwy and api_gateway config tests: `enabled:
   "false"`, `enabled: 'x'`, `pubsub_enabled: 'x'`, `swagger_enabled: 'x'`,
   and a number for `name`, `bind_address`, `db_path` are refused. (Fail
   today, except where WP-LOG07 already fixed log_srv; those stay as
   regression tests.)
3. Every configuration shipped in the repository (examples, container
   configs, `pm-config-gen` output for each combo) still loads.
4. Differential: for each leaf the review's harness replaced, the loader
   refuses exactly when `pm-cverifier` does.

**Change.** Small shared validators (bool-is-not-int, integral count,
`math.isfinite`, mapping-or-absent, strict bool) used by the loaders; the
`bool()` reads go.

**Exit criteria.** Tests 1–4 pass; config, gateway and log-server suites
green.

**Outcome (2026-11-17).** `config_coerce` gains `as_bool` (a YAML boolean
only) and `as_str` (a string only) beside `as_int`/`as_float`. The engine
loader reads every integer and float through them (`_int`/`_float`, so the
existing field-naming error texts stay): a bool, a fraction where a count
belongs and NaN/inf are refused. A market-maker quote's error now names the
field (`… market_maker_quotes[0] is invalid: … bid_qty must be an integer`),
`seed_once` must be a boolean, and a `schedule` that is not a mapping is
refused instead of ignored. pm-balf-gwy, pm-alf-gwy, pm-log-srv and pm-api-gwy
read `enabled`/`swagger_enabled` with `as_bool` and `name`, `bind_address`/
`host`, `db_path`, the database paths, the ZeroMQ addresses and `log_level`
with `as_str`.

Tests: `tests/test_config_loader.py::TestValuesTheFieldCannotHold` (22
cases), new `tests/test_config_strict_flags.py` (gateway and log-server
flags and names; every shipped configuration — the 37 example setups,
`src/data/ref_data`, the config-gui fixtures — still loads through all ten
loaders) and 15 new rows in `tests/test_cverifier_deploy_agreement.py`
(pm-cverifier already refused every one; the loaders now do too). All failed
first, except log_server `enabled`/`pubsub_enabled` (WP-LOG07 had fixed them;
kept as regression tests). Full suite: 15001 passed, 1 skipped (the 12
failures of that run were WP-FL10's tests, written ahead).

### WP-FL10 — Rejection texts name the real problem; an uncross print has a defined liquidity flag (L012, L026, L037; after Q7)

**Tests first:**

1. `models/order_fields.py`: a TRAILING_STOP or ICEBERG combo or OCO leg is
   refused as "… is not supported on a combo leg" with no "it needs …",
   with and without `TRAIL=`/the visible quantity. (Fails today.)
2. Wired engine: a TRAILING_STOP with `trail_offset -1.00` on a symbol
   without trades → `reject_code` `INVALID_VALUE`, reason about the offset;
   the same through pm-balf-gwy (`balf_gwy/protocol.py:124` mapping). (Fails
   today: "requires STOP= or a prior trade price".)
3. Uncross print: both drop-copy events carry `AUCTION`; a continuous trade
   still carries one TAKER and one MAKER. (Fails today: two MAKER.)
4. pm-dc-gwy and pm-alf-gwy render `AUCTION` on their drop-copy lines.

**Change.** Message text in `order_fields.py`; offset check before the
reference-price rule; enum value in `spec/messages/drop_copy.yaml`,
regenerate, `engine/main.py:3521`.

**Exit criteria.** Tests 1–4 pass; engine, combo, BALF and drop-copy suites
green.

**Outcome (2026-11-17).** Q7 (a) taken.
- L012: a leg type the leg cannot carry is refused as "`<TYPE>` is not
  supported on a combo leg" (or OCO leg), without "it needs …". A transport
  that names its fields also names the leg's type field, so ALF says
  `… (LEG0.TYPE)` / `(LEG1_TYPE)`: before, the leg was identified only by the
  field the message asked for.
- L026: `_validate_new_order` refuses a `trail_offset` of 0 or less with
  `INVALID_VALUE` "TRAILING_STOP order requires a positive trail_offset",
  before the reference-price rule; with a prior trade the order no longer
  reaches the book's assertion. pm-balf-gwy maps it to `RC_INVALID_FIELD`.
- L037: `liquidity_flag` gains `AUCTION` (`drop_copy.event`,
  `drop_copy.replay`, `order.fill`); both sides of an uncross print carry it.
  One engine helper, `_liquidity_flag`, now feeds both the drop copy and the
  private fill. pm-audit-replay's `LIQUIDITY_FLAG_DISAGREE` expects AUCTION
  on an uncross (MAKER there is now a disagreement); the lexicon glosses it.
  pm-dc-gwy and pm-alf-gwy pass the value through unchanged. Texts: ALF spec,
  operator ALF and DC gateway chapters, participant guide (order book,
  trader console), training ch. 26, regenerated message reference.

Tests: `tests/test_order_fields.py` (11 new cases), new
`tests/test_engine_trailing_offset.py` (6), `tests/test_liquidity_flag.py::TestUncrossPrint`
(3), the generated-enum tests, the DC and ALF relay tests with AUCTION, the
audit anomaly tests. All failed first, except the continuous-trade guard.
`tests/test_cross_transport_rejects.py` failed on the first version of the
L012 text (no leg named), which is why the type field is named. Full suite:
15015 passed, 1 skipped; `make test-e2e`: 39 passed (covers WP-FL09 too).

### WP-FL11 — Line gateways serve past 1024 descriptors, stop with EXIT, and answer a half-closed client (L036, L011; after Q8)

**Tests first:**

1. pm-md-gwy (`tests/test_md_gateway_unit.py`): with the descriptor limit
   raised and 1024 dummy descriptors open, a new client is served and no
   WARNING repeats. (Fails today.)
2. pm-md-gwy stop: each client receives `EXIT|REASON=shutdown` after its
   queued lines, within the flush bound. (Fails today.) Port WP-RALF04's
   tests.
3. pm-alf-gwy (`tests/test_alf_gwy_robustness.py`): `HELLO`, `SYMBOLS`,
   `EXIT`, then `shutdown(SHUT_WR)` → the client reads the logon reply, the
   symbol list and the exit line. (Fails today: nothing.)
4. A half-closed client whose replies never come is closed after the Q8
   bound.

**Change.** Copy `_read_client_data` (`select.poll`) and
`_flush_for_shutdown` from pm-ralf-gwy into pm-md-gwy; in pm-alf-gwy, EOF on
read stops reading and starts the bounded drain instead of disconnecting.
The training guide's `sleep 1` advice can go (WP-FL20).

**Exit criteria.** Tests 1–4 pass; md-gwy and alf-gwy suites green.

**Outcome (2026-11-17).** Q8 (a) taken.
- pm-md-gwy reads clients with `select.poll` and, on a requested stop, runs
  `_flush_for_shutdown` (one more engine pass, `EXIT|REASON=shutdown|TS=…`,
  a flush bounded by `SHUTDOWN_FLUSH_SEC` = 1 s), copied from pm-ralf-gwy.
  `close()` now counts each session's disconnect (`shutdown`, or the reason
  it was already closing for). Ledger entry renamed to `read poll failed`.
- pm-alf-gwy treats EOF on read as a half-close: it stops watching the
  socket for reading, keeps sending, and closes the session after
  `_HALF_CLOSE_GRACE_SEC` (2 s). On a half-closed session `EXIT` does not
  close it early, because the gateway does not track which replies are still
  owed: a `printf … | nc` script gets its replies and ends after the bound.
  An interactive `EXIT` is unchanged.

Deviation from test 3: ALF has no exit line (`EXIT` sends nothing back), so
the test checks the logon reply, the symbol list ending in `END`, and then a
clean close.

Tests: new `tests/test_md_gateway_poll_and_stop.py` (4: descriptor above
1023 served with no read WARNING, `EXIT|REASON=shutdown` on a stop, queued
lines before it, a non-reading client holds the stop under 1.5 s) and two
tests in `tests/test_alf_gwy_integration.py` (a half-closed
`HELLO`/`SYMBOLS`/`EXIT` script gets `WELCOME`, the symbol list and `END`; a
half-closed client whose logon is never answered is closed after about 2 s).
All failed first. Full suite: 15021 passed, 1 skipped; `make test-e2e`: 39
passed.

### WP-FL12 — pm-api-gwy's index and sim listeners fail loudly (L033)

**Tests first** (`tests/test_api_gateway_index_events.py`,
`tests/test_api_gateway_sim.py`):

1. A non-EINTR `ZMQError` in `IndexClient._receive_loop` logs at ERROR and
   calls `on_listener_failure`, so the process exits with status 1 as for the
   engine listener. (Fails today: the thread ends silently.)
2. The same for `SimClient._receive_loop`. (Fails today.)
3. EINTR keeps the loop running, unchanged.

**Change.** The engine listener's handling in both loops.

**Exit criteria.** Tests 1–3 pass; api-gwy suites green.

**Outcome (2026-11-17).** `IndexClient` and `SimClient` get the engine
listener's handling: an exception in the receive thread is logged at ERROR
("index listener died; stopping pm-api-gwy", "sim listener died; …") and
reported through `on_listener_failure`, which the lifespan sets to the same
callback as the engine's, so the process exits with status 1. EINTR now
continues the loop (it ended it before, silently). `SimClient` gains
`is_running()`. The final CRITICAL is worded for any listener ("a listener
died; exiting with status 1"); ledger entries and the operator guide's API
gateway chapter updated.

Tests (in `tests/test_api_gateway_listener.py`, beside the engine listener's,
rather than the two files the plan named): a dying index or sim listener is
logged and reported; EINTR keeps both running; the lifespan wires all three
listeners to the failure path. All failed first. Full suite: 15026 passed,
1 skipped; `make test-e2e`: 39 passed.

### WP-FL13 — The log-GUI live view notices a server restart and lost rows (L038; after Q9)

**Tests first:**

1. Python (`tests/test_log_srv_pubsub.py`): `log.server_state` carries an
   `instance_id` that differs between two server starts on one `log.db`.
   (Fails today.)
2. Bridge (vitest, `web-apps/log-gui/apps/bridge`): an ACTIVE uplink that
   receives `UP` with a new `instance_id` re-sends `log.subscribe` at once;
   the same id sends nothing. (Fails today.)
3. A `log.event` with `dropped > 0`, or a gap in the per-subscription counter
   of WP-LOG05, puts a gap marker in the live view. (Fails today.)

**Change.** Spec field, regenerate; the server sets it at start; the uplink
compares it and handles `dropped`/the counter; the view renders the marker.

**Exit criteria.** Tests 1–3 pass; log-server suites and the log-GUI's test
and type-check scripts green.

**Outcome (2026-11-17).** Q9 (a) taken. `log.server_state` gains
`instance_id` (16 hex characters from `secrets.token_hex(8)`, new at every
pm-log-srv start). The log-GUI bridge's uplink remembers it; an UP with a new
one re-subscribes at once (state `RECONNECTING`) and emits a `gap`
(`restart`). It also emits a `gap` when a `log.event`'s lifetime `dropped`
grows (`lost` = the increase) or its `msg_no` skips (`msg_no`); both counters
start afresh on each `subscribe_ack`. The bridge forwards a `{t: "gap"}`
frame; the live store keeps a marker entry in the tail (also while paused),
and the Explorer shows it as a row ("3 rows not received …", "log server
restarted …", with the advice to switch to history). Operator guide: log
server (liveness, `instance_id`) and log console (states, marker) chapters.

Limit: rows shed before a subscription's first event are not marked, because
`subscribe_ack` carries no counters to start from.

Tests: `tests/test_log_srv_pubsub.py` (2: the generated model has the field;
two starts on one `log.db` publish different ids), new
`apps/bridge/test/lalf-ps-uplink.test.ts` (5) and
`apps/web/test/live-gap.test.ts` (4). All failed first, except the two
"nothing happens" guards. Log-GUI: 107 vitest tests, type-check and build
clean. Full suite: 15028 passed, 1 skipped; `make test-e2e`: 39 passed.

### WP-FL14 — Close snapshots are pruned (L019)

**Tests first** (`tests/test_clearing_*`):

1. Snapshots for 40 dates and a retention of 30 days: the older dates are
   deleted, except the latest settled date even when it is older than the
   retention. (Fails today: nothing deleted.)
2. pm-eod still finds its baseline after a prune (pm-eod test).
3. The retention defaults to the `trade_events` retention, and the prune
   runs where that one does.

**Change.** A prune step next to the existing `trade_events` retention;
documented beside the other retention rules (WP-FL20).

**Exit criteria.** Tests 1–3 pass; clearing and EOD suites green.

**Outcome (2026-11-17).** New `prune_close_snapshots` deletes
`position_close_snapshot` dates older than the retention, never the newest
snapshot date; the boundary is the `trade_events` one (a date exactly N days
old stays). pm-clearing runs it wherever it prunes `trade_events` (start-up,
every close, every `system.eod`) with the same `--retention-days`, and logs
the count; `pm-clearing-cli prune` (and `--dry-run`) does both. Help texts
and the zsh completion updated; the books are WP-FL20's.

pm-clearing cannot know which date pm-eod settled last, so "the latest
settled date" became "the newest snapshot date", and pm-eod was made safe
for the rest: a previous settled date whose snapshot is gone, with a
recorded baseline from the *same* `clearing.db` (`clearing_instance`), is
settled from that recorded equity. Before, a missing snapshot was read as a
reset and the day booked the whole cumulative equity (shown by the test with
the pm-eod change removed).

Tests: new `tests/test_clearing_snapshot_retention.py` (7): the retention
rule, the newest date kept past it, an empty table, the prune at the close
(and not in CONTINUOUS), the CLI prune, pm-eod after a prune. All failed
first except the two guards. Full suite: 15035 passed, 1 skipped;
`make test-e2e`: 39 passed.

### WP-FL15 — Every topic pm-sim-forensics matches on is a declared topic (L001)

**Tests first** (`tests/test_msgen_literals.py`):

1. A checker given a synthetic module with the literal `"trade.exectued"`
   reports it as undeclared; one with `"order.ack."` (a prefix of a declared
   topic) passes. (Fails today: no checker.)
2. The checker run over `src/edumatcher/sim_forensics/` reports nothing.

**Change.** Reuse `pm-msgen grep-literals`' scanner to collect the forensics
literals and compare each with the spec's topics and their prefixes
(L001 option 2). The exemption stays.

**Exit criteria.** Tests 1–2 pass; msgen and sim-forensics suites green.

**Outcome (2026-11-17).** L001 option 2. New
`msgen.literals.undeclared_topics(roots, families)` walks the AST: every
string literal, and each f-string's leading text, whose first dotted part is
a topic root is checked against the spec. It passes when it is a declared
topic, a prefix of one ending at a part boundary (`"order.ack."`,
`"circuit_breaker."`) or an instance of a parameterised one
(`"order.ack.GW01"`). Under `engine.` and `health.`, which are also
beacon-metric namespaces (`engine.busy_pct`) with no registry to tell them
apart, only a subscription prefix (ending in `.`) is checked. The
exemption stays. It examines 182 literals in `src/edumatcher/sim_forensics/`
and finds none undeclared.

Tests: `TestForensicsTopicsAreDeclared` (9) and one shared-root case in
`tests/test_msgen_literals.py`. All failed first (no checker). Full suite:
15045 passed, 1 skipped; `make test-e2e`: 39 passed.

### WP-FL16 — CLIs behave in pipes and scripts (L013, L017, L034; after Q10)

**Tests first:**

1. For every table-printing CLI (parametrised over the entry points): run it
   as a subprocess whose stdout reader closes after the first line → no
   traceback on stderr. (Fails today for at least `pm-stats-cli daily`.)
2. `health -q` on an unhealthy service exits 1 in pm-audit-cli,
   pm-clearing-cli, pm-index-cli and pm-stats-cli, as without `-q`. (Fails
   today: 255.)
3. The `-q` help text of every entry point and of pm-help's common options
   is the Q10 wording (`tests/test_pm_help_*`). (Fails today.)

**Change.** One shared `BrokenPipeError` handling in the CLI entry helper (or
`SIGPIPE` reset); `SystemExit(1)` and help texts in the four CLIs; the `-q`
texts and the zsh completion file. Check the operator guide's health chapter
and the container healthchecks for a 255 comparison.

**Exit criteria.** Tests 1–3 pass; CLI suites green.

**Outcome (2026-11-17).** Q10 (a) taken.
- L013: new `edumatcher/cli_pipe.py` with `pipe_safe`, applied to the 21 CLI
  entry points that print to stdout (the `-cli` tools, pm-audit-replay,
  pm-sim-forensics, pm-eod, pm-config-gen/-deploy/-show, pm-cverifier,
  pm-msgen, pm-valuation, pm-news, pm-help). A closed stdout ends the process
  with status 1 and no traceback, also at the final flush. SIGPIPE is not
  reset: the daemons write to sockets, where that would kill them.
- L017: `health -q` exits 1 when unhealthy in pm-audit-cli, pm-clearing-cli,
  pm-index-cli, pm-stats-cli and pm-monitor-cli (the fifth CLI with the same
  pattern), as without `-q`; help texts say so. No container healthcheck
  compared the status.
- L034: every daemon's `-q` selects WARNING, the default; L034 named six
  entry points, but 25 had a "warnings/errors" text. All now start with "Explicit WARNING log level
  (the default)" (four keep an extra clause: the workers, or the precedence
  of `-v`/`--log-level`); pm-help's common options and pm-log-srv entry
  likewise; zsh completion regenerated. The books are WP-FL20's.

Tests: new `tests/test_cli_pipes_and_quiet.py` (21 entry points' `--help`
and `pm-stats-cli daily` into a pipe whose reader has gone; the `-q` texts
of every entry point found in the source and in pm-help) and the five CLIs'
`health -q` tests changed to expect 1. All failed first. Full suite: 15069
passed, 1 skipped; `make test-e2e`: 39 passed.

### WP-FL17 — pm-admin, ALF QBOOT and pm-orders print prices and states readably (L006, L008, L015)

**Tests first:**

1. pm-admin `BOOK` (`tests/test_commands_console.py`): prices of a 2- and a
   3-decimal symbol at their `tick_decimals`. (Fails today: `149.8`.)
2. After a restart that restored only the last price: `Last trade: 150.00`,
   no `× None`. (Fails today.)
3. ALF `QBOOT` lists an active quote with `STATUS=ACTIVE`. (Fails today:
   empty.)
4. pm-orders shows a rejected order as `REJECTED` with its reason
   (`tests/test_orders_main_runtime.py`). (Fails today: `?` columns.)

**Change.** Formatting in `commands/console.py`, the QBOOT encoder in
pm-alf-gwy, the rejected-row case in pm-orders.

**Exit criteria.** Tests 1–4 pass; commands, alf-gwy and orders suites
green.

**Outcome (2026-11-17).**
- L006/L008: pm-admin's `BOOK` (`_print_book`, shared by `pm-admin-cli`
  through the same command code) prints prices at the book's
  `tick_decimals` and the last trade as `Last trade: 150.00` when the
  quantity is unknown (restored after a restart), `… × 10` otherwise.
- L015: pm-alf-gwy's `QBOOT` read `status`, but the engine's `ActiveQuote`
  names it `state`; now `STATUS=ACTIVE`. pm-orders shows a rejected order
  with blank columns where the reject carries nothing (it has only the ids,
  the reason and the code) and `REJECTED (<reason>)` as its status.

Tests: three in `tests/test_commands_console.py` (2- and 3-decimal symbols,
a restored last price), one in `tests/test_alf_gwy_gateway_unit.py` (a
bootstrap built with the generated builder), one in
`tests/test_orders_main_runtime.py`. All failed first. Full suite: 15074
passed, 1 skipped; `make test-e2e`: 39 passed.

### WP-FL18 — trader-gui: no "-0.00%", and the audit modal shows the index's reach (L002, L018)

**Tests first** (vitest, `web-apps/trader-gui/apps/web/test/`):

1. `formatChangePct(149.9999, 150)` and a flat symbol give `"0.00%"`;
   `+0.01%` keeps its sign. (Fails today.)
2. `AdminOrderDetailModal`: a 404 whose message names `indexed_through`
   shows that message; a 200 shows `indexed_through`. (Fails today.)

**Change.** Sign on the rounded text (the `fixed` helper); the modal and
`src/types/index.ts`.

**Exit criteria.** Tests 1–2 pass; trader-gui test and type-check scripts
green.

**Outcome (2026-11-17).** `formatChangePct` signs the rounded text, as
`formatSignedPrice` does: a change that shows as 0.00 prints `0.00%` (also
an exact zero, which printed `+0.00%`). `AdminOrderDetailModal` shows the
server's 404 message, which names the index's reach, and on a 200 a line
"Audit index: indexed through …"; `AdminOrderLifecycleResponse` gains
`indexed_through`.

Tests: three cases in `apps/web/test/formatters.test.ts` and new
`apps/web/test/adminOrderDetailModal.test.tsx` (2). The rounding and both
modal cases failed first; the "+0.01%" case is a guard. trader-gui: 569
vitest tests and the type-check pass. Full suite: 15074 passed, 1 skipped;
`make test-e2e`: 39 passed.

### WP-FL19 — pm-mm-bot starts from the market model with --anchor-sim (L014)

**Tests first** (`tests/test_mm_bot*.py`):

1. `--anchor-sim`, an empty book and a market-model value for the symbol:
   the bot quotes around that value at start-up. (Fails today: no
   reference.)
2. A two-sided book is still preferred over the model's value.
3. Without `--anchor-sim`, unchanged.

**Change.** Fall back to the sim value in the start-up reference lookup.

**Exit criteria.** Tests 1–3 pass; mm-bot suites green.

**Outcome (2026-11-17).** The start-up waits passed `sim.value` nowhere, so
the reference lookup never saw it. `_buffer_event` now keeps each symbol's
value (no anchoring yet) when `--anchor-sim` is on, and
`_resolve_bootstrap_reference` uses it right after the book/trade mid,
before an inactive QBOOT quote and the random range. The participant
guide's bootstrap order lists it.

Tests: `TestAnchorSimStartupReference` in `tests/test_mm_bot_multi.py` (3):
an empty book starts from the value (failed first), a two-sided book wins,
and without `--anchor-sim` the value is ignored (both guards). Full suite:
15077 passed, 1 skipped; `make test-e2e`: 39 passed.

### WP-FL20 — The books describe what the code does (L003, L007, L016, L025, L020 interim; after Q11 and the WPs above)

**Tests first:**

1. `tests/test_engine_combo_acceptance.py`: an AON combo enters, one leg
   rests, and a later order fills that leg alone. This pins the behaviour
   the participant guide must describe (L016); it should pass today, and a
   failure means the guide's claim needs a code fix instead.
2. Grep checks with no hits: `six web` and `8090–8095` in
   `docs/books/` (L003); `not persisted` in the two persistence diagrams
   (L007); `first trades on` in training ch. 17 (L025).

**Change.** The texts of L003, L007, L016 (combo guarantees against the
actual contract) and L025 (Q11); the corporate-action contract of pm-index
review Q1 if not yet in the operator guide (L020 interim); and the texts the
earlier WPs left for here: the restart section (WP-FL03), end-of-run checks
(WP-FL04), the repair procedure (WP-FL05), snapshot retention (WP-FL14),
`health -q` and `-q` (WP-FL16), the `sleep 1` advice (WP-FL11).

**Exit criteria.** Test 1 passes; grep checks clean; `mkdocs build` clean.

**Outcome (2026-11-17).** Q11 (a) taken; (b) recorded as L041.
- L003: seven web applications on 8090–8096 (verified against the compose
  files, `edumatcher.sh` and `publish-images.yml`): installation, running the
  exchange (`make up-all` starts six, `clearing-gui` included, `config-gui`
  opt-in), container walkthrough (counts, nine published images), the
  architecture book's container and workflow chapters, quick start, two
  participant-guide port notes, and the same counts in `deployment/curl`
  (`install.sh`, `edumatcher.sh`, `README.md`, `.env.guis.example`,
  `compose.guis.yaml`) and `deployment/docker` (`README.md`, `Makefile`
  help).
- L007: the persistence chapter said in five places, not only the two
  diagrams, that DAY combo parents are not saved. `save_gtc_combos` keeps
  every working combo, GTC and DAY; a DAY one is discarded at a start after
  its business day (both diagrams, the file table, the shutdown and start-up
  steps, the day-rule list and the file's format note now say so).
- L016: the combo guide's opening, examples and reference say what AON is:
  a check at entry; resting legs fill independently afterwards
  (`PARTIALLY_MATCHED`), with a warning box on what a combo does not
  guarantee.
- L025: training ch. 17 says the collar takes effect from the next engine
  start after the first trades (`engine/main.py`, the one writer of
  `_collars`).
- L020 interim: already in the operator guide (market index chapter,
  "Apply corporate actions before the market opens"); unchanged.
- Earlier WPs' texts: halts across a restart (persistence chapter, start-up
  step 6a and the `book_stats.json` format; the CALF chapter's claims that a
  restart ends every halt silently and that symbols without a book go
  unanswered, both no longer true); the `clearing.db` repair procedure
  (persistence chapter, and `rebuild` in the participant guide's CLI table);
  snapshot retention (participant guide, closing-the-day chapter, whose "never
  pruned" and "settle a very old date" sentences changed meaning, and the
  stale `--retention-days 0` warning: all three triggers now skip pruning at
  0); `health -q` exits in five chapters and the reference manual; the Q10
  `-q` text in ten chapters; the ALF spec's half-close rule; training
  ch. 26's `nc` probe (`nc -N` needs no `sleep 1`; the container's `tcp`
  helper still does, as it closes completely).

Tests: `tests/test_engine_combo_acceptance.py::test_after_entry_an_aon_combos_legs_fill_independently`
passes, as expected: the guide was what had to change. Grep checks: no hit
for `six web` or `8090–8095` in `docs/books`, for `not persisted` in the
persistence chapter, or for `first trades on` in the training guide.
`mkdocs build` clean. Full suite: 15078 passed, 1 skipped; `make test-e2e`:
39 passed.

### WP-FL21 — Exchange-side corporate actions (L020; 1.x)

Not part of 1.0. First deliverable is a design document
(`docs-design/EduMatcher-Corporate-Actions.md`) deciding: when the action
applies (a session boundary), what happens to resting orders (adjust price
and quantity, or cancel as many venues do), the reference prices and
collars, the bots' anchors and pm-market-sim's model, and how pm-index takes
part. Its first test, written before any code, is an acceptance test: a 2:1
split at a session boundary leaves a two-name index level unchanged after
the next trade, and every resting order of the symbol is adjusted or
cancelled as decided. The design splits the implementation into its own
WPs.

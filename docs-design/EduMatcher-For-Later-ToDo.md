Version: 1.0.0

Date: 2026-11-11

Status: Design and Research Proposal

# EduMatcher — For Later ToDo

Global findings that fall outside the work package that uncovered them. They
are recorded here so they are not forgotten; each one is picked up later as
its own piece of work.

## Status

| ID | Date | Area | Finding | Priority | Status |
|----|------|------|---------|----------|--------|
| L001 | 2026-11-11 | sim_forensics / msgen | pm-sim-forensics hard-codes 185 topic literals and is exempt from the literal gate | Low | Open |
| L002 | 2026-11-11 | trader-gui | `formatChangePct` shows "-0.00%" (and "+0.00%" for zero) for a change that rounds to zero | Low | Open |
| L003 | 2026-11-13 | docs (operator guide, quick start, participant guide) | Container install has seven web applications (Clearing GUI on 8096), the books say six / 8090–8095 | Low | Open |
| L004 | 2026-11-13 | pm-config-gen | `[HINT] Validate with: poetry run python -c … Path("engine_config.yaml")` is wrong for installed users and names the wrong file | Low | Fixed (Config-Tools review WP-CFG04) |
| L005 | 2026-11-13 | pm-cverifier | Header counts `Semantic: 2 warnings` while the verdict says `1 WARNING` (the INFO M004 is counted as a warning) | Low | Fixed (Config-Tools review WP-CFG07) |
| L006 | 2026-11-13 | consoles / pm-mm-bot | Prices printed as raw floats: `149.8`, `@149.93333333333334`, `book mid=150.51999999999998` | Low | Open |
| L007 | 2026-11-13 | docs (operator guide, persistence) | Two diagrams say DAY combo parents are not persisted; the engine persists and restores them on a same-day restart | Low | Open |
| L008 | 2026-11-13 | pm-admin / pm-admin-cli | `BOOK` prints `Last trade: 150.0 × None` after an engine restart (restored price, unknown quantity) | Low | Open |
| L009 | 2026-11-13 | ExchangeCommandClient / pm-admin / pm-admin-cli | An illegal session transition prints `TIMEOUT`, although the engine answers on `session.transition_ack` (REST shows `409` with the reason) | Medium | Open |
| L010 | 2026-11-13 | pm-api-gwy | Once hung at shutdown on "Waiting for background tasks to complete"; second Ctrl-C needed (not reproduced) | Low | Fixed (API Gateway review WP-AGW01) |
| L011 | 2026-11-13 | pm-alf-gwy | A client that half-closes (`printf … \| nc`) loses the replies still on their way from the engine | Low | Open |
| L012 | 2026-11-13 | engine (combo/OCO validation) | `TRAILING_STOP is not supported on a combo leg: it needs trail_offset` is shown even when `LEG0.TRAIL=` was given | Low | Open |
| L013 | 2026-11-13 | pm-stats-cli (CLIs) | `pm-stats-cli daily \| head` ends with a `BrokenPipeError` traceback | Low | Open |
| L014 | 2026-11-13 | pm-mm-bot | With `--anchor-sim` the bot still needs a two-sided book or a range to start; it could start from the market model's value | Low | Open |
| L015 | 2026-11-13 | pm-alf-gwy / pm-orders | ALF `QBOOT` lines carry an empty `STATUS=`; `pm-orders` shows `?` in every column of a rejected order | Low | Open |
| L016 | 2026-11-13 | docs (participant combo guide) | Introduction promises atomic all-or-none execution for combos, although AON is an entry guard and later legs can fill independently | Medium | Open |
| L017 | 2026-11-13 | CLIs (`health -q`) | `health -q` exits `-1` (status 255) while the non-quiet path exits 1, in four CLIs | Low | Open |
| L018 | 2026-11-13 | trader-gui (admin order detail) | A 404 from the order-audit endpoint shows "No audited events for this order." without the index's reach (`indexed_through`), so an order newer than the last index build looks unknown | Low | Open |
| L019 | 2026-11-14 | pm-clearing (close snapshots) | `position_close_snapshot` is never pruned and keeps every flat position: one full position table per day in `clearing.db` and in every nightly backup | Low | Open |
| L020 | 2026-11-14 | engine / market sim / bots (corporate actions) | A split or dividend is applied to the index only; nothing adjusts the market's price, so the next trade moves the index by the split factor | Medium | Open |
| L021 | 2026-11-14 | pm-engine (halts) | Halts are not persisted: an engine restart silently clears every circuit-breaker and operator halt, so a symbol an operator halted trades again after a restart, with no resume published | Medium | Open |
| L022 | 2026-11-14 | pm-engine / subscribers (end of a run) | Trades lost just before an engine stop are undetectable downstream: the next run starts a new id sequence, and `system.eod` does not say which id the run ended at | Medium | Open |
| L023 | 2026-11-14 | pm-clearing (repair) | No way to repair `clearing.db` once a feed gap is known: nothing rebuilds the ledger from the audit trail | Medium | Open |
| L024 | 2026-11-14 | engine / log-server loaders | Loaders accept values they mean to refuse: `tick_decimals: true`, `outstanding_shares: true`, `max_order_qty: 1.5` (truncated to 1), `schedule: 'x'`, `log_server.enabled: 'x'`, `.nan` where `> 0` is required | Low | Open |
| L025 | 2026-11-14 | docs (training guide ch. 17) | Says the static collar "only takes effect from the first trades on"; the engine registers a collar only at start-up when a reference price is known | Low | Open |
| L026 | 2026-11-14 | pm-engine (order validation) | A TRAILING_STOP with a negative `trail_offset` and no prior trade is refused as "Trailing stop requires STOP= or a prior trade price", not as an invalid offset | Low | Open |
| L027 | 2026-11-14 | pm-balf-gwy (restart) | After a pm-balf-gwy restart a participant's resting orders are unreachable over BALF: no order ids, no fills, no cancel, and BALF has no order query | Medium | Open |
| L028 | 2026-11-14 | pm-engine (book requests) | `book.snapshot_request` for a symbol the engine holds no book for gets no answer, so a subscriber that cached the book before an engine restart cannot learn it is now empty | Low | Open |
| L029 | 2026-11-15 | pm-engine (heartbeats) | A session that never sent a heartbeat is never expired, so a client that connects and dies (or is answered after it gave up) holds its gateway id until an admin disconnect or an engine restart | Medium | Open |
| L030 | 2026-11-15 | pm-engine (admin queries) | Position and order queries about a disconnected gateway answer empty lists, so `GET /admin/gateways/{id}/positions` and `/orders` show a logged-off trader with resting orders as flat with none | Medium | Open |
| L031 | 2026-11-15 | pm-engine (gateway connect) | A refused `gateway_connect` for an unknown id still creates a session, a metrics label and a published topic that are never freed: 337 B per refused id, reachable by any client through ALF `HELLO` | Low | Open |
| L032 | 2026-11-15 | pm-engine (quotes) | `quote.new` carries `tick_decimals` but the engine ignores it, so a client with a wrong tick registry rests its quote at 1/100 or 100× the intended price without a reject | Medium | Open |
| L033 | 2026-11-15 | pm-api-gwy (index and sim listeners) | The `IndexClient` and `SimClient` receive threads end on a ZeroMQ error while the process keeps serving: index history and the sim/news streams then go quiet with no ERROR and no exit | Low | Open |
| L034 | 2026-11-15 | CLIs (`-q`) | `-q`/`--quiet` is documented as "Reduce output to warnings/errors" but sets WARNING, the default, so it changes nothing (5 entry points and pm-help's common log options) | Low | Open |
| L035 | 2026-11-15 | pm-dc-gwy (engine feed) | The drop-copy subscriber keeps ZeroMQ's default 1000-message RCVHWM and subscribes to every participant, so a burst for unwatched IDs drops watched fills with no log or metric | Medium | Moved to DC review WP-DCG01 (done 2026-11-15) |
| L036 | 2026-11-15 | pm-md-gwy (loop, shutdown) | Once a descriptor reaches 1024 `select` fails every pass and no client is read again (WARNING ~100/s); a stop closes every session with no `EXIT` and drops queued lines | Low | Open |
| L037 | 2026-11-15 | pm-engine (drop copy) | For an uncross print (`aggressor_side` AUCTION) both drop-copy events carry `liquidity_flag` MAKER, while `drop_copy.yaml` says exactly one of the two is TAKER | Low | Open |

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
is now WP-DCG03 of the DC gateway review (2026-11-15); this entry remains for
pm-md-gwy.

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


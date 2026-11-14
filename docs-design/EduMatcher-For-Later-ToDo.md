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
| L004 | 2026-11-13 | pm-config-gen | `[HINT] Validate with: poetry run python -c … Path("engine_config.yaml")` is wrong for installed users and names the wrong file | Low | Open |
| L005 | 2026-11-13 | pm-cverifier | Header counts `Semantic: 2 warnings` while the verdict says `1 WARNING` (the INFO M004 is counted as a warning) | Low | Open |
| L006 | 2026-11-13 | consoles / pm-mm-bot | Prices printed as raw floats: `149.8`, `@149.93333333333334`, `book mid=150.51999999999998` | Low | Open |
| L007 | 2026-11-13 | docs (operator guide, persistence) | Two diagrams say DAY combo parents are not persisted; the engine persists and restores them on a same-day restart | Low | Open |
| L008 | 2026-11-13 | pm-admin / pm-admin-cli | `BOOK` prints `Last trade: 150.0 × None` after an engine restart (restored price, unknown quantity) | Low | Open |
| L009 | 2026-11-13 | ExchangeCommandClient / pm-admin / pm-admin-cli | An illegal session transition prints `TIMEOUT`, although the engine answers on `session.transition_ack` (REST shows `409` with the reason) | Medium | Open |
| L010 | 2026-11-13 | pm-api-gwy | Once hung at shutdown on "Waiting for background tasks to complete"; second Ctrl-C needed (not reproduced) | Low | Open |
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


# EduMatcher — Key Component Review: Fix Workplan

Addresses every finding in
[`reviews/EduMatcher-Key-Component-Review.md`](reviews/EduMatcher-Key-Component-Review.md)
(35 findings across auction, stats, clearing, index, engine, ALF, BALF and API
gateway).

Each finding was re-validated against the current source before this plan was
written. Result: **34 CONFIRMED**, **1 PARTIALLY CONFIRMED** (C5), **0 refuted**,
**0 already fixed**. Validation evidence is summarised in §3.

One work package (WP) at a time. Every WP ends with its new regression tests
green, `make _check` plus the full suite green, a holistic review, and a
proposed commit message. The maintainer commits.

**Test-first is mandatory in this plan.** Every WP starts by writing a test that
*fails* on today's code and demonstrates the finding. No fix is accepted without
a test that would have caught the original defect. See §4 for why that rule
exists.

Started: 2026-11-03

---

## 1. Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit)

| # | WP | Content | Findings | Sev | Depends on | Est. | Status | Done on |
|---|----|---------|----------|-----|------------|------|--------|---------|
| 0 | K0 | Shared reproduction harness: restart, failure injection, multi-actor and malformed-value fixtures | — | — | — | 1.5 d | ☑ | 2026-11-03 |
| 1 | K1 | Auction: OCO sibling must not fill in the same uncross; auction honours SMP | A1, A2 | High | K0 | 1.5 d | ☑ | 2026-11-03 |
| 2 | K2 | Engine: AON combo preflight must account for SMP | E1 | High | K0 | 1 d | ☑ | 2026-11-03 |
| 3 | K3 | Engine: `displayed_qty` omitted on the direct order path | E2 | Med | K0 | 0.5 d | ☑ | 2026-11-03 |
| 4 | K4 | Clearing: commit before ledger mutation; durable duplicate protection | C1, C2 | High | K0 | 1.5 d | ☑ | 2026-11-03 |
| 5 | K5 | Clearing: warm-start must fail loudly; malformed auth/bye must not kill the receive loop | C3, C7 | Med | K4 | 0.5 d | ☑ | 2026-11-03 |
| 6 | K6 | Clearing: tick-precision changes and precision-aware query normalisation | C4, C5 | Med | K4 | 1 d | ☑ | 2026-11-03 |
| 7 | K7 | Index: state must be sufficient to restore the live calculator | I1 | High | K0 | 1.5 d | ☑ | 2026-11-03 |
| 8 | K8 | Index: non-finite prices, last-constituent delist atomicity, handler isolation | I2, I3, I4 | Med | K7 | 1 d | ☑ | 2026-11-03 |
| 9 | K9 | Stats: duplicate trades and same-millisecond index updates | S1, S4 | Med | K0 | 1 d | ☑ | 2026-11-03 |
| 10 | K10 | Stats: book snapshots use event time; snapshot baseline survives restart | S2, S3 | Med | K9 | 0.75 d | ☐ | |
| 11 | K11 | BALF: symbol-metadata readiness gate; engine-restart session reconciliation | B1, B2 | High | K0 | 1.5 d | ☐ | |
| 12 | K12 | BALF: per-request correlation tags; `EVICT_OLD` covers pending sessions | B3, B4 | Med | K11 | 1 d | ☐ | |
| 13 | K13 | API gateway: API key must never be used as a bus correlation id | P1 | High (sec) | K0 | 0.5 d | ☑ | 2026-11-03 |
| 14 | K14 | API gateway: recoverable replace (cancel succeeded, replacement failed) | P2 | High | K0 | 1 d | ☐ | |
| 15 | K15 | API gateway: rebalance `command_id` matching, restart de-auth, per-symbol replay | P3, P4, P5 | Med | K13 | 1 d | ☐ | |
| 16 | K16 | Event-loop fairness: ALF writability/backpressure, permanent socket errors, BALF drain budget, blocking SQLite in async routes | G1, G2, B5, P6 | Med | K0 | 1.5 d | ☐ | |
| 17 | K17 | Input strictness: integer/NaN config validation, ALF stale symbol set after restart | G3, G4, B6 | Low | — | 0.5 d | ☑ | 2026-11-03 |
| 18 | K18 | Complexity and hot-path cost | A3, C6, E3, I5, P7, S5 | Low | K1–K16 | 1.5 d | ☐ | |
| 19 | K19 | Retrospective: close the systemic test-suite gaps that let all 35 findings through | — | — | K1–K18 | 2 d | ☐ | |

Total ≈ 21 d. Execution order is the table order; K0 is a prerequisite for
almost everything and K19 must come last so it can generalise from the concrete
defects.

### 1.1 Finding → WP index

| Finding | WP | Finding | WP | Finding | WP |
|---|---|---|---|---|---|
| A1 | K1 | C5 | K6 | E3 | K18 |
| A2 | K1 | C6 | K18 | G1 | K16 |
| A3 | K18 | C7 | K5 | G2 | K16 |
| S1 | K9 | I1 | K7 | G3 | K17 |
| S2 | K10 | I2 | K8 | G4 | K17 |
| S3 | K10 | I3 | K8 | B1 | K11 |
| S4 | K9 | I4 | K8 | B2 | K11 |
| S5 | K18 | I5 | K18 | B3 | K12 |
| C1 | K4 | E1 | K2 | B4 | K12 |
| C2 | K4 | E2 | K3 | B5 | K16 |
| C3 | K5 | | | B6 | K17 |
| C4 | K6 | | | P1–P7 | K13–K16, K18 |

---

## 2. Execution rationale

The order is not severity order; it is *risk-of-rework* order.

1. **K0 first.** Nearly every finding is invisible today because the test suite
   cannot express the precondition (a restart, a failed write, a second
   gateway, a malformed value). Building those capabilities once avoids
   re-inventing them in fifteen WPs.
2. **Matching-engine truth next (K1–K3).** Auction, combo and iceberg defects
   corrupt the trade record itself. Everything downstream — stats, clearing,
   index — records whatever the engine produced, so fixing recorders before the
   engine would validate against wrong inputs.
3. **Then durable state (K4–K10).** Clearing, index and stats all share one root
   cause: *in-memory state is mutated before, or independently of, the durable
   record*, so behaviour differs across a restart. These WPs are grouped so the
   same restart-equivalence oracle can be reused.
4. **Then session/edge boundaries (K11–K15).** Gateway defects are
   client-visible but contained; they depend on the engine semantics settled in
   K1–K3.
5. **Then liveness (K16) and strictness (K17).** Neither changes trading
   semantics, so they can land late without blocking correctness work.
6. **Then cost (K18).** Complexity fixes are safest once behaviour is frozen by
   the new regression tests.
7. **K19 last.** Only after fixing all 35 does the common shape of the misses
   become provable rather than speculative.

---

## 3. Validation summary

All 35 findings were re-checked against the current source.

| Component | Confirmed | Partial | Refuted | Notes |
|---|---|---|---|---|
| Auction | 3 | 0 | 0 | A3 complexity is even documented in the docstring |
| Stats | 5 | 0 | 0 | |
| Clearing | 6 | 1 (C5) | 0 | C5: `query_exposure`/`query_symbols` confirmed; other aggregate views already normalise per row |
| Index | 5 | 0 | 0 | I1 is worse than reported: a runtime add/delist makes the process *unstartable* |
| Engine | 3 | 0 | 0 | |
| ALF gwy | 4 | 0 | 0 | |
| BALF gwy | 6 | 0 | 0 | |
| API gwy | 7 | 0 | 0 | |

Two findings are more severe than their review grading suggests and are treated
as High in this plan:

- **I1** — a runtime `add`/`delist` persists a constituent list that
  `_load_state()` rejects, so the index process will not restart at all until
  someone passes `--reset` (and silently loses the divisor). This is an
  availability bug, not only an accuracy bug.
- **P1** — the API key is placed on the engine bus *and* echoed in the reply
  topic. That is credential disclosure to every bus subscriber, not merely a
  correlation-hygiene issue.

---

## 4. Why 10,000+ tests found none of these — a self-critical analysis

This is the most important section of the plan. 35 real defects survived a
suite of over 10,000 tests at 85 %+ line coverage. Every one of the defective
lines **is executed** by the existing tests. Coverage was never the problem.
Nine systemic weaknesses explain all 35 misses, and K19 exists to close them.

### 4.1 Fixtures are mono-everything

Almost every fixture uses *one* of each thing: one gateway id, one symbol, one
precision, one connection, one order leg, one index constituent beyond the
minimum. Whole classes of defects are simply not constructible.

- A2, E1 need **two orders from the same gateway**; SMP tests
  (`tests/test_engine_oco_smp.py:83`) use the continuous path only, and combo
  tests (`tests/test_combo.py:635`) always use distinct gateways.
- P5 needs **two symbols interleaved** on one sequence stream;
  `tests/test_api_gateway_market_snapshot.py:140` uses AAPL alone — the review
  itself notes "the existing replay test uses only one symbol".
- C4, C5 need **two tick precisions**;
  `tests/test_clearing_ledger.py:385` uses one.
- I2 needs **exactly one constituent**;
  `tests/test_index_calculator.py:168` always delists one of several.
- B4 needs **two connections for one gateway id**;
  `tests/test_balf_gwy_robustness.py:675` authenticates the first before
  opening the second.

**Lesson:** a passing test with N=1 proves almost nothing about an exchange,
which is by definition a multi-party, multi-symbol system.

### 4.2 Restart is tested as a feature, not as an equivalence property

There are restart tests — but they restart with *well-behaved* data and assert
that a specific field survived. Nobody asserts the general property
*"observable state after restart == observable state before restart"*.

- `tests/test_clearing_advanced_integration.py:583` restarts and checks
  positions — but never after a *failed* flush (C1) or a *replay* (C2).
- `tests/test_stats_trading_day.py:379` restarts with distinct timestamps, so
  the same-millisecond collision (S4) never occurs.
- `tests/test_index_main.py:72` asserts a state file *exists*; no test loads it
  back and compares the level (I1).
- B2, P4 have **no engine-restart test at all** on those gateways.

**Lesson:** restart needs a reusable oracle (snapshot → restart → snapshot →
diff), not per-field spot checks.

### 4.3 No failure injection

Not one test makes a write fail, a socket reset, a send block, or a queue
overflow — so every "what if this fails midway" path is unverified.

- C1 (`flush_batch` raises), C3 (`fetch_all_positions` raises), P2
  (`send_new_order` raises after a successful cancel), G1 (`send` raises
  `BlockingIOError`), G2 (`recv` raises `ECONNRESET`) are all one-line
  monkeypatches away from being provable — and none exists.
- `tests/test_api_gateway_backpressure.py:145` *does* test `send_new_order`
  backpressure, but only standalone, never inside the replace sequence where it
  is destructive.

**Lesson:** the happy path is the cheap half. Partial-failure behaviour is where
money is lost, and it needs deliberate fault injection.

### 4.4 "Malformed" means malformed *encoding*, never malformed *values*

Robustness tests feed garbage bytes and assert no crash. They never feed a
well-formed message with a hostile field value.

- I3: `tests/test_index_main_runtime.py:121` covers decode failures — exactly
  the case that *is* already handled — while `int(None)` in a decoded payload
  kills the process.
- I4: `tests/test_index_calculator.py:82` tests `price = 0.0` but never
  `nan`/`inf`, which pass `price <= 0`.
- C7: `tests/test_clearing_main.py:371` tests a malformed *trade*, the one
  handler that is guarded.
- E2: iceberg tests always pass `displayed_qty` explicitly
  (`tests/test_auction_icebergs.py:70`), so the omitted-field path is never
  built.
- G4, B6: config tests use valid integers only.

**Lesson:** the boundary is the *value domain* (None, NaN, ±inf, absent
optional, wrong scale), not the wire format.

### 4.5 Assertions are too coarse — aggregates hide per-entity errors

Several tests execute the defect and still pass, because they assert a total.

- A1: `tests/test_auction.py:262` asserts aggregate matched quantity, which is
  identical whether one OCO leg or both filled.
- S1: `tests/test_stats_and_orders.py:249` is literally named
  `test_duplicate_trade_id_ignored` — and asserts only
  `len(trade_log) == 1`. The duplicate *was* delivered, the rollup *was*
  double-counted, and the test passed anyway.

**Lesson:** assert the per-entity invariant (which order filled, what the rollup
says), not the sum. S1 is the clearest evidence that a test can exercise a bug
and certify it.

### 4.6 Tests observe in-memory API state instead of durable artefacts

Where a defect lives in the gap between memory and storage, observing memory
cannot see it.

- S3: `tests/test_stats_and_orders.py:320` *seeds* `_last_snap_mid` by hand,
  which is precisely the step the production restart path is missing.
- C2: `tests/test_clearing_main.py:398` counts archive rows, not ledger P&L.
- P1: no test asserts what is actually put **on the bus** — the reply topic
  containing the API key is never inspected.

**Lesson:** test through the durable/wire boundary the next process actually
reads. If a test pre-populates internal state to make itself work, that is a
hint that production lacks the same step.

### 4.7 Concurrency and ordering are never adversarial

Every request/response test is send-one, await-one, in order.

- B3 needs two pipelined cancels before the first reply; P3 needs two
  rebalances resolved out of order. Both are one `await` away from being
  testable; neither test exists
  (`tests/test_balf_gwy_integration.py:1260`,
  `tests/test_api_gateway_index_events.py:52`).

**Lesson:** any correlation table needs an explicit out-of-order and
pipelining test; FIFO-resolution code must be proven against non-FIFO replies.

### 4.8 Tests were written from the implementation, not from the contract

Many tests read as a transcript of what the code does. They are therefore
immune to exactly the bugs that were present when they were written — they
encode the defect as expected behaviour.

- The A3 `O(P^2)` complexity is *documented in the docstring* and asserted
  nowhere; the docstring even claims the function runs once per phase, while
  `main.py` calls it once per symbol per second.
- `_on_book`'s comment says "a book message carries no timestamp of its own"
  (S2) — the message schema has carried `ts_ns` since. The comment was tested;
  the contract was not.

**Lesson:** derive assertions from the spec/message schema (`spec/`), not from
the code under test. Where code and comment disagree with the schema, the
schema wins.

### 4.9 Nothing asserts cost

A3, C6, E3, I5, P7 and S5 are all "works, but scales wrongly". No test
instruments call counts, iteration counts or query plans, so any O(n²) can be
introduced freely as long as the result is right.

**Lesson:** complexity is a behaviour. Assert it with call counters and
`EXPLAIN QUERY PLAN`, not with wall-clock benchmarks (which are flaky in CI).

### 4.10 The headline number is misleading

10,000+ tests were generated from a few hundred fixture shapes. The suite is
**wide but shallow**: it has enormous *line* coverage and very little
*state-space* coverage. Test count is a vanity metric; the actionable metrics
are mutation score, restart-equivalence coverage, and fault-injection coverage —
none of which the project currently measures. K19 introduces them.

---

## 5. Work packages

Each WP lists the finding, the required failing test (written first), the fix,
and explicit done criteria. "Suite green" below always means:
`poetry run black --check src tests && poetry run flake8 src tests && poetry run
mypy src tests && poetry run pyright src tests && poetry run pytest tests/ -n
logical --cov=src/edumatcher --cov-fail-under=85`.

### K0 — Shared reproduction harness

**Why first:** §4.1–§4.4 — the suite currently cannot express the preconditions
of most findings.

Steps:
1. `tests/support/restart.py`: a `restart_equivalence` helper — capture a
   component's durable state + derived observables, restart from disk, capture
   again, diff. Usable by clearing, stats, index, engine.
2. `tests/support/faults.py`: context managers to make a named callable raise
   once (`fail_once`), raise always, or raise a given `OSError`/`errno`.
3. `tests/support/actors.py`: fixtures for two gateway ids, two symbols with
   *different* `tick_decimals`, and a single-constituent index.
4. `tests/support/badvalues.py`: a shared parametrisation set —
   `None`, `float("nan")`, `float("inf")`, `-0.0`, absent optional key,
   oversized string, non-integral float — for value-domain fuzzing of decoded
   payloads.
5. `tests/support/counting.py`: call/iteration counters and an
   `assert_query_plan_has_no_temp_btree(conn, sql)` helper for §4.9.

Done when:
- All five modules exist with their own unit tests and are importable from
  `tests/conftest.py`.
- A smoke test demonstrates each helper against an existing, *correct*
  component (proving the helper itself does not false-positive).
- Suite green; no production code changed in this WP.

---

### K1 — Auction: OCO atomicity and self-match prevention (A1, A2 · High)

**A1** `engine/auction.py:305-319` passes `both_resting=True` to `_apply_fill`,
which suppresses the OCO callback at `engine/order_book.py:2024-2039`; the
uncross loop therefore keeps matching and can fill both legs before
`main.py:5935-5951` publishes and cancels the sibling.
**A2** the uncross path (`auction.py:278-319`) never checks `gateway_id` /
`smp_action`, unlike continuous matching at `order_book.py:1800-1825`;
`_auction_levels` (`auction.py:71-91`) also counts self-matchable quantity in
the published indicative.

Steps:
1. Failing test A1: OCO with two sell LIMIT legs at 100 and 101, 20 units of
   buy interest at 101, run an uncross. Assert exactly one leg trades, the
   sibling is cancelled, total OCO fill == 10.
2. Failing test A2: same-gateway bid and ask with `smp_action != NONE` resting
   in an auction. Assert the published indicative `eq_qty` excludes the pair,
   the uncross emits no trade, and both orders are resolved per policy.
3. Fix A1: make the uncross loop OCO-aware — resolve sibling cancellation
   inside the loop (or exclude already-resolved OCO siblings from subsequent
   iterations) rather than relying on the post-loop callback.
4. Fix A2: apply the same SMP decision function used by the continuous sweep in
   both `execute_uncross` and `_auction_levels`, so the indicative and the
   uncross agree.
5. Extend `tests/engine_invariants.py` with an invariant asserted after every
   uncross: no two legs of one OCO group have fills, and no trade has
   `buy.gateway_id == sell.gateway_id` when either side's `smp_action != NONE`.

Done when:
- Both new tests fail on `HEAD~` and pass after the fix.
- The new invariants run in every existing auction test, not only the new ones.
- Indicative `eq_qty` equals actual uncross quantity in a randomised
  multi-gateway auction test.
- Suite green.

---

### K2 — Engine: AON combo preflight must account for SMP (E1 · High)

`engine/main.py:5316-5325` computes `fillable_quantity()` per leg;
`order_book.py:1420-1437` sums *all* resting quantity, while execution applies
SMP at `order_book.py:1798-1825`. An AON combo can therefore pass entry and be
partially executed.

Steps:
1. Failing test: external liquidity for leg 1, same-gateway liquidity for leg 2,
   AON combo from that gateway with `CANCEL_AGGRESSOR`. Assert no child fills,
   no trade emitted, combo rejected.
2. Fix: give `fillable_quantity()` an SMP-aware form (aggressor gateway id +
   `smp_action`) and use it in the AON preflight, so preflight and execution
   use one decision function.
3. Add the reverse case: `CANCEL_RESTING` must *also* be excluded from the
   preflight count, because the resting order is gone by execution time.

Done when:
- New tests fail before / pass after.
- An invariant in `tests/engine_invariants.py`: an AON combo is either fully
  filled or produces zero trades — asserted across all existing combo tests.
- Suite green.

---

### K3 — Engine: omitted `displayed_qty` on the direct order path (E2 · Med)

`models/order.py:334-336` leaves `displayed_qty = None`;
`order_book.py:578-589` then indexes the iceberg with 0 visible quantity while
`auction.py:248-252` falls back to the *full* remaining quantity.

Steps:
1. Failing test: deserialize an ICEBERG limit order with `displayed_qty`
   absent, rest it in a queue-only phase, uncross. Assert either a clean
   rejection at entry, or a consistent visible slice (level index == shown
   quantity, fill ≤ displayed slice).
2. Fix (decided 2026-11-03: derive-on-accept): `displayed_qty` is engine
   bookkeeping, not client input. `_handle_new_order` sets it to
   `min(visible_qty, remaining_qty)` after `from_dict`, replacing whatever the
   wire carried; an invalid `visible_qty` is still rejected by M7. The restore
   path keeps the strict guard in `OrderBook.process`. The field stays in the
   `order_new` schema (gateways emit `Order.to_dict()`); its doc says the
   engine ignores it.
3. Add a book invariant: `sum(level visible qty) == sum(_shown_qty(order))` at
   that level, checked after every rest/uncross.

Done when: new test fails before / passes after; the invariant is active in the
shared harness; suite green.

---

### K4 — Clearing: durable write ordering and duplicate protection (C1, C2 · High)

**C1** `clearing/main.py:615-631` calls `ledger.apply_trade()` for every
buffered trade *before* `flush_batch()` commits; a retry after a write failure
double-applies.
**C2** `clearing/main.py:535-548` keys a bounded in-memory LRU on
`(id, ts_ns)`, while the archive's identity is `id` alone
(`clearing/store.py:66-72`); restart, LRU eviction, or a replay with a changed
timestamp all bypass it, and `INSERT OR IGNORE` protects only the archive.

Steps:
1. Failing test C1: `fail_once` on `main.flush_batch`, call `_flush()`, retry.
   Assert the ledger and DB show one trade's quantity/P&L, not two.
2. Failing test C2 (three cases): (a) process trade, restart, replay same id —
   position unchanged; (b) force LRU eviction, replay — unchanged; (c) replay
   same `id` with a different `ts_ns` — unchanged.
3. Fix C1: make the flush atomic — either stage ledger deltas and apply them
   only after `flush_batch()` returns, or make retry idempotent by committing
   the applied-trade watermark in the same transaction as the ledger rows.
4. Fix C2: make dedup durable and key it on `id` only, consistent with the
   archive PK — e.g. check `trade_events` within the flush transaction, or keep
   a persisted applied-id set / monotonic watermark. The in-memory LRU may stay
   as a fast path but must not be the authority.

Done when:
- All four new cases fail before / pass after.
- A `restart_equivalence` (K0) assertion is added to clearing: positions and
  P&L are identical before and after a restart with an interleaved replay.
- A property test: applying a random trade stream twice, in any interleaving,
  yields the same ledger as applying it once.
- Suite green.

---

### K5 — Clearing: loud warm start, resilient receive loop (C3, C7 · Med)

**C3** `clearing/main.py:299-310` catches `Exception` around
`fetch_all_positions()`/`restore()` and continues with an empty ledger; the next
flush UPSERTs over persisted positions.
**C7** `_handle_gateway_auth` / `_handle_gateway_bye`
(`clearing/main.py:831-849`) call `from_dict()` outside any per-message
`try/except`; the dispatch loop guards only `decode()`
(`clearing/main.py:457-466`), so a malformed but decodable payload kills the
receive thread.

Steps:
1. Failing test C3: make `fetch_all_positions` raise; assert startup fails (or
   the process refuses to flush) rather than silently resetting positions.
2. Failing test C7: feed a malformed `gateway_auth` and a malformed
   `gateway_bye` (K0 bad-value set) followed by a valid trade; assert the loop
   is alive and the trade is processed.
3. Fix C3: a hydration failure is fatal — log and exit non-zero, or enter a
   read-only degraded mode that never writes positions. Silent empty-ledger
   start is not an option.
4. Fix C7: wrap handler dispatch in the same per-message guard used for trades,
   so *any* handler exception is logged and skipped.

Done when: both tests fail before / pass after; the bad-value parametrisation
covers every clearing topic handler; suite green.

---

### K6 — Clearing: tick precision correctness (C4, C5 · Med)

**C4** `clearing/ledger.py:372-384` assigns `pos.tick_decimals = tick_decimals`
and applies the new fill without rescaling the existing `avg_cost` /
`mark_price` / P&L stored in the old scale.
**C5** (partial) `clearing/store.py:1039-1047` orders by raw
`net_qty * mark_price` before CLI normalisation, and
`store.py:1071-1078` uses `MAX(tick_decimals)` across dates. Other aggregate
views already normalise per row.

Steps:
1. Failing test C4: trade at precision 2, then the same `(gateway, symbol)` at
   precision 4. Assert either an explicit rejection or a correct conversion of
   the stored values.
2. Failing test C5: two symbols at precisions 2 and 4 whose *currency* notionals
   rank opposite to their raw tick values. Assert
   `query_exposure(sort="gross_notional")` ranks by normalised currency. Add a
   multi-date `query_symbols` case with differing precision per date.
3. Fix C4: on a precision change, convert the stored values to the new scale
   inside the same operation, or reject the trade with a clear error. Decide and
   document which; conversion is preferred as it keeps the venue running.
4. Fix C5: normalise inside the SQL (divide by `POWER(10, tick_decimals)`
   per row) before `ORDER BY`/`SUM`, and drop `MAX(tick_decimals)` in favour of
   per-row normalisation.

Done when: both tests fail before / pass after; a documented rule exists for
precision changes; suite green.

---

### K7 — Index: state sufficient to restore the calculator (I1 · High)

`index/main.py:252-270` persists only divisor, constituent list and last
prices; `_handle_trade()` never persists; share-changing corporate actions
persist the divisor but not `_outstanding_shares`; and `_load_state()`
(`main.py:223-239`) *rejects* a constituent list differing from static config —
so a runtime add/delist makes the process unstartable.

Steps:
1. Failing test (a): trade + share issuance → persist → new `IndexProcess` from
   the same state file → assert restored price, shares and level match.
2. Failing test (b): runtime `add` then `delist` → restart → assert the process
   starts with the changed constituent set (no `--reset` needed).
3. Fix: make the state file the authority for the *live* set — persist
   `outstanding_shares`, last prices (on a bounded cadence or at checkpoints),
   divisor, and the runtime constituent list; `_load_state()` must accept a
   constituent list that diverges from static config and log the divergence
   instead of raising. Keep `--reset` as the explicit override.
4. Decide and document the persistence cadence for trade-driven prices
   (every trade is too expensive; checkpoint + phase change + shutdown is the
   expected answer) and record the chosen contract in the design doc.

Done when:
- Both tests fail before / pass after.
- `restart_equivalence` (K0) is asserted for the index: published level before
  restart == published level after restart, for a scenario containing a trade, a
  split, an issuance, an add and a delist.
- Suite green.

---

### K8 — Index: value-domain and handler robustness (I2, I3, I4 · Med)

**I2** `index/calculator.py:226-243` deletes the constituent from every map and
*then* raises on zero aggregate cap, leaving the calculator empty while the
process reports a rejection.
**I3** `index/main.py:442-455`, `500-520` call `int(payload.get(...))` on
decoded payloads; `int(None)` raises `TypeError`, and the dispatch loop
(`main.py:808-821`) isolates only decode errors.
**I4** `calculator.py:117-125` tests `price <= 0.0`, which `nan` and `inf` both
pass; the poisoned value flows into `recalculate()` and is published.

Steps:
1. Failing test I2: single-constituent calculator, `delist_symbol()` must raise
   *and* leave the constituent and prior level intact.
2. Failing test I3: a decoded history request with `{"from_ts_ns": None}`, then
   a valid message; assert `run()` survives and processes the second. Repeat
   across every command handler using the K0 bad-value set.
3. Failing test I4: `price` of `"nan"` and `"inf"`; assert nothing is published
   and the stored price/level stay finite.
4. Fix I2: validate before mutating (compute the prospective cap first), or
   mutate a copy and swap on success.
5. Fix I3: wrap handler dispatch in a per-message guard *and* validate command
   fields through a typed parse that returns a reject, not an exception.
6. Fix I4: require `math.isfinite(price) and price > 0` at the calculator
   boundary and at `_handle_trade()`'s float conversion.

Done when: all three fail before / pass after; a published-level assertion
`math.isfinite(level)` is added to the index invariants; suite green.

---

### K9 — Stats: duplicate trades and same-millisecond index updates (S1, S4 · Med)

**S1** `stats/main.py:1481-1506` mutates the accumulator and writes
`daily_stats` before the `INSERT OR IGNORE` that discards the duplicate
`trade_id`.
**S4** `index_level_snapshots` has `PRIMARY KEY (ts, index_id)` at
millisecond resolution (`main.py:606-619`) and is written with
`INSERT OR IGNORE` after `_write_index_daily(acc)` (`main.py:1658-1668`), while
rehydration rebuilds OHLC/count from that incomplete table
(`main.py:1382-1420`).

Steps:
1. Failing test S1: deliver the same payload twice; assert one `trade_log` row
   **and** `daily_stats.trade_count == 1`, volume/turnover/VWAP of a single
   trade. (Note: `test_duplicate_trade_id_ignored` must be *strengthened*, not
   duplicated — see §4.5.)
2. Failing test S4: two index updates with identical `ts_ns` and different
   levels; assert the live rollup counts 2, then restart and assert the
   rehydrated rollup still counts 2 with the second level as close.
3. Fix S1: perform the `INSERT OR IGNORE` first and apply the accumulator
   update only when a row was actually inserted (`rowcount == 1`), inside the
   same transaction.
4. Fix S4: make the snapshot key collision-free (nanosecond `ts`, or
   `(ts, index_id, seq)`), or rehydrate count/close from a source that does not
   lose same-millisecond updates. Prefer the key change; record the schema
   migration.

Done when: both fail before / pass after; `restart_equivalence` holds for a
stats run containing duplicates and same-millisecond updates; suite green.

---

### K10 — Stats: event time and snapshot baseline (S2, S3 · Med)

**S2** `stats/main.py:1513-1519` uses `time.time()` with the comment "a book
message … carries no timestamp of its own", but the message carries `ts_ns`;
`main.py:1566` likewise stamps snapshots with receipt time.
**S3** `_last_snap_mid` (`main.py:960-963`) is never restored from
`price_snapshots`, so the first `pct_change` after restart is NULL
(`main.py:1561-1564`).

Steps:
1. Failing test S2: receipt time just after a trading-day boundary, payload
   `ts_ns` just before it; assert `daily_stats.date` and `price_snapshots.ts`
   use the *event* day.
2. Failing test S3: persist a snapshot with mid 100, restart, submit mid 110,
   assert `pct_change == 10.0`.
3. Fix S2: use `payload["ts_ns"]` when present, fall back to receipt time only
   when absent, and correct the stale comment.
4. Fix S3: restore `_last_snap_mid` from the latest persisted
   `price_snapshots` row per symbol at startup.

Done when: both fail before / pass after; the §4.6 rule is honoured (no test may
hand-seed `_last_snap_mid`); suite green.

---

### K11 — BALF: metadata readiness and engine-restart reconciliation (B1, B2 · High)

**B1** `balf_gwy/gateway.py:1010-1024` sends an accepted `LOGON_ACK` and *then*
requests symbols, while `gateway.py:552-554` already accepts `MSG_NEW_ORDER`;
`translate.py:85-90` calls `to_ticks_exact()` which falls back to the shared
2-decimal default. `_known_symbols` (`gateway.py:253-254`) is populated but
never consulted.
**B2** `gateway.py:266-270` subscribes to session-state and trade topics, but
`_dispatch_engine_event()` has no startup-recovery branch, so clients stay
authenticated to a session the restarted engine has lost.

Steps:
1. Failing test B1: authenticate, drain but do not answer
   `system.symbols_request`, submit a 3-decimal-symbol order. Assert either the
   correct tick value or a clear "metadata not ready" rejection.
2. Failing test B2: authenticate, publish the engine startup-recovery event,
   assert the client is logged out/disconnected and a subsequent order is not
   forwarded as authenticated.
3. Fix B1: gate order acceptance on symbol-metadata readiness — either delay
   `LOGON_ACK` until the symbols response is processed, or reject orders with an
   explicit code while `_known_symbols` is unpopulated. Never price against the
   default precision for an unknown symbol.
4. Fix B2: subscribe to and handle the engine startup-recovery event exactly as
   the ALF gateway does (`alf_gwy/gateway.py:1949-1959`), dropping lost sessions
   with a clear reason.

Done when: both fail before / pass after; a shared cross-gateway test asserts
ALF, BALF and API gateways all react to engine restart identically; suite green.

---

### K12 — BALF: request correlation and eviction (B3, B4 · Med)

**B3** `gateway.py:768-772` / `874-878` store one `_PendingRequest` per engine
UUID, so a pipelined second cancel/amend overwrites the first; no `request_tag`
is sent although the engine messages support one.
**B4** `_gateway_in_use()` (`gateway.py:1418-1426`) counts `auth_pending`
sessions, but eviction (`gateway.py:615-621`) looks only in
`_active_gateway_sessions`.

Steps:
1. Failing test B3: two cancels with different client order ids before either
   engine result; publish both results; assert two correctly correlated acks.
   Repeat for amends.
2. Failing test B4: under `EVICT_OLD`, connection A pending (no auth reply),
   connection B logs on with the same id; assert A is closed and only one
   engine connect remains effective.
3. Fix B3: send a per-request `request_tag` and key the pending maps on it;
   keep a list per engine UUID. Correlate results by tag.
4. Fix B4: make eviction consider pending sessions, and match auth replies by
   the requesting session's tag rather than "first pending found".

Done when: both fail before / pass after; a pipelining case is added to the
generic gateway contract tests; suite green.

---

### K13 — API gateway: API key off the engine bus (P1 · High, security)

`routers/reference.py:135-150` uses `session.gateway_id or session.api_key` as
the correlation id; for read-only sessions (no `gateway_id`) the raw key is sent
in the request and echoed in the reply topic, and keys over the engine's
64-character limit cannot match.

Steps:
1. Failing test: `fetch_reference_bundle()` with
   `Session(api_key="secret", gateway_id=None)`; capture `request_reference()`
   and `await_topic()` and assert neither argument contains the raw key and both
   equal `correlation_id(session)`.
2. Fix: use the hashed `correlation_id(session)` here, as the session and halts
   routes already do.
3. Repo-wide guard: a test that scans every engine-bound call site for use of
   `session.api_key` as a topic/correlation argument and fails on any match.

Done when: the test fails before / passes after; the repo-wide guard is in CI;
a note is added to the security section of the API gateway docs; suite green.

---

### K14 — API gateway: recoverable replace (P2 · High)

`routers/orders.py:544-580` cancels, then builds and sends the replacement;
if `send_new_order()` raises, `idempotency.py:138-143` forgets the entry, so the
retry re-cancels an already-cancelled order and never submits the replacement.

Steps:
1. Failing test: cancel ack succeeds, first `send_new_order()` raises
   (`fail_once`), retry with the same idempotency key. Assert the replacement
   *is* submitted and a second cancel is *not* issued.
2. Fix: persist a per-step record of the replace saga (cancel done /
   replacement submitted) in the idempotency entry, and make retry resume from
   the recorded step rather than restarting it. Do not forget entries whose
   cancel leg succeeded.
3. Add the inverse case: a retry after the replacement *did* succeed must return
   the original result, not submit a second order.

Done when: both cases fail before / pass after; the saga states are documented
in the REST API doc; suite green.

---

### K15 — API gateway: correlation, restart and replay (P3, P4, P5 · Med)

**P3** `index_client.py:216-227` resolves the oldest waiter on the shared
`index.rebalance_ack.<gateway_id>` topic without checking `command_id`.
**P4** `engine_client.py:481-489` clears `_authenticated` only on
`gateway_bye`; there is no startup-recovery handling.
**P5** `market_cache.py:199-216` compares a venue-wide sequence against a
per-symbol buffer, so interleaved symbols raise a false `ReplayMiss`.

Steps:
1. Failing test P3: two concurrent rebalances, reply B delivered before reply A;
   assert each caller gets its own `command_id`'s verdict.
2. Failing test P4: publish the engine startup-recovery event; assert the
   gateway id is de-authenticated and the next request performs
   `gateway_connect`.
3. Failing test P5: record AAPL 10, MSFT 11, AAPL 12; `resume_trades("AAPL",
   10)` returns only 12 with no `ReplayMiss`.
4. Fixes: match replies by `command_id`; handle the startup-recovery event
   (shared with K11); track a per-symbol sequence (or compare against the
   symbol's own retained sequence set) for replay detection.

Done when: all three fail before / pass after; the replay test is
parametrised over ≥ 2 symbols permanently (§4.1); suite green.

---

### K16 — Event-loop fairness and blocking I/O (G1, G2, B5, P6 · Med)

**G1** `alf_gwy/gateway.py:389-397` selects with timeout 0 whenever `_dirty` is
non-empty, and `gateway.py:563-567` leaves the session dirty on
`BlockingIOError` without registering for `EVENT_WRITE` → busy-spin.
**G2** the same handlers (`gateway.py:486-492`, `563-567`) swallow all
`OSError`, leaving a reset peer registered.
**B5** `balf_gwy/gateway.py:912-914` drains the SUB socket with no budget and
subscribes to topics dispatch never uses (`gateway.py:266-270`).
**P6** `api_gateway/routers/history.py:238-292` runs SQLite synchronously in
`async` handlers, unlike bootstrap's `asyncio.to_thread` pattern.

Steps:
1. Failing test G1: fake client socket whose `send()` raises `BlockingIOError`;
   assert the selector subsequently waits for `EVENT_WRITE` and that repeated
   flushes do not occur without write readiness.
2. Failing test G2: `recv()` raises `ConnectionResetError` → session removed and
   unregistered; same for `send()`, including `_dirty` cleanup.
3. Failing test B5: flood the SUB socket continuously; assert a client heartbeat
   and an idle timeout still occur within a bounded number of loop iterations.
4. Failing test P6: block the history query on a `threading.Event`; assert an
   unrelated coroutine makes progress before the query is released.
5. Fixes: register `EVENT_WRITE` on backpressure and clear it when the queue
   drains; classify permanent `errno`s (`ECONNRESET`, `EPIPE`, `ENOTCONN`,
   `EBADF`) as disconnects; give `_poll_engine_events()` a per-iteration budget
   and drop unused subscriptions; wrap history SQLite work in
   `asyncio.to_thread`.

Done when: all four fail before / pass after; no handler catches bare `OSError`
without classifying it; suite green.

---

### K17 — Input strictness (G3, G4, B6 · Low)

**G3** `alf_gwy/gateway.py:1949-1959` clears `_symbols_reply` on restart but not
`_known_symbols` / `_symbols_snapshot_loaded`, and `gateway.py:1491-1496` unions
rather than replaces.
**G4** `alf_gwy/config.py:41-50` and **B6** `balf_gwy/config.py:56-80` accept
floats for integer fields (`int(1.9) == 1`) and accept `NaN` for positive
timeouts (`nan <= 0` is false).

Steps:
1. Failing test G3: `_known_symbols = {"AAPL","OLD"}`, restart, deliver a
   snapshot containing only `AAPL`, assert `OLD` now fails validation.
2. Failing tests G4/B6: parametrised over *every* integer field —
   `port: 5565.9`, `max_connections: 1.9` must raise; `heartbeat_interval_sec:
   .nan` must raise.
3. Fixes: reset symbol state on restart and *replace* the set on each snapshot;
   reject non-integral numerics in `_as_int`; require `math.isfinite()` in
   `_as_float` before the positivity check.
4. Apply the same `_as_int`/`_as_float` rules to every other config module in
   the repo (grep for equivalent helpers) — this class of bug is not specific to
   the two gateways.

Done when: all tests fail before / pass after; the strict helpers are shared or
consistently duplicated across config modules; suite green.

---

### K18 — Complexity and hot-path cost (A3, C6, E3, I5, P7, S5 · Low)

| Finding | Location | Cost |
|---|---|---|
| A3 | `engine/auction.py:148-168`, called per symbol per second from `main.py:1061-1095` | O(P²) in price levels |
| C6 | `clearing/ledger.py:295-301` | O(all positions) per trade |
| E3 | `engine/order_book.py:2489-2497` | O(n²) stop cascade via `list.pop(0)` |
| I5 | `index/main.py:397-407` | full constituent scan per trade + eager `aggregate_cap()` in a disabled `log.debug` |
| P7 | `api_gateway/engine_client.py:540-548` | O(gateway caches) per public trade |
| S5 | `stats/main.py:1302-1307` | uncovered `ORDER BY quantity DESC` on rehydration |

Steps:
1. Write cost assertions *first*, using K0 counters (§4.9): iteration/call
   counts, not wall clock. For S5 assert `EXPLAIN QUERY PLAN` contains no
   `USE TEMP B-TREE FOR ORDER BY`.
2. Fixes: single-pass prefix-sum equilibrium scan (A3); symbol→positions index
   (C6); `collections.deque` for the stop cascade (E3); incremental aggregate
   cap and `log.isEnabledFor` guard — or lazy `%`-arg evaluation — (I5); update
   the shared last-price once instead of per cache (P7); add the covering index
   `(symbol, ts, quantity)` or equivalent (S5).
3. Correct the A3 docstring, which currently claims the function runs once per
   phase (§4.8).

Done when: every cost assertion fails before / passes after; no behavioural test
changes; suite green.

---

### K19 — Retrospective: close the systemic gaps (§4)

The point of this WP is that fixing 35 defects changes nothing if the suite that
missed them stays the same.

Steps:
1. **Mutation testing on the hot modules.** Add `mutmut` (or `cosmic-ray`) over
   `engine/auction.py`, `engine/order_book.py`, `clearing/ledger.py`,
   `index/calculator.py`, `stats/main.py`. Record a baseline mutation score and
   gate CI on "no regression", not on an absolute number.
2. **Restart-equivalence matrix.** Promote K0's helper to a required check:
   every stateful process (engine, clearing, stats, index) has a
   before/after-restart equivalence test over a scenario that includes a trade,
   a duplicate, a corporate action and a phase change.
3. **Fault-injection matrix.** Every durable write, every socket operation and
   every engine send must have at least one "fails once, then succeeds" test.
   Track the list explicitly; an unlisted call site fails the check.
4. **Value-domain fuzzing.** Run K0's bad-value parametrisation against every
   topic handler in every process. A handler that raises out of its loop is a
   failure.
5. **Multi-actor defaults.** Change the shared fixtures so the *default*
   scenario has two gateways, two symbols with different precisions, and two
   index constituents. Single-actor fixtures become the explicit exception.
6. **Invariant library.** Consolidate the invariants added in K1–K3 (OCO
   exclusivity, no self-match, AON atomicity, visible-quantity consistency,
   finite index level, ledger idempotence) into one module asserted by the
   harness after *every* scenario, not per test.
7. **Spec-derived assertions.** For the message fields involved in S2 and E2,
   add a check that the handler consumes every field the `spec/` schema
   declares, so stale comments like "carries no timestamp" cannot survive.
8. **Retire the vanity metric.** Replace "10,000+ tests" in the README/docs with
   the metrics that matter: mutation score, restart-equivalence coverage,
   fault-injection coverage, invariant count.
9. Write up §4 as a permanent testing-guidelines document under `docs-design/`
   and link it from the contributor docs.

Done when:
- Mutation baseline recorded and gated in CI.
- Each of items 2–7 has at least one failing-then-passing demonstration against
  a deliberately reintroduced defect (pick three of the 35 and prove the new
  machinery catches them).
- Testing-guidelines doc committed and linked.
- Suite green.

---

## 6. Risks

- **K4 and K9 change write ordering under load.** Both need a throughput check
  before and after; moving a dedup check into the flush transaction can cost
  more than it saves if done per trade.
- **K7 and K9 imply schema/state-format changes** (index state file, index
  snapshot key). Both need a migration note in `CHANGELOG.md` and a decision on
  whether existing stores are migrated or reset.
- **K11's readiness gate changes client-visible logon timing.** Delaying
  `LOGON_ACK` is the cleanest fix but is a protocol-behaviour change; the
  reject-until-ready alternative is less invasive. Decide explicitly before
  implementing.
- **K19 item 5 will churn many existing tests.** Expect a large, mostly
  mechanical diff; land it alone, after all fixes.

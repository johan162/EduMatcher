# EduMatcher — Matching Correctness and Test Quality: Workplan and Progress


Follows the test-quality review of 2026-10-21 (summary in §1). Fixes two
matching-engine bugs the review found (§2) and closes the test gaps that let
them through (§3). One work package (WP) at a time; each WP ends with a
holistic test run (`make _check` + the full test suite + `make test-e2e`), a
review for new insights, and a proposed commit message. The maintainer commits.

Started: 2026-10-21

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit)

| # | WP | Content | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|
| 1 | F1 | Fix bug A: auctions mishandle hidden iceberg quantity | Q1 | 1 d | ☑ | 2026-10-21 |
| 2 | F2 | Fix bug B: iceberg qty-decrease amend refills its peak with priority kept | Q2 | 0.5 d | ☑ | 2026-10-21 |
| 3 | T1 | Mutation-testing tool and baseline (`tools/mutate_engine.py`) | — | 1 d | ☑ | 2026-10-21 |
| 4 | T2 | Independent reference matcher (`tests/reference_matcher.py`) | F1, F2, Q3 | 3 d | ☑ | 2026-10-21 |
| 4b | F3 | Fix bug C: FOK partially fills under SMP CANCEL_AGGRESSOR/BOTH (found in T2) | — | — | ☑ | 2026-10-21 |
| 5 | T3 | Differential fuzz: `OrderBook` vs reference, trade-for-trade | T2 | 1.5 d | ☐ | |
| 6 | T4 | Dataset smoke test checked against the reference, not against itself | T2 | 0.5 d | ☐ | |
| 7 | T5 | Specification scenario tests for both sides (kills the surviving mutants) | T1 | 2 d | ☐ | |
| 8 | T6 | Extend the randomized invariant tests (stops, icebergs in auctions, crossing amends) | — | 1 d | ☐ | |
| 9 | T7 | In-process end-to-end trading test (ALF client → gateway → engine → fills/MD/clearing) | — | 2 d | ☐ | |
| 10 | T8 | Remove or strengthen weak-assertion tests | — | 1 d | ☐ | |
| 11 | T9 | Final mutation run, docs, CI gate decision | all | 0.5 d | ☐ | |

Total ≈ 14 d. F1/F2 come first so the reference matcher (T2) encodes the
corrected rules and the fuzzer (T3) does not start out red on known bugs. T1
comes early because every later test WP measures itself against its baseline.

## Per-WP checklist

1. Re-read the WP below; check the named files/functions still exist.
2. Write the failing test first (bug WPs: the repro from §2), then the fix.
3. Holistic test: `make _check`, the full `pytest` suite with `-n logical`,
   `make test-e2e`.
4. Test WPs: re-run `tools/mutate_engine.py` (from T1 on) and record the kill
   counts for the mutants the WP targets.
5. Review: what did implementation reveal? Fix code, and update this plan and
   later WPs where an assumption turned out wrong. Log it below.
6. Mark the WP ☑ here, propose a commit message, stop.

## Open decisions

| # | Question | Recommendation |
|---|---|---|
| Q1 | Does an iceberg's **hidden** quantity take part in an auction uncross? The docs do not say. | **Yes**, as on most real venues, but ranked behind visible quantity at the same price (the hidden part queues behind displayed orders, peak by peak). The indicative price/volume then has to include hidden quantity too, otherwise the published indicative differs from what the uncross prints. Alternative: hidden quantity sits out the auction, so equilibrium and execution both use displayed quantity only. That is simpler, but it is unusual and leaves hidden quantity unexecuted at a crossing price. |
| Q2 | After a qty-decrease amend on an iceberg, may the shown slice grow? | **No.** Shown = min(current shown, new remaining), so priority is kept honestly. A refill is a new peak and goes to the back of the queue, as on replenishment. `020-order-types.md:1074` ("displayed_qty is recalculated from `visible_qty`") gets reworded. |
| Q3 ☑ | The reference matcher must be written from the **documented** rules, not from `order_book.py`. Where the docs are silent (Q1, stop trigger evaluation after a multi-level sweep, iceberg aggressor resting with a partly used peak), whose rule wins? | Write each gap into the participant guide as part of T2, then implement both sides from that text. List each one in the insights log. |

---

## 1. Review summary (2026-10-21)

- 10,420 tests, coverage ≥ 85%. About 95% of the 7,170 test functions make
  substantive assertions. About 350 do not: no assertion, mock-called only, or
  only `isinstance`/`is not None`. Most of these are in
  `test_gateway_and_scheduler.py` (T8).
- **No independent check of matching.** `test_engine_dataset_smoke.py`
  compares `Engine` against a "paper trader" that is itself `OrderBook`
  (`tools/gen_verification_set.py`). It can only catch divergence in the
  engine layer, never a matching bug. `test_engine_determinism.py` proves the
  output is repeatable, not that it is correct.
- **Trade price and counterparty are rarely asserted.** Most matching tests
  check quantity and status only.
- **Randomized invariant tests** (`test_book_invariants_random_ops.py`) check
  structural consistency only. They generate no STOP, STOP_LIMIT or
  TRAILING_STOP orders and no crossing amends, the auction tier turns
  icebergs off, and they run 10 seeds × 120 steps.
- **Gateway and engine are never run together in CI.** Gateway integration
  tests use a fake engine, engine tests use fake sockets, and the container
  e2e tests are deselected by default.

### Mutation baseline

24 realistic bugs were injected one at a time into a scratch copy and the full
suite was run each time. Column "kills" = number of failing tests (0 = bug
survives). T1 turns this into a repeatable tool; T9 re-runs it.

| ID | Injected bug | Where | Kills |
|---|---|---|---|
| M01 | Trade prints at aggressor's limit instead of resting price | `_sweep` → `_apply_fill` price arg | 6 (none in plain matching tests) |
| M02 | Bids queue newest-first (time priority inverted, bid side) | `_rest` bid key | 3 |
| M03 | Limit BUY will not trade *at* its limit (off by one) | `_sweep` price check | 149 |
| M04 | Amend qty decrease loses priority | `amend_order` `priority_reset` | 5 |
| M05 | Amend qty increase keeps priority | `amend_order` `priority_reset` | 3 |
| M06 | BUY stop needs price strictly above stop | `_check_stops` | 8 |
| **M07** | **SELL stop needs price strictly below stop** | `_check_stops` | **0** |
| M08 | SELL trailing stop never ratchets | `_check_trailing_stops` | 4 |
| M09 | Stop already breached on entry is parked | `process` M2 branch | 1 |
| M10 | Stop cascade disabled | `process` cascade loop | 1 (only the 1000-link perf test) |
| M11 | Triggered BUY STOP_LIMIT becomes MARKET | `_check_stops` | 3 |
| M12 | FOK pre-check counts SMP-excluded own liquidity | `_fok_available_qty` | 1 |
| M13 | IOC remainder rests instead of cancelling | `_match_ioc` | 6 |
| M14 | Replenished iceberg peak keeps its time priority | `_reinsert_iceberg` | 2 |
| M15 | `aggressor_side` inverted on trades | `_apply_fill` | 6 |
| **M16** | **Auction tie-break maximises surplus** | `compute_equilibrium` | **0** |
| **M17** | **Auction picks highest price among full ties** (documented rule: lowest) | `compute_equilibrium` | **0** |
| M18 | Marketable amend not re-matched (book left crossed) | `Engine._handle_amend` | 2 |
| M19 | ATC orders not expired after closing auction | `Engine` session transition | 2 |
| M20 | DAY orders not expired at close | `Engine` session transition | 2 |
| M21 | Cancel ownership check removed | `Engine._handle_cancel` | 2 |
| M22 | SMP CANCEL_RESTING self-trades | `_sweep` | 9 |
| M23 | Passive iceberg filled beyond its shown slice (#17 regression) | `_sweep` `_passive_avail` | 5 |
| M24 | MARKET remainder cancelled silently | `_match_market` | 5 |

21 of 24 are caught, but 13 of those are caught by three tests or fewer,
often a single regression test from an earlier review. Buy and sell sides are
not tested symmetrically (M06 is caught by 8 tests, M07 by 0).

---

## 2. Bugs

### Bug A — auctions mishandle hidden iceberg quantity (two symptoms)

The equilibrium is computed from the price-level index (`_bid_qty`/`_ask_qty`),
which holds only each iceberg's **shown** slice. The uncross then fills
`min(bid.remaining_qty, ask.remaining_qty)`, which includes **hidden**
quantity, and `_apply_fill(both_resting=True)` takes the whole fill off that
price level's index total, even when the fill is larger than the shown slice
the index held.

**A1 — the price-level index is corrupted.** Repro (`OrderBook` + `execute_uncross`):

```
SELL ICEBERG 100 (show 10) @100   gw A     -- rested with match=False
SELL LIMIT    50           @100   gw B
BUY  LIMIT    60           @100   gw C
compute_equilibrium → eq 100, qty 60
execute_uncross     → one trade: ICEBERG × 60
ask index {100: 10}, but live = LIMIT 50 + iceberg shown 10 = 60    (I1 fails)
```

The LIMIT's 50 lots disappear from depth snapshots, from the next auction's
equilibrium and from `executable_at`. The iceberg's hidden part also executed
ahead of the displayed LIMIT at the same price.

**A2 — the published indicative differs from what is printed.** Repro:

```
SELL ICEBERG 100 (show 10) @100
BUY  LIMIT 60 @101
BUY  LIMIT  5 @100
indicative: 10 @ 101      executed: 60 @ 101
with hidden qty counted the equilibrium is 65 @ 100
```

So the price is wrong and the quantity differs from the published indicative.
It affects every `compute_equilibrium` caller: the scheduled uncross
(`main.py:5480`), the indicative publication (`main.py:940`, `3358`, `3440`)
and the reopen dry-run (`main.py:4819`).

**Fix (assuming Q1 = hidden quantity takes part, ranked behind visible).**

1. `auction.py:execute_uncross` — cap each pass at the iceberg's shown slice,
   exactly as `_sweep` already does for passive icebergs (finding #17):
   `avail = o.displayed_qty if o.order_type is ICEBERG else o.remaining_qty`
   for both the best bid and the best ask, and
   `fill_qty = min(bid_avail, ask_avail)`. `_apply_fill(both_resting=True)`
   already replenishes and re-queues a used-up peak to the back. With
   `fill_qty ≤ shown` its `_deduct_qty_index(..., fill_qty)` is then correct,
   so the loop naturally runs visible-first, then the hidden peaks in turn.
2. `auction.py:compute_equilibrium` and `executable_at` — build the demand and
   supply curves from **total** live resting quantity per price, not from the
   shown-only index. Add one helper,
   `_auction_levels(book) -> (bids, asks)`, that walks the live heap entries
   once (skipping invalid or dead entries, counting each order once, using
   `remaining_qty`), the same way `OrderBook.fillable_quantity` does. Auctions
   are rare, so O(n) is fine. Do **not** add a second persistent index: it
   would be one more structure to keep in sync (I1-style bugs).
3. Decide (in the F1 review) whether the published indicative may reveal
   hidden quantity. Under Q1 = yes it must, or indicative ≠ print again.
   Document it in `030-the-trading-day-and-auctions.md`.

**Tests (F1).**
- The two repros above as regression tests: assert the full trade list
  (counterparties, price, qty, in order) and `assert_book_invariants`.
- Visible-before-hidden ranking at one price: iceberg first in time, then a
  LIMIT. The uncross fills the iceberg's shown slice, then the LIMIT, then the
  iceberg's hidden peaks.
- Indicative == executed for a book with icebergs on both sides
  (engine level: the published `auction` indicative vs the trades printed on
  transition).
- Turn icebergs on in the auction tier of `test_book_invariants_random_ops.py`
  (that tier currently forces `allow_icebergs=False`; see T6).

### Bug B — iceberg qty-decrease amend refills the shown slice and keeps priority

`OrderBook.amend_order` (`order_book.py:520`) always sets
`displayed_qty = min(visible_qty, remaining_qty)`. A quantity **decrease** at the
same price keeps priority (`priority_reset=False`), so a partly used peak is
refilled in place and the iceberg jumps the orders that queued behind it.

```
SELL ICEBERG 100 (show 10) @100  A
SELL LIMIT    10           @100  B
BUY 6 @100                       → iceberg shown 10 → 4
AMEND iceberg QTY=90             → shown 4 → 10, priority_reset=False
BUY 10 @100                      → ICEBERG × 10      (should be ICEBERG × 4, LIMIT × 6)
```

**Fix (assuming Q2 = no growth).** In `amend_order`, after `priority_reset` is
known:

```python
if order.order_type == OrderType.ICEBERG and order.visible_qty is not None:
    if priority_reset:
        order.displayed_qty = min(order.visible_qty, order.remaining_qty)
    else:
        order.displayed_qty = min(order.displayed_qty or 0, order.remaining_qty)
```

Edge: `displayed_qty` can never be 0 on a resting iceberg, because
`_apply_fill` replenishes immediately. The qty-index bookkeeping around it
already uses `new_visible`, so nothing else changes. Reword
`020-order-types.md:1074` to say a decrease never enlarges the shown slice,
and that a price change or increase refills it (and loses priority).

**Tests (F2).** The repro above (full trade list), a decrease below the current
shown slice (shown shrinks to the new remaining), a price change (refills,
goes to the back), and `assert_book_invariants` after each.

### Bug C — FOK partially fills under SMP CANCEL_AGGRESSOR / CANCEL_BOTH (found in T2)

The operator guide promises "a self-match candidate can never cause a partial
fill". The FOK pre-check (`_fok_available_qty`) summed all non-own liquidity
within the limit, but the sweep **stops** at the first own order it meets
under `CANCEL_AGGRESSOR`/`CANCEL_BOTH`:

```
SELL LIMIT  3 @ 99   OTHER
SELL LIMIT  5 @ 100  ME
SELL LIMIT 10 @ 101  OTHER
BUY  FOK   10 @ 101  ME, SMP=CANCEL_AGGRESSOR
→ pre-check 13 ≥ 10, sweep trades 3 @ 99, meets ME @ 100, FOK cancelled
  with 3 of 10 filled
```

**Fix.** The pre-check walks the opposite side in priority order, as the
sweep will. Under `CANCEL_AGGRESSOR`/`CANCEL_BOTH` it stops at the first own
order. Iceberg hidden quantity counts only behind everything else at its
price, where replenished peaks queue. Under `CANCEL_RESTING` own orders are
skipped. Tests: `TestH8FokCorrectness` (both modes, and the variant where an
iceberg's hidden part sits behind an own order). Mutant M30. Operator guide
FOK step 1 reworded.

---

## 3. Test work packages

### T1 — Mutation-testing tool and baseline

Make the review's mutation run repeatable instead of a one-off.

- `tools/mutate_engine.py`: a list of mutants
  `(id, description, file, old, new)` (M01–M24 above, plus new mutants for
  bugs A and B: "uncross fills full remaining", "equilibrium on shown qty",
  "amend refills peak"). For each mutant it applies the change in a scratch
  copy of the working tree (tracked + untracked files, `.venv` symlinked,
  `PYTHONPATH` first, so the working tree is never touched; I7), runs
  `pytest tests -n logical -q`, and
  reports kills per mutant plus the killing test IDs. Arguments: mutant IDs
  to run, `--tests` to restrict the selection.
- A Makefile target `make mutate` (not part of `_check`; a full run takes
  about 45 min).
- Check that every mutant still applies (it fails loudly on a missing
  pattern), so engine refactors do not silently disable mutants.
- Record the baseline in this file.

Success: the tool reproduces the §1 table.

**As built (2026-10-21).** `tools/mutate_engine.py` (M01–M27; `--list`,
`--check`, `--tests PATH` repeatable, `--timeout`), `make mutate`, and the
guard `tests/test_mutate_engine.py` (in the default suite: every pattern occurs
exactly once and the mutated file parses). A run starts with an unmutated
baseline and stops unless pytest exits 0. A mutant is *killed* when pytest
exits 1 (count = failing tests), *error* on exit ≥ 2 (detected, by no single
test) and *hung* on timeout.

**Baseline (2026-10-21, after F1/F2, full suite, 10,430 tests).** It
reproduces §1: every count is equal or higher, and the F1/F2 regression
tests are the only tests added since, so they account for the rises. M25–M27
are new.

| ID | §1 | T1 | ID | §1 | T1 | ID | §1 | T1 |
|---|---|---|---|---|---|---|---|---|
| M01 | 6 | 6 | M10 | 1 | 1 | M19 | 2 | 2 |
| M02 | 3 | 3 | M11 | 3 | 3 | M20 | 2 | 2 |
| M03 | 149 | 153 | M12 | 1 | 1 | M21 | 2 | 2 |
| M04 | 5 | 6 | M13 | 6 | 6 | M22 | 9 | 9 |
| M05 | 3 | 5 | M14 | 2 | 5 | M23 | 5 | 6 |
| M06 | 8 | 8 | M15 | 6 | 6 | M24 | 5 | 5 |
| **M07** | **0** | **0** | **M16** | **0** | **0** | M25 | — | 2 |
| M08 | 4 | 4 | **M17** | **0** | **0** | M26 | — | 3 |
| M09 | 1 | 1 | M18 | 2 | 2 | M27 | — | 1 |

24/27 killed; survivors M07, M16, M17 (T5's targets). 12 of the 24 killed
mutants have ≤ 3 kills. The T1 column is the full run minus the guard test
(I10), spot-checked by a rerun of M07, M16, M17 and M27.

### T2 — Independent reference matcher

`tests/reference_matcher.py` (not collected): a deliberately naive matcher
written **from the documented rules** (participant guide order-types and
auction chapters, see Q3), never by reading `order_book.py`.

- Data: one plain list of live orders per side. Each pass sorts by
  (price, arrival seq). No heaps, no indexes, no lazy deletion.
- Covers LIMIT, MARKET, IOC, FOK (all-or-nothing including hidden and SMP
  exclusion), ICEBERG (fills at most the shown slice per pass; replenishment
  goes to the back), STOP / STOP_LIMIT (trigger on last trade, on entry if
  already breached, cascade), TRAILING_STOP (ratchet, trigger), SMP's three
  modes, cancel, amend (priority rules; a crossing amend is cancel/replace),
  auction (equilibrium by brute force over every candidate price with the
  documented tie-breaks; uncross per Q1).
- Output: the trade list `(buy_id, sell_id, price, qty, aggressor_side)`,
  per-order terminal status and remaining qty, and the resting book.
- Unit tests for the reference itself: the documented worked examples from
  the participant and operator guides (e.g. the auction tie example in
  `030-the-trading-day-and-auctions.md:190`). These are the oracle's
  acceptance tests.

Watch-outs: about 300 lines. If it grows a heap or an index, it is no longer
independent. Every place where the docs were silent goes into the docs first
and then into the insights log.

**As built (2026-10-21).** `tests/reference_matcher.py` (`ReferenceMatcher`:
`submit`, `cancel`, `amend`, `equilibrium`, `uncross`, `book`; `ROrder`,
`RTrade` with wire strings; about 420 lines including docstrings). Plain lists
are re-scanned with `min()` per match. The FOK check is a dry run of the
sweep on a deep copy, so it agrees with the sweep by construction.
`tests/test_reference_matcher.py`: 48 acceptance tests, each a documented
example or rule, cited. The gaps G1–G8 are in I13–I16; three of them changed
the engine (I14, I15, F3).

### T3 — Differential fuzz: `OrderBook` vs reference

`tests/test_matching_differential.py`: seeded random operation streams
(reuse `_OpDriver` from `test_book_invariants_random_ops.py`, extended to all
order types, crossing amends, SMP and auction batches with icebergs) are
applied to both `OrderBook` and the reference. After every step assert
**identical** trade lists (order, counterparties, price, qty), statuses and
resting books, plus `assert_book_invariants`.

- Crossing amends need the engine's re-match (M18 lives in
  `Engine._handle_amend`), so add a second variant that drives
  `Engine` through `tests/engine_harness.py` and compares the published
  trades.
- Defaults: 50 seeds × 300 steps in the normal run (target < 10 s with
  `-n logical`) and a `heavy` variant with 1000 seeds. A failure message
  prints the seed, the step and the last operations, like the existing driver.
- If the maintainer later accepts a new dev dependency, Hypothesis stateful
  testing is a drop-in for the driver (shrinking). Not part of this WP.

Success: M01, M02, M04, M05, M07, M09–M12, M14, M16, M17 and the bug A/B
mutants are each killed by T3 alone.

Starting point from T2 (I18): a scratch probe comparing trade lists over
800 seeds × 300 steps (all types, SMP, stops, cancels) found 0 divergences
against the fixed engine, and 200/200 against the pre-T2 engine. T3 makes it
a real test: it adds statuses, the resting book, crossing amends (engine
level) and auction batches. Expected divergence: the uncross stop cascade
(I19).

### T4 — Dataset smoke test checked against the reference

`test_engine_dataset_smoke.py` says it compares the engine against
"a straightforward reimplementation of matching", but its paper trader is
`OrderBook`. Change `tools/gen_verification_set.py` to compute `result` with
the reference matcher (`tools/verify_matching.sh` benefits too), or keep the
paper trader and add a third comparison, reference vs engine. Correct the
docstring either way.

### T5 — Specification scenario tests for both sides

Readable, hand-written scenarios that act as executable documentation. Each is
parametrized over **BUY and SELL** (mirror prices) and asserts the full trade
list, not just quantities. Proposed file: `tests/test_matching_spec.py`.

- Price-time priority with ≥ 3 orders at one price and across levels; a
  multi-level sweep with the price of each fill and the VWAP checked.
- Trade price = resting order's price (with price improvement for the aggressor).
- Stops and trailing stops: exactly at, one tick before and one tick through
  the trigger; triggered on entry; a cascade of 3; STOP_LIMIT that rests vs
  one that fills; trailing ratchet then trigger (both sides).
- FOK: exact fill, short by one lot, fill only possible through hidden iceberg
  quantity, SMP-excluded liquidity.
- IOC/MARKET: partial fill and cancel reason; empty book.
- Iceberg: shown slice, replenishment to the back, aggressive iceberg resting
  with a partly used peak (document per Q3).
- Auction: every tie-break step separately (maximum quantity, then minimum
  surplus, then lowest price as documented), one-sided book, all quantity at
  one price, icebergs (with F1), stops triggered by the uncross print.
- Session × TIF: ATO/ATC/DAY expiry with the published `order.expired`
  message checked.

Success: M07, M16 and M17 are killed, and every mutant has ≥ 3 kills.

### T6 — Extend the randomized invariant tests

`tests/test_book_invariants_random_ops.py`:

- Add STOP, STOP_LIMIT and TRAILING_STOP generation (with a last trade price
  so they can trigger).
- Turn icebergs on in the auction tier. F1 has landed, so no `xfail` is
  needed: measured 36/200 seeds failing before F1, 0/200 after (I2).
- Add an invariant: a stop-heap entry never shows up in `_bid_qty`/`_ask_qty`.
- Raise the defaults to 25 seeds × 200 steps (measure the time).
- Remove the stale "EXPECTED TO FAIL until …" docstrings (C2/C3/C7 are fixed).
- Cross-check that `assert_qty_conservation` also runs per step, not only at
  the end.

### T7 — In-process end-to-end trading test

The user-level path no CI test exercises today:
ALF TCP client → `pm-alf-gwy` → engine over real ZMQ → fills to both clients,
the public trade on the MD feed, positions in clearing.

- Run gateway and engine in-process (threads) on `free_ports()` (see
  `tests/conftest.py`). Two clients log in; for each order type, one scenario
  that crosses. Assert the ALF fill lines on both sessions (price, qty,
  liquidity flag), the `trade.executed` on the MD feed, and the clearing
  position of both sides.
- Also a cancel and an amend round trip, and a reject (wrong owner), so the
  ALF reply text is pinned.
- Must stay under ~10 s and run in the default suite. If it cannot, mark it
  `e2e` and add it to `make test-e2e`.

### T8 — Remove or strengthen weak-assertion tests

About 350 test functions (list from an AST scan; the T8 script should be
committed under `tools/` so the list can be regenerated):

- 159 with no assertion at all, 49 that only check a mock was called,
  146 with only `isinstance` / `is not None` / `> 0` assertions.
  Concentrated in `test_gateway_and_scheduler.py` (≈108),
  `test_generated_validators_integration.py`, `test_balf_gwy_unit.py`,
  `test_audit_cli.py`.
- For each: strengthen it (decode the sent frame and assert topic + payload,
  as `test_session_command_sends_session_state_request` already does), merge
  it into a stronger existing test, or delete it if it only exists to cover a
  line. Check coverage stays ≥ 85% after deletions. Deleted coverage padding
  that drops the figure is useful information, not a reason to keep it.
- Optional guard: a test that fails if a new `test_*` function has no
  assertion (allowlist for the deliberate "must not raise" tests).

### T9 — Final mutation run, docs, CI gate decision

- Re-run `tools/mutate_engine.py`. Target: every mutant killed, each by ≥ 3
  tests, at least one of them a plain specification test (T5).
- `docs/books/architecture-and-development/part-4-developing/030-verification.md`:
  describe the reference matcher, the differential fuzz and `make mutate`.
- Decide with the maintainer whether a reduced mutant set (≈ 6 fast mutants
  against the engine tests only) becomes a CI step.

---

## Insights log

Findings made during implementation that changed code, the design or a later
WP. Numbered I1, I2, … so they can be referenced from commits.

| # | WP | Insight | Action |
|---|---|---|---|
| I1 | F1/F2 | Q1 and Q2 were taken as recommended: hidden iceberg quantity takes part in the uncross, ranked behind visible quantity peak by peak; a priority-keeping amend never enlarges the shown slice. | `auction.py`: `_auction_levels()` (total live qty per level, used by `compute_equilibrium` and `executable_at`) and `_shown_qty()` (per-pass cap in `execute_uncross`). `order_book.py:amend_order` refills only when `priority_reset`. Participant guide (auction chapter info box, amend table) and the guided-tour code excerpt updated. |
| I2 | F1 | Turning icebergs on in the auction tier of `test_book_invariants_random_ops.py` fails 36 of 200 seeds before F1 and 0 after, so the existing fuzzer would have found bug A had that tier not forced `allow_icebergs=False`. | T6 bullet updated: enable it without `xfail`. |
| I3 | F1 | The indicative published during a call phase now includes hidden iceberg quantity in `eq_qty` / `imbalance_qty`. That is a consequence of Q1 (indicative == print) and is now documented, but it does let an observer infer hidden size from indicative changes. | None; noted for the maintainer. Revisit if a "hidden quantity not disseminated" rule is wanted. That would need the indicative and the print to differ again, deliberately. |
| I4 | F1 | `compute_equilibrium` is now O(n) instead of O(price levels). Callers: indicative flush (throttled), end of each call phase, ACE dry run, closing backstop, reopen dry run. None is per-order. | No action. Full suite and e2e unchanged in time. |
| I5 | F1 | `docs/books/architecture-and-development/part-2-inside-the-engine/010-order-book-deep-dive.md` §"Iceberg Orders and the FOK Undercount" is stale independently of this plan: since finding #15 the FOK pre-check walks the heaps and counts hidden quantity (`_fok_available_qty`), and `_available_qty` is now unused dead code. | Not changed (out of scope). Candidates for T9's docs pass and a dead-code removal. |
| I6 | F2 | `test_iceberg_qty_decrease_below_visible` already passed, because `min(visible, remaining)` happens to be right when the new remaining is below the current shown slice. Only the "partly used peak, decrease above it" case exposed the bug. | Regression tests cover decrease-above, decrease-below, price change and increase. T1 adds the mutant "amend refills peak". |
| I7 | T1 | `git archive HEAD` (as planned) measures the last commit, not the code under test. The copy is built from `git ls-files --cached --others --exclude-standard` instead, so uncommitted work (e.g. a new test file) counts. | Tool and T1 text updated. |
| I8 | T1 | `test_config_gen_cli_help.py` shells out to `poetry run`, which fails in a copy without an in-project venv. That was the one baseline failure in the review's scratch runs. | The copy gets a `.venv` symlink to the project's venv. |
| I9 | T1 | `-p no:cov` makes pytest exit with a usage error, because pyproject's `addopts` carry `--cov` flags. The first draft read "no FAILED lines" as green, so a run that tested nothing reported every mutant as SURVIVED and the baseline as green. | `--no-cov`. Every run is classified by pytest's exit code (0 / 1 / ≥ 2) and the baseline must exit 0. |
| I10 | T1 | The guard test fails for every mutant by construction (a mutated file no longer holds its pattern), so it added 1 to every count and turned the three survivors into "killed by 1". | Mutation runs `--ignore` the guard (`GUARD_TEST`). Baseline counts corrected by −1 (exact: no mutant's `new` contains its `old`) and spot-checked. |
| I11 | T1 | Two review patterns were not unique: M11 (the STOP→MARKET block exists for buy and sell stops) and M21 (the ownership check also guards amend). The review script picked "the first occurrence", which silently depends on source order. | Patterns extended with context until unique; uniqueness is enforced by the guard test. |
| I12 | T1 | Full run: 28 suite runs at about 90 s each, so about 45 min. Running a subset is fast (`--tests tests/test_auction.py …`: about 4 s per mutant), which is the practical loop for T5. | Documented in the tool's usage text and `make mutate` help. |
| I13 | T2 | Docs gaps closed (Q3), written into the participant guide ("Stop Trigger Logic → Exact evaluation rules", ICEBERG) and operator guide (SMP): **G1** stops are evaluated once per incoming order, against its last print (matters for a trailing stop's ratchet); **G2** several triggered at once run BUY stops (lowest stop first), then SELL (highest first), then trailing, each by arrival, and stops triggered by those queue behind; **G3** a stop already breached on entry triggers at once, all 3 types; **G4** an incoming iceberg trades its full quantity; **G5** SMP cancels a resting iceberg whole; **G6** no SMP in the uncross; **G8** no entry check while not matching. G1, G2, G5, G6 and G8 document existing behaviour. (G7, fresh priority for a triggered stop, was already documented.) | Docs updated; the reference implements G1–G8. |
| I14 | T2 | G3: a TRAILING_STOP already breached on entry was parked until the next trade, while STOP / STOP_LIMIT trigger on entry (M2). There was no reason for the difference. | `OrderBook.process` triggers it on entry via `_trigger_stop_now` (now also converts TRAILING_STOP → MARKET). Tests in `TestTrailingStopOrderBook`; mutant M28. |
| I15 | T2 | G4: an incoming iceberg traded in **peak-sized chunks**: 5 prints of 10 against one resting 50-lot, inflating trade counts and MD prints. After a partial fill it then rested with a partly used peak. Real venues (e.g. Xetra) execute an incoming iceberg's full volume. | `_match_iceberg` uses `_sweep` and rests the remainder behind `min(visible, remaining)`; `_sweep_iceberg` removed as unused. Tests in `test_order_flow.py`; mutant M29. |
| I16 | T2 | G5: the operator guide said SMP cancels only a resting iceberg's peak and it then replenishes; the engine cancels the whole order (one `order.cancelled`). The doc sentence was wrong. | Operator guide corrected; the reference follows the engine. |
| I17 | T2 | Bug C (FOK partial fill under SMP) found while writing the reference's FOK rule from the operator guide text. | F3 row added; fixed (§2, bug C); mutant M30. |
| I18 | T2 | A throwaway probe (reference vs `OrderBook`, trade lists only, 800 streams × 300 steps with SMP and stops) found 0 divergences after the T2 changes and 200/200 before them, so the probe is sensitive and the two independent implementations agree. | Basis for T3 (see its text). |
| I19 | T2 | Stop cascade after an uncross differs from continuous: `Engine._run_uncross` takes the triggered list once and runs each with `book.process` (depth-first: a stop's own triggers run before the next listed stop), while `OrderBook.process` queues them breadth-first (rule G2). | Not changed. T3 will confirm with an engine-level auction case and decide on the fix. |
| I20 | T2 | Mutant M09's pattern became ambiguous once the TRAILING_STOP on-entry branch existed. The T1 guard caught it on the first full run. | M09 re-anchored on its comment line; M28–M30 added (all killed). |

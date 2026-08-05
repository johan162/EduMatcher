Version: 1.0.0

Date: 2026-06-14

Status: Design and Research Proposal

# Exchange-Level Corporate Actions — Design

Supersedes the index-only corporate-action model in `pm-index`.
Closes GAP-2 from `EduMatcher-Stats-Review.md`.

---

## 1. Why this document exists

Corporate actions in EduMatcher today live entirely inside `pm-index`. That
placement produces a bug that is easy to demonstrate and impossible to fix
locally, and it leaves the instrument tape with no record that an action ever
happened.

Moving them into the engine touches the most safety-critical component in the
system — the order book — so the design is written down before any code is.

### 1.1 The bug in the current model

`pm-index-admin-cli split --index EDU100 --symbol AAPL --ratio 2:1` reaches
`IndexCalculator.apply_split`, which mutates the index's *private* view:

```python
self._outstanding_shares[sym] = old_shares * num // den      # 2N
new_price = old_price * den / num                            # P/2
self._last_prices[sym] = new_price
# then: divisor rescaled so level is continuous
```

Nothing in the engine responds. Resting orders keep their prices,
`last_trade_price` is unchanged, and no `trade.executed` price moves.

`pm-index` also subscribes to `trade.executed` and calls `update_price`, which
overwrites its halved figure with whatever actually prints:

```
PRE_OPEN   apply 2:1 split
           index: shares 2N, price P/2, divisor rescaled → level L  ✔
CONTINUOUS first real trade prints at P (nobody adjusted the book)
           index: shares 2N, price P   → aggregate cap doubles
                                       → level 2L                   �’
```

The index level doubles. The split is only coherent if every participant
independently re-quotes at half price, and nothing signals that they should.

### 1.2 What the tape does not record

`daily_stats` is a per-symbol OHLC series. If participants *do* re-quote, the
series has a genuine discontinuity with nothing explaining it. If they do not,
the index is wrong. Either way the statistics database has no idea an action
occurred, because the action is acknowledged only to the requesting gateway
(`index.corp_action_ack.{gateway_id}`) and never broadcast.

---

## 2. How real exchanges do this

The question that prompted this document was: *does a real exchange adjust the
book, or carry an adjustment factor in perpetuity?* The answer is **both, for
two different purposes**, and conflating them is the classic mistake.

### 2.1 Live trading — the book is purged, not rescaled

For cash equities, venues overwhelmingly **cancel resting orders** at a
corporate action rather than rescaling them. Nasdaq, NYSE and the major MTFs
all purge or cancel open orders on the ex-date for most action types; where
adjustment happens instead, it is done by the *broker* re-entering orders on
the client's behalf, not by the matching engine mutating live orders in place.

The reasons are mechanical, and every one of them applies to EduMatcher:

| Problem | Concrete example in this codebase |
|---|---|
| Adjusted prices leave the tick grid | 3:1 split of a limit at `10000` ticks → `3333.33`, not representable in `Order.price: int` |
| Quantities stop being whole | 1:10 reverse split of `105` shares → `10.5` |
| Queue priority becomes undefined | `_HeapEntry.key` carries an arrival sequence; does a rescaled order keep its place ahead of an order entered after the announcement? |
| Multi-price orders multiply the problem | `STOP_LIMIT` has `price` *and* `stop_price`; `TRAILING_STOP` has `trail_offset`; `ICEBERG` has `visible_qty` and `displayed_qty` |
| Linked structures need consistent treatment | `ComboOrder` legs and OCO groups must all adjust or all cancel, atomically |
| Economic intent may not survive | "buy 100 at 50" after a 1:10 reverse split is a materially different order |

Cancelling sidesteps all seven. It is also what a participant expects: their
order is returned to them, and they decide whether to re-enter.

**What the exchange *does* adjust is the reference data**: previous close,
opening reference, price-band/collar anchors and volatility-halt references.
Without that, the first post-action order trips every guard immediately.

### 2.2 Historical data — raw prices, adjustment factors forever

Historical series are the opposite: **the tape is immutable**. What traded,
traded. Exchanges and vendors publish corporate-action files carrying
adjustment factors, and consumers apply them at read time — or store a
*derived* adjusted series alongside the raw one. Nobody rewrites the official
record of what printed.

This is precisely the "carry an adjustment factor in perpetuity" model, and it
is the right one for `stats.db`.

### 2.3 Consequence for a decision already taken

The GAP-2 interview settled on *"corporate_actions table **plus a cumulative
adjustment factor on daily_stats**"*, with the noted cost that "every prior row
for that symbol must be rewritten when an action lands".

**This design recommends against back-propagating the factor**, on the grounds
of §2.2: a recorder that rewrites rows it already wrote is no longer an
append-only record of what happened, and `stats.db` is the thing auditors read.

The proposal keeps the benefit without the cost:

- `corporate_actions` is the authoritative, append-only event table.
- `daily_stats.adjustment_factor` is **materialised, not authoritative** —
  written forward only (each new day carries the cumulative factor as of that
  day), and fully regenerable from `corporate_actions` by
  `pm-stats-cli reindex-adjustments`.
- Consumers wanting an adjusted series either multiply by the stored factor
  (fast path) or recompute from the actions table (audit path). Both agree.

This is a deviation from the agreed answer and needs sign-off before Phase 5.

---

## 3. Target design

### 3.1 Ownership

```
pm-exchange-admin-cli  corp-action --symbol AAPL --split 2:1 --effective PRE_OPEN
        │  risk.corp_action  (PUSH :5555)
        ▼
   ┌─────────┐
   │ pm-engine│  1. validate (ADMIN role, session state, symbol exists)
   │          │  2. cancel every resting order/quote/combo/OCO leg in symbol
   │          │  3. adjust reference data (prev_close, collar, breaker, last_*)
   │          │  4. publish  corp.action.{SYMBOL}   ← new PUBLIC topic
   │          │  5. ack      risk.corp_action_ack.{gateway_id}
   └─────────┘
        │ corp.action.AAPL (public, sequenced)
        ├──────────────► pm-index   rescales divisor (subscriber, no longer owner)
        ├──────────────► pm-stats   writes corporate_actions row
        └──────────────► gateways   participants see it live and re-enter orders
```

The engine becomes the single source of truth. Every listed symbol can have an
action, whether or not it belongs to an index — which is the coverage GAP-2
requires and the current model cannot provide.

### 3.2 Why the engine, not a new process

The action must be atomic with respect to matching: no order may rest across
the moment the reference price changes. Only the engine's single-threaded
dispatch loop can guarantee that. A separate process would need to halt the
symbol, wait for quiescence, and race the engine on restart.

### 3.3 Session-state gating

Corporate actions are accepted only in `PRE_OPEN` or `CLOSED`, matching the
existing guidance in `150-market-index.md` ("apply corporate actions before the
market opens"). Attempting one in `CONTINUOUS` is rejected with a reason rather
than silently halting the symbol — an operator who mistimed it should be told,
not surprised by a halt.

`--force` is available for teaching scenarios that deliberately demonstrate a
mid-session action; it halts the symbol, applies, and leaves it halted for an
explicit resume.

---

## 4. Surfaces this change touches

Read from the current code. Line references are indicative.

### 4.1 New files

| File | Purpose |
|---|---|
| `src/edumatcher/engine/corp_action.py` | Pure functions: ratio validation, reference-price rescaling, tick conformance. No I/O, no engine state — directly unit-testable. |
| `src/edumatcher/exchange_admin/cli.py` | `pm-exchange-admin-cli corp-action` — mirrors `index/admin_cli.py` structure, including `--dry-run` and `-y`. |
| `tests/test_corp_action_engine.py` | Phase 1–3 tests. |
| `tests/test_corp_action_end_to_end.py` | Capstone (§7). |
| `docs/user-guide/075-corporate-actions.md` | New user-guide chapter (§8). |

### 4.2 Modified — engine

| Location | Change | Risk |
|---|---|---|
| `engine/main.py` dispatch table | Route `risk.corp_action` to a new `_handle_corp_action` | Low — additive, mirrors `risk.cancel_symbol` |
| `engine/main.py::_handle_corp_action` (new, ~120 lines) | Validate, purge, adjust, publish, ack | **High** — the core change |
| `engine/main.py::_handle_cancel_symbol` (2842) | Extract the purge loop into `_purge_symbol(symbol, reason)` and call it from both | Medium — refactor of working code; behaviour must be identical |
| `engine/main.py::_book_stats` (227) | `prev_close` rescaled by the action ratio | Medium — feeds `symbol_meta.prev_close` to gateways |
| `engine/main.py` collar seeding (~727) | `collar.reference_price` rescaled | **High** — a stale collar rejects every post-action order |
| `engine/circuit_breaker.py::reference_price` (131) | Rescale, and clear `trade_history` — pre-action prices are not comparable to post-action ones | **High** — a stale breaker halts the symbol on the first print |
| `engine/order_book.py` `last_trade_price`, `last_buy_price`, `last_sell_price`, `recent_trades` | Rescale or clear | Medium — feeds book snapshots and the index |
| `engine/persistence.py::save_gtc_orders` | GTC orders resting across a restart must not survive an action un-adjusted | **High** — silent corruption across restart if missed |

### 4.3 Modified — messaging

| Location | Change |
|---|---|
| `models/message.py` | `make_corp_action_msg`, `make_corp_action_ack_msg`, `make_corp_action_event_msg` |
| `models/feed_schema.py` | `CorpActionPayload` — typed, with units documented per field as the neighbouring payloads are |
| `messaging/bus.py` | None. The new topic is sequenced automatically by `SequencedPublisher`. |

### 4.4 Modified — pm-index

| Location | Change | Risk |
|---|---|---|
| `index/main.py::_handle_corp_action` | Becomes a **subscriber** to `corp.action.{SYMBOL}` instead of a command handler | Medium |
| `index/main.py` subscriptions | Add `corp.action.` | Low |
| `index/calculator.py::apply_split` etc. | Unchanged — still the right divisor maths, now driven by an event | None |
| `index/admin_cli.py` | Deprecated with a pointer to the new CLI; kept one release for muscle memory | Low |

The `_last_prices` overwrite that causes §1.1 disappears by construction: the
engine has already rescaled the instrument, so the first post-action print is
already at the new level.

### 4.5 Modified — pm-stats

| Location | Change |
|---|---|
| `stats/main.py` SCHEMA | New `corporate_actions` table; `daily_stats.adjustment_factor REAL NOT NULL DEFAULT 1.0` |
| `stats/main.py` | Subscribe to `corp.action.`, new `_on_corp_action` handler |
| `stats/query.py` | `query_corporate_actions`; adjusted-series helper |
| `stats/cli.py` | `corp-actions` subcommand; `reindex-adjustments` |
| `SCHEMA_VERSION` | 4 → 5 |

### 4.6 Documentation

| Document | Change |
|---|---|
| `075-corporate-actions.md` | **New chapter** (§8) |
| `140-statistics-and-reporting.md` | `corporate_actions` schema; adjusted-series recipe; replace the "prices are unadjusted" warning |
| `150-market-index.md` | Rewrite §Corporate Actions — pm-index is now a consumer |
| `152-index-admin-cli.md` | Deprecation notice |
| `270-message-reference.md` | New topic and payload |
| `160-exchange-commands.md` | New ADMIN command |
| `080-session-scheduling.md` | When actions may be applied |

---

## 5. Phased implementation

Each phase is independently testable and independently shippable. No phase
leaves the system in a worse state than it found it.

### Phase 0 — Fix the index bug in isolation *(optional, 1 day)*

Before any restructuring, make the current double-counting failure visible:
add a regression test that applies a split to `IndexCalculator`, feeds a
post-split trade at the *unadjusted* price, and asserts the level doubles.

**Value:** the bug is pinned before the code moves, so Phase 4 can prove the
move fixed it rather than asserting it did.

**Test:** `test_index_level_doubles_when_book_is_not_adjusted` — expected to
*fail* after Phase 4, at which point it is inverted into the correctness test.

### Phase 1 — Pure corporate-action maths

`engine/corp_action.py` only. No engine wiring.

```python
def split_ratio(num: int, den: int) -> Fraction
def adjust_price_ticks(price: int, ratio: Fraction) -> int      # + rounding rule
def adjust_quantity(qty: int, ratio: Fraction) -> int
def is_tick_conformant(price: int, tick_decimals: int) -> bool
```

**Testable alone:** ratio validation, rounding at boundaries, reverse splits,
dividend subtraction, tick conformance, overflow on extreme ratios.

**Ships:** nothing user-visible. Pure functions with full unit coverage.

### Phase 2 — Purge extraction

Extract `_purge_symbol(symbol, reason)` from `_handle_cancel_symbol`. Both the
existing ADMIN mass-cancel and (later) the corporate-action handler call it.

**Testable alone:** the existing `risk.cancel_symbol` tests must pass
unchanged — that is the whole acceptance criterion. Add coverage for
quote/combo/OCO leg interaction, which is currently thin.

**Ships:** a pure refactor, behaviour identical.

### Phase 3 — Engine applies and broadcasts

`_handle_corp_action`: validate → `_purge_symbol` → adjust reference data →
publish `corp.action.{SYMBOL}` → ack.

**Testable alone:**

- rejected outside `PRE_OPEN`/`CLOSED` without `--force`
- rejected for non-ADMIN
- book empty afterwards; every cancelled order produced an `order.cancelled`
  to its owner with reason `CORP_ACTION`
- `prev_close`, collar reference, breaker reference all rescaled
- breaker `trade_history` cleared
- `corp.action.AAPL` published exactly once, with a sequence frame
- GTC file on disk holds adjusted references after a save/load cycle

**Ships:** the engine half. `pm-index` still owns its own path, so nothing
regresses; the new topic simply has no subscribers yet.

### Phase 4 — pm-index becomes a subscriber

Switch `index/main.py` to consume `corp.action.{SYMBOL}`. Deprecate
`index/admin_cli.py`.

**Testable alone:** Phase 0's test inverts — apply a split via the engine, feed
the post-split print, assert the index level is **continuous**.

**Ships:** §1.1 fixed. This is the phase that delivers the headline correctness
win, and it is worth shipping on its own.

### Phase 5 — pm-stats records the actions

`corporate_actions` table, `_on_corp_action`, `pm-stats-cli corp-actions`.
Schema version 5.

**Testable alone:** action recorded with correct effective trading date, ratio
and symbol; survives a recorder restart; appears in the CLI.

**Ships:** the tape now explains its own discontinuities. **No adjustment
factor yet** — deliberately, so Phase 5 carries no history-rewriting risk.

### Phase 6 — Adjustment factors *(needs the §2.3 sign-off)*

`daily_stats.adjustment_factor`, written forward only, plus
`pm-stats-cli reindex-adjustments` to regenerate from `corporate_actions`.

**Testable alone:** a series spanning an action yields a continuous adjusted
close; `reindex-adjustments` is idempotent and reproduces the same factors from
the actions table alone.

**Ships:** charting convenience, with the authoritative record untouched.

---

## 6. Risks and mitigations

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Stale collar reference rejects every post-action order | **High** | Phase 3 test asserts an order at the new price is accepted and one outside the new band is rejected |
| R2 | Stale breaker reference halts the symbol on the first print | **High** | Clear `trade_history` on action; test asserts the first post-action trade does not halt |
| R3 | Purge misses a structure (quote, combo leg, OCO sibling) leaving an un-adjusted resting order | **High** | Phase 2 asserts the book is *empty* by enumeration, not by counting cancels |
| R4 | GTC orders reload un-adjusted after a restart | **High** | Phase 3 save/load round-trip test |
| R5 | Rounding drift makes the index divisor inconsistent with the engine's prices | Medium | Single shared rounding rule in `corp_action.py`, used by both; property test over random ratios |
| R6 | Participants unaware their orders were cancelled | Medium | Every cancel emits `order.cancelled` with reason `CORP_ACTION`; the public event names the symbol |
| R7 | Phase 4 leaves both paths live and an operator uses the old CLI | Medium | Old CLI prints a deprecation warning and refuses without `--i-know-this-is-deprecated` |
| R8 | Back-propagating factors rewrite audit history | **High** | §2.3 — do not back-propagate; regenerate instead |
| R9 | Reverse split produces a sub-tick price | Medium | `is_tick_conformant` check in Phase 1; action rejected at validation with a clear reason |
| R10 | Engine hot path slowed | Low | The handler runs once per action, not per order; no change to `process()` |

---

## 7. Capstone test

`tests/test_corp_action_end_to_end.py::test_two_for_one_split_is_coherent_across_the_whole_system`

Single test, real engine + real `pm-index` calculator + real `pm-stats`
recorder, proving every component agrees:

```
GIVEN  AAPL trading at 100.00 (10000 ticks), in index EDU100 at level L
       resting: bid 99.00 x100 (TRADER01), ask 101.00 x100 (MM01)
       a GTC buy at 95.00 from TRADER02
       session = PRE_OPEN

WHEN   ADMIN applies corp-action --symbol AAPL --split 2:1

THEN   1. book is empty                        (purge)
       2. TRADER01, MM01, TRADER02 each received order.cancelled
                                               reason=CORP_ACTION
       3. prev_close       == 5000 ticks        (reference rescale)
       4. collar reference == 5000 ticks
       5. breaker reference cleared
       6. corp.action.AAPL published once, sequenced
       7. GTC file reloads with the adjusted reference

AND    session → CONTINUOUS; participants re-enter at 50.00;
       a trade prints at 5000 ticks

THEN   8. no circuit-breaker halt fired         (R2)
       9. the order was not collar-rejected     (R1)
      10. index level == L, unchanged           (§1.1 fixed)
      11. stats corporate_actions has one row, SPLIT 2:1, effective today
      12. trade_log price == 5000, tick_decimals == 2
      13. daily_stats for today opens at 5000

AND    querying the adjusted series across the action

THEN  14. adjusted closes are continuous
      15. raw daily_stats rows are byte-identical to before the reindex  (R8)
```

Assertions 10, 14 and 15 are the ones that matter: 10 proves the original bug
is gone, 14 proves the adjustment works, 15 proves it did not rewrite history.

---

## 8. User-guide chapter

There is no corporate-actions chapter today — only the `pm-index-admin-cli`
reference and a section inside `150-market-index.md` describing divisor
adjustment. A new `docs/user-guide/075-corporate-actions.md` is required,
placed after order types and before market-maker material.

Outline:

1. **What a corporate action is** — splits, reverse splits, cash dividends,
   share issuance; value-neutral by construction.
2. **What EduMatcher does when one is applied** — the five engine steps, with
   an explicit before/after book illustration.
3. **Why resting orders are cancelled, not adjusted** — §2.1, including the
   tick-grid and queue-priority reasoning. This is the section a student
   learns the most from.
4. **What participants see** — `order.cancelled` with `reason=CORP_ACTION`,
   the public `corp.action` event, and the expectation to re-enter.
5. **Effect on the index** — divisor adjustment, now driven by the event.
6. **Effect on statistics** — raw tape immutable, `corporate_actions` table,
   adjusted vs unadjusted series, with worked `pm-stats-cli` examples.
7. **Applying one** — `pm-exchange-admin-cli` walkthrough with `--dry-run`.
8. **Timing rules** — `PRE_OPEN`/`CLOSED` only, and what `--force` does.
9. **Worked example** — a 2:1 split end to end, mirroring the capstone test so
   the documentation and the test assert the same numbers.
10. **Troubleshooting** — collar rejections, unexpected halts, index
    discontinuity, missing `corporate_actions` rows.

---

## 9. Open questions

1. **§2.3 sign-off** — back-propagating adjustment factors versus
   forward-only-plus-regenerate. This design recommends the latter and Phase 6
   depends on the answer.
2. **Dividends and the book.** A cash dividend reduces price by the dividend
   amount, which is not a ratio. Purging is still correct, but the reference
   adjustment is subtractive — should collars re-anchor to `prev_close - div`,
   or re-seed from the first post-action trade?
3. **Should `--force` exist at all?** It enables a teaching scenario but adds a
   path where an action lands mid-session. A safer alternative is to require an
   explicit halt first, making the operator's intent unambiguous.
4. **Retention.** `corporate_actions` must never be pruned — the retention
   guidance in `140-statistics-and-reporting.md` needs an explicit exception,
   or an old action silently stops being applied to an adjusted series.

# pm-engine Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/engine/` at `4f3e5657` (v0.78.4): `main.py` (7 923 lines),
`order_book.py` (2 521), `auction.py` (624), `config_loader.py` (1 662),
`circuit_breaker.py`, `collar.py`, `order_limits.py`, `persistence.py`,
`metrics.py`, `drop_copy.py`, `gc_policy.py`, `schedule_resolve.py`, plus the
models the engine mutates (`models/order.py`, `trade.py`, `quote.py`,
`combo.py`, `session.py`, `clock.py`, `order_fields.py`) and the
`CausalPublisher` contract in `messaging/bus.py`.

**Focus:** correctness, performance, and whether the comments let a reader
follow every main data flow (new order, cancel, amend, quote, OCO, combo,
uncross, halt/resume, restore/checkpoint) and are still true.

**Previous reviews:** `EduMatcher-Engine-Review.md` (v0.16) and
`EduMatcher-Final-engine-review.md` (pre-beta, E1–E5). Every finding of
both is in place: receive/decode is guarded, the book is checkpointed every
5 s with atomic writes, a handler exception answers with a reject, the
maintenance flushes are guarded one by one. This review does not repeat them.

**Method:** every line of the files above was read. Findings marked
*(repro)* were reproduced with a scratch pytest module built on
`tests/engine_harness.py`; the others are by inspection, with the line
numbers given.

Status: **In progress.** WP-ENG01, WP-ENG02, WP-ENG04 and WP-ENG05 done
2026-11-13 (uncommitted; outcomes in §8). Next: WP-ENG06.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver, built on `tests/engine_harness.py` (`make_engine`,
   `FakeSock`, `msgs`) and, for book-level WPs,
   `tests/engine_invariants.py`.
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_engine_*.py` with
   `-n logical`, then black/flake8/mypy/pyright. Do not start the next WP
   with a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-ENG01 | One engine-initiated cancel funnel that always runs the OCO and combo follow-ups | C1, C2 | — | 1 d | ☑ | 2026-11-13 |
| 2 | WP-ENG02 | Structure handlers (OCO, combo, quote) always answer, including on an internal error; OCO trailing-stop reference gate | C3, C4 | — | 0.5 d | ☑ | 2026-11-13 |
| 3 | WP-ENG03 | Reference-reload contract: what a reload may change, applied or refused consistently | C5 | Q2 | 1 d | ☐ | |
| 4 | WP-ENG04 | Startup-state robustness: corrupt `book_stats.json` entries, PARTIAL status on restore | C7, C8 | — | 0.5 d | ☑ | 2026-11-13 |
| 5 | WP-ENG05 | One business date; reference schedule `today` never stale | C6, C9, D12 | — | 0.5 d | ☑ | 2026-11-13 |
| 6 | WP-ENG06 | Halt consistency: orphaned quote legs on a CB halt, halt reason on quote rejects, admin halts at CLOSED | C10, C11, D7 | Q3 | 0.5 d | ☐ | |
| 7 | WP-ENG07 | Small correctness cleanups | C13–C17 | — | 0.5 d | ☐ | |
| 8 | WP-ENG08 | Performance: maintenance throttle, holiday-calendar cache, request-path lookups | P1–P5 | — | 1 d | ☐ | |
| 9 | WP-ENG09 | Comments and docstrings: data-flow walkthroughs correct and complete | D1–D13, C12 | WP-ENG01–08 | 1 d | ☐ | |

Suggested order: **WP-ENG01 → WP-ENG02 → WP-ENG04 → WP-ENG05 → WP-ENG06 →
WP-ENG03 → WP-ENG07 → WP-ENG08 → WP-ENG09**. WP-ENG01 and WP-ENG02 are the
two that change client-visible behaviour on error paths and should land
before any further end-to-end simulation run. WP-ENG03 waits for decision Q2.
WP-ENG09 goes last so every docstring describes the code as it ends up.

Estimated sequential effort: about 6.5 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The engine is in good shape for 1.0. The hot path (`_handle_new_order` →
`OrderBook.process` → `_publish_dispatch` → `_publish_trade`) is correct,
heavily cross-referenced, and every earlier review finding it cites is
genuinely implemented. The book's five denormalised structures are kept in
step on every path I traced, including the awkward ones (iceberg refill
inside an uncross, SMP inside a stop cascade, a stop cancelled while it waits
in `_triggered`). The auction code's SMP/OCO dry run is subtle but right, and
`compute_equilibrium`'s bound-ordered scan gives the same answer a full scan
would.

The defects are concentrated in one place: **the engine-initiated cancel
paths** (kill switches, admin cancel-symbol, disconnect `CANCEL_ALL`, TIF
expiry). They cancel orders through `_cancel_order_by_id` or
`book.cancel_order` directly, and neither runs the OCO/combo follow-ups that
`_handle_cancel` and the book's fill hooks run. The consequences are
client-visible (C1, C2) and the fix is one funnel. The second cluster is the
**structure handlers' error contract**: an exception in the OCO, combo or
quote handler answers nobody (C3), and one such exception is reachable from a
well-formed request (C4).

Everything else is medium or low: a reload that half-applies (C5), a stale
date in a cache (C6), a crash on a corrupt stats file (C7), and a set of
comments that have drifted from the code they describe (D1–D13).

Severity key: **High** — a participant loses a capability or state is left
wrong for the rest of the run; **Med** — a wrong or missing answer, or an
operator-visible inconsistency; **Low** — hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| C1 | High | OCO | Engine-initiated cancels (TIF expiry, kill switches, cancel-symbol, disconnect) never unlink the pair: `_oco_groups` keeps it, the id is "already in use" for the rest of the run, `_order_to_oco` grows *(repro)* | ENG01 |
| C2 | High | Combo | The same paths cancel combo children without the combo follow-up: parent stays PENDING, no `combo.status`, a cancel-symbol on one leg leaves the other legs resting for ever, and the half-dead combo is checkpointed and restored *(repro)* | ENG01 |
| C3 | Med | Error contract | `_reject_after_error` only answers payloads carrying `order_id`; an exception in the OCO, combo or quote handler answers nobody *(repro)* | ENG02 |
| C4 | Med | OCO | A trailing-stop OCO leg with no `stop_price` and no last trade is posted to the book and fails an `assert` there, after leg 1 was acked and posted; the client hears nothing *(repro)* | ENG02 |
| C5 | Med | Reload | `reference_reload` swaps `_engine_config` only: participant SMP defaults, MM obligations and quote policies change at once, while the allowlist, collars, order limits, breakers and `GET /reference` disagree with what is enforced *(repro)* | ENG03 |
| C6 | Med | Reference | `GET /reference` schedule `today` / `today_is_holiday` / `upcoming_holidays` are computed once at load and go stale at midnight; the config-version digest depends on the date | ENG05 |
| C7 | Med | Startup | One corrupt value in `book_stats.json` (`"prev_close": "abc"`, a missing `cb_window` key, a non-dict root) raises out of `_load_config` and the engine does not start; `gtc_orders.json` is guarded per entry, this file is not *(repro)* | ENG04 |
| C8 | Low | Restore | A persisted PARTIAL order is restored as NEW; every snapshot of it lies until its next fill *(repro)* | ENG04 |
| C9 | Low | Dates | Three notions of "today": restore uses the session timezone, `_archive_eod` and `_weekly_schedule_wire` use the host's local date | ENG05 |
| C10 | Low | Halt | A circuit-breaker halt (automatic and halt-all) cancels indexed quotes but not an orphaned hit-leg remainder; disconnect, kill switch and cancel-symbol do. Quote rejects on a halt always say "circuit breaker halt" even for an admin halt | ENG06 |
| C11 | Low | Halt | An admin-halted symbol with no breaker configured stays halted across CLOSED; the end-of-day reset walks `_circuit_breakers` only | ENG06 |
| C12 | Low | Wire order | Inside one dispatch the sibling's `order.cancelled` / `quote.status` / `oco.cancelled` are published from the book hook, before the `order.fill` that caused them | ENG09 |
| C13 | Low | Hygiene | `Engine(verbose=...)` is kept "for backward compatibility" and does nothing; the project has no backward-compatibility rule | ENG07 |
| C14 | Low | Auction | `_resolve_self_match` fires `on_oco_leg_done` a second time after `_smp_cancel_resting` already did | ENG07 |
| C15 | Low | Queries | `_handle_symbols_request` looks participants up with the un-uppercased id; a mixed-case caller silently gets no MM-obligation fields | ENG07 |
| C16 | Low | Shutdown | `_shutdown` is unguarded: a failed save skips the EOD checkpoint, the `system.eod` broadcast and the socket close | ENG07 |
| C17 | Low | Parsing | `Order.from_dict` maps an unknown `smp_action` string to `None`, i.e. to the gateway default, instead of refusing it | ENG07 |
| P1 | Low | Loop | Maintenance runs after every message; 5.7 µs per pass with 50 breakers (measured), ~4 % of an order under load | ENG08 |
| P2 | Low | Book | `fillable_quantity` sorts the whole opposite heap; the AON pre-flight does it twice per leg | ENG08 |
| P3 | Low | Queries | Every `session_schedule_request` rebuilds a two-year `holidays` calendar | ENG08 |
| P4 | Low | Queries | Quote bootstrap, QLEGS and `orders_request` build an id map over every resting order of every book per request | ENG08 |
| P5 | Low | Drop copy | `asdict()` per counterparty per trade | ENG08 |
| D1–D13 | — | Comments | See §5: gate numbering drift, a wrong circuit-breaker rule in a docstring, a wrong collar scope in a module header, a `replay()` nobody calls, an "all gates passed" comment above a reject | ENG09 |

---

## 3. Correctness findings

### C1. Engine-initiated cancels leak the OCO pair *(repro)* — High

`OrderBook.cancel_order` does not fire `on_oco_leg_done` (order_book.py:679),
and the engine's own cancel paths do not call `_check_oco_after_event`
either:

| Path | Cancels via | OCO follow-up | Combo follow-up |
|---|---|---|---|
| `_handle_cancel` (client) | `book.cancel_order` | yes (6765) | yes (6762) |
| book fill / SMP / IOC rest | hook `on_oco_leg_done` | yes | via `_publish_dispatch` |
| `_cancel_order_by_id` (3120) — used by kill switches, cancel-symbol, disconnect `CANCEL_ALL`, quote replace | `book.cancel_order` | **no** | **no** |
| `_expire_tif` (6067) | `book.cancel_order` | **no** | yes (6093) |
| `_cascade_cancel_combo` (5820), `_handle_oco_cancel` (6584) | `book.cancel_order` | n/a | n/a |

Consequence, reproduced: a DAY OCO pair expires at the close; on the next
trading day of the same engine run the gateway resubmits the same `oco_id`
and gets `OCO id BRACKET-1 is already in use` (main.py:6332). The pair is
also still in `_order_to_oco`, which grows for the life of the process. The
same happens after a kill switch (self, gateway or global), an admin
cancel-symbol and a `CANCEL_ALL` disconnect. The existing test
`test_an_id_is_free_again_once_its_pair_is_done` covers only the client's
own `order.oco_cancel`, which unlinks the group itself.

**Fix:** give the engine one cancel funnel. `_cancel_order_by_id` becomes the
only way engine code cancels a resting order, and after a successful cancel
it runs the two follow-ups the client path runs (`_check_combo_after_child_event`,
`_check_oco_after_event`). `_expire_tif` and `_handle_oco_cancel` use it too
(the latter already removes the group itself; make the follow-up a no-op in
that case by popping the group first, as `_cascade_cancel_combo` does for
combos). Add an engine-level invariant helper to `tests/engine_harness.py`:
every id in `_oco_groups`, `_order_to_oco` and `_order_to_combo` names an
order that is resting or waiting in a book's `_triggered`; call it at the end
of every batch-cancel test.

### C2. The same paths leave a combo half-dead *(repro)* — High

Reproduced: a two-leg AON combo (AAPL/MSFT) and a kill switch for its
gateway. Both children are cancelled; the parent stays `PENDING`, no
`combo.status` is published, and `_order_to_combo` keeps both ids. The combo
is then written to `gtc_combos.json` as live and restored as live.

By inspection the admin cancel-symbol is worse: it cancels only the leg in
that symbol, the combo follow-up never runs, so the other legs keep resting
with no cascade and the combo can neither complete nor fail. The participant
guide's AON promise ("any leg cancelled → FAILED, siblings cancelled") does
not hold for exchange-initiated cancels.

**Fix:** WP-ENG01's funnel. Decision Q1 picks the terminal status
(recommend `FAILED` with reason `Leg n (SYM) CANCELLED`, which is what the
existing `_check_combo_after_child_event` already does for a client cancel).

### C3. Structure handlers answer nobody on an internal error *(repro)* — Med

`_reject_after_error` (7425) addresses `payload["order_id"]`; an OCO payload
carries `oco_id`, a combo `combo_id`, and the quote topics are not in
`_ORDER_TOPICS` at all. Reproduced with `order.oco` carrying `"tif":
"FOREVER"`: `TIF()` raises at 6342, outside any `try`; the only publication
is `system.diagnostic`. The gateway waits for a timeout, exactly the limbo E3
of the pre-beta review removed for plain orders.

Reachable today from well-formed-looking requests: a bad `tif` or
non-integer `quantity` on an OCO (6341–6342), a bad enum in
`ComboOrder.from_submission_dict` (5639), C4 below.

**Fix:** (a) move the parsing at 6340–6342 and 5639 inside a guard that
answers with the structure's own ack, `accepted=false`,
`reject_code=MALFORMED_MESSAGE`; (b) teach `_reject_after_error` the three
structure topics: `oco.ack`/`combo.ack` with `INTERNAL_ERROR` keyed by
`oco_id`/`combo_id`, `quote.ack` keyed by `quote_id`+`symbol`, keeping the
"fills already printed" wording when `_fills_published` moved. The reject
funnel (`_oco_ack`, `_combo_ack`, `_quote_ack`) already counts them.

### C4. A trailing-stop OCO leg without a reference asserts inside the book *(repro)* — Med

`_handle_new_order` rejects a `TRAILING_STOP` with no `stop_price` when the
book has no last trade (2121–2131). `_handle_oco_order` only resolves the
stop when a last trade exists (6489–6497) and otherwise posts the leg;
`_add_trailing_stop` then fails its assertion (order_book.py:1622). By then
leg 1 has been acked and rests, the pair is registered, and the client gets
nothing (C3). Reproduced: `error_count=1`, leg 1 resting, no `oco.ack`.

**Fix:** the same gate as the single-order path, applied to both legs before
either is posted, answered with `oco.ack accepted=false MISSING_FIELD`.

### C5. Reference reload half-applies *(repro)* — Med

`_handle_reference_reload` (2374) refuses a changed symbol or index set, then
replaces `self._engine_config` and rebuilds the reference cache. Everything
that reads `self._engine_config` live changes immediately — `_resolve_smp_action`
(1040), the MM-obligation and quote-refresh policies (3827, 4038), the role
and disconnect behaviour a gateway gets on its *next* connect (2782). Everything
copied out of the config at startup keeps the old value: `_allowed_participants`,
`_gateway_descriptions`, `metrics.known_gateways`, `_collars`, `_order_limits`,
`_circuit_breakers`, `_sessions_enabled`, the two enforce flags, the tuning
values.

Reproduced: a reload adding participant `GW99` and setting every participant's
`smp_action` to `CANCEL_BOTH` is accepted; `GW99` cannot connect (not in the
allowlist) while `GW01`'s SMP default changed under its resting orders. Worse,
`_rebuild_reference_cache` reads collar bands and order limits from the *new*
config, so `GET /reference/symbols` advertises bands the engine does not
enforce.

**Fix:** decision Q2, then WP-ENG03. Recommended contract: a reload may change
only what the reference cache publishes (collar and order-limit figures,
circuit-breaker ladders, descriptions, schedule) and must apply those
explicitly (`_collars[sym].static_band_pct = ...`, rebuild `_order_limits`,
replace `CircuitBreakerConfig` on a non-halted breaker); a changed participant
set, role, `sessions_enabled`, enforce flag or tuning value is refused with the
same wording the symbol-set change gets.

### C6. `GET /reference` schedule goes stale at midnight — Med

`_rebuild_reference_cache` (2337) calls `_weekly_schedule_wire`, which
resolves `today`, `today_is_holiday` and `upcoming_holidays` at build time
(354–362). The cache is rebuilt only on load and reload, so in a multi-day
run the REST reference endpoint reports yesterday's `today` from the second
day on; `_handle_session_schedule_request` (2677) recomputes and is correct,
so the two endpoints disagree. The SHA-256 `config_version` includes the date
fields, so the same file produces a different version on a different day.

**Fix:** cache the static weekly table only; attach the `today*` fields in
`_handle_reference_request` at reply time; hash the static part.

### C7. A corrupt `book_stats.json` prevents startup *(repro)* — Med

`load_book_stats` returns whatever JSON parses (persistence.py:225). `_load_config`
then does `float(persisted["prev_close"])` (1195), `to_ticks(...)`, and
`window["saved_ns"]` / `window["trades"]` (1420–1422) with no guard. A
non-numeric value, a list root, or a `cb_window` missing a key raises out of
`_startup`, which `run()` does not catch: the engine exits before serving.
Reproduced with `{"AAPL": {"prev_close": "abc"}}`. The companion files are
guarded per entry and copied aside (`keep_corrupt_copy`); this one is not,
and it is rewritten by the first checkpoint 5 s after a successful start.

**Fix:** validate per symbol in `load_book_stats` (numeric prices, well-formed
`cb_window`), skip and log a bad entry at CRITICAL, keep the corrupt copy,
and report the count in `system.startup_recovery`.

### C8. A persisted PARTIAL order is restored as NEW *(repro)* — Low

`_restore_gtc` sets `order.status = OrderStatus.NEW` (1643) for every restored
order. A PARTIAL order keeps `remaining_qty < quantity` but reports `NEW` in
`orders_request`, `price_level_orders`, QLEGS and the book checkpoint until
its next fill. Fix: `PARTIAL if remaining_qty < quantity else NEW`.

### C9. Three notions of the business date — Low

`_restore_gtc` judges a DAY order by the date in the session timezone (1595);
`_archive_eod` names its directory with `datetime.now().date()` (1452), and
its own comment claims it is "the business date the restore judges DAY orders
by"; `_weekly_schedule_wire` resolves `today` with the host's local date
(354). On a host whose zone differs from `locale.session_timezone` the archive
lands in the wrong day's folder around midnight. Fix: one
`Engine._business_date()` helper used by all three.

### C10. Halt paths differ on orphaned quote legs — Low

A quote hit on one side under `INACTIVATE_ON_ANY_FILL` leaves its remainder
resting outside the `QuoteIndex`. Disconnect (4325), both kill switches
(4451, 4596) and cancel-symbol (5179) sweep those; `_check_circuit_breaker`
(3607) and `_handle_circuit_breaker_halt_all` (4822) do not, so a halt pulls
the market maker's quotes but not that remainder. Separately,
`_handle_quote_new`'s halt reject (3953) always reads "circuit breaker halt";
it should use `_halt_reject_code` like the order path (2044).

### C11. Admin halts survive CLOSED when no breaker is configured — Low

The CLOSED block (6001–6004) deactivates every *breaker* that is halted; a
symbol halted by `_handle_symbol_halt` without a `circuit_breaker` section
has only `_halted_symbols[sym] = True` and stays halted into the next day.
Decision Q3: intended (an operator's halt is theirs to lift) or not. Either
way the comment "End-of-day reset for any still-halted symbols" is wrong as
it stands, and the loop is redundant for breaker symbols because
`_run_closing_backstop` already reopened them (see D7).

### C12. Effects are published before their cause inside one dispatch — Low

`_apply_fill` calls the quote and OCO hooks mid-sweep (order_book.py:2043–2058),
and the engine publishes the sibling's `order.cancelled`, `quote.status
INACTIVE_*` or `oco.cancelled` right there, before `process()` returns and
`_publish_dispatch` sends the `order.fill` that triggered them. The causal
envelope is the same, so pm-audit orders them correctly, but a gateway or
GUI reading the raw stream sees a cancel "for no reason" followed by the fill.
This is a consequence of X3/X15 (the sibling must be gone before the next
fill of the sweep), so the order of *book mutation* must stay. Decision Q4:
document it (participant guide, `_publish_dispatch` docstring) or buffer the
hook's publications until after the fills. Recommend documenting for 1.0.

### C13–C17. Small items — Low

- **C13** `Engine.__init__(verbose=...)` (598–603) is kept "for backward
  compatibility" and has no effect. Remove the parameter and its callers.
- **C14** `auction._resolve_self_match` (499–503, 514–519) calls
  `on_oco_leg_done` after `_smp_cancel_resting`, which already called it via
  `_oco_leg_ended` (order_book.py:1758). Harmless (idempotent) and misleading.
- **C15** `_handle_symbols_request` (2462, 2482) clamps the id without
  upper-casing and then looks it up in `participants`, which is keyed
  upper-case. Every other handler upper-cases.
- **C16** `_shutdown` (7151) performs three saves, a checkpoint publish, the
  EOD broadcast and four closes with no guard; the first failure skips the
  rest, including the socket close that lets the port rebind.
- **C17** `Order.from_dict` (342) turns an unknown `smp_action` into `None`,
  which `_resolve_smp_action` then reads as "client omitted it". A typo in a
  hand-built client silently gets the gateway default.

---

## 4. Performance findings

All Low. The engine is well within classroom requirements; these are the
remaining avoidable costs on the hot path and on request paths that GUIs
poll.

- **P1** `run()` calls `_run_maintenance()` after *every* loop pass (7790–7798),
  so under load it runs per message: six clock reads and a walk over every
  breaker (`_flush_circuit_breakers`) per order. Measured 5.7 µs per pass with
  50 breakers, against the ~130 µs per order the design notes quote. Throttle
  to a time slice (for example every 10 ms, or every 64 messages, whichever
  comes first) when a message was handled; keep per-tick when idle. The
  breaker timers have 200 ms granularity anyway (the poll timeout), so a 10 ms
  slice changes no observable behaviour.
- **P2** `fillable_quantity` (order_book.py:1452) sorts the whole opposite heap;
  `_accept_combo` calls it twice per AON leg (5505–5524). Stop once `total >=
  quantity` for the FOK case; compute `fillable` and `unprevented` in one walk.
- **P3** `_weekly_schedule_wire` builds a two-year `holidays` calendar per call
  (`upcoming_holidays`), and `_handle_session_schedule_request` calls it per
  request. Cache per `(country, date)`.
- **P4** `_handle_quote_bootstrap_request` (2917), `_active_quote_legs` (3018)
  and `_handle_orders_request` (2823) walk every resting order of every book
  per request. The first two need only `book.get_order(entry.bid_order_id)`
  via `_order_symbol`; the third can use `book.orders_for_gateway`.
- **P5** `DropCopyPublisher.publish_fill` (169) does `asdict(msg)` (a deep copy
  of `trade_ids`) twice per trade. Build the kwargs directly.

Checked and fine: `_executions` is one pass; `_fill_frames` avoids
`Order.to_dict`; `_compact_heaps` is amortised O(1); `snapshot()` is bounded
by compaction; `_flush_trace` is per dispatch; the label cache in
`EngineMetrics` bounds cardinality.

---

## 5. Comments and docstrings

The walkthroughs that matter most — the module docstrings of `main.py` and
`order_book.py`, `_handle_new_order`, `OrderBook.process`, `_sweep`,
`_apply_fill`, `_publish_dispatch`, `_run_uncross`, `_flush_circuit_breakers`,
the OCO and combo section comments — are accurate and good enough to follow
every main flow from the text alone. The drift is in the details:

- **D1** `_handle_new_order`'s gate table (1898–1902) lists nine gates and
  omits the trailing-stop reference gate (2121–2131), which sits *below* the
  comment "All gates passed: from here the order WILL be accepted" (2116) and
  below the `NEW …` info log (2111). Move the gate above the log or renumber
  it as gate 10 and move the comment.
- **D2** Gate numbers drift: `_book_reject` (3412) and `_handle_oco_order`
  (6477) call the halt check "gate 8"; it is `[7]`. `_collar_breach` (5667)
  says gate 8, which is right.
- **D3** `_check_circuit_breaker`'s docstring (3578–3579) says the halt fires
  when "the rolling-window average has moved more than `dynamic_band_pct` from
  the trigger price". `record_trade` fires when `|trade − window average| /
  average >= level.price_shift_pct`, highest matching level wins, and an
  auction print joins the window but never fires. `dynamic_band_pct` is a
  collar term.
- **D4** `collar.py` header (23–25): "Both bands are checked on every LIMIT
  and ICEBERG order. MARKET/FOK/IOC orders bypass". The engine collars every
  order carrying `price_ticks` (2068): FOK, IOC and STOP_LIMIT included.
- **D5** `drop_copy.py` header: "The engine calls `replay(...)`". Nothing
  does (`grep` finds only docs). State that it is a library hook for embedded
  consumers and tests, or remove it.
- **D6** `persistence.load_book_stats` docstring describes the value shape as
  `{last_buy_price, last_sell_price}`; it also carries `prev_close` and
  `cb_window`.
- **D7** `_handle_session_transition` CLOSED block (6000): "End-of-day reset
  for any still-halted symbols (e.g. L3 rest-of-day)". `_run_closing_backstop`
  two lines earlier has already reopened every halted breaker, so this loop is
  a no-op for breakers and does not touch admin halts without one (C11). Say
  what it is (a belt-and-braces guard) or remove it.
- **D8** M9 comment (2141–2146) and `models/clock.py` call `now_ns()` "the
  monotonic clock". It is wall-clock nanoseconds with a never-decrease guard:
  after a backwards step every timestamp is the previous one plus 1 ns until
  the wall clock catches up. The property claimed (never backwards) holds; the
  name does not. Say so where the guard is described.
- **D9** `_handle_gateway_connect` (2760) and `__init__` (634) call the
  no-config mode "backward-compat mode". There is no compatibility rule in the
  project; call it what it is (no configuration loaded).
- **D10** `OrderBook.resting_orders` docstring: "used for persistence". It is
  the backbone of a dozen handlers; say "every full-book read".
- **D11** `_check_stops` (2294–2298) references `tools/mutate_engine.py`
  mutant M11 and asks the lines to stay adjacent. The tool exists; keep the
  note but add the reason a reader needs it (the mutation test matches the
  text).
- **D12** `_archive_eod` docstring claims the session business date (C9).
- **D13** `_handle_quote_new`'s docstring says "Unlike `order.new` every reject
  here is a `quote.ack` with `accepted=False`" — true today, and WP-ENG02 must
  keep it true for the internal-error path as well; add the sentence there.

Verified true and worth saying so: the ACK-before-match and deferred-ack
(X5) comments; the `_triggered` waiting-room comment; the iceberg index
accounting comments in `_apply_fill`; the `_orders_by_gateway` maintenance
list on its definition; the X8a/X8b/X15/X17 comments in the quote, uncross
and OCO paths; `_echo_command`'s two-property argument; `CausalPublisher`'s
contract as used by `run()`, `_flush_circuit_breakers` and
`_expire_silent_gateways`.

---

## 6. Verified as correct

Listed because it matters as much as the defects for a 1.0 decision.

- **Receive loop:** receive + decode + envelope inside the guard; dispatch
  guarded with the four failure counters; maintenance guarded per flush;
  signal handlers only flip the flag; `_shutdown` reached on every exit from
  the loop (but see C16 for its own body).
- **Order path:** duplicate ids refused before the ack; routing entry
  registered only after the book accepted (M8) and dropped in
  `_publish_dispatch` on every terminal status; deferred ack for anything the
  book may reject; one reject per order on every gate.
- **Book:** heap/`_entry_index`/`_bid_qty`/`_order_index`/`_orders_by_gateway`
  kept in step in `_rest`, `_apply_fill`, `_reinsert_iceberg`, `cancel_order`,
  `amend_order`, `_smp_cancel_resting`, `_check_stops`,
  `_check_trailing_stops`; lazy deletion plus compaction; a cancelled
  triggered stop does nothing when its turn comes; the iceberg guard in
  `process` prevents the infinite sweep.
- **SMP:** all four policies in `_sweep`, in the FOK pre-check, in
  `fillable_quantity` (stop-at-first for the aggressor policies), and in the
  auction dry run and residual resolution.
- **Auction:** curves in one pass; bound-ordered candidate scan gives the
  full-scan winner; SMP/OCO dry run only when it can matter; override price
  honoured only when a natural equilibrium exists except for `ADMIN_MANUAL`;
  K1 resolve-without-print path; stops run after the print through the same
  `run_stops` as continuous trading.
- **Circuit breaker:** window average before the trade; auction prints never
  trigger; ACE extension when the indicative is outside the corridor; random
  tail from the configured RNG; closing backstop clamps to the corridor and
  publishes `clamped`.
- **Persistence:** atomic writes with fsync; corrupt order/combo files kept
  aside; run sequence fail-loud; checkpoint every 5 s; DAY orders restored
  within the business day; OCO pairs re-linked only when both legs survive;
  quote index rebuilt from legs.
- **Sessions:** transition table enforced; uncross on leaving a call phase;
  ATO/ATC/DAY expiry at the right boundaries; daily counters carried into the
  monotonic health counters before reset.
- **Metrics:** label cardinality bounded; sampled timing; GC policy freeze
  after the open, routine collection on idle ticks.

---

## 7. Decisions

All five decided 2026-11-13 as recommended.

| # | Question | Decision |
|---|---|---|
| Q1 | Terminal combo status when the exchange cancels a leg (kill switch, cancel-symbol, disconnect, expiry)? | `FAILED` with reason `Leg n (SYM) CANCELLED` — the status `_check_combo_after_child_event` already gives a client cancel; one rule for every cancel. |
| Q2 | Reload contract: what may `POST /admin/reference/reload` change mid-session? | Only what the reference cache publishes (collar/limit figures, breaker ladders, descriptions, schedule), applied explicitly; refuse participant-set, role, `sessions_enabled`, enforce-flag and tuning changes with the existing "requires a restart" wording. |
| Q3 | Should an admin halt without a breaker be lifted at CLOSED? | No: an operator halt is the operator's to lift. Keep it, fix the comment, and make `_handle_halt_status_request` the place it is visible the next morning. |
| Q4 | Sibling cancels published before the fill that caused them (C12)? | Document for 1.0 (participant guide + `_publish_dispatch`); buffering is a 1.x change if a GUI needs it. |
| Q5 | Quotes bypass the price collar and order limits; combos and OCOs bypass order limits (both documented as deliberate in `_collar_breach` and `_validate_combo`). Keep for 1.0? | Keep, and add one sentence to the participant guide's risk-controls chapter listing exactly which entry paths each control covers. Not a WP here. |

---

## 8. Work packages

Each WP lists the tests to write first, the production change, and the exit
criteria. Test files are new unless named as existing.

### WP-ENG01 — One engine-initiated cancel funnel (C1, C2)

**Goal.** Every cancel the exchange decides on runs the same OCO and combo
follow-ups a client cancel runs, so no structure is left half-dead and no
`oco_id` is blocked after its pair is gone.

**Tests first** (`tests/test_engine_cancel_funnel.py`):

1. DAY OCO pair; `_expire_tif(TIF.DAY)`; the same `(gateway, oco_id)` is
   accepted again; `_oco_groups` and `_order_to_oco` are empty after the
   expiry; one `oco.cancelled` (or two `order.expired`, decide in the test what
   the wire must say — recommend the expiry messages only, no
   `oco.cancelled`, since both legs expired on their own).
2. OCO pair; kill switch (self), then kill switch (gateway, by ADMIN), then
   global kill switch, each in a fresh engine: group unlinked, id reusable,
   `cancelled_order_ids` lists both legs.
3. OCO pair; admin cancel-symbol: same.
4. OCO pair; gateway disconnect with `CANCEL_ALL`: same.
5. AON combo A/B; kill switch: parent reaches the Q1 status, one
   `combo.status` with that status, `_order_to_combo` empty, the combo is
   absent from the next `save_gtc_combos` output.
6. AON combo A/B; admin cancel-symbol on A: leg B is cancelled too, parent
   terminal, `combo.status` published once.
7. AON combo; disconnect `CANCEL_ALL`; and DAY combo at `_expire_tif(DAY)`:
   same assertions (the expiry path already cascades; the test pins it).
8. An invariant helper `assert_engine_links(engine)` in
   `tests/engine_harness.py` (every id in `_oco_groups`, `_order_to_oco`,
   `_order_to_combo` is resting or in a book's `_triggered`; every
   `_order_symbol` key is resting, triggered, or a quote leg mid-dispatch),
   called at the end of tests 1–7 and added to the existing kill-switch,
   cancel-symbol and disconnect tests (`test_engine_admin_scoped_cancel.py`,
   `test_engine_mass_cancel_inactive_quote.py`, `test_engine_handlers*.py`).

Expected failure before the change: test 1 fails on `accepted=False` with
"already in use"; test 5 fails on `combo.status == PENDING`.

**Change.** `_cancel_order_by_id` runs `_check_combo_after_child_event` and
`_check_oco_after_event` after a successful `book.cancel_order`;
`_expire_tif` and `_handle_oco_cancel` go through it (the latter pops the
group first so the follow-up is a no-op); `_cascade_cancel_combo` keeps its
direct cancels (the combo is already terminal) but publishes
`cancel_reason` like every other engine cancel. Update the OCO section
comment (6290–6296) to name the funnel as the second call site.

**Exit criteria.** Tests 1–8 pass; `assert_engine_links` holds in every
engine test that batch-cancels; `grep -n "book.cancel_order" src/edumatcher/engine/main.py`
shows only `_handle_cancel`, `_handle_amend` (marketable re-entry),
`_cancel_order_by_id`, `_expire_tif` (publishes `order.expired`, then the
follow-ups) and the two follow-ups themselves (`_cascade_cancel_combo`,
`_check_oco_after_event`); full engine suite green;
`docs/books/participant-guide/part-2-orders/030-combo-and-oco-orders.md`
states that an exchange-initiated cancel of one leg ends the structure.

**Outcome (2026-11-13).** `tests/test_engine_cancel_funnel.py` (12 tests)
and `assert_engine_links` in `tests/engine_harness.py`, also called from the
scoped-cancel and inactive-quote mass-cancel tests. `_after_engine_cancel`
is the one follow-up; `_cancel_order_by_id` runs it (or defers it for a
batch), `_cancel_orders` is the batch used by both kill switches, the global
kill switch, cancel-symbol, `CANCEL_ALL` disconnect and `_handle_oco_cancel`;
`_expire_tif` runs the follow-ups after its sweep. Design choice: follow-ups
run once the whole batch is gone, so legs the command itself pulled carry
its `cancel_reason` and appear in its ack, and the cascade reports only
what the command did not reach (a combo's legs in other symbols on a
cancel-symbol). Q1 as recommended: `FAILED`, reason `Leg n (SYM) CANCELLED`.
Participant guide §Cascade Cancellation gained the exchange-initiated case.
Engine + audit suites: 2252 passed.

### WP-ENG02 — Structure handlers always answer (C3, C4)

**Goal.** An OCO, combo or quote request gets exactly one answer, accepted or
refused, whatever goes wrong inside the handler.

**Tests first** (`tests/test_engine_structure_error_contract.py`):

1. `order.oco` with `tif: "FOREVER"` → one `oco.ack accepted=false
   reject_code=MALFORMED_MESSAGE`, nothing posted, `error_count == 0`.
2. `order.oco` with `quantity: "ten"` → same.
3. `order.combo` with `combo_type: "ALL"` → `combo.ack accepted=false
   MALFORMED_MESSAGE`.
4. Monkeypatch `_accept_combo` / the OCO book to raise mid-way → the
   structure's ack with `INTERNAL_ERROR`; when a fill printed first, the
   "fills already printed" wording.
5. Monkeypatch `book.process` to raise inside `_handle_quote_new` after the
   `quote.ack accepted=true` → a `quote.status CANCELLED` with reason
   `Internal error`, both legs gone from the book and the index (the quote was
   already acked, so the answer is a status, not a second ack).
6. OCO with a `TRAILING_STOP` leg, no `stop_price`, no last trade → `oco.ack
   accepted=false MISSING_FIELD`, no leg posted, no group registered.
7. Same with a last trade present → accepted; leg's stop resolved as the
   single-order path does.

**Change.** Guard the OCO/combo payload parsing with a reasoned reject; add
the trailing-stop reference gate to `_handle_oco_order` before either leg is
posted; extend `_reject_after_error` with a per-topic table
`{topic: (builder, id_key)}` covering `order.oco`, `order.combo`,
`quote.new`, and add `quote.new`/`quote.cancel` to `_ORDER_TOPICS` (rename it
`_ANSWERED_TOPICS` so the name says what it is).

**Exit criteria.** Tests 1–7 pass; every handler in `_dispatch_pull_message`
for a topic in `_ANSWERED_TOPICS` has a documented answer on the exception
path (table in `_reject_after_error`'s docstring); `_handle_quote_new`'s
docstring sentence (D13) holds; engine suite green.

**Outcome (2026-11-13).** `tests/test_engine_structure_error_contract.py`
(17 tests). Two deviations from the plan above: `oco.ack` and `combo.ack`
carry no `reject_code` field (only the cancel acks do), so a malformed
payload is refused with reason `Invalid OCO/combo payload: …`, which
`reject_label` already counts as `MALFORMED_MESSAGE`; and the post-ack
failure path was generalised to all three structures rather than quotes
only. Mechanics: `_ANSWERED_TOPICS` (was `_ORDER_TOPICS`) now includes
`quote.new`/`quote.cancel`; `_reject_after_error` takes the exception and
builds the answer per topic in `_error_answer`; a handler that fails after
its accept ack cleans up (`_end_unposted_leg` for an acked leg that never
reached a book, the existing cancel paths for the rest), ends the structure
(combo `FAILED` with reason `Internal error: …`, quote `CANCELLED`, OCO
unlinked) and raises `_AlreadyAnswered`, which the dispatcher counts and
diagnoses without sending a contradicting second ack. The OCO trailing-stop
reference gate (C4) runs before either leg is posted. Engine + audit suites:
2315 passed; black/flake8/mypy/pyright clean.

### WP-ENG03 — Reference-reload contract (C5; after Q2)

**Tests first** (`tests/test_engine_reference_reload.py`, extending the
existing reload tests):

1. Reload with a participant added → refused, reason names participants.
2. Reload with a role / `sessions_enabled` / `enforce_collars` / tuning
   change → refused.
3. Reload with a changed collar band → accepted; `_collars[sym]` has the new
   band; `risk.band.<SYM>` republished; a new order is judged by the new band;
   `GET /reference/symbols` and `_handle_risk_state_request` agree.
4. Reload with changed order limits → accepted and enforced on the next order
   and amend.
5. Reload with a changed breaker ladder on a non-halted symbol → accepted;
   `cb.config` replaced; on a halted symbol → refused for that symbol (or
   applied at `deactivate()` — decide in the test).
6. Reload with changed descriptions → `_gateway_descriptions` updated; next
   `gateways_request` shows it.

**Change.** Factor the "copy config into live state" lines of `__init__` and
`_load_config` into `_apply_static_reference(cfg)` used by both startup and
reload; a diff function that refuses the non-reloadable sections.

**Exit criteria.** Tests pass; every attribute `__init__`/`_load_config`
copies from `EngineConfig` is either applied by the reload or named in the
refusal; `_handle_reference_reload`'s docstring lists both sets; operator
guide reload section updated.

### WP-ENG04 — Startup-state robustness (C7, C8)

**Tests first** (extend `tests/test_engine_corrupt_startup_state.py` and
`tests/test_engine_restart_contract.py`):

1. `book_stats.json` with `prev_close: "abc"` for one symbol → engine
   starts, that symbol's stats are skipped and logged CRITICAL, a
   `.corrupt-<stamp>` copy exists, `startup_recovery` reports
   `failed_book_stats=1` (new field; add to `spec/messages/system.yaml`).
2. `cb_window` missing `trades` → breaker seeded from the last price instead;
   engine starts.
3. Root is a list → treated as empty, file kept aside.
4. A persisted PARTIAL order (remaining 4 of 10) restores with
   `status=PARTIAL`; `orders_request` shows PARTIAL; the next fill is reported
   with `cum_qty=7`.

**Change.** Per-symbol validation in `load_book_stats` mirroring
`load_gtc_orders`; status derived from quantities in `_restore_gtc`.

**Exit criteria.** Tests pass; `load_book_stats` docstring (D6) lists the
schema and the per-entry policy; no path in `_startup` can raise on file
*content* (only on an unreadable config, which stays fatal by design).

**Outcome (2026-11-13).** `load_book_stats` now returns `(stats, failed)`:
a bad price (not a positive finite number, `bool` excluded) or a non-object
entry skips the symbol; a malformed `cb_window` drops only the window, so
the breaker is seeded from the last price; each is CRITICAL, with the file
kept once via `keep_corrupt_copy`. Deviation from test 3: an unparseable
file or a non-object root counts as **one** failure (not zero), so
`failed_book_stats` is never silent about a lost file. To get the count into
`system.startup_recovery`, which goes out before `_load_config`, the stats
are now read at the top of `_restore_gtc` (into `self._book_stats`) and only
applied by `_load_config`; four tests that called `_load_config()` alone
with persisted stats now call `_restore_gtc()` first, as `_startup` does.
New field `failed_book_stats` (spec, generated bindings, message reference,
pm-audit replay `recovery_counts`, operator guide audit-trail table, golden
fixture 05); four ledger entries for the new CRITICAL logs. C8:
`_restore_gtc` derives `PARTIAL`/`NEW` from the quantities.

The exit criterion "no path in `_startup` can raise on file content" turned
up a wider gap: `Order.from_dict`/`ComboOrder.from_dict` copy values
unchecked, and `_restore_gtc` uses `symbol`/`arrival_seq` (sort key),
`ts_ns` (DAY date), `remaining_qty`/`quantity` (the new C8 status — which
would itself have crashed on `"4"`) outside its `book.process` guard. The
loaders now check those fields (`_checked_order`, `_checked_combo`: types,
`0 < remaining_qty <= quantity`, timestamps within `datetime` range) inside
their existing skip-and-keep guard. Three old round-trip tests in
`test_p1_coverage.py` persisted float `price_ticks` (`150.0`); their data
is now int ticks. Tests: `test_engine_corrupt_startup_state.py` (+38),
`test_engine_restart_contract.py` (+1). Full suite 13978 passed, coverage
90.9 %; `make _check` and `make test-e2e` clean.

### WP-ENG05 — One business date (C6, C9, D8)

**Tests first** (`tests/test_engine_business_date.py`):

1. With `session_timezone=Pacific/Auckland` and a host clock at 23:30 UTC,
   `_archive_eod` writes under the Auckland date; `_restore_gtc` and
   `_weekly_schedule_wire` use the same date (freeze the clock via the
   harness's time shim).
2. `reference_request` on day D then on D+1 without a reload → `today`
   changes, `config_version` does not.
3. `session_schedule_request` and `reference_request` return identical
   `today`/`today_is_holiday` on the same call.

**Change.** `Engine._business_date()` (session tz) used by all three sites;
reference cache stores the static table; `_handle_reference_request` adds
the per-day fields; digest over the static part; rename the M9 comment and
`clock.py` docstring per D8.

**Exit criteria.** Tests pass; `grep -n "datetime.now()" src/edumatcher/engine/main.py`
finds no naive call; operator guide's persistence chapter names the session
timezone as the archive date.

**Outcome (2026-11-13).** `tests/test_engine_business_date.py` (3 tests;
the clock is frozen by swapping `engine.main.datetime` for a subclass, since
the harness's time shim does not reach `datetime`; the host is simulated on
UTC and the exchange in Auckland on Christmas Day). `Engine._business_date()`
(session timezone) is now the only `datetime.now` in `engine/main.py`, used
by the DAY-order restore, the breaker-window same-day check, `_archive_eod`
(D12 docstring fixed) and the schedule. `_weekly_schedule_wire` takes
`today` from its caller; `_weekly_table_wire` is the static part, which is
all the reference cache holds and all `config_version` hashes; both schedule
replies go through `Engine._schedule_wire()`, so they agree by construction.
D8: `models/clock.py` and the M9 comment now say wall clock with a
never-decrease guard. Docs: the persistence chapter said "machine-local" in
three places (the restore had used the session timezone already, so that one
was wrong before); spec `WeeklySchedule` and `config_version` docs say what
"today" is and what the hash excludes (bindings, message reference and
`spec/rest/openapi.json` regenerated). Each reference reply now runs the
holiday lookup, as the session-schedule reply already did: WP-ENG08's
holiday-calendar cache (P-finding) covers both. Full suite 13981 passed;
`make _check` and `make test-e2e` clean.

### WP-ENG06 — Halt consistency (C10, C11, D7; after Q3)

**Tests first** (extend `tests/test_engine_handlers2.py` /
`tests/test_engine_mass_cancel_inactive_quote.py`):

1. Quote hit on the bid, remainder resting; breaker trips → remainder
   cancelled with `CIRCUIT_BREAKER_HALT`, `cancelled_quote_order_ids`
   includes it; same for halt-all and per-symbol admin halt.
2. Admin halt (no breaker) then `quote.new` → reject reason says trading
   halt, not circuit breaker; with a breaker trip → says circuit breaker.
3. Per Q3: admin-halted symbol without a breaker at CLOSED → still halted
   (and visible in `halt_status_request`) or cleared, as decided.

**Change.** One `_halt_symbol(symbol, reason, cancel_reason, command_id)`
helper doing the three quote sweeps (index, orphans) used by the four halt
sites; `_halt_reject_code` in the quote path; rewrite the CLOSED block per
Q3 and D7.

**Exit criteria.** Tests pass; the four halt sites call one helper; the
CLOSED block's comment describes what it does.

### WP-ENG07 — Small correctness cleanups (C13–C17)

**Tests first:** one focused test per item — `Engine()` has no `verbose`
parameter (grep test over `src/` and `tests/` for callers); a scratch
`OrderBook` with a counting `on_oco_leg_done` sees exactly one call per OCO
leg cancelled in `execute_uncross`; a lower-case `gateway_id` in
`symbols_request` gets the same MM fields as upper-case; `_shutdown` with a
raising `save_gtc_orders` still publishes `system.eod` and closes both
sockets; `Order.from_dict({"smp_action": "CANCEL_ALL"})` raises `ValueError`
and the order path answers `MALFORMED_MESSAGE`.

**Exit criteria.** Each test passes; no behaviour change outside the five
items; engine suite green.

### WP-ENG08 — Performance (P1–P5)

**Tests first** (`tests/test_engine_maintenance_throttle.py` plus
extensions):

1. With a fake clock, 1 000 messages inside 10 ms run `_run_maintenance`
   once; a breaker due at t+200 ms still reopens within one slice of its
   `resume_at_ns`; an idle tick still runs it every pass.
2. `fillable_quantity` for a FOK stops at the first level that satisfies the
   quantity (assert via a counting `_HeapEntry.__lt__` or by heap size vs
   compared entries).
3. Two `session_schedule_request`s on the same date build one calendar
   (monkeypatch `holidays.country_holidays` and count).
4. Quote bootstrap and QLEGS replies are unchanged byte-for-byte before and
   after the lookup change (golden test against the current output).
5. Drop-copy events unchanged byte-for-byte.

**Change.** Slice-throttled maintenance in `run()`; early exit in
`fillable_quantity` behind an explicit `need` argument; `functools.lru_cache`
keyed `(country, date)` in `schedule_resolve`; direct lookups in the three
request handlers; kwargs in `publish_fill`.

**Exit criteria.** Tests pass; `tests/test_engine_metrics.py` perf gate
unchanged; a before/after measurement of `_run_maintenance` per message and
of order p50/p99 with 50 breakers recorded in `docs-design/perf-notes.md`;
no change to any wire payload (golden tests).

### WP-ENG09 — Comments and docstrings (D1–D13, C12)

**Tests first.** Documentation has no unit tests; the check is a reading
protocol instead. Before editing, write the list of flows a new reader must
be able to follow from docstrings alone and the entry point of each:

| Flow | Entry | Must name every step to |
|---|---|---|
| New order | `main.py` module docstring → `_handle_new_order` | `_publish_trade` |
| Cancel / amend | `_handle_cancel`, `_handle_amend` | `_cancel_order_by_id` (post-ENG01), marketable re-entry |
| Quote | `_handle_quote_new` | `_on_quote_leg_filled`, `_cancel_orphaned_quote_legs` |
| OCO | OCO section comment | both hook sites, the funnel |
| Combo | combo section comment | `_check_combo_after_child_event`, cascade |
| Uncross | `_run_uncross` | `compute_equilibrium`, `execute_uncross`, `run_stops`, X8b |
| Halt / reopen | `_check_circuit_breaker` | `_flush_circuit_breakers`, ACE, backstop, admin reopen |
| Restore / checkpoint | `_startup` | `_restore_gtc`, `_load_config`, `_flush_persistence`, `_archive_eod` |
| Receive loop | `run` | `_echo_command`, `_dispatch_pull_message`, `_reject_after_error`, `_run_maintenance` |

**Change.** Fix D1–D13; add the C12 paragraph to `_publish_dispatch` and the
participant guide (per Q4); make the gate numbering a single table in
`_handle_new_order`'s docstring and refer to it by name ("the halt gate")
elsewhere rather than by number, so it cannot drift again.

**Exit criteria.** A reviewer who has not read the code before follows each
flow in the table from its entry docstring and ticks it off; `grep -n "gate [0-9]"`
in `main.py` returns only the table; every file path quoted in a docstring
exists (`scripts`-free check: a one-off grep of `docs/` and `docs-design/`
references); `mkdocs build` passes; the three module headers (`main.py`,
`order_book.py`, `auction.py`) are re-read end to end against the code once
WP-ENG01–08 have landed.

---

## 9. Out of scope, noted

- The gateways' handling of the `quote.ack`/`oco.ack`/`combo.ack`
  `INTERNAL_ERROR` replies WP-ENG02 introduces (api-gwy maps these codes
  already; ALF/BALF relay the ack line unchanged). Verify in the next e2e run.
- `startup_recovery.failed_orders` counts only orders whose `book.process`
  raised; an entry `load_gtc_orders` skipped (unparseable or mistyped) is
  logged CRITICAL and kept aside but not counted, and likewise for combos.
  Counting them needs the loaders to return a count as `load_book_stats`
  now does (found in WP-ENG04).
- `tests/engine_invariants.py` covers the book; WP-ENG01 adds the engine-level
  link invariant. A future review could fold both into one `assert_engine(engine)`
  used by every engine test.

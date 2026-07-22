# EduMatcher Matching Engine — Code Review

**Scope:** `src/edumatcher/engine/` (order_book.py, main.py, auction.py, circuit_breaker.py, collar.py, config_loader.py, drop_copy.py, persistence.py) plus the contracts it depends on (`models/order.py`, `models/trade.py`, `models/price.py`, `models/clock.py`, `models/session.py`, `models/message.py`).
**Review bar:** Educational-but-correct. Correctness defects are treated as must-fix; production-exchange gaps are noted briefly where they teach something. Performance findings are Python-realistic.
**Reviewer note:** Line numbers refer to the files as of this review (engine v0.16.x). Each finding has an ID for tracking (C = critical, H = high, M = medium, L = low, P = performance, A = architecture).

---

## 1. Executive summary

The engine is well-commented, has a sensible overall shape (per-symbol `OrderBook` with price-time priority, a single-threaded ZMQ event loop, separated risk modules for collars and circuit breakers), and is backed by a large test suite (~2,500 tests repo-wide). Integer-tick pricing internally with display conversion at the boundary is the right call.

However, the review found **six critical defects** that corrupt book state or lose participant notifications, and a cluster of high-severity issues that share two root causes:

1. **Denormalized state kept consistent by hand.** The book maintains three parallel structures per side (heap of `_HeapEntry`, `_entry_index`, `_bid_qty`/`_ask_qty` level index) plus two engine-level maps (`_order_symbol`, `_order_index`). At least four bugs below (C2, C3, H7, H8) are consistency failures between these structures.
2. **Events are mutable `Order` references, not immutable event records.** `OrderBook.process()` returns the *same live object* repeatedly in its `events` list, and the engine branches on the object's *final* status at publish time. This single design decision produces C4, H5, and H6.

Fixing the two root causes (Section 8) eliminates entire bug classes rather than individual symptoms.

| Severity | Count | Theme |
|---|---|---|
| Critical | 7 | State corruption, lost fills, startup crash, persistence round-trip, iceberg queue-jumping |
| High | 9 | Priority fairness, amend semantics, position/drop-copy divergence, session bypass |
| Medium | 14 | Notifications, validation, clock discipline, day-boundary hygiene |
| Low | 12 | Duplication, logging, typing, config verbosity |

---

## 2. Critical findings

### C1 — Book-stats persistence round-trip inflates prices by 10^tick_decimals on restart

- **Where:** `persistence.py:84-102` (`save_book_stats`) and `main.py:344-366` (`_load_config`).
- **What:** `save_book_stats` writes `book.last_buy_price` / `last_sell_price` **as raw integer ticks**. On restart, `_load_config` does `to_ticks(float(lbp_raw), sym)`. Because the value is coerced to `float`, `to_ticks` treats it as a *display* price and multiplies by `10^tick_decimals` (`price.py:52-63`). A persisted `15000` ticks ($150.00 at 2 decimals) reloads as `1,500,000` ticks ($15,000).
- **Impact:** After any restart with prior trades, the collar `reference_price` (`main.py:499-508`) and the circuit-breaker seed (`main.py:520-528`) are anchored 100× (or 10^N×) too high. The static collar band then rejects essentially every sane order for that symbol — a full-symbol outage that looks like a "collar misconfiguration." The current `data/book_stats.json` on disk only holds `null`s, which is why this hasn't been observed yet; it fires on the first restart after a trading session.
- **Fix:** Pick one unit for the file and be explicit. Simplest: persist display floats (`from_ticks(...)` at save), keep `to_ticks(float(...))` at load. Better: persist ticks *and* the `tick_decimals` used, and validate on load. Add a round-trip unit test (`save → load → assert equal ticks`).

### C2 — Auction uncross corrupts the bid price-level quantity index

- **Where:** `auction.py:166-178` (`execute_uncross`) calling `order_book.py:874-955` (`_apply_fill`).
- **What:** `execute_uncross` treats the best bid as "aggressor" and the best ask as "passive" for every fill. `_apply_fill` only calls `_deduct_qty_index` for the **passive** order — correct in continuous matching where the aggressor is not resting, but in an uncross **both orders are resting** and both are counted in the level indexes. The bid side's filled quantity is never deducted from `_bid_qty`.
- **Impact:** After every auction (opening, closing, circuit-breaker resumption), `_bid_qty` carries phantom quantity at the executed levels. This silently corrupts: FOK pre-checks (`_available_qty`), `depth_snapshot()` metrics, and — worst — the *next* `compute_equilibrium()`, which reads `_bid_qty`/`_ask_qty` directly (`auction.py:56-57`). Corruption compounds across auctions.
- **Fix:** In the uncross path, deduct the fill quantity from both sides' level indexes (e.g., add an `both_resting: bool` parameter to `_apply_fill`, or perform the aggressor-side deduction inside `execute_uncross`). Add an invariant test: after uncross, `sum(_bid_qty.values()) == sum(visible qty of resting bids)`.

### C3 — SMP-cancelled aggressors are rested on the book

- **Where:** `order_book.py:779-791` (`_sweep` SMP handling), `order_book.py:633-634` (`_match_limit`), `order_book.py:665-667` (`_match_iceberg`).
- **What:** When SMP fires with `CANCEL_AGGRESSOR` or `CANCEL_BOTH`, `_sweep` sets `aggressor.status = CANCELLED` and returns. `_match_limit` then unconditionally executes `if order.remaining_qty > 0: self._rest(order)` — resting the *cancelled* order. `_rest` adds its quantity to `_bid_qty`/`_ask_qty` and re-registers it in `_order_index`/`_entry_index`.
- **Impact:** `_peek` will later pop the dead entry from the heap *without* deducting the level index (`order_book.py:1016-1032` performs no index maintenance), so the phantom quantity is permanent. Same corruption vector as C2: FOK, depth, auction equilibrium. The cancelled order also reappears in `_order_index`.
- **Fix:** In `_match_limit` / `_match_iceberg`, guard the rest: `if order.remaining_qty > 0 and order.status not in _DEAD_STATUSES`. Add SMP unit tests that assert the qty index afterwards.

### C4 — Partial fills on IOC / MARKET / SMP-cancelled orders are never reported to the participant

- **Where:** `order_book.py:616-619` (`_match_market`), `685-690` (`_match_ioc`); `main.py:834-949` (event publication loop).
- **What:** `events` holds repeated references to the *same* mutable `Order`. An IOC that partially fills is appended once per fill with status `PARTIAL`, then its status is mutated to `CANCELLED` and appended again. At publish time the loop reads the object's **final** status for every occurrence — so all occurrences take the `CANCELLED` branch. The participant receives `order.cancelled` and **no `order.fill` at all**, despite real executions. The same happens for a partially filled MARKET order (remainder discarded → status `CANCELLED`) and for an aggressor partially filled before SMP `CANCEL_AGGRESSOR`. Additionally, `_match_market` sets `CANCELLED` on an unfilled remainder **without appending any event** (`order_book.py:616-619`), so a completely unfilled market order gets a positive ACK followed by silence.
- **Impact:** Trades are published globally and positions are updated, but the owning gateway's private fill notification (and its drop-copy record) is lost. Any participant-side blotter, risk system, or bot that keys off `order.fill` is now wrong. This is the most user-visible correctness defect in the engine.
- **Fix (tactical):** Publish fills before terminal-status handling, or track `(order_id, cumulative_qty)` in the event loop. **Fix (structural, recommended):** see A2 — have `_apply_fill` emit immutable fill records `(order_id, gateway_id, qty, price, remaining_after, liquidity_flag)` so publication cannot be affected by later mutation.

### C5 — OCO registration race: an immediately-filled leg orphans its sibling

- **Where:** `main.py:2811-2884` (`_handle_oco_order` leg loop), `main.py:2923-2955` (`_check_oco_after_event`).
- **What:** Legs are posted sequentially. If leg 1 fully fills on entry, `_check_oco_after_event` runs immediately: it tries to cancel leg 2 (a no-op — leg 2 is not on the book yet), then **removes `_order_symbol[leg2]`, `_order_to_oco[leg2]`, and the whole `_oco_groups[oco_id]` entry**. The loop then proceeds to post leg 2 anyway.
- **Impact:** Leg 2 rests with no OCO linkage (both legs can execute — the OCO invariant is broken) *and* is no longer cancellable through the API, because `_handle_cancel` routes via `_order_symbol`, which was popped. The order is stranded until fill or EOD.
- **Fix:** Register/post both legs first, then run the OCO fill-check pass; or in `_check_oco_after_event`, treat a sibling that is not yet on the book as "pending-cancel" and suppress its posting. Add a test: OCO where leg 1 is immediately marketable.

### C6 — Trailing stops crash in any no-match mode; GTC trailing stops brick engine startup

- **Where:** `order_book.py:191-202` (`process()` match=False branch), `order_book.py:976-983` (`_rest` asserts `price is not None`), `main.py:534-550` (`_restore_gtc`).
- **What:** The `match=False` branch handles MARKET/FOK/IOC (reject) and STOP/STOP_LIMIT (`_add_stop`), then routes *everything else* to `_rest()`. `TRAILING_STOP` orders have `price=None`, so `_rest` raises `AssertionError`.
- **Impact:** Two distinct failure paths:
  1. A trailing stop submitted during a halt or auction phase (both set `do_match=False` in `_handle_new_order`) is ACKed `accepted=True`, then the exception is swallowed by the blanket handler in `run()` (`main.py:3261-3267`). The order silently vanishes.
  2. A **GTC** trailing stop is persisted at shutdown (it sits in `_order_index` with status NEW, so `resting_orders()` includes it) and `_restore_gtc` replays it with `match=False` — with **no** exception guard. The engine crashes on startup and cannot start until the JSON file is hand-edited.
- **Fix:** Add `TRAILING_STOP → _add_trailing_stop` to the `match=False` branch. Wrap per-order restore in try/except with a skip-and-log path. Add tests for both paths.

### C7 — Passive iceberg fills bypass the displayed slice: queue jumping + index corruption

*(Found after the initial review by the randomized invariant suite, `tests/test_book_invariants_random_ops.py`, within 10 seeds of plain continuous flow.)*

- **Where:** `order_book.py:793` (`_sweep`: `fill_qty = min(aggressor.remaining_qty, best.remaining_qty)`) interacting with `_apply_fill`'s iceberg branch (`order_book.py:930-945`).
- **What:** For a **passive** iceberg, the sweep sizes the fill from `remaining_qty` — the full hidden quantity — not from `displayed_qty`. Two consequences:
  1. **Fairness:** an aggressor for 50 against an iceberg showing 10 executes all 50 against the iceberg in a single fill. A plain limit order resting at the *same price with earlier priority than any refreshed peak* is skipped entirely. Standard iceberg semantics (and this code's own replenish logic, which re-timestamps the fresh peak to the back of the queue) require the aggressor to take the 10-lot peak, then move to the next order at the level.
  2. **Index corruption:** `_apply_fill` deducts `fill_qty` (50) from a level index to which the iceberg only ever contributed `displayed_qty` (10). At a shared price level the difference is silently taken from *other orders'* visible quantity (observed: index 170 vs. true 210). When the iceberg is alone at the level, the clamp-to-zero in `_deduct_qty_index` masks the damage — which is why targeted iceberg tests never saw it.
- **Impact:** Ordinary continuous trading with icebergs — no SMP, no auctions — corrupts the qty index (FOK pre-checks, depth, auction equilibrium) and violates price-time priority for every same-level order behind an iceberg.
- **Fix:** In `_sweep`, cap the per-iteration fill against a passive iceberg at `best.displayed_qty`; let the existing replenish-and-re-queue logic in `_apply_fill` handle the rest (the loop naturally returns to the level in correct priority order). Regression: `TestC7IcebergDisplayedSliceSemantics` plus the `with_icebergs` tier of the randomized suite.

---

## 3. High-severity findings

### H1 — Time priority is derived from client-supplied timestamps

- **Where:** `models/order.py:233` (`from_dict` keeps `d["timestamp"]`), `order_book.py:984-991` (heap key `(±price, timestamp)`).
- **What:** The heap key's time component is whatever timestamp arrived in the `order.new` payload — i.e., set by the gateway's clock, not by engine arrival.
- **Impact:** Queue position depends on cross-host clock skew, and a participant can *spoof an older timestamp to jump the FIFO queue* at a price level. In any matching engine — educational or not — time priority must be assigned by the sequencer.
- **Fix:** Maintain a monotonically increasing per-engine arrival sequence number, stamp it in `_handle_new_order`, and key heaps on `(±price, arrival_seq)`. This also fixes M10 (tie-breaking) for free and makes replay deterministic.

### H2 — Amend never re-attempts a match; also bypasses collar and halt checks

- **Where:** `order_book.py:280-404` (`amend_order`), `main.py:3016-3102` (`_handle_amend`).
- **What:** A price amend re-inserts the order at its new price but never sweeps. Amending a bid up through the best ask leaves the book *crossed* until the next unrelated order arrives — trades that should print, don't; and the market data shows bid ≥ ask. Separately, `_handle_amend` performs no collar validation on the new price (fat-finger protection is bypassed by amending instead of entering) and no halted-symbol / session-state check.
- **Fix:** Treat priority-losing amends as cancel/replace: after re-insert, if the order is marketable, run the same sweep as a new order (or literally cancel + resubmit internally — simplest and matches real exchange semantics). Apply `validate_collar` and the halt check in `_handle_amend`.

### H3 — Position ledger only sees fills from the new-order and uncross paths

- **Where:** `_update_position` calls exist only at `main.py:951-969` (`_handle_new_order`) and `main.py:2562-2625` (`_run_uncross`). No calls in `_handle_quote_new` (1707-1733), `_load_config` quote seeding (429-455), `_accept_combo` (2276-2277), `_handle_oco_order` (2878-2879).
- **Impact:** Any trade whose *aggressing* flow entered as a quote, combo child, or OCO leg updates only... nothing at all — both counterparties' positions are skipped for those trades. `system.position_request` (used by bots to resync inventory) returns wrong data as soon as MM quotes trade.
- **Fix:** Route *all* trade publication through one function that publishes the trade **and** updates both positions (extend `_publish_trade`). This is the same consolidation as A1 below.

### H4 — Drop copy misses quote, combo, OCO and auction fills (and all cancels)

- **Where:** `main.py:896-914` — the only `_drop_copy.publish` call sits inside `_handle_new_order`'s fill loop.
- **Impact:** The feed documented as "for clearing/risk systems" (`drop_copy.py` module docstring) is structurally incomplete: an MM whose quote is hit never sees the fill on drop copy; auction executions never appear; no cancel/expire events are ever published despite the docstring claiming "fills, cancels, rejects."
- **Fix:** Same consolidation as H3 — a single event-publication path that also feeds drop copy.

### H5 — Duplicate fill messages in the quote, combo, OCO and uncross paths

- **Where:** `main.py:1709-1727`, `2241-2274`, `2843-2876`, `2546-2560`.
- **What:** `_handle_new_order` deduplicates fill events with a seen-set (`main.py:834-853`, with a comment explaining exactly why it is needed). The other four fill-publishing loops have no such guard. An order that sweeps k price levels appears k times in `events`; each occurrence publishes a fill message carrying the *final cumulative* quantities — so subscribers see k identical "total fill" messages and overcount by up to k×.
- **Fix:** Consolidation (A1). Any interim fix should copy the seen-set into all five loops — but that is exactly the duplication that caused this.

### H6 — Fill messages report the wrong price for multi-level sweeps

- **Where:** `main.py:817-821` (`_fill_px` computed once, after `process()` returns), used at `main.py:869` and in drop copy at `900-906`.
- **What:** Every fill message from one `process()` call carries `book.last_trade_price` — the *last* level swept. A passive sell resting at 100.00, filled while the aggressor walked up to 100.50, is told it filled at 100.50. The aggressor is told its whole quantity filled at the last price rather than per-level prices or VWAP.
- **Impact:** Participant-side P&L and average-cost tracking are wrong whenever an order sweeps more than one level. (The `trade.executed` public feed has correct per-trade prices; the private fill feed disagrees with it.)
- **Fix:** Emit per-fill event records with the actual fill price (see A2). If one message per order is desired, report VWAP and cumulative quantity computed from the trade records.

### H7 — Unbounded growth: filled/cancelled orders are never purged from indexes

- **Where:** `order_book.py:874-955` (`_apply_fill` never pops `_order_index`/`_entry_index` for FILLED orders), `240-278` (`cancel_order` leaves both maps populated), `main.py:744-745` (`_order_symbol` only popped in cancel paths, never on fill), `main.py:2283` (`_combos` never pruned of terminal combos).
- **Impact:** Memory grows linearly with lifetime order count, and — worse — `resting_orders()` iterates **all orders ever seen** (`order_book.py:406-412`). That method is called by `orders_request`, `quote_bootstrap_request`, `kill_switch`, `gateway_disconnect`, `_expire_tif`, and `_shutdown`, so handler latency degrades throughout the session. `get_order()` also returns long-dead orders.
- **Fix:** Pop `_order_index`, `_entry_index`, and notify the engine to pop `_order_symbol` when an order reaches a terminal state. If lazy heap deletion is retained, `_entry_index` cleanup belongs where `entry.valid` is set to False.

### H8 — FOK is neither reliably fill-checked nor atomic

- **Where:** `order_book.py:636-653` (`_match_fok`), `852-872` (`_available_qty`).
- **What:** Two defects:
  1. `_available_qty` sums the *visible* level index, so resting iceberg **hidden** quantity is invisible → spurious FOK rejects even when the book can fill the order (the sweep would have replenished peaks).
  2. The pre-check counts same-gateway resting quantity that SMP will subsequently skip/cancel. The sweep can then run out of liquidity, leaving the FOK order **partially filled**, status `PARTIAL`, neither resting nor cancelled — a limbo state that violates fill-or-kill by definition.
- **Fix:** Make the pre-check walk actual orders (respecting hidden qty and excluding SMP-conflicting counterparties), or run the sweep tentatively and roll back — with the current mutable-in-place design, rollback is not possible, which is another argument for A2. At minimum, after the sweep: if `remaining_qty > 0`, cancel the remainder and emit the event.

### H9 — Quotes and combo children bypass session and matching gates

- **Where:** `_handle_quote_new` (`main.py:1529-1747`) has no `accepts_orders` / `is_matching_enabled` check; `_accept_combo` calls `book.process(child)` with default `match=True` (`main.py:2238-2239`) regardless of session state or per-symbol halt; `_load_config` seeds quotes with `match=True` even when the engine starts in `CLOSED` (`main.py:430`).
- **Impact:** A market maker can quote — and *trade* — during auction phases and while the market is `CLOSED`; combo legs match during auction collection while ordinary limit orders are queued. This breaks the fairness premise of the auction (all interest crosses at one equilibrium price).
- **Fix:** Compute `do_match` once per inbound flow from session state + halt map, and pass it to every `book.process` call; reject quotes when `not accepts_orders(...)`.

---

## 4. Medium-severity findings

**M1 — Unfilled MARKET remainder cancelled with no event.** `order_book.py:616-619` sets `CANCELLED` without `events.append`, so (independent of C4) a totally unfilled market order produces a positive ACK and then nothing. Emit the cancel event and let the engine publish it.

**M2 — Stops never trigger on placement.** `_check_stops` only runs after a trade (`order_book.py:226-232`). A stop entered with `stop_price` already breached by `last_trade_price` sits dormant until the next unrelated trade. Real venues either reject ("would trigger immediately") or trigger immediately; either is fine — pick one and document it. Check triggerability in `_add_stop` / `_add_trailing_stop`.

**M3 — Crossed books are never uncrossed after restore or non-auction resume.** `_restore_gtc` deliberately rests without matching (good reasoning in the comment, `main.py:546-549`) but never uncrosses afterwards, so two crossed GTC orders leave a crossed book at startup. Same after a circuit-breaker resume with a non-AUCTION resumption mode. Run `_run_uncross(symbol)` after restore and after every resume.

**M4 — Startup snapshot published before tick registration.** `run()` calls `_restore_gtc()` (which publishes book snapshots, `main.py:556-559`) *before* `_load_config()` registers `tick_decimals` (`main.py:336-337`). For a 4-decimal symbol, those first snapshots show prices 100× off. Reorder: register tick decimals first, or defer the snapshot publish.

**M5 — `ComboType.AON` is not enforced.** Combo legs are posted as independent orders (`main.py:2216-2281`); nothing prevents leg 1 filling while leg 2 never does — the combo just becomes `PARTIALLY_MATCHED`. For an all-or-none instrument this is an unimplemented semantic, not a bug in the small; at minimum rename/document, ideally implement contingent execution (only execute when all legs are simultaneously marketable).

**M6 — Unbounded stop-cascade recursion.** Triggered stops are re-processed via recursive `self.process()` (`order_book.py:229-232`). A long cascade (stop → trade → stop → …) recurses once per link and can hit Python's recursion limit. Convert to an explicit work queue (`while triggered: ...`).

**M7 — No boundary validation of order payloads.** `_handle_new_order` never validates `quantity > 0`, `price > 0`/present for LIMIT, `visible_qty` present and `≤ quantity` for ICEBERG. Bad values ACK positive and then die on asserts/`TypeError` inside the book (swallowed by the blanket handler — order silently lost) or, worse, corrupt the qty index with negative quantities. Add an explicit validation function that rejects with a reasoned NACK before the ACK is sent.

**M8 — Blanket exception handling leaves half-applied state.** `run()`'s `except Exception` (`main.py:3261-3267`) prints and continues. Because handlers publish the ACK *before* `book.process()` (`main.py:753-813`), an exception mid-handler leaves the client believing the order is live. Consider: validate first, ACK after successful book application (or send an explicit reject on exception), and log with stack trace, not `print(exc)`.

**M9 — Monotonic clock bypassed on the hot path.** `clock.now_ns()` guarantees strict monotonicity; `_handle_new_order` deliberately uses raw `time.time_ns` (`main.py:115-118, 747-751`). Wall-clock regression (NTP step) can produce out-of-order timestamps used in heap keys and iceberg re-queue stamps. If H1's arrival-sequence fix is adopted, timestamps become informational only and this degrades to cosmetic; otherwise use a monotonic source.

**M10 — No tie-break beyond timestamp in heap keys.** Two entries with equal `(price, timestamp)` compare equal; `heapq` order is then arbitrary and non-deterministic across runs. Subsumed by the arrival-sequence fix (H1).

**M11 — Monetary aggregates in float.** `daily_value` (`order_book.py:146, 909`) and the avg-cost ledger (`main.py:190-191`) accumulate floats. The codebase's own tick discipline says internal money should be int ticks; accumulate `price_ticks * qty` and convert at the boundary.

**M12 — Amend quantity taken raw from JSON.** `payload.get("qty")` is passed unconverted (`main.py:3020, 3071`); a float (or string) propagates into `quantity`/`remaining_qty`. Coerce and validate like prices are.

**M13 — Drop copy `liquidity_flag` is always MAKER.** `main.py:908-912` labels every fill `MAKER`/`MAKER_QUOTE`, including the aggressor's. Derive taker/maker from `evt is order` (or from the event record's aggressor flag after A2).

**M14 — No day-boundary reset.** `daily_qty/value/trades` reset only on process restart; a multi-day run (CLOSED → PRE_OPEN) reports cumulative "daily" volume, and DAY orders are only expired at *shutdown* (`main.py:3112-3131`), not at session CLOSED. Expire DAY orders and reset daily counters on the transition into CLOSED.

---

## 5. Low-severity findings

**L1 — Five divergent copies of event-publication logic.** `_handle_new_order`, `_handle_quote_new`, `_accept_combo`, `_handle_oco_order`, `_run_uncross` each reimplement the fill/cancel/reject publish loop with different feature sets (dedup: only #1; drop copy: only #1; positions: #1 and #5; combo/OCO hooks: varies). H3–H6 are direct consequences. One `publish_order_events(book, order, trades, events)` is the fix.

**L2 — `print()` for operational logging.** `main.py` prints to stdout on the hot path (each order in verbose mode, every halt, every session change) while `persistence.py` uses `logging`. Standardize on `logging` with levels; stdout writes block the event loop.

**L3 — Hand-rolled order serialization in `_handle_orders_request`** (`main.py:1264-1300`) duplicates `Order.to_dict` plus tick conversion. One helper (`order_to_display_dict`) prevents field drift.

**L4 — PERF comment noise.** Roughly a quarter of `order_book.py`/`main.py` line count is nanosecond-level rationale (LOAD_FAST vs LOAD_ATTR, topic-byte caches). Meanwhile macro costs dominate: JSON per message, duplicate publications (H5), O(all-orders) scans (H7), stdout printing. Move the micro-opt rationale to a `docs-design/perf-notes.md` with the benchmark that justified each; keep code comments for *invariants*, not bytecode trivia. As written, the comments actively slow a maintainer down.

**L5 — Function-local imports** (`validate_collar` at `main.py:689`, `CircuitBreakerState` at `main.py:511`, `now_ns` inside `drop_copy.publish`). Import at module top; the cycle they presumably avoid should be broken by moving shared types instead.

**L6 — `Any`-typed engine state.** `_collars: dict[str, Any]`, `_circuit_breakers: dict[str, Any]`, `_drop_copy: Any` (`main.py:153-157`). Type them properly; the `Any`s hide exactly the misuse categories this review found.

**L7 — `# type: ignore` density in `order_book.py`.** ~20 ignores, nearly all from `Order` being one god-record with `Optional` everything. A validated construction path per order type (or `assert`-narrowing helpers) removes them.

**L8 — `_cancel_order_by_id` drops `client_tag`** (`main.py:1365`) while `_handle_cancel` includes it (`main.py:2995-2998`); subscribers correlating on `client_tag` miss quote/combo-driven cancels.

**L9 — Auction fills always mark the buyer as aggressor.** `execute_uncross` passes the bid as aggressor, so `last_buy_price` updates and `last_sell_price` never does during auctions, and `trade.aggressor_side` is always BUY. Auction prints should carry a neutral aggressor flag.

**L10 — `depth_snapshot.cost_to_move` is a mislabeled placeholder** (`order_book.py:491`, `= bid_depth "for now"`). Either compute it or drop the field; downstream consumers will treat it as real.

**L11 — `config_loader.py` is ~1,000 lines of hand-written validation.** Every field repeats the fetch/type-check/raise pattern. A `pydantic` (or dataclass + small validator helper) schema would cut it to ~200 lines and produce better error messages for the students configuring it.

**L12 — No transport authentication.** Any local process can `connect` to PULL :5555, send `system.gateway_connect` for a configured ADMIN id, and then issue `risk.kill_switch` / halts. Acceptable for a teaching system on localhost — but document it explicitly as a non-goal, and consider a shared-secret field in `gateway_connect` as a cheap improvement.

Also noted, acceptable as documented behavior but worth a line in the docs: the double-ACK contract (accepted=True precedes a possible accepted=False for MARKET/FOK/IOC, `main.py:753-760`) is unusual relative to the conventional NEW → REJECT lifecycle and every client must implement it correctly; and ZMQ PUB slow-joiner semantics mean a gateway can miss its own first ACKs after connecting (the 50 ms sleep at `main.py:266` is a heuristic, not a guarantee).

---

## 6. Performance review

The single-threaded, single-book-sweep design is sound for the stated educational TPS targets. The findings below are ordered by expected real-world impact — note that none of them are the nanosecond items the code comments focus on.

**P1 — O(total-orders-ever) scans (consequence of H7).** `resting_orders()` iterates every order since startup. Called from at least six handlers, including `orders_request` which bots may poll. Fix H7 and this disappears; the method becomes O(resting).

**P2 — `compute_equilibrium` is O(P²).** For each candidate price it linearly rescans `bid_prices` and `ask_prices` (`auction.py:85-107`) even though cumulative arrays were just built. With cumulative arrays + `bisect` over the sorted price lists it is O(P log P). P is small in classroom books; it matters if a symbol accumulates hundreds of levels during a halt.

**P3 — One inbound message per poll-loop iteration.** `run()` does `poll → recv one → flush snapshots → flush breakers` (`main.py:3196-3271`). Under burst load, per-message overhead includes the two flush calls and a full poll. Drain the socket with `recv_multipart(zmq.NOBLOCK)` in a bounded inner loop, then flush once.

**P4 — Heap garbage from lazy deletion.** Cancel/replace-heavy MM flow pushes a new entry per quote and leaves the old invalidated entry in the heap until it surfaces at the top. Entries at away-from-market prices can linger for the whole session (memory + comparison overhead in every sift). Consider periodic compaction (`heap = [e for e in heap if e.valid]; heapify`) when `invalid_count > len/2` — or the structural fix in §7.

**P5 — Publication overhead dominates matching.** Every trade produces: trade JSON, ≥2 fill JSONs, position updates, dirty-mark; every snapshot re-aggregates the whole book (`snapshot()` is O(heap incl. stale entries)). This is fine at 0.5 s throttle, but if TPS tests are a goal, cache per-level aggregates (which the level index already almost provides) instead of rescanning heap entries.

**P6 — Micro-optimizations: keep, but stop expanding.** The `__slots__`, enum lookup maps, topic-byte caches, and single-timestamp-per-order changes are all legitimate and measured. However, several of them duplicate logic to shave ~100 ns while the same handler performs duplicate JSON publications costing tens of µs (H5). Adopt a rule: no further micro-opts without a profile showing the target ≥1% of wall time.

---

## 7. Data-structure assessment

**Current design:** per side, a `heapq` of `_HeapEntry(key=(±price, ts))` with lazy deletion, plus `_entry_index` (order-id → entry) and `_bid_qty`/`_ask_qty` (price → visible qty), plus `_order_index`, plus the engine-level `_order_symbol`. Stops in two heaps (good choice), trailing stops in a scanned list (fine at expected counts).

**Assessment:** a heap-of-orders is a defensible teaching structure, and the lazy-deletion trick is implemented correctly *in the happy path*. But the review found four independent bugs (C2, C3, and the two H7/H8 corruption vectors) that are all failures to keep **four hand-synchronized structures** consistent, and the amend/iceberg/SMP code is dominated by index bookkeeping rather than matching logic.

**Recommendation: migrate to a price-level book.**

```
levels:  SortedDict[int, Level]        # sortedcontainers; bids use negated key or reverse view
Level:   deque[Order] + visible_qty:int + total_qty:int
index:   dict[order_id, (price, Order)]
```

Properties that remove entire bug classes:

- Level quantity is *owned by the level*, not by a parallel dict — C2/C3-style phantom-qty corruption becomes impossible by construction.
- FIFO within a level is explicit (`deque`), so time priority needs no timestamps at all — arrival order *is* the queue (fixes H1/M10 naturally when combined with an arrival-seq).
- Amend-preserving-priority = edit in place; amend-losing-priority = remove + append; iceberg replenish = rotate to tail. No duplicate heap entries, no `valid` flags, no compaction.
- Best bid/ask is `levels.peekitem(0)` — O(1) amortized; `snapshot()` and `depth_snapshot()` read levels directly.
- `compute_equilibrium` iterates levels directly with correct data.

`sortedcontainers.SortedDict` is pure Python, battle-tested, and O(log n) for inserts/deletes with very low constants. The migration is well-contained: `OrderBook`'s public surface (`process`, `cancel_order`, `amend_order`, `snapshot`, `resting_orders`) can stay identical, and the existing test suite (37 tests in `test_order_book_coverage.py` plus the engine suites and `tools/verify_matching.sh`) is the safety net.

If the team prefers to keep the heap design, then at minimum: (a) make `_deduct_qty_index`/`_add_qty_index` the *only* code paths that touch the level dicts, called from a small set of audited sites; (b) add a debug-mode invariant checker (`sum(level qty) == sum(resting visible qty)`) run in tests and optionally every N orders.

---

## 8. Architecture and organization

**A1 — Consolidate event publication (fixes H3, H4, H5, H6, M13, L1, L8).** One function owns: fill/cancel/reject/expire publication, per-event dedup, drop copy, position updates, combo/OCO hooks, dirty-marking. Every handler (`new_order`, `quote_new`, `accept_combo`, `oco_order`, `uncross`, seeding) calls it. This is the single highest-leverage refactor in the codebase.

**A2 — Make `OrderBook` emit immutable event records (fixes C4, H6, and enables H8).** Replace `events: list[Order]` with small frozen records:

```python
@dataclass(frozen=True, slots=True)
class FillEvent:   order_id; gateway_id; qty; price; remaining_after; is_aggressor; ...
@dataclass(frozen=True, slots=True)
class OrderEvent:  order_id; gateway_id; kind: Literal["ACK","CANCELLED","REJECTED","EXPIRED"]; reason; ...
```

Publication then cannot be corrupted by later mutation of the order, per-fill prices are exact, dedup logic disappears, and a future FOK rollback becomes possible. This is the second root-cause fix and pairs naturally with A1.

**A3 — Split `main.py` (3,296 lines).** `Engine` currently owns transport, dispatch, order lifecycle, quotes, combos, OCO, auctions, risk, positions, sessions, admin, and persistence orchestration. Suggested decomposition, keeping `Engine` as a thin composition root:

| Module | Contents (approx. current lines) |
|---|---|
| `engine/dispatch.py` | topic → handler table (replaces the 28-branch elif chain, `main.py:3204-3260`) |
| `engine/publisher.py` | A1's event publication + topic caches + drop copy |
| `engine/positions.py` | `_update_position`, position snapshot handler |
| `engine/quotes.py` | quote new/cancel/bootstrap, refresh policy, MM obligation checks |
| `engine/combos.py`, `engine/oco.py` | current combo/OCO handler blocks |
| `engine/risk.py` | collar wiring, circuit-breaker flush, halt/resume/kill handlers |
| `engine/sessions.py` | transition handling, `_expire_tif`, uncross orchestration |

**A4 — Boundary validation module.** A single `validate_new_order(payload) -> Order | Reject` covering M7/M12 (types, ranges, per-order-type required fields, duplicate order-id detection). Note the engine currently accepts a *duplicate order id* silently (`_order_symbol[order.id] = ...` overwrites) — replayed gateway messages double-execute.

**A5 — Sequence-number the public feed.** Drop copy has `seq`; the main PUB feed does not. Subscribers cannot detect gaps in `trade.executed` or their private fill stream. A per-engine monotone sequence on every published message (plus the arrival-seq from H1) makes the whole system replayable and verifiable — and `tools/compare_results.py` / `verify_matching.sh` can then assert determinism end-to-end.

**A6 — Clock discipline.** One rule: engine-assigned arrival sequence for priority, `now_ns()` for event timestamps, wall clock never used for ordering. Today three sources are mixed (gateway timestamps, `now_ns()`, raw `time.time_ns`).

---

## 9. Domain notes (educational-bar, brief)

These are not defects at the stated bar, but each is a small change that would teach the *right* market-structure lesson:

- **Auction transparency:** during auction phases, publish an indicative equilibrium (price/qty/imbalance) on each book change — real venues publish IOP/imbalance feeds, and it makes the auction observable for students. `compute_equilibrium` is already cheap enough to call on demand.
- **Auction tie-breaking:** when multiple prices maximize executable qty with equal surplus, the code picks the lowest (`auction.py:111`). Real venues add tie-breaks (minimum distance to reference price, market pressure). A comment or a reference-price tie-break would be pedagogically valuable.
- **Market orders in auctions** are rejected outright; real opening auctions accept them with highest priority. Worth a TODO.
- **Halt semantics mid-sweep:** a circuit breaker fires via `_publish_trade` *during* a sweep but the sweep completes anyway; real venues stop the sweep. Fine to keep — document it.
- **Stop triggers off last trade only** (not bid/ask or protected quotes) — a standard simplification; document it where stops are described.
- **`_restore_gtc` resets PARTIAL to NEW** (`main.py:544`), losing the partially-filled state distinction across restarts.

---

## 10. Testing and verification recommendations

The repo's test volume is a real asset (≈2,500 tests; engine-specific suites in `test_order_book_coverage.py`, `test_engine_handlers*.py`, `test_auction.py`, `test_negative_engine_state.py`, plus the `tools/` replay/verify harness).

> **Regression suites for C1–C7, H1–H9, and M1–M14:** `tests/test_engine_review_criticals.py` (13 tests), `tests/test_engine_review_highs.py` (15 tests), and `tests/test_engine_review_mediums.py` (15 tests; M12 lives in `test_engine_adversarial.py`) encode the correct expected behaviour for every critical, high, and medium finding — all currently failing by design. Each fix must turn its tests green; keep them as permanent coverage.
>
> **Systemic test foundation** (added after the review; ~190 tests, expected-failures each mapped to a finding):
>
> - `tests/engine_harness.py` — shared engine fixtures (replaces the per-file `_FakeSock`/`_make_engine` copies).
> - `tests/engine_invariants.py` — `assert_book_invariants()` (qty-index consistency, never-crossed, per-order sanity, entry-index agreement, optional terminal-purge hygiene) and `assert_qty_conservation()`. Call at the end of any book-level test.
> - `tests/test_book_invariants_random_ops.py` — seeded random operation sequences with invariants checked after every step, in four tiers: plain flow (green — proves the harness), +icebergs (red → C7, which this suite discovered), +SMP (red → C3), +auctions (red → C2).
> - `tests/test_engine_cross_flow_guarantees.py` — every guarantee (fills published, no duplicates, positions, drop copy, session gating) parametrized over every flow (order, quote, OCO, combo, stop-triggered, auction). New entry paths automatically inherit all guarantees.
> - `tests/test_order_type_session_matrix.py` — all 8 order types × {continuous, pre-open, halted}: every cell must end in a defined, notified state (catches C6, M1 and any future forgotten branch).
> - `tests/test_engine_adversarial.py` — valid-but-hostile inputs: duplicate order ids, zero qty, iceberg visible>qty, float amend qty (A4, M7, M12).
> - `tests/test_persistence_roundtrips.py` — save→load→equality for every GTC order variant and combos (green guards; the C1 engine-level round trip lives in the criticals suite).
> - `tests/test_engine_determinism.py` — identical input scripts through two engines must publish identical (normalized) streams (green guard for phase-4 and the §7 migration).

Gaps this review exposed — each Critical/High above should land with a regression test, and additionally:

1. **Invariant property tests** (hypothesis or hand-rolled): after any random sequence of new/cancel/amend/quote/auction operations — `sum(_bid_qty.values()) == sum(visible qty of live resting bids)`; no live order in a dead map; every trade's qty deducted exactly once per side. These would have caught C2, C3, H7 mechanically.
2. **Notification-completeness test:** for every trade published, both gateways received a fill message whose per-order cumulative qty and VWAP match the trade stream (catches C4, H5, H6).
3. **Restart round-trip test:** trade → shutdown → restart → assert collar/CB references and book stats equal pre-shutdown values (catches C1), and restore a GTC trailing stop (catches C6).
4. **Determinism replay:** run the same order file twice through `tools/replay_to_engine.py` and diff full output streams (catches H1/M10 once arrival-seq lands).
5. **Cross-flow position reconciliation:** positions derived from the `trade.executed` stream must equal `system.position_request` output after mixed order/quote/combo/OCO activity (catches H3).

---

## 11. Suggested remediation order

| Phase | Items | Rationale |
|---|---|---|
| 1 — Stop the bleeding (small, surgical) | C1, C3, C6, M1, M4, H8-minimum (cancel FOK remainder) | Each is a ≤20-line fix with a clear regression test; C1/C6 can take the system down |
| 2 — Event pipeline refactor | A1 + A2, closing C4, H3, H4, H5, H6, M13 | One refactor closes six findings; do before adding any new order types |
| 3 — Book integrity | C2, H7, invariant checker (§10.1); decide heap-vs-price-level (§7) | If migrating to price-level book, C2/H7 fixes fold into it |
| 4 — Fairness & determinism | H1, M9, M10, A5, A6 | Arrival sequence + feed sequencing; enables determinism replay |
| 5 — Gates & validation | H2, H9, M7, M12, A4 | Amend rematch/collar, session gating for quotes/combos, boundary validation |
| 6 — Hygiene | H7 pruning completion, M6, M8, M11, M14, L-items, A3 split, P2/P3/P4 | Structure and performance polish once behavior is correct |

---

*End of review. Findings C1–C6 were each re-verified against the source before publication; line references are to the current working tree.*


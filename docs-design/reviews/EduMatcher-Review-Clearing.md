# EduMatcher Clearing Module — Code Review

**Scope:** `src/edumatcher/clearing/` (main.py, ledger.py, store.py, cli.py) plus the legacy `src/edumatcher/clearing_v1/` still shipped as `pm-clearing-v1`, reviewed against the *actual* engine-side message contracts in `engine/main.py`, `models/message.py`, `models/trade.py`, and `engine/drop_copy.py`.
**Special focus (as requested):** the contact surface with the engine, and assumptions that are no longer valid.
**Review bar:** Educational-but-correct, consistent with `EduMatcher-Engine-Review.md`. Finding IDs use the `CL-` prefix (CL-C critical, CL-H high, CL-M medium, CL-L low) so they can be tracked alongside the engine findings.

---

## 1. Executive summary

The v2 clearing design is fundamentally sound and in several places better engineered than its upstream: WAL-mode SQLite with a genuinely atomic flush transaction (`store.flush_batch`), an idempotent raw-event archive, incremental daily UPSERTs that survive restarts, a correct position/P&L transition ledger (flat→long/short, add, partial close, cross-zero — `ledger.py:90-154` mirrors the engine's `_update_position` and handles the same cases correctly), a whitelisted ORDER-BY CLI with no injection surface, and a `reconcile` verb that shows the right instincts.

The serious problems are almost all at the **engine boundary** — and three of the four critical findings are *contract drift*: clearing was written against a version of the engine that no longer exists.

| # | Assumption baked into clearing | Reality today |
|---|---|---|
| CL-C1 | Trade IDs are globally unique (uuid4) → safe as `PRIMARY KEY` dedup key | Engine PERF #2 switched to a per-process counter: IDs repeat on every engine restart |
| CL-C2 | `system.eod` books carry `last_trade_price` / `best_bid` / `best_ask` | Engine sends `book.snapshot()` dicts: keys are `last_price` (display float), `bids`, `asks` |
| CL-C3 | `system.gateway_connect` / `_disconnect` are broadcast on the PUB feed | They are gateway→engine **PULL** topics; the engine broadcasts `system.gateway_auth.{id}` instead |
| CL-H1 | The trade feed is reliable | ZMQ PUB/SUB drops on slow-join and disconnect; `trade.executed` carries no sequence number |

Each drifted contract fails **silently** — empty tables, dead code paths, dropped archive rows — which is why the module's substantial test suite (`test_clearing_ledger/store/main/cli`) never noticed: those tests feed clearing hand-built payloads shaped like clearing's *expectations*, not like the engine's *output*. Section 8 proposes contract tests that generate the payloads with the engine's own `make_*_msg` builders so writer and reader can never drift apart unnoticed again.

| Severity | Count | Theme |
|---|---|---|
| Critical | 4 | ID-collision data loss, dead EOD path, dead session tracking, restart corrupts positions |
| High | 4 | Lossy transport, cross-scale sums, avg_cost display bug, one-sided reconcile |
| Medium | 9 | Dedup doesn't gate the ledger, thread race, UTC day bucketing, heuristics, v1 rot |
| Low | 7 | Dead DDL, stale comments, cosmetic ordering |

---

## 2. The engine contact surface, mapped

What clearing consumes, and the verified state of each contract:

| Topic (SUB on `ENGINE_PUB_ADDR` :5556) | Engine producer | Contract status |
|---|---|---|
| `trade.executed` | `engine/main.py:1378-1400` (`_publish_trade` — called from **every** flow: order, quote, combo, OCO, stop, auction) | **Working, but drifted in two fields** (id: CL-C1; no seq no: CL-H1). Payload: `id` = counter string, `price` = display float, `tick_decimals`, `timestamp` = float seconds. Clearing's re-normalization to int ticks / ns (`main.py:87-120`) handles the units correctly. |
| `system.eod` | `engine/main.py:3152-3154` → `make_eod_msg(book.snapshot() list)` | **Dead on arrival** — field names don't match (CL-C2). |
| `system.gateway_connect` | *Nobody publishes this on PUB.* Gateways PUSH it to the engine's PULL socket (`message.py:80-81`, `api_gateway/engine_client.py:131`, `alf_console/main.py:250`). | **Never received** (CL-C3). |
| `system.gateway_disconnect` | Same — PULL-only (`message.py:600-608`). | **Never received** (CL-C3). |

Two contract observations that are *correct* and worth preserving on purpose:

1. **`trade.executed` is the right feed.** It is currently the only *complete* execution feed in the system: the engine's private fill messages misreport prices on multi-level sweeps and go missing entirely for IOC/MARKET partial fills (engine review C4/H6), and the drop-copy feed on :5557 only covers the new-order flow (engine review H4). Clearing consuming public trades — with both gateway IDs per trade — sidesteps all of that. Document this as a deliberate choice so nobody "optimizes" clearing onto the broken private feeds before those are fixed.
2. **Clearing's ledger is more correct than the engine's own.** The engine's in-memory `_gateway_positions` misses all quote/combo/OCO-originated fills (engine review H3); clearing sees every trade. Until H3 is fixed, `system.position_request` (engine) and `pm-clearing-cli positions` **will disagree** — expect confused bug reports, and treat clearing as the source of truth.

Cross-reference: engine review A5 (sequence-number the public feed) is a prerequisite for fully fixing CL-H1; engine review H4/A1 (complete drop copy) would offer an alternative transport with replay.

---

## 3. Critical findings

### CL-C1 — Engine trade-ID counter breaks the archive's dedup key: silent trade loss after every engine restart

- **Where:** `store.py:44-58` (`id TEXT PRIMARY KEY`), `store.py:350-364` (`INSERT OR IGNORE`), against `models/trade.py:23,72` (`_trade_counter = itertools.count(1)`; `id=str(next(_trade_counter))`).
- **What:** The archive's idempotency design assumes trade IDs are globally unique. They were (uuid4) — until the engine's PERF #2 change replaced them with a per-process counter, explicitly documented as *"unique within a single engine run."* Clearing retains 90 days of rows. On the second engine run of the retention window, trades `"1"`, `"2"`, … collide with existing rows and `INSERT OR IGNORE` **silently drops them from `trade_events`** — while `_flush` (`main.py:320-330`) still applies them to the ledger, so positions and daily summaries include trades the raw archive says never happened.
- **Impact:** Permanent, silent divergence between the raw archive and every aggregate; `query_trades` shows *yesterday's* trade under today's ID; any audit or replay from `trade_events` is wrong from the second session onward. This is the single most damaging finding in the module and it is invisible in normal operation.
- **Fix (coordinate with the engine team):** the clean fix is engine-side — a run-scoped ID (`{run_epoch}-{counter}`) or restored UUID; engine review A5's per-engine sequence numbering solves this and CL-H1 together. Clearing-side hardening regardless: make the primary key `(id, ts_ns)` or a synthetic rowid with a UNIQUE index on `(id, trade_date)`, and **alert** (not ignore) when an incoming ID collides with a row whose content differs.
- **Regression test:** insert a trade with id "1", then a *different* trade with id "1" and a later timestamp; assert both survive in `trade_events` (or the second is loudly rejected — not silently absorbed) and that ledger and archive agree.

### CL-C2 — EOD mark-to-market is dead code: field names drifted from `book.snapshot()`

- **Where:** `main.py:373-382` (`_handle_eod` reads `book.get("last_trade_price")`, `book.get("best_bid")`, `book.get("best_ask")`), against `models/message.py:246-252` (`make_eod_msg` wraps `book.snapshot()` dicts) and `engine/order_book.py:581-602` (snapshot keys: `symbol`, `bids`, `asks`, `last_price`, `last_qty`, `last_buy_price`, `last_sell_price`, `recent_trades`).
- **What:** None of the three keys clearing looks for exists in the payload. `eod_marks` is therefore **always empty**, the entire EOD mark-to-market pass (step 2 of the handler) never executes, and every position's `mark_price`/`unrealized_pnl` is forever stuck at the *last trade* mark rather than the closing mark. Only the flush and the EOD sentinel row (steps 1 and 3) actually work. (Verified at runtime during this review: a real `book.snapshot()` after a trade at 150.75, fed through the handler's exact parse, yields `eod_marks == {}`.)
- **Why the tests missed it:** `test_clearing_main.py:424-449` tests `_handle_eod` with hand-built payloads containing `"last_trade_price": 15000, "best_bid": 14900, …` — the tests encode clearing's *expectation* of the contract, not the engine's *actual* output, so both sides of the drift stay green.
- **Latent second bug:** even if the key matched, `int(ltp)` (`main.py:380`) would truncate `last_price` — a **display float** (`150.75` → `150`) — and store it as if it were **ticks**, i.e. a ~100× unit error compounded with truncation. The engine review's C1 was the same class of bug in the opposite direction; this pair strongly argues for the shared rule in §7 (one explicit unit per message field, stated in the message builder's docstring).
- **Fix:** parse `last_price` via `to_ticks(last_price, symbol)`; derive best bid/ask from `bids[0]`/`asks[0]` if a fallback mark is wanted. Better: extend `make_eod_msg` to carry explicit closing marks in ticks + `tick_decimals`, since `snapshot()` is a viewer-oriented structure that will keep drifting.
- **Regression test:** build the payload with the real `make_eod_msg(book.snapshot())` (not a hand-built dict) after a trade at a known price; assert the position's `mark_price` equals that price in ticks. This test fails today and would have caught the drift the day it happened.

### CL-C3 — Gateway session tracking listens on topics the engine never publishes

- **Where:** `main.py:211-217` (subscribes `system.gateway_connect` / `system.gateway_disconnect` on the PUB feed), `main.py:427-480` (handlers), `store.py:151-160` (`gateway_sessions` table).
- **What:** Those topics are **gateway → engine** messages on the PULL socket :5555 (`message.py:12`, senders in `api_gateway/engine_client.py` and `alf_console/main.py`). The engine consumes them and broadcasts `system.gateway_auth.{gateway_id}` — a different topic — on PUB. Clearing's subscription therefore matches nothing, ever: `gateway_sessions` is permanently empty, `pm-clearing-cli sessions` always returns "No rows found", and the disconnect handler's deliberate safety behaviour ("force-flush buffered fills before the engine cancels the gateway's resting orders", `main.py:449-467`) never runs.
- **Why the tests missed it:** `test_clearing_main.py` calls `_handle_gateway_connect` directly with a hand-built payload — proving the handler works, not that it is ever invoked.
- **Fix options:** (a) engine broadcasts gateway lifecycle on PUB — it already publishes `system.gateway_auth.{id}` on connect, so clearing could subscribe to the `system.gateway_auth.` prefix and to a new `system.gateway_bye.{id}`; or (b) engine republishes connect/disconnect events verbatim on PUB. Either way, add the contract test from §8.

### CL-C4 — No warm start: a clearing restart overwrites correct positions with flat-based garbage

- **Where:** `main.py:166` (`self._ledger = Ledger()` — always empty), `store.py:366-393` (`_UPSERT_POSITION` — full replace of every column), `ledger.py:218-234` (`get_flush_rows` emits **all** in-memory positions every flush).
- **What:** The ledger has no persistence-recovery path. After a clearing restart mid-session, every position restarts from flat; the first post-restart trade for a (gateway, symbol) then UPSERTs `gateway_symbol_positions` with `net_qty`, `avg_cost`, `realized_pnl`, `buy_qty/sell_qty/…` computed *as if the day started flat* — **replacing** the correct cumulative row that was in the database. The daily-summary *delta* columns survive (they are increments, a good design), but the position table, the `end_*` snapshot columns, and all realized P&L from before the restart are destroyed.
- **Impact:** the process whose entire purpose is durable position state cannot survive its own restart. Combined with CL-C1 (which drops the raw rows you would need to rebuild from), a restart of both processes leaves no correct record anywhere.
- **Fix:** at startup, hydrate `Ledger` from `gateway_symbol_positions` (add `Ledger.restore(rows)`; net_qty, avg_cost, realized_pnl, buy/sell totals, tick_decimals are all in the table already). Alternatively rebuild from `trade_events` replay — slower but self-auditing. Guard with the restart round-trip test in §8.

---

## 4. High-severity findings

### CL-H1 — Lossy transport with no gap detection

- **Where:** `main.py:211-217` (SUB on the public PUB feed); `trade.executed` payload has no sequence number (`engine/main.py:1381-1399`).
- **What:** ZMQ PUB/SUB drops silently: everything published before the subscriber connects (slow-joiner — the engine seeds MM quotes *at startup*, and those first trades can print before clearing's SUB is joined), everything during a clearing outage or network hiccup, and everything beyond the HWM under burst. With no sequence numbers, clearing cannot even *detect* a gap, let alone recover one. Every missed trade is a permanently wrong position with no alarm.
- **Irony worth recording:** the engine's `DropCopyPublisher` (:5557) exists precisely for this consumer — sequenced messages plus a replay buffer (`drop_copy.py`) — but clearing doesn't use it, and currently *shouldn't* (it only carries new-order-flow fills; engine review H4). The architecture has two halves of a reliable clearing feed that have never been joined.
- **Fix (phased):** (1) engine review A5 — sequence every `trade.executed`; clearing tracks `last_seq`, logs/alerts on gaps, and records a `GAP` row in `session_events`. (2) recovery path: either complete drop copy (engine A1) and let clearing request `drop_copy.replay`, or add a `trades_since(seq)` request to the engine. (3) until then, run `pm-clearing-cli reconcile` (after CL-H4 is fixed) at every EOD as the manual gap detector.

### CL-H2 — Cross-scale aggregation: the totals views sum tick-units across symbols with different tick_decimals

- **Where:** `store.py:118-126` (`gateway_pnl_totals` — `SUM(realized_pnl)` etc. across all of a gateway's symbols), `store.py:128-136` (`daily_exchange_totals` — `SUM(traded_notional)` across all symbols), consumed raw by `pm-clearing-cli gateways` and `dates --with-totals` (no `tick_decimals` column even exists in the view output to normalize with).
- **What:** All P&L and notional figures are stored in **tick units** (correct, engine-consistent). But 100 ticks is \$1.00 for a 2-decimal symbol and \$0.01 for a 4-decimal symbol; summing them is meaningless. The moment a second tick-decimals value appears in `engine_config.yaml`, every gateway-level and exchange-level total silently becomes garbage — no error, plausible-looking numbers.
- **Fix:** normalize *inside* the views: `SUM(realized_pnl / POWER(10, tick_decimals))` (SQLite: `SUM(realized_pnl * 1.0 / (10 * 10 * ... )` via `POWER` from the math extension, or a CASE ladder over the 0–8 range, or precompute a `scale` column at write time — the last is simplest and fastest). Mark view outputs explicitly as display-currency.

### CL-H3 — CLI shows `avg_cost` in raw ticks next to normalized prices, backed by a false comment

- **Where:** `cli.py:166-175` — `_NORMALIZE_FIELDS["positions"]` excludes `avg_cost`, justified by the comment *"avg_cost is stored as REAL (result of division) and must NOT be divided again by the tick scale."*
- **What:** The comment confuses SQL affinity with units. `avg_cost` is REAL because VWAP division makes it fractional, but it is fractional **ticks**: `ledger.py:113` sets `avg_cost = float(price)` where `price` is int ticks. Both other consumers agree: `main.py:512-516` divides `avg_cost` by scale in its own P&L table, and the CLI itself normalizes `end_avg_cost` in the `daily` verb (`cli.py:183`). So `pm-clearing-cli positions` prints `avg_cost=15000` in the same row as `mark_price=150.0` — a 100× internal inconsistency in the tool operators will trust most.
- **Fix:** add `avg_cost` to the `positions` normalize list; delete the comment. One-line fix; the regression test is a positions query after one trade at a known price asserting `avg_cost == mark_price`.

### CL-H4 — `reconcile` cannot see total loss: summary-only keys are invisible

- **Where:** `store.py:1123-1149` — the final SELECT drives from `raw_all` (trade_events side) `LEFT JOIN summary_all`.
- **What:** A (date, gateway, symbol) key that exists **only in the summaries** — i.e. *every* raw row for it was lost — produces no output row at all, because the query only iterates raw-side keys. That is precisely the failure shape of CL-C1 after a full-day ID collision, and of any complete feed gap that the summaries survived (they don't — but a rebuilt DB could produce it). The verb whose one job is detecting divergence is blind to the worst divergence.
- **Also:** by design, `prune_old_events` (`store.py:463-477`) removes raw rows but keeps summaries — so once the join is fixed to be two-sided, reconcile must exclude dates older than the retention window or it will report false positives for every pruned day.
- **Fix:** make it a full outer comparison (`raw_all` ∪ `summary_all` keys via a UNION-driven anchor CTE), and add a `WHERE trade_date >= date('now', '-{retention} days')` guard (retention passed in from the CLI). The stale comment at `store.py:1144-1147` ("Notional values are stored as REAL after dividing by tick scale") describes a previous design — notionals are INTEGER ticks (`store.py:16-20`) — delete it and the now-pointless 0.0001 epsilon.

---

## 5. Medium-severity findings

**CL-M1 — Dedup gates the archive but not the ledger.** `INSERT OR IGNORE` makes `trade_events` idempotent, but `_flush` (`main.py:320-330`) applies every buffered trade to the ledger unconditionally. Any duplicate delivery — replayed message, future engine double-publish, or the CL-C1 collisions — double-counts positions while the archive dedupes. Idempotency must be one decision made once: check-and-mark (e.g. in-memory LRU of recent ids + the DB constraint) *before* both the ledger and the insert, and count rejected duplicates in a metric.

**CL-M2 — Unlocked ledger read races the flush thread.** `_print_pnl_table` (`main.py:486-528`) iterates `self._ledger.all_positions()` from the receive thread with no lock, while the timer thread mutates `_positions` inside `_flush` (held lock does not help a reader that doesn't take it). Symptoms range from torn rows in the printed table to `RuntimeError: dictionary changed size during iteration` killing the receive loop. Snapshot under `self._lock` (the v1 code, `clearing_v1/main.py:186-190`, actually does this correctly — the regression came with v2).

**CL-M3 — Trade dates bucket by UTC, not by exchange session.** `trade_date_utc` (`ledger.py:84-87`) buckets by UTC calendar day, while the engine's session schedule is wall-clock HH:MM (`ScheduleConfig`). For any deployment east of UTC with an evening session — or any classroom exercise crossing 00:00 UTC — one trading session splits across two `trade_date` buckets and daily summaries stop matching the session the students actually traded. Define the trading day once (engine publishes it in session messages, or clearing derives it from the EOD/session events) and bucket on that.

**CL-M4 — Unit mismatch inside the (dead) EOD mark pass.** `main.py:393-396`: `unrealized_pnl = net_qty * (float(mark) - pos.avg_cost)` where `mark` would be an int-truncated *display* price and `avg_cost` is ticks. Fix together with CL-C2 so the revived code path doesn't introduce a fresh 100× error.

**CL-M5 — Session matching state lives only in memory.** `_gw_connect_ts` (`main.py:175, 462`) maps connects to disconnects in a dict; a clearing restart orphans every open session row (disconnect is skipped when `connect_ts` is falsy, `main.py:468`). Match on `MAX(connected_at_ns)` for the gateway in SQL instead. (Moot until CL-C3 makes the feature live at all.)

**CL-M6 — The heuristic timestamp/price re-normalization is a liability.** `_to_timestamp_ns` (`main.py:96-104`) guesses seconds-vs-nanoseconds by magnitude; `_trade_from_payload` guesses ticks-vs-display by *type* (`isinstance(price_raw, float)`). Both currently guess right, but a millisecond timestamp (plausible from a future gateway) would be multiplied to year ~55,000, and an integer display price would be misread as ticks. This is the cost of an implicit contract; once `trade.executed` is documented/versioned (§7), replace guessing with one assertion of the declared units.

**CL-M7 — `session_events` documents PHASE rows nothing writes.** `query_session_events` (`store.py:944-957`) advertises `event_type='PHASE'` filtering, but the only writer is the EOD sentinel. The engine broadcasts `session.state` on PUB (`message.py:465-470`) — clearing simply doesn't subscribe. Either subscribe and record phase transitions (cheap, genuinely useful for bucketing) or delete the claim.

**CL-M8 — Legacy `clearing_v1` is still shipped and rotting.** `pm-clearing-v1` (`pyproject.toml:62`) parses `trade.executed` with `Trade.from_dict(payload)` raw — leaving a display *float* in a field typed as int ticks — computes P&L in a float/int hybrid, appends to an unbounded CSV, and its docstring still claims it runs as `poetry run pm-clearing`. Two clearing implementations with different numbers is worse than one; deprecate it (print a banner and exit unless `--yes-i-know`) or delete it.

**CL-M9 — Full position-table rewrite on every flush.** `get_flush_rows` (`ledger.py:227-229`) emits *every* position ever seen on *every* flush; with hundreds of (gateway, symbol) pairs, each 5-second flush rewrites the whole table to update a handful of rows. Track batch-touched keys (the `_batch_deltas` keys already are exactly that set) and emit only those.

---

## 6. Low-severity findings

**CL-L1** — `_create_table_if_missing` (`store.py:259-292`) is dead weight: the DDL it guards already uses `CREATE TABLE IF NOT EXISTS` and is in `SCHEMA`, executed one line earlier. Delete.
**CL-L2** — `open_writer_connection(check_same_thread=False)` (`store.py:327`) is only safe because every write path holds `self._lock`; that invariant is undocumented and one unlocked `conn.execute` away from corruption. Document it on the function, or move all DB work onto the timer thread.
**CL-L3** — `query_trades` orders by `ts_ns DESC, id ASC` (`store.py:741`): with counter IDs, TEXT ordering puts `"10"` before `"9"`. Cosmetic today; becomes the visible symptom of CL-C1's ID scheme. Order by `ts_ns DESC, ingest_ts_ns DESC`.
**CL-L4** — EOD sentinel and gateway rows are timestamped with clearing-local `now_ns()` (`main.py:368, 435, 460`) rather than any engine-side event time — fine, but label the column `ingest_ts_ns` semantics in the docstring so nobody treats it as exchange close time.
**CL-L5** — `aggressor_side` in the archive inherits the engine defect that auction trades always mark the buyer as aggressor (engine review L9). Note it in the schema docs so analysts don't trust the column for auction prints.
**CL-L6** — `_print_every` modulo check reads `_trade_count` outside the lock (`main.py:283`) — benign (worst case a skipped/duplicate table print), fine to leave with a comment.
**CL-L7** — Startup-only pruning: `prune_old_events` runs once in `run()`; a clearing process that stays up for months never prunes. Cheap fix: piggyback a daily prune on the EOD handler.

---

## 7. Structure, organization, and the unit-discipline rule

The module layout is good — clean separation of transport (main), domain math (ledger), persistence (store), and reporting (cli); dataclass row types crossing each boundary; the ledger is pure and easily testable. Three structural recommendations:

**A — Make the engine contract explicit and owned.** Every critical finding here is a reader/writer pair drifting because the contract lives in two heads. Create `docs-design/EduMatcher-Feeds.md` (or a `models/feed_schema.py` with typed payload dataclasses used by *both* the engine's `make_*_msg` builders and clearing's parsers) defining for each PUB topic: fields, **units** (ticks vs display, seconds vs ns), optionality, and a feed version field. CL-C2, CL-M6, and the engine's own C1 are all instances of the same missing artifact.

**B — One unit-normalization boundary per process.** Clearing does this almost right: `_trade_from_payload` converts to ticks/ns at ingress, everything internal is ticks, and the CLI converts at egress. The three leaks — the views (CL-H2), the CLI's avg_cost exemption (CL-H3), and the EOD handler's `int(display)` (CL-C2) — are each a second, inconsistent conversion point. Rule: ingress converts, egress renders, nothing in between touches units.

**C — Recovery is a feature, not an accident.** The store was built for durability (WAL, atomic batches, idempotent inserts) but the process wasn't (CL-C4, CL-M5, no gap recovery). Add a startup sequence: hydrate ledger from DB → verify against a quick `trade_events` aggregate (reuse the reconcile SQL) → log any divergence → then subscribe. That turns every restart into a self-audit.

---

## 8. Testing recommendations

> **Regression suites for this review:** `tests/test_clearing_review_criticals_highs.py` (CL-C1..C4, CL-H1..H4 — 8 tests, all failing by design until fixed) and `tests/test_clearing_cross_boundary.py` (XB1–XB7 conservation/round-trip/resilience guards plus the CL-M1 duplicate-delivery and the CL-C1×CL-C4 "day two of class" compound scenarios). Both are built on `tests/clearing_harness.py`, which implements items 1–5 below literally: every payload is produced by the engine's own handlers/builders and delivered over a real ZMQ socket into a real running `ClearingProcess`, so the tests assert behaviour, not topic names or code paths — any reasonable fix goes green without test edits. XB5 (cross-system position agreement) already demonstrated the pattern in reverse: it was red while engine finding H3 was open and went green the day that fix landed.

The existing clearing tests are solid on the ledger math and store SQL but share the engine suite's original systemic flaw (see engine review §10): payloads are hand-built to match clearing's expectations, so contract drift is untestable by construction. Additions, in value order:

1. **Contract tests using the engine's own builders.** For each subscribed topic, produce the payload with the real producer (`Engine._publish_trade` via a fake socket, `make_eod_msg(book.snapshot())`, the gateway-auth flow) and feed clearing's actual handler. Assert observable effects: EOD marks non-empty (catches CL-C2 today), a session row appears (catches CL-C3 today), archived price/timestamp round-trip to the engine's tick values.
2. **Engine-restart archive test.** Simulate two engine runs (reset `models.trade._trade_counter` between them) publishing into one clearing DB; assert no trade vanishes from `trade_events` and ledger totals equal archive totals (catches CL-C1 today).
3. **Clearing-restart warm-start test.** Trade → flush → new `ClearingProcess` on the same DB → one more trade → assert `gateway_symbol_positions` reflects *both* (catches CL-C4 today).
4. **Reconcile completeness test.** Delete all raw rows for one key, leave the summary; assert `query_reconcile` reports it (catches CL-H4 today).
5. **Mixed tick-decimals test.** Two symbols (2dp and 4dp), one trade each; assert `gateways` totals and `positions` avg_cost render in consistent display units (catches CL-H2/H3 today).
6. **Concurrency smoke test.** Hammer `_receive`-side appends while forcing timer flushes and table prints; assert no exception (catches CL-M2 probabilistically; better after the lock fix as a permanent guard).
7. **End-to-end conservation property:** after any random trade sequence, `SUM(net_qty)` across all gateways per symbol == 0, and `SUM(realized_pnl + unrealized_pnl)` across gateways == 0 per symbol (a closed system is zero-sum). This single invariant catches whole classes of ledger and ingestion bugs and mirrors the engine's invariant-suite approach.

---

## 9. Suggested remediation order

| Phase | Items | Rationale |
|---|---|---|
| 1 — Stop silent data loss | CL-C1 (with engine team), CL-M1, CL-H4 | Archive integrity first; reconcile becomes trustworthy |
| 2 — Make dead features live | CL-C2 + CL-M4, CL-C3 + CL-M5 (needs engine PUB change), CL-M7 | Each is small once the contract is agreed; do together with §7-A contract doc |
| 3 — Survive restarts | CL-C4, warm-start + self-audit sequence (§7-C) | Then a restart is safe, which phases 1-2 assume |
| 4 — Transport reliability | CL-H1 (engine A5 seq numbers → gap detection → replay path) | Biggest cross-team item; reconcile (phase 1) is the interim mitigation |
| 5 — Reporting correctness | CL-H2, CL-H3, CL-M3 | User-visible numbers; cheap fixes |
| 6 — Hygiene | CL-M2, CL-M6, CL-M8 (deprecate v1), CL-M9, CL-L1..L7 | Polish once behaviour is correct |

---

*End of review. All four critical findings and the contract-surface table were verified against both sides of each interface (clearing parser and engine producer) before publication; line references are to the current working tree.*

# EduMatcher — Simulation Forensics: Using Long Sim Runs as a Probabilistic Test

A long `edumatcher-sim` run (AI swarm + MM bot + market sim against the real
engine) is a randomized test that nobody wrote assertions for. Every fact the
engine produces is recorded independently by several consumers (pm-audit,
pm-stats, pm-clearing, drop-copy, post-trade, market data, pm-monitor). If
the engine and the recorders are correct, those records must agree with each
other and with the matching rules. This plan turns that into a structured,
repeatable check suite: **oracles → checks → findings ledger → regression
tests**.

One work package (WP) at a time, as in the other workplans; each WP ends with
the holistic test run, a review, and a proposed commit message. The
maintainer commits.

Started: 2026-10-23

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit)

| # | WP | Content | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|
| 0 | S0 | Freeze the current run: consistent snapshot of all stores | — | 0.5 h | ☑ | 2026-10-23 |
| 1 | S1 | Close observability gaps found in recon (§2), then start a new long run | S0, Q1 | 1 d | ☑ (run 2026-10-24 made) | 2026-10-23 |
| 2 | S2 | `tools/sim_forensics/` skeleton: loader, check registry, report | S0 | 1 d | ☑ | 2026-10-23 |
| 3 | S3 | Checks A + B: cross-store trade identity, double-entry book-keeping | S2 | 1 d | ☑ | 2026-10-23 |
| 4 | S4 | Checks C: order lifecycle legality | S2 | 1 d | ☑ | 2026-10-23 |
| 5 | S5 | Checks D: matching correctness from audit episodes (missed / illegal matches) | S1, S2 | 2 d | ☑ | 2026-10-24 |
| 6 | S6 | Check E: full replay differential (engine + reference matcher) | S5, T3 of matching plan | 2–3 d | ☐ | |
| 7 | S7 | Checks F–H: derived data, persistence, ops-signal correlation | S2 | 1.5 d | ☐ | |
| 8 | S8 | Triage of all findings; each confirmed bug → regression test + fix WP | S3–S7 | open | ☐ | |

Total ≈ 10 d plus fix WPs. S0 is **urgent** (see §2, R3: order events are
pruned after 12 h).

---

## 1. What the run produced (inventory, 2026-10-23)

Data dir: `~/.edumatcher-sim/data` (1.5 GB). The sim is **still running** —
every store is growing, so all analysis works on a snapshot (S0), never the
live files.

| Store | Content | Size / rows | Identity keys | Notes |
|---|---|---|---|---|
| `audit.log*` | every bus message, with `seq` (per topic), `msg` (ULID), `cause`, `chain` | 6 × 10 MB | trade id, order id, chain | **only ~3 min retained** (§2, R1) |
| `stats.db: trade_log` | every trade | 447 k | `trade_id` | |
| `stats.db: order_events` | ACK/FILL/CANCEL/EXPIRE/REJECT/QUOTE_*/OCO_* | 3.6 M | `order_id`, `seq` (receive order) | pruned at 0.5 d; `trade_id` always NULL (§2, R2) |
| `stats.db: daily_stats, price_snapshots` | OHLCV, 15-min BBO snapshots | 600 / 26 k | (date, symbol) | |
| `stats.db: index_*` | index levels | **0 rows** | | pm-index running but nothing recorded (§2, R6) |
| `clearing.db: trade_events` | every trade, settled | 447 k | `id` | |
| `clearing.db: gateway_symbol_positions, gateway_daily_summary` | positions, P&L | 3 148 | (gw, symbol) | |
| `clearing.db: session_events, gateway_sessions` | phase changes, connects | 3 / 204 | | |
| `metrics.db` | 2 631 series (engine counters per symbol/gw, latency, heap, gateway, process), threshold events | 1.8 M 1-min samples | series id | independent counters → reconciliation |
| `log.db` | structured logs | 3.7 k | | only api-gwy, ai-swarm, market-sim ship logs |
| `emo/*.log` | per-process stdout | small | | `engine.log` is empty |
| `gtc_orders.json`, `gtc_combos.json` | persisted resting GTC state | 1.8 MB | order id | snapshot of book state |
| `book_stats.json`, `market_sim_state.json` | prev close / last prices, sim fair values | | symbol | |
| `market_sim_news.db` | news events | 5 | | correlate price jumps |

"Almost 2 days" is really **one trading session**: the stack started
2026-10-22 16:37 local (after close; zero trades that day); trading began
2026-10-23 09:00 local (PRE_OPEN 09:00, opening auction 09:25, continuous
09:30). `run_seq` = 1 throughout (no engine restart).

## 2. Findings already made during recon

A first pass of read-only queries (bounded at trade `000001-000446970`)
already shows that the approach pays off:

**Passed (good news)**

- `stats.trade_log` and `clearing.trade_events` contain exactly the same trade
  ids, no gaps in the trade counter, identical price/qty/gateways/aggressor.
- `daily_stats` OHLCV/turnover is exactly reproducible from `trade_log` for all
  300 symbols.
- Clearing positions net to zero over all gateways; Σbuy_qty = Σsell_qty.
- No fill exceeds its order quantity; no zero/negative price or quantity.

**Red flags — need triage (S8)**

| ID | Observation | First hypothesis |
|---|---|---|
| R1 | Audit is a `RotatingFileHandler(maxBytes=10 MB, backupCount=5)`: 60 MB ≈ **3 minutes** of a 5 h session. ~35 % of lines are `book.*`/`depth.*` snapshots. | Observability gap. The only causal stream (cause/chain, inbound commands) is lost for >99 % of the run. Blocks checks D and E. |
| R2 | `order_events.trade_id` is NULL for **every** FILL. The engine sends `trade_ids` (a list); pm-stats reads `payload.get("trade_id")` (`src/edumatcher/stats/main.py:1711`). | Recorder bug. Fill ↔ trade cannot be joined in stats.db. |
| R3 | `keep_order_events_days = 0.5` | Data from this run disappears ~12 h after it was written. Snapshot now. |
| R4 | 123 trades with `buy_gateway_id == sell_gateway_id`, all `aggressor_side = AUCTION`, although every order carries `smp_action = CANCEL_AGGRESSOR`. | Spec question (Q2): does SMP apply in the uncross? If yes → engine bug. |
| R5 | 358 orders (all MM01 quote legs) show `CANCEL reason=QUOTE_LEG_FILLED` **before** a `FILL` of the same order, then a second CANCEL. | Either receive-order artefact in pm-stats (topics arrive out of order) or the engine emits the leg cancel before the fill. Needs audit `seq`/`msg` order to decide. |
| R6 | Σ FILL `fill_qty` (36.23 M) < 2 × Σ trade qty (36.32 M) at the same time bound: ~93 k shares (0.26 %) of fills are missing. | Dropped order events in pm-stats (`stats.records_dropped`), quote fills reported only as QUOTE_STATUS, or lost fill messages. Check B2 per gateway/symbol pinpoints it. |
| R7 | `index_daily_stats` / `index_level_snapshots` empty; engine logs nowhere. | Observability gaps; decide in S1. |
| R9 | After the sim stopped, clearing has trade `000001-000456710`, stats does not. | pm-stats loses its last unflushed record on shutdown. Minor; check B6/A1 confirm. |
| R8 | `engine_handle_p99_us` spikes to 35 ms (CRIT > 20 ms), `heap_garbage_pct` > 80 % on single books. | Not correctness, but every anomaly found later gets correlated with these windows (H1). |

## 3. The oracles

Every check is an instance of one of six oracle types. Strongest last.

1. **Conservation (double-entry).** Quantities that must balance: every trade
   is exactly one buy fill and one sell fill; per order Σfills ≤ qty and
   `remaining = qty − Σfills`; per symbol Σnet_qty = 0; Σbuy notional =
   Σsell notional.
2. **Cross-store reconciliation.** The same fact recorded by independent
   consumers must agree: audit ↔ stats ↔ clearing ↔ drop-copy ↔ post-trade ↔
   metrics counters. A disagreement is either a lost/duplicated message or a
   recorder bug.
3. **State-machine legality.** An order's event sequence must be a word in the
   lifecycle grammar (NEW → ACK → (FILL | AMEND)* → terminal); nothing after a
   terminal state; reasons/reject codes from the canonical set.
4. **Book-state oracles.** After the engine has finished processing one inbound
   command (one `chain` in the audit), the book in CONTINUOUS must not be
   crossed (bid ≥ ask between non-SMP-protected owners) → **a missed match**.
   Fills must respect limit prices, price-time priority and never trade
   through a better resting price → **an illegal match**.
5. **Replay differential.** Feed the inbound command stream, in engine arrival
   order, into a fresh `OrderBook` and into `tests/reference_matcher.py`; diff
   trades, acks and final book against what the live run produced (and against
   `gtc_orders.json`). Detects lost, extra and wrongly-priced matches in one
   go, and turns every divergence into a ready-made regression test.
6. **Statistical / temporal.** Not proofs, but pointers: distribution outliers
   (P&L, fill ratio, reject rate, spread, price jumps without news), and time
   clustering of anomalies with ops events (latency spikes, reconnects,
   dropped records).

## 4. Architecture of the tool

Keep it a tool (`tools/sim_forensics/`), not a product feature, until it has
proven its value. Plain Python + `sqlite3`; no new dependencies.

```
snapshot ──► load/normalise ──► checks (registry) ──► findings.json + report.md
 (S0)          forensics.db        A..H, one fn each        (ledger, S8)
```

- **Snapshot.** `sqlite3` backup API for each DB (consistent despite WAL),
  copy `audit.log*`, JSON state files, `emo/`. Record a **cut**: the highest
  trade id and ts present in *all* stores; every check is bounded by the cut
  so stores written at different speeds compare fairly.
- **Normalise.** One `forensics.db` that ATTACHes the snapshot DBs and adds
  views/tables: `audit_events(ts, topic, family, gw, seq, msg, cause, chain,
  payload json)` parsed via the existing `edumatcher.audit.query.iter_entries`
  / `split_topic`; `fills` (exploding `trade_ids`); `orders` (one row per
  order: first ACK fields + derived final state).
- **Reuse.** `pm-audit-replay` already has a fact/episode pipeline and a
  `Detector` (`src/edumatcher/audit/replay/detect.py`) with checks for fills
  naming their trades, trade counters, corridors, drop-copy sequencing,
  quote legs, liquidity flags. Checks D run *through* that detector and add
  the book-state oracles to it, rather than re-implementing audit parsing.
- **Check contract.** Each check: id, oracle type, SQL or Python function,
  expected violation count (normally 0), severity, up to N sample rows with
  the keys needed to drill down (trade id / order id / chain). A check that
  cannot run (missing data) reports `SKIPPED: <reason>` — never silently
  passes.
- **Report.** Markdown summary table (check, result, count, samples) plus
  `findings.json`. Run with
  `poetry run python tools/sim_forensics/run.py --data <snapshot> --out <dir>`.

## 5. Check catalogue

Status column of the report = PASS / FAIL(n) / SKIPPED(reason).

### A — Trade identity and completeness (cross-store)

| ID | Check |
|---|---|
| A1 | Trade id sets equal across stats, clearing, audit `trade.executed`, drop-copy and post-trade (where retained). Report each store's extras. |
| A2 | Trade counter (`run_seq-counter`) gap-free and duplicate-free per `run_seq`. |
| A3 | Per trade: price, qty, gateways, order ids, aggressor, tick_decimals identical in every store. |
| A4 | Trade ts monotonic in counter order; `ts_ns` within session phase windows (`session_events`). |

### B — Double-entry book-keeping

| ID | Check |
|---|---|
| B1 | Each trade has exactly one buy-side and one sell-side FILL whose order ids, qty and price match the trade (needs R2 fixed or audit). |
| B2 | Per order: Σfill_qty = Σ qty of the trades it is a side of (finer than per (symbol, gateway); needs no trade ids); localises R6. |
| B3 | Recompute `gateway_symbol_positions` from `trade_events` (net qty, buy/sell qty, notional, avg cost, realised P&L) and compare exactly. |
| B4 | `gateway_daily_summary` = aggregate of B3 per trade date. |
| B5 | Per symbol Σnet_qty = 0; Σbuy_notional = Σsell_notional; Σrealised P&L + Σunrealised P&L = 0 at a common mark (zero-sum market). |
| B6 | metrics `daily_totals` (restart-corrected) vs. rows, within a 15 s reporting slack of `counter_last.ts`: `engine.trades` per symbol = trades; `engine.fills` per gateway = trade sides (the engine counts one per side, not per FILL message); `clearing.trades_settled` = trade_events by ingest time. `stats.events_recorded` and `audit.records` deferred (no row set to count them against yet). |
| B7 | Loss/error counters never above 0 (`stats.records_dropped`, `stats.feed_gaps`, `audit.decode_errors`, `health.beacons_dropped`, `health.samples_rejected`, `monitor.*_invalid`, `monitor.*_errors`); `stats.feed_gaps` table empty. |

### C — Order lifecycle

| ID | Check |
|---|---|
| C1 | Event sequence per order is legal (grammar per order type, quotes and OCO). Ordering by audit `msg` ULID / per-topic `seq`, not by pm-stats receive order (R5). |
| C2 | Nothing after a terminal event (FILLED, CANCELLED, EXPIRED, REJECTED). |
| C3 | `remaining_qty = qty − cumulative fill` at every FILL; final status consistent with remaining. |
| C4 | Every ACKed order ends terminal, or is still resting at the cut; resting GTC orders = `gtc_orders.json`; DAY orders all EXPIRE at close. |
| C5 | OCO: at most one leg fills; sibling cancelled with the right reason. Quotes: leg-filled semantics (R5). Combos: legs fill together. |
| C6 | Reject / cancel reason codes are canonical; reject-rate time series per code (spikes → H). |
| C7 | Stops/trailing stops trigger only after a trade crossed the (trailing) stop price; icebergs: displayed ≤ peak, refill after peak exhausted. **Moved to S5**: `order_events` stores neither stop prices nor display quantities; needs the audit. |

### D — Matching correctness (audit episodes; needs S1 retention)

| ID | Check |
|---|---|
| D1 | **Missed match:** after each episode (one `chain`) in CONTINUOUS, the `book.*` snapshot is not crossed, unless the crossing orders are SMP-protected against each other. |
| D2 | **Marketable order rested:** an ACKed limit order that rests while the opposite best was at or through its limit (from the reconstructed book). |
| D3 | Limit respected: buy fill price ≤ limit, sell ≥ limit; market orders within collar. |
| D4 | No trade-through: each fill is at the best available opposite price at that moment. |
| D5 | Price-time priority: within a level, resting orders fill in `arrival_seq` order (iceberg refills lose priority; amend-down keeps it). |
| D6 | Auction uncross: one price per symbol per auction, maximises executable volume, tie-breaks per the spec; book uncrossed afterwards; all prints `aggressor_side = AUCTION`. |
| D7 | SMP: no continuous self-trades; auction self-trade policy per Q2 (R4). |
| D8 | All prices on the tick grid; trades inside collar / circuit-breaker bands; halts honoured. |

### E — Replay differential

| ID | Check |
|---|---|
| E1 | Extract inbound commands (`order.new`, `order.cancel`, amends, `quote.*`, `order.oco`, session changes) from the audit in engine arrival order (`arrival_seq` / ULID). |
| E2 | Replay into a fresh `OrderBook` (canonicalise ids and timestamps as in the System-Trading-Verification doc §9); diff trades, acks, rejects. A diff here means non-determinism or a hidden input (time, collar state). |
| E3 | Replay into `tests/reference_matcher.py`; diff trade-for-trade. A diff here is a matching bug on one side — shrink it to a minimal scenario and add it to the matching test suite. |
| E4 | Final replayed book vs `gtc_orders.json` and the last `book.*` snapshots. |

### F — Derived data and market data

| ID | Check |
|---|---|
| F1 | `daily_stats` OHLCV/turnover/VWAP from `trade_log` (passes today; keep as regression). |
| F2 | `price_snapshots` best bid/ask equal the audit book at the same instant. |
| F3 | `book.*` `last_price`/`last_qty`/`recent_trades` consistent with `trade.executed`. |
| F4 | `book_stats.json` `prev_close` = previous day's `close_price`. |
| F5 | Index levels recomputable from constituent prices (once R7 is fixed). |

### G — Persistence

| ID | Check |
|---|---|
| G1 | `gtc_orders.json` contains no terminal orders; `remaining_qty` matches the last FILL; ticks match `tick_decimals`. |
| G2 | `run_seq` in trade ids matches `engine_run_seq.json`; on a run with a restart, no trade id reused and resting orders survive. |

### H — Ops-signal correlation and statistics

| ID | Check |
|---|---|
| H1 | For every finding from A–G, list ops events within ±30 s (metrics `events`: thresholds, process status, connects; `gateway_sessions` disconnects; log.db WARN/ERROR). Clusters point at load-related bugs. |
| H2 | Per-agent outliers: P&L, fill ratio, reject rate, cancel-to-fill; per-symbol: spread, price jumps > k·σ without a news event (`market_sim_news.db`). |
| H3 | Latency (`engine.handle_us_*`) vs book size / garbage — not a correctness check, but feeds the perf plan. |

## 6. Triage workflow (S8)

Each FAIL becomes a row in a **findings ledger** (section appended to this
doc): id, check, count, example keys, classification, action.

Classification:

1. **Engine bug** → minimal repro (from the audit chain, or shrunk replay
   diff) → failing test in the matching suite → fix WP.
2. **Recorder/consumer bug** (stats, clearing, gateways) → unit test in that
   component → fix.
3. **Observability gap** → change for the next run (S1-style).
4. **Spec ambiguity** → question to the maintainer, then write the rule into
   the docs and both implementations (as Q3 of the matching plan).
5. **Expected / check wrong** → fix the check, document why.

Rule: a finding is only closed with a test that would have caught it.

## 7. Work packages

### S0 — Freeze the current run (do now)

- Back up `stats.db`, `clearing.db`, `metrics.db`, `log.db`,
  `market_sim_news.db` with the sqlite backup API; copy `audit.log*`, JSON
  state files, `ref_data/`, `emo/` into
  `~/.edumatcher-sim/forensics/2026-10-23/`.
- Write `cut.json` (highest common trade id, its ts).
- Verify: row counts of the copies ≥ the recon counts above.

**Done 2026-10-23 (changed):** the sim was stopped by the maintainer, so the
data dir itself is the snapshot — no copy. Cut written to
`~/.edumatcher-sim/forensics/2026-10-23/cut.json`: trade
`000001-000456709`, `2026-10-23T12:35:35.773Z`; trade_log 456 709,
trade_events 456 710 (R9), order_events 3 709 999. Constraint: do not restart
the sim on this data dir (pm-stats would prune `order_events`).

### S1 — Close observability gaps, start the next long run

- R1: make audit retention configurable (`audit.max_bytes`,
  `audit.backup_count`) and, for the sim profile, size it for a whole session
  (estimate ~8 GB/session at today's rate — or exclude `book.*`/`depth.*`
  from the audit file, which cuts ~35 % of lines and most bytes; see Q1).
- R2: pm-stats records `trade_ids` (fix + test).
- R3: sim profile keeps order events ≥ 7 days.
- R7: decide whether the engine should ship logs to log-srv; check why
  index stats are empty.
- Then run the sim for ≥ 1 full session including open and close auctions
  and, ideally, one deliberate engine restart (exercises G2).

**Done 2026-10-23 (code):**

- R1: `pm-audit --max-file-mb MB --backup-count N` (defaults 10 / 5, both
  ≥ 1). The `ai-sim` emo profile runs `--max-file-mb 256 --backup-count 100`
  (~25 GB ≈ two trading days at the measured ~1.2 GB/h). Readers already
  sort rotated files numerically, so `audit.log.10`+ needs no change.
  Docs: operator guide audit chapter, reference manual, `pm-help` registry,
  regenerated shell completion.
- R2: `order_events.trade_id` → `trade_ids` (JSON array text), stats
  schema 7 → 8 (old files refused, not migrated — move the old data dir).
  The existing unit tests fed a `trade_id` key the engine never sends, so the
  tests had encoded the bug. Insight for S2: recorder tests should build
  their payloads from the generated message bindings, not hand-written dicts.
- R3: `ai-sim` profile keeps order events 2 days instead of 0.5 (~1.2 GB of
  stats.db per trading day). 7 days was not needed now that the audit holds
  the session.
- R7 closed, no fault: s300-sim defines no indexes (`pm-index: loaded 0 index
  runtime config(s)`), and the engine runs at WARNING by design and logged
  no warnings.
- Pending (maintainer): move `~/.edumatcher-sim/data` away, rebuild/update the
  sim image so it contains these changes, run ≥ 1 full session.

### S2 — Tool skeleton

`tools/sim_forensics/{run.py, snapshot.py, load.py, checks/, report.py}`;
the check registry and contract from §4; one trivial check (F1) end to end.
Tests: small fixture data dir in `tests/fixtures/` with a planted violation
per check type, so every check is proven to *fail* when it should.

**Done 2026-10-23 (changed from the sketch above):**

- Layout: `tools/sim_forensics/{dataset,registry,report,__main__}.py` and
  `checks/` (one module per family; `checks/derived.py` holds F1). No
  `snapshot.py` — runs are analysed after the sim is stopped (S0 decision).
  Run: `make forensics DATA=<data dir> OUT=<report dir>` or
  `PYTHONPATH=tools poetry run python -m sim_forensics --data … --out … [--check ID] [--list]`.
  Exit code 1 on any FAIL/ERROR.
- `Dataset`: in-memory connection, each present store ATTACHed read-only
  under its name (`stats`, `clearing`, `metrics`, `log`); `session_date(ts)`
  SQL function in the session timezone (from `stats_meta`/`clearing_meta`);
  `cut_trade_id` = lowest of the trade stores' highest trade id. Audit parsing
  is left to S5 where it is first needed.
- Contract: `@check(id, oracle, title, needs=(stores…))` → `Outcome(violations,
  samples, note)`; a missing store → SKIPPED, an exception → ERROR (traceback in
  the report) without stopping the other checks; samples capped (`--samples`),
  violations counted in full.
- Fixture data is built in `tests/test_sim_forensics.py` with the recorders'
  real schemas (`stats.main.SCHEMA`, `clearing.store.apply_schema`) rather than
  checked-in files under `tests/fixtures/`, so a schema change breaks the test,
  not the next run. 16 tests, including planted violations for F1 and a
  midnight-in-Stockholm trade that a UTC date bucket would misfile.
- F1 on the 2026-10-23 run: PASS (300 symbol-days, 1.2 s); report in
  `~/.edumatcher-sim/forensics/2026-10-23/`. Open/close are recomputed in
  engine trade-id order, so this also shows pm-stats recorded trades in
  sequence.
- Insight: `make _check` runs black/flake8/pyright on `src tests` only; the
  tool's own files are reached by mypy through the test's imports but not by
  pyright/flake8. Run `poetry run flake8 tools/sim_forensics` and
  `poetry run pyright tools/sim_forensics` in each later S-WP.

### S3 — Checks A + B

Mostly SQL over ATTACHed DBs. Gives the R6 answer (B2 per gateway/symbol)
and the full clearing recomputation (B3).

**Done 2026-10-23:** `checks/trades.py` (A1–A4), `checks/bookkeeping.py`
(B1–B7). Result on the 2026-10-23 run (21 s for all 12 checks): everything
PASS except **B2 FAIL (749 orders)**; B1 SKIPPED (schema 7, R2).

- Design decisions: B1 needs `trade_ids` (schema 8) and raises the new
  `Skipped` for older files; B2 works without them (per-order quantity). B1/B2
  skip trades older than their gateway's oldest retained order event (pm-stats
  prunes per gateway class) and orders with trades beyond the cut. B3/B4
  replay `trade_events` in trade-id order with exact `Fraction` average cost
  and skip when clearing has pruned its first trade (positions are
  cumulative). B5 needs no replay: Σnet = 0 per symbol, and per position
  realized + unrealized = sell − buy notional + net·mark under any cost method.
- Tests: `tests/sim_forensics_world.py` builds a consistent 4-trade run
  (auction print, reduce, cross through zero, second symbol) whose stored
  positions come from the **production** clearing `Ledger`, so the all-pass test
  also pins replay ≡ Ledger. `tests/test_sim_forensics_bookkeeping.py`: one
  planted violation per failure mode (25 tests).
- Insights: (1) a FULL OUTER JOIN of two un-indexed CTEs ran > 10 min on
  real data — materialise into indexed temp tables (B2 now 3 s). (2) The
  registry fills on import of `sim_forensics.checks`; a test module that
  forgot it passed the all-pass test vacuously — the test now pins the check
  ids. (3) `engine.rejects` (35 903) ≫ REJECT rows in pm-stats (4 141): they
  count different things; examine in C6. (4) A4 confirmed auction prints are
  stamped up to 0.37 s *before* the CONTINUOUS transition, i.e. inside
  OPENING_AUCTION, as the uncross runs on exit.
- R6 resolved → finding **X1** (ledger, §9).

### S4 — Checks C

Python over `orders`/`order_events`, ordered by audit order where available.
Decides R5.

**Done 2026-10-23:** `checks/lifecycle.py` (C1–C6; C7 moved to S5). One
cached pass over `order_events` (order by order, receive order = engine
publish order: one PUB, one SUB) through a state machine; ~10 s on the run.
Result: C3, C5 PASS; C1 FAIL 4 107 (X5), C2 FAIL 414 (365 X3 + 49 X1 legs),
C4 FAIL 1 (X4), C6 FAIL 1 (X6). R5 decided → X3 (engine bug).

- Grammar decisions from the data, not just the spec: REJECT is pm-stats's
  name for `order.ack accepted=false`, so a REJECT after a terminal state is a
  rejected cancel/amend command (`Order not found`) and is legal; quote legs
  have no per-order ACK, so a quoting gateway (one with QUOTE_ACK rows) may
  start an order with FILL/CANCEL; "without an ACK" is not checked when the
  order events span more than `keep_order_events_days`.
- C4 uses `gtc_orders.json` as the oracle: it is the engine's whole resting
  book at shutdown (DAY and GTC, orders and quote legs, untriggered stops),
  not just GTC orders. DAY-after-close is checked when the last PHASE is
  CLOSED (not reached in this run).
- C5 encodes only the unambiguous OCO rule (docs: "when one fills or is
  cancelled, the engine cancels the other"); both legs partially filling is
  reported in the note (0 in this run). OCO closures are inferred from the
  group's OCO_CANCEL row (X7).
- C6 reconciles rejects with `engine.rejects` through the B6 helper
  (`counter_mismatches`, now shared). Fixed in it: a counter still at zero has
  no `daily_totals` row, so the sample time comes from `counter_last`.
- Tests: `tests/test_sim_forensics_lifecycle.py` (21); the world gained real
  ACK/FILL quantities, one resting order in `gtc_orders.json` and a zero
  `engine.rejects` counter. `iso_ns` consolidated into `dataset.py`.
- Gaps for S1-style follow-up: pm-stats keeps no `reject_code`, no
  `quote_id` on order rows, no `cancelled_order_id` on OCO_CANCEL rows, no
  stop price / display qty — each one forced an inference or a deferral here.

### S5 — Checks D

Extend the replay `Detector` with a reconstructed book per symbol and the
D1–D8 oracles. Needs a run made after S1.

**Done 2026-10-24 (changed: no `Detector`):** `tools/sim_forensics/audit.py`
(streaming line reader) and `checks/matching.py` (D1–D9, C7). The run of
2026-10-24 (engine start 2026-10-23 18:29 → close 2026-10-24 16:05, one full
session) has a complete audit: 36 × 256 MB, 14.6 M lines, first line the
engine's `system.startup_recovery`. Result: everything PASS except **D7
FAIL 12 (X9)**; 3.9 min for all 28 checks, ~2.5 min of it the replay.

- Why not `pm-audit-replay`'s `Detector`: on one 256 MB file it builds a
  750 MB index in a minute and then crashes (X10), so ~25 GB of index for
  the run; and its episodes model one order's life, not a book. The replay
  instead streams the files once: pm-audit has one SUB on the engine's PUB,
  and the engine republishes each inbound command, so file order is engine
  order and `chain` delimits a dispatch.
- Model: a per-symbol book rebuilt from acks, trades, cancels and expiries,
  plus an independent model of the matching rules — price-time priority,
  iceberg slices refilling at the back, stop/trailing-stop checkpoints after
  each matching step (the engine's cascade order; trailing stops ratchet at
  every checkpoint), STOP→MARKET / STOP_LIMIT→LIMIT conversion, M2 trigger
  on entry, the uncross equilibrium (max volume, least surplus, lowest
  price) with the stop cascade after it. Orders removed anywhere in a
  dispatch are excused from "who should have traded first" (the stream does
  not order a cancel against the trades). Tick sizes and SMP defaults come
  from `ref_data/engine_config.json`; trade counts by symbol need no stores.
- The oracle for the model itself is the engine's full-book snapshot
  (`book.<SYM>`, every level): **D9 compared all 4 061 328 snapshots and
  every fill's `remaining_qty` — none differ**, over 2 551 121 dispatches,
  563 282 trades (all), 588 uncrosses with prints, 11 195 stop triggers. So
  every other D check ran against an exact book. D9 counts divergence
  *episodes* (first differing snapshot per symbol), the note all differing
  snapshots.
- Checks: D1 crossed engine snapshot in CONTINUOUS; D2 replayed book crossed
  after a dispatch (names the order that rested); D3 fill through the
  aggressor's limit; D4 fill not at the resting price or a better price
  resting; D5 an earlier order at the price passed over, or a fill size other
  than min(aggressor left, shown slice); D6 uncross: one price, = replayed
  equilibrium, = `auction.result`, both sides in priority, book uncrossed
  after; D7 continuous self-trade when the aggressor's SMP is not NONE
  (auction self-trades counted in the note: 182, X2); D8 price on the tick
  grid; C7 a stop the engine traded or cancelled without a replay trigger,
  and one the replay triggered that the engine left silent. Iceberg rules
  (the C7 sketch) are D5 + D9.
- Not covered: collars and circuit-breaker bands (none configured in this
  run), halts/reopen auctions, amends and combos (counted in the D9 note if
  a run has them), runs whose audit does not reach the engine start or that
  span an engine restart (both SKIPPED: restored GTC orders are not in the
  stream).
- A4 changed (check wrong, run 2026-10-24: 41): a closing uncross's prints
  trigger stops that match at once, still in CLOSING_AUCTION, as the order
  types chapter documents. A4 now allows a non-AUCTION print in an auction
  phase for a symbol that already printed in that phase's uncross, and
  counts them in the note.
- `make forensics` no longer ends in `make: *** Error 1` when a check
  fails: exit 1 is the tool saying "findings", which the target now reports
  in words (other exit codes still fail the target).
- Tests: `tests/test_sim_forensics_matching.py` (23) writes small audit
  tapes in pm-audit's line format: a consistent continuous day (stop
  cascade, iceberg refill), an opening auction, seeds + MM quote + OCO, and
  one planted violation per check, including the X9 shape.

### S6 — Check E

Depends on the differential-fuzz work (T3 of the matching workplan), which
builds the same OrderBook ↔ reference harness. Any divergence is shrunk
(delta-debug on the command list) to a minimal scenario.

### S7 — Checks F, G, H

### S8 — Triage

Work the ledger; spin out fix WPs.

## 8. Open questions

- **Q1** Audit retention: bigger rotation for the sim profile, or keep
  `book.*`/`depth.*` out of the audit (they are derived and reproducible by
  replay)? Recommendation: both configurable; sim profile records everything
  with enough space, because D1/F2/F3 use the book snapshots as the oracle.
  **Settled 2026-10-23:** configurable rotation only, no topic exclude.
- **Q2** Does SMP apply to the auction uncross (R4)? The spec must say so
  either way; today 123 auction self-trades happened.
- **Q3** Tool vs product: `tools/sim_forensics` (recommended now) or a
  `pm-forensics` CLI later once the checks have stabilised?
- **Q4** Should the checks also run continuously against a live sim (e.g. a
  periodic job, findings as pm-monitor events)? Recommendation: not before S8
  has shown which checks are stable and cheap.

## 9. Findings ledger

Finding ids are X*n* (the catalogue's E1–E4 are replay checks).

| ID | Found by | Run | Count | Classification | Status |
|---|---|---|---|---|---|
| X1 | B2 | 2026-10-23 | 749 orders, 95 132 qty | Engine bug | Fixed (v0.52.0); confirmed 2026-10-24: B1, B2, C2 PASS |
| X2 | R4 | 2026-10-23 | 123 auction self-trades (2026-10-24: 182) | Spec question (Q2) | Open |
| X3 | C2 (R5) | 2026-10-23 | 365 quote legs | Engine bug | Fixed (v0.52.0); confirmed 2026-10-24: C2 PASS, D4/D5/D9 PASS |
| X4 | R9, C4 | 2026-10-23 | 1 trade, 1 order | Recorder bug (pm-stats shutdown flush) | Open; not seen 2026-10-24 (sim stopped after the close) |
| X5 | C1 | 2026-10-23 | 4 107 FOK orders (2026-10-24: 5 161) | Engine bug or spec gap | Open |
| X6 | C6 | 2026-10-23 | 31 678 MM01 rejects (2026-10-24: 41 095, all of them) | Recorder gap (pm-stats) + label | Open |
| X7 | C4, C5 | 2026-10-23 | 3 423 OCO siblings (2026-10-24: 4 248) | Recorder gap (pm-stats) | Open |
| X8 | X1/X3 fix review | — | — | Engine oddities, not yet measured | Open (see below) |
| X9 | D7 | 2026-10-24 | 12 self-trades | Engine bug: OCO legs have no SMP action | Open |
| X10 | S5 | 2026-10-24 | — | Tool bug: `pm-audit-replay` fails on a 256 MB log | Open |

**X1 — triggered stop orders trade without an `order.fill`.** B2: 749 orders
traded but have no FILL event in pm-stats (traded − filled = +95 132; top
gateways AI082, AI020, AI045, AI069, AI033). Of these, the 700 that have an
ACK are all `STOP` (32) or `TRAILING_STOP` (668); the other 49 are MM01 quote
legs with the shape `CANCEL CANCEL` (C2). The audit window holds 8 of them,
and for all 8 the audit has `order.ack`, `order.cancelled` and
`trade.executed` but **no `order.fill`** — so the engine never published it,
pm-stats is not at fault. Example: AI082 `TRAILING_STOP` SELL 375 CCL
(`a028dbad…`) triggers at 12:34:59.616, trades 178 with MM01
(`000001-000456050`), remainder cancelled `INSUFFICIENT_LIQUIDITY` — and the
cancel is published 1 ms *before* the trade. Not every triggered stop is hit
(X3's example shows a triggered trailing stop whose fill *was* published), so
the condition is narrower — probably a stop triggered and then cancelled in the
same cascade. Hypothesis: such orders are missing from the dispatch's
matched-quantity map that `engine/main.py` uses to publish fills (cf. the
"finding #5" comment there). Next: failing engine test.

**X3 — a quote leg cancelled with `QUOTE_LEG_FILLED` still trades.** C2: 365
MM01 orders `CANCEL FILL+ CANCEL`. Decided from the audit (one causal chain,
12:35:05.773): AI036 SELL LIMIT 57 IR hits MM01's bid leg `3e25…` (trade
…171); the engine publishes `order.cancelled` for the ask leg `1d7f…`
(`QUOTE_LEG_FILLED`) and `quote.status INACTIVE_BID_FILLED`; AI096's
`TRAILING_STOP` BUY 49 (`db27…`) triggers in the same dispatch and **matches
the cancelled ask leg** (trade `000001-000456172`, 49 @ 201.35); a second,
reason-less cancel follows. So the leg is reported cancelled before it leaves
the book, and the stop cascade matches it. A real trade against an order its
owner was told is dead. Same area as X1 (stop cascades). Next: failing engine
test (quote + resting stop that the quote's first fill triggers).

**X4 — pm-stats loses its last messages at shutdown.** Clearing has trade
`000001-000456710`, stats does not; C4's single "live in order_events, not in
the book" order (`b0e1a2e6…`, AI062) is the order that trade filled — its
ACK reached pm-stats, its FILL did not.

**X5 — an FOK without liquidity is accepted, then rejected.** C1: 4 107
orders `ACK REJECT`, all `FOK`. The audit shows two `order.ack` for the same
order within 1 ms: `accepted: true`, then `accepted: false` with
`reject_code INSUFFICIENT_LIQUIDITY`. IOC/MARKET/STOP orders in the same
situation get one ACK and `order.cancelled` with `cancel_reason
INSUFFICIENT_LIQUIDITY`. Either the FOK should be rejected without a prior
acceptance, or cancelled like the others — a client cannot otherwise tell
which ack to believe. Spec decision needed.

**X6 — quote-cancel rejects are invisible in pm-stats.** C6: the engine
counted 31 678 rejects for MM01 (labelled `ORDER_NOT_FOUND`); pm-stats has
none. They are `quote.ack accepted=false "No active quote for symbol"` with an
empty `quote_id` (257 in the audit window); pm-stats skips events without an
id. Also: pm-stats records no `reject_code` at all, only reason text.

**X7 — OCO sibling cancels lose the cancelled order.** The engine reports a
sibling's cancel only as `oco.cancelled {oco_id, cancelled_order_id}` (as
documented); pm-stats stores it under `oco_id` and drops
`cancelled_order_id`, so 3 423 cancelled orders look live forever in
`order_events`. C4/C5 infer the closure from the group's OCO_CANCEL row.

### X1 / X3 fix (2026-10-23)

**X1 root cause.** Of the six loops in `engine/main.py` that publish a
dispatch's fills and cancels, only the new-order and amend loops published a
fill whenever the order *executed* ("finding #5"/C4). The quote-submit, seed
quote, combo-child and OCO-leg loops still chose the message by the order's
*final* status (`if status in FILLED/PARTIAL … elif CANCELLED`), so an order
that filled part and was cancelled for the rest in the same dispatch — a stop
converted to MARKET by the cascade — got only `order.cancelled`. The
auction-uncross stop loop also chose by final status and published no cancel at
all. The sim's case was the quote path (MM01 quotes are the most frequent
crossing input). Fix: in all five loops the fill branch keys on the quantity
matched in this dispatch, and the cancel/reject branch is an independent `if`;
the auction loop gains the missing cancel (with the combo/OCO follow-ups the
new-order path runs).

**X3 root cause.** `_on_quote_leg_filled` (inactivate the quote, cancel the
sibling leg) ran only in the publication loop, *after* `book.process()`
returned — but the stop cascade runs inside `process()`, so a stop triggered by
the leg's fill could still match the sibling. Fix: `OrderBook` calls a new
`on_quote_leg_fill` hook from `_apply_fill` for every continuous fill of an
order with a `quote_id`; the engine sets it to `_on_quote_leg_filled`, which is
idempotent, so the loops' later calls are no-ops. Message order changes: the
sibling's cancel and `quote.status INACTIVE_*` now precede the leg's
`order.fill` (they already did in the cascade case). Not called in an uncross
(`both_resting`), whose two-sided heap walk must not be mutated mid-way.

**Tests.** `tests/test_engine_cascade_publication.py`: one repro per path
(quote, OCO, combo, auction for X1; X3 plus the INACTIVATE_ON_FULL_FILL case
where the stop *may* buy the still-live ask), each also asserting the B1
oracle in-engine — every trade side gets exactly one `order.fill` naming that
trade. All failed before the fix (the auction case: the stop's owner heard
nothing at all) and pass after; the full suite was unaffected, so no existing
test covered these paths.

**X8 — seen while fixing, deliberately not changed:**

- Quote submission whose bid leg fills on entry: the engine inactivates the
  quote (`INACTIVE_BID_FILLED`), then still rests the ask leg and publishes
  `quote.status ACTIVE` — the X1 audit trace shows exactly this sequence.
- Quote legs filled *in an uncross* are not inactivated by the hook (see
  above); whether the uncross path inactivates them at all is unchecked.
- The auction stop loop prices fills at `book.last_trade_price`, not the
  order's own VWAP (H6) as every other loop does.
- Six near-identical publication loops are the reason X1 survived the
  "finding #5" fix; consolidating them on one helper (the shape of
  `_publish_amend_rematch`) is worth a WP of its own.

**X9 — OCO legs trade with their owner despite SMP.** D7, run 2026-10-24:
12 continuous self-trades, all with an OCO **STOP leg** as the aggressor
against its owner's resting LIMIT order; every gateway involved is
configured `CANCEL_AGGRESSOR`. Example (chain `01M5PD2ZHKE2NBR31V7PZGZQJ6`,
MA, 07:30:31Z): AI017's buy prints 64.76, which triggers AI057's sell stop
and then AI037's OCO stop leg `00a4435c…`, which sells 5 @ 62.15 into
AI037's own bid `d49b804e…` (trade `000001-000015487`). Root cause:
`_handle_new_order` (and quotes, combo legs) resolve the order's SMP action
from the gateway default with `_resolve_smp_action`; `_handle_oco_order`
never does, so both legs carry `smp_action=None`, which `_sweep` treats as
`NONE`. All 12 are stop legs; a limit leg that crosses its owner's order
on entry should be exposed the same way (not seen in this run). Next: failing
engine test (an OCO stop leg triggered into its owner's bid must be
cancelled `SELF_MATCH_PREVENTED`), then resolve SMP for both legs.

**X10 — `pm-audit-replay` cannot read one rotated file of the sim
profile.** `pm-audit-replay --log-file audit.log.5 anomalies` (256 MB,
~390 k lines) builds a 750 MB episode index in about a minute and then fails
in `reader._events_for` with `sqlite3.OperationalError: too many SQL
variables`: `_hydrate` binds every episode id of the window into one
`IN (…)`, beyond SQLite's limit of 32 766. With the S1 rotation (256 MB ×
100) the tool cannot be used on a sim run's audit at all. Not needed by the
forensics (S5 streams the files itself); a fix chunks the `IN` list.

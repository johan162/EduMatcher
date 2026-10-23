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
| 1 | S1 | Close observability gaps found in recon (§2), then start a new long run | S0, Q1 | 1 d | ☑ (code; new run pending) | 2026-10-23 |
| 2 | S2 | `tools/sim_forensics/` skeleton: loader, check registry, report | S0 | 1 d | ☑ | 2026-10-23 |
| 3 | S3 | Checks A + B: cross-store trade identity, double-entry book-keeping | S2 | 1 d | ☑ | 2026-10-23 |
| 4 | S4 | Checks C: order lifecycle legality | S2 | 1 d | ☐ | |
| 5 | S5 | Checks D: matching correctness from audit episodes (missed / illegal matches) | S1, S2 | 2 d | ☐ | |
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
| C7 | Stops/trailing stops trigger only after a trade crossed the (trailing) stop price; icebergs: displayed ≤ peak, refill after peak exhausted. |

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
- R6 resolved → finding **E1** (ledger, §9).

### S4 — Checks C

Python over `orders`/`order_events`, ordered by audit order where available.
Decides R5.

### S5 — Checks D

Extend the replay `Detector` with a reconstructed book per symbol and the
D1–D8 oracles. Needs a run made after S1.

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

| ID | Found by | Run | Count | Classification | Status |
|---|---|---|---|---|---|
| E1 | B2 | 2026-10-23 | 749 orders, 95 132 qty | Engine bug (probable) | Open — triage in S8 |
| E2 | R4 | 2026-10-23 | 123 auction self-trades | Spec question (Q2) | Open |
| E3 | R5 | 2026-10-23 | 358 quote-leg orders | Undecided (ordering artefact or engine) | Open — C1 in S4 |
| E4 | R9 | 2026-10-23 | 1 trade | Recorder bug (pm-stats shutdown flush) | Open |

**E1 — triggered stop orders trade without an `order.fill`.** B2: 749 orders
traded but have no FILL event in pm-stats (traded − filled = +95 132; top
gateways AI082, AI020, AI045, AI069, AI033). Of these, the 700 that have an
ACK are all `STOP` (32) or `TRAILING_STOP` (668); the other 49 have no ACK
(not yet examined; MM01 among them). The audit window holds 8 of them, and
for all 8 the audit has `order.ack`, `order.cancelled` and
`trade.executed` but **no `order.fill`** — so the engine never published it,
pm-stats is not at fault. Example: AI082 `TRAILING_STOP` SELL 375 CCL
(`a028dbad…`) triggers at 12:34:59.616, trades 178 with MM01
(`000001-000456050`), remainder cancelled `INSUFFICIENT_LIQUIDITY` — and the
cancel is published 1 ms *before* the trade. Hypothesis: orders that match in
a stop-trigger cascade are not in the dispatch's matched-quantity map that
`engine/main.py` uses to publish fills (cf. the "finding #5" comment there).
Next: failing engine test with a resting trailing stop triggered by another
order's trade.

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
| 6 | S6 | Check E: full replay differential (engine re-run; reference part covered by S5) | S5 | 2–3 d | ☑ | 2026-10-24 |
| 7 | S7 | Checks F–H: derived data, persistence, ops-signal correlation | S2 | 1.5 d | ☑ | 2026-10-24 |
| 8 | S8 | Triage of all findings; each confirmed bug → regression test + fix WP | S3–S7 | open | ☑ | 2026-10-24 |
| 9 | S9 | Fix X5: an unfillable FOK gets one rejecting ack | S8 | 0.5 d | ☑ | 2026-10-24 |
| 10 | S10 | Fix X8a: a quote that trades on entry follows its refresh policy; new check C8 | S8 | 1 d | ☑ | 2026-10-25 |
| 11 | S11 | pm-stats recorder fixes X4, X6, X7 (+ `reject_code` column, fresh stats.db) | S8 | 1 d | ☑ | 2026-10-25 |
| 12 | S12 | Fix X10: `pm-audit-replay` chunks its `IN` lists | S8 | 0.25 d | ☑ | 2026-10-25 |
| 13 | S13 | X8b/X8c: measure, then fix, uncross quote legs and auction-stop fill prices | S8 | 1 d | ☑ | 2026-10-25 |
| 14 | S14 | Run 2026-10-25 (C5, C6 FAIL): X15 engine OCO sibling inside a cascade; X16 C5/C6 check fixes; X17 OCO entry | S13 | 0.5 d | ☑ | 2026-10-25 |
| 15 | S15 | X8d: one publisher for every `book.process()` result; X12, X18–X20 | S14 | 1 d | ☑ | 2026-10-25 |
| 16 | S16 | X21: a combo leg ending on entry fails the combo; `combo.ack` first | S15 | 0.5 d | ☑ | 2026-10-26 |
| 17 | S17 | A5 audit completeness (per-topic `seq` gaps) + H5 feature-coverage matrix | — | 0.5 d | ☑ | 2026-10-28 |
| 18 | S18 | Direct checks on today's data: C9 IOC/FOK/MARKET, C10 quote replace, D10 auction indicative, F6 depth fields | S17 | 1 d | ☑ | 2026-10-28 |
| 19 | S19 | Re-run differentials: E5 symbol isolation, E6 crash recovery, E7 metamorphic | — | 2 d | ☑ (E6: X23–X26 for triage) | 2026-10-28 |
| 20 | S20 | Pre-1.0 decisions: Q5–Q10, frozen field list for audit, bus and DBs (doc only) | S17–S19 | 0.5 d | ☑ | 2026-10-28 |
| 20b | S20b | Restart contract: fix X23–X26 (OCO links, last price, no recovery uncross, priority order) and X27 | S20 | 1 d | ☑ | 2026-10-28 |
| 21 | S21 | Self-describing audit: `system.startup` (version, sha, config) + audit format header | S20b | 1 d | ☑ | 2026-10-28 |
| 22 | S22 | Execution messages: integer ticks; cum qty / avg price / remaining on every report; priority seq | S20 | 1.5 d | ☑ | 2026-10-28 |
| 23 | S23 | Global engine sequence; trade context (`match_type`, `auction_id`, `trigger_order_id`) | S20 | 1 d | ☐ | |
| 24 | S24 | Explicit engine events: `order.triggered`, trailing ratchet / iceberg refill trace; collar band publication | S20 | 1.5 d | ☐ | |
| 25 | S25 | Book checkpoints at startup/recovery, phase changes, EOD; replay starts from a checkpoint | S22–S24 | 2 d | ☐ | |
| 26 | S26 | Stores: EOD archive of state files (+ G3), audit link keys in stats/clearing, order ids in `trade_log` | S20 | 1 d | ☐ | |
| 27 | S27 | Sim feature coverage: amend, combos, ATC, explicit SMP, bands/CB, halts, kill switch, one restart | S17 | 1.5 d | ☐ | |
| 28 | S28 | Replay models amend, combos, circuit breaker/halts; D8 checks bands; C7/D5 use explicit events | S24, S27 | 2 d | ☐ | |
| 29 | S29 | Long run on the 1.0 formats, full report, triage; then freeze | S21–S28 | open | ☐ | |

Total ≈ 10 d plus fix WPs. S0 is **urgent** (see §2, R3: order events are
pruned after 12 h). S17–S29 (≈ 16 d plus triage) are the pre-1.0 extension,
see §10: after 1.0 the audit, bus and DB formats freeze.

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
| A5 | (S17) The audit is complete: per topic, `seq` runs 1, 2, 3 … without gap or repeat within one engine start (after S23: the global engine sequence too). Every other audit check assumes this. |

### B — Double-entry book-keeping

| ID | Check |
|---|---|
| B1 | Each trade has exactly one buy-side and one sell-side FILL whose order ids, qty and price match the trade (needs R2 fixed or audit). |
| B2 | Per order: Σfill_qty = Σ qty of the trades it is a side of (finer than per (symbol, gateway); needs no trade ids); localises R6. |
| B3 | Recompute `gateway_symbol_positions` from `trade_events` (net qty, buy/sell qty, notional, avg cost, realised P&L) and compare exactly. |
| B4 | `gateway_daily_summary` = aggregate of B3 per trade date. |
| B5 | Per symbol Σnet_qty = 0; Σbuy_notional = Σsell_notional; Σrealised P&L + Σunrealised P&L = 0 at a common mark (zero-sum market). |
| B6 | metrics `daily_totals` (restart-corrected) vs. rows, within a 15 s reporting slack of `counter_last.ts`: `engine.trades` per symbol = trades; `engine.fills` per gateway = trade sides (the engine counts one per side, not per FILL message); `clearing.trades_settled` = trade_events by ingest time. `stats.events_recorded` and `audit.records` deferred (no row set to count them against yet). |
| B8 | Each FILL's `fill_qty` and `fill_price` are the total and the VWAP (integer notional, divided once, as the engine does) of the trades its `trade_ids` names (finding X14). |
| B7 | Loss/error counters never above 0 (`stats.records_dropped`, `stats.feed_gaps`, `audit.decode_errors`, `health.beacons_dropped`, `health.samples_rejected`, `monitor.*_invalid`, `monitor.*_errors`); `stats.feed_gaps` table empty. |

### C — Order lifecycle

| ID | Check |
|---|---|
| C1 | Event sequence per order is legal (grammar per order type, quotes and OCO). Ordering by audit `msg` ULID / per-topic `seq`, not by pm-stats receive order (R5). |
| C2 | Nothing after a terminal event (FILLED, CANCELLED, EXPIRED, REJECTED). |
| C3 | `remaining_qty = qty − cumulative fill` at every FILL; final status consistent with remaining. |
| C4 | Every ACKed order ends terminal, or is still resting at the cut; resting GTC orders = `gtc_orders.json`; DAY orders all EXPIRE at close. |
| C5 | OCO: no leg fills after its sibling ended (filled, or cancelled for a reason of its own — not the OCO rule's X7 row); a done leg ends its sibling. Quotes: leg-filled semantics (R5). Combos: legs fill together. |
| C6 | Reject / cancel reason codes are canonical (not the X7 OCO sibling rows, which carry `oco.cancelled`'s free text); reject-rate time series per code (spikes → H). |
| C8 | Quote lifecycle from the audit: no `ACTIVE` after a quote ended, no status before its ack, and an inactivating fill cancels the sibling leg in the same dispatch, after which it never trades (S10, finding X8a). |
| C7 | Stops/trailing stops trigger only after a trade crossed the (trailing) stop price; icebergs: displayed ≤ peak, refill after peak exhausted. **Moved to S5**: `order_events` stores neither stop prices nor display quantities; needs the audit. |
| C9 | (S18) IOC, FOK and MARKET end within their own dispatch (chain) and never rest; a FOK fills completely or not at all (or, accepted, ends CANCELLED `SELF_MATCH_PREVENTED` with no fill — the documented SMP case, see S17). |
| C10 | (S18) One quote per (gateway, symbol): when a quote is accepted no earlier leg of that gateway and symbol is live (the engine cancels them `QUOTE_REPLACED` first, a filled leg's remainder included), and a replaced leg never trades. |

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
| D8 | All prices on the tick grid; trades inside collar / circuit-breaker bands; halts honoured. (Built: tick grid only; bands and halts in S28, after S24 publishes the bands.) |
| D10 | (S18) Each `auction.indicative.*` (price, executable qty, imbalance qty and side) equals the uncross the replayed book makes at that point of the stream. ("`auction.result` = last indicative" dropped: D10 + D6 imply it.) |

### E — Replay differential

| ID | Check |
|---|---|
| E1 | Extract inbound commands (`order.new`, `order.cancel`, amends, `quote.*`, `order.oco`, session changes) from the audit in engine arrival order (`arrival_seq` / ULID). |
| E2 | Replay into a fresh `OrderBook` (canonicalise ids and timestamps as in the System-Trading-Verification doc §9); diff trades, acks, rejects. A diff here means non-determinism or a hidden input (time, collar state). |
| E3 | Replay into `tests/reference_matcher.py`; diff trade-for-trade. A diff here is a matching bug on one side — shrink it to a minimal scenario and add it to the matching test suite. **Not built (S6 decision):** the reference has no quotes, OCO or sessions; S5's replay is the independent model on the real stream, and the reference differential stays with T3 of the matching plan. |
| E4 | Final replayed book vs `gtc_orders.json` and the last `book.*` snapshots. |
| E5 | (S19, slow) Symbol isolation: each symbol's commands re-run alone equal that symbol's part of the full re-run (cross-symbol commands — OCO, kill switch, halt-all — grouped or left out). |
| E6 | (S19, slow) Crash recovery: persist the re-run engine at random command k with its own persistence code, restore a fresh engine from it, continue; the output equals the uninterrupted re-run. |
| E7 | (S19, slow) Metamorphic: renaming gateway and client ids gives the same trades; shifting every price of a symbol by k ticks (away from bands) gives the same trades shifted by k. |

### F — Derived data and market data

| ID | Check |
|---|---|
| F1 | `daily_stats` OHLCV/turnover/VWAP from `trade_log` (passes today; keep as regression). |
| F2 | `price_snapshots` best bid/ask equal the audit book at the same instant. |
| F3 | `book.*` `last_price`/`last_qty`/`recent_trades` consistent with `trade.executed`. |
| F4 | `book_stats.json` `prev_close` = previous day's `close_price`. |
| F5 | Index levels recomputable from constituent prices (once R7 is fixed). **Not built (S7 decision):** the s300-sim profile defines no index (R7), so there is no data to check; build it with the first run that has indexes. |
| F6 | (S18) `depth.*` derived fields (mid, bid/ask depth within tolerance, imbalance, microprice, cost to move) recomputed from the `book.*` snapshot of the same instant. |

### G — Persistence

| ID | Check |
|---|---|
| G1 | `gtc_orders.json` contains no terminal orders; `remaining_qty` matches the last FILL; ticks match `tick_decimals`. (Built per entry; "matches the last FILL" is C4's, and E4 compares the whole book.) |
| G2 | `run_seq` in trade ids matches `engine_run_seq.json`; on a run with a restart, no trade id reused and resting orders survive. |
| G3 | **Planned (S26).** Cross-day continuity: the archived EOD state of day N (resting GTC orders, combos, `book_stats.json`) is exactly what the engine recovers at the start of day N+1. |

### H — Ops-signal correlation and statistics

H checks report **INFO** (S7 decision): a count of pointers, never a FAIL.

| ID | Check |
|---|---|
| H1 | For every finding from A–G, list ops events within ±30 s (metrics `events`: thresholds, process status, connects; `gateway_sessions` disconnects; log.db WARN/ERROR). Clusters point at load-related bugs. |
| H2 | Per-agent outliers: P&L, fill ratio, reject rate, cancel-to-fill; per-symbol: spread, price jumps > k·σ without a news event (`market_sim_news.db`). |
| H3 | Latency (`engine.handle_us_*`) vs book size / garbage — not a correctness check, but feeds the perf plan. |
| H4 | How far and how fast prices follow the value model's jumps (`market_sim_news.value_jumps`, added 2026-10-26). |
| H5 | (S17) Feature coverage: counts per order type × TIF × SMP mode × phase × outcome, and per engine feature (amend, combo, OCO, quote, auction, band reject, halt, kill switch, restart). A zero marks a feature whose checks passed vacuously. |

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

**Done 2026-10-24 (changed: engine re-run, no reference):** decided with the
maintainer to build E1, E2, E4 as a re-run of the whole `Engine` and leave
E3 to T3 (see the catalogue). `tools/sim_forensics/checks/rerun.py`.

- Input: the engine echoes every inbound command into the audit before
  handling it (`Engine._echo_command`; queries and heartbeats excepted), so
  the audit *is* the engine's input. The re-run builds an `Engine` from the
  run's compiled `ref_data/engine_config.json` — the container engine reads
  the compiled artifact, not the YAML; the YAML seeds the books in a
  different symbol order — with fake sockets, runs `_restore_gtc` and
  `_load_config` as `run()` does, and calls `_dispatch_pull_message` for
  each echoed command. 2 550 622 commands, ~6 min.
- Comparison per command chain, all messages but market data and replies;
  clock fields dropped. Engine-generated order ids (seed, quote and OCO legs)
  and trade ids are bound live ↔ re-run where first named (the trade counter
  is global, so one extra or missing trade would otherwise shift every later
  id); 8-hex id prefixes in reason text are mapped too. A symbol whose
  outputs differed is one *episode* until the re-run's `book.snapshot()`
  (levels and last price) equals the next live `book.<SYM>`. Armed stops
  are not in a snapshot, so an episode can end early and recur: of the 15
  HEAD episodes that are not the ack field, 11 are the X9 dispatches and 4
  later ones in FSLR/FANG, where an OCO stop leg X9 had left armed or gone.
- **Result with the run's own engine (v0.52.0, via a worktree on
  `PYTHONPATH`): E1, E2, E4 PASS, twice.** The live run is fully reproducible
  from its commands: no hidden input (no silent-gateway expiry, no timer
  touched an order), no non-determinism in matching, and the re-run ends
  with exactly `gtc_orders.json`. The only difference is X11 (message
  order), which the comparison tolerates and counts.
- With the current engine, E2 shows the code change since the run:
  28 096 episodes, almost all the X9 fix's `smp_action` on OCO leg acks, and
  the self-trades X9 no longer makes. So E2 doubles as a behaviour-change
  report between releases; the note names both versions (the source commit,
  since the package version does not move between releases) and groups
  episodes by their first difference. For a determinism verdict, re-run with
  the run's engine version.
- A tool bug found on the way: a quote replacement cancels the old legs in
  set order (X11) and a new leg not yet bound; aligning only fully-bound
  batches cross-bound the legs in 3 of 2.5 M commands, depending on the hash
  seed. Fixed by aligning bound ids to their live position and filling the
  rest in order.
- Tests: `tests/test_sim_forensics_rerun.py` (5) records a short run of a
  real Engine on the s1-basic example as audit lines (commands echoed first)
  and plants one violation per check.

### S7 — Checks F, G, H

**Done 2026-10-24:** F2–F4 in `checks/derived.py`, G1–G2 in
`checks/persistence.py`, H1–H3 in `checks/ops.py`. F5 not built (no index in
the sim profile). Decided with Johan: H checks report a new **INFO** status
(oracle `statistical`), which never fails a run.

- F2 and F3 share one audit pass (`market_pass`, 37 s on the 9 GB run; a book
  line is parsed only when a row's window or a new trade needs it). G2 reads
  its engine starts from the same pass. `audit.Line` gained `ts`.
- **F2**: each `price_snapshots` row equals one `book.<SYM>` message whose
  `ts_ns` (engine publish time) falls in [row − 5 s, row + 1 s). The audit
  line's own time is pm-audit's write time and can trail pm-stats's receipt,
  so it only pre-selects messages. The first version keyed on it and missed
  2 rows. `mid` and `pct_change` must follow from the row and the symbol's
  previous row. `daily_stats` `open_bid`/`open_ask` are the date's first
  non-empty best bid and ask; `close_bid`/`close_ask` are checked against
  `system.eod` when the audit has one.
- **F3**: per symbol, in publish order: `last_price`/`last_qty` = last trade;
  `last_buy_price`/`last_sell_price` = last BUY-/SELL-aggressor trade (auction
  prints move neither, L9; the startup values are restored, so they are taken
  from the first snapshot); `recent_trades` = the last five trades, every
  field. A wrong snapshot is reported once, and the replay then takes the
  engine's values.
- **F4**: `book_stats.json` against `trade_log`'s last trades; flags an empty
  `prev_close` for a symbol `daily_stats` has closed before.
- **G1** checks each persisted order (live status, quantities, the prices its
  type needs, `tick_decimals` vs `instruments`) and combo (live, GTC).
  Cross-store agreement stays with C4 and E4.
- **G2**: no trade id above `engine_run_seq.json`; run_seq never falls in
  trade-time order; trades after the audit's last engine start carry it.
- **H1** places each failed check's first 50 samples in time from the keys
  they carry (`ts`, `chain` ULID, `trade_id`, `order_id`). It lists metrics
  events, clearing disconnects and log.db warnings within ±30 s, and reports
  the share of the run that is near some event (the chance level).
  `registry.failed_outcomes` keeps the uncapped outcomes; checks run in id
  order, so A–G are done before H1.
- **H2**: robust z (median/MAD) > 5 within a gateway kind (AI*, MM*, TRADER*)
  for P&L, fill ratio, reject rate and cancel-to-fill. A jump is a
  continuous print more than 5 % from the prevailing price (the median of
  the symbol's last 20 trades that day), counted once per excursion, unless
  symbol or market news came in the previous 15 min. Spread outliers across
  symbols use the median relative spread. `market_sim_news.db` is now an
  attached store. The catalogue's "k·σ" rule was tried first and dropped:
  the tape is bid-ask bounce (a one-tick median move, a spread-wide move at
  every crossing), and 10 σ flagged 19 025 ordinary crossings.
  Since 2026-10-26 a jump counts only if it lasts: the median of its print
  and the next 19 that day is still more than 5 % off (reverted jumps are
  only counted in the note). On the 2026-10-26 run 127 of 148 reverted:
  one print into a thin book, mostly an AI agent's OCO take-profit leg
  resting 5–10 % away, hit by a LIMIT/IOC at that price or a triggered stop,
  120 of them in the first 10 min after the open; 21 lasted. Of those, 16
  are the opening minutes' whipsaw: 20 prints span seconds there, and most
  return the price to the opening auction's after the first trades drifted
  off it. The other 5 (BABA, CRWD, TSLA, HUBB, MCO) are new levels that
  MM01 quotes into (7–14 of the next 20 prints) and that the market sim's
  end-of-day true value confirms: unannounced jumps of its value model
  (0.05/day/symbol, σ 4 %: ~3 jumps > 5 % a day expected over 300 symbols).
- **H3**: per minute, the engine p99 against msgs_in, resting orders, heap
  garbage, busy %, GC gen2 and host CPU (Spearman); spikes are > 10× the
  median minute.
- Tests: `tests/test_sim_forensics_market.py` (15),
  `test_sim_forensics_persistence.py` (12), `test_sim_forensics_ops.py` (8).
  Each plants one violation; the F tests use their own small audit tape.
- **Results on the 2026-10-24 run** (full suite 15 min, of which the F/G
  pass is 37 s): F1–F4, G1, G2 PASS. F2 covers 26 400 snapshot rows and
  both days' open bid/ask; F3 covers 4 061 328 book messages. The other
  checks are as before (C1 5161 X5, C6 1 X6, D7 12 X9, E2 28 094 with HEAD).
  Report: the scratchpad copy of the run, not yet in `forensics/2026-10-24/`.
  - H1 INFO 76: 366 ops events, and 20 % of the run lies within 30 s of one
    (the chance level). Near events: C1 21 of 50 timed samples (42 %), D7 5
    of 12, E2 50 of 50. The E2 samples are the run's first X9 OCO acks, at
    the CONTINUOUS transition (07:30:00.4), when engine p99 thresholds fire.
    C1 (X5) samples are near an event twice as often as chance: a hint for
    X5's triage, not evidence.
  - H2 INFO 123: 15 AI P&L outliers (±23–39 M against a median of −2.2 M;
    no fill/reject/cancel-rate outlier); 86 jumps, mostly in the first half
    hour after the open (thin books; the sim profile runs `--no-collars`),
    none explained by the 9 news events; 22 spread outliers.
  - H3 INFO 79: median p99 1.35 ms, 79 minutes > 13.5 ms (max 87 ms).
    Spearman with p99: resting orders +0.54, busy +0.49, msgs_in +0.45,
    host CPU +0.44, heap garbage +0.41, GC gen2 +0.05. Spikes also occur
    overnight at idle (01:38, 05:30: 600 resting, 3 % busy), so load alone
    does not explain them; this is for the perf plan.
- Observation: `daily_stats.close_bid/close_ask` are NULL for every symbol.
  That is correct, not a finding: the EOD books are empty because every DAY
  order has expired by then. pm-audit stops before the engine publishes
  `system.eod` (the audit has none), so F2 cannot check the close side on a
  sim run.

### S8 — Triage

Work the ledger; spin out fix WPs.

**Done 2026-10-24.** Every open item is classified from code, docs or a
repro on today's engine (probes against `tests/engine_harness.py`). Three
decisions were taken with Johan (X5, X8a, X6). Each confirmed bug is a fix
WP (S9–S13) that starts with the failing test and closes its ledger row.

| ID | Verdict | Evidence | Action |
|---|---|---|---|
| X2 | **Expected (documented)**: closes Q2 | Operator guide, risk controls: "SMP does not apply in an auction uncross … a gateway's crossing bid and ask in the same auction trade with each other." D7 already exempts uncross prints. | Close |
| X4 | Recorder bug, confirmed (2026-10-23) | pm-stats `_stop` clears `_running`, and the receive loop exits with messages still queued on its SUB socket (2026-10-24: "EOD received" logged after "stopped"). | S11: drain the SUB socket before closing |
| X5 | **Engine bug** (decision: the engine follows the docs) | Participant guide, order types: "an unfillable FOK is *rejected* … rather than accepted and cancelled". The engine publishes `accepted=true` before `book.process()`, then `accepted=false`; reproduced today. | S9 |
| X6 | Recorder gap, confirmed (decision: add `reject_code`) | `_on_order_event` drops events without an id (`quote.ack` "No active quote for symbol" has an empty `quote_id`); no `reject_code` column. | S11: record them, keyed on (gateway, symbol); add `reject_code`; fresh stats.db, no migration |
| X7 | Recorder gap, confirmed | `oco.cancelled` is stored under `oco_id`; `cancelled_order_id` is dropped. | S11: also a CANCEL row for the cancelled leg; C4/C5 lose their inference |
| X8a | **Engine bug** (decision: apply the refresh policy) | A quote whose bid fills on entry publishes `INACTIVE_BID_FILLED`, the fills, then `quote.ack` and `quote.status ACTIVE`, and rests the ask: against "INACTIVATE_ON_ANY_FILL: sibling leg cancelled, quote removed" (participant guide, MM quotes). Reproduced today. No check sees it. | S10: ack first; under ANY_FILL the sibling does not rest and the last status is `INACTIVE_*`; add check **C8** (no quote leg rests or trades after its quote's `INACTIVE_*`; no `ACTIVE` after `INACTIVE_*` in one dispatch) |
| X8b | Unmeasured | Quote legs filled in an uncross are not inactivated by the X3 hook. | S13: test first |
| X8c | Suspected | The auction stop loop prices `order.fill` at `book.last_trade_price`, not the order's own VWAP. B1 passed on both runs, so it has not happened yet. | S13: test (a stop the uncross triggers sweeps two levels) |
| X8d | Refactor | Six near-identical publication loops. | Its own WP after S9/S10/S13, which touch them |
| X10 | Tool bug, confirmed | `reader._hydrate` and the links query bind every id into one `IN (…)`. | S12 |
| X11 | Fixed (5b8a5f5f) | | Confirm on the next run |
| H1 | Pointer | C1/X5 samples sit near ops events at 2× chance. | Re-read after S9 |
| H2 | Not a bug | P&L outliers are agent behaviour. Jumps cluster after the open in thin books, and the sim runs `--no-collars`. | None. Revisit if a run with collars still jumps |
| H3 | Perf pointer | p99 spikes also at idle overnight (600 resting, 3 % busy) | Perf plan |

Fix order: S9 and S10 (engine, small, both change what clients see), then
S11, S12, S13. The next long sim run comes after S11, so that it starts
with the fresh stats.db and every fix in place, and confirms X9, X11, X5,
X8a and X4–X7 together.

## 8. Open questions

- **Q1** Audit retention: bigger rotation for the sim profile, or keep
  `book.*`/`depth.*` out of the audit (they are derived and reproducible by
  replay)? Recommendation: both configurable; sim profile records everything
  with enough space, because D1/F2/F3 use the book snapshots as the oracle.
  **Settled 2026-10-23:** configurable rotation only, no topic exclude.
- **Q2** Does SMP apply to the auction uncross (R4)? The spec must say so
  either way; today 123 auction self-trades happened. **Settled (S8):** the
  operator guide already says it does not (risk controls, SMP rules); X2
  closed as expected.
- **Q3** Tool vs product: `tools/sim_forensics` (recommended now) or a
  `pm-forensics` CLI later once the checks have stabilised?
- **Q4** Should the checks also run continuously against a live sim (e.g. a
  periodic job, findings as pm-monitor events)? Recommendation: not before S8
  has shown which checks are stable and cheap.

Pre-1.0 questions (§10), settled with the maintainer in S20 (2026-10-28),
each as recommended:

- **Q5** Engine-side input journal? The audit is a PUB/SUB tap (pm-audit's
  SUB, `_SUB_RCVHWM = 200_000`): best effort, and A5 can only *detect* a
  loss. E2 shows the engine is deterministic, so a sequenced inbound
  command journal written by the engine (batched fsync) would make the
  record complete by construction, at some hot-path cost. Recommendation:
  decide before 1.0 — it is the one change that is hard to add after the
  freeze; if no, A5 is the guard.
  **Settled: no.** A5 is the guard (no loss on the 2026-10-28 run); a journal can come later as a new file without touching a frozen format.
- **Q6** Global engine sequence: in addition to the per-topic `seq`, or
  replacing it? Recommendation: in addition (subscribers that filter topics
  still need per-topic gap detection); one more envelope frame field.
  **Settled: in addition** to the per-topic seq.
- **Q7** Stop triggers, trailing ratchets and iceberg refills: client-visible
  messages, or an audit-only trace topic? Recommendation: `order.triggered`
  client-visible (it is what a participant needs, cf. FIX ExecType=L);
  ratchet and refill on an audit-only `engine.trace.*` topic.
  **Settled:** `order.triggered.<GW>` to clients; ratchets and refills audit-only (`engine.trace.<SYM>`).
- **Q8** Prices on the bus: add `*_ticks` beside the display floats, or
  replace the floats? Recommendation: add ticks as the canonical value,
  keep the floats as display only (the GUIs show them as is). No migration
  either way: fresh stores.
  **Settled:** add integer `*_ticks`, canonical; the floats stay, display only.
- **Q9** Book checkpoints: phase boundaries, startup/recovery and EOD only,
  or also every N minutes? Size is ~one `gtc_orders.json` per checkpoint.
  Recommendation: the events only; add a period later if replay start-up
  time demands it (that is not a format change).
  **Settled: events only** (startup/recovery, phase change, EOD).
- **Q10** E3 (reference matcher differential): build it on the chains the
  reference supports (no quote, OCO, combo, auction), now that T3 of the
  matching plan is done, or leave it? Recommendation: leave it; E5–E7 give
  more for the effort.
  **Settled: not built** (E5–E7 cover more).

## 9. Findings ledger

Finding ids are X*n* (the catalogue's E1–E4 are replay checks).

| ID | Found by | Run | Count | Classification | Status |
|---|---|---|---|---|---|
| X1 | B2 | 2026-10-23 | 749 orders, 95 132 qty | Engine bug | Fixed (v0.52.0); confirmed 2026-10-24: B1, B2, C2 PASS |
| X2 | R4 | 2026-10-23 | 123 auction self-trades (2026-10-24: 182) | Expected: SMP does not apply in an uncross (documented) | Closed (S8) |
| X3 | C2 (R5) | 2026-10-23 | 365 quote legs | Engine bug | Fixed (v0.52.0); confirmed 2026-10-24: C2 PASS, D4/D5/D9 PASS |
| X4 | R9, C4 | 2026-10-23 | 1 trade, 1 order | Recorder bug (pm-stats shutdown flush) | Fixed 2026-10-25 (S11); confirmed 2026-10-25: A1 nothing beyond the cut, C4 PASS |
| X5 | C1 | 2026-10-23 | 4 107 FOK orders (2026-10-24: 5 161) | Engine bug (against the participant guide) | Fixed 2026-10-24 (S9); confirmed 2026-10-25: C1 PASS |
| X6 | C6 | 2026-10-23 | 31 678 MM01 rejects (2026-10-24: 41 095, all of them) | Recorder gap (pm-stats) + label | Fixed 2026-10-25 (S11); confirmed 2026-10-25: C6's reject reconciliation finds nothing |
| X7 | C4, C5 | 2026-10-23 | 3 423 OCO siblings (2026-10-24: 4 248) | Recorder gap (pm-stats) | Fixed 2026-10-25 (S11); confirmed 2026-10-25: C4/C5 infer 0. Its rows tripped C6 (X16) |
| X8 | X1/X3 fix review | 2026-10-24 (C8) | X8a: 40 898 quotes, 6 212 trades against a dead sibling | X8a/b/c engine bugs; X8d refactor | X8a fixed (S10), X8b/c (S13); confirmed 2026-10-25: C8, B8 PASS. X8d done 2026-10-25 (S15, uncommitted) |
| X9 | D7 | 2026-10-24 | 12 self-trades | Engine bug: OCO legs have no SMP action | Fixed 2026-10-24 (4fa2b4be); confirmed 2026-10-25: D7 PASS |
| X10 | S5 | 2026-10-24 | — | Tool bug: `pm-audit-replay` fails on a 256 MB log | Fixed 2026-10-25 (S12, uncommitted) |
| X12 | S9 review | — | — | Engine: book rejects of combo children / OCO legs (code, sibling) | Fixed 2026-10-25 (S15, uncommitted) |
| X14 | S13 | 2026-10-24 | 23 fills (B8) | Check gap: B1 does not compare a fill's price with its trades' VWAP | Fixed 2026-10-25: new check B8; 2026-10-25 run: PASS, 933 670 fills |
| X13 | S12 run of `pm-audit-replay` | 2026-10-24 | 3 in `audit.log.5` | Tool bug: a rejected cancel read as the order turning REJECTED | Fixed 2026-10-25 (uncommitted) |
| X11 | E2 | 2026-10-24 | ~6 400 cancel batches | Engine non-determinism (message order only) | Fixed 2026-10-24 (5b8a5f5f); confirmed 2026-10-25: E2 0 reordered batches |
| X15 | C5, E2 | 2026-10-25 | 196 OCO groups (10 traded both legs) | Engine bug: an OCO sibling pulled only after `book.process()`, and never from the quote-submit loop | Fixed 2026-10-25 (S14, uncommitted); confirm on next run (C5) |
| X16 | C6, X15 | 2026-10-25 | 4 622 rows (C6) | Check gaps: C6 read X7 rows' free text as cancel reasons; C5 checked only a FILLED sibling | Fixed 2026-10-25 (S14, uncommitted) |
| X17 | X15 review (probe) | — | not in a run | Engine bug: leg 2 of an OCO is posted after leg 1 filled on entry, and a breached stop leg trades at once | Fixed 2026-10-25 (S14, uncommitted) |
| X18 | S15 (probe) | — | not in a run | Engine bug: the OCO path ignores a symbol halt and matches its legs | Fixed 2026-10-25 (S15, uncommitted) |
| X19 | S15 (probe) | — | not in a run | Engine bug: an OCO's own group was exempt from the book hook while posting, so a cascade from leg 2's fill on entry could fill leg 1 | Fixed 2026-10-25 (S15, uncommitted) |
| X20 | S15 | every run | every non-new-order fill | Engine drift: `order.fill` lacked `price` outside the new-order path, and `tif`/`is_seed` on it | Fixed 2026-10-25 (S15, uncommitted) |
| X21 | S15 (probe) | — | not in a run | Engine: a combo whose child ends while the combo is being accepted (rejected, or cancelled by SMP) is never failed; its other legs rest on | Fixed 2026-10-26 (S16, uncommitted) |
| X22 | D9 | 2026-10-26 | 2 dispatches (4 rows) | Check bug: the replay's stop cascade ran the next trade's aggressor first, not the engine's FIFO order, so a triggered stop-limit that only rested was missing when a later stop traded into it | Fixed 2026-10-26 (uncommitted) |
| X23 | E6 | 2026-10-28 | every restart with a live OCO | Engine: `_restore_gtc` does not rebuild `_oco_groups`; a restored OCO leg that fills leaves its sibling live | Fixed 2026-10-28 (S20b); E6 on the 2026-10-28 run: 26 restarts, 0 differences |
| X24 | E6 | 2026-10-28 | every traded book at a restart | Engine: `book_stats.json` holds the last trade price (`prev_close`) but the restore sets only the last buy/sell prices; `last_trade_price` stays None (collar reference, a new trailing stop's trigger, depth) until the next trade | Fixed 2026-10-28 (S20b); E6 on the 2026-10-28 run: 26 restarts, 0 differences |
| X25 | E6 | 2026-10-28 | restart 1 (PRE_OPEN): 825 trades, all 300 books | Engine: the restore's M3 RECOVERY uncross runs whatever the phase, so a restart during pre-open or an auction call prints the collected book before the auction | Fixed 2026-10-28 (S20b); E6 on the 2026-10-28 run: 26 restarts, 0 differences |
| X26 | E6 | 2026-10-28 | 2 books at a restart in CONTINUOUS | Engine: the checkpoint lists orders in `_order_index` (first-arrival) order and the restore re-queues them so; a refilled iceberg (and any order that lost priority) gets its old place back | Fixed 2026-10-28 (S20b); E6 on the 2026-10-28 run: 26 restarts, 0 differences |
| X27 | S19 (E5 routing) | 2026-10-28 | every `order.oco` | Wire: `order.oco.tick_decimals` is 0 on every OCO — the ALF gateway never sets it, the generated default goes out; the engine ignores it | Fixed 2026-10-28 (S20b): the ALF gateway fills it (the API gateway already did) |

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

**X9 fix (2026-10-24).** `_handle_oco_order` resolves the gateway default
once (`_resolve_smp_action(gateway_id, None)` — no protocol carries an SMP
field on an OCO) and creates both legs with it; the per-leg `order.ack` now
shows it. Tests: `tests/test_engine_oco_smp.py` — the sim's case (a stop leg
triggered by another gateway's print meets its owner's bid: cancelled
`SELF_MATCH_PREVENTED`, no trade), the resolved action on both leg acks, a
limit leg crossing its owner's order on entry, and the control that a
gateway configured `NONE` still self-trades. The first three failed before
the fix. Docs: the OCO row in the operator guide's SMP per-path table.

**X10 — `pm-audit-replay` cannot read one rotated file of the sim
profile.** `pm-audit-replay --log-file audit.log.5 anomalies` (256 MB,
~390 k lines) builds a 750 MB episode index in about a minute and then fails
in `reader._events_for` with `sqlite3.OperationalError: too many SQL
variables`: `_hydrate` binds every episode id of the window into one
`IN (…)`, beyond SQLite's limit of 32 766. With the S1 rotation (256 MB ×
100) the tool cannot be used on a sim run's audit at all. Not needed by the
forensics (S5 streams the files itself); a fix chunks the `IN` list.

**X11 — batch cancels come out in hash order.** E2: in about 6 400 commands
(of 2.55 M) the engine published a batch of `order.cancelled` for one gateway
in a different order from the re-run — mostly quote replacements cancelling
the old legs. `OrderBook.orders_for_gateway` iterates the gateway's set of
order-id strings, whose order follows Python's per-process hash seed. The
same orders are cancelled and the book is identical; only the message order
differs between two runs of the same input, which makes the engine's output
non-reproducible byte for byte (and a recording compare harder). The same
index feeds kill switch and disconnect cancels. A fix iterates in
arrival-seq order.

*Fixed 2026-10-24.* `OrderBook._orders_by_gateway` and `QuoteIndex`'s
`_keys_by_gateway`/`_keys_by_symbol` (which order the disconnect, kill-switch,
halt and circuit-breaker quote cancels) are now insertion-ordered dicts used
as sets, so a batch cancels in the order the orders came to rest (a
re-triggered stop counts from when it rests again). This is deterministic, which is
all reproducibility needs, and is simpler than sorting by `arrival_seq`
at each read. The global kill switch already walked `_order_index` (a dict).
Tests: `tests/test_engine_batch_cancel_order.py` (40 ids, so a set matching
arrival order by chance is negligible; all three fail on the old code). On
the next run, E2's note should report no reordered cancel batches.

**X5 fix (S9, 2026-10-24).** An order the book may still reject
(`_book_may_reject`: a FOK, or a MARKET/IOC/FOK posted while matching is off)
is acked only after `book.process()`, and only if the book did not reject it.
A rejected one gets the single `accepted=false` ack (`INSUFFICIENT_LIQUIDITY`)
of the events loop. Applied at the three sites that ack before matching:
`_handle_new_order`, combo children (`_accept_combo`) and OCO legs. In the
new-order path the second clause never applies, because gate 8 rejects
MARKET/IOC/FOK before the book while matching is off. Message order changes
only for a FOK: its ack follows anything `process()` publishes itself (the
X3 quote-leg hook, when the FOK hits a quote). A FOK cancelled by SMP
(`CANCEL_AGGRESSOR` with a same-gateway conflict) is still accepted, then
cancelled `SELF_MATCH_PREVENTED`, as risk controls documents. Tests:
`tests/test_engine_fok_ack.py`: unfillable FOK, fillable FOK (ack before
fill), the SMP cancel (control), CANCEL_RESTING shortfall, an OCO FOK leg, and
a FOK combo child of a blocked AON combo. The four bug cases failed before
the fix. Docs: the order-flow chapter's ACK section. The audit replay keeps
tolerating accept-then-refuse, which older logs and converting stops hold.

**X12 — book rejects outside the new-order path (seen in S9, not changed).**
(a) A combo child posted while matching is off (symbol halted, session not
matching, or an AON combo blocked) that the book rejects (MARKET/IOC/FOK) is
reported with `reject_code INSUFFICIENT_LIQUIDITY`. A halted symbol should say
`INSTRUMENT_HALTED`, as gate 8 does for ordinary orders. (b) An OCO leg the
book rejects does not close its sibling (no `_check_oco_after_event`), whereas
`_handle_new_order` runs it for a rejected OCO-tagged order. Both are for
the X8d publication-loop consolidation, which removes the per-loop drift
that causes them.

**X8a fix and C8 (S10, 2026-10-25).** C8 (`checks/quotes.py`, one 34 s audit
pass) on the 2026-10-24 run: of 272 238 quotes, **40 898 traded on entry
and then rested their sibling**. In each case `INACTIVE_*_FILLED` came before
the quote's ack, `ACTIVE` came after it, and the sibling was never
cancelled. **6 212 trades** then hit such a sibling, after its owner had
been told the quote was inactive. Cause: `_handle_quote_new` posted the bid,
whose fill ran the X3 hook (`_on_quote_leg_filled`). The hook inactivated
the quote and cancelled a sibling that was not in the book yet, which
silently did nothing. The handler then posted the ask anyway, and only then
published `quote.ack` and `ACTIVE`. Fix: `quote.ack` and `ACTIVE` are
published before the legs reach the book, as an order is acked before it
matches. If the bid's fill inactivated the quote, the ask is not posted: it
gets `order.cancelled QUOTE_LEG_FILLED`, and the quote's history entry gets
both legs' snapshots. An ask that fills on entry already cancelled the
rested bid through the hook. Only the order of messages changed there.
`INACTIVATE_ON_FULL_FILL` with a partial entry fill keeps the quote active,
as before. C8 handles seeded quotes, which have no `quote.ack`, only their
legs' `order.ack`s (learnt from `is_seed` acks), and ignores the ack of a
quote cancel, which carries no legs. Tests:
`tests/test_engine_quote_entry_fill.py` (5; the four behaviour cases failed
before the fix) and `tests/test_sim_forensics_quotes.py` (4).
`test_engine_fill_status_vocabulary` traded against the ask that X8a
wrongly rested; it now posts a fresh quote first. Docs: participant guide,
MM quotes (refresh policies).

**X4, X6, X7 fix (S11, 2026-10-25), all in pm-stats.**
- **X4:** after a stop, the receive loop drains what is already queued on
  the engine SUB socket (`_drain`, at most `_DRAIN_SEC` = 0.5 s, inside
  `run()`'s 1 s join). The 2026-10-24 log shows the case: "EOD received"
  logged after "stopped".
- **X6:** a `QUOTE_REJECT` with no quote id (a quote cancel for a symbol
  with no live quote) is recorded with an empty `order_id`, identified by
  `gateway_id` and `symbol`; every other event without an id is still
  dropped. `order_events` gained `reject_code` (schema version 9). Older
  stats.db files are refused, not migrated: the next sim run starts with a
  fresh one.
- **X7:** `oco.cancelled` also writes a `CANCEL` row for `cancelled_order_id`,
  with the pair in `oco_group_id`.
- C4/C5 keep their OCO_CANCEL inference for older files. On a new run it
  should find nothing to infer.
- Tests: `tests/test_stats_recorder_gaps.py` (6: queued at stop, bounded
  drain, the X6 quote reject, `reject_code` kept, id-less events still
  dropped, the X7 leg row). All failed before the change.
  `test_service_metrics`'s mock SUB socket now reports an empty queue, as
  a real one would once drained.
- Docs: operator guide, statistics (schema version history, `event_type`
  table); the generated SQLite schema chapter.

**X10 fix (S12, 2026-10-25).** The four reader queries that bound a whole id
list into one `IN (…)` (`_by_ids`, `_events_for`, `_anomalies_for`,
`neighbours`) now run in batches sized by the connection's own
`SQLITE_LIMIT_VARIABLE_NUMBER` (`_batches`). `neighbours` binds each id twice
and keeps a link read from two batches once, by its primary key. `_in`
(CLI filter values) is unchanged: it binds what a user typed. Test:
`tests/test_audit_replay_reader_limits.py` lowers the limit to 3 on the
kill-switch fixture's index; a window and its neighbours read the same as
at the default limit. Both failed with the sim's `too many SQL variables`
before the fix.

On the real file (`audit.log.5`, 256 MB, copied to a scratch dir with a
scratch `--db`), `anomalies` now completes in 1 min 41 s: 252 222 episodes,
8 640 findings (4 errors). Before the fix it failed after the index build.
One error is a fill naming a trade outside this one file's window, which is
normal for a single rotated file. The other three are X13.

**X13 — `pm-audit-replay` reads a rejected cancel as a rejected order.**
`ILLEGAL_STATUS_TRANSITION … went FILLED -> REJECTED` (3 in `audit.log.5`).
Example `70c51725…` (AI091, ABNB): filled at 12:55:55.213; at .248 its
gateway's `order.cancel` (request_tag `CXL-AI091-4C1F`) is refused with
`order.ack accepted=false ORDER_NOT_FOUND`, correctly. The replay's status
ladder takes every `accepted=false` ack as the order becoming REJECTED. A
refusal that answers a cancel or amend (it carries a `request_tag`, or
`ORDER_NOT_FOUND` / `ORDER_ALREADY_TERMINAL`) refuses the command, not the
order. The forensics C1/C2 grammar already makes this distinction (S4). Fix
in `audit/replay/state.py` with a test; small, its own WP.

**X8b and X8c (S13, 2026-10-25).** Measured on the 2026-10-24 audit, in
uncross dispatches only (scratch script, 38 s):
- X8b: 301 quote-leg fills in an uncross. Each left the quote ACTIVE and the
  sibling leg live: the market maker cancelled 94 siblings itself later, and
  9 were still live at the end. No trade hit one in this run. The same
  loop also lacked the OCO sibling cancel, so a resting OCO leg filled in
  (say) the closing auction left its sibling live; that did not occur in
  the run.
- X8c: of 45 fills of stops the uncross triggered, 20 were reported at the
  last print rather than at their own VWAP.

Fix in `_run_uncross`: the uncross fill loop now runs `_on_quote_leg_filled`
and, for a FILLED OCO leg, `_check_oco_after_event`. These run after
`execute_uncross` (whose two-sided walk must not be mutated mid-way) and
before the stop loop, so a triggered stop cannot buy a leg the policy pulls.
The stop loop reports `_order_fill_prices` (H6) like every other loop.
Tests: `tests/test_engine_uncross_followups.py` (3). All failed before the
fix; in the quote case the triggered stop bought the MM's ask.

**X14 — no check compares a fill's price with its trades.** X8c's 20 wrong
fill prices passed B1, which matches fill to trade by id and quantity only.
Add to B1 (or a B8): each FILL's `fill_price` equals the quantity-weighted
price of the trades it names (`trade_ids`, schema 8+).

**X13 fix (2026-10-25).** `StateModel` remembers the msg ids of
`order.cancel` and `order.amend` commands. An `order.ack accepted=false`
whose `cause` is one of them, or (for logs without envelopes) whose
`reject_code` only a request on an existing order can get (`ORDER_NOT_FOUND`,
`ORDER_ALREADY_TERMINAL`, `AMEND_NOT_PERMITTED`, `NOT_OWNER`,
`DUPLICATE_ORDER`), refuses the request. The order keeps its status. The bug
was wider than the 3 findings showed: a refused cancel or amend of a *live*
order silently marked it REJECTED (NEW → REJECTED is on the ladder, so
nothing was reported). Tests in `tests/test_audit_replay_anomalies.py`:
- the sim's FILLED case;
- a refused amend for a code an order could also be rejected for (the
  cause alone decides);
- the envelope-less code rule;
- a genuine rejection, still REJECTED (control).

The first three failed before the fix. Two of the new tests first passed
vacuously: `reconstruct()` yields its steps lazily, and the model is built
only as they are read.

**X14 fix (2026-10-25): check B8.** On the 2026-10-24 run (4 s, 937 487
fills) B8 finds 23, all in the 14:05 closing uncross. They are the fills of
stops the uncross triggered **and of the resting limit orders those stops
traded with**, all reported at the last print: limit sells that executed
at 93.82 were told 92.28. That is X8c, wider than S13's scratch count (20
of 45, stops only). S13's fix covers both sides, since each order in the
stop loop now gets its own VWAP; `test_x8c_…` now also pins a passive
order's price. B8 should pass on the next run. Tests:
`tests/test_sim_forensics_bookkeeping.py` (a wrong price, a wrong quantity).


### S14 — Run 2026-10-25: X15 and X16

**The run.** 993 minutes, 560 408 trades, 2.5 M audited commands, every fix
through S13 in the engine (E2 PASS at HEAD: the run reproduces exactly).
It confirms X4–X11 and X14: A1–B8, C1–C4, C7, C8, D1–D9, E1–E4, F1–F4 and
G1–G2 all PASS. C5 FAIL 2 and C6 FAIL 4 622 are new. H1–H3 are INFO:
- H1 puts one C5 sample near an ops event; 30 % of the run is near one.
- H2: the P&L outliers are agent behaviour, as in S8. AI023's reject rate
  of 0.66 is the `block-taker` preset's FOKs, which are now rejected
  outright (X5). 148 price jumps (`--no-collars`).
- H3: p99 spikes co-occur with 58–73 % book heap garbage. That is for the
  latency plan, not a finding.

**X15 — an OCO sibling trades after its leg ended.** C5's two groups
(AI037-2B1F, AI077-164C) share one shape. The audit shows it for
AI037-2B1F, in a single MM01 `quote.new` dispatch:
1. The quote's ask trades at 242.87 and triggers AI037's buy stop leg.
2. The stop leg buys from the ask at 240.10 and is FILLED.
3. That print triggers AI057's sell stop, which sells into AI037's limit
   leg at 220.96: the leg's sibling.

The engine pulled a sibling only from the publication loops, after
`book.process()` returned, but the stop cascade runs inside `process()`.
The same mechanism as X3, for OCO legs.

Widening C5 (X16) found 194 more groups: 186 siblings of a leg a quote filled, never pulled until their owner cancelled them, and eight more traded ones. In each, a stop leg was triggered
in a quote's cascade and cancelled `INSUFFICIENT_LIQUIDITY`, and its limit
sibling stayed live and filled later (AI055-AEC: 3.8 s later). All eight
are MM01 `quote.new` dispatches. The quote-submit loop, like the seed-quote,
combo-child and amend loops, runs no OCO follow-up at all: the X8d drift.

Fix, in the book and so in every path:
- `OrderBook.on_oco_leg_done` is called from `_apply_fill` when an OCO leg
  fills, and from the cascade loop when a triggered stop leg ends
  otherwise. The engine sets it to `_check_oco_after_event`, which is
  idempotent, so the loops' later calls are no-ops. It skips the group
  that `_handle_oco_order` is still posting (`_oco_entering`), which checks
  its legs itself once both are in the book (finding #6).
- `_check_stops`/`_check_trailing_stops` keep triggered stops in
  `_triggered` until `process()` takes them up. `cancel_order` finds them
  there, and a stop cancelled while it waited does nothing. Otherwise a
  sibling triggered in the same cascade but queued behind the order that
  fills its leg would still trade.
- `_fok_available_qty` counts one leg per OCO group. Once the first leg
  fills, the second leaves the book mid-sweep, so counting both would let
  a FOK fill in part.

Message order changes as it did for X3: `oco.cancelled` for the sibling now
precedes the leg's `order.fill`. The forensics replay already treats an
`OCO_SIBLING` death in the dispatch as dying, and C5 now allows for it.
Tests: `tests/test_engine_oco_cascade.py` (4, all failed before the fix):
- the sim's FILLED case;
- the cascade-cancelled stop leg (quote path);
- a triggered sibling still queued;
- the FOK pre-check.

Docs: participant guide, order types (OCO edge cases).

**X16 — two check gaps.**
- C6 read the CANCEL rows pm-stats writes for an OCO sibling (X7) as
  cancel reasons. They carry `oco.cancelled`'s free text ("OCO sibling …
  reached FILLED"), not an `order.cancelled` code. They are recognised
  structurally, as the row right after their OCO_CANCEL row with its OCO
  id (`_OCO_RULE_CANCELS`), not by text. C6 skips them and counts them in
  its note.
- C5 flagged a sibling's fill only after the leg was FILLED, and checked
  "a done leg ends its sibling" only at the end. A sibling that filled
  after its leg was cancelled, or that its owner cancelled (or that
  expired) after its leg filled, ended terminal and passed. Now a leg ends
  when it fills, or is cancelled for a reason of its own (not by the OCO
  rule's row, which since X15 can precede the fill that caused it). After
  that the sibling must not fill, and after a fill it must end by the OCO
  rule's row.

On this run: C6 PASS (4 622 sibling rows skipped), C5 FAIL 196:
- 2 fills after the sibling FILLED;
- 8 fills after the sibling was CANCELLED;
- 186 siblings that outlived their filled leg until their owner cancelled
  them (the quote-submit loop's missing follow-up, with no trade).

E2 at HEAD (all samples kept) agrees. 3 534 of its 3 813 differing
dispatches differ only in message order (`oco.cancelled` now before the
fills). The rest are X15's change:
- 162 `quote.new` publish 194 sibling cancels the live engine did not;
- 106 later `order.oco_cancel` commands find the group already closed;
- about 10 are the trading cases and their after-effects on that symbol.

Tests: `tests/test_sim_forensics_lifecycle.py` (4). The cancelled case,
the outlived case and the C6 rows failed before; the pulled-before-fill
order is a guard.

**X17 — leg 2 of an OCO is posted after leg 1 ended on entry.** Seen
while reading `_handle_oco_order` for X15, and confirmed with a probe. It
was not in this run: C5 found no such pair. Finding #6 defers the legs'
OCO checks until both are posted, so leg 2 is posted even when leg 1
already filled. A buy stop leg at 99, posted after a buy limit leg filled
at 99, is already breached (M2): it triggers on entry and buys at 100, and
both legs are filled. Fix: if leg 1 is FILLED or CANCELLED after
`process()`, leg 2 is acked, then gets `oco.cancelled`, and is never
posted. Its owner hears what a resting sibling's owner would. The deferred
check of leg 1 unregisters the group. A REJECTED leg 1 still does not end
its sibling (X12b, unchanged). Test: the fifth case in
`tests/test_engine_oco_cascade.py` (failed before). Docs: the same OCO
edge-case table.

**Left for X8d.** The seed-quote, quote-submit and amend loops still run
no combo follow-up (`_check_combo_after_child_event`) for orders their
cascade fills or cancels. The book hook does not cover an OCO leg that
SMP cancels while resting, and only the new-order, OCO and uncross loops
handle that case. Neither gap has shown up in a run.

### S15 — X8d: one publisher for every match

**Done 2026-10-25.** Seven loops published what `book.process()` returned:
seed quote, new order, quote, combo child, uncross (and its stops), OCO
leg, amend. Each was a copy of the others with a different subset of the
follow-ups, and each fix since S9 had to find them all. They are now one
method, `Engine._publish_dispatch(trades, events, reject)`, which every
path calls. For each order in `events`, once:

- `order.fill` if it traded in this dispatch (X1), from one pass over the
  trades (`_executions`: quantity, VWAP in integer ticks, trade ids,
  MAKER/TAKER), then the quote refresh policy;
- `order.cancelled`, or the rejection *reject*;
- the combo follow-up; for an order that ended, the OCO follow-up and the
  drop of its routing entry (H7).

Then the trades. The new-order hot path keeps its inline ack; its fill now
comes from the same builder as everyone else's. The perf tests show no
regression: TPS 25.2–25.9 k against 24.4 k before, latency unchanged
within noise.

The book's OCO hook (X15) now also fires for a leg cancelled by SMP while
resting, for an order that ends in its own match (an IOC's rest, an SMP or
FOK refusal), and for a leg rejected while matching is off, so the OCO
follow-up no longer depends on which loop ran. `_handle_oco_order` no
longer exempts its own group from the hook (`_oco_entering`, the finding #6
deferral): with X17, leg 2 is never posted after leg 1 ended, so nothing is
left to defer.

What the drift had hidden, each now a test in
`tests/test_engine_dispatch_publication.py` (all ten failed before):

- **X12a.** A combo child or OCO leg the book rejected because matching
  was off was reported as `INSUFFICIENT_LIQUIDITY`. Now it gets the code
  an ordinary order of that type would: the halt's code
  (`INSTRUMENT_HALTED` or `CIRCUIT_BREAKER_ACTIVE`), or
  `SESSION_NOT_PERMITTED` outside continuous trading
  (`Engine._book_reject`). A leg of a blocked AON combo stays
  `INSUFFICIENT_LIQUIDITY`.
- **X12b.** A rejected OCO leg ends its sibling, as the participant guide
  says (OCO, example 4). On entry, a rejected leg 1 keeps leg 2 out of the
  book the way a filled one does (X17).
- **X18.** `_handle_oco_order` ignored the halt flag: on a halted symbol
  its legs matched continuously. They now rest, as ordinary orders do.
- **X19.** Leg 2 that filled on entry triggered a stop that sold into
  leg 1, which the deferral had kept live: both legs filled.
- **SMP.** An amend whose SMP `CANCEL_RESTING` pulled a resting OCO leg
  left its sibling live and the group registered (the amend loop had no
  OCO follow-up).
- **Combo follow-ups.** An amend, and a quote's cascade, that filled a
  combo child left the combo `PENDING`.
- **X20.** `order.fill` had two shapes. The new-order path built it by
  hand without `tif` and `is_seed`; every other path built it from
  `Order.to_dict()`, which has no display `price`, so their fills lost the
  order's limit price. One builder (`_fill_frames`) now sends all fields.
  `order.cancelled` from the new-order path likewise gains the group ids
  the other paths sent.

Wire changes: `order.fill` gains `tif`/`is_seed` (new-order path) and
`price` (other paths), and omits a null `client_tag`/`price` the hot path sent as `null`; `oco.cancelled` can now precede the leg's own
`order.cancelled` or rejection, as it already preceded its fill (X15).
Docs: the participant guide's OCO edge-case table (a leg ending while an
order matches; a rejected leg 1; a halted symbol) and the combo chapter
(reject codes of a leg that cannot rest); the order-flow chapter's §8 and
the VWAP section of the known limitations now show `_publish_dispatch`
and `_executions`.

**E2 on the 2026-10-25 run.** Re-run at v0.60.2 (all samples kept), E2
flags 315 165 dispatches, nearly all the field changes above. A fill
built by `_fill_frames` also omits a null `client_tag` and a MARKET
order's null `price`, which the hand-built hot path sent as `null`: the
spec's omit-when-none rule, invisible to readers using `.get`. With those
field differences masked, E2 equals the X15 baseline exactly: the same
3 813 dispatches with the same differences, 146 later commands on a
diverged symbol, and nothing new. On this run, X8d changes no message
order, no topic and no trade.

**X21 — decided 2026-10-26, fixed in S16.** A combo registered only after all its
children are posted, so the combo follow-up of a child that ends during
acceptance is a no-op. Reachable today: an AON combo blocked by a short
leg posts its IOC/FOK/MARKET legs with matching off, the book rejects
them, and the combo stays `PENDING` while its other legs rest. (A
remainder cancelled by SMP gets there too.) The guide says a cancelled or
expired leg fails the combo, but says nothing about a rejected one. Both
the rule (should a rejected leg fail the combo?) and the order of
`combo.ack` relative to a `FAILED` status need a decision, so it is left
out of S15.

### S16 — X21: a combo leg ending on entry fails the combo

**Done 2026-10-26.** Decided with Johan:

- a leg that ends without filling — rejected, cancelled (an IOC's rest,
  SMP) or expired — fails the combo, on entry as later. The guide named
  only cancelled and expired legs, but a rejected leg can never fill, so
  its combo could never match;
- `combo.ack` is published before the first leg is posted, as the guide's
  steps 2–3 already said; every leg event and `combo.status` follows it;
- a failed combo posts no further legs: they could only be acked and
  cancelled at once.

`_accept_combo` now publishes the ack and registers the combo before its
loop, so each child's own `_publish_dispatch` runs the combo follow-up:
fills move the combo to `PARTIALLY_MATCHED`/`MATCHED` as they happen, and an
ended leg fails it (`_check_combo_after_child_event` gains `REJECTED`). The
loop stops once the combo has `FAILED`, and its trailing
`_update_combo_status` is gone.

The probe that found X21 also showed worse than a stale status: with leg 0
cancelled by SMP on entry, leg 1 was still posted and **traded**, a fill for
a combo that could never complete. `tests/test_engine_combo_acceptance.py`
(5 tests, all failing before) covers a rejected leg after a resting one, a
rejected first leg, the AON-blocked IOC leg, the SMP-cancelled leg, and the
ack-first order with `MATCHED` published once. `test_combo.py`'s ack-order
test now expects `combo.ack` first.

Wire change: `combo.ack` precedes the legs' `order.ack`s on every combo, so
E2 on an earlier run will show every accepted combo as reordered.

### Run 2026-10-26: X22

Every check passed but D9 (4 rows, 2 dispatches on CSCO and CME). Both
are one pattern: an MM quote's leg trades, the print releases several
stops, among them AI073's buy `STOP_LIMIT`, which finds no ask and rests;
a sell stop released later in the same cascade then trades into it. The
engine is right (E2 passes; `OrderBook.process` pops `pending` first in,
first out). The replay picked from `pending` the next trade's aggressor
first, so it ran the sell stop before the stop-limit had rested, found
no resting order for the trade, and its book kept the stop-limit's full
quantity (`BUY 17812: engine (1868, 1) replay (2468, 1)`).

Fix: the cascade in `checks/matching.py` pops `pending` FIFO, as the
engine does (`_pick` stays for the dispatch's own commands).
`test_a_cascade_runs_its_stops_in_release_order` failed before. The run's
C7 and D1–D9 all PASS after the fix.

### Value jumps recorded; H4 (2026-10-26)

The H2 triage could not tell a lasting price jump that followed the value
model from one that did not: pm-market-sim kept no value history and its
jumps are never announced. Now `ValueModel.step` returns each step's jumps
(symbol → log size), and `MarketSim.step` logs each one at INFO and appends
it to `market_sim_news.db`'s new `value_jumps` table (`ts_ns`, `symbol`,
`log_jump`, `value` after the step).

- **H2** counts a lasting jump as explained by the model when a value jump
  on the symbol, in the price's direction, came in the 15 min before (the
  news window); the note gives that count beside news.
- **H4** (new, INFO): for each value jump of at least 1 %, the share of it
  the price shows 60 s and 300 s later: the median of the first 20 prints
  from then, against the median of the 20 before the jump, the same day.
  Samples are the jumps followed by less than half after 300 s, largest
  first. SKIPPED on a run whose pm-market-sim did not record jumps.

## 10. Pre-1.0: deeper checks and the last format changes (2026-10-28)

After 1.0 the audit line format, the bus message schemas (`spec/messages/`),
the DB schemas (stats, clearing, metrics) and the persistence files freeze.
This is the last chance to add what the forensics would need, so S17–S29
first add the checks today's data already allows, then settle and make the
format changes, then make the sim exercise what it never does, and end
with a long run on the 1.0 formats.

### Recon on the 2026-10-28 run

Audit: 25 files of 268 MB (plus 2026-10-27 as `.zst`); the sim was still
running. One hourly file (`audit-2026-10-28.12.log`): `book`/`depth`
snapshots 131 k lines, `order.new` 37 k, `trade.executed` 17 k, quotes
~38 k, OCO ~1.8 k.

**Coverage.** `order.new` over the whole day: LIMIT, IOC, TRAILING_STOP,
STOP, MARKET, ICEBERG, FOK; STOP_LIMIT 1 303; TIF ATO 2 955, GTC 6 751, the
rest DAY. **Never, all day:** `order.amend`/`order.amended`, `order.combo`
/ `combo.*`, TIF ATC, an explicit `smp_action` (all `null`, so every order
takes its gateway default), `circuit_breaker.*`, `auction.reopen`,
`risk.*` (halt, kill switch, force uncross), `system.reference_reload`,
`system.startup_recovery` (no restart). Every check on those features passes
vacuously, and the replay could not follow them anyway: `matching.py`'s
`_UNMODELLED = ("order.amended.", "combo.", "circuit_breaker.")`, and D8
checks the tick grid only.

**Audit completeness is assumed, not checked.** Lines carry a per-topic
`seq=`, but `sim_forensics/audit.py` drops it, and B7's
`audit.decode_errors` does not see a message pm-audit never received.
pm-audit is a ZMQ SUB (`audit/main.py`, `_SUB_RCVHWM = 200_000`): a slow
writer loses messages silently at the high-water mark.

**Format gaps found:**

- Execution messages carry money as display floats: `trade.executed.price`,
  `order.fill.fill_price`/`price`, `order.ack.price`/`stop_price`/
  `trail_offset`. The DBs already store integer ticks.
- `order.fill` has `remaining_qty` but no cumulative qty or average price;
  `order.cancelled` / `order.expired` have no remaining qty; no message
  carries the engine priority (`arrival_seq`; `order.new` echoes 0).
- `trade.executed` does not say in which phase or auction it printed, nor
  which stop triggered its aggressor; the replay infers both.
- Stop triggers, trailing ratchets and iceberg refills are published
  nowhere; C7 and D5 infer them.
- Collar / band reference prices are not published, so D8 cannot check
  bands.
- The audit has no header or format version, and no message says which
  engine (version, commit) and which compiled config made it. E2 reads
  `data/ref_data/engine_config.json`, which the next run overwrites, and
  needs the run's engine checked out by hand.
- `system.startup_recovery` holds only counts. The replay needs the audit
  from the engine's start, without a restart (else SKIPPED), and a daily
  audit file cannot be replayed alone when GTC orders rest overnight.
- `gtc_orders.json`, `gtc_combos.json`, `book_stats.json` are overwritten
  in place: no cross-day comparison is possible.
- `stats.order_events` and `clearing.trade_events` hold no audit `msg` /
  `chain`; `stats.trade_log` holds no order ids (clearing does).

### S17 — A5 audit completeness, H5 coverage

No format change. `audit.py`'s `Line` keeps `seq`; A5 tracks the last
`seq` per topic, resets on `system.startup_recovery` / a `run_seq` change,
and counts gaps and repeats (samples: topic, expected, got, file, ts). H5
counts `order.new` by type × TIF × `smp_action` (as received and as
acked) × phase, outcomes per type (filled / partial / cancelled by reason /
expired / rejected by code), and one row per engine feature; INFO, samples
are the zero rows.

Done when: a test plants a dropped line and a repeat (A5 FAIL) and a run
with no amend shows the zero (H5); the 2026-10-28 run reports both.

### S18 — C9, C10, D10, F6

No format change. C9 must accept an acked FOK that ends CANCELLED
`SELF_MATCH_PREVENTED` with no fill in its own dispatch: the operator
guide (risk controls, "FOK — self-match liquidity is excluded before the
pre-check", step 2) prescribes it for `CANCEL_AGGRESSOR`/`CANCEL_BOTH`
with a same-gateway conflict; H5 found 12 on the 2026-10-28 run. C9 (lifecycle, from the audit's chains), C10 (quotes,
extends `checks/quotes.py`), D10 (reuses the replay's uncross function
`matching.py` already has for D6, evaluated at each `auction.indicative.*`
on the replayed book), F6 (`derived.py`, from the same `book.*` /
`depth.*` pass F2/F3 use; `depth` and `book` of one dispatch share a
`ts_ns` window — confirm the pairing rule against the engine first).

Done when: one planted violation per check in a unit test; 2026-10-28 run
reported, any FAIL triaged as X*n*.

### S19 — E5, E6, E7

No format change; extends `checks/rerun.py` (same fake-socket engine, same
comparison and id binding).

- **E5** filters the echoed commands per symbol (a command naming several
  symbols — OCO across symbols, kill switch, halt-all, session — goes to
  every symbol it names or to all) and diffs each against its part of the
  full re-run. Finds state that leaks between symbols.
- **E6** at k random command indices (seeded; default 20) calls the
  engine's own GTC/combo persistence, builds a new `Engine` from those
  files as `run()` does after a restart, and continues; output after k
  must equal the uninterrupted re-run, apart from what a restart is
  documented to change (DAY orders, quotes, `run_seq` in new trade ids —
  write that list down first, it is part of the spec). Tests the
  persistence format **before** it freezes: iceberg slices, trailing
  levels, priority order, armed stops, OCO/combo links.
- **E7** two transforms: a bijective rename of gateway ids, client tags
  and order ids (trades must be equal after mapping back), and a +k tick
  shift of every price of one symbol, k chosen so no band is crossed
  (trades shifted by k). Run on a sample of symbols; cost is one re-run
  each.

Cost: each is one or more full re-runs (~6 min each on 2.5 M commands);
make E6/E7 opt-in (`--slow`) if the default report gets too long.

Done when: each has a unit test with a planted engine fault it catches
(E5: a cross-symbol global; E6: a field dropped from persistence; E7: a
tie-break on gateway id), and the 2026-10-28 run is reported.

### S20 — Pre-1.0 decisions (doc only) — done 2026-10-28

Decided with the maintainer: Q5–Q10 as recommended (see §8); X23–X26 are
engine bugs to fix before the freeze (S20b); X27 is fixed by filling the
field. The frozen list below is what S20b–S26 implement; a change to it
comes back here first. Units as `spec/messages` declares them (`ticks`
is new: an integer count of the symbol's tick).

**Execution messages (S22)** — each keeps its display floats:

| Message | Add |
|---|---|
| `order.ack` | `price_ticks`, `stop_price_ticks`, `trail_offset_ticks`. (`priority_seq` struck in S22, decided with the maintainer: the ack precedes the book, which assigns `arrival_seq` only when the order rests or arms — see `engine.trace` `RESTED`) |
| `order.amended` | `price_ticks`, `priority_seq` (`priority_kept` struck in S22: the message already carries `priority_reset`) |
| `order.fill` | `fill_notional_ticks` (Σ price_ticks × qty of the fill's trades: a VWAP is no whole tick, the notional is exact), `cum_qty`, `cum_notional_ticks` |
| `order.cancelled`, `order.expired` | `remaining_qty`, `cum_qty` |
| `trade.executed` | `price_ticks` |
| `auction.result`, `auction.indicative` | `eq_price_ticks` |
| `order.oco` | `tick_decimals` filled by every gateway (X27, S20b) |

**Envelope and trade context (S23):** `eseq` (engine-wide output
sequence) in the envelope frame, written by pm-audit as `eseq=N` in the
line's meta; `trade.executed` + `match_type` (`CONTINUOUS`,
`OPENING_AUCTION`, `CLOSING_AUCTION`, `REOPEN_AUCTION`, `FORCE_UNCROSS`),
`auction_id` (also on `auction.result`), `trigger_order_id` (null unless
the aggressor was a triggered stop).

**New messages (S21, S24, S25):**

| Topic | Fields | Who sees it |
|---|---|---|
| `system.startup` | `format_version`, `engine_version`, `git_commit`, `python_version`, `run_seq`, `config_sha256`, `config` (the compiled engine config), `loaded` (per persistence file: name, `sha256`, entries) | audit; the first message of every start |
| `order.triggered.<GW>` | `order_id`, `symbol`, `order_type` (as armed), `stop_price_ticks`, `trigger_trade_id`, `trigger_price_ticks`, `becomes` (`MARKET`/`LIMIT`) | owner and audit |
| `engine.trace.<SYM>` | `kind`: `TRAILING_RATCHET` (`order_id`, `stop_price_ticks`, `last_price_ticks`), `ICEBERG_REFILL` (`order_id`, `displayed_qty`, `priority_seq`) or `RESTED` (`order_id`, `priority_seq`: an order rests or arms; added in S22) | audit only (no gateway forwards it) |
| `risk.band.<SYM>` | `kind` (`COLLAR`/`CIRCUIT_BREAKER`), `reference_price_ticks`, `low_ticks`, `high_ticks`, `source` | public; on every change |
| `system.book_checkpoint.<SYM>` | `reason` (`STARTUP`/`PHASE`/`EOD`), `phase`, resting orders (`Order.to_dict` + `priority_seq`, hidden qty), armed and trailing stops with current trigger, quote ids, OCO groups, combo links, last trade/buy/sell prices | audit |

**Audit file (S21):** first line of every file `# edumatcher-audit
format=1 pm-audit=<version> started=<iso>`; readers already skip lines
that do not start with `[`.

**Stores (S26):** `stats.order_events` + `msg_id`; `stats.trade_log` +
`buy_order_id`, `sell_order_id`, `match_type`; `clearing.trade_events` +
`msg_id`, `match_type`; schema versions bumped, fresh databases. At
`system.eod`, `gtc_orders.json`, `gtc_combos.json` and `book_stats.json`
are copied to `<data>/eod/<session date>/`.

### S20b — Restart contract (X23–X27)

A restart gives back everything the checkpoint holds, as it was:

- **X23** `_restore_gtc` rebuilds `_oco_groups` from the restored legs'
  `oco_group_id` (as it rebuilds quotes); a group with one surviving leg
  is dissolved and the leg rests as a plain order (as a quote remnant).
- **X24** `last_trade_price` = `prev_close` from `book_stats.json` on every
  restart, the same rule as the last buy/sell prices.
- **X25** no RECOVERY uncross on restore: a crossed restored book stays
  crossed until the normal path uncrosses it (the auction at the end of
  the call). First confirm what happens when the engine enters CONTINUOUS
  with a crossed book (PRE_OPEN → CONTINUOUS directly; sessions disabled,
  where the engine starts in CONTINUOUS): uncross at that transition, so
  continuous trading never starts crossed.
- **X26** checkpoint and restore keep current priority: orders restored in
  `arrival_seq` order per side, stops in their heap order, trailing stops
  in list order.
- **X27** the ALF, BALF and API gateways set `order.oco.tick_decimals`
  from the symbol.

Tests first: E6's strict xfail (`test_e6_passes_on_a_day`) must pass, plus
one engine test per finding; then E6 probes on the 2026-10-28 run at a
pre-open and a continuous restart. Operator guide: the restart section
says what a restart restores.

### S21 — Self-describing audit

- New `system.startup` message, the engine's first on every start:
  package version, git commit (or "unknown" in a wheel), Python version,
  `run_seq`, the compiled `engine_config` (as JSON) and its SHA-256, the
  persistence files it loaded with their SHA-256.
- The audit writer starts every file with a header line (format version,
  pm-audit version, file start time); `discover_log_files`/`open_log_file`
  and `pm-audit-replay` skip it.
- E2 builds its engine from `system.startup`'s config instead of
  `ref_data/`, and its note names the commit to re-run with.

Done when: `make msgen-check` clean; E2 passes on a short recorded run with
`ref_data/` removed.

### S22 — Execution messages

Per S20's list, likely: `price_ticks` / `stop_price_ticks` /
`trail_offset_ticks` on `order.ack`, `order.amended`; `fill_price_ticks`,
`cum_qty`, `avg_price_ticks` on `order.fill`; `remaining_qty`, `cum_qty` on
`order.cancelled` / `order.expired`; `price_ticks` on `trade.executed`;
`priority_seq` (the engine's `arrival_seq`) on `order.ack` and
`order.amended`, with `priority_kept` on the latter. Spec in
`spec/messages/*.yaml`, `make msgen`; every publisher goes through
`_publish_dispatch` (S15), so the change is in one place. B8, C3, D3, D5
switch to the integer fields; C3 also checks `cum_qty` and `avg_price`.

Done when: msgen-check, full test suite, and a short recorded run on which
B8/C3 PASS with the new fields.

### S23 — Global sequence, trade context

- Every engine PUB message gets an engine-wide sequence (`eseq`) next to
  the per-topic one (envelope, `messaging/bus.py`); pm-audit writes it in
  the line's meta; A5 checks it gap-free per engine start.
- `trade.executed` gains `match_type` (CONTINUOUS, OPENING_AUCTION,
  CLOSING_AUCTION, REOPEN_AUCTION, FORCE_UNCROSS), `auction_id` (also on
  `auction.result`) and `trigger_order_id` (the stop whose trigger made
  the aggressor, else null). `stats.trade_log` / `clearing.trade_events`
  store `match_type`.
- A4 checks `match_type` against the phase; D6 groups prints by
  `auction_id` instead of by time.

### S24 — Explicit engine events, bands

- `order.triggered.<gw>` (order id, stop price ticks, trigger trade id,
  price that triggered it, resulting order type) when a stop / stop-limit
  / trailing stop fires.
- Per Q7, an audit-only trace topic for a trailing stop's new trigger
  level and an iceberg's refill (order id, new displayed qty, new
  priority), and (S22) an order resting or arming with its priority.
- Collar / circuit-breaker bands published when they change (symbol,
  reference price ticks, low, high, source), and the band on a band
  reject's ack.

C7 and D5 can then compare the replay's inference with the engine's
statement (a disagreement names a bug on one side); D8's band part
becomes possible (S28).

### S25 — Book checkpoints

`system.book_checkpoint.<SYM>` (or one message per engine, per Q9): every
resting order with hidden quantity and priority, armed stops with current
trigger levels, active quotes, OCO/combo links, last price, phase. Emitted
after startup/recovery, at each phase change, and at EOD. The replay
(`matching.py`) and `rerun.py` can then start at any checkpoint: a run with
a restart, or a single day file, is no longer SKIPPED; D9 compares order
by order at each checkpoint.

Done when: replay started from a mid-day checkpoint of a recorded run gives
the same D-results for the rest of the day as the replay from the start.

### S26 — Stores

- At EOD (`system.eod`), the engine copies `gtc_orders.json`,
  `gtc_combos.json`, `book_stats.json` to `eod/<session date>/`; G3 checks
  day N's archive against day N+1's recovery (and S25's startup
  checkpoint).
- `stats.order_events` and `clearing.trade_events` get `msg_id` (audit
  ULID); `stats.trade_log` gets `buy_order_id`, `sell_order_id`. Fresh DBs,
  schema versions bumped, no migration.
- Checks that join the audit to a store (B1, C6, F2) use `msg_id` where it
  makes them simpler; do not rewrite ones that work.

### S27 — Sim feature coverage

Make the run exercise what H5 shows as zero (2026-10-28, see S17's
result: COMBO entry, ATC, every explicit SMP mode, resolved SMP other than
`CANCEL_AGGRESSOR`, amend, combos, circuit breakers, every `risk.*`
command, reference reload; CLOSING_AUCTION/CLOSED were only not reached
yet). Also: the AI agents cancel every DAY order they enter in PRE_OPEN
(55 792, all by their own `order.cancel`, before or early in the opening
auction), so only ATO and MM orders reach the opening uncross. Cause:
`Agent._housekeeping` runs `OrderManager.stale` in every phase; it exempts
ATO/ATC/GTC but ages DAY limits out after the preset's
`max_order_age_sec` (20–120 s; ages at cancel cluster at 20/30/45/60/120 s)
against a 25 min pre-open, and its drift rule measures against a call
book's touch. **Fixed 2026-10-28** (separate change): `_housekeeping`
skips the stale sweep in call phases; leftovers go at the first continuous
sweep. Confirm on the next run (H5: PRE_OPEN DAY limits FILLED/EXPIRED,
opening-auction volume up). Then: AI agents amend (price up and
down, qty down) and send combos, ATC orders, explicit SMP modes (all four)
and more STOP_LIMIT and non-LIMIT GTC; the sim profile enables collars and
circuit breakers with bands a news jump can hit; a scripted operator
schedule (via the existing risk commands) halts and resumes a symbol,
fires a gateway kill switch and a force uncross, and restarts the engine
once mid-session. Rates low enough not to change the market's character
(watch H2/H4).

Done when: H5 on a 1 h run shows no zero row the engine supports.

### S28 — Replay models the rest

`matching.py` models `order.amended` (price change loses priority, qty
down keeps it — as the guide says), combos (legs as their own orders,
plus the combo grammar in C5), circuit-breaker halts and reopen auctions,
symbol halts (no trade while halted), using S24's bands for D8.
`_UNMODELLED` ends empty. C7/D5 compare against S24's events.

Done when: planted-fault tests per new feature; a run from S27 replays
with D9 PASS.

### S29 — The 1.0 long run

A full sim session on the 1.0 formats with S27's coverage; the full
report (with E5–E7); triage as in §6. Formats freeze when it is clean or
every finding is a fix that does not touch them.

### S17 — done 2026-10-28

- `sim_forensics/audit.py`: `Line` gains `seq`. **`audit_files` now reads
  the daily `.zst` archives first.** It used `discover_log_files`, which
  leaves archives out, so on a run that crossed midnight (every sim run
  since the zstd audit) the replay checks would have reported SKIPPED ("the
  audit does not reach back to the engine's start") and C8/F2/F3 read a
  partial trail without saying so. (`matching.py`'s 4-tuple unpack of
  `Line` became `*_`.)
- **A5** (`checks/completeness.py`, oracle conservation): per topic, seq
  must be previous + 1; `system.startup_recovery` with seq 1 starts every
  topic again; without the engine's start in the audit a topic's first
  line only sets the baseline (the note says so). A line pm-audit wrote
  without an envelope has no seq either, but its topic's next line shows
  the gap, so nothing slips through `lines()` skipping it.
- **H5** (`checks/coverage.py`, INFO): orders keyed (entry, type, TIF,
  resolved SMP, phase on entry) → outcome (FILLED, PARTIAL+CANCELLED,
  CANCELLED, PARTIAL+EXPIRED, EXPIRED, REJECTED, LIVE). Type and TIF come
  from `order.new` for a reject (a rejecting ack carries neither); quote
  legs from `quote.ack` (they get no `order.ack`); a rejecting ack with no
  `order.new` waiting is a refused cancel/amend, counted apart. Violations
  = values of a dimension never seen; samples = those, then the rarest
  combinations.
- Tests: `tests/test_sim_forensics_completeness.py` (13), including a real
  `Engine` recorded through the real `SequencedPublisher` and pm-audit's
  `_meta_section` (passes A5; dropping one ack is a gap on that topic), and
  archive ordering.
- **2026-10-28 run (sim still running, ~13:20):** A5 PASS — 11.0 M lines in
  29 files (archive included), 12 979 topics, 1 engine start, nothing
  missing (22 s). H5 (68 s): 1.58 M orders in 17 combinations; never seen:
  see S27. Two pointers checked: the 12 acked FOKs cancelled
  `SELF_MATCH_PREVENTED` with no fill are the documented SMP case (→ C9's
  rule, S18); the 55 792 PRE_OPEN DAY limits all cancelled are the agents'
  own cancels (→ S27).
- Not from S17: `test_shell_completion` failed at HEAD (871fa8d1 added
  pm-compdb-cli `--format grid/markdown` without `make completion`);
  `make _check` regenerated `src/edumatcher/completion/*` — commit apart.

### S18 — done 2026-10-28

- **C9** (`checks/immediate.py`): per `order.new` of type IOC/FOK/MARKET,
  its chain must end it (rejected, filled, cancelled, expired); a FOK
  that traded part, was cancelled for a reason other than
  `SELF_MATCH_PREVENTED`, expired, or was acked and then rejected (X5) is
  flagged. Other orders' messages are skipped unparsed.
- **C10** (`checks/quotes.py`, in C8's pass): live legs per (gateway,
  symbol), seeded legs included. The engine publishes no `quote.status`
  for a replaced quote, so the rule is on legs, not statuses.
- **D10** (`checks/matching.py`): `auction.indicative.*` lines are read
  like book snapshots (timer messages between dispatches) and compared
  with `_uncross_of(book)`; symbols D9 found diverged are skipped and
  counted. `_equilibrium` (D6) now uses the same `_uncross_of`, linear in
  the price levels instead of quadratic, and cached per book version
  (`_Book.version`) — 85 500 indicatives per opening auction.
  `tests/…matching.py` checks it against the price-by-price definition on
  300 random books.
- **F6** (`checks/derived.py`, in F2/F3's pass): a `depth.<SYM>` must
  directly follow its `book.<SYM>` (both from `Engine._flush_snapshots`);
  its figures are recomputed from the book's levels (shown quantities)
  with the window around the book's `last_price`. Tested against a real
  `OrderBook`'s own `snapshot()` and `depth_snapshot()`, iceberg included.
- Tests: `test_sim_forensics_immediate.py` (3), C10 (2), D10 (6), F6 (8);
  the lifecycle pin test excludes the audit-based C7–C10.
- **2026-10-28 run (sim still running): all PASS.** C9: FOK 360 filled /
  7 905 rejected / 12 cancelled (SMP), IOC 104 249 filled / 48 842
  cancelled, MARKET 30 872 / 1 711. C10: 147 297 legs cancelled
  `QUOTE_REPLACED`. D10: 85 500 indicatives. F6: 1 668 653 depth messages,
  all paired. D9 on the whole run (now that the archive is read): 3.1 M
  snapshots, 0 differ. Times: replay (C7, D*) 204 s, F-pass 113 s, C8/C10
  38 s, C9 36 s.

### S19 — done 2026-10-28

- `checks/differential.py`: one lockstep pass — the reference re-run (as
  E2's, from `rerun.fresh_engine`, now shared and pointing the
  persistence files into a temp dir, so no re-run reads the host's) plus:
  - **E5**: an engine per symbol (config with that symbol alone), created
    when its first command comes, after replaying every symbol-less
    command so far. Commands route by `symbol`, or by the order / OCO /
    quote id they name (`order.cancel`, `order.oco_cancel` carry no
    symbol); symbol-less commands go to every engine. Outputs are grouped
    by symbol on both sides; a `DUPLICATE_ORDER` difference is excused
    (order ids are engine-wide); combo symbols are left out.
  - **E6**: every 100 000 commands the reference checkpoints with its own
    `_flush_persistence`; a fresh engine restores from the files, with
    "today" pinned to the run's date (else a later re-run drops every DAY
    order as stale), the live phase and the connected gateways' connects.
    Books compared at once (priority order, quantities, shown slices,
    armed and trailing stops, last prices; OCO groups, quotes, combo
    links), then outputs for 20 000 commands. A book the restart seeds
    again is skipped and counted: by design (§5.4 of the quote-persistence
    design: `seed_once` seeds where no quote is live).
  - **E7**: (a) gateways shuffled within groups of identical config
    (`id`/`description` aside) and every order id renamed (md5), mapped
    back on the outputs, text prefixes too; (b) every price +7 ticks (seed
    quotes and last prices in the config too), only where no collar,
    order limit, circuit breaker or risk level is configured; fill prices
    are VWAPs off the grid, so that lane compares floats to 9 decimals.
- Slow checks: `@check(..., slow=True)`; `run_checks(..., slow=)`; CLI
  `--slow`, and a check named with `--check` always runs; `make forensics
  ... SLOW=1`.
- Tests: `tests/test_sim_forensics_differential.py` (8 + 1 strict xfail):
  a day on s3-basic (3 symbols interleaved: crossing, resting, iceberg,
  stop, trailing stop, OCO, quote replacement, IOC, FOK, cancel, MARKET);
  E5 and E7 pass; E6 finds X23/X24 and not the designed re-seed; planted
  faults: a per-engine counter (E5), trailing stops left out of the
  checkpoint (E6), dropping orders by id or by even price (E7 per lane);
  `test_e6_passes_on_a_day` is the strict xfail that turns into X23/X24's
  regression test.
- **2026-10-28 run** (2 280 194 commands; 22 min, 2.2 GB): **E5 PASS** (300
  symbols), **E7 PASS** (both transforms), **E6 FAIL 5 097**: restart 1
  fell in PRE_OPEN → X25 (825 trades on restore) made every book differ;
  a probe restart at command 300 000 (CONTINUOUS): 206 books re-seeded
  (by design), 48 only X24, 2 X26 (APH bids, BBY asks: iceberg order).
  X23 too: at that restart the reference held 232 live OCO groups (464
  resting legs), the restored engine none.
- X23 was in the count but not the samples: the engine-wide comparisons
  ran after the per-symbol ones and the cap (50) was full. They now run
  first. For triage of the rest, probe single restarts (`_E6_EVERY`
  patched), as above.

### S20b — done 2026-10-28

- **X23** `_restore_gtc` collects restored legs by `oco_group_id` and
  re-registers pairs of two in `_oco_groups` and `_order_to_oco` (legs in
  priority order, so leg 1 first, as `_handle_oco_order` registers them);
  a lone leg is not re-linked.
- **X24** `OrderBook.restore_stats` takes the last trade price too
  (`prev_close`), kept only if the book has not traded since the restart
  (`_load_config` runs after a recovery uncross may have printed).
- **X25** the RECOVERY uncross runs only if the engine starts in a
  matching phase (sessions disabled). With sessions the engine starts
  CLOSED, and `_handle_session_transition` already uncrosses on every
  entry into a matching phase from a non-matching one — so continuous
  trading never starts crossed either way.
- **X26** restored orders are sorted by `(symbol, arrival_seq)` before
  they are re-queued (the file stays in `_order_index` order).
- **X27** `alf_gwy` puts `tick_decimals` on `order.oco`.
- Tests: `tests/test_engine_restart_contract.py` (5; X23–X26, plus the
  sessions-disabled restore that must still uncross), all failing before;
  `test_alf_gwy_gateway_unit.py` pins X27. E6's strict xfail became
  `test_e6_passes_on_a_day_and_skips_a_designed_reseed`.
- Operator guide, persistence chapter, "At Startup": OCO pairs re-linked
  (3b), crossed restored books (5), the last trade price (6), priority
  (10, which credited "original timestamps").
- **2026-10-28 run, E6 alone** (sim still running, so more commands than
  S19's run): 26 restarts, 1 656 books re-seeded by design, **0
  differences** — state and 20 000 commands after each restart.

### S21 — done 2026-10-28

- **`system.startup`** (spec `system.yaml`, new record type `LoadedFile`;
  `make_startup_msg`): `format_version` 1, `engine_version`,
  `git_commit` (`cli_version.source_commit()`, also used by E2's note now),
  `python_version`, `run_seq`, `config_sha256`, `config`, `loaded`. The
  spec has no free-form object type, so `config` is the artifact's JSON
  *text*, verbatim: its hash is the file's and `config_artifact.decode`
  gives back what the engine loaded. `Engine.run` publishes it right after
  the run_seq bump, before `_restore_gtc` — necessary, because
  `recovery_item` lines precede `startup_recovery`, so after a restart
  with restored orders the latter was never the first line (A5, the
  replay and the re-runs assumed it was).
- One read for config and text: `config_artifact.load_compiled_text()`
  (`load_compiled_config` now uses it); the engine's
  `_compiled_engine_config()` became `_deployed_config()` → (engine
  config, text). A YAML-configured engine announces `config: null`.
- **Audit header:** `AuditFile.write` starts every new file (first and
  after each roll) with `# edumatcher-audit format=1 pm-audit=<version>
  started=<iso>`; `file_day` reads past it; `query.parse_line` already
  skips it.
- **Forensics:** `audit.STARTUP` and `run_config_text(files)`: A5 resets
  on `system.startup`, the replay (C7, D*), E1–E7 and the F pass take it
  as the run's start, and the replay and re-runs build from its config —
  `ref_data/` is no longer read. An audit written before S21 has no
  `system.startup`, so those checks now SKIP on it (no compatibility path,
  by policy); the 2026-10-28 run's results stand as recorded above.
- Tests: `tests/test_engine_startup_announcement.py` (2: content against a
  deployed artifact; first before the restore's messages), the writer's
  header test, every forensics recording now starts as `Engine.run` does,
  and the E tests deploy outside the data dir (`ref_data/` absent).
  Message counts: system family 34, reference 126. Operator guide,
  audit trail chapter: the header line and `system.startup`.
- Holistic: full suite 11 114 passed; `make _check` clean; e2e (sim
  stopped) 14 of 15 — `test_all_nine_rows_show_the_live_exchange` fails
  at HEAD too: 1394a847 added the dashboard's "Long" column, so the
  order-books row's "Trades" is cell 8, not 7 (test not updated then).

### S22 — done 2026-10-28

Two changes to S20's list, recorded there: `order.ack` carries no
`priority_seq` (decided with the maintainer — the ack precedes the book;
priority becomes visible as `engine.trace` `RESTED` in S24 and in the
checkpoints), and `order.amended` no `priority_kept` (it has
`priority_reset`).

- Spec: `order.ack` + `price_ticks`/`stop_price_ticks`/`trail_offset_ticks`;
  `order.fill` + `fill_notional_ticks`, `cum_qty`, `cum_notional_ticks`
  (new unit `notional_ticks`); `order.cancelled`/`order.expired` +
  `remaining_qty`, `cum_qty`; `order.amended` + `price_ticks`,
  `priority_seq`; `trade.executed` + `price_ticks`; `auction.indicative`/
  `auction.result` + `eq_price_ticks` (their `include:` lists name it —
  a field left out is read as topic-only and coerced with `0`).
- Engine: the new-order fast-path ack and `ack_detail()` (display dict +
  ticks; seed, combo and OCO acks); `_fill_frames` adds the execution to
  the new `Order.cum_notional_ticks`; dispatch cancels and
  `make_cancelled_msg`/`make_expired_msg` (`left_and_filled`) carry the
  quantities; amend, trade (`Trade.to_wire`), auction calls the ticks.
  `cum_notional_ticks` is engine state: not in `Order.to_dict()` (clients
  build `order.new` from it), written beside it by `save_gtc_orders`, read
  by `from_dict` — a restart keeps it. `feed_schema.TradeExecutedPayload`
  (the spec's hand-written twin) has `price_ticks`, omitted when unset.
- Forensics: new **C11** (`checks/cumulative.py`): running `cum_qty` /
  `cum_notional_ticks`, each fill's notional against its trades, a
  cancel's or expiry's `cum_qty`; SKIPPED on an audit without the fields.
  **D8** also flags a display price that is not `price_ticks`, and the
  replay prices trades by `price_ticks`. E7's price shift moves the new
  tick fields and the notionals (by k × qty).
- Tests: `tests/test_engine_execution_fields.py` (9, every field on real
  engine output, the running notional across a restart),
  `tests/test_sim_forensics_cumulative.py` (6); message-count and
  field-order tests updated.
- Holistic: 11 129 passed, coverage 88.8 %; `make _check` clean; e2e 14 of
  15 (the pre-existing `aapl[7]`, S21).


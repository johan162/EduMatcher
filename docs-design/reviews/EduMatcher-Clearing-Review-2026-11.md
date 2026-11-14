# pm-clearing / pm-clearing-cli Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/clearing/` at `7d4a63d2` (v0.79.0): `main.py`
(1 292 lines, pm-clearing: receive loop, buffer, flush, EOD, session and
gateway events), `ledger.py` (565, the in-memory position ledger), `store.py`
(1 702, schema, writers and every read query), `cli.py` (1 049,
pm-clearing-cli) and `query.py` (173, the read-only reader pm-api-gwy uses).
`store.py`'s `query_*` functions are shared: pm-api-gwy's clearing routes
(`api_gateway/routers/clearing.py`) and the clearing GUI call them, and pm-eod
reads `position_close_snapshot`, `session_events` and `clearing_meta`. The
engine's trade and end-of-day producers (`engine/main.py:3422`,
`engine/main.py:7463`, `engine/order_book.py:1155`), `models/price.py` and the
scheduler's catch-up were read where they decide what clearing receives, not
reviewed as code of their own.

**Focus:** correctness, edge-case handling, performance, and whether the
comments, help texts and the guides (operator guide `part-6…/010-persistence`,
`080-clearing-gui`, `part-4…/100-closing-the-day`; participant guide
`part-5…/010-positions-and-pnl`; training guide `120-pnl-clearing`) say what
the code does.

**Previous work:** `docs-design/reviews/EduMatcher-Review-Clearing.md`
(2026-07-14, findings CL-C1…CL-L7), the design `EduMatcher-Clearing.md`
(v3.0.0, whose §17.2 records which CL- findings were closed), the
key-component fixes K4–K6 (durable dedup, fatal warm-start failure,
per-symbol precision) and the clearing-GUI work CG0–CG16. Their fixes are in
place and are not repeated here: run-scoped trade ids (CL-C1), the EOD field
names (CL-C2), `system.gateway_auth`/`gateway_bye` (CL-C3), warm start
(CL-C4), in-run gap detection (CL-H1), per-row currency scaling (CL-H2,
CL-H3), two-sided reconcile (CL-H4), session-timezone trade dates (CL-M3),
the `clearing_meta` instance id and timezone guard, the close-snapshot
finality rules.

**Method:** every line of the files above was read. Findings marked
*(repro)* were reproduced with a scratch script against the tree at
`7d4a63d2`, driving `ClearingProcess._handle_message` with frames from the
engine's own builders (`make_trade_msg`, `make_eod_msg`) and, for H1, with
frames a real `Engine` (`tests/engine_harness.make_engine`) published.
*(measured)* means timed on this host against a ledger written by the real
`flush_batch`: 30 days × 100 000 trades (3.0 M `trade_events` rows), 300
gateways × 20 symbols (6 000 positions, 180 000 daily rows), 0.80 GB. The
other findings are by inspection, with line numbers given.

Status: **Done, uncommitted** (2026-11-14). Decisions Q1–Q3 taken as recommended. Last full suite 14 184 passed, 1 skipped; `make _check` and `mkdocs build` clean. Beyond the plan: the reconcile json fix (C2), the date-range limit of P2's fix, the `clearing.flush_failures` row in the dashboard design.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (rows in `clearing.db`, `session_events` entries, CLI
   output and exit code, log records, the health beacon's metrics).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_clearing_*.py`,
   `tests/test_api_gateway_clearing_*.py` and `tests/test_eod_*.py` with
   `-n logical`, then black/flake8/mypy/pyright. Do not start the next WP with
   a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Process tests build `ClearingProcess` on a `tmp_path` database and feed it
frames from the engine's builders through `_handle_message`, as
`tests/test_clearing_main.py` does; end-of-day frames come from
`make_eod_msg([book.snapshot() …])` of a real `OrderBook`. Transport tests use
`tests/clearing_harness.py` (real PUB/SUB, real `run()`). A test that needs
"pm-clearing as its own process" clears `models.price`'s registry, since
nothing registers tick precision in pm-clearing.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-CLR01 | End-of-day marks keep each position's precision | H1, D8 | — | 0.5 d | ☑ | 2026-11-14 |
| 2 | WP-CLR02 | A trade missed while pm-clearing was down is reported | H2, D9 | Q1 | 0.75 d | ☑ | 2026-11-14 |
| 3 | WP-CLR03 | A failing write is visible and loses nothing silently | C1, C9 | Q3 | 0.5 d | ☑ | 2026-11-14 |
| 4 | WP-CLR04 | The feed thread never draws tables; a deep receive buffer | P1, C10 | Q2 | 0.25 d | ☑ | 2026-11-14 |
| 5 | WP-CLR05 | pm-clearing-cli says what is true | C2–C8, C11, D10 | — | 0.75 d | ☑ | 2026-11-14 |
| 6 | WP-CLR06 | One day's trades are read from that day | P2 | — | 0.25 d | ☑ | 2026-11-14 |
| 7 | WP-CLR07 | Comments, docstrings, help texts, guides | D1–D7 | WP-CLR01–06 | 0.5 d | ☑ | 2026-11-14 |

Suggested order: **WP-CLR01 → WP-CLR02 → WP-CLR03 → WP-CLR04 → WP-CLR05 →
WP-CLR06 → WP-CLR07**. WP-CLR01 and WP-CLR02 fix positions that pm-eod
settles. WP-CLR03 builds on WP-CLR02: trades lost at a failing shutdown
become a reported gap through WP-CLR02's start-up check. WP-CLR04 is a
default change. WP-CLR05 and WP-CLR06 are read-side. WP-CLR07 goes last so
every text describes the code as it ends up.

Estimated sequential effort: about 3.5 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The **ledger** is sound. Every position transition (open, add, reduce,
close to flat, cross zero in both directions) realises P&L on the closed
quantity and resets the average cost correctly (`ledger.py:151-215`); a
precision change converts the position and the pending deltas first (K6);
re-marking every holder of a symbol on each trade keeps unrealised P&L
current for positions that did not trade. The **flush** is one SQLite
transaction, and a failed one rebuilds the ledger from the committed rows
(`main.py:606-623`). **Dedup** is decided once, against `trade_events`, so a
replay is never counted twice. **Warm start** is fatal on failure. The close
snapshot's finality rules hold in compressed mode, after an engine restart
and without a scheduler. Throughput is 7 000 trades/s at 300 gateways × 20
symbols *(measured)* with the console table off.

The defects are in four places:

- **End-of-day marks (H1).** pm-clearing converts the book's last price
  with a tick registry it never fills, so every symbol is taken as two
  decimals. A 4-decimal position is re-marked at 1/100 of its price at every
  engine shutdown: a 100-share position bought at 1.2345 shows −122.22
  unrealised, and the close snapshot pm-eod settles carries it.
- **Trades that never arrive (H2, C1).** The gap detector lives in memory,
  so a pm-clearing restart hides every trade made while it was down: the
  position is short, there is no `GAP` row, and `reconcile` is clean.
  Trades buffered when a write fails are lost at shutdown the same way,
  after one WARNING per trade.
- **The feed thread (P1, C10).** With the default `--print-every 100` the
  receive thread draws a table of every position: 3.9 s per draw at 6 000
  positions, a ceiling of about 26 trades/s, on a socket with ZMQ's default
  1 000-message high-water mark (pm-audit uses 200 000, pm-stats 100 000).
- **pm-clearing-cli (C2–C8, C11).** `reconcile` without
  `--retention-days` reports every pruned day as a discrepancy (the
  participant guide says to escalate any row); floats print with six
  significant digits; impossible dates pass; `prune` creates a database at a
  mistyped path and does not VACUUM as its help says.

Severity key: **High**: positions or P&L wrong without a warning, and
settled. **Med**: a wrong or misleading figure; a failure that is invisible
to its supervisor or loses data on a fault. **Low**: hardening, clarity,
hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| H1 | High | EOD | `system.eod` marks a 4-decimal position at the 2-decimal tick value of its price: 12345 → 123 ticks; a 100-share long at 1.2345 shows −122.22 unrealised (counterparty +122.22), written to positions and to the shutdown close snapshot *(repro)* | CLR01 |
| H2 | High | Feed | A pm-clearing restart hides the trades made while it was down: trades 6–10 of 15 missing, GW01 net 100 instead of 150, 0 `GAP` rows, `reconcile` clean *(repro)* | CLR02 |
| C1 | Med | Flush | A failing write logs a WARNING per trade (401 records for 500 trades), the buffer grows without bound, the health ping stays OK, and the shutdown flush raises and drops every buffered trade *(repro)* | CLR03 |
| C2 | Med | CLI | `reconcile` without `--retention-days` lists every pruned day (4 rows for 2 pruned days of a 7-day ledger); the participant guide says to contact operations on any row *(repro)* | CLR05 |
| C3 | Low | CLI | `reconcile` prints notionals in raw ticks (`100000` for 1 000.00) while every other verb normalises | CLR05 |
| C4 | Low | CLI | `_stringify` uses `%g`: `12345.67` → `12345.7`, `1234567.89` → `1.23457e+06` *(repro)* | CLR05 |
| C5 | Low | CLI | `validate_date` is a regex: `2026-02-30` is accepted and answers "No rows found." *(repro)* | CLR05 |
| C6 | Low | CLI | `prune` on a mistyped `--datapath` creates an empty `clearing.db` and reports "Pruned 0"; its help promises a VACUUM it never runs *(repro)* | CLR05 |
| C7 | Low | CLI | `store.open_readonly_connection` pastes the path into a URI unencoded and sets no `busy_timeout` (`query.py`'s opener does both); `health`'s `mode=rw` connect likewise | CLR05 |
| C8 | Low | CLI | `health --extended`'s "read/write" check writes only a TEMP table, which never touches `clearing.db` | CLR05 |
| C9 | Low | Loop | EINTR from `poll` ends the receive loop (`break`) and pm-clearing exits 0 | CLR03 |
| C10 | Low | Feed | The trade subscriber keeps ZMQ's default 1 000-message high-water mark | CLR04 |
| C11 | Low | CLI | `trades` hides `match_type` and `msg_id`, which are stored and selected | CLR05 |
| P1 | Low | Loop | `--print-every 100` (the default, and `pm-emo`'s nominal stack) draws every position on the receive thread: 65 ms / 1.5 s / 3.9 s per draw at 100 / 2 000 / 6 000 positions *(measured)* | CLR04 |
| P2 | Low | Query | `trades --date D` walks the timestamp index from the newest trade back to D: 1 ms for the newest day, 728 ms for the oldest of 30; grows with retained history *(measured)* | CLR06 |
| D1–D10 | — | Comments | See §5 | CLR01, 02, 05, 07 |

---

## 3. Correctness findings

### H1. End-of-day marks ignore the book's precision *(repro)* — High

`main.py:767-784` `_handle_eod`:

```python
if last_price is not None:
    eod_marks[sym] = to_ticks(last_price, sym)
elif bids and asks:
    eod_marks[sym] = (to_ticks(bids[0].price, sym) + to_ticks(asks[0].price, sym)) // 2
```

`to_ticks` scales by the symbol's registered precision and answers 2 for an
unknown symbol (`models/price.py:40-42`, `:63-75`). Nothing in pm-clearing
registers one: the gateways do (`alf_gwy/gateway.py:1753`,
`balf_gwy/gateway.py:1204`, `api_gateway/engine_client.py:672`), pm-clearing
never does. The `EodBook` record carries the scale its prices were produced
at (`spec/messages/system.yaml:502`, `tick_decimals`), and the handler does
not read it. The mark is then applied to positions held in ticks of their
own precision (`main.py:793-800`), without the `_rescale_position` the trade
path uses.

Reproduced: a real `Engine` with `FX4` at `tick_decimals: 4`, GW01 buys 100
from GW02 at 1.2345; its `trade.executed` and `make_eod_msg([book.snapshot()])`
frames go to a `ClearingProcess` with an empty registry:

| | mark (ticks) | unrealised (ticks) | unrealised (currency) |
|---|---|---|---|
| GW01 after the trade | 12345 | 0 | 0.00 |
| GW01 after `system.eod` | **123** | **−1 222 200** | **−122.22** |
| GW02 after `system.eod` | **123** | **+1 222 200** | **+122.22** |

The same rows land in `position_close_snapshot` when the shutdown is the
close (no scheduler, `main.py:819-820`). With a scheduler the snapshot taken
at `CLOSED` is final and kept, but the wrong marks stay in
`gateway_symbol_positions`: the next day's close copies them for every
holder of a symbol that does not trade that day, and pm-eod settles the
difference. Until then pm-api-gwy's `/positions` and the clearing GUI show
them. Every symbol with a precision other than 2 is affected, in either
direction (0 decimals: ×100).

**Fix.** Convert with the book's own `tick_decimals`
(`to_ticks_exact_at`) and bring each mark to the position's precision before
applying it, as `_remark_symbol` does.

### H2. A restart hides the trades it missed *(repro)* — High

`main.py:625-674` `_check_sequence_gap` keeps the last seen
`(run_seq, seq)` in `self._last_seq`, which starts as `None` in every
process. The first trade after a start is never compared with anything, so
trades published while pm-clearing was down (a crash, an upgrade, `pm-opctl`
restarting it) leave no trace.

Reproduced: trades `000003-1…5` to one `ClearingProcess`, the process
closed, trades 6–10 published to nobody, a new `ClearingProcess` on the same
file receives 11–15:

```
archived ids: 01 02 03 04 05 11 12 13 14 15
GAP rows: 0
GW01 net_qty: 100 (engine: 150)
reconcile discrepancies: 0
```

The position is wrong by the missing trades, for good: nothing replays the
engine's tape, `reconcile` compares two records that both lack them, and the
GUI's feed-gap alert stays green. pm-eod settles the short position. The
operator guide calls a restart against an existing file "safe"
(`010-persistence.md:687`) and says a missing gap is "only the absence of
evidence" (`080-clearing-gui.md:97-98`), but nothing tells the operator that
a restart *is* such a hole.

`trade_events` already holds the evidence: the highest archived sequence of
the current run. A first trade of the same run that jumps past it is a gap,
and so is one of a later run when the previous run's tail never arrived — the
second needs the engine to say where its run ended (§9).

**Fix.** See Q1.

### C1. A failing write is noisy, unbounded, invisible and lossy *(repro)* — Med

`main.py:507-508`, `:676-717`, `:540-552`, `:393-401`. When `flush_batch`
raises (a full disk, a lost mount), `_flush` rebuilds the ledger and
re-raises. The buffer is kept for a retry, which is right, but:

- on the receive thread, every trade after the buffer reaches `flush_size`
  retries the flush (with a full `fetch_all_positions` each time) and logs
  `error handling trade.executed` at WARNING; the timer thread adds one every
  half second;
- the buffer grows without bound;
- the health ping and the beacon (`clearing.trades_settled` merely stops
  growing) both stay green;
- at shutdown, `run()`'s `finally` calls `_force_flush()`, which raises:
  the buffered trades are gone, the connection is not closed, and the exit is
  a traceback.

Reproduced with `flush_batch` raising `database or disk is full`: 500 trades
→ 401 WARNING records, `len(buffer) == 500`, and the shutdown flush raises
with all 500 unwritten. As with H2, nothing records the loss afterwards.

**Fix.** See Q3.

### C2. `reconcile` reports pruned days *(repro)* — Med

`cli.py:436-445`, `store.py:1688-1691`. The retention guard is applied only
when `--retention-days` is given; without it every day whose raw trades were
pruned (a 7-day window in the AI-sim profile, `emo/cli.py:454-460`; 90 by
default) is a discrepancy. Reproduced: trades 10, 9 and 0 days old, the
close's prune with a 7-day window, then `pm-clearing-cli reconcile`: four
rows, each `raw_qty 0` against `summary_qty 10`. The participant guide's
recipe is a bare `pm-clearing-cli reconcile` followed by "If the reconcile
output shows rows, contact the EduMatcher operations team"
(`010-positions-and-pnl.md:1490-1495`). pm-api-gwy already does this right:
it bounds the comparison by `query_retained_from`
(`api_gateway/routers/clearing.py:976-980`).

**Fix.** Default the CLI's lower bound to the oldest retained raw date and
say "N day(s) before <date> not reconciled (raw trades pruned)".

### C3. `reconcile` prints ticks — Low

`cli.py:193-204`, `:238-273`. `reconcile` is not in `_NORMALIZE_FIELDS` and
its column list has no `tick_decimals`, so `raw_notional`, `summary_notional`
and `notional_diff` print as integer ticks (`100000` for 1 000.00 above)
next to verbs that print currency.

### C4. Six significant digits — Low

`cli.py:531-536` `_stringify` formats floats with `%g`: `12345.67` prints as
`12345.7`, a notional of `1234567.89` as `1.23457e+06`. The same defect was
fixed in pm-stats-cli (stats review C3) and pm-index-cli (index review C13).

### C5. Impossible dates pass — Low

`store.py:910-915` `validate_date` is `\d{4}-\d{2}-\d{2}`; `2026-02-30`
passes and every date-filtered verb answers "No rows found." instead of a
usage error (lessons A5). `stats.query.validate_date` round-trips the date.

### C6. `prune` creates what it should refuse, and does not VACUUM — Low

`cli.py:766-794`. `_open_writer` is `open_writer_connection`, which makes the
directory and the file (`store.py:430-431`). Reproduced:
`pm-clearing-cli --datapath <typo>/clearing.db prune --days 30` creates a
118 KB database there and prints "Pruned 0 trade_events rows". The help says
"Delete trade_events rows older than N days (default: 90) and VACUUM"
(`cli.py:493`); there is no VACUUM, so the file does not shrink.

### C7. Two read-only openers, one unsafe — Low

`store.py:472-478` builds `file:{db_path}?mode=ro` from the raw path and sets
no `busy_timeout`; `query.py:42-61` percent-encodes the path (a `?` in it
would otherwise end the path early and drop `mode=ro`) and waits 5 s for a
checkpoint lock. pm-clearing-cli uses the first; `health --extended` builds
`file:{db_path}?mode=rw` the same way (`cli.py:836`).

### C8. The "read/write" health check never writes the file — Low

`cli.py:849-852` creates, fills and rolls back a `TEMP` table, which lives
in SQLite's temporary store, never in `clearing.db`; a read-only mount or a file pm-clearing cannot write passes
(lessons A2).

### C9. EINTR stops pm-clearing — Low

`main.py:448-453`: a `ZMQError(EINTR)` from `poll` breaks the loop, `run()`
returns and the process exits 0 without having been stopped. The same
pattern was fixed in pm-audit, pm-stats and pm-index (index review C9).

### C10. A shallow receive buffer — Low

`main.py:362-384` subscribes without `rcvhwm`, so the socket drops at ZMQ's
default of 1 000 queued messages. pm-audit (`audit/main.py:103`, 200 000) and
pm-stats (`stats/main.py:242`, 100 000) raised theirs for the same feed. A
3 000-trade burst to a separate process was absorbed (kernel buffers plus
both high-water marks), so no loss was reproduced; with P1 the consumer's
ceiling is about 26 trades/s, and a sustained rate above it fills any buffer.

### C11. Stored, never shown — Low

`store.py:1078-1081` selects `match_type` and `msg_id`; `cli.py:101-115`
leaves both out of `trades`, so the link from a trade to its audit line is
not visible from the CLI (lessons A7).

---

## 4. Performance findings

At today's sizes only P1 matters, and only for a large ledger with the
default flag. Measured on the 0.80 GB synthetic ledger described above.

### P1. The console table on the feed thread *(measured)* — Low

`main.py:509-518`, `:1002-1050`. Every `--print-every` trades (default 100,
`main.py:1127-1133`), the receive thread flushes, copies every position and
renders a rich table of all of them. `pm-emo`'s nominal stack runs
`pm-clearing --verbose` with that default (`emo/cli.py:216-218`); the AI-sim
profile passes `--print-every 0`.

| positions | one table | output | trade ceiling with the default |
|---:|---:|---:|---:|
| 100 | 65 ms | — | ~1 500/s |
| 2 000 (100 gw × 20) | 1.51 s | 0.3 MB | ~66/s |
| 6 000 (300 gw × 20) | 3.86 s | 1.0 MB | ~26/s |

Without the table the same ledger handles 7 060 trades/s (25 600/s at 10 ×
20). The cost grows with the number of positions, not with the day.

**Fix.** See Q2.

### P2. One day's trades walk the whole archive *(measured)* — Low

`store.py:1055-1109` `query_trades` (the `trades` verb and pm-api-gwy's
`GET /clearing/trades`). The optional filters stay in their
`(:x IS NULL OR …)` form, so the planner walks `ix_trade_events_ts` from the
newest trade down to the requested day:

| query | newest day | oldest of 30 |
|---|---:|---:|
| `trades --date D` | 1 ms | 728 ms |
| `trades --date D --gateway G007` | 8 ms | 921 ms |

Plan: `SCAN trade_events USING INDEX ix_trade_events_ts` in both. The cost
grows with the number of retained days after D (about 2.2 s for the oldest
day of a 90-day window). `daily`, `symbols`, `reconcile` (0.4 s for one day,
constant) and `dates` (0.18 s) do not grow per day.

**Fix.** Resolve the unset filters (`_drop_unset_filters`, as the snapshot
and reconcile queries already do) and add `(trade_date, ts_ns, ingest_ts_ns,
id)` so one day is read from its own index range in order.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `store.py:14-20` | "`trade.price` arrives from the engine as an integer (raw int, no implicit decimal scaling)": it is a display float, converted at ingress (`main.py:166-170`); the design doc corrected this in §17.2, the module docstring did not. |
| D2 | `main.py:197-198` | `retention_days` "pruned on startup": also at every `CLOSED` and every `system.eod`. |
| D3 | `main.py:960-964`, `:978-980` | The disconnect handler flushes "before the engine cancels its resting orders" / "before the engine-side order cancellations arrive": a cancellation produces no trade, and the flush has no bearing on it. |
| D4 | `main.py:259-261`, `:949`, `:975` | `_gw_connect_ts` is written and popped, never read ("housekeeping only"). |
| D5 | `ledger.py:287` | `log.debug("ledger restored positions=%d", …)` is inside the loop: one line per position, each with the total. |
| D6 | `main.py:1161-1166` | `-q/--quiet` "Reduce log output to warnings/errors": WARNING is already the default, so the flag does nothing. |
| D7 | `cli.py:309-313` | `--no-header` "Suppress header row for csv output": also suppresses the table header (`cli.py:554`). |
| D8 | training guide `120-pnl-clearing.md:479-486`, `:520-527` | The EOD pass "writes updated positions … so `end_unrealized_pnl` in `gateway_daily_summary` reflects the official EOD mark": it writes position rows only (`main.py:805-808`, no daily rows). "The two differ when a symbol did not trade at all that day: then the EOD pass marks it at the mid": the book keeps its last trade price across days and restarts (`order_book.py:1053-1064`), so the mid is used only for a symbol that never traded. |
| D9 | operator guide `010-persistence.md:94`, `:687` | `clearing.db` is written "Per trade" (it is written per batch: 100 trades or 5 s); "restarting against an existing file is safe" says nothing of the trades made while pm-clearing is down (H2). |
| D10 | participant guide `010-positions-and-pnl.md:1185`, `:1490-1495` | The recipe is a bare `reconcile` and "contact operations" on any row (C2). |

---

## 6. Verified as correct

- **Position transitions.** Open, add (VWAP), reduce, close to flat and
  cross zero both ways realise P&L on the closed quantity and reset the
  average cost (`ledger.py:151-215`); unrealised P&L is recomputed at the
  fill price and every other holder of the symbol is re-marked.
- **Precision changes (K6).** Positions, pending deltas and stored daily
  rows are converted to the latest trade's precision before the fill, in the
  ledger and in the upsert.
- **Durable dedup.** `_unarchived` checks `trade_events` once per chunk at
  flush time; the LRU is only a fast path. A replay, after a restart or with
  a changed timestamp, is never applied twice.
- **Atomic flush and ledger rollback.** One transaction; a failure rebuilds
  the ledger from the committed rows and marks it stale until the rebuild
  succeeds.
- **Warm start.** All persistent columns are restored; a failure is fatal
  (K5).
- **Trade ids.** One publish site per trade (`engine/main.py:3651-3656`) and
  a run sequence that only grows (`engine/persistence.py:69-87`); nothing in
  `pm-opctl-cli clear` resets `engine_run_seq.json`, and `clear --state`
  removes `clearing.db` with the state, so ids cannot repeat into a live
  ledger. The in-run gap check therefore has no false alarms.
- **Close snapshots.** Finality is judged before the new `PHASE` row is
  recorded, so the boot-time `CLOSED`, a second fast day under
  `--speed`, a mid-day restart and a shutdown without a scheduler each write
  a provisional snapshot, and the day's real close is never replaced.
- **Session timezone.** Recorded in `clearing_meta` and enforced at start;
  `trade_date` comes from the engine's timestamp in that zone.
- **Reconcile.** Two-sided (summary-only keys surface), precision-aware,
  exact integer comparison.
- **Throughput.** 39 µs/trade at 10 × 20 and 142 µs/trade at 300 × 20,
  flushes included *(measured)*.

---

## 7. Decisions

Taken 2026-11-14 (Johan): Q1, Q2 and Q3 as recommended.

| # | Question | Recommendation |
|---|---|---|
| Q1 | H2: what should pm-clearing do about trades it never received across a restart? (a) **detect**: at start read the highest archived sequence of the newest run; a first trade of that run that jumps past it records a `GAP` (`reason: restart`) and logs ERROR; (b) detect and **backfill** from pm-audit's archive; (c) ask the engine to **replay**. | **(a)** for 1.0. It turns a silent hole into the GUI's red alert, the `gaps` verb and an ERROR, with the missing id range, using data clearing already has. (b) is right in principle but not a patch: applying the missing trades after later ones gives different average costs and realised P&L, so a correct backfill rebuilds the ledger from the start of retention — a "rebuild from the audit trail" tool, For-Later. (c) needs an engine tape it does not keep. The tail of a run (trades lost just before an engine stop) needs the engine to announce its last id; §9. |
| Q2 | P1: the console table. (a) default `--print-every 0`; (b) keep 100 but print gateway totals only; (c) move the drawing to the timer thread. | **(a)**. A money process's feed thread should not render; the table is a classroom aid (the training guide asks for `--print-every 1` explicitly, which still works). (b) still scans every position on the feed thread; (c) moves the stall to the thread that holds the flush lock. |
| Q3 | C1: on a failing write. (a) keep buffering, log ERROR once per outage (and once when it recovers), publish a `clearing.flush_failures` counter, and at shutdown with an unwritten buffer log CRITICAL with the count and id range and exit non-zero; (b) exit at the first failed flush so a supervisor restarts it. | **(a)**. The buffer survives a transient fault, the beacon makes the outage visible, and with WP-CLR02 the lost range becomes a `GAP` on the next start. (b) loses the buffer at the first hiccup and, with H2 open, silently. |

---

## 8. Work packages

Each WP lists the tests to write first, the production change, and the exit
criteria. Test files are existing ones unless marked new.

### WP-CLR01 — End-of-day marks keep each position's precision (H1, D8)

**Tests first** (`tests/test_clearing_tick_precision.py`):

1. A real engine's 4-decimal trade at 1.2345 and its `make_eod_msg`, fed to
   a `ClearingProcess` with an empty precision registry: the mark stays
   12345 and unrealised P&L 0.0, in positions and in the shutdown close
   snapshot. (Fails today: 123, −1 222 200.)
2. The same for 0 decimals (fails today ×100) and a book with no trade
   (mid of best bid and ask at the book's precision). (Fails today.)
3. A position recorded at 2 decimals and a book now at 4: the mark is
   brought to the position's precision (or the position to the book's, as
   the trade path does), and money is unchanged.
4. 2-decimal symbols: marks unchanged.

**Change.** `_handle_eod` converts with `book.tick_decimals`
(`to_ticks_exact_at`) and applies each mark through the ledger's rescaling.
Training guide `120`: what the EOD pass writes and when the mid is used.

**Exit criteria.** Tests pass; `tests/test_clearing_*.py`,
`tests/test_eod_*.py` green.

**Outcome (2026-11-14).** `_handle_eod` converts each book's `last_price`
(or its bid/ask mid) at the book's own `tick_decimals` (rounded, not
`to_ticks_exact_at`: one off-grid price must not abort the whole pass) and
marks through the new `Ledger.mark_symbol`, which converts each position to
the mark's precision first, flat ones included as before. The unused
`to_ticks` import went. Tests in `test_clearing_tick_precision.py`: the
real-engine 4- and 0-decimal cases, the mid and the precision-change cases
failed first (`123 == 12345`, `12300 == 123`, `2 == 4`); the 2-decimal case
passed before and after. Training guide `120`: what the EOD pass writes, when
the mid is used, the close snapshot without a scheduler. `make _check` clean;
full suite 14 157 passed, 1 skipped.

### WP-CLR02 — A trade missed while pm-clearing was down is reported (H2, D9; after Q1)

**Tests first** (`tests/test_clearing_durable_dedup.py` or new
`tests/test_clearing_restart_gap.py`):

1. The H2 repro: trades 1–5, restart, trades 11–15 → one `GAP` row
   `{run_seq: 3, last_seq: 5, next_seq: 11, missing_trades: 5, reason:
   "restart"}` and an ERROR. (Fails today.)
2. Restart, then trade 6 → no gap. Restart, then a trade of a new run → no
   gap (the run boundary is §9).
3. An empty ledger: no gap. Pruned history of the run: compared with what
   is retained, no false alarm.
4. `pm-clearing-cli gaps` and pm-api-gwy's feed-gap route show the new row.

**Change.** `ClearingProcess.__init__` seeds `_last_seq` from the newest
archived id; `_check_sequence_gap` records the reason. Operator guide
`010-persistence` (restart), `080-clearing-gui` (what a restart gap means and
what to do).

**Exit criteria.** Tests pass; clearing and API clearing suites green.

**Outcome (2026-11-14).** `store.latest_trade_seq` reads the newest
engine-shaped id from the primary key (`GLOB` skips ids of another shape);
`ClearingProcess.__init__` seeds `_last_seq` with it, so the first trade
after a start is compared with the last stored one. Each `GAP` payload and
log line carries `reason` (`restart` for that first comparison, `feed`
after); `query_feed_gaps` and the `gaps` verb show it. pm-api-gwy's
`GapPayload` ignores the new key (pydantic's default), so the REST contract
is unchanged. New `tests/test_clearing_restart_gap.py`: the restart case,
the `reason` of an in-run gap and the `gaps` verb failed first; the
contiguous restart, the new run, the empty ledger and the pruned-history
cases passed before and after. `test_clearing_cli.py`'s gap rows gained
`reason: None` (rows written before this change). Ledger entry text updated.
Operator guide: persistence (write cadence, what a restart loses and how it
shows), the clearing GUI's feed-gap line. Full suite 14 164 passed, 1
skipped; `make _check` clean.

### WP-CLR03 — A failing write is visible and loses nothing silently (C1, C9; after Q3)

**Tests first** (`tests/test_clearing_resilience.py`):

1. `flush_batch` raising for 500 trades: one ERROR record, not one per
   trade; `metric_samples()` carries `clearing.flush_failures` ≥ 1. (Fails
   today.)
2. The fault clears: the buffer is written once, an INFO says so, and the
   counter stops.
3. Shutdown with the fault still present: CRITICAL with the count and the
   first and last id, the connection closed, `main()` exits non-zero.
   (Fails today: traceback.) With WP-CLR02, the next start reports the range
   as a gap.
4. `poll` raising EINTR once: the loop continues. (Fails today.)

**Change.** Latch the flush error in `_flush`'s callers, add the counter to
`metric_samples`, guard the shutdown flush, EINTR `continue`s. New ledger
entries for the new log lines.

**Exit criteria.** Tests pass; `test_log_ledger.py` green.

**Outcome (2026-11-14).** `_try_flush` wraps the receive-loop and timer
flushes: a failure counts in the new `clearing.flush_failures` beacon
counter, restarts the flush interval (so the timer retries once per
interval) and logs one ERROR per outage; while it lasts, the receive loop no
longer retries on every trade. `_flush` logs "clearing writes recovered"
when a write succeeds after a failure, whichever path made it (`flush_now`,
EOD, the close). The shutdown flush moved into `_shutdown`, which logs the
unwritten trades' count and id range at CRITICAL, closes the connection and
sets `unwritten_trades`; `main()` then exits 1. The old `_force_flush` and
the timer's per-tick WARNING went. EINTR `continue`s. Two ledger entries:
the timer warning replaced by the latched ERROR, and the CRITICAL. Tests in
`test_clearing_resilience.py`: all five failed first (401 WARNINGs, no
metric, no `_shutdown`, no `SystemExit`, the loop stopping after EINTR); the
existing timer-retry test passes unchanged. Full suite 14 169 passed, 1
skipped; `make _check` clean.

### WP-CLR04 — The feed thread never draws tables; a deep receive buffer (P1, C10; after Q2)

**Tests first** (`tests/test_clearing_main.py`):

1. `build_parser().parse_args([]).print_every == 0`. (Fails today.)
2. `--print-every 1` still prints a table after each trade.
3. The trade subscriber is made with `rcvhwm` ≥ 100 000 (patched
   `make_subscriber` records it). (Fails today.)

**Change.** Default 0; `rcvhwm` as pm-stats; help text, `pm_help`
registry, reference manual and operator guide tables;
`make completion`.

**Exit criteria.** Tests pass; `test_shell_completion` green.

**Outcome (2026-11-14).** `_PRINT_EVERY = 0` is the default of both
`--print-every` and the constructor; `_SUB_RCVHWM = 100_000` (as pm-stats) on
the trade subscriber. `pm-emo`'s nominal stack therefore no longer draws
tables; the training guide's `--print-every 1` still does (the existing
cadence test passes unchanged). Help text, `pm_help` registry, the operator
guide's option table, the reference manual, the participant guide's help copy
and the AI-traders setup table updated; `make completion`. Both new tests in
`test_clearing_main.py` failed first (`100 == 0`, no `rcvhwm`). Full suite
14 171 passed, 1 skipped; `make _check` clean.

### WP-CLR05 — pm-clearing-cli says what is true (C2–C8, C11, D10)

**Tests first** (`tests/test_clearing_cli.py`):

1. A 7-day-retention ledger with two pruned days: bare `reconcile` prints
   "OK" and "2 day(s) before <date> not reconciled (raw trades pruned)";
   `--from` inside the pruned range says the same. (Fails today.)
2. `reconcile` prints notionals in currency, with `--raw-output` in ticks.
   (Fails today.)
3. `positions` prints `12345.67` and `1234567.89` in full. (Fails today.)
4. `--date 2026-02-30` is a usage error, exit 2. (Fails today.)
5. `prune` on a missing database: error, exit 1, no file created; `prune`
   on a real one shrinks it (VACUUM) or the help no longer says so. (Fails
   today.)
6. A data directory whose path contains `?` opens the right file read-only.
   (Fails today.)
7. `health --extended` on a read-only copy of `clearing.db` reports the
   database as not writable. (Fails today.)
8. `trades` shows `match_type` and `msg_id`. (Fails today.)

**Change.** Retained-range guard by default (as pm-api-gwy), reconcile
normalisation, `%.15g`, a round-tripping date check (`stats.query.validate_date`),
`prune` refuses a missing file and VACUUMs (or drops the claim — say which in
the outcome), one read-only opener (`query.open_readonly_connection`), a
write check inside a rolled-back transaction on a real table, the two
columns. Participant guide recipe.

**Exit criteria.** Tests pass; `make completion` if help text changed.

**Outcome (2026-11-14).** New `tests/test_clearing_cli_truth.py`; 12 of its
13 tests failed first (the writable-health case passed before and after).
- C2: `reconcile` starts at `query_retained_from` (as pm-api-gwy) and prints
  "N day(s) before <date> not reconciled (raw trades pruned)" from the new
  `store.count_summary_days`. The "OK" and that line go to stdout for the
  table and to stderr for json/csv, which also fixes a json output that
  began with "OK — …" (the participant guide documented the workaround).
  `--retention-days` still narrows further.
- C3: reconcile money normalised; `tick_decimals` column added.
- C4: `%.15g`.
- C5: `stats.query.validate_date`; `store.validate_date` (left unused) and
  its three tests removed.
- C6: `prune` refuses a missing database; the VACUUM claim is dropped rather
  than VACUUMing a live ledger under pm-clearing's writer (help and training
  guide say the file keeps its size).
- C7: `store.open_readonly_connection` delegates to
  `query.open_readonly_connection`, so pm-eod gets the encoded path and the
  busy timeout too; `health`'s `mode=rw` connect is encoded.
- C8: the health write check takes `BEGIN IMMEDIATE` on `clearing.db` and
  inserts into `clearing_meta` before rolling back.
- C11: `trades` shows `match_type` and `msg_id`.
- Participant and training guides updated; `make completion`. Full suite
  14 181 passed, 1 skipped; `make _check` clean.

### WP-CLR06 — One day's trades are read from that day (P2)

**Tests first** (`tests/test_clearing_day_queries.py`):

1. The executed SQL of `query_trades(date_value=D)` (captured with
   `set_trace_callback`) plans as `SEARCH … USING INDEX` on a
   `trade_date`-led index, not `SCAN … ix_trade_events_ts`. (Fails today.)
2. Paging with `after` returns the same rows in the same order as before,
   with and without a date.
3. Bench in the outcome: `trades --date <oldest>` on the 30-day bench
   ledger ≤ 20 ms (a guess; report the measurement).

**Change.** `_drop_unset_filters` in `query_trades`; index
`(trade_date, ts_ns, ingest_ts_ns, id)`; `make dbdocs`.

**Exit criteria.** Tests pass; `make _check` (dbdocs) clean.

**Outcome (2026-11-14).** `ix_trade_events_date(trade_date)` became
`ix_trade_events_date_ts(trade_date, ts_ns, ingest_ts_ns, id)`; its prefix
serves every other day-scoped read and the prune (an existing ledger keeps the
old index as well: no migration code). `query_trades` resolves its unset
filters only for a single `date_value`. Found on the way: resolving them
always made the GUI's newest-first page for one gateway use the two gateway
indexes and sort all of that gateway's trades
(`test_a_page_reads_the_sort_index_not_the_whole_table`, F2, failed), and a
`--from/--to` range would sort the whole range; both keep the
`ix_trade_events_ts` walk. Both plan tests in `test_clearing_day_queries.py`
failed first; the paging test passed before and after. Bench on the 30-day
ledger: `trades --date <oldest>` 728 → 1.4 ms, with `--gateway` 921 →
9.6 ms (target ≤ 20 ms met); the newest-first gateway page stays at 8 ms.
`make dbdocs`. Full suite 14 184 passed, 1 skipped; `make _check` clean.

### WP-CLR07 — Comments, docstrings, help texts, guides (D1–D7)

**Change.** Fix D1–D7 as listed in §5; reread the clearing passages of the
operator, participant and training guides against the code as it ends up
(EOD marks, restart gaps, flush failures, the table default, reconcile).

**Exit criteria.** `mkdocs build` clean; a reread of every module and class
docstring in `src/edumatcher/clearing/*.py` finds nothing stale.

**Outcome (2026-11-14).** D1 (`store.py` price note), D2 (retention
docstring), D3 (disconnect handler: the flush is about the session's trades,
not order cancellations), D5 (one restore log line), D6 (`-q`), D7
(`--no-header`) as listed. D4 was wrong as written: `_gw_connect_ts` is not
read in production, but `tests/clearing_harness.py` and
`test_clearing_main.py` use it as their readiness probe, so removing it
failed 27 tests; it stays, with a comment saying exactly that. The reread
also updated `main.py`'s module docstring (prunes at EOD; failed writes;
restart gaps) and `_handle_eod`'s action list. Guides re-walked: the training
guide's first-trade chapter said the table prints every 100 trades by
default (now none); the operator-dashboard design lists
`clearing.flush_failures`. `make completion`; `mkdocs build` clean; full
suite 14 184 passed, 1 skipped.

---

## 9. Out of scope, noted

- **The tail of an engine run.** Trades lost just before an engine stop
  cannot be detected by clearing: the next run starts a new sequence. The
  engine's `system.eod` could carry the run's last trade id, so a subscriber
  can check it has everything; For-Later **L022**.
- **Rebuilding `clearing.db` from the audit trail** (Q1 (b)): a tool that
  replays `trade.executed` from pm-audit's archive into a fresh ledger,
  the only way to repair positions once a gap is known; For-Later **L023**.
- `position_close_snapshot` is never pruned: already **L019**.
- `pm-clearing-cli health -q` exits −1 (status 255): already **L017**.
- `query_health` counts `trade_events` (0.18 s at 3 M rows, grows with
  retention); it backs an on-demand route, not a poll, so it is noted, not a
  finding.
- pm-api-gwy's clearing routes share P2 and get WP-CLR06's fix through
  `query_trades`; their own code was not reviewed.

# pm-stats / pm-stats-cli Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/stats/` at `b57d2f9f` (v0.78.4): `main.py`
(2 584 lines, pm-stats), `query.py` (990), `trading_day.py` (123),
`event_types.py` (42), and pm-stats-cli's `cli.py` (829). `query.py` and
`trading_day.py` are shared: pm-api-gwy's history and bootstrap routers,
pm-eod, pm-ticker, pm-viewer, pm-monitor and pm-sim-forensics read through
them. `audit/replay/stats.py` is not part of pm-stats and was not reviewed.

**Focus:** correctness, edge-case handling, performance, and whether the
comments and help texts are correct and helpful.

**Previous work:** `docs-design/EduMatcher-Stats-Review.md` (2026-06, P0-1 …
P2, GAP), the sim-forensics recorder findings (X4, X6, X7, S26) and the
K9 key-component fixes (trade-id dedupe, index `seq`). Their fixes are in
place and are not repeated here: rehydration after a restart, WAL and
`busy_timeout`, the writer lock, schema versioning, trading-date bucketing
on event time, the truncation notice, gap detection.

**Method:** every line of the files above was read, plus the operator
guide's statistics chapter
(`part-4-run-a-market/060-statistics-and-reporting.md`) where the code's
behaviour is documented. Findings marked *(repro)* were reproduced with a
scratch script against the tree at `b57d2f9f`; *(measured)* means timed on
this host. The others are by inspection, with line numbers given.

Status: **Done, uncommitted.** WP-STA01–09 completed 2026-11-14; Q1–Q3
taken as recommended. Outcomes in §8.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (rows in `stats.db`, CLI output, exit code, metric).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_stats_*.py`,
   `tests/test_api_gateway_history*.py` and (for reader WPs)
   `tests/test_eod*.py` with `-n logical`, then black/flake8/mypy/pyright.
   Do not start the next WP with a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Recorder tests build `StatsProcess` with the three socket factories patched
(the `sp` fixture in `tests/test_stats_recorder_gaps.py`) and call the
handlers directly.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-STA01 | Rollups survive a day change in either direction | C1, C4, D10 | — | 0.5 d | ☑ | 2026-11-14 |
| 2 | WP-STA02 | Every recorder failure exits non-zero; index stream accounted | C2, C8, C13 | — | 0.5 d | ☑ | 2026-11-14 |
| 3 | WP-STA03 | Book and trade path write only what changed | P1, C12 | — | 0.5 d | ☑ | 2026-11-14 |
| 4 | WP-STA04 | Retention deletes in bounded batches | P2, P4 | — | 0.5 d | ☑ | 2026-11-14 |
| 5 | WP-STA05 | pm-stats-cli output: exact numbers, no silent truncation, every column | C3, C9, C10, D7, D8 | — | 0.5 d | ☑ | 2026-11-14 |
| 6 | WP-STA06 | `--to` bound and feed-gap rows say what they mean | C5, C6, D6 | Q1, Q2 | 0.5 d | ☑ | 2026-11-14 |
| 7 | WP-STA07 | Time-ordered trade reads use an index | P3 | Q3 | 0.25 d | ☑ | 2026-11-14 |
| 8 | WP-STA08 | Small items | C7, C11 | — | 0.25 d | ☑ | 2026-11-14 |
| 9 | WP-STA09 | Comments, docstrings, help texts, operator guide | D1–D9 | WP-STA01–08 | 0.5 d | ☑ | 2026-11-14 |

Suggested order: **WP-STA01 → WP-STA02 → WP-STA04 → WP-STA03 → WP-STA05 →
WP-STA08 → WP-STA06 → WP-STA07 → WP-STA09**. WP-STA01 is the only finding
that destroys stored figures. WP-STA02 and WP-STA04 decide whether pm-stats
keeps recording through a failure or a prune burst, and should land before
the next long simulation run. WP-STA06 and WP-STA07 wait for decisions
Q1–Q3. WP-STA09 goes last so every text describes the code as it ends up.

Estimated sequential effort: about 4 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The **storage model** is sound. Prices are exact integer ticks with the
scale on every row; each trade and its rollup commit in one transaction,
and the live accumulator is installed only after the commit; the rollup is
rebuilt exactly from `trade_log` after a restart (including the VWAP
numerator and the largest-trade tie-break); the writer lock, the schema
version and the recorded session timezone refuse every mixed-up database
rather than writing into it. The readers' keyset pagination is total and
type-checked, and trading dates resolve to half-open UTC ranges that are
right across DST.

The defects sit in four places:

- **One rehydration gap with a large blast radius (C1).** Rehydration runs
  only on the first touch of a symbol in a process. Any event that moves a
  symbol's accumulator to a *different* day than the one it holds, and then
  back, starts a blank accumulator and overwrites both days' rows with a
  handful of trades. The receipt-clock EOD (C4) is one way in.
- **Failure accounting (C2, C8).** A receive thread that dies while
  pm-stats is still waiting for the engine ends the process with status 0;
  the index stream's failures are not counted anywhere.
- **Write amplification and long transactions (P1, P2).** Every book
  message commits two no-op writes; the hourly prune deletes everything due
  in one transaction on the receive thread, long enough to overflow the
  SUB high-water mark under an AI swarm.
- **pm-stats-cli presentation (C3, C9, C10).** The table renderer rounds
  numbers to six significant digits, `gaps` truncates silently, and the
  `reject_code` the recorder has kept since schema 9 is never shown.

Severity key: **Med** — a wrong, lost or misleading figure, or a recorder
whose failure is invisible to its supervisor; **Low** — hardening,
clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| C1 | Med | Rollup | `_accum_for`/`_index_accum_for` rehydrate only on first touch; switching a symbol to another day and back starts blank accumulators and overwrites both days' `daily_stats` rows (volume 21 → 1 and 15 → 5 in the repro) *(repro)* | STA01 |
| C2 | Med | Recorder | `run()` returns 0 when the receive thread dies before the engine answered the symbols request (`main.py:2107`); a supervisor restarting on failure leaves pm-stats down | STA02 |
| C3 | Med | CLI | Table output prints floats with `%g`: `12345.67` shows as `12345.7`, `turnover` as `1.23457e+08`. Default format; the guide mentions it for `aggregate_cap` only *(repro)* | STA05 |
| C4 | Low | EOD | `_on_eod` files closing bid/ask under the *pm-stats host's* wall-clock trading date; an EOD handled after midnight writes a phantom next-day row and leaves the real day's closes NULL | STA01 |
| C5 | Low | Gaps | One drop on `trade.executed` writes two `feed_gaps` rows with the same `stream` in two different id spaces; `stats.feed_gaps` counts 2 and `SUM(missing_count)` doubles *(repro)* | STA06 |
| C6 | Low | Query | An inclusive `--to` without fractional seconds excludes a row stamped exactly `.000` of that second; documented in the guide, but `trading_day.py` claims text and instant comparison agree *(repro)* | STA06 |
| C7 | Low | CLI health | `health --extended`'s "read/write" check writes a TEMP table, which never touches `stats.db`: a read-only database passes *(repro)* | STA08 |
| C8 | Low | Recorder | Index-stream failures are logged at WARNING and counted nowhere; `stats.events_recorded` counts messages handled without an exception, including ignored, duplicate and malformed ones | STA02 |
| C9 | Low | CLI | `gaps` has no cursor and no truncation notice: more than `--limit` (500) gaps are cut silently, the exact failure the 2026-06 P0-3 fixed for every other command | STA05 |
| C10 | Low | CLI | `order-events`/`order-lifecycle` omit `reject_code` and `msg_id`; `trades` omits `match_type`, the order ids and `msg_id` (not even selected by `query_trades`) | STA05 |
| C11 | Low | Recorder | A trade without `id` is stored under trade_id `""`; every later one is then dropped as a duplicate | STA08 |
| C12 | Low | Recorder | After a mid-day tick-scale change, `_note_tick_decimals` logs ERROR on every message of that symbol (not latched) | STA03 |
| C13 | Low | Recorder | EINTR on `poll` ends recording and skips the drain | STA02 |
| P1 | Med | Book path | Every book message commits a `daily_stats` upsert (once an opening quote is known) and an `instruments` upsert; 18.4 µs → 4.3 µs per message without them *(measured)* | STA03 |
| P2 | Med | Retention | The prune deletes everything due in one transaction under the lock on the receive thread: 900 000 `order_events` rows took 3.4 s and grew the WAL to 244 MB *(measured)* | STA04 |
| P3 | Low | Query | `trades` without a symbol (CLI and the public `GET /history/trades`) scans and sorts all of `trade_log`: 1.2 s per `order=desc` page on 1 M trades, 1 ms with an index on `ts` *(measured)* | STA07 |
| P4 | Low | Recorder | One message per `poll` wake-up, with the prune-due check and its SQL rebuilt each time | STA04 |
| D1–D10 | — | Comments | See §5 | STA09 (D6: STA06, D7/D8: STA05, D10: STA01) |

---

## 3. Correctness findings

### C1. A day switch back and forth wipes both days' rollups *(repro)* — Med

`main.py:1254-1276` `_accum_for`, `main.py:1384-1395` `_index_accum_for`.

```python
if acc is None:
    acc = self._rehydrate_daily(symbol, day)
else:
    self._flush_daily(acc)
    acc = _DayAccum(date=day, symbol=symbol)   # blank, never rehydrated
```

The docstring's reasoning ("a same-process day rollover does not rehydrate:
the outgoing day was fully accumulated in memory … the incoming day
genuinely starts empty") holds only for a forward rollover into a day that
has nothing on disk. For any other switch the blank accumulator's next
flush replaces the stored row: `UPSERT_DAILY` overwrites every column.

Reproduced (UTC session): two trades on day 10 (qty 10+10), two on day 11
(5+5), then one late print stamped day 10 (qty 1), then one more on day 11
(qty 5). Result:

| date | `daily_stats.volume` | `trade_count` | `trade_log` volume |
|---|---|---|---|
| 2026-11-10 | **1** | **1** | 21 |
| 2026-11-11 | **5** | **1** | 15 |

Nothing logs, and both rows look plausible. The 2026-06 review's P0-1
(restart wipes the day) is back for this path.

How an accumulator gets a different day than the one it holds, in practice:

- **EOD on the receipt clock (C4).** The day of `system.eod` comes from
  `time.time()` on the pm-stats host, every other day from the engine's
  `ts_ns`.
- **A trade or book without `ts_ns`** falls back to receipt time
  (`main.py:1474-1479`, `1569-1571`).
- **A clock step** on the engine host (NTP correction, VM resume) across
  midnight in the session timezone; `now_ns()` is strictly increasing only
  within one engine process.
- **An index update** from a pm-index host whose clock differs from the
  previous update's host after a failover.

The index rollup has the same code and the same effect on
`index_daily_stats` (open/high/low/`update_count`).

**Fix.** Rehydrate whenever the requested day differs from the held one;
`_rehydrate_daily` on a day with no rows returns a blank accumulator, so a
genuine forward rollover costs three indexed queries per symbol per day.

### C2. A receive loop that dies during start-up exits 0 — Med

`main.py:2103-2109`:

```python
while self._running and not self._request_startup_symbols():
    time.sleep(_ENGINE_RETRY_SEC)
if not self._running:
    self.close()
    return 0
```

`_receive` sets `_running = False` in its `finally`, so when the receive
thread fails while pm-stats is still waiting for pm-engine (a prune that
raises, a feed-gap insert hitting a locked or full disk, a poll error),
`run()` takes this branch and returns 0, ignoring `_receive_failure`. The
`_receive` docstring promises the opposite ("must stop the whole process …
invisible to anything watching the process table"). With systemd's
`Restart=on-failure` or a compose `restart: on-failure`, pm-stats then stays
down. The same branch is also taken for a clean SIGTERM during the wait,
which is correct; only the failure case is wrong.

### C3. Table output rounds numbers to six significant digits *(repro)* — Med

`cli.py:528-533`: `f"{value:g}"`.

| stored | shown |
|---|---|
| `12345.67` (a price) | `12345.7` |
| `150.2537` (a VWAP) | `150.254` |
| `123456789.0` (`turnover`) | `1.23457e+08` |

`table` is the default format, so `pm-stats-cli daily --wide` prints a
price that never traded and a turnover nobody can read. The guide explains
`%g` only under `index-snapshots` (for `aggregate_cap`) and points to json/csv
there. Prices come out of `to_display_prices` as `ticks / 10**tick_decimals`,
so the shortest round-trip form (`repr`) shows them exactly.

### C4. EOD closes are filed on the recorder's clock — Low

`main.py:1738`: `day = self._trading_date(time.time())`. `system.eod`
carries no timestamp (`spec/messages/system.yaml:876-893`), so receipt time
is the only clock available — but the day it selects need not be the day
the session belonged to. An engine stopped at 23:59:59 session time whose
EOD is handled at 00:00:00.2, or a pm-stats host whose clock runs ahead of
the engine host's, gets:

- the real day's `close_bid`/`close_ask` left NULL;
- a new row for the next day holding only those closes (listed by `dates`
  and `symbols`), which the next morning's process rehydrates as that day's
  closing quotes before any trade;
- with C1, the switch also flushes and replaces the day's accumulator.

**Fix.** EOD closes the session the symbol's accumulator already describes:
use `acc.date` when the symbol has an accumulator in this process, and the
receipt-time trading date only when it has none.

### C5. One trade drop is recorded twice *(repro)* — Low

`main.py:1093-1149` (publisher sequence) and `main.py:1151-1208` (trade id).
Both checks run for every `trade.executed`, both insert into `feed_gaps`,
and both use the stream name `trade.executed` (`TRADE_STREAM =
TOPIC_TRADE_EXECUTED`, and the topic itself). Reproduced: trades with
publisher seq 1, 2, 5 and ids …1, …2, …5 give two identical-looking rows
`('trade.executed', 3, 5, 2)` and `stats.feed_gaps == 2`.

The guide says the overlap is deliberate (the trade-id check also catches
loss upstream of the publisher) and describes `expected_id` as "trade-id
suffix, or publisher sequence number". But nothing in a row says which, so:

- `SELECT SUM(missing_count) … WHERE stream = 'trade.executed'` reports
  twice the trades lost;
- the dashboard's `stats.feed_gaps` counter moves by 2 per drop;
- the guide's `missing_count` description ("how many trades are
  unaccounted for") is wrong for every non-trade stream.

See Q1.

### C6. An inclusive `--to` misses rows at `.000` *(repro)* — Low

`query.py:281-283`: `ts <= normalise_ts_bound(to_ts)`. `canonical_ts` drops
a zero fractional part, and `'+'` sorts before `'.'`, so the bound
`09:00:00+00:00` sorts *before* the stored `09:00:00.000+00:00`. Reproduced:
`query_trades(to_ts="2026-11-10T09:00:00Z")` returns the `08:59:59.999`
trade and not the `09:00:00.000` one.

The guide states this (`060-statistics-and-reporting.md:166-172`) and tells
the reader to write `--to …:00.999`. The module docstring of
`trading_day.py` (lines 73-79) claims the opposite: "that single rule makes
text comparison agree with instant comparison across both stored
precisions" — true for `>=` and for the half-open day range, false for an
inclusive upper bound (D6).

Rendering the **upper** bound always with milliseconds makes `<=` exact
against both stored precisions (`09:00:00+00:00` and `09:00:00.000+00:00`
both sort at or before `09:00:00.000+00:00`) without changing the lower
bound. See Q2.

### C7. The health write check never writes to `stats.db` *(repro)* — Low

`cli.py:440-443`: `BEGIN` (deferred) then `CREATE TEMP TABLE …; INSERT`.
A TEMP table lives in the connection's temp database, so no lock or write
on `stats.db` is ever attempted. Reproduced: `chmod 444 stats.db` →
`(True, 'read/write and integrity checks passed')`. The help and the guide
both say the check proves "read/write access".

`BEGIN IMMEDIATE` (then `ROLLBACK`) takes the main database's write lock
and fails on a read-only file or directory; with `timeout=2.0` it waits out
the recorder's short transactions.

### C8. Index-stream failures are invisible — Low

`main.py:2036-2051` `_receive_one_index_message`:

- a decode failure is logged and not counted (the engine path counts
  `messages_undecodable`);
- a handler exception (`_on_index_update` failing to write) is logged at
  WARNING and counted in neither `records_dropped` nor anything else; the
  engine path logs ERROR and counts it (`main.py:1919-1924`).

And `stats.events_recorded` (`main.py:1926`) is incremented for every engine
message whose handler did not raise, including a trade ignored for a
missing field (`main.py:1470-1471`, silent), a duplicate trade, an order
event without an id, and an ignored book sub-topic. The metric's
description ("events recorded") overstates what was stored.

### C9. `gaps` truncates silently — Low

`cli.py:689-698` returns `None` as the cursor and `query_feed_gaps` has no
`after`; a day with more than `--limit` (500) gaps prints the first 500 and
no `[WARN] Output truncated` line. `gaps` is the command the guide's
"is this session complete?" recipe (`060-…:1678`) relies on. Help text says
"trades the recorder never received" although every stream is covered (D7).

### C10. Recorded columns that pm-stats-cli never shows — Low

- `_ORDER_EVENTS_COLUMNS` (`cli.py:88-110`) has 21 of the table's 23
  columns: `reject_code` (schema 9, sim forensics X6) and `msg_id`
  (schema 10) are missing. The guide says every `*_REJECT` row keeps
  `reject_code` and, a few lines later, "All 21 `order_events` columns are
  printed".
- `query_trades` (`query.py:557-560`) selects neither `buy_order_id`,
  `sell_order_id`, `match_type` nor `msg_id` (schema 10), so `trades` and
  `GET /history/trades` cannot show them. Exposing them on the API is a
  contract change and stays out of this WP (see §9); the CLI can show them
  once the query selects them.

### C11. A trade without an id becomes the dedupe key `""` — Low

`main.py:1514`: `payload.get("id", "")`. The first id-less trade is stored
under `""`; `INSERT OR IGNORE` then drops every later one as a duplicate
(counted `duplicate_trades`, not `records_dropped`), and
`_check_trade_sequence("")` disables gap detection for the run. The spec
requires `id`, so this is a malformed message, which should be refused and
counted like one, not deduplicated.

### C12. The tick-scale mismatch error is not latched — Low

`main.py:1238-1247`. Once a symbol's scale disagrees with the day's, every
later trade and book message for it logs the same ERROR. At book rates that
is thousands of lines a second into pm-log-srv. Log once per (symbol, day).

### C13. EINTR ends recording — Low

`main.py:1870-1875`: an `EINTR` from `poller.poll` sets `_receive_failure`
and returns, skipping `_drain`. pyzmq retries EINTR (PEP 475) and signals
are delivered to the main thread, so it is nearly unreachable; it should be
`continue` all the same (the same pattern was fixed in pm-audit, D10 of the
audit review).

---

## 4. Performance findings

### P1. The book path commits two no-op writes per message *(measured)* — Med

`main.py:1582-1589` and `main.py:1210-1227`, `1229-1248`.

- `_on_book` calls `_flush_daily(acc)` on every book message once an
  opening bid or ask is known — i.e. all day — although nothing in the row
  changed after the first one.
- `_note_tick_decimals` calls `_record_instrument` on every book and every
  trade message: an `UPSERT_INSTRUMENT` (whose `WHERE` makes it a no-op) in
  its own transaction, plus a `datetime.now().isoformat()`.

Timed with the `sp` fixture on 20 000 book messages for one symbol:

| | per message |
|---|---|
| as is | 18.4 µs |
| without the instrument upsert | 13.4 µs |
| without both | 4.3 µs |

Book updates are the recorder's firehose, so this is most of its write
cost. **Fix.** Flush the daily row only when `open_bid`/`open_ask` was set
by this message; keep a `{symbol: (tick_decimals, source)}` cache and
upsert the instrument only when it changes.

### P2. Retention deletes in one long transaction *(measured)* — Med

`main.py:1974-1998`. `_prune_if_due` runs every statement inside one
`with self._lock, self._conn:` on the receive thread. Timed on disk: one
prune of 900 000 `order_events` rows (four indexes) took **3.4 s** and left
a **244 MB** WAL (a single transaction cannot be checkpointed part-way).

While it runs, nothing is read from the SUB sockets. At the swarm rates
behind `--keep-order-events-days` (the help's own motivation), 3 s of
backlog approaches the 100 000-message `_SUB_RCVHWM`; past it, ZeroMQ drops
messages, which then appear as feed gaps blamed on the network. The first
prune after a restart that followed a long stop is the worst case: it
deletes everything accumulated since.

**Fix.** Delete in bounded batches (e.g. `seq`/`rowid` ranges of 10 000)
with one batch per loop iteration until a statement deletes nothing, and
keep the hourly clock for starting a round. The watermark subquery already
gives the upper `seq`/`rowid`.

### P3. Trades without a symbol scan the whole tape *(measured)* — Low

`query.py:557-575`. `trade_log` has indexes on `(symbol, ts)` and
`(symbol, quantity, ts)` only, so a query without `symbol` scans
`idx_tl_symbol_ts` and sorts every match into a temp B-tree
(`EXPLAIN QUERY PLAN` confirms). On 1 M trades in memory:
`order=desc` 1.2 s per page; with `CREATE INDEX … ON trade_log(ts)` 1 ms.
`GET /history/trades` accepts no symbol and is open to every
authenticated participant, so each page request costs a full scan in
pm-api-gwy's worker. `symbols` without `--date` (`query.py:729-736`) also
scans all of `trade_log`; `instruments` ∪ `daily_stats` already names every
symbol that traded. See Q3.

### P4. One message per poll — Low

`main.py:1866-1888`. Each loop iteration polls three sockets, rebuilds the
prune tier list (`_order_event_prune_tiers`, 1.8 µs, string formatting
every time) and handles at most one engine message and one index message.
Draining up to a bound (e.g. 256) with `zmq.NOBLOCK` per wake-up, and
building the prune statements once in `__init__`, removes that per-message
overhead.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `main.py:1-95` | Usage lists `--timezone TZ`, which pm-stats does not have (the timezone comes from engine config). "Subscribes to" omits the order/combo/oco/quote topics and `system.symbols.STATS`. The table list is stale: `daily_stats` lacks `turnover`/`tick_decimals`, `price_snapshots` lacks `tick_decimals`, `trade_log` lacks `aggressor_side`, the order ids, `match_type`, `msg_id`; `order_events`, `feed_gaps`, `instruments` and `stats_meta` are missing; `daily_stats` is also upserted on book messages. |
| D2 | `main.py:460-462` | "Price columns below are INTEGER *ticks*" also covers `order_events.price`/`fill_price`, which are REAL display money (the guide says so; the DDL has no column comment). |
| D3 | `main.py:309`, `967`, `985`; `970-971`, `976-977` | "calendar date" where the code means the trading date; two comment pairs where the old line was kept above its rewrite. |
| D4 | `main.py:2014-2018` | The `book.depth.AAPL` example: depth is published on `depth.{symbol}`, and on the engine PUB `book.` matches only `book.{symbol}`. The guard is still right; the example is not. |
| D5 | `main.py:2418-2423` | `-q/--quiet` "Reduce log output to warnings/errors": WARNING is already the default, so the flag does nothing. Say so, or drop it. |
| D6 | `trading_day.py:73-79` | Claims text and instant comparison agree for every bound; not for an inclusive `--to` (fixed with C6). |
| D7 | `cli.py:367-369` | `gaps` help: "trades the recorder never received" — every subscribed stream (fixed with C9). |
| D8 | `cli.py:280-281` and the other `--from`/`--to` | No help text: nothing says the bounds are inclusive instants and that an offset-less value is session-local (the guide does). |
| D9 | `query.py:676-690` | `query_order_events_retained_from` is "the instant before which events have been pruned"; pruning runs hourly and only while pm-stats runs, so rows up to an hour older can still be there. Say "at most". |
| D10 | `main.py:1254-1266` | `_accum_for`'s "the incoming day genuinely starts empty" (fixed with C1). |

---

## 6. Verified as correct

- **Trade transaction.** `trade_log` insert, gap row and `daily_stats`
  upsert commit together; the accumulator is a copy installed only after
  the commit, so a failed write or a duplicate leaves memory equal to disk.
- **Rehydration.** Count, volume, turnover, low/high, open/close (by `ts`
  then `rowid`) and the largest trade (by quantity, earliest on ties, as
  `on_trade`'s strict `>`) are rebuilt exactly; `INDEXED BY
  idx_tl_symbol_qty` is safe because `initialize_schema` creates it on
  every open. Opening/closing quotes and the tick scale come from the
  stored row.
- **Tick conversion.** `round(price * 10**d)` recovers the engine's integer
  exactly; every row carries its scale; a mid-day scale change keeps the
  day's scale.
- **Snapshots.** The first snapshot is not delayed by host uptime; the
  `pct_change` baseline advances only on a stored row, is restored from disk
  after a restart, and a deduplicated insert does not move it.
- **File safety.** The sidecar `.lock` (exclusive SQLite transaction,
  `busy_timeout 0`) refuses a second recorder before the database is
  touched and is released on every failure path; a schema version or
  session timezone mismatch is refused; the read-only URI is
  percent-encoded.
- **Retention SQL.** The watermark subqueries delete only rows at the head
  of the table; the bound without fractional seconds is right for `<`
  against both stored precisions; the two order-event tiers split the
  range by gateway without a second scan; GLOB patterns are quote-doubled.
- **Readers.** Every cursor is type-checked; `daily`/`index-daily` pin the
  date of their first page; `trading_day_bounds` is half-open and correct
  on 23- and 25-hour days; `--date` resolves in the recorded timezone, and an
  override that contradicts it warns.
- **Shutdown.** The drain is bounded (0.5 s) and runs before the
  connection is closed under the lock; `close()` handles a partly built
  instance.
- **Health process match.** `find_process_pids("pm-stats")` does not count
  `pm-stats-cli`.

---

## 7. Decisions

All three taken as recommended on 2026-11-14.

| # | Question | Recommendation |
|---|---|---|
| Q1 (taken as recommended) | Both gap checks fire on one trade drop (C5). Keep both rows, or record one? | Keep both (they catch different losses) and say which is which: a `source` column (`publisher_seq` / `trade_id`), schema 12, refused-not-migrated as usual. `gaps` shows it; the guide's `missing_count` text says "messages" for `publisher_seq` and "trades" for `trade_id`; `stats.feed_gaps` counts rows, documented as such. |
| Q2 (taken as recommended) | Fix the inclusive `--to` (C6) or keep the documented `.999` workaround? | Fix: render an upper bound always with milliseconds. One line in `_apply_time_filters`, and the guide paragraph shrinks to "both bounds are inclusive". pm-api-gwy's `to` gains the same behaviour, which matches its documented "inclusive". |
| Q3 (taken as recommended) | Add an index on `trade_log(ts)` (P3)? It costs every trade insert one more B-tree write. | Add it, after measuring the insert cost in the WP (one more index on an append-only table with three already). It also lets `trade_log`'s prune use a range instead of the rowid watermark. |

---

## 8. Work packages

Each WP lists the tests to write first, the production change, and the exit
criteria. Test files are existing ones unless marked new.

### WP-STA01 — Rollups survive a day change (C1, C4, D10)

**Goal.** No sequence of events rewrites a stored day with fewer trades
than `trade_log` holds for it; EOD closes the session the symbol was in.

**Tests first** (`tests/test_stats_trading_day.py` or a new
`tests/test_stats_day_switch.py`):

1. The repro: trades on D, D+1, a late one on D, one on D+1. For each day,
   `daily_stats.volume`/`trade_count`/`turnover`/`open`/`high`/`low` equal
   the aggregates of that day's `trade_log` rows. (Fails today.)
2. The same for an index: updates on D, D+1, a late one on D, one on D+1;
   `index_daily_stats.update_count` equals the snapshot rows per day.
3. A forward rollover with nothing on disk for D+1 still starts D+1 blank
   (no regression of `test_stats_and_orders` rollover tests).
4. EOD received at receipt time D+1 00:00:00.2 for a symbol whose
   accumulator is on D: `close_bid`/`close_ask` land on D's row; no D+1 row
   exists.
5. EOD for a symbol with no accumulator in this process: filed under the
   receipt-time trading date (unchanged).

**Change.** `_accum_for`/`_index_accum_for`: on any day mismatch flush the
held accumulator and rehydrate the requested day. `_on_eod`: use the
symbol's accumulator date when there is one. Fix the docstring (D10).

**Exit criteria.** Tests 1–5 pass; `tests/test_stats_*.py` green.

**Outcome (2026-11-14).** `_accum_for`/`_index_accum_for` flush the held
accumulator and rehydrate the requested day on any day mismatch (a forward
rollover finds nothing on disk and starts empty). `_on_eod` keeps a held
accumulator's day and uses the receipt-time date only for a symbol with
none. Docstring rewritten (D10). Tests: `tests/test_stats_day_switch.py`
(5 tests; the three behaviour tests failed first, the two "unchanged"
tests passed as intended). Full suite: 13 980 passed (with WP-STA02).

### WP-STA02 — Every recorder failure exits non-zero (C2, C8, C13)

**Tests first** (`tests/test_stats_recorder_gaps.py` or
`tests/test_stats_cli.py`, wherever `run()` is driven today):

1. The receive thread raises while `_request_startup_symbols` keeps
   failing: `run()` returns 1 and logs CRITICAL. (Fails today.)
2. SIGTERM (`_stop`) during the same wait: `run()` returns 0.
3. `_on_index_update` raising (patch the insert): `stats.records_dropped`
   moves by 1, logged at ERROR; an undecodable index message counts
   `messages_undecodable`.
4. A trade with no `symbol` is not counted in `stats.events_recorded`
   (decide the counter's meaning in the test: rows written, or messages
   stored; recommend "messages that produced a row").
5. `poll` raising `ZMQError(EINTR)` once: the loop continues and records
   the next message.

**Change.** `run()` checks `_receive_failure` on the early-return branch.
The index path mirrors the engine path's accounting. Handlers that ignore a
message return a flag (or raise a small `Ignored`) so the loop counts
only stored messages. EINTR → `continue`.

**Exit criteria.** Tests pass; the stats tile in dash-gui still reads the
same three metrics.

**Outcome (2026-11-14).** `run()` returns `_exit_code()` (1 after a
receive failure) on the engine-wait branch too; EINTR `continue`s. Handlers
return whether they stored the message (`_dispatch` → bool); only stored
messages count in `stats.events_recorded`. The index path counts
`messages_undecodable` and `records_dropped` and logs ERROR like the engine
path. Log ledger: the index-only WARNING entry replaced by the malformed
trade entry; the "failed to record" entry covers both streams. Tests:
`tests/test_stats_recorder_failures.py` (8; 7 failed first);
`test_service_metrics.py`'s fake `_dispatch` now returns True. Metric names
unchanged. Full suite: 13 980 passed.

### WP-STA03 — Write only what changed (P1, C12)

**Tests first** (`tests/test_stats_and_orders.py`):

1. 1 000 book messages with an unchanged opening quote execute
   `UPSERT_DAILY` once and `UPSERT_INSTRUMENT` once (count via
   `set_trace_callback`). (Fails today.)
2. A config row from `system.symbols` is still never overwritten by an
   observed value; a scale change still writes the instrument row.
3. A mid-day scale change logs one ERROR for 100 later messages of that
   symbol.
4. Existing opening-quote tests: the row still exists after the first book
   message even with no trades.

**Change.** Flush in `_on_book` only when this message set `open_bid` or
`open_ask`; an instrument cache keyed by symbol; latch the scale error per
(symbol, day).

**Exit criteria.** Tests pass; the bench in the WP notes shows ≤ 6 µs per
book message.

**Outcome (2026-11-14).** `_on_book` flushes only when this message set
the opening bid or ask; `_record_instrument` skips an unchanged
(scale, source) per symbol; the scale-change ERROR is latched per
(symbol, day). Bench: **4.4 µs** per book message (was 18.4). Tests:
`tests/test_stats_write_amplification.py` (4; 3 failed first). Full suite:
13 988 passed.

### WP-STA04 — Retention in bounded batches (P2, P4)

**Tests first** (`tests/test_stats_and_orders.py`, retention section):

1. 50 000 due `order_events` rows with a batch size of 10 000: one
   `_prune_if_due` call deletes at most one batch; repeated loop iterations
   delete all of them; no undue row is touched. (Fails today.)
2. Both order-event tiers and the `trade_log` rowid watermark still delete
   exactly the rows they did before (existing tier tests unchanged).
3. A message arriving between two batches is recorded before the next
   batch (drive `_receive_loop` with a fake poller).
4. P4: with 300 queued messages, one wake-up records up to the drain bound
   without another `poll`.

**Change.** Prune state machine: the hourly clock starts a round; each loop
iteration runs one `LIMIT`-bounded delete per statement until all report 0.
Prune statements built once in `__init__`. Drain up to N messages per
wake-up.

**Exit criteria.** Tests pass; a 1 M-row prune holds the lock for no more
than ~50 ms at a time.

**Outcome (2026-11-14).** A round starts hourly (and at start-up), binds
each statement's cutoff and, for the watermark statements, the watermark
once (`_Prune` + `_prune_params`); each `_prune_if_due` call then deletes
at most `_PRUNE_BATCH_ROWS` (5 000) rows per statement in its own
transaction. Computing the watermark per batch, as first written, rescanned
every remaining due row each time; measured and fixed before the outcome.
The plan is built once in `__init__`; one wake-up drains up to
`_DRAIN_PER_WAKE` (1 000) engine messages. Measured on disk, 900 000
`order_events`: watermark scan 47 ms once, batches p50 26 ms, p90 43 ms,
worst 143 ms (a WAL checkpoint landing on that commit); 5.3 s for the
round in total, interleaved with message handling. Tests:
`tests/test_stats_retention_batches.py` (4; 3 failed first, the fixture
first patched the not-yet-existing constant with `raising=False` to get
behavioural failures). Existing retention tests unchanged. Full suite:
13 984 passed.

### WP-STA05 — pm-stats-cli output (C3, C9, C10, D7, D8)

**Tests first** (`tests/test_stats_cli.py`):

1. `daily --wide` table output shows `12345.67` and a turnover of
   `123456789.5` unchanged. (Fails today.)
2. `gaps --limit 2` with three gaps prints the truncation warning and a
   cursor; `--after` returns the third. (Fails today.)
3. `order-events` on a `REJECT` row shows `reject_code`; `msg_id` is in
   json output.
4. `trades --format json` carries `match_type`, `buy_order_id`,
   `sell_order_id`, `msg_id`; the API's trade response is unchanged
   (`tests/test_api_gateway_history*.py`).
5. `gaps --help` and `trades --help` describe the stream coverage and the
   `--from`/`--to` semantics.

**Change.** `_stringify` uses `repr` for floats. `query_feed_gaps` gains a
`(ts, seq)` keyset `after`. Add the missing columns to the CLI lists;
`query_trades` selects them and the API router keeps projecting its own
fields. Help strings (D7, D8); guide's "All 21 columns" and the `%g` note.

**Exit criteria.** Tests pass; `mkdocs build` clean.

**Outcome (2026-11-14).** `_stringify` prints floats with 15 significant
digits (`12345.67`, `123456789.5`, `7350000000000`, and `150` for a whole
price). `query_feed_gaps` takes `after` and returns a `(ts, seq)` cursor;
`gaps --after` added, truncation warned like every other command.
`order-events` shows `reject_code` and `msg_id`; `query_trades` selects
`match_type`, the order ids and `msg_id`, which `trades` shows. The
`GET /history/trades` router now projects rows onto `TradeRow`'s fields, so
the API contract is unchanged (the contract check caught the leak). Help:
`--from`/`--to` on every command, `gaps` description. Guide: trades and
order-events examples regenerated with the renderer, the `%g` note
replaced, "All 23 columns", `gaps --after`. Completions regenerated. Tests:
`tests/test_stats_cli_output.py` (7; 6 failed first); the pinned CSV header
in `test_stats_cli.py` updated. Full suite: 13 995 passed; `mkdocs build`
clean.

### WP-STA06 — Bounds and gap rows (C5, C6, D6; after Q1, Q2)

**Tests first** (`tests/test_stats_cli_query.py`,
`tests/test_stats_recorder_gaps.py`):

1. `--to 2026-11-10T09:00:00Z` returns a trade at `09:00:00.000`, and a
   snapshot at `09:00:00`; not one at `09:00:00.001`. (Fails today.)
2. `--from` unchanged for both precisions (existing tests).
3. Per Q1: a dropped trade yields one `publisher_seq` and one `trade_id`
   row; `gaps` shows the source.

**Change.** Upper bound rendered with milliseconds; per Q1 the `source`
column, `SCHEMA_VERSION = 12`, guide's schema-history and `feed_gaps`
sections. Fix D6.

**Exit criteria.** Tests pass; `tests/test_stats_*.py` and api-gwy history
tests green.

**Outcome (2026-11-14).** `normalise_ts_bound(..., inclusive_upper=True)`
renders `--to` with milliseconds; `_apply_time_filters` uses it, so the
REST `to` parameter gains the same fix. `trading_day.py`'s docstring now
states the two rules (D6). `feed_gaps.source` (`publisher_seq` /
`trade_id`), `SCHEMA_VERSION = 12`, shown by `gaps`. Guide: `--to`
paragraph, schema history, `feed_gaps` columns, a "count lost trades" query,
`gaps` example; `stats_meta` example gained the retention keys. Schema docs
regenerated (`make dbdocs`). pm-sim-forensics' B7 sample list reads
`feed_gaps` unchanged. Tests: `tests/test_stats_bounds_and_gaps.py` (3; 2
failed first); three hand-written `feed_gaps` inserts in other tests gained
`source`. Full suite: 14 002 passed.

### WP-STA07 — Index for time-ordered trade reads (P3; after Q3)

**Tests first** (`tests/test_stats_cli_query.py`):

1. `EXPLAIN QUERY PLAN` of `query_trades(symbol=None, newest_first=True)`
   uses no temp B-tree. (Fails today.)
2. `query_symbols(date_value=None)` does not scan `trade_log`, and still
   lists a symbol that traded but is absent from `instruments`' config rows
   (an observed row exists for it).

**Change.** `CREATE INDEX idx_tl_ts ON trade_log(ts)` (folded into the
schema-12 bump if WP-STA06 lands first, else bump); `symbols` from
`instruments` ∪ `daily_stats` ∪ `price_snapshots`. Measure the per-trade
insert cost before and after and record it in the outcome.

**Exit criteria.** Tests pass; insert cost increase noted.

**Outcome (2026-11-14).** `idx_tl_ts` folded into schema 12. `symbols`
without a date reads `daily_stats` ∪ `price_snapshots` (a trade's daily row
commits with it and is never pruned); with a date the tape branch stays and
now uses the index. Insert cost: 197.8 → 189.6 µs per trade on disk (best
of 3; within noise, the commit dominates). Tests:
`tests/test_stats_trade_reads.py` (3, all failed first);
`test_query_symbols_uses_union_across_tables` seeded a tape-only symbol
that pm-stats never writes and now pins both branches. The `_prune_by_key`
comment no longer says trade_log has no ts index. Guide: `trade_log` table
gained its four schema-10 columns and the index list. Full suite: 14 005
passed.

### WP-STA08 — Small items (C7, C11)

**Tests first:**

1. `health --extended` on a `chmod 444` database reports the database
   FAIL (`tests/test_stats_cli.py`). (Fails today.)
2. A trade without `id`: no row, `records_dropped` +1, a later trade with
   an id is stored (`tests/test_stats_duplicates_and_collisions.py`).

**Change.** `BEGIN IMMEDIATE` + rollback in `_check_database_health`;
`_on_trade` refuses a missing or empty `id` with a WARNING.

**Exit criteria.** Tests pass.

**Outcome (2026-11-14).** `_check_database_health` creates and fills a
table in `main` inside `BEGIN IMMEDIATE` and rolls back; `BEGIN IMMEDIATE`
alone passed on a read-only file (SQLite opens it read-only silently).
`_on_trade` refuses a trade without id, symbol, price or quantity with one
WARNING and counts it in `records_dropped` (log-ledger entry updated).
Tests: `tests/test_stats_small_items.py` (4; 3 failed first). Full suite:
13 999 passed.

### WP-STA09 — Comments, docstrings, help texts (D1–D5, D9)

**Change.** Fix D1–D5 and D9 as listed in §5; reread the statistics
chapter of the operator guide against the code as it ends up (EOD day,
batch prune, `gaps` paging, columns, `--to`).

**Exit criteria.** `mkdocs build` clean; a reread of every module and
class docstring in `src/edumatcher/stats/*.py` against the code finds
nothing stale.

**Outcome (2026-11-14).** D1 (module docstring: options, subscriptions,
tables), D2 (order_events price comment), D3, D4, D5 (`-q` help: the
default already, `-v`/`--log-level` win), D9 ("may have been pruned", an
upper bound). Guide: retention batches, `close_bid`/`close_ask` filing.
Completions regenerated for the `-q` help. Full suite: 14 004 passed before
the completion regeneration, then green; `mkdocs build` clean.

---

## 9. Out of scope, noted

- `health -q` exits `-1` (status 255); already recorded as L017 in
  `EduMatcher-For-Later-ToDo.md`.
- `order_events.ts` is pm-stats' receipt time. The guide documents this
  (`060-…:623-629`). `order.ack` and `order.fill` now carry the engine's
  `ts_ns`, but cancels, expiries and amends do not, so switching to it would
  mix two clocks in one column. An `engine_ts_ns` column for the events that
  carry it is a 1.x addition, not a fix.
- `GET /history/trades` does not expose `match_type`, the order ids or
  `msg_id` (C10). Adding them is an API contract change for 1.x.
- Index levels and `order_events` prices are REAL by design (documented);
  not revisited.
- `fnmatch` (reader) and SQLite `GLOB` (pruner) differ on `[!…]` vs `[^…]`
  negation and on Windows case folding; only matters for an exotic
  `--human-gateways` pattern, and only for the stated retention, not for
  what is deleted.

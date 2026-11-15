# pm-monitor Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/monitor/` at `e0725970` (v0.79.0): `collector.py`
(911 lines, the collector loop, snapshot and own beacon), `activity.py` (668,
rates and the trading, participant, book, gateway and API blocks), `cli.py`
(704, `pm-monitor-cli`), `store.py` (567, `metrics.db`), `state.py` (509,
the per-process health model), `main.py` (268, the `pm-monitor` entry
point), `config.py` (260, the `monitor:` section), `thresholds.py` (257),
`rates.py` (180), `roster.py` (151), `host.py` (111), `events.py` (105),
`timefmt.py` (14). `config.py` is shared with every beaconing process, the
verifier and `pm-config-show`; `metrics.db` is also read by the dash-gui
bridge (`web-apps/dash-gui/apps/bridge/src/metrics-db.ts`). The beacon
sender (`health/reporter.py`), the engine's metric emitter
(`engine/metrics.py`, `Engine` book samples) and
`stats/trading_day.trading_date` were read where they decide pm-monitor's
behaviour. They were not reviewed as code of their own.

**Focus:** correctness, edge-case handling, performance, and whether the
comments, help texts, the `pm-help` registry and the operator guide's
"Health Monitoring" chapter
(`docs/books/operator-guide/part-6-observe-and-recover/060-health-monitor.md`)
say what the code does.

**Previous work:** `docs-design/EduMatcher-Operator-Dashboard.md` (design,
WPs A1–E3) and its workplan's insights log I1–I123, including the review
items R1–R9 cited in the code and the final review I123. Their fixes are in
place and are not repeated here: a failing loop step costs the step, not the
process (R1); gone processes show no live gauges (R2); baselines from before
today (R3); RSS warm-up and ramp rules (R4); idle when disabled (R5); the
`daily_totals` name index (R6); the 1.5 s final grace (R9); one raw stamp per
write (I120); slim snapshots, minute-only labelled series and
`metrics_store_errors` (I123).

**Method:** every line of the files above was read. Findings marked
*(repro)* were reproduced with a scratch script against the tree at
`e0725970`, driving the real `Monitor` (fake monotonic and wall clocks, real
sockets on free ports), `MetricsStore` and `pm-monitor-cli`'s
`query_events`. *(measured)* means timed on this host against a synthetic
`metrics.db`: 5 000 counter series, one day of minute rows for 3 000 series
(4.3 M rows), and `daily_totals` for 30 and 365 days at the AI-trader
simulation's shape (300 symbols, 112 participants, 10 per-gateway counters,
40 reject reasons; 533 k rows at a year). The other findings are by
inspection, with line numbers given.

Status: **Done, uncommitted.** WP-MON01–07 completed 2026-11-15 in order,
each test-first and verified with black/flake8/mypy/pyright and the full
suite (last run: 14 435 passed, 1 skipped; `make _check` clean). Decisions
Q1–Q4 taken as recommended. Beyond the plan: WP-MON02 also writes an
unchanged counter once per trading date (needed by WP-MON01's same-date
priming); WP-MON05 added `%41` to the path tests. `make test-e2e` was not
run.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (rows in `metrics.db`, snapshot fields, events,
   `pm-monitor-cli` output and exit code, pm-monitor's own counters).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_monitor_*.py`,
   `tests/test_dash_*_mirror.py` and `tests/test_health_*.py` with
   `-n logical`, then black/flake8/mypy/pyright. Do not start the next WP
   with a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Store and restart tests use `tests/test_monitor_store.py`'s helpers
(`_Clocks`, `_monitor`, `_store`, `_rows`) with beacons built by
`tests/test_monitor_main.py::_beacon_frames`; snapshot tests drive
`Monitor.snapshot()` directly with `QuietHost`. CLI tests call
`pm-monitor-cli`'s functions (`query_events`, `_follow` with a fake socket)
and `main(argv)` for exit codes, as `tests/test_monitor_cli.py` does.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-MON01 | A restart never books another day's counts to today | C2 | Q1 | 0.5 d | ☑ | 2026-11-15 |
| 2 | WP-MON02 | Counter state of a source that never returns expires | C1, P2 | Q2 | 0.5 d | ☑ | 2026-11-15 |
| 3 | WP-MON03 | A failing `metrics.db` cannot grow pm-monitor's memory | C3 | Q3 | 0.5 d | ☑ | 2026-11-15 |
| 4 | WP-MON04 | Figures stay right after a restart or a removed book | C4, C5 | — | 0.5 d | ☑ | 2026-11-15 |
| 5 | WP-MON05 | `pm-monitor-cli`: exact times, any data path, follow across a new numbering | C6, C7, C8, C9 | Q4 | 0.5 d | ☑ | 2026-11-15 |
| 6 | WP-MON06 | Daily averages read seven dates, not the whole history | P1 | — | 0.25 d | ☑ | 2026-11-15 |
| 7 | WP-MON07 | Comments, docstrings, help texts, operator guide | D1–D8 | WP-MON01–06 | 0.25 d | ☑ | 2026-11-15 |

Suggested order: **WP-MON01 → WP-MON02 → WP-MON03 → WP-MON04 → WP-MON05 →
WP-MON06 → WP-MON07**. WP-MON01 writes wrong totals into `daily_totals`,
which is kept for good and feeds the seven-day averages, so it goes first.
WP-MON02 and WP-MON03 are unbounded growth (rows rewritten forever; memory
while the disk is full). WP-MON02 changes when `counter_last` is written,
which WP-MON01's tests also read, so it follows WP-MON01. WP-MON07 goes last
so every text describes the final code.

Estimated sequential effort: about 3 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The **health model** is sound. Ages are measured on pm-monitor's own
monotonic clock at receipt; an older incarnation's late beacon is stale, not
a restart; silence is credited to the loop figures only after it was shown
SILENT; DEAD is told from SILENT by PID *and* start time, zombies included.
The **exchange status** follows the spec's rule, and bots never count. The
**threshold book** debounces warnings, raises critical levels at once, and
clears with a dead band, without jumping past an intervening warn level.
`metrics.db` writes daily totals and counter state in one transaction, so a
kill at any moment resumes consistently; a second writer and a changed
session timezone are refused. The loop survives any failing step, and
snapshots never block. `pm-monitor-cli` is strictly read-only.

The defects are in four places:

- **Restarts across days (C2, C4).** A pm-monitor restart resumes each
  counter from the value `metrics.db` last recorded, whatever day that was.
  Counts from the previous day are booked to today, and the engine's daily
  counters, reset at PRE_OPEN, lose up to the whole previous total: today's
  trades 1 000 instead of 4 000 in the repro. Both go into `daily_totals`
  for good and into seven days of averages. After any restart, "avg / hour"
  divides by the hours since midnight instead of since the open.
- **State that never goes away (C1, C5).** Counter state of a source that is
  not heard from again after a restart (a bot instance of an earlier
  profile, a removed API gateway instance) is rewritten every 10 s with a
  fresh time stamp, so retention never deletes it. A book the engine no
  longer reports keeps its last gauges, and a breach on it keeps the
  exchange DEGRADED until pm-monitor restarts.
- **A disk that fills while running (C3).** Every failed write keeps the
  closed minutes it could not write, and the next failure adds more:
  12 MB an hour at 405 series in the repro, without limit.
- **`pm-monitor-cli` edges (C6–C9).** `--since` is compared as text, so
  `2026-11-14 10:00` returns the whole day and an offset is ignored; a data
  path with `#` reads the wrong file; `events --follow` drops every event
  after pm-monitor restarts its numbering.

Severity key: **High**: a wrong exchange status or a lost health event
without a trace. **Med**: a wrong figure that is kept (daily totals,
averages), or growth without bound. **Low**: a wrong figure on screen only,
a CLI edge, hardening, clarity.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| C1 | Med | Store | `counter_last` rows (and tracker entries) of a source not heard from after a restart are rewritten every 10 s with the current time, so `minute_days` retention never deletes them: 200 rows of a bot gone 10 days still stamped "now" *(repro)* | MON02 |
| C2 | Med | Rates | A restart resumes counters from a value recorded on an earlier trading date: the previous evening is booked to today (orders 9 000, true 8 000) and the engine's PRE_OPEN-reset counters lose the old total (trades 1 000, true 4 000); written to `daily_totals` *(repro)* | MON01 |
| C3 | Med | Store | While every write fails (disk full, read-only remount), each tick keeps the closed minutes it could not write: 48 600 pending rows and 26 MB after 2 h at 405 series, without limit *(repro)* | MON03 |
| C4 | Low | Rates | After any pm-monitor restart mid-session, `avg_per_hour` divides by the hours since midnight: 1 091 instead of 6 000 at 11:00 with the open at 09:00 *(repro)* | MON04 |
| C5 | Low | Books | A book the engine no longer reports keeps its gauges, its row in `books`, and its threshold breach: the exchange stays DEGRADED 120 s (and for good) after an engine restart without that symbol *(repro)* | MON04 |
| C6 | Low | CLI | `events --follow` ignores every live event whose `seq` is not above the history's newest; pm-monitor numbers from 0 again without `metrics.db` or after it was moved aside, so the follow prints nothing | MON05 |
| C7 | Low | CLI | `events --since` is compared as text: `2026-11-14 10:00` returns events from 06:00Z, `…T10:00:00+01:00` misses 09:30Z, `yesterday` returns nothing, all without an error *(repro)* | MON05 |
| C8 | Low | CLI | `file:{db}?mode=ro` is built unencoded: a data path containing `#` opens a different file and `events` fails with "no such table: events" *(repro)*; `health --extended` alike | MON05 |
| C9 | Low | Wording | Breach values are formatted with `:g` in `THRESHOLD` events, log lines and `status`: a 1 234 567 µs p99 reads `1.23457e+06` | MON05 |
| P1 | Low | Store | `avg_per_day` over all labels scans every date of a name's history once a minute: 3 ms at 30 days, 65 ms at a year for `engine.trades`; 98 ms a minute for all 114 averages *(measured)* | MON06 |
| P2 | Low | Store | Every raw flush rewrites every `counter_last` row, changed or not: 10.5 ms per 10 s at 5 000 series *(measured)* | MON02 |
| D1–D8 | — | Comments | See §5 | MON07 |

---

## 3. Correctness findings

### C1. Counter state of a source that never returns is kept for good *(repro)* — Med

`store.py:350-384` `flush_raw`, `store.py:469` `_delete_old`,
`collector.py:756-771` `_resume_from`, `rates.py:151-154`
`CounterTracker.prime`.

At start-up `_resume_from` primes the tracker with every row of
`counter_last`. `flush_raw` then writes the *whole* tracker state every
10 s, each row stamped with the write's time:

```python
last = [(*k, boot, v, ts) for k, (boot, v) in (counters or {}).items()]
```

Retention deletes `counter_last` rows older than `minute_days`
(`store.py:469`), but a primed row is never older than 10 s. A source that
pm-monitor never hears from again is therefore kept in the tracker, in
`counter_last` and in `monitor.series_tracked` for good, and every later
restart primes it again. `refresh_sources` forgets an unheard source after an
hour (`collector.py:485-498`), but only sources in the process table; a
primed series has none.

Repro: a bot `pm-mm-bot/MM07` with 200 labelled counters beacons, pm-monitor
closes; 10 days later pm-monitor runs for 67 minutes (one retention pass)
and MM07 never returns:

```
after day 0      : counter_last rows for MM07 = 200
10 days later    : counter_last rows for MM07 = (200, '2026-10-29T08:06:46.000Z', '2026-10-29T08:06:46.000Z')
tracker series   : 200          (minute_days = 7; wall now = 2026-10-29T08:06:46.000Z)
```

Real triggers: bot instances of an earlier profile (the AI-trader profiles
name their bots by instance), a removed `pm-api-gwy --instance`, a host
renamed between runs (sources are keyed `process/instance@host`). Each adds
its series for good; the guide's table says `counter_last` is "Kept:
`minute_days`".

**Fix (see Q2).** Write a `counter_last` row only when its value or
`boot_id` changed since the last write, so `ts` is when it was last seen and
retention applies; drop primed series that were never stepped once their
row has expired.

### C2. A restart books another day's counts to today *(repro)* — Med

`rates.py:156-171` `CounterTracker.step`, `activity.py:309-317` `observe`,
`collector.py:756-771` `_resume_from`.

A primed series' first value after a restart is a `RESUMED` step: its
increment is the difference from the value `metrics.db` last recorded
(`rates.py:166-170`). `observe` books every `RESUMED` increment to today;
only a `FIRST` step is checked against the process start
(`activity.py:311`). Nothing checks *when* the primed value was recorded.

- A cumulative counter (`engine.orders_in`) books everything since
  pm-monitor stopped, the rest of the previous day included, to today.
- The engine resets `engine.trades`, `traded_qty` and `traded_value` at
  PRE_OPEN without a restart (`engine/metrics.py:152`, `rates.py` module
  docstring). `increment` reads a lower value as a reset and books the whole
  of it, but a value that has already passed yesterday's total looks like
  plain growth: the reset and yesterday's last figure are both lost.

Repro: the engine started day 1 at 08:00 and runs for days. pm-monitor stops
at 15:00 on day 1 and restarts at 11:00 on day 2.

| | `daily_totals` day 1 | `daily_totals` day 2 | true day 1 | true day 2 |
|---|---|---|---|---|
| `engine.orders_in` | 6 000 | **9 000** | 7 000 | 8 000 |
| `engine.trades` | 3 000 | **1 000** | 3 500 | 4 000 |

The snapshot shows the same figures as "today". `daily_totals` is kept for
good and `avg_per_day` averages it over seven dates, so a wrong day skews
the dashboard's "avg / day" for a week. The guide promises the opposite:
"the first beacon of a process that kept running counts exactly what
happened while `pm-monitor` was down".

Triggers: any pm-monitor stop or crash that spans a trading-date change
while the engine keeps running: the simulation and any exchange left up over
night, with pm-monitor stopped by hand or out of its restart loop.

**Fix (see Q1).** A primed value recorded on an earlier trading date than
today is not a resume point: such a step follows the `FIRST` rule (counted
only when the process started today, otherwise a baseline).

### C3. A failing `metrics.db` grows memory without limit *(repro)* — Med

`store.py:297-322` `record`, `store.py:390-407` `flush_minutes`,
`collector.py:856-874` `store_tick`.

`record` moves a series' finished minute to `self._closed` when the next
minute starts. `flush_minutes` writes `_closed` in one transaction and
clears it only on success. When the write fails, the minutes stay, and the
next tick's closed minutes are added to them. `_raw` and `_daily` are
bounded by the number of series; `_closed` is not.

Repro: 405 series (300 book gauges, 100 participant counters), one engine
beacon every 2 s, every write failing (`PRAGMA query_only = 1`, the same
error a read-only remount gives):

```
minute   0: pending closed minutes       0, traced  1.4 MB, store_errors    7
minute  30: pending closed minutes   12150, traced  8.3 MB, store_errors  907
minute  60: pending closed minutes   24300, traced 14.5 MB, store_errors 1807
minute 120: pending closed minutes   48600, traced 26.2 MB, store_errors 3607
```

About 12 MB an hour at 405 series. pm-monitor stores some 3 000 series on
the AI-trader simulation (I123), so a full disk over a night costs it about
a gigabyte (an extrapolation, not measured). The guide's promise "a write
that fails later is counted the same way" holds (`metrics_store_errors`
shows DEGRADED); the growth is not mentioned. When space returns, the whole
backlog is written in one transaction on the collector thread.

**Fix (see Q3).** Cap what waits for the next write and count what is
dropped in `monitor.store_errors`.

### C4. "avg / hour" after a restart divides by the hours since midnight *(repro)* — Low

`activity.py:268-274` `hours_open`, `activity.py:454-461`
`set_session_state`.

`session_opened_at` is set only on a seen move out of `CLOSED`. A
pm-monitor started or restarted while the session is open learns the state
from the engine's `engine.session_state` gauge, with no previous state, so
`hours_open` counts from local midnight. Repro (open at 09:00, 12 000 orders
by 11:00): `avg_per_hour` 6 000.0 live, **1 090.8** after a restart at 11:00.
The guide says "today divided by the hours since the session opened today
(else since midnight)", which describes the code but not that every restart
lands in the "else". The opening time is in `metrics.db`: the day's first
`SESSION` event leaving `CLOSED`.

### C5. A book the engine no longer reports keeps its breach *(repro)* — Low

`activity.py:402-403` `_engine_gauge`, `collector.py:592-595` `readings`,
`activity.py:546-566` `book_records`.

Book gauges are merged into `self.books` and never removed. Every engine
beacon carries the latest samples of every book (the engine reuses them
between `book_metrics_interval_sec` recomputations), so a symbol missing
from a beacon is gone from the engine. Repro: `OLD` at heap bloat 4.0 (CRIT),
then the engine restarts with a configuration without `OLD`:

```
before restart: DEGRADED [('heap_bloat_ratio', 'OLD', 'CRIT')]
120 s after   : DEGRADED [('heap_bloat_ratio', 'OLD', 'CRIT')] books: ['AAPL', 'OLD']
```

The exchange stays DEGRADED, and the books row lists `OLD`, until pm-monitor
restarts. The same gauges also stay judged while the engine is STOPPED or
DEAD (masked then by DOWN). The readings skip processes that are not live
(`collector.py:567-569`); the books loop does not.

### C6. `events --follow` drops a new numbering — Low

`cli.py:664-665` `_follow`, `cli.py:617` `newest_seq`,
`collector.py:268` and `collector.py:714`.

`_follow` skips every live event with `seq <= last_seq`, where `last_seq`
starts as the newest `seq` in `metrics.db`. pm-monitor numbers events from
`store.next_event_seq()`, but from **0** when it runs without history
(`history_unavailable`, a read-only data directory), and from 1 again when
`metrics.db` was moved aside (the guide's advice after a timezone change).
A `--follow` started against the old file, or running across such a
restart, prints nothing until the new numbers pass the old ones; with a
read-only `metrics.db` of 10 000 events that is never in practice. The
guide says "No event is lost or repeated between the history and the live
feed". The dashboard bridge already handles this (I118: "only an older seq
not held resets").

### C7. `events --since` is compared as text *(repro)* — Low

`cli.py:164`, `cli.py:528-530`.

`ts >= ?` compares the argument with stored `…T09:30:00.000Z` strings.
Events at 06:00Z, 09:30Z and 11:00Z:

```
--since '2026-11-14T10:00:00Z'       -> ['e3']
--since '2026-11-14 10:00'           -> ['e1', 'e2', 'e3']   (space sorts before 'T')
--since '2026-11-14T10:00:00+01:00'  -> ['e3']               (09:30Z is after 09:00Z)
--since 'yesterday'                  -> []                   (no error)
```

Nothing says the argument must be UTC with a `T`. The guide's cookbook uses
`2026-10-19T00:00:00Z`; an operator in Stockholm typing local time gets the
wrong hour without a warning.

### C8. A data path with `#` or `?` reads the wrong file *(repro)* — Low

`cli.py:309`, `cli.py:542`, `cli.py:553`.

`sqlite3.connect(f"file:{db}?mode=ro", uri=True)` takes `#` as the start of
a URI fragment and `?` as the query. With the data directory `…/x#y`,
`events` opens `…/x` and fails with `OperationalError: no such table:
events`; `health --extended` reports a database fault that is not there.
`stats.query.open_readonly_connection` and the other read-only openers
percent-encode the path (lessons-learned B4).

### C9. Breach values print in exponent form — Low

`thresholds.py:125-129` `Change.detail`, `cli.py:474-475`.

`f"{value:g}"` keeps six significant digits and switches to exponent form
from 10⁶: an engine p99 of 1 234 567 µs (a 1.2 s stall) reads
`engine_handle_p99_us CRIT 1.23457e+06 > 20000` in the event log, the log
line and `status`. RSS growth and the other rules stay below 10⁶, so the
engine latency rule is the one that can reach it.

---

## 4. Performance findings

None of this matters at today's sizes: every step below is under 0.1 s on
the collector thread, which has a 1 s budget. Only P1 grows with history.

### P1. Seven-day averages scan the whole history *(measured)* — Low

`store.py:549-567` `avg_per_day`, `collector.py:835-854`
`_refresh_averages` (once a minute, on the collector thread).

With `label=None` the query is `name = ? AND date < ?` over
`idx_daily_name(name, label, date)`: the label column sits between name and
date, so SQLite reads every row of the name and groups by date in a temp
B-tree before taking seven. `daily_totals` is kept for good.

| `daily_totals` | rows | `engine.trades` (300 labels) | all 114 averages |
|---|---|---|---|
| 30 days | 43 800 | 3.3 ms | 8.0 ms |
| 365 days | 532 900 | 64.9 ms | 98.0 ms |

```
SEARCH daily_totals USING INDEX idx_daily_name (name=?)
USE TEMP B-TREE FOR GROUP BY
```

The per-participant averages (label given) use the whole index and stay
flat. Cost grows linearly with days of history: about 0.2 s a minute after
two years.

**Fix.** Find the seven latest dates first (an index on `(name, date)`, or
a `DISTINCT date … ORDER BY date DESC LIMIT 7` it can satisfy), then sum
those dates only.

### P2. Every flush rewrites all counter state *(measured)* — Low

`store.py:364`, `store.py:380-384`.

`flush_raw` upserts every tracker series into `counter_last` every 10 s,
changed or not: 10.5 ms per flush at 5 000 series (0.1 % of the loop),
30 000 rows a minute through the WAL. Harmless alone; it is also the
mechanism behind C1, and WP-MON02's fix removes both.

Measured and fine: hourly retention deleting one hour of minute rows of
3 000 series (180 000 rows, `incremental_vacuum` included) takes 61 ms; it
is per series, by primary-key range.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `config.py:77-78` | "``enabled: false`` means … ``pm-monitor`` refuses to start": it idles until stopped (exit 0), as `main.py`, the guide and pm-help say. |
| D2 | `main.py:4-6` | The usage block omits `--log-failover-timeout` and `--version`, which `build_parser` defines. |
| D3 | `store.py:25`, guide table "`counter_last` … Kept `minute_days`" | Never true for a series in the tracker: its row is rewritten every 10 s (C1). Only a source forgotten in this run expires. To restate after WP-MON02. |
| D4 | `rates.py:26-30` (module docstring) | "the first value of a primed series is a `RESUMED` step whose increment is exactly what happened while pm-monitor was down … It counts towards today": not when the primed value is from an earlier date (C2). |
| D5 | Guide "Rates and today" | "counts exactly what happened while `pm-monitor` was down" (C2) and "average per hour … since the session opened today (else since midnight)" (C4) to restate after WP-MON01/04. |
| D6 | Guide `events`, `cli.py:164` help | `--since ISO_TS` does not say which time zone or form; after WP-MON05 say what is accepted. "No event is lost or repeated between the history and the live feed" needs the restart case (C6). |
| D7 | `collector.py:705-710` `publish_event` | "The number continues from metrics.db … and is never reused": without a store it starts at 0 on every start and repeats (C6). |
| D8 | `thresholds.py:4-5` | Module docstring line wrapped wrongly (97 characters, the rest of the paragraph at 79). |

---

## 6. Verified as correct

- **Beacon identity and ordering.** `ProcessState.accept` ignores repeated
  and out-of-order `seq` and older incarnations (`started_at_ns`), so two
  processes claiming one identity show as one with `beacons_stale` rising;
  a burst queued while pm-monitor was down feeds the sparkline in order.
- **DEAD versus SILENT.** `process_alive` checks PID *and* create time
  within 1 s, and treats a zombie as dead; `AccessDenied` counts as alive.
  Remote hosts fall back to time (2 × the limit).
- **Credited silence (I108).** Only silence beyond the SILENT limit is
  credited, and the credit moves from loop age to loop lag once the loop has
  ticked; checked against the module docstring's argument.
- **Exchange status.** Matches the guide's table: bots excluded, STOPPED
  impairs only when the roster expects it, any non-process breach degrades.
- **Threshold hysteresis.** Raise after 5, clear after 30 with the 80 %
  dead band; an inverted rule's critical dead band never reaches into the
  warn band; a vanished reading clears after 30 s.
- **Store transactions.** Raw rows, daily totals and counter state are one
  transaction; a rollback also forgets the series ids it created
  (`_forget_new_series`); a minute written at shutdown is merged, not
  replaced, on restart; a backfilled increment does not enter the current
  minute's delta (I102).
- **Event numbering with a store.** `AUTOINCREMENT`'s `sqlite_sequence`
  keeps the high-water mark past retention, so numbers are not reused.
  `make_health_event` cannot fail validation for the values
  `publish_event` passes (subject ≤ 200 and detail ≤ 512 are truncated
  first; kind and severity come from fixed sets), so its
  `MessageValidationError` branch, which would reuse a number, is
  unreachable.
- **Hourly retention cost** (61 ms for an hour of 3 000 series, §4) and the
  `events.ts` index used by retention and `--since`.
- **Engine bus topics.** `session.state` and `system.diagnostic` are matched
  exactly, so longer topics with the same prefix are ignored; a malformed
  message is counted, not fatal.
- **`reject_pct_5m`.** `MARKET_CLOSED` rejects leave numerator and
  denominator alike; under 20 requests it is not judged.
- **Config loader.** Strict booleans (a quoted `"false"` is refused), port
  and count ranges, and thresholds that must give both edges.

---

## 7. Decisions

All four taken as recommended (2026-11-15).

| # | Question | Recommendation |
|---|---|---|
| Q1 | C2: what does a primed counter value recorded on an earlier trading date mean? (a) Not a resume point: the step follows the `FIRST` rule (whole value to today only if the process started today, else a baseline). (b) Keep counting the difference into today. (c) Split the difference between the dates. | **(a)**: it gives exactly what a fresh `metrics.db` gives, which the guide already documents ("begins the day at zero for processes that started earlier"), and never books one day's counts to another. (b) is today's wrong figure. (c) has nothing to split by: the beacons in between were never received. |
| Q2 | C1: how does counter state of a vanished source expire? (a) Write a `counter_last` row only when the series stepped since the last write (its `ts` is "last seen"), so `minute_days` retention applies; drop primed, never-stepped series from the tracker when their row expires. (b) Keep rewriting, but forget primed series not stepped within `FORGET_AFTER_SEC`. | **(a)**: it reuses the retention the guide already documents, removes P2 as well, and a source back within `minute_days` still resumes exactly. (b) loses the exact resume of a process that is down for more than an hour (an exchange stopped overnight while pm-monitor runs). |
| Q3 | C3: what bounds the backlog while writes fail? (a) Keep at most a fixed backlog of closed minutes (e.g. 10 minutes' worth: the oldest are dropped first) and count every dropped row in `monitor.store_errors`. (b) After N consecutive failures close the store and run without history until restart. | **(a)**: history comes back by itself when space is freed, which matches "costs history, not monitoring"; the counter keeps `metrics_store_errors` raised. (b) needs a restart to recover and loses the daily totals and counter state that would still have been written. |
| Q4 | C7: what does `--since` accept? (a) Any ISO-8601 date-time; with an offset it is converted, without one it is UTC (what the output's `TS` column shows); anything else is a usage error (exit 2). (b) Naive means the session timezone. | **(a)**: the user compares with what the tool prints, which is UTC; one rule, no config needed. (b) would make the same text mean different instants in `--since` and in the output. |

---

## 8. Work packages

### WP-MON01 — A restart never books another day's counts to today (C2; after Q1)

**Tests first** (`tests/test_monitor_store.py`, restart class):

1. Engine started on day 1 and still running; pm-monitor stops at 15:00 on
   day 1 and restarts at 11:00 on day 2 with `engine.orders_in` 6 000 →
   15 000: day 2's `daily_totals` and the snapshot's `orders.today` hold
   0 (a baseline, Q1(a)), not 9 000. (Fails today.)
2. The same with `engine.trades` reset at PRE_OPEN (3 000 → 4 000): day 2
   holds 0, not 1 000. (Fails today.)
3. Engine restarted on day 2 (new `boot_id`, started day 2): its whole value
   counts to day 2. Unchanged.
4. pm-monitor restarted on the same trading date: the resume is exact, as
   today (`test_monitor_store.py`'s existing restart tests). Unchanged.
5. Day boundary while pm-monitor runs: increments go to the date they were
   received on. Unchanged.

**Change.** `MetricsStore.counter_state` also returns each row's trading
date (from `counter_last.ts` in the session timezone); `CounterTracker.prime`
marks series primed on an earlier date; `step` reports their first value as
`Step.FIRST`, which `observe` already handles.

**Exit criteria.** Tests 1–5 pass; `tests/test_monitor_*.py` green.

**Outcome (2026-11-15).** Simpler than planned: `MetricsStore.counter_state(date)`
returns only the `counter_last` rows written on or after the start of trading
date `date` (session timezone), and `_resume_from` rolls the day *before*
priming. A series whose value is from an earlier date is then simply not in
the tracker, so its first value after the restart is a `FIRST` step and
`observe`'s existing started-today rule decides (Q1(a)); no new tracker
state. Tests in `tests/test_monitor_store.py::TestRestartAcrossDays`: the
engine running on (orders 0, not 9 000; trades 0, not 1 000; later beacons
count normally; day 1's totals untouched), an engine started today (whole
value counts), and midnight while pm-monitor runs (unchanged). The first
failed with `assert 9000.0 == 0.0`; the other two passed before and after.
The existing same-day restart tests (I69) are unchanged and pass. D4
(`rates.py` docstring) fixed here, since it describes this code. Full suite:
14 386 passed, 1 skipped.

---

### WP-MON02 — Counter state of a source that never returns expires (C1, P2; after Q2, WP-MON01)

**Tests first** (`tests/test_monitor_store.py`):

1. Repro of C1: a source primed but never heard from again has its
   `counter_last` rows deleted by the first retention pass after
   `minute_days`, and is gone from the tracker (`monitor.series_tracked`
   drops). (Fails today.)
2. A flush with no counter changed writes no `counter_last` row (count the
   rows changed via `conn.total_changes`). (Fails today.)
3. A source back within `minute_days` resumes exactly (C2's same-day
   restart test). Unchanged.
4. Kill between flushes: daily totals and counter state still agree (the
   existing I69 test). Unchanged.

**Change.** The tracker records which series stepped since the last flush;
`flush_raw` writes only those rows. At retention, primed series never
stepped whose rows were deleted are dropped from the tracker.

**Exit criteria.** Tests 1–4 pass; `tests/test_monitor_*.py` green;
`flush_raw` at 5 000 unchanged series measured below 1 ms (from 10.5 ms).

**Outcome (2026-11-15).** One refinement of Q2(a), forced by WP-MON01: since
only rows written *today* are primed, writing a row only when its value
changed would leave a quiet counter (a participant with no orders yet today)
on yesterday's row, and a restart would no longer resume it. So
`flush_raw` gets the series *heard* since the last write
(`CounterTracker.heard()`, cleared only after a successful write) and writes
a row when its value or `boot_id` changed **or** it has not been written yet
on the current trading date (`MetricsStore._written`, seeded by
`counter_state`). A series not heard keeps the row of when it was, so
`minute_days` retention deletes it; the deleted keys come back from
`_delete_old` (`DELETE … RETURNING`) and are booked after the commit, and
`CounterTracker.forget_expired` drops those still primed and never stepped.
`CounterTracker.state` is gone (its two callers now use `heard()`).
Tests in `tests/test_monitor_store.py::TestCounterState`: a primed source
never heard again for eight days is gone from `counter_last` and the tracker
(failed: tracker length 1), an unchanged counter keeps its first row's `ts`
(failed: rewritten 10 s later), and a quiet counter heard on a new date is
written once that day and resumes exactly after a restart (passed before and
after; it guards the refinement). Measured: `flush_raw` with 5 000 heard,
unchanged series 0.93 ms (from 10.5 ms); with all 5 000 changed 12.2 ms.
Full suite: 14 405 passed, 1 skipped. `make _check` fails on mypy in
`tests/test_balf_gwy_sessions.py`, an untracked BALF file changed by other
work in progress; `mypy`/`pyright` on the monitor package and its tests are
clean.

---

### WP-MON03 — A failing `metrics.db` cannot grow pm-monitor's memory (C3; after Q3)

**Tests first** (`tests/test_monitor_store.py`):

1. Every write failing for two simulated hours at 400 series: the pending
   closed minutes never exceed the cap, and `monitor.store_errors` counts
   every dropped row. (Fails today.)
2. When writes succeed again, the minutes still held are written and the
   cap's oldest-first dropping left no gap inside what was kept. (Fails
   today.)
3. A single failed flush followed by a good one loses nothing. Unchanged.

**Change.** `MetricsStore` bounds `_closed` (Q3(a)) and reports how many
rows it dropped; `store_tick` adds them to `store_errors`.

**Exit criteria.** Tests 1–3 pass; `tests/test_monitor_*.py` green.

**Outcome (2026-11-15).** The cap is by age: `store.BACKLOG_SEC` (600 s).
`flush_minutes` drops closed minutes that started more than ten minutes
before the current one and adds them to `MetricsStore.dropped_rows`;
`store_tick` moves that count into `monitor.store_errors` after every tick,
so `metrics_store_errors` stays raised. Normally `_closed` is empty after a
tick, so the filter costs nothing. Tests in
`tests/test_monitor_store.py::TestFailingWrites`: two hours of failing
writes at 40 series keep at most 11 minutes per series and count the rest,
and once writes succeed the newest minutes are written with no gap (failed:
4 760 pending rows against a bound of 440); one failed write then a good one
loses nothing (failed only on the new `dropped_rows` attribute; the
behaviour was already right); in the collector, dropped minutes add to
`store_errors` beyond one per failed write (failed). Repro of C3 after the
change: 4 050 pending rows and 5.0 MB from minute 30 on (was 48 600 rows and
26 MB after two hours, still growing); a failing tick costs 2.7 ms. Full
suite: 14 409 passed, 1 skipped (mypy in `make _check` fails only in the
BALF files under other work).

---

### WP-MON04 — Figures stay right after a restart or a removed book (C4, C5)

**Tests first** (`tests/test_monitor_snapshot.py`, `tests/test_monitor_store.py`):

1. Repro of C4: restart at 11:00 with a `SESSION` event `CLOSED -> …` at
   09:00 in `metrics.db`: `avg_per_hour` is today ÷ 2, not ÷ 11. (Fails
   today.)
2. Restart before the open (no such event today): from midnight, as now.
   Unchanged.
3. Repro of C5: an engine beacon without `OLD` removes it from `books` and
   its `heap_bloat_ratio` breach clears after `CLEAR_AFTER`. (Fails today.)
4. While the engine is STOPPED or DEAD, books are not judged (no new
   breach). (Fails today.)
5. A book in every beacon keeps its gauges. Unchanged.

**Change.** `_resume_from` reads today's first `SESSION` event leaving
`CLOSED` and sets `session_opened_at`. An engine beacon replaces the book
gauges, as a gateway beacon replaces its gauges (`activity.py:293`); a
book's `trades` today stay. `readings` judges books only while an engine is
live.

**Exit criteria.** Tests 1–5 pass; `tests/test_monitor_*.py` and
`tests/test_dash_*_mirror.py` green.

**Outcome (2026-11-15).** `MetricsStore.session_opened(date)` returns the
time of the date's first `SESSION` event whose detail is `CLOSED -> …` (the
form `events.translate` writes), and `_resume_from` sets
`session_opened_at` from it. Before relying on "absent from a beacon means
gone" it was checked that `Engine.metric_samples` adds every book's cached
`book_samples` and `engine.book_halted` to every beacon, and that the
reporter caps nothing (`_valid_samples` drops only invalid samples). So
`Activity.observe` empties every book's gauges on each engine beacon,
`book_records` lists only books with gauges (a book's `trades` today stay
in memory), and `readings` judges books only while a pm-engine source is
live. A STOPPED engine's books are still listed as last seen. Tests:
`tests/test_monitor_store.py::TestSessionOpenedAfterRestart` (avg/hour from
the open after a restart: failed with 1 090.8 against 5 995.8; from midnight
before any open, and an open on an earlier date ignored: passed before and
after) and two in `tests/test_monitor_snapshot.py` (a book the restarted
engine no longer reports leaves `books` and its CRIT clears, exchange
OPERATIONAL: failed with `['AAA', 'OLD']`; a STOPPED engine's book is not
judged: failed with a CRIT). Full suite: 14 418 passed, 1 skipped. One
earlier run in this WP showed 10 failures that two reruns did not
reproduce; BALF files were being changed by other work at the time, and the
failures were not captured, so they are not attributed here.

---

### WP-MON05 — `pm-monitor-cli`: exact times, any data path, follow across a new numbering (C6, C7, C8, C9; after Q4)

**Tests first** (`tests/test_monitor_cli.py`, `tests/test_monitor_thresholds.py`):

1. `--since '2026-11-14 10:00'`, `…T10:00`, `…T10:00:00Z` and
   `…T11:00:00+01:00` all return exactly the events at or after 10:00Z.
   (Fails today.)
2. `--since yesterday` is a usage error, exit 2. (Fails today.)
3. `events` and `health --extended` work with a data directory named
   `x#y` and `a?b`. (Fails today.)
4. `_follow` with a history whose newest `seq` is 500 and live events
   numbered from 0 (with timestamps after the history's newest) prints
   them. (Fails today.)
5. A live event already in the history (subscribe before history read) is
   not printed twice. Unchanged.
6. `Change.detail` and `status` print `1234567` for a 1 234 567 µs p99, not
   an exponent. (Fails today.)

**Change.** Parse `--since` with `datetime.fromisoformat` (Q4) and query
with the canonical form; build the read-only URI with the percent-encoded
path, as `stats.query.open_readonly_connection` does; in `_follow`, a lower
`seq` whose event is not in the history (or is there with another `ts`)
starts a new numbering; format values with a fixed, non-exponent format.

**Exit criteria.** Tests 1–6 pass; `make completion` up to date;
`tests/test_monitor_*.py` and `tests/test_shell_completion.py` green.

**Outcome (2026-11-15).** `cli.iso_instant` is the `--since` argparse type:
`datetime.fromisoformat` (date only, `T` or space, `Z` or an offset), no
offset means UTC, and the value is turned into the stored form with
`timefmt.iso_utc`; anything else is argparse's usage error (exit 2,
"argument --since: not an ISO-8601 date-time …"). `cli._open_readonly`
percent-encodes the resolved path as `stats.query.open_readonly_connection`
does (that opener was not reused: it raises a "Statistics DB" error, logs as
pm-stats and sets a row factory), with `timeout=2.0`; it replaces the three
URI connects, and `query_events`' separate `busy_timeout` pragma went with
it. In `_follow`, a live event at or below the last seq is skipped only if
metrics.db holds that seq with the same `ts` (`_in_history`); otherwise it
starts a new numbering. `thresholds.fmt_value` (three decimals at most,
never an exponent) formats `Change.detail` and the `status` breach table;
the guide's `WARN 81 > 80` form is unchanged. Tests in
`tests/test_monitor_cli.py` (`TestSince`, `test_a_data_path_with_uri_characters`
for `#`, `?` and `%41`, `test_follow_takes_a_new_numbering`,
`test_breach_values_print_without_an_exponent`) and
`tests/test_monitor_thresholds.py`. Failed first: the space and `+01:00`
forms (`[1, 2, 3]`, `[3]`), `yesterday` (exit 0), all three paths ("no such
table: events", "unable to open"), the follow (never returned; the test runs
it on a thread with a 5 s bound, since the old code waits for ever), and
both exponent checks. The `T10:00`, date-only and `T11:00+01:00` cases passed
before by string order and still pass. `make completion` regenerated
`pm-completion.zsh`. Full suite: 14 432 passed, 1 skipped; `make _check`
clean.

---

### WP-MON06 — Daily averages read seven dates, not the whole history (P1)

**Tests first** (`tests/test_monitor_store_perf.py`, `tests/test_monitor_store.py`):

1. The SQL `avg_per_day(…, label=None)` executes (captured with
   `set_trace_callback`) has no `USE TEMP B-TREE` and reads only the last
   seven dates' rows (plan asserts an index range on date). (Fails today.)
2. Averages with and without a label, gaps in dates, fewer than seven dates
   and none: same values as today. Unchanged.

**Change.** An index or query shape that selects the seven latest dates of a
name first (see P1); `make dbdocs` if the schema changes.

**Exit criteria.** Tests 1–2 pass; `_refresh_averages` at 365 days measured
under 10 ms (from 98 ms; a guess from the 30-day figure).

**Outcome (2026-11-15).** A new index `idx_daily_name_date(name, date)` and a
two-step query: `SELECT DISTINCT date … ORDER BY date DESC LIMIT ?` (served
from the covering index, newest first) inside `date IN (…)` for the sums,
with the label filter in both parts when given. The schema statement is
idempotent, so an existing `metrics.db` gets the index when pm-monitor next
opens it; `make dbdocs` regenerated `040-sqlite-schemas.md`. Tests in
`tests/test_monitor_store.py`: the plan of the SQL actually executed
(captured with `set_trace_callback`) has no `TEMP B-TREE` and no `SCAN`, for
all labels (failed: `USE TEMP B-TREE FOR GROUP BY`) and for one label
(passed before and after); values with gaps, fewer than seven dates, an
unknown label and no data (passed before and after). Measured at 365 days:
all 114 averages 5.1 ms (from 98 ms), `engine.trades` over all labels 0.4 ms
(from 64.9 ms), the same as at 30 days. Full suite: 14 435 passed,
1 skipped; `make _check` clean.

---

### WP-MON07 — Comments, docstrings, help texts, operator guide (D1–D8)

**Tests first.** Text-only; `tests/test_docs_monitor_config.py` and the
docs tests stay green.

**Change.** Fix D1–D8 against the code as it ends up. Re-walk the guide's
"Starting", "Rates and today", "`metrics.db`" and "`events`" sections and
the troubleshooting table against WP-MON01–06 (lessons-learned B1).

**Exit criteria.** Every D item fixed; `make _check` clean.

**Outcome (2026-11-15).** D1 (`config.py`: idles), D2 (`main.py` usage),
D3 (`store.py` docstring and the guide's `counter_last` row: written on
change and once a day, kept `minute_days` after last heard), D5 (guide
"Rates and today": same-date resume, the date-change rule, avg/hour from
today's `SESSION` event), D6 (guide `events`: accepted `--since` forms, a
new numbering; the `--help` text changed in WP-MON05), D7
(`publish_event` docstring), D8 (`thresholds.py` wrap). D4 was fixed in
WP-MON01. Also from the re-walk (lessons-learned B1): the guide's failing-
write paragraph now says what is held and dropped (WP-MON03), the
troubleshooting row "Today's counts start from zero" names the date-change
case, and `store.py`'s docstring describes the backlog cap and the
`counter_last` retention. The guide's `--since` examples were run through
`cli.iso_instant`. Re-walked and unchanged: the SIGTERM final picture
(`close` flushes the heard counters), `pm-opctl-cli clear --all` (a new
file numbers events anew, which `--follow` now takes), the dashboard
chapter (its books row and the "No process … in the latest snapshot" row
hold). Full suite: 14 435 passed, 1 skipped; `make _check` clean.

---

## 9. Out of scope, noted

- **A host rename while pm-monitor keeps running.** Sources are keyed by
  host; an expected identity under its old host stays DEAD (and, for a
  non-engine process, IMPAIRED) as long as pm-monitor runs, because roster
  identities are never forgotten (`collector.py:491-494`). Every shipped
  container sets `hostname: edumatcher`, and a source install restarts
  pm-monitor with the exchange, so this was not pursued. No For-Later entry.
- **The dash-gui bridge** reads `metrics.db` and was not reviewed; it already
  resets on a lower event `seq` (I118), so C6 is the CLI's only.

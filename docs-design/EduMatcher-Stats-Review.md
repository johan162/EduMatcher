# Statistics & Reporting — Pre-Ship Review

Scope: `src/edumatcher/stats/{main,query,cli}.py` and
`docs/user-guide/140-statistics-and-reporting.md`.

Severity key:

- **P0** — produces *wrong* numbers or silent data loss. Must fix before ship.
- **P1** — correctness/robustness risk, or documentation that will mislead a user
  into believing a wrong number.
- **P2** — dead code, redundancy, documentation gaps.
- **GAP** — missing information in the data model. Safe to defer to a later
  release, listed so the decision is explicit.

Findings marked *(verified)* were reproduced by running the actual code against
the actual `SCHEMA`.

---

## P0 — Ship blockers

### P0-1. A `pm-stats` restart mid-session silently destroys the day's OHLCV, volume and VWAP

`main.py` contains **no `SELECT` at all** (`grep -c SELECT` → `0`). Accumulators
live only in memory, and `UPSERT_DAILY` overwrites *every* column
unconditionally:

```sql
ON CONFLICT(date, symbol) DO UPDATE SET
    open_price = excluded.open_price,
    ...
    volume     = excluded.volume,
    vwap       = excluded.vwap,
```

Sequence:

1. `pm-stats` runs from 09:00–14:00. `daily_stats` for today holds
   `open_price=150`, `high=158`, `low=149`, `volume=1_000_000`, `vwap=153.2`.
2. `pm-stats` is restarted (crash, redeploy, operator).
3. `_accum_for("AAPL")` finds nothing in `self._accum`, creates a **blank**
   `_DayAccum`.
4. The next trade at 14:01 fires `_flush_daily`, which writes
   `open_price=<14:01 price>`, `high=low=<14:01 price>`, `volume=<that trade>`,
   `vwap=<that price>`.

The morning is gone. **Volume goes down. Open price changes retroactively. VWAP
is wrong.** Nothing logs, nothing errors, and the row still looks perfectly
plausible. `index_daily_stats` has the identical bug via `UPSERT_INDEX_DAILY`
(`open_level`, `high_level`, `low_level`, `update_count` all reset).

This is the single most dangerous defect in the module, and it is exactly the
"wrong information is a catastrophe" case.

**Fix.** Rehydrate on first touch of a `(date, symbol)`. `trade_log` is keyed on
`trade_id` with `INSERT OR IGNORE`, so it is a lossless source:

```sql
SELECT COUNT(*), SUM(quantity), SUM(price*quantity), MIN(price), MAX(price),
       MAX(quantity)
FROM trade_log WHERE symbol = ? AND substr(ts,1,10) = ?
```

…plus the first/last trade for open/close. `open_bid`/`open_ask` and
`_pv_sum`/`_q_sum` can be recovered the same way. For indexes, rehydrate from
`index_level_snapshots`. Do this lazily inside `_accum_for` /
`_index_accum_for` so the cost is one query per symbol per process lifetime.

*(An alternative — making the UPSERT use `MIN()`/`MAX()`/`volume + excluded.volume`
— does **not** work here, because `_flush_daily` re-writes the same cumulative
accumulator on every trade. It would double-count. Rehydration is the correct
fix.)*

There is currently **no test covering a mid-day restart** (`grep restart
tests/test_stats_and_orders.py` → nothing). Add one.

---

### P0-2. `--from` / `--to` timestamp bounds are lexicographic string comparisons — silently wrong result sets *(verified)*

Every range filter in `query.py` does a raw string compare against the stored
ISO text:

```python
sql += " AND ts >= ?"    # ts is TEXT: "2026-06-14T16:30:00.500+00:00"
```

`validate_iso_ts()` happily accepts `Z` suffixes and non-UTC offsets, then hands
them straight to a byte-wise comparison. Reproduced against the real schema:

| Bound passed | Rows returned | Correct answer |
|---|---|---|
| `--to 2026-06-14T16:30:00+00:00` | 1 | 2 |
| `--from 2026-06-14T09:00:00Z` | 1 | 2 |
| `--from 2026-06-14T11:00:00+02:00` | 1 | 2 |

Three independent failure modes:

1. **`Z` suffix.** `'Z'` (0x5A) sorts *after* `'+'` (0x2B), so
   `"…T09:00:00Z" > "…T09:00:00+00:00"` and the 09:00:00 row is excluded. The
   validator explicitly accepts `Z`, so the user has every reason to think it
   works.
2. **Non-UTC offsets.** `11:00:00+02:00` is the same instant as `09:00:00Z`, but
   compares as `"11…" > "09…"`. Any user in CET who types their local time gets a
   silently truncated result set — no error, just missing trades.
3. **Precision mismatch.** `trade_log.ts` / `index_level_snapshots.ts` use
   `timespec="milliseconds"`, `price_snapshots.ts` uses `timespec="seconds"`.
   A `--to` at second granularity drops every sub-second row inside that second,
   because `'+'` (0x2B) < `'.'` (0x2E). `--to …16:30:00+00:00` excludes
   `…16:30:00.500+00:00`, which contradicts the documented "inclusive upper
   bound".

The same defect reaches the REST API — `/api/v1/history/*` passes `from`/`to`
through to these functions unchanged, and the docs describe them as "Inclusive
ISO timestamp lower/upper bound".

**Fix.** Normalise both the stored value and the bound to a single canonical
form before comparison. Cheapest correct change: parse the bound with
`datetime.fromisoformat`, convert to UTC, and re-emit in the exact stored format
with an explicit precision floor/ceiling (`>= from` at `.000`, `<= to` at
`.999`). The robust change: store `ts` as integer epoch-milliseconds with a
generated ISO view column. Either way, add a test matrix over `Z`, `+02:00`,
naked-local, second- and millisecond-precision bounds.

---

### P0-3. The CLI silently truncates at `--limit`, and the documentation's own validation recipes depend on it

`query_*` all return `(rows, next_cursor)`. `cli.py` discards the cursor in
every call site:

```python
rows, _next_cursor = query_trades(...)
```

There is no `has_more`, no warning, no non-zero exit. Defaults are `trades=200`,
`snapshots=500`, `order-events=500`, `daily=100`. So the documented recipe:

```bash
pm-stats-cli --format csv trades --date 2026-06-14 | wc -l   # doc §Validation
```

…caps at **201** lines regardless of the real trade count, and the doc tells the
reader to "Verify: matches expected number from the trading floor." A reader
following that instruction on a day with 5 000 trades will read `201`, conclude
the counts mismatch (or worse, that 200 trades printed), and be wrong either
way. The `wc -l` also counts the CSV header — off by one on top.

The VWAP-verification recipe in §"VWAP calculation looks wrong" has the same
problem: it recomputes VWAP from at most 200 trades and compares it to a
full-day `daily_stats.vwap`. It will report a mismatch on any active day and
send the reader chasing a phantom bug.

**Fix.** Print a `[WARN] result truncated at N rows; more data available` to
stderr whenever `next_cursor is not None`, and expose `--after` so the CLI can
actually page. Then correct the two recipes.

---

### P0-4. The documented multi-day history recipes return exactly one day *(verified)*

Docs §"Multi-Day Price Trends":

```bash
pm-stats-cli --format csv daily --symbol AAPL --limit 100 > aapl_history.csv
```

> "This gives you historical OHLCV to track trends, seasonal patterns, or
> support/resistance zones over time."

It does not. With `date_value=None` and no `from_date`/`to_date`, `query_daily`
resolves `selected_date = latest_daily_date(conn)` and filters `WHERE date = ?`.
Verified against a 3-date DB: **1 row returned**. The file is a one-day CSV
labelled `aapl_history.csv`.

Identical problem in §"Index Level History":

```bash
pm-stats-cli --format csv index-daily --index-id EDU100 --limit 100 > edu100_history.csv
```

The range mode exists — `query_daily`/`query_index_daily` accept
`from_date`/`to_date`, and `/api/v1/history/daily` exposes them — but **the CLI
never passes them and the user guide never mentions them.** A whole public
capability is undocumented while a recipe that cannot work is documented in its
place.

**Fix.** Add `--from-date` / `--to-date` to the `daily` and `index-daily`
subcommands (one `argparse` line and one kwarg each), then correct both recipes.

---

### P0-5. `daily_stats.date` is a **local** date; every `ts` column is **UTC**

`_today()` returns `date.today().isoformat()` — the recorder host's local
calendar date. Every timestamp written (`trade_log.ts`, `price_snapshots.ts`,
`index_level_snapshots.ts`, `order_events.ts`) is UTC. The date filters in
`query.py` use `substr(ts, 1, 10)` — a UTC date.

So `--date 2026-06-14` means two different things depending on the subcommand,
and for any host not on UTC the two disagree for part of every day. Worst case is
`query_symbols`, which mixes both in a single statement:

```sql
SELECT symbol FROM daily_stats     WHERE date = ?               -- local date
UNION SELECT symbol FROM price_snapshots WHERE substr(ts,1,10) = ?  -- UTC date
UNION SELECT symbol FROM trade_log       WHERE substr(ts,1,10) = ?  -- UTC date
```

For a host at UTC+2, trades between 22:00 and 24:00 UTC are booked into
`daily_stats` for the *next* local day while their `trade_log` rows carry the
current UTC day. The VWAP-verification recipe (recompute from `trade_log`,
compare to `daily_stats`) will disagree for exactly those trades — and the doc
tells the reader "they should match".

`pm-ticker` inherits this too (`ticker/main.py:352` uses `date.today()`).

**Fix.** Pick one clock and state it. For an exchange the correct answer is a
*trading date* driven by the venue session, not the host's `date.today()`.
Minimum viable fix: use UTC everywhere (`datetime.now(timezone.utc).date()`),
document that `date` is a UTC calendar date, and derive the day bucket from the
trade's own `timestamp` rather than from processing wall-clock time. The
documentation currently says nothing at all about this.

---

### P0-6. No WAL and no `busy_timeout` on the writer — a reader can silently destroy a trade record

`_open_db()` sets no pragmas. `open_readonly_connection()` opens `mode=ro`. In
SQLite's default rollback-journal mode a reader holds a SHARED lock that blocks
the writer's RESERVED lock, and with no `busy_timeout` the writer raises
`sqlite3.OperationalError: database is locked` **immediately**.

That exception surfaces inside `_on_trade`, and `_receive` swallows it:

```python
except Exception as exc:
    log.warning("error handling topic=%s err=%s", topic, exc)
```

At the default `WARNING` level the line is emitted — but the trade is **gone**.
No retry, no dead-letter, no counter. Running `pm-stats-cli` or `pm-ticker`
against a live recorder can therefore drop trades from the permanent record.

The docs assert the opposite:

> "Between transactions no lock is held, so `pm-stats-cli` reads are never
> blocked."

That is backwards — it is the *writer* that gets blocked, and it does not
survive it.

Note that `audit/indexer.py:78` and `clearing/store.py:51` already set
`journal_mode=WAL` + `synchronous=NORMAL`. The stats store is the odd one out,
which strongly suggests oversight rather than a deliberate choice.

**Fix.** `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;` on the writer,
`conn.execute("PRAGMA busy_timeout=5000")` on both connections, and make the
handler exception path in `_receive` count failures and log at `ERROR`.

---

### P0-7. The recorder can die while the process stays "up", recording nothing, exiting 0

Two paths in `_receive`:

```python
except zmq.ZMQError as exc:
    if exc.errno != errno.EINTR:
        raise          # ← dies in a daemon thread
    break              # ← exits the loop without clearing self._running
```

Neither clears `self._running`. `run()` then spins:

```python
while self._running:
    t.join(timeout=0.5)   # returns instantly — the thread is dead
```

Result: a busy loop at 100 % CPU, "recording market statistics" still in the
log, zero rows being written, and eventually a clean `exit 0`. Any supervisor or
operator checking `ps aux | grep pm-stats` (which is exactly what the
troubleshooting section tells them to do) sees a healthy process.

**Fix.** Set `self._running = False` in both branches, record the cause, and
have `run()` exit non-zero when the receive thread terminated unexpectedly. A
statistics recorder that fails must fail loudly.

---

## P1 — Correctness and robustness

### P1-1. Combo / OCO / quote rejections are indistinguishable from acceptances

```python
if topic.startswith("combo."): return "COMBO"
if topic.startswith("oco."):   return "OCO"
if topic.startswith("quote."): return "QUOTE"
```

`combo.ack` carries `accepted: bool` (`models/message.py:466`), as do `oco.ack`
and `quote.ack` — but the flag is thrown away. `oco.cancelled.*` is recorded as
`OCO`, not `CANCEL`. `combo.status.*` and `combo.ack.*` collapse to the same
value.

The user guide claims this workflow answers:

> - Was the order accepted or rejected?
> - Was the order cancelled, expired, or linked to a combo/OCO group?

For combo/OCO/quote events, it cannot. `--event-type CANCEL` will never return a
cancelled OCO. Either widen the enum (`COMBO_ACK` / `COMBO_REJECT` /
`OCO_CANCEL` / …) or document the limitation precisely — but the current
documentation is an overclaim.

### P1-2. `order.ack` → `REJECT` on a missing field

```python
return "ACK" if payload.get("accepted") else "REJECT"
```

Today `accepted` is always populated, so this is latent. But the failure mode —
a payload change silently reclassifying every accepted order as **REJECT** in
the audit trail — is severe enough to warrant an explicit check:

```python
accepted = payload.get("accepted")
if accepted is None:
    log.error("order.ack without 'accepted' field: %s", topic)
```

### P1-3. `close()` runs without the lock; `join(timeout=1.0)` is not a guarantee

```python
finally:
    t.join(timeout=1.0)
    self.close()          # closes self._conn — no self._lock held
```

The comment says "Wait for the receive thread to finish its current message" but
a timed `join` does not wait, it gives up. If the receive thread is mid-`with
self._conn:` when the timeout expires, `close()` yanks the connection and the
in-flight write raises `ProgrammingError`. Unlikely with a 300 ms poll, but it
is free to fix: take `self._lock` in `close()`, and log at ERROR if the join
times out rather than proceeding silently.

`__del__` calling `close()` compounds this — a GC-time close can race a live
receive thread. Since `run()` already closes deterministically, `__del__` is
mostly a liability.

### P1-4. Trade insert and daily upsert are not atomic, and cost two fsyncs per trade

```python
with self._lock:
    acc.on_trade(price, qty)
    self._flush_daily(acc)      # transaction 1 (commit)
    with self._conn:
        self._conn.execute(INSERT_TRADE, ...)   # transaction 2 (commit)
```

A crash between the two leaves `daily_stats` and `trade_log` inconsistent —
precisely the invariant the VWAP-verification recipe relies on. Wrap both in a
single `with self._conn:`. This also halves the fsync count; with default
`synchronous=FULL` and no WAL, this is currently two disk syncs per trade.

### P1-5. The first price snapshot is skipped on a recently-booted host

```python
self._last_snap_ts: dict[str, float] = defaultdict(float)   # default 0.0
...
if now - self._last_snap_ts[symbol] >= self._snapshot_interval_sec:
```

`now` is `time.monotonic()`, which on Linux/macOS is seconds since boot. The
first snapshot therefore requires `monotonic() >= 900`. On a host up less than
15 minutes — a fresh VM, a container, a demo laptop — **no opening snapshot is
written**, and none appears until the boot clock passes the interval. This
directly defeats the startup book-snapshot request whose stated purpose
(`_on_startup_symbols` docstring, and doc step 3) is to guarantee an initial
`price_snapshots` row.

Initialise with a sentinel (`-inf`, or `None` meaning "never") instead of `0.0`.

### P1-6. No schema versioning or migration path

`SCHEMA` is `CREATE TABLE IF NOT EXISTS` only. Point `pm-stats` at a `stats.db`
written by an earlier release and the tables are left untouched — a column added
in this release is silently absent, and the `INSERT` fails at runtime with a
column-count error (or worse, an older DB with a *superset* just works and
reports stale semantics). Nothing records which schema version a file is.

Add `PRAGMA user_version`, check it at open, and either migrate or refuse. This
is a required item before shipping a persisted format to users.

### P1-7. `quantity` falsy-fallback loses a legitimate zero

```python
payload.get("quantity") or payload.get("qty")
```

`quantity=0` falls through to `qty`, and if that is absent the column is `NULL`.
Use explicit `is None` chaining.

### P1-8. Day bucketing uses processing time, not event time

`_on_trade` derives `ts` from `payload["timestamp"]` but buckets the trade via
`self._accum_for(symbol)` → `date.today()` *at processing time*. A trade whose
engine timestamp is 23:59:59.9 but which is processed at 00:00:00.1 lands in the
wrong day's `daily_stats` while its `trade_log.ts` says otherwise. Derive the
bucket from the payload timestamp.

Also: `payload.get("timestamp", time.time())` silently substitutes receipt time
if the engine omits the field. For an audit-grade record this should log.

### P1-9. `pct_change` can silently span more than one interval

`_last_snap_mid[symbol]` is updated whenever `mid is not None`, but the row
insert is `INSERT OR IGNORE` — if the `(ts, symbol)` key collides the row is
dropped while the baseline still advances. Likewise, a snapshot with `mid=None`
writes `pct_change=NULL` and leaves the baseline stale, so the *next* snapshot's
percentage silently covers two intervals. Neither case is distinguishable in the
output. Record the baseline timestamp alongside the value, or document the
behaviour.

### P1-10. No message-loss detection anywhere in the pipeline

`make_subscriber` sets no `RCVHWM`, so the ZMQ default of 1 000 applies. ZMQ
PUB/SUB is lossy by design: a slow subscriber silently drops messages at the
high-water mark. `pm-stats` has no sequence numbers, no gap detection, and no
counter that survives a non-DEBUG log level (`_dbg_count` early-returns unless
`log.isEnabledFor(DEBUG)`).

Consequence: **there is currently no way to demonstrate that `stats.db` contains
every trade the engine printed.** For a system whose statistics "must be 100 %
correct", that is a structural gap rather than a bug — see GAP-6.

Short-term: raise `RCVHWM` on the stats subscriber and export the message
counters unconditionally (they are cheap).

### P1-11. Nothing prevents two `pm-stats` writers on one database

Two instances would each keep independent accumulators and clobber each other's
`daily_stats` rows (per P0-1), and duplicate every `order_events` row —
`INSERT_ORDER_EVENT` has no `OR IGNORE` and no natural key. Take an advisory
lock (an exclusive lock file next to the DB, or a `sqlite` `BEGIN EXCLUSIVE`
sentinel row) and refuse to start. Document the single-writer contract.

### P1-12. Money is stored as binary floating point

`price`, `vwap`, `mid_price`, `aggregate_cap`, `level`, `divisor` are all
`REAL`. `_pv_sum` accumulates `price * qty` in a Python float over the whole
day. For a teaching exchange this is defensible, but it should be a *documented*
decision with a stated precision bound, not an implicit one — a VWAP that
differs from a hand-computed value in the 12th digit will generate support
tickets. `aggregate_cap` in the 10^12 range plus float VWAP accumulation is the
combination most likely to bite.

---

## P2 — Dead code, redundancy, and inconsistency

| # | Location | Issue |
|---|---|---|
| 1 | `query.py` | `query_snapshots` and `query_price_snapshots` are near-duplicates. The docstring acknowledges it ("predates the keyset-pagination work"). The CLI uses the unpaginated one, the API the paginated one, so the CLI has no pagination path at all. Delete `query_snapshots` and have the CLI drop the cursor. |
| 2 | `query.py:203`, `:598` | `ORDER BY date DESC, symbol ASC` in the single-date branch, where `date` is pinned by `WHERE date = ?`. The `date DESC` is a no-op. |
| 3 | `cli.py` (5 sites) | `rows, _next_cursor = ...` — the cursor is computed and discarded. Either use it (P0-3) or the functions should not compute it for CLI callers. |
| 4 | `cli.py:306` etc. | `args.symbol.upper()`, `args.gateway.upper()`, `args.index_id.upper()` force uppercase — while the troubleshooting section says "Verify the symbol is correct (case-sensitive)". Contradictory. One or the other must change. |
| 5 | `cli.py` | `--no-header` is documented as "useful for CSV scripts" but also suppresses the table header. Harmless, but the help text is narrower than the behaviour. |
| 6 | `query.py:88` | `sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)` does not URI-escape the path. A path containing `?` or `#` silently opens the wrong file / fails obscurely. |
| 7 | `query.py:99` | `validate_date` accepts any `%Y-%m-%d`-parseable string including `2026-6-4`, which then never matches the zero-padded stored form. Returns "No rows found." instead of an error. |
| 8 | `main.py:920` | `__del__` → `close()`; redundant with the deterministic close in `run()` and a GC-race liability. |

---

## Documentation review — `140-statistics-and-reporting.md`

### Statements that are factually wrong

| Location | Claim | Reality |
|---|---|---|
| §Running the recorder | "`pm-stats` must start **after** the engine binds its ZeroMQ sockets. If you start it before the engine, it will fail to connect." | ZMQ `connect()` is asynchronous and retries indefinitely; it does not fail. What actually happens is the startup symbols request may be lost, so opening bid/ask is missed. Rewrite to say that. |
| §Troubleshooting → Database is locked | "Between transactions no lock is held, so `pm-stats-cli` reads are never blocked." | Backwards, and dangerous — see P0-6. It is the writer that gets blocked, and it drops the record. |
| §Multi-Day Price Trends | `daily --symbol AAPL --limit 100` "gives you historical OHLCV" | Returns one date. P0-4. |
| §Index Level History | `index-daily --index-id EDU100 --limit 100` as a history export | Same. P0-4. |
| §Validation step 2 | `trades --date … \| wc -l` "matches expected number from the trading floor" | Capped at 200 rows + header. P0-3. |
| §VWAP calculation looks wrong | recompute from CSV, "they should match" | Capped at 200 trades (P0-3) and crosses the local/UTC date boundary (P0-5). Will mismatch on any active day. |
| §Troubleshooting → empty books | `snapshots … \| grep -E "(null\|^-)"` | `_stringify` renders `None` as the **empty string** in table format, never `null`. The grep can never match. |
| §snapshots example output | `pct_change` shown as `null` | Table format prints empty. Only `--format json` prints `null`. |
| §snapshots / §trades example output | `2026-06-14T09:00:00`, `2026-06-14T09:00:01.000` | Real output carries the offset: `2026-06-14T09:00:00+00:00`, `2026-06-14T09:00:01.000+00:00`. This matters because users copy these strings into `--from`/`--to` — and the truncated form is exactly the one that silently misbehaves (P0-2). |
| §Exporting to BI Tools | `sqlite3 analysis.db < <<EOF` | Shell syntax error. Should be `sqlite3 analysis.db <<EOF`. |
| §Troubleshooting → symbols | "Verify the symbol is correct (case-sensitive)" | The CLI uppercases the argument. |
| §price_snapshots | "captured every 15 minutes per symbol" | Captured *at most* every 15 minutes, and only when a `book.*` message arrives. The troubleshooting section says this correctly; the schema section overstates it. |

### Schema documentation gaps

The schema tables list column name, type and description, but omit the things a
consumer actually needs to write a correct query:

- **No primary keys, indexes, uniqueness or nullability.** A reader cannot tell
  that `price_snapshots` is `PK(ts, symbol)` and that a same-second duplicate is
  `INSERT OR IGNORE`-dropped, or that `trade_id` is the sole PK of `trade_log`.
- **No units or precision.** `pct_change` is documented as percent (good);
  `aggregate_cap`, `divisor`, `level` have no stated units or currency.
- **`daily_stats.date` timezone is undefined** — and, per P0-5, is *not* the same
  clock as the `ts` columns. This must be stated explicitly.
- **`largest_trade_qty` defaults to `0`, not `NULL`,** on a day with no trades
  (the dataclass field is `int = 0`), while `largest_trade_price` is `NULL`.
  Undocumented asymmetry.
- **`mid_price` fallback chain is understated.** The doc says
  "`(best_bid + best_ask) / 2`; falls back to last trade price if book is
  empty". The code falls back to the *single available side* first — a
  one-sided book yields `mid_price = best_bid`, which is not a mid at all, and
  `pct_change` then mixes true mids with one-sided prices. Document the full
  chain: both sides → mid; one side → that side; neither → `last_price`; else
  `NULL`.
- **`order_events.ts` is recorder wall-clock** (`datetime.now`) while
  `trade_log.ts` is the **engine's** timestamp. The `order_events` row correctly
  says so, but nothing warns that the two tables therefore cannot be merged into
  a single ordered timeline, and that a `FILL` event can appear *before* its own
  trade. This is important for the "does API Gateway history match the live
  WebSocket events" workflow.
- **`session_state` values are never enumerated.** The doc says "e.g.
  `CONTINUOUS`, `CLOSED`" in one place and `OPENING_AUCTION` in an example. The
  authoritative set is `models/session.py::SessionState`: `PRE_OPEN`,
  `OPENING_AUCTION`, `CONTINUOUS`, `CLOSING_AUCTION`, `CLOSED`. Since the entire
  EOD-finality contract hinges on an exact string match against `CLOSED`, the
  full enum must be listed.
- **No `WITHOUT ROWID` / `rowid` stability note.** The pagination cursors depend
  on `rowid` being insertion-ordered and stable. That is a schema invariant
  (`VACUUM` can renumber rowids) and belongs in the docs next to the tables.

### Missing public functionality

- **`from_date` / `to_date` range mode** of `query_daily` and `query_index_daily`
  is not documented anywhere, despite being exposed on `/api/v1/history/daily`
  and `/api/v1/history/index-daily`. It is also the fix for P0-4.
- **`--log-target`, `--log-file`, `--log-failover-timeout`** are absent from the
  `pm-stats` startup-options table.
- **Pagination is CLI-absent.** The API section documents `after`/`next_cursor`
  well; the CLI section never says the CLI has no equivalent and truncates
  instead.
- **`--snapshot-interval` has no stated lower bound.** Values below 1 s silently
  collide on the second-precision `(ts, symbol)` primary key and are dropped by
  `INSERT OR IGNORE`. Either validate `>= 1` or document it.

### Missing operational content

The guide walks a reader from start to finish for the *happy path*, but a
production shipment needs:

- **Retention and growth.** `trade_log` and `order_events` are append-only and
  unbounded. No sizing guidance, no pruning procedure, no `VACUUM` advice.
- **Backup.** The current advice is "stop `pm-stats`, `cp` the file". With WAL
  (P0-6) a `cp` is *unsafe*; the correct online procedure is
  `sqlite3 stats.db "VACUUM INTO 'backup.db'"` or `.backup`. Both are safe with
  the recorder running.
- **Single-writer contract** (P1-11) and what happens if it is violated.
- **Restart semantics** — what a mid-day restart does to the current day's row.
  This is currently silent, and per P0-1 it is destructive.
- **Schema version / upgrade** procedure between EduMatcher releases.
- **A completeness check.** There is no documented way to answer "did I capture
  every trade?" — see GAP-6.

---

## GAP — Missing information in the data model

These are *omissions*, not errors. Each is safe to defer, but the decision
should be recorded.

**GAP-1 — No aggressor side or trade condition.** `trade_log` records
`buy_gateway_id` and `sell_gateway_id` but not which side lifted, nor whether the
print came from an auction uncross, a continuous match, or a cross. The guide's
"Trade Flow Analysis" and "detecting potential market manipulation" use cases
are not actually achievable without it — order-flow imbalance and trade
classification both require the aggressor flag. This is the most consequential
gap for the stated analyst workflows.

**GAP-2 — No corporate-action awareness in `daily_stats`.** `pm-index` handles
corporate actions and keeps a JSONL audit trail, but the instrument OHLC series
is unadjusted and carries no split/dividend marker. Any multi-day return
calculation across a corporate action is wrong — including the `return_pct`
example in the guide's Pandas section. At minimum: document that prices are
unadjusted; better: add an adjustment factor column or a `corporate_actions`
table.

**GAP-3 — No auction/continuous distinction on `open_price`/`close_price`.**
`open_price` is simply the first trade of the day, whether that came from the
opening uncross or the first continuous match. Real venues publish these
separately. Similarly there is no official closing price distinct from "last
trade", and `_on_eod` deliberately does not set `close_price`.

**GAP-4 — No provenance metadata.** Nothing in the DB records the `pm-stats`
version, the `--snapshot-interval` in force, the engine instance, or the host
timezone. A `stats.db` assembled across runs with different intervals is
indistinguishable from one with gaps — a chart consumer cannot tell. Add a
`recorder_runs` table (start ts, end ts, version, interval, db schema version).

**GAP-5 — No currency, tick size, lot size or price precision.** Not stored
anywhere in `stats.db`, so the file is not self-describing for a downstream BI
consumer — which is precisely the use case §"Exporting to BI Tools" promotes.

**GAP-6 — No completeness/gap detection.** No engine sequence numbers, no
per-session expected-vs-received reconciliation, no `gaps` table. Combined with
lossy PUB/SUB (P1-10), there is no evidence that `stats.db` is complete. For a
system positioned as authoritative statistics this is the gap I would most want
closed before the release *after* this one — and in the meantime, the
documentation should say plainly that `stats.db` is a best-effort recording, not
a guaranteed-complete audit source (`pm-audit-cli` presumably holds that role —
the See Also link should make the distinction explicit).

**GAP-7 — No quote/spread statistics.** `daily_stats` carries open/close
bid/ask but no time-weighted spread, no quoted depth, no time-at-touch. These
are standard EOD exchange statistics and the raw material is already flowing
through `_on_book`.

**GAP-8 — No turnover (notional).** `volume` is share count only. Turnover
(`Σ price × qty`) is already computed in `_pv_sum` and thrown away; persisting it
would also make VWAP exactly reconstructible without a float round-trip.

**GAP-9 — No participant counts per day.** "How many gateways traded this
symbol today" requires a full `trade_log` scan; a `distinct_participants` column
would be free at flush time.

---

## Suggested ordering

**Before ship (P0):** 1 (restart clobber), 2 (timestamp bounds), 5 (local vs UTC
date), 6 (WAL + busy_timeout), 7 (silent recorder death). These five all produce
*wrong numbers* or *lost records* with no visible signal.

**Before ship (documentation):** P0-3 and P0-4 plus the "factually wrong"
table — a user following the guide today will compute wrong answers and believe
them. Correcting the docs is cheap and independent of the code fixes.

**Next release:** the P1 list, then GAP-1, GAP-2 and GAP-6.

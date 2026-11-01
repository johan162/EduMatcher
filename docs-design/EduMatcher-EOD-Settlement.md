# EduMatcher — End-of-Day Settlement and Housekeeping (`pm-eod`): Design and Workplan


When a trading day closes, one command — `pm-eod run` — turns the day's
clearing data into **settlement**: every trader's net amount against the
exchange, a running cash balance, one statement per trader and one exchange
summary, all written as files under `<data>/settlement/<date>/`. The same run does
the day's housekeeping: it confirms the audit archive, compresses stale
logs and takes compressed backups of the SQLite stores. `pm-scheduler`
starts it after the `CLOSED` transition (`--on-close`), and
`pm-eod run --pending` catches up on any day that was missed.

One work package (WP) at a time; each WP ends with a holistic test run
(`make _check` + the full test suite + `make test-e2e`), a review for new
insights, and a proposed commit message. The maintainer commits.

Started: 2026-11-01

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit)

| # | WP | Content | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|
| 1 | E1 | Close-time snapshot: `pm-clearing` records every position, marked, when the session closes | — | 1 d | ☑ | 2026-11-01 |
| 2 | E2 | Settlement engine and ledger: day P&L → integer cash, zero-sum, running balances (`eod.db`) | E1 | 1.5 d | ☑ | 2026-11-01 |
| 3 | E3 | Roster and reports: per-trader statements, exchange summary, leaderboard (CSV/JSON/Markdown) | E2 | 1.5 d | ☑ | 2026-11-01 |
| 4 | E4 | Housekeeping steps: audit-archive check, log compression, compressed DB backups, retention | — | 1 d | ☑ | 2026-11-01 |
| 5 | E5 | `pm-eod` CLI: `run` (gates, steps, idempotency), `--pending`, `status`, `balances`, health | E2–E4 | 1.5 d | ☑ | 2026-11-01 |
| 6 | E6 | Trigger: `pm-scheduler --on-close`, start-up catch-up, emo profile | E5 | 0.5 d | ☐ | |
| 7 | E7 | Docs: operator guide chapter, file formats, `pm-help`, completions, deployments | E1–E6 | 0.5 d | ☐ | |

Total ≈ 7.5 d. E1 first because settlement is only as good as the closing
marks it reads. E4 is independent of the money path and can run in parallel
with E2/E3 if wanted.

## Per-WP checklist

1. Re-read the WP below; check the named files/functions still exist.
2. Write the failing test first, then the change.
3. Holistic test: `make _check` (black, flake8, mypy, then pyright), the full
   `pytest` suite with `-n logical`, `make test-e2e`.
4. Review: anything learned goes into the insights log and, if it changes a
   later WP, into that WP.
5. Mark the WP ☑ here, propose a commit message, stop.

## Open decisions

Recommended answers in **bold**; the WPs below assume them until decided.
Q1–Q6 were decided on 2026-11-01.

| # | Question | Options | Affects | Decided |
|---|---|---|---|---|
| Q1 | Kind of money | **Simulated cash settlement** (fictional currency, real owes/receives instructions, balances carry over) · classroom score only · real money | E2, E3 | ✔ simulated |
| Q2 | Netting | **Central pool**: each trader pays/receives its net amount against the exchange · bilateral minimised transfers | E2, E3 | ✔ pool |
| Q3 | Delivery | **Files only** under `<data>/settlement/<date>/`; the instructor sends them · SMTP in `pm-eod` | E3 | ✔ files |
| Q4 | Fees | **None** · flat per trade · bps of notional | E2 | ✔ none |
| Q5 | Negative balance | **Informational** (statement + leaderboard) · warn below a floor · enforce in the engine | E3 | ✔ info |
| Q6 | Roster location | **`<data>/ref_data/roster.yaml`** · inside `engine_config.yaml` · flag only | E3 | ✔ ref_data |
| Q7 | What is settled | **The day's change in mark-to-market equity** (realized + unrealized, per symbol, between two close snapshots) · realized P&L only | E1, E2 | |
| Q8 | Currency unit | **Display currency, rounded to the minor unit (2 decimals)** with a largest-remainder fix-up so the day sums to exactly 0 · raw ticks | E2 | |
| Q9 | Where the ledger lives | **A new `<data>/eod.db`** (SQLite, same conventions as `clearing.db`) · inside `clearing.db` | E2 | |
| Q10 | Starting balance | **0 for everyone**; an optional `opening_balance` per roster entry · fixed stake | E2, E3 | |

---

## 1. Current state (2026-11-01)

- **Clearing store** (`src/edumatcher/clearing/store.py`, `clearing.db`):
  `trade_events` (raw, `--retention-days` pruned), `gateway_symbol_positions`
  (current snapshot per `(gateway_id, symbol)`: `net_qty`, `avg_cost`,
  cumulative `realized_pnl`, `unrealized_pnl`, `mark_price`,
  `tick_decimals`), `gateway_daily_summary` (one row per
  `(trade_date, gateway_id, symbol)` that **traded** that day:
  `net_amount`, `realized_pnl`, `end_unrealized_pnl`, …), `session_events`
  (`PHASE` rows for every session transition; one `EOD` sentinel) and the
  view `gateway_pnl_totals`, which normalises tick units to display currency
  per row before summing (finding CL-H2).
- **Units.** P&L and notional are integers in ticks (`avg_cost`/P&L are
  `REAL`); one tick is `10^-tick_decimals` of currency, per symbol. Cross
  symbol sums must go through the tick scale.
- **Trading date.** `clearing/ledger.py::trade_date` and
  `stats/trading_day.py` define it as the date in `locale.session_timezone`
  (default `Europe/Stockholm`). `pm-eod` reuses it; it never invents its own.
- **End of day.** `pm-clearing` marks to market and writes the `EOD` sentinel
  on `system.eod` — but the engine sends that **only when it shuts down**.
  The reliable day boundary of a long-running exchange is the
  `PHASE`→`CLOSED` row; `pm-clearing` already hangs its `trade_events`
  prune on it (`clearing/main.py`, after the `state == "CLOSED"` check).
- **Audit.** `pm-audit` closes the day and spawns `pm-audit-cli archive
  --pending` itself (`EduMatcher-Zstd-Audit.md`); nothing else needs to
  compress the audit trail.
- **Scheduler.** `pm-scheduler` drives `PRE_OPEN → … → CLOSED` and has no
  post-close hook. It runs from `--daily`, which waits through non-trading
  days.
- **Not present:** any cash balance, any notion of "owes", any roster of
  who runs which gateway, any mail code, any backup of the SQLite stores,
  any rotation of `data/logs/` (`LOG_FALLBACK_DIR`).

## 2. Problems to solve

1. **No settlement.** Clearing knows P&L per gateway, but nothing turns it
   into amounts to pay or receive, and nothing carries a balance from day to
   day.
2. **Daily summaries miss silent holders.** `gateway_daily_summary` has a
   row only for symbols a gateway *traded* that day. A gateway that sat on a
   position while the price moved has no row for that symbol, so a day's
   unrealized change cannot be read from it. (Settling on the summaries
   would silently lose that P&L.)
3. **The closing mark is only taken at engine shutdown.** Positions are
   marked on `system.eod`; a weeks-long run never does it, so the last
   mark would be stale.
4. **Gateways are not people.** Traders are known to the exchange only as
   gateway ids.
5. **Housekeeping is scattered and partly absent**: the audit archive and
   the clearing prune run by themselves, but the logs and the databases
   have no daily care, and nobody confirms the day's chores actually ran.

## 3. Design

### 3.1 What is settled (Q7) — close snapshots

At the `CLOSED` transition `pm-clearing` (E1) marks every open position to
the day's closing price and copies the result into a new table:

```sql
CREATE TABLE position_close_snapshot (
  trade_date    TEXT    NOT NULL,
  gateway_id    TEXT    NOT NULL,
  symbol        TEXT    NOT NULL,
  net_qty       INTEGER NOT NULL,
  realized_pnl  REAL    NOT NULL,   -- cumulative, ticks
  unrealized_pnl REAL   NOT NULL,   -- at mark_price, ticks
  mark_price    INTEGER,
  tick_decimals INTEGER NOT NULL,
  PRIMARY KEY (trade_date, gateway_id, symbol)
);
```

One row per position that exists at the close, whether or not it traded
that day (problem 2). A day's settlement per `(gateway, symbol)` is

```
day_pnl = (realized + unrealized)[D]  −  (realized + unrealized)[previous snapshot, else 0]
```

The previous snapshot is the latest earlier `trade_date` for that key — gaps
for weekends and holidays are just longer intervals. A position that
disappears (not possible while `gateway_symbol_positions` keeps flat
positions) counts as 0 equity afterwards.

*Why equity differences, not realized P&L:* equity is cash plus positions
at the mark, so for each symbol the sum over all gateways is zero by
construction (every trade has a buyer and a seller). Realized-only would
leave open positions unsettled and the exchange would never converge.

### 3.2 Units, rounding and the zero-sum check (Q8)

1. `day_pnl` per `(gateway, symbol)` is divided by `10^tick_decimals` →
   display currency (a `Decimal`, not a `float`).
2. Summed per gateway → exact `Decimal` → rounded to 2 decimals
   (**minor units**, an `int`) with *largest remainder*: the unrounded
   residues are ranked and the ±0.01 steps handed out so the rounded
   amounts sum to exactly the rounded total of all gateways.
3. The rounded total of all gateways should be 0. The float `avg_cost`
   makes it drift by far less than one minor unit per position; the run
   **fails the gate** if `|Σ| > 0.01 × number of position keys` (a real
   accounting error looks far bigger), otherwise the residual is booked to
   the `EXCHANGE` account as a `rounding` line so the ledger sums to exactly
   0 and the statements can say so.

### 3.3 Central pool (Q2) and the ledger (Q9)

Every trader's day amount is "paid by / received from the exchange": a
positive number is credited, a negative one is owed. `<data>/eod.db`
(E2):

```sql
eod_runs      (trade_date PK, status, started_at, finished_at, steps_json)
eod_settlement(trade_date, account, symbol_detail_json, amount_minor,
               PRIMARY KEY (trade_date, account))      -- account = gateway id or 'EXCHANGE'
eod_balance   VIEW: account, balance_minor = opening + Σ amount_minor up to a date
```

- `amount_minor` is the integer from §3.2. `Σ amount_minor` per
  `trade_date` is exactly 0 — an invariant the writer checks before commit
  and `pm-eod balances --check` re-checks across all days.
- **Idempotent.** Re-running a settled date is a no-op reporting the
  stored result; `--redo DATE` deletes that date and every later one in a
  transaction and recomputes, because balances are cumulative. It is the
  only way to correct history, and it refuses once `--keep-days` has pruned
  a snapshot it needs.
- No fees (Q4): no `EXCHANGE` amounts other than the rounding line. The
  ledger has the account column so fees can be added later without a schema
  change, but nothing in the code anticipates them.

### 3.4 Roster (Q6) and statements (Q3, Q5)

`<data>/ref_data/roster.yaml`:

```yaml
traders:
  - gateway: GWY_ALICE
    name: Alice Andersson
    email: alice@example.org       # printed on the statement; never used to send
    opening_balance: 0             # optional (Q10), display currency
```

- A gateway in the clearing data but not in the roster still gets a
  statement, keyed by gateway id, and the run logs one warning naming it. A
  roster entry with no activity gets a zero statement, so every enrolled
  trader receives one every trading day.
- The loader rejects duplicate gateways and malformed amounts with a line
  number, in the style of the other YAML loaders; there is no schema
  migration and no legacy format.

Per trading day, in `<data>/settlement/<date>/`:

```
statements/<gateway>.md|.json|.csv   per-trader: trades, positions at the close, day amount,
                                      new balance, "pay / receive" sentence
summary.md|.json                      exchange: volume, trade count, top winners/losers,
                                      reject counts, sum-zero proof, run times
instructions.csv                      one line per account: gateway, name, email, amount, balance
leaderboard.csv                       balance ranking (informational, Q5)
```

Files are written to a temp name and renamed, so a half-written day is
never visible. Statements are the deliverable; sending them is the
instructor's job (Q3), and `instructions.csv` is the mail-merge input.

### 3.5 The run: gates, steps, idempotency

`pm-eod run [--date D] [--force]` for one trading date, as a list of named
steps whose result is recorded in `eod_runs.steps_json`:

| Step | What | Failure |
|---|---|---|
| `gate` | `PHASE→CLOSED` row exists for D in `session_events`; a `position_close_snapshot` exists for D; `pm-clearing-cli reconcile` clean for D | stop, nothing written (`--force` skips the `CLOSED` check only) |
| `settle` | §3.1–3.3 | stop; ledger untouched (single transaction) |
| `report` | §3.4 | settlement stays, status `report-failed`, retried by `--pending` |
| `audit` | `pm-audit-cli archive --pending`; verify `audit-D.log.zst` exists and no parts of D remain | warning, run continues |
| `logs` | gzip fallback logs older than 1 day; delete after `--log-keep-days` | warning |
| `backup` | `sqlite3 .backup` of `clearing.db`, `stats.db`, `eod.db` into `<data>/backup/D/`, zstd-compressed; delete after `--backup-keep-days` | warning |
| `done` | summary line in the log, health gauge, `eod_runs.status = ok` | — |

Only the money path (`gate`, `settle`) can fail the day; housekeeping
trouble is reported and retried but never withholds statements. The same
step list drives `pm-eod run --only STEP` for manual re-runs.

### 3.6 Trigger and catch-up

`pm-scheduler --on-close "pm-eod run --pending"` — after the engine
confirms `CLOSED`, the scheduler spawns the command detached (one child at a
time, output captured to the scheduler log, exactly as `pm-audit` spawns its
archiver) and goes on. `--pending` runs every trading date that has a
`CLOSED` event but no `ok` run, oldest first, so a scheduler that was down,
a day that closed late, or a failed `report` step all heal on the next
trigger. `pm-eod run --pending` also runs from the scheduler's start-up.

Without the scheduler (`sessions_enabled: false`) there is no `CLOSED`
event; `pm-eod run --date D --force` or a cron entry is the manual route,
documented in E7.

## 4. Work packages

### E1 — Close-time snapshot in `pm-clearing`

- **Verified first (2026-11-01).** Clearing does not mark at `CLOSED`, but
  it does not need to: `Ledger._remark_symbol` re-marks every open position
  in a symbol to the last trade price on each trade, so the marks at the
  close already are the closing marks. E1 only has to flush the buffer and
  copy; a symbol with no trade yet keeps its previous mark.
- Add `position_close_snapshot` to the schema (`SCHEMA_SQL`) and a
  `write_close_snapshot(conn, trade_date)` helper that re-marks every row and
  copies it; call it on the `CLOSED` transition in the same transaction as
  the `PHASE` row. Calling it twice for a date replaces the date's rows.
- `pm-clearing-cli snapshots [--date D] [--gateway G]` (read-only, same
  formats as the other verbs) so the data is inspectable; add to
  `sqlite_schema_docs.py` and the retention rule: snapshots are small and
  **not pruned** with `trade_events`.
- Tests: snapshot includes a gateway that did not trade that day; two
  closes in one day replace, not duplicate; marks use the tick scale;
  schema docs test.
- **Verify:** unit tests + the clearing e2e; manual: run a sim day, `pm-clearing-cli snapshots`.

### E2 — Settlement engine and ledger (`src/edumatcher/eod/settle.py`, `ledger.py`)

- `settle.py`: pure functions, no I/O — `day_pnl(snapshots_D, snapshots_prev)
  → dict[(gateway,symbol), Decimal]`, `to_minor_units(per_gateway)` with the
  largest-remainder rounding of §3.2, `check_zero_sum(...)`. All in
  `Decimal`; the only `float`→`Decimal` conversion is at the snapshot read
  (via `Decimal(repr(x))`).
- `ledger.py`: `eod.db` schema (§3.3), `record_day`, `balance_as_of`,
  `redo_from`, WAL mode and the `open_*_connection` helpers in the style of
  `clearing/store.py`. Path constant `EOD_DB_FILE` in `config.py`.
- Property tests (hypothesis, if already a dev dependency; else
  parametrised): for any generated set of buy/sell trades with random tick
  decimals, `Σ amount_minor == 0` after the fix-up; a symbol that moves
  while a gateway is silent is settled; weekends produce one long
  interval, not two days.
- **Verify:** tests; golden test with a hand-computed three-trader day.

### E3 — Roster and reports (`eod/roster.py`, `eod/report.py`)

- Roster loader per §3.4 with line-numbered errors; `opening_balance`
  feeds `balance_as_of`.
- Report writers for statement (md/json/csv), summary, `instructions.csv`,
  `leaderboard.csv`; temp-file-and-rename; all text through one template
  module so wording is in one place ("You owe the exchange 12.34" /
  "The exchange owes you 12.34").
- Summary pulls volume and counts from `pm-stats` (`stats.db` read-only), so
  the figures match the other tools by construction; if `stats.db` is
  missing the summary says so instead of failing.
- Tests: unlisted gateway warning; zero statement for an idle trader;
  golden files for the Markdown; rename atomicity (kill between write and
  rename leaves no partial file visible).
- **Verify:** tests; open the statements for a sim day and read them as a
  trader would.

### E4 — Housekeeping steps (`eod/housekeeping.py`)

- `check_audit(date)`: run `pm-audit-cli archive --pending` and assert the
  day's `.zst` exists and no loose parts remain.
- `compress_logs(keep_days)`: gzip `LOG_FALLBACK_DIR/*.log` files whose
  mtime is before today (never the file a process still holds open — skip
  anything modified in the last hour), delete `.gz` older than the
  retention. Check first whether `pm-log-srv` already rotates `log.db` and
  what its retention is; if it does, `eod` only reports it.
- `backup_databases(date, keep_days)`: Python's `sqlite3.Connection.backup`
  (consistent while the writer runs), then stdlib `compression.zstd` to
  `<data>/backup/<date>/<name>.db.zst`; verify by decompressing and running
  `PRAGMA integrity_check` on a temp copy; prune by date.
- Each step returns a small result object (`ok|warn`, bytes before/after,
  message) that `run` records.
- Tests: crash-safety (partial backup never replaces a good one), skip of
  recently modified logs, retention deletes only what it should.
- **Verify:** tests; run against a copy of a real `data/`.

### E5 — `pm-eod` CLI and orchestration (`eod/main.py`)

- Entry point `pm-eod = "edumatcher.eod.main:main"` in `pyproject.toml`.
- Verbs: `run` (`--date`, `--pending`, `--only STEP`, `--force`, `--redo`,
  `--dry-run`), `status` (last runs and their steps), `balances`
  (`--date`, `--gateway`, `--check`), all with `--format table|json|csv`
  like `pm-clearing-cli`.
- The gate and step table of §3.5; a lock file so two runs cannot overlap
  (the scheduler hook plus a manual run); exit codes: 0 ok, 1 gate/settle
  failed, 2 housekeeping warnings only.
- Health: a `HealthReporter` gauge `eod_last_ok_date` and `eod_last_status`
  for `pm-monitor`; no long-lived process, so the gauge is written to the
  run row and `pm-eod status -q` is the health check emo can call.
- Tests: step ordering and failure semantics (housekeeping failure keeps the
  settlement), `--pending` order and gap handling, `--redo` cascades, lock.
- **Verify:** tests; e2e: simulated two-day run with `--speed`, `--pending`
  catches up the first day.

### E6 — Trigger and profiles

- `pm-scheduler --on-close CMD`: after the confirmed `CLOSED` state, spawn
  the command once, detached, with output to the scheduler log; at most one
  child at a time; a failed child logs a warning and never delays the next
  day's schedule. Also runs it once at start-up after state alignment.
- emo: the `pm-eod` entry in the profiles that run the scheduler (command
  `pm-scheduler --daily --on-close "pm-eod run --pending"`); `emo clean`
  must **not** delete `<data>/settlement/` or `eod.db` without `--all`, since they
  are the exchange's money history — check what `clean` removes today and
  add the exclusion to its listing.
- Tests: hook spawn/reap with a stub command, non-trading day does nothing,
  failing child.
- **Verify:** tests; compressed-time day via `--speed 600` ends with a
  settled date.

### E7 — Operations and docs

- Operator guide chapter ("Closing the day"): the run, its files, how to
  send the statements from `instructions.csv`, how to correct a day
  (`--redo`), the manual/cron route without the scheduler.
- File-format reference for `roster.yaml`, `eod.db`, `position_close_snapshot`
  and the report files; `pm-help`/`pm-man` pages, completions
  (`tools/gen_completion.py`), the deployment READMEs and the `pm-eod`
  line in the README tool list; entry in `docs-design/README.md`.
- Doc-check script (`scripts/checkdocs.py`) clean.
- **Verify:** `make docs` builds without warnings.

## Insights log

*(Append per WP: measurements, surprises, changes to later WPs.)*

**Design (2026-11-01).**
- Q1–Q6 decided with Johan: simulated cash, central pool, files only, no
  fees, balances informational, roster in `ref_data/roster.yaml`. Q7–Q10
  are the author's recommendations, not yet confirmed.
- Two traps found while reading the code, both folded into the design:
  `system.eod` fires only at engine shutdown (so the day boundary is the
  `CLOSED` `PHASE` row), and `gateway_daily_summary` has no row for a symbol
  a gateway merely held (so settlement reads close snapshots, E1).
- The audit archive and the clearing prune already run at day close; `pm-eod`
  only verifies them, so there is one owner per chore.

**E1 (2026-11-01).**
- No re-marking needed: positions are already marked to the last trade price
  on every trade (`Ledger._remark_symbol`), so the `CLOSED` handler flushes
  the buffer (closing-auction trades may still be in it) and copies
  `gateway_symbol_positions` with one `INSERT … SELECT`.
- The snapshot is written on **every** `CLOSED` broadcast, replacing that
  date's rows. A mid-day engine restart that re-announces `CLOSED` therefore
  writes a provisional snapshot that the real close overwrites. E5's gate
  must check the *time* of the last `CLOSED` row against the snapshot, not
  just that one exists, if this ever matters in practice.
- `pm-clearing-cli snapshots` added (with `--date/--from/--to/--gateway/
  --symbol`, tick-normalised like the other verbs); the schema reference and
  the shell completions are generated from the schema/CLI and were
  regenerated.
- `make test-e2e` ran 1 passed / 20 skipped here (the fixed-port exchange
  tests skip), so the end-to-end path of the new snapshot is covered by the
  unit tests only; a real sim day is the manual check.

**E2 (2026-11-01).**
- New package `src/edumatcher/eod/`: `settle.py` (pure arithmetic plus
  `settle_date`, which only reads `position_close_snapshot`) and `ledger.py`
  (`eod.db`, `EOD_DB_FILE` in `config.py`, listed in the generated SQLite
  reference).
- Changes against §3.1/§3.3, all simplifications: a position present in the
  previous snapshot but absent today is **ignored** (not counted as 0 equity,
  which would book a loss from nothing and break the zero sum); `eod_runs`
  is **not** created yet — E5 owns it; balances are a function over the
  amounts (`balances()`), not the `eod_balance` view; `redo_from` has no
  "snapshot was pruned" refusal because snapshots are never pruned.
- The zero-sum gate is `|exact total| ≤ 0.01 × positions`; anything beyond
  is a `SettlementError`, anything within is booked to `EXCHANGE`
  (`rounding_minor`). `record_day` independently refuses a day that does not
  sum to exactly 0 and a date that is already settled or older than the
  latest one.
- `hypothesis` is not a dev dependency, so the property test is 25 seeded
  random zero-sum days (2–40 accounts, 0–6 tick decimals): sum exactly 0 and
  every amount within 1 minor unit of exact.
- Any gateway with a snapshot row appears in the result, with 0 if its
  equity did not change, so E3 can give every active trader a statement.

**E3 (2026-11-01).**
- Three modules in `eod/`: `roster.py` (loader), `report.py` (dataclasses,
  all wording, renderers, atomic writer — pure, no DB), `assemble.py`
  (`build_day`: `eod.db` + `clearing.db` + optional `stats.db` → `DayReport`;
  writes nothing). E5 calls `build_day` then `write_day`.
- Atomicity is per **day directory**, not per file: everything is written to
  `.<date>.partial/` and renamed into place (an existing day is moved to
  `.<date>.old/` first), so a failed rewrite leaves the previous day intact.
- Deviations from §3.4: the exchange summary has **no reject counts**
  (`stats.db` `daily_stats` has volume, trade count and close only; reject
  counts would need the order-event tables — left out until someone asks);
  the per-statement CSV is one row per symbol (day P&L, quantity, mark), the
  trade list lives in the `.md`/`.json`.
- The wording is fixed in `report.py`: "The exchange owes you X." / "You owe
  the exchange X." / "Nothing to pay or receive today."; no currency name
  (fictional currency). Trade times are UTC and the column says so.
- A trader with no activity gets a zero statement and keeps their balance;
  roster `opening_balance` is added once in `balances()`. Roster gateway ids
  are upper-cased, as `pm-clearing-cli` does.
- A statement's trade list comes from `trade_events`, which is pruned after
  `--retention-days`; settling an old date by `--redo` after the prune shows
  no trades but still the correct amounts (they come from the snapshots).

**E4 (2026-11-01).**
- `eod/housekeeping.py`: `archive_audit`, `compress_logs`, `backup_databases`,
  each returning `StepResult(step, ok|warn, message)`. Foreseeable failures
  (busy lock, full disk, unreadable database) are `warn` results, not
  exceptions, so one chore never stops the others. E5 only has to call them.
- **`audit` step archives days before today only.** `archive_day` refuses the
  current day, so right after `CLOSED` the day that just closed cannot be
  archived; `pm-audit` does it after midnight. The step is therefore a
  safety net for earlier days that were missed, and its message says
  "nothing pending" in the normal case. Audit `--keep-days` retention stays
  with `pm-audit`.
- **`log.db` is not touched**: `pm-log-srv` already prunes it
  (`retention_days`). `compress_logs` handles only `data/logs/*.log`, the
  client failover files.
- **Failover logs are copy-truncated, not deleted.** `logging.FileHandler`
  keeps the file open for the life of the process, so deleting it would
  silently lose every later line. The step compresses the bytes it saw to
  `<name>.<YYYYMMDD of mtime>.log.zst` (with a counter if that exists),
  verifies, and only then truncates the original in place if its size and
  mtime are unchanged; otherwise it removes the archive and warns. Files
  modified in the last hour are skipped. The window between the final stat
  and `truncate` is not zero but is microseconds on a file that has been idle
  for an hour.
- **Backups** use `sqlite3.Connection.backup` (consistent under WAL), an
  `integrity_check` of the copy, zstd with a decompress-and-compare, fsync,
  then rename over the earlier backup of the same date. A failed backup keeps
  the previous one. Missing databases (e.g. no `stats.db` yet) are listed in
  the message, not warned. Which databases to back up is the caller's list
  (E5: `clearing.db`, `stats.db`, `eod.db`).
- Not done: `VACUUM` (decided against daily in the proposal).

**E5 (2026-11-01).**
- **Output directory renamed to `<data>/settlement/<date>/`** (`SETTLEMENT_DIR`
  in `config.py`). `<data>/eod/<date>/` is already the **engine's**
  (`Engine._archive_eod` writes the GTC orders/combos and book stats there,
  and `tools/sim_forensics` reads them), and `write_day` replaces a whole date
  directory — it would have destroyed them. A test asserts the engine's files
  survive a run. The plan text above was changed to match.
- Modules: `runner.py` (`Paths`, `Options`, `run_day`, `pending_dates`,
  `run_lock`, `exit_code`) and `main.py` (argparse; `run`, `status`,
  `balances`). `eod_runs` is created in `ledger.py` (deferred from E2);
  `redo_from` also forgets the runs of the dropped dates, so a later
  `--pending` re-settles them in order.
- **Gate rule is "the latest `PHASE` row of the date is `CLOSED`"**, not
  "a `CLOSED` row exists". A mid-day engine restart re-announces `CLOSED` and
  trading goes on, so the E1 snapshot of that moment is provisional; this
  rule refuses to settle it. `--force` skips only this check (for runs
  without the scheduler); a missing snapshot or a reconcile discrepancy still
  fails.
- **`--pending` only considers dates that have a close snapshot.** Before E1
  there are `CLOSED` rows without snapshots; counting them would fail on the
  first day and, because later days must wait for earlier ones, block
  everything forever. It stops at the first failing date.
- `--only STEP` (`report|audit|logs|backup`) re-runs one step of an already
  settled date and records nothing, so it cannot downgrade an `ok` run.
  `--dry-run` runs the gate and prints the amounts; it creates no file.
- Exit codes: 0 clean, 1 gate/settle/report failed, 2 housekeeping warnings
  only. `run_lock` is a `flock` on `<data>/.pm-eod.lock`.
- **No `HealthReporter` gauge** (the plan mentioned one): `pm-eod` is not a
  long-lived process, so `pm-eod status -q` (exit 0 when nothing is pending
  and the last run is `ok`) is the health check emo can call in E6.
- The CLI has its own 15-line table/JSON/CSV renderer: `pm-clearing-cli`'s
  are private (pyright rejects importing them) and the audit ones print
  "No matching events found.".
- `pm-eod` is registered in `pyproject.toml`; it is not on the PATH until
  `poetry install` is re-run. Completions and the SQLite reference were
  regenerated.

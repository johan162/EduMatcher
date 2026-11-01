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
| 6 | E6 | Trigger: `pm-scheduler --on-close`, start-up catch-up, emo profile | E5 | 0.5 d | ☑ | 2026-11-01 |
| 7 | E7 | Docs: operator guide chapter, file formats, `pm-help`, completions, deployments | E1–E6 | 0.5 d | ☑ | 2026-11-01 |
| 8 | R1 | Review: baseline = last settled date, settle in order, atomic `--redo` | E7 | — | ☑ | 2026-11-01 |
| 9 | R2 | Review: a day's close snapshot is final once the day has closed | R1 | — | ☑ | 2026-11-01 |
| 10 | R3 | Review: read one day of trades and the snapshot dates by index | R1 | — | ☑ | 2026-11-01 |
| 11 | R4 | Review: docs (worked example re-run), `--only`+`--dry-run`, roster `.inf` | R3 | — | ☑ | 2026-11-01 |
| 12 | R5 | Review: one backup per catch-up; statements without long-dead symbols | R4 | — | ☑ | 2026-11-01 |

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
Q1–Q6 were decided on 2026-11-01; Q7–Q10 were built as recommended (E1–E2).

| # | Question | Options | Affects | Decided |
|---|---|---|---|---|
| Q1 | Kind of money | **Simulated cash settlement** (fictional currency, real owes/receives instructions, balances carry over) · classroom score only · real money | E2, E3 | ✔ simulated |
| Q2 | Netting | **Central pool**: each trader pays/receives its net amount against the exchange · bilateral minimised transfers | E2, E3 | ✔ pool |
| Q3 | Delivery | **Files only** under `<data>/settlement/<date>/`; the instructor sends them · SMTP in `pm-eod` | E3 | ✔ files |
| Q4 | Fees | **None** · flat per trade · bps of notional | E2 | ✔ none |
| Q5 | Negative balance | **Informational** (statement + leaderboard) · warn below a floor · enforce in the engine | E3 | ✔ info |
| Q6 | Roster location | **`<data>/ref_data/roster.yaml`** · inside `engine_config.yaml` · flag only | E3 | ✔ ref_data |
| Q7 | What is settled | **The day's change in mark-to-market equity** (realized + unrealized, per symbol, between two close snapshots) · realized P&L only | E1, E2 | ✔ as built |
| Q8 | Currency unit | **Display currency, rounded to the minor unit (2 decimals)** with a largest-remainder fix-up so the day sums to exactly 0 · raw ticks | E2 | ✔ as built |
| Q9 | Where the ledger lives | **A new `<data>/eod.db`** (SQLite, same conventions as `clearing.db`) · inside `clearing.db` | E2 | ✔ as built |
| Q10 | Starting balance | **0 for everyone**; an optional `opening_balance` per roster entry · fixed stake | E2, E3 | ✔ as built |

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

At the `CLOSED` transition `pm-clearing` (E1) copies every position into a
new table. No re-marking is needed: positions are marked to the last trade
price on every trade (E1). Once the day's latest `PHASE` is `CLOSED` the
snapshot is final and nothing replaces it (R2):

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

The previous snapshot is that of the latest earlier **settled** `trade_date`
(review fix, see the insights log) — gaps for weekends, holidays and unsettled
days are just longer intervals. A position that
disappears (not possible while `gateway_symbol_positions` keeps flat
positions) is ignored (E2): counting it as 0 equity would book a loss from
nothing and break the zero sum.

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
   makes it drift by far less than one minor unit per position; the
   `settle` step **fails** if `|Σ| > 0.01 × number of position keys` (a real
   accounting error looks far bigger), otherwise the residual is booked to
   the `EXCHANGE` account as a `rounding` line so the ledger sums to exactly
   0 and the statements can say so.

### 3.3 Central pool (Q2) and the ledger (Q9)

Every trader's day amount is "paid by / received from the exchange": a
positive number is credited, a negative one is owed. `<data>/eod.db`
(E2):

```sql
eod_runs      (trade_date PK, status, started_at, finished_at, steps_json)
eod_settlement(trade_date, account, amount_minor, detail_json,
               PRIMARY KEY (trade_date, account))      -- account = gateway id or 'EXCHANGE'
```

Balances are not stored and there is no view: `ledger.balances()` sums
`amount_minor` up to a date and adds the roster's opening balances (E2).

- `amount_minor` is the integer from §3.2. `Σ amount_minor` per
  `trade_date` is exactly 0 — an invariant the writer checks before commit
  and `pm-eod balances --check` re-checks across all days.
- **Idempotent.** Re-running a settled date is a no-op reporting the
  stored result; `--redo DATE` recomputes it, then deletes that date and
  every later one and inserts the new day in one transaction (R1), because
  balances are cumulative. It is the only way to correct history. Snapshots
  are never pruned, so there is no "snapshot gone" refusal (E2).
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
summary.md|.json                      exchange: volume, trade count, close, top winners/losers,
                                      sum-zero proof, warnings (no reject counts, E3)
instructions.csv                      one line per account: gateway, name, email, amount, balance
leaderboard.csv                       balance ranking (informational, Q5)
```

The day is written to a hidden work directory that is renamed into place
(E3), so a half-written day is never visible. Statements are the deliverable; sending them is the
instructor's job (Q3), and `instructions.csv` is the mail-merge input.

### 3.5 The run: gates, steps, idempotency

`pm-eod run [--date D] [--force]` for one trading date, as a list of named
steps whose result is recorded in `eod_runs.steps_json`:

| Step | What | Failure |
|---|---|---|
| `gate` | the **latest** `PHASE` row of D in `session_events` is `CLOSED` (E5); a `position_close_snapshot` exists for D; `pm-clearing-cli reconcile` clean for D | stop, nothing written (`--force` skips the `CLOSED` check only) |
| `settle` | §3.1–3.3; refused while an earlier closed date is unsettled (R1) | stop; ledger untouched (single transaction) |
| `report` | §3.4 | settlement stays, status `report-failed`, retried by `--pending` |
| `audit` | archive days *before today* that `pm-audit` missed; today is `pm-audit`'s after midnight (E4) | warning, run continues |
| `logs` | zstd-compress fallback logs idle for an hour, then truncate them in place (they are held open); delete archives after `--log-keep-days` (E4) | warning |
| `backup` | `sqlite3 .backup` of `clearing.db`, `stats.db`, `eod.db` into `<data>/backup/D/`, zstd-compressed; delete after `--backup-keep-days` | warning |
| `done` | `eod_runs` row (`ok`, `report-failed` or `failed`); no health gauge — `pm-eod status -q` is the health check (E5) | — |

Only the money path (`gate`, `settle`) can fail the day; housekeeping
trouble is reported and retried but never withholds statements. The same
step list drives `pm-eod run --only STEP` for manual re-runs.

### 3.6 Trigger and catch-up

`pm-scheduler --on-close "pm-eod run --pending"` — after the engine
confirms `CLOSED`, the scheduler spawns the command detached (one child at a
time, output captured to the scheduler log, exactly as `pm-audit` spawns its
archiver) and goes on, after `--on-close-delay` (30 s, E6). `--pending` runs
every trading date whose latest `PHASE` is `CLOSED`, that has a close snapshot
and no `ok` run, oldest first, so a scheduler that was down,
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
  long-lived process, so `pm-eod status -q` is the health check (exit 0 when
  no closed date is waiting; corrected in E7, see below).
- The CLI has its own 15-line table/JSON/CSV renderer: `pm-clearing-cli`'s
  are private (pyright rejects importing them) and the audit ones print
  "No matching events found.".
- `pm-eod` is registered in `pyproject.toml`; it is not on the PATH until
  `poetry install` is re-run. Completions and the SQLite reference were
  regenerated.

**E6 (2026-11-01).**
- `pm-scheduler --on-close COMMAND [--on-close-delay SEC=30]`. A `_CloseHook`
  is called from `_run_transitions` right after the CLOSED step is
  dispatched (threaded through `_run_scheduled` and `_run_forever` as
  `on_closed`), and once at start-up before the first schedule run. It sets
  a daemon `Timer` for the delay, then starts the command with `Popen`
  (inheriting stdout/stderr, so its output lands in the scheduler's log) and
  a reaper thread that logs the exit code. Nothing in the transition loop
  waits for it.
- **Why a delay:** the scheduler's confirmation and `pm-clearing`'s close
  snapshot both come from the same `session.state` broadcast, so a command
  started immediately can find the snapshot not yet written and fail its gate.
- One child at a time: a trigger while one runs is skipped with a warning.
  That is safe because `pm-eod run --pending` takes every missed date; the
  next trigger (next close, or a restart) picks up what was skipped.
- **Shutdown:** a single-shot run waits for the timer and the command
  (otherwise the daemon timer would die with the process before it fired); a
  `--daily` run being stopped only cancels pending timers and does not hold
  the shutdown. `--on-close` with `--now` is ignored with a warning.
- **`pending_dates` now uses the same rule as the gate** (latest `PHASE` row
  of the date is `CLOSED`). Otherwise the start-up trigger, run mid-day, would
  list today (the engine's boot-time `CLOSED` left a snapshot) and report a
  gate failure on every start.
- emo: `DEFAULT_PROCESSES` and `MINI_PROCESSES` start the scheduler with
  `--on-close "pm-eod run --pending"` (the other profiles have no
  scheduler). `eod.db`, `settlement/` and `backup/` are in `NON_STATE_PATHS`:
  removed only by `emo clear --all`, never by `--state`, since the balances
  must survive a reset of the working state. A caveat: after `--state`
  (clearing.db gone, eod.db kept) a settled date cannot be settled again, so
  re-running the same calendar date after a reset needs `pm-eod run --redo`.
- Not run end-to-end here (needs a live engine); the hook is covered with real
  subprocesses and `_run_transitions`. A compressed-time `--speed 600` day is
  the manual check.

**E7 (2026-11-01).**
- Documentation, written for an absolute beginner with every financial term
  defined before use and every number taken from a real run of `pm-eod` on the
  Alice/Bob/Carol example (not invented):
  - `operator-guide/part-4-run-a-market/100-closing-the-day.md` — the chapter:
    big picture, the ideas from scratch (share, trade, long/short, average cost,
    closing price, marking to market, unrealized/realized P&L, equity,
    settlement, central pool, netting, zero-sum, balance, minor units and
    rounding, trading date), a 3-day worked example, setup (roster, hook, no
    scheduler), a normal day, every output file, the three housekeeping steps
    with a restore procedure, corrections (`--redo`, `--only`, `--dry-run`),
    a troubleshooting table covering every message, FAQ and a first-day checklist.
  - `participant-guide/part-5-positions-and-results/020-your-end-of-day-statement.md`
    — the trader's page: the statement line by line, with a hand-checkable example.
  - Reference manual: `pm-eod` section (options, `roster.yaml`, files, ledger
    tables, settlement rules), scheduler `--on-close`, the command table, and
    glossary entries for the new terms.
  - Existing pages touched: positions page (`position_close_snapshot`,
    `snapshots` verb, "settles instantly" wording), persistence (new files, and
    a note that `eod/` is the engine's), sessions (`--on-close`), installation
    (data directory table), the book index, the README.
  - `pm-help`/`pm-man` registry: `pm-eod`, `pm-scheduler --on-close`,
    `pm-clearing-cli snapshots`.
- **Found while documenting, and fixed:**
  - With `sessions_enabled: false` no `CLOSED` is ever announced, so no close
    snapshot existed and `pm-eod` could never settle. `pm-clearing` now also
    takes the snapshot on `system.eod` (the engine's graceful shutdown) **if
    the date has none yet**, so a real `CLOSED` snapshot is never overwritten.
    This is what makes the documented `--force` / cron route work.
  - Prices printed as `10.2` instead of `10.20`; they now keep the symbol's
    decimals.
  - A mistyped `--date` was recorded as a failed run and kept `status -q`
    unhealthy forever (it judged the newest row). Health is now "no closed
    date is waiting" — a failed run on a real closed day still counts as
    waiting.
  - The `mini` emo profile has no `pm-clearing`; the E6 change had added the
    hook to its scheduler too, where `pm-eod` would fail its gate at every
    close. The hook is now only in the `default` profile.
- Rehearsal caveat (documented): `pm-scheduler --speed` compresses the
  timetable but trading dates come from the real clock, so several fast days
  share one date and one settlement.

**Simulation default (2026-11-01).**
- `ai-swarm`, `ai-sim` and `mm-demo` are built from `DEFAULT_PROCESSES`, so
  they already ran `pm-eod run --pending` after every close; a test now pins
  that. `ai-sim` (the weeks-long profile) has its own scheduler command:
  `--on-close "pm-eod run --pending --backup-keep-days 2 --backup-skip stats.db"`.
- New `pm-eod run --backup-skip NAME` (repeatable; `clearing.db`, `stats.db`
  or `eod.db`). The `backup` step's message ends with `skipped by request:
  <names>` so a missing backup is never silent.
- Why: `stats.db` peaks at about 3 GB in the simulation (the sim docs' own
  table) and is mostly order events that are discarded after 12 hours; its
  uncompressed working copy alone would have added ~3 GB to the disk needed at
  every close. The compressed size of the retained backups is **not measured**;
  the simulation docs say so and ask the operator to check `du -sh data/backup`
  after a week.


**Review fixes R1 (2026-11-01).** A holistic review after E7 found three ledger
bugs, each reproduced before fixing; none was caught by the zero-sum check,
because each loses or deletes a zero-sum set of amounts.
- **Baseline = last settled date, not last snapshot.** `settle_date` measured
  from the latest earlier *snapshot*. Any snapshot date that was never settled
  (a skipped `--force` day, a failed gate, a mid-day restart whose day never
  closed again) had its equity change silently dropped: three no-scheduler
  days with only the last settled gave A 5.00 instead of 35.00. `settle_date`
  now takes `previous` (`ledger.last_settled_before`); a missing snapshot for
  it means zero, which keeps the `emo clear --state` case right.
- **Dates settle in order.** `run --date D` while an earlier closed day was
  pending settled D, after which `record_day` refused the earlier day forever
  and `--pending` stopped on it at every close. `_settle` now refuses D while
  an earlier date is pending *and* unsettled (a `report-failed` day does not
  block). Without a scheduler there is no `CLOSED`, so nothing blocks and a
  skipped day folds into the next interval.
- **`--redo` is one transaction.** `redo_from` committed its deletes before the
  recomputation, so a failing recompute left the history gone. `redo_from` is
  replaced by `record_day(..., redo=True)`, which computes first and deletes +
  inserts in one transaction.
- Still open from the review (separate WPs): a post-close engine restart can
  rewrite a settled date's snapshot (M1); the no-scheduler route keeps only
  the first shutdown snapshot of a date (M2); per-gateway full scans of
  `trade_events` in `assemble._trades` and loading every snapshot row in
  `pending_dates` (P1, P2); the remaining doc fixes.

**Review fixes R2 (2026-11-01).** When `pm-clearing` writes or keeps the close
snapshot, now one rule for both handlers: `store.close_snapshot_is_final` —
the date's latest `PHASE` row is `CLOSED` and a snapshot exists. A final
snapshot is never replaced; any other is.
- **M1, post-close restart.** The graceful shutdown re-marks positions
  (bid/ask mid where the book has no last price) and the next boot announces
  `CLOSED` again, which rewrote the date's snapshot after `pm-eod` may have
  settled it; the next day was then measured from different numbers. The
  `CLOSED` handler judges finality *before* recording its own `PHASE` row, so a
  `CLOSED` that follows the day's `CLOSED` keeps the snapshot. A `CLOSED` after
  trading resumed (morning boot, mid-day restart) still replaces it.
- **M2, no scheduler.** The shutdown wrote a snapshot only if the date had
  none, so a second graceful stop the same day was ignored and the afternoon
  went into the next settled day. With no `PHASE` rows nothing is final, so the
  last shutdown of the day wins. With sessions, a shutdown after the real close
  keeps it (as before); a mid-day shutdown replaces a provisional one, which
  the gate refuses to settle anyway.
- "Snapshot exists" is part of the rule so a crash between the `PHASE` row and
  the copy cannot freeze a date with no snapshot.
- Not run against a live engine; covered by handler tests driving the real
  `_handle_session_state` / `_handle_eod`.

**Review fixes R3 (2026-11-01).** Two reads that grew with the retained history
instead of with the day. Measured on 1M `trade_events` (10 days), 100 gateways
× 20 symbols and a year of close snapshots (732k rows):
- **P1, statement trade lists.** `assemble._trades` called `query_trades` once
  per gateway; its `(:x IS NULL OR …)` filters defeat every index, so each call
  scanned and sorted the whole retained table. Now one `query_day_trades`
  (plain `trade_date = ?`, uses `ix_trade_events_date`) grouped by gateway in
  Python; a self-trade is one `SELF` line. `build_day` 10.6 s → 0.79 s, same
  200 000 lines. A query-plan test pins the index so the pattern cannot
  creep back.
- **P2, `pending_dates`.** It loaded every snapshot row as a dict (and capped
  silently at 1M rows) to get the dates; now `query_close_snapshot_dates`
  (`SELECT DISTINCT` on the primary key). 3.0 s → 0.03 s; this also runs on
  every `pm-eod status -q`.
- Left alone: `query_close_snapshots(date_value=…)` has the same optional-filter
  form and scans the snapshot table (~40 ms per call at a year of history; a
  run makes four calls). The gate's `query_reconcile` is ~0.3 s per 1M trades.

**Review fixes R5 (2026-11-01).** The last two low findings.
- **One backup per catch-up.** A `--pending` run over N dates backed up the
  same current databases N times, each under an older date's name. Now
  `Options.backup=False` makes each date's step `deferred`, and `main` takes one
  `backup_step` after the last date that got through, also when a later date
  fails and stops the run. A single-date run (the normal close) still backs up
  inside its run and records it in `eod_runs`. The deferred backup is printed,
  counts towards the exit code, and is not recorded in a run row.
- **Statements without long-dead symbols.** Flat positions stay in the
  snapshot for good, so "Result by symbol" printed 0.00 for every symbol the
  trader ever touched. It now lists a symbol only if it is held at the close,
  traded that day or has a non-zero result; the ledger's `detail_json` keeps
  every symbol. The empty-table text is now "Nothing held, traded or changed
  today." (it said "No positions.", which was wrong for a trader with a result).

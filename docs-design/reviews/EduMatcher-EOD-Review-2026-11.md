# pm-eod Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/eod/` at `7d9016a1` (v0.78.4): `main.py` (336
lines, the `pm-eod` CLI), `runner.py` (352), `ledger.py` (312), `settle.py`
(150), `assemble.py` (146), `report.py` (350), `housekeeping.py` (244),
`roster.py` (107). `ledger.py`'s readers are shared with pm-api-gwy
(`/clearing/eod/*`). The `clearing/store.py` functions pm-eod calls
(`closed_trade_dates`, `query_close_snapshots`, `query_reconcile`,
`query_day_trades`, `write_close_snapshot`) and the snapshot logic in
`clearing/main.py` were read where they decide pm-eod's behaviour. They
were not reviewed as code of their own.

**Focus:** correctness, edge-case handling, performance, and whether the
comments, help texts and the operator guide's "Closing the day" chapter
(`part-4-run-a-market/100-closing-the-day.md`) say what the code does.

**Previous work:** `docs-design/EduMatcher-EOD-Settlement.md` (E1–E7 and the
review fixes R1–R6). Their fixes are in place and are not repeated here:
baseline = last settled date, dates settle in order, atomic `--redo`, one
backup per catch-up run, an engine boot's CLOSED is not a close.

**Method:** every line of the files above was read. Findings marked
*(repro)* were reproduced with a scratch script against the tree at
`7d9016a1`, using the real `clearing.store` writers and `run_day`.
*(measured)* means timed on this host against a synthetic `clearing.db` of
30 days × 100 000 trades and 200 gateways × 50 symbols (626 MB). The other
findings are by inspection, with line numbers given.

Status: **Done, uncommitted.** WP-EOD01–08 completed 2026-11-14 in order,
each test-first and verified with black/flake8/mypy/pyright and the full
suite (last run: 14 073 passed, 1 skipped). Decisions Q1–Q3 taken as
recommended. WP-EOD08's text pass found one more defect, introduced by
WP-EOD01, and it was fixed (see WP-EOD01's follow-up). Exit codes changed:
warnings are now **3**; 2 means only a usage error.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (rows in `eod.db`, files under `settlement/`, CLI
   output, exit code).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_eod_*.py`,
   `tests/test_api_gateway_clearing_eod.py` and (for WP-EOD01/07)
   `tests/test_clearing_*.py` with `-n logical`, then
   black/flake8/mypy/pyright. Do not start the next WP with a known failing
   test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Runner tests build `clearing.db` with `tests/test_eod_runner.py`'s helpers
(`pos`, `close_day`, `boot`). The H1 tests also need the snapshot rule
pm-clearing applies (`close_snapshot_is_final` before
`write_close_snapshot`), as in the repro in §3.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-EOD01 | A settled day's baseline cannot change under the ledger | H1, D3 | Q1 | 1 d | ☑ | 2026-11-14 |
| 2 | WP-EOD02 | Reruns never downgrade a settled day; pruned days pass the gate | C1, C2 | Q3 | 0.5 d | ☑ | 2026-11-14 |
| 3 | WP-EOD03 | Every failure is a recorded step with a clear exit code | C4, C10 | — | 0.5 d | ☑ | 2026-11-14 |
| 4 | WP-EOD04 | The zero-sum tolerance tracks the day, not the history | C3 | Q2 | 0.25 d | ☑ | 2026-11-14 |
| 5 | WP-EOD05 | CLI edges: health check, read-only commands, dry run, bounds | C5, C6, C11, C12 | — | 0.5 d | ☑ | 2026-11-14 |
| 6 | WP-EOD06 | Report files: names, optional stats, atomic swap, stale days | C7, C8, C9, C14, C15 | — | 0.5 d | ☑ | 2026-11-14 |
| 7 | WP-EOD07 | Housekeeping and query cost | C13, P1, P2 | — | 0.5 d | ☑ | 2026-11-14 |
| 8 | WP-EOD08 | Comments, docstrings, help texts, operator guide | D1–D11 | WP-EOD01–07 | 0.5 d | ☑ | 2026-11-14 |

Suggested order: **WP-EOD01 → WP-EOD02 → WP-EOD03 → WP-EOD04 → WP-EOD05 →
WP-EOD06 → WP-EOD07 → WP-EOD08**. WP-EOD01 is the only finding that loses
money from the ledger, and it does so silently. WP-EOD02 and WP-EOD03 decide
whether one bad day can stop the scheduler's `--pending` for good. WP-EOD08
goes last so every text describes the code as it ends up.

Estimated sequential effort: about 4 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The **arithmetic** is sound. Equity is read exactly (`Decimal(repr(float))`),
summed per gateway in `Decimal`, and rounded once with the largest-remainder
method, so every recorded day sums to exactly zero. `record_day` refuses an
out-of-order date and makes `--redo` one transaction. The run is serialised
by `flock`; the report directory is swapped in by rename; backups are online
copies, integrity-checked, compressed and verified before they replace
anything.

The defects are in four places:

- **The ledger trusts that a settled snapshot never changes (H1).** The next
  day's baseline is re-read from `clearing.db`, and pm-clearing rewrites a
  date's snapshot whenever that date closes again: after a reopen (a
  `--speed` rehearsal, training step 9) or after another graceful shutdown
  without a scheduler. Everything traded between the settlement and the
  rewrite disappears from the ledger, and the zero-sum check cannot see it.
- **One failure can stop the scheduler for good (C1, C2, C4).** A rerun of a
  settled day whose gate now fails rewrites its `ok` run as `failed`. The
  day is then pending again, and `--pending` stops on it at every close. A
  day older than pm-clearing's `--retention-days` always fails the gate, and
  a YAML syntax error in the roster escapes as a traceback.
- **The zero-sum guard weakens every day (C3).** The tolerance is 0.01 per
  snapshot row, and the snapshot holds every position ever opened, flat ones
  included. Anything under the tolerance is booked to `EXCHANGE` and called
  rounding.
- **CLI and report edges (C5–C15).** `status -q` reports healthy for a
  mistyped `--datapath`. A dry run does not predict the real run. Dotted
  gateway ids overwrite each other's statements.

Severity key: **High**: money lost from or misattributed in the ledger
without a warning. **Med**: a run that fails or misleads in a way that
blocks later days or hides an error. **Low**: hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| H1 | High | Ledger | A settled date's close snapshot is rewritten when that date closes again (reopen with a scheduler; a second shutdown without one); the next day settles from the new snapshot and the change in between is never settled: A's ledger balance 15.00, true equity 35.00, in both repros *(repro)* | EOD01 |
| C1 | Med | Runner | A rerun of a settled date whose gate fails records `failed` over `ok`; the date is pending again and `--pending` stops on it at every close *(repro)* | EOD02 |
| C2 | Med | Gate | `query_reconcile` flags every date whose `trade_events` were pruned (`pm-clearing --retention-days`): such a date can be neither settled nor redone. The guide says it can *(repro)* | EOD02 |
| C3 | Med | Settle | The tolerance is `0.01 × len(today)`, all snapshot rows ever; with 2 001 rows a one-sided gain of 15.00 settles and books −15.00 to `EXCHANGE` as "rounding" *(repro)* | EOD04 |
| C4 | Med | Runner | Exceptions outside the caught set escape `run_day`: a YAML syntax error in `roster.yaml` gives a traceback after the settlement is committed, with no run row and no housekeeping *(repro)*; the same for `sqlite3.Error` in `_settle` and `balances` | EOD03 |
| C5 | Low | CLI | `status -q` with a wrong or missing `--datapath` exits 0 (healthy) and creates the directory and an empty `eod.db`; `status`, `balances` and `show` all create `eod.db` *(repro)* | EOD05 |
| C6 | Low | CLI | `--dry-run` ignores "already settled" and the order rule; in a batch, every date is measured from the last *real* settlement; amounts formatted through `float` with no `EXCHANGE` line | EOD05 |
| C7 | Low | Report | Statement file names are `Path(gateway).with_suffix(...)`: `GW.A` and `GW.B` both become `GW.md`; a `/` in a roster gateway fails or escapes `statements/`. The engine accepts any participant id *(repro)* | EOD06 |
| C8 | Low | Report | After `--redo D`, the files of the dropped later dates stay under `settlement/` with stale balances until the next `--pending` | EOD06 |
| C9 | Low | Report | A present but unusable `stats.db` (schema mismatch, corrupt) fails the whole report, though its market table is optional | EOD06 |
| C10 | Low | CLI | Exit code 2 means "housekeeping warnings" and also every usage error; `--only` silently ignores `--redo` and `--force` | EOD03 |
| C11 | Low | CLI | `validate_date` is a regex: `2026-02-30` passes and is recorded as a failed run | EOD05 |
| C12 | Low | CLI | Negative `--backup-keep-days`/`--log-keep-days` are accepted; `-1` deletes the backup the run just took | EOD05 |
| C13 | Low | Logs | Bytes appended between `compress_logs`' second `stat` and `truncate(0)` are lost | EOD07 |
| C14 | Low | Report | `write_day`: if `work.rename(final)` fails after `final.rename(old)`, the day has no directory, contrary to the docstring | EOD06 |
| C15 | Low | Report | A statement's "Today's result" can cover several closed dates (skipped or forced days fold into one interval) while the trade list is D's only; nothing says so | EOD06 |
| P1 | Low | Backup | `PRAGMA integrity_check` is 17.3 s of a 30.7 s backup of a 626 MB database; `quick_check` takes 0.9 s *(measured)* | EOD07 |
| P2 | Low | Queries | The gate's reconcile and every snapshot read scan their whole table (`(:x IS NULL OR col = :x)`): 0.61 s at 3 M trades; snapshot reads grow by 10 000 rows per sim day *(measured)* | EOD07 |
| D1–D11 | — | Comments | See §5 | EOD08 (D3: EOD01) |

---

## 3. Correctness findings

### H1. A settled day's snapshot can change under the ledger *(repro)* — High

`settle.py:121-137` `settle_date`; `runner.py:297-330` `_settle`;
`clearing/main.py:815-820` and `clearing/main.py:874-904`.

`settle_date` measures day D+1 from `position_close_snapshot` of the last
settled date D, *re-read from `clearing.db` at the time D+1 is settled*.
pm-clearing replaces a date's snapshot whenever `close_snapshot_is_final`
is false, and that becomes false again whenever date D opens again after its
close:

- **With a scheduler**, a later `PHASE` on D (a reopen) makes D "not closed"
  until its next `CLOSED`, which rewrites the snapshot. pm-eod's `--pending`
  then reports "nothing pending", because D already has an `ok` run. This is
  the `pm-scheduler --speed` rehearsal ("several fast simulated days all land
  on today's date"), and step 9 of the training chapter ("Reopen the same
  day, trade, close, then `--redo`").
- **Without a scheduler** there are no `PHASE` rows, so no snapshot is ever
  final; every graceful shutdown on D rewrites it ("replacing an earlier
  shutdown's of the same day", `clearing/main.py:815-818`). Settling D with
  `--force` and then restarting and stopping the engine on D does the same.

Reproduced both ways (A long 100, B short 100; equity in display currency):

| step | A's true equity | ledger after the step |
|---|---|---|
| D closes, `--pending` / `--force` settles D | 10.00 | A 10.00 |
| D reopens (or restarts), trades, closes again | 30.00 | A 10.00, "nothing pending" |
| D+1 closes and settles | 35.00 | **A 15.00** (should be 35.00) |

The 20.00 earned after the first settlement of D is in no settlement. Each
recorded day is still zero-sum, so `balances --check` says OK. The guide's
rehearsal section presents `--redo` as optional ("use `--redo` to run it
again on the same date"). It is the only thing that prevents the loss, and
nothing tells the operator to run it.

The design document says the shutdown snapshot is taken "**if the date has
none yet**" (`EduMatcher-EOD-Settlement.md:673`). The code replaces it (D3).

**Fix (see Q1).** pm-eod records the equity it settled from and uses its own
record as the next baseline. If D's snapshot changes after settlement, the
change then falls into D+1's interval and no money is lost. A changed
snapshot is also detected and reported.

### C1. A rerun downgrades a settled day and blocks `--pending` *(repro)* — Med

`runner.py:196-218` `finish`, `runner.py:224-229`.

`pm-eod run --date D` on a date that is already settled runs the gate again
(it only skips settling). If the gate now fails, `finish()` records
`status='failed'` with `INSERT OR REPLACE`, over the `ok` run. `pending_dates`
treats a date without an `ok` run as waiting, so D is pending again:

```
first run : gate:ok, settle:ok
rerun     : gate:fail: clearing does not reconcile for 2026-07-01 (1 discrepancies …)
runs      : [('2026-07-01', 'failed')]
pending   : ['2026-07-01', '2026-07-02']
```

`--pending` processes the oldest date first, fails its gate, prints
"stopping: later dates wait for 2026-07-01" and exits 1. The scheduler's
hook does this at every close, so no later day is settled until someone
notices. The settlement itself is untouched, so `status -q` is the only
signal. The rerun is what an operator does after fixing a roster (the
guide's "statements are wrong" route). The trigger is any gate condition
that changed since, most likely C2.

### C2. Days older than pm-clearing's retention fail the gate *(repro)* — Med

`runner.py:179-186` → `clearing/store.py:1473` `query_reconcile`.

`pm-clearing` deletes `trade_events` older than `--retention-days` (90 by
default, 7 in the AI-traders setup) and keeps `gateway_daily_summary`. The
gate calls `query_reconcile` without its `retention_days` guard, so every
summary key of a pruned date is a discrepancy. Such a date:

- cannot be settled when pm-eod catches up after a long outage (it then
  blocks every later date in `--pending`);
- cannot be redone: `--redo` fails the same gate (repro, last line);
- turns `failed` on a rerun (C1).

The guide says the opposite (`100-closing-the-day.md:728-732`): "Settling a
very old date later still gives the correct amounts … but the trade list
may be empty."

pm-eod does not know pm-clearing's retention. It can see that a date's raw
rows are gone: the date is older than `MIN(trade_date)` of `trade_events`,
and summary rows exist.

### C3. The zero-sum tolerance grows with history *(repro)* — Med

`settle.py:30-32`, `settle.py:111-118`.

```python
if abs(drift) > _TOLERANCE_PER_KEY * len(today):   # 0.01 × every snapshot row
```

`today` is the whole snapshot: every (gateway, symbol) ever traded,
including flat positions, which `write_close_snapshot` keeps for good. In
the simulation that is about 10 000 rows, so the guard accepts an
imbalance of up to 100.00 a day. `to_minor_units` then books the whole
imbalance to `EXCHANGE` (`rounding_minor = -total`), and the summary
calls it "Rounding booked to the exchange", which the guide describes as
"a cent or two".

Repro: 2 000 flat positions plus one gateway that gains 15.00 with no
counterparty. The day settles with A +15.00 and `EXCHANGE` −15.00, and
nothing is logged.

Float noise comes from changed positions only (`avg_cost` arithmetic on
today's fills and the re-mark). Flat, untouched rows contribute exactly 0.

### C4. Unexpected exceptions escape the run *(repro)* — Med

`runner.py:322`, `runner.py:343`, `roster.py:45`, `main.py:268-272`.

`_report` catches `OSError, RosterError, LedgerError, sqlite3.Error`, but
`load_roster` lets `yaml.YAMLError` (a syntax error) and
`UnicodeDecodeError` through. `_settle` catches only `SettlementError` and
`LedgerError`, so a `sqlite3.OperationalError` (disk full, locked
`eod.db`) also escapes. Repro with `name: [unclosed`:

```
raised: yaml.parser ParserError
settled: ['2026-07-01']   runs: []
```

The settlement is committed, then pm-eod dies with a traceback. There is no
run row and no audit, logs or backup step. The scheduler logs "exited 1".
`pm-eod balances` fails the same way. The roster docstring promises that
`RosterError` "names the line". The training chapter's "make a roster
mistake" exercise produces `report-failed` only because its mistake is
semantic, not a syntax error.

### C5. `status -q` is healthy for a wrong data path *(repro)* — Low

`main.py:231-241`, `runner.py:143-144`, `ledger.py:63-74`.

`_cmd_status` opens the ledger with `open_ledger`, which creates the
directory and `eod.db`, and `pending_dates` returns `[]` when `clearing.db`
does not exist. `pm-eod --datapath /typo/data status -q` therefore exits 0
and leaves `/typo/data/eod.db` behind (repro). `balances` and `show` create
the ledger too. A health check should fail when it has nothing to judge.

### C6. A dry run does not predict the real run — Low

`runner.py:275-294`, `main.py:179-201`.

- On an already-settled date it says "would settle: …"; the real run says
  "already settled" (or, with `--redo`, also drops later dates, which the
  dry run does not mention).
- It skips `_settle`'s order rule, so it says "would settle" for a date the
  real run refuses because an earlier one is pending.
- In `--pending --dry-run`, every date uses `last_settled_before` from the
  unchanged ledger, so date 2 shows the change since the last *real*
  settlement (two days), not what the real run would book.
- `f"{a / 100:+.2f}"` goes through `float`, unlike every other amount
  (`fmt_minor`), and the `EXCHANGE` line is left out.

### C7. Gateway ids become file names unchecked *(repro)* — Low

`report.py:309-317`.

`stem.with_suffix(".md")` treats everything after the last dot as a suffix:
`statements/GW.A` and `statements/GW.B` both write `statements/GW.md` (and
`.json`, `.csv`), so one trader's statement replaces another's. The engine
accepts any non-empty participant id (`engine/config_loader.py:1292-1295`);
only pm-alf-gwy and config-gen restrict it to `[A-Z][A-Z0-9_]`. A roster
gateway may be any string, so `A/B` fails the report with an `OSError`, and
`../X` would write outside `statements/`.

### C8. `--redo` leaves stale files for the dates it dropped — Low

`runner.py:318-330`, `ledger.py:122-133`.

`--redo D` deletes the ledger rows and runs of D and every later date, and
rewrites D's files. The directories of the later dates stay as they were,
with balances that no longer match the ledger. pm-api-gwy, which reads
`eod.db`, disagrees with them until those dates are settled again. That
happens at the next close (or a manual `--pending`), not in the same run.

### C9. A broken `stats.db` fails the report — Low

`runner.py:335-346`, `assemble.py:110`.

`stats.db` is optional: when it is missing, the summary says "Market
statistics unavailable." When it is present but unusable (a schema
mismatch after an upgrade, corruption, a missing table on a fresh file),
`query_daily` raises `sqlite3.Error` and the whole `report` step fails.
That withholds every statement because of an informational table.

### C10. Exit code 2 is ambiguous; `--only` drops flags silently — Low

`main.py:9-10`, `main.py:162-169`.

The docstring and guide define exit 2 as "only housekeeping warnings".
pm-eod also returns 2 for "give --date or --pending" and "--dry-run cannot
be combined with --only", and argparse exits 2 on every usage error. A
script or the scheduler hook cannot tell "settled, a backup failed" from
"did nothing". `--only report --redo` and `--only report --force` run
without the flag and without a word.

### C11. Impossible dates pass validation — Low

`main.py:323-328` → `clearing/store.py:875` `validate_date` (regex only).

`--date 2026-02-30` is accepted, fails the gate, and is recorded as a failed
run that `status` lists for good. `_prune_backups`' `date.fromisoformat`
would raise on it if a run ever got that far.

### C12. Negative retention deletes fresh files — Low

`main.py:106-107`, `housekeeping.py:166`, `housekeeping.py:236-244`.

`--backup-keep-days -1` gives a cutoff of tomorrow, so `_prune_backups`
removes `backup/<today>` right after writing it, and the step still reports
"backed up …". `--log-keep-days -1` removes every `.log.zst`.

### C13. Log compression can lose a burst of lines — Low

`housekeeping.py:150-163`.

The check `after == before` and the `truncate(0)` are two operations.
Anything a writer appends between them is truncated without having been
compressed. The one-hour idle rule makes this rare. The docstring says a
changed file "is left for the next run", but that only covers changes
before the second `stat`. A cheap fix is to re-check the size inside the
`r+b` handle just before truncating. That narrows the window to
microseconds; closing it fully needs the writer's cooperation.

### C14. `write_day` can leave the day without a directory — Low

`report.py:326-350`.

If `work.rename(final)` fails after `final.rename(old)` succeeded, the
`except` removes `work` and re-raises. The previous version is left at
`.D.old` and `settlement/D` does not exist, although the docstring says "a
failed write leaves the previous one untouched". The fix is to rename `old`
back in the `except`.

### C15. A multi-day interval reads as one day — Low

`settle.py:121-131`, `report.py:246-289`.

A skipped `--force` day, or a closed day without a snapshot (which
`pending_dates` never lists), folds into the next settlement by design
(`settle_date`'s docstring). The statement still says "Today's result", and
the trade list comes from `trade_events` of D only, so a trader sees a result
whose trades are not listed. The previous settled date is known at settle
time. Store it with the day and print "Result since <date>" when it is not
the previous closed date.

---

## 4. Performance findings

Neither finding matters at today's sizes. pm-eod runs once a day and takes
seconds. Both grow with history, not with the size of the day.

### P1. The backup's integrity check dominates *(measured)* — Low

`housekeeping.py:222-233`. On the 626 MB synthetic `clearing.db`:

| | time |
|---|---|
| `backup_databases` (copy + check + compress + verify) | 30.7 s |
| `PRAGMA integrity_check` alone | 17.3 s |
| `PRAGMA quick_check` | 0.9 s |

`stats.db` peaks at about 3 GB in the simulation (the reason `ai-sim` skips
it), where the full check alone would take over a minute. `quick_check`
verifies page and record structure. It skips only index-to-table
consistency, which an online copy of a healthy database cannot break.

### P2. Gate and snapshot reads scan whole tables *(measured)* — Low

`clearing/store.py:1387-1420` (`query_close_snapshots`) and `:1473`
(`query_reconcile`) use `(:x IS NULL OR col = :x)`, which SQLite plans as a
full scan:

```
WHERE (:d IS NULL OR trade_date = :d)  → SCAN position_close_snapshot
WHERE trade_date = :d                  → SEARCH … USING INDEX (trade_date=?)
```

Measured at 30 days: reconcile for one day 0.61 s (3 M `trade_events`),
snapshot read 0.04 s (300 000 rows). `position_close_snapshot` is never
pruned and grows by every (gateway, symbol) ever traded, every day: about
3.6 M rows a year in the simulation. A run reads the snapshot four times
(gate, settle ×2, report). `pending_dates` also loads every run with its
`steps_json` (`runner.py:155`) to collect the `ok` dates.

**Fix.** Plain `trade_date = ?` queries for the day-scoped reads pm-eod
uses (as `query_day_trades` already does, `f122c4e7`), and
`SELECT trade_date FROM eod_runs WHERE status = 'ok'`.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `runner.py:187` | The gate's ok message "closed, snapshot present, reconciled" is printed under `--force`, which never checked "closed". |
| D2 | `main.py:92-95` | `--force` help "Do not require the CLOSED session event (no scheduler)": it skips the whole closed rule (including "the market opened"), and nothing warns that a forced day must not be traded again (H1). |
| D3 | `EduMatcher-EOD-Settlement.md:670-674`; `clearing/main.py:815-818` | The design doc says the shutdown snapshot is taken "if the date has none yet"; the code replaces every non-final one. One of them changes with WP-EOD01 (H1). |
| D4 | `settle.py:1-11`, `settle.py:30-32`, `ledger.py:1-9` | "what is left over is float noise … and the rounding" and "the rounding residual sits on EXCHANGE": the tolerance admits more than noise (C3); `compute_settlement` does not say that `rounding_minor` is the negated exact total. |
| D5 | `report.py:7` | "Layout of `<eod dir>/<date>/`": the directory is `<data>/settlement/<date>/`; `<data>/eod/` is the engine's, which pm-eod must never touch. |
| D6 | `report.py:326-332` | `write_day`'s "a failed write leaves the previous one untouched" (C14). |
| D7 | `housekeeping.py:133-139` | `compress_logs`' "a file that changes while it is being compressed is left for the next run" (C13). |
| D8 | `roster.py:28-29` | `RosterError` "the message names the line": YAML syntax errors bypass it (C4). |
| D9 | `main.py:9-10`, `main.py:120-124` | Exit codes (C10); `status -q` "exit 0 when no closed date is waiting" is also exit 0 when there is no `clearing.db` (C5). |
| D10 | `100-closing-the-day.md:728-732`, `:1074-1081`, `:514` | Old dates "still give the correct amounts" (C2); the rehearsal's `--redo` is presented as optional (H1); "`--force` skips *only* the closed-day test" also needs the H1 warning. |
| D11 | `assemble.py:37`, `runner.py:47` | `build_day`, the module's only public function, has no docstring; `STEPS` is the list `--only` accepts, not every step (`gate`/`settle` are missing), and says neither. |

---

## 6. Verified as correct

- **Rounding.** `to_minor_units` adds `total − Σ floors` units, which is
  always in `[0, number of accounts with a remainder]`, so the result sums
  to `total` exactly. Ties go to the lower account id, which is
  deterministic.
- **Exact equity.** `Decimal(repr(float))` recovers the stored value
  exactly, and scaling by `10**tick_decimals` per row handles mixed
  precisions.
- **Ledger writes.** `record_day` checks zero-sum, "already settled" and
  "later date settled" before its transaction. A redo deletes and inserts
  in one transaction. A failure leaves the ledger as it was.
- **Order rule.** `_settle` refuses D while an earlier closed date is
  unsettled. A `report-failed` day does not block, because it is settled.
- **Pending.** Boot-only dates and mid-day restarts are not pending
  (`closed_trade_dates`). Dates without a snapshot are excluded. A date
  whose run failed stays pending.
- **Locking.** `flock` on `.pm-eod.lock` with `LOCK_NB` refuses a second
  run. Read-only commands do not need the lock: the ledger is WAL, and its
  writes are single transactions.
- **Batch backup.** One backup after the last date that got through,
  labelled with that date. None when the first date fails, which matches a
  single failed run.
- **Report swap.** The `.partial` work directory is cleared first. A
  rewrite replaces the whole directory, so no statement of a gateway that
  disappeared survives.
- **Backups.** The online backup API gives a consistent copy under a live
  writer. The check runs on the copy, `_verified_zstd` decompresses and
  compares digests before the `fsync` and rename, and a failure leaves the
  previous backup in place.
- **Roster.** Duplicate gateways (after upper-casing), unknown keys,
  `EXCHANGE`, non-finite and over-precise opening balances are all refused
  with a line number.
- **Readers for pm-api-gwy.** `open_ledger_readonly` percent-encodes the
  path, never creates the file and sets `busy_timeout`.

---

## 7. Decisions

All three taken as recommended on 2026-11-14.

| # | Question | Recommendation |
|---|---|---|
| Q1 (taken as recommended) | Where does the next day's baseline come from (H1)? (a) pm-eod stores the equity rows it settled from in `eod.db` and uses them as the baseline. (b) pm-clearing refuses to rewrite a snapshot once the date has closed once, and also without a scheduler. (c) Keep reading `clearing.db`, but detect a changed snapshot and refuse to settle until `--redo`. | **(a), plus detection.** A new table `eod_close_equity(trade_date, gateway_id, symbol, equity TEXT)` is written in `record_day`'s transaction. `settle_date` takes the baseline from it. When `clearing.db` has no snapshot for the previous date at all, that is still treated as a reset (zero baseline, as today). If the clearing snapshot of the previous settled date differs from the stored one, the settle message says so ("D's snapshot changed after it was settled; the difference is in this day"), so nothing is lost and the operator can still `--redo D`. (b) cannot work without a scheduler, where the last shutdown *is* the close. (c) blocks the scheduler. `eod.db` grows by one snapshot a day: rows for positions that changed are enough if a missing row means "unchanged since the last stored value", but storing every row is simpler and is about 10 000 rows a day in the simulation. Recommend all rows; no migration (new table, `CREATE IF NOT EXISTS`; earlier dates fall back to `clearing.db`, documented). |
| Q2 (taken as recommended) | What should the zero-sum tolerance be (C3)? | 0.01 per position **whose equity changed since the baseline**, and a minimum of 0.01. Record the exact drift in the run's settle message whenever the `EXCHANGE` line is not zero, so a growing residual is visible. Re-measure the largest residual on the next simulation run before tightening further. |
| Q3 (taken as recommended) | How should a settled date, or one whose raw trades were pruned, pass the gate (C1, C2)? | A date that is already settled (and no `--redo`) skips the gate: nothing is settled, and only the report and housekeeping run. A failed rerun then cannot replace `ok`, because the recorded status keeps `ok` unless settle itself ran. For settle and redo, a date older than `MIN(trade_events.trade_date)` skips the reconcile check, and the gate message says so ("raw trades pruned; not reconciled"). |

---

## 8. Work packages

### WP-EOD01 — A settled baseline cannot change (H1, D3; after Q1)

**Tests first** (`tests/test_eod_baseline.py`, new):

1. Scheduler reopen: D closes, `--pending` settles D; D opens, trades and
   closes again (pm-clearing's rule rewrites the snapshot); D+1 closes and
   settles. `balances()` equals the final equity (A 35.00, B −35.00).
   (Fails today: 15.00.)
2. No scheduler: shutdown on D, `--force` settles D, another shutdown on D
   with more P&L, then D+1. Same assertion. (Fails today.)
3. Test 1's D+1 settle message names D's changed snapshot.
4. Reset: `clearing.db` replaced (no snapshot for D) → D+1 starts from zero,
   as today.
5. `--redo D` after the reopen settles D from the rewritten snapshot and
   drops D+1, as today.

**Change.** `eod_close_equity` in `ledger.SCHEMA`. `record_day` stores
the day's equity rows, and a redo deletes them with the settlements.
`settle_date` gets the baseline rows from the ledger. A previous date
without stored rows (settled before this WP) falls back to `clearing.db`.
`_settle` compares the two baselines and adds the note. D3: the design doc
says what pm-clearing does.

**Exit criteria.** Tests 1–5 pass; `tests/test_eod_*.py` and
`tests/test_api_gateway_clearing_eod.py` green.

**Outcome (2026-11-14).** New table `eod_close_equity` (exact decimal
strings), written in `record_day`'s transaction and deleted by a redo.
`Settlement` carries `equity` and `baseline_changed`. `settle_date(clearing,
date, previous, settled)` measures from the recorded equity. It falls back
to `previous`'s snapshot when nothing was recorded, and starts from zero
when `clearing.db` has no snapshot for `previous` (a reset).
`compute_settlement`/`day_pnl` now take the baseline as a
`{(gateway, symbol): equity}` mapping (`equities()` builds one from
snapshots). `_settle` and the dry run share `_settle_against_ledger`.
A changed baseline makes the settle step `warn`, naming the date and the
`--redo` alternative; the run status stays `ok`. Docs: the design doc's
"if the date has none yet" corrected (D3); the reference manual's ledger
table and settlement rule; the schema docs regenerated. Tests:
`tests/test_eod_baseline.py` (6; the 4 behaviour tests failed first, with
15.00 against 35.00), plus 3 `settle_date` tests and 1 ledger round trip.
Full suite: 14 017 passed, 1 skipped.

**Follow-up (found during WP-EOD08, 2026-11-14).** Checking the guide's
"After `pm-opctl-cli clear`" section showed a case the recorded baseline
made worse. `clear --state` deletes `clearing.db` and keeps `eod.db`. If
the same calendar date then trades again, that date has a snapshot again,
but in a new `clearing.db` whose equity restarted at zero. Without `--redo`,
the next date was measured from the pre-reset equity and erased every
pre-reset gain (repro: A 500 instead of 1 500). Before WP-EOD01 that case
only lost the post-reset part of that one date. Fix: `apply_schema` writes
a random `instance_id` into `clearing_meta` once per file
(`store.clearing_instance()`). `record_day` stores the instance each date
was settled from in the new table `eod_close_source`, and
`ledger.settled_baseline()` returns a `Baseline(equity, clearing_instance)`.
`settle_date` measures from zero (`baseline_reset`, settle step `warn`
"clearing.db was replaced after D was settled …") when both instances are
known and differ. Unknown counts as the same file. Tests:
`test_a_reset_then_the_same_date_again_starts_from_zero` (failed first: 500
against 1 500), a `settle_date` test for both instances, the instance id
test and the ledger round trip. Reference manual and schema docs updated.
Full suite: 14 073 passed, 1 skipped.

### WP-EOD02 — Reruns and pruned days (C1, C2; after Q3)

**Tests first** (`tests/test_eod_runner.py`):

1. A settled date whose reconcile now fails: a rerun (no `--redo`) writes
   the report, the run stays `ok`, and `pending_dates` does not list it.
   (Fails today.)
2. `--pending` with that date and a later closed date settles the later
   one. (Fails today.)
3. A date whose `trade_events` are older than the oldest remaining row,
   with summaries present: it settles, and the gate message says "not
   reconciled". (Fails today.)
4. The same date with `--redo`. (Fails today.)
5. A real discrepancy on a date that still has raw trades fails the gate,
   unchanged.

**Change.** In `run_day`, a settled date without `redo` skips `_gate`.
`_gate` skips the reconcile check for pruned dates. `finish()` does not
downgrade an `ok` run when settle did not run.

**Exit criteria.** Tests pass; the guide's old-date paragraph (D10) is true.

**Outcome (2026-11-14).** `run_day` decides up front whether this is a
rerun (settled already, no `--redo`, no `--only`). A rerun's gate step is
`ok` "already settled: not checked again (--redo recomputes)", and a failing
rerun does not replace an `ok` run (it is not recorded, like `--only`). A
`report-failed` day is still recorded, so it can heal. `_gate` accepts a
reconcile discrepancy when the date is older than the oldest `trade_events`
row, or the table is empty (`_raw_trades_pruned`), and says "not
reconciled". Tests: `TestRerunAndPrunedDays` in `tests/test_eod_runner.py`
(8; the 6 behaviour tests failed first). Full suite: 14 025 passed, 1
skipped.

### WP-EOD03 — Every failure is a recorded step (C4, C10)

**Tests first** (`tests/test_eod_runner.py`, `tests/test_eod_cli.py`):

1. A roster with a YAML syntax error: `report` is `fail` with the file and
   line, the run is `report-failed`, and housekeeping still runs. (Fails
   today.)
2. `balances` with that roster prints `pm-eod: …` and exits 1, with no
   traceback. (Fails today.)
3. `_settle` with `record_day` raising `sqlite3.OperationalError`: settle
   `fail`, run `failed`, exit 1. (Fails today.)
4. A run whose only problems are housekeeping warnings exits 3; usage
   errors still exit 2 (argparse's code); `--only` with `--redo`/`--force`
   is a usage error. (Fails today.)

**Change.** `load_roster` wraps `yaml.YAMLError` and `UnicodeDecodeError`
in `RosterError`, using the mark's line. `_settle` also catches
`sqlite3.Error`. "Housekeeping warnings" moves from 2 to 3, so 2 stays
argparse's usage code everywhere. Confirm with Johan before changing it,
because cron and container setups may test for 2. Update the help, the
docstring and the guide's exit-code table.

**Exit criteria.** Tests pass; no code path of `pm-eod run` prints a
traceback for a foreseeable error.

**Outcome (2026-11-14).** `load_roster` turns a YAML syntax error into
`RosterError` "<path>: line N: not valid YAML: <problem> (<context> started
on line M)", and a non-UTF-8 file into "not UTF-8 text". pm-api-gwy's roster
reader catches `RosterError` already. `_settle` also catches
`sqlite3.Error`; `_report` opens its databases inside its `try`. `main()`
turns any `sqlite3.Error`/`OSError` outside a step into `pm-eod: <error>`,
exit 1. Exit codes: **3** = settled and reported with warnings (this also
covers WP-EOD01's settle note), and 2 is now only a usage error. No caller
in the repo tests for 2: the scheduler only logs non-zero codes, and the
container and emo profiles do not check it. `--only` with `--redo` or
`--force` is a usage error. Updated: the module docstring, `exit_code`, the
`pm-help` registry, the reference manual, and the guide's exit-code table
and warnings table (with the settle note's row). Tests: 2 runner, 5 CLI and
2 roster tests (all failed first); one existing assertion moved from 2 to 3.
Full suite: 14 034 passed, 1 skipped.

### WP-EOD04 — Tolerance tracks the day (C3; after Q2)

**Tests first** (`tests/test_eod_settle.py`):

1. 2 000 unchanged positions plus a one-sided 15.00 gain: `SettlementError`.
   (Fails today.)
2. Float noise of 1e-9 per changed position over 500 changed positions
   settles, unchanged.
3. A non-zero `EXCHANGE` line puts the exact drift in the settle message.

**Change.** Count the changed positions (delta ≠ 0) in
`compute_settlement`, with a minimum of 1. `_settle` appends the drift. D4.

**Exit criteria.** Tests pass; existing settle tests unchanged.

**Outcome (2026-11-14).** `compute_settlement` allows 0.01 per position
whose equity changed (at least 0.01), and the error says "N changed
position(s)". `Settlement.drift` keeps the exact total. A non-zero rounding
line makes the settle message "…; rounding -0.01 booked to EXCHANGE (exact
total of the day 0.006)". The guide's troubleshooting row and the reference
manual's settlement rule were updated; the module comments are D4
(WP-EOD08). Tests: 3 settle tests and 1 runner test (all failed first).
Full suite: 14 038 passed, 1 skipped.

### WP-EOD05 — CLI edges (C5, C6, C11, C12)

**Tests first** (`tests/test_eod_cli.py`):

1. `status -q` with a missing `clearing.db` exits 1, says why on stderr, and
   creates nothing. (Fails today.)
2. `status`, `balances` and `show` on a data directory without `eod.db`
   create no file. (Fails today.)
3. `run --date 2026-02-30` exits 2 with "invalid date" and records no run.
   (Fails today.)
4. `--backup-keep-days -1` and `--log-keep-days -1` are usage errors.
   (Fails today.)
5. Dry run on a settled date says "already settled"; on a date blocked by
   the order rule it fails like the real run; `--pending --dry-run` chains
   each date's baseline to the previous date's dry result; amounts use
   `fmt_minor` and include `EXCHANGE`. (Fails today.)

**Change.** Read-only commands use `open_ledger_readonly` and treat a missing
ledger as "nothing settled". `validate_date` parses with
`date.fromisoformat` (shared with pm-clearing-cli; check its tests). Use a
`non_negative_int` argparse type. `_dry_run` shares `_settle`'s checks and
takes an in-memory baseline for batches.

**Exit criteria.** Tests pass; the training chapter's CLI transcripts still
match.

**Outcome (2026-11-14).** `status`, `balances` and `show` read `eod.db`
read-only and never create it (`balances`/`show` without one use an empty
in-memory ledger). `pending_dates` and `run_day`'s rerun check read it
read-only too. `status` without `clearing.db` prints `pm-eod: <path> not
found`, and `-q` exits 1. pm-eod validates dates with
`stats.query.validate_date` (`strptime` plus the zero-padded round trip),
which pm-api-gwy's EOD routes already use. `clearing.store.validate_date`
is unchanged; see §9. `--backup-keep-days`/`--log-keep-days` take 0 or
more, and gained help texts. A dry run settles into
`ledger.open_scratch_ledger` (an in-memory copy of `eod.db`) with the real
`_settle`, so it says "already settled" and applies the order rule like the
real run. With `--redo` it names what it would drop. `--pending --dry-run`
shares one scratch ledger, so each date chains from the previous dry
result. Amounts use `fmt_minor` with an explicit `+`, plus the `EXCHANGE`
line when it is not zero, so the guide's transcripts still match.
`pm-completion.zsh` regenerated. Tests: 12 CLI tests and 1 runner test (all
behaviour tests failed first). Full suite: 14 051 passed, 1 skipped, then
the completion test after regeneration.

### WP-EOD06 — Report files (C7, C8, C9, C14, C15)

**Tests first** (`tests/test_eod_report.py`, `tests/test_eod_runner.py`):

1. Gateways `GW.A` and `GW.B` get `GW.A.md` and `GW.B.md`. (Fails today.)
2. A roster gateway containing `/` is refused by `load_roster` with its
   line. (Fails today.)
3. After `--redo D` with D+1 settled, `settlement/D+1` no longer exists (or
   is rewritten; see the change). (Fails today.)
4. A `stats.db` without `daily_stats`: report `ok`, "Market statistics
   unavailable" plus a warning naming the error. (Fails today.)
5. `write_day` with `work.rename` patched to fail after the old directory
   moved: `settlement/D` is the previous version. (Fails today.)
6. A day settled across a skipped closed date: the statement says
   "Result since <previous settled date>". (Fails today.)

**Change.** Use `stem.parent / f"{stem.name}.md"`. The roster restricts
gateway ids to the engine's practical charset (no `/`, `\`, NUL, no leading
dot). `--redo` removes the dropped dates' directories (the next `--pending`
writes them again). Recommend removal over re-settling in the same run:
it keeps `--redo` one date. `_market` errors become a warning. `write_day`
restores `old` on failure. The previous settled date is stored on the run or
the settlement rows. If Q1 is taken as recommended, it is
`eod_close_equity`'s baseline date.

**Exit criteria.** Tests pass.

**Outcome (2026-11-14).** Statement files are `<gateway>.md|.json|.csv`
built by string, not `with_suffix`. `load_roster` refuses a gateway with
`/`, `\`, NUL or a leading `.`, naming its line. A real (non-dry) redo
removes `settlement/<date>/` of every date it drops, including its own,
which the report step writes again. A `sqlite3.Error` from `stats.db`
becomes the warning "market statistics unavailable: <error>" and "Market
statistics unavailable." in the summary. `write_day` renames `.D.old` back
when the swap fails halfway. `Statement.since` (in the JSON as `since`) is
the previous settled date when a close-snapshot date between it and this
date was never settled; the statement then reads "Result since the close of
<date>: X (no day in between was settled; the trades below are <D>'s)".
It is derived from the ledger and `clearing.db` at report time, so nothing
new is stored. Tests: 4 report, 2 assemble, 4 roster and 1 runner tests
(all failed first). Full suite: 14 063 passed, 1 skipped.

### WP-EOD07 — Housekeeping and query cost (C13, P1, P2)

**Tests first** (`tests/test_eod_housekeeping.py`, `tests/test_clearing_*.py`):

1. `compress_logs` with an append injected between the second `stat` and the
   truncation leaves the file intact for the next run. (Fails today.)
2. `_online_copy` runs `quick_check` (assert via a trace callback), and a
   corrupt page is still refused.
3. `EXPLAIN QUERY PLAN` of the snapshot read and the gate's reconcile for one
   date uses the `trade_date` index. (Fails today.)

**Change.** Truncate only when the size seen through the `r+b` handle
equals the compressed length. Use `PRAGMA quick_check`. Add date-scoped
`query_day_snapshots(conn, date)` and a date-scoped reconcile in
`clearing/store.py` (plain `trade_date = ?`), used by pm-eod. In
`pending_dates`, select only the `ok` dates.

**Exit criteria.** Tests pass; on the bench database, `_gate` runs in under
0.1 s and the backup is at least 40 % faster.

**Outcome (2026-11-14).** `compress_logs` checks the size once more with
`os.fstat` on the `r+b` handle that truncates, and leaves the file for the
next run if it grew. `_online_copy` uses `PRAGMA quick_check`; a corrupt
b-tree page is still refused (test). `clearing/store.py` gained
`_drop_unset_filters`, which resolves `(:x IS NULL OR cond)` in Python
before SQLite plans the query. It is applied only to `query_close_snapshots`
and `query_reconcile`, pm-eod's paths; their results are unchanged for every
caller (the whole clearing suite passes). `pending_dates` reads
`ledger.ok_dates()`.

Bench (626 MB `clearing.db`, 30 days × 100 000 trades):

| | before | after |
|---|---|---|
| `backup_databases` | 30.7 s | 12.7 s (−59 %) |
| `_gate` | 0.63 s | 0.29 s |
| `settle_date` | 0.14 s | 0.10 s |
| reconcile, first vs last day | grows with history | 0.287 s vs 0.291 s |

The gate misses the 0.1 s target. Its cost is now the day's own
aggregation, two passes over that day's 100 000 trades (one side alone
takes 0.12 s), and no longer grows with retention, which was the finding.
The target was a guess and is not worth a covering index. Tests: 3 in
`tests/test_clearing_day_queries.py`, 3 housekeeping tests and 1 ledger
test (the four behaviour tests failed first; the corrupt-page guard passed
before and after). Guide: the backup step's check. Full suite: 14 070
passed, 1 skipped.

### WP-EOD08 — Comments, docstrings, help texts, guide (D1, D2, D4–D11)

Text only, after WP-EOD01–07 so the texts describe the final behaviour.
Each changed help text is checked against `pm-eod run --help` output and
the guide's command table (`100-closing-the-day.md:1190-1205`), and against
the `pm-help` registry entry.

**Outcome (2026-11-14).** D1: the gate says `not checked (--force), snapshot
present, …` under `--force`. D2/D9: `--force`, `--only`, `--dry-run`,
`--*-keep-days` and `status -q` help texts, in argparse and in the `pm-help`
registry (zsh completion regenerated). D4: the `settle`/`ledger` module
docstrings describe the tolerance and the `EXCHANGE` residual. D5:
`report.py`'s layout is `<data>/settlement/<date>/`. D6: `write_day`. D8:
`RosterError`. D11: `build_day` docstring, `STEPS` comment. (D3 was done in
WP-EOD01, D7 in WP-EOD07.) D10, operator guide: the `--force` gate line;
stopping the engine twice; rerun semantics and `status -q`; pruned days
"not reconciled"; *Result since* and the JSON `since`; `--only`
restrictions; dry run; `--redo` removes the dropped dates' folders; after
`clear --state` (do **not** `--redo` a re-traded date); the rehearsal
section; the troubleshooting and warnings tables. Training chapter 20:
Exercise 9 (a failing rerun no longer turns an `ok` day `report-failed`:
the run exits 1, `status -q` stays 0), Exercise 10 (`--redo --dry-run`, and
what happens without `--redo`), the summary. Participant guide: *Result
since …*. Reference manual: options, status, rerun rule, statement JSON.
The changed transcripts were derived from the code's messages, not
re-run end to end.

While checking the `clear --state` section this WP found the reset defect
fixed under WP-EOD01's follow-up. It is the only behaviour change in this
WP. Full suite: 14 073 passed, 1 skipped.

---

## 9. Out of scope, noted

- `position_close_snapshot` is never pruned and keeps every flat position,
  so `clearing.db`, and with it every nightly backup, grows by one full
  position table per day (about 10 000 rows a day in the simulation). Once
  WP-EOD01 stores the settled equity in `eod.db`, pm-clearing could keep
  snapshots for a window only. Recorded as L019 in
  `EduMatcher-For-Later-ToDo.md`.
- `clearing/store.py` uses the `(:x IS NULL OR col = :x)` pattern in most of
  its readers (pm-clearing-cli, pm-api-gwy). WP-EOD07 fixes only the two
  pm-eod paths. The rest belongs to a clearing review.
- `clearing.store.validate_date` (pm-clearing-cli and, until WP-EOD05,
  pm-eod) is a regex: it accepts `2026-02-30`. pm-eod now uses
  `stats.query.validate_date`; pm-clearing-cli's `--date`/`--from`/`--to`
  only returns no rows for such a date, which is harmless.
- The scheduler's `--on-close` delay is what orders pm-clearing's snapshot
  before pm-eod's `pending_dates`. If pm-clearing lags past the delay, the
  day is not seen as pending and is settled at the next close, together
  with that day, in order. That is correct, only late, and is not changed
  here.

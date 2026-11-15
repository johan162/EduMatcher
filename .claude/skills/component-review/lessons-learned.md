# Lessons learned

Collected from the 2026-11 reviews of pm-stats, pm-audit and pm-eod and from
implementing their WPs. Part A is a checklist of defect patterns that were
actually found; go through it during every review. Part B is about the
process; check it before closing every WP.

## A. Defect patterns to hunt for

### A1. State that another process can change underneath you
- **A value re-read from another component's database is not what you
  consumed.** pm-eod re-read a settled day's close snapshot from
  `clearing.db` as the next day's baseline; pm-clearing rewrites that
  snapshot whenever the date closes again (reopen, second shutdown). The
  money in between vanished. Fix pattern: *record what you consumed* (the
  equity settled at) and detect when the source changed afterwards.
- **A file can be replaced, not just changed.** After
  `pm-opctl-cli clear --state` a new `clearing.db` has the same dates but
  restarted figures. Give a database an identity (a random
  `clearing_meta.instance_id` written once) and record which instance you
  read.
- Ask for every input: who else writes it, when, and can it be rewritten,
  pruned, or replaced after I used it?

### A2. Checks that cannot see the failure
- **Zero-sum / aggregate checks** cannot catch a dropped, deleted or
  re-based zero-sum set. Every one of the EOD money bugs passed
  `balances --check`. Prove money is conserved across the *sequence* of days
  (balance = true cumulative equity), not per day.
- **Tolerances scaled by a count that grows with history** weaken over time:
  the settlement tolerance was 0.01 × *every snapshot row ever* (flat ones
  included), so about 100.00/day was absorbed as "rounding". Scale by what
  changed today.
- **A health check must fail when it has nothing to judge.** `status -q`
  exited 0 for a mistyped `--datapath`. A "read/write" health check that
  writes a TEMP table never touches the real file.
- **Read commands must not create state.** `status`/`balances`/`show` created
  an empty `eod.db` (and the directory) via the read-write opener. Use the
  read-only opener and treat a missing file as empty.

### A3. Reruns, restarts, catch-up and order
- **A rerun must never downgrade a good state.** A rerun of an `ok` day whose
  gate now failed recorded `failed` over `ok`, making the day pending again;
  `--pending` then stopped on it at every close, forever. Rerun failures are
  printed, not recorded over success.
- **One failing item must not block a queue for good** (oldest-first
  catch-up stops at the first failure: is there any input that always fails?).
- **Retention and pruning versus checks:** a consistency check comparing raw
  rows with summaries flags every pruned day. Detect "pruned" (older than the
  oldest raw row) and say "not reconciled" instead of failing.
- **Rehydrate on every switch, not only on first touch:** pm-stats rebuilt a
  day's accumulator only the first time it saw a symbol; switching to another
  day and back overwrote both days with a handful of trades.
- **Clocks:** a value stamped with the receiver's clock (EOD on receipt time)
  lands on the wrong trading date after midnight or with host clock skew.
  Prefer the event's own timestamp, or the context already held.

### A4. Failure handling and exit codes
- **List what each library call can raise.** `yaml.safe_load` raises
  `yaml.YAMLError` (not `ValueError`), `read_text` raises
  `UnicodeDecodeError`, SQLite raises `sqlite3.Error` subclasses. Anything
  outside the caught set escaped `run_day` *after* the settlement was
  committed: a traceback, no run row, no housekeeping.
- **A dying worker thread must make the process exit non-zero**, on every
  branch (pm-stats returned 0 when its receive thread died during start-up).
  EINTR from `poll` is a `continue`, not a stop.
- **Exit codes must not collide.** argparse uses 2 for usage errors, so a
  meaningful "2 = warnings" is ambiguous. Give warnings their own code (3).
- **Failures must be counted and visible:** every failure path increments a
  metric or logs at ERROR, and repeated errors are latched per key, not logged
  per message.
- **Silently ignored flags** (`--only` ignoring `--redo`/`--force`) should be
  usage errors.

### A5. Files and paths
- **`Path.with_suffix()` on an identifier containing a dot** truncates it:
  `GW.A` and `GW.B` both became `GW.md`. Build names by string, and refuse ids
  that cannot be file names (`/`, `\`, NUL, leading `.`).
- **Atomic directory swap:** when `final → old` succeeded and `work → final`
  failed, put `old` back in the `except`.
- **TOCTOU in copy-then-truncate:** re-check the size on the very handle that
  truncates (`os.fstat`); a check before opening leaves a window.
- **A negative retention value** deleted the backup just taken. Validate
  `N ≥ 0` in argparse.
- **Dates:** a regex accepts `2026-02-30`. Parse, and round-trip the
  zero-padded form (`stats.query.validate_date`).

### A6. SQL and performance
- **`(:x IS NULL OR col = :x)` defeats indexes.** SQLite plans it as a full
  scan whatever `:x` is. Resolve unset filters before planning
  (`clearing.store._drop_unset_filters`) or write plain `col = ?` for hot or
  day-scoped paths.
- **Verify plans on the SQL actually executed:** capture it with
  `conn.set_trace_callback(list.append)` (bound values expanded) and
  `EXPLAIN QUERY PLAN` it; a test can assert "no `SCAN <table>`".
- **Say whether cost grows with history or with the day.** Compare the first
  and the last day of a bench database; a constant cost per day is fine.
- **`PRAGMA integrity_check` dominated a backup** (17 s of 31 s on 626 MB);
  `quick_check` (0.9 s) checks every page and record, enough for a fresh online
  copy. Keep a corrupt-page test proving it still refuses damage.
- **Write amplification:** no-op upserts per message (pm-stats book path
  18 µs → 4 µs without them). **Long transactions** on a receive thread (a
  bulk prune) overflow the subscriber's high-water mark; delete in bounded
  batches.
- **Loading whole rows to use one column** (all runs with `steps_json` just to
  collect `ok` dates): select the column.

### A7. Output and wording
- **`%g` rounds to six significant digits** (`12345.67` → `12345.7`); print
  prices and amounts with an exact formatter.
- **Silent truncation** at a `--limit` must say so (or page).
- **Recorded but never shown columns** (`reject_code`, `msg_id`) are findings.
- **A message that claims a check that was skipped** ("closed, …" under
  `--force`) is a finding.
- **A dry run should run the real code** against a scratch copy (an in-memory
  copy of the ledger), so it refuses what the real run refuses, chains
  multi-date runs, and never drifts from the real logic.
- **A result over several periods must say so** ("Result since the close of
  …" when skipped days fold into one interval).

## B. Process lessons

### B1. Re-walk documented flows after changing behaviour
The EOD reset regression (pre-reset gains erased) was introduced by WP-EOD01
and found only during the text-only WP, by checking the guide's
"After `pm-opctl-cli clear`" section against the new code. For every change in
behaviour, go through each doc passage, training exercise and transcript
that describes that flow, and run it through the new code mentally or with
a script. Also check that the guide's *advice* is still safe: after the fix,
`--redo` became harmful in exactly that reset case.

### B2. Tests fail first, for the right reason
Read the `E` lines of the first run. A test that fails on an import, a
fixture, or a mistake in the test itself (passing the wrong date's equity as
a baseline) proves nothing. Tests that encode unchanged behaviour must pass
before the change too.

### B3. Scripted edits can hit the wrong place
`str.replace(old, new, 1)` hit an identical block in another function
(`query_daily` instead of `query_close_snapshots`), and a table-cell replace
hit the status table instead of the decisions table. After scripted edits run
`git diff -U0 <file> | grep '^@@'` and check that every hunk is in the
intended function. Assert `old in text` before replacing, and slice by an
anchor (`text.index("def target(")`) when the block is not unique.

### B4. Mechanics of this repo
- Coverage is on by default: use `--no-cov` for focused runs.
- `make _check` also verifies generated artefacts: `make dbdocs` after schema
  changes and `make completion` after argparse help changes; the
  `test_shell_completion` test fails otherwise.
- The full suite takes about 2 minutes: run it in the foreground. Editing
  files while a background run is in flight risks a mixed result.
- `mypy` flags unused `# type: ignore`; prefer `Any`-typed test helpers to
  ignores.
- The read-only SQLite opener of each component (`open_ledger_readonly`,
  `stats.query.open_readonly_connection`) percent-encodes the path, sets
  `busy_timeout`, and never creates the file. Reuse it.
- Untracked files that appear during a test run (for example
  `build-tools/.mermaid-cache/*`) are not yours: mention them, don't delete
  them.

### B5. Honesty in outcomes
- A numeric exit criterion that was a guess and turns out wrong is reported
  as missed, with the measurement and the reason (the gate target of 0.1 s was
  0.29 s, all of it the day's own aggregation).
- Items the plan said to "confirm with the user" (an exit-code change, an API
  contract) are named in the hand-over even when the user said to accept the
  proposals.
- Transcripts in the docs that were derived from code messages rather than
  re-run are labelled as such in the outcome.

### B6. Scope discipline
- Shared code is changed only on the component's paths. A broader fix
  (every `(:x IS NULL …)` reader, `clearing.store.validate_date`) goes in §9
  or the For-Later list.
- Prefer an existing correct helper elsewhere in the codebase over changing a
  shared one used by other CLIs (`stats.query.validate_date` instead of
  tightening `clearing.store.validate_date`).
- No migration code (project rule). A fallback that is simply the old code
  path for data that predates a new table is acceptable when a decision says
  so, and it is documented.

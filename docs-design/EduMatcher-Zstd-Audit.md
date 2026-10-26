# EduMatcher — Daily zstd Archives of the Audit Trail: Design and Workplan


At the end of every trading day the day's audit trail is compressed with
zstd into one archive, `audit-YYYY-MM-DD.log.zst`, and every audit reader
(`pm-audit-cli`, `pm-audit-replay`, `tools/sim_forensics`) reads archives as
seamlessly as plain files. To make "the whole day" well defined, `pm-audit`
itself closes the day: it stops writing a day's lines at the date change, so
nothing of a day is still being written when it is archived.

One work package (WP) at a time; each WP ends with a holistic test run
(`make _check` + the full test suite + `make test-e2e`), a review for new
insights, and a proposed commit message. The maintainer commits.

Started: 2026-10-25

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit)

| # | WP | Content | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|
| 1 | Z1 | Readers: `.zst` and the dated file layout in `audit/query.py`; stdlib `compression.zstd` | — | 0.5 d | ☑ | 2026-10-26 |
| 2 | Z2 | `pm-audit` closes the day: per-line date split, numbered day parts, no deletion | Z1 | 1 d | ☑ | 2026-10-26 |
| 3 | Z3 | `pm-audit-cli archive`: concatenate → verify → rename → delete, crash-safe | Z1, Z2 | 1 d | ☑ | 2026-10-26 |
| 4 | Z4 | Automatic archiving from `pm-audit`, start-up catch-up, retention, health metrics | Z3 | 0.5 d | ☑ | 2026-10-26 |
| 5 | Z5 | Replay and CLI scope: live trail by default, `--date`, archive paths, `--follow` across midnight | Z1, Z2 | 0.5 d | ☐ | |
| 6 | Z6 | Operations and docs: emo profiles and clean, deployments, operator guide, file formats | Z2–Z5 | 0.5 d | ☐ | |

Total ≈ 4 d. Z1 comes first so every reader understands archives before
anything writes one; Z2 before Z3 because only closed day parts can be
archived safely.

## Per-WP checklist

1. Re-read the WP below; check the named files/functions still exist.
2. Write the failing test first, then the change.
3. Holistic test: `make _check`, the full `pytest` suite with `-n logical`,
   `make test-e2e`, and `tools/verify_audit_trail.sh` for Z2–Z5.
4. Review: anything learned goes into the insights log and, if it changes a
   later WP, into that WP.
5. Mark the WP ☑ here, propose a commit message, stop.

## Open decisions

Recommended answers in **bold**; the WPs below assume them until decided.

| # | Question | Options | Affects |
|---|---|---|---|
| Q1 | When does a trading day end? | **Midnight in `locale.session_timezone`** (matches `pm-stats`' trading date; keeps the post-close end-of-day messages with their day) · on `session.state` → `CLOSED` | Z2 |
| Q2 | What does `pm-audit-replay` / `pm-audit-cli` read by default? | **The live trail: every not-yet-archived part plus `audit.log`**; archives only with `--date D` or an explicit path · everything, archives included | Z5 |
| Q3 | Retention of archives | **`--keep-days N`, default 0 = keep all** · fixed default (e.g. 30) · none | Z4 |
| Q4 | Where do day parts and archives live? | **`<data>/audit/`**, beside the active `<data>/audit.log` · beside `audit.log` | Z2, Z6 |

---

## 1. Current state (2026-10-25)

- **Writer.** `pm-audit` (`src/edumatcher/audit/main.py`) writes one line per
  message through a `logging.handlers.RotatingFileHandler`:
  `[<UTC ts>] [<topic>] [<meta>] {json}`. Lines are buffered (`--buffer-size`
  100, `--flush-interval` 10 s) and written by `_flush_buffer`, from the
  receive thread or a `threading.Timer`.
- **Rotation is by size only**: `--max-file-mb` (10) × `--backup-count` (5).
  On every rotation `audit.log.1` → `.2` → …, and the oldest is deleted.
- **Profiles.** emo's default `audit` entry runs `pm-audit --verbose`, i.e.
  10 MB × 5 = 60 MB kept. The ai-swarm profile runs `--max-file-mb 256
  --backup-count 100` (≈ 25 GB, "about two trading days at ~1.2 GB an hour",
  `emo/cli.py`).
- **Readers.** Every reader finds files with
  `audit/query.py:discover_log_files` (`audit.log.N[.gz]`, highest N first,
  then `audit.log`) and opens them with `_open_file` (plain, or gzip for
  `.gz` — a branch nothing writes today). Users: `audit/cli.py` (incl.
  `--follow`, which re-discovers each poll and tracks position by
  `(timestamp, skip)`, not offsets), `audit/indexer.py`,
  `audit/replay/cli.py`, and `tools/sim_forensics/audit.py`, which
  discovers through `query.py` but opens files itself (`path.open`).
- **Replay index.** `audit/replay/index.py:fingerprint` keys the episode
  index on `(path, size, mtime)` of the input files, so it rebuilds by
  itself when the file set changes.
- **Python.** `pyproject.toml` allows `^3.13`; the stdlib
  `compression.zstd` exists only from 3.14 (PEP 784).

## 2. Problems with the current layout

1. **A busy day loses its start before end of day.** Rotation deletes the
   oldest file as soon as `backup-count` is exceeded. With the default 60 MB
   that happens within the first hour or so of a simulated day; an EOD job
   cannot archive what is already gone.
2. **Files are not days.** A size-rotated file holds the end of one day and
   the start of the next, so "the day's files" does not exist.
3. **Names move.** Every rotation renumbers every backup; an external job
   that compresses `audit.log.3` can race a rename.
4. **The active file is never complete.** Copying `audit.log` at EOD misses
   up to 100 buffered lines (10 s), can cut the last line, and the copied
   part would be archived again with the next day.

## 3. Design

### 3.1 File layout

```
<data>/audit.log                        the active file: today's lines, being written
<data>/audit/audit-2026-10-25.1.log     closed parts of a day, numbered in write order,
<data>/audit/audit-2026-10-25.2.log     never renamed again once written
<data>/audit/audit-2026-10-24.log.zst   one archive per archived day
```

- A part is closed when `audit.log` reaches `--max-file-mb` or the day ends;
  it is renamed to the next free number for its date. Numbers only grow, so
  nothing is ever renumbered (problem 3).
- **Nothing is deleted by the writer** (problem 1). `--backup-count` goes
  away; disk use is governed by archiving (≈ 10× smaller) and retention
  (Q3). Old `audit.log.N` files from the previous layout are neither read
  nor migrated (no backwards compatibility).

### 3.2 Closing the day (Q1: midnight, session timezone)

The date of a line is the **session-timezone date of its receive
timestamp** — the `[ts]` pm-audit already stamps. The buffer keeps each
line's date beside it, and the writer splits on it: a line received at
23:59:59.990 and flushed at 00:00:05 still lands in the old day's part.
That makes the rule exact: *every line in `audit-D.*` was received on D*.

On the first line dated after the current file's date the writer: flushes
the old day's lines, closes `audit.log`, renames it to the old day's next
part number, opens a fresh `audit.log`, writes the new day's lines. All of
it happens inside `_flush_buffer` under `_buffer_lock`, so the timer thread
and the receive thread cannot interleave a rollover. A quiet day boundary
(no line for hours) is closed by the flush timer and on start-up, so an idle
exchange still archives yesterday.

Session timezone: from the compiled config's `locale.session_timezone`, as
`pm-stats` reads it (`load_compiled_config()`), default `Europe/Stockholm`.
Wall clock, not the simulation clock: audit timestamps are wall time even
under `pm-scheduler --speed`.

This replaces `RotatingFileHandler` with a small `AuditFile` writer class
(size + date rollover, no logging framework in the data path).

### 3.3 The archive

**One zstd stream per day: the day's parts concatenated in order**, not a
tar. The parts are consecutive slices of one line-oriented log, so their
concatenation *is* the day's log: `zstdcat audit-D.log.zst | grep …` works,
readers see one file, and `--show-source` line numbers are line numbers in
the day. A tar would add member boundaries nobody needs.

**Steps** (`pm-audit-cli archive --date D`), crash-safe at every point:

1. Refuse unless D is before today (session timezone): only closed days.
   Take an exclusive `fcntl` lock on `<data>/audit/.archive.lock`, so the
   automatic and a manual run never overlap.
2. Check free space ≥ 25 % of the parts' total size (zstd on this JSON is
   ≈ 10:1, Z3 measures it).
3. Stream the parts in number order into `audit-D.log.zst.part`, computing
   SHA-256 and the line count of the input as it goes. `fsync`.
4. Verify: stream-decompress the `.part`, compare SHA-256 and line count.
5. `rename` to `audit-D.log.zst`, `fsync` the directory.
6. Delete the parts.

A crash leaves the parts (before 5) or the archive plus parts (between 5 and
6); a re-run sees the archive, re-verifies it against the parts if any are
left, and deletes them. Never neither. A leftover `.part` is deleted and
redone.

**Level and speed.** ai-swarm writes ≈ 1.2 GB an hour, ≈ 10–14 GB a day.
zstd level 3 compresses JSON at several hundred MB/s on one core, so a day
takes about a minute; level 19 would take hours. Z3 measures levels 3, 9 and
12 on a real 256 MB part and fixes the default (`--level`), aiming for at
most ~1 min per GB.

**Library.** `compression.zstd` on 3.14, the `backports.zstd` package (same
API) on 3.13, behind one import in `query.py`.

### 3.4 Reading (Q2: the live trail by default)

- `_open_file` opens `.zst` with `zstd.open(path, "rt")` — streaming, so a
  14 GB day is never held in memory. The `.gz` branch goes.
- `discover_log_files` returns **the live trail**: unarchived parts ordered
  by (date, number), then `audit.log`. That is today plus any day not yet
  archived (pm-audit was down at midnight, an archive failed).
- `--date D` (both CLIs) reads that day: its archive if there is one, else
  its parts. An explicit path (`--log-file audit-2026-10-24.log.zst`) reads
  exactly that file.
- `--follow` needs no new mechanism: it re-discovers every poll and keys its
  position on `(timestamp, skip)`, so the midnight rename is invisible to it
  — Z5 proves it with a test.

### 3.5 Automatic archiving and retention (Q3)

`pm-audit` starts the archiver as a **child process** (`pm-audit-cli archive
--pending`, `nice` 10) right after closing a day, and once at start-up. A
child process keeps compression off the receive loop's GIL and CPU, and a
crash in it cannot take the recorder down. `--pending` archives every closed
day that has parts, oldest first, then applies `--keep-days`.

Health: `audit.archives` (counter), `audit.archive_errors` (counter),
`audit.archive_ratio` (gauge, last archive). A failed archive leaves the parts
in the live trail, where they are still readable, and logs an ERROR through
LALF.

---

## 4. Work packages

### Z1 — Readers understand `.zst` and the dated layout

- `audit/query.py`: zstd import shim (`compression.zstd` /
  `backports.zstd`); `_open_file` reads `.zst`; `discover_log_files` per
  §3.4 (parts by date and number, then `audit.log`); remove `.gz` and the
  `audit.log.N` patterns.
- `tools/sim_forensics/audit.py`: open through `query._open_file` (made
  public as `open_log_file`) instead of `path.open`.
- `pyproject.toml`: `backports.zstd` for `python < 3.14`.
- Tests: discovery order across two dates and several parts; a `.zst` file
  reads line for line like the plain one; `iter_entries`, the indexer and a
  replay `facts` run over a mixed set give the same events as over the plain
  files.

**Done when:** a hand-made `audit-D.log.zst` replays and queries exactly as
the same lines in plain parts.

### Z2 — `pm-audit` closes the day

- New `AuditFile` writer in `audit/main.py` (or `audit/writer.py`): size and
  date rollover per §3.1–3.2, rename to the next free part number, `fsync`
  on close. Replaces `RotatingFileHandler`.
- The buffer holds `(date, line)`; `_flush_buffer` splits on date; the flush
  timer and start-up close a day that ended while idle.
- Session timezone from the compiled config; `--max-file-mb` stays,
  `--backup-count` is removed (also from `pm_help/registry.py`).
- Tests: lines either side of midnight land in the right day even when one
  flush carries both; size rollover numbers parts 1, 2, 3 and never renames
  an existing one; idle midnight closed by the timer; restart after midnight
  closes yesterday's `audit.log`; a DST-change day; no line lost or
  duplicated under concurrent receive + timer (stress test).

**Done when:** a run across a (faked) midnight leaves `audit-D.1.log …` with
exactly the lines received on D, and the new `audit.log` with the rest.

### Z3 — `pm-audit-cli archive`

- Subcommand `archive [--date D | --pending] [--level N] [--keep-days N]`
  implementing §3.3 steps 1–6.
- Measure levels 3/9/12 on a real 256 MB part (ratio, MB/s compress and
  decompress); record in the insights log; set the default.
- Tests: archive of D round-trips byte for byte; refuses today; lock held →
  second run waits or exits cleanly; crash injected after each step (kill
  between steps via a hook) → re-run ends with exactly the archive and no
  parts; corrupt `.part` → redone; low free space → refused, parts kept.

**Done when:** `pm-audit-cli archive --date D` replaces D's parts with one
verified `.zst`, and every crash point recovers on re-run.

### Z4 — Automatic archiving from `pm-audit`

- After a day closes and at start-up, spawn `pm-audit-cli archive --pending`
  (`nice` 10), at most one at a time; reap it from the receive loop.
- `--keep-days` passed through from `pm-audit`'s own option.
- Metrics `audit.archives`, `audit.archive_errors`, `audit.archive_ratio`;
  add `audit.archive_errors` to pm-monitor's "any increase in 5 min" rules
  and to pm-dash's metric mirror if shown.
- Tests: rollover spawns the archiver once; a failing archiver increments
  the error counter and leaves the parts readable; retention deletes only
  archives older than N days, never parts.

**Done when:** an exchange left running across midnight has yesterday as one
`.zst` a minute or so later, with no gap in the receive loop's ticks.

### Z5 — Replay and CLI scope

- `--date D` on `pm-audit-replay` and `pm-audit-cli`; explicit archive paths
  accepted as `--log-file`.
- `pm-audit-cli stats --extended --verbose`: parts, archives, sizes and
  ratio instead of "rotated backups".
- Tests: default reads the live trail only; `--date` reads an archive or,
  before archiving, the parts; `--follow` across a rollover prints every line
  once; the replay index rebuilds after archiving (fingerprint changes) and
  gives the same episodes.

**Done when:** yesterday replays with `--date` from its archive, and today
replays by default, across a rollover, with no duplicated or missing event.

### Z6 — Operations and docs

- `emo/cli.py`: drop `--backup-count` from the profiles (ai-swarm keeps
  `--max-file-mb 256`, adds `--keep-days` per Q3); `emo clean --all` also
  removes `<data>/audit/`.
- Deployments: the docker data mount already covers `<data>/audit/`; check
  the VM image and `deployment/curl` installer notes.
- Docs: operator guide `020-audit-trail.md` (layout, day close, archive,
  retention, recovering a failed archive by hand), `030-audit-replay.md`
  (`--date`, archives), `010-persistence.md`; architecture
  `030-file-formats.md`; `pm_help` registry; `tools/verify_audit_trail.sh`
  reads through the new discovery.
- e2e: extend `tests/test_monitor_e2e.py` or add an audit e2e that runs
  `pm-audit` across a faked midnight and replays the archive.

**Done when:** docs describe the new layout, `mkdocs build` is clean, and the
e2e passes.

---

## Insights log

*(Append per WP: measurements, surprises, changes to later WPs.)*

**Z1 (2026-10-26).**
- Python 3.14 is now mandatory (`pyproject.toml` `^3.14`), so the
  `backports.zstd` shim and dependency are dropped everywhere: `query.py`
  imports `compression.zstd` directly. Z-WPs below need no 3.13 path.
- `discover_log_files` also skips the parts of a day that already has an
  archive (crash between rename and delete), so the live trail never repeats
  a line. Archives themselves are read by explicit path until Z5 adds `--date`.
- The indexer builds from the live trail only, so it does not index archives
  yet; Z5 must make `--date D` feed the archive to the indexer.
- `cli.py:_collect_log_stats` still counts non-active files as "rotated
  backups"; Z5 rewrites it.

**Z2 (2026-10-26).**
- Q1–Q4 taken as the recommended answers (Johan: "cont.").
- `AuditFile` lives in `audit/writer.py`, not `main.py`. It is a binary
  append-only writer that tracks its own size; `AuditProcess` owns the
  buffer of `(date, line)` and the session timezone (default UTC for
  tests; `main()` passes the compiled config's, as `pm-stats` does).
- The idle-midnight close runs from the receive loop once a second
  (`_close_ended_day`), not from the flush timer: the timer exists only while
  lines are buffered, so it never fires on a silent exchange. The same method
  runs at start-up. Z4 hooks the archiver spawn onto `AuditFile.roll` /
  `_close_ended_day`.
- The size check is after a batch write, so a part can exceed `--max-file-mb`
  by up to one flush (≤ `--buffer-size` lines).
- A line whose date is *earlier* than the file's (wall clock stepped back) is
  appended to the current file; only a later date closes it.
- `--backup-count` removed from `pm-audit`, emo profiles, `pm_help` and
  completions. Operator/reference docs still mention it: Z6.
- `tools/verify_audit_trail.sh` now clears and counts `audit/audit-*.log`.
  Verified end to end: 36510 lines, no findings.

**Z3 (2026-10-26).**
- **Level measurement** on three real 256 MB parts from `~/.edumatcher-sim/data`
  (oldest, middle, newest; ~380–410 k lines each; single core, in memory):

  | level | ratio | compress | decompress |
  |---|---|---|---|
  | 1 | 7.5:1 | ~610 MB/s | ~750 MB/s |
  | 3 | 9.5:1 | ~475 MB/s | ~780 MB/s |
  | 9 | 13.4:1 | ~140 MB/s | ~885 MB/s |
  | 12 | 13.7:1 | ~70 MB/s | ~910 MB/s |

  Level 12 buys 2 % over 9 for half the speed, so **`--level` defaults to 9**.
  A 14 GB day then takes ≈ 100 s to compress. End to end through
  `archive_day` (read, hash, compress, verify): 512 MB → 37.7 MB (13.6:1) in
  8 s, i.e. ≈ 16 s/GB, well inside the ~1 min/GB aim. The external `zstd`
  CLI decodes the archive to the same bytes. A day of ~10–14 GB becomes
  ≈ 1 GB.
- The 25 % free-space rule is therefore very conservative (needs ~8 %); kept
  as is.
- Logic is in `audit/archive.py`; the CLI is a thin wrapper. Crash tests use an
  `on_step` hook that raises after "compressed", "verified", "renamed",
  "deleted".
- An archive found next to parts is re-verified against them; if it does not
  match (stale or truncated) it is deleted and made again from the parts,
  which are the source of truth.
- A held lock makes `archive` print a note and exit 0 (the other run does the
  work); a failed day exits 1. `--pending` carries on with the next day after
  a failure.
- `session_timezone()` moved into `archive.py`; `pm-audit` uses it too, so the
  config lookup now exists once in the audit package (pm-stats still has its
  own copy).
- Z4: `ArchiveResult.ratio` feeds `audit.archive_ratio`; spawn
  `pm-audit-cli archive --pending --keep-days N`.

**Z4 (2026-10-26).**
- `AuditFile` takes an `on_day_closed` callback, fired only when a roll closes
  an *ended day* (a later-dated line, or the idle/start-up close), not on a
  size roll: parts of today are not archivable. `AuditProcess` only sets a flag
  from it (it runs under the buffer lock, possibly on the timer thread); the
  **receive thread** spawns and reaps, in the once-a-second day check, so the
  child is never started from a foreign thread.
- Start-up catch-up is requested in `run()`, not `__init__`, so constructing an
  `AuditProcess` in tests never starts a process.
- One archiver at a time. A day that closes while one runs sets the flag again;
  the run after it picks the day up, since `--pending` takes every closed day.
- The child is `nice -n 10 python -m edumatcher.audit.cli --log-file <log>
  archive --pending --keep-days N` (`sys.executable`, so the venv is used).
  `preexec_fn` was avoided: pm-audit has timer threads.
- The ratio reaches pm-audit through the child's result line:
  `archive.format_result` writes it, `parse_ratio` reads it back. A non-zero
  exit counts one `audit.archive_errors` and is logged at ERROR with the child's
  stderr; a child that cannot be started counts the same.
- A pm-audit shutdown does not kill a running archiver: it is crash-safe and
  finishes (or the next start-up re-runs it).
- Monitor: `audit.archive_errors` is in `WATCHED_INCREASES`
  (`audit_archive_errors`), mirrored in dash-gui's `FIXED_RULES`; the health
  contract test now lists pm-audit as its owner. Docs for the new rule:
  Z6 (operator guide `060-health-monitor.md`, dashboard design).
- `make test-e2e` target name: it exists; the earlier failure was run from
  the wrong directory after a vitest call.

# pm-audit / pm-audit-cli Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/audit/` at `649ed534` (v0.78.4), excluding
`replay/`: `main.py` (734 lines, pm-audit), `writer.py` (201),
`archive.py` (307), `manifest.py` (209), `rawlines.py` (122), and
pm-audit-cli's `cli.py` (1 247), `query.py` (930), `indexer.py` (334),
`formatters.py` (177). `rawlines.py` is shared with pm-audit-replay and
pm-sim-forensics; `indexer.py` is also read by pm-api-gwy
(`GET /admin/orders/{order_id}/audit`).

**Focus:** correctness, edge-case handling, and whether the comments and
help texts are correct and helpful.

**Previous work:** `EduMatcher-Zstd-Audit.md` (archives, manifest),
`EduMatcher-Audit-Completeness-Workplan.md` (A1–A9) and the zstd audit
review of 2026-10-26. Their fixes are in place and are not repeated here.

**Method:** every line of the files above was read. Findings marked
*(repro)* were reproduced with a scratch script against the tree at
`649ed534`; the others are by inspection, with line numbers given.

Status: **Open.** No WP started.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (CLI output, file contents, exit code, metric).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_audit_*.py` (and
   `tests/test_api_gateway_admin_views.py` for index WPs) with
   `-n logical`, then black/flake8/mypy/pyright. Do not start the next WP
   with a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-AUD01 | `file_day` reads the stamp, not the mtime | C2, D9 | — | 0.25 d | ☐ | |
| 2 | WP-AUD02 | `orders` view and summaries match the wire spec | C6 | — | 0.5 d | ☐ | |
| 3 | WP-AUD03 | `--follow`: no repeats, filters and range honoured, cheap polls | C3, C4, P1 | Q2 | 1 d | ☐ | |
| 4 | WP-AUD04 | Recorder robustness: a dead receive loop ends the process; write errors counted | C5, C7, C13, P2, D10 | Q3 | 1 d | ☐ | |
| 5 | WP-AUD05 | SQLite index: no duplicates, no silent staleness | C1, C10, D7 | Q1 | 1 d | ☐ | |
| 6 | WP-AUD06 | `verify` reports, never crashes, never hides | C8, C9 | — | 0.25 d | ☐ | |
| 7 | WP-AUD07 | Small items | C11, C12, P3 | — | 0.5 d | ☐ | |
| 8 | WP-AUD08 | Comments, docstrings, help texts, operator guide | D1–D8 | WP-AUD01–07 | 0.5 d | ☐ | |

Suggested order: **WP-AUD01 → WP-AUD02 → WP-AUD06 → WP-AUD04 → WP-AUD03 →
WP-AUD05 → WP-AUD07 → WP-AUD08**. WP-AUD01, 02 and 06 are small, isolated
and fully specified. WP-AUD04 is the recorder itself and should land before
the next long simulation run. WP-AUD03 and WP-AUD05 wait for decisions Q2
and Q1. WP-AUD08 goes last so every text describes the code as it ends up.

Estimated sequential effort: about 5 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The **write side** is sound. The archive pipeline (compress → verify →
rename → record → delete) is crash-safe at every step, the leftover-tail
detection after a crash mid-delete is right, the manifest's torn-line
handling agrees between `_append` and `verify`, the lock serialises the
automatic and manual archivers, and the recorder splits a flush at the date
change and drains to `system.eod` on shutdown.

The defects sit in three places:

- **One parsing slip with wide reach (C2).** `file_day` skips one comment
  line, but a fresh recorder writes two, so the session date of most
  `audit.log` files comes from their mtime. pm-audit's restart, `archive` and
  `--date` all trust it.
- **The read side's convenience features (C1, C3, C4, C6).** The SQLite
  index duplicates on rebuild and is auto-used however stale it is (and
  pm-api-gwy serves it); `--follow` repeats rows under a filter and forgets
  `--from`/`--to`; the `orders` view shows the gateway id as the event and
  the wrong price for fills.
- **The recorder's failure mode (C5).** An exception that escapes the
  receive loop leaves pm-audit running but recording nothing.

Severity key: **Med** — a wrong or missing answer, or a recorder that stops
recording without exiting; **Low** — hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| C1 | Med | Index | `index` without flags appends every line again; `events` auto-uses any existing index however stale; the index path's summary, gateway filter and error handling differ from the JSONL path; pm-api-gwy's order-lifecycle endpoint serves the same duplicates and staleness *(repro)* | AUD05 |
| C2 | Med | Writer | `file_day` skips one `#` line; a file begun by a fresh recorder has two (header, recorder-start), so the date falls back to `st_mtime` *(repro)* | AUD01 |
| C3 | Med | Follow | Tie skipping counts unfiltered lines while the CLI counts filtered rows: with a filter, the last row is reprinted every poll *(repro)* | AUD03 |
| C4 | Med | Follow | Polls drop `--from`/`--to`; with an empty first batch, the first poll prints the trail from its start *(repro)* | AUD03 |
| C5 | Med | Recorder | `run()` waits on `_running` only; a receive thread killed by an uncaught OSError/ZMQError leaves the process alive and deaf. The EINTR branch `break`s out of the loop while `_running` is still True | AUD04 |
| C6 | Med | Orders view | `event` is the last topic segment, i.e. the gateway id on every `order.*.{gateway_id}` topic; fills show the limit price; acks show no qty; `order.new` shows no price (it carries only `price_ticks`). `indexer.event_type` has the same split *(repro)* | AUD02 |
| C7 | Low | Recorder | A write error on the receive path is logged as "failed to decode" and counted in `audit.decode_errors`; a two-day flush that fails on the second day rewrites the first on retry | AUD04 |
| C8 | Low | Verify | A manifest line that is valid JSON but not an object crashes `_handle_verify` (`AttributeError`), and is reported as "not valid JSON" *(repro)* | AUD06 |
| C9 | Low | Verify | A day whose current manifest entry is `day`, with its archive gone, passes whenever any part of that day exists | AUD06 |
| C10 | Low | Index | `--incremental` resumes at last stamp + 1 µs; stamps have ms precision, so lines in the last indexed millisecond flushed after the build are never indexed | AUD05 |
| C11 | Low | rawlines | Without `chain=` in the meta section, `rfind` returns −1 and `chain` is `meta[5:]` (garbage) rather than `""` | AUD07 |
| C12 | Low | CLI | `--from`/`--to` take a bare date as UTC midnight while `--date` is a session-timezone day; `--to 2026-07-08` excludes that day; the help says neither | AUD07 |
| C13 | Low | Recorder | `_archive_wanted` is cleared before the child runs; if a manual `archive --date` holds the lock, a newly closed day waits for the next close or restart | AUD04 |
| P1 | Low | Follow | Every poll re-runs regex + `json.loads` on every line of the live trail before comparing timestamps | AUD03 |
| P2 | Low | Recorder | Two `threading.Timer` OS threads per `--buffer-size` batch; `_last_flush_time` is written and never read | AUD04 |
| P3 | Low | Query | `events --reverse` (and `trades --reverse`) materialise every matching entry before slicing | AUD07 |
| D1–D10 | — | Comments | See §5 | AUD08 (D7: AUD05, D9: AUD01, D10: AUD04) |

---

## 3. Correctness findings

### C1. The SQLite index duplicates and goes stale silently *(repro)* — Med

`indexer.py:144` `build_index`, `cli.py:630` `_handle_events`,
`api_gateway/routers/admin.py:995` `GET /admin/orders/{order_id}/audit`.

- **Duplicates.** With neither `--rebuild` nor `--incremental`,
  `build_index` deletes nothing and sets no lower bound: it inserts the
  whole live trail again. Reproduced: two `build_index` calls on a 2-line
  log leave 4 rows. The help calls the command "Build or update".
- **Silent staleness.** `_handle_events` uses the index whenever
  `index_is_available` is true. Nothing compares `last_indexed_timestamp`
  with the trail, so after one `pm-audit-cli index` every later `events`
  query misses everything recorded since, without a word. The design doc
  lists "Index staleness detection" as future work (§954).
- **Divergent output.** On the index path `summary` is `str(p)[:80]` (a
  Python dict repr), not `_summarise`; `--gateway` matches `gateway_id`
  only, so a trade's seller gateway is not found (the JSONL path checks
  `buy_gateway_id`/`sell_gateway_id`); any exception is swallowed by
  `except Exception: pass` and the JSONL path answers instead.
- **pm-api-gwy.** The admin order-lifecycle endpoint reads the same index:
  it returns each event twice after a second plain `index` run, and
  `404 UNKNOWN_ORDER` for any order newer than the last build. The 404 cannot
  tell "not indexed yet" from "no such order".
- **Help text (D7).** `--use-index` says "Auto-detected from --log-dir" and
  `index --output` says `<log-dir>/audit_index.db`; both use
  `log_file.parent` (`cli.py:612`, `cli.py:866`).

### C2. `file_day` reads the mtime for most fresh files *(repro)* — Med

`writer.py:35-54`. The function skips one leading `#` line, then parses the
stamp of the next one. `AuditFile.write` prepends the recorder-start marker
and then the header (`writer.py:123-127`), so a file begun by a freshly
started recorder opens with **two** comment lines. The marker has no `]`,
`first.index("]")` raises `ValueError`, and the `except` falls back to
`st_mtime`.

Reproduced: a file whose only line is stamped `2026-11-10T23:59:59`, with
mtime `2026-11-11T00:00:05`, gives `file_day` → `2026-11-11`.

Who trusts it:

- `AuditFile.__init__` (`_day` at pm-audit start, hence
  `close_days_before` in `AuditProcess.__init__`): a wrong later date keeps
  yesterday's lines in today's file and they are archived under today.
- `_handle_archive` (`open_day`, hence which days may be archived).
- `discover_day_files` (`--date`: whether `audit.log` belongs to the day).

In a running recorder the mtime is close to the stamp, so this mostly shows
after a shutdown just past midnight, or after anything rewrites mtime: a
`cp` without `-p` of a data directory, a restore from backup, `touch`. The
docstring ("the first line after the header names it") is wrong for the
same reason (D9).

### C3. `--follow` reprints the last row under a filter *(repro)* — Med

`query.py:440-448`, `cli.py:831-845`. `_run_follow` sets `after_skip` to
the number of **printed** rows sharing the last timestamp. `iter_entries`
applies it to **every parsed line** at that timestamp, before the topic,
gateway and symbol filters. Lines share a millisecond routinely
(`order.new`, `order.ack.*`, `book.*`, `trade.executed` of one command).

Reproduced: an `order.new` and a `trade.executed` at the same ms;
`events --topic trade. -f` prints the trade, then each poll skips the
`order.new` (the first tie) and returns the trade again. With no newer
trade, the same row is printed every interval.
`test_audit_cli.py:470` tests ties without a filter, so it passes.

### C4. `--follow` polls forget `--from`/`--to` *(repro)* — Med

`cli.py:776-812`. `_follow_fetch` passes neither bound. When the first
batch had rows, `after_ts` stands in for `--from`; when it was empty,
`after_ts` is None and the first poll returns the trail from its start (up
to 10 000 rows). `--to` is ignored on every poll.

Reproduced with the design doc's own example
(`timeline --from <later than every line> --follow`): it printed
"No matching events found.", then on the first poll every older line.

### C5. A dead receive loop leaves pm-audit running — Med

`main.py:641`: `while self._running: t.join(timeout=_JOIN_POLL_SEC)`. The
main thread only leaves when `_running` turns False. These paths raise out
of `_receive` and end the daemon thread, with `_running` still True:

- `_close_ended_day` → `_flush_locked` → `AuditFile.write` (OSError: disk
  full, EIO). Only the roll is guarded (`_try_roll`).
- `self._file.sync_if_due()` (`main.py:564`, fsync).
- `tempfile.TemporaryFile` in `_service_archiver` (`main.py:485`), outside
  the `try` that guards `Popen`.
- `poller.poll` raising a ZMQError other than EINTR (`main.py:555`).

Afterwards the health beacon (ticked on that thread) and the ZMQ ping stop,
but the process neither records nor exits, so nothing restarts it. The
traceback goes to `threading.excepthook` (stderr), not to pm-log-srv.

Related (D10): the EINTR branch (`main.py:556`) says "honour _running flag"
but `break`s unconditionally, which leaves the loop with `_running` still
True and takes the same path. PEP 475 and pyzmq retry EINTR, and signals
are delivered to the main thread, so it is nearly unreachable; it should be
`continue` all the same.

### C6. The `orders` view mislabels events and prices *(repro)* — Med

`query.py:623-648`, `query.py:546-592`, `indexer.py:113-115`.

- `"event": entry.topic.split(".")[-1]`: on `order.ack.TRADER01`,
  `order.fill.*`, `order.cancelled.*`, `order.expired.*`,
  `order.triggered.*`, `order.amended.*` this is the gateway id. Reproduced:
  the column reads `TRADER01` for an ack and a fill. `split_topic()` in the
  same module already resolves topics against the registry.
  `indexer._entry_to_row`'s `event_type` uses the same split, so
  `idx_event_type` indexes gateway ids.
- `"price": p.get("price") or p.get("fill_price")`: `order_fill` carries
  both (`price` is the order's limit), so a fill shows the limit price.
  Reproduced: 10.0 shown for a fill at 9.5.
- `"qty"` reads `quantity`, `fill_qty`, `remaining_qty`; `order_ack` and
  `order_amended` carry `qty`, so an ack shows nothing and an amend shows
  the remaining quantity.
- `order.new` carries `price_ticks` + `tick_decimals` and no `price`, so
  both the `orders` price column and `_summarise` (`query.py:567`,
  `"LIMIT BUY 100@"`) are blank for it.
- `_summarise` for an ack prints `status`, which `order_ack` does not have;
  `accepted` is the field.

### C7. Write errors are counted as decode errors — Low

`main.py:567-592`. `_add_to_buffer` may flush; an OSError from
`AuditFile.write` lands in the `except Exception` meant for decoding: it is
logged "failed to decode/log message" and counted in `audit.decode_errors`.
There is no write-error metric for the dashboard. `_flush_locked` writes
one `groupby` group per day and clears the buffer only at the end, so if the
second day's write fails, the first day's lines are written again on the
next flush.

### C8. `verify` crashes on a non-object manifest line *(repro)* — Low

`verify` rejects a line that parses to a non-dict, but `read_entries`
(`manifest.py:58`) returns it, and `_handle_verify` (`cli.py:1153`) calls
`e.get` on it. Reproduced with a manifest of `[1]`: the `[FAIL]` line is
printed, then `AttributeError`. `record_day`/`record_retired` go through the
same `_current(read_entries(...))` and would crash the archiver the same
way. The message says "not valid JSON" for valid JSON that is not an
object.

### C9. `verify` can hide a missing archive — Low

`manifest.py:192-195`. If the current entry for a day is `day` and its
archive is missing, the problem is reported only when the day has no parts.
A manifest `day` entry is written only after the archive is renamed into
place, and only retention (which records `retired` first) deletes an
archive. No legitimate sequence reaches "entry, no archive, parts", so the
exemption only hides a deleted archive whose day was reopened. Nothing
explains it.

### C10. Incremental index drops lines of the last millisecond — Low

`indexer.py:198-208`. The lower bound is `last_indexed_timestamp + 1 µs`.
Stamps have millisecond precision, and the recorder flushes in batches, so
the file seen by one build can end in the middle of a millisecond. Lines of
that millisecond flushed afterwards fall below the bound for ever.

### C11. `rawlines.lines` mis-parses a line without `chain=` — Low

`rawlines.py:89`: `meta[meta.rfind("chain=") + 6 :]` is `meta[5:]` when
`chain=` is absent. Every envelope sets `correlation_id` (a root uses its
own id), so only a line with a sequence but no envelope is affected; its
chain becomes a unique garbage string, not `""`. Consumers: the re-run
(`replay/rerun.py:779-828`) and sim-forensics.

### C12. Time-range options are inconsistent — Low

`parse_ts` takes `YYYY-MM-DD` as UTC midnight. `--date` (since the
day-scope work) means a trading day in the session timezone, read from its
files. So `--from 2026-07-08 --to 2026-07-08` matches only `00:00:00.000`
UTC, and `--to 2026-07-08` excludes that day. Neither help text says that
a bare date is UTC midnight or that `--to` is inclusive of an instant, not
a day. `date_to_range` and the `date_str` parameters of `query_*` and
`_where_clauses` are now reached only by tests (the CLI clears `args.date`
before querying).

### C13. A busy lock postpones the automatic archive — Low

`main.py:480-481` clears `_archive_wanted` before starting the child. If
the child finds the lock held (a manual `archive --date X`), it prints
"nothing done" and exits 0, and the day that just closed waits for the next
close or restart. Nothing is lost (parts stay in the live trail), but
`audit.archives` lags. Re-arming `_archive_wanted` when the child's output
says the lock was busy is enough.

---

## 4. Performance findings

### P1. `--follow` re-parses the whole live trail every poll — Low

`iter_entries` runs `_LINE_RE` and `json.loads` on each line before the
`after_ts` comparison. The live trail is every unarchived part plus
`audit.log`; on a simulation day that is hundreds of MB, parsed once per
second. The timestamp is the first bracket, so a prefix comparison on the
raw line can skip older lines without parsing them. Remembering the file
and byte offset of the last poll would avoid re-reading at all, but the
current design (re-discover each poll, to survive rolls) is simpler, and
the prefix check removes most of the cost.

### P2. One OS thread per flush timer — Low

`_schedule_flush` creates a `threading.Timer` (an OS thread) after every
size flush and again on the first line of the next batch: about two per
`--buffer-size` lines (default 100). The receive loop already wakes every
300 ms (`_POLL_TIMEOUT_MS`); comparing `_last_flush_time` (written at
`main.py:418`, never read) with `flush_interval` there removes the timer,
its cancel race at shutdown, and the second thread touching the buffer.

### P3. `--reverse` holds every match in memory — Low

`query_events` builds `list(iter_entries(...))` of `AuditEntry` objects
(each with its payload dict) for `--reverse`; `query_trades` keeps every
row. `collections.deque(maxlen=limit)` bounds both.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `main.py:8-11` | The format example has no meta section and no UTC offset (`isoformat` writes `+00:00`), and calls the line "a single JSON line". |
| D2 | `query.py:1-5` | "Audit log JSONL parser"; example without meta. |
| D3 | `cli.py:1-36`, `cli.py:204-207` | "Reads the JSONL log files"; the command list omits `verify`. |
| D4 | `main.py:30-31` | "only --keep-days ever deletes anything": archiving deletes the day parts after verifying the archive. |
| D5 | `cli.py:791-793` | "matching the cap query_timeline already uses": `query_timeline`'s default is 500. |
| D6 | `archive.py:205-207` | The `on_step` list omits `"recorded"`. |
| D7 | `cli.py:249-253`, `cli.py:446` | `--use-index` "Auto-detected from --log-dir", `index --output` "<log-dir>/…": both use `log_file.parent` (fixed with C1). |
| D8 | `cli.py:243`, `cli.py:652` | `--no-header` says "for csv output" but applies to `table` too; `import json as _json` inside the loop although `json` is imported at module level. |
| D9 | `writer.py:36-39` | "the first line after the header names it" (fixed with C2). |
| D10 | `main.py:556` | "EINTR — honour _running flag" above an unconditional `break` (fixed with C5). |

Also for WP-AUD08: the operator guide's audit chapters
(`part-6-observe-and-recover/020-audit-trail.md`, `080-index-administration.md`,
`050-api-gateway.md` troubleshooting row) must describe the index as
decided in Q1 and `--follow` as decided in Q2.

---

## 6. Verified as correct

- **Archive pipeline.** Compress → fsync → verify (sha + line count of the
  decompressed `.part`) → rename → fsync dir → record → delete. A crash at
  any step leaves either the parts or the archive plus parts; the
  `_archive_ends_with` tail check finishes an interrupted delete, and a
  reopened day is appended to its archive rather than replacing it.
- **Manifest.** `_append` ends a torn last line before appending and chains
  to the torn line's hash; `verify` computes `expected` the same way, so a
  torn line is reported once and does not cascade.
- **Lock.** `flock(LOCK_EX | LOCK_NB)` on `.archive.lock`; both the child
  and a manual run take it; retention runs inside it and records `retired`
  before unlinking.
- **Day split.** `_flush_locked` writes one `groupby` group per day; the
  1-second day check flushes an ended day's buffered lines before
  `close_days_before`, so they do not reopen the closed day.
- **fsync throttle.** `sync_due` is safe to read without the lock and
  `sync_if_due` runs under it; `roll` and `close` always fsync.
- **Shutdown.** `_drain` reads until `system.eod` or 5 s; `run()` joins for
  6 s, cancels the timer, flushes, closes.
- **Sequence accounting.** `_note_eseq` counts gaps as missed and a
  non-startup decrease as a discontinuity; a restart (`system.startup`) is
  neither.
- **Health process match.** `find_process_pids("pm-audit")` matches the
  whole word, so it does not count `pm-audit-cli` or `pm-audit-replay`.

---

## 7. Decisions

Open; recommendations given.

| # | Question | Recommendation |
|---|---|---|
| Q1 | The index is built by hand and read by `events` (auto) and by pm-api-gwy. How should staleness be handled for 1.0? | `index` with no flag rebuilds from scratch (drop `--rebuild`), `--incremental` appends. pm-audit-cli uses the index only with an explicit `--use-index` and prints its `last_indexed_timestamp` to stderr when it does. pm-api-gwy adds `indexed_through` to the lifecycle response and to the 404 message. Keeping the index current inside pm-audit is 1.x. |
| Q2 | `events`/`timeline --follow` start with the **oldest** `--limit` rows of the trail and then catch up 10 000 rows per poll. Keep the backfill-from-start, or start like `tail -f`? | Start like `tail -f`: the first batch is the **last** `--limit` matching rows (or the rows after `--from` when given), then new rows only. That is what "watch for new events" suggests, and it removes the catch-up flood. |
| Q3 | When the receive loop dies (C5), should pm-audit keep going or exit? | Both, in order. Catch OSError around the flush and sync calls in the loop: count it in a new `audit.write_errors`, log ERROR, keep the lines buffered, and retry on the next tick. Anything that still escapes ends the process with exit status 1 (`run()` also checks `t.is_alive()`), so a supervisor restarts it and the gap is marked by the recorder-start line. |

---

## 8. Work packages

Each WP lists the tests to write first, the production change, and the exit
criteria. Test files are existing ones unless marked new.

### WP-AUD01 — `file_day` reads the stamp (C2, D9)

**Goal.** The session date of an audit file comes from its first entry's
stamp, whatever comment lines precede it; mtime only for a file whose first
entry is unparseable.

**Tests first** (`tests/test_audit_writer.py`):

1. `AuditFile(..., announce_start=True)` writes one line stamped day D;
   `os.utime` sets mtime to D+1; `file_day` returns D. Fails today with D+1.
2. A file holding header, recorder-start, a second recorder-start and an
   entry: still the entry's day.
3. A file of comment lines only: `None` (it holds no day).
4. `AuditProcess` restart: `audit.log` holds day-D lines with the marker,
   mtime D+1, now D+1: the constructor closes it as `audit-D.1.log`
   (`tests/test_audit_main_runtime.py`).
5. `_handle_archive` with that `audit.log`: day D is not archived
   (`open_day` is D) (`tests/test_audit_archiver.py`).

**Change.** Skip every leading line that starts with `#`; return `None`
when no entry follows. Fix the docstring.

**Exit criteria.** Tests 1–5 pass; `tests/test_audit_*.py` green.

### WP-AUD02 — `orders` view and summaries match the spec (C6)

**Goal.** Every column of `orders`, and `events`' summary, reads the field
the wire spec defines for that topic.

**Tests first** (`tests/test_audit_cli.py`), one line per topic built from
the spec's field names:

1. `orders`: `event` is `ack`, `fill`, `cancelled`, `expired`, `triggered`,
   `amended`, `new`, `cancel` for the respective topics, never a gateway id.
2. A fill with `price=10.0, fill_price=9.5, fill_qty=5`: price 9.5, qty 5.
3. An ack with `qty=5, price=10.0`: qty 5; an amend with `qty=7,
   remaining_qty=3`: qty 7.
4. An `order.new` with `price_ticks=1234, tick_decimals=2`: price `12.34`
   in `orders` and in the `events` summary (`LIMIT BUY 100@12.34`).
5. An ack with `accepted=false, reject_code=…`: the summary says rejected
   and shows the code; with `accepted=true`, accepted.
6. `indexer`: `event_type` of `order.fill.TRADER01` is `fill`
   (`tests/test_audit_cli.py`, index section).

**Change.** Derive the event from `split_topic(topic)[0]`'s last segment
in both `query_orders` and `_entry_to_row`. Per-topic field selection
(`fill_price`/`fill_qty` for fills, `qty` for ack/amend, tick price for
`order.new` via `tick_decimals`) in one helper used by `query_orders` and
`_summarise`.

**Exit criteria.** Tests 1–6 pass; `orders --id X` on a simulation trail
shows one readable lifecycle.

### WP-AUD06 — `verify` reports, never crashes, never hides (C8, C9)

**Tests first** (`tests/test_audit_manifest.py`):

1. Manifest line `[1]` between two valid entries: `verify` returns one
   chain problem ("not a JSON object"), `pm-audit-cli verify` exits 1 with
   no traceback, and `record_day` still appends.
2. A `day` entry, the archive deleted, a part of that day present: the
   problem "archive is missing (not retired)" is reported.
3. Existing tests for the crash-between-rename-and-delete case still pass
   (the archive exists there, so test 2 does not touch them).

**Change.** `read_entries` keeps dicts only; the message distinguishes
"not valid JSON" from "not a JSON object"; drop the parts exemption at
`manifest.py:193`.

**Exit criteria.** Tests pass; `tests/test_audit_archive*.py` green.

### WP-AUD04 — Recorder robustness (C5, C7, C13, P2, D10; after Q3)

**Goal.** pm-audit never keeps running while not recording; a write error is
visible as one, and no line is written twice.

**Tests first** (`tests/test_audit_main_runtime.py`):

1. `AuditFile.write` raising `OSError(ENOSPC)` once from the day-check
   flush: the loop survives, `audit.write_errors == 1`,
   `audit.decode_errors == 0`, and after the error clears every line is in
   the file exactly once.
2. A two-day buffer whose second-day write fails once: after the retry each
   line appears exactly once.
3. An exception that escapes `_receive` (patch `poller.poll` to raise a
   non-EINTR `ZMQError`): `run()` returns promptly and `main()` exits 1.
4. `tempfile.TemporaryFile` raising: counted in `audit.archive_errors`, loop
   alive.
5. The archiver child reports the lock busy: `_archive_wanted` is set again
   and a later tick starts a new child.
6. Flush by interval without timers: with `flush_interval=0.2` and one
   line, the line is on disk within 0.5 s, and no `threading.Timer` is
   created (patch it to fail).

**Change.** Remove the timer; flush in the loop when the buffer is
non-empty and `flush_interval` has passed since `_last_flush_time`. Move
the flush and size checks out of `_receive_one_message` so its `except`
covers decoding only. `_flush_locked` drops each day group from the buffer
once written. Wrap the per-tick flush, sync, day check and archiver service
in `except OSError` → `write_errors`/`archive_errors` + ERROR log.
`run()` loops `while self._running and t.is_alive()`, and `main()` exits 1
when the thread died. EINTR → `continue`. Re-arm `_archive_wanted` on a
busy child (the child prints a recognisable line; match it next to
`parse_ratio`). Add `audit.write_errors` to `metric_samples` and to the
dashboard spec if the audit tile lists metrics.

**Exit criteria.** Tests 1–6 pass; `tests/test_audit_*.py` and
`tests/test_monitor*` green; a 10-minute simulation run shows the same
`audit.records` as before and no `decode_errors`.

### WP-AUD03 — `--follow` (C3, C4, P1; after Q2)

**Tests first** (`tests/test_audit_cli.py`, `TestCliFollow`):

1. `order.new` and `trade.executed` at the same ms; `events --topic trade.
   -f`, three polls with no new line: the trade is printed once. (Fails
   today.)
2. The same with `--gateway` and `--symbol` filters.
3. `timeline --from <after every line> -f`, one poll with no new line:
   nothing but the empty-result message; a line appended after `--from` is
   printed on the next poll; a line before it is not. (Fails today.)
4. `timeline --to T -f`: a line appended after T is not printed.
5. Per Q2: a 500-line trail, `events --limit 10 -f`: the first batch is the
   last 10 lines.
6. P1: a poll over a 10 000-line file whose lines all precede `after_ts`
   calls `json.loads` zero times (patch to count).

**Change.** Resume position becomes "(timestamp, number of **matching**
entries at it)": count ties after the filters in `iter_entries`.
`_follow_fetch` passes `from_dt`/`to_dt`. In `iter_entries`, compare the
raw stamp (`raw[1:raw.find("]")]`) with `after_ts` and the range bounds
before `parse_line`. First batch per Q2 (tail with a bounded deque, P3's
helper).

**Exit criteria.** Tests 1–6 pass; `events -f` on a simulation trail uses
under 5 % CPU between bursts.

### WP-AUD05 — SQLite index (C1, C10, D7; after Q1)

**Tests first** (`tests/test_audit_cli.py`, index section;
`tests/test_api_gateway_admin_views.py`):

1. `index` twice: row count equals the line count. (Fails today.)
2. `index --incremental` after lines are appended in the last indexed
   millisecond: every line indexed exactly once. (Fails today.)
3. Per Q1: with `audit_index.db` present and no `--use-index`, `events`
   reads the JSONL trail (a line appended after the build is shown).
4. With `--use-index`: the summary column equals the JSONL path's;
   `--gateway SELLER` finds the trade; the index age is printed on stderr;
   a corrupt index exits 1 with a message instead of falling back silently.
5. pm-api-gwy: the lifecycle response carries `indexed_through`; the 404
   message names it.

**Change.** Default build = clear and rebuild; `--incremental` keyed on
the last indexed timestamp **inclusive**, de-duplicated against the rows
already at that timestamp (the index stores `file`/`line_no` or a
uniqueness key per line, e.g. `UNIQUE(timestamp, msg_id)`, with
`INSERT OR IGNORE`). Map index rows through `_summarise`; match
`gateway_id` or the payload's buy/sell gateway. Remove auto-detection and
the bare `except`. Fix the two help texts (D7).

**Exit criteria.** Tests 1–5 pass; api-gwy admin tests green.

### WP-AUD07 — Small items (C11, C12, P3)

**Tests first:**

1. `rawlines.lines` on `[ts] [t] [seq=1 eseq=2 msg=X] {}`: `chain == ""`
   (`tests/test_audit_replay_reader_limits.py` or a new
   `tests/test_audit_rawlines.py`).
2. `--to 2026-07-08` includes the whole of that UTC day; or, if the help is
   changed instead, the help says so (decide in the test; recommend
   "a bare date in `--to` means the end of that day").
3. `events --reverse --limit 5` over 100 000 lines keeps memory bounded
   (assert on the deque's size via a patched constructor, not on RSS).

**Change.** `chain = meta[i + 6:] if (i := meta.rfind("chain=")) >= 0 else ""`.
`parse_ts` gains an `end_of_day` flag for `--to`. `deque(maxlen=limit)`
in `query_events` and `query_trades`. Remove `date_to_range` and the dead
`date_str` parameters if no test needs them beyond their own.

**Exit criteria.** Tests pass; `tests/test_audit_*.py` green.

### WP-AUD08 — Comments, docstrings, help texts (D1–D8)

**Change.** Fix D1–D6 and D8 as listed in §5; update the operator guide
chapters named in §5 for Q1/Q2; make sure `pm-audit-cli --help` and each
subcommand's help match the guide.

**Exit criteria.** `mkdocs build` clean; a reread of every module docstring
in `src/edumatcher/audit/*.py` against the code finds nothing stale.

---

## 9. Out of scope, noted

- `health -q` exits with `-1` (status 255) where the non-quiet path exits 1.
  The same pattern is in `clearing/cli.py`, `index/cli.py` and
  `stats/cli.py`; recorded as L017 in `EduMatcher-For-Later-ToDo.md`.
- The recorder re-encodes each payload with `json.dumps` after decoding it;
  the trail holds an equivalent, not byte-identical, payload. Fine for every
  current reader; worth a sentence in the audit-trail chapter if anyone
  relies on byte equality.
- pm-audit-replay was not reviewed here, apart from its use of `rawlines`
  (C11).

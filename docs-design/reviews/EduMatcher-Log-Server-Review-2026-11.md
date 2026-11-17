# pm-log-srv and logclient Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/log_srv/` and `src/edumatcher/logclient/` at
`dac95e8f` (v0.80.0). `log_srv`: `server.py` (785 lines, the select loop, LALF
handling, session bookkeeping, retention), `pubsub.py` (1239, the LALF-PS hub),
`writer.py` (254, the single SQLite writer thread), `schema.py` (250),
`config.py` (358), `main.py` (282), `session.py` (76). `logclient`:
`protocol.py` (416, the LALF codec shared with the server), `handler.py` (324,
`TcpLogHandler`, used by every `pm-*` process), `discovery.py` (142, the
start-up probe; `resolve_handler` is called from 26 entry points). The
generated LALF-PS message classes (`models/generated/log.py`, from
`spec/messages/log.yaml`), `log_cli/diagnose.py` and `log_cli/queries.py` (the
readers of the `processes` table), the log-GUI bridge's LALF-PS uplink
(`web-apps/log-gui/apps/bridge/src/lalf-ps-uplink.ts`) and the book-GUI bridge's
LALF client (`web-apps/book-gui/packages/lalf-client`) were read where they
decide this component's behaviour. They were not reviewed as code of their own.

**Focus:** correctness, edge-case handling, performance, and whether the
comments, help texts, `docs/books/operator-guide/part-6-observe-and-recover/040-log-server.md`,
the LALF specification
(`docs/books/protocols-and-clients/part-2-specifications/050-lalf.md`), the
configuration reference (§6.7) and the design document
(`docs-design/EduMatcher-log-srv.md`) say what the code does.

**Previous work:** the design document, and the scheduler/log_srv review of
2026-11-05 (commit `fff1572f`). Its fixes are in place and are not repeated
here: WAL and `busy_timeout` on `log.db`, the `idx_le_client_ts` index,
pruning in 5000-row chunks, backpressure on the writer backlog (all reads stop
above `max_client_queue`, idle timeout suspended meanwhile), failed writer
batches retried rather than dropped, a draining shutdown, the `io_error`
disconnect reason, and backfill bounded at the live `seq` with bounded seq
windows per pass. Also in place: deferred `processes` registration so a probe
leaves no row (`1d4ad425`), persisted heartbeats (`5b65d384`), disconnect
reasons (`9eb8ed7f`), the 3-second start-up probe window (`d9a05a21`), and the
log-ledger template id plus `schema_version` (log ledger L1).

**Method:** every line of the files above was read. Findings marked *(repro)*
were reproduced with a scratch script against the tree at `dac95e8f`, using a
real `LogServer` (run on a thread with a temporary `log.db`), real
`TcpLogHandler`s and `resolve_handler` in child processes, raw LALF sockets
built with `logclient.protocol`, and real ZeroMQ `SUB`/`PUSH` subscribers using
`models.message`. *(measured)* means timed on this host (36 cores, Python 3.14,
load average about 5) against a synthetic `log.db` of 31 days × 100 000 rows
(3.1 M rows, 1.0 GB) written with the server's own `INSERT_LOG_EVENT`, and a
1-day copy for comparison. The real sim `log.db` of 2026-11-10 holds about
70 000 rows a day, with a peak of 223 rows/s from one process. Timings are on
tmpfs unless they say "on disk" (btrfs on NVMe, where SQLite's fsync per commit
counts). The other findings are by inspection, with line numbers given.

Status: **Done, uncommitted (2026-11-16).** All WPs implemented in one go.
Q1–Q5 taken as recommended; WP-LOG05 made two choices to confirm (the
`pub_sndhwm` cap kept, the 100 ms partial-chunk wait on the live stream).

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (rows in `log.db`, lines in the fallback file,
   `processes.disconnect_reason`, `pm-log-cli diagnose` output and exit code,
   the LALF-PS messages a `SUB` socket receives, a metric).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_log_srv_*.py`,
   `tests/test_logclient_*.py`, `tests/test_lalf_protocol.py`,
   `tests/test_log_server_pubsub_config.py`, `tests/test_msgen_log_server.py`
   and `tests/test_log_cli*.py` with `-n logical`, then
   black/flake8/mypy/pyright. Do not start the next WP with a known failing
   test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Server tests should use the `_RunningServer` fixture pattern of
`tests/test_log_srv_server.py` (a real `LogServer` on a thread, `tmp_path`
database, an ephemeral port) and raw sockets built with `logclient.protocol`.
Handler tests should use the same pattern as `tests/test_logclient_handler.py`;
the "process exit" tests run a child interpreter that calls `resolve_handler`
and `sys.exit`, as the repro did, so `logging.shutdown` runs for real. LALF-PS
tests use the hub fixture and `_row()` helper of `tests/test_log_srv_pubsub.py`,
or a real `SUB` socket where the ZeroMQ queue is the subject.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-LOG01 | A record a process logs before it exits or while pm-log-srv is down ends in `log.db` or the fallback file, or is counted and reported | H1, H2, D5 | Q1, Q2 | 1 d | ☑ | 2026-11-16 |
| 2 | WP-LOG02 | Every session row is closed with a reason, so `diagnose` never calls a gone process "stuck" | C1, C12 | Q3 | 0.5 d | ☑ | 2026-11-16 |
| 3 | WP-LOG03 | No input from a client can stop collection silently | C2, C9 | — | 0.5 d | ☑ | 2026-11-16 |
| 4 | WP-LOG04 | LALF-PS delivers rows with NULL columns as null, and never reports rows it did not send | C3, C4, C11 | Q4 | 0.5 d | ☑ | 2026-11-16 |
| 5 | WP-LOG05 | A slow subscriber can see every loss, and cannot grow the server's memory past a bound | C5, P1, D3 | Q5, WP-LOG04 | 1 d | ☑ | 2026-11-16 |
| 6 | WP-LOG06 | The main loop never stalls on history, on retention or on error replies | P2, P3, P4, P5, D6, D9 | — | 0.5 d | ☑ | 2026-11-16 |
| 7 | WP-LOG07 | The client follows the LALF specification and the configuration is strict | C6, C7, C8, C10 | — | 0.5 d | ☑ | 2026-11-16 |
| 8 | WP-LOG08 | The guide, the specification, the help registry and the docstrings describe the final code | D1, D2, D4, D7, D8 | all | 0.5 d | ☑ | 2026-11-16 |

Suggested order: **WP-LOG01 → WP-LOG02 → WP-LOG03 → WP-LOG04 → WP-LOG05 →
WP-LOG06 → WP-LOG07 → WP-LOG08**. WP-LOG01 first: it loses the most important
rows (the CRITICAL line before an exit) on every normal shutdown. WP-LOG02
makes `diagnose` trustworthy again after any server restart. WP-LOG03 is
small and removes a one-frame way to stop all logging. WP-LOG04 changes the
message spec, and WP-LOG05 changes it again on top. The text WP goes last so
the texts describe the final code.

Estimated sequential effort: about 5 days, excluding review time and findings
discovered on the way.

---

## 1. Overall assessment

The server side is in good shape. The single writer thread persists 110 000
rows/s on tmpfs and 14 600 rows/s on disk, with no growth from 1 to 31 days of
history; the real peak is 223 rows/s. Retried batches, backpressure on the
writer backlog and the draining shutdown hold. Rows are published on LALF-PS
only after commit, so the live stream never shows a row `log.db` lacks. The
backfill path is cheap per pass (worst 18 ms at 100 000 rows a day) because it
scans bounded `seq` windows. The probe leaves no `processes` row and the
`DOWN` server state reaches subscribers at shutdown.

The defects are in five places:

- **The client loses rows it accepted (H1, H2).** `TcpLogHandler.close()` stops
  its thread without draining the queue. In three of three real process exits,
  the final `CRITICAL fatal runtime error` line never reached `log.db`. At
  failover the handler throws away everything it queued during the 30-second
  grace window, and the drop counter the design says is "reported once" is
  never reported anywhere.
- **The `processes` table outlives the server (C1).** A server stop or crash
  closes no session row. Afterwards `pm-log-cli processes --active` lists dead
  sessions and `diagnose` exits 3, calling each one stuck.
- **One frame stops collection (C2).** A `LINE` or `PID` beyond 64-bit raises
  `OverflowError`, which no handler catches. A `LINE` kills the writer thread
  silently. A `PID` in `HELLO` kills the server.
- **LALF-PS rows with NULL columns (C3, C4).** The message spec declares
  `instance`, `module` and `line` non-nullable, but `log.db` stores NULLs. Every
  NULL `instance` (most rows) goes out as the string `"None"`. A row with NULL
  `line` (every book-GUI bridge row) makes the whole 500-row chunk fail; the
  live chunk is lost and a backfill reports `done` with `total_sent` 303 after
  sending 0 rows.
- **A slow subscriber (C5, P1).** ZeroMQ `PUB` drops silently at its
  high-water mark, so `dropped` reported 19 250 of 100 900 lost rows. Rows move
  into ZeroMQ at once, so the `max_pending_rows` bound never applies; a wedged
  subscriber grew the server by 461 MB per million rows with no plateau.

Severity key: **High**: a log record lost from `log.db` and from the fallback
file without a count or a warning, on a path normal operation takes. **Med**:
a wrong, lost or misleading figure or row in a viewer or a diagnostic, or a
way to stop collection that needs unusual input; a cost that grows without
bound. **Low**: hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| H1 | High | Client exit | `close()` stops the sender without draining: 1 of 7 lines of an exiting process stored, the CRITICAL line never (3 of 3 runs); 2 of 1000 queued records after `close()` *(repro)* | LOG01 |
| H2 | High | Client outage | Failover discards the queued backlog: 366 of 389 records logged during the outage in neither `log.db` nor the file; `dropped_count` 0 and never reported; 2 records lost per server restart, uncounted *(repro)* | LOG01 |
| C1 | Med | Sessions | A server stop or crash leaves `disconnected_at` NULL: `processes --active` lists dead sessions, `diagnose` exits 3 with false "stuck" warnings *(repro)* | LOG02 |
| C2 | Med | Input | `LINE`/`PID` beyond int64 raise `OverflowError`: the writer thread dies silently (0 rows reach `log.db` until shutdown), or the server process dies *(repro)* | LOG03 |
| C3 | Med | LALF-PS | `LogRow` declares `instance`/`module`/`line` non-nullable: NULL `instance` goes out as `"None"`; a NULL `line` loses its live chunk (163 of 303 rows delivered) *(repro)* | LOG04 |
| C4 | Med | LALF-PS | Backfill and stream state advance before the publish: a failed publish loses the chunk and the backfill still reports `done`, `total_sent` 303, 0 rows sent *(repro)* | LOG04 |
| C5 | Med | LALF-PS | `PUB` high-water-mark drops are never counted: `dropped` 19 250 against 100 900 rows lost *(repro)* | LOG05 |
| C6 | Low | Client | `SEQ` continues across reconnects, against the specification's MUST restart at 1 | LOG07 |
| C7 | Low | Client | No send timeout after the handshake: against a silent peer `sendall` blocks and failover never triggers | LOG07 |
| C8 | Low | Client | `_try_connect` leaks the socket on every failed handshake | LOG07 |
| C9 | Low | Input | `LEN` is not checked before buffering: one header makes the server buffer without limit | LOG03 |
| C10 | Low | Config | `enabled`/`pubsub_enabled` use `bool()` (`"false"` is true); a `name` with `\|` crashes the server on the first `HELLO` | LOG07 |
| C11 | Low | LALF-PS | Re-subscribing discards the subscription's buffered rows uncounted and leaves an older backfill running with the old filter | LOG04 |
| C12 | Low | Lifecycle | `LogServer.close()` runs twice (from `run()` and from `main()`) | LOG02 |
| P1 | Med | LALF-PS | A wedged subscriber grows the server by 46 MB per 100 000 rows with no plateau at 1 M rows; `max_pending_rows` never engages *(measured)* | LOG05 |
| P2 | Low | LALF-PS | `_first_seq_at_or_after` scans the primary key from the oldest row: 7 ms at 1 day, 269 ms at 31 days, per subscribe with backfill *(measured)* | LOG06 |
| P3 | Low | Server | Each `ERR` reply is its own fsync'd commit on the main loop: 1.24 ms on disk *(measured)* | LOG06 |
| P4 | Low | Retention | A prune runs every chunk in one main-loop pass: 5.1 s with no reads for 1.1 M rows *(measured)* | LOG06 |
| P5 | Low | Ingest | One client is read at most 4096 bytes per 10 ms pass: 1 730 rows/s per client *(measured)* | LOG06 |
| D1–D9 | — | Texts | See §5 | LOG01, 05, 06, 08 |

---

## 3. Correctness findings

### H1. A process's last records never reach log.db *(repro)* — High

`logclient/handler.py:120-126` `close`, `:213-268` `_run`.

`close()` sets `_stop_event` and joins the thread for 2 s. The thread checks
the event at the top of every pass (`:219`), so it sends at most the frame it
is holding, then `EXIT`, and leaves the rest of the queue behind. The
`logging` module calls `close()` from `logging.shutdown()` at interpreter exit,
so this is the path of every normal process exit, including the exits after a
CRITICAL message, which the log-ledger rule makes the most important line a
process writes.

Repro 1: a real `LogServer`, a handler, `n` CRITICAL records, then `close()`.

| records logged before `close()` | stored in `log.db` | `dropped_count` |
|---|---|---|
| 1 | 1 | 0 |
| 10 | 1 | 0 |
| 100 | 1 | 0 |
| 1000 | 2 | 0 |

Repro 2: a child interpreter configured exactly as an entry point does
(`resolve_handler` + `basicConfig`), logging `starting`, five `shutting down`
lines and `CRITICAL fatal runtime error: boom`, then `sys.exit(1)`. Three runs:
each session stored one row, `starting`. The disconnect reason is
`client_exit`, so nothing in `log.db` hints that rows are missing.

The rows are not in a file either: the handler has not failed over, so nothing
writes them anywhere. The operator who looks up why a process stopped finds
the start-up line and nothing after it.

**Fix.** `close()` drains: keep sending until the queue is empty or a
deadline passes, then send `EXIT`. Rows left at the deadline (server
unreachable) go to the fallback file. See Q1.

### H2. The client loses its backlog around every outage *(repro)* — High

`logclient/handler.py:213-232`, `:284-294` `_drain_queue_to_fallback`,
`:254-261`, `:84`/`:116` `dropped_count`.

Three paths lose accepted records without a trace:

1. **Failover discards the grace-window backlog.** While the socket is down the
   thread only reconnects and sleeps; it does not touch the queue, so every
   record of the grace window waits there (up to `queue_maxsize` 2000, the rest
   counted in `dropped_count`). At failover `_drain_queue_to_fallback` throws
   the queue away because it holds encoded LALF frames, not `LogRecord`s. Its
   comment calls this "the small in-flight backlog"; with the default 30 s
   window it is the whole outage.
2. **`dropped_count` is never reported.** Nothing reads it (`grep` finds only
   its two writes). The design (§8.2, §8.6 step 2) says the count "is reported
   once" after a reconnect; no code does that, on reconnect or at failover.
3. **The frame whose send failed is dropped** (`:254-261`), and one more is
   lost in the dead socket's kernel buffer, on every server restart.

Repro (failover): handler with `failover_timeout_sec=2`, server stopped, 100
records/s for 4 s.

| logged during the outage | in `log.db` | in the fallback file | `dropped_count` | lost |
|---|---|---|---|---|
| 389 | 0 | 23 | 0 | 366 |

The fallback file starts with the marker and then record 366: nothing says 366
records came before it.

Repro (restart within the grace window): 100 records/s, server stopped for
1 s and restarted on the same port. Three runs: 391/392/391 logged, 2 missing
each time (seqs 97–99), `dropped_count` 0.

Path 3's second record is inherent to a protocol without acknowledgements
(LALF has none, §5.5); the first record and paths 1–2 are not.

**Fix.** Queue what both outputs need (the frame and the formatted fallback
line), write the backlog to the file in order at failover, put a failed frame
back at the head of the queue, and report the drop count once as a WARNING
row (on reconnect) or a fallback-file line (after failover). See Q2.

### C1. A server stop leaves every session open for good *(repro)* — Med

`log_srv/server.py:236-259` `close`; `log_cli/diagnose.py:188`,
`log_cli/queries.py:155`.

`close()` closes every client socket but writes no `disconnected_at` for the
registered sessions; a crash cannot write it either, and start-up does not
repair it. `diagnose`'s `process_silence` and `processes --active` both select
`disconnected_at IS NULL`, so every session open at a server stop counts as
connected forever.

Repro: three handlers log one line each; the server is stopped, then the
handlers are closed; 32 s later:

```text
$ pm-log-cli processes --active      (exit 0)
pm-proc2 | ... | disconnect_reason (empty) | 1
pm-proc0 | ... | (empty) | 1
pm-proc1 | ... | (empty) | 1
$ pm-log-cli diagnose                (exit 3)
[WARNING] process_silence: pm-proc2 (session 9af7dcdb) has not logged or heartbeated in 33s despite an open connection
[WARNING] process_silence: pm-proc0 ...
[WARNING] process_silence: pm-proc1 ...
```

Every server restart adds one stale row per connected process. The guide's
"Scripted health check — non-zero exit means something was flagged" then
fails for good, and each warning tells the operator to check a process that
is in fact fine and logging under a newer session. The LALF specification
(`050-lalf.md`, `EXIT`) says the server MUST mark the stored process record
disconnected when the socket closes.

**Fix.** `close()` records `server_stop` for each registered session; start-up
closes any row still open with `server_restart` (it can only be left by a
crash). See Q3 for how `diagnose` reads the two reasons.

### C2. One out-of-range integer stops collection *(repro)* — Med

`log_srv/server.py:461-470` (`PID`), `:565-571` (`LINE`), `:594-621`;
`log_srv/writer.py:419-484`, `:385-389`.

`int()` accepts any size; SQLite does not, and the bind raises
`OverflowError`, which is not a `sqlite3.Error`.

- `LOG|...|LINE=18446744073709551616`: the writer's `except sqlite3.Error`
  (`writer.py:474`) does not catch it, `_run` has no guard, and the writer
  thread dies. The batch it held is lost. The main loop keeps accepting rows;
  nothing is written, no error is logged after the thread's traceback, and
  once 10 000 rows are pending the backpressure stops every client for good.
- `HELLO|...|PID=18446744073709551616`: `_register_process` raises on the
  main thread, `run()` ends, the process exits and the port closes.

Repro (`LINE`): a good handler logs 200 rows after the bad frame; 1 s later
`writer alive: False, pending: 200, rows in db: 0`, server loop alive. Repro
(`PID`): `server loop alive: False`, `connect: [Errno 111] Connection refused`.

No EduMatcher client sends such values; the server listens on `0.0.0.0` and
trusts the network by design (§10), so a buggy third-party client or a stray
`nc` session is enough. The cost is total, silent loss of central logging.

**Fix.** Range-check `PID`, `LINE` and `SEQ` at the edge (`PID`: refuse
`HELLO` as for a non-integer; `LINE`: store NULL as for a non-integer). Make the
writer survive any exception the way it survives `sqlite3.Error`, and make the
main loop stop the process (non-zero exit, CRITICAL) if the writer thread is
no longer alive.

### C3. LALF-PS misreads NULL columns and loses chunks over them *(repro)* — Med

`spec/messages/log.yaml:75,81,82` (`LogRow.instance`, `module`, `line`);
`models/generated/log.py:218,224,225`; `log_srv/pubsub.py:1083-1103`,
`:932-1006`; `log_srv/schema.py:46,52-53` (all three columns nullable).

`log_events.instance`, `module` and `line` are nullable and are NULL in real
data: `instance` is NULL for 73 097 of the 73 111 rows of the 2026-11-10 sim
database, and the book-GUI bridge's LALF client omits `MODULE` and `LINE`
(`web-apps/book-gui/apps/bridge/src/logging/logger.ts:39-40`). The spec
declares the three fields non-nullable, so the generated `LogRow.from_dict`
runs `str(None)` and `int(None)`:

- NULL `instance` and `module` become the string `"None"`. The log-GUI bridge
  already decodes `null` for these columns (`lalf-ps-uplink.ts:40,46-47`), so
  the live view shows `None` where the same row read from `log.db` shows
  nothing.
- NULL `line` raises `TypeError` inside `make_log_event`, so the whole chunk
  of up to `backfill_chunk_rows` (500) rows is not published.

Repro: a STREAM subscriber with no filter; a Python handler logs 300 rows and
a raw client sends 3 rows without `LINE`, interleaved.

| stored | delivered live | `instance` values seen | server ERROR records |
|---|---|---|---|
| 303 | 163 | `{'None'}` | 3 |

What the backfill does with the same rows is C4.

**Fix.** Mark the three fields nullable in `spec/messages/log.yaml` and
regenerate. See Q4.

### C4. A failed publish is counted as delivered *(repro)* — Med

`log_srv/pubsub.py:968-991` `_pump_backfills`, `:1087-1088` `_flush_streams`.

`_pump_backfills` advances `job.sent_rows` and `job.cursor_seq` before it
builds and publishes the chunk; `_flush_streams` deletes the chunk from
`pending_rows` before it publishes. When the build raises (C3, or any
validation error such as a `logger` longer than the spec's 128), the exception
leaves `poll()` (the rest of the pass, reaping and server state included, is
skipped), and on the next pass the job carries on past the lost rows.

Repro: the 303 rows of C3, then a NOTIFY subscription with
`backfill_minutes=5`:

```text
backfill rows delivered= 0 total_sent claimed= [303]
backfill chunks=1 done=True
```

The subscriber is told its history is complete and gets none of it.

**Fix.** Build the message first; change the cursor, counters and buffer only
after `_publish` returns. A row that cannot be serialised is an INTERNAL error
on that subscription, not a silent skip.

### C5. Rows ZeroMQ drops are never in `dropped` *(repro)* — Med

`log_srv/pubsub.py:1212-1223` `_publish`, `:1083-1103` `_flush_streams`,
`:1050-1056`.

A ZeroMQ `PUB` socket never blocks and never raises `EAGAIN`: at the
high-water mark it drops the message for that peer silently. The
`except zmq.Again` branch is dead, and a message dropped there was already
counted in `sent_rows`. `_flush_streams` moves every pending row into ZeroMQ
on every pass (the main loop runs about 100 passes a second), so the
server-side buffer with its `dropped` accounting only fills when the writer
outruns the loop; the real backlog of a slow subscriber sits in ZeroMQ.

Repro: STREAM subscriber with `RCVHWM` 100 that does not read while 200 000
rows are committed (`pub_sndhwm` 100), then drains:

| committed | received | lost | largest `dropped` reported |
|---|---|---|---|
| 200 000 | 99 100 | 100 900 | 19 250 |

A subscriber with a filter cannot use `seq` gaps instead, because filtered-out
rows leave gaps too. The guide (§"The other failure") and the configuration
reference tell the operator to watch `dropped`.

**Fix.** See Q5: a per-subscription message counter so the subscriber can
detect lost messages, and a `PUB` bound expressed in rows.

### C6. `SEQ` does not restart on reconnect — Low

`logclient/handler.py:82`, `:130-133`.

`_seq` belongs to the handler and keeps counting across reconnects. The LALF
specification says a reconnecting client MUST restart `SEQ` at 1
(`050-lalf.md` §`SEQ`, conformance item 6; design §5.10). The server only logs
gaps at DEBUG, so nothing breaks today, but every new session's first frame
looks like a gap to a conforming server.

**Fix.** Reset the counter on each successful handshake.

### C7. A silent peer blocks the client past its failover window — Low

`logclient/handler.py:313-315`, `:246`, `:255`.

After the handshake the socket has no timeout. If the server host disappears
without a reset (a container network gone, a powered-off host), `sendall`
blocks until the kernel gives up on the connection (on Linux about 15 minutes),
the 30-second failover never starts, and the queue fills and drops. The
design promises the switch to file after `failover_timeout_sec`.

**Fix.** A send timeout (for example `failover_timeout_sec`, at least a few
seconds) treated as a disconnect.

### C8. A failed handshake leaks its socket — Low

`logclient/handler.py:301-324` `_try_connect`.

When `create_connection` succeeds but `recv`, `parse_header_line` or
`parse_welcome` fails, the `except` returns without closing `sock`. With the
backoff this is one descriptor per attempt (4–8 a second at first) until the
garbage collector runs. `discovery._probe_server` uses `with` and is fine.

**Fix.** Close in the `except`.

### C9. `LEN` is buffered without a limit — Low

`logclient/protocol.py:414-424` `FrameReader.next_frame`;
`log_srv/server.py:541-563`.

The reader waits for `LEN` bytes, whatever `LEN` says; the server truncates
only after the whole payload has arrived. A header claiming `LEN=10000000000`
makes the server buffer whatever that client sends next, without bound. The
specification already promises that payloads above `max_message_bytes` are
truncated.

**Fix.** Give `FrameReader` a payload ceiling; above it, keep the first
`max_message_bytes` bytes, discard the rest as it arrives, and mark the frame
truncated.

### C10. Configuration accepts what it cannot honour — Low

`log_srv/config.py:281-282`, `:304`; `log_srv/server.py:486-492`.

`enabled` and `pubsub_enabled` are read with `bool()`, so `enabled: "false"`
and `pubsub_enabled: "no"` mean true. The pm-md-gwy and pm-monitor reviews
made the same fields strict (`md_gateway/config.py:62`, `monitor/config.py:118`).
`name` is put into `WELCOME|SRV=` unchecked; a name containing `|` makes
`build_header_line` raise inside `_handle_hello`, which ends `run()` on the
first client.

**Fix.** Reject non-boolean values and a `name` with `|` or a newline in the
loader, so `pm-config-gen` and `pm-cverifier` refuse them too.

### C11. Re-subscribing silently discards buffered rows — Low

`log_srv/pubsub.py:692-709`, `:713-746`.

A repeated `log.subscribe` (the documented cure for the slow-joiner race)
replaces the `Subscription`: its `pending_rows` and NOTIFY counts are dropped
without being added to `dropped_rows`, and a backfill started by the earlier
subscribe keeps running with the earlier filter unless the new request carries
`backfill_minutes`.

**Fix.** Carry the pending rows over (or count them as dropped), and end an
earlier backfill when the filter changes.

### C12. `close()` runs twice — Low

`log_srv/server.py:210-211`, `log_srv/main.py:274-275`.

`run()` calls `close()` in its `finally`, and `main()` calls it again. The
second call logs "closing pm-log-srv" again and repeats the writer drain. With
C1's fix it would also write the session reasons twice.

**Fix.** Make `close()` idempotent, or call it in one place.

---

## 4. Performance findings

At today's sizes (70 000 rows a day, peaks of 223 rows/s per process) the
writer and the ingest path have a wide margin. P1 is the one cost that grows
without a bound; P2 grows with history.

### P1. A wedged subscriber pins unbounded memory *(measured)* — Med

`log_srv/pubsub.py:503`, `:1083-1103`.

`pub_sndhwm` counts messages, and a message carries up to 500 rows, so the
default bound is 5 million rows per subscriber. Because `_flush_streams`
empties the per-subscription buffer into ZeroMQ on every pass (C5),
`max_pending_rows` (20 000) never limits anything. A subscriber that is
connected but not reading (a frozen viewer that still renews its lease):

| rows committed | server RSS growth |
|---|---|
| 100 000 | +57 MB |
| 500 000 | +237 MB |
| 1 000 000 | +461 MB |

Linear, no plateau, about 46 MB per 100 000 rows of 200-byte messages. The
guide and the module docstring say the bound protects the server's memory.

**Fix.** With Q5: derive the `PUB` high-water mark from
`max_pending_rows / backfill_chunk_rows` (per peer), so ZeroMQ holds at most
about `max_pending_rows` rows per subscriber.

### P2. Backfill start scans the table from its oldest row *(measured)* — Low

`log_srv/pubsub.py:915-930` `_first_seq_at_or_after`.

`SELECT MIN(seq) FROM log_events WHERE client_ts >= ?` is planned as
`SEARCH log_events` (walk the primary key from the lowest `seq` until a row
matches), not through `idx_le_client_ts`. It walks every row older than the
window, on the main loop, for every subscribe with a backfill:

| database | plan | time (5-minute window) |
|---|---|---|
| 1 day, 100 000 rows | `SEARCH log_events` | 7.3 ms |
| 31 days, 3.1 M rows | `SEARCH log_events` | 269 ms |
| 31 days, `INDEXED BY idx_le_client_ts` | `COVERING INDEX idx_le_client_ts (client_ts>?)` | 0.0 ms |

Cost grows with history, not with the window. The docstring says "via its
index" (D6).

**Fix.** Force the index (`INDEXED BY idx_le_client_ts`) and assert the plan
in a test.

### P3. Each ERR reply is a synchronous commit on the main loop *(measured)* — Low

`log_srv/server.py:753-759` `_queue_line`.

Every `ERR` increments `server_stats.total_errors_sent` in its own
transaction on the main loop: 9 µs on tmpfs, **1.24 ms on disk** (WAL fsync),
against 1 µs for a `PONG`. `PAYLOAD_TOO_LARGE` is sent per truncated row, so an
operator who lowers `max_message_bytes` caps truncated ingest near 800 rows/s
for all clients together. Repro: `max_message_bytes=256`, one client logging
60 000 rows of 330 bytes in bursts: 35 740 stored, 24 260 dropped at the
client.

**Fix.** Count `ERR`s in memory and add them in the next writer batch or the
heartbeat flush.

### P4. Retention runs all its chunks in one pass *(measured)* — Low

`log_srv/server.py:720-747` `_prune_older_than`.

Chunking bounds each transaction (23–29 ms per 5000 rows) but the loop runs
every chunk before returning, and the main loop reads no socket meanwhile:

| rows deleted | main loop blocked |
|---|---|
| 100 107 (one day at 100 000/day) | 0.58 s |
| 1 100 109 (retention cut from 30 to 20 days) | 5.08 s |

During a long prune no client is read, the LALF-PS hub publishes nothing (a
viewer misses its `server_state` heartbeats and shows the server down), and
client queues can overflow.

**Fix.** Delete one chunk per main-loop pass until a chunk comes back short.

### P5. One recv per client per 10 ms pass *(measured)* — Low

`log_srv/server.py:209`, `:321`.

Each pass reads at most 4096 bytes from a client, then sleeps 10 ms. A single
client is therefore read at about 1 730 rows/s (20 000-row burst: 3 309
dropped at the client's 2000-slot queue), while the writer could take 14 600
rows/s on disk. The real peak is 223 rows/s, so this only matters for a
process run at DEBUG.

**Fix.** Read until `EAGAIN` or a per-pass byte budget (for example 64 KiB),
and skip the sleep when a pass did work.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | operator guide `040-log-server.md` §"Startup options", `pm_help/registry.py:2609-2668` | Lists `--config PATH` / `-c`, which `pm-log-srv` no longer has (`log_srv/main.py:25-120`); omits `--log-target` and `--log-file` (the registry omits `--log-file`). The expected start-up line lacks the `(cwd=...)` part the code prints (`server.py:186-194`). |
| D2 | guide §"Overview" note "Phased rollout"; `pm_help/registry.py:2664-2666` notes; `logclient/__init__.py:3-9`; design §8.7 | Say auto-detection is not yet rolled out and `TcpLogHandler` is "phase 2 work"; 26 entry points call `resolve_handler`. |
| D3 | guide §"The other failure", §"Troubleshooting"; config reference §6.7 `max_pending_rows`; `pubsub.py:38-42`, `:500-502` | Say a slow subscriber's losses are reported as `dropped` and that the bounds protect memory; see C5, P1. |
| D4 | `050-lalf.md` `HELLO_TIMEOUT` row, its "Implementation note", "What to watch out for"; the `EXIT` reason list | Say `HELLO_TIMEOUT` is closed in the same step without a flush; the code queues it and gives it one flush pass (`server.py:643-653`). The reason list lacks `io_error` (and will lack C1's new reasons). |
| D5 | design §8.2 and §8.6 step 2; `handler.py:284-289` | Say `dropped_count` "is reported once"; nothing reports it. The comment calls the discarded queue "the small in-flight backlog"; it is the whole grace window (H2). |
| D6 | `pubsub.py:916` | "Lowest seq whose client_ts is in the window, via its index": the query does not use the index (P2). |
| D7 | config reference §6.7 `enabled`, `max_client_queue` | `enabled: false` "refuses to accept connections": `pm-log-srv` exits at once (`main.py:242-244`). `max_client_queue` "per-connection outbound backlog limit": it is also the global writer backlog at which every read stops (`server.py:291`). |
| D8 | `logclient/protocol.py:243-245` | `build_log_frame` "Returns the truncation flag alongside the encoded bytes"; it returns the bytes only. |
| D9 | guide §"Retention" | "Pruning runs automatically once per hour in the background": it runs on the main loop and stops collection while it runs (P4). |

---

## 6. Verified as correct

- **Writer throughput and growth.** 100 000 rows in 0.90 s (1 day of history)
  and 0.93 s (31 days) on tmpfs; 6.8 s on disk. The per-batch cost does not
  grow with history.
- **Commit-then-publish.** `on_batch_persisted` runs after the transaction
  commits (`writer.py:486`); seqs are contiguous per batch because the writer
  is the only inserter and uses one `executemany`.
- **Backfill/live seam.** The job is created in `_handle_control_requests`
  before `_fan_out_new_rows` in the same pass, with `max_seq = _last_seq`; rows
  still in the inbox get seqs above it and arrive live. An empty window
  produces one `done` chunk.
- **Backfill chunk cost.** Bounded seq windows keep every pass small: worst
  pass 14 ms (no filter), 5 ms (`min_level=ERROR`), 18 ms (one process) for a
  24-hour window at 100 000 rows/day.
- **Prune query plan.** The `DELETE … WHERE seq IN (SELECT seq … ORDER BY seq
  LIMIT ?)` walks the primary key from the oldest row and stops after the
  chunk; the per-chunk cost (23–29 ms) does not grow with history.
- **`DOWN` at shutdown.** `LINGER 0` does not lose it on the way out: 10 of 10
  stops delivered `UP` and `DOWN` to a connected `SUB`.
- **Probe.** `_probe_server` closes its socket (`with`) and leaves no
  `processes` row; the 3-second retry window (`d9a05a21`) is deliberate and
  only costs time when no server runs.
- **Backpressure and retries** from the 2026-11-05 review hold: a failed
  batch keeps its rows in `_retry`, `pending` counts them, and reads stop above
  `max_client_queue`.
- **Truncation** never splits a UTF-8 code point on either side, and header
  lines are decoded with `errors="replace"`, so no surrogate reaches SQLite.

---

## 7. Decisions

| # | Question | Recommendation |
|---|---|---|
| Q1 | How long may `close()` wait to drain? (a) until the queue is empty or a deadline of `connect_timeout_sec` + 2 s, then the rest to the fallback file; (b) no deadline; (c) leave it, document the loss | **(a)**: at exit a process should not hang on a dead server, and 2 s carries thousands of rows on loopback; (b) can hang an exit for good, (c) loses the CRITICAL line H1 is about. |
| Q2 | What does the queue hold so a backlog can go to the file? (a) a pair (frame bytes, formatted fallback line), both built in `emit()`; (b) the `LogRecord`, encoded on the thread; (c) decode the frame back into a line at failover | **(a)**: `emit()` keeps formatting on the caller's thread as now, the file gets the same line format as later records, and nothing parses LALF back. (b) defers `getMessage()` to another thread, where mutable arguments may have changed; (c) needs a second parser. |
| Q3 | How does `diagnose` read the new reasons `server_stop` / `server_restart`? (a) as unexpected, with their own wording ("pm-log-srv stopped while X was connected; X has not reconnected"); (b) as expected | **(a)**: the newest session of a process that never came back after a server restart is exactly what the failover heuristic exists to show (the process probably failed over to file). A process that reconnected has a newer session and is not reported. |
| Q4 | NULL columns on LALF-PS: (a) mark `instance`, `module`, `line` nullable in the spec and regenerate; (b) coerce NULL to `""`/`0` on the server | **(a)**: the log-GUI bridge already expects `null` for these; (b) puts invented values on the wire that differ from `log.db`. |
| Q5 | Slow subscribers: (a) add a per-subscription message counter (`msg_no`) to `log.event` and `log.backfill`, so a subscriber detects a lost message by a gap, set the `PUB` high-water mark from `max_pending_rows / backfill_chunk_rows`, and document that `dropped` counts only server-side shedding; (b) switch to `XPUB` with `XPUB_NODROP` and keep the backlog in the server buffer | **(a)**: (b) makes a send fail for every subscriber when one is slow, so one wedged viewer would stall all of them. (a) changes the message spec (a field added), which the log-GUI bridge ignores until it uses it (§9, L038). |

---

## 8. Work packages

### WP-LOG01 — A record logged before an exit or during an outage is stored, filed or counted (H1, H2, D5; after Q1, Q2)

**Tests first** (`tests/test_logclient_handler.py`):

1. A handler connected to a running server; 1000 CRITICAL records; `close()`;
   all 1000 are in `log_events`. (Fails today: 2.)
2. A child interpreter configured through `resolve_handler` logs 7 lines,
   the last CRITICAL, and calls `sys.exit(1)`; the session holds all 7 rows
   and the reason is `client_exit`. (Fails today: 1 row.)
3. Server stopped; `failover_timeout_sec=1`; 200 records logged before
   failover triggers; every one is in the fallback file, in order, after the
   marker. (Fails today: none.)
4. Server unreachable from the start, queue size 10, 25 records, then
   failover: the file holds the 10 queued records and a line saying 15
   records were dropped. (Fails today.)
5. Queue overflow while connected to a slow server, then the server catches
   up: one WARNING row from `edumatcher.logclient` states the number dropped,
   and `dropped_count` matches it. (Fails today.)
6. The server is stopped and restarted on the same port within the grace
   window while 100 records/s are logged: at most one record is missing.
   (Fails today: 2.)
7. `close()` against an unreachable server returns within the Q1 deadline and
   the queued records are in the fallback file. (Fails today.)
8. `emit()` never raises and never blocks while the server is absent,
   unchanged.

**Change.** In `handler.py`: queue `(frame, fallback_line)`; `close()` drains
to the deadline, then files the rest; on failover write the queue to the file
before switching; requeue a frame whose `sendall` failed at the head; report
the drop count once (WARNING record on reconnect, file line after failover).
Fix the `_drain_queue_to_fallback` comment and the design §8.2/§8.6 text (D5).

**Exit criteria.** Tests 1–8 pass; the suites of the delivery rule green;
`make _check` clean.

**Outcome (2026-11-16).** Q1 (a) and Q2 (a) taken as recommended.
`TcpLogHandler` (`logclient/handler.py`) now queues `(frame, fallback line)`
pairs, both built in `emit()` with the fallback formatter. `close()` sets a
deadline of `connect_timeout_sec` + 2 s (`_CLOSE_DRAIN_SEC`); the thread keeps
sending (and reconnecting, with backoff capped by the deadline) until the
queue is empty or the deadline passes, then sends `EXIT`; what is left goes to
the fallback file under "pm-log-srv did not take N records before the handler
closed; writing them to …". An idle handler returns at once. At failover the
marker, the held frame, the whole grace-window backlog and the drop line are
written in order under the lock `emit()` writes with, and `_failed_over` is set
inside it, so later records follow the backlog. A frame whose `sendall` failed
is held and sent first on the next connection. Drops are reported once, when
the queue has drained: a WARNING `LOG` frame from `edumatcher.logclient`
("N log records dropped: the handler queue was full (queue_maxsize=…)") while
connected, or the same line in the file after failover or at close. The
fallback output is now a plain append-mode file written by the handler instead
of a `logging.FileHandler`, because backlog items are already-formatted lines.
Design §8.2/§8.6 updated (D5); the `_drain_queue_to_fallback` comment now
says what it does.

Tests (`tests/test_logclient_handler.py`, 8 new): on the old handler test 1
(1000 records) stored 2, test 2 (child interpreter through `resolve_handler`)
stored 1 of 7 (`starting`), test 3 filed none of the backlog, test 6 lost the
failed frames; tests 4, 5, 7 failed on the missing file/WARNING row. Test 5 is
built as "server absent at start, then started on the same port" instead of a
slow server: it is deterministic and exercises the same report. Test 6 passed
45 of 45 repeated runs after a wait budget fix in the test itself (the first
version asserted inside a 5 s wait). The drop WARNING row and the two handler
notes are `LogRecord`s built by the handler, not `log.warning` call sites, so
they have no log-ledger entry (the scanner does not see them). Full suite:
14645 passed, 1 skipped.

### WP-LOG02 — Every session row is closed with a reason (C1, C12; after Q3)

**Tests first** (`tests/test_log_srv_server.py`, `tests/test_log_cli_diagnose.py`):

1. Three registered sessions; `server.stop()`; each row has
   `disconnected_at` set and reason `server_stop`. (Fails today.)
2. A `log.db` with an open session row (written by a server that crashed:
   construct one, register a session, abandon it without `close()`); a new
   `LogServer` on the same file closes that row with `server_restart` before
   accepting clients. (Fails today.)
3. After 1, `pm-log-cli processes --active` lists nothing and `diagnose`
   reports no `process_silence`. (Fails today: three warnings, exit 3.)
4. A process whose newest session ended with `server_stop` and that never
   reconnected is reported by `diagnose` with the Q3 wording; one that
   reconnected is not. (Fails today: wording.)
5. `close()` called twice writes each reason once and logs "closing
   pm-log-srv" once. (Fails today.)
6. `EXIT` still records `client_exit`, a reset still records `io_error`,
   unchanged.

**Change.** `server.close()` marks registered sessions; `LogServer.__init__`
closes open rows; `close()` becomes idempotent; `diagnose` wording for the two
reasons.

**Exit criteria.** Tests 1–6 pass; suites green.

**Outcome (2026-11-16).** Q3 (a) taken as recommended. `LogServer.close()`
is idempotent (`_closed` flag) and closes each connected session through
`_disconnect(..., reason="server_stop")`, so registered sessions get
`disconnected_at` and the reason before the writer stops. `LogServer.__init__`
runs the new `schema.CLOSE_OPEN_PROCESSES` with `server_restart` before the
server accepts anything: a row still open at start can only be left by a
server that stopped without `close()`. `diagnose`'s `fallback_to_file` keeps
treating both reasons as unexpected, with their own wording ("pm-log-srv
stopped at … while X was connected; X has not reconnected", and "stopped
without a clean shutdown … the session was closed when pm-log-srv started
again at …"). A process that reconnected has a newer session and is not
reported, unchanged. `main()` still calls `close()` after `run()`; the second
call is now a no-op (C12).

Tests: `tests/test_log_srv_server.py` (stop closes three sessions with
`server_stop`; a simulated crash, `close()` replaced by a no-op, leaves an
open row that the next `LogServer` closes with `server_restart`; `close()`
twice logs "closing pm-log-srv" once and leaves `disconnected_at` unchanged),
`tests/test_log_cli_diagnose.py` (both wordings, reconnect not reported),
`tests/test_log_cli_main.py` (a real server stopped with three sessions:
`processes --active` lists none and `diagnose` has no `process_silence`). All
six failed first on the expected assertion (reason `None`, two log lines, old
wording, three active rows). The unchanged `client_exit`/`peer_closed`/
`io_error` tests pass. Full suite: 14652 passed, 1 skipped. Note: `flake8`
now fails on `tests/test_dc_gwy_gateway.py:8` and `tests/test_ralf_gateway.py:4`
(unused `import os`), which arrived with the upstream merge `995fb624`, not
with this work; left untouched.

### WP-LOG03 — No client input stops collection silently (C2, C9)

**Tests first** (`tests/test_log_srv_server.py`, `tests/test_lalf_protocol.py`):

1. `HELLO` with `PID=2**64`: `ERR|CODE=MISSING_FIELD`, connection closed,
   server still accepting. (Fails today: server dies.)
2. `LOG` with `LINE=2**64`: the row is stored with `line` NULL, and a
   following good row is stored within 1 s. (Fails today: writer dies, 0 rows.)
3. The writer's insert raises a non-SQLite exception once (monkeypatched):
   the batch is retried and stored. (Fails today.)
4. The writer thread is dead: the main loop logs CRITICAL and `run()` ends
   with a non-zero exit from `main()`. (Fails today.)
5. `FrameReader` fed a header with `LEN=10**9` and 1 MiB of payload holds at
   most the ceiling plus one read in memory and yields a truncated frame once
   the declared length has passed. (Fails today.)
6. A normal oversized payload is still stored truncated with an advisory
   `ERR`, unchanged.

**Change.** Range checks in `_handle_hello`/`_handle_log`; writer catches
`Exception` like `sqlite3.Error`; a liveness check of the writer in `run()`;
a payload ceiling in `FrameReader`.

**Exit criteria.** Tests 1–6 pass; suites green.

**Outcome (2026-11-16).** `server._sqlite_int` turns `PID`, `LINE` and `SEQ`
into an int only when it fits SQLite's signed 64-bit range, else `None`:
`HELLO` with an out-of-range `PID` gets `ERR|CODE=MISSING_FIELD` ("PID must
be a 64-bit integer") and is closed; an out-of-range `LINE` is stored NULL; an
out-of-range `SEQ` counts as absent. (Repro detail: on this tree the bad `PID`
was accepted with a `WELCOME` and killed the server at the first `HB`, when
the deferred registration bound it.) The writer catches `Exception`, not only
`sqlite3.Error`, and retries the batch as before. `WriterThread.is_alive` is
checked every main-loop pass: a dead writer logs CRITICAL "log writer thread
stopped; stopping pm-log-srv" and `run()` raises `RuntimeError`, so `main()`
logs "fatal runtime error" and exits non-zero after `close()` (log-ledger entry
added). `FrameReader` takes `max_payload_bytes` (the server passes
`max_message_bytes`): of a longer `LEN` it keeps the first bytes, discards the
rest as it arrives, and returns the frame with the new `LalfFrame.truncated`
flag once the declared length has passed; the server then stores it truncated
with the usual advisory `PAYLOAD_TOO_LARGE`. `buffered_bytes()` reports what
the reader holds.

Tests: `tests/test_log_srv_server.py` (PID, LINE, non-SQLite writer error,
dead writer) and `tests/test_lalf_protocol.py` (1 MiB of a `LEN=10**9` frame
holds at most ceiling + one 4096-byte read; a frame within the ceiling is not
truncated). First run: WELCOME instead of ERR, 0 rows, writer thread dead,
server loop still alive, `TypeError` on the new argument. The unchanged
oversized-payload test passes. Full suite: 14682 passed, 1 skipped (a first
run had two timing failures in `tests/test_ralf_gateway.py` that pass on
their own and on the rerun; they are outside this work).

### WP-LOG04 — LALF-PS sends NULL as null and counts only what it sent (C3, C4, C11; after Q4)

**Tests first** (`tests/test_log_srv_pubsub.py`, `tests/test_msgen_log_server.py`):

1. A persisted row with NULL `instance`, `module` and `line` reaches a STREAM
   subscriber with JSON `null` in all three. (Fails today: `"None"`, and the
   chunk is lost.)
2. 300 rows, 3 of them with NULL `line`: all 303 delivered live. (Fails today:
   163.)
3. A backfill over the same rows delivers 303 rows and `total_sent` 303.
   (Fails today: 0 delivered, `total_sent` 303.)
4. A row that fails validation (logger of 200 characters): the subscriber
   gets `log.error` INTERNAL, the cursor and `sent_rows` do not move past
   rows that were not sent, and the rest of `poll()` still runs (reaping,
   server state). (Fails today.)
5. Re-subscribing with a different filter while rows are pending: pending rows
   are delivered or counted in `dropped`; a running backfill under the old
   filter is ended with `truncated: true`. (Fails today.)
6. The log-GUI bridge's `rowFromWire` reads the new payload unchanged (it
   already accepts `null`).

**Change.** `spec/messages/log.yaml` nullable fields, `make msgen`; reorder
state changes after `_publish` in `_pump_backfills` and `_flush_streams`; a
per-subscription guard in `poll()`; re-subscribe bookkeeping.

**Exit criteria.** Tests 1–6 pass; suites green; `make _check` (msgen)
clean.

**Outcome (2026-11-16).** Q4 (a) taken as recommended. `spec/messages/log.yaml`
marks `LogRow.instance`, `module` and `line` nullable (with a doc line each);
`make msgen` regenerated `models/generated/log.py`, `generated/rest/log.py` and
the message reference. `_flush_streams` and `_pump_backfills` now build the
message first and change state only after: a live chunk that fails to build is
counted in `dropped_rows` (not `sent_rows`), a backfill chunk that fails ends
the job through the new `_end_backfill` (empty final chunk, `done` and
`truncated`, `total_sent` and `last_seq` where they stood), and both report
`log.error` INTERNAL naming the seq range plus an ERROR log line (ledger entry
added). The failure is caught per subscription, so the rest of `poll()` runs.
Re-subscribe: with the same mode and filter the buffered rows and NOTIFY
counts carry over; otherwise they are added to `dropped_rows`; a filter change
ends a running backfill as truncated (a new `backfill_minutes` then starts a
fresh one). The log-GUI bridge's `rowFromWire` already maps `null` for the
three fields (`lalf-ps-uplink.ts:40,46-47`), so test 6 is by inspection.

Tests (`tests/test_log_srv_pubsub.py`, 7 new, two with a new `_CapturingHub`
that records decoded publishes): first run showed no row delivered for the
NULL row, 294 of 303 live (the harness's 3-row chunks), 294 of 303 backfilled,
`MessageValidationError` and `TypeError` escaping `poll()`, and nothing counted
on re-subscribe. Full suite: 14710 passed, 1 skipped.

### WP-LOG05 — A slow subscriber sees every loss and has a memory bound (C5, P1, D3; after Q5, WP-LOG04)

**Tests first** (`tests/test_log_srv_pubsub.py`, real `SUB` socket):

1. A STREAM subscriber that does not read while 200 000 rows are committed,
   then drains: the `msg_no` values it receives show exactly the number of
   lost messages, and received rows plus rows in those messages equal the
   rows committed. (Fails today: no counter, `dropped` 19 250 of 100 900.)
2. The same with defaults: the server's RSS growth stays below a bound
   computed from `max_pending_rows` (measured, not guessed, in the WP).
   (Fails today: +461 MB at 1 M rows.)
3. A fast subscriber sees consecutive `msg_no` and `dropped` 0, unchanged
   except for the new field.

**Change.** `msg_no` in `log.event`/`log.backfill` (spec, msgen), counted per
subscription; `PUB` high-water mark from `max_pending_rows /
backfill_chunk_rows`; remove the dead `zmq.Again` branch; texts of D3 (guide,
configuration reference, module docstring).

**Exit criteria.** Tests 1–3 pass; suites green; the RSS bound recorded with
the measurement.

**Outcome (2026-11-16).** Q5 (a) taken as recommended, with two decisions
made on the way that are worth confirming:

- `msg_no` (spec field on `log.event` and `log.backfill`, regenerated) is one
  counter per subscription shared by both topics, from 1, kept across a
  re-subscribe like the other lifetime counters. A gap is a lost message; a
  loss at the tail shows when the next message arrives.
- The `PUB` `SNDHWM` is `min(pub_sndhwm, max(1, max_pending_rows //
  backfill_chunk_rows))` (`LogPubSubHub.pub_hwm`; 40 messages by default).
  `pub_sndhwm` is kept as an upper cap rather than removed, because it is
  wired through `pm-config-gen`, `pm-cverifier`, the config-GUI and the
  guides; with defaults it no longer decides anything. **To confirm.**
- **Beyond the plan:** a live chunk is now sent when it is full, and a
  partial chunk at most `_STREAM_FLUSH_INTERVAL_SEC` (100 ms) after the last
  send. Without it, the main loop sent one message of a row or two every
  10 ms pass, and 40 messages would have held only about 0.4 s of a slow
  viewer's backlog. Cost: up to 100 ms more latency on the live view.
  **To confirm.**
- The dead `except zmq.Again` branch in `_publish` is gone; the comment says
  why a `PUB` send never raises there.

Texts (D3): module docstring of `pubsub.py`, the `start()` comment, guide
§"The other failure" (both bounds and their two loss signals, with the
measured figure), the STREAM paragraph, the example client (tracks
`msg_no`), the troubleshooting row, the configuration-file reference rows
for `max_pending_rows`/`pub_sndhwm`, and the `pm-config-gen` field comments
(`config_gen/cli_comments.py`; the config-GUI mirror `defaultFieldComments.ts`
regenerated with `tools/gen_config_gui_comments.py`). The comment lines in the
generated example configs under `docs/examples/ref_data/` were not
regenerated; the old line ("ZeroMQ send high-water mark on the PUB socket")
is still accurate.

Measured (scratch `rss_bench.py`: the hub in a child process, defaults, one
STREAM subscriber with `RCVHWM` 100 in another process that never reads):
before, +15 MB at 100 000 rows, +89 MB at 300 000, +163 MB at 500 000; after,
+5.0 MB at 100 000, 500 000 and 1 000 000 rows. The RSS test runs the same
child at 300 000 rows and asserts < 30 MB.

Tests (`tests/test_log_srv_pubsub.py`): 200 000 rows to a subscriber that does
not read: for every pair of received messages with consecutive `msg_no` the
missing seqs equal the growth of `dropped`, and the losses are accounted
for by `msg_no` gaps; a fast subscriber sees `msg_no` 1..n, every row,
`dropped` 0; backfill and live share the numbering; `SNDHWM` derived and
capped; the RSS bound. First run: `KeyError: 'msg_no'` and `SNDHWM` 10000.
The `tests/test_msgen_log_server.py` round-trip payloads gained `msg_no`.
Full suite: 14733 passed, 1 skipped (an earlier run had a timing failure in
`tests/test_monitor_cli.py` that passes on its own, and five failures in
another session's in-progress `alf_console` tests).

### WP-LOG06 — The main loop never stalls on history, retention or error replies (P2, P3, P4, P5, D6, D9)

**Tests first** (`tests/test_log_srv_pubsub.py`, `tests/test_log_srv_server.py`):

1. The SQL `_first_seq_at_or_after` executes (captured with
   `set_trace_callback`) is planned with `idx_le_client_ts`, no
   `SEARCH log_events` without an index. (Fails today.)
2. One `_run_retention_if_due` pass deletes at most `PRUNE_CHUNK_ROWS` rows;
   later passes finish the job; the total deleted equals today's. (Fails
   today: one pass deletes all.)
3. 1000 `ERR` replies cause no main-loop commit; `total_errors_sent` is
   1000 after the next flush. (Fails today: 1000 commits.)
4. One client sending 20 000 rows without pause is ingested at no less than
   5 000 rows/s on tmpfs (measured 1 730 today; the target is a guess, to be
   confirmed by measurement in the WP). (Fails today.)
5. Retention deletes only rows older than the cutoff, unchanged.

**Change.** `INDEXED BY` on the first-seq query; prune state carried across
passes; `ERR` counter folded into a batch; a read budget per pass and no sleep
after a busy pass; fix D6 and the guide's retention sentence (D9).

**Exit criteria.** Tests 1–5 pass; suites green; P2 and P4 re-measured on
the 31-day bench database.

**Outcome (2026-11-16).**
- P2/D6: `_first_seq_at_or_after` uses `INDEXED BY idx_le_client_ts`, and its
  docstring says why. Re-measured on a 31-day bench (31 × 100 000 rows):
  259 ms with `SEARCH log_events` before, 0.0 ms with `COVERING INDEX
  idx_le_client_ts (client_ts>?)` after.
- P3: `_queue_line` counts `ERR` replies in `_errors_sent_unflushed`; they are
  added to `server_stats.total_errors_sent` in one statement
  (`INCREMENT_TOTAL_ERRORS_SENT` now takes `?`) at each heartbeat flush and in
  `close()`. The count in `log.db` therefore lags by up to
  `heartbeat_interval_sec`.
- P4/D9: retention keeps its cutoff in `_prune_cutoff` and deletes one
  `PRUNE_CHUNK_ROWS` chunk per main-loop pass until a chunk comes back short,
  then logs the total once. `_prune_older_than` is gone (only the old loop and
  tests used it). Re-measured, retention cut from 31 to 20 days on the bench
  copy: 1 100 041 rows over 221 passes, 17 ms a pass on average, worst pass
  168 ms (one pass, presumably a WAL checkpoint), against 5.1 s in one pass
  before. Guide §"Retention" and design §6.5 sentence updated.
- P5: `_read_session` reads a ready client until `EAGAIN` or 64 KiB
  (`_READ_BUDGET_BYTES`) per pass, and the main loop skips its 10 ms sleep
  after a pass that read anything. One client, 20 000 rows of 200-byte
  messages on tmpfs: 1 485 rows/s with the old read path (measured by
  reverting the two lines), about 10 500 rows/s now (scratch profile: the
  writer thread is now the limit).

Tests: `tests/test_log_srv_pubsub.py` (the executed first-seq SQL, captured
with `set_trace_callback`, plans through `idx_le_client_ts`; failed first with
`SEARCH log_events`); `tests/test_log_srv_server.py` (one pass deletes one
chunk, `[4, 2, 1, 1, 1]` remaining over five passes, failed first with
`[1, 1, 1, 1, 1]`; 1000 ERRs make no `UPDATE server_stats` until the flush,
which makes one; one client ingested at ≥ 5 000 rows/s, which failed first at
1 485 rows/s). Two test bugs were fixed on the way: the ingest test's socket
kept `rs.connect()`'s 2 s timeout, so its `sendall` gave up whenever writer
backpressure paused reads, and the ERR test counted its own `SELECT`. The
existing retention tests now drive the passes through a
`_prune_to_completion` helper; the oversized-payload test waits for the
heartbeat flush before reading `total_errors_sent`. Full suite: 14762 passed,
1 skipped, 9 failed, none of them in this scope: 7 in
`tests/test_gateway_and_scheduler.py` (`alf_console/main.py._parse_date`,
being changed in another session at the same time) and 2 RALF timing tests
that pass on their own (53/53).

### WP-LOG07 — The client follows the specification and the configuration is strict (C6, C7, C8, C10)

**Tests first** (`tests/test_logclient_handler.py`,
`tests/test_log_server_pubsub_config.py`):

1. After a server restart the first `LOG` of the new session has `SEQ=1`.
   (Fails today.)
2. Against a peer that accepts, answers `WELCOME` and then never reads, the
   handler fails over within `failover_timeout_sec` plus the send timeout.
   (Fails today: blocks.)
3. A handshake that fails after connect leaves no open descriptor (count
   `/proc/self/fd`). (Fails today.)
4. `log_server.enabled: "false"`, `pubsub_enabled: "no"` and
   `name: "a|b"` are refused by the loader with a message naming the field.
   (Fails today.)
5. `enabled: false` still makes `pm-log-srv` exit 0 with its warning,
   unchanged.

**Change.** Reset `_seq` on handshake; `settimeout` after the handshake and
treat a timeout as a disconnect; close in `_try_connect`'s `except`; strict
booleans and a `name` check in `config.py`.

**Exit criteria.** Tests 1–5 pass; suites green; `make completion` not
needed (no argparse change).

**Outcome (2026-11-16).**
- C6: `emit()` still builds the frame (Q2), but with `SEQ=0`; the background
  thread writes the connection's next number into the `LOG|SEQ=0|` prefix as
  it sends (`_numbered`), and resets the counter on every handshake. A held
  frame resent on a new connection gets that connection's number.
  `_build_log_frame` takes `seq` (default 0) and no longer needs a lock.
- C7: after `WELCOME` the socket keeps a timeout of
  `max(failover_timeout_sec, 2 s)` (`_MIN_SEND_TIMEOUT_SEC`); a `sendall` that
  times out is an `OSError` like any other disconnect, so the frame is held
  and the failover clock starts.
- C8: `_try_connect` closes the socket on every failed handshake.
- C10: `log_server.enabled` and `pubsub_enabled` must be YAML booleans
  (`_as_bool`, same wording as pm-md-gwy), and `name` must not contain `|` or
  a line break. `pm-config-deploy` and `pm-cverifier` (S101, through the
  loader) refuse them; S096 already flagged the booleans.

Tests: `tests/test_logclient_handler.py` (a fake peer that ends the first
session after three frames: the second session's first `LOG` had `SEQ=5`
before, `1` now; a peer that sends `WELCOME` and never reads, 60 MB queued:
no failover within 8 s before, failover now; ten failed handshakes: ten
`ResourceWarning: unclosed socket` before, none now) and
`tests/test_log_server_pubsub_config.py` (the loader refuses `"false"`, `"no"`,
`a|b`, `a\nb`; pm-cverifier reports S101 for `a|b`; all "DID NOT RAISE" or no
finding before). Test 5 (`enabled: false` exits cleanly) is the existing
`tests/test_log_srv_main.py::test_main_exits_cleanly_when_log_server_disabled`.
No argparse change. Full suite: 14778 passed, 1 skipped, 1 failed outside
this scope (`tests/test_shell_completion.py[zsh]`, stale completion for an
`alf_console` help text another session is changing).

### WP-LOG08 — Texts describe the final code (D1, D2, D4, D7, D8)

**Tests first.** `tests/test_pm_help.py` gains a check that every option the
registry lists for `pm-log-srv` exists in `build_parser()` and vice versa.
(Fails today: `--log-file` missing.) The rest is text, checked by re-walking
each passage against the code (lessons-learned §B1).

**Change.** Guide: start-up options table and output line (D1), the phased
rollout note (D2), `HELLO_TIMEOUT` and reason list in `050-lalf.md` (D4,
including WP-LOG02's reasons), configuration reference §6.7 (D7),
`build_log_frame` docstring (D8), `logclient/__init__.py` and the registry
notes (D2).

**Exit criteria.** The registry test passes; `make _check` clean; every D-row
re-checked against the code.

**Outcome (2026-11-16).**
- Test: `tests/test_pm_help.py::test_the_pm_log_srv_options_match_its_parser`
  compares the registry's flags with `build_parser()`; it failed first on
  `--log-file` (and `--version`, which the renderer adds to every page through
  `COMMON_VERSION_OPTION`, so the test leaves it out).
- D1: registry gains `--log-file PATH`. Guide start-up table: `--config`/`-c`
  removed, `--log-target` and `--log-file` added, and the sentence says the
  `log_server:` block comes from the deployed configuration. The start-up
  transcript was **re-run** (`pm-log-srv -v` against a scratch database) and
  now shows the `config_artifact` line, the LALF-PS line before the listening
  line, and resolved paths with `(cwd=...)`. The run also showed that a
  relative `--db` resolves against the data directory, not the working
  directory; the guide now says so.
- D2: the guide's "Phased rollout" note is replaced by "How processes find
  the server"; the registry note, the `logclient/__init__.py` docstring and
  design §8.7 now say what is wired (26 entry points call `resolve_handler`).
- D4: `050-lalf.md`: the `HELLO_TIMEOUT` row, its implementation note and the
  "What to watch out for" item describe the one flush pass; the
  `disconnect_reason` list gains `io_error`, `server_stop` and
  `server_restart`, and loses `hello_timeout` (a connection that never
  completed its handshake has no stored row). The guide's `disconnect_reason`
  paragraph and the fallback-to-file heuristic row say the same.
- D7: reference manual §6.7 (`030-formal-specification.md`): `enabled: false`
  makes `pm-log-srv` exit at once; `max_client_queue` is both the per-client
  reply limit and the global writer backlog at which all reads stop.
- D8: `build_log_frame` docstring says it returns the bytes only.
- D3, D5, D6 and D9 were done in WP-LOG05, 01, 06 and 06.

Every D-row was re-checked against the code. Re-walking the flows these WPs
changed found nothing to fix, but two behaviours are worth knowing: after an
end-of-day stop in which `pm-log-srv` goes down before the other processes,
`diagnose` reports each process with the `server_stop` wording (before
WP-LOG02 they were "stuck" `process_silence` warnings); and a process that
exits while `pm-log-srv` is unreachable but before failover now waits up to
`connect_timeout_sec` + 2 s while it drains. Full suite: 14783 passed,
1 skipped, 1 failed outside this scope (the same stale zsh completion for
another session's `alf_console` help text).

---

## 9. Out of scope, noted

- **log-GUI live view gaps (L038).** `lalf-ps-uplink.ts:247-253` re-subscribes
  on `server_state UP` only when its state is not ACTIVE. After a server crash
  and restart inside its 15-second heartbeat budget it stays ACTIVE until the
  next renew returns `UNKNOWN_SUB` (up to 15 s), and rows of that window never
  reach the live view. It also ignores `dropped` (and would ignore Q5's
  `msg_no`), so the view shows no marker for a gap. Recorded as L038.
- **book-GUI bridge LALF client.** It omits `MODULE` and `LINE`, which the
  specification allows; the server-side fix is C3. Whether its `SEQ` restarts
  per connection was not checked.
- **pm-md-gwy** closes every session without `EXIT` on stop (L036), the same
  shape as C1 on the CALF side; not changed here.

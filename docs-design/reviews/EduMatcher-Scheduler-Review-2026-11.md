# pm-scheduler Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/scheduler/` at `5acf9b03` (v0.81.2): `main.py`
(1460 lines, the whole process: schedule resolution, catch-up and
reconcile planning, the transition loop, the `--on-close` hook and the
CLI); `__init__.py` is empty. Read where they decide the scheduler's
behaviour, not reviewed as code of their own: the engine's session handlers
(`engine/main.py` `_handle_session_transition`, `_handle_session_next`,
`_handle_session_state_request`, the boot state and `_announce_startup`),
`models/session.py` (`VALID_TRANSITIONS`), `engine/schedule_resolve.py`,
`engine/config_loader.py` (`normalize_hhmm`, `_parse_day_schedule`), and the
two consumers of the scheduler's `CLOSED`: pm-clearing's close snapshot
(`clearing/main.py:1020-1049`) and pm-eod's gate (`eod/runner.py:146-186`).

**Focus:** correctness, edge-case handling, performance, and whether the
comments, help texts, the `pm-help` entry, the log ledger
(`log_ledger/entries/scheduler.yaml`), the operator guide chapter
(`part-4-run-a-market/030-sessions-and-scheduling.md`), the reference manual
and the training and AI-trader books say what the code does.

**Previous work:** `EduMatcher-scheduler-review.md` (H1–H3, M1–M3, L1–L7,
A1–A3) and the 2026-11-05 scheduler/log-server review (off-path reconcile,
`--on-close` only on a confirmed `CLOSED`), plus the design items F8, I76,
I93 (health-beacon liveness) and T-M6 (countdown target). Their fixes are in
place and are not repeated here: catch-up to the current phase, bounded
`SNDTIMEO`/`LINGER`, strict `HH:MM` parsing in the loader, chain and order
validation at start-up, the start-up state query and per-transition
confirmation, one shared transition loop, `logging` instead of `print`,
`--daily`, per-day schedules and bank holidays, session-timezone DST policy,
wall-clock re-derivation of waits, compressed mode, the shortest-route
reconcile of off-path states, and the CLOSED-gated `--on-close` hook.

**Method:** every line of `main.py` was read, with the shared code above.
Findings marked *(repro)* were reproduced with a scratch harness against the
tree at `5acf9b03` that drives the real scheduler functions (`_run_scheduled`,
`_run_transitions`, `_run_now`, `_query_engine_state`) against a real
`Engine` built with `tests/engine_harness.make_engine(sessions_enabled=True)`:
a PUSH stand-in hands each message to the engine's own handler, and a SUB
stand-in reads the engine's published `session.state` and
`system.session_status.*` frames in order. *(measured)* means timed on this
host. The other findings are by inspection, with line numbers given.

Status: **Open.** Decisions Q1–Q2 are needed before WP-SCH01 and WP-SCH04.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (the transitions the engine receives and applies, the
   engine's final state, warnings logged, whether `--on-close` fires, CLI
   exit status and message).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_scheduler_*.py`,
   `tests/test_schedule_resolution.py` and
   `tests/test_gateway_and_scheduler.py` with `-n logical`, then
   black/flake8/mypy/pyright. Do not start the next WP with a known failing
   test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

The correctness tests should drive the scheduler against a real engine, not
a mock that answers what the test expects: build the engine with
`tests/engine_harness.make_engine(..., sessions_enabled=True)` and connect it
through two small doubles (a PUSH side that calls the engine's
`_handle_session_transition` / `_handle_session_next` /
`_handle_session_state_request`, and a SUB side with `poll`/`recv_multipart`
over the engine's `pub_sock.sent`), as in the repro harness described under
Method. A shared helper in a new `tests/scheduler_harness.py` keeps the WPs
from copying it. The clock is a `_Clock(speed, start)` patched onto
`sched._clock`; use `speed=1.0` where the test must not cross a schedule
time by accident.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-SCH01 | Only the engine's answer to this request confirms it | C3 | — | 0.5 d | ☐ | |
| 2 | WP-SCH02 | An unknown engine state never replays a closed day | C2 | — | 0.25 d | ☐ | |
| 3 | WP-SCH03 | An engine restart is followed by the schedule within seconds | C1 | Q1, WP-SCH01 | 1 d | ☐ | |
| 4 | WP-SCH04 | `--now` starts from CLOSED and reports what the engine applied | C4 | Q2, WP-SCH01 | 0.5 d | ☐ | |
| 5 | WP-SCH05 | Bad flags are usage errors; the close hook never drops a trigger | C5, C6 | — | 0.5 d | ☐ | |
| 6 | WP-SCH06 | Comments, help texts, ledger, guides | D1–D9 | WP-SCH01–05 | 0.5 d | ☐ | |

Suggested order: **WP-SCH01 → WP-SCH02 → WP-SCH03 → WP-SCH04 → WP-SCH05 →
WP-SCH06**. WP-SCH01 first because WP-SCH03 and WP-SCH04 add more queries and
confirmations, and those are only worth anything once a queued message from
somebody else cannot answer them. WP-SCH02 is a one-line rule with the
largest blast radius per occurrence (a whole replayed day). WP-SCH03 is the
headline operational defect but needs Q1. The text-only WP goes last so the
texts describe the final code.

Estimated sequential effort: about 3.25 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The **schedule side** is sound. Times are normalised once in the loader
(`config_loader.py:206-236`, unquoted `9:30` included), every distinct day
block is checked for a legal chain from `CLOSED` and strictly increasing
times before anything is sent (`main.py:293-359`), day resolution is shared
with the engine (`schedule_resolve.resolve_day`), and DST is handled with one
explicit policy (`_local_instant`, later instant wins) for waits, catch-up and
the published countdown. Waits re-derive from the wall clock every 0.5 s and
tick the health beacon on every wake-up. Sends cannot block (2 s `SNDTIMEO`,
1 s `LINGER`). At start-up the scheduler asks the engine where it is and
either replays what is missing or routes an off-path engine to the scheduled
phase by the shortest legal path.

The defects are in the **closed loop** with the engine, which is only closed
at start-up:

- **An engine restart is never followed (C1).** The engine boots `CLOSED`.
  A running scheduler does not notice; every later transition that day is
  rejected, the market stays closed until the next morning, the day's `CLOSED`
  never happens (so its `DAY` orders survive into the next day and pm-eod never
  settles it as its own date), and `--on-close` does not fire. The AI-trader
  book documents the workaround: kill the scheduler.
- **An unknown engine state replays a closed day (C2).** With `--no-confirm`,
  or when the start-up query gets no answer within 2 s, a scheduler started
  after the close sends all five transitions in a few milliseconds: a second
  opening and closing auction, a second end-of-day archive, a second `CLOSED`
  for pm-clearing, and an `--on-close` run.
- **Confirmations are not tied to the request (C3).** Any queued
  `session.state` with the right state name confirms a transition, including
  an operator's from hours earlier; a late state reply answers the next query.
  A rejected close was reported as applied and fired `--on-close`.
- **`--now` is open-loop (C4).** From any state but `CLOSED` it sends five
  transitions, the engine rejects three, and the log is identical to the
  successful run the training guide shows as the expected output.
- **CLI and hook edges (C5, C6).** `--speed nan`/`inf` and a quote error in
  `--on-close` are tracebacks; an empty `--on-close` crashes the timer thread;
  a close trigger that arrives while the start-up run is still busy is
  dropped, and a single-shot run never retries it.

The process does nothing expensive: performance needs no work (§4).

Severity key: **High**: money or data lost or misattributed without a
warning. **Med**: a wrong market phase for a significant time, a day that
does not close or closes twice, or a failure reported as a success.
**Low**: hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| C1 | Med | Closed loop | Engine restart mid-day: the next two transitions are rejected (`CLOSED → CLOSED`), the engine stays `CLOSED` for the rest of the day, the day never closes, `--on-close` does not fire *(repro)* | SCH03 |
| C2 | Med | Catch-up | Unknown engine state after the close (`--no-confirm` or 2 s query timeout) replays the whole day: 10 `session.state` broadcasts instead of 5, a second `CLOSED`, `--on-close` fires *(repro)* | SCH02 |
| C3 | Med | Closed loop | A queued broadcast from another producer confirms a rejected transition (and fires `--on-close`); a late state reply answers the next query (`CLOSED` read while the engine is `CONTINUOUS`) *(repro)* | SCH01 |
| C4 | Low | `--now` | From `CONTINUOUS`, 3 of 5 transitions are rejected, nothing is logged, the run ends "Done."; training ch. 01 Ex. 7 leads straight into this *(repro)* | SCH04 |
| C5 | Low | CLI | `--speed nan`/`inf` → `ValueError`/`OverflowError` traceback; `--on-close ''` → `IndexError` in the timer thread; unbalanced quote → `ValueError` traceback; negative `--on-close-delay` accepted; `--now --daily` ignores `--daily` silently *(repro)* | SCH05 |
| C6 | Low | `--on-close` | A close trigger that fires while the start-up run is still busy is skipped; a single-shot run never retries it, and its shutdown waits for the child however long it takes | SCH05 |
| D1–D9 | — | Texts | See §5 | SCH06 |

---

## 3. Correctness findings

### C1. An engine restart leaves the market closed for the rest of the day *(repro)* — Med

`main.py:837-903` `_run_transitions`, `main.py:906-931`
`_dispatch_transition`; engine boot `engine/main.py:820-822`.

With `sessions_enabled: true` the engine always boots `CLOSED`. The
scheduler queries the engine's state once per day, in `_run_scheduled`
(`main.py:985-993`), and never again. After that, an unconfirmed transition
only logs a warning (`main.py:926-931`) and the loop moves on to the next
step, which the engine rejects from the same wrong state.

Repro: scheduler started on Tuesday 2026-11-17 at 08:59, the engine
replaced by a freshly booted one just before the 16:00 transition.

```
transition sent   engine before   -> engine after
PRE_OPEN          CLOSED          -> PRE_OPEN
OPENING_AUCTION   PRE_OPEN        -> OPENING_AUCTION
CONTINUOUS        OPENING_AUCTION -> CONTINUOUS
   [engine restarted -> boots CLOSED]
CLOSING_AUCTION   CLOSED          -> CLOSED      (rejected)
CLOSED            CLOSED          -> CLOSED      (rejected)
final engine state: CLOSED     --on-close triggered: 0
```

With the restart at 10:00 instead, the result is the same: the market is
closed from 10:00 until 09:00 the next day.

Consequences, beyond a lost trading day:

- **The day never closes.** The restarted engine publishes no
  `session.state` at boot (`make_session_state_msg` is sent only from
  `_handle_session_transition`, `engine/main.py:6417`), and both later
  transitions are rejected, so there is no `CLOSED` for the date.
  `_expire_tif(TIF.DAY)` and `_archive_eod` never run (`engine/main.py:6389-6394`):
  the `DAY` orders the restart restored keep resting into the next day's
  pre-open. pm-clearing records no close for the date
  (`clearing/main.py:1020-1049`), so `closed_trade_dates` never lists it and
  pm-eod never settles it as its own day (`eod/runner.py:146-186`); its
  trades fold into the next settled day.
- **`--on-close` does not fire** (`main.py:897-901`), by design for an
  unconfirmed close.

How it is triggered: an engine crash and restart by the container watchdog,
an operator restarting pm-engine for a config change, an engine OOM in a
long AI-trader run. The AI-trader book (`150-running-it-for-weeks.md:29`,
`160-troubleshooting-and-faq.md:10`) documents it and tells the operator to
kill pm-scheduler so the watchdog restarts it. The operator guide and the
log ledger say nothing about it beyond "restart pm-scheduler to reconcile".

The engine does announce a start: `system.startup` is the first thing it
publishes (`engine/main.py:1630-1660`), after its PUB settle, and pm-audit
relies on receiving it.

**Fix.** Re-synchronise during the day, not only at start-up: when the
engine announces a start, and after any unconfirmed transition, query its
state and bring it to the phase the schedule says is current with the
existing `_plan_catch_up` logic. See Q1 for the trigger.

---

### C2. An unknown engine state replays a day that has already closed *(repro)* — Med

`main.py:719-739` `_catch_up_transitions`, `main.py:764-793` `_plan_catch_up`.

When the engine's state is unknown, `_catch_up_transitions` replays *every*
past transition (`main.py:731-732`). After 16:05 that is the whole day. The
comment calls this "assumes the engine booted CLOSED", but an engine that
booted `CLOSED` and had the day's five transitions applied is also `CLOSED`,
and the replay is legal from there: every transition is accepted.

Repro: engine driven through a full day, scheduler (re)started at 17:00.

| Case | Transitions applied by the engine | `session.state` broadcasts (5 = the real day) | `--on-close` |
|---|---|---|---|
| `--no-confirm` | `PRE_OPEN`, `OPENING_AUCTION`, `CONTINUOUS`, `CLOSING_AUCTION`, `CLOSED` | 10 | 1 |
| query unanswered (2 s timeout) | the same five | 10 | 1 |
| query answered `CLOSED` | none | 5 | 0 |

What the replay does, in milliseconds: an opening uncross and a closing
uncross on whatever rests in the books (`engine/main.py:6366-6370`), the
closing backstop, ATO/ATC/DAY expiries, the per-symbol daily counters reset
at `PRE_OPEN` (`engine/main.py:6400-6407`), a second `_archive_eod`, and a
second `CLOSED` for the date, which pm-clearing judges against
`close_snapshot_is_final` (`clearing/main.py:1020-1023`). The log ledger's
explanation of the start-up warning says only that "some of them are
refused".

How it is triggered: `--no-confirm` is a documented flag; the 2 s query
timeout is hit when the engine is busy restoring a large book at start, or
when the SUB subscription has not propagated within the 0.1 s settle
(`main.py:1413-1415`), so the reply is lost.

**Fix.** Unknown state means "assume CLOSED", and realign on that
assumption: `_catch_up_transitions(past, SessionState.CLOSED)` already
returns nothing after the day's `CLOSED` and the full replay before it. A
morning start is unchanged; a start after the close sends nothing.

---

### C3. Confirmations and state replies are not tied to the request *(repro)* — Med

`main.py:652-678` `_confirm_transition`, `main.py:681-716`
`_query_engine_state`.

The SUB socket subscribes to every `session.state` broadcast and to the
scheduler's own reply topic, and nothing reads it between transitions, which
can be hours apart. `_confirm_transition` accepts the *first* queued
broadcast whose `state` equals the expected one; `_query_engine_state`
accepts the first queued reply on its topic.

Repro 1: engine in `CONTINUOUS` at 15:00; an operator closes early
(`CLOSING_AUCTION`, `CLOSED`); the broadcasts wait in the scheduler's queue.

```
CLOSING_AUCTION   CLOSED -> CLOSED   (rejected)
CLOSED            CLOSED -> CLOSED   (rejected)
warnings logged: []   --on-close: 1
```

Both rejected transitions were "confirmed" by the operator's broadcasts.
Combined with C1 (an operator move earlier in the day, then an engine
restart), the stale confirmations hide a day that never closed and fire
`--on-close` on it.

Repro 2: a state reply that arrives after its query timed out (engine
`CLOSED` then), the engine is then opened by hand; the next query returns
`CLOSED` while the engine is `CONTINUOUS`. Under `--daily` a timed-out query
is followed by the next day's, which reads the stale reply first.

The engine's broadcast carries `prev_state` and the requester's `command_id`
(empty for the scheduler, set by operator commands,
`engine/main.py:6408-6424`).

**Fix.** Drain the SUB socket immediately before each send and each query,
so only what the engine published after the request can answer it, and
require an empty `command_id` on a confirmation. Both are local to the two
functions.

---

### C4. `--now` does not know where the engine is *(repro)* — Low

`main.py:1086-1111` `_run_now`.

`--now` sends the five transitions without a confirmation socket and without
asking the engine's state. From any state but `CLOSED` the first transitions
are rejected. Repro, engine in `CONTINUOUS`:

```
PRE_OPEN          CONTINUOUS      -> CONTINUOUS        (rejected)
OPENING_AUCTION   CONTINUOUS      -> CONTINUOUS        (rejected)
CONTINUOUS        CONTINUOUS      -> CONTINUOUS        (rejected)
CLOSING_AUCTION   CONTINUOUS      -> CLOSING_AUCTION
CLOSED            CLOSING_AUCTION -> CLOSED
scheduler log: -> PRE_OPEN, -> OPENING_AUCTION, -> CONTINUOUS,
               -> CLOSING_AUCTION, -> CLOSED, Done.
```

The log is line for line the "Expected output" of training ch. 01
Exercise 7 (`010-configuring-startup.md:407-418`), and that exercise gets
the student here: it first starts `pm-scheduler` during trading hours, which
catches up to `CONTINUOUS`, then says to stop it and run `--now`. The
student sees "all five transitions, ending with `Done.`" (the checkpoint),
but no opening auction happened. Chapter 06 avoids it by closing the day by
hand first (`060-time-in-force-sessions.md:59-67`); chapter 01 does not.

**Fix.** See Q2: route the engine to `CLOSED` first and confirm each
transition, as scheduled mode does.

---

### C5. CLI input that ends in a traceback or is silently ignored *(repro)* — Low

`main.py:1142-1152`, `main.py:1195-1210`, `main.py:1282-1295`, `main.py:530-552`.

| Input | Result |
|---|---|
| `--daily --speed nan` | passes `speed <= 0` (`nan <= 0` is False), then `_Clock.now()` raises `ValueError: cannot convert float NaN to integer` |
| `--daily --speed inf` | `OverflowError: cannot convert float infinity to integer` |
| `--on-close ''` | `shlex.split` gives `[]`; 30 s later `Popen([])` raises `IndexError` inside the timer thread (only `OSError` is caught, `main.py:552`): a thread traceback, no ledger row, no end-of-day run |
| `--on-close "pm-eod 'run"` | `shlex.split` raises `ValueError: No closing quotation` from `main()`: a traceback |
| `--on-close-delay -5` | accepted; the timer fires at once |
| `--now --daily` (also with `--speed`) | `--now` runs, `--daily` and `--speed` are ignored without a word |

Same class as lessons-learned A4/A5: validate in argparse.

**Fix.** `--speed` must be finite and > 0; `--on-close-delay` ≥ 0;
`--on-close` must split into at least one word (a usage error, not a
traceback); `--now` with `--daily`, `--speed` or `--start` is a usage error.

---

### C6. A dropped close trigger is never retried in a single-shot run — Low

`main.py:518-582` `_CloseHook`, `main.py:1421-1450`.

`main()` fires the hook once at start-up (`main.py:1422-1423`) and once per
confirmed `CLOSED`. `_spawn` skips a trigger while the previous child is
still running (`main.py:547-549`) and the docstring calls that safe "because
the next trigger picks up whatever was missed". In a single-shot run there
is no next trigger: started at 16:04, the start-up run of
`pm-eod run --pending` (which may settle several days and take a backup)
can still be running at 16:05:30, the close trigger is skipped, and the
process exits with today unsettled. Under `--daily` the next trigger comes
a day later.

Separately, a single-shot run's shutdown calls `close_hook.wait()`
(`main.py:1450`), which joins the timer and the child with no bound; SIGINT
during that wait sets `running = False` but nothing reads it, so Ctrl-C does
not stop the process until the end-of-day command finishes.

**Fix.** Coalesce instead of skipping: a trigger that arrives while a child
runs sets a flag, and the reaper starts the command once more when the
child exits. Keep the single-shot wait (the point of it is to let the
command finish) but say so on SIGINT with one INFO line naming the child's
PID.

---

## 4. Performance findings

None. The process sends at most seven messages per day and otherwise sleeps.
*(measured)*: an idle 5 s wait costs 0.54 ms of CPU (ten 0.5 s wake-ups with
the health tick); the first `_next_scheduled_day` across Christmas costs
54 ms (building the `holidays` calendar), 0.008 ms once cached;
`_is_supported_country` 0.1 ms. Nothing grows with history or with the day.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `pm_help/registry.py:553-557, 570-573` | "Fire-and-forget: does not subscribe to anything" — it subscribes to `session.state` and its own `system.session_status.SCHEDULER` (`main.py:1405-1419`) and confirms every transition. "at the times configured in engine_config.yaml" — it reads only the compiled artifact (`main.py:1340-1353`). `--daily`: "every calendar day" — working days only. |
| D2 | `reference-manual/.../010-processes-environment-and-ports.md:357, 1585-1593` | Ports table: "connects out to `5555` … ZeroMQ (PUSH)" — also SUB on `5556`. "Messages sent" lists only `session.transition` (also `session.next`, `system.session_state_request`), and "The scheduler does not subscribe to any PUB messages — it is fire-and-forget" is false. |
| D3 | `operator-guide/.../030-sessions-and-scheduling.md:257-262, 285` | "Use times from engine_config.yaml"; "Repeat the schedule every calendar day" (code comment and `--daily` row) — both as D1. Wall-clock section (`:531-539`): "wakes at least every 30 seconds … picked up within 30 seconds" — every wait passes `LIVENESS_CHUNK_SEC` (0.5 s, `main.py:874, 1081`). The chapter does not say what happens when the engine restarts (C1) or what `--no-confirm` costs after the close (C2). |
| D4 | `main.py:59-65, 185-189, 446-457, 1049-1053` | The module docstring, the `WALLCLOCK_RECHECK_SEC` comment, `_sleep_until_wallclock` ("never sleeps more than … (30s)") and `_run_forever` describe a 30 s re-check; no caller uses the 30 s default. The constant is only a default for a parameter both callers override. |
| D5 | `ai-traders/.../150-running-it-for-weeks.md:31` | "The scheduler re-reads the wall clock every few minutes" — every 0.5 s. |
| D6 | `log_ledger/entries/scheduler.yaml` ("could not determine engine state …") | "If the engine is in fact further on, some of them are refused" — after the close none are refused and the whole day is replayed (C2). The "not delivered" and "no confirmation" entries advise "restart pm-scheduler to reconcile"; after WP-SCH03 that is automatic. |
| D7 | `training-guide/010-configuring-startup.md:395, 404-436` | "after 16:05 on a weekday it catches up straight to `CLOSED`" — the engine is already `CLOSED`; the scheduler sends nothing and logs "Engine already at the current phase". The `--now` step that follows starts from whatever phase the first run reached (C4). |
| D8 | `ai-traders/.../150-running-it-for-weeks.md:29`, `160-troubleshooting-and-faq.md:10` | The engine-restart rows tell the operator to kill pm-scheduler; after WP-SCH03 the scheduler recovers by itself. |
| D9 | `main.py:723-729` | `_catch_up_transitions`: "When unknown, replay every past transition (assumes the engine booted CLOSED — the H1 fallback)" — changes with C2. |

---

## 6. Verified as correct

- **Schedule parsing and validation.** `normalize_hhmm` recovers YAML's
  sexagesimal integers and rejects `25:00`, `16:5:00` and booleans; every
  block must carry all five keys (`config_loader.py:239-263`); the scheduler
  refuses to start on an illegal chain or non-increasing times, reporting each
  bad block once with every label that shares it (`main.py:332-359`).
- **Day resolution.** Bank holidays beat the weekday entry; the scheduler and
  the engine use the same `resolve_day`; `--daily` skips CLOSED days to the
  next scheduled day's midnight and announces its pre-open.
- **DST.** A repeated local time runs on its second occurrence, a missing one
  is shifted by the gap; waits, catch-up classification and the UTC countdown
  use the same `_local_instant` (covered by `tests/test_scheduler_dst.py`).
- **Off-path reconcile.** Stale early phases are kept and the schedule
  resumes after them; `CONTINUOUS`/`CLOSING_AUCTION` off the day's path are
  routed by `_route` (BFS over `VALID_TRANSITIONS`, deterministic ties).
- **Transport bounds.** `SNDTIMEO` 2 s and `LINGER` 1 s on the PUSH socket;
  every `send_multipart` catches `zmq.ZMQError`; every wait polls in 0.5 s
  slices that tick the health beacon (I76, I93).
- **Compressed mode.** Sim-time days and holidays, wall-time waits and
  countdown instants; an aware `--start` is converted to session-local time.
  `EDUMATCHER_SCHEDULER_SPEED` set without `--daily` is a usage error on
  purpose (an existing test asserts it).
- **Sessions disabled.** The scheduler idles and keeps beaconing rather than
  sending transitions the engine refuses.
- **`--on-close` gating.** It fires only after a confirmed `CLOSED`
  (`main.py:897-901`), modulo the stale confirmations of C3.

---

## 7. Decisions

| # | Question | Recommendation |
|---|---|---|
| Q1 | What makes a running scheduler re-synchronise with the engine (C1)? (a) the engine's `system.startup` broadcast (subscribe to it; on receipt query the state and reconcile to the scheduled phase), plus a re-query after any unconfirmed transition; (b) a periodic state query (every 30 s) that reconciles any mismatch; (c) only a re-query after an unconfirmed transition | **(a)**: it reacts within seconds to exactly the event that breaks the day, and leaves an operator's deliberate move (an early close, a frozen phase in training ch. 06) alone. (b) would undo those moves within 30 s. (c) alone leaves the market closed from the restart until the next scheduled time (10:00 → 16:00), and then reopens it only for the closing auction. The re-query in (a) covers a lost `system.startup`. |
| Q2 | What does `--now` do when the engine is not `CLOSED` (C4)? (a) ask the engine's state, route it to `CLOSED` by the shortest legal path, then run the day, confirming each step and warning on a rejection (with `--no-confirm` keeping today's blind behaviour); (b) refuse to start unless the engine is `CLOSED`; (c) only document "close the day first" in ch. 01 | **(a)**: `--now` exists to show every phase, and (a) does so from any starting point, which is what the training exercise assumes. (b) adds a manual step the student has to look up. (c) leaves the log claiming five transitions that did not happen. |

---

## 8. Work packages

### WP-SCH01 — Only the engine's answer to this request confirms it (C3)

**Tests first** (`tests/test_scheduler_closed_loop.py`, real engine via
`tests/scheduler_harness.py`):

1. Engine in `CONTINUOUS`; an operator transition pair `CLOSING_AUCTION`,
   `CLOSED` is published before the scheduler sends its own two → both
   `_dispatch_transition` calls return False, two "no confirmation" warnings
   are logged, `on_closed` is not called. (Fails today.)
2. A `system.session_status.SCHEDULER` reply with `CLOSED` is queued, the
   engine then moves to `CONTINUOUS`; `_query_engine_state` returns
   `CONTINUOUS`. (Fails today.)
3. An operator-driven broadcast (non-empty `command_id`) published after the
   send with the expected state does not confirm it. (Fails today.)
4. Normal scheduled day against the engine: all five confirmed, `on_closed`
   called once, unchanged.

**Change.** A `_drain(sock)` helper (non-blocking `recv` until `zmq.Again`)
called right before the send in `_dispatch_transition` and before the
request in `_query_engine_state`; `_confirm_transition` also requires
`command_id == ""`.

**Exit criteria.** Tests 1–4 pass; scheduler suites green; mypy/pyright
clean.

---

### WP-SCH02 — An unknown engine state never replays a closed day (C2)

**Tests first** (`tests/test_scheduler_closed_loop.py`):

1. Full day applied, scheduler started at 17:00 with `confirm_sock=None` →
   the engine receives no transition, `on_closed` not called. (Fails today.)
2. Same with a confirm socket whose state query is never answered → no
   transition. (Fails today.)
3. Start at 10:00 with `confirm_sock=None` and a freshly booted engine →
   `PRE_OPEN`, `OPENING_AUCTION`, `CONTINUOUS` applied, unchanged.
4. `_catch_up_transitions(past, None)` equals
   `_catch_up_transitions(past, CLOSED)` for every prefix of the day.
   (Fails today for the full day.)

**Change.** In `_catch_up_transitions` (or `_plan_catch_up`) treat
`engine_state is None` as `SessionState.CLOSED`; update its docstring (D9).

**Exit criteria.** Tests 1–4 pass; existing
`TestA2CatchUpTransitions.test_unknown_state_replays_all` is updated to the
new rule (it encodes the defect) and the change is named in the outcome;
scheduler suites green.

---

### WP-SCH03 — An engine restart is followed by the schedule within seconds (C1; after Q1, WP-SCH01)

**Tests first** (`tests/test_scheduler_closed_loop.py`):

1. Scheduler driving a day; at 10:00 the engine is replaced by a freshly
   booted one and publishes `system.startup` → within one wake-up the engine
   is back in `CONTINUOUS` (catch-up `PRE_OPEN`, `OPENING_AUCTION`,
   `CONTINUOUS`), and the 16:00/16:05 transitions are applied and confirmed;
   `on_closed` is called once. (Fails today.)
2. Same restart but the `system.startup` frame is lost → the 16:00
   transition is unconfirmed, the scheduler re-queries, routes the engine to
   `CLOSING_AUCTION`, and the 16:05 `CLOSED` is applied. (Fails today.)
3. An operator closes the market at 15:00 (no engine restart) → the
   scheduler does not reopen it before 16:00. Unchanged.
4. Engine restart after the close → nothing is sent. (Passes once
   WP-SCH02 is in.)

**Change.** Subscribe the confirm socket to the engine's startup topic as
well. Make the waits in `_run_transitions` poll that socket (the existing
`_poll_live` slices) instead of `time.sleep`; on a `system.startup`, and
after an unconfirmed transition, re-query the state, run `_plan_catch_up`
against the schedule's current partition, and continue with what remains.
`_run_scheduled` builds the step list from a function it can call again for
this purpose.

**Exit criteria.** Tests 1–4 pass; scheduler suites and
`tests/test_gateway_and_scheduler.py` green; the restart repro of §3 C1 ends
with the engine in `CLOSED` after a confirmed close and `--on-close`
triggered once.

---

### WP-SCH04 — `--now` starts from CLOSED and reports what the engine applied (C4; after Q2, WP-SCH01)

**Tests first** (`tests/test_scheduler_closed_loop.py`):

1. Engine in `CONTINUOUS`; `--now` → the engine receives `CLOSED`, then the
   five day transitions, all applied; the log names the reconcile step.
   (Fails today.)
2. A transition the engine rejects during `--now` is logged as "no
   confirmation" at WARNING and the final line is not "Done.". (Fails
   today.)
3. `--now --no-confirm` from `CLOSED`: five transitions sent, "Done.",
   unchanged.

**Change.** `main()` builds the confirm socket for `--now` too (unless
`--no-confirm`); `_run_now` queries the state, prefixes the steps with
`_route(state, CLOSED)`, and passes the socket to `_run_transitions`, which
returns whether every step was applied.

**Exit criteria.** Tests 1–3 pass; scheduler suites green.

---

### WP-SCH05 — Bad flags are usage errors; the close hook never drops a trigger (C5, C6)

**Tests first** (`tests/test_scheduler_cli.py`, `tests/test_scheduler_on_close.py`):

1. `--daily --speed nan`, `--speed inf`, `--speed 0` → exit 2 with a usage
   message, no traceback. (Fails today for nan/inf.)
2. `--on-close ''` and `--on-close "pm-eod 'run"` → exit 2. (Fails today.)
3. `--on-close-delay -1` → exit 2. (Fails today.)
4. `--now --daily` → exit 2. (Fails today.)
5. A trigger while the child runs → the command runs a second time after the
   first exits; two triggers while it runs → still exactly one re-run.
   (Fails today.)
6. A trigger when no child runs starts it once, unchanged.

**Change.** `type=` validators for `--speed` and `--on-close-delay`;
`--on-close` split and checked in `main()` with `parser.error`; the `--now`
combinations checked next to the existing `--speed`/`--start` rule;
`_CloseHook` keeps a `_pending` flag that `_reap` consumes; one INFO line
when a single-shot shutdown waits for the child.

**Exit criteria.** Tests 1–6 pass; `make completion` regenerated if the help
changes; scheduler suites green.

---

### WP-SCH06 — Comments, help texts, ledger, guides (D1–D9)

Rewrite each text in §5 to what the code does after WP-SCH01–05: the
`pm-help` entry and reference manual (subscriptions, messages, ports,
"working day"), the operator chapter (compiled artifact, 0.5 s re-check, a
short "If the engine restarts" paragraph, what `--no-confirm` gives up), the
module docstring and wait comments, the ledger explanations, training ch. 01
Exercise 7 (the after-close case and `--now` from any phase), and the two
AI-trader rows. Re-walk each documented flow against the final code
(lessons-learned B1): the ch. 01 and ch. 06 exercises, `--on-close` with
pm-eod, a container watchdog restart of pm-engine.

**Exit criteria.** `make _check` clean (including `pm-log-cli ledger
check` via the ledger test); `poetry run mkdocs build` without new
warnings; every row of §5 addressed.

---

## 9. Out of scope, noted

- **The engine does not say when it entered its state.** A scheduler started
  after an outage that spanned a close finds the engine in, say,
  `CONTINUOUS` from yesterday; that is on today's path, so it is accepted as
  today's phase and the day boundary (DAY expiry, archive, counter reset,
  opening auction) never happens. A `--daily` scheduler that stays up routes
  such an engine to `CLOSED` at midnight, which covers the common case. A
  real fix needs the engine to report the trading date of its last
  transition on `system.session_status`. Recorded as **L042** in
  `EduMatcher-For-Later-ToDo.md`.
- `EDUMATCHER_SCHEDULER_SPEED` in the environment makes a plain
  `pm-scheduler --now` in the container a usage error. Deliberate (2026-11-05
  decision, asserted by a test); noted only so it is not reported again.

# pm-opctl-cli Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/emo/` at `0ab90bdd` (v0.84.0): `cli.py` (1 464
lines: the six built-in profiles, `emo-config.yaml` loading and validation,
PID files and re-adoption, `start`/`list`/`health`/`stop`/`kill`/`init`/
`show`/`clear`), `__init__.py` (1) and `README.md` (216). Read where they
decide this tool's behaviour, not reviewed as code of their own: the
container entrypoint and compose files that drive it
(`deployment/docker/entrypoint.sh`, `compose*.yaml`, `Dockerfile`), the data
files of every process it clears (`config.py:254-275`,
`market_sim/main.py:100`, `market_sim/news_history.py:17`,
`ai_trader/worker.py:126`, `engine/main.py:1581-1600`), and the healthcheck
commands it runs (`pm-monitor-cli health`, `monitor/cli.py:242-290`,
`monitor/collector.py:94`).

**Focus:** correctness, edge-case handling, performance, and whether the
comments, `--help`, the pm-help registry, `emo/README.md`, the operator
guide (`docs/books/operator-guide/part-3-run/010-running-the-exchange.md`,
`part-6-observe-and-recover/010-persistence.md`), the reference manual
(`docs/books/reference-manual/part-1-command-line/010-processes-environment-and-ports.md:3904-4005`)
and the guides' `clear`/`stop` procedures say what the code does.

**Previous work:** no earlier review of this component. Fixes already in
place and not repeated here: `stop` in waves (others → engine → recorders →
log server, `549ff737`/`15708884`), the audit healthcheck before the engine
starts, `pm-log-srv` first and waited for, `clear` removes SQLite `-wal`/
`-shm`/`-journal` companions (monitor review I107), `clear` warns about live
pm-* processes using `_is_pm_program` (which ignores `npm-cli.js`, shell
`-c` text), `--no-tcp-probe` for `list`, `pipe_safe`. The API-gateway review
saw `stop` leave a hung `pm-api-gwy` behind (its H2, fixed in the gateway);
its note that `stop` then "exited 1" does not match today's code, which
returns 0 (C2).

**Method:** every line of the files above was read. Findings marked *(repro)*
were reproduced with scratch scripts against the tree at `0ab90bdd`, using
the installed `pm-opctl-cli` with `EDUMATCHER_DATA_DIR` pointing at a
scratch directory whose `emo-config.yaml` defines harmless profiles (`sleep`,
`false`, a shell that ignores SIGTERM, a Python script named `pm-fakesched`
started with the scheduler's real arguments), so no real stack and no
process outside the scratch profile was touched. `kill` was reproduced by
running the real `kill_all_processes()` with only pkill's *pattern* replaced
by one that matches nothing (running the real command on this host would
signal unrelated processes). *(measured)* means timed on this host (Fedora,
procps-ng 4.0.6). The other findings are by inspection, with line numbers
given.

Status: **Done, uncommitted (2026-11-23).** All six WPs and a holistic
review done in one go; last full suite 15 521 passed, 1 skipped. Q1–Q5 taken
as recommended without an explicit answer (to confirm). Beyond the plan:
`stop` re-adopts lost entries (WP-OPC01), the container entrypoint tolerates
`start`'s new exit 1 (WP-OPC03), the holistic review's HR1–HR3, and a
port-race fix in a test of the pm-admin review.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (which processes are started, signalled or left
   alone, PID files, lines printed, the exit code, files deleted).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_emo*.py` with `-n logical`,
   then black/flake8/mypy/pyright. Do not start the next WP with a known
   failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Tests run the real functions against a `tmp_path` data directory
(monkeypatching `resolve_data_path`/`DATA_DIR` as the existing
`tests/test_emo_cli.py` does) with profiles of real, harmless child processes
(`sys.executable -c "import time; time.sleep(60)"`, a script that ignores
SIGTERM, `false`), each one killed in a fixture finalizer. `kill` is tested
by asserting which PIDs the new selection returns and signals, never by
signalling outside the test's own children.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-OPC01 | A PID file names its own process, or it is not trusted | H1, C1, C3, D1 | Q1 | 0.75 d | ☑ | 2026-11-23 |
| 2 | WP-OPC02 | `kill` stops every pm-* program and nothing else, and keeps track of survivors | H2 | Q2 | 0.5 d | ☑ | 2026-11-23 |
| 3 | WP-OPC03 | `start` and `stop` report what really happened | C2, C4 | Q3 | 0.5 d | ☑ | 2026-11-23 |
| 4 | WP-OPC04 | `clear` never deletes under a running process and covers every data file | C5, C6 | Q4, Q5 | 0.5 d | ☑ | 2026-11-23 |
| 5 | WP-OPC05 | Healthchecks get time to answer; process names are file names | C7, C8 | — | 0.25 d | ☑ | 2026-11-23 |
| 6 | WP-OPC06 | Comments, help texts and guides say what the code does | D2–D7 | WP-OPC01–05 | 0.5 d | ☑ | 2026-11-23 |

Suggested order: **WP-OPC01 → WP-OPC02 → WP-OPC03 → WP-OPC04 → WP-OPC05 →
WP-OPC06**. WP-OPC01 removes the path on which `stop` signals an unrelated
process and `start` skips a real one; the others build on its PID identity
(WP-OPC02 and WP-OPC03 decide which PID files survive a signal). WP-OPC06
goes last so every text describes the final code.

Estimated sequential effort: about 3 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The **profiles** are well documented in code and match what the container
images run; the `ai-sim` derivation keeps one source of truth for the
shared entries. **Start ordering** is right where it matters: `pm-log-srv`
first and waited for, `pm-audit` before `pm-engine` and proven healthy by
its own healthcheck. **`stop` ordering** (others, engine, recorders, log
server) matches what the recorders need, and `clear` removes SQLite
companions and never touches `ref_data/`. `health -q` exits 1 when no profile
is active, and every subcommand's expected errors (`OSError`, `ValueError`,
`yaml.YAMLError`) end in one line and exit 2.

The defects are in four places:

- **Process identity (H1, C1, C3).** A PID file is trusted as soon as *some*
  process has that PID. After a crash, a killed container or a reboot, the
  stale file's PID is often reused (containers restart from small PIDs, and
  the data directory with `emo/*.pid` is bind-mounted). `start` then skips
  the real process, `list` shows the stranger as running, and `stop` sends
  it SIGTERM; a root-owned stranger aborts `stop` half-way with exit 2.
  Re-adoption, meant to cover a lost PID file, cannot match the scheduler's
  own command line, so a restart loop starts a second scheduler.
- **The emergency stop (H2).** `kill` runs `pkill -15 -f -i -l pm-`. On
  procps-ng 4.0.6 `pkill` rejects `-l` and signals nothing, but the tool
  then deletes every PID file and the active profile anyway, so the next
  `stop` finds nothing to stop. Where `-l` is accepted, `-f -i pm-` matches
  any command line containing `pm-` in any case: `npm-cli.js`, an editor
  with a `pm-notes` file, the shell that ran the command, and pm-opctl-cli
  itself.
- **Reporting (C2, C4).** `stop` exits 0 and forgets a process that survived
  SIGTERM; `start` reports a process that died at once as started and
  exits 0.
- **`clear` (C5, C6).** It deletes the databases of running processes after
  only a warning (`--yes` skips the prompt), and its lists miss five data
  files, one of which (`market_sim_state.json`) brings the old market back
  after a "clean" restart.

Severity key: **High**: an unrelated process signalled, a stack left running
that the tool believes stopped, or a profile process silently not started.
**Med**: a wrong status or exit code that a script or supervisor acts on; data
deleted under a live writer; a duplicate singleton process. **Low**:
hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| H1 | High | PID files | A stale PID file whose PID now belongs to another process: `start` skips the entry ("already running"), `list` shows it running, `stop` SIGTERMs the other process *(repro)* | OPC01 |
| H2 | High | `kill` | `pkill … -l` is rejected by procps-ng 4.0.6 (exit 2): nothing is signalled, yet all PID files and the active profile are deleted; elsewhere the `-f -i pm-` pattern signals unrelated processes and pm-opctl-cli itself *(repro)* | OPC02 |
| C1 | Med | `stop` | One PID file pointing at another user's process (PID reuse) raises `PermissionError`: `stop` exits 2 after the first entry and every later entry and wave keeps running *(repro)* | OPC01 |
| C2 | Med | `stop` | A process alive 15 s after SIGTERM: warning, its PID file deleted, exit 0; a second `stop` says nothing is running *(repro)* | OPC03 |
| C3 | Med | Re-adoption | `ps` text loses argument quoting, so an entry with a spaced argument (`--on-close "pm-eod run --pending"`, every built-in scheduler) is never re-adopted; `list -y` / `EM_RESTART_DEAD` would start a second scheduler *(repro)* | OPC01 |
| C4 | Med | `start` | A process that exits immediately is printed as `started` and `start` exits 0 *(repro)* | OPC03 |
| C5 | Med | `clear` | Deletes `clearing.db`, `stats.db`, GTC files … under running processes after a warning; `--yes` proceeds without one | OPC04 |
| C6 | Low | `clear` | Not removed by either scope: `market_sim_state.json` (the model resumes its old values after `clear --state`), `audit_replay.db`, `market_sim_news.db`, `ai_swarm/`, `eod/<date>/` | OPC04 |
| C7 | Low | Health | 2 s healthcheck budget vs `pm-monitor-cli health`: 0.33 s start-up + slow-joiner + up to 1 s to the next snapshot leaves ~0.6 s headroom on an idle host *(measured)* | OPC05 |
| C8 | Low | Config | Process names are used as file names unchecked (`../x` writes outside `emo/`) | OPC05 |
| D1–D7 | — | Texts | See §5 | OPC01, OPC06 |

---

## 3. Correctness findings

### H1. A stale PID file is trusted whatever process now has the PID *(repro)* — High

`cli.py:628-640` `read_pid` accepts a PID when `os.kill(pid, 0)` succeeds
(or raises `PermissionError`); `resolve_pid` (`:696-702`) returns it before
any command-line check. `start` (`:1012-1016`), `list`/`health` and `stop`
(`:1073-1088`) all act on it.

PID files survive every exit that is not a clean `stop`: a crashed or
SIGKILLed process, a `docker kill`, a stop that outlived
`stop_grace_period` (30 s / 60 s, `compose*.yaml`, against up to four 15 s
waves), a reboot. In the container the data directory, `emo/` included, is
bind-mounted, and a new container numbers its processes from 1 again, so a
stale file's PID is very likely to belong to something else, including a
process started earlier in the same `start`.

Repro: a scratch profile `a` = `sleep 3001`, `b` = `sleep 3002`; `a.pid`
holds the PID of an unrelated `sleep 9999`:

```
--- start (victim pid 2455738 in a.pid)
  already running a (pid 2455738)
  started b (pid 2455746): sleep 3002
--- list
✅ a   2455738  00:00  2.7  running  no healthcheck or tcp check configured
--- stop
  stopped a (pid 2455738)
  stopped b (pid 2455746)
stop exit=0
VICTIM 2455738 WAS KILLED
```

Entry `a` was never started, `list` reported it running, and `stop`
terminated a process the tool never started. With a real profile the skipped
entry can be the engine or the log server, and the signalled process anything
the user owns.

**Fix.** See Q1: record the process's start time with its PID and trust the
file only when both match.

### H2. `kill` signals nothing on procps-ng 4, and the wrong processes elsewhere *(repro)* — High

`cli.py:1103-1120`:

```python
result = subprocess.run(["pkill", "-15", "-f", "-i", "-l", "pm-"], check=False)
for path in runtime.glob("*.pid"):
    path.unlink(missing_ok=True)
active_profile_path().unlink(missing_ok=True)
```

`-l` ("list name") is a `pgrep` option. procps-ng 4.0.6 (this host) rejects it
in `pkill`. Repro, the real `kill_all_processes()` with only the pattern
replaced by one that matches nothing:

```
Sending signal 15 to all matching EduMatcher processes...
  pkill exit 2: pkill: invalid option -- 'l'
pkill failed with exit code 2
kill_all_processes -> 2 | pid files left: [] | active-profile exists: False
```

Nothing is signalled, but the tracking is deleted first, so a following
`pm-opctl-cli stop` prints "No pm-opctl-managed processes are running" while
the whole stack runs on; `list` says no profile is active. The container
image's Debian bookworm procps was not checked here.

Where `pkill` does accept the flags, the selection is wrong by inspection:
`-f` matches the whole command line and `-i` ignores case, so every process of
the user whose arguments contain `pm-`/`PM-` is signalled: `npm-cli.js`, an
editor with `pm-notes.md` open, `rpm-ostree`. `pkill` never signals itself,
but `pm-opctl-cli` is a separate Python process whose command line contains
`pm-opctl-cli`: it receives SIGTERM and dies before deleting the PID files,
and so does the shell that ran `bash -c "pm-opctl-cli kill"`. The tool
already has the right selection: `_is_pm_program` (`:1228-1238`), written for
`clear`'s warning, accepts a process only when its program (argv[0], or the
script a Python interpreter runs) is a `pm-*` command, and
`_running_pm_pids` (`:1241-1264`) skips itself and its ancestors.

**Fix.** See Q2.

### C1. `stop` aborts at the first PID it may not signal *(repro)* — Med

`cli.py:1083-1087` catches only `ProcessLookupError` around
`os.kill(pid, SIGTERM)`. A PID file whose PID was reused by another user's
process (H1's mechanism; `read_pid` even returns such a PID on
`PermissionError`, `:638-639`) raises `PermissionError`, which leaves
`stop_profile` and is turned into exit 2 by `main` (`:1457-1459`).

Repro: profile `a`, `b` started; `a.pid` overwritten with `1`:

```
--- stop with a.pid -> pid 1 (root)
pm-opctl: [Errno 1] Operation not permitted
stop exit=2
2455849 sleep 3001
2455855 sleep 3002
```

Neither process was stopped. In the container `shutdown` runs
`pm-opctl-cli stop || true` and exits; Docker then SIGKILLs everything, so
the engine never writes its final persistence.

**Fix.** Part of WP-OPC01: an untrusted PID file (Q1) is never signalled; a
signal that fails for any other reason is reported per entry, and `stop`
goes on with the rest and exits non-zero at the end.

### C2. `stop` exits 0 and forgets a process that survived *(repro)* — Med

`cli.py:1081-1098`: the PID file is deleted when SIGTERM is *sent*
(`:1088`); after 15 s the survivors get a warning and the wave moves on; the
function returns 0. Repro with an entry that ignores SIGTERM:

```
  warning: stubborn still running 15s after SIGTERM; continuing
  stopped stubborn (pid 2456915)
stop exit=0 after 15 s
--- still alive after stop:  2456915 sleep 40
--- second stop:  No pm-opctl-managed processes are running.
```

A script `pm-opctl-cli stop && pm-opctl-cli clear --all --yes` proceeds
against a live process (C5); the next `start` finds the port taken. The
message order is also misleading: "stopped stubborn" is printed after the
warning that it did not stop.

**Fix.** See Q3.

### C3. Re-adoption cannot match an argument that contains a space *(repro)* — Med

`cli.py:657-681`: `command_line` reads `ps -o args=`, which joins argv with
spaces and loses the quoting; `matches_command` `shlex.split`s it again. An
argument with a space (`--on-close "pm-eod run --pending"`, in the scheduler
entry of `default`, `mm-demo`, `ai-swarm` and `ai-sim`, `:225-231`,
`:411-417`) splits into three tokens and never equals the profile's one.

Repro: an entry running a Python script `pm-fakesched --daily --on-close
"pm-eod run --pending"`, then its PID file deleted while it runs:

```
--- ps line:  python3 …/pm-fakesched --daily --on-close pm-eod run --pending
--- list after sched.pid was lost (process still running)
❌ sched   -   -   -  dead   process is not running
```

When the PID file of a running scheduler is lost (`clear --all` deletes
`emo/` while the stack runs, C5; a stale-file cleanup by `read_pid`), the
container's `EM_RESTART_DEAD=1` loop (`list --restart` every minute,
`entrypoint.sh:105-112`) or `list -y` starts a second pm-scheduler: two
processes driving session transitions and running `pm-eod` at every close.

**Fix.** Part of WP-OPC01: compare against the exact argv
(`psutil.Process(pid).cmdline()`), not `ps` text.

### C4. `start` reports a process that died at once as started *(repro)* — Med

`cli.py:1017-1022`: after `Popen` the entry is printed as `started` and
nothing checks that it is still alive; `start` returns 0 (`:1040`). Repro, an
entry `false`:

```
  started crashes (pid 2456762): false
start exit=0
```

A real process exits at once on a bad configuration, a port already taken
(H2 of the API-gateway review) or a missing deployed config. The container
entrypoint prints `list --no-restart` after `start`, so a person sees it, but
`start`'s exit code (what scripts and the e2e tests act on) says success.

**Fix.** After the last process is spawned, wait a short grace (1 s), check
every PID started by this run, print each one that has exited with its exit
code and the tail of its log path, and return 1.

### C5. `clear` deletes the databases of running processes — Med

`cli.py:1289-1312`: `_running_pm_pids()` produces a warning, and with
`--yes` (or a "y" at the prompt) the files are deleted regardless. A running
`pm-clearing`, `pm-stats` or `pm-engine` keeps writing to the unlinked inode
(SQLite holds the file open), so everything written until it restarts is
lost, and the engine rewrites `book_stats.json`/`gtc_orders.json` at its next
checkpoint, undoing the clear. `clear --all` also deletes `emo/`, so the tool
loses track of the running stack (C3's trigger).

Every guide procedure says to stop first
(`training-guide/110-risk-controls.md:454`, `quick-start/90-backmatter/010-faq.md:54`,
`000-installation.md:638`), and the README the same; the tool does not
enforce it, and `--yes` is what those procedures paste.

**Fix.** See Q4.

### C6. `clear` misses five data files — Low

`cli.py:1166-1193`. Data files written under `DATA_DIR` that neither scope
removes, against the persistence chapter's own list
(`operator-guide/part-6-observe-and-recover/010-persistence.md:102-111`):

| File | Writer | Consequence of keeping it |
|---|---|---|
| `market_sim_state.json` | pm-market-sim (`market_sim/main.py:100`) | After `clear --state` the model resumes its old true values while the engine's prices start from the configuration again; the anchored market maker and the value traders pull prices back to the previous run's. |
| `audit_replay.db` | pm-audit-replay (`config.py:264`) | After `clear --all` the episode index of a deleted audit trail remains. |
| `market_sim_news.db` | pm-market-sim (`news_history.py:17`) | News history of the previous run survives `--all`. |
| `ai_swarm/` | pm-ai-swarm (`ai_trader/worker.py:126`) | Daily trader summaries survive `--all`. |
| `eod/<date>/` | pm-engine (`engine/main.py:1581-1600`) | The engine's close archives survive `--all`. |

`engine_run_seq.json` is kept by design (trade ids never repeat into a
ledger, Clearing review §6), and `companies.db` is reference data built by the
container entrypoint.

**Fix.** See Q5.

### C7. The healthcheck budget barely covers pm-monitor-cli *(measured)* — Low

`cli.py:173`: `HEALTHCHECK_TIMEOUT_SEC = 2.0` for every healthcheck.
`pm-monitor-cli health -q` subscribes and waits for the next
`health.snapshot`, which pm-monitor publishes once a second
(`monitor/collector.py:94`), after a ZeroMQ slow join. Measured start-up
(`--version`): pm-monitor-cli 0.33 s, pm-stats-cli 0.37 s, pm-index-cli
0.31 s, pm-audit-cli 0.25 s. The monitor check therefore needs up to about
1.4 s on an idle host, leaving 0.6 s; on a host saturated by the ai-sim
profile (the Sim-vs-pytest note in the monitor review) Python start-up alone
can exceed that, and `list`/`health` report a healthy pm-monitor as
`not responding: … timed out after 2.0 seconds`.

**Fix.** Raise the budget to 5 s (healthchecks run only for live PIDs, so a
longer budget costs time only when a process is really hung).

### C8. Process names are used as file names unchecked — Low

`cli.py:584-587` checks only that a name is a non-empty string;
`pid_path`/`log_path` (`:510-515`) put it into a path, so a name containing
`/` or `..` writes outside `emo/`, and a name with a newline breaks the
status table. Names come from the operator's own `emo-config.yaml`
(lessons A5).

**Fix.** Refuse names that are not a single path component (no `/`, `\`, NUL,
newline, leading `.`).

---

## 4. Performance findings

Nothing here grows with history or with the day. `list` and `health` run one
`ps` per live process plus each configured healthcheck, sequentially; the
healthchecks dominate (*(measured)* Python start-up 0.25–0.37 s each, plus
the check itself: up to 1 s for pm-monitor's snapshot). Re-adoption adds one
`pgrep` and one `ps` per candidate, only for entries without a valid PID file.
With the default profile's five healthchecks a `list` takes a few seconds;
the container's restart loop runs it once a minute. No change is proposed
beyond C7's budget.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | Reference manual `010-processes-environment-and-ports.md:3984-3987` | "re-adopted on the next `list`/`health`/`stop`" — `stop` only reads PID files; "a stale PID file is never treated as final" — a stale file whose PID is alive is final (H1). |
| D2 | Reference manual `:3935` (`ai-sim` row) | `pm-stats … --keep-order-events-days 0.5`; the code passes `2` (`cli.py:449-450`); the row also omits pm-audit's `--max-file-mb 256 --keep-days 7` and the scheduler's `--backup-keep-days 2 --backup-skip stats.db`. |
| D3 | `cli.py:1043-1049` `stop_wave` | "Index into STOP_WAVES (0 is the first to stop)": it returns the index **plus one**; 0 means "in no wave", which is what stops first. |
| D4 | `cli.py:978` | "Starting pm-opctl configuration 'X' from <DATA_DIR>/emo-config.yaml" is printed when that file does not exist and the built-ins are used. |
| D5 | `cli.py:103-106`, README `:66-75`, registry `:2305-2306`, reference manual `:3949` | Describe `kill` as `pkill -15 -f -i -l pm-` signalling "every process whose command line contains pm-" (changes with WP-OPC02). |
| D6 | `cli.py:98-100`, registry `:2297`, reference manual `:3947` | `health` is "the same checks as `list`", but it has no `--no-tcp-probe`: it always connects to the gateways' ports. |
| D7 | Reference manual `:3952`, README, operator guide `010-running-the-exchange.md:1065-1071`, persistence chapter | What `clear` removes, `stop`'s exit code and what happens to a process that does not stop (change with WP-OPC03/04). |

---

## 6. Verified as correct

- **Start order.** `pm-log-srv` is moved first (`:983`) and waited for on its
  TCP port; `pm-audit` is moved before `pm-engine` and its own healthcheck
  must pass within 10 s before the engine starts (`:984-1031`), else `start`
  stops with exit 1 and the engine is not started.
- **Stop waves.** Entries outside `STOP_WAVES` stop first, then the engine,
  then the five recorders, then the log server, each wave waited up to 15 s
  (`:1081-1098`); a profile-less stop (no active profile) puts everything in
  the first wave, which is the safe default.
- **`--debug`.** Every program in the built-in profiles accepts
  `--log-level` (all 17 checked with `--help`), so `start -d` cannot break a
  process by its flag.
- **Profiles.** `ai-sim` is derived from `ai-swarm` by replacing named
  commands and inserting the monitor gateway after the dashboards gateway;
  `init` writes the built-ins and refuses to overwrite (`open("x")`).
- **`clear`.** SQLite companions go with their database; `ref_data/`,
  `engine_run_seq.json` and `companies.db` are never touched; without `--yes`
  and without a TTY it refuses (exit 1).
- **`health`.** Exit 0 only when every entry is `running`, 1 when any is not
  or no profile is active; `-q` prints nothing.

---

## 7. Decisions

Answers (2026-11-23, user asked for all WPs in one go): Q1–Q5 taken as
recommended, to confirm.

| # | Question | Recommendation |
|---|---|---|
| Q1 | How does a PID file prove its process (H1, C1)? (a) write `pid` and the process's start time (`psutil.Process(pid).create_time()`) and trust the file only when both match; (b) check the live process's command line against the profile entry; (c) both | **(a)**: the start time identifies one process exactly, also for a `--debug` start (extra arguments) and for spaced arguments (C3). (b) fails for both, and a reused PID running the same program (a second scheduler) would pass it. An untrusted file is deleted and the entry falls back to re-adoption (which uses exact argv, C3). |
| Q2 | What does `kill` signal (H2)? (a) every process whose *program* is a `pm-*` command (`_is_pm_program`), of the current user, except pm-opctl-cli itself and its ancestors, via psutil; PID files deleted only for processes that are gone afterwards; (b) keep `pkill`, drop `-l` and `-i`; (c) only the PIDs in the PID directory | **(a)**: it is the selection `clear` already trusts, works without procps, and cannot hit `npm`, editors or the calling shell. (b) still matches any argument containing `pm-`. (c) is what `stop` is for; `kill` exists for processes the tool lost track of. |
| Q3 | What does `stop` do with a process that outlives the 15 s wait (C2)? (a) keep its PID file, name it, go on with the next waves and exit 1; (b) escalate to SIGKILL; (c) (a), plus a `--force` that sends SIGKILL to survivors | **(a)**: a SIGKILLed engine loses its last persistence, so that is the operator's call; `kill` (and then `kill -9` by hand) is the emergency path. The container's `pm-opctl-cli stop \|\| true` keeps working. |
| Q4 | What does `clear` do while pm-* processes run (C5)? (a) refuse with exit 1, naming them, even with `--yes`; a new `--force` overrides; (b) keep the warning | **(a)**: every documented procedure stops first, and nothing useful comes from deleting a live process's database. `--force` keeps the expert path. |
| Q5 | Where do the missing files go (C6)? (a) `market_sim_state.json` → `--state` (it is working state the model reloads, like `book_stats.json`); `audit_replay.db`, `market_sim_news.db`, `ai_swarm/`, `eod/` → `--all`; (b) all five → `--all` | **(a)**: `clear --state` promises a fresh market; keeping the model's values defeats it. The others are records, like the logs. |

---

## 8. Work packages

### WP-OPC01 — A PID file names its own process, or it is not trusted (H1, C1, C3, D1; after Q1)

**Tests first** (`tests/test_emo_pid_identity.py`):

1. A PID file holding the PID of a live process the tool did not start (a
   child of the test): `start` starts the entry (a new PID), `list` does not
   show the stranger, `stop` leaves the stranger alive. (Fails today.)
2. A PID file holding PID 1 (another user's process): `stop` stops every
   other entry and exits non-zero naming the untrusted file, or treats it as
   stale; nothing raises. (Fails today.)
3. A process started by `start`, then restarted under the same profile by
   `start` again: "already running" with the same PID, unchanged.
4. The PID file of a running entry whose argv has a spaced argument is
   deleted: `list --no-restart` re-adopts it (same PID, "re-adopted").
   (Fails today.)
5. `start --debug`, then `list`: every entry is `running` with its PID,
   unchanged.

**Change.** `spawn_process`/re-adoption write `"<pid> <create_time>\n"`;
`read_pid` returns the PID only when `psutil.Process(pid).create_time()`
equals the recorded value (a file without one, or a mismatch, is stale and
removed). `command_line`/`matches_command` use `psutil.Process(pid).cmdline()`
(exact argv; the python-interpreter skip as today). `stop_profile` catches
`OSError` per entry, reports it, continues, and returns 1 at the end. D1.

**Exit criteria.** Tests 1–5 pass; `tests/test_emo*.py` green; the H1, C1
and C3 scratch repros show the entry started, the stranger alive, and the
scheduler stand-in re-adopted.

**Outcome (2026-11-23).** Q1 taken as recommended. A PID file now holds
`<pid> <start time>` (`write_pid`, psutil `create_time`), and `read_pid`
returns the PID only while the process with that PID has that start time; a
file that does not match, or carries no start time, is removed and never
acted on (no migration: a bare-PID file of an earlier version is stale and
its process is re-adopted). `command_line` returns the exact argv from psutil
instead of `ps` text, `matches_command` compares argv lists (C3), and
re-adoption skips processes of other users (`owned_by_me`; pgrep lists every
user's). `stop` catches `OSError` per entry, reports it on stderr, stops the
rest and exits 1 (C1). Beyond the plan: `stop` also re-adopts active-profile
entries whose PID file is missing or stale. The C1 repro showed why: after the
fix `stop` no longer aborted, but left the entry whose file was overwritten
running; and after an upgrade every PID file of a running stack is in the
old format, so a `stop` before any `list` would have stopped nothing. The
reference manual already promised re-adoption on `stop` (D1); D1 and the
module docstring now describe the start-time rule.

Failed first: the reused-PID test (the stranger's PID was taken for the
entry), the stale-start-time test (no `process_start_time`), both `stop` tests
(`PermissionError` raised), the spaced-argument re-adoption (`(None, False)`),
then the two tests added for the extension (the entry with a stale file kept
running; no `owned_by_me`). The two "unchanged" cases passed before and
after. Five existing `tests/test_emo_cli.py` tests encoded the old contract
(bare-PID files, `ps` strings) and were updated; the matching test gained the
spaced-argument cases. Scratch repros through the installed CLI: H1 — entry
started, stranger alive after `stop`; C1 — `stop` exits 0 and stops the other
entry; C3 — the scheduler stand-in re-adopted by `list` and stopped. Full
suite: 15 490 passed, 1 skipped.

### WP-OPC02 — `kill` stops every pm-* program and nothing else, and keeps track of survivors (H2; after Q2)

**Tests first** (`tests/test_emo_kill.py`):

1. The selection function, given a fake process table (cmdlines):
   `["python3", "/v/bin/pm-engine", "--verbose"]` and `["pm-log-srv"]` are
   selected; `["node", "/usr/lib/npm-cli.js"]`, `["vim", "pm-notes.md"]`,
   `["bash", "-c", "pm-opctl-cli kill"]`, `["rpm-ostree"]` are not; the
   caller's own PID and its ancestors are never selected. (Fails today: no
   such function; pkill selection.)
2. With two real children named `pm-zzz-test` (a script) and one unrelated
   child: `kill_all_processes()` signals the two, not the third, and returns
   0. (Fails today on procps-ng 4: exit 2, nothing signalled.)
3. A selected child that ignores SIGTERM: its PID file stays, the others'
   are removed, the exit code is 1 and the line names it. (Fails today.)

**Change.** Replace the `pkill` call with the psutil selection built on
`_is_pm_program` and `_running_pm_pids`'s self/ancestor exclusion (shared
helper), current user only; SIGTERM each, wait up to `STOP_WAIT_SEC` for them
to go, delete the PID files of the ones gone, keep the rest and return 1 if
any remain. The active-profile file is deleted only when nothing remains.

**Exit criteria.** Tests 1–3 pass; the H2 scratch repro (real function,
harmless pattern) is replaced by test 2; `tests/test_emo*.py` green.

**Outcome (2026-11-23).** Q2 taken as recommended. `kill` no longer runs
`pkill`: a new `pm_processes()` lists this user's running processes whose
*program* is a pm-* command (`_is_pm_program`), excluding pm-opctl-cli itself
and its ancestors; `kill` sends each SIGTERM, waits up to `STOP_WAIT_SEC`
(`psutil.wait_procs`), removes the PID files of the processes that are gone,
and for survivors keeps their PID files and the active profile, names them on
stderr and exits 1. Nothing to kill prints "No running EduMatcher processes
were found." and exits 0. `_running_pm_pids` (the `clear` warning) is now a
formatter over the same `pm_processes()` and keeps its never-fail contract;
`kill` lets an unexpected error surface. The current-user filter is shared
with re-adoption (`owned_by_me`, WP-OPC01).

Tests (`tests/test_emo_kill.py`) run the real selection on real children,
with `psutil.process_iter` narrowed to those children and `subprocess.run`
stubbed, so neither the old `pkill` nor the new selection can reach any other
process on the host. Failed first: the three kill tests (`pkill failed with
exit code 2`: today's command run against the stub) and the user-filter test
(no `pm_processes`); the selection cases passed before and after. Removed:
`test_emergency_kill_translates_pkill_outcomes` (pkill exit codes); one
planned test (self/ancestor exclusion) duplicated the existing
`test_running_process_detection_ignores_itself_and_its_ancestors`, which now
covers `pm_processes()`. Full suite: 15 498 passed, 1 skipped.

### WP-OPC03 — `start` and `stop` report what really happened (C2, C4; after Q3)

**Tests first** (`tests/test_emo_reporting.py`):

1. An entry that ignores SIGTERM: `stop` exits 1, names it as still
   running, keeps its PID file, and still stops the entries of later waves;
   a second `stop` tries it again. (Fails today: exit 0, PID file gone.)
2. Normal entries: `stop` exits 0 and removes every PID file, unchanged.
3. An entry `false`: `start` exits 1 and prints that it exited at once with
   its exit code and log path; the other entries are started. (Fails today:
   "started", exit 0.)
4. Normal entries: `start` exits 0, unchanged; an entry that is already
   running is not re-checked as "exited".

**Change.** `stop_profile` keeps a survivor's PID file and returns 1; the
"stopped X" line is printed after the wave, per entry, as `stopped` or
`still running`. `start_profile` remembers the PIDs it spawned, waits 1 s
after the last spawn, and reports each that has exited (`psutil` /
`os.waitpid`-free check via `is_alive`, plus `Popen.poll()` for the code).

**Exit criteria.** Tests 1–4 pass; `tests/test_emo*.py` and the container e2e
helpers that call `start`/`stop` green.

**Outcome (2026-11-23).** Q3 taken as recommended. `stop` signals a wave,
waits, then reports each member: `stopped X (pid N)` and its PID file removed,
or `error: X (pid N) still running 15s after SIGTERM; PID file kept`; the
later waves are stopped all the same, the active profile is kept while a
survivor remains, and the exit code is 1. `start` remembers what it spawned
and, after `START_GRACE_SEC` (1 s) following the last spawn, names each one
that has already exited with its exit code and log path, removes its PID
file and exits 1. The exit code comes from the `Popen` object, which
`spawn_process` now keeps (`_SPAWNED`): `subprocess` reaps an unreferenced
`Popen` at the next spawn, so the first implementation reported "exited"
without a code.

Beyond the plan (re-walk, lessons B1): the container entrypoint runs
`pm-opctl-cli start` under `set -euo pipefail`, and its own comments say a
bot can die at start when it races the engine (what `EM_RESTART_DEAD`
repairs). With the new exit code that would have ended PID 1 and stopped the
container. `entrypoint.sh` now logs a warning and carries on; a static test
pins it. The same change means an unhealthy `pm-audit` (already exit 1 before
this WP) no longer stops the container either: the engine stays unstarted,
`list` shows it dead, and `EM_RESTART_DEAD` starts it. To confirm.

Failed first: the survivor test (`stop` exit 0), the early-exit test
(`start` exit 0), the entrypoint test; the clean-stop and running-entry cases
passed before and after. Existing tests adjusted: the wave-order test records
the one extra `is_alive` per member that reporting needs; the start tests in
`tests/test_emo_cli.py` and `test_monitor_startup.py` spawn through mocks that
return PIDs of no process, so they opt out of the early-exit check. Real CLI:
`false` named with `exit code 1`, `start` exit 1; the SIGTERM-ignoring entry
kept its PID file, `stop` exit 1. Full suite: 15 503 passed, 1 skipped.

### WP-OPC04 — `clear` never deletes under a running process and covers every data file (C5, C6; after Q4, Q5)

**Tests first** (`tests/test_emo_clear.py`):

1. With a running child whose program is `pm-*` (a script): `clear --state
   --yes` exits 1, names it, and deletes nothing. (Fails today: deletes.)
2. The same with `--force --yes`: deletes, with the warning, unchanged
   otherwise.
3. No pm-* process: `clear --state --yes` removes `market_sim_state.json`
   and keeps `audit_replay.db`, `market_sim_news.db`, `ai_swarm/`, `eod/`,
   `engine_run_seq.json`, `companies.db`, `ref_data/`. (Fails today:
   `market_sim_state.json` kept.)
4. `clear --all --yes` removes all of test 3's list except
   `engine_run_seq.json`, `companies.db` and `ref_data/`. (Fails today.)

**Change.** `clear_data` refuses when `_running_pm_pids()` is non-empty
unless `force`; `--force` on the parser; the path lists per Q5, with new
`config.py` constants only where none exist (`MARKET_SIM_STATE_FILE` etc. are
defined in their modules today: import them, or move the constant to
`config.py` if importing the module is heavy).

**Exit criteria.** Tests 1–4 pass; `tests/test_emo*.py` green; `make
completion` regenerated.

**Outcome (2026-11-23).** Q4 and Q5 taken as recommended. `clear` refuses
with exit 1 while pm-* processes of this user run (`_running_pm_pids`, now
built on WP-OPC02's `pm_processes`), naming them and pointing at
`pm-opctl-cli stop` / `--force`, also under `--yes`; `--force` keeps the old
behaviour (warning, then the prompt unless `--yes`). `STATE_PATHS` gained
`market_sim_state.json`; `NON_STATE_PATHS` gained `audit_replay.db`,
`market_sim_news.db`, `ai_swarm/` and `eod/`. The paths are written as the
module already writes `indexes` and `backup` (`DATA_DIR / "…"`), and a test
ties each one to its writer's own constant or default (pm-market-sim's
`STATE_FILE`, `news_history.NEWS_HISTORY_DB`, the AI worker's `summary_dir`
default, `config.AUDIT_REPLAY_DB_FILE`), with another proving that
`engine_run_seq.json`, `companies.db` and `ref_data/` are in neither scope.
`make completion` regenerated for `--force`.

Failed first: the refusal (`clear` exit 0), the two `--force` tests (no such
option), the writers'-paths test (`market_sim_state.json` not in
`STATE_PATHS`); the kept-files test passed before and after. Existing tests
updated for the new contract: the documented-data-sets test (the five files),
the confirmation test (now with `force=True`, since without it the refusal
comes first), and the `main` dispatch test (`force=`). Re-walk: every guide
procedure that runs `clear` stops the stack first (quick-start container and
Python routes, training 000/110/140/195/260/270); inside the container `stop`
removes the active profile, so `EM_RESTART_DEAD` cannot restart processes
between `stop` and `clear`. Full suite: 15 508 passed, 1 skipped.

### WP-OPC05 — Healthchecks get time to answer; process names are file names (C7, C8)

**Tests first** (`tests/test_emo_config.py`):

1. A profile with a process named `../x`, `a/b`, `.hidden` or containing a
   newline is refused with a message naming it. (Fails today.)
2. A healthcheck that takes 3 s and exits 0 reads as `running`. (Fails
   today: `not responding` after 2 s.)
3. A healthcheck that hangs is `not responding` within the budget, unchanged
   in kind.

**Change.** `HEALTHCHECK_TIMEOUT_SEC = 5.0`; name check in
`validate_processes` (the built-in names pass).

**Exit criteria.** Tests 1–3 pass; `tests/test_emo*.py` green.

**Outcome (2026-11-23).** `HEALTHCHECK_TIMEOUT_SEC` is 5 s, with the
reason next to it. `validate_processes` refuses a name that is not a single
file name (`/`, `\`, NUL, newline, carriage return, a leading `.`, or anything
`os.path.basename` would change); every built-in name passes.

Failed first: the six name cases (`DID NOT RAISE`) and the 3 s healthcheck
(`not responding`); the built-in names and the hanging-check case passed
before and after. Found on the way, in the tests: the first full run of the
opctl tests under `-n logical` failed two WP-OPC01 tests, because two xdist
workers ran sleepers with the same argv and re-adoption in one adopted the
other's. The sleepers in `test_emo_pid_identity.py` and
`test_emo_reporting.py` now carry a unique tag; three parallel runs green.
Full suite: 15 517 passed, 1 skipped.

### WP-OPC06 — Comments, help texts and guides say what the code does (D2–D7)

**Tests first.** None for texts; `tests/test_shell_completion.py` and the
pm-help registry tests stay green.

**Change.** D2–D7 in the module docstring, `README.md`, `--help`, the
registry, the reference manual, the operator guide's shut-down section and
the persistence chapter's `clear` notes. Re-walk every guide procedure that
runs `stop`, `kill` or `clear` (training 000/110/140/195/260/270, quick-start
FAQ and troubleshooting, ai-traders FAQ) against the final behaviour,
especially `clear` now refusing while processes run (lessons B1).

**Exit criteria.** Every D item resolved; `make _check` green; `mkdocs
build` without new warnings.

**Outcome (2026-11-23).** D2: the reference manual's `ai-sim` row says
`--keep-order-events-days 2` and lists pm-audit's and the scheduler's
options. D3: `stop_wave`'s docstring says 0 means "in no wave, stopped
first". D4: `start` names "the built-in profiles" when no `emo-config.yaml`
exists. D5: `kill` is described as the pm-*-program selection in the module
docstring, README, registry, `--help`, reference manual and operator guide.
D6: `health` "always with the tcp probe" in the same places. D7: what
`clear` removes, its refusal and `--force`, the exit codes of `start`, `stop`,
`kill`, `health` and `clear`, and the PID-file rule in the README (which also
listed only three of the six profiles), registry, reference manual, operator
guide (process-tracking bullets and the shut-down section) and training
chapter 11's reset matrix. `make completion` regenerated.

Re-walk (lessons B1): every guide procedure that runs `clear` stops every
pm-* program first, consoles included (training 000, 110, 140, 195, 260,
270; quick-start FAQ and troubleshooting); none runs `kill`. Full suite:
15 517 passed, 1 skipped; `mkdocs build`: the one pre-existing warning.

### Holistic review (2026-11-23)

All changes re-read as one diff (`emo/cli.py`, the entrypoint, the texts),
looking for interference between the WPs, and the whole flow run through the
installed CLI on a scratch profile of two `pm-*` stand-ins, one with the
scheduler's spaced argument: `start -d` (both started with `--log-level
DEBUG`), `health` OK, `clear --state --yes` refused (exit 1) while they ran,
`stop` (both stopped, exit 0), `clear --state --yes` (deleted
`market_sim_state.json`, exit 0). The real `kill` was not run on this host
(it would signal the user's own pm-* programs); its tests run the real
selection on the tests' own children.

- **HR1 (fixed; WP-OPC01 × WP-OPC03).** `stop` re-adopted a process whose
  PID file was lost but wrote no file for it, so a survivor was reported as
  "PID file kept" without one. Re-adopted entries are now recorded like any
  other. Test: a re-adopted survivor has a trusted PID file after `stop`
  (failed first: `None`).
- **HR2 (fixed; WP-OPC01).** psutil's start time is the kernel's boot time
  plus the process's ticks, and the boot time moves when the wall clock is
  stepped (NTP at a VM's boot, `date -s`). After a step every PID file looked
  stale; plain entries were re-adopted by argv, but a `start --debug` stack
  (extra arguments) could not be, and `stop` would have reported "nothing
  running" with the stack up. The PID file now also records the argv
  actually launched (second line, JSON); a start-time mismatch is accepted
  only when that PID is this user's process still running exactly that argv,
  and the file is then rewritten. Tests: a 37 s shift on a debug-started entry
  is still recognised and stopped (failed first: `None`); a reused PID
  running another command is stale even with an argv recorded.
- **HR3 (fixed; WP-OPC02 × WP-OPC01).** `kill` selected pm-* programs only,
  then removed the PID file of every process not among its survivors; an
  entry of a custom profile running another program was neither signalled
  nor tracked any more. Every process with a trusted PID file is now a
  target too. Test failed first (the process was still alive); texts say so.
- **Checked, no change.** `clear --all` can no longer delete `emo/` under a
  running stack (C3's trigger), because WP-OPC04 refuses first. An
  upgraded host's bare-PID files are stale (no migration code), and their
  processes are re-adopted by `start`/`list`/`stop`. `pm_processes` serves
  both `kill` and `clear`'s refusal, so the two always agree on what counts
  as running. Re-adoption matches exact argv, so two stacks of one user with
  identical commands on one host would adopt each other's processes; the
  fixed engine ports make such a setup impossible today, and other users'
  processes are excluded.
- **A flaky test from the pm-admin review** failed once in a full run:
  `test_connect_waits_until_replies_can_arrive` chose a free TCP port and
  bound it 0.3 s later on purpose, which leaves the port to any other xdist
  worker in between. It passed 5/5 alone and 24/24 under full CPU load; it now
  uses an `ipc://` endpoint in its temp directory, and still fails without
  WP-ADM02's fix (checked with the probe disabled).

Full suite after the review: 15 521 passed, 1 skipped.

---

## 9. Out of scope, noted

- **Container stop budget.** `stop_grace_period` is 30 s (60 s for ai-sim)
  while `stop` may wait up to 4 × 15 s; a slow engine shutdown in the ai-sim
  container is SIGKILLed by Docker before the recorders' wave. A deployment
  setting, not a code defect; WP-OPC03's exit code makes it visible in the
  container log. For-Later **L045**.
- **`kill` on the container image's procps.** Debian bookworm's procps was
  not checked; WP-OPC02 removes the dependency on `pkill`'s option set.

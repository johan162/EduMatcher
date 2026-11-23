# EduMatcher Operational Scripts

This directory contains operational scripts for starting and stopping a named
EduMatcher process profile. The main entry point is `pm-opctl-cli`.

## `pm-opctl-cli`

Run it from the repository checkout with Python or Poetry:

```bash
poetry run pm-opctl-cli start
poetry run pm-opctl-cli start micro
poetry run pm-opctl-cli list
poetry run pm-opctl-cli health
poetry run pm-opctl-cli stop
poetry run pm-opctl-cli init
```

When installed as an executable, the same commands are:

```bash
pm-opctl-cli start
pm-opctl-cli start micro
pm-opctl-cli list
pm-opctl-cli health
pm-opctl-cli stop
pm-opctl-cli kill
pm-opctl-cli init
```

`start` without a name starts the `default` profile. When no
`<DATA-DIR>/emo-config.yaml` exists, the six built-in profiles are available
(`default`, `micro`, `mini`, `mm-demo`, `ai-swarm`, `ai-sim`; see the module
docstring in `cli.py`). When the file exists, its profiles replace the
built-ins and a missing `default` profile is supplied from the built-in
nominal profile.

`init` writes all built-in profiles to
`<DATA-DIR>/emo-config.yaml` as a starting point for customization. It refuses
to overwrite an existing file and returns a nonzero exit code; remove or move
the existing file explicitly before creating a fresh one.

The `default` profile starts a full nominal exchange stack. The `mini` profile
starts a trading-capable subset with external access but no audit or clearing.
The `micro` profile starts only centralized logging and the engine.
Processes are launched from the repository root, inherit the
current environment (including `EDUMATCHER_DATA_DIR`), and write their combined
stdout/stderr to `<DATA-DIR>/emo/<process>.log`. PID files are kept beside them,
each holding the PID, the process's start time and the argv it was launched
with: a file is trusted only while the process with that PID also has that
start time (or, after the clock was stepped, still runs that argv as this
user), because after a crash, a killed container or a reboot the PID belongs
to some other process.
A file that does not match is removed, never acted on, and a profile process
whose file is missing or stale is re-adopted by its exact command line among
this user's processes.

`start` exits `1` when a process it started has already exited one second
after the last one was launched (a bad configuration, a port in use); it names
each one with its exit code and log file. The others keep running.

When a profile contains both `pm-audit` and `pm-engine`, `start` launches the
audit recorder first and waits for `pm-audit-cli health -q` to succeed before
launching the engine. If the recorder does not become healthy within 10 seconds,
startup stops and the engine is not started. The healthcheck confirms that
`pm-audit` is running and its health endpoint responds; it does not confirm that
the ZeroMQ subscription has joined an already-running publisher.

`stop` stops the processes recorded in the PID directory, plus any process of
the active profile whose PID file was lost, found by its exact command line
among this user's processes. It never signals a process whose start time does
not match its PID file.

It stops the exchange in order, waiting for each step to exit before starting the
next: gateways, bots and other processes first, then `pm-engine`, then the
recorders (`pm-clearing`, `pm-stats`, `pm-audit`, `pm-index`, `pm-monitor`), and
`pm-log-srv` last. The recorders therefore see everything the engine published
before it exited. A process still running 15 seconds after `SIGTERM` is
reported, keeps its PID file and makes `stop` exit `1`; the next steps proceed,
and a later `stop` (or `kill`) tries it again.

`kill` is an emergency command. It sends signal 15 (`SIGTERM`) to every running
process of this user whose program is a `pm-*` command (`pm-engine`, or a
Python interpreter running `pm-engine`), including processes not started by
`pm-opctl-cli`, but never to anything that merely mentions `pm-` in its
arguments (`npm`, an editor, the shell that ran the command) or to
`pm-opctl-cli` itself; every process recorded in the PID directory is signalled
too, whatever its program. It waits up to 15 seconds, then removes the PID files of
the processes that are gone. A survivor keeps its PID file and makes `kill`
exit `1`. Finding nothing to stop is success.

`list` reads the active profile recorded by `start` and prints one status row
per configured process. The markers are:

- green `✓` — the PID is alive and, if configured, its `healthcheck` passed or
  its `tcp` address accepted a connection
- red `✗` — the PID is no longer alive
- yellow `⚠` — the PID is alive but its configured `healthcheck` or `tcp` check
  failed or timed out

`health` runs the same checks as `list` (always including the `tcp` probe) but
is meant for scripting: it prints
a compact per-process line plus an overall `health: OK`/`health: FAIL` line,
and exits `0` only when every process in the active profile is `running`
(exits `1` otherwise, including when no profile is active). Pass `-q`/`--quiet`
to suppress all output and rely on the exit code alone, e.g. in a monitoring
cron job:

```bash
poetry run pm-opctl-cli health -q || alert "pm-opctl-cli profile unhealthy"
```

There is no generic, reliable way to determine whether an arbitrary process is
internally hung. Two optional per-process checks upgrade the liveness report
from "PID exists" to something closer to "is responding":

- `tcp: "host:port"` — the cheapest useful check for a process that binds a
  ZMQ or TCP socket (engine, log server, gateways). `pm-opctl-cli` attempts a plain
  `socket.create_connection()` with a short (0.3s) timeout and immediately
  closes it; a successful connect is reported as `running`, a refused or
  timed-out connect as `not responding`. **Caveat:** libzmq's I/O thread
  accepts TCP connections independently of the application's own processing
  loop, so a successful connect proves the process is alive and bound to the
  port, but does not prove its message loop is unstuck. Treat it as a cheap
  "is it alive and listening" signal, not a full liveness guarantee.
- `healthcheck` — a command that returns exit code `0` when the process is
  responsive, for a stronger, application-level check where one exists (e.g.
  `pm-stats-cli health -q`, `pm-audit-cli health -q`,
  `pm-clearing-cli health -q` or `pm-index-cli health -q`, or an HTTP health
  endpoint via `curl --fail`).

When both `tcp` and `healthcheck` are configured for the same process,
`healthcheck` takes precedence since it is the stronger signal; `tcp` is used
only when no `healthcheck` is configured. When neither is configured, an alive
PID is reported as `running` with no further detail.

```yaml
default:
	processes:
		- name: api-desk
			command: [pm-api-gwy, --verbose, --instance, desk]
			tcp: "127.0.0.1:8080"
			healthcheck: [curl, --fail, --silent, http://127.0.0.1:8080/api/v1/health]
```

Healthchecks are executed with a five-second timeout and do not inherit stdin.
They should be read-only and inexpensive. For processes without a suitable
`tcp` address or health endpoint, `list`/`health` can only report process
liveness, not application health.

The built-in profiles configure `tcp` using each process's conventional bind
address: `pm-log-srv` 5600, `pm-engine` 5555, `pm-md-gwy` 5570, `pm-ralf-gwy`
5580, `pm-dc-gwy` 5590, `pm-alf-gwy` 5565, `pm-balf-gwy` 5560, and `pm-api-gwy`
8080/8081 for the `desk`/`dashboards` instances. Processes that only subscribe
to the bus (`pm-audit`, `pm-stats`, `pm-clearing`, `pm-scheduler`) do not bind
a socket and have no `tcp` entry.

## Process configuration

The optional configuration file is:

```text
<DATA-DIR>/emo-config.yaml
```

It maps profile names to process lists. A profile can be written either as a
mapping containing `processes`, or directly as a list:

```yaml
default:
	processes:
		- name: log
			command: [pm-log-srv]
		- name: audit
			command: [pm-audit]
		- name: stats
			command: [pm-stats]
		- name: clearing
			command: [pm-clearing]
		- name: engine
			command: [pm-engine, --verbose]
		- name: scheduler
			command: [pm-scheduler]
		- name: market-data
			command: [pm-md-gwy]
		- name: api
			command: [pm-api-gwy, --instance, desk]

micro:
	processes:
		- name: log
			command: pm-log-srv
		- name: engine
			command: "pm-engine --verbose"
		- name: trader
			command: "pm-alf-console --id TRADER01 --verbose"
```

Each process entry has:

| Field | Required | Meaning |
|---|---:|---|
| `name` | yes | Unique PID/log identifier within the profile; one file name (no `/`, `\`, newline, NUL or leading `.`) |
| `command` | yes | Either a YAML list of argv tokens or a shell-like command string; it is launched without a shell |
| `healthcheck` | no | Optional YAML command list or shell-like string; exit code `0` means responsive |
| `tcp` | no | Optional `"host:port"` string; a successful connect means responsive (see caveat above) |

The command must be available on `PATH`. Use `poetry run` explicitly in a
command when the profile is launched with plain Python, or run the script as
`poetry run pm-opctl-cli ...` so installed project commands are
available from the Poetry environment.

The profile format is deliberately small so future commands can reuse the same
profile loader. A future `status` command can read the same PID files and
compare them with the selected profile without changing the YAML format.

## Clearing data

`clear --state` deletes the exchange's working state: GTC orders and combos,
book statistics, `stats.db`, `clearing.db`, index state and the market
model's `market_sim_state.json`. `clear --all` also deletes the records: the
audit trail and its indexes (`audit_index.db`, `audit_replay.db`), `log.db`,
`metrics.db`, fallback logs, the `emo/` directory, `eod.db`, `settlement/`,
`backup/`, the market model's `market_sim_news.db`, the AI traders' `ai_swarm/`
summaries and the engine's `eod/` close archives. `ref_data/`,
`engine_run_seq.json` and `companies.db` are never deleted. `clear` refuses
(exit `1`) while `pm-*` processes of this user run, since they would keep
writing to the deleted files; stop them first, or pass `--force`.

## Data directory

`pm-opctl-cli` follows the project data-directory convention:

1. `EDUMATCHER_DATA_DIR`, when set.
2. `<repo>/src/data` when this script is in a source checkout.
3. `~/.local/share/edumatcher` otherwise.

All processes in a profile inherit the same data-directory environment. Deploy
the configuration before starting a profile:

```bash
poetry run pm-config-deploy engine_config.yaml
poetry run pm-opctl-cli start micro
```

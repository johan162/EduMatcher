# EduMatcher Operational Scripts

This directory contains operational scripts for starting and stopping a named
EduMatcher process profile. The main entry point is `pm-emo`.

## `pm-emo`

Run it from the repository checkout with Python or Poetry:

```bash
poetry run python emo-scripts/pm-emo start
poetry run python emo-scripts/pm-emo start micro
poetry run python emo-scripts/pm-emo list
poetry run python emo-scripts/pm-emo stop
poetry run python emo-scripts/pm-emo create
```

When installed as an executable, the same commands are:

```bash
pm-emo start
pm-emo start micro
pm-emo list
pm-emo stop
pm-emo kill
pm-emo create
```

`start` without a name starts the `default` profile. When no
`<DATA-DIR>/emo-config.yaml` exists, built-in `default` and `micro` profiles
are available. When the file exists, its profiles replace the built-ins and a
missing `default` profile is supplied from the built-in nominal profile.

`create` writes all built-in profiles (`default`, `micro`, and `mini`) to
`<DATA-DIR>/emo-config.yaml` as a starting point for customization. It refuses
to overwrite an existing file and returns a nonzero exit code; remove or move
the existing file explicitly before creating a fresh one.

The default profile starts a full nominal exchange stack. The `micro` profile
starts only centralized logging, the engine.
Processes are launched from the repository root, inherit the
current environment (including `EDUMATCHER_DATA_DIR`), and write their combined
stdout/stderr to `<DATA-DIR>/emo/<process>.log`. PID files are kept beside them.

`stop` stops only processes that `pm-emo` recorded in its PID directory. It
does not search for or terminate unrelated processes with the same executable
name.

`kill` is an emergency command. It runs:

```bash
pkill -15 -f -i -l 'pm-'
```

This sends signal 15 (`SIGTERM`) to every process whose full command line
contains `pm-`, including processes not started by `pm-emo`. Use it only when
you intentionally want to stop the entire EduMatcher process group. It also
clears `pm-emo`'s persisted PID and active-profile state. A result with no
matching processes is treated as success.

`list` reads the active profile recorded by `start` and prints one status row
per configured process. The markers are:

- green `✓` — the PID is alive; if a `healthcheck` is configured, it passed
- red `✗` — the PID is no longer alive
- yellow `⚠` — the PID is alive but its configured healthcheck failed or timed out

There is no generic, reliable way to determine whether an arbitrary process is
internally hung. An alive PID is therefore reported as running when no
healthcheck is configured. Add a cheap command that returns exit code `0` when
the process is responsive to get the yellow state:

```yaml
default:
	processes:
		- name: api-desk
			command: [pm-api-gwy, --verbose, --instance, desk]
			healthcheck: [curl, --fail, --silent, http://127.0.0.1:8080/api/v1/health]
```

Healthchecks are executed with a two-second timeout and do not inherit stdin.
They should be read-only and inexpensive. For processes without a suitable
health endpoint, `list` can only report process liveness, not application
health.

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
| `name` | yes | Unique PID/log identifier within the profile |
| `command` | yes | Either a YAML list of argv tokens or a shell-like command string; it is launched without a shell |
| `healthcheck` | no | Optional YAML command list or shell-like string; exit code `0` means responsive |

The command must be available on `PATH`. Use `poetry run` explicitly in a
command when the profile is launched with plain Python, or run the script as
`poetry run python emo-scripts/pm-emo ...` so installed project commands are
available from the Poetry environment.

The profile format is deliberately small so future commands can reuse the same
profile loader. A future `status` command can read the same PID files and
compare them with the selected profile without changing the YAML format.

## Data directory

`pm-emo` follows the project data-directory convention:

1. `EDUMATCHER_DATA_DIR`, when set.
2. `<repo>/src/data` when this script is in a source checkout.
3. `~/.local/share/edumatcher` otherwise.

All processes in a profile inherit the same data-directory environment. Deploy
the configuration before starting a profile:

```bash
poetry run pm-config-deploy engine_config.yaml
poetry run python emo-scripts/pm-emo start micro
```


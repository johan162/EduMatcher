# Installation & Setup

## Objective

Get a working EduMatcher, understand **where its files live**, and know **how to
change them**. There are four ways to install; you need exactly one, and
**Containers is the recommended default** — it needs no Python setup, gives
you the exchange plus four web applications in a single command, and is what
the rest of this chapter assumes unless you have a specific reason to choose
otherwise. By the end of this chapter you will have an exchange you can start
and stop, a deployed configuration, and a clear picture of which directory
holds your trades and logs.



!!! abstract "Pre-reading in the User Guide"
    - [Installation](../user-guide/005-installation.md)
    - [A Path Through the Guide](../user-guide/001-learning-path.md)

## Exercise 0: Read [How an Exchange Works](../how-exchange-works.md)

Not strictly required, but it gives you a mental model of the core components
and data flows in an exchange, which makes the rest of the training far more
intuitive. Especially recommended if you are new to how exchanges work under
the hood, or have no financial background.

You can refer back to it at any time; the concepts get clearer as you see them
in action.


## Choosing how to install

| Route | You need | You get | Best for |
|---|---|---|---|
| **A — Containers (recommended)** | Podman or Docker | The exchange **and four web applications**, in one command | Most students: no Python to install, the fastest path to a live market, and works through every chapter that follows |
| **B — pipx** | Python 3.13 | `pm-*` commands on your PATH | You would rather work outside a container, or Podman/Docker is not available to you |
| **C — Multipass VM** | Multipass | A Linux VM with `pm-*` inside it | Workshops; keeping your own machine untouched; a snapshot you can reset |
| **D — Poetry checkout** | Python 3.13, Git | The repository plus dev dependencies | Changing EduMatcher itself |

!!! warning "How this affects the rest of the training"
    From Chapter 01 onward you start and stop **individual processes by hand**,
    one per terminal — that is how the exercises teach you what each process
    does. Routes B and C give you that directly, in your own terminals.

    Route A gives you the same thing with one extra step: the containerised
    exchange starts its processes for itself, so before following Chapter 01
    you open a shell *inside* the container and stop them first. Exercise 1
    below shows exactly how, and it is a one-time step per session — after
    that, every `pm-*` command in the chapters works unchanged. This is why
    Route A is still the recommended default even though the chapters are
    demonstrated as bare commands: the only difference is prefixing your first
    command with `./edumatcher.sh shell`.

Pick one route below, then continue from Exercise 2 — the remaining exercises
apply to all of them.


## Exercise 1: Containers — the whole system in one command

You need Podman or Docker Desktop installed and running before you start. If
neither is available, the installer stops immediately and tells you so; there
is nothing else to prepare.

### Where everything will be stored

Before running an installer, know what it creates. **Everything lives in one
directory**, `~/.edumatcher` by default. Nothing is written anywhere else: no
system paths, no service registered, no change to your PATH. Deleting that
directory removes the installation.

| Path | Holds |
|---|---|
| `~/.edumatcher/data` | **Every trade, order book, log and database the exchange produces.** It is mounted into the containers, so it lives on your disk rather than inside a container, and survives stop, start and update |
| `~/.edumatcher/config` | An engine configuration of your own, once you supply one |
| `~/.edumatcher/.env` | Your settings — version, configuration, ports, timezone |
| `~/.edumatcher/compose.yaml`, `compose.zmq.yaml` | The container definitions. You will not normally edit these |
| `~/.edumatcher/edumatcher.sh` | The command you drive everything with |

Use `--dir` to put it somewhere else; the layout underneath is the same.

### Install

```bash
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/curl/install.sh | bash
```

!!! tip "Security-first variant"
    To read the script before running it:
    ```bash
    curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/curl/install.sh -o install.sh
    less install.sh
    bash install.sh
    ```

The installer checks for Podman or Docker, resolves the newest release,
downloads four small support files (`compose.yaml`, `compose.zmq.yaml`,
`edumatcher.sh`, `.env.example`), pulls five images and starts them. Nothing
is compiled on your machine.

When it finishes you have a complete exchange **and** four web applications:

| Application | URL | What it is |
|---|---|---|
| Trading terminal | <http://localhost:8090> | Live order books, trades and market data |
| Log viewer | <http://localhost:8091> | The centralized log, searchable |
| Configuration builder | <http://localhost:8092> | Author an `engine_config.yaml` in your browser |
| Trader GUI | <http://localhost:8093> | Submit and manage orders as a participant |
| REST API docs | <http://localhost:8080/docs> | Swagger UI for the `desk` API gateway |

Open the trading terminal. You should see order books with live quotes: the
bundled `three-basic` configuration seeds each symbol with a resting
market-maker bid and ask the moment `pm-engine` starts, so there is a two-sided
book before anyone has traded.

!!! note "If a port is already taken"
    The published ports (`8080`, `8090`–`8093`) are fixed. If another program
    on your machine already uses one of them, `./edumatcher.sh start` fails
    with a bind error naming that port. Free it, or move the conflicting
    service, then run `./edumatcher.sh start` again — nothing was left
    half-started.

!!! warning "Running a second install on the same machine"
    Every container and its ports are fixed by name, so a second `curl |
    bash` into a different `--dir` will refuse to start once it reaches the
    point of creating the exchange container, naming the other install's data
    directory and telling you to stop it first (`./edumatcher.sh stop` in that
    other directory, or `make -C <repo>/deployment/docker down-all` for a
    source checkout). Stop one before starting the other; the two are not
    designed to run side by side.

### Driving it

Everything runs from the install directory through one script:

```bash
cd ~/.edumatcher
./edumatcher.sh status              # containers, plus the exchange process table
./edumatcher.sh urls                # the table above, with your ports
./edumatcher.sh logs terminal-gui   # follow one service
./edumatcher.sh mounts              # which directory is behind each container path
./edumatcher.sh stop                # stop everything; your data is kept
./edumatcher.sh start               # bring it back
```

### Running `pm-*` commands for the rest of the training

Every `pm-*` command is inside the exchange container, already on the PATH.
The control script puts you there:

```bash
cd ~/.edumatcher
./edumatcher.sh shell
```

Inside that shell, `pm-engine`, `pm-alf-console`, `pm-config-deploy` and the
rest work exactly as the training chapters describe, and
`EDUMATCHER_DATA_DIR` is already set to `/data`.

To run a single command without staying inside, pass it along:

```bash
./edumatcher.sh shell pm-opctl-cli list
```

One difference matters. The container **starts the processes for you** — the
`default` profile is already running, which is why the terminal showed a live
market. The training chapters assume you start them yourself, so stop them
first:

```bash
pm-opctl-cli list           # see what is running
pm-opctl-cli stop           # stop the profile; the container stays up
pm-engine --verbose         # now follow the chapters
```

For the exercises that need several terminals, run `./edumatcher.sh shell` once
in each of them.

!!! note "Getting back to a running market"
    `pm-opctl-cli start` restarts the whole profile whenever you want the
    web applications populated again.

:material-checkbox-blank-outline: **Checkpoint:** <http://localhost:8090> shows
order books, and `./edumatcher.sh shell pm-engine --version` prints a version
number.


## Alternate Routes

Skip this section if you took Route A. It covers three routes for specific
situations: working outside a container, a disposable sandbox, and
contributing to EduMatcher itself. Each still ends at the same place —
`pm-engine --version` resolving and a data directory you can name — so
Exercise 2 onward works the same regardless of which one you picked.

### Route B: pipx — commands on your own machine

Choose this when you would rather not run a container, or Podman/Docker is not
available to you.

| Requirement | Notes |
|---|---|
| Python 3.13 or later | Check with `python --version` |
| `pipx` | Installs command-line applications into isolated environments |
| Several terminals | Or `tmux` / `screen`; one process per pane is normal |

```bash
# macOS with Homebrew
brew install pipx
pipx ensurepath

# Linux, or macOS without Homebrew
python -m pip install --user pipx
python -m pipx ensurepath
```

!!! warning "`pip install pipx` on its own often fails"
    On a system Python (most Linux distributions since 2023, including
    Debian and Ubuntu), a bare `pip install pipx` refuses with `error:
    externally-managed-environment`. The `--user` flag above installs into
    your own home directory instead of the system site-packages, which is
    both what avoids that error and the setup pipx itself recommends.

`pipx ensurepath` edits your shell's startup file but cannot update the
*current* shell. **Open a new terminal** before continuing, then install
EduMatcher into it:

```bash
pipx install edumatcher
```

Verify:

```bash
pm-engine --version
```

!!! note "`command not found: pm-engine`"
    Almost always the same cause: you are still in the terminal that was open
    when you ran `pipx ensurepath`. Open a new one (or `exec $SHELL`) and try
    again before suspecting anything else.

Then bootstrap your workspace:

```bash
pm-setup
```

`pm-setup` creates the data directory, compiles a bundled example
configuration (`three-basic` unless you say otherwise) and installs it as the
deployed artifact, then prints the one environment variable you need. The
output looks like this — yours will show your own home directory and shell:

```text
pm-setup — EduMatcher session initialisation
==================================================
  ✓ Created data directory:          /Users/you/.local/share/edumatcher
  ✓ Example config 'three-basic' compiled to: /Users/you/.local/share/edumatcher/ref_data/engine_config.json
    3 symbol(s) ready to trade.

  Shell environment snippet — add to your shell profile:
  (~/.zshrc)
  ----------------------------------------------
  export EDUMATCHER_DATA_DIR="/Users/you/.local/share/edumatcher"
  ----------------------------------------------

  This is the only variable to set. Every process derives its
  configuration, database and log paths from it, so they cannot
  drift apart.
  ...
```

Add the `export` line to `~/.zshrc` (macOS default shell) or `~/.bashrc`
(Linux, or bash on macOS) — `pm-setup` names the right file for your shell in
its own output — then reload it:

```bash
source ~/.zshrc     # or source ~/.bashrc — whichever pm-setup named
```

!!! note "Re-running pm-setup"
    `pm-setup --force` replaces an already-deployed configuration with the
    bundled example. `pm-setup --config ten-nominal` picks a different one.
    `pm-setup --no-config` creates only the data directory.

:material-checkbox-blank-outline: **Checkpoint:** `pm-engine --version` prints a
version, and `echo $EDUMATCHER_DATA_DIR` prints a path — **in a new terminal**,
not just the one where you ran `pm-setup`.

### Route C: Multipass VM — a disposable Linux sandbox

A ready-to-run Linux environment without installing Python tooling on your
host. Install Multipass from [multipass.run](https://multipass.run/install),
verify it, then bootstrap:

```bash
multipass version

curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/vm/curl_setup_vm.sh | bash -s -- --version 0.31.1
```

If `multipass version` fails with `command not found`, the install did not
complete or your shell has not picked up its PATH change yet — open a new
terminal and retry before moving on.

This launches a VM (default name `ems`), installs the runtime inside it, runs
`pm-setup` for you, takes a snapshot named `clean`, and prints the VM's
address and API keys.

```bash
multipass shell ems
pm-engine --version
```

Inside the VM, `pm-*` commands work exactly as the chapters describe. The whole
exchange can be started at once with `pm-opctl-cli start`, or process by
process as the exercises do it.

```bash
multipass stop ems              # pause the VM
multipass start ems             # resume
multipass delete --purge ems    # remove it entirely
```

!!! tip "The snapshot is the point"
    Provisioning takes a snapshot named `clean`. After an exercise leaves the
    order books in a mess, restore it with the `-d` (destructive) flag, which
    skips the confirmation prompt and discards everything since:
    ```bash
    multipass restore -d ems.clean
    ```

:material-checkbox-blank-outline: **Checkpoint:** `multipass shell ems` works and
`pm-engine --version` succeeds inside the VM.

### Route D: Poetry checkout — for changing EduMatcher itself

Choose this only if you intend to modify EduMatcher's own source, not to run
it as a student.

```bash
git clone https://github.com/johan162/EduMatcher.git
cd EduMatcher
poetry config virtualenvs.in-project true
poetry install --with dev,docs
```

Every command is then prefixed with `poetry run`, e.g. `poetry run pm-engine`.
The data directory is the repository's own `src/data/` unless you set
`EDUMATCHER_DATA_DIR`.


## Exercise 2: Find where your files live

One idea underlies everything in this chapter: **one data directory is one
exchange**. Every process reads its configuration from there and writes its
trades, logs and databases back to it. Two processes pointed at different data
directories are two different exchanges that cannot see each other.

Find yours:

**If you installed with containers:**

```bash
cd ~/.edumatcher
./edumatcher.sh mounts
```

The directory is `~/.edumatcher/data` on your disk, mounted as `/data`
inside the container. Both names refer to the same files — that is why the
log viewer's health page says `/backend-data/log.db` while on your machine
the file is `~/.edumatcher/data/log.db`.

**If you installed with pipx, the VM, or Poetry:**

```bash
echo $EDUMATCHER_DATA_DIR
ls -la "$EDUMATCHER_DATA_DIR"
```

`EDUMATCHER_DATA_DIR` is **the only location variable there is**. If it is
unset, EduMatcher falls back to `~/.local/share/edumatcher` for an
installed copy, or the repository's `src/data/` in a Poetry checkout.

Whichever route you took, the directory holds the same things:

| Inside the data directory | What it is |
|---|---|
| `ref_data/engine_config.json` | The **compiled artifact every process actually reads**. Never edit it by hand |
| `ref_data/engine_config.yaml` | The authored source it was compiled from, kept for provenance |
| `log.db` | The centralized log, written by `pm-log-srv` |
| `stats.db` | Trade and market statistics, written by `pm-stats` |
| `clearing.db`, `clearing_report.csv` | Positions and P&L |
| `audit.log`, `audit_index.db` | The audit trail and its index |
| `gtc_orders.json`, `book_stats.json` | Resting orders and book state across restarts |
| `emo/` | One log file per process, plus the process manager's state |

Relative paths inside a configuration, such as `data/stats.db`, resolve under
this directory — so they mean the same file no matter which directory you
started a process from.

:material-checkbox-blank-outline: **Checkpoint:** you can name your data
directory, and `ref_data/` inside it contains both `engine_config.json` and
`engine_config.yaml`.


## Exercise 3: Understand the deployed configuration

EduMatcher separates **the file you author** from **the file the exchange
runs**:

```text
your engine_config.yaml   →   pm-config-deploy   →   ref_data/engine_config.json
        (edit this)              (validates,              (every process
                                  compiles)                reads this)
```

No process takes a path to a configuration. There is exactly one deployed
artifact per data directory, which is what makes it impossible to start two
processes on different configurations by accident.

Look at what your install deployed:

**If you installed with containers:**

```bash
./edumatcher.sh shell pm-config-show
cat ~/.edumatcher/data/ref_data/engine_config.yaml
```

**If you installed with pipx, the VM, or Poetry:**

```bash
pm-config-deploy --show
cat "$EDUMATCHER_DATA_DIR/ref_data/engine_config.yaml"
```

You should see a `symbols:` section and a `gateways:` section. This is the same
*kind* of file you will author yourself in the next chapter — there, though,
you keep your own copy under version control rather than editing the deployed
one.

EduMatcher ships twelve ready-made configurations: one, three, ten or thirty
order books, each as a `basic`, `nominal` or `complex` variant. See
[Example Engine Configs](../user-guide/810-example-configs.md) for what each
contains.

:material-checkbox-blank-outline: **Checkpoint:** you can display the deployed
configuration and see its symbols.


## Exercise 4: Customise your installation

### Choosing a different configuration

**If you installed with containers:**

```bash
cd ~/.edumatcher
./edumatcher.sh config ten-nominal      # a bundled example
./edumatcher.sh config ./my-market.yaml # or one of your own
./edumatcher.sh restart
```

A file of your own is copied into `~/.edumatcher/config/` and deployed on
every start, so editing it and restarting is the whole edit-test loop.

**If you installed with pipx, the VM, or Poetry:**

```bash
pm-config-deploy ~/configs/classroom.yaml
```

Or give a scenario its own data directory, which isolates its statistics
and logs as well:

```bash
export EDUMATCHER_DATA_DIR=~/sessions/classroom
pm-config-deploy ~/configs/classroom.yaml
```

### Settings — the `.env` file (containers only)

`~/.edumatcher/.env` holds every choice about a running install. Compose reads
it automatically because it sits beside `compose.yaml`; there is no other
configuration file, and `compose.yaml` itself contains only `${VARIABLE}`
references into it. The installer writes it once and then **keeps your copy**,
so updating does not discard your edits.

| Variable | Default | What it does |
|---|---|---|
| `EM_VERSION` | *(the installed release)* | Which release to run. All five images carry this tag, so one value pins the whole system |
| `GHCR_OWNER` | `johan162` | The registry namespace images come from. Change only for a fork |
| `EM_CONFIG` | `three-basic` | Which bundled example the exchange deploys |
| `EM_CONFIG_FILE` | *(empty)* | Set when you run a configuration of your own; non-empty wins over `EM_CONFIG` |
| `EM_PROFILE` | `default` | Which processes start: `default`, `mini` or `micro` |
| `TZ` | `UTC` | Container timezone — match the trading calendar in your configuration |
| `BIND_ADDR` | `127.0.0.1` | Which host interface the published ports listen on — **the setting that decides whether the exchange is on your network** |
| `EM_ZMQ` | `0` | `1` also publishes the raw ZeroMQ bus, and tells the engine and `pm-index` to bind the container interface so host tools can attach |
| `EDUMATCHER_GATEWAY_BIND_HOST` | `0.0.0.0` | Bind host for the gateways *inside* the container. This is what makes them reachable from the GUI containers; it is not a host-exposure setting |
| `TERMINAL_GUI_PORT` | `8090` | Host port for the trading terminal |
| `LOG_GUI_PORT` | `8091` | Host port for the log viewer |
| `CONFIG_GUI_PORT` | `8092` | Host port for the configuration builder |
| `TRADER_GUI_PORT` | `8093` | Host port for the trader GUI |

Change any of them and run `./edumatcher.sh restart`. Two have their own
commands, because they need more than an edit — `./edumatcher.sh config` keeps
`EM_CONFIG` and `EM_CONFIG_FILE` consistent, and `./edumatcher.sh update`
pulls images after changing `EM_VERSION`.

!!! warning "`BIND_ADDR=0.0.0.0` puts an unauthenticated exchange on your network"
    It is the right setting for a classroom where students connect to the
    instructor's machine, and the wrong one on a network you do not control:
    the protocol gateways have no password. The default keeps everything on
    this machine.

!!! note "Two different `0.0.0.0`s"
    `0.0.0.0` appears twice above and means two different things. On
    `BIND_ADDR` it is a real exposure decision: it opens the published ports to
    your LAN. On `EDUMATCHER_GATEWAY_BIND_HOST` it is not — that address lives
    inside the container's private network, where the only route in is a port
    `BIND_ADDR` published. Widening it lets the GUI containers reach the
    exchange and nothing else. [The installation
    chapter](../user-guide/005-installation.md#what-0000-does-and-does-not-expose)
    works through all three places an address appears.

:material-checkbox-blank-outline: **Checkpoint:** you have switched to a
different bundled configuration and seen the symbols change.


## Exercise 5: Confirm your entry points

Verify the commands the coming chapters use. Prefix each with
`./edumatcher.sh shell` on the container route, or run them directly
otherwise:

```bash
pm-engine --help
pm-scheduler --help
pm-alf-console --help
pm-config-deploy --help
pm-config-gen --help
pm-mm-bot --help
```

Each should print usage information without errors.

!!! note "`pm-mm-bot` is available"
    It is part of the installed command set. Chapter 02 starts with manual
    market-maker quotes so you understand quote mechanics first, then
    introduces the equivalent bot-based workflow.

:material-checkbox-blank-outline: **Checkpoint:** all commands respond to
`--help`.


## Troubleshooting

A quick index of the problems most students hit, and where above each one is
handled in full:

| Symptom | Cause | Fix |
|---|---|---|
| Installer exits immediately with "Neither podman nor docker is installed" | No container engine on this machine | Install Podman or Docker Desktop, then re-run the install command |
| `./edumatcher.sh start` fails with a bind error naming a port | Something else on your machine already uses `8080` or `8090`–`8093` | Free the port or stop the other service, then `./edumatcher.sh start` again |
| Starting a second install fails, naming another install's data directory | Container names and ports are fixed, so two installs cannot run side by side | Stop the other one (`./edumatcher.sh stop` in its directory), then retry — see the warning in Exercise 1 |
| `pip install pipx` fails with `externally-managed-environment` | Modern Linux distributions block installing into the system Python | Use `python -m pip install --user pipx` instead, as Route B now shows |
| `command not found: pm-engine` right after `pipx install edumatcher` | `pipx ensurepath` only takes effect in a *new* shell | Open a new terminal (or `exec $SHELL`) and try again |
| `pm-engine --version` works in one terminal but not another | `EDUMATCHER_DATA_DIR` was exported in one shell but never added to your shell profile | Add the `export` line from `pm-setup`'s output to `~/.zshrc` or `~/.bashrc`, then open a new terminal |
| `multipass version` reports `command not found` | Multipass did not finish installing, or your shell has not picked up its PATH change | Reinstall from [multipass.run](https://multipass.run/install), then open a new terminal |
| Container route: chapter exercises see a market that already has orders in it | The `default` profile is still running from install | `pm-opctl-cli stop` inside `./edumatcher.sh shell`, as the "Before You Continue" checklist below requires |

If something goes wrong that is not on this list, `./edumatcher.sh logs` (container
route) or the relevant process's own `--verbose` output is the next place to
look, and [Running the Exchange](../user-guide/040-running-the-exchange.md) has
a fuller troubleshooting section for problems that show up after startup.


## Summary

You now have:

- EduMatcher installed — Containers by default, or one of the three alternate
  routes for a reason of your own — and you know which one you chose.
- A data directory you can name, holding the deployed configuration and
  everything the exchange writes.
- A deployed configuration you can display, swap for another bundled example,
  or replace with your own.
- A way to run `pm-*` commands for the chapters that follow.

## Before You Continue

Confirm every item before starting Chapter 01 — each is a prerequisite that
chapter assumes without re-explaining:

- [ ] A configuration is deployed, and you can display it.
- [ ] You can name your data directory, and `ref_data/` inside it contains both
      `engine_config.json` and `engine_config.yaml`.
- [ ] `pm-engine --version` and `pm-engine --help` both resolve **in the shell
      you will use for the next chapter** — for pipx that means
      `EDUMATCHER_DATA_DIR` is in your shell profile, not just this terminal;
      for containers it means a shell opened with `./edumatcher.sh shell`.
- [ ] On the container route only: `pm-opctl-cli stop`, so the next chapter can
      start the processes itself.

## Reflection

Why does EduMatcher refuse to let a process take a path to a configuration
file, insisting instead on one deployed artifact per data directory? What would
break in Chapter 16 (Persistence & Recovery) if two terminals ended up pointing
at two different data directories?

And if you took the container route: the log viewer reports its database as
`/backend-data/log.db` while the exchange reports the same file as
`/data/log.db`. Why do two names for one file make the system safer rather than
more confusing?

## Further Reading

- [Installation](../user-guide/005-installation.md) — the reference version of
  this chapter, with every flag, directory and build option
- [Getting Started](../user-guide/000-getting-started.md)
- [Running the Exchange](../user-guide/040-running-the-exchange.md)
- [Processes](../user-guide/170-processes.md)

**Next:** [01 — Configuring & Starting Up](010-configuring-startup.md)

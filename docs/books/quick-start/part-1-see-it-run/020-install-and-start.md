# Install and Start

!!! note "Learning objectives"
    After this chapter you will have:

    - a running exchange, started with one command
    - the browser applications open and showing live quotes
    - a terminal "inside" the exchange where every `pm-*` command works
    - an idea of where EduMatcher keeps its data, and how to stop and start it

**Time:** about 15 minutes, most of it spent downloading.

## Before you start

You need a Linux or macOS computer. On Windows, install WSL 2 and run every
command in this book in its Linux terminal: the installer and the
`edumatcher.sh` control script are bash scripts. You also need a web browser
and an internet connection for the first download of the container images.

Check what you already have by typing these in a terminal:

```bash
podman --version           # either of these two is enough ...
docker --version
docker compose version     # ... but Docker also needs Compose
python3 --version          # only for the Python route; it must say 3.14 or newer
```

A "command not found" simply means that tool is not installed. If you have
neither Podman nor Docker, install one first (on macOS, Docker Desktop or
Podman with `podman machine start`; on Linux, your package manager). Most
people should then use the container route below.

## Pick a route

There are two ways in. Both give you the same exchange.

| | **Containers** (recommended) | **Python package** (`pipx`) |
|---|---|---|
| You need | Podman or Docker, with Compose | Python 3.14 and `pipx` |
| Time to a running exchange | one command | a few commands |
| Browser applications | six, ready to use | not included |
| Where `pm-*` commands run | inside the container, after `./edumatcher.sh shell` | in your own terminal |
| Your data lives in | `~/.edumatcher/data` | `~/.local/share/edumatcher` |
| Best for | seeing the whole system; classes and demos | learning the processes one by one |

If you are unsure, use containers: nothing is installed outside one directory
you can delete again, and you get the browser applications for free. The
Operator's Guide [Installation](../../operator-guide/part-1-install-and-deploy/010-installation.md)
chapter describes these and three more routes (a Multipass VM, building the
containers from source, and a developer checkout) in full detail.

## Route 1: containers

### Install and start

With Podman or Docker installed, run:

```bash
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/curl/install.sh | bash
cd ~/.edumatcher
```

(The installer is a short script that you are piping into `bash`. If you
prefer to read it first, open the URL in a browser, or download it with
`curl -fsSLO <the same URL>`, look through it and run `bash install.sh`.)

The installer downloads the latest release into `~/.edumatcher`, pulls seven
container images (the exchange plus six browser applications) and starts
them. The first start takes a few minutes; later starts take seconds. When it
finishes it prints the addresses of the browser applications.

`./edumatcher.sh` is your control panel for this installation. You only need
a handful of its commands:

| Command | What it does |
|---|---|
| `./edumatcher.sh status` | Shows the containers and every exchange process with its health |
| `./edumatcher.sh urls` | Prints the browser addresses again |
| `./edumatcher.sh shell` | Opens a terminal inside the exchange, where the `pm-*` commands live |
| `./edumatcher.sh logs` | Follows what the containers print, starting with the startup messages; press `Ctrl-C` to stop watching (the exchange keeps running) |
| `./edumatcher.sh config <name>` | Chooses another configuration (applied by the next `restart`) |
| `./edumatcher.sh restart` | Stops and starts everything, applying configuration changes |
| `./edumatcher.sh stop` / `start` | Stops or starts everything; your data is kept |

### Checkpoint: open the browser applications

Open these addresses on the same computer:

| Address | Application | What you should see |
|---|---|---|
| <http://localhost:8090> | **TapeDeck** — the market display | Ten symbols (`AAPL`, `MSFT`, `TSLA`, …) with bid and ask prices |
| <http://localhost:8094> | **Order Book Viewer** | One symbol's full book; press `s` to switch symbol |
| <http://localhost:8093> | **Trading GUI** | A login screen — you will use it in [The Browser Applications](040-the-browser-applications.md) |
| <http://localhost:8091> | **Log Operator Console** | The operational log of every process |
| <http://localhost:8095> | **Operator Dashboard** | Every process HEALTHY and the exchange OPERATIONAL |
| <http://localhost:8092> | **Configuration GUI** | A form-based editor for exchange configurations |
| <http://localhost:8080/docs> | **REST API documentation** | The interactive Swagger page of the API gateway |

Then confirm that the exchange itself is healthy:

```bash
./edumatcher.sh status
```

Every process in the table should show `running`. If a container is missing
or a page does not open, see
[When Something Does Not Work](../90-backmatter/020-when-something-does-not-work.md).

!!! question "Where do the prices on TapeDeck come from?"
    The container starts a slow **market-maker bot**, `pm-mm-bot`, trading as
    participant `MM01`. A market maker's job is to always offer to buy (a
    *bid*) and to sell (an *ask*), so the books are never empty. Nobody is
    trading yet, so you see quotes moving now and then, but no trades. You
    will make the first trade in the next chapter.

### What you just started

One container runs the exchange: the engine and about fifteen supporting
processes (sixteen in all, including the market-maker bot), started in the right order by the process manager `pm-opctl-cli`.
Six more containers run the browser applications. They share a private
network, which is why nothing asked you for an address. The bundled
configuration is called `s10-basic`: ten symbols, four participants
(`TRADER01`, `TRADER02`, `MM01` and the operator `OPS01`) and no trading-day
schedule, so the market is open for continuous trading straight away.

### A terminal inside the exchange

The `pm-*` commands are installed inside the exchange container, not on your
computer. Open a shell there:

```bash
./edumatcher.sh shell
```

Your prompt changes, and every `pm-*` command now works. Try the built-in
command index:

```bash
pm-help                 # one line for every pm-* command, grouped by purpose
pm-help pm-alf-console  # the full manual page of one command
pm-config-show          # what the running exchange is configured with
```

Leave the shell with `exit` or `Ctrl-D`. You can open as many as you like, one
per terminal window — the next chapter uses two.

## Route 2: the Python package

Use this route if you would rather run each process yourself, or cannot use
containers. It needs **Python 3.14 or newer**, which many systems do not have
by default (check with `python3 --version`); if yours is older, use the
container route instead.

[`pipx`](https://pipx.pypa.io) installs Python programs in their own
environments. If `pipx --version` says "command not found", install it with
your package manager (for example `brew install pipx` on macOS, or
`python3 -m pip install --user pipx`) and then run `pipx ensurepath`.
Open a new terminal window afterwards so the change takes effect. Then:

```bash
pipx install edumatcher
pm-setup
```

If you have several Python versions, tell pipx which to use:
`pipx install --python python3.14 edumatcher`.

`pm-setup` creates the data directory (`~/.local/share/edumatcher`) and
deploys the bundled `s10-basic` configuration. It also prints one line to
add to your shell profile:

```bash
export EDUMATCHER_DATA_DIR="$HOME/.local/share/edumatcher"
```

Every `pm-*` process finds the configuration, and writes its databases and
logs, through this one variable, so all processes of one exchange must agree
on it.

Start the whole exchange with the process manager, and check it:

```bash
pm-opctl-cli start      # starts the full set of processes in the right order
pm-opctl-cli list       # one line per process, with its health
```

`pm-opctl-cli stop` stops them all again. The next chapter also shows how to
start just the two or three processes a first trade needs, one terminal each —
the slow way, and the best way to see what every process does.

!!! note "Browser applications on the Python route"
    The browser applications are web projects of their own and are not part
    of the Python package, but you can run them as ready-built containers
    next to your `pipx` exchange (a plain exchange or the simulation). With
    Podman or Docker installed, and the exchange started with
    `EDUMATCHER_GATEWAY_BIND_HOST=0.0.0.0 pm-opctl-cli start`:

    ```bash
    curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/curl/install.sh \
    | bash -s -- --guis
    ```

    The addresses are the same as on the container route. The Operator's Guide
    chapter [Installation](../../operator-guide/part-1-install-and-deploy/010-installation.md#web-applications-with-a-pipx-exchange)
    explains what it sets up and what to check if a GUI stays empty.

## Where your data lives

Everything the exchange produces — order books saved between sessions,
statistics, profit-and-loss records, the audit trail, logs — is an ordinary
file in one data directory:

| Route | Data directory |
|---|---|
| Containers | `~/.edumatcher/data` (seen as `/data` inside the container) |
| Python package | `~/.local/share/edumatcher`, or `$EDUMATCHER_DATA_DIR` if set |

The deployed configuration is inside it, at `ref_data/engine_config.json`.

!!! note "Why the two routes use different directories"
    The Python code picks the directory the same way on both routes; the
    container simply sets `EDUMATCHER_DATA_DIR=/data` and mounts the `data`
    folder of your install directory there. The routes keep their data apart
    on purpose:

    - **One folder per install.** `~/.edumatcher` holds the script, its
      settings and the data, so deleting that one folder removes the whole
      installation, and installs made with `--dir` never share data.
    - **No clashes.** A container and a `pipx` install sharing one directory
      would overwrite each other's deployed configuration and databases, and
      different versions may not accept each other's compiled configuration.
    - **File ownership.** With Docker on Linux the container writes its
      files as `root`, which your own `pm-*` commands could then not change.

    The consequence: a `pm-*` command you installed with `pipx` does **not**
    see the container's exchange data by default. Use
    `./edumatcher.sh shell` instead, or point the command at the container's
    data explicitly:

    ```bash
    export EDUMATCHER_DATA_DIR="$HOME/.edumatcher/data"
    ```
The Reference Manual's
[Environment variables](../../reference-manual/part-1-command-line/010-processes-environment-and-ports.md#environment-variables)
section explains exactly how the directory is chosen, and the Operator's Guide
chapter [Persistence](../../operator-guide/part-6-observe-and-recover/010-persistence.md)
lists every file in it.

## Where to go next

Continue with [Your First Trade](030-your-first-trade.md). If something did not
work, see [When Something Does Not Work](../90-backmatter/020-when-something-does-not-work.md).

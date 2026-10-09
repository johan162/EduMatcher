# Install and Start

!!! note "Learning objectives"
    After this chapter you will have:

    - a running exchange, started with one command
    - the browser applications open and showing live quotes
    - a terminal "inside" the exchange where every `pm-*` command works
    - an idea of where EduMatcher keeps its data, and how to stop and start it

**Time:** about 15 minutes, most of it spent downloading.

## Pick a route

There are two ways in. Both give you the same exchange.

| | **Containers** (recommended) | **Python package** (`pipx`) |
|---|---|---|
| You need | Podman or Docker, with Compose | Python 3.13 and `pipx` |
| Time to a running exchange | one command | a few commands |
| Browser applications | five, ready to use | not included |
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

The installer downloads the latest release into `~/.edumatcher`, pulls six
container images (the exchange plus five browser applications) and starts
them. The first start takes a few minutes; later starts take seconds. When it
finishes it prints the addresses of the browser applications.

`./edumatcher.sh` is your control panel for this installation. You only need
a handful of its commands:

| Command | What it does |
|---|---|
| `./edumatcher.sh status` | Shows the containers and every exchange process with its health |
| `./edumatcher.sh urls` | Prints the browser addresses again |
| `./edumatcher.sh shell` | Opens a terminal inside the exchange, where the `pm-*` commands live |
| `./edumatcher.sh logs` | Shows what the exchange printed while starting |
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
| <http://localhost:8092> | **Configuration GUI** | A form-based editor for exchange configurations |
| <http://localhost:8080/docs> | **REST API documentation** | The interactive Swagger page of the API gateway |

Then confirm that the exchange itself is healthy:

```bash
./edumatcher.sh status
```

Every process in the table should show `running`.

!!! question "Where do the prices on TapeDeck come from?"
    The container starts a slow **market-maker bot**, `pm-mm-bot`, trading as
    participant `MM01`. A market maker's job is to always offer to buy (a
    *bid*) and to sell (an *ask*), so the books are never empty. Nobody is
    trading yet, so you see quotes moving now and then, but no trades. You
    will make the first trade in the next chapter.

### What you just started

One container runs the exchange: the engine and about fourteen supporting
processes, started in the right order by the process manager `pm-opctl-cli`.
Five more containers run the browser applications. They share a private
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
containers.

```bash
pipx install edumatcher
pm-setup
```

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
    of the Python package. The easiest way to use them is the container route
    above.

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

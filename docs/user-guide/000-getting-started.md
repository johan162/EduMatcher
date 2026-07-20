# Getting Started with EduMatcher

!!! note "Learning objectives"
    After reading this page you will understand:

    - What EduMatcher is and what you can do with it
    - The minimum steps to start an exchange and execute your first trade
    - What each process does and when to start it
    - How to quickly bootstrap a new `engine_config.yaml` with `pm-config-gen`
    - Which sections to read next based on your role



## What is EduMatcher?

EduMatcher is a **fully functional financial exchange matching engine** built for
education, research, and demo purposes. It implements the same core mechanics that
underpin real stock exchanges:

- A **continuous order book** that matches buyers and sellers
- **Auction phases** (opening and closing) with equilibrium price calculation
- **Market-maker quoting** with obligations and protection
- **Risk controls**: price collars, circuit breakers, kill switches
- **Combo and OCO orders**: multi-leg strategies with cascade cancellation
- **Statistics recording** (OHLCV, VWAP, mid prices) in SQLite
- **Drop-copy feed** for compliance monitoring
- **Autonomous AI traders** to simulate real order flow

Participants connect via a terminal (the *gateway*) and type commands to place
orders. The engine matches them and publishes fill events over a ZeroMQ message bus
that all other processes subscribe to.

```mermaid
flowchart LR
    GW1["pm-alf-console\nParticipant A"]
    GW2["pm-alf-console\nParticipant B"]
    AI["pm-ai-trader\nAutonomous bot"]
    ENG["pm-engine\nMatching engine\nPULL :5555 / PUB :5556"]
    ADM["pm-admin\nOperator console"]
    CLR["pm-clearing\nP&L tracker"]
    STAT["pm-stats\nStatistics recorder"]
    DC["Drop-copy feed\n(built into pm-engine)\n:5557"]
    SCH["pm-scheduler\nSession phases"]

    GW1 -- "NEW|SYM=AAPL|..." --> ENG
    GW2 -- "NEW|SYM=AAPL|..." --> ENG
    AI -- "orders" --> ENG
    ADM -- "HALT / RESUME / STATUS" --> ENG
    ENG -- "fills / book / session" --> GW1
    ENG -- "fills / book / session" --> GW2
    ENG -- "trade.executed" --> CLR
    ENG -- "trade.executed / book." --> STAT
    ENG -- "per-fill drop-copy" --> DC
    SCH -- "session state" --> ENG
```

## How to get started

Running the exchange is complex enough that you really **need** to read the documentation and follow the instructions in the User Guide to get a full exchange up and running. The installation below is just the very first step to get started. The rest of the User Guide will explain how to configure the exchange, start and stop processes, and run the system in a realistic way. 

This might seem overwhelming at first and the best way to get started is to skim through the entirety of the user-guide. After the installation a good way to get started is through the self-paced [training sections](../training/index.md)


## Installation

EduMatcher supports three installation modes. Choose the one that matches your role:

- **VM bootstrap** — a ready-to-run VM; nothing to install on your host
- **End-user / pipx** — quickest way to just run an exchange session (recommended)
- **Developer / Poetry** — for modifying the engine, running tests, or contributing


### VM bootstrap mode — `curl` + Multipass (no repo clone)

Use this mode when you want a ready-to-run EduMatcher VM without installing
Python or cloning this repository on your host.

**What is Multipass?**

Multipass is a lightweight VM manager from Canonical. It launches Ubuntu VMs
with simple CLI commands so you can run isolated Linux environments locally on
macOS, Linux, or Windows.

**Requirements**

| Requirement     | Notes                                                       |
|-----------------|-------------------------------------------------------------|
| Multipass       | Install from [multipass.run](https://multipass.run/install) |
| curl            | Used to download the VM bootstrap script                    |
| Internet access | Required for downloading scripts and PyPI packages          |
| Host resources  | Recommended minimum: 2 vCPU, 3 GB RAM, 10 GB disk           |

**Bootstrap with one command**

```bash
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/vm/curl_setup_vm.sh | bash -s -- --version 0.16.0 --snapshot
```

This command downloads the VM setup scripts, launches a Multipass VM,
installs EduMatcher in the VM, links all `pm-*` commands into
`/usr/local/bin`, prepares `/home/ubuntu/session`, and optionally takes
an initial snapshot.

**Start using the VM**

```bash
multipass shell edumatcher-vm
cd /home/ubuntu/session
pm-engine --verbose
```

Open additional host terminals and run `multipass shell edumatcher-vm` in each
terminal to start `pm-alf-console`, `pm-viewer`, `pm-clearing`, and `pm-audit`.

**Useful bootstrap options**

```bash
# Different VM name and version
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/vm/curl_setup_vm.sh | \
    bash -s -- --name edumatcher-vm --version 0.16.0 --snapshot

# Tune resources
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/vm/curl_setup_vm.sh | \
    bash -s -- --cpus 2 --memory 3G --disk 8G
```

**Optional: inspect script before execution**

```bash
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/vm/curl_setup_vm.sh -o curl_setup_vm.sh
less curl_setup_vm.sh
bash curl_setup_vm.sh --version 0.16.0 --snapshot
```

### End-user / student mode — `pipx install` (recommended)

This is the quickest path if you just want to *run* an exchange session —
no source code, no Poetry, no virtual environment management.

**Requirements**

| Requirement                    | Notes                                    |
|--------------------------------|------------------------------------------|
| Python 3.13 or later           | Check with `python --version`            |
| Three or more terminal windows | Or a terminal multiplexer such as `tmux` |

**Install**

If using `brew` then install `pipx` 

```bash
# Install pipx using homebrew
brew install pipx
pipx ensurepath        # adds ~/.local/bin to PATH; reopen your shell after this
```

or on Linux

```bash
# Install pipx (once, if not already present)
pip install pipx
pipx ensurepath        # adds ~/.local/bin to PATH; reopen your shell after this
```


**Install EduMatcher — all pm-* commands land on your PATH**

Run the commands below to install EduMatcher with `pipx`, create a fresh working
directory for your exchange session, and initialize it with `pm-setup` so the
`pm-*` commands and local defaults are ready to use.

```bash
pipx install edumatcher
mkdir session
cd session
pm-setup
```

`pm-setup` prints a shell snippet to add to your `.zshrc` / `.bashrc`:

```bash
export EDUMATCHER_DATA_DIR="$HOME/.local/share/edumatcher"
export EDUMATCHER_CONFIG="$HOME/my-exchange-session/engine_config.yaml"
```

Or use the provided one-shot script (handles pipx installation automatically):

```bash
./scripts/install-runtime.sh
```

After reloading your shell, every `pm-*` command picks up the right data
directory automatically — no flags needed.

**Edit the config, then start trading**

If you prefer generating a starter config instead of manually writing YAML:

```bash
pm-config-gen \
    --symbols AAPL MSFT \
    --gateways TRADER01 TRADER02 OPS01:ADMIN \
    --sessions-enabled \
    --output engine_config.yaml
```

Then edit any remaining details and start the engine.

For full generator details (all flags, `--symbol-opts`, MM quote stubs,
validation hints, and recipes), see
[Configuration](010-configuration.md#generate-configs-with-pm-config-gen).

```bash
# Edit the sample config that pm-setup copied into your directory
nano engine_config.yaml

# Start the engine
pm-engine --verbose
```



### Developer mode — Poetry + source checkout

Use this mode if you want to modify the engine, run tests, or contribute.

**Requirements**

| Requirement                          | Notes                                         |
|--------------------------------------|-----------------------------------------------|
| Python 3.13 or later                 | Check with `python --version`                 |
| [Poetry](https://python-poetry.org/) | `pip install poetry` or `pipx install poetry` |
| Three terminal windows               | Or `tmux` / `screen`                          |

**Install**

```bash
git clone https://github.com/johan162/EduMatcher.git
cd EduMatcher
poetry install --with dev
```

Data is stored in `src/data/` inside the repo and `engine_config.yaml` is
read from the repo root — no environment variables needed.

All commands are prefixed with `poetry run`:


```bash
poetry run pm-engine --verbose
poetry run pm-alf-console --id GW01
```

!!! tip "Switching from developer to end-user mode"
    You can install the locally built wheel with pipx at any time:

    ```bash
    poetry build
    pipx install dist/edumatcher-*.whl --force
    pm-setup --force    # re-copy the latest sample config
    ```



## Environment variables

These two variables work in both modes. Set them in your shell profile to
override the defaults permanently.

| Variable              | Default (installed)          | Default (source)            | Purpose                                    |
|-----------------------|------------------------------|-----------------------------|--------------------------------------------|
| `EDUMATCHER_DATA_DIR` | `~/.local/share/edumatcher`  | `<repo>/src/data/`          | Where all persistent data files are stored |
| `EDUMATCHER_CONFIG`   | `./engine_config.yaml` (CWD) | `<repo>/engine_config.yaml` | Path to the engine configuration YAML      |

The `--config` flag on `pm-engine` and `pm-scheduler` always takes precedence
over both the environment variable and the default.



## PM command family overview

Use these tables as a quick index for every `pm-` entry point currently
documented. All commands are shown in pipx form; in developer mode prepend
`poetry run`. All `pm-` processes/utilities are described in [Processes](170-processes.md).

### Runtime processes (runnable)

| Command | Interactivity | Purpose | More information |
|---|---|---|---|
| `pm-engine` | Background | Matching engine; central order-book writer | [Processes](170-processes.md), [Running the Engine](040-running-the-engine.md), [Configuration](010-configuration.md) |
| `pm-alf-console` | Interactive terminal | ALF participant terminal and order entry | [Processes](170-processes.md), [Gateway](050-gateway.md), [ALF Protocol](900-app-alf-protocol.md) |
| `pm-scheduler` | Background | Session phase transitions by schedule | [Processes](170-processes.md), [Auctions and Scheduling](080-auctions-scheduling.md) |
| `pm-viewer` | Terminal display | Single-symbol live order book view | [Processes](170-processes.md), [Order Types](060-order-types.md) |
| `pm-orders` | Terminal display | Live cross-gateway order status monitor | [Processes](170-processes.md), [Messages](270-messages.md) |
| `pm-board` | Terminal display | Multi-symbol market board display | [Processes](170-processes.md) |
| `pm-ticker` | Terminal display | Scrolling ticker with live plus OHLCV context | [Processes](170-processes.md), [Statistics and Reporting](140-statistics-and-reporting.md) |
| `pm-stats` | Background | Persist market statistics to SQLite | [Processes](170-processes.md), [Statistics and Reporting](140-statistics-and-reporting.md) |
| `pm-clearing` | Terminal display | Trade recording and running P&L | [Processes](170-processes.md), [P&L and Clearing](130-pnl-clearing.md) |
| `pm-audit` | Background | Full event log capture from the bus | [Processes](170-processes.md), [Persistence](180-persistence.md) |
| `pm-ralf-gwy` | Background | External post-trade dissemination gateway (RALF) | [Processes](170-processes.md), [Post-Trade Dissemination](250-post-trade.md), [RALF Protocol](930-app-ralf-protocol.md) |
| `pm-admin` | Interactive terminal | Interactive operational console | [Processes](170-processes.md), [Risk Controls](120-risk-controls.md) |
| `pm-ai-trader` | Background | Single autonomous trading bot gateway | [Processes](170-processes.md), [AI Traders](110-ai-traders.md) |
| `pm-ai-swarm` | Background | Multi-agent autonomous trading swarm | [Processes](170-processes.md), [AI Traders](110-ai-traders.md) |
| `pm-mm-bot` | Background | Autonomous market-maker quoting bot | [Processes](170-processes.md), [Market-Maker Bot](100-mm-bot.md) |
| `pm-md-gwy` | Background | Market-data distribution gateway (CALF) | [Processes](170-processes.md#pm-md-gwy-calf-market-data-gateway), [Market Data Feed](240-market-data-feed.md), [CALF Protocol](920-app-calf-protocol.md) |
| `pm-api-gwy` | Background | REST/WebSocket order-entry and market-data API gateway | [Processes](170-processes.md#pm-api-gwy-restwebsocket-api-gateway), [API Gateway](260-api-gateway.md) |
| `pm-index` | Background | Real-time cap-weighted index calculation and dissemination | [Processes](170-processes.md#pm-index-index-calculation-process), [Market Index](150-index.md) |
| `pm-balf-gwy` | Background | Binary order-entry gateway (BALF) over TCP | [Processes](170-processes.md), [BALF Gateway](230-balf-gateway.md), [BALF Protocol](910-app-balf-protocol.md) |

### CLI utilities (runnable)

| Command |  Purpose | More information |
|---|---|---|
| `pm-admin-cli` | Non-interactive admin commands for scripts | [Processes](170-processes.md), [Risk Controls](120-risk-controls.md) |
| `pm-cverifier` | Validate `engine_config.yaml` before runtime (YAML, schema, semantic, completeness checks) | [Processes](170-processes.md), [Configuration](010-configuration.md), [Config Verifier](020-config-verifier.md) |
| `pm-stats-cli` | Query `stats.db` without writing SQL | [Processes](170-processes.md#pm-stats-cli-statistics-query-cli), [Statistics and Reporting](140-statistics-and-reporting.md) |
| `pm-clearing-cli` | Query `clearing.db` without writing SQL | [Processes](170-processes.md#pm-clearing-cli-clearing-query-cli), [P&L & Clearing](130-pnl-clearing.md) |
| `pm-audit-cli` | Query audit log files without shell pipelines | [Processes](170-processes.md#pm-audit-event-logger), [Audit Trail](190-audit.md) |
| `pm-index-cli` | Read-only query interface for index history files | [Processes](170-processes.md#pm-index-cli-index-structuralaudit-history-query-tool), [Commands](160-commands.md), [Market Index](150-index.md#using-pm-index-cli-for-structuralaudit-records) |
| `pm-index-admin-cli` | Apply index corporate actions (splits, dividends, share issuance/buybacks) and constituent changes (add/delist) | [Processes](170-processes.md#pm-index-admin-cli-index-corporate-action-constituent-change-cli), [Index Admin CLI](152-index-admin-cli.md), [Market Index](150-index.md) |
| `pm-calf-spy` | Spy on the CALF market-data protocol — connect to `pm-md-gwy` and print every line, human-readable or JSON | [Processes](170-processes.md#pm-calf-spy-calf-protocol-spy), [CALF Protocol Spy](241-calf-spy-cli.md), [Market Data Feed](240-market-data-feed.md) |
| `pm-setup` |  Bootstrap local session directory and defaults | [Processes](170-processes.md), [Installation](000-getting-started.md#installation) |
| `pm-config-gen` | Generate `engine_config.yaml` from CLI options | [Processes](170-processes.md), [Configuration generator](010-configuration.md#generate-configs-with-pm-config-gen) |

For startup order and a practical first-run sequence, see
[Processes](170-processes.md#process-overview).


## Market-Maker Quick Reference

If your gateway role is `MARKET_MAKER`, this is the fastest practical command
set for quote operation and fill recognition:

| Goal                       | Command                                                                            |
|----------------------------|------------------------------------------------------------------------------------|
| Submit/replace quote       | `QUOTE\|SYM=AAPL\|BID=209.80\|ASK=210.20\|BID_QTY=500\|ASK_QTY=500\|QUOTE_ID=Q123` |
| Cancel active quote        | `QUOTE_CANCEL\|SYM=AAPL`                                                           |
| Show active quote legs     | `QLEGS`                                                                            |
| Show one-symbol quote legs | `QLEGS\|SYM=AAPL`                                                                  |
| Show recent completed legs | `QLEGS\|SHOW=RECENT`                                                               |
| Show active + recent legs  | `QLEGS\|SYM=AAPL\|SHOW=ALL`                                                        |

Recommended manual loop:

1. Send `QUOTE` with an explicit `QUOTE_ID`.
2. After any `FILL`, run `QLEGS|SYM=<symbol>|SHOW=ALL`.
3. Read `Filled?`, `Rem`, and `Leg status` to decide whether to re-quote.

See [Gateway](050-gateway.md#qlegs-inspect-mm-quote-legs-and-fill-flags) for
full `QLEGS` behavior and [Market Making](090-market-maker.md) for operator
workflows and policy-specific behavior.



## Five-minute minimum session

This walkthrough starts a matching engine, connects two participant terminals,
and executes one trade. No configuration file is required — the engine starts in
*unrestricted mode* when `engine_config.yaml` is absent.

!!! tip "pipx vs. developer mode"
    Commands below are shown in pipx (installed) form. In developer mode, prepend
    `poetry run` to every `pm-*` command, e.g. `poetry run pm-engine`.

### Step 1 — Start the engine

Open a terminal and run:

```bash
pm-engine
```

Expected output:

```
[ENGINE] WARNING: no engine_config.yaml found — running in unrestricted mode (no symbol/gateway allowlist)
[ENGINE] Drop copy PUB bound on port 5557
[ENGINE] Listening on PULL=tcp://127.0.0.1:5555  PUB=tcp://127.0.0.1:5556
```

With no config file the engine runs in **unrestricted mode** and session
handling is **disabled**, so it starts directly in the `CONTINUOUS` state and
matches orders immediately — there is no auction phase to advance past.

The engine is now running. Leave this terminal open.

### Step 2 — Connect Participant A (the buyer)

Open a second terminal:

```bash
pm-alf-console --id GW01
```

You should see a prompt after the connection banner:

```
[GW01] Connected to engine
GW01>
```

### Step 3 — Connect Participant B (the seller)

Open a third terminal:

```bash
pm-alf-console --id GW02
```

```
[GW02] Connected to engine
GW02>
```

### Step 4 — Check the session state

On either gateway, ask what state the exchange is in:

```
GW01> STATUS
```

The engine replies with the current session state. In unrestricted mode (no
config file) session handling is disabled, so the engine is already in
`CONTINUOUS` and matching is enabled — you do **not** need to advance any phase.

!!! tip "Session phases only apply when sessions are enabled"
    Auction phases (`PRE_OPEN → OPENING_AUCTION → CONTINUOUS → …`) only exist
    when you run with `sessions_enabled: true` and a `pm-scheduler` (or advance
    them manually from `pm-admin`). With no config, or with
    `sessions_enabled: false`, the engine stays in `CONTINUOUS` the whole time.

You can run this walkthrough with no config at all. If you prefer to be explicit,
start the engine with a config that disables sessions:

```bash
echo "sessions_enabled: false" > /tmp/demo.yaml
pm-engine --config /tmp/demo.yaml       # installed
# or:  poetry run pm-engine --config /tmp/demo.yaml
```

### Step 5 — Place orders and trade

!!! info "Book liquidity depends on your configuration"
    This walkthrough starts the engine with `sessions_enabled: false` and **no
    `engine_config.yaml`**, so the book is completely empty at startup.

    If you are running against an `engine_config.yaml` that configures `AAPL`
    with a `market_maker_quotes` seed block, the book already has a two-sided
    MM quote resting in it when trading opens. In that case, an aggressive order
    from one participant will immediately match against the seed quote — **before**
    the second participant even types anything. For example, a market buy from
    GW01 would fill against the MM's resting ask rather than waiting for GW02's
    sell.

    If this happens and you are surprised by an unexpected fill, check whether
    your config seeds the book:
    ```bash
    grep -A5 "market_maker_quotes" engine_config.yaml
    ```
    To follow this walkthrough exactly with a known-empty book, either start
    the engine with no config file, or use a config with no `market_maker_quotes`
    entries.

On Participant B's terminal, post a sell order at 150.00:

```
GW02> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.00|TIF=DAY
```

Expected response:

```
[HH:MM:SS] ORDER ACK  ord-xxxx  AAPL SELL LIMIT 100@150.00 DAY → RESTING
```

On Participant A's terminal, buy at the same price:

```
GW01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00|TIF=DAY
```

Both gateways see fill events:

```
[HH:MM:SS] FILL  ord-xxxx  AAPL BUY 100@150.00
[HH:MM:SS] FILL  ord-yyyy  AAPL SELL 100@150.00
```

A `trade.executed` event is published to all subscribers. Congratulations — you
just ran a trade on your own exchange.

### What happened under the hood

```mermaid
sequenceDiagram
    participant A as GW01 (buyer)
    participant E as pm-engine
    participant B as GW02 (seller)

    B->>E: NEW SELL AAPL 100@150.00
    E-->>B: order.ack → RESTING

    A->>E: NEW BUY AAPL 100@150.00
    E-->>A: order.ack → RESTING
    note over E: bid price ≥ ask price → match
    E-->>A: order.fill.GW01  AAPL BUY  100@150.00
    E-->>B: order.fill.GW02  AAPL SELL 100@150.00
    E-->>E: trade.executed published to all subscribers
```



## Starting more processes

The engine is the only mandatory process. Add the others as you need them,
grouped below by role.

### Mandatory

| When you want to…                                       | Start this process | More information                                |
|-------------------------------------------------------------|-----------------------|------------------------------------------------------|
| Run the matching engine (required for everything else)   | `pm-engine`         | [Running the Engine](040-running-the-engine.md) |

### Recommended core

| When you want to…                            | Start this process             | More information                                      |
|----------------------------------------------|----------------------------------|--------------------------------------------------------|
| Automate opening/closing auctions            | `pm-scheduler`                  | [Auctions and Scheduling](080-auctions-scheduling.md) |
| Capture the full event log for later audit   | `pm-audit`                      | [Audit Trail](190-audit.md)                           |
| Watch P&L update in real time                | `pm-clearing`                   | [P&L and Clearing](130-pnl-clearing.md)               |
| Use operator commands (halt/resume/session)  | `pm-admin` (interactive REPL)   | [Risk Controls](120-risk-controls.md)                 |

### Reporting, statistics & monitoring

| When you want to…                                | Start this process                      | More information                                             |
|------------------------------------------------------|--------------------------------------------|-------------------------------------------------------------------|
| Record OHLCV statistics                           | `pm-stats`                              | [Statistics and Reporting](140-statistics-and-reporting.md) |
| Query recorded statistics without SQL             | `pm-stats-cli daily --date 2026-06-14`  | [Statistics and Reporting](140-statistics-and-reporting.md) |
| Query clearing and P&L data without SQL           | `pm-clearing-cli pnl`                   | [P&L and Clearing](130-pnl-clearing.md)                     |
| Query audit logs without shell pipelines          | `pm-audit-cli events --date 2026-06-14` | [Audit Trail](190-audit.md)                                 |
| Watch a single symbol's live order book           | `pm-viewer`                              | [Order Types](060-order-types.md)                           |
| Monitor live order status across gateways         | `pm-orders`                              | [Messages](270-messages.md)                                 |
| Display a multi-symbol market board               | `pm-board`                               | [Processes](170-processes.md)                               |
| Show a scrolling ticker with OHLCV context        | `pm-ticker`                               | [Statistics and Reporting](140-statistics-and-reporting.md) |
| Calculate and disseminate a cap-weighted index    | `pm-index`                               | [Market Index](150-index.md)                                |
| Query index history without SQL                  | `pm-index-cli`                           | [Market Index](150-index.md#using-pm-index-cli-recommended) |

### Gateways

| When you want to…                                    | Start this process                      | More information                                 |
|-----------------------------------------------------------|--------------------------------------------|--------------------------------------------------------|
| Distribute market data externally (CALF)             | `pm-md-gwy`                             | [Market Data Feed](240-market-data-feed.md)     |
| Expose REST/WebSocket order entry & market data      | `pm-api-gwy`                             | [API Gateway](260-api-gateway.md)                |
| Accept binary order entry over TCP (BALF)            | `pm-balf-gwy`                           | [BALF Gateway](230-balf-gateway.md)              |
| Feed external clearing/drop-copy consumers (RALF)    | `pm-ralf-gwy`                           | [Post-Trade Dissemination](250-post-trade.md)    |
| Feed compliance/risk systems directly                | Subscribe to `:5557` (drop-copy socket) | [Drop Copy](200-drop-copy.md)                    |

### Automation

| When you want to…                                | Start this process                    | More information                  |
|------------------------------------------------------|------------------------------------------|----------------------------------------|
| Add a single autonomous trading bot               | `pm-ai-trader`                        | [AI Traders](110-ai-traders.md)   |
| Add autonomous AI order flow (multi-agent)        | `pm-ai-swarm --count 5 --duration 60` | [AI Traders](110-ai-traders.md)   |
| Add automated market-maker liquidity              | `pm-mm-bot --symbol AAPL`             | [Market-Maker Bot](100-mm-bot.md) |

### Other utilities

| When you want to…                                | Start this process | More information                                                                    |
|-------------------------------------------------------|-----------------------|------------------------------------------------------------------------------------------|
| Generate `engine_config.yaml` from CLI flags      | `pm-config-gen`     | [Configuration generator](010-configuration.md#generate-configs-with-pm-config-gen) |
| Validate `engine_config.yaml` before runtime      | `pm-cverifier`      | [Config Verifier](020-config-verifier.md)                                          |
| Run admin commands non-interactively (scripts)    | `pm-admin-cli`      | [Risk Controls](120-risk-controls.md)                                               |
| Bootstrap a local session directory               | `pm-setup`          | [Installation](000-getting-started.md#installation)                                |

!!! tip "Where does all this data go?"
    Several of these processes write data files (statistics, P&L, audit log,
    index history). For a single map of **every data file EduMatcher creates —
    which process writes it, when, why, and how to query it** — see
    [Persistence → Data files at a glance](180-persistence.md#data-files-at-a-glance).

For a full classroom session, use the provided launch script:

```bash
./tools/launch_all.sh
```

The script detects whether `pm-engine` is on PATH (installed mode) or falls
back to `poetry run` automatically when running from a source checkout.



## Typical architecture for a classroom demo

```mermaid
flowchart TD
    subgraph Instructor
        direction TB
        ADM["pm-admin\n(operator console)"]
    end
    subgraph Server
        direction TB
        ENG["pm-engine"]
        CLR["pm-clearing"]
        STAT["pm-stats"]
        SCH["pm-scheduler"]
        AI["pm-ai-swarm\n(simulated order flow)"]
    end
    subgraph Student terminals
        direction TB
        GW1["pm-alf-console --id ST01"]
        GW2["pm-alf-console --id ST02"]
        GWN["pm-alf-console --id STnn"]
    end

    ADM -- "halt / resume / session" --> ENG
    ENG -- "gateway traffic" --> GW1
    GW1 --> GW2
    GW2 --> GWN

    AI -. "orders" .-> ENG
    SCH -. "phase changes" .-> ENG
    ENG -- "trade events" --> CLR
    ENG -- "market data" --> STAT
```

Typical setup:

1. Instructor creates `engine_config.yaml` with student gateway IDs and symbols.
2. Instructor starts engine, scheduler, clearing, stats, and a small AI swarm.
3. Students each `ssh` to the server and run their gateway.
4. Instructor uses `pm-admin` to manage session phases and monitor the market.


## Reading path

Use the table below to decide what to read based on your goal.

| Goal                           | Read these sections in order                         |
|--------------------------------|------------------------------------------------------|
| **Understand the full system** | 01 → 03 → 08 → 04 → 06 → 11 → 12 → 02 → 07 → 09 → 10 |
| **Set up a classroom session** | 01 → 03 → 08 → 06 → 14 (MM) → 15 (AI)                |
| **Participate as a trader**    | 08 → 04 → 05                                         |
| **Run as a market maker**      | 01 → 08 → 14 (MM)                                    |
| **Monitor the market**         | 09 → 10 → 13 → 07                                    |
| **Write a custom client**      | 09 → 20 → 02                                         |
| **Understand risk controls**   | 12 → 06 → 04                                         |



## Glossary of terms used throughout this guide

| Term                | Meaning                                                                                            |
|---------------------|----------------------------------------------------------------------------------------------------|
| **Engine**          | The `pm-engine` matching engine process — the authoritative order book                             |
| **Gateway**         | A `pm-alf-console` participant terminal; one per trader                                                |
| **Symbol**          | A tradeable instrument, e.g. `AAPL`, `MSFT`                                                        |
| **IPO / listing**   | Defining a new symbol with its opening reference price, issued shares, and (if a market maker exists) opening quote. Those seed the book and both risk-control references. The symbol universe is fixed at startup — see [Configuration - Adding or Removing Symbols](010-configuration.md#adding-or-removing-symbols) and [Risk Controls - Day one (IPO) behaviour](120-risk-controls.md#day-one-ipo-behaviour) |
| **Order book**      | Sorted list of resting bids and asks for one symbol                                                |
| **Fill**            | An execution — the result of two orders matching                                                   |
| **TIF**             | Time-in-Force: how long an order lives (`DAY`, `GTC`, `ATO`, `ATC`)                                |
| **Tick**            | Minimum price increment (e.g. 0.01 for most equities)                                              |
| **Gateway ID**      | Unique identifier for a participant connection, e.g. `GW01`                                        |
| **Session state**   | Phase of the trading day: `PRE_OPEN`, `OPENING_AUCTION`, `CONTINUOUS`, `CLOSING_AUCTION`, `CLOSED` |
| **Market maker**    | A participant with role `MARKET_MAKER` who quotes two-sided prices                                 |
| **Circuit breaker** | Automatic halt triggered when price moves beyond a configured threshold                            |
| **Drop copy**       | A copy of all fill events published to a dedicated socket for compliance systems                   |

## See also

- [Configuration](010-configuration.md) — full `engine_config.yaml` reference
- [Configuration generator](010-configuration.md#generate-configs-with-pm-config-gen) — build `engine_config.yaml` from CLI flags
- [Running the Engine](040-running-the-engine.md) — detailed startup, monitoring, and troubleshooting
- [Gateway Commands](050-gateway.md) — complete command reference for participants
- [Order Types](060-order-types.md) — LIMIT, MARKET, STOP, ICEBERG, TRAILING_STOP, OCO, COMBO
- [Market Making](090-market-maker.md) — QUOTE command, obligations, and MMP
- [AI Traders](110-ai-traders.md) — autonomous order flow with `pm-ai-trader` and `pm-ai-swarm`
- [Market-Maker Bot](100-mm-bot.md) — automated quoting with `pm-mm-bot`
- [Post-Trade Dissemination](250-post-trade.md) — external post-trade gateway with `pm-ralf-gwy`
- [External Protocols Overview](210-protocol-overview.md) — where ALF, BALF, CALF, and RALF fit and how to choose between them
- [RALF Protocol](930-app-ralf-protocol.md) — protocol-level wire specification

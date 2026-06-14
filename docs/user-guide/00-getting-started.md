# Getting Started with EduMatcher

!!! note "Learning objectives"
    After reading this page you will understand:

    - What EduMatcher is and what you can do with it
    - The minimum steps to start an exchange and execute your first trade
    - What each process does and when to start it
    - Which sections to read next based on your role

---

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
    GW1["pm-gateway\nParticipant A"]
    GW2["pm-gateway\nParticipant B"]
    AI["pm-ai-trader\nAutonomous bot"]
    ENG["pm-engine\nMatching engine\nPULL :5555 / PUB :5556"]
    ADM["pm-admin\nOperator console"]
    CLR["pm-clearing\nP&L tracker"]
    STAT["pm-stats\nStatistics recorder"]
    DC["pm-dropcopy\nDrop-copy feed :5557"]
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

---

## Installation

EduMatcher supports two installation modes. Choose the one that matches your role.

---

### End-user / student mode — `pipx install` (recommended)

This is the quickest path if you just want to *run* an exchange session —
no source code, no Poetry, no virtual environment management.

**Requirements**

| Requirement | Notes |
|---|---|
| Python 3.13 or later | Check with `python --version` |
| Three or more terminal windows | Or a terminal multiplexer such as `tmux` |

**Install**

```bash
# Install pipx (once, if not already present)
pip install pipx
pipx ensurepath        # adds ~/.local/bin to PATH; reopen your shell after this

# Install EduMatcher — all pm-* commands land on your PATH
pipx install edumatcher
```

Or use the provided one-shot script (handles pipx installation automatically):

```bash
./scripts/install-runtime.sh
```

**Bootstrap your session directory**

```bash
cd ~/my-exchange-session    # create and cd into any working directory you like
pm-setup                    # creates ~/.local/share/edumatcher  +  copies engine_config.yaml here
```

`pm-setup` prints a shell snippet to add to your `.zshrc` / `.bashrc`:

```bash
export EDUMATCHER_DATA_DIR="$HOME/.local/share/edumatcher"
export EDUMATCHER_CONFIG="$HOME/my-exchange-session/engine_config.yaml"
```

After reloading your shell, every `pm-*` command picks up the right data
directory automatically — no flags needed.

**Edit the config, then start trading**

```bash
# Edit the sample config that pm-setup copied into your directory
nano engine_config.yaml

# Start the engine
pm-engine --verbose
```

---

### Developer mode — Poetry + source checkout

Use this mode if you want to modify the engine, run tests, or contribute.

**Requirements**

| Requirement | Notes |
|---|---|
| Python 3.13 or later | Check with `python --version` |
| [Poetry](https://python-poetry.org/) | `pip install poetry` or `pipx install poetry` |
| Three terminal windows | Or `tmux` / `screen` |

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
poetry run pm-gateway --id GW01
```

!!! tip "Switching from developer to end-user mode"
    You can install the locally built wheel with pipx at any time:

    ```bash
    poetry build
    pipx install dist/edumatcher-*.whl --force
    pm-setup --force    # re-copy the latest sample config
    ```

---

## Environment variables

These two variables work in both modes. Set them in your shell profile to
override the defaults permanently.

| Variable | Default (installed) | Default (source) | Purpose |
|---|---|---|---|
| `EDUMATCHER_DATA_DIR` | `~/.local/share/edumatcher` | `<repo>/src/data/` | Where all persistent data files are stored |
| `EDUMATCHER_CONFIG` | `./engine_config.yaml` (CWD) | `<repo>/engine_config.yaml` | Path to the engine configuration YAML |

The `--config` flag on `pm-engine` and `pm-scheduler` always takes precedence
over both the environment variable and the default.

---

## Five-minute minimum session

This walkthrough starts a matching engine, connects two participant terminals,
and executes one trade. No configuration file is required — the engine starts in
*unrestricted mode* when `engine_config.yaml` is absent.

### Step 1 — Start the engine

Open a terminal and run:

**"Installed (pipx)"** mode

```bash
pm-engine
```

**"Developer (Poetry)"** mode

 ```bash
 poetry run pm-engine
 ```

Expected output:

```
[ENGINE] EduMatcher matching engine starting
[ENGINE] Listening for orders on tcp://127.0.0.1:5555
[ENGINE] Publishing events on tcp://127.0.0.1:5556
[ENGINE] Drop-copy feed on tcp://127.0.0.1:5557
[ENGINE] Session state: PRE_OPEN
[ENGINE] Ready
```

The engine is now running. Leave this terminal open.

### Step 2 — Connect Participant A (the buyer)

Open a second terminal:

**"Installed (pipx)" mode**

```bash
pm-gateway --id GW01
```

**"Developer (Poetry)" mode**

```bash
poetry run pm-gateway --id GW01
```

You should see a prompt after the connection banner:

```
[GW01] Connected to engine
GW01>
```

### Step 3 — Connect Participant B (the seller)

Open a third terminal:

**"Installed (pipx)"** mode

 ```bash
 pm-gateway --id GW02
 ```

**"Developer (Poetry)"** mode
```bash
poetry run pm-gateway --id GW02
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

The engine replies with the current session state. In unrestricted mode it starts
in `PRE_OPEN`. To enable matching, advance to `CONTINUOUS`:

!!! tip "Skipping auctions in testing"
    Without `pm-scheduler`, the session state stays where you set it. Advance
    to `CONTINUOUS` with `pm-admin` or the operator console. The quickest way
    if you just have the engine running is to start with a config that sets
    `sessions_enabled: false` (which defaults to `CONTINUOUS`).

For this walkthrough, start the engine with:

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

---

## Starting more processes

The engine is the only mandatory process. Add the others as you need them:

| When you want to… | Start this process |
|---|---|
| Watch P&L update in real time | `pm-clearing` |
| Record OHLCV statistics | `pm-stats` |
| Use `pm-admin` operator commands | `pm-admin` (interactive REPL) |
| Schedule opening/closing auctions | `pm-scheduler` |
| Add autonomous AI order flow | `pm-ai-swarm --count 5 --duration 60` |
| Feed compliance/risk systems | Subscribe to `:5557` (drop-copy socket) |

For a full classroom session, use the provided launch script:

```bash
./tools/launch_all.sh
```

The script detects whether `pm-engine` is on PATH (installed mode) or falls
back to `poetry run` automatically when running from a source checkout.

---

## Typical architecture for a classroom demo

```mermaid
flowchart TD
    subgraph Server
        ENG["pm-engine"]
        CLR["pm-clearing"]
        STAT["pm-stats"]
        SCH["pm-scheduler"]
        AI["pm-ai-swarm\n(simulated order flow)"]
    end
    subgraph Student terminals
        GW1["pm-gateway --id ST01"]
        GW2["pm-gateway --id ST02"]
        GWN["pm-gateway --id STnn"]
    end
    subgraph Instructor
        ADM["pm-admin\n(operator console)"]
    end

    GW1 & GW2 & GWN -- "orders" --> ENG
    AI -- "orders" --> ENG
    ADM -- "halt / resume / session" --> ENG
    ENG -- "fills, book, session" --> GW1 & GW2 & GWN
    ENG --> CLR & STAT
    SCH -- "phase changes" --> ENG
```

Typical setup:

1. Instructor creates `engine_config.yaml` with student gateway IDs and symbols.
2. Instructor starts engine, scheduler, clearing, stats, and a small AI swarm.
3. Students each `ssh` to the server and run their gateway.
4. Instructor uses `pm-admin` to manage session phases and monitor the market.

---

## Reading path

Use the table below to decide what to read based on your goal.

| Goal | Read these sections in order |
|---|---|
| **Understand the full system** | 01 → 03 → 08 → 04 → 06 → 11 → 12 → 02 → 07 → 09 → 10 |
| **Set up a classroom session** | 01 → 03 → 08 → 06 → 14 (MM) → 15 (AI) |
| **Participate as a trader** | 08 → 04 → 05 |
| **Run as a market maker** | 01 → 08 → 14 (MM) |
| **Monitor the market** | 09 → 10 → 13 → 07 |
| **Write a custom client** | 09 → 20 → 02 |
| **Understand risk controls** | 12 → 06 → 04 |

---

## Glossary of terms used throughout this guide

| Term | Meaning |
|---|---|
| **Engine** | The `pm-engine` matching engine process — the authoritative order book |
| **Gateway** | A `pm-gateway` participant terminal; one per trader |
| **Symbol** | A tradeable instrument, e.g. `AAPL`, `MSFT` |
| **Order book** | Sorted list of resting bids and asks for one symbol |
| **Fill** | An execution — the result of two orders matching |
| **TIF** | Time-in-Force: how long an order lives (`DAY`, `GTC`, `ATO`, `ATC`) |
| **Tick** | Minimum price increment (e.g. 0.01 for most equities) |
| **Gateway ID** | Unique identifier for a participant connection, e.g. `GW01` |
| **Session state** | Phase of the trading day: `PRE_OPEN`, `OPENING_AUCTION`, `CONTINUOUS`, `CLOSING_AUCTION`, `CLOSED` |
| **Market maker** | A participant with role `MARKET_MAKER` who quotes two-sided prices |
| **Circuit breaker** | Automatic halt triggered when price moves beyond a configured threshold |
| **Drop copy** | A copy of all fill events published to a dedicated socket for compliance systems |

## See also

- [Configuration](01-configuration.md) — full `engine_config.yaml` reference
- [Running the Engine](03-running-the-engine.md) — detailed startup, monitoring, and troubleshooting
- [Gateway Commands](08-gateway.md) — complete command reference for participants
- [Order Types](04-order-types.md) — LIMIT, MARKET, STOP, ICEBERG, TRAILING_STOP, OCO, COMBO
- [Market Making](14-market-maker.md) — QUOTE command, obligations, and MMP
- [AI Traders](15-ai-traders.md) — autonomous order flow with `pm-ai-trader` and `pm-ai-swarm`

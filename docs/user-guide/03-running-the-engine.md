# Running the Exchange

!!! note "Learning objectives"
    After reading this page you will understand:

    - What a minimum-viable configuration looks like and how to verify it
    - Which processes must be started and in which order
    - The purpose of every `pm-` process and its command-line flags
    - How `tools/launch_all.sh` works and when to write your own launcher
    - How to confirm the system is running correctly after startup
    - How to diagnose common startup failures
    - How to monitor a live session using the operator console and the display processes

    **Prerequisites**: [Configuration](01-configuration.md) — you should have a
    working `engine_config.yaml` before following the steps on this page.
    [Commands](02-commands.md) — for the operator console used in the
    monitoring section.

---

## 1. Minimum-viable configuration

Before starting anything, verify your configuration covers the mandatory
fields.  A completely minimal `engine_config.yaml` looks like this:

```yaml
gateways:
  fix:
    - id: TRADER01
      description: First trader
    - id: MM01
      description: Market maker
      role: MARKET_MAKER
    - id: GW_ADMIN
      description: Operator console
      role: ADMIN

symbols:
  AAPL:
    tick_decimals: 2
    last_buy_price: 149.90
    last_sell_price: 150.10
    market_maker_quotes:
      - gateway_id: MM01
        bid_price: 149.90
        ask_price: 150.10
        bid_qty: 500
        ask_qty: 500
        tif: DAY
        quote_id: MM-AAPL-SEED
```

!!! tip "Why a market-maker gateway with seeded quotes?"
    An order book has no liquidity until orders rest in it.  The engine
    solves this via the `market_maker_quotes` block: when `MM01` connects and
    authenticates, the engine automatically injects the configured two-sided
    quote on its behalf — no manual typing required.  This means the book
    is liquid from the very first moment trading opens.

    Without this, a new trader sees an empty book and a crossing order has
    nothing to trade against.  `last_buy_price` / `last_sell_price` seed the
    "last traded price" display before any real trades have occurred.

    After startup, `pm-viewer --symbol AAPL` will immediately show a
    two-sided book: 500 bid at 149.90 and 500 ask at 150.10.

The engine will refuse to start (exit 1) if:

- The file exists but `gateways.fix` is not a list, **or**
- The file exists but `symbols` is not a mapping.

Run this quick sanity check before starting the engine:

```bash
python - <<'EOF'
import yaml, sys, pathlib
cfg = yaml.safe_load(pathlib.Path("engine_config.yaml").read_text())
gws = cfg.get("gateways", {}).get("fix", None)
syms = cfg.get("symbols", None)
ok = isinstance(gws, list) and len(gws) > 0 and isinstance(syms, dict) and len(syms) > 0
print("Config OK" if ok else "Config INVALID")
print(f"  Gateways : {[g['id'] for g in gws] if isinstance(gws, list) else gws}")
print(f"  Symbols  : {list(syms.keys()) if isinstance(syms, dict) else syms}")
EOF
```

Expected output:
```
Config OK
  Gateways : ['TRADER01', 'MM01', 'GW_ADMIN']
  Symbols  : ['AAPL']
```

### Checklist before the first start

| Check | Why it matters |
|---|---|
| At least one entry under `gateways.fix` | No gateways → nobody can connect |
| At least one entry under `symbols` | No symbols → no books, no trading |
| Every gateway that should submit orders has a matching `id` | IDs must match exactly (case-insensitive on connect; stored uppercase) |
| `role: ADMIN` exists for at least one gateway if you want operator control | Required to use `pm-admin` / `pm-admin-cli` |
| `sessions_enabled: true` and a `schedule` block if you want automatic session transitions | Omitting both is fine for manual / always-open operation |
| `tick_decimals` set correctly for each symbol | Controls price precision; wrong value means prices display wrong |
| Each symbol that needs liquidity has a `market_maker_quotes` block referencing a `MARKET_MAKER`-role gateway | Without seeded quotes the book is empty on startup and traders have nothing to trade against |

---

## 2. Starting the exchange

### Startup order

**The engine must start first.**  It binds the ZeroMQ sockets that all other
processes connect to.  If any process connects before the engine is ready,
it either exits with a timeout error or silently drops its first messages.

```
1. pm-engine          ← binds :5555 and :5556
2. pm-scheduler       ← optional; connects after engine is ready
3. pm-gateway         ← one per trader / market maker / admin; connects to engine
4. pm-viewer          ← one per symbol you want to watch; subscribes to engine
5. pm-orders          ← connects to engine
6. pm-audit           ← connects to engine
7. pm-clearing        ← connects to engine
8. pm-stats           ← connects to engine
9. pm-ticker          ← connects to engine and reads from stats.db
10. pm-board          ← connects to engine and reads from stats.db
```

Steps 2–10 can be started in any order relative to each other, but all of
them require the engine to be up first.  The conventional 0.3–1 second
stagger between processes gives sockets time to fully connect.

### Starting each process

Open a terminal per process, or use a multiplexer like `tmux`.

**Step 1 — matching engine (mandatory)**

```bash
# Verbose mode shows every order and trade on stdout — useful when learning
poetry run pm-engine --verbose

# Silent mode for cleaner output in production-like runs
poetry run pm-engine

# Custom config file
poetry run pm-engine --config my_config.yaml
```

Wait for the engine to print its startup banner before starting anything else:

```
EduMatcher engine starting…
  Symbols  : AAPL MSFT TSLA
  Gateways : GW_ADMIN TRADER01 TRADER02 MM01
  Sessions : enabled (scheduler required)
PULL :5555  PUB :5556  DROP-COPY :5557
Ready.
```

**Step 2 — session scheduler (optional but recommended)**

```bash
# Normal mode: reads schedule from engine_config.yaml and sends transitions at
# the configured wall-clock times
poetry run pm-scheduler

# Test mode: fires all transitions immediately, with a short delay between each
# Useful for verifying your config without waiting for real market hours
poetry run pm-scheduler --now
poetry run pm-scheduler --now --delay 5   # 5-second pause between phases
```

**Step 3 — gateways (one per participant)**

```bash
poetry run pm-gateway --id TRADER01
poetry run pm-gateway --id TRADER02
poetry run pm-gateway --id MM01
```

The gateway ID must exactly match a configured entry in `engine_config.yaml`.
Each gateway gets its own terminal — the prompt is where a trader types orders.

**Step 4+ — optional display and observer processes**

```bash
# Order book for one symbol (one pm-viewer per symbol you want to watch)
poetry run pm-viewer --symbol AAPL
poetry run pm-viewer --symbol AAPL --depth 10   # show 10 price levels

# Cross-gateway order status monitor
poetry run pm-orders

# Audit log (all events, every message written to data/audit.log)
poetry run pm-audit                    # quiet — writes file only
poetry run pm-audit --terminal         # also prints to stdout
poetry run pm-audit --log-file /tmp/my_audit.log

# P&L and trade settlement
poetry run pm-clearing

# OHLCV statistics to SQLite (required by pm-ticker and pm-board)
poetry run pm-stats

# Scrolling market data ticker (needs pm-stats running)
poetry run pm-ticker
poetry run pm-ticker --interval 15    # print a new line every 15 seconds

# Full-screen multi-symbol dashboard (needs pm-stats running)
poetry run pm-board

# ADMIN operator console
poetry run pm-admin --id GW_ADMIN

# AI trading bots (optional)
poetry run pm-ai-trader               # single bot
poetry run pm-ai-swarm                # coordinated multi-bot swarm
```

---

## 3. Process reference

| Process | Mandatory? | Ports | Purpose |
|---------|-----------|-------|---------|
| `pm-engine` | **Yes** | PULL :5555, PUB :5556, PUB :5557 | Matching engine — the single writer of the order book. All orders flow in through :5555; all events flow out through :5556. Also publishes per-participant drop-copy fills on :5557. |
| `pm-gateway` | At least one | PUSH :5555, SUB :5556 | Interactive FIX-like order entry terminal. One per trader, market maker, or operator. Handles authentication, order submission, amend, cancel, and displays acks/fills in real time. |
| `pm-scheduler` | No (manual mode) | PUSH :5555 | Drives automatic session-phase transitions (`PRE_OPEN → OPENING_AUCTION → CONTINUOUS → CLOSING_AUCTION → CLOSED`) at the wall-clock times defined in `engine_config.yaml`. Omit this process if you want to advance phases manually with `SESSION\|STATE=...` in `pm-admin`. |
| `pm-viewer` | No | SUB :5556, PUSH :5555 | Live L1/L2 order-book display for one symbol. Uses a push request to fetch the initial snapshot on connect; then updates on every `book.<SYMBOL>` event. |
| `pm-orders` | No | SUB :5556 | Cross-gateway resting-order monitor. Subscribes to all `order.*` events and displays a live table of every active order regardless of which gateway submitted it. |
| `pm-audit` | No | SUB :5556 | Passive event logger. Writes every message topic and payload to `data/audit.log` in JSONL format. Produces the authoritative record of everything that happened in the session. |
| `pm-clearing` | No | SUB :5556 | Trade settlement and P&L engine. Calculates realized/unrealized P&L per gateway using VWAP average cost, and writes `data/clearing_report.csv` on shutdown. |
| `pm-stats` | No | SUB :5556, PUSH :5555 | OHLCV statistics aggregator. Writes open/high/low/close/volume bars to `data/stats.db` (SQLite). Required by `pm-ticker` and `pm-board`. |
| `pm-ticker` | No | Reads `data/stats.db` | Scrolling one-line-per-interval market data ticker. Queries `pm-stats`'s database at a configurable interval and prints a formatted price/volume line. |
| `pm-board` | No | SUB :5556, reads `data/stats.db` | Full-screen multi-symbol dashboard. Combines live order-book data from the PUB socket with OHLCV data from the stats database. |
| `pm-admin` | No (for operator use) | PUSH :5555, SUB :5556 | Interactive ADMIN console with tab completion. Used for halt/resume, kill switch, gateway management, and read-only queries. Requires an `ADMIN`-role gateway configured. |
| `pm-admin-cli` | No | PUSH :5555, SUB :5556 | Single-shot CLI wrapper for the same commands as `pm-admin`. For scripting and automation. |
| `pm-ai-trader` | No | PUSH :5555, SUB :5556 | Single AI trading bot that connects as a gateway and submits orders based on configurable personality profiles. |
| `pm-ai-swarm` | No | PUSH :5555, SUB :5556 | Coordinated multi-agent AI trading swarm. Runs multiple bots simultaneously to generate realistic order flow. |

### ZeroMQ port summary

| Port | Pattern | Direction | Used by |
|------|---------|-----------|---------|
| **5555** | PULL (engine) / PUSH (clients) | Clients → Engine | All order-submitting and command-sending processes |
| **5556** | PUB (engine) / SUB (clients) | Engine → All | All event-receiving processes |
| **5557** | PUB (engine) / SUB (drop-copy subscribers) | Engine → Drop-copy | Per-participant fill feed; not used by core observer processes |

---

## 4. The `tools/launch_all.sh` convenience launcher

`tools/launch_all.sh` is a macOS-only shell script that opens **each process
in its own Terminal window** using `osascript`.  It starts the standard
two-trader configuration with all observer processes in one command:

```bash
# Viewer watches MSFT by default
./tools/launch_all.sh

# Watch a different symbol
./tools/launch_all.sh AAPL

# Open one viewer window per symbol
./tools/launch_all.sh AAPL MSFT TSLA
```

The script starts processes in the correct order and inserts the necessary
sleep delays (1 second after the engine, 0.3 seconds between the rest):

```bash
pm-engine --verbose          # window 1
pm-scheduler                 # window 2  (after 1 s)
pm-gateway --id TRADER01     # window 3
pm-gateway --id TRADER02     # window 4
pm-viewer  --symbol <SYM>    # one window per SYM argument
pm-orders                    # next window
pm-audit   --terminal        # next window
pm-clearing                  # next window
pm-stats                     # next window
pm-ticker  --interval 30     # next window
pm-board                     # last window
```

!!! warning "macOS only"
    `launch_all.sh` uses `osascript` to open Terminal windows and will not
    work on Linux or Windows. On other platforms use `tmux`, `screen`, or a
    process supervisor (see the Troubleshooting section).

### Customising the launcher for your own setup

The bundled script covers the two-trader demo configuration. You will need
to extend it when adding:

- **More traders** — add `_term "poetry run pm-gateway --id TRADER03"` lines
- **Market makers** — add `_term "poetry run pm-gateway --id MM01"` (the role is
  in the config, not the command line)
- **An ADMIN console** — add `_term "poetry run pm-admin --id GW_ADMIN"` after the
  engine is up
- **AI bots** — add `_term "poetry run pm-ai-trader"` or
  `_term "poetry run pm-ai-swarm"` near the end
- **Multiple viewer symbols** — already supported via command-line arguments
  (`./launch_all.sh AAPL MSFT TSLA`)

A starting template for a more complete four-gateway run:

```bash
#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

_term() {
    local cmd="$1"
    osascript \
        -e "tell application \"Terminal\"" \
        -e "  activate" \
        -e "  do script \"cd '$DIR' && $cmd\"" \
        -e "end tell"
}

_term "poetry run pm-engine --verbose"
sleep 1

_term "poetry run pm-scheduler"
sleep 0.3

# Traders
_term "poetry run pm-gateway --id TRADER01"
_term "poetry run pm-gateway --id TRADER02"
sleep 0.3

# Market maker
_term "poetry run pm-gateway --id MM01"
sleep 0.3

# ADMIN operator console
_term "poetry run pm-admin --id GW_ADMIN"
sleep 0.3

# Viewers — one per symbol
for SYM in AAPL MSFT TSLA; do
    _term "poetry run pm-viewer --symbol $SYM"
    sleep 0.2
done

# Observer processes
_term "poetry run pm-orders"
_term "poetry run pm-audit --terminal"
_term "poetry run pm-clearing"
_term "poetry run pm-stats"
_term "poetry run pm-ticker --interval 15"
_term "poetry run pm-board"

echo "Launched."
```

On Linux, replace `osascript` with `gnome-terminal --`, `xterm -e`, or a `tmux`
new-window command depending on your terminal emulator.

---

## 5. Verifying the system is running correctly

### Immediate checks after startup

**a) The engine prints `Ready.`**

The engine startup banner lists the loaded symbols, configured gateways, and
bound socket addresses.  If it prints nothing or exits immediately, see the
troubleshooting section.

**b) Gateways authenticate successfully**

Each `pm-gateway` terminal shows:

```
Gateway TRADER01 connected and authenticated.
[TRADER01]>
```

If the gateway times out instead, the engine is not reachable.

**c) Use the ADMIN console to confirm live state**

```bash
poetry run pm-admin --id GW_ADMIN
```

Then type these commands to validate the running system:

```
[GW_ADMIN|ADMIN]> SYMBOLS
# Should list every symbol from engine_config.yaml

[GW_ADMIN|ADMIN]> GATEWAYS
# Should list all configured gateways; check "Connected" column

[GW_ADMIN|ADMIN]> SESSION_STATUS
# Should print the current session state (PRE_OPEN, CONTINUOUS, etc.)

[GW_ADMIN|ADMIN]> SCHEDULE
# Should print the timing configuration if sessions_enabled is true
```

**d) Verify ZeroMQ ports are bound**

```bash
lsof -i :5555 -i :5556 -i :5557
```

Expected output shows three lines for the `pm-engine` process:

```
COMMAND   PID  USER   FD   TYPE  NODE NAME
Python  12345   ljp   11u  IPv4       *:5555 (LISTEN)
Python  12345   ljp   12u  IPv4       *:5556 (LISTEN)
Python  12345   ljp   13u  IPv4       *:5557 (LISTEN)
```

**e) Submit a test order end-to-end**

From a `pm-gateway` terminal:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00
```

Expected response: `ACK  order_id=...  status=NEW`

If the order is acknowledged, the full path (gateway → engine PULL → engine
matching logic → engine PUB → gateway SUB) is working.

**f) Check that pm-viewer shows the resting order**

After submitting the test order above, `pm-viewer --symbol AAPL` should
update to show a 100-share bid at 150.00.

**g) Verify audit logging**

```bash
tail -5 data/audit.log
```

Every event in the system should appear here within a second of occurring.  If
the file does not exist, `pm-audit` either was not started or failed to create
the `data/` directory.

---

## 6. Troubleshooting startup problems

### Engine exits immediately

| Symptom | Likely cause | Fix |
|---|---|---|
| `Config error: symbols must be a mapping` | `symbols:` is a list or missing | Correct `engine_config.yaml` |
| `Config error: gateways.fix must be a list` | `gateways.fix:` is not a list | Correct `engine_config.yaml` |
| `Address already in use — :5555` | Another engine (or other process) is already bound | `lsof -i :5555` to find and kill the conflicting process |
| Silent exit with code 1 | Syntax error in the YAML file | `python -c "import yaml; yaml.safe_load(open('engine_config.yaml'))"` |

### Gateway authentication timeout

```
Gateway authentication timed out.  Is the engine running at tcp://127.0.0.1:5555?
```

Causes (in order of likelihood):

1. The engine is not running — start it first.
2. The engine is still starting up — wait for `Ready.` before launching gateways.
3. The gateway ID is not in `engine_config.yaml` — the engine silently ignores
   the connect request.  Add the ID to the config and restart the engine.
4. Port 5555 is blocked by a firewall rule or VPN.

### Viewer shows an empty book

An empty `pm-viewer` is expected if no orders have been submitted yet.  The
viewer subscribes to `book.<SYMBOL>` events, which are only published when the
book changes.  Submit a resting order or enable `market_maker_quotes` in your
config.

If the viewer was running before the engine started, it may have missed the
initial snapshot.  Restart the viewer after the engine is up.

### `pm-ticker` or `pm-board` show nothing

Both processes read from `data/stats.db`.  This file is created by `pm-stats`.
Ensure `pm-stats` is running and has received at least one trade event.
The first update only appears after the first `trade.executed` message.

### `pm-scheduler` exits immediately with `Fatal: config missing`

The scheduler requires a `schedule:` block in `engine_config.yaml`.  If the
block is missing, use `--now` mode for testing or add a schedule to your config.

### `pm-admin` refuses connection with `Auth refused: role is not ADMIN`

The gateway ID you passed to `--id` exists in the config but does not have
`role: ADMIN`.  Update the config:

```yaml
gateways:
  fix:
    - id: GW_ADMIN
      role: ADMIN
      description: Operator console
```

Restart the engine after editing the config.

### General diagnostics

```bash
# Check all pm- processes are running
ps aux | grep pm-

# Check ZMQ ports
lsof -i :5555 -i :5556 -i :5557

# Check the most recent audit events
tail -20 data/audit.log | python -c "import sys,json; [print(json.loads(l)['topic']) for l in sys.stdin]"

# Check the engine config parsed cleanly
python -c "
from edumatcher.engine.config_loader import load_engine_config
cfg = load_engine_config('engine_config.yaml')
print('Symbols:', sorted(cfg.symbols.keys()) if cfg else 'None (unrestricted)')
print('Gateways:', sorted(cfg.fix_gateways.keys()) if cfg else 'None (unrestricted)')
"
```

---

## 7. Monitoring a running exchange

### Continuous visual monitoring

| Tool | Best for |
|---|---|
| `pm-viewer --symbol <SYM>` | Watching one book in real time — see bids, asks, last trade |
| `pm-board` | High-level overview of all symbols simultaneously |
| `pm-ticker` | Scrolling tape of OHLCV data — good for a side monitor |
| `pm-orders` | Watching resting orders across all gateways |
| `pm-audit --terminal` | Raw event stream — everything that touches the engine |
| `pm-clearing` | Live P&L per gateway |

### Operator query commands

There are two interfaces to the same set of commands:

- **`pm-admin`** — interactive REPL with tab completion; stay connected and run
  multiple commands in one session.
- **`pm-admin-cli`** — single-shot CLI; runs one command, prints the result, and
  exits with code 0 (success) or 1 (failure).  Use this in scripts and cron jobs.

Both require an `ADMIN`-role gateway ID (`--id GW_ADMIN`) and the engine to be
running.

#### Interactive console (`pm-admin`)

```bash
poetry run pm-admin --id GW_ADMIN
```

```
[GW_ADMIN|ADMIN]> SESSION_STATUS
Session state : CONTINUOUS
Sessions      : enabled

[GW_ADMIN|ADMIN]> SCHEDULE
Sessions enabled : true
PRE_OPEN          : 09:00
OPENING_AUCTION   : 09:25
CONTINUOUS        : 09:30
CLOSING_AUCTION   : 16:00
CLOSING_AUCTION_END: 16:05

[GW_ADMIN|ADMIN]> GATEWAYS
ID          Role          Connected
----------  ------------  ----------
TRADER01    TRADER        yes
MM01        MARKET_MAKER  yes
GW_ADMIN    ADMIN         yes

[GW_ADMIN|ADMIN]> BOOK|SYM=AAPL
AAPL   bid 149.90 x 500   ask 150.10 x 500   last 149.95

[GW_ADMIN|ADMIN]> ORDERS|GW=TRADER01
order_id  sym   side  type   qty  price   status
--------  ----  ----  -----  ---  ------  ------
...

[GW_ADMIN|ADMIN]> VOLUME
Symbol   Qty    Value        Trades
------   -----  -----------  ------
AAPL     1 200  179 940.00        8
TOTAL    1 200  179 940.00        8

[GW_ADMIN|ADMIN]> SYMBOLS
AAPL  MSFT  TSLA
```

#### Single-shot CLI (`pm-admin-cli`)

Each interactive command maps to a subcommand.  Pipe or capture the output
like any shell command.

```bash
# Read-only queries
poetry run pm-admin-cli --id GW_ADMIN session-status
poetry run pm-admin-cli --id GW_ADMIN schedule
poetry run pm-admin-cli --id GW_ADMIN gateways
poetry run pm-admin-cli --id GW_ADMIN volume
poetry run pm-admin-cli --id GW_ADMIN symbols
poetry run pm-admin-cli --id GW_ADMIN book   --sym AAPL
poetry run pm-admin-cli --id GW_ADMIN orders --gw TRADER01

# State-changing commands
poetry run pm-admin-cli --id GW_ADMIN session --state CONTINUOUS
poetry run pm-admin-cli --id GW_ADMIN halt
poetry run pm-admin-cli --id GW_ADMIN resume
poetry run pm-admin-cli --id GW_ADMIN kill   --gw TRADER01
poetry run pm-admin-cli --id GW_ADMIN kill   --gw TRADER01 --sym AAPL
poetry run pm-admin-cli --id GW_ADMIN kick   --gw TRADER01 --reason "Compliance hold"
poetry run pm-admin-cli --id GW_ADMIN qcancel --gw MM01 --sym AAPL
```

Use `--timeout MS` (default 3000 ms) and `--push` / `--sub` to override
defaults when the engine is on a remote host:

```bash
poetry run pm-admin-cli --id GW_ADMIN \
    --push tcp://192.168.1.10:5555 \
    --sub  tcp://192.168.1.10:5556 \
    --timeout 5000 \
    session-status
```

The exit code makes it easy to compose with `&&` or `||` in shell scripts:

```bash
poetry run pm-admin-cli --id GW_ADMIN session-status \
    | grep -q CONTINUOUS \
    && echo "Market is open" \
    || echo "Market is closed"
```

### Health check script

A minimal shell health check suitable for a cron job or monitoring system:

```bash
#!/bin/bash
# health_check.sh — exit 0 if exchange appears healthy, 1 otherwise

# 1. Engine ports bound
lsof -i :5555 >/dev/null 2>&1 || { echo "FAIL: engine port 5555 not bound"; exit 1; }
lsof -i :5556 >/dev/null 2>&1 || { echo "FAIL: engine port 5556 not bound"; exit 1; }

# 2. Engine process running
pgrep -f "pm-engine" >/dev/null || { echo "FAIL: pm-engine not found"; exit 1; }

# 3. ADMIN console can query session state
SESSION=$(poetry run pm-admin-cli --id GW_ADMIN --timeout 2000 session-status 2>&1)
echo "$SESSION" | grep -q "Session state" || { echo "FAIL: could not query session state"; exit 1; }

echo "OK: $SESSION"
exit 0
```

### Log-based monitoring

`data/audit.log` is JSONL — one JSON object per line — making it easy to pipe
into `jq` for live filtering:

```bash
# Stream every trade as it happens
tail -f data/audit.log | grep '"topic":"trade.executed"' | jq '.payload | {sym: .symbol, price, qty: .quantity}'

# Count fills per gateway in the last 1000 events
tail -1000 data/audit.log | jq -r 'select(.topic | startswith("order.fill")) | .payload.gateway_id' | sort | uniq -c | sort -rn

# Find the most recent session-state change
grep '"session.state"' data/audit.log | tail -1 | jq '.payload'
```

### Watching statistics

```bash
# Query the SQLite database for live daily stats
sqlite3 data/stats.db "SELECT symbol, open, high, low, close, volume FROM daily_stats ORDER BY symbol;"
```

---

## 8. Frequently asked questions

### Do I have to start all processes every time?

No. The only mandatory process is `pm-engine`.  Everything else is optional:

- You can trade without any viewer — you just won't see the live book.
- You can run without `pm-audit` — you just won't have an event log.
- You can run without `pm-scheduler` — session phases stay where you set them
  manually (or in `PRE_OPEN` on a fresh start without `sessions_enabled: true`).

For quick experiments, starting just the engine and one or two gateways is
enough.

### Does the exchange work without `engine_config.yaml`?

Yes — the engine starts in **unrestricted mode** with no symbol allowlist and no
gateway allowlist.  Any gateway ID can connect, and orders for any symbol are
accepted.  This is useful for quick tests but not for structured sessions.

In unrestricted mode a new order book is created automatically the first time
an order for that symbol arrives.  The engine's internal `_book(symbol)` helper
does this lazily:

```python
# engine/main.py — called on every incoming order
def _book(self, symbol: str) -> OrderBook:
    if symbol not in self.books:
        self.books[symbol] = OrderBook(symbol)   # created on first use
    return self.books[symbol]
```

When a `symbols:` block is present in `engine_config.yaml`, the engine builds
an allowlist at startup.  Every incoming order is validated against that list
*before* `_book()` is called, and any order for an unlisted symbol is rejected
immediately with `"Symbol not configured: <SYM>"`.  The book is therefore only
ever created for symbols that are explicitly configured.

### Can I restart a single process without restarting everything?

Yes.  Because every process connects to the engine's sockets (rather than the
engine connecting to them), you can stop and restart any non-engine process at
any time.  The engine continues running; the restarted process reconnects on
startup.

The exception is `pm-engine` itself.  Restarting the engine disconnects every
connected gateway and causes all non-persistent (DAY TIF) resting orders to
expire.  GTC orders are saved on clean shutdown and reloaded on the next start.

### What happens to orders if a gateway crashes?

The engine applies the gateway's configured `disconnect_behaviour`:

| Value | Effect |
|---|---|
| `CANCEL_QUOTES_ONLY` (default) | Active quote legs are cancelled; resting limit orders remain |
| `CANCEL_ALL` | All resting orders and quotes are cancelled |
| `LEAVE_ALL` | Nothing is cancelled — orders rest until explicitly removed |

You can override this at runtime with `KICK|GW=<gw>` from the ADMIN console.

### What is the correct order if I want to use the scheduler?

```
1. pm-engine    — binds sockets, loads config
2. pm-scheduler — connects to engine; waits for the first scheduled time
3. pm-gateway   — one per participant
4. (optional observers)
```

The scheduler must connect before the first scheduled transition time arrives,
otherwise it misses that transition and waits for the next one.

### How do I run sessions without waiting for real clock times?

Use `--now` mode on the scheduler:

```bash
poetry run pm-scheduler --now --delay 10
```

This fires all transitions (PRE_OPEN → OPENING_AUCTION → CONTINUOUS →
CLOSING_AUCTION → CLOSED) with a 10-second pause between each, ignoring
the wall-clock schedule entirely.  Ideal for classroom demos and testing.

### How do I advance the session phase manually?

Use the ADMIN console (requires an `ADMIN`-role gateway):

```
poetry run pm-admin --id GW_ADMIN
[GW_ADMIN|ADMIN]> SESSION|STATE=CONTINUOUS
```

Or with the CLI tool (useful in scripts):

```bash
poetry run pm-admin-cli --id GW_ADMIN session --state CONTINUOUS
```

### How do I cleanly shut down the exchange?

Press `Ctrl-C` on the `pm-engine` terminal.  The engine will:

1. Serialize all resting GTC orders to `data/gtc_orders.json`
2. Publish `order.expired` for all DAY orders
3. Publish `system.eod` with final book snapshots
4. Close sockets

All other processes detect the socket closure and exit cleanly.  For scripted
shutdown, send `SIGINT` to the engine PID:

```bash
pkill -INT -f pm-engine
```

### `launch_all.sh` opens too many terminal windows. Is there a tmux alternative?

Yes. Replace the `_term` function with a `tmux new-window` call:

```bash
_term() {
    tmux new-window -d -n "$(echo "$1" | awk '{print $3}')" "cd '$DIR' && $1"
}
```

This opens each process in a new `tmux` window instead of a new Terminal
application window.  Run `tmux new-session -d -s edumatcher` first to create
the session.

### Can I run multiple exchanges on the same machine?

Yes, but you must change the ports.  All port constants are defined in
`src/edumatcher/config.py`.  You cannot override them on the command line for
most processes (only `pm-admin` and `pm-admin-cli` expose `--push` / `--sub`
flags).  For a second instance, edit `config.py` or make a copy of the package
with different defaults.

# FAQ & Common Mistakes

Common questions and gotchas when learning EduMatcher.

---

## Architecture & Setup

### The engine started but gateways can't connect. What's wrong?

Check that:
1. The engine is running *before* the gateways try to connect.
2. ZMQ ports 5555 and 5556 are not blocked by a firewall or in use by another
    process: `lsof -i :5555 -i :5556`
3. The gateway ID exists in `engine_config.yaml`.

If the engine is down or unreachable, `pm-alf-console` exits after about three
seconds with `Gateway authentication timed out`.

---

### The book already has liquidity before I submit any orders. Why?

If your `engine_config.yaml` has a `market_maker_quotes` block for the symbol,
the engine injects a two-sided seed quote on behalf of the configured market-maker
gateway at startup. This is intentional — it gives the book immediate liquidity
so participants always have something to trade against.

A side effect is that your **first aggressive order may fill immediately** against
the seed quote, before a second participant has typed anything.

To run with a deliberately empty book (e.g. for a demo of price discovery from
scratch), either:
- Remove or comment out `market_maker_quotes` in the config, or
- Start the engine without a config file (`sessions_enabled: false` minimum).

---

### Why did the seed MM quote disappear after the second day?

By default, `market_maker_quotes` entries have `seed_once: true`. This means the
quote is only injected on the **first** startup for a symbol (detected by the
absence of a `book_stats.json` entry). From the second day onward the real market
maker is expected to submit its own quotes.

To inject the seed on every startup (e.g. for a repeatable classroom demo):

```yaml
market_maker_quotes:
  - gateway_id: MM01
    bid_price: 149.00
    ask_price: 151.00
    bid_qty: 500
    ask_qty: 500
    tif: DAY
    seed_once: false    # inject on every startup
```

To force a day-1 re-injection without changing the config:

```bash
rm data/book_stats.json    # or $EDUMATCHER_DATA_DIR/book_stats.json
```

---

### Why is the engine not matching orders? It starts in CLOSED state

With `sessions_enabled: true` (the default), the engine starts in `CLOSED` state
and waits for `pm-scheduler` to drive it through the session phases before it
accepts orders.

Two ways to get to a matching state quickly:

1. **Start `pm-scheduler`** alongside the engine — it drives the transition
   from CLOSED → PRE_OPEN → OPENING_AUCTION → CONTINUOUS automatically at
   the configured wall-clock times, or immediately with `pm-scheduler --now`.
2. **Disable sessions** for testing or demos:
   ```yaml
   # engine_config.yaml
   sessions_enabled: false
   ```
   With `sessions_enabled: false` the engine enters CONTINUOUS state immediately
   on startup and `pm-scheduler` has no effect.

---

### Why is my viewer empty even though it started correctly?

An empty viewer usually means the symbol has no resting orders yet. `pm-viewer`
subscribes to `book.<SYMBOL>` and then requests an initial snapshot, but if the
book is empty the snapshot is also empty.

**Fix:** Submit a resting order, enable market-maker quote seeds for that
symbol, or verify that you are watching a configured symbol.

---

### Why did `pm-scheduler --config ...` exit immediately?

An explicit `--config` path is treated strictly. If the file does not exist,
the scheduler exits with a fatal error instead of silently falling back.

If you omit `--config`, the scheduler uses `engine_config.yaml` when present and
otherwise falls back to its built-in default times.

---

### Why doesn't `./launch_all.sh` work on my machine?

`launch_all.sh` is macOS-specific. It uses `osascript` to open Terminal windows,
so it does not behave like a generic Linux or Windows launcher.

Use the manual process commands from the home page if you are not on macOS.

---

### Why do I need five terminal windows?

Each process is an independent OS process communicating over ZeroMQ. They
cannot run inside a single terminal because each blocks on its own event loop.
For convenience, use the provided `./tools/launch_all.sh` script which starts
the standard setup in separate Terminal windows on macOS. In a remote server
setting, `tmux` or `screen` are the standard alternatives.

---

### How do I see what messages are flowing between processes?

Run `pm-audit --terminal` in a separate window. It subscribes to **all**
ZeroMQ messages and prints them to stdout, giving a full real-time trace of
every event in the system.

---

### Why does the engine use integer ticks instead of float prices?

Float arithmetic can introduce tiny representation errors in comparisons and
aggregation. Using integer ticks makes price-time matching and level math exact.

---

### How do I reset all persisted state to start fresh?

Delete the contents of the data directory:

```bash
# Installed mode (default data dir)
rm -f ~/.local/share/edumatcher/*.json \
       ~/.local/share/edumatcher/*.csv  \
       ~/.local/share/edumatcher/*.db   \
       ~/.local/share/edumatcher/audit.log

# Source checkout
rm -f src/data/*.json src/data/*.csv src/data/*.db src/data/audit.log

# Or with a custom directory
rm -f "$EDUMATCHER_DATA_DIR"/*.json ...
```

This resets GTC orders, book statistics, clearing history, and audit logs.
The engine will re-seed MM quotes as if it were day 1 (because `book_stats.json`
no longer exists).

----

## Orders & Execution

### Why was my IOC order rejected?

IOC (Immediate-Or-Cancel) orders **cannot rest on the book**, so they are
rejected during any non-matching phase (PRE_OPEN, OPENING_AUCTION,
CLOSING_AUCTION, CLOSED). IOC is only valid during `CONTINUOUS` trading.

```
[GW01] order.ack: accepted=false reason="IOC rejected outside CONTINUOUS phase"
```

**Fix:** The gateway has no `SESSION` command. Watch the scheduler output,
run `pm-audit --terminal`, or use `pm-viewer` / `pm-orders` to see
`session.state` events, then wait for CONTINUOUS or switch to a `LIMIT` order
with `TIF=DAY` if you're willing to have the order rest.

---

### Why didn't my STOP order trigger?

STOP orders only trigger from **last trade price** events. If no trades have
occurred since you submitted the STOP, the trigger is never evaluated —
regardless of the current bid/ask quotes.

```
# This SELL STOP at 148 won't fire if no trades have happened yet
NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP|QTY=100|STOP=148.00
```

**Fix:** Check whether any trades have printed in the engine output (`--verbose`
mode) or in the audit log. A stop only becomes relevant once the market is
actively trading through its trigger level.

Also check the trigger direction. A **SELL STOP** triggers when `last_trade_price <= stop_price`.
If the market is above your stop, it won't fire until price falls *to* or *through* it.

See [Stop Trigger Logic](user-guide/060-order-types.md#stop-trigger-logic) for full details.

---

### Why did my STOP_LIMIT order trigger but not fill?

This is expected behaviour. When a STOP_LIMIT triggers, it converts to a
**LIMIT order at your specified `PRICE=`**. If the market has moved past that
limit price before the converted order can match, it sits on the book unfilled.

**Example:** SELL STOP_LIMIT with `STOP=148.00` and `PRICE=147.50`.
If the market gaps down to $146.00 before the converted limit can fill,
your order rests at $147.50 — but nobody is bidding that high. You are
protected from filling at $146.00, but you may not fill at all.

**Tradeoff:** STOP gives fill certainty. STOP_LIMIT gives price certainty.
Neither gives both.

---

### My FOK order was rejected even though there was liquidity. Why?

FOK checks whether the **entire quantity** can be filled at the limit price
*before* executing. It does not execute at all unless the full size is
available.

```
# Book has only 80 shares at 150.00, but you want 100
NEW|SYM=AAPL|SIDE=BUY|TYPE=FOK|QTY=100|PRICE=150.00
# → REJECTED because 80 < 100
```

**Fix:** Reduce `QTY` to match available liquidity, or use a `LIMIT` order
and accept a partial fill.

---

### Why is my LIMIT order filling at a different price than I specified?

Your limit price is the **worst** price you'll accept — not necessarily the
price you'll get. If better prices are available, you fill at those better
prices.

**Example:** You submit `BUY LIMIT QTY=100 PRICE=151.00` but the book has asks
at 149.90 and 150.20. You fill at 149.90 and 150.20 (both better than your
limit of 151.00), not at 151.00.

This is called **price improvement** — you get a better deal than the worst
price you were willing to accept.

---

### I submitted a MARKET order but it only partially filled. Where did the rest go?

A MARKET order sweeps the book until it runs out of liquidity. If the book
does not have enough resting orders to fill the entire quantity, the
unfilled remainder is **discarded** (not rested). You will receive one or
more partial fill events, then a cancellation for the remaining quantity.

**Fix:** If you need guaranteed full execution at whatever price, use FOK
and ensure liquidity is available. If you're comfortable with partial fills,
MARKET is correct — just understand the remainder is discarded, not queued.

---

## P&L & Position

### Why is my unrealized P&L different from my realized P&L?

They measure different things:

- **Unrealized P&L**: paper gain/loss on shares you still hold, calculated as
  `(current_price - avg_cost) × position`. This changes every time a trade
  prints and updates the last trade price.
- **Realized P&L**: profit/loss locked in when you *closed* part of your
  position (sold shares you were long, or bought back a short). This never
  changes after the trade.

Until you close your position, your gains are "on paper" — the market can
take them back. Once realized, they are yours regardless of subsequent
price moves.

---

### Why does my average cost change when I buy more shares?

When you add to an existing position, your **VWAP average cost** updates to
reflect the new shares at the new price. This is standard practice for
tracking the true cost basis of a position built over multiple trades.

**Example:**
```
Buy 100 shares @ 150.00  →  avg_cost = 150.00
Buy 100 shares @ 152.00  →  avg_cost = (150 × 100 + 152 × 100) / 200 = 151.00
```

See [P&L & Clearing — VWAP Average Cost](user-guide/130-pnl-clearing.md#vwap-average-cost).

---

### Why do I have a negative position?

A negative position means you are **short** — you have sold shares you did not
own. This can happen if you submit a SELL order without first having bought any
shares. In a real brokerage this requires a margin account and stock borrowing;
EduMatcher does not enforce these constraints, so short positions are allowed
freely.

---

## Sessions & Orders

### What happens to my open orders when the market closes?

It depends on their time-in-force:

| TIF | At market close |
|-----|----------------|
| `DAY` | Expired and removed. You receive `order.expired` events. |
| `GTC` | Saved to `data/gtc_orders.json` and reloaded on next engine start. |
| `ATO` | Expired when OPENING_AUCTION phase ends. |
| `ATC` | Expired when CLOSING_AUCTION phase ends. |

---

### My GTC orders didn't reload after restart. Why?

GTC orders are written to `data/gtc_orders.json` **on engine shutdown** (when
you press Ctrl-C or the scheduler sends a CLOSED transition). If the engine was
killed forcefully (`kill -9` or a crash), the file was not written.

**Fix:** Check whether `data/gtc_orders.json` exists and has recent content.
If the engine was killed mid-session, the file may be stale or missing.

---

### Why is my order rejected with "Gateway not authenticated"?

Your gateway ID is not in the engine's allowlist. Gateway IDs must be
pre-configured in `engine_config.yaml` under `gateways.alf`:

```yaml
gateways:
    alf:
        - id: GW01
          description: My first trader
```

Restart the engine after editing the config.

---

## Self-Match Prevention

### What is SMP and why did my order get cancelled?

**Self Match Prevention (SMP)** stops you from accidentally trading against
your own resting orders. If you submit a buy that would match a sell you
already have on the same book, SMP kicks in.

```
# Submit a buy that would cross with your own resting sell
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=151.00|SMP=CANCEL_AGGRESSOR
```

With `SMP=CANCEL_AGGRESSOR`, the incoming buy is cancelled instead of
filling against your own sell. Options:

| Value | Behaviour |
|-------|-----------|
| `NONE` | No SMP — you can trade against yourself |
| `CANCEL_AGGRESSOR` | The incoming order is cancelled |
| `CANCEL_RESTING` | The resting order is cancelled |
| `CANCEL_BOTH` | Both orders are cancelled |

---

## Installation & Setup

### Do I need Poetry or pipx?

It depends on your role:

| Role | Tool | Install command |
|---|---|---|
| **Student / instructor** (just want to run the exchange) | pipx | `pipx install edumatcher` |
| **Developer** (modifying the engine, running tests) | Poetry | `poetry install --with dev` |

End users should not need a source checkout at all. After `pipx install edumatcher`
all `pm-*` commands are on your PATH and ready to use.

---

### I installed with pipx but `pm-engine` is not found. What do I do?

pipx installs scripts to `~/.local/bin`, which may not be on your PATH yet.

```bash
pipx ensurepath        # adds ~/.local/bin to your shell profile
exec $SHELL            # reload your current shell
which pm-engine        # should now print a path
```

If you just installed pipx itself for the first time, open a **new terminal
window** after running `pipx ensurepath` — the PATH change only takes effect
in new shells.

---

### What does `pm-setup` do and do I have to run it?

`pm-setup` is a one-time bootstrap command for **installed** (pipx) users:

1. Creates the data directory (`~/.local/share/edumatcher` by default).
2. Copies the bundled sample `engine_config.yaml` into your current working
   directory.
3. Prints a shell snippet to add to `~/.zshrc` or `~/.bashrc`.

If you skip it, the engine still starts — but it looks for `engine_config.yaml`
in `./` (your CWD) and writes data files to `~/.local/share/edumatcher`,
creating that directory automatically. The main reason to run `pm-setup` is to
get the sample config so you have a starting point to edit.

Developer mode (Poetry + source checkout) does not need `pm-setup` at all.

---

### The engine says it cannot find `engine_config.yaml`. Where should the file be?

The search path depends on how you are running EduMatcher:

| Mode | Default config location |
|---|---|
| **pipx installed** | `engine_config.yaml` in the **current working directory** |
| **Source checkout** | `engine_config.yaml` in the **repository root** |
| **Either** | `EDUMATCHER_CONFIG` environment variable (highest priority) |

The most common mistake is running `pm-engine` from a directory that does not
contain `engine_config.yaml`. Either `cd` to the directory that has the file,
or point to it explicitly:

```bash
pm-engine --config ~/my-session/engine_config.yaml
# or:
export EDUMATCHER_CONFIG=~/my-session/engine_config.yaml
pm-engine
```

---

### Where are my data files stored?

Data files (`gtc_orders.json`, `stats.db`, `audit.log`, etc.) go to:

| Mode | Data directory |
|---|---|
| **pipx installed** | `~/.local/share/edumatcher` |
| **Source checkout** | `<repo>/src/data/` |
| **Either** | `EDUMATCHER_DATA_DIR` environment variable (highest priority) |

To isolate two sessions from each other, run each in its own directory and set
`EDUMATCHER_DATA_DIR` to a different path:

```bash
export EDUMATCHER_DATA_DIR=~/sessions/morning
pm-engine --config ~/sessions/morning/engine_config.yaml
```

---

### How do I upgrade EduMatcher to a newer version?

```bash
pipx upgrade edumatcher            # upgrade from PyPI
# or, to install a locally built wheel:
poetry build
pipx install dist/edumatcher-*.whl --force
pm-setup --force                   # refresh the sample config if needed
```

Your existing `engine_config.yaml` and data files are not touched by the upgrade.

---

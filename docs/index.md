# EduMatcher — Educational Trading System

EduMatcher is a multi-process Python trading simulator designed to teach the fundamentals of
**order matching**, **market microstructure**, and **exchange architecture** through a hands-on,
fully runnable system.

---

## What is this system modelling?

When you buy a share of stock through a broker, your order travels to an
exchange — a regulated marketplace where buy and sell orders are matched. At
the heart of every exchange is a **matching engine**: software that maintains
an **order book** for each traded instrument, pairs buy orders with sell
orders, and produces **trades** when prices agree.

EduMatcher reproduces this entire stack as independent processes
communicating over a message bus, just as a real exchange does. The
difference is that here, everything is visible and inspectable:

```
  Your terminal          Matching engine           Other participants
  (pm-gateway)  ──────►  (pm-engine)  ◄──────────  (other pm-gateways)
                              │
                    broadcasts trades & fills
                              │
            ┌─────────────────┼────────────────────┐
            ▼                 ▼                    ▼
       pm-viewer          pm-clearing          pm-audit
    (live order book)  (P&L accounting)   (full event log)
```

A **trade** happens when two orders cross: a buyer willing to pay at least
what a seller is willing to accept. The matching engine applies
**price-time priority** — the best-priced order fills first; among orders at
the same price, the earliest one fills first.

---

## What you'll learn

| Topic | Where |
|-------|-------|
| Order books, bids, asks, spread, depth | [The Order Book](concepts/01-concepts-order-book.md) |
| How to execute your first trade | [Your First Trade](concepts/04-concepts-first-trade.md) |
| Session phases, opening & closing auctions | [A Full Trading Day](concepts/05-concepts-trading-day.md) |
| All ten order types with worked examples | [Order Types](user-guide/04-order-types.md) |
| Multi-leg combo and OCO strategies | [Combo Orders](user-guide/05-combos.md) |
| Realized vs. unrealized P&L, VWAP cost basis | [P&L & Clearing](user-guide/07-pnl-clearing.md) |
| ZeroMQ pub/sub architecture | [Architecture](architecture/01-architecture.md) |
| Definitions of all financial terms | [Glossary](glossary.md) |

---

## Suggested reading path

If you are new to trading systems, follow this path:

1. **[The Order Book](concepts/01-concepts-order-book.md)** — understand bids, asks, spread, and price-time priority
2. **[Your First Trade](concepts/04-concepts-first-trade.md)** — run the system and execute a trade step-by-step
3. **[A Full Trading Day](concepts/05-concepts-trading-day.md)** — learn session phases and auctions
4. **[Order Types](user-guide/04-order-types.md)** — explore all ten order types
5. **[P&L & Clearing](user-guide/07-pnl-clearing.md)** — understand how profit and loss are tracked

If you are already familiar with trading concepts, go straight to the
[Quick Start](#quick-start) below or browse the [reference section](#reference-docs).

---

## Quick Start

### Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/) 1.7+

### Install

```bash
cd EduMatcher
poetry config virtualenvs.in-project true
poetry install --with dev,docs
```

### Start the system (minimum viable session)

Open **five** terminal windows and run one process per window, in this order:

```bash
# Terminal 1 — Matching engine
poetry run pm-engine --verbose

# Terminal 2 — Audit log (printed to terminal)
poetry run pm-audit --terminal

# Terminal 3 — Clearing / P&L
poetry run pm-clearing

# Terminal 4 — Order book viewer for AAPL
poetry run pm-viewer --symbol AAPL

# Terminal 5 — Your gateway (user GW01)
poetry run pm-gateway --id GW01
```

`GW01` must be configured under `gateways.alf` in `engine_config.yaml` or the
gateway will fail authentication and exit.

To add more users, watch more symbols, or enable auctions:

```bash
# Another user
poetry run pm-gateway --id GW02

# Watch MSFT in parallel
poetry run pm-viewer --symbol MSFT

# Global order status monitor
poetry run pm-orders

# Market statistics recorder
poetry run pm-stats

# Session scheduler (drives opening/closing auctions)
poetry run pm-scheduler --now
```

### One-command launch

On macOS, you can use the convenience launcher instead:

```bash
./launch_all.sh
```

`launch_all.sh` uses `osascript` to open new Terminal windows, so it is
macOS-specific rather than a generic background-process launcher.

### Browse the docs

```bash
poetry run mkdocs serve
# Open http://127.0.0.1:8000
```

---

## Reference docs

### Ports used

| Socket | Address | Purpose |
|--------|---------|---------|
| Engine PULL | `tcp://127.0.0.1:5555` | Receive orders from gateways |
| Engine PUB  | `tcp://127.0.0.1:5556` | Broadcast all events to subscribers |
| Drop-copy PUB | `tcp://127.0.0.1:5557` | Broadcast fill-only drop-copy events |

---

## Console scripts

| Command | Description |
|---------|-------------|
| `pm-engine`   | Matching engine — the core process that must start first |
| `pm-gateway`  | User gateway (one per user) — accepts ALF commands on stdin ([ALF Protocol Reference](user-guide/20-app-alf-protocol.md)) |
| `pm-viewer`   | Live order book display for a single symbol |
| `pm-orders`   | Global order status monitor (all gateways, all symbols) |
| `pm-audit`    | Event logger — records every message to a rotating log file |
| `pm-clearing` | Trade settlement & P&L tracking |
| `pm-stats`    | Market statistics recorder (SQLite) — OHLCV, VWAP, snapshots |
| `pm-scheduler`| Session scheduler — drives auction/continuous phase transitions |
| `pm-ticker`   | Scrolling market-data ticker fed by `data/stats.db` and live books |
| `pm-board`    | Multi-symbol market board for demos or projections |
| `pm-ai-trader`| Single AI bot gateway/trader |
| `pm-ai-swarm` | Multi-agent AI trading swarm |

---

## Data files

All runtime files are created under `data/` automatically on first run:

| File | Content |
|------|---------|
| `data/gtc_orders.json` | Resting GTC orders — reloaded next trading day |
| `data/gtc_combos.json` | Resting GTC combo parents and child-link state |
| `data/book_stats.json` | Persisted per-symbol last-buy / last-sell context |
| `data/audit.log` | Full audit trail (rotating, max 10 MB × 5 files) |
| `data/clearing_report.csv` | Trade-by-trade settlement record |
| `data/stats.db` | SQLite database: daily OHLCV, snapshots, and trade log |

# Training Guide

Welcome to the EduMatcher self-study training programme. This hands-on guide
takes you from a cold start to confidently operating every major feature of the
exchange.

## How to Use This Guide

Each chapter is a self-contained exercise session. Work through them in order —
later chapters build on configuration and positions established in earlier ones.

**Prerequisites:**

- EduMatcher installed (`pipx install edumatcher` or Poetry dev environment).
- A terminal (or several) available.
- Basic familiarity with YAML and the command line.

**Conventions:**

- `pm-engine>` — text you type in the engine terminal.
- `GW01>` — text you type in a gateway terminal.
- `[output]` — expected output from the system (may vary slightly).
- :material-checkbox-blank-outline: — exercise checkpoint; verify before continuing.

---

## Training Plan

| # | Chapter | Topics |
|---|---------|--------|
| 00 | [Installation & Setup](00-installation.md) | PyPI install, pm-setup, environment variables, data directory |
| 01 | [Configuring & Starting Up](01-configuring-startup.md) | engine_config.yaml, symbols, gateways, starting pm-engine & pm-scheduler |
| 02 | [Setting Up Market-Maker Liquidity](02-setting-up-MM-bots.md) | Market-maker role, manual quotes, QLEGS, planned pm-mm-bot workflow |
| 03 | [The First Trade](03-the-first-trade.md) | BUY/SELL limit orders, fills, order book basics |
| 04 | [Amending Orders](04-amending-orders.md) | AMEND command, price/qty changes, priority rules |
| 05 | [Order Types Deep Dive](05-order-types.md) | MARKET, STOP, FOK, IOC, ICEBERG, TRAILING_STOP |
| 06 | [Time-in-Force & Sessions](06-time-in-force-sessions.md) | DAY, GTC, ATO, ATC; session phases; scheduled transitions |
| 07 | [Auctions](07-auctions.md) | Opening/closing auctions, equilibrium price, ATO/ATC orders |
| 08 | [Cancelling & Managing Orders](08-cancelling-orders.md) | CANCEL, STATUS, ORDERS; managing resting order book |
| 09 | [Market Making](09-market-making.md) | QUOTE command, inactivation policies, obligations, QLEGS |
| 10 | [Combo Orders](10-combo-orders.md) | Multi-leg atomic fills, OCO, leg risk |
| 11 | [Risk Controls](11-risk-controls.md) | pm-admin, pm-admin-cli, price collars, circuit breakers, HALT/RESUME, kill switch |
| 12 | [P&L & Clearing](12-pnl-clearing.md) | Positions, VWAP, realized/unrealized P&L |
| 13 | [Market Data & Drop Copy](13-market-data-drop-copy.md) | CALF feed, drop-copy, subscribing to book/trade events |
| 14 | [AI Traders & Swarm](14-ai-traders.md) | pm-ai-trader, pm-ai-swarm, personality profiles, classroom demos |
| 15 | [Statistics & Reporting](15-statistics-reporting.md) | pm-stats, pm-stats-cli, OHLCV, VWAP queries |
| 16 | [Persistence & Recovery](16-persistence-recovery.md) | data directory, GTC persistence, stats.db, audit logs |
| 17 | [Capstone Scenario](17-capstone-scenario.md) | full exchange session combining all major features |
| 18 | [Exchange Observer Processes](18-exchange-observer-processes.md) | pm-viewer, pm-board, pm-ticker, pm-orders, pm-audit, pm-stats, pm-clearing |

---

## Quick Reference

After completing the training, use the [User Guide](../user-guide/00-getting-started.md)
and [Glossary](../glossary.md) for day-to-day reference.

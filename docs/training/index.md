# Training Guide

Welcome to the EduMatcher self-study training programme. This hands-on guide
takes you from a cold start to confidently operating every major feature of the
exchange.

If you are new to finance we strongly recommend you start by 
reading the [How an Exchange Works](../how-exchange-works.md) which is 
a non-technical introduction to the core components and data flows in an exchange. 
It will make the training exercises more intuitive and meaningful.


## How to Use This Guide

Each chapter is a hands-on session with exercises and checkpoints. Part 1 must
be done in order — later chapters build on the exchange, configuration and
liquidity it establishes. After that the parts are largely independent.

Every chapter states its prerequisites and links the user-guide sections that
back it. Read those first if the topic is new to you; use them afterwards as
the reference.

### What you need

- **EduMatcher installed.** Any of the routes in
  [Installation](../user-guide/005-installation.md) works. Chapter 00 walks
  through them and helps you pick.
- **Several terminals.** The exchange is a set of processes, and this guide
  asks you to watch them side by side. A multiplexer (`tmux`, `screen`) or
  split panes helps, but separate windows are fine.
- **Basic YAML and command line.** No finance background is assumed.

### The two consoles

This is the one thing worth knowing before Chapter 01, because mixing them up
is the most common early mistake:

| | `pm-alf-console` | `pm-admin` |
|---|---|---|
| You are | a **trader** | the **exchange operator** |
| Prompt shown in this guide | `[TRADER01]>` | `[GW_ADMIN\|ADMIN]>` |
| Typical commands | `NEW`, `AMEND`, `CANCEL`, `STATUS`, `ORDERS`, `POS`, `QUOTE`, `QLEGS` | `BOOK`, `HALT_SYM`, `CANCEL_SYM`, `KILL\|GW=`, `SESSION\|STATE=`, `GATEWAYS` |
| Can see the whole order book | No | Yes |

A prompt containing `|ADMIN]>` always means the `pm-admin` terminal. Anything
else is a trader console. Commands are **not** interchangeable between them —
a `BOOK` typed into a trader console just answers `Unknown command`.

### Conventions

- `[TRADER01]>` — type this at that trader console's prompt.
- `[GW_ADMIN|ADMIN]>` — type this at the operator console's prompt.
- A plain `$` or a bare command — type this in a normal shell.
- `[output]` — expected output; exact wording may vary between versions.
- :material-checkbox-blank-outline: — a checkpoint. Verify it before moving on;
  if it fails, the next exercise will not behave as described.

 

## Training Plan

The chapters are grouped into five parts. **Work through Part 1 in order** —
everything later assumes the exchange, configuration and liquidity it sets up.
After that, Parts 2–4 can be taken in the order that suits you, and Part 5 is
a separate integration track you can start any time after Part 1.

Each row links to the lesson. The last column is the user-guide reading that
backs it — skim it before the chapter, or use it afterwards as the reference.

### Part 1 — Foundations (do these in order)

| # | Chapter | You will be able to | Pre-reading |
|---|---------|---------------------|-------------|
| 00 | [Installation & Setup](00-installation.md) | Install EduMatcher and know where its files live | [Installation](../user-guide/005-installation.md), [A Path Through the Guide](../user-guide/001-learning-path.md) |
| 01 | [Configuring & Starting Up](01-configuring-startup.md) | Author, verify, deploy a configuration; start the engine, scheduler and both consoles | [Configuration](../user-guide/010-configuration.md), [Config Verifier](../user-guide/020-config-verifier.md), [Running the Exchange](../user-guide/040-running-the-exchange.md) |
| 02 | [Setting Up Market-Maker Liquidity](02-setting-up-MM-bots.md) | Seed a two-sided book so there is something to trade against | [Market Making](../user-guide/090-market-maker.md), [Market-Maker Bot](../user-guide/100-mm-bot.md) |
| 03 | [The First Trade](03-the-first-trade.md) | Submit orders, read fills, follow an order's lifecycle | [ALF Console](../user-guide/055-alf-console.md), [Order Types](../user-guide/060-order-types.md) |
| 18 | [Exchange Observer Processes](18-exchange-observer-processes.md) | *Do this early.* See the book, the tape and the audit trail while you trade | [Processes](../user-guide/170-processes.md) |

### Part 2 — Trading mechanics

| # | Chapter | You will be able to | Pre-reading |
|---|---------|---------------------|-------------|
| 04 | [Amending Orders](04-amending-orders.md) | Change price and quantity, and predict the effect on queue priority | [Order Amendment](../user-guide/060-order-types.md#order-amendment-amend) |
| 08 | [Cancelling & Managing Orders](08-cancelling-orders.md) | Inspect and cancel resting orders; use the operator's bulk-cancel tools | [ALF Console](../user-guide/055-alf-console.md), [Exchange Commands](../user-guide/160-exchange-commands.md) |
| 05 | [Order Types Deep Dive](05-order-types.md) | Use MARKET, STOP, STOP_LIMIT, FOK, IOC, ICEBERG and TRAILING_STOP | [Order Types](../user-guide/060-order-types.md) |
| 06 | [Time-in-Force & Sessions](06-time-in-force-sessions.md) | Choose a TIF and predict how each session phase treats it | [Auctions & Scheduling](../user-guide/080-session-scheduling.md) |
| 07 | [Auctions](07-auctions.md) | Run an auction and compute the equilibrium price by hand | [Auctions & Scheduling — Equilibrium price](../user-guide/080-session-scheduling.md#equilibrium-price) |
| 10 | [Combo Orders](10-combo-orders.md) | Submit multi-leg and OCO orders, and reason about leg risk | [Combo Orders](../user-guide/070-combo-orders.md) |

### Part 3 — Liquidity and automation

| # | Chapter | You will be able to | Pre-reading |
|---|---------|---------------------|-------------|
| 09 | [Market Making](09-market-making.md) | Run a two-sided quote by hand and inspect its legs | [Market Making](../user-guide/090-market-maker.md) |
| 14 | [AI Traders & Swarm](14-ai-traders.md) | Generate realistic order flow for a demo or class | [AI Traders](../user-guide/110-ai-traders.md) |
| 21 | [Automation & MM Bot Tuning](21-automation-commandclient-mm-bot.md) | Script operator workflows and tune `pm-mm-bot` | [Exchange Commands](../user-guide/160-exchange-commands.md), [Market-Maker Bot](../user-guide/100-mm-bot.md) |

### Part 4 — Operating the exchange

| # | Chapter | You will be able to | Pre-reading |
|---|---------|---------------------|-------------|
| 11 | [Risk Controls](11-risk-controls.md) | Configure and trigger collars, circuit breakers, halts and the kill switch | [Risk Controls](../user-guide/120-risk-controls.md) |
| 19 | [Advanced Admin Operations](19-advanced-admin-operations.md) | Use KICK, QCANCEL, CANCEL_SYM and manual session overrides | [Exchange Commands](../user-guide/160-exchange-commands.md) |
| 12 | [P&L & Clearing](12-pnl-clearing.md) | Read positions, VWAP cost and realized/unrealized P&L | [P&L & Clearing](../user-guide/130-pnl-clearing.md) |
| 15 | [Statistics & Reporting](15-statistics-reporting.md) | Query OHLCV, trades and snapshots for analysis | [Statistics and Reporting](../user-guide/140-statistics-and-reporting.md) |
| 25 | [Market Index](25-index.md) | Run an index and apply corporate actions without disturbing its level | [Market Index](../user-guide/150-market-index.md), [Index Admin CLI](../user-guide/152-index-admin-cli.md) |
| 16 | [Persistence & Recovery](16-persistence-recovery.md) | Say what survives a restart, and verify it | [Persistence](../user-guide/180-persistence.md), [Audit Trail](../user-guide/190-audit.md) |
| 17 | [Capstone Scenario](17-capstone-scenario.md) | Run a full session end to end, combining everything above | [Running the Exchange](../user-guide/040-running-the-exchange.md) |

### Part 5 — External connectivity (integration track)

Start any time after Part 1. These chapters are about connecting *other
software* to the exchange, and are largely independent of each other.

| # | Chapter | You will be able to | Pre-reading |
|---|---------|---------------------|-------------|
| 13 | [Market Data & Drop Copy](13-market-data-drop-copy.md) | Explain the market-data and drop-copy feeds and watch them | [Drop Copy](../user-guide/200-drop-copy.md), [DC Gateway](../user-guide/201-dc-gateway.md) |
| 20 | [Drop-Copy Replay & Recovery](20-drop-copy-replay-recovery.md) | Detect sequence gaps and recover a consumer | [Drop Copy — Replay](../user-guide/200-drop-copy.md#replay) |
| 26 | [ALF TCP Gateway](26-alf-gwy.md) | Speak ALF over a raw socket | [ALF Gateway](../user-guide/220-alf-gateway.md), [ALF Protocol](../user-guide/900-app-alf-protocol.md) |
| 27 | [BALF TCP Gateway](27-balf-gwy.md) | Speak the binary order-entry protocol | [BALF Gateway](../user-guide/230-balf-gateway.md), [BALF Protocol](../user-guide/910-app-balf-protocol.md) |
| 23 | [CALF Market-Data Protocol](23-calf.md) | Write a market-data consumer with snapshots and replay | [CALF Gateway](../user-guide/240-calf-gateway.md), [CALF Protocol](../user-guide/920-app-calf-protocol.md) |
| 22 | [RALF Post-Trade Protocol](22-ralf.md) | Write a clearing, drop-copy or audit consumer | [RALF Gateway](../user-guide/250-ralf-gateway.md), [RALF Protocol](../user-guide/930-app-ralf-protocol.md) |
| 24 | [API Gateway REST/WebSocket](24-api-gwy.md) | Trade and query over REST, and stream over WebSocket | [API Gateway](../user-guide/260-api-gateway.md), [REST API Reference](../user-guide/950-app-REST-API-reference.md) |

 

## Quick Reference

After completing the training, use the [User Guide](../user-guide/000-getting-started.md)
and [Glossary](../glossary.md) for day-to-day reference.

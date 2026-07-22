# Training Guide

Welcome to the EduMatcher self-study training programme. This hands-on guide
takes you from a cold start to confidently operating every major feature of the
exchange.

If you are new to finance we strongly recommend you start by 
reading the [How an Exchange Works](../how-exchange-works.md) which is 
a non-technical introduction to the core components and data flows in an exchange. 
It will make the training exercises more intuitive and meaningful.


## How to Use This Guide

Each chapter is a self-contained exercise session. Work through them in order —
later chapters build on configuration and positions established in earlier ones.

**Prerequisites:**

- EduMatcher installed (`pipx install edumatcher` or Poetry dev environment).
- A terminal (or several) available.
- Basic familiarity with YAML and the command line.

**Bonus:**
- If you are familiar with a terminal multiplexer like `tmux` or `screen`, it can be helpful to run multiple processes in one window with panes. Otherwise, just open several terminal windows. All commands are designed to be run from the command line. Processes that are started often prints status information to the terminal (in addition to data log files) so you can see activity in real time.


**Conventions:**

- `pm-engine>` — text you type in the engine terminal.
- `GW01>` — text you type in a gateway terminal.
- `[output]` — expected output from the system (may vary slightly).
- :material-checkbox-blank-outline: — exercise checkpoint; verify before continuing.

 

## Training Plan

| # | Chapter | Topics |
|---|---------|--------|
| 00 | [Installation & Setup](../user-guide/000-getting-started.md) | PyPI install, pm-setup, environment variables, data directory |
| 01 | [Configuring & Starting Up](../user-guide/010-configuration.md) | engine_config.yaml, symbols, gateways, starting pm-engine & pm-scheduler |
| 02 | [Setting Up Market-Maker Liquidity](../user-guide/090-market-maker.md) | Market-maker role, manual quotes, QLEGS, and pm-mm-bot workflow |
| 03 | [The First Trade](../user-guide/040-running-the-engine.md) | BUY/SELL limit orders, fills, order book basics |
| 04 | [Amending Orders](../user-guide/060-order-types.md) | AMEND command, price/qty changes, priority rules |
| 05 | [Order Types Deep Dive](../user-guide/060-order-types.md) | MARKET, STOP, FOK, IOC, ICEBERG, TRAILING_STOP |
| 06 | [Time-in-Force & Sessions](../user-guide/080-auctions-scheduling.md) | DAY, GTC, ATO, ATC; session phases; scheduled transitions |
| 07 | [Auctions](../user-guide/080-auctions-scheduling.md) | Opening/closing auctions, equilibrium price, ATO/ATC orders |
| 08 | [Cancelling & Managing Orders](../user-guide/050-gateway.md) | CANCEL, STATUS, ORDERS; managing resting order book |
| 09 | [Market Making](../user-guide/090-market-maker.md) | QUOTE command, inactivation policies, obligations, QLEGS |
| 10 | [Combo Orders](../user-guide/070-combos.md) | Multi-leg atomic fills, OCO, leg risk |
| 11 | [Risk Controls](../user-guide/120-risk-controls.md) | pm-admin, pm-admin-cli, price collars, circuit breakers, HALT/RESUME, kill switch |
| 12 | [P&L & Clearing](../user-guide/130-pnl-clearing.md) | Positions, VWAP, realized/unrealized P&L |
| 13 | [Market Data & Drop Copy](../user-guide/200-drop-copy.md) | CALF feed, drop-copy, subscribing to book/trade events |
| 14 | [AI Traders & Swarm](../user-guide/110-ai-traders.md) | pm-ai-trader, pm-ai-swarm, personality profiles, classroom demos |
| 15 | [Statistics & Reporting](../user-guide/140-statistics-and-reporting.md) | pm-stats, pm-stats-cli, OHLCV, VWAP queries |
| 16 | [Persistence & Recovery](../user-guide/180-persistence.md) | data directory, GTC persistence, stats.db, audit logs |
| 17 | [Capstone Scenario](../user-guide/040-running-the-engine.md) | full exchange session combining all major features |
| 18 | [Exchange Observer Processes](../user-guide/170-processes.md) | pm-viewer, pm-board, pm-ticker, pm-orders, pm-audit, pm-stats, pm-clearing |
| 19 | [Advanced Admin Operations](../user-guide/160-commands.md) | kick, qcancel, cancel-sym, session overrides, verification patterns |
| 20 | [Drop-Copy Replay & Recovery Patterns](../user-guide/200-drop-copy.md) | sequence-gap detection, replay limits, operational recovery workflow |
| 21 | [Automation with CommandClient & MM Bot Tuning](../user-guide/160-commands.md) | Python automation flows, admin orchestration, advanced pm-mm-bot runtime tuning |
| 22 | [RALF Post-Trade Gateway Protocol](../user-guide/250-post-trade.md) | pm-ralf-gwy, RALF handshake/subscriptions, role-based consumers, replay and recovery |
| 23 | [CALF Market-Data Gateway Protocol](../user-guide/240-market-data-feed.md) | pm-md-gwy, CALF handshake/subscriptions, snapshots, replay and recovery |
| 24 | [API Gateway REST/WebSocket](../user-guide/170-processes.md) | pm-api-gwy, bearer tokens, REST endpoints, WebSocket streams, multi-instance split |
| 25 | [Market Index (pm-index)](../user-guide/150-index.md) | Index config, cap-weighted formula, divisor, corporate actions via pm-index-admin-cli, INDEX command, pm-index-cli |
| 26 | [ALF TCP Gateway Protocol](../user-guide/220-alf-gateway.md) | pm-alf-gwy, port verification with CLI tools, nc/telnet handshake, Python and C example clients, order lifecycle over raw TCP |
| 27 | [BALF TCP Gateway Protocol](../user-guide/230-balf-gateway.md) | pm-balf-gwy, binary LOGON/LOGON_ACK session flow, raw frame order lifecycle, heartbeat handling, parser validation |

 

## User Guide Cross-Reference by Chapter

Use these links when you want the authoritative user-guide section behind each
training chapter.

| Training Chapter | Relevant User Guide Sections |
|---|---|
| 00 | [Installation](../user-guide/000-getting-started.md#installation), [Environment variables](../user-guide/000-getting-started.md#environment-variables) |
| 01 | [Configuring the Exchange](../user-guide/010-configuration.md#configuring-the-exchange), [Generate Configs with pm-config-gen](../user-guide/010-configuration.md#generate-configs-with-pm-config-gen) |
| 02 | [The QUOTE command](../user-guide/090-market-maker.md#the-quote-command), [Quick start (pm-mm-bot)](../user-guide/100-mm-bot.md#quick-start) |
| 03 | [Command Format](../user-guide/050-gateway.md#command-format), [Gateway Responses](../user-guide/050-gateway.md#gateway-responses) |
| 04 | [Order Amendment (AMEND)](../user-guide/060-order-types.md#order-amendment-amend), [Command Format](../user-guide/050-gateway.md#command-format) |
| 05 | [STOP (Stop-Market)](../user-guide/060-order-types.md#stop-stop-market), [TRAILING_STOP](../user-guide/060-order-types.md#trailing_stop) |
| 06 | [Session phases](../user-guide/080-auctions-scheduling.md#session-phases), [The session scheduler (pm-scheduler)](../user-guide/080-auctions-scheduling.md#the-session-scheduler-pm-scheduler) |
| 07 | [Equilibrium price](../user-guide/080-auctions-scheduling.md#equilibrium-price), [What are auctions?](../user-guide/080-auctions-scheduling.md#what-are-auctions) |
| 08 | [Command Format](../user-guide/050-gateway.md#command-format), [Gateway Responses](../user-guide/050-gateway.md#gateway-responses) |
| 09 | [Quote lifecycle](../user-guide/090-market-maker.md#quote-lifecycle), [MM quote identification and quote-leg mapping](../user-guide/090-market-maker.md#mm-quote-identification-and-quote-leg-mapping) |
| 10 | [What Are Combo Orders?](../user-guide/070-combos.md#what-are-combo-orders), [OCO (One-Cancels-Other)](../user-guide/060-order-types.md#oco-one-cancels-other) |
| 11 | [Price collars](../user-guide/120-risk-controls.md#price-collars), [Circuit breakers](../user-guide/120-risk-controls.md#circuit-breakers) |
| 12 | [Position Tracking](../user-guide/130-pnl-clearing.md#position-tracking), [Quick-reference: P&L formulas](../user-guide/130-pnl-clearing.md#quick-reference-pl-formulas) |
| 13 | [Message format](../user-guide/200-drop-copy.md#message-format), [Sequence and recovery semantics](../user-guide/920-app-calf-protocol.md#sequence-and-recovery-semantics) |
| 14 | [Personality profiles](../user-guide/110-ai-traders.md#personality-profiles), [Launching a swarm](../user-guide/110-ai-traders.md#launching-a-swarm) |
| 15 | [Querying with pm-stats-cli](../user-guide/140-statistics-and-reporting.md#querying-with-pm-stats-cli), [Common Analyst Workflows](../user-guide/140-statistics-and-reporting.md#common-analyst-workflows) |
| 16 | [How It Works](../user-guide/180-persistence.md#how-it-works), [Summary of All Data Files](../user-guide/180-persistence.md#summary-of-all-data-files) |
| 17 | [Verifying the system is running correctly](../user-guide/040-running-the-engine.md#verifying-the-system-is-running-correctly), [Process Overview](../user-guide/170-processes.md#process-overview) |
| 18 | [Process Overview](../user-guide/170-processes.md#process-overview), [pm-clearing — Clearing & P&L](../user-guide/170-processes.md#pm-clearing-clearing-pl) |
| 19 | [ADMIN console (pm-admin)](../user-guide/160-commands.md#admin-console-pm-admin), [CLI tool (pm-admin-cli)](../user-guide/160-commands.md#cli-tool-pm-admin-cli) |
| 20 | [Replay](../user-guide/200-drop-copy.md#replay), [Sequence and recovery semantics](../user-guide/920-app-calf-protocol.md#sequence-and-recovery-semantics) |
| 21 | [ExchangeCommandClient](../user-guide/160-commands.md#exchangecommandclient), [CLI reference (pm-mm-bot)](../user-guide/100-mm-bot.md#cli-reference) |
| 22 | [Post-Trade Dissemination (RALF)](../user-guide/250-post-trade.md), [Appendix: RALF Protocol Reference](../user-guide/930-app-ralf-protocol.md) |
| 23 | [Market Data Feed (CALF)](../user-guide/240-market-data-feed.md), [Appendix: CALF Protocol Reference](../user-guide/920-app-calf-protocol.md) |
| 24 | [pm-api-gwy processes](../user-guide/170-processes.md#pm-api-gwy-restwebsocket-api-gateway), [API Gateway Config](../user-guide/260-api-gateway.md) |
| 25 | [Market Index (pm-index)](../user-guide/150-index.md), [Index Admin CLI](../user-guide/152-index-admin-cli.md), [pm-index-cli reference](../user-guide/160-commands.md), [pm-index process](../user-guide/170-processes.md#pm-index-index-calculation-process) |
| 26 | [ALF TCP Gateway](../user-guide/220-alf-gateway.md), [ALF Protocol Reference](../user-guide/900-app-alf-protocol.md), [Gateway Commands](../user-guide/050-gateway.md) |
| 27 | [BALF TCP Gateway](../user-guide/230-balf-gateway.md), [BALF Protocol Reference](../user-guide/910-app-balf-protocol.md), [Configuration](../user-guide/010-configuration.md#configuring-pm-balf-gwy) |

 

## Quick Reference

After completing the training, use the [User Guide](../user-guide/000-getting-started.md)
and [Glossary](../glossary.md) for day-to-day reference.

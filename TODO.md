Version: 1.9.0

Date: 2026-09-24

Status: Proposal



# High Level Roadmap

The roadmap is given in roughly the chrnological order the features will be implemented. 
Fully implemeted features are removed from this file. 

All referenced desig documents live under `docs-design/`


## Fix remaining bugs in Trader Info Terminal GUI

See: `docs-design/reviews/EduMatcher-Terminal-GUI-Final-Review.md` 

Target: Oct 2026

### High defects
 - H1. Production sign-off still lacks a live-stack failure-mode soak
 - H2. AUCTION gaps are broadcast but not displayed anywhere
 - H3. History failures in Symbol Detail can be rendered as "no history"
 - H4. No liveness check on the browser↔bridge WebSocke

### Medium defects
 - M1. Index View lacks the same explicit history-outage handling
 - M2. Default Index View hides Open/High/Low on intraday timeframes
 - M3. Live-feed silence is visible but not forceful
 - M4. Previous-close age is defined but not surfaced
 - M5. Halt countdown and "halted for" timers freeze between frames
 - M6. Symbol Detail session statistics ignore history failure and age
 - M7. Chart windows do not roll over at UTC midnight on an unattended display
 - M8. "Fade off" preference comes back after a reload as a control that shows "fade 1 min"


## Replace the TradingView graph module in the termina-GUI with Apache ECharts

Target: Nov 2026

Design for replacing TradingView **Lightweight Charts v5** with **Apache ECharts** in the
Symbol Detail chart ([§16.2 of `EduMatcher-Trading-GUI.md`](./EduMatcher-Trading-GUI.md#162-chart-tab-tradingview-lightweight-charts-v5)),
driven by a licensing constraint: Lightweight Charts is Apache-2.0 licensed but carries a
self-imposed attribution clause (on-chart logo + backlink to tradingview.com via the
`attributionLogo` option, default `true`) that is inappropriate for an educational product.
Apache ECharts carries no such clause.


## Implement a model CCP

Target: Mar 2027

Design: `EduMatcher-Clearing.md` (related: `EduMatcher-contract-multiplyer.md`)

The current `pm-clearing` process keeps P&L state in memory, periodically prints
that state, and appends trade rows to a CSV file (`data/clearing_report.csv`).
This is useful for demos but has operational limitations:

- state is not query-friendly after restart
- no indexed filtering by gateway, symbol, or day
- no robust ad-hoc reporting surface for operations/compliance teams
- no controlled write batching for high-throughput trade bursts

We need a durable clearing subsystem that:

- preserves all trade-level inputs from `trade.executed`
- keeps per-gateway running position and P&L summaries continuously available
- supports high-frequency trade bursts without writing each event individually
- ~~exposes user-friendly, no-SQL query tooling (`pm-clearing-cli`)~~
- ~~follows EduMatcher CLI conventions, including `--help` and `--version`~~


## Completion of the System-Testing Framework

Target: Maj 2027

Design: `EduMatcher-System-Trading-Verification.md` 

That suite proves *components* behave. It does not prove the *exchange*
behaves. Every unit test constructs its own fake sockets, its own config, its
own in-process `Engine`, and asserts on a return value. Nothing today answers
the question an exchange operator actually asks:

> If a trader submits a LIMIT order through the ALF console, and another
> trader submits an aggressing MARKET order through the REST API, does the
> resulting trade, the market-data tick, the drop-copy, the post-trade
> dissemination, the audit journal, the stats database and the clearing
> ledger *all agree with each other and with the rulebook*?

This framework aims to use *sensors* on all observable output from the SIT and correltate them to secure 
internal consistency. 

- ~~Phase 0 — Prerequisites, complete observability gaps~~
- Phase 1 — Framework skeleton + first scenario
- Phase 3 — Time and the trading week
- Phase 4 — Extension

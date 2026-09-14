Version: 1.8.0

Date: 2026-09-14

Status: Proposal

# High Level Roadmap

The roadmap is given in roughly the chrnological order the features will be implemented. 
Fully implemeted features are removed from this file. 

All referenced desig documents live under `docs-design/`


## 1. Complete the `pm-audit-replay-cli` command

Target completion date: Q4 2026

Design: `EduMatcher-Audit-Replay.md` 

This command is intended both as a verification tool during development that secures the internal
consistency of the exchange from an holistic POV but also as a post-mortem tool to fullly understand
the steps that lead up to a certain market condition

- ~~Phase 0 — Foudational work, extending message covering~~
- ~~Phase 1 - The tool fundamentals, scaffolding~~
- ~~Phase 2 — State models and the link resolver~~ 
- ~~Phase 3 — Episodes and the index~~
- ~~Phase 4 — Narration, first user-visible output~~
- Phase 5 — Anomalies and the remaining views

## 2. Completion of the System-Testing Framework

Target completion: Q1 2027

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


## 3. Implement a model CCP

Target completion: Q1 2027

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

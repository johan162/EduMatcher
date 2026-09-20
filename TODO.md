Version: 1.8.0

Date: 2026-09-14

Status: Proposal

# High Level Roadmap

The roadmap is given in roughly the chrnological order the features will be implemented. 
Fully implemeted features are removed from this file. 

All referenced desig documents live under `docs-design/`

## ~~ALF Gateway Combo bug~~

**FIXED**

"Known bug: OCO leg price/stop/trail fields are dropped on the wire"
The ALF gateway builds each OCO leg's wire payload with the keys `price`,
`stop_price`, and `trail_offset`, but the engine's OCO handler reads
`price_ticks`, `stop_price_ticks`, and `trail_offset_ticks` from that same
payload. The mismatch means any `LEG1_PRICE=`/`LEG1_STOP=`/`LEG1_TRAIL=`
(or `LEG2_*`) value you supply is silently dropped before it reaches the
engine, and the leg is then rejected as missing its required price/stop
(e.g. `Leg 1 (LIMIT) requires price`). As of this writing, **every OCO
example below that includes a leg price, stop, or trail offset will be
rejected** — only an OCO pair whose legs need no such field (which none
of the standard order types allow) would go through. This is a defect in
the gateway/engine wire contract, not in how you invoke `NEW|TYPE=OCO`.

- If any leg is cancelled or expires, all remaining legs are automatically
  **cascade-cancelled** (unfilled quantities only — fills already ex



## Fix remaining known bugs in Trading Station GUI

Target: Oct 2026

### Critical defects
#### ~~C1 — A rejected cancel or amend marks a live order `REJECTED` (GUI and gateway cache)~~
#### ~~C2 — Cancel-replace defaults to the original total quantity → over-trading on partial fills~~
#### ~~C3 — Live order rows lack `stop_price` / `visible_qty` / `trail_offset` / `smp_action`, so Replace and Undo break~~

### High defects
#### ~~H1 — OCO legs are never grouped; "Cancel group" is unreachable~~
#### ~~H2 — Trade prints are not de-duplicated; replay inflates volume and can crash the chart handler~~
#### ~~H3 — Gap repair for `trade.executed` can never succeed~~
#### ~~H4 — Halts are invisible to TRADER/MARKET_MAKER unless they begin after login~~
#### ~~H5 — Session phase defaults to CLOSED and is never re-synced after a reconnect~~
#### ~~H6 — The private stream has no gap detection, and Refresh cannot reconcile~~

### Medium defects
#### ~~M1 — Order-type gating is narrower than the engine~~
#### ~~M2 — "Accepted" is misleading for FOK, MARKET and IOC~~
#### ~~M3 — Bulk cancel and Flatten All lose per-order feedback~~
#### ~~M4 — Flatten semantics~~
#### ~~M5 — The combo form forces~~
#### ~~M6 — The Amend and Replace dialogs work on a snapshot of the order~~
#### ~~M7 — The ticket's session and tick rules have no single source~~
#### ~~M8 — Gateway~~

### Low defect
~~L1, L2, L3, L4, L5, L6, L7, L8, L9, L10~~

## Fix remaining bugs in Trader Info Terminal GUI

Target: Dec 2026

### High defects
#### H1. Production sign-off still lacks a live-stack failure-mode soak
#### H2. AUCTION gaps are broadcast but not displayed anywhere
#### H3. History failures in Symbol Detail can be rendered as "no history"
#### H4. No liveness check on the browser↔bridge WebSocke

### Medium defects
#### M1. Index View lacks the same explicit history-outage handling
#### M2. Default Index View hides Open/High/Low on intraday timeframes
#### M3. Live-feed silence is visible but not forceful
#### M4. Previous-close age is defined but not surfaced
#### M5. Halt countdown and "halted for" timers freeze between frames
#### M6. Symbol Detail session statistics ignore history failure and age
#### M7. Chart windows do not roll over at UTC midnight on an unattended display
#### M8. "Fade off" preference comes back after a reload as a control that shows "fade 1 min"

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

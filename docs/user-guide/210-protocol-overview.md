# External Protocols Overview

!!! note "Learning objectives"
    After reading this page you will understand:

    - which external protocols EduMatcher defines and why each exists
    - the runtime status of each protocol and the gateway/process that serves it
    - where to find each protocol's formal specification appendix
    - where to find the operational chapters that explain how each protocol is used


## Why this page exists

EduMatcher exposes and documents four external protocol families:

1. ALF
2. BALF
3. CALF
4. RALF

They serve different connectivity purposes. This page is the quick map that
connects each protocol to:

- its purpose
- runtime status
- gateway/process context
- detailed chapters
- formal protocol reference appendix


## Protocol map

| Protocol | Primary purpose | Transport/format | Runtime status | Typical gateway/process |
|---|---|---|---|---|
| **ALF** | Human-readable order entry and gateway control | Text line protocol (`FIELD=VALUE|...`) | Implemented and active | `pm-alf-console` (interactive) · `pm-alf-gwy` (TCP) |
| **BALF** | Low-latency binary order entry for programmatic clients | Binary framed protocol | Implemented and active | `pm-balf-gwy` |
| **CALF** | External market-data dissemination (top/book/trade/state style channels) | Text line protocol over TCP | Implemented and active | `pm-md-gwy` |
| **RALF** | External post-trade dissemination for clearing, drop-copy, and audit consumers | Text line protocol over TCP (`RALF1`) | Implemented and active | `pm-ralf-gwy` |


## ALF (Almost FIX)

ALF is EduMatcher's active, user-facing order-entry protocol. It is used by
interactive participant gateways and is the primary way traders submit and
manage orders in current deployments.

ALF is available in two runtime forms:

| Process | Purpose | Transport |
|---------|---------|----------|
| `pm-alf-console` | Interactive REPL for a human at a terminal — stdin/stdout, tab completion, P&L display | Local process; stdin/stdout |
| `pm-alf-gwy` | TCP gateway for external bots and remote clients — same ALF protocol over a plain TCP socket | TCP (default port `5565`) |

Use ALF when you need:

- interactive/manual order entry → `pm-alf-console`
- educational readability of commands
- direct access to the full command set
- an external bot or remote process submitting orders → `pm-alf-gwy`

Where to read more:

- ALF TCP gateway operational guide: [ALF TCP Gateway](220-alf-gateway.md)
- Gateway behavior and operator workflow: [Gateway Commands](050-gateway.md)
- Process-level role of both ALF processes: [Processes](170-processes.md#pm-alf-gwy-alf-tcp-gateway)
- Engine configuration of allowed ALF IDs/roles: [Configuration](010-configuration.md#alf-gateway-allowlist)
- Formal wire syntax and semantics: [Appendix - ALF Protocol](900-app-alf-protocol.md)


## BALF (Binary ALF)

BALF is the binary order-entry protocol family. It targets programmatic clients
that need compact framing and lower parsing overhead than text order-entry
formats.

BALF is implemented and runs as `pm-balf-gwy`, a TCP gateway that accepts binary
order-entry frames from programmatic clients.

Use BALF when you need:

- binary order-entry framing
- explicit low-latency protocol design
- a programmatic session model with binary message layouts

Where to read more:

- Operational deployment and runbook: [BALF TCP Gateway](230-balf-gateway.md)
- Runtime process and architecture placement: [Processes](170-processes.md)
- Protocol design details and message/frame definitions: [Appendix - BALF Protocol](910-app-balf-protocol.md)
- Configuration context and protocol family notes: [Configuration](010-configuration.md)


## CALF (Channel ALF)

CALF is the external market-data protocol family. It is designed for
subscription-based market-data delivery (channelized streams, snapshot +
incremental patterns, and sequence-aware recovery semantics).

CALF is implemented via `pm-md-gwy` and is used for external market-data
distribution with snapshot, incremental, and replay-aware reconnect semantics.

Use CALF when you need:

- external market-data subscription channels
- deterministic sequence/reconnect semantics for data consumers
- a text-based market-data feed for educational and integration scenarios
- to subscribe to the index for the exchange

Where to read more:

- Market-data concepts and channel model: [Market Data Feed (CALF)](../concepts/06-concepts-market-data-feed.md)
- Runtime process and architecture placement: [Processes](170-processes.md#pm-md-gwy-calf-market-data-gateway)
- Operational client onboarding and examples: [Market Data Feed (CALF)](240-market-data-feed.md)
- Formal wire protocol reference: [Appendix - CALF Protocol](920-app-calf-protocol.md)


## RALF (Reconciliation ALF)

RALF is EduMatcher's active post-trade dissemination protocol. It is used by
`pm-ralf-gwy` to stream post-trade events to external systems such as clearing,
drop-copy, and audit consumers.

Use RALF when you need:

- external post-trade event distribution
- role-based consumption (`CLEARING`, `DROP_COPY`, `AUDIT`)
- replay-aware reconnect behavior for downstream systems

Where to read more:

- Operational deployment and runbook: [Post-Trade Dissemination (RALF)](250-post-trade.md)
- Process-level role in runtime topology: [Processes](170-processes.md#pm-ralf-gwy-post-trade-dissemination-gateway)
- RALF gateway configuration details: [Configuration](010-configuration.md#configuring-pm-ralf-gwy)
- Formal wire protocol reference: [Appendix - RALF Protocol](930-app-ralf-protocol.md)


## Quick selection guide

| If you need to...                                    | Protocol to start with |
|------------------------------------------------------|------------------------|
| Enter and manage orders from participant terminals   | **ALF** (`pm-alf-console`) |
| Submit orders from an external bot or remote process | **ALF** (`pm-alf-gwy`) |
| Plan binary low-latency order-entry integrations     | **BALF** (`pm-balf-gwy`)              |
| Consume market-data channels externally              | **CALF** (`pm-md-gwy`)               |
| Consume post-trade/clearing/audit streams externally | **RALF** (`pm-ralf-gwy`)               |


## See also

- [Getting Started](000-getting-started.md)
- [Processes](170-processes.md)
- [ALF TCP Gateway](220-alf-gateway.md)
- [BALF TCP Gateway](230-balf-gateway.md)
- [Market Data Feed (CALF)](240-market-data-feed.md)
- [Post-Trade Dissemination (RALF)](250-post-trade.md)
- [Appendix - ALF Protocol](900-app-alf-protocol.md)
- [Appendix - BALF Protocol](910-app-balf-protocol.md)
- [Appendix - CALF Protocol](920-app-calf-protocol.md)
- [Appendix - RALF Protocol](930-app-ralf-protocol.md)

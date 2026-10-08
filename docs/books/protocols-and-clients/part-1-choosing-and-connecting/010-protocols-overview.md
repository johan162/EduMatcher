# Protocols Overview

!!! note "Learning objectives"
    After reading this page you will understand:

    - which external protocols EduMatcher defines and why each exists
    - the runtime status of each protocol and the gateway/process that serves it
    - where to find each protocol's formal specification appendix
    - where to find the operational chapters that explain how each protocol is used


## Why this page exists

EduMatcher exposes and documents six external protocol families, plus the
internal ZeroMQ message bus that ties its own processes together:

1. ALF — order entry
2. BALF — binary order entry
3. CALF — market data
4. RALF — post-trade dissemination
5. LALF — centralized process logging
6. REST/WebSocket (`pm-api-gwy`) — HTTP access to order entry and history

A seventh, narrower wire format, DC1 (spoken by `pm-dc-gwy`), gives plain-TCP
clients a text-line view of the same fill data RALF's `DROP_COPY` role and the
engine's own drop-copy PUB socket already carry — see
[Drop Copy](../part-3-session-behaviour/060-drop-copy.md) for how the three relate.

They serve different connectivity purposes. This page is the quick map that
connects each protocol to:

- its purpose
- runtime status
- gateway/process context
- detailed chapters
- formal protocol reference appendix


## Protocol map

| Protocol | Primary purpose | Transport/format | Prices on the wire | Runtime status | Typical gateway/process |
|---|---|---|---|---|---|
| **ALF** | Human-readable order entry and gateway control | Text line protocol (`FIELD=VALUE|...`) | Decimal display price | Implemented and active | `pm-alf-console` (interactive) · `pm-alf-gwy` (TCP) |
| **BALF** | Low-latency binary order entry for programmatic clients | Binary framed protocol | `i64` fixed-point, scale 1e8 | Implemented and active | `pm-balf-gwy` |
| **CALF** | External market-data dissemination (top/book/trade/state style channels) | Text line protocol over TCP (`CALF1`) | Decimal display price | Implemented and active | `pm-md-gwy` |
| **RALF** | External post-trade dissemination for clearing, drop-copy, and audit consumers | Text line protocol over TCP (`RALF1`) | Decimal display price | Implemented and active | `pm-ralf-gwy` |
| **LALF** | Centralized process logging | Text line protocol over TCP | n/a | Implemented and active | `pm-log-srv` |
| **REST/WebSocket** | HTTP/WS access to order entry and history, for browser UIs and dashboards | JSON over HTTP + WebSocket | Decimal display price | Implemented and active | `pm-api-gwy` |

BALF is the one protocol here whose wire encoding of price actually differs —
a scaled 64-bit integer, not a decimal string — so a client written against
ALF/CALF/RALF/REST needs a different price parser for BALF.


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

- ALF TCP gateway operational guide: [ALF TCP Gateway](../../operator-guide/part-5-gateways/010-alf-gateway.md)
- Interactive client behavior and operator workflow (`pm-alf-console` is a client, not a gateway): [ALF Console](../../participant-guide/part-2-orders/010-the-trader-console.md)
- Process-level role of `pm-alf-console`: [Processes](../../reference-manual/part-1-command-line/010-processes-environment-and-ports.md#pm-alf-console-user-gateway)
- Process-level role of `pm-alf-gwy`: [Processes](../../reference-manual/part-1-command-line/010-processes-environment-and-ports.md#pm-alf-gwy-alf-tcp-gateway)
- Engine configuration of allowed ALF IDs/roles: [Configuration](../../operator-guide/part-2-configure/010-the-configuration-workflow.md#participants)
- Formal wire syntax and semantics: [Appendix - ALF Protocol](../part-2-specifications/010-alf.md)


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

- Operational deployment and runbook: [BALF TCP Gateway](../../operator-guide/part-5-gateways/020-balf-gateway.md)
- Runtime process and architecture placement: [Processes](../../reference-manual/part-1-command-line/010-processes-environment-and-ports.md)
- Protocol design details and message/frame definitions: [Appendix - BALF Protocol](../part-2-specifications/020-balf.md)
- Configuration context and protocol family notes: [Configuration](../../operator-guide/part-2-configure/010-the-configuration-workflow.md)


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

- Market-data concepts and channel model: [Market Data Feed (CALF)](../part-3-session-behaviour/030-calf-market-data-feed.md)
- Runtime process and architecture placement: [Processes](../../reference-manual/part-1-command-line/010-processes-environment-and-ports.md#pm-md-gwy-calf-market-data-gateway)
- Operational client onboarding and examples: [Market Data Feed (CALF)](../../operator-guide/part-5-gateways/030-calf-gateway.md)
- Formal wire protocol reference: [Appendix - CALF Protocol](../part-2-specifications/030-calf.md)


## RALF (Reconciliation ALF)

RALF is EduMatcher's active post-trade dissemination protocol. It is used by
`pm-ralf-gwy` to stream post-trade events to external systems such as clearing,
drop-copy, and audit consumers.

Use RALF when you need:

- external post-trade event distribution
- role-based consumption (`CLEARING`, `DROP_COPY`, `AUDIT`)
- replay-aware reconnect behavior for downstream systems

Where to read more:

- Operational deployment and runbook: [Post-Trade Dissemination (RALF)](../../operator-guide/part-5-gateways/040-ralf-gateway.md)
- Process-level role in runtime topology: [Processes](../../reference-manual/part-1-command-line/010-processes-environment-and-ports.md#pm-ralf-gwy-post-trade-dissemination-gateway)
- RALF gateway configuration details: [Configuration](../../operator-guide/part-2-configure/010-the-configuration-workflow.md#configuring-pm-ralf-gwy)
- Formal wire protocol reference: [Appendix - RALF Protocol](../part-2-specifications/040-ralf.md)


## LALF (Log ALF)

LALF is the protocol `pm-log-srv` speaks to collect operational log lines from
every other `pm-*` process, and to distribute them live to log viewers. It
carries no trading data.

Where to read more:

- Operational guide: [Log Server](../../operator-guide/part-6-observe-and-recover/040-log-server.md)
- Formal wire protocol reference: [Appendix - LALF Protocol](../part-2-specifications/050-lalf.md)


## REST/WebSocket (`pm-api-gwy`)

The REST API is EduMatcher's HTTP-native external interface, intended for
browser UIs, dashboards, and simple bots that would rather speak JSON over
HTTP than a text-line protocol. It translates requests into the same order
flow and history queries the other gateways use, and exposes a WebSocket for
live updates.

Use REST/WebSocket when you need:

- a browser-based UI or dashboard
- a scripting language with an easy HTTP client but no ZeroMQ bindings
- JSON request/response instead of a line protocol

Where to read more:

- Operational guide and endpoint reference: [API Gateway](../../operator-guide/part-5-gateways/050-api-gateway.md)
- Formal reference: [Appendix - REST API Reference](../part-2-specifications/060-rest-and-websocket.md)


## Drop copy and DC1 (`pm-dc-gwy`)

Drop copy is not a separate protocol family in the sense of the six above —
it is a second way to reach the same fill data RALF's `DROP_COPY` role
already carries. The engine publishes fills directly on its own dedicated
ZMQ PUB socket (port `5557`); `pm-dc-gwy` relays that feed as a lightweight
text-line protocol ("DC1") for plain-TCP clients that don't speak ZeroMQ or
RALF.

Where to read more:

- Engine-side feed and wire format: [Drop Copy](../part-3-session-behaviour/060-drop-copy.md)
- The DC1 gateway and protocol: [Drop-Copy Gateway](../../operator-guide/part-5-gateways/060-drop-copy-gateway.md)
- A ready-made DC1 client for testing: [dc-spy CLI](../part-4-writing-clients/040-the-spy-tools.md)


## Internal ZeroMQ message bus

Everything above is the *external* surface. Internally, every EduMatcher
process talks to every other one over a shared ZeroMQ bus of topic-tagged
messages — the catalogue the protocols above are themselves built from.

Where to read more:

- Message framing, topics, and the full message catalogue: [Message Reference](../part-5-message-reference/010-message-reference.md)


## Quick selection guide

| If you need to...                                    | Protocol to start with |
|------------------------------------------------------|------------------------|
| Enter and manage orders from participant terminals   | **ALF** (`pm-alf-console`) |
| Submit orders from an external bot or remote process | **ALF** (`pm-alf-gwy`) |
| Plan binary low-latency order-entry integrations     | **BALF** (`pm-balf-gwy`)              |
| Consume market-data channels externally              | **CALF** (`pm-md-gwy`)               |
| Consume post-trade/clearing/audit streams externally | **RALF** (`pm-ralf-gwy`)               |
| Give a plain-TCP client just the fill stream          | **DC1** (`pm-dc-gwy`)                |
| Collect operational logs centrally                    | **LALF** (`pm-log-srv`)              |
| Build a browser UI, dashboard, or simple HTTP bot      | **REST/WebSocket** (`pm-api-gwy`)    |


## See also

**In this book:**

- [Message Reference](../part-5-message-reference/010-message-reference.md)
- [Drop Copy](../part-3-session-behaviour/060-drop-copy.md)
- [Appendix - ALF Protocol](../part-2-specifications/010-alf.md)
- [Appendix - BALF Protocol](../part-2-specifications/020-balf.md)
- [Appendix - CALF Protocol](../part-2-specifications/030-calf.md)
- [Appendix - RALF Protocol](../part-2-specifications/040-ralf.md)
- [Appendix - LALF Protocol](../part-2-specifications/050-lalf.md)
- [Appendix - REST API Reference](../part-2-specifications/060-rest-and-websocket.md)

**Quick Start Guide:**

- Getting Started

**Operator's Guide:**

- ALF TCP Gateway
- BALF TCP Gateway
- Market Data Feed (CALF)
- Post-Trade Dissemination (RALF)
- Drop-Copy Gateway
- Log Server
- API Gateway

**Reference Manual:**

- Processes

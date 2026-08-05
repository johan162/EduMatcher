# Gateway Concepts

!!! note "Learning objectives"
    After reading this page you will understand:

    - What a gateway is and what role it plays in an exchange architecture
    - Why real exchanges offer multiple gateway protocols and what the major
      industry-standard formats are
    - How EduMatcher simplifies the real-world concepts of users, participants,
      and members — and what those concepts mean in production
    - Why arrival order at the matching engine matters and how real exchanges are
      legally obligated to handle it fairly
    - Which gateway processes EduMatcher provides, and where to read the
      operational guide for each one
    - Why `pm-alf-console`, the interactive terminal used throughout this guide,
      is technically **not** a gateway, and where the real ALF gateway lives

    **Prerequisites**: [Configuration](010-configuration.md) — gateway IDs and
    roles are defined in `engine_config.yaml` before any client can connect.

## What is a gateway?

An exchange **gateway** is the entry point through which external participants
send orders and receive market data and execution reports.  It translates the
external message format (FIX, binary, proprietary) into the internal format the
matching engine understands, authenticates the sender, applies pre-trade risk
checks, and routes messages to the right destination.

The gateway is deliberately kept outside the matching engine.  The engine's
only job is to match orders; it must not be slowed down by format parsing,
session management, or rate limiting.  Separating these concerns also allows
the exchange to offer multiple gateway protocols simultaneously — an HFT firm
and a retail broker can both connect to the same engine while speaking
completely different wire formats.

A defining trait of a gateway, in this sense, is that it terminates an
external transport (typically a TCP listener) and accepts connections from
processes it does not control, often running on other hosts. A process that
only talks to the engine's own internal message bus, and cannot be reached
from outside that bus, is not a gateway by this definition — see
[`pm-alf-console` is not a gateway](055-alf-console.md#pm-alf-console-is-not-a-gateway)
for a concrete example.

## Industry-standard gateway protocols

Real exchanges offer a range of gateway types.  Each targets a different
client population:

| Protocol | Type | Used by | Notes |
|----------|------|---------|-------|
| **FIX 4.2 / 4.4 / 5.0** | Text (tag=value) | Brokers, buy-side OMS | The lingua franca of institutional order routing; every major venue supports it; verbose but universally understood |
| **OUCH (Nasdaq)** | Binary | HFT, proprietary traders | Ultra-low latency; fixed-length binary fields; single-digit microsecond round trips |
| **ITCH (Nasdaq)** | Binary (market data only) | Market data consumers | One-way feed; used for direct order book reconstruction at co-location |
| **FAST / SBE** | Binary | Market data consumers | Simple Binary Encoding; used by CME, Eurex for market data |
| **BOE (CBOE/BATS)** | Binary | HFT | Binary Order Entry; competes with OUCH |
| **ETI (Eurex)** | Binary | European derivatives traders | Enhanced Transaction Interface; supports complex derivatives workflows |
| **Proprietary REST/WebSocket** | Text / JSON | Retail, algorithmic | Used by crypto exchanges and some retail venues; easy to integrate |

EduMatcher's order-entry gateway speaks a **FIX-inspired pipe-delimited text format** that
we call **ALF** (**AL**most **F**ix):
`NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00`.
It borrows FIX's field=value concept but uses a simplified subset - no session
layer, no checksums, no sequence numbers, and no standard FIX message set.
A production FIX gateway would add all of these.

!!! note "Formal protocol reference"
    This page explains the general gateway concept and lists what EduMatcher
    provides. The formal syntax and semantics of the ALF protocol are defined
    in [Appendix: ALF Protocol Reference](900-app-alf-protocol.md), and a
    protocol-by-protocol comparison of ALF/BALF/CALF/RALF lives in
    [External Protocols Overview](210-protocols-overview.md).

## EduMatcher's gateways

EduMatcher ships one gateway (or gateway-like process) per protocol family. Each
binds its own TCP port, is configured from its own section of
`engine_config.yaml`, and can be started and restarted independently of the
matching engine and of every other gateway.

| Protocol | Process | Direction | Purpose | Operational guide |
|---|---|---|---|---|
| **ALF** | `pm-alf-gwy` | Order entry (in) | Text order entry for external bots and remote clients, over a plain TCP socket | [ALF TCP Gateway](220-alf-gateway.md) |
| **BALF** | `pm-balf-gwy` | Order entry (in) | Binary, low-latency order entry for programmatic clients | [BALF TCP Gateway](230-balf-gateway.md) |
| **CALF** | `pm-md-gwy` | Market data (out) | Subscribe/unsubscribe market-data feed: order-book snapshots, trade prints, session-state changes | [Market Data Feed (CALF)](240-calf-gateway.md) |
| **RALF** | `pm-ralf-gwy` | Post-trade (out) | Replayable audit feed of executed trades for clearing, drop-copy, and audit consumers | [Post-Trade Dissemination (RALF)](250-ralf-gateway.md) |
| **DC1** | `pm-dc-gwy` | Drop copy (out) | Relays the engine's internal drop-copy feed to plain TCP clients that cannot speak ZeroMQ | [Drop-Copy TCP Gateway](201-dc-gateway.md) |
| **LALF** | `pm-log-srv` | Logging (in), LALF-PS (out) | Collects operational logs from every other `pm-*` process; also distributes them to live log viewers | [Centralized Log Server](280-log-srv.md) |
| **REST/WebSocket** | `pm-api-gwy` | Order entry + market data | HTTP/JSON and WebSocket interface for browser and API-native clients | [API Gateway](260-api-gateway.md) |

!!! note "`pm-alf-console` is not in this table"
    `pm-alf-console`, the interactive trading terminal used throughout this
    guide's examples, is deliberately absent from this list: it connects
    directly to the engine's internal ZeroMQ bus instead of terminating a TCP
    port, so it does not fit the definition of a gateway above. See
    [`pm-alf-console` — Interactive ALF Trading Terminal](055-alf-console.md)
    for what it is instead, and [ALF TCP Gateway](220-alf-gateway.md) for the
    process that *is* the real ALF gateway.

Each protocol's configuration lives in a different part of `engine_config.yaml`:

- **ALF** — configured under `gateways.alf`; used by `pm-engine` to authenticate order-entry connections from `pm-alf-console` and `pm-alf-gwy`, as well as `pm-balf-gwy` (the gateway id used in the BALF configurations must exist under `gateways.alf`).
  Uses a pipe-delimited text format (`FIELD=VALUE|FIELD=VALUE`).
- **BALF** — configured under the top-level `balf_gateway` key; used by `pm-balf-gwy`. Uses fixed-width binary frames with sequence numbers and integer-scaled prices, targeting programmatic clients where text-parsing overhead is undesirable.
- **CALF** — configured under the top-level `market_data_gateway` key; used by `pm-md-gwy`. Provides a subscribe/unsubscribe market-data feed delivering order-book snapshots, trade prints, and session-state changes over a persistent TCP connection with sequence-based gap detection.
- **RALF** — configured under the top-level `post_trade_gateway` key; used by `pm-ralf-gwy`. Provides a replayable audit feed of all executed trades, including the original order details, over a persistent TCP connection with sequence-based gap detection.
- **DC1** — configured under the top-level `dc_gateway` key; used by `pm-dc-gwy`. Relays the engine's internal drop-copy feed to plain TCP clients that cannot speak ZeroMQ, using the lightweight DC1 text protocol.
- **LALF** — configured under the top-level `log_server` key; used by `pm-log-srv`. Collects operational `logging`-module output from every other `pm-*` process over a persistent TCP connection into a queryable SQLite database. The same key also configures **LALF-PS**, the ZeroMQ `PUB`/`PULL` interface that distributes those rows back out to live log viewers.

See [Configuration](010-configuration.md) for the full field-by-field schema of
each gateway's configuration block, and [External Protocols Overview](210-protocols-overview.md)
for a protocol-centric comparison of ALF, BALF, CALF, and RALF.

## One user per gateway — a learning simplification

EduMatcher maps one gateway process to one user.  In a real exchange, the
relationship between gateways, users, and legal entities has several layers:

```
Exchange
  └─ Member firm  (legal entity; signed exchange rules; financial responsibility)
       ├─ Participant  (trading desk or system within the firm)
       │    ├─ User  (individual trader or algorithm)
       │    └─ User
       └─ Participant
            └─ User
```

A single FIX session (one TCP connection to the exchange) can carry orders for
many users in the same firm, tagged with a `SenderSubID` or `Account` field to
identify the individual.  Risk limits may be set at the firm level, the desk
level, or the individual user level.  Pre-trade checks (position limits, fat-finger
checks, credit checks) can be applied independently at each layer.

EduMatcher collapses all of this:

- There is no concept of a member firm or legal entity.
- There is no concept of a "user" separate from the gateway.
- The gateway ID (`--id GW01`) is the only identity the engine knows.
- All orders from `GW01` are treated as one account for position tracking and
  self-match prevention purposes.

This makes the system much easier to learn and operate, at the cost of the
access-control and risk-management structures that real venues require.

## Multiple gateways and arrival order

When two gateways submit orders at almost the same moment, the engine processes
them in the order the messages arrive at its PULL socket.  On localhost with
ZeroMQ, this is effectively FIFO — but only at the network level, not at the
wall-clock level of the original submission.

In production this is a critical fairness issue:

- Two orders submitted at the same microsecond by two different participants on
  opposite sides of a co-location facility do not arrive at the engine at the
  same time.
- The order that traverses fewer network hops, or whose gateway server sits
  closer to the matching engine, will arrive first.
- This is the economics behind **co-location** services: participants pay to
  place their servers in the same data centre as the exchange, minimising the
  physical distance their messages travel.

**Legal fairness obligations**

Regulated exchanges are legally required to treat all participants fairly and
without discrimination.  In practice this means:

- **Deterministic FIFO processing**: the engine must process messages in the
  exact sequence they are received; it cannot re-order them for any reason.
- **No preferential access**: the exchange must offer the same co-location
  facilities and network connections to any participant willing to pay the
  published fee.
- **Timestamping**: many regulators (MiFID II in Europe, FINRA/SEC in the US)
  require the exchange to log a nanosecond-precision hardware timestamp
  ("gateway receipt timestamp") on every inbound message and include it in
  execution reports.  This creates an auditable record of arrival order that
  can be reviewed by regulators after any suspicious trading pattern.
- **Speed bumps**: some venues (IEX, Cboe EDGA) deliberately introduce a short
  delay (350 microseconds for IEX's "Magic Shoebox") on certain order types to
  level the playing field between speed-optimised HFT and slower participants.

EduMatcher has none of these mechanisms.  The engine processes messages in
ZeroMQ arrival order with no timestamps beyond the wall clock of the machine
running the test.  For a learning system on localhost this is irrelevant; for a
regulated venue it would be a *compliance failure*.

## See also

- [`pm-alf-console` — Interactive ALF Trading Terminal](055-alf-console.md) — the learning/demo ALF client, and why it is not itself a gateway
- [External Protocols Overview](210-protocols-overview.md) — ALF/BALF/CALF/RALF compared side by side
- [ALF TCP Gateway](220-alf-gateway.md) — the real ALF gateway for external bots and remote clients
- [BALF TCP Gateway](230-balf-gateway.md)
- [Market Data Feed (CALF)](240-calf-gateway.md)
- [Post-Trade Dissemination (RALF)](250-ralf-gateway.md)
- [Drop-Copy TCP Gateway (pm-dc-gwy)](201-dc-gateway.md)
- [Centralized Log Server](280-log-srv.md)
- [API Gateway](260-api-gateway.md)
- [Configuration — ALF Gateway Allowlist](010-configuration.md#alf-gateway-allowlist) — how gateway IDs, roles, and disconnect behavior are configured

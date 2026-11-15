# RALF Protocol Reference

> **Status: Normative.** This appendix is the single source of truth for the RALF
> wire contract as implemented by `pm-ralf-gwy` (`ralf_gateway/`). For an operational,
> tutorial-style guide see [Post-Trade Dissemination](../../operator-guide/part-5-gateways/040-ralf-gateway.md); for the
> gateway's configuration block see
> [Engine Config Specification §6.4](../../reference-manual/part-3-configuration/030-formal-specification.md#64-post_trade_gateway-pm-ralf-gwy-ralf).

## 1. What RALF is

**RALF** (Reconciliation ALF) is EduMatcher's **text post-trade dissemination**
protocol. It streams executed-trade and end-of-day events over TCP to external
back-office consumers (clearing, drop-copy, audit). It is served by `pm-ralf-gwy`,
which subscribes to the engine event bus and re-publishes derived events as RALF
lines. RALF is **read-only**: clients subscribe and receive; they never submit orders.

## 2. Scope & conformance

This document defines the client-visible wire behaviour of RALF version token
`RALF1`: framing, message set, fields, roles, sequencing, timeouts, and errors. The
key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are used per RFC 2119.
A conforming client or gateway MUST implement the message set in §6 with the field
constraints in §6 and §10. Behaviour not stated here is unspecified.

## 3. Transport & session model

| Property | Value |
|----------|-------|
| Transport | TCP |
| Default port | `5580` (`post_trade_gateway.port`) |
| Encoding | UTF-8 text lines |
| Delimiter | `\n` |
| Max line length | 4096 bytes including newline |
| Version token | `RALF1` |
| Connection model | long-lived, one authenticated session per connection |
| Direction | gateway → client for all data; client → gateway for control only |

A session proceeds: **connect → `HELLO` → `WELCOME` → one or more `SUB`/`UNSUB` →
event stream + heartbeats → `EXIT`/disconnect**. A client MUST send `HELLO` before
any other message; a non-`HELLO` first message is rejected with
`ERR|CODE=AUTH_REQUIRED`. A connection that sends no `HELLO` within 5 seconds
receives `EXIT|REASON=auth_timeout` and is closed. Once the gateway has sent
the line that ends a session, it ignores anything more the client sends.

A client that closes its sending side (a TCP half-close, as
`printf 'HELLO|…\nSUB|…\n' | nc host 5580` does once its input ends) ends the
session: the gateway disconnects it when it reads the end of input, so it
receives only what was already sent. A read-only client MUST keep its
sending side open — the same rule as in `pm-md-gwy` and `pm-dc-gwy`.

## 4. Wire format

Every message is one line:

```text
MSGTYPE|KEY=VALUE|KEY=VALUE|...\n
```

- `MSGTYPE` MUST be uppercase ASCII from `A-Z`, `0-9`, `_`.
- Fields are `|`-delimited; each field is split into key/value on the **first** `=`.
- A parser MUST ignore unknown fields (forward compatibility) except where a field
  is required for validation.
- Values do not contain `|` or `\n`.
- Field order is not significant: a parser MUST look fields up by key. (The
  gateway appends `SEQ` last; the examples in this document may show it
  elsewhere.)

**Reserved cross-message keys** (present on most messages):

| Key | Meaning |
|-----|---------|
| `CH` | Channel: `CLEARING`, `DROP_COPY`, or `AUDIT` |
| `SYM` | Symbol filter (control) or event symbol (data); `*` = all |
| `SEQ` | Channel-local monotonic message sequence (see §8) |
| `TS` | UTC ISO-8601 timestamp with milliseconds and `Z` suffix |

## 5. Message catalog

| Message | Direction | Purpose |
|---------|-----------|---------|
| `HELLO` | client → gw | open session; authenticate role; optional replay checkpoint |
| `WELCOME` | gw → client | session accepted; negotiated parameters |
| `SUB` | client → gw | subscribe channel(s) × symbol scope |
| `UNSUB` | client → gw | remove subscriptions |
| `SNAP` | gw → client | subscription/recovery baseline (carries current `SEQ`) |
| `EXEC` | gw → client | one executed trade (post-trade view) |
| `EOD` | gw → client | per-symbol summary when the engine stops (§6) |
| `HB` | gw → client | heartbeat every `HBINT` seconds |
| `PING` / `PONG` | client → gw / gw → client | liveness probe and reply |
| `EXIT` | both | from the gateway: session terminated, with `REASON` (e.g. `idle_timeout`); from the client: close after flushing |
| `ERR` | gw → client | protocol, entitlement, or replay error |

## 6. Message definitions

### `HELLO` (client → gateway)

| Field | Type | Req | Constraints |
|-------|------|:---:|-------------|
| `CLIENT` | string | ✔ | external client identifier (logging) |
| `PROTO` | string | ✔ | MUST equal `RALF1` |
| `ROLE` | enum | ✔ | one of `CLEARING`, `DROP_COPY`, `AUDIT`; MUST be in the gateway's `allowed_roles` |
| `LASTSEQ` | int | – | replay checkpoint; requests events with `SEQ > LASTSEQ` (see §8) |
| `EPOCH` | string | with `LASTSEQ > 0` | the `WELCOME\|EPOCH` of the gateway run `LASTSEQ` came from (see §8) |

Missing `CLIENT`/`PROTO`/`ROLE` → `ERR|CODE=AUTH_REQUIRED`. A `ROLE` outside
`allowed_roles` → `ERR|CODE=ENTITLEMENT_DENIED`. A non-integer `LASTSEQ`, or a
`LASTSEQ` above 0 without `EPOCH` → `ERR|CODE=BAD_MESSAGE`; each ends the session.

### `WELCOME` (gateway → client)

| Field | Meaning |
|-------|---------|
| `PROTO` | negotiated version (`RALF1`) |
| `GW` | gateway id (`post_trade_gateway.name`) |
| `EPOCH` | this gateway run's identity: 8 hex digits, new at every start of `pm-ralf-gwy`; store it with the checkpoint |
| `ROLE` | accepted role |
| `REPLAY` | replay retention window, seconds (`replay_retention_sec`) |
| `HBINT` | heartbeat interval, seconds (`heartbeat_interval_sec`) |

### `SUB` / `UNSUB` (client → gateway)

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `CH` | csv of channels | ✔ | — | each ∈ {`CLEARING`,`DROP_COPY`,`AUDIT`}; entitlement checked (§7) |
| `SYM` | csv of symbols or `*` | – | `*` | scope filter |

A subscription is the set of `(channel, symbol)` pairs. `SUB` is cumulative; `UNSUB`
removes exactly the pairs it names and is idempotent (`UNSUB` of one symbol does not
narrow a `SYM=*` pair). After a `SUB`, the gateway emits one `SNAP`;
in a session whose `HELLO` carried a checkpoint, the replay for the pairs the `SUB`
added (or `ERR|CODE=REPLAY_MISS`) comes first, in the same reply (§8).
A missing/empty `CH` → `ERR|CODE=INVALID_CHANNEL`; an unknown channel →
`ERR|CODE=INVALID_CHANNEL`; a channel the role may not access →
`ERR|CODE=ENTITLEMENT_DENIED`.

### `SNAP` (gateway → client)

Baseline emitted after a `SUB` and on replay-miss recovery. Carries `CH` (the
subscribed channels, comma-joined), `SYM`, `SEQ` (the highest current sequence over
the `CH` set in that `SNAP`), and `TS`. RALF `SNAP` carries **no book/position
state** — it is a sequence baseline only.

### `EXEC` (gateway → client)

One line per executed trade, per subscribed channel.

| Field | Description |
|-------|-------------|
| `CH` `SYM` `SEQ` `TS` | envelope (§4) |
| `EXEC_ID` | execution id (engine trade id) |
| `MATCH_ID` | match id — **identical to `EXEC_ID`** in `RALF1` |
| `BUY_ORDER_ID` / `SELL_ORDER_ID` | resting/aggressing order ids |
| `BUY_GW` / `SELL_GW` | buy-side / sell-side gateway ids |
| `SIDE` | aggressor side (`BUY`/`SELL`); `AUCTION` for an uncross print, where both sides rested |
| `QTY` | executed quantity |
| `PX` | execution price (display units) |

A single trade is emitted **once per channel** (`CLEARING`, `DROP_COPY`, `AUDIT`),
each copy consuming its own `SEQ` (§8).

### `EOD` (gateway → client)

Per-symbol summary, derived from the engine `system.eod` broadcast. The engine
sends that broadcast in its shutdown sequence, whenever it stops (mid-session
included), not at a fixed end of the trading day; a killed engine sends none.

| Field | Description |
|-------|-------------|
| `CH` `SYM` `SEQ` | envelope |
| `TS` | when the gateway received `system.eod` (the broadcast carries no time) |
| `TRADE_COUNT` | trades for the symbol that **this gateway run** disseminated since it started or since its previous `EOD` (the counter resets to zero at every `EOD` and when `pm-ralf-gwy` restarts). It counts the `EXEC` lines sent, so trades lost before the gateway are not in it |
| `EXEC_COUNT` | execution count — **identical to `TRADE_COUNT`** in `RALF1` |

`EOD` is emitted once per symbol on all three channels:
`CLEARING`, `DROP_COPY`, and `AUDIT`.

### `HB`, `PING`/`PONG`, `EXIT`

`HB|TS=…` is sent to every authenticated client every `HBINT` seconds. A client
MAY send `PING`; the gateway replies `PONG|TS=…`. `EXIT|REASON=…|TS=…` signals
gateway-initiated termination (`idle_timeout`, `auth_timeout`, or `shutdown`
when `pm-ralf-gwy` is stopped: lines already queued are sent before it, for up
to 1 s). A client MAY send
a bare `EXIT` to end its session; the gateway closes after flushing — as
`pm-md-gwy` and `pm-dc-gwy` do.

## 7. Roles & entitlements

Roles and channels share the same three names. Entitlement rules:

| Role | May subscribe to |
|------|------------------|
| `CLEARING` | `CLEARING` only |
| `DROP_COPY` | `DROP_COPY` only |
| `AUDIT` | **any** channel (`CLEARING`, `DROP_COPY`, `AUDIT`) |

A role subscribing outside its entitlement receives `ERR|CODE=ENTITLEMENT_DENIED`.
Only roles listed in `post_trade_gateway.allowed_roles` may authenticate.

## 8. Sequencing & recovery

`SEQ` is maintained **per channel** (`CLEARING`, `DROP_COPY`, `AUDIT`).

- Within one channel, `SEQ` is strictly increasing by 1 per emitted line.
- Across different channels, `SEQ` values are independent and are not globally
  ordered or globally unique.
- Clients MUST do gap detection and ordering **within a given `CH` stream**, not
  across mixed channels.
- A `SEQ` jump is a gap only on a `SYM=*` subscription: with a symbol filter,
  the channel's `SEQ` also moves for every other symbol's events. A filtered
  client still keeps the last `SEQ` as its replay checkpoint.
- The gateway numbers what it emits: an engine message that never reached the
  gateway leaves no gap in any channel. The gateway counts such losses for the
  operator (`gwy.bus_gaps`); they cannot be replayed.

Sequences and the replay journal live in the gateway's memory: they begin again
at 1 when `pm-ralf-gwy` restarts. `WELCOME|EPOCH` names the run, and a checkpoint
is the pair (`EPOCH`, `LASTSEQ`). A client that resumes MUST send both; a
checkpoint from another run is a `REPLAY_MISS` whatever its `LASTSEQ`.

`LASTSEQ` in `HELLO` is a single integer checkpoint. The gateway applies that same
threshold to each channel independently and replays events where
`event.SEQ > LASTSEQ` for that event's channel.

**Replay.** `HELLO` only records the checkpoint; `WELCOME` is followed by nothing
until the client subscribes. Each `SUB` then answers, in this order and in one
pass, so no event falls between them:

1. the journalled events with `SEQ > LASTSEQ` that the pairs this `SUB` added
   want and the session's earlier pairs did not (so a channel is replayed once,
   and only the subscribed symbols), in journal order;
2. the `SNAP`, whose `SEQ` is the last of them; live events follow it.

If the checkpoint's `EPOCH` is not this run's, or `LASTSEQ` predates the retained
journal window (`replay_retention_sec`) for a channel of the `SUB` — including a
channel whose journal has aged out entirely — or is ahead of one, the `SUB` is
answered with `ERR|CODE=REPLAY_MISS` and then its `SNAP`; the client MUST reset to
that baseline. A `HELLO` with a checkpoint and no `SUB` receives nothing beyond
`WELCOME` (and heartbeats): nothing was subscribed.

Replayed lines do not count towards `max_client_queue` (§9): a client that resumes
from far back is not a slow client while it takes the replay.

## 9. Liveness & timeouts

| Parameter | Source | Default |
|-----------|--------|---------|
| Heartbeat interval (`HBINT`) | `heartbeat_interval_sec` | 2 s |
| Idle timeout | `idle_timeout_sec` | 20 s |
| Replay retention (`REPLAY`) | `replay_retention_sec` | 86400 s |

The gateway sends `HB` to every authenticated client every heartbeat interval,
whether or not other lines were sent in between. The idle timeout counts traffic
in **both** directions — a line received, or a line the client actually took
off the socket — so a client that keeps reading is never idle: the heartbeats
alone keep it alive. In practice the idle timeout fires only when writes to a
client have stopped succeeding; it then sends `EXIT|REASON=idle_timeout`. A client whose outbound queue exceeds
`max_client_queue` beyond the replayed lines it has still to take (§8) receives
`ERR|CODE=SLOW_CLIENT` and is disconnected.

## 10. Error codes

| Code | Meaning / trigger |
|------|-------------------|
| `AUTH_REQUIRED` | first message was not `HELLO`, or `HELLO` missing `CLIENT`/`PROTO`/`ROLE` |
| `BAD_MESSAGE` | unparseable line, unsupported message type, or malformed field (e.g. non-integer `LASTSEQ`, or `LASTSEQ` without `EPOCH`; both end the session); an oversized line (`DETAIL=line exceeds 4096 bytes`) also ends the session |
| `INVALID_CHANNEL` | `SUB` with missing/empty or unknown `CH` |
| `ENTITLEMENT_DENIED` | role not in `allowed_roles`, or channel outside the role's entitlement |
| `REPLAY_MISS` | the checkpoint's `EPOCH` is not this gateway run's, or `LASTSEQ` is older than the retained journal window or ahead of the channel |
| `SLOW_CLIENT` | outbound queue exceeded `max_client_queue`; session disconnected |

`ERR` carries `CODE` and a human-readable `DETAIL`, e.g.
`ERR|CODE=REPLAY_MISS|DETAIL=requested seq outside retention`.

## 11. Configuration reference

`pm-ralf-gwy` reads the `post_trade_gateway` block of `engine_config.yaml`
(consumed only by this process). Full field law is in
[Engine Config Specification §6.4](../../reference-manual/part-3-configuration/030-formal-specification.md#64-post_trade_gateway-pm-ralf-gwy-ralf).

| Key | Default | Purpose |
|-----|---------|---------|
| `name` | `ralf-gwy01` | gateway id in `WELCOME\|GW=`; non-empty, without `\|` or line breaks |
| `bind_address` | `0.0.0.0` | TCP listen address |
| `port` | `5580` | TCP listen port |
| `replay_retention_sec` | `86400` | journal window; advertised as `WELCOME\|REPLAY=` |
| `heartbeat_interval_sec` | `2` | `HB` cadence; advertised as `WELCOME\|HBINT=` |
| `idle_timeout_sec` | `20` | disconnect after this long with no traffic in either direction |
| `max_connections` | `64` | simultaneous TCP connections; one beyond this is accepted and closed at once |
| `max_client_queue` | `10000` | outbound backlog before `SLOW_CLIENT` |
| `allowed_roles` | `[CLEARING, DROP_COPY, AUDIT]` | roles permitted to authenticate; a non-empty list of those three |

## 12. Conformance notes

A conforming `RALF1` implementation:

- derives events solely from engine broadcasts: `trade.executed` → `EXEC`,
  `system.eod` → `EOD`. No other event families exist in `RALF1`.
- MUST send `HELLO`/`WELCOME` before any data; MUST reject pre-auth data with
  `AUTH_REQUIRED`.
- MUST enforce the §7 entitlement matrix on `SUB` (live path).
- MUST apply per-channel `SEQ` semantics from §8 (no global `SEQ` stream).
- MUST advertise `REPLAY`/`HBINT` in `WELCOME` matching its configuration.
- MUST replay on `SUB`, for the pairs that `SUB` adds, before its `SNAP` (§8).

Future revisions may add `CORRECT`, `BUST`, `ALLOC`, and `SETTLE` event families as
the corresponding engine events become available; they are **not** part of `RALF1`.

## See also

**In this book:**

- [RALF Protocol Spy (pm-ralf-spy)](../part-4-writing-clients/040-the-spy-tools-ralf.md) — read-only CLI for inspecting the live wire format
- [External Protocols Overview](../part-1-choosing-and-connecting/010-protocols-overview.md) — ALF/BALF/CALF/RALF at a glance

**Operator's Guide:**

- [Post-Trade Dissemination](../../operator-guide/part-5-gateways/040-ralf-gateway.md) — operational guide and client examples

**Reference Manual:**

- [Processes, Environment, and Ports](../../reference-manual/part-1-command-line/010-processes-environment-and-ports.md) — where `pm-ralf-gwy` sits
- [Engine Config Specification](../../reference-manual/part-3-configuration/030-formal-specification.md#64-post_trade_gateway-pm-ralf-gwy-ralf) — `post_trade_gateway` field law

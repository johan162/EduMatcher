# Appendix: RALF Protocol Reference

> **Status: Normative.** This appendix is the single source of truth for the RALF
> wire contract as implemented by `pm-ralf-gwy` (`ralf_gateway/`). For an operational,
> tutorial-style guide see [Post-Trade Dissemination](18-post-trade.md); for the
> gateway's configuration block see
> [Engine Config Specification §6.4](99-app-config-spec.md#64-post_trade_gateway-pm-ralf-gwy-ralf).

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
constraints in §6 and §10. Behaviour not stated here is unspecified. Where the
current implementation deviates from what a robust protocol would require, the
deviation is called out with a **⚠ Known deviation** note and tracked in the
project's suspected-bugs report.

## 3. Transport & session model

| Property | Value |
|----------|-------|
| Transport | TCP |
| Default port | `5580` (`post_trade_gateway.port`) |
| Encoding | UTF-8 text lines |
| Delimiter | `\n` |
| Version token | `RALF1` |
| Connection model | long-lived, one authenticated session per connection |
| Direction | gateway → client for all data; client → gateway for control only |

A session proceeds: **connect → `HELLO` → `WELCOME` → one or more `SUB`/`UNSUB` →
event stream + heartbeats → `EXIT`/disconnect**. A client MUST send `HELLO` before
any other message; a non-`HELLO` first message is rejected with
`ERR|CODE=AUTH_REQUIRED`.

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

**Reserved cross-message keys** (present on most messages):

| Key | Meaning |
|-----|---------|
| `CH` | Channel: `CLEARING`, `DROP_COPY`, or `AUDIT` |
| `SYM` | Symbol filter (control) or event symbol (data); `*` = all |
| `SEQ` | Global monotonic message sequence (see §8) |
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
| `EOD` | gw → client | end-of-day per-symbol summary marker |
| `HB` | gw → client | heartbeat when the stream is quiet |
| `PING` / `PONG` | client → gw / gw → client | liveness probe and reply |
| `EXIT` | gw → client | session terminated (e.g. idle timeout) |
| `ERR` | gw → client | protocol, entitlement, or replay error |

## 6. Message definitions

### `HELLO` (client → gateway)

| Field | Type | Req | Constraints |
|-------|------|:---:|-------------|
| `CLIENT` | string | ✔ | external client identifier (logging) |
| `PROTO` | string | ✔ | MUST equal `RALF1` |
| `ROLE` | enum | ✔ | one of `CLEARING`, `DROP_COPY`, `AUDIT`; MUST be in the gateway's `allowed_roles` |
| `LASTSEQ` | int | – | replay checkpoint; requests events with `SEQ > LASTSEQ` (see §8) |

Missing `CLIENT`/`PROTO`/`ROLE` → `ERR|CODE=AUTH_REQUIRED`. A `ROLE` outside
`allowed_roles` → `ERR|CODE=ENTITLEMENT_DENIED`. A non-integer `LASTSEQ` →
`ERR|CODE=BAD_MESSAGE`.

### `WELCOME` (gateway → client)

| Field | Meaning |
|-------|---------|
| `PROTO` | negotiated version (`RALF1`) |
| `GW` | gateway id (`post_trade_gateway.name`) |
| `ROLE` | accepted role |
| `REPLAY` | replay retention window, seconds (`replay_retention_sec`) |
| `HBINT` | heartbeat interval, seconds (`heartbeat_interval_sec`) |

### `SUB` / `UNSUB` (client → gateway)

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `CH` | csv of channels | ✔ | — | each ∈ {`CLEARING`,`DROP_COPY`,`AUDIT`}; entitlement checked (§7) |
| `SYM` | csv of symbols or `*` | – | `*` | scope filter |

A subscription is the set of `(channel, symbol)` pairs. `SUB` is cumulative; `UNSUB`
removes matching pairs and is idempotent. After a `SUB`, the gateway emits one `SNAP`.
A missing/empty `CH` → `ERR|CODE=INVALID_CHANNEL`; an unknown channel →
`ERR|CODE=INVALID_CHANNEL`; a channel the role may not access →
`ERR|CODE=ENTITLEMENT_DENIED`.

### `SNAP` (gateway → client)

Baseline emitted after a `SUB` and on replay-miss recovery. Carries `CH` (the
subscribed channels, comma-joined), `SYM`, `SEQ` (the current global high-water
sequence), and `TS`. RALF `SNAP` carries **no book/position state** — it is a
sequence baseline only: store its `SEQ` as the starting point for gap tracking.

### `EXEC` (gateway → client)

One line per executed trade, per subscribed channel.

| Field | Description |
|-------|-------------|
| `CH` `SYM` `SEQ` `TS` | envelope (§4) |
| `EXEC_ID` | execution id (engine trade id) |
| `MATCH_ID` | match id — **identical to `EXEC_ID`** in `RALF1` |
| `BUY_ORDER_ID` / `SELL_ORDER_ID` | resting/aggressing order ids |
| `BUY_GW` / `SELL_GW` | buy-side / sell-side gateway ids |
| `SIDE` | aggressor side (`BUY`/`SELL`) |
| `QTY` | executed quantity |
| `PX` | execution price (display units) |

A single trade is emitted **once per channel** (`CLEARING`, `DROP_COPY`, `AUDIT`),
each copy consuming its own `SEQ` (§8).

### `EOD` (gateway → client)

Per-symbol end-of-day marker, derived from the engine `system.eod` broadcast.

| Field | Description |
|-------|-------------|
| `CH` `SYM` `SEQ` `TS` | envelope |
| `TRADE_COUNT` | trades seen for the symbol this session |
| `EXEC_COUNT` | execution count — **identical to `TRADE_COUNT`** in `RALF1` |

`EOD` is emitted on the `CLEARING` and `AUDIT` channels **only** — it is **not**
disseminated on `DROP_COPY`.

### `HB`, `PING`/`PONG`, `EXIT`

`HB|TS=…` is sent to authenticated clients when the stream is otherwise quiet
(cadence `HBINT`). A client MAY send `PING`; the gateway replies `PONG|TS=…`.
`EXIT|REASON=…|TS=…` signals gateway-initiated termination (e.g. `idle_timeout`).

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

`SEQ` is a **single global monotonic counter** for the gateway, incremented once per
**emitted line**. Because a trade is emitted once per channel (§6), consecutive
`SEQ` values span channels.

!!! warning "⚠ Known deviation — SEQ is not contiguous within one channel"
    A client subscribed to a single channel receives a **non-contiguous** `SEQ`
    stream (values increase but skip the sequence numbers spent on other channels'
    copies). A naive "gap when `received_seq != last_seq + 1`" check will therefore
    **false-positive**. Clients SHOULD treat `SEQ` as strictly increasing but not
    dense. (A per-`(channel)` sequence would remove this; tracked as a suspected
    implementation issue.)

**Replay.** If `HELLO` carries `LASTSEQ`, the gateway attempts to resend journalled
events with `SEQ > LASTSEQ`. If `LASTSEQ` predates the retained journal window
(`replay_retention_sec`), the gateway emits `ERR|CODE=REPLAY_MISS` followed by a
`SNAP` baseline; the client MUST reset to that baseline.

!!! warning "⚠ Known deviation — replay is not entitlement/subscription filtered"
    The current replay path resends the **entire** journal for `SEQ > LASTSEQ`,
    regardless of the reconnecting client's role or subscriptions. A `CLEARING`
    client can thus receive `DROP_COPY`/`AUDIT` event lines on reconnect. Treat this
    as a known issue; a conforming gateway SHOULD filter replay by the session's
    entitlement and subscriptions exactly as live delivery does.

## 9. Liveness & timeouts

| Parameter | Source | Default |
|-----------|--------|---------|
| Heartbeat interval (`HBINT`) | `heartbeat_interval_sec` | 1 s |
| Idle timeout | `idle_timeout_sec` | 5 s |
| Replay retention (`REPLAY`) | `replay_retention_sec` | 86400 s |

The gateway sends `HB` when no other line has been sent within the heartbeat
interval. A session with no inbound activity for the idle timeout is dropped
(`EXIT|REASON=idle_timeout`). A client whose outbound queue exceeds
`max_client_queue` receives `ERR|CODE=SLOW_CLIENT` and is disconnected.

## 10. Error codes

| Code | Meaning / trigger |
|------|-------------------|
| `AUTH_REQUIRED` | first message was not `HELLO`, or `HELLO` missing `CLIENT`/`PROTO`/`ROLE` |
| `BAD_MESSAGE` | unparseable line, unsupported message type, or malformed field (e.g. non-integer `LASTSEQ`) |
| `INVALID_CHANNEL` | `SUB` with missing/empty or unknown `CH` |
| `ENTITLEMENT_DENIED` | role not in `allowed_roles`, or channel outside the role's entitlement |
| `REPLAY_MISS` | requested `LASTSEQ` is older than the retained journal window |
| `SLOW_CLIENT` | outbound queue exceeded `max_client_queue`; session disconnected |

`ERR` carries `CODE` and a human-readable `DETAIL`, e.g.
`ERR|CODE=REPLAY_MISS|DETAIL=requested seq outside retention`.

## 11. Configuration reference

`pm-ralf-gwy` reads the `post_trade_gateway` block of `engine_config.yaml`
(consumed only by this process). Full field law is in
[Engine Config Specification §6.4](99-app-config-spec.md#64-post_trade_gateway-pm-ralf-gwy-ralf).

| Key | Default | Purpose |
|-----|---------|---------|
| `name` | `ralf-gwy01` | gateway id in `WELCOME\|GW=` |
| `bind_address` | `0.0.0.0` | TCP listen address |
| `port` | `5580` | TCP listen port |
| `replay_retention_sec` | `86400` | journal window; advertised as `WELCOME\|REPLAY=` |
| `heartbeat_interval_sec` | `1` | `HB` cadence; advertised as `WELCOME\|HBINT=` |
| `idle_timeout_sec` | `5` | inbound-idle disconnect |
| `max_client_queue` | `10000` | outbound backlog before `SLOW_CLIENT` |
| `allowed_roles` | `[CLEARING, DROP_COPY, AUDIT]` | roles permitted to authenticate |

## 12. Conformance notes

A conforming `RALF1` implementation:

- derives events solely from engine broadcasts: `trade.executed` → `EXEC`,
  `system.eod` → `EOD`. No other event families exist in `RALF1`.
- MUST send `HELLO`/`WELCOME` before any data; MUST reject pre-auth data with
  `AUTH_REQUIRED`.
- MUST enforce the §7 entitlement matrix on `SUB` (live path).
- MUST advertise `REPLAY`/`HBINT` in `WELCOME` matching its configuration.
- treats `SEQ` as strictly increasing (see the §8 deviations for the contiguity and
  replay-filtering caveats a production revision should close).

Future revisions may add `CORRECT`, `BUST`, `ALLOC`, and `SETTLE` event families as
the corresponding engine events become available; they are **not** part of `RALF1`.

## See also

- [Post-Trade Dissemination](18-post-trade.md) — operational guide and client examples
- [Processes](10-processes.md#pm-ralf-gwy-post-trade-dissemination-gateway) — where `pm-ralf-gwy` sits
- [Engine Config Specification](99-app-config-spec.md#64-post_trade_gateway-pm-ralf-gwy-ralf) — `post_trade_gateway` field law
- [External Protocols Overview](19-protocol-overview.md) — ALF/BALF/CALF/RALF at a glance

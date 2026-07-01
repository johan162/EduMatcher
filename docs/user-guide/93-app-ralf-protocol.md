# Appendix: RALF Protocol Reference

!!! note "Learning objectives"
    After reading this appendix you will understand:

    - the exact `RALF` wire format and message grammar
    - handshake and subscription flow for external post-trade consumers
    - required fields for core lifecycle messages (`EXEC`, `EOD`)
    - replay and error semantics for reconnect behavior


## What RALF is

**RALF** stands for **Reconciliation ALF**.

RALF is EduMatcher's text post-trade dissemination protocol, delivered over TCP
by `pm-ralf-gwy`.

!!! info "Runtime support"
    `RALF` is supported through the running `pm-ralf-gwy` process. External
    clients use this protocol by opening a TCP connection to `pm-ralf-gwy`.

| Protocol | Purpose                      |
|----------|------------------------------|
| ALF      | Interactive text order entry |
| BALF     | Binary order entry           |
| CALF     | Market-data dissemination    |
| RALF     | Post-trade dissemination     |

This appendix defines the client-visible behavior for `RALF`.


## Transport and session model

| Property         | Value                         |
|------------------|-------------------------------|
| Transport        | TCP                           |
| Default port     | `5580`                        |
| Encoding         | UTF-8 text lines              |
| Delimiter        | `\n`                          |
| Connection model | Long-lived per-client session |

Session sequence:

1. Client connects
2. Client sends `HELLO`
3. Gateway sends `WELCOME`
4. Client sends one or more `SUB`/`UNSUB`
5. Gateway streams events and heartbeats


## Wire grammar

Each message is a single line:

```text
<MSGTYPE>|KEY=VALUE|KEY=VALUE|...\n
```

Rules:

- `MSGTYPE` is uppercase ASCII (`A-Z`, `0-9`, `_`)
- fields are pipe-delimited
- key-value pairs are split on first `=`
- unknown fields are ignored unless required for validation

Reserved cross-message keys:

| Key   | Meaning                                    |
|-------|--------------------------------------------|
| `CH`  | Channel (`CLEARING`, `DROP_COPY`, `AUDIT`) |
| `SYM` | Symbol filter or event symbol              |
| `SEQ` | Monotonic message sequence                 |
| `TS`  | UTC ISO-8601 timestamp                     |


## Roles and channels

Supported roles:

- `CLEARING`
- `DROP_COPY`
- `AUDIT`

Supported channels:

- `CLEARING`
- `DROP_COPY`
- `AUDIT`

A client subscribes by channel and symbol scope.


## Handshake messages

### `HELLO` (client -> gateway)

Required fields:

| Field    | Type   | Notes                      |
|----------|--------|----------------------------|
| `CLIENT` | string | External client identifier |
| `PROTO`  | string | Must be `RALF1`            |
| `ROLE`   | string | One of allowed roles       |

Optional fields:

| Field     | Type | Notes             |
|-----------|------|-------------------|
| `LASTSEQ` | int  | Replay checkpoint |

Example:

```text
HELLO|CLIENT=ccp01|PROTO=RALF1|ROLE=CLEARING|LASTSEQ=1200
```

### `WELCOME` (gateway -> client)

Fields:

| Field    | Description                           |
|----------|---------------------------------------|
| `PROTO`  | Negotiated protocol version (`RALF1`) |
| `GW`     | Gateway identifier                    |
| `ROLE`   | Accepted role                         |
| `REPLAY` | Replay retention (seconds)            |
| `HBINT`  | Heartbeat interval (seconds)          |


## Subscription messages

### `SUB`

Required fields:

| Field | Type                     |
|-------|--------------------------|
| `CH`  | Comma-separated channels |

Optional fields:

| Field | Type                           | Default |
|-------|--------------------------------|---------|
| `SYM` | Comma-separated symbols or `*` | `*`     |

Examples:

```text
SUB|CH=CLEARING|SYM=*
SUB|CH=DROP_COPY|SYM=AAPL,MSFT
SUB|CH=AUDIT|SYM=*
```

After `SUB`, gateway emits a `SNAP` confirmation line.

### `UNSUB`

Removes previously registered subscriptions.

Example:

```text
UNSUB|CH=DROP_COPY|SYM=AAPL
```


## Event messages

### `EXEC`

Live execution dissemination message.

Required fields in `RALF1` implementation:

| Field           | Description     |
|-----------------|-----------------|
| `CH`            | Channel         |
| `SYM`           | Symbol          |
| `SEQ`           | Sequence number |
| `TS`            | Timestamp       |
| `EXEC_ID`       | Execution id    |
| `MATCH_ID`      | Match id        |
| `BUY_ORDER_ID`  | Buy order id    |
| `SELL_ORDER_ID` | Sell order id   |
| `BUY_GW`        | Buy gateway id  |
| `SELL_GW`       | Sell gateway id |
| `SIDE`          | Aggressor side  |
| `QTY`           | Quantity        |
| `PX`            | Price           |

Example:

```text
EXEC|CH=CLEARING|SYM=AAPL|SEQ=42|TS=2026-06-19T09:30:01.234Z|EXEC_ID=123|MATCH_ID=123|BUY_ORDER_ID=b1|SELL_ORDER_ID=s1|BUY_GW=GW01|SELL_GW=GW02|SIDE=BUY|QTY=100|PX=150.25
```

### `EOD`

End-of-day summary marker.

Fields:

| Field         | Description     |
|---------------|-----------------|
| `CH`          | Channel         |
| `SYM`         | Symbol          |
| `SEQ`         | Sequence number |
| `TS`          | Timestamp       |
| `TRADE_COUNT` | Summary count   |
| `EXEC_COUNT`  | Summary count   |


## Session control messages

### `PING` / `PONG`

Liveness probe pair.

```text
PING|TS=2026-06-19T09:30:01.000Z
PONG|TS=2026-06-19T09:30:01.001Z
```

### `HB`

Heartbeat from gateway to authenticated clients.

```text
HB|TS=2026-06-19T09:30:02.000Z
```

### `EXIT`

Session shutdown / timeout signal.

```text
EXIT|REASON=idle_timeout|TS=2026-06-19T09:45:00.000Z
```

### `SNAP`

Subscription/recovery baseline message.


## Error handling

Gateway emits `ERR` for protocol and entitlement failures.

| Code                 | Meaning                                      |
|----------------------|----------------------------------------------|
| `AUTH_REQUIRED`      | Missing or invalid handshake sequence        |
| `BAD_MESSAGE`        | Parse/validation failure                     |
| `INVALID_CHANNEL`    | Unsupported channel requested                |
| `ENTITLEMENT_DENIED` | Role not permitted                           |
| `REPLAY_MISS`        | Requested replay point is outside retention  |
| `SLOW_CLIENT`        | Outbound queue exceeded configured threshold |

Example:

```text
ERR|CODE=REPLAY_MISS|DETAIL=requested seq outside retention
```


## Replay semantics

If `HELLO` includes `LASTSEQ`, gateway attempts replay for events where
`SEQ > LASTSEQ` from its in-memory journal window.

If replay is not possible due retention limits:

1. gateway emits `ERR|CODE=REPLAY_MISS`
2. gateway emits `SNAP` baseline hint


## Implementation notes

Current `RALF1` in EduMatcher is sourced from engine messages:

- `trade.executed` -> `EXEC`
- `system.eod` -> `EOD`

Future protocol revisions may add dedicated `CORRECT`, `BUST`, `ALLOC`, and
`SETTLE` event families as those internal events become available.


## See also

- [Post-Trade Dissemination](18-post-trade.md)
- [Processes](10-processes.md#pm-ralf-gwy-post-trade-dissemination-gateway)

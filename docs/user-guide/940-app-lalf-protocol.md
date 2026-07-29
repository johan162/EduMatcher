# Appendix: LALF Protocol Reference

> **Status: Normative.** This appendix is the single source of truth for the LALF
> `1` wire contract (`PROTO=LALF1`) as implemented by `pm-log-srv`
> (`edumatcher.log_srv`). For an operational, tutorial-style guide — how to
> start the server, how to use `pm-log-cli`, and worked query examples — see
> [Centralized Log Server](280-log-srv.md). The key words MUST, MUST NOT,
> SHOULD, SHOULD NOT, and MAY are used per RFC 2119. This appendix follows the
> same conventions as the normative [ALF Protocol Reference](900-app-alf-protocol.md)
> and [CALF Protocol Reference](920-app-calf-protocol.md), to which it should
> be read as a sibling, not a subset.



## What LALF is

**LALF** stands for **Logging ALF**.

LALF is EduMatcher's centralized-logging transport protocol: a small,
newline-delimited, line-oriented TCP protocol that every `pm-*` process can
use to ship its own operational log records to a single collector process,
`pm-log-srv`. Like its siblings, a LALF client establishes one long-lived TCP
connection, exchanges a `HELLO`/`WELCOME` handshake, and then streams typed,
`KEY=VALUE`-framed messages until the connection ends.

LALF complements the other application protocols:

| Protocol | Purpose                                       |
|----------|-----------------------------------------------|
| ALF      | Text order entry (interactive)                |
| BALF     | Binary order entry (low-latency programmatic) |
| CALF     | Channelized text market data                  |
| RALF     | Post-trade dissemination                      |
| LALF     | Centralized process logging                   |

LALF departs from its siblings in exactly one structural respect, required by
what it carries: every LALF client is a producer of exactly one thing — its
own process's log records — so LALF is unidirectional and subscription-free
where ALF/CALF/RALF are request/response or publish/subscribe. "Scope &
conformance" and "Wire format" below state precisely what this means for
conformance.

This appendix is the **normative reference** for LALF `1` semantics.



## Scope & conformance

LALF is the transport between any `pm-*` process and `pm-log-srv`, the
centralized log collector. It is not exposed to end users or external bots
the way CALF/ALF are — it exists purely so every process's logging lands in
one queryable place (`log.db`).

### Supported in LALF `1`

- One TCP connection per client process, carrying that process's own log
  records only, from `HELLO` to session end.
- Nine message types: `HELLO`, `WELCOME`, `LOG`, `ACK`, `ERR`, `HB`, `PING`,
  `PONG`, `EXIT`.
- A fixed, non-extensible-in-this-revision `LOG` header field set plus an
  explicit `LEN`-prefixed binary-safe payload.
- Server-side backpressure via TCP flow control; no application-level
  flow-control message type.

### Out of scope in LALF `1`

- Replay, resume, or any form of gap recovery on reconnect. A reconnecting
  client MUST start a new session (fresh `HELLO`, `SEQ` restarting at `1`) and
  MUST NOT expect the server to have retained anything about a prior
  connection beyond what is durably stored in `log_events`.
- Any read/query path on the LALF socket itself. A LALF server MUST NOT
  expose a mechanism for retrieving previously stored records over this
  protocol — that is `pm-log-cli`'s job, reading `log.db` directly. See
  [Centralized Log Server](280-log-srv.md).
- Authentication, authorization, and transport encryption. LALF assumes the
  same trusted-network posture as CALF (see the normative
  [CALF Protocol Reference](920-app-calf-protocol.md)).
- Multi-host routing, service discovery, or multi-server fan-out. A LALF
  client speaks to exactly one `pm-log-srv` at a time, at a statically
  configured `host:port`.



## Transport and session model

| Property | Value |
|---|---|
| Transport | TCP, one connection per client process |
| Default port | `5600` |
| Encoding | UTF-8 for all header lines and payload bytes |
| Header line delimiter | `\n` (LF); a bare LF terminates every header line, matching ALF/CALF |
| Payload framing | Explicit byte count (`LEN=<n>`), not delimiter-based |
| Max header line length | 4096 bytes including the terminating `\n` |
| Max payload length | `max_message_bytes`, default 65536 bytes; a server MUST truncate (not reject) an oversized payload and MUST record `truncated=1` for the stored row |
| Handshake timeout | A server MUST close the connection if no valid `HELLO` is received within 5 seconds of accept |
| Heartbeat interval | `HBINT` seconds, server-assigned in `WELCOME`, default `5` |
| Idle/dead-connection timeout | A server MUST treat a connection as dead, and close it, if no message of any kind (including `HB`) arrives within `2 × HBINT` seconds |
| Session cardinality | Exactly one `HELLO`/`WELCOME` per TCP connection; a second `HELLO` on an already-established connection is a protocol violation (`ERR|CODE=PROTO_MISMATCH`) |
| Direction | `LOG`, `HB`, and `EXIT` are client → server only; `WELCOME` is server → client only; `ERR` is server → client only; `PING`/`PONG` are wire-symmetric (either endpoint MAY send `PING`, the receiver MUST reply `PONG`), though the shipped `pm-log-srv` implementation never initiates a `PING` itself — it only replies to a client-sent one |
| Subscriptions | None. LALF has no `SUB`/`UNSUB`, no channel model, and no `SYM=`-style filtering — every connected client's data is, by construction, exactly its own log stream |



## Wire format

### Line structure

Every LALF message begins with a header line of the form:

```text
<MSGTYPE>|KEY=VALUE|KEY=VALUE|...\n
```

identical in shape to a CALF line: `MSGTYPE` is an uppercase token, each
subsequent field is a `KEY=VALUE` pair separated by `|`, and the line is
terminated by a single `\n`. A message type that carries a payload (only
`LOG`, in this revision) MUST include a `LEN` field as its final `KEY=VALUE`
pair, whose value is the exact number of UTF-8 bytes that immediately follow
the header line's terminating `\n`. A receiver MUST read exactly `LEN` bytes
as the payload — it MUST NOT scan those bytes for a delimiter, and the
payload MUST NOT be assumed to end with its own trailing `\n`.

This exists because a log message is arbitrary text and cannot be assumed
free of `|`, `\n`, or any other byte value that would collide with a
delimiter-based grammar the way CALF's `KEY=VALUE|KEY=VALUE` grammar can
assume for its own constrained field values (symbols, prices, enums).

```text
HELLO|CLIENT=pm-api-gwy|PID=48213|HOST=trader-laptop|PROTO=LALF1
LOG|SEQ=1042|TS=2026-07-28T14:32:07.511Z|LEVEL=WARNING|LOGGER=edumatcher.md_gateway.gateway|LEN=57
slow client detected on channel DEPTH, symbol AAPL, dropping
```

### Parsing behavior

A conforming parser MUST:

1. Read bytes up to and including the next `\n` as one header line.
2. Split the header line on `|`; the first token is `MSGTYPE`, every
   subsequent token MUST parse as `KEY=VALUE` (split on the first `=`).
3. If the parsed fields include `LEN`, read exactly that many further bytes
   as the payload before considering the message complete and before parsing
   the next header line. A connection that closes before `LEN` bytes have
   arrived MUST be treated as an incomplete message, not a valid zero-length
   one.
4. If the parsed fields do not include `LEN`, the message has no payload; the
   parser proceeds directly to the next header line.
5. Reject (via `ERR`) any header line exceeding 4096 bytes before its
   terminating `\n` is found, any unrecognized `MSGTYPE`, and any message
   missing a field marked required below.

### TCP stream requirement

TCP is a byte stream, not a message queue. A LALF implementation MUST treat
the connection as one continuous byte stream and MUST NOT assume any
correspondence between `send()`/`recv()` calls on either side and logical
message boundaries. A single `recv()` may deliver part of a header line, a
whole message, or several messages concatenated; a conforming implementation
buffers and re-frames accordingly, exactly as required of ALF/CALF/RALF
implementations.



## Message catalog

| Message   | Direction         | Purpose                                      |
|-----------|-------------------|-----------------------------------------------|
| `HELLO`   | Client -> Server  | Start session; identifies the connecting process |
| `WELCOME` | Server -> Client  | Confirm session and advertise parameters       |
| `LOG`     | Client -> Server  | One formatted log record, header + payload     |
| `ACK`     | Server -> Client  | Reserved for future use — not sent in this revision |
| `ERR`     | Server -> Client  | Protocol violation or advisory condition       |
| `HB`      | Client -> Server  | Heartbeat, sent whether or not `LOG` was recently sent |
| `PING`    | Either direction  | On-demand liveness check                       |
| `PONG`    | Either direction  | Reply to `PING`                                |
| `EXIT`    | Client -> Server  | Clean disconnect                               |



## Message definitions

### `HELLO`

**Direction:** Client -> Server, exactly once, as the first message on a new
connection.

**Purpose:** identifies the connecting process and negotiates protocol
version; MUST precede any other message type.

| Field | Req | Type | Description |
|---|---|---|---|
| `CLIENT` | Yes | string | Process name, matching the connecting `pm-*` command name |
| `PID` | Yes | int | OS process ID of the connecting client |
| `HOST` | Yes | string | Hostname the client is running on |
| `PROTO` | Yes | string | MUST be `LALF1` in this revision |
| `INSTANCE` | No | string | Disambiguator when multiple instances of the same `CLIENT` connect concurrently |

```text
HELLO|CLIENT=pm-api-gwy|PID=48213|HOST=trader-laptop|PROTO=LALF1
```

A server receiving a second `HELLO` on a connection that has already
completed a handshake MUST respond `ERR|CODE=PROTO_MISMATCH` and close the
connection. A `HELLO` missing `CLIENT`, `PID`, `HOST`, or `PROTO` MUST be
rejected with `ERR|CODE=MISSING_FIELD`; a non-integer `PID` is rejected the
same way.

### `WELCOME`

**Direction:** Server -> Client, exactly once, in direct reply to a valid
`HELLO`.

**Purpose:** confirms the session is established and communicates
server-assigned session parameters the client MUST honor for the remainder
of the connection.

| Field | Req | Type | Description |
|---|---|---|---|
| `PROTO` | Yes | string | Echoes `LALF1` |
| `SRV` | Yes | string | Configured name of the responding `pm-log-srv` instance |
| `HBINT` | Yes | int | Heartbeat interval in seconds; the client MUST send `HB` at least this often |
| `SESSION` | Yes | string | Opaque per-connection session identifier, included in every stored row for this connection; not a security token |

```text
WELCOME|PROTO=LALF1|SRV=log-srv01|HBINT=5|SESSION=a1b2c3d4
```

A `WELCOME` is the sole positive acknowledgment of a `HELLO`; there is no
separate `ACK` for the handshake.

### `LOG`

**Direction:** Client -> Server, any number of times after `WELCOME`. This is
the only message type in LALF that carries a payload, and the only message
type a conforming server is required to durably store.

**Purpose:** carries one formatted log record — header fields plus a
length-prefixed message body.

| Field | Req | Type | Description |
|---|---|---|---|
| `SEQ` | Yes | int | Monotonic per-connection sequence number, starting at 1 |
| `TS` | Yes | string | UTC ISO-8601 timestamp with milliseconds, set by the client at emission time (`LogRecord.created`) |
| `LEVEL` | Yes | enum | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `LOGGER` | Yes | string | Originating logger name (`LogRecord.name`) |
| `MODULE` | No | string | `LogRecord.module`, when available |
| `LINE` | No | int | `LogRecord.lineno`, when available |
| `EXC` | No | bool (`1` or absent) | Set when the payload includes a formatted exception/traceback |
| `LEN` | Yes | int | Byte length of the UTF-8 payload following this header line's `\n` |

```text
LOG|SEQ=1042|TS=2026-07-28T14:32:07.511Z|LEVEL=WARNING|LOGGER=edumatcher.md_gateway.gateway|LEN=57
slow client detected on channel DEPTH, symbol AAPL, dropping
```

A server MUST reject (`ERR|CODE=INVALID_LEVEL`) any `LOG` whose `LEVEL` is
not one of the five listed values, and MUST reject (`ERR|CODE=MISSING_FIELD`)
any `LOG` missing `SEQ`, `TS`, `LEVEL`, `LOGGER`, or `LEN`. Neither rejection
is session-ending — the client SHOULD fix the sending code and MAY continue
sending subsequent `LOG` messages on the same connection.

A server MUST NOT reject a `LOG` solely for exceeding `max_message_bytes`; it
MUST instead truncate the stored payload to that limit (never splitting a
multi-byte UTF-8 codepoint), record `truncated=1`, and MAY send an advisory
`ERR|CODE=PAYLOAD_TOO_LARGE` — this is the one `ERR` code in this revision
that does not imply the client did anything requiring a fix before
continuing.

### `ACK`

**Direction:** Server -> Client.

**Purpose:** reserved for future use. A server MUST NOT send `ACK` for
individual `LOG` messages in this revision — `LOG` is fire-and-forget by
design, and per-message acknowledgment would be pure overhead at realistic
logging rates. `HELLO` success is communicated exclusively via `WELCOME`; no
separate `ACK` follows it. `ACK` is defined here only so its wire shape is
reserved and unambiguous for a future revision that adds a request/response
exchange to LALF. The shipped `pm-log-srv` never sends this message type.

```text
ACK|SEQ=1042
```

| Field | Req | Type | Description |
|---|---|---|---|
| `SEQ` | Yes | int | Echoes the `SEQ` of the message being acknowledged |

### `ERR`

**Direction:** Server -> Client.

**Purpose:** reports a protocol violation or an advisory condition on a
message the client sent. Whether `ERR` precedes a connection close depends on
the code (see table).

```text
ERR|CODE=INVALID_LEVEL|MSG=unknown LEVEL value: TRACE
```

| Field | Req | Type | Description |
|---|---|---|---|
| `CODE` | Yes | enum | One of the codes below |
| `MSG` | Yes | string | Free-text, human-readable detail; MUST NOT be parsed programmatically beyond logging/display |

| Code | Meaning | Session-ending? |
|---|---|---|
| `INVALID_LEVEL` | `LOG.LEVEL` not one of the five valid values | No — indicates a client bug; client SHOULD fix and MAY continue sending subsequent `LOG` messages on the same connection |
| `MISSING_FIELD` | A required header field absent on the message | No, same as `INVALID_LEVEL` |
| `PAYLOAD_TOO_LARGE` | `LOG.LEN` exceeded `max_message_bytes` | No — advisory only; the server has already truncated and stored the record |
| `PROTO_MISMATCH` | `HELLO.PROTO` was not `LALF1`, or a second `HELLO` was sent on an established connection | Yes — server MUST close the connection after queuing this `ERR` |
| `HELLO_TIMEOUT` | No `HELLO` received within 5 seconds of accept | Yes — the server queues this `ERR` and disconnects in the same step, without an intervening flush of the outbound queue; a client SHOULD NOT rely on receiving this `ERR` before the socket closes, and MUST instead treat an unexpected close with no prior `WELCOME` as an implicit handshake timeout |

**Implementation note on `HELLO_TIMEOUT` delivery.** Unlike every other
terminal `ERR` code above — which are queued and then the connection is
marked closing-after-flush, guaranteeing the `ERR` bytes are sent before the
socket closes — `HELLO_TIMEOUT` is queued and the connection is closed
immediately afterward, in the same pass through the server's idle-connection
sweep, with no guarantee the outbound queue was flushed first. In practice
this means a client is unlikely to ever observe this specific `ERR` on the
wire; it should be treated as effectively equivalent to a bare connection
close with no prior `WELCOME`.

### `HB`

**Direction:** Client -> Server, periodically. The server never sends `HB`;
it is purely a client-liveness signal the server listens for.

**Purpose:** liveness signal sent at least every `HBINT` seconds (from
`WELCOME`), whether or not the client has sent any `LOG` in that interval, so
the server can distinguish a quiet-but-alive client from a dead connection.

```text
HB|TS=2026-07-28T14:32:10.000Z
```

| Field | Req | Type | Description |
|---|---|---|---|
| `TS` | Yes | string | UTC ISO-8601 timestamp with milliseconds, at the moment this `HB` was sent |

### `PING` / `PONG`

**Direction:** wire-symmetric; either endpoint MAY send `PING` at any time
after `WELCOME`, and the receiver MUST reply with `PONG` as soon as possible.
The shipped `pm-log-srv` server implementation only ever replies to a
client-initiated `PING` — it has no code path that sends `PING` itself. The
symmetric grammar is reserved for a future operator tool that might want to
probe a specific client connection's liveness on demand.

**Purpose:** an on-demand liveness check independent of the regular `HB`
cadence.

```text
PING
PONG
```

Neither message carries fields. A `PONG` is a direct, unsolicited-content
reply to a `PING` and carries no correlation identifier in this revision (a
connection has, at any time, at most one outstanding `PING` it is waiting
on).

### `EXIT`

**Direction:** Client -> Server.

**Purpose:** graceful, client-initiated end of session.

```text
EXIT
```

On receiving `EXIT`, a server MUST flush any buffered rows already accepted
for that connection before closing the socket. A client disconnecting
without sending `EXIT` (process killed by signal, crash) is not a protocol
violation; the server MUST treat the closed socket identically to an
explicit `EXIT` for the purpose of flushing buffered rows and marking the
connection's stored process record disconnected.



## Backpressure

LALF defines no application-level flow-control message. A server
experiencing a write bottleneck MUST apply backpressure by ceasing to read
from a connection's TCP receive buffer once its per-connection internal
queue exceeds `max_client_queue`, relying on standard TCP flow control to
slow the client's `send()` calls. A server MUST NOT silently discard a `LOG`
message it has already accepted from the TCP layer solely due to write-path
load; the sole exception is oversized-payload truncation
(`PAYLOAD_TOO_LARGE`), which is a per-message content limit, not a
load-shedding mechanism.



## Sequence semantics

- `SEQ` is a monotonic per-**connection** counter starting at `1`, present on
  every `LOG` message.
- A reconnecting client MUST start a new session (fresh `HELLO`) and MUST
  restart `SEQ` at `1`; a server MUST NOT interpret a lower `SEQ` on a new
  connection as a gap or a duplicate of a prior connection's stream —
  `SESSION` (from `WELCOME`), not `SEQ` alone, is what disambiguates rows
  from different connections in storage.
- A server MAY log a client-visible gap in `SEQ` for diagnostic purposes
  (the reference `pm-log-srv` implementation does, at `DEBUG` level) but MUST
  NOT reject or otherwise treat a `SEQ` gap as a protocol violation — LALF
  defines no retransmission or replay mechanism, so a gap is purely
  informational.
- LALF defines no cross-connection replay or resume. There is nothing
  equivalent to CALF's `RESUME=1`/`LASTSEQ=` — a reconnecting client's
  records generated during the disconnect window were never buffered
  server-side to begin with.



## Configuration reference

LALF's wire-level parameters are exposed as `pm-log-srv` configuration, read
from an optional top-level `log_server` block in `engine_config.yaml`. See
[Configuration — Configuring pm-log-srv](010-configuration.md#configuring-pm-log-srv)
for the full field reference and example. They are not negotiated on the
wire beyond `WELCOME.HBINT`:

| Parameter | Wire effect | Config key |
|---|---|---|
| Listen port | Default port clients connect to | `log_server.port` (default `5600`) |
| Handshake timeout | 5-second `HELLO` deadline | Fixed at 5s in this revision, not separately configurable |
| Heartbeat interval | Value sent in `WELCOME.HBINT` | `log_server.heartbeat_interval_sec` (default `5`) |
| Idle timeout | `2 × HBINT` dead-connection rule | Derived, not independently configurable |
| Max header line length | Header-line rejection ceiling | Fixed at 4096 bytes, matching CALF |
| Max payload length | `LOG.LEN` ceiling before truncation | `log_server.max_message_bytes` (default `65536`) |
| Per-connection queue limit | Backpressure trigger | `log_server.max_client_queue` (default `10000`) |



## What to watch out for during implementation

- **Do not treat `LOG`'s payload as line-oriented.** The single most common
  implementation mistake: reading the payload with a line-based
  `readline()`-style call instead of reading exactly `LEN` bytes will
  silently truncate any log message containing an embedded `\n` (i.e., any
  formatted traceback). Always read the payload as a fixed byte count.
- **`SEQ` is per-connection, not global.** A reconnecting client MUST restart
  `SEQ` at 1; a server MUST NOT interpret a lower `SEQ` on a new connection as
  a gap or a duplicate — `SESSION`, not `SEQ` alone, disambiguates rows from
  different connections in storage.
- **`ERR` is not always fatal.** Unlike `PROTO_MISMATCH`/`HELLO_TIMEOUT`,
  `INVALID_LEVEL`/`MISSING_FIELD`/`PAYLOAD_TOO_LARGE` do not end the session —
  an implementation that closes the connection on every `ERR` will disconnect
  a client over one malformed `LOG` line instead of continuing to accept its
  subsequent, valid ones.
- **`pm-log-srv` itself never speaks LALF as a client to another instance.**
  It is the one `pm-*` process whose own logging configuration hard-codes
  stdout/file only — there is nothing paradoxical about this in the protocol
  itself, but it is easy to forget when wiring `TcpLogHandler` into every
  other entrypoint.
- **A missing `LEN` means no payload, not a zero-length one.** Only `LOG`
  carries `LEN` in this revision; every other message type MUST be parsed as
  header-only. An implementation that defaults to expecting a payload after
  every message type will stall waiting for bytes that are never sent.
- **Do not assume `HELLO_TIMEOUT` is reliably observable.** As noted under
  `ERR` above, the reference server implementation queues this `ERR` and
  closes the connection without guaranteeing a flush first. Client code
  should treat "connected but no `WELCOME` within a few seconds, then the
  socket closes" as the practical signal, not a specific received `ERR` code.



## Conformance notes

If you are implementing a LALF client or server, the most important protocol
truths are:

1. Every LALF session begins with exactly one `HELLO` and, on success,
   exactly one `WELCOME`; a second `HELLO` on the same connection is a
   protocol violation.
2. `LOG` is the only message type that carries a payload, and its `LEN` field
   is mandatory; every other message type is header-only with no `LEN`
   field.
3. Payload bytes are read by exact count, never scanned for a delimiter; they
   may contain any UTF-8 byte sequence, including `|`, `\n`, and embedded
   control characters, without escaping.
4. `LOG` is fire-and-forget: a server never sends a per-message `ACK` for it,
   and a client never waits for one before sending the next `LOG`.
5. Oversized payloads are truncated and stored, never dropped; only a
   malformed or incomplete message is refused outright.
6. `SEQ` numbering, and any gap-detection built on it, is scoped to a single
   TCP connection and MUST be reset on reconnect; LALF defines no
   cross-connection replay or resume.
7. A client MUST send `HB` at least every `HBINT` seconds; a server MUST
   consider a connection dead after `2 × HBINT` seconds of total silence (no
   message of any kind, `HB` included). `HB` is client-to-server only.
8. LALF has no subscription, filtering, or channel model of any kind — every
   connected client's data is exactly and only its own log stream.
9. LALF defines no read/query path; retrieval of stored records happens
   entirely outside this protocol, against `log.db` directly via
   `pm-log-cli`.
10. `PING`/`PONG` are wire-symmetric by grammar, but in the shipped
    implementation only a client ever initiates `PING` — the server only
    replies.



## See also

- [Centralized Log Server](280-log-srv.md) — operational guide: starting `pm-log-srv`, using `pm-log-cli`, and query cookbook
- [Processes](170-processes.md#pm-log-srv-centralized-log-server) — where `pm-log-srv`/`pm-log-cli` sit in the process model
- [Configuration — Configuring pm-log-srv](010-configuration.md#configuring-pm-log-srv) — `log_server` field law
- [ALF Protocol Reference](900-app-alf-protocol.md) — the normative sibling document this appendix's structure and conventions follow
- [CALF Protocol Reference](920-app-calf-protocol.md) — the normative sibling document LALF's transport/session model and line-oriented framing are most directly modeled on
- [External Protocols Overview](210-protocols-overview.md) — ALF/BALF/CALF/RALF at a glance

# Configuration Schema and Process Blocks

This chapter is the field-by-field reference for `engine_config.yaml`: every
top-level key, which process reads it, and the settings of each section. For
how to write, check and deploy a configuration, read the Operator's Guide
chapter [The Configuration Workflow](../../operator-guide/part-2-configure/010-the-configuration-workflow.md);
for the formal grammar and validation rules, see
[Engine Configuration Specification](030-formal-specification.md).

## Current Schema

The current parser recognizes these top-level keys:

| Key                        | Required when file exists? | Used by                         | Purpose                                                                   |
|----------------------------|---------------------------:|---------------------------------|---------------------------------------------------------------------------|
| `symbols`                  |                        Yes | Engine                          | Accepted symbols and per-symbol settings                                  |
| `participants`             |                        Yes | Engine                          | Participant identities allowed to connect, with per-participant settings |
| `participant_defaults`     |                         No | Engine                          | Values a `participants` entry inherits when it omits them                 |
| `alf_gateway`              |                         No | `pm-alf-gwy`                    | External ALF text TCP gateway settings                                    |
| `sessions_enabled`         |                         No | Engine                          | Enable scheduler-driven session states                                    |
| `enforce_collars`          |                         No | Engine                          | Global collar enforcement toggle                                          |
| `enforce_circuit_breakers` |                         No | Engine                          | Global circuit-breaker enforcement toggle                                 |
| `engine_tuning`            |                         No | Engine                          | Runtime retention and throttling knobs                                    |
| `mm_obligation_defaults`   |                         No | Engine                          | Default market-maker quote obligation policy                              |
| `risk_controls`            |                         No | Engine                          | Named collar and order-limit profiles                                     |
| `circuit_breaker_defaults` |                         No | Engine                          | Default circuit-breaker ladder                                            |
| `market_maker_combos`      |                         No | Engine                          | Startup multi-symbol combo seeds                                          |
| `schedule`                 |                         No | Scheduler, parsed by engine too | Session transition times                                                  |
| `country`                  |                         No | `pm-scheduler`                  | Country used for the scheduler's bank-holiday/weekend calendar            |
| `post_trade_gateway`       |                         No | `pm-ralf-gwy`                   | External RALF dissemination gateway settings                              |
| `market_data_gateway`      |                         No | `pm-md-gwy`                     | External CALF dissemination gateway settings                              |
| `balf_gateway`             |                         No | `pm-balf-gwy`                   | External BALF binary TCP gateway settings                                 |
| `dc_gateway`               |                         No | `pm-dc-gwy`                     | Drop-copy TCP relay gateway settings                                      |
| `log_server`               |                         No | `pm-log-srv`                    | Centralized LALF log-collector settings                                   |
| `api_gateways`             |                         No | `pm-api-gwy`                | Named REST/WebSocket order-entry and market-data gateway process settings |
| `indices`                  |                         No | `pm-index`                      | Index calculation process configurations                                  |

The nested sections below document every field currently parsed under these
top-level keys. Unknown keys in a mapping are generally ignored by the loader,
but they should not be relied on for runtime behavior — `pm-config-show -a`
lists any it finds, which is the cheapest way to catch a mistyped section name.

## Which Process Reads What

`engine_config.yaml` is one shared ref-data file, but no single process reads
all of it. Each auxiliary gateway or service opens the file independently at
its own startup, ignores every top-level key it doesn't recognize, and parses
only the section(s) it owns. `pm-engine` is the only process that reads most
of the file — the gateway-specific blocks (`market_data_gateway`,
`balf_gateway`, `post_trade_gateway`, `dc_gateway`, `log_server`,
`alf_gateway`, `api_gateways`) are never touched by the engine itself.

| Process | Loader module | Top-level section(s) read | What it needs it for |
|---|---|---|---|
| `pm-engine` | `engine/config_loader.py` | `symbols`, `participants`, `participant_defaults`, `sessions_enabled`, `enforce_collars`, `enforce_circuit_breakers`, `engine_tuning`, `mm_obligation_defaults`, `risk_controls`, `circuit_breaker_defaults`, `market_maker_combos`, `schedule`, `indices` | Symbol universe, allowed order-entry gateways, session/collar/order-limit/circuit-breaker policy, runtime tuning, MM obligations, startup combo seeds, session schedule, and index definitions |
| `pm-alf-gwy` | `alf_gwy/config.py` | `alf_gateway`, `participants` | Own bind address/port/timeouts, plus the gateway ID allowlist and roles for ALF client sessions |
| `pm-balf-gwy` | `balf_gwy/config.py` | `balf_gateway`, `participants` | Own bind address/port/timeouts, plus the gateway ID allowlist, roles, and `disconnect_behaviour` for BALF sessions |
| `pm-ralf-gwy` | `ralf_gateway/config.py` | `post_trade_gateway` | Own bind address/port/timeouts and `allowed_roles` for RALF (post-trade) subscribers |
| `pm-md-gwy` | `md_gateway/config.py` | `market_data_gateway` | Own bind address/port/timeouts, replay window, and `depth_levels` for CALF subscribers |
| `pm-dc-gwy` | `dc_gwy/config.py` | `dc_gateway` | Own bind address/port/timeouts and per-client queue limit for the drop-copy TCP relay |
| `pm-log-srv` | `log_srv/config.py` | `log_server` | Own bind address/port/retention/throughput knobs for the centralized LALF log collector, plus the LALF-PS ZeroMQ log-distribution ports and subscription limits |
| `pm-api-gwy` | `api_gateway/config.py` | `api_gateways` | Named REST/WebSocket gateway instances, API credentials, rate limits, and timeouts |
| `pm-index` | `index/config_loader.py` (wraps `engine/config_loader.py`) | `indices`, `symbols.<SYM>.outstanding_shares`, `symbols.<SYM>.last_buy_price` / `last_sell_price` | Index definitions (constituents, base value, publish interval) and the per-constituent share counts / reference prices needed to seed each index at startup |
| `pm-scheduler` | `scheduler/main.py` | `schedule`, `country` | Session-phase transition times — re-reads the same block `pm-engine` reads, but as an independent process so the schedule can be driven or tested externally — plus the country used to skip weekends and bank holidays |

!!! note "Tooling reads everything"
    `pm-cverifier` and `pm-config-show` are the exceptions: the linter parses
    and cross-validates the whole file, and the viewer displays all of it,
    including sections no runtime process consumes on its own. Neither is a
    "reader" in the operational sense above — see
    [Verify Configs with `pm-cverifier`](../../operator-guide/part-2-configure/010-the-configuration-workflow.md#verify-configs-with-pm-cverifier) and
    [Inspect Configs with `pm-config-show`](../../operator-guide/part-2-configure/010-the-configuration-workflow.md#inspect-configs-with-pm-config-show).

Two practical consequences follow from this split:

- A typo in, say, `balf_gateway` will not be caught by `pm-engine` at all —
  only `pm-balf-gwy` (or `pm-cverifier`) will reject it. Run `pm-cverifier`
  before starting a full stack to catch cross-section mistakes early.
- Each gateway process can be restarted independently with a changed config
  section (for example, bumping `market_data_gateway.depth_levels`) without
  restarting `pm-engine`, since the engine never reads that section.

## Configuring `pm-alf-gwy`

`pm-alf-gwy` is the TCP front door for the ALF text protocol. It reads an
optional top-level `alf_gateway` block from the same `engine_config.yaml`. The
block is not consumed by `pm-engine`; it only configures the gateway process
itself. Who may log in, and with which role, is **not** set here: the gateway
takes that from the `participants` list (see
[Participants](#participants)). Omit the block entirely to run
on the defaults shown below.

Minimal example (every value shown is the default):

```yaml
alf_gateway:
  enabled: true
  name: alf-gwy01
  bind_address: 0.0.0.0
  port: 5565
  heartbeat_interval_sec: 5
  handshake_timeout_sec: 10
  idle_timeout_sec: 30
  max_connections: 64
  max_client_queue: 10000
  max_commands_per_second: 100
  max_errors_before_disconnect: 50
  error_window_sec: 60
```

### Fields

| Field | Default | Rule | What it does |
|-------|---------|------|--------------|
| `enabled` | `true` | boolean | When `false`, `pm-alf-gwy` logs a warning and refuses to start |
| `name` | `alf-gwy01` | string | Reported to every client as `GW=` in the `WELCOME` line |
| `bind_address` | `0.0.0.0` | string | Interface the listener binds. Use `127.0.0.1` for loopback-only. The `EDUMATCHER_GATEWAY_BIND_HOST` environment variable overrides this value |
| `port` | `5565` | `1..65535` | TCP port clients connect to |
| `heartbeat_interval_sec` | `5` | integer `> 0` | How often the gateway sends `HB` to an authenticated client that has received nothing else in that time. Advertised as `HBINT=` in `WELCOME` |
| `handshake_timeout_sec` | `10` | integer `> 0` | How long a new connection has to complete the `HELLO` login |
| `idle_timeout_sec` | `30` | integer `> 0` | How long a client may stay silent before it is disconnected. Advertised as `IDLE=` in `WELCOME` |
| `max_connections` | `64` | integer `> 0` | Cap on simultaneous client connections |
| `max_client_queue` | `10000` | integer `> 0` | Cap on lines queued for one client that is not reading |
| `max_commands_per_second` | `100` | integer `> 0` | Per-client command rate limit |
| `max_errors_before_disconnect` | `50` | integer `> 0` | Number of protocol errors tolerated within `error_window_sec` |
| `error_window_sec` | `60` | integer `> 0` | Length of the sliding window over which errors are counted |

### How the settings work together

A connection goes through these stages, and each setting acts at one of them.

1. **Accept.** A new TCP connection is accepted unless `max_connections` clients
   are already connected; in that case the socket is closed immediately and a
   warning is logged. The client receives no `ERR` line, only a closed
   connection.
2. **Login.** The first message must be `HELLO`. If login is not complete within
   `handshake_timeout_sec`, the gateway sends `ERR|CODE=AUTH_TIMEOUT` and closes
   the connection. On success the client gets `WELCOME|PROTO=ALF1|GW=<name>|ID=<gateway id>|HBINT=<n>|IDLE=<n>`,
   so a client can read the timers it must respect instead of hard-coding them.
3. **Keep-alive.** Once logged in, the gateway sends `HB` whenever
   `heartbeat_interval_sec` has passed without any other line going out to that
   client. In the other direction, *any* bytes received from the client count as
   activity; if nothing arrives for `idle_timeout_sec` the gateway sends
   `ERR|CODE=IDLE_TIMEOUT` and closes. A client that is only watching and
   sending nothing must therefore send a `PING` more often than the idle
   timeout, so keep `idle_timeout_sec` comfortably above the interval at which
   your clients ping.
4. **Commands.** Each client has its own token bucket that holds up to
   `max_commands_per_second` tokens and refills at that rate; every command
   spends one token. A command arriving with the bucket empty is rejected with
   `ERR|CODE=RATE_LIMITED` and is **not** forwarded to the engine; the
   connection stays open. `PING`, `EXIT` and `QUIT` after login do not spend
   tokens.
5. **Errors.** Every `ERR` the gateway sends for a client's mistake (bad syntax,
   unknown command, rejected request, `RATE_LIMITED`, and so on) is recorded with
   a timestamp. Timestamps older than `error_window_sec` drop out. When
   `max_errors_before_disconnect` errors are inside the window, the gateway sends
   `ERR|CODE=MAX_ERRORS` and disconnects. A client that is rate-limited all the
   time is therefore eventually disconnected; raise `max_commands_per_second`
   or lower the client's send rate.
6. **Slow consumers.** Lines for a client wait in an outbound queue until its
   socket accepts them. If that queue reaches `max_client_queue` lines, the
   queue is discarded, the gateway sends `ERR|CODE=SLOW_CLIENT` and closes the
   connection, so one stuck client cannot consume the gateway's memory.

Choosing values for a classroom: the defaults suit a few dozen desks. Raise
`max_connections` if more clients connect, raise `max_commands_per_second` for
bots that send quote refreshes in bursts, and lower `idle_timeout_sec` if you
want abandoned sessions released quickly.

### Overrides and generation

- `pm-alf-gwy --bind ADDR` and `--port N` override `bind_address` and `port` for
  one run; `--engine-host HOST` points the gateway at an engine on another
  machine. The other fields can only be changed in the file.
- Changing the block takes effect when `pm-alf-gwy` is restarted; `pm-engine`
  does not need to be restarted, since it never reads this block.
- `pm-config-gen` emits the block with `--alf-gateway` and the `--alf-*`
  overrides listed under [ALF gateway options](../../operator-guide/part-2-configure/010-the-configuration-workflow.md#option-reference).
- `pm-cverifier` validates every field above and reports an unrecognised key in
  the block (`S121`), which would otherwise be ignored and leave the default in
  force.

See [ALF Gateway](../../operator-guide/part-5-gateways/010-alf-gateway.md) for operating the gateway and
[ALF Protocol](../../protocols-and-clients/part-2-specifications/010-alf.md) for the message formats.


## Configuring `pm-ralf-gwy`

`pm-ralf-gwy` reads an optional top-level `post_trade_gateway` block from the
same `engine_config.yaml` file used by the engine. This block is not consumed by
`pm-engine`; it is consumed by the RALF dissemination gateway process itself.

Minimal example:

```yaml
post_trade_gateway:
  name: ralf-gwy01
  bind_address: 0.0.0.0
  port: 5580
  replay_retention_sec: 86400
  heartbeat_interval_sec: 1
  idle_timeout_sec: 5
  max_client_queue: 10000
  allowed_roles:
    - CLEARING
    - DROP_COPY
    - AUDIT
```

Use this block to control where the RALF gateway listens and which external
client roles it will accept. In the current implementation:

- `name` is the gateway id reported in `WELCOME`
- `bind_address` and `port` define the TCP listener for external subscribers
- `replay_retention_sec` controls the in-memory replay window
- `heartbeat_interval_sec` controls `HB` cadence
- `idle_timeout_sec` controls inactive-session disconnect timing
- `max_client_queue` caps slow-client buffering before `SLOW_CLIENT`
- `allowed_roles` limits accepted `HELLO|ROLE=...` values

If you prefer to generate this block instead of writing it by hand, `pm-config-gen`
can emit it with `--post-trade-gateway` and optional `--post-trade-*` overrides.


## Configuring `pm-md-gwy`

`pm-md-gwy` reads an optional top-level `market_data_gateway` block from the
same `engine_config.yaml` file. This block is not consumed by `pm-engine`; it
is consumed by the CALF market-data gateway process itself.

Minimal example:

```yaml
market_data_gateway:
  enabled: true
  name: md-gwy01
  bind_address: 0.0.0.0
  port: 5570
  heartbeat_interval_sec: 1
  idle_timeout_sec: 5
  replay_window_sec: 30
  max_symbols_per_client: 200
  max_client_queue: 10000
  depth_levels: 10
```

Use this block to control whether the CALF gateway starts and how it serves
subscribers. In the current implementation:

- `enabled` controls whether `pm-md-gwy` starts serving clients
- `name` is the gateway id reported in welcome/session payloads
- `bind_address` and `port` define the TCP listener for CALF subscribers
- `heartbeat_interval_sec` controls heartbeat cadence
- `idle_timeout_sec` controls inactive-session disconnect timing
- `replay_window_sec` controls the in-memory replay history window
- `max_symbols_per_client` caps per-client subscription fanout
- `max_client_queue` caps slow-client buffering
- `depth_levels` sets how many aggregated price levels per side are sent on
  the CALF `DEPTH` channel (see [920-app-calf-protocol.md](../../protocols-and-clients/part-2-specifications/030-calf.md))

If you prefer to generate this block instead of writing it by hand,
`pm-config-gen` can emit it with `--market-data-gateway` and optional
`--market-data-*` overrides.


## Configuring `pm-balf-gwy`

`pm-balf-gwy` reads an optional top-level `balf_gateway` block from the same
`engine_config.yaml` file used by the engine.  This block is not consumed by
`pm-engine`; it is consumed by the BALF binary TCP gateway process.

Gateway identities and disconnect behaviour are read from the existing
`participants` list — no separate credentials block is needed.

Minimal example:

```yaml
balf_gateway:
  name: balf-gwy01
  bind_address: 0.0.0.0
  port: 5560
  heartbeat_interval_sec: 1
  heartbeat_timeout_sec: 5
  idle_timeout_sec: 30
  auth_timeout_sec: 10
  max_connections: 64
  max_client_queue: 10000
  max_messages_per_second: 100
  max_errors_before_disconnect: 10
  error_window_sec: 60
  duplicate_session_policy: REJECT_NEW
```

| Field | Default | Description |
|-------|---------|-------------|
| `name` | `balf-gwy01` | Gateway name echoed in the `LOGON_ACK` message field |
| `bind_address` | `0.0.0.0` | TCP listen interface (`127.0.0.1` for loopback-only) |
| `port` | `5560` | TCP listen port |
| `heartbeat_interval_sec` | `1` | Seconds between server-initiated `HEARTBEAT` frames when no other outbound traffic |
| `heartbeat_timeout_sec` | `5` | Disconnect session if no inbound traffic arrives within this window |
| `idle_timeout_sec` | `30` | Additional idle-session cleanup guard |
| `auth_timeout_sec` | `10` | Hard-close unauthenticated connections if `LOGON` is not completed within this window |
| `max_connections` | `64` | Maximum simultaneous TCP connections |
| `max_client_queue` | `10000` | Per-client outbound frame buffer depth before `SLOW_CLIENT` disconnect |
| `max_messages_per_second` | `100` | Token-bucket inbound rate limit per client |
| `max_errors_before_disconnect` | `10` | Error threshold in the sliding `error_window_sec` before forced disconnect |
| `error_window_sec` | `60` | Sliding window length (seconds) for the error counter |
| `duplicate_session_policy` | `REJECT_NEW` | What to do when a second `LOGON` arrives for an already-connected gateway ID: `REJECT_NEW` or `EVICT_OLD` |

If you prefer to generate this block instead of writing it by hand,
`pm-config-gen` can emit it with `--balf-gateway` and optional `--balf-*`
overrides.  See [BALF TCP Gateway](../../operator-guide/part-5-gateways/020-balf-gateway.md) for the full
client-facing documentation.


## Configuring `pm-api-gwy`

`pm-api-gwy` reads an optional top-level `api_gateways` block from the same
`engine_config.yaml` file. This block is not consumed by `pm-engine`; it is
consumed by the REST/WebSocket API gateway process.

Minimal generated example:

```yaml
api_gateways:
  desk:
    enabled: true
    host: 0.0.0.0
    port: 8080
    swagger_enabled: true
    log_level: info
    stats_db: data/stats.db
    credentials:
      - api_key: key-trader01-example
        gateway_id: TRADER01
        description: Generated key for TRADER01
      - api_key: key-dashboard-example
        gateway_id: null
        description: Read-only dashboard client
    rate_limit:
      writes_per_second: 10
      burst: 20
    timeouts:
      engine_auth_sec: 3.0
      engine_reply_sec: 3.0
      wait_ack_sec: 3.0
```

Use this block to control where the REST API listens, whether Swagger is
available, which bearer tokens are accepted, and how write rate limits and
engine reply waits are applied. In the current implementation:

- `enabled` lets `pm-api-gwy` refuse startup when set to `false`
- `host` and `port` define the uvicorn HTTP listener
- `swagger_enabled` controls `/docs` and `/openapi.json`
- `stats_db` points history endpoints at the `pm-stats` SQLite database
- `credentials[].api_key` is the bearer token used by REST and WebSocket clients
- `credentials[].gateway_id` maps a key to an ALF gateway; `null` is read-only
- a non-null `credentials[].gateway_id` may appear in only one `api_gateways` entry
- `rate_limit` applies per API key to write endpoints only
- `timeouts.engine_reply_sec` and `timeouts.wait_ack_sec` control request/reply and `?wait=ack` waits

If you prefer to generate this block instead of writing it by hand,
`pm-config-gen` can emit it with `--api-gateway`. By default it generates one
credential per configured ALF gateway. Add `--api-gateway-readonly-key` for a
dashboard-style key with `gateway_id: null`, or pass explicit `--api-key`
entries when you need known token values.

When more than one named API gateway is configured, start each process with its
entry name, for example `pm-api-gwy --instance desk`.


## Configuring `pm-index`

`pm-index` reads an optional top-level `indices` block from the same
`engine_config.yaml` file. This block is not consumed by `pm-engine`; it is
consumed by the index calculation process.

Example with two indices:

```yaml
indices:
  - id: EDU100
    description: EduMatcher broad index
    base_value: 1000.0
    publish_interval_sec: 1.0
    history_file: data/indexes/EDU100_history.jsonl
    state_file: data/indexes/EDU100_state.json
    constituents:
      - AAPL
      - MSFT
      - TSLA
  - id: TECH2
    description: Technology pair
    base_value: 500.0
    publish_interval_sec: 2.0
    history_file: data/indexes/TECH2_history.jsonl
    state_file: data/indexes/TECH2_state.json
    constituents:
      - AAPL
      - MSFT
```

Use this block to define one or more weighted-average price indices that
`pm-index` tracks as trades print through the engine. In the current
implementation:

- `id` is the unique index identifier used in events, history records, and derived file names
- `description` is a human-readable label emitted in `INDEX_OPEN` and `INDEX_UPDATED` events
- `base_value` is the divisor-normalized starting level; `1000.0` is the standard convention
- `publish_interval_sec` throttles how frequently index updates are published to subscribers
- `history_file` is a line-delimited JSON file where corporate-action and constituent events are persisted
- `state_file` is a JSON file where the current divisor and constituent shares are checkpointed
- `constituents` is an ordered list of symbols; each must have `outstanding_shares` set in `symbols:`

Constraints enforced at startup:

- Maximum 5 indices per config file
- Every constituent symbol must appear in `symbols:` with a positive `outstanding_shares`
- `id` values must be unique across the `indices` list

If you prefer to generate this block instead of writing it by hand,
`pm-config-gen` can emit it with `--index` and the associated `--index-*`
options. File paths are automatically derived from the index ID when not
specified.


## Configuring `pm-log-srv`

`pm-log-srv` reads an optional top-level `log_server` block from the same
`engine_config.yaml` file. This block is not consumed by `pm-engine`; it is
consumed by the centralized LALF log-collector process. See
[Centralized Log Server](../../operator-guide/part-6-observe-and-recover/040-log-server.md) for the operational guide (starting
the server, using `pm-log-cli`) and [LALF Protocol Reference](../../protocols-and-clients/part-2-specifications/050-lalf.md)
for the normative wire specification.

Minimal example:

```yaml
log_server:
  enabled: true
  name: log-srv01
  bind_address: 0.0.0.0
  port: 5600
  db_path: data/log.db
  retention_days: 30
  max_message_bytes: 65536
  max_client_queue: 10000
  write_batch_size: 50
  write_batch_interval_ms: 100
  heartbeat_interval_sec: 5
```

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `true` | Master switch — lets `pm-log-srv` refuse to accept connections when set to `false` |
| `name` | `log-srv01` | Server name echoed in the LALF `WELCOME.SRV` field |
| `bind_address` | `0.0.0.0` | TCP listen interface (`127.0.0.1` for loopback-only) |
| `port` | `5600` | TCP listen port for LALF clients |
| `db_path` | `data/log.db` | SQLite database path where `log_events`/`processes`/`server_stats` are stored |
| `retention_days` | `30` | Prune `log_events` rows older than this many days, once per hour; `null` (or `--retention-days 0`) means unbounded retention |
| `max_message_bytes` | `65536` | Maximum `LOG` payload size before truncation — oversized messages are truncated and stored, never dropped |
| `max_client_queue` | `10000` | Per-connection outbound backlog limit before backpressure is applied |
| `write_batch_size` | `50` | Maximum rows per SQLite transaction in the background writer thread |
| `write_batch_interval_ms` | `100` | Maximum time between writer-thread flushes, whichever comes first with `write_batch_size` |
| `heartbeat_interval_sec` | `5` | How often a connected client must send something (`LOG` or `HB`) to stay alive; the server disconnects after 2× this interval of silence and advertises the value to clients in `WELCOME.HBINT` (the server itself never sends `HB`). Doubles as the publish interval for the LALF-PS `log.server_state` tick |

### LALF-PS fields — the ZeroMQ log-distribution interface

Everything above configures how logging gets *in* to `pm-log-srv`. The
fields below configure how it gets back *out*: `pm-log-srv` also binds a
ZeroMQ `PUB`/`PULL` pair so live log viewers can be pushed rows as they are
committed, rather than polling `log.db` on a timer. See
[LALF-PS](../../operator-guide/part-6-observe-and-recover/040-log-server.md#lalf-ps-the-zeromq-log-distribution-interface) for
the full interface.

```yaml
log_server:
  # ... the collector fields above ...
  pubsub_enabled: true
  pub_port: 5601
  pull_port: 5602
  lease_sec: 30
  max_lease_sec: 300
  max_subscribers: 32
  notify_interval_ms: 250
  backfill_chunk_rows: 500
  max_backfill_minutes: 1440
  max_backfill_rows: 100000
  max_pending_rows: 20000
  pub_sndhwm: 10000
```

| Field | Default | Description |
|-------|---------|-------------|
| `pubsub_enabled` | `true` | Master switch for LALF-PS. When `false`, no ZeroMQ socket is bound at all and `pm-log-srv` runs as a pure TCP collector |
| `pub_port` | `5601` | ZeroMQ `PUB` port carrying live rows, notification ticks, backfill chunks, control acks and errors |
| `pull_port` | `5602` | ZeroMQ `PULL` port receiving subscriber control requests |
| `lease_sec` | `30` | Subscription lease TTL. A `PUB` socket cannot see that a peer died, so every subscription carries a TTL the subscriber must refresh with `log.renew`; one that goes silent is reaped and its buffers discarded |
| `max_lease_sec` | `300` | Ceiling on a subscriber's requested lease. A request above it is *clamped*, not rejected. Must be `>= lease_sec` |
| `max_subscribers` | `32` | Maximum concurrent leased subscriptions; further `log.subscribe` requests are answered with `TOO_MANY_SUBS` |
| `notify_interval_ms` | `250` | Coalescing window for `NOTIFY`-mode ticks, and the floor on a subscriber's own requested interval |
| `backfill_chunk_rows` | `500` | Rows per backfill chunk, and the maximum rows per live stream message |
| `max_backfill_minutes` | `1440` | Largest "last n minutes" window a subscriber may request (24 h) |
| `max_backfill_rows` | `100000` | Hard cap on rows returned by one backfill; the final chunk sets `truncated` when it bites |
| `max_pending_rows` | `20000` | Per-subscription stream buffer cap. A subscriber that is alive but too slow loses its oldest buffered rows rather than growing the server without bound |
| `pub_sndhwm` | `10000` | ZeroMQ send high-water mark on the `PUB` socket |

`pm-log-srv` therefore occupies a contiguous three-port block —
`5600`/`5601`/`5602` by default — and all three must be different. It
refuses to start otherwise, and `pm-cverifier` reports the condition as
`S102` before you ever get there. `pm-cverifier` also cross-checks the two
LALF-PS ports against every other configured listener (`M018`) and rejects
a `max_lease_sec` below `lease_sec` (`S103`).

Every CLI flag on `pm-log-srv` (`--host`, `--port`, `--db`,
`--retention-days`, `--max-message-bytes`, `--pub-port`, `--pull-port`,
`--lease-sec`, `--no-pubsub`) overrides the corresponding config field for
that invocation only — the same CLI-flag-over-config precedence every other
`pm-*` process uses.

If you prefer to generate this block instead of writing it by hand,
`pm-config-gen` can emit it with `--log-server` and the associated
`--log-server-*` options — see "Log server options" and "Log server LALF-PS
options" in
[Generate Configs with pm-config-gen](../../operator-guide/part-2-configure/010-the-configuration-workflow.md#generate-configs-with-pm-config-gen)
above.


## Engine Behavior Flags

### `sessions_enabled`

```yaml
sessions_enabled: true
```

When `true`, the engine starts in `CLOSED` and accepts scheduler transitions.
When `false`, the engine starts in `CONTINUOUS` and ignores scheduler
transitions.

| Scenario                           | Effective value |
|------------------------------------|-----------------|
| Config file present, field absent  | `true`          |
| No config file (unrestricted mode) | `false`         |

### `enforce_collars`

```yaml
enforce_collars: true
```

Controls whether configured price collars reject incoming orders. This defaults
to `true` and should normally remain enabled outside tests.

### `enforce_circuit_breakers`

```yaml
enforce_circuit_breakers: true
```

Controls whether configured circuit breakers can halt symbols. This defaults to
`true` and should normally remain enabled outside tests.

### `engine_tuning`

```yaml
engine_tuning:
  snapshot_interval_sec: 0.5
  quote_history_maxlen: 30
  drop_copy_buffer_size: 10000
  recent_trades_maxlen: 20
  depth_snapshot_tolerance_ticks: 100
```

`engine_tuning` groups low-level runtime retention and throttling knobs that
affect memory usage, snapshot cost, and replay depth. All of them are optional;
omitted fields fall back to built-in defaults.

### `engine_tuning.snapshot_interval_sec`

```yaml
engine_tuning:
  snapshot_interval_sec: 0.5
```

Controls the per-symbol throttle window for `book.<SYMBOL>` publications from
dirty books.

Rules:

- must be numeric
- must be greater than zero
- defaults to `0.5` seconds when omitted

### `engine_tuning.quote_history_maxlen`

```yaml
engine_tuning:
  quote_history_maxlen: 30
```

Controls how many recently inactivated quotes per gateway are retained in
memory for `QLEGS SHOW=RECENT` / `SHOW=ALL`.

Rules:

- must be an integer
- must be greater than zero
- defaults to `30` when omitted

### `engine_tuning.drop_copy_buffer_size`

```yaml
engine_tuning:
  drop_copy_buffer_size: 10000
```

Controls how many drop-copy events are retained in memory for replay after a
subscriber reconnects.

Rules:

- must be an integer
- must be greater than zero
- defaults to `10000` when omitted

### `engine_tuning.recent_trades_maxlen`

```yaml
engine_tuning:
  recent_trades_maxlen: 20
```

Controls how many recent trade rows each order book keeps for snapshots and
diagnostics.

Rules:

- must be an integer
- must be greater than zero
- defaults to `20` when omitted

### `engine_tuning.depth_snapshot_tolerance_ticks`

```yaml
engine_tuning:
  depth_snapshot_tolerance_ticks: 100
```

Controls the depth window around the last trade, measured in ticks, when the
engine publishes aggregated depth snapshots.

Rules:

- must be an integer
- must be greater than zero
- defaults to `100` when omitted


## Participant Defaults

The optional top-level `participant_defaults` block holds values that every
`participants` entry **inherits when it omits the key**. Use it to state a
uniform policy once instead of repeating it on each gateway.

```yaml
participant_defaults:
  smp_action: CANCEL_AGGRESSOR
  disconnect_behaviour: CANCEL_ALL

participants:
  - id: TRADER01             # inherits both defaults
  - id: TRADER02
    smp_action: NONE         # explicit: allows self-trades on this gateway
  - id: OPS01
    role: ADMIN
    disconnect_behaviour: LEAVE_ALL
```

| Field                  | Required | Accepted values                                  | Default when omitted |
|------------------------|---------:|--------------------------------------------------|----------------------|
| `smp_action`           |       No | `NONE`, `CANCEL_AGGRESSOR`, `CANCEL_RESTING`, `CANCEL_BOTH` | `NONE`               |
| `disconnect_behaviour` |       No | `CANCEL_QUOTES_ONLY`, `CANCEL_ALL`, `LEAVE_ALL`  | `CANCEL_QUOTES_ONLY` |

Rules:

- a gateway's effective value is its own key, then `participant_defaults`, then the
  built-in default shown above
- an explicit gateway value always wins, including `smp_action: NONE` when the
  default is something else
- the block applies to every role; a `disconnect_behaviour` default of
  `CANCEL_ALL` also reaches `ADMIN` and `MARKET_MAKER` entries that omit the key,
  so give those entries their own value when they need a different behaviour
- `participant_defaults` must be a mapping, values are case-insensitive, and any key
  other than the two above is rejected at load (a mistyped name is not
  silently ignored)
- per-order `SMP=` still outranks both (see the `smp_action` note below)

`pm-config-gen` writes the block with `--participant-default-smp` and
`--participant-default-disconnect`, `pm-cverifier` checks it (`S118`–`S120`), and the
config GUI edits it under **Basics → Participants**.

## Participants

Only gateway IDs listed under `participants` may connect and submit orders when
a config file exists.

```yaml
participants:
  - id: TRADER01
    description: Student workstation 1
    role: TRADER
    disconnect_behaviour: CANCEL_ALL
```

### Participant Fields

| Field                   | Required | Accepted values / type                                                  | Default                       |
|-------------------------|---------:|-------------------------------------------------------------------------|-------------------------------|
| `id`                    |      Yes | Non-empty string, uppercased by parser                                  | None                          |
| `description`           |       No | String or null                                                          | Empty string                  |
| `role`                  |       No | `TRADER`, `MARKET_MAKER`, `ADMIN`                                       | `TRADER`                      |
| `disconnect_behaviour`  |       No | `CANCEL_QUOTES_ONLY`, `CANCEL_ALL`, `LEAVE_ALL`                         | `participant_defaults`, then `CANCEL_QUOTES_ONLY` |
| `quote_refresh_policy`  |       No | `INACTIVATE_ON_ANY_FILL`, `INACTIVATE_ON_FULL_FILL`, `NEVER_INACTIVATE` | `INACTIVATE_ON_ANY_FILL`      |
| `enforce_mm_obligation` |       No | Boolean                                                                 | Global MM default             |
| `mm_max_spread_ticks`   |       No | Positive integer                                                        | Global MM default, then `10`  |
| `mm_min_qty`            |       No | Positive integer                                                        | Global MM default, then `100` |
| `mm_obligations`        |       No | Per-symbol mapping                                                      | Empty mapping                 |
| `smp_action`            |       No | `NONE`, `CANCEL_AGGRESSOR`, `CANCEL_RESTING`, `CANCEL_BOTH`             | `participant_defaults`, then `NONE` |

!!! note "`smp_action` is a fallback default, not an override"
    `participants[].smp_action` is the self-match-prevention action the
    engine applies to this gateway's orders **when the order itself doesn't
    specify one**:

    - `QUOTE` legs (the bid/ask orders a `QUOTE` command generates via
      `pm-alf-gwy` or the ALF console) have no per-request SMP concept of
      their own, so they **always** use this gateway default.
    - `NEW` orders and combo orders/legs submitted through `pm-alf-gwy`, the
      ALF console, or the REST API gateway each carry their own optional
      per-order `SMP=` field (see the `NEW` command in
      [ALF Protocol](../../protocols-and-clients/part-2-specifications/010-alf.md)). If the client sends an
      explicit `SMP=` — including `SMP=NONE`, a deliberate request to allow
      self-trades — that value is always honoured as-is. Only when the
      client omits `SMP=` entirely does the engine fall back to this
      gateway's `smp_action` (or the inherited `participant_defaults.smp_action`),
      and finally to `NONE` if neither is configured.

    In short: an explicit per-order `SMP=` always wins; `participants[].smp_action`
    only fills the gap when the client didn't say anything.

Nested `mm_obligations.<SYMBOL>` entries support these fields:

| Field                   | Required | Accepted values / type                                  | Default                         |
|-------------------------|---------:|---------------------------------------------------------|---------------------------------|
| `enforce_mm_obligation` |       No | Boolean                                                 | Gateway `enforce_mm_obligation` |
| `max_spread_ticks`      |       No | Integer; use positive values for a valid spread limit   | Gateway `mm_max_spread_ticks`   |
| `min_qty`               |       No | Integer; use positive values for a valid quantity floor | Gateway `mm_min_qty`            |

Inside `mm_obligations`, use this shape:

```yaml
participants:
  - id: MM01
    role: MARKET_MAKER
    mm_obligations:
      AAPL:
        enforce_mm_obligation: true
        max_spread_ticks: 6
        min_qty: 300
```

Use `max_spread_ticks` and `min_qty` inside `mm_obligations`; do not use the
flat-field names `mm_max_spread_ticks` and `mm_min_qty` there.

### Role Privileges

| Role           | Regular orders | Quotes | Admin circuit-breaker halt/resume | Typical use                               |
|----------------|---------------:|-------:|----------------------------------:|-------------------------------------------|
| `TRADER`       |            Yes |     No |                                No | Students, manual participants, AI traders |
| `MARKET_MAKER` |            Yes |    Yes |                                No | Quote providers                           |
| `ADMIN`        |            Yes |     No |                               Yes | Instructor/operator console               |

`MARKET_MAKER` gateways are the only gateways allowed to submit quotes. `ADMIN`
gateways can send exchange-wide circuit-breaker halt/resume commands.


## Market-Maker Obligation Defaults

`mm_obligation_defaults` defines quote-quality policy inherited by market-maker
gateways.

```yaml
mm_obligation_defaults:
  enforce_mm_obligation: true
  mm_max_spread_ticks: 20
  mm_min_qty: 100
  symbols:
    AAPL:
      enforce_mm_obligation: true
      mm_max_spread_ticks: 8
      mm_min_qty: 200
```

| Field                   | Required | Description                                      |
|-------------------------|---------:|--------------------------------------------------|
| `enforce_mm_obligation` |       No | Enable quote obligation checks                   |
| `mm_max_spread_ticks`   |       No | Maximum allowed bid/ask spread in ticks          |
| `mm_min_qty`            |       No | Minimum bid and ask quantity                     |
| `symbols`               |       No | Per-symbol overrides using the same three fields |

Defaults and validation:

| Field                                    | Accepted values / type | Default                           |
|------------------------------------------|------------------------|-----------------------------------|
| `enforce_mm_obligation`                  | Boolean                | `false`                           |
| `mm_max_spread_ticks`                    | Positive integer       | `10`                              |
| `mm_min_qty`                             | Positive integer       | `100`                             |
| `symbols.<SYMBOL>.enforce_mm_obligation` | Boolean                | Top-level `enforce_mm_obligation` |
| `symbols.<SYMBOL>.mm_max_spread_ticks`   | Positive integer       | Top-level `mm_max_spread_ticks`   |
| `symbols.<SYMBOL>.mm_min_qty`            | Positive integer       | Top-level `mm_min_qty`            |

The effective policy is resolved from most specific to least specific:

1. `participants[*].mm_obligations.<SYMBOL>`
2. `mm_obligation_defaults.symbols.<SYMBOL>`
3. Gateway flat fields
4. `mm_obligation_defaults` flat fields
5. Built-in defaults


## Symbol Universe

Only symbols declared under `symbols` are accepted by the configured engine.

!!! note "Adding a symbol is an IPO"
    Treat each symbol as an **initial listing (IPO)**: you set its opening
    reference price, issued shares, and (when a market maker is configured) its
    opening quote up front, and those values seed the book and both risk-control
    references. The symbol universe is fixed at startup — the engine does
    **not** support adding symbols intra-day. See
    [Adding or Removing Symbols](../../operator-guide/part-2-configure/010-the-configuration-workflow.md#adding-or-removing-symbols) and
    [Risk Controls - Day one (IPO) behaviour](../../operator-guide/part-4-run-a-market/040-risk-controls.md#day-one-ipo-behaviour).

```yaml
symbols:
  AAPL:
    tick_decimals: 2
  MSFT: {}
  TSLA:
```

Symbol keys are uppercased. The value for a symbol may be a mapping, `{}`, or
null.

### Symbol Fields

| Field                 |    Required | Type / accepted values          | Description                                                |
|-----------------------|------------:|----------------------------------|-------------------------------------------------------------|
| `tick_decimals`       |          No | Integer `0..8`                  | Decimal places used to convert display prices to ticks     |
| `level`               |          No | Key from `risk_controls.levels` | Named collar profile                                       |
| `outstanding_shares`  | Conditional | Positive integer                | Required only if the symbol is an index constituent        |
| `last_buy_price`      |          No | Number                          | Initial last-buy reference when no persisted stat exists   |
| `last_sell_price`     |          No | Number                          | Initial last-sell reference when no persisted stat exists  |
| `collar`              |          No | Mapping                         | Symbol-level collar override                                |
| `circuit_breaker`     |          No | Mapping                         | Symbol-level circuit-breaker override                       |
| `market_maker_quotes` | Conditional | List of mappings                | Required (non-empty) only if a `MARKET_MAKER` gateway exists |

### Mandatory Fields

None of `tick_decimals`, `level`, `last_buy_price`, `last_sell_price`, `collar`,
or `circuit_breaker` are ever mandatory — each has a built-in default or is
simply left inactive when omitted. Two fields become mandatory, but only under
specific conditions:

- **`market_maker_quotes`** — becomes mandatory (must be a non-empty list) for
  *every* symbol as soon as any `participants` entry has `role: MARKET_MAKER`,
  unless the top-level `require_mm_seed_quotes` is explicitly set to `false`
  (default `true`). With `require_mm_seed_quotes: false`, a `MARKET_MAKER`
  gateway may exist with no `market_maker_quotes` entries at all. If no
  `MARKET_MAKER` gateway is configured, this field can be omitted for every
  symbol regardless of `require_mm_seed_quotes`.
- **`outstanding_shares`** — becomes mandatory (must be a positive integer)
  only for symbols listed in an `indices[].constituents` entry (see
  [Configuring `pm-index`](#configuring-pm-index)). A symbol not referenced by
  any index does not need `outstanding_shares`.

### Collar Reference Price Selection

When a symbol ends up with an active collar (via `symbols.<SYMBOL>.collar`,
its `level`, or `risk_controls.default_level` — see
[Risk Controls and Collars](#risk-controls-and-collars)), the engine derives
the collar's static-band `reference_price` at startup as follows:

1. Persisted `<DATA_DIR>/book_stats.json` values are restored first (see
  [Startup and Persistence Order](../../operator-guide/part-2-configure/010-the-configuration-workflow.md#startup-and-persistence-order)). If the
   symbol has a persisted `last_buy_price`, it is used.
2. Otherwise, if the symbol has a persisted `last_sell_price`, it is used.
3. Otherwise, fall back to the config file's `last_buy_price`.
4. Otherwise, fall back to the config file's `last_sell_price`.
5. If none of the above are set, the collar is still parsed but is **not**
   activated for that symbol — no collar check runs for it at all, even
   though `enforce_collars: true` and a `collar`/`level` section are present.

In short: **persisted `book_stats.json` prices always take precedence over the
`last_buy_price` / `last_sell_price` seed values in `engine_config.yaml`**, so
the collar tracks the most recently known trading price instead of a
config value that may go stale as the session progresses. This uses the same
resolved last-buy/last-sell prices that seed the order book itself, so the
collar reference and the book's displayed last prices never disagree.

Orders for unknown symbols are rejected with:

```text
Symbol not configured: UNKNOWN
```


## Risk Controls and Collars

`risk_controls` defines reusable collar levels.

```yaml
risk_controls:
  default_level: L2
  levels:
    L1:
      collar:
        static_band_pct: 0.30
        dynamic_band_pct: 0.05
    L2:
      collar:
        static_band_pct: 0.20
        dynamic_band_pct: 0.02
```

### Per-symbol risk-level assignment

Use per-symbol risk levels when different symbols should inherit different
named collar profiles from `risk_controls.levels`.

You can assign the symbol level directly in YAML:

```yaml
risk_controls:
  default_level: DEFAULT
  levels:
    DEFAULT:
      collar:
        static_band_pct: 0.20
        dynamic_band_pct: 0.02
    CORE:
      collar:
        static_band_pct: 0.18
        dynamic_band_pct: 0.02
    HIGH_BETA:
      collar:
        static_band_pct: 0.12
        dynamic_band_pct: 0.04

symbols:
  AAPL:
    level: CORE
  TSLA:
    level: HIGH_BETA
```

Or generate the same structure from CLI:

```bash
pm-config-gen \
  --symbols AAPL TSLA \
  --participants TRADER01 \
  --risk-level CORE:0.18:0.02 \
  --risk-level HIGH_BETA:0.12:0.04 \
  --symbol-risk-level AAPL:CORE \
  --symbol-risk-level TSLA:HIGH_BETA
```

Semantics:

- `symbols.<SYMBOL>.level` selects one named profile from
  `risk_controls.levels`.
- If `level` is omitted, the symbol uses `risk_controls.default_level` when
  present.
- If neither a symbol level nor `default_level` applies, the symbol has no
  collar unless `symbols.<SYMBOL>.collar` is defined directly.
- `symbols.<SYMBOL>.collar` remains the highest-priority per-field override
  over any selected level.

### Risk-control Fields

| Field                   | Required | Accepted values / type                      | Default       |
|-------------------------|---------:|---------------------------------------------|---------------|
| `default_level`         |       No | Non-empty string matching a key in `levels` | None          |
| `levels`                |       No | Mapping of named level configs              | Empty mapping |
| `levels.<LEVEL>`        |       No | Mapping; level name is uppercased           | None          |
| `levels.<LEVEL>.collar` |       No | Mapping                                     | Empty mapping |

### Collar Fields

Collars may appear under `risk_controls.levels.<LEVEL>.collar` or under
`symbols.<SYMBOL>.collar`.

| Field              | Required | Accepted values / type | Default when a collar is active |
|--------------------|---------:|------------------------|---------------------------------|
| `static_band_pct`  |       No | Number in `(0, 1)`     | `0.20`                          |
| `dynamic_band_pct` |       No | Number in `(0, 1)`     | `0.02`                          |

Meaning of collar values:

- `static_band_pct` is an absolute guard around the symbol reference price
  (for example prior close or seeded last price). A value of `0.20` means
  allow prices within ±20% of that reference.
- `dynamic_band_pct` is an incremental guard around the latest trade price.
  A value of `0.02` means allow prices within ±2% of the latest fill.

This is the same behavior described in [Risk Controls](../../operator-guide/part-4-run-a-market/040-risk-controls.md)
and implemented in `src/edumatcher/engine/collar.py`.

Validation rules:

- `risk_controls` must be a mapping
- `risk_controls.default_level` must reference a key under `risk_controls.levels`
- each `levels.<LEVEL>.collar` must be a mapping when present
- `risk_controls.levels.<LEVEL>.circuit_breaker` is not supported; use top-level `circuit_breaker_defaults`
- collar percentages must be in `(0, 1)` after level and symbol overrides are merged

A symbol only gets a collar if at least one of these is present:
`symbols.<SYMBOL>.collar`, the symbol's `level` collar, or the
`risk_controls.default_level` collar. If none of them apply, the symbol has
**no collar at all**, even when `enforce_collars: true`.

When a collar *is* active, its two fields are resolved most-specific first:

1. `symbols.<SYMBOL>.collar` (per-field override)
2. `symbols.<SYMBOL>.level` collar
3. `risk_controls.default_level` collar
4. built-in field defaults (`static_band_pct: 0.20`, `dynamic_band_pct: 0.02`)

The built-in defaults in step 4 only fill in fields that none of the higher tiers
set; they never create a collar on their own.


## Circuit Breakers

`circuit_breaker_defaults` defines the default threshold ladder. Symbol-level
`circuit_breaker` sections merge over it field by field.

For an operational comparison of symbol-level circuit breakers versus symbol
price collars, see [Risk Controls - Price collars vs circuit breakers](../../operator-guide/part-4-run-a-market/040-risk-controls.md#price-collars-vs-circuit-breakers).

```yaml
circuit_breaker_defaults:
  reference_window_ns: 300000000000
  levels:
    L1:
      price_shift_pct: 0.07
      halt_duration_ns: 300000000000
    L2:
      price_shift_pct: 0.13
      halt_duration_ns: 900000000000
    L3:
      price_shift_pct: 0.20
      halt_duration_ns:

symbols:
  TSLA:
    circuit_breaker:
      levels:
        L1:
          halt_duration_ns: 600000000000
```

Validation rules:

- `circuit_breaker_defaults` must be a mapping when present
- `levels` must be a non-empty mapping after defaults and symbol overrides merge
- each level requires `price_shift_pct` in `(0, 1)`
- `halt_duration_ns` must be a positive integer or null
- `reference_window_ns` is converted to integer nanoseconds

A halt has no resumption setting, and deliberately so. The halt period *is* a
reopening auction's call phase — LIMIT orders are accepted and rest, market
and immediate-or-cancel orders are rejected, and no matching runs — so every
halt ends in an uncross at the equilibrium price. Resuming without one would
restart continuous matching on a book that had been accumulating crossed
interest for the whole halt.

A symbol only gets a circuit breaker if `circuit_breaker_defaults` or its own
`symbols.<SYMBOL>.circuit_breaker` section is present. If neither exists, the
symbol has **no circuit breaker at all**, even when
`enforce_circuit_breakers: true`.

When a breaker *is* active, configuration is resolved as follows:

1. `symbols.<SYMBOL>.circuit_breaker` (per-level, per-field override)
2. `circuit_breaker_defaults`
3. built-in ladder fallback (L1 7%/5m, L2 13%/15m, L3 20%/rest-of-day),
   used **only** when a circuit-breaker section is present but supplies no
   `levels`

### Circuit-breaker Fields

Circuit breakers may appear under `circuit_breaker_defaults` or under
`symbols.<SYMBOL>.circuit_breaker`. Symbol-level fields merge over defaults.

| Field                             |                     Required | Accepted values / type               | Default                                            |
|-----------------------------------|-----------------------------:|--------------------------------------|----------------------------------------------------|
| `reference_window_ns`             |                           No | Integer nanoseconds                  | `300000000000`                                     |
| `levels`                          | Yes when a breaker is active | Non-empty mapping after merging      | Built-in L1/L2/L3 only when no levels are supplied |
| `levels.<LEVEL>.price_shift_pct`  |                          Yes | Number in `(0, 1)`                   | None                                               |
| `levels.<LEVEL>.halt_duration_ns` |                           No | Positive integer nanoseconds or null | Null                                               |


## Market-Maker Quote Seeds

`market_maker_quotes` create linked bid/ask quote legs at engine startup.

```yaml
symbols:
  AAPL:
    market_maker_quotes:
      - gateway_id: MM01
        quote_id: SEED-MM01-AAPL
        bid_price: 209.00
        ask_price: 211.00
        bid_qty: 2000
        ask_qty: 2000
        tif: DAY
        seed_once: true
```

| Field        | Required | Accepted values / type                      | Default   | Description                                               |
|--------------|---------:|---------------------------------------------|-----------|-----------------------------------------------------------|
| `gateway_id` |      Yes | Non-empty string, uppercased                | None      | Configured `MARKET_MAKER` gateway that owns the quote     |
| `quote_id`   |       No | String; empty string is treated as omitted  | Generated | Explicit quote label                                      |
| `bid_price`  |      Yes | Number                                      | None      | Display price converted to ticks by the engine            |
| `ask_price`  |      Yes | Number greater than `bid_price`             | None      | Display price converted to ticks by the engine            |
| `bid_qty`    |      Yes | Positive integer                            | None      | Bid-side quantity                                         |
| `ask_qty`    |      Yes | Positive integer                            | None      | Ask-side quantity                                         |
| `tif`        |       No | `DAY`, `GTC`, `ATO`, `ATC`                  | `DAY`     | Time in force                                             |
| `seed_once`  |       No | Boolean-like value; use YAML `true`/`false` | `true`    | Skip injection after `book_stats.json` has symbol history |

Validation rules:

- quote seeds must be mappings inside a list
- `gateway_id` must reference a configured gateway with `role: MARKET_MAKER`
- `bid_price` must be lower than `ask_price`
- quantities must be positive
- if any configured gateway has `role: MARKET_MAKER`, every symbol must define at least one quote seed

Quote legs are not persisted to `gtc_orders.json`; config seeds remain the source
of truth. `seed_once: true` skips injection after `book_stats.json` has history
for the symbol. `seed_once: false` injects on every startup.


## Startup Market-Maker Combo Seeds

`market_maker_combos` inject startup combo orders through the same combo path used
by live combo entry.

```yaml
market_maker_combos:
  - combo_id: SEED-PAIR-AAPL-MSFT
    combo_type: AON
    tif: DAY
    legs:
      - symbol: AAPL
        side: BUY
        order_type: LIMIT
        quantity: 100
        price: 20950
        smp_action: NONE
      - symbol: MSFT
        side: SELL
        order_type: LIMIT
        quantity: 50
        price: 41550
        smp_action: NONE
```

Combo fields:

| Field        | Required | Accepted values / type                        |
|--------------|---------:|-----------------------------------------------|
| `combo_id`   |      Yes | Non-empty string                              |
| `combo_type` |       No | `AON`; defaults to `AON`                      |
| `tif`        |       No | `DAY`, `GTC`, `ATO`, `ATC`; defaults to `DAY` |
| `legs`       |      Yes | List with 2 to 10 entries                     |

Leg fields:

| Field        |    Required | Accepted values / type                                                            |
|--------------|------------:|-----------------------------------------------------------------------------------|
| `symbol`     |         Yes | Configured symbol, unique inside the combo                                        |
| `side`       |         Yes | `BUY`, `SELL`                                                                     |
| `order_type` |         Yes | `MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT`, `FOK`, `ICEBERG`, `IOC`, `TRAILING_STOP` |
| `quantity`   |         Yes | Integer quantity                                                                  |
| `price`      | Conditional | Display price for priced order types, on the leg symbol's tick grid               |
| `stop_price` | Conditional | Display stop price for stop order types, on the leg symbol's tick grid            |
| `smp_action` |          No | `NONE`, `CANCEL_AGGRESSOR`, `CANCEL_RESTING`, `CANCEL_BOTH`; if omitted, falls back to the seeding gateway's `participants[].smp_action` (§below), then `NONE` |

Combo leg values are passed to `ComboLeg.from_dict()`, so these are the only leg
fields used by current config parsing. Unlike quote seeds, combo legs do not
include a `gateway_id`; startup combo ownership is assigned by the engine's combo
seed path — that combo-level `gateway_id` is what an omitted `smp_action` falls
back through.

Prefer `tif: DAY` for repeatable demo seeds. `GTC` combo seeds can interact with
restored `gtc_combos.json` state and duplicate intended startup liquidity if you
are not managing persistence deliberately.


## Session Schedule

The scheduler reads `schedule` and sends transitions to the engine. Every
weekday (`mon`..`sun`) resolves to its own five-time block, or CLOSED if
unconfigured; `weekdays:`/`weekend:` are shortcuts for repeating one block
across Monday-Friday or Saturday+Sunday, and `holidays:` gives bank holidays
their own schedule instead of defaulting to CLOSED. See
[Session Scheduling → Configuring the schedule](../../operator-guide/part-4-run-a-market/030-sessions-and-scheduling.md#configuring-the-schedule)
for the full set of keys, precedence rules, and worked examples.

```yaml
schedule:
  weekdays:
    pre_open: "09:00"
    opening_auction_start: "09:25"
    continuous_start: "09:30"
    closing_auction_start: "16:00"
    closing_auction_end: "16:05"
```

| Key         | Required | Applies to                                    |
|-------------|---------:|------------------------------------------------|
| `weekdays`  |       No | Monday-Friday, for any day not overridden below |
| `mon`..`fri`|       No | One weekday, overriding `weekdays` for that day |
| `weekend`   |       No | Saturday and Sunday — mutually exclusive with `sat`/`sun` |
| `sat`, `sun`|       No | One weekend day, overriding `weekend` for that day |
| `holidays`  |       No | Bank holidays for the configured `country`     |

Every block that is present MUST define all five transition times
(`pre_open`, `opening_auction_start`, `continuous_start`,
`closing_auction_start`, `closing_auction_end`) — there is no per-key
fallback for a partial block. A day with nothing resolved for it (not
`weekdays`/`weekend` and not individually specified) is CLOSED. If no usable
`schedule` section is present at all, `pm-scheduler` uses built-in defaults
(the times shown above, applied as `weekdays`; weekends and holidays CLOSED).
With `pm-scheduler --now`, the wall-clock values are ignored and transitions
are sent immediately with short delays.

The default session path is:

```text
PRE_OPEN -> OPENING_AUCTION -> CONTINUOUS -> CLOSING_AUCTION -> CLOSED
```

### `country`

```yaml
country: Sweden
```

`country` is a top-level key — a sibling of `schedule`, not nested under it.
`pm-scheduler` uses it to decide, for a given calendar day, whether the
`holidays:` block applies (see the table above), using the
[`python-holidays`](https://pypi.org/project/holidays/) package to resolve
the holiday calendar.

| Aspect | Value |
|---|---|
| Accepted forms | Country name (`"Sweden"`) or ISO 3166-1 alpha-2 code (`"SE"`) |
| Default when omitted | `"Sweden"` |
| Behavior on an unrecognized value | Falls back to `"Sweden"` and logs a warning |
| Weekends | No longer forced CLOSED — `weekend:`/`sat:`/`sun:` can give them their own schedule, same as any weekday |

Under `--daily`, a CLOSED day is skipped and the scheduler sleeps through to
the next day that resolves to a schedule, rather than the next calendar day.
In single-shot mode (the default, no `--daily`), the scheduler simply sends
no transitions and exits if today is CLOSED. See
[Session Scheduling → Bank holidays and weekends](../../operator-guide/part-4-run-a-market/030-sessions-and-scheduling.md#bank-holidays-and-weekends)
for the full behavior breakdown by run mode.


## Formal Specification

This section is a complete machine-readable-style reference for every field
parsed from `engine_config.yaml`. Types follow Python conventions: `bool`,
`int`, `float`, `str`. "Enum" means the field must match one of the listed
string values exactly (case-insensitive during loading; stored in uppercase).

For the auxiliary gateway processes (`pm-alf-gwy`, `pm-balf-gwy`, `pm-md-gwy`,
`pm-ralf-gwy`, `pm-api-gwy`) and the full normative schema, see
[App Config Spec](030-formal-specification.md), which governs if the two documents
ever disagree.
Ranges use mathematical interval notation: `(a, b)` is open (exclusive),
`[a, b]` is closed (inclusive).

---

### Top-level fields

| Field                      | Type    | Required | Default                                               | Allowed values / range | Constraint                               |
|----------------------------|---------|---------:|-------------------------------------------------------|------------------------|------------------------------------------|
| `symbols`                  | mapping |      Yes | —                                                     | —                      | Must contain at least one entry          |
| `participants`             | list    |      Yes | —                                                     | —                      | Non-empty list of participant mappings   |
| `sessions_enabled`         | bool    |       No | `true` when file exists, `false` in unrestricted mode | `true`, `false`        | Must be a YAML boolean                   |
| `enforce_collars`          | bool    |       No | `true`                                                | `true`, `false`        | Must be a YAML boolean                   |
| `enforce_circuit_breakers` | bool    |       No | `true`                                                | `true`, `false`        | Must be a YAML boolean                   |
| `engine_tuning`            | mapping |       No | —                                                     | —                      | Runtime tuning block                     |
| `mm_obligation_defaults`   | mapping |       No | —                                                     | —                      | —                                        |
| `risk_controls`            | mapping |       No | —                                                     | —                      | —                                        |
| `circuit_breaker_defaults` | mapping |       No | —                                                     | —                      | —                                        |
| `market_maker_combos`      | list    |       No | `[]`                                                  | —                      | Each entry must be a mapping             |
| `schedule`                 | mapping |       No | —                                                     | —                      | Parsed by scheduler and stored by engine |
| `require_mm_seed_quotes`   | bool    |       No | `true`                                                | `true`, `false`        | If `false`, a `MARKET_MAKER` gateway may exist with no `market_maker_quotes` (see [Mandatory Fields](#mandatory-fields)) |
| `country`                  | str     |       No | `"Sweden"`                                            | Any non-empty string   | Used for the scheduler's holiday calendar; an unrecognized value falls back to the default (see `M026` in [Config Verifier](../../operator-guide/part-2-configure/020-config-verifier.md)) |
| `indices`                  | list    |       No | `[]`                                                  | —                      | At most 5 entries; see [Configuring `pm-index`](#configuring-pm-index) for the per-index field reference |
| `auction_indicative_interval_sec` | float | No | `1.0`                                            | Any number             | Must be `> 0`                            |
| `participant_defaults`     | mapping |       No | —                                                     | `smp_action`, `disconnect_behaviour` | Inherited by `participants` entries that omit them; see [Participant Defaults](#participant-defaults) |
| `alf_gateway`              | mapping |       No | —                                                     | —                      | `pm-alf-gwy` settings; see [Configuring `pm-alf-gwy`](#configuring-pm-alf-gwy) |
| `balf_gateway`             | mapping |       No | —                                                     | —                      | `pm-balf-gwy` settings; see [Configuring `pm-balf-gwy`](#configuring-pm-balf-gwy) |
| `market_data_gateway`      | mapping |       No | —                                                     | —                      | `pm-md-gwy` settings; see [Configuring `pm-md-gwy`](#configuring-pm-md-gwy) |
| `post_trade_gateway`       | mapping |       No | —                                                     | —                      | `pm-ralf-gwy` settings; see [Configuring `pm-ralf-gwy`](#configuring-pm-ralf-gwy) |
| `dc_gateway`               | mapping |       No | —                                                     | —                      | `pm-dc-gwy` settings; see [Drop-Copy Gateway](../../operator-guide/part-5-gateways/060-drop-copy-gateway.md) |
| `log_server`               | mapping |       No | —                                                     | —                      | `pm-log-srv` settings; see [Configuring `pm-log-srv`](#configuring-pm-log-srv) |
| `api_gateways`             | mapping |       No | —                                                     | —                      | Named `pm-api-gwy` instances; see [Configuring `pm-api-gwy`](#configuring-pm-api-gwy) |

### `engine_tuning` fields

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `snapshot_interval_sec` | float | No | `0.5` | Any number | Must be `> 0` |
| `quote_history_maxlen` | int | No | `30` | Positive integer | Must be `> 0` |
| `drop_copy_buffer_size` | int | No | `10000` | Positive integer | Must be `> 0` |
| `recent_trades_maxlen` | int | No | `20` | Positive integer | Must be `> 0` |
| `depth_snapshot_tolerance_ticks` | int | No | `100` | Positive integer | Must be `> 0` |

---

### `participants[]` — gateway entry fields

| Field                   | Type        | Required | Default                                                           | Allowed values / range                                                  | Constraint                                 |
|-------------------------|-------------|---------:|-------------------------------------------------------------------|-------------------------------------------------------------------------|--------------------------------------------|
| `id`                    | str         |      Yes | —                                                                 | Any non-empty string                                                    | Uppercased; must be unique within the list |
| `description`           | str or null |       No | `""`                                                              | Any string or null                                                      | Null is coerced to `""`                    |
| `role`                  | Enum        |       No | `TRADER`                                                          | `TRADER`, `MARKET_MAKER`, `ADMIN`                                       | Case-insensitive                           |
| `disconnect_behaviour`  | Enum        |       No | `CANCEL_QUOTES_ONLY`                                              | `CANCEL_QUOTES_ONLY`, `CANCEL_ALL`, `LEAVE_ALL`                         | Case-insensitive                           |
| `quote_refresh_policy`  | Enum        |       No | `INACTIVATE_ON_ANY_FILL`                                          | `INACTIVATE_ON_ANY_FILL`, `INACTIVATE_ON_FULL_FILL`, `NEVER_INACTIVATE` | Case-insensitive                           |
| `enforce_mm_obligation` | bool        |       No | From `mm_obligation_defaults.enforce_mm_obligation`, else `false` | `true`, `false`                                                         | Must be a YAML boolean                     |
| `mm_max_spread_ticks`   | int         |       No | From `mm_obligation_defaults.mm_max_spread_ticks`, else `10`      | Integer                                                                 | Must be `> 0`                              |
| `mm_min_qty`            | int         |       No | From `mm_obligation_defaults.mm_min_qty`, else `100`              | Integer                                                                 | Must be `> 0`                              |
| `mm_obligations`        | mapping     |       No | `{}`                                                              | Mapping of symbol → obligation entry                                    | Symbol keys are uppercased                 |
| `smp_action`            | Enum        |       No | `NONE`                                                            | `NONE`, `CANCEL_AGGRESSOR`, `CANCEL_RESTING`, `CANCEL_BOTH`             | Case-insensitive; fallback default used when an order (`NEW`, combo, or `QUOTE`) doesn't specify its own `SMP=` |

### `participants[].mm_obligations.<SYMBOL>` fields

| Field                   | Type | Required | Default                         | Allowed values / range | Constraint             |
|-------------------------|------|---------:|---------------------------------|------------------------|------------------------|
| `enforce_mm_obligation` | bool |       No | Gateway `enforce_mm_obligation` | `true`, `false`        | Must be a YAML boolean |
| `max_spread_ticks`      | int  |       No | Gateway `mm_max_spread_ticks`   | Integer                | Must be `> 0`          |
| `min_qty`               | int  |       No | Gateway `mm_min_qty`            | Integer                | Must be `> 0`          |

---

### `mm_obligation_defaults` fields

| Field                   | Type    | Required | Default | Allowed values / range         | Constraint                                                          |
|-------------------------|---------|---------:|---------|--------------------------------|---------------------------------------------------------------------|
| `enforce_mm_obligation` | bool    |       No | `false` | `true`, `false`                | Must be a YAML boolean                                              |
| `mm_max_spread_ticks`   | int     |       No | `10`    | Integer                        | Must be `> 0`                                                       |
| `mm_min_qty`            | int     |       No | `100`   | Integer                        | Must be `> 0`                                                       |
| `symbols`               | mapping |       No | `{}`    | Symbol name → override mapping | Symbol keys are uppercased; each must reference a configured symbol |

### `mm_obligation_defaults.symbols.<SYMBOL>` fields

| Field                   | Type | Required | Default                           | Allowed values / range | Constraint             |
|-------------------------|------|---------:|-----------------------------------|------------------------|------------------------|
| `enforce_mm_obligation` | bool |       No | Top-level `enforce_mm_obligation` | `true`, `false`        | Must be a YAML boolean |
| `mm_max_spread_ticks`   | int  |       No | Top-level `mm_max_spread_ticks`   | Integer                | Must be `> 0`          |
| `mm_min_qty`            | int  |       No | Top-level `mm_min_qty`            | Integer                | Must be `> 0`          |

---

### `risk_controls` fields

| Field           | Type    | Required | Default | Allowed values / range            | Constraint                                        |
|-----------------|---------|---------:|---------|-----------------------------------|---------------------------------------------------|
| `default_level` | str     |       No | `null`  | Any non-empty string              | Must match a key in `risk_controls.levels` if set |
| `levels`        | mapping |       No | `{}`    | Level name → level config mapping | Level names are uppercased                        |

### `risk_controls.levels.<LEVEL>` fields

| Field    | Type    | Required | Default | Allowed values / range | Constraint                                               |
|----------|---------|---------:|---------|------------------------|----------------------------------------------------------|
| `collar` | mapping |       No | `{}`    | See collar fields      | Must be a mapping; `circuit_breaker` sub-key is rejected |

### Collar fields — in `risk_controls.levels.<LEVEL>.collar` or `symbols.<SYMBOL>.collar`

| Field              | Type  | Required | Default | Allowed values / range | Constraint                                                          |
|--------------------|-------|---------:|---------|------------------------|---------------------------------------------------------------------|
| `static_band_pct`  | float |       No | `0.20`  | `(0, 1)` exclusive     | Band truncates toward zero; makes range slightly tighter than exact |
| `dynamic_band_pct` | float |       No | `0.02`  | `(0, 1)` exclusive     | Same truncation rule                                                |

---

### `circuit_breaker_defaults` fields

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `reference_window_ns` | int | No | `300000000000` (5 min) | Positive integer nanoseconds | Coerced to `int` |
| `levels` | mapping | No | Built-in L1/L2/L3 ladder only when a CB section is present but omits `levels` | Level name → level config mapping | Values must be mappings |
| `reopening` | mapping | No | Built-in ACE defaults | Automated Corridor Expansion settings | Merges field-by-field over defaults |

### `circuit_breaker_defaults.reopening` and `symbols.<SYMBOL>.circuit_breaker.reopening` fields

Governs how a circuit-breaker halt ends — see
[Risk Controls - Automated Corridor Expansion](../../operator-guide/part-4-run-a-market/040-risk-controls.md#automated-corridor-expansion-ace).

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `enabled` | bool | No | `true` | `true` / `false` | When `false` a halt reopens at the equilibrium price with no corridor |
| `initial_band_pct` | float | No | `0.10` | `(0, 1)` exclusive | Corridor half-width as a fraction of the CB reference price |
| `expansions` | list | No | `[{0.10, 2 min}, {0.20, 5 min}]` | Non-empty list of mappings | The final entry repeats indefinitely. **Only valid under `circuit_breaker_defaults`**; per-symbol is an error (`S112`) |
| `expansions[].widen_pct` | float | Yes within an entry | — | `(0, 1)` exclusive | Added to the half-width; additive on the reference, not compounding |
| `expansions[].min_duration_ns` | int | Yes within an entry | — | Positive integer nanoseconds | Minimum length of that extension's call phase |
| `random_end_max_ns` | int | No | `30000000000` (30 s) | `>= 0` nanoseconds | Uniform random tail added to every call phase; `0` disables it |
| `random_seed` | int or null | No | `null` | Integer or `null` | Engine-wide. **Only valid under `circuit_breaker_defaults`**; per-symbol is an error |

### `circuit_breaker_defaults.levels.<LEVEL>` and `symbols.<SYMBOL>.circuit_breaker.levels.<LEVEL>` fields

Symbol-level entries merge over the defaults: only the fields you specify are overridden.

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `price_shift_pct` | float | Yes when creating a level | — | `(0, 1)` exclusive | Required in any level that originates from config; inherited from defaults for symbol overrides |
| `halt_duration_ns` | int or null | No | `null` | Positive integer nanoseconds, or `null`/omitted | `null` means rest-of-day halt; must be `> 0` when provided |

**Built-in default CB ladder** (used only when a circuit-breaker section exists
but supplies no `levels`; if no circuit-breaker section is present at all, the
symbol has no breaker):

| Level | `price_shift_pct` | `halt_duration_ns`      |
|-------|-------------------|-------------------------|
| L1    | `0.07`            | `300000000000` (5 min)  |
| L2    | `0.13`            | `900000000000` (15 min) |
| L3    | `0.20`            | `null` (rest-of-day)    |

---

### `symbols.<SYMBOL>` fields

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `tick_decimals` | int | No | `2` | `[0, 8]` inclusive | Must be an integer |
| `level` | str | No | `risk_controls.default_level` | Any non-empty string | Must reference a key in `risk_controls.levels` |
| `last_buy_price` | float | No | `null` | Any number | Overridden by persisted `book_stats.json` |
| `last_sell_price` | float | No | `null` | Any number | Overridden by persisted `book_stats.json` |
| `collar` | mapping | No | — | See collar fields | Merged over the level's collar; symbol wins on conflicting keys |
| `circuit_breaker` | mapping | No | — | See circuit-breaker fields | `levels` subkey merged over defaults; other keys replace |
| `market_maker_quotes` | list | No | `[]` | List of quote seed mappings | Required (non-empty) if any `MARKET_MAKER` gateway is configured, unless `require_mm_seed_quotes: false` (see [Mandatory Fields](#mandatory-fields)) |
| `outstanding_shares` | int | No | `null` | Positive integer | Required if the symbol is listed in an `indices[].constituents` entry (see [Mandatory Fields](#mandatory-fields)) |
| `order_limits` | mapping | No | — | See below | Rejected at `risk_controls.levels.<LEVEL>` — set per symbol only |

### `symbols.<SYMBOL>.order_limits` fields

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `max_order_qty` | int | No | `null` (no limit) | Positive integer | Must be `> 0` |
| `max_order_value` | float | No | `null` (no limit) | Any number | Must be `> 0` |

---

### `symbols.<SYMBOL>.market_maker_quotes[]` fields

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `gateway_id` | str | Yes | — | Any non-empty string | Uppercased; must reference a `MARKET_MAKER` gateway |
| `quote_id` | str | No | Auto-generated | Any string | Empty string treated as absent |
| `bid_price` | float | Yes | — | Any number | Must be `< ask_price` |
| `ask_price` | float | Yes | — | Any number | Must be `> bid_price` |
| `bid_qty` | int | Yes | — | Positive integer | Must be `> 0` |
| `ask_qty` | int | Yes | — | Positive integer | Must be `> 0` |
| `tif` | Enum | No | `DAY` | `DAY`, `GTC`, `ATO`, `ATC` | Case-insensitive |
| `seed_once` | bool | No | `true` | `true`, `false` | When `true`, skips injection if `book_stats.json` has history for this symbol |

---

### `market_maker_combos[]` fields

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `combo_id` | str | Yes | — | Any non-empty string | Must not be empty after stripping whitespace |
| `combo_type` | Enum | No | `AON` | `AON` | Case-insensitive |
| `tif` | Enum | No | `DAY` | `DAY`, `GTC`, `ATO`, `ATC` | Case-insensitive |
| `legs` | list | Yes | — | List of leg mappings | Must contain 2 to 10 entries |

### `market_maker_combos[].legs[]` fields

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `symbol` | str | Yes | — | Configured symbol | Uppercased; must be unique within the combo; must be in `symbols` |
| `side` | Enum | Yes | — | `BUY`, `SELL` | Case-insensitive |
| `order_type` | Enum | Yes | — | `MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT`, `FOK`, `ICEBERG`, `IOC`, `TRAILING_STOP` | Case-insensitive |
| `quantity` | int | Yes | — | Positive integer | — |
| `price` | float | Conditional | `null` | Display price | Required for `LIMIT`, `STOP_LIMIT`, `FOK`, `ICEBERG` (not enforced for `IOC`); must be a multiple of the leg symbol's tick size |
| `stop_price` | float | Optional | `null` | Display price | Not currently validated as required for any order type, including `STOP`/`STOP_LIMIT`/`TRAILING_STOP`; must be a multiple of the leg symbol's tick size |
| `smp_action` | Enum | No | Seeding gateway's `participants[].smp_action`, else `NONE` | `NONE`, `CANCEL_AGGRESSOR`, `CANCEL_RESTING`, `CANCEL_BOTH` | Case-insensitive |

!!! note "Combo leg prices use the leg symbol's scale"
    The legs of one combo trade different instruments, which need not share a
    tick size, so each leg's price is checked against its own symbol's
    `tick_decimals` rather than the combo's.

---

### `schedule` fields

Top level:

| Field | Type | Required | Applies to | Constraint |
|---|---|---:|---|---|
| `weekdays` | day block | No | Mon-Fri, for any day not overridden below | mutually exclusive with nothing; see individual-day override rule below |
| `mon`, `tue`, `wed`, `thu`, `fri` | day block | No | one weekday | overrides `weekdays` for that day only |
| `weekend` | day block | No | Sat+Sun, for either day not overridden below | mutually exclusive with `sat`/`sun` |
| `sat`, `sun` | day block | No | one weekend day | overrides `weekend` for that day only; mutually exclusive with `weekend` |
| `holidays` | day block | No | bank holidays for `country` | applies instead of the calendar day's own entry |

Each **day block** (the value of `weekdays`, `weekend`, `holidays`, or any
individual `mon`..`sun` key) is:

| Field | Type | Required | Default | Allowed values / range |
|---|---|---:|---|---|
| `pre_open` | str | Yes, if the block is present | — | `"HH:MM"` (local server time) |
| `opening_auction_start` | str | Yes, if the block is present | — | `"HH:MM"` (local server time) |
| `continuous_start` | str | Yes, if the block is present | — | `"HH:MM"` (local server time) |
| `closing_auction_start` | str | Yes, if the block is present | — | `"HH:MM"` (local server time) |
| `closing_auction_end` | str | Yes, if the block is present | — | `"HH:MM"` (local server time) |

A day block with any of the five keys missing is rejected — there is no
per-key default once a block is present at all. A day (or `holidays`) with no
block resolved for it is CLOSED. `weekend` and an individual `sat`/`sun` key
present together is also rejected.

---

### Cross-field validation rules

These constraints span multiple sections and are checked after all fields are
parsed:

1. If any gateway has `role: MARKET_MAKER`, every symbol in `symbols` must
   have at least one `market_maker_quotes` entry, unless top-level
   `require_mm_seed_quotes` is set to `false`.
2. Every `market_maker_quotes[].gateway_id` must reference a configured
   gateway with `role: MARKET_MAKER`.
3. Every `symbols.<SYMBOL>.level` must reference a key in
   `risk_controls.levels`.
4. `risk_controls.default_level` must reference a key in
   `risk_controls.levels`.
5. Every `mm_obligation_defaults.symbols.<SYMBOL>` key must reference a
   symbol in `symbols`.
6. Every `market_maker_combos[].legs[].symbol` must reference a symbol in
   `symbols`.
7. Symbols within one combo must be unique.
8. `risk_controls.levels.<LEVEL>.circuit_breaker` is explicitly rejected with
   an error; use top-level `circuit_breaker_defaults` instead.
9. `risk_controls.levels.<LEVEL>.order_limits` is explicitly rejected with an
   error; set `order_limits` on each symbol instead.



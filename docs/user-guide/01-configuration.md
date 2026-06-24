# Engine Configuration

!!! note "Learning objectives"
    After reading this page you will understand:

    - Which `engine_config.yaml` sections are required when a config file exists
    - How to generate a starter config with `pm-config-gen`
    - Which fields the current engine and scheduler parsers recognize
    - How to configure the optional `pm-ralf-gwy`, `pm-md-gwy`, and `pm-api-gateway` blocks
    - How to configure symbols, gateways, risk controls, market-maker seeds, combo seeds, and schedules
    - How to choose between minimal, medium, and fully featured configurations
    - Which checks to perform before using a config in a class, demo, or test


## Configuring the Exchange

The matching engine and session scheduler both read `engine_config.yaml`. The
engine uses it to define the symbol universe, authenticated ALF gateway IDs,
session mode, risk controls, market-maker policy, per-symbol outstanding shares,
and startup seeds. The scheduler uses only the optional `schedule` section.
The optional `post_trade_gateway`, `market_data_gateway`, and `api_gateways`
sections are read by `pm-ralf-gwy`, `pm-md-gwy`, and `pm-api-gateway`
respectively.

If the config file is absent, `pm-engine` starts in unrestricted mode: any symbol
and gateway can be used, and no startup seeds are loaded. If the config file is
present, the parser requires two sections:

- `symbols` - a mapping of accepted symbols; generated examples include a
  positive integer `outstanding_shares` field for each symbol
- `gateways.alf` - a list with at least one accepted ALF gateway

The sample `engine_config.yaml` intentionally keeps the
live configuration minimal and places the full parser-recognized shape in
comments. This page explains that shape in operational terms.

!!! warning "Only `gateways.alf` is parsed today"
    BALF and CALF are documented protocol designs, but `gateways.balf` and
    `gateways.calf` are not active engine configuration sections in the current
    parser. Do not add them to production configs expecting runtime behavior.

Protocol-specific gateway sections are expected to live under `gateways:` in
`engine_config.yaml` as protocols become implemented. Currently only
`gateways.alf` is active; `gateways.balf` and `gateways.calf` are reserved for
future releases.

- **ALF** uses a pipe-delimited text format (`FIELD=VALUE|FIELD=VALUE`) delivered through the interactive `pm-gateway` terminal process. This is the only order-entry protocol currently available.
- **BALF** will use fixed-width binary frames with sequence numbers and integer-scaled prices, targeting programmatic clients where text-parsing latency is undesirable. See the BALF appendix in the User Guide for the message layout specification.
- **CALF** will provide a subscribe/unsubscribe market-data feed delivering order-book snapshots, trade prints, and session-state changes over a persistent TCP connection with sequence-based gap detection. See the CALF appendix in the User Guide for the full protocol specification.


## File Location

By default, installed mode looks for `engine_config.yaml` in the current working
directory, while source-checkout mode uses the repository root. You can override
this with `--config` or `EDUMATCHER_CONFIG`.

```bash
pm-engine --verbose
pm-engine --verbose --config my_config.yaml

pm-scheduler
pm-scheduler --config my_config.yaml
```

If you are running from a Poetry checkout, prefix commands with `poetry run`.

### Missing-file Behavior

The engine and scheduler handle missing config differently:

| Process | Missing default config | Missing explicit `--config` |
|---|---|---|
| `pm-engine` | Starts unrestricted | Starts unrestricted for that path |
| `pm-scheduler` | Uses built-in schedule | Fatal error |

Unrestricted engine mode means there is no symbol allowlist, no gateway
allowlist, no configured risk levels, no seeded last prices, no seeded
market-maker quotes, no configured startup combos, and no outstanding share
metadata.


## Generate Configs with `pm-config-gen`

`pm-config-gen` creates a parser-compatible `engine_config.yaml` from concise
CLI inputs. It is designed for operators and instructors who want to bootstrap
new sessions without manually writing large YAML blocks.

Use it when:

- you are creating a new class/demo config from scratch
- you want consistent defaults and validation hints
- you need repeatable config generation in scripts

### Quick start

Installed mode:

```bash
pm-config-gen \
  --symbols AAPL MSFT \
  --gateways TRADER01 TRADER02 OPS01:ADMIN \
  --outstanding-shares AAPL:15400000000 \
  --outstanding-shares MSFT:7430000000 \
  --sessions-enabled \
  --output engine_config.yaml
```

Poetry/source mode:

```bash
poetry run pm-config-gen \
  --symbols AAPL MSFT \
  --gateways TRADER01 TRADER02 OPS01:ADMIN \
  --outstanding-shares AAPL:15400000000 \
  --outstanding-shares MSFT:7430000000 \
  --sessions-enabled \
  --output engine_config.yaml
```

Print to stdout only (no file write):

```bash
pm-config-gen \
  --symbols AAPL \
  --gateways TRADER01 \
  --outstanding-shares AAPL:15400000000 \
  --dry-run
```

### Important behavior

- If `--output` is omitted, YAML is printed to stdout.
- If `--output` exists, generation fails unless `--force` is set.
- If any gateway is `MARKET_MAKER` and you do not pass `--seed-mm-mid-range`,
  MM quote stubs are emitted with `bid_price: null` and `ask_price: null`.
  Fill these values before starting `pm-engine`.
- If you pass `--seed-mm-mid-range`, MM quotes are emitted with concrete prices
  on the configured tick grid.
- Loader validation is skipped only in the MM-stub case above. It runs
  automatically for non-MM configs and MM configs with seeded midpoints.

MM quote generation decision matrix:

| Gateway/flags state | Generated `market_maker_quotes` | Generated `last_buy_price` / `last_sell_price` |
|---|---|---|
| No `MARKET_MAKER` gateway configured | No MM quote section emitted | Only emitted if `--seed-last-prices` is set (as `null` placeholders) |
| `MARKET_MAKER` present, no `--seed-mm-mid-range` | Stub quotes with `bid_price: null`, `ask_price: null` | `null` placeholders only if `--seed-last-prices` is set |
| `MARKET_MAKER` present, with `--seed-mm-mid-range MIN:MAX` | Concrete bid/ask quote prices generated on tick grid | If `--seed-last-prices-from-mm` is set, both are set to the same midpoint used for seeded quotes |

In this guide, "MM stub" means a quote row exists but prices are `null` and must
be filled manually. "Full MM setup" means concrete bid/ask prices are generated
for each MM quote seed at generation time.

### Option reference

Required inputs:

| Option | Type | Description |
|---|---|---|
| `--symbols SYM [SYM ...]` | Repeatable tokens | Symbol universe (uppercased on parse) |
| `--gateways GW_SPEC [GW_SPEC ...]` | Repeatable tokens | Gateway specs as `ID[:ROLE[:DISCONNECT]]` |

Session and schedule options:

| Option | Type | Default | Description |
|---|---|---|---|
| `--sessions-enabled` / `--no-sessions-enabled` | Flag pair | `false` | Enable/disable scheduler-driven sessions |
| `--schedule` / `--no-schedule` | Flag pair | auto | Force include/exclude `schedule`; auto emits when sessions are enabled |
| `--pre-open HH:MM` | String | `09:00` | Schedule pre-open time |
| `--opening-auction HH:MM` | String | `09:25` | Opening auction start |
| `--continuous HH:MM` | String | `09:30` | Continuous start |
| `--closing-auction HH:MM` | String | `16:00` | Closing auction start |
| `--closing-end HH:MM` | String | `16:05` | Closing auction end |

Core engine and risk options:

| Option | Type | Default | Description |
|---|---|---|---|
| `--snapshot-interval SECS` | float (`> 0`) | `0.5` | `snapshot_interval_sec` |
| `--no-collars` | Flag | off | Emit `enforce_collars: false` |
| `--no-circuit-breakers` | Flag | off | Emit `enforce_circuit_breakers: false` |
| `--static-band PCT` | float in `(0,1)` | unset | Default risk-control static band (`DEFAULT` level) |
| `--dynamic-band PCT` | float in `(0,1)` | unset | Default risk-control dynamic band (`DEFAULT` level) |
| `--symbol-static-band SYM:PCT` | Repeatable | none | Per-symbol `collar.static_band_pct` override |
| `--symbol-dynamic-band SYM:PCT` | Repeatable | none | Per-symbol `collar.dynamic_band_pct` override |
| `--symbol-risk-level SYM:LEVEL` | Repeatable | none | Per-symbol `symbols.<SYM>.level` override |
| `--risk-level NAME:STATIC[:DYNAMIC]` | Repeatable | none | Add named risk levels under `risk_controls.levels` |
| `--cb-levels NAME:SHIFT[:HALT_MINS] ...` | List | built-in ladder | Circuit-breaker level specs |
| `--cb-window-ns NS` | int (`> 0`) | `300000000000` | Circuit-breaker reference window |

Market-maker and symbol defaults:

| Option | Type | Default | Description |
|---|---|---|---|
| `--mm-spread-ticks N` | int (`> 0`) | `20` | Global MM spread threshold |
| `--mm-min-qty N` | int (`> 0`) | `100` | Global MM min quantity |
| `--enforce-mm-obligations` / `--no-enforce-mm-obligations` | Flag pair | `false` | Global MM obligation toggle |
| `--tick-decimals N` | int `0..8` | `2` | Default `tick_decimals` for symbols |
| `--outstanding-shares SYM:N` | Repeatable | none | Per-symbol outstanding shares in the generated config |
| `--seed-last-prices` | Flag | off | Emit `last_buy_price`/`last_sell_price` placeholders |
| `--seed N` | int | random source default | Deterministic RNG seed for generated training values |
| `--seed-mm-mid-range MIN:MAX` | string | none | Seed MM quotes from a random midpoint in the inclusive price range |
| `--seed-last-prices-from-mm` | Flag | off | Set `last_buy_price`/`last_sell_price` to the same midpoint used for seeded MM quotes |

Output and safety options:

| Option | Type | Default | Description |
|---|---|---|---|
| `--output FILE` | Path | none | Write YAML to file |
| `--force` | Flag | off | Overwrite existing output file |
| `--dry-run` | Flag | off | Print YAML only; do not write file |
| `--comment-default-config-fields` | Flag | off | Add a header comment block listing defaultable `engine_config.yaml` fields currently omitted from the generated file |

Post-trade gateway options:

| Option | Type | Default | Description |
|---|---|---|---|
| `--post-trade-gateway` | Flag | off | Emit top-level `post_trade_gateway` block for `pm-ralf-gwy` |
| `--post-trade-name` | string | `ralf-gwy01` | `post_trade_gateway.name` |
| `--post-trade-bind-address` | string | `0.0.0.0` | `post_trade_gateway.bind_address` |
| `--post-trade-port` | int (`> 0`) | `5580` | `post_trade_gateway.port` |
| `--post-trade-replay-retention-sec` | int (`> 0`) | `86400` | `post_trade_gateway.replay_retention_sec` |
| `--post-trade-heartbeat-interval-sec` | int (`> 0`) | `1` | `post_trade_gateway.heartbeat_interval_sec` |
| `--post-trade-idle-timeout-sec` | int (`> 0`) | `5` | `post_trade_gateway.idle_timeout_sec` |
| `--post-trade-max-client-queue` | int (`> 0`) | `10000` | `post_trade_gateway.max_client_queue` |
| `--post-trade-allowed-roles ROLE [ROLE ...]` | list | `CLEARING DROP_COPY AUDIT` | `post_trade_gateway.allowed_roles` |

Market-data gateway options:

| Option | Type | Default | Description |
|---|---|---|---|
| `--market-data-gateway` | Flag | off | Emit top-level `market_data_gateway` block for `pm-md-gwy` |
| `--market-data-enabled` / `--market-data-disabled` | Flag pair | unset (`true` when emitted) | Set `market_data_gateway.enabled` |
| `--market-data-name` | string | `md-gwy01` | `market_data_gateway.name` |
| `--market-data-bind-address` | string | `0.0.0.0` | `market_data_gateway.bind_address` |
| `--market-data-port` | int (`> 0`) | `5570` | `market_data_gateway.port` |
| `--market-data-heartbeat-interval-sec` | int (`> 0`) | `1` | `market_data_gateway.heartbeat_interval_sec` |
| `--market-data-idle-timeout-sec` | int (`> 0`) | `5` | `market_data_gateway.idle_timeout_sec` |
| `--market-data-replay-window-sec` | int (`> 0`) | `30` | `market_data_gateway.replay_window_sec` |
| `--market-data-max-symbols-per-client` | int (`> 0`) | `200` | `market_data_gateway.max_symbols_per_client` |
| `--market-data-max-client-queue` | int (`> 0`) | `10000` | `market_data_gateway.max_client_queue` |

API gateway options:

| Option | Type | Default | Description |
|---|---|---|---|
| `--api-gateway` | Flag | off | Emit top-level `api_gateways` block for `pm-api-gateway` |
| `--api-gateway-name NAME` | string | `default` | Name of the generated `api_gateways.<NAME>` entry for single-process generation |
| `--api-gateway-instance NAME:GATEWAY[,GATEWAY...][:PORT]` | Repeatable | none | Emit one named API gateway process per option, optionally limiting generated keys to listed ALF gateways |
| `--api-gateway-enabled` / `--api-gateway-disabled` | Flag pair | unset (`true` when emitted) | Set each generated API gateway `enabled` field |
| `--api-gateway-host ADDR` | string | `127.0.0.1` | HTTP bind address |
| `--api-gateway-port N` | int (`> 0`) | `8080` | HTTP listen port |
| `--api-gateway-swagger-enabled` / `--api-gateway-swagger-disabled` | Flag pair | unset (`true` when emitted) | Enable or disable `/docs` and `/openapi.json` |
| `--api-gateway-log-level LEVEL` | enum | `info` | `debug`, `info`, `warning`, or `error` |
| `--api-gateway-stats-db PATH` | path | `data/stats.db` | SQLite database used by `/history/*` endpoints |
| `--api-key KEY:GATEWAY_ID[:DESCRIPTION]` | Repeatable | none | Add an explicit bearer-token credential; use `GATEWAY_ID=null` for read-only access |
| `--api-gateway-generate-keys` / `--no-api-gateway-generate-keys` | Flag pair | generated when emitted | Generate one key for each `gateways.alf` entry |
| `--api-gateway-readonly-key` | Flag | off | Generate an additional read-only key with `gateway_id: null` |
| `--api-gateway-rate-limit-writes-per-second N` | int (`> 0`) | `10` | Per-key write rate limit |
| `--api-gateway-rate-limit-burst N` | int (`> 0`) | `20` | Per-key write burst capacity |
| `--api-gateway-engine-auth-sec SECS` | float (`> 0`) | `3.0` | Engine auth timeout field |
| `--api-gateway-engine-reply-sec SECS` | float (`> 0`) | `3.0` | Engine request/reply timeout |
| `--api-gateway-wait-ack-sec SECS` | float (`> 0`) | `3.0` | `?wait=ack` timeout |

When `--api-gateway` is enabled, `pm-config-gen` emits sensible local defaults
and automatically generates one bearer token for each configured ALF gateway.
Pass `--seed N` to make those generated keys reproducible. Use
`--no-api-gateway-generate-keys` when you only want manually supplied
`--api-key` entries.

Use repeated `--api-gateway-instance` options when you want separate API
gateway processes for logical separation. A non-null `gateway_id` can belong to
only one generated API gateway entry; read-only `gateway_id: null` credentials
may be repeated.

Typical CLI example for a local lab with RALF enabled:

```bash
pm-config-gen \
  --symbols AAPL MSFT \
  --gateways TRADER01 TRADER02 OPS01:ADMIN \
  --sessions-enabled \
  --post-trade-gateway \
  --post-trade-bind-address 127.0.0.1 \
  --post-trade-port 5580 \
  --post-trade-replay-retention-sec 3600 \
  --post-trade-heartbeat-interval-sec 1 \
  --post-trade-idle-timeout-sec 10 \
  --post-trade-max-client-queue 2000 \
  --post-trade-allowed-roles CLEARING AUDIT \
  --outstanding-shares AAPL:15400000000 \
  --outstanding-shares MSFT:7430000000 \
  --output engine_config.yaml
```

This generates a standard engine config plus a top-level `post_trade_gateway`
block for `pm-ralf-gwy`. Use `127.0.0.1` for a single-host lab; switch to a
controlled network bind such as `0.0.0.0` only when external clients must
connect from other machines.

### `--gateways` format

Each gateway token is:

```text
ID[:ROLE[:DISCONNECT]]
```

Examples:

- `TRADER01`
- `MM01:MARKET_MAKER`
- `OPS01:ADMIN:LEAVE_ALL`

Role defaults for disconnect behavior:

| Role | Default disconnect behavior |
|---|---|
| `TRADER` | `CANCEL_ALL` |
| `MARKET_MAKER` | `CANCEL_QUOTES_ONLY` |
| `ADMIN` | `LEAVE_ALL` |

### `--symbol-opts` format

Use `--symbol-opts` for per-symbol overrides:

```text
SYMBOL:KEY=VALUE[,KEY=VALUE,...]
```

Example:

```bash
pm-config-gen \
  --symbols AAPL MSFT \
  --gateways TRADER01 MM01:MARKET_MAKER \
  --symbol-opts AAPL:tick_decimals=2,level=L1,mm_spread_ticks=8 \
  --symbol-opts MSFT:dynamic_band=0.03,cb_halt_l1=10
```

Supported `KEY` values:

| Key | Value type | Effect |
|---|---|---|
| `tick_decimals` | int `0..8` | Override symbol tick precision |
| `static_band` | float `(0,1)` | Symbol collar static band |
| `dynamic_band` | float `(0,1)` | Symbol collar dynamic band |
| `cb_shift_l1` / `cb_shift_l2` / `cb_shift_l3` | float `(0,1)` | Override CB level shift pct |
| `cb_halt_l1` / `cb_halt_l2` / `cb_halt_l3` | int `>= 0` minutes | Override CB halt duration (`0` means rest-of-day) |
| `level` | string | Symbol risk level key |
| `mm_spread_ticks` | int `> 0` | Symbol MM spread threshold |
| `mm_min_qty` | int `> 0` | Symbol MM minimum quantity |

For the two most common collar overrides, you can also use explicit flags:

```bash
pm-config-gen \
  --symbols AAPL MSFT \
  --gateways TRADER01 \
  --symbol-static-band AAPL:0.18 \
  --symbol-dynamic-band AAPL:0.03
```

Per-symbol risk-level assignment can also use an explicit flag:

```bash
pm-config-gen \
  --symbols AAPL MSFT TSLA \
  --gateways TRADER01 \
  --risk-level CORE:0.18:0.02 \
  --risk-level HIGH_BETA:0.12:0.04 \
  --symbol-risk-level AAPL:CORE \
  --symbol-risk-level TSLA:HIGH_BETA
```

`--symbol-risk-level` is a convenience alias for `--symbol-opts SYM:level=...`.
It writes `symbols.<SYM>.level` and uses the same runtime validation rules.

Unknown symbols/keys or invalid values in `--symbol-opts` are reported as
warnings and ignored.

The generated `symbols:` section also includes an `outstanding_shares` field
for every symbol. Use that as the slow-changing input for statistics and future
index-style consumers; market capitalization can then be derived from it and
the latest price instead of being stored as a separate static field.

### Practical recipes

Minimal classroom config:

```bash
pm-config-gen \
  --symbols AAPL \
  --gateways TRADER01 TRADER02 OPS01:ADMIN \
  --outstanding-shares AAPL:15400000000 \
  --no-sessions-enabled \
  --output engine_config.yaml
```

Session-driven day with risk levels and CB ladder:

```bash
pm-config-gen \
  --symbols AAPL MSFT TSLA \
  --gateways TRADER01 TRADER02 OPS01:ADMIN \
  --outstanding-shares AAPL:15400000000 \
  --outstanding-shares MSFT:7430000000 \
  --outstanding-shares TSLA:3200000000 \
  --sessions-enabled \
  --risk-level L1:0.30:0.05 \
  --risk-level L2:0.20:0.02 \
  --cb-levels L1:0.07:5 L2:0.13:15 L3:0.20 \
  --output engine_config.yaml
```

Market-maker session with seeded startup quotes:

```bash
pm-config-gen \
  --symbols AAPL MSFT \
  --gateways TRADER01 MM01:MARKET_MAKER OPS01:ADMIN \
  --outstanding-shares AAPL:15400000000 \
  --outstanding-shares MSFT:7430000000 \
  --sessions-enabled \
  --enforce-mm-obligations \
  --seed 20260621 \
  --seed-mm-mid-range 20:300 \
  --seed-last-prices-from-mm \
  --output engine_config.yaml
```

After generation, validate manually:

```bash
poetry run python -c 'from pathlib import Path; from edumatcher.engine.config_loader import load_engine_config; print(load_engine_config(Path("engine_config.yaml")))'
```

If MM gateways are present and you do not use `--seed-mm-mid-range`, fill all `market_maker_quotes` prices first, then
run the validation command.

Post-trade gateway config with explicit RALF listener settings:

```bash
pm-config-gen \
  --symbols AAPL MSFT \
  --gateways TRADER01 OPS01:ADMIN \
  --outstanding-shares AAPL:15400000000 \
  --outstanding-shares MSFT:7430000000 \
  --post-trade-gateway \
  --post-trade-bind-address 127.0.0.1 \
  --post-trade-port 5580 \
  --post-trade-allowed-roles CLEARING AUDIT \
  --output engine_config.yaml
```

Expected emitted section:

```yaml
post_trade_gateway:
  name: ralf-gwy01
  bind_address: 127.0.0.1
  port: 5580
  replay_retention_sec: 3600
  heartbeat_interval_sec: 1
  idle_timeout_sec: 10
  max_client_queue: 2000
  allowed_roles:
    - CLEARING
    - AUDIT
```

This is the quickest path when you want one command that prepares both:

- the engine symbol and ALF gateway config used by `pm-engine`
- the optional RALF listener settings used by `pm-ralf-gwy`

REST/WebSocket API gateway config with generated keys:

```bash
pm-config-gen \
  --symbols AAPL MSFT \
  --gateways TRADER01 TRADER02 OPS01:ADMIN \
  --outstanding-shares AAPL:15400000000 \
  --outstanding-shares MSFT:7430000000 \
  --api-gateway \
  --api-gateway-readonly-key \
  --api-gateway-host 127.0.0.1 \
  --api-gateway-port 8080 \
  --seed 20260624 \
  --output engine_config.yaml
```

Expected emitted section shape:

```yaml
api_gateways:
  default:
    enabled: true
    host: 127.0.0.1
    port: 8080
    swagger_enabled: true
    log_level: info
    stats_db: data/stats.db
    credentials:
      - api_key: key-trader01-...
        gateway_id: TRADER01
        description: Generated key for TRADER01
      - api_key: key-trader02-...
        gateway_id: TRADER02
        description: Generated key for TRADER02
      - api_key: key-ops01-...
        gateway_id: OPS01
        description: Generated key for OPS01
      - api_key: key-readonly-...
        gateway_id: null
        description: Generated read-only market-data key
    rate_limit:
      writes_per_second: 10
      burst: 20
    timeouts:
      engine_auth_sec: 3.0
      engine_reply_sec: 3.0
      wait_ack_sec: 3.0
```

Explicit API-key config:

```bash
pm-config-gen \
  --symbols AAPL \
  --gateways TRADER01 \
  --api-key trader-secret:TRADER01:"Desk app" \
  --api-key dashboard-secret:null:"Read-only dashboard" \
  --no-api-gateway-generate-keys \
  --output engine_config.yaml
```

`gateway_id` values in API credentials must either be `null` for read-only
market-data access or match an ID from `gateways.alf`. Generated keys are plain
YAML bearer tokens for local labs and teaching setups; production deployments
should manage secrets with the surrounding platform and terminate TLS in front
of `pm-api-gateway`.

For multiple generated processes, start a specific named entry with
`pm-api-gateway --config engine_config.yaml --instance NAME`.


## Current Schema

The current parser recognizes these top-level keys:

| Key | Required when file exists? | Used by | Purpose |
|---|---:|---|---|
| `symbols` | Yes | Engine | Accepted symbols and per-symbol settings |
| `gateways` | Yes | Engine | Gateway configuration container |
| `gateways.alf` | Yes | Engine | Accepted ALF order-entry gateways |
| `sessions_enabled` | No | Engine | Enable scheduler-driven session states |
| `enforce_collars` | No | Engine | Global collar enforcement toggle |
| `enforce_circuit_breakers` | No | Engine | Global circuit-breaker enforcement toggle |
| `snapshot_interval_sec` | No | Engine | Per-symbol book snapshot throttle |
| `mm_obligation_defaults` | No | Engine | Default market-maker quote obligation policy |
| `risk_controls` | No | Engine | Named collar profiles |
| `circuit_breaker_defaults` | No | Engine | Default circuit-breaker ladder |
| `market_maker_combos` | No | Engine | Startup multi-symbol combo seeds |
| `schedule` | No | Scheduler, parsed by engine too | Session transition times |
| `post_trade_gateway` | No | `pm-ralf-gwy` | External RALF dissemination gateway settings |
| `market_data_gateway` | No | `pm-md-gwy` | External CALF dissemination gateway settings |
| `api_gateways` | No | `pm-api-gateway` | Named REST/WebSocket order-entry and market-data gateway process settings |

The nested sections below document every field currently parsed under these
top-level keys. Unknown keys in a mapping are generally ignored by the loader,
but they should not be relied on for runtime behavior.

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

If you prefer to generate this block instead of writing it by hand,
`pm-config-gen` can emit it with `--market-data-gateway` and optional
`--market-data-*` overrides.


## Configuring `pm-api-gateway`

`pm-api-gateway` reads an optional top-level `api_gateways` block from the same
`engine_config.yaml` file. This block is not consumed by `pm-engine`; it is
consumed by the REST/WebSocket API gateway process.

Minimal generated example:

```yaml
api_gateways:
  desk:
    enabled: true
    host: 127.0.0.1
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

- `enabled` lets `pm-api-gateway` refuse startup when set to `false`
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
entry name, for example `pm-api-gateway --config engine_config.yaml --instance desk`.


## Minimal Example

Use this when you want the smallest fully working configured exchange. It starts
in continuous matching mode, accepts only `AAPL`, and allows two trader gateways.
This mirrors the live sample `engine_config.yaml`.

```yaml
sessions_enabled: false
enforce_collars: true
enforce_circuit_breakers: true
snapshot_interval_sec: 0.5

symbols:
  AAPL:
    tick_decimals: 2
    last_buy_price: 209.50
    last_sell_price: 210.50

gateways:
  alf:
    - id: TRADER01
      description: Student workstation 1
      role: TRADER
      disconnect_behaviour: CANCEL_ALL
    - id: TRADER02
      description: Student workstation 2
      role: TRADER
      disconnect_behaviour: CANCEL_ALL
```

This config does not define a `MARKET_MAKER` gateway, so no
`market_maker_quotes` are required.


## Medium Example

Use this for a classroom session with scheduled phases, multiple symbols, an
operator gateway, reusable collar levels, and a normal continuous trading day.

```yaml
sessions_enabled: true
enforce_collars: true
enforce_circuit_breakers: true
snapshot_interval_sec: 0.5

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

symbols:
  AAPL:
    tick_decimals: 2
    last_buy_price: 209.50
    last_sell_price: 210.50
  MSFT:
    tick_decimals: 2
    level: L1
    last_buy_price: 415.00
    last_sell_price: 415.50
  TSLA:
    tick_decimals: 2
    collar:
      dynamic_band_pct: 0.04

gateways:
  alf:
    - id: TRADER01
      description: Student workstation 1
      role: TRADER
      disconnect_behaviour: CANCEL_ALL
    - id: TRADER02
      description: Student workstation 2
      role: TRADER
      disconnect_behaviour: CANCEL_ALL
    - id: OPS01
      description: Instructor console
      role: ADMIN
      disconnect_behaviour: LEAVE_ALL

schedule:
  pre_open: "09:00"
  opening_auction_start: "09:25"
  continuous_start: "09:30"
  closing_auction_start: "16:00"
  closing_auction_end: "16:05"
```

This still avoids market-maker seed quotes. Students can supply liquidity
manually, and the operator can manage session phases and exchange-wide
circuit-breaker controls.


## Fully Complex Example

Use this as a reference for every major parser-supported feature: market-maker
roles, quote seeds, obligation policy, collar profiles, circuit-breaker defaults,
symbol overrides, startup combo seeds, and scheduler times.

```yaml
sessions_enabled: true
enforce_collars: true
enforce_circuit_breakers: true
snapshot_interval_sec: 0.5

mm_obligation_defaults:
  enforce_mm_obligation: true
  mm_max_spread_ticks: 20
  mm_min_qty: 100
  symbols:
    AAPL:
      enforce_mm_obligation: true
      mm_max_spread_ticks: 8
      mm_min_qty: 200
    TSLA:
      enforce_mm_obligation: true
      mm_max_spread_ticks: 40
      mm_min_qty: 50

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
    L3:
      collar:
        static_band_pct: 0.12
        dynamic_band_pct: 0.01

circuit_breaker_defaults:
  reference_window_ns: 300000000000
  levels:
    L1:
      price_shift_pct: 0.07
      halt_duration_ns: 300000000000
      resumption_mode: AUCTION
    L2:
      price_shift_pct: 0.13
      halt_duration_ns: 900000000000
      resumption_mode: AUCTION
    L3:
      price_shift_pct: 0.20
      halt_duration_ns:
      resumption_mode: AUCTION

gateways:
  alf:
    - id: TRADER01
      description: Student workstation 1
      role: TRADER
      disconnect_behaviour: CANCEL_ALL
    - id: TRADER02
      description: Student workstation 2
      role: TRADER
      disconnect_behaviour: CANCEL_ALL
    - id: MM01
      description: Primary market maker
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_ANY_FILL
      enforce_mm_obligation: true
      mm_max_spread_ticks: 20
      mm_min_qty: 100
      mm_obligations:
        AAPL:
          enforce_mm_obligation: true
          max_spread_ticks: 6
          min_qty: 300
        TSLA:
          enforce_mm_obligation: true
          max_spread_ticks: 50
          min_qty: 50
    - id: MM02
      description: Backup market maker
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_FULL_FILL
      enforce_mm_obligation: true
      mm_max_spread_ticks: 30
      mm_min_qty: 50
    - id: OPS01
      description: Instructor console
      role: ADMIN
      disconnect_behaviour: LEAVE_ALL

symbols:
  AAPL:
    tick_decimals: 2
    last_buy_price: 209.50
    last_sell_price: 210.50
    collar:
      dynamic_band_pct: 0.015
    circuit_breaker:
      levels:
        L1:
          halt_duration_ns: 180000000000
    market_maker_quotes:
      - gateway_id: MM01
        quote_id: SEED-MM01-AAPL
        bid_price: 209.00
        ask_price: 211.00
        bid_qty: 2000
        ask_qty: 2000
        tif: DAY
        seed_once: true
      - gateway_id: MM02
        quote_id: SEED-MM02-AAPL
        bid_price: 208.50
        ask_price: 211.50
        bid_qty: 1000
        ask_qty: 1000
        tif: DAY
        seed_once: true

  MSFT:
    tick_decimals: 2
    level: L1
    last_buy_price: 415.00
    last_sell_price: 415.50
    market_maker_quotes:
      - gateway_id: MM01
        quote_id: SEED-MM01-MSFT
        bid_price: 414.00
        ask_price: 416.00
        bid_qty: 1000
        ask_qty: 1000
        tif: DAY
        seed_once: true

  TSLA:
    tick_decimals: 2
    level: L3
    last_buy_price: 248.00
    last_sell_price: 249.00
    collar:
      dynamic_band_pct: 0.04
    circuit_breaker:
      levels:
        L1:
          halt_duration_ns: 600000000000
        L2:
          halt_duration_ns: 1800000000000
    market_maker_quotes:
      - gateway_id: MM01
        quote_id: SEED-MM01-TSLA
        bid_price: 247.00
        ask_price: 250.00
        bid_qty: 500
        ask_qty: 500
        tif: DAY
        seed_once: false

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

schedule:
  pre_open: "09:00"
  opening_auction_start: "09:25"
  continuous_start: "09:30"
  closing_auction_start: "16:00"
  closing_auction_end: "16:05"
```

!!! important "Combo seed prices are ticks"
    `market_maker_quotes` use display prices such as `209.00`. Startup combo
    legs are parsed through the combo model and expect integer tick prices. With
    `tick_decimals: 2`, `price: 20950` represents `209.50`.


## Configuration Checklist

Use this checklist when creating a new engine configuration.

1. Decide session mode.
   Use `sessions_enabled: false` for simple demos and tests. Use
   `sessions_enabled: true` when `pm-scheduler` should drive phases.

2. Define the symbol universe.
   Add every tradable symbol under `symbols`, set `tick_decimals`, and add
   `last_buy_price` / `last_sell_price` if viewers should start with references.

3. Define ALF gateways.
   Add every expected `pm-gateway --id ...` under `gateways.alf`. Choose
   `TRADER`, `MARKET_MAKER`, or `ADMIN`, then choose disconnect behavior.

4. Decide whether market makers exist.
   If no gateway has `role: MARKET_MAKER`, `market_maker_quotes` are optional.
   If any gateway has `role: MARKET_MAKER`, every symbol needs at least one
   quote seed. Quote seed `gateway_id` values must reference configured
   `MARKET_MAKER` gateways.

5. Add risk controls only as needed.
   Use `risk_controls.levels` for reusable collar profiles,
   `circuit_breaker_defaults` for the global breaker ladder, and symbol-level
   overrides only for exceptions.

6. Add market-maker obligation policy if quote quality matters.
   Start with `mm_obligation_defaults`, override by symbol under
   `mm_obligation_defaults.symbols`, and use `gateways.alf[*].mm_obligations`
   only for gateway-specific exceptions.

7. Add startup combos only after symbols are stable.
   Keep combo leg symbols unique within one combo, use 2 to 10 legs, and remember
   combo leg prices are integer ticks.

8. Add a schedule if sessions are enabled.
   Provide all five schedule keys for readability and confirm times are local
   server `HH:MM` strings.

9. Check persistence before first run.
   Remove stale state when changing seed behavior or symbol universe, especially
   `data/book_stats.json`, `data/gtc_orders.json`, and `data/gtc_combos.json`.

10. Validate before class or demo.
    Start `pm-engine --verbose --config your_config.yaml`, connect each gateway
    ID you expect to use, and run `SYMBOLS` from a gateway.


## Engine Behavior Flags

### `sessions_enabled`

```yaml
sessions_enabled: true
```

When `true`, the engine starts in `CLOSED` and accepts scheduler transitions.
When `false`, the engine starts in `CONTINUOUS` and ignores scheduler
transitions.

| Scenario | Effective value |
|---|---|
| Config file present, field absent | `true` |
| No config file (unrestricted mode) | `false` |

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

### `snapshot_interval_sec`

```yaml
snapshot_interval_sec: 0.5
```

Controls the per-symbol throttle window for `book.<SYMBOL>` publications from
dirty books.

Rules:

- must be numeric
- must be greater than zero
- defaults to `0.5` seconds when omitted


## ALF Gateway Allowlist

Only gateway IDs listed under `gateways.alf` may connect and submit orders when
a config file exists.

```yaml
gateways:
  alf:
    - id: TRADER01
      description: Student workstation 1
      role: TRADER
      disconnect_behaviour: CANCEL_ALL
```

### Gateway Fields

| Field | Required | Accepted values / type | Default |
|---|---:|---|---|
| `id` | Yes | Non-empty string, uppercased by parser | None |
| `description` | No | String or null | Empty string |
| `role` | No | `TRADER`, `MARKET_MAKER`, `ADMIN` | `TRADER` |
| `disconnect_behaviour` | No | `CANCEL_QUOTES_ONLY`, `CANCEL_ALL`, `LEAVE_ALL` | `CANCEL_QUOTES_ONLY` |
| `quote_refresh_policy` | No | `INACTIVATE_ON_ANY_FILL`, `INACTIVATE_ON_FULL_FILL`, `NEVER_INACTIVATE` | `INACTIVATE_ON_ANY_FILL` |
| `enforce_mm_obligation` | No | Boolean | Global MM default |
| `mm_max_spread_ticks` | No | Positive integer | Global MM default, then `10` |
| `mm_min_qty` | No | Positive integer | Global MM default, then `100` |
| `mm_obligations` | No | Per-symbol mapping | Empty mapping |

Nested `mm_obligations.<SYMBOL>` entries support these fields:

| Field | Required | Accepted values / type | Default |
|---|---:|---|---|
| `enforce_mm_obligation` | No | Boolean | Gateway `enforce_mm_obligation` |
| `max_spread_ticks` | No | Integer; use positive values for a valid spread limit | Gateway `mm_max_spread_ticks` |
| `min_qty` | No | Integer; use positive values for a valid quantity floor | Gateway `mm_min_qty` |

Inside `mm_obligations`, use this shape:

```yaml
gateways:
  alf:
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

| Role | Regular orders | Quotes | Admin circuit-breaker halt/resume | Typical use |
|---|---:|---:|---:|---|
| `TRADER` | Yes | No | No | Students, manual participants, AI traders |
| `MARKET_MAKER` | Yes | Yes | No | Quote providers |
| `ADMIN` | Yes | No | Yes | Instructor/operator console |

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

| Field | Required | Description |
|---|---:|---|
| `enforce_mm_obligation` | No | Enable quote obligation checks |
| `mm_max_spread_ticks` | No | Maximum allowed bid/ask spread in ticks |
| `mm_min_qty` | No | Minimum bid and ask quantity |
| `symbols` | No | Per-symbol overrides using the same three fields |

Defaults and validation:

| Field | Accepted values / type | Default |
|---|---|---|
| `enforce_mm_obligation` | Boolean | `false` |
| `mm_max_spread_ticks` | Positive integer | `10` |
| `mm_min_qty` | Positive integer | `100` |
| `symbols.<SYMBOL>.enforce_mm_obligation` | Boolean | Top-level `enforce_mm_obligation` |
| `symbols.<SYMBOL>.mm_max_spread_ticks` | Positive integer | Top-level `mm_max_spread_ticks` |
| `symbols.<SYMBOL>.mm_min_qty` | Positive integer | Top-level `mm_min_qty` |

The effective policy is resolved from most specific to least specific:

1. `gateways.alf[*].mm_obligations.<SYMBOL>`
2. `mm_obligation_defaults.symbols.<SYMBOL>`
3. Gateway flat fields
4. `mm_obligation_defaults` flat fields
5. Built-in defaults


## Symbol Universe

Only symbols declared under `symbols` are accepted by the configured engine.

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

| Field | Required | Type / accepted values | Description |
|---|---:|---|---|
| `tick_decimals` | No | Integer `0..8` | Decimal places used to convert display prices to ticks |
| `level` | No | Key from `risk_controls.levels` | Named collar profile |
| `last_buy_price` | No | Number | Initial last-buy reference when no persisted stat exists |
| `last_sell_price` | No | Number | Initial last-sell reference when no persisted stat exists |
| `collar` | No | Mapping | Symbol-level collar override |
| `circuit_breaker` | No | Mapping | Symbol-level circuit-breaker override |
| `market_maker_quotes` | No | List of mappings | Startup quote seeds |

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
  --gateways TRADER01 \
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

| Field | Required | Accepted values / type | Default |
|---|---:|---|---|
| `default_level` | No | Non-empty string matching a key in `levels` | None |
| `levels` | No | Mapping of named level configs | Empty mapping |
| `levels.<LEVEL>` | No | Mapping; level name is uppercased | None |
| `levels.<LEVEL>.collar` | No | Mapping | Empty mapping |

### Collar Fields

Collars may appear under `risk_controls.levels.<LEVEL>.collar` or under
`symbols.<SYMBOL>.collar`.

| Field | Required | Accepted values / type | Default when a collar is active |
|---|---:|---|---|
| `static_band_pct` | No | Number in `(0, 1)` | `0.20` |
| `dynamic_band_pct` | No | Number in `(0, 1)` | `0.02` |

Meaning of collar values:

- `static_band_pct` is an absolute guard around the symbol reference price
  (for example prior close or seeded last price). A value of `0.20` means
  allow prices within ±20% of that reference.
- `dynamic_band_pct` is an incremental guard around the latest trade price.
  A value of `0.02` means allow prices within ±2% of the latest fill.

This is the same behavior described in [Risk Controls](12-risk-controls.md)
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
price collars, see [Risk Controls - Price collars vs circuit breakers](12-risk-controls.md#price-collars-vs-circuit-breakers).

```yaml
circuit_breaker_defaults:
  reference_window_ns: 300000000000
  levels:
    L1:
      price_shift_pct: 0.07
      halt_duration_ns: 300000000000
      resumption_mode: AUCTION
    L2:
      price_shift_pct: 0.13
      halt_duration_ns: 900000000000
      resumption_mode: AUCTION
    L3:
      price_shift_pct: 0.20
      halt_duration_ns:
      resumption_mode: AUCTION

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
- `resumption_mode` must be `AUCTION` or `CONTINUOUS`
- `reference_window_ns` is converted to integer nanoseconds

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

| Field | Required | Accepted values / type | Default |
|---|---:|---|---|
| `reference_window_ns` | No | Integer nanoseconds | `300000000000` |
| `levels` | Yes when a breaker is active | Non-empty mapping after merging | Built-in L1/L2/L3 only when no levels are supplied |
| `levels.<LEVEL>.price_shift_pct` | Yes | Number in `(0, 1)` | None |
| `levels.<LEVEL>.halt_duration_ns` | No | Positive integer nanoseconds or null | Null |
| `levels.<LEVEL>.resumption_mode` | No | `AUCTION`, `CONTINUOUS` | `AUCTION` |


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

| Field | Required | Accepted values / type | Default | Description |
|---|---:|---|---|---|
| `gateway_id` | Yes | Non-empty string, uppercased | None | Configured `MARKET_MAKER` gateway that owns the quote |
| `quote_id` | No | String; empty string is treated as omitted | Generated | Explicit quote label |
| `bid_price` | Yes | Number | None | Display price converted to ticks by the engine |
| `ask_price` | Yes | Number greater than `bid_price` | None | Display price converted to ticks by the engine |
| `bid_qty` | Yes | Positive integer | None | Bid-side quantity |
| `ask_qty` | Yes | Positive integer | None | Ask-side quantity |
| `tif` | No | `DAY`, `GTC`, `ATO`, `ATC` | `DAY` | Time in force |
| `seed_once` | No | Boolean-like value; use YAML `true`/`false` | `true` | Skip injection after `book_stats.json` has symbol history |

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

| Field | Required | Accepted values / type |
|---|---:|---|
| `combo_id` | Yes | Non-empty string |
| `combo_type` | No | `AON`; defaults to `AON` |
| `tif` | No | `DAY`, `GTC`, `ATO`, `ATC`; defaults to `DAY` |
| `legs` | Yes | List with 2 to 10 entries |

Leg fields:

| Field | Required | Accepted values / type |
|---|---:|---|
| `symbol` | Yes | Configured symbol, unique inside the combo |
| `side` | Yes | `BUY`, `SELL` |
| `order_type` | Yes | `MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT`, `FOK`, `ICEBERG`, `IOC`, `TRAILING_STOP` |
| `quantity` | Yes | Integer quantity |
| `price` | Conditional | Integer tick price for priced order types |
| `stop_price` | Conditional | Integer tick stop price for stop order types |
| `smp_action` | No | `NONE`, `CANCEL_AGGRESSOR`, `CANCEL_RESTING`, `CANCEL_BOTH`; defaults to `NONE` |

Combo leg values are passed to `ComboLeg.from_dict()`, so these are the only leg
fields used by current config parsing. Unlike quote seeds, combo legs do not
include a `gateway_id`; startup combo ownership is assigned by the engine's combo
seed path.

Prefer `tif: DAY` for repeatable demo seeds. `GTC` combo seeds can interact with
restored `gtc_combos.json` state and duplicate intended startup liquidity if you
are not managing persistence deliberately.


## Session Schedule

The scheduler reads `schedule` and sends transitions to the engine.

```yaml
schedule:
  pre_open: "09:00"
  opening_auction_start: "09:25"
  continuous_start: "09:30"
  closing_auction_start: "16:00"
  closing_auction_end: "16:05"
```

| Key | Required | Default |
|---|---:|---|
| `pre_open` | No | `09:00` |
| `opening_auction_start` | No | `09:25` |
| `continuous_start` | No | `09:30` |
| `closing_auction_start` | No | `16:00` |
| `closing_auction_end` | No | `16:05` |

Schedule values are read as strings and should be local server `HH:MM` values.
The scheduler uses any provided subset in trading-day order. If no usable
schedule is present, it uses built-in defaults. With `pm-scheduler --now`, the
wall-clock values are ignored and transitions are sent immediately with short
delays.

The default session path is:

```text
PRE_OPEN -> OPENING_AUCTION -> CONTINUOUS -> CLOSING_AUCTION -> CLOSED
```


## Startup and Persistence Order

The effective engine startup sequence is:

```text
Engine startup
    |
    +-- 1. Parse config if present
    +-- 2. Bind main PULL/PUB sockets
    +-- 3. Load persisted book stats from data/book_stats.json
    +-- 4. Restore persisted GTC orders from data/gtc_orders.json
    +-- 5. Restore persisted GTC combos from data/gtc_combos.json
    +-- 6. Inject market_maker_quotes
    +-- 7. Inject market_maker_combos
    +-- 8. Bind drop-copy PUB :5557 if available
    +-- 9. Publish initial book snapshots
```

This ordering means persisted GTC state comes back before config seed liquidity,
and persisted book stats override `last_buy_price` / `last_sell_price` seeds.
When changing seed behavior or symbol definitions, consider removing stale data:

```bash
rm -f data/gtc_orders.json data/book_stats.json data/gtc_combos.json
```


## Adding or Removing Symbols

Edit `engine_config.yaml` and restart the engine.

- adding a symbol makes it tradable on next startup
- removing a symbol causes future orders for it to be rejected
- persisted GTC orders for removed symbols are skipped during restore
- startup combo seeds referencing removed symbols make config loading fail
- `mm_obligation_defaults.symbols.<SYMBOL>` entries must reference configured symbols


## Validation Commands

For a quick parser check from a source checkout:

```bash
poetry run python -c 'from pathlib import Path; from edumatcher.engine.config_loader import load_engine_config; print(load_engine_config(Path("engine_config.yaml")))'
```

If the file is valid, this prints the parsed `EngineConfig` object.  On error
you get a traceback ending with a descriptive message:

```text
ValueError: Engine config must have a 'symbols' mapping
```

```text
ValueError: Gateway 'TRADER01' has invalid disconnect_behaviour: 'CANCEL_NONE'
  (allowed: CANCEL_QUOTES_ONLY, CANCEL_ALL, LEAVE_ALL)
```

For installed (pipx) users who do not have access to the `poetry run` environment,
pass the config file to the engine directly — it validates on startup:

```bash
pm-engine --config engine_config.yaml
```

For the focused config parser test suite:

```bash
poetry run pytest tests/test_config_loader.py tests/test_config_extensions.py
```


## Formal Specification

This section is a complete machine-readable-style reference for every field
parsed from `engine_config.yaml`. Types follow Python conventions: `bool`,
`int`, `float`, `str`. "Enum" means the field must match one of the listed
string values exactly (case-insensitive during loading; stored in uppercase).
Ranges use mathematical interval notation: `(a, b)` is open (exclusive),
`[a, b]` is closed (inclusive).

---

### Top-level fields

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `symbols` | mapping | Yes | — | — | Must contain at least one entry |
| `gateways` | mapping | Yes | — | — | Must contain key `alf` |
| `gateways.alf` | list | Yes | — | — | Non-empty list of gateway mappings |
| `sessions_enabled` | bool | No | `true` when file exists, `false` in unrestricted mode | `true`, `false` | Must be a YAML boolean |
| `enforce_collars` | bool | No | `true` | `true`, `false` | Must be a YAML boolean |
| `enforce_circuit_breakers` | bool | No | `true` | `true`, `false` | Must be a YAML boolean |
| `snapshot_interval_sec` | float | No | `0.5` | Any number | Must be `> 0` |
| `mm_obligation_defaults` | mapping | No | — | — | — |
| `risk_controls` | mapping | No | — | — | — |
| `circuit_breaker_defaults` | mapping | No | — | — | — |
| `market_maker_combos` | list | No | `[]` | — | Each entry must be a mapping |
| `schedule` | mapping | No | — | — | Parsed by scheduler and stored by engine |

---

### `gateways.alf[]` — gateway entry fields

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `id` | str | Yes | — | Any non-empty string | Uppercased; must be unique within the list |
| `description` | str or null | No | `""` | Any string or null | Null is coerced to `""` |
| `role` | Enum | No | `TRADER` | `TRADER`, `MARKET_MAKER`, `ADMIN` | Case-insensitive |
| `disconnect_behaviour` | Enum | No | `CANCEL_QUOTES_ONLY` | `CANCEL_QUOTES_ONLY`, `CANCEL_ALL`, `LEAVE_ALL` | Case-insensitive |
| `quote_refresh_policy` | Enum | No | `INACTIVATE_ON_ANY_FILL` | `INACTIVATE_ON_ANY_FILL`, `INACTIVATE_ON_FULL_FILL`, `NEVER_INACTIVATE` | Case-insensitive |
| `enforce_mm_obligation` | bool | No | From `mm_obligation_defaults.enforce_mm_obligation`, else `false` | `true`, `false` | Must be a YAML boolean |
| `mm_max_spread_ticks` | int | No | From `mm_obligation_defaults.mm_max_spread_ticks`, else `10` | Integer | Must be `> 0` |
| `mm_min_qty` | int | No | From `mm_obligation_defaults.mm_min_qty`, else `100` | Integer | Must be `> 0` |
| `mm_obligations` | mapping | No | `{}` | Mapping of symbol → obligation entry | Symbol keys are uppercased |

### `gateways.alf[].mm_obligations.<SYMBOL>` fields

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `enforce_mm_obligation` | bool | No | Gateway `enforce_mm_obligation` | `true`, `false` | Must be a YAML boolean |
| `max_spread_ticks` | int | No | Gateway `mm_max_spread_ticks` | Integer | Must be `> 0` |
| `min_qty` | int | No | Gateway `mm_min_qty` | Integer | Must be `> 0` |

---

### `mm_obligation_defaults` fields

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `enforce_mm_obligation` | bool | No | `false` | `true`, `false` | Must be a YAML boolean |
| `mm_max_spread_ticks` | int | No | `10` | Integer | Must be `> 0` |
| `mm_min_qty` | int | No | `100` | Integer | Must be `> 0` |
| `symbols` | mapping | No | `{}` | Symbol name → override mapping | Symbol keys are uppercased; each must reference a configured symbol |

### `mm_obligation_defaults.symbols.<SYMBOL>` fields

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `enforce_mm_obligation` | bool | No | Top-level `enforce_mm_obligation` | `true`, `false` | Must be a YAML boolean |
| `mm_max_spread_ticks` | int | No | Top-level `mm_max_spread_ticks` | Integer | Must be `> 0` |
| `mm_min_qty` | int | No | Top-level `mm_min_qty` | Integer | Must be `> 0` |

---

### `risk_controls` fields

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `default_level` | str | No | `null` | Any non-empty string | Must match a key in `risk_controls.levels` if set |
| `levels` | mapping | No | `{}` | Level name → level config mapping | Level names are uppercased |

### `risk_controls.levels.<LEVEL>` fields

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `collar` | mapping | No | `{}` | See collar fields | Must be a mapping; `circuit_breaker` sub-key is rejected |

### Collar fields — in `risk_controls.levels.<LEVEL>.collar` or `symbols.<SYMBOL>.collar`

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `static_band_pct` | float | No | `0.20` | `(0, 1)` exclusive | Band truncates toward zero; makes range slightly tighter than exact |
| `dynamic_band_pct` | float | No | `0.02` | `(0, 1)` exclusive | Same truncation rule |

---

### `circuit_breaker_defaults` fields

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `reference_window_ns` | int | No | `300000000000` (5 min) | Positive integer nanoseconds | Coerced to `int` |
| `levels` | mapping | No | Built-in L1/L2/L3 ladder only when a CB section is present but omits `levels` | Level name → level config mapping | Values must be mappings |

### `circuit_breaker_defaults.levels.<LEVEL>` and `symbols.<SYMBOL>.circuit_breaker.levels.<LEVEL>` fields

Symbol-level entries merge over the defaults: only the fields you specify are overridden.

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `price_shift_pct` | float | Yes when creating a level | — | `(0, 1)` exclusive | Required in any level that originates from config; inherited from defaults for symbol overrides |
| `halt_duration_ns` | int or null | No | `null` | Positive integer nanoseconds, or `null`/omitted | `null` means rest-of-day halt; must be `> 0` when provided |
| `resumption_mode` | Enum | No | `AUCTION` | `AUCTION`, `CONTINUOUS` | Case-insensitive |

**Built-in default CB ladder** (used only when a circuit-breaker section exists
but supplies no `levels`; if no circuit-breaker section is present at all, the
symbol has no breaker):

| Level | `price_shift_pct` | `halt_duration_ns` | `resumption_mode` |
|---|---|---|---|
| L1 | `0.07` | `300000000000` (5 min) | `AUCTION` |
| L2 | `0.13` | `900000000000` (15 min) | `AUCTION` |
| L3 | `0.20` | `null` (rest-of-day) | `AUCTION` |

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
| `market_maker_quotes` | list | No | `[]` | List of quote seed mappings | Required (non-empty) if any `MARKET_MAKER` gateway is configured |

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
| `price` | int | Conditional | `null` | Integer tick price | Required for `LIMIT`, `STOP_LIMIT`, `FOK`, `ICEBERG`, `IOC` |
| `stop_price` | int | Conditional | `null` | Integer tick price | Required for `STOP`, `STOP_LIMIT`, `TRAILING_STOP` |
| `smp_action` | Enum | No | `NONE` | `NONE`, `CANCEL_AGGRESSOR`, `CANCEL_RESTING`, `CANCEL_BOTH` | Case-insensitive |

!!! note "Combo leg prices are integer ticks"
    All combo leg price fields (`price`, `stop_price`) are integer tick values,
    not display floats. For a symbol with `tick_decimals: 2`, the display price
    `209.50` is stored as `20950` ticks.

---

### `schedule` fields

| Field | Type | Required | Default | Allowed values / range | Constraint |
|---|---|---:|---|---|---|
| `pre_open` | str | No | `"09:00"` | `"HH:MM"` (local server time) | Any provided subset is used in order |
| `opening_auction_start` | str | No | `"09:25"` | `"HH:MM"` (local server time) | — |
| `continuous_start` | str | No | `"09:30"` | `"HH:MM"` (local server time) | — |
| `closing_auction_start` | str | No | `"16:00"` | `"HH:MM"` (local server time) | — |
| `closing_auction_end` | str | No | `"16:05"` | `"HH:MM"` (local server time) | — |

---

### Cross-field validation rules

These constraints span multiple sections and are checked after all fields are
parsed:

1. If any gateway has `role: MARKET_MAKER`, every symbol in `symbols` must
   have at least one `market_maker_quotes` entry.
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

---

## See Also

- [Running the Engine](03-running-the-engine.md) - startup order and common runtime workflows
- [Gateway Commands](08-gateway.md) - ALF commands and gateway behavior
- [Risk Controls](12-risk-controls.md) - collar and circuit-breaker behavior in depth
- [Persistence](11-persistence.md) - how GTC orders, book stats, and combos are saved and restored
- [Processes](10-processes.md) - which process reads which config section

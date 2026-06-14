# Engine Configuration

!!! note "Learning objectives"
    After reading this page you will understand:

    - Which top-level `engine_config.yaml` sections are required vs optional, and what each one controls
    - How to configure symbols (a.k.a. Order Books or LOBs), tick precision, seeded market-maker quotes/combos, and session schedules
    - How gateway roles (`TRADER`, `MARKET_MAKER`, `ADMIN`) change permissions and operational controls
    - How risk-control settings are resolved (global defaults, levels, and symbol-level overrides)
    - What startup and persistence precedence rules affect real runtime behavior (restore vs seed, `DAY` vs `GTC`)
  

## Configuring the exchange

The matching engine and session scheduler both consume the YAML configuration file in the project root. It defines:

- the allowed ALF order-entry gateways
- the traded symbol universe
- optional `sessions_enabled` control for auction/session enforcement
- optional seeded last-buy / last-sell statistics
- startup market-maker quotes used to seed initial book liquidity
- optional startup market-maker combo orders
- optional global MM obligation defaults
- optional global risk-control level profiles
- optional daily session schedule for `pm-scheduler`

## Exchange Protocol Family

EduMatcher defines a family of named protocols, each serving a different participant type:

| Protocol | Full name | Purpose | Status |
|---|---|---|---|
| ALF | ALmost FIX | Text-based interactive order entry | Implemented |
| BALF | Binary ALF | Fixed-width binary order entry for low-latency clients | Design proposal |
| CALF | Channel ALF | Line-based market-data distribution and subscription | Design proposal |

Each protocol has its own section under `gateways:` in `engine_config.yaml`. Currently only `gateways.alf` is active; `gateways.balf` and `gateways.calf` are reserved for future releases when those protocols are implemented.

- **ALF** uses a pipe-delimited text format (`FIELD=VALUE|FIELD=VALUE`) delivered through the interactive `pm-gateway` terminal process. This is the only order-entry protocol currently available.
- **BALF** will use fixed-width binary frames with sequence numbers and integer-scaled prices, targeting programmatic clients where text-parsing latency is undesirable. See the BALF appendix in the User Guide for the message layout specification.
- **CALF** will provide a subscribe/unsubscribe market-data feed delivering order-book snapshots, trade prints, and session-state changes over a persistent TCP connection with sequence-based gap detection. See the CALF appendix in the User Guide for the full protocol specification.

---

## File Location

By default both processes look for `engine_config.yaml` in the project root.
You can override it with `--config`.

```bash
poetry run pm-engine --verbose
poetry run pm-engine --verbose --config my_config.yaml

poetry run pm-scheduler
poetry run pm-scheduler --config my_config.yaml
```

### Missing-file behavior

The engine does **not** fail if the config file is missing. If the configured
path does not exist, the engine starts in unrestricted mode:

- no symbol allowlist
- no ALF gateway allowlist
- no seeded market statistics
- no startup market-maker quotes
- no startup market-maker combos

The scheduler behaves differently:

- `pm-scheduler --config missing.yaml` is **fatal**
- `pm-scheduler` with no explicit `--config` falls back to its built-in default
  schedule if the default file is missing or lacks a `schedule` section

## Top-level Structure

The full supported schema is:

```yaml
sessions_enabled: true

gateways:
  alf:
    - id: TRADER01
      description: Human trader workstation

symbols:
  AAPL:
    tick_decimals: 2
    level: L2
    last_buy_price: 209.50
    last_sell_price: 210.50
    collar:
      static_band_pct: 0.20
      dynamic_band_pct: 0.02
    circuit_breaker:
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
    market_maker_quotes:
      - gateway_id: MM01
        quote_id: MM-AAPL-1
        bid_price: 209.00
        ask_price: 211.00
        bid_qty: 2000
        ask_qty: 2000
        tif: DAY

market_maker_combos:
  - combo_id: MM-PAIR-AAPL-MSFT
    combo_type: AON
    tif: DAY
    legs:
      - symbol: AAPL
        side: BUY
        order_type: LIMIT
        quantity: 100
        price: 209.50
      - symbol: MSFT
        side: SELL
        order_type: LIMIT
        quantity: 50
        price: 415.50

mm_obligation_defaults:
  enforce_mm_obligation: false
  mm_max_spread_ticks: 10
  mm_min_qty: 100
  symbols:
    AAPL:
      enforce_mm_obligation: true
      mm_max_spread_ticks: 8
      mm_min_qty: 120

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

schedule:
  pre_open: "09:00"
  opening_auction_start: "09:25"
  continuous_start: "09:30"
  closing_auction_start: "16:00"
  closing_auction_end: "16:05"

snapshot_interval_sec: 0.5
```

### Required vs optional top-level keys

| Key | Required when config file exists? | Used by |
|---|---|---|
| `gateways` | Yes | Engine |
| `gateways.alf` | Yes (ALF order-entry gateways) | Engine |
| `gateways.balf` | No (reserved for future BALF support) | Engine |
| `gateways.calf` | No (reserved for future CALF support) | Engine |
| `symbols` | Yes | Engine |
| `market_maker_combos` | No | Engine |
| `risk_controls` | No | Engine |
| `mm_obligation_defaults` | No | Engine |
| `circuit_breaker_defaults` | No | Engine |
| `snapshot_interval_sec` | No | Engine |
| `sessions_enabled` | No | Engine |
| `schedule` | No | Scheduler |

If a config file exists, `symbols` must be a mapping and `gateways.alf` must be
a list. Otherwise config loading fails and the engine exits.

## Snapshot Publish Throttle

`snapshot_interval_sec` controls the per-symbol throttle window for
`book.<SYMBOL>` publications from dirty books.

```yaml
snapshot_interval_sec: 0.5
```

Rules:

- must be numeric
- must be `> 0`
- default is `0.5` seconds when omitted

The engine poll loop still runs every 200ms; this setting only controls how
frequently a changed symbol is eligible for snapshot publication.

## ALF Gateway Allowlist

Only ALF gateway IDs listed under `gateways.alf` may connect and submit orders.

```yaml
gateways:
  alf:
    - id: TRADER01
      description: The first trader
    - id: TRADER02
      description: High frequency
```

### Supported fields

| Field | Required | Notes |
|---|---|---|
| `id` | Yes | Must be a non-empty string. Stored uppercased by the loader. |
| `description` | No | Display-only label used in gateway auth responses and logs. Defaults to empty string. |
| `role` | No | `TRADER`, `MARKET_MAKER`, or `ADMIN`. Defaults to `TRADER`. |
| `disconnect_behaviour` | No | `CANCEL_QUOTES_ONLY`, `CANCEL_ALL`, or `LEAVE_ALL`. Defaults to `CANCEL_QUOTES_ONLY`. |
| `quote_refresh_policy` | No | `INACTIVATE_ON_ANY_FILL`, `INACTIVATE_ON_FULL_FILL`, or `NEVER_INACTIVATE`. Defaults to `INACTIVATE_ON_ANY_FILL`. |
| `enforce_mm_obligation` | No | Boolean toggle for quote obligation checks. Defaults to `false`. |
| `mm_max_spread_ticks` | No | Max allowed quote spread in ticks when enforcement is enabled. Defaults to `10`. |
| `mm_min_qty` | No | Min allowed bid/ask quote quantity when enforcement is enabled. Defaults to `100`. |

### Role Privileges and Obligations

`role` defines the participant class attached to an ALF gateway session. The
engine currently enforces the following differences:

| Role | Can submit regular orders | Can submit quotes (`quote.new`) | MM obligation checks | Disconnect behavior knobs | Kill switch (`risk.kill_switch`) | Exchange Wide CB Halt (`risk.circuit_breaker_halt_all`) | Exchange Wide CB Resume (`risk.circuit_breaker_resume_all`) |
|---|---|---|---|---|---|---|---|
| `TRADER` | Yes | No | Not applicable | Yes | Yes | No | No |
| `MARKET_MAKER` | Yes | Yes | Applicable when enabled | Yes | Yes | No | No |
| `ADMIN` | Yes | No (current behavior) | Not applicable | Yes | Yes | Yes | Yes |

Detailed behavior:

- `TRADER`:
  - Intended for directional/order-entry participants.
  - May place/cancel/amend orders and use normal gateway APIs.
  - Quote submission is rejected because only `MARKET_MAKER` may quote.

- `MARKET_MAKER`:
  - All trader capabilities, plus `quote.new` / `quote.cancel` support.
  - Subject to quote-lifecycle controls (`quote_refresh_policy`).
  - Subject to MM obligation policy when enabled (`enforce_mm_obligation`,
    `mm_max_spread_ticks`, `mm_min_qty`, plus symbol overrides).

- `ADMIN`:
  - Reserved role for operational/admin participants.
  - Not allowed to submit MM quotes unless role is `MARKET_MAKER`.
  - Authorized to send `risk.circuit_breaker_halt_all`, which halts all known
    symbols in one command.
  - Authorized to send `risk.circuit_breaker_resume_all`, which resumes all
    symbols that were halted by the global halt command.
  - Can still invoke shared APIs such as kill switch, because kill switch is
    currently gated by authenticated/connected gateway status, not by role.

!!! note "Current implementation scope"
    Role-based enforcement is currently focused on quote authorization
    (`MARKET_MAKER` only), MM obligation policy, and ADMIN authorization for
    `risk.circuit_breaker_halt_all` / `risk.circuit_breaker_resume_all`.
    Additional ADMIN-specific privileges (if desired) would require explicit
    engine-side role checks.



Example:

```yaml
gateways:
  alf:
    - id: TRADER01
      description: Human trader workstation
      role: TRADER
      disconnect_behaviour: CANCEL_ALL
      quote_refresh_policy: INACTIVATE_ON_ANY_FILL
      enforce_mm_obligation: false
    - id: MM01
      description: Market maker
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_FULL_FILL
      enforce_mm_obligation: true
      mm_max_spread_ticks: 8
      mm_min_qty: 50
```

### Runtime effect

ALF gateway startup flow:

1. ALF gateway sends `system.gateway_connect`
2. Engine checks the configured `gateways.alf` allowlist
3. Engine replies on `system.gateway_auth.<GW_ID>`
4. Rejected gateways cannot place orders

Direct orders from an unauthorised ALF gateway are rejected with reason:

```text
Gateway not configured: <GW_ID>
```

## Global MM Obligation Defaults

`mm_obligation_defaults` defines quote-obligation policy defaults for
market-maker quote validation, with optional per-symbol overrides.

```yaml
mm_obligation_defaults:
  enforce_mm_obligation: false
  mm_max_spread_ticks: 10
  mm_min_qty: 100
  symbols:
    TSLA:
      enforce_mm_obligation: true
      mm_max_spread_ticks: 8
      mm_min_qty: 120
```

### Supported fields

| Field | Required | Description |
|---|---|---|
| `enforce_mm_obligation` | No | Global default toggle for MM quote obligation checks. |
| `mm_max_spread_ticks` | No | Global default max allowed quote spread. |
| `mm_min_qty` | No | Global default min quote size on each side. |
| `symbols` | No | Per-symbol override mapping (`<SYMBOL> -> policy`). |

Each `symbols.<SYMBOL>` policy supports the same three fields.

### MM obligation precedence

The effective policy for a quote is resolved using:

1. `gateways.alf[*].mm_obligations.<SYMBOL>` (most specific)
2. `mm_obligation_defaults.symbols.<SYMBOL>`
3. Gateway flat fields (`enforce_mm_obligation`, `mm_max_spread_ticks`, `mm_min_qty`)
4. `mm_obligation_defaults` flat fields (least specific)

This lets you set one global policy and then tighten/relax specific symbols or
specific gateway+symbol pairs.

## Symbol Universe

Only symbols declared under `symbols:` are accepted by the engine.

```yaml
symbols:
  AAPL: {}
  MSFT: {}
  TSLA: {}
```

Each symbol key is uppercased by the loader. The value for a symbol must be a
mapping or `null`/empty.

### Runtime effect

- orders for unknown symbols are rejected
- only configured symbols are considered valid in combo seed legs
- only configured symbols participate in seeded stats and market-maker startup flow

Rejected single-leg orders use reason:

```text
Symbol not configured: UNKNOWN
```

!!! tip
    The `SYMBOLS` command in the gateway reflects the live symbol set known by
    the engine. After startup this matches the configured allowlist plus any
    books created for restored state that still belongs to configured symbols.

## Symbol-Level Options

Every symbol entry supports the following keys:

| Key | Type | Required | Description |
|---|---|---|---|
| `level` | string | No | Named collar profile from `risk_controls.levels`.
| `collar` | mapping | No | Per-symbol collar config or override.
| `circuit_breaker` | mapping | No | Per-symbol circuit-breaker overrides (threshold ladder). |
| `last_buy_price` | number | No | Seed value for the viewer’s Last Buy field. |
| `last_sell_price` | number | No | Seed value for the viewer’s Last Sell field. |
| `market_maker_quotes` | list of mappings | No | Quote definitions injected at engine startup as linked bid/ask quote legs. |

### Global risk-control levels and symbol precedence

You can define reusable risk profiles once at the top level and then assign
them per symbol.

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

symbols:
  AAPL:
    # Inherits L2 because default_level is L2
    tick_decimals: 2
  TSLA:
    level: L1
    # Partial override: static from L1, dynamic overridden below
    collar:
      dynamic_band_pct: 0.06
```

Resolution order for collar values is:

1. Symbol-level override (`symbols.<sym>.collar`)
2. Symbol level (`symbols.<sym>.level`)
3. Global default level (`risk_controls.default_level`)
4. Built-in hard defaults

Validation rules:

- `risk_controls.levels` must be a mapping
- `risk_controls.default_level` must reference a defined level name
- `symbols.<sym>.level` must reference a defined level name
- level `collar` sections must be mappings when present

### Circuit-breaker threshold ladders (L1/L2/L3)

Circuit breakers are configured as a threshold ladder, not by selecting one
"default breaker level". A trade's absolute price shift from rolling reference
determines which level fires.

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
      halt_duration_ns:   # null => rest of trading day
      resumption_mode: AUCTION

symbols:
  TSLA:
    circuit_breaker:
      levels:
        L1:
          halt_duration_ns: 600000000000
```

Circuit-breaker precedence is:

1. `symbols.<sym>.circuit_breaker` (most specific)
2. `circuit_breaker_defaults`
3. built-in defaults (L1=7%/5m, L2=13%/15m, L3=20%/rest-of-day)

Validation rules:

- `circuit_breaker.levels` values must be mappings
- each level requires `price_shift_pct` in `(0, 1)`
- `halt_duration_ns` must be positive integer or null
- `resumption_mode` must be `AUCTION` or `CONTINUOUS`

### `last_buy_price` and `last_sell_price`

```yaml
symbols:
  MSFT:
    last_buy_price: 415.00
    last_sell_price: 415.50
```

These values seed the order-book viewer before the first trade in a fresh
environment.

#### Precedence

Persisted `data/book_stats.json` values take priority over config seeds.
Config values are only used to fill gaps when no persisted value exists.

### `market_maker_quotes`

```yaml
symbols:
  MSFT:
    market_maker_quotes:
      - gateway_id: MM01
        quote_id: MM-MSFT-1
        bid_price: 414.00
        ask_price: 416.00
        bid_qty: 1000
        ask_qty: 1000
        tif: DAY
        seed_once: true   # default — inject only on first startup
```

These quotes are injected at engine startup by creating linked bid/ask quote
legs on the target symbol.

#### Validation rules

- `market_maker_quotes` must be a list
- every element must be a mapping with:
  - `gateway_id`
  - `bid_price`, `ask_price`
  - `bid_qty`, `ask_qty`
- `gateway_id` must reference a configured ALF gateway (`gateways.alf` entry) with role `MARKET_MAKER`
- each quote requires `bid_price < ask_price`
- each quote requires positive quantities
- if at least one `MARKET_MAKER` gateway exists, each symbol must define at least one `market_maker_quotes` entry

#### Supported fields

| Field | Required | Description |
|---|---|---|
| `gateway_id` | Yes | Must be a configured ALF gateway (`gateways.alf` entry) with role `MARKET_MAKER`. |
| `quote_id` | No | Optional explicit quote ID. If omitted, engine generates one. |
| `bid_price` | Yes | Bid side display price; converted to ticks by the engine. |
| `ask_price` | Yes | Ask side display price; converted to ticks by the engine. |
| `bid_qty` | Yes | Bid quantity, must be positive. |
| `ask_qty` | Yes | Ask quantity, must be positive. |
| `tif` | No | Defaults to `DAY`; supports `DAY` or `GTC`. |
| `seed_once` | No | Defaults to `true`. When `true`, the seed is injected only on the very first startup for that symbol (detected via `book_stats.json`). When `false`, re-injected on every startup. |

#### Persistence interaction

Quote legs (regardless of `tif`) are **never written to `gtc_orders.json`** at
shutdown. Config seeds are always the authoritative source; saving the legs
would create duplicate orders in the book on the next startup.

The `seed_once` field controls how often the seed is applied:

| `seed_once` | Day 1 (no `book_stats.json` entry for symbol) | Day 2+ (entry exists) |
|---|---|---|
| `true` *(default)* | Seed injected | Skipped — symbol has prior history |
| `false` | Seed injected | Seed injected |

!!! tip "Resetting to day-one state"
    Delete `src/data/book_stats.json` before starting the engine. Every symbol
    will appear new again and `seed_once: true` seeds will fire again.

## First Startup (Fresh Seeded Book)

The first time you start the engine there are no persisted files. The entire
opening book is created from `market_maker_quotes` in the config.

### Prerequisites

1. Every symbol must have at least one `market_maker_quotes` entry.
2. Every quote seed must reference a configured `MARKET_MAKER` gateway.
3. Bid price must be strictly less than ask price for every seed.

If any of these rules are violated, the config loader raises a `ValueError` and
the engine exits before binding any socket.

### Procedure

```bash
# 1. Ensure no stale persistence files are present
rm -f data/gtc_orders.json data/book_stats.json data/gtc_combos.json

# 2. Start the engine in verbose mode so you can see the seeding log
poetry run pm-engine --verbose
```

The engine will log each injected quote and a summary line:

```
[ENGINE] MM quote SEED-MM01-AAPL-1 AAPL bid=209.00x2000 ask=211.00x2000 gw=MM01
[ENGINE] MM quote SEED-MM01-MSFT-1 MSFT bid=414.00x1000 ask=416.00x1000 gw=MM01
[ENGINE] Injected 2 market-maker quote(s) and 0 combo(s).
```

### What happens before the MM gateway connects

Seed quotes enter the book the instant the engine starts, before any gateway
has connected.  The `gateway_id` in a seed quote is an **accounting identity**
— it determines which gateway owns the quote, not whether that gateway is
online.

If a trader connects and sends an aggressive order during continuous session
before the MM gateway dials in, the order will match against the seed quote
normally.  Depending on the MM gateway's configured `quote_refresh_policy`,
the quote may be inactivated (sibling leg cancelled).  The book then has no MM
liquidity until the MM connects and re-quotes.

If a fill generated from seed liquidity breaches the configured circuit-breaker
band, the symbol can halt immediately even before the market-maker process
connects.  See [Risk Controls](12-risk-controls.md) for exact circuit-breaker
semantics.

### Subsequent startups

On every restart the engine evaluates each seed entry:

- **`seed_once: true` (default)**: if `book_stats.json` already has an entry
  for the symbol, the seed is skipped. The symbol has been traded before; the
  live market maker is expected to quote when ready.
- **`seed_once: false`**: the seed is always injected, regardless of history.
  Useful for demo setups where a specific spread must be the opening quote
  every day.

In both cases, quote legs are never persisted across restarts. To force a
full day-one reset (re-inject all `seed_once: true` seeds), delete
`src/data/book_stats.json` before starting the engine.

## Startup Market-Maker Combo Orders

Combos are configured at the top level because they span multiple symbols.

```yaml
market_maker_combos:
  - combo_id: MM-PAIR-AAPL-MSFT
    combo_type: AON
    tif: DAY
    legs:
      - symbol: AAPL
        side: BUY
        order_type: LIMIT
        quantity: 100
        price: 209.50
      - symbol: MSFT
        side: SELL
        order_type: LIMIT
        quantity: 50
        price: 415.50
```

These combos are injected at engine startup with internal `gateway_id = "MM"`
through the same combo acceptance path used for live combo orders.

### Supported fields

| Field | Required | Description |
|---|---|---|
| `combo_id` | Yes | User-visible identifier for the seeded combo |
| `combo_type` | No | Currently `AON` is supported; defaults to `AON` |
| `tif` | No | Combo parent time-in-force; defaults to `DAY` |
| `legs` | Yes | List of 2 to 10 combo legs |

Each leg supports:

| Key | Required | Description |
|---|---|---|
| `symbol` | Yes | Must reference a configured symbol |
| `side` | Yes | `BUY` or `SELL` |
| `order_type` | Yes | Same order types supported by combo legs in live entry |
| `quantity` | Yes | Must be positive |
| `price` | Conditional | Required for `LIMIT`, `FOK`, `STOP_LIMIT`, `ICEBERG` |
| `stop_price` | Conditional | Used for `STOP`, `STOP_LIMIT` |
| `smp_action` | No | Defaults to `NONE` |

### Validation rules

- `market_maker_combos` must be a list
- each combo entry must be a mapping
- `combo_id` must be a non-empty string
- `combo_type` must be valid
- `tif` must be valid
- `legs` must be a list of length 2 to 10
- duplicate symbols inside one combo are rejected
- every leg symbol must exist under `symbols`
- invalid leg structure causes config load failure

### Persistence interaction

Combo seeds follow the same duplication caveat as seeded single-leg GTC orders:

- `DAY` combo seeds are cleanly recreated every startup
- `GTC` combo seeds can be restored from persistence and then seeded again from config

For a stable demo/opening book, use `DAY` unless you explicitly want persisted
combo inventory and are managing the persistence files yourself.

## Session Schedule

The `schedule` section is consumed by `pm-scheduler`, not by the matching
engine directly.

```yaml
schedule:
  pre_open: "09:00"
  opening_auction_start: "09:25"
  continuous_start: "09:30"
  closing_auction_start: "16:00"
  closing_auction_end: "16:05"
```

### Supported fields

| Key | Required | Default |
|---|---|---|
| `pre_open` | No | `09:00` |
| `opening_auction_start` | No | `09:25` |
| `continuous_start` | No | `09:30` |
| `closing_auction_start` | No | `16:00` |
| `closing_auction_end` | No | `16:05` |

All values are interpreted as local-time `HH:MM` strings.

### Scheduler behavior

- if the config file exists and `schedule` contains any of these keys, the scheduler uses them
- missing keys fall back to their defaults
- if you pass `--config` and the file is missing, the scheduler exits with a fatal error
- if you do **not** pass `--config` and the default file is missing or `schedule` is absent, the scheduler uses its built-in default schedule

The default session path is:

```text
PRE_OPEN -> OPENING_AUCTION -> CONTINUOUS -> CLOSING_AUCTION -> CLOSED
```

### Important distinction

The scheduler only matters when `sessions_enabled: true` in the engine config.
With sessions disabled, the engine stays in `CONTINUOUS` and ignores incoming
`session.transition` messages. With sessions enabled, the engine starts in
`CLOSED` and waits for scheduler-driven transitions.

## Startup and Persistence Order

The effective startup sequence is:

```text
Engine startup
    |
    +-- 1. Parse config if present
    |       +-- establish symbol allowlist / gateway allowlist / session flags
    |
    +-- 2. Bind main PULL/PUB sockets
    +-- 3. Load persisted book stats from data/book_stats.json
    |       +-- use config last_buy_price / last_sell_price only where stats are missing
    +-- 4. Restore persisted GTC orders from data/gtc_orders.json
    +-- 5. Restore persisted GTC combos from data/gtc_combos.json
    +-- 6. Inject market_maker_quotes
    +-- 7. Inject market_maker_combos
    +-- 8. Bind drop-copy PUB :5557 if available
    +-- 9. Publish initial book snapshots
```

This ordering matters:

- persisted GTC state comes back before seeded startup liquidity
- persisted book stats override config seeds
- seeded GTC quotes or combos can duplicate restored GTC state

## Full Example

```yaml
gateways:
  alf:
    - id: TRADER01
      description: The first trader
    - id: TRADER02
      description: High frequency

symbols:
  MSFT:
    last_buy_price: 415.00
    last_sell_price: 415.50
    market_maker_quotes:
      - gateway_id: TRADER02
        quote_id: MM-MSFT-1
        bid_price: 414.00
        ask_price: 416.00
        bid_qty: 1000
        ask_qty: 1000
        tif: DAY

  AAPL:
    last_buy_price: 209.50
    last_sell_price: 210.50
    market_maker_quotes:
      - gateway_id: TRADER02
        quote_id: MM-AAPL-1
        bid_price: 209.00
        ask_price: 211.00
        bid_qty: 2000
        ask_qty: 2000
        tif: DAY

  TSLA:
    last_buy_price: 248.00
    last_sell_price: 249.00
    market_maker_quotes:
      - gateway_id: TRADER02
        quote_id: MM-TSLA-1
        bid_price: 247.00
        ask_price: 250.00
        bid_qty: 500
        ask_qty: 500
        tif: DAY

market_maker_combos:
  - combo_id: MM-PAIR-AAPL-MSFT
    combo_type: AON
    tif: DAY
    legs:
      - symbol: AAPL
        side: BUY
        order_type: LIMIT
        quantity: 100
        price: 209.50
      - symbol: MSFT
        side: SELL
        order_type: LIMIT
        quantity: 50
        price: 415.50

schedule:
  pre_open: "09:00"
  opening_auction_start: "09:25"
  continuous_start: "09:30"
  closing_auction_start: "16:00"
  closing_auction_end: "16:05"
```

## Adding or Removing Symbols

Edit `engine_config.yaml` and restart the engine.

- adding a symbol makes it tradeable on next startup
- removing a symbol causes future orders for it to be rejected
- persisted GTC orders for removed symbols are skipped during restore
- startup combo seeds referencing removed symbols will make config loading fail

## Tick Precision

Each symbol can define `tick_decimals` in `engine_config.yaml`.

- `tick_decimals: 2` means one tick is `0.01`.
- `tick_decimals: 4` means one tick is `0.0001`.

Example:

```yaml
symbols:
  AAPL:
    tick_decimals: 2
    last_buy_price: 209.50
    last_sell_price: 210.50
```

Inbound config price values are converted to integer ticks during config load.

## Migration Cutover Note

For the tick/ns migration with no backward compatibility, remove persisted files
before the first migrated startup:

```bash
rm -f data/gtc_orders.json data/book_stats.json data/gtc_combos.json
```

## See also

- [Running the Engine](03-running-the-engine.md) — minimum-viable config and startup order
- [Processes](10-processes.md) — what each process does and which config keys it reads
- [Risk Controls](12-risk-controls.md) — collar and circuit-breaker configuration in depth
- [Persistence](11-persistence.md) — how GTC orders, book stats, and combos are saved and restored
- [Gateway](08-gateway.md) — role privileges and disconnect behaviour at runtime

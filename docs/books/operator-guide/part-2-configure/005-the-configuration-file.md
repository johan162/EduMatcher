# The Configuration File, Block by Block

<a id="the-shape-of-the-file"></a>

!!! note "Learning objectives"
    After reading this chapter you will understand:

    - how `engine_config.yaml` is organised into top-level blocks, and which process reads which block
    - the smallest file that gives you a working exchange, and what each later block adds to it
    - every parameter of every block: its type, its default, and what it changes at runtime
    - which mistakes the tools catch for you, and which they do not

`engine_config.yaml` has grown into a large file. It describes the instruments,
who may trade, when the exchange is open, how prices are protected, how
liquidity is seeded, and how every gateway and service listens. Read top to
bottom it is easy to lose the thread, so this chapter does two things:

1. It shows the **shape** of the file first — a map of the top-level blocks
   and what each one is for.
2. It then **builds a complete file in nine steps**. Step 1 is the smallest
   file the engine accepts; every later step adds one concern, explains every
   parameter of it, and ends with a file that still passes `pm-cverifier`.
   Step 9 is a full specification you can use as a template.

Every YAML listing in this chapter was verified: each step's cumulative file
was run through `pm-cverifier`, and the final file was compiled with
`pm-config-deploy` and started on a real `pm-engine`.

!!! tip "Two ways to reach the same file"
    You do not have to type the file by hand. [`pm-config-gen`](010-the-configuration-workflow.md#generate-configs-with-pm-config-gen)
    generates it from command-line options and the
    [Configuration GUI](030-config-gui.md) builds it in a form. Both write the
    structure described here. Knowing the structure still matters: you will
    read, review and hand-edit generated files.

## The shape of the file

`engine_config.yaml` is a single YAML mapping. Each top-level key is a
**block**. Only two blocks are required; every other block is optional and has
built-in defaults.

```text
engine_config.yaml
│
├── CORE ─ who and what ──────────────────────────────────────────────────
│   ├── symbols                    required   the instruments that can trade
│   ├── participants               required   the gateway IDs that may log in
│   └── participant_defaults                  defaults inherited by participants
│
├── TRADING DAY ─ when ───────────────────────────────────────────────────
│   ├── sessions_enabled                      scheduler-driven phases on/off
│   ├── schedule                              the five phase times, per weekday
│   └── locale                                country (holidays) and timezone
│
├── PRICE PROTECTION ─ how prices are guarded ────────────────────────────
│   ├── enforce_collars                       global collar switch
│   ├── enforce_circuit_breakers              global circuit-breaker switch
│   ├── risk_controls                         named collar levels
│   └── circuit_breaker_defaults              the halt ladder and reopening rules
│
├── LIQUIDITY ─ market makers and seeds ──────────────────────────────────
│   ├── mm_obligation_defaults                quote-quality policy
│   ├── require_mm_seed_quotes                every symbol needs a seed quote?
│   └── market_maker_combos                   startup multi-leg combo orders
│
├── ENGINE TUNING ────────────────────────────────────────────────────────
│   ├── engine_tuning                         memory and snapshot knobs
│   └── auction_indicative_interval_sec       indicative-price refresh rate
│
├── DERIVED DATA ─────────────────────────────────────────────────────────
│   └── indices                               market indices (pm-index)
│
├── ACCESS POINTS ─ how the outside world connects ───────────────────────
│   ├── alf_gateway                           pm-alf-gwy   text order entry
│   ├── balf_gateway                          pm-balf-gwy  binary order entry
│   ├── market_data_gateway                   pm-md-gwy    market data (CALF)
│   ├── post_trade_gateway                    pm-ralf-gwy  post-trade (RALF)
│   ├── dc_gateway                            pm-dc-gwy    drop copy
│   └── api_gateways                          pm-api-gwy   REST / WebSocket
│
└── OPERATIONS ─ watching the exchange ───────────────────────────────────
    ├── log_server                            pm-log-srv   central log collector
    └── monitor                               pm-monitor   health beacons
```

The same map as a table, with the process that reads each block and the step of
this chapter that introduces it:

| Block | Required | Read by | Step |
|---|:-:|---|:-:|
| `include` | no | every tool that reads the authored file | [Splitting the file](#splitting-the-file-with-include) |
| `symbols` | **yes** | `pm-engine`, `pm-index` | [1](#step-1-the-smallest-working-file), [2](#step-2-reference-data), [4](#step-4-price-protection), [5](#step-5-market-makers-and-seeded-liquidity) |
| `participants` | **yes** | `pm-engine`, `pm-alf-gwy`, `pm-balf-gwy` | [1](#step-1-the-smallest-working-file), [5](#step-5-market-makers-and-seeded-liquidity) |
| `participant_defaults` | no | `pm-engine` | [5](#step-5-market-makers-and-seeded-liquidity) |
| `sessions_enabled` | no | `pm-engine` | [1](#step-1-the-smallest-working-file), [3](#step-3-the-trading-day) |
| `schedule` | no | `pm-scheduler`, `pm-engine` | [3](#step-3-the-trading-day) |
| `locale` | no | `pm-scheduler`, `pm-stats`, `pm-clearing`, `pm-monitor` | [3](#step-3-the-trading-day) |
| `enforce_collars`, `enforce_circuit_breakers` | no | `pm-engine` | [4](#step-4-price-protection) |
| `risk_controls` | no | `pm-engine` | [4](#step-4-price-protection) |
| `circuit_breaker_defaults` | no | `pm-engine` | [4](#step-4-price-protection) |
| `mm_obligation_defaults` | no | `pm-engine` | [5](#step-5-market-makers-and-seeded-liquidity) |
| `require_mm_seed_quotes` | no | `pm-engine` | [5](#step-5-market-makers-and-seeded-liquidity) |
| `market_maker_combos` | no | `pm-engine` | [5](#step-5-market-makers-and-seeded-liquidity) |
| `engine_tuning`, `auction_indicative_interval_sec` | no | `pm-engine` | [6](#step-6-engine-tuning) |
| `indices` | no | `pm-index` | [7](#step-7-a-market-index) |
| `alf_gateway` | no | `pm-alf-gwy` | [8](#step-8-the-access-points) |
| `balf_gateway` | no | `pm-balf-gwy` | [8](#step-8-the-access-points) |
| `market_data_gateway` | no | `pm-md-gwy` | [8](#step-8-the-access-points) |
| `post_trade_gateway` | no | `pm-ralf-gwy` | [8](#step-8-the-access-points) |
| `dc_gateway` | no | `pm-dc-gwy` | [8](#step-8-the-access-points) |
| `api_gateways` | no | `pm-api-gwy` | [8](#step-8-the-access-points) |
| `log_server` | no | `pm-log-srv` | [9](#step-9-operations-logging-and-health) |
| `monitor` | no | `pm-monitor` and every process that sends a health beacon | [9](#step-9-operations-logging-and-health) |

Three facts about the file explain most of the surprises operators meet:

- **No process reads the YAML you edit.** `pm-config-deploy` validates it and
  compiles it into `<EDUMATCHER_DATA_DIR>/ref_data/engine_config.json`, and that
  compiled artifact is the only thing the running processes load. Edit the YAML,
  then redeploy, then restart. See
  [The Configuration Workflow](010-the-configuration-workflow.md#configuration-workflow).
- **Each process reads only its own blocks.** `pm-engine` never looks at
  `alf_gateway`; `pm-alf-gwy` never looks at `risk_controls`. A mistake in a
  gateway block cannot be seen by the engine — `pm-cverifier` is what looks at
  the whole file.
- **A misspelled key is an error.** The loaders themselves ignore a key they do
  not know, so `hartbeat_interval_sec` would silently leave the default in
  force. `pm-cverifier` closes that gap: `S121` reports any key that no loader
  reads, at any level, and names the closest accepted spelling. The verifier
  runs inside `pm-config-deploy`, so an unrecognised key stops a deploy.

### Conventions used by every block

| Convention | Rule |
|---|---|
| **Prices** | Written as display money (`209.50`), never as ticks. A price the symbol's tick grid cannot represent (`209.505` at `tick_decimals: 2`) is a config error, not a silent rounding. |
| **IDs and names** | Symbols, participant IDs, level names and index IDs are upper-cased by the loader. Write them upper-case anyway. |
| **Durations** | Suffix tells the unit: `_sec`, `_ms`, `_days`, `_hours` are what they say. Circuit-breaker fields end in `_ns` — **nanoseconds**: `300000000000` is five minutes. |
| **Fractions** | Percentages are fractions: `0.20` means 20 %. |
| **Wall-clock times** | `"HH:MM"` strings, 24-hour, in `locale.session_timezone`. Quote them; an unquoted `9:30` is read by YAML as a number of minutes. |
| **`null`** | An empty value (`halt_duration_ns:`) is `null`. Where a field allows it, `null` means "no limit". |
| **Bind addresses** | `bind_address` / `host` default to `0.0.0.0` (all interfaces). The environment variable `EDUMATCHER_GATEWAY_BIND_HOST`, when set, overrides every one of them. |
| **Ports** | Every listener in the file must use a different port — see [Ports at a glance](#ports-at-a-glance). `pm-cverifier` reports a clash as `M018`. |

## Splitting the file with `include`

A class with hundreds of symbols and participants makes one file hard to read
and hard to compare between runs. YAML has no include of its own, so
EduMatcher defines a small one: the top-level key `include` lists other files
whose contents are merged into the configuration.

```yaml
include:
  - symbols.yaml
  - participants.yaml

sessions_enabled: true
locale: {country: SE, session_timezone: Europe/Stockholm}
```

```yaml
# symbols.yaml
symbols:
  AAPL: {tick_decimals: 2, last_buy_price: 150.00}
  MSFT: {tick_decimals: 2, last_buy_price: 400.00}
```

The rules are deliberately few:

| Rule | Detail |
|---|---|
| **Where** | Paths are relative to the file that lists them. No absolute paths and no `..`; a subdirectory (`parts/symbols.yaml`) is fine. |
| **Names** | Each file may be listed once. Beside the main file, `engine_config.yaml`, `engine_config.json` and `market_sim.yaml` are reserved, because `pm-config-deploy` installs its own files under those names; put such a file in a subdirectory or rename it. The same applies to a `credentials_file`. |
| **Depth** | One level. An included file may not have an `include` of its own; list every file in the main file. |
| **Content** | An included file is a YAML mapping using the same top-level keys as the main file. |
| **Lists** | A list present in several files (`participants`) is concatenated: the main file's entries first, then each include in the order listed. |
| **Mappings** | A mapping present in several files (`symbols`) is merged. The same symbol defined twice is an error. |
| **Anything else** | A scalar or a block defined twice, or a list in one file and a mapping in another, is an error that names both files. Nothing is silently overridden. |

Everything that reads the file sees the merged result, so `pm-cverifier`,
`pm-config-show` and `pm-config-deploy` behave exactly as if you had written one
file. Three things differ in practice:

- **Findings name the file.** A verifier finding about `symbols.AAPL` that comes
  from an included file is followed by `in symbols.yaml`, and `pm-config-deploy`
  shows it as `[symbols.yaml: symbols.AAPL.tick_decimals]`. A broken or missing
  include is `Y005`.
- **Deploy treats the files as one unit.** The staleness check covers every
  file, so editing only `symbols.yaml` without redeploying is reported, just as
  for the main file. `pm-config-deploy` copies the main file and its includes
  beside the artifact, and removes copies of includes you have since dropped.
- **`pm-new-symbol` edits the include.** A symbol is added to the file that
  supplies the last listed symbol, and the main file is left untouched.

`pm-config-gen --split --output engine_config.yaml` writes a configuration in
this layout from the start: `symbols.yaml` and `participants.yaml` beside the
main file.

## Step 1: the smallest working file

Two blocks are required: **`symbols`** (what can be traded) and
**`participants`** (who may trade). Add `sessions_enabled: false` and you have a
file that starts an exchange which is open for continuous trading immediately.

```yaml
sessions_enabled: false

symbols:
  AAPL:

participants:
  - id: TRADER01
  - id: TRADER02
  - id: OPS01
    role: ADMIN
```

This is a complete, valid `engine_config.yaml`. It lists one instrument, `AAPL`,
and three gateway IDs: two ordinary traders and one `ADMIN` for the operator.
Everything else is default.

!!! warning "Always decide `sessions_enabled` explicitly"
    When a config file exists and `sessions_enabled` is left out, the engine
    behaves as if it were `true`: it starts in the `CLOSED` state and waits for
    `pm-scheduler` to open the market. If you did not mean to run a scheduler,
    your students will log in to a closed exchange. (Only when there is *no*
    config file at all does the engine default to continuous trading.)

Run the verifier on it:

```bash
pm-cverifier engine_config.yaml
```

```text
pm-cverifier engine_config.yaml

✓ YAML syntax: OK
✓ Schema: 0 errors
⚠ Semantic: 1 warning
⚠ Completeness: 5 advisories

[M032] WARN  No read-only API credential (gateway_id: null) is defined under api_gateways.
[C001] WARN  No symbol has a reference price (last_buy_price / last_sell_price).
[C003] INFO  enforce_collars is true but no symbol has an effective collar ...
[C004] INFO  enforce_circuit_breakers is true but no circuit breaker is configured ...
[C007] INFO  snapshot_interval_sec is at the default of 0.5 seconds.
[C009] INFO  sessions_enabled is false and no schedule is configured. ...

Verdict:  ⚠ 2 WARNINGS, 4 ADVISORIES — engine can start but review warnings
```

(The full report also prints each suggestion and a *Risk Summary*; they are cut
here for space.) Zero errors means the engine can start. The warnings and
advisories are the to-do list for the steps that follow — by Step 8 they are
all gone.

### `symbols`

A mapping from symbol name to its settings. A symbol with no settings may be
written as a bare key, as above.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `tick_decimals` | integer `0`–`8` | `2` | Number of decimal places in the symbol's prices. The tick size is `10^-tick_decimals`: at `2`, prices move in steps of `0.01`. |
| `last_buy_price`, `last_sell_price` | number | none | Opening reference prices. Added in [Step 2](#step-2-reference-data). |
| `outstanding_shares` | positive integer | none | Issued share count. Added in [Step 2](#step-2-reference-data). |
| `level` | name from `risk_controls.levels` | `risk_controls.default_level` | Collar profile. Added in [Step 4](#step-4-price-protection). |
| `collar` | mapping | none | Per-symbol collar override. [Step 4](#step-4-price-protection). |
| `circuit_breaker` | mapping | none | Per-symbol circuit-breaker override. [Step 4](#step-4-price-protection). |
| `order_limits` | mapping | none | Per-order size and value caps. [Step 4](#step-4-price-protection). |
| `market_maker_quotes` | list | none | Startup quotes. Required once a market maker exists. [Step 5](#step-5-market-makers-and-seeded-liquidity). |

The symbol universe is fixed when the engine starts. To list a new symbol, edit
the file, redeploy and restart — see
[Adding or Removing Symbols](010-the-configuration-workflow.md#adding-or-removing-symbols)
and [Listing a New Symbol](../part-4-run-a-market/010-new-symbols.md).

### `participants`

A list of the gateway IDs that may log in. Only an ID in this list can submit an
order; anything else is refused.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `id` | string, **required** | — | The gateway ID a client presents at login. Unique. No ID may be a prefix of another (`TRADER01` and `TRADER010` cannot coexist) — `pm-alf-gwy` and `pm-balf-gwy` refuse to start. |
| `description` | string | empty | Free-text label shown in tools. |
| `role` | `TRADER`, `MARKET_MAKER`, `ADMIN` | `TRADER` | What the participant may do (see below). |
| `disconnect_behaviour` | `CANCEL_QUOTES_ONLY`, `CANCEL_ALL`, `LEAVE_ALL` | `participant_defaults`, else `CANCEL_QUOTES_ONLY` | What the engine does with the participant's resting interest when it disconnects. |

The three roles:

| Role | Orders | Quotes | Circuit-breaker halt / resume | Typical user |
|---|:-:|:-:|:-:|---|
| `TRADER` | yes | no | no | Students, manual participants, AI traders |
| `MARKET_MAKER` | yes | yes | no | Liquidity providers |
| `ADMIN` | yes | no | yes | The operator or instructor console |

The three disconnect behaviours:

| Value | On disconnect the engine… |
|---|---|
| `CANCEL_QUOTES_ONLY` | cancels the participant's active quote legs; ordinary resting orders stay in the book. |
| `CANCEL_ALL` | cancels quotes **and** all resting orders. A student who closes the laptop leaves nothing behind. |
| `LEAVE_ALL` | cancels nothing. Use it for the operator console, whose connection should not disturb the book. |

The market-maker-only fields of a participant (`quote_refresh_policy`,
`smp_action`, `enforce_mm_obligation`, `mm_max_spread_ticks`, `mm_min_qty`,
`mm_obligations`) arrive in [Step 5](#step-5-market-makers-and-seeded-liquidity).

### `sessions_enabled`

| Value | Effect |
|---|---|
| `false` | The engine starts in `CONTINUOUS` and ignores scheduler transitions. |
| `true` (the default when a config file exists) | The engine starts `CLOSED`; `pm-scheduler` drives it through the trading day. |

## Step 2: reference data

A bare `AAPL:` gives the engine no idea what the stock costs, so collars,
circuit breakers and index calculations have nothing to anchor to. Step 2 lists
each symbol the way an **initial listing** would: its price grid, its opening
reference prices, and its issued shares. It also fills in the descriptions and
disconnect behaviour of the participants.

```yaml
symbols:
  AAPL:
    tick_decimals: 2
    last_buy_price: 209.50
    last_sell_price: 210.50
    outstanding_shares: 15400000000
  MSFT:
    tick_decimals: 2
    last_buy_price: 415.00
    last_sell_price: 415.50
    outstanding_shares: 7430000000
  TSLA:
    tick_decimals: 2
    last_buy_price: 248.00
    last_sell_price: 249.00
    outstanding_shares: 3200000000

participants:
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
```

| Field | Meaning |
|---|---|
| `tick_decimals: 2` | Prices have two decimals; the tick is `0.01`. Use `0` for whole-unit prices, `4` for a currency quoted to four places. |
| `last_buy_price`, `last_sell_price` | The opening bid-side and ask-side reference prices, in display money. They seed the book's last prices and the *reference* for collars and circuit breakers on the first order of day one. |
| `outstanding_shares` | Issued share count. Required for any symbol that is an index constituent ([Step 7](#step-7-a-market-index)); used for market capitalisation. |

!!! note "Persisted prices win"
    After a first trading day the engine writes `book_stats.json` to the data
    directory and, on the next start, restores the last prices from it. A
    restored price **replaces** `last_buy_price` / `last_sell_price` from the
    file. The values in the YAML only matter on the first start, or after you
    delete `book_stats.json`. See
    [Persistence](../part-6-observe-and-recover/010-persistence.md).

The collar reference is chosen in this order: persisted `last_buy_price`,
persisted `last_sell_price`, then the YAML `last_buy_price`, then the YAML
`last_sell_price`. A symbol with none of the four has no collar active at all.

## Step 3: the trading day

Until now the exchange was always open. Step 3 turns on **sessions**: the engine
starts `CLOSED`, and `pm-scheduler` moves it through the phases of the day at the
times you give.

```yaml
sessions_enabled: true

schedule:
  weekdays:
    pre_open: "09:00"
    opening_auction_start: "09:25"
    continuous_start: "09:30"
    closing_auction_start: "16:00"
    closing_auction_end: "16:05"

locale:
  country: Sweden
  session_timezone: Europe/Stockholm
```

The phases in order are:

```text
CLOSED → PRE_OPEN → OPENING_AUCTION → CONTINUOUS → CLOSING_AUCTION → CLOSED
```

### `schedule`

Each block you write must contain **all five** times; there is no per-key
fallback.

| Key | Meaning |
|---|---|
| `pre_open` | `PRE_OPEN`: orders are accepted and rest on the book; nothing executes. |
| `opening_auction_start` | `OPENING_AUCTION`: the opening call auction collects orders; nothing executes. |
| `continuous_start` | The opening auction uncrosses at one equilibrium price; `CONTINUOUS` matching begins. |
| `closing_auction_start` | Continuous matching ends; `CLOSING_AUCTION` collects orders. |
| `closing_auction_end` | The closing auction uncrosses; the exchange goes `CLOSED` and resting `DAY` orders expire. |

Times are `"HH:MM"` in the timezone given by `locale.session_timezone` (below) — **not** the clock of the machine the scheduler happens to run on.

The block names say which days a block applies to:

| Block | Applies to |
|---|---|
| `weekdays` | Monday–Friday, for any day not given its own block. |
| `mon` … `fri` | One weekday; overrides `weekdays` for that day. |
| `weekend` | Saturday and Sunday. Cannot be combined with `sat` / `sun`. |
| `sat`, `sun` | One weekend day. |
| `holidays` | Bank holidays of `locale.country`. |

A day with no block is `CLOSED` all day. See
[Session Scheduling and Auctions](../part-4-run-a-market/030-sessions-and-scheduling.md)
for worked examples, including how a closed day is skipped.

### `locale`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `country` | country name (`"Sweden"`) or ISO 3166-1 alpha-2 code (`"SE"`) | `Sweden` | Which country's bank-holiday calendar `pm-scheduler` uses to decide when `holidays` applies. An unrecognised value falls back to `Sweden` with a logged warning. |
| `session_timezone` | `UTC` or an IANA timezone name | `Europe/Stockholm` | Which calendar date a timestamp belongs to. `pm-stats` and `pm-clearing` use it to cut events into trading days. An unknown name is rejected. |

!!! warning "Do not change `session_timezone` on a running exchange"
    `pm-stats` and `pm-clearing` remember the timezone they first ran with and
    refuse to start if the configuration later disagrees, because re-cutting
    existing history would silently change figures already published.

## Step 4: price protection

Two independent mechanisms guard prices:

- A **collar** rejects an *incoming order* whose limit price is too far from a
  reference — a fat finger is stopped at the door.
- A **circuit breaker** *halts a symbol* when trades move the price too far, too
  fast, and reopens it through an auction.

The full behaviour is in [Risk Controls](../part-4-run-a-market/040-risk-controls.md).
Step 4 adds the global switches, named collar levels, the halt ladder, and
per-symbol exceptions.

```yaml
enforce_collars: true

enforce_circuit_breakers: true

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
  reference_window_ns: 300000000000     # 5 minutes
  levels:
    L1:
      price_shift_pct: 0.07
      halt_duration_ns: 300000000000    # 5 minutes
    L2:
      price_shift_pct: 0.13
      halt_duration_ns: 900000000000    # 15 minutes
    L3:
      price_shift_pct: 0.20
      halt_duration_ns:                 # null = halted for the rest of the day
  reopening:
    enabled: true
    initial_band_pct: 0.10
    random_end_max_ns: 30000000000      # up to 30 s of random extension
    random_seed:                        # null = seed from OS entropy
    expansions:
      - widen_pct: 0.10
        min_duration_ns: 120000000000
      - widen_pct: 0.20
        min_duration_ns: 300000000000

symbols:
  AAPL:
    tick_decimals: 2
    last_buy_price: 209.50
    last_sell_price: 210.50
    outstanding_shares: 15400000000
    order_limits:
      max_order_qty: 10000
      max_order_value: 2000000
    collar:
      dynamic_band_pct: 0.015
  MSFT:
    tick_decimals: 2
    level: L1
    last_buy_price: 415.00
    last_sell_price: 415.50
    outstanding_shares: 7430000000
  TSLA:
    tick_decimals: 2
    level: L3
    last_buy_price: 248.00
    last_sell_price: 249.00
    outstanding_shares: 3200000000
    circuit_breaker:
      reference_window_ns: 600000000000
      levels:
        L1:
          halt_duration_ns: 600000000000
        L2:
          halt_duration_ns: 1800000000000
      reopening:
        initial_band_pct: 0.15
```

!!! warning "Both mechanisms are opt-in per symbol"
    `enforce_collars: true` does nothing for a symbol that has no collar, and
    `enforce_circuit_breakers: true` does nothing for a symbol that has no
    circuit breaker. A symbol has a collar only if it gets one from its own
    `collar`, its `level`, or `risk_controls.default_level`. It has a circuit
    breaker only if `circuit_breaker_defaults` or its own `circuit_breaker`
    block exists. In Step 1's file neither exists, so no symbol was protected.

### The global switches

| Field | Default | Meaning |
|---|---|---|
| `enforce_collars` | `true` | Master switch for collar checks. Set `false` only for tests. |
| `enforce_circuit_breakers` | `true` | Master switch for halts. Set `false` only for tests. |

### `risk_controls`

Named, reusable collar profiles.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `default_level` | a key of `levels` | none | The level every symbol gets unless it names its own. Must exist in `levels`. |
| `levels.<NAME>.collar.static_band_pct` | number in `(0, 1)` | `0.20` | Allowed distance from the **reference price** (see Step 2). `0.20` allows prices within ±20 %. |
| `levels.<NAME>.collar.dynamic_band_pct` | number in `(0, 1)` | `0.02` | Allowed distance from the **latest trade price**. `0.02` allows ±2 % of the last fill. |

A level carries only a `collar`. Putting `order_limits` or `circuit_breaker` inside
a level is rejected with an error that names the right place.

### `circuit_breaker_defaults`

The exchange-wide halt ladder. A symbol's own `circuit_breaker` block is merged
over it, field by field.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `reference_window_ns` | integer ns | `300000000000` (5 min) | How far back the breaker looks for the price it measures the move against. |
| `levels.<NAME>.price_shift_pct` | number in `(0, 1)`, **required** | — | The move, as a fraction of the reference, that triggers this rung. Rungs are sorted by it, so name them as you like. Level names are limited to 32 characters. |
| `levels.<NAME>.halt_duration_ns` | positive integer ns, or `null` | `null` | The *minimum* length of the halt's reopening call phase (the random tail below is added on top). `null` means rest-of-day: the symbol never reopens on a timer — it stays halted until an `ADMIN` resumes it or the exchange closes for the day, when halts are reset. |

If a circuit-breaker block is present but has no `levels`, the built-in ladder
is used: L1 7 % / 5 min, L2 13 % / 15 min, L3 20 % / until resumed. If *no*
circuit-breaker block exists anywhere, the symbol has no breaker.

A halt is a **reopening auction**: orders keep arriving and resting, nothing
matches, and the halt ends with an uncross. The `reopening` block controls how
that auction ends:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `reopening.enabled` | boolean | `true` | `false` makes the reopening uncross at whatever price the auction finds, with no corridor. |
| `reopening.initial_band_pct` | number in `(0, 1)` | `0.10` | The corridor around the reference price within which the symbol may reopen. |
| `reopening.expansions` | non-empty list | two rungs, shown below | When the indicative price is outside the corridor, the call is extended and the corridor widened by one rung. The last rung repeats. *Exchange-wide only* — not allowed per symbol. |
| `reopening.expansions[].widen_pct` | number in `(0, 1)` | required | Added to the corridor half-width, as a fraction of the reference price. |
| `reopening.expansions[].min_duration_ns` | positive integer ns | required | Minimum length of that extended call. |
| `reopening.random_end_max_ns` | integer ns `>= 0` | `30000000000` (30 s) | Each call ends at a uniformly random moment within this tail after its minimum, so the uncross instant cannot be targeted. |
| `reopening.random_seed` | integer or `null` | `null` | Seed for that randomness. `null` draws from OS entropy; set an integer for reproducible demos. *Exchange-wide only.* |

The built-in expansions are `10 % / 2 min` then `20 % / 5 min`. A symbol may
override `reopening.enabled`, `initial_band_pct` and `random_end_max_ns`, but not
`expansions` or `random_seed`: those are venue policy, not instrument traits.

### Per-symbol exceptions

The step's `symbols` block shows each kind of exception:

| In the example | What it does |
|---|---|
| `MSFT: level: L1` | Uses the wide L1 collar instead of the default L2. |
| `TSLA: level: L3` | Uses the tight L3 collar. |
| `AAPL: collar: dynamic_band_pct: 0.015` | Overrides one collar field; `static_band_pct` still comes from the level. |
| `TSLA: circuit_breaker:` | Widens the reference window to 10 minutes, lengthens the L1 and L2 halts, and starts the reopening corridor at 15 %. L3 and everything else are inherited. |
| `AAPL: order_limits:` | Caps a single order. |

Precedence for a collar field, most specific first: the symbol's `collar`, the
symbol's `level`, `risk_controls.default_level`, then the built-in `0.20` /
`0.02`.

`order_limits` (symbol level only — there is no level or global default):

| Field | Type | Default | Meaning |
|---|---|---|---|
| `max_order_qty` | positive integer | none | Largest quantity one order may carry. Catches the extra-zero fat finger the collar cannot see. |
| `max_order_value` | positive number | none | Largest notional (`quantity × price`) in display money. Skipped for `MARKET` and `IOC` orders, which carry no price. |

An absent cap is not enforced.

## Step 5: market makers and seeded liquidity

An empty order book teaches little. A **market maker** posts a two-sided quote
and keeps the book alive. Step 5 adds two market-maker participants, seeds every
book with their opening quotes, sets the quality bar they must meet, and adds one
startup combo order.

```yaml
participant_defaults:
  disconnect_behaviour: CANCEL_QUOTES_ONLY
  smp_action: NONE

participants:
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
    smp_action: NONE
    enforce_mm_obligation: true
    mm_max_spread_ticks: 20
    mm_min_qty: 100
    mm_obligations:
      AAPL:
        enforce_mm_obligation: true
        max_spread_ticks: 10
        min_qty: 300
  - id: MM02
    description: Backup market maker
    role: MARKET_MAKER
    quote_refresh_policy: INACTIVATE_ON_FULL_FILL
  - id: OPS01
    description: Instructor console
    role: ADMIN
    disconnect_behaviour: LEAVE_ALL

mm_obligation_defaults:
  enforce_mm_obligation: true
  mm_max_spread_ticks: 20
  mm_min_qty: 100
  symbols:
    AAPL:
      mm_max_spread_ticks: 10
      mm_min_qty: 200

require_mm_seed_quotes: true

symbols:
  AAPL:
    # ... fields from Steps 2 and 4 unchanged ...
    market_maker_quotes:
      - gateway_id: MM01
        quote_id: SEED-MM01-AAPL
        bid_price: 209.45
        ask_price: 209.55
        bid_qty: 2000
        ask_qty: 2000
        tif: DAY
        seed_once: true
      - gateway_id: MM02
        quote_id: SEED-MM02-AAPL
        bid_price: 209.40
        ask_price: 209.50
        bid_qty: 1000
        ask_qty: 1000
  MSFT:
    # ... fields from Steps 2 and 4 unchanged ...
    market_maker_quotes:
      - gateway_id: MM01
        bid_price: 414.90
        ask_price: 415.10
        bid_qty: 1000
        ask_qty: 1000
  TSLA:
    # ... fields from Steps 2 and 4 unchanged ...
    market_maker_quotes:
      - gateway_id: MM01
        bid_price: 247.90
        ask_price: 248.10
        bid_qty: 500
        ask_qty: 500
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
        price: 209.30
        smp_action: NONE
      - symbol: MSFT
        side: SELL
        order_type: LIMIT
        quantity: 50
        price: 415.30
        smp_action: NONE
```

### The rule you will trip over first

As soon as one participant has `role: MARKET_MAKER`, **every symbol must have at
least one entry in `market_maker_quotes`**, or the config is rejected:

```text
Symbol 'MSFT': at least one market_maker_quotes entry is required when
MARKET_MAKER gateways are configured (set require_mm_seed_quotes: false to
allow an empty book)
```

Set `require_mm_seed_quotes: false` to allow market makers with empty books at
startup. The default is `true`.

### `participant_defaults`

Values a participant inherits when it omits them. Only these two keys are
accepted.

| Field | Default | Meaning |
|---|---|---|
| `disconnect_behaviour` | `CANCEL_QUOTES_ONLY` | Inherited by participants that do not set their own. |
| `smp_action` | `NONE` | Inherited self-match-prevention action (below). |

### More `participants` fields

| Field | Type | Default | Meaning |
|---|---|---|---|
| `quote_refresh_policy` | `INACTIVATE_ON_ANY_FILL`, `INACTIVATE_ON_FULL_FILL`, `NEVER_INACTIVATE` | `INACTIVATE_ON_ANY_FILL` | What a fill does to a two-sided quote. `ANY_FILL`: the other leg is cancelled after any fill and the quote is inactive until re-sent. `FULL_FILL`: only a completely filled leg does that. `NEVER_INACTIVATE`: the quote stays; a fill just reduces its quantity. |
| `smp_action` | `NONE`, `CANCEL_AGGRESSOR`, `CANCEL_RESTING`, `CANCEL_BOTH` | `participant_defaults`, else `NONE` | Self-match prevention for this participant's own orders: what to cancel when an order would trade against the same participant's resting order. It is a *fallback*: an explicit `SMP=` on an order always wins; quote legs always use this value. |
| `enforce_mm_obligation` | boolean | `mm_obligation_defaults`, else `false` | Whether this participant's quotes are checked against the quality bar. |
| `mm_max_spread_ticks` | positive integer | `mm_obligation_defaults`, else `20` | Widest allowed bid–ask spread, in ticks. |
| `mm_min_qty` | positive integer | `mm_obligation_defaults`, else `100` | Smallest allowed bid and ask quantity. |
| `mm_obligations.<SYMBOL>` | mapping | none | Per-symbol exception, with fields `enforce_mm_obligation`, `max_spread_ticks`, `min_qty`. Note the shorter names here: **no `mm_` prefix**. Unset fields fall back to the participant's flat fields. |

### `mm_obligation_defaults`

The quote-quality policy every market maker inherits.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `enforce_mm_obligation` | boolean | `false` | Master switch for the checks. |
| `mm_max_spread_ticks` | positive integer | `20` | Widest allowed spread, in ticks. |
| `mm_min_qty` | positive integer | `100` | Smallest allowed quantity on each side. |
| `symbols.<SYMBOL>` | mapping | none | Per-symbol override with the same three fields. The symbol must exist. |

For one participant and one symbol, the effective policy is taken from the most
specific source that sets it:

1. `participants[].mm_obligations.<SYMBOL>`
2. `mm_obligation_defaults.symbols.<SYMBOL>`
3. the participant's flat fields
4. `mm_obligation_defaults` flat fields
5. the built-in defaults

In the example, AAPL is held to 10 ticks by `mm_obligation_defaults.symbols`
and MM01 is further held to a 300-share minimum there; every other symbol uses
20 ticks and 100 shares.

!!! note "Make your seeds meet your own bar"
    A seed quote is a real quote. Keep each one inside its effective
    `mm_max_spread_ticks` and `mm_min_qty`; the spread in ticks is
    `(ask − bid) ÷ tick size`. `pm-cverifier` warns about a wide seed (`M003`),
    comparing it with the limit that applies to that gateway on that symbol.

### `symbols.<SYMBOL>.market_maker_quotes`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `gateway_id` | string, **required** | — | The `MARKET_MAKER` participant that owns the quote. |
| `quote_id` | string | generated (`SEED-<ID>-<SYMBOL>-<n>`) | An explicit label. |
| `bid_price`, `ask_price` | number, **required** | — | Display prices on the symbol's tick grid; `bid_price` must be below `ask_price`. |
| `bid_qty`, `ask_qty` | positive integer, **required** | — | Quantity on each side. |
| `tif` | `DAY`, `GTC` | `DAY` | Time in force. |
| `seed_once` | boolean | `true` | `true`: skip this seed if the gateway already has a live quote on the symbol restored from the previous run, so a restart does not replace it. A quote that was fully traded away or expired is not restored, so the seed fires again. `false`: always inject, replacing any restored quote. |

Live quote legs are saved with the resting orders and restored on restart; that is
why `seed_once` exists. See [Persistence](../part-6-observe-and-recover/010-persistence.md).

### `market_maker_combos`

Startup **combo** orders — several legs across symbols that fill all-or-nothing
(`AON`). Useful to show students that multi-leg interest exists.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `combo_id` | string, **required** | — | Unique label. |
| `combo_type` | `AON` | `AON` | The only type. |
| `tif` | `DAY`, `GTC`, `ATO`, `ATC` | `DAY` | Time in force. Prefer `DAY`: a `GTC` seed can duplicate itself against the restored `gtc_combos.json`. |
| `legs` | list of 2–10 | **required** | The legs; each symbol at most once, and each must exist in `symbols`. |
| `legs[].symbol` | string | required | |
| `legs[].side` | `BUY`, `SELL` | required | |
| `legs[].order_type` | `MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT`, `FOK`, `ICEBERG`, `IOC`, `TRAILING_STOP` | required | |
| `legs[].quantity` | integer | required | |
| `legs[].price`, `legs[].stop_price` | number | needed by priced / stop order types | **Display money**, validated on that leg's symbol's tick grid. |
| `legs[].smp_action` | as above | the seeding gateway's, else `NONE` | |

## Step 6: engine tuning

The defaults suit almost every deployment; change them when you have measured a
reason to.

```yaml
auction_indicative_interval_sec: 1.0

engine_tuning:
  snapshot_interval_sec: 0.5
  quote_history_maxlen: 30
  drop_copy_buffer_size: 10000
  recent_trades_maxlen: 20
  depth_snapshot_tolerance_ticks: 100
```

| Field | Type | Default | Meaning |
|---|---|---|---|
| `auction_indicative_interval_sec` | number `> 0` | `1.0` | Minimum time between republications of the indicative uncross price during a call phase (`PRE_OPEN`, `PRE_CLOSE`, or a halt). |
| `engine_tuning.snapshot_interval_sec` | number `> 0` | `0.5` | Minimum time between order-book snapshots for a symbol whose book changed. Lower: fresher viewers, more CPU and traffic. |
| `engine_tuning.quote_history_maxlen` | integer `> 0` | `30` | Inactivated quotes remembered per gateway for `QLEGS RECENT` / `ALL`. Memory-only. |
| `engine_tuning.drop_copy_buffer_size` | integer `> 0` | `10000` | Drop-copy events kept for replay when a subscriber reconnects. |
| `engine_tuning.recent_trades_maxlen` | integer `> 0` | `20` | Trades kept per symbol for snapshots and diagnostics. |
| `engine_tuning.depth_snapshot_tolerance_ticks` | integer `> 0` | `100` | How far from the last trade, in ticks, the published depth reaches. |

Note that `auction_indicative_interval_sec` is a top-level key, not part of
`engine_tuning`.

## Step 7: a market index

An **index** is a weighted average of constituent prices that `pm-index`
calculates as trades print.

```yaml
indices:
  - id: EDU100
    description: EduMatcher broad index
    base_value: 1000.0
    publish_interval_sec: 1.0
    constituents:
      - AAPL
      - MSFT
      - TSLA
```

| Field | Type | Default | Meaning |
|---|---|---|---|
| `id` | alphanumeric string, **required** | — | Unique index ID, up to five indices per file. |
| `description` | string, **required** | — | Human-readable label. |
| `base_value` | number `> 0` | `1000.0` | The index level at inception. |
| `publish_interval_sec` | number `> 0` | `1.0` | Minimum time between published updates. |
| `history_file` | path | `data/indexes/<ID>_history.jsonl` | Event history. A relative path is placed under the data directory. |
| `state_file` | path | `data/indexes/<ID>_state.json` | Checkpoint of the divisor and constituent shares. |
| `constituents` | non-empty list of symbols, **required** | — | Each must exist in `symbols` **and** have `outstanding_shares`. |

`pm-index` creates the history and state directories on start. Leave both paths
out unless you have a reason to move them. (`pm-cverifier` warns, `C013`, only
when a path you give is below a directory `pm-index` could not create.)

## Step 8: the access points

Everything so far configured the engine. The remaining blocks configure the
**processes that stand between the engine and the outside world**. Each is read
only by its own process, and each is optional — an absent block means every
default shown.

```yaml
alf_gateway:
  enabled: true
  name: alf-gwy01
  bind_address: 0.0.0.0
  port: 5565
  heartbeat_interval_sec: 5
  handshake_timeout_sec: 10
  idle_timeout_sec: 30
  max_connections: 1024
  max_client_queue: 10000
  max_commands_per_second: 100
  max_errors_before_disconnect: 50
  error_window_sec: 60

balf_gateway:
  enabled: true
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

market_data_gateway:
  enabled: true
  name: md-gwy01
  bind_address: 0.0.0.0
  port: 5570
  heartbeat_interval_sec: 1
  idle_timeout_sec: 5
  replay_window_sec: 30
  max_connections: 64
  max_messages_per_second: 200
  max_symbols_per_client: 200
  max_client_queue: 10000
  depth_levels: 10

post_trade_gateway:
  name: ralf-gwy01
  bind_address: 0.0.0.0
  port: 5580
  replay_retention_sec: 86400
  heartbeat_interval_sec: 2
  idle_timeout_sec: 20
  max_connections: 64
  max_client_queue: 10000
  allowed_roles:
    - CLEARING
    - DROP_COPY
    - AUDIT

dc_gateway:
  name: dc-gwy01
  bind_address: 0.0.0.0
  port: 5590
  heartbeat_interval_sec: 2
  idle_timeout_sec: 20
  max_connections: 64
  max_client_queue: 10000

api_gateways:
  desk:
    enabled: true
    host: 0.0.0.0
    port: 8080
    swagger_enabled: true
    log_level: info
    stats_db: data/stats.db
    audit_db: data/audit_index.db
    clearing_db: data/clearing.db
    order_retention_sec: 3600
    market_data_cache_sec: 60
    credentials:
      - api_key: REPLACE-WITH-A-SECRET-FOR-TRADER01
        gateway_id: TRADER01
        description: Key for TRADER01
      - api_key: REPLACE-WITH-A-SECRET-FOR-TRADER02
        gateway_id: TRADER02
        description: Key for TRADER02
      - api_key: REPLACE-WITH-A-SECRET-FOR-DASHBOARD
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

Fields that appear in several blocks mean the same thing wherever they appear:

| Field | Meaning |
|---|---|
| `enabled` | `false` makes the process log a warning and refuse to start. (`post_trade_gateway` and `dc_gateway` have no such switch — simply do not run the process.) |
| `name` | The gateway name reported to clients in the welcome / logon reply. |
| `bind_address` | The interface the listener binds. Use `127.0.0.1` for loopback only. |
| `port` | TCP port, `1`–`65535`. |
| `heartbeat_interval_sec` | How often the gateway sends a heartbeat on an otherwise quiet connection. |
| `idle_timeout_sec` | How long a client may stay silent before it is disconnected. |
| `max_connections` | Simultaneous connection cap. |
| `max_client_queue` | How many outbound messages may queue for one client that is not reading, before it is disconnected as a slow client. |

### `alf_gateway` — text order entry (`pm-alf-gwy`)

Who may log in, and as what role, comes from `participants`, not from this block.

| Field | Default | Meaning |
|---|---|---|
| `enabled`, `name`, `bind_address`, `port` | `true`, `alf-gwy01`, `0.0.0.0`, `5565` | As above. |
| `heartbeat_interval_sec` | `5` | Advertised to clients as `HBINT=`. |
| `handshake_timeout_sec` | `10` | Time a new connection has to complete `HELLO`. |
| `idle_timeout_sec` | `30` | Advertised to clients as `IDLE=`. |
| `max_connections` | `1024` | |
| `max_client_queue` | `10000` | |
| `max_commands_per_second` | `100` | Per-client command rate limit. |
| `max_errors_before_disconnect` | `50` | Protocol errors tolerated within `error_window_sec`. |
| `error_window_sec` | `60` | Length of the sliding error window. |

All values are integers greater than zero. See [ALF Gateway](../part-5-gateways/010-alf-gateway.md).

### `balf_gateway` — binary order entry (`pm-balf-gwy`)

| Field | Default | Meaning |
|---|---|---|
| `enabled`, `name`, `bind_address`, `port` | `true`, `balf-gwy01`, `0.0.0.0`, `5560` | As above. |
| `heartbeat_interval_sec` | `1` | Interval between server heartbeats on a quiet connection. |
| `heartbeat_timeout_sec` | `5` | Disconnect when nothing arrives within this time. This, not `idle_timeout_sec`, drives idle disconnects. |
| `idle_timeout_sec` | `30` | Accepted but not used by the runtime today; reserved. |
| `auth_timeout_sec` | `10` | Time to complete `LOGON` before the connection is closed. |
| `max_connections` | `64` | |
| `max_client_queue` | `10000` | |
| `max_messages_per_second` | `100` | Per-client inbound rate limit. |
| `max_errors_before_disconnect` | `10` | Errors tolerated within `error_window_sec`. |
| `error_window_sec` | `60` | |
| `duplicate_session_policy` | `REJECT_NEW` | A second `LOGON` for a gateway ID already connected: `REJECT_NEW` refuses the newcomer, `EVICT_OLD` drops the existing session. |

See [BALF Gateway](../part-5-gateways/020-balf-gateway.md).

### `market_data_gateway` — market data (`pm-md-gwy`, CALF)

| Field | Default | Meaning |
|---|---|---|
| `enabled`, `name`, `bind_address`, `port` | `true`, `md-gwy01`, `0.0.0.0`, `5570` | As above. |
| `heartbeat_interval_sec` | `1` | |
| `idle_timeout_sec` | `5` | |
| `replay_window_sec` | `30` | How much history is held for a client that reconnects and asks to resume. |
| `max_connections` | `64` | |
| `max_messages_per_second` | `200` | Per-client inbound rate limit. |
| `max_symbols_per_client` | `200` | Subscription cap per client. |
| `max_client_queue` | `10000` | |
| `depth_levels` | `10` | Aggregated price levels per side sent on the `DEPTH` channel. |

All values are integers greater than zero. See [Market Data Feed](../part-5-gateways/030-calf-gateway.md).

### `post_trade_gateway` — post-trade feed (`pm-ralf-gwy`, RALF)

| Field | Default | Meaning |
|---|---|---|
| `name`, `bind_address`, `port` | `ralf-gwy01`, `0.0.0.0`, `5580` | As above. |
| `replay_retention_sec` | `86400` | How long executed trades are held in memory for replay (24 h). |
| `heartbeat_interval_sec` | `2` | |
| `idle_timeout_sec` | `20` | |
| `max_connections` | `64` | |
| `max_client_queue` | `10000` | |
| `allowed_roles` | `CLEARING`, `DROP_COPY`, `AUDIT` | Which `HELLO ROLE=` values a subscriber may present. |

See [Post-Trade Dissemination](../part-5-gateways/040-ralf-gateway.md).

### `dc_gateway` — drop copy (`pm-dc-gwy`)

| Field | Default | Meaning |
|---|---|---|
| `name`, `bind_address`, `port` | `dc-gwy01`, `0.0.0.0`, `5590` | As above. |
| `heartbeat_interval_sec` | `2` | |
| `idle_timeout_sec` | `20` | |
| `max_connections` | `64` | |
| `max_client_queue` | `10000` | |

See [Drop-Copy Gateway](../part-5-gateways/060-drop-copy-gateway.md).

### `api_gateways` — REST and WebSocket (`pm-api-gwy`)

Unlike the others, `api_gateways` is a **mapping of named instances**. Each
instance is one `pm-api-gwy` process, started with `pm-api-gwy --instance <name>`;
the example defines one named `desk`. Several instances let you give different
audiences different keys on different ports.

| Field | Default | Meaning |
|---|---|---|
| `enabled` | `true` | |
| `host` | `0.0.0.0` | Listen interface. |
| `port` | `8080` | HTTP port. Give each instance its own. |
| `swagger_enabled` | `true` | Serve `/docs` and `/openapi.json`. |
| `log_level` | `info` | Log verbosity for the process. |
| `stats_db` | `data/stats.db` | `pm-stats` database, for history endpoints. |
| `audit_db` | `data/audit_index.db` | `pm-audit` index, used only by the order-audit endpoint (`503` if the file is absent). |
| `clearing_db` | `data/clearing.db` | `pm-clearing` ledger, used only for realised P&L on `GET /positions` (reported as `null` if absent). |
| `order_retention_sec` | `3600` | How long a finished order stays in the in-memory cache; `0` never evicts. |
| `market_data_cache_sec` | `60` | Lifetime of the per-symbol cache behind WebSocket snapshots and resume. |
| `credentials` | empty | The accepted API keys (below). |
| `credentials_file` | none | A file holding the keys instead (below). Not allowed together with `credentials`. |
| `rate_limit.writes_per_second` | `10` | Sustained write rate per key. |
| `rate_limit.burst` | `20` | Burst allowance per key. Reads are not limited. |
| `timeouts.engine_auth_sec` | `3.0` | Wait for the engine to accept the gateway's login. |
| `timeouts.engine_reply_sec` | `3.0` | Wait for an engine reply to a request. |
| `timeouts.wait_ack_sec` | `3.0` | Wait used by `?wait=ack`. |

Each entry of `credentials`:

| Field | Meaning |
|---|---|
| `api_key` | The bearer token a client sends. **Required.** Treat it as a password. |
| `gateway_id` | The `participants` ID the key trades as, or `null` for a **read-only** key. A given non-null ID may appear in only one instance. |
| `description` | Free-text label. |

Relative database paths are placed under the data directory.

**Keys in their own file.** With one key per participant the `credentials` list
grows as long as the participant list, and the keys are secrets that do not
belong in a file you keep under version control. Name a file instead:

```yaml
api_gateways:
  desk:
    port: 8080
    credentials_file: desk-keys.yaml
```

```yaml
# desk-keys.yaml -- a YAML list, one entry per key
- api_key: key-trader01-4ye7zh
  gateway_id: TRADER01
  description: Student desk 1
- api_key: key-dashboard-9fk2qa
  gateway_id: null
  description: Read-only dashboard
```

The path follows the same rules as `include:` (relative to the file that names
it, no absolute path, no `..`), and an instance may use `credentials` or
`credentials_file`, not both. Everything else treats the file as if its list had
been written inline: the verifier checks every key, a finding names the file
(`in desk-keys.yaml`), and `pm-config-deploy` compiles the keys into the
artifact, installs a copy of the file beside it and reports an edit you have not
deployed. Several instances may share one file. The file is not protected by
EduMatcher: keep it readable by the exchange's user only (`pm-config-gen`
creates it with mode `0600`).

!!! danger "Replace the example keys"
    The `REPLACE-WITH-…` values in the listing are placeholders that anyone who
    has read this book knows. Use long random strings, and keep the deployed
    config readable only by the exchange's own user.
    [`pm-config-gen`](010-the-configuration-workflow.md#generate-configs-with-pm-config-gen)
    can generate keys for you. Add at least one read-only key
    (`gateway_id: null`): without it `pm-cverifier` warns (`M032`) and
    `pm-dash`, the terminal GUI and the book GUI have nothing to read with.

See [API Gateway](../part-5-gateways/050-api-gateway.md).

## Step 9: operations — logging and health

The last two blocks are about **watching** the exchange.

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

monitor:
  enabled: true
  bind_address: 127.0.0.1
  host: 127.0.0.1
  pull_port: 5610
  pub_port: 5611
  beacon_interval_sec: 2
  hung_after_sec: 5
  silent_after_beacons: 3
  book_metrics_interval_sec: 10
  retention:
    raw_hours: 6
    minute_days: 7
  thresholds:
    host_cpu_pct:         {warn: 80,   crit: 95}
    host_mem_pct:         {warn: 80,   crit: 92}
    disk_free_pct:        {warn: 15,   crit: 5}
    engine_handle_p99_us: {warn: 5000, crit: 20000}
    reject_pct_5m:        {warn: 10,   crit: 30}
    rss_growth_pct_1h:    {warn: 50,   crit: 100}
    heap_bloat_ratio:     {warn: 1.5,  crit: 3}
```

### `log_server` — central log collector (`pm-log-srv`)

Every `pm-*` process sends its log lines to `pm-log-srv`, which stores them in
SQLite. The first group configures how logs come **in**.

| Field | Default | Meaning |
|---|---|---|
| `enabled`, `name`, `bind_address`, `port` | `true`, `log-srv01`, `0.0.0.0`, `5600` | As above. |
| `db_path` | `data/log.db` | The SQLite database. A relative path is placed under the data directory. |
| `retention_days` | `30` | Rows older than this are pruned hourly. `null` keeps everything. |
| `max_message_bytes` | `65536` | Longer messages are truncated, never dropped. |
| `max_client_queue` | `10000` | Per-connection backlog before backpressure. |
| `write_batch_size` | `50` | Most rows written per SQLite transaction. |
| `write_batch_interval_ms` | `100` | Longest wait before a partial batch is written. |
| `heartbeat_interval_sec` | `5` | How often a client must send something; the server disconnects after twice this much silence. |

The second group configures **LALF-PS**, the ZeroMQ interface that pushes live
rows to log viewers such as `pm-log-ui`:

| Field | Default | Meaning |
|---|---|---|
| `pubsub_enabled` | `true` | `false` binds no ZeroMQ socket; `pm-log-srv` is then a pure TCP collector. |
| `pub_port` | `5601` | ZeroMQ `PUB` port carrying live rows. |
| `pull_port` | `5602` | ZeroMQ `PULL` port receiving subscriber requests. |
| `lease_sec` | `30` | Lifetime of a subscription unless renewed. |
| `max_lease_sec` | `300` | Ceiling on a requested lease; larger requests are clamped. Must be `>= lease_sec`. |
| `max_subscribers` | `32` | Concurrent subscriptions. |
| `notify_interval_ms` | `250` | Coalescing window for notify-mode ticks. |
| `backfill_chunk_rows` | `500` | Rows per backfill chunk. |
| `max_backfill_minutes` | `1440` | Largest "last n minutes" window a viewer may ask for. |
| `max_backfill_rows` | `100000` | Hard cap on rows in one backfill. |
| `max_pending_rows` | `20000` | Per-subscriber stream buffer; a slow viewer loses its oldest rows. |
| `pub_sndhwm` | `10000` | ZeroMQ send high-water mark. |

`port`, `pub_port` and `pull_port` must all differ. See
[Centralized Log Server](../part-6-observe-and-recover/040-log-server.md).

### `monitor` — health beacons (`pm-monitor`)

Every process sends a small **beacon** to `pm-monitor`, which judges health and
publishes it to `pm-dash` and `pm-monitor-cli`. An absent block means these
defaults, with monitoring on.

| Field | Default | Meaning |
|---|---|---|
| `enabled` | `true` | `false`: no process sends beacons and `pm-monitor` idles. |
| `bind_address` | `127.0.0.1` | Interface `pm-monitor` binds. |
| `host` | `127.0.0.1` | Where processes send beacons and where `pm-monitor-cli` and the dashboard connect. Must be able to reach `bind_address`. |
| `pull_port` | `5610` | Beacons in. |
| `pub_port` | `5611` | Health snapshots and events out. |
| `beacon_interval_sec` | `2` | How often each process reports. |
| `hung_after_sec` | `5` | A process whose main loop is older than this is `HUNG`. Must exceed `beacon_interval_sec`. |
| `silent_after_beacons` | `3` | Missed beacons before a process is `SILENT` (alive) or `DEAD`. |
| `book_metrics_interval_sec` | `10` | How often the engine recomputes per-book figures. |
| `retention.raw_hours` | `6` | Hours of 10-second samples kept. |
| `retention.minute_days` | `7` | Days of one-minute buckets kept. Daily totals are kept indefinitely. |
| `thresholds.<rule>.warn` / `.crit` | see below | The levels at which a reading turns yellow / red. |

The seven threshold rules and their defaults:

| Rule | `warn` | `crit` | Reading |
|---|--:|--:|---|
| `host_cpu_pct` | 80 | 95 | Host CPU use, % |
| `host_mem_pct` | 80 | 92 | Host memory use, % |
| `disk_free_pct` | 15 | 5 | Free disk, % — **lower is worse**, so `warn` is above `crit` |
| `engine_handle_p99_us` | 5000 | 20000 | Engine message-handling 99th percentile, µs |
| `reject_pct_5m` | 10 | 30 | Order rejects over five minutes, % |
| `rss_growth_pct_1h` | 50 | 100 | Process memory growth over an hour, % |
| `heap_bloat_ratio` | 1.5 | 3 | Book heap size over the size compaction tolerates (1 = at the limit) |

A rule you leave out keeps its default. See
[Health Monitoring](../part-6-observe-and-recover/060-health-monitor.md).

## The complete file

This is Step 9's cumulative file in one piece — everything above, ready to copy,
edit and deploy. It has no errors, no warnings and no completeness advisories
beyond one informational note that `snapshot_interval_sec` is at its default.

```yaml
sessions_enabled: true

symbols:
  AAPL:
    tick_decimals: 2
    last_buy_price: 209.50
    last_sell_price: 210.50
    outstanding_shares: 15400000000
    order_limits:
      max_order_qty: 10000
      max_order_value: 2000000
    collar:
      dynamic_band_pct: 0.015
    market_maker_quotes:
      - gateway_id: MM01
        quote_id: SEED-MM01-AAPL
        bid_price: 209.45
        ask_price: 209.55
        bid_qty: 2000
        ask_qty: 2000
        tif: DAY
        seed_once: true
      - gateway_id: MM02
        quote_id: SEED-MM02-AAPL
        bid_price: 209.40
        ask_price: 209.50
        bid_qty: 1000
        ask_qty: 1000
  MSFT:
    tick_decimals: 2
    level: L1
    last_buy_price: 415.00
    last_sell_price: 415.50
    outstanding_shares: 7430000000
    market_maker_quotes:
      - gateway_id: MM01
        bid_price: 414.90
        ask_price: 415.10
        bid_qty: 1000
        ask_qty: 1000
  TSLA:
    tick_decimals: 2
    level: L3
    last_buy_price: 248.00
    last_sell_price: 249.00
    outstanding_shares: 3200000000
    circuit_breaker:
      reference_window_ns: 600000000000
      levels:
        L1:
          halt_duration_ns: 600000000000
        L2:
          halt_duration_ns: 1800000000000
      reopening:
        initial_band_pct: 0.15
    market_maker_quotes:
      - gateway_id: MM01
        bid_price: 247.90
        ask_price: 248.10
        bid_qty: 500
        ask_qty: 500
        seed_once: false

participants:
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
    smp_action: NONE
    enforce_mm_obligation: true
    mm_max_spread_ticks: 20
    mm_min_qty: 100
    mm_obligations:
      AAPL:
        enforce_mm_obligation: true
        max_spread_ticks: 10
        min_qty: 300
  - id: MM02
    description: Backup market maker
    role: MARKET_MAKER
    quote_refresh_policy: INACTIVATE_ON_FULL_FILL
  - id: OPS01
    description: Instructor console
    role: ADMIN
    disconnect_behaviour: LEAVE_ALL

schedule:
  weekdays:
    pre_open: "09:00"
    opening_auction_start: "09:25"
    continuous_start: "09:30"
    closing_auction_start: "16:00"
    closing_auction_end: "16:05"

locale:
  country: Sweden
  session_timezone: Europe/Stockholm

enforce_collars: true

enforce_circuit_breakers: true

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
  reference_window_ns: 300000000000     # 5 minutes
  levels:
    L1:
      price_shift_pct: 0.07
      halt_duration_ns: 300000000000    # 5 minutes
    L2:
      price_shift_pct: 0.13
      halt_duration_ns: 900000000000    # 15 minutes
    L3:
      price_shift_pct: 0.20
      halt_duration_ns:                 # null = halted for the rest of the day
  reopening:
    enabled: true
    initial_band_pct: 0.10
    random_end_max_ns: 30000000000      # up to 30 s of random extension
    random_seed:                        # null = seed from OS entropy
    expansions:
      - widen_pct: 0.10
        min_duration_ns: 120000000000
      - widen_pct: 0.20
        min_duration_ns: 300000000000

participant_defaults:
  disconnect_behaviour: CANCEL_QUOTES_ONLY
  smp_action: NONE

mm_obligation_defaults:
  enforce_mm_obligation: true
  mm_max_spread_ticks: 20
  mm_min_qty: 100
  symbols:
    AAPL:
      mm_max_spread_ticks: 10
      mm_min_qty: 200

require_mm_seed_quotes: true

market_maker_combos:
  - combo_id: SEED-PAIR-AAPL-MSFT
    combo_type: AON
    tif: DAY
    legs:
      - symbol: AAPL
        side: BUY
        order_type: LIMIT
        quantity: 100
        price: 209.30
        smp_action: NONE
      - symbol: MSFT
        side: SELL
        order_type: LIMIT
        quantity: 50
        price: 415.30
        smp_action: NONE

auction_indicative_interval_sec: 1.0

engine_tuning:
  snapshot_interval_sec: 0.5
  quote_history_maxlen: 30
  drop_copy_buffer_size: 10000
  recent_trades_maxlen: 20
  depth_snapshot_tolerance_ticks: 100

indices:
  - id: EDU100
    description: EduMatcher broad index
    base_value: 1000.0
    publish_interval_sec: 1.0
    constituents:
      - AAPL
      - MSFT
      - TSLA

alf_gateway:
  enabled: true
  name: alf-gwy01
  bind_address: 0.0.0.0
  port: 5565
  heartbeat_interval_sec: 5
  handshake_timeout_sec: 10
  idle_timeout_sec: 30
  max_connections: 1024
  max_client_queue: 10000
  max_commands_per_second: 100
  max_errors_before_disconnect: 50
  error_window_sec: 60

balf_gateway:
  enabled: true
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

market_data_gateway:
  enabled: true
  name: md-gwy01
  bind_address: 0.0.0.0
  port: 5570
  heartbeat_interval_sec: 1
  idle_timeout_sec: 5
  replay_window_sec: 30
  max_connections: 64
  max_messages_per_second: 200
  max_symbols_per_client: 200
  max_client_queue: 10000
  depth_levels: 10

post_trade_gateway:
  name: ralf-gwy01
  bind_address: 0.0.0.0
  port: 5580
  replay_retention_sec: 86400
  heartbeat_interval_sec: 2
  idle_timeout_sec: 20
  max_connections: 64
  max_client_queue: 10000
  allowed_roles:
    - CLEARING
    - DROP_COPY
    - AUDIT

dc_gateway:
  name: dc-gwy01
  bind_address: 0.0.0.0
  port: 5590
  heartbeat_interval_sec: 2
  idle_timeout_sec: 20
  max_connections: 64
  max_client_queue: 10000

api_gateways:
  desk:
    enabled: true
    host: 0.0.0.0
    port: 8080
    swagger_enabled: true
    log_level: info
    stats_db: data/stats.db
    audit_db: data/audit_index.db
    clearing_db: data/clearing.db
    order_retention_sec: 3600
    market_data_cache_sec: 60
    credentials:
      - api_key: REPLACE-WITH-A-SECRET-FOR-TRADER01
        gateway_id: TRADER01
        description: Key for TRADER01
      - api_key: REPLACE-WITH-A-SECRET-FOR-TRADER02
        gateway_id: TRADER02
        description: Key for TRADER02
      - api_key: REPLACE-WITH-A-SECRET-FOR-DASHBOARD
        gateway_id: null
        description: Read-only dashboard client
    rate_limit:
      writes_per_second: 10
      burst: 20
    timeouts:
      engine_auth_sec: 3.0
      engine_reply_sec: 3.0
      wait_ack_sec: 3.0

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

monitor:
  enabled: true
  bind_address: 127.0.0.1
  host: 127.0.0.1
  pull_port: 5610
  pub_port: 5611
  beacon_interval_sec: 2
  hung_after_sec: 5
  silent_after_beacons: 3
  book_metrics_interval_sec: 10
  retention:
    raw_hours: 6
    minute_days: 7
  thresholds:
    host_cpu_pct:         {warn: 80,   crit: 95}
    host_mem_pct:         {warn: 80,   crit: 92}
    disk_free_pct:        {warn: 15,   crit: 5}
    engine_handle_p99_us: {warn: 5000, crit: 20000}
    reject_pct_5m:        {warn: 10,   crit: 30}
    rss_growth_pct_1h:    {warn: 50,   crit: 100}
    heap_bloat_ratio:     {warn: 1.5,  crit: 3}
```

Verify, deploy and inspect it:

```bash
pm-cverifier engine_config.yaml
pm-config-deploy engine_config.yaml
pm-config-show
```

```text
pm-cverifier engine_config.yaml

✓ YAML syntax: OK
✓ Schema: 0 errors
✓ Semantic: 0 warnings
i Completeness: 1 advisory

[C007] INFO  snapshot_interval_sec is at the default of 0.5 seconds.

Symbols          3  (AAPL, MSFT, TSLA)
Gateways         5  (TRADER01: TRADER, TRADER02: TRADER, MM01: MARKET_MAKER, MM02: MARKET_MAKER … +1 more)
Sessions         enabled — 5 of 7 days scheduled
Collars          enabled — L1: static=30%, dynamic=5%; L2: static=20%, dynamic=2%; L3: static=12%, dynamic=1%
Order limits     AAPL: max qty 10000, max value 2000000
Circuit breakers enabled — L1=7% (5 min), L2=13% (15 min), L3=20% (rest-of-day)
MM obligations   enforced
Admin gateway    OPS01
Indices          1  (EDU100)

Verdict:  ✓ OK — no issues found
```

(Advisory suggestions and rule lines are shortened here.) Starting `pm-engine`
on the deployed file logs the seeds going in:

```text
Session handling: enabled (startup state: CLOSED)
Risk enforcement: collars=on, circuit_breakers=on
MM quote SEED-MM01-AAPL AAPL bid=209.45x2000 ask=209.55x2000 gw=MM01
MM quote SEED-MM02-AAPL AAPL bid=209.4x1000 ask=209.5x1000 gw=MM02
MM quote SEED-MM01-MSFT-1 MSFT bid=414.9x1000 ask=415.1x1000 gw=MM01
MM quote SEED-MM01-TSLA-1 TSLA bid=247.9x500 ask=248.1x500 gw=MM01
COMBO SEED-PAIR-AAPL-MSFT accepted (2 legs) from MM
Injected 4 market-maker quote(s) and 1 combo(s).
```

## Ports at a glance

Every listener has its own port. The configurable ones come from the blocks above;
the others are fixed or set through environment variables and appear nowhere in
`engine_config.yaml`.

| Port | Protocol | Process | Purpose | Set by |
|--:|---|---|---|---|
| 5553 | ZMQ PUB | `pm-market-sim` | True values and heartbeat | `EDUMATCHER_SIM_PUB_PORT` |
| 5554 | ZMQ PULL | `pm-market-sim` | Instructor commands | `EDUMATCHER_SIM_PULL_PORT` |
| 5555 | ZMQ PULL | `pm-engine` | Order intake | fixed |
| 5556 | ZMQ PUB | `pm-engine` | Event and book feed | fixed |
| 5557 | ZMQ PUB | `pm-engine` | Drop-copy feed | fixed |
| 5558 | ZMQ PUB | `pm-index` | Index values | `EDUMATCHER_INDEX_PUB_PORT` |
| 5559 | ZMQ PULL | `pm-index` | Index commands | `EDUMATCHER_INDEX_PULL_PORT` |
| 5560 | TCP | `pm-balf-gwy` | Binary order entry | `balf_gateway.port` |
| 5561 | ZMQ REP | `pm-stats` | Health ping | `EDUMATCHER_STATS_HEALTH_PORT` |
| 5562 | ZMQ REP | `pm-audit` | Health ping | `EDUMATCHER_AUDIT_HEALTH_PORT` |
| 5563 | ZMQ REP | `pm-clearing` | Health ping | `EDUMATCHER_CLEARING_HEALTH_PORT` |
| 5564 | ZMQ REP | `pm-index` | Health ping | `EDUMATCHER_INDEX_HEALTH_PORT` |
| 5565 | TCP | `pm-alf-gwy` | Text order entry | `alf_gateway.port` |
| 5570 | TCP | `pm-md-gwy` | Market data | `market_data_gateway.port` |
| 5580 | TCP | `pm-ralf-gwy` | Post-trade feed | `post_trade_gateway.port` |
| 5590 | TCP | `pm-dc-gwy` | Drop copy | `dc_gateway.port` |
| 5600 | TCP | `pm-log-srv` | Log ingest | `log_server.port` |
| 5601 | ZMQ PUB | `pm-log-srv` | Live log feed | `log_server.pub_port` |
| 5602 | ZMQ PULL | `pm-log-srv` | Log subscriber control | `log_server.pull_port` |
| 5610 | ZMQ PULL | `pm-monitor` | Health beacons in | `monitor.pull_port` |
| 5611 | ZMQ PUB | `pm-monitor` | Health feed out | `monitor.pub_port` |
| 8080 | HTTP | `pm-api-gwy` | REST / WebSocket | `api_gateways.<name>.port` |

The engine's own sockets (5555–5557) bind `127.0.0.1` unless
`EDUMATCHER_ENGINE_BIND_HOST` says otherwise, and are not configurable in the file.

## Where to go next

- [The Configuration Workflow](010-the-configuration-workflow.md) — generate,
  verify, deploy and inspect the file.
- [Config Verifier](020-config-verifier.md) — every check code `pm-cverifier` can raise.
- [Configuration Schema and Process Blocks](../../reference-manual/part-3-configuration/010-schema-and-process-blocks.md)
  and the [Engine Configuration Specification](../../reference-manual/part-3-configuration/030-formal-specification.md)
  — the exhaustive reference and grammar.
- [Example Engine Configs](040-example-configs.md) — ready-made files for classes
  of different sizes.

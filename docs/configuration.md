# Engine Configuration

The matching engine and session scheduler both consume the YAML configuration
file in the project root. It defines:

- the allowed FIX gateways
- the traded symbol universe
- optional seeded last-buy / last-sell statistics
- optional startup market-maker single-leg orders
- optional startup market-maker combo orders
- optional daily session schedule for `pm-scheduler`

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
- no FIX gateway allowlist
- no seeded market statistics
- no startup market-maker orders
- no startup market-maker combos

The scheduler behaves differently: if its config file is missing or does not
contain a `schedule` section, it falls back to built-in default session times.

## Top-level Structure

The full supported schema is:

```yaml
gateways:
  fix:
    - id: TRADER01
      description: Human trader workstation

symbols:
  AAPL:
    last_buy_price: 209.50
    last_sell_price: 210.50
    market_maker_orders:
      - "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=2000|PRICE=209.00|TIF=DAY"

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

### Required vs optional top-level keys

| Key | Required when config file exists? | Used by |
|---|---|---|
| `gateways` | Yes | Engine |
| `gateways.fix` | Yes | Engine |
| `symbols` | Yes | Engine |
| `market_maker_combos` | No | Engine |
| `schedule` | No | Scheduler |

If a config file exists, `symbols` must be a mapping and `gateways.fix` must be
a list. Otherwise config loading fails and the engine exits.

## Gateway Allowlist

Only FIX gateway IDs listed under `gateways.fix` may connect and submit orders.

```yaml
gateways:
  fix:
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

### Runtime effect

Gateway startup flow:

1. Gateway sends `system.gateway_connect`
2. Engine checks the configured allowlist
3. Engine replies on `system.gateway_auth.<GW_ID>`
4. Rejected gateways cannot place orders

Direct orders from an unauthorized gateway are rejected with reason:

```text
Gateway not configured: <GW_ID>
```

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
| `last_buy_price` | number | No | Seed value for the viewer’s Last Buy field. |
| `last_sell_price` | number | No | Seed value for the viewer’s Last Sell field. |
| `market_maker_orders` | list of strings | No | FIX-like order definitions injected at engine startup. |

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

### `market_maker_orders`

```yaml
symbols:
  MSFT:
    market_maker_orders:
      - "NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=1000|PRICE=414.00|TIF=DAY"
      - "NEW|SYM=MSFT|SIDE=SELL|TYPE=LIMIT|QTY=1000|PRICE=416.00|TIF=DAY"
```

These orders are parsed and injected at engine startup using internal
`gateway_id = "MM"`.

#### Validation rules

- `market_maker_orders` must be a list
- every element must be a string
- every string must start with `NEW|`

#### Supported FIX-like fields

| Field | Required | Description |
|---|---|---|
| `SYM=` | Yes | Target symbol. In practice this should match the enclosing symbol block. |
| `SIDE=` | Yes | `BUY` or `SELL` |
| `TYPE=` | Yes | `MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT`, `FOK`, `ICEBERG` |
| `QTY=` | Yes | Total quantity |
| `PRICE=` | Conditional | Required for `LIMIT`, `STOP_LIMIT`, `FOK`, `ICEBERG` |
| `STOP=` | Conditional | Required for `STOP`, `STOP_LIMIT` |
| `TIF=` | No | Defaults to `DAY`; can be `DAY`, `GTC`, or any other order TIF supported by the order model |
| `VISIBLE=` | Conditional | Required for `ICEBERG` |
| `SMP=` | No | Self-match prevention action; defaults to `NONE` |

#### Persistence interaction

| TIF | Behavior |
|---|---|
| `DAY` | Removed at shutdown and re-injected cleanly on next startup. |
| `GTC` | Persisted to `data/gtc_orders.json` and also re-injected from config on next startup, which can create duplicates. |

!!! warning
    `GTC` market-maker orders are usually the wrong choice for seeded books.
    Because they are both persisted and re-injected from config, they will be
    duplicated across restarts unless you explicitly clear persisted state.

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
- if the config file is missing or `schedule` is absent, the scheduler uses its built-in default schedule

The default session path is:

```text
PRE_OPEN -> OPENING_AUCTION -> CONTINUOUS -> CLOSING_AUCTION -> CLOSED
```

### Important distinction

The engine itself still starts in `CONTINUOUS` mode by default for backward
compatibility. The `schedule` section only has an effect if you actually run
`pm-scheduler`.

## Startup and Persistence Order

The effective startup sequence is:

```text
Engine startup
    |
    +-- 1. Load config if present
    |       +-- establish symbol allowlist
    |       +-- establish FIX gateway allowlist
    |
    +-- 2. Restore persisted GTC orders from data/gtc_orders.json
    +-- 3. Restore persisted GTC combos from data/gtc_combos.json
    +-- 4. Load persisted book stats from data/book_stats.json
    |       +-- use config last_buy_price / last_sell_price only where stats are missing
    +-- 5. Inject market_maker_orders
    +-- 6. Inject market_maker_combos
    +-- 7. Publish initial book snapshots
```

This ordering matters:

- persisted GTC state comes back before seeded startup liquidity
- persisted book stats override config seeds
- seeded GTC orders or combos can duplicate restored GTC state

## Full Example

```yaml
gateways:
  fix:
    - id: TRADER01
      description: The first trader
    - id: TRADER02
      description: High frequency

symbols:
  MSFT:
    last_buy_price: 415.00
    last_sell_price: 415.50
    market_maker_orders:
      - "NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=1000|PRICE=414.00|TIF=DAY"
      - "NEW|SYM=MSFT|SIDE=SELL|TYPE=LIMIT|QTY=1000|PRICE=416.00|TIF=DAY"

  AAPL:
    last_buy_price: 209.50
    last_sell_price: 210.50
    market_maker_orders:
      - "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=2000|PRICE=209.00|TIF=DAY"
      - "NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=2000|PRICE=211.00|TIF=DAY"

  TSLA:
    last_buy_price: 248.00
    last_sell_price: 249.00
    market_maker_orders:
      - "NEW|SYM=TSLA|SIDE=BUY|TYPE=LIMIT|QTY=500|PRICE=247.00|TIF=DAY"
      - "NEW|SYM=TSLA|SIDE=SELL|TYPE=LIMIT|QTY=500|PRICE=250.00|TIF=DAY"

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

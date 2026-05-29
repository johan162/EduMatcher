# MM Quotes

!!! note "Learning objectives"
    After reading this page you will understand:

    - What a two-sided market-maker quote is and how it differs from single orders
    - How EduMatcher represents one quote as two linked orders on the same symbol
    - How quote lifecycle events work: active, inactive-on-fill, cancelled
    - How gateway disconnect policy and kill-switch controls interact with quotes
    - How to submit, replace, and cancel quotes from the gateway CLI
    - Why startup seeding and gateway connectivity are independent events
    - What happens when a fill occurs against a seed quote before the MM gateway connects
    - Why no circuit breaker fires in that scenario (and what does happen instead)

---

## Concept

A market-maker quote is a coordinated bid/ask pair for one symbol:

- Bid leg: willingness to buy at bid price
- Ask leg: willingness to sell at ask price
- Shared quote ID: lets the engine manage the pair as one logical quote

EduMatcher keeps matching logic simple by posting both quote legs as regular
limit orders. Each order stores:

- `origin=QUOTE`
- `quote_id=<shared-id>`

This means price-time matching stays unchanged while quote controls are handled
in engine orchestration.

## Startup Quote Seeding

On every engine startup, `_load_config()` reads each symbol's
`market_maker_quotes` list and posts the defined bid/ask pairs into the order
book before any gateway connection is accepted.  This gives every book a
guaranteed spread from the first moment of the trading day.

Each seeded quote entry defines:

- `gateway_id` (must be a configured `MARKET_MAKER` gateway)
- `bid_price`, `ask_price`
- `bid_qty`, `ask_qty`
- optional `tif` (default `DAY`), optional `quote_id`

If at least one `MARKET_MAKER` gateway is configured, the engine **requires**
each symbol to define at least one quote seed — the config loader rejects the
file otherwise.

### Exact startup sequence

```
1.  Engine binds ZeroMQ sockets (no gateways connected yet)
2.  Restore data/book_stats.json  → last_buy_price / last_sell_price per symbol
3.  Restore data/gtc_orders.json  → re-inject GTC orders with original timestamps
4.  Restore data/gtc_combos.json  → rebuild parent-child combo maps
5.  Inject market_maker_quotes    → one quote (bid + ask) per configured entry
        • quote legs posted with origin=QUOTE, quote_id=<configured or generated>
        • matching is enabled — a GTC resting order could cross a seed quote here
        • trades and fill messages are published immediately
6.  Inject market_maker_combos    → seeded combo orders at top level
7.  Publish initial book snapshots for all symbols
8.  Begin accepting gateway connections
```

For a clean first run, clear persisted files so no stale state competes with
your seeds:

```bash
rm -f data/gtc_orders.json data/book_stats.json data/gtc_combos.json
poetry run pm-engine --verbose
```

The engine will print one line per injected quote:

```
[ENGINE] MM quote SEED-MM01-AAPL-1 AAPL bid=209.00x2000 ask=211.00x2000 gw=MM01
[ENGINE] Injected 3 market-maker quote(s) and 0 combo(s).
```

### `gateway_id` is an accounting identity, not a connectivity check

The `gateway_id` field in a seed quote serves two purposes:

1. It records which market maker *owns* the quote (for fill reporting, kill-switch scope, and disconnect cleanup).
2. It must match a configured `MARKET_MAKER` FIX gateway — this is validated at load time.

**It does not require that gateway to be connected.**  `_load_config()` bypasses
the normal `_gateway_status()` connectivity check.  Seed quotes enter the book
the moment the engine starts, before any participant has dialled in.

This is intentional: the seeds represent the MM's *agreed opening liquidity*,
not a live quote submission.

## Fills Against Seed Quotes Before the MM Connects

Because seed quotes are live in the book before the MM gateway connects, it is
possible for another participant's aggressive order to cross a seed quote during
continuous session before the MM has dialled in.

### What actually happens

| Step | Event |
|------|-------|
| 1 | Engine injects seed quote `MM-AAPL-1` for MM01 (MM01 not yet connected) |
| 2 | Session transitions to continuous (e.g. via scheduler or manual command) |
| 3 | TRADER01 submits a MARKET or aggressive LIMIT that crosses the seed bid or ask |
| 4 | Normal price-time matching fires — a **trade executes** |
| 5 | `_on_quote_leg_filled` is called for the filled leg |
| 6 | Based on `quote_refresh_policy` for MM01's gateway config: |
|   | &nbsp;• `INACTIVATE_ON_ANY_FILL` (default): sibling leg cancelled, quote removed from QuoteIndex, `INACTIVE_*` status published to PUB socket |
|   | &nbsp;• `INACTIVATE_ON_FULL_FILL`: only cancels if the leg was fully filled |
|   | &nbsp;• `NEVER_INACTIVATE`: both legs stay in the book, fill reduces remaining quantity |
| 7 | The `INACTIVE_*` status message is sent to `quote.status.MM01` on the PUB socket — but MM01 is not connected and has no subscriber, so the message is **silently dropped** |
| 8 | Book continues in continuous session with reduced or no MM liquidity |

### No circuit breaker fires

The circuit breaker is a **planned future feature** and is not implemented in
the current codebase.  There is no `circuit_breaker.py`, no `HALTED` session
state, and no per-symbol halt mechanism.  A fill against an unattended seed
quote does **not** trigger any halt or rejection of subsequent orders.

The book simply becomes thin.  All other participants can continue to submit
and match orders normally.

### What the MM must do on connect

When MM01 eventually connects, the engine does **not** automatically re-quote.
The seeded quote may be:

- **Still active** — if no one crossed it.  The MM can leave it or replace it
  by submitting a fresh `QUOTE` message (which cancels-and-replaces).
- **Partially filled** — sibling still resting with reduced quantity (only under
  `NEVER_INACTIVATE`).  The MM should inspect its book state and re-quote.
- **Inactive / gone** — consumed by the inactivation policy.  The book has no
  MM quote for this symbol.  The MM **must** re-quote immediately.

The MM gateway should query book state on connect and submit a fresh quote for
every symbol where no active quote exists:

```text
QUOTE|SYM=AAPL|BID=209.80|ASK=210.20|BID_QTY=2000|ASK_QTY=2000|TIF=DAY
```

If the seed is still active this replace-and-cancel is safe — the existing
quote is cancelled and the new one is registered atomically.

## Gateway Commands

Submit or replace a quote:

```text
QUOTE|SYM=AAPL|BID=209.80|ASK=210.20|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=MM-AAPL-1
```

Cancel active quote for one symbol:

```text
QUOTE_CANCEL|SYM=AAPL
```

Trigger kill-switch for your gateway (optional symbol scope):

```text
KILL
KILL|SYM=AAPL
```

## Message Flow

Gateway to engine:

- `quote.new`
- `quote.cancel`
- `risk.kill_switch`
- `system.gateway_disconnect`

Engine to gateway:

- `quote.ack.<GW_ID>`
- `quote.status.<GW_ID>`
- `risk.kill_switch_ack.<GW_ID>`

Quote status values used by the engine:

- `ACTIVE`
- `INACTIVE_BID_FILLED`
- `INACTIVE_ASK_FILLED`
- `CANCELLED`

## Refresh Policies

Each gateway can define quote refresh behavior in [configuration.md](configuration.md):

- `INACTIVATE_ON_ANY_FILL`: any fill on one leg inactivates the quote
- `INACTIVATE_ON_FULL_FILL`: only full fill inactivates the quote
- `NEVER_INACTIVATE`: quote is not auto-inactivated by fills

When inactivation is triggered, the engine cancels the opposite leg and emits
`quote.status.<GW_ID>`.

MM obligation enforcement is optional and configured per gateway:

- `enforce_mm_obligation: false` (default): quote spread/size checks are skipped
- `enforce_mm_obligation: true`: engine enforces:
    - `mm_max_spread_ticks`
    - `mm_min_qty`

## Disconnect And Risk Controls

Gateway disconnect behavior is configurable per gateway:

- `CANCEL_QUOTES_ONLY` (default for MM gateways): on disconnect, all active
  quote legs for that gateway are cancelled.  Regular resting orders are left.
- `CANCEL_ALL`: on disconnect, quotes **and** all resting non-quote orders are
  cancelled.
- `LEAVE_ALL`: disconnect is recorded but nothing is cancelled.  Quotes and
  orders remain in the book unchanged.

`KILL` is an immediate risk control that cancels:

- Active quote legs
- Non-quote resting orders (optionally scoped to a single symbol)

The acknowledgement message includes cancellation totals so the gateway can
confirm action scope.

!!! warning "Seed quotes and disconnect"
    If the MM gateway was never connected in the first place, `_handle_gateway_disconnect`
    is never called and the seed quotes are **not** auto-cancelled on any disconnect
    event.  Only an explicit gateway disconnect message (or a `KILL` command from
    an admin gateway) would remove them.

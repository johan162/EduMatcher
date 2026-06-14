# Persistence — Data Across Trading Sessions

!!! note "Learning objectives"
    After reading this page you will understand:

    - Which data files survive an engine restart and what each one contains
    - How GTC orders preserve their price-time priority across sessions
    - The exact shutdown and startup sequence that keeps the order book consistent
    - How book statistics allow stop orders to trigger correctly on the first trade of a new day
    - How to safely inspect, edit, or delete persistence files between sessions

EduMatcher models a real exchange behaviour: **Good-Till-Cancelled (GTC)** orders
survive the end of a trading session and are automatically restored when the system
restarts for the next day.  Several other data files are also maintained across
sessions to preserve market state and historical records.



## How It Works

### At Shutdown (Ctrl-C on the engine)

1. The engine collects all **resting** orders (status `NEW` or `PARTIAL`) from every order book.
2. Orders with `TIF = DAY` receive an `order.expired.<GW_ID>` event and are discarded.
3. DAY combo children that expire trigger cascade-cancel of their parent combo.
4. Orders with `TIF = GTC` are serialized to `data/gtc_orders.json`.
5. GTC combos (status `PENDING` or `PARTIALLY_MATCHED`) are serialized to `data/gtc_combos.json`.
6. Book statistics (`last_buy_price`, `last_sell_price` per symbol) are saved to `data/book_stats.json`.
7. A `system.eod` message is published with final book snapshots for all symbols (allows stats/viewers to record closing state).
8. ZMQ sockets are closed.

### At Startup

1. The engine reads `data/gtc_orders.json` (if it exists).
2. Each GTC order is re-injected into its symbol's order book **with its original timestamp preserved**.
3. The engine reads `data/gtc_combos.json` (if it exists) and rebuilds parent-child tracking maps.
4. If any GTC orders were restored, initial book snapshots are published.
5. The engine reads `data/book_stats.json` (if it exists) and restores `last_buy_price` / `last_sell_price` per symbol.  Persisted values take priority over config-seeded values.
6. Market-maker quotes from each symbol's `market_maker_quotes` config section are injected as linked bid/ask quote legs.  **No gateway connection is required** — seeds enter the book before any participant dials in.  If a restored GTC order already crosses a seed price, a trade executes immediately during this step.
7. Market-maker combos from the `market_maker_combos` config section are injected.
8. Book snapshots are published for any symbol where MM quotes were injected.
9. Original timestamps ensure that price-time priority carries over correctly — an order
   submitted yesterday still has seniority over a new order at the same price submitted today.



## Operational edge cases

- If `data/gtc_orders.json`, `data/gtc_combos.json`, or `data/book_stats.json`
  is malformed JSON, startup does **not** fail. The loader returns empty state
  for that file and the engine continues.
- Restored GTC orders for symbols that no longer exist in the current config are
  skipped during restore rather than aborting startup.
- Because config quote seeds run **after** persisted GTC restore, seeded `GTC`
  liquidity can duplicate already-restored inventory on restart. Use `DAY` for
  seeded demo liquidity unless you are intentionally managing persisted state.



## Order ID Stability

GTC order IDs are UUID4 strings generated at submission time by the gateway.
They **do not change** across restarts. Gateways and the order monitor will see
the same order ID in all events throughout the order's life.



## Submitting a GTC Order

Add `TIF=GTC` to any LIMIT, STOP, STOP_LIMIT, or ICEBERG order:

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=148.00|TIF=GTC
NEW|SYM=AAPL|SIDE=BUY|TYPE=ICEBERG|QTY=1000|PRICE=149.00|VISIBLE=100|TIF=GTC
```

MARKET, FOK, and IOC orders are always DAY orders — they cannot be GTC because they do not rest.



## The data/gtc_orders.json File

Format: a JSON array of serialized `Order` objects.

```json
[
  {
    "id": "3f2a1b4c-...",
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "tif": "GTC",
    "quantity": 100,
    "remaining_qty": 100,
    "gateway_id": "GW01",
    "timestamp": 1714393921345678000,
    "status": "NEW",
    "price": 14800,
    ...
  }
]
```

!!! note "Internal representations in the JSON"
    Prices (`price`, `stop_price`, `trail_offset`) are stored as **integer tick
    values** — e.g. `14800` represents `148.00` for a symbol with `tick_decimals: 2`.
    Timestamps are **nanoseconds** since the Unix epoch, not seconds.

You can inspect or edit this file between trading sessions. To cancel all GTC orders
for the next day, simply delete the file before restarting the engine.



## Trading Day Lifecycle

```
Engine start  (no gateways connected yet)
    │
    ├─ Load data/gtc_orders.json
    ├─ Load data/gtc_combos.json (rebuild parent-child maps)
    ├─ Re-inject GTC orders with original timestamps
    ├─ Publish book snapshots (only if GTC orders were restored)
    ├─ Load data/book_stats.json (restore last_buy/sell prices)
    ├─ Inject market-maker quotes from config  ← seeds posted without MM online
    │       GTC resting orders may cross seeds here; trades fire immediately
    ├─ Inject market-maker combos from config
    ├─ Publish book snapshots (only for symbols where MM quotes injected)
    │
    │  ← Gateways begin connecting ──────────────────
    │  MM gateway connects and re-quotes if seed was consumed
    │
    │  ← Trading session ────────────────────────────
    │  Orders arrive, match, fill, rest
    │
Ctrl-C / SIGTERM
    │
    ├─ Publish order.expired for all DAY resting orders
    ├─ Cascade-cancel DAY combo children
    ├─ Save all resting GTC orders to data/gtc_orders.json
    ├─ Save active GTC combos to data/gtc_combos.json
    ├─ Save book stats to data/book_stats.json
    ├─ Publish system.eod with final book snapshots
    └─ Shutdown
```



## Cancelling a GTC Order

Cancel it like any other order while the engine is running:

```
CANCEL|ID=<full-order-id>
```

Cancelled orders are **not** included in the GTC save at shutdown — they are
already marked `CANCELLED`.

!!! tip
    To find the full order ID, type `ORDERS` in your gateway terminal or check the audit log.



## The data/book_stats.json File

Preserves the **last trade price context** per symbol across sessions.  This allows the
engine to correctly trigger stop orders on the first trade of a new day (stops compare
against `last_trade_price`, which would otherwise be unknown).

Format: a JSON object keyed by symbol.  Prices are stored as **integer tick
values** (the engine's internal representation):

```json
{
  "AAPL": {"last_buy_price": 15025, "last_sell_price": 14980},
  "MSFT": {"last_buy_price": null, "last_sell_price": 41550}
}
```

For a symbol with `tick_decimals: 2`, the value `15025` represents `150.25`.

- `last_buy_price`: tick-integer price of the most recent trade where the buyer was the aggressor
- `last_sell_price`: tick-integer price of the most recent trade where the seller was the aggressor
- `null` means no trade of that type occurred during the session

On startup, persisted values **override** any `last_buy_price` / `last_sell_price` seeded
in `engine_config.yaml`.  Config seeds are only used when no persisted file exists (first run).



## The data/gtc_combos.json File

Format: a JSON array of serialized `ComboOrder` objects (only combos with TIF=GTC and
status `PENDING` or `PARTIALLY_MATCHED`):

```json
[
  {
    "id": "internal-uuid",
    "combo_id": "MY-PAIR-01",
    "gateway_id": "GW01",
    "combo_type": "AON",
    "tif": "GTC",
    "timestamp": 1714393921345678000,
    "legs": [ ... ],
    "status": "PARTIALLY_MATCHED",
    "child_order_ids": ["uuid-1", "uuid-2"],
    "leg_fill_qty": {"0": 50, "1": 0},
    "leg_statuses": {"0": "PARTIAL", "1": "NEW"}
  }
]
```

On restore, the engine rebuilds the `_combos` and `_order_to_combo` tracking maps so
that fill events on restored child orders correctly propagate to their parent combo.



## Other Persistent Files

These files are maintained by subscriber processes (not the engine) and accumulate data
across sessions:

| File | Process | Format | Purpose |
|------|---------|--------|---------|
| `data/audit.log` | pm-audit | Line-oriented JSON | Full event audit trail (rotating: 10 MB × 5 backups) |
| `data/clearing_report.csv` | pm-clearing | CSV | Append-only trade settlement records |
| `data/stats.db` | pm-stats | SQLite | OHLCV statistics, price snapshots, trade log |

These files are **append-only** (or upsert for SQLite) — they are never truncated by the
system.  To reset, delete them manually between sessions.



## Summary of All Data Files

| File | Written By | Written At | Read By | Read At |
|------|-----------|-----------|---------|---------|
| `data/gtc_orders.json` | Engine | Shutdown | Engine | Startup |
| `data/gtc_combos.json` | Engine | Shutdown | Engine | Startup |
| `data/book_stats.json` | Engine | Shutdown | Engine | Startup |
| `data/audit.log` | pm-audit | Continuously | — | Manual inspection |
| `data/clearing_report.csv` | pm-clearing | On each trade | — | Manual inspection |
| `data/stats.db` | pm-stats | On each trade/snapshot | pm-ticker, pm-board | At configured intervals |

All files reside in the `src/data/` directory.
The directory is created automatically if it does not exist.

!!! note "Why `src/data/` and not `data/`?"
    `DATA_DIR` is resolved relative to `src/edumatcher/config.py`, two parent
    directories up, which gives `src/data/`.  A project-root `data/` directory
    also exists (used for sample CSVs) but is not written to by the engine.



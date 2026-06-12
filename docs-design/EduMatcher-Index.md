Version: 0.1.0

Date: 2026-06-12

Status: Design and Research Proposal

# EduMatcher — Exchange Index Design Proposal



## Table of Contents

1. [Motivation](#1-motivation)
2. [Financial Concepts Primer](#2-financial-concepts-primer)
3. [Architecture Overview](#3-architecture-overview)
4. [Index Configuration](#4-index-configuration)
5. [Index Calculation Algorithm](#5-index-calculation-algorithm)
6. [Corporate Actions](#6-corporate-actions)
7. [Symbol Delisting](#7-symbol-delisting)
8. [History and Persistence](#8-history-and-persistence)
9. [Dissemination — Using CALF](#9-dissemination--using-calf)
10. [New Process: `pm-index`](#10-new-process-pm-index)
11. [New Files and Changes to Existing Files](#11-new-files-and-changes-to-existing-files)
12. [ZMQ Messages](#12-zmq-messages)
13. [Gateway Command: `INDEX`](#13-gateway-command-index)
14. [Configuration Reference](#14-configuration-reference)
15. [Testing Guide](#15-testing-guide)
16. [Open Questions and Future Work](#16-open-questions-and-future-work)



## 1. Motivation

EduMatcher currently has no aggregate view of how the exchange as a whole is
performing. Individual symbol prices are visible via the book viewer, but there
is no single number that answers "is the market up or down today?"

A market index solves this. It aggregates prices across a basket of symbols into
one number that rises and falls with the collective market, following the same
principles as real-world indices such as the S&P 500, DAX, or FTSE 100.

This proposal adds:

- A configurable, market-capitalisation-weighted index calculated in a dedicated
  `pm-index` process.
- Real-time index updates published on the existing ZMQ PUB bus and via the CALF
  market-data protocol for external subscribers.
- Historical index values stored on disk so that past index levels can be queried.
- Handling for corporate actions (splits, dividends) and symbol delisting via a
  divisor adjustment mechanism — the same technique used by S&P 500.
- An `INDEX` command in the ALF gateway so traders can query the index interactively.

### Simplifications for educational use

Full production index methodologies (S&P 500, Russell, etc.) involve committees,
eligibility rules, public float calculations, and quarterly reconstitutions.
This design simplifies those to:

- Constituent selection is manual and done via `engine_config.yaml`.
- Weighting is based on configured initial market cap (price × shares), not a
  free-float adjusted market cap from an external data source.
- Rebalancing happens on demand (operator command or config reload), not on a
  fixed schedule.
- Corporate actions are applied manually through a new operator command.

These simplifications are explicitly called out so students understand the gap
between this educational implementation and the real world.



## 2. Financial Concepts Primer

Make sure you understand these concepts before writing any code.

**Index** — A single number computed from the prices of a basket of stocks.
It tells you the aggregate direction of those stocks. An index of 1000 that rises
to 1050 means the basket appreciated by 5% on average (weighted).

**Market capitalisation ("market cap")** — The total value of all outstanding
shares of a company. Calculated as: `share_price × shares_outstanding`. A company
trading at $200 with 1 billion shares has a market cap of $200 billion.

**Cap-weighted index** — Each constituent contributes to the index in proportion
to its market cap relative to the total market cap of all constituents. Large
companies influence the index more than small companies. This is how the S&P 500
works. A stock with a market cap of $400B in an index with $4 trillion total cap
contributes 10% of the index's movement.

**Index divisor** — A scaling factor used to maintain continuity of the index
value across corporate actions and constituent changes. When a constituent splits
its stock or is replaced, the divisor is adjusted so the index level does not jump
artificially. The divisor starts at 1.0 and evolves over time as adjustments occur.
This is the same mechanism used by the S&P 500.

**Base value** — The starting level of the index, conventionally set to 1000 at
launch. The index is always expressed relative to this base.

**Corporate action** — An event by a company that changes its share structure.
Examples: a stock split (10 shares become 20 shares, halving the price), a stock
dividend (existing holders receive new shares), or a rights issue. Each of these
changes the market cap calculation unless the divisor is adjusted.

**Stock split** — A company replaces each existing share with N new shares, and
the price divides by N. After a 2-for-1 split, a $200 stock becomes a $100 stock
with twice as many shares. Market cap is unchanged, but if the index naively uses
the new lower price without adjusting, the index will drop — which is wrong.

**Delisting** — A symbol is removed from trading. The index must remove it from
the basket and adjust the divisor so the remaining constituents continue smoothly.

**Divisor adjustment formula** — When a corporate action or constituent change
would otherwise shift the aggregate market cap, the divisor is adjusted to
preserve the current index level:

```
new_divisor = old_divisor × (new_aggregate_cap / old_aggregate_cap)
```

This means the index level does not change at the moment of adjustment; only
future price movements will change it.



## 3. Architecture Overview

```
┌────────────────────────────────────┐
│         Matching Engine            │
│   PUB :5556                        │
│   trade.executed                   │
│   session.state                    │
└────────────┬───────────────────────┘
             │ ZMQ SUB
             ▼
┌────────────────────────────────────┐
│           pm-index                 │
│   Subscribes to trade.executed     │
│   Subscribes to session.state      │
│   Subscribes to system.eod         │
│   Recalculates index on each trade │
│   Persists snapshots to disk       │
│   Publishes index.update (ZMQ PUB) │
│   Serves index history requests    │
└────────────┬───────────────────────┘
             │ ZMQ PUB :5558
             ▼
┌──────────────────────────────────────────────┐
│                  CALF Gateway (pm-md-gwy)     │
│   Subscribes to index.update on port 5558     │
│   Exposes INDEX channel to external clients   │
└──────────────────────────────────────────────┘
             │ TCP :5570  CALF protocol
             ▼
    External subscribers (bots, viewers)
```

`pm-index` is a new standalone process. It does **not** connect to the engine's
PULL socket — it never sends commands to the engine. It is a pure subscriber that
reads `trade.executed` events and recomputes the index in real time.

It also binds its own PUB socket on port `5558` for downstream consumers. The
existing `pm-md-gwy` (CALF gateway) subscribes to this socket and forwards index
data to external clients via the CALF `INDEX` channel.

### Why a separate process and not inside the engine?

The engine is a single-threaded, latency-sensitive process. Index calculation
involves file I/O (history persistence) and potentially slow aggregations across
many constituents. Keeping it out of the engine loop prevents any index workload
from adding latency to order processing.

### Why a separate PUB socket on port 5558 and not the engine's port 5556?

The engine owns port 5556. The index is calculated externally. Allowing external
processes to publish to the same bus as the engine would break the single-writer
design assumption and make it impossible to reason about message ordering.
Port 5558 is reserved for `pm-index` output.



## 4. Index Configuration

All index configuration lives in `engine_config.yaml` under a new top-level key
`index`. This keeps it alongside the symbol and gateway configuration it depends on.

### 4.1 YAML Structure

```yaml
index:
  enabled: true
  name: "EDU-100"                  # displayed name of the index
  base_value: 1000.0               # index level at launch date
  publish_interval_sec: 1.0        # minimum seconds between published updates
  history_file: "data/index_history.jsonl"  # where snapshots are written

  constituents:
    AAPL:
      shares_outstanding: 15_000_000_000   # used to compute initial market cap weight
      initial_price: 209.50                # reference price at index launch
    MSFT:
      shares_outstanding: 7_400_000_000
      initial_price: 415.00
    TSLA:
      shares_outstanding: 3_200_000_000
      initial_price: 248.00
```

### 4.2 Field Reference

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Whether the index process should run |
| `name` | string | `"EDU-INDEX"` | Short name broadcast in index messages |
| `base_value` | float | `1000.0` | Index level set at launch; does not change after launch |
| `publish_interval_sec` | float | `1.0` | Throttle — minimum seconds between `index.update` publishes |
| `history_file` | string | `"data/index_history.jsonl"` | JSONL file for snapshot persistence |
| `state_file` | string | `"data/index_state.json"` | State file for divisor, last prices, and intraday OHLC recovery |
| `constituents` | dict | — | Map of `symbol → ConstituentConfig` |
| `constituents.<SYM>.shares_outstanding` | int | — | Total shares; used to compute initial weight |
| `constituents.<SYM>.initial_price` | float | — | Price at index launch; used to compute base aggregate cap |

### 4.3 Constituent Weights Explained

The initial weight for each constituent is:

```
initial_cap(sym)      = initial_price(sym) × shares_outstanding(sym)
total_initial_cap     = sum of initial_cap for all constituents
initial_weight(sym)   = initial_cap(sym) / total_initial_cap
```

Weights change as prices move — this is the defining feature of a cap-weighted index.
The `shares_outstanding` value stays fixed (it only changes via corporate action).

### 4.4 Divisor Initialisation at Launch

On first startup (no persisted state), the divisor is computed so that the
initial index value equals `base_value`:

```
initial_aggregate_cap = sum(initial_price(sym) × shares_outstanding(sym))
                        for all constituents
initial_divisor       = initial_aggregate_cap / base_value
```

Example with three stocks:
```
AAPL: 209.50 × 15,000,000,000 = 3,142,500,000,000
MSFT: 415.00 ×  7,400,000,000 = 3,071,000,000,000
TSLA: 248.00 ×  3,200,000,000 =   793,600,000,000

total_initial_cap = 7,007,100,000,000
initial_divisor   = 7,007,100,000,000 / 1000.0 = 7,007,100,000
```

The divisor is a large number but the ratio (aggregate_cap / divisor) always
yields the index level near 1000. The divisor is saved to disk as part of the
persisted state and loaded on restart.



## 5. Index Calculation Algorithm

### 5.1 Index Level Formula

The index level at any moment is:

```
index_level = aggregate_cap / divisor

where:
  aggregate_cap = sum(last_trade_price(sym) × shares_outstanding(sym))
                  for all active constituents
  divisor       = current divisor (adjusted for corporate actions and changes)
```

When no trade has occurred yet for a constituent since startup, the
`initial_price` from the config is used as `last_trade_price`.

### 5.2 Update Trigger

The index recalculates every time a `trade.executed` message arrives for a
constituent symbol. The calculation is O(N) where N is the number of
constituents — typically 5–50 for an educational exchange, so this is fast.

Non-constituent trades are ignored — `pm-index` checks `payload["symbol"]`
against `self._constituents` before doing any work.

### 5.3 Step-by-Step Calculation Code

Below is the complete algorithm. Implement this in `IndexCalculator._recalculate()`:

```python
def _recalculate(self) -> float:
    """
    Compute the current index level from last known prices.

    Returns the new index level as a float.
    """
    aggregate_cap: float = 0.0
    for symbol, constituent in self._constituents.items():
        # Use last known trade price, falling back to initial_price if no trade yet
        price = self._last_prices.get(symbol, constituent.initial_price)
        aggregate_cap += price * constituent.shares_outstanding

    if self._divisor == 0.0:
        raise ValueError("Divisor is zero — index is not initialised")

    return aggregate_cap / self._divisor
```

### 5.4 Throttled Publishing

Recalculation happens on every relevant trade, but publishing is throttled to
`publish_interval_sec` (default 1 second). This prevents flooding subscribers
during a fast market:

```python
def _on_trade(self, symbol: str, price: float) -> None:
    self._last_prices[symbol] = price
    new_level = self._recalculate()
    self._current_level = new_level

    now = time.monotonic()
    if now - self._last_publish_time >= self._publish_interval_sec:
        self._publish(new_level)
        self._last_publish_time = now
```

Even when throttled, the index value is always up-to-date internally. The
throttle only controls how often the value is broadcast.

### 5.5 End-of-Day Snapshot

When a `session.state` message arrives with `state == "CLOSED"`, or when a
`system.eod` message is received, `pm-index` calls one shared EOD finalisation
path guarded by an idempotency flag (for example `_eod_finalized_for_session`).
This guarantees exactly one EOD write/publish per session:

1. Computes the final index value for the day.
2. Writes a snapshot to the history file (see Section 8).
3. Publishes a final `index.update` with `session_state = "CLOSED"`.
4. Resets `_last_publish_time` so the next day starts fresh.

If both events arrive, the second event is ignored for EOD finalisation.



## 6. Corporate Actions

Corporate actions change a company's share structure without changing its
economic value. Without adjustment, a stock split would cause the index to
drop — which would be wrong because no value was destroyed.

The solution is to **adjust the divisor** whenever a corporate action changes
the aggregate market cap, so the index level is preserved at the moment of
adjustment.

### 6.1 The Divisor Adjustment Formula

Whenever a corporate action changes the aggregate market cap from `old_cap` to
`new_cap`, the new divisor is computed as:

```
new_divisor = old_divisor × (new_cap / old_cap)
```

This guarantees `index_level` does not change at the moment of adjustment:

```
Before: index_level = old_cap / old_divisor
After:  index_level = new_cap / new_divisor
                    = new_cap / (old_divisor × new_cap / old_cap)
                    = old_cap / old_divisor   ← same value ✓
```

### 6.2 Stock Split

A split ratio of `N:1` means each share becomes N shares. The price divides by N.

Effect: `shares_outstanding` increases by factor N; `last_price` drops by factor N;
their product (market cap) stays the same. **No divisor adjustment is needed.**

However, the `shares_outstanding` value in the constituent config must be updated.
For educational simplicity, shares remain integers after splits. Use standard
rounding to nearest integer (half up):

```
new_shares_outstanding = int((old_shares * ratio_numerator / ratio_denominator) + 0.5)
```

The snippet below is shown in the `pm-index` runtime service layer (where publish
and history hooks exist), not in the pure `IndexCalculator` math core:

```python
def apply_split(self, symbol: str, ratio_numerator: int, ratio_denominator: int) -> None:
    """
    Apply a stock split.

    ratio_numerator:ratio_denominator — e.g. 2:1 (2-for-1 split), 3:2 (3-for-2 split).
    Example: 2:1 split on AAPL with 15B shares → 30B shares, price halved.
    No divisor adjustment needed because market cap is unchanged.
    """
    constituent = self._constituents[symbol]
    if ratio_numerator <= 0 or ratio_denominator <= 0:
        raise ValueError("Split ratio must be positive")
    # Update shares outstanding with integer rounding policy
    old_shares = constituent.shares_outstanding
    constituent.shares_outstanding = int(
        (old_shares * ratio_numerator / ratio_denominator) + 0.5
    )

    # The current last_price must also be adjusted so aggregate cap stays the same
    old_price = self._last_prices.get(symbol, constituent.initial_price)
    new_price = old_price * ratio_denominator / ratio_numerator
    self._last_prices[symbol] = new_price

    # Divisor is NOT changed — cap is unchanged
    new_level = self._recalculate()
    self._current_level = new_level
    self._publish(new_level)
    self._record_corporate_action_event(
        symbol, "SPLIT",
        f"{ratio_numerator}:{ratio_denominator}",
        old_shares, constituent.shares_outstanding,
        old_price, new_price,
    )
```

### 6.3 Cash Dividend

A cash dividend reduces the stock price by the dividend amount on the ex-dividend date.
In a simple model, the stock price drops by the dividend per share on ex-date.
This reduces the aggregate market cap and therefore requires a **divisor adjustment**.

```python
def apply_cash_dividend(self, symbol: str, dividend_per_share: float) -> None:
    """
    Apply a cash dividend adjustment.

    On ex-dividend date, the stock price drops by dividend_per_share.
    We adjust the divisor so the index level is preserved.
    """
    constituent = self._constituents[symbol]
    old_cap = self._aggregate_cap()  # current total cap before adjustment

    # Apply price reduction
    old_price = self._last_prices.get(symbol, constituent.initial_price)
    new_price = old_price - dividend_per_share
    if new_price <= 0:
        raise ValueError(
            f"Dividend {dividend_per_share} would make {symbol} price non-positive"
        )
    self._last_prices[symbol] = new_price

    new_cap = self._aggregate_cap()  # total cap after price drop

    # Adjust divisor to preserve current index level
    old_divisor = self._divisor
    self._divisor = old_divisor * (new_cap / old_cap)

    new_level = self._recalculate()
    self._current_level = new_level
    self._publish(new_level)
    self._record_corporate_action_event(
        symbol, "CASH_DIVIDEND",
        f"div={dividend_per_share}",
        old_price, new_price,
        old_divisor, self._divisor,
    )
```

### 6.4 Shares Issuance (New Shares Added)

A company issues new shares (e.g. a rights issue). This increases
`shares_outstanding` without changing the current price, so aggregate cap rises.
A divisor adjustment preserves the index level.

```python
def apply_shares_issuance(self, symbol: str, new_shares_outstanding: int) -> None:
    """
    Apply a change to shares outstanding (rights issue, new issuance).
    Adjusts divisor to preserve the current index level.
    """
    constituent = self._constituents[symbol]
    old_cap = self._aggregate_cap()
    constituent.shares_outstanding = new_shares_outstanding
    new_cap = self._aggregate_cap()

    self._divisor = self._divisor * (new_cap / old_cap)
    new_level = self._recalculate()
    self._current_level = new_level
    self._publish(new_level)
```

### 6.5 Applying Corporate Actions via the Operator CLI

Corporate actions are applied through the `pm-operator` command client or via a
new `CORP_ACTION` command to be added to the `ExchangeCommandClient`. See Section 11
for the message design. The `pm-index` process receives the command and applies it
in-process.

Corporate actions are also written to the history file with a `type: "CORP_ACTION"`
record so the change is visible in the historical audit trail.



## 7. Symbol Delisting

When a symbol is delisted, it must be removed from the index basket. The removal
must be done with a divisor adjustment so the remaining constituents continue
smoothly without the index jumping.

### 7.1 Delisting Algorithm

```python
def delist_symbol(self, symbol: str) -> None:
    """
    Remove a constituent from the index and adjust the divisor.

    Steps:
    1. Compute current aggregate cap with the symbol included.
    2. Remove the symbol from _constituents and _last_prices.
    3. Compute new aggregate cap without the symbol.
    4. Adjust divisor: new_divisor = old_divisor × (new_cap / old_cap).
    5. Recompute and publish the index.
    6. Write a DELIST event to the history file.

    After this call, trades in the delisted symbol are silently ignored.
    """
    if symbol not in self._constituents:
        raise KeyError(f"Symbol {symbol!r} is not an index constituent")

    old_cap = self._aggregate_cap()  # before removal
    del self._constituents[symbol]
    self._last_prices.pop(symbol, None)
    new_cap = self._aggregate_cap()  # after removal

    if new_cap == 0.0:
        raise ValueError("Delisting last constituent would make aggregate cap zero")

    old_divisor = self._divisor
    self._divisor = old_divisor * (new_cap / old_cap)
    new_level = self._recalculate()
    self._current_level = new_level
    self._publish(new_level)

    # Record the delisting in history
    self._history.append({
        "type": "DELIST",
        "timestamp": time.time(),
        "symbol": symbol,
        "old_divisor": old_divisor,
        "new_divisor": self._divisor,
        "level": new_level,
    })
    self._flush_history()
```

### 7.2 Adding a New Constituent

Adding a new constituent is the mirror of delisting. New constituents are added with
a divisor adjustment that keeps the current index level unchanged.

```python
def add_constituent(
    self,
    symbol: str,
    shares_outstanding: int,
    initial_price: float,
) -> None:
    """
    Add a new constituent to the index.

    The divisor is adjusted so the index level does not change at the moment
    of addition. Future price movements of the new symbol will affect the index.
    """
    if symbol in self._constituents:
        raise KeyError(f"Symbol {symbol!r} is already a constituent")

    old_cap = self._aggregate_cap()
    self._constituents[symbol] = ConstituentConfig(
        symbol=symbol,
        shares_outstanding=shares_outstanding,
        initial_price=initial_price,
    )
    self._last_prices[symbol] = initial_price
    new_cap = self._aggregate_cap()

    self._divisor = self._divisor * (new_cap / old_cap)
    new_level = self._recalculate()
    self._current_level = new_level
    self._publish(new_level)
```

### 7.3 Handling Trades for Delisted Symbols

Once a symbol is delisted, `pm-index` will receive `trade.executed` messages for
that symbol if it is still on the engine. These must be ignored:

```python
def _on_trade(self, symbol: str, price: float) -> None:
    if symbol not in self._constituents:
        return   # symbol not in index or already delisted — ignore
    self._last_prices[symbol] = price
    # ... rest of update logic
```



## 8. History and Persistence

### 8.1 Storage Format

Index history is stored as a JSONL file (one JSON object per line). This is simple
to write, append-only, human-readable, and trivially parseable in Python. Each line
is a self-contained JSON object:

```json
{"type": "LEVEL", "timestamp": 1749733200.123, "level": 1048.73, "session_state": "CONTINUOUS", "aggregate_cap": 7350000000000.0, "divisor": 7007100000.0}
{"type": "EOD",   "timestamp": 1749760800.000, "level": 1051.20, "session_state": "CLOSED",     "aggregate_cap": 7368000000000.0, "divisor": 7007100000.0, "open": 1042.10, "high": 1056.30, "low": 1040.05, "close": 1051.20}
{"type": "CORP_ACTION", "timestamp": 1749847200.000, "symbol": "AAPL", "action": "SPLIT", "detail": "2:1", "old_divisor": 7007100000.0, "new_divisor": 7007100000.0, "level": 1051.20}
{"type": "DELIST", "timestamp": 1749933600.000, "symbol": "TSLA", "old_divisor": 7007100000.0, "new_divisor": 6180000000.0, "level": 1051.20}
```

#### Record types

| `type` | When written | Fields |
|---|---|---|
| `LEVEL` | Every `publish_interval_sec` during trading | `timestamp`, `level`, `session_state`, `aggregate_cap`, `divisor` |
| `EOD` | When session transitions to `CLOSED` | All `LEVEL` fields plus `open`, `high`, `low`, `close` for the day |
| `CORP_ACTION` | On every corporate action command | `symbol`, `action`, `detail`, `old_divisor`, `new_divisor`, `level` |
| `DELIST` | On delisting | `symbol`, `old_divisor`, `new_divisor`, `level` |
| `ADD_CONSTITUENT` | On adding a constituent | `symbol`, `shares_outstanding`, `initial_price`, `old_divisor`, `new_divisor`, `level` |
| `INIT` | On first startup (no prior state) | `base_value`, `divisor`, `constituents` (list of symbols), `level` |

### 8.2 State Persistence

In addition to the JSONL history, a small state file is needed to recover the
divisor and last-known prices across restarts:

**`data/index_state.json`:**

```json
{
  "divisor": 7007100000.0,
  "last_prices": {
    "AAPL": 211.30,
    "MSFT": 418.50,
    "TSLA": 251.00
  },
  "day_open": 1042.10,
  "day_high": 1056.30,
  "day_low":  1040.05,
  "last_level": 1051.20,
  "last_updated": 1749760800.000
}
```

This file is rewritten on every `EOD` record and on every corporate action. On
startup, if this file exists, the divisor and last prices are loaded from it
rather than re-initialising from config.

### 8.3 History Query

The `pm-index` process serves history queries over ZMQ. The gateway/operator sends
`index.history_request` via PUSH to `INDEX_PULL_ADDR` (`5559`); `pm-index` scans
the JSONL file and replies on its PUB socket (`5558`) with topic
`index.history.{gateway_id}`.

This is an acceptable implementation for educational use. A production system
would use a time-series database.

```python
def _serve_history_request(self, payload: dict) -> None:
    """
    Return LEVEL and EOD records within [from_ts, to_ts].

    The JSONL file is read linearly from disk. For large files this is slow
    but acceptable for an educational system. A future optimisation would
    add a binary-search index by timestamp.
    """
    gateway_id = payload["gateway_id"]
    from_ts = float(payload.get("from_ts", 0.0))
    to_ts   = float(payload.get("to_ts", time.time()))
    record_types = set(payload.get("types", ["LEVEL", "EOD"]))

    results = []
    try:
        with open(self._history_file, "r") as f:
            for line in f:
                rec = json.loads(line)
                if (rec["type"] in record_types
                        and from_ts <= rec["timestamp"] <= to_ts):
                    results.append(rec)
    except FileNotFoundError:
        pass   # No history yet — return empty list

    self._pub_sock.send_multipart(
        make_index_history_msg(gateway_id, results)
    )
```

### 8.4 Intraday OHLC Tracking

During each trading day, `pm-index` tracks:

```python
self._day_open:  float | None  # first index level after session opens
self._day_high:  float         # highest level today
self._day_low:   float         # lowest level today
self._day_close: float | None  # set when session closes
```

These are reset when `session.state` transitions to `OPENING_AUCTION` or
`CONTINUOUS` (start of day). They are written to the `EOD` record at `CLOSED`.



## 9. Dissemination — Using CALF

External clients should be able to receive index data without knowing about ZMQ
or the internal JSON message format. The CALF protocol (documented in
`EduMatcher-Market_Data_Protocol.md`) already solves exactly this problem for
market data. The index is added as a new channel in CALF.

### 9.1 No New Protocol Needed

CALF already provides:
- Subscription by channel and symbol.
- Sequence-numbered incremental updates.
- Gap-recovery with replay.
- A human-readable text format compatible with simple terminal clients.

The index is treated as a "symbol" within the CALF framework — clients subscribe
to `CH=INDEX|SYM=EDU-100` (or whatever the index name is). The existing CALF
`SNAP`, `MD`, and `STATE` message types are extended with index-specific fields,
and a new `IDX` message type handles the index-specific level data.

This approach means no new transport layer, no new port for clients, and no new
client library. A client that already understands CALF can subscribe to the index
by adding one `SUB` message.

### 9.2 New CALF Channel: `INDEX`

Add `INDEX` to the list of valid CALF channels in the CALF specification and in
`pm-md-gwy`.

**Subscription example:**

```
SUB|CH=INDEX|SYM=EDU-100
```

### 9.3 New CALF Message Type: `IDX`

```
IDX|CH=INDEX|SYM=EDU-100|SEQ=42|TS=2026-06-12T10:15:23.411Z|LEVEL=1048.73|CHG=+6.63|PCTCHG=+0.64|OPEN=1042.10|HIGH=1056.30|LOW=1040.05|AGGCAP=7350000000000|SESSION=CONTINUOUS
```

| Field | Req | Type | Description |
|---|---|---|---|
| `CH` | ✓ | string | Always `INDEX` |
| `SYM` | ✓ | string | Index name (e.g. `EDU-100`) |
| `SEQ` | ✓ | int | Monotonic sequence for this `(INDEX, SYM)` stream |
| `TS` | ✓ | string | UTC ISO-8601 timestamp |
| `LEVEL` | ✓ | decimal | Current index level |
| `CHG` | — | decimal | Change from day open (signed); omitted if no open yet |
| `PCTCHG` | — | decimal | Percentage change from day open (signed); omitted if no open yet |
| `OPEN` | — | decimal | Day open level; omitted if session not yet open |
| `HIGH` | — | decimal | Day high level; omitted if session not yet open |
| `LOW` | — | decimal | Day low level; omitted if session not yet open |
| `AGGCAP` | — | int | Current aggregate market cap (integer for display simplicity) |
| `SESSION` | ✓ | string | Current session state (`CONTINUOUS`, `CLOSING_AUCTION`, etc.) |

### 9.4 SNAP for INDEX Channel

When a client subscribes to `CH=INDEX`, the gateway sends an initial `SNAP`:

```
SNAP|CH=INDEX|SYM=EDU-100|SEQ=42|TS=2026-06-12T10:15:23.000Z|LEVEL=1048.73|OPEN=1042.10|HIGH=1056.30|LOW=1040.05|SESSION=CONTINUOUS
```

This is identical in structure to the `IDX` message and uses the same field names.

### 9.5 pm-md-gwy Changes

In `pm-md-gwy`, add a second SUB socket connecting to `pm-index` on port `5558`:

```python
self._index_sub = context.socket(zmq.SUB)
self._index_sub.connect(INDEX_PUB_ADDR)   # "tcp://127.0.0.1:5558"
self._index_sub.setsockopt_string(zmq.SUBSCRIBE, "index.")
```

In the main poll loop, handle `index.update` messages:

```python
if self._index_sub in socks:
    frames = self._index_sub.recv_multipart()
    topic, payload = decode(frames)
    if topic == "index.update":
        self._handle_index_update(payload)
```

`_handle_index_update` converts the internal JSON payload to a CALF `IDX` message
and fans it out to all clients subscribed to `CH=INDEX`.

### 9.6 External Client Example

```python
import socket

s = socket.create_connection(("127.0.0.1", 5570))
s.sendall(b"HELLO|CLIENT=student01|PROTO=CALF1\n")
print(s.recv(4096).decode())

s.sendall(b"SUB|CH=INDEX|SYM=EDU-100\n")

while True:
    line = s.recv(4096).decode().strip()
    parts = line.split("|")
    mtype = parts[0]
    kv = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
    if mtype == "SNAP":
        print(f"Index snapshot: {kv.get('LEVEL')} ({kv.get('SESSION')})")
    elif mtype == "IDX":
        print(f"Index update:   {kv.get('LEVEL')}  {kv.get('CHG')}  ({kv.get('PCTCHG')}%)")
```

The client does not need to know that ZMQ, JSON, or a divisor exist.



## 10. New Process: `pm-index`

### 10.1 Responsibilities

- Load index configuration from `engine_config.yaml`.
- Subscribe to `trade.executed`, `session.state`, `system.eod` on engine PUB
  port 5556.
- Receive `index.corp_action`, `index.constituent_change`, and
  `index.history_request` on a PULL socket (port 5559).
- Recalculate the index on every relevant trade.
- Throttle publications to `publish_interval_sec`.
- Track intraday OHLC.
- Persist history to the JSONL file.
- Persist divisor and last prices to `index_state.json`.
- Bind a PUB socket on port 5558 and publish `index.update` messages.
- Serve `index.history_request` messages.

### 10.2 Non-Responsibilities

- `pm-index` does NOT modify the engine.
- `pm-index` does NOT calculate P&L or positions.
- `pm-index` does NOT publish to port 5556 — that is the engine's exclusive socket.

### 10.3 Process Startup

```
poetry run pm-index
poetry run pm-index --config engine_config.yaml
poetry run pm-index --reset   # delete state file and reinitialise from config
```

### 10.4 Class Structure

**`src/edumatcher/index/main.py`** — entry point and main loop.

**`src/edumatcher/index/calculator.py`** — `IndexCalculator` class:

```python
@dataclass
class ConstituentConfig:
    symbol: str
    shares_outstanding: int
    initial_price: float

class IndexCalculator:
    """
    Pure calculation/state-transition class. No ZMQ, no file I/O.
    Holds the divisor, constituent configs, and last prices.
    Exposes deterministic methods that update internal state and return values.
    Publishing and persistence are handled by the pm-index runtime service.
    """
    def __init__(
        self,
        constituents: list[ConstituentConfig],
        base_value: float,
        divisor: float | None = None,   # None means initialise from constituents
        last_prices: dict[str, float] | None = None,
    ) -> None:
        ...
```

**`src/edumatcher/index/history.py`** — `IndexHistory` class:

```python
class IndexHistory:
    """
    Manages the JSONL history file. Handles append, EOD snapshot, and query.
    No ZMQ — pure file I/O.
    """
    def __init__(self, history_file: str) -> None: ...
    def append(self, record: dict) -> None: ...
    def flush(self) -> None: ...
    def query(self, from_ts: float, to_ts: float, types: set[str]) -> list[dict]: ...
```

**`src/edumatcher/index/config_loader.py`** — `load_index_config(path)` function
that reads `index:` section from `engine_config.yaml`.

### 10.5 Main Loop

```python
def run(self) -> None:
    self._load_or_init_state()
    poller = zmq.Poller()
    poller.register(self._sub_sock, zmq.POLLIN)
    poller.register(self._pull_sock, zmq.POLLIN)

    while self._running:
        socks = dict(poller.poll(timeout=200))
        if self._sub_sock in socks:
            frames = self._sub_sock.recv_multipart()
            topic, payload = decode(frames)
            if topic == "trade.executed":
                self._on_trade(payload)
            elif topic == "session.state":
                self._on_session_state(payload)
            elif topic == "system.eod":
                self._on_eod()
        if self._pull_sock in socks:
            frames = self._pull_sock.recv_multipart()
            topic, payload = decode(frames)
            if topic == "index.corp_action":
                self._on_index_corp_action(payload)
            elif topic == "index.constituent_change":
                self._on_index_constituent_change(payload)
            elif topic == "index.history_request":
                self._serve_history_request(payload)
        # Flush any pending history writes every poll cycle
        self._history.flush()
```

This design is intentionally single-threaded for determinism and simplicity:
all state updates (trades, session transitions, corporate actions, constituent
changes, and history requests) are handled in one poll loop.



## 11. New Files and Changes to Existing Files

### 11.1 New Files

| File | Purpose |
|---|---|
| `src/edumatcher/index/__init__.py` | Package marker (empty) |
| `src/edumatcher/index/main.py` | `pm-index` entry point and run loop |
| `src/edumatcher/index/calculator.py` | `IndexCalculator` class (pure maths, no I/O) |
| `src/edumatcher/index/history.py` | `IndexHistory` JSONL file manager |
| `src/edumatcher/index/config_loader.py` | Load `index:` section from YAML |
| `tests/test_index_calculator.py` | Unit tests for `IndexCalculator` |
| `tests/test_index_history.py` | Unit tests for `IndexHistory` |

### 11.2 Changes to Existing Files

#### `src/edumatcher/config.py`

Add two new address constants:

```python
INDEX_PUB_ADDR  = "tcp://127.0.0.1:5558"   # pm-index → pm-md-gwy
INDEX_PULL_ADDR = "tcp://127.0.0.1:5559"   # operator → pm-index (commands)
```

#### `src/edumatcher/models/message.py`

Add the following new message builders. Follow the existing `make_*` naming and
`encode(topic, payload)` pattern exactly.

```python
# -----------------------------------------------------------------------
# Index messages
# -----------------------------------------------------------------------

def make_index_update_msg(
    index_name: str,
    level: float,
    aggregate_cap: float,
    divisor: float,
    session_state: str,
    day_open: float | None,
    day_high: float | None,
    day_low: float | None,
) -> list[bytes]:
    """pm-index → pm-md-gwy and all: current index level broadcast."""
    payload: dict[str, Any] = {
        "index_name": index_name,
        "level": level,
        "aggregate_cap": aggregate_cap,
        "divisor": divisor,
        "session_state": session_state,
        "timestamp": time.time(),
    }
    if day_open is not None:
        payload["day_open"] = day_open
        payload["day_high"] = day_high
        payload["day_low"]  = day_low
    return encode("index.update", payload)


def make_index_history_request_msg(
    gateway_id: str,
    from_ts: float,
    to_ts: float,
    types: list[str] | None = None,
) -> list[bytes]:
    """Gateway/operator → pm-index: request historical index records."""
    return encode(
        "index.history_request",
        {
            "gateway_id": gateway_id,
            "from_ts": from_ts,
            "to_ts": to_ts,
            "types": types or ["LEVEL", "EOD"],
        },
    )


def make_index_history_msg(
    gateway_id: str,
    records: list[dict[str, Any]],
) -> list[bytes]:
    """pm-index → requestor: history query response."""
    return encode(
        f"index.history.{gateway_id}",
        {"records": records},
    )


def make_index_corp_action_msg(
    action: str,      # "SPLIT", "CASH_DIVIDEND", "SHARES_ISSUANCE"
    symbol: str,
    gateway_id: str,
    params: dict[str, Any],
) -> list[bytes]:
    """Operator → pm-index: apply a corporate action."""
    return encode(
        "index.corp_action",
        {
            "action": action,
            "symbol": symbol,
            "gateway_id": gateway_id,
            **params,
        },
    )


def make_index_constituent_change_msg(
    change_type: str,   # "ADD" or "DELIST"
    symbol: str,
    gateway_id: str,
    shares_outstanding: int | None = None,
    initial_price: float | None = None,
) -> list[bytes]:
    """Operator → pm-index: add or remove a constituent."""
    payload: dict[str, Any] = {
        "change_type": change_type,
        "symbol": symbol,
        "gateway_id": gateway_id,
    }
    if shares_outstanding is not None:
        payload["shares_outstanding"] = shares_outstanding
    if initial_price is not None:
        payload["initial_price"] = initial_price
    return encode("index.constituent_change", payload)
```

#### `engine_config.yaml`

Add the `index:` section (see Section 4.1 for the full structure).

#### `src/edumatcher/commands/client.py`

Add to `_ACK_SUB_PREFIXES`:

```python
"index.history.",   # reply topic for history queries
```

Add new methods to `ExchangeCommandClient`:

```python
def index_history(
    self,
    from_ts: float,
    to_ts: float,
    types: list[str] | None = None,
) -> dict[str, Any]:
    """Query historical index records within the given Unix timestamp range."""
    self._send(make_index_history_request_msg(
        self._gw_id, from_ts, to_ts, types
    ))
    return self._recv(f"index.history.{self._gw_id}")

def index_corp_action(
    self,
    action: str,
    symbol: str,
    **params: Any,
) -> None:
    """
    Apply a corporate action to the index.
    action: "SPLIT", "CASH_DIVIDEND", or "SHARES_ISSUANCE"
    For SPLIT pass ratio_numerator and ratio_denominator.
    For CASH_DIVIDEND pass dividend_per_share.
    For SHARES_ISSUANCE pass new_shares_outstanding.
    """
    self._send(make_index_corp_action_msg(action, symbol, self._gw_id, params))

def index_delist(self, symbol: str) -> None:
    """Remove a constituent from the index."""
    self._send(make_index_constituent_change_msg("DELIST", symbol, self._gw_id))

def index_add_constituent(
    self,
    symbol: str,
    shares_outstanding: int,
    initial_price: float,
) -> None:
    """Add a new constituent to the index."""
    self._send(make_index_constituent_change_msg(
        "ADD", symbol, self._gw_id,
        shares_outstanding=shares_outstanding,
        initial_price=initial_price,
    ))
```

#### `pyproject.toml`

Add the `pm-index` entry point:

```toml
[tool.poetry.scripts]
pm-index = "edumatcher.index.main:main"
```



## 12. ZMQ Messages

### 12.1 Topic Conventions

| Topic | Direction | Description |
|---|---|---|
| `index.update` | `pm-index` → all on port 5558 | Current index level, OHLC, session state |
| `index.history_request` | Gateway/Operator → `pm-index` via port 5559 | Query history by time range |
| `index.history.{GW_ID}` | `pm-index` → requestor via port 5558 | History query response |
| `index.corp_action` | Operator → `pm-index` via port 5559 | Apply corporate action |
| `index.constituent_change` | Operator → `pm-index` via port 5559 | Add or delist constituent |

### 12.2 `index.update` Payload

```json
{
  "index_name": "EDU-100",
      "level": 1048.73,
  "aggregate_cap": 7350000000000.0,
  "divisor": 7007100000.0,
  "session_state": "CONTINUOUS",
  "timestamp": 1749733200.123,
  "day_open": 1042.10,
  "day_high": 1056.30,
  "day_low": 1040.05
}
```

`day_open`, `day_high`, `day_low` are omitted if the session has not yet opened
(e.g. during `PRE_OPEN` or `OPENING_AUCTION` before the first trade).

### 12.3 `index.history_request` Payload

```json
{
  "gateway_id": "GW01",
  "from_ts": 1749700000.0,
  "to_ts":   1749800000.0,
  "types":   ["LEVEL", "EOD"]
}
```

### 12.4 `index.history.{GW_ID}` Payload

```json
{
  "records": [
    {
      "type": "LEVEL",
      "timestamp": 1749733200.123,
      "level": 1048.73,
      "session_state": "CONTINUOUS",
      "aggregate_cap": 7350000000000.0,
      "divisor": 7007100000.0
    },
    {
      "type": "EOD",
      "timestamp": 1749760800.000,
      "level": 1051.20,
      "session_state": "CLOSED",
      "aggregate_cap": 7368000000000.0,
      "divisor": 7007100000.0,
      "open": 1042.10,
      "high": 1056.30,
      "low": 1040.05,
      "close": 1051.20
    }
  ]
}
```

### 12.5 `index.corp_action` Payload

```json
{
  "action": "SPLIT",
  "symbol": "AAPL",
  "gateway_id": "GW_ADMIN",
  "ratio_numerator": 2,
  "ratio_denominator": 1
}
```

```json
{
  "action": "CASH_DIVIDEND",
  "symbol": "MSFT",
  "gateway_id": "GW_ADMIN",
  "dividend_per_share": 2.50
}
```

```json
{
  "action": "SHARES_ISSUANCE",
  "symbol": "TSLA",
  "gateway_id": "GW_ADMIN",
  "new_shares_outstanding": 3500000000
}
```

### 12.6 `index.constituent_change` Payload

```json
{
  "change_type": "DELIST",
  "symbol": "TSLA",
  "gateway_id": "GW_ADMIN"
}
```

```json
{
  "change_type": "ADD",
  "symbol": "AMZN",
  "gateway_id": "GW_ADMIN",
  "shares_outstanding": 10500000000,
  "initial_price": 195.00
}
```



## 13. Gateway Command: `INDEX`

Add an `INDEX` command to the ALF gateway (`gateway/main.py`) following the same
pattern as `SYMBOLS` and `SESSION`. This lets traders at the terminal query the
index without needing a separate tool.

### 13.1 Command Syntax

```
INDEX              — show current index level with OHLC and change
INDEX|HISTORY      — show last 30 days (mixed LEVEL + EOD records)
INDEX|HISTORY|FROM=2026-06-01|TO=2026-06-12  — query history by date range
```

### 13.2 Wiring the Command

Use the existing index sockets directly:

- Subscribe to `pm-index` PUB on `5558` for `index.update` and `index.history.{gateway_id}`.
- Send index commands and history requests to `pm-index` PULL on `5559`.

The gateway subscribes to index data directly on port `5558`:

```python
# In Gateway.__init__, add a second SUB socket for index data
self._index_sub = make_subscriber_at(
    INDEX_PUB_ADDR,
    f"index.update",
    f"index.history.{self.gateway_id}",
)
```

> **Note:** `make_subscriber_at` would be a small helper that accepts an address
> as its first argument instead of using `ENGINE_PUB_ADDR`. Alternatively, add
> `INDEX_PUB_ADDR` as an additional address to the existing `make_subscriber`
> if the bus module supports multiple addresses. The simplest approach is to
> create a second subscriber socket in `Gateway.__init__` and poll both sockets
> in `_listen()`.

**Modified `_listen()` to poll two sockets:**

```python
def _listen(self) -> None:
    poller = zmq.Poller()
    poller.register(self.sub_sock, zmq.POLLIN)
    poller.register(self._index_sub, zmq.POLLIN)
    while self._running:
        socks = dict(poller.poll(timeout=200))
        if self.sub_sock in socks:
            frames = self.sub_sock.recv_multipart()
            topic, payload = decode(frames)
            self._handle_event(topic, payload)
        if self._index_sub in socks:
            frames = self._index_sub.recv_multipart()
            topic, payload = decode(frames)
            self._handle_event(topic, payload)
```

**Handler additions in `_handle_event`:**

```python
elif "index.update" in topic:
    self._last_index_update = payload   # cache latest for instant local display

elif "index.history" in topic:
    self._print_index_history(payload.get("records", []))
```

**Dispatch in `_parse_and_send`:**

```python
if cmd == "INDEX":
    kv = self._kv(parts[1:])
    if "HISTORY" in parts[1:] or kv.get("HISTORY") is not None or len(parts) > 1 and parts[1].upper() == "HISTORY":
        # Parse optional FROM= / TO= date strings
        from_ts = _parse_date(kv.get("FROM")) or (time.time() - 86400 * 30)
        to_ts   = _parse_date(kv.get("TO"))   or time.time()
        self._index_push_sock.send_multipart(
            make_index_history_request_msg(self.gateway_id, from_ts, to_ts)
        )
    else:
        # Print current cached level immediately (no network round-trip needed)
        self._print_current_index()
    return
```

`_index_push_sock` is a PUSH socket connecting to `INDEX_PULL_ADDR` (port 5559).

### 13.3 Display Helpers

```python
def _print_current_index(self) -> None:
    p = self._last_index_update
    if not p:
        console.print("[dim]No index data received yet. Is pm-index running?[/dim]")
        return
    ts = datetime.fromtimestamp(p["timestamp"]).strftime("%H:%M:%S.%f")[:-3]
    level = p["level"]
    session = p.get("session_state", "?")
    chg = ""
    if p.get("day_open"):
        delta = level - p["day_open"]
        pct   = delta / p["day_open"] * 100
        colour = "green" if delta >= 0 else "red"
        chg = f"  [{colour}]{delta:+.2f}  {pct:+.2f}%[/{colour}]"
    ohlc = ""
    if p.get("day_open"):
        ohlc = (
            f"  [dim]O={p['day_open']:.2f}  "
            f"H={p['day_high']:.2f}  "
            f"L={p['day_low']:.2f}[/dim]"
        )
    console.print(
        f"[{ts}] [bold cyan]{p.get('index_name', 'INDEX')}[/bold cyan]  "
        f"[bold]{level:.2f}[/bold]{chg}{ohlc}  [dim]{session}[/dim]"
    )
```

### 13.4 Update `_HELP_TEXT`

Add to the operational commands section:

```
  INDEX              — show current index level (requires pm-index running)
  INDEX|HISTORY      — show 30-day mixed LEVEL/EOD history
  INDEX|HISTORY|FROM=YYYY-MM-DD|TO=YYYY-MM-DD  — custom date range
```

### 13.5 Update `_TOP_LEVEL_CMDS`

```python
_TOP_LEVEL_CMDS = [
    ...
    "SESSION",
    "INDEX",      # ← add here
    "HELP",
    ...
]
```



## 14. Configuration Reference

### 14.1 Full `index:` YAML Section

```yaml
# ---------------------------------------------------------------------------
# Index configuration — used by pm-index
# ---------------------------------------------------------------------------
index:
  enabled: true

  # Displayed name of the index; used in ZMQ messages and CALF output
  name: "EDU-100"

  # Starting level assigned at first launch (no state file found).
  # Does NOT change after the index is initialised. Change of base_value
  # after launch requires --reset, which loses all history continuity.
  base_value: 1000.0

  # Minimum seconds between consecutive index.update publishes.
  # Recalculation still happens on every trade; only publishing is throttled.
  publish_interval_sec: 1.0

  # Path to the JSONL history file (relative to project root or absolute).
  history_file: "data/index_history.jsonl"

  # Path to the state file that persists divisor and last prices across restarts.
  state_file: "data/index_state.json"

  # Constituent symbols and their weighting parameters.
  # shares_outstanding × initial_price = initial market cap weight.
  # These values are used ONLY at first launch to compute the divisor.
  # After launch, shares_outstanding is updated via corporate action commands.
  constituents:
    AAPL:
      shares_outstanding: 15_000_000_000
      initial_price: 209.50
    MSFT:
      shares_outstanding: 7_400_000_000
      initial_price: 415.00
    TSLA:
      shares_outstanding: 3_200_000_000
      initial_price: 248.00
```

### 14.2 Socket Addresses

Add to `src/edumatcher/config.py`:

```python
INDEX_PUB_ADDR  = "tcp://127.0.0.1:5558"
INDEX_PULL_ADDR = "tcp://127.0.0.1:5559"
```

### 14.3 Process Startup Order

The recommended startup order with `pm-index` added:

1. `pm-engine` — binds PULL :5555 and PUB :5556
2. `pm-index` — subscribes to engine PUB :5556, binds own PUB :5558 and PULL :5559
3. `pm-md-gwy` — subscribes to engine PUB :5556 and index PUB :5558
4. `pm-scheduler` — sends session transitions
5. Gateways and viewers — connect as usual

`pm-index` can be started or restarted without stopping the engine. It will
simply miss trades that occurred while it was down; the next published value
will be based on whatever `last_prices` are in its state file plus new trades
after reconnect.



## 15. Testing Guide

### 15.1 Unit Tests for `IndexCalculator`

Create `tests/test_index_calculator.py`. These tests do not require ZMQ or the
engine — they test pure calculation logic.

```python
from edumatcher.index.calculator import IndexCalculator, ConstituentConfig

def _make_calc() -> IndexCalculator:
    """Three constituents: AAPL, MSFT, TSLA at known initial prices."""
    return IndexCalculator(
        constituents=[
            ConstituentConfig("AAPL", shares_outstanding=15_000_000_000, initial_price=209.50),
            ConstituentConfig("MSFT", shares_outstanding=7_400_000_000,  initial_price=415.00),
            ConstituentConfig("TSLA", shares_outstanding=3_200_000_000,  initial_price=248.00),
        ],
        base_value=1000.0,
    )


class TestInitialisation:
    def test_initial_level_equals_base_value(self):
        calc = _make_calc()
        assert abs(calc.recalculate() - 1000.0) < 0.01

    def test_divisor_is_nonzero(self):
        calc = _make_calc()
        assert calc.divisor > 0


class TestPriceUpdate:
    def test_price_rise_increases_level(self):
        calc = _make_calc()
        calc.update_price("AAPL", 230.00)   # was 209.50
        assert calc.recalculate() > 1000.0

    def test_price_fall_decreases_level(self):
        calc = _make_calc()
        calc.update_price("AAPL", 190.00)   # was 209.50
        assert calc.recalculate() < 1000.0

    def test_non_constituent_update_ignored(self):
        calc = _make_calc()
        level_before = calc.recalculate()
        calc.update_price("AMZN", 200.00)   # not a constituent
        assert abs(calc.recalculate() - level_before) < 0.0001


class TestStockSplit:
    def test_split_preserves_index_level(self):
        calc = _make_calc()
        level_before = calc.recalculate()
        calc.apply_split("AAPL", ratio_numerator=2, ratio_denominator=1)
        level_after = calc.recalculate()
        # Index level must not change after a split
        assert abs(level_after - level_before) < 0.01

    def test_split_doubles_shares(self):
        calc = _make_calc()
        old_shares = calc.get_constituent("AAPL").shares_outstanding
        calc.apply_split("AAPL", 2, 1)
        assert calc.get_constituent("AAPL").shares_outstanding == old_shares * 2

    def test_split_halves_price(self):
        calc = _make_calc()
        old_price = calc.last_price("AAPL")
        calc.apply_split("AAPL", 2, 1)
        assert abs(calc.last_price("AAPL") - old_price / 2) < 0.001


class TestCashDividend:
    def test_dividend_preserves_index_level(self):
        calc = _make_calc()
        level_before = calc.recalculate()
        calc.apply_cash_dividend("MSFT", dividend_per_share=2.50)
        level_after = calc.recalculate()
        assert abs(level_after - level_before) < 0.01

    def test_dividend_adjusts_divisor(self):
        calc = _make_calc()
        old_divisor = calc.divisor
        calc.apply_cash_dividend("MSFT", 2.50)
        assert calc.divisor != old_divisor


class TestDelisting:
    def test_delist_preserves_index_level(self):
        calc = _make_calc()
        level_before = calc.recalculate()
        calc.delist_symbol("TSLA")
        level_after = calc.recalculate()
        assert abs(level_after - level_before) < 0.01

    def test_delist_removes_constituent(self):
        calc = _make_calc()
        calc.delist_symbol("TSLA")
        assert "TSLA" not in calc.constituent_symbols()

    def test_delisted_price_update_ignored(self):
        calc = _make_calc()
        calc.delist_symbol("TSLA")
        level_before = calc.recalculate()
        calc.update_price("TSLA", 500.00)   # should be ignored
        assert abs(calc.recalculate() - level_before) < 0.0001


class TestAddConstituent:
    def test_add_preserves_index_level(self):
        calc = _make_calc()
        level_before = calc.recalculate()
        calc.add_constituent("AMZN", shares_outstanding=10_500_000_000, initial_price=195.00)
        level_after = calc.recalculate()
        assert abs(level_after - level_before) < 0.01

    def test_new_constituent_price_moves_index(self):
        calc = _make_calc()
        calc.add_constituent("AMZN", 10_500_000_000, 195.00)
        level_before = calc.recalculate()
        calc.update_price("AMZN", 220.00)   # large price move
        assert calc.recalculate() > level_before
```

### 15.2 Unit Tests for `IndexHistory`

```python
import json
import tempfile
from pathlib import Path
from edumatcher.index.history import IndexHistory

class TestIndexHistory:
    def test_append_and_query(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        h = IndexHistory(path)
        h.append({"type": "LEVEL", "timestamp": 1000.0, "level": 1010.0})
        h.append({"type": "EOD",   "timestamp": 2000.0, "level": 1020.0})
        h.flush()

        results = h.query(from_ts=0.0, to_ts=3000.0, types={"LEVEL", "EOD"})
        assert len(results) == 2

    def test_query_type_filter(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        h = IndexHistory(path)
        h.append({"type": "LEVEL", "timestamp": 1000.0, "level": 1010.0})
        h.append({"type": "EOD",   "timestamp": 2000.0, "level": 1020.0})
        h.flush()

        results = h.query(from_ts=0.0, to_ts=3000.0, types={"EOD"})
        assert len(results) == 1
        assert results[0]["type"] == "EOD"
```

### 15.3 Manual End-to-End Test

1. Start the engine: `poetry run pm-engine`
2. Start `pm-index`: `poetry run pm-index`
3. Open a gateway: `poetry run pm-gateway --id GW01`
4. Type `INDEX` — you should see `No index data received yet` (no trades yet).
5. Submit two orders that cross: `NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=210.00`
   and `NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=210.00`.
6. Type `INDEX` — you should now see a level close to 1000.
7. Run more AAPL trades at higher prices and type `INDEX` again — level should rise.
8. In a separate terminal, start the scheduler: `poetry run pm-scheduler --now`.
   When it sends `CLOSED`, check that an `EOD` record appears in `data/index_history.jsonl`.
9. Query history from the gateway: `INDEX|HISTORY` — you should see the EOD record.

### 15.4 Integration and Failure-Path Tests (Required)

Add the following integration tests so implementation matches this design and
does not regress under operational edge cases.

1. **Socket wiring and transport contract**
    - Verify gateway sends `index.history_request` to `INDEX_PULL_ADDR` (`5559`).
    - Verify `pm-index` replies on `INDEX_PUB_ADDR` (`5558`) with topic
      `index.history.{gateway_id}`.
    - Verify gateway receives history response from index PUB socket, not engine PUB.

2. **Gateway command round-trip**
    - `INDEX` prints cached latest `index.update`.
    - `INDEX|HISTORY` sends request, receives response, and renders records.
    - `INDEX|HISTORY|FROM=...|TO=...` limits returned records to range.

3. **EOD deduplication**
    - Send `session.state=CLOSED` and `system.eod` in the same session.
    - Assert exactly one EOD record is written.
    - Assert exactly one final CLOSED `index.update` is published.

4. **Single-thread determinism under mixed events**
    - Feed interleaved trade, corp action, constituent change, and history request events.
    - Assert no race symptoms (no partial updates, no inconsistent divisor/constituent state).
    - Assert event ordering is deterministic for identical input sequence.

5. **Restart and recovery behavior**
    - Restart `pm-index` with existing `state_file` and assert divisor/last prices reload.
    - Assert first post-restart index level is computed from restored state + new trades.
    - Assert process continues serving history requests after restart.

6. **Corporate-action validation checks**
    - Invalid split ratios (`<= 0`) are rejected.
    - Dividend that makes price non-positive is rejected.
    - Delisting non-constituent symbol returns clear error.



## 16. Open Questions and Future Work

### 16.1 Open Questions

1. **Weighting methodology** — This design uses full market cap weighting
   (price × total shares). Should a free-float adjustment be added? In a real
   exchange not all shares trade publicly. For educational purposes, full cap
   weighting is sufficient, but a `float_factor` field per constituent (e.g. 0.85
   meaning 85% of shares are freely floating) could be added to `ConstituentConfig`
   as a future enhancement without changing the core algorithm.

2. **Real-time vs. delayed index** — The index currently updates on every
   constituent trade. Real-world indices are typically calculated at a fixed
   cadence (e.g. every 15 seconds for the S&P 500 during trading hours). The
   `publish_interval_sec` throttle approximates this, but the calculation is still
   real-time. This is a deliberate simplification.

3. **Multiple indices** — The design supports exactly one index. Supporting multiple
   indices (e.g. an index for large caps and another for small caps) would require
   `pm-index` to manage a list of `IndexCalculator` instances and route trades to
   the right one. This is a straightforward extension: change the `index:` config
   key to `indices:` (a list) and name each entry.

4. **What happens if `pm-index` is offline when a session closes?** — The EOD record
   will not be written. On restart, `pm-index` will load the state file and compute
   the current level from the last known prices. The missing EOD record is a gap in
   history. A future improvement would have `pm-index` write a `RESTART` event on
   startup and compute a synthetic EOD if the state file indicates a previous session
   ended without an EOD record.

5. **Price staleness** — If MSFT has not traded in several hours, the index uses
   MSFT's last known price. This is standard practice for intraday indices (use the
   last transaction price). A future enhancement could flag constituents as "stale"
   if no trade has occurred in a configurable window and show that in the `IDX` CALF
   message.

### 16.2 Future Work (v2+)

- **Sector sub-indices** — Split constituents into sectors (Technology, Energy, etc.)
  and compute sub-indices per sector. Displayed as `EDU-TECH`, `EDU-ENERGY`, etc.
- **Benchmark comparison** — Add a separate field `vs_benchmark` to `IDX` messages
  showing performance against a fixed comparison level.
- **BCALF binary index feed** — Once BALF (binary ALF) is implemented, add a binary
  variant of the `IDX` message for low-latency consumers.
- **HTTP REST endpoint** — Add a simple HTTP endpoint to `pm-index` for one-off
  queries from web dashboards or notebooks, without needing a CALF client.
- **Constituent rebalancing command** — A `REBALANCE` operator command that updates
  all `shares_outstanding` values at once from a CSV file, applies divisor adjustments
  for each change, and records a bulk `REBALANCE` event in the history.
- **Persistence to a time-series database** — Replace the JSONL file with SQLite
  or InfluxDB for faster range queries once history files grow large.



## Summary of Implementation Steps

For a junior developer, follow this order:

1. **Read** `models/session.py`, `models/message.py`, and `engine/main.py` (the main loop only) to understand the ZMQ pattern.
2. **Create** `src/edumatcher/index/calculator.py` with `ConstituentConfig` and `IndexCalculator`. Write unit tests. Get them passing.
3. **Create** `src/edumatcher/index/history.py` with `IndexHistory`. Write unit tests. Get them passing.
4. **Add** message builders to `models/message.py` (Section 11.2). Add lightweight unit tests for topic names and required payload keys.
5. **Add** address constants to `config.py`.
6. **Create** `src/edumatcher/index/config_loader.py` to parse the `index:` YAML section.
7. **Create** `src/edumatcher/index/main.py`. Start with a minimal version that subscribes, recalculates, and prints to stdout. No ZMQ publish yet. Test with the engine running.
8. **Add** the ZMQ PUB socket output and PULL command socket to `pm-index`.
9. **Add** the `INDEX` command to `gateway/main.py` (Section 13).
10. **Add** the CALF `INDEX` channel to `pm-md-gwy` (Section 9.5).
11. **Test** end-to-end with the manual test sequence in Section 15.3.
12. **Add** corporate action and constituent change handling last — these are less urgent and depend on steps 7–8 being solid first.

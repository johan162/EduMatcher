Version: 1.2.0

Date: 2026-07-05

Status: Design and Research Proposal

# EduMatcher - Contract Multiplier in Symbol Definition

## Table of Contents

1. Finance Concepts Primer
2. Motivation and Current Failure Modes
3. Problem Statement
4. Goals and Non-Goals
5. Proposed Data Model Changes
6. Message Contract Changes
7. Exact Formula Impact in Clearing
8. Statistics Module Deep Analysis
9. Risk Controls: Collars and Circuit Breakers
10. Index Calculation Impact
11. Process-by-Process Impact Analysis
12. Config Tooling: `pm-config-gen` and `pm-cverifier`
13. Complete Code Change Manifest
14. SQLite Schema Migrations
15. Worked Example: `ESU6` with Multiplier 50
16. Test Scenarios
17. Additional Risks and Migration Considerations
18. Documentation Update Plan
19. Iterative Implementation Plan
20. Acceptance Checklist
21. Resolved Design Decisions

## 1. Finance Concepts Primer

Before reading the technical sections, understand these terms. Every design
decision below makes sense only once you understand what the system is modelling.

### What is a contract multiplier?

In financial markets, a contract multiplier (sometimes called *contract size* or
*point value*) scales the economic exposure of one unit of quantity.

For equities:

- 1 share of AAPL at price $150 = $150 economic exposure.
- Contract multiplier = 1.

For futures:

- 1 ES futures contract at price 5325 points.
- Contract multiplier = 50 (the E-mini S&P 500 standard).
- 1 contract at 5325 = 5325 × 50 = $266,250 economic exposure.
- A 1-point move in price = $50 profit or loss per contract.

This is not a display factor like `tick_decimals` — it is a scaling factor
applied to compute economic notional value and P&L.

### What is notional value vs economic notional?

**Raw notional** = `price_ticks × qty` — current stored integer accounting value.
It preserves historical reconcile semantics and is not multiplier-adjusted.

**Display notional** = `price_display × qty` — useful for price charts, VWAP.

**Economic notional** = `price_display × qty × contract_multiplier` — the actual
dollar exposure. In storage, the equivalent integer value is
`price_ticks × qty × contract_multiplier`.

For multiplier = 1 (equities), these are identical. For multiplier > 1
(derivatives), economic notional can be orders of magnitude larger.

### What is VWAP and does multiplier affect it?

Volume-weighted average price: sum(price × qty) / sum(qty).

Multiplier cancels out completely in VWAP:

```
VWAP = Σ(price × qty × m) / Σ(qty × m)
     = Σ(price × qty) / Σ(qty)
```

**Conclusion: VWAP is a pure price measure. It is correct without applying
multiplier.**

### What is realized P&L and does multiplier affect it?

**Without multiplier (current code):**

```
realized_pnl = (close_price - avg_cost) × closed_qty
```

This gives a P&L in price-unit terms. For equities (multiplier = 1) this is
correct in dollars. For futures (multiplier = 50) this is 50× too small.

**With multiplier:**

```
realized_pnl = (close_price - avg_cost) × closed_qty × contract_multiplier
```

### What is avg_cost and should multiplier be inside it?

`avg_cost` is the volume-weighted average entry price per unit. Multiplier must
NOT be folded into avg_cost because:

- avg_cost must be comparable to market price (same units).
- All fill-leg comparisons (`price - avg_cost`) depend on this.

Multiplier is applied only at the point of computing dollar P&L and notional.

### What is a price collar and does multiplier affect it?

A price collar rejects orders whose price deviates too far from a reference:

```python
static_upper = int(ref * (1 + static_band_pct))
static_lower = int(ref * (1 - static_band_pct))
```

This is a price-ratio comparison. Both sides are in the same price unit and
multiplier cancels out. **Collars do not need modification.**

However: when calibrating collar band percentages (e.g., ±20%), operators of
high-multiplier contracts must recognise that a 1% price move on a ×50
contract causes 50× more dollar exposure than the same percentage on a ×1
contract. This is a configuration advisory, not a code change.

### What is a circuit breaker and does multiplier affect it?

Circuit breakers monitor rolling-average price deviation:

```python
shift = abs(price - ref) / ref
```

This is a ratio of prices in the same unit. Multiplier cancels. **Circuit
breakers do not need modification.**

---

## 2. Motivation and Current Failure Modes

EduMatcher currently models per-symbol tick precision (`tick_decimals`) but does
not model per-symbol contract multiplier.

For **equity-like symbols** (multiplier = 1), the current system is correct.

For **futures-like symbols** (multiplier > 1), the following economic values are
silently **wrong or unavailable** today:

| Field | Where produced | Current calculation | Error factor |
|---|---|---|---|
| `realized_pnl` | `clearing/ledger.py` | `(price − avg_cost) × qty` | off by `m` |
| `unrealized_pnl` | `clearing/ledger.py` | `net_qty × (price − avg_cost)` | off by `m` |
| economic buy notional | `clearing/ledger.py` | not stored; only `qty × price_ticks` raw notional exists | missing |
| economic sell notional | `clearing/ledger.py` | not stored; only `qty × price_ticks` raw notional exists | missing |
| economic net amount | `clearing/store.py` | not stored; only raw net amount exists | missing |
| `gross_notional` | `clearing/cli.py` (exposure) | `ABS(net_qty × mark_price)` | off by `m` |
| economic traded notional | `clearing/store.py` | not stored; only `qty × price` raw notional exists | missing |

The statistics module is more nuanced (see Section 8).

## 3. Problem Statement

We need a design that introduces symbol-level contract multiplier while:

- preserving backward compatibility for existing configurations (multiplier absent = 1)
- keeping avg_cost as a per-unit price (not folding multiplier into it)
- correctly scaling realized P&L, unrealized P&L, and newly added economic
    notional fields in clearing
- avoiding VWAP changes in the statistics module (VWAP is not affected)
- keeping collars and circuit breakers unchanged (price-ratio math)
- carrying multiplier in event payloads so consumers are self-contained
- adding multiplier to config tooling and verifier

## 4. Goals and Non-Goals

### 4.1 Goals

- Add non-mandatory `contract_multiplier` to symbol config, defaulting to `1`.
- Extend `trade.executed` and `system.symbols` to carry `contract_multiplier`.
- Correct P&L and notional math in `clearing/ledger.py`.
- Persist `contract_multiplier` in clearing, stats trade logs, and participant
    event payloads where consumers reconstruct exposure.
- Preserve existing raw notional columns and add separate economic notional
    columns instead of reinterpreting historical storage.
- Apply multiplier exactly once when computing economic notional and P&L values.
- Update `pm-config-gen` and `pm-cverifier`.
- Maintain all existing raw tick-unit storage; never break reconcile integrity.
- Provide a worked numeric example and acceptance checklist.

### 4.2 Non-Goals

- No redesign of matching logic, order book, or price-time priority.
- No support for variable multipliers over time (single static value per symbol).
- No margin engine, haircut, or settlement design.
- No per-gateway multiplier override.

## 5. Proposed Data Model Changes

### 5.1 Engine config symbol schema

Add optional field under each symbol entry in `engine_config.yaml`:

```yaml
symbols:
  AAPL:
    tick_decimals: 2
    # contract_multiplier omitted → defaults to 1
  ESU6:
    tick_decimals: 2
    contract_multiplier: 50
```

Field rules:

| Property | Specification |
|---|---|
| Type | Integer only in v1 |
| Validation | Must be a strictly positive integer; floats and fractional numeric strings are invalid |
| Default | 1 when omitted |
| Range advisory | 1 to 10,000 (warn if > 10,000 in pm-cverifier) |

### 5.2 SymbolConfig dataclass

In `src/edumatcher/engine/config_loader.py`, class `SymbolConfig`:

```python
@dataclass
class SymbolConfig:
    name: str
    level: str | None = None
    tick_decimals: int = 2
    outstanding_shares: int | None = None
    contract_multiplier: int = 1     # NEW
    ...
```

Parsing addition. Do not use `int(cm_raw)` directly, because it silently truncates
floats such as `1.5` to `1`:

```python
cm_raw = cfg.get("contract_multiplier", 1)
if isinstance(cm_raw, bool) or not isinstance(cm_raw, int):
    raise ValueError(f"Symbol '{sym}': contract_multiplier must be an integer")
contract_multiplier = cm_raw
if contract_multiplier <= 0:
    raise ValueError(f"Symbol '{sym}': contract_multiplier must be > 0")
```

## 6. Message Contract Changes

### 6.1 `trade.executed` — add `contract_multiplier`

In `src/edumatcher/engine/main.py`, method `_publish_trade`:

```python
def _publish_trade(self, trade: Any) -> None:
    tick_decimals = get_tick_decimals(trade.symbol)
    contract_multiplier = self._get_contract_multiplier(trade.symbol)  # NEW
    _pub = self.pub_sock
    _pub.send_multipart(
        [
            _TRADE_TOPIC,
            dumps(
                {
                    "id": trade.id,
                    "symbol": trade.symbol,
                    "buy_order_id": trade.buy_order_id,
                    "sell_order_id": trade.sell_order_id,
                    "buy_gateway_id": trade.buy_gateway_id,
                    "sell_gateway_id": trade.sell_gateway_id,
                    "price": from_ticks(trade.price, trade.symbol),
                    "tick_decimals": tick_decimals,
                    "contract_multiplier": contract_multiplier,   # NEW
                    "quantity": trade.quantity,
                    "aggressor_side": trade.aggressor_side,
                    "timestamp": trade.timestamp / 1_000_000_000,
                }
            ),
        ]
    )
```

`_get_contract_multiplier` is a small helper:

```python
def _get_contract_multiplier(self, symbol: str) -> int:
    if self._engine_config:
        sym_cfg = self._engine_config.symbols.get(symbol)
        if sym_cfg is not None:
            return sym_cfg.contract_multiplier
    return 1
```

### 6.2 `system.symbols.{GW_ID}` — add `contract_multiplier` to metadata

In `src/edumatcher/engine/main.py`, method `_handle_symbols_request`, inside the
`symbol_meta` construction loop:

```python
if sym_cfg is not None:
    meta["tick_size"] = 10 ** (-int(sym_cfg.tick_decimals))
    meta["contract_multiplier"] = sym_cfg.contract_multiplier   # NEW
```

### 6.3 Trade model

In `src/edumatcher/models/trade.py`:

- Add `contract_multiplier: int = 1` field to the `Trade` dataclass.
- Update `to_dict()` to emit `"contract_multiplier": self.contract_multiplier`.
- Update `from_dict()` to validate a positive integer with the same helper used
    at config and clearing-ingest boundaries. Do not silently truncate floats.

### 6.4 Clearing trade ingestion normalization

In `src/edumatcher/clearing/main.py`, function `_trade_from_payload`:

```python
normalized["contract_multiplier"] = _parse_contract_multiplier(payload)
```

Validate this as a positive integer before constructing `Trade`; reject bools,
floats, fractional strings, zero, and negative values.

### 6.5 Private fill and drop-copy messages — add `contract_multiplier`

`order.fill.{GW_ID}` is not just an acknowledgement in practice. The ALF console
updates a local position/P&L tracker from fill messages, and external clients can
do the same. To make participant-local exposure calculations self-contained,
private fill messages must include `contract_multiplier`.

In `src/edumatcher/models/message.py`, extend `make_fill_msg()` payloads:

```python
payload = {
    "order_id": order_id,
    "fill_qty": fill_qty,
    "fill_price": fill_price,
    "contract_multiplier": contract_multiplier,
    "remaining_qty": remaining_qty,
    "status": status,
}
```

In `src/edumatcher/engine/main.py`, every call to `make_fill_msg()` must pass
the symbol's multiplier. The engine drop-copy publisher must include the same
field in its `order.fill` drop-copy payloads because drop copy is explicitly a
participant risk/clearing feed.

`pm-alf-console` should store multiplier per symbol from `system.symbols` and
apply it in its local realized P&L calculation. If the field is missing, default
to 1 for backward compatibility.

### 6.6 Translated external protocols — add explicit `MULT`

RALF and CALF/market-data gateways are not raw dictionary pass-throughs; they
build explicit protocol field maps. They must add a multiplier field explicitly:

| Gateway | Message | New field | Semantics |
|---|---|---|---|
| `pm-ralf-gwy` | `EXEC` | `MULT` | Contract multiplier from `trade.executed` |
| `pm-md-gwy` | `TRADE` | `MULT` | Contract multiplier from `trade.executed` |

Do not add economic notional to these messages in v1. Keep `PX` and `QTY`
unchanged, and let downstream consumers compute `PX × QTY × MULT` if needed.

### 6.7 Messages that do NOT need multiplier

| Message | Reason |
|---|---|
| `book.{SYMBOL}` | Pure price/quantity data; multiplier irrelevant for matching |
| `depth.{SYMBOL}` | Depth metrics; price-ratio based |
| `order.ack.*`, `order.cancelled.*` etc | Order lifecycle; no P&L content |
| `circuit_breaker.halt.*` | Price-ratio based trigger; multiplier irrelevant |
| `session.state` | No numerical data |

## 7. Exact Formula Impact in Clearing

### 7.1 Reading the current code

The four formulas in `src/edumatcher/clearing/ledger.py` that must change:

**Line: realized P&L on long close**
```python
# Current
realized_delta = (float(price) - pos.avg_cost) * close_qty
# Corrected
realized_delta = (float(price) - pos.avg_cost) * close_qty * pos.contract_multiplier
```

**Line: realized P&L on short close**
```python
# Current
realized_delta = (pos.avg_cost - float(price)) * close_qty
# Corrected
realized_delta = (pos.avg_cost - float(price)) * close_qty * pos.contract_multiplier
```

**Line: unrealized P&L update**
```python
# Current
pos.unrealized_pnl = pos.net_qty * (float(price) - pos.avg_cost)
# Corrected
pos.unrealized_pnl = pos.net_qty * (float(price) - pos.avg_cost) * pos.contract_multiplier
```

**Lines: economic notional accumulators in `_apply_leg`**
```python
# Current
pos.buy_notional += quantity * price
pos.sell_notional += quantity * price
delta.traded_notional += quantity * price
delta.buy_notional += quantity * price
delta.sell_notional += quantity * price

# Corrected design: preserve these raw columns unchanged and add separate
# economic columns.
raw_notional = quantity * price
economic_notional = raw_notional * contract_multiplier

pos.buy_notional += raw_notional
pos.buy_economic_notional += economic_notional
pos.sell_notional += raw_notional
pos.sell_economic_notional += economic_notional

delta.traded_notional += raw_notional
delta.traded_economic_notional += economic_notional
delta.buy_notional += raw_notional
delta.buy_economic_notional += economic_notional
delta.sell_notional += raw_notional
delta.sell_economic_notional += economic_notional
```

The existing raw columns keep their historical meaning. New economic columns are
the multiplier-adjusted values used for exposure and economic reporting.

### 7.2 avg_cost does NOT change

The VWAP avg_cost formula is price-per-unit, so multiplier must NOT enter it:

```python
# Adding to existing position — CORRECT as-is, do not change
existing_notional = pos.avg_cost * abs(pos.net_qty)
incoming_notional = float(price) * qty
pos.avg_cost = (existing_notional + incoming_notional) / abs(pos.net_qty)
```

This keeps `avg_cost` in the same units as `price` so the subtraction
`(price - avg_cost)` is meaningful before multiplying by `contract_multiplier`.

### 7.3 `_Position` and `_BatchDelta` dataclass additions

Both need a `contract_multiplier: int = 1` field and separate economic notional
fields. The apply_leg method receives `contract_multiplier` from the caller:

```python
def _apply_leg(
    self,
    *,
    gateway_id: str,
    symbol: str,
    price: int,
    tick_decimals: int,
    contract_multiplier: int,   # NEW
    quantity: int,
    is_buy: bool,
    ts_ns: int,
    trade_date: str,
) -> None:
    pos = self._positions.setdefault(
        (gateway_id, symbol),
        _Position(gateway_id=gateway_id, symbol=symbol)
    )
    pos.tick_decimals = tick_decimals
    if pos.contract_multiplier != contract_multiplier and (
        pos.net_qty != 0 or pos.buy_qty or pos.sell_qty
    ):
        raise ValueError(
            f"contract_multiplier changed for {gateway_id}/{symbol}: "
            f"{pos.contract_multiplier} -> {contract_multiplier}"
        )
    pos.contract_multiplier = contract_multiplier
    ...
```

Reject multiplier changes once accounting state exists for a gateway/symbol.
Silently storing the latest multiplier would mix economic units in one position.

### 7.4 Ledger.apply_trade signature addition

```python
def apply_trade(
    self,
    *,
    symbol: str,
    buy_gateway_id: str,
    sell_gateway_id: str,
    price: int,
    tick_decimals: int = 2,
    contract_multiplier: int = 1,   # NEW
    quantity: int,
    ts_ns: int,
    ingest_ts_ns: int,
) -> None:
```

Called from `clearing/main.py` flush path with the value from `trade.contract_multiplier`.

## 8. Statistics Module Deep Analysis

### 8.1 OHLCV — no change required

`open_price`, `high_price`, `low_price`, `close_price` are prices. Multiplier
does not affect their values. No code change needed.

### 8.2 VWAP — no change required (mathematical proof)

Current code in `_DayAccum.on_trade`:

```python
self._pv_sum += price * qty
self._q_sum += qty
# VWAP = self._pv_sum / self._q_sum
```

If we applied multiplier: `Σ(p × q × m) / Σ(q × m) = m × Σ(p × q) / (m × Σq)`.
The `m` cancels. **Conclusion: the VWAP code is correct as-is.** Do not modify it.

### 8.3 `trade_log` table — add `contract_multiplier`

`trade_log` stores `price` as the display value received from `trade.executed`.
This is a factual record of the execution price, not an economic notional.
The `price` column is correct as-is. `quantity` is count of contracts.

However, for audit reconstruction the row must also store
`contract_multiplier`. Without it, historical economic notional cannot be
reconstructed from the trade log alone unless the exact symbol configuration at
execution time is available elsewhere.

### 8.4 What the stats module is missing

The stats module does not currently compute any economic notional field. This
is a limitation but not a bug. Adding economic notional to stats is an optional
future enhancement that would require:

- Receiving and persisting `contract_multiplier` from `trade.executed`.
- Adding a `notional` or `economic_volume` column to `daily_stats`.
- This is deferred beyond v1; the required raw material is preserved in
    `trade_log.contract_multiplier`.

### 8.5 Summary of stats changes

| Component | Change needed? | Reason |
|---|---|---|
| OHLCV accumulation | No | Price-based metrics; multiplier cancels |
| VWAP | No | Multiplier cancels mathematically |
| `trade_log.price` | No | Record the execution price, not notional |
| `trade_log.quantity` | No | Contract count is correct |
| `trade_log.contract_multiplier` | Yes | Required for self-contained audit reconstruction |
| Economic notional in stats | Optional Phase 3 | New column, additive change |

## 9. Risk Controls: Collars and Circuit Breakers

### 9.1 Price collars — no code change required

From `src/edumatcher/engine/collar.py`:

```python
static_upper = int(ref * (1 + collar.static_band_pct))
static_lower = int(ref * (1 - collar.static_band_pct))
```

Both sides are in integer ticks. The test `static_lower <= price <= static_upper`
is a pure price-range check. Multiplier does not enter this calculation.

**Important operator advisory**: for a high-multiplier contract, a 20% static
band on a contract worth $100,000 implies allowing a $20,000 single-order
price error. Operators configuring `engine_config.yaml` for futures-like
symbols should use tighter collar bands than they would for equities. This is
a documentation and training concern, not a code change.

### 9.2 Circuit breakers — no code change required

From `src/edumatcher/engine/circuit_breaker.py`:

```python
shift = abs(price - ref) / ref if ref > 0 else 0.0
for level in sorted(self.config.levels, key=lambda lvl: lvl.price_shift_pct):
    if shift >= level.price_shift_pct:
        fired_level = level
```

`shift` is a dimensionless ratio of prices. Multiplier cancels. No change needed.

Same advisory applies: threshold calibration for high-multiplier symbols warrants
tighter thresholds to limit notional exposure per halt event.

## 10. Index Calculation Impact

The cap-weighted index formula is:

```
index_level = Σ(price_i × outstanding_shares_i) / divisor
```

This uses prices and share counts. Contract multiplier is a derivative
valuation concept that does not apply to index calculation.

**No change required to `pm-index` or its calculation logic.**

Future caveat: if a futures contract were added as a synthetic constituent,
the index methodology would need an explicit policy decision. That is outside
the scope of this design.

## 11. Process-by-Process Impact Analysis

### 11.1 `pm-engine`

| What changes | File | Details |
|---|---|---|
| Config loader | `engine/config_loader.py` | Parse, validate, default `contract_multiplier` in `SymbolConfig` |
| Trade publish | `engine/main.py` | Add `contract_multiplier` to `_publish_trade` payload |
| Symbols reply | `engine/main.py` | Add `contract_multiplier` to symbol metadata in `_handle_symbols_request` |

### 11.2 `pm-clearing`

| What changes | File | Details |
|---|---|---|
| Trade model | `models/trade.py` | Add `contract_multiplier` field |
| Ingest normalization | `clearing/main.py` | Parse from payload in `_trade_from_payload` |
| Trade event row | `clearing/store.py` | Add `contract_multiplier` column, dataclass field, insert/query |
| Position row | `clearing/store.py` | Add `contract_multiplier` column |
| Daily summary row | `clearing/store.py` | Add `contract_multiplier` column |
| P&L formulas | `clearing/ledger.py` | See Section 7 — four formula changes |
| Economic notional accumulation | `clearing/ledger.py` | Preserve raw notional columns; add multiplier-adjusted economic columns |
| Multiplier invariants | `clearing/ledger.py` | Reject a multiplier change once a gateway/symbol position or daily row has state |
| Console P&L table | `clearing/main.py` | Display P&L already includes multiplier after ledger calculation |
| Schema migration | `clearing/store.py` | `_add_column_if_missing` for new columns |

### 11.3 `pm-clearing-cli`

| What changes | File | Details |
|---|---|---|
| Column lists | `clearing/cli.py` | Add `contract_multiplier` and economic notional columns to `_POSITIONS_COLS`, `_TRADES_COLS`, etc |
| Normalization | `clearing/cli.py` | Raw columns divide only by tick scale; economic columns divide by tick scale after ledger/store multiplication |

**Critical note on CLI normalization**: existing raw notional columns retain
their current meaning and are normalized only by `10^tick_decimals`.
Economic notional columns are separately stored as raw ticks multiplied by
`contract_multiplier`, then normalized by `10^tick_decimals` for display/export.
The CLI must not multiply economic fields again.

For exposure-style output, keep any existing raw `gross_notional` meaning as
`ABS(net_qty × mark_price)`. Add a separate economic exposure value computed as
`ABS(net_qty × mark_price × contract_multiplier)` and normalize it by tick scale
for display/export.

### 11.4 `pm-stats`

- OHLCV and VWAP accumulation do not change (see Section 8).
- `trade_log` must add `contract_multiplier INTEGER NOT NULL DEFAULT 1` and
    persist the value from `trade.executed` for audit reconstruction.
- Optional future enhancement: add `economic_notional` or `economic_volume` to
    `daily_stats`. This is not required for v1.

### 11.5 `pm-alf-console` and `pm-alf-gwy`

- No order-entry semantic change.
- `SYMBOLS` command response now includes `contract_multiplier` in metadata
    (engine change above).
- `order.fill.{GW_ID}` payloads include `contract_multiplier`.
- `pm-alf-console` must apply multiplier in its local realized P&L tracker and
    should display multiplier in symbol metadata where practical.
- `pm-alf-gwy` should forward the new fill field unchanged to ALF sessions.

### 11.6 `pm-api-gwy`

- The `/symbols` endpoint payload comes from `system.symbols.{GW_ID}`.
- Once engine emits `contract_multiplier` in `symbol_meta`, the existing symbol
    cache can carry it, but endpoint schemas/docs must list it explicitly.
- The `/market-data` WebSocket forwards `trade.executed` payload as-is.
  `contract_multiplier` will appear automatically once the engine adds it.
- The `/positions` endpoint currently exposes `symbol`, `net_qty`, and
    `last_price`. It should include `contract_multiplier` from cached symbol
    metadata so API clients can compute economic exposure.

### 11.7 `pm-mm-bot`

The bot uses `tick_size` and price-based spread. It reads `symbol_meta` on
startup. Current position limit is `--max-position` measured in contract count:

```python
if abs(new_qty) > self._max_position:
    return  # skip order
```

This is a quantity-based limit, not a notional limit. No change required for
correct bot operation.

**Advisory**: once `contract_multiplier` is in `symbol_meta`, operators of
high-multiplier bots must treat `--max-position` as a contract-count limit, not
an economic exposure limit. Add docs and verifier/config-generator warnings in
v1; `--max-notional` remains a future enhancement.

### 11.8 `pm-ai-trader` and `pm-ai-swarm`

Same pattern as `pm-mm-bot`. Position limits are quantity-based. No change
required for correctness. Same docs-and-warnings advisory applies.

### 11.9 `pm-board`, `pm-ticker`, `pm-viewer`, `pm-orders`

These processes display prices, quantities, and bid/ask from book events. No
economic notional is currently shown. No change required.

### 11.10 `pm-ralf-gwy` (post-trade dissemination)

RALF `EXEC` messages are built from `trade.executed` payloads using an explicit
field map. Add `MULT` to each `EXEC` event, sourced from
`payload["contract_multiplier"]` with default `1`. Do not add economic notional
in v1.

### 11.11 `pm-md-gwy` (market-data gateway)

CALF `TRADE` messages are built by the market-data normaliser using an explicit
field map. Add `MULT` to the `TRADE` fields, sourced from
`payload["contract_multiplier"]` with default `1`. Book/top-of-book messages do
not need multiplier.

### 11.12 `pm-index`

No change. See Section 10.

### 11.13 `pm-audit`

Records all messages verbatim. New field appears in the log automatically. No
change.

### 11.14 Engine drop copy

Engine drop copy publishes participant-scoped fill events on a dedicated socket
for clearing/risk consumers. Add `contract_multiplier` to `order.fill` drop-copy
payloads. Replay uses the stored payload, so no separate replay schema change is
needed once live payloads include the field.

## 12. Config Tooling: `pm-config-gen` and `pm-cverifier`

### 12.1 `pm-config-gen`

File: `src/edumatcher/config_gen/symbol_spec.py`

Add `contract_multiplier` field to symbol spec with default value 1.

File: `src/edumatcher/config_gen/cli_parser.py`

Add `contract_multiplier` as a recognized key in `--symbol-opts`:

```
--symbol-opts ESU6:tick_decimals=2,contract_multiplier=50
```

File: `src/edumatcher/config_gen/renderer.py`

Emit field in YAML output when it is not the default (1), or always when set
explicitly:

```yaml
ESU6:
  tick_decimals: 2
  contract_multiplier: 50
```

File: `src/edumatcher/config_gen/cli.py`

Add global default flag:

```
--contract-multiplier N   Default contract_multiplier for all symbols (default: 1)
```

### 12.2 `pm-cverifier`

File: `src/edumatcher/cverifier/layer2_schema.py`

Add a new check function, modelled after `_check_symbol_tick_decimals`:

```python
def _check_symbol_contract_multiplier(
    sym: str, cfg: dict[str, Any], results: list[CheckResult]
) -> None:
    val = cfg.get("contract_multiplier")
    if val is None:
        return  # not set — defaults to 1, no error
    if isinstance(val, bool) or not isinstance(val, int):
        results.append(
            CheckResult(
                severity=Severity.ERROR,
                message=f"Symbol '{sym}': contract_multiplier must be a positive integer.",
                suggestion=f"    symbols:\n      {sym}:\n        contract_multiplier: 50",
                path=f"symbols.{sym}.contract_multiplier",
            )
        )
        return
    as_int = val
    if as_int <= 0:
        results.append(
            CheckResult(
                severity=Severity.ERROR,
                message=f"Symbol '{sym}': contract_multiplier must be > 0, got {as_int}.",
                suggestion=f"    symbols:\n      {sym}:\n        contract_multiplier: 1",
                path=f"symbols.{sym}.contract_multiplier",
            )
        )
    elif as_int > 10_000:
        results.append(
            CheckResult(
                severity=Severity.WARN,
                message=(
                    f"Symbol '{sym}': contract_multiplier={as_int} is unusually large. "
                    "Verify this is intentional."
                ),
                suggestion="Double-check the contract specification.",
                path=f"symbols.{sym}.contract_multiplier",
            )
        )
```

Call site — add alongside the existing checks in the symbol loop:

```python
_check_symbol_tick_decimals(sym, cfg, results)
_check_symbol_outstanding_shares(sym, cfg, results)
_check_symbol_contract_multiplier(sym, cfg, results)   # NEW
```

Include `contract_multiplier` in the effective config summary output in the risk
summary printer so operators can verify intent.

## 13. Complete Code Change Manifest

A developer implementing this feature should touch these files:

| File | Change type | Section reference |
|---|---|---|
| `src/edumatcher/engine/config_loader.py` | Add `contract_multiplier` field and parsing | §5.2 |
| `src/edumatcher/engine/main.py` | Add field to `_publish_trade`, `_handle_symbols_request`, private fill emissions, and drop-copy payloads | §6.1, §6.2, §6.5 |
| `src/edumatcher/models/message.py` | Add `contract_multiplier` to `make_fill_msg()` | §6.5 |
| `src/edumatcher/models/trade.py` | Add `contract_multiplier` field | §6.3 |
| `src/edumatcher/clearing/main.py` | Parse from payload in `_trade_from_payload` | §6.4 |
| `src/edumatcher/clearing/ledger.py` | Four P&L formula changes; new economic notional accumulator changes; multiplier invariant; field additions | §7 |
| `src/edumatcher/clearing/store.py` | Schema migration; dataclass fields; insert/upsert SQL | §14 |
| `src/edumatcher/clearing/cli.py` | Add column to output column lists | §11.3 |
| `src/edumatcher/stats/main.py` | Persist `contract_multiplier` in `trade_log` | §8.3, §11.4 |
| `src/edumatcher/alf_console/main.py` | Apply multiplier in local realized P&L tracker | §6.5, §11.5 |
| `src/edumatcher/alf_console/display.py` | Display multiplier in symbol metadata where practical | §11.5 |
| `src/edumatcher/alf_gwy/gateway.py` | Forward multiplier on private fill payloads | §11.5 |
| `src/edumatcher/api_gateway/routers/reference.py` | Include multiplier in `/positions` response | §11.6 |
| `src/edumatcher/api_gateway/schemas.py` | Document typed API responses where applicable | §11.6 |
| `src/edumatcher/ralf_gateway/gateway.py` | Add `MULT` to `EXEC` messages | §6.6, §11.10 |
| `src/edumatcher/md_gateway/normaliser.py` | Add `MULT` to CALF `TRADE` messages | §6.6, §11.11 |
| `src/edumatcher/config_gen/symbol_spec.py` | Add field and default | §12.1 |
| `src/edumatcher/config_gen/cli_parser.py` | Allow in `--symbol-opts` | §12.1 |
| `src/edumatcher/config_gen/renderer.py` | Emit in YAML output | §12.1 |
| `src/edumatcher/config_gen/cli.py` | Add global `--contract-multiplier` flag | §12.1 |
| `src/edumatcher/cverifier/layer2_schema.py` | Add `_check_symbol_contract_multiplier` | §12.2 |
| `src/edumatcher/cverifier/risk_summary.py` | Surface multiplier and notional-risk advisory | §12.2 |

**Files that do NOT need changes:**

| File | Reason |
|---|---|
| `engine/collar.py` | Pure price math; multiplier cancels |
| `engine/circuit_breaker.py` | Pure price-ratio math; multiplier cancels |
| `index/*` | Cap-weighted price/share math; see Section 10 |
| `clearing/ledger.py` (avg_cost) | Intentionally excluded; see Section 7.2 |
| `mm_bot/bot.py` | Quantity-based limits; no change needed |
| `ai_trader/main.py` | Quantity-based limits; no change needed |

## 14. SQLite Schema Migrations

All three clearing tables need `contract_multiplier` plus separate economic
notional columns. The migration uses the existing
`_add_column_if_missing` helper already in `src/edumatcher/clearing/store.py`:

```python
def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_PRAGMAS)
    conn.executescript(SCHEMA)
    _add_column_if_missing(
        conn, "trade_events", "tick_decimals", "INTEGER NOT NULL DEFAULT 2"
    )
    _add_column_if_missing(
        conn, "trade_events", "contract_multiplier", "INTEGER NOT NULL DEFAULT 1"  # NEW
    )
    _add_column_if_missing(
        conn, "gateway_symbol_positions", "tick_decimals", "INTEGER NOT NULL DEFAULT 2"
    )
    _add_column_if_missing(
        conn, "gateway_symbol_positions", "contract_multiplier", "INTEGER NOT NULL DEFAULT 1"  # NEW
    )
    _add_column_if_missing(
        conn, "gateway_symbol_positions", "buy_economic_notional", "INTEGER NOT NULL DEFAULT 0"  # NEW
    )
    _add_column_if_missing(
        conn, "gateway_symbol_positions", "sell_economic_notional", "INTEGER NOT NULL DEFAULT 0"  # NEW
    )
    _add_column_if_missing(
        conn, "gateway_daily_summary", "tick_decimals", "INTEGER NOT NULL DEFAULT 2"
    )
    _add_column_if_missing(
        conn, "gateway_daily_summary", "contract_multiplier", "INTEGER NOT NULL DEFAULT 1"  # NEW
    )
    _add_column_if_missing(
        conn, "gateway_daily_summary", "traded_economic_notional", "INTEGER NOT NULL DEFAULT 0"  # NEW
    )
    _add_column_if_missing(
        conn, "gateway_daily_summary", "buy_economic_notional", "INTEGER NOT NULL DEFAULT 0"  # NEW
    )
    _add_column_if_missing(
        conn, "gateway_daily_summary", "sell_economic_notional", "INTEGER NOT NULL DEFAULT 0"  # NEW
    )
    _add_column_if_missing(
        conn, "gateway_daily_summary", "economic_net_amount", "INTEGER NOT NULL DEFAULT 0"  # NEW
    )
```

This is a backward-compatible migration: existing databases get the new column
and economic columns with default multiplier 1 / value 0, which preserves their
existing raw-column semantics exactly.

### 14.1 Updated SCHEMA constant additions

In `trade_events`:
```sql
tick_decimals      INTEGER NOT NULL DEFAULT 2,
contract_multiplier INTEGER NOT NULL DEFAULT 1,
```

In `gateway_symbol_positions`:
```sql
tick_decimals       INTEGER NOT NULL DEFAULT 2,
contract_multiplier INTEGER NOT NULL DEFAULT 1,
buy_economic_notional  INTEGER NOT NULL DEFAULT 0,
sell_economic_notional INTEGER NOT NULL DEFAULT 0,
```

In `gateway_daily_summary`:
```sql
tick_decimals       INTEGER NOT NULL DEFAULT 2,
contract_multiplier INTEGER NOT NULL DEFAULT 1,
traded_economic_notional INTEGER NOT NULL DEFAULT 0,
buy_economic_notional    INTEGER NOT NULL DEFAULT 0,
sell_economic_notional   INTEGER NOT NULL DEFAULT 0,
economic_net_amount      INTEGER NOT NULL DEFAULT 0,
```

### 14.2 Reconcile integrity

`query_reconcile` must continue to compare raw event notional against raw daily
summary notional:

```sql
SUM(quantity * price) AS raw_buy_notional
```

It should additionally compare economic event notional against economic daily
summary notional:

```sql
SUM(quantity * price * contract_multiplier) AS economic_buy_notional
```

Apply the same pattern to sell notional, traded notional, raw net amount, and
economic net amount. Reconcile integrity is maintained because raw and economic
values are checked independently instead of reinterpreting existing columns.

## 15. Worked Example: `ESU6` with Multiplier 50

This example shows exact numbers before and after the fix.

### Setup

```yaml
symbols:
  ESU6:
    tick_decimals: 2
    contract_multiplier: 50
```

Gateway `GW_A` trades:
1. BUY 3 contracts at 5325.00
2. SELL 2 contracts at 5340.00

### Step 1: BUY 3 @ 5325.00 (price_ticks = 532500)

**avg_cost computation** (unchanged):
```
avg_cost = 532500.0   (per unit)
net_qty  = +3
```

**Raw and economic notional accumulation (corrected)**:
```
buy_notional += 3 × 532500 = 1,597,500 raw tick-units
              = 1,597,500 / 100 = 15,975 price-units

buy_economic_notional += 3 × 532500 × 50 = 79,875,000 economic tick-units
                       = 79,875,000 / 100 = $798,750
```

**Without multiplier (current limitation):**
```
buy_notional += 3 × 532500 = 1,597,500 raw tick-units = 15,975 price-units
buy_economic_notional is unavailable
```
Economic exposure is missing.

**Unrealized P&L at mark = 5325.00 (corrected)**:
```
unrealized = 3 × (532500 - 532500) × 50 = 0
```

### Step 2: SELL 2 @ 5340.00 (price_ticks = 534000)

**avg_cost unchanged** (partial close, long):
```
avg_cost = 532500.0  (correct — not changed)
close_qty = 2
```

**Realized P&L (corrected)**:
```
realized = (534000 - 532500) × 2 × 50
         = 1500 × 2 × 50
         = 150,000 tick-units
         / 100 (tick_decimals=2) = $1,500
```

**Without multiplier (current bug)**:
```
realized = (534000 - 532500) × 2 = 3,000 tick-units / 100 = $30
```
Error: 50× too small. Should be $1,500 per standard ES contract economics.

**Remaining position: net_qty = +1 @ 5340 mark**

**Unrealized P&L (corrected)**:
```
unrealized = 1 × (534000 - 532500) × 50
           = 1500 × 50 = 75,000 tick-units / 100 = $750
```

**Without multiplier (current bug)**:
```
unrealized = 1 × (534000 - 532500) = 1500 / 100 = $15
```
Error: 50× too small.

### Summary table

| Field | Current (broken) | Corrected | Error |
|---|---|---|---|
| buy_notional | 15,975 price-units | 15,975 price-units | unchanged raw value |
| buy_economic_notional | unavailable | $798,750 | missing today |
| realized_pnl | $30 | $1,500 | 50× too small |
| unrealized_pnl | $15 | $750 | 50× too small |
| avg_cost | 532500 | 532500 | unchanged (correct) |
| net_qty | 1 | 1 | unchanged (correct) |

## 16. Test Scenarios

Each scenario should be a pytest test in
`tests/test_clearing_ledger_multiplier.py`:

| Scenario | Test name | Assertion |
|---|---|---|
| Multiplier = 1, single trade | `test_multiplier_1_passthrough` | All values match current behavior exactly |
| Multiplier = 50, buy and close | `test_multiplier_50_realized_pnl` | realized = (close - avg) × qty × 50 |
| Multiplier = 50, partial close | `test_multiplier_50_partial_close` | realized scaled; avg_cost unchanged |
| Multiplier = 50, cross-zero | `test_multiplier_50_cross_zero` | P&L on close scaled; new side P&L also scaled |
| Multiplier = 50, raw notional preservation | `test_multiplier_50_raw_notionals_unchanged` | buy_notional = qty × price_ticks |
| Multiplier = 50, economic notional accumulation | `test_multiplier_50_economic_notionals` | buy_economic_notional = qty × price_ticks × 50 |
| Default (missing from payload) | `test_missing_multiplier_defaults_to_1` | Trade.from_dict without field → multiplier = 1 |
| Config omitted | `test_config_missing_defaults_to_1` | SymbolConfig without field → 1 |
| Config invalid (zero) | `test_config_zero_raises` | ValueError raised |
| Config invalid (negative) | `test_config_negative_raises` | ValueError raised |
| Config invalid (float) | `test_config_float_rejected` | `1.5` raises ValueError |
| Config invalid (fractional string) | `test_config_fractional_string_rejected` | `"1.5"` raises ValueError |
| Reconcile consistency | `test_reconcile_matches_with_multiplier` | raw and economic reconcile checks return no rows |
| Multiplier change rejected | `test_multiplier_change_rejected_for_existing_position` | open position with m=50 rejects later m=5 trade |
| Fill payload multiplier | `test_private_fill_includes_contract_multiplier` | `order.fill.{GW}` includes field |
| Drop-copy multiplier | `test_drop_copy_fill_includes_contract_multiplier` | drop-copy fill includes field |
| RALF multiplier | `test_ralf_exec_includes_mult` | `EXEC` includes `MULT` |
| CALF multiplier | `test_md_trade_includes_mult` | `TRADE` includes `MULT` |
| Stats trade log multiplier | `test_stats_trade_log_persists_multiplier` | `trade_log.contract_multiplier` is stored |
| Cverifier detects invalid | `test_cverifier_contract_multiplier_zero` | ERROR severity |
| Cverifier warns on large | `test_cverifier_contract_multiplier_large` | WARN at >10000 |

## 17. Additional Risks and Migration Considerations

### 17.1 Risk table

| Risk | Severity | Mitigation |
|---|---|---|
| Existing clearing.db has multiplier=1 data; actual contracts had multiplier>1 | High | Historical data cannot be retroactively corrected; document the upgrade cutover point clearly |
| Bot or risk guard is calibrated on notional thinking multiplier=1 | Medium | Advisory: re-calibrate `--max-position` as contracts after upgrade |
| Consumers hard-validate exact payload fields | Low | Multiplier has default in `from_dict`; new field is additive |
| Multiplier changes mid-position or mid-day | High | Reject the change instead of mixing economic units in one accounting row |
| Economic columns overflow SQLite INTEGER | Medium | Keep integer multiplier range warning and add tests around high-but-allowed values |
| Reconcile query misses economic drift | Medium | Reconcile raw and economic aggregates independently |
| Float multiplier supplied by user | Low | Reject explicitly; v1 is integer-only |

### 17.2 Cutover approach

Because historical clearing data cannot be retroactively multiplied with full
confidence:

- Tag the upgrade with a migration event in documentation.
- Existing raw notional columns retain their historical meaning.
- Existing economic notional columns added during migration default to 0 because
    the historical multiplier at execution time is unknown.
- New rows after upgrade are immediately correct when `contract_multiplier` is
    present in `trade.executed`.

### 17.3 Unit labeling

The CLI should label raw and economic columns clearly. After normalization,
raw notional columns are price-units and economic notional/P&L columns are
display-currency units under EduMatcher's implicit single-currency assumption.
Consider adding a `(MULT != 1)` header note when non-1 multipliers are present.

## 18. Documentation Update Plan

| Document | Change |
|---|---|
| `docs/user-guide/01-configuration.md` | Add `contract_multiplier` to symbol config table and `--symbol-opts` reference |
| `docs/user-guide/09-messages.md` | Add `contract_multiplier` to `trade.executed`, `system.symbols`, private fills, and drop copy; add `MULT` to RALF/CALF examples |
| `docs/user-guide/10-processes.md` | Note multiplier in pm-clearing-cli section |
| `docs/user-guide/07-pnl-clearing.md` | Update formulas; explain multiplier effect on P&L |
| `docs/user-guide/16-statistics-and-reporting.md` | Note VWAP invariance; note trade_log records price not notional |
| `docs-design/EduMatcher-Cleaaring.md` | Update schema tables and SQL blueprints |
| `docs-design/EduMatcher-contract-multiplyer.md` | This document — v1.2 update on completion |
| RALF/CALF protocol appendices | Add `MULT` to translated trade/execution message examples |

## 19. Iterative Implementation Plan

### Phase 1: Config and message plumbing

1. Add `contract_multiplier` to `SymbolConfig`.
2. Add parsing/validation in `config_loader.py`.
3. Add field to `Trade` model and serialization.
4. Extend `_publish_trade` in engine.
5. Extend `_handle_symbols_request` in engine.
6. Parse in `_trade_from_payload` in clearing.
7. Add multiplier to private fill and drop-copy payloads.
8. Add schema migration to clearing store and stats trade log.
9. Add `MULT` to RALF/CALF trade translations.
10. **Verify**: all 2189 existing tests still pass; clearing DB upgrades clean.

### Phase 2: Clearing P&L and storage

1. Add `contract_multiplier` to `_Position`, `_BatchDelta`, `PositionRow`, `DailySummaryRow`, `TradeEventRow`.
2. Add economic notional fields to `_Position`, `_BatchDelta`, `PositionRow`, and `DailySummaryRow`.
3. Apply multiplier to four P&L formulas and new economic notional accumulators.
4. Preserve existing raw notional accumulators unchanged.
5. Reject multiplier changes for an existing gateway/symbol accounting row.
6. Update `query_reconcile` in `store.py` for raw and economic checks.
7. Add `contract_multiplier` and economic notional fields to CLI column lists.
8. **Verify**: worked example test scenarios pass; reconcile returns zero rows.

### Phase 3: Config tooling

1. Update `pm-config-gen` symbol spec and renderer.
2. Add `--symbol-opts` key and global flag.
3. Add `_check_symbol_contract_multiplier` in cverifier.
4. **Verify**: generate config with multiplier; verify config shows no errors; wrong value shows error.

### Phase 4: Documentation and polish

1. Update all user-guide pages listed in Section 18.
2. Add CLI header annotation for non-1 multiplier result sets.
3. Document bot/trader max-position as contract count, not economic exposure.
4. Optional future work: add economic notional column to stats `daily_stats`.

## 20. Acceptance Checklist

- [ ] `contract_multiplier: 50` in YAML loads cleanly with no error.
- [ ] `contract_multiplier` absent in YAML resolves to 1 at runtime.
- [ ] `contract_multiplier: 0` in YAML raises `ValueError`.
- [ ] `contract_multiplier: 1.5` in YAML raises `ValueError`.
- [ ] `trade.executed` payload includes `contract_multiplier`.
- [ ] `system.symbols` metadata includes `contract_multiplier`.
- [ ] `order.fill.{GW_ID}` payloads include `contract_multiplier`.
- [ ] Engine drop-copy fill payloads include `contract_multiplier`.
- [ ] RALF `EXEC` messages include `MULT`.
- [ ] CALF `TRADE` messages include `MULT`.
- [ ] `Trade.from_dict` round-trips with and without the field.
- [ ] Clearing `trade_events` table has `contract_multiplier` column after migration.
- [ ] `gateway_symbol_positions` table has `contract_multiplier` column.
- [ ] `gateway_daily_summary` table has `contract_multiplier` column.
- [ ] Position and daily summary tables have economic notional columns.
- [ ] `pm-stats` `trade_log` has `contract_multiplier` column.
- [ ] Existing `clearing.db` without the column gets it added on startup (default 1).
- [ ] realized P&L for multiplier=50 is 50× greater than for multiplier=1 at same prices.
- [ ] avg_cost is identical regardless of multiplier (price-per-unit).
- [ ] unrealized P&L is 50× greater for multiplier=50.
- [ ] raw notional fields are unchanged by multiplier.
- [ ] economic notional fields are 50× greater for multiplier=50.
- [ ] `query_reconcile` returns no rows after raw and economic checks for multiplier=50 trades.
- [ ] A multiplier change for an existing gateway/symbol accounting row is rejected.
- [ ] VWAP in `pm-stats` is unchanged by multiplier.
- [ ] `trade_log.contract_multiplier` persists the event multiplier.
- [ ] Collar check: same order passes or fails regardless of multiplier.
- [ ] Circuit breaker: same price move triggers the same level regardless of multiplier.
- [ ] pm-cverifier reports ERROR on `contract_multiplier: 0`.
- [ ] pm-cverifier reports WARN on `contract_multiplier: 20000`.
- [ ] pm-cverifier reports no issue on omitted `contract_multiplier`.
- [ ] pm-config-gen emits `contract_multiplier: 50` when `--symbol-opts SYM:contract_multiplier=50` passed.
- [ ] Full suite (`2189` tests) passes unchanged before Phase 1 begins.
- [ ] New multiplier-specific tests pass after Phase 2.

## 21. Resolved Design Decisions

1. **Multiplier type**: v1 supports positive integers only. Floats, bools,
    fractional numeric strings, zero, and negative values are invalid.

2. **Existing notional column semantics**: existing notional columns remain raw
    `price_ticks × qty` values. New economic notional columns store
    `price_ticks × qty × contract_multiplier`.

3. **Effective-date tracking**: v1 does not implement effective dating. If a
    multiplier changes while a gateway/symbol has existing position or daily
    accounting state, the process rejects the event instead of mixing units.

4. **Bot notional limits**: v1 does not add `--max-notional`. Documentation and
    verifier/config-generator output must warn that bot/trader max-position values
    are contract-count limits, not economic exposure limits.

5. **Symbol metadata defaults**: `system.symbols` emits `contract_multiplier`
    even when the value is the default `1`, so consumers can remain stateless.

6. **External protocol fields**: RALF `EXEC` and CALF `TRADE` emit `MULT`. They do
    not emit economic notional in v1.


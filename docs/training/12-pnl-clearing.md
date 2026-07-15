# P&L & Clearing

## Objective

Understand how the DB-backed clearing process tracks positions, computes VWAP
average cost, and reports realized and unrealized P&L per trader per symbol.
Gain hands-on proficiency with every `pm-clearing-cli` command verb through
intraday, end-of-day, and operational exercises.

## Prerequisites

- Chapters 01–11 completed.
- Live trading activity available (manual trading, AI traders, or both).

## Background

### What pm-clearing stores

`pm-clearing` subscribes to `trade.executed` events and persists all state in
`clearing.db` (SQLite WAL mode). There is no CSV artifact — everything is in
the database.

| Table | Purpose |
|---|---|
| `trade_events` | Append-only trade audit log |
| `gateway_symbol_positions` | Running live position per gateway/symbol |
| `gateway_daily_summary` | Daily rollup aggregates |
| `session_events` | EOD sentinel rows written on `system.eod` |
| `gateway_sessions` | Gateway connect/disconnect history |

### What pm-clearing maintains per position

- **net_qty** — signed quantity (positive = long, negative = short, 0 = flat)
- **avg_cost** — VWAP of entry prices (per unit; never multiplied by quantity)
- **realized_pnl** — profit/loss locked in by closing or crossing trades
- **unrealized_pnl** — paper profit/loss: `net_qty × (mark_price − avg_cost)`

### Position state machine

A position starts flat and transitions as fills arrive:

```
Flat → Long  (BUY fill opens a long)
Flat → Short (SELL fill opens a short)
Long → Flat  (SELL fill closes the full position, close_qty == net_qty)
Long → Short (SELL fill exceeds net_qty — cross-zero)
Short → Flat (BUY fill closes the full position)
Short → Long (BUY fill exceeds abs(net_qty) — cross-zero)
```

A cross-zero fill realizes P&L on the closing portion and sets `avg_cost` to
the fill price for the newly-opened side.

---

## Part A — Intraday exercises

### Exercise 1: Start the clearing service

```bash
pm-clearing
```

Expected:

```
[INFO] Clearing connected - listening for trade events
```

:material-checkbox-blank-outline: **Checkpoint:** clearing service is running.

---

### Exercise 2: Check DB health

In a second terminal:

```bash
pm-clearing-cli health
```

Expected: one row showing the DB path, row counts for each table, the last
trade and last flush timestamps, and `wal_mode` enabled.

Run `health` again after a few trades to see the row counts grow.

:material-checkbox-blank-outline: **Checkpoint:** `health` returns a row with WAL mode enabled.

---

### Exercise 3: Build a long position and query it

From TRADER01:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=200
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
```

Query the position:

```bash
pm-clearing-cli positions --gateway TRADER01 --symbol AAPL
```

Confirm:

- `net_qty` ≈ 300
- `avg_cost` is the VWAP of the two fills (not the last price alone)
- `buy_qty` is 300, `sell_qty` is 0

Query all open positions across every gateway and symbol:

```bash
pm-clearing-cli positions
```

:material-checkbox-blank-outline: **Checkpoint:** `positions` shows the AAPL long for TRADER01 with correct VWAP avg_cost.

---

### Exercise 4: Inspect the raw trade event log

```bash
pm-clearing-cli trades --gateway TRADER01 --symbol AAPL --limit 10
```

Each row is one matched fill. Observe: `id`, `trade_date`, `symbol`,
`quantity`, `price`, `tick_decimals`, `buy_gateway_id`, `sell_gateway_id`,
`aggressor_side`.

Switch format to JSON:

```bash
pm-clearing-cli --format json trades --gateway TRADER01 --symbol AAPL --limit 3
```

Export all trades for a date to CSV for a spreadsheet:

```bash
pm-clearing-cli --format csv trades --date 2026-07-05 > trades_today.csv
```

:material-checkbox-blank-outline: **Checkpoint:** you can retrieve fills in table, JSON, and CSV formats.

---

### Exercise 5: Realize P&L by partially closing

Sell part of the AAPL position:

```
TRADER01> NEW|SYM=AAPL|SIDE=SELL|TYPE=MARKET|QTY=100
```

Expected accounting:

```
realized_pnl += (sell_price - avg_cost) x 100
net_qty = 200
```

Query:

```bash
pm-clearing-cli pnl --gateway TRADER01 --symbol AAPL
```

Confirm `realized_pnl` is non-zero and `total_pnl = realized_pnl + unrealized_pnl`.

Query the exchange-wide P&L across every gateway in one row per gateway:

```bash
pm-clearing-cli pnl
```

:material-checkbox-blank-outline: **Checkpoint:** `pnl` shows realized P&L on the partial close.

---

### Exercise 6: Cross-zero position

This is the most complex accounting path. Starting from the 200-share AAPL long:

```
TRADER01> NEW|SYM=AAPL|SIDE=SELL|TYPE=MARKET|QTY=300
```

This single order closes all 200 long shares **and** opens a 100-share short.

Expected accounting after the cross:

```
realized_pnl += (sell_price - avg_cost) x 200   ← the closing portion
net_qty      = -100                              ← new short side
avg_cost     = sell_price                        ← reset to open price of new side
```

Verify:

```bash
pm-clearing-cli positions --gateway TRADER01 --symbol AAPL
pm-clearing-cli pnl      --gateway TRADER01 --symbol AAPL
```

Close the short:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
```

```bash
pm-clearing-cli pnl --gateway TRADER01 --symbol AAPL
```

Position should return to flat (`net_qty = 0`) with `realized_pnl` reflecting
both the original long close and the short round-trip.

:material-checkbox-blank-outline: **Checkpoint:** cross-zero P&L is realized correctly on the closing portion.

---

### Exercise 7: Exposure — net and gross notional

With a few positions open across symbols:

```bash
pm-clearing-cli exposure
```

Default sort is `gross_notional` (largest exposure first). Try other sorts:

```bash
pm-clearing-cli exposure --sort total_pnl
pm-clearing-cli exposure --sort net_notional
```

Fields include `net_qty`, `mark_price`, `net_notional`, `gross_notional`,
`realized_pnl`, `unrealized_pnl`, `total_pnl`.

This is the clearing house **risk concentration view**: a large `gross_notional`
with small `net_notional` means a participant is running offsetting positions that
could unwind rapidly.

:material-checkbox-blank-outline: **Checkpoint:** you can rank all positions by exposure and P&L.

---

### Exercise 8: Gateway-level P&L summary

To see every participant's P&L in a single query:

```bash
pm-clearing-cli gateways
```

Output: one row per gateway with `realized_pnl_total`, `unrealized_pnl_total`,
`total_pnl`, `net_qty_total`.

Filter to one participant:

```bash
pm-clearing-cli gateways --gateway TRADER01
```

Export for downstream reporting:

```bash
pm-clearing-cli --format csv gateways > gateway_pnl.csv
pm-clearing-cli --format json gateways > gateway_pnl.json
```

This is the clearing house **top-level risk snapshot**: one row per participant,
usable without knowing which symbols they traded.

:material-checkbox-blank-outline: **Checkpoint:** `gateways` returns a P&L summary row for each active participant.

---

### Exercise 9: Symbol-level clearing totals

Query what was cleared per symbol across all gateways:

```bash
pm-clearing-cli symbols
```

Sort by traded volume or P&L:

```bash
pm-clearing-cli symbols --sort traded_qty
pm-clearing-cli symbols --sort realized_pnl
```

Fields include `symbol`, `traded_qty`, `traded_notional`, `realized_pnl`,
`open_net_qty`, `open_unrealized_pnl`.

:material-checkbox-blank-outline: **Checkpoint:** `symbols` shows per-symbol volume and P&L across all participants.

---

### Exercise 10: Normalized vs raw-output

By default, price-derived fields are divided by `10^tick_decimals` to produce
display-currency units. Use `--raw-output` to see the raw integer tick values:

```bash
pm-clearing-cli positions --gateway TRADER01 --symbol AAPL
pm-clearing-cli --raw-output positions --gateway TRADER01 --symbol AAPL
```

Rules:
- `avg_cost` is **never** raw-normalized (it is already computed as a REAL ratio)
- Fields like `mark_price`, `realized_pnl`, `unrealized_pnl`, `buy_notional`, `sell_notional` are normalized by default

Use `--raw-output` when piping into scripts that expect tick integers, or when
debugging a suspected normalization issue.

:material-checkbox-blank-outline: **Checkpoint:** you can explain which fields are normalized and why `--raw-output` exists.

---

## Part B — End-of-day exercises

End-of-day (EOD) is when the clearing house finalizes marks, settles daily P&L,
and prepares tomorrow's opening state. `pm-clearing` handles this automatically
when the engine sends `system.eod`, but as a clearing operator you need to
verify and audit the result.

### What happens at EOD

When `pm-clearing` receives `system.eod`:

1. **Force-flushes** any buffered trades immediately
2. Applies official EOD **mark-to-market** using last-trade price (or mid-price
   if no trade occurred) to update `mark_price` and `unrealized_pnl`
3. Writes updated positions to `gateway_symbol_positions` so
   `end_unrealized_pnl` in `gateway_daily_summary` reflects the official EOD mark
4. Inserts an `EOD` sentinel row into `session_events`

---

### Exercise 11: Verify EOD sentinel

After a session is closed (engine shut down gracefully):

```bash
pm-clearing-cli eod --limit 5
```

Each row shows the timestamp and a `payload_json` containing the mark prices
applied. The `eod` sentinel is proof that marks were applied.

:material-checkbox-blank-outline: **Checkpoint:** `eod` returns at least one row with mark prices in `payload_json`.

---

### Exercise 12: Inspect daily rollup

Query the official daily summary for today:

```bash
pm-clearing-cli daily --date 2026-07-05
```

Filter to one gateway:

```bash
pm-clearing-cli daily --date 2026-07-05 --gateway TRADER01
```

Key fields:
- `traded_qty`, `traded_notional` — total volume for the day
- `buy_qty`, `sell_qty`, `buy_notional`, `sell_notional` — side breakdown
- `end_net_qty`, `end_avg_cost`, `end_unrealized_pnl` — official EOD position state

Export the day's summary for settlement reporting:

```bash
pm-clearing-cli --format csv daily --date 2026-07-05 > daily_settlement_2026-07-05.csv
```

Query across multiple days:

```bash
pm-clearing-cli daily --from 2026-07-01 --to 2026-07-05 --gateway TRADER01
```

:material-checkbox-blank-outline: **Checkpoint:** daily rollup contains `end_*` fields populated by the EOD mark pass.

---

### Exercise 13: Browse available trading dates

```bash
pm-clearing-cli dates
```

Add volume and net-amount totals per date:

```bash
pm-clearing-cli dates --with-totals
```

Filter by symbol to see on which days that symbol traded:

```bash
pm-clearing-cli dates --symbol AAPL
```

:material-checkbox-blank-outline: **Checkpoint:** you can navigate which dates have clearing data.

---

### Exercise 14: Reconciliation check

After EOD, verify that raw `trade_events` aggregates match `gateway_daily_summary`:

```bash
pm-clearing-cli reconcile --from 2026-07-05 --to 2026-07-05
```

Expected:
- `OK — no discrepancies found.` when consistent
- Rows showing side / date / gateway / symbol / quantity-diff / notional-diff if not

Reconcile across the whole week:

```bash
pm-clearing-cli reconcile --from 2026-07-01 --to 2026-07-05
```

If discrepancies appear, use `trades` to investigate the affected gateway/symbol/date.

:material-checkbox-blank-outline: **Checkpoint:** you can run a full reconciliation and interpret the result.

---

### Exercise 15: Session history

Query gateway connect and disconnect events recorded during the session:

```bash
pm-clearing-cli sessions
```

Show only sessions that have not yet disconnected (still open):

```bash
pm-clearing-cli sessions --connected-only
```

This is the operational audit trail for: who connected, when, and whether
they disconnected cleanly or the engine was killed unexpectedly.

:material-checkbox-blank-outline: **Checkpoint:** `sessions` returns at least one row per gateway that connected today.

---

## Part C — Ongoing operations

### Exercise 16: Data retention and pruning

`pm-clearing` prunes old `trade_events` rows on startup. The default window is
90 days. Control it with `--retention-days`:

```bash
# Start clearing with 30-day retention
pm-clearing --retention-days 30
```

Use `pm-clearing-cli prune` for on-demand pruning without restarting:

```bash
# Dry run — see how many rows would be deleted
pm-clearing-cli prune --days 30 --dry-run

# Actually prune and VACUUM
pm-clearing-cli prune --days 30
```

Use `--dry-run` first to avoid unintended data loss.
`prune` is the only `pm-clearing-cli` verb that writes to the database.

:material-checkbox-blank-outline: **Checkpoint:** you can run a dry-run prune and interpret the row count.

---

## Key Formulas

| Metric | Formula |
|--------|---------|
| Average cost (long) | $\frac{\sum(\text{buy\_price} \times \text{buy\_qty})}{\sum \text{buy\_qty}}$ |
| Realized P&L (closing sell) | $(\text{sell\_price} - \text{avg\_cost}) \times \text{qty\_closed}$ |
| Unrealized P&L (long) | $(\text{mark\_price} - \text{avg\_cost}) \times \text{net\_qty}$ |
| Unrealized P&L (short) | $(\text{avg\_cost} - \text{mark\_price}) \times |\text{net\_qty}|$ |
| Cross-zero realized | $(\text{fill\_price} - \text{avg\_cost}) \times |\text{old\_net\_qty}|$ |

---

## pm-clearing-cli verb reference

| Verb | What it returns | Key options |
|---|---|---|
| `gateways` | One row per gateway: total realized, unrealized, total P&L | `--gateway`, `--limit` |
| `positions` | Full live position state per gateway/symbol | `--gateway`, `--symbol`, `--limit` |
| `pnl` | Focused P&L view (no qty/notional detail) | `--gateway`, `--symbol`, `--limit` |
| `trades` | Raw trade-level audit log | `--gateway`, `--symbol`, `--date`, `--from`, `--to`, `--limit` |
| `exposure` | Net/gross notional exposure, sorted by size | `--gateway`, `--symbol`, `--sort`, `--limit` |
| `symbols` | Symbol-level volume, notional, P&L | `--date`, `--from`, `--to`, `--sort` |
| `daily` | Daily rollup + EOD snapshots | `--gateway`, `--symbol`, `--date`, `--from`, `--to` |
| `dates` | Available trading dates | `--gateway`, `--symbol`, `--from`, `--to`, `--with-totals` |
| `health` | DB row counts, last flush, WAL mode | — |
| `reconcile` | Raw vs summary discrepancies | `--gateway`, `--symbol`, `--from`, `--to` |
| `sessions` | Gateway connect/disconnect history | `--gateway`, `--from`, `--to`, `--connected-only` |
| `eod` | EOD sentinel rows with mark prices | `--from`, `--to`, `--limit` |
| `prune` | Delete old `trade_events` + VACUUM (**writes**) | `--days`, `--dry-run` |

Global options apply to all verbs: `--format table|json|csv`, `--no-header`,
`--raw-output`, `--datapath PATH`, `--db-name NAME`.

---

## Reflection

Why does realized P&L use the trade price at the moment of the closing fill,
while unrealized P&L keeps recalculating against the current mark? In the
cross-zero scenario, why is realized P&L computed only on the closing portion
and not the new opening portion?

At end-of-day, which three `pm-clearing-cli` commands would you run in order
to: (1) confirm the EOD mark was applied, (2) export the official daily
settlement file, and (3) check the audit integrity of the day's clearing?

---

## Further Reading

- [P&L & Clearing](../user-guide/130-pnl-clearing.md)
- [Messages](../user-guide/270-messages.md)
- [Statistics and Reporting](../user-guide/140-statistics-and-reporting.md)
- [Your First Trade](../concepts/04-concepts-first-trade.md)

**Next:** [13 — Market Data & Drop Copy](13-market-data-drop-copy.md)

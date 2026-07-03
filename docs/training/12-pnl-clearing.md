# P&L & Clearing

## Objective

Understand how the clearing service tracks positions, computes VWAP average
cost, and reports realized and unrealized P&L per trader per symbol.

 

## Prerequisites

- Chapters 01–11 completed.
- Live trading activity available (manual trading, AI traders, or both).

 

## Background

`pm-clearing` subscribes to all `trade.executed` events and maintains:

- **Position** — net quantity (positive = long, negative = short).
- **Average cost** — VWAP of entry prices.
- **Realized P&L** — profit/loss locked in by closing trades.
- **Unrealized P&L** — paper profit/loss on open positions (mark-to-market).

 

## Exercise 1: Start the Clearing Service

```bash
pm-clearing
```

Expected:

```
[INFO] Clearing connected — listening for trade events
```

:material-checkbox-blank-outline: **Checkpoint:** clearing service running.

 

## Exercise 2: Build a Position

From TRADER01, buy AAPL shares:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=200
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
```

The clearing service records:

- Position: +300 AAPL
- Average cost: VWAP of the two fill prices

Verify with a command, not just the terminal log: inspect the CSV artifact
the clearing service appends on every trade:

```bash
tail -n 5 "$EDUMATCHER_DATA_DIR/clearing_report.csv"
```

You should see two new rows, one per fill, with `symbol=AAPL` and
`quantity` of 200 and 100 respectively (the CSV logs raw trades — `trade_id`,
`symbol`, `buy_order_id`, `sell_order_id`, `buy_gateway`, `sell_gateway`,
`price`, `quantity`, `timestamp` — it does not carry P&L, which is computed
separately per gateway/symbol in the clearing console's P&L Summary table).

:material-checkbox-blank-outline: **Checkpoint:** two new rows for AAPL appear in `clearing_report.csv` with quantities 200 and 100.

 

## Exercise 3: Realize Profit by Selling

Sell some shares (hopefully at a higher price after price moves):

```
TRADER01> NEW|SYM=AAPL|SIDE=SELL|TYPE=MARKET|QTY=100
```

The clearing service computes realized P&L:

```
Realized P&L = (sell_price - avg_cost) × qty_sold
```

Verify this from the clearing console's periodically-printed **P&L Summary**
table (not the CSV, which only logs raw trades): find the row for your
gateway/`AAPL` and confirm the `Realized` column now shows a non-zero value
matching the formula above.

:material-checkbox-blank-outline: **Checkpoint:** P&L Summary table shows a non-zero `Realized` value for AAPL matching the expected calculation.

 

## Exercise 4: Check Unrealized P&L

The remaining 200 shares have unrealized P&L based on the current market price:

```
Unrealized P&L = (current_mid - avg_cost) × position
```

This updates continuously as the book changes. Verify it the same way as
Exercise 3: in the clearing console's P&L Summary table, confirm the `AAPL`
row's `Position` column reads `+200` and its `Unrealized` column changes
value if you re-check after the market price moves.

:material-checkbox-blank-outline: **Checkpoint:** P&L Summary table shows AAPL position `+200` with an `Unrealized` value that changes as price moves.

 

## Exercise 5: Short Position

Sell shares you don't own:

```
TRADER01> NEW|SYM=MSFT|SIDE=SELL|TYPE=MARKET|QTY=100
```

Position becomes −100 MSFT (short). If price drops, unrealized P&L is positive.

Close by buying:

```
TRADER01> NEW|SYM=MSFT|SIDE=BUY|TYPE=MARKET|QTY=100
```

Position returns to 0; realized P&L reflects the round-trip.

:material-checkbox-blank-outline: **Checkpoint:** short position and close works correctly.

 

## Exercise 6: Multiple Symbols

Build positions in all three symbols and observe per-symbol and total P&L
tracking in the clearing output.

:material-checkbox-blank-outline: **Checkpoint:** clearing tracks each symbol independently.

 

## Key Formulas

| Metric | Formula |
|--------|---------|
| Average cost (long) | $\frac{\sum(\text{buy\_price} \times \text{buy\_qty})}{\sum \text{buy\_qty}}$ |
| Realized P&L (closing sell) | $(\text{sell\_price} - \text{avg\_cost}) \times \text{qty}$ |
| Unrealized P&L (long) | $(\text{mid\_price} - \text{avg\_cost}) \times \text{position}$ |
| Unrealized P&L (short) | $(\text{avg\_cost} - \text{mid\_price}) \times |\text{position}|$ |

 

## Reflection

Why does realized P&L use the trade price at the moment of the closing sell,
while unrealized P&L keeps recalculating against the current mid-price? What
would happen to your reported P&L if the clearing service stopped updating
`last_price` while the book kept trading?

## Further Reading

- [P&L & Clearing](../user-guide/07-pnl-clearing.md)
- [Messages](../user-guide/09-messages.md)
- [Statistics and Reporting](../user-guide/16-statistics-and-reporting.md)
- [Your First Trade](../concepts/04-concepts-first-trade.md)

 

**Next:** [13 — Market Data & Drop Copy](13-market-data-drop-copy.md)

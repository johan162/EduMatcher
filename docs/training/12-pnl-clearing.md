# 12 — P&L & Clearing

## Objective

Understand how the clearing service tracks positions, computes VWAP average
cost, and reports realized and unrealized P&L per trader per symbol.

---

## Background

`pm-clearing` subscribes to all `trade.executed` events and maintains:

- **Position** — net quantity (positive = long, negative = short).
- **Average cost** — VWAP of entry prices.
- **Realized P&L** — profit/loss locked in by closing trades.
- **Unrealized P&L** — paper profit/loss on open positions (mark-to-market).

---

## Exercise 1: Start the Clearing Service

```bash
pm-clearing
```

Expected:

```
[INFO] Clearing connected — listening for trade events
```

:material-checkbox-blank-outline: **Checkpoint:** clearing service running.

---

## Exercise 2: Build a Position

From TRADER01, buy AAPL shares:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=200
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
```

The clearing service records:

- Position: +300 AAPL
- Average cost: VWAP of the two fill prices

:material-checkbox-blank-outline: **Checkpoint:** position building confirmed in clearing logs.

---

## Exercise 3: Realize Profit by Selling

Sell some shares (hopefully at a higher price after price moves):

```
TRADER01> NEW|SYM=AAPL|SIDE=SELL|TYPE=MARKET|QTY=100
```

The clearing service computes realized P&L:

```
Realized P&L = (sell_price - avg_cost) × qty_sold
```

:material-checkbox-blank-outline: **Checkpoint:** realized P&L appears in clearing output.

---

## Exercise 4: Check Unrealized P&L

The remaining 200 shares have unrealized P&L based on the current market price:

```
Unrealized P&L = (current_mid - avg_cost) × position
```

This updates continuously as the book changes.

:material-checkbox-blank-outline: **Checkpoint:** unrealized P&L calculation understood.

---

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

---

## Exercise 6: Multiple Symbols

Build positions in all three symbols and observe per-symbol and total P&L
tracking in the clearing output.

:material-checkbox-blank-outline: **Checkpoint:** clearing tracks each symbol independently.

---

## Key Formulas

| Metric | Formula |
|--------|---------|
| Average cost (long) | $\frac{\sum(\text{buy\_price} \times \text{buy\_qty})}{\sum \text{buy\_qty}}$ |
| Realized P&L (closing sell) | $(\text{sell\_price} - \text{avg\_cost}) \times \text{qty}$ |
| Unrealized P&L (long) | $(\text{mid\_price} - \text{avg\_cost}) \times \text{position}$ |
| Unrealized P&L (short) | $(\text{avg\_cost} - \text{mid\_price}) \times |\text{position}|$ |

---

## Further Reading

- [P&L & Clearing](../user-guide/07-pnl-clearing.md)
- [Messages](../user-guide/09-messages.md)
- [Statistics and Reporting](../user-guide/16-statistics-and-reporting.md)

---

**Next:** [13 — Market Data & Drop Copy](13-market-data-drop-copy.md)

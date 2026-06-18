# 09 — Market Making

## Objective

Understand the QUOTE command from a human operator's perspective, explore quote
lifecycle, inactivation policies, QLEGS inspection, and MM obligations.

---

## Prerequisites

Add a manual MM gateway to your config:

```yaml
    - id: MM_MANUAL_01
      description: "Manual market-maker for training"
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_ANY_FILL
```

Restart the engine and connect:

```bash
pm-gateway --id MM_MANUAL_01
```

---

## Exercise 1: Submit a Two-Sided Quote

```
MM_MANUAL_01> QUOTE|SYM=AAPL|BID=149.90|ASK=150.10|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=Q001
```

Expected:

```
QUOTE ACK   Q001  bid=<bid_id> ask=<ask_id>
QUOTE ACTIVE  Q001
```

Note both leg IDs — you'll need them to identify fills.

:material-checkbox-blank-outline: **Checkpoint:** quote acknowledged and active.

---

## Exercise 2: Inspect Quote Legs with QLEGS

```
MM_MANUAL_01> QLEGS|SYM=AAPL|SHOW=ALL
```

Expected: a table showing both legs with prices, quantities, and fill status.

:material-checkbox-blank-outline: **Checkpoint:** QLEGS shows both bid and ask legs.

---

## Exercise 3: Get Filled and Observe Inactivation

From TRADER01, buy into the MM's ask:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
```

Back at MM_MANUAL_01, you should see:

```
FILL      <ask_id>  qty=100 @150.10
CANCELLED <bid_id>
QUOTE INACTIVE_ASK_FILLED  Q001
```

Under `INACTIVATE_ON_ANY_FILL`, both legs are pulled after any fill.

:material-checkbox-blank-outline: **Checkpoint:** fill + sibling cancel + INACTIVE status.

---

## Exercise 4: Re-quote After Inactivation

Submit a fresh quote:

```
MM_MANUAL_01> QUOTE|SYM=AAPL|BID=149.92|ASK=150.08|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=Q002
```

:material-checkbox-blank-outline: **Checkpoint:** new quote active; QLEGS shows fresh legs.

---

## Exercise 5: Replace a Quote Without Cancelling

You can replace directly — the engine handles the swap:

```
MM_MANUAL_01> QUOTE|SYM=AAPL|BID=149.95|ASK=150.05|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=Q003
```

Expected:

```
QUOTE CANCELLED  Q002
QUOTE ACK   Q003  ...
QUOTE ACTIVE  Q003
```

:material-checkbox-blank-outline: **Checkpoint:** old quote cancelled, new quote active in one step.

---

## Exercise 6: Explicit Cancel

```
MM_MANUAL_01> QUOTE_CANCEL|SYM=AAPL
```

Expected:

```
CANCELLED <bid_id>
CANCELLED <ask_id>
QUOTE CANCELLED  Q003
```

!!! note
    `QUOTE_CANCEL` is keyed by symbol, not by `quote_id`.

:material-checkbox-blank-outline: **Checkpoint:** quote fully cancelled.

---

## Exercise 7: Check Quote Bootstrap State (QBOOT)

After submitting a quote, inspect the bootstrap state:

```
MM_MANUAL_01> QBOOT|SYM=AAPL
```

This shows the current active quote slot for your gateway+symbol — useful for
verifying what the engine thinks your active quote is.

:material-checkbox-blank-outline: **Checkpoint:** QBOOT shows active quote or empty slot.

---

## Exercise 8: Understand Inactivation Policies

| Policy | Behaviour |
|--------|-----------|
| `INACTIVATE_ON_ANY_FILL` | Sibling cancelled on any fill (even partial) |
| `INACTIVATE_ON_FULL_FILL` | Sibling cancelled only when filled leg fully consumed |
| `NEVER_INACTIVATE` | No automatic sibling cancel; MM must manage manually |

---

## Key Takeaways

- The QUOTE command creates two linked limit orders (bid + ask).
- `quote_id` identifies the logical quote; legs are separate order IDs.
- QLEGS inspects current leg state; QBOOT inspects the active slot.
- Replacement quotes don't require explicit cancel first.
- `order.fill` does **not** include `quote_id` — correlate via leg order IDs.

---

**Next:** [10 — Combo Orders](10-combo-orders.md)

# 06 — Time-in-Force & Sessions

## Objective

Understand how Time-in-Force (TIF) controls order lifetime across session phases,
and how to use the scheduler to drive the exchange through a full trading day.

---

## Prerequisites

- Chapters 01–05 completed.
- `pm-engine`, `pm-scheduler`, and at least one trader gateway running.

---

## Background

Session phases progress as:

```
PRE_OPEN → OPENING_AUCTION → CONTINUOUS → CLOSING_AUCTION → CLOSED
```

Different TIF values control when orders are active and when they expire.

| TIF | Meaning | Valid During |
|-----|---------|--------------|
| `DAY` | Lives until end of session (cancelled at CLOSED) | CONTINUOUS |
| `GTC` | Good-Till-Cancelled; survives session boundaries | Any |
| `ATO` | At-The-Open only; participates in opening auction | OPENING_AUCTION |
| `ATC` | At-The-Close only; participates in closing auction | CLOSING_AUCTION |

---

## Exercise 1: Observe Session Phases

Start the scheduler in manual mode (if supported) or watch the automatic
transitions:

```bash
pm-scheduler --immediate
```

From your gateway, observe session state notifications:

```
[SESSION] state=PRE_OPEN
[SESSION] state=OPENING_AUCTION
[SESSION] state=CONTINUOUS
```

:material-checkbox-blank-outline: **Checkpoint:** you see at least one session state transition.

---

## Exercise 2: DAY Order Expiry

During CONTINUOUS, place a DAY order:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=148.00|TIF=DAY
```

When the session transitions to CLOSED, the order is automatically cancelled.

If your scheduler moves through phases quickly, watch for the cancellation
message.

Operational note: DAY is best for intraday intent where stale overnight orders
must not persist.

:material-checkbox-blank-outline: **Checkpoint:** DAY order cancelled at session close.

---

## Exercise 3: GTC Order Survives

Place a GTC order:

```
TRADER01> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=415.00|TIF=GTC
```

This order survives the CLOSED phase and will still be resting when the next
session opens.

Operational note: GTC is used for standing instructions that remain valid until
explicitly cancelled.

:material-checkbox-blank-outline: **Checkpoint:** GTC order remains after session restart.

---

## Exercise 4: ATO Order

During PRE_OPEN (before the opening auction), place an At-The-Open order:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=200|PRICE=150.50|TIF=ATO
```

This order only participates in the opening auction. If not filled during the
auction, it is cancelled when CONTINUOUS begins.

:material-checkbox-blank-outline: **Checkpoint:** ATO order participates in auction or is cancelled.

---

## Exercise 5: ATC Order

During CONTINUOUS, place an At-The-Close order:

```
TRADER01> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=149.00|TIF=ATC
```

This order is held until the closing auction. It only matches during that phase.

:material-checkbox-blank-outline: **Checkpoint:** ATC order does not match during CONTINUOUS.

---

## Exercise 6: Rejected TIF

Try submitting an ATO order during CONTINUOUS:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00|TIF=ATO
```

Expected: rejection — ATO orders are only accepted during PRE_OPEN or
OPENING_AUCTION phase.

:material-checkbox-blank-outline: **Checkpoint:** engine rejects out-of-phase TIF correctly.

---

## Summary

| Phase | Accepts | Cancels |
|-------|---------|---------|
| PRE_OPEN | ATO, GTC | — |
| OPENING_AUCTION | ATO, GTC | — |
| CONTINUOUS | DAY, GTC, ATC, IOC, FOK | ATO (unfilled) |
| CLOSING_AUCTION | ATC, GTC | — |
| CLOSED | — | DAY, ATC (unfilled) |

---

## Further Reading

- [Auctions & Scheduling](../user-guide/06-auctions-scheduling.md)
- [Persistence](../user-guide/11-persistence.md)
- [A Full Trading Day](../concepts/05-concepts-trading-day.md)

---

**Next:** [07 — Auctions](07-auctions.md)

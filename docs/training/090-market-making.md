# Market Making

## Objective

Understand the QUOTE command from a human operator's perspective, explore quote
lifecycle, inactivation policies, QLEGS inspection, and MM obligations.

 


!!! abstract "Pre-reading in the User Guide"
    - [Market Making](../user-guide/090-market-maker.md)

## Prerequisites

Add a manual MM gateway to your config:

```yaml
    - id: MM_MANUAL_01
      description: "Manual market-maker for training"
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_ANY_FILL
```

Deploy the change, then restart the engine — editing the YAML alone changes
nothing, because every process reads the compiled artifact:

```bash
pm-config-deploy engine_config.yaml
```

Then restart `pm-engine` and connect:

```bash
pm-alf-console --id MM_MANUAL_01
```

 

## Exercise 1: Submit a Two-Sided Quote

```
[MM_MANUAL_01]> QUOTE|SYM=AAPL|BID=149.90|ASK=150.10|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=Q001
```

Expected:

```
QUOTE ACK   Q001  bid=<bid_id> ask=<ask_id>
QUOTE ACTIVE  Q001
```

Note both leg IDs — you'll need them to identify fills.

:material-checkbox-blank-outline: **Checkpoint:** quote acknowledged and active.

 

## Exercise 2: Inspect Quote Legs with QLEGS

```
[MM_MANUAL_01]> QLEGS|SYM=AAPL|SHOW=ALL
```

Expected: a `Quote legs` table with one row per leg. The columns are:

| Column | Meaning |
|---|---|
| `Symbol` | The instrument |
| `Quote` | Your `QUOTE_ID` — the label you chose when submitting |
| `Leg` | `BID` or `ASK` |
| `Order` | The leg's order ID, **truncated to 8 characters** for display |
| `Qty` | Original quantity of the leg |
| `Rem` | Still resting |
| `Filled` | Already executed |
| `Filled?` | `YES` / `NO` — a quick scan column |
| `Leg status` | The order status of that leg |
| `Quote status` | The parent quote's state |
| `Time` | Last event time for the leg |

Two things are worth noticing straight away, because they are the ones people
misread:

- **`Leg status` and `Quote status` are different enums.** A leg is `NEW`,
  `PARTIAL`, `FILLED`, `CANCELLED`, `EXPIRED` or `PENDING`. The *quote* is
  `ACTIVE`, `INACTIVE_BID_FILLED`, `INACTIVE_ASK_FILLED` or `CANCELLED`.
  There is no `ACTIVE` leg status — a resting, untouched leg shows `NEW`.
- **The `Order` column is truncated.** `AMEND` and `CANCEL` need the *full*
  order ID; take it from the `QUOTE ACK` line, not from this column.

Try the filters — `SHOW=` accepts `ALL`, `ACTIVE` or `RECENT`:

```
[MM_MANUAL_01]> QLEGS|SYM=AAPL|SHOW=ACTIVE
[MM_MANUAL_01]> QLEGS|SYM=AAPL|SHOW=RECENT
```

`ACTIVE` keeps legs that are still working (an active status, or any remaining
quantity); `RECENT` shows the complement — legs that are done. Right now
`ACTIVE` should list both of your legs and `RECENT` should be empty; after
Exercise 3 that flips.

:material-checkbox-blank-outline: **Checkpoint:** `QLEGS` shows both a BID and an
ASK row for `Q001`, each with `Leg status` `NEW` and `Quote status` `ACTIVE`,
and you can say why no leg shows a status of `ACTIVE`.

 

## Exercise 3: Get Filled and Observe Inactivation

From TRADER01, buy into the MM's ask:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
```

Back at MM_MANUAL_01, you should see:

```
FILL      <ask_id>  qty=100 @150.10
CANCELLED <bid_id>
QUOTE INACTIVE_ASK_FILLED  Q001
```

Under `INACTIVATE_ON_ANY_FILL`, both legs are pulled after any fill.

:material-checkbox-blank-outline: **Checkpoint:** fill + sibling cancel + INACTIVE status.

 

## Exercise 4: Re-quote After Inactivation

Submit a fresh quote:

```
[MM_MANUAL_01]> QUOTE|SYM=AAPL|BID=149.92|ASK=150.08|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=Q002
```

:material-checkbox-blank-outline: **Checkpoint:** new quote active; QLEGS shows fresh legs.

 

## Exercise 5: Replace a Quote Without Cancelling

You can replace directly — the engine handles the swap:

```
[MM_MANUAL_01]> QUOTE|SYM=AAPL|BID=149.95|ASK=150.05|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=Q003
```

Expected:

```
QUOTE CANCELLED  Q002
QUOTE ACK   Q003  ...
QUOTE ACTIVE  Q003
```

:material-checkbox-blank-outline: **Checkpoint:** old quote cancelled, new quote active in one step.

 

## Exercise 6: Explicit Cancel

```
[MM_MANUAL_01]> QUOTE_CANCEL|SYM=AAPL
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

 

## Exercise 7: Cancel a Single Leg Directly — and See Why You Shouldn't

`QLEGS` gives you each leg's full order ID (Exercise 2's note about
truncation). Nothing stops you from feeding that ID straight into a plain
`CANCEL`, bypassing `QUOTE_CANCEL` entirely. Try it.

Submit a fresh quote and note the bid's full order ID from the `QUOTE ACK` line:

```
[MM_MANUAL_01]> QUOTE|SYM=AAPL|BID=149.90|ASK=150.10|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=Q004
```

Now cancel *only* the bid leg, by order ID, with plain `CANCEL` — not
`QUOTE_CANCEL`:

```
[MM_MANUAL_01]> CANCEL|ID=<bid_id>
```

Expected:

```
CANCELLED <bid_id>
```

That's it — no `QUOTE CANCELLED` line, no sibling cancel. Now inspect both views:

```
[MM_MANUAL_01]> QLEGS|SYM=AAPL|SHOW=ALL
[MM_MANUAL_01]> QBOOT|SYM=AAPL
```

You should see the bid leg's `Leg status` as `CANCELLED`, but the ask leg is
still `NEW` and resting, and **`Quote status` on both rows still reads
`ACTIVE`** — `QBOOT` agrees, still showing `Q004` as the active slot for this
symbol. Compare this with Exercise 3: a fill on one leg makes the engine
cancel the sibling and publish `QUOTE INACTIVE_*_FILLED` for you. A manual
`CANCEL` on one leg does not — the engine treats it as an ordinary,
independent order cancel and never consults the quote it belongs to.

!!! warning "This is a real trap, not just an exercise"
    The engine has no special handling for cancelling a single quote leg by
    order ID. Only `QUOTE_CANCEL` (whole quote, both legs) and a fill
    (subject to `quote_refresh_policy`) keep the quote's state consistent.
    If you cancel one leg manually, the other leg keeps resting — silently
    carrying one-sided market risk — while your own state and the engine's
    have quietly diverged. Always use `QUOTE_CANCEL|SYM=<symbol>` to pull a
    quote, never a bare `CANCEL` on one of its legs.

Clean up before moving on:

```
[MM_MANUAL_01]> QUOTE_CANCEL|SYM=AAPL
```

:material-checkbox-blank-outline: **Checkpoint:** you have seen a single-leg
`CANCEL` leave the sibling resting and both `Quote status` rows stuck on
`ACTIVE`, and can explain why `QUOTE_CANCEL` is the only safe way to pull a
whole quote.

 

## Exercise 8: Check Quote Bootstrap State (QBOOT)

After submitting a quote, inspect the bootstrap state:

```
[MM_MANUAL_01]> QBOOT|SYM=AAPL
```

This shows the current active quote slot for your gateway+symbol — useful for
verifying what the engine thinks your active quote is.

Why this matters operationally: on bot restart, a previous instance might have
left an active quote in the book. `QBOOT` prevents blind re-quoting by showing
whether a slot is already active so the new process can adopt or replace safely
instead of creating duplicates.

!!! note "The engine, not just your bot, can restart between quotes"
    Quote legs now persist across an **engine** restart the same way any
    other resting order does: unconditionally if `TIF=GTC`, or if `TIF=DAY`
    and the restart happens on the same business day. So `QBOOT` right after
    an engine restart can legitimately show your `Q001` slot still `ACTIVE`
    with the same leg IDs, even though you never resubmitted the quote — the
    engine restored it and re-registered it in its own `QuoteIndex`. Only a
    business-day rollover (or an explicit `QUOTE_CANCEL`/fill) clears a
    `TIF=DAY` quote slot. See
    [Persistence — Impact of a Business-Day Change](../user-guide/180-persistence.md#impact-of-a-business-day-change)
    for the full mechanics.

The reply is a `Quote bootstrap` table, one row per active quote:

| Column | Meaning |
|---|---|
| `Symbol` | The instrument |
| `Quote` | The `QUOTE_ID` of the quote occupying the slot |
| `State` | The quote state — `ACTIVE`, `INACTIVE_BID_FILLED`, `INACTIVE_ASK_FILLED` or `CANCELLED` |
| `Bid` / `Ask` | The two quoted prices, or `-` if that side has none |
| `BidRem` / `AskRem` | Remaining quantity on each leg |

When there is nothing to report — no active quote for that gateway and symbol
— you get a single dim line instead of a table:

```
No active quote bootstrap entries returned.
```

That empty response is the useful one on startup: it means the slot is free
and you can quote without first cancelling something.

Run it in both states to see the difference. With `Q001` still active from
Exercise 1 you get a row; after Exercise 3's fill inactivates the quote, run it
again and compare the `State` column with what `QLEGS` reports for the legs.

!!! note "`SYM=` is optional"
    `QBOOT` on its own asks about every symbol you have a quote on; `QBOOT|SYM=AAPL`
    narrows it to one. Use the bare form on a bot restart, when you do not yet
    know which slots are occupied.

:material-checkbox-blank-outline: **Checkpoint:** you have seen both responses —
a table with a `State` of `ACTIVE`, and the "No active quote bootstrap entries"
line — and can say which one tells a restarting bot it is safe to quote.

 

## Exercise 9: Compare Inactivation Policies

| Policy | Behaviour |
|--------|-----------|
| `INACTIVATE_ON_ANY_FILL` | Sibling cancelled on any fill (even partial) |
| `INACTIVATE_ON_FULL_FILL` | Sibling cancelled only when the filled leg is fully consumed |
| `NEVER_INACTIVATE` | No automatic sibling cancel; the MM manages both legs itself |

Reading the table is not the same as believing it. Change the policy and watch
the difference — this is the exercise that makes the three names mean
something.

**1.** Edit `MM_MANUAL_01` in your configuration to
`quote_refresh_policy: INACTIVATE_ON_FULL_FILL`, then deploy and restart:

```bash
pm-config-deploy engine_config.yaml
```

**2.** Quote again, then take only *part* of one leg:

```
[MM_MANUAL_01]> QUOTE|SYM=AAPL|BID=149.90|ASK=150.10|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=Q010
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.10|TIF=DAY
```

**3.** Inspect both views:

```
[MM_MANUAL_01]> QLEGS|SYM=AAPL|SHOW=ALL
[MM_MANUAL_01]> QBOOT|SYM=AAPL
```

Under `INACTIVATE_ON_ANY_FILL` (Exercise 3) this partial fill would have pulled
the bid and inactivated the quote. Under `INACTIVATE_ON_FULL_FILL` the ask leg
shows `PARTIAL` with `Rem` 400, the bid leg is still `NEW`, and the quote is
still `ACTIVE`.

**4.** Now consume the rest of the ask (another 400) and watch the quote flip
to `INACTIVE_ASK_FILLED`.

:material-checkbox-blank-outline: **Checkpoint:** you can state, for each of the
three policies, what happens to the sibling leg on a *partial* fill — and you
have observed at least two of them.

!!! tip "Set the policy back"
    Later chapters assume `INACTIVATE_ON_ANY_FILL`. Restore it and redeploy
    before moving on, or note that you changed it.

 

## Exercise 10: Disconnect and Bulk-Cancel Behaviour

Two more ways a quote gets pulled that have nothing to do with `QUOTE_CANCEL`
or a fill: your gateway disconnecting, and the self-service kill switch.
Both matter for risk — a quote left resting after your process dies is the
one-sided exposure Exercise 7 warned about, just caused by a dropped
connection instead of a stray `CANCEL`.

**Part A — disconnect behaviour.** Recall the Prerequisites config:

```yaml
disconnect_behaviour: CANCEL_QUOTES_ONLY
```

Quote a symbol, add a plain resting order too, then disconnect the gateway
(Ctrl+C or close the console):

```
[MM_MANUAL_01]> QUOTE|SYM=AAPL|BID=149.90|ASK=150.10|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=Q020
[MM_MANUAL_01]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=300.00|TIF=DAY
```

Disconnect `MM_MANUAL_01` (Ctrl+C), then reconnect the same way as in the
Prerequisites and check both:

```bash
pm-alf-console --id MM_MANUAL_01
```

```
[MM_MANUAL_01]> QBOOT|SYM=AAPL
[MM_MANUAL_01]> ORDERS
```

`ORDERS` has no symbol filter — it lists everything resting under this
gateway. Expected: the `AAPL` quote is gone (`QBOOT` reports no active entry
for it), but the `MSFT` limit order is still listed by `ORDERS`, resting
exactly as you left it.
`CANCEL_QUOTES_ONLY` — the default — cancels only quotes on disconnect;
ordinary resting orders are untouched. There are two other values: `CANCEL_ALL`
additionally sweeps every plain resting order too, and `LEAVE_ALL` cancels
nothing at all, leaving both quotes and orders resting across the
disconnect. Which one you want is a risk decision, not a technical one —
`LEAVE_ALL` trusts the MM to reconcile via `QBOOT`/`QLEGS` on reconnect
(Exercise 8's note on surviving quotes); `CANCEL_QUOTES_ONLY` assumes a
disconnected quoting engine can no longer manage its own risk and should not
keep resting prices in the book; `CANCEL_ALL` extends that same assumption
to every order, not just quotes.

**Part B — self-service `KILL`.** `QUOTE_CANCEL` is symbol-scoped and only
touches quotes. When you need to pull everything for your own gateway in one
shot — every active quote *and* every plain resting order, across every
symbol — use `KILL`:

```
[MM_MANUAL_01]> KILL
```

Expected:

```
KILL ACK  cancelled_orders=<n> cancelled_quotes=<n>
```

`cancelled_quotes` counts individual legs, not quote records, so a single
two-sided quote contributes up to 2 to that count. Scope it to one symbol
with `KILL|SYM=<symbol>` instead of clearing every symbol at once.

!!! note "This is not the admin `KILL|GW=...`"
    `KILL` on its own is self-service — a gateway can only kill its *own*
    exposure this way. An admin pulling another participant's exposure uses
    `KILL|GW=<gateway_id>` instead, covered in
    [19 — Advanced Admin Operations](190-advanced-admin-operations.md).

:material-checkbox-blank-outline: **Checkpoint:** you have seen a quote
disappear on disconnect while a plain order survived under
`CANCEL_QUOTES_ONLY`, and used `KILL` to clear all of your own gateway's
exposure in one command.

 

## Key Takeaways

- The QUOTE command creates two linked limit orders (bid + ask).
- `quote_id` identifies the logical quote; legs are separate order IDs.
- `QLEGS` inspects leg-level state; `QBOOT` inspects the quote slot. They
  report different enums: legs are `NEW`/`PARTIAL`/`FILLED`/…, quotes are
  `ACTIVE`/`INACTIVE_*_FILLED`/`CANCELLED`.
- Use QBOOT first during startup, then QLEGS for leg-level reconciliation.
- Replacement quotes don't require explicit cancel first.
- `order.fill` **does** include `quote_id` for a quote-leg fill, so you can correlate a fill back to the quote directly as well as via the leg order IDs.
- A plain `CANCEL` on one leg's order ID does **not** cancel the sibling or
  update `Quote status` — only `QUOTE_CANCEL`, or a fill under your
  `quote_refresh_policy`, keep the quote consistent. Never cancel a single
  leg manually.
- On disconnect, `disconnect_behaviour` decides what happens to your
  exposure: `CANCEL_QUOTES_ONLY` (default) cancels quotes only,
  `CANCEL_ALL` also cancels plain resting orders, `LEAVE_ALL` cancels
  neither.
- `KILL` (optionally `KILL|SYM=<symbol>`) is the self-service bulk cancel —
  every quote and every plain order for your own gateway in one command;
  `KILL|GW=<gateway_id>` is the admin equivalent for another gateway.

 

## Reflection

Why does the engine tie the bid and ask legs of a quote together with a
`quote_id` at all, rather than treating a market maker's two orders as
completely independent? What could go wrong for a market maker's risk
exposure if one leg filled and the sibling stayed resting under a
`NEVER_INACTIVATE` policy?

Why do you think the engine cascades a sibling cancel on a *fill* but not on
a manual `CANCEL` of one leg? What would have to change internally for
single-leg `CANCEL` to be quote-aware, and can you think of a reason the
engine might deliberately *not* want that — i.e., a case where cancelling
one leg without touching the other is exactly what you'd want?

## Further Reading

- [Market Making](../user-guide/090-market-maker.md)
- [Market-Maker Bot (pm-mm-bot)](../user-guide/100-mm-bot.md)
- [Market-Maker Bot CLI Reference](../user-guide/100-mm-bot.md#cli-reference)
- [ALF Console (pm-alf-console)](../user-guide/055-alf-console.md)
- [MM Quotes Concept](../concepts/03-concepts-mm-quotes.md)
- [ALF Protocol Reference](../user-guide/900-app-alf-protocol.md)
- [Advanced Admin Operations — admin-side KILL and QCANCEL](190-advanced-admin-operations.md)

 

**Next:** [10 — Combo Orders](100-combo-orders.md)

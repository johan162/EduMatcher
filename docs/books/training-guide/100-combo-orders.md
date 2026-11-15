# Combo Orders

## Objective

Build and close multi-leg strategies, size their hedges, and distinguish
entry checks from lifetime guarantees. Use OCO (One-Cancels-Other) for
alternative entries and exits, then test partial fills, stops, failure
cascades, session boundaries and recovery.

 


!!! abstract "Background reading"
    - [Combo Orders](../participant-guide/part-2-orders/030-combo-and-oco-orders.md)
    - [OCO](../participant-guide/part-2-orders/020-order-types.md#oco-one-cancels-other)

## Prerequisites

- Chapters 01–09 completed.
- Two trader gateways connected so you can stage opposing liquidity.
- An admin console for clearing the training books.
- For the stop-trigger labs, a third configured and connected trader,
  `TRADER03`, to print a trigger trade without changing `TRADER01`'s position.
  Add it to the `participants:` list of your `engine_config.yaml`, check,
  deploy, restart `pm-engine`, restart your open consoles and reopen the market
  (see "After every engine restart" in the
  [introduction](index.md#after-every-engine-restart)):

  ```yaml
    - id: TRADER03
      description: "Carol — third trader"
      role: TRADER
  ```

  then connect with `pm-alf-console --id TRADER03`.
- For the three-leg basket, `TSLA` configured alongside `AAPL` and `MSFT`.

### Lab discipline

Use an **isolated classroom exchange**, not a shared trading session.
Stop market-maker bots and AI traders. Keep the session in `CONTINUOUS`
with the scheduler stopped, using the
[freeze/advance procedure](060-time-in-force-sessions.md#freezeadvance-procedure-deterministic-session-control).
The session exercise explicitly changes this.

Exercises 1–3 build on each other. Before Exercise 4 and before **each
independent run or variant** in Exercises 5–14, clear the affected books:

```text
[GW_ADMIN|ADMIN]> CANCEL_SYM|SYM=AAPL
[GW_ADMIN|ADMIN]> CANCEL_SYM|SYM=MSFT
[GW_ADMIN|ADMIN]> CANCEL_SYM|SYM=TSLA
```

Only use the TSLA command if that symbol is configured. These commands cancel
orders, **not positions or trade history**. Record positions with `POS` in the
trader console before and after each lab and measure the change, rather than
assuming a flat account. `POS` values its `Real P&L` at the average cost of
*everything* that gateway has traded, so after a few labs it will not show a
single exercise's P&L exactly; work that out from the fills. Price
collars and circuit breakers must allow the example prices (AAPL 148–153,
MSFT near 420 and TSLA near 250); have the instructor align the configuration
before starting rather than treating a risk rejection as a strategy result.

Copy commands without the console prompt. Replace `<...>` placeholders with
actual IDs. Use a fresh `COMBO_ID` or `OCO_ID` on every repeat. Save the child
IDs from acknowledgements: `ORDERS` lists every order the console has seen —
the children of a combo or OCO included — with its latest status, but there is
no parent-combo status row. Use fill/cancel messages and parent status messages
as evidence; the operator console's `ORDERS|GW=<gateway>` shows what the engine
really has resting, and `pm-audit --terminal` is useful alongside the consoles.

### Progression

| Exercises | Skill |
|---|---|
| 1–3 | Entry atomicity, resting leg risk and parent cancellation |
| 4–7 | OCO entries/exits, partial fills and breakouts |
| 8–9 | Hedge ratios, closing a pair and multi-leg baskets |
| 10–11 | Depth, execution instructions and conditional combo legs |
| 12–14 | Failure handling, self-match prevention, sessions and recovery |

## Background

A **combo order** bundles two to ten legs on distinct symbols, each with its
own side and quantity, and submits them as one message with a shared
`COMBO_ID`.

`COMBO_TYPE=AON` (all-or-none) gives you an atomicity guarantee — but it is
narrower than it first sounds, and the exact shape of it is the main thing this
chapter teaches:

The experiments below begin with ordinary limit legs, external liquidity,
continuous matching and no halt. AON is a submission-time liquidity check,
not transaction rollback if a later child encounters SMP or another
execution restriction; Exercises 11–13 explore those boundaries.

!!! important "AON is atomic **at entry**, not for the combo's lifetime"
    When you submit an AON combo the engine checks, at that instant, whether
    *every* leg can fill completely. In the controlled setup above, there are
    three outcomes:

    - **All legs can fill** → all legs execute together. No partial.
    - **A leg is short, and another would trade at once** → the combo is
      **rejected**: its first leg with `INSUFFICIENT_LIQUIDITY`, and the
      combo `FAILED`. Resting the leg that would trade would leave its book
      crossed.
    - **A leg is short, and no leg would trade** → **no leg matches at all**.
      Every leg is posted to its book as an ordinary resting order.

    That third outcome is where the nuance lives. Those resting legs are now
    normal orders. Nothing stops another participant from hitting one of them
    later, and when that happens the combo moves to `PARTIALLY_MATCHED` — one
    leg filled, the others still resting. **You have leg risk again.**

In this controlled all-limit setup, a depth shortfall cannot make the combo
execute only part of its intended entry. It can still *end up* half-filled
while it rests. Exercises 2 and 3 show both halves of that.

The combo's lifecycle states are `PENDING`, `PARTIALLY_MATCHED`, `MATCHED`,
`FAILED` (a leg was cancelled, rejected or expired, so the siblings cascade-cancel),
`CANCELLED` and `REJECTED`.

 

## Exercise 1: Simple Two-Leg Combo

To see the combo **fill atomically**, first guarantee liquidity on both legs
with explicit counter-orders, and nothing else. Market-maker quotes from
earlier chapters would get in the way — TRADER02's MSFT buy at 420.50, for
example, would trade straight away with a market maker's cheaper ask instead
of resting. So stop any `pm-mm-bot`, clear both symbols from the operator
console, and then place the counter-orders:

```
[GW_ADMIN|ADMIN]> CANCEL_SYM|SYM=AAPL
[GW_ADMIN|ADMIN]> CANCEL_SYM|SYM=MSFT
```

```
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.10|TIF=DAY
[TRADER02]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=420.50|TIF=DAY
```

Now submit the combo — buy AAPL and sell MSFT atomically:

```
[TRADER01]> NEW|TYPE=COMBO|COMBO_ID=PAIR-001|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.10|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=50|LEG1.PRICE=420.50
```

Because both counter-orders above match the combo's leg prices exactly, the
engine can fill both legs simultaneously.

:material-checkbox-blank-outline: **Checkpoint:** the trader console shows a fill on each leg (with a `COMBO PARTIALLY_MATCHED  PAIR-001` line between them) followed by `COMBO MATCHED  PAIR-001`, and `BOOK|SYM=AAPL` / `BOOK|SYM=MSFT` in the operator console show both counter-orders gone.

Observation: when the pre-check passes, both legs execute in the same pass —
this is the case the AON guarantee is designed for.

 

## Exercise 2: Atomicity at Entry — One Short Leg Blocks Every Leg

Now check the pre-check: when liquidity is missing on **one** leg, *no* leg
matches, even the one that could have — and the combo is rejected:

1. Exercise 1 used up the AAPL sell, so place a new one:
   `[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.10|TIF=DAY`.
2. Do **not** place any MSFT buy at 420.50 — cancel or avoid resting MSFT
   liquidity at that price so the second leg has nothing to match against.
3. Submit a new combo with a fresh ID:

   ```
   [TRADER01]> NEW|TYPE=COMBO|COMBO_ID=PAIR-002|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.10|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=50|LEG1.PRICE=420.50
   ```

4. The AAPL leg is rejected with `INSUFFICIENT_LIQUIDITY` and the combo
   `FAILED`; the MSFT leg is never posted. Check `BOOK|SYM=AAPL` in the
   operator console and confirm the AAPL sell at 150.10 is **still resting,
   unfilled**, proving the combo did not execute the AAPL leg alone even
   though a matching counter-order existed for it.

:material-checkbox-blank-outline: **Checkpoint:** the combo did not execute the
AAPL leg even though a matching counter-order was sitting there, and nothing of
the combo rests.

Operational rationale: without the entry pre-check you would pick up accidental
directional inventory the moment you submitted an unbalanced combo. And the
AAPL leg could not rest instead: a buy at 150.10 resting against a sell at
150.10 would leave the book crossed.

 

## Exercise 3: Leg Risk Returns Once the Combo Rests

A combo with no leg that can trade yet rests with both legs in their books.
This is the case people are surprised by, so cause it deliberately.

**1.** Submit a combo whose AAPL leg bids below TRADER02's AAPL sell at
150.10, and confirm it is resting and `PENDING`:

```
[TRADER01]> NEW|TYPE=COMBO|COMBO_ID=PAIR-003|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.00|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=50|LEG1.PRICE=420.50
[TRADER01]> ORDERS
```

You should see both child legs — the AAPL buy at 150.00 and the MSFT sell at
420.50 — with status `NEW`.

**2.** From `TRADER02`, hit **only the MSFT leg**:

```
[TRADER02]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=420.50|TIF=DAY
```

**3.** Look at what happened to the combo:

```
[TRADER01]> ORDERS
```

The MSFT fill message says `FILLED`, and `ORDERS` now lists that leg as
`FILLED`. The AAPL leg is still `NEW`, resting. The combo has moved to
`PARTIALLY_MATCHED`.

`TRADER01` is now short 50 MSFT with no offsetting AAPL position — precisely
the leg risk the combo was supposed to prevent. The AON guarantee was never
violated: it applied at submission, and at submission nothing executed.

:material-checkbox-blank-outline: **Checkpoint:** the combo is
`PARTIALLY_MATCHED` with one leg filled and one resting, and you can explain
why this does not contradict "all-or-none".

!!! tip "What a real desk does about this"
    Because a resting AON combo can be picked apart, desks do not leave them
    resting. They either submit only when both sides are already fillable, or
    they cancel the whole combo the moment it fails to execute at entry, as
    you do in step 4. That cancels every remaining leg. Fills that already
    happened are **not** reversed — cancel the combo before someone hits a
    leg, not after.

**4.** Cancel what is left of the combo as a whole:

```
[TRADER01]> CANCEL|COMBO_ID=PAIR-003
```

Expected (each line also carries a `[HH:MM:SS.mmm]` time):

```
CANCELLED <aapl_leg_id>
COMBO CANCELLED  PAIR-003
COMBO CXL OK PAIR-003  legs cancelled=1
```

Only one leg is cancelled — the resting AAPL buy. The MSFT leg had already
filled, and that fill stands. Cancel a combo before anyone hits a leg and
`legs cancelled` equals the number of legs.

:material-checkbox-blank-outline: **Checkpoint:** you can explain why
`legs cancelled=1`, and what position the cancel left you with.

 

## Exercise 4: OCO — One-Cancels-Other

Link two independent orders so that when one **fully fills** or otherwise
ends (cancel, rejection or expiry), the other is automatically cancelled.
A partial fill alone does not end the pair; Exercise 6 tests this distinction.

```
[TRADER01]> NEW|TYPE=OCO|OCO_ID=OCO-AAPL-ENTRY|SYM=AAPL|QTY=100|TIF=DAY|LEG1_SIDE=BUY|LEG1_TYPE=LIMIT|LEG1_PRICE=149.50|LEG2_SIDE=BUY|LEG2_TYPE=LIMIT|LEG2_PRICE=148.00
```

Make the first leg fill by selling into it from `TRADER02`:

```
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=149.50|TIF=DAY
```

The 149.50 leg fills, and the console reports the sibling at 148.00
cancelled: `OCO CANCEL OCO-AAPL-ENTRY  sibling=…  OCO sibling … reached FILLED`.
(If the AAPL book still holds asks at or below 149.50 from earlier
exercises, the OCO's first leg fills on entry instead — clear AAPL with
`CANCEL_SYM` first for a clean run.)

To pull an OCO pair yourself before either leg fills, cancel it by its
`OCO_ID` rather than cancelling each leg individually. `OCO-AAPL-ENTRY` has
already completed (cancelling it now answers `OCO CXL REJ … ORDER_NOT_FOUND`),
so submit a fresh pair and cancel that:

```
[TRADER01]> NEW|TYPE=OCO|OCO_ID=OCO-AAPL-ENTRY-2|SYM=AAPL|QTY=100|TIF=DAY|LEG1_SIDE=BUY|LEG1_TYPE=LIMIT|LEG1_PRICE=149.50|LEG2_SIDE=BUY|LEG2_TYPE=LIMIT|LEG2_PRICE=148.00
[TRADER01]> CANCEL|OCO_ID=OCO-AAPL-ENTRY-2
```

Both legs are cancelled: `OCO CXL OK OCO-AAPL-ENTRY-2  legs cancelled=2`.

:material-checkbox-blank-outline: **Checkpoint:** filling one OCO leg cancels the other.

 

## Exercise 5: OCO — Protect an Existing Long Position

A common exit pattern is a take-profit plus a stop-loss. Both legs are
**SELL**, not different sides: each is an alternative way to close the
same long position. First acquire 100 shares on the cleared AAPL book:

```text
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.00|TIF=DAY
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00|TIF=DAY
```

Now submit the exit pair:

```
[TRADER01]> NEW|TYPE=OCO|OCO_ID=BRACKET-AAPL-001|SYM=AAPL|QTY=100|TIF=DAY|LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|LEG1_PRICE=151.00|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=149.00
```

Run both branches separately, acquiring a fresh 100-share position and using
a fresh OCO ID on the second run:

- **Take profit:** `TRADER02` buys 100 AAPL at 151.00. The resting limit
  sells all 100; the stop is cancelled. Gross profit is 100.
- **Stop loss:** `TRADER02` posts a bid for 101 AAPL at 149.00, then
  `TRADER03` sells 1 at 149.00. That print triggers the stop, whose 100-share
  market sell consumes the remaining bid; the take-profit is cancelled.
  Gross loss is 100.

Quotes merely moving are not enough: these stop exercises create an actual
trade at the trigger price.

!!! warning "This is not an attached, reduce-only bracket"
    The OCO does not create or reserve the long position, wait for a separate
    entry order, or resize itself after partial fills. A stop becomes a
    market order: 149.00 is a trigger, **not** a guaranteed execution price.
    If liquidity is absent, it may execute partly or not at all. You must
    reconcile the resulting position yourself.

:material-checkbox-blank-outline: **Checkpoint:** demonstrate both exits,
identify the sibling cancellation, and calculate P&L from actual fills rather
than from the stop trigger.

## Exercise 6: OCO — A Partial Fill Is Not a Completed Choice

**Predict first:** after 40 shares of a 100-share leg fill, does the sibling
remain at 100, resize to 60, or disappear?

On a cleared AAPL book:

```text
[TRADER01]> NEW|TYPE=OCO|OCO_ID=OCO-PARTIAL-01|SYM=AAPL|QTY=100|TIF=DAY|LEG1_SIDE=BUY|LEG1_TYPE=LIMIT|LEG1_PRICE=149.50|LEG2_SIDE=BUY|LEG2_TYPE=LIMIT|LEG2_PRICE=148.00
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=40|PRICE=149.50|TIF=DAY
[TRADER01]> ORDERS
```

The first leg has 60 remaining and is `PARTIAL`. The sibling still bids for
**100**, not 60. OCO has not cancelled or resized it.

1. Sell another 60 at 149.50 from `TRADER02`. The first leg becomes `FILLED`
   and the 148.00 sibling is cancelled.
2. Reset and repeat with a fresh ID, but after the first 40-share fill,
   cancel the **partially filled child** with `CANCEL|ID=<child_id>`.
   The sibling is cancelled with it (`OCO sibling … reached CANCELLED`).
   `CANCEL|OCO_ID=<new_oco_id>` would have the same effect. Either way the
   40 bought shares remain: compare `POS`, not just the cancel messages.

Explain why the higher of two ordinary buy limits usually fills first.
These are not two independent opportunities to buy 100 shares each. Nor
does the link impose a shared cumulative-fill budget while both legs remain
nonterminal. For a partially filled exit OCO, you must manage the remaining
position and outstanding quantities yourself.

:material-checkbox-blank-outline: **Checkpoint:** record 40 filled, 60
remaining on one leg and 100 on its sibling; prove that cancellation does
not undo the 40-share fill.

## Exercise 7: OCO — Breakout Entry

Unlike Exercise 5, this pair has **opposite sides**. It expresses an
alternative entry, not protection of an existing position.

First establish a last trade of 150.00 with a one-share sell from `TRADER02`
and a one-share buy from `TRADER03`. Then submit:

```text
[TRADER01]> NEW|TYPE=OCO|OCO_ID=BREAKOUT-01|SYM=AAPL|QTY=100|TIF=DAY|LEG1_SIDE=BUY|LEG1_TYPE=STOP|LEG1_STOP=151.00|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=149.00
```

- **Up-break run:** `TRADER02` offers 101 at 151.00; `TRADER03` buys 1
  at 151.00. The buy stop consumes the other 100 and cancels the sell stop.
  `TRADER01`'s position change is +100 AAPL.
- **Down-break run:** reset, print 150.00 again and recreate the OCO.
  `TRADER02` bids for 101 at 149.00; `TRADER03` sells 1 at 149.00.
  The sell stop consumes the other 100 and cancels the buy stop.
  The position change is −100 AAPL.

Repeat with only 1 share at the trigger price, leaving no liquidity for the
stop. The triggered stop ends `CANCELLED … reason=INSUFFICIENT_LIQUIDITY`, and
its sibling is cancelled all the same (`OCO sibling … reached CANCELLED`).
**OCO cancellation does not prove a position was acquired.**

The stop-limit and trailing-stop exits of [chapter 05](050-order-types.md)
work as OCO legs too (`LEG2_TYPE=STOP_LIMIT` with `LEG2_STOP` and
`LEG2_PRICE`, or `LEG2_TYPE=TRAILING_STOP` with `LEG2_TRAIL`) and keep the
risks you met there: a stop-limit can trigger and still not fill.

:material-checkbox-blank-outline: **Checkpoint:** you can tell an entry OCO
(opposite sides) from an exit OCO (same side), and you have seen a triggered
stop end with `CANCELLED … reason=INSUFFICIENT_LIQUIDITY` while still
cancelling its sibling.

## Exercise 8: Size a Pairs Trade and Close It

Exercise 1's 100 AAPL versus 50 MSFT is not dollar-neutral: at 150 and 420,
the notionals are 15,000 versus 21,000. A combo supplies execution mechanics,
**not** the hedge ratio or a profitable trading signal.

Choose a gross notional of 42,000 on each side. That requires buying 280
AAPL at 150 and selling 100 MSFT at 420:

```text
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=280|PRICE=150.00|TIF=DAY
[TRADER02]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=420.00|TIF=DAY
[TRADER01]> NEW|TYPE=COMBO|COMBO_ID=NEUTRAL-IN-01|COMBO_TYPE=AON|TIF=DAY|TAG=PAIR-LAB|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=280|LEG0.PRICE=150.00|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=100|LEG1.PRICE=420.00
```

After both fill, close the **actual filled quantities** with a new,
opposite-side combo:

```text
[TRADER02]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=280|PRICE=152.00|TIF=DAY
[TRADER02]> NEW|SYM=MSFT|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=422.00|TIF=DAY
[TRADER01]> NEW|TYPE=COMBO|COMBO_ID=NEUTRAL-OUT-01|COMBO_TYPE=AON|TIF=DAY|TAG=PAIR-LAB|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=SELL|LEG0.QTY=280|LEG0.PRICE=152.00|LEG1.SYM=MSFT|LEG1.SIDE=BUY|LEG1.QTY=100|LEG1.PRICE=422.00
```

Calculate before reading the answer:

- Long AAPL: 280 × (152 − 150) = +560.
- Short MSFT: 100 × (420 − 422) = −200.
- Gross strategy P&L: **+360**, before fees. The combined position change
  over entry and exit is zero.

Compute this from the four `FILL` lines. `POS` will show a different
`Real P&L` change unless `TRADER01` was flat before you started (see Lab
discipline).

Equal notionals are not equal market sensitivities. Discuss how different
volatility, beta and correlation could invalidate this hedge. Prices moving
together do not guarantee a profit, and a pairs trade is not risk-free
arbitrage.

`TAG` is a client correlation label; it does not link the two combo parents
or make the exit automatic. Cancelling an already filled entry cannot close
the position.

:material-checkbox-blank-outline: **Checkpoint:** justify the 280:100 ratio,
prove both parents matched, and reconcile four leg fills to +360 gross P&L.

## Exercise 9: Three-Leg Basket

Model a hypothetical relative-value signal: buy AAPL against a basket of
MSFT and TSLA. Use unequal quantities to balance cash notionals:
100 × 150 = 25 × 420 + 18 × 250 = 15,000.

```text
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.00|TIF=DAY
[TRADER02]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=25|PRICE=420.00|TIF=DAY
[TRADER02]> NEW|SYM=TSLA|SIDE=BUY|TYPE=LIMIT|QTY=18|PRICE=250.00|TIF=DAY
[TRADER01]> NEW|TYPE=COMBO|COMBO_ID=BASKET-01|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=3|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.00|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=25|LEG1.PRICE=420.00|LEG2.SYM=TSLA|LEG2.SIDE=SELL|LEG2.QTY=18|LEG2.PRICE=250.00
```

1. Verify all three fills and `MATCHED`.
2. Reset and repeat, but stage only **17 TSLA**, not 18. Predict the result
   before submitting. No leg may trade at entry in this controlled
   all-limit setup; the parent becomes `FAILED`. All counter-orders remain.
3. Reset and submit the same basket to **empty** books. It rests. Fill only
   10 AAPL from `TRADER02`: the parent becomes `PARTIALLY_MATCHED`, even
   though no entire leg has finished. Record the remaining quantities.
   Cancel the parent and identify the residual +10 AAPL position.

The same rules hold for up to ten legs (`LEG_COUNT=10`, `LEG0` … `LEG9`),
each on a different symbol; Exercise 13 shows the console refusing
`LEG_COUNT=11`.

:material-checkbox-blank-outline: **Checkpoint:** submit a three-leg basket,
diagnose a one-share shortfall, and explain why a resting basket can be
`PARTIALLY_MATCHED` with no leg finished.

## Exercise 10: Execution Cost — Depth, MARKET, IOC and FOK Legs

An AON pre-check needs the **whole quantity**, not merely a visible best
price. On cleared books stage this ladder:

```text
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=40|PRICE=150.00|TIF=DAY
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=60|PRICE=150.10|TIF=DAY
[TRADER02]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=20|PRICE=420.50|TIF=DAY
[TRADER02]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=30|PRICE=420.40|TIF=DAY
[TRADER01]> NEW|TYPE=COMBO|COMBO_ID=DEPTH-01|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.TYPE=LIMIT|LEG0.PRICE=150.10|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=50|LEG1.TYPE=LIMIT|LEG1.PRICE=420.40
```

Calculate the leg VWAPs: AAPL (40 × 150.00 + 60 × 150.10) / 100 = **150.06**,
MSFT **420.44**. The trader console prints one `FILL` line per leg with that
average already worked out (`qty=100 @150.06`).
The entry receives 21,022 − 15,006 = **6,016 cash** before fees, but it
also creates a short liability. That receipt is not a profit.

Repeat with a fresh ID and restaged ladder for each variant:

| Variant | Command changes | Prediction in this controlled setup |
|---|---|---|
| Price limit too tight | AAPL `LEG0.PRICE=150.00` | Only 40 eligible AAPL; no leg trades; parent `FAILED` |
| One share short | Stage 59 instead of 60 at 150.10 | Only 99 AAPL; no leg trades; parent `FAILED` |
| Market legs | Both `.TYPE=MARKET`; remove both `.PRICE` fields | Full depth is available; both fill, but no leg price cap |
| IOC legs | Both `.TYPE=IOC`; keep both prices | Both fill completely when the pre-check passes |
| FOK legs | Both `.TYPE=FOK`; keep both prices | Both fill completely when the pre-check passes |

Repeat the short-liquidity run with IOC and FOK legs too. Do **not** import
the single-order IOC lesson ("take 99 and cancel 1") into an AON combo:
the parent pre-check blocks execution here. Finally, submit each immediate
type to empty books; unlike passive limits, those legs cannot wait, so the
combo fails instead of remaining `PENDING`.

There is **no parent net-price limit**. Choose each leg's cap yourself and
compute the resulting worst-case cash flow. `COMBO_TYPE` currently supports
only `AON`, not a ratio-fill, net-debit or net-credit execution mode.

:material-checkbox-blank-outline: **Checkpoint:** reconcile quantities and
VWAPs across multiple price levels, and explain the interaction between
parent AON and each child's execution instruction.

## Exercise 11: Conditional Combo Legs Are Not a Synchronized Trigger

The engine accepts `STOP` and `STOP_LIMIT` combo legs, but their triggers
belong to their individual symbol books. Use them to study conditional
exposure, **not** as a promise of an atomic future hedge.

Establish a one-share AAPL trade at 150.00 between `TRADER02` and
`TRADER03`. Leave no other interest, then submit:

```text
[TRADER01]> NEW|TYPE=COMBO|COMBO_ID=CONDITIONAL-01|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.TYPE=STOP|LEG0.STOP=151.00|LEG1.SYM=MSFT|LEG1.SIDE=BUY|LEG1.QTY=50|LEG1.TYPE=LIMIT|LEG1.PRICE=420.00
```

1. Confirm the parent is pending. The AAPL stop is dormant; the MSFT limit
   is working. There was no immediate opposing liquidity.
2. `TRADER02` offers 101 AAPL at 151.00; `TRADER03` buys 1 at 151.00.
   The print releases the 100-share buy stop, which fills from the
   remaining offer. MSFT has not filled. Observe `PARTIALLY_MATCHED`.
3. `TRADER02` sells 50 MSFT at 420.00. The parent now reaches `MATCHED`.
   Explain why this is two separate exposures in time, not an atomic
   event at the AAPL trigger.

!!! important "Do not generalize the all-limit entry experiment"
    A stop's trigger and subsequent liquidity are separate from the combo's
    submission-time depth check. Neither the parent ACK nor AON means that
    all conditional legs will trigger together, or that a stop will fill.
    The same caution applies to later auctions, halts and SMP interactions.

:material-checkbox-blank-outline: **Checkpoint:** demonstrate both dormant
and triggered legs, and explain why the parent was `PARTIALLY_MATCHED` for
as long as the MSFT leg stayed unfilled.

## Exercise 12: Parent Cancel, Child Failure and Self-Match Prevention

### A. Cancel one child, fail the strategy

Submit a passive combo to empty books and save the child order IDs. Instead
of cancelling the parent, cancel one child:

```text
[TRADER01]> NEW|TYPE=COMBO|COMBO_ID=PAIR-005|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=149.00|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=50|LEG1.PRICE=420.50
[TRADER01]> CANCEL|ID=<aapl_child_id>
```

The MSFT sibling is cancelled too, and the parent reports
`COMBO FAILED  PAIR-005  Leg 0 (AAPL) CANCELLED`. Contrast
this with `CANCEL|COMBO_ID=...`, which produces `CANCELLED`. Repeat after a
10-share AAPL fill: failure cancels the remaining interest, not that fill.

### B. AON entry preflight and later child matching use SMP differently

Stage an AAPL offer **owned by TRADER01**, and an MSFT bid owned by
`TRADER02`:

```text
[TRADER01]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.00|TIF=DAY
[TRADER02]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=420.00|TIF=DAY
[TRADER01]> NEW|TYPE=COMBO|COMBO_ID=SMP-01|COMBO_TYPE=AON|SMP=CANCEL_AGGRESSOR|TIF=DAY|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.00|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=50|LEG1.PRICE=420.00
```

The combo-level `SMP` applies to every child. For an AON entry, the
preflight counts only liquidity the child could actually trade against under
that policy. With `CANCEL_AGGRESSOR`, the AAPL offer counts as **zero** even
though 100 shares sit at the exact price: the combo is accepted, then its
first leg is rejected with `INSUFFICIENT_LIQUIDITY` and the parent shows
`COMBO FAILED  SMP-01  Leg 0 (AAPL) REJECTED`. The MSFT child is not posted,
there is no trade, and both the AAPL offer and external MSFT bid remain.

Reset and send the same combo with `SMP=CANCEL_RESTING`, then
`SMP=CANCEL_BOTH`: with any policy other than `NONE` the outcome is the same,
because the entry check discounts own liquidity before any SMP action could
run; it does not cancel the resting offer. Now reset once more and send it
with `SMP=NONE`, or omit `SMP=` when your gateway default is `NONE` (as in the
configuration you wrote in chapter 01): both legs fill, the AAPL leg *against
your own offer*, and the parent reaches `MATCHED`. That is a self-trade, not
hedge liquidity. Do not equate an accepted parent, displayed depth or a
`MATCHED` parent with genuine external execution.

Omitting `SMP=` uses the gateway's configured default (`smp_action` in the
participant's block; the bundled example configurations set
`CANCEL_AGGRESSOR`, a hand-written one like yours sets nothing, which means
`NONE`). OCO has no per-request SMP field: its legs use the gateway default.

This entry preflight is different from a combo child that rests and later
becomes marketable. To see the regular SMP actions at execution time, reset
the books and submit an AON combo with its AAPL buy at 149.00, its MSFT sell
at 420.00, and `SMP=CANCEL_RESTING`. After both children rest, place your own
AAPL sell at 150.00, then amend the saved combo-child ID to 150.00:

```text
[TRADER01]> NEW|TYPE=COMBO|COMBO_ID=LATER-01|COMBO_TYPE=AON|SMP=CANCEL_RESTING|TIF=DAY|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=149.00|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=50|LEG1.PRICE=420.00
[TRADER01]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.00
[TRADER01]> AMEND|ID=<aapl_child_id>|PRICE=150.00
```

The amended combo child is now the aggressor. `CANCEL_RESTING` cancels your
own offer, then leaves the amended child and its MSFT sibling resting; the
parent remains `PENDING` and no trade prints. Repeat from clean books with
`NONE`, `CANCEL_AGGRESSOR`, and `CANCEL_BOTH`: `NONE` permits the AAPL
self-trade and moves the parent to `PARTIALLY_MATCHED`; `CANCEL_AGGRESSOR`
cancels the amended child and its sibling but leaves your offer; `CANCEL_BOTH`
cancels the offer and both combo children. The two cancel policies leave the
parent `FAILED`. These policies differ when an actual child is matched, even
though the AON entry preflight gives the same result for all non-`NONE`
policies.

### C. Reprice a child without re-entering the parent

On empty books submit a fresh passive combo buying 100 AAPL at 149.00
and selling 50 MSFT at 420.00. Then `TRADER02` offers 100 AAPL at 150.00.
Amend the saved AAPL child ID:

```text
[TRADER01]> AMEND|ID=<aapl_child_id>|PRICE=150.00|RTAG=COMBO-REPRICE-01
```

The amended child can fill alone, moving the parent to `PARTIALLY_MATCHED`.
Its sibling remains working. Complete it with a 50-share MSFT buy from
`TRADER02`, or cancel the parent and reconcile the AAPL exposure.

There is no parent-wide atomic amend command. A child reprice is an ordinary
order amendment, not a resubmission of the original AON package. Apply
[Amending Orders](040-amending-orders.md)'s priority rules, and do not assume
the other child limits were changed.

:material-checkbox-blank-outline: **Checkpoint:** explain why AON entry
preflight rejects own-only liquidity under any non-`NONE` policy, why an
amended resting combo child applies its own SMP policy when it becomes the
aggressor, and why cascade cancellation cannot roll back a previous execution.

## Exercise 13: Validation and TIF — When Should Nothing Be Posted?

### A. Reject malformed intent before trading

Starting from a valid passive combo command, change **one thing at a time**.
Use a new label for every attempt and preserve the error message:

| Change | What to establish |
|---|---|
| `LEG_COUNT=1` or `11` | The console refuses it: `LEG_COUNT must be between 2 and 10` |
| Use AAPL for both legs | Engine refuses duplicate symbols |
| Remove a required limit `.PRICE` | Engine refuses it: `COMBO REJ … Leg 0: LIMIT requires price` |
| Supply a price between that symbol's valid ticks | The console refuses it: `Leg 0 parse error: 149.005 is not a multiple of AAPL's tick size 0.01` |
| `LEG0.TYPE=TRAILING_STOP` or `ICEBERG` | Unsupported combo leg shape is refused |
| Set a leg quantity to zero | Invalid quantity is refused |
| Use an unconfigured symbol | Submission is refused, not partially posted |

A line with no `[HH:MM:SS.mmm]` time was refused by the console itself; the
order never left your terminal. A `COMBO REJ` line came back from the engine.

Combo legs support LIMIT, MARKET, IOC, FOK, STOP and STOP_LIMIT. OCO also
supports TRAILING_STOP, but **not ICEBERG**. For OCO, try an immediate
`MARKET`, `IOC` and `FOK` first leg against staged sufficient liquidity,
paired with a passive second leg: when the first ends at entry, the second
must not trade. Repeat IOC with too little liquidity and FOK with none;
compare actual fills before sibling cancellation.

### B. DAY versus GTC at the close

With the scheduler stopped and sessions enabled, submit passive combos
under two fresh labels, one `TIF=DAY` and one `TIF=GTC`, to empty books.
Advance from `CONTINUOUS` through `CLOSING_AUCTION` to `CLOSED`.
The DAY children expire and the parent fails; GTC interest survives.
Cancel the GTC combo after reopening.

The expiry arrives as `EXPIRED <leg_id>  (Trading day ended)` for each DAY
child, followed by `COMBO FAILED  <id>  Leg 1 (MSFT) EXPIRED`. Combos in the
auction phases follow the same per-book rules as ordinary orders
([chapter 07](070-auctions.md)): each book uncrosses on its own, so an auction
does not rerun the combo's entry check across symbols. `TIF=DAY` and
`LEG0.TYPE=IOC` are different things: TIF controls lifetime; the leg type
controls execution.

### C. A halted hedge leg

Using [Risk Controls](110-risk-controls.md)'s manual halt procedure, halt
MSFT on an empty book with `HALT_SYM|SYM=MSFT`. Submit a fresh passive
two-limit combo to empty books; its MSFT child can rest, but must not match
while halted. Then, on freshly cleared books, repeat with an MSFT MARKET,
IOC or FOK child: that child cannot rest and the parent fails.

Use the leg rejection to distinguish `INSTRUMENT_HALTED` from an ordinary
liquidity shortfall. Resume with `RESUME_SYM|SYM=MSFT` and inspect actual
fills; do not assume resuming reconstructs an atomic hedge. Restore
`CONTINUOUS` and clear all interest before leaving this lab.

:material-checkbox-blank-outline: **Checkpoint:** separate gateway errors,
parent rejection, child failure and expiry, using the ACKs and status events
rather than a single "accepted" line.

## Exercise 14: Advanced Operations — Recovery and Strategy Liquidity

This lab extends [Persistence & Recovery](160-persistence-recovery.md).
Use a dedicated data directory, the same configuration on restart, and a
clean stop. Do not hand-edit persistence files to manufacture a result.

### A. Recover the relationship, not just the orders

1. On empty books submit a passive two-limit combo with
   `COMBO_ID=RECOVER-GTC-01` and `TIF=GTC`. Also submit a passive OCO with
   `TIF=GTC`. Record parent labels and all child IDs.
2. Stop and restart the engine using the same data directory. Reconnect
   the gateways and restore `CONTINUOUS` if sessions are enabled. The restart
   also places the configured market-maker seed quotes again, and they would
   take the fill in step 4. Pull them with `KILL|GW=MM_AAPL_01`,
   `KILL|GW=MM_MSFT_01` and `KILL|GW=MM_TSLA_01` — not `CANCEL_SYM`, which
   would cancel your restored GTC orders as well.
3. Cancel the restored combo by `COMBO_ID`; both working children must
   disappear, proving the parent-child relationship was restored.
4. Fill one restored OCO leg completely. Its restored sibling must cancel,
   proving that restoring two orders also restored their OCO relationship.
5. Repeat with a **partially filled GTC combo**, recording filled quantities
   before restart. Complete its remaining legs afterwards and check the
   resulting parent status; do not resubmit the original full quantities.

**Comparison:** repeat the passive combo with `TIF=DAY` and restart on the
same business day, without a session-close transition first. The DAY combo
comes back as well, parent and children, and `CANCEL|COMBO_ID=...` still
cancels both legs. Only a new business day (or the close of Exercise 13)
ends it: on a later day's restart the engine discards a DAY combo together
with its legs.

### B. Provide liquidity for another participant's strategy

As `TRADER02`, post the opposite of Exercise 8's entry as a passive live
combo: sell 280 AAPL at 150 and buy 100 MSFT at 420. With both legs resting,
submit the entry from `TRADER01`. Both parents can complete through ordinary
book matching; there is no separate combo order book.

Repeat, but have `TRADER03` take just part of one resting provider leg
first. Recompute the depth before `TRADER01` submits. The provider's
remaining pair is no longer a guaranteed hedge package. This is why a
strategy liquidity provider needs per-leg inventory monitoring.


:material-checkbox-blank-outline: **Checkpoint:** prove restored GTC
relationships still work, say when a DAY combo is discarded, and explain why
a provider's partly taken combo is no longer a hedge package.

 

## When to Use Combos vs OCO

| Use Case | Mechanism |
|----------|-----------|
| Spread / pairs trade (buy A + sell B) | Combo |
| Hedging (must have both sides or neither) | Combo — but see the caveat below |
| Take-profit + stop-loss (only want one to execute) | OCO |
| Multiple entries at different prices (only want one) | OCO |

!!! warning "AON is not a lifetime execution transaction"
    The entry liquidity check prevents the ordinary all-limit, short-depth
    case from executing only one leg. Resting fills, conditional triggers,
    amendments, auctions and execution restrictions can still leave leg risk.
    Stage external liquidity, check each leg's eligibility, and reconcile
    actual fills before cancelling or unwinding. Cancellation never rolls
    back an execution.

 

## Reflection

An AON combo is described as "all-or-none", yet a combo can reach a state where
one leg is filled and another is still resting. Explain how both statements are
true at once, and name the moment at which the guarantee applies.

Why does a Combo check liquidity at entry while OCO reacts to a child reaching
a terminal state? How do partial fills change the risk in each case, and why
does the distinction matter for a pairs trade versus a take-profit/stop-loss
pair?

For that comparison, state the assumptions under which the entry liquidity
check is sufficient. Would your answer change with SMP, conditional legs or
a later child amendment?

### Strategy design challenge

Choose a pairs trade, a three-symbol rotation, or an OCO-protected long.
Give another student your strategy and ask them to break its assumptions
using one of the failure cases above.

Submit a short worksheet containing:

1. The thesis and a losing scenario — not just the expected profit.
2. Symbols, sides, quantities, tick-valid prices and the hedge-ratio argument.
3. Entry and exit commands, including who supplies the opposing liquidity.
4. Predicted ACKs, fills, cancellations and parent states for a successful
   run, a one-share liquidity shortfall and a partial-fill interruption.
5. Actual fills and position changes, gross P&L, and a plan for residual
   exposure if the strategy cannot complete.
6. What remains live at session close or restart, and who can cancel it.

**Completion standard:** the peer must reproduce the successful run and one
failure case. A parent ACK, an empty `ORDERS` list or a sibling cancellation
alone is not evidence that the intended strategy executed.

## Further Reading

- [Combo Orders](../participant-guide/part-2-orders/030-combo-and-oco-orders.md)
- [ALF Protocol — OCO and Combo Orders](../protocols-and-clients/part-2-specifications/010-alf.md)

 

**Next:** [11 — Risk Controls](110-risk-controls.md)

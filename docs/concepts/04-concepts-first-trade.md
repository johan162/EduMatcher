# Your First Trade

!!! note "Learning objectives"
    After completing this walkthrough you will have:

    - Started EduMatcher and connected two trading terminals
    - Submitted a limit order and watched it rest on the book
    - Executed a trade between two gateways
    - Read your fill confirmation, including who was maker and who was taker
    - Checked P&L in the clearing window
    - Cancelled and amended a resting order
    - Submitted a MARKET order

This is a step-by-step guided walkthrough. You need about 10 minutes and three
terminal windows. No prior trading knowledge is assumed — every term is
explained as it appears.

!!! tip "New to exchanges generally?"
    If terms like "order book", "bid/ask" or "matching" are unfamiliar, read
    [The Order Book](01-concepts-order-book.md) first — it explains the
    structure this walkthrough exercises. This chapter assumes that concept
    but not any EduMatcher-specific knowledge.



## Prerequisites

Install EduMatcher if you haven't yet — see
[Installation](../user-guide/005-installation.md). This walkthrough uses the
`pipx` / Poetry path, where each process runs in its own terminal:

```bash
pipx install edumatcher
mkdir edumatcher-session && cd edumatcher-session
pm-setup
```

`pm-setup` creates a data directory and deploys a default sample
configuration with three symbols (`AAPL`, `MSFT`, `TSLA`) and four gateways,
including `TRADER01` and `TRADER02` — the two we'll use below. Session
scheduling is disabled in the sample, so matching is available immediately;
you don't need to worry about auctions or session phases for this
walkthrough (see [A Full Trading Day](05-concepts-trading-day.md) for that,
later).

Verify the install worked:

```bash
pm-engine --version
```

If this doesn't work, re-read the installation guide and its troubleshooting
section.

!!! tip "Using the container install instead?"
    The exchange is already running — skip Step 1 below and open a shell
    inside the container for each terminal instead:

    ```bash
    cd ~/.edumatcher
    ./edumatcher.sh shell
    ```

    The container's default configuration has the same symbols and gateway
    IDs used here, so every command below works unchanged. You can also
    watch the trade land in the browser terminal at
    <http://localhost:8090>.



## Step 1 — Start the engine

Open a terminal and start the matching engine. Leave it running for the rest
of this walkthrough.

```bash
# Terminal 1 — Matching engine
pm-engine --verbose
```

Wait until it prints that it has bound its sockets and loaded the deployed
configuration.



## Step 2 — Connect two trading terminals

Open two more terminals and connect a console to the engine from each, using
the two gateway IDs from the sample configuration:

```bash
# Terminal 2 — First trader
pm-alf-console --id TRADER01
```

```bash
# Terminal 3 — Second trader
pm-alf-console --id TRADER02
```

Each terminal prints a short banner once connected:

```
Gateway TRADER01 connected.  Type HELP for commands.  Tab=complete  ↑↓=history  Ctrl-A/E=line start/end

[TRADER01]>
```

The `[TRADER01]>` prompt means you're ready to enter commands. Every event
the engine sends back — fills, acknowledgements, rejections — appears
inline in this same window, prefixed with a `[HH:MM:SS.mmm]` timestamp, so
keep an eye on it after every command.



## Step 3 — Check what symbols are available

At the `[TRADER01]>` prompt, type:

```
SYMBOLS
```

You should see a table of active instruments:

```
┌─────────────────────────────────────────────────────────┐
│                    Active Instruments                   │
├────┬────────┬──────┬────────────┬────────────┬─────────┤
│  # │ Symbol │ Tick │ MM Enforced │ Max Spread │ Min Qty │
├────┼────────┼──────┼────────────┼────────────┼─────────┤
│  1 │ AAPL   │ 0.01 │ YES         │         10 │     100 │
│  2 │ MSFT   │ 0.01 │ NO          │         10 │     100 │
└────┴────────┴──────┴────────────┴────────────┴─────────┘
```

All examples in this walkthrough use `AAPL`.

!!! note
    `SYMBOLS` only lists symbols that already have an active order book — one
    is created the first time an order (or a seeded market-maker quote)
    arrives for it. It's normal to see fewer symbols here than are defined in
    `engine_config.yaml` if nothing has traded them yet.



## Step 4 — Submit a passive LIMIT BUY (make liquidity)

A **LIMIT BUY** order says: *"I want to buy X shares, but only at this price
or lower."* If no one is selling at that price right now, the order **rests
on the book** — it waits until someone is willing to sell at your price.

At the `[TRADER01]>` prompt:

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00|TIF=DAY
```

**What each field means:**

| Field | Value | Meaning |
|-------|-------|---------|
| `SYM` | `AAPL` | The symbol (instrument) you want to trade |
| `SIDE` | `BUY` | You want to buy |
| `TYPE` | `LIMIT` | Price-limited order — won't fill above $150.00 |
| `QTY` | `100` | 100 shares |
| `PRICE` | `150.00` | Maximum price you'll pay |
| `TIF` | `DAY` | Time-in-force: expires at the end of the trading day if never filled |

You should see the acknowledgement appear in the same window:

```
[09:31:02.104] ACK       a1b2c3d4  order accepted
```

The 8-character ID (`a1b2c3d4` here — yours will differ) is a short
reference used only for display in this console. Hold onto the idea that a
*full* order ID exists too — you'll need it for `AMEND` and `CANCEL` in
Steps 9 and 10.

Your order is now resting on the book, waiting for a seller at $150.00 or
better.



## Step 5 — Submit a matching LIMIT SELL (take liquidity)

Switch to the `[TRADER02]>` terminal and submit a sell order at the same
price:

```
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.00|TIF=DAY
```

Because TRADER01 has a resting bid at $150.00 and TRADER02 is now willing to
sell at $150.00, the prices **cross** — a trade happens immediately instead
of resting.



## Step 6 — Read the fill confirmation

Both terminals receive a `FILL` line the moment the trade executes.

In the `TRADER01` window:

```
[09:31:07.552] FILL      a1b2c3d4  qty=100 @150.00  remaining=0  [FILLED]
```

In the `TRADER02` window:

```
[09:31:07.552] FILL      e5f6a7b8  qty=100 @150.00  remaining=0  [FILLED]
```

`remaining=0` and `[FILLED]` mean the whole order is done; a partial fill
would instead show `remaining=<n>` and `[PARTIAL]`, leaving the rest of the
order still resting on the book.

This is also the moment to connect the fill back to the maker/taker idea
from [The Order Book](01-concepts-order-book.md#passive-vs-aggressive-orders):
TRADER01's LIMIT BUY was already resting on the book when the trade
happened, so TRADER01 was the **maker**; TRADER02's LIMIT SELL crossed the
spread to match it, so TRADER02 was the **taker**.

You don't have to work that out from who submitted first, though. Every fill
also carries the derived `liquidity_flag` directly — you just have to ask
for it. The plain `FILL` line above doesn't print it (it's a terse,
high-frequency console line by design), but two other views show it
explicitly:

- **Drop-copy**, if you start the console with `--drop-copy` (or send
  `DC|STATE=ON` once connected), prints one extra line per fill:

  ```
  [09:31:07.552] DC_FILL   a1b2c3d4  AAPL  qty=100 @150.00  [MAKER]  #4821  (drop_copy.event.TRADER01)
  ```

  TRADER02's window would show the mirror image, tagged `[TAKER]`.

- The **REST/WebSocket API** puts it on every `order.fill` event as
  `data.liquidity_flag`, no extra opt-in required — see
  [order.fill in the API Gateway guide](../user-guide/260-api-gateway.md).

If you'd rather see this live without switching consoles, reconnect with
`pm-alf-console --id TRADER01 --drop-copy` and repeat Steps 4–6 — the
`DC_FILL  ...  [MAKER]` / `[TAKER]` lines will appear right alongside the
ordinary `FILL` lines.

!!! note "Watching the book empty out"
    If you have a fourth terminal free, run `pm-viewer --symbol AAPL` before
    Step 4 and watch it live: the bid at $150.00 appears after Step 4 and
    disappears the instant the trade in Step 6 consumes it. `pm-viewer` is
    covered in [Processes](../user-guide/170-processes.md).



## Step 7 — Check P&L in the clearing window

Open a fourth terminal and start the clearing process:

```bash
# Terminal 4 — Clearing / P&L tracker
pm-clearing
```

After a moment it prints a P&L Summary table covering every position it has
seen fills for:

```
                              P&L Summary
┌──────────┬────────┬─────────┬──────────┬────────┬──────────┬────────────┬───────────┐
│ Gateway  │ Symbol │ Net Qty │ Avg Cost │  Mark  │ Realized │ Unrealized │ Total P&L │
├──────────┼────────┼─────────┼──────────┼────────┼──────────┼────────────┼───────────┤
│ TRADER01 │ AAPL   │    +100 │   150.00 │ 150.00 │    +0.00 │      +0.00 │     +0.00 │
│ TRADER02 │ AAPL   │    -100 │   150.00 │ 150.00 │    +0.00 │      +0.00 │     +0.00 │
└──────────┴────────┴─────────┴──────────┴────────┴──────────┴────────────┴───────────┘
```

`pm-clearing` re-prints this table after every trade batch, so from now on
just watch this window after each fill.

**Reading the P&L:**

- **TRADER01** bought 100 shares at $150.00 and now has a **long position**
  (`Net Qty +100`). Unrealized P&L is $0 because the mark price is still
  $150.00 — no gain or loss yet.
- **TRADER02** sold 100 shares it doesn't hold, so it is now **short** 100
  shares (`Net Qty -100`). Its P&L is also $0 at this instant, for the same
  reason.

For the full mechanics behind avg cost, realized and unrealized P&L —
including what happens when a position adds, reduces, or flips sides — see
[P&L & Clearing](../user-guide/130-pnl-clearing.md).



## Step 8 — Close the position for a profit

From `[TRADER01]>`, post another order to close the long position at a
higher price:

```
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=152.00|TIF=GTC
```

`TIF=GTC` (Good-Till-Cancelled) means this order isn't tied to today's
trading day: it's persisted and reloaded automatically at the start of the
next session if it doesn't fill today. It rests on the ask side of the book,
waiting for a buyer at $152.00.

From `[TRADER02]>`, buy back the short position at that price:

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=152.00|TIF=DAY
```

Another trade executes immediately. The clearing window updates:

```
                              P&L Summary
┌──────────┬────────┬─────────┬──────────┬────────┬──────────┬────────────┬───────────┐
│ Gateway  │ Symbol │ Net Qty │ Avg Cost │  Mark  │ Realized │ Unrealized │ Total P&L │
├──────────┼────────┼─────────┼──────────┼────────┼──────────┼────────────┼───────────┤
│ TRADER01 │ AAPL   │      +0 │        — │ 152.00 │  +200.00 │      +0.00 │   +200.00 │
│ TRADER02 │ AAPL   │      +0 │        — │ 152.00 │  -200.00 │      +0.00 │   -200.00 │
└──────────┴────────┴─────────┴──────────┴────────┴──────────┴────────────┴───────────┘
```

TRADER01 bought at $150 and sold at $152 — **$2 × 100 shares = $200 realized
profit**. TRADER02 sold at $150 and bought back at $152 — **$200 realized
loss**. Both are now flat (`Net Qty 0`, `Avg Cost —`).



## Step 9 — Submit and cancel a resting order

Submit a new bid that won't fill immediately:

```
# From [TRADER01]>
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=148.00
```

You'll get an ACK with a short display ID, e.g.:

```
[09:34:15.881] ACK       f9e8d7c6  order accepted
```

To cancel or amend it you need the *full* order ID, not the short one shown
above. Ask the engine for it:

```
ORDERS
```

This prints your resting orders with their full UUIDs. Copy the one matching
this order, then cancel it:

```
CANCEL|ID=<full-order-uuid>
```

The engine confirms:

```
[09:34:22.017] CANCELLED f9e8d7c6
```

!!! warning "Short ID vs. full order ID"
    The 8-character ID on `ACK`/`FILL` lines is display-only. `AMEND` and
    `CANCEL` both require the full UUID from `ORDERS` — this is the single
    most common mistake when scripting or typing commands by hand. See
    [Common mistakes and fast triage](../user-guide/055-alf-console.md#common-mistakes-and-fast-triage)
    for more.



## Step 10 — Amend an existing order

Sometimes you want to change your mind without withdrawing completely —
maybe you'd take a slightly higher price, or want fewer shares. `AMEND`
updates a **resting** LIMIT order in place, without losing your spot in the
queue any more than necessary.

From `[TRADER01]>`, post a new resting bid and note its full ID via
`ORDERS` as in Step 9:

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=148.00
ORDERS
```

Now change the price to $149.00 and reduce the quantity to 30 shares:

```
AMEND|ID=<full-order-uuid>|PRICE=149.00|QTY=30
```

The engine confirms the change:

```
[09:35:40.229] AMENDED   f9e8d7c6  price=149.0 qty=30 remaining=30
```

You can amend the price, the quantity, or both in a single command. You
cannot amend a fully filled or cancelled order.

!!! warning "Queue priority"
    Amending an order can cost you your **time priority** in the queue,
    mirroring real exchanges:

    - **Price change** — always loses priority. The order moves to the back
      of the new price level's queue.
    - **Quantity increase** — loses priority, for the same reason.
    - **Quantity decrease** — priority is **preserved**. Reducing your size
      is a concession to the market, so exchanges reward it.

    In the example above, both the price change ($148 → $149) *and* the
    quantity reduction (50 → 30) happen in one command. The price change
    dominates — the order goes to the back of the $149.00 queue.



## Step 11 — Try a MARKET order

A MARKET order doesn't specify a price — it says "buy/sell at whatever is
available right now." First, make sure there's something to trade against.

From `[TRADER02]>`, post a resting sell:

```
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=151.00|TIF=DAY
```

Now from `[TRADER01]>`, sweep it with a market buy:

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
```

The fill confirms immediately at $151.00 — the resting sell's price, not a
price TRADER01 chose:

```
[09:36:51.703] FILL      12ab34cd  qty=100 @151.00  remaining=0  [FILLED]
```

You didn't choose the price; you prioritized speed and certainty of
execution over price control.



## Summary

You have completed a full basic trading session:

| Step | What you did | Concept learned |
|------|-------------|-----------------|
| 1–2 | Started the engine and connected two terminals | System topology |
| 3 | Queried symbols | System state |
| 4 | Posted a LIMIT BUY | Passive / maker order, resting on book |
| 5 | Posted a matching LIMIT SELL | Aggressive / taker order, price crossing |
| 6 | Read the fill confirmation | Order lifecycle, `liquidity_flag` (drop-copy / API) |
| 7 | Checked P&L | Long/short positions, unrealized P&L |
| 8 | Closed positions for profit/loss | Realized P&L |
| 9 | Cancelled a resting order | Order cancellation, short ID vs. full order ID |
| 10 | Amended a resting order | In-place price/qty update, queue priority |
| 11 | Submitted a MARKET order | Immediacy vs. price certainty |



## What next?

- [Order Types](../user-guide/060-order-types.md) — all order types with detailed mechanics
- [A Full Trading Day](05-concepts-trading-day.md) — auctions, session phases, and daily lifecycle
- [P&L & Clearing](../user-guide/130-pnl-clearing.md) — full explanation of VWAP cost basis and realized vs. unrealized
- [ALF Console](../user-guide/055-alf-console.md) — the full command reference for everything used in this walkthrough (quotes, OCO, combos, drop-copy, and more)


[Glossary →](../glossary.md)

# Your First Trade

!!! note "Learning objectives"
    After this walkthrough you will have:

    - put a limit order into an empty order book and watched it rest there
    - made it trade with an order from a second participant
    - read the fill, and worked out who was the *maker* and who the *taker*
    - checked your position and your realized profit or loss
    - cancelled and amended a resting order
    - sent a market order

**Time:** about 30 minutes. **You need:** the exchange from
[Install and Start](020-install-and-start.md) and three terminal windows. No
trading knowledge is assumed — every term is explained where it first
appears.

!!! tip "Two ideas before you start"
    An **order book** is the list of everyone currently willing to buy a
    symbol (the *bids*) and everyone willing to sell it (the *asks*), best
    price first. An order **rests** in the book until an order from the other
    side arrives at a price that crosses it — then the two **match** and a
    trade happens. If you would like a fuller picture first, read
    [The Order Book](../../participant-guide/part-1-trading-basics/020-the-order-book.md)
    in the Participant Guide; it takes ten minutes.

## Step 1 — Prepare an empty market

To see your own orders clearly, start from a market with no other orders in
it: no seeded quotes and no market-maker bot. The bundled configuration
`s3-basic-nomm` has three symbols (`AAPL`, `MSFT`, `TSLA`), the same four
participants as before, no trading-day schedule and *no market-maker quotes*
("nomm").

**Containers.** In `~/.edumatcher`, choose the configuration, switch the
process profile from `mm-demo` to `default` (the same processes without the
market-maker bot) and restart:

```bash
cd ~/.edumatcher
./edumatcher.sh config s3-basic-nomm
sed -i.bak 's/^EM_PROFILE=.*/EM_PROFILE=default/' .env
./edumatcher.sh restart
```

The `sed` line just edits one setting in the file `.env`; you can make the
same change in any text editor. Then open **two** terminals and run
`./edumatcher.sh shell` in each, so both are inside the exchange.

**Python package.** Deploy the same configuration and restart the processes:

```bash
pm-opctl-cli stop
pm-setup --config s3-basic-nomm --force
pm-opctl-cli start
```

Then open two terminals with the same `EDUMATCHER_DATA_DIR`.

!!! tip "The minimal exchange, by hand"
    On the Python route you can also skip `pm-opctl-cli` and start only what
    a trade needs: run `pm-engine --verbose` in a third terminal and leave it
    running. That is the whole matching engine. Everything below works the
    same, except Step 7's `pm-clearing-cli`, which needs the `pm-clearing`
    recorder running *before* you trade.

## Step 2 — Connect two traders

In the first terminal, connect as `TRADER01`; in the second, as `TRADER02`:

```bash
pm-alf-console --id TRADER01
```

```bash
pm-alf-console --id TRADER02
```

`pm-alf-console` is the **trader console**: it connects you to the engine as
one participant, using the text order-entry protocol ALF. Each window prints a
banner and a prompt:

```text
Gateway TRADER01 connected.   — Student desk 1 Type HELP for commands.
Tab=complete  ↑↓=history  Ctrl-A/E=line start/end

[TRADER01]>
```

Everything the engine sends back to you — acknowledgements, fills,
rejections — appears in the same window with a `[HH:MM:SS.mmm]` timestamp.
Type `HELP` at any time to list the commands.

## Step 3 — See what you can trade

At the `[TRADER01]>` prompt, type:

```text
SYMBOLS
```

```text
                       Active Instruments
┏━━━━━━┳━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━┓
┃ #    ┃ Symbol     ┃ Tick ┃ MM Enforced ┃ Max Spread ┃ Min Qty ┃
┡━━━━━━╇━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━┩
│ 1    │ AAPL       │ 0.01 │     NO      │         20 │     100 │
│ 2    │ MSFT       │ 0.01 │     NO      │         20 │     100 │
│ 3    │ TSLA       │ 0.01 │     NO      │         20 │     100 │
└──────┴────────────┴──────┴─────────────┴────────────┴─────────┘
```

`Tick` is the smallest price step: AAPL prices are whole cents. The other
columns are market-maker rules, which this configuration does not enforce.
Every example below uses `AAPL`.

## Step 4 — Place a buy order that rests

A **limit order** says: *"I want to buy (or sell) this many shares, but only
at this price or better."* At the `[TRADER01]>` prompt:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00|TIF=DAY
```

| Field | Value | Meaning |
|---|---|---|
| `SYM` | `AAPL` | The symbol to trade |
| `SIDE` | `BUY` | You want to buy |
| `TYPE` | `LIMIT` | Never pay more than `PRICE` |
| `QTY` | `100` | 100 shares |
| `PRICE` | `150.00` | The most you will pay per share |
| `TIF` | `DAY` | *Time in force*: the order expires at the end of the trading day if it has not traded |

The engine acknowledges it:

```text
[09:31:02.104] ACK       855b6f946fe9cb7ae96bbda1c8d1dc06  order accepted
```

The long hexadecimal string is the **order ID**. You will need it to cancel
or amend an order, so it is worth knowing where to find it: here, and in the
`ORDERS` list you will use in Step 9.

Nobody is selling, so nothing trades. Your order now **rests** in the book as
the best bid. If you have the container route, look at AAPL in the Order Book
Viewer (<http://localhost:8094>) or on TapeDeck (<http://localhost:8090>): a
bid of 100 at 150.00 has appeared where there was nothing.

## Step 5 — Sell into it

Switch to the `[TRADER02]>` window and offer to sell at the same price:

```text
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.00|TIF=DAY
```

TRADER01 is willing to pay 150.00 and TRADER02 is willing to accept 150.00:
the prices **cross**, so the engine matches the two orders at once instead of
letting the sell order rest.

## Step 6 — Read the fill confirmation

Both windows receive a `FILL` line the moment the trade happens. In
`TRADER01`'s window:

```text
[09:31:07.552] FILL      855b6f946fe9cb7ae96bbda1c8d1dc06  qty=100 @150.0  remaining=0  [FILLED]
```

TRADER02 sees the same for its own order ID. `remaining=0` and `[FILLED]`
mean the whole order traded. A partial fill would show `remaining=<n>` and
`[PARTIAL]`, and the rest of the order would keep resting in the book.

This is the moment to meet two words used everywhere on exchanges:

- TRADER01's order was already resting in the book and *provided* the
  liquidity: TRADER01 was the **maker**.
- TRADER02's order arrived and *took* that liquidity: TRADER02 was the
  **taker**.

You can ask the engine to state this for every fill. Start a console with
`--drop-copy` (or type `DC|STATE=ON` in a connected one) and each of your fills
is followed by a **drop-copy** line carrying the flag:

```text
[09:31:07.552] DC_FILL   855b6f946fe9cb7ae96bbda1c8d1dc06  AAPL  qty=100 @150.0  [MAKER]  #1  (drop_copy.event.TRADER01)
```

Drop copy is the independent copy of fills that a firm's risk and compliance
staff receive. The Participant Guide covers it in
[The Trader Console](../../participant-guide/part-2-orders/010-the-trader-console.md).

## Step 7 — Check your position and P&L

Your **position** is how many shares you hold: positive after buying (*long*),
negative after selling shares you did not have (*short*). At the
`[TRADER01]>` prompt:

```text
POS
```

```text
                                   Positions
┏━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Symbol   ┃  Net Qty ┃   Avg Cost ┃    Last Px ┃   Unreal P&L ┃     Real P&L ┃
┡━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ AAPL     │     +100 │     150.00 │     150.00 │        +0.00 │        +0.00 │
└──────────┴──────────┴────────────┴────────────┴──────────────┴──────────────┘
```

TRADER01 is long 100 shares bought at an average cost of 150.00. The last
trade price is also 150.00, so the **unrealized** P&L (the gain or loss you
would make by closing the position at the last price) is zero. TRADER02 is
short 100, also at zero. Nothing is **realized** yet, because neither has
closed a position.

## Step 8 — Close the position at a profit

TRADER01 now offers the shares back at a higher price. From `[TRADER01]>`:

```text
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=152.00|TIF=GTC
```

`TIF=GTC` means *good till cancelled*: unlike a `DAY` order, it is saved when
the trading day ends and comes back the next day if it has not traded. It
rests on the ask side of the book. From `[TRADER02]>`, buy back the short
position at that price:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=152.00|TIF=DAY
```

The orders cross and trade. Type `POS` again at `[TRADER01]>`:

```text
┃ Symbol   ┃  Net Qty ┃   Avg Cost ┃    Last Px ┃   Unreal P&L ┃     Real P&L ┃
│ AAPL     │        0 │          — │          — │            — │      +200.00 │
```

TRADER01 bought at 150 and sold at 152: 2.00 × 100 shares = **200.00 realized
profit**, and a flat position. TRADER02 sold at 150 and bought back at 152 and
has realized a 200.00 loss. Every profit on an exchange is someone else's
loss or forgone gain: the exchange itself only matches.

The same figures are recorded by the `pm-clearing` recorder, which the full
process set starts for you. From any shell inside the exchange:

```bash
pm-clearing-cli pnl
```

```text
gateway_id | symbol | realized_pnl | unrealized_pnl | total_pnl | net_qty | mark_price | tick_decimals
-----------+--------+--------------+----------------+-----------+---------+------------+--------------
TRADER01   | AAPL   | 200          | 0              | 200       | 0       | 152        | 2
TRADER02   | AAPL   | -200         | 0              | -200      | 0       | 152        | 2
```

!!! warning "Recorders only record what they see"
    `pm-clearing`, `pm-stats` and `pm-audit` only capture trades that happen
    while they are running. If you started the engine by hand and
    `pm-clearing` afterwards, its figures miss the earlier trades and will
    not match `POS`. That is why the process manager starts the recorders
    before the engine.

## Step 9 — Cancel a resting order

Post a bid that will not trade straight away. From `[TRADER01]>`:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=148.00|TIF=DAY
```

To cancel an order you need its ID. Copy it from the `ACK` line, or list your
orders:

```text
ORDERS
```

```text
┃ ID                               ┃ Symbol ┃ Side ┃ Type  ┃ TIF ┃ Qty ┃ Rem ┃ Price ┃ Status ┃ Time     ┃
│ a129aadacb20eaf85c4eef86386be6e9 │ AAPL   │ BUY  │ LIMIT │ DAY │  50 │  50 │ 148.0 │ NEW    │ 09:34:15 │
│ 9ceca6d5db612b51d2dcb94ea880055f │ AAPL   │ SELL │ LIMIT │ GTC │ 100 │   0 │ 152.0 │ FILLED │ 09:32:40 │
│ 855b6f946fe9cb7ae96bbda1c8d1dc06 │ AAPL   │ BUY  │ LIMIT │ DAY │ 100 │   0 │ 150.0 │ FILLED │ 09:31:02 │
```

Then cancel it with the full ID:

```text
CANCEL|ID=a129aadacb20eaf85c4eef86386be6e9
```

```text
[09:34:22.017] CANCELLED a129aadacb20eaf85c4eef86386be6e9
```

!!! tip "Use the whole ID"
    `CANCEL` and `AMEND` need the complete 32-character order ID. In a narrow
    terminal window the `ORDERS` table shortens the ID column (`a129aa…`);
    widen the window, or copy the ID from the `ACK` line instead.

## Step 10 — Amend a resting order

Sometimes you want to change an order rather than withdraw it. Post a new bid,
note its ID, and then change its price to 149.00 and its quantity to 30:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=148.00|TIF=DAY
AMEND|ID=<the new order's ID>|PRICE=149.00|QTY=30
```

```text
[09:35:40.229] AMENDED   73cfaf47645825b341c93513a908bd81  price=149.0 qty=30 remaining=30 (priority reset)
```

`(priority reset)` matters. Orders at the same price trade in the order they
arrived — **price-time priority** — and an amendment can cost you your place
in that queue, just as on real exchanges:

- **a price change** always sends the order to the back of the queue at its
  new price;
- **a quantity increase** does too;
- **a quantity decrease** keeps your place, because offering less is no
  disadvantage to anyone already waiting.

Here the price changed, so the order lost its priority.

## Step 11 — Send a market order

A **market order** has no price: it says *"buy (or sell) now, at the best
prices available"*. First give it something to trade against. From
`[TRADER02]>`:

```text
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=151.00|TIF=DAY
```

Then, from `[TRADER01]>`:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
```

```text
[09:36:51.703] FILL      53d7d9eae488049000d4131a1729cd07  qty=100 @151.0  remaining=0  [FILLED]
```

It filled at 151.00 — the resting seller's price, not one you chose. A market
order trades certainty of execution for control over the price. In a thin
book that can be an expensive trade, which is why the Participant Guide's
[Order Types](../../participant-guide/part-2-orders/020-order-types.md)
chapter spends some time on it.

## Summary

| Step | What you did | What it taught you |
|---|---|---|
| 1–2 | Prepared an empty market and connected two traders | Participants, the trader console |
| 3 | Listed the symbols | Instruments and tick size |
| 4 | Posted a limit buy that rested | Bids, resting orders, order IDs |
| 5–6 | Sold into it and read the fills | Crossing prices, fills, maker and taker |
| 7 | Looked at your position | Long, short, unrealized P&L |
| 8 | Closed the position | Realized P&L, `GTC`, recorders |
| 9 | Cancelled an order | Order IDs, `ORDERS` |
| 10 | Amended an order | Price-time priority |
| 11 | Sent a market order | Immediacy versus price |

!!! tip "Back to the full demo market"
    To get the market-maker bot and the ten-symbol configuration back on the
    container route, run `./edumatcher.sh config s10-basic`, set
    `EM_PROFILE=mm-demo` again in `.env`, and `./edumatcher.sh restart`.

## Where to go next

- [The Browser Applications](040-the-browser-applications.md) — the same
  market through the trading screen and the market displays.
- [Order Types](../../participant-guide/part-2-orders/020-order-types.md) —
  every order type, with its exact behavior.
- [The Trader Console](../../participant-guide/part-2-orders/010-the-trader-console.md)
  — every command you can type at the `[TRADER01]>` prompt.
- The Training Guide's [The First Trade](../../training-guide/030-the-first-trade.md)
  — the same ground as exercises with checkpoints.

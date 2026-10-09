# The Browser Applications

!!! note "Learning objectives"
    After this chapter you will know:

    - what each of the five browser applications is for
    - how to log in to the Trading GUI with an API key, and where to find one
    - how to place the same kind of order from the browser that you typed in
      the trader console

**Time:** about 15 minutes. **You need:** the container installation from
[Install and Start](020-install-and-start.md). The browser applications are
not part of the Python package.

## Five windows on one exchange

All five applications talk to the same running exchange, so anything you do
in one — or in a `pm-alf-console` — shows up in the others within a second.

| Address | Application | Read-only? | Use it to… |
|---|---|---|---|
| <http://localhost:8090> | **TapeDeck** (`pm-terminal`) | yes | watch prices, trades, auctions and halts across all symbols — a classroom wallboard |
| <http://localhost:8094> | **Order Book Viewer** (`pm-book`) | yes | see every price level of one symbol's book, its statistics and its trade tape |
| <http://localhost:8093> | **Trading GUI** (`pm-trading-ui`) | no | trade, quote or operate the exchange through screens instead of commands |
| <http://localhost:8091> | **Log Operator Console** (`pm-log-ui`) | yes | read what every process is doing, and why something was rejected |
| <http://localhost:8092> | **Configuration GUI** (`config-gui`) | — | build an exchange configuration with forms instead of YAML |

The read-only displays need no login. The Trading GUI does, because it can
change things.

## Find your API key

The Trading GUI logs in with an **API key**. Each key in the configuration
belongs to one participant, and the participant's role (`TRADER`,
`MARKET_MAKER` or `ADMIN`) decides which screens you get. The bundled
configurations generate their keys, so look them up in the running exchange:

```bash
./edumatcher.sh shell pm-config-show -a
```

The `-a` option shows everything, including the keys in full. Look for the
**API KEYS** panel:

```text
╭─  API KEYS  ───────────────────────────────────────────────────────────╮
│ GATEWAY ID      API GW        ROLE             API KEY                 │
│ TRADER01        desk          TRADER           key-trader01-z8hu5h     │
│ TRADER02        desk          TRADER           key-trader02-199pf4     │
│ OPS01           desk          ADMIN            key-ops01-tvj553        │
│ MM01            desk          MARKET_MAKER     key-mm01-tp6aoi         │
│ —               dashboards    READ-ONLY        key-readonly-z6f1hx     │
╰────────────────────────────────────────────────────────────────────────╯
```

Your keys will be different. The `READ-ONLY` key is the one the two displays
use behind the scenes; it cannot log in to the Trading GUI.

## Trade from the browser

1. Open <http://localhost:8093>, paste `TRADER01`'s key and click
   **Connect**. You land in the **Trading Workspace**: a price chart, a depth
   ladder (the order book, best prices in the middle), an order ticket and a
   blotter of your working orders.
2. Open the Order Book Viewer at <http://localhost:8094> in a second window,
   on the same symbol.
3. In the ticket, choose **Limit**, enter a quantity and a price below the
   best ask, and press **Buy**. A toast confirms *accepted*, the order appears
   in the blotter, and the Order Book Viewer shows it as a new bid.
4. Sell into it from a trader console (or log in as `TRADER02` in a private
   browser window) and watch the trade appear on the tape in both windows and
   on TapeDeck.

!!! tip "Reloading logs you out"
    The Trading GUI keeps your key in memory only, never on disk. Reloading
    the page returns you to the login screen. That is deliberate, not a
    fault.

Log in with `OPS01`'s key instead and you get the operator's screens: the
system dashboard, session control, halts, circuit breakers and the kill
switch. Log in as `MM01` for the market maker's quote management.

## When a display looks empty

- **TapeDeck shows symbols but no trades.** Nobody has traded yet. Quotes are
  not trades.
- **The Order Book Viewer shows an empty ladder.** The book has no orders.
  On `s3-basic-nomm` with the `default` profile that is the expected state
  until you trade.
- **A banner says the application is disconnected or reconnecting.** The
  exchange is stopped or restarting. Check `./edumatcher.sh status`.

## Where to go next

Each application has its own chapter in the Participant Guide —
[TapeDeck](../../participant-guide/part-6-front-ends/010-trading-info-terminal.md),
the [Trading GUI](../../participant-guide/part-6-front-ends/020-trading-platform-gui.md)
and the [Order Book Viewer](../../participant-guide/part-6-front-ends/030-order-book-gui.md)
— and the Operator's Guide covers the
[Log Operator Console](../../operator-guide/part-6-observe-and-recover/050-log-console.md)
and the [Configuration GUI](../../operator-guide/part-2-configure/030-config-gui.md).
Part II of this guide continues with
[Run a Trading Session](../part-2-next-steps/010-run-a-trading-session.md).

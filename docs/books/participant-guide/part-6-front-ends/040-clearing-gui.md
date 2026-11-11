# Clearing GUI (`pm-clearing-ui`)

!!! note "Learning objectives"
    After reading this page you will understand:

    - What the Clearing GUI shows, and what it deliberately does not
    - How to log in, and what each role (trader, market maker, ADMIN) sees
    - How to read its money columns: ticks, display currency and minor units
    - Why a fill can take a few seconds to appear, and how far back trades go
    - What an EOD settlement and the derived balance are — and are not
    - How to tell "nothing there" from "could not be read"


## Overview

The **Clearing GUI** is a read-only browser view of the post-trade record:
your positions and P&L, the trades behind them, your position at every close,
and the end-of-day settlement amounts. It reads only what
[`pm-clearing`](../part-5-positions-and-results/010-positions-and-pnl.md) and
[`pm-eod`](../part-5-positions-and-results/020-your-end-of-day-statement.md)
recorded, through the API gateway's `/api/v1/clearing` routes. Its source
lives in `web-apps/clearing-gui/`; it is served on port **8096**.

There is nothing to change here: no orders, no settings that reach the
exchange. Use the [Trading GUI](020-trading-platform-gui.md) to trade, and
this application to see what clearing made of it.

It shows no margin, equity, collateral, buying power or open interest. The
exchange computes none of them, so the GUI does not invent them.


## Logging in

Open <http://localhost:8096> and paste your gateway's API key — the same key
the Trading GUI takes. The key stays in the browser tab's memory only;
reloading the page asks for it again.

| Your key | You land on | You can open |
|---|---|---|
| A `TRADER` gateway | My Positions | My Positions, My Trades, Daily & Close History, EOD Settlement, Gateway Sessions |
| A `MARKET_MAKER` gateway | My Positions | The same, plus My Quote Obligations |
| An `ADMIN` gateway | Clearing Overview | The whole venue — see the [operator chapter](../../operator-guide/part-6-observe-and-recover/080-clearing-gui.md) |
| A read-only key | — | Nothing: a read-only key has no gateway, so it has no clearing record |

Every screen shows **your gateway only**. The API enforces that, not the
browser: asking it for another gateway's data is refused with
`SCOPE_DENIED`, and typing an ADMIN address into the address bar just takes
you back to My Positions.


## The screens

**My Positions** — each symbol you hold: signed quantity (negative is short),
average cost, mark, realized and unrealized P&L, what you bought and sold,
and, below it, the same positions valued at their marks (net and gross
notional). The line above the table says when clearing last committed your
data. It refreshes every 5 seconds.

**My Trades** — every execution clearing still holds for you, newest first,
200 at a time (**Load more** for the next page). *Exchange time* is when the
exchange printed the trade; *Clearing ingest* is when clearing wrote it. You
see your own side of each trade: the other side's gateway and order id are
blank. *Match type* says how the trade came about (continuous trading, an
auction), and *Audit msg id* links the row to the exchange's audit trail.
Filter by symbol and by day.

**Daily & Close History** — per day and symbol: what you traded, the day's
realized P&L and your position after the day's last trade; and your
cumulative P&L at every session close, as a table and a chart. The chart has
one point per close: the exchange keeps no intraday history, and the GUI
does not draw one.

**EOD Settlement** — your daily settlement amounts and the balance they add
up to (see below), with the run status of each day's `pm-eod`.

**Gateway Sessions** — when clearing saw your gateway connect and
disconnect, and why it disconnected.

**My Quote Obligations** (market makers) — for each symbol, whether the
engine enforces a quoting obligation for you, the widest spread and the
smallest size that satisfy it. This is the configuration the engine checks
your quotes against, not a score of how you quoted.


## Reading the numbers

**Ticks and decimals.** Clearing stores money in ticks of each symbol's
precision: 18 750 ticks of a 2-decimal symbol is 187.50, while 10 862 ticks
of a 4-decimal symbol is 1.0862. Every cell is converted with its own row's
precision, so a 4-decimal symbol shows 4 decimals. Totals across symbols —
such as the cumulative P&L of each close in Daily & Close History — are added
up only after that conversion.

**Settlement amounts are a different unit.** They are whole cents of the
display currency (minor units), always shown with 2 decimals, and exact.

**Lag.** `pm-clearing` writes fills in batches — every 100 trades, or every
5 seconds. A fill can take up to 5 seconds to appear; the freshness line
tells you when the shown data was committed.

**Retention.** Raw trades are kept for a retention window (90 days by
default). My Trades states the oldest day still held. Older days are gone
from the trade list but stay in Daily & Close History.

**Empty is zero; an error says so.** An empty table means there really is
nothing to show — you have not traded, or nothing matches the filter. When a
request fails, the screen says why instead: a refused request, the clearing
or EOD ledger being unavailable (`CLEARING_DB`, `EOD_DB`), a reply the GUI
does not understand (an API contract error — the GUI and gateway versions
differ), or the API gateway not answering. The top bar's *API connected* /
*API unreachable* shows the last request's outcome.


## EOD settlement and the derived balance

After each session closes, `pm-eod` settles the day: for every gateway it
takes the change in cumulative P&L between the previous close and this one,
and records it as that day's **settlement amount**. A positive amount means
the exchange owes you; a negative one, that you owe the exchange. The
amounts of a day add up to zero across all gateways (any rounding cent goes
to the exchange's own `EXCHANGE` account, which only an ADMIN sees).

Your **derived balance** is your opening balance (from the exchange's
roster) plus every settlement up to a date — *Balance as of* picks the date.
It is computed when you ask; it is not an account balance stored anywhere.

Neither is margin, collateral or a completed payment, and both exist only
after `pm-eod` has settled a day: today's P&L on My Positions is not a
settlement. See [Your End-of-Day Statement](../part-5-positions-and-results/020-your-end-of-day-statement.md).


## When something looks wrong

| You see | Meaning | What to do |
|---|---|---|
| *Invalid API key.* | The gateway does not know the key | Check the key with your instructor or operator |
| *This is a read-only key* | The key has no gateway | Use your trading gateway's key |
| *Not permitted (SCOPE_DENIED)* | You asked for another gateway's data | Nothing to fix: you can see only your own |
| *CLEARING_DB: … unavailable* | The API gateway cannot read the clearing ledger | Tell the operator; `pm-clearing` may not be deployed |
| *EOD_DB: … unavailable* | The settlement ledger cannot be read | Settlement screens only; tell the operator |
| *No settlements* | `pm-eod` has not settled a day in that range | Wait for the end of day |
| *API unreachable* | The API gateway does not answer | Tell the operator; `pm-api-gwy` may be down |
| A fill is missing | It may not be committed yet | Wait 5 seconds |

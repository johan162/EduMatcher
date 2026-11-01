# Your End-of-Day Statement

!!! note "Learning objectives"
    After reading this page you will be able to:

    - Read your daily statement from top to bottom and explain every line
    - Say, in your own words, what *position*, *closing price*, *profit and loss*, *settlement* and *balance* mean
    - Work out for yourself whether your statement is right
    - Know what to do if you think it is wrong

    **No finance background is needed.** Every word is explained here.

## What the statement is

When the market closes for the day, the exchange adds up how each trader did
and writes you a short **statement**, like the one your bank sends you. It tells
you three things:

1. **How much you gained or lost today** — and so whether *you owe the exchange*
   or *the exchange owes you*.
2. **What you still hold** when the market closed.
3. **Every trade you made** that day.

The money is **fictional**: your instructor decides what the numbers mean (points,
pretend dollars, a class competition). Nothing real is paid.

Your instructor gives you the statement as a file (usually
`statements/<your gateway name>.md`) or by email.

## An example, line by line

Here is the statement of a trader called Bob for Tuesday 3 November 2026:

```text
# Statement for 2026-11-03

Bob Berg (GW_BOB) <bob@example.org>

**The exchange owes you 30.00.**

- Today's result: 30.00
- Balance after today: -20.00

## Result by symbol

| Symbol | Result |
|---|---:|
| AAPL | 30.00 |

## Open positions at the close

| Symbol | Quantity | Closing price |
|---|---:|---:|
| AAPL | -150 | 10.20 |

## Trades

| Time (UTC) | Symbol | Side | Quantity | Price |
|---|---|---|---:|---:|
| 10:30:01 | AAPL | SELL | 50 | 10.20 |
```

### The heading and your name

`Statement for 2026-11-03` is the **trading date** — the day this statement is
about. `GW_BOB` is your **gateway**, the name your trading program connects
with. If your name is not listed, the statement shows only the gateway name and
adds *"This gateway is not in the roster"* — tell your instructor.

### The headline sentence

There are exactly three possible sentences:

| It says | It means |
|---|---|
| **The exchange owes you 30.00.** | You gained 30.00 today. Think of it as 30.00 *added* to your account. |
| **You owe the exchange 30.00.** | You lost 30.00 today. 30.00 is *taken* from your account. |
| **Nothing to pay or receive today.** | Your gain for the day was exactly zero — which is also what you get if you took no part in the market and held nothing. |

### Today's result and your balance

- **Today's result** is the same number as the headline, with a sign:
  positive means you gained, negative means you lost.
- **Balance after today** is the running total of all your daily results since
  the start, plus any starting amount your instructor gave you (your *opening
  balance*). It can be negative; a negative balance simply means you are down
  overall. It does not stop you trading.

### Result by symbol

A **symbol** is the short code of one company's shares (`AAPL`). If you traded
several, this table shows how much of today's result came from each.

### Open positions at the close

Your **position** is how many shares you hold in a symbol.

- A **positive** number means you *own* that many shares (you are **long**). You
  gain when the price rises.
- A **negative** number means you have *sold shares you did not own* (you are
  **short**). You gain when the price **falls**. Bob's `-150` means he is short
  150.
- If a symbol is missing, you hold none of it.

The **closing price** is the price of the *last trade of the day* in that symbol.
It is the price the exchange uses to put a value on what you hold overnight
(this is called **marking to market**).

### Trades

Each line is one trade you made: the time (in **UTC**, a worldwide reference
time that may differ from your local clock), the symbol, whether you bought
(**BUY**) or sold (**SELL**) — or **SELF** if both sides of the trade were yours —
how many shares, and at what price.

## Where today's number comes from

Your result is **the change in the value of your account since yesterday's
close**. Two kinds of profit go into it:

- **Unrealized profit or loss** — on paper, for shares you still hold. If you
  bought 100 shares at 10.00 and the closing price is 10.50, you are 100 × 0.50 =
  **50.00 up on paper**.
- **Realized profit or loss** — locked in because you closed part of a position.
  Buy at 10.00, later sell at 10.30: you realized 0.30 per share.

Add both together and subtract what the total was at the previous close. That
difference is today's result.

!!! example "Check Bob's number yourself"
    Bob has been short since day 1 at an average price of 10.00 for 100 shares,
    then sold 50 more at 10.20, so his average sale price is
    (100 × 10.00 + 50 × 10.20) ÷ 150 = **10.0667**.

    - At the closing price of 10.20 he is short 150, so on paper he has
      lost 150 × (10.20 − 10.0667) = **20.00**. (A short position *loses* when
      the price is above what you sold at.)
    - At yesterday's close the price was 10.50 and he was short 100 at 10.00, so
      he was **50.00** down on paper.
    - Today he is 20.00 down instead of 50.00 down — an improvement of
      **30.00**. That is exactly the 30.00 the statement says the exchange owes
      him.

    Notice Bob is still *down* overall (his balance is −20.00): he is owed 30.00
    for the improvement, but he had already paid 50.00 on day 1.

Everyone's results add up to exactly zero: whatever one trader gains, another
loses. If a statement says you gained, someone else's says they lost the same
amount.

## Questions

**Why was I paid even though I did not sell anything?**
Because you hold shares and their price rose. Your holdings are re-valued every
day, and you settle the *change*. If the price falls back tomorrow, tomorrow's
result is negative and takes it back.

**I did nothing today, so why is my result not zero?**
Because the market moved while you held a position. Doing nothing while holding
shares is still a bet on the price.

**Does a negative balance mean I am out of the game?**
No. It has no effect on whether you can trade.

**The price on my statement has two decimals — is that all of it?**
Prices are shown with the precision of the symbol (two decimals for most
symbols). Amounts of money always have two decimals.

**My statement looks wrong. What now?**
Tell your instructor which line you doubt. They can re-calculate without changing
anything (`pm-eod run --date <date> --dry-run`) and show you the closing
positions (`pm-clearing-cli snapshots --date <date>`) and your trades
(`pm-clearing-cli trades --gateway <your gateway>`). If a mistake is found,
the day is re-done and a corrected statement is written.

## Words used on this page

| Word | Meaning |
|---|---|
| **Share** | A small slice of ownership in a company |
| **Symbol** | The short code for a company's shares, such as `AAPL` |
| **Trade** | A buyer and a seller agreeing on a price and a quantity |
| **Gateway** | The connection your trading program uses; it has a name such as `GW_BOB` |
| **Position** | How many shares you hold (negative = short) |
| **Long / short** | Holding shares / having sold shares you do not own |
| **Closing price** | The price of the last trade of the day |
| **Marking to market** | Valuing what you hold at the latest market price |
| **Unrealized P&L** | Profit or loss on paper, on shares you still hold |
| **Realized P&L** | Profit or loss locked in by closing a position |
| **P&L** | "Profit and Loss" |
| **Settlement** | Turning each trader's gain or loss for the day into an amount to pay or receive |
| **Balance** | Your running total of daily results plus your opening balance |
| **Trading date** | The calendar date, in the exchange's own timezone, of the trading day |

For the full mechanics see [Positions and P&L](010-positions-and-pnl.md). How
the exchange produces this statement is described in the operator's chapter
[Closing the Day](../../operator-guide/part-4-run-a-market/100-closing-the-day.md).

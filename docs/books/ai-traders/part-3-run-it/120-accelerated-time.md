# Accelerated Time

!!! note "Learning objectives"
    After reading this chapter you will be able to:

    - Run the simulation's trading calendar faster than real time, and pick
      a speed for what you want to see
    - Say exactly what speeds up and what does not
    - Predict how a faster calendar changes the market you watch
    - Avoid the traps: restarts, dates in the statistics, auctions at high speed

## One setting

```bash
EM_SPEED=24 docker compose -f compose.ai-sim.yaml up -d
```

`EM_SPEED=N` runs the trading calendar N times faster than the clock on the
wall. At 24 a calendar day passes in an hour of wall time: the market opens,
trades through the day, closes, sleeps through the night and opens again an
hour later. Weekends and Swedish holidays pass too, at the same speed.
`EM_SPEED=1` (the default) is real time.

`EM_START` says where the faster calendar starts, as local time:

```bash
EM_SPEED=24 EM_START=2026-11-02T08:55 docker compose -f compose.ai-sim.yaml up -d
```

Without it the calendar starts at the real present moment. A start a few
minutes before 09:00 on a weekday is the usual choice: the market opens
almost at once.

By hand (without the container) the same two settings are the scheduler's
`--speed` and `--start` flags, or the environment variables
`EDUMATCHER_SCHEDULER_SPEED` and `EDUMATCHER_SCHEDULER_START`; see
[A Complete Set-up by Hand](100-a-complete-setup-by-hand.md#accelerated-time-by-hand).

## Choosing a speed

The trading day is 09:00–16:05: a 25-minute pre-open, a 5-minute opening
auction, 6.5 hours of continuous trading, a 5-minute closing auction.

| `EM_SPEED` | A trading day (09:00–16:05) | Continuous trading | An auction | A week | 30 trading days | Good for |
|---|---|---|---|---|---|---|
| 1 | 7 h 5 min | 6 h 30 min | 5 min | 7 days | 6 weeks | A live market alongside a course |
| 10 | 42.5 min | 39 min | 30 s | 16.8 h | 4.2 days | A whole day inside one lesson |
| 24 | 17.7 min | 16.3 min | 12.5 s | 7 h | 42 h | A day an hour; a week over a working day |
| 60 | 7.1 min | 6.5 min | 5 s | 2.8 h | 17 h | Several days in a lesson; overnight runs |
| 600 | 42.5 s | 39 s | 0.5 s | 17 min | 1.7 h | Soak tests: a month of closes in an afternoon |

(Thirty trading days are six calendar weeks, weekends included.)

## What speeds up, and what does not

Only the **calendar** is faster. Everything that happens *during* trading
runs on the wall clock.

| Faster (calendar time) | Not faster (wall clock) |
|---|---|
| The open, the auctions, the close, nights, weekends, holidays | How often each AI trader decides, how many orders a second the swarm sends |
| How far the true values move in a day: a compressed day moves as much as a real one | How long an order rests before its trader cancels it |
| How many headlines a trading day brings, and how soon a rumour resolves | The market maker's quoting rhythm |
| | Heartbeats, time-outs, every log and file timestamp |

So a compressed day is a **short day, not a fast day**. At `EM_SPEED=24` the
traders send their usual orders a second, but continuous trading lasts 16
minutes, so a day has a twenty-fourth of the orders of a real one. Meanwhile
the values move a whole day's worth in those 16 minutes. The consequences
you can see:

- **Prices lag the value more.** Value traders and the market maker have
  fewer orders to pull the price after a value that moves 24 times faster per
  minute. Measured with the `s300-sim` set-up: the typical gap between price
  and value (the RMS of ln(price / value)) was about 0.3 % at real speed,
  about 0.45 % at `EM_SPEED=24` and about 3.5 % at 600.
- **News comes thick and fast.** Six symbol headlines a trading day is one
  every three minutes of wall time at 24, one every 7 seconds at 600. Rumours
  that resolve after 8–60 trading minutes resolve after 20 s–2.5 min at 24.
- **Auctions get thin.** A 5-minute auction lasts 12.5 s at 24 and half a
  second at 600 — barely time for the auction players to send their orders.
  Opening and closing prices at high speed come mostly from the market
  maker's quotes.
- **Order ages feel longer.** A trader that cancels after 60 s keeps an
  order for a sixteenth of the continuous session at 24, and for longer than
  the whole session at 600.

For teaching, 10 to 60 keeps a market that looks right; above that, use it
to test that the exchange keeps running, not to look at prices.

## Traps

**Every restart starts the calendar again.** The accelerated clock begins at
`EM_START` (or now) whenever the scheduler starts — after `compose down`/`up`,
a reboot, or the container restarting a dead scheduler. With `EM_START` set,
the market goes back to that morning. For a long accelerated run, set
`EM_START` for the first start only, then remove it (from `.env`, or leave
`START=` off `make up-sim`) and run the same `up` command again, so Compose
recreates the container without it; the data stays. A container keeps the
settings it was created with, so until then every restart still goes back
to `EM_START`. Later restarts begin at the real present, which never goes
back.

**Dates are wall-clock dates.** Statistics, clearing and the AI traders' daily
results are filed by the date the wall clock shows, because every message is
time-stamped with real time. At `EM_SPEED=24` a whole compressed week lands
on one real date: `pm-stats-cli daily` shows one row per symbol for that
date, with the week's high and low; the AI swarm's daily summaries
(`ai_swarm/<date>-<worker>.jsonl`, by UTC date) hold one line per trader
per *compressed* day, numbered `day 1`, `day 2`, … in the file of the real
date. If you need
true daily statistics, run at real speed.

**Load is per wall second.** A faster calendar does not make the exchange
work harder: the orders a second are the same. The disk grows by the same
amount per *wall-clock* day at any speed (see
[Running It for Weeks](../part-4-watch-and-teach/150-running-it-for-weeks.md)),
so a compressed month costs the disk of the real days it took to run.

## A lesson plan at speed 10

1. Before class: start with `EM_SPEED=10` and `EM_START` set to a weekday at
   08:55, about five minutes before you want the open.
2. Pre-open and opening auction (3 minutes): watch the indicative prices
   form in book-gui; open the books at the open.
3. Continuous trading (39 minutes): inject a headline at minute 5
   ([News and Rumours](../part-2-how-it-works/040-news-and-rumours.md)), a
   rumour at minute 15, confirm or retract it at minute 20.
4. Closing auction (30 seconds) and close: compare the day's moves with the
   values (`pm-market-sim --status --id OPS01` during trading).
5. After class: `down`, remove `EM_START` and `EM_SPEED` from `.env`, `up -d`
   — back to real hours.

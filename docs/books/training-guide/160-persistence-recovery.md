# Persistence & Recovery

## Objective

Learn what EduMatcher persists, where persistent files live, and how to verify
state across restart scenarios.

 


!!! abstract "Background reading"
    - [Persistence](../operator-guide/part-6-observe-and-recover/010-persistence.md)
    - [Audit Trail](../operator-guide/part-6-observe-and-recover/020-audit-trail.md)

## Prerequisites

- Chapters 01–15 completed, and back on your own configuration (the end of
  chapter 14), with `pm-engine`, `pm-admin` and `TRADER01` running and the
  market open.
- Consistent `EDUMATCHER_DATA_DIR` configured for all processes.

 

## Background

EduMatcher stores persistent runtime data under `EDUMATCHER_DATA_DIR`. Common
files include:

- `gtc_orders.json` — resting `GTC` orders (any age) **and** resting `DAY`
  orders from the current business day, including MM quote legs. Written on
  every checkpoint and at clean shutdown; read back at the next startup.
- `stats.db` — SQLite database written by `pm-stats`.
- `audit.log` — event log if `pm-audit` writes to disk.

!!! note "A restart is not a day boundary"
    Despite its name, `gtc_orders.json` also carries
    resting `TIF=DAY` orders across an **engine restart**, as long as the
    restart happens on the same business day the order was placed. The
    day-vs-restart distinction is the subject of Exercise 3 below — see
    [Persistence — Impact of a Business-Day Change](../operator-guide/part-6-observe-and-recover/010-persistence.md#impact-of-a-business-day-change)
    for the full rule.

 

## Exercise 1: Locate the Data Directory

```bash
echo "$EDUMATCHER_DATA_DIR"
ls -la "$EDUMATCHER_DATA_DIR"
```

If the variable is empty, revisit [00 — Installation & Setup](000-installation.md)
and run `pm-setup`.

:material-checkbox-blank-outline: **Checkpoint:** you can locate the persistent data directory.

 

## Exercise 2: Create a GTC and a DAY Order

Place two orders away from the market, one of each lifetime:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=145.00|TIF=GTC
[TRADER01]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=399.00|TIF=DAY
```

(145.00 is as far from AAPL's 150.00 as chapter 11's `L2` collar of ±5%
allows; 140.00 would be rejected with `COLLAR_BREACH`.) Check both are
resting:

```
[TRADER01]> ORDERS
```

:material-checkbox-blank-outline: **Checkpoint:** both orders are resting and visible.

 

## Exercise 3: Restart the Engine

GTC persistence in EduMatcher is unconditional — there is no config flag to
enable/disable it — but it only works correctly under these conditions:

- **Prefer a clean stop** (`Ctrl+C` / SIGINT) over `kill -9`. The engine
  writes `gtc_orders.json` in its graceful shutdown handler. A hard kill skips
  that write, but the engine *also* checkpoints GTC state periodically while
  running, so a `kill -9` loses only the orders placed since the last
  checkpoint — not all of them.
- **Restart with the same `EDUMATCHER_DATA_DIR`** (and thus the same
  `gtc_orders.json` path) used in Exercise 2 — a different data directory has
  nothing to restore from.
- **Restart with a config that still lists the same symbol** — on restore,
  the engine skips any persisted GTC order whose symbol is no longer in
  `engine_config.yaml`.

With those three conditions met, stop `pm-engine` cleanly and start it again,
this time with `--verbose`, so you can watch both halves:

```bash
pm-engine --verbose
```

The shutdown you just did ended with `Saved N resting order(s) to
/data/gtc_orders.json`; the startup now prints a `Restored GTC order <id>
(<symbol>)` line per order (the wording says GTC for same-day DAY orders
too), then `Restored N resting order(s) from previous session.`. N includes
the market makers' quote legs, so it is larger than your two orders. Because
those quotes came back, the engine also skips its seed quotes
(`Skipping seed quote for AAPL/MM_AAPL_01 (seed_once=true, an active quote
was restored)`).

Restart your consoles, reopen the market and look:

```
[TRADER01]> ORDERS
```

Both orders are resting again. The GTC order would always come back; the DAY
order came back because the restart did not cross a business-day boundary.

:material-checkbox-blank-outline: **Checkpoint:** both the GTC and the DAY order survived a same-day restart.

!!! note "Two separate ways a DAY order disappears"
    Don't confuse these — they are driven by different things:

    - **Session close** (`pm-scheduler` transitioning to `CLOSED`, or you
      forcing it with `SESSION|STATE=CLOSED`): every resting DAY order is
      cancelled *live*, with an `order.expired` event, regardless of restart.
      See [06 — Time-in-Force & Sessions](060-time-in-force-sessions.md).
    - **Engine restart after the business day has rolled over**: a resting
      DAY order from a prior business day is silently discarded during
      restore — logged at `INFO`, but with **no** `order.expired` published.
      There is no live sweep for this; it is only checked once, at the next
      startup. See
      [Persistence — Impact of a Business-Day Change](../operator-guide/part-6-observe-and-recover/010-persistence.md#impact-of-a-business-day-change).

    If you want to see the second case instead of the first, you would need
    to actually cross a calendar date between shutdown and restart — not
    practical to demonstrate live in this exercise, so take it as read from
    the Operator's Guide.

 

The other files in the data directory belong to the processes that write
them, and survive any restart the same way: `stats.db` (chapter 15),
`clearing.db` (chapter 12) and `audit.log` (chapter 13) are only ever
appended to by `pm-stats`, `pm-clearing` and `pm-audit`. Only
`pm-opctl-cli clear` removes them.

 

## Summary

You now understand:

- Which data belongs in `EDUMATCHER_DATA_DIR`.
- Why GTC and DAY orders behave differently across session boundaries, and
  why that is a *different* question from how they behave across an engine
  restart.
- Which other files live in the data directory, and what removes them.

## Reflection

A resting `DAY` order and a live MM quote leg both now survive an engine
restart on the same business day, restored from `gtc_orders.json` exactly
like a `GTC` order would — only a business-day rollover discards them, and
only at the next startup. Why does it make sense to key this purely off the
*business day*, rather than off the number of times the engine process has
restarted? What would go wrong operationally in a classroom setting if a
`DAY` order's survival depended instead on "how many restarts have happened
since it was placed"?

## Further Reading

- [Persistence](../operator-guide/part-6-observe-and-recover/010-persistence.md)
- [Statistics and Reporting](../operator-guide/part-4-run-a-market/060-statistics-and-reporting.md)
- [Processes, Environment and Ports](../reference-manual/part-1-command-line/010-processes-environment-and-ports.md)
- [A Full Trading Day](../participant-guide/part-1-trading-basics/030-the-trading-day-and-auctions.md)

**Next:** [17 — Capstone Scenario](170-capstone-scenario.md)

# Persistence & Recovery

## Objective

Learn what EduMatcher persists, where persistent files live, and how to verify
state across restart scenarios.

 


!!! abstract "Pre-reading in the User Guide"
    - [Persistence](../user-guide/180-persistence.md)
    - [Audit Trail](../user-guide/190-audit.md)

## Prerequisites

- Chapters 01–15 completed.
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
    `gtc_orders.json` is not just a "GTC file" any more: it also carries
    resting `TIF=DAY` orders across an **engine restart**, as long as the
    restart happens on the same business day the order was placed. The
    day-vs-restart distinction is the subject of Exercise 4 below — see
    [Persistence — Impact of a Business-Day Change](../user-guide/180-persistence.md#impact-of-a-business-day-change)
    for the full rule.

 

## Exercise 1: Locate the Data Directory

```bash
echo "$EDUMATCHER_DATA_DIR"
ls -la "$EDUMATCHER_DATA_DIR"
```

If the variable is empty, revisit [00 — Installation & Setup](00-installation.md)
and run `pm-setup`.

:material-checkbox-blank-outline: **Checkpoint:** you can locate the persistent data directory.

 

## Exercise 2: Create a GTC Order

Start the exchange and place a GTC order away from the market:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=140.00|TIF=GTC
```

Check the order is resting:

```
[TRADER01]> ORDERS
```

:material-checkbox-blank-outline: **Checkpoint:** the GTC order is resting and visible.

 

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

With those three conditions met, stop `pm-engine` cleanly, then start it again
with the same config and data dir:

```bash
pm-engine
```

Reconnect `TRADER01` and inspect orders:

```
[TRADER01]> ORDERS
```

The GTC order should be restored — the engine also prints a line at shutdown
confirming how many GTC orders it saved (`[ENGINE] Saved N GTC order(s) to
...`), which you can check as a stable confirmation instead of relying on
`ORDERS` output alone.

Compare explicitly after restart:

- GTC orders restore from persistence (given the conditions above).
- Stats remain in `stats.db` if `pm-stats` was writing before restart.

:material-checkbox-blank-outline: **Checkpoint:** verify whether the GTC order survives restart.

 

## Exercise 4: DAY Order Survives a Same-Day Restart

A resting `DAY` order is no longer tied to the engine process — it is tied to
the business day. Place a DAY order at a non-marketable price:

```
[TRADER01]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=399.00|TIF=DAY
```

Restart `pm-engine` cleanly, on the **same calendar day**, with the same data
directory and config. Reconnect `TRADER01` and check:

```
[TRADER01]> ORDERS
```

The DAY order should still be resting — restored exactly like the GTC order
from Exercise 3, because the restart did not cross a business-day boundary.
This is new behaviour: earlier versions of the engine excluded `TIF=DAY`
orders from `gtc_orders.json` entirely, and any resting DAY order was gone
after any restart, same-day or not.

:material-checkbox-blank-outline: **Checkpoint:** the DAY order is still resting after a same-day restart.

!!! note "Two separate ways a DAY order disappears"
    Don't confuse these — they are driven by different things:

    - **Session close** (`pm-scheduler` transitioning to `CLOSED`, or you
      forcing it with `SESSION|STATE=CLOSED`): every resting DAY order is
      cancelled *live*, with an `order.expired` event, regardless of restart.
      See [06 — Time-in-Force & Sessions](06-time-in-force-sessions.md).
    - **Engine restart after the business day has rolled over**: a resting
      DAY order from a prior business day is silently discarded during
      restore — logged at `INFO`, but with **no** `order.expired` published.
      There is no live sweep for this; it is only checked once, at the next
      startup. See
      [Persistence — Impact of a Business-Day Change](../user-guide/180-persistence.md#impact-of-a-business-day-change).

    If you want to see the second case instead of the first, you would need
    to actually cross a calendar date between shutdown and restart — not
    practical to demonstrate live in this exercise, so take it as read from
    the user guide.

 

## Exercise 5: Persist Statistics

Start `pm-stats`, execute a few trades, and inspect the stats database:

```bash
pm-stats
pm-stats-cli trades --symbol AAPL --limit 5
ls -lh "$EDUMATCHER_DATA_DIR"
```

You should see `stats.db` in the data directory once statistics have been
recorded.

:material-checkbox-blank-outline: **Checkpoint:** `stats.db` exists and contains recent trades.

 

## Exercise 6: Audit to Disk

Start audit logging to a file:

```bash
pm-audit --audit-log-file "$EDUMATCHER_DATA_DIR/audit.log" --terminal
```

Execute a trade, then inspect the log:

```bash
tail -20 "$EDUMATCHER_DATA_DIR/audit.log"
```

:material-checkbox-blank-outline: **Checkpoint:** audit log contains events from your trading session.

 

## Summary

You now understand:

- Which data belongs in `EDUMATCHER_DATA_DIR`.
- Why GTC and DAY orders behave differently across session boundaries, and
  why that is a *different* question from how they behave across an engine
  restart.
- How stats and audit files survive beyond the current terminal session.

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

- [Persistence](../user-guide/180-persistence.md)
- [Statistics and Reporting](../user-guide/140-statistics-and-reporting.md)
- [Processes](../user-guide/170-processes.md)
- [A Full Trading Day](../concepts/05-concepts-trading-day.md)

**Next:** [17 — Capstone Scenario](17-capstone-scenario.md)

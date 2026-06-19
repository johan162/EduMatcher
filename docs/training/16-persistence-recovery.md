# 16 — Persistence & Recovery

## Objective

Learn what EduMatcher persists, where persistent files live, and how to verify
state across restart scenarios.

---

## Prerequisites

- Chapters 01–15 completed.
- Consistent `EDUMATCHER_DATA_DIR` configured for all processes.

---

## Background

EduMatcher stores persistent runtime data under `EDUMATCHER_DATA_DIR`. Common
files include:

- `gtc_orders.json` — Good-Till-Cancelled orders that survive session boundaries.
- `stats.db` — SQLite database written by `pm-stats`.
- `audit.log` — event log if `pm-audit` writes to disk.

---

## Exercise 1: Locate the Data Directory

```bash
echo "$EDUMATCHER_DATA_DIR"
ls -la "$EDUMATCHER_DATA_DIR"
```

If the variable is empty, revisit [00 — Installation & Setup](00-installation.md)
and run `pm-setup`.

:material-checkbox-blank-outline: **Checkpoint:** you can locate the persistent data directory.

---

## Exercise 2: Create a GTC Order

Start the exchange and place a GTC order away from the market:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=140.00|TIF=GTC
```

Check the order is resting:

```
TRADER01> ORDERS
```

:material-checkbox-blank-outline: **Checkpoint:** the GTC order is resting and visible.

---

## Exercise 3: Restart the Engine

Stop `pm-engine` cleanly, then start it again with the same config and data dir:

```bash
pm-engine --config engine_config.yaml
```

Reconnect `TRADER01` and inspect orders:

```
TRADER01> ORDERS
```

The GTC order should be restored if persistence is enabled for your run.

Compare explicitly after restart:

- GTC orders may restore from persistence.
- DAY orders from prior session should not survive CLOSED.
- Stats remain in `stats.db` if `pm-stats` was writing before restart.

:material-checkbox-blank-outline: **Checkpoint:** verify whether the GTC order survives restart.

---

## Exercise 4: Compare DAY and GTC Behaviour

Place one DAY and one GTC order at non-marketable prices:

```
TRADER01> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=400.00|TIF=DAY
TRADER01> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=399.00|TIF=GTC
```

Move the session to CLOSED, then restart and inspect `ORDERS`. DAY orders should
expire at session close; GTC orders are the ones designed to survive.

:material-checkbox-blank-outline: **Checkpoint:** explain the different lifecycle of DAY and GTC orders.

---

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

---

## Exercise 6: Audit to Disk

Start audit logging to a file:

```bash
pm-audit --log-file "$EDUMATCHER_DATA_DIR/audit.log" --terminal
```

Execute a trade, then inspect the log:

```bash
tail -20 "$EDUMATCHER_DATA_DIR/audit.log"
```

:material-checkbox-blank-outline: **Checkpoint:** audit log contains events from your trading session.

---

## Summary

You now understand:

- Which data belongs in `EDUMATCHER_DATA_DIR`.
- Why GTC and DAY orders behave differently across session boundaries.
- How stats and audit files survive beyond the current terminal session.

## Further Reading

- [Persistence](../user-guide/11-persistence.md)
- [Statistics and Reporting](../user-guide/16-statistics-and-reporting.md)
- [Processes](../user-guide/10-processes.md)
- [A Full Trading Day](../concepts/05-concepts-trading-day.md)

**Next:** [17 — Capstone Scenario](17-capstone-scenario.md)

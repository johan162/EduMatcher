# Closing the Day: Settlement (`pm-eod`)

## Objective

Close a trading day the way an exchange operator does, using `pm-eod`:

- settle every trader's result for the day
- produce the statements and the payment instructions
- check the books add up to zero
- recover from the mistakes that happen in practice: a missed day, a broken
  roster file, and trading after the close

!!! abstract "Background reading"
    - [Closing the Day: Settlement, Statements and Housekeeping](../operator-guide/part-4-run-a-market/100-closing-the-day.md)
      — the concepts (equity, settlement, the central pool, zero-sum) and every
      message `pm-eod` can print
    - [Your End-of-Day Statement](../participant-guide/part-5-positions-and-results/020-your-end-of-day-statement.md)
      — the statement as a trader reads it

## Prerequisites

- Chapters 01–19 completed. Chapter 12 (`pm-clearing`) matters most here:
  settlement reads what `pm-clearing` recorded.
- The engine running with `TRADER01`, `TRADER02`, `GW_ADMIN` and the market
  makers from chapter 02 connected, and `pm-clearing` running. If chapter 19
  left `TRADER02` kicked, start a new console for it, and re-send a `QUOTE`
  from `MM_AAPL_01` if its quote was cancelled: Exercise 5 needs liquidity on
  AAPL.
- **No `pm-scheduler` running.** You move the session phases yourself, as in
  earlier chapters. A running `--daily` scheduler would close the day at its
  own time.
- `pm-eod` on your `PATH`. Try `pm-eod --version`; if it is missing in a source
  checkout, run `poetry install` once.

 

## Background

At the end of each trading day, `pm-eod run` does five things:

1. **Checks** that the day has really closed and that the clearing books agree.
2. **Works out** each trader's result for the day: the change in their equity
   (realized + unrealized P&L) since the close of the previous settled day.
3. **Adds** that amount to the trader's running balance in `eod.db`.
4. **Writes** one statement per trader, a summary and a payments file under
   `$EDUMATCHER_DATA_DIR/settlement/<date>/`.
5. **Tidies up:** compresses old logs, takes backups, and archives any audit
   days `pm-audit` missed.

All amounts together always add up to exactly zero, because every trade has a
buyer and a seller.

On a production exchange, `pm-scheduler --on-close "pm-eod run --pending"` runs
this by itself 30 seconds after every close. In this chapter you run every step
by hand, so that you see each one.

!!! note "The trading date"
    `pm-eod` labels each day with its **trading date**: the calendar date in the
    exchange's timezone (`locale.session_timezone`, default `Europe/Stockholm`).
    Set it once in the shell you use for this chapter:

    ```bash
    D=$(TZ=Europe/Stockholm date +%F)   # use your session timezone if you changed it
    echo "$D"
    ```

 

## Exercise 1: Check the starting point

Confirm that `pm-clearing` is healthy and the market is open:

```bash
pm-clearing-cli health
```

```
[GW_ADMIN|ADMIN]> SESSION_STATUS
```

If the session is not `CONTINUOUS`, open it as in chapter 01 (`SESSION|STATE=PRE_OPEN`,
then `SESSION|STATE=CONTINUOUS`).

!!! warning "Why the market must be open before Exercise 2"
    If you left the market `CLOSED` at the end of an earlier chapter *today*,
    today counts as a closed trading day. The next step would then settle
    today before you have traded in this chapter. Open the market first.

:material-checkbox-blank-outline: **Checkpoint:** `pm-clearing-cli health` reports
`health: OK` and the session is `CONTINUOUS`.

 

## Exercise 2: Clear the backlog

The earlier chapters closed trading days while `pm-clearing` was running, so
those days are probably still waiting to be settled. Look:

```bash
pm-eod status
```

The table of runs is empty the first time. If any days are waiting, a line on
the error stream lists them:

```
[output]
No rows found.
pending: 2026-11-04
```

Settle them, oldest first:

```bash
pm-eod run --pending
```

```
[output]
2026-11-04:
  [ok] gate: closed, snapshot present, reconciled
  [ok] settle: settled
  [ok] report: wrote .../settlement/2026-11-04 (no roster: statements are keyed by gateway id)
  [ok] audit: nothing pending
  [ok] logs: no log directory
  [ok] backup: backed up clearing.db, eod.db (…); not present: stats.db
```

Each line is one step: `gate`, `settle` and `report` are the money, and `audit`,
`logs` and `backup` are the housekeeping. Your dates, sizes and
`not present:` list will differ. `nothing pending` instead of the block above
means there was no backlog.

!!! tip "If the backlog run stops on an old day"
    `--pending` stops at the first day that fails and says
    `stopping: later dates wait for <date>`, because days are settled in order.
    Look the `[FAIL]` message up in the operator chapter's
    [Troubleshooting](../operator-guide/part-4-run-a-market/100-closing-the-day.md#troubleshooting)
    table. On a training machine, an old day whose clearing data is damaged
    can be cleared away with `pm-opctl-cli clear --state` (with everything
    stopped). That deletes all working state (clearing history, GTC orders,
    statistics) but keeps `eod.db`, so the balances settled so far survive.
    See [Starting over](110-risk-controls.md#starting-over) for the full reset
    matrix and the `--all` data-loss warning.

:material-checkbox-blank-outline: **Checkpoint:** `pm-eod run --pending` ended
without a `[FAIL]` line, and a second `pm-eod run --pending` prints
`nothing pending`.

 

## Exercise 3: Ask too early

Try to settle today while the market is still open:

```bash
pm-eod run --date "$D" --dry-run
```

```
[output]
2026-11-05:
  [FAIL] gate: 2026-11-05 has not closed yet
```

The **gate** is the first step, and it protects the money. A day is closed only
when its latest session phase is `CLOSED` *and* the market was open earlier that
day. `--dry-run` runs the gate and the calculation and writes nothing, so it is
always safe to try.

:material-checkbox-blank-outline: **Checkpoint:** the gate refuses today, and
`echo $?` right after the command prints `1`.

 

## Exercise 4: Write the roster

`pm-eod` knows traders only by gateway id. The **roster** connects ids to
people. Create `$EDUMATCHER_DATA_DIR/ref_data/roster.yaml`:

```yaml
traders:
  - gateway: TRADER01
    name: Alice
    email: alice@example.org
    opening_balance: 1000.00
  - gateway: TRADER02
    name: Bob
    email: bob@example.org
    opening_balance: 1000.00
```

Leave the market makers out on purpose: you will see what `pm-eod` does with a
gateway that is not in the roster.

:material-checkbox-blank-outline: **Checkpoint:** the file exists, and you can
say what `opening_balance` does: it is the starting point of the trader's
running balance, added whenever a balance is shown.

 

## Exercise 5: Trade a day

Give both traders something to settle. TRADER01 buys and keeps a position;
TRADER02 buys and sells part of it again:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=200
[TRADER02]> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=MARKET|QTY=50
```

Look at their positions and P&L before the close:

```bash
pm-clearing-cli positions --symbol AAPL
pm-clearing-cli pnl --symbol AAPL
```

Predict, before going on: whose day result will be positive and whose
negative? (Market orders pay the spread to the market makers, so a trader who
bought and sold at once is usually a little down.)

:material-checkbox-blank-outline: **Checkpoint:** both traders show filled trades
in `pm-clearing-cli trades --date "$D"`, and you have written down a prediction.

 

## Exercise 6: Close the day and settle it

**1. Close the session** from the operator console:

```
[GW_ADMIN|ADMIN]> SESSION|STATE=CLOSED
```

**2. See the close snapshot.** At the close `pm-clearing` saves every position
at the closing price. This is what is settled:

```bash
pm-clearing-cli snapshots --date "$D" --gateway TRADER01
```

```
[output]
trade_date | gateway_id | symbol | net_qty | mark_price | tick_decimals | realized_pnl | unrealized_pnl
-----------+------------+--------+---------+------------+---------------+--------------+---------------
2026-11-05 | TRADER01   | AAPL   | 200     | 149        | 2             | -106.667     | -213.333
```

**3. Dry run.** Now the gate passes, and you see the amounts before anything
is written:

```bash
pm-eod run --date "$D" --dry-run
```

```
[output]
2026-11-05:
  [ok] gate: closed, snapshot present, reconciled
  [ok] settle: would settle: MM_AAPL_01 +275.00, TRADER01 -320.00, TRADER02 +45.00
```

**4. Check one number by hand.** A trader's amount is the sum over all their
symbols of `realized_pnl + unrealized_pnl` in today's snapshot, minus the same
sum at the close of the previous *settled* day (`pm-eod status` lists the
settled days; with none, it is 0). In the example above, TRADER01 has
−106.667 + (−213.333) = −320.00 today. Repeat this for TRADER01 with your own
numbers, using `pm-clearing-cli snapshots --gateway TRADER01 --date <that day>`
for the earlier day.

**5. Settle:**

```bash
pm-eod run --pending
```

A plain `--pending` is enough: today is now the only closed day that is
waiting.

**6. Check the books:**

```bash
pm-eod balances
pm-eod balances --check
```

`--check` should print `OK - every settled date sums to zero`. Add up today's
amounts from the dry run yourself: they also come to 0.00.

:material-checkbox-blank-outline: **Checkpoint:** your hand calculation matches
TRADER01's amount, the run had no `[FAIL]` line, and `--check` says OK. Was your
prediction from Exercise 5 right?

 

## Exercise 7: Read what the traders receive

```bash
ls "$EDUMATCHER_DATA_DIR/settlement/$D" "$EDUMATCHER_DATA_DIR/settlement/$D/statements"
cat "$EDUMATCHER_DATA_DIR/settlement/$D/statements/TRADER01.md"
cat "$EDUMATCHER_DATA_DIR/settlement/$D/instructions.csv"
cat "$EDUMATCHER_DATA_DIR/settlement/$D/leaderboard.csv"
cat "$EDUMATCHER_DATA_DIR/settlement/$D/summary.md"
```

Answer from the files:

1. What is TRADER01's headline sentence, and does its amount match the dry
   run?
2. Does TRADER01's *Open positions at the close* agree with `POS` in TRADER01's
   console?
3. In `instructions.csv`, which traders `pay` and which `receive`? Whose
   balance includes the 1000.00 opening balance?
4. How does the market maker's statement differ from TRADER01's, and which
   warning names it? (Look at the end of `summary.md`.)

:material-checkbox-blank-outline: **Checkpoint:** you can answer all four from the
files alone.

 

## Exercise 8: Run it again

Settlement must never count a day twice. Run today again:

```bash
pm-eod run --date "$D"
pm-eod status
```

The `settle` line now says `already settled`. The report and housekeeping run
again: the statements are written afresh, and the amounts are the stored ones,
not new ones. `pm-eod status` shows today with status `ok`.

:material-checkbox-blank-outline: **Checkpoint:** `pm-eod balances` shows the same
numbers as after Exercise 6.

 

## Exercise 9: A broken roster

Introduce a typical mistake: change TRADER01's opening balance to
`1000.005` (three decimals) and run today again:

```bash
pm-eod run --date "$D"
```

```
[output]
2026-11-05:
  [ok] gate: closed, snapshot present, reconciled
  [ok] settle: already settled
  [FAIL] report: .../ref_data/roster.yaml: line 2: opening_balance has more than 2 decimals
  ...
```

The error names the line. The settlement is safe in the ledger; only the
statements could not be written. Now look at the day as a monitoring system
would:

```bash
pm-eod status
pm-eod status -q; echo "exit code $?"
```

Today's status is `report-failed`, and `status -q` (the health check) returns
**1**. Fix the file back to `1000.00` and run the day again, **without**
`--only`:

```bash
pm-eod run --date "$D"
pm-eod status -q; echo "exit code $?"
```

!!! note "Why not `--only report`?"
    `pm-eod run --date "$D" --only report` would rewrite the statements too, but
    a run with `--only` is never recorded, so the day would stay
    `report-failed` and the health check red. A full run records `ok`.

:material-checkbox-blank-outline: **Checkpoint:** the health check went from exit
code 1 back to 0, and today's status is `ok` again.

 

## Exercise 10: Trading after the close

Sometimes trading resumes on a date that is already settled, for example when
a class runs over. Reopen the market and trade. Buy rather than sell here: Exercise 5 ended with a
sell at the market makers' bid, so selling again at that same price would not
move the closing price and the new amounts would equal the old ones. A buy
trades at the offer, which moves it:

```
[GW_ADMIN|ADMIN]> SESSION|STATE=PRE_OPEN
[GW_ADMIN|ADMIN]> SESSION|STATE=CONTINUOUS
[MM_AAPL_01]> QUOTE|SYM=AAPL|BID=149.95|ASK=150.05|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=AAPL-LATE-001
[TRADER02]> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=50
[GW_ADMIN|ADMIN]> SESSION|STATE=CLOSED
```

Now ask `pm-eod` to catch up:

```bash
pm-eod run --pending
```

It says `nothing pending`. There is **one settlement per trading date**, and
today's is already done. The afternoon's trading is in the new close snapshot,
but not in the ledger. See the difference:

```bash
pm-eod run --date "$D" --dry-run
```

The dry run computes today again from the new snapshot and shows different
amounts. To replace today's settlement with them, use `--redo`:

```bash
pm-eod run --date "$D" --redo
pm-eod balances
pm-eod balances --check
```

```
[output]
2026-11-05:
  [ok] gate: closed, snapshot present, reconciled
  [ok] settle: redone, dropped 2026-11-05
  ...
```

!!! danger "`--redo` drops every later day too"
    Balances are a running total, so `--redo` deletes the chosen date's
    settlement **and every later date's** and recomputes the chosen one. The
    later dates are settled again by the next `pm-eod run --pending`. On a real
    exchange, always do a `--dry-run` first.

:material-checkbox-blank-outline: **Checkpoint:** after `--redo` the balances
include the afternoon's trade, `--check` still says OK, and you can explain why
`--pending` did not pick the afternoon up by itself.

 

## Summary

You can now:

- Settle a trading day with `pm-eod`, and know what the gate checks before any
  money is written.
- Check a trader's amount by hand from the close snapshots, and check that the
  day sums to zero.
- Read the statement, `instructions.csv`, the leaderboard and the summary.
- Clear a backlog with `--pending`, recover from a broken roster without
  leaving the day `report-failed`, and recompute a day with `--redo`.

## Reflection

1. Settlement pays out *paper* profits every day, not only profits locked in
   by selling. Why is that safer for an exchange than waiting until each
   position is closed? (The operator chapter's
   [Why settle paper profits at all?](../operator-guide/part-4-run-a-market/100-closing-the-day.md#settlement)
   box is a hint.)
2. The engine announces `CLOSED` when it starts. Why must `pm-eod` *not* treat
   that as the day's close? What would a trader's statement say if the
   exchange were started in the morning and `pm-eod` settled the day at once?
3. `pm-eod` refuses to settle a day while an earlier closed day is still
   waiting. What would go wrong with the balances if it allowed it?

## Further Reading

- [Closing the Day](../operator-guide/part-4-run-a-market/100-closing-the-day.md)
  — the scheduler hook, running without a scheduler, backups and restore,
  troubleshooting
- [Your End-of-Day Statement](../participant-guide/part-5-positions-and-results/020-your-end-of-day-statement.md)
- [`pm-eod` reference](../reference-manual/part-1-command-line/010-processes-environment-and-ports.md#pm-eod-end-of-day-settlement)
- [Positions and P&L](../participant-guide/part-5-positions-and-results/010-positions-and-pnl.md)

**Next:** [21 — Drop-Copy Replay & Recovery Patterns](200-drop-copy-replay-recovery.md)

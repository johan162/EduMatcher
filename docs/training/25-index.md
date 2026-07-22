# Market Index (`pm-index`)

## Objective

Configure and operate the `pm-index` calculation process, observe a
cap-weighted index updating in real time, apply corporate actions without
disrupting the index level using `pm-index-admin-cli`, and analyse historical
data with `pm-index-cli` and `pm-stats-cli`.

You will practice:

- generating an index config with `pm-config-gen`
- starting `pm-index` and verifying initialisation
- querying the live index level through the `INDEX` gateway command
- watching the index move as trades execute
- applying a stock split and a cash dividend corporate action with `pm-index-admin-cli`
- adding and removing index constituents without restarting, with `pm-index-admin-cli`
- querying structural/audit history with `pm-index-cli`
- querying level and EOD time-series history with `pm-stats-cli`
- exporting history to CSV and JSON for offline analysis

 

## Prerequisites

- Chapters 01–03 completed (engine running, at least one gateway, a few trades).
- Every constituent symbol must have `outstanding_shares` set in `symbols:`.
- To follow Exercise 9 (level/EOD queries via `pm-stats-cli`), `pm-stats` must
  also be running (see [Chapter 15](15-statistics-reporting.md)) — it needs to
  be up *before* the trades happen so it can capture the `index.update` ticks
  live.

Recommended startup order for this chapter:

1. Generate `engine_config.yaml` (Exercise 1).
2. Start `pm-engine`.
3. Start `pm-index`.
4. Start `pm-stats` (needed later for Exercise 9's level/EOD history).
5. Connect two gateway terminals (one TRADER, one ADMIN).

 

## Background

`pm-index` is a **standalone** process — it never sends commands to the engine.
It subscribes to trade events published by `pm-engine` on port 5556 and
recomputes configured indices in real time.

### Cap-weighted formula

Each index level is:

$$
\text{level} = \frac{\sum_{\text{sym}} \text{last\_price(sym)} \times \text{outstanding\_shares(sym)}}{\text{divisor}}
$$

The divisor is chosen at first launch so the level equals `base_value`. It
changes only when a corporate action alters share structures. This keeps the
index level **continuous** across structural events.

### Key processes and ports

```
pm-engine  PUB :5556  ──► pm-index  PUB :5558  ──► pm-md-gwy  ──► CALF clients
                                    PULL :5559  ◄── ADMIN gateways
```

ADMIN gateways send corporate-action and history-request commands to `pm-index`
on the PULL socket (port 5559).

!!! note "Two different history stores"
    `pm-index` writes a JSONL file per index, but it only records
    **structural/audit events** — `INIT`, `CORP_ACTION`, `ADD_CONSTITUENT`,
    `DELIST`. It does **not** write intraday level ticks or end-of-day OHLC
    records to that file. Those are captured instead by `pm-stats`, which
    subscribes to the live `index.update` broadcast and records every tick
    (plus the EOD-forced publish) into its own SQLite database. This means
    `pm-stats` must be **running** while trades occur for level/EOD history to
    exist later — unlike the JSONL file, which `pm-index-cli` can read at any
    time, even offline.

 

## Exercise 1: Configure an Index

Generate a complete config with one index, three constituents, and outstanding
shares:

```bash
pm-config-gen \
  --symbols AAPL MSFT TSLA \
  --gateways TRADER01 OPS01:ADMIN \
  --outstanding-shares AAPL:15000000000 \
  --outstanding-shares MSFT:7400000000 \
  --outstanding-shares TSLA:3200000000 \
  --sessions-enabled \
  --seed 20260625 \
  --index EDU100:"EduMatcher broad index" \
  --index-constituents EDU100:AAPL,MSFT,TSLA \
  --output engine_config.yaml
```

Open `engine_config.yaml` and locate the `indices:` block. It should look like:

```yaml
indices:
  - id: EDU100
    description: "EduMatcher broad index"
    base_value: 1000.0
    publish_interval_sec: 1.0
    history_file: data/indexes/EDU100_history.jsonl
    state_file: data/indexes/EDU100_state.json
    constituents:
      - AAPL
      - MSFT
      - TSLA
```

!!! note "Outstanding shares"
    Every constituent must have `outstanding_shares` set in `symbols:`.
    The default `pm-config-gen` behaviour adds this from `--outstanding-shares`.
    Without it `pm-index` will refuse to start.

:material-checkbox-blank-outline: **Checkpoint:** `engine_config.yaml` contains a valid `indices:` block with all three symbols.

 

## Exercise 2: Start `pm-index`

In a dedicated terminal, start the index calculation process:

```bash
pm-index --config engine_config.yaml
```

Expected startup output:

```
[INFO] pm-index starting — 1 index configured
[INFO] EDU100: No state file found — initialising from config
[INFO] EDU100: divisor=7007100000.000 level=1000.00 (base_value)  constituents=AAPL,MSFT,TSLA
[INFO] pm-index ready — subscribing to pm-engine on tcp://127.0.0.1:5556
```

The `INIT` record has been written to `data/indexes/EDU100_history.jsonl`.
Verify:

```bash
cat data/indexes/EDU100_history.jsonl
```

```json
{"type": "INIT", "timestamp": ..., "index_id": "EDU100", "base_value": 1000.0, "divisor": 7007100000.0, "constituents": ["AAPL", "MSFT", "TSLA"], "level": 1000.0}
```

:material-checkbox-blank-outline: **Checkpoint:** `pm-index` running, INIT record visible in history file.

 

## Exercise 3: Query the Live Index Level

Connect your TRADER01 gateway and run the `INDEX` command:

```
TRADER01> INDEX
```

Expected response (level will depend on seeded prices):

```
[10:00:01.042] EDU100  1000.00  +0.00  +0.00%  O=-- H=-- L=--  PRE_OPEN
```

Fields shown:

| Field | Description |
|---|---|
| Timestamp | UTC time of the reading |
| Index ID | `EDU100` |
| Level | Current calculated level |
| Change / % | Change from day open (empty before first open) |
| O / H / L | Day open, high, low (empty before continuous trading begins) |
| Session state | Current engine session state |

The `INDEX` command works from any gateway role (TRADER, ADMIN, or read-only).

:material-checkbox-blank-outline: **Checkpoint:** `INDEX` command returns a level for `EDU100`.

 

## Exercise 4: Watch the Index Move

Move the session into `CONTINUOUS` (if the scheduler hasn't already done so)
and execute a few trades:

```
OPS01> SESSION|STATE=CONTINUOUS
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=500
TRADER01> NEW|SYM=MSFT|SIDE=BUY|TYPE=MARKET|QTY=300
TRADER01> NEW|SYM=TSLA|SIDE=SELL|TYPE=MARKET|QTY=200
```

After each fill, query the index again:

```
TRADER01> INDEX
```

Observe the level changing as trades update the constituent prices. The index is
recalculated on every trade but published at most once per second (the
`publish_interval_sec` throttle).

!!! tip
    Run `INDEX` several times in quick succession to see the throttle in action —
    the level updates, but the published timestamp advances at most once per second.

:material-checkbox-blank-outline: **Checkpoint:** index level changed after trades; querying `INDEX` shows the new value.

 

## Exercise 5: Apply a Stock Split

Suppose AAPL announces a 2-for-1 stock split. Without adjustment, the index
would drop by ~50% when AAPL's price halves — which is wrong because no value
was destroyed.

!!! note "No gateway command for corporate actions"
    Unlike `INDEX|HISTORY` (Exercise 11), corporate actions and constituent
    changes have **no** `pm-alf-console` command, no `pm-admin`/`pm-admin-cli`
    subcommand, and no ALF/CALF wire message — there is no `CORP_ACTION|...`
    line you can type at a gateway prompt. Instead, use the dedicated
    [`pm-index-admin-cli`](../user-guide/152-index-admin-cli.md) tool, which
    talks directly to `pm-index`'s PULL socket (port 5559). See
    [Market Index → Applying corporate actions](../user-guide/150-index.md#applying-corporate-actions).

Apply the split:

```bash
pm-index-admin-cli --id OPS01 split \
  --index EDU100 --symbol AAPL \
  --ratio-numerator 2 --ratio-denominator 1
```

You'll be shown a confirmation prompt before the command is sent (add `-y` to
skip it, or `--dry-run` to preview the payload without sending). The command
blocks for the `index.corp_action_ack.OPS01` response and prints the result.
`pm-index` applies the action in-process, publishes an updated index value
live, and writes a `CORP_ACTION` record to the structural/audit history file.

Query the index immediately after, from any gateway terminal:

```
TRADER01> INDEX
```

The level should be **unchanged** (or differ by only rounding). Now check that
the divisor was adjusted in the history file:

```bash
grep CORP_ACTION data/indexes/EDU100_history.jsonl | python3 -m json.tool
```

You should see `old_divisor` and `new_divisor` in the record, and the two
values should be **approximately equal** (differing only by integer-rounding
of the new share count). This is expected: a split doubles AAPL's outstanding
shares *and* halves AAPL's price, so AAPL's contribution to the aggregate cap
(`shares × price`) is unchanged — no divisor adjustment is needed to keep the
index level continuous. Contrast this with `ADD`/`DELIST` (Exercise 7), where
the aggregate cap genuinely changes and the divisor must move to compensate.

!!! important "Apply during PRE_OPEN"
    Applying a corporate action mid-session means one more trade at the old
    price may be processed before the divisor update. Best practice is to apply
    all corporate actions during `PRE_OPEN`.

:material-checkbox-blank-outline: **Checkpoint:** compare the `level` field of the `CORP_ACTION`
record to the `INDEX` reading you took just before applying the split — the
absolute difference should be at most a few cents (rounding only), never a
~50% jump. `CORP_ACTION` record confirmed written to history.

 

## Exercise 6: Apply a Cash Dividend

Apply a $2.50 cash dividend for MSFT — same `pm-index-admin-cli` mechanism
as Exercise 5, no gateway command:

```
TRADER01> INDEX        (before)
```

```bash
pm-index-admin-cli --id OPS01 dividend \
  --index EDU100 --symbol MSFT --dividend-per-share 2.50
```

```
TRADER01> INDEX        (after)
```

A cash dividend reduces the effective price by the dividend amount. The divisor
is adjusted to compensate so the index level is preserved.

:material-checkbox-blank-outline: **Checkpoint:** index level preserved across dividend adjustment.

??? note "Under the hood: `ExchangeCommandClient`"
    `pm-index-admin-cli` is a thin wrapper over the same
    `ExchangeCommandClient` class `pm-admin-cli` uses internally. If you ever
    need to script a corporate action directly (e.g. from a test harness),
    the equivalent code is:

    ```python
    from edumatcher.commands import ExchangeCommandClient

    client = ExchangeCommandClient("OPS01")
    result = client.index_corp_action(
        "EDU100", "CASH_DIVIDEND", "MSFT",
        dividend_per_share=2.50,
    )
    print("CORP_ACTION result:", result)
    client.close()
    ```

    Note `pm-index`'s PULL socket has no `connect()`/auth handshake, unlike
    the engine socket `pm-admin-cli` talks to.

 

## Exercise 7: Add and Remove a Constituent

Constituent changes also use [`pm-index-admin-cli`](../user-guide/152-index-admin-cli.md)
— no gateway command exists for these either.

### Add AMZN to the index

Adding a constituent adjusts the divisor so the level does not jump at the
moment of addition. You must supply the new shares and a reference price:

```bash
pm-index-admin-cli --id OPS01 add \
  --index EDU100 --symbol AMZN \
  --shares-outstanding 10500000000 --initial-price 195.00
```

Check that AMZN now appears when you run `INDEX`. It may take a few trades before
AMZN's price updates from the seeded reference.

```
TRADER01> INDEX
```

### Remove TSLA from the index

```bash
pm-index-admin-cli --id OPS01 delist --index EDU100 --symbol TSLA
```

Run `INDEX` again and confirm TSLA no longer appears in the constituent listing.

:material-checkbox-blank-outline: **Checkpoint:** AMZN added and TSLA removed without visible discontinuity in the index level.

 

## Exercise 8: Query History with `pm-index-cli` and `pm-stats-cli`

Two tools cover two different slices of index history:

- `pm-index-cli` reads the JSONL structural/audit file directly from
  disk — `pm-index` does **not** need to be running. It only knows about
  `INIT`, `CORP_ACTION`, `ADD_CONSTITUENT`, and `DELIST` records.
- `pm-stats-cli` reads level ticks and end-of-day OHLC rollups from
  `pm-stats`' SQLite database. Those rows only exist if `pm-stats` was
  **running** while the ticks happened — it captures them live from the
  `index.update` broadcast, it does not replay history after the fact.

If you started `pm-stats` back in the Prerequisites step, it has been
recording every `EDU100` tick since. If you skipped that step, go start it
now — `pm-stats-cli` will simply return no rows for anything that happened
before it was running.

### List configured indices

```bash
pm-index-cli --config engine_config.yaml indices
```

### View recent intraday level snapshots

Every recorded tick (throttled to `publish_interval_sec`, same as the live
`INDEX` command) is available via `pm-stats-cli index-snapshots`:

```bash
pm-stats-cli index-snapshots --index-id EDU100 --limit 50
```

Sample table output:

```
ts                  | index_id | level   | aggregate_cap       | divisor      | session_state | day_open | day_high | day_low
--------------------+----------+---------+---------------------+--------------+----------------+----------+----------+---------
2026-06-25T10:00:01 | EDU100   | 1000.00 | 7007100000000.00    | 7007100000.0 | PRE_OPEN       |          |          |
2026-06-25T10:01:23 | EDU100   | 1034.82 | 7251000000000.00    | 7007100000.0 | CONTINUOUS     | 1000.00  | 1034.82  | 1000.00
...
```

You can list which index IDs `pm-stats` has actually recorded with:

```bash
pm-stats-cli index-ids
```

### View EOD records

`pm-index` no longer writes an end-of-day record to its own JSONL file —
that file is structural/audit only now. Instead, `pm-stats` treats the
EOD-forced publish like any other tick and rolls the day's ticks up into
one daily OHLC row. Query it with `pm-stats-cli index-daily`:

```bash
pm-stats-cli index-daily --index-id EDU100
```

```
date       | index_id | open_level | high_level | low_level | close_level | update_count
-----------+----------+------------+------------+-----------+-------------+--------------
2026-06-25 | EDU100   | 1000.00    | 1052.10    | 987.40    | 1041.55     | 312
```

Add `--wide` to also show the opening/closing aggregate market cap:

```bash
pm-stats-cli index-daily --index-id EDU100 --wide
```

### View all structural events

```bash
pm-index-cli --config engine_config.yaml events --index EDU100
```

This shows `INIT`, `CORP_ACTION`, `ADD_CONSTITUENT`, and `DELIST` records.
You should see the split, dividend, add, and delist from earlier exercises.

Filter to only corporate actions:

```bash
pm-index-cli --config engine_config.yaml events --index EDU100 --type CORP_ACTION
```

:material-checkbox-blank-outline: **Checkpoint:** `pm-index-cli` returns structural
events; `pm-stats-cli index-snapshots` and `index-daily` return level and EOD
rows for `EDU100`.

 

## Exercise 9: Export and Analyse Data

### Export EOD data to CSV

```bash
pm-stats-cli index-daily --index-id EDU100 --format csv > edu100_eod.csv
cat edu100_eod.csv
```

### Export intraday data to JSON

```bash
pm-stats-cli index-snapshots --index-id EDU100 --format json \
  | python3 -c "
import json, sys
rows = json.load(sys.stdin)
print(f'{len(rows)} snapshots')
if rows:
    print(f'First: {rows[0][\"ts\"]}  level={rows[0][\"level\"]}')
    print(f'Last:  {rows[-1][\"ts\"]}  level={rows[-1][\"level\"]}')
"
```

### Date-range query

For a single trading day, `--date` is the simplest filter:

```bash
pm-stats-cli index-snapshots --index-id EDU100 --date 2026-06-25 --limit 500
```

For an arbitrary time window, use `--from`/`--to` with full ISO-8601
timestamps instead:

```bash
pm-stats-cli index-snapshots --index-id EDU100 \
  --from 2026-06-25T09:30:00+00:00 \
  --to 2026-06-25T16:00:00+00:00 \
  --limit 500
```

:material-checkbox-blank-outline: **Checkpoint:** CSV and JSON exports contain the expected data.

 

## Exercise 10: Two Indices

Configure a second, narrower index alongside `EDU100`:

```bash
pm-config-gen \
  --symbols AAPL MSFT TSLA \
  --gateways TRADER01 OPS01:ADMIN \
  --outstanding-shares AAPL:15000000000 \
  --outstanding-shares MSFT:7400000000 \
  --outstanding-shares TSLA:3200000000 \
  --sessions-enabled \
  --seed 20260625 \
  --index EDU100:"EduMatcher broad index" \
  --index-constituents EDU100:AAPL,MSFT,TSLA \
  --index TECH2:"Technology pair" \
  --index-constituents TECH2:AAPL,MSFT \
  --index-base-value TECH2:500.0 \
  --index-interval TECH2:2.0 \
  --output engine_config.yaml
```

Restart `pm-index` with `--reset` to clear state and re-initialise:

```bash
pm-index --config engine_config.yaml --reset
```

!!! warning "`--reset` discards divisors"
    `--reset` removes all state files. The divisors for both indices are
    recomputed from scratch using current reference prices. Use only when
    you intentionally want a clean slate.

Run `INDEX` in the TRADER terminal to see both indices:

```
TRADER01> INDEX
```

```
[10:00:01.100] EDU100   1000.00  +0.00  +0.00%  PRE_OPEN
[10:00:01.100] TECH2     500.00  +0.00  +0.00%  PRE_OPEN
```

Use `pm-index-cli` to list both configured indices, and `pm-stats-cli` to
confirm `pm-stats` is capturing ticks for both:

```bash
pm-index-cli --config engine_config.yaml indices
pm-stats-cli index-ids
pm-stats-cli index-daily
```

`pm-index-cli indices` always shows every index in the config. `pm-stats-cli
index-daily` with no `--index-id` filter shows the daily rollup for every
index `pm-stats` has recorded — useful here to confirm both `EDU100` and
`TECH2` are being tracked. `pm-stats-cli index-snapshots`, by contrast,
requires an explicit `--index-id` (it returns raw ticks, not a summary, so a
single-index scope keeps the output meaningful).

:material-checkbox-blank-outline: **Checkpoint:** both `EDU100` and `TECH2` reported by `INDEX` command, `pm-index-cli indices`, and `pm-stats-cli index-daily`.

 

## Exercise 11: History Query via the Gateway

`pm-index` also accepts history requests directly through the ADMIN gateway.
These go over the PULL socket (port 5559) and return records inline:

```
OPS01> INDEX|HISTORY
```

Returns the last 30 days of **structural/audit records** — `INIT`,
`CORP_ACTION`, `ADD_CONSTITUENT`, `DELIST` — for whichever index you last
saw an `INDEX` update for (or pass `INDEX=<id>` explicitly, e.g.
`INDEX|HISTORY|INDEX=EDU100`).

```
OPS01> INDEX|HISTORY|FROM=2026-06-25|TO=2026-06-25
```

Returns structural/audit records within the specified date range, newest
last.

!!! warning "No level or EOD ticks here"
    `INDEX|HISTORY` never returns intraday level ticks or end-of-day OHLC
    rows — only the same four structural/audit record types you saw in
    Exercise 8's `pm-index-cli events` output. For level and EOD history,
    use `pm-stats-cli index-snapshots` / `pm-stats-cli index-daily` instead;
    the gateway command has no equivalent for that data.

!!! tip "Gateway vs `pm-index-cli` vs `pm-stats-cli`"
    The gateway `INDEX|HISTORY` command is convenient for a quick structural
    lookup in the operator terminal without leaving your session. For richer
    filtering, multi-index queries, CSV/JSON export, or scripting workflows,
    use `pm-index-cli` instead — it reads the structural/audit JSONL file
    directly without going through the network. For level and EOD
    time-series data, neither of those tools applies — use `pm-stats-cli`.

:material-checkbox-blank-outline: **Checkpoint:** `INDEX|HISTORY` returns structural/audit records only; date-range filter works.

 

## Summary

| Concept | Command / file |
|---|---|
| Start index process | `pm-index --config engine_config.yaml` |
| Re-initialise from scratch | `pm-index --reset` |
| Live level query | `INDEX` (any gateway) |
| Structural/audit history query (gateway) | `INDEX\|HISTORY`, `INDEX\|HISTORY\|FROM=…\|TO=…` — INIT/CORP_ACTION/ADD_CONSTITUENT/DELIST only |
| Stock split (no gateway command — use `pm-index-admin-cli`) | `pm-index-admin-cli --id ID split --index IDX --symbol SYM --ratio-numerator … --ratio-denominator …` |
| Cash dividend | `pm-index-admin-cli --id ID dividend --index IDX --symbol SYM --dividend-per-share …` |
| Shares issuance / buy-back | `pm-index-admin-cli --id ID shares --index IDX --symbol SYM --new-shares …` (or `--delta …`) |
| Add constituent | `pm-index-admin-cli --id ID add --index IDX --symbol SYM --shares-outstanding … --initial-price …` |
| Remove constituent | `pm-index-admin-cli --id ID delist --index IDX --symbol SYM` |
| List configured indices | `pm-index-cli --config … indices` |
| Structural/audit events | `pm-index-cli --config … events [--type TYPE]` |
| Intraday level snapshots | `pm-stats-cli index-snapshots --index-id ID` |
| Daily OHLC (EOD) rollup | `pm-stats-cli index-daily [--index-id ID]` |
| List indices seen by pm-stats | `pm-stats-cli index-ids` |
| CSV export (structural events) | `pm-index-cli --config … events --format csv > out.csv` |
| CSV export (daily OHLC) | `pm-stats-cli index-daily --format csv > out.csv` |

 

## Reflection

Why does a stock split leave the index divisor roughly unchanged while a
cash dividend or shares issuance actually changes it? What would happen to
the index's continuity (its "don't jump on non-economic events" property) if
the divisor were recalculated the same way for all four corporate action
types?

## See Also

- [Market Index — User Guide](../user-guide/150-index.md) — full reference for config fields, formulas, and history record types
- [Index Admin CLI](../user-guide/152-index-admin-cli.md) — full `pm-index-admin-cli` subcommand reference, `--dry-run`, and confirmation-prompt behaviour
- [pm-index-cli reference](../user-guide/160-commands.md) — `events`/`indices` subcommands, column descriptions, and output-format options
- [Statistics and Reporting](../user-guide/140-statistics-and-reporting.md) — `pm-stats-cli index-daily` / `index-snapshots` / `index-ids` reference
- [Chapter 15 — Statistics & Reporting](15-statistics-reporting.md) — starting `pm-stats` and querying its SQLite database
- [Engine Configuration](../user-guide/010-configuration.md#configuring-pm-index) — `indices:` YAML field reference
- [Process Reference — pm-index](../user-guide/170-processes.md#pm-index-index-calculation-process) — socket layout and message types

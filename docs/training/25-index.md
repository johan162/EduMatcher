# Market Index (`pm-index`)

## Objective

Configure and operate the `pm-index` calculation process, observe a
cap-weighted index updating in real time, apply corporate actions without
disrupting the index level, and analyse historical data offline with
`pm-index-cli`.

You will practice:

- generating an index config with `pm-config-gen`
- starting `pm-index` and verifying initialisation
- querying the live index level through the `INDEX` gateway command
- watching the index move as trades execute
- applying a stock split and a cash dividend corporate action
- adding and removing index constituents without restarting
- querying level, EOD, and event history with `pm-index-cli`
- exporting history to CSV and JSON for offline analysis

 

## Prerequisites

- Chapters 01–03 completed (engine running, at least one gateway, a few trades).
- Every constituent symbol must have `outstanding_shares` set in `symbols:`.

Recommended startup order for this chapter:

1. Generate `engine_config.yaml` (Exercise 1).
2. Start `pm-engine`.
3. Start `pm-index`.
4. Connect two gateway terminals (one TRADER, one ADMIN).

 

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

Apply the split from your ADMIN gateway:

```
OPS01> CORP_ACTION|INDEX=EDU100|SYM=AAPL|ACTION=SPLIT|NUM=2|DEN=1
```

Expected response:

```
[OK] CORP_ACTION applied: AAPL SPLIT 2:1 — divisor adjusted, index level preserved
```

Query the index immediately after:

```
OPS01> INDEX
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

Apply a $2.50 cash dividend for MSFT:

```
OPS01> CORP_ACTION|INDEX=EDU100|SYM=MSFT|ACTION=CASH_DIVIDEND|DIV=2.50
```

A cash dividend reduces the effective price by the dividend amount. The divisor
is adjusted to compensate so the index level is preserved.

Verify the level before and after:

```
OPS01> INDEX        (before)
OPS01> CORP_ACTION|INDEX=EDU100|SYM=MSFT|ACTION=CASH_DIVIDEND|DIV=2.50
OPS01> INDEX        (after)
```

:material-checkbox-blank-outline: **Checkpoint:** index level preserved across dividend adjustment.

 

## Exercise 7: Add and Remove a Constituent

### Add AMZN to the index

Adding a constituent adjusts the divisor so the level does not jump at the
moment of addition. You must supply the new shares and a reference price:

```
OPS01> CORP_ACTION|INDEX=EDU100|SYM=AMZN|ACTION=ADD|SHARES=10500000000|PRICE=195.00
```

Check that AMZN now appears when you run `INDEX`. It may take a few trades before
AMZN's price updates from the seeded reference.

```
OPS01> INDEX
```

### Remove TSLA from the index

```
OPS01> CORP_ACTION|INDEX=EDU100|SYM=TSLA|ACTION=DELIST
```

Expected response:

```
[OK] CORP_ACTION applied: TSLA DELIST — divisor adjusted, index level preserved
```

Run `INDEX` again and confirm TSLA no longer appears in the constituent listing.

:material-checkbox-blank-outline: **Checkpoint:** AMZN added and TSLA removed without visible discontinuity in the index level.

 

## Exercise 8: Query History with `pm-index-cli`

`pm-index-cli` reads history files directly from disk — `pm-index` does **not**
need to be running.

### List configured indices

```bash
pm-index-cli --config engine_config.yaml indices
```

### View recent intraday snapshots

```bash
pm-index-cli --config engine_config.yaml level --index EDU100 --days 1
```

Sample table output:

```
ts                  | index_id | level   | session_state | aggregate_cap       | divisor
--------------------+----------+---------+---------------+---------------------+--------------
2026-06-25T10:00:01 | EDU100   | 1000.00 | PRE_OPEN      | 7007100000000.00    | 7007100000.0
2026-06-25T10:01:23 | EDU100   | 1034.82 | CONTINUOUS    | 7251000000000.00    | 7007100000.0
...
```

### View EOD records

At the end of the session `pm-index` writes one EOD record. Query all EOD
records (table format):

```bash
pm-index-cli --config engine_config.yaml eod
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

:material-checkbox-blank-outline: **Checkpoint:** `pm-index-cli` returns level, EOD, and event records.

 

## Exercise 9: Export and Analyse Data

### Export EOD data to CSV

```bash
pm-index-cli --config engine_config.yaml eod --format csv > edu100_eod.csv
cat edu100_eod.csv
```

### Export intraday data to JSON

```bash
pm-index-cli --config engine_config.yaml level --index EDU100 --format json \
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

```bash
pm-index-cli --config engine_config.yaml level \
  --index EDU100 \
  --from 2026-06-25 \
  --to 2026-06-25 \
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

Use `pm-index-cli` to list both:

```bash
pm-index-cli --config engine_config.yaml indices
pm-index-cli --config engine_config.yaml level --days 1
```

With no `--index` filter, all configured indices are queried.

:material-checkbox-blank-outline: **Checkpoint:** both `EDU100` and `TECH2` reported by `INDEX` command and `pm-index-cli`.

 

## Exercise 11: History Query via the Gateway

`pm-index` also accepts history requests directly through the ADMIN gateway.
These go over the PULL socket (port 5559) and return records inline:

```
OPS01> INDEX|HISTORY
```

Returns the last 30 days of LEVEL and EOD records.

```
OPS01> INDEX|HISTORY|FROM=2026-06-25|TO=2026-06-25
```

Returns records within the specified date range, newest last.

!!! tip "Gateway vs `pm-index-cli`"
    The gateway `INDEX|HISTORY` command is convenient for quick lookups in the
    operator terminal. For richer filtering, multi-index queries, CSV/JSON export,
    or scripting workflows, use `pm-index-cli` instead — it reads files directly
    without going through the network.

:material-checkbox-blank-outline: **Checkpoint:** `INDEX|HISTORY` returns records; date-range filter works.

 

## Summary

| Concept | Command / file |
|---|---|
| Start index process | `pm-index --config engine_config.yaml` |
| Re-initialise from scratch | `pm-index --reset` |
| Live level query | `INDEX` (any gateway) |
| History query (gateway) | `INDEX\|HISTORY`, `INDEX\|HISTORY\|FROM=…\|TO=…` |
| Stock split | `CORP_ACTION\|INDEX=…\|SYM=…\|ACTION=SPLIT\|NUM=…\|DEN=…` |
| Cash dividend | `CORP_ACTION\|INDEX=…\|SYM=…\|ACTION=CASH_DIVIDEND\|DIV=…` |
| Shares issuance | `CORP_ACTION\|INDEX=…\|SYM=…\|ACTION=SHARES_ISSUANCE\|SHARES=…` |
| Add constituent | `CORP_ACTION\|INDEX=…\|SYM=…\|ACTION=ADD\|SHARES=…\|PRICE=…` |
| Remove constituent | `CORP_ACTION\|INDEX=…\|SYM=…\|ACTION=DELIST` |
| List configured indices | `pm-index-cli --config … indices` |
| Intraday snapshots | `pm-index-cli --config … level --index ID --days N` |
| EOD records | `pm-index-cli --config … eod` |
| Structural events | `pm-index-cli --config … events [--type TYPE]` |
| CSV export | `pm-index-cli --config … eod --format csv > out.csv` |

 

## Reflection

Why does a stock split leave the index divisor roughly unchanged while a
cash dividend or shares issuance actually changes it? What would happen to
the index's continuity (its "don't jump on non-economic events" property) if
the divisor were recalculated the same way for all four corporate action
types?

## See Also

- [Market Index — User Guide](../user-guide/22-index.md) — full reference for config fields, formulas, and history record types
- [pm-index-cli reference](../user-guide/02-commands.md) — all subcommands, column descriptions, and output-format options
- [Engine Configuration](../user-guide/01-configuration.md#configuring-pm-index) — `indices:` YAML field reference
- [Process Reference — pm-index](../user-guide/10-processes.md#pm-index-index-calculation-process) — socket layout and message types

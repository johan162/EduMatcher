# Configuring & Starting Up

## Objective

By the end of this chapter you will have a working exchange with at least one
gateway and three tradeable symbols, ready to accept orders.
In addition you have become familiar with the two tools:

- **`pm-config-gen`** used to automatically generate configuration file based on options and flags. 
- **`pm-cverifier`**  used to verify an existing (possibly hand-crafterd) configuration file for errors or missing settings

 

## Prerequisites

- EduMatcher installed and `pm-setup` completed (see [00 — Installation & Setup](00-installation.md)).

## Background

EduMatcher requires two essential processes:

1. **pm-engine** — the matching engine (reads `engine_config.yaml`).
2. **pm-scheduler** — drives session phase transitions.

A **gateway** (`pm-alf-console`) connects traders to the engine.

 

## Exercise 1: Create a Minimal Configuration

Create a file called `engine_config.yaml` in your working directory:

```yaml
symbols:
  AAPL:
    description: "Apple Inc."
    tick_size: 0.01
    last_price: 150.00
  MSFT:
    description: "Microsoft Corp."
    tick_size: 0.01
    last_price: 420.00
  TSLA:
    description: "Tesla Inc."
    tick_size: 0.05
    last_price: 250.00

gateways:
  alf:
    - id: TRADER01
      description: "Alice — first trader"
      role: TRADER
    - id: TRADER02
      description: "Bob — second trader"
      role: TRADER
    - id: GW_ADMIN
      description: "Exchange operator"
      role: ADMIN
```

:material-checkbox-blank-outline: **Checkpoint:** file saved, YAML is valid (no tabs!).

 

## Exercise 2: Generate a Config with pm-config-gen

Instead of writing YAML by hand, you can use the `pm-config-gen` helper to
scaffold a configuration. Try generating an equivalent config:

```bash
pm-config-gen \
  --symbols AAPL MSFT TSLA \
  --symbol-opts AAPL:tick_decimals=2 \
  --symbol-opts MSFT:tick_decimals=2 \
  --symbol-opts TSLA:tick_decimals=2 \
  --gateways TRADER01:TRADER TRADER02:TRADER GW_ADMIN:ADMIN \
  --static-band 0.10 \
  --dynamic-band 0.05 \
  --sessions-enabled \
  --output engine_config.yaml --force
```

This produces a ready-to-use `engine_config.yaml` with:

- Three symbols (AAPL, MSFT, TSLA) with 2-decimal tick precision.
- Two trader gateways and one admin gateway.
- Static and dynamic price collars pre-configured.
- Session schedule enabled (PRE_OPEN → CONTINUOUS → CLOSED).

Inspect the generated file:

```bash
cat engine_config.yaml
```

!!! tip "Dry-run mode"
    Add `--dry-run` to preview the output without writing a file:
    ```bash
    pm-config-gen --symbols AAPL MSFT TSLA --gateways TRADER01 --dry-run
    ```

!!! tip "Adding market-maker gateways"
    You can include MM gateways in the same command:
    ```bash
    pm-config-gen \
      --symbols AAPL MSFT TSLA \
      --gateways TRADER01 TRADER02 GW_ADMIN:ADMIN MM_AAPL_01:MARKET_MAKER \
      --enforce-mm-obligations \
      --output engine_config.yaml --force
    ```

:material-checkbox-blank-outline: **Checkpoint:** generated config matches the manual one; symbols and gateways present.

 

## Exercise 3: Validate the Config with pm-cverifier

Before starting runtime processes, verify the file:

```bash
pm-cverifier engine_config.yaml
```

Check the verdict and exit code:

```bash
echo $?
```

Expected for this chapter config:

- Verdict is `OK` or `WARN` (depending on optional sections you did or did not add).
- Exit code is `0` when there are no warnings/errors, `1` when warnings exist, and `2` when hard errors exist.

!!! tip "CI-style validation"
    Treat warnings as failures and emit machine-readable output:
    ```bash
    pm-cverifier --strict --format json engine_config.yaml
    ```

!!! tip "Focus only on actionable items"
    Hide info-level advisories while iterating:
    ```bash
    pm-cverifier --level warn engine_config.yaml
    ```

:material-checkbox-blank-outline: **Checkpoint:** you can run `pm-cverifier`, read the verdict, and interpret its exit code.

## Exercise 4: Practice Fixing Verifier Findings

Create a temporary broken config and use `pm-cverifier` to diagnose it:

```bash
cp engine_config.yaml engine_config.bad.yaml
```

Edit `engine_config.bad.yaml` and intentionally introduce two issues:

1. Remove the `GW_ADMIN` gateway entry.
2. Set one symbol's `tick_decimals` to an invalid value like `12`.

Run verifier:

```bash
pm-cverifier engine_config.bad.yaml
```

You should see at least:

- `M013` warning (no ADMIN gateway).
- `S010` error (invalid `tick_decimals`).

Now fix the file and rerun until verdict is `OK` or your expected warning-only state.

:material-checkbox-blank-outline: **Checkpoint:** you can reproduce a verifier finding, map it to a check code, and clear it by fixing the config.

## Exercise 5: Start the Engine

Open a terminal and run:

```bash
pm-engine --config engine_config.yaml
```

Expected output includes (exact wording/log format may vary by version — this
is illustrative, not a literal match target):

```
[INFO] Loaded 3 symbols: AAPL, MSFT, TSLA
[INFO] Loaded 3 gateways
[INFO] Engine listening on :5555 (PULL), publishing on :5556 (PUB)
```

The stable way to confirm the engine actually loaded your config, independent
of log wording, is to query it from a gateway once connected (Exercise 7) with
`SYMBOLS` — if it lists `AAPL`, `MSFT`, and `TSLA`, the engine started correctly
regardless of what the startup banner said.

:material-checkbox-blank-outline: **Checkpoint:** engine is running without errors.

 

## Exercise 6: Start the Scheduler

In a **second terminal**:

```bash
pm-scheduler
```

Expected output (illustrative):

```
[INFO] Session state: PRE_OPEN
```

The scheduler will transition through PRE_OPEN → OPENING_AUCTION → CONTINUOUS
automatically (or you can trigger immediate continuous with `--immediate`).

:material-checkbox-blank-outline: **Checkpoint:** scheduler reports session state changes.

 

## Exercise 7: Connect a Gateway

In a **third terminal**:

```bash
pm-alf-console --id TRADER01
```

You should see:

```
[INFO] Connected as TRADER01
TRADER01>
```

Try typing `ORDERS` — it should report no resting orders for this gateway.

:material-checkbox-blank-outline: **Checkpoint:** gateway prompt is interactive and connected.

 

## Exercise 8: Verify the Setup

From the gateway prompt, confirm the three symbols are available by attempting
a tiny limit order:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=1|PRICE=0.01|TIF=DAY
```

You should see an acknowledgement (the order rests since no matching ask exists).

Repeat for `MSFT` and `TSLA` to confirm all three books are active.

:material-checkbox-blank-outline: **Checkpoint:** all three symbols accept orders.

 

## Exercise 9: Connect the Admin Gateway

In a **fourth terminal**:

```bash
pm-alf-console --id GW_ADMIN
```

Try an admin command:

```
GW_ADMIN> BOOK|SYM=AAPL
```

You should see a book snapshot (possibly with the 1-lot bid from Exercise 8).

:material-checkbox-blank-outline: **Checkpoint:** admin gateway works; BOOK command shows data.

 

## Exercise 10: Inspect Enriched SYMBOLS Metadata

From any connected gateway:

```
TRADER01> SYMBOLS
```

In addition to symbol IDs, inspect metadata fields exposed by the gateway view,
including symbol description and matching constraints such as tick size and MM
obligation settings when configured.

:material-checkbox-blank-outline: **Checkpoint:** you can identify at least `description` and `tick_size` for each symbol from `SYMBOLS` output.

 

## Summary

You now have:

- A configuration file defining 3 symbols and 3 gateways.
- A repeatable verifier workflow (`pm-cverifier`) to catch config problems before startup.
- A running engine, scheduler, and at least one trader gateway.
- Confirmation that all symbols accept orders.

## Reflection

Why does the engine, scheduler, and each gateway all run as **separate
processes** connected over ZMQ sockets, instead of one monolithic program?
What would you lose (or gain) operationally if the scheduler crashed while
the engine kept running?

## Further Reading

- [Configuration](../user-guide/010-configuration.md)
- [Config Verifier (`pm-cverifier`)](../user-guide/020-config-verifier.md)
- [Running the Engine](../user-guide/040-running-the-engine.md)
- [Gateway Commands](../user-guide/050-gateway.md)
- [Message Types (system.symbols)](../user-guide/270-messages.md)

**Next:** [02 — Setting Up Market-Maker Liquidity](02-setting-up-MM-bots.md)

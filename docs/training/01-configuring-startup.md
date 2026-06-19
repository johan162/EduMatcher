# 01 — Configuring & Starting Up

## Objective

By the end of this chapter you will have a working exchange with at least one
gateway and three tradeable symbols, ready to accept orders.

---

## Prerequisites

- EduMatcher installed and `pm-setup` completed (see [00 — Installation & Setup](00-installation.md)).

## Background

EduMatcher requires two essential processes:

1. **pm-engine** — the matching engine (reads `engine_config.yaml`).
2. **pm-scheduler** — drives session phase transitions.

A **gateway** (`pm-gateway`) connects traders to the engine.

---

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

---

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

---

## Exercise 3: Start the Engine

Open a terminal and run:

```bash
pm-engine --config engine_config.yaml
```

Expected output includes:

```
[INFO] Loaded 3 symbols: AAPL, MSFT, TSLA
[INFO] Loaded 3 gateways
[INFO] Engine listening on :5555 (PULL), publishing on :5556 (PUB)
```

:material-checkbox-blank-outline: **Checkpoint:** engine is running without errors.

---

## Exercise 4: Start the Scheduler

In a **second terminal**:

```bash
pm-scheduler
```

Expected output:

```
[INFO] Session state: PRE_OPEN
```

The scheduler will transition through PRE_OPEN → OPENING_AUCTION → CONTINUOUS
automatically (or you can trigger immediate continuous with `--immediate`).

:material-checkbox-blank-outline: **Checkpoint:** scheduler reports session state changes.

---

## Exercise 5: Connect a Gateway

In a **third terminal**:

```bash
pm-gateway --id TRADER01
```

You should see:

```
[INFO] Connected as TRADER01
TRADER01>
```

Try typing `ORDERS` — it should report no resting orders for this gateway.

:material-checkbox-blank-outline: **Checkpoint:** gateway prompt is interactive and connected.

---

## Exercise 6: Verify the Setup

From the gateway prompt, confirm the three symbols are available by attempting
a tiny limit order:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=1|PRICE=0.01|TIF=DAY
```

You should see an acknowledgement (the order rests since no matching ask exists).

Repeat for `MSFT` and `TSLA` to confirm all three books are active.

:material-checkbox-blank-outline: **Checkpoint:** all three symbols accept orders.

---

## Exercise 7: Connect the Admin Gateway

In a **fourth terminal**:

```bash
pm-gateway --id GW_ADMIN
```

Try an admin command:

```
GW_ADMIN> BOOK|SYM=AAPL
```

You should see a book snapshot (possibly with the 1-lot bid from Exercise 5).

:material-checkbox-blank-outline: **Checkpoint:** admin gateway works; BOOK command shows data.

---

## Summary

You now have:

- A configuration file defining 3 symbols and 3 gateways.
- A running engine, scheduler, and at least one trader gateway.
- Confirmation that all symbols accept orders.

## Further Reading

- [Configuration](../user-guide/01-configuration.md)
- [Running the Engine](../user-guide/03-running-the-engine.md)
- [Gateway Commands](../user-guide/08-gateway.md)

**Next:** [02 — Setting Up Market-Maker Liquidity](02-setting-up-MM-bots.md)

# Risk Controls

## Objective

Configure and trigger the exchange's safety mechanisms: price collars, circuit
breakers, symbol halts, and the kill switch. You will use both the interactive
`pm-admin` console and the one-shot `pm-admin-cli` tool.

 


!!! abstract "Background reading"
    - [Risk Controls](../operator-guide/part-4-run-a-market/040-risk-controls.md)
    - [The Admin Console and Exchange Commands](../operator-guide/part-3-run/020-admin-console-and-commands.md)

## Prerequisites

- Chapters 01–10 completed.
- `GW_ADMIN` configured with `role: ADMIN` and connected.

 

## Background

Risk controls prevent erroneous or manipulative orders from distorting the market:

- **Price collars** — reject orders outside static/dynamic price bands.
- **Circuit breakers** — auto-halt a symbol after violent price moves.
- **Symbol halt** — manually halt trading on one instrument.
- **Exchange halt** — halt all trading.
- **Kill switch** — cancel all orders for a specific gateway.

Administrative controls can be sent through an admin gateway session, but the
preferred operator tools are:

- `pm-admin --id GW_ADMIN` — interactive admin console with tab completion.
- `pm-admin-cli --id GW_ADMIN <command>` — one command, one response, useful for
  scripts, demos, and operational runbooks.

Both require a gateway configured with `role: ADMIN`, such as the `GW_ADMIN`
gateway from chapter 01.

 

## Exercise 1: Configure Price Collars

Collars are configured per symbol under `symbols.<SYM>.collar` (a direct
override) or inherited from a named `risk_controls.levels` profile via
`symbols.<SYM>.level`. Add a direct collar override to `engine_config.yaml`:

```yaml
symbols:
  AAPL:
    collar:
      static_band_pct: 0.10    # ±10% from reference price
      dynamic_band_pct: 0.05   # ±5% from last traded price
  MSFT:
    collar:
      static_band_pct: 0.10
      dynamic_band_pct: 0.05
```

Both fields are fractions in `(0, 1)`, not whole percentages — `0.10` means
10%. Those built-in defaults (`static_band_pct: 0.20`, `dynamic_band_pct:
0.02`) fill in a field that is *missing from a `collar:` block that is
present*. Leave the whole `collar:` section out and the symbol gets **no
collar at all** — not a default one. `enforce_collars` (top-level, defaults to
`true`) must also not be set to `false`.

!!! warning "A collar needs a reference price to compare against"
    The engine only registers a collar for a symbol once a reference price
    resolves — from `last_buy_price`/`last_sell_price` in the configuration, or
    from persisted `book_stats.json`. If those are unset, the collar is
    silently never enforced and the rejection below will not fire. Chapter 01's
    configuration seeds them; if you generated yours with `pm-config-gen`, pass
    `--seed-last-prices-from-mm` or set the two fields by hand.

Deploy the change, then restart the engine — editing the YAML alone changes
nothing, because every process reads the compiled artifact:

```bash
pm-config-deploy engine_config.yaml
```

Then restart `pm-engine`.

:material-checkbox-blank-outline: **Checkpoint:** engine loads risk control configuration.

 

## Exercise 2: Trigger a Static Collar Rejection

Place an order far outside the allowed range:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=200.00|TIF=DAY
```

If the reference price is 150.00 and the static collar is ±10%, anything
above 165.00 or below 135.00 is rejected.

Expected: rejection — price outside static collar.

:material-checkbox-blank-outline: **Checkpoint:** out-of-range order rejected with collar error.

 

## Exercise 3: Configure Circuit Breakers

Circuit-breaker trigger percentages and halt durations come from a global
ladder, `circuit_breaker_defaults`, applied to every symbol unless a symbol
defines its own `circuit_breaker.levels` override (see the `TSLA` pattern in
[The Configuration Workflow](../operator-guide/part-2-configure/010-the-configuration-workflow.md#risk-controls-and-collars)).
Add a two-level ladder:

```yaml
circuit_breaker_defaults:
  reference_window_ns: 300000000000   # 5 minutes — window the move is measured over
  levels:
    L1:
      price_shift_pct: 0.05           # halt if price moves ±5% within the window
      halt_duration_ns: 30000000000   # 30 second halt
```

`enforce_circuit_breakers` (top-level, defaults to `true`) must also not be
set to `false`.

Deploy the change, then restart the engine — editing the YAML alone changes
nothing, because every process reads the compiled artifact:

```bash
pm-config-deploy engine_config.yaml
```

Then restart `pm-engine`.

:material-checkbox-blank-outline: **Checkpoint:** circuit breaker config loaded.

 

## Exercise 4: Trigger a Circuit Breaker

A circuit breaker does not compare a trade with the previous one. It compares
it with the **average price of the trades in the last `reference_window_ns`**
(5 minutes here) — on a fresh start, the opening reference price of 150.00.
A gradual climb therefore has to go further than 5% before it trips, while
the 5% dynamic collar from Exercise 1 stops any single jump of more than 5%.
Walk the price up in steps.

First give the two traders the book to themselves: stop any `pm-mm-bot` and
clear AAPL so no market-maker quote trades in between:

```
[GW_ADMIN|ADMIN]> CANCEL_SYM|SYM=AAPL
```

Then, for each price in turn — 154.00, 158.00, 161.00, 164.50 — let TRADER02
offer 100 shares and TRADER01 buy them:

```
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=154.00|TIF=DAY
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=154.00|TIF=DAY
```

| Trade at | Reference (average of earlier trades in the window) | Move | Result |
|---|---|---|---|
| 154.00 | 150.00 (opening reference) | 2.7% | trades |
| 158.00 | (150 + 154) / 2 = 152.00 | 3.9% | trades |
| 161.00 | (150 + 154 + 158) / 3 = 154.00 | 4.5% | trades |
| 164.50 | (150 + 154 + 158 + 161) / 4 = 155.75 | 5.6% | trades, then **halts AAPL** |

The trade at 164.50 still happens; the halt applies from that moment on. The
engine log records it (in `pm-engine --verbose`, or the Log Operator
Console):

```
CIRCUIT BREAKER HALT AAPL: level=L1 trigger=16450, ref=15575 ticks, corridor=[14017, 17132] ticks (+/-10.0%)
```

During the halt, **market-maker quote legs are cancelled**, no matching takes
place, `MARKET`, `FOK` and `IOC` orders are rejected, and `LIMIT` orders are
accepted and rest: a halt is the collection phase of a *reopening auction*,
which uncrosses when the 30-second halt ends.

Verification drill, while the halt lasts:

1. Send a market order — it is rejected with `code=CIRCUIT_BREAKER_ACTIVE`:

    ```
    [TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
    ```

2. Send a limit order — it is accepted and rests, waiting for the reopening:

    ```
    [TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=160.00|TIF=DAY
    ```

:material-checkbox-blank-outline: **Checkpoint:** AAPL halted by the circuit breaker after the fourth step; a market order is rejected and a limit order rests until the halt ends.

 

## Exercise 5: Open the Admin Console

In a new terminal, start the interactive admin console:

```bash
pm-admin --id GW_ADMIN
```

At the prompt, inspect the exchange:

```
[GW_ADMIN|ADMIN]> HELP
[GW_ADMIN|ADMIN]> SYMBOLS
[GW_ADMIN|ADMIN]> SESSION_STATUS
[GW_ADMIN|ADMIN]> GATEWAYS
```

Use `BOOK|SYM=AAPL` to confirm the console can query market state:

```
[GW_ADMIN|ADMIN]> BOOK|SYM=AAPL
```

:material-checkbox-blank-outline: **Checkpoint:** `pm-admin` authenticates as `GW_ADMIN` and can show symbols, session status, gateways, and book state.

 

## Exercise 6: Manual Symbol Halt and Resume

From the `pm-admin` console:

```
[GW_ADMIN|ADMIN]> HALT_SYM|SYM=MSFT
```

Try trading MSFT from TRADER01:

```
[TRADER01]> NEW|SYM=MSFT|SIDE=BUY|TYPE=MARKET|QTY=100
```

Expected: rejection — `code=INSTRUMENT_HALTED`. (A *limit* order would be
accepted and rest for the reopening, as in Exercise 4.)

Resume:

```
[GW_ADMIN|ADMIN]> RESUME_SYM|SYM=MSFT
```

:material-checkbox-blank-outline: **Checkpoint:** halt prevents trading; resume restores it.

 

## Exercise 7: Exchange-Wide Halt with pm-admin-cli

Use the one-shot CLI form when you want an operation to run from a script or
checklist without opening an interactive console:

```bash
pm-admin-cli --id GW_ADMIN halt
```

All symbols stop matching. Confirm status:

```bash
pm-admin-cli --id GW_ADMIN session-status
pm-admin-cli --id GW_ADMIN symbols
```

Then resume:

```bash
pm-admin-cli --id GW_ADMIN resume
```

:material-checkbox-blank-outline: **Checkpoint:** `pm-admin-cli` halts and resumes the exchange without entering a REPL.

 

## Exercise 8: Query and Manage with pm-admin-cli

Try the read-only commands first:

```bash
pm-admin-cli --id GW_ADMIN book --sym AAPL
pm-admin-cli --id GW_ADMIN orders --gw TRADER01
pm-admin-cli --id GW_ADMIN gateways
pm-admin-cli --id GW_ADMIN volume
pm-admin-cli --id GW_ADMIN schedule
```

Now halt and resume one symbol through the CLI:

```bash
pm-admin-cli --id GW_ADMIN halt-sym --sym TSLA
pm-admin-cli --id GW_ADMIN resume-sym --sym TSLA
```

:material-checkbox-blank-outline: **Checkpoint:** you can choose `pm-admin` for interactive operation and `pm-admin-cli` for repeatable one-shot commands.

 

## Exercise 9: Exchange-Wide Halt from the Admin Console

```
[GW_ADMIN|ADMIN]> HALT
```

All symbols stop matching. Then:

```
[GW_ADMIN|ADMIN]> RESUME
```

:material-checkbox-blank-outline: **Checkpoint:** full halt and resume works across all symbols.

 

## Exercise 10: Kill Switch

Cancel all orders for a misbehaving gateway:

```
[GW_ADMIN|ADMIN]> KILL|GW=TRADER02
```

Expected: all of TRADER02's resting orders cancelled.

Or scope to a single symbol:

```
[GW_ADMIN|ADMIN]> KILL|GW=TRADER02|SYM=AAPL
```

The same operation as a one-shot CLI command is:

```bash
pm-admin-cli --id GW_ADMIN kill --gw TRADER02 --sym AAPL
```

:material-checkbox-blank-outline: **Checkpoint:** kill switch cancels targeted orders.

 

## Risk Control Summary

| Control | Scope | Trigger | Effect |
|---------|-------|---------|--------|
| Static collar | Per symbol | Order price vs reference | Order rejected |
| Dynamic collar | Per symbol | Order price vs last trade | Order rejected |
| Circuit breaker | Per symbol | Price move vs. average of recent trades | Symbol halted, then reopened by auction |
| Symbol halt | Per symbol | `pm-admin` / `pm-admin-cli` | Trading paused |
| Exchange halt | All symbols | `pm-admin` / `pm-admin-cli` | All trading paused |
| Kill switch | Per gateway | `pm-admin` / `pm-admin-cli` | All orders cancelled |

 

## Reflection

Why does a circuit breaker halt the whole symbol rather than just rejecting
new orders like the collars do? What failure mode (think: a runaway
algorithmic trader or a bad data feed) is a circuit breaker specifically
designed to stop that per-order collars cannot?

## Further Reading

- [Risk Controls](../operator-guide/part-4-run-a-market/040-risk-controls.md)
- [Controlling the Exchange](../operator-guide/part-3-run/020-admin-console-and-commands.md)
- [Processes, Environment and Ports](../reference-manual/part-1-command-line/010-processes-environment-and-ports.md)
- [Drop Copy](../protocols-and-clients/part-3-session-behaviour/060-drop-copy.md)
- [A Full Trading Day](../participant-guide/part-1-trading-basics/030-the-trading-day-and-auctions.md)

 

**Next:** [12 — P&L & Clearing](120-pnl-clearing.md)

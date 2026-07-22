# Risk Controls

## Objective

Configure and trigger the exchange's safety mechanisms: price collars, circuit
breakers, symbol halts, and the kill switch. You will use both the interactive
`pm-admin` console and the one-shot `pm-admin-cli` tool.

 

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
10%. If omitted, the built-in defaults are `static_band_pct: 0.20`,
`dynamic_band_pct: 0.02`. `enforce_collars` (top-level, defaults to `true`)
must also not be set to `false`.

Restart the engine.

:material-checkbox-blank-outline: **Checkpoint:** engine loads risk control configuration.

 

## Exercise 2: Trigger a Static Collar Rejection

Place an order far outside the allowed range:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=200.00|TIF=DAY
```

If the reference price is 150.00 and the static collar is ±10%, anything
above 165.00 or below 135.00 is rejected.

Expected: rejection — price outside static collar.

:material-checkbox-blank-outline: **Checkpoint:** out-of-range order rejected with collar error.

 

## Exercise 3: Configure Circuit Breakers

Circuit-breaker trigger percentages and halt durations come from a global
ladder, `circuit_breaker_defaults`, applied to every symbol unless a symbol
defines its own `circuit_breaker.levels` override (see the `TSLA` pattern in
[Configuration](../user-guide/010-configuration.md#risk-controls-and-collars)).
Add a two-level ladder:

```yaml
circuit_breaker_defaults:
  reference_window_ns: 300000000000   # 5 minutes — window the move is measured over
  levels:
    L1:
      price_shift_pct: 0.05           # halt if price moves ±5% within the window
      halt_duration_ns: 30000000000   # 30 second halt
      resumption_mode: AUCTION
```

`enforce_circuit_breakers` (top-level, defaults to `true`) must also not be
set to `false`.

Restart the engine.

:material-checkbox-blank-outline: **Checkpoint:** circuit breaker config loaded.

 

## Exercise 4: Trigger a Circuit Breaker

Push AAPL's price 5% within the 5-minute reference window by trading
aggressively (you may need to adjust MM bot gap or trade in volume). When the
threshold is breached, the exact halt announcement wording may vary by
version — the reliable way to confirm the halt fired is to check that new
AAPL orders are rejected (see the verification drill below), not to match a
literal log line. Illustratively:

```
[HALT] AAPL — circuit breaker triggered (~5% move)
```

All resting orders on AAPL are preserved but no new matching occurs.

Verification drill:

1. Run `BOOK|SYM=AAPL` and confirm resting orders remain visible.
2. Submit a fresh AAPL order and confirm rejection while halted.

:material-checkbox-blank-outline: **Checkpoint:** AAPL halted by circuit breaker.

 

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
TRADER01> NEW|SYM=MSFT|SIDE=BUY|TYPE=MARKET|QTY=100
```

Expected: rejection — symbol halted.

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
| Circuit breaker | Per symbol | Price move % in session | Symbol halted |
| Symbol halt | Per symbol | `pm-admin` / `pm-admin-cli` | Trading paused |
| Exchange halt | All symbols | `pm-admin` / `pm-admin-cli` | All trading paused |
| Kill switch | Per gateway | `pm-admin` / `pm-admin-cli` | All orders cancelled |

 

## Reflection

Why does a circuit breaker halt the whole symbol rather than just rejecting
new orders like the collars do? What failure mode (think: a runaway
algorithmic trader or a bad data feed) is a circuit breaker specifically
designed to stop that per-order collars cannot?

## Further Reading

- [Risk Controls](../user-guide/120-risk-controls.md)
- [Controlling the Exchange](../user-guide/160-commands.md)
- [Processes](../user-guide/170-processes.md)
- [Drop Copy](../user-guide/200-drop-copy.md)
- [A Full Trading Day](../concepts/05-concepts-trading-day.md)

 

**Next:** [12 — P&L & Clearing](12-pnl-clearing.md)

# 11 — Risk Controls

## Objective

Configure and trigger the exchange's safety mechanisms: price collars, circuit
breakers, symbol halts, and the kill switch. You will use both the interactive
`pm-admin` console and the one-shot `pm-admin-cli` tool.

---

## Prerequisites

- Chapters 01–10 completed.
- `GW_ADMIN` configured with `role: ADMIN` and connected.

---

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

---

## Exercise 1: Configure Price Collars

Add risk controls to `engine_config.yaml`:

```yaml
risk_controls:
  AAPL:
    static_collar_pct: 10       # ±10% from reference price
    dynamic_collar_ticks: 50    # ±50 ticks from last trade
  MSFT:
    static_collar_pct: 10
    dynamic_collar_ticks: 50
```

Restart the engine.

:material-checkbox-blank-outline: **Checkpoint:** engine loads risk control configuration.

---

## Exercise 2: Trigger a Static Collar Rejection

Place an order far outside the allowed range:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=200.00|TIF=DAY
```

If the reference price is 150.00 and the collar is ±10%, anything above 165.00
or below 135.00 is rejected.

Expected: rejection — price outside static collar.

:material-checkbox-blank-outline: **Checkpoint:** out-of-range order rejected with collar error.

---

## Exercise 3: Configure Circuit Breakers

```yaml
risk_controls:
  AAPL:
    circuit_breaker_pct: 5      # halt if price moves ±5% in one session
    circuit_breaker_cooldown_sec: 30
```

Restart the engine.

:material-checkbox-blank-outline: **Checkpoint:** circuit breaker config loaded.

---

## Exercise 4: Trigger a Circuit Breaker

Push AAPL's price 5% by trading aggressively (you may need to adjust MM bot
gap or trade in volume). When the threshold is breached:

```
[HALT] AAPL — circuit breaker triggered (5.1% move)
```

All resting orders on AAPL are preserved but no new matching occurs.

:material-checkbox-blank-outline: **Checkpoint:** AAPL halted by circuit breaker.

---

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

---

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

---

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

---

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

---

## Exercise 9: Exchange-Wide Halt from the Admin Console

```
[GW_ADMIN|ADMIN]> HALT
```

All symbols stop matching. Then:

```
[GW_ADMIN|ADMIN]> RESUME
```

:material-checkbox-blank-outline: **Checkpoint:** full halt and resume works across all symbols.

---

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

---

## Risk Control Summary

| Control | Scope | Trigger | Effect |
|---------|-------|---------|--------|
| Static collar | Per symbol | Order price vs reference | Order rejected |
| Dynamic collar | Per symbol | Order price vs last trade | Order rejected |
| Circuit breaker | Per symbol | Price move % in session | Symbol halted |
| Symbol halt | Per symbol | `pm-admin` / `pm-admin-cli` | Trading paused |
| Exchange halt | All symbols | `pm-admin` / `pm-admin-cli` | All trading paused |
| Kill switch | Per gateway | `pm-admin` / `pm-admin-cli` | All orders cancelled |

---

## Further Reading

- [Risk Controls](../user-guide/12-risk-controls.md)
- [Controlling the Exchange](../user-guide/02-commands.md)
- [Processes](../user-guide/10-processes.md)
- [Drop Copy](../user-guide/13-drop-copy.md)
- [A Full Trading Day](../concepts/05-concepts-trading-day.md)

---

**Next:** [12 — P&L & Clearing](12-pnl-clearing.md)

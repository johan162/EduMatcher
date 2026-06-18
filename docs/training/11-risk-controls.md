# 11 — Risk Controls

## Objective

Configure and trigger the exchange's safety mechanisms: price collars, circuit
breakers, symbol halts, and the kill switch.

---

## Background

Risk controls prevent erroneous or manipulative orders from distorting the market:

- **Price collars** — reject orders outside static/dynamic price bands.
- **Circuit breakers** — auto-halt a symbol after violent price moves.
- **Symbol halt** — manually halt trading on one instrument.
- **Exchange halt** — halt all trading.
- **Kill switch** — cancel all orders for a specific gateway.

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

## Exercise 5: Manual Symbol Halt and Resume

From the admin gateway:

```
GW_ADMIN> HALT_SYM|SYM=MSFT
```

Try trading MSFT from TRADER01:

```
TRADER01> NEW|SYM=MSFT|SIDE=BUY|TYPE=MARKET|QTY=100
```

Expected: rejection — symbol halted.

Resume:

```
GW_ADMIN> RESUME_SYM|SYM=MSFT
```

:material-checkbox-blank-outline: **Checkpoint:** halt prevents trading; resume restores it.

---

## Exercise 6: Exchange-Wide Halt

```
GW_ADMIN> HALT
```

All symbols stop matching. Then:

```
GW_ADMIN> RESUME
```

:material-checkbox-blank-outline: **Checkpoint:** full halt and resume works across all symbols.

---

## Exercise 7: Kill Switch

Cancel all orders for a misbehaving gateway:

```
GW_ADMIN> KILL|GATEWAY_ID=TRADER02
```

Expected: all of TRADER02's resting orders cancelled.

Or scope to a single symbol:

```
GW_ADMIN> KILL|GATEWAY_ID=TRADER02|SYM=AAPL
```

:material-checkbox-blank-outline: **Checkpoint:** kill switch cancels targeted orders.

---

## Risk Control Summary

| Control | Scope | Trigger | Effect |
|---------|-------|---------|--------|
| Static collar | Per symbol | Order price vs reference | Order rejected |
| Dynamic collar | Per symbol | Order price vs last trade | Order rejected |
| Circuit breaker | Per symbol | Price move % in session | Symbol halted |
| Symbol halt | Per symbol | Admin command | Trading paused |
| Exchange halt | All symbols | Admin command | All trading paused |
| Kill switch | Per gateway | Admin command | All orders cancelled |

---

## Further Reading

- [Risk Controls](../user-guide/12-risk-controls.md)
- [Controlling the Exchange](../user-guide/02-commands.md)
- [Drop Copy](../user-guide/13-drop-copy.md)

---

**Next:** [12 — P&L & Clearing](12-pnl-clearing.md)

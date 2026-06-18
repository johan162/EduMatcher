# 02 — Setting Up MM Bots

## Objective

Add market-maker gateways to your configuration and launch `pm-mm-bot` to
provide continuous two-sided liquidity for all three symbols.

---

## Background

A market maker posts simultaneous buy (bid) and sell (ask) prices. Without one,
the order book is empty and no trader can get an immediate fill. `pm-mm-bot` is
an autonomous bot that maintains a two-sided quote on one symbol.

---

## Exercise 1: Add MM Gateways to Configuration

Extend your `engine_config.yaml` gateways section:

```yaml
gateways:
  alf:
    # ... existing TRADER01, TRADER02, GW_ADMIN entries ...

    - id: MM_AAPL_01
      description: "AAPL market-maker bot"
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_ANY_FILL

    - id: MM_MSFT_01
      description: "MSFT market-maker bot"
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_ANY_FILL

    - id: MM_TSLA_01
      description: "TSLA market-maker bot"
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_ANY_FILL
```

Restart `pm-engine` to pick up the new gateways.

:material-checkbox-blank-outline: **Checkpoint:** engine logs show 6 gateways loaded.

---

## Exercise 2: Launch MM Bot for AAPL

In a new terminal:

```bash
pm-mm-bot --symbol AAPL --gap 0.10 --qty 500
```

Expected output:

```
[INFO] MM_AAPL_01 connected
[INFO] Session: CONTINUOUS — quoting AAPL bid=149.95 ask=150.05
```

The bot uses `last_price` from config as initial mid-price reference.

:material-checkbox-blank-outline: **Checkpoint:** bot is running; no errors.

---

## Exercise 3: Launch Bots for MSFT and TSLA

```bash
# Terminal 5
pm-mm-bot --symbol MSFT --gap 0.20 --qty 300

# Terminal 6
pm-mm-bot --symbol TSLA --gap 0.50 --qty 200
```

:material-checkbox-blank-outline: **Checkpoint:** all three bots report quoting state.

---

## Exercise 4: Verify Liquidity from the Trader Gateway

From `TRADER01`:

```
TRADER01> BOOK|SYM=AAPL
```

You should see a two-sided book with the MM's bid and ask. Repeat for MSFT and TSLA.

```
TRADER01> BOOK|SYM=MSFT
TRADER01> BOOK|SYM=TSLA
```

:material-checkbox-blank-outline: **Checkpoint:** all three books show bid and ask prices.

---

## Exercise 5: Understand the Gap Parameter

The `--gap` controls the total spread:

| Symbol | Gap | Tick | Bid | Ask |
|--------|-----|------|-----|-----|
| AAPL | 0.10 | 0.01 | mid − 0.05 | mid + 0.05 |
| MSFT | 0.20 | 0.01 | mid − 0.10 | mid + 0.10 |
| TSLA | 0.50 | 0.05 | mid − 0.25 | mid + 0.25 |

Try stopping the AAPL bot (Ctrl+C) and restarting with a tighter gap:

```bash
pm-mm-bot --symbol AAPL --gap 0.04 --qty 500
```

Check the book again — the spread should be narrower.

:material-checkbox-blank-outline: **Checkpoint:** you can see the gap reflected in the book.

---

## Exercise 6: Run Two Competing MMs on the Same Symbol

Launch a second AAPL bot with a different suffix:

```bash
pm-mm-bot --symbol AAPL --gap 0.12 --qty 200 --id-suffix 02
```

!!! note
    You must have `MM_AAPL_02` defined in `engine_config.yaml` first.

Check the book — you should see two bid levels and two ask levels.

:material-checkbox-blank-outline: **Checkpoint:** BOOK shows multiple price levels from different MMs.

---

## Summary

You now have:

- Market-maker gateways configured for all symbols.
- `pm-mm-bot` providing continuous liquidity.
- Understanding of `--gap`, `--qty`, and multiple competing MMs.

**Next:** [03 — The First Trade](03-the-first-trade.md)

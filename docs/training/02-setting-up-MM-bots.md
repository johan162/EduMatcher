# 02 — Setting Up Market-Maker Liquidity

## Objective

Configure market-maker gateways and use manual `QUOTE` commands to provide
two-sided liquidity for all three symbols. You will also compare this manual
workflow with `pm-mm-bot`, which automates the same lifecycle.

---

## Prerequisites

- Chapters 00–01 completed.
- `pm-engine` and `pm-scheduler` running.
- At least one trader gateway connected (for book checks).

---

## Background

A market maker posts simultaneous buy (bid) and sell (ask) prices. Without one,
the order book is empty and no trader can get an immediate fill.

!!! note "Manual first, automation second"
  `pm-mm-bot` is available, but this chapter starts with manual
  `pm-gateway` + `QUOTE` so you can see quote lifecycle and operator tools
  directly before using automation.

---

## Exercise 1: Add MM Gateways to Configuration

Extend your `engine_config.yaml` gateways section:

```yaml
gateways:
  alf:
    # ... existing TRADER01, TRADER02, GW_ADMIN entries ...

    - id: MM_AAPL_01
      description: "AAPL market-maker"
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_ANY_FILL

    - id: MM_MSFT_01
      description: "MSFT market-maker"
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_ANY_FILL

    - id: MM_TSLA_01
      description: "TSLA market-maker"
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_ANY_FILL
```

Restart `pm-engine` to pick up the new gateways.

:material-checkbox-blank-outline: **Checkpoint:** engine logs show 6 gateways loaded.

---

## Exercise 2: Connect the AAPL Market Maker

In a new terminal:

```bash
pm-gateway --id MM_AAPL_01
```

At the prompt, submit a two-sided quote:

```
MM_AAPL_01> QUOTE|SYM=AAPL|BID=149.95|ASK=150.05|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=AAPL-MM-001
```

Expected output should include a quote acknowledgement and active status.

:material-checkbox-blank-outline: **Checkpoint:** AAPL quote acknowledged and active.

---

## Exercise 3: Quote MSFT and TSLA

Open one terminal per MM gateway:

```bash
pm-gateway --id MM_MSFT_01
pm-gateway --id MM_TSLA_01
```

Submit quotes:

```
MM_MSFT_01> QUOTE|SYM=MSFT|BID=419.90|ASK=420.10|BID_QTY=300|ASK_QTY=300|TIF=DAY|QUOTE_ID=MSFT-MM-001
MM_TSLA_01> QUOTE|SYM=TSLA|BID=249.75|ASK=250.25|BID_QTY=200|ASK_QTY=200|TIF=DAY|QUOTE_ID=TSLA-MM-001
```

:material-checkbox-blank-outline: **Checkpoint:** all three market makers report active quotes.

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

:material-checkbox-blank-outline: **Checkpoint:** all three books show two-sided liquidity.

---

## Exercise 5: Inspect Quote State with QLEGS

From each market-maker gateway, inspect quote legs:

```
MM_AAPL_01> QLEGS|SYM=AAPL|SHOW=ALL
MM_MSFT_01> QLEGS|SYM=MSFT|SHOW=ALL
MM_TSLA_01> QLEGS|SYM=TSLA|SHOW=ALL
```

`QLEGS` shows the bid and ask leg order IDs, prices, remaining quantities, and
fill flags. This is the operator view that helps you reconcile fills after
restart or partial execution.

Interpretation guide:

- `remaining` is open quantity still resting in the book.
- `filled_qty` is already executed quantity on that leg.
- `status` shows state such as ACTIVE, PARTIAL, or FILLED.

:material-checkbox-blank-outline: **Checkpoint:** QLEGS shows both quote legs for each symbol.

---

## Exercise 6: Run the Equivalent Bot Workflow (Optional)

The manual quote sequence above can be automated with one bot per symbol:

```bash
pm-mm-bot --symbol AAPL --gap 0.10 --qty 500
pm-mm-bot --symbol MSFT --gap 0.20 --qty 300
pm-mm-bot --symbol TSLA --gap 0.50 --qty 200
```

The bot will connect as `MM_<SYMBOL>_01`, quote around the current mid-price,
reissue after fills, and use `QBOOT`/`QLEGS`-style state to avoid startup
deadlocks and reconcile quote legs.

Quick primer:

- `QBOOT` asks the engine whether a gateway+symbol already has an active quote
  slot (for example after a crash/restart).
- `QLEGS` reconciles leg-level state (order IDs, remaining, fills) so the bot
  can adopt or replace safely instead of duplicating quotes.

See the detailed walkthrough in [09 — Market Making](09-market-making.md).

:material-checkbox-blank-outline: **Checkpoint:** explain what the bot automates compared with your manual `QUOTE` workflow.

---

## Summary

You now have:

- Market-maker gateways configured for all symbols.
- Manual `QUOTE` liquidity in AAPL, MSFT, and TSLA.
- Familiarity with `QLEGS` as the quote-leg inspection tool.
- A clear picture of what `pm-mm-bot` automates.

## Further Reading

- [Market Making](../user-guide/14-market-maker.md)
- [Market-Maker Bot (pm-mm-bot)](../user-guide/17-mm-bot.md)
- [Market-Maker Bot CLI Reference](../user-guide/17-mm-bot.md#cli-reference)
- [Gateway Commands](../user-guide/08-gateway.md)
- [ALF Protocol Reference](../user-guide/20-app-alf-protocol.md)

**Next:** [03 — The First Trade](03-the-first-trade.md)

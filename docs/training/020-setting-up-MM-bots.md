# Setting Up Market-Maker Liquidity

## Objective

Configure market-maker gateways and use manual `QUOTE` commands to provide
two-sided liquidity for all three symbols. You will also compare this manual
workflow with `pm-mm-bot`, which automates the same lifecycle.

 


!!! abstract "Pre-reading in the User Guide"
    - [Market Making](../user-guide/090-market-maker.md)
    - [Market-Maker Bot](../user-guide/100-mm-bot.md)

## Prerequisites

- Chapters 00–01 completed.
- `pm-engine` and `pm-scheduler` running.
- At least one trader gateway connected (for book checks).

 

## Background

A market maker posts simultaneous buy (bid) and sell (ask) prices. Without one,
the order book is empty and no trader can get an immediate fill.

!!! note "Manual first, automation second"
  `pm-mm-bot` is available, but this chapter starts with manual
  `pm-alf-console` + `QUOTE` so you can see quote lifecycle and operator tools
  directly before using automation.

 

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

Declaring a `MARKET_MAKER` gateway obliges you to seed a quote for every
symbol it makes a market in. Add a `market_maker_quotes` entry under each
symbol naming its market maker:

```yaml
symbols:
  AAPL:
    tick_decimals: 2
    last_buy_price: 150.00
    last_sell_price: 150.00
    market_maker_quotes:
      - gateway_id: MM_AAPL_01
        bid_price: 149.95
        ask_price: 150.05
        bid_qty: 500
        ask_qty: 500
  # ... the same shape for MSFT/MM_MSFT_01 and TSLA/MM_TSLA_01
```

!!! warning "Skip the seeds and the deploy is refused"
    Without them the verifier raises **M001 (ERROR)** — *"Symbol 'AAPL' has no
    market_maker_quotes entry for MARKET_MAKER gateway(s) MM_AAPL_01"* — and
    `pm-config-deploy` refuses to install a configuration with any error. This
    is the verifier doing its job: a market maker with nothing to quote is a
    configuration mistake, not a runtime one.

Check, deploy, then restart the engine — editing the YAML alone changes
nothing, because every process reads the compiled artifact:

```bash
pm-cverifier engine_config.yaml       # expect 0 errors
pm-config-deploy engine_config.yaml
```

Then restart `pm-engine` to pick up the new gateways.

:material-checkbox-blank-outline: **Checkpoint:** `pm-cverifier` reports 0 errors,
the deploy succeeds, and the engine logs show 6 gateways loaded.

 

## Exercise 2: Connect the AAPL Market Maker

In a new terminal:

```bash
pm-alf-console --id MM_AAPL_01
```

At the prompt, submit a two-sided quote:

```
[MM_AAPL_01]> QUOTE|SYM=AAPL|BID=149.95|ASK=150.05|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=AAPL-MM-001
```

Expected output should include a quote acknowledgement and active status.

:material-checkbox-blank-outline: **Checkpoint:** AAPL quote acknowledged and active.

 

## Exercise 3: Quote MSFT and TSLA

Open one terminal per MM gateway:

```bash
pm-alf-console --id MM_MSFT_01
pm-alf-console --id MM_TSLA_01
```

Submit quotes:

```
[MM_MSFT_01]> QUOTE|SYM=MSFT|BID=419.90|ASK=420.10|BID_QTY=300|ASK_QTY=300|TIF=DAY|QUOTE_ID=MSFT-MM-001
[MM_TSLA_01]> QUOTE|SYM=TSLA|BID=249.75|ASK=250.25|BID_QTY=200|ASK_QTY=200|TIF=DAY|QUOTE_ID=TSLA-MM-001
```

:material-checkbox-blank-outline: **Checkpoint:** all three market makers report active quotes.

 

## Exercise 4: Verify Liquidity from the Trader Gateway

From `TRADER01`:

```
[GW_ADMIN|ADMIN]> BOOK|SYM=AAPL
```

You should see a two-sided book with the MM's bid and ask. Repeat for MSFT and TSLA.

```
[GW_ADMIN|ADMIN]> BOOK|SYM=MSFT
[GW_ADMIN|ADMIN]> BOOK|SYM=TSLA
```

:material-checkbox-blank-outline: **Checkpoint:** all three books show two-sided liquidity.

 

## Exercise 5: Inspect Quote State with QLEGS

From each market-maker gateway, inspect quote legs:

```
[MM_AAPL_01]> QLEGS|SYM=AAPL|SHOW=ALL
[MM_MSFT_01]> QLEGS|SYM=MSFT|SHOW=ALL
[MM_TSLA_01]> QLEGS|SYM=TSLA|SHOW=ALL
```

`QLEGS` shows the bid and ask leg order IDs, prices, remaining quantities, and
fill flags. This is the operator view that helps you reconcile fills after
restart or partial execution.

Interpretation guide:

- `Rem` is open quantity still resting in the book.
- `Filled` is already executed quantity on that leg.
- `Leg status` shows state such as `RESTING`, `PARTIAL`, or `FILLED`.

:material-checkbox-blank-outline: **Checkpoint:** QLEGS shows both quote legs for each symbol.

 

## Exercise 6: Run the Equivalent Bot Workflow (Optional)

The manual quote sequence above can be automated with one bot per symbol:

```bash
pm-mm-bot --symbol AAPL --gap 0.10 --qty 500
pm-mm-bot --symbol MSFT --gap 0.20 --qty 300
pm-mm-bot --symbol TSLA --gap 0.50 --qty 200
```

The bot connects using the gateway ID `MM_<SYMBOL>_<id-suffix>` (default
suffix `01`), quotes around the current mid-price, reissues after fills, and
uses `QBOOT`/`QLEGS`-style state to avoid startup deadlocks and reconcile
quote legs.

!!! warning "Gateway ID must already exist in your config"
    `pm-mm-bot` does not create a gateway — it connects under the ID it
    computes (`MM_AAPL_01`, `MM_MSFT_01`, `MM_TSLA_01` by default) and expects
    that ID to already be present in `engine_config.yaml` from Exercise 1. If
    your config used different gateway IDs, either rename them to match this
    pattern or pass `--id-suffix` to the bot so the computed ID lines up. A
    mismatch here causes the engine to reject the bot's connection.

Quick primer:

- `QBOOT` asks the engine whether a gateway+symbol already has an active quote
  slot (for example after a crash/restart).
- `QLEGS` reconciles leg-level state (order IDs, remaining, fills) so the bot
  can adopt or replace safely instead of duplicating quotes.

See the detailed walkthrough in [09 — Market Making](090-market-making.md).

:material-checkbox-blank-outline: **Checkpoint:** explain what the bot automates compared with your manual `QUOTE` workflow.

 

## Summary

You now have:

- Market-maker gateways configured for all symbols.
- Manual `QUOTE` liquidity in AAPL, MSFT, and TSLA.
- Familiarity with `QLEGS` as the quote-leg inspection tool.
- A clear picture of what `pm-mm-bot` automates.

## Reflection

If no market maker were quoting a symbol, what would happen to a marketable
order sent by a regular trader in Chapter 03? Why does the training guide
insist you set up liquidity *before* any trading exercises rather than
letting students discover an empty book on their own?

## Further Reading

- [Market Making](../user-guide/090-market-maker.md)
- [Market-Maker Bot (pm-mm-bot)](../user-guide/100-mm-bot.md)
- [Market-Maker Bot CLI Reference](../user-guide/100-mm-bot.md#cli-reference)
- [ALF Console (pm-alf-console)](../user-guide/055-alf-console.md)
- [ALF Protocol Reference](../user-guide/900-app-alf-protocol.md)

**Next:** [03 — The First Trade](030-the-first-trade.md)

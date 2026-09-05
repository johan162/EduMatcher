# Setting Up Market-Maker Liquidity

## Objective

Configure market-maker gateways and use manual `QUOTE` commands to provide
two-sided liquidity for all three symbols. You will also compare this manual
workflow with `pm-mm-bot`, which automates the same lifecycle — including how
to drive the bot from a committed config file instead of a long CLI
invocation.

 


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

!!! tip "pm-config-gen can generate the seeds instead of hand-writing them"
    `pm-config-gen` (Chapter 01) will emit a `market_maker_quotes` stub for
    every `MARKET_MAKER` gateway automatically — you don't have to hand-write
    the block above. Two ways to use it:

    ```bash
    # Stub only: emits gateway_id/bid_qty/ask_qty/tif, but bid_price and
    # ask_price are left as `null` for you to fill in by hand
    pm-config-gen \
      --symbols AAPL MSFT TSLA \
      --gateways TRADER01 TRADER02 GW_ADMIN:ADMIN \
        MM_AAPL_01:MARKET_MAKER MM_MSFT_01:MARKET_MAKER MM_TSLA_01:MARKET_MAKER \
      --enforce-mm-obligations \
      --output engine_config.yaml --force

    # Fully seeded: also fills bid_price/ask_price from a random midpoint in
    # the given range, rounded to each symbol's tick grid
    pm-config-gen \
      --symbols AAPL MSFT TSLA \
      --gateways TRADER01 TRADER02 GW_ADMIN:ADMIN \
        MM_AAPL_01:MARKET_MAKER MM_MSFT_01:MARKET_MAKER MM_TSLA_01:MARKET_MAKER \
      --enforce-mm-obligations \
      --seed-mm-mid-range 100:400 \
      --output engine_config.yaml --force
    ```

    The first form is a trap worth knowing about: `pm-cverifier` will report
    **0 errors** on the stub — `market_maker_quotes` entries exist, so M001
    doesn't fire, and the required keys are all present (just `null`), so the
    schema check doesn't fire either. The verifier cannot see that `null` is
    unusable. It's `pm-config-deploy` that catches it, at compile time, with
    `Symbol 'AAPL': market_maker_quotes[0] is invalid` — because loading the
    artifact tries `float(None)`. `pm-config-gen` itself warns you about this
    up front with `[HINT] Fill all market_maker_quotes bid_price/ask_price
    values before starting pm-engine`, right after it writes the file — that
    hint is the moment to either fill the two prices in by hand or rerun with
    `--seed-mm-mid-range` instead.

    If you never want seeded quotes at all (a deliberately empty book for a
    symbol), `--no-mm-seed-quotes` sets `require_mm_seed_quotes: false` and
    suppresses M001 for that config entirely — no stub is emitted and no
    price is expected.

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
- `Leg status` is one of `NEW`, `PARTIAL`, `FILLED`, `CANCELLED`, `EXPIRED`, or `PENDING` — a resting, untouched leg shows `NEW`, not `RESTING`.

:material-checkbox-blank-outline: **Checkpoint:** QLEGS shows both quote legs for each symbol.

 

## Exercise 6: Run the Equivalent Bot Workflow (Optional)

The manual quote sequence above can be automated with one bot per symbol.
Stop your manual quotes first (`QUOTE_CANCEL|SYM=<symbol>` from each MM
console, or just leave them — the bot's own startup reconciliation handles
either case, see the note below) and run:

```bash
pm-mm-bot --symbol AAPL --gap 0.10 --qty 500
pm-mm-bot --symbol MSFT --gap 0.20 --qty 300
pm-mm-bot --symbol TSLA --gap 0.50 --qty 200
```

The bot connects using the gateway ID `MM_<SYMBOL>_<id-suffix>` (default
suffix `01`), quotes symmetrically around the current mid-price at `--gap`,
reissues after fills, and reprices when the mid drifts. It also runs a
`QBOOT` request at startup so it can adopt an already-active quote instead of
creating a duplicate, and periodically re-runs `QLEGS` to reconcile leg state
in case an engine reply was ever dropped.

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

See the detailed walkthrough in [09 — Market Making](090-market-making.md), and
[20 — Automation with CommandClient & MM Bot Tuning](210-automation-commandclient-mm-bot.md)
for the advanced runtime flags (bootstrap timeout, QLEGS reconciliation
interval, and similar) that this chapter deliberately leaves out.

:material-checkbox-blank-outline: **Checkpoint:** explain what the bot automates compared with your manual `QUOTE` workflow.

 

## Exercise 7: Drive the Bot from a Config File

Every CLI flag except `--config` itself and the logging flags can instead
live in a version-controlled YAML file, keyed by the flag's long name with
dashes replaced by underscores. Create `mm_aapl.yaml`:

```yaml
symbol: AAPL
id_suffix: "01"
strategy: symmetric
gap: 0.10
qty: 500
tif: DAY
drift_ticks: 3
```

Run the bot from it instead of typing the flags:

```bash
pm-mm-bot --config mm_aapl.yaml
```

An explicit CLI flag always overrides the same key from the file, so you can
keep one committed file per symbol for a class and still override a single
value for a one-off run:

```bash
pm-mm-bot --config mm_aapl.yaml --gap 0.15
```

`--symbol` may be omitted from the CLI entirely as long as the file supplies
it — but the bot fails fast with a usage error if *neither* the CLI nor the
file provides one, rather than silently picking a default symbol.

!!! note "`--strategy` exists but only one strategy ships today"
    `strategy: symmetric` (the default, so the line above is not strictly
    needed) selects the pricing logic that turns the tracked mid-price into a
    bid/ask — quote symmetrically around mid at `gap`. It's the only pricing
    strategy that ships today; the selection point exists so a future
    strategy (skewing the quote by inventory, or widening the gap with
    volatility) can be added later without changing anything else about the
    bot. Naming any other strategy is a startup failure, not a silent
    fallback.

!!! warning "A typo in the file fails fast, not silently"
    An unknown key in the file — a flag name spelled with dashes instead of
    underscores, or a genuine typo — is rejected at startup with
    `invalid config file: ... unknown key(s)`, the same way an unrecognised
    CLI flag would be. It is never silently ignored.

:material-checkbox-blank-outline: **Checkpoint:** you have started a bot from
a config file alone, then overridden one value from the CLI and confirmed the
CLI value won.

 

## Summary

You now have:

- Market-maker gateways configured for all symbols, seeded either by hand or
  with `pm-config-gen --seed-mm-mid-range`.
- Manual `QUOTE` liquidity in AAPL, MSFT, and TSLA.
- Familiarity with `QLEGS` as the quote-leg inspection tool.
- A clear picture of what `pm-mm-bot` automates, and how to drive it from
  either the CLI or a committed config file.

## Reflection

If no market maker were quoting a symbol, what would happen to a marketable
order sent by a regular trader in Chapter 03? Why does the training guide
insist you set up liquidity *before* any trading exercises rather than
letting students discover an empty book on their own?

`pm-config-gen`'s stub `market_maker_quotes` entry (no `--seed-mm-mid-range`)
passes `pm-cverifier` with 0 errors, yet still fails at `pm-config-deploy`.
Why do you think the verifier and the compile-time loader disagree here —
what would it take for the verifier to catch a `null` bid/ask price itself,
and can you think of a reason the two checks are allowed to diverge like
this rather than the verifier being made strict enough to catch everything
`pm-config-deploy` would?

## Further Reading

- [Market Making](../user-guide/090-market-maker.md)
- [Market-Maker Bot (pm-mm-bot)](../user-guide/100-mm-bot.md)
- [Market-Maker Bot CLI Reference](../user-guide/100-mm-bot.md#cli-reference)
- [Market-Maker Bot — Config File](../user-guide/100-mm-bot.md#config-file)
- [ALF Console (pm-alf-console)](../user-guide/055-alf-console.md)
- [ALF Protocol Reference](../user-guide/900-app-alf-protocol.md)
- [Config Verifier (`pm-cverifier`)](../user-guide/020-config-verifier.md)
- [20 — Automation with CommandClient & MM Bot Tuning](210-automation-commandclient-mm-bot.md)

**Next:** [03 — The First Trade](030-the-first-trade.md)

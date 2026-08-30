# Capstone Scenario

## Objective

Run a complete exchange session that combines configuration, market making,
trading, risk controls, clearing, market data, persistence, and reporting.

 


!!! abstract "Pre-reading in the User Guide"
    - [Running the Exchange](../user-guide/040-running-the-exchange.md)
    - [Processes](../user-guide/170-processes.md)

## Prerequisites

- Chapters 01–16 completed.
- Ability to run multiple terminals/processes simultaneously.

 

## Scenario

You are running a classroom exchange with three symbols (`AAPL`, `MSFT`, `TSLA`),
two human traders, three AI traders, one admin/operator, one market maker per
symbol and a spare manual market maker. Your goal is to open the market,
provide liquidity, generate trades, trigger a risk event, inspect
P&L/statistics, and verify persistence.

This chapter rebuilds the configuration from scratch rather than continuing
from Chapter 16's. That is deliberate — an operator should be able to stand a
venue up from nothing — but it means Exercise 1 re-declares every gateway the
earlier chapters introduced, so nothing you learned to use disappears.

 

## Exercise 1: Generate a Fresh Config

!!! warning "`--force` overwrites the configuration you have been building"
    This command replaces `engine_config.yaml` outright. Everything you added
    by hand in earlier chapters — `MM_MANUAL_01` from Chapter 09, the `AI01`–
    `AI03` gateways from Chapter 14, any collar or circuit-breaker tuning from
    Chapter 11 — is gone unless the command below re-creates it.

    Back it up first so you can compare, or return to it afterwards:

    ```bash
    cp engine_config.yaml engine_config.pre-capstone.yaml
    ```

The command below deliberately re-declares **every** gateway the earlier
chapters introduced, so the capstone exercises a complete venue rather than a
subset:

```bash
pm-config-gen \
  --symbols AAPL MSFT TSLA \
  --gateways TRADER01:TRADER TRADER02:TRADER GW_ADMIN:ADMIN \
             MM_AAPL_01:MARKET_MAKER MM_MSFT_01:MARKET_MAKER MM_TSLA_01:MARKET_MAKER \
             MM_MANUAL_01:MARKET_MAKER \
             AI01:TRADER AI02:TRADER AI03:TRADER \
  --sessions-enabled \
  --static-band 0.10 \
  --dynamic-band 0.05 \
  --seed-mm-mid-range 90:430 \
  --seed-last-prices-from-mm \
  --output engine_config.yaml --force
```

The two `--seed-*` flags are not optional decoration. Four `MARKET_MAKER`
gateways with no `market_maker_quotes` would fail verification with **M001
(ERROR)**, and `pm-config-deploy` refuses any configuration containing an
error — so without them this capstone stops at Exercise 2. Chapter 02
Exercise 1 covered the same rule.

Open the file and confirm the symbol and gateway sections are present.

:material-checkbox-blank-outline: **Checkpoint:** config contains 3 symbols,
5 traders (`TRADER01`, `TRADER02`, `AI01`–`AI03`), 1 admin, and 4 market
makers — and every symbol has a `market_maker_quotes` block.

 

## Exercise 2: Verify and Deploy

A generated file is not a running configuration. Verify it, then install it —
this is the step that makes everything after it possible:

```bash
pm-cverifier engine_config.yaml       # expect: 0 ERRORS
pm-config-deploy engine_config.yaml
pm-config-deploy --show               # confirm where it landed
```

Warnings and advisories are fine here; errors are not. If `pm-cverifier`
reports an error, fix it before deploying — a refused deploy leaves the
*previous* configuration running, which is the confusing case where the
exchange starts but has the wrong gateways.

:material-checkbox-blank-outline: **Checkpoint:** `pm-cverifier` reports 0
errors and `pm-config-deploy` completes.

 

## Exercise 3: Start the Exchange Stack

Use separate terminals:

```bash
pm-engine --verbose
pm-scheduler
pm-stats
pm-clearing
pm-audit --terminal
pm-viewer --symbol AAPL
```

:material-checkbox-blank-outline: **Checkpoint:** every process starts cleanly and connects.

 

## Exercise 4: Connect Gateways

Open gateway terminals:

```bash
pm-alf-console --id TRADER01
pm-alf-console --id TRADER02
pm-admin        --id GW_ADMIN          # the operator console — a different program
pm-alf-console --id MM_AAPL_01
pm-alf-console --id MM_MSFT_01
pm-alf-console --id MM_TSLA_01
```

`MM_MANUAL_01` and `AI01`–`AI03` are configured but do not need a console of
their own yet: `MM_MANUAL_01` is there if you want to repeat Chapter 09's
manual quoting against this venue, and the AI gateways are driven by
`pm-ai-trader` in Exercise 6 rather than typed at.

Confirm the engine agrees with your configuration:

```
[GW_ADMIN|ADMIN]> GATEWAYS
```

All ten should be listed, with the six above showing as connected.

:material-checkbox-blank-outline: **Checkpoint:** `GATEWAYS` lists all ten
configured identities, and the six consoles you opened authenticate.

 

## Exercise 5: Provide Manual MM Liquidity

Submit quotes:

```
[MM_AAPL_01]> QUOTE|SYM=AAPL|BID=149.95|ASK=150.05|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=AAPL-CAP-001
[MM_MSFT_01]> QUOTE|SYM=MSFT|BID=419.90|ASK=420.10|BID_QTY=300|ASK_QTY=300|TIF=DAY|QUOTE_ID=MSFT-CAP-001
[MM_TSLA_01]> QUOTE|SYM=TSLA|BID=249.75|ASK=250.25|BID_QTY=200|ASK_QTY=200|TIF=DAY|QUOTE_ID=TSLA-CAP-001
```

Verify with `QLEGS|SHOW=ALL` on each MM gateway (trader console) and `BOOK|SYM=...` in the operator console.

:material-checkbox-blank-outline: **Checkpoint:** every symbol has a live two-sided market.

 

## Exercise 6: Generate Trades and Amendments

From `TRADER01`:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
[TRADER01]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=419.50|TIF=DAY
[TRADER01]> ORDERS
[TRADER01]> AMEND|ID=<msft_order_id>|PRICE=419.70
```

From `TRADER02`:

```
[TRADER02]> NEW|SYM=MSFT|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=419.70|TIF=DAY
```

Now add background flow, so the later P&L and statistics exercises have more
than a handful of hand-typed trades to work with. Start the three AI gateways
you configured in Exercise 1, each with a different personality, in their own
terminals:

```bash
pm-ai-trader --id AI01 --profile aggressive  --duration 300
pm-ai-trader --id AI02 --profile cautious    --duration 300
pm-ai-trader --id AI03 --profile many-small  --duration 300
```

`--duration 300` stops them after five minutes, which is long enough for the
rest of the capstone and short enough that you are not chasing runaway
processes later. Watch `pm-viewer` — the book should get noticeably busier.

:material-checkbox-blank-outline: **Checkpoint:** you have at least one market
fill, one amended order, one cross-trader fill, and a visible stream of AI
trades in `pm-viewer` and `pm-audit`.

 

## Exercise 7: Trigger an Operator Action

From the admin gateway:

```
[GW_ADMIN|ADMIN]> HALT_SYM|SYM=TSLA
```

Try to trade TSLA from a trader gateway and confirm it is rejected. Then resume:

```
[GW_ADMIN|ADMIN]> RESUME_SYM|SYM=TSLA
```

:material-checkbox-blank-outline: **Checkpoint:** symbol halt blocks trading and resume restores it.

 

## Exercise 8: Inspect P&L, Audit, and Stats

Check the observer terminals and run:

```bash
pm-stats-cli trades --symbol AAPL --limit 10
pm-stats-cli daily
```

(`daily` with no `--symbol` filter gives one OHLCV summary row per symbol —
see [15 — Statistics & Reporting](15-statistics-reporting.md) for the full
`pm-stats-cli` verb reference; there is no separate `summary` verb.)

Explain what each observer showed:

- `pm-clearing`: positions and P&L.
- `pm-audit`: raw event stream.
- `pm-stats-cli`: persisted trade/statistics view.
- `pm-viewer`: current book state.

:material-checkbox-blank-outline: **Checkpoint:** you can trace one trade through all observers.

 

## Exercise 9: Persistence Check

Place a GTC order, restart the engine, and confirm whether it restores:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=140.00|TIF=GTC
```

Restart `pm-engine`, reconnect `TRADER01`, then run:

```
[TRADER01]> ORDERS
```

:material-checkbox-blank-outline: **Checkpoint:** you can explain what persisted and what expired.

 

## Final Review Questions

Answer these without looking at earlier chapters:

1. Which process owns the order book?
2. Which commands create, amend, cancel, and inspect resting orders?
3. Why does a quote have both a `quote_id` and two child order IDs?
4. What is the difference between public market data and drop-copy?
5. Which order types never rest on the book?
6. What happens to DAY vs GTC orders at session close?
7. How do you halt and resume a single symbol?

:material-checkbox-blank-outline: **Checkpoint:** you can answer every question from memory or by using the user guide.

Review map:

- Q1: [Architecture Overview](../architecture/01-architecture.md)
- Q2: [ALF Console (pm-alf-console)](../user-guide/055-alf-console.md)
- Q3: [MM Quotes Concept](../concepts/03-concepts-mm-quotes.md)
- Q4: [Drop Copy](../user-guide/200-drop-copy.md)
- Q5: [Order Types](../user-guide/060-order-types.md)
- Q6: [Time-in-Force & Session Lifecycle](../user-guide/080-session-scheduling.md)
- Q7: [Controlling the Exchange](../user-guide/160-exchange-commands.md)

 

## Further Reading

- [How an Exchange Works](../how-exchange-works.md)
- [User Guide](../user-guide/000-getting-started.md)
- [Architecture Overview](../architecture/01-architecture.md)
- [Glossary](../glossary.md)
- [Exchange Observer Processes](18-exchange-observer-processes.md)
- [Order Book Deep Dive](../concepts/02-concepts-order-book-deep-dive.md)

You have completed the capstone. Finish with
[18 — Exchange Observer Processes](18-exchange-observer-processes.md) to compare
the different live views of the exchange.

# 17 — Capstone Scenario

## Objective

Run a complete exchange session that combines configuration, market making,
trading, risk controls, clearing, market data, persistence, and reporting.

---

## Scenario

You are running a classroom exchange with three symbols (`AAPL`, `MSFT`, `TSLA`),
two human traders, one admin/operator, and one manual market maker per symbol.
Your goal is to open the market, provide liquidity, generate trades, trigger a
risk event, inspect P&L/statistics, and verify persistence.

---

## Exercise 1: Generate a Fresh Config

```bash
pm-config-gen \
  --symbols AAPL MSFT TSLA \
  --gateways TRADER01:TRADER TRADER02:TRADER GW_ADMIN:ADMIN MM_AAPL_01:MARKET_MAKER MM_MSFT_01:MARKET_MAKER MM_TSLA_01:MARKET_MAKER \
  --sessions-enabled \
  --static-band 0.10 \
  --dynamic-band 0.05 \
  --output engine_config.yaml --force
```

Open the file and confirm the symbol and gateway sections are present.

:material-checkbox-blank-outline: **Checkpoint:** config contains 3 symbols, 2 traders, 1 admin, and 3 MMs.

---

## Exercise 2: Start the Exchange Stack

Use separate terminals:

```bash
pm-engine --config engine_config.yaml --verbose
pm-scheduler
pm-stats
pm-clearing
pm-audit --terminal
pm-viewer --symbol AAPL
```

:material-checkbox-blank-outline: **Checkpoint:** every process starts cleanly and connects.

---

## Exercise 3: Connect Gateways

Open gateway terminals:

```bash
pm-gateway --id TRADER01
pm-gateway --id TRADER02
pm-gateway --id GW_ADMIN
pm-gateway --id MM_AAPL_01
pm-gateway --id MM_MSFT_01
pm-gateway --id MM_TSLA_01
```

:material-checkbox-blank-outline: **Checkpoint:** all gateway identities authenticate.

---

## Exercise 4: Provide Manual MM Liquidity

Submit quotes:

```
MM_AAPL_01> QUOTE|SYM=AAPL|BID=149.95|ASK=150.05|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=AAPL-CAP-001
MM_MSFT_01> QUOTE|SYM=MSFT|BID=419.90|ASK=420.10|BID_QTY=300|ASK_QTY=300|TIF=DAY|QUOTE_ID=MSFT-CAP-001
MM_TSLA_01> QUOTE|SYM=TSLA|BID=249.75|ASK=250.25|BID_QTY=200|ASK_QTY=200|TIF=DAY|QUOTE_ID=TSLA-CAP-001
```

Verify with `QLEGS|SHOW=ALL` on each MM gateway and `BOOK|SYM=...` from a trader.

:material-checkbox-blank-outline: **Checkpoint:** every symbol has a live two-sided market.

---

## Exercise 5: Generate Trades and Amendments

From `TRADER01`:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
TRADER01> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=419.50|TIF=DAY
TRADER01> ORDERS
TRADER01> AMEND|ID=<msft_order_id>|PRICE=419.70
```

From `TRADER02`:

```
TRADER02> NEW|SYM=MSFT|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=419.70|TIF=DAY
```

:material-checkbox-blank-outline: **Checkpoint:** you have at least one market fill, one amended order, and one cross-trader fill.

---

## Exercise 6: Trigger an Operator Action

From the admin gateway:

```
GW_ADMIN> HALT_SYM|SYM=TSLA
```

Try to trade TSLA from a trader gateway and confirm it is rejected. Then resume:

```
GW_ADMIN> RESUME_SYM|SYM=TSLA
```

:material-checkbox-blank-outline: **Checkpoint:** symbol halt blocks trading and resume restores it.

---

## Exercise 7: Inspect P&L, Audit, and Stats

Check the observer terminals and run:

```bash
pm-stats-cli trades --symbol AAPL --limit 10
pm-stats-cli summary
```

Explain what each observer showed:

- `pm-clearing`: positions and P&L.
- `pm-audit`: raw event stream.
- `pm-stats-cli`: persisted trade/statistics view.
- `pm-viewer`: current book state.

:material-checkbox-blank-outline: **Checkpoint:** you can trace one trade through all observers.

---

## Exercise 8: Persistence Check

Place a GTC order, restart the engine, and confirm whether it restores:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=140.00|TIF=GTC
```

Restart `pm-engine`, reconnect `TRADER01`, then run:

```
TRADER01> ORDERS
```

:material-checkbox-blank-outline: **Checkpoint:** you can explain what persisted and what expired.

---

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

---

## Further Reading

- [How an Exchange Works](../how-exchange-works.md)
- [User Guide](../user-guide/00-getting-started.md)
- [Architecture Overview](../architecture/01-architecture.md)
- [Glossary](../glossary.md)
- [Exchange Observer Processes](18-exchange-observer-processes.md)

You have completed the capstone. Finish with
[18 — Exchange Observer Processes](18-exchange-observer-processes.md) to compare
the different live views of the exchange.

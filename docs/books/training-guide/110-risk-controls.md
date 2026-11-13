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
- `pm-admin-cli --id ADMIN_CLI <command>` — one command, one response,
  useful for scripts, demos, and operational runbooks.

Both require a gateway configured with `role: ADMIN`. The chapter 01
configuration uses distinct IDs so both tools can stay connected at once:
`GW_ADMIN` for the console and `ADMIN_CLI` for the CLI. The engine allows
only one live connection per participant ID.

 

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
10%. A field you leave out of a `collar:` block gets a built-in default
(`static_band_pct: 0.20`, `dynamic_band_pct: 0.02`). Leave the whole `collar:` section out and the symbol gets **no
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

The collar and circuit-breaker exercises compare prices with the symbol's
reference price and recent trades. After chapter 10 the engine remembers the
last trades of those labs, so start from a clean slate. Stop every `pm-*`
program you started — `pm-engine`, the consoles, any `pm-mm-bot`, and
`pm-clearing` if it still runs from chapter 03 (`Ctrl-C` in each) — then
clear the exchange's working state:

```bash
pm-opctl-cli clear --state
```

Answer `y`. This deletes the remembered prices, resting orders and the
statistics and clearing databases, but not your configuration (see
[Starting over](#starting-over)). If it warns that `pm-*` processes are
still running, one of them is still up: stop it and run the command again. Restart `pm-engine`, your consoles, and
reopen the market. The reference prices are now 150.00, 420.00 and 250.00
again, from your configuration.

:material-checkbox-blank-outline: **Checkpoint:** engine loads risk control configuration.

 

## Exercise 2: Trigger a Static Collar Rejection

Place an order far outside the allowed range:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=200.00|TIF=DAY
```

If the reference price is 150.00 and the static collar is ±10%, anything
above 165.00 or below 135.00 is rejected.

Expected: `REJECTED … code=COLLAR_BREACH  STATIC_COLLAR_BREACH: price 20000 ticks is
outside [13500, 16500] ticks (±10% from reference 15000)` (prices are shown in
ticks of 0.01).

:material-checkbox-blank-outline: **Checkpoint:** out-of-range order rejected with collar error.

 

## Exercise 3: Configure Circuit Breakers

Circuit-breaker trigger percentages and halt durations come from a global
ladder, `circuit_breaker_defaults`, applied to every symbol unless a symbol
defines its own `circuit_breaker.levels` override (see the `TSLA` pattern in
[The Configuration Workflow](../operator-guide/part-2-configure/010-the-configuration-workflow.md#risk-controls-and-collars)).
Add a one-level ladder:

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
accepted and rest: a halt is the collection phase of a *reopening auction*.
`halt_duration_ns` is the *minimum* length of that phase; the engine adds a
random 0–30 s on top, so nobody can time the last order in. Expect AAPL to
reopen 30–60 s after the halt.

Verification drill, while the halt lasts:

1. Send a market order — it is rejected with `code=CIRCUIT_BREAKER_ACTIVE`:

    ```
    [TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
    ```

2. Send a limit order — it is accepted and rests, waiting for the reopening:

    ```
    [TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=160.00|TIF=DAY
    ```

3. Wait for the reopening. The engine log shows the auction and the resume:

    ```
    UNCROSS AAPL: no crossable interest
    CIRCUIT BREAKER RESUME AAPL: after 0 ACE extension(s)
    ```

    Nothing crossed, because nobody offered at or below 160.00, so your
    buy is still resting. Had someone offered, say 60 at 159.80, the
    reopening auction would have traded them at one price, exactly like the
    opening auction of [chapter 07](070-auctions.md).

:material-checkbox-blank-outline: **Checkpoint:** AAPL halted by the circuit breaker after the fourth step; a market order is rejected, a limit order rests, and the symbol reopens on its own.

 

## Exercise 5: Manual Symbol Halt and Resume

From the `pm-admin` console:

```
[GW_ADMIN|ADMIN]> HALT_SYM|SYM=MSFT
```

Try trading MSFT from TRADER01:

```
[TRADER01]> NEW|SYM=MSFT|SIDE=BUY|TYPE=MARKET|QTY=100
```

Expected: `REJECTED … code=INSTRUMENT_HALTED  MSFT is halted — MARKET orders
rejected during trading halt`. (A *limit* order would be accepted and rest for
the reopening, as in Exercise 4.) The `HALT_SYM` reply also tells you how many
market-maker quote legs it pulled: `HALTED  MSFT  2 quote leg(s) cancelled`.

Resume:

```
[GW_ADMIN|ADMIN]> RESUME_SYM|SYM=MSFT
```

:material-checkbox-blank-outline: **Checkpoint:** halt prevents trading; resume restores it.

 

## Exercise 6: Exchange-Wide Halt with pm-admin-cli

Use the one-shot CLI form when you want an operation to run from a script or
checklist without opening an interactive console.

!!! note "Use a separate identity for each operator client"
    The interactive console remains connected as `GW_ADMIN`; one-shot commands
    use `ADMIN_CLI`. If both tools use `GW_ADMIN`, the second connection is
    refused with `Gateway already connected: GW_ADMIN`.

```bash
pm-admin-cli --id ADMIN_CLI halt
```

It prints `HALTED  3 symbol(s), <n> quote leg(s) cancelled` and exits. All
symbols stop matching, but the session phase does not change —
`pm-admin-cli --id ADMIN_CLI session-status` still says `CONTINUOUS`. A halt
is per symbol, not a session state. Prove it is in force by sending a
`MARKET` order from `TRADER01` on any symbol: it is rejected. Then resume:

```bash
pm-admin-cli --id ADMIN_CLI resume
```

The interactive console has the same pair as `HALT` and `RESUME`.

:material-checkbox-blank-outline: **Checkpoint:** `pm-admin-cli` halts and resumes the exchange without entering a REPL.

 

## Exercise 7: Query and Manage with pm-admin-cli

Try the read-only commands first:

```bash
pm-admin-cli --id ADMIN_CLI book --sym AAPL
pm-admin-cli --id ADMIN_CLI orders --gw TRADER01
pm-admin-cli --id ADMIN_CLI gateways
pm-admin-cli --id ADMIN_CLI volume
pm-admin-cli --id ADMIN_CLI schedule
```

`schedule` shows a dash in every cell: your configuration has no `schedule:`
block (chapter 01).

Now halt and resume one symbol through the CLI:

```bash
pm-admin-cli --id ADMIN_CLI halt-sym --sym TSLA
pm-admin-cli --id ADMIN_CLI resume-sym --sym TSLA
```

:material-checkbox-blank-outline: **Checkpoint:** you can choose `pm-admin` for interactive operation and `pm-admin-cli` for repeatable one-shot commands.

 

## Exercise 8: Kill Switch

Give `TRADER02` something to lose first — three resting sells that will not
trade:

```
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=10|PRICE=152.00|TIF=DAY
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=10|PRICE=153.00|TIF=DAY
[TRADER02]> NEW|SYM=MSFT|SIDE=SELL|TYPE=LIMIT|QTY=10|PRICE=425.00|TIF=DAY
```

Pull only its AAPL orders, then everything that is left:

```
[GW_ADMIN|ADMIN]> KILL|GW=TRADER02|SYM=AAPL
[GW_ADMIN|ADMIN]> KILL|GW=TRADER02
```

Expected: `KILL OK  TRADER02  orders=2  quotes=0`, then
`KILL OK  TRADER02  orders=1  quotes=0`. `TRADER02` stays connected and sees a
`CANCELLED … reason=KILL_SWITCH` line per order.

The same operation as a one-shot CLI command is:

```bash
pm-admin-cli --id ADMIN_CLI kill --gw TRADER02 --sym AAPL
```

:material-checkbox-blank-outline: **Checkpoint:** kill switch cancels targeted orders.

 

## Exercise 9: Named Risk Levels — One Policy, Many Symbols

Exercise 1 gave each symbol its own inline `collar:`. With 150 symbols that is
150 copies of the same numbers. A **risk level** is a named collar profile that
symbols share: define it once under `risk_controls.levels`, pick a
`default_level` for symbols that name none, and let a volatile or thinly traded
symbol opt into a looser one with `level:`.

Replace the inline collars of AAPL and MSFT by this (keep `TSLA` and the other
symbols as they are, with no `collar:` and no `level:`):

```yaml
risk_controls:
  default_level: L2
  levels:
    L1:                       # loose: for volatile names
      collar:
        static_band_pct: 0.30
        dynamic_band_pct: 0.05
    L2:                       # tight: the house default
      collar:
        static_band_pct: 0.05
        dynamic_band_pct: 0.02

symbols:
  MSFT:
    level: L1                 # MSFT opts into the loose profile
```

AAPL and TSLA name no level, so both get `default_level: L2`. Check and deploy.

The circuit-breaker walk of Exercise 4 moved AAPL's reference, so reset the
working state again exactly as in Exercise 1: stop `pm-engine` and the
consoles, run `pm-opctl-cli clear --state`, restart, reopen the market and
clear the three books with `CANCEL_SYM` (the restart places the
market-maker seed quotes again). A same-business-day restart alone is not
enough: it restores resting `DAY` orders and the remembered prices.

The reference prices are now 150, 420 and 250 again (from your configuration)
and there is no last trade. **Predict** the outcome of each order before
sending it. Use buys below the market, which rest instead of trading, so that
only the *static* band is being tested:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=1|PRICE=143.00|TIF=DAY
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=1|PRICE=142.00|TIF=DAY
[TRADER01]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=1|PRICE=300.00|TIF=DAY
[TRADER01]> NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=1|PRICE=290.00|TIF=DAY
[TRADER01]> NEW|SYM=TSLA|SIDE=BUY|TYPE=LIMIT|QTY=1|PRICE=240.00|TIF=DAY
[TRADER01]> NEW|SYM=TSLA|SIDE=BUY|TYPE=LIMIT|QTY=1|PRICE=237.00|TIF=DAY
```

| Order | Band that applies | Result |
|---|---|---|
| AAPL 143.00 | L2 (default), ±5% of 150 = 142.50–157.50 | accepted |
| AAPL 142.00 | same | `COLLAR_BREACH` — price 14200 ticks is outside [14250, 15750] |
| MSFT 300.00 | L1, ±30% of 420 = 294–546 | accepted |
| MSFT 290.00 | same | `COLLAR_BREACH` — outside [29399, 54600] |
| TSLA 240.00 | L2 (default), ±5% of 250 = 237.50–262.50 | accepted |
| TSLA 237.00 | same | `COLLAR_BREACH` — outside [23750, 26250] |

MSFT's 290.00 would have been rejected under L2 as well, and AAPL's 142.00 would
have passed under L1: the level is the whole difference. An inline `collar:` on
a symbol still overrides its level field by field, which is how `TSLA` in
[The Configuration Workflow](../operator-guide/part-2-configure/010-the-configuration-workflow.md#risk-controls-and-collars)
sets only a tighter `dynamic_band_pct`.

Three of the six orders were accepted and are still resting. Remove them
before the next chapter, so they do not sit in the books as stale prices:

```
[GW_ADMIN|ADMIN]> KILL|GW=TRADER01
```

:material-checkbox-blank-outline: **Checkpoint:** you predicted all six results
before sending the orders, and can say which symbols the single line
`default_level: L2` governs.

 

## Risk Control Summary

| Control | Scope | Trigger | Effect |
|---------|-------|---------|--------|
| Static collar | Per symbol (inline or via a named level) | Order price vs reference | Order rejected |
| Dynamic collar | Per symbol | Order price vs last trade | Order rejected |
| Circuit breaker | Per symbol | Price move vs. average of recent trades | Symbol halted, then reopened by auction |
| Symbol halt | Per symbol | `pm-admin` / `pm-admin-cli` | Trading paused |
| Exchange halt | All symbols | `pm-admin` / `pm-admin-cli` | All trading paused |
| Kill switch | Per gateway | `pm-admin` / `pm-admin-cli` | All orders cancelled |

## Starting over

Stop every EduMatcher process before resetting data. The clear command only
warns when it detects running `pm-*` processes; it does not block deletion,
and `--yes` bypasses the confirmation prompt. Live processes may recreate or
write files during or immediately after a reset.

| Reset | Command/effect | Preserved |
|---|---|---|
| Reset only remembered reference/last-trade prices | Stop `pm-engine`, remove `$EDUMATCHER_DATA_DIR/book_stats.json` (container shell: `/data/book_stats.json`), then restart the engine. | Orders, quotes, clearing/statistics history, logs, audit, and configuration. |
| Clear exchange working state | After stopping every process, run `pm-opctl-cli clear --state`. This removes `book_stats.json`, persisted GTC orders and combos, `stats.db`, `clearing.db`, and `indexes/`. Use `--yes` only when intentionally skipping the confirmation. | Configuration, audit/log data, EOD records, settlements, and backups. |
| Clear all managed data | After stopping every process, run `pm-opctl-cli clear --all`. This removes all `--state` data plus the audit trail/index, log database/fallback logs, monitor metrics, operator process tracking, and EOD database/settlement/backup data. | Deployed configuration under `ref_data/` and `emo-config.yaml`. |

Neither clear mode removes the deployed configuration or requires redeployment;
restart the processes after clearing and they will load the existing deployed
configuration. `--all` permanently deletes EOD balances and settlement
records, so use it only when those records are intentionally disposable. For a
fresh exchange with money records retained, use `--state`.

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

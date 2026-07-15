# AI Traders & Swarm

## Objective

Launch AI-driven autonomous traders to generate realistic order flow for
demonstrations, classroom sessions, and stress testing.

 

## Prerequisites

- Chapters 01–13 completed.
- Baseline liquidity available (manual MM gateways or `pm-mm-bot`).

 

## Background

EduMatcher ships with AI trader bots that simulate real market participants:

- **pm-ai-trader** — a single autonomous trader with configurable personality.
- **pm-ai-swarm** — launches multiple AI traders simultaneously, distributing
  profiles and symbols round-robin.

Bots submit only `LIMIT DAY` orders derived from the current book — they never
send `MARKET`, `FOK`, or `IOC` orders.

Four built-in personality profiles create diverse order flow:

| Profile | Decision interval | Order size | Cross probability | Character |
|---------|--------------------|------------|--------------------|-----------|
| `aggressive` | 250 ms | 20–120 | 35% | Frequent trader; crosses the spread often |
| `cautious` | 900 ms | 10–60 | 5% | Slow, patient; rarely crosses; small passive orders |
| `many-small` | 180 ms | 1–25 | 18% | High-frequency tiny orders |
| `few-large` | 1400 ms | 150–700 | 12% | Infrequent institutional-style block orders |

 

## Exercise 1: Add AI Trader Gateways

`pm-ai-swarm` generates gateway IDs as `<prefix><NN>` (default prefix `AI`,
so `AI01`, `AI02`, `AI03`, ...). Add matching entries to `engine_config.yaml`
so the bots can authenticate:

```yaml
    - id: AI01
      description: "AI bot 1"
      role: TRADER
    - id: AI02
      description: "AI bot 2"
      role: TRADER
    - id: AI03
      description: "AI bot 3"
      role: TRADER
```

!!! tip "Unrestricted mode"
    If your engine is started with no `engine_config.yaml` gateway restrictions,
    any gateway ID can connect — this step can be skipped for a quick demo.

Restart the engine.

:material-checkbox-blank-outline: **Checkpoint:** 3 additional gateways loaded (`AI01`–`AI03`).

 

## Exercise 2: Launch a Single AI Trader

```bash
pm-ai-trader --id AI01 --profile aggressive --symbols AAPL
```

Watch the gateway output — you'll see orders being submitted at the profile's
`decision_interval_ms` cadence (250 ms for `aggressive`).

:material-checkbox-blank-outline: **Checkpoint:** AI trader generates order flow on AAPL.

 

## Exercise 3: Launch the AI Swarm

Launch multiple traders across all configured symbols with one command:

```bash
pm-ai-swarm --count 3 --config engine_config.yaml --duration 60
```

This spawns `AI01`, `AI02`, `AI03`, cycling through all four profiles and
symbols round-robin. Or launch bots manually with matching IDs:

```bash
pm-ai-trader --id AI01 --profile aggressive --symbols AAPL &
pm-ai-trader --id AI02 --profile cautious --symbols MSFT &
pm-ai-trader --id AI03 --profile many-small --symbols TSLA &
```

:material-checkbox-blank-outline: **Checkpoint:** multiple AI traders running; books active.

 

## Exercise 4: Observe Market Dynamics

With MMs and AI traders running, the exchange simulates a realistic market.
From your trader gateway:

```
TRADER01> BOOK|SYM=AAPL
```

Run it repeatedly — you'll see the book evolving as AI traders interact with
the MMs.

:material-checkbox-blank-outline: **Checkpoint:** dynamic order book with changing prices.

 

## Exercise 5: Trade Against AI Flow

With AI traders providing diverse order flow, practice manual trading:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=149.90|TIF=DAY
```

Your order interacts naturally with both MM quotes and AI trader orders.

:material-checkbox-blank-outline: **Checkpoint:** successful trades against AI-generated liquidity.

 

## Exercise 6: Stop the AI Swarm

Ctrl+C on the swarm process (this forwards `SIGINT` to every child bot; each
bot cancels its pending orders and disconnects cleanly). A second Ctrl+C
force-kills immediately if a bot hangs. Your baseline liquidity providers
(manual MM gateways or `pm-mm-bot`) continue running.

:material-checkbox-blank-outline: **Checkpoint:** clean shutdown; books return to MM-only state.

 

## Classroom Tips

- Run 3–5 AI traders for realistic order flow without overwhelming the book.
- Mix profiles (`--profiles aggressive,cautious`) for diverse market dynamics.
- Use `--seed` for reproducible order sequences across repeated classroom runs.
- Combine with circuit breakers to demonstrate halt/resume under stress.

 

## Reflection

Why does `aggressive` generate more executions per minute than `few-large`,
even though both can trade the same symbol? What would happen to book depth
if you launched only `aggressive` bots with no market maker running?

 

## Further Reading

- [AI Traders](../user-guide/110-ai-traders.md)
- [Market-Maker Bot (pm-mm-bot)](../user-guide/100-mm-bot.md) — sibling automation tool for liquidity provision
- [Developer AI Bot Traders](../developer/02-ai-bot.md)
- [Risk Controls](../user-guide/120-risk-controls.md)
- [Order Book Deep Dive](../concepts/02-concepts-order-book-deep-dive.md)

 

**Next:** [15 — Statistics & Reporting](15-statistics-reporting.md)

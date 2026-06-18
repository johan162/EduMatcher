# 14 — AI Traders & Swarm

## Objective

Launch AI-driven autonomous traders to generate realistic order flow for
demonstrations, classroom sessions, and stress testing.

---

## Background

EduMatcher ships with AI trader bots that simulate real market participants:

- **pm-ai-trader** — a single autonomous trader with configurable personality.
- **pm-ai-swarm** — launches multiple AI traders simultaneously.

Four personality profiles create diverse order flow:

| Profile | Behaviour |
|---------|-----------|
| `frequent-small` | Many small orders, short hold times |
| `infrequent-large` | Few large orders, longer hold |
| `trend-follower` | Buys into rises, sells into drops |
| `mean-reverter` | Buys dips, sells rallies |

---

## Exercise 1: Add AI Trader Gateways

Extend `engine_config.yaml`:

```yaml
    - id: AI_TRADER_01
      description: "AI bot — frequent small"
      role: TRADER
    - id: AI_TRADER_02
      description: "AI bot — trend follower"
      role: TRADER
    - id: AI_TRADER_03
      description: "AI bot — mean reverter"
      role: TRADER
```

Restart the engine.

:material-checkbox-blank-outline: **Checkpoint:** 3 additional gateways loaded.

---

## Exercise 2: Launch a Single AI Trader

```bash
pm-ai-trader --id AI_TRADER_01 --symbol AAPL --personality frequent-small
```

Watch the gateway output or verbose mode (`-v`) — you'll see orders being
submitted every few seconds.

:material-checkbox-blank-outline: **Checkpoint:** AI trader generates order flow on AAPL.

---

## Exercise 3: Launch the AI Swarm

Launch multiple traders across all symbols:

```bash
pm-ai-swarm --config engine_config.yaml
```

Or manually specify:

```bash
pm-ai-trader --id AI_TRADER_01 --symbol AAPL --personality frequent-small &
pm-ai-trader --id AI_TRADER_02 --symbol MSFT --personality trend-follower &
pm-ai-trader --id AI_TRADER_03 --symbol TSLA --personality mean-reverter &
```

:material-checkbox-blank-outline: **Checkpoint:** multiple AI traders running; books active.

---

## Exercise 4: Observe Market Dynamics

With MMs and AI traders running, the exchange simulates a realistic market.
From your trader gateway:

```
TRADER01> BOOK|SYM=AAPL
```

Run it repeatedly — you'll see the book evolving as AI traders interact with
the MMs.

:material-checkbox-blank-outline: **Checkpoint:** dynamic order book with changing prices.

---

## Exercise 5: Trade Against AI Flow

With AI traders providing diverse order flow, practice manual trading:

```
TRADER01> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=149.90|TIF=DAY
```

Your order interacts naturally with both MM quotes and AI trader orders.

:material-checkbox-blank-outline: **Checkpoint:** successful trades against AI-generated liquidity.

---

## Exercise 6: Stop the AI Swarm

Ctrl+C on the swarm process, or kill individual traders. The MM bots continue
providing base liquidity.

:material-checkbox-blank-outline: **Checkpoint:** clean shutdown; books return to MM-only state.

---

## Classroom Tips

- Run 3–5 AI traders for realistic order flow without overwhelming the book.
- Mix personalities for diverse market dynamics.
- Use `--verbose` to show students what the AI is "thinking".
- Combine with circuit breakers to demonstrate halt/resume under stress.

---

**Next:** [15 — Statistics & Reporting](15-statistics-reporting.md)

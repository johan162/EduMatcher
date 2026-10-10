# Running the AI-Trader Swarm

<a id="pm-ai-swarm-runbook"></a>

!!! note "Learning objectives"
    After reading this page you will be able to:

    - Start, size and stop a swarm of AI traders for a class or a load test
    - Read its logs and its daily summaries
    - Recognise what happens when a worker, `pm-alf-gwy` or the engine goes down,
      and what (if anything) you have to do
    - Run a compressed multi-day soak

    **Prerequisites**: [Running the Exchange](010-running-the-exchange.md),
    [ALF Gateway](../part-5-gateways/010-alf-gateway.md),
    [Session Scheduling](../part-4-run-a-market/030-sessions-and-scheduling.md).

## What runs

`pm-ai-swarm` is a supervisor. It splits the agents into *K* contiguous ID
blocks and runs each block in one worker process. A worker hosts its agents in
one event loop:

- **Orders** go through `pm-alf-gwy`, one ALF session per agent, logged on as
  the agent's own participant ID (`AI001`, `AI002`, …). The gateway converts
  prices, heartbeats the engine for the session and applies the participant's
  `disconnect_behaviour` when the session ends.
- **Market data** comes straight from the engine's PUB socket, one subscription
  per worker shared by its agents.

Every agent is a *preset* — strategy × execution style × tempo × risk limits —
and the swarm's *composition* says how many agents get which preset. `pm-ai-trader`
runs one agent on its own.

```text
pm-ai-swarm (supervisor)
 ├─ worker w1  AI001–AI167 ─┐ 167 ALF sessions ─┐
 ├─ worker w2  AI168–AI334 ─┤                   ├─> pm-alf-gwy ─> pm-engine
 └─ worker w3  AI335–AI500 ─┘ engine PUB (market data) <───────────────┘
```

## Before you start

1. The deployed configuration must list every agent as a participant with role
   `TRADER`. The `s150-*` examples register `AI001`–`AI020`, `s300-load`
   registers `AI001`–`AI500`. The swarm checks this before it starts.
2. `pm-engine`, `pm-scheduler` (if sessions are enabled) and `pm-alf-gwy` are
   running. `pm-alf-gwy` accepts up to `max_connections` sessions (default
   1024).

## Starting it

Each example that has AI participants ships a `swarm.yaml` next to its
`engine_config.yaml`:

```bash
pm-ai-swarm --swarm docs/examples/ref_data/s150-nominal-setup/swarm.yaml
pm-ai-swarm --swarm docs/examples/ref_data/s300-load-setup/swarm.yaml
```

Flags given on the command line win over the file, the file over the built-in
defaults, so one file serves several runs:

```bash
pm-ai-swarm --swarm swarm.yaml --count 100 --budget 200 -v
```

Under `pm-opctl-cli`, the `ai-swarm` profile is `mm-demo` with its market
maker anchored to the true values (`pm-mm-bot --anchor-sim 0.3`), plus
[`pm-market-sim`](../part-4-run-a-market/090-market-model.md) and
`pm-ai-swarm --count 20 --budget 40 --symbols-per-agent 1000`.

!!! warning "Anchor the market maker"
    A passive `pm-mm-bot` without `--anchor-sim` refills its quotes around
    its own mid. Informed AI traders cannot move such a price: in a test run
    the market drifted 2–4 % from the true values within minutes, against
    under 1 % with `--anchor-sim 0.3`.

### `swarm.yaml`

| Key | Default | Meaning |
|---|---|---|
| `version` | — | Must be `1` |
| `agents.prefix` / `start` / `count` | `AI` / `1` / `10` | Agent IDs `AI001`… (three digits, at most 999) |
| `workers` | `0` | Worker processes; `0` = `min(cpus − 1, ceil(count / 100))` |
| `budget` | `0` | Order actions per second for the whole swarm (new orders and cancels); `0` lets the presets' own tempo decide |
| `seed` | `1000` | Agent *i* gets `seed + i`: the same file gives the same agents |
| `duration` | `0` | Seconds to run; `0` = until stopped |
| `composition` | every built-in preset, equal weights | `preset: weight`. A key is a built-in preset name or a preset YAML file relative to `swarm.yaml`. Weights can sum to anything; the counts are rounded to add up to `count` exactly and interleaved so every worker gets the same mix |
| `symbols.include` | every deployed symbol | The swarm's universe |
| `symbols.exclude` | none | Taken out of the universe |
| `symbols.per_agent` | just enough to cover the universe | Consecutive symbols each agent trades; raised if needed so every symbol is traded |
| `alf.host` / `alf.port` | `EDUMATCHER_ENGINE_HOST` / deployed `alf_gateway.port` | Where `pm-alf-gwy` listens |
| `logging.level` / `target` / `file` / `failover_timeout` | as other `pm-*` processes | Logging of supervisor and workers |

Unknown keys and bad values are refused before anything starts, with the key
named.

### Sizing

- **Throughput is bounded by the presets' risk limits**, not only by the
  budget. A passive agent holds at most `max_live_orders_per_symbol` orders per
  symbol, so it needs several symbols to stay busy. The `s300-load` file gives
  every agent 10 symbols (`per_agent: 10`) and reaches its 1 000 actions per
  second about a minute after the open; with one symbol per agent the same
  swarm managed about 130.
- **Spread the kinds of trader over every symbol.** With the default, each
  symbol is traded by about one agent, so a symbol whose only agent is a
  noise trader never finds its value nor reacts to news. The `s150-*` files
  give all twenty agents all 150 symbols (`per_agent: 150`); the `s300-load`
  file's `per_agent: 10` gives each symbol about seventeen.
- The budget controller learns how many actions a decision produces and
  corrects every 10 seconds, so the first minute runs below budget.
- Measured with `s300-load` at 1 000 actions per second: each of the three
  workers (167 agents) about 13% of a core, `pm-alf-gwy` about 45%, the engine
  about 65%.

## Logs and daily summaries

At `INFO` (`-v`) the swarm logs, per worker: one status line a minute, each
session change, and one line per trading day:

```text
[w1-AI001-AI167] t=120s session=CONTINUOUS actions=34737 (289.4/s) live_orders=2466 fills=22462 rejects=1
[w1-AI001-AI167] day 3 closed: 167 agents, 9120 orders, 5021 fills, 2 rejects, P&L 1532.40
```

Five seconds after each close (so the closing auction's fills are in), every
worker appends one JSON line per agent to
`<DATA_DIR>/ai_swarm/<date>-<worker>.jsonl`:

```json
{"closed_at": "2026-12-08T16:05:05+00:00", "day": 2, "agent": "AI001",
 "preset": "noise-retail", "submitted": 41, "fills": 12, "filled_qty": 97,
 "cancels": 9, "rejected": 0, "killed": 0, "unseen_expiries": 0,
 "gtc_orders": 0, "gross_position": 37, "pnl_realized": -1.52, "pnl_mtm": 0.83}
```

The counters are for that day. `unseen_expiries` counts DAY/ATO/ATC orders the
agent dropped at the close without having seen their expiry. P&L is the
agent's position ledger since it started (or last re-read its positions after
a reconnect), marked at the last trade. `day` counts the closes the worker has
seen since it started.

Per-order rejects are logged at `DEBUG` only.

## When something goes down

| What fails | What you see | What happens | You do |
|---|---|---|---|
| A worker process | `worker exited (code …); restarting in N s` | Only that worker restarts (back-off 1 s doubling to 60 s); its agents log on again and re-read their positions | Nothing. After 10 restarts in an hour the supervisor gives up on that worker (`giving up on its N agents`) and, when stopped, exits 1 |
| `pm-alf-gwy` | `ALF session lost` per agent, then `ALF session restored` | Agents retry with jittered back-off (at most 10 s apart). The engine keeps a dead gateway's IDs for about 15 s, so they come back 15–25 s after the gateway does | Restart `pm-alf-gwy` |
| The engine | `SESSION_LOST The exchange engine restarted` per agent | `pm-alf-gwy` closes every session; agents log on again, the worker re-reads the market. The engine restarts flat: positions start from zero, GTC orders are restored | Restart `pm-scheduler` if it happened during the trading day: a running scheduler does not notice the engine is back `CLOSED` and the market stays closed until the next day. A restarted scheduler catches up to the current phase |

## Stopping

`SIGTERM` or `Ctrl-C` stops every worker; each closes its ALF sessions, which
applies the participants' `disconnect_behaviour` (`CANCEL_ALL` for the example
AI participants). Workers get 10 seconds before they are killed.

## Compressed soak

`pm-scheduler --daily --speed F` runs the trading calendar F times faster
(see [Compressed mode](../part-4-run-a-market/030-sessions-and-scheduling.md#compressed-mode)).
At `--speed 1200` a trading day takes about a minute of wall time, so 30
trading days — weekends and holidays included — pass in under an hour:

```bash
pm-scheduler --daily --speed 1200 --start 2026-12-07T08:55 -v
pm-ai-swarm --swarm docs/examples/ref_data/s150-nominal-setup/swarm.yaml -v
```

Only the calendar is compressed. Order ages, heartbeats and decision rates run
on the wall clock, so a compressed day is a short day, not a fast one.

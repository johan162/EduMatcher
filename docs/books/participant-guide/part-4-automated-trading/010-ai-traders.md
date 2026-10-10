# AI Traders

<a id="pm-ai-trader-autonomous-trader-bot"></a>
<a id="pm-ai-swarm-multi-agent-trading-swarm"></a>

!!! note "Learning objectives"
    After reading this page you will understand:

    - What `pm-ai-trader` and `pm-ai-swarm` are and how they reach the exchange
    - What a *preset* is, and which built-in presets there are
    - How to run one AI trader, a swarm of them, and your own preset
    - Which traders need the market model (`pm-market-sim`) and why

    **Prerequisites**: [Running the Exchange](../../operator-guide/part-3-run/010-running-the-exchange.md),
    [ALF Gateway](../../operator-guide/part-5-gateways/010-alf-gateway.md) — AI
    traders log on through `pm-alf-gwy` like any ALF client, so their IDs must
    be participants in the deployed configuration.

---

## What are the AI trader processes?

| Process | Purpose |
|---|---|
| `pm-ai-trader` | One AI trader, logged on as one participant |
| `pm-ai-swarm` | Many AI traders — tens to hundreds — in a few worker processes, each trader logged on as its own participant |

An AI trader is a participant like a student desk. It logs on to
`pm-alf-gwy` with its own ID (`AI001`, `AI002`, …, role `TRADER`), sends its
orders over that ALF session, and reads market data from the engine's public
feed. Everything it does is visible to everyone else exactly as a person's
orders are: in the books, the trades, the audit trail. When its session ends,
the participant's `disconnect_behaviour` applies (`CANCEL_ALL` for the
example AI participants).

The `s150-*` examples register `AI001`–`AI020`, the `s300-load` example
`AI001`–`AI500`; both ship a `swarm.yaml` and a `market_sim.yaml`.

---

## Presets

What a trader does is set by its *preset*, four parts:

| Part | Decides | Choices |
|---|---|---|
| **Strategy** | *What* it wants to trade, which way, how urgently | `noise`, `trend`, `reversion`, `value`, `news` |
| **Execution** | *How* a wish becomes orders | `passive`, `marketable`, `sweep`, `iceberg`, `twap` |
| **Tempo** | How often it decides, and how big its orders are | `many-small`, `aggressive`, `cautious`, `few-large`, or your own |
| **Risk** | Position limit, live orders per symbol, order age, protective orders | per preset |

[How the AI Traders Decide](020-how-the-bots-decide.md) explains each in
detail. The built-in presets (`pm-ai-trader --list-presets`):

| Preset | Strategy | Execution | Tempo | Protection | Character |
|---|---|---|---|---|---|
| `noise-retail` | noise | passive | many-small | — | Uninformed retail flow: small random orders resting near the touch |
| `market-taker` | noise | sweep (MARKET) | cautious | — | Impatient noise trader that takes liquidity |
| `iceberg-seller` | noise | iceberg | few-large | — | Large orders showing a fifth of their size |
| `scalper` | trend | sweep (IOC) | aggressive | trailing stop | Fast momentum trader |
| `trend-follower` | trend | marketable | cautious | stop | Follows momentum with marketable limits |
| `block-taker` | trend | sweep (FOK) | few-large | stop-limit | Takes whole blocks or nothing |
| `contrarian` | reversion | passive (GTC) | cautious | bracket (OCO) | Fades moves patiently |
| `auction-player` | reversion | passive | cautious | — | Trades mostly in the opening and closing auctions (ATO/ATC) |
| `value-investor` | value | passive | cautious | — | Buys below its view of the true value, sells above |
| `institutional` | value | twap | few-large | — | Large parent orders toward the value, worked in slices over minutes |
| `news-trader` | news | marketable | aggressive | — | Trades headlines within seconds, in their direction |

Between them the presets send every order type and time in force the
exchange has: LIMIT, MARKET, IOC, FOK, ICEBERG, STOP, STOP_LIMIT,
TRAILING_STOP, OCO; DAY, GTC, ATO, ATC.

### Value and news need the market model

The `value` and `news` strategies trade on what
[`pm-market-sim`](../../operator-guide/part-4-run-a-market/090-market-model.md)
publishes: a hidden *true value* per symbol, and news. Without it running,
`value-investor`, `institutional` and `news-trader` stand idle — they log on
but send nothing. The true values never reach students: only the AI traders,
`pm-mm-bot --anchor-sim` and ADMIN keys see them. The headlines are public.

---

## Running one AI trader

```bash
pm-ai-trader --id AI001 --preset noise-retail --symbols AAPL,MSFT -v
```

| Flag | Default | Meaning |
|---|---|---|
| `--id` | — | Participant ID to log on as |
| `--preset` / `--preset-file` | `noise-retail` | A built-in preset, or your own preset YAML |
| `--list-presets` | — | Print the built-in presets and exit |
| `--symbols` | every symbol | Comma-separated symbols to trade |
| `--seed` | `1` | Same seed, same decisions given the same market |
| `--alf-host` / `--alf-port` | engine host / deployed `alf_gateway.port` | Where `pm-alf-gwy` listens |
| `--duration` | `0` | Seconds to run; `0` = until Ctrl+C |
| `-v` | off | Log a status line a minute and every session change |

Stop it with Ctrl+C: it closes its session, and its orders are cancelled.

---

## Running a swarm

```bash
pm-ai-swarm --swarm docs/examples/ref_data/s150-nominal-setup/swarm.yaml -v
```

`swarm.yaml` says how many traders, which presets in what mix, which symbols,
and how many order actions a second the whole swarm may send:

```yaml
version: 1
agents: {prefix: AI, start: 1, count: 20}
budget: 40            # order actions per second, whole swarm
seed: 1000            # agent i gets seed + i
symbols:
  per_agent: 150      # every agent trades every symbol
composition:          # preset: weight
  noise-retail: 25
  value-investor: 22
  news-trader: 5
  institutional: 8
  scalper: 8
  trend-follower: 10
  contrarian: 10
  iceberg-seller: 4
  market-taker: 4
  block-taker: 2
  auction-player: 2
```

Command-line flags override the file (`--count`, `--budget`, `--workers`,
`--presets noise-retail:3,scalper:1`, `--symbols-per-agent`, `--duration`).
The operator's [swarm runbook](../../operator-guide/part-3-run/030-ai-trader-swarm.md)
has every key, how to size a swarm, the logs, the daily summaries and what
happens when a process goes down.

---

## Your own preset

Copy a built-in preset and change it. A preset file names its four parts:

```yaml
name: nervous-scalper
description: A scalper with a tight trailing stop and small positions.
strategy: {name: trend, strength: 0.9, sample: 4, urgency: 0.9}
execution: {style: sweep, sweep_type: IOC, cross_ticks: 1}
tempo: {decisions_per_min: 30, size_min: 10, size_max: 50}
risk: {max_position: 200, max_live_orders_per_symbol: 2, max_order_age_sec: 15,
       protection: trailing, protection_pct: 0.005}
```

```bash
pm-ai-trader --id AI001 --preset-file nervous-scalper.yaml -v
```

In a `swarm.yaml`, a composition key that ends in `.yaml` is a preset file,
relative to the `swarm.yaml`. Unknown keys and out-of-range values are
refused before anything starts, naming the file and the key.

---

## Reading its output

With `-v`, each trader (or each swarm worker, for its traders together) logs
one line a minute:

```text
[AI001] t=120s session=CONTINUOUS actions=96 (0.8/s) live_orders=2 fills=31 rejects=0
```

`actions` counts new orders and cancels. A trader whose orders keep being
refused pauses itself for a few seconds (the *reject breaker*); a cancel that
lost the race with a fill, or an order in flight when the market closed, does
not count. After each close the swarm writes a summary per trader — orders,
fills, position, P&L — see the runbook.

---

## See also

- [How the AI Traders Decide](020-how-the-bots-decide.md) — strategies, execution styles, tempo and risk in detail
- [Running the AI-Trader Swarm](../../operator-guide/part-3-run/030-ai-trader-swarm.md) — the operator's runbook
- [The Market Model (`pm-market-sim`)](../../operator-guide/part-4-run-a-market/090-market-model.md) — true values and news
- [The Market-Maker Bot (`pm-mm-bot`)](../part-3-market-making/030-the-market-maker-bot.md) — liquidity for the AI traders to trade against
- [Order Types](../part-2-orders/020-order-types.md)
- [AI Traders & News](../../training-guide/140-ai-traders.md) — classroom exercises

# The Market Model (`pm-market-sim`)

<a id="pm-market-sim-market-model"></a>

!!! note "Learning objectives"
    After reading this page you will be able to:

    - Explain what the *true value* of a symbol is and who gets to see it
    - Write or generate a `market_sim.yaml` and deploy it with the engine configuration
    - Run `pm-market-sim`, check on it, and anchor a market maker to it
    - Tell how a compressed trading day relates to a real one
    - Publish news with `pm-news`, by hand or from a scenario

    **Prerequisites**: [Session Scheduling](030-sessions-and-scheduling.md),
    [Running the AI-Trader Swarm](../part-3-run/030-ai-trader-swarm.md).

## What it does

Prices on the exchange are whatever the participants agree on. `pm-market-sim`
adds what a real market has behind its prices: a *true value* for every
symbol, moving the way company values move — together with the market, with
the sector, on its own, and now and then in a jump. Bots that trade on value
pull prices toward it; noise and momentum traders push them away; the gap is
what students can learn to read.

The values are for the bots and the instructor only. They travel on
`pm-market-sim`'s own sockets (loopback by default), never on the engine bus
that students' clients reach, and the API gateway serves them to ADMIN keys
only.

| Who | Uses the value for |
|---|---|
| AI traders with the `value` strategy (presets `value-investor`, `institutional`) | Buy below their view of the value, sell above it |
| `pm-mm-bot --anchor-sim W` | Move its quoted mid a share `W` of the way toward the value |
| ADMIN API keys | `GET /api/v1/admin/sim`, WebSocket `/api/v1/admin/sim` |
| `pm-market-sim --status --id OPS01` | Where the market is furthest from the value |

The model also publishes *news*: headlines that move the values (see
[News](#news)). Headlines are public — every API key, `pm-ticker` and both
GUIs show them; what a headline does to the value is not.

## The model

For each symbol, one step of trading time Δ (in days) moves the log value by

```text
(μ − ½σ²u)Δ + σ√(uΔ) · (β_m·Z_market + β_s·Z_sector + √(1 − β_m² − β_s²)·Z_symbol) + jumps
```

- σ and μ are annual (252 trading days); `u` is an intraday multiplier, high
  after the open and before the close, low at midday, averaging 1.
- `β_m` and `β_s` load each symbol on a market factor and its sector's factor,
  so symbols of one sector move together: two of them correlate by about
  `β_m² + β_s²`.
- Jumps arrive at `jump_rate` per day with normally distributed log size.
- When the exchange reopens after a close, one extra move with
  `overnight_fraction` of a day's variance is applied.

The model steps only during continuous trading. A day's variance accrues over
the continuous phase *as the engine reports it* — from its start to the
scheduler's countdown to the close — so a day compressed with
`pm-scheduler --speed` moves as much as a real one. Without a countdown (no
scheduler, or `pm-scheduler --now`) a 6.5-hour day is assumed.

Every source of randomness is its own stream seeded from the model seed, so a
run is reproducible and adding a symbol does not change the others' paths.

## `market_sim.yaml`

```yaml
version: 1
seed: 150
step_sec: 1.0              # seconds between steps
overnight_fraction: 0.2
defaults: {vol: 0.30, drift: 0.05, jump_rate: 0.05, jump_mean: 0.0,
           jump_std: 0.04, beta_market: 0.5, beta_sector: 0.4}
sectors:
  TECH: {vol: 0.35, beta_market: 0.6, beta_sector: 0.45}
symbols:
  AAPL: {sector: TECH, vol: 0.28}
  NVDA: {sector: TECH, vol: 0.45, initial: 120.0}
```

A symbol's parameters are the defaults, overridden by its sector's, overridden
by its own entry. A symbol of the engine configuration that the file does not
list gets the defaults (sector `OTHER`); a symbol the engine does not list is
an error. A symbol starts at its `initial`, or else at the engine's previous
close, or else at the configuration's last price.

`pm-market-sim --init` writes a file for the deployed symbols, each in its
sector (the usual industry sectors for the bundled tickers) with that
sector's betas and a volatility spread around the sector's. The `s150-*` and
`s300-load` examples ship one.

Keep the file next to the `engine_config.yaml` you deploy: `pm-config-deploy`
checks it against the engine's symbols and installs it beside the compiled
configuration; deploying a configuration without one removes the old one.

```bash
pm-market-sim --init --seed 7 > my-course/market_sim.yaml
pm-config-deploy my-course/engine_config.yaml
```

## Running it

```bash
pm-market-sim -v
```

It follows the engine's session (asking for it at startup and after an engine
restart), publishes `sim.value` once per `step_sec` during continuous trading
and a `sim.state` heartbeat every second (`RUNNING` or `PAUSED`). It saves its
values to `<DATA_DIR>/market_sim_state.json` every ten seconds and on exit, so
a restart continues from where the model stood.

| Socket | Port | Carries |
|---|---|---|
| PUB | `5553` (`EDUMATCHER_SIM_PUB_PORT`) | `sim.value`, `sim.state`, `news.event`, `sim.command_ack.<ID>` |
| PULL | `5554` (`EDUMATCHER_SIM_PULL_PORT`) | `sim.command` from ADMIN participants |

Both bind to `EDUMATCHER_SIM_BIND_HOST` (default `127.0.0.1`).

`pm-market-sim --status --id OPS01` asks the running process where it stands
and lists the symbols whose market mid is furthest from the value:

```text
pm-market-sim: RUNNING seq=4120 symbols=150
symbol        value        mid  mid/value
TSLA         212.40     219.95     +3.55%
...
```

## Anchoring a market maker

`pm-mm-bot --anchor-sim 0.3` moves the bot's mid 30% of the remaining way to
the true value at every model step (once a second), and from the first value
on the book no longer sets its mid: its quotes converge on the value within a
few seconds. With `0` (the default) the bot ignores the model and quotes
around the book. A market maker anchored this way is a strong pull
toward the value; leave it off to let the value traders do the work.

## News

<a id="pm-news"></a>

A headline has a *scope* — one or more symbols, one or more sectors, or the
whole market — a *kind* (`EARNINGS`, `GUIDANCE`, `MNA`, `REGULATORY`,
`PRODUCT`, `LEGAL`, `MANAGEMENT`, `MACRO`), a public *sentiment* from −1 (bad)
to 1 (good), and a secret *impact*: the log move of the true value (0.10 is
about +10.5%). A sector headline moves each of its symbols by `β_s` times the
impact, a market headline every symbol by `β_m` times it.

A headline can start as a **rumour**. A rumour carries a *credibility* (0 to
1) and moves nothing; it is later **confirmed** — a second headline, and the
value moves then — or **retracted**, and nothing ever moves. Prices may well
move on a rumour anyway: that is traders betting on it.

| Who | Reads the news through |
|---|---|
| AI traders with the `news` strategy (preset `news-trader`) | Trade the headline within seconds, in its direction, harder the stronger the sentiment |
| AI traders with the `value` strategy | Shift their view of the value on a rumour, by sentiment × credibility |
| Every API key | `GET /api/v1/news`, and the `news` channel of the market-data WebSocket |
| `pm-ticker`, the trading GUI, TapeDeck | A news line, a News screen, a News view |

### Generated news

Without anyone doing anything, `pm-market-sim` publishes news at random during
continuous trading: on average 6 symbol, 0.5 sector and 0.3 market headlines
per trading day across the whole exchange. 30% start as rumours, which resolve
on their own 0.02 to 0.15 trading days later — confirmed 60% of the time; a
rumour that will be confirmed tends to carry a higher credibility. Tune it in
`market_sim.yaml`; a rate of 0 turns that scope off:

```yaml
news:
  rate_symbol: 6.0
  rate_sector: 0.5
  rate_market: 0.3
  rumour_share: 0.3
  rumour_confirm: 0.6
  rumour_delay_min: 0.02   # trading days
  rumour_delay_max: 0.15
```

### Publishing news yourself: `pm-news`

`pm-news` sends commands to the running `pm-market-sim` as an ADMIN
participant (`--id`) and prints what happened:

```bash
pm-news --id OPS01 inject --symbol AAPL --kind EARNINGS --sentiment 0.8 --impact 0.08
pm-news --id OPS01 inject --sector ENERGY --kind REGULATORY --sentiment -0.7 \
    --impact -0.06 --rumour --credibility 0.6
N7
pm-news --id OPS01 confirm N7      # or: retract N7
pm-news list                       # print headlines as they are published
```

`inject` prints the new headline's id. `--headline` sets the text; without it
one is written from the kind and the sentiment. A rumour you inject waits for
your `confirm` or `retract` — it never resolves on its own. Commands from a
participant that is not ADMIN are refused.

### Scenarios

`pm-news play scenario.yaml` runs a timed script. Each step fires
`after_sec` seconds into a session phase (or into the play when `phase` is
left out); a phase already under way when the play starts counts from the
start of the play. A step either injects a headline (same fields as the
`inject` flags) or confirms or retracts an earlier step by its `name`:

```yaml
version: 1
steps:
  - at: {phase: CONTINUOUS, after_sec: 60}
    name: bid
    inject: {symbol: JPM, kind: MNA, sentiment: 0.7, impact: 0.12, rumour: true,
             credibility: 0.5, headline: "JPM said to be in talks over a takeover bid"}
  - at: {phase: CONTINUOUS, after_sec: 240}
    confirm: bid
```

Three classroom scenarios ship in `docs/examples/news/` and fit every `s150-*`
example and `s300-load`: `earnings-surprise.yaml`, `rumour-confirmed.yaml` and
`rumour-retracted.yaml`. The [AI Traders & News](../../training-guide/140-ai-traders.md)
training chapter uses them.


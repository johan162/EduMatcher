# Tuning the Traders

!!! note "Learning objectives"
    After reading this chapter you will be able to:

    - Find every setting that changes how the simulated market behaves
    - Predict what a change does — to volume, spreads, volatility and how
      closely prices follow the values — before you make it
    - Make the market calmer, wilder, better or worse informed, more or less
      news-driven, and check that the change worked

    **Prerequisites**: [The True Value](030-the-true-value.md),
    [News and Rumours](040-news-and-rumours.md),
    [How the AI Traders Decide](../../participant-guide/part-4-automated-trading/020-how-the-bots-decide.md).

## Where the settings live

The market you see is the sum of four things, each with its own file:

| Layer | Decides | File | Read by |
|---|---|---|---|
| **The model** | How the true values move; how much news there is | `market_sim.yaml` | `pm-market-sim` |
| **The swarm** | How many traders, which kinds, how busy, which symbols | `swarm.yaml` | `pm-ai-swarm` |
| **The presets** | How each kind of trader trades | preset YAML files | `pm-ai-swarm` |
| **The market maker** | How tight and deep the quotes are, how fast they follow the value | its command-line flags in the process profile | `pm-mm-bot` |

and the exchange underneath — symbols, tick sizes, trading hours, the
market maker's obligations — in `engine_config.yaml`.

How to deploy your own copy of each:

| Running | `market_sim.yaml`, `engine_config.yaml` | `swarm.yaml`, presets, market-maker flags |
|---|---|---|
| In the container | put them in `./data-sim/custom/`, start with `EM_CONFIG_FILE=/data/custom/engine_config.yaml` | `pm-opctl-cli init`, then edit `./data-sim/emo-config.yaml` |
| By hand | `pm-config-deploy my-sim/engine_config.yaml` | `pm-opctl-cli init`, then edit `$EDUMATCHER_DATA_DIR/emo-config.yaml` |

The details are in [The Simulation Container](../part-3-run-it/110-the-simulation-container.md#changing-what-it-runs)
and [A Complete Set-up by Hand](../part-3-run-it/100-a-complete-setup-by-hand.md#your-own-variant).
Every change takes effect when the process that reads it restarts; the
simplest is to restart the whole stack.

## What to watch

Before changing anything, decide what you want to move, and how you will see
it move:

| Property | What it means | How to see it |
|---|---|---|
| **Activity** | Orders and trades a second | the growth of `actions=…` between two of the swarm's once-a-minute status lines (the rate in brackets is the average since the start; see [Watching the Market](../part-4-watch-and-teach/130-watching-the-market.md#what-is-the-market-doing)): `pm-log-cli query --process pm-ai-swarm --grep actions= --limit 3`; trades in terminal-gui |
| **Spread and depth** | How tight and thick the books are | book-gui |
| **Volatility** | How far prices move in a minute, a day | terminal-gui charts; `pm-stats-cli daily` (high − low) |
| **Efficiency** | How close prices stay to the values | `pm-market-sim --status --id OPS01`; the admin API |
| **Reaction to news** | How fast and far prices follow a headline | inject one and watch ([News and Rumours](040-news-and-rumours.md#publishing-news-yourself)) |
| **Who wins** | Profit and loss per kind of trader | the daily summaries in `/data/ai_swarm/` ([Watching the Market](../part-4-watch-and-teach/130-watching-the-market.md#who-made-money)) |

## The swarm

`swarm.yaml` of the `s300-sim` example:

```yaml
version: 1
agents: {prefix: AI, start: 1, count: 100}
workers: 0
budget: 120           # order actions per second, whole swarm
seed: 1000
symbols:
  per_agent: 30       # each agent trades 30 of the 300 symbols
composition:
  noise-retail: 15
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
  patient-liquidity: 10
```

| Setting | What it does | Raise it | Lower it |
|---|---|---|---|
| `budget` | Order actions (new orders and cancels) a second for the whole swarm. The swarm scales every trader's decision rate to meet it, correcting every 10 seconds | Busier books, more trades, more CPU and disk | A quieter market; too low, and some symbols go a long time without a trade |
| `count` | How many traders. Each needs a participant `AI001`… in the engine configuration (`s300-sim` has 100) | More, smaller voices: the same budget spread thinner, more disagreement | Fewer: each trader's quirks show more |
| `symbols.per_agent` | Symbols each trader trades. Each symbol is traded by about `count × per_agent / 300` traders | More traders per symbol: every symbol gets every kind of trader, smoother prices | Fewer per symbol: some symbols get only noise traders and never find their value |
| `composition` | The mix of presets (weights; any sum) | — | — |
| `seed` | The traders' random choices; the same seed and market give the same decisions | — | — |
| `workers` | Processes the traders run in; `0` = one per hundred traders, at most the CPUs minus one | Uses more cores | — |

!!! note "The budget needs a few minutes"
    After the open the traders fire off their opening orders and the
    controller has nothing to learn from yet: in the first minutes of a day
    the swarm sends several times its budget, and settles to it within
    about four minutes. A budget is an average, not a cap.

### The composition: who the market is made of

The mix is the most powerful setting there is. In the `s300-sim` mix, 35 of
the 100 traders know something about the values or the news (22 value, 8
institutional, 5 news); 65 trade on prices alone.

| Give more weight to | And the market gets |
|---|---|
| `value-investor`, `institutional` | Prices closer to the values; quicker recovery after noise; less volatility than the values themselves |
| `news-trader` | Faster, sharper reactions to headlines — including rumours that turn out false |
| `noise-retail` | More volume and depth near the touch; prices that wander further from the values |
| `patient-liquidity` | Deeper books: more price levels behind the best prices, and moves that run into resting size |
| `trend-follower`, `scalper` | Momentum: moves run further than the value justifies, then snap back; fatter tails |
| `contrarian` | Mean reversion: moves get faded, prices stickier, short-term volatility lower |
| `market-taker`, `block-taker` | The spread crossed more often; more trades, more volatility, thinner books |
| `iceberg-seller` | Hidden size: books look thinner than they trade |
| `auction-player` | Busier opening and closing auctions |

A market of only informed traders hardly trades — they agree with each
other about the value, give or take their 1 % errors. A market of only noise
traders trades a lot and finds nothing. Real markets, and good teaching
markets, are in between.

## The presets

Each preset is a strategy, an execution style, a tempo and risk limits
([How the AI Traders Decide](../../participant-guide/part-4-automated-trading/020-how-the-bots-decide.md)
defines every parameter). To change one kind of trader, copy its preset file
from the package (`pm-ai-trader --list-presets` names them; they are in
`edumatcher/ai_trader/presets/`), change it, give it a new `name`, and put
the file's path in the composition instead of the built-in name:

```yaml
composition:
  noise-retail: 25
  my-value-investor.yaml: 22     # relative to this swarm.yaml
  # ...
```

What each lever does:

### Strategy

| Parameter | Strategies | Raise it and the trader… |
|---|---|---|
| `urgency` | all | crosses the spread more often (and sooner reaches `urgency_cross`) |
| `strength` | trend, reversion | follows its signal more consistently instead of half at random |
| `sample` | trend, reversion, value | looks at more symbols per decision and picks the strongest signal — a sharper eye, more concentrated trading |
| `threshold` | value | waits for a bigger gap before trading: fewer, larger corrections, prices further from the values |
| `bias_std` | value | is more wrong about the value: more disagreement, more trading among value traders, a noisier consensus |
| `redraw` | value | changes its mind more often |
| `rumour_shift` | value | moves its view more on a rumour |
| `lag_sec`, `lag_sigma` | news | hears news later, and more spread out from the other news traders |
| `half_life_sec` | news | keeps trading a headline longer |
| `threshold` | news | ignores weaker news |
| `move` | news | pays further beyond the pre-news price: news is priced in faster, and overshoots more |

### Execution

| Parameter | Raise it and the trader… |
|---|---|
| `offset_ticks` | rests further from the touch: more depth behind the best price, fewer fills |
| `offset_max` | spreads its resting orders over more price levels, from `offset_ticks` out to this, most of them near the touch |
| `cross_ticks` | pays further through the touch when it crosses |
| `urgency_cross` | crosses less often (it crosses when urgency reaches this) |
| `visible_fraction` (iceberg) | shows more of its order |
| `slices`, `horizon_sec` (twap) | works its order in more pieces over a longer time: less impact, slower to reach the value |
| `auction_participation` | takes part in more auction decisions |
| `tif: GTC` | leaves orders on the book overnight |
| `gtc_fraction` | sends that share of its resting orders as GTC, whatever `tif` says: a few long orders that outlive the day (a trader keeps at most one per symbol, and never cancels it as stale) |
| `amend_fraction` | amends more of its stale orders instead of cancelling them: re-priced to the touch, or trimmed when still at it |
| `combo_fraction` | sends more of its continuous decisions as two-symbol all-or-none combos |
| `smp` | (not a number) picks the self-match prevention mode on its orders |

### Tempo

`decisions_per_min` sets how often a trader decides *relative to the
others*: the swarm's budget then scales everyone's rate up or down together.
So with a budget, doubling one preset's `decisions_per_min` doubles its
share of the activity, not the total. Order size (`size_min`, `size_max`,
`size_distribution`) is not scaled: bigger orders mean more volume, more
impact per trade and more inventory.

### Risk

| Parameter | Raise it and the trader… |
|---|---|
| `max_position` | holds larger positions: informed traders can push prices further toward the value before they are full |
| `max_live_orders_per_symbol` | keeps more orders working: more depth |
| `max_order_age_sec` | leaves orders longer: more depth, staler prices |
| `stale_price_ticks` | tolerates its order further behind the touch before cancelling |
| `protection_pct` | puts its stops further away: fewer stop-outs, bigger losses when they hit |

## The market maker

`MM01` quotes every symbol: a bid and an ask 20 cents apart, 200 shares
each, centred on a price it moves toward the true value every second. Its
flags are in the `ai-sim` profile's `mm-bot` entry:

```text
pm-mm-bot --gateway-id MM01 --all-symbols --strategy symmetric --gap 0.20 --qty 200
          --reissue-delay-ms 5000 --drift-ticks 15 --anchor-sim 0.3
```

It uses the `symmetric` strategy: it quotes its own price ± half the gap and
re-quotes only when that price has moved more than `--drift-ticks`, or a few
seconds after a fill. The `passive` strategy of the `mm-demo` profile steps
behind other traders' orders instead, and re-quotes whenever those orders
change; with a hundred AI traders on 300 symbols that was 83 % of all the
order messages on the exchange and half its CPU, for the same price
quality.

| Flag | Now | Raise it | Lower it |
|---|---|---|---|
| `--anchor-sim` | 0.3 | Quotes follow the value faster: prices stick to the values, rumours barely move them | Slower to follow; `0` = ignores the values (see the warning below) |
| `--gap` | 0.20 | A wider spread to cross: noise traders pay more, value traders wait for bigger gaps. The engine's obligation for the market maker caps it at 20 ticks (0.20) | Tighter books |
| `--qty` | 200 | Deeper quotes: harder for any trader to move a price | Thinner: prices move on smaller orders |
| `--reissue-delay-ms` | 5000 | Waits longer to re-quote after a fill: gaps in the book after a fill | Refills at once: a wall at its price |
| `--drift-ticks` | 15 | Re-quotes less often as its price moves: quotes lag the value by up to this many ticks | Re-quotes more often (more messages) |

!!! warning "Anchored, or not at all"
    A market maker that ignores the values (`--anchor-sim 0`) keeps refilling
    its quotes around its own last price. Informed traders then cannot move
    the price, and the market drifts away from the values: in a test, 2–4 %
    within minutes, against under 1 % anchored, and 1.4 % with no market
    maker at all. If you want the value traders to do the work, remove the
    market maker rather than un-anchoring it.

**Removing it.** In the container a dead process comes back within a minute,
so stopping `mm-bot` is not enough: write the profiles out
(`pm-opctl-cli init`), delete the `mm-bot` entry from the `ai-sim` profile in
`emo-config.yaml`, and restart. Without it the books are the AI traders'
orders alone: thinner, and with a narrower median spread (0.03 % of the
price against 0.10 %; the traders compete for the touch instead of queueing
behind the market maker). Prices sit three times further from the values
(1.3 % against 0.44 %, measured over a day at `EM_SPEED=24`), and rumours
move prices visibly — the right market for a lesson on rumours.

## The model

The values and the news have their own chapters:
[The True Value](030-the-true-value.md#changing-the-model) and
[News and Rumours](040-news-and-rumours.md#steering-the-news). In short:
volatility and jumps decide how hard the traders have to work to keep up;
news rates decide how often the informed traders get something to trade.

## Recipes

Start from the `s300-sim` settings and change only what the recipe says.
Each was run against the default on the same machine, with the same seeds:
16 minutes of continuous trading at real speed, or, where the effect needs
a whole day (news, rumours), a day at `EM_SPEED=24`. The default for
comparison: prices 0.29 % from the values (RMS), a typical one-minute price
move of 0.42 %, 1,400 trades a minute, 290 of the 300 symbols trading in
any five minutes; at `EM_SPEED=24`, 0.44 % and 0.73 %.

| Recipe | Change | Measured, against the default |
|---|---|---|
| **Calm first lesson** | `market_sim.yaml`: every `vol` halved, `jump_rate: 0`, news rates 0; `swarm.yaml`: `budget: 30` | Prices 0.16 % from the values, one-minute moves 0.22 %: half of both. 345 trades a minute, 263 symbols in five minutes, a quarter of a core |
| **Wild market** | every `vol` × 2, `jump_rate: 0.2`; composition: `trend-follower: 20`, `scalper: 15`, `market-taker: 8` | One-minute moves 0.57 % (+35 %), 1,550 trades a minute, every symbol trading; prices still close to the values (0.35 %) |
| **Inefficient market** | composition: `value-investor: 5`, `institutional: 2`; remove the market maker | Prices 2.1 % from the values, seven times the default; 36 symbols more than 2 % off at any moment. A market for students to beat |
| **Efficient market** | composition: `value-investor: 40`, `institutional: 15`; `--anchor-sim 0.5` | No measurable change (0.32 %): the default is already about as close to the values as this market gets. Use it to show that more value traders stop helping |
| **News day** | `rate_symbol: 60`, `rate_sector: 3`; composition: `news-trader: 15` | 66 headlines in a trading day instead of 6; one-minute moves 0.85 % (+17 %); prices follow the values as closely as before (0.45 %) |
| **Rumour mill** | `rumour_share: 0.7`, `rumour_confirm: 0.5`; remove the market maker | Without the market maker alone prices sit 1.3 % from the values; the rumours add a little (1.4 %, 35 symbols more than 2 % off instead of 27). At 6 headlines a day that is four or five rumours: raise `rate_symbol` for more |
| **Auction lesson** | composition: `auction-player: 20` | Opening auction volume +60 %, and 298 of 300 symbols open with a cross instead of 243; continuous trading unchanged |
| **Thin market** | `per_agent: 5`; `--qty 50` | 38 symbols trade in a minute instead of 240, 60 in five minutes; prices 0.9 % from the values: symbols sit still, then jump |

After a change, give the market a full trading day — the budget needs a
few minutes, and each kind of trader needs its own symbols to warm up —
before you judge it.

## Measuring a change

1. Run a day with the old settings; note the RMS gap
   (`pm-market-sim --status --id OPS01` shows the extreme ones; the admin
   API all of them), typical spreads in book-gui, actions a second, and the
   day's ranges (`pm-stats-cli daily`).
2. Change one thing. Restart.
3. Run a day; compare the same numbers.

Accelerated time ([Accelerated Time](../part-3-run-it/120-accelerated-time.md))
shortens step 3, with one caveat: at high speed the traders have fewer
orders per trading day to follow the values, so compare settings at the
same speed.

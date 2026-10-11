# The True Value

!!! note "Learning objectives"
    After reading this chapter you will be able to:

    - Explain price discovery with the simulation as the example: a price
      looking for a value nobody on the exchange can see
    - Describe how the true values move, in words and in numbers
    - Say who pulls prices toward the values and who pushes them away
    - Measure how far the market is from its values, and change that
    - Read and change every setting of the market model

    **Prerequisites**: [A Market That Runs Itself](../part-1-start-here/010-a-market-that-runs-itself.md).

## Price and value

A share's **price** is the last price two traders agreed on. Its **value** is
what the share is really worth — on a real exchange, what the company's
future earnings are worth today. Nobody knows the value exactly. Some traders
have a good estimate of it and trade on the difference: they buy when the
price is below their estimate, sell when it is above. Their orders pull the
price toward the value. Everyone else — traders who follow momentum, who need
cash, who simply guess — pushes the price around. The price you see is the
outcome of that tug of war, and the process by which it finds the value is
called **price discovery**.

On a real exchange nobody can check how well price discovery works, because
the value is never revealed. In the simulation it exists: `pm-market-sim`
keeps a true value for every share and moves it the way company values move.
You, as the instructor, can see it; the students cannot; the AI traders that
trade on value see it through errors of their own. So you can watch the gap
between price and value open and close — and show it to a class after the
fact.

## How the values move

Every second of continuous trading, each share's value takes a small random
step. The step is a mix of four things:

| Ingredient | What it is | In the `s300-sim` example |
|---|---|---|
| **The market** | One random move shared by every share | each share follows it with weight `beta_market`, 0.35–0.60 by sector |
| **The sector** | One random move per industry sector | weight `beta_sector`, 0.35–0.60 |
| **The share itself** | Its own random move | the rest of its volatility |
| **Jumps** | Now and then a sudden move: an unannounced event | 0.05 a day per share, size ±4 % (σ) |

Plus a slow **drift** (5 % a year), news ([next chapter](040-news-and-rumours.md))
and an **overnight** move when the market reopens. The size of the random
steps is the share's **volatility**: 30 % a year by default, 18 % for the
calmest sectors (consumer staples, utilities), 35 % for technology and
energy, and spread a little around its sector for each share.

What that means in a day:

| | Typical size (one standard deviation) |
|---|---|
| A whole trading day, volatility 30 % | 1.9 %, about 2.1 % with the jumps |
| One hour of continuous trading | 0.7 % |
| One minute | 0.1 % |
| The overnight move (20 % of a day's variance) | 0.85 % |
| A jump (once in 20 trading days per share) | 4 % |

So on a typical day a share's value ends within about ±2 % of where it
started, one day in twenty more than ±4 %; across the 300 shares, about 15
jump somewhere every day.

**Shares move together.** Two shares in the same sector move together with a
correlation of about `beta_market² + beta_sector²` — 0.56 for two technology
shares — and two shares in different sectors with about the product of their
market betas, around 0.3. A bad day for the market is a bad day for most
shares; a bad day for energy is a bad day for all 16 energy shares.

**The day has a rhythm.** Real markets are busiest after the open and before
the close; so is the model. The values move about twice as fast (in
variance) right after the open and before the close as at midday, averaging
one day's worth over the day.

**Only during trading.** The values move only while the exchange trades
continuously — not in the auctions, not at night. The night's move arrives
in one step when the market reopens, so the opening auction has a new value
to find.

!!! note "Where the values start"
    On the first day each share's value starts at the engine's previous
    close, or, on a brand-new exchange, at the share's last price in the
    configuration — so price and value start equal. From then on
    `pm-market-sim` saves the values every 10 seconds
    (`market_sim_state.json`) and continues from them after any restart.

## Who pulls, who pushes

| Pulls the price toward the value | Pushes it away |
|---|---|
| `MM01`, the market maker: every second it moves its own price 30 % of the remaining way to the value (`--anchor-sim 0.3`) and re-quotes around it | `noise-retail`, `market-taker`, `iceberg-seller`: orders in random directions |
| 22 `value-investor`s: buy when the price is more than 0.4 % below their view of the value, sell when above | `trend-follower`s and `scalper`s: buy what rose, sell what fell — they amplify moves |
| 8 `institutional`s: the same with a 0.6 % threshold, in big orders worked over three minutes | `contrarian`s and `auction-player`s: fade moves; they pull toward the recent *price*, not the value |
| | Every value trader's own error: each sees the value through a bias of its own (about ±1 %) |

The value traders do not see the value exactly. Each one has, per share, a
persistent error drawn at random (standard deviation 1 % for value
investors, 0.8 % for institutions) and redrawn now and then. That is why two
value traders disagree about a price, and trade with each other — and why the
market as a whole has a better estimate of the value than any single trader.

## How close does the market get?

The yardstick is the gap `ln(price / value)` — for small gaps the same as
the percentage difference — across all 300 shares, summarised as its root
mean square (RMS). Measured on the `s300-sim` set-up at real speed on a
2-vCPU machine, minute by minute from the fifth to the sixteenth minute of
continuous trading:

| Measure | Value |
|---|---|
| RMS gap, all shares | about 0.3 % (0.21–0.43 % from one minute to the next) |
| Median absolute gap | about 0.04 % |
| Shares more than 2 % away | 2 of the 300 on average, never more than 5 |

In other words half the prices sit within a few hundredths of a percent of
their value, and a handful of shares — usually ones that just jumped, or a
thinly traded one — are a percent or two away; those few make up most of the
RMS. The gap is what keeps the value
traders busy: if it were zero, they would have nothing to trade.

To see the gap yourself:

```bash
docker exec edumatcher-sim pm-market-sim --status --id OPS01
```

```text
pm-market-sim: RUNNING seq=4120 symbols=300 open_rumours=0
symbol        value        mid  mid/value
LHX           62.63      65.63     +4.79%
GPN           28.51      27.61     -3.19%
...
```

It lists the shares furthest from their value. For every share, ask the API
with the instructor's key:

```bash
curl -s -H "Authorization: Bearer key-ops01-9yn0rc" http://localhost:8080/api/v1/admin/sim
```

The answer holds the model's state and the latest value of every share. The
same data streams on the WebSocket `/api/v1/admin/sim`. Only ADMIN keys get
an answer; a student's key is refused.

## Changing the model

The model's settings are in `market_sim.yaml`, deployed next to the engine
configuration (in the container `/data/ref_data/market_sim.yaml`; how to
deploy your own copy: [The Simulation Container](../part-3-run-it/110-the-simulation-container.md#your-own-configuration)
or [A Complete Set-up by Hand](../part-3-run-it/100-a-complete-setup-by-hand.md#your-own-variant)).

```yaml
version: 1
seed: 301
step_sec: 1.0
overnight_fraction: 0.2
defaults: {vol: 0.30, drift: 0.05, jump_rate: 0.05, jump_mean: 0.0,
           jump_std: 0.04, beta_market: 0.5, beta_sector: 0.4}
sectors:
  TECH: {vol: 0.35, beta_market: 0.6, beta_sector: 0.45}
  # ... ten more
symbols:
  AAPL: {sector: TECH, vol: 0.392}
  # ... 299 more
news: { ... }   # next chapter
```

A share's settings are `defaults`, overridden by its sector's, overridden by
its own line.

| Setting | Range | Raise it and | Lower it and |
|---|---|---|---|
| `vol` | 0–3 | values wander further each day; prices lag them more; value traders trade more | a calm market where prices hug the values |
| `drift` | −1–1 | values creep up (a bull market); at 0.05 it is invisible within a day | negative: a slow bear market |
| `jump_rate` | 0–10 | more sudden moves the news never announced; more large gaps | 0: values only diffuse |
| `jump_std` | 0–1 | bigger surprises | |
| `jump_mean` | −1–1 | jumps mostly up (positive) or down (negative) | |
| `beta_market` | 0–1 | shares move together; a market-wide day is visible in every book | shares independent |
| `beta_sector` | 0–1 | sectors move as blocks | |
| `overnight_fraction` | 0–5 | bigger gaps at the open; busier opening auctions | 0: the open continues the close |
| `step_sec` | 0.01–60 | coarser steps, fewer value messages | smoother values, more messages |
| `seed` | any integer ≥ 0 | a different but repeatable path | |
| `initial` (per symbol) | > 0 | start a share at a chosen value: the market finds it from its old price | |

`beta_market² + beta_sector²` must not exceed 1 for any share; the rest of
its variance is its own.

### Recipes

| You want | Change in `market_sim.yaml` |
|---|---|
| A calm market for a first lesson | `defaults: {vol: 0.15, jump_rate: 0.0}`, and the sectors' `vol` down too |
| A volatile market | every `vol` × 2, `jump_rate: 0.2` |
| A crash day | inject a market headline with impact −0.08 ([next chapter](040-news-and-rumours.md)) rather than changing the model |
| Mispriced shares to find | `initial` for a few shares, 10 % away from their last price: watch the value traders close the gap |
| Independent shares | `beta_market: 0` and `beta_sector: 0` everywhere |
| The same day again | the same `seed`, a fresh data directory |

Restart after a change: the model reads `market_sim.yaml` when it starts.
A share's values carry on from where they were; only how they move from now
on changes (except `initial`, which applies only to a share without a saved
value).

## The market maker's anchor

The strongest single force toward the value is the market maker. With
`--anchor-sim 0.3` it moves its own price 30 % of the way to the value every
second, so that price reaches a new value within a few seconds; its quotes
follow as soon as the price has moved more than 15 ticks (`--drift-ticks`). The value
traders then trade against prices that are already about right.

Without it, the value traders do all the pulling. That is a more
interesting market to watch — prices wander further, rumours move them —
but with one caveat: a market maker that is *not* anchored, and simply
re-quotes around its own last mid, is worse than none. It refills the same
prices whatever happens, and informed traders cannot move it. In a test the
gap grew from under 1 % to 2–4 % within minutes. Either anchor the market
maker or stop it;
[Tuning the Traders](060-tuning-the-traders.md#the-market-maker) shows how.

## See also

- [News and Rumours](040-news-and-rumours.md) — the other way values move
- [The Market Model](../../operator-guide/part-4-run-a-market/090-market-model.md) — the reference: the formula, the sockets, `--init`
- [How the AI Traders Decide](../../participant-guide/part-4-automated-trading/020-how-the-bots-decide.md) — the `value` strategy in detail

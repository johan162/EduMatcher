# AI Traders & News

## Objective

Run a swarm of AI traders over a market whose prices have a hidden *true
value* behind them, then move that market with news: trade an earnings
surprise, decide what to do with a rumour, and watch a retraction unwind.

 


!!! abstract "Background reading"
    - [AI Traders](../participant-guide/part-4-automated-trading/010-ai-traders.md)
    - [Running the AI-Trader Swarm](../operator-guide/part-3-run/030-ai-trader-swarm.md)
    - [The Market Model (`pm-market-sim`)](../operator-guide/part-4-run-a-market/090-market-model.md)

## Prerequisites

- Chapters 01–13 completed.
- The `s150-nominal` example deployed (Exercise 1). It registers the AI
  traders `AI001`–`AI020`, the student desks `TRADER01`–`TRADER10`, the
  instructor `OPS01` (ADMIN) and the market maker `MM01`, and it ships the
  market model's `market_sim.yaml` and the swarm's `swarm.yaml`.

 

## Background

Three processes make the AI market:

- **`pm-market-sim`** — the market model. Every symbol gets a *true value*
  that moves like a company's value does: with the market, with its sector,
  on its own, and now and then in a jump. Students never see it. It also
  publishes **news**: headlines that move the values.
- **`pm-ai-swarm`** — runs many AI traders, each logged on through
  `pm-alf-gwy` as its own participant (`AI001`, `AI002`, …) exactly like a
  student desk. `pm-ai-trader` runs a single one.
- **`pm-news`** — the instructor's news desk: publish a headline now, or play
  a timed scenario.

Each AI trader is a *preset*: what it trades on (its strategy), how it places
orders, how fast, and its risk limits. `pm-ai-trader --list-presets` prints
them all:

| Preset | Trades on | Character |
|---|---|---|
| `noise-retail` | nothing in particular | Small random orders resting near the touch |
| `market-taker`, `iceberg-seller` | nothing in particular | Takes liquidity with MARKET orders; hides size behind icebergs |
| `scalper`, `trend-follower`, `block-taker` | momentum | Buys what has been rising, with IOC, marketable or fill-or-kill orders and protective stops |
| `contrarian`, `auction-player` | reversion | Fades moves; trades the opening and closing auctions |
| `value-investor`, `institutional` | the true value | Buys below its own (imperfect) estimate of the value, sells above it |
| `news-trader` | headlines | Trades a headline within seconds, hard, in its direction |

The value and news traders are why prices end up near the values and react
to news; the noise and momentum traders are why they never sit exactly on
them. A headline has a public *sentiment* (−1 bad to 1 good) and a secret
*impact* on the value. A **rumour** carries a *credibility* and moves no value
until it is **confirmed**; a **retracted** rumour never moves anything.

 

## Exercise 1: Deploy an Example with AI Traders

```bash
pm-config-deploy --example s150-nominal
```

Restart `pm-engine`, then start the gateway the AI traders log on through,
the market model, and a market maker for all 150 symbols that quotes around
the model's true values, each in its own terminal:

```bash
pm-alf-gwy -v
pm-market-sim -v
pm-mm-bot --gateway-id MM01 --all-symbols --strategy passive --gap 0.20 --qty 200 --anchor-sim 0.3
```

Without `--anchor-sim` the market maker keeps refilling its quotes around
its own mid, and no amount of informed trading moves the price.

Open the market from the operator console:

```
pm-admin --id OPS01
[OPS01|ADMIN]> SESSION|STATE=PRE_OPEN
[OPS01|ADMIN]> SESSION|STATE=OPENING_AUCTION
[OPS01|ADMIN]> SESSION|STATE=CONTINUOUS
```

`pm-market-sim` starts moving the values when continuous trading starts.
Check it:

```bash
pm-market-sim --status --id OPS01
```

:material-checkbox-blank-outline: **Checkpoint:** `pm-market-sim: RUNNING … symbols=150`.

 

## Exercise 2: One AI Trader

```bash
pm-ai-trader --id AI001 --preset noise-retail --symbols AAPL -v
```

The trader logs on, reads the AAPL book and starts resting small orders near
the touch. Watch them arrive with `BOOK|SYM=AAPL` in the operator console.
Stop it with Ctrl+C: its session closes and the participant's
`disconnect_behaviour` (`CANCEL_ALL`) removes its orders.

:material-checkbox-blank-outline: **Checkpoint:** AI001's orders appear in the AAPL book and disappear when you stop it.

 

## Exercise 3: The Swarm

```bash
pm-ai-swarm --swarm docs/examples/ref_data/s150-nominal-setup/swarm.yaml -v
```

`swarm.yaml` gives the twenty traders `AI001`–`AI020` a mix of every preset,
spreads the 150 symbols over them, and caps the whole swarm at 40 order
actions a second. Once a minute the swarm logs a status line:

```text
[w1-AI001-AI020] t=120s session=CONTINUOUS actions=4801 (40.0/s) live_orders=164 fills=1290 rejects=0
```

:material-checkbox-blank-outline: **Checkpoint:** a status line every minute; books changing on symbols nobody in the room is trading.

 

## Exercise 4: Price and Value

The instructor can see what the students cannot:

```bash
pm-market-sim --status --id OPS01 --top 5
```

```text
symbol        value        mid  mid/value
TSLA         212.40     219.95     +3.55%
...
```

The value traders lean against these gaps; the noise and momentum traders
keep opening new ones. Run the command again a few minutes later: the
symbols at the top change, and large gaps rarely last.

:material-checkbox-blank-outline: **Checkpoint:** mid/value gaps of a few percent at most, changing from one look to the next.

 

## Exercise 5: An Earnings Surprise

Every student opens a news display: the **News** screen of the trading GUI,
the News view of TapeDeck, `pm-ticker`, or simply

```bash
pm-news list
```

Then the instructor plays the first scenario:

```bash
pm-news --id OPS01 play docs/examples/news/earnings-surprise.yaml
```

Sixty seconds into the play (it counts from its start when the market is
already in continuous trading) AAPL reports far above expectations. The
news is confirmed from the start: AAPL's value jumps about 8% at once. The
news traders hit the book within seconds; the value investors follow.

Students try to buy AAPL as soon as they see the headline:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
```

Compare your fill with the AAPL price a minute later.

:material-checkbox-blank-outline: **Checkpoint:** AAPL trades several percent higher within a minute of the headline.

 

## Exercise 6: A Rumour That Turns Out True

First stop the market maker (Ctrl+C on `pm-mm-bot`; its quotes are
withdrawn). It quotes around the true values, and a rumour changes no value:
it would sell to every rumour buyer at the old price, and the rumour would
leave no trace. Without it, prices are what the traders believe — the AI
traders' resting orders keep the books two-sided.

```bash
pm-news --id OPS01 play docs/examples/news/rumour-confirmed.yaml
```

At 60 seconds a rumour says JPM is a takeover target, credibility 50%.
Nothing has happened to JPM's value — any move now is traders betting on the
rumour. Discuss before the next step: buy now, or wait? At 240 seconds the
bid is confirmed and the value jumps about 12%.

:material-checkbox-blank-outline: **Checkpoint:** JPM moves a little on the rumour and much more on the confirmation.

 

## Exercise 7: A Rumour That Is Retracted

```bash
pm-news --id OPS01 play docs/examples/news/rumour-retracted.yaml
```

At 60 seconds a rumour says energy producers face a new windfall tax: a
*sector* headline, so every ENERGY symbol (`XOM`, `CVX`, …) is concerned. The
values do not move; prices dip only because traders believe it. At 240
seconds it is retracted — in the GUIs the rumour is now struck through — and
prices drift back to where the values are.

:material-checkbox-blank-outline: **Checkpoint:** ENERGY symbols dip after the rumour and are back near their earlier prices a few minutes after the retraction.

Restart the market maker afterwards (the command from Exercise 1).

 

## Exercise 8: Stop the Swarm

Ctrl+C on `pm-ai-swarm` stops every worker; each closes its traders'
sessions, which cancels their orders. Stop `pm-market-sim` with Ctrl+C too:
it saves its values and continues from them next time.

:material-checkbox-blank-outline: **Checkpoint:** no `AI0xx` orders left in the books; the market maker's quotes remain.

 

## Classroom Tips

- Your own headlines need no scenario:
  `pm-news --id OPS01 inject --symbol TSLA --kind PRODUCT --sentiment -0.6 --impact -0.05`.
  A rumour you inject (`--rumour --credibility 0.4`) waits for your
  `pm-news --id OPS01 confirm N7` or `retract N7` — the id is printed when
  you inject it.
- `pm-market-sim` also generates news on its own, a handful a day. Set the
  rates in `market_sim.yaml` to `0` for a class where only your headlines
  should appear.
- Same `swarm.yaml` and `market_sim.yaml` seeds, same traders and same
  values: change `seed` in either file for a different market.
- A larger `--anchor-sim` (up to 1) makes the market maker follow the true
  value faster; then the AI traders, and the students, have less of a gap
  to trade.
- [Running the AI-Trader Swarm](../operator-guide/part-3-run/030-ai-trader-swarm.md)
  covers sizing, logs and daily summaries for longer runs.

 

## Reflection

Why does a confirmed headline move the price further than a rumour with the
same sentiment? Who in the swarm was on the other side of the news traders'
orders right after the earnings headline? The market maker quotes around the
true value: what would have happened to the price, and to the students'
chances of buying AAPL cheaply, if it had not been anchored?

 

## Further Reading

- [AI Traders](../participant-guide/part-4-automated-trading/010-ai-traders.md)
- [Running the AI-Trader Swarm](../operator-guide/part-3-run/030-ai-trader-swarm.md)
- [The Market Model (`pm-market-sim`)](../operator-guide/part-4-run-a-market/090-market-model.md)
- [The Market-Maker Bot (`pm-mm-bot`)](../participant-guide/part-3-market-making/030-the-market-maker-bot.md)

 

**Next:** [15 — Statistics & Reporting](150-statistics-reporting.md)

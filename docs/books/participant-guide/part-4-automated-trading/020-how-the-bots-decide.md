# How the AI Traders Decide

!!! note "Learning objectives"
    After reading this page you will be able to:

    - Follow one AI trader from a decision to the orders it sends
    - Explain each strategy, execution style, tempo and risk setting
    - Predict how a preset will behave, and write your own

    **Prerequisites**: [AI Traders](010-ai-traders.md).

## The loop

An AI trader does nothing on a fixed timer. Decisions arrive at random — a
Poisson process at the tempo's `decisions_per_min` — so a swarm's orders do
not come in bursts. In between, it keeps its house in order. Each time it
wakes, in this order:

1. **Housekeeping.** Cancel resting orders older than `max_order_age_sec`, or
   more than `stale_price_ticks` behind the touch on their own side (a buy
   order behind the best bid, a sell order behind the best ask).
2. **Slices due** of a `twap` parent order.
3. **Protection.** Place, resize or remove the protective orders for each
   open position (continuous trading only).
4. **A decision**, if one is due: the strategy names a symbol, a side, an
   urgency and a size multiplier — an *intent* — or nothing. The execution
   style turns the intent into orders, within the risk limits.

During continuous trading the decision rate follows the day's U shape:
about twice the average after the open and before the close, half of it at
midday. A swarm's `budget` scales every trader's rate so the swarm as a
whole sends the actions per second it was given.

The trader reads the market from the engine's public feed — book snapshots,
trades, the session, halts — and from `pm-market-sim` the true values and
the news. It sends nothing for a halted symbol, nothing while the market is
closed, and only what each phase allows: resting LIMIT and ICEBERG orders in
the call phases, ATO in the opening auction, ATC in the closing auction,
everything during continuous trading.

## Strategies: what to trade

A strategy says which way it leans with a *score* from −1 to 1 and buys with
probability `(1 + score × strength) / 2`, so it leans without becoming
predictable.

| Strategy | Looks at | Buys when | Parameters |
|---|---|---|---|
| `noise` | one random symbol | at random (score 0) | `urgency` |
| `trend` | `sample` random symbols, acts on the strongest signal | its fast average price (30 s) is above its slow one (300 s) | `strength`, `sample`, `urgency` |
| `reversion` | the same way | the price is below its slow average | `strength`, `sample`, `urgency` |
| `value` | `sample` random symbols, acts on the widest gap | the price is below its view of the true value by more than `threshold` | `threshold`, `bias_std`, `redraw`, `sample`, `urgency`, `rumour_shift` |
| `news` | the news touching its symbols | the headline is good news | `lag_sec`, `lag_sigma`, `half_life_sec`, `threshold`, `urgency`, `move` |

**Trend and reversion** need about 30 seconds and 20 prices of a symbol
before they have an opinion on it. Both scale the difference by the symbol's
own recent volatility, so a 1% move means more in a quiet stock than in a
wild one. The stronger the signal, the more urgent the intent.

**Value** sees each symbol's true value through a bias of its own — a
persistent error, drawn per symbol with standard deviation `bias_std` and
re-drawn now and then (`redraw`). That is why two value traders disagree,
and trade with each other. It acts once the log gap between its view and the
price exceeds `threshold`; the wider the gap, the more urgent and the larger
the order, up to three times its usual size. When it crosses the spread it
pays up to its view of the value less `threshold` — not one tick past the
touch — so a jump in the value is priced in by a few orders rather than a
thousand one-tick steps. An open rumour shifts its view by
`rumour_shift × sentiment × credibility`.

**News** hears each headline after a delay of its own (lognormal, median
`lag_sec`), so news traders do not all hit the book in the same millisecond.
From then on its conviction is the headline's |sentiment| — times the
credibility for a rumour — halving every `half_life_sec`. While conviction is
above `threshold` it trades the headline's symbols in the headline's
direction, urgently and in up to three times its usual size, paying up to
`move × conviction` (a log move) beyond the price it saw when it first acted
on the headline. A confirmation
turns a rumour into news known to be true; a retraction leaves an impulse the
other way, as large as the rumour was believable.

## Execution styles: how to trade it

| Style | Sends | Parameters |
|---|---|---|
| `passive` | A LIMIT `offset_ticks` behind the touch (0 joins it) | `offset_ticks`, `tif` |
| `marketable` | A LIMIT `cross_ticks` through the touch; what does not fill rests | `cross_ticks`, `tif` |
| `sweep` | A MARKET, IOC or FOK order against the other side | `sweep_type`, `cross_ticks` |
| `iceberg` | An ICEBERG behind the touch showing `visible_fraction` of its size | `offset_ticks`, `visible_fraction` |
| `twap` | A parent order cut into `slices` child orders over `horizon_sec` | `slices`, `horizon_sec`, `child_style` |

Any style becomes marketable when the intent's urgency reaches
`urgency_cross`. A crossing order (marketable, IOC, FOK) is priced at the
strategy's limit when it gives one (`value` and `news` do), otherwise
`cross_ticks` past the touch. In the call phases — pre-open and the auctions — a trader
takes part in a decision with probability `auction_participation`, and then
sends a limit order straddling the reference price (with TIF ATO or ATC in
the auctions), so that buyers and sellers overlap at the uncross. Prices are
kept inside the symbol's price collar and quantities inside its order
limits: an AI trader does not send what the engine would refuse.

## Tempo: how often and how big

| Tempo | Decisions per minute | Order size | Sizes |
|---|---|---|---|
| `many-small` | 30 | 1–25 | mostly small |
| `aggressive` | 20 | 20–120 | even |
| `cautious` | 6 | 10–60 | even |
| `few-large` | 2 | 150–700 | mostly large |

A preset can give its own instead:
`tempo: {decisions_per_min: 12, size_min: 5, size_max: 80, size_distribution: small-heavy}`
(`balanced`, `small-heavy` or `block-heavy`). The strategy's size multiplier
applies on top.

## Risk: what it will not do

| Setting | Effect |
|---|---|
| `max_position` | No order that could take the position past ± this many shares, counting open orders as if filled |
| `max_live_orders_per_symbol` | At most this many working orders per symbol |
| `max_order_age_sec` | Cancel resting orders older than this |
| `stale_price_ticks` | Cancel resting orders this far behind their own side's touch |
| `protection`, `protection_pct` | Protective orders for open positions, `protection_pct` of the price away |

`protection` is one of `none`, `stop` (a STOP order), `stop_limit`,
`trailing` (a TRAILING_STOP) or `bracket` (an OCO of a take-profit LIMIT and
a STOP). It follows the position: a new fill resizes it, a flat position
removes it.

A trader that gets 25 orders refused within 10 seconds pauses for 5 seconds
— the *reject breaker* — so a misconfigured preset cannot flood the
exchange with refused orders. A cancel that lost the race with a fill, or an
order in flight when the market closed, does not count.

## Writing a preset

Start from the closest built-in preset in `src/edumatcher/ai_trader/presets/`
and change one part at a time:

| You want | Change |
|---|---|
| More flow | `tempo` |
| Takes liquidity instead of providing it | `execution.style: sweep` or `marketable` |
| Holds bigger positions | `risk.max_position` |
| Reacts to news faster | `strategy.lag_sec` (news), `execution.urgency_cross` |
| Disagrees more with other value traders | `strategy.bias_std` (value) |

Every parameter has a range; a value outside it is refused with the file and
the key named. [AI Traders](010-ai-traders.md#your-own-preset) shows how to
run your preset.

## The other bot: `pm-mm-bot`

`pm-ai-trader` trades like a directional participant. The
[market-maker bot](../part-3-market-making/030-the-market-maker-bot.md) has
a different job: it posts two-sided quotes on many symbols from one
participant ID. Run one with the swarm — AI traders alone make a thin, jumpy
book.

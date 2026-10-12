# Simulation Glossary

The terms this book uses for the simulation. Exchange terms in general —
order book, spread, auction, tick — are in the Reference Manual's glossary
and in [How an Exchange Works](../../../how-exchange-works.md).

**Accelerated time** — Running the trading calendar faster than the wall
clock (`EM_SPEED`). Only the calendar is faster; the traders act at their
usual pace. See [Accelerated Time](../part-3-run-it/120-accelerated-time.md).

**`ai-sim`** — The process profile that runs the simulation: the full
exchange, the market maker, the market model and the AI swarm.

**AI trader** — A program that trades as a participant (`AI001`…), following
a preset. Many of them run inside one `pm-ai-swarm`.

**Anchor** (`--anchor-sim`) — How strongly the market maker moves its quotes
toward the true value each second: the share of the remaining gap it closes.

**Bias** — A value trader's own, persistent error about a share's value.
Different biases are why value traders disagree and trade with each other.

**Budget** — The order actions per second (new orders and cancels) the whole
swarm aims for.

**Composition** — The mix of presets in the swarm: how many traders of each
kind.

**Credibility** — How believable a rumour looks, 0 to 1. Informative, not
reliable.

**Efficiency** — How closely prices follow the true values; measured as the
gap.

**`EM_SPEED`, `EM_START`** — The container's settings for accelerated time:
how many times faster, and from when.

**Gap** — `ln(price / value)`: how far a price is from its true value, about
the same as the percentage difference. Summarised over all shares as its
RMS (root mean square).

**Headline** — A piece of news: scope, kind, sentiment, and the secret
impact.

**Impact** — The log move a confirmed headline causes in the true value;
secret. 0.05 is about +5 %.

**Informed trader** — A trader that knows something about the true values or
the news: the `value-investor`, `institutional` and `news-trader` presets.

**Jump** — A sudden move in a value without any headline: an unannounced
event.

**Market model** — `pm-market-sim`: keeps the true values, moves them,
publishes news.

**Noise trader** — A trader that trades in random directions, without
information: `noise-retail`, `market-taker`, `iceberg-seller`.

**Preset** — A kind of AI trader: a strategy, an execution style, a tempo
and risk limits, in one YAML file.

**Price discovery** — The process by which trading moves a price toward the
value.

**Retention** — How long a record is kept before it is deleted to bound the
disk: 7 days for individual trades in the statistics and in clearing, about
an hour for order events, 30 days for logs, the last 60 MB of the audit trail.

**Rumour** — A headline that may not be true. It moves no value until it is
confirmed; if it is retracted, it never does.

**Scope** — What a headline is about: one symbol, a sector, or the whole
market.

**Sector** — An industry group of shares that move together: eleven in
`s300-sim`.

**Sentiment** — How good a headline sounds, −1 to +1; public, and a blurred
version of the impact.

**`s300-sim`** — The bundled example the simulation runs: 300 shares,
`AI001`–`AI100`, `MM01`, `TRADER01`–`TRADER10`, `OPS01`.

**Swarm** — `pm-ai-swarm`: the process that runs many AI traders, in one or
more worker processes.

**True value** — A share's hidden value in the market model; what price
discovery aims at.

**Volatility** — How much a value (or a price) moves: the standard deviation
of its log changes, quoted per year (30 % a year is about 1.9 % a day).

**Watchdog** — The container's once-a-minute check that restarts any process
of the profile that has died (`EM_RESTART_DEAD=1`).

# 300-Symbol Simulation Setup

The long-running simulated market of the
[AI Traders and Market Simulation](../../../books/ai-traders/00-front/010-how-to-use-this-book.md)
book, and the default of the `edumatcher-ai-sim` container image.

- Symbols: 300 (the 150 `s150` tickers plus 150 more)
- Participants: `TRADER01`–`TRADER10` (people), `OPS01` (instructor), `MM01` (the market-maker bot), and AI traders `AI001`–`AI100`
- `swarm.yaml`: the 100 AI traders, each trading 30 symbols (about 10 agents per symbol), 80 order actions a second in total
- `market_sim.yaml`: the market model (hidden true values) with generated news and rumours on
- Sessions: enabled, the default weekday schedule 09:00–16:05, Sweden's calendar and time zone; collars off; market-maker obligations enforced
- Seeded market-maker quotes on every symbol
- Market-data gateway: `max_symbols_per_client: 300`
- Run it: `pm-config-deploy --example s300-sim`, then `pm-opctl-cli start ai-sim`
- Regenerate: `./mkrefdata.sh [--seed INTEGER]` (this file was generated with `--seed 300100`)

# 300-Symbol Load Setup

Design-limit test bed for the AI traders (see `docs-design/EduMatcher-AI-Traders-v3-Plan.md`, WP-A3).

- Symbols: 300 (the 150 `s150` tickers plus 150 more)
- Participants: `TRADER01`–`TRADER10`, `OPS01`, `MM01`, `MM02`, and AI traders `AI001`–`AI500`; start the swarm with `pm-ai-swarm --swarm swarm.yaml` (this directory)
- Sessions: enabled (default schedule); collars off; market-maker obligations enforced
- Seeded market-maker quotes on every symbol
- Market-data gateway: `max_symbols_per_client: 300`
- Regenerate: `./mkrefdata.sh [--seed INTEGER]` (this file was generated with `--seed 300500`)

# 150-Symbol Nominal Setup

This folder contains a generated reference configuration for a 150-symbol **nominal** environment with seeded market-maker quotes.

- Sessions: enabled with the default schedule
- Market-data and post-trade gateways: enabled
- AI traders: participants `AI001`–`AI020` (`TRADER`); start them with `pm-ai-swarm --swarm swarm.yaml` (this directory)
- Regenerate: `./mkrefdata.sh [--seed INTEGER]`
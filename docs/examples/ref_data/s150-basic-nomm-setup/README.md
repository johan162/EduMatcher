# 150-Symbol Basic Setup Without Seed Quotes

This folder contains a generated reference configuration for a 150-symbol **basic** environment without seeded market-maker quotes.

- Sessions: disabled
- Risk, market-maker, and circuit-breaker tuning: defaults
- AI traders: participants `AI001`–`AI020` (`TRADER`); start them with `pm-ai-swarm --swarm swarm.yaml` (this directory)
- Regenerate: `./mkrefdata.sh [--seed INTEGER]`
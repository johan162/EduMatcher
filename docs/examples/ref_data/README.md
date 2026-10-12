# Reference Data Templates

This folder contains runnable engine configuration templates grouped by book count and setup profile.

Each `*-setup/` directory contains:

- `README.md`
- `mkrefdata.sh`
- `engine_config.yaml`

## Regenerating configs

A `Makefile` is provided to regenerate all configs at once:

```bash
make          # regenerates every discovered setup (default target: configs)
make configs  # same
```

Each subdirectory's `mkrefdata.sh` is discovered automatically via wildcard
expansion, so new setups are picked up without editing the Makefile.

Each `mkrefdata.sh` is a one-line wrapper that delegates to a shared
generator, driven entirely by its own directory name (size/profile/mm):

- `s1-*`, `s3-*`, `s10-*`, `s30-*` setups delegate to `mkrefdata_common.py`
  (requires `python3`).
- `s150-*` setups delegate to `mks150.sh`; `s300-*` setups delegate to
  `mks300.sh`.

### Seed reuse

Running a setup's `mkrefdata.sh` without `--seed`:

- generates a new random seed, if `engine_config.yaml` doesn't exist yet;
- otherwise reuses the seed already recorded in that file's header comment,
  so re-running (e.g. via `make force`) reproduces the same book instead of
  drawing a new random one.

Pass `--seed <integer>` explicitly to override either way.

## Notes

- `pm-config-gen` supports emitting both RALF (`post_trade_gateway`) and CALF (`market_data_gateway`) sections via native flags.
- Generated symbol entries now include mandatory `outstanding_shares` values so the configs are ready for statistics and future index-style consumers.
- The `s150-*` setups provide basic, nominal, and complex 150-symbol variants, with and without seeded market-maker quotes. Each also lists `AI001`–`AI020` as `TRADER` participants, so `pm-ai-swarm --count 20` runs against any of them unchanged.
- `s300-load-setup` (`--example s300-load`) is the AI-trader design-limit test bed: 300 symbols (the s150 tickers plus 150 more), sessions enabled, seeded quotes from `MM01`/`MM02`, `TRADER01`–`TRADER10`, `OPS01`, and `AI001`–`AI500`. It has no `-nomm` variant.

# Reference Data Templates

This folder contains runnable engine configuration templates grouped by book count and setup profile.

Each `*-setup/` directory contains:

- `README.md`
- `mkrefdata.sh`
- `engine_config.yaml`

## Regenerating configs

A `Makefile` is provided to regenerate all configs at once:

```bash
make          # regenerates all 12 subdirectories (default target: configs)
make configs  # same
```

Each subdirectory's `mkrefdata.sh` is discovered automatically via wildcard
expansion, so new setups are picked up without editing the Makefile.

## Notes

- `pm-config-gen` supports emitting both RALF (`post_trade_gateway`) and CALF (`market_data_gateway`) sections via native flags.
- Generated symbol entries now include mandatory `outstanding_shares` values so the configs are ready for statistics and future index-style consumers.
- `one-book-setup` is a legacy single-file sample kept for backward compatibility.

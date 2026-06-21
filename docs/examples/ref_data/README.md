# Reference Data Templates

This folder contains runnable engine configuration templates grouped by book count and setup profile.

Each `*-setup/` directory contains:

- `README.md`
- `mkrefdata.sh`
- `engine_config.yaml`

## Notes

- `pm-config-gen` supports emitting both RALF (`post_trade_gateway`) and CALF (`market_data_gateway`) sections via native flags.
- `one-book-setup` is a legacy single-file sample kept for backward compatibility.

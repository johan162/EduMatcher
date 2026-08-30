# 10-Book Complex Setup

This folder contains a generated reference configuration template for a 10-book **complex** environment.

## Files

- `mkrefdata.sh` - Regenerates `engine_config.yaml` via `pm-config-gen` plus profile-specific post-processing
- `engine_config.yaml` - Ready-to-use generated config

## Setup Profile

- Books: 10 symbols
- Symbols: AAPL MSFT TSLA AMZN GOOGL META NVDA NFLX INTC ORCL
- Base gateways: `TRADER01` .. `TRADER05`, `OPS01:ADMIN`
- Includes two MARKET_MAKER gateways across all symbols (two quote seeds per symbol)
- Includes explicit risk/circuit-breaker/session/MM options
- Includes RALF `post_trade_gateway` block from `pm-config-gen`
- Includes CALF `market_data_gateway` block from `pm-config-gen`

Note: both RALF and CALF sections are generated natively by `pm-config-gen`.

## Verify

From this directory:

```bash
./mkrefdata.sh
```

Then validate with your runtime checks from the configuration guide.

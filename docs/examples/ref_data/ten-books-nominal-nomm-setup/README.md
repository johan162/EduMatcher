# 10-Book Nominal Setup

This folder contains a generated reference configuration template for a 10-book **nominal** environment.

## Files

- `mkrefdata.sh` - Regenerates `engine_config.yaml` via `pm-config-gen` plus profile-specific post-processing
- `engine_config.yaml` - Ready-to-use generated config

## Setup Profile

- Books: 10 symbols
- Symbols: AAPL MSFT TSLA AMZN GOOGL META NVDA NFLX INTC ORCL
- Base gateways: `TRADER01`, `TRADER02`, `OPS01:ADMIN`
- Includes one MARKET_MAKER gateway across all symbols (one quote seed per symbol)
- Includes RALF `post_trade_gateway` block from `pm-config-gen`
- Includes CALF `market_data_gateway` block from `pm-config-gen`

Note: both RALF and CALF sections are generated natively by `pm-config-gen`.

## Verify

From this directory:

```bash
./mkrefdata.sh
```

Then validate with your runtime checks from the configuration guide.

# 30-Book Basic Setup

This folder contains a generated reference configuration template for a 30-book **basic** environment.

## Files

- `mkrefdata.sh` - Regenerates `engine_config.yaml` via `pm-config-gen` plus profile-specific post-processing
- `engine_config.yaml` - Ready-to-use generated config

## Setup Profile

- Books: 30 symbols
- Symbols: AAPL MSFT TSLA AMZN GOOGL META NVDA NFLX INTC ORCL IBM ADBE CRM QCOM AMD AVGO TXN NOW SHOP UBER PYPL SQ BABA SONY SAP ASML CSCO MU BKNG TSM
- Base gateways: `TRADER01`, `TRADER02`, `OPS01:ADMIN`
- Sessions: disabled (minimal setup)
- Risk/MM/CB tuning: defaults

## Verify

From this directory:

```bash
./mkrefdata.sh
```

Then validate with your runtime checks from the configuration guide.

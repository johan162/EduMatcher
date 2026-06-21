#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if command -v pm-config-gen >/dev/null 2>&1; then
  CONFIG_GEN=(pm-config-gen)
elif command -v poetry >/dev/null 2>&1; then
  CONFIG_GEN=(poetry run pm-config-gen)
else
  echo "Error: neither pm-config-gen nor poetry is available in PATH" >&2
  exit 1
fi

SYMBOLS=(AAPL MSFT TSLA AMZN GOOGL META NVDA NFLX INTC ORCL IBM ADBE CRM QCOM AMD AVGO TXN NOW SHOP UBER PYPL SQ BABA SONY SAP ASML CSCO MU BKNG TSM)
GATEWAYS=(TRADER01 TRADER02 OPS01:ADMIN)

COMMON_ARGS=(
  --symbols "${SYMBOLS[@]}"
  --gateways "${GATEWAYS[@]}"
  --output engine_config.yaml
  --force
)
"${CONFIG_GEN[@]}" "${COMMON_ARGS[@]}"

echo "Generated $(pwd)/engine_config.yaml"

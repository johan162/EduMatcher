#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

SEED=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --seed)
      if [[ $# -lt 2 ]]; then
        echo "Error: --seed requires an integer argument" >&2
        exit 1
      fi
      SEED="$2"
      shift 2
      ;;
    --seed=*)
      SEED="${1#*=}"
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--seed <integer>]"
      exit 0
      ;;
    *)
      echo "Error: unknown argument: $1" >&2
      echo "Usage: $0 [--seed <integer>]" >&2
      exit 1
      ;;
  esac
done

if [[ -n "$SEED" && ! "$SEED" =~ ^-?[0-9]+$ ]]; then
  echo "Error: --seed must be an integer" >&2
  exit 1
fi

SEED_ARGS=()
if [[ -n "$SEED" ]]; then
  SEED_ARGS=(--seed "$SEED")
fi

if command -v pm-config-gen >/dev/null 2>&1; then
  CONFIG_GEN=(pm-config-gen)
elif command -v poetry >/dev/null 2>&1; then
  CONFIG_GEN=(poetry run pm-config-gen)
else
  echo "Error: neither pm-config-gen nor poetry is available in PATH" >&2
  exit 1
fi

SYMBOLS=(AAPL)
GATEWAYS=(TRADER01:TRADER:CANCEL_ALL TRADER02:TRADER:CANCEL_ALL OPS01:ADMIN:LEAVE_ALL)
MM_GATEWAYS=(MM01:MARKET_MAKER:CANCEL_QUOTES_ONLY)
GATEWAYS+=("${MM_GATEWAYS[@]}")

OUTSTANDING_ARGS=(
  --outstanding-shares AAPL:15400000000
)

COMMON_ARGS=(
  --symbols "${SYMBOLS[@]}"
  --gateways "${GATEWAYS[@]}"
  --seed-mm-mid-range 20:300
  --seed-last-prices-from-mm
  --output engine_config.yaml
  --force
  --comment-default-config-fields
  "${SEED_ARGS[@]}"
  "${OUTSTANDING_ARGS[@]}"
)
"${CONFIG_GEN[@]}" "${COMMON_ARGS[@]}" \
  --sessions-enabled \
  --post-trade-gateway \
  --post-trade-bind-address 127.0.0.1 \
  --post-trade-port 5580 \
  --post-trade-replay-retention-sec 3600 \
  --post-trade-heartbeat-interval-sec 1 \
  --post-trade-idle-timeout-sec 10 \
  --post-trade-max-client-queue 5000 \
  --post-trade-allowed-roles CLEARING DROP_COPY AUDIT \
  --market-data-gateway \
  --market-data-enabled \
  --market-data-name md-gwy01 \
  --market-data-bind-address 127.0.0.1 \
  --market-data-port 5570 \
  --market-data-heartbeat-interval-sec 1 \
  --market-data-idle-timeout-sec 5 \
  --market-data-replay-window-sec 30 \
  --market-data-max-symbols-per-client 200 \
  --market-data-max-client-queue 10000

echo "Generated $(pwd)/engine_config.yaml"

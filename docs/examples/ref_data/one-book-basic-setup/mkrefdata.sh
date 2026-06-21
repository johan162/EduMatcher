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
GATEWAYS=(TRADER01 TRADER02 OPS01:ADMIN MM01:MARKET_MAKER:CANCEL_QUOTES_ONLY)

OUTSTANDING_ARGS=(
  --outstanding-shares AAPL:15400000000
)

COMMON_ARGS=(
  --symbols "${SYMBOLS[@]}"
  --gateways "${GATEWAYS[@]}"
  --seed-mm-mid-range 20:300
  --seed-last-prices-from-mm
  --no-collars
  --no-circuit-breakers
  --output engine_config.yaml
  --force
  --comment-default-config-fields
  "${SEED_ARGS[@]}"
  "${OUTSTANDING_ARGS[@]}"
)
"${CONFIG_GEN[@]}" "${COMMON_ARGS[@]}"

echo "Generated $(pwd)/engine_config.yaml"

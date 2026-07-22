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

# Guarantee a deterministic seed so both generation passes produce identical
# MM quote prices, keeping the combo leg prices consistent with the book seeds.
if [[ -z "$SEED" ]]; then
  SEED=$(( RANDOM * 32768 + RANDOM ))
  echo "[INFO] Auto-generated seed $SEED — re-run with --seed $SEED for identical output." >&2
fi
SEED_ARGS=(--seed "$SEED")

if command -v pm-config-gen >/dev/null 2>&1; then
  CONFIG_GEN=(pm-config-gen)
elif command -v poetry >/dev/null 2>&1; then
  CONFIG_GEN=(poetry run pm-config-gen)
else
  echo "Error: neither pm-config-gen nor poetry is available in PATH" >&2
  exit 1
fi

SYMBOLS=(AAPL MSFT TSLA AMZN GOOGL META NVDA NFLX INTC ORCL)
GATEWAYS=(
  "TRADER01:TRADER:CANCEL_ALL:Student desk 1"
  "TRADER02:TRADER:CANCEL_ALL:Student desk 2"
  "OPS01:ADMIN:LEAVE_ALL:Instructor console"
  "MM01:MARKET_MAKER:CANCEL_QUOTES_ONLY:Market maker"
)

OUTSTANDING_ARGS=(
  --outstanding-shares AAPL:15400000000
  --outstanding-shares MSFT:7430000000
  --outstanding-shares TSLA:3200000000
  --outstanding-shares AMZN:10600000000
  --outstanding-shares GOOGL:12200000000
  --outstanding-shares META:2560000000
  --outstanding-shares NVDA:24600000000
  --outstanding-shares NFLX:430000000
  --outstanding-shares INTC:4300000000
  --outstanding-shares ORCL:2800000000
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

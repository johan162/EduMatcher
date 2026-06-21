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

SYMBOLS=(AAPL MSFT TSLA AMZN GOOGL META NVDA NFLX INTC ORCL)
GATEWAYS=(TRADER01:TRADER:CANCEL_ALL TRADER02:TRADER:CANCEL_ALL TRADER03:TRADER:CANCEL_ALL TRADER04:TRADER:CANCEL_ALL TRADER05:TRADER:CANCEL_ALL OPS01:ADMIN:LEAVE_ALL)
MM_GATEWAYS=(MM01:MARKET_MAKER:CANCEL_QUOTES_ONLY MM02:MARKET_MAKER:CANCEL_QUOTES_ONLY)
GATEWAYS+=("${MM_GATEWAYS[@]}")

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
  --output engine_config.yaml
  --force
  --comment-default-config-fields
  "${SEED_ARGS[@]}"
  "${OUTSTANDING_ARGS[@]}"
)
"${CONFIG_GEN[@]}" "${COMMON_ARGS[@]}" \
  --sessions-enabled \
  --schedule \
  --pre-open 08:45 \
  --opening-auction 08:55 \
  --continuous 09:00 \
  --closing-auction 16:00 \
  --closing-end 16:10 \
  --snapshot-interval 0.25 \
  --static-band 0.20 \
  --dynamic-band 0.02 \
  --risk-level CORE:0.18:0.02 \
  --risk-level HIGH_BETA:0.12:0.04 \
  --cb-levels L1:0.07:5 L2:0.13:15 L3:0.20:0 \
  --cb-window-ns 300000000000 \
  --mm-spread-ticks 12 \
  --mm-min-qty 200 \
  --enforce-mm-obligations \
  --tick-decimals 2 \
  --symbol-opts AAPL:level=CORE,mm_spread_ticks=8,mm_min_qty=300 \
  --symbol-opts TSLA:level=HIGH_BETA,dynamic_band=0.04,cb_halt_l1=10 \
  --post-trade-gateway \
  --post-trade-name ralf-gwy01 \
  --post-trade-bind-address 127.0.0.1 \
  --post-trade-port 5580 \
  --post-trade-replay-retention-sec 14400 \
  --post-trade-heartbeat-interval-sec 1 \
  --post-trade-idle-timeout-sec 10 \
  --post-trade-max-client-queue 8000 \
  --post-trade-allowed-roles CLEARING DROP_COPY AUDIT \
  --market-data-gateway \
  --market-data-enabled \
  --market-data-name md-gwy01 \
  --market-data-bind-address 127.0.0.1 \
  --market-data-port 5570 \
  --market-data-heartbeat-interval-sec 1 \
  --market-data-idle-timeout-sec 5 \
  --market-data-replay-window-sec 120 \
  --market-data-max-symbols-per-client 500 \
  --market-data-max-client-queue 20000

# Add one explicit seeded MM combo for complex profile bootstrap.
combo_a="${SYMBOLS[0]}"
combo_b="${SYMBOLS[1]}"
combo_price_a="$(awk -v symbol="$combo_a" '
$0 == "symbols:" { in_symbols = 1; next }
in_symbols && $0 ~ /^  [A-Z0-9_.-]+:$/ {
  current = $1
  sub(/:$/, "", current)
  next
}
in_symbols && current == symbol && $1 == "last_buy_price:" {
  printf "%d\n", (($2 + 0) * 100) + 0.5
  exit
}
' engine_config.yaml)"
combo_price_b="$(awk -v symbol="$combo_b" '
$0 == "symbols:" { in_symbols = 1; next }
in_symbols && $0 ~ /^  [A-Z0-9_.-]+:$/ {
  current = $1
  sub(/:$/, "", current)
  next
}
in_symbols && current == symbol && $1 == "last_buy_price:" {
  printf "%d\n", (($2 + 0) * 100) + 0.5
  exit
}
' engine_config.yaml)"
cat >> engine_config.yaml <<YAML

market_maker_combos:
  - combo_id: SEED-PAIR-${combo_a}-${combo_b}
    combo_type: AON
    tif: DAY
    legs:
      - symbol: ${combo_a}
        side: BUY
        order_type: LIMIT
        quantity: 100
        price: ${combo_price_a}
        stop_price:
        smp_action: NONE
      - symbol: ${combo_b}
        side: SELL
        order_type: LIMIT
        quantity: 100
        price: ${combo_price_b}
        stop_price:
        smp_action: NONE
YAML

echo "Generated $(pwd)/engine_config.yaml"

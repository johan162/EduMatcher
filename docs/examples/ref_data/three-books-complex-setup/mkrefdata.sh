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

if command -v pm-config-gen >/dev/null 2>&1; then
  CONFIG_GEN=(pm-config-gen)
elif command -v poetry >/dev/null 2>&1; then
  CONFIG_GEN=(poetry run pm-config-gen)
else
  echo "Error: neither pm-config-gen nor poetry is available in PATH" >&2
  exit 1
fi

SYMBOLS=(AAPL MSFT TSLA)
GATEWAYS=(TRADER01:TRADER:CANCEL_ALL TRADER02:TRADER:CANCEL_ALL TRADER03:TRADER:CANCEL_ALL TRADER04:TRADER:CANCEL_ALL TRADER05:TRADER:CANCEL_ALL OPS01:ADMIN:LEAVE_ALL)
MM_GATEWAYS=(MM01:MARKET_MAKER:CANCEL_QUOTES_ONLY MM02:MARKET_MAKER:CANCEL_QUOTES_ONLY)
GATEWAYS+=("${MM_GATEWAYS[@]}")

COMMON_ARGS=(
  --symbols "${SYMBOLS[@]}"
  --gateways "${GATEWAYS[@]}"
  --output engine_config.yaml
  --force
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
  --seed-last-prices \
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

# Assign a varied bootstrap mid-price per symbol (20-300), then derive
# last buy/sell and MM bid/ask around that symbol-specific midpoint.
if [[ -n "$SEED" ]]; then
  RANDOM="$SEED"
fi

SYMBOL_MIDS=()
MID_VALUES=()
for sym in "${SYMBOLS[@]}"; do
  mid=$((20 + RANDOM % 281))
  SYMBOL_MIDS+=("${sym}:${mid}")
  MID_VALUES+=("${mid}")
done
SYMBOL_MIDS_CSV="$(IFS=,; echo "${SYMBOL_MIDS[*]}")"

awk -v mids_csv="$SYMBOL_MIDS_CSV" '
BEGIN {
  n = split(mids_csv, pairs, ",")
  for (i = 1; i <= n; i++) {
    split(pairs[i], kv, ":")
    mid[kv[1]] = kv[2] + 0
  }
}
function fmt(v) { return sprintf("%.2f", v) }
$0 == "symbols:" { in_symbols = 1; print; next }
in_symbols && $0 ~ /^  [A-Z0-9_.-]+:$/ {
  current_symbol = $0
  sub(/^  /, "", current_symbol)
  sub(/:$/, "", current_symbol)
  print
  next
}
in_symbols && current_symbol != "" && $0 ~ /^    last_buy_price:/ {
  $0 = "    last_buy_price: " fmt(mid[current_symbol] - 0.50) "    # REQUIRED: set last buy reference price"
  print
  next
}
in_symbols && current_symbol != "" && $0 ~ /^    last_sell_price:/ {
  $0 = "    last_sell_price: " fmt(mid[current_symbol] + 0.50) "    # REQUIRED: set last sell reference price"
  print
  next
}
in_symbols && current_symbol != "" && $0 ~ /^      bid_price:/ {
  $0 = "      bid_price: " fmt(mid[current_symbol] - 0.50) "    # REQUIRED: set display bid price (e.g. 209.00)"
  print
  next
}
in_symbols && current_symbol != "" && $0 ~ /^      ask_price:/ {
  $0 = "      ask_price: " fmt(mid[current_symbol] + 0.50) "    # REQUIRED: set display ask price (e.g. 211.00)"
  print
  next
}
{ print }
' engine_config.yaml > engine_config.yaml.tmp
mv engine_config.yaml.tmp engine_config.yaml

# Add one explicit seeded MM combo for complex profile bootstrap.
combo_a="${SYMBOLS[0]}"
combo_b="${SYMBOLS[1]}"
combo_price_a=$((MID_VALUES[0] * 100))
combo_price_b=$((MID_VALUES[1] * 100))
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

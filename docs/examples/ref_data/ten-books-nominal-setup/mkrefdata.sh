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

SYMBOLS=(AAPL MSFT TSLA AMZN GOOGL META NVDA NFLX INTC ORCL)
GATEWAYS=(TRADER01:TRADER:CANCEL_ALL TRADER02:TRADER:CANCEL_ALL OPS01:ADMIN:LEAVE_ALL)
MM_GATEWAYS=(MM01:MARKET_MAKER:CANCEL_QUOTES_ONLY)
GATEWAYS+=("${MM_GATEWAYS[@]}")

COMMON_ARGS=(
  --symbols "${SYMBOLS[@]}"
  --gateways "${GATEWAYS[@]}"
  --output engine_config.yaml
  --force
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

echo "Generated $(pwd)/engine_config.yaml"

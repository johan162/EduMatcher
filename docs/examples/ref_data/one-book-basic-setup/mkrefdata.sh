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

SYMBOLS=(AAPL)
GATEWAYS=(TRADER01 TRADER02 OPS01:ADMIN MM01:MARKET_MAKER:CANCEL_QUOTES_ONLY)

COMMON_ARGS=(
  --symbols "${SYMBOLS[@]}"
  --gateways "${GATEWAYS[@]}"
  --output engine_config.yaml
  --force
)
"${CONFIG_GEN[@]}" "${COMMON_ARGS[@]}"

# Seed one startup MM quote per symbol so each book has immediate top-of-book
# liquidity, without requiring any running MM bot process.
SYMBOL_MIDS=()
for i in "${!SYMBOLS[@]}"; do
  mid=$((100 + i * 10))
  SYMBOL_MIDS+=("${SYMBOLS[i]}:${mid}")
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

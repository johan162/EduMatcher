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

SYMBOLS=(AAPL MSFT TSLA AMZN GOOGL META NVDA NFLX INTC ORCL IBM ADBE CRM QCOM AMD AVGO TXN NOW SHOP UBER PYPL SQ BABA SONY SAP ASML CSCO MU BKNG TSM)
GATEWAYS=(
  "TRADER01:TRADER:CANCEL_ALL:Student desk 1"
  "TRADER02:TRADER:CANCEL_ALL:Student desk 2"
  "TRADER03:TRADER:CANCEL_ALL:Student desk 3"
  "TRADER04:TRADER:CANCEL_ALL:Student desk 4"
  "TRADER05:TRADER:CANCEL_ALL:Student desk 5"
  "OPS01:ADMIN:LEAVE_ALL:Instructor console"
)
MM_GATEWAYS=(
  "MM01:MARKET_MAKER:CANCEL_QUOTES_ONLY:Primary market maker"
  "MM02:MARKET_MAKER:CANCEL_QUOTES_ONLY:Backup market maker"
)
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
  --outstanding-shares IBM:910000000
  --outstanding-shares ADBE:460000000
  --outstanding-shares CRM:970000000
  --outstanding-shares QCOM:1690000000
  --outstanding-shares AMD:1620000000
  --outstanding-shares AVGO:4700000000
  --outstanding-shares TXN:910000000
  --outstanding-shares NOW:205000000
  --outstanding-shares SHOP:1320000000
  --outstanding-shares UBER:2130000000
  --outstanding-shares PYPL:1080000000
  --outstanding-shares SQ:600000000
  --outstanding-shares BABA:2200000000
  --outstanding-shares SONY:1240000000
  --outstanding-shares SAP:1150000000
  --outstanding-shares ASML:415000000
  --outstanding-shares CSCO:4060000000
  --outstanding-shares MU:1100000000
  --outstanding-shares BKNG:44000000
  --outstanding-shares TSM:5180000000
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
SPECIFIC_ARGS=(
  --sessions-enabled
  --schedule
  --pre-open 08:45
  --opening-auction 08:55
  --continuous 09:00
  --closing-auction 16:00
  --closing-end 16:10
  --snapshot-interval 0.25
  --quote-history-maxlen 30
  --drop-copy-buffer-size 10000
  --recent-trades-maxlen 20
  --depth-snapshot-tolerance-ticks 100
  --static-band 0.20
  --dynamic-band 0.02
  --risk-level CORE:0.18:0.02
  --risk-level HIGH_BETA:0.12:0.04
  --cb-levels L1:0.07:5 L2:0.13:15 L3:0.20:0
  --cb-window-ns 300000000000
  --mm-spread-ticks 12
  --mm-min-qty 200
  --enforce-mm-obligations
  --tick-decimals 2
  --symbol-opts AAPL:level=CORE,mm_spread_ticks=8,mm_min_qty=300
  --symbol-opts TSLA:level=HIGH_BETA,dynamic_band=0.04,cb_halt_l1=10
  --post-trade-gateway
  --post-trade-name ralf-gwy01
  --post-trade-bind-address 127.0.0.1
  --post-trade-port 5580
  --post-trade-replay-retention-sec 14400
  --post-trade-heartbeat-interval-sec 1
  --post-trade-idle-timeout-sec 10
  --post-trade-max-client-queue 8000
  --post-trade-allowed-roles CLEARING DROP_COPY AUDIT
  --market-data-gateway
  --market-data-enabled
  --market-data-name md-gwy01
  --market-data-bind-address 127.0.0.1
  --market-data-port 5570
  --market-data-heartbeat-interval-sec 1
  --market-data-idle-timeout-sec 5
  --market-data-replay-window-sec 120
  --market-data-max-symbols-per-client 500
  --market-data-max-client-queue 20000
)

# Pass 1: generate base config to obtain seeded MM quote / last-price values.
"${CONFIG_GEN[@]}" "${COMMON_ARGS[@]}" "${SPECIFIC_ARGS[@]}"

# Extract integer tick prices from the seeded last_buy_price fields
# (tick_decimals=2, so display price × 100 gives integer ticks).
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

if [[ -z "$combo_price_a" || -z "$combo_price_b" ]]; then
  echo "Error: failed to extract seeded prices from engine_config.yaml" >&2
  exit 1
fi

# Pass 2: regenerate with --combo so pm-config-gen validates the combo entry.
# The same seed guarantees identical MM quote prices in both passes.
"${CONFIG_GEN[@]}" "${COMMON_ARGS[@]}" "${SPECIFIC_ARGS[@]}" \
  --combo "SEED-PAIR-${combo_a}-${combo_b}:AON:DAY:${combo_a}/BUY/LIMIT/100/${combo_price_a},${combo_b}/SELL/LIMIT/100/${combo_price_b}"

echo "Generated $(pwd)/engine_config.yaml"

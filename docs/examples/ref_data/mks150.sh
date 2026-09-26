#!/usr/bin/env bash
set -euo pipefail

setup_dir="${1:?usage: mks150.sh SETUP_DIR [--seed INTEGER]}"
shift
cd "$setup_dir"

case "$(basename "$setup_dir")" in
  s150-basic-setup) profile=basic; seed_quotes=true ;;
  s150-basic-nomm-setup) profile=basic; seed_quotes=false ;;
  s150-nominal-setup) profile=nominal; seed_quotes=true ;;
  s150-nominal-nomm-setup) profile=nominal; seed_quotes=false ;;
  s150-complex-setup) profile=complex; seed_quotes=true ;;
  s150-complex-nomm-setup) profile=complex; seed_quotes=false ;;
  *) echo "Error: unsupported s150 setup: $setup_dir" >&2; exit 1 ;;
esac

seed=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --seed) seed="${2:?Error: --seed requires an integer argument}"; shift 2 ;;
    --seed=*) seed="${1#*=}"; shift ;;
    -h|--help) echo "Usage: $0 SETUP_DIR [--seed INTEGER]"; exit 0 ;;
    *) echo "Error: unknown argument: $1" >&2; exit 1 ;;
  esac
done
if [[ -n "$seed" && ! "$seed" =~ ^-?[0-9]+$ ]]; then
  echo "Error: --seed must be an integer" >&2
  exit 1
fi
if [[ -z "$seed" ]]; then
  seed=$(( RANDOM * 32768 + RANDOM ))
  echo "[INFO] Auto-generated seed $seed -- re-run with --seed $seed for identical output." >&2
fi

if command -v pm-config-gen >/dev/null 2>&1; then
  config_gen=(pm-config-gen)
elif command -v poetry >/dev/null 2>&1; then
  config_gen=(poetry run pm-config-gen)
else
  echo "Error: neither pm-config-gen nor poetry is available in PATH" >&2
  exit 1
fi

symbols=(
  AAPL MSFT TSLA AMZN GOOGL META NVDA NFLX INTC ORCL IBM ADBE CRM QCOM AMD
  AVGO TXN NOW SHOP UBER PYPL SQ BABA SONY SAP ASML CSCO MU BKNG TSM JPM BAC
  WFC C GS MS V MA AXP BLK SCHW WMT COST TGT HD LOW NKE SBUX MCD KO PEP PG CL
  EL JNJ PFE MRK ABBV LLY BMY AMGN GILD CVS UNH CI HUM ISRG MDT XOM CVX COP
  SLB EOG OXY MPC VLO PSX KMI BA CAT DE GE HON LMT RTX NOC UPS FDX UNP CSX DIS
  CMCSA T VZ TMUS SPOT ROKU PANW CRWD SNOW PLTR DDOG NET MDB TEAM ZS FTNT INTU
  ADP PAYX FIS FI ABNB MAR HLT DAL UAL AAL RCL CCL F GM TM HMC RIVN LCID NEE
  DUK SO AEP EXC XEL SRE LIN APD SHW FCX NEM NUE PLD AMT CCI EQIX SPG O PSA
  REG DLR WELL CB
)

gateways=(
  "TRADER01:TRADER:CANCEL_ALL:Student desk 1"
  "TRADER02:TRADER:CANCEL_ALL:Student desk 2"
  "OPS01:ADMIN:LEAVE_ALL:Instructor console"
  "MM01:MARKET_MAKER:CANCEL_QUOTES_ONLY:Primary market maker"
)
desk_gateways="TRADER01,TRADER02,MM01,OPS01"
if [[ "$profile" == complex ]]; then
  gateways=(
    "TRADER01:TRADER:CANCEL_ALL:Student desk 1"
    "TRADER02:TRADER:CANCEL_ALL:Student desk 2"
    "TRADER03:TRADER:CANCEL_ALL:Student desk 3"
    "TRADER04:TRADER:CANCEL_ALL:Student desk 4"
    "TRADER05:TRADER:CANCEL_ALL:Student desk 5"
    "OPS01:ADMIN:LEAVE_ALL:Instructor console"
    "MM01:MARKET_MAKER:CANCEL_QUOTES_ONLY:Primary market maker"
    "MM02:MARKET_MAKER:CANCEL_QUOTES_ONLY:Backup market maker"
  )
  desk_gateways="TRADER01,TRADER02,TRADER03,TRADER04,TRADER05,MM01,MM02,OPS01"
fi

outstanding_args=()
for index in "${!symbols[@]}"; do
  outstanding_args+=(--outstanding-shares "${symbols[$index]}:$((500000000 + index * 10000000))")
done

common_args=(
  --symbols "${symbols[@]}"
  --gateways "${gateways[@]}"
  --output engine_config.yaml
  --force
  --comment-default-config-fields
  --seed "$seed"
  "${outstanding_args[@]}"
  --api-gateway-instance "desk:${desk_gateways}:8080"
  --api-gateway-instance dashboards::8081
  --api-gateway-readonly-key
)
if [[ "$seed_quotes" == true ]]; then
  common_args+=(--seed-mm-mid-range 20:300 --seed-last-prices-from-mm)
else
  common_args+=(--no-mm-seed-quotes)
fi

gateway_args=(
  --post-trade-gateway
  --post-trade-bind-address 0.0.0.0
  --post-trade-port 5580
  --post-trade-replay-retention-sec 3600
  --post-trade-heartbeat-interval-sec 1
  --post-trade-idle-timeout-sec 10
  --post-trade-max-client-queue 5000
  --post-trade-allowed-roles CLEARING DROP_COPY AUDIT
  --market-data-gateway
  --market-data-enabled
  --market-data-name md-gwy01
  --market-data-bind-address 0.0.0.0
  --market-data-port 5570
  --market-data-heartbeat-interval-sec 1
  --market-data-idle-timeout-sec 5
  --market-data-replay-window-sec 30
  --market-data-max-symbols-per-client 200
  --market-data-max-client-queue 10000
)

case "$profile" in
  basic)
    "${config_gen[@]}" "${common_args[@]}" --no-collars --no-circuit-breakers "${gateway_args[@]}"
    ;;
  nominal)
    "${config_gen[@]}" "${common_args[@]}" --sessions-enabled "${gateway_args[@]}"
    ;;
  complex)
    complex_args=(
      --sessions-enabled --schedule
      --pre-open 08:45 --opening-auction 08:55 --continuous 09:00
      --closing-auction 16:00 --closing-end 16:10
      --snapshot-interval 0.25 --quote-history-maxlen 30
      --drop-copy-buffer-size 10000 --recent-trades-maxlen 20
      --depth-snapshot-tolerance-ticks 100 --static-band 0.20 --dynamic-band 0.02
      --risk-level CORE:0.18:0.02 --risk-level HIGH_BETA:0.12:0.04
      --cb-levels L1:0.07:5 L2:0.13:15 L3:0.20:0
      --cb-window-ns 300000000000 --mm-spread-ticks 12 --mm-min-qty 200
      --enforce-mm-obligations --tick-decimals 2
      --symbol-opts AAPL:level=CORE,mm_spread_ticks=8,mm_min_qty=300
      --symbol-opts TSLA:level=HIGH_BETA,dynamic_band=0.04,cb_halt_l1=10
      --post-trade-gateway --post-trade-name ralf-gwy01
      --post-trade-bind-address 0.0.0.0 --post-trade-port 5580
      --post-trade-replay-retention-sec 14400 --post-trade-heartbeat-interval-sec 1
      --post-trade-idle-timeout-sec 10 --post-trade-max-client-queue 8000
      --post-trade-allowed-roles CLEARING DROP_COPY AUDIT
      --market-data-gateway --market-data-enabled --market-data-name md-gwy01
      --market-data-bind-address 0.0.0.0 --market-data-port 5570
      --market-data-heartbeat-interval-sec 1 --market-data-idle-timeout-sec 5
      --market-data-replay-window-sec 120 --market-data-max-symbols-per-client 500
      --market-data-max-client-queue 20000
    )
    combo_a="${symbols[0]}"
    combo_b="${symbols[1]}"
    if [[ "$seed_quotes" == true ]]; then
      "${config_gen[@]}" "${common_args[@]}" "${complex_args[@]}"
      combo_price_a="$(awk -v symbol="$combo_a" '$0 == "symbols:" { found = 1; next } found && $0 ~ /^  [A-Z0-9_.-]+:$/ { current = $1; sub(/:$/, "", current); next } found && current == symbol && $1 == "last_buy_price:" { print $2; exit }' engine_config.yaml)"
      combo_price_b="$(awk -v symbol="$combo_b" '$0 == "symbols:" { found = 1; next } found && $0 ~ /^  [A-Z0-9_.-]+:$/ { current = $1; sub(/:$/, "", current); next } found && current == symbol && $1 == "last_buy_price:" { print $2; exit }' engine_config.yaml)"
    else
      combo_price_a=150.00
      combo_price_b=150.00
    fi
    "${config_gen[@]}" "${common_args[@]}" "${complex_args[@]}" \
      --combo "SEED-PAIR-${combo_a}-${combo_b}:AON:DAY:${combo_a}/BUY/LIMIT/100/${combo_price_a},${combo_b}/SELL/LIMIT/100/${combo_price_b}"
    ;;
esac

echo "Generated $(pwd)/engine_config.yaml"
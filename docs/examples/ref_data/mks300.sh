#!/usr/bin/env bash
# Generates the s300-load example: the design-limit test bed for the AI
# traders (300 symbols, 500 AI participants). See
# docs-design/EduMatcher-AI-Traders-v3-Plan.md, WP-A3.
set -euo pipefail

setup_dir="${1:?usage: mks300.sh SETUP_DIR [--seed INTEGER]}"
shift
cd "$setup_dir"

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

# The 150 s150 tickers followed by 150 more, so s150 sector data carries over.
symbols=(
  AAPL MSFT TSLA AMZN GOOGL META NVDA NFLX INTC ORCL IBM ADBE CRM QCOM AMD AVGO
  TXN NOW SHOP UBER PYPL SQ BABA SONY SAP ASML CSCO MU BKNG TSM JPM BAC WFC C
  GS MS V MA AXP BLK SCHW WMT COST TGT HD LOW NKE SBUX MCD KO PEP PG CL EL JNJ
  PFE MRK ABBV LLY BMY AMGN GILD CVS UNH CI HUM ISRG MDT XOM CVX COP SLB EOG OXY
  MPC VLO PSX KMI BA CAT DE GE HON LMT RTX NOC UPS FDX UNP CSX DIS CMCSA T VZ
  TMUS SPOT ROKU PANW CRWD SNOW PLTR DDOG NET MDB TEAM ZS FTNT INTU ADP PAYX FIS
  FI ABNB MAR HLT DAL UAL AAL RCL CCL F GM TM HMC RIVN LCID NEE DUK SO AEP EXC
  XEL SRE LIN APD SHW FCX NEM NUE PLD AMT CCI EQIX SPG O PSA REG DLR WELL CB ACN
  ADI ADSK AFL AIG AJG ALB ALL AMAT AME AMP ANET AON APH ARE ATO AVB AWK AZO BAX
  BBY BDX BIIB BK BKR BR BRO BSX BX CAH CARR CDNS CDW CEG CF CHD CHTR CINF CLX
  CMG CME CMI CMS CNC COF CPRT CSGP CTAS CTSH CTVA D DD DG DHI DHR DLTR DOV DOW
  DPZ DRI DTE DVN DXCM EA EBAY ECL ED EFX EIX EMR ENPH EPAM ES ETN ETR EW EXPD
  EXPE FANG FAST FICO FITB FSLR GD GEHC GIS GLW GPC GPN GRMN GWW HAL HAS HBAN
  HCA HES HIG HPE HPQ HSY HUBB IDXX IFF ILMN INCY IP IQV IR IRM IT ITW JBHT JCI
  K KDP KEY KHC KLAC KMB KR LEN LH LHX LRCX LULU LVS LYB MAA MCHP MCK MCO MDLZ
  MET MGM MKC MLM MMC MMM MNST MO MOS MRNA MSCI MSI MTB MTD NDAQ NOV NRG NSC
)

participants=()
trader_ids=()
for n in $(seq 1 10); do
  trader_id=$(printf 'TRADER%02d' "$n")
  participants+=("${trader_id}:TRADER:CANCEL_ALL:Student desk ${n}")
  trader_ids+=("$trader_id")
done
participants+=(
  "OPS01:ADMIN:LEAVE_ALL:Instructor console"
  "MM01:MARKET_MAKER:CANCEL_QUOTES_ONLY:Primary market maker"
  "MM02:MARKET_MAKER:CANCEL_QUOTES_ONLY:Backup market maker"
)
for n in $(seq 1 500); do
  participants+=("$(printf 'AI%03d' "$n"):TRADER:CANCEL_ALL:AI trader ${n}")
done
trader_list=$(IFS=,; echo "${trader_ids[*]}")

outstanding_args=()
for index in "${!symbols[@]}"; do
  outstanding_args+=(--outstanding-shares "${symbols[$index]}:$((500000000 + index * 10000000))")
done

"${config_gen[@]}" \
  --symbols "${symbols[@]}" \
  --participants "${participants[@]}" \
  --participant-default-smp CANCEL_AGGRESSOR \
  --output engine_config.yaml \
  --force \
  --comment-default-config-fields \
  --seed "$seed" \
  "${outstanding_args[@]}" \
  --api-gateway-instance "desk:${trader_list},MM01,MM02,OPS01:8080" \
  --api-gateway-instance dashboards::8081 \
  --api-gateway-readonly-key \
  --seed-mm-mid-range 20:300 --mm-seed-spread-ticks 10 --seed-last-prices-from-mm \
  --enforce-mm-obligations \
  --no-collars \
  --sessions-enabled \
  --market-data-gateway --market-data-enabled --market-data-name md-gwy01 \
  --market-data-bind-address 0.0.0.0 --market-data-port 5570 \
  --market-data-heartbeat-interval-sec 1 --market-data-idle-timeout-sec 5 \
  --market-data-replay-window-sec 30 --market-data-max-symbols-per-client 300 \
  --market-data-max-client-queue 20000

echo "Generated $(pwd)/engine_config.yaml"

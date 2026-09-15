#!/usr/bin/env bash
# verify_matching.sh — End-to-end deterministic matching-engine verification.
#
# What it does
# ------------
#   1. Generates mm_orders.fix, test_orders.fix and paper_result.json
#      (the "golden" expected result from the pure-Python paper trader).
#   2. Starts a clean engine instance with verify_engine_config.yaml.
#   3. Replays every order through the engine and collects engine_result.json.
#   4. Compares the two results and exits 0 on full agreement, 1 on any diff.
#
# Run with --help for the full option list.
#
# Requires: poetry environment set up (poetry install --with dev)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VERIFY_DIR="$REPO_ROOT/data/verify"

SEED=42
COUNT=10000
TOLERANCE=0
SKIP_GEN=false
ENGINE_PULL="tcp://localhost:5555"
ENGINE_PUB="tcp://localhost:5556"

usage() {
  cat <<'EOF'
Usage: verify_matching.sh [OPTIONS]

End-to-end deterministic verification of the matching engine. Generates a
seeded order flow, paper-trades it in pure Python, replays the same flow
through a real pm-engine, and compares the two resulting order books. Any
difference is an engine defect: the paper trader is the specification.

Options:
  --seed N          Seed for the generated dataset (default: 42). The whole
                    run is deterministic in this seed -- the same seed always
                    produces the same orders, amendments and cancellations.
  --count N         Test lines to generate (default: 10000). Roughly 70% new
                    orders, 30% amendments and cancellations of orders still
                    resting from earlier in the same flow.
  --tolerance F     Relative quantity tolerance in the comparison
                    (default: 0, meaning exact agreement).
  --skip-gen        Reuse the dataset already in data/verify/ instead of
                    regenerating it. Fails if it is not there.
  --pull ADDR       Engine order-entry (PULL) address
                    (default: tcp://localhost:5555).
  --pub ADDR        Engine market-data (PUB) address
                    (default: tcp://localhost:5556).
  -h, --help        Show this help and exit.

Steps:
  1  Generate mm_orders.fix, test_orders.fix and paper_result.json.
  2  Deploy the verification config and start a clean engine.
  3  Replay every line through it and collect engine_result.json.
  4  Stop the engine.
  5  Compare paper against engine, per symbol.

Files, all under data/verify/:
  mm_orders.fix              market-maker seed orders, sent first
  test_orders.fix            the flow under test
  verify_engine_config.yaml  4 symbols, one gateway, sessions disabled
  paper_result.json          what the paper trader says the books should be
  engine_result.json         what the engine actually produced

Side effects:
  Deploys verify_engine_config.yaml as THE compiled configuration for this
  EDUMATCHER_DATA_DIR, replacing whatever was deployed there. Set that
  variable to a scratch directory to keep an existing configuration.
  Deletes gtc_orders.json, gtc_combos.json and book_stats.json from the
  engine's data directory so the run starts from an empty book.

Exit status:
  0  the engine's books match the paper trader's
  1  they differ, or the run could not be completed

Examples:
  ./verify_matching.sh                    # 10 000 lines, seed 42
  ./verify_matching.sh --count 500        # a quick pass
  ./verify_matching.sh --seed 7           # a different flow
  ./verify_matching.sh --skip-gen         # re-run the last dataset
  ./verify_matching.sh --tolerance 0.01   # allow 1% quantity drift

Requires: poetry install --with dev
EOF
}

# Parse optional arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --seed)       SEED="$2";      shift 2 ;;
    --count)      COUNT="$2";     shift 2 ;;
    --tolerance)  TOLERANCE="$2"; shift 2 ;;
    --skip-gen)   SKIP_GEN=true;  shift   ;;
    --pull)       ENGINE_PULL="$2"; shift 2 ;;
    --pub)        ENGINE_PUB="$2";  shift 2 ;;
    -h|--help)    usage; exit 0 ;;
    *)
      echo "verify_matching.sh: unknown option: $1" >&2
      echo "Try 'verify_matching.sh --help'." >&2
      exit 1
      ;;
  esac
done

ENGINE_PID=""

cleanup() {
  if [[ -n "$ENGINE_PID" ]]; then
    echo ""
    echo "[VERIFY] Stopping engine (PID $ENGINE_PID) …"
    kill "$ENGINE_PID" 2>/dev/null || true
    wait "$ENGINE_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

header() { echo ""; echo "━━━  $*  ━━━"; }

# ── Step 1: Generate FIX files and paper trade result ───────────────────────
if [[ "$SKIP_GEN" == "false" ]]; then
  header "STEP 1 — Generate verification dataset (seed=$SEED, count=$COUNT)"
  cd "$REPO_ROOT"
  poetry run python tools/gen_verification_set.py --seed "$SEED" --count "$COUNT"
else
  header "STEP 1 — Skipping generation (--skip-gen)"
  for f in mm_orders.fix test_orders.fix paper_result.json; do
    if [[ ! -f "$VERIFY_DIR/$f" ]]; then
      echo "[VERIFY] ERROR: $VERIFY_DIR/$f not found; run without --skip-gen first."
      exit 1
    fi
  done
fi

# ── Step 2: Start a clean engine ────────────────────────────────────────────
header "STEP 2 — Start matching engine"

# Remove stale GTC persistence so each run starts from a clean state.
# Ask config.py where that is rather than assuming: DATA_DIR is src/data in a
# source checkout, ~/.local/share/edumatcher when installed, and whatever
# EDUMATCHER_DATA_DIR says if it is set. This used to delete $REPO_ROOT/data,
# which in a source checkout is not the engine's data directory at all -- so
# the run it promises is clean inherited the previous run's resting orders.
DATA_DIR="$(poetry run python -c 'from edumatcher.config import DATA_DIR; print(DATA_DIR)')"
echo "[VERIFY] Engine data directory: $DATA_DIR"
rm -f "$DATA_DIR/gtc_orders.json" \
      "$DATA_DIR/gtc_combos.json" \
      "$DATA_DIR/book_stats.json"

echo "[VERIFY] Deploying verify_engine_config.yaml …"
cd "$REPO_ROOT"
# No process takes a config path any more, so the verification config has to
# be installed as the deployed one first. This replaces whatever was deployed
# for this EDUMATCHER_DATA_DIR — set that variable to a scratch directory if
# you need to keep an existing configuration.
poetry run pm-config-deploy data/verify/verify_engine_config.yaml

echo "[VERIFY] Starting engine …"
poetry run pm-engine &
ENGINE_PID=$!

# Wait for the engine to bind its sockets
echo "[VERIFY] Waiting for engine to bind (2 s) …"
sleep 2

# Sanity-check: make sure the process is still alive
if ! kill -0 "$ENGINE_PID" 2>/dev/null; then
  echo "[VERIFY] ERROR: engine exited prematurely."
  exit 1
fi
echo "[VERIFY] Engine PID=$ENGINE_PID is running."

# ── Step 3: Replay orders through the engine ────────────────────────────────
header "STEP 3 — Replay orders to engine"
cd "$REPO_ROOT"
poetry run python tools/replay_to_engine.py --pull "$ENGINE_PULL" --pub "$ENGINE_PUB"

# ── Step 4: Stop engine ─────────────────────────────────────────────────────
header "STEP 4 — Shut down engine"
echo "[VERIFY] Sending SIGINT to engine …"
kill -INT "$ENGINE_PID" 2>/dev/null || true
wait "$ENGINE_PID" 2>/dev/null || true
ENGINE_PID=""

# ── Step 5: Compare results ──────────────────────────────────────────────────
header "STEP 5 — Compare paper vs engine"
cd "$REPO_ROOT"
if poetry run python tools/compare_results.py --tolerance "$TOLERANCE"; then
  echo ""
  echo "✓  Verification PASSED — engine output matches paper trade."
  exit 0
else
  echo ""
  echo "✗  Verification FAILED — see diffs above."
  exit 1
fi

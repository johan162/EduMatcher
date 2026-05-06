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
# Usage
# -----
#   ./verify_matching.sh                     # 1 000 orders, seed 42
#   ./verify_matching.sh --seed 7            # different random seed
#   ./verify_matching.sh --count 500         # fewer test orders
#   ./verify_matching.sh --tolerance 0.01    # allow 1% qty rounding in compare
#   ./verify_matching.sh --skip-gen          # reuse existing .fix files
#
# Requires: poetry environment set up (poetry install --with dev)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VERIFY_DIR="$REPO_ROOT/data/verify"

SEED=42
COUNT=1000
TOLERANCE=0
SKIP_GEN=false
ENGINE_PULL="tcp://localhost:5555"
ENGINE_PUB="tcp://localhost:5556"

# Parse optional arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --seed)       SEED="$2";      shift 2 ;;
    --count)      COUNT="$2";     shift 2 ;;
    --tolerance)  TOLERANCE="$2"; shift 2 ;;
    --skip-gen)   SKIP_GEN=true;  shift   ;;
    --pull)       ENGINE_PULL="$2"; shift 2 ;;
    --pub)        ENGINE_PUB="$2";  shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
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

# Remove stale GTC persistence so each run starts from a clean state
rm -f "$REPO_ROOT/data/gtc_orders.json" \
      "$REPO_ROOT/data/gtc_combos.json" \
      "$REPO_ROOT/data/book_stats.json"

echo "[VERIFY] Starting engine with verify_engine_config.yaml …"
cd "$REPO_ROOT"
poetry run pm-engine --config data/verify/verify_engine_config.yaml &
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

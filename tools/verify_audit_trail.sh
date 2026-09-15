#!/usr/bin/env bash
# verify_audit_trail.sh — record a verification run and check the trail reads clean.
#
# What it does
# ------------
#   1. Starts pm-audit, which subscribes to the engine's PUB feed and writes
#      the audit trail.
#   2. Runs verify_matching.sh, which generates a dataset, starts an engine,
#      replays the dataset through it and compares the books.
#   3. Stops pm-audit and lets it flush.
#   4. Runs `pm-audit-replay anomalies --severity warn` over the trail that run
#      produced. Any finding at warn or error fails the script.
#
# Why it is a separate script
# ---------------------------
# verify_matching.sh answers "does the engine match?"; this answers "and does
# the trail it left say so?". They are different questions and the second needs
# a recorder process the first has no use for. Wrapping keeps verify_matching.sh
# exactly as it was.
#
# pm-audit starts BEFORE the engine on purpose. A SUB socket that joins after
# a PUB has started sending misses what came first, and the engine publishes
# its startup recovery the moment it is up.
#
# Usage
# -----
#   ./verify_audit_trail.sh                  # 10 000 lines, seed 42
#   ./verify_audit_trail.sh --count 2000     # passed through to verify_matching.sh
#
# Requires: poetry environment set up (poetry install --with dev)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Ask config.py where the trail lands rather than assuming: DATA_DIR is
# src/data in a source checkout and ~/.local/share/edumatcher when installed.
DATA_DIR="$(poetry run python -c 'from edumatcher.config import DATA_DIR; print(DATA_DIR)')"
AUDIT_LOG="$DATA_DIR/audit.log"

AUDIT_PID=""

cleanup() {
  if [[ -n "$AUDIT_PID" ]]; then
    kill -INT "$AUDIT_PID" 2>/dev/null || true
    wait "$AUDIT_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

header() { echo ""; echo "━━━  $*  ━━━"; }

header "STEP A — Start the audit recorder"
mkdir -p "$DATA_DIR"
# Start from an empty trail, or the findings below would be about whatever
# some previous run left behind.
: > "$AUDIT_LOG"
echo "[AUDIT] Trail: $AUDIT_LOG"
poetry run pm-audit --audit-log-file "$AUDIT_LOG" &
AUDIT_PID=$!
sleep 1
if ! kill -0 "$AUDIT_PID" 2>/dev/null; then
  echo "[AUDIT] ERROR: pm-audit exited immediately."
  exit 1
fi
echo "[AUDIT] pm-audit PID=$AUDIT_PID is recording."

header "STEP B — Run the matching verification"
"$SCRIPT_DIR/verify_matching.sh" "$@"

header "STEP C — Stop the recorder and flush"
kill -INT "$AUDIT_PID" 2>/dev/null || true
wait "$AUDIT_PID" 2>/dev/null || true
AUDIT_PID=""
LINES="$(wc -l < "$AUDIT_LOG" | tr -d ' ')"
echo "[AUDIT] Recorded $LINES line(s)."
if [[ "$LINES" -eq 0 ]]; then
  echo "[AUDIT] ERROR: the trail is empty — pm-audit recorded nothing."
  exit 1
fi

header "STEP D — Reconstruct the trail and look for anomalies"
# --no-index: this trail is written once and read once, so building an index
# for it would only leave a database behind.
REPORT="$(poetry run pm-audit-replay --log-file "$AUDIT_LOG" --no-index \
            anomalies --severity warn)"
echo "$REPORT"

if grep -q "^No findings" <<<"$REPORT"; then
  echo ""
  echo "✓  Audit trail verification PASSED — nothing at warn or above."
  exit 0
fi

echo ""
echo "✗  Audit trail verification FAILED — see the findings above."
echo "   Each one prints the story command that shows it."
exit 1

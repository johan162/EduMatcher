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
# Run with --help for the full option list.
#
# Requires: poetry environment set up (poetry install --with dev)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

usage() {
  cat <<'EOF'
Usage: verify_audit_trail.sh [OPTIONS]

Records a verification run with pm-audit and checks that the trail it leaves
reads clean. verify_matching.sh answers "does the engine match?"; this answers
"and does the trail it left say so?".

Every option is the one verify_matching.sh takes, and is passed straight
through to it:

  --seed N          Seed for the generated dataset (default: 42).
  --count N         Test lines to generate (default: 10000).
  --tolerance F     Relative quantity tolerance in the comparison
                    (default: 0, meaning exact agreement).
  --skip-gen        Reuse the dataset already in data/verify/.
  --pull ADDR       Engine order-entry (PULL) address
                    (default: tcp://localhost:5555).
  --pub ADDR        Engine market-data (PUB) address
                    (default: tcp://localhost:5556).
  -h, --help        Show this help and exit.

They are validated here, before the recorder starts, so a typo costs nothing.
Run `verify_matching.sh --help` for what each one does to the run itself.

Steps:
  A  Start pm-audit, which subscribes to the engine's PUB feed and writes the
     trail. It starts BEFORE the engine on purpose: a SUB socket joining after
     a PUB has begun sending misses what came first, and the engine publishes
     its startup recovery the moment it is up.
  B  Run verify_matching.sh, unchanged, with the options given here.
  C  Stop the recorder and let it flush.
  D  Run `pm-audit-replay anomalies --severity warn` over the trail. Any
     finding at warn or error fails the script.

The trail:
  Written to <DATA_DIR>/audit.log, where DATA_DIR is what config.py reports --
  src/data in a source checkout, ~/.local/share/edumatcher when installed, or
  whatever EDUMATCHER_DATA_DIR says. pm-audit rotates at 10 MiB and a
  10 000-order run is about 28 MB, so it leaves audit.log.1 and audit.log.2
  beside it, and pm-audit-replay reads the whole rotated set.

  STEP A therefore deletes the active file AND its rotated segments. Anything
  left there from a previous run would otherwise be replayed alongside this
  one, and because the dataset is seeded both runs carry the same order ids:
  every order looks accepted twice and its fills look doubled.

  So this run replaces whatever audit history is in that directory. Point
  EDUMATCHER_DATA_DIR at a scratch directory if you need to keep it.

Exit status:
  0  no findings at warn or above
  1  findings, or the run could not be completed

Examples:
  ./verify_audit_trail.sh                 # 10 000 lines, seed 42
  ./verify_audit_trail.sh --count 2000    # a quicker pass
  ./verify_audit_trail.sh --seed 7        # a different flow

Requires: poetry install --with dev
EOF
}

# Validate before anything is started, and keep the arguments verbatim for
# verify_matching.sh. Discovering a typo in STEP B would mean tearing down a
# recorder that has only just been spawned -- which is how `--help` used to
# hang: a background job in a non-interactive shell inherits SIGINT ignored,
# and the signal arrived before pm-audit had installed its own handler.
#
# The option list mirrors verify_matching.sh's; that script is the authority
# on what each one means, and `--help` above says so rather than restating it.
VERIFY_ARGS=()
while [[ $# -gt 0 ]]; do
  case $1 in
    --seed|--count|--tolerance|--pull|--pub)
      if [[ $# -lt 2 ]]; then
        echo "verify_audit_trail.sh: $1 needs a value" >&2
        exit 1
      fi
      VERIFY_ARGS+=("$1" "$2"); shift 2 ;;
    --skip-gen)   VERIFY_ARGS+=("$1"); shift ;;
    -h|--help)    usage; exit 0 ;;
    *)
      echo "verify_audit_trail.sh: unknown option: $1" >&2
      echo "Try 'verify_audit_trail.sh --help'." >&2
      exit 1
      ;;
  esac
done

# Ask config.py where the trail lands rather than assuming: DATA_DIR is
# src/data in a source checkout and ~/.local/share/edumatcher when installed.
DATA_DIR="$(poetry run python -c 'from edumatcher.config import DATA_DIR; print(DATA_DIR)')"
AUDIT_LOG="$DATA_DIR/audit.log"

AUDIT_PID=""

cleanup() {
  if [[ -n "$AUDIT_PID" ]]; then
    # SIGTERM, not SIGINT. Bash sets SIGINT to ignore in a background job of a
    # non-interactive shell, and pm-audit only overrides that once its own
    # handler is installed -- so a SIGINT during its first second is discarded
    # and the `wait` below never returns. It handles SIGTERM identically, and
    # before the handler exists SIGTERM still terminates.
    kill -TERM "$AUDIT_PID" 2>/dev/null || true
    wait "$AUDIT_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

header() { echo ""; echo "━━━  $*  ━━━"; }

header "STEP A — Start the audit recorder"
mkdir -p "$DATA_DIR"
# Start from an empty trail, or the findings below would be about whatever
# some previous run left behind.
#
# The ROTATED segments have to go too. pm-audit writes through a
# RotatingFileHandler (10 MiB, 5 backups) and a 10 000-order run is about
# 28 MB, so one run leaves audit.log plus audit.log.1 and audit.log.2 — while
# pm-audit-replay reads the whole rotated set, not just the active file
# (`discover_log_files`). Truncating audit.log alone therefore left the
# previous run's first 22 000 lines in place to be replayed alongside this
# one's. The dataset is seeded, so both runs carry the SAME order ids: every
# one of them looked accepted twice and its fills looked doubled. 1073
# findings, none of them real.
rm -f "$AUDIT_LOG" "$AUDIT_LOG".*
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
"$SCRIPT_DIR/verify_matching.sh" ${VERIFY_ARGS[@]+"${VERIFY_ARGS[@]}"}

header "STEP C — Stop the recorder and flush"
kill -TERM "$AUDIT_PID" 2>/dev/null || true
wait "$AUDIT_PID" 2>/dev/null || true
AUDIT_PID=""
# Across every segment, for the same reason STEP A deletes them all: this is
# what STEP D is about to read, and counting only the active file under-reports
# a rotated run by several times.
LINES="$(cat "$AUDIT_LOG" "$AUDIT_LOG".* 2>/dev/null | wc -l | tr -d ' ')"
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

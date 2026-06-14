#!/usr/bin/env bash
# launch_all.sh — Open every EduMatcher process in its own Terminal window.
#
# Works in two modes:
#   • Installed (pipx install edumatcher): pm-* commands are on PATH.
#   • Developer (source checkout): if pm-engine is not on PATH, falls back to
#     "poetry run pm-engine" automatically.
#
# Usage:
#   ./launch_all.sh                    # viewer watches MSFT (default)
#   ./launch_all.sh AAPL               # viewer watches a different symbol
#   ./launch_all.sh AAPL MSFT GOOGL   # open one viewer per symbol
#
# Environment:
#   EDUMATCHER_DATA_DIR   Override the data directory (default: ~/.local/share/edumatcher
#                         or src/data/ when running from a source checkout)
#   EDUMATCHER_CONFIG     Override the engine config path (default: ./engine_config.yaml)

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SYMBOLS=("${@:-MSFT}")

# ---------------------------------------------------------------------------
# Determine how to invoke pm-* commands
# ---------------------------------------------------------------------------
if command -v pm-engine &>/dev/null; then
    RUN=""         # installed — bare command names work
else
    # Fall back to poetry run if we are in a source checkout
    if command -v poetry &>/dev/null && [ -f "$DIR/../pyproject.toml" ]; then
        RUN="poetry run"
        echo "ℹ  pm-engine not found on PATH; using 'poetry run' (source mode)"
    else
        echo "✗  pm-engine not found. Install EduMatcher first:" >&2
        echo "     pipx install edumatcher" >&2
        echo "   or from source:" >&2
        echo "     poetry install" >&2
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Export data/config locations so every spawned window inherits them
# ---------------------------------------------------------------------------
if [ -n "${EDUMATCHER_DATA_DIR:-}" ]; then
    export EDUMATCHER_DATA_DIR
    echo "ℹ  EDUMATCHER_DATA_DIR=${EDUMATCHER_DATA_DIR}"
fi
if [ -n "${EDUMATCHER_CONFIG:-}" ]; then
    export EDUMATCHER_CONFIG
    echo "ℹ  EDUMATCHER_CONFIG=${EDUMATCHER_CONFIG}"
fi

# Open a new macOS Terminal window that runs CMD inside the project directory.
_term() {
    local cmd="$1"
    local env_prefix=""
    [ -n "${EDUMATCHER_DATA_DIR:-}" ] && env_prefix+="EDUMATCHER_DATA_DIR='${EDUMATCHER_DATA_DIR}' "
    [ -n "${EDUMATCHER_CONFIG:-}" ]   && env_prefix+="EDUMATCHER_CONFIG='${EDUMATCHER_CONFIG}' "
    osascript \
        -e "tell application \"Terminal\"" \
        -e "  activate" \
        -e "  do script \"cd '$DIR' && ${env_prefix}${cmd}\"" \
        -e "end tell"
}

VIEWER_COUNT=${#SYMBOLS[@]}
TOTAL=$((10 + VIEWER_COUNT))
echo "Launching EduMatcher — $TOTAL Terminal windows"
echo "  Viewer symbol(s): ${SYMBOLS[*]}  (override: ./launch_all.sh AAPL MSFT …)"
echo ""

_term "${RUN:+$RUN }pm-engine --verbose"
echo "  [1/$TOTAL] Engine started — waiting 1 s for sockets to bind…"
sleep 1

_term "${RUN:+$RUN }pm-scheduler"
echo "  [2/$TOTAL] Session scheduler"
sleep 0.3

_term "${RUN:+$RUN }pm-gateway --id TRADER01"
echo "  [3/$TOTAL] Gateway TRADER01"
sleep 0.3

_term "${RUN:+$RUN }pm-gateway --id TRADER02"
echo "  [4/$TOTAL] Gateway TRADER02"
sleep 0.3

VIEWER_IDX=5
for SYM in "${SYMBOLS[@]}"; do
    _term "${RUN:+$RUN }pm-viewer --symbol $SYM"
    echo "  [$VIEWER_IDX/$TOTAL] Viewer ($SYM)"
    VIEWER_IDX=$((VIEWER_IDX + 1))
    sleep 0.3
done

_term "${RUN:+$RUN }pm-orders"
echo "  [$VIEWER_IDX/$TOTAL] Orders monitor"
VIEWER_IDX=$((VIEWER_IDX + 1))
sleep 0.3

_term "${RUN:+$RUN }pm-audit --terminal"
echo "  [$VIEWER_IDX/$TOTAL] Audit"
VIEWER_IDX=$((VIEWER_IDX + 1))
sleep 0.3

_term "${RUN:+$RUN }pm-clearing"
echo "  [$VIEWER_IDX/$TOTAL] Clearing"
VIEWER_IDX=$((VIEWER_IDX + 1))

_term "${RUN:+$RUN }pm-stats"
echo "  [$VIEWER_IDX/$TOTAL] Statistics"
VIEWER_IDX=$((VIEWER_IDX + 1))

_term "${RUN:+$RUN }pm-ticker --interval 30"
echo "  [$VIEWER_IDX/$TOTAL] Ticker"
VIEWER_IDX=$((VIEWER_IDX + 1))

_term "${RUN:+$RUN }pm-board"
echo "  [$VIEWER_IDX/$TOTAL] Market Board"

echo ""
echo "Done. Switch between Terminal windows to interact with each process."
echo "To stop: Ctrl-C in each window (engine saves GTC orders on exit)."

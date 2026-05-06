#!/usr/bin/env bash
# launch_all.sh — Open every EduMatcher process in its own Terminal window.
#
# Usage:
#   ./launch_all.sh                    # viewer watches MSFT (default)
#   ./launch_all.sh AAPL               # viewer watches a different symbol
#   ./launch_all.sh AAPL MSFT GOOGL   # open one viewer per symbol

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SYMBOLS=("${@:-MSFT}")

# Open a new macOS Terminal window that runs CMD inside the project directory.
_term() {
    local cmd="$1"
    osascript \
        -e "tell application \"Terminal\"" \
        -e "  activate" \
        -e "  do script \"cd '$DIR' && $cmd\"" \
        -e "end tell"
}

VIEWER_COUNT=${#SYMBOLS[@]}
TOTAL=$((10 + VIEWER_COUNT))
echo "Launching EduMatcher — $TOTAL Terminal windows"
echo "  Viewer symbol(s): ${SYMBOLS[*]}  (override: ./launch_all.sh AAPL MSFT …)"
echo ""

_term "poetry run pm-engine --verbose"
echo "  [1/$TOTAL] Engine started — waiting 1 s for sockets to bind…"
sleep 1

_term "poetry run pm-scheduler"
echo "  [2/$TOTAL] Session scheduler"
sleep 0.3

_term "poetry run pm-gateway --id TRADER01"
echo "  [3/$TOTAL] Gateway TRADER01"
sleep 0.3

_term "poetry run pm-gateway --id TRADER02"
echo "  [4/$TOTAL] Gateway TRADER02"
sleep 0.3

VIEWER_IDX=5
for SYM in "${SYMBOLS[@]}"; do
    _term "poetry run pm-viewer --symbol $SYM"
    echo "  [$VIEWER_IDX/$TOTAL] Viewer ($SYM)"
    VIEWER_IDX=$((VIEWER_IDX + 1))
    sleep 0.3
done

_term "poetry run pm-orders"
echo "  [$VIEWER_IDX/$TOTAL] Orders monitor"
VIEWER_IDX=$((VIEWER_IDX + 1))
sleep 0.3

_term "poetry run pm-audit --terminal"
echo "  [$VIEWER_IDX/$TOTAL] Audit"
VIEWER_IDX=$((VIEWER_IDX + 1))
sleep 0.3

_term "poetry run pm-clearing"
echo "  [$VIEWER_IDX/$TOTAL] Clearing"
VIEWER_IDX=$((VIEWER_IDX + 1))

_term "poetry run pm-stats"
echo "  [$VIEWER_IDX/$TOTAL] Statistics"
VIEWER_IDX=$((VIEWER_IDX + 1))

_term "poetry run pm-ticker --interval 30"
echo "  [$VIEWER_IDX/$TOTAL] Ticker"
VIEWER_IDX=$((VIEWER_IDX + 1))

_term "poetry run pm-board"
echo "  [$VIEWER_IDX/$TOTAL] Market Board"

echo ""
echo "Done. Switch between Terminal windows to interact with each process."
echo "To stop: Ctrl-C in each window (engine saves GTC orders on exit)."

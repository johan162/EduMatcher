#!/usr/bin/env bash
# install-runtime.sh — Install EduMatcher for end users (students / instructors).
#
# What this script does:
#   1. Checks that Python 3.13+ is available.
#   2. Ensures pipx is installed (installs it automatically on macOS/Linux).
#   3. Installs (or upgrades) EduMatcher from PyPI via pipx.
#   4. Runs pm-setup to create the data directory and copy a sample config.
#
# Usage:
#   ./scripts/install-runtime.sh           # first install
#   ./scripts/install-runtime.sh --upgrade # upgrade an existing installation
#   ./scripts/install-runtime.sh --help
#
# After this script completes, add the printed environment snippet to your
# shell profile (~/.zshrc or ~/.bashrc), then run pm-engine to start trading.

set -euo pipefail

PACKAGE="edumatcher"
MIN_PYTHON_MINOR=13

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

ok()   { echo -e "${GREEN}  ✓${NC} $*"; }
info() { echo -e "${BLUE}  ℹ${NC} $*"; }
warn() { echo -e "${YELLOW}  ⚠${NC} $*"; }
err()  { echo -e "${RED}  ✗${NC} $*" >&2; }

UPGRADE=false
HELP=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --upgrade) UPGRADE=true; shift ;;
        --help)    HELP=true;    shift ;;
        *) err "Unknown option: $1"; echo "Use --help for usage." >&2; exit 2 ;;
    esac
done

if [ "$HELP" = true ]; then
    cat <<EOF
EduMatcher Runtime Installer

USAGE
  $0 [OPTIONS]

OPTIONS
  --upgrade   Force-reinstall / upgrade an existing pipx installation
  --help      Show this help

ENVIRONMENT
  EDUMATCHER_DATA_DIR   Override the data directory (default: ~/.local/share/edumatcher)
  EDUMATCHER_CONFIG     Override where engine_config.yaml is expected

EXAMPLES
  $0                            # fresh install
  $0 --upgrade                  # upgrade to latest PyPI release
  EDUMATCHER_DATA_DIR=~/session $0   # install and initialise a custom session dir
EOF
    exit 0
fi

echo ""
echo "========================================"
echo "  EduMatcher Runtime Installer"
echo "========================================"
echo ""

# -----------------------------------------------------------------------
# 1. Check Python version
# -----------------------------------------------------------------------
info "Checking Python version..."
PYTHON_BIN=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        version_output=$("$candidate" --version 2>&1 | awk '{print $2}')
        major=$(echo "$version_output" | cut -d. -f1)
        minor=$(echo "$version_output" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge "$MIN_PYTHON_MINOR" ]; then
            PYTHON_BIN="$candidate"
            ok "Python ${version_output} found at $(command -v $candidate)"
            break
        fi
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    err "Python 3.${MIN_PYTHON_MINOR}+ is required but not found."
    echo ""
    echo "  Install Python 3.${MIN_PYTHON_MINOR}+ from https://python.org/downloads"
    echo "  or via your system package manager, then re-run this script."
    exit 1
fi

# -----------------------------------------------------------------------
# 2. Ensure pipx is available
# -----------------------------------------------------------------------
info "Checking pipx..."
if command -v pipx &>/dev/null; then
    ok "pipx $(pipx --version) found at $(command -v pipx)"
else
    warn "pipx not found — installing it now..."
    if command -v brew &>/dev/null; then
        brew install pipx
        pipx ensurepath
    elif command -v apt-get &>/dev/null; then
        sudo apt-get install -y pipx
        pipx ensurepath
    else
        "$PYTHON_BIN" -m pip install --user pipx
        "$PYTHON_BIN" -m pipx ensurepath
    fi
    # After install pipx may not be in PATH yet in this shell
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v pipx &>/dev/null; then
        err "pipx installation succeeded but it is not on PATH."
        echo "  Add ~/.local/bin to your PATH, open a new shell, and re-run."
        exit 1
    fi
    ok "pipx installed successfully"
fi

# -----------------------------------------------------------------------
# 3. Install / upgrade EduMatcher
# -----------------------------------------------------------------------
info "Installing ${PACKAGE} via pipx..."
if [ "$UPGRADE" = true ]; then
    pipx install "${PACKAGE}" --force
else
    if pipx list | grep -q "package ${PACKAGE}"; then
        ok "${PACKAGE} is already installed"
        info "Use --upgrade to force reinstall."
    else
        pipx install "${PACKAGE}"
    fi
fi

# Verify the key commands are on PATH
if ! command -v pm-engine &>/dev/null; then
    warn "pm-engine is not yet on PATH."
    info "Run:  pipx ensurepath  then open a new terminal."
else
    ok "pm-engine available at $(command -v pm-engine)"
fi

# -----------------------------------------------------------------------
# 4. Run pm-setup to initialise session directory
# -----------------------------------------------------------------------
echo ""
info "Initialising session directory..."
pm-setup ${EDUMATCHER_DATA_DIR:+--data-dir "$EDUMATCHER_DATA_DIR"}

# -----------------------------------------------------------------------
# 5. Final checklist
# -----------------------------------------------------------------------
echo ""
echo "========================================"
echo "  Next steps"
echo "========================================"
echo ""
echo "  1. Copy the shell snippet above into your profile (~/.zshrc or ~/.bashrc)"
echo "     so every new terminal inherits the correct EDUMATCHER_DATA_DIR."
echo ""
echo "  2. Edit engine_config.yaml in your working directory:"
echo "     - Add student gateway IDs under gateways.alf"
echo "     - Add symbols and their seed quotes"
echo ""
echo "  3. Verify the config:"
echo "     pm-admin-cli status"
echo ""
echo "  4. Start the exchange:"
echo "     pm-engine --verbose         # terminal 1"
echo "     pm-scheduler                # terminal 2 (optional)"
echo "     pm-gateway --id TRADER01    # terminal 3"
echo ""
echo "  Full classroom launcher (macOS):"
echo "     tools/launch_all.sh"
echo ""
